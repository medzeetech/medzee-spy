"""Tests for ``app.workers.report.generate_report_pipeline`` (F3 T20).

The pipeline is fire-and-forget: it NEVER raises out of the public entry
point. Every failure path is asserted via the ``error_code`` value handed
to ``repository.update_failed``.

These tests rely on the shared conftest fixtures:

* ``fake_repository`` — monkeypatches ``app.modules.reports.repository.*`` to
  ``AsyncMock`` instances exposed as a ``SimpleNamespace``.
* ``fake_llm`` — an ``AsyncMock`` whose ``complete_json`` returns a valid
  5-key dict matching ``LLM_TOOL_SCHEMA``.
* ``sample_extracted_payload`` — factory producing realistic
  ``ExtractedPayload`` instances.

Tests use the default report id from conftest
(``UUID('00000000-0000-0000-0000-000000000099')``) so we don't have to
chain ``create_generating.return_value`` per-test.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.clients.llm import LLMInvalidResponse, LLMUnavailable
from app.workers.report import generate_report_pipeline


DEFAULT_REPORT_ID = UUID("00000000-0000-0000-0000-000000000099")


def _valid_llm_dict() -> dict:
    """Minimal-but-valid 5-key LLM response shaped like ``LLM_TOOL_SCHEMA``."""
    return {
        "diagnostic_summary": (
            "A clínica responde rápido em horário comercial mas perde leads "
            "no período da noite. Recomenda-se um fluxo automatizado para "
            "captar essas oportunidades fora do expediente."
        ),
        "opportunities": [
            {
                "tag": "Lead quente sem follow-up",
                "context": "Paciente perguntou e nunca recebeu retorno.",
                "reason": "Demonstrou interesse claro.",
                "value_brl": 1500.0,
                "when": "há 2 dias",
            },
        ],
        "objections": [
            {"label": "Preço", "pct": 50.0, "count": 10, "color": "#EF4444"},
        ],
        "faqs": [
            {"q": "Vocês aceitam parcelamento?", "count": 14},
        ],
        "sentiment": [
            {"name": "Positivo", "value": 50, "color": "#10B981"},
            {"name": "Neutro", "value": 30, "color": "#6B7280"},
            {"name": "Negativo", "value": 20, "color": "#EF4444"},
        ],
    }


# ─── Tests ────────────────────────────────────────────────────────────


async def test_worker_happy_path(
    fake_repository,
    fake_llm,
    sample_extracted_payload,
):
    """End-to-end happy path: create_generating → LLM → update_completed."""
    sid = uuid4()
    payload = sample_extracted_payload(message_count=200, conversation_count=20)

    await generate_report_pipeline(sid, payload, user_id=uuid4(), llm=fake_llm)

    # create_generating called exactly once with the session id.
    assert fake_repository.create_generating.await_count == 1
    create_kwargs = fake_repository.create_generating.await_args.kwargs
    assert create_kwargs["whatsapp_session_id"] == sid

    # LLM called once with the standard happy path (no retry).
    assert fake_llm.complete_json.await_count == 1

    # update_completed called with the conftest-default report id.
    assert fake_repository.update_completed.await_count == 1
    completed_args = fake_repository.update_completed.await_args
    assert completed_args.args[0] == DEFAULT_REPORT_ID

    # No failure path was taken.
    fake_repository.update_failed.assert_not_awaited()
    fake_repository.update_partial.assert_not_awaited()


async def test_worker_partial_payload_calls_update_partial(
    fake_repository,
    fake_llm,
    sample_extracted_payload,
):
    """When ExtractedPayload.partial=True, repository.update_partial wins."""
    sid = uuid4()
    payload = sample_extracted_payload(message_count=200, conversation_count=20)
    payload = payload.model_copy(update={"partial": True})

    await generate_report_pipeline(sid, payload, user_id=uuid4(), llm=fake_llm)

    fake_repository.update_partial.assert_awaited_once()
    fake_repository.update_completed.assert_not_awaited()
    fake_repository.update_failed.assert_not_awaited()


async def test_worker_llm_unavailable_persists_failed(
    fake_repository,
    fake_llm,
    sample_extracted_payload,
):
    """LLMUnavailable → update_failed(error_code='llm_unavailable')."""
    sid = uuid4()
    payload = sample_extracted_payload(message_count=200, conversation_count=20)
    fake_llm.complete_json.side_effect = LLMUnavailable("boom")

    await generate_report_pipeline(sid, payload, user_id=uuid4(), llm=fake_llm)

    fake_repository.update_failed.assert_awaited_once()
    args, kwargs = fake_repository.update_failed.await_args
    assert args[0] == DEFAULT_REPORT_ID
    assert kwargs["error_code"] == "llm_unavailable"
    fake_repository.update_completed.assert_not_awaited()


async def test_worker_llm_invalid_first_then_valid(
    fake_repository,
    fake_llm,
    sample_extracted_payload,
):
    """First LLMInvalidResponse triggers a single corrective retry."""
    sid = uuid4()
    payload = sample_extracted_payload(message_count=200, conversation_count=20)
    fake_llm.complete_json.side_effect = [
        LLMInvalidResponse("bad json"),
        _valid_llm_dict(),
    ]

    await generate_report_pipeline(sid, payload, user_id=uuid4(), llm=fake_llm)

    assert fake_llm.complete_json.await_count == 2
    fake_repository.update_completed.assert_awaited_once()
    fake_repository.update_failed.assert_not_awaited()


async def test_worker_llm_invalid_twice_persists_failed(
    fake_repository,
    fake_llm,
    sample_extracted_payload,
):
    """Two consecutive LLMInvalidResponse → update_failed('llm_invalid_json')."""
    sid = uuid4()
    payload = sample_extracted_payload(message_count=200, conversation_count=20)
    fake_llm.complete_json.side_effect = [
        LLMInvalidResponse("a"),
        LLMInvalidResponse("b"),
    ]

    await generate_report_pipeline(sid, payload, user_id=uuid4(), llm=fake_llm)

    assert fake_llm.complete_json.await_count == 2
    fake_repository.update_failed.assert_awaited_once()
    _, kwargs = fake_repository.update_failed.await_args
    assert kwargs["error_code"] == "llm_invalid_json"
    fake_repository.update_completed.assert_not_awaited()


async def test_worker_timeout_persists_failed(
    fake_repository,
    fake_llm,
    sample_extracted_payload,
    monkeypatch,
):
    """asyncio.TimeoutError from hard pipeline timeout → 'llm_timeout'."""
    sid = uuid4()
    payload = sample_extracted_payload(message_count=200, conversation_count=20)

    async def _slow(**_kwargs):
        await asyncio.sleep(200)
        return _valid_llm_dict()

    fake_llm.complete_json.side_effect = _slow
    monkeypatch.setattr("app.workers.report._HARD_TIMEOUT_S", 0.05)

    await generate_report_pipeline(sid, payload, user_id=uuid4(), llm=fake_llm)

    fake_repository.update_failed.assert_awaited_once()
    _, kwargs = fake_repository.update_failed.await_args
    assert kwargs["error_code"] == "llm_timeout"
    fake_repository.update_completed.assert_not_awaited()


async def test_worker_generic_exception_persists_failed(
    fake_repository,
    fake_llm,
    sample_extracted_payload,
):
    """Any unexpected exception inside the pipeline → 'internal_error'."""
    sid = uuid4()
    payload = sample_extracted_payload(message_count=200, conversation_count=20)
    fake_repository.update_completed.side_effect = RuntimeError("db blip")

    # Must not raise out.
    await generate_report_pipeline(sid, payload, user_id=uuid4(), llm=fake_llm)

    fake_repository.update_failed.assert_awaited_once()
    _, kwargs = fake_repository.update_failed.await_args
    assert kwargs["error_code"] == "internal_error"


async def test_worker_user_id_none_falls_back_outro_segment(
    fake_repository,
    fake_llm,
    sample_extracted_payload,
):
    """No user_id → no auth lookup, clinic_segment defaults to 'outro'."""
    sid = uuid4()
    payload = sample_extracted_payload(message_count=200, conversation_count=20)

    await generate_report_pipeline(sid, payload, user_id=None, llm=fake_llm)

    fake_repository.create_generating.assert_awaited_once()
    kwargs = fake_repository.create_generating.await_args.kwargs
    assert kwargs["clinic_segment"] == "outro"
    assert kwargs["user_id"] is None


async def test_worker_resolves_clinic_segment_from_user_profile(
    fake_repository,
    fake_llm,
    sample_extracted_payload,
    monkeypatch,
):
    """When user_id is provided, clinic_segment comes from auth_repo.get_profile."""
    sid = uuid4()
    uid = uuid4()
    payload = sample_extracted_payload(message_count=200, conversation_count=20)

    fake_get_profile = AsyncMock(
        return_value={"clinic_segment": "odonto", "id": str(uid)}
    )
    monkeypatch.setattr(
        "app.modules.auth.repository.get_profile",
        fake_get_profile,
    )

    await generate_report_pipeline(sid, payload, user_id=uid, llm=fake_llm)

    fake_get_profile.assert_awaited_once()
    fake_repository.create_generating.assert_awaited_once()
    kwargs = fake_repository.create_generating.await_args.kwargs
    assert kwargs["clinic_segment"] == "odonto"


async def test_worker_create_failed_aborts_silently(
    fake_repository,
    fake_llm,
    sample_extracted_payload,
):
    """If create_generating itself errors, we can't even record the failure.

    The pipeline must return without raising, must not call any downstream
    update_* function (there's no report_id to address), and must not call
    the LLM.
    """
    sid = uuid4()
    payload = sample_extracted_payload(message_count=200, conversation_count=20)
    fake_repository.create_generating.side_effect = RuntimeError("insert err")

    # Must not raise.
    await generate_report_pipeline(sid, payload, user_id=uuid4(), llm=fake_llm)

    fake_repository.update_failed.assert_not_awaited()
    fake_repository.update_completed.assert_not_awaited()
    fake_repository.update_partial.assert_not_awaited()
    fake_llm.complete_json.assert_not_awaited()
