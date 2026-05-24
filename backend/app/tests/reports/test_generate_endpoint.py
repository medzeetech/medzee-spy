"""HTTP route tests for ``POST /api/reports/generate``.

Scope: route layer only — auth gating, body validation, rate limiting, and
the happy-path envelope. The dispatch ``service.trigger_generate(...)`` is
exercised by ``test_service.py``.

F5 simplification (still current): the route no longer enforces a minimum
``message_count`` — it always dispatches and lets the worker persist a
``data_quality='insufficient'`` short-circuit when there's nothing useful.

F8: ``period_days`` is still accepted for backwards compatibility but the
default ``mode='last_n_per_chat'`` ignores it and uses ``n_per_chat`` (30).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.security import get_current_user_id
from app.main import app
from app.modules.reports.service import get_report_service


# Local stand-in: the route's snapshot pre-check still calls
# ``captured_messages.stats_for_user`` for log observability. We mock it so
# tests don't touch Supabase.
_REPO_REIMPORT_SITES: tuple[str, ...] = (
    "app.modules.captured_messages.repository",
    "app.modules.reports.routes",
)


@pytest.fixture
def fake_captured_repo(monkeypatch) -> SimpleNamespace:
    """Replace ``stats_for_user`` with an ``AsyncMock`` returning empty stats."""
    empty_stats = {
        "message_count": 0,
        "conversation_count": 0,
        "last_message_at": None,
    }
    stats_for_user = AsyncMock(
        return_value=dict(empty_stats), name="stats_for_user"
    )
    for site in _REPO_REIMPORT_SITES:
        monkeypatch.setattr(
            f"{site}.stats_for_user", stats_for_user, raising=False
        )
    return SimpleNamespace(stats_for_user=stats_for_user)


@pytest.fixture(autouse=True)
def _clear_overrides_and_rate_limit():
    """Reset everything that can leak between tests."""
    from app.modules.reports import routes as reports_routes

    reports_routes._last_generate_call.clear()
    yield
    app.dependency_overrides.clear()
    reports_routes._last_generate_call.clear()


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #


def test_generate_without_token_returns_401_or_403():
    """No Authorization header → HTTPBearer rejects before the body even
    deserializes. Accept 401 or 403 (FastAPI default is 403).
    """
    client = TestClient(app)
    r = client.post("/api/reports/generate", json={"period_days": 30})
    assert r.status_code in (401, 403)


def test_generate_invalid_period_days_returns_422(fake_captured_repo):
    """``period_days`` is a ``Literal[7, 15, 30, 60]`` — any other value
    must be rejected by FastAPI's pydantic validation with a 422.
    """
    user_id = uuid4()
    app.dependency_overrides[get_current_user_id] = lambda: user_id

    client = TestClient(app)
    r = client.post("/api/reports/generate", json={"period_days": 999})
    assert r.status_code == 422


def test_generate_happy_returns_report_id(fake_captured_repo):
    """Happy path: first call → 200 with the new ``report_id`` returned by
    the service plus ``status: 'generating'``.

    F5/F8: the route always dispatches (no min-volume gate) and forwards
    ``mode/n_per_chat/period_days`` to the service.
    """
    user_id = uuid4()
    new_report_id = UUID("12345678-1234-1234-1234-123456789abc")
    app.dependency_overrides[get_current_user_id] = lambda: user_id

    fake_service = AsyncMock()
    fake_service.trigger_generate = AsyncMock(return_value=new_report_id)
    app.dependency_overrides[get_report_service] = lambda: fake_service

    client = TestClient(app)
    r = client.post("/api/reports/generate", json={"period_days": 7})

    assert r.status_code == 200
    body = r.json()
    assert body["data"]["report_id"] == str(new_report_id)
    assert body["data"]["status"] == "generating"
    fake_service.trigger_generate.assert_awaited_once()
    args, kwargs = fake_service.trigger_generate.call_args
    assert args[0] == user_id
    # F5 defaults — mode=last_n_per_chat, n_per_chat=30, period_days=7 (from body).
    assert kwargs["period_days"] == 7
    assert kwargs["mode"] == "last_n_per_chat"
    assert kwargs["n_per_chat"] == 30


def test_generate_rate_limit_returns_429_on_second_call(fake_captured_repo):
    """Two back-to-back calls from the same user → first succeeds, second
    is rejected with 429 ``too_many_generations_retry_in_*s``.
    """
    user_id = uuid4()
    app.dependency_overrides[get_current_user_id] = lambda: user_id

    fake_service = AsyncMock()
    fake_service.trigger_generate = AsyncMock(return_value=uuid4())
    app.dependency_overrides[get_report_service] = lambda: fake_service

    client = TestClient(app)
    r1 = client.post("/api/reports/generate", json={"period_days": 30})
    assert r1.status_code == 200

    r2 = client.post("/api/reports/generate", json={"period_days": 30})
    assert r2.status_code == 429
    assert "too_many_generations" in r2.json()["detail"]


def test_generate_accepts_all_allowed_periods(fake_captured_repo):
    """``period_days`` ∈ {7, 15, 30, 60} should all be accepted by the
    validator. Use a fresh user per call to dodge the rate limit.
    """
    fake_service = AsyncMock()
    fake_service.trigger_generate = AsyncMock(return_value=uuid4())
    app.dependency_overrides[get_report_service] = lambda: fake_service

    user_ids: list[UUID] = []
    client = TestClient(app)
    for period in (7, 15, 30, 60):
        user_id = uuid4()
        user_ids.append(user_id)
        app.dependency_overrides[get_current_user_id] = lambda uid=user_id: uid

        r = client.post(
            "/api/reports/generate", json={"period_days": period}
        )
        assert r.status_code == 200, f"period={period} failed: {r.text}"

    assert fake_service.trigger_generate.await_count == 4
    actual_periods = [
        call.kwargs["period_days"]
        for call in fake_service.trigger_generate.await_args_list
    ]
    assert actual_periods == [7, 15, 30, 60]
