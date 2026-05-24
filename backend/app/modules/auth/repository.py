"""Persistence repository for ``medzee_spy.users_profile``.

All operations use the Supabase **service_role** admin client. Profile rows
are inserted right after Supabase Auth creates the ``auth.users`` row, so we
need to bypass RLS for the bootstrap INSERT. Subsequent reads/updates still
go through the admin client here for consistency — the route layer enforces
authentication and ownership before calling into this module.

supabase-py 2.x is **synchronous** (requests under the hood), so every public
function in this module wraps the blocking call with :func:`asyncio.to_thread`
to keep the FastAPI event loop responsive. The lambdas capture the table
reference fresh on each call — the admin client is created per call in
:func:`app.clients.supabase.get_supabase_admin_client`, which is fine for our
volume and avoids leaking a long-lived service_role client across coroutines.

Sensitive fields:

* ``email`` is **never** logged in full. Only the domain (substring after
  ``@``) is emitted, as ``email_domain``, for low-cardinality observability.
* Passwords never reach this module — Supabase Auth owns credential storage.
* Full Supabase responses are never logged either; we emit structured fields
  (``user_id``, ``found``, ``fields``) only.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from app.clients.supabase import get_supabase_admin_client

logger = logging.getLogger(__name__)


# Fields the caller is allowed to mutate via :func:`update_profile`.
# ``email`` and ``user_id`` are intentionally excluded:
#   * ``user_id`` is the PK (immutable).
#   * ``email`` lives in ``auth.users`` — changing it here would desync the
#     two tables. Email changes must go through Supabase Auth and a separate
#     reconciliation flow (out of F2 scope).
_UPDATABLE_FIELDS: frozenset[str] = frozenset(
    {"name", "phone", "ticket_medio", "clinic_segment"}
)


def _table() -> Any:
    """Return a fresh table handle scoped to ``medzee_spy.users_profile``."""
    return get_supabase_admin_client().schema("medzee_spy").table("users_profile")


def _email_domain(email: str) -> str:
    """Extract the domain portion of an email for safe logging.

    Returns ``"unknown"`` if the input has no ``@`` separator (defensive —
    pydantic ``EmailStr`` should have already enforced shape upstream).
    """
    _, _, domain = email.partition("@")
    return domain or "unknown"


async def create_profile(
    user_id: UUID,
    *,
    name: str,
    email: str,
    phone: str,
    ticket_medio: float | None,
) -> None:
    """Insert a new ``users_profile`` row for a freshly signed-up user.

    Called by :class:`AuthService` immediately after ``auth.users`` creation
    succeeds. If this INSERT fails, the service is responsible for rolling
    back the auth user (best-effort) via :func:`delete_profile` is *not*
    used for that — auth rollback is a separate Supabase Auth admin call.
    """
    row: dict[str, Any] = {
        "user_id": str(user_id),
        "name": name,
        "email": email,
        "phone": phone,
        "ticket_medio": ticket_medio,
    }
    await asyncio.to_thread(lambda: _table().insert(row).execute())
    logger.info(
        "repo.auth.create_profile",
        extra={
            "user_id": str(user_id),
            "email_domain": _email_domain(email),
        },
    )


async def get_profile(user_id: UUID) -> dict | None:
    """Return the profile row as a dict, or ``None`` if not found.

    Keys returned (per schema): ``user_id``, ``name``, ``email``, ``phone``,
    ``ticket_medio``, ``clinic_segment``, ``created_at``, ``updated_at``.
    """
    result = await asyncio.to_thread(
        lambda: _table().select("*").eq("user_id", str(user_id)).limit(1).execute()
    )
    rows = getattr(result, "data", None) or []
    found = bool(rows)
    logger.info(
        "repo.auth.get_profile",
        extra={"user_id": str(user_id), "found": found},
    )
    if not found:
        return None
    return rows[0]


async def update_profile(user_id: UUID, **fields: Any) -> None:
    """Update one or more whitelisted profile fields.

    Whitelisted keys: ``name``, ``phone``, ``ticket_medio``, ``clinic_segment``.

    Raises ``ValueError`` if any disallowed key is passed (notably ``email``
    and ``user_id``, which are immutable here). If ``fields`` is empty after
    pydantic-style filtering (caller passed only ``None``s), this is a no-op
    and no Supabase call is made.

    ``updated_at`` is intentionally **not** set here — the DB trigger handles
    it on every UPDATE.
    """
    unknown = set(fields) - _UPDATABLE_FIELDS
    if unknown:
        raise ValueError(
            f"unsupported update_profile fields: {sorted(unknown)}"
        )

    # Drop ``None`` values so callers can pass an UpdateMeRequest.model_dump()
    # without forcing every field into the payload.
    payload: dict[str, Any] = {k: v for k, v in fields.items() if v is not None}

    if not payload:
        logger.info(
            "repo.auth.update_profile",
            extra={"user_id": str(user_id), "fields": [], "noop": True},
        )
        return

    await asyncio.to_thread(
        lambda: _table().update(payload).eq("user_id", str(user_id)).execute()
    )
    logger.info(
        "repo.auth.update_profile",
        extra={
            "user_id": str(user_id),
            "fields": sorted(payload.keys()),
            "noop": False,
        },
    )


async def delete_profile(user_id: UUID) -> None:
    """Delete a profile row.

    Used by :class:`AuthService` as part of the signup rollback path when
    ``create_profile`` succeeds but a downstream step (e.g. F1 session link)
    fails irrecoverably. Idempotent at the DB level — deleting a missing
    row is a no-op in PostgREST.
    """
    await asyncio.to_thread(
        lambda: _table().delete().eq("user_id", str(user_id)).execute()
    )
    logger.info(
        "repo.auth.delete_profile",
        extra={"user_id": str(user_id)},
    )
