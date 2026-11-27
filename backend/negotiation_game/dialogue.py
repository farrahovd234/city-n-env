"""Доступные аргументы анкеты и подсказки по текущему проекту соглашения."""

import json
import re

from .report import exact_money
from .rules import contribution_limit, project_funding
from .schemas import speech_key


MILLION = 1_000_000
ADMIN = "city_administration"
HOLDING = "industrial_holding"
REGION = "regional_government"
RESIDENTS = "city_residents"
NGO = "environmental_ngo"

# Условия, которые роль вправе запрашивать у другой стороны, следуя своей анкете.
REQUESTABLE_CONDITIONS = {
    ADMIN: ("timeline",),
    HOLDING: ("tax_relief", "protest_moratorium"),
    REGION: ("timeline",),
    RESIDENTS: ("water_supply", "tariffs_freeze", "open_sensors", "timeline"),
    NGO: ("plant_mode", "timeline"),
}


FUNDING_REPLIES = {
    ADMIN: "Городу нужно увязать оставшиеся расходы с обязательствами перед жителями.",
    HOLDING: "Просим область уточнить, какую часть разницы она готова покрыть.",
    REGION: "Предлагаю сверить, какие суммы ещё можно подтвердить до голосования.",
}


ROLE_ARGUMENTS = {
    ADMIN: {
        "cost_split": "Город не потянет реконструкцию один. Нам нужно распределить расходы между городом, областью и предприятием.",
        "water_cost": "Подвоз питьевой воды требует отдельной статьи расходов. Если её включаем, придётся заново распределить взносы на стройку.",
        "city_delivery": "Жителям важно понимать, как город обеспечит их водой на время работ. Нужен план, который можно выполнить с имеющимися средствами.",
        "tariffs": "Повышение тарифов сейчас ударит по тем, кто уже пострадал от аварии. Стоимость работ нужно обсуждать отдельно от платежей жителей.",
    },
    HOLDING: {
        "jobs": "Для города важно сохранить производство и рабочие места, пока идут работы. Давайте увяжем режим предприятия со сроком запуска очистных.",
        "shared_cost": "Мы готовы участвовать в реконструкции. Просим область подтвердить свою долю, чтобы предприятие могло планировать собственный взнос.",
        "schedule": "Реальный срок работ важнее красивой даты. Предлагаю увязать график с тем, когда финансирование станет доступно.",
        "operation": "Ограничения для предприятия нужно привязать к периоду реконструкции. Так будет понятно, когда стороны вернутся к обсуждению режима работы.",
    },
    REGION: {
        "cofunding": "Областные деньги должны дополнять вклад предприятия. Нужны подтверждённые суммы, чтобы понимать, какую часть проекта ещё предстоит оплатить.",
        "accountability": "Предлагаю сначала сверить, кто за что отвечает. Тогда у комиссии будут обязательства, которые можно проверить после заседания.",
        "milestones": "По срокам нам нужен ориентир для контроля работ. Если график сдвинется, стороны должны понимать, кто и когда вернётся к этому вопросу.",
        "seal_funding": "Перед голосованием предлагаю сверить деньги, закреплённые в проекте. Условные обещания оставим предметом переговоров до их подтверждения.",
    },
    RESIDENTS: {
        "daily_life": "Семьям нужна безопасная вода уже сейчас. Даже если очистные заработают вовремя, людям придётся как-то жить до их запуска.",
        "tariff_impact": "Ремонт не должен обернуться дополнительными платежами для семей. Просим администрацию объяснить, что будет с тарифами на воду.",
        "public_control": "Нам важно самим видеть, меняется ли качество воды. Это поможет жителям проверить, как стороны выполняют обещанное.",
        "delivery_details": "Если в проект попадёт подвоз воды, сразу уточним, как о нём узнают жители разных районов. Одного обещания о доставке для этого мало.",
    },
    NGO: {
        "measurements": "Нам важно заранее договориться, как будут проверяться сбросы. Жители должны иметь возможность сверить результаты сами.",
        "river_load": "Во время реконструкции нагрузка на реку сохранится. Давайте обсуждать, как её снизить до пуска новых очистных.",
        "independent_control": "Чтобы оценить восстановление реки, измерения нужно вести и во время работ, и после запуска очистных. Тогда увидим изменение качества воды.",
        "data_access": "У мониторинга должны быть понятные правила доступа. Предлагаю уточнить, где жители смогут посмотреть результаты замеров.",
    },
}


