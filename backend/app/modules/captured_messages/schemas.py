"""Pydantic models for the captured_messages module (F4 design § 4).

Layout:

* :class:`CapturedMessage` — full row as it lives in the DB (read path).
* :class:`CapturedMessageInsert` — normalized payload from the webhook
  parser (write path; no ``id``/``created_at`` because those are
  DB-assigned).
* :class:`WhatsappStatusResponse` — body of ``GET /api/whatsapp/status``.
* :class:`GenerateReportRequest` / :class:`GenerateReportResponse` —
  request and response of ``POST /api/reports/generate``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


# Tipos de mensagem que o parser do webhook reconhece. Anything else cai
# em "other" (count-only, sem text útil pra LLM).
MessageType = Literal[
    "text", "image", "audio", "video", "sticker", "document", "other"
]


# Períodos permitidos pro relatório on-demand (F4-11).
ReportPeriodDays = Literal[7, 15, 30, 60]


# ─── Row models ─────────────────────────────────────────────────────


class CapturedMessage(BaseModel):
    """Full row as stored in ``medzee_spy.captured_messages``."""

    id: UUID
    user_id: UUID
    whatsapp_session_id: UUID
    wa_chatid: str
    contact_name: str | None = None
    ts: datetime
    is_from_me: bool
    message_type: str = "text"
    text: str | None = None
    raw_message_id: str | None = None
    created_at: datetime


class CapturedMessageInsert(BaseModel):
    """Normalized payload produced by the uazapi webhook parser.

    No ``id`` / ``created_at`` because the DB assigns those. The
    repository ``insert_many`` consumes this shape directly.
    """

    user_id: UUID
    whatsapp_session_id: UUID
    wa_chatid: str
    contact_name: str | None = None
    ts: datetime
    is_from_me: bool
    message_type: MessageType = "text"
    text: str | None = None
    raw_message_id: str | None = None


# ─── HTTP responses ─────────────────────────────────────────────────


class WhatsappStatusResponse(BaseModel):
    """Body of ``GET /api/whatsapp/status`` (F4-14)."""

    connected: bool
    session_id: UUID | None = None
    connected_since: datetime | None = None
    message_count: int = 0
    conversation_count: int = 0  # distinct wa_chatid
    last_message_at: datetime | None = None


class GenerateReportRequest(BaseModel):
    """Body of ``POST /api/reports/generate`` (F4-11)."""

    period_days: ReportPeriodDays = 30


class GenerateReportResponse(BaseModel):
    """Response of ``POST /api/reports/generate`` (F4-11)."""

    report_id: UUID
    status: Literal["generating"] = "generating"


__all__ = [
    "CapturedMessage",
    "CapturedMessageInsert",
    "WhatsappStatusResponse",
    "GenerateReportRequest",
    "GenerateReportResponse",
    "MessageType",
    "ReportPeriodDays",
]
