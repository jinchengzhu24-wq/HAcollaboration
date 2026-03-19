from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FocusArea(str, Enum):
    MIND_MAP = "mind_map"
    SUMMARY = "summary"
    PRACTICE_PROBLEM = "practice_problem"
    LITERATURE_EVIDENCE = "literature_evidence"
    RESEARCH_PROBLEM = "research_problem"
    EXPECTED_OUTCOME = "expected_outcome"
    INTERVENTION_PLAN = "intervention_plan"
    DATA_COLLECTION_AND_REFLECTION = "data_collection_and_reflection"


class ResearchCycleStage(str, Enum):
    PLANNING = "planning"
    ACTION = "action"
    OBSERVATION = "observation"
    REFLECTION = "reflection"


@dataclass
class ResearchSession:
    session_id: str
    teacher_id: str
    project_title: str
    cycle_stage: ResearchCycleStage
    current_focus: FocusArea
    guiding_questions: list[str] = field(default_factory=list)
    latest_draft: str | None = None
    state_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "teacher_id": self.teacher_id,
            "project_title": self.project_title,
            "cycle_stage": self.cycle_stage,
            "current_focus": self.current_focus,
            "guiding_questions": self.guiding_questions,
            "latest_draft": self.latest_draft,
            "state_snapshot": self.state_snapshot,
        }

