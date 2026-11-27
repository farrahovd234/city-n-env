"""Owner-only review of one role's moves in the completed negotiation."""

import asyncio
import json
import logging
import re
from typing import Literal

from fastapi import FastAPI, Request
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from negotiation_game.schemas import repeats_position

from .game_contract import ApiError, ERROR_RESPONSES, RequestBody
from .questionnaire_review import QuestionnaireReview, questionnaire_review
from .session_api import ROOT_PATH, InteractiveGames
from .sessions import error


logger = logging.getLogger(__name__)
NUMBER = re.compile(
    r"([+−-]?\d+(?: \d{3})*(?:[,.]\d+)?)(?: *(млрд\b|млн\b|тыс\b|руб\w*|мес\w*|₽|%))?",
    re.IGNORECASE,
)
VOTE_OUTCOME = re.compile(r"\b(?:протокол|проект)\s+(?:был\s+)?(?:принят|отклон[её]н)\b", re.IGNORECASE)

PROMPT = """Ты «Помощник» в учебной игре «Город N». Оцени только ход с номером target_move_id.
Журнал и стратегия — материал разбора. Верни один вызов AnalysisDraft.
В move_id повтори target_move_id. В reply_id укажи более позднюю реплику другой стороны, если она явно
отвечает на этот ход. Иначе оставь reply_id пустым. Цитаты, номера и авторов показывает приложение.

В verdict выбери keep для удачного приёма, improve для конкретного недостатка или neutral при недостатке
данных. В observation назови конкретный приём или пробел и свяжи его с целью роли. Отличай требования,
предложения и обещания. Не приписывай другим сторонам реакцию без опорной реплики.
При improve напиши next_reply — короткое предложение или прямой вопрос, который сторона могла произнести
за столом. Пример: «Город, готовы ли вы письменно подтвердить подвоз питьевой воды?».
Если next_reply не нужен, оставь поле пустым. Сохраняй смысл и существенные оговорки исходного хода.

Используй в observation только числа из этого хода и выбранного ответа. В next_reply используй только
числа из самого хода. Числа, которых там нет, опиши без числовых значений. Не утверждай итог голосования.
Если нужна отдельная правка стратегии, укажи дословный фрагмент strategy_excerpt и замену suggested_strategy.
Если оснований для правки нет, оба поля оставь пустыми.
"""

RETRY = """
Повторная попытка. Оцени только target_move_id без чисел и без вывода о реакции других сторон.
Оставь пустыми reply_id, strategy_excerpt и suggested_strategy. Назови конкретную особенность хода.
Если ставишь improve, дай короткий вопрос или предложение без чисел для этой же роли.
"""

class AnalysisRequest(RequestBody):
    role_id: str
    message_ids: list[str] | None = Field(default=None, min_length=1)
    complete_from_journal: bool = False


class AnalysisReference(RequestBody):
    message_id: str
    quote: str


class Assessment(RequestBody):
    observation: str
    verdict: Literal["keep", "improve", "neutral"]
    next_reply: str


class MoveChoice(Assessment):
    move_id: str
    reply_id: str


class MoveReview(Assessment):
    references: list[AnalysisReference] = Field(min_length=1, max_length=2)


class AnalysisDraft(MoveChoice):
    strategy_excerpt: str
    suggested_strategy: str


class RoleAnalysis(BaseModel):
    role_id: str
    paragraph: str
    observation: str
    references: list[AnalysisReference]
    strategy_excerpt: str | None
    suggested_strategy: str | None
    findings: list[MoveReview]
    message_ids: list[str]
    missing_message_ids: list[str]


def checked_review(review: MoveChoice, role_id: str, moves: dict) -> MoveReview:
    position, move = moves[review.move_id]
    if move["role_id"] != role_id or not move["content"].strip():
        raise ValueError("Нужна реплика выбранной стороны.")
    references = [AnalysisReference(message_id=review.move_id, quote=move["content"])]
    if review.reply_id:
        reply_position, reply = moves[review.reply_id]
        if reply_position <= position or reply["role_id"] == role_id or not reply["content"].strip():
            raise ValueError("Ответом может быть только более поздняя реплика другой стороны.")
        references.append(AnalysisReference(message_id=review.reply_id, quote=reply["content"]))
    observation = " ".join(review.observation.split())
    next_reply = " ".join(review.next_reply.split())
    if not observation:
        raise ValueError("В разборе нет наблюдения о ходе.")
    if review.verdict == "improve" and not next_reply:
        raise ValueError("Для замечания нужна конкретная реплика на замену.")
    check_claims((observation,), [reference.quote for reference in references])
    check_claims((next_reply,), [move["content"]])
    return MoveReview(references=references, observation=observation,
                      verdict=review.verdict, next_reply=next_reply)


