"""Public response fields derived from a saved game."""

from pathlib import Path

from consequences_model import forecast
from consequences_model.catalog import CONDITIONS, OUTCOMES
from negotiation_game.engine import _get_default_settings
from negotiation_game.report import render_partial_report

from .scenario import ROOT, ROLES


ROLE_BY_NAME = {role["player_name"]: role["player_id"] for role in ROLES}
PHASES = {1: "opening", 2: "bargaining", 3: "voting"}
VOTES = {"ЗА": "for", "ПРОТИВ": "against", "ВОЗДЕРЖАЛСЯ": "abstain", None: None}
DECISIONS = {"accept": "принято", "reject": "отклонено", "counter": "встречное предложение"}


def illustration(outcome_id: str) -> Path | None:
    # Preserve image URLs already present in exported reports.
    if outcome_id in OUTCOMES or outcome_id in {"holding_paid", "city_paid"}:
        path = ROOT / "assets" / "consequences" / f"{outcome_id}.png"
        if path.is_file():
            return path
    return None


def condition_text(value):
    if isinstance(value, bool):
        return "да" if value else "нет"
    return str(value)


def action_labels(actions: list[dict]) -> list[str]:
    labels = []
    for action in actions:
        kind = action["kind"]
        if kind == "PLEDGE":
            labels.append(f"Взнос: {action['contribution']} ₽")
        elif kind == "LEVER":
            labels.append(f"{action['title']}: {condition_text(action['value'])}")
        elif kind == "DEMAND":
            value = action["value"]
            value_text = f"{value} ₽" if action["demand_type"] == "pledge" else condition_text(value)
            labels.append(f"Требование {action['id']} к {action['target']}: {action['title']} ({value_text})")
        elif kind == "DEMAND_RESPONSE":
            labels.append(f"Ответ на требование {action['demand_id']}: {DECISIONS[action['decision']]}")
        elif kind == "DEMAND_WITHDRAWN":
            labels.append(f"Требование {action['demand_id']} отозвано")
    return labels


def transcript(history: list[dict]) -> list[dict]:
    return [{
        "turn": row["turn"],
        "phase": "last_call" if row.get("is_last_call") else PHASES[row["phase"]],
        "role_id": ROLE_BY_NAME[row["speaker"]],
        "text": row["command"],
        "actions": action_labels(row["action"].get("applied", [])),
        "status": row["action"]["status"],
    } for row in history]


def public_game(game_id: str, raw: dict, images: bool) -> dict:
    status = raw["status"]
    response = {"game_id": game_id, "status": status}
    if status == "queued":
        return response

    history = raw["history"]
    turns = transcript(history)
    if status == "completed":
        response["result"] = completed_game(raw, turns, images)
        return response

    reason = None
    if status == "failed":
        reason = "Не удалось завершить игру. Запустите новую партию."
        response["error"] = {"code": "provider_unavailable", "message": reason}
    report = render_partial_report(history, raw.get("state") or {"players": {}}, raw.get("total_cost", 0),
                                   _get_default_settings()["levers"], status, reason)
    response["progress"] = {"transcript": turns, "report_markdown": report}
    return response


def completed_game(raw: dict, turns: list[dict], images: bool) -> dict:
    state = raw["state"]
    voting = raw["voting_summary"]
    prediction = forecast(raw)
    outcome = prediction["outcome"]
    outcome_id = outcome["id"]
    return {
        "accepted": raw["consensus_reached"],
        "budget_closed": voting["budget_closed"],
        "total_cost_rub": raw["total_cost"],
        "pledged_rub": raw["total_money"],
        "deficit_rub": raw["deficit"],
        "contributions": [
            {"role_id": role_id, "pledged_rub": state["players"][name]["contribution"] or 0,
             "spent_on_conditions_rub": state["players"][name]["spent_on_levers"]}
            for role_id, name in state["player_ids"].items()
        ],
        "conditions": [{"id": condition_id, "owner_role_id": CONDITIONS[condition_id]["owner"], "value": value}
                       for condition_id, value in state["levers"].items()],
        "votes": [{"role_id": ROLE_BY_NAME[row["player"]], "value": VOTES[row["vote"]], "status": row["status"]}
                  for row in voting["records"]],
        "transcript": turns,
        "negotiation_report_markdown": raw["report"],
        "consequences": {
            "model_version": prediction["model_version"],
            "financial_load": prediction["financial_load"],
            "outcome_id": outcome_id,
            "outcome_title": outcome["name"],
            "executed_rub": prediction["paid"],
            "commissioning_month": prediction["commissioning_month"],
            "report_markdown": prediction["report"],
            "herald_text": prediction["herald_text"],
            "image_url": f"/api/v1/illustrations/{outcome_id}.png" if images and illustration(outcome_id) else None,
        },
    }
