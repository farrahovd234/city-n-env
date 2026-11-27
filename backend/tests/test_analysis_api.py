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
MOVE_TEXT = f"{MOVE_QUOTE}. Предлагаем это для начала обсуждения."
REACTION_TEXT = f"{REACTION_QUOTE}."
POSITION_TEXT = "Подтверждаю позицию своей стороны."
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
                         model_factory=partial(fixture_model, provider), game_options={"request_timeout_seconds": 6})
        self.transport = httpx.ASGITransport(app=app)
        self.api = await self.enterAsyncContext(httpx.AsyncClient(transport=self.transport, base_url="http://city.test"))
        await self.enterAsyncContext(app.router.lifespan_context(app))
        created = await self.api.post("/api/v1/games", headers=self.key())
        self.assertEqual(created.status_code, 201, created.text)
        self.draft = created.json()
        self.path = f"/api/v1/games/{self.draft['game_id']}"
        self.role_id = self.draft["scenario"]["role_order"][0]
        self.provider_payloads = []
        self.replies_by_move = {}
        self.slow_moves = set()
        self.model_reply = {
            "move_id": "1", "reply_id": "2",
            "observation": OBSERVATION,
            "verdict": "improve",
            "next_reply": "Готовы выделить 30 млн ₽. Какую гарантию по подвозу воды вы предлагаете?",
            "strategy_excerpt": EXCERPT,
            "suggested_strategy": SUGGESTION,
        }

    @staticmethod
    def key():
        return {"Idempotency-Key": uuid4().hex}

    async def reply(self, request):
        body = json.loads(request.content)
        payload = json.loads(body["messages"][-1]["content"])
        self.provider_payloads.append(payload)
        target = payload["target_move_id"]
        if target in self.slow_moves:
            await asyncio.Event().wait()
        replies = self.replies_by_move.get(target)
        if replies:
            model_reply = replies.pop(0)
        elif target == "1":
            model_reply = self.model_reply
        else:
            model_reply = {"move_id": target, "reply_id": "", "observation": "Сторона подтвердила свою позицию.",
                           "verdict": "keep", "next_reply": "", "strategy_excerpt": "", "suggested_strategy": ""}
        if model_reply is None:
            return httpx.Response(503, json={"error": {"message": "fixture outage"}})
        name = body["tools"][0]["function"]["name"]
        return httpx.Response(200, json={"id": "fixture", "object": "chat.completion", "created": 0,
            "model": "fixture", "choices": [{"index": 0, "finish_reason": "tool_calls",
                "message": {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "fixture", "type": "function", "function": {
                        "name": name, "arguments": json.dumps(model_reply, ensure_ascii=False)}}]}}]})

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

    async def complete_game(self, speeches=None):
        roles = [{"role_id": role_id, "control_mode": "human", "pledged_rub": 0, "conditions": {},
                  "strategy": STRATEGY if role_id == self.role_id else None}
                 for role_id in self.draft["scenario"]["role_order"]]
        saved = await self.api.put(self.path + "/settings", json={"roles": roles})
        self.assertEqual(saved.status_code, 200, saved.text)
        started = await self.api.post(self.path + "/start", headers=self.key())
        self.assertEqual(started.status_code, 200, started.text)
        previous = None
        if speeches is None:
            speeches = [MOVE_TEXT, REACTION_TEXT, *([POSITION_TEXT] * 13)]
        inputs = [{"type": "speech", "content": speech} for speech in speeches]
        inputs += [{"type": "vote", "vote": "for"}] * 5
        for entry in inputs:
            state = await self.wait_for(lambda game: game["pending_input"] and game["pending_input"]["input_id"] != previous)
            previous = state["pending_input"]["input_id"]
            accepted = await self.api.post(f"{self.path}/inputs/{previous}", headers=self.key(), json=entry)
            self.assertEqual(accepted.status_code, 200, accepted.text)
        return await self.wait_for(lambda game: game["status"] == "completed")

    async def analyze(self, *, role_id=None, client=None, message_ids=None, complete_from_journal=False):
        body = {"role_id": role_id or self.role_id}
        if message_ids is not None:
            body["message_ids"] = message_ids
        if complete_from_journal:
            body["complete_from_journal"] = True
        return await (client or self.api).post(self.path + "/analysis", json=body)

    async def test_completed_game_analysis_cites_actual_messages_and_strategy(self):
        completed = await self.complete_game()
        response = await self.analyze()
        self.assertEqual(response.status_code, 200, response.text)
        analysis = response.json()
        self.assertEqual(analysis["message_ids"], ["1", "6", "11"])
        self.assertEqual(analysis["missing_message_ids"], [])
        self.assertEqual([finding["references"][0]["message_id"] for finding in analysis["findings"]],
                         analysis["message_ids"])
        self.assertEqual({payload["target_move_id"] for payload in self.provider_payloads}, {"1", "6", "11"})
        for payload in self.provider_payloads:
            self.assertEqual(payload["strategy"], STRATEGY)
            self.assertEqual(payload["messages"], completed["messages"])
        self.assertEqual(analysis["role_id"], self.role_id)
        self.assertEqual(analysis["references"], [{"message_id": "1", "quote": MOVE_TEXT},
                                                  {"message_id": "2", "quote": REACTION_TEXT}])
        self.assertIn(MOVE_QUOTE, analysis["paragraph"])
        self.assertIn(REACTION_QUOTE, analysis["paragraph"])
        self.assertEqual(analysis["observation"], OBSERVATION)
        self.assertEqual(analysis["strategy_excerpt"], EXCERPT)
        self.assertEqual(analysis["suggested_strategy"], SUGGESTION)
        self.assertEqual(analysis["findings"][0]["next_reply"], self.model_reply["next_reply"])

    async def test_residents_keep_verified_moves_when_one_repeatedly_fails_numeric_validation(self):
        completed = await self.complete_game()
        residents = "city_residents"
        moves = [message["message_id"] for message in completed["messages"] if message["role_id"] == residents]
        broken = {"move_id": moves[1], "reply_id": "", "observation": "Предложено внести 90 млн ₽.",
                  "verdict": "keep", "next_reply": "", "strategy_excerpt": "", "suggested_strategy": ""}
        self.replies_by_move[moves[1]] = [broken, broken]
        with self.assertLogs("web_backend.analysis_api", level="WARNING"):
            response = await self.analyze(role_id=residents)
        self.assertEqual(response.status_code, 200)
        analysis = response.json()
        self.assertEqual(analysis["message_ids"], moves)
        self.assertEqual(analysis["missing_message_ids"], moves[1:2])
        self.assertEqual([finding["references"][0]["message_id"] for finding in analysis["findings"]],
                         [moves[0], moves[2]])
        self.provider_payloads.clear()
        retry = await self.analyze(role_id=residents, message_ids=analysis["missing_message_ids"])
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json()["missing_message_ids"], [])
        self.assertEqual([payload["target_move_id"] for payload in self.provider_payloads], moves[1:2])
        self.assertEqual((await self.api.get(self.path)).json(), completed)

    async def test_retry_uses_verified_second_answer_for_same_move(self):
        await self.complete_game()
        self.replies_by_move["1"] = [dict(self.model_reply, move_id="99"), self.model_reply]
        answer = await self.analyze(message_ids=["1"])
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(answer.json()["references"][0], {"message_id": "1", "quote": MOVE_TEXT})
        self.assertEqual([payload["target_move_id"] for payload in self.provider_payloads], ["1", "1"])

    async def test_final_retry_can_review_a_copied_speech_from_the_journal(self):
        copied = ("Заморозить тарифы и разделить ответственность — это основа доверия. "
                  "Наш вклад — не более 30 млн, остальное за счёт региона и холдинга.")
        speeches = [copied, *([POSITION_TEXT] * 13),
                    f"{copied} Открытые датчики 24/7 — обязательно."]
        await self.complete_game(speeches)
        self.replies_by_move["15"] = [None]
        response = await self.analyze(role_id="environmental_ngo", message_ids=["15"], complete_from_journal=True)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["missing_message_ids"], [])
        finding, = response.json()["findings"]
        self.assertIn("дословно повторяет", finding["observation"])
        self.assertEqual([reference["message_id"] for reference in finding["references"]], ["15", "1"])
        self.assertEqual([data["target_move_id"] for data in self.provider_payloads], ["15"])

    async def test_slow_move_does_not_consume_the_other_moves_time(self):
        await self.complete_game()
        self.slow_moves.add("1")
        response = await self.analyze()
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()
        self.assertEqual(report["missing_message_ids"], ["1"])
        self.assertEqual([finding["references"][0]["message_id"] for finding in report["findings"]], ["6", "11"])

    async def test_analysis_requires_owner_completed_game_and_owned_target(self):
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
        wrong_target = await self.analyze(message_ids=["2"])
        self.assertEqual(wrong_target.status_code, 422, wrong_target.text)
        self.assertEqual(wrong_target.json()["code"], "INVALID_ANALYSIS_TARGET")
        self.assertEqual(self.provider_payloads, [])

    async def test_unavailable_or_invalid_move_is_reported_as_missing(self):
        await self.complete_game()
        for model_reply in (None, dict(self.model_reply, reply_id="6"), dict(self.model_reply, next_reply=""),
                            dict(self.model_reply, next_reply="Готовы вложить 30 млрд ₽.")):
            with self.subTest(model_reply=model_reply):
                self.replies_by_move["1"] = [model_reply, model_reply]
                with self.assertLogs("web_backend.analysis_api", level="WARNING"):
                    response = await self.analyze(message_ids=["1"])
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["missing_message_ids"], ["1"])
                self.assertEqual(response.json()["findings"], [])

    async def test_unverified_strategy_edit_does_not_hide_the_observation(self):
        await self.complete_game()
        for invalid in (dict(self.model_reply, strategy_excerpt="Неизвестная стратегия."),
                        dict(self.model_reply, suggested_strategy="Город внесёт 90 млн ₽.")):
            with self.subTest(invalid=invalid):
                self.replies_by_move["1"] = [invalid]
                response = await self.analyze(message_ids=["1"])
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                self.assertEqual(result["observation"], OBSERVATION)
                self.assertEqual(result["missing_message_ids"], [])
                self.assertIsNone(result["strategy_excerpt"])
                self.assertIsNone(result["suggested_strategy"])
