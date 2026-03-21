from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any
from uuid import uuid4

from backend.application.services.document_service import StageDocumentService
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
    awaiting_document_review: bool
    active_stage_number: int | None
    completed_stage_count: int
    current_document: dict[str, Any] | None = None
    stage_documents: list[dict[str, Any]] = field(default_factory=list)
    final_summary: str | None = None


class DialogueService:
    def __init__(self) -> None:
        settings = get_settings()
        self.prioritization_service = PrioritizationService()
        self.document_service = StageDocumentService()
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
        opening_plan = self._generate_opening_plan(project_title, initial_idea)
        stage_plan = self._normalize_stage_plan(
            opening_plan.get("stage_plan"),
            fallback=self._derive_stage_plan(initial_idea),
        )
        first_stage = stage_plan[0]
        first_focus = first_stage["focus"]
        return ResearchSession(
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
                "stage_plan": stage_plan,
                "current_stage_index": 0,
                "total_rounds": len(stage_plan),
                "plan_confirmed": False,
                "current_focus_reason": first_stage["reason"],
                "awaiting_document_review": False,
                "pending_next_stage_index": None,
                "pending_next_questions": [],
                "stage_documents": {},
                "is_complete": False,
            },
        )

    def build_opening_message(self, session: ResearchSession) -> str:
        stage_lines = [
            f"{index}. {stage['label']}：{stage['reason']}"
            for index, stage in enumerate(session.state_snapshot.get("stage_plan", []), start=1)
        ]
        return (
            f"{session.state_snapshot.get('opening_acknowledgement')}\n"
            f"{session.state_snapshot.get('plan_overview')}\n"
            f"建议按 {session.state_snapshot.get('total_rounds', 1)} 个阶段推进：\n"
            f"{chr(10).join(stage_lines)}\n"
            f"当前先从【{self.prioritization_service.focus_label(session.current_focus)}】开始。\n"
            f"原因是：{session.state_snapshot.get('current_focus_reason')}\n"
            f"初步建议：{session.state_snapshot.get('opening_guidance')}\n"
            "如果安排合理，我们就开始；如果不合适，你可以让我调整。"
        )

    def confirm_stage_plan(self, session: ResearchSession) -> str:
        session.state_snapshot["plan_confirmed"] = True
        return (
            f"我们就按这个节奏推进。当前还有 {self.remaining_rounds(session)} 个阶段，"
            f"先从【{self.prioritization_service.focus_label(session.current_focus)}】开始。"
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
        session.state_snapshot.update(
            {
                "stage_plan": stage_plan,
                "current_stage_index": 0,
                "total_rounds": len(stage_plan),
                "plan_confirmed": True,
                "current_focus_reason": first_stage["reason"],
                "plan_overview": self._normalize_text(
                    revised_plan.get("plan_overview"),
                    fallback="我已经根据你的反馈重新调整了阶段顺序。",
                ),
                "opening_guidance": self._normalize_text(
                    revised_plan.get("initial_guidance"),
                    fallback=self.prioritization_service.focus_guidance(first_focus),
                ),
                "conversation_history": [],
                "awaiting_document_review": False,
                "pending_next_stage_index": None,
                "pending_next_questions": [],
                "stage_documents": {},
                "is_complete": False,
            }
        )
        session.current_focus = first_focus
        session.guiding_questions = self._normalize_questions(
            revised_plan.get("questions"),
            fallback=self.prioritization_service.default_questions(first_focus),
        )
        return f"我已经按你的意见调整了阶段安排。\n{self.build_opening_message(session)}"

    def get_current_questions(self, session: ResearchSession) -> list[str]:
        if session.state_snapshot.get("awaiting_document_review") or session.state_snapshot.get("is_complete"):
            return []
        return session.guiding_questions

    def get_current_round_label(self, session: ResearchSession) -> str:
        total_rounds = session.state_snapshot.get("total_rounds", 1)
        if session.state_snapshot.get("is_complete"):
            return "已完成所有阶段"
        if session.state_snapshot.get("awaiting_document_review"):
            return f"第 {self.completed_stage_count(session)}/{total_rounds} 阶段已完成，等待文档确认"
        current_index = session.state_snapshot.get("current_stage_index", 0) + 1
        return f"第 {current_index}/{total_rounds} 阶段：{self.prioritization_service.focus_label(session.current_focus)}"

    def remaining_rounds(self, session: ResearchSession) -> int:
        return max(session.state_snapshot.get("total_rounds", 1) - self.completed_stage_count(session), 0)

    def completed_stage_count(self, session: ResearchSession) -> int:
        return len(session.state_snapshot.get("conversation_history", []))

    def active_stage_number(self, session: ResearchSession) -> int | None:
        if session.state_snapshot.get("awaiting_document_review") or session.state_snapshot.get("is_complete"):
            return None
        return session.state_snapshot.get("current_stage_index", 0) + 1

    def list_stage_documents(self, session: ResearchSession) -> list[dict[str, Any]]:
        documents = session.state_snapshot.get("stage_documents", {})
        return [documents[key] for key in sorted(documents.keys(), key=int)]

    def get_latest_document(self, session: ResearchSession) -> dict[str, Any] | None:
        documents = self.list_stage_documents(session)
        return documents[-1] if documents else None

    def upload_stage_document(
        self,
        session: ResearchSession,
        stage_index: int,
        file_bytes: bytes,
    ) -> dict[str, Any]:
        metadata = session.state_snapshot.get("stage_documents", {}).get(str(stage_index))
        if metadata is None:
            raise ValueError("当前阶段文档不存在，无法上传修订版。")
        updated = self.document_service.save_uploaded_revision(
            session_id=session.session_id,
            stage_index=stage_index,
            stage_label=metadata["stage_label"],
            file_bytes=file_bytes,
        )
        return self._apply_document_revision(session, stage_index, metadata, updated)

    def edit_stage_document(
        self,
        session: ResearchSession,
        stage_index: int,
        content: str,
    ) -> dict[str, Any]:
        metadata = session.state_snapshot.get("stage_documents", {}).get(str(stage_index))
        if metadata is None:
            raise ValueError("当前阶段文档不存在，无法在线修改。")
        if not content.strip():
            raise ValueError("文档内容不能为空。")

        updated = self.document_service.save_text_revision(
            session_id=session.session_id,
            stage_index=stage_index,
            stage_label=metadata["stage_label"],
            content=content,
        )
        return self._apply_document_revision(session, stage_index, metadata, updated)

    def continue_to_next_stage(self, session: ResearchSession) -> dict[str, Any]:
        if not session.state_snapshot.get("awaiting_document_review"):
            raise ValueError("当前没有等待确认的阶段文档。")
        next_stage_index = session.state_snapshot.get("pending_next_stage_index")
        if next_stage_index is None:
            raise ValueError("缺少下一阶段信息，无法继续。")

        latest_document = self.get_latest_document(session)
        revision_note = ""
        if latest_document and latest_document.get("is_modified"):
            revision_note = (
                f"我注意到你对上一阶段【{latest_document['stage_label']}】的文档做了修改："
                f"{latest_document.get('modification_summary', '')}"
            )

        next_stage = session.state_snapshot["stage_plan"][next_stage_index]
        next_focus = next_stage["focus"]
        pending_questions = self._normalize_questions(
            session.state_snapshot.get("pending_next_questions"),
            fallback=self.prioritization_service.default_questions(next_focus),
        )
        session.state_snapshot.update(
            {
                "current_stage_index": next_stage_index,
                "awaiting_document_review": False,
                "pending_next_stage_index": None,
                "pending_next_questions": [],
                "current_focus_reason": next_stage["reason"],
            }
        )
        session.current_focus = next_focus
        session.guiding_questions = pending_questions
        message_parts = []
        if revision_note:
            message_parts.append(revision_note)
        message_parts.append(
            f"现在我们进入第 {next_stage_index + 1}/{session.state_snapshot.get('total_rounds', 1)} 阶段【{next_stage['label']}】。"
        )
        message_parts.append(f"这一阶段关注的是：{next_stage['reason']}")
        return {"message": "\n".join(message_parts), "current_questions": pending_questions}

    def _apply_document_revision(
        self,
        session: ResearchSession,
        stage_index: int,
        metadata: dict[str, Any],
        updated: dict[str, Any],
    ) -> dict[str, Any]:
        original_text = metadata.get("generated_text", "")
        revised_text = updated["latest_text"]
        metadata.update(updated)
        metadata["is_modified"] = self._documents_are_different(original_text, revised_text)
        metadata["modification_summary"] = (
            self._summarize_document_revision(metadata["stage_label"], original_text, revised_text)
            if metadata["is_modified"]
            else None
        )
        session.state_snapshot["stage_documents"][str(stage_index)] = metadata
        return metadata

    def advance_session(
        self,
        session: ResearchSession,
        answers: list[str],
        latest_input: str | None = None,
    ) -> DialogueReply:
        if session.state_snapshot.get("awaiting_document_review"):
            raise ValueError("请先确认右侧文档，再进入下一阶段。")

        current_focus = session.current_focus
        current_stage_index = session.state_snapshot.get("current_stage_index", 0)
        total_rounds = session.state_snapshot.get("total_rounds", 1)
        current_stage = session.state_snapshot["stage_plan"][current_stage_index]
        stage_number = current_stage_index + 1
        stage_key = self.prioritization_service.state_key_for_focus(current_focus)

        reply_payload = self._generate_round_reply(session, answers, latest_input)
        round_summary = self._normalize_text(
            reply_payload.get("current_focus_summary"),
            fallback=self._build_round_summary(session, current_focus, answers, latest_input),
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
            fallback=self._build_draft(session, current_focus, round_summary),
        )

        session.state_snapshot[stage_key] = round_summary
        session.state_snapshot["conversation_history"].append(
            {
                "round_index": stage_number,
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
        session.latest_draft = draft
        session.cycle_stage = self._next_stage(session.cycle_stage)

        document_metadata = self.document_service.build_stage_document(
            session_id=session.session_id,
            project_title=session.project_title,
            stage_index=stage_number,
            stage_label=current_stage["label"],
            answers=answers,
            latest_input=latest_input,
            summary=round_summary,
            feedback=stage_feedback,
            guidance=guidance,
            draft=draft,
        )
        session.state_snapshot["stage_documents"][str(stage_number)] = document_metadata

        if stage_number >= total_rounds:
            session.state_snapshot.update(
                {
                    "is_complete": True,
                    "awaiting_document_review": False,
                    "pending_next_stage_index": None,
                    "pending_next_questions": [],
                    "current_stage_index": total_rounds,
                }
            )
            return DialogueReply(
                message=self._normalize_text(
                    reply_payload.get("coach_message"),
                    fallback="最后一个阶段已经完成，我也把整个项目的阶段成果整理好了。",
                ),
                stage_feedback=stage_feedback,
                guidance=guidance,
                draft=draft,
                next_questions=[],
                remaining_rounds=0,
                is_complete=True,
                final_summary=self._normalize_text(
                    reply_payload.get("final_summary"),
                    fallback=self._build_final_summary(session),
                ),
                awaiting_document_review=False,
                active_stage_number=None,
                completed_stage_count=self.completed_stage_count(session),
                current_document=document_metadata,
                stage_documents=self.list_stage_documents(session),
            )

        next_stage = session.state_snapshot["stage_plan"][stage_number]
        session.state_snapshot.update(
            {
                "awaiting_document_review": True,
                "pending_next_stage_index": stage_number,
                "pending_next_questions": self._normalize_questions(
                    reply_payload.get("next_questions"),
                    fallback=self.prioritization_service.default_questions(next_stage["focus"]),
                ),
            }
        )
        return DialogueReply(
            message=self._normalize_text(
                reply_payload.get("coach_message"),
                fallback=(
                    f"第 {stage_number} 阶段【{current_stage['label']}】已经整理完成。"
                    "我已经把本阶段内容整理成 docx 放到右侧了。"
                    "你可以先下载修改，也可以不修改，确认后再进入下一阶段。"
                ),
            ),
            stage_feedback=stage_feedback,
            guidance=guidance,
            draft=draft,
            next_questions=[],
            remaining_rounds=max(total_rounds - stage_number, 0),
            is_complete=False,
            awaiting_document_review=True,
            active_stage_number=None,
            completed_stage_count=self.completed_stage_count(session),
            current_document=document_metadata,
            stage_documents=self.list_stage_documents(session),
        )

    def llm_status_text(self) -> str:
        if self.deepseek_client is None:
            return "当前未配置 DeepSeek API，系统正在使用本地规则生成阶段内容。"
        return "当前已启用 DeepSeek API，阶段规划、反馈和文稿将由模型辅助生成。"

    def _generate_opening_plan(self, project_title: str, initial_idea: str) -> dict[str, Any]:
        if self.deepseek_client is None:
            return self._opening_plan_fallback(initial_idea)
        system_prompt = """
You are an action-research facilitator.
Split the teacher idea into 2-5 stages and return valid JSON only.
Each stage focus must be one of:
mind_map, summary, practice_problem, literature_evidence, research_problem,
expected_outcome, intervention_plan, data_collection_and_reflection.
"""
        user_prompt = f"Project title: {project_title}\nTeacher idea: {initial_idea}"
        try:
            return self.deepseek_client.generate_json(system_prompt, user_prompt)
        except Exception:
            return self._opening_plan_fallback(initial_idea)

    def _opening_plan_fallback(self, initial_idea: str) -> dict[str, Any]:
        stage_plan = self._derive_stage_plan(initial_idea)
        first_focus = stage_plan[0]["focus"]
        return {
            "acknowledgement": f"我先理解一下你的想法：{initial_idea}",
            "plan_overview": "我先按信息完整度和行动研究推进顺序，把它拆成几个阶段。",
            "stage_plan": [
                {"focus": stage["focus"].value, "label": stage["label"], "reason": stage["reason"]}
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
            return self._revised_plan_fallback(session, adjustment_text)
        system_prompt = "Revise the stage plan in Chinese and return valid JSON only."
        user_prompt = (
            f"Project title: {session.project_title}\n"
            f"Teacher initial idea: {session.state_snapshot.get('initial_idea', '')}\n"
            f"Original stage plan: {session.state_snapshot.get('stage_plan', [])}\n"
            f"Teacher feedback: {adjustment_text}"
        )
        try:
            return self.deepseek_client.generate_json(system_prompt, user_prompt)
        except Exception:
            return self._revised_plan_fallback(session, adjustment_text)

    def _revised_plan_fallback(
        self,
        session: ResearchSession,
        adjustment_text: str,
    ) -> dict[str, Any]:
        stage_plan = self._derive_stage_plan(
            f"{session.state_snapshot.get('initial_idea', '')}\n{adjustment_text}"
        )
        first_focus = stage_plan[0]["focus"]
        return {
            "plan_overview": "我已经根据你的反馈重新调整了推进顺序。",
            "stage_plan": [
                {"focus": stage["focus"].value, "label": stage["label"], "reason": stage["reason"]}
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
        is_last_stage = current_stage_index + 1 >= session.state_snapshot.get("total_rounds", 1)
        fallback_summary = self._build_round_summary(session, current_focus, answers, latest_input)
        fallback_feedback = self._build_stage_feedback(current_focus, answers, latest_input)
        fallback_guidance = self._build_guidance(current_focus, answers, latest_input)
        fallback_draft = self._build_draft(session, current_focus, fallback_summary)
        fallback_next_questions = []
        if not is_last_stage:
            next_stage = session.state_snapshot["stage_plan"][current_stage_index + 1]
            fallback_next_questions = self.prioritization_service.default_questions(next_stage["focus"])
        if self.deepseek_client is None:
            payload = {
                "current_focus_summary": fallback_summary,
                "stage_feedback": fallback_feedback,
                "guidance": fallback_guidance,
                "draft": fallback_draft,
                "coach_message": (
                    "这一阶段我已经整理成文档了，右侧可以下载和上传修订版。"
                    if not is_last_stage
                    else "最后一个阶段已经完成，我这边也整理好了最终总结。"
                ),
                "next_questions": fallback_next_questions,
            }
            if is_last_stage:
                payload["final_summary"] = self._build_final_summary(session)
            return payload
        system_prompt = "Continue the staged dialogue in Chinese and return valid JSON only."
        user_prompt = (
            f"Project title: {session.project_title}\n"
            f"Initial idea: {session.state_snapshot.get('initial_idea', '')}\n"
            f"Stage plan: {session.state_snapshot.get('stage_plan', [])}\n"
            f"Current stage: {current_stage_index + 1}\n"
            f"Teacher answers: {answers}\n"
            f"Teacher extra input: {latest_input or ''}\n"
            f"History: {session.state_snapshot.get('conversation_history', [])}"
        )
        try:
            return self.deepseek_client.generate_json(system_prompt, user_prompt)
        except Exception:
            return self._generate_round_reply_fallback(is_last_stage, fallback_summary, fallback_feedback, fallback_guidance, fallback_draft, fallback_next_questions, session)

    def _generate_round_reply_fallback(
        self,
        is_last_stage: bool,
        fallback_summary: str,
        fallback_feedback: str,
        fallback_guidance: str,
        fallback_draft: str,
        fallback_next_questions: list[str],
        session: ResearchSession,
    ) -> dict[str, Any]:
        payload = {
            "current_focus_summary": fallback_summary,
            "stage_feedback": fallback_feedback,
            "guidance": fallback_guidance,
            "draft": fallback_draft,
            "coach_message": (
                "这一阶段我已经整理成文档了，右侧可以下载和上传修订版。"
                if not is_last_stage
                else "最后一个阶段已经完成，我这边也整理好了最终总结。"
            ),
            "next_questions": fallback_next_questions,
        }
        if is_last_stage:
            payload["final_summary"] = self._build_final_summary(session)
        return payload

    def _build_round_summary(self, session: ResearchSession, focus_area: FocusArea, answers: list[str], latest_input: str | None) -> str:
        answer_one = answers[0] if len(answers) > 0 and answers[0].strip() else "暂无回答"
        answer_two = answers[1] if len(answers) > 1 and answers[1].strip() else "暂无回答"
        supplement = latest_input.strip() if latest_input and latest_input.strip() else "暂无补充"
        focus_label = self.prioritization_service.focus_label(focus_area)
        return f"围绕“{session.state_snapshot.get('initial_idea', '')}”的{focus_label}阶段，本轮形成的要点是：{answer_one}；{answer_two}；补充信息为{supplement}。"

    def _build_stage_feedback(self, focus_area: FocusArea, answers: list[str], latest_input: str | None) -> str:
        focus_label = self.prioritization_service.focus_label(focus_area)
        if not any(item.strip() for item in answers) and not (latest_input and latest_input.strip()):
            return f"这一轮关于【{focus_label}】的信息还比较少，不过方向已经出现了，后面我们可以边补充边收束。"
        return f"你这一轮对【{focus_label}】已经给出了比较清楚的线索，我已经帮你收束成一版可修改文稿。"

    def _build_guidance(self, focus_area: FocusArea, answers: list[str], latest_input: str | None) -> str:
        base_guidance = self.prioritization_service.focus_guidance(focus_area)
        details = [item.strip() for item in [answers[0] if len(answers) > 0 else "", answers[1] if len(answers) > 1 else "", latest_input or ""] if item and item.strip()]
        if not details:
            return base_guidance
        return f"{base_guidance} 你还可以继续细化这些要点：{'；'.join(details[:3])}。"

    def _build_draft(self, session: ResearchSession, focus_area: FocusArea, round_summary: str) -> str:
        return (
            f"【当前循环阶段：{self._stage_label(session.cycle_stage)}】\n"
            f"【当前聚焦主题：{self.prioritization_service.focus_label(focus_area)}】\n"
            f"{round_summary}\n"
            "这是一个便于继续修改的阶段草稿。"
        )

    def _build_final_summary(self, session: ResearchSession) -> str:
        lines = [f"项目：{session.project_title}", f"初始想法：{session.state_snapshot.get('initial_idea', '')}", "本次对话形成的阶段结论如下："]
        for item in session.state_snapshot.get("conversation_history", []):
            lines.append(f"- 第 {item['round_index']} 阶段【{item['focus_label']}】：{item['summary']}")
        lines.append("每个阶段的 docx 文档也已经整理完成，可在右侧继续下载查看。")
        return "\n".join(lines)

    def _derive_stage_plan(self, seed_text: str) -> list[dict[str, Any]]:
        text = seed_text.lower()
        stages: list[FocusArea] = [FocusArea.RESEARCH_PROBLEM]
        if any(keyword in text for keyword in ("文献", "理论", "literature", "研究依据")):
            stages.append(FocusArea.LITERATURE_EVIDENCE)
        if any(keyword in text for keyword in ("目标", "预期", "希望达到", "效果", "结果")):
            stages.append(FocusArea.EXPECTED_OUTCOME)
        stages.append(FocusArea.INTERVENTION_PLAN)
        if len(seed_text.strip()) > 80 or any(keyword in text for keyword in ("观察", "数据", "证据", "反思", "记录", "评估")):
            stages.append(FocusArea.DATA_COLLECTION_AND_REFLECTION)
        deduplicated: list[FocusArea] = []
        for focus in stages:
            if focus not in deduplicated:
                deduplicated.append(focus)
        return [{"focus": focus, "label": self.prioritization_service.focus_label(focus), "reason": self.prioritization_service.focus_reason(focus)} for focus in deduplicated[:5]]

    def _summarize_document_revision(self, stage_label: str, original_text: str, revised_text: str) -> str:
        if not self._documents_are_different(original_text, revised_text):
            return ""
        if self.deepseek_client is not None:
            try:
                summary = self.deepseek_client.generate(
                    "Summarize differences between two Chinese documents in one sentence.",
                    f"Stage: {stage_label}\nOriginal:\n{original_text}\n\nRevised:\n{revised_text}",
                ).strip()
                if summary:
                    return summary
            except Exception:
                pass
        original_lines = self._meaningful_lines(original_text)
        revised_lines = self._meaningful_lines(revised_text)
        added = [line for line in revised_lines if line not in set(original_lines)]
        removed = [line for line in original_lines if line not in set(revised_lines)]
        parts = []
        if added:
            parts.append(f"补充了“{self._clip_text(added[0])}”等内容")
        if removed:
            parts.append(f"删减或改写了“{self._clip_text(removed[0])}”等表述")
        if not parts:
            if SequenceMatcher(None, original_text, revised_text).ratio() < 0.7:
                parts.append("整体重写了文档结构和表达")
            elif len(revised_text) >= len(original_text):
                parts.append("在原稿基础上做了细化补充")
            else:
                parts.append("对原稿做了压缩和措辞调整")
        return "；".join(parts) + "。"

    def _documents_are_different(self, original_text: str, revised_text: str) -> bool:
        return "".join(original_text.split()) != "".join(revised_text.split())

    def _meaningful_lines(self, text: str) -> list[str]:
        return [line.strip() for line in text.splitlines() if line.strip()]

    def _clip_text(self, text: str, limit: int = 24) -> str:
        return text if len(text) <= limit else f"{text[:limit]}..."

    def _next_stage(self, current_stage: ResearchCycleStage) -> ResearchCycleStage:
        if current_stage == ResearchCycleStage.PLANNING:
            return ResearchCycleStage.ACTION
        if current_stage == ResearchCycleStage.ACTION:
            return ResearchCycleStage.OBSERVATION
        if current_stage == ResearchCycleStage.OBSERVATION:
            return ResearchCycleStage.REFLECTION
        return ResearchCycleStage.PLANNING

    def _stage_label(self, stage: ResearchCycleStage) -> str:
        return {
            ResearchCycleStage.PLANNING: "计划",
            ResearchCycleStage.ACTION: "行动",
            ResearchCycleStage.OBSERVATION: "观察",
            ResearchCycleStage.REFLECTION: "反思",
        }[stage]

    def _normalize_stage_plan(self, raw_plan: Any, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
                    "label": self._normalize_text(raw_stage.get("label"), self.prioritization_service.focus_label(focus)),
                    "reason": self._normalize_text(raw_stage.get("reason"), self.prioritization_service.focus_reason(focus)),
                }
            )
        return normalized_plan or fallback

    def _normalize_focus(self, raw_focus: Any, fallback: FocusArea | None) -> FocusArea | None:
        if isinstance(raw_focus, str):
            normalized = raw_focus.strip().lower()
            for focus_area in FocusArea:
                if focus_area.value == normalized:
                    return focus_area
        return fallback

    def _normalize_questions(self, raw_questions: Any, fallback: list[str]) -> list[str]:
        if isinstance(raw_questions, list):
            cleaned = [str(item).strip() for item in raw_questions if str(item).strip()]
            if len(cleaned) >= 2:
                return cleaned[:2]
        return fallback

    def _normalize_text(self, raw_text: Any, fallback: str) -> str:
        if isinstance(raw_text, str) and raw_text.strip():
            return raw_text.strip()
        return fallback
