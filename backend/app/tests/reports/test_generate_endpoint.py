"""HTTP route tests for ``POST /api/reports/generate`` (F4-T19).

Mirrors the style of ``app/tests/reports/test_routes.py``:

* ``TestClient(app)`` (sync) for HTTP exercising.
* ``app.dependency_overrides`` swaps ``get_current_user_id`` (bypass auth)
  and ``get_report_service`` (drive the route in isolation).
* ``fake_captured_repo`` (from the captured_messages conftest) controls
  the ``stats_for_user`` pre-check.
* Module-level ``_last_generate_call`` rate-limit bucket is cleared
  between tests so per-test users hit a fresh bucket.

Scope: route layer only — auth gating, body validation (Literal period
values), the two pre-conditions (rate limit + min volume), and the
happy-path envelope. The dispatch ``service.trigger_generate(...)`` is
exercised by ``test_service.py``.
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


# The F4 captured_messages conftest exposes ``fake_captured_repo`` scoped
# to its parent package — we can't ``pytest_plugins``-import it from here
# (ValueError: Plugin already registered when the conftest is also
# auto-loaded elsewhere). Local minimal fixture instead — we only consume
# ``stats_for_user`` here (the min-volume pre-check), patched at the
# canonical site plus the reports route's re-import site.
_REPO_REIMPORT_SITES: tuple[str, ...] = (
    "app.modules.captured_messages.repository",
    "app.modules.reports.routes",
)


@pytest.fixture
def fake_captured_repo(monkeypatch) -> SimpleNamespace:
    """Local stand-in for the sibling F4 fixture.

    Replaces ``stats_for_user`` with an ``AsyncMock`` returning an
    empty-stats dict by default. Tests override ``.return_value`` to
    inject the message_count value driving the pre-check branch.
    """
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


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _clear_overrides_and_rate_limit():
    """Reset everything that can leak between tests:

    * ``app.dependency_overrides`` — auth/service injection.
    * ``reports.routes._last_generate_call`` — the in-memory per-user
      rate-limit bucket (1/60s). Different tests use fresh UUIDs so this
      is mostly defensive, but the same suite re-using a UUID would
      otherwise pollute the next test.
    """
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
    deserializes. Accept 401 or 403 (see test_status_endpoint for the
    auto_error rationale).
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


def test_generate_with_zero_messages_returns_422_not_enough_data(
    fake_captured_repo,
):
    """Min-volume pre-check: ``message_count < REPORTS_GENERATE_MIN_MESSAGES``
    (default 10) → 422 ``not_enough_data``. The default ``fake_captured_repo``
    already returns zero, so we just hit the endpoint.
    """
    user_id = uuid4()
    app.dependency_overrides[get_current_user_id] = lambda: user_id

    fake_captured_repo.stats_for_user.return_value = {
        "message_count": 0,
        "conversation_count": 0,
        "last_message_at": None,
    }

    client = TestClient(app)
    r = client.post("/api/reports/generate", json={"period_days": 30})

    assert r.status_code == 422
    assert r.json()["detail"] == "not_enough_data"


def test_generate_happy_returns_report_id(fake_captured_repo):
    """Happy path: enough messages + first call → 200 with the new
    ``report_id`` returned by the service plus ``status: 'generating'``.
    Asserts the service was called with the right (user_id, period_days)
    pair.
    """
    user_id = uuid4()
    new_report_id = UUID("12345678-1234-1234-1234-123456789abc")
    app.dependency_overrides[get_current_user_id] = lambda: user_id

    fake_captured_repo.stats_for_user.return_value = {
        "message_count": 50,
        "conversation_count": 3,
        "last_message_at": None,
    }

    fake_service = AsyncMock()
    fake_service.trigger_generate = AsyncMock(return_value=new_report_id)
    app.dependency_overrides[get_report_service] = lambda: fake_service

    client = TestClient(app)
    r = client.post("/api/reports/generate", json={"period_days": 7})

    assert r.status_code == 200
    body = r.json()
    assert body["data"]["report_id"] == str(new_report_id)
    assert body["data"]["status"] == "generating"
    fake_service.trigger_generate.assert_awaited_once_with(
        user_id, period_days=7
    )


def test_generate_rate_limit_returns_429_on_second_call(fake_captured_repo):
    """Two back-to-back calls from the same user → first succeeds, second
    is rejected with 429 ``too_many_generations_retry_in_*s``. Uses the
    in-memory ``_last_generate_call`` bucket (cleared by autouse fixture
    between tests).
    """
    user_id = uuid4()
    app.dependency_overrides[get_current_user_id] = lambda: user_id

    fake_captured_repo.stats_for_user.return_value = {
        "message_count": 50,
        "conversation_count": 3,
        "last_message_at": None,
    }

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
    validator. We use a fresh user per call to dodge the per-user rate
    limit and assert the service receives each value verbatim.
    """
    fake_captured_repo.stats_for_user.return_value = {
        "message_count": 50,
        "conversation_count": 3,
        "last_message_at": None,
    }

    # Single service mock across the loop — we inspect ``call_args_list``
    # at the end rather than per-iteration. Per-iteration assertions
    # against per-iteration mocks are flaky because the route resolves
    # the dependency override via the *current* mapping but the assertion
    # closure captures a different binding.
    fake_service = AsyncMock()
    fake_service.trigger_generate = AsyncMock(return_value=uuid4())
    app.dependency_overrides[get_report_service] = lambda: fake_service

    user_ids: list[UUID] = []
    client = TestClient(app)
    for period in (7, 15, 30, 60):
        # Fresh user per iteration → fresh rate-limit bucket entry.
        user_id = uuid4()
        user_ids.append(user_id)
        app.dependency_overrides[get_current_user_id] = lambda uid=user_id: uid

        r = client.post(
            "/api/reports/generate", json={"period_days": period}
        )
        assert r.status_code == 200, f"period={period} failed: {r.text}"

    assert fake_service.trigger_generate.await_count == 4
    actual_calls = [
        (call.args[0], call.kwargs["period_days"])
        for call in fake_service.trigger_generate.await_args_list
    ]
    expected_calls = list(zip(user_ids, (7, 15, 30, 60)))
    assert actual_calls == expected_calls
