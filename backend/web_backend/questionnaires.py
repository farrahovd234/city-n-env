"""City N questionnaires and the strategies derived from their answers."""

import json
from pathlib import Path

from consequences_model.catalog import TIMELINE_MONTHS

from .scenario import ROLES


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
CONTRIBUTION_REQUIREMENTS = {
    "holding_demand": ("industrial_holding", "холдинга"),
    "region_demand": ("regional_government", "области"),
    "holding_min": ("industrial_holding", "холдинга"),
}
STANDARD_TIMELINE = 36
EXTENDED_TIMELINE_CONDITIONS = {
    "city_residents": "свыше 36 месяцев допустимо только при подвозе питьевой воды",
    "environmental_ngo": "свыше 36 месяцев допустимо только при работе завода на 70% мощности",
}

for role in ROLES:
    for field in QUESTIONNAIRES[role["player_id"]]["fields"]:
        if field["id"] in FINANCIAL_FIELDS:
            field["number_range"] = {"minimum": 0, "maximum": role["budget_millions"], "unit": "млн ₽"}
        elif field["id"] == "timeline":
            minimum, maximum = TIMELINE_MONTHS
            field["number_range"] = {"minimum": minimum, "maximum": maximum, "unit": "мес."}
            if role["player_id"] in EXTENDED_TIMELINE_CONDITIONS:
                field["hint"] = EXTENDED_TIMELINE_CONDITIONS[role["player_id"]].capitalize() + "."

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
                if bounds := field.get("number_range"):
                    low, high = bounds["minimum"], bounds["maximum"]
                    if type(value) is not int or not low <= value <= high:
                        reject([role_id, field_id], f"Введите целое число от {low} до {high} {bounds['unit']}.")
                        continue
                elif not any(type(value) is type(option["value"]) and value == option["value"]
                             for option in field["options"]):
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


def vote_objections(role_id: str, answers: dict, state: dict) -> list[str]:
    """Проверяет формализуемые красные линии анкеты по зафиксированным условиям."""
    levers = state["levers"]
    timeline = levers["timeline"]
    objections = []
    required = {
        "city_administration": {"water_supply": "подвоз питьевой воды"},
        "industrial_holding": {"protest_moratorium": "мораторий на протесты и иски"},
        "city_residents": {
            "tariffs_freeze": "заморозка тарифов",
            "water_supply": "подвоз питьевой воды",
            "open_sensors": "открытые данные датчиков",
        },
        "environmental_ngo": {"open_sensors": "открытые данные датчиков"},
    }
    for key, name in required.get(role_id, {}).items():
        if answers[key] and not levers[key]:
            objections.append(f"отсутствует обязательное условие «{name}»")
    for key, (target_id, target_name) in CONTRIBUTION_REQUIREMENTS.items():
        if key in answers:
            # Значения проверены по анкете. Для диапазона берём явную нижнюю границу.
            minimum = int(answers[key].split()[2].split("–")[0])
            pledge = state["players"][state["player_ids"][target_id]]["contribution"] or 0
            if pledge < minimum * MILLION:
                objections.append(f"взнос {target_name} ниже {minimum} млн ₽")
    if role_id in {"regional_government", "city_residents", "environmental_ngo"} and timeline > answers["timeline"]:
        objections.append(f"срок реконструкции превышает {answers['timeline']} мес.")
    if role_id == "industrial_holding":
        if answers["plant_mode"] == "100%" and levers["plant_mode"] != "100%":
            objections.append("снижена мощность предприятия")
        if answers["guilt"] == "shared" and levers["guilt"] == "holding":
            objections.append("вся ответственность возложена на холдинг")
        pledge = state["players"][state["player_ids"][role_id]]["contribution"] or 0
        if answers["tax_relief"] and pledge > answers["comfort_money"] * MILLION and not levers["tax_relief"]:
            objections.append("для взноса выше комфортного уровня нужны налоговые льготы")
    if role_id == "regional_government" and not answers["tax_relief"] and levers["tax_relief"]:
        objections.append("включены налоговые льготы")
    if role_id == "city_residents":
        if not answers["protest_moratorium"] and levers["protest_moratorium"]:
            objections.append("включён мораторий на протесты и иски")
        if not levers["water_supply"] and not answers["water_supply"]:
            if not levers["tariffs_freeze"]:
                objections.append("тарифы могут вырасти без гарантии питьевой воды")
            elif timeline > STANDARD_TIMELINE:
                objections.append("при сроке свыше 36 мес. нужен подвоз питьевой воды")
    if role_id == "environmental_ngo" and levers["plant_mode"] != "70%":
        if answers["plant_mode"] == "70%" or timeline > STANDARD_TIMELINE:
            objections.append("мощность предприятия не ограничена 70%")
        elif not levers["open_sensors"] and not answers["open_sensors"]:
            objections.append("при полной мощности нужны открытые данные датчиков")
    return objections


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
        if bounds := field.get("number_range"):
            choice = next((option["label"] for option in field["options"] if option["value"] == value),
                          f"{value} {bounds['unit']}")
        else:
            choice = next(option["label"] for option in field["options"] if option["value"] == value)
        if key == "timeline" and role_id in EXTENDED_TIMELINE_CONDITIONS and STANDARD_TIMELINE < value < TIMELINE_MONTHS[1]:
            choice += f" ({EXTENDED_TIMELINE_CONDITIONS[role_id]})"
        if key == "tax_relief" and role_id == "industrial_holding" and value:
            choice = f"льготы обязательны при взносе выше {answers['comfort_money']} млн ₽ (комфортный уровень)"
        if key in owned:
            stance = "ваше условие протокола"
        elif key in CONTRIBUTION_REQUIREMENTS:
            stance = "денежное требование к другой стороне"
            choice = value
        else:
            stance = "позиция по условию другой стороны"
        positions.append(f"- {field['label']} ({stance}) — {choice}.")

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
