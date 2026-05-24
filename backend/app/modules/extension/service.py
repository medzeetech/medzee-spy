"""Business logic for the Chrome extension ingestion module (F8 / §4.2).

Five async public functions, one per route:

* :func:`pair_extension`   — ``POST /api/extension/pair``
* :func:`ingest_batch`     — ``POST /api/extension/messages``
* :func:`record_telemetry` — ``POST /api/extension/telemetry``
* :func:`capture_mobile_lead` — ``POST /api/extension/mobile-lead``
* :func:`get_status`       — ``GET  /api/extension/status``

Design notes worth keeping in mind:

* This module **never** talks to Supabase directly — every persistence
  call goes through :mod:`app.modules.extension.repository` (or the
  cross-module :func:`app.modules.captured_messages.repository.insert_many`
  for the F4 dedup-safe bulk insert path).
* Logs are structured (``logger.info("svc.extension.<event>", extra=...)``)
  and **never** include PII. ``text`` / ``contact_name`` / ``wa_chatid``
  travel through ``ingest_batch`` but are never logged — only counts.
* :func:`record_telemetry` enforces an in-memory 60/min/user rate-limit
  (CHX-16). The bucket is a module-level ``dict[UUID, deque[float]]``
  protected by an :class:`asyncio.Lock`. Two concurrent requests from
  the same user that arrive at the 60-event boundary will not both pass.
* When a batch is the last one (``batch_index == total_batches - 1``)
  :func:`ingest_batch` fires :py:meth:`ReportService.trigger_generate`
  as an ``asyncio.create_task`` so the HTTP response returns 202 fast
  while the worker (F3) runs in the background.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from uuid import UUID

from fastapi import HTTPException, status

from app.core.config import settings
from app.modules.captured_messages.repository import insert_many
from app.modules.captured_messages.schemas import CapturedMessageInsert
from app.modules.extension import repository
from app.modules.extension.schemas import (
    ExtensionMessageBatch,
    ExtensionPairRequest,
    ExtensionPairResponse,
    ExtensionStatusResponse,
    ExtensionTelemetryEvent,
    MobileRedirectLeadCreate,
)
from app.modules.extension.security import (
    decode_pairing_token,
    issue_refresh_token,
)

logger = logging.getLogger(__name__)


# ─── version comparison ────────────────────────────────────────────────


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a ``"1.2.3"``-style version string into a comparable tuple.

    Non-numeric segments and malformed strings collapse to ``(0,)`` so
    we never raise from inside the request path — the rate-limit / 409
    decision still happens, just biased toward "outdated" which is the
    safe default.
    """
    try:
        return tuple(int(part) for part in v.split("."))
    except (AttributeError, ValueError):
        return (0,)


def _is_outdated(client_version: str, min_version: str) -> bool:
    return _parse_version(client_version) < _parse_version(min_version)


# ─── pair ──────────────────────────────────────────────────────────────


async def pair_extension(req: ExtensionPairRequest) -> ExtensionPairResponse:
    """Trade a short-lived pairing token for a long-lived refresh token.

    Flow:
        1. Decode the pairing JWT — wrong ``typ`` / expired / malformed
           raises HTTP 401 (handled inside ``decode_pairing_token``).
        2. UPSERT the install row so subsequent calls can attribute
           telemetry / collections to this device.
        3. Mint a refresh token (30d TTL by default) and return it with
           the user id so the extension can store both atomically.
    """
    user_id = decode_pairing_token(req.pairing_token)
    await repository.upsert_install(
        install_id=req.extension_install_id,
        user_id=user_id,
        extension_version=req.extension_version,
        user_agent=req.user_agent,
    )
    refresh_token = issue_refresh_token(user_id)
    logger.info(
        "svc.extension.pair.success",
        extra={
            "user_id": str(user_id),
            "install_id": req.extension_install_id,
            "extension_version": req.extension_version,
        },
    )
    return ExtensionPairResponse(refresh_token=refresh_token, user_id=user_id)


# ─── ingest_batch ──────────────────────────────────────────────────────


