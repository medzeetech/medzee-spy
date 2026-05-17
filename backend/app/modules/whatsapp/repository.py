"""Persistence repository for ``medzee_spy.whatsapp_sessions``.

All operations use the Supabase **service_role** admin client because sessions
are created *before* signup (no JWT yet), so RLS must be bypassed. F2 will
attach a ``user_id`` via :func:`link_user` once the user signs up; RLS then
naturally scopes downstream reads to the owner.

supabase-py 2.x is **synchronous** (requests under the hood), so every public
function in this module wraps the blocking call with :func:`asyncio.to_thread`
to keep the FastAPI event loop responsive. The lambdas capture the table
reference fresh on each call — the admin client is created per call in
:func:`app.clients.supabase.get_supabase_admin_client`, which is fine for our
volume and avoids leaking a long-lived service_role client across coroutines.

Sensitive fields:

* ``uazapi_token`` is **never** logged in full. If a future debug log needs
  any signal, use the last 6 chars only.
* Full Supabase responses are never logged either — they may echo the inserted
  row including the token. We log structured fields (``session_id``,
  ``status``, etc.) only.
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
    """Return a fresh table handle scoped to ``medzee_spy.whatsapp_sessions``."""
    return get_supabase_admin_client().schema("medzee_spy").table("whatsapp_sessions")


async def create(
    id: UUID,
    uazapi_token: str,
    status: str = "pending",
    user_id: UUID | None = None,
) -> None:
    """Insert a new session row in ``pending`` state (or the given status).

    ``user_id`` is set at creation when the caller is authenticated (F4:
    /app/connect for reconnect). Anonymous /spy flow leaves it ``None`` and
    :func:`link_user` fills it later when signup completes.
    """
    row: dict[str, Any] = {
        "id": str(id),
        "uazapi_token": uazapi_token,
        "status": status,
    }
    if user_id is not None:
        row["user_id"] = str(user_id)
    await asyncio.to_thread(lambda: _table().insert(row).execute())
    logger.info(
        "repo.create",
        extra={
            "session_id": str(id),
            "status": status,
            "user_id": str(user_id) if user_id else None,
        },
    )


async def mark_status(id: UUID, status: str, **extra: Any) -> None:
    """Update ``status`` plus any of: ``phone_masked``, ``message_count``,
    ``extracted_at`` (datetime → ISO 8601), ``failed_code``, ``connected_at``
    (F4 — datetime → ISO 8601; set when transitioning to 'connected' so the
    status card mostra "Conectado há X").

    ``updated_at`` is intentionally **not** set here — the DB trigger handles
    it on every UPDATE.
    """
    payload: dict[str, Any] = {"status": status}

    allowed = {
        "phone_masked",
        "message_count",
        "extracted_at",
        "failed_code",
        "connected_at",
    }
    unknown = set(extra) - allowed
    if unknown:
        raise ValueError(f"unsupported mark_status fields: {sorted(unknown)}")

    for key in allowed:
        if key not in extra:
            continue
        value = extra[key]
        if key in {"extracted_at", "connected_at"} and isinstance(value, datetime):
            value = value.isoformat()
        payload[key] = value

    await asyncio.to_thread(
        lambda: _table().update(payload).eq("id", str(id)).execute()
    )
    logger.info(
        "repo.mark_status",
        extra={
            "session_id": str(id),
            "status": status,
            "fields": sorted(k for k in payload if k != "status"),
        },
    )


async def mark_extracted(id: UUID, message_count: int) -> None:
    """Terminal-ish update used at the end of the extract pipeline."""
    payload = {
        "status": "extracted",
        "message_count": message_count,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }
    await asyncio.to_thread(
        lambda: _table().update(payload).eq("id", str(id)).execute()
    )
    logger.info(
        "repo.mark_extracted",
        extra={"session_id": str(id), "message_count": message_count},
    )


async def mark_failed(id: UUID, code: str) -> None:
    """Mark a session as failed with a stable error ``code``."""
    payload = {"status": "failed", "failed_code": code}
    await asyncio.to_thread(
        lambda: _table().update(payload).eq("id", str(id)).execute()
    )
    logger.info(
        "repo.mark_failed",
        extra={"session_id": str(id), "failed_code": code},
    )


async def mark_consumed(id: UUID) -> None:
    """Mark a session as consumed (called after F2 pulls the payload)."""
    payload = {"status": "consumed"}
    await asyncio.to_thread(
        lambda: _table().update(payload).eq("id", str(id)).execute()
    )
    logger.info("repo.mark_consumed", extra={"session_id": str(id)})


async def link_user(id: UUID, user_id: UUID) -> None:
    """Attach a freshly-signed-up user to a previously anonymous session.

    Called from F2 after the user completes signup. RLS picks up from here.
    """
    payload = {"user_id": str(user_id)}
    await asyncio.to_thread(
        lambda: _table().update(payload).eq("id", str(id)).execute()
    )
    logger.info(
        "repo.link_user",
        extra={"session_id": str(id), "user_id": str(user_id)},
    )


async def get(id: UUID) -> dict | None:
    """Return the session row as a dict, or ``None`` if not found."""
    result = await asyncio.to_thread(
        lambda: _table().select("*").eq("id", str(id)).limit(1).execute()
    )
    rows = getattr(result, "data", None) or []
    found = bool(rows)
    logger.info(
        "repo.get",
        extra={"session_id": str(id), "found": found},
    )
    if not found:
        return None
    return rows[0]


async def find_disconnected_before(cutoff: datetime) -> list[UUID]:
    """Return IDs of sessions in ``status='disconnected'`` whose
    ``updated_at`` is strictly older than ``cutoff``.

    Used by the F4 TTL cleanup loop (``app.workers.ttl_cleanup``) to find
    sessions whose captured_messages should be purged.

    NOTE on status filter: today ``'disconnected'`` is the typical terminal
    value after a user clicks Disconnect or uazapi reports ``LoggedOut``.
    Other terminals (``expired``, ``failed``, ``consumed``) are
    **intentionally excluded** — they have different lifecycles and the
    user pivoted F4 to only count ``'disconnected'`` as the TTL trigger.

    Returns ``[]`` when nothing has expired yet.
    """
    cutoff_iso = cutoff.isoformat()
    result = await asyncio.to_thread(
        lambda: _table()
        .select("id")
        .eq("status", "disconnected")
        .lt("updated_at", cutoff_iso)
        .execute()
    )
    rows = getattr(result, "data", None) or []
    ids = [UUID(row["id"]) for row in rows]
    logger.info(
        "repo.find_disconnected_before",
        extra={"cutoff": cutoff_iso, "count": len(ids)},
    )
    return ids


async def find_pending() -> list[dict]:
    """Return all sessions still in ``status='pending'`` in the DB.

    Used by the startup recovery path to re-spawn the connection-poll
    fallback for sessions that were created before a backend restart.
    Without recovery, those sessions would never transition from pending
    (in-memory state and poll task are both lost on restart).
    """
    result = await asyncio.to_thread(
        lambda: _table().select("*").eq("status", "pending").execute()
    )
    rows = getattr(result, "data", None) or []
    logger.info(
        "repo.find_pending",
        extra={"count": len(rows)},
    )
    return rows


async def get_active_for_user(user_id: UUID) -> dict | None:
    """Return the most recent session belonging to ``user_id``, or ``None``.

    Ordered by ``created_at`` desc — the most recently created session wins,
    even if older rows exist for the same user (those would have been
    disconnected/expired and are no longer "active"). The caller inspects
    ``status`` to decide whether the session is currently *connected*.
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
        "repo.get_active_for_user",
        extra={"user_id": str(user_id), "found": found},
    )
    if not found:
        return None
    return rows[0]
