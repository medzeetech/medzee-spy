"""Unit tests for ``app.modules.auth.repository`` (T11).

Mirrors the F1 repository tests: we don't care about ``asyncio.to_thread``,
just that each public function builds the right Supabase request chain
against the right schema/table.

Patch target note: ``repository.py`` does
``from app.clients.supabase import get_supabase_admin_client`` at import
time, so the name lives in the repository namespace. Patching the
*repository-local* reference is what guarantees the test mock is the one
actually called.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.modules.auth import repository


@pytest.fixture
def fake_supabase(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch the repository-local ``get_supabase_admin_client`` reference.

    Returns the root MagicMock so tests can inspect the
    ``client.schema(...).table(...).<verb>(...).execute()`` chain.
    """
    fake = MagicMock(name="supabase_admin_client")
    monkeypatch.setattr(
        "app.modules.auth.repository.get_supabase_admin_client",
        lambda: fake,
    )
    return fake


def _table_handle(fake: MagicMock) -> MagicMock:
    """Convenience: the ``schema('medzee_spy').table('users_profile')`` handle."""
    return fake.schema.return_value.table.return_value


def _last_verb_call(fake: MagicMock, verb: str):
    """Return the most recent ``.<verb>(...)`` call args on the table handle."""
    verb_handle = getattr(_table_handle(fake), verb)
    assert verb_handle.called, f"expected .{verb}(...) to have been called"
    return verb_handle.call_args


# --------------------------------------------------------------------------- #
# create_profile                                                              #
# --------------------------------------------------------------------------- #


async def test_create_profile_inserts_correct_payload(fake_supabase: MagicMock) -> None:
    """INSERT into medzee_spy.users_profile carries the full row payload,
    with ``user_id`` serialized to its string UUID form."""
    uid = uuid4()
    await repository.create_profile(
        uid,
        name="Dr X",
        email="x@y.com",
        phone="5511999999999",
        ticket_medio=250.0,
    )

    fake_supabase.schema.assert_called_with("medzee_spy")
    fake_supabase.schema.return_value.table.assert_called_with("users_profile")

    call = _last_verb_call(fake_supabase, "insert")
    (row,), _ = call
    assert row["user_id"] == str(uid)
    assert row["name"] == "Dr X"
    assert row["email"] == "x@y.com"
    assert row["phone"] == "5511999999999"
    assert row["ticket_medio"] == 250.0


# --------------------------------------------------------------------------- #
# get_profile                                                                 #
# --------------------------------------------------------------------------- #


async def test_get_profile_returns_first_row(fake_supabase: MagicMock) -> None:
    """``get_profile`` returns ``execute().data[0]`` when present."""
    uid = uuid4()
    row = {
        "user_id": str(uid),
        "name": "Dr X",
        "email": "x@y.com",
        "phone": "5511999999999",
        "ticket_medio": 250.0,
        "clinic_segment": None,
    }
    handle = _table_handle(fake_supabase)
    handle.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[row]
    )

    result = await repository.get_profile(uid)
    assert result == row

    # Sanity: select('*') was issued and the eq filter targets user_id.
    handle.select.assert_called_with("*")
    handle.select.return_value.eq.assert_called_with("user_id", str(uid))


async def test_get_profile_empty_returns_none(fake_supabase: MagicMock) -> None:
    """Empty ``data`` list → ``None``."""
    uid = uuid4()
    handle = _table_handle(fake_supabase)
    handle.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[]
    )

    assert await repository.get_profile(uid) is None


# --------------------------------------------------------------------------- #
# update_profile                                                              #
# --------------------------------------------------------------------------- #


async def test_update_profile_rejects_unknown_fields(fake_supabase: MagicMock) -> None:
    """Whitelist enforcement: ``email`` and ``user_id`` (the immutable PK)
    must be rejected before any Supabase call is made."""
    uid = uuid4()

    with pytest.raises(ValueError):
        await repository.update_profile(uid, email="other@x.com")

    # ``user_id`` is the positional arg name, so passing it as a kwarg would
    # collide before reaching the whitelist. Use another unsupported field
    # (``created_at``) for the second branch.
    with pytest.raises(ValueError):
        await repository.update_profile(uid, created_at="2026-01-01")

    # Reject happens upstream of any .update() call.
    _table_handle(fake_supabase).update.assert_not_called()


async def test_update_profile_empty_after_filtering_is_noop(
    fake_supabase: MagicMock,
) -> None:
    """All-``None`` payload → no Supabase ``.update()`` call (caller may pass
    a model_dump where every field is unset)."""
    uid = uuid4()
    await repository.update_profile(uid, name=None, phone=None)

    _table_handle(fake_supabase).update.assert_not_called()


# --------------------------------------------------------------------------- #
# delete_profile                                                              #
# --------------------------------------------------------------------------- #


async def test_delete_profile_calls_eq_user_id(fake_supabase: MagicMock) -> None:
    """``delete_profile`` issues ``.delete().eq('user_id', str(uid)).execute()``."""
    uid = uuid4()
    await repository.delete_profile(uid)

    handle = _table_handle(fake_supabase)
    handle.delete.assert_called_once_with()
    handle.delete.return_value.eq.assert_called_once_with("user_id", str(uid))
    handle.delete.return_value.eq.return_value.execute.assert_called_once_with()
