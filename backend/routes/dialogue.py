from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from backend.models.session import StageStatus
from backend.repositories.dialogue_repository import InMemoryDialogueRepository
from backend.schemas.dialogue import (
    DialogueCidaModeRequest,
    DialogueCombinedDocumentEditRequest,
    DialogueCreateRequest,
    DialogueDocumentEditRequest,
    DialogueDocumentResponse,
    DialogueSessionResponse,
    DialogueStageResponse,
    DialogueTurnRequest,
)
from backend.services.dialogue_service import DialogueService

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
        cida_enabled=payload.cida_enabled,
    )
    dialogue_repository.save(session)
    return _build_session_response(session)


@router.get("/sessions/{session_id}", response_model=DialogueSessionResponse)
def get_dialogue_session(session_id: str) -> DialogueSessionResponse:
    session = _get_session_or_404(session_id)
    return _build_session_response(session)


@router.post("/sessions/{session_id}/cida", response_model=DialogueSessionResponse)
def set_cida_mode(session_id: str, payload: DialogueCidaModeRequest) -> DialogueSessionResponse:
    session = _get_session_or_404(session_id)
    message = dialogue_service.set_cida_mode(session, payload.enabled)
    dialogue_repository.save(session)
    return _build_session_response(session, message=message)


@router.post("/sessions/{session_id}/stages/{stage_index}/activate", response_model=DialogueSessionResponse)
def activate_stage(session_id: str, stage_index: int) -> DialogueSessionResponse:
    session = _get_session_or_404(session_id)
    try:
        message = dialogue_service.activate_stage(session, stage_index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dialogue_repository.save(session)
    return _build_session_response(session, message=message)


@router.post("/sessions/{session_id}/stages/{stage_index}/turn", response_model=DialogueSessionResponse)
def turn_stage(
    session_id: str,
    stage_index: int,
    payload: DialogueTurnRequest,
) -> DialogueSessionResponse:
    session = _get_session_or_404(session_id)
    try:
        message = dialogue_service.turn_stage(session, stage_index, payload.answers, payload.latest_input)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dialogue_repository.save(session)
    return _build_session_response(session, message=message)


@router.post("/sessions/{session_id}/stages/{stage_index}/confirm", response_model=DialogueSessionResponse)
def confirm_stage(session_id: str, stage_index: int) -> DialogueSessionResponse:
    session = _get_session_or_404(session_id)
    try:
        message = dialogue_service.confirm_stage(session, stage_index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dialogue_repository.save(session)
    return _build_session_response(session, message=message)


@router.post("/sessions/{session_id}/stages/{stage_index}/skip", response_model=DialogueSessionResponse)
def skip_stage(session_id: str, stage_index: int) -> DialogueSessionResponse:
    session = _get_session_or_404(session_id)
    try:
        message = dialogue_service.skip_stage(session, stage_index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dialogue_repository.save(session)
    return _build_session_response(session, message=message)


@router.post("/sessions/{session_id}/stages/{stage_index}/delete", response_model=DialogueSessionResponse)
def delete_stage(session_id: str, stage_index: int) -> DialogueSessionResponse:
    session = _get_session_or_404(session_id)
    try:
        message = dialogue_service.delete_stage(session, stage_index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dialogue_repository.save(session)
    return _build_session_response(session, message=message)


@router.post("/sessions/{session_id}/stages/{stage_index}/review", response_model=DialogueSessionResponse)
def review_stage(session_id: str, stage_index: int) -> DialogueSessionResponse:
    session = _get_session_or_404(session_id)
    try:
        message = dialogue_service.review_stage(session, stage_index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dialogue_repository.save(session)
    return _build_session_response(session, message=message)


@router.post("/sessions/{session_id}/stages/{stage_index}/regenerate", response_model=DialogueSessionResponse)
def regenerate_stage(session_id: str, stage_index: int) -> DialogueSessionResponse:
    session = _get_session_or_404(session_id)
    try:
        message = dialogue_service.regenerate_stage(session, stage_index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dialogue_repository.save(session)
    return _build_session_response(session, message=message)


@router.post("/sessions/{session_id}/document/edit", response_model=DialogueSessionResponse)
def edit_combined_document(
    session_id: str,
    payload: DialogueCombinedDocumentEditRequest,
) -> DialogueSessionResponse:
    session = _get_session_or_404(session_id)
    try:
        message = dialogue_service.edit_combined_document(session, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dialogue_repository.save(session)
    return _build_session_response(session, message=message)


@router.post("/sessions/{session_id}/document/save", response_model=DialogueSessionResponse)
def save_combined_document(
    session_id: str,
    payload: DialogueCombinedDocumentEditRequest,
) -> DialogueSessionResponse:
    session = _get_session_or_404(session_id)
    try:
        edit_message = dialogue_service.edit_combined_document(session, payload.content)
        save_path = dialogue_service.save_combined_document_to_desktop(session)
        message = f"{edit_message} Saved a copy to {save_path}."
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dialogue_repository.save(session)
    return _build_session_response(session, message=message)


@router.post(
    "/sessions/{session_id}/stages/{stage_index}/document/edit",
    response_model=DialogueSessionResponse,
)
def edit_stage_document(
    session_id: str,
    stage_index: int,
    payload: DialogueDocumentEditRequest,
) -> DialogueSessionResponse:
    session = _get_session_or_404(session_id)
    try:
        message = dialogue_service.edit_stage_document(session, stage_index, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dialogue_repository.save(session)
    return _build_session_response(session, message=message)


@router.post(
    "/sessions/{session_id}/stages/{stage_index}/document/upload",
    response_model=DialogueSessionResponse,
)
async def upload_stage_document(
    session_id: str,
    stage_index: int,
    file: UploadFile = File(...),
) -> DialogueSessionResponse:
    session = _get_session_or_404(session_id)
    filename = file.filename or ""
    if not filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Please upload a .docx file.")
    file_bytes = await file.read()
    try:
        message = dialogue_service.upload_stage_document(session, stage_index, file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dialogue_repository.save(session)
    return _build_session_response(session, message=message)


@router.get("/sessions/{session_id}/stages/{stage_index}/document/download")
def download_stage_document(session_id: str, stage_index: int) -> FileResponse:
    session = _get_session_or_404(session_id)
    try:
        stage = dialogue_service.get_stage(session, stage_index)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if stage.document is None:
        raise HTTPException(status_code=404, detail="Stage document not found.")
    path = dialogue_service.document_service.download_path(stage.document)
    return FileResponse(path, filename=stage.document["file_name"])


def _build_session_response(session, message: str | None = None) -> DialogueSessionResponse:
    active_stage = dialogue_service.get_active_stage(session)
    current_questions = dialogue_service.get_current_questions(session)
    return DialogueSessionResponse(
        session_id=session.session_id,
        project_title=session.project_title,
        llm_status=dialogue_service.llm_status_text(),
        opening_message=dialogue_service.build_opening_message(session),
        current_round_label=dialogue_service.get_current_round_label(session),
        current_questions=current_questions,
        active_stage_index=active_stage.index if active_stage is not None else None,
        cida_enabled=dialogue_service.is_cida_enabled(session),
        is_complete=dialogue_service.is_complete(session),
        message=message,
        combined_document=dialogue_service.build_combined_document(session),
        stages=[_serialize_stage(session, stage) for stage in session.stages],
    )


def _serialize_stage(session, stage) -> DialogueStageResponse:
    return DialogueStageResponse(
        index=stage.index,
        focus=stage.focus.value,
        label=stage.label,
        reason=stage.reason,
        status=stage.status.value,
        is_active=session.active_stage_index == stage.index,
        is_outdated=stage.is_outdated,
        needs_confirmation=stage.needs_confirmation,
        can_activate=stage.status not in {StageStatus.LOCKED, StageStatus.DELETED},
        can_confirm=stage.needs_confirmation and stage.status == StageStatus.AVAILABLE,
        can_skip=stage.status == StageStatus.AVAILABLE,
        can_delete=stage.status != StageStatus.DELETED,
        can_review=stage.is_outdated,
        can_regenerate=bool(stage.document or stage.latest_answers or stage.latest_input or stage.draft),
        questions=list(stage.questions),
        draft=stage.draft,
        summary=stage.summary,
        feedback=stage.feedback,
        guidance=stage.guidance,
        latest_answers=list(stage.latest_answers),
        latest_input=stage.latest_input,
        document=_serialize_document(stage.document, session.session_id),
        cida_guidance=dialogue_service.get_cida_guidance(session, stage),
    )


def _serialize_document(document: dict | None, session_id: str) -> DialogueDocumentResponse | None:
    if document is None:
        return None
    return DialogueDocumentResponse(
        stage_index=document["stage_index"],
        stage_label=document["stage_label"],
        file_name=document["file_name"],
        download_url=f"/dialogue/sessions/{session_id}/stages/{document['stage_index']}/document/download",
        source=document.get("source", "generated"),
        preview_text=document.get("preview_text", ""),
        is_modified=bool(document.get("is_modified")),
        modification_summary=document.get("modification_summary"),
        updated_at=document.get("updated_at"),
    )


def _get_session_or_404(session_id: str):
    session = dialogue_repository.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Dialogue session not found.")
    return session


def _default_title(initial_idea: str) -> str:
    shortened = initial_idea.strip().replace("\n", " ")
    return shortened if len(shortened) <= 24 else f"{shortened[:24]}..."
