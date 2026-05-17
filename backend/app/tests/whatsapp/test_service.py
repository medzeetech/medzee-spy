"""Unit tests for ``WhatsAppService`` (T7).

The service is a thin orchestrator over provider + store + repository, so
we mock those collaborators rather than wiring real I/O:

* ``provider`` — ``AsyncMock`` spec'd to ``WhatsAppProvider``.
* ``store``   — real ``SessionStore`` instance from the ``fresh_store`` fixture.
* ``repository.<func>`` — patched to ``AsyncMock`` per test so DB calls
  don't escape into Supabase.

Patch target: service does ``from app.modules.whatsapp import repository``
which puts the *module* in service's namespace. Patching
``app.modules.whatsapp.service.repository.<func>`` is equivalent to
patching the function on the module itself — every consumer sees it.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.clients.whatsapp import WhatsAppProvider
from app.clients.whatsapp.errors import UazapiUnavailable
from app.clients.whatsapp.types import ProviderSession
from app.modules.whatsapp.schemas import (
    SessionStatus,
    UazapiWebhookPayload,
)
from app.modules.whatsapp.service import (
    RateLimitExceeded,
    SessionNotFound,
    WhatsAppService,
    _RATE_LIMIT_WINDOW_S,
)
from app.modules.whatsapp.state import SessionStore


# --------------------------------------------------------------------------- #
# helpers / fixtures                                                          #
# --------------------------------------------------------------------------- #


@pytest.fixture
def mock_provider() -> AsyncMock:
    """A fresh ``AsyncMock`` spec'd to the provider Protocol.

    ``create_session`` and ``disconnect`` are pre-set to no-ops; tests can
    override per-call.
    """
    p = AsyncMock(spec=WhatsAppProvider)
    p.create_session.return_value = ProviderSession(
        session_token="tok_svc", qr_base64="QRBASE64"
    )
    p.register_webhook.return_value = None
    p.disconnect.return_value = None
    return p


@pytest.fixture
def mock_repo(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch every repository function the service touches to AsyncMock().

    Returns a MagicMock holder whose attributes mirror the patched names
    (``mock_repo.create``, ``mock_repo.mark_status``, …) for easy assertion.
    """
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


# --------------------------------------------------------------------------- #
# 1. create_session — happy path                                              #
# --------------------------------------------------------------------------- #


async def test_create_session_happy(
    mock_provider: AsyncMock,
    mock_repo: MagicMock,
    fresh_store: SessionStore,
) -> None:
    """Happy path: provider returns a ProviderSession; service wires
    webhook + repo.create + store.create and returns the QR payload."""
    svc = _svc(mock_provider, fresh_store)

    resp = await svc.create_session(client_ip="1.2.3.4")

    assert resp.qr == "QRBASE64"
    assert resp.status == "pending"
    assert isinstance(resp.session_id, UUID)

    mock_provider.create_session.assert_awaited_once()
    mock_provider.register_webhook.assert_awaited_once()
    mock_repo.create.assert_awaited_once()
    # Store has the freshly created session.
    state = await fresh_store.get(resp.session_id)
    assert state is not None
    assert state.uazapi_token == "tok_svc"
    assert state.qr_base64 == "QRBASE64"


# --------------------------------------------------------------------------- #
# 2. create_session — provider failure propagates                              #
# --------------------------------------------------------------------------- #


async def test_create_session_provider_failure_raises_through(
    mock_provider: AsyncMock,
    mock_repo: MagicMock,
    fresh_store: SessionStore,
) -> None:
    """If ``provider.create_session`` raises before we have a session_id,
    the error propagates and no DB row is touched."""
    mock_provider.create_session.side_effect = UazapiUnavailable("boom")

    svc = _svc(mock_provider, fresh_store)

    with pytest.raises(UazapiUnavailable):
        await svc.create_session(client_ip="1.2.3.4")

    mock_repo.create.assert_not_called()
    mock_repo.mark_failed.assert_not_called()


# --------------------------------------------------------------------------- #
# 3. rate-limit blocks 4th attempt from same IP                                #
# --------------------------------------------------------------------------- #


