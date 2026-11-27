"""Settings validation and projections for the interactive game API."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, StringConstraints

from consequences_model import forecast
from consequences_model.catalog import HORIZON_MONTHS, SUBSYSTEM_LABELS, TIMELINE_MONTHS
from negotiation_game.engine import _get_default_settings
from negotiation_game.rules import is_owner

from .questionnaires import MILLION, QUESTIONNAIRES, build_strategy, questionnaire_answers
from .results import ROLE_BY_NAME, VOTES, illustration
from .scenario import ROLES, public_scenario


class RequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


Content = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=6000)]
Answer = StrictBool | StrictInt | StrictStr
SetupMode = Literal["manual", "automatic"]
Vote = Literal["for", "against", "abstain"]
SPEECH_PHASES = {"positions", "negotiation", "amendments"}
MAX_DIALOGUE_MESSAGES = len(SPEECH_PHASES) * len(ROLES)
CONDITIONAL_COMMITMENTS = {"tax_relief", "protest_moratorium"}
LEVERS = _get_default_settings()["levers"]
ROLE_LEVERS = {role["player_id"]: [lever for lever in LEVERS if is_owner(lever["owner"], role["player_name"])]
               for role in ROLES}


class RoleSettings(RequestBody):
    role_id: str
    control_mode: Literal["ai", "human"]
    pledged_rub: Annotated[StrictInt, Field(ge=0)]
    conditions: dict[str, StrictBool | StrictInt | StrictStr]
    strategy: Content | None = None


class Settings(RequestBody):
    roles: Annotated[list[RoleSettings], Field(min_length=5, max_length=5)]


class ManualSettings(RequestBody):
    mode: Literal["manual"]
    answers: dict[str, dict[str, Answer]]


class AutomaticSettings(RequestBody):
    mode: Literal["automatic"]


SetupSettings = Settings | Annotated[ManualSettings | AutomaticSettings, Field(discriminator="mode")]


class Speech(RequestBody):
    type: Literal["speech"]
    content: Content


class Ballot(RequestBody):
    type: Literal["vote"]
    vote: Vote


ManualInput = Annotated[Speech | Ballot, Field(discriminator="type")]


class Instruction(RequestBody):
    content: Content


class FieldError(BaseModel):
    path: list[str | int]
    message: str


class ApiError(BaseModel):
    code: str
    message: str
    field_errors: list[FieldError] = Field(default_factory=list)


class ConditionSchema(BaseModel):
    id: str
    label: str
    description: str
    type: Literal["boolean", "integer", "string"]
    required: bool
    default: StrictBool | StrictInt | StrictStr
    cost_rub: int
    allowed: list[StrictBool | StrictInt | StrictStr] | None = None
    min_value: int | None = None
    max_value: int | None = None


class RoleSettingsSchema(BaseModel):
    pledged_rub_max: int
    conditions: list[ConditionSchema]


class Role(BaseModel):
    id: str
    name: str
    interest: str


class QuestionnaireOption(BaseModel):
    value: Answer
    label: str


class QuestionnaireRange(BaseModel):
    minimum: int
    maximum: int
    unit: str


class QuestionnaireField(BaseModel):
    id: str
    label: str
    hint: str | None
    options: list[QuestionnaireOption]
    required: bool
    number_range: QuestionnaireRange | None = Field(default=None, exclude_if=lambda value: value is None)


class Questionnaire(BaseModel):
    fields: list[QuestionnaireField]
    defaults: dict[str, Answer]


class Scenario(BaseModel):
    title: str
    briefing: str
    version: str
    role_order: list[str]
    roles: list[Role]
    total_cost_rub: int
    max_bargaining_turns: int
    max_dialogue_messages: int = MAX_DIALOGUE_MESSAGES
    questionnaires: dict[str, Questionnaire] = Field(
        default_factory=lambda: {key: Questionnaire.model_validate(value) for key, value in QUESTIONNAIRES.items()})
    role_settings_schema: dict[str, RoleSettingsSchema]


class SavedRoleSettings(RoleSettings):
    strategy: str | None = None
    answers: dict[str, Answer] | None = Field(default=None, exclude_if=lambda value: value is None)
    spent_on_conditions_rub: int


class SavedSettings(BaseModel):
    roles: list[SavedRoleSettings]
    setup_mode: SetupMode | None = Field(default=None, exclude_if=lambda value: value is None)


Phase = Literal["positions", "negotiation", "amendments", "preparing_protocol", "forecasting", "voting",
                "calculating_result"]


class Message(BaseModel):
    message_id: str
    turn_id: str
    role_id: str
    phase: Phase
    content: str
    skipped: bool = Field(default=False, exclude_if=lambda value: not value)


class SpeechRequest(BaseModel):
    input_id: str
    role_id: str
    type: Literal["speech"]
    turn_id: str


class VoteRequest(BaseModel):
    input_id: str
    role_id: str
    type: Literal["vote"]
    protocol_version: int
    allowed_votes: list[Vote]


class Funding(BaseModel):
    role_id: str
    amount_rub: int | float


class ProtocolItem(BaseModel):
    item_id: str
    title: str
    description: str
    responsible_role_ids: list[str]
    funding: list[Funding]
    value: StrictBool | StrictInt | StrictStr | None = None


class GameProtocol(BaseModel):
    version: int
    items: list[ProtocolItem]


class Indicator(BaseModel):
    id: str
    label: str
    unit: str
    initial_value: str | int | float | None
    year_one_value: str | int | float
    final_value: str | int | float


class FinancialLoad(BaseModel):
    role_id: str
    budget_rub: float | None
    pledged_rub: float
    spent_on_conditions_rub: float
    committed_rub: float
    budget_used_percent: float | None
    over_budget_rub: float | None


class Projection(BaseModel):
    protocol_version: int
    basis: Literal["proposed_protocol", "accepted_protocol", "no_agreement"]
    period_months: int
    indicators: list[Indicator]
    outcome_title: str
    executed_rub: float
    commissioning_month: int | None
    herald_text: str
    image_url: str | None
    model_version: int | None = None
    financial_load: list[FinancialLoad] = Field(default_factory=list)
    report_markdown: str | None = None


class RoleVote(BaseModel):
    role_id: str
    vote: Vote


class VoteSummary(BaseModel):
    for_count: int = Field(alias="for")
    against: int
    abstain: int
    votes: list[RoleVote]


class GameSnapshot(BaseModel):
    game_id: str
    status: Literal["draft", "running", "completed", "cancelled", "failed"]
    phase: Phase | None
    pause_state: Literal["none", "requested", "paused"]
    last_event_id: int
    expires_at: str
    available_actions: list[str]
    scenario: Scenario
    settings: SavedSettings
    current_role_id: str | None
    messages: list[Message]
    pending_input: Annotated[SpeechRequest | VoteRequest, Field(discriminator="type")] | None
    protocol: GameProtocol | None
    forecast: Projection | None
    protocol_status: Literal["pending", "accepted", "rejected"]
    vote_summary: VoteSummary | None
    result: Projection | None
    error: ApiError | None


class MessageCreated(BaseModel):
    event_id: int
    type: Literal["message.created"]
    payload: Message


class StateChanged(BaseModel):
    event_id: int
    type: Literal["settings.saved", "phase.changed", "turn.started", "input.requested", "input.resolved", "pause.changed",
                  "vote.closed", "game.completed", "game.cancelled", "game.failed"]
    payload: dict


class EventPage(BaseModel):
    events: list[Annotated[MessageCreated | StateChanged, Field(discriminator="type")]]
    next_cursor: int
    has_more: bool


class InstructionAccepted(BaseModel):
    instruction_id: str
    applies_to: Literal["next_unstarted_speech"]


ERROR_RESPONSES = {status: {"model": ApiError} for status in (404, 409, 422)}


def settings_schema() -> dict:
    return {role["player_id"]: {
        "pledged_rub_max": int(role["budget_millions"] * 1_000_000),
        "conditions": [{"id": item["id"], "label": item["title"], "description": item["description"],
                        "type": {"bool": "boolean", "int": "integer", "str": "string"}[item["type"]],
                        "required": False, "default": item["default"], "cost_rub": int(item.get("cost", 0)),
                        **{key: item[key] for key in ("allowed", "min_value", "max_value") if key in item}}
                       for item in ROLE_LEVERS[role["player_id"]]],
    } for role in ROLES}


def scenario_contract() -> dict:
    return {**public_scenario(), "version": "1", "role_order": [role["player_id"] for role in ROLES],
            "max_bargaining_turns": len(ROLES), "role_settings_schema": settings_schema(),
            "max_dialogue_messages": MAX_DIALOGUE_MESSAGES, "questionnaires": QUESTIONNAIRES}


def default_settings() -> dict:
    return {"roles": [{"role_id": role_id, "control_mode": "ai", "pledged_rub": 0, "strategy": None,
                       "conditions": {lever["id"]: lever["default"] for lever in levers},
                       "spent_on_conditions_rub": 0} for role_id, levers in ROLE_LEVERS.items()]}


def questionnaire_levers() -> list[dict]:
    minimum, maximum = TIMELINE_MONTHS
    return [{**lever, "min_value": minimum, "max_value": maximum,
             "description": f"Срок ввода очистных сооружений в месяцах. Допустимы целые числа от {minimum} до {maximum}."}
            if lever["id"] == "timeline" else lever for lever in LEVERS]


def spent_on_conditions(levers: list[dict], values: dict) -> int:
    return sum(int(lever.get("cost", 0)) for lever in levers
               if values[lever["id"]] is True
               or (type(values[lever["id"]]) is int and values[lever["id"]] > 0))


def validate_setup_settings(settings: SetupSettings) -> tuple[dict, list]:
    if isinstance(settings, Settings):
        return validate_settings(settings)
    if isinstance(settings, AutomaticSettings):
        answers = {role_id: data["defaults"] for role_id, data in QUESTIONNAIRES.items()}
    else:
        answers = settings.answers
    answers, errors = questionnaire_answers(answers)
    if errors:
        return {}, errors

    roles = []
    for role in ROLES:
        role_id = role["player_id"]
        values = answers[role_id]
        levers = ROLE_LEVERS[role_id]
        # Conditional offers remain open until the owner confirms them during negotiation.
        conditions = {lever["id"]: (values[lever["id"]] if lever["id"] not in CONDITIONAL_COMMITMENTS
                                    else lever["default"]) for lever in levers}
        roles.append({"role_id": role_id, "control_mode": "ai", "answers": values,
                      "conditions": conditions, "pledged_rub": values.get("start_money", 0) * MILLION,
                      "strategy": build_strategy(role_id, values, levers, role["budget_millions"]),
                      "spent_on_conditions_rub": spent_on_conditions(levers, conditions)})
    return {"setup_mode": settings.mode, "roles": roles}, []


def validate_settings(settings: Settings) -> tuple[dict, list]:
    schema = settings_schema()
    roles = {}
    errors = []
    for index, role in enumerate(settings.roles):
        path = ["roles", index]
        if role.role_id not in schema or role.role_id in roles:
            errors.append({"path": [*path, "role_id"], "message": "Укажите известную роль один раз."})
            continue
        definition = schema[role.role_id]
        levers = {item["id"]: item for item in definition["conditions"]}
        values = {lever_id: item["default"] for lever_id, item in levers.items()}
        for lever_id, value in role.conditions.items():
            item = levers.get(lever_id)
            condition_path = [*path, "conditions", lever_id]
            if item is None:
                errors.append({"path": condition_path, "message": "Условие недоступно для этой роли."})
            elif (type(value) is not {"boolean": bool, "integer": int, "string": str}[item["type"]]
                  or ("allowed" in item and value not in item["allowed"])
                  or (type(value) is int and not item.get("min_value", value) <= value <= item.get("max_value", value))):
                errors.append({"path": condition_path, "message": "Недопустимое значение условия."})
            else:
                values[lever_id] = value
        spent = spent_on_conditions(ROLE_LEVERS[role.role_id], values)
        if role.pledged_rub > definition["pledged_rub_max"]:
            errors.append({"path": [*path, "pledged_rub"], "message": "Взнос превышает бюджет роли."})
        roles[role.role_id] = {**role.model_dump(), "conditions": values, "spent_on_conditions_rub": spent}
    return {"roles": [roles[role_id] for role_id in schema if role_id in roles]}, errors


def make_protocol(state: dict, levers: list[dict]) -> dict:
    funding = [{"role_id": role_id, "amount_rub": state["players"][name]["contribution"] or 0}
               for role_id, name in state["player_ids"].items()]
    items = [{"item_id": "project_funding", "title": "Финансирование проекта",
              "description": "Финансирование проекта по итогам дебатов.",
              "responsible_role_ids": [row["role_id"] for row in funding if row["amount_rub"]], "funding": funding}]
    for lever in levers:
        value = state["levers"][lever["id"]]
        owners = [role_id for role_id, name in state["player_ids"].items() if is_owner(lever["owner"], name)]
        items.append({"item_id": lever["id"], "title": lever["title"], "description": lever["description"],
                      "value": value, "responsible_role_ids": owners, "funding": []})
    return {"version": 1, "items": items}


def votes(raw: dict) -> dict:
    rows = [{"role_id": ROLE_BY_NAME[row["player"]], "vote": VOTES[row["vote"]]}
            for row in raw["voting_summary"]["records"]]
    return {**{value: sum(row["vote"] == value for row in rows) for value in ("for", "against", "abstain")},
            "votes": rows}


def projection(raw: dict, version: int, *, basis: str, images: bool) -> dict:
    prediction = forecast(raw)
    year_one = prediction["state"]["year_1"]["subsystems"]
    year_ten = prediction["state"]["year_10"]["subsystems"]
    outcome = prediction["outcome"]
    return {"protocol_version": version, "basis": basis, "period_months": HORIZON_MONTHS,
            "indicators": [{"id": key, "label": label, "unit": "оценка", "initial_value": None,
                            "year_one_value": year_one[key], "final_value": year_ten[key]}
                           for key, label in SUBSYSTEM_LABELS.items()],
            "outcome_title": outcome["name"], "executed_rub": prediction["paid"],
            "commissioning_month": prediction["commissioning_month"], "herald_text": prediction["herald_text"],
            "model_version": prediction["model_version"], "financial_load": prediction["financial_load"],
            "report_markdown": prediction["report"],
            "image_url": (f"/api/v1/illustrations/{outcome['id']}.png"
                          if images and illustration(outcome["id"]) else None)}
