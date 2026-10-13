from __future__ import annotations

import json
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.models.client import Client
from app.models.commitment import Commitment
from app.models.meeting import Meeting
from app.models.user import User
from app.services.json_utils import from_json, to_json
from app.services.meeting_processing_service import MeetingProcessingService
from app.services.memory_service import MemoryService
from app.worker import WorkerSettings
from scripts.cleanup_demo_accounts import cleanup_demo_accounts


# ==============================================================================
# 1. Challenge MeetingProcessingService._merge_string_list_field
# ==============================================================================
class TestMeetingProcessingMergeStringListField:
    @pytest.fixture
    def service(self) -> MeetingProcessingService:
        return MeetingProcessingService()

    def test_merge_duplicates_and_casing(self, service: MeetingProcessingService):
        current_json = to_json(["Savings Account", "Fixed Deposit"])
        new_items = ["fixed deposit", "SAVINGS ACCOUNT", "Mutual Funds", "mutual funds"]
        result_json = service._merge_string_list_field(current_json, new_items)
        result = from_json(result_json, [])
        # Should preserve original casing of first occurrence and eliminate case-insensitive duplicates
        assert result == ["Savings Account", "Fixed Deposit", "Mutual Funds"]

    def test_merge_whitespace_and_empty_strings(self, service: MeetingProcessingService):
        current_json = to_json(["  Term Insurance  ", ""])
        new_items = ["   ", "Term Insurance", "\tWealth Management\n", "   "]
        result_json = service._merge_string_list_field(current_json, new_items)
        result = from_json(result_json, [])
        # Strips whitespaces, drops pure empty/whitespace strings
        assert result == ["Term Insurance", "Wealth Management"]

    def test_merge_none_and_non_string_elements(self, service: MeetingProcessingService):
        current_json = json.dumps(["Credit Card", None, 12345])
        new_items = [None, "", "Home Loan", 67890]
        result_json = service._merge_string_list_field(current_json, new_items)  # type: ignore[arg-type]
        result = from_json(result_json, [])
        assert result == ["Credit Card", "12345", "Home Loan", "67890"]

    def test_merge_invalid_or_malformed_current_json(self, service: MeetingProcessingService):
        # When current_json is invalid JSON or empty string
        malformed_inputs = ["not a json string", "", "{'invalid': json}", "null", "123"]
        new_items = ["Gold Loan", "Car Loan"]
        for malformed in malformed_inputs:
            result_json = service._merge_string_list_field(malformed, new_items)
            result = from_json(result_json, [])
            assert result == ["Gold Loan", "Car Loan"], f"Failed for malformed input: {malformed}"

    def test_merge_empty_or_none_new_items(self, service: MeetingProcessingService):
        current_json = to_json(["Current Account"])
        assert service._merge_string_list_field(current_json, []) == current_json
        assert service._merge_string_list_field(current_json, None) == current_json  # type: ignore[arg-type]

    def test_merge_preserves_insertion_order(self, service: MeetingProcessingService):
        current_json = to_json(["Alpha", "Beta"])
        new_items = ["Gamma", "Alpha", "Delta", "Beta", "Epsilon"]
        result_json = service._merge_string_list_field(current_json, new_items)
        result = from_json(result_json, [])
        assert result == ["Alpha", "Beta", "Gamma", "Delta", "Epsilon"]

    def test_merge_large_stress_list(self, service: MeetingProcessingService):
        # 1000 items with heavy duplication and mixed casing
        existing = [f"Product_{i % 50}" for i in range(500)]
        new_items = [f"PRODUCT_{i % 100}" for i in range(500)]
        current_json = to_json(existing)
        result_json = service._merge_string_list_field(current_json, new_items)
        result = from_json(result_json, [])
        assert len(result) == 100
        assert result[0] == "Product_0"
        assert result[49] == "Product_49"
        assert result[50] == "PRODUCT_50"


