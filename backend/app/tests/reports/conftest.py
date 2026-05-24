"""Shared fixtures for the reports module tests (F3).

Mirrors the F2 (auth) conftest pattern: lazy string-path monkeypatching so
attribute resolution is deferred to fixture-call time. Several sibling agents
are concurrently authoring ``app/modules/reports/repository.py`` and
``app/clients/llm`` — by patching via dotted strings (and using
``raising=False`` where the target may not yet expose the symbol) this conftest
can be collected even when those modules are mid-flight.

Fixtures exposed:

* :func:`fake_llm` — an ``AsyncMock`` shaped like ``app.clients.llm.LLMClient``
  whose ``complete_json`` returns the 5-field dict that the report worker
  expects from the LLM (matches ``LLM_TOOL_SCHEMA``).
* :func:`fake_llm_factory` — patches ``app.clients.llm.get_llm_client`` to
  return :func:`fake_llm` (and the re-bound name inside the reports service,
  with ``raising=False``).
* :func:`fake_repository` — replaces every public coroutine in
  ``app.modules.reports.repository`` with an ``AsyncMock`` and returns a
  ``SimpleNamespace`` for assertion ergonomics.
* :func:`sample_extracted_payload` — factory producing realistic
  ``ExtractedPayload`` instances (configurable size + time window).
* :func:`sample_report_payload` — a fully-populated valid ``ReportPayload``
  for service/routes tests that don't exercise generation.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.reports.schemas import (
    BenchmarkMetric,
    ConversationPayload,
    ExtractedPayload,
    FAQ,
    FunnelStage,
    HeatmapPeriod,
    MessagePayload,
    Objection,
    Opportunity,
    ReportPayload,
    ResponseTimeBucket,
    SentimentSlice,
)


# Stable UUID returned by ``create_generating`` so tests can assert against it
# without juggling per-call values.
DEFAULT_REPORT_ID = UUID("00000000-0000-0000-0000-000000000099")


# ─── LLM client ───────────────────────────────────────────────────────


def _default_llm_response() -> dict:
    """Realistic LLM tool_use output — 5 keys matching ``LLM_TOOL_SCHEMA``.

    Sentiment slices sum to 100 (45 + 35 + 20) per the schema constraint in
    ``SentimentSlice.value: Field(ge=0, le=100)`` and the design contract that
    the three slices form a percentage breakdown.
    """
    return {
        "diagnostic_summary": (
            "A clínica responde em média em 2h17min, mas 38% dos leads ficam "
            "sem resposta por mais de 4 horas — a maioria deles à noite. O "
            "principal gargalo está na transição entre o agendamento inicial "
            "e a confirmação do horário."
        ),
        "opportunities": [
            {
                "tag": "Lead quente sem follow-up",
                "context": "Paciente perguntou sobre implante e nunca recebeu retorno.",
                "reason": "Demonstrou interesse claro e mencionou orçamento.",
                "value_brl": 4500.0,
                "when": "há 3 dias",
            },
            {
                "tag": "Reagendamento perdido",
                "context": "Cancelou consulta de avaliação e ninguém retomou.",
                "reason": "Histórico de duas consultas anteriores na clínica.",
                "value_brl": 1200.0,
                "when": "há 5 dias",
            },
        ],
        "objections": [
            {"label": "Preço alto", "pct": 42.0, "count": 17, "color": "#EF4444"},
            {"label": "Sem convênio", "pct": 28.0, "count": 11, "color": "#F59E0B"},
            {"label": "Distância", "pct": 18.0, "count": 7, "color": "#3B82F6"},
            {"label": "Horário", "pct": 12.0, "count": 5, "color": "#8B5CF6"},
        ],
        "faqs": [
            {"q": "Vocês aceitam parcelamento?", "count": 14},
            {"q": "Atendem por convênio?", "count": 11},
            {"q": "Qual o valor da consulta de avaliação?", "count": 9},
            {"q": "Têm estacionamento?", "count": 4},
        ],
        "sentiment": [
            {"name": "Positivo", "value": 45, "color": "#10B981"},
            {"name": "Neutro", "value": 35, "color": "#6B7280"},
            {"name": "Negativo", "value": 20, "color": "#EF4444"},
        ],
    }


@pytest.fixture
def fake_llm() -> AsyncMock:
    """An ``AsyncMock`` shaped like ``LLMClient`` with a sane default response.

    Tests can override ``fake_llm.complete_json.return_value`` (or
    ``.side_effect``) to inject schema-violating payloads, exceptions, etc.

    We don't pass ``spec=LLMClient`` because the Protocol may be unimportable
    at fixture-call time in some parallel-dev scenarios and the runtime
    surface we care about is just ``complete_json``.
    """
    mock = AsyncMock(name="llm_client")
    mock.complete_json = AsyncMock(
        name="complete_json",
        return_value=_default_llm_response(),
    )
    return mock


@pytest.fixture
def fake_llm_factory(
    monkeypatch: pytest.MonkeyPatch,
    fake_llm: AsyncMock,
) -> AsyncMock:
    """Patch ``app.clients.llm.get_llm_client`` to return :func:`fake_llm`.

    Also patches the re-imported name inside ``app.modules.reports.service``
    with ``raising=False`` — harmless if service.py hasn't bound the symbol
    yet, correct once it has.
    """
    monkeypatch.setattr(
        "app.clients.llm.get_llm_client",
        lambda: fake_llm,
        raising=False,
    )
    monkeypatch.setattr(
        "app.modules.reports.service.get_llm_client",
        lambda: fake_llm,
        raising=False,
    )
    # Also patch the worker entry point if/when it lands as a separate module.
    monkeypatch.setattr(
        "app.modules.reports.worker.get_llm_client",
        lambda: fake_llm,
        raising=False,
    )
    return fake_llm


# ─── Reports repository ───────────────────────────────────────────────


@pytest.fixture
def fake_repository(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Replace every public function in ``app.modules.reports.repository`` with
    an ``AsyncMock``.

    Patches by dotted string path so resolution is deferred to fixture-call
    time (repository.py may still be under construction by a sibling agent).
    ``raising=False`` is used uniformly: if a symbol doesn't exist yet, the
    patch is a no-op rather than a collection error — tests that depend on
    the patched name will fail loudly when the test body actually invokes it.
    """
    create_generating = AsyncMock(
        return_value=DEFAULT_REPORT_ID,
        name="create_generating",
    )
    update_completed = AsyncMock(return_value=None, name="update_completed")
    update_partial = AsyncMock(return_value=None, name="update_partial")
    update_failed = AsyncMock(return_value=None, name="update_failed")
    link_user = AsyncMock(return_value=None, name="link_user")
    get_existing_for_session = AsyncMock(
        return_value=None, name="get_existing_for_session"
    )
    get_by_id = AsyncMock(return_value=None, name="get_by_id")
    get_latest_for_user = AsyncMock(return_value=None, name="get_latest_for_user")
    list_for_user = AsyncMock(return_value=[], name="list_for_user")

    targets = (
        ("create_generating", create_generating),
        ("update_completed", update_completed),
        ("update_partial", update_partial),
        ("update_failed", update_failed),
        ("link_user", link_user),
        ("get_existing_for_session", get_existing_for_session),
        ("get_by_id", get_by_id),
        ("get_latest_for_user", get_latest_for_user),
        ("list_for_user", list_for_user),
    )

    for fn_name, fn_mock in targets:
        # Canonical location.
        monkeypatch.setattr(
            f"app.modules.reports.repository.{fn_name}",
            fn_mock,
            raising=False,
        )
        # Common re-import sites — patched defensively so a
        # ``from .repository import create_generating`` inside service/worker/
        # routes still sees the fake.
        for site in (
            "app.modules.reports.service",
            "app.modules.reports.worker",
            "app.modules.reports.routes",
        ):
            monkeypatch.setattr(
                f"{site}.{fn_name}",
                fn_mock,
                raising=False,
            )

    return SimpleNamespace(
        create_generating=create_generating,
        update_completed=update_completed,
        update_partial=update_partial,
        update_failed=update_failed,
        link_user=link_user,
        get_existing_for_session=get_existing_for_session,
        get_by_id=get_by_id,
        get_latest_for_user=get_latest_for_user,
        list_for_user=list_for_user,
    )


