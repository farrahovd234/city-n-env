"""Persistent snapshots, polling and execution control for interactive games."""

import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
from pathlib import Path
import secrets
import sqlite3
from uuid import uuid4

from fastapi import HTTPException

from consequences_model.catalog import MODEL_VERSION
from negotiation_game.engine import NegotiationEngine

from .game_contract import (SPEECH_PHASES, default_settings, make_protocol, projection, scenario_contract, votes)
from .scenario import game_profiles, game_settings


logger = logging.getLogger(__name__)
SESSION_TTL = timedelta(days=7)
COOKIE = "city_n_owner"
EVENT_LIMIT = 256
EVENT_PAGE = 50


def error(status, code, message, fields=()):
    return HTTPException(status, detail={"code": code, "message": message, "field_errors": list(fields)})


def now():
    return datetime.now(timezone.utc)


class SessionStore:
    def __init__(self, runs: Path):
        runs.mkdir(parents=True, exist_ok=True)
        self.path = runs / "sessions.sqlite3"
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, expires_at TEXT, data TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value BLOB)")
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('owner_secret', ?)", (secrets.token_bytes(32),))
            self.secret = db.execute("SELECT value FROM metadata WHERE key = 'owner_secret'").fetchone()[0]

    def owner_token(self, key):
        # First-create retry works even if the Set-Cookie response was lost.
        return hmac.new(self.secret, key.encode(), hashlib.sha256).hexdigest()

    def save(self, record):
        snapshot = record["snapshot"]
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)",
                       (snapshot["game_id"], snapshot["expires_at"], json.dumps(record, ensure_ascii=False)))

    def get(self, game_id):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT data FROM sessions WHERE id = ? AND expires_at > ?",
                             (game_id, now().isoformat())).fetchone()
        return json.loads(row[0]) if row else None

    def recover(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now().isoformat(),))
            rows = db.execute("SELECT data FROM sessions WHERE json_extract(data, '$.snapshot.status') = 'running'")
            return [json.loads(row[0]) for row in rows]