async def test_rate_limit_blocks_4th_attempt(
    mock_provider: AsyncMock,
    mock_repo: MagicMock,
    fresh_store: SessionStore,
) -> None:
    """Three creates from the same IP succeed; the 4th raises
    ``RateLimitExceeded`` (WPP-16: > 3 in 5min)."""
    svc = _svc(mock_provider, fresh_store)
    ip = "9.9.9.9"

    for _ in range(3):
        await svc.create_session(client_ip=ip)

    with pytest.raises(RateLimitExceeded):
        await svc.create_session(client_ip=ip)


# --------------------------------------------------------------------------- #
# 4. rate-limit window expires                                                #
# --------------------------------------------------------------------------- #


async def test_rate_limit_window_expires(
    mock_provider: AsyncMock,
    mock_repo: MagicMock,
    fresh_store: SessionStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After ``_RATE_LIMIT_WINDOW_S``+ elapses, old timestamps are pruned
    and a fresh attempt is allowed again."""
    svc = _svc(mock_provider, fresh_store)
    ip = "8.8.8.8"

    # Drive ``time.monotonic`` from a single mutable counter — every call
    # returns the current value. We bump it between create_session calls.
    import app.modules.whatsapp.service as service_mod
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(service_mod.time, "monotonic", lambda: clock["t"])

    # 3 attempts inside the window (clock barely moves).
    await svc.create_session(client_ip=ip)
    clock["t"] += 1.0
    await svc.create_session(client_ip=ip)
    clock["t"] += 1.0
    await svc.create_session(client_ip=ip)

    # Jump past the rate-limit window — old timestamps get pruned.
    clock["t"] += _RATE_LIMIT_WINDOW_S + 1.0
    # 4th attempt occurs *after* the window has elapsed → allowed.
    await svc.create_session(client_ip=ip)


# --------------------------------------------------------------------------- #
# 5. webhook event=connection / loggedIn=True                                  #
# --------------------------------------------------------------------------- #


async def test_handle_webhook_event_loggedin_publishes_connected_and_schedules_extract(
    mock_provider: AsyncMock,
    mock_repo: MagicMock,
    fresh_store: SessionStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On loggedIn=True, the service must (a) move state to CONNECTED,
    (b) publish the 'connected' event, (c) schedule ``_run_extract``."""
    svc = _svc(mock_provider, fresh_store)

    # Create a session in PENDING first so the webhook can target it.
    resp = await svc.create_session(client_ip="2.2.2.2")
    sid = resp.session_id

    # Track _run_extract invocations without actually firing the worker.
    extract_calls: list[UUID] = []

    async def _fake_run_extract(s: UUID) -> None:
        extract_calls.append(s)

    monkeypatch.setattr(svc, "_run_extract", _fake_run_extract)

    payload = {
        "event": "connection",
        "instance": "inst-1",
        "data": {"loggedIn": True, "jid": "5511987651234@s.whatsapp.net"},
    }
    await svc.handle_webhook_event(sid, payload)

    # Let the scheduled task get picked up by the loop.
    await asyncio.sleep(0)

    state = await fresh_store.get(sid)
    assert state is not None
    assert state.status == SessionStatus.CONNECTED
    # Phone is stored *unmasked* now (column/kwarg name kept for legacy schema).
    # Input "5511987651234@s.whatsapp.net" → strip suffix → "5511987651234".
    assert state.phone_masked == "5511987651234"
    assert state.last_event is not None
    assert state.last_event.name == "connected"
    assert state.last_event.data["phone"] == "5511987651234"

    assert extract_calls == [sid]


# --------------------------------------------------------------------------- #
# 6. webhook for unknown session → noop                                        #
# --------------------------------------------------------------------------- #


async def test_handle_webhook_event_unknown_session_noop(
    mock_provider: AsyncMock,
    mock_repo: MagicMock,
    fresh_store: SessionStore,
) -> None:
    """Webhook arrives for a session the store has never seen → silent
    no-op; no exception, no repository writes, no SSE."""
    svc = _svc(mock_provider, fresh_store)

    from uuid import uuid4
    sid = uuid4()

    payload = {
        "event": "connection",
        "instance": "inst-x",
        "data": {"loggedIn": True, "jid": "5511999990000@s.whatsapp.net"},
    }
    await svc.handle_webhook_event(sid, payload)

    # No state in the store, no repo writes.
    assert (await fresh_store.get(sid)) is None
    mock_repo.mark_status.assert_not_called()


# --------------------------------------------------------------------------- #
# 7. cancel_session — happy                                                    #
# --------------------------------------------------------------------------- #


async def test_cancel_session_happy(
    mock_provider: AsyncMock,
    mock_repo: MagicMock,
    fresh_store: SessionStore,
) -> None:
    """``cancel_session`` deletes the upstream instance (DELETE /instance
    handles disconnect + remove atomically), publishes 'expired', marks EXPIRED."""
    svc = _svc(mock_provider, fresh_store)

    resp = await svc.create_session(client_ip="3.3.3.3")
    sid = resp.session_id

    await svc.cancel_session(sid)

    mock_provider.delete_instance.assert_awaited_once_with("tok_svc")

    state = await fresh_store.get(sid)
    assert state is not None
    assert state.status == SessionStatus.EXPIRED
    assert state.last_event is not None
    assert state.last_event.name == "expired"
    assert state.last_event.data.get("reason") == "cancelled"


# --------------------------------------------------------------------------- #
# 8. cancel_session — already terminal → silent                                #
# --------------------------------------------------------------------------- #


async def test_cancel_session_already_terminal_silent(
    mock_provider: AsyncMock,
    mock_repo: MagicMock,
    fresh_store: SessionStore,
) -> None:
    """If the session is already CONSUMED (or any terminal status),
    ``cancel_session`` returns without poking the provider."""
    svc = _svc(mock_provider, fresh_store)

    resp = await svc.create_session(client_ip="4.4.4.4")
    sid = resp.session_id
    await fresh_store.update(sid, status=SessionStatus.CONSUMED)

    # Reset mocks so we only count calls from inside cancel_session.
    mock_provider.disconnect.reset_mock()
    mock_provider.delete_instance.reset_mock()

    await svc.cancel_session(sid)

    mock_provider.disconnect.assert_not_called()
    mock_provider.delete_instance.assert_not_called()


# --------------------------------------------------------------------------- #
# 9. cancel_session — not found → SessionNotFound                              #
# --------------------------------------------------------------------------- #


async def test_cancel_session_not_found_raises(
    mock_provider: AsyncMock,
    mock_repo: MagicMock,
    fresh_store: SessionStore,
) -> None:
    """Cancel for an unknown session raises ``SessionNotFound``."""
    svc = _svc(mock_provider, fresh_store)

    from uuid import uuid4
    with pytest.raises(SessionNotFound):
        await svc.cancel_session(uuid4())


# --------------------------------------------------------------------------- #
# 10. consume_extracted — happy path releases provider slot                    #
# --------------------------------------------------------------------------- #


async def test_consume_extracted_happy_releases_slot(
    mock_provider: AsyncMock,
    mock_repo: MagicMock,
    fresh_store: SessionStore,
) -> None:
    """When the session is in EXTRACTED at entry, consume_extracted should
    finalize the lifecycle and call ``provider.delete_instance`` exactly
    once to free the uazapi slot."""
    from uuid import uuid4
    svc = _svc(mock_provider, fresh_store)

    resp = await svc.create_session(client_ip="5.5.5.5")
    sid = resp.session_id
    await fresh_store.update(sid, status=SessionStatus.EXTRACTED)

    mock_provider.delete_instance.reset_mock()

    await svc.consume_extracted(sid, user_id=uuid4())

    mock_provider.delete_instance.assert_awaited_once_with("tok_svc")
    mock_repo.link_user.assert_awaited_once()
    mock_repo.mark_consumed.assert_awaited_once()


# --------------------------------------------------------------------------- #
# 11. consume_extracted — skip release when entry status already terminal      #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "entry_status",
    [SessionStatus.FAILED, SessionStatus.EXPIRED, SessionStatus.CONSUMED],
)
async def test_consume_extracted_skips_release_when_already_terminal(
    mock_provider: AsyncMock,
    mock_repo: MagicMock,
    fresh_store: SessionStore,
    entry_status: SessionStatus,
) -> None:
    """If the session is already in FAILED / EXPIRED / CONSUMED, the uazapi
    instance was already deleted by an upstream path (extract failure
    cleanup, TTL expire, cancel, or a previous consume). Reissuing
    ``DELETE /instance`` only spews a stale-token 401 warning into the
    logs — service must skip it."""
    from uuid import uuid4
    svc = _svc(mock_provider, fresh_store)

    resp = await svc.create_session(client_ip="6.6.6.6")
    sid = resp.session_id
    await fresh_store.update(sid, status=entry_status)

    mock_provider.delete_instance.reset_mock()
    mock_provider.disconnect.reset_mock()

    await svc.consume_extracted(sid, user_id=uuid4())

    mock_provider.delete_instance.assert_not_called()
    mock_provider.disconnect.assert_not_called()
    # The DB write + user link should still happen — only the provider call is skipped.
    mock_repo.link_user.assert_awaited_once()


