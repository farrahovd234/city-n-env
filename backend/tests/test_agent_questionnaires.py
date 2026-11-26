"""HTTP lifecycle tests using a deterministic model provider fixture."""

import asyncio
from copy import deepcopy
from functools import partial
import json
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx

from test_web_api import PAUSE, fixture_model, tool_reply
from web_backend.app import create_app


ROOT = "/api/v1/games"
CONTRIBUTIONS = {
    "city_administration": 10,
    "industrial_holding": 170,
    "regional_government": 90,
    "city_residents": 0,
    "environmental_ngo": 0,
}
ROUNDS = ["positions", "negotiation", "amendments"]
CUSTOM = "Предложите еженедельную сверку плана реконструкции."


class AgentQuestionnaireTests(unittest.IsolatedAsyncioTestCase):
    async def test_automatic_answers_start_a_readonly_game(self):
        await self.play("automatic")

    async def test_manual_answers_set_owned_conditions_and_enforce_contribution_limits(self):
        await self.play("manual")

    async def play(self, mode):
        model_started, let_model_reply = asyncio.Event(), asyncio.Event()
        provider_prompts = {}

        async def reply(request):
            body = json.loads(request.content)
            role = body["model"]
            provider_prompts.setdefault(role, []).extend(message["content"] for message in body["messages"])
            voting = body["tools"][0]["function"]["parameters"]["properties"]["vote"]["enum"] != ["none"]
            model_started.set()
            await let_model_reply.wait()
            condition = {"city_administration": "water_supply", "environmental_ngo": "open_sensors"}.get(role)
            city_opening = role == "city_administration" and any(
                "ИДЕТ ЭТАП 1:" in message["content"] for message in body["messages"])
            return tool_reply({
                "speech": f"Позиция стороны {role}.",
                "own_contribution": {"action": "unchanged" if voting else "set",
                                     "amount_millions": 0 if voting else 20 if city_opening else CONTRIBUTIONS[role]},
                "own_conditions": [
                    {"lever_id": condition, "value_json": "false" if city_opening and mode == "manual" else "true"}
                ] if condition and not voting else [],
                "pledge_demands": [], "condition_demands": [], "responses": [], "withdrawn_demands": [],
                "addressed_to": "everyone", "vote": "for" if voting else "none",
            })

        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(reply)) as provider,
            asyncio.timeout(10),
        ):
            with tempfile.TemporaryDirectory() as directory:
                app = create_app(runs_dir=directory, model_factory=partial(fixture_model, provider),
                                 images=False, embedding_base_url="")
                async with (
                    app.router.lifespan_context(app),
                    httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://city.test") as api,
                ):
                    created = await api.post(ROOT, headers={"Idempotency-Key": uuid4().hex})
                    self.assertEqual(created.status_code, 201, created.text)
                    path = created.headers["Location"]
                    draft = created.json()
                    scenario = draft["scenario"]
                    self.assertEqual(scenario["max_dialogue_messages"], 15)
                    questionnaires = scenario["questionnaires"]
                    self.assertEqual(list(questionnaires), list(CONTRIBUTIONS))
                    self.assertEqual([len(row["fields"]) for row in questionnaires.values()], [9, 9, 8, 6, 5])
                    for questionnaire in questionnaires.values():
                        optional = questionnaire["fields"][-1]
                        self.assertEqual(optional["id"], "custom_instructions")
                        self.assertFalse(optional["required"])
                        self.assertEqual(optional["options"], [])
                    saved = await api.put(path + "/settings", json={"mode": "automatic"})
                    self.assertEqual(saved.status_code, 200, saved.text)
                    expected = {role_id: questionnaire["defaults"] for role_id, questionnaire in questionnaires.items()}
                    if mode == "manual":
                        expected["city_administration"].update(water_supply=True, comfort_money=10, max_money=10,
                                                               custom_instructions=CUSTOM)
                        expected["city_residents"].update(water_supply=False, open_sensors=False, protest_moratorium=True)
                        expected["industrial_holding"].update(start_money=140)
                        await self.assert_invalid_answers(api, path, expected)
                        saved = await api.put(path + "/settings", json={"mode": mode, "answers": expected})
                        self.assertEqual(saved.status_code, 200, saved.text)
                    configured = saved.json()
                    self.assertEqual(configured["status"], "draft")
                    self.assertEqual(configured["settings"]["setup_mode"], mode)
                    self.assertEqual(configured["messages"], [])
                    for role in configured["settings"]["roles"]:
                        self.assertEqual(role["answers"], expected[role["role_id"]])
                        self.assertEqual(role["control_mode"], "ai")
                        self.assertEqual(role["strategy"].count("\n["), 3)
                    if mode == "manual":
                        city, holding, _, residents, ngo = configured["settings"]["roles"]
                        self.assertEqual(city["conditions"], {"tariffs_freeze": True, "water_supply": True})
                        self.assertEqual(city["spent_on_conditions_rub"], 20_000_000)
                        self.assertEqual(holding["pledged_rub"], 140_000_000)
                        self.assertEqual(holding["conditions"], {"plant_mode": "100%", "timeline": 36})
                        self.assertEqual(residents["conditions"], {"protest_moratorium": False})
                        self.assertEqual(ngo["conditions"], {"open_sensors": True})

                    with patch("asyncio.sleep", new=AsyncMock()):
                        launched = await api.post(path + "/start", headers={"Idempotency-Key": uuid4().hex})
                        self.assertEqual(launched.status_code, 200, launched.text)
                        await model_started.wait()
                        running = (await api.get(path)).json()
                        self.assertNotIn("add_instruction", running["available_actions"])
                        instruction = await api.post(path + "/roles/city_administration/instructions",
                                                     json={"content": "Измените свою стратегию"},
                                                     headers={"Idempotency-Key": uuid4().hex})
                        self.assertEqual(instruction.status_code, 409, instruction.text)
                        self.assertEqual(instruction.json()["code"], "INSTRUCTION_UNAVAILABLE")
                        written = await api.post(path + "/inputs/previous", json={"type": "speech", "content": "Реплика"},
                                                 headers={"Idempotency-Key": uuid4().hex})
                        self.assertEqual(written.status_code, 409, written.text)
                        let_model_reply.set()
                        while True:
                            final = (await api.get(path)).json()
                            self.assertNotEqual(final["status"], "failed", final.get("error"))
                            if final["status"] == "completed":
                                break
                            await PAUSE(0.01)

                    messages = final["messages"]
                    self.assertEqual(len(messages), 15)
                    self.assertEqual([row["phase"] for row in messages], [phase for phase in ROUNDS for _ in range(5)])
                    self.assertEqual([row["role_id"] for row in messages], list(CONTRIBUTIONS) * 3)
                    self.assertEqual(len({row["message_id"] for row in messages}), 15)
                    self.assertEqual(messages[0]["content"], "Ход пропущен: корректный ответ не получен.")
                    self.assertEqual(final["protocol_status"], "accepted")
                    self.assertEqual(final["vote_summary"], {
                        "for": 5, "against": 0, "abstain": 0,
                        "votes": [{"role_id": role, "vote": "for"} for role in CONTRIBUTIONS],
                    })
                    self.assertEqual(final["forecast"]["basis"], "proposed_protocol")
                    self.assertEqual(final["result"]["basis"], "accepted_protocol")
                    self.assertEqual(final["result"]["outcome_title"], "Открытая река")
                    self.assertEqual(final["result"]["executed_rub"], 270_000_000)
                    self.assertIn("Очистные города N заработали на 36-м месяце", final["result"]["herald_text"])
                    self.assertEqual(final["result"]["financial_load"][0]["budget_rub"], 30_000_000)
                    self.assertEqual(final["result"]["financial_load"][0]["committed_rub"], 30_000_000)
                    for role in configured["settings"]["roles"]:
                        self.assertTrue(any(role["strategy"] in prompt for prompt in provider_prompts[role["role_id"]]))
                    if mode == "manual":
                        self.assertEqual({role for role, prompts in provider_prompts.items()
                                          if any(CUSTOM in prompt for prompt in prompts)}, {"city_administration"})

    async def assert_invalid_answers(self, api, path, expected):
        invalid = deepcopy(expected)
        invalid["city_administration"]["max_money"] = 20
        invalid["city_administration"]["timeline"] = True
        invalid["industrial_holding"].update(start_money=140, max_money=120)
        invalid["environmental_ngo"]["water_supply"] = True
        invalid.pop("city_residents")
        response = await api.put(path + "/settings", json={"mode": "manual", "answers": invalid})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(set(tuple(row["path"]) for row in response.json()["field_errors"]), {
            ("answers", "city_administration", "max_money"),
            ("answers", "city_administration", "timeline"),
            ("answers", "industrial_holding", "start_money"),
            ("answers", "industrial_holding", "max_money"),
            ("answers", "environmental_ngo", "water_supply"),
            ("answers", "city_residents"),
        })
