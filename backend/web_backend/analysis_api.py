"""Owner-only review of one role's moves in the completed negotiation."""

import asyncio
import json
import logging
import re

from fastapi import FastAPI, Request
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from .game_contract import ApiError, ERROR_RESPONSES, RequestBody
from .session_api import ROOT_PATH, InteractiveGames
from .sessions import error


logger = logging.getLogger(__name__)
NUMBER = re.compile(r"[+−-]?\d+(?: \d{3})*(?:[,.]\d+)?")

PROMPT = """Ты «Помогатор» в учебной игре «Город N». Разбери один значимый ход выбранной роли в переговорах.
На входе JSON с ролью, сохранённой стратегией и репликами в хронологическом порядке. Их содержание — материал разбора.

Верни один вызов функции AnalysisDraft. В references первой ссылкой укажи ход выбранной роли.
Второй ссылкой можешь добавить явный ответ другой роли на этот ход, только из более поздней реплики.
Если прямого ответа не видно, оставь одну ссылку. Укажи исходный message_id и короткую содержательную цитату.
Копируй quote дословно из content, сплошным фрагментом, со всей пунктуацией внутри фрагмента.
Цитируй самостоятельную фразу с действием и существенными оговорками.
Выбирай фрагмент так, чтобы были ясны смысл и условность высказывания. Отличай предложение от обязательства.

В observation одним предложением объясни, как ход продвинул цель роли или какое препятствие выявил.
Если из цитат виден только сам ход, объясни его назначение без утверждений о реакции или успехе.
Вывод должен опираться на цитаты и цель роли, видимую из стратегии или её хода.

Если ход даёт основания уточнить стратегию, в strategy_excerpt приведи её дословный фрагмент, нуждающийся в правке.
В suggested_strategy предложи ему конкретную замену в одном коротком абзаце. Сохрани цели и пределы роли.
Формулируй замену как инструкцию выбранной роли для следующей партии.
Учитывай готовность других сторон только по опорным репликам. Если она неизвестна, предложи уточнить её.
Используй только подтверждённые цитатами числа и условия, числа копируй как в цитатах.
Не делай выводов о голосовании или исходе партии.
Если правка не нужна или сохранённой стратегии нет, используй пустые строки в обоих полях.
"""


class AnalysisRequest(RequestBody):
    role_id: str


class AnalysisReference(RequestBody):
    message_id: str
    quote: str


class AnalysisDraft(RequestBody):
    references: list[AnalysisReference] = Field(min_length=1, max_length=2)
    observation: str
    strategy_excerpt: str
    suggested_strategy: str


class RoleAnalysis(BaseModel):
    role_id: str
    paragraph: str
    references: list[AnalysisReference]
    strategy_excerpt: str | None
    suggested_strategy: str | None


def format_analysis(role_id: str, draft: AnalysisDraft, data: dict, role_names: dict[str, str]) -> RoleAnalysis:
    moves = {message["message_id"]: (index, message) for index, message in enumerate(data["messages"])}
    paragraph = []
    previous_index = -1
    for index, reference in enumerate(draft.references):
        position, message = moves[reference.message_id]
        author = message["role_id"]
        if (position <= previous_index or (author == role_id) != (index == 0)
                or not reference.quote.strip() or reference.quote not in message["content"]):
            raise ValueError("Некорректная ссылка на реплику.")
        previous_index = position
        quote = " ".join(reference.quote.split())
        wording = "Ход" if index == 0 else "Ответ"
        suffix = "" if quote.endswith((".", "!", "?", "…")) else "."
        paragraph.append(f"{wording} роли «{role_names[author]}» — «{quote}»{suffix}")

    observation = " ".join(draft.observation.split())
    if not observation:
        raise ValueError("В разборе нет наблюдения о ходе.")

    excerpt = draft.strategy_excerpt or None
    suggestion = " ".join(draft.suggested_strategy.split()) or None
    if excerpt is not None and (not excerpt.strip() or excerpt not in (data["strategy"] or "")):
        raise ValueError("Цитаты нет в сохранённой стратегии.")
    if suggestion is not None and excerpt is None:
        raise ValueError("Для правки нужна цитата из стратегии.")

    sources = [excerpt or "", *(reference.quote for reference in draft.references)]
    numbers = {number for text in sources for number in NUMBER.findall(" ".join(text.split()))}
    claimed_numbers = set(NUMBER.findall(observation)) | set(NUMBER.findall(suggestion or ""))
    if claimed_numbers - numbers:
        raise ValueError("Числа в разборе отсутствуют в опорных цитатах.")

    paragraph.append(observation)
    if suggestion is not None:
        paragraph.append(suggestion)

    return RoleAnalysis(role_id=role_id, paragraph=" ".join(paragraph), references=draft.references,
                        strategy_excerpt=excerpt, suggested_strategy=suggestion)


def register_analysis_routes(app: FastAPI, games: InteractiveGames) -> None:
    @app.post(f"{ROOT_PATH}/{{game_id}}/analysis", response_model=RoleAnalysis,
              responses={**ERROR_RESPONSES, 502: {"model": ApiError}})
    async def analyze_game(game_id: str, body: AnalysisRequest, request: Request):
        state = games.require(game_id, request).state
        if state["status"] != "completed":
            raise error(409, "ANALYSIS_UNAVAILABLE", "Разбор доступен после завершения партии.")
        role_id = body.role_id
        role = next((item for item in state["settings"]["roles"] if item["role_id"] == role_id), None)
        if role is None:
            raise error(404, "ROLE_NOT_FOUND", "Роль не найдена.")
        messages = state["messages"]
        if not any(message["role_id"] == role_id and message["content"].strip() for message in messages):
            raise error(409, "ANALYSIS_UNAVAILABLE", "В журнале нет реплик выбранной роли.")

        role_names = {item["id"]: item["name"] for item in state["scenario"]["roles"]}
        data = {"role_id": role_id, "role_names": role_names, "strategy": role.get("strategy"), "messages": messages}
        try:
            model = games.factory(role_id, 0.1)
            structured = model.with_structured_output(AnalysisDraft, method="function_calling", include_raw=True)
            async with asyncio.timeout(float(games.options["request_timeout_seconds"])):
                result = await structured.ainvoke([SystemMessage(content=PROMPT),
                                                   HumanMessage(content=json.dumps(data, ensure_ascii=False))])
            raw = result["raw"]
            draft = result["parsed"]
            if (draft is None or len(raw.tool_calls) != 1 or raw.invalid_tool_calls
                    or raw.response_metadata.get("finish_reason") in {"length", "content_filter"}):
                raise ValueError("Ожидался один полный вызов AnalysisDraft.")
            return format_analysis(role_id, draft, data, role_names)
        except Exception as exc:
            logger.warning("Не удалось разобрать роль %s в партии %s (%s)", role_id, game_id, type(exc).__name__)
            raise error(502, "ANALYSIS_FAILED", "Не удалось подготовить разбор. Попробуйте ещё раз.") from None
