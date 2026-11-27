"""Advice on individual questionnaire answers based on a finished protocol."""

from math import ceil

from pydantic import BaseModel

from negotiation_game.report import format_money

from .questionnaires import MILLION, QUESTIONNAIRES


class AnswerAdvice(BaseModel):
    field_id: str
    question: str
    chosen: str
    suggested: str
    reason: str


class QuestionnaireReview(BaseModel):
    context: str
    items: list[AnswerAdvice]


def questionnaire_review(state: dict, role_id: str, answers: dict) -> QuestionnaireReview:
    protocol = {item["item_id"]: item for item in (state.get("protocol") or {}).get("items", [])}
    funding = {row["role_id"]: row["amount_rub"]
               for row in protocol.get("project_funding", {}).get("funding", [])}
    total = state["scenario"]["total_cost_rub"]
    collected = sum(round(value * 100) for value in funding.values()) / 100
    gap = max(0, round(total - collected, 2))
    context = ""
    if funding:
        context = f"В проекте протокола было {format_money(collected)} из {format_money(total)}"
        context += f" Не хватило {format_money(gap)}" if gap else " Смету закрыли."

    fields = {field["id"]: field for field in QUESTIONNAIRES[role_id]["fields"]}
    items = []

    def recommend(field_id, value, reason):
        field = fields[field_id]

        def label(answer):
            if "number_range" in field:
                return f"{answer} {field['number_range']['unit']}"
            return next(option["label"] for option in field["options"] if option["value"] == answer)

        items.append(AnswerAdvice(field_id=field_id, question=field["label"], chosen=label(answers[field_id]),
                                  suggested=label(value), reason=reason))

    def agreed(key):
        return protocol.get(key, {}).get("value")

    all_answers = {role["role_id"]: role.get("answers") or {} for role in state["settings"]["roles"]}
    if role_id == "city_administration" and all_answers["city_residents"].get("water_supply"):
        water = ("В проекте закрепили подвоз, который жители отметили обязательным условием."
                 if agreed("water_supply") else
                 "Жители выбрали обязательный подвоз, а в проекте протокола он отсутствовал.")
        recommend("water_supply", True, water + " Если включите подвоз, укажите комфортный взнос и потолок до 10 млн ₽.")
    elif role_id == "industrial_holding":
        if all_answers["environmental_ngo"].get("plant_mode") == "70%":
            recommend("plant_mode", "70%", "НКО выбрала требование о снижении мощности до 70%. "
                      "Выберите этот режим, если готовы к уступке по мощности.")
        else:
            recommend("tax_relief", answers["tax_relief"], "Увяжите требование о льготах с комфортным взносом. "
                      "Если льготы обязательны, они нужны при взносе выше комфортного уровня.")
    elif role_id == "regional_government":
        holding = funding.get("industrial_holding")
        reason = f"В проекте взнос холдинга составил {format_money(holding)} " if holding is not None else ""
        recommend("holding_min", answers["holding_min"],
                  reason + "Сохраните этот минимум, если область готова выделять средства только при таком участии холдинга.")
    elif role_id == "city_residents":
        if not agreed("water_supply") or not agreed("tariffs_freeze"):
            if not agreed("water_supply"):
                reason = ("Вы уже отметили подвоз обязательным, но мэрия не включила его в проект. "
                          "Сохраните этот ответ, если подвоз остаётся вашим приоритетом."
                          if answers["water_supply"] else
                          "В проекте отсутствовал подвоз воды. Отметьте его обязательным, "
                          "если это ваше главное требование до ввода очистных.")
                recommend("water_supply", True, reason)
            if not agreed("tariffs_freeze"):
                reason = ("Вы уже требовали заморозку тарифов, но она не вошла в проект. "
                          "Сохраните этот ответ, если защита от повышения остаётся вашим приоритетом."
                          if answers["tariffs_freeze"] else
                          "В проекте не закрепили заморозку тарифов. "
                          "Выберите её как обязательное условие, если хотите защитить жителей от повышения.")
                recommend("tariffs_freeze", True, reason)
        else:
            recommend("water_supply", True, "В проекте уже были подвоз и заморозка тарифов. "
                      "Сохраните подвоз как обязательное условие, если хотите закрепить эту защиту за ролью.")
    elif role_id == "environmental_ngo":
        reason = ("В проекте уже были открытые датчики. Сохраните публичный доступ к замерам как требование."
                  if agreed("open_sensors") else
                  "В проекте отсутствовали открытые датчики. Отметьте их обязательными, если нужен публичный контроль.")
        recommend("open_sensors", True, reason)
        if agreed("plant_mode") == "100%":
            recommend("plant_mode", "70%", "В проекте сохранили полную мощность. "
                      "Выберите 70%, если для НКО важно ограничить производство до запуска очистных.")

    if gap and funding and "max_money" in answers:
        field_id = "start_money" if "start_money" in answers else "comfort_money"
        cap = answers["max_money"]
        if role_id == "city_administration" and agreed("water_supply"):
            cap = min(cap, 10)
        amount = min(cap, ceil((funding.get(role_id, 0) + gap) / MILLION))
        if amount > answers[field_id] and not (role_id == "city_administration" and items):
            recommend(field_id, amount, "В проекте остался дефицит. Выберите этот взнос, если готовы "
                      "раньше предложить больше средств в пределах своего потолка.")

    if not items:
        recommend("holding_demand", answers["holding_demand"], "Сохраните этот нижний порог, "
                  "если такой вклад холдинга всё ещё нужен городу для софинансирования.")
    return QuestionnaireReview(context=context, items=items)
