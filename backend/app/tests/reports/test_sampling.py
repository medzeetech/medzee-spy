"""Unit tests for :mod:`app.modules.reports.sampling` (F3 T19).

The sampler is a pure function over an ``ExtractedPayload`` whose job is
to package the most diagnostic 1:1 conversations under a character
budget that maps to ~50k tokens of PT-BR. The properties exercised here:

* Group chats are dropped (signal-to-noise too low for personality reads).
* Conversations are visited top-volume first (richer = more diagnostic).
* The greedy packer respects the budget — but always returns at least
  one conversation if any qualifies (defensive fallback).
* Single conversations longer than head+tail (10 + 20) are truncated.
"""
from __future__ import annotations

from app.modules.reports.sampling import (
    _KEEP_HEAD,
    _KEEP_TAIL,
    _MAX_CONVERSATION_CHARS,
    sample_conversations,
)
from app.modules.whatsapp.schemas import (
    ConversationPayload,
    ExtractedPayload,
    MessagePayload,
)


def _msg(*, ts: int = 0, from_me: bool = False, text: str = "msg") -> MessagePayload:
    return MessagePayload(ts=ts, from_me=from_me, type="text", text=text)


def _conv(
    *,
    wa_chatid: str,
    messages: list[MessagePayload],
    is_group: bool = False,
    contact_name: str | None = None,
) -> ConversationPayload:
    return ConversationPayload(
        wa_chatid=wa_chatid,
        contact_name=contact_name or wa_chatid,
        is_group=is_group,
        last_message_at=messages[-1].ts if messages else None,
        messages=messages,
    )


def _payload(conversations: list[ConversationPayload]) -> ExtractedPayload:
    return ExtractedPayload(
        message_count=sum(len(c.messages) for c in conversations),
        conversation_count=len(conversations),
        conversations=conversations,
        partial=False,
    )


# ─── Filter / ordering ───────────────────────────────────────────────


def test_sample_excludes_groups(sample_extracted_payload) -> None:
    """Conversations with ``is_group=True`` are removed from the sample."""
    payload = sample_extracted_payload(
        message_count=60, conversation_count=10, with_groups=True
    )
    # Pre-condition: factory actually injected some groups.
    assert any(c.is_group for c in payload.conversations)

    sampled = sample_conversations(payload)
    assert all(not c.is_group for c in sampled)


def test_sample_orders_by_volume_desc() -> None:
    """Conversations are returned biggest-first (descending message count)."""
    convs = [
        _conv(
            wa_chatid="small@s.whatsapp.net",
            messages=[_msg(text="x")] * 2,
        ),
        _conv(
            wa_chatid="huge@s.whatsapp.net",
            messages=[_msg(text="x")] * 10,
        ),
        _conv(
            wa_chatid="mid@s.whatsapp.net",
            messages=[_msg(text="x")] * 5,
        ),
    ]
    sampled = sample_conversations(_payload(convs))

    assert [len(c.messages) for c in sampled] == [10, 5, 2]
    assert [c.wa_chatid for c in sampled] == [
        "huge@s.whatsapp.net",
        "mid@s.whatsapp.net",
        "small@s.whatsapp.net",
    ]


# ─── Budget ──────────────────────────────────────────────────────────


def test_sample_respects_budget_when_huge() -> None:
    """Greedy packer stops before crossing ``_MAX_CONVERSATION_CHARS``.

    Each conversation here contributes ~5_000 chars (5 messages × 1_000)
    so the cap should be exhausted somewhere between conv 30 and 31.
    The packer must not return all 50 conversations.
    """
    convs = [
        _conv(
            wa_chatid=f"big-{i}@s.whatsapp.net",
            messages=[_msg(text="a" * 1_000) for _ in range(5)],
        )
        for i in range(50)
    ]
    sampled = sample_conversations(_payload(convs))

    assert 0 < len(sampled) < len(convs)
    total_chars = sum(
        sum(len(m.text or "") for m in c.messages) for c in sampled
    )
    # After the last add we may sit a hair above the cap, but the loop
    # always declines the *next* would-be addition. Without a one-conv
    # overshoot the running total stays at or below the cap.
    assert total_chars <= _MAX_CONVERSATION_CHARS


def test_truncate_long_conversation() -> None:
    """A conversation with 50 messages collapses to 10 head + 20 tail = 30."""
    long_conv = _conv(
        wa_chatid="long@s.whatsapp.net",
        messages=[_msg(ts=i, text="msg") for i in range(50)],
    )
    sampled = sample_conversations(_payload([long_conv]))

    assert len(sampled) == 1
    assert len(sampled[0].messages) == _KEEP_HEAD + _KEEP_TAIL == 30
    # Head and tail preserved; middle dropped.
    assert [m.ts for m in sampled[0].messages[:_KEEP_HEAD]] == list(range(_KEEP_HEAD))
    assert [m.ts for m in sampled[0].messages[_KEEP_HEAD:]] == list(range(30, 50))


def test_short_conversation_passes_through() -> None:
    """Conversations under the head+tail threshold are returned unchanged."""
    short = _conv(
        wa_chatid="short@s.whatsapp.net",
        messages=[_msg(ts=i, text="msg") for i in range(5)],
    )
    sampled = sample_conversations(_payload([short]))

    assert len(sampled) == 1
    assert len(sampled[0].messages) == 5
    assert [m.ts for m in sampled[0].messages] == [0, 1, 2, 3, 4]


def test_always_returns_at_least_one() -> None:
    """Even a single oversize conversation comes back (defensive minimum)."""
    # Build 35 messages so truncation kicks in (10 head + 20 tail = 30) yet
    # the surviving 30 messages × 6_000 chars = 180_000 > 150_000 cap.
    huge = _conv(
        wa_chatid="huge-solo@s.whatsapp.net",
        messages=[_msg(ts=i, text="x" * 6_000) for i in range(35)],
    )
    sampled = sample_conversations(_payload([huge]))

    assert len(sampled) == 1
    assert len(sampled[0].messages) == _KEEP_HEAD + _KEEP_TAIL
    total_chars = sum(len(m.text or "") for m in sampled[0].messages)
    assert total_chars > _MAX_CONVERSATION_CHARS  # genuinely over budget


# ─── Edge cases ──────────────────────────────────────────────────────


def test_empty_payload_returns_empty_list() -> None:
    """No conversations → empty list, no crash."""
    payload = ExtractedPayload(
        message_count=0,
        conversation_count=0,
        conversations=[],
        partial=False,
    )
    assert sample_conversations(payload) == []


def test_all_groups_returns_empty() -> None:
    """If every conversation is a group, sampling yields nothing."""
    convs = [
        _conv(
            wa_chatid=f"55119000{i:04d}@g.us",
            messages=[_msg(text="oi"), _msg(text="oi")],
            is_group=True,
            contact_name=f"Grupo {i}",
        )
        for i in range(3)
    ]
    sampled = sample_conversations(_payload(convs))
    assert sampled == []
