from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from backend.core.config import get_settings
from backend.domain.models.session import FocusArea, ResearchCycleStage, ResearchSession
from backend.domain.services.prioritization import PrioritizationService
from backend.infrastructure.llm.deepseek_client import DeepSeekClient


@dataclass
class DialogueReply:
    message: str
    stage_feedback: str
    guidance: str
    draft: str
    next_questions: list[str]
    remaining_rounds: int
    is_complete: bool
    final_summary: str | None = None


class DialogueService:
    """Local terminal dialogue flow for quick prototyping inside PyCharm."""

    def __init__(self) -> None:
        settings = get_settings()
        self.prioritization_service = PrioritizationService()
        self.deepseek_client: DeepSeekClient | None = None
        if settings.deepseek_api_key:
            self.deepseek_client = DeepSeekClient(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                model=settings.deepseek_model,
                timeout_seconds=settings.deepseek_timeout_seconds,
            )

    def create_session(
        self,
        project_title: str,
        initial_idea: str,
        teacher_id: str = "local_teacher",
    ) -> ResearchSession:
        opening_plan = self._generate_opening_plan(
            project_title=project_title,
            initial_idea=initial_idea,
        )
        stage_plan = self._normalize_stage_plan(
            opening_plan.get("stage_plan"),
            fallback=self._derive_stage_plan(initial_idea),
        )
        first_stage = stage_plan[0]
        first_focus = first_stage["focus"]

        session = ResearchSession(
            session_id=str(uuid4()),
            teacher_id=teacher_id,
            project_title=project_title,
            cycle_stage=ResearchCycleStage.PLANNING,
            current_focus=first_focus,
            guiding_questions=self._normalize_questions(
                opening_plan.get("questions"),
                fallback=self.prioritization_service.default_questions(first_focus),
            ),
            latest_draft=None,
            state_snapshot={
                "initial_idea": initial_idea,
                "conversation_round": 1,
                "conversation_history": [],
                "opening_acknowledgement": self._normalize_text(
                    opening_plan.get("acknowledgement"),
                    fallback=f"我先理解一下你的想法：{initial_idea}",
                ),
                "plan_overview": self._normalize_text(
                    opening_plan.get("plan_overview"),
                    fallback="我先按信息完整度和行动研究推进顺序，把它拆成几个阶段。",
                ),
                "opening_guidance": self._normalize_text(
                    opening_plan.get("initial_guidance"),
                    fallback=self.prioritization_service.focus_guidance(first_focus),
                ),
                "llm_enabled": self.deepseek_client is not None,
                "stage_plan": stage_plan,
                "current_stage_index": 0,
                "total_rounds": len(stage_plan),
                "plan_confirmed": False,
                "current_focus_reason": first_stage["reason"],
            },
        )
        return session

    def build_opening_message(self, session: ResearchSession) -> str:
        acknowledgement = session.state_snapshot.get(
            "opening_acknowledgement",
            f"我先理解一下你的想法：{session.state_snapshot['initial_idea']}",
        )
        plan_overview = session.state_snapshot.get(
            "plan_overview",
            "我先把这个项目拆成若干阶段来推进。",
        )
        total_rounds = session.state_snapshot.get("total_rounds", 1)
        current_focus_reason = session.state_snapshot.get(
            "current_focus_reason",
            self.prioritization_service.focus_reason(session.current_focus),
        )
        opening_guidance = session.state_snapshot.get(
            "opening_guidance",
            self.prioritization_service.focus_guidance(session.current_focus),
        )
        stage_lines = [
            f"{index}. {stage['label']}：{stage['reason']}"
            for index, stage in enumerate(session.state_snapshot.get("stage_plan", []), start=1)
        ]
        return (
            f"{acknowledgement}\n"
            f"{plan_overview}\n"
            f"基于你当前提供的信息，我建议先按这 {total_rounds} 轮来推进：\n"
            f"{chr(10).join(stage_lines)}\n"
            f"当前第一轮先聚焦【{self.prioritization_service.focus_label(session.current_focus)}】。\n"
            f"原因是：{current_focus_reason}\n"
            f"我的初步思路是：{opening_guidance}\n"
            "如果这个分阶段安排合理，我们就从第一轮开始；如果不合理，你可以马上让我调整。"
        )

    def confirm_stage_plan(self, session: ResearchSession) -> str:
        session.state_snapshot["plan_confirmed"] = True
        return (
            f"好，我们就按这个节奏推进。"
            f"当前还有 {self.remaining_rounds(session)} 轮聚焦问答，先从"
            f"【{self.prioritization_service.focus_label(session.current_focus)}】开始。"
        )

    def revise_stage_plan(self, session: ResearchSession, adjustment_text: str) -> str:
        revised_plan = self._generate_revised_stage_plan(session, adjustment_text)
        stage_plan = self._normalize_stage_plan(
            revised_plan.get("stage_plan"),
            fallback=self._derive_stage_plan(
                f"{session.state_snapshot.get('initial_idea', '')}\n{adjustment_text}"
            ),
        )
        first_stage = stage_plan[0]
        first_focus = first_stage["focus"]

        session.state_snapshot["stage_plan"] = stage_plan
        session.state_snapshot["current_stage_index"] = 0
        session.state_snapshot["total_rounds"] = len(stage_plan)
        session.state_snapshot["plan_confirmed"] = True
        session.state_snapshot["plan_overview"] = self._normalize_text(
            revised_plan.get("plan_overview"),
            fallback="我已经根据你的反馈重新调整了阶段安排。",
        )
        session.state_snapshot["opening_guidance"] = self._normalize_text(
            revised_plan.get("initial_guidance"),
            fallback=self.prioritization_service.focus_guidance(first_focus),
        )
        session.state_snapshot["current_focus_reason"] = first_stage["reason"]
        session.current_focus = first_focus
        session.guiding_questions = self._normalize_questions(
            revised_plan.get("questions"),
            fallback=self.prioritization_service.default_questions(first_focus),
        )
        return (
            "我已经按你的意见调整了阶段安排。\n"
            f"{self.build_opening_message(session)}"
        )

    def get_current_questions(self, session: ResearchSession) -> list[str]:
        return session.guiding_questions

    def get_current_round_label(self, session: ResearchSession) -> str:
        stage_index = session.state_snapshot.get("current_stage_index", 0)
        total_rounds = session.state_snapshot.get("total_rounds", 1)
        focus_label = self.prioritization_service.focus_label(session.current_focus)
        return f"第 {stage_index + 1}/{total_rounds} 轮：{focus_label}"

    def remaining_rounds(self, session: ResearchSession) -> int:
        total_rounds = session.state_snapshot.get("total_rounds", 1)
        current_stage_index = session.state_snapshot.get("current_stage_index", 0)
        return max(total_rounds - current_stage_index, 0)

    def advance_session(
        self,
        session: ResearchSession,
        answers: list[str],
        latest_input: str | None = None,
    ) -> DialogueReply:
        current_focus = session.current_focus
        current_stage_index = session.state_snapshot.get("current_stage_index", 0)
        total_rounds = session.state_snapshot.get("total_rounds", 1)
        current_stage = session.state_snapshot["stage_plan"][current_stage_index]
        stage_key = self.prioritization_service.state_key_for_focus(current_focus)

        reply_payload = self._generate_round_reply(
            session=session,
            answers=answers,
            latest_input=latest_input,
        )

        round_summary = self._normalize_text(
            reply_payload.get("current_focus_summary"),
            fallback=self._build_round_summary(
                session=session,
                focus_area=current_focus,
                answers=answers,
                latest_input=latest_input,
            ),
        )
        stage_feedback = self._normalize_text(
            reply_payload.get("stage_feedback"),
            fallback=self._build_stage_feedback(current_focus, answers, latest_input),
        )
        guidance = self._normalize_text(
            reply_payload.get("guidance"),
            fallback=self._build_guidance(current_focus, answers, latest_input),
        )
        draft = self._normalize_text(
            reply_payload.get("draft"),
            fallback=self._build_draft(
                session=session,
                focus_area=current_focus,
                round_summary=round_summary,
            ),
        )

        session.state_snapshot[stage_key] = round_summary
        session.state_snapshot["conversation_history"].append(
            {
                "round_index": current_stage_index + 1,
                "focus": current_focus.value,
                "focus_label": current_stage["label"],
                "answers": answers,
                "latest_input": latest_input or "",
                "summary": round_summary,
                "feedback": stage_feedback,
                "guidance": guidance,
                "draft": draft,
            }
        )
        session.state_snapshot["conversation_round"] += 1
        session.latest_draft = draft
        session.cycle_stage = self._next_stage(session.cycle_stage)

        next_stage_index = current_stage_index + 1
        remaining_rounds = max(total_rounds - next_stage_index, 0)
        session.state_snapshot["current_stage_index"] = next_stage_index

        if next_stage_index >= total_rounds:
            final_summary = self._normalize_text(
                reply_payload.get("final_summary"),
                fallback=self._build_final_summary(session),
            )
            message = self._normalize_text(
                reply_payload.get("coach_message"),
                fallback="这一轮的关键信息已经收束好了。下面我把整个对话先总结一下。",
            )
            return DialogueReply(
                message=message,
                stage_feedback=stage_feedback,
                guidance=guidance,
                draft=draft,
                next_questions=[],
                remaining_rounds=0,
                is_complete=True,
                final_summary=final_summary,
            )

        next_stage = session.state_snapshot["stage_plan"][next_stage_index]
        next_focus = next_stage["focus"]
        next_questions = self._normalize_questions(
            reply_payload.get("next_questions"),
            fallback=self.prioritization_service.default_questions(next_focus),
        )
        session.current_focus = next_focus
        session.guiding_questions = next_questions
        session.state_snapshot["current_focus_reason"] = next_stage["reason"]

        message = self._normalize_text(
            reply_payload.get("coach_message"),
            fallback=(
                f"这一轮我先帮你收束成一个【{current_stage['label']}】的小结。"
                f"接下来还剩 {remaining_rounds} 轮，我们继续推进【{next_stage['label']}】。"
            ),
        )
        return DialogueReply(
            message=message,
            stage_feedback=stage_feedback,
            guidance=guidance,
            draft=draft,
            next_questions=next_questions,
            remaining_rounds=remaining_rounds,
            is_complete=False,
        )

    def llm_status_text(self) -> str:
        if self.deepseek_client is None:
            return "当前未配置 DeepSeek API，正在使用本地规则版。"
        return "当前已启用 DeepSeek API，阶段规划、提问和草稿将由模型生成。"

    def _generate_opening_plan(
        self,
        project_title: str,
        initial_idea: str,
    ) -> dict[str, Any]:
        if self.deepseek_client is None:
            stage_plan = self._derive_stage_plan(initial_idea)
            first_focus = stage_plan[0]["focus"]
            return {
                "acknowledgement": f"我先理解一下你的想法：{initial_idea}",
                "plan_overview": "我先按信息完整度和行动研究推进顺序，把它拆成几个阶段。",
                "stage_plan": [
                    {
                        "focus": stage["focus"].value,
                        "label": stage["label"],
                        "reason": stage["reason"],
                    }
                    for stage in stage_plan
                ],
                "initial_guidance": self.prioritization_service.focus_guidance(first_focus),
                "questions": self.prioritization_service.default_questions(first_focus),
            }

        system_prompt = """
You are an action-research facilitator, not a general chatbot.
Read the teacher's idea and split it into several reasonable stages.
Return valid json only.

Each stage focus must be one of:
- mind_map
- summary
- practice_problem
- literature_evidence
- research_problem
- expected_outcome
- intervention_plan
- data_collection_and_reflection

Return this json shape:
{
  "acknowledgement": "short Chinese acknowledgement",
  "plan_overview": "short Chinese explanation of why you split the work this way",
  "stage_plan": [
    {
      "focus": "one focus value from the list above",
      "label": "Chinese label",
      "reason": "short Chinese reason"
    }
  ],
  "initial_guidance": "short Chinese actionable guidance for stage 1",
  "questions": ["question 1 in Chinese", "question 2 in Chinese"]
}

Rules:
- create 2 to 5 stages
- the stages should reflect how complete or incomplete the teacher's idea is
- keep the questions focused only on stage 1
"""
        user_prompt = (
            "Please propose a staged action-research conversation plan in Chinese.\n"
            f"Project title: {project_title}\n"
            f"Teacher idea: {initial_idea}"
        )
        try:
            return self.deepseek_client.generate_json(system_prompt, user_prompt)
        except Exception:
            stage_plan = self._derive_stage_plan(initial_idea)
            first_focus = stage_plan[0]["focus"]
            return {
                "acknowledgement": f"我先理解一下你的想法：{initial_idea}",
                "plan_overview": "我先按信息完整度和行动研究推进顺序，把它拆成几个阶段。",
                "stage_plan": [
                    {
                        "focus": stage["focus"].value,
                        "label": stage["label"],
                        "reason": stage["reason"],
                    }
                    for stage in stage_plan
                ],
                "initial_guidance": self.prioritization_service.focus_guidance(first_focus),
                "questions": self.prioritization_service.default_questions(first_focus),
            }

    def _generate_revised_stage_plan(
        self,
        session: ResearchSession,
        adjustment_text: str,
    ) -> dict[str, Any]:
        if self.deepseek_client is None:
            stage_plan = self._derive_stage_plan(
                f"{session.state_snapshot.get('initial_idea', '')}\n{adjustment_text}"
            )
            first_focus = stage_plan[0]["focus"]
            return {
                "plan_overview": "我根据你的反馈重新调整了推进顺序。",
                "stage_plan": [
                    {
                        "focus": stage["focus"].value,
                        "label": stage["label"],
                        "reason": stage["reason"],
                    }
                    for stage in stage_plan
                ],
                "initial_guidance": self.prioritization_service.focus_guidance(first_focus),
                "questions": self.prioritization_service.default_questions(first_focus),
            }

        system_prompt = """
You are an action-research facilitator.
Revise the stage plan based on the teacher's feedback.
Return valid json only.

Each stage focus must be one of:
- mind_map
- summary
- practice_problem
- literature_evidence
- research_problem
- expected_outcome
- intervention_plan
- data_collection_and_reflection

Return this json shape:
{
  "plan_overview": "short Chinese explanation",
  "stage_plan": [
    {
      "focus": "one focus value from the list above",
      "label": "Chinese label",
      "reason": "short Chinese reason"
    }
  ],
  "initial_guidance": "short Chinese actionable guidance for the new stage 1",
  "questions": ["question 1 in Chinese", "question 2 in Chinese"]
}
"""
        user_prompt = (
            "Revise the staged action-research plan in Chinese.\n"
            f"Project title: {session.project_title}\n"
            f"Teacher initial idea: {session.state_snapshot.get('initial_idea', '')}\n"
            f"Original stage plan: {session.state_snapshot.get('stage_plan', [])}\n"
            f"Teacher feedback on the plan: {adjustment_text}"
        )
        try:
            return self.deepseek_client.generate_json(system_prompt, user_prompt)
        except Exception:
            stage_plan = self._derive_stage_plan(
                f"{session.state_snapshot.get('initial_idea', '')}\n{adjustment_text}"
            )
            first_focus = stage_plan[0]["focus"]
            return {
                "plan_overview": "我根据你的反馈重新调整了推进顺序。",
                "stage_plan": [
                    {
                        "focus": stage["focus"].value,
                        "label": stage["label"],
                        "reason": stage["reason"],
                    }
                    for stage in stage_plan
                ],
                "initial_guidance": self.prioritization_service.focus_guidance(first_focus),
                "questions": self.prioritization_service.default_questions(first_focus),
            }

    def _generate_round_reply(
        self,
        session: ResearchSession,
        answers: list[str],
        latest_input: str | None,
    ) -> dict[str, Any]:
        current_focus = session.current_focus
        current_stage_index = session.state_snapshot.get("current_stage_index", 0)
        total_rounds = session.state_snapshot.get("total_rounds", 1)
        current_stage = session.state_snapshot["stage_plan"][current_stage_index]
        is_last_stage = current_stage_index + 1 >= total_rounds

        fallback_summary = self._build_round_summary(
            session=session,
            focus_area=current_focus,
            answers=answers,
            latest_input=latest_input,
        )
        fallback_feedback = self._build_stage_feedback(
            current_focus,
            answers,
            latest_input,
        )
        fallback_guidance = self._build_guidance(
            current_focus,
            answers,
            latest_input,
        )
        fallback_draft = self._build_draft(
            session=session,
            focus_area=current_focus,
            round_summary=fallback_summary,
        )
        fallback_next_questions = []
        if not is_last_stage:
            next_stage = session.state_snapshot["stage_plan"][current_stage_index + 1]
            fallback_next_questions = self.prioritization_service.default_questions(
                next_stage["focus"]
            )

        if self.deepseek_client is None:
            payload = {
                "current_focus_summary": fallback_summary,
                "stage_feedback": fallback_feedback,
                "guidance": fallback_guidance,
                "draft": fallback_draft,
                "coach_message": (
                    "这一轮已经整理好了，下面我把整个对话先总结一下。"
                    if is_last_stage
                    else (
                        f"这一轮我先帮你收束成一个【{current_stage['label']}】的小结。"
                        "接下来我们进入下一轮。"
                    )
                ),
                "next_questions": fallback_next_questions,
            }
            if is_last_stage:
                payload["final_summary"] = self._build_final_summary(session)
            return payload

        next_stage = (
            None if is_last_stage else session.state_snapshot["stage_plan"][current_stage_index + 1]
        )
        system_prompt = """
You are an action-research facilitator, not a general chatbot.
You must follow the predefined stage plan instead of inventing a new order.
Return valid json only in Chinese.

Return this json shape:
{
  "current_focus_summary": "1 short paragraph in Chinese",
  "stage_feedback": "1 to 3 sentences of brief feedback on the teacher's answers",
  "guidance": "2 to 4 sentences of actionable Chinese guidance for the teacher",
  "draft": "a revision-friendly Chinese draft for the current stage",
  "coach_message": "short Chinese transition message",
  "next_questions": ["question 1 in Chinese", "question 2 in Chinese"],
  "final_summary": "Chinese final summary when this is the last stage, otherwise empty string"
}

Rules:
- give a little feedback after each round
- if this is not the last stage, next_questions should target the next planned stage
- if this is the last stage, set next_questions to an empty list and provide final_summary
"""
        user_prompt = (
            "Continue this staged action-research conversation in Chinese.\n"
            f"Project title: {session.project_title}\n"
            f"Initial idea: {session.state_snapshot.get('initial_idea', '')}\n"
            f"Stage plan: {session.state_snapshot.get('stage_plan', [])}\n"
            f"Current stage index: {current_stage_index + 1}\n"
            f"Current stage label: {current_stage['label']}\n"
            f"Current stage focus: {current_focus.value}\n"
            f"Current cycle stage: {session.cycle_stage.value}\n"
            f"Teacher answer 1: {answers[0] if len(answers) > 0 else ''}\n"
            f"Teacher answer 2: {answers[1] if len(answers) > 1 else ''}\n"
            f"Teacher extra input: {latest_input or ''}\n"
            f"Previous conversation history: {session.state_snapshot.get('conversation_history', [])}\n"
            f"Next planned stage: {next_stage if next_stage is not None else 'This is the final stage.'}"
        )
        try:
            return self.deepseek_client.generate_json(system_prompt, user_prompt)
        except Exception:
            payload = {
                "current_focus_summary": fallback_summary,
                "stage_feedback": fallback_feedback,
                "guidance": fallback_guidance,
                "draft": fallback_draft,
                "coach_message": (
                    "这一轮已经整理好了，下面我把整个对话先总结一下。"
                    if is_last_stage
                    else (
                        f"这一轮我先帮你收束成一个【{current_stage['label']}】的小结。"
                        "接下来我们进入下一轮。"
                    )
                ),
                "next_questions": fallback_next_questions,
            }
            if is_last_stage:
                payload["final_summary"] = self._build_final_summary(session)
            return payload

    def _build_round_summary(
        self,
        session: ResearchSession,
        focus_area: FocusArea,
        answers: list[str],
        latest_input: str | None,
    ) -> str:
        initial_idea = session.state_snapshot.get("initial_idea", "")
        answer_one = answers[0] if len(answers) > 0 else "暂无回答"
        answer_two = answers[1] if len(answers) > 1 else "暂无回答"
        supplement = latest_input.strip() if latest_input else "暂无额外补充"
        focus_label = self.prioritization_service.focus_label(focus_area)
        return (
            f"{focus_label}围绕“{initial_idea}”展开。"
            f"第一点，{answer_one}。"
            f"第二点，{answer_two}。"
            f"补充说明：{supplement}。"
        )

    def _build_stage_feedback(
        self,
        focus_area: FocusArea,
        answers: list[str],
        latest_input: str | None,
    ) -> str:
        focus_label = self.prioritization_service.focus_label(focus_area)
        answer_count = sum(1 for item in answers if item.strip())
        if answer_count == 0:
            return f"这一轮关于【{focus_label}】的信息还比较少，不过方向已经出来了，我们可以边问边收束。"

        feedback = [f"你这一轮对【{focus_label}】已经给出了比较明确的线索。"]
        if answers and answers[0].strip():
            feedback.append("第一条回答已经提供了一个可继续展开的核心点。")
        if len(answers) > 1 and answers[1].strip():
            feedback.append("第二条回答让这个阶段的判断更具体了一些。")
        if latest_input and latest_input.strip():
            feedback.append("你后面的补充也帮助我把重点收得更稳。")
        return "".join(feedback)

    def _build_guidance(
        self,
        focus_area: FocusArea,
        answers: list[str],
        latest_input: str | None,
    ) -> str:
        base_guidance = self.prioritization_service.focus_guidance(focus_area)
        answer_one = answers[0].strip() if len(answers) > 0 and answers[0].strip() else ""
        answer_two = answers[1].strip() if len(answers) > 1 and answers[1].strip() else ""
        supplement = latest_input.strip() if latest_input else ""

        details = []
        if answer_one:
            details.append(f"你可以优先围绕“{answer_one}”继续细化。")
        if answer_two:
            details.append(f"同时把“{answer_two}”转成更具体、可观察的表述。")
        if supplement:
            details.append(f"你刚补充的“{supplement}”也值得写进这一轮草稿里。")

        if not details:
            return base_guidance
        return f"{base_guidance} {' '.join(details)}"

    def _build_draft(
        self,
        session: ResearchSession,
        focus_area: FocusArea,
        round_summary: str,
    ) -> str:
        stage_label = self._stage_label(session.cycle_stage)
        focus_label = self.prioritization_service.focus_label(focus_area)
        return (
            f"【当前阶段：{stage_label}】\n"
            f"【当前聚焦：{focus_label}】\n"
            f"{round_summary}\n"
            "这是一版可继续修改的工作草稿，后续可以继续补充证据、细化行动或调整表述。"
        )

    def _build_final_summary(self, session: ResearchSession) -> str:
        lines = [
            f"项目：{session.project_title}",
            f"初始想法：{session.state_snapshot.get('initial_idea', '')}",
            "本次对话已经完成的阶段：",
        ]
        for item in session.state_snapshot.get("conversation_history", []):
            lines.append(
                f"- 第 {item['round_index']} 轮【{item['focus_label']}】：{item['summary']}"
            )
        lines.append("如果你愿意，下一步可以把这些小结整合成正式的行动研究方案初稿。")
        return "\n".join(lines)

    def _derive_stage_plan(self, seed_text: str) -> list[dict[str, Any]]:
        text = seed_text.lower()
        stages: list[FocusArea] = [FocusArea.RESEARCH_PROBLEM]

        if any(keyword in text for keyword in ("文献", "理论", "literature", "研究依据")):
            stages.append(FocusArea.LITERATURE_EVIDENCE)

        if any(keyword in text for keyword in ("目标", "预期", "希望达到", "效果", "结果")):
            stages.append(FocusArea.EXPECTED_OUTCOME)

        stages.append(FocusArea.INTERVENTION_PLAN)

        if len(seed_text.strip()) > 80 or any(
            keyword in text for keyword in ("观察", "数据", "证据", "反思", "记录", "评估")
        ):
            stages.append(FocusArea.DATA_COLLECTION_AND_REFLECTION)

        deduplicated: list[FocusArea] = []
        for focus in stages:
            if focus not in deduplicated:
                deduplicated.append(focus)

        return [
            {
                "focus": focus,
                "label": self.prioritization_service.focus_label(focus),
                "reason": self.prioritization_service.focus_reason(focus),
            }
            for focus in deduplicated[:5]
        ]

    def _next_stage(self, current_stage: ResearchCycleStage) -> ResearchCycleStage:
        if current_stage == ResearchCycleStage.PLANNING:
            return ResearchCycleStage.ACTION
        if current_stage == ResearchCycleStage.ACTION:
            return ResearchCycleStage.OBSERVATION
        if current_stage == ResearchCycleStage.OBSERVATION:
            return ResearchCycleStage.REFLECTION
        return ResearchCycleStage.PLANNING

    def _stage_label(self, stage: ResearchCycleStage) -> str:
        labels = {
            ResearchCycleStage.PLANNING: "计划",
            ResearchCycleStage.ACTION: "行动",
            ResearchCycleStage.OBSERVATION: "观察",
            ResearchCycleStage.REFLECTION: "反思",
        }
        return labels[stage]

    def _normalize_stage_plan(
        self,
        raw_plan: Any,
        fallback: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not isinstance(raw_plan, list):
            return fallback

        normalized_plan: list[dict[str, Any]] = []
        for raw_stage in raw_plan:
            if not isinstance(raw_stage, dict):
                continue
            focus = self._normalize_focus(raw_stage.get("focus"), fallback=None)
            if focus is None:
                continue
            normalized_plan.append(
                {
                    "focus": focus,
                    "label": self._normalize_text(
                        raw_stage.get("label"),
                        fallback=self.prioritization_service.focus_label(focus),
                    ),
                    "reason": self._normalize_text(
                        raw_stage.get("reason"),
                        fallback=self.prioritization_service.focus_reason(focus),
                    ),
                }
            )
        return normalized_plan or fallback

    def _normalize_focus(
        self,
        raw_focus: Any,
        fallback: FocusArea | None,
    ) -> FocusArea | None:
        if isinstance(raw_focus, str):
            normalized = raw_focus.strip().lower()
            for focus_area in FocusArea:
                if focus_area.value == normalized:
                    return focus_area
        return fallback

    def _normalize_questions(
        self,
        raw_questions: Any,
        fallback: list[str],
    ) -> list[str]:
        if isinstance(raw_questions, list):
            cleaned = [str(item).strip() for item in raw_questions if str(item).strip()]
            if len(cleaned) >= 2:
                return cleaned[:2]
        return fallback

    def _normalize_text(self, raw_text: Any, fallback: str) -> str:
        if isinstance(raw_text, str) and raw_text.strip():
            return raw_text.strip()
        return fallback
