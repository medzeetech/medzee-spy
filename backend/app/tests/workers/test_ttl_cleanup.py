"""Tests for the rolling-window TTL cleanup worker (``app.workers.ttl_cleanup``).

Covers ``_run_once()`` only — the infinite ``ttl_cleanup_loop`` is intentionally
not exercised here (it'd block; loop-level exception handling is documented in
the module docstring and verified manually).

The worker now issues a single ``DELETE FROM captured_messages WHERE ts < cutoff``
via the Supabase admin client, where ``cutoff = now - CAPTURED_MESSAGES_TTL_DAYS``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.workers import ttl_cleanup


@pytest.fixture
def fake_supabase(monkeypatch):
    """Patch the lazy import of ``get_supabase_admin_client`` inside ``_run_once``.

    ``_run_once`` does ``from app.clients.supabase import get_supabase_admin_client``
    at call-time, so we patch the canonical site (the import binds to whatever
    is bound on the source module at that moment).
    """
    fake = MagicMock(name="supabase_admin_client")
    # Default empty delete response — tests override ``.data`` when needed.
    table = fake.schema.return_value.table.return_value
    table.delete.return_value.lt.return_value.execute.return_value = (
        SimpleNamespace(data=[])
    )
    monkeypatch.setattr(
        "app.clients.supabase.get_supabase_admin_client",
        lambda: fake,
    )
    return fake


def _delete_chain(fake: MagicMock) -> MagicMock:
    """Shortcut: returns the ``.delete().lt()`` handle for return-value rigging."""
    return (
        fake.schema.return_value.table.return_value.delete.return_value.lt
    )


async def test_run_once_deletes_rows_older_than_cutoff(fake_supabase):
    """Happy path: 12 expired rows → returns total_deleted=12 and issues a
    DELETE filtered by ``ts < cutoff``.
    """
    _delete_chain(fake_supabase).return_value.execute.return_value = (
        SimpleNamespace(data=[{"id": f"r{i}"} for i in range(12)])
    )

    result = await ttl_cleanup._run_once()

    assert result["total_deleted"] == 12
    assert result["ttl_days"] == 30
    # Targeted the right schema + table.
    fake_supabase.schema.assert_called_with("medzee_spy")
    fake_supabase.schema.return_value.table.assert_called_with("captured_messages")
    # Filter clause uses the ``ts`` column with ``lt``.
    lt_call = _delete_chain(fake_supabase).call_args
    assert lt_call.args[0] == "ts"
    # ISO 8601 cutoff value — sanity-check it parses as a datetime.
    cutoff_iso = lt_call.args[1]
    parsed = datetime.fromisoformat(cutoff_iso)
    assert parsed.tzinfo is not None


async def test_run_once_zero_deleted_returns_zero(fake_supabase):
    """No rows older than cutoff → total_deleted=0, still a clean exit."""
    _delete_chain(fake_supabase).return_value.execute.return_value = (
        SimpleNamespace(data=[])
    )

    result = await ttl_cleanup._run_once()

    assert result == {"total_deleted": 0, "ttl_days": 30}


async def test_run_once_uses_correct_cutoff(monkeypatch, fake_supabase):
    """Cutoff passed to ``.lt('ts', ...)`` = now - TTL_DAYS."""
    monkeypatch.setenv("CAPTURED_MESSAGES_TTL_DAYS", "7")

    before_call = datetime.now(timezone.utc)
    await ttl_cleanup._run_once()
    after_call = datetime.now(timezone.utc)

    lt_call = _delete_chain(fake_supabase).call_args
    cutoff_iso = lt_call.args[1]
    cutoff = datetime.fromisoformat(cutoff_iso)
    expected_min = before_call - timedelta(days=7, seconds=1)
    expected_max = after_call - timedelta(days=7) + timedelta(seconds=1)
    assert expected_min <= cutoff <= expected_max


async def test_run_once_respects_ttl_env_zero(monkeypatch, fake_supabase):
    """TTL=0 means cutoff is essentially 'now' — everything counts as expired."""
    monkeypatch.setenv("CAPTURED_MESSAGES_TTL_DAYS", "0")
    _delete_chain(fake_supabase).return_value.execute.return_value = (
        SimpleNamespace(data=[{"id": "r1"}, {"id": "r2"}, {"id": "r3"}, {"id": "r4"}, {"id": "r5"}])
    )

    result = await ttl_cleanup._run_once()

    assert result["total_deleted"] == 5
    assert result["ttl_days"] == 0


async def test_run_once_falls_back_when_ttl_env_invalid(monkeypatch, fake_supabase):
    """Non-int TTL env value -> falls back to 30-day default (see _ttl_days)."""
    monkeypatch.setenv("CAPTURED_MESSAGES_TTL_DAYS", "not-a-number")

    before_call = datetime.now(timezone.utc)
    await ttl_cleanup._run_once()
    after_call = datetime.now(timezone.utc)

    lt_call = _delete_chain(fake_supabase).call_args
    cutoff_iso = lt_call.args[1]
    cutoff = datetime.fromisoformat(cutoff_iso)
    expected_min = before_call - timedelta(days=30, seconds=1)
    expected_max = after_call - timedelta(days=30) + timedelta(seconds=1)
    assert expected_min <= cutoff <= expected_max


async def test_run_once_propagates_delete_failure(fake_supabase):
    """If the DELETE blows up, ``_run_once`` propagates (no per-call catch).

    Loop-level swallowing happens in ``ttl_cleanup_loop`` only; ``_run_once``
    itself is intentionally raw so tests/callers can observe failures.
    """
    _delete_chain(fake_supabase).return_value.execute.side_effect = RuntimeError(
        "DB blip"
    )

    with pytest.raises(RuntimeError, match="DB blip"):
        await ttl_cleanup._run_once()
