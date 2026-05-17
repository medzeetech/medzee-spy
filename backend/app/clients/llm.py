"""LLM client abstraction — only file in the codebase that talks to the LLM provider.

Defines a provider-neutral `LLMClient` Protocol whose single method
`complete_json` forces the model to return a JSON object that conforms to a
caller-supplied JSON Schema. The Anthropic adapter implements this by issuing
a Messages API call with a single tool whose `input_schema` is the desired
schema and `tool_choice` pinned to that tool — Anthropic guarantees the
response will contain exactly one `tool_use` block whose `input` matches the
schema (see design § 5 of F3).

All network / non-2xx outcomes funnel through the `LLMError` hierarchy so
callers (report worker) never see raw `httpx` exceptions.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Protocol

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_TOOL_NAME = "submit_report"
_TOOL_DESCRIPTION = "Submit the structured commercial report."
_DEFAULT_TIMEOUT_S = 90.0


class LLMError(Exception):
    """Base class for all LLM client failures."""


class LLMUnavailable(LLMError):
    """Transient provider failure — network, timeout, 5xx, or 429.

    Callers should treat this as retryable.
    """


class LLMInvalidResponse(LLMError):
    """Provider returned 200 but the payload did not contain the expected tool_use block."""


class LLMClient(Protocol):
    """Provider-neutral LLM contract.

    `complete_json` must coerce the model into returning a JSON object that
    matches `schema`. Implementations are free to use whatever provider-native
    mechanism is available (Anthropic tool_use, OpenAI response_format, etc.).
    """

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> dict[str, Any]: ...


class AnthropicClient:
    """Async adapter for Anthropic's Messages API with tool_use coercion."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_s = timeout_s

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        body = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [
                {
                    "name": _TOOL_NAME,
                    "description": _TOOL_DESCRIPTION,
                    "input_schema": schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": _TOOL_NAME},
        }

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.post(
                    _ANTHROPIC_MESSAGES_URL,
                    headers=headers,
                    json=body,
                )
        except httpx.TimeoutException:
            self._log("err", started, model=self._model, err="LLMUnavailable:timeout")
            raise LLMUnavailable("anthropic request timed out") from None
        except httpx.HTTPError as exc:
            self._log(
                "err",
                started,
                model=self._model,
                err=f"LLMUnavailable:{type(exc).__name__}",
            )
            raise LLMUnavailable(f"anthropic network error: {type(exc).__name__}") from exc

        status = response.status_code

        if status >= 500 or status == 429:
            snippet = (response.text or "")[:200]
            logger.info(
                "llm provider=anthropic model=%s status=%d err=LLMUnavailable body=%r",
                self._model,
                status,
                snippet,
            )
            raise LLMUnavailable(f"anthropic {status}")

        if 400 <= status < 500:
            snippet = (response.text or "")[:200]
            logger.info(
                "llm provider=anthropic model=%s status=%d err=LLMError body=%r",
                self._model,
                status,
                snippet,
            )
            raise LLMError(f"anthropic {status}: {snippet}")

        if not (200 <= status < 300):
            snippet = (response.text or "")[:200]
            logger.info(
                "llm provider=anthropic model=%s status=%d err=LLMError body=%r",
                self._model,
                status,
                snippet,
            )
            raise LLMError(f"anthropic unexpected status {status}")

        try:
            data = response.json()
        except ValueError as exc:
            logger.info(
                "llm provider=anthropic model=%s status=%d err=LLMInvalidResponse:not_json",
                self._model,
                status,
            )
            raise LLMInvalidResponse("anthropic response was not valid JSON") from exc

        tool_input = _extract_tool_input(data, tool_name=_TOOL_NAME)
        if tool_input is None:
            logger.info(
                "llm provider=anthropic model=%s status=%d err=LLMInvalidResponse:no_tool_use",
                self._model,
                status,
            )
            raise LLMInvalidResponse(
                f"no tool_use block named {_TOOL_NAME!r} in anthropic response"
            )

        self._log(status, started, model=self._model)
        return tool_input

    @staticmethod
    def _log(
        status: int | str,
        started: float,
        *,
        model: str,
        err: str | None = None,
    ) -> None:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if err:
            logger.info(
                "llm provider=anthropic model=%s status=%s elapsed_ms=%d err=%s",
                model,
                status,
                elapsed_ms,
                err,
            )
        else:
            logger.info(
                "llm provider=anthropic model=%s status=%s elapsed_ms=%d",
                model,
                status,
                elapsed_ms,
            )


def _extract_tool_input(data: Any, *, tool_name: str) -> dict[str, Any] | None:
    """Find the `tool_use` content block matching `tool_name` and return its `input`.

    Anthropic's Messages API returns:
        {"content": [{"type": "tool_use", "name": "...", "input": {...}}, ...], ...}
    With `tool_choice` pinned to a tool we expect exactly one such block, but
    we still iterate defensively in case the API returns text + tool_use.
    """
    if not isinstance(data, dict):
        return None
    content = data.get("content")
    if not isinstance(content, list):
        return None
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool_use":
            continue
        if block.get("name") != tool_name:
            continue
        tool_input = block.get("input")
        if isinstance(tool_input, dict):
            return tool_input
    return None


def get_llm_client() -> LLMClient:
    """Factory — pick the adapter based on `settings.LLM_PROVIDER`."""
    if settings.LLM_PROVIDER == "anthropic":
        return AnthropicClient(
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.LLM_MODEL,
        )
    raise NotImplementedError(f"LLM_PROVIDER={settings.LLM_PROVIDER!r}")
