"""End-to-end coverage of the browser contract without a model provider."""

import asyncio
from contextlib import nullcontext
from functools import partial
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx

from test_web_api import fixture_model, tool_reply
from web_backend.app import create_app
from web_backend.sessions import COOKIE, SessionStore, now


class InteractiveAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.runs = Path(directory.name)
        self.ai = None
        self.app = create_app(runs_dir=self.runs, images=False, embedding_base_url="", model_factory=self.model_factory)
        self.transport = httpx.ASGITransport(app=self.app)
        self.api = await self.enterAsyncContext(httpx.AsyncClient(transport=self.transport, base_url="http://city.test"))
        await self.enterAsyncContext(self.app.router.lifespan_context(self.app))

    def model_factory(self, *args):
        if self.ai is None:
            self.fail("A human role must never initialize a model")
        return self.ai(*args)

    async def post(self, path, body=None, key=None, client=None):
        return await (client or self.api).post(f"/api/v1/games{path}", json=body,
                                              headers={"Idempotency-Key": key or uuid4().hex})

    async def snapshot(self):
        response = await self.api.get(f"/api/v1/games{self.path}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def wait_for(self, condition):
        async with asyncio.timeout(10):
            while True:
                state = await self.snapshot()
                if condition(state):
                    return state
                self.assertNotIn(state["status"], ("failed", "cancelled"), state.get("error"))
                await asyncio.sleep(0.01)

    async def test_rejection_calculates_city_result_and_supports_retry(self):
        await self.play(accepted=False, result_failure=True)

    async def test_unanimous_vote_applies_protocol(self):
        await self.play(accepted=True, result_failure=False)

    async def test_ai_instruction_reaches_next_speech_and_pause_waits_for_it(self):
        started, finish = asyncio.Event(), asyncio.Event()
        observed = []
        marker = "Отдельная инструкция для следующего хода"

        async def reply(request):
            body = json.loads(request.content)
            observed.extend(message["content"] for message in body["messages"])
            started.set()
            await finish.wait()
            return tool_reply({"speech": "Позиция AI-роли.",
                               "own_contribution": {"action": "unchanged", "amount_millions": 0},
                               "own_conditions": [], "pledge_demands": [], "condition_demands": [],
                               "responses": [], "withdrawn_demands": [], "addressed_to": "everyone", "vote": "none"})

        # Put the AI after a human in the test so the instruction can arrive before generation.
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as provider, asyncio.timeout(10):
            self.ai = partial(fixture_model, provider)
            draft = (await self.post("")).json()
            self.path = "/" + draft["game_id"]
            roles = draft["settings"]["roles"]
            ai_role = roles[1]["role_id"]
            for role in roles:
                role.pop("spent_on_conditions_rub")
                role["control_mode"] = "ai" if role["role_id"] == ai_role else "human"
            settings = await self.api.put(f"/api/v1/games{self.path}/settings", json={"roles": roles})
            self.assertEqual(settings.status_code, 200, settings.text)
            await self.post(self.path + "/start")
            human = await self.wait_for(lambda view: view["pending_input"])
            command = await self.post(self.path + f"/roles/{ai_role}/instructions", {"content": marker})
            self.assertEqual(command.json()["applies_to"], "next_unstarted_speech")
            await self.post(self.path + f"/inputs/{human['pending_input']['input_id']}",
                            {"type": "speech", "content": "Начальная позиция."})
            await started.wait()
            self.assertTrue(any(marker in message for message in observed))
            paused = await self.post(self.path + "/pause")
            self.assertEqual(paused.json()["pause_state"], "requested")
            finish.set()
            paused = await self.wait_for(lambda view: view["pause_state"] == "paused")
            self.assertEqual(len(paused["messages"]), 2)
            self.assertIsNone(paused["pending_input"])
            cancelled = await self.post(self.path + "/cancel")
            self.assertEqual(cancelled.json()["status"], "cancelled")

    async def play(self, *, accepted, result_failure):
        key = uuid4().hex
        created = await self.post("", key=key)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertIn("HttpOnly", created.headers["set-cookie"])
        draft = created.json()
        self.path = "/" + draft["game_id"]
        self.assertEqual(draft["status"], "draft")
        self.assertEqual((await self.post(self.path + "/start")).json()["code"], "SETTINGS_REQUIRED")
        async with httpx.AsyncClient(transport=self.transport, base_url="http://city.test") as stranger:
            self.assertEqual((await stranger.get(f"/api/v1/games{self.path}")).status_code, 404)
            # The first response might have been lost before the browser got its cookie.
            repeated = await self.post("", key=key, client=stranger)
            self.assertEqual(repeated.json()["game_id"], draft["game_id"])
            self.assertEqual(stranger.cookies[COOKIE], self.api.cookies[COOKIE])

        roles = draft["settings"]["roles"]
        for role in roles:
            role.pop("spent_on_conditions_rub")
            role["control_mode"] = "human"
            if role["role_id"] == "city_administration":
                role["conditions"]["water_supply"] = True
                role["pledged_rub"] = 30_000_000

        invalid = [*roles[:-1], {**roles[-1], "conditions": {"water_supply": True}}]
        response = await self.api.put(f"/api/v1/games{self.path}/settings", json={"roles": invalid})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["field_errors"][0]["path"], ["roles", 4, "conditions", "water_supply"])
        response = await self.api.put(f"/api/v1/games{self.path}/settings", json={"roles": roles})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["settings"]["roles"][0]["spent_on_conditions_rub"], 20_000_000)

        start = await self.post(self.path + "/start")
        self.assertEqual(start.status_code, 200, start.text)
        self.assertEqual((await self.post(self.path + "/start")).status_code, 200)
        phases = []
        previous = None
        for index in range(15):
            state = await self.wait_for(lambda view: view["pending_input"] and view["pending_input"]["input_id"] != previous)
            phases.append(state["phase"])
            pending = state["pending_input"]
            message = {"type": "speech", "content": f"Выступление {index + 1}"}
            path = f"{self.path}/inputs/{pending['input_id']}"
            if index == 0:
                # A new browser tab using the owner cookie sees the same pending action.
                async with httpx.AsyncClient(transport=self.transport, base_url="http://city.test",
                                             cookies={COOKIE: self.api.cookies[COOKIE]}) as reopened:
                    reopened_state = await reopened.get(f"/api/v1/games{self.path}")
                    self.assertEqual(reopened_state.json()["pending_input"], pending)
                paused = await self.post(self.path + "/pause")
                self.assertEqual(paused.json()["pause_state"], "paused")
                paused_vote = await self.post(path, message)
                self.assertEqual(paused_vote.json()["code"], "GAME_PAUSED", paused_vote.text)
                resumed = await self.post(self.path + "/continue")
                self.assertEqual(resumed.json()["pending_input"], pending)
            key = uuid4().hex
            response = await self.post(path, message, key)
            self.assertEqual(response.status_code, 200, response.text)
            if index == 0:
                self.assertEqual((await self.post(path, message, key)).json(), response.json())
                self.assertEqual((await self.post(path, message)).status_code, 409)
            previous = pending["input_id"]
        self.assertEqual(phases, ["positions"] * 5 + ["negotiation"] * 5 + ["amendments"] * 5)

        from web_backend.sessions import projection

        def calculate(*args, **kwargs):
            if result_failure and kwargs["basis"] != "proposed_protocol":
                raise RuntimeError("simulated failure")
            return projection(*args, **kwargs)

        log = self.assertLogs("web_backend.sessions", level="ERROR") if result_failure else nullcontext()
        with patch("web_backend.sessions.projection", side_effect=calculate), log:
            for index in range(5):
                state = await self.wait_for(lambda view: view["pending_input"] and view["pending_input"]["input_id"] != previous)
                self.assertEqual(state["phase"], "voting")
                self.assertIsNone(state["vote_summary"])
                self.assertEqual(state["forecast"]["protocol_version"], state["protocol"]["version"])
                pending = state["pending_input"]
                self.assertEqual(pending["type"], "vote")
                response = await self.post(f"{self.path}/inputs/{pending['input_id']}", {
                    "type": "vote", "vote": "against" if not accepted and index == 1 else "for"})
                self.assertEqual(response.status_code, 200, response.text)
                previous = pending["input_id"]

            if result_failure:
                failed = await self.wait_for(lambda view: view["status"] == "failed")
                self.assertEqual(failed["error"]["code"], "RESULT_FAILED")
                self.assertIsNone(failed["result"])
                self.assertEqual(failed["vote_summary"]["for"], 4)

        if result_failure:
            response = await self.post(self.path + "/retry-result")
            self.assertEqual(response.status_code, 200, response.text)
        final = await self.wait_for(lambda view: view["status"] == "completed")
        self.assertEqual(len(final["messages"]), 15)
        self.assertEqual(final["protocol_status"], "accepted" if accepted else "rejected")
        self.assertEqual(final["vote_summary"]["for"], 5 if accepted else 4)
        self.assertEqual(final["result"]["basis"], "accepted_protocol" if accepted else "no_agreement")
        self.assertEqual(final["result"]["outcome_title"], "Недострой" if accepted else "Каждый сам за себя")
        self.assertEqual(final["result"]["model_version"], 3)
        self.assertEqual(final["result"]["financial_load"][0]["committed_rub"], 50_000_000)
        self.assertEqual(final["result"]["executed_rub"], 30_000_000 if accepted else 0)
        self.assertEqual(len(final["result"]["indicators"]), 5)

        events = []
        cursor = 0
        while True:
            response = await self.api.get(f"/api/v1/games{self.path}/events?after={cursor}")
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            events.extend(data["events"])
            cursor = data["next_cursor"]
            if not data["has_more"]:
                break
        self.assertEqual(cursor, final["last_event_id"])
        self.assertEqual([event["event_id"] for event in events], list(range(1, cursor + 1)))
        self.assertEqual(sum(event["type"] == "vote.closed" for event in events), 1)
        self.assertEqual(events[-1]["type"], "game.completed")
        stored = SessionStore(self.runs).get(final["game_id"])
        self.assertEqual(stored["snapshot"]["result"], final["result"])
        if not accepted:
            stored["snapshot"]["result"].update(model_version=2, herald_text="Прежний формат газеты.")
            SessionStore(self.runs).save(stored)
            restored = await self.snapshot()
            self.assertEqual(restored["result"], final["result"])
            self.assertEqual(restored["vote_summary"], final["vote_summary"])
            stored["result_input"] = {"status": "completed"}
            SessionStore(self.runs).save(stored)
            with self.assertLogs("web_backend.sessions", level="WARNING"):
                fallback = await self.snapshot()
            self.assertEqual(fallback["result"]["herald_text"], "Прежний формат газеты.")
            self.assertEqual(fallback["result"]["model_version"], 2)
        stored["snapshot"]["expires_at"] = now().isoformat()
        SessionStore(self.runs).save(stored)
        self.assertEqual((await self.api.get(f"/api/v1/games{self.path}")).status_code, 404)
