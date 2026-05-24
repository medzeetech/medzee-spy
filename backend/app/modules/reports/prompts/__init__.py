"""Prompts subpackage — system/user templates + tool JSON Schema for F3 T7.

Public surface:

* :data:`BASE_SYSTEM` is internal; consumers should call
  :func:`get_system_prompt` so the per-segment addendum is appended.
* :func:`get_system_prompt` — segment-aware system prompt.
* :func:`build_user_prompt` — deterministic user-role message that bundles
  hard metrics + sampled conversations.
* :data:`LLM_TOOL_SCHEMA` — JSON Schema for the Anthropic ``submit_report``
  tool (re-exported from ``schema``).
* :data:`PROMPT_VERSION` — bump on every meaningful prompt change so we can
  filter / re-run on stored reports.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone, timedelta
from typing import Any, Iterable

from app.modules.reports.prompts import odonto, outro, saude
from app.modules.reports.prompts.base import BASE_SYSTEM
from app.modules.reports.prompts.schema import LLM_TOOL_SCHEMA

__all__ = [
    "BASE_SYSTEM",
    "LLM_TOOL_SCHEMA",
    "PROMPT_VERSION",
    "build_user_prompt",
    "get_system_prompt",
]

PROMPT_VERSION = "v1.0.0"

# America/Sao_Paulo is UTC-3 year-round (Brazil dropped DST in 2019). Using a
# fixed offset keeps the build deterministic without dragging in zoneinfo /
# tzdata as a hard dep on Windows.
_SAO_PAULO_TZ = timezone(timedelta(hours=-3), name="America/Sao_Paulo")

_ADDENDUM_BY_SEGMENT: dict[str, str] = {
    "saude": saude.SEGMENT_ADDENDUM,
    "odonto": odonto.SEGMENT_ADDENDUM,
    "outro": outro.SEGMENT_ADDENDUM,
}


def get_system_prompt(clinic_segment: str) -> str:
    """Return BASE_SYSTEM + the per-segment addendum.

    Unknown segments fall back to ``outro`` so a typo never breaks generation.
    """
    addendum = _ADDENDUM_BY_SEGMENT.get(clinic_segment, _ADDENDUM_BY_SEGMENT["outro"])
    return BASE_SYSTEM + "\n\n" + addendum


def _tag_for_chatid(wa_chatid: str) -> str:
    """Stable P-XXXX tag derived from the wa_chatid via SHA-256.

    SHA-256 is used (instead of Python's hash()) so the tag stays stable across
    process restarts and PYTHONHASHSEED randomization.
    """
    digest = hashlib.sha256(wa_chatid.encode("utf-8")).hexdigest()
    return "P-" + str(int(digest[:8], 16) % 10000).zfill(4)


def _format_ts(ts: int) -> str:
    """Format a unix-seconds timestamp as ``YYYY-MM-DD HH:MM`` in America/Sao_Paulo."""
    return datetime.fromtimestamp(ts, tz=_SAO_PAULO_TZ).strftime("%Y-%m-%d %H:%M")


def _format_metrics_block(metrics: dict[str, Any]) -> str:
    """Render the ``## MÉTRICAS DURAS`` section.

    Top-level scalar / int / float / str fields are emitted as ``key: value``.
    The optional ``funnel`` field (list of {stage, count}) is rendered inline.
    Unknown / nested fields fall through to a ``key: <json>``-style line so we
    never silently drop info — but the common shape stays readable.
    """
    lines: list[str] = ["## MÉTRICAS DURAS (já calculadas, não recompute)"]

    funnel = metrics.get("funnel")
    flat_pairs: list[tuple[str, Any]] = []
    for key, value in metrics.items():
        if key == "funnel":
            continue
        flat_pairs.append((key, value))

    if flat_pairs:
        lines.append(
            " / ".join(f"{k}: {v}" for k, v in flat_pairs)
        )

    if isinstance(funnel, list) and funnel:
        funnel_parts: list[str] = []
        for stage in funnel:
            if isinstance(stage, dict) and "stage" in stage and "count" in stage:
                funnel_parts.append(f"{stage['stage']}={stage['count']}")
        if funnel_parts:
            lines.append("funnel: " + ", ".join(funnel_parts))

    return "\n".join(lines)


def _format_conversation(conversation: Any) -> str:
    """Render one ``### Conversa P-XXXX (N msgs)`` block.

    Accepts both a ``ConversationPayload`` instance and a plain dict (handy for
    tests / fixtures that bypass pydantic).
    """
    if isinstance(conversation, dict):
        wa_chatid = conversation.get("wa_chatid", "")
        messages: Iterable[Any] = conversation.get("messages") or []
    else:
        wa_chatid = getattr(conversation, "wa_chatid", "")
        messages = getattr(conversation, "messages", []) or []

    messages_list = list(messages)
    tag = _tag_for_chatid(wa_chatid)
    header = f"### Conversa {tag} ({len(messages_list)} msgs)"

    body_lines: list[str] = []
    for msg in messages_list:
        if isinstance(msg, dict):
            ts = msg.get("ts")
            from_me = bool(msg.get("from_me"))
            text = msg.get("text")
        else:
            ts = getattr(msg, "ts", None)
            from_me = bool(getattr(msg, "from_me", False))
            text = getattr(msg, "text", None)

        if ts is None or text is None or text == "":
            # Skip empty / non-text messages — the LLM can't infer intent from
            # a sticker, and including ``None`` would only burn tokens.
            continue

        speaker = "CLÍNICA" if from_me else "LEAD"
        body_lines.append(f"[{_format_ts(int(ts))}] {speaker}: {text}")

    if not body_lines:
        body_lines.append("(sem mensagens de texto)")

    return header + "\n" + "\n".join(body_lines)


def build_user_prompt(
    *,
    clinic_segment: str,  # noqa: ARG001 — accepted for API symmetry; segment guidance lives in system prompt
    metrics_snapshot: dict,
    sampled_conversations: list,  # list[ConversationPayload] or list[dict]
) -> str:
    """Build the user-role message with hard metrics + sampled conversations.

    Output is fully deterministic: input order is preserved (no sorting), tags
    are derived from ``wa_chatid`` via SHA-256, and timestamps are rendered in
    a fixed America/Sao_Paulo offset.

    Format::

        ## MÉTRICAS DURAS (já calculadas, não recompute)
        message_count: X / conversation_count: Y / response_rate: Z%
        funnel: stage1=A, stage2=B, ...

        ## CONVERSAS (top-volume + amostra)
        ### Conversa P-XXXX (N msgs)
        [YYYY-MM-DD HH:MM] LEAD: ...
        [YYYY-MM-DD HH:MM] CLÍNICA: ...
        ...
    """
    metrics_block = _format_metrics_block(metrics_snapshot)

    conversations_header = "## CONVERSAS (top-volume + amostra)"
    conversation_blocks = [_format_conversation(c) for c in sampled_conversations]

    if conversation_blocks:
        conversations_section = (
            conversations_header + "\n" + "\n\n".join(conversation_blocks)
        )
    else:
        conversations_section = conversations_header + "\n(sem conversas amostradas)"

    return metrics_block + "\n\n" + conversations_section
