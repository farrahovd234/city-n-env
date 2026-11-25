"""Проверки API и сравнение с эталонными партиями."""

import asyncio
import base64
from functools import partial
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zlib
from unittest.mock import AsyncMock, patch

import httpx
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI
from parity_snapshot import snapshot

from consequences_model import forecast
from negotiation_game.engine import NegotiationEngine
from web_backend.app import create_app
from web_backend.scenario import build_rag, rag_corpus


FIXTURES = Path(__file__).resolve().parent / "fixtures"

CASES = json.loads((FIXTURES / "reference_games.json").read_text())["cases"]
CONSEQUENCES_V2 = {
    "accepted_full": ("open_river", 270_000_000, 36),
    "accepted_deficit": ("dolgostroy", 260_000_000, 60),
    "rejected_with_abstentions": ("stagnation", 0, None),
}
PAUSE = asyncio.sleep


def tool_reply(reply):
    return httpx.Response(200, json={"id": "fixture", "object": "chat.completion", "created": 0,
        "model": "fixture", "choices": [{"index": 0, "finish_reason": "tool_calls",
            "message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "fixture", "type": "function", "function": {
                    "name": "PlayerTurn", "arguments": json.dumps(reply, ensure_ascii=False)}}]}}]})


def fixture_model(provider, role_id, temperature):
    return ChatOpenAI(base_url="http://fixture.invalid/v1", api_key="fixture-only",
                      model=role_id, temperature=temperature, max_retries=0,
                      http_async_client=provider)


