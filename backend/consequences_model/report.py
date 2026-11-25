"""Шаг 5: отчёт по шаблону (без LLM) и промпт для «Вестника города N, 2036»."""

from __future__ import annotations

from typing import Any

from .catalog import (ACHIEVED, CONDITIONS, FAILED, FULL, GUILT, GUILT_LABELS, MIN_COVERAGE_TO_BUILD, MOMENT_LABELS,
                      PARTIAL, PARTLY, PLANT_MODE, RECONSTRUCTION_LABEL, RECONSTRUCTION_OWNER, ROLE_LABELS, SENSORS,
                      SUBSYSTEM_LABELS, TARIFFS, TIMELINE, VOTE_LABELS, WATER, WATER_MAX_MONTHS)

MLN = 1_000_000

# Показатели критерия 6: из какой подсистемы через 10 лет и как называть её уровень.
INDICATORS = (
    ("Экологический риск", "ecology", {ACHIEVED: "низкий", PARTLY: "средний", FAILED: "высокий"}),
    ("Недовольство и риск протестов", "politics", {ACHIEVED: "низкие", PARTLY: "средние", FAILED: "высокие"}),
    ("Доверие к администрации", "politics", {ACHIEVED: "восстановлено", PARTLY: "восстановлено частично",
                                             FAILED: "подорвано"}),
    ("Негатив к холдингу", "media", {ACHIEVED: "снижен до 60% и ниже", PARTLY: "снижается, но выше 60%",
                                     FAILED: "остаётся около 90%"}),
    ("Рабочие места", "economy", {ACHIEVED: "сохранены", PARTLY: "под давлением", FAILED: "под угрозой"}),
)


def millions(amount: float) -> str:
    """Сумма в миллионах без единиц: 225 000 000 → «225»."""
    return f"{amount / MLN:.7f}".rstrip("0").rstrip(".").replace(".", ",")


def mln(amount: float) -> str:
    return millions(amount) + " млн ₽"


def terms(result: dict[str, Any]) -> str:
    month, promised = result["commissioning_month"], result["promised_months"]
    if month is None:
        return f"обещано {promised} мес., очистные не введены за 10 лет"
    return f"обещано {promised} мес., очистные введены на {month}-м месяце"


def events(result: dict[str, Any]) -> str:
    month, promised = result["commissioning_month"], result["promised_months"]
    if month is None:
        happened = ["очистные не введены за 10 лет"]
    elif month > promised:
        happened = [f"очистные введены на {month}-м месяце, на {month - promised} мес. позже обещанного"]
    else:
        happened = [f"очистные введены в обещанный срок, на {month}-м месяце"]
    return "; ".join(happened)


def condition_value(condition: str, value: Any) -> str:
    if condition == GUILT:
        return GUILT_LABELS[value]
    if isinstance(value, bool):
        return "включено" if value else "не включено"
    return str(value)


def condition_execution(result: dict[str, Any], condition: str) -> str:
    if condition == GUILT:
        return "решение: действует, если протокол принят"
    return result["execution"]["conditions"].get(condition, "—")


def temporary_measures(result: dict[str, Any]) -> str:
    conditions = result["execution"]["conditions"]
    water = conditions.get(WATER, "не включена")
    tariffs = conditions.get(TARIFFS, "не включена")
    return f"гарантия питьевой воды — {water}, подвоз до ввода очистных, не дольше {WATER_MAX_MONTHS // 12} лет; " \
           f"заморозка тарифов на время работ — {tariffs}"


def protocol_conditions(result: dict[str, Any]) -> str:
    if not result["protocol"]["accepted"]:
        return "протокол не принят, его условия не вступили в силу"
    conditions = result["protocol"]["conditions"]
    included = [f"{CONDITIONS[condition]['label'][0].lower()}{CONDITIONS[condition]['label'][1:]} — {level}"
                for condition, level in result["execution"]["conditions"].items()]
    return (f"срок реконструкции {conditions[TIMELINE]} мес.; режим работы комбината {conditions[PLANT_MODE]}; "
            f"вина за аварию {GUILT_LABELS[conditions[GUILT]]}; "
            + ("включены: " + ", ".join(included) if included else "других условий не включено"))


def cost_split(result: dict[str, Any]) -> str:
    protocol = result["protocol"]
    total = protocol["total_cost"]
    parts = [f"{ROLE_LABELS[role]} — {mln(amount)} ({amount / total:.0%})"
             for role, amount in protocol["contributions"].items()]
    text = "; ".join(parts) if parts else "взносов нет"
    text += f". Фактически внесено {mln(result['paid'])} из {mln(total)}"
    return text


