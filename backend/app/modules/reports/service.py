"""Report service — read + on-demand generation (F3 §11 + F4-11..13).

Thin layer over :mod:`app.modules.reports.repository`. Routes do not call
the repository directly — they go through the service so authorization
filters (defense-in-depth) stay in one place and exceptions map cleanly
to HTTP codes.

F4 adds :py:meth:`ReportService.trigger_generate` which creates a report
row and dispatches the worker fire-and-forget over a window of captured
messages. The worker (``app.workers.report.generate_report_pipeline``) is
reused as-is — it accepts an optional ``report_id`` so we just hand it
the freshly created id.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from app.modules.reports import repository
from app.modules.reports.schemas import (
    ReportListResponse,
    ReportResponse,
    ReportStatus,
    ReportSummary,
)
from app.modules.whatsapp.schemas import (
    ConversationPayload,
    ExtractedPayload,
    MessagePayload,
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

    # ── F4-11..13: on-demand generation over captured_messages ────────

    async def trigger_generate(
        self, user_id: UUID, *, period_days: int
    ) -> UUID:
        """Create a generating-state report row and dispatch the worker.

        Returns the new ``report_id`` so the route can hand it back to the
        client (which then navigates to ``/app/reports/{id}`` and polls).

        Pre-conditions (enforced by the route layer):
            * user is authenticated
            * captured_messages.stats_for_user(user_id) ≥ 10
            * rate limit check (1/min) passed

        Concurrency:
            * fire-and-forget asyncio task; this method returns immediately
            * the worker handles its own error mapping → reports.status
        """
        clinic_segment = await _resolve_clinic_segment(user_id)
        whatsapp_session_id = await _resolve_active_session(user_id)

        report_id = await repository.create_generating(
            whatsapp_session_id=whatsapp_session_id,
            user_id=user_id,
            clinic_segment=clinic_segment,
        )
        # Lembrar a janela escolhida pelo user pra exibir na lista.
        try:
            await repository.update_period_days(report_id, period_days)
        except Exception:
            # Não-crítico: o relatório roda mesmo sem o period_days
            # explícito (default 30). Log + segue.
            logger.warning(
                "service.reports.update_period_days_failed",
                extra={"report_id": str(report_id), "period_days": period_days},
                exc_info=True,
            )

        logger.info(
            "service.reports.trigger_generate",
            extra={
                "op": "trigger_generate",
                "user_id": str(user_id),
                "report_id": str(report_id),
                "period_days": period_days,
                "clinic_segment": clinic_segment,
            },
        )

        asyncio.create_task(
            _build_and_run(
                report_id=report_id,
                user_id=user_id,
                period_days=period_days,
                whatsapp_session_id=whatsapp_session_id,
            ),
            name=f"report-{report_id}",
        )
        return report_id


# ─── F4 helpers (módulo-level pra serem testáveis sem instanciar service) ─


async def _resolve_clinic_segment(user_id: UUID) -> str:
    """Lazy import wrapper around the worker's own segment resolver."""
    try:
        from app.workers.report import _resolve_clinic_segment as worker_resolve
        return await worker_resolve(user_id)
    except Exception:
        logger.warning(
            "service.reports.resolve_segment_failed",
            extra={"user_id": str(user_id)},
            exc_info=True,
        )
        return "outro"


async def _resolve_active_session(user_id: UUID) -> UUID:
    """Find the user's currently-linked whatsapp_session_id.

    If none exists, returns a fresh uuid4 — the worker will still create
    the report row with whatsapp_session_id pointing to a non-existent
    session. This is a degenerate case (user clicked "Gerar relatório"
    without ever connecting WhatsApp), and the route layer should have
    blocked it via the 10-message minimum. We don't crash.
    """
    try:
        from app.modules.whatsapp import repository as whatsapp_repo
        session = await whatsapp_repo.get_active_for_user(user_id)
        if session and session.get("id"):
            return UUID(str(session["id"]))
    except Exception:
        logger.warning(
            "service.reports.resolve_session_failed",
            extra={"user_id": str(user_id)},
            exc_info=True,
        )
    # Degenerate fallback — never expected on the happy path.
    return uuid4()


