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


# F8: origem da captura. ``extension`` vem do Chrome extension push (ingest
# direto via API autenticada). ``webhook`` permanece no enum apenas pra ler
# rows legadas históricas (capturadas pelo provedor SaaS antigo antes do
# cutover). Inserts novos sempre usam ``extension``. CHECK constraint em DB
# garante esses dois únicos valores.
MessageSource = Literal["webhook", "extension"]


# Períodos permitidos pro relatório on-demand (F4-11, legado window_days).
ReportPeriodDays = Literal[7, 15, 30, 60]

# F5: estratégia de coleta. ``last_n_per_chat`` é o default —
# pega as últimas N msgs de cada conversa, sem janela temporal.
# ``window_days`` mantido pra compat com clientes legados.
ReportMode = Literal["last_n_per_chat", "window_days"]

# F5: valores permitidos pra n_per_chat. Limitado pra controlar custo LLM:
# 30 chats × 50 msgs = 1.500 linhas no contexto, ainda confortável.
ReportNPerChat = Literal[10, 20, 30, 50]


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
    source: MessageSource = "webhook"
    # F8 — batch_id da coleta (NULL pra rows pre-f8_4). Worker filtra
    # por esse campo pra isolar relatórios entre coletas distintas.
    batch_id: str | None = None
    created_at: datetime


class CapturedMessageInsert(BaseModel):
    """Normalized payload produced by the extension ingest endpoint.

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
    source: MessageSource = "webhook"
    # F8 — UUID v4 gerado pelo wa-collector, único por execução de coleta.
    # Todos os batches da mesma "Gerar relatório" compartilham o mesmo
    # batch_id. Persistido em captured_messages e usado pelo worker pra
    # filtrar dados isoladamente por coleta.
    batch_id: str | None = None


# ─── HTTP responses ─────────────────────────────────────────────────


class WhatsappStatusResponse(BaseModel):
    """Body of ``GET /api/whatsapp/status`` (F4-14)."""

    connected: bool
    session_id: UUID | None = None
    connected_since: datetime | None = None
    message_count: int = 0
    conversation_count: int = 0  # distinct wa_chatid
    last_message_at: datetime | None = None
    # Status real da row em `medzee_spy.whatsapp_sessions` (pending |
    # connected | extracting | extracted | consumed | failed | expired |
    # disconnected). Frontend usa pra diferenciar 3 estados que pareciam
    # iguais antes:
    #   - null: usuário nunca conectou WhatsApp
    #   - consumed/disconnected/failed/expired: já conectou antes mas
    #     sessão terminou — UX deve oferecer "Reconectar"
    #   - connected/extracting/extracted: WhatsApp ativo
    #   - pending: scan QR em andamento
    db_status: str | None = None
    # ISO timestamp da última atualização da row. Usado pra exibir
    # "última conexão em X" quando user tem histórico mas não está ativo.
    last_seen_at: datetime | None = None


class GenerateReportRequest(BaseModel):
    """Body of ``POST /api/reports/generate`` (F4-11 + F5).

    Default novo (F5): ``mode='last_n_per_chat'``, ``n_per_chat=30``.
    Gera relatório sempre — mesmo com sample pequena.

    Compat: clientes antigos podem mandar só ``period_days=N``; nesse
    caso o backend usa ``mode='window_days'`` automaticamente.
    """

    mode: ReportMode = "last_n_per_chat"
    n_per_chat: ReportNPerChat = 30
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
    "MessageSource",
    "ReportPeriodDays",
    "ReportMode",
    "ReportNPerChat",
]