# ==============================================================================
# 2. Challenge MemoryService._build_rolling_summary and _suggested_talking_point
# ==============================================================================
class TestMemoryServiceRollingSummaryAndTalkingPoints:
    @pytest.fixture
    def memory(self) -> MemoryService:
        return MemoryService()

    def test_rolling_summary_both_present(self, memory: MemoryService):
        summary = memory._build_rolling_summary(
            client_name="Vikram Mehta",
            latest_meeting=None,
            pending=[],
            concerns=[],
            products_owned=["Current Account", "Overdraft Facility"],
            products_interested=["Term Loan", "Forex Card"],
        )
        assert "Tracked products include Current Account, Overdraft Facility." in summary
        assert "Client expressed interest in Term Loan, Forex Card." in summary

    def test_rolling_summary_only_interested(self, memory: MemoryService):
        summary = memory._build_rolling_summary(
            client_name="Vikram Mehta",
            latest_meeting=None,
            pending=[],
            concerns=[],
            products_owned=[],
            products_interested=["Commercial Vehicle Loan"],
        )
        assert "Tracked products" not in summary
        assert "Client expressed interest in Commercial Vehicle Loan." in summary

    def test_rolling_summary_only_owned(self, memory: MemoryService):
        summary = memory._build_rolling_summary(
            client_name="Vikram Mehta",
            latest_meeting=None,
            pending=[],
            concerns=[],
            products_owned=["Fixed Deposit", "Savings Account"],
            products_interested=[],
        )
        assert "Tracked products include Fixed Deposit, Savings Account." in summary
        assert "Client expressed interest in" not in summary

    def test_rolling_summary_neither_present(self, memory: MemoryService):
        summary = memory._build_rolling_summary(
            client_name="Vikram Mehta",
            latest_meeting=None,
            pending=[],
            concerns=[],
            products_owned=[],
            products_interested=[],
        )
        assert "Tracked products" not in summary
        assert "Client expressed interest in" not in summary
        assert summary == "Vikram Mehta has no stored briefing yet."

    def test_rolling_summary_slicing_more_than_three_items(self, memory: MemoryService):
        summary = memory._build_rolling_summary(
            client_name="Priya Sharma",
            latest_meeting=None,
            pending=[],
            concerns=[],
            products_owned=["P1", "P2", "P3", "P4", "P5"],
            products_interested=["I1", "I2", "I3", "I4", "I5"],
        )
        assert "Tracked products include P1, P2, P3." in summary
        assert "P4" not in summary
        assert "Client expressed interest in I1, I2, I3." in summary
        assert "I4" not in summary

    def test_suggested_talking_point_precedence_matrix(self, memory: MemoryService):
        pending_commit = Commitment(
            id=1,
            organization_id="org_1",
            user_id="user_1",
            client_id=1,
            description="Send audited financial sheets",
            status="pending",
        )
        mock_meeting = Meeting(
            id=1,
            organization_id="org_1",
            user_id="user_1",
            summary="Discussion about interest rates",
            key_discussion_points_json="[]",
            concerns_json="[]",
            status="processed",
        )

        # 1. Concern with "timeline" or "processing time" overrides ALL
        tp1 = memory._suggested_talking_point(
            products_owned=["Savings Account"],
            last_meeting=mock_meeting,
            pending=[pending_commit],
            top_concern="Client is concerned about the loan processing timeline delay",
            products_interested=["Home Loan"],
        )
        assert tp1 == "Explain loan processing timeline."

        # 2. Concern with "approval" overrides products and commitments
        tp2 = memory._suggested_talking_point(
            products_owned=["Savings Account"],
            last_meeting=mock_meeting,
            pending=[pending_commit],
            top_concern="Pending credit approval status from risk team",
            products_interested=["Home Loan"],
        )
        assert tp2 == "Share a clear approval status update and next step."

        # 3. No critical concern keywords -> products_interested takes precedence over products_owned and pending
        tp3 = memory._suggested_talking_point(
            products_owned=["Savings Account"],
            last_meeting=mock_meeting,
            pending=[pending_commit],
            top_concern="",
            products_interested=["Business Loan", "Mutual Funds"],
        )
        assert tp3 == "Follow up on client's interest in Business Loan."

        # 4. No products_interested -> products_owned takes precedence over pending commitments
        tp4 = memory._suggested_talking_point(
            products_owned=["Current Account"],
            last_meeting=mock_meeting,
            pending=[pending_commit],
            top_concern="",
            products_interested=[],
        )
        assert tp4 == "Reconfirm the client's priority around Current Account and align on the next step."

        # 5. Neither interested nor owned -> pending commitment takes precedence
        tp5 = memory._suggested_talking_point(
            products_owned=[],
            last_meeting=mock_meeting,
            pending=[pending_commit],
            top_concern="",
            products_interested=[],
        )
        assert tp5 == "Start by confirming progress on send audited financial sheets."

        # 6. No pending commitment -> last meeting summary takes precedence
        tp6 = memory._suggested_talking_point(
            products_owned=[],
            last_meeting=mock_meeting,
            pending=[],
            top_concern="",
            products_interested=[],
        )
        assert tp6 == "Reconfirm the previous discussion and align on the next action."

        # 7. Total empty state -> default fallback
        tp7 = memory._suggested_talking_point(
            products_owned=[],
            last_meeting=None,
            pending=[],
            top_concern="",
            products_interested=None,
        )
        assert tp7 == "Start with a quick recap and confirm the client's current priority."


