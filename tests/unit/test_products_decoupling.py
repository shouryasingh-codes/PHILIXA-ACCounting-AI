from __future__ import annotations

import pytest
from app.ai.prompts import MEETING_EXTRACTION_SYSTEM_PROMPT
from app.models.client import Client
from app.schemas.ai_extraction import MeetingExtraction
from app.schemas.client import (
    ClientCreateRequest,
    ClientListItem,
    ClientMemoryResponse,
    ClientResponse,
    PreMeetingBriefResponse,
)
from app.schemas.common import MeetingExtractionRead
from app.services.json_utils import from_json, to_json
from app.services.meeting_processing_service import MeetingProcessingService
from app.services.memory_service import MemoryService


def test_client_model_columns():
    cols = {c.name for c in Client.__table__.columns}
    assert "products_owned_json" in cols
    assert "products_interested_json" in cols


def test_client_schemas_default_and_serialization():
    # ClientResponse
    res = ClientResponse(
        id=1,
        name="Test Client",
        organization_id="org_1",
        user_id="user_1",
        products_owned=["Product A"],
        products_interested=["Product B"],
    )
    assert res.products_owned == ["Product A"]
    assert res.products_interested == ["Product B"]

    # ClientCreateRequest
    req = ClientCreateRequest(
        name="Test Client",
        products_owned=["Product A"],
        products_interested=["Product B"],
    )
    assert req.products_owned == ["Product A"]
    assert req.products_interested == ["Product B"]

    # PreMeetingBriefResponse
    brief = PreMeetingBriefResponse(
        title="Client Brief",
        products_owned=["Product A"],
        products_interested=["Product B"],
        last_meeting="Recent Meeting",
        pending=["Task 1"],
        concern="No concern",
        highest_urgency="low",
        suggested_talking_point="Talking point",
    )
    assert brief.products_interested == ["Product B"]


def test_meeting_extraction_schemas():
    extraction = MeetingExtraction(
        client_identification={
            "status": "identified",
            "suggested_client_name": "Test Client",
            "confidence": 0.95,
        },
        meeting_summary="Summary of meeting",
        key_discussion_points=["Point 1"],
        products_owned=["Current Account"],
        products_interested=["Business Loan"],
        concerns=[],
        commitments=[],
    )
    assert extraction.products_owned == ["Current Account"]
    assert extraction.products_interested == ["Business Loan"]

    read_schema = MeetingExtractionRead(
        client_identification={
            "status": "identified",
            "matched_client_id": 1,
            "suggested_client_name": "Test Client",
            "confidence": 0.95,
            "requires_confirmation": False,
        },
        meeting_summary="Summary",
        key_discussion_points=["Point 1"],
        products_owned=["Current Account"],
        products_interested=["Business Loan"],
        concerns=[],
        commitments=[],
        action_items=[],
        warnings=[],
    )
    assert read_schema.products_interested == ["Business Loan"]


def test_prompt_rules_contract():
    assert '"products_owned":' in MEETING_EXTRACTION_SYSTEM_PROMPT
    assert '"products_interested":' in MEETING_EXTRACTION_SYSTEM_PROMPT
    assert "CRITICAL RULE 5: DECOUPLE PRODUCTS OWNED VS INTERESTED:" in MEETING_EXTRACTION_SYSTEM_PROMPT
    assert "place them in 'products_interested'" in MEETING_EXTRACTION_SYSTEM_PROMPT


def test_merge_string_list_field():
    svc = MeetingProcessingService()
    current_json = to_json(["Savings Account", "Fixed Deposit"])
    new_items = ["fixed deposit", "Mutual Funds", "   "]
    merged_json = svc._merge_string_list_field(current_json, new_items)
    merged_list = from_json(merged_json, [])
    assert merged_list == ["Savings Account", "Fixed Deposit", "Mutual Funds"]


def test_memory_service_suggested_talking_point():
    mem = MemoryService()
    # When products_interested is provided
    talking_point = mem._suggested_talking_point(
        products_owned=["Savings Account"],
        last_meeting=None,
        pending=[],
        top_concern="",
        products_interested=["Business Loan"],
    )
    assert "Business Loan" in talking_point
    assert "Follow up on client's interest in Business Loan." == talking_point
