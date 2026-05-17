"""Unit tests for the 30-day extract pipeline worker (T8).

The pipeline lives in ``app.workers.extract`` and pulls together:
  * provider (uazapi) — replaced with an ``AsyncMock``
  * repository — replaced with ``AsyncMock`` per function
  * session_store — the singleton in the worker module is replaced with
    a fresh ``SessionStore`` to keep tests isolated

Covers (per design § 6 / WPP-07..WPP-10 / EC-02..EC-04):
  * 30-day cutoff filter (drops older messages)
  * type=='text' filter (drops images/audio/etc.)
  * empty clinic → extracted with count=0
  * banned (UazapiBanned) → failed event with code='banned'
  * generic unavailable → failed with 'uazapi_unavailable'
  * hard timeout → partial=True extract event
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import app.workers.extract as extract_mod
from app.clients.whatsapp.errors import UazapiBanned, UazapiUnavailable
from app.clients.whatsapp.types import Chat, Message
from app.modules.whatsapp.schemas import SessionStatus
from app.modules.whatsapp.state import SessionStore


# --------------------------------------------------------------------------- #
# fixtures / helpers                                                          #
# --------------------------------------------------------------------------- #


@pytest.fixture
def isolated_store(monkeypatch: pytest.MonkeyPatch) -> SessionStore:
    """Swap the worker's module-level ``session_store`` for a fresh store."""
    store = SessionStore()
    monkeypatch.setattr(extract_mod, "session_store", store)
    return store


@pytest.fixture
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Patch ``get_provider()`` (deferred-imported inside the worker) to
    return an AsyncMock. Both the main path and ``_fail`` re-import it
    via ``from app.clients.whatsapp import get_provider``."""
    provider = AsyncMock()
    provider.disconnect = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.clients.whatsapp.get_provider", lambda: provider
    )
    return provider


@pytest.fixture
def fake_repo(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch every repository function the worker uses."""
    holder = MagicMock()
    for name in ("create", "mark_status", "mark_extracted", "mark_failed"):
        m = AsyncMock(name=f"repository.{name}")
        setattr(holder, name, m)
        monkeypatch.setattr(
            f"app.workers.extract.repository.{name}", m
        )
    return holder


async def _seed_connected_session(store: SessionStore, token: str = "tok_extract"):
    """Create a session and move it to CONNECTED — required precondition
    for ``extract_30d_pipeline`` to do any work."""
    sid = uuid4()
    await store.create(sid, uazapi_token=token, qr_base64="QR")
    await store.update(sid, status=SessionStatus.CONNECTED)
    return sid


def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _ts_days_ago(n: int) -> int:
    return int((datetime.now(timezone.utc) - timedelta(days=n)).timestamp())


# --------------------------------------------------------------------------- #
# 1. 30-day cutoff filter                                                     #
# --------------------------------------------------------------------------- #


async def test_extracts_only_30d_messages(
    isolated_store: SessionStore,
    fake_provider: AsyncMock,
    fake_repo: MagicMock,
) -> None:
    """Messages older than ``EXTRACT_DAYS_WINDOW`` are dropped. The first
    out-of-window message in a chat aborts pagination for that chat."""
    sid = await _seed_connected_session(isolated_store)

    chat_a = Chat(
        wa_chatid="5511111110001@s.whatsapp.net",
        contact_name="A",
        is_group=False,
        last_message_at=_now_ts(),
    )
    chat_b = Chat(
        wa_chatid="5511111110002@s.whatsapp.net",
        contact_name="B",
        is_group=False,
        last_message_at=_now_ts(),
    )

    # First page of chats; ``list_chats`` is (chats, has_more).
    fake_provider.list_chats.return_value = ([chat_a, chat_b], False)

    async def _list_messages(token, chat_id, limit=100, offset=0):
        # Messages are returned newest-first; the worker stops at the first
        # one older than cutoff. So put fresh first, then stale.
        if chat_id == chat_a.wa_chatid:
            return (
                [
                    Message(ts=_ts_days_ago(1), from_me=False, type="text", text="recent A"),
                    Message(ts=_ts_days_ago(45), from_me=False, type="text", text="OLD A"),
                ],
                False,
                2,
            )
        if chat_id == chat_b.wa_chatid:
            return (
                [
                    Message(ts=_ts_days_ago(2), from_me=True, type="text", text="recent B"),
                    Message(ts=_ts_days_ago(60), from_me=False, type="text", text="OLD B"),
                ],
                False,
                2,
            )
        return ([], False, 0)

    fake_provider.list_messages.side_effect = _list_messages

    await extract_mod.extract_30d_pipeline(sid)

    state = await isolated_store.get(sid)
    assert state is not None
    assert state.status == SessionStatus.EXTRACTED
    assert state.payload is not None
    assert state.payload.message_count == 2
    assert state.payload.conversation_count == 2

    texts = [m.text for c in state.payload.conversations for m in c.messages]
    assert "recent A" in texts
    assert "recent B" in texts
    assert "OLD A" not in texts
    assert "OLD B" not in texts


