"""Shared types for WhatsApp provider adapters.

These are framework-agnostic — provider adapters (uazapi today, possibly
Baileys/Cloud API tomorrow) map their wire format to these shapes.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSession:
    """Session created by the provider — token + QR ready to display."""

    session_token: str       # uazapi instance_token
    qr_base64: str           # PNG already base64-encoded (no `data:image/png;base64,` prefix)


@dataclass(frozen=True)
class Chat:
    wa_chatid: str
    contact_name: str
    is_group: bool
    last_message_at: int | None   # unix seconds


@dataclass(frozen=True)
class Message:
    ts: int                       # unix seconds
    from_me: bool
    type: str                     # "text" | "image" | "audio" | ... — M1 keeps only "text"
    text: str