class WebGameAPITests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self, case_name, *, images=True):
        case = CASES[case_name]
        inputs = case["inputs"]
        marker = inputs["strategies"]["city_residents"]
        markers_seen = set()

        async def reply(request):
            body = json.loads(request.content)
            role = body["model"]
            system = "\n".join(m["content"] for m in body["messages"] if m["role"] == "system")
            if marker in system:
                markers_seen.add(role)
            tool = body["tools"][0]["function"]
            self.assertEqual(tool["name"], "PlayerTurn")
            voting = tool["parameters"]["properties"]["vote"]["enum"] != ["none"]
            condition = {"city_administration": "water_supply", "environmental_ngo": "open_sensors"}.get(role)
            reply = {
                "speech": "Подтверждаю позицию своей стороны.",
                "own_contribution": {"action": "unchanged" if voting else "set",
                                     "amount_millions": 0 if voting else inputs["contributions_millions"][role]},
                "own_conditions": [{"lever_id": condition, "value_json": "true"}] if condition and not voting else [],
                "pledge_demands": [], "condition_demands": [], "responses": [], "withdrawn_demands": [],
                "addressed_to": "everyone", "vote": inputs["votes"][role] if voting else "none",
            }
            return tool_reply(reply)

        with tempfile.TemporaryDirectory() as directory:
            async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as provider:
                app = create_app(runs_dir=Path(directory), model_factory=partial(fixture_model, provider), images=images,
                                 embedding_base_url="")
                async with (app.router.lifespan_context(app),
                            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as api):
                    scenario = (await api.get("/api/v1/scenario")).json()
                    self.assertEqual(scenario["total_cost_rub"], 270_000_000)
                    self.assertEqual(len(scenario["roles"]), 5)
                    with patch("asyncio.sleep", new=AsyncMock()):
                        response = await api.post("/api/v1/games", json={"strategies": inputs["strategies"]})
                        self.assertEqual(response.status_code, 202, response.text)
                        game_id = response.json()["game_id"]
                        self.assertEqual(response.headers["location"], f"/api/v1/games/{game_id}")
                        for _ in range(300):
                            result = (await api.get(response.headers["location"])).json()
                            if result["status"] not in {"queued", "running"}:
                                break
                            await PAUSE(0.02)
                    self.assertEqual(result["status"], "completed", result)
                    self.assertEqual(markers_seen, {"city_residents"})
                    data = result["result"]
                    outcome_id, executed_rub, commissioning_month = CONSEQUENCES_V2[case_name]
                    forecast_data = data["consequences"]
                    self.assertEqual(forecast_data["outcome_id"], outcome_id)
                    self.assertEqual(forecast_data["executed_rub"], executed_rub)
                    self.assertEqual(forecast_data["commissioning_month"], commissioning_month)
                    self.assertEqual(forecast_data["model_version"], 2)
                    self.assertEqual(len(forecast_data["herald_text"].splitlines()), 1)
                    if images:
                        self.assertEqual(forecast_data["image_url"], f"/api/v1/illustrations/{outcome_id}.png")
                        image = await api.get(forecast_data["image_url"])
                        self.assertEqual(image.status_code, 200)
                        asset = FIXTURES.parents[1] / "assets" / "consequences" / f"{outcome_id}.png"
                        self.assertEqual(image.content, asset.read_bytes())
                        image_sha = hashlib.sha256(image.content).hexdigest()
                    else:
                        self.assertIsNone(data["consequences"]["image_url"])
                        image = await api.get("/api/v1/illustrations/open_river.png")
                        self.assertEqual(image.status_code, 404)
                        image_sha = case["expected"]["illustration_sha256"]
                    self.assertNotIn(marker, json.dumps(result, ensure_ascii=False))
                    raw = json.loads((Path(directory) / game_id / "result.json").read_text())
                    self.assertTrue(all(row["core_chunk_ids"] for row in raw["rag_retrievals"]))
                    self.assertTrue(any(row.get("skip_reason") == "no_allowed_sources" for row in raw["rag_retrievals"]))
                    actual = snapshot(raw, forecast(raw), data["negotiation_report_markdown"],
                                      data["consequences"]["herald_text"], image_sha)
                    # The saved migration reference still verifies the entire negotiation.
                    consequence_fields = {"forecast", "newspaper", "illustration_sha256"}
                    negotiation = {key: value for key, value in actual.items() if key not in consequence_fields}
                    expected = {key: value for key, value in case["expected"].items() if key not in consequence_fields}
                    self.assertEqual(negotiation, expected)
                    self.assertEqual(data["pledged_rub"], raw["total_money"])
                    self.assertEqual(data["deficit_rub"], raw["deficit"])
                    self.assertEqual(data["accepted"], raw["consensus_reached"])
                    self.assertEqual(data["budget_closed"], raw["voting_summary"]["budget_closed"])
                    expected_votes = list(inputs["votes"].values())
                    self.assertCountEqual([v["value"] for v in data["votes"]], expected_votes)
                    self.assertEqual({c["id"]: c["value"] for c in data["conditions"]}, actual["conditions"])
                    self.assertEqual(len(data["transcript"]), len(actual["turns"]))
                    self.assertEqual(forecast_data["financial_load"][0]["over_budget_rub"], 20_000_000)
                    self.assertEqual(forecast_data["report_markdown"], actual["forecast"]["report"])
                    self.assertEqual((await api.post(response.headers["location"] + "/cancel")).status_code, 409)
                    return data

    async def test_full_game_matches_reference(self):
        await self.run_case("accepted_full")

    async def test_accepted_deficit_matches_reference(self):
        await self.run_case("accepted_deficit")

    async def test_rejection_with_abstentions_matches_reference(self):
        await self.run_case("rejected_with_abstentions")

    async def test_http_contract_rejects_invalid_input(self):
        app = create_app(embedding_base_url="")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as api:
            for body in ({"strategies": {"unknown": "План"}}, {"strategies": {"city_residents": 7}},
                         {"strategies": {"city_residents": " "}}, {"budget": 1}):
                response = await api.post("/api/v1/games", json=body)
                self.assertEqual(response.status_code, 422, body)
                self.assertEqual(response.json()["code"], "invalid_game_input")
            missing = await api.get("/api/v1/games/missing")
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(missing.json()["code"], "game_not_found")

    async def test_provider_503_preserves_public_progress(self):
        await self.check_interruption("503")

    async def test_request_timeout_preserves_public_progress(self):
        await self.check_interruption("timeout")

    async def test_cancel_during_request_preserves_public_progress(self):
        await self.check_interruption("cancelled")

    async def check_interruption(self, interruption):
        attempts = 0
        started = asyncio.Event()
        stopped = asyncio.Event()
        secret_error = "PROVIDER_PRIVATE_ERROR"

        async def reply(request):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                answer = {"speech": "Первый ход зафиксирован.", "own_contribution": {
                    "action": "unchanged", "amount_millions": 0}, "own_conditions": [],
                    "pledge_demands": [], "condition_demands": [], "responses": [],
                    "withdrawn_demands": [], "addressed_to": "everyone", "vote": "none"}
                return tool_reply(answer)
            started.set()
            if interruption == "503":
                return httpx.Response(503, json={"error": {"message": secret_error}})
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        with tempfile.TemporaryDirectory() as directory:
            async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as provider:
                options = {"request_timeout_seconds": 0.2} if interruption == "timeout" else {}
                app = create_app(runs_dir=directory, model_factory=partial(fixture_model, provider), embedding_base_url="",
                                 images=False, game_options=options)
                async with (app.router.lifespan_context(app),
                            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as api,
                            asyncio.timeout(10)):
                    with patch("asyncio.sleep", new=AsyncMock()):
                        start = await api.post("/api/v1/games", json={})
                        self.assertEqual(start.status_code, 202)
                        url = start.headers["location"]
                        await started.wait()
                        if interruption == "cancelled":
                            pending = (await api.get(url)).json()
                            self.assertEqual(pending["status"], "running")
                            self.assertEqual(len(pending["progress"]["transcript"]), 1)
                            self.assertNotIn("result", pending)
                            cancelled = await api.post(url + "/cancel")
                            self.assertEqual(cancelled.status_code, 200)
                            self.assertEqual((await api.post(url + "/cancel")).json(), cancelled.json())
                        expected = "cancelled" if interruption == "cancelled" else "failed"
                        while (await api.get(url)).json()["status"] in {"queued", "running"}:
                            await PAUSE(0.01)
                    result = (await api.get(url)).json()
                    self.assertEqual(result["status"], expected)
                    self.assertNotIn("result", result)
                    self.assertEqual(len(result["progress"]["transcript"]), 1)
                    self.assertIn("Первый ход зафиксирован.", result["progress"]["report_markdown"])
                    self.assertNotIn(secret_error, json.dumps(result, ensure_ascii=False))
                    self.assertEqual(attempts, 2 if interruption == "cancelled" else 3)
                    if interruption != "503":
                        self.assertTrue(stopped.is_set())
                    if interruption != "cancelled":
                        self.assertEqual((await api.post(url + "/cancel")).status_code, 409)

    async def test_completed_game_can_disable_images(self):
        response = await self.run_case("accepted_full", images=False)
        self.assertIsNone(response["consequences"]["image_url"])

    async def test_chroma_search_and_embedding_failure_preserve_role_visibility(self):
        _, raw = rag_corpus()
        template = json.loads(raw.splitlines()[0])
        embedding = template["embedding"]
        allowed = dict(template, chunk_id="migration-test-allowed", area="methodology",
                       audience=["admin"], text="Разрешённый пример для администрации.")
        hidden = dict(allowed, chunk_id="migration-test-hidden", audience=["holding"],
                      text="Частный пример холдинга.")
        excluded = dict(allowed, chunk_id="migration-test-excluded", index_policy="reference_hold_not_main_index",
                        text="Пример пока не допущен к поиску.")
        corpus = b"\n".join([raw, *(json.dumps(row).encode() for row in (allowed, hidden, excluded))])
        encoded = base64.b64encode(zlib.compress(corpus)).decode()
        with tempfile.TemporaryDirectory() as directory:
            with patch("web_backend.scenario.rag_corpus", return_value=(encoded, corpus)):
                config = build_rag(Path(directory), "http://fixture.invalid/v1", "fixture")

            engine = NegotiationEngine()
            engine.rag_config = config
            profile = {"id": "city_administration"}

            async def response(request):
                self.assertTrue(request.url.path.endswith("/embeddings"))
                return httpx.Response(200, json={"data": [{"embedding": embedding, "index": 0}]})

            for handler in (response, lambda _: httpx.Response(503, json={"error": "fixture offline"})):
                transport = httpx.MockTransport(handler)

                def mock_client(**options):
                    return AsyncOpenAI(**options, http_client=httpx.AsyncClient(transport=transport))

                with patch("openai.AsyncOpenAI", side_effect=mock_client):
                    text = await engine._rag_context("Администрация", profile, [], 1)
                audit = engine._rag_audit[-1]
                self.assertTrue(audit["core_chunk_ids"])
                self.assertNotIn(hidden["text"], text)
                self.assertNotIn(excluded["text"], text)
                if handler is response:
                    self.assertEqual(audit["retrieval_status"], "ok")
                    self.assertEqual(audit["chunk_ids"], [allowed["chunk_id"]])
                    self.assertIn(allowed["text"], text)
                else:
                    self.assertEqual(audit["retrieval_status"], "error")
                    self.assertNotIn(allowed["text"], text)
                    self.assertNotIn("fixture offline", text)

    async def test_unavailable_chroma_index_keeps_core_context(self):
        with (tempfile.TemporaryDirectory() as directory,
              patch("chromadb.PersistentClient", side_effect=OSError("private diagnostic")),
              self.assertLogs("web_backend.scenario", level="WARNING") as logs):
            engine = NegotiationEngine()
            engine.rag_config = build_rag(Path(directory), "http://fixture.invalid/v1", "fixture")
        self.assertNotIn("private diagnostic", "\n".join(logs.output))
        self.assertFalse(engine.rag_config["embedding_base_url"])
        context = await engine._rag_context("Администрация", {"id": "city_administration"}, [], 1)
        self.assertTrue(context)
        self.assertTrue(engine._rag_audit[-1]["core_chunk_ids"])

    def test_public_actions_include_answers_and_withdrawals(self):
        from web_backend.results import action_labels

        labels = action_labels([
            {"kind": "PLEDGE", "contribution": 1_001_000},
            {"kind": "DEMAND_RESPONSE", "demand_id": "d3", "decision": "reject"},
            {"kind": "DEMAND_WITHDRAWN", "demand_id": "d4"},
        ])
        self.assertEqual(labels, ["Взнос: 1001000 ₽", "Ответ на требование d3: отклонено",
                                  "Требование d4 отозвано"])

    async def test_state_reaches_failed_if_progress_cannot_be_written(self):
        from negotiation_game.run_store import RunStore

        save = RunStore.save

        def reject_progress_write(store, payload):
            if payload["status"] == "queued":
                save(store, payload)
            else:
                raise OSError("private disk diagnostic")

        with tempfile.TemporaryDirectory() as directory:
            app = create_app(runs_dir=directory, embedding_base_url="", model_factory=lambda *_: object())
            async with (app.router.lifespan_context(app),
                        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as api,
                        asyncio.timeout(5)):
                with (patch.object(RunStore, "save", reject_progress_write),
                      self.assertLogs("web_backend.app", level="ERROR")):
                    accepted = await api.post("/api/v1/games", json={})
                    self.assertEqual(accepted.status_code, 202)
                    while True:
                        state = (await api.get(accepted.headers["location"])).json()
                        if state["status"] not in {"queued", "running"}:
                            break
                        await PAUSE(0.01)
                self.assertEqual(state["status"], "failed")
                self.assertNotIn("private disk diagnostic", str(state))
