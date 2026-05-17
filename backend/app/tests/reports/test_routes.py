"""HTTP integration tests for the 3 reports routes (T21 of F3).

Style mirrors ``app/tests/auth/test_auth_routes.py``:

* ``TestClient(app)`` (sync) for HTTP exercising.
* ``app.dependency_overrides`` swaps both ``get_current_user_id`` (so we
  bypass the real ``HTTPBearer`` + Supabase token lookup) and
  ``get_report_service`` (so we drive the route layer in isolation).
* An autouse fixture clears overrides after each test so suites don't bleed.

Scope: routes only — service exceptions → HTTP shapes, the
``SuccessResponse`` envelope, and query-parameter forwarding to the service.
Service internals live in ``test_service.py``; repo internals in
``test_repository.py``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.security import get_current_user_id
from app.main import app
from app.modules.reports.schemas import (
    ReportListResponse,
    ReportPayload,
    ReportResponse,
    ReportStatus,
    ReportSummary,
)
from app.modules.reports.service import (
    ReportNotFound,
    get_report_service,
)


# --------------------------------------------------------------------------- #
# Constants + helpers                                                          #
# --------------------------------------------------------------------------- #


FIXED_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
FIXED_REPORT_ID = UUID("11111111-1111-1111-1111-111111111111")


def _report_response(
    *,
    payload: ReportPayload | None = None,
    status: ReportStatus = ReportStatus.COMPLETED,
    report_id: UUID = FIXED_REPORT_ID,
) -> ReportResponse:
    return ReportResponse(
        id=report_id,
        status=status,
        payload=payload,
        error_code=None,
        message_count=842 if payload else None,
        score=72 if payload else None,
        created_at=datetime.now(timezone.utc),
        generated_at=datetime.now(timezone.utc) if payload else None,
    )


def _report_summary(
    *,
    status: ReportStatus = ReportStatus.COMPLETED,
    report_id: UUID | None = None,
    score: int | None = 72,
) -> ReportSummary:
    return ReportSummary(
        id=report_id or uuid4(),
        status=status,
        message_count=842,
        score=score,
        created_at=datetime.now(timezone.utc),
    )


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def fake_service(sample_report_payload: ReportPayload) -> MagicMock:
    """``ReportService``-shaped MagicMock with ``AsyncMock`` methods.

    Defaults are happy-path stubs; per-test ``side_effect`` /
    ``return_value`` overrides drive the error cases.
    """
    svc = MagicMock(name="ReportService")
    svc.get_latest = AsyncMock(
        name="get_latest",
        return_value=_report_response(payload=sample_report_payload),
    )
    svc.get_by_id = AsyncMock(
        name="get_by_id",
        return_value=_report_response(payload=sample_report_payload),
    )
    svc.list_for_user = AsyncMock(
        name="list_for_user",
        return_value=ReportListResponse(
            items=[_report_summary(), _report_summary()],
            total=2,
            page=1,
            page_size=20,
        ),
    )
    return svc


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    """Wipe ``app.dependency_overrides`` after every test."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(fake_service: MagicMock) -> TestClient:
    """Sync TestClient with ``get_report_service`` + ``get_current_user_id``
    overridden so each test gets an authenticated principal by default.

    Tests exercising the unauthenticated path simply omit the principal
    override before issuing the request (see
    ``test_get_latest_without_token_401_or_403``).
    """
    app.dependency_overrides[get_report_service] = lambda: fake_service
    app.dependency_overrides[get_current_user_id] = lambda: FIXED_USER_ID
    return TestClient(app)


# --------------------------------------------------------------------------- #
# GET /api/reports/latest                                                      #
# --------------------------------------------------------------------------- #


def test_get_latest_200(
    client: TestClient,
    fake_service: MagicMock,
    sample_report_payload: ReportPayload,
) -> None:
    """Happy path → 200 ``SuccessResponse[ReportResponse]`` envelope."""
    response = client.get("/api/reports/latest")

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "ok"
    data = body["data"]
    assert data["id"] == str(FIXED_REPORT_ID)
    assert data["status"] == "completed"
    assert data["payload"] is not None
    assert data["payload"]["score"] == sample_report_payload.score
    assert data["payload"]["clinic_segment"] == sample_report_payload.clinic_segment
    fake_service.get_latest.assert_awaited_once_with(FIXED_USER_ID)


