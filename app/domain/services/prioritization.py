from app.domain.models.session import FocusArea


class PrioritizationService:
    """Chooses what the system should advance next."""

    def choose_next_focus(
        self,
        state_snapshot: dict,
        teacher_revision: str | None,
    ) -> FocusArea:
        if teacher_revision and "literature" in teacher_revision.lower():
            return FocusArea.LITERATURE_EVIDENCE
        if "intervention_plan" not in state_snapshot:
            return FocusArea.INTERVENTION_PLAN
        if "expected_outcome" not in state_snapshot:
            return FocusArea.EXPECTED_OUTCOME
        return FocusArea.DATA_COLLECTION_AND_REFLECTION

    def default_questions(self, focus_area: FocusArea) -> list[str]:
        prompts = {
            FocusArea.MIND_MAP: [
                "What are the key concepts that should appear in the map?",
                "Which concept is central to the current cycle?",
            ],
            FocusArea.SUMMARY: [
                "What should the summary emphasize for this iteration?",
                "What change since the last round must be reflected?",
            ],
            FocusArea.PRACTICE_PROBLEM: [
                "What classroom or practice problem is most urgent?",
                "What observable evidence supports that this is the right problem?",
            ],
            FocusArea.LITERATURE_EVIDENCE: [
                "Which authors or studies should be connected to the current issue?",
                "What claim needs stronger literature support?",
            ],
            FocusArea.RESEARCH_PROBLEM: [
                "What precise teaching or learning issue is being studied?",
                "Why is this issue important in the local context?",
            ],
            FocusArea.EXPECTED_OUTCOME: [
                "What change do you expect after the intervention?",
                "How will you recognize that change in practice?",
            ],
            FocusArea.INTERVENTION_PLAN: [
                "What concrete teaching action will be implemented next?",
                "What is the time scope of that action?",
            ],
            FocusArea.DATA_COLLECTION_AND_REFLECTION: [
                "What data will be collected after the action?",
                "What reflection question should guide the next cycle?",
            ],
        }
        return prompts[focus_area]