# ─── ExtractedPayload factory ─────────────────────────────────────────


# Small pool of PT-BR snippets — alternated to make timeline-shaped tests
# deterministic without being suspiciously uniform.
_FROM_ME_SNIPPETS = (
    "Olá! Tudo bem? Como posso te ajudar?",
    "Claro, podemos agendar para essa semana. Qual horário fica melhor pra você?",
    "O valor da consulta de avaliação é R$ 250.",
    "Sim, atendemos por convênio. Qual o seu plano?",
    "Vou confirmar a disponibilidade e já te retorno.",
    "Perfeito! Sua consulta está confirmada para amanhã às 14h.",
)
_FROM_THEM_SNIPPETS = (
    "Oi, gostaria de saber o valor da consulta.",
    "Vocês aceitam parcelamento?",
    "Quanto custa o tratamento de canal?",
    "Tem horário disponível essa semana?",
    "Atendem por convênio?",
    "Onde fica a clínica?",
    "Obrigada, vou pensar e te retorno!",
)


def _make_message(*, ts: int, from_me: bool) -> MessagePayload:
    pool = _FROM_ME_SNIPPETS if from_me else _FROM_THEM_SNIPPETS
    return MessagePayload(
        ts=ts,
        from_me=from_me,
        type="text",
        text=random.choice(pool),
    )


