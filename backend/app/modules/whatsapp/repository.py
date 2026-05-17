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


async def create(id: UUID, uazapi_token: str, status: str = "pending") -> None:
    """Insert a new session row in ``pending`` state (or the given status)."""
    row = {
        "id": str(id),
        "uazapi_token": uazapi_token,
        "status": status,
    }
    await asyncio.to_thread(lambda: _table().insert(row).execute())
    logger.info(
        "repo.create",
        extra={"session_id": str(id), "status": status},
    )


async def mark_status(id: UUID, status: str, **extra: Any) -> None:
    """Update ``status`` plus any of: ``phone_masked``, ``message_count``,
    ``extracted_at`` (datetime → ISO 8601), ``failed_code``.

    ``updated_at`` is intentionally **not** set here — the DB trigger handles
    it on every UPDATE.
    """
    payload: dict[str, Any] = {"status": status}

    allowed = {"phone_masked", "message_count", "extracted_at", "failed_code"}
    unknown = set(extra) - allowed
    if unknown:
        raise ValueError(f"unsupported mark_status fields: {sorted(unknown)}")

    for key in allowed:
        if key not in extra:
            continue
        value = extra[key]
        if key == "extracted_at" and isinstance(value, datetime):
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