# --------------------------------------------------------------------------- #
# 12. consume_extracted — also links the user on the reports row (F3)        #
# --------------------------------------------------------------------------- #


async def test_consume_extracted_calls_reports_link_user(
    mock_provider: AsyncMock,
    mock_repo: MagicMock,
    fresh_store: SessionStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F3 §REPORT-12: after linking the whatsapp_sessions row to the user,
    consume_extracted must also link the matching reports row.

    The current flow first checks whether a reports row exists for this
    session via ``get_existing_for_session``:
        - row exists → call ``link_user`` to backfill user_id.
        - row absent (race: signup before extract finished) → call
          ``create_generating`` to insert a placeholder.

    This case exercises the "row exists" branch.
    """
    from uuid import uuid4

    reports_get_existing = AsyncMock(
        name="reports.repository.get_existing_for_session",
        return_value={"id": "00000000-0000-0000-0000-000000000077"},
    )
    reports_link_user = AsyncMock(name="reports.repository.link_user")
    reports_create_generating = AsyncMock(
        name="reports.repository.create_generating",
        return_value="00000000-0000-0000-0000-000000000077",
    )
    monkeypatch.setattr(
        "app.modules.reports.repository.get_existing_for_session", reports_get_existing
    )
    monkeypatch.setattr(
        "app.modules.reports.repository.link_user", reports_link_user
    )
    monkeypatch.setattr(
        "app.modules.reports.repository.create_generating", reports_create_generating
    )

    svc = _svc(mock_provider, fresh_store)
    resp = await svc.create_session(client_ip="7.7.7.7")
    sid = resp.session_id
    await fresh_store.update(sid, status=SessionStatus.EXTRACTED)

    user_id = uuid4()
    await svc.consume_extracted(sid, user_id=user_id)

    reports_get_existing.assert_awaited_once_with(sid)
    reports_link_user.assert_awaited_once_with(sid, user_id)
    reports_create_generating.assert_not_awaited()
    # And the whatsapp-side link still happened too.
    mock_repo.link_user.assert_awaited_once()


# --------------------------------------------------------------------------- #
# 13. consume_extracted — swallows reports.link_user failures                 #
# --------------------------------------------------------------------------- #


async def test_consume_extracted_swallows_reports_link_failure(
    mock_provider: AsyncMock,
    mock_repo: MagicMock,
    fresh_store: SessionStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure inside the reports-side calls is best-effort —
    consume_extracted must log a warning and continue (mark_consumed still
    runs, payload still returns). Without this guarantee a transient
    reports outage would break the user-facing signup flow."""
    from uuid import uuid4

    reports_get_existing = AsyncMock(
        name="reports.repository.get_existing_for_session",
        side_effect=RuntimeError("reports schema down"),
    )
    monkeypatch.setattr(
        "app.modules.reports.repository.get_existing_for_session", reports_get_existing
    )

    svc = _svc(mock_provider, fresh_store)
    resp = await svc.create_session(client_ip="7.7.7.8")
    sid = resp.session_id
    await fresh_store.update(sid, status=SessionStatus.EXTRACTED)

    user_id = uuid4()
    # Should NOT raise.
    result = await svc.consume_extracted(sid, user_id=user_id)

    # No exception propagated; result is the (possibly-None) payload — what
    # matters here is that the call returned and downstream steps ran.
    assert result is None or hasattr(result, "message_count")
    reports_get_existing.assert_awaited_once()
    mock_repo.mark_consumed.assert_awaited_once()
    mock_repo.link_user.assert_awaited_once()
