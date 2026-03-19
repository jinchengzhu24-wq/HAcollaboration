from typing import Any

from pydantic import BaseModel, Field

from app.domain.models.session import FocusArea, ResearchCycleStage


class SessionCreateRequest(BaseModel):
    teacher_id: str = Field(..., description="Teacher identifier")
    project_title: str = Field(..., description="Action research project title")
    context_note: str | None = Field(
        default=None,
        description="Optional context provided at session creation",
    )


class SessionAdvanceRequest(BaseModel):
    teacher_revision: str | None = Field(
        default=None,
        description="Teacher-edited content from the previous round",
    )
    teacher_answers: list[str] = Field(
        default_factory=list,
        description="Answers to the focused follow-up questions",
    )
    state_patch: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional structured state updates",
    )


class SessionResponse(BaseModel):
    session_id: str
    teacher_id: str
    project_title: str
    cycle_stage: ResearchCycleStage
    current_focus: FocusArea
    guiding_questions: list[str]
    latest_draft: str | None = None
    state_snapshot: dict[str, Any] = Field(default_factory=dict)

