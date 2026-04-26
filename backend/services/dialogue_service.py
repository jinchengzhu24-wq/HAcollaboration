from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any
from uuid import uuid4

from backend.clients.deepseek_client import DeepSeekClient
from backend.config import get_settings
from backend.models.session import FocusArea, ResearchCycleStage, ResearchSession, SessionStage, StageStatus
from backend.services.cida import CidaSupportService
from backend.services.document_service import StageDocumentService
from backend.services.prioritization import PrioritizationService


class DialogueService:
    def __init__(self) -> None:
        settings = get_settings()
        self.prioritization_service = PrioritizationService()
        self.cida_support_service = CidaSupportService()
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
        cida_enabled: bool = False,
    ) -> ResearchSession:
        initial_idea = initial_idea.strip()
        session_start = self._generate_session_start(initial_idea, cida_enabled)
        stage_one_questions = list(session_start["stage_one_questions"])
        if cida_enabled:
            stage_one_questions.extend(self.cida_support_service.support_questions(FocusArea.PROBLEM_FRAMING))
        stages = [
            SessionStage(
                index=index,
                label=str(stage["label"]),
                reason=str(stage["reason"]),
                focus=stage["focus"],
                questions=stage_one_questions
                if index == 1
                else self._stage_questions(stage["focus"], cida_enabled),
                status=StageStatus.AVAILABLE if index == 1 else StageStatus.LOCKED,
                visited=index == 1,
            )
            for index, stage in enumerate(self.prioritization_service.build_car_stage_plan(), start=1)
        ]
        return ResearchSession(
            session_id=str(uuid4()),
            teacher_id=teacher_id,
            project_title=project_title,
            cycle_stage=ResearchCycleStage.PLANNING,
            stages=stages,
            active_stage_index=1,
            latest_draft=None,
            state_snapshot={
                "initial_idea": initial_idea,
                "cida_enabled": cida_enabled,
                "opening_message": session_start["opening_message"],
            },
        )

    def is_cida_enabled(self, session: ResearchSession) -> bool:
        return bool(session.state_snapshot.get("cida_enabled"))

    def set_cida_mode(self, session: ResearchSession, enabled: bool) -> str:
        currently_enabled = self.is_cida_enabled(session)
        session.state_snapshot["cida_enabled"] = enabled
        for stage in session.stages:
            if stage.status != StageStatus.DELETED:
                stage.questions = self._stage_questions(
                    stage.focus,
                    enabled,
                    initial_idea=str(session.state_snapshot.get("initial_idea", "")),
                )

        if currently_enabled == enabled:
            return "CIDA support is already turned on." if enabled else "CIDA support is already turned off."

        affected_count = 0
        for stage in session.stages:
            if stage.status in {StageStatus.DELETED, StageStatus.LOCKED}:
                continue
            if stage.document or stage.summary or stage.draft:
                if not stage.is_outdated:
                    affected_count += 1
                stage.is_outdated = True

        mode = "on" if enabled else "off"
        message = f"CIDA support turned {mode}. Stage prompts have been updated."
        if affected_count:
            message = f"{message} {affected_count} existing stage(s) are marked outdated and can be regenerated."
        return message

    def get_cida_guidance(self, session: ResearchSession, stage: SessionStage) -> list[str]:
        if not self.is_cida_enabled(session):
            return []
        return self.cida_support_service.support_questions(stage.focus)

    def llm_status_text(self) -> str:
        return "DeepSeek connected" if self.deepseek_client is not None else "Fallback mode"

    def build_opening_message(self, session: ResearchSession) -> str:
        return str(session.state_snapshot.get("opening_message", ""))

    def _generate_session_start(self, initial_idea: str, cida_enabled: bool) -> dict[str, str | list[str]]:
        fallback = {
            "opening_message": self._build_session_opening_message(initial_idea, cida_enabled),
            "stage_one_questions": self._problem_framing_questions_for_initial_idea(initial_idea),
        }
        if self.deepseek_client is None:
            return fallback

        try:
            system_prompt = (
                "You are a warm, specific classroom action research facilitator. "
                "Return JSON with keys opening_message and questions. "
                "opening_message must be 2-4 concise conversational sentences that directly respond "
                "to the teacher's specific first message. Avoid stock phrases and do not sound like a report. "
                "questions must be an array of exactly two concrete Problem Framing questions. "
                "Each question must connect to the teacher's topic and ask about observable classroom moments, "
                "affected learners, or a visible early improvement. Use the same language as the teacher when practical. "
                "Do not use markdown."
            )
            if cida_enabled:
                system_prompt += (
                    " CIDA mode is enabled, so the opening may briefly mention evidence, collaborators, "
                    "or technology support, but keep the two questions focused on problem framing."
                )
            payload = self.deepseek_client.generate_json(
                system_prompt=system_prompt,
                user_prompt=(
                    f"Teacher's first message:\n{initial_idea or 'No specific idea yet.'}\n\n"
                    "Create the first assistant reply and the first two questions."
                ),
            )
            return {
                "opening_message": self._text_or(payload.get("opening_message"), fallback["opening_message"]),
                "stage_one_questions": self._questions_or(payload.get("questions"), fallback["stage_one_questions"]),
            }
        except Exception:
            return fallback

    def _build_session_opening_message(self, initial_idea: str, cida_enabled: bool) -> str:
        idea = self._clean_initial_idea(initial_idea)
        focus = self._initial_idea_focus(idea)
        acknowledgement = self._opening_acknowledgement(idea)
        cida_note = (
            "\n\nCIDA support is on, so I will also ask about evidence, collaborators, and technology support."
            if cida_enabled
            else ""
        )
        return (
            f"{acknowledgement}\n\n"
            f"Let's make this researchable: {focus}. "
            "First we need to pin down where it appears, who is most affected, "
            "and what early classroom change would show progress."
            f"{cida_note}"
        )

    def _clean_initial_idea(self, initial_idea: str) -> str:
        cleaned = re.sub(r"\s+", " ", initial_idea).strip()
        if not cleaned:
            return "the classroom situation you want to investigate"
        if len(cleaned) <= 180:
            return cleaned
        return f"{cleaned[:177].rstrip()}..."

    def _opening_acknowledgement(self, idea: str) -> str:
        compact = re.sub(r"[\s.!?,;:'\"`~]+", "", idea).lower()
        small_talk = {
            "hi",
            "hello",
            "hey",
            "start",
            "\u4f60\u597d",
            "\u60a8\u597d",
            "\u55e8",
            "\u54c8\u55bd",
            "\u5f00\u59cb",
            "\u5728\u5417",
        }
        if compact in small_talk:
            return "Hi, I can help turn a classroom concern into an action research plan."
        return f"That gives us a useful starting point: {idea}"

    def _initial_idea_focus(self, initial_idea: str) -> str:
        focus = initial_idea.strip()
        replacements = (
            r"^(?:i\s+want\s+to|i\s+would\s+like\s+to|i\s+need\s+to|i'?m\s+trying\s+to|my\s+goal\s+is\s+to)\s+",
            r"^(?:help\s+me\s+|can\s+you\s+help\s+me\s+)",
            r"^(?:research|study|investigate)\s+",
            r"^(?:\u6211\u60f3(?:\u8981)?(?:\u7814\u7a76|\u6539\u5584|\u63d0\u9ad8)?|\u5e2e\u6211|\u8bf7\u5e2e\u6211)\s*",
            r"^(?:\u7814\u7a76|\u6539\u5584|\u63d0\u9ad8)\s*",
        )
        for pattern in replacements:
            focus = re.sub(pattern, "", focus, count=1, flags=re.IGNORECASE).strip()
        focus = re.sub(r"\s+", " ", focus).strip(" .")
        if not focus:
            return "this classroom concern"
        if focus[:1].isupper() and not focus[:2].isupper():
            focus = f"{focus[0].lower()}{focus[1:]}"
        if re.match(
            r"^(?:improve|increase|reduce|develop|strengthen|support|encourage|help|raise|build)\b",
            focus,
            flags=re.IGNORECASE,
        ):
            focus = f"the need to {focus}"
        if len(focus) > 120:
            return f"{focus[:117].rstrip()}..."
        return focus

    def build_combined_document(self, session: ResearchSession) -> str:
        sections = []
        for stage in session.stages:
            if stage.status == StageStatus.DELETED:
                continue
            draft, _ = self._editable_parts(stage.draft or self._current_stage_body(session, stage), stage.guidance)
            parts = [
                f"Stage {stage.index}: {stage.label}",
                "Working Draft:",
                draft or "This stage still needs more detail.",
            ]
            if stage.feedback:
                parts.extend(["System Feedback:", stage.feedback.strip()])
            qa_record = self._compose_qa_record(stage)
            if qa_record:
                parts.extend(["Question and Answer Record:", qa_record])
            sections.append("\n".join(parts).rstrip())
        return "\n\n".join(section for section in sections if section.strip())

    def get_stage(self, session: ResearchSession, stage_index: int) -> SessionStage:
        for stage in session.stages:
            if stage.index == stage_index:
                return stage
        raise ValueError("Stage not found.")

    def get_active_stage(self, session: ResearchSession) -> SessionStage | None:
        if session.active_stage_index is None:
            return None
        for stage in session.stages:
            if stage.index == session.active_stage_index:
                return stage
        return None

    def get_current_questions(self, session: ResearchSession) -> list[str]:
        active_stage = self.get_active_stage(session)
        if active_stage is None or active_stage.status == StageStatus.DELETED:
            return []
        return active_stage.questions

    def _stage_questions(
        self,
        focus_area: FocusArea,
        cida_enabled: bool,
        initial_idea: str | None = None,
    ) -> list[str]:
        if focus_area == FocusArea.PROBLEM_FRAMING and initial_idea and initial_idea.strip():
            questions = self._problem_framing_questions_for_initial_idea(initial_idea)
        else:
            questions = list(self.prioritization_service.default_questions(focus_area))
        if cida_enabled:
            questions.extend(self.cida_support_service.support_questions(focus_area))
        return questions

    def _problem_framing_questions_for_initial_idea(self, initial_idea: str) -> list[str]:
        focus = self._initial_idea_focus(self._clean_initial_idea(initial_idea))
        return [
            (
                f"Which lesson moment makes this issue most visible: {focus}? "
                "What do students or the teacher do in that moment?"
            ),
            (
                "Which learners are most affected by this issue, and what small early change would show progress?"
            ),
        ]

    def get_current_round_label(self, session: ResearchSession) -> str:
        active_stage = self.get_active_stage(session)
        if active_stage is None:
            return "No active stage"
        return f"Stage {active_stage.index}/{len(session.stages)}: {active_stage.label}"

    def is_complete(self, session: ResearchSession) -> bool:
        visible = [stage for stage in session.stages if stage.status != StageStatus.DELETED]
        return bool(visible) and all(
            stage.status in {StageStatus.COMPLETED, StageStatus.SKIPPED} for stage in visible
        )

    def activate_stage(self, session: ResearchSession, stage_index: int) -> str:
        stage = self.get_stage(session, stage_index)
        if stage.status in {StageStatus.LOCKED, StageStatus.DELETED}:
            raise ValueError("This stage is not available yet.")
        previous_active_index = session.active_stage_index
        if previous_active_index is not None and stage.index < previous_active_index:
            session.state_snapshot["return_stage_index"] = previous_active_index
            self._mark_following_stages_outdated(session, stage.index)
        else:
            session.state_snapshot.pop("return_stage_index", None)
        session.active_stage_index = stage.index
        stage.visited = True
        return f"Now working on Stage {stage.index}: {stage.label}."

    def turn_stage(
        self,
        session: ResearchSession,
        stage_index: int,
        answers: list[str],
        latest_input: str | None,
    ) -> str:
        stage = self.get_stage(session, stage_index)
        if stage.status in {StageStatus.LOCKED, StageStatus.DELETED}:
            raise ValueError("This stage is not available for editing.")

        cleaned_answers = [item.strip() for item in answers if item and item.strip()]
        cleaned_latest_input = latest_input.strip() if latest_input and latest_input.strip() else None
        if not cleaned_answers and not cleaned_latest_input:
            raise ValueError("Please add at least one useful response for this stage.")

        session.active_stage_index = stage.index
        stage.visited = True
        payload = self._generate_stage_payload(session, stage, cleaned_answers, cleaned_latest_input)
        stage.document = self.document_service.build_stage_document(
            session_id=session.session_id,
            project_title=session.project_title,
            stage_index=stage.index,
            stage_label=stage.label,
            questions=list(stage.questions),
            answers=cleaned_answers,
            latest_input=cleaned_latest_input,
            summary=payload["summary"],
            feedback=payload["feedback"],
            guidance=self._build_stage_guidance(session, stage, payload["guidance"]),
            draft=payload["draft"],
        )
        stage.summary = payload["summary"]
        stage.feedback = payload["feedback"]
        stage.guidance = self._build_stage_guidance(session, stage, payload["guidance"])
        stage.draft = payload["draft"].strip()
        stage.latest_answers = cleaned_answers
        stage.latest_input = cleaned_latest_input
        stage.is_outdated = False
        if stage.status in {StageStatus.COMPLETED, StageStatus.SKIPPED}:
            stage.status = StageStatus.COMPLETED
            stage.needs_confirmation = False
        else:
            stage.status = StageStatus.AVAILABLE
            stage.needs_confirmation = True
        session.latest_draft = stage.draft
        outdated_count = self._mark_following_stages_outdated(session, stage.index)
        return self._build_turn_message(session, stage, outdated_count)

    def confirm_stage(self, session: ResearchSession, stage_index: int) -> str:
        stage = self.get_stage(session, stage_index)
        if stage.status in {StageStatus.LOCKED, StageStatus.DELETED}:
            raise ValueError("This stage cannot be confirmed.")
        if not self._current_stage_body(session, stage):
            raise ValueError("Please generate or edit stage content before confirming it.")
        stage.status = StageStatus.COMPLETED
        stage.needs_confirmation = False
        stage.is_outdated = False
        next_stage = self._unlock_next_stage(session, stage.index)
        return_stage = self._consume_return_stage(session, stage.index)
        if return_stage is not None:
            session.active_stage_index = return_stage.index
            return_stage.visited = True
            return (
                f"Stage {stage.index} confirmed. Returned to Stage {return_stage.index}: {return_stage.label}. "
                "Regenerate this stage after reviewing the upstream change."
            )
        self._refresh_active_stage_after_progress(session, next_stage)
        return (
            f"Stage {stage.index} confirmed."
            if next_stage is None
            else f"Stage {stage.index} confirmed. Stage {next_stage.index} is now unlocked."
        )

    def skip_stage(self, session: ResearchSession, stage_index: int) -> str:
        stage = self.get_stage(session, stage_index)
        if stage.status in {StageStatus.LOCKED, StageStatus.DELETED}:
            raise ValueError("This stage cannot be skipped.")
        stage.status = StageStatus.SKIPPED
        stage.needs_confirmation = False
        stage.is_outdated = False
        next_stage = self._unlock_next_stage(session, stage.index)
        return_stage = self._consume_return_stage(session, stage.index)
        if return_stage is not None:
            session.active_stage_index = return_stage.index
            return_stage.visited = True
            return (
                f"Stage {stage.index} skipped. Returned to Stage {return_stage.index}: {return_stage.label}. "
                "Regenerate this stage after reviewing the upstream change."
            )
        self._refresh_active_stage_after_progress(session, next_stage)
        return (
            f"Stage {stage.index} skipped."
            if next_stage is None
            else f"Stage {stage.index} skipped. Stage {next_stage.index} is now unlocked."
        )

    def delete_stage(self, session: ResearchSession, stage_index: int) -> str:
        stage = self.get_stage(session, stage_index)
        if stage.status == StageStatus.DELETED:
            raise ValueError("This stage has already been deleted.")
        stage.status = StageStatus.DELETED
        stage.needs_confirmation = False
        stage.is_outdated = False
        next_stage = self._unlock_next_stage(session, stage.index)
        if session.active_stage_index == stage.index:
            replacement = self._pick_replacement_active_stage(session, stage.index, next_stage)
            session.active_stage_index = replacement.index if replacement is not None else None
        return f"Stage {stage.index} deleted."

    def review_stage(self, session: ResearchSession, stage_index: int) -> str:
        stage = self.get_stage(session, stage_index)
        if stage.status in {StageStatus.LOCKED, StageStatus.DELETED}:
            raise ValueError("This stage cannot be reviewed.")
        if not stage.is_outdated:
            raise ValueError("This stage is already up to date.")
        stage.is_outdated = False
        return f"Stage {stage.index} marked as up to date."

    def regenerate_stage(
        self,
        session: ResearchSession,
        stage_index: int,
        workspace_content: str | None = None,
    ) -> str:
        stage = self.get_stage(session, stage_index)
        if stage.status in {StageStatus.LOCKED, StageStatus.DELETED}:
            raise ValueError("This stage cannot be regenerated.")
        if workspace_content is not None:
            current_body = self._current_stage_body(session, stage)
            workspace_body = self._collapse_repeated_heading_lines(
                self._normalize_stage_body(workspace_content, session, stage)
            )
            if self._documents_are_different(current_body, workspace_body):
                return self._regenerate_feedback_for_workspace_edit(session, stage, current_body, workspace_body)

        answers = list(stage.latest_answers)
        latest_input = stage.latest_input
        if not answers and not latest_input:
            body = self._current_stage_body(session, stage)
            if body:
                answers = [body]
        if not answers and not latest_input:
            raise ValueError("This stage does not have enough content to regenerate.")
        message = self.turn_stage(session, stage.index, answers, latest_input)
        if stage.status in {StageStatus.COMPLETED, StageStatus.SKIPPED}:
            stage.status = StageStatus.COMPLETED
            stage.needs_confirmation = False
            stage.is_outdated = False
        return f"Stage {stage.index} regenerated. {message}"

    def _regenerate_feedback_for_workspace_edit(
        self,
        session: ResearchSession,
        stage: SessionStage,
        previous_body: str,
        workspace_body: str,
    ) -> str:
        if not workspace_body.strip():
            raise ValueError("The workspace draft cannot be empty.")

        change_summary = self._summarize_document_revision(previous_body, workspace_body)
        stage.feedback = self._generate_feedback_for_workspace_body(session, stage, workspace_body)
        updated = self.document_service.save_text_revision(
            session_id=session.session_id,
            stage_index=stage.index,
            stage_label=stage.label,
            content=self._compose_stage_document_text(session, stage, workspace_body),
        )
        stage.document = self._merge_document_metadata(stage, updated)
        stage.draft = workspace_body
        stage.summary = self._manual_summary(stage, workspace_body)
        stage.is_outdated = False
        stage.visited = True
        session.active_stage_index = stage.index
        session.latest_draft = workspace_body
        if stage.status in {StageStatus.COMPLETED, StageStatus.SKIPPED}:
            stage.status = StageStatus.COMPLETED
            stage.needs_confirmation = False
        else:
            stage.status = StageStatus.AVAILABLE
            stage.needs_confirmation = True

        outdated_count = self._mark_following_stages_outdated(session, stage.index)
        message = (
            f"I noticed you changed the workspace draft: {change_summary} "
            "I kept your draft as written and regenerated the feedback only."
        )
        if outdated_count:
            message = f"{message} {outdated_count} later stage(s) are now marked outdated."
        return f"{message}\n\nUpdated Feedback:\n{stage.feedback}"

    def _generate_feedback_for_workspace_body(
        self,
        session: ResearchSession,
        stage: SessionStage,
        workspace_body: str,
    ) -> str:
        fallback = self._fallback_feedback(session, stage, [workspace_body], None)
        if self.deepseek_client is None:
            return fallback

        try:
            payload = self.deepseek_client.generate_json(
                system_prompt=(
                    "You are reviewing a teacher-edited classroom action research draft. "
                    "Return JSON with key feedback only. Do not rewrite the draft. "
                    "The feedback must use exactly three short headings on separate lines: "
                    "What Changed:, Make It Stronger:, Example To Add:. "
                    "Under each heading, write one or two specific sentences grounded in the edited draft. "
                    "Include one concrete example sentence or classroom evidence example the teacher can adapt. "
                    "Mark one important phrase with **double asterisks** and do not use markdown bullets."
                ),
                user_prompt=(
                    f"Project title: {session.project_title}\n"
                    f"Current stage: Stage {stage.index} {stage.label}\n"
                    f"Stage purpose: {stage.reason}\n"
                    f"Teacher-edited draft:\n{workspace_body}"
                ),
            )
            return self._ensure_structured_feedback(
                self._text_or(payload.get("feedback"), fallback),
                fallback,
            )
        except Exception:
            return fallback

    def edit_stage_document(self, session: ResearchSession, stage_index: int, content: str) -> str:
        stage = self.get_stage(session, stage_index)
        if stage.status in {StageStatus.LOCKED, StageStatus.DELETED}:
            raise ValueError("This stage cannot be edited.")
        body = self._normalize_stage_body(content, session, stage)
        draft, guidance = self._split_editable_section(body, stage.guidance)
        self._apply_manual_stage_update(
            session,
            stage,
            draft,
            "This stage was updated directly in the document editor.",
            guidance,
        )
        outdated_count = self._mark_following_stages_outdated(session, stage.index)
        return (
            f"Stage {stage.index} saved."
            if outdated_count == 0
            else f"Stage {stage.index} saved. {outdated_count} later stage(s) are now marked outdated."
        )

    def edit_combined_document(self, session: ResearchSession, content: str) -> str:
        if not content.strip():
            raise ValueError("The document cannot be empty.")
        updates = self._parse_combined_document(content)
        if not updates:
            raise ValueError("Use the existing `Stage N: Label` headings when editing the document.")

        changed_indexes: list[int] = []
        for stage in session.stages:
            if stage.index not in updates or stage.status == StageStatus.DELETED:
                continue
            new_body = self._normalize_stage_body(updates[stage.index], session, stage)
            current_body = self._current_stage_body(session, stage)
            current_guidance = (stage.guidance or "").strip()
            draft, guidance = self._split_editable_section(new_body, current_guidance)
            normalized_combined = self._combine_editable_section(draft, guidance)
            current_combined = self._combine_editable_section(current_body, current_guidance)
            if not self._documents_are_different(current_combined, normalized_combined):
                continue
            if stage.status == StageStatus.LOCKED:
                raise ValueError(
                    f"Stage {stage.index} is still locked. Confirm or skip earlier stages before editing it."
                )
            self._apply_manual_stage_update(
                session,
                stage,
                draft,
                "This stage was updated directly in the combined document.",
                guidance,
            )
            changed_indexes.append(stage.index)

        if not changed_indexes:
            return "No stage content changed."

        affected = self._mark_stages_outdated_after_changes(session, changed_indexes)
        changed_label = ", ".join(str(index) for index in changed_indexes)
        if not affected:
            return f"Saved the combined document for stage(s) {changed_label}."
        affected_label = ", ".join(str(index) for index in affected)
        return (
            f"Saved the combined document for stage(s) {changed_label}. "
            f"Later stage(s) {affected_label} are now marked outdated."
        )

    def save_combined_document_to_desktop(self, session: ResearchSession) -> str:
        sections = [
            {
                "stage_index": stage.index,
                "stage_label": stage.label,
                "draft": self._current_stage_body(session, stage),
                "feedback": stage.feedback or "",
                "questions": list(stage.questions),
                "answers": list(stage.latest_answers),
                "latest_input": stage.latest_input,
            }
            for stage in session.stages
            if stage.status != StageStatus.DELETED
        ]
        path = self.document_service.save_combined_document_to_desktop(session.project_title, sections)
        return str(path)

    def upload_stage_document(
        self,
        session: ResearchSession,
        stage_index: int,
        file_bytes: bytes,
    ) -> str:
        stage = self.get_stage(session, stage_index)
        if stage.status in {StageStatus.LOCKED, StageStatus.DELETED}:
            raise ValueError("This stage cannot accept uploads.")
        updated = self.document_service.save_uploaded_revision(
            session_id=session.session_id,
            stage_index=stage.index,
            stage_label=stage.label,
            file_bytes=file_bytes,
        )
        stage.document = self._merge_document_metadata(stage, updated)
        stage.draft = self._normalize_stage_body(stage.document["preview_text"], session, stage)
        stage.summary = self._manual_summary(stage, stage.draft)
        stage.feedback = "This stage was updated from an uploaded document."
        stage.guidance = self._build_stage_guidance(
            session,
            stage,
            self._base_guidance(session, stage),
        )
        stage.is_outdated = False
        if stage.status in {StageStatus.COMPLETED, StageStatus.SKIPPED}:
            stage.status = StageStatus.COMPLETED
            stage.needs_confirmation = False
        else:
            stage.status = StageStatus.AVAILABLE
            stage.needs_confirmation = True
        outdated_count = self._mark_following_stages_outdated(session, stage.index)
        return (
            f"Stage {stage.index} imported the uploaded document."
            if outdated_count == 0
            else f"Stage {stage.index} imported the uploaded document. {outdated_count} later stage(s) are now marked outdated."
        )

    def _generate_stage_payload(
        self,
        session: ResearchSession,
        stage: SessionStage,
        answers: list[str],
        latest_input: str | None,
    ) -> dict[str, str]:
        if self.deepseek_client is not None:
            try:
                system_prompt = (
                    "You are a concise classroom action research assistant. "
                    "Return JSON with keys summary, feedback, guidance, draft. "
                    "The draft value must use short section headings on their own lines. "
                    "The feedback value must be more substantial than a single sentence: use 3 short headings "
                    "on their own lines, include concrete advice under each heading, and include one example sentence "
                    "or classroom example the teacher could adapt. "
                    "In feedback and guidance, wrap one short key phrase in double asterisks for emphasis."
                )
                if self.is_cida_enabled(session):
                    system_prompt += (
                        " CIDA support is enabled: explicitly connect the draft, feedback, and guidance "
                        "to inquiry process, collective process, and technological support."
                    )
                payload = self.deepseek_client.generate_json(
                    system_prompt=system_prompt,
                    user_prompt=self._build_llm_prompt(session, stage, answers, latest_input),
                )
                draft = self._append_cida_support_notes(
                    session,
                    stage,
                    self._ensure_structured_draft(
                        stage,
                        self._text_or(payload.get("draft"), self._fallback_draft(stage, answers, latest_input)),
                    ),
                )
                fallback_feedback = self._fallback_feedback(session, stage, answers, latest_input)
                return {
                    "summary": self._text_or(payload.get("summary"), self._fallback_summary(stage, answers, latest_input)),
                    "feedback": self._ensure_structured_feedback(
                        self._text_or(payload.get("feedback"), fallback_feedback),
                        fallback_feedback,
                    ),
                    "guidance": self._ensure_key_emphasis(
                        self._text_or(payload.get("guidance"), self._base_guidance(session, stage))
                    ),
                    "draft": draft,
                }
            except Exception:
                pass

        return {
            "summary": self._fallback_summary(stage, answers, latest_input),
            "feedback": self._fallback_feedback(session, stage, answers, latest_input),
            "guidance": self._base_guidance(session, stage),
            "draft": self._append_cida_support_notes(
                session,
                stage,
                self._ensure_structured_draft(stage, self._fallback_draft(stage, answers, latest_input)),
            ),
        }

    def _build_llm_prompt(
        self,
        session: ResearchSession,
        stage: SessionStage,
        answers: list[str],
        latest_input: str | None,
    ) -> str:
        previous_blocks = []
        for previous_stage in session.stages:
            if previous_stage.index >= stage.index:
                break
            if previous_stage.status == StageStatus.DELETED:
                continue
            previous_text = self._current_stage_body(session, previous_stage)
            if previous_text:
                previous_blocks.append(f"Stage {previous_stage.index} {previous_stage.label}:\n{previous_text}")

        teacher_input = "\n".join(f"- {item}" for item in answers)
        if latest_input:
            teacher_input = f"{teacher_input}\n- {latest_input}" if teacher_input else f"- {latest_input}"
        previous_text = "\n\n".join(previous_blocks) if previous_blocks else "None"
        cida_text = (
            f"CIDA support:\n{self._format_cida_support_prompt(stage)}\n"
            if self.is_cida_enabled(session)
            else ""
        )
        return (
            f"Project title: {session.project_title}\n"
            f"Initial idea: {session.state_snapshot.get('initial_idea', '')}\n"
            f"Current stage: Stage {stage.index} {stage.label}\n"
            f"Stage purpose: {stage.reason}\n"
            f"Draft format:\n{self._build_draft_format_instruction(session, stage)}\n"
            "Feedback format:\n"
            "Write feedback with exactly three short headings on separate lines: What Works:, Make It Sharper:, "
            "Example To Add:. Under each heading, write one or two specific sentences grounded in the teacher input. "
            "The Example To Add section must include a concrete sentence, classroom moment, evidence example, or wording "
            "the teacher can adapt. Mark one important phrase with **double asterisks** and do not bold whole paragraphs.\n"
            "Guidance format:\n"
            "Write one concise next-step paragraph. Mark one important phrase with **double asterisks**.\n"
            f"{cida_text}"
            f"Teacher input:\n{teacher_input or '- None'}\n"
            f"Previous stage content:\n{previous_text}"
        )

    def _fallback_summary(self, stage: SessionStage, answers: list[str], latest_input: str | None) -> str:
        points = self._collect_points(answers, latest_input)
        if not points:
            return f"{stage.label}: more detail is still needed."
        lead = " ".join(points[:2])
        return f"{stage.label}: {lead}"

    def _fallback_feedback(
        self,
        session: ResearchSession,
        stage: SessionStage,
        answers: list[str] | None = None,
        latest_input: str | None = None,
    ) -> str:
        focus = self._feedback_focus(session, answers or [], latest_input)
        mapping = {
            FocusArea.PROBLEM_FRAMING: (
                "What Works:\n"
                f"You have a usable starting point around **{focus}**. It is close to a classroom problem because it can be seen in specific lesson moments.\n\n"
                "Make It Sharper:\n"
                "Name the learner group, the lesson situation, and the behavior that shows the problem. This will keep the inquiry from becoming too broad.\n\n"
                "Example To Add:\n"
                "Try a sentence like: In grade seven reading discussions, this issue appears when students answer with one short phrase and do not build on a peer's idea."
            ),
            FocusArea.ACTION_DESIGN: (
                "What Works:\n"
                f"The action is connected to **{focus}**, so it can stay practical instead of becoming a general teaching improvement goal.\n\n"
                "Make It Sharper:\n"
                "Specify what the teacher will do first, what students will do in response, and how long the first trial will last.\n\n"
                "Example To Add:\n"
                "Try a sentence like: For two reading lessons, the teacher will use one prepared follow-up prompt after each short answer and ask students to add evidence from the text."
            ),
            FocusArea.OBSERVATION_EVIDENCE: (
                "What Works:\n"
                f"The plan can collect evidence around **{focus}** without turning the inquiry into a large assessment project.\n\n"
                "Make It Sharper:\n"
                "Choose evidence that is easy to capture during class, such as response length, number of follow-up turns, exit tickets, or short observation notes.\n\n"
                "Example To Add:\n"
                "Try recording three sample student responses before and after the action, then compare whether they include reasons, evidence, or peer references."
            ),
            FocusArea.REFLECTION_ITERATION: (
                "What Works:\n"
                f"The reflection can now look back at **{focus}** and separate what actually changed from what still feels uncertain.\n\n"
                "Make It Sharper:\n"
                "Sort the evidence into confirmed gains, weak signals, and unresolved problems before deciding the next cycle.\n\n"
                "Example To Add:\n"
                "Try a sentence like: The strongest gain was longer student responses, but peer-to-peer follow-up still needs a more explicit routine in the next cycle."
            ),
        }
        feedback = mapping[stage.focus]
        if self.is_cida_enabled(session):
            feedback = (
                f"{feedback}\n\nCIDA Lens:\n"
                "Also name one data source, one collaborator who can comment on the pattern, and one technology support that can preserve the evidence."
            )
        return feedback

    def _feedback_focus(self, session: ResearchSession, answers: list[str], latest_input: str | None) -> str:
        points = self._collect_points(answers, latest_input)
        if points:
            focus = points[0]
        else:
            focus = str(session.state_snapshot.get("initial_idea", "") or "the classroom issue")
        focus = self._clean_initial_idea(focus)
        focus = self._initial_idea_focus(focus)
        return self._clip_text(focus, 90)

    def _ensure_structured_feedback(self, feedback: str, fallback: str) -> str:
        cleaned = re.sub(r"\n{3,}", "\n\n", feedback.strip())
        has_headings = len(re.findall(r"(?m)^[A-Za-z][A-Za-z0-9 /&()'-]{1,54}:$", cleaned)) >= 2
        has_example = re.search(r"(?i)\bexample\b|try a sentence|for example", cleaned) is not None
        if has_headings and has_example:
            return self._ensure_key_emphasis(cleaned)
        return fallback

    def _fallback_draft(self, stage: SessionStage, answers: list[str], latest_input: str | None) -> str:
        points = self._collect_points(answers, latest_input)
        chosen = points[:3] if points else self._default_draft_points(stage)
        return self._build_structured_draft(stage, [self._teacher_sentence(item) for item in chosen if item.strip()])

    def _base_guidance(self, session: ResearchSession, stage: SessionStage) -> str:
        guidance = self.prioritization_service.focus_guidance(stage.focus)
        if self.is_cida_enabled(session):
            guidance = (
                f"{guidance} Add CIDA support by naming the data inquiry move, the collaboration move, "
                "and the technology support the system should provide."
            )
        return guidance

    def _format_cida_support_prompt(self, stage: SessionStage) -> str:
        return "\n".join(f"- {item}" for item in self.cida_support_service.support_questions(stage.focus))

    def _append_cida_support_notes(
        self,
        session: ResearchSession,
        stage: SessionStage,
        draft: str,
    ) -> str:
        if not self.is_cida_enabled(session):
            return draft
        if re.search(r"(?im)^CIDA Support Notes:\s*$", draft):
            return draft
        notes = self.cida_support_service.support_notes(stage.focus)
        return f"{draft.strip()}\n\nCIDA Support Notes:\n{notes}".strip()

    def _build_draft_format_instruction(self, session: ResearchSession, stage: SessionStage) -> str:
        headings = ", ".join(f"{heading}:" for heading in self._draft_headings(stage))
        instruction = (
            f"Use these headings when they fit: {headings}\n"
            "Put each heading on its own line, followed by one to three concise sentences. "
            "Do not use markdown bullets or numbered lists in the draft."
        )
        if self.is_cida_enabled(session):
            instruction += (
                "\nAlso add a final heading named CIDA Support Notes: with one line each for "
                "Inquiry process, Collective process, and Technological support."
            )
        return instruction

    def _ensure_structured_draft(self, stage: SessionStage, draft: str) -> str:
        cleaned = re.sub(r"\n{3,}", "\n\n", draft.strip())
        cleaned = self._collapse_repeated_heading_lines(cleaned)
        if self._has_structured_stage_lines(stage, cleaned):
            return cleaned
        sentences = self._split_sentences(cleaned)
        sentences.extend(self._teacher_sentence(item) for item in self._default_draft_points(stage))
        return self._collapse_repeated_heading_lines(
            self._build_structured_draft(stage, self._dedupe_sentences(sentences))
        )

    def _collapse_repeated_heading_lines(self, draft: str) -> str:
        lines = draft.splitlines()
        collapsed = []
        index = 0
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            heading_match = re.match(r"^([A-Za-z][A-Za-z0-9 /&()'-]{1,54}:)$", stripped)
            if heading_match:
                heading = heading_match.group(1)
                next_index = index + 1
                while next_index < len(lines) and not lines[next_index].strip():
                    next_index += 1
                if next_index < len(lines):
                    next_line = lines[next_index].strip()
                    if next_line.lower().startswith(heading.lower()) and next_line[len(heading):].strip():
                        index = next_index
                        continue
            collapsed.append(line)
            index += 1
        return "\n".join(collapsed).strip()

    def _build_structured_draft(self, stage: SessionStage, sentences: list[str]) -> str:
        headings = self._draft_headings(stage)
        blocks = []
        for heading, sentence in zip(headings, sentences):
            if sentence.strip():
                blocks.append(f"{heading}:\n{sentence.strip()}")
        return "\n\n".join(blocks).strip()

    def _draft_headings(self, stage: SessionStage) -> list[str]:
        mapping = {
            FocusArea.PROBLEM_FRAMING: [
                "Classroom Problem",
                "Learner Group",
                "Desired Early Change",
            ],
            FocusArea.ACTION_DESIGN: [
                "Planned Action",
                "Implementation Details",
                "Roles and Timing",
            ],
            FocusArea.OBSERVATION_EVIDENCE: [
                "Evidence Sources",
                "Observation Focus",
                "How Evidence Will Be Used",
            ],
            FocusArea.REFLECTION_ITERATION: [
                "What Worked",
                "What Needs Adjustment",
                "Next Cycle Decision",
            ],
        }
        return mapping[stage.focus]

    def _default_draft_points(self, stage: SessionStage) -> list[str]:
        mapping = {
            FocusArea.PROBLEM_FRAMING: [
                "The classroom problem still needs to be clarified.",
                "The teacher wants to narrow the problem to one visible classroom change.",
                "The first improvement target should be concrete enough to observe in class.",
            ],
            FocusArea.ACTION_DESIGN: [
                "The teacher will try a focused classroom action.",
                "The first trial will be scheduled in one specific class and time slot.",
                "The action should name what the teacher and learners will each do.",
            ],
            FocusArea.OBSERVATION_EVIDENCE: [
                "The teacher will collect evidence from classroom observations and learner responses.",
                "The teacher will record the most visible changes during implementation.",
                "The evidence should be simple enough to gather during the first cycle.",
            ],
            FocusArea.REFLECTION_ITERATION: [
                "The teacher will reflect on what worked and what still needs adjustment.",
                "The next cycle will keep the strongest actions and revise weaker points.",
                "The next decision should be based on visible evidence from the classroom.",
            ],
        }
        return mapping[stage.focus]

    def _has_structured_headings(self, draft: str) -> bool:
        headings = re.findall(r"(?m)^[A-Za-z][A-Za-z0-9 /&()'-]{1,54}:$", draft)
        return len(headings) >= 2

    def _has_structured_stage_lines(self, stage: SessionStage, draft: str) -> bool:
        headings = {f"{heading}:".lower() for heading in self._draft_headings(stage)}
        found = set()
        for line in draft.splitlines():
            stripped = line.strip().lower()
            for heading in headings:
                if stripped == heading or stripped.startswith(heading):
                    found.add(heading)
        return len(found) >= 2

    def _split_sentences(self, text: str) -> list[str]:
        cleaned = re.sub(r"\s+", " ", text.strip())
        if not cleaned:
            return []
        return [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", cleaned)
            if sentence.strip()
        ]

    def _dedupe_sentences(self, sentences: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped = []
        for sentence in sentences:
            key = re.sub(r"\W+", "", sentence).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(sentence)
        return deduped

    def _apply_manual_stage_update(
        self,
        session: ResearchSession,
        stage: SessionStage,
        body: str,
        feedback: str,
        guidance_override: str | None = None,
    ) -> None:
        guidance = (guidance_override or "").strip() or self._build_stage_guidance(
            session,
            stage,
            self._base_guidance(session, stage),
        )
        stage.feedback = feedback
        stage.guidance = guidance
        updated = self.document_service.save_text_revision(
            session_id=session.session_id,
            stage_index=stage.index,
            stage_label=stage.label,
            content=self._compose_stage_document_text(session, stage, body),
        )
        stage.document = self._merge_document_metadata(stage, updated)
        stage.draft = body
        stage.summary = self._manual_summary(stage, body)
        stage.is_outdated = False
        stage.visited = True
        session.active_stage_index = stage.index
        session.latest_draft = body
        if stage.status in {StageStatus.COMPLETED, StageStatus.SKIPPED}:
            stage.status = StageStatus.COMPLETED
            stage.needs_confirmation = False
        else:
            stage.status = StageStatus.AVAILABLE
            stage.needs_confirmation = True

    def _compose_stage_document_text(
        self,
        session: ResearchSession,
        stage: SessionStage,
        body: str,
    ) -> str:
        blocks = [
            session.project_title,
            f"Stage {stage.index}: {stage.label}",
            "Working Draft:",
            body.strip() or "This stage still needs more detail.",
        ]
        if stage.feedback:
            blocks.extend(["System Feedback:", stage.feedback.strip()])
        if stage.guidance:
            blocks.extend(["Next Step:", stage.guidance.strip()])
        if stage.questions:
            blocks.append("Current Questions:")
            blocks.extend(
                f"{index}. {question.strip()}"
                for index, question in enumerate(stage.questions, start=1)
                if question and question.strip()
            )
        return "\n\n".join(blocks)

    def _parse_combined_document(self, content: str) -> dict[int, str]:
        matches = list(re.finditer(r"(?im)^Stage\s+(\d+)\s*:\s*(.+?)\s*$", content.strip()))
        if not matches:
            return {}
        sections: dict[int, str] = {}
        for idx, match in enumerate(matches):
            stage_index = int(match.group(1))
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
            sections[stage_index] = content[start:end].strip()
        return sections

    def _normalize_stage_body(
        self,
        content: str,
        session: ResearchSession,
        stage: SessionStage,
    ) -> str:
        normalized = content.replace("\r\n", "\n").strip()
        if not normalized:
            return ""
        lines = [line.strip() for line in normalized.splitlines()]
        while lines and not lines[0]:
            lines.pop(0)
        if lines and lines[0] == session.project_title:
            lines.pop(0)
            while lines and not lines[0]:
                lines.pop(0)
        heading = re.compile(rf"^Stage\s+{stage.index}\s*:\s*", re.IGNORECASE)
        if lines and heading.match(lines[0]):
            lines.pop(0)
        cleaned = "\n".join(lines).strip()
        cleaned = re.split(
            r"\n\s*(?:System Feedback:|Question and Answer Record:|Current Questions:)\s*\n",
            cleaned,
            maxsplit=1,
        )[0]
        cleaned = re.sub(r"\s*Working Draft:\s*", "\n", cleaned, count=1, flags=re.IGNORECASE)
        return re.sub(r"\n{3,}", "\n\n", cleaned.strip())

    def _current_stage_body(self, session: ResearchSession, stage: SessionStage) -> str:
        if stage.draft is not None and stage.draft.strip():
            draft, _ = self._editable_parts(stage.draft.strip(), stage.guidance)
            return draft
        if stage.document and stage.document.get("preview_text"):
            body = self._normalize_stage_body(stage.document["preview_text"], session, stage)
            draft, _ = self._split_editable_section(body, stage.guidance)
            return draft
        return ""

    def _manual_summary(self, stage: SessionStage, body: str) -> str:
        if not body.strip():
            return f"{stage.label}: the section is currently empty."
        first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
        clipped = first_line if len(first_line) <= 120 else f"{first_line[:117]}..."
        return f"{stage.label}: {clipped}"

    def _editable_parts(self, draft: str | None, guidance: str | None) -> tuple[str, str]:
        return (draft or "").strip(), (guidance or "").strip()

    def _combine_editable_section(self, draft: str, guidance: str) -> str:
        parts = [draft.strip()]
        if guidance.strip():
            parts.extend(["Next Step:", guidance.strip()])
        return "\n\n".join(part for part in parts if part)

    def _split_editable_section(self, content: str, fallback_guidance: str | None) -> tuple[str, str]:
        normalized = content.strip()
        match = re.split(r"\n\s*Next Step:\s*\n", normalized, maxsplit=1, flags=re.IGNORECASE)
        if len(match) == 2:
            draft = re.sub(r"^Working Draft:\s*", "", match[0].strip(), flags=re.IGNORECASE)
            guidance = match[1].strip()
        else:
            draft = re.sub(r"^Working Draft:\s*", "", normalized, flags=re.IGNORECASE)
            guidance = (fallback_guidance or "").strip()
        if draft == "This stage still needs more detail.":
            draft = ""
        return draft.strip(), guidance

    def _compose_qa_record(self, stage: SessionStage) -> str:
        lines = []
        for index, answer in enumerate(stage.latest_answers, start=1):
            cleaned_answer = answer.strip()
            if not cleaned_answer:
                continue
            question = stage.questions[index - 1] if index - 1 < len(stage.questions) else "Follow-up response"
            lines.append(f"Q{index}: {question.strip()}")
            lines.append(f"A{index}: {cleaned_answer}")
        if stage.latest_input and stage.latest_input.strip():
            note_index = len(stage.latest_answers) + 1
            lines.append(f"Q{note_index}: Additional user input")
            lines.append(f"A{note_index}: {stage.latest_input.strip()}")
        return "\n".join(lines).strip()

    def _build_stage_guidance(
        self,
        session: ResearchSession,
        stage: SessionStage,
        base_guidance: str,
    ) -> str:
        emphasized_guidance = self._ensure_key_emphasis(base_guidance)
        next_stage = self._next_non_deleted_stage(session, stage.index)
        if next_stage is None:
            decision = "You can keep refining this stage, or confirm it to finish the CAR sequence."
        else:
            decision = (
                f"You can keep refining this stage, or confirm or skip it to move into "
                f"Stage {next_stage.index}: {next_stage.label}."
            )
        return f"{emphasized_guidance} {decision}".strip()

    def _ensure_key_emphasis(self, text: str) -> str:
        cleaned = text.strip()
        if not cleaned or "**" in cleaned:
            return cleaned
        match = re.search(r"[A-Za-z0-9][^.!?]{12,160}[.!?]", cleaned)
        if match is None:
            return cleaned
        phrase = match.group(0).strip()
        return cleaned.replace(phrase, f"**{phrase}**", 1)

    def _build_turn_message(
        self,
        session: ResearchSession,
        stage: SessionStage,
        outdated_count: int,
    ) -> str:
        sections = [
            f"Feedback:\nStage {stage.index}: {stage.feedback}",
            f"Next Step:\n{stage.guidance}",
        ]
        if outdated_count:
            sections.append(
                f"Review Needed:\n{outdated_count} later stage(s) are now marked outdated and should be reviewed."
            )
        return "\n\n".join(section for section in sections if section)

    def _consume_return_stage(
        self,
        session: ResearchSession,
        edited_stage_index: int,
    ) -> SessionStage | None:
        return_index = session.state_snapshot.pop("return_stage_index", None)
        if not isinstance(return_index, int) or return_index <= edited_stage_index:
            return None
        try:
            stage = self.get_stage(session, return_index)
        except ValueError:
            return None
        if stage.status == StageStatus.DELETED:
            return None
        return stage

    def _unlock_next_stage(self, session: ResearchSession, stage_index: int) -> SessionStage | None:
        for stage in session.stages:
            if stage.index <= stage_index or stage.status == StageStatus.DELETED:
                continue
            if not self._can_unlock_stage(session, stage.index):
                return None
            if stage.status == StageStatus.LOCKED:
                stage.status = StageStatus.AVAILABLE
            return stage
        return None

    def _can_unlock_stage(self, session: ResearchSession, target_index: int) -> bool:
        for stage in session.stages:
            if stage.index >= target_index or stage.status == StageStatus.DELETED:
                continue
            if stage.status not in {StageStatus.COMPLETED, StageStatus.SKIPPED}:
                return False
        return True

    def _next_non_deleted_stage(self, session: ResearchSession, stage_index: int) -> SessionStage | None:
        for stage in session.stages:
            if stage.index > stage_index and stage.status != StageStatus.DELETED:
                return stage
        return None

    def _refresh_active_stage_after_progress(
        self,
        session: ResearchSession,
        next_stage: SessionStage | None,
    ) -> None:
        if next_stage is not None and next_stage.status != StageStatus.DELETED:
            session.active_stage_index = next_stage.index
            next_stage.visited = True
            return
        replacement = self._pick_replacement_active_stage(session, session.active_stage_index)
        session.active_stage_index = replacement.index if replacement is not None else None

    def _pick_replacement_active_stage(
        self,
        session: ResearchSession,
        preferred_index: int | None,
        next_stage: SessionStage | None = None,
    ) -> SessionStage | None:
        if next_stage is not None and next_stage.status != StageStatus.DELETED:
            return next_stage
        if preferred_index is not None:
            for stage in session.stages:
                if stage.index > preferred_index and stage.status not in {StageStatus.DELETED, StageStatus.LOCKED}:
                    return stage
        for stage in reversed(session.stages):
            if (preferred_index is None or stage.index < preferred_index) and stage.status not in {
                StageStatus.DELETED,
                StageStatus.LOCKED,
            }:
                return stage
        return None

    def _mark_following_stages_outdated(self, session: ResearchSession, stage_index: int) -> int:
        count = 0
        for stage in session.stages:
            if stage.index <= stage_index or stage.status in {StageStatus.DELETED, StageStatus.LOCKED}:
                continue
            if stage.document or stage.summary or stage.draft or stage.status in {StageStatus.COMPLETED, StageStatus.SKIPPED}:
                if not stage.is_outdated:
                    count += 1
                stage.is_outdated = True
        return count

    def _mark_stages_outdated_after_changes(
        self,
        session: ResearchSession,
        changed_indexes: list[int],
    ) -> list[int]:
        changed = set(changed_indexes)
        affected: list[int] = []
        for changed_index in sorted(changed_indexes):
            for stage in session.stages:
                if stage.index <= changed_index or stage.index in changed:
                    continue
                if stage.status in {StageStatus.DELETED, StageStatus.LOCKED}:
                    continue
                if stage.document or stage.summary or stage.draft or stage.status in {StageStatus.COMPLETED, StageStatus.SKIPPED}:
                    if not stage.is_outdated:
                        affected.append(stage.index)
                    stage.is_outdated = True
        for stage in session.stages:
            if stage.index in changed:
                stage.is_outdated = False
        return affected

    def _merge_document_metadata(self, stage: SessionStage, updated: dict[str, Any]) -> dict[str, Any]:
        original = stage.document or {
            "stage_index": stage.index,
            "stage_label": stage.label,
            "file_name": updated["file_name"],
            "generated_path": updated["latest_path"],
            "latest_path": updated["latest_path"],
            "generated_text": "",
            "latest_text": "",
            "preview_text": "",
            "is_modified": False,
            "modification_summary": None,
            "source": updated["source"],
            "updated_at": updated["updated_at"],
        }
        generated_text = original.get("generated_text") or original.get("latest_text", "")
        latest_text = updated["latest_text"]
        is_modified = self._documents_are_different(generated_text, latest_text)
        return {
            **original,
            **updated,
            "stage_index": stage.index,
            "stage_label": stage.label,
            "file_name": updated["file_name"],
            "generated_path": original.get("generated_path", updated["latest_path"]),
            "generated_text": generated_text or latest_text,
            "is_modified": is_modified,
            "modification_summary": self._summarize_document_revision(generated_text, latest_text) if is_modified else None,
        }

    def _summarize_document_revision(self, original_text: str, revised_text: str) -> str:
        original_lines = [line.strip() for line in original_text.splitlines() if line.strip()]
        revised_lines = [line.strip() for line in revised_text.splitlines() if line.strip()]
        original_set = set(original_lines)
        revised_set = set(revised_lines)
        added = next((line for line in revised_lines if line not in original_set), "")
        removed = next((line for line in original_lines if line not in revised_set), "")
        if added:
            return f'Added "{self._clip_text(added)}".'
        if removed:
            return f'Reworked "{self._clip_text(removed)}".'
        if SequenceMatcher(None, original_text, revised_text).ratio() < 0.7:
            return "Rewrote most of the section."
        return "Adjusted the wording in the section."

    def _documents_are_different(self, original_text: str, revised_text: str) -> bool:
        return "".join(original_text.split()) != "".join(revised_text.split())

    def _collect_points(self, answers: list[str], latest_input: str | None) -> list[str]:
        points = [item.strip() for item in answers if item and item.strip()]
        if latest_input and latest_input.strip():
            points.append(latest_input.strip())
        return points

    def _teacher_sentence(self, text: str) -> str:
        cleaned = text.strip()
        replacements = (
            ("I plan to ", "The teacher plans to "),
            ("I want to ", "The teacher wants to "),
            ("I will ", "The teacher will "),
            ("I also want to ", "The teacher also wants to "),
            ("I also plan to ", "The teacher also plans to "),
            ("I'm going to ", "The teacher is going to "),
        )
        for source, target in replacements:
            if cleaned.startswith(source):
                cleaned = target + cleaned[len(source):]
                break
        return cleaned if cleaned.endswith((".", "!", "?")) else f"{cleaned}."

    def _clip_text(self, text: str, limit: int = 24) -> str:
        return text if len(text) <= limit else f"{text[:limit]}..."

    def _text_or(self, value: Any, fallback: str) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return fallback

    def _questions_or(self, value: Any, fallback: list[str]) -> list[str]:
        if isinstance(value, list):
            candidates = [str(item).strip() for item in value]
        elif isinstance(value, str):
            candidates = [item.strip() for item in re.split(r"\n+", value)]
            if len([item for item in candidates if item]) < 2:
                candidates = [item.strip() for item in re.findall("[^?\uFF1F]+[?\uFF1F]", value)]
        else:
            candidates = []

        questions = []
        for candidate in candidates:
            cleaned = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", candidate).strip()
            if len(cleaned) < 12:
                continue
            questions.append(cleaned)

        return questions[:2] if len(questions) >= 2 else fallback
