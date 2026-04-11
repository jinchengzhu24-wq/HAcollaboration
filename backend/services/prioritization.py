from backend.models.session import FocusArea


class PrioritizationService:
    _FOCUS_LABELS = {
        FocusArea.PROBLEM_FRAMING: "Problem Framing",
        FocusArea.ACTION_DESIGN: "Action Design",
        FocusArea.OBSERVATION_EVIDENCE: "Observation and Evidence",
        FocusArea.REFLECTION_ITERATION: "Reflection and Iteration",
    }

    _FOCUS_REASONS = {
        FocusArea.PROBLEM_FRAMING: (
            "Clarify the classroom problem, the learner group, and the specific change you want to see."
        ),
        FocusArea.ACTION_DESIGN: (
            "Turn the problem into a concrete classroom action with a realistic first-round implementation plan."
        ),
        FocusArea.OBSERVATION_EVIDENCE: (
            "Decide what evidence to collect so you can judge whether the action is actually helping."
        ),
        FocusArea.REFLECTION_ITERATION: (
            "Interpret what worked, what did not, and how the next cycle should be adjusted."
        ),
    }

    _FOCUS_GUIDANCE = {
        FocusArea.PROBLEM_FRAMING: (
            "Anchor this stage in one visible classroom issue, one learner group, and one improvement target."
        ),
        FocusArea.ACTION_DESIGN: (
            "Name who will do what, when it will happen, and what the first implementation round will look like."
        ),
        FocusArea.OBSERVATION_EVIDENCE: (
            "Choose two or three manageable evidence sources that will make change visible without overloading the teacher."
        ),
        FocusArea.REFLECTION_ITERATION: (
            "Separate confirmed gains, unresolved problems, and the adjustment you want to make next."
        ),
    }

    _DEFAULT_QUESTIONS = {
        FocusArea.PROBLEM_FRAMING: [
            "What is the main classroom problem you want to study, and how does it currently show up in class?",
            "Why is this problem worth addressing now, and what early change would you hope to see first?",
        ],
        FocusArea.ACTION_DESIGN: [
            "What classroom action or intervention are you planning to try first?",
            "Which class, time frame, and implementation steps will you use for the first round?",
        ],
        FocusArea.OBSERVATION_EVIDENCE: [
            "What evidence will you collect to judge whether this action is working?",
            "Which classroom behaviors or learner responses will you pay most attention to?",
        ],
        FocusArea.REFLECTION_ITERATION: [
            "Based on the evidence so far, what seems most effective and what still needs improvement?",
            "If you begin another cycle, what would you keep, revise, or add next?",
        ],
    }

    def build_car_stage_plan(self) -> list[dict[str, str | FocusArea]]:
        ordered_focuses = [
            FocusArea.PROBLEM_FRAMING,
            FocusArea.ACTION_DESIGN,
            FocusArea.OBSERVATION_EVIDENCE,
            FocusArea.REFLECTION_ITERATION,
        ]
        return [
            {
                "focus": focus,
                "label": self.focus_label(focus),
                "reason": self.focus_reason(focus),
            }
            for focus in ordered_focuses
        ]

    def focus_label(self, focus_area: FocusArea) -> str:
        return self._FOCUS_LABELS[focus_area]

    def focus_reason(self, focus_area: FocusArea) -> str:
        return self._FOCUS_REASONS[focus_area]

    def focus_guidance(self, focus_area: FocusArea) -> str:
        return self._FOCUS_GUIDANCE[focus_area]

    def default_questions(self, focus_area: FocusArea) -> list[str]:
        return self._DEFAULT_QUESTIONS[focus_area]
