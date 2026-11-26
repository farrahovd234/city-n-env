"""City N questionnaires and the strategies derived from their answers."""

import json
from pathlib import Path


QUESTIONNAIRES = json.loads(Path(__file__).with_name("questionnaires.json").read_text(encoding="utf-8"))
MILLION = 1_000_000
MAX_CUSTOM_INSTRUCTIONS = 6000

ROLE_DESCRIPTIONS = {
    "city_administration": (
        "Вы — глава администрации моногорода N (Мэр). Городские очистные сооружения изношены на 70%. "
        "Доступный резерв городского бюджета — 30 млн ₽. Общая смета проекта реконструкции — 270 млн ₽."
    ),
    "industrial_holding": (
        "Вы — генеральный директор градообразующего холдинга «Промкомплекс» "
        "(3 000 рабочих мест, ключевой налогоплательщик и источник тепла для города). "
        "Ваш резервный бюджет на преодоление кризиса — 180 млн ₽. Общая смета реконструкции — 270 млн ₽."
    ),
    "regional_government": (
        "Вы — вице-губернатор области, председатель согласительной комиссии. "
        "Резерв регионального бюджета на софинансирование — 90 млн ₽. Общая смета реконструкции — 270 млн ₽."
    ),
    "city_residents": (
        "Вы — председатель инициативного комитета жителей города N, пострадавших от загрязнения "
        "водопроводной воды. Финансового бюджета у жителей нет (0 млн ₽). "
        "Ваш рычаг влияния — общественный резонанс, протестная активность или согласие на мораторий."
    ),
    "environmental_ngo": (
        "Вы — руководитель независимой экологической организации «Чистая река». "
        "Финансового взноса в строительную смету вы не делаете (0 млн ₽). "
        "Вы обладаете данными независимых замеров и отвечаете за экологический контроль."
    ),
}
FINANCIAL_FIELDS = {"start_money", "comfort_money", "max_money"}
VOTING_STRATEGY = (
    "[4. ТАКТИКА, АРГУМЕНТЫ И ФИНАЛЬНОЕ ГОЛОСОВАНИЕ]\n"
    "1. Настаивайте на соблюдении ваших требований из блока [3]. "
    "Меняйте только собственные обязательства. Адресуйте требования к чужим условиям их владельцам.\n"
    '2. В финальном раунде голосуйте ЗА (vote: "for"), если общая смета 270 млн ₽ закрыта, '
    "ваш взнос в пределах потолка и соблюдены ключевые условия.\n"
    '3. Если смета не закрыта или ваши красные линии нарушены — голосуйте ПРОТИВ (vote: "against").'
)


def questionnaire_answers(submitted: dict) -> tuple[dict, list]:
    answers = {}
    errors = []

    def reject(path, message):
        errors.append({"path": ["answers", *path], "message": message})

    for role_id in sorted(submitted.keys() - QUESTIONNAIRES.keys()):
        reject([role_id], "Неизвестная роль.")
    for role_id, questionnaire in QUESTIONNAIRES.items():
        if role_id not in submitted:
            reject([role_id], "Заполните анкету этой роли.")
            continue
        values = submitted[role_id]
        fields = {field["id"]: field for field in questionnaire["fields"]}
        for field_id in sorted(values.keys() - fields.keys()):
            reject([role_id, field_id], "Неизвестный вопрос.")
        normalized = {}
        for field_id, field in fields.items():
            value = values.get(field_id, "")
            if field["required"]:
                options = [option["value"] for option in field["options"]]
                if not any(type(value) is type(option) and value == option for option in options):
                    reject([role_id, field_id], "Выберите один из предложенных вариантов.")
                    continue
            elif not isinstance(value, str) or len(value.strip()) > MAX_CUSTOM_INSTRUCTIONS:
                reject([role_id, field_id], f"Введите текст длиной до {MAX_CUSTOM_INSTRUCTIONS} символов.")
                continue
            normalized[field_id] = value.strip() if field_id == "custom_instructions" else value

        if "max_money" in normalized:
            cap = normalized["max_money"]
            if cap < normalized.get("comfort_money", 0):
                reject([role_id, "max_money"], "Потолок взноса должен быть не ниже комфортного взноса.")
            if normalized.get("start_money", 0) > cap:
                reject([role_id, "start_money"], "Стартовый взнос не может превышать потолок.")
            if role_id == "city_administration" and normalized.get("water_supply") and cap > 10:
                reject([role_id, "max_money"], "При подвозе воды допустимый взнос города — до 10 млн ₽.")
        answers[role_id] = normalized
    return answers, errors


def build_strategy(role_id: str, answers: dict, own_conditions: list[dict], budget: int) -> str:
    condition_titles = [condition["title"] for condition in own_conditions]
    owned = {condition["id"] for condition in own_conditions}
    funding = []
    if "max_money" in answers:
        def amount(value):
            percent = f" ({round(value / 270 * 100)}% сметы)" if role_id != "regional_government" else ""
            return f"{value} млн ₽{percent}"

        funding.append(f"- Доступный бюджет роли: {budget} млн ₽.")
        water_supply = role_id == "city_administration" and answers["water_supply"]
        cap = min(answers["max_money"], 10) if water_supply else answers["max_money"]
        if water_supply:
            funding.append("- Из бюджета города 20 млн ₽ зарезервировано на подвоз питьевой воды (water_supply).")
        if "start_money" in answers:
            funding.append(f"- Стартовое предложение взноса (Раунд 1): {amount(answers['start_money'])}.")
        comfort = answers["comfort_money"]
        funding.extend((
            f"- Комфортный целевой взнос: {amount(comfort)}.",
            f"- ЖЕСТКИЙ ПОТОЛОК взноса (красная линия): не более {amount(cap)}.",
        ))
    else:
        funding.append("- Финансовый взнос в смету: 0 млн ₽.")

    positions = []
    for field in QUESTIONNAIRES[role_id]["fields"]:
        key = field["id"]
        if key in FINANCIAL_FIELDS or not field["options"]:
            continue
        value = answers[key]
        choice = next(option["label"] for option in field["options"] if option["value"] == value)
        if key in owned:
            stance = "ваше условие протокола"
        elif key in {"holding_demand", "region_demand", "holding_min"}:
            stance = "денежное требование к другой стороне"
        else:
            stance = "позиция по условию другой стороны"
        notation = json.dumps(value, ensure_ascii=False) if type(value) is bool else str(value)
        positions.append(f"- {field['label']} ({key}: {notation}, {stance}) — {choice}.")

    strategy = "\n".join((
        "[1. РОЛЬ И ИСХОДНЫЕ ДАННЫЕ]",
        ROLE_DESCRIPTIONS[role_id],
        f"Условия протокола под вашим прямым управлением: {', '.join(condition_titles)}.",
        "",
        "[2. ФИНАНСОВЫЕ РАМКИ]",
        *funding,
        "",
        "[3. ПОЗИЦИЯ ПО УСЛОВИЯМ ПРОТОКОЛА И ТРЕБОВАНИЯ]",
        *positions,
        "",
        VOTING_STRATEGY,
    ))
    if answers["custom_instructions"]:
        strategy += f"\n\nИндивидуальная инструкция от участника:\n{answers['custom_instructions']}"
    return strategy