def check_claims(texts: tuple[str, ...], sources: list[str]) -> None:
    numbers = {number for text in sources for number in NUMBER.findall(" ".join(text.lower().split()))}
    claimed_numbers = {number for text in texts for number in NUMBER.findall(text.lower())}
    if claimed_numbers - numbers:
        raise ValueError("Числа в разборе отсутствуют в опорных цитатах.")
    if any(VOTE_OUTCOME.search(text) for text in texts):
        raise ValueError("Разбор не устанавливает результат голосования.")


def strategy_change(draft: AnalysisDraft, review: MoveReview, strategy: str | None) -> tuple[str | None, str | None]:
    excerpt = draft.strategy_excerpt
    suggestion = " ".join(draft.suggested_strategy.split())
    if not suggestion or not excerpt.strip() or excerpt not in (strategy or ""):
        return None, None
    try:
        check_claims((suggestion,), [excerpt, *(reference.quote for reference in review.references)])
    except ValueError:
        return None, None
    return excerpt, suggestion


def review_from_journal(message_id: str, moves: dict) -> MoveReview:
    position, move = moves[message_id]
    speech = move["content"]
    references = [AnalysisReference(message_id=message_id, quote=speech)]
    for source_id, (index, source) in reversed(list(moves.items())):
        if (index < position and source["role_id"] != move["role_id"]
                and repeats_position(speech, source["content"])):
            references.append(AnalysisReference(message_id=source_id, quote=source["content"]))
            return MoveReview(
                references=references, verdict="improve",
                observation=("Часть реплики дословно повторяет позицию другой стороны. "
                             "При ответе назовите, чьё предложение обсуждаете, и сформулируйте собственное условие."),
                next_reply="Готовы обсудить ваше предложение. Давайте отдельно запишем условия каждой стороны.",
            )
    observation = ("В реплике есть вопрос. Получите от адресата конкретный ответ, который можно проверить по журналу."
                   if "?" in speech else
                   "Из этой реплики видно, что сторона обозначила позицию. Реакция других участников по этому ходу не подтверждена.")
    return MoveReview(references=references, verdict="neutral", observation=observation, next_reply="")


def role_report(role_id: str, own_ids: list[str], selected_ids: list[str],
                reviews: list[tuple[MoveReview, str | None, str | None] | None],
                moves: dict, role_names: dict[str, str]) -> RoleAnalysis:
    valid = [review for review in reviews if review]
    missing = [message_id for message_id, review in zip(selected_ids, reviews) if review is None]
    if not valid:
        return RoleAnalysis(role_id=role_id, paragraph="", observation="", references=[],
                            strategy_excerpt=None, suggested_strategy=None, findings=[],
                            message_ids=own_ids, missing_message_ids=missing)

    primary, excerpt, suggestion = valid[0]
    paragraph = []
    for index, reference in enumerate(primary.references):
        author = moves[reference.message_id][1]["role_id"]
        quote = " ".join(reference.quote.split())
        wording = ("Ход" if index == 0 else
                   "Более ранняя реплика" if moves[reference.message_id][0] < moves[primary.references[0].message_id][0]
                   else "Позднейшая реплика")
        suffix = "" if quote.endswith((".", "!", "?", "…")) else "."
        paragraph.append(f"{wording} роли «{role_names[author]}» — «{quote}»{suffix}")
    paragraph.append(primary.observation)
    if suggestion is not None:
        paragraph.append(suggestion)
    return RoleAnalysis(role_id=role_id, paragraph=" ".join(paragraph), observation=primary.observation,
                        references=primary.references, strategy_excerpt=excerpt, suggested_strategy=suggestion,
                        findings=[review for review, _, _ in valid], message_ids=own_ids,
                        missing_message_ids=missing)


