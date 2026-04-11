from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FocusArea(str, Enum):
    PROBLEM_FRAMING = "problem_framing"
    ACTION_DESIGN = "action_design"
    OBSERVATION_EVIDENCE = "observation_evidence"
    REFLECTION_ITERATION = "reflection_iteration"


class ResearchCycleStage(str, Enum):
    PLANNING = "planning"
    ACTION = "action"
    OBSERVATION = "observation"
    REFLECTION = "reflection"


class StageStatus(str, Enum):
    LOCKED = "locked"
    AVAILABLE = "available"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    DELETED = "deleted"


@dataclass
class SessionStage:
    index: int
    label: str
    reason: str
    focus: FocusArea
    questions: list[str] = field(default_factory=list)
    status: StageStatus = StageStatus.LOCKED
    needs_confirmation: bool = False
    is_outdated: bool = False
    visited: bool = False
    summary: str | None = None
    feedback: str | None = None
    guidance: str | None = None
    draft: str | None = None
    latest_answers: list[str] = field(default_factory=list)
    latest_input: str | None = None
    document: dict[str, Any] | None = None

    def is_deleted(self) -> bool:
        return self.status == StageStatus.DELETED


@dataclass
class ResearchSession:
    session_id: str
    teacher_id: str
    project_title: str
    cycle_stage: ResearchCycleStage
    stages: list[SessionStage] = field(default_factory=list)
    active_stage_index: int | None = None
    latest_draft: str | None = None
    state_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "teacher_id": self.teacher_id,
            "project_title": self.project_title,
            "cycle_stage": self.cycle_stage,
            "active_stage_index": self.active_stage_index,
            "latest_draft": self.latest_draft,
            "state_snapshot": self.state_snapshot,
            "stages": [
                {
                    "index": stage.index,
                    "label": stage.label,
                    "reason": stage.reason,
                    "focus": stage.focus,
                    "questions": stage.questions,
                    "status": stage.status,
                    "needs_confirmation": stage.needs_confirmation,
                    "is_outdated": stage.is_outdated,
                    "visited": stage.visited,
                    "summary": stage.summary,
                    "feedback": stage.feedback,
                    "guidance": stage.guidance,
                    "draft": stage.draft,
                    "latest_answers": stage.latest_answers,
                    "latest_input": stage.latest_input,
                    "document": stage.document,
                }
                for stage in self.stages
            ],
        }
