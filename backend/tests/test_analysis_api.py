"""Checks for the owner-only role analysis of a completed game."""

import asyncio
from functools import partial
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

import httpx

from test_web_api import fixture_model
from web_backend.app import create_app


MOVE_QUOTE = "Готовы выделить 30 млн ₽ на реконструкцию"
REACTION_QUOTE = "Готовы обсуждать ваш взнос при условии подвоза воды"
OBSERVATION = "Город обозначил свой взнос, а обсуждение этой суммы связалось с подвозом воды."
EXCERPT = "Сначала назови предельный взнос города."
STRATEGY = f"{EXCERPT} Затем обсуди условия реконструкции."
SUGGESTION = "Назови свой взнос вместе с предложением о подвозе воды и попроси ответить на оба условия."


class AnalysisAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        provider = await self.enterAsyncContext(httpx.AsyncClient(transport=httpx.MockTransport(self.reply)))
        app = create_app(runs_dir=Path(directory.name), images=False, embedding_base_url="",
                         model_factory=partial(fixture_model, provider))
        self.transport = httpx.ASGITransport(app=app)
        self.api = await self.enterAsyncContext(httpx.AsyncClient(transport=self.transport, base_url="http://city.test"))
        await self.enterAsyncContext(app.router.lifespan_context(app))
        created = await self.api.post("/api/v1/games", headers=self.key())
        self.assertEqual(created.status_code, 201, created.text)
        self.draft = created.json()
        self.path = f"/api/v1/games/{self.draft['game_id']}"
        self.role_id = self.draft["scenario"]["role_order"][0]
        self.model_reply = {
            "references": [{"message_id": "1", "quote": MOVE_QUOTE}, {"message_id": "2", "quote": REACTION_QUOTE}],
            "observation": OBSERVATION,
            "strategy_excerpt": EXCERPT,
            "suggested_strategy": SUGGESTION,
        }

    @staticmethod
    def key():
        return {"Idempotency-Key": uuid4().hex}

    async def reply(self, request):
        if self.model_reply is None:
            return httpx.Response(503, json={"error": {"message": "fixture outage"}})
        body = json.loads(request.content)
        name = body["tools"][0]["function"]["name"]
        return httpx.Response(200, json={"id": "fixture", "object": "chat.completion", "created": 0,
            "model": "fixture", "choices": [{"index": 0, "finish_reason": "tool_calls",
                "message": {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "fixture", "type": "function", "function": {
                        "name": name, "arguments": json.dumps(self.model_reply, ensure_ascii=False)}}]}}]})

    async def wait_for(self, condition):
        async with asyncio.timeout(10):
            while True:
                response = await self.api.get(self.path)
                self.assertEqual(response.status_code, 200, response.text)
                game = response.json()
                if condition(game):
                    return game
                self.assertNotIn(game["status"], {"failed", "cancelled"}, game["error"])
                await asyncio.sleep(0.01)

    async def complete_game(self):
        roles = [{"role_id": role_id, "control_mode": "human", "pledged_rub": 0, "conditions": {},
                  "strategy": STRATEGY if role_id == self.role_id else None}
                 for role_id in self.draft["scenario"]["role_order"]]
        saved = await self.api.put(self.path + "/settings", json={"roles": roles})
        self.assertEqual(saved.status_code, 200, saved.text)
        started = await self.api.post(self.path + "/start", headers=self.key())
        self.assertEqual(started.status_code, 200, started.text)
        previous = None
        speeches = [f"{MOVE_QUOTE}. Предлагаем это для начала обсуждения.", f"{REACTION_QUOTE}."]
        speeches += ["Подтверждаю позицию своей стороны."] * 13
        inputs = [{"type": "speech", "content": speech} for speech in speeches]
        inputs += [{"type": "vote", "vote": "for"}] * 5
        for entry in inputs:
            state = await self.wait_for(lambda game: game["pending_input"] and game["pending_input"]["input_id"] != previous)
            previous = state["pending_input"]["input_id"]
            accepted = await self.api.post(f"{self.path}/inputs/{previous}", headers=self.key(), json=entry)
            self.assertEqual(accepted.status_code, 200, accepted.text)
        return await self.wait_for(lambda game: game["status"] == "completed")

    async def analyze(self, *, role_id=None, client=None):
        return await (client or self.api).post(self.path + "/analysis", json={"role_id": role_id or self.role_id})

    async def test_completed_game_analysis_cites_actual_messages_and_strategy(self):
        completed = await self.complete_game()
        response = await self.analyze()
        self.assertEqual(response.status_code, 200, response.text)
        analysis = response.json()
        self.assertEqual(analysis["role_id"], self.role_id)
        self.assertEqual(analysis["references"], [
            {"message_id": completed["messages"][0]["message_id"], "quote": MOVE_QUOTE},
            {"message_id": completed["messages"][1]["message_id"], "quote": REACTION_QUOTE},
        ])
        self.assertIn(MOVE_QUOTE, analysis["paragraph"])
        self.assertIn(REACTION_QUOTE, analysis["paragraph"])
        self.assertIn(OBSERVATION, analysis["paragraph"])
        self.assertEqual(analysis["paragraph"].splitlines(), [analysis["paragraph"]])
        self.assertEqual(analysis["strategy_excerpt"], EXCERPT)
        self.assertEqual(analysis["suggested_strategy"], SUGGESTION)

    async def test_unverified_amount_from_model_does_not_change_result(self):
        completed = await self.complete_game()
        self.model_reply["suggested_strategy"] = "Сразу предложи городу взнос 90 млн ₽."
        with self.assertLogs("web_backend.analysis_api", level="WARNING"):
            response = await self.analyze()

        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(response.json()["code"], "ANALYSIS_FAILED")
        self.assertEqual((await self.api.get(self.path)).json(), completed)

    async def test_analysis_requires_owner_and_completed_game(self):
        draft = await self.analyze()
        self.assertEqual(draft.status_code, 409, draft.text)
        self.assertEqual(draft.json()["code"], "ANALYSIS_UNAVAILABLE")
        await self.complete_game()
        async with httpx.AsyncClient(transport=self.transport, base_url="http://city.test") as stranger:
            denied = await self.analyze(client=stranger)
        self.assertEqual(denied.status_code, 404, denied.text)
        self.assertEqual(denied.json()["code"], "GAME_NOT_FOUND")
        unknown_role = await self.analyze(role_id="unknown_role")
        self.assertEqual(unknown_role.status_code, 404, unknown_role.text)
        self.assertEqual(unknown_role.json()["code"], "ROLE_NOT_FOUND")

    async def test_invalid_evidence_and_provider_failure_allow_another_analysis(self):
        completed = await self.complete_game()
        valid = self.model_reply
        first, reaction = valid["references"]
        later_own_move = {"message_id": completed["messages"][5]["message_id"],
                          "quote": "Подтверждаю позицию своей стороны"}
        invalid_replies = {
            "unknown id": {**valid, "references": [{**first, "message_id": "99"}, reaction]},
            "inexact quote": {**valid, "references": [{**first, "quote": "выделим 30 млн ₽"}, reaction]},
            "wrong author": {**valid, "references": [reaction]},
            "own reaction": {**valid, "references": [first, later_own_move]},
            "early reaction": {**valid, "references": [later_own_move, reaction]},
            "invalid excerpt": {**valid, "strategy_excerpt": "Сначала назови предельный взнос региона."},
            "provider outage": None,
        }
        for case, model_reply in invalid_replies.items():
            with self.subTest(case=case):
                self.model_reply = model_reply
                with self.assertLogs("web_backend.analysis_api", level="WARNING"):
                    failure = await self.analyze()
                self.assertEqual(failure.status_code, 502, failure.text)
                self.assertEqual(failure.json()["code"], "ANALYSIS_FAILED")
                self.assertEqual((await self.api.get(self.path)).json(), completed)
        self.model_reply = valid
        self.assertEqual((await self.analyze()).status_code, 200)

    async def test_analysis_can_return_just_one_move_without_a_strategy_change(self):
        completed = await self.complete_game()
        reference = self.model_reply["references"][1]
        observation = "Условие о подвозе воды обозначило, при каких обстоятельствах сторона готова обсудить взнос."
        self.model_reply = {"references": [reference], "observation": observation,
                            "strategy_excerpt": "", "suggested_strategy": ""}
        response = await self.analyze(role_id=completed["messages"][1]["role_id"])
        self.assertEqual(response.status_code, 200, response.text)
        analysis = response.json()
        self.assertEqual(analysis["references"], [reference])
        self.assertIn(observation, analysis["paragraph"])
        self.assertIsNone(analysis["strategy_excerpt"])
        self.assertIsNone(analysis["suggested_strategy"])