def discussion_options(role_id, speaker, answers, state, history, phase, total_cost, objections=()) -> dict[str, str]:
    """Подбирает фактические поводы для реплики с учётом уже сказанного."""
    arguments = {}
    opening = phase == "Вступление"
    prior_topics = {row["action"].get("discussion") for row in history}
    stated = {speech_key(row["command"]) for row in history}
    pledge = state["players"][speaker]["contribution"] or 0
    announced_responsibility = any(
        row["speaker"] == speaker and (row["action"].get("discussion") or "").startswith("responsibility_")
        for row in history
    )
    if answers.get("custom_instructions") and not announced_responsibility:
        actual = state["levers"]["guilt"]
        positions = {
            "shared": "разделить ответственность между городом и холдингом",
            "holding": "возложить ответственность на холдинг",
            "city": "возложить ответственность на город",
        }
        for value, position in positions.items():
            if value != actual:
                arguments[f"responsibility_{value}"] = (
                    f"Для нашей поддержки нужно {position}. Сейчас в проекте зафиксировано другое решение. "
                    "Просим обсудить этот пункт до голосования."
                )

    if phase == "Последний раунд" and objections:
        reasons = ". ".join((reason[:1].upper() + reason[1:]).rstrip(".") for reason in objections)
        arguments[f"objections_{role_id}"] = f"В текущем проекте остаются вопросы, важные для нашего голоса. {reasons}."

    if opening and pledge:
        arguments["opening_pledge"] = f"Начинаем переговоры с собственного взноса в {exact_money(pledge)}."

    if not opening:
        for demand in reversed(state["demands"]):
            if demand["target"] != speaker or demand["status"] != "pending" or demand.get("response"):
                continue
            if demand["demand_type"] == "pledge":
                subject = f"ваш запрос на взнос в {exact_money(demand['value'])}"
                follow_up = "Надо сверить, как этот взнос сочетается с долями остальных участников."
            else:
                subject = f"ваше предложение по условию «{demand['title']}»"
                follow_up = {
                    "water_supply": "Сначала сверим, как оплатить доставку воды вместе со стройкой.",
                    "timeline": "Нужно увязать новый срок с графиком работ и финансированием.",
                    "plant_mode": "Нужно согласовать, сколько времени предприятие сможет работать в таком режиме.",
                    "tax_relief": "Области важно понимать, какую сумму предприятие готово подтвердить в обмен.",
                    "protest_moratorium": "Сначала нужно договориться о выполнении обязательств перед жителями.",
                    "guilt": "Важно зафиксировать основания такой ответственности.",
                }.get(demand["lever_id"], "Нужно согласовать порядок выполнения этого обязательства.")
            arguments[f"reply_{demand['id']}"] = f"{demand['from']}, услышали {subject}. {follow_up}"

        if role_id in {ADMIN, HOLDING, REGION}:
            _, deficit = project_funding(state, total_cost)
            for row in reversed(history):
                partner = row["speaker"]
                if partner == speaker:
                    continue
                before = state["players"][partner]["contribution"]
                if not before or not any(
                        action["kind"] == "PLEDGE" and action["contribution"] == before
                        for action in row["action"].get("applied", [])):
                    continue
                funding = (f"До полной сметы остаётся {exact_money(deficit)}. {FUNDING_REPLIES[role_id]}"
                           if deficit else "Сумма собрана. Можно сосредоточиться на условиях, от которых зависит запуск работ.")
                arguments[f"funding_reply_{row['turn']}"] = (
                    f"Учли подтверждённый взнос стороны «{partner}» в {exact_money(before)}. {funding}"
                )
                break

    levers = state["levers"]
    if role_id == RESIDENTS:
        if answers.get("water_supply") and not levers["water_supply"]:
            arguments["missing_water"] = (
                "До запуска очистных семьям по-прежнему нужна питьевая вода. Просим администрацию закрепить доставку на время работ."
            )
        if answers.get("protest_moratorium") is False:
            arguments["protest_rights"] = "Жители хотят сохранить возможность добиваться исполнения обещаний через протесты и суд."
    elif role_id == HOLDING and answers.get("tax_relief") and not levers["tax_relief"]:
        arguments["tax_relief"] = (
            "Если от предприятия нужен взнос выше комфортного уровня, просим область обсудить налоговую льготу."
        )
    elif role_id == NGO and answers.get("plant_mode") == "70%" and levers["plant_mode"] != "70%":
        arguments["production_limit"] = "Просим предприятие ограничить мощность до 70% на время работ. Это снизит нагрузку на реку."
    elif role_id == ADMIN and levers["water_supply"]:
        arguments["water_in_draft"] = "Подвоз воды уже предусмотрен. Нам важно сохранить его в итоговом соглашении."

    role_arguments = ROLE_ARGUMENTS.get(role_id, {})
    if role_id == RESIDENTS and levers["water_supply"]:
        role_arguments = {**role_arguments, "delivery_details":
                          "Подвоз воды уже предусмотрен. Уточним, как жители узнают о графике доставки в своих районах."}
    if role_id == REGION and project_funding(state, total_cost)[1] == 0:
        role_arguments = {**role_arguments, "cofunding":
                          "Взносы подтверждены. Теперь важно распределить ответственность за исполнение обязательств."}
    if role_id == ADMIN and levers["water_supply"]:
        role_arguments = {key: text for key, text in role_arguments.items() if key != "water_cost"}
    if phase == "Последний раунд":
        role_arguments = dict(reversed(role_arguments.items()))
    arguments.update(role_arguments)
    return {key: argument for key, argument in arguments.items()
            if key not in prior_topics and speech_key(argument) not in stated}