@pytest.fixture
def sample_extracted_payload():
    """Factory producing realistic ``ExtractedPayload`` instances.

    Usage::

        payload = sample_extracted_payload(message_count=50, conversation_count=5)

    Generation rules:

    * ``message_count`` is distributed roughly evenly across the conversations
      (the last conversation absorbs the remainder so the totals always match).
    * Timestamps are unix ints in seconds, spread within the last ``days``
      days using a uniform random offset.
    * Within a single conversation messages alternate ``from_me`` starting with
      ``False`` (contact opens the conversation).
    * If ``with_groups`` is true, every third conversation is flagged as a
      group (``is_group=True``, ``contact_name`` prefixed ``"Grupo"``).
    """

    def _factory(
        *,
        message_count: int = 200,
        conversation_count: int = 20,
        days: int = 30,
        with_groups: bool = False,
    ) -> ExtractedPayload:
        if conversation_count <= 0:
            raise ValueError("conversation_count must be > 0")
        if message_count < conversation_count:
            raise ValueError(
                "message_count must be >= conversation_count "
                "(at least 1 message per conversation)"
            )

        now_ts = int(datetime.now().timestamp())
        window_seconds = days * 24 * 60 * 60
        rng = random.Random(42)  # deterministic across test runs

        # Distribute messages: each conversation gets the floor, the last one
        # gets the remainder.
        per_conv_base = message_count // conversation_count
        remainder = message_count - per_conv_base * conversation_count

        conversations: list[ConversationPayload] = []
        for i in range(conversation_count):
            n_msgs = per_conv_base + (remainder if i == conversation_count - 1 else 0)
            messages: list[MessagePayload] = []
            for j in range(n_msgs):
                offset = rng.randint(0, window_seconds)
                ts = now_ts - offset
                # Alternate: first message of the conversation is from the
                # contact (from_me=False), then we toggle.
                from_me = (j % 2) == 1
                messages.append(_make_message(ts=ts, from_me=from_me))

            # Sort chronologically inside the conversation so downstream
            # timeline logic gets sensibly ordered input.
            messages.sort(key=lambda m: m.ts)

            is_group = with_groups and (i % 3 == 0)
            contact_name = (
                f"Grupo Pacientes {i + 1}" if is_group else f"Paciente {i + 1}"
            )
            wa_chatid = (
                f"55119000{i:04d}@g.us" if is_group else f"55119000{i:04d}@s.whatsapp.net"
            )

            conversations.append(
                ConversationPayload(
                    wa_chatid=wa_chatid,
                    contact_name=contact_name,
                    is_group=is_group,
                    last_message_at=messages[-1].ts if messages else None,
                    messages=messages,
                )
            )

        return ExtractedPayload(
            message_count=message_count,
            conversation_count=conversation_count,
            conversations=conversations,
            partial=False,
        )

    return _factory


