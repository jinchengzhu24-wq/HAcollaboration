from backend.domain.models.session import FocusArea


class PrioritizationService:
    """Chooses what the system should advance next."""

    _FOCUS_LABELS = {
        FocusArea.MIND_MAP: "Concept Map",
        FocusArea.SUMMARY: "Working Summary",
        FocusArea.PRACTICE_PROBLEM: "Practice Problem",
        FocusArea.LITERATURE_EVIDENCE: "Literature Support",
        FocusArea.RESEARCH_PROBLEM: "Research Problem",
        FocusArea.EXPECTED_OUTCOME: "Expected Outcome",
        FocusArea.INTERVENTION_PLAN: "Intervention Plan",
        FocusArea.DATA_COLLECTION_AND_REFLECTION: "Evidence and Reflection",
    }

    _FOCUS_REASONS = {
        FocusArea.MIND_MAP: "It helps us sort the core ideas and how they connect before we write anything longer.",
        FocusArea.SUMMARY: "You already have some useful material, so it makes sense to compress it into a cleaner working version.",
        FocusArea.PRACTICE_PROBLEM: "Action research works best when it starts from a specific classroom problem that can be observed.",
        FocusArea.LITERATURE_EVIDENCE: "Linking the problem to existing research will make the logic and justification more solid.",
        FocusArea.RESEARCH_PROBLEM: "If we sharpen the research problem first, the goals, intervention, and evaluation will line up much more easily.",
        FocusArea.EXPECTED_OUTCOME: "It helps to name the change you want to see before we decide whether the action is working.",
        FocusArea.INTERVENTION_PLAN: "Once the problem is clear enough, we should turn it into a concrete teaching move or action plan.",
        FocusArea.DATA_COLLECTION_AND_REFLECTION: "Thinking about evidence and reflection early will make the next cycle much easier to run.",
    }

    _FOCUS_GUIDANCE = {
        FocusArea.MIND_MAP: "Start by listing the learners, the classroom pattern, likely causes, possible actions, and the change you hope to see.",
        FocusArea.SUMMARY: "Try a short version first that covers the problem, the goal, the action, and the evidence you expect to collect.",
        FocusArea.PRACTICE_PROBLEM: "Keep the problem concrete and observable, and anchor it in one clear classroom situation.",
        FocusArea.LITERATURE_EVIDENCE: "Pick two or three theories or research strands that directly support your reading of the problem.",
        FocusArea.RESEARCH_PROBLEM: "Try to narrow the problem to one setting, one learner group, and one visible change you want to study.",
        FocusArea.EXPECTED_OUTCOME: "Separate the change you hope for from the signs you can actually observe in class.",
        FocusArea.INTERVENTION_PLAN: "Write the intervention as a sequence of teachable steps, including who, when, and how it will happen.",
        FocusArea.DATA_COLLECTION_AND_REFLECTION: "Pick two or three easy evidence sources first, then add one reflection question for the next round.",
    }

    _STATE_KEYS = {
        FocusArea.MIND_MAP: "mind_map",
        FocusArea.SUMMARY: "summary",
        FocusArea.PRACTICE_PROBLEM: "practice_problem",
        FocusArea.LITERATURE_EVIDENCE: "literature_evidence",
        FocusArea.RESEARCH_PROBLEM: "research_problem",
        FocusArea.EXPECTED_OUTCOME: "expected_outcome",
        FocusArea.INTERVENTION_PLAN: "intervention_plan",
        FocusArea.DATA_COLLECTION_AND_REFLECTION: "data_collection_and_reflection",
    }

    _FOCUS_ORDER = [
        FocusArea.RESEARCH_PROBLEM,
        FocusArea.LITERATURE_EVIDENCE,
        FocusArea.EXPECTED_OUTCOME,
        FocusArea.INTERVENTION_PLAN,
        FocusArea.DATA_COLLECTION_AND_REFLECTION,
        FocusArea.SUMMARY,
    ]

    _KEYWORDS = {
        FocusArea.MIND_MAP: ("mind map", "concept map", "思维导图", "脑图"),
        FocusArea.SUMMARY: ("summary", "overview", "摘要", "总结", "概述"),
        FocusArea.PRACTICE_PROBLEM: ("problem", "issue", "challenge", "实践问题", "课堂问题", "痛点"),
        FocusArea.LITERATURE_EVIDENCE: ("literature", "theory", "research support", "文献", "理论", "研究依据"),
        FocusArea.RESEARCH_PROBLEM: ("research problem", "research question", "研究问题", "研究主题"),
        FocusArea.EXPECTED_OUTCOME: ("outcome", "goal", "target", "expected outcome", "预期成果", "目标"),
        FocusArea.INTERVENTION_PLAN: ("intervention", "plan", "strategy", "行动计划", "干预", "方案"),
        FocusArea.DATA_COLLECTION_AND_REFLECTION: (
            "data",
            "evidence",
            "reflection",
            "observation",
            "数据",
            "证据",
            "观察",
            "反思",
        ),
    }

    def choose_next_focus(
        self,
        state_snapshot: dict,
        teacher_revision: str | None,
    ) -> FocusArea:
        explicit_focus = self.match_focus_from_text(teacher_revision)
        if explicit_focus is not None:
            return explicit_focus

        for focus in self._FOCUS_ORDER:
            state_key = self.state_key_for_focus(focus)
            if not state_snapshot.get(state_key):
                return focus

        return FocusArea.SUMMARY

    def detect_initial_focus(self, text: str) -> FocusArea:
        return self.match_focus_from_text(text) or FocusArea.RESEARCH_PROBLEM

    def match_focus_from_text(self, text: str | None) -> FocusArea | None:
        if not text:
            return None

        normalized_text = text.lower()
        for focus_area, keywords in self._KEYWORDS.items():
            if any(keyword.lower() in normalized_text for keyword in keywords):
                return focus_area
        return None

    def focus_label(self, focus_area: FocusArea) -> str:
        return self._FOCUS_LABELS[focus_area]

    def focus_reason(self, focus_area: FocusArea) -> str:
        return self._FOCUS_REASONS[focus_area]

    def focus_guidance(self, focus_area: FocusArea) -> str:
        return self._FOCUS_GUIDANCE[focus_area]

    def state_key_for_focus(self, focus_area: FocusArea) -> str:
        return self._STATE_KEYS[focus_area]

    def default_questions(self, focus_area: FocusArea) -> list[str]:
        prompts = {
            FocusArea.MIND_MAP: [
                "What are the three to five core ideas in this project?",
                "Which relationships between those ideas matter most right now?",
            ],
            FocusArea.SUMMARY: [
                "If you had to explain the project in two or three sentences, what would you keep?",
                "Compared with the last version, what feels most important now?",
            ],
            FocusArea.PRACTICE_PROBLEM: [
                "What classroom pattern or teaching problem do you most want to work on?",
                "What have you already seen that tells you this problem is worth studying?",
            ],
            FocusArea.LITERATURE_EVIDENCE: [
                "Which theories, authors, or research strands feel most relevant here?",
                "What claim or judgment in your project most needs research support?",
            ],
            FocusArea.RESEARCH_PROBLEM: [
                "Can you say your research problem in one concrete sentence?",
                "Why does this problem matter in your current teaching context?",
            ],
            FocusArea.EXPECTED_OUTCOME: [
                "If this action works, what change do you most hope to see?",
                "What would tell you that the change is actually happening?",
            ],
            FocusArea.INTERVENTION_PLAN: [
                "What specific teaching move or intervention are you considering?",
                "Where, when, and with whom do you plan to try it?",
            ],
            FocusArea.DATA_COLLECTION_AND_REFLECTION: [
                "What evidence will you collect to see whether the action is working?",
                "What is one reflection question you want to carry into the next round?",
            ],
        }
        return prompts[focus_area]
