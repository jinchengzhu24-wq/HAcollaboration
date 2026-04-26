from __future__ import annotations

from dataclasses import dataclass

from backend.models.session import FocusArea


@dataclass(frozen=True)
class CidaSupportItem:
    dimension: str
    prompt: str


class CidaSupportService:
    _SUPPORT_ITEMS = {
        FocusArea.PROBLEM_FRAMING: [
            CidaSupportItem(
                dimension="Inquiry process",
                prompt="Identify what classroom data or observable evidence shows that this problem is worth investigating.",
            ),
            CidaSupportItem(
                dimension="Collective process",
                prompt="Name who should help interpret the problem, such as peer teachers, students, or a mentor.",
            ),
            CidaSupportItem(
                dimension="Technological support",
                prompt="Record which system artifacts, uploads, notes, or data sources should be kept for later comparison.",
            ),
        ],
        FocusArea.ACTION_DESIGN: [
            CidaSupportItem(
                dimension="Inquiry process",
                prompt="State the working hypothesis that connects the planned action to the expected classroom change.",
            ),
            CidaSupportItem(
                dimension="Collective process",
                prompt="Clarify teacher, peer, and learner roles so the action can be coordinated rather than done alone.",
            ),
            CidaSupportItem(
                dimension="Technological support",
                prompt="Specify what templates, reminders, shared notes, or generated documents the system should provide.",
            ),
        ],
        FocusArea.OBSERVATION_EVIDENCE: [
            CidaSupportItem(
                dimension="Inquiry process",
                prompt="Define the indicators and evidence sources that will make progress visible during the action.",
            ),
            CidaSupportItem(
                dimension="Collective process",
                prompt="Decide who will observe, review, or compare evidence so interpretation is not only individual.",
            ),
            CidaSupportItem(
                dimension="Technological support",
                prompt="Plan how evidence will be stored, tagged, summarized, or linked to the working document.",
            ),
        ],
        FocusArea.REFLECTION_ITERATION: [
            CidaSupportItem(
                dimension="Inquiry process",
                prompt="Use collected evidence to separate confirmed findings, weak signals, and alternative explanations.",
            ),
            CidaSupportItem(
                dimension="Collective process",
                prompt="Invite collaborators to validate the interpretation and negotiate the next-cycle decision.",
            ),
            CidaSupportItem(
                dimension="Technological support",
                prompt="Preserve the revision trail and generate next-cycle prompts from the evidence-based reflection.",
            ),
        ],
    }

    def support_items(self, focus_area: FocusArea) -> list[CidaSupportItem]:
        return list(self._SUPPORT_ITEMS[focus_area])

    def support_questions(self, focus_area: FocusArea) -> list[str]:
        return [f"{item.dimension}: {item.prompt}" for item in self.support_items(focus_area)]

    def support_notes(self, focus_area: FocusArea) -> str:
        return "\n".join(f"{item.dimension}: {item.prompt}" for item in self.support_items(focus_area))
