from io import BytesIO
from pathlib import Path

from docx import Document
from fastapi.testclient import TestClient

from backend.main import app


def test_car_stage_plan_is_returned_on_create() -> None:
    client = TestClient(app)

    response = client.post(
        "/dialogue/sessions",
        json={
            "initial_idea": "I want to improve questioning quality in reading lessons.",
            "project_title": "Questioning Improvement",
        },
    )
    assert response.status_code == 200

    payload = response.json()
    stages = payload["stages"]
    assert len(stages) == 4
    assert payload["active_stage_index"] == 1
    assert payload["current_questions"]
    assert stages[0]["status"] == "available"
    assert stages[0]["is_active"] is True
    assert stages[1]["status"] == "locked"
    assert stages[2]["status"] == "locked"
    assert stages[3]["status"] == "locked"
    assert "Stage 1: Problem Framing" in payload["combined_document"]
    assert "Stage 4: Reflection and Iteration" in payload["combined_document"]


def test_locked_stage_requires_confirm_or_skip_before_unlock() -> None:
    client = TestClient(app)
    session_id = _create_session(client)

    locked_response = client.post(f"/dialogue/sessions/{session_id}/stages/2/activate")
    assert locked_response.status_code == 400

    turn_response = client.post(
        f"/dialogue/sessions/{session_id}/stages/1/turn",
        json={
            "answers": [
                "Students often give short answers and the discussion stops too early.",
                "I want to redesign the teacher's follow-up questions.",
            ],
            "latest_input": "The target group is grade seven reading classes.",
        },
    )
    assert turn_response.status_code == 200
    turn_payload = turn_response.json()
    assert turn_payload["stages"][0]["needs_confirmation"] is True

    confirm_response = client.post(f"/dialogue/sessions/{session_id}/stages/1/confirm")
    assert confirm_response.status_code == 200
    confirm_payload = confirm_response.json()
    assert confirm_payload["active_stage_index"] == 2
    assert confirm_payload["stages"][0]["status"] == "completed"
    assert confirm_payload["stages"][1]["status"] == "available"

    delete_response = client.post(f"/dialogue/sessions/{session_id}/stages/2/delete")
    assert delete_response.status_code == 200
    delete_payload = delete_response.json()
    assert delete_payload["stages"][1]["status"] == "deleted"
    assert delete_payload["stages"][2]["status"] == "available"
    assert delete_payload["active_stage_index"] == 3


def test_deleting_a_future_stage_does_not_unlock_later_stages_too_early() -> None:
    client = TestClient(app)
    session_id = _create_session(client)

    _turn_and_confirm_stage(
        client,
        session_id,
        1,
        [
            "Students often give short answers and the discussion stops too early.",
            "I want to redesign the teacher's follow-up questions.",
        ],
        "The target group is grade seven reading classes.",
    )

    delete_response = client.post(f"/dialogue/sessions/{session_id}/stages/3/delete")
    assert delete_response.status_code == 200
    delete_payload = delete_response.json()
    assert delete_payload["active_stage_index"] == 2
    assert delete_payload["stages"][1]["status"] == "available"
    assert delete_payload["stages"][2]["status"] == "deleted"
    assert delete_payload["stages"][3]["status"] == "locked"


def test_jumping_back_marks_later_stage_outdated_and_confirm_returns_to_current_stage() -> None:
    client = TestClient(app)
    session_id = _create_session(client)

    _turn_and_confirm_stage(
        client,
        session_id,
        1,
        [
            "Students often give short answers and the discussion stops too early.",
            "I want to redesign the teacher's follow-up questions.",
        ],
        "The target group is grade seven reading classes.",
    )
    _turn_and_confirm_stage(
        client,
        session_id,
        2,
        [
            "I plan to model better follow-up prompts during reading discussions.",
            "I will try this first in one grade seven class next week.",
        ],
        "I also want to keep the steps manageable for the first trial.",
    )

    jump_response = client.post(f"/dialogue/sessions/{session_id}/stages/1/activate")
    assert jump_response.status_code == 200
    jump_payload = jump_response.json()
    assert jump_payload["active_stage_index"] == 1
    assert jump_payload["stages"][1]["is_outdated"] is True

    confirm_response = client.post(f"/dialogue/sessions/{session_id}/stages/1/confirm")
    assert confirm_response.status_code == 200
    confirm_payload = confirm_response.json()
    assert confirm_payload["active_stage_index"] == 3


