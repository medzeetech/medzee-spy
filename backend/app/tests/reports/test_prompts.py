"""Tests for ``app.modules.reports.prompts`` (F3 T20).

Covers:

* :func:`get_system_prompt` per-segment behavior (saude / odonto / outro
  fallback for unknown segments).
* :func:`build_user_prompt` deterministic rendering of metrics + sampled
  conversations.
* :data:`LLM_TOOL_SCHEMA` minimal shape sanity + JSON-serializability.
* :data:`PROMPT_VERSION` versioning convention (semver-ish ``vX.Y.Z``).
"""
from __future__ import annotations

import json

from app.modules.reports.prompts import (
    LLM_TOOL_SCHEMA,
    PROMPT_VERSION,
    build_user_prompt,
    get_system_prompt,
)


# ─── get_system_prompt ────────────────────────────────────────────────


def test_get_system_prompt_saude_includes_addendum():
    """The 'saude' segment addendum mentions the SAÚDE specialty marker."""
    prompt = get_system_prompt("saude")
    assert "SAÚDE" in prompt


def test_get_system_prompt_odonto_includes_addendum():
    """The 'odonto' segment addendum mentions ODONTOLOGIA."""
    prompt = get_system_prompt("odonto")
    assert "ODONTOLOGIA" in prompt


def test_get_system_prompt_unknown_falls_back_outro():
    """Unknown segments fall back to the 'outro' addendum text."""
    prompt = get_system_prompt("foobar")
    # Marker fragment from prompts/outro.py.
    assert "NÃO CLASSIFICADA" in prompt


# ─── build_user_prompt ───────────────────────────────────────────────


def test_build_user_prompt_includes_metrics_and_conversations():
    """All scalar metrics + at least one conversation message text are rendered."""
    convs = [
        {
            "wa_chatid": "5511900000001@s.whatsapp.net",
            "messages": [
                {
                    "ts": 1_700_000_000,
                    "from_me": False,
                    "text": "Oi, gostaria de saber o valor da consulta.",
                },
                {
                    "ts": 1_700_000_600,
                    "from_me": True,
                    "text": "Claro! A consulta de avaliação custa R$ 250.",
                },
            ],
        },
    ]
    prompt = build_user_prompt(
        clinic_segment="saude",
        metrics_snapshot={
            "message_count": 42,
            "conversation_count": 5,
            "score": 78,
            "funnel": [],
        },
        sampled_conversations=convs,
    )
    # Scalar metrics must appear in the rendered block.
    assert "42" in prompt
    assert "5" in prompt
    assert "78" in prompt
    # At least one sampled-conversation message must surface.
    assert (
        "valor da consulta" in prompt
        or "R$ 250" in prompt
    )


# ─── LLM_TOOL_SCHEMA ─────────────────────────────────────────────────


def test_llm_tool_schema_is_valid_jsonschema_shape():
    """Top-level shape sanity + JSON-serializability.

    The schema feeds Anthropic's ``input_schema`` and must therefore be a
    plain object with the standard top-level keys, and must round-trip through
    ``json.dumps`` without TypeError.
    """
    assert LLM_TOOL_SCHEMA["type"] == "object"
    assert "required" in LLM_TOOL_SCHEMA
    assert isinstance(LLM_TOOL_SCHEMA["required"], list)
    assert "properties" in LLM_TOOL_SCHEMA
    assert isinstance(LLM_TOOL_SCHEMA["properties"], dict)
    # Must be JSON-serializable (no tuples / sets / pydantic models in there).
    json.dumps(LLM_TOOL_SCHEMA)


# ─── PROMPT_VERSION ──────────────────────────────────────────────────


def test_prompt_version_is_semver_string():
    """``vMAJOR.MINOR.PATCH`` shape — bump on every meaningful prompt change."""
    assert isinstance(PROMPT_VERSION, str)
    assert PROMPT_VERSION.startswith("v")
    # Two dots between the three numeric components.
    assert PROMPT_VERSION.count(".") == 2
