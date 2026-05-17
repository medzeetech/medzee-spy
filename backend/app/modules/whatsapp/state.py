"""In-memory ``SessionStore`` with per-session pub/sub for SSE subscribers.

Implements the state layer described in design.md §5:

* `SessionState` — full per-session record (token, status, QR, payload,
  subscriber queues, timestamps). Lives only in process memory; the database
  side is handled by `repository.py`.
* `SessionStore` — async-safe singleton. Writes go under `self._lock`; reads
  (`get`) and per-subscriber queue receives are lock-free since dict lookups
  and `asyncio.Queue` are themselves coroutine-safe.
* TTL background loop — wakes every 60s and expires non-terminal sessions
  older than ``settings.SESSION_TTL_MINUTES`` (WPP-14/EC-05).

Per WPP-15, subscribers attached to a session already in a terminal status
receive `last_event` and the generator returns, closing the SSE stream.

Logging is intentionally minimal regarding PII: `uazapi_token`, `qr_base64`,
and payload contents are never written to logs — only counts, transitions
and session IDs.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from uuid import UUID

from app.core.config import settings
from app.modules.whatsapp.schemas import (
    ExtractedPayload,
    SessionStatus,
    SSEEvent,
)

logger = logging.getLogger(__name__)

# Statuses that mean "stream is done, do not keep the SSE connection open".
_TERMINAL_STATUSES: frozenset[SessionStatus] = frozenset(
    {
        SessionStatus.EXTRACTED,
        SessionStatus.CONSUMED,
        SessionStatus.FAILED,
        SessionStatus.EXPIRED,
    }
)

# Statuses that the TTL expire loop should leave alone (already done).
_EXPIRE_EXEMPT: frozenset[SessionStatus] = frozenset(
    {
        SessionStatus.CONSUMED,
        SessionStatus.FAILED,
        SessionStatus.EXPIRED,
    }
)

# Event names that close the SSE stream once received.
_TERMINAL_EVENT_NAMES: frozenset[str] = frozenset({"extracted", "failed", "expired"})

# Max events buffered per subscriber before drop-oldest kicks in.
_SUBSCRIBER_QUEUE_MAX: int = 32


@dataclass
class SessionState:
    """Per-session in-memory record. See design.md §5.1."""

    session_id: UUID
    uazapi_token: str
    status: SessionStatus = SessionStatus.PENDING
    qr_base64: str | None = None
    phone_masked: str | None = None
    payload: ExtractedPayload | None = None
    last_event: SSEEvent | None = None
    subscribers: list[asyncio.Queue[SSEEvent]] = field(default_factory=list)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    failed_code: str | None = None
    message_count: int = 0


class SessionStore:
    """Async-safe in-memory store with per-session pub/sub.

    Locking strategy: ``self._lock`` is held only across mutations of
    ``self._sessions`` and ``SessionState`` fields (`create`, `update`,
    `publish`'s state mutation). Reads (`get`) and per-queue receives are
    safe without the lock because Python dict lookups are atomic and
    `asyncio.Queue` is itself coroutine-safe.
    """

    def __init__(self) -> None:
        self._sessions: dict[UUID, SessionState] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._expire_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ CRUD

    async def create(
        self,
        session_id: UUID,
        uazapi_token: str,
        qr_base64: str,
    ) -> SessionState:
        """Register a new pending session under the lock and return it."""
        async with self._lock:
            state = SessionState(
                session_id=session_id,
                uazapi_token=uazapi_token,
                qr_base64=qr_base64,
                status=SessionStatus.PENDING,
            )
            self._sessions[session_id] = state
        logger.info(
            "session created",
            extra={"session_id": str(session_id), "op": "create", "status": state.status.value},
        )
        return state

    async def get(self, session_id: UUID) -> SessionState | None:
        """Lock-free read — dict lookup is atomic under CPython's GIL."""
        return self._sessions.get(session_id)

    async def update(self, session_id: UUID, **fields: Any) -> None:
        """Atomically set one or more fields on the session under the lock."""
        async with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                logger.warning(
                    "update on unknown session",
                    extra={"session_id": str(session_id), "op": "update"},
                )
                return
            prev_status = state.status
            for key, value in fields.items():
                if not hasattr(state, key):
                    logger.warning(
                        "update with unknown field ignored",
                        extra={
                            "session_id": str(session_id),
                            "op": "update",
                            "field": key,
                        },
                    )
                    continue
                # Skip mutable PII fields in the log loop — setattr only.
                setattr(state, key, value)
            new_status = state.status

        if prev_status != new_status:
            logger.info(
                "session status transition",
                extra={
                    "session_id": str(session_id),
                    "op": "update",
                    "from": prev_status.value,
                    "to": new_status.value,
                },
            )

    async def set_payload(
        self, session_id: UUID, payload: ExtractedPayload
    ) -> None:
        """Cache the extracted payload + propagate `message_count` to state."""
        async with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                logger.warning(
                    "set_payload on unknown session",
                    extra={"session_id": str(session_id), "op": "set_payload"},
                )
                return
            state.payload = payload
            state.message_count = payload.message_count
        logger.info(
            "payload cached",
            extra={
                "session_id": str(session_id),
                "op": "set_payload",
                "message_count": payload.message_count,
                "conversation_count": payload.conversation_count,
            },
        )

    async def consume(self, session_id: UUID) -> ExtractedPayload | None:
        """Mark the session as CONSUMED and return the cached payload (F2 entry)."""
        state = self._sessions.get(session_id)
        if state is None:
            logger.warning(
                "consume on unknown session",
                extra={"session_id": str(session_id), "op": "consume"},
            )
            return None
        payload = state.payload
        await self.update(session_id, status=SessionStatus.CONSUMED)
        logger.info(
            "session consumed",
            extra={
                "session_id": str(session_id),
                "op": "consume",
                "had_payload": payload is not None,
            },
        )
        return payload

    # ----------------------------------------------------------- Pub / Sub

    async def publish(self, session_id: UUID, event: SSEEvent) -> None:
        """Persist `last_event` and broadcast to all subscriber queues.

        If a subscriber queue is full we drop its oldest event and enqueue the
        new one — keeping the stream live while shedding stale progress
        updates. The lock is held while we snapshot the subscriber list and
        update `last_event`; the actual `put_nowait` calls happen on the
        snapshot to avoid blocking other writers.
        """
        async with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                logger.warning(
                    "publish on unknown session",
                    extra={
                        "session_id": str(session_id),
                        "op": "publish",
                        "event": event.name,
                    },
                )
                return
            state.last_event = event
            queues = list(state.subscribers)

        delivered = 0
        for q in queues:
            try:
                q.put_nowait(event)
                delivered += 1
            except asyncio.QueueFull:
                # Drop-oldest fallback: pop one, then enqueue. Both ops are
                # non-blocking; if the queue drains between these calls and
                # put_nowait fails again, we give up on this subscriber.
                try:
                    _ = q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(event)
                    delivered += 1
                except asyncio.QueueFull:
                    logger.warning(
                        "subscriber queue full, event dropped",
                        extra={
                            "session_id": str(session_id),
                            "op": "publish",
                            "event": event.name,
                        },
                    )

        logger.info(
            "event published",
            extra={
                "session_id": str(session_id),
                "op": "publish",
                "event": event.name,
                "subscribers": len(queues),
                "delivered": delivered,
            },
        )

    async def subscribe(
        self, session_id: UUID
    ) -> AsyncIterator[SSEEvent]:
        """Yield events for ``session_id`` (replay-last first, then live).

        Semantics (WPP-14 / WPP-15):
        * If the session is unknown, return immediately — the route maps this
          to ``404 session_not_found``.
        * Yield ``state.last_event`` first when present (replay-last for
          reconnects).
        * If the session is already in a terminal status, return after the
          replay event — closing the SSE stream as required by WPP-15.
        * Otherwise loop on a per-subscriber queue (maxsize=32) until a
          terminal event arrives.
        """
        state = self._sessions.get(session_id)
        if state is None:
            return
        queue: asyncio.Queue[SSEEvent] = asyncio.Queue(
            maxsize=_SUBSCRIBER_QUEUE_MAX
        )
        state.subscribers.append(queue)
        logger.info(
            "subscriber attached",
            extra={
                "session_id": str(session_id),
                "op": "subscribe",
                "subscribers": len(state.subscribers),
            },
        )
        try:
            if state.last_event is not None:
                yield state.last_event
                if state.status in _TERMINAL_STATUSES:
                    return
            while True:
                event = await queue.get()
                yield event
                if event.name in _TERMINAL_EVENT_NAMES:
                    return
        finally:
            try:
                state.subscribers.remove(queue)
            except ValueError:
                # Already removed (e.g. session torn down) — ignore.
                pass
            logger.info(
                "subscriber detached",
                extra={
                    "session_id": str(session_id),
                    "op": "unsubscribe",
                    "subscribers": len(state.subscribers),
                },
            )

    # --------------------------------------------------------- TTL expire

    async def _expire_loop(self) -> None:
        """Background loop: every 60s sweep stale non-terminal sessions."""
        logger.info("session expire loop started", extra={"op": "expire_loop"})
        try:
            while True:
                await asyncio.sleep(60)
                try:
                    await self._tick_expire()
                except Exception:  # pragma: no cover — defensive guard
                    logger.exception(
                        "expire tick failed", extra={"op": "expire_tick"}
                    )
        except asyncio.CancelledError:
            logger.info(
                "session expire loop cancelled", extra={"op": "expire_loop"}
            )
            raise

    async def _tick_expire(self) -> None:
        """Single sweep — expire sessions older than ``SESSION_TTL_MINUTES``.

        Uses a deferred import of ``get_provider`` to avoid the
        ``app.clients.whatsapp`` <-> ``app.modules.whatsapp.state`` import
        cycle (the provider's expire path calls back into the store).
        """
        from app.clients.whatsapp import get_provider  # deferred: see docstring

        now = datetime.now(timezone.utc)
        snapshot = list(self._sessions.items())
        for sid, state in snapshot:
            age_minutes = (now - state.created_at).total_seconds() / 60.0
            if age_minutes <= settings.SESSION_TTL_MINUTES:
                continue
            if state.status in _EXPIRE_EXEMPT:
                continue

            logger.info(
                "session ttl expired",
                extra={
                    "session_id": str(sid),
                    "op": "expire",
                    "age_minutes": round(age_minutes, 2),
                    "status": state.status.value,
                },
            )

            # Best-effort: tell the provider to drop the upstream instance.
            try:
                await get_provider().disconnect(state.uazapi_token)
            except Exception:
                logger.warning(
                    "provider disconnect on expire failed (ignored)",
                    extra={"session_id": str(sid), "op": "expire"},
                )

            await self.publish(sid, SSEEvent(name="expired", data={"reason": "ttl"}))
            await self.update(sid, status=SessionStatus.EXPIRED)

    def start_expire_loop(self) -> asyncio.Task[None]:
        """Spawn the expire loop task (idempotent). Call from `lifespan`."""
        if self._expire_task is not None and not self._expire_task.done():
            return self._expire_task
        loop = asyncio.get_event_loop()
        self._expire_task = loop.create_task(
            self._expire_loop(), name="whatsapp-session-expire-loop"
        )
        return self._expire_task

    async def stop_expire_loop(self) -> None:
        """Cancel + await the expire loop task. Call from `lifespan` shutdown."""
        task = self._expire_task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "expire loop raised on shutdown", extra={"op": "stop_expire_loop"}
            )
        finally:
            self._expire_task = None


# Module-level singleton — wired into routes/service/worker via direct import.
session_store: SessionStore = SessionStore()
