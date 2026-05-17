"""Extract pipeline worker (F1 — design § 6).

Drives the 30-day WhatsApp history pull after the session transitions to
``CONNECTED``. Runs entirely off the request path — it's scheduled by the
webhook route via FastAPI ``BackgroundTasks``.

Algorithm (mirrors design § 6, gated by ``settings.EXTRACT_HARD_TIMEOUT_S``):

1. Validate the session is ``CONNECTED`` (idempotent guard — webhook may fire
   twice).
2. Flip status to ``EXTRACTING`` in both the in-memory store and the DB
   (DB is best-effort: a Supabase blip must not abort the extract).
3. Page through ``chat/find`` until ``has_more=False``.
4. Fan out one task per chat under an ``asyncio.Semaphore`` of
   ``EXTRACT_PARALLELISM`` chats; each task pages ``message/find`` and
   stops at the 30-day cutoff OR ``has_more=False``. Only text messages
   are kept (WPP-08 — media/audio/sticker dropped explicitly).
5. Aggregate, persist payload to the store (NOT to DB — WPP-10), update
   DB metadata, and emit the ``extracted`` SSE event.

Partial-results on hard timeout (EC-03 / design § 6 says "salvar o que tem
como partial=true"):

We accumulate ``ConversationPayload`` instances into a shared list as each
per-chat task completes (inside the lock-free section ``async with sem``),
*before* the gather returns. When ``asyncio.timeout`` fires, the running
tasks are cancelled but already-finished tasks have already pushed their
result onto the shared list — so ``_finalize_partial`` can mark
``partial=True`` and still emit ``extracted`` with whatever was collected.

Note on ``asyncio.timeout`` + ``gather``: the timeout is raised in the
context-manager body, which cancels the *current* task (the body) and
propagates ``CancelledError`` into ``await gather(...)``. ``gather`` does
*not* automatically cancel its child tasks when interrupted that way —
they keep running in the background. To make the cancel propagate cleanly
we wrap the gather call in a ``try/finally`` that explicitly cancels any
still-running per-chat tasks before re-raising. Without that, a slow chat
task would outlive the pipeline and burn provider quota.

Privacy / WPP-10:
* No message text, contact name, JID, or full uazapi token is ever logged.
* Token is referenced by its last 6 chars only in debug-level traces.
* Logs carry counts and elapsed_ms, nothing else.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.clients.whatsapp.errors import (
    UazapiBanned,
    UazapiError,
    UazapiTimeout,
    UazapiUnavailable,
)
from app.clients.whatsapp.types import Chat
from app.core.config import settings
from app.modules.whatsapp import repository
from app.modules.whatsapp.schemas import (
    ConversationPayload,
    ExtractedPayload,
    MessagePayload,
    SessionStatus,
    SSEEvent,
)
from app.modules.whatsapp.state import SessionState, session_store

logger = logging.getLogger(__name__)

# How often we emit a progress SSE event during the per-chat fan-out.
_PROGRESS_EVERY_N_CHATS: int = 5

# Page size used against uazapi for both chat/find and message/find.
_PAGE_SIZE: int = 100

# B3 fix (F3 §REPORT-14): uazapi free tier returns 500 on /chat/find
# immediately after `connected` — the internal history sync hasn't
# finished yet. Empirically 5s wasn't enough; bumped to 15s so we hit a
# higher probability of the first attempt succeeding (and reduce dependence
# on the retry budget). Tests monkeypatch this constant to 0 to stay fast.
_POST_CONNECTED_DELAY_S: float = 15.0


async def extract_30d_pipeline(session_id: UUID) -> None:
    """Run the 30-day extraction pipeline for ``session_id``.

    Entry-point scheduled by the webhook route. Catches every recoverable
    error and converts it to either an ``extracted`` (partial) or
    ``failed`` SSE event — never raises out of this coroutine.
    """
    started_at = time.monotonic()
    state = await session_store.get(session_id)
    if state is None:
        logger.warning(
            "extract pipeline: unknown session",
            extra={"session_id": str(session_id), "op": "extract"},
        )
        return
    if state.status != SessionStatus.CONNECTED:
        logger.info(
            "extract pipeline: skipping (not connected)",
            extra={
                "session_id": str(session_id),
                "op": "extract",
                "status": state.status.value,
            },
        )
        return

    # Defer the provider import to avoid eager httpx initialization at module
    # import time — the worker module is imported by the webhook route and we
    # want clean import-time semantics for the route tree.
    from app.clients.whatsapp import get_provider

    provider = get_provider()

    # --- mark EXTRACTING (store: authoritative for SSE; DB: best-effort) ---
    await session_store.update(session_id, status=SessionStatus.EXTRACTING)
    try:
        await repository.mark_status(session_id, "extracting")
    except Exception:
        # DB outage must not abort the extract — store stays authoritative.
        logger.warning(
            "extract pipeline: repo.mark_status(extracting) failed (ignored)",
            extra={"session_id": str(session_id), "op": "extract"},
        )

    cutoff_ts = int(
        (
            datetime.now(timezone.utc)
            - timedelta(days=settings.EXTRACT_DAYS_WINDOW)
        ).timestamp()
    )

    # Shared accumulator — populated as per-chat tasks finish, regardless of
    # whether the overall gather completes. This is what makes partial-on-
    # timeout work (see module docstring).
    conversations: list[ConversationPayload] = []
    total_chats: int = 0

    # B3: give uazapi free a head start on history sync (REPORT-14).
    if _POST_CONNECTED_DELAY_S > 0:
        await asyncio.sleep(_POST_CONNECTED_DELAY_S)

    try:
        async with asyncio.timeout(settings.EXTRACT_HARD_TIMEOUT_S):
            chats = await _list_all_chats(provider, state)
            total_chats = len(chats)

            await session_store.publish(
                session_id,
                SSEEvent(
                    name="extracting",
                    data={"collected": 0, "total_chats": total_chats},
                ),
            )

            await _fan_out_extract(
                provider=provider,
                state=state,
                session_id=session_id,
                chats=chats,
                cutoff_ts=cutoff_ts,
                conversations_out=conversations,
            )

            # All chats processed within the hard deadline → full payload.
            await _finalize_success(
                session_id=session_id,
                conversations=conversations,
                started_at=started_at,
                chat_count=total_chats,
            )

    except asyncio.TimeoutError:
        # EC-03 — hard timeout: keep whatever was collected and mark partial.
        await _finalize_partial(
            session_id=session_id,
            conversations=conversations,
            started_at=started_at,
            chat_count=total_chats,
        )
    except UazapiBanned:
        await _fail(
            session_id=session_id,
            state=state,
            code="banned",
            started_at=started_at,
            chat_count=total_chats,
        )
    except UazapiTimeout:
        await _fail(
            session_id=session_id,
            state=state,
            code="timeout",
            started_at=started_at,
            chat_count=total_chats,
        )
    except UazapiUnavailable:
        await _fail(
            session_id=session_id,
            state=state,
            code="uazapi_unavailable",
            started_at=started_at,
            chat_count=total_chats,
        )
    except UazapiError:
        await _fail(
            session_id=session_id,
            state=state,
            code="unknown",
            started_at=started_at,
            chat_count=total_chats,
        )
    except Exception:
        logger.exception(
            "extract pipeline crashed",
            extra={"session_id": str(session_id), "op": "extract"},
        )
        await _fail(
            session_id=session_id,
            state=state,
            code="extract_failed",
            started_at=started_at,
            chat_count=total_chats,
        )


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------


async def _list_all_chats(provider, state: SessionState) -> list[Chat]:
    """Paginate ``chat/find`` until ``has_more=False`` and return the union."""
    chats: list[Chat] = []
    offset = 0
    while True:
        page, has_more = await provider.list_chats(
            state.uazapi_token, limit=_PAGE_SIZE, offset=offset
        )
        chats.extend(page)
        if not has_more:
            break
        offset += _PAGE_SIZE
    return chats


async def _fan_out_extract(
    *,
    provider,
    state: SessionState,
    session_id: UUID,
    chats: list[Chat],
    cutoff_ts: int,
    conversations_out: list[ConversationPayload],
) -> None:
    """Fan out per-chat extraction under a semaphore.

    Results land in ``conversations_out`` (shared list) as each task
    finishes so a hard-timeout cancellation still leaves us with the
    work completed before the cutoff (see module docstring).

    On cancellation we explicitly cancel any still-running per-chat
    tasks because ``asyncio.gather`` does *not* propagate cancellation
    to its children when the awaiting coroutine is itself cancelled.
    """
    sem = asyncio.Semaphore(settings.EXTRACT_PARALLELISM)
    collected_chats: int = 0
    lock = asyncio.Lock()  # protects collected_chats counter

    async def _extract_chat(chat: Chat) -> None:
        nonlocal collected_chats
        async with sem:
            msgs: list[MessagePayload] = []
            msg_offset = 0
            while True:
                page, has_more, next_offset = await provider.list_messages(
                    state.uazapi_token,
                    chat.wa_chatid,
                    limit=_PAGE_SIZE,
                    offset=msg_offset,
                )
                old_found = False
                for m in page:
                    if m.ts < cutoff_ts:
                        old_found = True
                        break
                    if m.type == "text" and m.text:
                        msgs.append(
                            MessagePayload(
                                ts=m.ts,
                                from_me=m.from_me,
                                type=m.type,
                                text=m.text,
                            )
                        )
                if old_found or not has_more:
                    break
                msg_offset = next_offset

            if msgs:
                conversations_out.append(
                    ConversationPayload(
                        wa_chatid=chat.wa_chatid,
                        contact_name=chat.contact_name,
                        is_group=chat.is_group,
                        last_message_at=chat.last_message_at,
                        messages=msgs,
                    )
                )

            async with lock:
                collected_chats += 1
                snapshot = collected_chats

            if snapshot % _PROGRESS_EVERY_N_CHATS == 0:
                await session_store.publish(
                    session_id,
                    SSEEvent(
                        name="extracting",
                        data={
                            "collected": snapshot,
                            "total_chats": len(chats),
                        },
                    ),
                )

    tasks = [asyncio.create_task(_extract_chat(c)) for c in chats]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        # Hard-timeout (CancelledError) or unexpected raise from a child:
        # cancel siblings so they don't keep hammering uazapi after we've
        # already given up. Then re-raise to the outer handler.
        for t in tasks:
            if not t.done():
                t.cancel()
        # Drain cancellations so they don't surface as "Task was destroyed
        # but it is pending!" warnings.
        for t in tasks:
            try:
                await t
            except BaseException:
                pass
        raise


async def _finalize_success(
    *,
    session_id: UUID,
    conversations: list[ConversationPayload],
    started_at: float,
    chat_count: int,
) -> None:
    """Build payload, persist, publish ``extracted`` (non-partial)."""
    payload = ExtractedPayload(
        message_count=sum(len(c.messages) for c in conversations),
        conversation_count=len(conversations),
        conversations=conversations,
        partial=False,
    )
    await session_store.set_payload(session_id, payload)
    await session_store.update(
        session_id,
        status=SessionStatus.EXTRACTED,
        message_count=payload.message_count,
    )
    try:
        await repository.mark_extracted(session_id, payload.message_count)
    except Exception:
        # DB blip — store still has the payload; F2 can still consume it.
        logger.warning(
            "extract pipeline: repo.mark_extracted failed (ignored)",
            extra={"session_id": str(session_id), "op": "extract"},
        )

    await session_store.publish(
        session_id,
        SSEEvent(
            name="extracted",
            data={
                "message_count": payload.message_count,
                "conversation_count": payload.conversation_count,
            },
        ),
    )

    # F3 §REPORT-11: kick off the report generation pipeline.
    _kick_off_report(session_id, payload)

    logger.info(
        "extract pipeline completed",
        extra={
            "session_id": str(session_id),
            "op": "extract",
            "status": "extracted",
            "chat_count": chat_count,
            "conversation_count": payload.conversation_count,
            "message_count": payload.message_count,
            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
            "partial": False,
        },
    )


async def _finalize_partial(
    *,
    session_id: UUID,
    conversations: list[ConversationPayload],
    started_at: float,
    chat_count: int,
) -> None:
    """Build a partial payload from whatever the per-chat tasks managed to
    finish before the hard timeout fired, then emit ``extracted`` with
    ``partial=True`` (EC-03 / design § 6 partial-save semantics).
    """
    payload = ExtractedPayload(
        message_count=sum(len(c.messages) for c in conversations),
        conversation_count=len(conversations),
        conversations=conversations,
        partial=True,
    )
    await session_store.set_payload(session_id, payload)
    await session_store.update(
        session_id,
        status=SessionStatus.EXTRACTED,
        message_count=payload.message_count,
    )
    try:
        await repository.mark_extracted(session_id, payload.message_count)
    except Exception:
        logger.warning(
            "extract pipeline: repo.mark_extracted(partial) failed (ignored)",
            extra={"session_id": str(session_id), "op": "extract"},
        )

    await session_store.publish(
        session_id,
        SSEEvent(
            name="extracted",
            data={
                "message_count": payload.message_count,
                "conversation_count": payload.conversation_count,
                "partial": True,
            },
        ),
    )

    # F3 §REPORT-11: still kick off the report generation on partial.
    # The worker handles ``payload.partial=True`` via update_partial.
    _kick_off_report(session_id, payload)

    logger.warning(
        "extract pipeline hard-timeout: saved partial",
        extra={
            "session_id": str(session_id),
            "op": "extract",
            "status": "extracted",
            "chat_count": chat_count,
            "conversation_count": payload.conversation_count,
            "message_count": payload.message_count,
            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
            "partial": True,
        },
    )


async def _fail(
    *,
    session_id: UUID,
    state: SessionState,
    code: str,
    started_at: float,
    chat_count: int,
) -> None:
    """Best-effort delete + publish ``failed`` SSE + persist failure."""
    # uazapi's DELETE /instance disconnects + removes the row in one call,
    # freeing the device slot. Never let cleanup errors mask the original
    # failure — log and continue.
    from app.clients.whatsapp import get_provider

    try:
        await get_provider().delete_instance(state.uazapi_token)
    except Exception:
        logger.warning(
            "extract pipeline: provider.delete_instance failed (ignored)",
            extra={"session_id": str(session_id), "op": "extract"},
        )

    await session_store.publish(
        session_id,
        SSEEvent(
            name="failed",
            data={"code": code, "message": f"extract {code}"},
        ),
    )
    await session_store.update(
        session_id,
        status=SessionStatus.FAILED,
        failed_code=code,
    )
    try:
        await repository.mark_failed(session_id, code)
    except Exception:
        logger.warning(
            "extract pipeline: repo.mark_failed failed (ignored)",
            extra={"session_id": str(session_id), "op": "extract"},
        )

    logger.error(
        "extract pipeline failed",
        extra={
            "session_id": str(session_id),
            "op": "extract",
            "status": "failed",
            "failed_code": code,
            "chat_count": chat_count,
            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
        },
    )

    # F3: se já existe row de reports pra essa session (placeholder criado
    # pelo signup), marca como failed pra frontend parar de polar com
    # status='generating' eterno.
    await _mark_report_failed_for_session(session_id, code)


async def _mark_report_failed_for_session(session_id: UUID, code: str) -> None:
    """Best-effort: marca a row reports vinculada como failed."""
    try:
        from app.modules.reports import repository as reports_repo
        existing = await reports_repo.get_existing_for_session(session_id)
        if existing is None:
            return  # Nenhuma row foi criada — nada a fazer.
        report_id = UUID(str(existing["id"]))
        await reports_repo.update_failed(
            report_id, error_code=f"extract_{code}"
        )
        logger.info(
            "extract pipeline: linked report marked failed",
            extra={
                "op": "extract",
                "session_id": str(session_id),
                "report_id": str(report_id),
                "error_code": f"extract_{code}",
            },
        )
    except Exception:
        logger.warning(
            "extract pipeline: mark_report_failed failed (ignored)",
            extra={"op": "extract", "session_id": str(session_id)},
            exc_info=True,
        )


# ─── F3 integration: kick off report generation ───────────────────────


def _kick_off_report(session_id: UUID, payload: ExtractedPayload) -> None:
    """Spawn the report generation worker fire-and-forget.

    Lazy-imports ``app.workers.report`` to avoid an import cycle and to keep
    this module usable even if F3 hasn't been merged yet (defensive — if the
    import fails we just log and skip).

    The user_id is resolved best-effort from ``whatsapp_sessions.user_id``
    (may be null if signup hasn't happened yet; F2's ``consume_extracted``
    will link the report row when signup arrives).
    """
    try:
        from app.workers.report import generate_report_pipeline
    except ImportError:
        logger.warning(
            "extract pipeline: report worker import failed — skipping",
            extra={"session_id": str(session_id), "op": "extract"},
        )
        return

    asyncio.create_task(
        _run_report_with_user(session_id, payload, generate_report_pipeline),
        name=f"report-{session_id}",
    )


async def _run_report_with_user(
    session_id: UUID,
    payload: ExtractedPayload,
    pipeline,
) -> None:
    """Resolve user_id from DB row, then call ``generate_report_pipeline``."""
    user_id: UUID | None = None
    try:
        row = await repository.get(session_id)
        if row and row.get("user_id"):
            user_id = UUID(str(row["user_id"]))
    except Exception:
        logger.warning(
            "extract pipeline: failed resolving user_id for report — proceeding null",
            extra={"session_id": str(session_id), "op": "extract"},
            exc_info=True,
        )

    await pipeline(session_id, payload, user_id=user_id)


__all__ = ["extract_30d_pipeline"]
