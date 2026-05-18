"""Persistence repository for ``medzee_spy.captured_messages``.

All operations use the Supabase **service_role** admin client. Captured
messages are written by the F4 ingestion worker before any user-facing
auth context is in play (the webhook handler runs server-to-server from
uazapi), so RLS is bypassed at this layer. Read paths exposed to the API
(``query_window_for_user``, ``stats_for_user``) defensively filter by
``user_id`` even though RLS already scopes ownership.

supabase-py 2.x is **synchronous** (requests under the hood), so every
public function in this module wraps the blocking call with
:func:`asyncio.to_thread` to keep the FastAPI event loop responsive. The
lambdas capture the table reference fresh on each call — the admin client
is created per call in :func:`app.clients.supabase.get_supabase_admin_client`,
which is fine for our volume and avoids leaking a long-lived service_role
client across coroutines.

Dedup strategy:

The table has a partial unique index on
``(whatsapp_session_id, raw_message_id) WHERE raw_message_id IS NOT NULL``
so that the uazapi webhook can be replayed (at-least-once delivery) without
producing duplicate rows. :func:`insert_many` uses PostgREST's
``upsert(..., on_conflict='whatsapp_session_id,raw_message_id',
ignore_duplicates=True)`` — postgrest 0.17.x supports this exact signature
(verified via vendor inspection). With ``ignore_duplicates=True`` PostgREST
emits ``Prefer: resolution=ignore-duplicates``, which translates to
``INSERT ... ON CONFLICT DO NOTHING`` server-side. The response only
contains the rows that were *actually* inserted, which is what we use to
compute the return value.

Sensitive fields:

* ``text`` (the message body) is **never** logged. It may contain PHI /
  patient-identifying content from clinic conversations.
* ``contact_name`` is likewise omitted from logs.
* Full Supabase responses are never logged either; we emit structured
  fields (``count``, ``user_id``, ``whatsapp_session_id``, ``range``,
  ``rows_inserted``, ``rows_affected``) only.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from app.clients.supabase import get_supabase_admin_client
from app.modules.captured_messages.schemas import (
    CapturedMessage,
    CapturedMessageInsert,
)

logger = logging.getLogger(__name__)


# Composite conflict target matching the partial unique index defined in
# the F4 migration. Keep this in sync with the index definition.
_ON_CONFLICT: str = "whatsapp_session_id,raw_message_id"


def _table() -> Any:
    """Return a fresh table handle scoped to ``medzee_spy.captured_messages``."""
    return (
        get_supabase_admin_client()
        .schema("medzee_spy")
        .table("captured_messages")
    )


def _serialize(item: CapturedMessageInsert) -> dict[str, Any]:
    """Convert a :class:`CapturedMessageInsert` to a JSON-safe row dict.

    UUIDs are stringified and ``datetime`` is rendered as ISO 8601 — the
    PostgREST HTTP layer requires both. ``model_dump(mode='json')`` would
    almost do this but pydantic emits ``UUID`` as a plain string and
    ``datetime`` as ISO already, so we just normalise explicitly to keep
    the wire format deterministic and easy to grep in logs.
    """
    return {
        "user_id": str(item.user_id),
        "whatsapp_session_id": str(item.whatsapp_session_id),
        "wa_chatid": item.wa_chatid,
        "contact_name": item.contact_name,
        "ts": item.ts.isoformat(),
        "is_from_me": item.is_from_me,
        "message_type": item.message_type,
        "text": item.text,
        "raw_message_id": item.raw_message_id,
    }


async def insert_many(items: list[CapturedMessageInsert]) -> int:
    """Bulk insert captured messages, ignoring duplicates by raw_message_id.

    Rows that collide on the
    ``(whatsapp_session_id, raw_message_id)`` partial unique index are
    silently skipped (NOT an error). This makes the webhook safe to retry —
    uazapi has at-least-once delivery semantics, so the same event can land
    twice.

    Returns the number of rows **actually inserted** (excluding silently
    ignored duplicates). PostgREST's response with
    ``Prefer: resolution=ignore-duplicates`` only includes truly-inserted
    rows, so ``len(result.data)`` is the right count.

    Empty input is a no-op and returns 0 without hitting Supabase.
    """
    requested = len(items)
    if requested == 0:
        logger.info(
            "repo.captured.insert_many",
            extra={"count": 0, "rows_inserted": 0, "noop": True},
        )
        return 0

    rows = [_serialize(item) for item in items]
    result = await asyncio.to_thread(
        lambda: _table()
        .upsert(
            rows,
            on_conflict=_ON_CONFLICT,
            ignore_duplicates=True,
        )
        .execute()
    )
    returned = getattr(result, "data", None) or []
    rows_inserted = len(returned)
    logger.info(
        "repo.captured.insert_many",
        extra={
            "count": requested,
            "rows_inserted": rows_inserted,
            "rows_skipped": requested - rows_inserted,
        },
    )
    return rows_inserted


async def query_window_for_user(
    user_id: UUID,
    *,
    since: datetime,
    until: datetime | None = None,
) -> list[CapturedMessage]:
    """Return messages for a user within a half-open time window.

    Filters: ``user_id = ?`` AND ``ts >= since`` AND (when ``until`` is
    provided) ``ts < until``. Results are ordered by ``ts`` ascending so
    the F3 report generator can stream the conversation in chronological
    order.

    Returns parsed :class:`CapturedMessage` instances (pydantic handles
    the ISO 8601 → ``datetime`` coercion automatically). Returns ``[]`` if
    no rows match.
    """
    since_iso = since.isoformat()
    until_iso = until.isoformat() if until is not None else None

    def _run() -> Any:
        q = (
            _table()
            .select("*")
            .eq("user_id", str(user_id))
            .gte("ts", since_iso)
        )
        if until_iso is not None:
            q = q.lt("ts", until_iso)
        return q.order("ts", desc=False).execute()

    result = await asyncio.to_thread(_run)
    raw_rows: list[dict] = getattr(result, "data", None) or []
    parsed = [CapturedMessage.model_validate(row) for row in raw_rows]
    logger.info(
        "repo.captured.query_window",
        extra={
            "user_id": str(user_id),
            "count": len(parsed),
            "range": f"{since_iso}..{until_iso or 'open'}",
        },
    )
    return parsed


def _compute_stats(rows: list[dict]) -> dict[str, Any]:
    """Reduce a list of message rows to ``{message_count, conversation_count,
    last_message_at}``.

    Computed client-side: supabase-py / PostgREST does not expose ``DISTINCT``
    aggregations cleanly without a stored function, and the captured_messages
    rows are small (chat id + timestamp). For the volumes we deal with
    (single-user window) one full scan is fine — if this ever becomes a hot
    path we can promote it to a Postgres view or RPC.
    """
    if not rows:
        return {
            "message_count": 0,
            "conversation_count": 0,
            "last_message_at": None,
        }
    chatids: set[str] = set()
    last_ts: datetime | None = None
    for row in rows:
        chatid = row.get("wa_chatid")
        if chatid:
            chatids.add(chatid)
        ts_raw = row.get("ts")
        if ts_raw is None:
            continue
        # PostgREST returns ISO 8601 strings; parse defensively in case the
        # driver ever hands us a datetime directly.
        if isinstance(ts_raw, datetime):
            ts = ts_raw
        else:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        if last_ts is None or ts > last_ts:
            last_ts = ts
    return {
        "message_count": len(rows),
        "conversation_count": len(chatids),
        "last_message_at": last_ts,
    }


async def query_last_n_per_chat(
    user_id: UUID, *, n_per_chat: int = 30
) -> list[CapturedMessage]:
    """Retorna as últimas ``n_per_chat`` mensagens de cada conversa do user.

    Sem janela temporal. Estratégia equivalente ao F5 pipeline
    (:func:`app.workers.extract.pull_last_n_per_chat`) — útil quando o
    webhook está funcionando e o cache local já tem mensagens.

    Implementação: lê tudo do user (snapshot pode crescer, mas no MVP é
    pequeno) e faz top-N por wa_chatid em Python. Em produção com alto
    volume virar window function PostgreSQL.

    Returns:
        Lista plana de :class:`CapturedMessage`, ordenada por
        (wa_chatid asc, ts asc) — pronta pra agrupar no serviço.
    """
    n_per_chat = max(1, min(int(n_per_chat), 100))

    def _run() -> Any:
        # Limita por user_id; sem cutoff temporal. Ordena por (wa_chatid, ts desc)
        # pra pegar fácil os últimos N por chat.
        return (
            _table()
            .select("*")
            .eq("user_id", str(user_id))
            .order("wa_chatid", desc=False)
            .order("ts", desc=True)
            .execute()
        )

    result = await asyncio.to_thread(_run)
    raw_rows: list[dict] = getattr(result, "data", None) or []

    # Top-N por wa_chatid mantendo ordem desc (mais recente primeiro).
    seen_per_chat: dict[str, int] = {}
    kept: list[dict] = []
    for row in raw_rows:
        chatid = row.get("wa_chatid") or ""
        current = seen_per_chat.get(chatid, 0)
        if current < n_per_chat:
            kept.append(row)
            seen_per_chat[chatid] = current + 1

    parsed = [CapturedMessage.model_validate(row) for row in kept]
    logger.info(
        "repo.captured.query_last_n_per_chat",
        extra={
            "user_id": str(user_id),
            "n_per_chat": n_per_chat,
            "total_rows_scanned": len(raw_rows),
            "kept_after_topN": len(parsed),
            "conversation_count": len(seen_per_chat),
        },
    )
    return parsed


async def stats_for_user(user_id: UUID) -> dict:
    """Return aggregate stats over **all** captured messages for a user.

    Shape: ``{message_count: int, conversation_count: int,
    last_message_at: datetime | None}``. ``conversation_count`` is the
    number of distinct ``wa_chatid`` values.

    Empty result is ``{0, 0, None}`` — see :func:`_compute_stats`.
    """
    result = await asyncio.to_thread(
        lambda: _table()
        .select("wa_chatid,ts")
        .eq("user_id", str(user_id))
        .execute()
    )
    rows: list[dict] = getattr(result, "data", None) or []
    stats = _compute_stats(rows)
    logger.info(
        "repo.captured.stats_for_user",
        extra={
            "user_id": str(user_id),
            "message_count": stats["message_count"],
            "conversation_count": stats["conversation_count"],
        },
    )
    return stats


async def stats_for_session(session_id: UUID) -> dict:
    """Return aggregate stats scoped to a single WhatsApp session.

    Same response shape as :func:`stats_for_user`. Used by
    ``GET /api/whatsapp/status`` to surface "messages captured so far" for
    the currently-connected session without leaking historical counts from
    a previous re-pair.
    """
    result = await asyncio.to_thread(
        lambda: _table()
        .select("wa_chatid,ts")
        .eq("whatsapp_session_id", str(session_id))
        .execute()
    )
    rows: list[dict] = getattr(result, "data", None) or []
    stats = _compute_stats(rows)
    logger.info(
        "repo.captured.stats_for_session",
        extra={
            "whatsapp_session_id": str(session_id),
            "message_count": stats["message_count"],
            "conversation_count": stats["conversation_count"],
        },
    )
    return stats


async def delete_for_session(session_id: UUID) -> int:
    """Hard-delete every captured message for a WhatsApp session.

    Used by the TTL / session-rotation flow when a WhatsApp pairing is
    revoked or expires: we drop the captured history so the next pairing
    starts clean and we honour the data-retention contract.

    Returns the count of deleted rows. PostgREST returns the deleted
    rows in ``result.data`` when the default ``returning=representation``
    is used, so ``len(...)`` is the affected-row count.
    """
    result = await asyncio.to_thread(
        lambda: _table()
        .delete()
        .eq("whatsapp_session_id", str(session_id))
        .execute()
    )
    rows = getattr(result, "data", None) or []
    rows_affected = len(rows)
    logger.info(
        "repo.captured.delete_for_session",
        extra={
            "whatsapp_session_id": str(session_id),
            "rows_affected": rows_affected,
        },
    )
    return rows_affected


__all__ = [
    "insert_many",
    "query_window_for_user",
    "query_last_n_per_chat",
    "stats_for_user",
    "stats_for_session",
    "delete_for_session",
]
