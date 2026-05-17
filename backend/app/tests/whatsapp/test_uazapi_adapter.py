"""Unit tests for `UazapiProvider` — covers design § 4.2 / § 4.3 / § 10.

Mocking pattern: each test gets the `mock_uazapi` fixture which pre-stubs all
7 endpoints with happy-path bodies. Failure-mode tests override the specific
route they care about by calling `.mock(...)` again on `respx_mock` (last
registered route wins).
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.clients.whatsapp.errors import (
    UazapiBanned,
    UazapiTimeout,
    UazapiUnavailable,
    UazapiUnknown,
)
from app.clients.whatsapp.types import ProviderSession
from app.clients.whatsapp.uazapi import UazapiProvider


async def test_create_session_happy_path(
    mock_uazapi: respx.MockRouter,
    uazapi_base: str,
) -> None:
    """`create_session` chains /instance/create + /instance/connect and returns
    a `ProviderSession` carrying the instance token + QR base64."""
    provider = UazapiProvider()
    try:
        session = await provider.create_session()
    finally:
        await provider.aclose()

    assert isinstance(session, ProviderSession)
    assert session.session_token == "tok_xyz"
    assert session.qr_base64 == "<fake_base64>"

    create_route = mock_uazapi.routes[0]
    connect_route = mock_uazapi.routes[1]
    assert create_route.called, "/instance/create should be hit"
    assert connect_route.called, "/instance/connect should be hit"

    # Order: /instance/create first, /instance/connect second.
    calls = mock_uazapi.calls
    assert calls[0].request.url.path == "/instance/create"
    assert calls[1].request.url.path == "/instance/connect"


async def test_create_session_uses_admintoken_then_token(
    mock_uazapi: respx.MockRouter,
    uazapi_base: str,
) -> None:
    """First call (/instance/create) uses `admintoken` header; second call
    (/instance/connect) uses `token` header carrying the freshly-issued
    instance token."""
    provider = UazapiProvider()
    try:
        await provider.create_session()
    finally:
        await provider.aclose()

    create_req = mock_uazapi.calls[0].request
    connect_req = mock_uazapi.calls[1].request

    assert create_req.headers.get("admintoken") == "admin_tok_test"
    assert "token" not in {k.lower() for k in create_req.headers.keys()} or (
        # httpx normalizes header keys; explicit "token" must NOT be present as
        # auth for /instance/create. Some httpx versions expose lowercase keys.
        create_req.headers.get("token") is None
    )

    # /instance/connect must carry `token` = the instance token from step 1.
    assert connect_req.headers.get("token") == "tok_xyz"
    assert connect_req.headers.get("admintoken") is None


async def test_5xx_raises_uazapi_unavailable(
    mock_uazapi: respx.MockRouter,
    uazapi_base: str,
) -> None:
    """5xx response from any endpoint → `UazapiUnavailable`."""
    mock_uazapi.post(f"{uazapi_base}/instance/create").mock(
        return_value=httpx.Response(503, json={"error": "service unavailable"})
    )
    provider = UazapiProvider()
    try:
        with pytest.raises(UazapiUnavailable):
            await provider.create_session()
    finally:
        await provider.aclose()


async def test_timeout_raises_uazapi_timeout(
    mock_uazapi: respx.MockRouter,
    uazapi_base: str,
) -> None:
    """`httpx.TimeoutException` on the wire → `UazapiTimeout`."""
    mock_uazapi.post(f"{uazapi_base}/instance/create").mock(
        side_effect=httpx.TimeoutException("simulated timeout")
    )
    provider = UazapiProvider()
    try:
        with pytest.raises(UazapiTimeout):
            await provider.create_session()
    finally:
        await provider.aclose()


async def test_provider_code_463_raises_banned(
    mock_uazapi: respx.MockRouter,
    uazapi_base: str,
) -> None:
    """Body carrying `provider_code: 463` (even on a 200) → `UazapiBanned`."""
    mock_uazapi.post(f"{uazapi_base}/chat/find").mock(
        return_value=httpx.Response(
            200,
            json={
                "error": "WhatsApp signaled the number is banned",
                "provider_code": 463,
            },
        )
    )
    provider = UazapiProvider()
    try:
        with pytest.raises(UazapiBanned):
            await provider.list_chats(session_token="tok_xyz", limit=100, offset=0)
    finally:
        await provider.aclose()


async def test_list_messages_parses_correctly(
    mock_uazapi: respx.MockRouter,
    uazapi_base: str,
) -> None:
    """`list_messages` returns (list[Message] of expected length, has_more, next_offset)
    from the uazapi /message/find body."""
    body: dict[str, Any] = {
        "messages": [
            {
                "ts": 1_700_000_000,
                "fromMe": False,
                "type": "text",
                "text": "olá doutor",
            },
            {
                "ts": 1_700_000_100,
                "fromMe": True,
                "type": "text",
                "text": "tudo bem?",
            },
            {
                "ts": 1_700_000_200,
                "fromMe": False,
                "type": "text",
                "text": "tudo sim, obrigado",
            },
        ],
        "hasMore": False,
        "nextOffset": 3,
    }
    mock_uazapi.post(f"{uazapi_base}/message/find").mock(
        return_value=httpx.Response(200, json=body)
    )

    provider = UazapiProvider()
    try:
        messages, has_more, next_offset = await provider.list_messages(
            session_token="tok_xyz",
            chat_id="5511999990001@s.whatsapp.net",
            limit=100,
            offset=0,
        )
    finally:
        await provider.aclose()

    assert len(messages) == 3
    assert has_more is False
    assert next_offset == 3
    assert messages[0].text == "olá doutor"
    assert messages[0].from_me is False
    assert messages[1].from_me is True
    assert messages[2].ts == 1_700_000_200
    assert all(m.type == "text" for m in messages)


async def test_disconnect_happy(
    mock_uazapi: respx.MockRouter,
    uazapi_base: str,
) -> None:
    """`disconnect` POSTs to /instance/disconnect with the session token."""
    provider = UazapiProvider()
    try:
        result = await provider.disconnect(session_token="tok_xyz")
    finally:
        await provider.aclose()

    assert result is None  # disconnect returns None per Protocol

    disconnect_route = mock_uazapi.post(f"{uazapi_base}/instance/disconnect")
    assert disconnect_route.called
    last_call = mock_uazapi.calls[-1]
    assert last_call.request.url.path == "/instance/disconnect"
    assert last_call.request.headers.get("token") == "tok_xyz"


async def test_delete_instance_uses_delete_endpoint_with_instance_token(
    mock_uazapi: respx.MockRouter,
    uazapi_base: str,
) -> None:
    """`delete_instance` calls DELETE /instance with the `token` header.

    Per uazapi docs, this disconnects the WhatsApp session AND removes the
    instance row from the database — frees the device slot in one round-trip.
    """
    mock_uazapi.delete(f"{uazapi_base}/instance").mock(
        return_value=httpx.Response(200, json={"response": "Instance Deleted"})
    )

    provider = UazapiProvider()
    try:
        result = await provider.delete_instance(session_token="tok_xyz")
    finally:
        await provider.aclose()

    assert result is None
    last_call = mock_uazapi.calls[-1]
    assert last_call.request.url.path == "/instance"
    assert last_call.request.method == "DELETE"
    assert last_call.request.headers.get("token") == "tok_xyz"
    assert "admintoken" not in last_call.request.headers


async def test_list_all_instances_uses_admin_token(
    mock_uazapi: respx.MockRouter,
    uazapi_base: str,
) -> None:
    """`list_all_instances` GETs /instance/all with the admin token header."""
    fake_instances: list[dict[str, Any]] = [
        {"id": "inst_a", "token": "tok_a", "status": "disconnected", "name": "X"},
        {"id": "inst_b", "token": "tok_b", "status": "connected", "name": "Y"},
    ]
    mock_uazapi.get(f"{uazapi_base}/instance/all").mock(
        return_value=httpx.Response(200, json=fake_instances)
    )

    provider = UazapiProvider()
    try:
        result = await provider.list_all_instances()
    finally:
        await provider.aclose()

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["id"] == "inst_a"
    last_call = mock_uazapi.calls[-1]
    assert last_call.request.url.path == "/instance/all"
    assert last_call.request.method == "GET"
    assert last_call.request.headers.get("admintoken")  # admin auth
    assert "token" not in {k.lower() for k in last_call.request.headers.keys() if k.lower() == "token"}


# --------------------------------------------------------------------------- #
# F3 / B3 — _retry_5xx: transient 5xx retries with exponential backoff       #
# --------------------------------------------------------------------------- #


async def test_list_chats_retries_on_5xx_then_succeeds(
    mock_uazapi: respx.MockRouter,
    uazapi_base: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B3: ``/chat/find`` returns 500 twice (sync still in flight) then 200.
    The retry helper transparently absorbs both failures and returns the
    successful body. respx must record exactly 3 calls."""
    # Zero out the backoff so the test doesn't actually wait 7s+.
    monkeypatch.setattr(
        "app.clients.whatsapp.uazapi._RETRY_DELAYS_S", (0.0, 0.0, 0.0)
    )

    success_body = {
        "chats": [
            {
                "wa_chatid": "5511999990001@s.whatsapp.net",
                "name": "Paciente A",
                "is_group": False,
                "last_message_at": 1_700_000_000,
            }
        ],
        "hasMore": False,
    }
    mock_uazapi.post(f"{uazapi_base}/chat/find").mock(
        side_effect=[
            httpx.Response(500, json={"error": "history sync in progress"}),
            httpx.Response(500, json={"error": "history sync in progress"}),
            httpx.Response(200, json=success_body),
        ]
    )

    provider = UazapiProvider()
    try:
        chats, has_more = await provider.list_chats(
            session_token="tok_xyz", limit=100, offset=0
        )
    finally:
        await provider.aclose()

    assert len(chats) == 1
    assert chats[0].wa_chatid == "5511999990001@s.whatsapp.net"
    assert has_more is False

    chat_calls = [c for c in mock_uazapi.calls if c.request.url.path == "/chat/find"]
    assert len(chat_calls) == 3, "should retry twice then succeed (3 calls total)"


