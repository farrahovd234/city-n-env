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
from negotiation_game.rules import project_funding
from web_backend.app import create_app
from web_backend.questionnaires import QUESTIONNAIRES, vote_objections


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
    def test_funding_is_compared_in_kopecks(self):
        amounts = [5_000_000.2, 175_000_006.4, 89_999_993.4]
        state = {"players": {i: {"contribution": value, "contribution_cap": 180_000_000}
                             for i, value in enumerate(amounts)}}
        self.assertEqual(project_funding(state, 270_000_000), (270_000_000, 0))
        state["players"][0]["contribution"] -= 0.01
        self.assertEqual(project_funding(state, 270_000_000), (269_999_999.99, 0.01))

    def test_holding_requires_relief_only_above_comfortable_pledge(self):
        role = "industrial_holding"
        answers = {**QUESTIONNAIRES[role]["defaults"], "plant_mode": "100%"}
        state = {"player_ids": {role: "Холдинг"},
                 "players": {"Холдинг": {"contribution": answers["comfort_money"] * 1_000_000}},
                 "levers": {"timeline": 36, "plant_mode": "100%", "guilt": "shared", "tax_relief": False}}
        self.assertEqual(vote_objections(role, answers, state), [])
        state["players"]["Холдинг"]["contribution"] += 1
        self.assertEqual(len(vote_objections(role, answers, state)), 1)
        state["levers"]["tax_relief"] = True
        self.assertEqual(vote_objections(role, answers, state), [])

    async def test_manual_numeric_answers_work_between_presets(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(runs_dir=directory, images=False, embedding_base_url="")
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://city.test") as api,
            ):
                created = await api.post(ROOT, headers={"Idempotency-Key": uuid4().hex})
                path = created.headers["Location"]
                questionnaires = created.json()["scenario"]["questionnaires"]
                answers = {role: row["defaults"] for role, row in questionnaires.items()}
                answers["city_administration"].update(comfort_money=17, max_money=27, timeline=32)
                answers["industrial_holding"].update(start_money=137, timeline=32)
                payload = {"mode": "manual", "answers": answers}
                saved = await api.put(path + "/settings", json=payload)
                self.assertEqual(saved.status_code, 200, saved.text)
                city, holding = saved.json()["settings"]["roles"][:2]
                self.assertEqual(city["answers"]["max_money"], 27)
                self.assertIn("32 мес.", city["strategy"])
                self.assertEqual(holding["conditions"]["timeline"], 32)
                self.assertEqual(holding["pledged_rub"], 137_000_000)
                answers["city_administration"].update(max_money=31, timeline=23)
                rejected = await api.put(path + "/settings", json=payload)
                self.assertEqual(rejected.status_code, 422, rejected.text)
                self.assertEqual({error["path"][-1] for error in rejected.json()["field_errors"]}, {"max_money", "timeline"})

    async def test_automatic_answers_start_a_readonly_game(self):
        await self.play("automatic")

    async def test_manual_answers_set_owned_conditions_and_enforce_contribution_limits(self):
        await self.play("manual")

    async def test_even_small_deficit_requires_five_votes_against(self):
        await self.play("automatic", deficit_millions=0.05)

    async def play(self, mode, *, deficit_millions=0):
        model_started, let_model_reply = asyncio.Event(), asyncio.Event()
        provider_prompts = {}
        model_votes = []
        repeated_city_position = ("Заморозка тарифов — наше условие, но гарантию питьевой воды не включаем, "
                                  "чтобы сохранить все 30 млн на реконструкцию.")
        city_clarification = "Промкомплекс, какой вклад вы готовы записать в протокол?"

        async def reply(request):
            body = json.loads(request.content)
            role = body["model"]
            provider_prompts.setdefault(role, []).extend(message["content"] for message in body["messages"])
            if "tools" not in body:
                content = city_clarification if role == "city_administration" else "Мы выделим 90 млн ₽."
                return httpx.Response(200, json={"id": "clarification", "object": "chat.completion", "created": 0,
                    "model": role, "choices": [{"index": 0, "finish_reason": "stop",
                                                "message": {"role": "assistant", "content": content}}]})
            parameters = body["tools"][0]["function"]["parameters"]
            properties = parameters["properties"]
            voting = properties["vote"]["enum"] != ["none"]
            if voting:
                self.assertEqual(properties["vote"]["enum"], ["for", "against"])
                model_votes.append(role)
            if role == "city_residents" and not voting:
                owned = parameters["$defs"]["ConditionInput"]["properties"]["lever_id"]["enum"]
                self.assertEqual(owned, ["protest_moratorium"])
                self.assertEqual(properties["own_conditions"]["maxItems"], 1)
            model_started.set()
            await let_model_reply.wait()
            condition = {"city_administration": "water_supply", "environmental_ngo": "open_sensors",
                         "regional_government": "tax_relief"}.get(role)
            city_opening = role == "city_administration" and any(
                "ИДЕТ ЭТАП 1:" in message["content"] for message in body["messages"])
            bargaining = any("ЭТАП 2 ИЗ 3" in message["content"] for message in body["messages"])
            correction = any("Ответ не применён." in message["content"] for message in body["messages"])
            speech = ("Регион: стартовая позиция и требования. Предлагаю разделить ответственность (shared) "
                      "и предоставить налоговые льготы (tax_relief: true). Признание вины — только shared."
                      if role == "regional_government"
                      else f"Позиция стороны {role}.")
            if bargaining and role in {"city_administration", "regional_government"} and not correction:
                speech = repeated_city_position
            own_conditions = [{"lever_id": condition,
                               "value_json": "false" if city_opening and mode == "manual" else "true"}
                              ] if condition and not voting else []
            if role == "environmental_ngo":
                own_conditions = own_conditions * 2
            if role == "city_residents" and bargaining and not voting:
                own_conditions = [{"lever_id": "water_supply", "value_json": "true"}]
            contribution = CONTRIBUTIONS[role] - deficit_millions if role == "industrial_holding" else CONTRIBUTIONS[role]
            return tool_reply({
                "speech": speech,
                "own_contribution": {"action": "unchanged" if voting else "set",
                                     "amount_millions": 0 if voting else 20 if city_opening else contribution},
                "own_conditions": own_conditions,
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
                        expected["industrial_holding"].update(start_money=140, plant_mode="100%")
                        expected["environmental_ngo"].update(plant_mode="100%", guilt="shared")
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
                    else:
                        self.assertEqual(configured["settings"]["roles"][1]["answers"]["plant_mode"], "70%")

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
                    self.assertEqual(messages[0]["content"], city_clarification)
                    self.assertEqual(messages[8]["content"],
                                     "Администрация, как вы предлагаете обеспечить жителей питьевой водой до запуска очистных?")
                    self.assertFalse(any(row.get("skipped") for row in messages))
                    self.assertEqual(messages[2]["content"],
                                     "Предлагаю разделить ответственность и предоставить налоговые льготы. "
                                     "Признание вины — только разделённая ответственность.")
                    self.assertEqual(messages[5]["content"], repeated_city_position)
                    self.assertEqual(messages[7]["content"], messages[2]["content"])
                    accepted = not deficit_millions
                    votes_against = set() if accepted else set(CONTRIBUTIONS)
                    self.assertEqual(set(model_votes), set(CONTRIBUTIONS) - votes_against)
                    self.assertEqual(final["protocol_status"], "accepted" if accepted else "rejected")
                    self.assertEqual(final["vote_summary"], {
                        "for": 5 - len(votes_against), "against": len(votes_against), "abstain": 0,
                        "votes": [{"role_id": role, "vote": "against" if role in votes_against else "for"}
                                  for role in CONTRIBUTIONS],
                    })
                    self.assertEqual(final["forecast"]["basis"], "proposed_protocol")
                    review_path = f"{path}/analysis/questionnaire"
                    response = await api.get(f"{review_path}/city_residents")
                    self.assertEqual(response.status_code, 200, response.text)
                    review = response.json()
                    self.assertIn("270 млн", review["context"])
                    if deficit_millions:
                        self.assertIn("50 000", review["context"])
                    option = review["items"][0]
                    self.assertEqual(option["field_id"], "water_supply")
                    if mode == "manual":
                        self.assertNotEqual(option["chosen"], option["suggested"])
                    else:
                        self.assertEqual(option["chosen"], option["suggested"])
                    for configured_role in configured["settings"]["roles"]:
                        role_id = configured_role["role_id"]
                        advice = await api.get(f"{review_path}/{role_id}")
                        self.assertEqual(advice.status_code, 200, advice.text)
                        self.assertTrue(advice.json()["items"])
                        self.assertTrue(all(item["field_id"] in configured_role["answers"]
                                            for item in advice.json()["items"]))
                    if accepted:
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