def test_combined_document_edit_marks_later_stage_outdated_until_reviewed() -> None:
    client = TestClient(app)
    session_id = _create_session(client)

    _turn_and_confirm_stage(
        client,
        session_id,
        1,
        [
            "Students often give short answers and the discussion stops too early.",
            "I want to redesign the teacher's follow-up questions.",
        ],
        "The target group is grade seven reading classes.",
    )
    _turn_and_confirm_stage(
        client,
        session_id,
        2,
        [
            "I plan to model better follow-up prompts during reading discussions.",
            "I will try this first in one grade seven class next week.",
        ],
        "I also want to keep the steps manageable for the first trial.",
    )

    session_response = client.get(f"/dialogue/sessions/{session_id}")
    assert session_response.status_code == 200
    combined_document = session_response.json()["combined_document"]
    revised_document = combined_document.replace(
        "Stage 1: Problem Framing\n",
        (
            "Stage 1: Problem Framing\n"
            "The teacher refined the problem statement around follow-up questioning.\n"
            "The revised focus is on extending student talk in grade seven reading lessons."
        ),
        1,
    )

    edit_response = client.post(
        f"/dialogue/sessions/{session_id}/document/edit",
        json={"content": revised_document},
    )
    assert edit_response.status_code == 200
    edit_payload = edit_response.json()
    assert edit_payload["stages"][0]["status"] == "completed"
    assert edit_payload["stages"][1]["is_outdated"] is True
    assert (
        "The teacher refined the problem statement around follow-up questioning."
        in edit_payload["combined_document"]
    )

    review_response = client.post(f"/dialogue/sessions/{session_id}/stages/2/review")
    assert review_response.status_code == 200
    review_payload = review_response.json()
    assert review_payload["stages"][1]["is_outdated"] is False


def test_stage_document_upload_and_download_flow() -> None:
    client = TestClient(app)
    session_id = _create_session(client)

    turn_response = client.post(
        f"/dialogue/sessions/{session_id}/stages/1/turn",
        json={
            "answers": [
                "Students often give short answers and the discussion stops too early.",
                "I want to redesign the teacher's follow-up questions.",
            ],
            "latest_input": "The target group is grade seven reading classes.",
        },
    )
    assert turn_response.status_code == 200
    turn_payload = turn_response.json()
    stage_one = turn_payload["stages"][0]
    download_url = stage_one["document"]["download_url"]
    assert "System Feedback:" in stage_one["document"]["preview_text"]
    assert "Next Step:" in stage_one["document"]["preview_text"]
    assert "Current Questions:" in stage_one["document"]["preview_text"]

    download_response = client.get(download_url)
    assert download_response.status_code == 200
    assert download_response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    revised_doc = Document()
    revised_doc.add_heading("Questioning Improvement", level=1)
    revised_doc.add_paragraph("Stage 1: Problem Framing")
    revised_doc.add_paragraph("Added a revision about follow-up questioning in reading lessons.")
    buffer = BytesIO()
    revised_doc.save(buffer)
    buffer.seek(0)

    upload_response = client.post(
        f"/dialogue/sessions/{session_id}/stages/1/document/upload",
        files={
            "file": (
                "stage_1_revised.docx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert upload_response.status_code == 200
    upload_payload = upload_response.json()
    document = upload_payload["stages"][0]["document"]
    assert document["is_modified"] is True
    assert "follow-up questioning" in document["preview_text"]


def test_save_document_exports_a_copy_to_desktop() -> None:
    client = TestClient(app)
    session_id = _create_session(client)

    turn_response = client.post(
        f"/dialogue/sessions/{session_id}/stages/1/turn",
        json={
            "answers": [
                "Students often give short answers and the discussion stops too early.",
                "I want to redesign the teacher's follow-up questions.",
            ],
            "latest_input": "The target group is grade seven reading classes.",
        },
    )
    assert turn_response.status_code == 200
    combined_document = client.get(f"/dialogue/sessions/{session_id}").json()["combined_document"]

    save_response = client.post(
        f"/dialogue/sessions/{session_id}/document/save",
        json={"content": combined_document},
    )
    assert save_response.status_code == 200
    message = save_response.json()["message"]
    assert "Saved a copy to" in message

    save_path = Path(message.split("Saved a copy to ", 1)[1].rstrip("."))
    assert save_path.exists()


def _create_session(client: TestClient) -> str:
    response = client.post(
        "/dialogue/sessions",
        json={
            "initial_idea": "I want to improve questioning quality in reading lessons.",
            "project_title": "Questioning Improvement",
        },
    )
    assert response.status_code == 200
    return response.json()["session_id"]


def _turn_and_confirm_stage(
    client: TestClient,
    session_id: str,
    stage_index: int,
    answers: list[str],
    latest_input: str | None,
) -> None:
    turn_response = client.post(
        f"/dialogue/sessions/{session_id}/stages/{stage_index}/turn",
        json={
            "answers": answers,
            "latest_input": latest_input,
        },
    )
    assert turn_response.status_code == 200

    confirm_response = client.post(f"/dialogue/sessions/{session_id}/stages/{stage_index}/confirm")
    assert confirm_response.status_code == 200
