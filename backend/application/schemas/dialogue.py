from pydantic import BaseModel, Field


class DialogueCreateRequest(BaseModel):
    initial_idea: str = Field(..., description="Teacher's initial action-research idea")
    project_title: str | None = Field(
        default=None,
        description="Optional project title",
    )
    teacher_id: str = Field(default="web_teacher")


class DialoguePlanRequest(BaseModel):
    confirmed: bool
    adjustment_text: str | None = None


class DialogueTurnRequest(BaseModel):
    answers: list[str] = Field(default_factory=list)
    latest_input: str | None = None


class DialogueStageResponse(BaseModel):
    index: int
    label: str
    reason: str


class DialogueSessionResponse(BaseModel):
    session_id: str
    llm_status: str
    opening_message: str
    plan_confirmed: bool
    stage_plan: list[DialogueStageResponse]
    current_round_label: str
    remaining_rounds: int
    current_questions: list[str]
    is_complete: bool = False
    final_summary: str | None = None


class DialoguePlanResponse(BaseModel):
    message: str
    plan_confirmed: bool
    stage_plan: list[DialogueStageResponse]
    current_round_label: str
    remaining_rounds: int
    current_questions: list[str]


class DialogueTurnResponse(BaseModel):
    message: str
    stage_feedback: str
    guidance: str
    draft: str
    next_questions: list[str]
    current_round_label: str
    remaining_rounds: int
    is_complete: bool
    final_summary: str | None = None