async def ingest_batch(user_id: UUID, batch: ExtensionMessageBatch) -> dict:
    """Persist one batch of extension-collected messages.

    Steps:
        1. Reject ``extension_version < EXTENSION_MIN_VERSION`` with
           409 ``code='extension_outdated'`` (CHX-14).
        2. Resolve the user's synthetic ``whatsapp_sessions`` row.
        3. Map ``ExtensionMessage`` → ``CapturedMessageInsert`` and call
           ``captured_messages.repository.insert_many`` (re-uses the L11
           dedup-safe bulk insert path).
        4. On the **last** batch fire ``ReportService.trigger_generate``
           as an ``asyncio.create_task`` — the HTTP response goes out
           fast while F3 runs in the background.
        5. Bump ``last_seen_at`` on the install row (best-effort).
    """
    if _is_outdated(batch.extension_version, settings.EXTENSION_MIN_VERSION):
        logger.info(
            "svc.extension.ingest.outdated",
            extra={
                "user_id": str(user_id),
                "client_version": batch.extension_version,
                "min_version": settings.EXTENSION_MIN_VERSION,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "extension_outdated",
                "min_version": settings.EXTENSION_MIN_VERSION,
                "client_version": batch.extension_version,
            },
        )

    session_id = await repository.get_or_create_extension_session(user_id)

    inserts: list[CapturedMessageInsert] = [
        CapturedMessageInsert(
            user_id=user_id,
            whatsapp_session_id=session_id,
            wa_chatid=msg.wa_chatid,
            contact_name=msg.contact_name,
            ts=msg.ts,
            is_from_me=msg.is_from_me,
            message_type=msg.message_type,
            text=msg.text,
            raw_message_id=msg.wa_msg_id,
            source="extension",
        )
        for msg in batch.messages
    ]

    received = await insert_many(inserts)

    is_final = batch.batch_index == batch.total_batches - 1
    if is_final:
        # Lazy import to avoid a circular dependency at module load —
        # reports.service imports plenty of upstream modules and we only
        # need it on the terminal batch of a run.
        from app.modules.reports.service import get_report_service

        report_service = get_report_service()
        asyncio.create_task(
            report_service.trigger_generate(
                user_id, mode="last_n_per_chat", n_per_chat=30
            ),
            name=f"extension-trigger-{batch.batch_id}",
        )
        logger.info(
            "svc.extension.ingest.report_fired",
            extra={
                "user_id": str(user_id),
                "batch_id": batch.batch_id,
                "total_batches": batch.total_batches,
            },
        )

    # Best-effort install touch — if the user paired from another device
    # we don't have the install_id here, so we skip silently when absent.
    try:
        install = await repository.get_install_for_user(user_id)
        if install:
            await repository.touch_install(install["install_id"])
    except Exception:
        logger.warning(
            "svc.extension.ingest.touch_install_failed",
            extra={"user_id": str(user_id)},
            exc_info=True,
        )

    logger.info(
        "svc.extension.ingest.batch_persisted",
        extra={
            "user_id": str(user_id),
            "batch_id": batch.batch_id,
            "batch_index": batch.batch_index,
            "total_batches": batch.total_batches,
            "received": received,
            "is_final": is_final,
        },
    )
    return {
        "received": received,
        "batch_id": batch.batch_id,
        "batch_index": batch.batch_index,
        "is_final": is_final,
    }


# ─── telemetry rate-limit (in-memory) ──────────────────────────────────


# Per-user sliding window of telemetry timestamps. Lives in-process —
# rate-limiting only kicks in at the boundary of a single worker, which
# is fine because the threat model here is a buggy/abusive client, not a
# distributed DoS (the endpoint is auth-only and the cost per call is a
# single insert).
_TELEMETRY_RATE_BUCKETS: dict[UUID, deque[float]] = {}
_TELEMETRY_RATE_LOCK = asyncio.Lock()

_TELEMETRY_WINDOW_S = 60.0


