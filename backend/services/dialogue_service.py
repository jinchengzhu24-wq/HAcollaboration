from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any
from uuid import uuid4

from backend.clients.deepseek_client import DeepSeekClient
from backend.config import get_settings
from backend.models.session import FocusArea, ResearchCycleStage, ResearchSession, SessionStage, StageStatus
from backend.services.document_service import StageDocumentService
from backend.services.prioritization import PrioritizationService


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
        stages = [
            SessionStage(
                index=index,
                label=str(stage["label"]),
                reason=str(stage["reason"]),
                focus=stage["focus"],
                questions=self.prioritization_service.default_questions(stage["focus"]),
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
                "initial_idea": initial_idea.strip(),
                "opening_message": (
                    f"Starting point captured: {initial_idea.strip()}\n\n"
                    "The workspace now shows all four CAR stages at once. "
                    "Only the current stage can unlock the next one, but you can revisit any available stage at any time. "
                    "Use `delete stage 2` in chat if you want to remove a stage entirely."
                ),
            },
        )

    def llm_status_text(self) -> str:
        return "DeepSeek connected" if self.deepseek_client is not None else "Fallback mode"

    def build_opening_message(self, session: ResearchSession) -> str:
        return str(session.state_snapshot.get("opening_message", ""))

    def build_combined_document(self, session: ResearchSession) -> str:
        sections = []
        for stage in session.stages:
            if stage.status == StageStatus.DELETED:
                continue
            draft, guidance = self._editable_parts(stage.draft or self._current_stage_body(session, stage), stage.guidance)
            parts = [
                f"Stage {stage.index}: {stage.label}",
                "Working Draft:",
                draft or "This stage still needs more detail.",
            ]
            if guidance:
                parts.extend(["Next Step:", guidance])
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

    def regenerate_stage(self, session: ResearchSession, stage_index: int) -> str:
        stage = self.get_stage(session, stage_index)
        if stage.status in {StageStatus.LOCKED, StageStatus.DELETED}:
            raise ValueError("This stage cannot be regenerated.")
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
            new_body = updates[stage.index]
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
                "guidance": stage.guidance or "",
                "questions": list(stage.questions),
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
            self.prioritization_service.focus_guidance(stage.focus),
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
                payload = self.deepseek_client.generate_json(
                    system_prompt=(
                        "You are a concise classroom action research assistant. "
                        "Return JSON with keys summary, feedback, guidance, draft."
                    ),
                    user_prompt=self._build_llm_prompt(session, stage, answers, latest_input),
                )
                return {
                    "summary": self._text_or(payload.get("summary"), self._fallback_summary(stage, answers, latest_input)),
                    "feedback": self._text_or(payload.get("feedback"), self._fallback_feedback(stage)),
                    "guidance": self._text_or(payload.get("guidance"), self.prioritization_service.focus_guidance(stage.focus)),
                    "draft": self._text_or(payload.get("draft"), self._fallback_draft(stage, answers, latest_input)),
                }
            except Exception:
                pass

        return {
            "summary": self._fallback_summary(stage, answers, latest_input),
            "feedback": self._fallback_feedback(stage),
            "guidance": self.prioritization_service.focus_guidance(stage.focus),
            "draft": self._fallback_draft(stage, answers, latest_input),
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
        return (
            f"Project title: {session.project_title}\n"
            f"Initial idea: {session.state_snapshot.get('initial_idea', '')}\n"
            f"Current stage: Stage {stage.index} {stage.label}\n"
            f"Stage purpose: {stage.reason}\n"
            f"Teacher input:\n{teacher_input or '- None'}\n"
            f"Previous stage content:\n{previous_text}"
        )

    def _fallback_summary(self, stage: SessionStage, answers: list[str], latest_input: str | None) -> str:
        points = self._collect_points(answers, latest_input)
        if not points:
            return f"{stage.label}: more detail is still needed."
        lead = " ".join(points[:2])
        return f"{stage.label}: {lead}"

    def _fallback_feedback(self, stage: SessionStage) -> str:
        mapping = {
            FocusArea.PROBLEM_FRAMING: "Keep narrowing the problem until it is observable and researchable.",
            FocusArea.ACTION_DESIGN: "Make the first-round action concrete enough to run in a real class soon.",
            FocusArea.OBSERVATION_EVIDENCE: "Keep the evidence plan manageable but specific.",
            FocusArea.REFLECTION_ITERATION: "Separate confirmed gains, unresolved issues, and next-step revisions.",
        }
        return mapping[stage.focus]

    def _fallback_draft(self, stage: SessionStage, answers: list[str], latest_input: str | None) -> str:
        points = self._collect_points(answers, latest_input)
        defaults = {
            FocusArea.PROBLEM_FRAMING: [
                "The classroom problem still needs to be clarified.",
                "The teacher wants to narrow the problem to one visible classroom change.",
            ],
            FocusArea.ACTION_DESIGN: [
                "The teacher will try a focused classroom action.",
                "The first trial will be scheduled in one specific class and time slot.",
            ],
            FocusArea.OBSERVATION_EVIDENCE: [
                "The teacher will collect evidence from classroom observations and learner responses.",
                "The teacher will record the most visible changes during implementation.",
            ],
            FocusArea.REFLECTION_ITERATION: [
                "The teacher will reflect on what worked and what still needs adjustment.",
                "The next cycle will keep the strongest actions and revise weaker points.",
            ],
        }
        chosen = points[:3] if points else defaults[stage.focus]
        return " ".join(self._teacher_sentence(item) for item in chosen if item.strip())

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
            self.prioritization_service.focus_guidance(stage.focus),
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
        cleaned = re.split(r"\n\s*(?:System Feedback:|Current Questions:)\s*\n", cleaned, maxsplit=1)[0]
        cleaned = re.sub(r"^Working Draft:\s*", "", cleaned, flags=re.IGNORECASE)
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

    def _build_stage_guidance(
        self,
        session: ResearchSession,
        stage: SessionStage,
        base_guidance: str,
    ) -> str:
        next_stage = self._next_non_deleted_stage(session, stage.index)
        if next_stage is None:
            decision = "You can keep refining this stage, or confirm it to finish the CAR sequence."
        else:
            decision = (
                f"You can keep refining this stage, or confirm or skip it to move into "
                f"Stage {next_stage.index}: {next_stage.label}."
            )
        return f"{base_guidance} {decision}".strip()

    def _build_turn_message(
        self,
        session: ResearchSession,
        stage: SessionStage,
        outdated_count: int,
    ) -> str:
        sections = [
            f"Stage {stage.index} feedback: {stage.feedback}",
            f"Next step: {stage.guidance}",
        ]
        if outdated_count:
            sections.append(
                f"{outdated_count} later stage(s) are now marked outdated and should be reviewed."
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
            return f"Added “{self._clip_text(added)}”."
        if removed:
            return f"Reworked “{self._clip_text(removed)}”."
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
