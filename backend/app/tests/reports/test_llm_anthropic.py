"""Unit tests for ``app.clients.llm.AnthropicClient`` — F3 T22.

Mocks Anthropic's Messages API (``https://api.anthropic.com/v1/messages``) via
``respx`` so we can exercise the full request/response cycle of the adapter
without touching the network. Covers:

* Happy path — ``tool_use`` block extraction (returns the ``input`` dict).
* ``LLMInvalidResponse`` paths — missing ``tool_use`` block, wrong tool name.
* ``LLMUnavailable`` paths — 5xx, 429, timeout (all retryable by callers).
* ``LLMError`` path — 4xx ``Bad Request`` (NOT a subclass marker for retry).
* Request shape — verifies the body wires ``tool_choice`` to ``submit_report``
  with the caller-supplied ``input_schema`` (the coercion mechanism per
  design § 5 of F3).
"""
from __future__ import annotations

import json
from typing import Any, Iterator

import httpx
import pytest
import respx

from app.clients.llm import (
    AnthropicClient,
    LLMError,
    LLMInvalidResponse,
    LLMUnavailable,
)


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


SAMPLE_TOOL_INPUT: dict[str, Any] = {
    "diagnostic_summary": "Análise resumida.",
    "opportunities": [],
    "objections": [],
    "faqs": [],
    "sentiment": [
        {"name": "Positivo", "value": 40, "color": "#FF6B35"},
        {"name": "Neutro", "value": 40, "color": "#B8A8D9"},
        {"name": "Negativo", "value": 20, "color": "#5C1D2E"},
    ],
}


def _ok_response_body() -> dict[str, Any]:
    return {
        "content": [
            {"type": "tool_use", "name": "submit_report", "input": SAMPLE_TOOL_INPUT}
        ]
    }


def _make_client() -> AnthropicClient:
    return AnthropicClient(
        api_key="test_key",
        model="claude-sonnet-4-6",
        timeout_s=2.0,
    )


@pytest.fixture
def respx_mock() -> Iterator[respx.MockRouter]:
    """Locally-scoped respx router (mirrors the whatsapp conftest pattern)."""
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


# ─── Happy path ────────────────────────────────────────────────────────


async def test_anthropic_returns_tool_use_block(
    respx_mock: respx.MockRouter,
) -> None:
    """200 + well-formed ``tool_use`` block → ``complete_json`` returns the
    block's ``input`` dict verbatim."""
    respx_mock.post(ANTHROPIC_URL).mock(
        return_value=httpx.Response(200, json=_ok_response_body())
    )

    client = _make_client()
    result = await client.complete_json(
        system="x",
        user="y",
        schema={"type": "object"},
    )

    assert result == SAMPLE_TOOL_INPUT


# ─── Invalid response shapes ───────────────────────────────────────────


async def test_anthropic_no_tool_use_block_raises_invalid(
    respx_mock: respx.MockRouter,
) -> None:
    """200 with only a text block (no ``tool_use``) → ``LLMInvalidResponse``."""
    respx_mock.post(ANTHROPIC_URL).mock(
        return_value=httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "hi"}]},
        )
    )

    client = _make_client()
    with pytest.raises(LLMInvalidResponse):
        await client.complete_json(
            system="x",
            user="y",
            schema={"type": "object"},
        )


async def test_anthropic_wrong_tool_name_raises_invalid(
    respx_mock: respx.MockRouter,
) -> None:
    """200 with a ``tool_use`` block whose name is NOT ``submit_report``
    → ``LLMInvalidResponse``."""
    respx_mock.post(ANTHROPIC_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "content": [
                    {"type": "tool_use", "name": "different_tool", "input": {}}
                ]
            },
        )
    )

    client = _make_client()
    with pytest.raises(LLMInvalidResponse):
        await client.complete_json(
            system="x",
            user="y",
            schema={"type": "object"},
        )


# ─── Transient (retryable) failures ────────────────────────────────────


async def test_anthropic_500_raises_unavailable(
    respx_mock: respx.MockRouter,
) -> None:
    """5xx → ``LLMUnavailable`` (retryable)."""
    respx_mock.post(ANTHROPIC_URL).mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )

    client = _make_client()
    with pytest.raises(LLMUnavailable):
        await client.complete_json(
            system="x",
            user="y",
            schema={"type": "object"},
        )


async def test_anthropic_429_raises_unavailable(
    respx_mock: respx.MockRouter,
) -> None:
    """429 (rate-limited) → ``LLMUnavailable`` (retryable per design § 5)."""
    respx_mock.post(ANTHROPIC_URL).mock(
        return_value=httpx.Response(429, json={"error": "rate limited"})
    )

    client = _make_client()
    with pytest.raises(LLMUnavailable):
        await client.complete_json(
            system="x",
            user="y",
            schema={"type": "object"},
        )


async def test_anthropic_timeout_raises_unavailable(
    respx_mock: respx.MockRouter,
) -> None:
    """``httpx.TimeoutException`` on the wire → ``LLMUnavailable``."""
    respx_mock.post(ANTHROPIC_URL).mock(
        side_effect=httpx.TimeoutException("slow")
    )

    client = _make_client()
    with pytest.raises(LLMUnavailable):
        await client.complete_json(
            system="x",
            user="y",
            schema={"type": "object"},
        )


# ─── Non-retryable client error ────────────────────────────────────────


async def test_anthropic_400_raises_llm_error(
    respx_mock: respx.MockRouter,
) -> None:
    """400 Bad Request → ``LLMError`` (but NOT ``LLMUnavailable`` — caller
    must NOT retry: the request itself is malformed)."""
    respx_mock.post(ANTHROPIC_URL).mock(
        return_value=httpx.Response(400, json={"error": "bad request"})
    )

    client = _make_client()
    with pytest.raises(LLMError) as exc_info:
        await client.complete_json(
            system="x",
            user="y",
            schema={"type": "object"},
        )

    assert not isinstance(exc_info.value, LLMUnavailable), (
        "400 must raise LLMError but NOT the retryable LLMUnavailable subclass"
    )


# ─── Request body shape ────────────────────────────────────────────────


async def test_anthropic_request_body_includes_tool_choice(
    respx_mock: respx.MockRouter,
) -> None:
    """The outgoing request must pin ``tool_choice`` to ``submit_report`` and
    embed the caller-supplied JSON schema as ``tools[0].input_schema`` — this
    is the coercion mechanism that guarantees structured output (design § 5)."""
    respx_mock.post(ANTHROPIC_URL).mock(
        return_value=httpx.Response(200, json=_ok_response_body())
    )

    client = _make_client()
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"diagnostic_summary": {"type": "string"}},
        "required": ["diagnostic_summary"],
    }
    user_prompt = "Please analyze this conversation log."
    system_prompt = "You are an expert sales analyst."

    await client.complete_json(
        system=system_prompt,
        user=user_prompt,
        schema=schema,
    )

    # respx records every intercepted call; pull the last one and inspect its body.
    last_request = respx_mock.calls.last.request
    body = json.loads(last_request.content)

    assert body["model"] == "claude-sonnet-4-6"
    assert body["system"] == system_prompt
    assert body["messages"] == [{"role": "user", "content": user_prompt}]
    assert isinstance(body["tools"], list) and len(body["tools"]) == 1
    assert body["tools"][0]["name"] == "submit_report"
    assert body["tools"][0]["input_schema"] == schema
    assert body["tool_choice"] == {"type": "tool", "name": "submit_report"}
