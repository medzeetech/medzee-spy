"""Tests for the F4 TTL cleanup worker (``app.workers.ttl_cleanup``).

Covers ``_run_once()`` only — the infinite ``ttl_cleanup_loop`` is intentionally
not exercised here (it'd block; loop-level exception handling is documented in
the module docstring and verified manually).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.workers import ttl_cleanup


@pytest.fixture
def patched_repos(monkeypatch):
    """Patch both repos that ``_run_once`` depends on.

    Note: ``_run_once`` does ``from app.modules.whatsapp import repository as
    whatsapp_repo`` *inside* the function, so we must patch the attribute on
    the source module (which is what the local import binds to).
    """
    find_disconnected = AsyncMock(return_value=[])
    delete_for_session = AsyncMock(return_value=0)
    monkeypatch.setattr(
        "app.modules.whatsapp.repository.find_disconnected_before",
        find_disconnected,
    )
    monkeypatch.setattr(
        "app.modules.captured_messages.repository.delete_for_session",
        delete_for_session,
    )
    return find_disconnected, delete_for_session


async def test_run_once_deletes_expired_sessions(patched_repos):
    """Happy path: 2 sessions expired -> each gets delete_for_session called,
    return totals match."""
    find_disconnected, delete_for_session = patched_repos
    session_a, session_b = uuid4(), uuid4()
    find_disconnected.return_value = [session_a, session_b]
    delete_for_session.side_effect = [12, 8]  # 12 msgs from A, 8 from B

    result = await ttl_cleanup._run_once()

    assert result == {"expired_session_count": 2, "total_deleted": 20}
    # Called once per expired session.
    assert delete_for_session.await_count == 2
    # Verify session_ids passed (order matches iteration over the list).
    actual_args = [c.args[0] for c in delete_for_session.await_args_list]
    assert set(actual_args) == {session_a, session_b}


async def test_run_once_zero_expired_returns_zero(patched_repos):
    """Nothing expired -> return totals = 0, no delete calls."""
    find_disconnected, delete_for_session = patched_repos
    find_disconnected.return_value = []

    result = await ttl_cleanup._run_once()

    assert result == {"expired_session_count": 0, "total_deleted": 0}
    delete_for_session.assert_not_awaited()


async def test_run_once_uses_correct_cutoff(monkeypatch, patched_repos):
    """Cutoff passed to find_disconnected_before = now - TTL_DAYS."""
    find_disconnected, _ = patched_repos
    # Force TTL_DAYS=7 via env
    monkeypatch.setenv("CAPTURED_MESSAGES_TTL_DAYS", "7")

    before_call = datetime.now(timezone.utc)
    await ttl_cleanup._run_once()
    after_call = datetime.now(timezone.utc)

    assert find_disconnected.await_count == 1
    cutoff_arg = find_disconnected.await_args.args[0]
    expected_min = before_call - timedelta(days=7, seconds=1)
    expected_max = after_call - timedelta(days=7) + timedelta(seconds=1)
    assert expected_min <= cutoff_arg <= expected_max


async def test_run_once_respects_ttl_env_zero(monkeypatch, patched_repos):
    """TTL=0 means cutoff is essentially 'now' — all disconnected sessions
    are considered expired. Confirms env override path works."""
    find_disconnected, delete_for_session = patched_repos
    monkeypatch.setenv("CAPTURED_MESSAGES_TTL_DAYS", "0")
    find_disconnected.return_value = [uuid4()]
    delete_for_session.return_value = 5

    result = await ttl_cleanup._run_once()

    assert result["expired_session_count"] == 1
    assert result["total_deleted"] == 5


async def test_run_once_falls_back_when_ttl_env_invalid(monkeypatch, patched_repos):
    """Non-int TTL env value -> falls back to 30-day default (see _ttl_days)."""
    find_disconnected, _ = patched_repos
    monkeypatch.setenv("CAPTURED_MESSAGES_TTL_DAYS", "not-a-number")

    before_call = datetime.now(timezone.utc)
    await ttl_cleanup._run_once()
    after_call = datetime.now(timezone.utc)

    cutoff_arg = find_disconnected.await_args.args[0]
    expected_min = before_call - timedelta(days=30, seconds=1)
    expected_max = after_call - timedelta(days=30) + timedelta(seconds=1)
    assert expected_min <= cutoff_arg <= expected_max


async def test_run_once_propagates_delete_failure(patched_repos):
    """If delete_for_session raises, _run_once propagates (no per-iteration
    catch). Verified against source: only ``ttl_cleanup_loop`` swallows
    exceptions; ``_run_once`` itself is intentionally raw so tests/callers can
    observe failures. After the raise, the second session is NOT processed."""
    find_disconnected, delete_for_session = patched_repos
    session_a, session_b = uuid4(), uuid4()
    find_disconnected.return_value = [session_a, session_b]
    delete_for_session.side_effect = [
        RuntimeError("DB blip"),  # first call fails -> bubbles up
        7,                        # would-be second call, never reached
    ]

    with pytest.raises(RuntimeError, match="DB blip"):
        await ttl_cleanup._run_once()

    # Only the first session was attempted before the exception propagated.
    assert delete_for_session.await_count == 1
    assert delete_for_session.await_args_list[0].args[0] == session_a