# --------------------------------------------------------------------------- #
# 2. type=='text' filter                                                      #
# --------------------------------------------------------------------------- #


async def test_filters_non_text_messages(
    isolated_store: SessionStore,
    fake_provider: AsyncMock,
    fake_repo: MagicMock,
) -> None:
    """Non-text messages (images, audio, …) are dropped per WPP-08."""
    sid = await _seed_connected_session(isolated_store)

    chat = Chat(
        wa_chatid="5511222220001@s.whatsapp.net",
        contact_name="C",
        is_group=False,
        last_message_at=_now_ts(),
    )
    fake_provider.list_chats.return_value = ([chat], False)
    fake_provider.list_messages.return_value = (
        [
            Message(ts=_ts_days_ago(1), from_me=False, type="text", text="hello"),
            Message(ts=_ts_days_ago(1), from_me=False, type="imagemessage", text=""),
            Message(ts=_ts_days_ago(1), from_me=True, type="audiomessage", text=""),
            Message(ts=_ts_days_ago(1), from_me=False, type="text", text="world"),
        ],
        False,
        4,
    )

    await extract_mod.extract_30d_pipeline(sid)

    state = await isolated_store.get(sid)
    assert state is not None
    assert state.payload is not None
    assert state.payload.message_count == 2
    texts = [m.text for c in state.payload.conversations for m in c.messages]
    assert sorted(texts) == ["hello", "world"]


# --------------------------------------------------------------------------- #
# 3. empty clinic → extracted with count=0                                    #
# --------------------------------------------------------------------------- #


async def test_empty_clinic_extracted_with_count_zero(
    isolated_store: SessionStore,
    fake_provider: AsyncMock,
    fake_repo: MagicMock,
) -> None:
    """No chats at all → ``EXTRACTED`` with ``message_count=0`` (EC-02)."""
    sid = await _seed_connected_session(isolated_store)

    fake_provider.list_chats.return_value = ([], False)

    await extract_mod.extract_30d_pipeline(sid)

    state = await isolated_store.get(sid)
    assert state is not None
    assert state.status == SessionStatus.EXTRACTED
    assert state.payload is not None
    assert state.payload.message_count == 0
    assert state.payload.conversation_count == 0


# --------------------------------------------------------------------------- #
# 4. banned → failed event with code='banned'                                 #
# --------------------------------------------------------------------------- #


async def test_banned_publishes_failed_banned(
    isolated_store: SessionStore,
    fake_provider: AsyncMock,
    fake_repo: MagicMock,
) -> None:
    """``UazapiBanned`` from list_chats → SSE 'failed' with code='banned'."""
    sid = await _seed_connected_session(isolated_store)

    fake_provider.list_chats.side_effect = UazapiBanned("banned")

    await extract_mod.extract_30d_pipeline(sid)

    state = await isolated_store.get(sid)
    assert state is not None
    assert state.status == SessionStatus.FAILED
    assert state.last_event is not None
    assert state.last_event.name == "failed"
    assert state.last_event.data["code"] == "banned"
    fake_repo.mark_failed.assert_awaited()