async def _build_and_run(
    *,
    report_id: UUID,
    user_id: UUID,
    period_days: int,
    whatsapp_session_id: UUID,
) -> None:
    """Read captured_messages within the window, build ExtractedPayload,
    call ``generate_report_pipeline`` with the pre-created ``report_id``.

    Errors here are best-effort: the worker has its own try/except that
    marks the row as failed with a stable error_code.
    """
    try:
        from app.modules.captured_messages import repository as captured_repo
        from app.workers.report import generate_report_pipeline

        since = datetime.now(timezone.utc) - timedelta(days=period_days)
        captured = await captured_repo.query_window_for_user(user_id, since=since)
        payload = _build_extracted_payload(captured)

        logger.info(
            "service.reports.payload_built",
            extra={
                "report_id": str(report_id),
                "user_id": str(user_id),
                "period_days": period_days,
                "messages": payload.message_count,
                "conversations": payload.conversation_count,
            },
        )

        await generate_report_pipeline(
            session_id=whatsapp_session_id,
            payload=payload,
            user_id=user_id,
            report_id=report_id,
        )
    except Exception:
        logger.exception(
            "service.reports.build_and_run_failed",
            extra={"report_id": str(report_id), "user_id": str(user_id)},
        )
        # Best-effort: marca row failed pra frontend parar de polar.
        try:
            await repository.update_failed(report_id, error_code="internal_error")
        except Exception:
            logger.exception(
                "service.reports.persist_failed_secondary",
                extra={"report_id": str(report_id)},
            )


def _build_extracted_payload(
    captured: list,  # list[CapturedMessage]
) -> ExtractedPayload:
    """Translate captured_messages rows into the F3 ``ExtractedPayload`` shape.

    Groups by ``wa_chatid``, sorts messages chronologically inside each
    conversation, infers ``is_group`` from the JID suffix, and forwards
    ``contact_name`` as the conversation label. The F3 pipeline accepts
    this output verbatim — no other adapter needed.

    Empty input → empty ExtractedPayload (worker handles that gracefully).
    """
    by_chat: dict[str, list[MessagePayload]] = {}
    contact_names: dict[str, str | None] = {}
    last_seen: dict[str, int] = {}

    for m in captured:
        ts_unix = int(m.ts.timestamp())
        msgs = by_chat.setdefault(m.wa_chatid, [])
        msgs.append(
            MessagePayload(
                ts=ts_unix,
                from_me=m.is_from_me,
                type=m.message_type,
                text=m.text or "",
            )
        )
        # Mantém o primeiro contact_name visto (estabilidade entre runs).
        if m.wa_chatid not in contact_names:
            contact_names[m.wa_chatid] = m.contact_name
        # Track última msg (em unix) por chat.
        if ts_unix > last_seen.get(m.wa_chatid, 0):
            last_seen[m.wa_chatid] = ts_unix

    conversations: list[ConversationPayload] = []
    for cid, msgs in by_chat.items():
        msgs_sorted = sorted(msgs, key=lambda x: x.ts)
        conversations.append(
            ConversationPayload(
                wa_chatid=cid,
                contact_name=contact_names.get(cid) or "",
                is_group=cid.endswith("@g.us"),
                last_message_at=last_seen.get(cid),
                messages=msgs_sorted,
            )
        )

    return ExtractedPayload(
        message_count=sum(len(c.messages) for c in conversations),
        conversation_count=len(conversations),
        conversations=conversations,
        partial=False,
    )


# ─── Existing F3 helpers ──────────────────────────────────────────────


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
        period_days=row.get("period_days"),
        created_at=row["created_at"],
    )


_service_singleton: ReportService | None = None


def get_report_service() -> ReportService:
    global _service_singleton
    if _service_singleton is None:
        _service_singleton = ReportService()
    return _service_singleton


__all__ = [
    "ReportService",
    "ReportError",
    "ReportNotFound",
    "get_report_service",
    "_build_extracted_payload",
]
