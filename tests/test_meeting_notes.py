import app.services.meeting_processing_service as meeting_processing_service_module
from app.ai.provider import AIExtractionError
from fastapi.testclient import TestClient


def test_auth_is_required(client_app: TestClient) -> None:
    response = client_app.get("/api/v1/clients")

    assert response.status_code == 401


def test_process_clear_client_note_updates_memory(
    client_app: TestClient, api_headers: dict[str, str]
) -> None:
    response = client_app.post(
        "/api/v1/meeting-notes/process",
        headers=api_headers,
        json={
            "raw_notes": (
                "Met Rajesh Sharma today. Interested in business loan. "
                "Concerned about processing time. Promised documents by Friday."
            ),
            "meeting_date": "2026-06-19",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["client_status"] == "created"
    assert payload["requires_client_confirmation"] is False
    assert payload["client_id"] == 1
    assert payload["meeting"]["status"] == "processed"
    assert payload["extraction"]["client_identification"]["status"] == "created"
    assert payload["extraction"]["key_discussion_points"] != []
    assert payload["extraction"]["concerns"][0]["description"] == "processing time"
    assert payload["extraction"]["action_items"] == ["Send documents"]
    assert len(payload["commitments_created"]) == 1
    assert payload["commitments_created"][0]["description"] == "Send documents"
    assert payload["commitments_created"][0]["due_date"] == "2026-06-26"

    memory = client_app.get("/api/v1/clients/1/memory", headers=api_headers)
    assert memory.status_code == 200
    memory_payload = memory.json()
    assert memory_payload["client_name"] == "Rajesh Sharma"
    assert memory_payload["last_meeting_summary"] == (
        "Rajesh Sharma discussed a business loan. "
        "Rajesh Sharma expressed concerns about processing time. "
        "One follow-up commitment was created: Send documents by Friday."
    )
    assert (
        memory_payload["rolling_summary"]
        == "Rajesh Sharma discussed a business loan. Rajesh Sharma expressed concerns about processing time. One follow-up commitment was created: Send documents by Friday. Tracked products include Business Loan. A key concern is: processing time. One follow-up commitment is still open: Send documents by Friday."
    )
    assert memory_payload["pre_meeting_brief"]["last_meeting"] == "Business Loan Discussion"
    assert memory_payload["pre_meeting_brief"]["pending"] == ["Send documents by Friday"]
    assert memory_payload["pre_meeting_brief"]["concern"] == "Processing time"
    assert (
        memory_payload["pre_meeting_brief"]["suggested_talking_point"]
        == "Explain loan processing timeline."
    )
    assert memory_payload["pending_commitments"][0]["description"] == "Send documents"
    assert memory_payload["major_concerns"][0]["description"] == "processing time"


def test_unknown_client_requires_confirmation_then_updates_memory(
    client_app: TestClient, api_headers: dict[str, str]
) -> None:
    response = client_app.post(
        "/api/v1/meeting-notes/process",
        headers=api_headers,
        json={
            "raw_notes": "Customer interested in home loan. Wants callback Friday.",
            "meeting_date": "2026-06-19",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["requires_client_confirmation"] is True
    assert payload["client_id"] is None
    assert payload["client_status"] == "client_identification_required"

    confirm = client_app.post(
        f"/api/v1/meeting-notes/{payload['meeting_id']}/confirm-client",
        headers=api_headers,
        json={"new_client_name": "Amit Verma"},
    )

    assert confirm.status_code == 200
    confirm_payload = confirm.json()
    assert confirm_payload["client_status"] == "created"
    assert confirm_payload["client_id"] == 1
    assert confirm_payload["meeting"]["client_id"] == 1
    assert confirm_payload["extraction"]["client_identification"]["status"] == "created"
    assert confirm_payload["pending_commitments"][0]["description"] == "Call client back"


def test_confirmation_saves_the_whatsapp_phone_for_a_new_client(
    client_app: TestClient, api_headers: dict[str, str]
) -> None:
    processed = client_app.post(
        "/api/v1/meeting-notes/process",
        headers=api_headers,
        json={
            "raw_notes": "Customer interested in home loan. Wants callback Friday.",
            "meeting_date": "2026-06-19",
        },
    )
    assert processed.status_code == 200

    confirmed = client_app.post(
        f"/api/v1/meeting-notes/{processed.json()['meeting_id']}/confirm-client",
        headers=api_headers,
        json={
            "new_client_name": "Amit Verma",
            "new_client_whatsapp_phone": "+919876543210",
        },
    )
    assert confirmed.status_code == 200

    client = client_app.get(
        f"/api/v1/clients/{confirmed.json()['client_id']}", headers=api_headers
    )
    assert client.status_code == 200
    assert client.json()["whatsapp_phone"] == "+919876543210"


def test_confirmation_saves_a_manually_provided_phone_for_an_existing_client(
    client_app: TestClient, api_headers: dict[str, str]
) -> None:
    initial = client_app.post(
        "/api/v1/meeting-notes/process",
        headers=api_headers,
        json={
            "raw_notes": "Met Rajesh Sharma today. Interested in business loan.",
            "meeting_date": "2026-06-19",
        },
    )
    unresolved = client_app.post(
        "/api/v1/meeting-notes/process",
        headers=api_headers,
        json={
            "raw_notes": "Customer wants a callback Friday.",
            "meeting_date": "2026-06-20",
        },
    )

    confirmed = client_app.post(
        f"/api/v1/meeting-notes/{unresolved.json()['meeting_id']}/confirm-client",
        headers=api_headers,
        json={
            "client_id": initial.json()["client_id"],
            "new_client_whatsapp_phone": "+919876543210",
        },
    )
    assert confirmed.status_code == 200

    client = client_app.get(
        f"/api/v1/clients/{initial.json()['client_id']}", headers=api_headers
    )
    assert client.json()["whatsapp_phone"] == "+919876543210"


def test_vague_due_date_is_not_invented(
    client_app: TestClient, api_headers: dict[str, str]
) -> None:
    response = client_app.post(
        "/api/v1/meeting-notes/process",
        headers=api_headers,
        json={
            "raw_notes": "Met Neha Gupta today. I will send documents soon.",
            "meeting_date": "2026-06-19",
        },
    )

    assert response.status_code == 200
    commitment = response.json()["commitments_created"][0]
    assert commitment["due_date"] is None
    assert commitment["due_date_text"] == "soon"
    assert commitment["due_date_confidence"] < 0.75


def test_duplicate_pending_commitment_is_updated_not_duplicated(
    client_app: TestClient, api_headers: dict[str, str]
) -> None:
    first = client_app.post(
        "/api/v1/meeting-notes/process",
        headers=api_headers,
        json={
            "raw_notes": "Met Rajesh Sharma today. Promised documents by Friday.",
            "meeting_date": "2026-06-19",
        },
    )
    assert first.status_code == 200

    second = client_app.post(
        "/api/v1/meeting-notes/process",
        headers=api_headers,
        json={
            "raw_notes": "Met Rajesh Sharma today. Reminder: still need to send documents.",
            "meeting_date": "2026-06-20",
        },
    )

    assert second.status_code == 200
    payload = second.json()
    assert payload["commitments_created"] == []
    assert len(payload["commitments_updated"]) == 1

    commitments = client_app.get("/api/v1/commitments", headers=api_headers)
    assert commitments.status_code == 200
    assert len(commitments.json()["commitments"]) == 1


def test_mark_commitment_completed(client_app: TestClient, api_headers: dict[str, str]) -> None:
    created = client_app.post(
        "/api/v1/meeting-notes/process",
        headers=api_headers,
        json={
            "raw_notes": "Met Pooja Singh today. I will call next Monday.",
            "meeting_date": "2026-06-19",
        },
    )
    commitment_id = created.json()["commitments_created"][0]["id"]

    response = client_app.patch(
        f"/api/v1/commitments/{commitment_id}/status",
        headers=api_headers,
        json={"status": "completed"},
    )

    assert response.status_code == 200
    assert response.json()["commitment"]["status"] == "completed"


def test_low_confidence_due_date_is_not_saved_even_if_provider_returns_one(
    client_app: TestClient, api_headers: dict[str, str], monkeypatch
) -> None:
    class LowConfidenceDueDateProvider:
        provider_name = "test"
        model_name = "test-model"

        def extract_meeting_intelligence(self, raw_notes: str, meeting_date):  # noqa: ANN001
            return {
                "client_identification": {
                    "status": "identified",
                    "matched_client_id": None,
                    "suggested_client_name": "Neha Gupta",
                    "confidence": 0.92,
                    "requires_confirmation": False,
                },
                "meeting_summary": "Neha Gupta requested documents.",
                "key_discussion_points": ["Documents requested"],
                "concerns": [],
                "commitments": [
                    {
                        "description": "Send documents",
                        "owner": "RM",
                        "due_date_text": "soon",
                        "due_date": "2026-06-20",
                        "due_date_confidence": 0.30,
                        "status": "pending",
                        "confidence": 0.90,
                    }
                ],
                "action_items": ["Send documents"],
                "warnings": ["Due date confidence is low."],
            }

    monkeypatch.setattr(
        meeting_processing_service_module,
        "get_ai_provider",
        lambda settings: LowConfidenceDueDateProvider(),
    )

    response = client_app.post(
        "/api/v1/meeting-notes/process",
        headers=api_headers,
        json={
            "raw_notes": "Met Neha Gupta today. I will send documents soon.",
            "meeting_date": "2026-06-19",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["commitments_created"][0]["due_date"] is None
    assert payload["commitments_created"][0]["due_date_text"] == "soon"
    assert payload["extraction"]["commitments"][0]["due_date"] is None
    assert payload["warnings"] == ["Due date confidence is low."]


def test_ai_provider_failure_returns_controlled_error(
    client_app: TestClient, api_headers: dict[str, str], monkeypatch
) -> None:
    class FailingProvider:
        provider_name = "test"
        model_name = "test-model"

        def extract_meeting_intelligence(self, raw_notes: str, meeting_date):  # noqa: ANN001
            raise AIExtractionError("Provider unavailable.")

    monkeypatch.setattr(
        meeting_processing_service_module,
        "get_ai_provider",
        lambda settings: FailingProvider(),
    )

    response = client_app.post(
        "/api/v1/meeting-notes/process",
        headers=api_headers,
        json={
            "raw_notes": "Met Rajesh Sharma today. Promised documents by Friday.",
            "meeting_date": "2026-06-19",
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Provider unavailable."


def test_delete_client_removes_related_data(
    client_app: TestClient, api_headers: dict[str, str]
) -> None:
    created = client_app.post(
        "/api/v1/meeting-notes/process",
        headers=api_headers,
        json={
            "raw_notes": "Met Wrong Client today. I will send documents tomorrow.",
            "meeting_date": "2026-06-19",
        },
    )
    client_id = created.json()["client_id"]

    deleted = client_app.delete(f"/api/v1/clients/{client_id}", headers=api_headers)

    assert deleted.status_code == 200
    payload = deleted.json()
    assert payload["meetings_deleted"] == 1
    assert payload["commitments_deleted"] == 1
    assert client_app.get(f"/api/v1/clients/{client_id}/memory", headers=api_headers).status_code == 404
    assert client_app.get("/api/v1/commitments", headers=api_headers).json()["commitments"] == []


def test_health_is_public(client_app: TestClient) -> None:
    response = client_app.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] in {"ok", "degraded"}


def test_dashboard_assets_load(client_app: TestClient) -> None:
    page = client_app.get("/")
    script = client_app.get("/static/app.js")

    assert page.status_code == 200
    assert "PHILIXA 6.0" in page.text
    assert script.status_code == 200
    assert "processNotes" in script.text


def test_openapi_includes_main_workflow_examples(client_app: TestClient) -> None:
    response = client_app.get("/openapi.json")

    assert response.status_code == 200
    openapi = response.json()
    process_request_examples = openapi["paths"]["/api/v1/meeting-notes/process"]["post"][
        "requestBody"
    ]["content"]["application/json"]["examples"]
    confirm_request_examples = openapi["paths"][
        "/api/v1/meeting-notes/{meeting_id}/confirm-client"
    ]["post"]["requestBody"]["content"]["application/json"]["examples"]
    process_response_schema = openapi["components"]["schemas"]["MeetingNoteProcessResponse"]

    assert "clear_client" in process_request_examples
    assert "ambiguous_client" in process_request_examples
    assert "create_new_client" in confirm_request_examples
    assert "example" in process_response_schema
