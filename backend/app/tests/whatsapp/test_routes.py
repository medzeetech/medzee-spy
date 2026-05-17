"""Integration tests for the 4 WhatsApp routes (T15).

These tests focus on the route layer's three responsibilities:

* **Routing** — paths, methods, status codes, response envelopes match the
  spec (WPP-01/02/04/06, EC-06).
* **Error mapping** — service-layer exceptions translate into the documented
  HTTP shapes (design § 10).
* **SSE wire format** — `text/event-stream` headers, ``event:`` / ``data:``
  framing, terminal-event stream closure.

The real provider + service behavior is unit-tested in T13/T14 (respx +
mocks); here we use ``app.dependency_overrides`` to swap ``get_service`` for
a ``MagicMock`` carrying ``AsyncMock`` methods, and we monkeypatch the
``session_store`` reference in ``routes.py`` for cases where the route reads
state directly (``GET /events``, ``DELETE``).

Why ``app.dependency_overrides`` instead of ``monkeypatch``: it is the
idiomatic FastAPI hook and survives `Depends` reuse across requests, while
patching the factory symbol misses requests that already resolved the
dependency at app-startup time.
"""
from __future__ import annotations

from typing import AsyncIterator, Iterator
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.whatsapp.schemas import (
    CreateSessionResponse,
    SessionStatus,
    SSEEvent,
)
from app.modules.whatsapp.service import (
    RateLimitExceeded,
    get_service,
)
from app.modules.whatsapp.state import SessionState, SessionStore
from app.clients.whatsapp.errors import (
    UazapiBanned,
    UazapiUnavailable,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_service() -> MagicMock:
    """A `WhatsAppService`-shaped MagicMock with AsyncMock methods.

    Default returns are happy-path stubs; individual tests override
    ``side_effect`` / ``return_value`` per method as needed.
    """
    svc = MagicMock(name="WhatsAppService")
    svc.create_session = AsyncMock(name="create_session")
    svc.handle_webhook_event = AsyncMock(name="handle_webhook_event")
    svc.cancel_session = AsyncMock(name="cancel_session")
    svc.consume_extracted = AsyncMock(name="consume_extracted")
    return svc


@pytest.fixture
def override_service(mock_service: MagicMock) -> Iterator[MagicMock]:
    """Install ``mock_service`` as the ``get_service`` dependency and clean up."""
    app.dependency_overrides[get_service] = lambda: mock_service
    try:
        yield mock_service
    finally:
        app.dependency_overrides.pop(get_service, None)


@pytest.fixture
def client(override_service: MagicMock) -> Iterator[TestClient]:
    """Sync TestClient with the service override + lifespan run.

    ``with TestClient(app) as c`` triggers the lifespan, which starts the
    ``session_store`` expire loop. The loop's first tick is 60s out, so it
    does not interfere with these tests; the ``stop_expire_loop`` on exit
    cancels it cleanly.
    """
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# POST /api/whatsapp/sessions
# ---------------------------------------------------------------------------


def test_post_sessions_happy(client: TestClient, mock_service: MagicMock) -> None:
    """Happy path: service returns a CreateSessionResponse → 200 SuccessResponse."""
    session_id = uuid4()
    mock_service.create_session.return_value = CreateSessionResponse(
        session_id=session_id,
        qr="abc",
        status="pending",
    )

    response = client.post("/api/whatsapp/sessions", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "ok"
    assert body["data"]["session_id"] == str(session_id)
    assert body["data"]["qr"] == "abc"
    assert body["data"]["status"] == "pending"
    mock_service.create_session.assert_awaited_once()


def test_post_sessions_429_rate_limit(
    client: TestClient, mock_service: MagicMock
) -> None:
    """RateLimitExceeded → 429 with detail 'too_many_sessions' (WPP-16)."""
    mock_service.create_session.side_effect = RateLimitExceeded("too_many_sessions")

    response = client.post("/api/whatsapp/sessions", json={})

    assert response.status_code == 429
    assert response.json() == {"detail": "too_many_sessions"}


def test_post_sessions_503_uazapi_unavailable(
    client: TestClient, mock_service: MagicMock
) -> None:
    """UazapiUnavailable → 503 detail='uazapi_unavailable' (design § 10)."""
    mock_service.create_session.side_effect = UazapiUnavailable("boom")

    response = client.post("/api/whatsapp/sessions", json={})

    assert response.status_code == 503
    assert response.json() == {"detail": "uazapi_unavailable"}


def test_post_sessions_502_banned(
    client: TestClient, mock_service: MagicMock
) -> None:
    """UazapiBanned → 502 detail='banned' (provider_code 463 collapses here)."""
    mock_service.create_session.side_effect = UazapiBanned("banned")

    response = client.post("/api/whatsapp/sessions", json={})

    assert response.status_code == 502
    assert response.json() == {"detail": "banned"}


# ---------------------------------------------------------------------------
# GET /api/whatsapp/sessions/{id}/events  (SSE)
# ---------------------------------------------------------------------------


def test_get_events_404_when_session_unknown(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown session → 404 detail='session_not_found'."""
    from app.modules.whatsapp import routes as routes_mod

    async def _none(_sid: UUID) -> None:
        return None

    monkeypatch.setattr(routes_mod.session_store, "get", _none)

    sid = uuid4()
    response = client.get(f"/api/whatsapp/sessions/{sid}/events")

    assert response.status_code == 404
    assert response.json() == {"detail": "session_not_found"}


async def test_get_events_streams_replay_last_then_terminal(
    monkeypatch: pytest.MonkeyPatch,
    mock_service: MagicMock,
) -> None:
    """SSE stream replays last_event for terminal session and closes.

    We swap the module-level ``session_store`` in ``routes.py`` for a fresh
    SessionStore, pre-populate it with a session whose ``last_event`` is the
    terminal ``extracted`` event, then read the stream. The first (and only)
    frame should carry ``event: extracted`` + the JSON ``data:`` payload,
    after which the generator returns and the stream closes (WPP-15).
    """
    from app.modules.whatsapp import routes as routes_mod

    fresh_store = SessionStore()
    monkeypatch.setattr(routes_mod, "session_store", fresh_store)

    session_id = uuid4()
    await fresh_store.create(
        session_id, uazapi_token="tok_test", qr_base64="qr_b64"
    )
    # Drive the session to a terminal state and pin the replay event.
    await fresh_store.update(session_id, status=SessionStatus.EXTRACTED)
    terminal_event = SSEEvent(
        name="extracted",
        data={"message_count": 42, "conversation_count": 3},
    )
    await fresh_store.publish(session_id, terminal_event)

    # Use AsyncClient + ASGITransport so we can iterate bytes async.
    app.dependency_overrides[get_service] = lambda: mock_service
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as ac:
            async with ac.stream(
                "GET",
                f"/api/whatsapp/sessions/{session_id}/events",
                timeout=5.0,
            ) as r:
                assert r.status_code == 200
                assert r.headers["content-type"].startswith("text/event-stream")
                assert r.headers.get("cache-control") == "no-cache"
                assert r.headers.get("x-accel-buffering") == "no"

                body = b""
                async for chunk in r.aiter_bytes():
                    body += chunk
                    # One terminal frame is enough; subscribe() returns after it.
                    if b"\n\n" in body:
                        break
    finally:
        app.dependency_overrides.pop(get_service, None)

    text = body.decode("utf-8")
    assert "event: extracted" in text
    assert '"message_count": 42' in text
    assert '"conversation_count": 3' in text
    # Frame terminator present.
    assert text.endswith("\n\n") or "\n\n" in text


# ---------------------------------------------------------------------------
# POST /api/whatsapp/webhook
# ---------------------------------------------------------------------------


def test_post_webhook_200_on_unknown_session(
    client: TestClient, mock_service: MagicMock
) -> None:
    """Webhook for unknown session → 200 {'status':'ok'} (no 404 leak, EC-06)."""
    # handle_webhook_event is itself a no-op for unknown sessions — we just
    # make sure the route doesn't raise and returns 200.
    mock_service.handle_webhook_event.return_value = None

    sid = uuid4()
    response = client.post(
        f"/api/whatsapp/webhook?session_id={sid}",
        json={
            "event": "connection",
            "instance": "inst_1",
            "data": {"loggedIn": False},
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_service.handle_webhook_event.assert_awaited_once()


def test_post_webhook_always_returns_200_on_exception(
    client: TestClient, mock_service: MagicMock
) -> None:
    """Service raising should NOT propagate — webhook stays 200 (EC-06).

    uazapi retries non-2xx forever; the route swallows handler errors so a
    transient blip in the service doesn't trigger a retry storm.
    """
    mock_service.handle_webhook_event.side_effect = RuntimeError("boom")

    sid = uuid4()
    response = client.post(
        f"/api/whatsapp/webhook?session_id={sid}",
        json={
            "event": "connection",
            "instance": "inst_1",
            "data": {"loggedIn": True, "jid": "5511999990001@s.whatsapp.net"},
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_service.handle_webhook_event.assert_awaited_once()


# ---------------------------------------------------------------------------
# DELETE /api/whatsapp/sessions/{id}
# ---------------------------------------------------------------------------


def test_delete_already_terminal(
    client: TestClient,
    mock_service: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session already in a terminal status → 200 {'status':'already_terminal'}.

    The route peeks state via ``session_store.get`` *before* calling the
    service so it can distinguish 'cancelled' from 'already_terminal' (the
    service is silently idempotent and would not signal this otherwise).
    """
    from app.modules.whatsapp import routes as routes_mod

    sid = uuid4()
    terminal_state = SessionState(
        session_id=sid,
        uazapi_token="tok_test",
        status=SessionStatus.CONSUMED,
    )

    async def _get(_sid: UUID) -> SessionState:
        return terminal_state

    monkeypatch.setattr(routes_mod.session_store, "get", _get)

    response = client.delete(f"/api/whatsapp/sessions/{sid}")

    assert response.status_code == 200
    assert response.json() == {"status": "already_terminal"}
    mock_service.cancel_session.assert_not_awaited()


def test_delete_cancelled(
    client: TestClient,
    mock_service: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Active session → service.cancel_session awaited, 200 {'status':'cancelled'}."""
    from app.modules.whatsapp import routes as routes_mod

    sid = uuid4()
    active_state = SessionState(
        session_id=sid,
        uazapi_token="tok_test",
        status=SessionStatus.PENDING,
    )

    async def _get(_sid: UUID) -> SessionState:
        return active_state

    monkeypatch.setattr(routes_mod.session_store, "get", _get)

    response = client.delete(f"/api/whatsapp/sessions/{sid}")

    assert response.status_code == 200
    assert response.json() == {"status": "cancelled"}
    mock_service.cancel_session.assert_awaited_once_with(sid)


def test_delete_session_not_found(
    client: TestClient,
    mock_service: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown session → 404 detail='session_not_found'."""
    from app.modules.whatsapp import routes as routes_mod

    async def _none(_sid: UUID) -> None:
        return None

    monkeypatch.setattr(routes_mod.session_store, "get", _none)

    sid = uuid4()
    response = client.delete(f"/api/whatsapp/sessions/{sid}")

    assert response.status_code == 404
    assert response.json() == {"detail": "session_not_found"}
    mock_service.cancel_session.assert_not_awaited()


# ---------------------------------------------------------------------------
# Regression smoke
# ---------------------------------------------------------------------------


def test_health_still_responds(client: TestClient) -> None:
    """GET /health → 200 {'status':'ok'} — mounting whatsapp routes didn't
    regress the top-level health check (T12)."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
