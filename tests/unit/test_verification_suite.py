import pytest
from sqlalchemy import inspect
from app.models.client import Client
from app.schemas.client import ClientResponse, ClientListItem, PreMeetingBriefResponse, ClientMemoryResponse
from app.schemas.ai_extraction import MeetingExtraction
from app.main import app


def test_client_model_columns_verification():
    cols = [c.name for c in inspect(Client).columns]
    assert "products_interested_json" in cols
    assert "products_owned_json" in cols


def test_schemas_verification():
    assert hasattr(ClientResponse, "model_fields")
    assert "products_interested" in ClientResponse.model_fields
    assert "products_owned" in ClientResponse.model_fields
    assert "products_interested" in ClientListItem.model_fields
    assert "products_interested" in PreMeetingBriefResponse.model_fields
    assert "products_interested" in ClientMemoryResponse.model_fields
    assert "products_interested" in MeetingExtraction.model_fields


def test_fastapi_app_startup_import():
    assert "PHILIXA" in app.title
