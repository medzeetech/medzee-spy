"""Schemas + enums for the WhatsApp module.

- `CreateSessionResponse` — public response for POST /sessions
- `UazapiWebhookPayload` — incoming webhook from uazapi
- `ExtractedPayload` + sub-models — internal cache of the 30d extract (never
  serialized to public clients; F2 consumes it via the service)
- `SSEEvent` — envelope passed through asyncio queues to SSE subscribers
- `SessionStatus` — finite-state enum used in DB + memory + logs
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    PENDING = "pending"
    CONNECTED = "connected"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    CONSUMED = "consumed"
    FAILED = "failed"
    EXPIRED = "expired"


# Statuses past which a session is effectively done: the SSE stream closes,
# cancel is a no-op, and the TTL expire loop skips them. EXTRACTED is included
# because once the payload is cached the session waits passively for F2 to
# consume or for TTL — no further transitions a client triggers.
TERMINAL_STATUSES: frozenset[SessionStatus] = frozenset({
    SessionStatus.EXTRACTED,
    SessionStatus.CONSUMED,
    SessionStatus.FAILED,
    SessionStatus.EXPIRED,
})


class CreateSessionResponse(BaseModel):
    session_id: UUID
    qr: str                       # base64 PNG, no prefix
    status: Literal["pending"]


class UazapiWebhookPayload(BaseModel):
    event: str                    # "connection" | "messages" | ...
    instance: str
    data: dict[str, Any] = Field(default_factory=dict)


class MessagePayload(BaseModel):
    ts: int
    from_me: bool
    type: str
    text: str


class ConversationPayload(BaseModel):
    wa_chatid: str
    contact_name: str
    is_group: bool
    last_message_at: int | None
    messages: list[MessagePayload]


class ExtractedPayload(BaseModel):
    message_count: int
    conversation_count: int
    conversations: list[ConversationPayload]
    partial: bool = False         # True if the hard timeout cut the extract short


@dataclass(frozen=True)
class SSEEvent:
    """In-memory envelope for events flowing through the per-session pub/sub.

    Serialized to the wire as ``event: <name>\\ndata: <json(data)>\\n\\n``.
    """

    name: str                     # qr-updated | connected | extracting | extracted | failed | expired
    data: dict[str, Any]
