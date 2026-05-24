"""Extension adapter — Strategy no-op for the Chrome MV3 ingestion path.

F8 / D11. When ``WHATSAPP_PROVIDER=extension`` the WhatsApp data lives in
the user's browser: the Chrome extension reads ``web.whatsapp.com`` via
wa-js and POSTs batches to ``/api/extension/*``. The backend never holds
a uazapi-style session/QR/instance, so every method in the
:class:`app.clients.whatsapp.WhatsAppProvider` Protocol that maps to a
uazapi REST call raises :class:`ProviderNotApplicable`.

``get_status`` is the only method with a meaningful return — it tells
callers which provider is wired so legacy health-check sites can detect
the F8 cutover without 500-ing.
"""
from __future__ import annotations

from app.clients.whatsapp.errors import ProviderNotApplicable
from app.clients.whatsapp.types import Chat, Message, ProviderSession


class ExtensionProvider:
    """WhatsAppProvider adapter for the F8 Chrome extension flow.

    Server-side session lifecycle is owned by the extension itself
    (pairing token → refresh token, see ``app.modules.extension``); this
    adapter exists only so callers that hold a ``WhatsAppProvider``
    reference can short-circuit cleanly via ``ProviderNotApplicable``.
    """

    async def create_session(self) -> ProviderSession:
        raise ProviderNotApplicable(
            "ExtensionProvider does not create server-side sessions"
        )

    async def register_webhook(
        self, session_token: str, callback_url: str
    ) -> None:
        raise ProviderNotApplicable(
            "ExtensionProvider does not register webhooks"
        )

    async def refresh_qr(self, session_token: str) -> str:
        raise ProviderNotApplicable(
            "ExtensionProvider does not issue QR codes"
        )

    async def get_status(self, session_token: str) -> dict:
        return {"provider": "extension"}

    async def list_chats(
        self, session_token: str, limit: int = 100, offset: int = 0
    ) -> tuple[list[Chat], bool]:
        raise ProviderNotApplicable(
            "ExtensionProvider does not list chats server-side"
        )

    async def list_messages(
        self,
        session_token: str,
        chat_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Message], bool, int]:
        raise ProviderNotApplicable(
            "ExtensionProvider does not list messages server-side"
        )

    async def get_chat_totals(self, session_token: str) -> dict:
        raise ProviderNotApplicable(
            "ExtensionProvider does not expose chat totals"
        )

    async def request_history_sync(
        self, session_token: str, chat_jid: str, count: int = 100
    ) -> None:
        raise ProviderNotApplicable(
            "ExtensionProvider does not trigger history sync"
        )

    async def get_chat_details(self, session_token: str, number: str) -> dict:
        raise ProviderNotApplicable(
            "ExtensionProvider does not expose chat details"
        )

    async def get_webhook_errors(self, session_token: str) -> list[dict]:
        raise ProviderNotApplicable(
            "ExtensionProvider has no webhook delivery to diagnose"
        )

    async def disconnect(self, session_token: str) -> None:
        raise ProviderNotApplicable(
            "ExtensionProvider does not manage server-side connections"
        )

    async def delete_instance(self, session_token: str) -> None:
        raise ProviderNotApplicable(
            "ExtensionProvider does not own provider instances"
        )
