"""Предложения по анкете для ходов, в которых агент сохранил позицию."""

from copy import deepcopy
from dataclasses import dataclass

from .report import exact_money
from .rules import contribution_limit, prepare_player_turn, project_funding
from .schemas import Demand, DemandResponse, PlayerTurn


MILLION = 1_000_000
FUNDING_PROGRESS = {
    "city_administration": "Город свою часть добавил. Остальным сторонам осталось собрать {amount}.",
    "industrial_holding": "Теперь для полного финансирования стройки нужен ещё вклад в {amount}.",
    "regional_government": "После подтверждения областной доли в смете остаётся дефицит {amount}.",
}


def compatible_funding_plan(state, roles, cost, objections, *, minimum=None):
    """Дособирает смету в пределах комфортных взносов при совместимых условиях."""
    pledges = {name: player["contribution"] or 0 for name, player in state["players"].items()}
    if not project_funding(state, cost)[1]:
        if minimum and pledges[minimum[0]] < minimum[1]:
            return None
        return pledges if not any(objections(role_id, state) for role_id in roles) else None

    floors = pledges.copy()
    if minimum:
        name, amount = minimum
        floors[name] = max(pledges[name], amount)
    goal = round(cost * 100)
    if sum(round(value * 100) for value in floors.values()) > goal:
        return None

    rejected_pledges = {item["target"] for item in state["demands"]
                        if item["demand_type"] == "pledge" and item.get("response") == "reject"
                        and item["status"] == "pending"}
    projected = deepcopy(state)
    ceilings = pledges.copy()
    for role_id, name in state["player_ids"].items():
        answers = roles[role_id]
        if answers.get("custom_instructions") or name in rejected_pledges:
            continue
        player = projected["players"][name]
        ceiling = min(contribution_limit(player), answers.get("comfort_money", 0) * MILLION)
        ceilings[name] = max(pledges[name], ceiling)
        player["contribution"] = ceilings[name]

    collected, deficit = project_funding(projected, cost)
    if (deficit or any(ceilings[name] < floor for name, floor in floors.items())
            or any(objections(role_id, projected) for role_id in roles)):
        return None

    preferred = floors.copy()
    for item in state["demands"]:
        if item["demand_type"] == "pledge" and item["status"] == "pending" and not item.get("response"):
            target, amount = item["target"], item["value"]
            if amount <= ceilings[target]:
                preferred[target] = max(preferred[target], amount)

    def allocate(minimums):
        # Сокращаем излишек в обратном порядке ходов, сохраняя смету и красные линии.
        surplus = round(collected * 100) - goal
        for name, ceiling in ceilings.items():
            projected["players"][name]["contribution"] = ceiling
        for name in reversed(tuple(projected["players"])):
            player = projected["players"][name]
            top = round(ceilings[name] * 100)
            left, right = 0, min(surplus, top - round(minimums[name] * 100))
            while left < right:
                cut = (left + right + 1) // 2
                player["contribution"] = (top - cut) / 100
                if any(objections(role_id, projected) for role_id in roles):
                    right = cut - 1
                else:
                    left = cut
            player["contribution"] = (top - left) / 100
            surplus -= left
        if surplus == 0:
            return {name: player["contribution"] for name, player in projected["players"].items()}
        return None

    return allocate(preferred) or allocate(floors)


@dataclass(frozen=True)
class NegotiatedMove:
    answer: PlayerTurn
    state: dict
    action: dict
    comment: str = ""


def _explicit_reply_context(answer, state):
    rejected_ids = {response.demand_id for response in answer.responses if response.decision == "reject"}
    details = []
    for demand in state["demands"]:
        if demand["id"] not in rejected_ids:
            continue
        if demand["demand_type"] == "pledge":
            amount = state["players"][demand["target"]]["contribution"] or 0
            details.append(f"В проекте сохраняем взнос {exact_money(amount)} вместо запрошенных {exact_money(demand['value'])}.")
        elif demand["lever_id"] == "plant_mode":
            details.append(f"Сохраняем работу предприятия на {state['levers']['plant_mode']} мощности.")
        elif demand["lever_id"] == "timeline":
            details.append(f"По текущему графику сохраняем срок реконструкции {state['levers']['timeline']} мес.")
        else:
            details.append(f"Пока сохраняем условия действующего проекта по пункту «{demand['title']}».")
    return " ".join(details)


