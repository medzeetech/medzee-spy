"""Unit tests for the reports repository (T21 of F3).

The repository wraps every blocking supabase-py call in ``asyncio.to_thread``
— we don't care about that here; we just verify each public function builds
the correct ``.insert(...)`` / ``.update(...).eq(...)`` / ``.select(...)``
chain against ``medzee_spy.reports``.

Patch target note: ``repository.py`` does
``from app.clients.supabase import get_supabase_admin_client`` at import
time, so the bound name lives in the repository namespace — we monkeypatch
``app.modules.reports.repository.get_supabase_admin_client`` directly
(MagicMock auto-vivifies the rest of the chain).
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.modules.reports import repository


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


@pytest.fixture
def fake_supabase(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch the repository-local ``get_supabase_admin_client`` reference.

    Returns the root MagicMock so tests can inspect the
    ``client.schema(...).table(...).<verb>(...)....execute()`` chain.
    """
    fake = MagicMock(name="supabase_admin_client")
    monkeypatch.setattr(
        "app.modules.reports.repository.get_supabase_admin_client",
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
# create_generating                                                            #
# --------------------------------------------------------------------------- #


async def test_create_generating_inserts_row_with_status(
    fake_supabase: MagicMock,
) -> None:
    """``create_generating`` issues an INSERT against medzee_spy.reports with
    status='generating', whatsapp_session_id, user_id, and clinic_segment.
    """
    sid = uuid4()
    uid = uuid4()
    new_id = uuid4()

    table_handle = fake_supabase.schema.return_value.table.return_value
    table_handle.insert.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": str(new_id)}]
    )

    returned = await repository.create_generating(
        whatsapp_session_id=sid,
        user_id=uid,
        clinic_segment="odonto",
    )

    fake_supabase.schema.assert_called_with("medzee_spy")
    fake_supabase.schema.return_value.table.assert_called_with("reports")

    (row,), _ = _last_verb_call(fake_supabase, "insert")
    assert row["status"] == "generating"
    assert row["whatsapp_session_id"] == str(sid)
    assert row["user_id"] == str(uid)
    assert row["clinic_segment"] == "odonto"
    assert returned == new_id


async def test_create_generating_allows_null_user_id(
    fake_supabase: MagicMock,
) -> None:
    """``user_id=None`` is legal pre-signup — the column must be stored as
    JSON ``null``, not the string 'None'.
    """
    sid = uuid4()
    new_id = uuid4()

    table_handle = fake_supabase.schema.return_value.table.return_value
    table_handle.insert.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": str(new_id)}]
    )

    await repository.create_generating(
        whatsapp_session_id=sid,
        user_id=None,
        clinic_segment="saude",
    )

    (row,), _ = _last_verb_call(fake_supabase, "insert")
    assert row["user_id"] is None
    assert row["clinic_segment"] == "saude"


# --------------------------------------------------------------------------- #
# update_completed                                                             #
# --------------------------------------------------------------------------- #


async def test_update_completed_sets_payload_and_generated_at(
    fake_supabase: MagicMock,
) -> None:
    """``update_completed`` writes status='completed', payload, model,
    prompt_version, message_count, score, and an ISO-formatted generated_at.
    """
    rid = uuid4()
    payload = {"diagnostic_summary": "ok", "score": 72}

    await repository.update_completed(
        rid,
        payload=payload,
        model="claude-3-5-sonnet",
        prompt_version="v1",
        message_count=842,
        score=72,
    )

    (sent,), _ = _last_verb_call(fake_supabase, "update")
    assert sent["status"] == "completed"
    assert sent["payload"] == payload
    assert sent["model"] == "claude-3-5-sonnet"
    assert sent["prompt_version"] == "v1"
    assert sent["message_count"] == 842
    assert sent["score"] == 72
    assert "generated_at" in sent
    # ISO 8601 — must parse via fromisoformat without raising.
    datetime.fromisoformat(sent["generated_at"])

    # WHERE id = <rid>
    table_handle = fake_supabase.schema.return_value.table.return_value
    table_handle.update.return_value.eq.assert_called_with("id", str(rid))


# --------------------------------------------------------------------------- #
# update_failed                                                                #
# --------------------------------------------------------------------------- #


async def test_update_failed_no_payload(fake_supabase: MagicMock) -> None:
    """``update_failed`` writes status='failed' + error_code; payload is
    intentionally NOT touched (we keep any prior partial generation for
    debugging).
    """
    rid = uuid4()

    await repository.update_failed(rid, error_code="llm_timeout")

    (sent,), _ = _last_verb_call(fake_supabase, "update")
    assert sent["status"] == "failed"
    assert sent["error_code"] == "llm_timeout"
    assert "payload" not in sent
    assert "model" not in sent
    assert "generated_at" not in sent