def render_report(result: dict[str, Any]) -> str:
    outcome, protocol, execution = result["outcome"], result["protocol"], result["execution"]
    lines = ["# Модель последствий: город N через 10 лет", "",
             f"**Исход: «{outcome['name']}».** {outcome['description']}", "",
             f"Почему: {outcome['rule']}.", "",
             "## Кто что сделал", "",
             "| Роль | Голос | Взнос | Исполнение взноса |", "| --- | --- | --- | --- |"]
    for role, label in ROLE_LABELS.items():
        amount = protocol["contributions"].get(role)
        lines.append(f"| {label} | {VOTE_LABELS[protocol['votes'][role]]} | "
                     f"{mln(amount) if amount else '—'} | {execution['contributions'].get(role, '—')} |")
    lines += ["", "| Условие протокола | Значение | Владелец | Исполнение |", "| --- | --- | --- | --- |",
              f"| {RECONSTRUCTION_LABEL} | срок {protocol['conditions'][TIMELINE]} мес. | "
              f"{ROLE_LABELS[RECONSTRUCTION_OWNER]} | {execution['reconstruction']} |"]
    for condition, info in CONDITIONS.items():
        if condition == TIMELINE:
            continue
        lines.append(f"| {info['label']} | {condition_value(condition, protocol['conditions'][condition])} | "
                     f"{ROLE_LABELS[info['owner']]} | {condition_execution(result, condition)} |")

    lines += ["", "## Финансовая нагрузка по заявленным обязательствам", "",
              "| Роль | Взнос | Отдельные расходы | Всего заявлено | Бюджет | Доля бюджета | Сверх бюджета |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in result["financial_load"]:
        budget = mln(row["budget_rub"]) if row["budget_rub"] is not None else "—"
        percent = f"{row['budget_used_percent']:g}%" if row["budget_used_percent"] is not None else "—"
        excess = mln(row["over_budget_rub"]) if row["over_budget_rub"] is not None else "—"
        lines.append(f"| {ROLE_LABELS[row['role_id']]} | {mln(row['pledged_rub'])} | "
                     f"{mln(row['spent_on_conditions_rub'])} | {mln(row['committed_rub'])} | "
                     f"{budget} | {percent} | {excess} |")

    state = result["state"]
    headers = [MOMENT_LABELS[moment] + (f" ({state[moment]['month']}-й мес.)" if moment == "commissioning"
                                        and state[moment]["month"] else "") for moment in state]
    lines += ["", "## Состояние города", "", "| Подсистема | " + " | ".join(headers) + " |",
              "| --- |" + " --- |" * len(state)]
    for subsystem, label in SUBSYSTEM_LABELS.items():
        cells = [moment["subsystems"][subsystem] if moment["subsystems"] else "очистные не введены"
                 for moment in state.values()]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    year_10 = state["year_10"]["subsystems"]
    lines += ["", "## Показатели критерия 6", "",
              f"- **Распределение затрат:** {cost_split(result)}.",
              f"- **Сроки:** {terms(result)}."]
    lines += [f"- **{name}:** {words[year_10[subsystem]]}." for name, subsystem, words in INDICATORS]
    lines.append(f"- **Доступность временных мер:** {temporary_measures(result)}.")

    lines += ["", "## Судьбы участников", ""]
    for role, checks in result["fates"].items():
        marks = "; ".join(("✓ " if check["met"] else "✗ ") + check["goal"] for check in checks)
        lines.append(f"- **{ROLE_LABELS[role]}:** {marks}.")

    lines += ["", "## Почему так", ""]
    lines += [f"{number}. {rule['text']} _({rule['source']})_"
              for number, rule in enumerate(result["explanation"]["rules"], 1)]
    lines += ["", "## Без вклада роли", "", "| Если бы не выполнила свои обязательства | Исход |", "| --- | --- |"]
    lines += [f"| {ROLE_LABELS[role]} | {name} |" for role, name in result["explanation"]["without_role"].items()]
    lines += ["", "## Допущения", "",
              "Пороги правил, коэффициенты исполнения и влияние условий протокола — наша формализация, требуют "
              "согласования с заказчицей. "
              "Прогноз — учебная гипотеза, а не прогноз по реальной реке."]
    if result["warnings"]:
        lines += ["", "## Предупреждения", ""] + [f"- {warning}" for warning in result["warnings"]]
    return "\n".join(lines)


def render_herald_text(result: dict[str, Any]) -> str:
    """Один абзац о том, что произошло в городе по итогам партии."""
    outcome, protocol = result["outcome"], result["protocol"]
    conditions = result["execution"]["conditions"]
    pledged = sum(protocol["contributions"].values())
    if not protocol["accepted"]:
        sentences = ["Стороны не приняли протокол, и через десять лет после слушаний у города N так и нет "
                     "обновлённых очистных."]
        if pledged:
            sentences.append(f"На стройку обещали {mln(pledged)}, но в общую смету не поступило ни рубля.")
        measures = {
            WATER: "мэрия частично организовала подвоз питьевой воды",
            PLANT_MODE: "холдинг частично снизил мощность комбината",
            SENSORS: "НКО частично запустила открытый мониторинг реки",
        }
        started = [text for condition, text in measures.items() if conditions.get(condition) == PARTIAL]
        if started:
            sentences.append("При этом " + ", ".join(started) + ".")
        else:
            sentences.append("Самостоятельных мер по реке и питьевой воде стороны не предприняли.")
        return " ".join(sentences)

    month, promised = result["commissioning_month"], result["promised_months"]
    if month is None:
        lead = "Очистные города N так и не заработали за десять лет после слушаний."
    elif month > promised:
        lead = f"Очистные города N заработали на {month}-м месяце вместо {promised}-го, указанного в протоколе."
    else:
        lead = f"Очистные города N заработали на {month}-м месяце, в обещанный срок."

    paid, total = result["paid"], protocol["total_cost"]
    if paid == total:
        funding = f"В строительство вложили все {mln(total)} по принятому протоколу."
    elif paid > total:
        funding = f"В строительство вложили {mln(paid)} при смете {mln(total)}."
    else:
        funding = f"В общую смету поступило {mln(paid)} из {mln(total)}."
    sentences = [lead, funding]
    if paid < total * MIN_COVERAGE_TO_BUILD:
        sentences.append("Этой суммы не хватило для завершения стройки.")
    if outcome["id"] == "without_residents":
        sentences.append("Жители и НКО не поддержали протокол на голосовании.")

    water = conditions.get(WATER)
    if water == PARTIAL:
        sentences.append("Обещание подвоза питьевой воды выполнили лишь частично.")
    elif month is not None and month > promised:
        if water == FULL and month > WATER_MAX_MONTHS:
            sentences.append(f"Подвоз питьевой воды закончился после {WATER_MAX_MONTHS}-го месяца, ещё до запуска очистных.")
        elif water == FULL:
            sentences.append("Пока шли работы, мэрия подвозила жителям питьевую воду.")
        else:
            sentences.append("На время задержки подвоз питьевой воды не организовали.")

    if outcome["id"] == "compromise" and water != PARTIAL:
        partial = next((CONDITIONS[condition]["label"] for condition, level in conditions.items() if level == PARTIAL), None)
        if partial:
            sentences.append(f"Условие «{partial}» выполнили лишь частично.")
        elif any(vote is not True for vote in protocol["votes"].values()):
            sentences.append("Протокол поддержали не все стороны.")

    if conditions.get(SENSORS) == FULL:
        sentences.append("Открытые датчики публикуют замеры реки, и жители могут сами посмотреть данные.")
    elif outcome["id"] == "closed_data":
        sentences.append("У жителей по-прежнему нет полных открытых данных о состоянии реки.")
    return " ".join(sentences)


def render_herald_prompt(result: dict[str, Any]) -> str:
    outcome, state = result["outcome"], result["state"]
    year_10 = state["year_10"]["subsystems"]
    facts = [f"Исход: «{outcome['name']}». {outcome['description']}",
             f"Условия протокола: {protocol_conditions(result)}.",
             f"Сроки: {terms(result)}.",
             f"Распределение затрат: {cost_split(result)}."]
    for moment, label in MOMENT_LABELS.items():
        month, levels = state[moment]["month"], state[moment]["subsystems"]
        if levels is None:
            facts.append(f"{label}: очистные не введены за 10 лет.")
            continue
        heading = f"{label} ({month}-й мес.)" if moment == "commissioning" else label
        facts.append(f"{heading}: " + "; ".join(f"{name} — {levels[subsystem]}"
                                               for subsystem, name in SUBSYSTEM_LABELS.items()) + ".")
    facts += [f"События: {events(result)}.", f"Временные меры: {temporary_measures(result)}."]
    facts += [f"{name}: {words[year_10[subsystem]]}." for name, subsystem, words in INDICATORS]
    for role, checks in result["fates"].items():
        facts.append(f"{ROLE_LABELS[role]}: " + "; ".join(
            ("достигнуто — " if check["met"] else "не достигнуто — ") + check["goal"] for check in checks) + ".")
    return "\n".join([
        "Напиши короткую заметку для газеты «Вестник города N, 2036» о том, каким стал город N через 10 лет "
        "после общественных слушаний по реконструкции очистных сооружений.",
        "",
        "Правила:",
        "- Опирайся только на факты ниже. Не добавляй фактов, событий и чисел, которых нет в списке.",
        "- Не утверждай ущерб здоровью людей или банкротство как установленный факт.",
        "- 150–250 слов, живой газетный стиль, на русском языке.",
        "- Весь ответ напиши одним абзацем, без заголовков, списков, таблиц и переносов строк.",
        "- Пиши только об итогах игры: без методических пояснений, ссылок на источники, сравнений с эталоном "
        "и оговорок об учебном прогнозе.",
        "",
        "Факты:",
        *[f"- {fact}" for fact in facts],
    ])