async def test_list_chats_retry_exhausted_raises_unavailable(
    mock_uazapi: respx.MockRouter,
    uazapi_base: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B3: after the full retry budget (1 initial + 3 retries = 4 attempts)
    the last ``UazapiUnavailable`` is re-raised to the caller."""
    monkeypatch.setattr(
        "app.clients.whatsapp.uazapi._RETRY_DELAYS_S", (0.0, 0.0, 0.0)
    )

    mock_uazapi.post(f"{uazapi_base}/chat/find").mock(
        side_effect=[
            httpx.Response(500, json={"error": "down"}),
            httpx.Response(500, json={"error": "down"}),
            httpx.Response(500, json={"error": "down"}),
            httpx.Response(500, json={"error": "down"}),
        ]
    )

    provider = UazapiProvider()
    try:
        with pytest.raises(UazapiUnavailable):
            await provider.list_chats(
                session_token="tok_xyz", limit=100, offset=0
            )
    finally:
        await provider.aclose()

    chat_calls = [c for c in mock_uazapi.calls if c.request.url.path == "/chat/find"]
    assert len(chat_calls) == 4, "should attempt 4 times then give up"


async def test_list_chats_4xx_no_retry(
    mock_uazapi: respx.MockRouter,
    uazapi_base: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """4xx is NOT transient: ``_request`` maps it to ``UazapiUnknown`` and
    ``_retry_5xx`` re-raises immediately without retry. respx must record
    only a single call."""
    monkeypatch.setattr(
        "app.clients.whatsapp.uazapi._RETRY_DELAYS_S", (0.0, 0.0, 0.0)
    )

    mock_uazapi.post(f"{uazapi_base}/chat/find").mock(
        return_value=httpx.Response(400, json={"error": "bad request"})
    )

    provider = UazapiProvider()
    try:
        with pytest.raises(UazapiUnknown):
            await provider.list_chats(
                session_token="tok_xyz", limit=100, offset=0
            )
    finally:
        await provider.aclose()

    chat_calls = [c for c in mock_uazapi.calls if c.request.url.path == "/chat/find"]
    assert len(chat_calls) == 1, "4xx must not trigger retries"


async def test_list_messages_retries_on_5xx(
    mock_uazapi: respx.MockRouter,
    uazapi_base: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bonus: ``list_messages`` (also wrapped in ``_retry_5xx``) recovers
    from a transient 500 the same way ``list_chats`` does."""
    monkeypatch.setattr(
        "app.clients.whatsapp.uazapi._RETRY_DELAYS_S", (0.0, 0.0, 0.0)
    )

    success_body: dict[str, Any] = {
        "messages": [
            {
                "ts": 1_700_000_000,
                "fromMe": False,
                "type": "text",
                "text": "oi",
            }
        ],
        "hasMore": False,
        "nextOffset": 1,
    }
    mock_uazapi.post(f"{uazapi_base}/message/find").mock(
        side_effect=[
            httpx.Response(500, json={"error": "transient"}),
            httpx.Response(200, json=success_body),
        ]
    )

    provider = UazapiProvider()
    try:
        messages, has_more, next_offset = await provider.list_messages(
            session_token="tok_xyz",
            chat_id="5511999990001@s.whatsapp.net",
            limit=100,
            offset=0,
        )
    finally:
        await provider.aclose()

    assert len(messages) == 1
    assert messages[0].text == "oi"
    assert has_more is False
    assert next_offset == 1

    msg_calls = [c for c in mock_uazapi.calls if c.request.url.path == "/message/find"]
    assert len(msg_calls) == 2, "should retry once then succeed"
