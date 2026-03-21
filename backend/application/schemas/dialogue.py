from pydantic import BaseModel, Field


class DialogueCreateRequest(BaseModel):
    initial_idea: str = Field(..., description="Teacher's initial action-research idea")
    project_title: str | None = Field(default=None, description="Optional project title")
    teacher_id: str = Field(default="web_teacher")


class DialoguePlanRequest(BaseModel):
    confirmed: bool
    adjustment_text: str | None = None


class DialogueTurnRequest(BaseModel):
    answers: list[str] = Field(default_factory=list)
    latest_input: str | None = None


class DialogueDocumentEditRequest(BaseModel):
    content: str


class DialogueStageResponse(BaseModel):
    index: int
    label: str
    reason: str


class DialogueDocumentResponse(BaseModel):
    stage_index: int
    stage_label: str
    file_name: str
    download_url: str
    source: str
    preview_text: str
    is_modified: bool = False
    modification_summary: str | None = None
    updated_at: str | None = None


class DialogueSessionResponse(BaseModel):
    session_id: str
    llm_status: str
    opening_message: str
    plan_confirmed: bool
    stage_plan: list[DialogueStageResponse]
    current_round_label: str
    remaining_rounds: int
    current_questions: list[str]
    awaiting_document_review: bool = False
    active_stage_number: int | None = None
    completed_stage_count: int = 0
    current_document: DialogueDocumentResponse | None = None
    stage_documents: list[DialogueDocumentResponse] = Field(default_factory=list)
    is_complete: bool = False
    final_summary: str | None = None


class DialoguePlanResponse(BaseModel):
    message: str
    plan_confirmed: bool
    stage_plan: list[DialogueStageResponse]
    current_round_label: str
    remaining_rounds: int
    current_questions: list[str]
    awaiting_document_review: bool = False
    active_stage_number: int | None = None
    completed_stage_count: int = 0
    current_document: DialogueDocumentResponse | None = None
    stage_documents: list[DialogueDocumentResponse] = Field(default_factory=list)


class DialogueTurnResponse(BaseModel):
    message: str
    stage_feedback: str
    guidance: str
    draft: str
    next_questions: list[str]
    current_round_label: str
    remaining_rounds: int
    awaiting_document_review: bool = False
    active_stage_number: int | None = None
    completed_stage_count: int = 0
    current_document: DialogueDocumentResponse | None = None
    stage_documents: list[DialogueDocumentResponse] = Field(default_factory=list)
    is_complete: bool
    final_summary: str | None = None


class DialogueContinueResponse(BaseModel):
    message: str
    current_round_label: str
    remaining_rounds: int
    current_questions: list[str]
    awaiting_document_review: bool = False
    active_stage_number: int | None = None
    completed_stage_count: int = 0
    current_document: DialogueDocumentResponse | None = None
    stage_documents: list[DialogueDocumentResponse] = Field(default_factory=list)


class DialogueDocumentUploadResponse(BaseModel):
    message: str
    current_document: DialogueDocumentResponse
    stage_documents: list[DialogueDocumentResponse] = Field(default_factory=list)
