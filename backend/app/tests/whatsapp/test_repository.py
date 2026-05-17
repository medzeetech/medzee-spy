"""Unit tests for the WhatsApp repository (T5).

The repository wraps every blocking Supabase call in ``asyncio.to_thread`` —
we don't care about that here; we just verify each public function builds
the correct ``insert(...)`` / ``update(...)`` / ``select(...)`` payload and
targets the right schema/table.

Patch target note: ``repository.py`` does
``from app.clients.supabase import get_supabase_admin_client`` at import
time, so the name lives in the repository namespace. The conftest's
``fake_admin_supabase`` patches the *source* module, which is enough for
*new* imports but **not** for the already-bound name in ``repository``.
To make the assertion work, each test re-patches the local reference.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.modules.whatsapp import repository


@pytest.fixture
def fake_supabase(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch the repository-local ``get_supabase_admin_client`` reference.

    Returns the root MagicMock so tests can inspect the
    ``client.schema(...).table(...).<verb>(...).execute()`` chain.
    """
    fake = MagicMock(name="supabase_admin_client")
    monkeypatch.setattr(
        "app.modules.whatsapp.repository.get_supabase_admin_client",
        lambda: fake,
    )
    return fake


def _last_verb_call(fake: MagicMock, verb: str):
    """Return the most recent ``.schema('medzee_spy').table(...).<verb>(...)``
    call args on the fake supabase client.
    """
    table_handle = fake.schema.return_value.table.return_value
    verb_handle = getattr(table_handle, verb)
    assert verb_handle.called, f"expected .{verb}(...) to have been called"
    return verb_handle.call_args


# --------------------------------------------------------------------------- #
# create                                                                       #
# --------------------------------------------------------------------------- #


async def test_create_inserts_correct_payload(fake_supabase: MagicMock) -> None:
    """``create`` issues an INSERT against medzee_spy.whatsapp_sessions with
    id/uazapi_token/status. ``message_count`` defaults via DB column."""
    sid = uuid4()
    await repository.create(sid, uazapi_token="tok_abc", status="pending")

    fake_supabase.schema.assert_called_with("medzee_spy")
    fake_supabase.schema.return_value.table.assert_called_with("whatsapp_sessions")

    call = _last_verb_call(fake_supabase, "insert")
    (row,), _ = call
    assert row["id"] == str(sid)
    assert row["uazapi_token"] == "tok_abc"
    assert row["status"] == "pending"


# --------------------------------------------------------------------------- #
# mark_extracted                                                              #
# --------------------------------------------------------------------------- #


async def test_mark_extracted_sets_status_and_count(
    fake_supabase: MagicMock,
) -> None:
    """``mark_extracted`` sets status='extracted', message_count, and
    extracted_at (ISO-8601 string)."""
    sid = uuid4()
    await repository.mark_extracted(sid, message_count=42)

    call = _last_verb_call(fake_supabase, "update")
    (payload,), _ = call
    assert payload["status"] == "extracted"
    assert payload["message_count"] == 42
    assert "extracted_at" in payload
    # ISO 8601 — must parse via fromisoformat without raising.
    from datetime import datetime as _dt
    _dt.fromisoformat(payload["extracted_at"])


# --------------------------------------------------------------------------- #
# mark_failed                                                                  #
# --------------------------------------------------------------------------- #


async def test_mark_failed_sets_status_and_failed_code(
    fake_supabase: MagicMock,
) -> None:
    sid = uuid4()
    await repository.mark_failed(sid, "banned")

    call = _last_verb_call(fake_supabase, "update")
    (payload,), _ = call
    assert payload["status"] == "failed"
    assert payload["failed_code"] == "banned"


# --------------------------------------------------------------------------- #
# mark_consumed                                                               #
# --------------------------------------------------------------------------- #


async def test_mark_consumed_sets_status(fake_supabase: MagicMock) -> None:
    sid = uuid4()
    await repository.mark_consumed(sid)

    call = _last_verb_call(fake_supabase, "update")
    (payload,), _ = call
    assert payload == {"status": "consumed"}


# --------------------------------------------------------------------------- #
# link_user                                                                   #
# --------------------------------------------------------------------------- #


async def test_link_user_sets_user_id(fake_supabase: MagicMock) -> None:
    """``link_user`` attaches the freshly-signed-up user to the anon row."""
    sid = uuid4()
    uid = uuid4()
    await repository.link_user(sid, uid)

    call = _last_verb_call(fake_supabase, "update")
    (payload,), _ = call
    assert payload == {"user_id": str(uid)}


# --------------------------------------------------------------------------- #
# get                                                                          #
# --------------------------------------------------------------------------- #


async def test_get_returns_first_row(fake_supabase: MagicMock) -> None:
    """``get`` returns the first row of ``execute().data`` when present."""
    sid = uuid4()

    # supabase-py builder is select(...).eq(...).limit(...).execute().
    table_handle = fake_supabase.schema.return_value.table.return_value
    table_handle.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": str(sid), "status": "connected"}]
    )

    row = await repository.get(sid)
    assert row == {"id": str(sid), "status": "connected"}

    # Sanity: select('*') was issued.
    table_handle.select.assert_called_with("*")


async def test_get_returns_none_when_empty(fake_supabase: MagicMock) -> None:
    """Empty ``data`` list → ``None``."""
    sid = uuid4()

    table_handle = fake_supabase.schema.return_value.table.return_value
    table_handle.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[]
    )

    row = await repository.get(sid)
    assert row is None
