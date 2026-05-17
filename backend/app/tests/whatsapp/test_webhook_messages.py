"""Tests for the F4 ``messages`` webhook event handler (T18).

Covers two units of :mod:`app.modules.whatsapp.service`:

* ``_parse_uazapi_message`` (module-level helper) — the three known uazapi
  shapes (``conversation``, ``extendedTextMessage``, ``imageMessage``) plus
  fallback / rejection cases.
* ``WhatsAppService._handle_messages_event`` — full flow exercised via the
  public :meth:`WhatsAppService.handle_webhook_event` router so we also
  verify the event-routing branch lights up.

Fixture-sharing note
--------------------
The ``fake_captured_repo`` / ``sample_uazapi_message_raw`` fixtures live in
``app/tests/captured_messages/conftest.py``. Pytest does not propagate
sibling-package conftests, so we inline equivalent factories here. They
mirror the production-side conftest contract 1:1 (same names, same default
values) so swapping back to the shared fixtures is a no-op should pytest's
discovery rules ever permit it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.clients.whatsapp import WhatsAppProvider
from app.clients.whatsapp.types import ProviderSession
from app.modules.whatsapp.service import (
    WhatsAppService,
    _parse_uazapi_message,
)
from app.modules.whatsapp.state import SessionStore


# --------------------------------------------------------------------------- #
# Local fixtures (mirrors test_service.py + captured_messages/conftest.py)    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def mock_provider() -> AsyncMock:
    """AsyncMock spec'd to :class:`WhatsAppProvider` with happy-path defaults."""
    p = AsyncMock(spec=WhatsAppProvider)
    p.create_session.return_value = ProviderSession(
        session_token="tok_msg", qr_base64="QRBASE64"
    )
    p.register_webhook.return_value = None
    p.disconnect.return_value = None
    return p