def advance_negotiation(move, *, phase, role_id, roles, before, levers, cost, objections, requests):
    """Проводит доступный ход роли по её анкете через штатный валидатор."""
    answer = move.answer
    if answer.responses:
        comment = _explicit_reply_context(answer, move.state)
        return NegotiatedMove(answer, move.state, move.action, comment)
    if (answer.own_contribution_millions is not None or answer.own_levers or answer.demands
            or answer.withdrawn_demands or roles[role_id].get("custom_instructions")):
        return move

    speaker = before["player_ids"][role_id]

    def amend(comment="", **fields):
        answer = move.answer.model_copy(update=fields)
        try:
            state, action = prepare_player_turn(answer, speaker, before, levers, cost)
        except ValueError:
            return None
        return NegotiatedMove(answer, state, action, comment)

    if phase != "Вступление":
        pending = [d for d in move.state["demands"] if d["target"] == speaker
                   and d["status"] == "pending" and not d.get("response")]
        if pending:
            incoming = pending[0]
            if incoming["lever_id"] == "timeline":
                # Кратчайший из запрошенных сроков одновременно отвечает на остальные запросы по сроку.
                incoming = min((d for d in pending if d["lever_id"] == "timeline"), key=lambda d: d["value"])
            identifier = incoming["id"]
            value = incoming["value"]
            author_id = next(key for key, name in before["player_ids"].items() if name == incoming["from"])
            accept = [DemandResponse(demand_id=identifier, decision="accept")]
            if incoming["demand_type"] == "pledge":
                plan = compatible_funding_plan(move.state, roles, cost, objections, minimum=(speaker, value))
                # Согласуем взнос из совместимого плана. Сумма требования задаёт его нижнюю границу.
                accepted = amend(responses=accept, own_contribution_millions=plan[speaker] / MILLION,
                                 addressed_to=author_id) if plan is not None else None
                reason = f"Сейчас не можем подтвердить запрошенные {exact_money(value)} в составе общего плана взносов."
            else:
                lever = incoming["lever_id"]
                accepted = amend(responses=accept, own_levers={lever: value}, addressed_to=author_id)
                introduced = (set(objections(role_id, accepted.state)) - set(objections(role_id, move.state))
                              if accepted else set())
                if introduced:
                    accepted = None
                if accepted and lever in {"water_supply", "tax_relief"} and not roles[role_id].get(lever):
                    # Уступка вопреки исходной позиции оправдана при совместимом обеспеченном плане.
                    if compatible_funding_plan(accepted.state, roles, cost, objections) is None:
                        accepted = None
                if lever == "plant_mode":
                    current = move.state["levers"][lever]
                    reason = f"Запрос касается {value} мощности. По нашей позиции сохраняем работу предприятия на {current}."
                elif introduced:
                    reason = f"При такой поправке {', '.join(sorted(introduced)).rstrip('.')}."
                elif lever == "water_supply":
                    reason = "Подвоз требует отдельного финансирования. При текущем распределении обязательств мы не можем его подтвердить."
                elif lever == "tax_relief":
                    reason = "Для такой уступки сначала нужен общий план взносов, который область сможет поддержать."
                else:
                    reason = "В текущем проекте наша сторона не готова взять на себя это обязательство."
            if accepted:
                return accepted
            rejected = amend(reason, responses=[DemandResponse(demand_id=identifier, decision="reject")],
                             addressed_to=author_id)
            if rejected:
                return rejected

    if phase != "Вступление":
        plan = compatible_funding_plan(move.state, roles, cost, objections)
        pledge = move.state["players"][speaker]["contribution"] or 0
        if plan is not None and plan[speaker] > pledge:
            funded = amend(own_contribution_millions=plan[speaker] / MILLION)
            if funded:
                _, deficit = project_funding(funded.state, cost)
                template = FUNDING_PROGRESS.get(role_id, "После нашей поправки осталось собрать {amount}.")
                comment = (template.format(amount=exact_money(deficit)) if deficit else
                           "Этим взносом закрываем остаток сметы.")
                return NegotiatedMove(funded.answer, funded.state, funded.action, comment)

    if requests:
        item = requests[0]
        demand = Demand(target=item["target"], demand_type="lever", lever_id=item["lever_id"],
                        value=item["value"], text="Требование по анкете", counter_to=None)
        requested = amend(demands=[*move.answer.demands, demand], addressed_to=demand.target)
        if requested:
            return requested
    return move
