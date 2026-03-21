from backend.domain.models.session import FocusArea


class PrioritizationService:
    """Chooses what the system should advance next."""

    _FOCUS_LABELS = {
        FocusArea.MIND_MAP: "思维导图",
        FocusArea.SUMMARY: "摘要总结",
        FocusArea.PRACTICE_PROBLEM: "实践问题",
        FocusArea.LITERATURE_EVIDENCE: "文献依据",
        FocusArea.RESEARCH_PROBLEM: "研究问题",
        FocusArea.EXPECTED_OUTCOME: "预期成果",
        FocusArea.INTERVENTION_PLAN: "干预计划",
        FocusArea.DATA_COLLECTION_AND_REFLECTION: "资料收集与反思",
    }

    _FOCUS_REASONS = {
        FocusArea.MIND_MAP: "先把核心概念和它们之间的关系理清，后续写作会更稳定。",
        FocusArea.SUMMARY: "当前已经积累了一些要点，适合先压缩成一版可继续修改的摘要。",
        FocusArea.PRACTICE_PROBLEM: "行动研究首先要落在真实、可观察的教学问题上。",
        FocusArea.LITERATURE_EVIDENCE: "把问题和前人研究连接起来，论证会更扎实。",
        FocusArea.RESEARCH_PROBLEM: "先把研究问题说准，后续目标、干预和评估才容易对齐。",
        FocusArea.EXPECTED_OUTCOME: "先明确希望看到什么变化，后面才好判断行动是否有效。",
        FocusArea.INTERVENTION_PLAN: "问题和目标初步明确后，应尽快落实到可执行的教学行动。",
        FocusArea.DATA_COLLECTION_AND_REFLECTION: "想形成研究闭环，就需要提前想清楚证据与反思方式。",
    }

    _FOCUS_GUIDANCE = {
        FocusArea.MIND_MAP: "可以先列出研究对象、课堂现象、可能原因、干预策略和预期变化，再整理它们的关系。",
        FocusArea.SUMMARY: "可以先写一个短版摘要，包含问题、目标、行动和预期证据，后面再逐步精炼语言。",
        FocusArea.PRACTICE_PROBLEM: "建议先把问题描述得具体、可观察，尽量落到某类课堂表现，而不是停留在泛泛判断。",
        FocusArea.LITERATURE_EVIDENCE: "可以先找两三类最相关的理论或研究方向，用来支撑你对问题成因和干预价值的判断。",
        FocusArea.RESEARCH_PROBLEM: "建议先把研究问题收窄到一个明确场景、一个核心对象和一种可观察变化。",
        FocusArea.EXPECTED_OUTCOME: "可以先区分短期变化和观察指标，比如参与人数、回答质量、任务完成度等。",
        FocusArea.INTERVENTION_PLAN: "建议先把干预写成可执行步骤，包括对象、频率、周期和课堂中的具体做法。",
        FocusArea.DATA_COLLECTION_AND_REFLECTION: "可以先确定两三种最容易实施的证据来源，再配一个反思问题帮助进入下一轮修订。",
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
        FocusArea.MIND_MAP: ("思维导图", "脑图", "mind map"),
        FocusArea.SUMMARY: ("摘要", "总结", "概述", "summary"),
        FocusArea.PRACTICE_PROBLEM: ("实践问题", "课堂问题", "痛点", "困境", "problem"),
        FocusArea.LITERATURE_EVIDENCE: ("文献", "理论", "研究依据", "参考文献", "literature"),
        FocusArea.RESEARCH_PROBLEM: ("研究问题", "研究主题", "我想研究", "问题是"),
        FocusArea.EXPECTED_OUTCOME: ("预期成果", "目标", "期望", "希望达到", "outcome"),
        FocusArea.INTERVENTION_PLAN: ("干预", "方案", "策略", "行动计划", "intervention"),
        FocusArea.DATA_COLLECTION_AND_REFLECTION: (
            "数据",
            "资料收集",
            "观察",
            "反思",
            "证据",
            "reflection",
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
                "你觉得这个研究里最核心的 3 到 5 个概念分别是什么？",
                "这些概念之间最重要的关系是什么？",
            ],
            FocusArea.SUMMARY: [
                "如果用两三句话概括你当前的研究设想，你最想保留哪些信息？",
                "和上一版相比，这次最重要的新变化是什么？",
            ],
            FocusArea.PRACTICE_PROBLEM: [
                "你在课堂或教学实践中最想解决的具体现象是什么？",
                "你已经观察到哪些例子或证据，说明这个问题值得优先研究？",
            ],
            FocusArea.LITERATURE_EVIDENCE: [
                "你希望借助哪些理论、作者或研究方向来支撑这个项目？",
                "当前最需要文献支持的观点或判断是什么？",
            ],
            FocusArea.RESEARCH_PROBLEM: [
                "请用尽量具体的一句话说出你想研究的教学或学习问题。",
                "这个问题为什么对你现在的教学场景很重要？",
            ],
            FocusArea.EXPECTED_OUTCOME: [
                "如果这次行动有效，你最希望学生、课堂或教学方式发生什么变化？",
                "你打算用什么现象来判断这种变化已经出现？",
            ],
            FocusArea.INTERVENTION_PLAN: [
                "你准备采取什么具体行动或教学策略来回应这个问题？",
                "这个行动准备在哪个班级、什么时间范围内实施？",
            ],
            FocusArea.DATA_COLLECTION_AND_REFLECTION: [
                "你准备收集哪些资料来观察这次行动是否产生效果？",
                "下一轮反思时，你最想追问自己的一个问题是什么？",
            ],
        }
        return prompts[focus_area]