def render_discussion(selected, options, decision, history) -> tuple[str, str | None]:
    """Принимает выбор темы от модели, оставляя за игрой формулировку."""
    used = {speech_key(row["command"]) for row in history}
    previous_sentences = {speech_key(sentence) for row in history
                          for sentence in re.split(r"(?<=[.!?])\s+(?=[А-ЯЁ])", row["command"])}
    if not isinstance(selected, str) or selected not in options:
        selected = None
    options = {key: argument for key, argument in options.items()
               if key == selected or not key.startswith("responsibility_")}
    choices = [selected, *[key for key in options if key != selected]] if selected else options
    for key in choices:
        argument = " ".join(sentence for sentence in re.split(r"(?<=[.!?])\s+(?=[А-ЯЁ])", options[key])
                            if speech_key(sentence) not in previous_sentences)
        if not argument:
            continue
        text = f"{decision} {argument}" if decision else argument
        if speech_key(text) not in used:
            return text, key
    return (decision, None) if decision and speech_key(decision) not in used else ("", None)


def funding_hint(state, speaker, role_id, answers, total_cost, recommended=None) -> str:
    player = state["players"][speaker]
    if player["max_budget"] == 0:
        return "У твоей стороны нет бюджета на реконструкцию. Оставь собственный взнос без изменений."
    pledge = player["contribution"] or 0
    _, deficit = project_funding(state, total_cost)
    if recommended is not None and recommended > pledge:
        return (
            f"До полной сметы не хватает {exact_money(deficit)}. "
            f"С совместимой схемой доплат твой итоговый взнос составит {exact_money(recommended)}. "
            f"Если готов подтвердить, передай own_contribution={_json_offer(recommended)}. "
            f"Чтобы явно сохранить свой текущий взнос, передай own_contribution={_json_offer(pledge)}."
        )
    if deficit == 0:
        return "Смета закрыта. Сохрани текущий взнос, если у тебя нет конкретной причины его менять."

    limit = contribution_limit(player)
    comfortable = answers.get("comfort_money", 0) * MILLION
    if role_id == HOLDING and answers.get("tax_relief") and not state["levers"]["tax_relief"]:
        limit = min(limit, max(pledge, comfortable))
    maximum = min(limit, pledge + deficit)
    if maximum <= pledge:
        return "При текущих условиях ты исчерпал лимит взноса. Обсуди условия сделки или запроси недостающие средства у других сторон."

    offers = []
    if pledge < comfortable < maximum:
        offers.append(comfortable)
    offers.append(maximum)
    examples = " или ".join(_json_offer(amount) for amount in offers)
    return (
        f"До полной сметы не хватает {exact_money(deficit)}. "
        f"Ты сейчас вносишь {exact_money(pledge)}. Допустимый предмет торга для own_contribution: {examples}. "
        "Выбери, какую сумму готов подтвердить при текущих условиях. "
        "Если сумма не подходит, оставь прежний взнос и укажи конкретное условие или встречное требование."
    )


def requested_conditions(role_id, answers, state, owners, speaker) -> list[dict]:
    """Показывает новые предметные требования в точном формате вызова."""
    requests = []
    for lever in REQUESTABLE_CONDITIONS.get(role_id, ()):
        if lever not in answers or lever not in owners:
            continue
        desired, actual = answers[lever], state["levers"][lever]
        if lever == "tax_relief" and role_id == HOLDING:
            player = state["players"][speaker]
            comfortable = answers["comfort_money"] * MILLION
            if ((player["contribution"] or 0) <= comfortable
                    and (contribution_limit(player) <= comfortable or not project_funding(state, state["total_cost"])[1])):
                continue
        if (desired is False or desired == actual or (type(desired) is int and desired >= actual)
                or (lever == "plant_mode" and desired != "70%")):
            continue
        target = owners[lever]
        if any(demand["from"] == speaker and demand["target_id"] == target
               and demand["lever_id"] == lever and demand["value"] == desired and not demand.get("withdrawn")
               for demand in state["demands"]):
            continue
        requests.append({"target": target, "lever_id": lever, "value": desired})
    return requests


def condition_requests(requests) -> str:
    if not requests:
        return ""
    return ("\nЕщё не согласованные пункты твоей анкеты. "
            "Если хочешь официально запросить один из них, выбери его в condition_demands: "
            + json.dumps([
                {"target": item["target"], "lever_id": item["lever_id"],
                 "value_json": json.dumps(item["value"]) if type(item["value"]) is bool else str(item["value"]),
                 "counter_to": ""}
                for item in requests
            ], ensure_ascii=False))


def _json_offer(amount):
    millions = f"{amount / MILLION:.8f}".rstrip("0").rstrip(".")
    return f'{{"action":"set","amount_millions":{millions}}}'
