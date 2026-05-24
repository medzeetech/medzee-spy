"""Unit tests for ``app.modules.reports.service._build_extracted_payload`` (T17 of F4).

The helper is a pure function that translates a list of ``CapturedMessage``
rows into the F3 ``ExtractedPayload`` shape consumed by the report worker.
It must:

* group messages by ``wa_chatid``
* sort messages chronologically within each conversation
* infer ``is_group`` from the JID suffix (``@g.us``)
* preserve the **first** ``contact_name`` seen for each chat (NOT the
  first non-None — see ``_build_extracted_payload`` source)
* coerce ``text=None`` to ``""``
* report ``last_message_at`` as the **unix int** max(ts) per chat

These tests only construct ``CapturedMessage`` instances and call the
helper directly — no Supabase, no asyncio.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.modules.captured_messages.schemas import CapturedMessage
from app.modules.reports.schemas import ExtractedPayload
from app.modules.reports.service import _build_extracted_payload


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


_UID = uuid4()
_SID = uuid4()


def _msg(
    *,
    wa_chatid: str,
    ts: datetime,
    is_from_me: bool = False,
    text: str | None = "oi",
    contact_name: str | None = "Paciente",
    message_type: str = "text",
) -> CapturedMessage:
    return CapturedMessage(
        id=uuid4(),
        user_id=_UID,
        whatsapp_session_id=_SID,
        wa_chatid=wa_chatid,
        contact_name=contact_name,
        ts=ts,
        is_from_me=is_from_me,
        message_type=message_type,
        text=text,
        raw_message_id=uuid4().hex,
        created_at=ts,
    )


_BASE = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #


def test_build_groups_by_wa_chatid() -> None:
    """5 messages across 2 distinct ``wa_chatid`` → 2 ConversationPayload
    entries, message_count=5, conversation_count=2.
    """
    chat_a = "5511900000001@s.whatsapp.net"
    chat_b = "5511900000002@s.whatsapp.net"
    captured = [
        _msg(wa_chatid=chat_a, ts=_BASE + timedelta(minutes=0)),
        _msg(wa_chatid=chat_b, ts=_BASE + timedelta(minutes=1)),
        _msg(wa_chatid=chat_a, ts=_BASE + timedelta(minutes=2)),
        _msg(wa_chatid=chat_b, ts=_BASE + timedelta(minutes=3)),
        _msg(wa_chatid=chat_a, ts=_BASE + timedelta(minutes=4)),
    ]

    payload = _build_extracted_payload(captured)

    assert isinstance(payload, ExtractedPayload)
    assert payload.message_count == 5
    assert payload.conversation_count == 2
    assert {c.wa_chatid for c in payload.conversations} == {chat_a, chat_b}
    assert payload.partial is False

    # Per-chat counts: chat_a has 3, chat_b has 2.
    by_id = {c.wa_chatid: c for c in payload.conversations}
    assert len(by_id[chat_a].messages) == 3
    assert len(by_id[chat_b].messages) == 2


def test_build_preserves_order_within_chat() -> None:
    """Messages inside each ConversationPayload are sorted ascending by ts,
    regardless of input order.
    """
    chat = "5511@s.whatsapp.net"
    captured = [
        _msg(wa_chatid=chat, ts=_BASE + timedelta(minutes=30)),
        _msg(wa_chatid=chat, ts=_BASE + timedelta(minutes=5)),
        _msg(wa_chatid=chat, ts=_BASE + timedelta(minutes=20)),
        _msg(wa_chatid=chat, ts=_BASE + timedelta(minutes=1)),
    ]

    payload = _build_extracted_payload(captured)

    conv = payload.conversations[0]
    tss = [m.ts for m in conv.messages]
    assert tss == sorted(tss)
    # First message is the earliest (1 minute after base).
    assert tss[0] == int((_BASE + timedelta(minutes=1)).timestamp())


def test_build_marks_is_group_true_for_g_us_suffix() -> None:
    """JID ending in ``@g.us`` → ``is_group=True``; ``@s.whatsapp.net`` →
    ``is_group=False``.
    """
    group_jid = "120363012345678901@g.us"
    individual_jid = "5511900000001@s.whatsapp.net"
    captured = [
        _msg(wa_chatid=group_jid, ts=_BASE),
        _msg(wa_chatid=individual_jid, ts=_BASE),
    ]

    payload = _build_extracted_payload(captured)
    by_id = {c.wa_chatid: c for c in payload.conversations}

    assert by_id[group_jid].is_group is True
    assert by_id[individual_jid].is_group is False


def test_build_picks_contact_name_first_occurrence() -> None:
    """The helper keeps the **first** ``contact_name`` it sees for each
    chat (`if m.wa_chatid not in contact_names`). If the first occurrence
    is None, that stays — subsequent updates do NOT overwrite.

    Inputs are passed in order: [contact_name='Maria', None, 'Maria Updated']
    → first occurrence is 'Maria', so output uses 'Maria'.
    """
    chat = "5511@s.whatsapp.net"
    captured = [
        _msg(wa_chatid=chat, ts=_BASE + timedelta(minutes=0), contact_name="Maria"),
        _msg(wa_chatid=chat, ts=_BASE + timedelta(minutes=1), contact_name=None),
        _msg(
            wa_chatid=chat,
            ts=_BASE + timedelta(minutes=2),
            contact_name="Maria Updated",
        ),
    ]

    payload = _build_extracted_payload(captured)
    assert payload.conversations[0].contact_name == "Maria"


def test_build_empty_captured_returns_empty_payload() -> None:
    """Empty input → empty ExtractedPayload (worker tolerates this)."""
    payload = _build_extracted_payload([])

    assert payload.message_count == 0
    assert payload.conversation_count == 0
    assert payload.conversations == []
    assert payload.partial is False


def test_build_last_message_at_is_max_ts_per_chat() -> None:
    """``last_message_at`` is the unix-int max of all message ts in the chat
    (irrespective of input ordering).
    """
    chat = "5511@s.whatsapp.net"
    early = _BASE
    middle = _BASE + timedelta(hours=2)
    latest = _BASE + timedelta(days=1)
    captured = [
        _msg(wa_chatid=chat, ts=middle),
        _msg(wa_chatid=chat, ts=latest),
        _msg(wa_chatid=chat, ts=early),
    ]

    payload = _build_extracted_payload(captured)
    conv = payload.conversations[0]

    assert conv.last_message_at == int(latest.timestamp())


def test_build_handles_none_text_as_empty_string() -> None:
    """A captured row with ``text=None`` (e.g. raw 'sticker' message) is
    forwarded with ``text=""`` so the F3 ``MessagePayload`` (text: str)
    validates.
    """
    chat = "5511@s.whatsapp.net"
    captured = [
        _msg(wa_chatid=chat, ts=_BASE, text=None, message_type="sticker"),
        _msg(wa_chatid=chat, ts=_BASE + timedelta(minutes=1), text="oi"),
    ]

    payload = _build_extracted_payload(captured)
    msgs = payload.conversations[0].messages

    assert msgs[0].text == ""
    assert msgs[0].type == "sticker"
    assert msgs[1].text == "oi"


def test_build_message_payload_carries_from_me_and_type() -> None:
    """Each MessagePayload faithfully forwards ``is_from_me`` → ``from_me``
    and ``message_type`` → ``type``.
    """
    chat = "5511@s.whatsapp.net"
    captured = [
        _msg(
            wa_chatid=chat,
            ts=_BASE,
            is_from_me=False,
            message_type="text",
            text="pergunta",
        ),
        _msg(
            wa_chatid=chat,
            ts=_BASE + timedelta(minutes=1),
            is_from_me=True,
            message_type="audio",
            text="resposta em audio",
        ),
    ]

    payload = _build_extracted_payload(captured)
    m0, m1 = payload.conversations[0].messages

    assert m0.from_me is False
    assert m0.type == "text"
    assert m1.from_me is True
    assert m1.type == "audio"
