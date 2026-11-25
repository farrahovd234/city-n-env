"""HTTP routes for the interactive session lifecycle."""

import asyncio
from datetime import datetime
from hashlib import sha256
import hmac
import os
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Body, Header, Query, Request, Response

from .game_contract import (ERROR_RESPONSES, EventPage, GameSnapshot, Instruction, InstructionAccepted, ManualInput,
                            Settings, SPEECH_PHASES, validate_settings)
from .sessions import COOKIE, SESSION_TTL, GameSession, SessionStore, error, logger, now


ROOT_PATH = "/api/v1/games"
NOT_FOUND = "Партия не найдена."


class InteractiveGames:
    def __init__(self, runs, factory, options, images):
        self.runs, self.factory, self.options, self.images = runs, factory, options, images
        self.active = {}
        self.rag = None
        self.store = None

    def initialize(self, rag):
        self.store = SessionStore(self.runs)
        self.rag = rag
        for record in self.store.recover():
            session = GameSession(self.store, record, self.images)
            if record["result_input"]:
                session.fail("RESULT_FAILED", "Расчёт прерван перезапуском сервера. Повторите расчёт.")
            else:
                session.fail("GAME_INTERRUPTED", "Игра прервана перезапуском сервера.")

    async def shutdown(self):
        tasks = [task for _, task in self.active.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def get(self, game_id, request):
        if self.store is None:
            return None
        record = self.store.get(game_id)
        if record is None:
            return None
        owner = request.cookies.get(COOKIE, "")
        if not hmac.compare_digest(record["owner"], sha256(owner.encode()).hexdigest()):
            raise error(404, "GAME_NOT_FOUND", NOT_FOUND)
        if game_id in self.active:
            return self.active[game_id][0]
        return GameSession(self.store, record, self.images)

    def require(self, game_id, request):
        session = self.get(game_id, request)
        if session is None:
            raise error(404, "GAME_NOT_FOUND", NOT_FOUND)
        return session

    def create(self, request: Request, response: Response, key: str | None):
        key = require_key(key)
        owner = request.cookies.get(COOKIE) or self.store.owner_token(key)
        digest = hmac.new(self.store.secret, f"{owner}:{key}".encode(), "sha256").hexdigest()
        game_id = UUID(hex=digest[:32], version=4).hex
        owner_hash = sha256(owner.encode()).hexdigest()
        existing = self.store.get(game_id)
        session = (GameSession(self.store, existing, self.images) if existing else
                   GameSession.create(self.store, owner_hash, game_id, self.images))
        response.set_cookie(COOKIE, owner, httponly=True, samesite="lax",
                            secure=request.url.scheme == "https" or os.getenv("CITY_N_SECURE_COOKIE") == "1",
                            max_age=int(SESSION_TTL.total_seconds()))
        response.headers["Location"] = f"{ROOT_PATH}/{game_id}"
        response.status_code = 201
        return session.public()

    def launch(self, session, *, retry=False):
        game_id = session.state["game_id"]

        async def run():
            try:
                remaining = (datetime.fromisoformat(session.state["expires_at"]) - now()).total_seconds()
                async with asyncio.timeout(max(remaining, 0)):
                    if retry:
                        await session.calculate_result()
                    else:
                        await session.play(self.factory, self.options, self.rag)
            except Exception:
                logger.exception("Интерактивная партия %s прервана", game_id)
                if session.state["phase"] == "calculating_result":
                    session.fail("RESULT_FAILED", "Не удалось рассчитать последствия. Повторите расчёт.")
                else:
                    session.fail("GAME_FAILED", "Не удалось завершить игру.")

        def finished(task):
            current = self.active.get(game_id)
            if current and current[1] is task:
                self.active.pop(game_id)

        task = asyncio.create_task(run())
        self.active[game_id] = session, task
        task.add_done_callback(finished)


def require_key(key):
    if not key or not 16 <= len(key) <= 128:
        raise error(422, "IDEMPOTENCY_KEY_REQUIRED", "Укажите Idempotency-Key длиной от 16 до 128 символов.")
    return key


KeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


def register_session_routes(app, games):
    @app.put(f"{ROOT_PATH}/{{game_id}}/settings", response_model=GameSnapshot, responses=ERROR_RESPONSES)
    async def save_settings(game_id: str, settings: Settings, request: Request):
        session = games.require(game_id, request)
        if session.state["status"] != "draft":
            raise error(409, "SETTINGS_LOCKED", "Настройки зафиксированы после запуска.")
        values, errors = validate_settings(settings)
        if errors:
            raise error(422, "INVALID_SETTINGS", "Проверьте настройки ролей.", errors)
        session.state["settings"] = values
        session.record["settings_saved"] = True
        session.emit("settings.saved")
        session.save()
        return session.public()

    @app.post(f"{ROOT_PATH}/{{game_id}}/start", response_model=GameSnapshot, responses=ERROR_RESPONSES)
    async def start(game_id: str, request: Request, key: KeyHeader = None):
        key = require_key(key)
        session = games.require(game_id, request)
        started = False

        def apply():
            nonlocal started
            if session.state["status"] == "draft":
                if not session.record.get("settings_saved"):
                    raise error(409, "SETTINGS_REQUIRED", "Сохраните настройки перед запуском игры.")
                session.state.update(status="running", phase="positions")
                session.emit("phase.changed")
                started = True
            elif session.state["status"] == "cancelled" and session.state["phase"] is None:
                raise error(409, "GAME_CANCELLED", "Партия отменена.")
            return session.public()

        result = session.command(key, "start", None, apply)
        if started:
            games.launch(session)
        return result

    @app.get(f"{ROOT_PATH}/{{game_id}}/events", response_model=EventPage, responses=ERROR_RESPONSES)
    async def events(game_id: str, request: Request, after: Annotated[int, Query(ge=0)] = 0):
        return games.require(game_id, request).event_page(after)

    async def set_pause(game_id, request, key, pause):
        session = games.require(game_id, request)

        def apply():
            if session.state["status"] != "running":
                raise error(409, "GAME_NOT_RUNNING", "Команда доступна во время игры.")
            old = session.state["pause_state"]
            value = ("requested" if session.in_step else "paused") if pause else "none"
            if pause and old != "none":
                value = old
            if old != value:
                session.state["pause_state"] = value
                session.emit("pause.changed")
            return session.public()

        return session.command(require_key(key), "pause" if pause else "continue", None, apply)

    @app.post(f"{ROOT_PATH}/{{game_id}}/pause", response_model=GameSnapshot, responses=ERROR_RESPONSES)
    async def pause(game_id: str, request: Request, key: KeyHeader = None):
        return await set_pause(game_id, request, key, True)

    @app.post(f"{ROOT_PATH}/{{game_id}}/continue", response_model=GameSnapshot, responses=ERROR_RESPONSES)
    async def resume(game_id: str, request: Request, key: KeyHeader = None):
        return await set_pause(game_id, request, key, False)

    @app.post(f"{ROOT_PATH}/{{game_id}}/inputs/{{input_id}}", response_model=GameSnapshot, responses=ERROR_RESPONSES)
    async def input_reply(game_id: str, input_id: str, request: Request,
                          body: Annotated[ManualInput, Body()], key: KeyHeader = None):
        session = games.require(game_id, request)
        data = body.model_dump()

        def apply():
            pending = session.state["pending_input"]
            if not pending or pending["input_id"] != input_id or pending["type"] != data["type"]:
                raise error(409, "INPUT_CLOSED", "Этот запрос ввода больше недоступен.")
            if session.state["pause_state"] != "none":
                raise error(409, "GAME_PAUSED", "Продолжите игру перед отправкой ответа.")
            session.reply = data
            session.state["pending_input"] = None
            session.emit("input.resolved")
            return session.public()

        return session.command(require_key(key), f"input:{input_id}", data, apply)

    @app.post(f"{ROOT_PATH}/{{game_id}}/roles/{{role_id}}/instructions", response_model=InstructionAccepted,
              responses=ERROR_RESPONSES)
    async def instructions(game_id: str, role_id: str, body: Instruction, request: Request, key: KeyHeader = None):
        session = games.require(game_id, request)

        def apply():
            state = session.state
            role = next((role for role in state["settings"]["roles"] if role["role_id"] == role_id), None)
            if role is None:
                raise error(404, "ROLE_NOT_FOUND", "Роль не найдена.")
            if (state["status"] != "running" or state["phase"] not in SPEECH_PHASES
                    or role["control_mode"] != "ai"):
                raise error(409, "INSTRUCTION_UNAVAILABLE", "Инструкция доступна для следующего хода AI-роли.")
            if state["phase"] == "amendments" and state["current_role_id"]:
                order = state["scenario"]["role_order"]
                if order.index(role_id) <= order.index(state["current_role_id"]):
                    raise error(409, "INSTRUCTION_UNAVAILABLE", "Роль уже начала последний ход.")
            session.record["instructions"].setdefault(role_id, []).append(body.content)
            return {"instruction_id": uuid4().hex, "applies_to": "next_unstarted_speech"}

        return session.command(require_key(key), f"instruction:{role_id}", body.model_dump(), apply)

    @app.post(f"{ROOT_PATH}/{{game_id}}/retry-result", response_model=GameSnapshot, responses=ERROR_RESPONSES)
    async def retry_result(game_id: str, request: Request, key: KeyHeader = None):
        session = games.require(game_id, request)
        started = False

        def apply():
            nonlocal started
            if "retry_result" not in session.public()["available_actions"]:
                raise error(409, "RESULT_RETRY_UNAVAILABLE", "Повтор расчёта недоступен.")
            session.state.update(status="running", phase="calculating_result", error=None)
            session.emit("phase.changed")
            started = True
            return session.public()

        result = session.command(require_key(key), "retry-result", None, apply)
        if started:
            games.launch(session, retry=True)
        return result


def cancel_interactive(games, session, key):
    cancelled = False

    def apply():
        nonlocal cancelled
        if session.state["status"] in {"completed", "failed"}:
            raise error(409, "GAME_ALREADY_FINISHED", "Партия уже завершена.")
        if session.state["status"] != "cancelled":
            session.state.update(status="cancelled", phase=None, pause_state="none", pending_input=None,
                                 current_role_id=None)
            session.emit("game.cancelled")
            cancelled = True
        return session.public()

    result = session.command(require_key(key), "cancel", None, apply)
    running = games.active.get(session.state["game_id"])
    if cancelled and running:
        running[1].cancel()
    return result
