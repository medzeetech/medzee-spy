"""Conversation sampling for the report-processing pipeline.

Keeps LLM input bounded by:
  1. Filtering out groups (signal-to-noise too low for 1:1 personality reads).
  2. Sorting by message volume (richer conversations are more diagnostic).
  3. Greedily packing conversations under a character budget that maps to
     roughly 50k tokens of PT-BR (~3.5 chars/token).
  4. Truncating any single conversation to its first 10 + last 20 messages so
     a hyper-active chat cannot crowd out variety.

Pure functions: no I/O, no logging. T19 owns the tests.
"""
from __future__ import annotations

from app.modules.whatsapp.schemas import (
    ConversationPayload,
    ExtractedPayload,
    MessagePayload,
)

_MAX_CONVERSATION_CHARS = 150_000  # ~50k tokens of conversation budget (PT-BR ~3.5 chars/token)
_KEEP_HEAD = 10
_KEEP_TAIL = 20


def sample_conversations(payload: ExtractedPayload) -> list[ConversationPayload]:
    """Sample conversations to fit within the LLM input budget.

    Strategy:
      1. Filter out groups (is_group=True).
      2. Sort by message count descending (top-volume first).
      3. Greedy: accumulate conversations until adding the next would exceed
         _MAX_CONVERSATION_CHARS. Always include at least one (defensive).
      4. For any single conversation longer than _KEEP_HEAD + _KEEP_TAIL,
         truncate to keep the first 10 + last 20 messages.
    """
    one_to_one: list[ConversationPayload] = [
        c for c in payload.conversations if not c.is_group
    ]
    if not one_to_one:
        return []

    one_to_one.sort(key=lambda c: len(c.messages), reverse=True)

    selected: list[ConversationPayload] = []
    running_chars = 0
    for conv in one_to_one:
        truncated = _truncate_if_needed(conv)
        conv_chars = _estimate_chars(truncated)
        if selected and running_chars + conv_chars > _MAX_CONVERSATION_CHARS:
            break
        selected.append(truncated)
        running_chars += conv_chars

    return selected


def _estimate_chars(conv: ConversationPayload) -> int:
    """Sum of len(m.text or '') across messages."""
    return sum(len(m.text or "") for m in conv.messages)


def _truncate_if_needed(conv: ConversationPayload) -> ConversationPayload:
    """Keep first _KEEP_HEAD + last _KEEP_TAIL messages if conv is longer."""
    messages: list[MessagePayload] = conv.messages
    if len(messages) <= _KEEP_HEAD + _KEEP_TAIL:
        return conv
    head = messages[:_KEEP_HEAD]
    tail = messages[-_KEEP_TAIL:]
    return conv.model_copy(update={"messages": head + tail})