# --------------------------------------------------------------------------- #
# link_user                                                                    #
# --------------------------------------------------------------------------- #


async def test_link_user_updates_only_when_null(fake_supabase: MagicMock) -> None:
    """``link_user`` builds .update({'user_id': uid}).eq(whatsapp_session_id)
    .is_('user_id', 'null') so we never overwrite an existing link.
    """
    sid = uuid4()
    uid = uuid4()

    table_handle = fake_supabase.schema.return_value.table.return_value
    # The chain returns 1 affected row.
    (
        table_handle
        .update.return_value
        .eq.return_value
        .is_.return_value
        .execute.return_value
    ) = SimpleNamespace(data=[{"id": "row-1"}])

    affected = await repository.link_user(sid, uid)

    (sent,), _ = _last_verb_call(fake_supabase, "update")
    assert sent == {"user_id": str(uid)}

    table_handle.update.return_value.eq.assert_called_with(
        "whatsapp_session_id", str(sid)
    )
    # The repository uses .is_('user_id', 'null') (supabase-py 2.x style).
    table_handle.update.return_value.eq.return_value.is_.assert_called_with(
        "user_id", "null"
    )
    assert affected == 1


# --------------------------------------------------------------------------- #
# get_by_id                                                                    #
# --------------------------------------------------------------------------- #


async def test_get_by_id_filters_by_user_id(fake_supabase: MagicMock) -> None:
    """When the report exists but is owned by another user, the .eq('user_id')
    filter yields data=[] → function returns None (REPORT-17 defense-in-depth).
    """
    rid = uuid4()
    uid = uuid4()

    table_handle = fake_supabase.schema.return_value.table.return_value
    (
        table_handle
        .select.return_value
        .eq.return_value
        .eq.return_value
        .limit.return_value
        .execute.return_value
    ) = SimpleNamespace(data=[])

    result = await repository.get_by_id(rid, user_id=uid)

    assert result is None
    # Both eq filters were issued (id + user_id).
    select_handle = table_handle.select.return_value
    select_handle.eq.assert_called_with("id", str(rid))
    select_handle.eq.return_value.eq.assert_called_with("user_id", str(uid))


# --------------------------------------------------------------------------- #
# get_latest_for_user                                                          #
# --------------------------------------------------------------------------- #


async def test_get_latest_for_user_orders_desc_limit_1(
    fake_supabase: MagicMock,
) -> None:
    """``get_latest_for_user`` orders by created_at DESC and limits to 1."""
    uid = uuid4()

    table_handle = fake_supabase.schema.return_value.table.return_value
    row = {
        "id": str(uuid4()),
        "status": "completed",
        "created_at": "2025-01-01T00:00:00+00:00",
    }
    (
        table_handle
        .select.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ) = SimpleNamespace(data=[row])

    result = await repository.get_latest_for_user(uid)

    select_handle = table_handle.select.return_value
    select_handle.eq.assert_called_with("user_id", str(uid))
    select_handle.eq.return_value.order.assert_called_with("created_at", desc=True)
    select_handle.eq.return_value.order.return_value.limit.assert_called_with(1)
    assert result == row


# --------------------------------------------------------------------------- #
# list_for_user                                                                #
# --------------------------------------------------------------------------- #


async def test_list_for_user_pagination(fake_supabase: MagicMock) -> None:
    """page=2, page_size=10 → .range(10, 19); ``count`` is forwarded back."""
    uid = uuid4()
    rows = [
        {"id": str(uuid4()), "status": "completed", "created_at": "2025-01-02T00:00:00+00:00"},
        {"id": str(uuid4()), "status": "completed", "created_at": "2025-01-01T00:00:00+00:00"},
    ]

    table_handle = fake_supabase.schema.return_value.table.return_value
    (
        table_handle
        .select.return_value
        .eq.return_value
        .order.return_value
        .range.return_value
        .execute.return_value
    ) = SimpleNamespace(data=rows, count=42)

    out_rows, total = await repository.list_for_user(uid, page=2, page_size=10)

    select_handle = table_handle.select.return_value
    # select('*', count='exact') is what enables result.count.
    table_handle.select.assert_called_with("*", count="exact")
    select_handle.eq.assert_called_with("user_id", str(uid))
    select_handle.eq.return_value.order.return_value.range.assert_called_with(10, 19)
    assert out_rows == rows
    assert total == 42