# --------------------------------------------------------------------------- #
# 5. uazapi unavailable → failed with 'uazapi_unavailable'                    #
# --------------------------------------------------------------------------- #


async def test_uazapi_unavailable_failed(
    isolated_store: SessionStore,
    fake_provider: AsyncMock,
    fake_repo: MagicMock,
) -> None:
    sid = await _seed_connected_session(isolated_store)

    fake_provider.list_chats.side_effect = UazapiUnavailable("boom")

    await extract_mod.extract_30d_pipeline(sid)

    state = await isolated_store.get(sid)
    assert state is not None
    assert state.status == SessionStatus.FAILED
    assert state.last_event is not None
    assert state.last_event.name == "failed"
    assert state.last_event.data["code"] == "uazapi_unavailable"


# --------------------------------------------------------------------------- #
# 6. hard timeout → partial extract                                           #
# --------------------------------------------------------------------------- #


async def test_hard_timeout_partial(
    isolated_store: SessionStore,
    fake_provider: AsyncMock,
    fake_repo: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``settings.EXTRACT_HARD_TIMEOUT_S`` is sliced to a tiny value; the
    per-chat task that sleeps longer than that gets cancelled, but the
    pipeline must still emit ``extracted`` with ``partial=True``."""
    sid = await _seed_connected_session(isolated_store)

    # Squeeze the hard timeout below the chat-task latency.
    monkeypatch.setattr(extract_mod.settings, "EXTRACT_HARD_TIMEOUT_S", 0.05)

    chat = Chat(
        wa_chatid="5511333330001@s.whatsapp.net",
        contact_name="Slow",
        is_group=False,
        last_message_at=_now_ts(),
    )
    fake_provider.list_chats.return_value = ([chat], False)

    async def _slow_list_messages(*a, **kw):
        await asyncio.sleep(1.0)
        return ([], False, 0)

    fake_provider.list_messages.side_effect = _slow_list_messages

    await extract_mod.extract_30d_pipeline(sid)

    state = await isolated_store.get(sid)
    assert state is not None
    # Hard-timeout still finalizes via ``_finalize_partial`` → state EXTRACTED,
    # payload.partial=True, and an 'extracted' SSE event was emitted.
    assert state.status == SessionStatus.EXTRACTED
    assert state.payload is not None
    assert state.payload.partial is True
    assert state.last_event is not None
    assert state.last_event.name == "extracted"
    assert state.last_event.data.get("partial") is True


# --------------------------------------------------------------------------- #
# 7. F3 §REPORT-11: _finalize_success fires _kick_off_report                  #
# --------------------------------------------------------------------------- #


async def test_finalize_success_kicks_off_report(
    isolated_store: SessionStore,
    fake_provider: AsyncMock,
    fake_repo: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the happy path the extract worker MUST trigger the report
    generation worker exactly once via ``_kick_off_report``. The autouse
    ``_no_op_report_kickoff`` fixture replaces it with a no-op for backward
    compat — we override that locally with a spy that captures invocations."""
    sid = await _seed_connected_session(isolated_store)

    captured: list[dict] = []

    def _spy(session_id, payload):
        captured.append({"session_id": session_id, "payload": payload})

    # Override the autouse no-op fixture for this test only.
    monkeypatch.setattr(
        "app.workers.extract._kick_off_report", _spy, raising=False
    )

    chat = Chat(
        wa_chatid="5511444440001@s.whatsapp.net",
        contact_name="Patient",
        is_group=False,
        last_message_at=_now_ts(),
    )
    fake_provider.list_chats.return_value = ([chat], False)
    fake_provider.list_messages.return_value = (
        [Message(ts=_ts_days_ago(1), from_me=False, type="text", text="oi")],
        False,
        1,
    )

    await extract_mod.extract_30d_pipeline(sid)

    state = await isolated_store.get(sid)
    assert state is not None
    assert state.status == SessionStatus.EXTRACTED

    assert len(captured) == 1, "report worker must be kicked off exactly once"
    assert captured[0]["session_id"] == sid
    # Payload carries the extracted data — `partial=False` on the happy path.
    assert captured[0]["payload"].partial is False
    assert captured[0]["payload"].message_count == 1
