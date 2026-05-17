"""Deterministic metrics computed from an F1 ``ExtractedPayload``.

All functions in this module are **pure**: no I/O, no logging, no DB calls,
no global mutation. They take an ``ExtractedPayload`` (or already-computed
sub-results, for :func:`compute_score`) and return values that drop straight
into the corresponding F3 ``ReportPayload`` sub-models.

See F3 design.md §7 for the spec. The LLM-driven insights (opportunities,
objections, FAQs, sentiment, diagnostic_summary) live elsewhere — this
module owns only the math.

Conventions:

* Group conversations (``is_group=True``) are **excluded everywhere** —
  they distort 1:1 lead funnels.
* Timestamps are interpreted in ``America/Sao_Paulo`` (the clinics are
  Brazilian); weekday/period bucketing depends on local civil time, not UTC.
* Empty payloads return 0 / empty lists / score=0 — never raise.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

from app.modules.reports._keywords import KW_BOOKED, KW_VALUE
from app.modules.reports.schemas import (
    FunnelStage,
    HeatmapPeriod,
    ResponseTimeBucket,
)
from app.modules.whatsapp.schemas import (
    ConversationPayload,
    ExtractedPayload,
    MessagePayload,
)

# ─── Constants ───────────────────────────────────────────────────────────

_TZ: Final[ZoneInfo] = ZoneInfo("America/Sao_Paulo")

# Response-time bucket edges (seconds, upper-exclusive) paired with their
# UI label + hex color from the design system.
_RT_BUCKETS: Final[tuple[tuple[str, int, str], ...]] = (
    ("< 5min", 300, "#FF6B35"),
    ("5–30min", 1800, "#FF6B35"),
    ("30min–1h", 3600, "#E8B33C"),
    ("1h–4h", 14400, "#E8B33C"),
    ("4h–24h", 86400, "#8B3A50"),
    ("> 24h", math.inf, "#5C1D2E"),  # type: ignore[arg-type]
)

# Heatmap period boundaries: (label, hour_start_inclusive, hour_end_exclusive).
_HM_PERIODS: Final[tuple[tuple[str, int, int], ...]] = (
    ("Madrug.", 0, 6),
    ("Manhã", 6, 12),
    ("Tarde", 12, 18),
    ("Noite", 18, 24),
)

# Score-formula weights (must sum to 1.0).
_W_RESPONSE_TIME: Final[float] = 0.35
_W_CONVERSION: Final[float] = 0.30
_W_RESPONSE_RATE: Final[float] = 0.20
_W_VOLUME: Final[float] = 0.15

# Volume normalization endpoints (log-scale interpolation between).
_VOL_FLOOR: Final[int] = 50
_VOL_CEILING: Final[int] = 2000


# ─── Helpers ─────────────────────────────────────────────────────────────


def _non_group_conversations(
    payload: ExtractedPayload,
) -> list[ConversationPayload]:
    """Filter out group chats — they skew every 1:1 metric."""
    return [c for c in payload.conversations if not c.is_group]


def _bucket_index_for_delay(delay_seconds: float) -> int:
    """Return the index into :data:`_RT_BUCKETS` for a positive delay."""
    for idx, (_label, upper, _color) in enumerate(_RT_BUCKETS):
        if delay_seconds < upper:
            return idx
    return len(_RT_BUCKETS) - 1  # safety net; "> 24h" catches everything


# ─── Public API ──────────────────────────────────────────────────────────


def compute_message_count(payload: ExtractedPayload) -> int:
    """Total messages across all non-group conversations."""
    return sum(len(c.messages) for c in _non_group_conversations(payload))


def compute_conversation_count(payload: ExtractedPayload) -> int:
    """Total non-group (1:1) conversations."""
    return len(_non_group_conversations(payload))


def compute_response_time_distribution(
    payload: ExtractedPayload,
) -> list[ResponseTimeBucket]:
    """Distribution of clinic reply delays across 6 buckets.

    For every clinic message (``from_me=True``), we look at the most recent
    *prior* lead message (``from_me=False``) in the same conversation; the
    delay (clinic_ts - lead_ts) feeds into one bucket. Clinic messages with
    no preceding lead message are ignored. Group chats are ignored.
    """
    counts = [0] * len(_RT_BUCKETS)

    for conv in _non_group_conversations(payload):
        # Messages assumed roughly chronological from F1 but we sort to be safe.
        msgs = sorted(conv.messages, key=lambda m: m.ts)
        last_lead_ts: int | None = None
        for msg in msgs:
            if not msg.from_me:
                last_lead_ts = msg.ts
            else:
                if last_lead_ts is None:
                    continue
                delay = msg.ts - last_lead_ts
                if delay < 0:
                    continue
                counts[_bucket_index_for_delay(delay)] += 1
                # Consume the lead — we only want one reply-pair per inbound.
                last_lead_ts = None

    return [
        ResponseTimeBucket(faixa=label, count=counts[idx], color=color)  # type: ignore[arg-type]
        for idx, (label, _upper, color) in enumerate(_RT_BUCKETS)
    ]


def compute_heatmap(payload: ExtractedPayload) -> list[HeatmapPeriod]:
    """4 periods x 7 weekdays of average messages-per-day.

    For each (period, weekday) bucket we sum the messages whose local
    timestamp falls in that bucket and divide by the number of distinct
    calendar dates contributing to it. Empty buckets are 0.0. Values are
    rounded to 1 decimal place. Group chats are ignored.
    """
    # totals[period_idx][weekday] = total messages
    totals: list[list[int]] = [[0] * 7 for _ in _HM_PERIODS]
    # dates[period_idx][weekday] = set of date keys seen
    dates: list[list[set[str]]] = [[set() for _ in range(7)] for _ in _HM_PERIODS]

    for conv in _non_group_conversations(payload):
        for msg in conv.messages:
            local = datetime.fromtimestamp(msg.ts, tz=_TZ)
            weekday = local.weekday()  # 0=Mon..6=Sun, matches "Seg..Dom"
            hour = local.hour
            for p_idx, (_label, h_start, h_end) in enumerate(_HM_PERIODS):
                if h_start <= hour < h_end:
                    totals[p_idx][weekday] += 1
                    dates[p_idx][weekday].add(local.date().isoformat())
                    break

    periods: list[HeatmapPeriod] = []
    for p_idx, (label, _h_start, _h_end) in enumerate(_HM_PERIODS):
        values: list[float] = []
        for wd in range(7):
            n_dates = len(dates[p_idx][wd])
            if n_dates == 0:
                values.append(0.0)
            else:
                values.append(round(totals[p_idx][wd] / n_dates, 1))
        periods.append(HeatmapPeriod(label=label, values=values))  # type: ignore[arg-type]
    return periods


def compute_funnel(payload: ExtractedPayload) -> list[FunnelStage]:
    """5-stage funnel (counts + pct relative to stage 1).

    Stages:

    1. Primeiro contato        — total non-group conversations
    2. Respondidos             — convs with >=1 clinic message
    3. Engajados (3+ msgs)     — convs with >=3 total messages
    4. Receberam info / valor  — clinic ever sent a value/pricing keyword
    5. Agendamento confirmado  — clinic ever sent a booking keyword
    """
    convs = _non_group_conversations(payload)
    n_total = len(convs)

    n_responded = 0
    n_engaged = 0
    n_value = 0
    n_booked = 0

    for conv in convs:
        has_clinic_msg = False
        sent_value_kw = False
        sent_booked_kw = False
        for msg in conv.messages:
            if msg.from_me:
                has_clinic_msg = True
                # Only clinic-side text counts for value/booked keywords.
                if msg.text:
                    if not sent_value_kw and KW_VALUE.search(msg.text):
                        sent_value_kw = True
                    if not sent_booked_kw and KW_BOOKED.search(msg.text):
                        sent_booked_kw = True
        if has_clinic_msg:
            n_responded += 1
        if len(conv.messages) >= 3:
            n_engaged += 1
        if sent_value_kw:
            n_value += 1
        if sent_booked_kw:
            n_booked += 1

    def _pct(count: int) -> float:
        if n_total == 0:
            return 0.0
        return round((count / n_total) * 100, 1)

    return [
        FunnelStage(stage="Primeiro contato", count=n_total, pct=_pct(n_total)),
        FunnelStage(stage="Respondidos", count=n_responded, pct=_pct(n_responded)),
        FunnelStage(stage="Engajados (3+ msgs)", count=n_engaged, pct=_pct(n_engaged)),
        FunnelStage(stage="Receberam info / valor", count=n_value, pct=_pct(n_value)),
        FunnelStage(stage="Agendamento confirmado", count=n_booked, pct=_pct(n_booked)),
    ]


def _volume_normalized(message_count: int) -> float:
    """Map total message volume to a 0-100 score on a log scale.

    * < 50 messages → 0 (too little signal to evaluate).
    * >= 2000 messages → 100 (saturated; high-volume clinic).
    * In between → ``log(n/floor) / log(ceiling/floor) * 100``.
    """
    if message_count < _VOL_FLOOR:
        return 0.0
    if message_count >= _VOL_CEILING:
        return 100.0
    return (
        math.log(message_count / _VOL_FLOOR)
        / math.log(_VOL_CEILING / _VOL_FLOOR)
        * 100
    )


def compute_score(
    message_count: int,
    response_time_distribution: list[ResponseTimeBucket],
    funnel: list[FunnelStage],
) -> int:
    """Composite 0-100 health score (see design.md §7 for the formula).

    * 35% — share of clinic replies under 30 min (buckets 0 + 1).
    * 30% — last funnel stage pct, normalized by ×4 capped at 100.
    * 20% — funnel stage 2 pct (response rate, already 0-100).
    * 15% — log-scale volume score.
    """
    # Response-time component
    total_responses = sum(b.count for b in response_time_distribution)
    if total_responses == 0:
        pct_fast = 0.0
    else:
        fast_responses = (
            response_time_distribution[0].count
            + response_time_distribution[1].count
        )
        pct_fast = (fast_responses / total_responses) * 100
    response_time_score = max(0.0, min(100.0, pct_fast))

    # Conversion + response-rate components from the funnel
    if len(funnel) >= 5:
        pct_last = funnel[-1].pct
        pct_stage_2 = funnel[1].pct
    else:
        pct_last = 0.0
        pct_stage_2 = 0.0
    conversion_score = max(0.0, min(100.0, pct_last * 4))
    response_rate_score = max(0.0, min(100.0, pct_stage_2))

    # Volume component
    volume_score = _volume_normalized(message_count)

    total = (
        _W_RESPONSE_TIME * response_time_score
        + _W_CONVERSION * conversion_score
        + _W_RESPONSE_RATE * response_rate_score
        + _W_VOLUME * volume_score
    )
    return int(round(total))


__all__ = [
    "compute_message_count",
    "compute_conversation_count",
    "compute_response_time_distribution",
    "compute_heatmap",
    "compute_funnel",
    "compute_score",
]


# Silence unused-import warnings for re-exports used only as type hints
# in the public signatures (MessagePayload).
_ = MessagePayload
