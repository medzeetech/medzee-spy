"""Shared fixtures for WhatsApp module tests.

The `mock_uazapi` fixture wires happy-path responses for the 7 endpoints that
`UazapiProvider` (design § 4.3) talks to. Individual tests can override any
single route via `respx_mock.post(...).mock(return_value=...)` — the last call
to `.mock(...)` wins.

`fake_admin_supabase` patches `get_supabase_admin_client` to a `MagicMock` so
the repository layer can be exercised without hitting Supabase.

`fresh_store` yields a fresh `SessionStore()` if T6 has landed; otherwise it
emits a `pytest.skip` so other tests in the suite still collect.
"""
from __future__ import annotations

from typing import Iterator
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from app.core.config import settings


@pytest.fixture(autouse=True)
def _disable_extract_post_connected_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """B3 fix introduced a 5s sleep before the first /chat/find. Tests would
    otherwise spend an extra 5s per extract scenario — autouse this patch so
    every whatsapp test sees a zero delay. The constant lives in
    ``app.workers.extract`` (F3 §REPORT-14)."""
    monkeypatch.setattr(
        "app.workers.extract._POST_CONNECTED_DELAY_S", 0.0, raising=False
    )


@pytest.fixture(autouse=True)
def _no_op_report_kickoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """F3 wires extract → report worker via ``_kick_off_report`` which fires
    ``asyncio.create_task``. In tests the spawned task survives past the
    event-loop teardown and pollutes output with "Task was destroyed but
    it is pending!" warnings. Tests that specifically verify the trigger
    can override this in their own scope."""
    monkeypatch.setattr(
        "app.workers.extract._kick_off_report",
        lambda *args, **kwargs: None,
        raising=False,
    )


# Stable test URL — tests must monkeypatch settings.UAZAPI_BASE_URL to this
# so the adapter's httpx.AsyncClient (constructed lazily with that base_url)
# routes through respx.
TEST_UAZAPI_BASE = "http://uazapi.test"


@pytest.fixture
def uazapi_base(monkeypatch: pytest.MonkeyPatch) -> str:
    """Pin settings.UAZAPI_BASE_URL to a deterministic test URL."""
    monkeypatch.setattr(settings, "UAZAPI_BASE_URL", TEST_UAZAPI_BASE)
    monkeypatch.setattr(settings, "UAZAPI_ADMIN_TOKEN", "admin_tok_test")
    return TEST_UAZAPI_BASE


@pytest.fixture
def respx_mock() -> Iterator[respx.MockRouter]:
    """Locally-scoped respx router. Mirrors the `pytest-respx` plugin so we
    don't depend on plugin discovery quirks on Windows."""
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


@pytest.fixture
def mock_uazapi(
    respx_mock: respx.MockRouter,
    uazapi_base: str,
) -> respx.MockRouter:
    """Pre-stubs all 7 uazapi endpoints with happy-path responses.

    Tests can override any route by calling `.mock(...)` again — respx applies
    the most recently registered route.
    """
    base = uazapi_base

    respx_mock.post(f"{base}/instance/create").mock(
        return_value=httpx.Response(
            200,
            json={
                "token": "tok_xyz",
                "instance": {"id": "inst_1", "name": "test"},
            },
        )
    )
    respx_mock.post(f"{base}/instance/connect").mock(
        return_value=httpx.Response(
            200,
            json={
                "connected": False,
                "loggedIn": False,
                "instance": {
                    "qrcode": "<fake_base64>",
                    "paircode": None,
                },
            },
        )
    )
    respx_mock.post(f"{base}/webhook").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    respx_mock.get(f"{base}/instance/status").mock(
        return_value=httpx.Response(
            200,
            json={
                "instance": {"id": "inst_1"},
                "status": {
                    "connected": True,
                    "loggedIn": True,
                    "jid": "5511999990001@s.whatsapp.net",
                },
            },
        )
    )
    respx_mock.post(f"{base}/chat/find").mock(
        return_value=httpx.Response(
            200,
            json={"chats": [], "hasMore": False},
        )
    )
    respx_mock.post(f"{base}/message/find").mock(
        return_value=httpx.Response(
            200,
            json={
                "messages": [],
                "hasMore": False,
                "nextOffset": 0,
            },
        )
    )
    respx_mock.post(f"{base}/instance/disconnect").mock(
        return_value=httpx.Response(200, json={"status": "disconnected"})
    )
    return respx_mock


@pytest.fixture
def fake_admin_supabase(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch `get_supabase_admin_client` to return a recording MagicMock.

    Returns the mock itself so tests can inspect `mock.return_value.schema(...).
    table(...).insert(...).execute()` chains.
    """
    fake = MagicMock(name="supabase_admin_client")
    monkeypatch.setattr(
        "app.clients.supabase.get_supabase_admin_client",
        lambda: fake,
    )
    return fake


@pytest.fixture
def fresh_store():
    """Yields a fresh SessionStore() instance, or skips if T6 hasn't landed."""
    try:
        from app.modules.whatsapp.state import SessionStore
    except ImportError:
        pytest.skip("SessionStore not yet implemented (T6)")
    return SessionStore()
