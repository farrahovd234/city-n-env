"""FastAPI entry point for the City N negotiation game."""

import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, field_validator

from negotiation_game.engine import NegotiationEngine
from negotiation_game.run_store import RunStore

from .results import illustration, public_game
from .game_contract import ERROR_RESPONSES, GameSnapshot
from .scenario import CONFIG, ROLE_IDS, ROOT, build_rag, game_profiles, game_settings, public_scenario
from .session_api import InteractiveGames, KeyHeader, cancel_interactive, register_session_routes


logger = logging.getLogger(__name__)


class StartGame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategies: dict[str, str] = Field(default_factory=dict)

    @field_validator("strategies")
    @classmethod
    def check_strategies(cls, strategies: dict[str, str]) -> dict[str, str]:
        if strategies.keys() - ROLE_IDS or any(not value.strip() for value in strategies.values()):
            raise ValueError("Стратегии должны быть непустым текстом и принадлежать известным ролям.")
        return strategies


def configured_model(role_id: str, temperature: float) -> ChatOpenAI:
    base_url = os.getenv("CITY_N_LLM_BASE_URL", "")
    model = os.getenv("CITY_N_LLM_MODEL") or CONFIG["model"]
    if not base_url:
        raise ValueError("Задайте CITY_N_LLM_BASE_URL.")
    return ChatOpenAI(base_url=base_url, model=model, temperature=temperature,
                      api_key=os.getenv("CITY_N_LLM_API_KEY") or "local", max_retries=0)


def create_app(*, runs_dir=None, model_factory=None, images=None, embedding_base_url=None,
               embedding_api_key=None, game_options=None) -> FastAPI:
    runs = Path(runs_dir or os.getenv("CITY_N_RUNS_DIR") or ROOT / "games" / "web").expanduser().resolve()
    factory = model_factory or configured_model
    images = os.getenv("CITY_N_IMAGES") == "1" if images is None else images
    embedding_url = os.getenv("CITY_N_EMBEDDING_BASE_URL", "") if embedding_base_url is None else embedding_base_url
    embedding_key = os.getenv("CITY_N_EMBEDDING_API_KEY", "") if embedding_api_key is None else embedding_api_key
    options = {**CONFIG["game"], **(game_options or {})}
    interactive = InteractiveGames(runs, factory, options, images)
    jobs: dict[str, asyncio.Task] = {}
    unsaved_results: dict[str, dict] = {}

    def save_terminal(store: RunStore, raw: dict) -> None:
        try:
            store.save(raw)
        except OSError as exc:
            unsaved_results[store.run_id] = raw
            logger.error("Результат партии %s не записан: %s", store.run_id, type(exc).__name__)

    def read_game(game_id: str) -> dict:
        try:
            if UUID(game_id).hex != game_id:
                raise ValueError("Invalid game ID")
            if game_id in unsaved_results:
                return unsaved_results[game_id]
            return json.loads((runs / game_id / "result.json").read_text(encoding="utf-8"))
        except (ValueError, FileNotFoundError):
            raise HTTPException(404, detail={"code": "game_not_found", "message": "Партия не найдена."}) from None

    async def stop_game(game_id: str) -> dict:
        job = jobs.get(game_id)
        if job and not job.done():
            if not job.cancelling():
                job.cancel()
            await asyncio.gather(job, return_exceptions=True)
        raw = read_game(game_id)
        if raw["status"] in {"queued", "running"}:
            raw.update(status="cancelled", error=None, report="# Игра отменена\n")
            save_terminal(RunStore(runs, game_id, exist_ok=True), raw)
        return raw

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.rag = build_rag(runs, embedding_url, embedding_key)
        interactive.initialize(app.state.rag)
        try:
            yield
        finally:
            await interactive.shutdown()
            await asyncio.gather(*(stop_game(game_id) for game_id in tuple(jobs)))

    app = FastAPI(title="Город N", version="1.0.0", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        fields = [{"path": list(item["loc"][1:]), "message": item["msg"]} for item in exc.errors()]
        return JSONResponse({"code": "invalid_game_input",
                             "message": "Проверьте поля запроса.", "field_errors": fields}, status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(exc.detail, status_code=exc.status_code, headers=exc.headers)

    async def run_game(store: RunStore, strategies: dict[str, str]):
        try:
            engine = NegotiationEngine()
            engine.players = game_profiles(strategies, factory)
            engine.settings = game_settings()
            engine.rag_config = app.state.rag
            for key in CONFIG["game"]:
                setattr(engine, key, options[key])
            result = await engine.run_game(store)
        except Exception as exc:
            result = {"status": "failed", "error": f"{type(exc).__name__}: {exc}",
                      "history": [], "report": "# Игра прервана\n"}
        if "run_id" not in result:
            save_terminal(store, result)

    @app.get("/api/v1/scenario")
    async def scenario():
        return public_scenario()

    @app.post("/api/v1/games", status_code=201, response_model=GameSnapshot,
              responses={**ERROR_RESPONSES, 202: {"description": "Прежний режим автоматического запуска"}})
    async def start_game(request: Request, response: Response, body: StartGame | None = None, key: KeyHeader = None):
        if body is None or key is not None:
            if body is not None and body.strategies:
                raise HTTPException(422, detail={"code": "INVALID_SETTINGS", "message": "Сохраните стратегии через PUT settings.", "field_errors": []})
            return interactive.create(request, response, key)
        game_id = uuid4().hex
        store = RunStore(runs, game_id)
        store.save({"status": "queued", "history": [], "report": "# Партия в очереди\n"})
        job = asyncio.create_task(run_game(store, body.strategies))
        jobs[game_id] = job
        job.add_done_callback(lambda _: jobs.pop(game_id, None))
        url = f"/api/v1/games/{game_id}"
        response.headers["Location"] = url
        return JSONResponse({"game_id": game_id, "status": "queued", "status_url": url}, status_code=202,
                            headers={"Location": url})

    @app.get("/api/v1/games/{game_id}", response_model=GameSnapshot, responses=ERROR_RESPONSES)
    async def get_game(game_id: str, request: Request):
        session = interactive.get(game_id, request)
        if session is not None:
            return session.public()
        return JSONResponse(public_game(game_id, read_game(game_id), images))

    @app.post("/api/v1/games/{game_id}/cancel", response_model=GameSnapshot, responses=ERROR_RESPONSES)
    async def cancel_game(game_id: str, request: Request, key: KeyHeader = None):
        session = interactive.get(game_id, request)
        if session is not None:
            return cancel_interactive(interactive, session, key)
        raw = read_game(game_id)
        if raw["status"] in {"completed", "failed"}:
            raise HTTPException(409, detail={"code": "game_cannot_cancel", "message": "Партия уже завершена."})
        if raw["status"] != "cancelled":
            raw = await stop_game(game_id)
        return JSONResponse(public_game(game_id, raw, images))

    @app.get("/api/v1/illustrations/{outcome_id}.png", include_in_schema=False)
    async def get_illustration(outcome_id: str):
        path = illustration(outcome_id) if images else None
        if path is None:
            raise HTTPException(404, detail={"code": "illustration_not_found", "message": "Иллюстрация не найдена."})
        return FileResponse(path, media_type="image/png")

    register_session_routes(app, interactive)
    frontend = ROOT.parent / "frontend"
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


app = create_app()
