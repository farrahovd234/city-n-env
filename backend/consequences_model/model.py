"""Прогноз по итогу игры: протокол → исполнение → состояние города → исход."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .catalog import (CONDITIONS, DELAY_PARTIAL_RECONSTRUCTION, DELAY_UNDERFUNDED, FULL, GUILT, HORIZON_MONTHS,
                      MIN_COVERAGE_TO_BUILD, MODEL_VERSION, NGO, NONE, OUTCOMES, PAID_PART, PARTIAL,
                      RECONSTRUCTION_OWNER, RESIDENTS, ROLE_LABELS, SENSORS, STANDALONE_CONDITIONS, WATER,
                      WATER_MAX_MONTHS)
from .explain import fired_rules
from .protocol import Protocol, read_protocol
from .report import render_herald_prompt, render_herald_text, render_report
from .state import city_state, fates


def execute(protocol: Protocol, excluded: str | None = None) -> dict[str, Any]:
    """Шаг 1: насколько каждая роль выполнила свои обязательства.

    excluded — роль, чьи обязательства считаются невыполненными (контрфактический прогон).
    """
    def by_vote(owner: str) -> str:
        if owner == excluded:
            return NONE
        return FULL if protocol.supports(owner) else PARTIAL

    if protocol.accepted:
        contributions = {role: by_vote(role) for role in protocol.contributions}
        conditions = {condition: by_vote(CONDITIONS[condition]["owner"]) for condition in protocol.included}
        reconstruction = by_vote(RECONSTRUCTION_OWNER)
    else:
        contributions = dict.fromkeys(protocol.contributions, NONE)
        conditions = dict.fromkeys(protocol.included, NONE)
        for condition in STANDALONE_CONDITIONS:
            owner = CONDITIONS[condition]["owner"]
            if condition in conditions and owner != excluded and protocol.supports(owner):
                conditions[condition] = PARTIAL
        reconstruction = NONE
    return {"contributions": contributions, "conditions": conditions, "reconstruction": reconstruction}


def paid_in(protocol: Protocol, execution: dict[str, Any]) -> float:
    """Сколько денег реально внесено: полностью — весь взнос, частично — половина."""
    return sum(amount * PAID_PART[execution["contributions"][role]] for role, amount in protocol.contributions.items())


def commissioning(protocol: Protocol, execution: dict[str, Any]) -> tuple[int | None, list[tuple[int, str]]]:
    """Месяц ввода очистных от голосования (None — не введены к году 10) и задержки с причинами."""
    coverage = paid_in(protocol, execution) / protocol.total_cost
    reconstruction = execution["reconstruction"]
    if reconstruction == NONE or coverage < MIN_COVERAGE_TO_BUILD:
        return None, []
    delays = []
    if reconstruction == PARTIAL:
        delays.append((DELAY_PARTIAL_RECONSTRUCTION, "реконструкция выполнена частично"))
    if coverage < 1:
        delays.append((DELAY_UNDERFUNDED, "смета покрыта не полностью"))
    month = protocol.promised_months + sum(months for months, _ in delays)
    return (month, delays) if month <= HORIZON_MONTHS else (None, delays)


def shares(protocol: Protocol) -> dict[str, float]:
    """Доля каждой роли в смете по заявленным взносам."""
    return {role: protocol.contributions.get(role, 0) / protocol.total_cost for role in ROLE_LABELS}


# Исходы проверяются по порядку, срабатывает первый подходящий.
ACCEPTED_RULES = (
    ("nedostroy", lambda f: f["month"] is None),
    ("without_residents", lambda f: not f["support"][RESIDENTS] and not f["support"][NGO]),
    ("dolgostroy", lambda f: f["late_water_gap"]),
    ("open_river", lambda f: f["month"] == f["promised_months"] and f["monitoring_ok"]
        and all(value == FULL for value in f["levels"]) and f["support"][RESIDENTS] and f["support"][NGO]),
    ("closed_data", lambda f: not f["monitoring_ok"]),
    ("compromise", lambda f: True),
)
REJECTED_RULES = (
    ("each_for_self", lambda f: bool(f["standalone_measures"])),
    ("stagnation", lambda f: True),
)


def choose_outcome(protocol: Protocol, facts: dict[str, Any]) -> dict[str, str]:
    rules = ACCEPTED_RULES if protocol.accepted else REJECTED_RULES
    outcome_id = next(outcome_id for outcome_id, applies in rules if applies(facts))
    return {"id": outcome_id, **OUTCOMES[outcome_id]}


def simulate(protocol: Protocol, excluded: str | None = None) -> dict[str, Any]:
    execution = execute(protocol, excluded)
    month, delays = commissioning(protocol, execution)
    # Условие влияет на город, только если выполнено полностью.
    acting = {condition for condition, value in execution["conditions"].items() if value == FULL}
    standalone_measures = [condition for condition in STANDALONE_CONDITIONS
                           if not protocol.accepted and execution["conditions"].get(condition) == PARTIAL]
    facts = {
        "month": month,
        "delays": delays,
        "promised_months": protocol.promised_months,
        "paid": paid_in(protocol, execution),
        "contributions": execution["contributions"],
        "conditions": execution["conditions"],
        "reconstruction": execution["reconstruction"],
        "levels": [*execution["contributions"].values(), *execution["conditions"].values(),
                   execution["reconstruction"]],
        "acting": acting,
        "included": protocol.included,
        "guilt": protocol.conditions[GUILT] if protocol.accepted else None,
        "support": {role: protocol.supports(role) for role in ROLE_LABELS},
        "shares": shares(protocol),
        "late_water_gap": month is not None and month > protocol.promised_months
        and (WATER not in acting or month > WATER_MAX_MONTHS),
        "standalone_measures": standalone_measures,
        "over_budget": {role for role in protocol.budgets if protocol.overspend(role) > 0},
        "monitoring_ok": SENSORS in acting,
    }
    return {"execution": execution, "facts": facts, "outcome": choose_outcome(protocol, facts)}


def forecast(game_result: dict[str, Any]) -> dict[str, Any]:
    """Рассчитывает прогноз по итогу партии."""
    game_status = game_result.get("status", "completed")
    if game_status != "completed":
        labels = {"running": "продолжается", "failed": "прервана из-за ошибки", "cancelled": "отменена"}
        label = labels.get(game_status, "имеет неизвестный статус") if isinstance(game_status, str) else "имеет неизвестный статус"
        return {
            "status": "skipped",
            "game_status": game_status,
            "herald_text": "Игра не завершена. Итоги последствий появятся после завершения партии.",
            "report": f"# Прогноз не рассчитан\n\nИгра не завершена: {label}. Смотрите промежуточный отчёт переговоров.",
            "herald_prompt": "",
        }
    protocol = read_protocol(game_result)
    run = simulate(protocol)
    facts = run["facts"]
    state = city_state(facts)
    without_role = {role: simulate(protocol, excluded=role)["outcome"]["name"] for role in ROLE_LABELS}
    result = {
        "model_version": MODEL_VERSION,
        "outcome": run["outcome"],
        "protocol": {**asdict(protocol), "included": protocol.included},
        "financial_load": protocol.financial_load(),
        "promised_months": protocol.promised_months,
        "paid": facts["paid"],
        "execution": run["execution"],
        "commissioning_month": facts["month"],
        "state": state,
        "fates": fates(facts, state),
        "explanation": {"rules": fired_rules(protocol, facts, state, run["outcome"]), "without_role": without_role},
        "warnings": list(protocol.warnings),
    }
    result["report"] = render_report(result)
    result["herald_text"] = render_herald_text(result)
    result["herald_prompt"] = render_herald_prompt(result)
    return result