class GameSession:
    def __init__(self, store, record, images):
        self.store = store
        self.record = record
        self.state = record["snapshot"]
        self.images = images
        self.changed = asyncio.Event()
        self.in_step = False
        self.reply = None
        self.history_offset = 0

    @classmethod
    def create(cls, store, owner, game_id, images):
        state = {"game_id": game_id, "status": "draft", "phase": None, "pause_state": "none",
                 "expires_at": (now() + SESSION_TTL).isoformat(), "last_event_id": 0,
                 "scenario": scenario_contract(), "settings": default_settings(), "current_role_id": None,
                 "messages": [], "pending_input": None, "protocol": None, "forecast": None,
                 "protocol_status": "pending", "vote_summary": None, "result": None, "error": None}
        session = cls(store, {"snapshot": state, "owner": owner, "events": [], "commands": {}, "settings_saved": False,
                              "instructions": {}, "result_input": None}, images)
        session.save()
        return session

    def public(self):
        state = self.state
        actions = []
        if state["status"] == "draft":
            actions = ["settings", "cancel"]
            if self.record.get("settings_saved"):
                actions.append("start")
        elif state["status"] == "running":
            actions = ["cancel", "pause" if state["pause_state"] == "none" else "continue"]
            if state["pending_input"] and state["pause_state"] == "none":
                actions.append("submit_input")
            if state["phase"] in SPEECH_PHASES:
                actions.append("add_instruction")
        elif state["status"] == "failed" and (state["error"] or {}).get("code") == "RESULT_FAILED":
            actions = ["retry_result"]
        result = state["result"]
        if (state["status"] == "completed" and result and result.get("model_version") != MODEL_VERSION
                and self.record.get("result_input")):
            result = self.final_projection()
        return {**state, "result": result, "available_actions": actions}

    def save(self):
        self.store.save(self.record)

    def emit(self, kind, payload=None):
        self.state["last_event_id"] += 1
        events = self.record["events"]
        events.append({"event_id": self.state["last_event_id"], "type": kind, "payload": payload or {}})
        if len(events) > EVENT_LIMIT:
            del events[:-EVENT_LIMIT]

    def event_page(self, after):
        events = self.record["events"]
        if after > self.state["last_event_id"] or (events and after < events[0]["event_id"] - 1):
            raise error(409, "EVENT_CURSOR_EXPIRED", "Загрузите актуальное состояние игры.")
        page = [event for event in events if event["event_id"] > after][:EVENT_PAGE]
        cursor = page[-1]["event_id"] if page else after
        return {"events": page, "next_cursor": cursor, "has_more": cursor < self.state["last_event_id"]}

    def command(self, key, command, body, apply):
        fingerprint = hashlib.sha256(json.dumps([command, body], sort_keys=True).encode()).hexdigest()
        entry = self.record["commands"].get(key)
        if entry is not None:
            if entry["fingerprint"] != fingerprint:
                raise error(409, "IDEMPOTENCY_CONFLICT", "Для другой команды нужен новый ключ.")
            return entry["response"]
        response = apply()
        # Copy snapshot data before the engine can mutate it again.
        self.record["commands"][key] = {"fingerprint": fingerprint, "response": json.loads(json.dumps(response))}
        self.save()
        self.changed.set()
        return response

    async def checkpoint(self):
        self.in_step = False
        if self.state["pause_state"] == "requested":
            self.state["pause_state"] = "paused"
            self.emit("pause.changed")
            self.save()
        while self.state["pause_state"] == "paused":
            self.changed.clear()
            await self.changed.wait()
        self.in_step = True

    async def begin_phase(self, phase):
        await self.checkpoint()
        if phase == self.state["phase"] and self.state["current_role_id"] is None:
            return
        self.state.update(phase=phase, current_role_id=None)
        self.emit("phase.changed")
        self.save()

    async def begin_turn(self, role_id, turn, voting):
        await self.checkpoint()
        self.state["current_role_id"] = role_id
        self.emit("turn.started", {"role_id": role_id, "turn_id": str(turn)})
        role = next(role for role in self.state["settings"]["roles"] if role["role_id"] == role_id)
        if role["control_mode"] == "ai":
            instructions = [] if voting else self.record["instructions"].pop(role_id, [])
            self.save()
            return None, instructions
        self.in_step = False
        pending = {"input_id": uuid4().hex, "role_id": role_id, "type": "vote" if voting else "speech"}
        if voting:
            pending.update(protocol_version=self.state["protocol"]["version"], allowed_votes=["for", "against", "abstain"])
        else:
            pending["turn_id"] = str(turn)
        self.state["pending_input"] = pending
        self.emit("input.requested")
        self.save()
        while self.reply is None or self.state["pause_state"] != "none":
            self.changed.clear()
            await self.changed.wait()
        response, self.reply = self.reply, None
        self.in_step = True
        return response, []

    def record_history(self, history):
        phase = self.state["phase"]
        if phase not in SPEECH_PHASES or self.history_offset == len(history):
            return
        role_by_name = {role["name"]: role["id"] for role in self.state["scenario"]["roles"]}
        for row in history[self.history_offset:]:
            if not row["command"]:
                continue
            turn = str(row["turn"])
            message = {"message_id": turn, "turn_id": turn, "role_id": role_by_name[row["speaker"]],
                       "phase": phase, "content": row["command"]}
            self.state["messages"].append(message)
            self.emit("message.created", message)
        self.history_offset = len(history)
        self.save()

    async def prepare_protocol(self, state, profiles, total_cost, levers):
        await self.begin_phase("preparing_protocol")
        self.state["protocol"] = make_protocol(state, levers)
        await self.begin_phase("forecasting")
        raw = {"status": "completed", "state": state, "total_cost": total_cost,
               "players": [{key: value for key, value in profile.items() if key != "llm"} for profile in profiles],
               "consensus_reached": True,
               "voting_summary": {"records": [{"player": profile["name"], "vote": "ЗА"} for profile in profiles]}}
        self.state["forecast"] = await asyncio.to_thread(projection, raw, self.state["protocol"]["version"],
                                                         basis="proposed_protocol", images=False)

    def forecast_context(self):
        return "\n".join(f"{item['label']}: {item['final_value']}"
                         for item in self.state["forecast"]["indicators"])

    def fail(self, code, text):
        self.state.update(status="failed", error={"code": code, "message": text},
                          pending_input=None, current_role_id=None, pause_state="none")
        self.emit("game.failed")
        self.save()

    def final_projection(self):
        raw = self.record["result_input"]
        basis = "accepted_protocol" if self.state["protocol_status"] == "accepted" else "no_agreement"
        return projection(raw, self.state["protocol"]["version"], basis=basis, images=self.images)

    async def calculate_result(self):
        await self.checkpoint()
        result = await asyncio.to_thread(self.final_projection)
        await self.checkpoint()
        self.state.update(status="completed", phase=None, result=result)
        self.emit("game.completed")
        self.save()

    async def play(self, factory, options, rag):
        engine = NegotiationEngine()
        for key, value in options.items():
            setattr(engine, key, value)
        roles = self.state["settings"]["roles"]
        engine.players = game_profiles({role["role_id"]: role["strategy"] for role in roles if role["strategy"]},
                                       factory, human_roles={role["role_id"] for role in roles
                                                             if role["control_mode"] == "human"})
        engine.settings = game_settings()
        engine.initial_roles, engine.session, engine.rag_config = roles, self, rag
        raw = await engine.run_game()
        if raw["status"] != "completed":
            code = {"preparing_protocol": "PROTOCOL_FAILED", "forecasting": "FORECAST_FAILED"}.get(
                self.state["phase"], "GAME_FAILED")
            self.fail(code, "Не удалось завершить текущий этап игры.")
            return
        self.record["result_input"] = {key: raw[key] for key in (
            "status", "state", "total_cost", "consensus_reached", "voting_summary")}
        self.record["result_input"]["players"] = [{key: role[key] for key in ("id", "name", "budget")}
                                                   for role in raw["players"]]
        self.state.update(protocol_status="accepted" if raw["consensus_reached"] else "rejected",
                          vote_summary=votes(raw), phase="calculating_result", current_role_id=None)
        self.emit("vote.closed")
        self.emit("phase.changed")
        self.save()
        await self.calculate_result()
