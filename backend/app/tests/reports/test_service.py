"""Unit tests for ``ReportService`` (T21 of F3).

The service is a thin orchestration layer over
``app.modules.reports.repository``. The conftest's ``fake_repository``
fixture replaces every repository function with an ``AsyncMock``, so these
tests can exercise mapping + error translation without touching Supabase.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.modules.reports.schemas import ReportPayload, ReportStatus
from app.modules.reports.service import (
    ReportNotFound,
    ReportService,
)


def _row(
    *,
    payload: ReportPayload,
    status: str = "completed",
    score: int | None = 72,
) -> dict:
    """Build a Supabase-shaped row that mirrors what the repo would return."""
    return {
        "id": str(uuid4()),
        "status": status,
        "payload": payload.model_dump(),
        "error_code": None,
        "message_count": 842,
        "score": score,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# --------------------------------------------------------------------------- #
# get_latest                                                                   #
# --------------------------------------------------------------------------- #


async def test_get_latest_happy_returns_response(
    fake_repository: SimpleNamespace,
    sample_report_payload: ReportPayload,
) -> None:
    """Repo returns a row → service maps to ``ReportResponse`` with the right
    id, status, and payload values.
    """
    row = _row(payload=sample_report_payload, status="completed")
    fake_repository.get_latest_for_user.return_value = row
    uid = uuid4()

    response = await ReportService().get_latest(uid)

    assert response.id == UUID(row["id"])
    assert response.status == ReportStatus.COMPLETED
    assert response.payload is not None
    assert response.payload.score == sample_report_payload.score
    assert response.payload.clinic_segment == sample_report_payload.clinic_segment
    assert response.message_count == 842
    fake_repository.get_latest_for_user.assert_awaited_once_with(uid)


async def test_get_latest_returns_none_raises_not_found(
    fake_repository: SimpleNamespace,
) -> None:
    """Repo returns ``None`` → service raises ``ReportNotFound`` (→ 404)."""
    fake_repository.get_latest_for_user.return_value = None

    with pytest.raises(ReportNotFound):
        await ReportService().get_latest(uuid4())


# --------------------------------------------------------------------------- #
# get_by_id                                                                    #
# --------------------------------------------------------------------------- #


async def test_get_by_id_returns_404_when_cross_user(
    fake_repository: SimpleNamespace,
) -> None:
    """The repository filters by user_id (REPORT-17), so a cross-user lookup
    sees ``None``. The service must translate that to ``ReportNotFound`` —
    indistinct from a genuinely missing id to prevent enumeration.
    """
    fake_repository.get_by_id.return_value = None
    rid = uuid4()
    uid = uuid4()

    with pytest.raises(ReportNotFound):
        await ReportService().get_by_id(rid, user_id=uid)

    fake_repository.get_by_id.assert_awaited_once_with(rid, user_id=uid)


async def test_get_by_id_happy_returns_response(
    fake_repository: SimpleNamespace,
    sample_report_payload: ReportPayload,
) -> None:
    """Owner can read their own report → mapped to ``ReportResponse``."""
    row = _row(payload=sample_report_payload, status="partial", score=68)
    fake_repository.get_by_id.return_value = row
    rid = UUID(row["id"])
    uid = uuid4()

    response = await ReportService().get_by_id(rid, user_id=uid)

    assert response.id == rid
    assert response.status == ReportStatus.PARTIAL
    assert response.score == 68


# --------------------------------------------------------------------------- #
# list_for_user                                                                #
# --------------------------------------------------------------------------- #


async def test_list_for_user_clamps_pagination(
    fake_repository: SimpleNamespace,
) -> None:
    """``page=-5, page_size=500`` is clamped to ``page=1, page_size=100``
    before the repo is called. Empty rows → empty items list, total preserved.
    """
    fake_repository.list_for_user.return_value = ([], 0)
    uid = uuid4()

    result = await ReportService().list_for_user(uid, page=-5, page_size=500)

    fake_repository.list_for_user.assert_awaited_once_with(
        uid, page=1, page_size=100
    )
    assert result.items == []
    assert result.total == 0
    assert result.page == 1
    assert result.page_size == 100


async def test_list_for_user_maps_rows_to_summaries(
    fake_repository: SimpleNamespace,
    sample_report_payload: ReportPayload,
) -> None:
    """Each row is mapped to a ``ReportSummary`` (no ``payload`` field
    materialised in the list view) and the total is forwarded."""
    rows = [
        _row(payload=sample_report_payload, status="completed", score=72),
        _row(payload=sample_report_payload, status="generating", score=None),
    ]
    fake_repository.list_for_user.return_value = (rows, 2)

    result = await ReportService().list_for_user(uuid4(), page=1, page_size=20)

    assert len(result.items) == 2
    assert result.items[0].status == ReportStatus.COMPLETED
    assert result.items[0].score == 72
    assert result.items[1].status == ReportStatus.GENERATING
    assert result.items[1].score is None
    assert result.total == 2
    # The summary has no `payload` attribute.
    assert not hasattr(result.items[0], "payload")
