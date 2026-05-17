"""HTTP routes for the reports module (F3 §7 + §11).

Three GET endpoints under ``/api/reports``:

* ``GET /reports/latest``     — most recent report of the authenticated user.
* ``GET /reports/{id}``       — single report; 404 if missing or cross-user.
* ``GET /reports/``           — paginated list (default 20/page).

All endpoints require a valid Supabase JWT via ``get_current_user_id`` (F2).
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.contracts.responses import SuccessResponse
from app.core.security import get_current_user_id
from app.modules.reports.schemas import ReportListResponse, ReportResponse
from app.modules.reports.service import (
    ReportNotFound,
    ReportService,
    get_report_service,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/latest",
    response_model=SuccessResponse[ReportResponse],
    summary="Return the authenticated user's most recent report",
)
async def get_latest_report(
    user_id: UUID = Depends(get_current_user_id),
    service: ReportService = Depends(get_report_service),
) -> SuccessResponse[ReportResponse]:
    try:
        result = await service.get_latest(user_id)
    except ReportNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="report_not_found"
        )
    return SuccessResponse(data=result)


@router.get(
    "/{report_id}",
    response_model=SuccessResponse[ReportResponse],
    summary="Fetch a single report by id (owner-only)",
)
async def get_report_by_id(
    report_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    service: ReportService = Depends(get_report_service),
) -> SuccessResponse[ReportResponse]:
    try:
        result = await service.get_by_id(report_id, user_id=user_id)
    except ReportNotFound:
        # 404 indistinct from cross-user (prevents enumeration).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="report_not_found"
        )
    return SuccessResponse(data=result)


@router.get(
    "",
    response_model=SuccessResponse[ReportListResponse],
    summary="List the authenticated user's reports (paginated)",
)
async def list_reports(
    user_id: UUID = Depends(get_current_user_id),
    service: ReportService = Depends(get_report_service),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> SuccessResponse[ReportListResponse]:
    result = await service.list_for_user(user_id, page=page, page_size=page_size)
    return SuccessResponse(data=result)


__all__ = ["router"]
