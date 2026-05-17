"""HTTP route tests for ``GET /api/whatsapp/status`` (F4-T19).

Style mirrors ``app/tests/reports/test_routes.py``:

* ``TestClient(app)`` (sync) for HTTP exercising.
* ``app.dependency_overrides`` swaps ``get_current_user_id`` so we bypass
  the real ``HTTPBearer`` + Supabase token lookup.
* ``monkeypatch`` swaps both ``whatsapp_repo.get_active_for_user`` and
  the ``captured_messages.repository.stats_for_session`` calls (the
  latter via the shared :func:`fake_captured_repo` fixture imported from
  ``app.tests.captured_messages.conftest``).
* An autouse fixture clears overrides after each test so suites don't
  bleed.

Scope: route layer only — auth gating, schema envelope, and the two
state branches (no session / active session). Repository and service
internals live in their own test files.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.security import get_current_user_id
from app.main import app


# The captured_messages conftest exposes a ``fake_captured_repo`` fixture
# scoped to its parent package, so we can't import it here. Pytest also
# refuses ``pytest_plugins`` on a conftest path that's already auto-loaded
# elsewhere (ValueError: Plugin already registered). The cheapest
# resolution: redefine the slice of the fixture we actually need locally —
# we only consume ``stats_for_session`` here, patched at the canonical
# location and at the whatsapp route's re-import site.
_REPO_REIMPORT_SITES: tuple[str, ...] = (
    "app.modules.captured_messages.repository",
    "app.modules.whatsapp.routes",
)


@pytest.fixture
def fake_captured_repo(monkeypatch) -> SimpleNamespace:
    """Minimal local stand-in for the sibling F4 fixture.

    Replaces ``stats_for_session`` with an ``AsyncMock`` returning an
    empty-stats dict by default. Tests override ``.return_value`` to
    inject specific counts.
    """
    empty_stats = {
        "message_count": 0,
        "conversation_count": 0,
        "last_message_at": None,
    }
    stats_for_session = AsyncMock(
        return_value=dict(empty_stats), name="stats_for_session"
    )
    for site in _REPO_REIMPORT_SITES:
        monkeypatch.setattr(
            f"{site}.stats_for_session", stats_for_session, raising=False
        )
    return SimpleNamespace(stats_for_session=stats_for_session)


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _clear_overrides():
    """Clear ``app.dependency_overrides`` after each test (no cross-bleed)."""
    yield
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #


def test_status_without_token_returns_401_or_403():
    """HTTPBearer's ``auto_error`` default is 403 'Not authenticated' on a
    missing Authorization header. Accept both 401 and 403 to remain
    tolerant to future security-layer tweaks (e.g. flipping ``auto_error``
    off and raising 401 explicitly).
    """
    client = TestClient(app)
    r = client.get("/api/whatsapp/status")
    assert r.status_code in (401, 403)


def test_status_no_session_returns_disconnected(monkeypatch, fake_captured_repo):
    """When the user has no ``whatsapp_session`` row, the route short-circuits
    to ``{connected: false}`` with all other counts defaulting to zero/None.
    The captured_messages repo should not even be queried in this branch.
    """
    user_id = uuid4()
    app.dependency_overrides[get_current_user_id] = lambda: user_id

    monkeypatch.setattr(
        "app.modules.whatsapp.repository.get_active_for_user",
        AsyncMock(return_value=None),
    )

    client = TestClient(app)
    r = client.get("/api/whatsapp/status")

    assert r.status_code == 200
    body = r.json()
    assert body["data"]["connected"] is False
    assert body["data"]["session_id"] is None
    assert body["data"]["message_count"] == 0
    assert body["data"]["conversation_count"] == 0
    assert body["data"]["last_message_at"] is None


def test_status_with_active_session_returns_connected_and_counts(
    monkeypatch, fake_captured_repo
):
    """When the user has an active ``connected`` session, the route returns
    the full payload — ``connected=true``, the session id, and the message
    counts pulled from ``captured_repo.stats_for_session``.
    """
    user_id = uuid4()
    session_id = uuid4()
    app.dependency_overrides[get_current_user_id] = lambda: user_id

    connected_at = datetime.now(timezone.utc)
    monkeypatch.setattr(
        "app.modules.whatsapp.repository.get_active_for_user",
        AsyncMock(
            return_value={
                "id": str(session_id),
                "status": "connected",
                "connected_at": connected_at.isoformat(),
            }
        ),
    )

    last_msg_at = datetime.now(timezone.utc)
    fake_captured_repo.stats_for_session.return_value = {
        "message_count": 42,
        "conversation_count": 5,
        "last_message_at": last_msg_at,
    }

    client = TestClient(app)
    r = client.get("/api/whatsapp/status")

    assert r.status_code == 200
    body = r.json()
    assert body["data"]["connected"] is True
    assert body["data"]["session_id"] == str(session_id)
    assert body["data"]["message_count"] == 42
    assert body["data"]["conversation_count"] == 5
    assert body["data"]["last_message_at"] is not None


def test_status_session_not_yet_connected_returns_disconnected_with_counts(
    monkeypatch, fake_captured_repo
):
    """When the session row exists but ``status != 'connected'`` (e.g. the
    user disconnected and we kept the row), the route returns
    ``connected=false`` but still surfaces the session id + last-known
    stats so the front can show "you had X messages last time".
    """
    user_id = uuid4()
    session_id = uuid4()
    app.dependency_overrides[get_current_user_id] = lambda: user_id

    monkeypatch.setattr(
        "app.modules.whatsapp.repository.get_active_for_user",
        AsyncMock(
            return_value={
                "id": str(session_id),
                "status": "disconnected",
                "connected_at": None,
            }
        ),
    )
    fake_captured_repo.stats_for_session.return_value = {
        "message_count": 7,
        "conversation_count": 2,
        "last_message_at": None,
    }

    client = TestClient(app)
    r = client.get("/api/whatsapp/status")

    assert r.status_code == 200
    body = r.json()
    assert body["data"]["connected"] is False
    assert body["data"]["session_id"] == str(session_id)
    assert body["data"]["message_count"] == 7
    assert body["data"]["conversation_count"] == 2
