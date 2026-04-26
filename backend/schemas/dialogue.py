from pydantic import BaseModel, Field


class DialogueCreateRequest(BaseModel):
    initial_idea: str = Field(..., description="Teacher's initial action-research idea")
    project_title: str | None = Field(default=None, description="Optional project title")
    teacher_id: str = Field(default="web_teacher")
    cida_enabled: bool = Field(default=False, description="Enable CIDA inquiry/collaboration/technology support")


class DialogueTurnRequest(BaseModel):
    answers: list[str] = Field(default_factory=list)
    latest_input: str | None = None


class DialogueDocumentEditRequest(BaseModel):
    content: str


class DialogueRegenerateRequest(BaseModel):
    content: str | None = None


class DialogueCombinedDocumentEditRequest(BaseModel):
    content: str


class DialogueCidaModeRequest(BaseModel):
    enabled: bool


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


class DialogueStageResponse(BaseModel):
    index: int
    focus: str
    label: str
    reason: str
    status: str
    is_active: bool
    is_outdated: bool = False
    needs_confirmation: bool = False
    can_activate: bool = False
    can_confirm: bool = False
    can_skip: bool = False
    can_delete: bool = False
    can_review: bool = False
    can_regenerate: bool = False
    questions: list[str] = Field(default_factory=list)
    draft: str | None = None
    summary: str | None = None
    feedback: str | None = None
    guidance: str | None = None
    latest_answers: list[str] = Field(default_factory=list)
    latest_input: str | None = None
    document: DialogueDocumentResponse | None = None
    cida_guidance: list[str] = Field(default_factory=list)


class DialogueSessionResponse(BaseModel):
    session_id: str
    project_title: str
    llm_status: str
    opening_message: str
    current_round_label: str
    current_questions: list[str]
    active_stage_index: int | None = None
    cida_enabled: bool = False
    is_complete: bool = False
    message: str | None = None
    combined_document: str = ""
    stages: list[DialogueStageResponse] = Field(default_factory=list)
