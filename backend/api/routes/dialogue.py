from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from backend.application.schemas.dialogue import (
    DialogueContinueResponse,
    DialogueCreateRequest,
    DialogueDocumentEditRequest,
    DialogueDocumentResponse,
    DialogueDocumentUploadResponse,
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
    session = _get_session_or_404(session_id)
    return _build_session_response(session)


@router.post("/sessions/{session_id}/plan", response_model=DialoguePlanResponse)
def update_stage_plan(session_id: str, payload: DialoguePlanRequest) -> DialoguePlanResponse:
    session = _get_session_or_404(session_id)
    if payload.confirmed:
        message = dialogue_service.confirm_stage_plan(session)
    else:
        if not payload.adjustment_text or not payload.adjustment_text.strip():
            raise HTTPException(status_code=400, detail="Adjustment text is required when the plan is rejected")
        message = dialogue_service.revise_stage_plan(session, payload.adjustment_text)
    dialogue_repository.save(session)
    return DialoguePlanResponse(
        message=message,
        plan_confirmed=bool(session.state_snapshot.get("plan_confirmed")),
        stage_plan=_serialize_stage_plan(session),
        current_round_label=dialogue_service.get_current_round_label(session),
        remaining_rounds=dialogue_service.remaining_rounds(session),
        current_questions=dialogue_service.get_current_questions(session),
        awaiting_document_review=bool(session.state_snapshot.get("awaiting_document_review")),
        active_stage_number=dialogue_service.active_stage_number(session),
        completed_stage_count=dialogue_service.completed_stage_count(session),
        current_document=_serialize_document(dialogue_service.get_latest_document(session), session.session_id),
        stage_documents=_serialize_documents(session),
    )


@router.post("/sessions/{session_id}/turn", response_model=DialogueTurnResponse)
def advance_dialogue(session_id: str, payload: DialogueTurnRequest) -> DialogueTurnResponse:
    session = _get_session_or_404(session_id)
    try:
        reply = dialogue_service.advance_session(session, payload.answers, payload.latest_input)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dialogue_repository.save(session)
    return DialogueTurnResponse(
        message=reply.message,
        stage_feedback=reply.stage_feedback,
        guidance=reply.guidance,
        draft=reply.draft,
        next_questions=reply.next_questions,
        current_round_label=dialogue_service.get_current_round_label(session),
        remaining_rounds=reply.remaining_rounds,
        awaiting_document_review=reply.awaiting_document_review,
        active_stage_number=reply.active_stage_number,
        completed_stage_count=reply.completed_stage_count,
        current_document=_serialize_document(reply.current_document, session.session_id),
        stage_documents=[_serialize_document(item, session.session_id) for item in reply.stage_documents],
        is_complete=reply.is_complete,
        final_summary=reply.final_summary,
    )


@router.post("/sessions/{session_id}/continue", response_model=DialogueContinueResponse)
def continue_to_next_stage(session_id: str) -> DialogueContinueResponse:
    session = _get_session_or_404(session_id)
    try:
        payload = dialogue_service.continue_to_next_stage(session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dialogue_repository.save(session)
    return DialogueContinueResponse(
        message=payload["message"],
        current_round_label=dialogue_service.get_current_round_label(session),
        remaining_rounds=dialogue_service.remaining_rounds(session),
        current_questions=payload["current_questions"],
        awaiting_document_review=bool(session.state_snapshot.get("awaiting_document_review")),
        active_stage_number=dialogue_service.active_stage_number(session),
        completed_stage_count=dialogue_service.completed_stage_count(session),
        current_document=_serialize_document(dialogue_service.get_latest_document(session), session.session_id),
        stage_documents=_serialize_documents(session),
    )


@router.post(
    "/sessions/{session_id}/documents/{stage_index}/upload",
    response_model=DialogueDocumentUploadResponse,
)
async def upload_stage_document(
    session_id: str,
    stage_index: int,
    file: UploadFile = File(...),
) -> DialogueDocumentUploadResponse:
    session = _get_session_or_404(session_id)
    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Please upload a .docx file")
    file_bytes = await file.read()
    try:
        metadata = dialogue_service.upload_stage_document(session, stage_index, file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dialogue_repository.save(session)
    message = "The uploaded revision has been read."
    if metadata.get("is_modified"):
        message = f"{message} The next stage will use these updates."
    return DialogueDocumentUploadResponse(
        message=message,
        current_document=_serialize_document(metadata, session.session_id),
        stage_documents=_serialize_documents(session),
    )


@router.post(
    "/sessions/{session_id}/documents/{stage_index}/edit",
    response_model=DialogueDocumentUploadResponse,
)
def edit_stage_document(
    session_id: str,
    stage_index: int,
    payload: DialogueDocumentEditRequest,
) -> DialogueDocumentUploadResponse:
    session = _get_session_or_404(session_id)
    try:
        metadata = dialogue_service.edit_stage_document(session, stage_index, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dialogue_repository.save(session)
    message = "The editor changes have been saved."
    if metadata.get("is_modified"):
        message = f"{message} The next stage will use this revised content."
    return DialogueDocumentUploadResponse(
        message=message,
        current_document=_serialize_document(metadata, session.session_id),
        stage_documents=_serialize_documents(session),
    )


@router.get("/sessions/{session_id}/documents/{stage_index}/download")
def download_stage_document(session_id: str, stage_index: int) -> FileResponse:
    session = _get_session_or_404(session_id)
    metadata = session.state_snapshot.get("stage_documents", {}).get(str(stage_index))
    if metadata is None:
        raise HTTPException(status_code=404, detail="Stage document not found")
    path = dialogue_service.document_service.download_path(metadata)
    return FileResponse(path, filename=metadata["file_name"])


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
        awaiting_document_review=bool(session.state_snapshot.get("awaiting_document_review")),
        active_stage_number=dialogue_service.active_stage_number(session),
        completed_stage_count=dialogue_service.completed_stage_count(session),
        current_document=_serialize_document(dialogue_service.get_latest_document(session), session.session_id),
        stage_documents=_serialize_documents(session),
        is_complete=bool(session.state_snapshot.get("is_complete")),
        final_summary=None,
    )


def _serialize_stage_plan(session) -> list[DialogueStageResponse]:
    return [
        DialogueStageResponse(index=index, label=stage["label"], reason=stage["reason"])
        for index, stage in enumerate(session.state_snapshot.get("stage_plan", []), start=1)
    ]


def _serialize_documents(session) -> list[DialogueDocumentResponse]:
    return [_serialize_document(item, session.session_id) for item in dialogue_service.list_stage_documents(session)]


def _serialize_document(document: dict | None, session_id: str) -> DialogueDocumentResponse | None:
    if document is None:
        return None
    return DialogueDocumentResponse(
        stage_index=document["stage_index"],
        stage_label=document["stage_label"],
        file_name=document["file_name"],
        download_url=f"/dialogue/sessions/{session_id}/documents/{document['stage_index']}/download",
        source=document.get("source", "generated"),
        preview_text=document.get("preview_text", ""),
        is_modified=bool(document.get("is_modified")),
        modification_summary=document.get("modification_summary"),
        updated_at=document.get("updated_at"),
    )


def _get_session_or_404(session_id: str):
    session = dialogue_repository.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Dialogue session not found")
    return session


def _default_title(initial_idea: str) -> str:
    shortened = initial_idea.strip().replace("\n", " ")
    return shortened if len(shortened) <= 18 else f"{shortened[:18]}..."