# ==============================================================================
# 3. Challenge CORS Origin Parsing in app/main.py
# ==============================================================================
class TestCORSOriginParsingAndMiddleware:
    def _create_app_with_origins(self, raw_origins: Any) -> FastAPI:
        test_app = FastAPI()

        if isinstance(raw_origins, list):
            origins = [o.strip() for o in raw_origins if o.strip()]
        elif isinstance(raw_origins, str) and raw_origins.strip():
            origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
        else:
            origins = ["http://localhost:8000", "http://localhost:3000", "http://127.0.0.1:8000"]

        if "*" in origins:
            origins = [o for o in origins if o != "*"]

        if origins:
            test_app.add_middleware(
                CORSMiddleware,
                allow_origins=origins,
                allow_credentials=True,
                allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
                allow_headers=[
                    "Authorization",
                    "Content-Type",
                    "X-CSRF-Token",
                    "X-Requested-With",
                    "Accept",
                    "Origin",
                ],
                expose_headers=["Content-Length", "X-CSRF-Token"],
                max_age=600,
            )

        @test_app.get("/ping")
        def ping():
            return {"status": "ok"}

        return test_app

    def test_cors_whitespace_and_comma_separated_strings(self):
        raw = "  http://app.example.com  ,  http://crm.example.com , , http://localhost:3000  "
        app = self._create_app_with_origins(raw)
        client = TestClient(app)

        # Test allowed origin
        resp = client.options(
            "/ping",
            headers={
                "Origin": "http://app.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://app.example.com"
        assert resp.headers.get("access-control-allow-credentials") == "true"
        assert resp.headers.get("access-control-max-age") == "600"
        assert "X-CSRF-Token" in resp.headers.get("access-control-expose-headers", "")

        # Test another allowed origin
        resp2 = client.options(
            "/ping",
            headers={
                "Origin": "http://crm.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp2.headers.get("access-control-allow-origin") == "http://crm.example.com"

        # Test unauthorized origin
        resp_unauth = client.options(
            "/ping",
            headers={
                "Origin": "http://attacker.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" not in resp_unauth.headers

    def test_cors_wildcard_sanitization(self):
        # When wildcard '*' is mixed with valid origins
        raw = ["*", "http://legitimate.domain.com", " * "]
        app = self._create_app_with_origins(raw)
        client = TestClient(app)

        # Wildcard * must NOT be in allowed origins when allow_credentials=True
        resp_wildcard = client.options(
            "/ping",
            headers={
                "Origin": "*",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" not in resp_wildcard.headers

        # Legitimate domain should still succeed
        resp_legit = client.options(
            "/ping",
            headers={
                "Origin": "http://legitimate.domain.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp_legit.headers.get("access-control-allow-origin") == "http://legitimate.domain.com"

    def test_cors_fallback_on_empty_or_none(self):
        for empty_val in ["", "   ", None, []]:
            app = self._create_app_with_origins(empty_val)
            client = TestClient(app)

            # Default localhost origins must be enabled
            resp = client.options(
                "/ping",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_live_app_cors_behavior(self):
        from app.main import app
        client = TestClient(app)

        # Preflight against /health
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization,Content-Type,X-CSRF-Token",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
        assert resp.headers.get("access-control-allow-credentials") == "true"
        assert resp.headers.get("access-control-max-age") == "600"
        assert "X-CSRF-Token" in resp.headers.get("access-control-expose-headers", "")


# ==============================================================================
# 4. Challenge ARQ WorkerSettings Cron Job Inspection
# ==============================================================================
class TestARQWorkerSettingsCronInspection:
    def test_worker_settings_cron_jobs_structure(self):
        cron_jobs = WorkerSettings.cron_jobs
        assert len(cron_jobs) >= 4, "Expected at least 4 registered cron jobs"

        coroutine_names = [job.coroutine.__name__ for job in cron_jobs]
        assert "cleanup_demo_accounts" in coroutine_names
        assert "send_client_followups" in coroutine_names
        assert "send_pre_interaction_briefs" in coroutine_names
        assert "retry_failed_notifications" in coroutine_names

    def test_cleanup_demo_accounts_cron_timing(self):
        cleanup_job = next(job for job in WorkerSettings.cron_jobs if job.coroutine.__name__ == "cleanup_demo_accounts")
        # Runs hourly at minute 0
        assert cleanup_job.hour is None, f"Expected hour=None for hourly execution, got {cleanup_job.hour}"
        assert cleanup_job.minute == {0} or cleanup_job.minute == 0, f"Expected minute=0, got {cleanup_job.minute}"

    @pytest.mark.asyncio
    async def test_cleanup_demo_accounts_execution_with_custom_ctx(self):
        # Mock session and execute
        mock_session = AsyncMock()
        mock_db_result = MagicMock()
        mock_user_1 = MagicMock(spec=User, email="demo_guest_1234@philixa.ai")
        mock_user_2 = MagicMock(spec=User, email="demo_guest_5678@philixa.ai")
        mock_db_result.scalars.return_value.all.return_value = [mock_user_1, mock_user_2]
        mock_session.execute.return_value = mock_db_result

        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session
        mock_session_factory.return_value.__aexit__.return_value = None

        ctx = {"db_session_factory": mock_session_factory}
        await cleanup_demo_accounts(ctx)

        mock_session.execute.assert_called_once()
        assert mock_session.delete.call_count == 2
        mock_session.delete.assert_any_call(mock_user_1)
        mock_session.delete.assert_any_call(mock_user_2)
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_demo_accounts_fallback_when_ctx_is_empty_or_none(self):
        # Verify function accepts None and empty dict without throwing TypeError
        with patch("scripts.cleanup_demo_accounts.AsyncSessionLocal") as mock_local_session:
            mock_session = AsyncMock()
            mock_db_result = MagicMock()
            mock_db_result.scalars.return_value.all.return_value = []
            mock_session.execute.return_value = mock_db_result
            mock_local_session.return_value.__aenter__.return_value = mock_session
            mock_local_session.return_value.__aexit__.return_value = None

            # Test with ctx=None
            await cleanup_demo_accounts(None)
            mock_session.commit.assert_called_once()
            mock_session.reset_mock()

            # Test with ctx={}
            await cleanup_demo_accounts({})
            mock_session.commit.assert_called_once()
