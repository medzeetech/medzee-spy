"""Report service — read-only orchestration (F3 §11).

Thin layer over :mod:`app.modules.reports.repository`. Routes do not call
the repository directly — they go through the service so authorization
filters (defense-in-depth) stay in one place and exceptions map cleanly
to HTTP codes.
"""
from __future__ import annotations

import logging
from uuid import UUID

from app.modules.reports import repository
from app.modules.reports.schemas import (
    ReportListResponse,
    ReportResponse,
    ReportStatus,
    ReportSummary,
)

logger = logging.getLogger(__name__)


class ReportError(Exception):
    """Base."""


class ReportNotFound(ReportError):
    """404 (REPORT-16, REPORT-17)."""


class ReportService:
    async def get_latest(self, user_id: UUID) -> ReportResponse:
        row = await repository.get_latest_for_user(user_id)
        if row is None:
            raise ReportNotFound(str(user_id))
        return _to_response(row)

    async def get_by_id(self, report_id: UUID, *, user_id: UUID) -> ReportResponse:
        row = await repository.get_by_id(report_id, user_id=user_id)
        if row is None:
            # 404 (indistinct from cross-user — prevents enumeration).
            raise ReportNotFound(str(report_id))
        return _to_response(row)

    async def list_for_user(
        self, user_id: UUID, *, page: int = 1, page_size: int = 20
    ) -> ReportListResponse:
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        rows, total = await repository.list_for_user(
            user_id, page=page, page_size=page_size
        )
        items = [_to_summary(r) for r in rows]
        return ReportListResponse(
            items=items, total=total, page=page, page_size=page_size
        )


def _to_response(row: dict) -> ReportResponse:
    return ReportResponse(
        id=row["id"],
        status=ReportStatus(row["status"]),
        payload=row.get("payload"),
        error_code=row.get("error_code"),
        message_count=row.get("message_count"),
        score=row.get("score"),
        created_at=row["created_at"],
        generated_at=row.get("generated_at"),
    )


def _to_summary(row: dict) -> ReportSummary:
    return ReportSummary(
        id=row["id"],
        status=ReportStatus(row["status"]),
        message_count=row.get("message_count"),
        score=row.get("score"),
        created_at=row["created_at"],
    )


_service_singleton: ReportService | None = None


def get_report_service() -> ReportService:
    global _service_singleton
    if _service_singleton is None:
        _service_singleton = ReportService()
    return _service_singleton


__all__ = ["ReportService", "ReportError", "ReportNotFound", "get_report_service"]
