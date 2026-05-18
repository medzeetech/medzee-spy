"""HTTP routes for the reports module (F3 §7 + §11 + F4-11..13).

Four endpoints under ``/api/reports``:

* ``GET  /reports/latest``     — most recent report of the authenticated user.
* ``GET  /reports/{id}``       — single report; 404 if missing or cross-user.
* ``GET  /reports/``           — paginated list (default 20/page).
* ``POST /reports/generate``   — F4: trigger a new on-demand report over a
                                 user-selected window (7/15/30/60 days).

All endpoints require a valid Supabase JWT via ``get_current_user_id`` (F2).
"""
from __future__ import annotations

import logging
import os
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.contracts.responses import SuccessResponse
from app.core.security import get_current_user_id
from app.modules.captured_messages.schemas import (
    GenerateReportRequest,
    GenerateReportResponse,
)
from app.modules.reports.schemas import ReportListResponse, ReportResponse
from app.modules.reports.service import (
    ReportNotFound,
    ReportService,
    get_report_service,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── F4: rate limit + min volume thresholds (overridable via env) ─────

# Minimum captured messages required before user can generate a report
# (EC-02: avoid useless reports on near-empty datasets). Configurable
# pra dev/smoke poder relaxar.
_GENERATE_MIN_MESSAGES: int = int(
    os.environ.get("REPORTS_GENERATE_MIN_MESSAGES", "10")
)

# Rate limit: 1 generation per N seconds per user (EC-03). Prevents
# accidental double-clicks and abuse. In-memory bucket — sufficient pro
# MVP. Em produção c/ múltiplas réplicas viraria Redis ou similar.
_GENERATE_RATE_S: float = float(
    os.environ.get("REPORTS_GENERATE_RATE_S", "60")
)

_last_generate_call: dict[str, float] = {}


def _check_rate_limit(user_id: UUID) -> None:
    """Raise 429 if user generated < ``_GENERATE_RATE_S`` ago."""
    key = str(user_id)
    now = time.monotonic()
    last = _last_generate_call.get(key)
    if last is not None and (now - last) < _GENERATE_RATE_S:
        retry_in = int(_GENERATE_RATE_S - (now - last))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"too_many_generations_retry_in_{retry_in}s",
        )
    _last_generate_call[key] = now


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


# ─── F4-11..13: on-demand report generation ───────────────────────────


@router.post(
    "/generate",
    response_model=SuccessResponse[GenerateReportResponse],
    summary="Trigger a new on-demand report (F5: last-N per chat by default)",
)
async def generate_report(
    req: GenerateReportRequest,
    user_id: UUID = Depends(get_current_user_id),
    service: ReportService = Depends(get_report_service),
) -> SuccessResponse[GenerateReportResponse]:
    """Dispara um relatório novo on-demand.

    F5 (default): ``mode='last_n_per_chat'``, ``n_per_chat=30``.
    Pega as últimas N msgs de cada conversa, sem janela temporal.

    F4 legacy: ``mode='window_days'`` mantém o filtro por dias.

    Pré-condições verificadas aqui (route layer):
    1. Rate limit: 1 generation por ``REPORTS_GENERATE_RATE_S`` segundos
       por user (default 60s). Excedeu → 429 ``too_many_generations_*``.

    Eliminado em F5: o threshold rígido "min 10 msgs" → bloqueava o user
    sem deixar ele NEM TENTAR. Agora SEMPRE dispara — o worker decide se
    a sample é suficiente e persiste ``data_quality=insufficient`` com
    diagnóstico honesto quando não tiver dados. Relatório SEMPRE existe.

    Em sucesso retorna ``{report_id, status: 'generating'}`` imediato; o
    frontend navega pra ``/app/reports/{id}`` e polla até status terminal.
    """
    # 1. Rate limit
    _check_rate_limit(user_id)

    # 2. Observabilidade — qual é o ponto de partida (snapshot local).
    try:
        from app.modules.captured_messages import repository as captured_repo
        stats = await captured_repo.stats_for_user(user_id)
    except Exception:
        logger.warning(
            "route.reports.generate.stats_check_failed",
            extra={"user_id": str(user_id)},
            exc_info=True,
        )
        stats = {"message_count": 0, "conversation_count": 0}

    logger.info(
        "route.reports.generate.snapshot",
        extra={
            "user_id": str(user_id),
            "mode": req.mode,
            "n_per_chat": req.n_per_chat,
            "period_days": req.period_days,
            "captured_message_count": stats.get("message_count", 0),
            "captured_conversation_count": stats.get("conversation_count", 0),
        },
    )

    # 3. Dispatch — SEM threshold rígido. Worker decide insufficient.
    report_id = await service.trigger_generate(
        user_id,
        mode=req.mode,
        n_per_chat=req.n_per_chat,
        period_days=req.period_days,
    )
    logger.info(
        "route.reports.generate.dispatched",
        extra={
            "user_id": str(user_id),
            "report_id": str(report_id),
            "mode": req.mode,
            "n_per_chat": req.n_per_chat,
            "period_days": req.period_days,
        },
    )
    return SuccessResponse(
        data=GenerateReportResponse(report_id=report_id)
    )


__all__ = ["router"]
