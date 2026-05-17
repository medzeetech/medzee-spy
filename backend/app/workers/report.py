"""Report generation pipeline (F3 design § 12).

Fire-and-forget worker spawned by ``app.workers.extract`` after a successful
or partial extract. Computes deterministic metrics, samples conversations,
calls the LLM, validates the structured output, composes the final
``ReportPayload``, and persists to ``medzee_spy.reports``.

The pipeline NEVER raises out of the public entry point. Every failure path
maps to ``repository.update_failed`` with a stable ``error_code`` (see the
error mapping in F3 design § 16).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from uuid import UUID

from app.clients.llm import (
    LLMClient,
    LLMError,
    LLMInvalidResponse,
    LLMUnavailable,
    get_llm_client,
)
from app.core.config import settings
from app.modules.reports import repository
from app.modules.reports.benchmarks import build_benchmarks
from app.modules.reports.metrics import (
    compute_conversation_count,
    compute_funnel,
    compute_heatmap,
    compute_message_count,
    compute_response_time_distribution,
    compute_score,
)
from app.modules.reports.prompts import (
    LLM_TOOL_SCHEMA,
    PROMPT_VERSION,
    build_user_prompt,
    get_system_prompt,
)
from app.modules.reports.sampling import sample_conversations
from app.modules.reports.schemas import (
    BenchmarkMetric,
    FAQ,
    FunnelStage,
    HeatmapPeriod,
    Objection,
    Opportunity,
    ReportPayload,
    ResponseTimeBucket,
    SentimentSlice,
)
from app.modules.whatsapp.schemas import ExtractedPayload

logger = logging.getLogger(__name__)


# Hard timeout for the whole pipeline (LLM + metrics). F3 §REPORT-13.
_HARD_TIMEOUT_S: float = 120.0

# LLM error code → persisted ``error_code`` value (F3 §16 mapping).
_ERR_TIMEOUT = "llm_timeout"
_ERR_UNAVAILABLE = "llm_unavailable"
_ERR_INVALID_JSON = "llm_invalid_json"
_ERR_INTERNAL = "internal_error"

# A correction nudge for the second attempt when the LLM returns JSON
# that fails the schema check (F3 §EC-03).
_LLM_RETRY_NUDGE = (
    " IMPORTANTE: a chamada anterior falhou no schema. Use APENAS a tool "
    "`submit_report` com os campos exatos do input_schema (5 campos, tipos "
    "corretos). Não acrescente texto antes ou depois."
)


async def generate_report_pipeline(
    session_id: UUID,
    payload: ExtractedPayload,
    *,
    user_id: UUID | None = None,
    llm: LLMClient | None = None,
    report_id: UUID | None = None,
) -> None:
    """Public entry. Fire-and-forget. NEVER raises out.

    Two entry modes:

    * **F3 mode** (``report_id=None``): legacy F1 → F3 flow. The worker
      creates the row itself (or reuses a placeholder from
      ``consume_extracted``).
    * **F4 mode** (``report_id`` provided by caller): the row was already
      INSERTed by ``ReportService.trigger_generate`` with the right
      ``period_days``. Skip the create step and reuse the caller's id.

    Sequence:
        1. Resolve ``clinic_segment`` (from ``users_profile`` if user_id, else 'outro').
        2. Get/create the ``report_id`` (depends on entry mode above).
        3. Run the inner pipeline inside ``asyncio.wait_for(timeout=120s)``:
           a. Compute deterministic metrics.
           b. Score.
           c. Sample conversations.
           d. Build prompts.
           e. Call LLM; retry once on ``LLMInvalidResponse`` with nudge.
           f. Compose ``ReportPayload``.
           g. ``repository.update_completed`` (or ``update_partial`` if
              ``payload.partial=True``).
        4. On any exception: ``repository.update_failed(error_code=...)``.
    """
    started_at = time.monotonic()
    logger.info(
        "worker.report.enter",
        extra={
            "op": "generate_report",
            "session_id": str(session_id),
            "user_id": str(user_id) if user_id else None,
            "report_id": str(report_id) if report_id else None,
            "message_count": payload.message_count,
            "conversation_count": payload.conversation_count,
            "partial": payload.partial,
        },
    )

    clinic_segment = await _resolve_clinic_segment(user_id)

    # F4: caller (ReportService.trigger_generate) already created the row.
    # Skip create logic entirely.
    if report_id is not None:
        logger.info(
            "worker.report.using_caller_provided_row",
            extra={
                "op": "generate_report",
                "session_id": str(session_id),
                "report_id": str(report_id),
            },
        )
    else:
        # F3 mode: create (or reuse placeholder from consume_extracted).
        try:
            existing = await repository.get_existing_for_session(session_id)
            if existing is not None:
                report_id = UUID(str(existing["id"]))
                logger.info(
                    "worker.report.reusing_placeholder_row",
                    extra={
                        "op": "generate_report",
                        "session_id": str(session_id),
                        "report_id": str(report_id),
                    },
                )
            else:
                report_id = await repository.create_generating(
                    whatsapp_session_id=session_id,
                    user_id=user_id,
                    clinic_segment=clinic_segment,
                )
        except Exception:
            logger.exception(
                "worker.report.create_failed",
                extra={"op": "generate_report", "session_id": str(session_id)},
            )
            return  # Nothing else to do — we can't even mark a row failed.

    client = llm if llm is not None else get_llm_client()

    try:
        await asyncio.wait_for(
            _inner(
                report_id=report_id,
                session_id=session_id,
                payload=payload,
                clinic_segment=clinic_segment,
                llm=client,
                started_at=started_at,
            ),
            timeout=_HARD_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        await _persist_failed(report_id, error_code=_ERR_TIMEOUT, session_id=session_id)
    except LLMUnavailable as exc:
        logger.warning(
            "worker.report.llm_unavailable",
            extra={
                "op": "generate_report",
                "session_id": str(session_id),
                "report_id": str(report_id),
                "detail": str(exc)[:200],
            },
        )
        await _persist_failed(
            report_id, error_code=_ERR_UNAVAILABLE, session_id=session_id
        )
    except LLMInvalidResponse as exc:
        logger.warning(
            "worker.report.llm_invalid_json",
            extra={
                "op": "generate_report",
                "session_id": str(session_id),
                "report_id": str(report_id),
                "detail": str(exc)[:200],
            },
        )
        await _persist_failed(
            report_id, error_code=_ERR_INVALID_JSON, session_id=session_id
        )
    except LLMError as exc:
        logger.warning(
            "worker.report.llm_error",
            extra={
                "op": "generate_report",
                "session_id": str(session_id),
                "report_id": str(report_id),
                "detail": str(exc)[:200],
            },
        )
        await _persist_failed(
            report_id, error_code=_ERR_UNAVAILABLE, session_id=session_id
        )
    except Exception:
        logger.exception(
            "worker.report.internal_error",
            extra={
                "op": "generate_report",
                "session_id": str(session_id),
                "report_id": str(report_id),
            },
        )
        await _persist_failed(
            report_id, error_code=_ERR_INTERNAL, session_id=session_id
        )


# ─── Inner pipeline ────────────────────────────────────────────────────


async def _inner(
    *,
    report_id: UUID,
    session_id: UUID,
    payload: ExtractedPayload,
    clinic_segment: str,
    llm: LLMClient,
    started_at: float,
) -> None:
    # 1. Deterministic metrics.
    funnel = compute_funnel(payload)
    response_time = compute_response_time_distribution(payload)
    heatmap = compute_heatmap(payload)
    message_count = compute_message_count(payload)
    conversation_count = compute_conversation_count(payload)
    score = compute_score(message_count, response_time, funnel)

    # 2. Sample conversations for LLM input budget.
    sampled = sample_conversations(payload)

    # 3. Prompts.
    metrics_snapshot = {
        "message_count": message_count,
        "conversation_count": conversation_count,
        "score": score,
        "funnel": [{"stage": s.stage, "count": s.count, "pct": s.pct} for s in funnel],
    }
    system_prompt = get_system_prompt(clinic_segment)
    user_prompt = build_user_prompt(
        clinic_segment=clinic_segment,
        metrics_snapshot=metrics_snapshot,
        sampled_conversations=sampled,
    )

    # 4. LLM call with 1 corrective retry on invalid JSON.
    # Observability: emite log explícito ANTES e DEPOIS da chamada. Permite
    # confirmar visualmente que Claude foi acionado de fato (não é fallback).
    llm_started = time.monotonic()
    logger.info(
        "worker.report.llm_call.start",
        extra={
            "op": "generate_report",
            "report_id": str(report_id),
            "session_id": str(session_id),
            "clinic_segment": clinic_segment,
            "sampled_conversations": len(sampled),
            "user_prompt_chars": len(user_prompt),
            "system_prompt_chars": len(system_prompt),
        },
    )
    try:
        llm_dict = await llm.complete_json(
            system=system_prompt,
            user=user_prompt,
            schema=LLM_TOOL_SCHEMA,
        )
    except LLMInvalidResponse:
        # Second chance with explicit correction guidance.
        logger.info(
            "worker.report.llm_retry_invalid_json",
            extra={"op": "generate_report", "report_id": str(report_id)},
        )
        llm_dict = await llm.complete_json(
            system=system_prompt,
            user=user_prompt + "\n" + _LLM_RETRY_NUDGE,
            schema=LLM_TOOL_SCHEMA,
        )

    logger.info(
        "worker.report.llm_call.done",
        extra={
            "op": "generate_report",
            "report_id": str(report_id),
            "session_id": str(session_id),
            "elapsed_ms": int((time.monotonic() - llm_started) * 1000),
            "opportunities_count": len(llm_dict.get("opportunities") or []),
            "objections_count": len(llm_dict.get("objections") or []),
            "faqs_count": len(llm_dict.get("faqs") or []),
            "diagnostic_summary_chars": len(llm_dict.get("diagnostic_summary") or ""),
        },
    )

    # 5. Compose ReportPayload.
    benchmarks = _build_clinic_benchmarks(
        clinic_segment=clinic_segment,
        response_time=response_time,
        funnel=funnel,
    )
    final_payload = _compose(
        message_count=message_count,
        conversation_count=conversation_count,
        score=score,
        clinic_segment=clinic_segment,
        funnel=funnel,
        response_time=response_time,
        heatmap=heatmap,
        llm_dict=llm_dict,
        benchmarks=benchmarks,
    )

    # 6. Persist.
    model = settings.LLM_MODEL
    persist_fn = (
        repository.update_partial if payload.partial else repository.update_completed
    )
    await persist_fn(
        report_id,
        payload=final_payload.model_dump(),
        model=model,
        prompt_version=PROMPT_VERSION,
        message_count=message_count,
        score=score,
    )

    logger.info(
        "worker.report.exit",
        extra={
            "op": "generate_report",
            "report_id": str(report_id),
            "session_id": str(session_id),
            "status": "partial" if payload.partial else "completed",
            "score": score,
            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
        },
    )


# ─── Helpers ──────────────────────────────────────────────────────────


async def _resolve_clinic_segment(user_id: UUID | None) -> str:
    """Look up ``users_profile.clinic_segment`` when a user is already linked.

    Falls back to ``'outro'`` for anonymous flows (signup hasn't happened yet)
    and for any DB lookup error (best-effort — no need to fail the whole
    pipeline over this).
    """
    if user_id is None:
        return "outro"
    try:
        from app.modules.auth import repository as auth_repo
        profile = await auth_repo.get_profile(user_id)
        if profile is None:
            return "outro"
        segment = profile.get("clinic_segment")
        if segment in ("saude", "odonto", "outro"):
            return segment
        return "outro"
    except Exception:
        logger.warning(
            "worker.report.resolve_segment_failed",
            extra={"op": "generate_report", "user_id": str(user_id)},
            exc_info=True,
        )
        return "outro"


def _build_clinic_benchmarks(
    *,
    clinic_segment: str,
    response_time: list[ResponseTimeBucket],
    funnel: list[FunnelStage],
) -> list[BenchmarkMetric]:
    """Translate deterministic metrics into the 4 benchmark inputs."""
    total_responses = sum(b.count for b in response_time)
    # Weighted average response time in hours. Use bucket midpoints.
    bucket_midpoints_h = [
        (0 + 5 / 60) / 2,             # < 5 min       → ~2.5 min
        (5 / 60 + 30 / 60) / 2,       # 5-30 min      → ~17.5 min
        (30 / 60 + 1) / 2,            # 30 min - 1h   → ~45 min
        (1 + 4) / 2,                  # 1-4 h         → 2.5 h
        (4 + 24) / 2,                 # 4-24 h        → 14 h
        24 + 12,                      # > 24h         → assume 36 h
    ]
    if total_responses > 0:
        weighted_h = sum(
            b.count * m for b, m in zip(response_time, bucket_midpoints_h, strict=True)
        )
        avg_response_h = round(weighted_h / total_responses, 2)
    else:
        avg_response_h = 0.0

    # pct of stage 5 (conversion) and stage 2 (response rate) come from funnel
    conversion_pct = funnel[4].pct if len(funnel) >= 5 else 0.0
    response_rate_pct = funnel[1].pct if len(funnel) >= 2 else 0.0
    unanswered_pct = round(max(0.0, 100.0 - response_rate_pct), 1)
    # Follow-up: rough proxy = pct of conversations that went past stage 4.
    followup_pct = funnel[3].pct if len(funnel) >= 4 else 0.0

    return build_benchmarks(
        clinic_segment=clinic_segment,
        clinic_response_time_h=avg_response_h,
        clinic_conversion_pct=conversion_pct,
        clinic_unanswered_pct=unanswered_pct,
        clinic_followup_pct=followup_pct,
    )


def _compose(
    *,
    message_count: int,
    conversation_count: int,
    score: int,
    clinic_segment: str,
    funnel: list[FunnelStage],
    response_time: list[ResponseTimeBucket],
    heatmap: list[HeatmapPeriod],
    llm_dict: dict[str, Any],
    benchmarks: list[BenchmarkMetric],
) -> ReportPayload:
    return ReportPayload(
        message_count=message_count,
        conversation_count=conversation_count,
        score=score,
        clinic_segment=clinic_segment,
        diagnostic_summary=llm_dict.get("diagnostic_summary", ""),
        funnel=funnel,
        response_time_distribution=response_time,
        heatmap_periods=heatmap,
        opportunities=[Opportunity(**o) for o in llm_dict.get("opportunities", [])],
        objections=[Objection(**o) for o in llm_dict.get("objections", [])],
        faqs=[FAQ(**f) for f in llm_dict.get("faqs", [])],
        sentiment=[SentimentSlice(**s) for s in llm_dict.get("sentiment", [])],
        benchmarks=benchmarks,
    )


async def _persist_failed(report_id: UUID, *, error_code: str, session_id: UUID) -> None:
    """Best-effort: mark the row failed. Swallow secondary errors."""
    try:
        await repository.update_failed(report_id, error_code=error_code)
    except Exception:
        logger.exception(
            "worker.report.persist_failed_secondary_error",
            extra={
                "op": "generate_report",
                "report_id": str(report_id),
                "session_id": str(session_id),
                "error_code": error_code,
            },
        )


__all__ = ["generate_report_pipeline"]
