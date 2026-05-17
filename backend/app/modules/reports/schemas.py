"""Pydantic models for the reports module (F3 design § 4).

The payload models are intentionally aligned 1:1 with the field names + shapes
already consumed by the frontend mock in ``frontend/src/data/reportData.js`` —
fewer translation layers, fewer bugs.

Layout:

* :class:`ReportStatus` — lifecycle enum (``pending`` → ``generating`` →
  ``completed`` | ``partial`` | ``failed``).
* Sub-models (one per UI section) — ``FunnelStage``, ``ResponseTimeBucket``,
  ``HeatmapPeriod``, ``Opportunity``, ``Objection``, ``FAQ``, ``SentimentSlice``,
  ``BenchmarkMetric``.
* :class:`ReportPayload` — the full snapshot stored in
  ``reports.payload jsonb`` and returned by the API on success.
* :class:`ReportResponse` / :class:`ReportSummary` / :class:`ReportListResponse`
  — HTTP envelopes for the REST endpoints (REPORT-16..18).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ReportStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


# ─── Sub-models (UI sections) ─────────────────────────────────────────


class FunnelStage(BaseModel):
    stage: str
    count: int
    pct: float = Field(ge=0, le=100)


_RESPONSE_TIME_FAIXAS = Literal[
    "< 5min", "5–30min", "30min–1h", "1h–4h", "4h–24h", "> 24h"
]


class ResponseTimeBucket(BaseModel):
    faixa: _RESPONSE_TIME_FAIXAS
    count: int
    color: str  # hex


_HEATMAP_LABELS = Literal["Madrug.", "Manhã", "Tarde", "Noite"]


class HeatmapPeriod(BaseModel):
    label: _HEATMAP_LABELS
    values: list[float] = Field(min_length=7, max_length=7)


class Opportunity(BaseModel):
    tag: str
    context: str
    reason: str
    value_brl: float = Field(ge=0)
    when: str


class Objection(BaseModel):
    label: str
    pct: float = Field(ge=0, le=100)
    count: int
    color: str


class FAQ(BaseModel):
    q: str
    count: int


_SENTIMENT_NAMES = Literal["Positivo", "Neutro", "Negativo"]


class SentimentSlice(BaseModel):
    name: _SENTIMENT_NAMES
    value: int = Field(ge=0, le=100)
    color: str


class BenchmarkMetric(BaseModel):
    metric: str
    clinic: float
    market: float
    unit: str
    better: Literal["lower", "higher"]


# ─── Payload ──────────────────────────────────────────────────────────


_HEATMAP_DAYS_DEFAULT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


class ReportPayload(BaseModel):
    """Snapshot the frontend renders across the 9 dashboard sections."""

    # Top-level metrics
    message_count: int
    conversation_count: int
    period_days: int = 30
    score: int = Field(ge=0, le=100)
    clinic_segment: Literal["saude", "odonto", "outro"]

    # LLM-generated diagnostic
    diagnostic_summary: str

    # Deterministic metrics
    funnel: list[FunnelStage]
    response_time_distribution: list[ResponseTimeBucket]
    heatmap_days: list[str] = Field(default_factory=lambda: list(_HEATMAP_DAYS_DEFAULT))
    heatmap_periods: list[HeatmapPeriod]

    # LLM-generated insights
    opportunities: list[Opportunity]
    objections: list[Objection]
    faqs: list[FAQ]
    sentiment: list[SentimentSlice]

    # Hardcoded per segment + honest asterisk in the UI
    benchmarks: list[BenchmarkMetric]


# ─── HTTP responses ───────────────────────────────────────────────────


class ReportResponse(BaseModel):
    id: UUID
    status: ReportStatus
    payload: ReportPayload | None = None
    error_code: str | None = None
    message_count: int | None = None
    score: int | None = None
    created_at: datetime
    generated_at: datetime | None = None


class ReportSummary(BaseModel):
    """Lightweight list-view item (no payload)."""

    id: UUID
    status: ReportStatus
    message_count: int | None = None
    score: int | None = None
    period_days: int | None = None
    created_at: datetime


class ReportListResponse(BaseModel):
    items: list[ReportSummary]
    total: int
    page: int = 1
    page_size: int = 20
