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
    """Bulk insert captured messages, dedup'ing duplicates by raw_message_id.

    **Fix 2026-05-19**: o ``upsert(on_conflict='whatsapp_session_id,
    raw_message_id', ignore_duplicates=True)`` original quebrava com
    PostgREST APIError ``42P10`` ("no unique or exclusion constraint
    matching the ON CONFLICT specification"), porque o índice
    ``ux_captured_messages_dedup`` é **partial** (``WHERE raw_message_id IS
    NOT NULL``) e PostgREST não consegue referenciá-lo via
    ``on_conflict=<cols>`` — só por nome de constraint normal. Resultado:
    TODO insert via webhook quebrava → ``captured_messages`` ficava vazia.

    Nova estratégia:
        1. **Dedup batch em Python** por ``(whatsapp_session_id,
           raw_message_id)`` — evita duplicatas dentro do mesmo webhook.
        2. **Plain INSERT** (sem on_conflict).
        3. Em ``unique_violation`` (code 23505) — retry one-by-one
           pulando os que conflitam (cobre at-least-once cross-batch
           do webhook uazapi).

    Empty input é no-op e retorna 0 sem hit no Supabase.
    """
    requested = len(items)
    if requested == 0:
        logger.info(
            "repo.captured.insert_many",
            extra={"count": 0, "rows_inserted": 0, "noop": True},
        )
        return 0

    # 1. Dedup em memória — uazapi webhook pode mandar a mesma msg 2x
    # no mesmo batch (raro mas observado em paid).
    seen: set[tuple[str, str]] = set()
    unique_items: list[CapturedMessageInsert] = []
    for it in items:
        key = (str(it.whatsapp_session_id), it.raw_message_id or "")
        if it.raw_message_id and key in seen:
            continue
        seen.add(key)
        unique_items.append(it)

    rows = [_serialize(item) for item in unique_items]

    # 2. Plain INSERT (sem on_conflict — o partial index ainda protege
    #    em profundidade, dispara 23505 que tratamos abaixo).
    try:
        result = await asyncio.to_thread(
            lambda: _table().insert(rows).execute()
        )
        rows_inserted = len(getattr(result, "data", None) or [])
    except Exception as exc:
        # 3. Fallback row-by-row se algum raw_message_id colidiu com
        #    insert anterior (webhook at-least-once cross-batch).
        msg = str(exc)
        if "23505" not in msg and "duplicate" not in msg.lower():
            logger.exception(
                "repo.captured.insert_many.fatal",
                extra={"count": requested, "error": msg[:200]},
            )
            raise
        logger.info(
            "repo.captured.insert_many.batch_conflict_fallback_one_by_one",
            extra={"count": len(rows)},
        )
        rows_inserted = 0
        for r in rows:
            try:
                res = await asyncio.to_thread(
                    lambda r=r: _table().insert(r).execute()
                )
                rows_inserted += len(getattr(res, "data", None) or [])
            except Exception as inner:
                inner_msg = str(inner)
                if "23505" in inner_msg or "duplicate" in inner_msg.lower():
                    continue  # ok, duplicate cross-batch
                logger.warning(
                    "repo.captured.insert_many.row_failed",
                    extra={"error": inner_msg[:200]},
                )

    logger.info(
        "repo.captured.insert_many",
        extra={
            "count": requested,
            "unique_in_batch": len(unique_items),
            "rows_inserted": rows_inserted,
            "rows_skipped_batch_dedup": requested - len(unique_items),
            "rows_skipped_cross_batch": len(unique_items) - rows_inserted,
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


def _compute_stats_from_sample(
    rows: list[dict], total_count: int
) -> dict[str, Any]:
    """Build stats dict de uma amostra (max ~1000 rows) + total exato.

    **Fix 2026-05-19**: PostgREST limita Range a 0-999 por default. A versão
    antiga contava ``len(rows)`` direto, retornando 1000 mesmo com 8.6k
    msgs reais no DB. Agora ``total_count`` vem de ``count="exact"`` no
    select e é a fonte de verdade pro ``message_count``.

    ``conversation_count`` e ``last_message_at`` são derivados da amostra
    (subestimação aceitável em corner cases com >1000 msgs).
    """
    if total_count == 0 and not rows:
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
        if isinstance(ts_raw, datetime):
            ts = ts_raw
        else:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        if last_ts is None or ts > last_ts:
            last_ts = ts
    return {
        "message_count": total_count,
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
        #
        # Limit alto explícito: PostgREST tem default Range 0-999 que truncaria
        # um user com 50+ chats * 30 msgs = 1500 linhas. 10_000 cobre folgadamente
        # até ~330 chats × 30 msgs; pra além disso, virar window function SQL.
        return (
            _table()
            .select("*")
            .eq("user_id", str(user_id))
            .order("wa_chatid", desc=False)
            .order("ts", desc=True)
            .limit(10_000)
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
    last_message_at: datetime | None}``.

    Usa ``count="exact"`` (PostgREST header ``Prefer: count=exact``) pra
    obter o ``message_count`` REAL sem truncar no limite default de 1000
    rows por request. A amostra ordenada por ``ts desc`` é usada pra
    derivar ``conversation_count`` + ``last_message_at``.
    """
    result = await asyncio.to_thread(
        lambda: _table()
        .select("wa_chatid,ts", count="exact")
        .eq("user_id", str(user_id))
        .order("ts", desc=True)
        .limit(1000)
        .execute()
    )
    rows: list[dict] = getattr(result, "data", None) or []
    total = getattr(result, "count", None)
    if total is None:
        total = len(rows)
    stats = _compute_stats_from_sample(rows, total)
    logger.info(
        "repo.captured.stats_for_user",
        extra={
            "user_id": str(user_id),
            "message_count": stats["message_count"],
            "conversation_count": stats["conversation_count"],
            "sample_rows": len(rows),
        },
    )
    return stats


async def stats_for_session(session_id: UUID) -> dict:
    """Return aggregate stats scoped to a single WhatsApp session.

    Mesma estratégia que :func:`stats_for_user` — ``count="exact"`` pra
    evitar truncamento em 1000 rows.
    """
    result = await asyncio.to_thread(
        lambda: _table()
        .select("wa_chatid,ts", count="exact")
        .eq("whatsapp_session_id", str(session_id))
        .order("ts", desc=True)
        .limit(1000)
        .execute()
    )
    rows: list[dict] = getattr(result, "data", None) or []
    total = getattr(result, "count", None)
    if total is None:
        total = len(rows)
    stats = _compute_stats_from_sample(rows, total)
    logger.info(
        "repo.captured.stats_for_session",
        extra={
            "whatsapp_session_id": str(session_id),
            "message_count": stats["message_count"],
            "conversation_count": stats["conversation_count"],
            "sample_rows": len(rows),
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
