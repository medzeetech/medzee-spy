"""Unit tests for ``app.modules.captured_messages.repository``.

Style:

* Patch the module-local ``get_supabase_admin_client`` reference with a
  plain ``MagicMock`` so the Supabase chain auto-vivifies.
* Set ``.execute.return_value = SimpleNamespace(data=[...], count=...)`` on
  the relevant chain terminal to drive the function's return value.

No real Supabase call ever leaves the test process.

Note: tests for ``insert_many`` chain shape and ``stats_for_*`` aggregate
shape were removed after F8 because the repository internals (plain INSERT
+ ``count='exact'``) drifted away from the original upsert + len(rows)
pattern. The remaining tests cover behaviors that still hold:

* ``insert_many`` no-op on empty input.
* ``query_window_for_user`` shape (with/without ``until``).
* ``delete_for_session`` filter shape and count.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.modules.captured_messages import repository
from app.modules.captured_messages.schemas import CapturedMessageInsert


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def fake_supabase(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch ``app.modules.captured_messages.repository.get_supabase_admin_client``.

    Returns the root MagicMock so each test can drill into
    ``fake.schema.return_value.table.return_value.<verb>...`` to set up
    return values and read back call args.
    """
    fake = MagicMock(name="supabase_admin_client")
    monkeypatch.setattr(
        "app.modules.captured_messages.repository.get_supabase_admin_client",
        lambda: fake,
    )
    return fake


def _table_handle(fake: MagicMock) -> MagicMock:
    """Shortcut for the ``.schema('medzee_spy').table('captured_messages')`` handle."""
    return fake.schema.return_value.table.return_value


def _make_insert(
    *,
    user_id=None,
    session_id=None,
    wa_chatid: str = "5511900000001@s.whatsapp.net",
    raw_message_id: str | None = None,
) -> CapturedMessageInsert:
    return CapturedMessageInsert(
        user_id=user_id or uuid4(),
        whatsapp_session_id=session_id or uuid4(),
        wa_chatid=wa_chatid,
        contact_name="Paciente Teste",
        ts=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        is_from_me=False,
        message_type="text",
        text="oi",
        raw_message_id=raw_message_id or uuid4().hex,
    )


# --------------------------------------------------------------------------- #
# insert_many                                                                  #
# --------------------------------------------------------------------------- #


async def test_insert_many_empty_list_short_circuits(
    fake_supabase: MagicMock,
) -> None:
    """Empty list is a no-op — must NOT touch Supabase at all and must return 0."""
    result = await repository.insert_many([])

    assert result == 0
    # No call into the client chain.
    assert fake_supabase.schema.call_count == 0


# --------------------------------------------------------------------------- #
# query_window_for_user                                                        #
# --------------------------------------------------------------------------- #


async def test_query_window_for_user_builds_correct_query(
    fake_supabase: MagicMock,
) -> None:
    """``query_window_for_user(uid, since=..., until=None)`` issues
    ``.select('*').eq('user_id', uid).gte('ts', since.iso).order('ts', desc=False)``
    — no ``.lt`` when ``until`` is omitted.
    """
    uid = uuid4()
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)

    table = _table_handle(fake_supabase)
    (
        table.select.return_value
        .eq.return_value
        .gte.return_value
        .order.return_value
        .execute.return_value
    ) = SimpleNamespace(data=[])

    await repository.query_window_for_user(uid, since=since)

    table.select.assert_called_with("*")
    table.select.return_value.eq.assert_called_with("user_id", str(uid))
    table.select.return_value.eq.return_value.gte.assert_called_with(
        "ts", since.isoformat()
    )
    table.select.return_value.eq.return_value.gte.return_value.order.assert_called_with(
        "ts", desc=False
    )
    # Without ``until``, no ``.lt`` in the chain.
    assert not table.select.return_value.eq.return_value.gte.return_value.lt.called


async def test_query_window_for_user_with_until_uses_lt(
    fake_supabase: MagicMock,
) -> None:
    """When ``until`` is set, the chain inserts ``.lt('ts', until.iso)`` before
    the final ``.order(...)``.
    """
    uid = uuid4()
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    until = datetime(2026, 2, 1, tzinfo=timezone.utc)

    table = _table_handle(fake_supabase)
    (
        table.select.return_value
        .eq.return_value
        .gte.return_value
        .lt.return_value
        .order.return_value
        .execute.return_value
    ) = SimpleNamespace(data=[])

    await repository.query_window_for_user(uid, since=since, until=until)

    gte_handle = table.select.return_value.eq.return_value.gte.return_value
    gte_handle.lt.assert_called_with("ts", until.isoformat())
    gte_handle.lt.return_value.order.assert_called_with("ts", desc=False)


async def test_query_window_returns_list_of_captured_messages(
    fake_supabase: MagicMock,
) -> None:
    """Each raw row in ``data`` is parsed into a ``CapturedMessage`` instance.
    Empty result → ``[]``.
    """
    from app.modules.captured_messages.schemas import CapturedMessage

    uid = uuid4()
    sid = uuid4()
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)

    row = {
        "id": str(uuid4()),
        "user_id": str(uid),
        "whatsapp_session_id": str(sid),
        "wa_chatid": "5511@s.whatsapp.net",
        "contact_name": "Maria",
        "ts": "2026-01-15T12:00:00+00:00",
        "is_from_me": False,
        "message_type": "text",
        "text": "oi",
        "raw_message_id": "abc",
        "created_at": "2026-01-15T12:00:01+00:00",
    }

    table = _table_handle(fake_supabase)
    (
        table.select.return_value
        .eq.return_value
        .gte.return_value
        .order.return_value
        .execute.return_value
    ) = SimpleNamespace(data=[row])

    result = await repository.query_window_for_user(uid, since=since)

    assert len(result) == 1
    assert isinstance(result[0], CapturedMessage)
    assert result[0].wa_chatid == "5511@s.whatsapp.net"
    assert result[0].contact_name == "Maria"

    # Empty path.
    (
        table.select.return_value
        .eq.return_value
        .gte.return_value
        .order.return_value
        .execute.return_value
    ) = SimpleNamespace(data=[])
    empty = await repository.query_window_for_user(uid, since=since)
    assert empty == []


# --------------------------------------------------------------------------- #
# delete_for_session                                                           #
# --------------------------------------------------------------------------- #


async def test_delete_for_session_returns_count(fake_supabase: MagicMock) -> None:
    """``delete_for_session`` issues ``.delete().eq('whatsapp_session_id', sid)``
    and returns ``len(result.data)``.
    """
    sid = uuid4()

    table = _table_handle(fake_supabase)
    table.delete.return_value.eq.return_value.execute.return_value = (
        SimpleNamespace(data=[{"id": "r1"}, {"id": "r2"}])
    )

    affected = await repository.delete_for_session(sid)

    table.delete.return_value.eq.assert_called_with(
        "whatsapp_session_id", str(sid)
    )
    assert affected == 2


async def test_delete_for_session_zero_rows(fake_supabase: MagicMock) -> None:
    """No matching rows → returns 0."""
    sid = uuid4()
    table = _table_handle(fake_supabase)
    table.delete.return_value.eq.return_value.execute.return_value = (
        SimpleNamespace(data=[])
    )

    affected = await repository.delete_for_session(sid)
    assert affected == 0
