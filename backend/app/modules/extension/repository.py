"""Persistence repository for the Chrome extension module (F8 / §4.2).

Tables touched (all in schema ``medzee_spy``):

* ``whatsapp_sessions``      — synthetic row with ``provider='extension'``,
  ``status='connected'`` (FK target for ``captured_messages``). The legacy
  provider-token column on this table is nullable post-F8 and left NULL
  for extension-sourced rows.
* ``extension_telemetry``    — no-PII operational events (CHX-16).
* ``mobile_redirect_leads``  — ANON-writable lead capture from the mobile
  block screen.

PIVOT (2026-05-24): the ``extension_installs`` table is gone (dropped by
migration ``f8_2_drop_extension_installs``). The extension now
authenticates via Supabase login (email+password), so the install
registry — which only existed to back the custom JWT pairing dance —
served no further purpose.

All calls go through the Supabase ``service_role`` admin client (RLS
bypassed) — same pattern as ``captured_messages.repository``. The
synchronous supabase-py client is wrapped in :func:`asyncio.to_thread`
to keep the FastAPI event loop responsive.

Logging conventions:

* Every public function emits a single ``logger.info(...)`` line with
  structured ``extra=`` fields after a successful write.
* ``user_id`` is logged as a UUID string.
* ``ua`` (user agent) is **only** logged by its length, never by content,
  because UA strings can leak browser-version + OS-version fingerprints
  that we treat as low-grade PII.
* Telemetry / message text fields are not stored here; if a future change
  ever touches a row that has them, this module's logging must stay
  silent on them (mirrors the F4 rule in ``captured_messages``).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from app.clients.supabase import get_supabase_admin_client
from app.modules.extension.schemas import (
    ExtensionTelemetryEvent,
    MobileRedirectLeadCreate,
)

logger = logging.getLogger(__name__)


# ─── table handles ─────────────────────────────────────────────────────


def _sessions() -> Any:
    """Fresh ``medzee_spy.whatsapp_sessions`` table handle."""
    return (
        get_supabase_admin_client()
        .schema("medzee_spy")
        .table("whatsapp_sessions")
    )


def _telemetry() -> Any:
    """Fresh ``medzee_spy.extension_telemetry`` table handle."""
    return (
        get_supabase_admin_client()
        .schema("medzee_spy")
        .table("extension_telemetry")
    )


def _mobile_leads() -> Any:
    """Fresh ``medzee_spy.mobile_redirect_leads`` table handle."""
    return (
        get_supabase_admin_client()
        .schema("medzee_spy")
        .table("mobile_redirect_leads")
    )


# ─── whatsapp_sessions (extension provider) ────────────────────────────


async def get_or_create_extension_session(user_id: UUID) -> UUID:
    """Return the ``whatsapp_sessions.id`` for the user's extension session.

    Selects the row with ``user_id = ? AND provider = 'extension'``. If
    none exists, INSERTs a synthetic row with ``status='connected'`` and
    the legacy provider-token column left NULL (allowed since migration
    ``f8_1`` dropped the NOT NULL there). The unique partial index
    ``ux_whatsapp_sessions_extension_per_user`` guarantees at most one
    per user.

    Returns the session UUID either way.
    """
    user_id_str = str(user_id)

    def _select() -> Any:
        return (
            _sessions()
            .select("id")
            .eq("user_id", user_id_str)
            .eq("provider", "extension")
            .limit(1)
            .execute()
        )

    existing = await asyncio.to_thread(_select)
    rows: list[dict] = getattr(existing, "data", None) or []
    if rows:
        sid = UUID(str(rows[0]["id"]))
        logger.info(
            "repo.extension.session.reused",
            extra={"user_id": user_id_str, "whatsapp_session_id": str(sid)},
        )
        return sid

    # The legacy provider-token column is nullable post-F8; we omit it from
    # the INSERT so Postgres applies the column default (NULL).
    new_row = {
        "user_id": user_id_str,
        "provider": "extension",
        "status": "connected",
    }

    def _insert() -> Any:
        return _sessions().insert(new_row).execute()

    result = await asyncio.to_thread(_insert)
    data: list[dict] = getattr(result, "data", None) or []
    if not data:
        # The unique partial index may have raced us with another worker;
        # re-select and return whatever's there.
        again = await asyncio.to_thread(_select)
        again_rows: list[dict] = getattr(again, "data", None) or []
        if again_rows:
            sid = UUID(str(again_rows[0]["id"]))
            logger.info(
                "repo.extension.session.race_recovered",
                extra={
                    "user_id": user_id_str,
                    "whatsapp_session_id": str(sid),
                },
            )
            return sid
        raise RuntimeError(
            "get_or_create_extension_session: insert returned no rows and "
            "re-select found none"
        )

    sid = UUID(str(data[0]["id"]))
    logger.info(
        "repo.extension.session.created",
        extra={"user_id": user_id_str, "whatsapp_session_id": str(sid)},
    )
    return sid


# ─── extension_telemetry ───────────────────────────────────────────────


async def insert_telemetry(user_id: UUID, event: ExtensionTelemetryEvent) -> None:
    """Persist one telemetry event.

    No PII ever lands here — :class:`ExtensionTelemetryEvent` is
    ``extra='forbid'``, so the wire layer already rejects ``text`` /
    ``wa_chatid`` / ``contact_name``. ``ua`` is the only fingerprintable
    field; we store it but log only its length.
    """
    row = {
        "user_id": str(user_id),
        "event": event.event,
        "extension_version": event.extension_version,
        "reason": event.reason,
        "chats_total": event.chats_total,
        "chats_processed": event.chats_processed,
        "duration_ms": event.duration_ms,
        "ua": event.ua,
    }
    await asyncio.to_thread(
        lambda: _telemetry().insert(row).execute()
    )
    logger.info(
        "repo.extension.telemetry.insert",
        extra={
            "user_id": str(user_id),
            "event": event.event,
            "extension_version": event.extension_version,
            "ua_len": len(event.ua) if event.ua else 0,
        },
    )


# ─── mobile_redirect_leads ─────────────────────────────────────────────


async def insert_mobile_lead(item: MobileRedirectLeadCreate) -> None:
    """Insert a lead row captured from the mobile block screen.

    No auth context required — the table grants INSERT to ``anon`` (see
    migration ``f8_1``). We deliberately do not log the email body; only
    its presence + length, to keep log lines free of PII.
    """
    row = {
        "email": str(item.email),
        "user_agent": item.user_agent,
        "source_url": item.source_url,
    }
    await asyncio.to_thread(
        lambda: _mobile_leads().insert(row).execute()
    )
    logger.info(
        "repo.extension.mobile_lead.insert",
        extra={
            "email_len": len(str(item.email)),
            "ua_len": len(item.user_agent) if item.user_agent else 0,
            "has_source_url": item.source_url is not None,
        },
    )


__all__ = [
    "get_or_create_extension_session",
    "insert_telemetry",
    "insert_mobile_lead",
]
