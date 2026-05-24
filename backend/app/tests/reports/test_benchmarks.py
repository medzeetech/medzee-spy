"""Unit tests for :mod:`app.modules.reports.benchmarks` (F3 T19).

The benchmarks module is a tiny lookup table + a factory that fills in
the clinic's measured values without mutating the underlying template.
The tests here pin:

* The four metric rows are emitted in the documented order.
* The market values come from the segment-specific template (saude vs
  odonto vs outro).
* An unknown segment falls back to the ``outro`` template.
* The template dict is never mutated — call ``build_benchmarks`` twice
  and the templates' ``clinic=0`` baseline must still hold.
"""
from __future__ import annotations

from app.modules.reports.benchmarks import (
    _BENCHMARKS_BY_SEGMENT,
    build_benchmarks,
)


_EXPECTED_METRICS = (
    "Tempo 1ª resposta",
    "Taxa de conversão",
    "Mensagens sem resposta",
    "Follow-up pós-orçamento",
)


def test_build_benchmarks_saude() -> None:
    """Saude template fills in clinic values without changing market."""
    result = build_benchmarks(
        clinic_segment="saude",
        clinic_response_time_h=4.4,
        clinic_conversion_pct=15.0,
        clinic_unanswered_pct=7.0,
        clinic_followup_pct=40.0,
    )
    assert len(result) == 4
    # First metric: response-time row.
    assert result[0].metric == "Tempo 1ª resposta"
    assert result[0].clinic == 4.4
    # Market value from saude template.
    expected_market = _BENCHMARKS_BY_SEGMENT["saude"][0].market
    assert result[0].market == expected_market
    # Clinic values mapped in declaration order.
    assert [r.clinic for r in result] == [4.4, 15.0, 7.0, 40.0]


def test_build_benchmarks_odonto_different_market() -> None:
    """Odonto markets differ from saude — the lookup actually branches."""
    saude = build_benchmarks(
        clinic_segment="saude",
        clinic_response_time_h=1.0,
        clinic_conversion_pct=20.0,
        clinic_unanswered_pct=5.0,
        clinic_followup_pct=50.0,
    )
    odonto = build_benchmarks(
        clinic_segment="odonto",
        clinic_response_time_h=1.0,
        clinic_conversion_pct=20.0,
        clinic_unanswered_pct=5.0,
        clinic_followup_pct=50.0,
    )

    saude_markets = [r.market for r in saude]
    odonto_markets = [r.market for r in odonto]
    assert saude_markets != odonto_markets
    # At least the response-time benchmark must differ (0.8h vs 0.5h).
    assert saude[0].market != odonto[0].market


def test_build_benchmarks_outro_fallback() -> None:
    """Unknown segment string transparently maps to the ``outro`` template."""
    result = build_benchmarks(
        clinic_segment="not-a-real-segment",
        clinic_response_time_h=2.0,
        clinic_conversion_pct=10.0,
        clinic_unanswered_pct=15.0,
        clinic_followup_pct=30.0,
    )
    expected_markets = [m.market for m in _BENCHMARKS_BY_SEGMENT["outro"]]
    assert [r.market for r in result] == expected_markets


def test_market_values_immutable() -> None:
    """Repeated calls do not mutate the template's clinic=0 baseline."""
    # Drive a variety of clinic-side numbers through every supported segment.
    for seg in ("saude", "odonto", "outro", "ghost-segment"):
        build_benchmarks(
            clinic_segment=seg,
            clinic_response_time_h=99.0,
            clinic_conversion_pct=88.0,
            clinic_unanswered_pct=77.0,
            clinic_followup_pct=66.0,
        )

    # Templates are still pristine — clinic baseline is 0 for every row.
    for seg, rows in _BENCHMARKS_BY_SEGMENT.items():
        for row in rows:
            assert row.clinic == 0, (
                f"template for segment {seg!r} was mutated: {row}"
            )


def test_metric_order_preserved() -> None:
    """All segments emit the four metrics in the documented order."""
    for seg in ("saude", "odonto", "outro"):
        result = build_benchmarks(
            clinic_segment=seg,
            clinic_response_time_h=1.0,
            clinic_conversion_pct=1.0,
            clinic_unanswered_pct=1.0,
            clinic_followup_pct=1.0,
        )
        assert tuple(r.metric for r in result) == _EXPECTED_METRICS
