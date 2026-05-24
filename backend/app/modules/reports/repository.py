"""Persistence repository for ``medzee_spy.reports``.

All operations use the Supabase **service_role** admin client. Reports are
created by the worker before the user is necessarily linked (the F1 session
may still be anonymous when the worker fires), so RLS is bypassed at this
layer. Read paths exposed to the API (``get_by_id``, ``get_latest_for_user``,
``list_for_user``) defensively filter by ``user_id`` even though RLS already
scopes ownership — see REPORT-17.

supabase-py 2.x is **synchronous** (requests under the hood), so every public
function in this module wraps the blocking call with :func:`asyncio.to_thread`
to keep the FastAPI event loop responsive. The lambdas capture the table
reference fresh on each call — the admin client is created per call in
:func:`app.clients.supabase.get_supabase_admin_client`, which is fine for our
volume and avoids leaking a long-lived service_role client across coroutines.

Sensitive fields:

* ``payload`` (the generated report JSON) is **never** logged. It may contain
  WhatsApp-derived signals that we do not want in observability pipelines.
* Full Supabase responses are never logged either; we emit structured fields
  (``report_id``, ``user_id``, ``whatsapp_session_id``, ``status``,
  ``error_code``, ``rows_affected``) only.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.clients.supabase import get_supabase_admin_client

logger = logging.getLogger(__name__)


def _table() -> Any:
    """Return a fresh table handle scoped to ``medzee_spy.reports``."""
    return get_supabase_admin_client().schema("medzee_spy").table("reports")


async def get_existing_for_session(whatsapp_session_id: UUID) -> dict | None:
    """Return the report row already attached to this WhatsApp session, or
    ``None`` if none exists.

    Used by the worker (idempotency: if a placeholder row was inserted by
    a previous run we want to UPDATE it instead of creating a duplicate)
    and by ``_fail`` (to mark the placeholder as failed when generation dies).
    """
    result = await asyncio.to_thread(
        lambda: _table()
        .select("*")
        .eq("whatsapp_session_id", str(whatsapp_session_id))
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", None) or []
    found = bool(rows)
    logger.info(
        "repo.reports.get_existing_for_session",
        extra={"whatsapp_session_id": str(whatsapp_session_id), "found": found},
    )
    if not found:
        return None
    return rows[0]


def _utcnow_iso() -> str:
    """Return the current UTC timestamp as an ISO 8601 string.

    We compute ``generated_at`` client-side (rather than via a DB ``default``)
    because the column only takes a value on the ``completed``/``partial``
    transition — the row is first inserted with ``status='generating'`` and
    ``generated_at`` NULL.
    """
    return datetime.now(timezone.utc).isoformat()


async def create_generating(
    *,
    whatsapp_session_id: UUID,
    user_id: UUID | None,
    clinic_segment: str | None,
) -> UUID:
    """Insert a new report row in ``generating`` state and return its id.

    Called by the F3 worker the moment it picks up an extracted WhatsApp
    session. The ``user_id`` may legitimately be ``None`` here — F1 sessions
    can be created pre-signup, in which case :func:`link_user` will backfill
    the column once the user signs up. ``clinic_segment`` is denormalised
    from the user profile at creation time for prompt selection.
    """
    row: dict[str, Any] = {
        "whatsapp_session_id": str(whatsapp_session_id),
        "user_id": str(user_id) if user_id is not None else None,
        "clinic_segment": clinic_segment,
        "status": "generating",
    }
    result = await asyncio.to_thread(
        lambda: _table().insert(row).execute()
    )
    rows = getattr(result, "data", None) or []
    if not rows or "id" not in rows[0]:
        # supabase-py returns the inserted row(s) by default; if we don't
        # get one back something has gone very wrong server-side.
        raise RuntimeError(
            "repo.reports.create_generating: INSERT returned no id"
        )
    report_id = UUID(rows[0]["id"])
    logger.info(
        "repo.reports.create_generating",
        extra={
            "report_id": str(report_id),
            "user_id": str(user_id) if user_id is not None else None,
            "whatsapp_session_id": str(whatsapp_session_id),
            "status": "generating",
        },
    )
    return report_id


async def update_completed(
    report_id: UUID,
    *,
    payload: dict,
    model: str,
    prompt_version: str,
    message_count: int,
    score: int,
) -> None:
    """Transition a report to ``completed`` with the generated payload.

    ``generated_at`` is set client-side to "now" — see :func:`_utcnow_iso`.
    ``updated_at`` is handled by the DB trigger.
    """
    update: dict[str, Any] = {
        "status": "completed",
        "payload": payload,
        "model": model,
        "prompt_version": prompt_version,
        "message_count": message_count,
        "score": score,
        "generated_at": _utcnow_iso(),
    }
    await asyncio.to_thread(
        lambda: _table().update(update).eq("id", str(report_id)).execute()
    )
    logger.info(
        "repo.reports.update_completed",
        extra={
            "report_id": str(report_id),
            "status": "completed",
        },
    )


async def update_partial(
    report_id: UUID,
    *,
    payload: dict,
    model: str,
    prompt_version: str,
    message_count: int,
    score: int,
) -> None:
    """Transition a report to ``partial`` with a best-effort payload.

    Same shape as :func:`update_completed`, used when the worker produced
    something usable but flagged degraded quality (e.g. small sample, model
    fallback). The route layer surfaces ``partial`` to the UI as a soft
    warning rather than a failure.
    """
    update: dict[str, Any] = {
        "status": "partial",
        "payload": payload,
        "model": model,
        "prompt_version": prompt_version,
        "message_count": message_count,
        "score": score,
        "generated_at": _utcnow_iso(),
    }
    await asyncio.to_thread(
        lambda: _table().update(update).eq("id", str(report_id)).execute()
    )
    logger.info(
        "repo.reports.update_partial",
        extra={
            "report_id": str(report_id),
            "status": "partial",
        },
    )


async def update_period_days(report_id: UUID, period_days: int) -> None:
    """Set the window length (F4) on a report row.

    Called by :func:`ReportService.trigger_generate` right after
    :func:`create_generating` so the row remembers which window the user
    chose. Separate from create_generating to keep the create signature
    stable for F3 callers that don't know about period_days.
    """
    await asyncio.to_thread(
        lambda: _table()
        .update({"period_days": period_days})
        .eq("id", str(report_id))
        .execute()
    )
    logger.info(
        "repo.reports.update_period_days",
        extra={"report_id": str(report_id), "period_days": period_days},
    )


async def update_failed(report_id: UUID, *, error_code: str) -> None:
    """Mark a report as failed with a stable ``error_code``.

    ``payload`` is intentionally **not** touched here — if a previous
    generation attempt left a row behind we keep it for debugging while
    still surfacing failure to the caller via ``status``.
    """
    update = {"status": "failed", "error_code": error_code}
    await asyncio.to_thread(
        lambda: _table().update(update).eq("id", str(report_id)).execute()
    )
    logger.info(
        "repo.reports.update_failed",
        extra={
            "report_id": str(report_id),
            "status": "failed",
            "error_code": error_code,
        },
    )


async def link_user(whatsapp_session_id: UUID, user_id: UUID) -> int:
    """Attach a freshly-signed-up user to any pre-existing report rows.

    Called from the F2 signup flow after profile creation. If the worker has
    already inserted a report for this session (race: extraction finished
    before signup), this UPDATE backfills ``user_id`` so RLS picks up. If
    the worker hasn't run yet, the UPDATE affects 0 rows — that's fine, the
    worker will set ``user_id`` itself at INSERT time using the
    now-linked session.

    Only rows where ``user_id IS NULL`` are touched, so we never overwrite
    an existing link.

    Returns the number of rows affected.
    """
    update = {"user_id": str(user_id)}
    result = await asyncio.to_thread(
        lambda: _table()
        .update(update)
        .eq("whatsapp_session_id", str(whatsapp_session_id))
        .is_("user_id", "null")
        .execute()
    )
    rows = getattr(result, "data", None) or []
    rows_affected = len(rows)
    logger.info(
        "repo.reports.link_user",
        extra={
            "whatsapp_session_id": str(whatsapp_session_id),
            "user_id": str(user_id),
            "rows_affected": rows_affected,
        },
    )
    return rows_affected


async def get_by_id(report_id: UUID, *, user_id: UUID) -> dict | None:
    """Return a single report scoped to its owner, or ``None``.

    The ``user_id`` filter is defensive — RLS would already block a
    cross-tenant read, but we belt-and-braces it here so a service_role
    bug or misconfigured RLS policy can't leak rows (REPORT-17).
    """
    result = await asyncio.to_thread(
        lambda: _table()
        .select("*")
        .eq("id", str(report_id))
        .eq("user_id", str(user_id))
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", None) or []
    found = bool(rows)
    logger.info(
        "repo.reports.get_by_id",
        extra={
            "report_id": str(report_id),
            "user_id": str(user_id),
            "found": found,
        },
    )
    if not found:
        return None
    return rows[0]


async def get_latest_for_user(user_id: UUID) -> dict | None:
    """Return the most recent report for a user, or ``None`` if none exist.

    Used by the dashboard "latest report" widget. Ordering is by
    ``created_at`` (insertion time), not ``generated_at`` — a still-
    generating row should preempt an older completed one so the UI can
    show a spinner instead of stale data.
    """
    result = await asyncio.to_thread(
        lambda: _table()
        .select("*")
        .eq("user_id", str(user_id))
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", None) or []
    found = bool(rows)
    logger.info(
        "repo.reports.get_latest_for_user",
        extra={"user_id": str(user_id), "found": found},
    )
    if not found:
        return None
    return rows[0]


async def list_for_user(
    user_id: UUID, *, page: int, page_size: int
) -> tuple[list[dict], int]:
    """Return a page of reports for a user plus the total count.

    ``page`` is 1-based to match the public API contract. ``count='exact'``
    is requested so the caller can compute total pages without a second
    round trip — supabase-py exposes the value as ``result.count``.

    The ``range`` is inclusive on both ends in PostgREST, hence
    ``offset + page_size - 1`` for the upper bound.
    """
    offset = (page - 1) * page_size
    upper = offset + page_size - 1
    result = await asyncio.to_thread(
        lambda: _table()
        .select("*", count="exact")
        .eq("user_id", str(user_id))
        .order("created_at", desc=True)
        .range(offset, upper)
        .execute()
    )
    rows: list[dict] = getattr(result, "data", None) or []
    total = getattr(result, "count", None) or 0
    logger.info(
        "repo.reports.list_for_user",
        extra={
            "user_id": str(user_id),
            "rows_affected": len(rows),
        },
    )
    return rows, int(total)