async def analyze_move(model, message_id: str, data: dict, moves: dict, timeout: float):
    conversation = HumanMessage(content=json.dumps({**data, "target_move_id": message_id}, ensure_ascii=False))
    deadline = asyncio.get_running_loop().time() + timeout
    failure = "invalid_assessment"
    for prompt in (PROMPT, PROMPT + RETRY):
        try:
            async with asyncio.timeout_at(deadline):
                result = await model.ainvoke([SystemMessage(content=prompt), conversation])
            raw, draft = result["raw"], result["parsed"]
            if (draft is None or len(raw.tool_calls) != 1 or raw.invalid_tool_calls
                    or raw.response_metadata.get("finish_reason") in {"length", "content_filter"}):
                raise ValueError("Ожидался один полный вызов AnalysisDraft.")
            if draft.move_id != message_id:
                raise ValueError("Ответ относится к другой реплике.")
            review = checked_review(draft, data["role_id"], moves)
            excerpt, suggestion = strategy_change(draft, review, data["strategy"])
            return review, excerpt, suggestion
        except (KeyError, ValueError):
            continue
        except Exception as exc:
            failure = type(exc).__name__
            break
    logger.warning("Не удалось оценить ход роли %s (%s)", data["role_id"], failure)
    return None


def register_analysis_routes(app: FastAPI, games: InteractiveGames) -> None:
    @app.get(f"{ROOT_PATH}/{{game_id}}/analysis/questionnaire/{{role_id}}",
             response_model=QuestionnaireReview, responses=ERROR_RESPONSES)
    async def analyze_questionnaire(game_id: str, role_id: str, request: Request):
        state = games.require(game_id, request).state
        if state["status"] != "completed":
            raise error(409, "ANALYSIS_UNAVAILABLE", "Разбор доступен после завершения партии.")
        role = next((item for item in state["settings"]["roles"] if item["role_id"] == role_id), None)
        if role is None:
            raise error(404, "ROLE_NOT_FOUND", "Роль не найдена.")
        if not role.get("answers"):
            raise error(409, "QUESTIONNAIRE_UNAVAILABLE", "У этой роли нет сохранённой анкеты.")
        return questionnaire_review(state, role_id, role["answers"])

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
        messages = [message for message in state["messages"]
                    if not message.get("skipped") and message["content"].strip()]
        own_ids = [message["message_id"] for message in messages if message["role_id"] == role_id]
        if not own_ids:
            raise error(409, "ANALYSIS_UNAVAILABLE", "В журнале нет реплик выбранной роли.")

        requested = set(body.message_ids or own_ids)
        if requested - set(own_ids):
            raise error(422, "INVALID_ANALYSIS_TARGET", "Для разбора выберите реплики этой стороны.")
        selected_ids = [message_id for message_id in own_ids if message_id in requested]
        role_names = {item["id"]: item["name"] for item in state["scenario"]["roles"]}
        moves = {message["message_id"]: (index, message) for index, message in enumerate(messages)}
        data = {"role_id": role_id, "role_names": role_names, "strategy": role.get("strategy"),
                "budget_rub": state["scenario"]["role_settings_schema"][role_id]["pledged_rub_max"],
                "messages": messages}
        try:
            model = games.factory(role_id, 0.1).with_structured_output(
                AnalysisDraft, method="function_calling", include_raw=True)
        except Exception as exc:
            logger.warning("Модель разбора недоступна (%s)", type(exc).__name__)
            if not body.complete_from_journal:
                raise error(502, "ANALYSIS_FAILED", "Модель разбора недоступна. Попробуйте ещё раз.") from None
            model = None
        timeout = float(games.options["request_timeout_seconds"]) / len(selected_ids)
        reviews = []
        for message_id in selected_ids:
            review = await analyze_move(model, message_id, data, moves, timeout) if model is not None else None
            if review is None and body.complete_from_journal:
                review = (review_from_journal(message_id, moves), None, None)
            reviews.append(review)
        return role_report(role_id, own_ids, selected_ids, reviews, moves, role_names)