async def record_telemetry(
    user_id: UUID, event: ExtensionTelemetryEvent
) -> None:
    """Persist a no-PII telemetry event, rate-limited 60/min/user.

    The Pydantic model is ``extra='forbid'`` (T4), so any payload that
    sneaks in ``text`` / ``wa_chatid`` etc. is already rejected at the
    wire layer. This function trusts the schema and only enforces the
    rate-limit + logs ``collect_failed`` at WARNING so an operator alert
    can fire on a spike.
    """
    limit = settings.EXTENSION_TELEMETRY_RATE_PER_MINUTE
    now = time.monotonic()
    async with _TELEMETRY_RATE_LOCK:
        bucket = _TELEMETRY_RATE_BUCKETS.setdefault(user_id, deque())
        cutoff = now - _TELEMETRY_WINDOW_S
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            logger.info(
                "svc.extension.telemetry.rate_limited",
                extra={
                    "user_id": str(user_id),
                    "limit": limit,
                    "window_s": _TELEMETRY_WINDOW_S,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "rate_limited",
                    "limit": limit,
                    "window_s": int(_TELEMETRY_WINDOW_S),
                },
            )
        bucket.append(now)

    await repository.insert_telemetry(user_id, event)

    if event.event == "collect_failed":
        logger.warning(
            "svc.extension.telemetry.collect_failed",
            extra={
                "user_id": str(user_id),
                "event": event.event,
                "reason": event.reason,
                "extension_version": event.extension_version,
                "chats_total": event.chats_total,
                "chats_processed": event.chats_processed,
                "duration_ms": event.duration_ms,
            },
        )
    else:
        logger.info(
            "svc.extension.telemetry.recorded",
            extra={
                "user_id": str(user_id),
                "event": event.event,
                "extension_version": event.extension_version,
            },
        )


# ─── mobile lead ───────────────────────────────────────────────────────


async def capture_mobile_lead(req: MobileRedirectLeadCreate) -> None:
    """Persist a lead captured on the mobile block screen (no auth).

    The wire schema (:class:`MobileRedirectLeadCreate`) already enforces
    a valid email via :class:`pydantic.EmailStr`. RLS on
    ``mobile_redirect_leads`` grants INSERT to ``anon`` so no further
    auth or rate-limit is needed here — PostgREST + Supabase guard the
    table directly.
    """
    await repository.insert_mobile_lead(req)
    logger.info(
        "svc.extension.mobile_lead.captured",
        extra={
            "has_user_agent": req.user_agent is not None,
            "has_source_url": req.source_url is not None,
        },
    )


# ─── status ────────────────────────────────────────────────────────────


async def get_status(user_id: UUID) -> ExtensionStatusResponse:
    """Return the pairing + last-collection state for the user.

    If no install row exists, ``paired=False`` and the rest defaults to
    zero. When paired, we reuse :func:`captured_messages.stats_for_user`
    to surface ``last_collection_at`` (= last message timestamp) and
    ``last_collection_message_count`` — that's the cheapest signal the
    frontend needs to render "última coleta: X msgs".
    """
    install = await repository.get_install_for_user(user_id)
    if install is None:
        logger.info(
            "svc.extension.status.unpaired",
            extra={"user_id": str(user_id)},
        )
        return ExtensionStatusResponse(
            paired=False,
            last_collection_at=None,
            last_collection_message_count=0,
            extension_min_version=settings.EXTENSION_MIN_VERSION,
        )

    # Best-effort stats — if the helper errors we'd still rather return
    # paired=True than 500 the status endpoint, so we swallow + log.
    last_collection_at = None
    last_collection_message_count = 0
    try:
        from app.modules.captured_messages import repository as cap_repo

        stats = await cap_repo.stats_for_user(user_id)
        last_collection_at = stats.get("last_message_at")
        last_collection_message_count = int(stats.get("message_count") or 0)
    except Exception:
        logger.warning(
            "svc.extension.status.stats_failed",
            extra={"user_id": str(user_id)},
            exc_info=True,
        )

    logger.info(
        "svc.extension.status.paired",
        extra={
            "user_id": str(user_id),
            "install_id": install.get("install_id"),
            "message_count": last_collection_message_count,
        },
    )
    return ExtensionStatusResponse(
        paired=True,
        last_collection_at=last_collection_at,
        last_collection_message_count=last_collection_message_count,
        extension_min_version=settings.EXTENSION_MIN_VERSION,
    )


__all__ = [
    "pair_extension",
    "ingest_batch",
    "record_telemetry",
    "capture_mobile_lead",
    "get_status",
]
