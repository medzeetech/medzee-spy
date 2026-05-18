"""WhatsApp provider layer.

Exports:
    - ``WhatsAppProvider`` — structural Protocol every adapter must satisfy.
    - ``get_provider()`` — lazy factory returning the configured adapter
      (currently :class:`app.clients.whatsapp.uazapi.UazapiProvider`).

The factory uses a deferred import so the heavy `httpx`-backed adapter is
only instantiated when actually needed, and so this module remains
importable even while the adapter file is being introduced in parallel.

Shared dataclasses (``ProviderSession``, ``Chat``, ``Message``) live in
:mod:`.types` and the error hierarchy in :mod:`.errors`.
"""
from __future__ import annotations

from typing import Protocol

from app.clients.whatsapp.types import Chat, Message, ProviderSession


class WhatsAppProvider(Protocol):
    """Abstract WhatsApp provider contract (see design § 4.2)."""

    async def create_session(self) -> ProviderSession:
        ...

    async def register_webhook(
        self, session_token: str, callback_url: str
    ) -> None:
        ...

    async def refresh_qr(self, session_token: str) -> str:
        """Returns a fresh ``qr_base64`` for the given session."""
        ...

    async def get_status(self, session_token: str) -> dict:
        """Health-check / webhook fallback."""
        ...

    async def list_chats(
        self, session_token: str, limit: int = 100, offset: int = 0
    ) -> tuple[list[Chat], bool]:
        """Returns ``(chats, has_more)``."""
        ...

    async def list_messages(
        self,
        session_token: str,
        chat_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Message], bool, int]:
        """Returns ``(messages, has_more, next_offset)``."""
        ...

    async def get_chat_totals(self, session_token: str) -> dict:
        """Returns the raw uazapi /chat/find payload (for totalChatsStats)."""
        ...

    async def request_history_sync(
        self, session_token: str, chat_jid: str, count: int = 100
    ) -> None:
        """Triggers uazapi server-side sync of chat history.

        Without this, ``list_messages`` returns empty for fresh instances.
        """
        ...

    async def get_chat_details(self, session_token: str, number: str) -> dict:
        """Rich contact details including LID↔JID mapping (wa_chatlid)."""
        ...

    async def get_webhook_errors(self, session_token: str) -> list[dict]:
        """Diagnostic: list recent webhook delivery errors."""
        ...

    async def disconnect(self, session_token: str) -> None:
        ...

    async def delete_instance(self, session_token: str) -> None:
        """Destroy the instance entry and free the provider's device slot."""
        ...


def get_provider() -> WhatsAppProvider:
    """Return the configured provider instance.

    Imports lazily so that:
      1. This module stays cheap to import (no eager ``httpx`` init).
      2. ``WhatsAppProvider`` / static typing keeps working even if
         ``uazapi.py`` hasn't been written yet.
    """
    from app.clients.whatsapp.uazapi import UazapiProvider  # noqa: WPS433

    return UazapiProvider()


__all__ = ["WhatsAppProvider", "get_provider"]