@pytest.fixture
def mock_repo(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch the whatsapp repository functions so create_session() doesn't hit the DB."""
    holder = MagicMock()
    for name in (
        "create",
        "mark_status",
        "mark_extracted",
        "mark_failed",
        "mark_consumed",
        "link_user",
        "get",
    ):
        m = AsyncMock(name=f"repository.{name}")
        setattr(holder, name, m)
        monkeypatch.setattr(
            f"app.modules.whatsapp.service.repository.{name}", m
        )
    return holder


def _svc(provider: AsyncMock, store: SessionStore) -> WhatsAppService:
    return WhatsAppService(
        provider=provider,
        store=store,
        callback_base_url="http://test",
    )


@pytest.fixture
def fake_captured_repo(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Patch ``app.modules.captured_messages.repository.insert_many``.

    The service does a lazy import (``from app.modules.captured_messages
    import repository as captured_repo`` inside ``_handle_messages_event``)
    so the canonical patch target is the repository module itself — the name
    is resolved fresh on every call.
    """
    insert_many = AsyncMock(return_value=0, name="insert_many")
    monkeypatch.setattr(
        "app.modules.captured_messages.repository.insert_many",
        insert_many,
        raising=False,
    )
    return SimpleNamespace(insert_many=insert_many)


@pytest.fixture
def sample_uazapi_message_raw() -> SimpleNamespace:
    """Factory matching ``app/tests/captured_messages/conftest.py``."""

    def _wrapper(
        *,
        message: dict[str, Any],
        from_me: bool,
        raw_message_id: str | None,
        push_name: str,
        remote_jid: str,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        return {
            "key": {
                "id": raw_message_id or uuid4().hex,
                "remoteJid": remote_jid,
                "fromMe": from_me,
                "participant": None,
            },
            "messageTimestamp": int(now.timestamp()),
            "pushName": push_name,
            "message": message,
        }

    def make_text(
        text: str = "oi",
        from_me: bool = False,
        raw_message_id: str | None = None,
        push_name: str = "Paciente Teste",
        remote_jid: str = "5511900000001@s.whatsapp.net",
    ) -> dict[str, Any]:
        return _wrapper(
            message={"conversation": text},
            from_me=from_me,
            raw_message_id=raw_message_id,
            push_name=push_name,
            remote_jid=remote_jid,
        )

    def make_extended(
        text: str = "oi formatado",
        from_me: bool = False,
        raw_message_id: str | None = None,
        push_name: str = "Paciente Teste",
        remote_jid: str = "5511900000001@s.whatsapp.net",
    ) -> dict[str, Any]:
        return _wrapper(
            message={
                "extendedTextMessage": {"text": text, "contextInfo": {}},
            },
            from_me=from_me,
            raw_message_id=raw_message_id,
            push_name=push_name,
            remote_jid=remote_jid,
        )

    def make_image(
        caption: str = "foto",
        from_me: bool = False,
        raw_message_id: str | None = None,
        push_name: str = "Paciente Teste",
        remote_jid: str = "5511900000001@s.whatsapp.net",
    ) -> dict[str, Any]:
        return _wrapper(
            message={
                "imageMessage": {
                    "caption": caption,
                    "mimetype": "image/jpeg",
                    "url": "https://example.invalid/img.jpg",
                }
            },
            from_me=from_me,
            raw_message_id=raw_message_id,
            push_name=push_name,
            remote_jid=remote_jid,
        )

    return SimpleNamespace(
        make_text=make_text,
        make_extended=make_extended,
        make_image=make_image,
    )


# Stable identities for the parser unit-tests (no service involved).
_SID = uuid4()
_UID = uuid4()


# =========================================================================== #
# 1. _parse_uazapi_message — three known shapes                               #
# =========================================================================== #


def test_parse_text_message_conversation_shape() -> None:
    """Shape A: plain ``message.conversation`` string → text message."""
    raw: dict[str, Any] = {
        "key": {
            "id": "ABC1",
            "remoteJid": "5511900000001@s.whatsapp.net",
            "fromMe": False,
        },
        "messageTimestamp": 1735000000,
        "pushName": "Maria",
        "message": {"conversation": "Olá"},
    }
    result = _parse_uazapi_message(raw, session_id=_SID, user_id=_UID)

    assert result is not None
    assert result.text == "Olá"
    assert result.message_type == "text"
    assert result.raw_message_id == "ABC1"
    assert result.contact_name == "Maria"
    assert result.is_from_me is False
    assert result.wa_chatid == "5511900000001@s.whatsapp.net"
    assert result.user_id == _UID
    assert result.whatsapp_session_id == _SID
    # Timestamp converted to aware datetime in UTC.
    assert result.ts.tzinfo is not None
    assert result.ts == datetime.fromtimestamp(1735000000, tz=timezone.utc)


def test_parse_text_message_extended_shape() -> None:
    """Shape B: ``extendedTextMessage.text`` (replies/mentions) → text message."""
    raw: dict[str, Any] = {
        "key": {
            "id": "ABC2",
            "remoteJid": "5511900000002@s.whatsapp.net",
            "fromMe": True,
        },
        "messageTimestamp": 1735000060,
        "message": {
            "extendedTextMessage": {"text": "Posso te encaixar quarta"}
        },
    }
    result = _parse_uazapi_message(raw, session_id=_SID, user_id=_UID)

    assert result is not None
    assert result.text == "Posso te encaixar quarta"
    assert result.message_type == "text"
    assert result.is_from_me is True


def test_parse_image_message_with_caption() -> None:
    """Shape C: ``imageMessage.caption`` → image message with text=caption."""
    raw: dict[str, Any] = {
        "key": {
            "id": "ABC3",
            "remoteJid": "5511900000003@s.whatsapp.net",
            "fromMe": False,
        },
        "messageTimestamp": 1735000120,
        "message": {"imageMessage": {"caption": "Mando foto da receita"}},
    }
    result = _parse_uazapi_message(raw, session_id=_SID, user_id=_UID)

    assert result is not None
    assert result.message_type == "image"
    assert result.text == "Mando foto da receita"


# =========================================================================== #
# 2. _parse_uazapi_message — fallbacks + rejections                            #
# =========================================================================== #


def test_parse_audio_message_no_text() -> None:
    """Audio message has no caption field → text remains None, type=audio."""
    raw: dict[str, Any] = {
        "key": {
            "id": "AUD1",
            "remoteJid": "5511900000004@s.whatsapp.net",
            "fromMe": False,
        },
        "messageTimestamp": 1735000180,
        "message": {"audioMessage": {"url": "https://example.invalid/a.ogg"}},
    }
    result = _parse_uazapi_message(raw, session_id=_SID, user_id=_UID)

    assert result is not None
    assert result.message_type == "audio"
    assert result.text is None


def test_parse_unknown_message_type_is_other() -> None:
    """Unknown ``message.<field>`` falls back to ``message_type='other'``."""
    raw: dict[str, Any] = {
        "key": {
            "id": "UNK1",
            "remoteJid": "5511900000005@s.whatsapp.net",
            "fromMe": False,
        },
        "messageTimestamp": 1735000240,
        "message": {"someUnknownField": {"foo": "bar"}},
    }
    result = _parse_uazapi_message(raw, session_id=_SID, user_id=_UID)

    assert result is not None
    assert result.message_type == "other"
    assert result.text is None


def test_parse_returns_none_when_no_key() -> None:
    """Missing ``key`` block → no remoteJid → reject (return None)."""
    raw: dict[str, Any] = {
        "messageTimestamp": 1735000300,
        "message": {"conversation": "hi"},
    }
    assert _parse_uazapi_message(raw, session_id=_SID, user_id=_UID) is None


def test_parse_returns_none_when_no_remote_jid() -> None:
    """``key`` present but no ``remoteJid`` → reject (cannot attribute chat)."""
    raw: dict[str, Any] = {
        "key": {"id": "X", "fromMe": False},
        "messageTimestamp": 1735000360,
        "message": {"conversation": "hi"},
    }
    assert _parse_uazapi_message(raw, session_id=_SID, user_id=_UID) is None


def test_parse_returns_none_when_no_timestamp() -> None:
    """No ``messageTimestamp``/``timestamp`` → reject (cannot place in window)."""
    raw: dict[str, Any] = {
        "key": {
            "id": "X",
            "remoteJid": "5511900000006@s.whatsapp.net",
            "fromMe": False,
        },
        "message": {"conversation": "hi"},
    }
    assert _parse_uazapi_message(raw, session_id=_SID, user_id=_UID) is None


# =========================================================================== #
# 3. _handle_messages_event — full flow via handle_webhook_event              #
# =========================================================================== #


async def test_handle_messages_event_no_session_skips_silently(
    mock_provider: AsyncMock,
    mock_repo: MagicMock,
    fresh_store: SessionStore,
    fake_captured_repo: SimpleNamespace,
    sample_uazapi_message_raw: SimpleNamespace,
) -> None:
    """No session in the store → handler logs+returns, no insert attempted."""
    svc = _svc(mock_provider, fresh_store)
    unknown_sid = uuid4()
    payload: dict[str, Any] = {
        "EventType": "messages.upsert",
        "messages": [sample_uazapi_message_raw.make_text("oi")],
    }

    # MUST NOT raise — webhook must always finish cleanly for uazapi.
    await svc.handle_webhook_event(unknown_sid, payload)

    fake_captured_repo.insert_many.assert_not_called()


async def test_handle_messages_event_no_user_linked_skips_silently(
    mock_provider: AsyncMock,
    mock_repo: MagicMock,
    fresh_store: SessionStore,
    fake_captured_repo: SimpleNamespace,
    sample_uazapi_message_raw: SimpleNamespace,
) -> None:
    """Session exists but ``user_id is None`` (signup not yet linked) → skip."""
    svc = _svc(mock_provider, fresh_store)
    resp = await svc.create_session(client_ip="1.1.1.1")
    sid = resp.session_id
    # NOTE: deliberately do NOT update user_id — simulates pre-signup race.

    payload: dict[str, Any] = {
        "EventType": "messages.upsert",
        "messages": [sample_uazapi_message_raw.make_text("oi")],
    }
    await svc.handle_webhook_event(sid, payload)

    fake_captured_repo.insert_many.assert_not_called()


async def test_handle_messages_event_inserts_batch(
    mock_provider: AsyncMock,
    mock_repo: MagicMock,
    fresh_store: SessionStore,
    fake_captured_repo: SimpleNamespace,
    sample_uazapi_message_raw: SimpleNamespace,
) -> None:
    """Happy path: 3 valid messages of varied shapes → insert_many awaited with 3 items."""
    svc = _svc(mock_provider, fresh_store)
    resp = await svc.create_session(client_ip="1.1.1.2")
    sid = resp.session_id
    user_id = uuid4()
    await fresh_store.update(sid, user_id=user_id)

    fake_captured_repo.insert_many.return_value = 3

    payload: dict[str, Any] = {
        "EventType": "messages.upsert",
        "messages": [
            sample_uazapi_message_raw.make_text("oi"),
            sample_uazapi_message_raw.make_extended("e aí"),
            sample_uazapi_message_raw.make_image("foto"),
        ],
    }
    await svc.handle_webhook_event(sid, payload)

    fake_captured_repo.insert_many.assert_awaited_once()
    args, _kwargs = fake_captured_repo.insert_many.call_args
    items = args[0]
    assert len(items) == 3
    # Every insert must be attributed to the right user/session.
    for item in items:
        assert item.user_id == user_id
        assert item.whatsapp_session_id == sid
    # Message types reflect the source shapes (in declaration order).
    assert [m.message_type for m in items] == ["text", "text", "image"]


async def test_handle_messages_event_accepts_nested_data_messages(
    mock_provider: AsyncMock,
    mock_repo: MagicMock,
    fresh_store: SessionStore,
    fake_captured_repo: SimpleNamespace,
    sample_uazapi_message_raw: SimpleNamespace,
) -> None:
    """uazapi variant B: messages array nested under ``data.messages``."""
    svc = _svc(mock_provider, fresh_store)
    resp = await svc.create_session(client_ip="1.1.1.3")
    sid = resp.session_id
    user_id = uuid4()
    await fresh_store.update(sid, user_id=user_id)

    payload: dict[str, Any] = {
        "event": "messages",
        "data": {
            "messages": [sample_uazapi_message_raw.make_text("nested")],
        },
    }
    await svc.handle_webhook_event(sid, payload)

    fake_captured_repo.insert_many.assert_awaited_once()
    args, _kwargs = fake_captured_repo.insert_many.call_args
    items = args[0]
    assert len(items) == 1
    assert items[0].text == "nested"
    assert items[0].user_id == user_id


async def test_handle_messages_event_swallows_insert_failure(
    mock_provider: AsyncMock,
    mock_repo: MagicMock,
    fresh_store: SessionStore,
    fake_captured_repo: SimpleNamespace,
    sample_uazapi_message_raw: SimpleNamespace,
) -> None:
    """``insert_many`` raising must NOT propagate — webhook stays 2xx."""
    svc = _svc(mock_provider, fresh_store)
    resp = await svc.create_session(client_ip="1.1.1.4")
    sid = resp.session_id
    user_id = uuid4()
    await fresh_store.update(sid, user_id=user_id)

    fake_captured_repo.insert_many.side_effect = RuntimeError("DB down")

    payload: dict[str, Any] = {
        "EventType": "messages.upsert",
        "messages": [sample_uazapi_message_raw.make_text("any")],
    }
    # MUST NOT raise — otherwise uazapi retry-storms.
    await svc.handle_webhook_event(sid, payload)

    fake_captured_repo.insert_many.assert_awaited_once()


async def test_handle_webhook_event_routes_messages_to_messages_handler(
    mock_provider: AsyncMock,
    mock_repo: MagicMock,
    fresh_store: SessionStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Event ``messages.upsert`` routes to ``_handle_messages_event``, not connection."""
    svc = _svc(mock_provider, fresh_store)
    resp = await svc.create_session(client_ip="1.1.1.5")
    sid = resp.session_id

    msgs_handler = AsyncMock(name="_handle_messages_event")
    conn_handler = AsyncMock(name="_handle_connection_event")
    monkeypatch.setattr(svc, "_handle_messages_event", msgs_handler)
    monkeypatch.setattr(svc, "_handle_connection_event", conn_handler)

    payload: dict[str, Any] = {
        "EventType": "messages.upsert",
        "messages": [],
    }
    await svc.handle_webhook_event(sid, payload)

    msgs_handler.assert_awaited_once_with(sid, payload)
    conn_handler.assert_not_called()
