"""Pydantic schemas for the Chrome extension ingestion module (F8 / §4.2).

Wire shapes for the five extension endpoints:

* ``POST /api/extension/pair`` — :class:`ExtensionPairRequest` →
  :class:`ExtensionPairResponse`
* ``POST /api/extension/messages`` — :class:`ExtensionMessageBatch`
* ``GET  /api/extension/status``   — :class:`ExtensionStatusResponse`
* ``POST /api/extension/telemetry`` — :class:`ExtensionTelemetryEvent`
* ``POST /api/extension/mobile-lead`` — :class:`MobileRedirectLeadCreate`

Plus :class:`ExtensionPairingTokenResponse` used by
``POST /api/auth/me/extension-pairing-token`` (T6).

Design contracts enforced here:

* :class:`ExtensionMessage` and :class:`ExtensionTelemetryEvent` both set
  ``model_config = ConfigDict(extra="forbid")`` so unknown keys are
  rejected with HTTP 422. For telemetry that's the **PII guard** (CHX-16) —
  callers cannot accidentally send ``text``, ``wa_chatid``, ``contact_name``
  or ``msg_id`` even if the extension is buggy.
* ``ExtensionMessageBatch.batch_index`` is ``>= 0`` and ``total_batches >= 1``;
  the ingest service uses these to detect the last batch and fire the F3
  worker.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# Allowed message type taxonomy — kept in sync with
# ``captured_messages.schemas.MessageType`` (F4) so the ingest service can
# pass values through 1:1 into ``CapturedMessageInsert``.
ExtensionMessageType = Literal[
    "text", "image", "audio", "video", "sticker", "document", "other"
]


# Allowed telemetry events (CHX-16). Keep in sync with the CHECK constraint
# on ``medzee_spy.extension_telemetry.event``.
ExtensionTelemetryEventName = Literal[
    "collect_failed",
    "collect_started",
    "collect_completed",
    "wa_needs_login",
    "service_worker_woke",
    "pairing_failed",
]


# ─── Batch / messages ──────────────────────────────────────────────────


class ExtensionMessage(BaseModel):
    """Single message in an extension batch (CHX-04).

    ``extra='forbid'`` keeps the wire shape tight: the extension is the
    only producer, so any unknown field is almost certainly a bug we want
    to surface as a 422 rather than silently drop.
    """

    model_config = ConfigDict(extra="forbid")

    wa_chatid: str
    wa_msg_id: str
    ts: datetime
    is_from_me: bool
    message_type: ExtensionMessageType = "text"
    text: str | None = None
    contact_name: str | None = None
    wa_is_group: bool = False


class ExtensionMessageBatch(BaseModel):
    """Envelope of one chunk of an extension collection run."""

    batch_id: str
    batch_index: int = Field(ge=0)
    total_batches: int = Field(ge=1)
    extension_version: str
    messages: list[ExtensionMessage]


# ─── Pair / status ─────────────────────────────────────────────────────


class ExtensionPairRequest(BaseModel):
    """Body of ``POST /api/extension/pair``.

    The ``pairing_token`` JWT is emitted by ``/api/auth/signup`` (T6) with
    ``typ='extension_pairing'`` and a short TTL.
    """

    pairing_token: str
    extension_install_id: str
    extension_version: str | None = None
    user_agent: str | None = None


class ExtensionPairResponse(BaseModel):
    refresh_token: str
    user_id: UUID


class ExtensionStatusResponse(BaseModel):
    """Body of ``GET /api/extension/status`` — used by frontend polling."""

    paired: bool
    last_collection_at: datetime | None = None
    last_collection_message_count: int = 0
    extension_min_version: str = "1.0.0"


# ─── Telemetry ─────────────────────────────────────────────────────────


class ExtensionTelemetryEvent(BaseModel):
    """No-PII telemetry event (CHX-16).

    ``extra='forbid'`` is load-bearing: it rejects any payload that
    accidentally carries ``text``, ``wa_chatid``, ``contact_name`` or
    ``msg_id`` — those would be a privacy regression. The matching unit
    test in ``test_schemas.py`` locks this guard in place.
    """

    model_config = ConfigDict(extra="forbid")

    event: ExtensionTelemetryEventName
    extension_version: str
    reason: str | None = None
    chats_total: int | None = None
    chats_processed: int | None = None
    duration_ms: int | None = None
    ua: str | None = None


# ─── Auth token re-emission (CHX-15) ───────────────────────────────────


class ExtensionPairingTokenResponse(BaseModel):
    """Body of ``POST /api/auth/me/extension-pairing-token`` (T6).

    Returned to the frontend when a logged-in user needs a fresh
    short-lived pairing token to hand off to the extension.
    """

    extension_pairing_token: str


# ─── Mobile redirect leads ─────────────────────────────────────────────


class MobileRedirectLeadCreate(BaseModel):
    """Body of ``POST /api/extension/mobile-lead`` (no auth, anon insert).

    Captured on the mobile block screen when a user enters their email so
    we can mail them the desktop link. ``email`` uses Pydantic's
    :class:`EmailStr` (``email-validator`` is already a project dep).
    """

    email: EmailStr
    user_agent: str | None = None
    source_url: str | None = None


__all__ = [
    "ExtensionMessage",
    "ExtensionMessageBatch",
    "ExtensionMessageType",
    "ExtensionPairRequest",
    "ExtensionPairResponse",
    "ExtensionStatusResponse",
    "ExtensionTelemetryEvent",
    "ExtensionTelemetryEventName",
    "ExtensionPairingTokenResponse",
    "MobileRedirectLeadCreate",
]
