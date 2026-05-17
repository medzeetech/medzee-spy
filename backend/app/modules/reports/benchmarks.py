"""Hardcoded sector benchmarks by clinic specialty (F3 design § 8).

The values below are *estimates* compiled from publicly available sector
research and internal consultancy averages — they are **not** measured from
the Medzee fleet itself:

* Sebrae 2023 — "Pesquisa de Atendimento em Clínicas e Consultórios".
* RD Station Marketing Pulse 2024 — response-time / conversion benchmarks.
* Médias setoriais consultor — internal Medzee advisory averages.

The UI surfaces each row with an asterisk + tooltip explaining the source
("estimativa baseada em pesquisas setoriais da rede Medzee") — see
REPORT-22.

This module exposes:

* ``_BENCHMARKS_BY_SEGMENT`` — the immutable template table (private; do
  not mutate at runtime — :func:`build_benchmarks` always returns copies).
* :func:`build_benchmarks` — factory that returns a list of
  :class:`BenchmarkMetric` with the clinic's measured values filled in.
"""
from __future__ import annotations

from .schemas import BenchmarkMetric

# Hardcoded estimates from setor pesquisas (Sebrae 2023, RD Station 2024).
# UI displays with asterisk explaining "estimativa baseada em pesquisas
# setoriais da rede Medzee" — see REPORT-22.
_BENCHMARKS_BY_SEGMENT: dict[str, list[BenchmarkMetric]] = {
    "saude": [
        BenchmarkMetric(metric="Tempo 1ª resposta",       clinic=0, market=0.8,  unit="h", better="lower"),
        BenchmarkMetric(metric="Taxa de conversão",       clinic=0, market=24.0, unit="%", better="higher"),
        BenchmarkMetric(metric="Mensagens sem resposta",  clinic=0, market=6,    unit="%", better="lower"),
        BenchmarkMetric(metric="Follow-up pós-orçamento", clinic=0, market=58,   unit="%", better="higher"),
    ],
    "odonto": [
        BenchmarkMetric(metric="Tempo 1ª resposta",       clinic=0, market=0.5,  unit="h", better="lower"),
        BenchmarkMetric(metric="Taxa de conversão",       clinic=0, market=30.0, unit="%", better="higher"),
        BenchmarkMetric(metric="Mensagens sem resposta",  clinic=0, market=4,    unit="%", better="lower"),
        BenchmarkMetric(metric="Follow-up pós-orçamento", clinic=0, market=65,   unit="%", better="higher"),
    ],
    "outro": [
        BenchmarkMetric(metric="Tempo 1ª resposta",       clinic=0, market=1.2,  unit="h", better="lower"),
        BenchmarkMetric(metric="Taxa de conversão",       clinic=0, market=20.0, unit="%", better="higher"),
        BenchmarkMetric(metric="Mensagens sem resposta",  clinic=0, market=8,    unit="%", better="lower"),
        BenchmarkMetric(metric="Follow-up pós-orçamento", clinic=0, market=50,   unit="%", better="higher"),
    ],
}


def build_benchmarks(
    *,
    clinic_segment: str,
    clinic_response_time_h: float,
    clinic_conversion_pct: float,
    clinic_unanswered_pct: float,
    clinic_followup_pct: float,
) -> list[BenchmarkMetric]:
    """Return benchmarks with clinic values filled in.

    Falls back to 'outro' segment if clinic_segment is not in the map.
    Each returned BenchmarkMetric is a fresh copy (does not mutate the template).
    """
    seg = clinic_segment if clinic_segment in _BENCHMARKS_BY_SEGMENT else "outro"
    template = _BENCHMARKS_BY_SEGMENT[seg]
    clinic_values = [
        clinic_response_time_h, clinic_conversion_pct,
        clinic_unanswered_pct, clinic_followup_pct,
    ]
    return [
        m.model_copy(update={"clinic": v})
        for m, v in zip(template, clinic_values, strict=True)
    ]