# ─── Full valid ReportPayload ─────────────────────────────────────────


@pytest.fixture
def sample_report_payload() -> ReportPayload:
    """A fully-populated, schema-valid ``ReportPayload``.

    Useful for routes/service tests that need a ``completed`` report sitting
    in the repository without exercising the generation pipeline.

    All numeric breakdowns satisfy their bounds: funnel & objection pcts
    sum to <= 100 within their category, sentiment slices sum to 100, and
    every list satisfies its ``min_length`` constraint where applicable.
    """
    return ReportPayload(
        message_count=842,
        conversation_count=63,
        period_days=30,
        score=72,
        clinic_segment="odonto",
        diagnostic_summary=(
            "A clínica tem um bom volume mas perde leads no follow-up. "
            "Recomenda-se um SLA de resposta de 30 minutos no horário comercial "
            "e um fluxo automatizado para mensagens recebidas à noite."
        ),
        funnel=[
            FunnelStage(stage="Mensagens recebidas", count=842, pct=100.0),
            FunnelStage(stage="Respondidas", count=720, pct=85.5),
            FunnelStage(stage="Agendamentos", count=180, pct=21.4),
            FunnelStage(stage="Confirmados", count=124, pct=14.7),
        ],
        response_time_distribution=[
            ResponseTimeBucket(faixa="< 5min", count=210, color="#10B981"),
            ResponseTimeBucket(faixa="5–30min", count=180, color="#3B82F6"),
            ResponseTimeBucket(faixa="30min–1h", count=140, color="#8B5CF6"),
            ResponseTimeBucket(faixa="1h–4h", count=120, color="#F59E0B"),
            ResponseTimeBucket(faixa="4h–24h", count=130, color="#EF4444"),
            ResponseTimeBucket(faixa="> 24h", count=62, color="#991B1B"),
        ],
        heatmap_periods=[
            HeatmapPeriod(label="Madrug.", values=[0.1, 0.0, 0.2, 0.1, 0.1, 0.3, 0.4]),
            HeatmapPeriod(label="Manhã", values=[4.2, 4.5, 4.1, 4.6, 4.0, 2.1, 1.0]),
            HeatmapPeriod(label="Tarde", values=[5.8, 6.1, 5.9, 6.3, 5.5, 3.2, 1.8]),
            HeatmapPeriod(label="Noite", values=[3.1, 3.4, 3.0, 3.5, 3.8, 2.5, 1.5]),
        ],
        opportunities=[
            Opportunity(
                tag="Lead quente sem follow-up",
                context="Paciente perguntou sobre implante e nunca recebeu retorno.",
                reason="Demonstrou interesse claro e mencionou orçamento.",
                value_brl=4500.0,
                when="há 3 dias",
            ),
        ],
        objections=[
            Objection(label="Preço alto", pct=42.0, count=17, color="#EF4444"),
            Objection(label="Sem convênio", pct=28.0, count=11, color="#F59E0B"),
            Objection(label="Distância", pct=18.0, count=7, color="#3B82F6"),
            Objection(label="Horário", pct=12.0, count=5, color="#8B5CF6"),
        ],
        faqs=[
            FAQ(q="Vocês aceitam parcelamento?", count=14),
            FAQ(q="Atendem por convênio?", count=11),
            FAQ(q="Qual o valor da consulta de avaliação?", count=9),
        ],
        sentiment=[
            SentimentSlice(name="Positivo", value=45, color="#10B981"),
            SentimentSlice(name="Neutro", value=35, color="#6B7280"),
            SentimentSlice(name="Negativo", value=20, color="#EF4444"),
        ],
        benchmarks=[
            BenchmarkMetric(
                metric="Tempo médio de resposta",
                clinic=137.0,
                market=45.0,
                unit="min",
                better="lower",
            ),
            BenchmarkMetric(
                metric="Taxa de conversão",
                clinic=14.7,
                market=22.0,
                unit="%",
                better="higher",
            ),
        ],
    )
