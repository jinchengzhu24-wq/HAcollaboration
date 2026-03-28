from io import BytesIO
from pathlib import Path

from docx import Document
from fastapi.testclient import TestClient

from backend.main import app


def test_stage_document_upload_flow() -> None:
    client = TestClient(app)
    session_id, turn_data = _complete_first_stage(client)

    assert turn_data["awaiting_document_review"] is True
    assert turn_data["current_document"]["download_url"].endswith("/documents/1/download")

    stage_docs_dir = Path("data/stage_docs")
    generated_files = list(stage_docs_dir.glob(f"{session_id}_stage_01_*_generated.docx"))
    assert len(generated_files) == 1
    assert generated_files[0].parent == stage_docs_dir

    download_response = client.get(turn_data["current_document"]["download_url"])
    assert download_response.status_code == 200
    assert download_response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    revised_doc = Document()
    revised_doc.add_heading("Questioning Improvement", level=1)
    revised_doc.add_paragraph("Stage 1: Research Problem")
    revised_doc.add_paragraph("Added a revision about follow-up questioning in reading lessons.")
    buffer = BytesIO()
    revised_doc.save(buffer)
    buffer.seek(0)

    upload_response = client.post(
        f"/dialogue/sessions/{session_id}/documents/1/upload",
        files={
            "file": (
                "stage_1_revised.docx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert upload_response.status_code == 200
    upload_data = upload_response.json()
    assert upload_data["current_document"]["is_modified"] is True
    assert "follow-up questioning" in upload_data["current_document"]["preview_text"]

    revised_files = list(stage_docs_dir.glob(f"{session_id}_stage_01_*_revised.docx"))
    assert len(revised_files) == 1
    assert revised_files[0].parent == stage_docs_dir

    continue_response = client.post(f"/dialogue/sessions/{session_id}/continue")
    assert continue_response.status_code == 200
    continue_data = continue_response.json()
    assert continue_data["message"]
    assert len(continue_data["current_questions"]) == 2


def test_stage_document_editor_flow() -> None:
    client = TestClient(app)
    session_id, turn_data = _complete_first_stage(client)

    edit_response = client.post(
        f"/dialogue/sessions/{session_id}/documents/1/edit",
        json={
            "content": (
                "Questioning Improvement\n"
                "Stage 1: Research Problem\n"
                "The teacher revised the stage draft directly in the browser.\n"
                "A new action point was added for classroom probing questions."
            )
        },
    )
    assert edit_response.status_code == 200
    edit_data = edit_response.json()
    assert edit_data["current_document"]["is_modified"] is True
    assert "directly in the browser" in edit_data["current_document"]["preview_text"]

    stage_docs_dir = Path("data/stage_docs")
    edited_files = list(stage_docs_dir.glob(f"{session_id}_stage_01_*_edited.docx"))
    assert len(edited_files) == 1
    assert edited_files[0].parent == stage_docs_dir

    downloaded = client.get(edit_data["current_document"]["download_url"])
    assert downloaded.status_code == 200
    downloaded_doc = Document(BytesIO(downloaded.content))
    downloaded_text = "\n".join(
        paragraph.text.strip() for paragraph in downloaded_doc.paragraphs if paragraph.text.strip()
    )
    assert "directly in the browser" in downloaded_text
    assert "classroom probing questions" in downloaded_text

    continue_response = client.post(f"/dialogue/sessions/{session_id}/continue")
    assert continue_response.status_code == 200
    continue_data = continue_response.json()
    assert continue_data["message"]
    assert len(continue_data["current_questions"]) == 2


def test_stage_documents_accumulate_across_stages() -> None:
    client = TestClient(app)
    session_id, _ = _complete_first_stage(client)

    continue_response = client.post(f"/dialogue/sessions/{session_id}/continue")
    assert continue_response.status_code == 200

    second_turn_response = client.post(
        f"/dialogue/sessions/{session_id}/turn",
        json={
            "answers": [
                "I plan to model better follow-up prompts during reading discussions.",
                "I will try this first in one grade seven class next week.",
            ],
            "latest_input": "I also want to note how students respond after the prompt change.",
        },
    )
    assert second_turn_response.status_code == 200
    second_turn_data = second_turn_response.json()
    preview_text = second_turn_data["current_document"]["preview_text"]

    assert "Stage 1 -" in preview_text
    assert "Stage 2 -" in preview_text
    assert "grade seven" in preview_text
    assert "follow-up prompts" in preview_text
    assert "\n\nStage 2" in preview_text


def _complete_first_stage(client: TestClient) -> tuple[str, dict]:
    create_response = client.post(
        "/dialogue/sessions",
        json={
            "initial_idea": "I want to improve questioning quality in reading lessons.",
            "project_title": "Questioning Improvement",
        },
    )
    assert create_response.status_code == 200
    session_data = create_response.json()
    session_id = session_data["session_id"]
    assert session_data["stage_documents"] == []
    assert session_data["plan_confirmed"] is True
    assert len(session_data["current_questions"]) == 2
    assert "Stage 1" in session_data["opening_message"]
    assert "Stage 2" not in session_data["opening_message"]

    turn_response = client.post(
        f"/dialogue/sessions/{session_id}/turn",
        json={
            "answers": [
                "Students often give short answers and the discussion stops too early.",
                "I want to begin by redesigning the teacher's follow-up questions.",
            ],
            "latest_input": "The target group is grade seven reading classes.",
        },
    )
    assert turn_response.status_code == 200
    turn_data = turn_response.json()
    assert "AI阶段总结" not in turn_data["current_document"]["preview_text"]
    assert "用户回答" not in turn_data["current_document"]["preview_text"]
    return session_id, turn_data