def test_get_latest_404_no_report(
    client: TestClient, fake_service: MagicMock
) -> None:
    """``ReportNotFound`` from the service → 404 detail='report_not_found'."""
    fake_service.get_latest.side_effect = ReportNotFound(str(FIXED_USER_ID))

    response = client.get("/api/reports/latest")

    assert response.status_code == 404
    assert response.json() == {"detail": "report_not_found"}


# --------------------------------------------------------------------------- #
# GET /api/reports/{report_id}                                                 #
# --------------------------------------------------------------------------- #


def test_get_by_id_200(
    client: TestClient,
    fake_service: MagicMock,
    sample_report_payload: ReportPayload,
) -> None:
    """Happy path → 200 envelope; service called with ``(report_id, user_id=)``."""
    response = client.get(f"/api/reports/{FIXED_REPORT_ID}")

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "ok"
    data = body["data"]
    assert data["id"] == str(FIXED_REPORT_ID)
    assert data["status"] == "completed"
    assert data["payload"]["score"] == sample_report_payload.score

    fake_service.get_by_id.assert_awaited_once_with(
        FIXED_REPORT_ID, user_id=FIXED_USER_ID
    )


def test_get_by_id_404_cross_user(
    client: TestClient, fake_service: MagicMock
) -> None:
    """``ReportNotFound`` (cross-user OR truly missing) → 404 indistinctly."""
    fake_service.get_by_id.side_effect = ReportNotFound(str(FIXED_REPORT_ID))

    response = client.get(f"/api/reports/{FIXED_REPORT_ID}")

    assert response.status_code == 404
    assert response.json() == {"detail": "report_not_found"}


def test_get_by_id_invalid_uuid_422(
    client: TestClient, fake_service: MagicMock
) -> None:
    """Non-UUID path param → FastAPI 422 before the service is reached."""
    response = client.get("/api/reports/not-a-uuid")

    assert response.status_code == 422
    fake_service.get_by_id.assert_not_awaited()


# --------------------------------------------------------------------------- #
# GET /api/reports                                                             #
# --------------------------------------------------------------------------- #


def test_list_reports_200(client: TestClient, fake_service: MagicMock) -> None:
    """Default pagination → 200 ``SuccessResponse[ReportListResponse]``."""
    response = client.get("/api/reports")

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "ok"
    data = body["data"]
    assert len(data["items"]) == 2
    assert data["total"] == 2
    assert data["page"] == 1
    assert data["page_size"] == 20
    # Summary items don't carry the full payload.
    assert "payload" not in data["items"][0]
    assert data["items"][0]["status"] == "completed"

    fake_service.list_for_user.assert_awaited_once_with(
        FIXED_USER_ID, page=1, page_size=20
    )


def test_list_reports_pagination_query_params(
    client: TestClient, fake_service: MagicMock
) -> None:
    """``?page=2&page_size=10`` forwards verbatim to ``service.list_for_user``."""
    fake_service.list_for_user.return_value = ReportListResponse(
        items=[], total=0, page=2, page_size=10
    )

    response = client.get("/api/reports?page=2&page_size=10")

    assert response.status_code == 200
    fake_service.list_for_user.assert_awaited_once_with(
        FIXED_USER_ID, page=2, page_size=10
    )


def test_list_reports_invalid_page_size_422(
    client: TestClient, fake_service: MagicMock
) -> None:
    """``page_size=500`` violates ``Query(le=100)`` → 422 before service call."""
    response = client.get("/api/reports?page_size=500")

    assert response.status_code == 422
    fake_service.list_for_user.assert_not_awaited()


# --------------------------------------------------------------------------- #
# Auth boundary                                                                #
# --------------------------------------------------------------------------- #


def test_get_latest_without_token_401_or_403(
    fake_service: MagicMock,
) -> None:
    """No Authorization header → FastAPI ``HTTPBearer`` rejects the request.

    With ``HTTPBearer(auto_error=True)`` (the default — see
    ``app/core/security.py``), a missing/empty Authorization header yields
    **403 Forbidden** with ``detail == 'Not authenticated'``. We accept
    either 401 or 403 because some FastAPI/Starlette combos emit 401 here;
    on the current pin it is **403**. ``get_current_user_id`` is NOT
    overridden so the real auth dependency runs and short-circuits before
    the service.
    """
    # Install only the service override — leave auth real so the bearer
    # scheme fires.
    app.dependency_overrides[get_report_service] = lambda: fake_service
    bare = TestClient(app)

    response = bare.get("/api/reports/latest")

    assert response.status_code in (401, 403)
    fake_service.get_latest.assert_not_awaited()
