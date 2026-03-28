from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from textwrap import dedent
from typing import Any
from uuid import uuid4

from backend.application.services.document_service import StageDocumentService
from backend.core.config import PROJECT_ROOT, get_settings
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
        self.facilitator_prompt = self._load_prompt_file(
            "system/facilitator.md",
            fallback=(
                "You are a focused action-research facilitator. "
                "Advance one focus area at a time, ask at most two targeted questions, "
                "ground every reply in the teacher input, and avoid repetition."
            ),
        )
        self.prioritization_prompt = self._load_prompt_file(
            "workflows/prioritization.md",
            fallback="Advance the weakest research component with at most two targeted questions.",
        )
        self.draft_generation_prompt = self._load_prompt_file(
            "workflows/draft_generation.md",
            fallback="Produce a specific, practical, revision-friendly stage draft.",
        )
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
                    fallback=f"That is a useful starting point. I am hearing: {initial_idea}",
                ),
                "plan_overview": self._normalize_text(
                    opening_plan.get("plan_overview"),
                    fallback="I mapped the work into a few internal stages so we can move one step at a time.",
                ),
                "opening_guidance": self._normalize_text(
                    opening_plan.get("initial_guidance"),
                    fallback=self.prioritization_service.focus_guidance(first_focus),
                ),
                "stage_plan": stage_plan,
                "current_stage_index": 0,
                "total_rounds": len(stage_plan),
                "plan_confirmed": True,
                "current_focus_reason": first_stage["reason"],
                "awaiting_document_review": False,
                "pending_next_stage_index": None,
                "pending_next_questions": [],
                "stage_documents": {},
                "is_complete": False,
            },
        )
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
                    fallback=f"好，我先接住你的这个想法：{initial_idea}",
                ),
                "plan_overview": self._normalize_text(
                    opening_plan.get("plan_overview"),
                    fallback="我先把它拆成几个小阶段，这样我们会更好往下聊。",
                ),
                "opening_guidance": self._normalize_text(
                    opening_plan.get("initial_guidance"),
                    fallback=self.prioritization_service.focus_guidance(first_focus),
                ),
                "stage_plan": stage_plan,
                "current_stage_index": 0,
                "total_rounds": len(stage_plan),
                "plan_confirmed": True,
                "current_focus_reason": first_stage["reason"],
                "awaiting_document_review": False,
                "pending_next_stage_index": None,
                "pending_next_questions": [],
                "stage_documents": {},
                "is_complete": False,
            },
        )

    def build_opening_message(self, session: ResearchSession) -> str:
        stage_plan = session.state_snapshot.get("stage_plan", [])
        first_stage = stage_plan[0] if stage_plan else {"label": "Stage 1"}
        sections = [
            session.state_snapshot.get("opening_acknowledgement", "").strip()
            or "That gives us something workable to build on.",
            f"We'll start with Stage 1: {first_stage['label']}.",
        ]
        guidance = session.state_snapshot.get("opening_guidance", "").strip()
        if guidance:
            sections.append(guidance)
        return "\n".join(sections)
        stage_lines = [
            f"{index}. {stage['label']}：{stage['reason']}"
            for index, stage in enumerate(session.state_snapshot.get("stage_plan", []), start=1)
        ]
        return (
            f"好，我先把这个想法拆成 {session.state_snapshot.get('total_rounds', 1)} 个阶段：\n"
            f"{chr(10).join(stage_lines)}\n"
            f"我们先聊 Stage 1【{self.prioritization_service.focus_label(session.current_focus)}】。"
        )

    def confirm_stage_plan(self, session: ResearchSession) -> str:
        session.state_snapshot["plan_confirmed"] = True
        return "All right. We can keep moving one stage at a time."
        session.state_snapshot["plan_confirmed"] = True
        return (
            f"好，那我们就继续往下走。"
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
                    fallback="I adjusted the internal stage order based on your note.",
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
        return f"I tightened the flow a bit.\n{self.build_opening_message(session)}"
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
                    fallback="好，我按你的意思把阶段顺序重新排了一下。",
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
        return f"好，我重新整理了一下。\n{self.build_opening_message(session)}"

    def get_current_questions(self, session: ResearchSession) -> list[str]:
        if session.state_snapshot.get("awaiting_document_review") or session.state_snapshot.get("is_complete"):
            return []
        return session.guiding_questions

    def get_current_round_label(self, session: ResearchSession) -> str:
        total_rounds = session.state_snapshot.get("total_rounds", 1)
        if session.state_snapshot.get("is_complete"):
            return "All stages complete"
        if session.state_snapshot.get("awaiting_document_review"):
            return f"Stage {self.completed_stage_count(session)} complete, waiting for confirmation"
        current_index = session.state_snapshot.get("current_stage_index", 0) + 1
        return f"Stage {current_index}/{total_rounds}: {self.prioritization_service.focus_label(session.current_focus)}"
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
            raise ValueError("There is no completed stage waiting for confirmation.")
        next_stage_index = session.state_snapshot.get("pending_next_stage_index")
        if next_stage_index is None:
            raise ValueError("The next stage is not ready yet.")

        latest_document = self.get_latest_document(session)
        revision_note = ""
        if latest_document and latest_document.get("is_modified"):
            revision_summary = latest_document.get("modification_summary") or "You revised the stage draft."
            revision_note = f"I also picked up your edits to {latest_document['stage_label']}: {revision_summary}"

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
        message_parts: list[str] = []
        if revision_note:
            message_parts.append(revision_note)
        message_parts.append(f"All right. Let's move into Stage {next_stage_index + 1}: {next_stage['label']}.")
        message_parts.append(next_stage["reason"])
        return {"message": "\n".join(message_parts), "current_questions": pending_questions}
        if not session.state_snapshot.get("awaiting_document_review"):
            raise ValueError("当前没有等待确认的阶段文档。")
        next_stage_index = session.state_snapshot.get("pending_next_stage_index")
        if next_stage_index is None:
            raise ValueError("缺少下一阶段信息，无法继续。")

        latest_document = self.get_latest_document(session)
        revision_note = ""
        if latest_document and latest_document.get("is_modified"):
            revision_note = (
                f"我看到你把上一阶段【{latest_document['stage_label']}】又补了一下："
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
            f"好，那我们接着聊 Stage {next_stage_index + 1}【{next_stage['label']}】。"
        )
        message_parts.append(f"这一段我们主要想聊清楚：{next_stage['reason']}")
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
            raise ValueError("Please confirm the draft on the right before moving to the next stage.")

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

        previous_document = self.get_latest_document(session)
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
            previous_text=previous_document["latest_text"] if previous_document else None,
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
                    fallback="Everything is now in place. I wrapped the final version up on the right.",
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
                    f"Stage {stage_number} is in good shape. "
                    "I put the draft on the right. "
                    "Click Confirm when you want the next stage."
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
                    fallback="好，这个项目我们先收住了，我也顺手帮你整理好了。",
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
                    f"好，Stage {stage_number} 我先帮你收住了。"
                    "右边文档已经同步好。"
                    "你想继续的话，点 Confirm 就行。"
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
            return "Using local fallback logic"
        return "Using DeepSeek assistance"
        if self.deepseek_client is None:
            return "当前用的是本地规则。"
        return "当前由 DeepSeek 辅助生成。"

    def _generate_opening_plan(self, project_title: str, initial_idea: str) -> dict[str, Any]:
        if self.deepseek_client is None:
            return self._opening_plan_fallback(initial_idea)
        system_prompt = self._build_opening_plan_system_prompt()
        user_prompt = self._build_opening_plan_user_prompt(project_title, initial_idea)
        try:
            return self.deepseek_client.generate_json(system_prompt, user_prompt)
        except Exception:
            return self._opening_plan_fallback(initial_idea)

    def _opening_plan_fallback(self, initial_idea: str) -> dict[str, Any]:
        stage_plan = self._derive_stage_plan(initial_idea)
        first_focus = stage_plan[0]["focus"]
        return {
            "acknowledgement": f"That sounds promising. At the core, you want to explore: {initial_idea}",
            "plan_overview": "I mapped the work into a few internal stages so we can move one step at a time.",
            "stage_plan": [
                {"focus": stage["focus"].value, "label": stage["label"], "reason": stage["reason"]}
                for stage in stage_plan
            ],
            "initial_guidance": self.prioritization_service.focus_guidance(first_focus),
            "questions": self.prioritization_service.default_questions(first_focus),
        }
        stage_plan = self._derive_stage_plan(initial_idea)
        first_focus = stage_plan[0]["focus"]
        return {
            "acknowledgement": f"好，我先接住你的这个想法：{initial_idea}",
            "plan_overview": "我先把它拆成几个小阶段，这样更容易往下聊。",
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
        system_prompt = self._build_revised_plan_system_prompt()
        user_prompt = self._build_revised_plan_user_prompt(session, adjustment_text)
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
            "plan_overview": "I reorganized the internal stage order around your new note.",
            "stage_plan": [
                {"focus": stage["focus"].value, "label": stage["label"], "reason": stage["reason"]}
                for stage in stage_plan
            ],
            "initial_guidance": self.prioritization_service.focus_guidance(first_focus),
            "questions": self.prioritization_service.default_questions(first_focus),
        }
        stage_plan = self._derive_stage_plan(
            f"{session.state_snapshot.get('initial_idea', '')}\n{adjustment_text}"
        )
        first_focus = stage_plan[0]["focus"]
        return {
            "plan_overview": "好，我按你的意思重新排了一下顺序。",
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
        fallback_next_questions: list[str] = []
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
                    "I put this stage draft on the right. Click Confirm if you want the next stage."
                    if not is_last_stage
                    else "I also wrapped the overall result up for you."
                ),
                "next_questions": fallback_next_questions,
            }
            if is_last_stage:
                payload["final_summary"] = self._build_final_summary(session)
            return payload
        system_prompt = self._build_round_reply_system_prompt(is_last_stage)
        user_prompt = self._build_round_reply_user_prompt(
            session=session,
            answers=answers,
            latest_input=latest_input,
            is_last_stage=is_last_stage,
        )
        try:
            return self.deepseek_client.generate_json(system_prompt, user_prompt)
        except Exception:
            return self._generate_round_reply_fallback(
                is_last_stage,
                fallback_summary,
                fallback_feedback,
                fallback_guidance,
                fallback_draft,
                fallback_next_questions,
                session,
            )
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
                    "好，这一段我先帮你收好了，右边文档已经同步。"
                    if not is_last_stage
                    else "好，最后一段也收好了，我顺手把总结一起整理了。"
                ),
                "next_questions": fallback_next_questions,
            }
            if is_last_stage:
                payload["final_summary"] = self._build_final_summary(session)
            return payload
        system_prompt = self._build_round_reply_system_prompt(is_last_stage)
        user_prompt = self._build_round_reply_user_prompt(
            session=session,
            answers=answers,
            latest_input=latest_input,
            is_last_stage=is_last_stage,
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
                "I put this stage draft on the right. Click Confirm if you want the next stage."
                if not is_last_stage
                else "I also wrapped the overall result up for you."
            ),
            "next_questions": fallback_next_questions,
        }
        if is_last_stage:
            payload["final_summary"] = self._build_final_summary(session)
        return payload
        payload = {
            "current_focus_summary": fallback_summary,
            "stage_feedback": fallback_feedback,
            "guidance": fallback_guidance,
            "draft": fallback_draft,
            "coach_message": (
                "好，这一段我先帮你收好了，右边文档已经同步。"
                if not is_last_stage
                else "好，最后一段也收好了，我顺手把总结一起整理了。"
            ),
            "next_questions": fallback_next_questions,
        }
        if is_last_stage:
            payload["final_summary"] = self._build_final_summary(session)
        return payload

    def _build_round_summary(self, session: ResearchSession, focus_area: FocusArea, answers: list[str], latest_input: str | None) -> str:
        del session
        details = [item.strip() for item in [*answers, latest_input or ""] if item and item.strip()]
        if not details:
            return (
                f"For {self.prioritization_service.focus_label(focus_area).lower()}, "
                "we still need one concrete detail before this is sharp enough."
            )
        clipped = [self._ensure_sentence(self._clip_text(item, 180)) for item in details[:3]]
        return " ".join(clipped)
        answer_one = answers[0] if len(answers) > 0 and answers[0].strip() else "暂无回答"
        answer_two = answers[1] if len(answers) > 1 and answers[1].strip() else "暂无回答"
        supplement = latest_input.strip() if latest_input and latest_input.strip() else "暂无补充"
        focus_label = self.prioritization_service.focus_label(focus_area)
        return f"围绕{focus_label}这一段，目前先收住这几个点：{answer_one}；{answer_two}；补充是{supplement}。"

    def _build_stage_feedback(self, focus_area: FocusArea, answers: list[str], latest_input: str | None) -> str:
        if not any(item.strip() for item in answers) and not (latest_input and latest_input.strip()):
            return f"I can see the direction, but {self.prioritization_service.focus_label(focus_area).lower()} still needs one concrete detail."
        if latest_input and latest_input.strip():
            return f"This is focused enough to work with, especially with the added detail about {self._clip_text(latest_input.strip(), 60)}."
        return "This is focused enough to turn into a usable stage draft."
        focus_label = self.prioritization_service.focus_label(focus_area)
        if not any(item.strip() for item in answers) and not (latest_input and latest_input.strip()):
            return f"这一段先有方向了，不过关于【{focus_label}】还差一点更具体的信息。"
        return f"好，这一段关于【{focus_label}】已经清楚不少了，我先帮你收成一版。"

    def _build_guidance(self, focus_area: FocusArea, answers: list[str], latest_input: str | None) -> str:
        del focus_area
        details = [item.strip() for item in [*answers, latest_input or ""] if item and item.strip()]
        if not details:
            return "If you want to sharpen it, give me one concrete classroom example or one clear learner group."
        if len(details) == 1:
            return "If you want to sharpen it, add one more concrete detail about context, learners, or what you observed."
        return "If you want to sharpen it, make the setting or the evidence slightly more specific."
        base_guidance = self.prioritization_service.focus_guidance(focus_area)
        details = [item.strip() for item in [answers[0] if len(answers) > 0 else "", answers[1] if len(answers) > 1 else "", latest_input or ""] if item and item.strip()]
        if not details:
            return f"如果你还想往下补，就沿着这个方向再具体一点。"
        return f"如果你还想继续补，就把这些点再说得更具体一点：{'；'.join(details[:2])}。"

    def _build_draft(self, session: ResearchSession, focus_area: FocusArea, round_summary: str) -> str:
        del session, focus_area
        return round_summary
        return (
            f"{self.prioritization_service.focus_label(focus_area)}这一段先可以这样写："
            f"{round_summary}"
        )

    def _build_final_summary(self, session: ResearchSession) -> str:
        lines = [
            f"Project: {session.project_title}",
            f"Starting idea: {session.state_snapshot.get('initial_idea', '')}",
            "What we clarified:",
        ]
        for item in session.state_snapshot.get("conversation_history", []):
            lines.append(f"- Stage {item['round_index']} ({item['focus_label']}): {item['summary']}")
        lines.append("Each stage draft is available on the right.")
        return "\n".join(lines)
        lines = [f"项目：{session.project_title}", f"一开始的想法：{session.state_snapshot.get('initial_idea', '')}", "这次我们先聊到这里："]
        for item in session.state_snapshot.get("conversation_history", []):
            lines.append(f"- 第 {item['round_index']} 阶段【{item['focus_label']}】：{item['summary']}")
        lines.append("每一段的文档我也都放在右边了。")
        return "\n".join(lines)

    def _build_opening_plan_system_prompt(self) -> str:
        return dedent(
            f"""
            {self.facilitator_prompt}

            {self.prioritization_prompt}

            You are creating an internal stage plan for a teacher.
            Return valid JSON only. No markdown fences. Write in English.

            Hard constraints:
            - Build an internal stage plan with 2-5 stages.
            - Each stage focus must be one of:
              mind_map, summary, practice_problem, literature_evidence,
              research_problem, expected_outcome, intervention_plan,
              data_collection_and_reflection.
            - Ask exactly 2 targeted questions for Stage 1.
            - acknowledgement must be 1 short spoken sentence.
            - plan_overview must be 1 short sentence and must not enumerate every stage.
            - initial_guidance must be 1 short sentence about Stage 1 only.
            - Stage labels should be short and specific.
            - Reasons must connect directly to the teacher's idea, not generic pedagogy.
            - The tone should feel like a thoughtful teammate in normal conversation.

            Return this JSON shape:
            {{
              "acknowledgement": "...",
              "plan_overview": "...",
              "initial_guidance": "...",
              "questions": ["...", "..."],
              "stage_plan": [
                {{"focus": "research_problem", "label": "...", "reason": "..."}}
              ]
            }}
            """
        ).strip()
        return dedent(
            f"""
            {self.facilitator_prompt}

            {self.prioritization_prompt}

            You are creating the opening stage plan for a teacher.
            Return valid JSON only. No markdown fences. Write in Chinese.

            Hard constraints:
            - Split the idea into 2-5 stages only.
            - Each stage focus must be one of:
              mind_map, summary, practice_problem, literature_evidence,
              research_problem, expected_outcome, intervention_plan,
              data_collection_and_reflection.
            - acknowledgement, plan_overview, and initial_guidance must be concise and non-redundant.
            - Ask exactly 2 targeted questions for the first stage.
            - Stage labels should be short and specific.
            - Reasons must connect directly to the teacher's idea, not generic pedagogy.
            - acknowledgement must be within 1 short sentence.
            - plan_overview must be within 1 short sentence.
            - initial_guidance must be within 1 short sentence.
            - Sound like natural chat between collaborators, not a report.
            - Prefer spoken Chinese such as "好，我们先..." over formal textbook tone.

            Return this JSON shape:
            {{
              "acknowledgement": "...",
              "plan_overview": "...",
              "initial_guidance": "...",
              "questions": ["...", "..."],
              "stage_plan": [
                {{"focus": "research_problem", "label": "...", "reason": "..."}}
              ]
            }}
            """
        ).strip()

    def _build_opening_plan_user_prompt(self, project_title: str, initial_idea: str) -> str:
        title = project_title.strip() if project_title and project_title.strip() else "Untitled project"
        return dedent(
            f"""
            Project title: {title}

            Teacher's initial idea:
            {initial_idea.strip()}

            Output requirements:
            - Keep the acknowledgement short and natural.
            - Keep the plan internal. Do not write a long overview of all future stages.
            - Make Stage 1 the most useful next move.
            - Ask exactly two concrete Stage 1 questions.
            - Keep the wording concise and conversational.
            """
        ).strip()
        title = project_title.strip() if project_title and project_title.strip() else "未命名项目"
        return dedent(
            f"""
            项目标题：{title}

            教师初始想法：
            {initial_idea.strip()}

            生成要求：
            - acknowledgement：1 句话，准确复述教师最核心的研究意图。
            - plan_overview：1 句话即可。
            - initial_guidance：只针对第一阶段给出 1 句建议。
            - questions：恰好 2 个可直接回答的问题。
            - stage_plan：优先围绕真实教学问题、行动方案、证据与反思来拆分。
            - 避免“首先/其次/最后”这类模板化长句。
            - 语气像平常聊天，不要像论文指导手册。
            """
        ).strip()

    def _build_revised_plan_system_prompt(self) -> str:
        return dedent(
            f"""
            {self.facilitator_prompt}

            {self.prioritization_prompt}

            You are revising an internal stage plan for a teacher.
            Return valid JSON only. No markdown fences. Write in English.

            Hard constraints:
            - Respect the teacher's revision request first.
            - Keep the plan to 2-5 stages.
            - Preserve useful original stages when possible.
            - Ask exactly 2 targeted questions for the new Stage 1.
            - Keep every field short, direct, and conversational.

            Use the same JSON shape as the opening plan.
            """
        ).strip()
        return dedent(
            f"""
            {self.facilitator_prompt}

            {self.prioritization_prompt}

            You are revising a stage plan for a teacher.
            Return valid JSON only. No markdown fences. Write in Chinese.

            Hard constraints:
            - Respect the teacher's revision request first.
            - Keep the stage plan to 2-5 stages.
            - Preserve useful original stages when possible instead of rewriting everything.
            - Avoid repeating the same explanation across plan_overview, initial_guidance, and stage reasons.
            - Ask exactly 2 targeted questions for the new first stage.
            - Keep every field short and direct.
            - Keep the tone natural and conversational.

            Use the same JSON shape as the opening plan.
            """
        ).strip()

    def _build_revised_plan_user_prompt(self, session: ResearchSession, adjustment_text: str) -> str:
        return dedent(
            f"""
            Project title: {session.project_title}

            Initial idea:
            {session.state_snapshot.get('initial_idea', '')}

            Current internal stage plan:
            {self._format_stage_plan_for_prompt(session.state_snapshot.get('stage_plan', []))}

            Teacher's revision request:
            {adjustment_text.strip()}

            Output requirements:
            - Keep the reply short and practical.
            - Rebuild the internal order if needed.
            - Make the new Stage 1 immediately useful.
            - Ask exactly two Stage 1 questions.
            """
        ).strip()
        return dedent(
            f"""
            项目标题：{session.project_title}

            教师初始想法：
            {session.state_snapshot.get('initial_idea', '')}

            当前阶段计划：
            {self._format_stage_plan_for_prompt(session.state_snapshot.get('stage_plan', []))}

            教师修改意见：
            {adjustment_text.strip()}

            生成要求：
            - plan_overview：简要说明你如何根据教师反馈调整了顺序或重点。
            - initial_guidance：只给新第一阶段最需要的 1 句推进建议。
            - questions：聚焦新第一阶段，不要泛泛追问。
            - 说话像正常对话，不要像在写说明文。
            """
        ).strip()

    def _build_round_reply_system_prompt(self, is_last_stage: bool) -> str:
        final_rule = (
            "- final_summary: for the final stage, give a concise 3-5 line wrap-up. Otherwise return an empty string."
            if is_last_stage
            else '- final_summary: return "".'
        )
        return dedent(
            f"""
            {self.facilitator_prompt}

            {self.prioritization_prompt}

            {self.draft_generation_prompt}

            You are generating the result for one stage of an action-research conversation.
            Return valid JSON only. No markdown fences. Write in English.

            Hard constraints:
            - Ground every field in the current stage and the teacher's latest input.
            - Be concise, specific, and non-repetitive.
            - Do not restate the full project background unless it is essential.
            - Do not invent classes, evidence, time ranges, literature, or outcomes not mentioned by the teacher.
            - Different fields must do different jobs.
            - The tone must feel like normal conversation with a thoughtful collaborator.

            Field requirements:
            - current_focus_summary: at most 2 short sentences, only about this stage.
            - stage_feedback: 1 short sentence that comments on the quality or gap.
            - guidance: 1 short actionable sentence about how to refine the current draft.
            - draft: 1 compact paragraph that the teacher can directly edit.
            - coach_message: 1 short sentence. If not final, tell the teacher the draft is ready on the right and they can confirm when ready for the next stage.
            - next_questions: if there is a next stage, provide exactly 2 targeted questions for that next stage; otherwise return [].
            {final_rule}

            Return this JSON shape:
            {{
              "current_focus_summary": "...",
              "stage_feedback": "...",
              "guidance": "...",
              "draft": "...",
              "coach_message": "...",
              "next_questions": ["...", "..."],
              "final_summary": ""
            }}
            """
        ).strip()
        final_rule = (
            "- final_summary：最后阶段必须给出 3 到 5 行简洁总结；非最后阶段留空字符串。"
            if is_last_stage
            else "- final_summary：留空字符串。"
        )
        return dedent(
            f"""
            {self.facilitator_prompt}

            {self.prioritization_prompt}

            {self.draft_generation_prompt}

            You are generating the stage result for a teacher.
            Return valid JSON only. No markdown fences. Write in Chinese.

            Hard constraints:
            - Ground every field in the current stage and the teacher's latest input.
            - Be concise, specific, and non-repetitive.
            - Do not restate the full project background unless it is essential.
            - Do not invent classes, evidence, time ranges, literature, or outcomes not mentioned by the teacher.
            - Different fields must serve different purposes.
            - Avoid stiff academic filler such as "有待进一步完善" unless you name the exact missing point.
            - The tone must feel like normal conversation with a thoughtful collaborator.

            Field requirements:
            - current_focus_summary: at most 2 short sentences, only about this stage.
            - stage_feedback: 1 short sentence, diagnose quality or gaps, mention at least one concrete teacher detail when available.
            - guidance: 1 short actionable sentence about how to refine the current draft or document.
            - draft: one short revision-friendly paragraph that the teacher can directly edit, keep it compact.
            - coach_message: 1 short sentence. If not final, say the stage doc is ready for review before the next stage. If final, say the overall summary is ready.
            - next_questions: if there is a next stage, provide exactly 2 targeted questions for that next stage; otherwise return [].
            {final_rule}
            - Avoid labels such as "阶段反馈：" or "下一步建议：".

            Return this JSON shape:
            {{
              "current_focus_summary": "...",
              "stage_feedback": "...",
              "guidance": "...",
              "draft": "...",
              "coach_message": "...",
              "next_questions": ["...", "..."],
              "final_summary": ""
            }}
            """
        ).strip()

    def _build_round_reply_user_prompt(
        self,
        session: ResearchSession,
        answers: list[str],
        latest_input: str | None,
        is_last_stage: bool,
    ) -> str:
        current_stage_index = session.state_snapshot.get("current_stage_index", 0)
        total_rounds = session.state_snapshot.get("total_rounds", 1)
        current_stage = session.state_snapshot["stage_plan"][current_stage_index]
        next_stage = None if is_last_stage else session.state_snapshot["stage_plan"][current_stage_index + 1]
        return dedent(
            f"""
            Project title: {session.project_title}

            Initial idea:
            {session.state_snapshot.get('initial_idea', '')}

            Current stage:
            - Number: {current_stage_index + 1}/{total_rounds}
            - Label: {current_stage['label']}
            - Focus: {current_stage['focus'].value}
            - Why this stage: {current_stage['reason']}

            Current stage questions:
            {self._format_questions_for_prompt(session.guiding_questions)}

            Teacher response this round:
            {self._format_answers_for_prompt(answers, latest_input)}

            Completed stage history:
            {self._format_history_for_prompt(session)}

            Latest document revision:
            {self._format_latest_document_for_prompt(session)}

            Next stage:
            {self._format_next_stage_for_prompt(next_stage)}

            Output requirements:
            - Only summarize the current stage.
            - If the teacher input is incomplete, name the single most important missing piece.
            - next_questions must truly belong to the next stage.
            - Keep every field short and natural.
            """
        ).strip()
        current_stage_index = session.state_snapshot.get("current_stage_index", 0)
        total_rounds = session.state_snapshot.get("total_rounds", 1)
        current_stage = session.state_snapshot["stage_plan"][current_stage_index]
        next_stage = None if is_last_stage else session.state_snapshot["stage_plan"][current_stage_index + 1]
        return dedent(
            f"""
            项目标题：{session.project_title}

            初始想法：
            {session.state_snapshot.get('initial_idea', '')}

            当前阶段：
            - 序号：{current_stage_index + 1}/{total_rounds}
            - 标签：{current_stage['label']}
            - focus：{current_stage['focus'].value}
            - 本阶段原因：{current_stage['reason']}

            当前阶段问题：
            {self._format_questions_for_prompt(session.guiding_questions)}

            教师本轮回答：
            {self._format_answers_for_prompt(answers, latest_input)}

            已完成阶段摘要：
            {self._format_history_for_prompt(session)}

            最近文档修订：
            {self._format_latest_document_for_prompt(session)}

            下一阶段：
            {self._format_next_stage_for_prompt(next_stage)}

            输出要求：
            - 只总结当前阶段，不要把历史内容整段再说一遍。
            - 如果教师信息不足，只指出当前阶段最关键的缺口。
            - next_questions 必须真正服务于下一阶段，而不是重复当前阶段问题。
            - 全部字段尽量用短句。
            - 语气像真实聊天，不要生硬，不要端着。
            """
        ).strip()

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
                    "Summarize the difference between two draft versions in one short English sentence.",
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
            parts.append(f"Added '{self._clip_text(added[0])}'")
        if removed:
            parts.append(f"reworked or removed '{self._clip_text(removed[0])}'")
        if not parts:
            if SequenceMatcher(None, original_text, revised_text).ratio() < 0.7:
                parts.append("Reworked the draft structure and wording")
            elif len(revised_text) >= len(original_text):
                parts.append("Expanded the original draft with more detail")
            else:
                parts.append("Condensed and tightened the original draft")
        return ". ".join(parts) + "."
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

    def _ensure_sentence(self, text: str) -> str:
        stripped = text.strip()
        if not stripped:
            return ""
        if stripped.endswith((".", "!", "?")):
            return stripped
        return f"{stripped}."

    def _load_prompt_file(self, relative_path: str, fallback: str) -> str:
        path = PROJECT_ROOT / "prompts" / relative_path
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError:
            return fallback
        return content or fallback

    def _format_stage_plan_for_prompt(self, stage_plan: list[dict[str, Any]]) -> str:
        if not stage_plan:
            return "None"
        return "\n".join(
            f"- Stage {index} [{stage['focus'].value}] {stage['label']}: {stage['reason']}"
            for index, stage in enumerate(stage_plan, start=1)
        )
        if not stage_plan:
            return "无"
        return "\n".join(
            f"- 第 {index} 阶段 [{stage['focus'].value}] {stage['label']}：{stage['reason']}"
            for index, stage in enumerate(stage_plan, start=1)
        )

    def _format_questions_for_prompt(self, questions: list[str]) -> str:
        if not questions:
            return "None"
        return "\n".join(f"- {question}" for question in questions)
        if not questions:
            return "无"
        return "\n".join(f"- {question}" for question in questions)

    def _format_answers_for_prompt(self, answers: list[str], latest_input: str | None) -> str:
        lines = []
        for index, answer in enumerate(answers, start=1):
            cleaned = answer.strip()
            if cleaned:
                lines.append(f"- Answer {index}: {cleaned}")
        if latest_input and latest_input.strip():
            lines.append(f"- Extra note: {latest_input.strip()}")
        return "\n".join(lines) if lines else "- No useful input yet."
        lines = []
        for index, answer in enumerate(answers, start=1):
            cleaned = answer.strip()
            if cleaned:
                lines.append(f"- 回答 {index}：{cleaned}")
        if latest_input and latest_input.strip():
            lines.append(f"- 补充说明：{latest_input.strip()}")
        return "\n".join(lines) if lines else "- 本轮暂无有效输入"

    def _format_history_for_prompt(self, session: ResearchSession) -> str:
        history = session.state_snapshot.get("conversation_history", [])
        if not history:
            return "None"
        return "\n".join(
            f"- Stage {item['round_index']} ({item['focus_label']}): {item['summary']}"
            for item in history[-3:]
        )
        history = session.state_snapshot.get("conversation_history", [])
        if not history:
            return "无"
        return "\n".join(
            f"- 第 {item['round_index']} 阶段【{item['focus_label']}】：{item['summary']}"
            for item in history[-3:]
        )

    def _format_latest_document_for_prompt(self, session: ResearchSession) -> str:
        latest_document = self.get_latest_document(session)
        if latest_document is None:
            return "None"
        if latest_document.get("is_modified"):
            return (
                f"The previous stage draft '{latest_document['stage_label']}' was revised. "
                f"Revision summary: {latest_document.get('modification_summary') or 'There were substantive edits.'}"
            )
        return f"The previous stage draft '{latest_document['stage_label']}' was not revised."
        latest_document = self.get_latest_document(session)
        if latest_document is None:
            return "无"
        if latest_document.get("is_modified"):
            return (
                f"上一阶段文档【{latest_document['stage_label']}】已被教师修订，"
                f"修订摘要：{latest_document.get('modification_summary') or '有实质修改'}"
            )
        return f"上一阶段文档【{latest_document['stage_label']}】未被教师修订。"

    def _format_next_stage_for_prompt(self, next_stage: dict[str, Any] | None) -> str:
        if next_stage is None:
            return "There is no next stage."
        return f"{next_stage['label']} ({next_stage['focus'].value}): {next_stage['reason']}"
        if next_stage is None:
            return "无下一阶段，本轮是最后阶段。"
        return f"{next_stage['label']}（{next_stage['focus'].value}）：{next_stage['reason']}"

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
            ResearchCycleStage.PLANNING: "Planning",
            ResearchCycleStage.ACTION: "Action",
            ResearchCycleStage.OBSERVATION: "Observation",
            ResearchCycleStage.REFLECTION: "Reflection",
        }[stage]
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
