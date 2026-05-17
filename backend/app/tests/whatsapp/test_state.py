"""Unit tests for ``SessionStore`` + ``SessionState`` (design § 5 / T6).

Covers:
* create → publish → subscribe happy path
* subscribe-after-publish replays the last event
* terminal status closes the SSE stream after replay
* multi-subscriber broadcast
* subscriber queue overflow → drop-oldest, no exception
* consume returns cached payload + marks CONSUMED
* TTL expire loop: provider.disconnect called, ``expired`` event published,
  session moved to EXPIRED status

WPP-04 (in-memory state w/ pub-sub), WPP-14/WPP-15 (replay-last + terminal
close), EC-05 (TTL expiration).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.whatsapp.schemas import (
    ConversationPayload,
    ExtractedPayload,
    SessionStatus,
    SSEEvent,
)
from app.modules.whatsapp.state import (
    SessionStore,
    _SUBSCRIBER_QUEUE_MAX,
    _STREAM_END_STATUSES,
)


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #


async def _collect(aiter, max_events: int = 10, timeout: float = 1.0) -> list[SSEEvent]:
    """Drain an async iterator up to ``max_events`` or until it closes."""
    out: list[SSEEvent] = []
    try:
        async with asyncio.timeout(timeout):
            async for event in aiter:
                out.append(event)
                if len(out) >= max_events:
                    break
    except asyncio.TimeoutError:
        pass
    return out


# --------------------------------------------------------------------------- #
# 1. happy path                                                               #
# --------------------------------------------------------------------------- #


async def test_create_get_publish_subscribe_happy(fresh_store: SessionStore) -> None:
    """Subscribe with a queue *before* publishing; the live broadcast lands."""
    sid = uuid4()
    await fresh_store.create(sid, uazapi_token="tok", qr_base64="QR")
    assert (await fresh_store.get(sid)) is not None

    # Start subscriber first, then publish so the event is delivered via queue.
    aiter = fresh_store.subscribe(sid)

    async def _publish_after_attach() -> None:
        # Give the generator a chance to attach its queue before we publish.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await fresh_store.publish(
            sid, SSEEvent(name="qr-updated", data={"qr": "QR2"})
        )

    pub_task = asyncio.create_task(_publish_after_attach())
    events = await _collect(aiter, max_events=1)
    await pub_task

    assert len(events) == 1
    assert events[0].name == "qr-updated"
    assert events[0].data == {"qr": "QR2"}


# --------------------------------------------------------------------------- #
# 2. replay-last                                                              #
# --------------------------------------------------------------------------- #


async def test_subscribe_replay_last_event(fresh_store: SessionStore) -> None:
    """Publish first, then subscribe → the first yielded event is the replay."""
    sid = uuid4()
    await fresh_store.create(sid, uazapi_token="tok", qr_base64="QR")

    first = SSEEvent(name="connected", data={"phone": "+55 11 9****-1234"})
    await fresh_store.publish(sid, first)

    aiter = fresh_store.subscribe(sid)
    events = await _collect(aiter, max_events=1, timeout=0.3)

    assert len(events) == 1
    assert events[0].name == "connected"
    assert events[0].data["phone"] == "+55 11 9****-1234"


# --------------------------------------------------------------------------- #
# 3. terminal status closes after replay                                      #
# --------------------------------------------------------------------------- #


async def test_subscribe_closes_on_terminal(fresh_store: SessionStore) -> None:
    """When session is already in a terminal status (EXTRACTED), subscribing
    yields the replay event and the generator returns — closing the SSE."""
    sid = uuid4()
    await fresh_store.create(sid, uazapi_token="tok", qr_base64="QR")

    final = SSEEvent(name="extracted", data={"message_count": 3, "conversation_count": 1})
    await fresh_store.publish(sid, final)
    await fresh_store.update(sid, status=SessionStatus.EXTRACTED)

    # Sanity: EXTRACTED is a stream-end status per the module contract.
    assert SessionStatus.EXTRACTED in _STREAM_END_STATUSES

    aiter = fresh_store.subscribe(sid)
    events = await _collect(aiter, max_events=10, timeout=0.5)

    # Exactly the replay event, then the generator returned (no more yields).
    assert len(events) == 1
    assert events[0].name == "extracted"


# --------------------------------------------------------------------------- #
# 4. multi-subscriber broadcast                                               #
# --------------------------------------------------------------------------- #


async def test_multi_subscriber_broadcast(fresh_store: SessionStore) -> None:
    """Two concurrent subscribers each receive the same published event."""
    sid = uuid4()
    await fresh_store.create(sid, uazapi_token="tok", qr_base64="QR")

    aiter_a = fresh_store.subscribe(sid)
    aiter_b = fresh_store.subscribe(sid)

    async def _publish() -> None:
        # Let both subscribers attach their queues first.
        for _ in range(3):
            await asyncio.sleep(0)
        await fresh_store.publish(sid, SSEEvent(name="extracting", data={"collected": 1}))

    pub_task = asyncio.create_task(_publish())
    events_a, events_b = await asyncio.gather(
        _collect(aiter_a, max_events=1, timeout=0.5),
        _collect(aiter_b, max_events=1, timeout=0.5),
    )
    await pub_task

    assert len(events_a) == 1
    assert len(events_b) == 1
    assert events_a[0].name == "extracting"
    assert events_b[0].name == "extracting"
    assert events_a[0].data == events_b[0].data


# --------------------------------------------------------------------------- #
# 5. queue overflow → drop-oldest, no exception                               #
# --------------------------------------------------------------------------- #


async def test_full_queue_drops_oldest_no_exception(
    fresh_store: SessionStore, caplog: pytest.LogCaptureFixture
) -> None:
    """Filling a subscriber queue to maxsize and publishing one more must
    not raise — the drop-oldest fallback engages and the latest event lands."""
    sid = uuid4()
    state = await fresh_store.create(sid, uazapi_token="tok", qr_base64="QR")

    # Manually inject a subscriber queue (mimics what `subscribe` does
    # internally) so we can control its drain rate.
    q: asyncio.Queue[SSEEvent] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_MAX)
    state.subscribers.append(q)

    # Fill the queue to maxsize.
    for i in range(_SUBSCRIBER_QUEUE_MAX):
        q.put_nowait(SSEEvent(name="extracting", data={"i": i}))
    assert q.full()

    # Publishing the 33rd event must not raise — drop-oldest absorbs it.
    await fresh_store.publish(
        sid, SSEEvent(name="extracting", data={"i": _SUBSCRIBER_QUEUE_MAX})
    )

    # Queue still at maxsize; oldest dropped, newest inside.
    assert q.qsize() == _SUBSCRIBER_QUEUE_MAX
    # Drain — the newest must be at the tail.
    drained: list[SSEEvent] = []
    while not q.empty():
        drained.append(q.get_nowait())
    assert drained[-1].data == {"i": _SUBSCRIBER_QUEUE_MAX}
    # And the very oldest (i=0) was dropped.
    assert all(e.data != {"i": 0} for e in drained)


# --------------------------------------------------------------------------- #
# 6. consume marks CONSUMED + returns cached payload                          #
# --------------------------------------------------------------------------- #


async def test_consume_marks_consumed_and_returns_payload(
    fresh_store: SessionStore,
) -> None:
    """``set_payload`` caches the extract; ``consume`` returns it and marks
    the state CONSUMED."""
    sid = uuid4()
    await fresh_store.create(sid, uazapi_token="tok", qr_base64="QR")

    payload = ExtractedPayload(
        message_count=5,
        conversation_count=1,
        conversations=[
            ConversationPayload(
                wa_chatid="5511999990001@s.whatsapp.net",
                contact_name="Dra. House",
                is_group=False,
                last_message_at=1_700_000_000,
                messages=[],
            )
        ],
    )
    await fresh_store.set_payload(sid, payload)

    got = await fresh_store.consume(sid)
    assert got is not None
    assert got.message_count == 5
    assert got.conversation_count == 1

    state = await fresh_store.get(sid)
    assert state is not None
    assert state.status == SessionStatus.CONSUMED
    assert state.message_count == 5


# --------------------------------------------------------------------------- #
# 7. TTL expire loop                                                          #
# --------------------------------------------------------------------------- #


async def test_tick_expire_disconnects_and_publishes_expired(
    fresh_store: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_tick_expire`` should: call provider.disconnect, publish 'expired',
    move status to EXPIRED."""
    sid = uuid4()
    state = await fresh_store.create(sid, uazapi_token="tok_expired", qr_base64="QR")

    # Make the session look 30 minutes old (>SESSION_TTL_MINUTES=15).
    state.created_at = datetime.now(timezone.utc) - timedelta(minutes=30)

    fake_provider = AsyncMock()
    fake_provider.disconnect = AsyncMock(return_value=None)

    # ``_tick_expire`` does ``from app.clients.whatsapp import get_provider``
    # *inside* the function — patch the source module.
    monkeypatch.setattr(
        "app.clients.whatsapp.get_provider", lambda: fake_provider
    )

    await fresh_store._tick_expire()

    fake_provider.disconnect.assert_awaited_once_with("tok_expired")

    state_after = await fresh_store.get(sid)
    assert state_after is not None
    assert state_after.status == SessionStatus.EXPIRED
    assert state_after.last_event is not None
    assert state_after.last_event.name == "expired"
    assert state_after.last_event.data.get("reason") == "ttl"
