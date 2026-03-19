from fastapi import APIRouter, HTTPException

from backend.application.schemas.session import (
    SessionAdvanceRequest,
    SessionCreateRequest,
    SessionResponse,
)
from backend.application.services.orchestration_service import orchestration_service

router = APIRouter()


@router.post("", response_model=SessionResponse)
def create_session(payload: SessionCreateRequest) -> SessionResponse:
    return orchestration_service.create_session(payload)


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: str) -> SessionResponse:
    session = orchestration_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/{session_id}/advance", response_model=SessionResponse)
def advance_session(
    session_id: str,
    payload: SessionAdvanceRequest,
) -> SessionResponse:
    session = orchestration_service.advance_session(session_id, payload)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session
