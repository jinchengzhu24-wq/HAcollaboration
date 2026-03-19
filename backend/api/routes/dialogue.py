from fastapi import APIRouter, HTTPException

from backend.application.schemas.dialogue import (
    DialogueCreateRequest,
    DialoguePlanRequest,
    DialoguePlanResponse,
    DialogueSessionResponse,
    DialogueStageResponse,
    DialogueTurnRequest,
    DialogueTurnResponse,
)
from backend.application.services.dialogue_service import DialogueService
from backend.infrastructure.repositories.dialogue_repository import InMemoryDialogueRepository

router = APIRouter()

dialogue_service = DialogueService()
dialogue_repository = InMemoryDialogueRepository()


@router.post("/sessions", response_model=DialogueSessionResponse)
def create_dialogue_session(payload: DialogueCreateRequest) -> DialogueSessionResponse:
    project_title = payload.project_title or _default_title(payload.initial_idea)
    session = dialogue_service.create_session(
        project_title=project_title,
        initial_idea=payload.initial_idea,
        teacher_id=payload.teacher_id,
    )
    dialogue_repository.save(session)
    return _build_session_response(session)


@router.get("/sessions/{session_id}", response_model=DialogueSessionResponse)
def get_dialogue_session(session_id: str) -> DialogueSessionResponse:
    session = dialogue_repository.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Dialogue session not found")
    return _build_session_response(session)


@router.post("/sessions/{session_id}/plan", response_model=DialoguePlanResponse)
def update_stage_plan(
    session_id: str,
    payload: DialoguePlanRequest,
) -> DialoguePlanResponse:
    session = dialogue_repository.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Dialogue session not found")

    if payload.confirmed:
        message = dialogue_service.confirm_stage_plan(session)
    else:
        if not payload.adjustment_text or not payload.adjustment_text.strip():
            raise HTTPException(
                status_code=400,
                detail="Adjustment text is required when the stage plan is rejected",
            )
        message = dialogue_service.revise_stage_plan(session, payload.adjustment_text)

    dialogue_repository.save(session)
    return DialoguePlanResponse(
        message=message,
        plan_confirmed=bool(session.state_snapshot.get("plan_confirmed")),
        stage_plan=_serialize_stage_plan(session),
        current_round_label=dialogue_service.get_current_round_label(session),
        remaining_rounds=dialogue_service.remaining_rounds(session),
        current_questions=dialogue_service.get_current_questions(session),
    )


@router.post("/sessions/{session_id}/turn", response_model=DialogueTurnResponse)
def advance_dialogue(
    session_id: str,
    payload: DialogueTurnRequest,
) -> DialogueTurnResponse:
    session = dialogue_repository.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Dialogue session not found")
    if not session.state_snapshot.get("plan_confirmed"):
        raise HTTPException(status_code=400, detail="Please confirm the stage plan first")

    reply = dialogue_service.advance_session(
        session=session,
        answers=payload.answers,
        latest_input=payload.latest_input,
    )
    dialogue_repository.save(session)
    next_round_label = (
        "已完成所有轮次"
        if reply.is_complete
        else dialogue_service.get_current_round_label(session)
    )
    return DialogueTurnResponse(
        message=reply.message,
        stage_feedback=reply.stage_feedback,
        guidance=reply.guidance,
        draft=reply.draft,
        next_questions=reply.next_questions,
        current_round_label=next_round_label,
        remaining_rounds=reply.remaining_rounds,
        is_complete=reply.is_complete,
        final_summary=reply.final_summary,
    )


def _build_session_response(session) -> DialogueSessionResponse:
    return DialogueSessionResponse(
        session_id=session.session_id,
        llm_status=dialogue_service.llm_status_text(),
        opening_message=dialogue_service.build_opening_message(session),
        plan_confirmed=bool(session.state_snapshot.get("plan_confirmed")),
        stage_plan=_serialize_stage_plan(session),
        current_round_label=dialogue_service.get_current_round_label(session),
        remaining_rounds=dialogue_service.remaining_rounds(session),
        current_questions=dialogue_service.get_current_questions(session),
        is_complete=False,
        final_summary=None,
    )


def _serialize_stage_plan(session) -> list[DialogueStageResponse]:
    plan = session.state_snapshot.get("stage_plan", [])
    return [
        DialogueStageResponse(
            index=index,
            label=stage["label"],
            reason=stage["reason"],
        )
        for index, stage in enumerate(plan, start=1)
    ]


def _default_title(initial_idea: str) -> str:
    shortened = initial_idea.strip().replace("\n", " ")
    if len(shortened) <= 18:
        return shortened
    return f"{shortened[:18]}..."
