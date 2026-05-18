"""Uazapi REST adapter — only file in the codebase that talks to uazapi.com.

Maps the `WhatsAppProvider` Protocol (see design § 4.2) onto uazapi's HTTP
endpoints (see design § 4.3). All non-2xx and network failures funnel through
`_raise_for_response` / except-blocks into the `UazapiError` hierarchy so
callers never see raw `httpx` exceptions.
"""
from __future__ import annotations

import asyncio
import logging
import time
from types import TracebackType
from typing import Any, Awaitable, Callable
from uuid import uuid4

import httpx

from app.clients.whatsapp.errors import (
    UazapiBanned,
    UazapiQrExpired,
    UazapiTimeout,
    UazapiUnauthorized,
    UazapiUnavailable,
    UazapiUnknown,
)
from app.clients.whatsapp.types import Chat, Message, ProviderSession
from app.core.config import settings

logger = logging.getLogger(__name__)


_PROVIDER_CODE_BANNED = 463

# B3 fix (F3 §REPORT-15): uazapi free returns 500 on /chat/find right
# after connect because the history sync is still in flight. The original
# (2,5,12)s budget = ~19s was way too tight — empiric measurement on free
# tier shows the sync can take 60-120s. Bumped to (10,30,60,120)s so the
# retry budget ≈ 220s. 4xx propagates immediately (not transient). Only
# applied to the heavy data-pulling ops (list_chats / list_messages) —
# create/connect/delete stay on a single attempt.
# Retry budget AJUSTADO pós-experiência F4-on-demand: o budget anterior
# (15/30/60/120/180/180 = 585s) trava o usuário no spinner. Pro F1 auto-extract
# o tempo é ok (background, não bloqueia UX), mas o /generate on-demand é
# síncrono na percepção do usuário. Compromisso: (5/10/30/60) = 105s — cobre
# blips transitórios + 1 ciclo de uazapi history sync, mas falha rápido
# quando uazapi tá realmente off. pull_history aplica timeout absoluto de
# 3min em cima disso pra garantir UX.
_RETRY_DELAYS_S: tuple[float, ...] = (5.0, 10.0, 30.0, 60.0)


async def _retry_5xx(
    call: Callable[[], Awaitable[Any]], *, op: str, **log_extra: Any
) -> Any:
    """Run ``call()``; retry on ``UazapiUnavailable`` with exponential backoff.

    Up to ``len(_RETRY_DELAYS_S)`` retries. After the budget is exhausted,
    the last ``UazapiUnavailable`` is re-raised. Any other exception
    propagates immediately (e.g. 4xx → ``UazapiError`` family).
    """
    last_exc: UazapiUnavailable | None = None
    attempts = len(_RETRY_DELAYS_S) + 1
    for attempt in range(attempts):
        try:
            return await call()
        except UazapiUnavailable as exc:
            last_exc = exc
            if attempt >= len(_RETRY_DELAYS_S):
                break
            delay = _RETRY_DELAYS_S[attempt]
            logger.warning(
                "uazapi op=%s 5xx_retry attempt=%d/%d delay_s=%s",
                op,
                attempt + 1,
                attempts,
                delay,
                extra=log_extra,
            )
            await asyncio.sleep(delay)
    assert last_exc is not None  # loop only exits via raise or break-with-exc
    raise last_exc


class UazapiProvider:
    """Async REST adapter against uazapi.com."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=settings.UAZAPI_BASE_URL,
                timeout=settings.UAZAPI_HTTP_TIMEOUT_S,
                headers={"Content-Type": "application/json"},
            )
        return self._client

    async def __aenter__(self) -> "UazapiProvider":
        _ = self.client
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def create_session(self) -> ProviderSession:
        # uazapi (free tier especially) requires a `name` in the body — empty
        # payload returns 400 "Missing Name or instanceName in payload". We
        # generate an ephemeral identifier; the real session UUID is tracked
        # separately by the service layer.
        instance_name = f"medzee-spy-{uuid4().hex[:8]}"
        create_payload = await self._request(
            "POST",
            "/instance/create",
            op="create_session.create",
            token=settings.UAZAPI_ADMIN_TOKEN,
            token_header="admintoken",
            json_body={"name": instance_name},
        )
        instance_token = _extract_instance_token(create_payload)
        if not instance_token:
            raise UazapiUnknown("missing instance token in /instance/create response")

        connect_payload = await self._request(
            "POST",
            "/instance/connect",
            op="create_session.connect",
            token=instance_token,
            json_body={},
        )
        qr = _extract_qr(connect_payload)
        if not qr:
            raise UazapiUnknown("missing qrcode in /instance/connect response")
        return ProviderSession(session_token=instance_token, qr_base64=qr)

    async def register_webhook(self, session_token: str, callback_url: str) -> None:
        # uazapi paid: testes empíricos mostraram que ``events: ['connection',
        # 'messages']`` não estava entregando o evento de mensagens (só o
        # connection chegava). Ampliamos pra cobrir todos os nomes conhecidos
        # de evento de mensagem no ecossistema Baileys/uazapi. Mantemos
        # ``excludeMessages: false`` defensivo (alguns tiers default = exclude).
        #
        # Sem retry: register_webhook está no caminho síncrono de POST /sessions,
        # então qualquer espera aqui trava o usuário no spinner "Gerando QR".
        # _RETRY_DELAYS_S (10/30/60/120 = 220s) era impraticável; já testamos.
        # Caller trata UazapiError como não-fatal — se falhar, o QR é entregue
        # mesmo assim, só perde o webhook 'connection' (F1 auto-extract não
        # dispara, mas F4 on-demand ainda funciona).
        body = {
            "url": callback_url,
            "events": [
                "connection",
                "messages",
                "messages.upsert",
                "messages.update",
                "message",
                "message.upsert",
                "message.received",
                "messages.received",
                "presence.update",
                "chats.upsert",
                "chats.update",
            ],
            "enabled": True,
            # uazapi (Go) espera []string. Mandar boolean false dispara
            # "cannot unmarshal bool into Go struct field
            # webhookStruct.excludeMessages of type []string" → HTTP 500.
            # Empty list = "não excluir nenhum tipo de mensagem". Confirmado
            # via curl direto: com [] o registro retorna 200; com false, 500.
            "excludeMessages": [],
            "addUrlEvents": True,
            "addUrlTypesMessages": True,
        }
        await self._request(
            "POST",
            "/webhook",
            op="register_webhook",
            token=session_token,
            json_body=body,
        )
        # Diagnóstico: lê de volta o webhook configurado pra confirmar o que
        # a uazapi efetivamente aceitou (alguns campos podem ter sido
        # ignorados silenciosamente).
        try:
            verification = await self._request(
                "GET",
                "/webhook",
                op="register_webhook.verify",
                token=session_token,
            )
            logger.info(
                "uazapi webhook config verified: %r",
                verification,
            )
        except Exception:
            logger.warning("uazapi webhook GET verification failed (ignored)")

    async def refresh_qr(self, session_token: str) -> str:
        payload = await self._request(
            "POST",
            "/instance/connect",
            op="refresh_qr",
            token=session_token,
            json_body={},
        )
        qr = _extract_qr(payload)
        if not qr:
            raise UazapiUnknown("missing qrcode in /instance/connect refresh response")
        return qr

    async def get_status(self, session_token: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/instance/status",
            op="get_status",
            token=session_token,
        )

    async def list_chats(
        self,
        session_token: str,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Chat], bool]:
        async def _do() -> Any:
            return await self._request(
                "POST",
                "/chat/find",
                op="list_chats",
                token=session_token,
                json_body={
                    "limit": limit,
                    "offset": offset,
                    "sort": "last_message_desc",
                },
            )

        payload = await _retry_5xx(_do, op="list_chats")
        raw_chats = _extract_collection(payload, ("chats", "data", "results"))
        chats = [_parse_chat(item) for item in raw_chats]
        has_more = _extract_has_more(payload)
        if has_more is None:
            has_more = len(chats) == limit
        return chats, has_more

    async def list_messages(
        self,
        session_token: str,
        chat_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Message], bool, int]:
        async def _do() -> Any:
            return await self._request(
                "POST",
                "/message/find",
                op="list_messages",
                token=session_token,
                json_body={"chatid": chat_id, "limit": limit, "offset": offset},
            )

        payload = await _retry_5xx(_do, op="list_messages")
        raw_messages = _extract_collection(payload, ("messages", "data", "results"))
        messages = [_parse_message(item) for item in raw_messages]
        has_more = _extract_has_more(payload)
        if has_more is None:
            has_more = len(messages) == limit
        next_offset_raw = _maybe_int(payload.get("next_offset")) if isinstance(payload, dict) else None
        next_offset = next_offset_raw if next_offset_raw is not None else offset + len(messages)
        return messages, has_more, next_offset

    async def get_chat_totals(self, session_token: str) -> dict[str, Any]:
        """Call ``POST /chat/find`` with limit=1 and return the full payload.

        Used by ``GET /api/whatsapp/uazapi-stats`` para a página de Conexão
        exibir contagens em tempo real (chats + mensagens) direto do provider,
        em vez do snapshot de ``captured_messages`` (que depende do webhook
        ``messages`` chegar — não confiável em todos os tiers).

        Não passa por ``_retry_5xx`` propositalmente: este é um endpoint de
        UI que pola a cada poucos segundos. Um 500 transitório vira erro no
        front e o próximo poll já tenta de novo. Backoff exponencial aqui
        atrapalharia a responsividade da página.

        Retorna o payload bruto pra route layer extrair ``totalChatsStats``.
        """
        return await self._request(
            "POST",
            "/chat/find",
            op="get_chat_totals",
            token=session_token,
            json_body={
                "operator": "AND",
                "sort": "-wa_lastMsgTimestamp",
                "limit": 1,
                "offset": 0,
            },
        )

    async def disconnect(self, session_token: str) -> None:
        await self._request(
            "POST",
            "/instance/disconnect",
            op="disconnect",
            token=session_token,
            json_body={},
        )

    async def delete_instance(self, session_token: str) -> None:
        """Disconnect + destroy the uazapi instance in a single call.

        Calls ``DELETE /instance`` with the per-instance ``token`` header,
        which uazapi documents as: "The device has been successfully
        disconnected and the instance has been deleted from the database."
        Frees the tenant's device slot immediately — no separate disconnect
        call required.
        """
        await self._request(
            "DELETE",
            "/instance",
            op="delete_instance",
            token=session_token,
        )

    async def list_all_instances(self) -> list[dict[str, Any]]:
        """Admin-only: list every instance under this tenant.

        Used by the orphan-cleanup utility (see scripts/cleanup_orphans.py).
        Each entry includes the per-instance token, so the caller can pair it
        with ``delete_instance`` to wipe slots that the normal lifecycle never
        cleaned up (e.g., process crashed mid-extract).
        """
        payload = await self._request(
            "GET",
            "/instance/all",
            op="list_all_instances",
            token=settings.UAZAPI_ADMIN_TOKEN,
            token_header="admintoken",
        )
        # /instance/all returns a JSON array; _request wraps non-dict in {"data": ...}.
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            return payload["data"]
        if isinstance(payload, list):
            return payload
        return []

    async def _request(
        self,
        method: str,
        path: str,
        *,
        op: str,
        token: str,
        token_header: str = "token",
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {token_header: token}
        token_tail = (token or "")[-6:] if token else "------"
        started = time.perf_counter()
        try:
            response = await self.client.request(
                method,
                path,
                headers=headers,
                json=json_body if json_body is not None else None,
            )
        except httpx.TimeoutException:
            self._log(op, "err", started, token_tail, err="UazapiTimeout")
            raise UazapiTimeout(f"{op} timed out") from None
        except httpx.HTTPError as exc:
            self._log(op, "err", started, token_tail, err="UazapiUnavailable")
            raise UazapiUnavailable(f"{op} network error: {type(exc).__name__}") from exc

        try:
            payload = self._raise_for_response(response, op=op, token_tail=token_tail)
        except Exception:
            # _raise_for_response already logged the error code; re-raise.
            raise
        self._log(op, response.status_code, started, token_tail)
        return payload

    def _raise_for_response(
        self,
        response: httpx.Response,
        *,
        op: str,
        token_tail: str,
    ) -> dict[str, Any]:
        status = response.status_code

        if 200 <= status < 300:
            try:
                data = response.json()
            except ValueError:
                data = {}
            payload: dict[str, Any] = data if isinstance(data, dict) else {"data": data}
            if _has_provider_code(payload, _PROVIDER_CODE_BANNED):
                logger.info(
                    "uazapi op=%s status=%d elapsed_ms=- token=...%s err=UazapiBanned",
                    op,
                    status,
                    token_tail,
                )
                raise UazapiBanned("provider_code 463")
            return payload

        try:
            body_json = response.json()
        except ValueError:
            body_json = None

        if isinstance(body_json, dict) and _has_provider_code(body_json, _PROVIDER_CODE_BANNED):
            logger.info(
                "uazapi op=%s status=%d token=...%s err=UazapiBanned",
                op,
                status,
                token_tail,
            )
            raise UazapiBanned("provider_code 463")

        if status >= 500:
            logger.info(
                "uazapi op=%s status=%d token=...%s err=UazapiUnavailable",
                op,
                status,
                token_tail,
            )
            raise UazapiUnavailable(f"uazapi {status}")

        if 400 <= status < 500:
            if _looks_like_qr_expired(body_json, response.text):
                logger.info(
                    "uazapi op=%s status=%d token=...%s err=UazapiQrExpired",
                    op,
                    status,
                    token_tail,
                )
                raise UazapiQrExpired(f"qr expired ({status})")
            if status == 401:
                logger.info(
                    "uazapi op=%s status=%d token=...%s err=UazapiUnauthorized",
                    op,
                    status,
                    token_tail,
                )
                raise UazapiUnauthorized(f"token invalid ({status})")
            snippet = response.text[:500] if response.text else f"http {status}"
            logger.info(
                "uazapi op=%s status=%d token=...%s err=UazapiUnknown",
                op,
                status,
                token_tail,
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("uazapi op=%s body=%s", op, snippet)
            raise UazapiUnknown(snippet)

        # Unexpected status (1xx/3xx) — surface as unknown.
        raise UazapiUnknown(f"unexpected status {status}")

    @staticmethod
    def _log(
        op: str,
        status: int | str,
        started: float,
        token_tail: str,
        *,
        err: str | None = None,
    ) -> None:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if err:
            logger.info(
                "uazapi op=%s status=%s elapsed_ms=%d token=...%s err=%s",
                op,
                status,
                elapsed_ms,
                token_tail,
                err,
            )
        else:
            logger.info(
                "uazapi op=%s status=%s elapsed_ms=%d token=...%s",
                op,
                status,
                elapsed_ms,
                token_tail,
            )


def _has_provider_code(payload: Any, target: int) -> bool:
    """Recursively scan dict/list payloads for `provider_code == target`."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "provider_code":
                if _maybe_int(value) == target:
                    return True
            if isinstance(value, (dict, list)) and _has_provider_code(value, target):
                return True
        return False
    if isinstance(payload, list):
        return any(_has_provider_code(item, target) for item in payload)
    return False


def _looks_like_qr_expired(body_json: Any, body_text: str) -> bool:
    if isinstance(body_json, dict):
        for key in ("error", "code", "message", "reason", "status"):
            value = body_json.get(key)
            if isinstance(value, str):
                lowered = value.lower()
                if "qr" in lowered and "expir" in lowered:
                    return True
        nested = body_json.get("data") if isinstance(body_json.get("data"), dict) else None
        if nested and _looks_like_qr_expired(nested, ""):
            return True
    if body_text:
        lowered = body_text.lower()
        if "qr" in lowered and any(hint in lowered for hint in ("expired", "expir")):
            return True
    return False


def _extract_instance_token(payload: dict[str, Any]) -> str | None:
    if not isinstance(payload, dict):
        return None
    direct = payload.get("token") or payload.get("instance_token")
    if isinstance(direct, str) and direct:
        return direct
    instance = payload.get("instance")
    if isinstance(instance, dict):
        nested = instance.get("token") or instance.get("instance_token")
        if isinstance(nested, str) and nested:
            return nested
    data = payload.get("data")
    if isinstance(data, dict):
        nested = data.get("token") or data.get("instance_token")
        if isinstance(nested, str) and nested:
            return nested
    return None


def _extract_qr(payload: dict[str, Any]) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("qrcode", "qr", "qr_base64"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return _strip_data_url(value)
    instance = payload.get("instance")
    if isinstance(instance, dict):
        for key in ("qrcode", "qr", "qr_base64"):
            value = instance.get(key)
            if isinstance(value, str) and value:
                return _strip_data_url(value)
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("qrcode", "qr", "qr_base64"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return _strip_data_url(value)
    return None


def _strip_data_url(value: str) -> str:
    if value.startswith("data:") and "," in value:
        return value.split(",", 1)[1]
    return value


def _extract_collection(payload: Any, keys: tuple[str, ...]) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _extract_has_more(payload: Any) -> bool | None:
    if not isinstance(payload, dict):
        return None
    for key in ("has_more", "hasMore", "more"):
        if key in payload:
            value = payload.get(key)
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, str)):
                try:
                    return bool(int(value))
                except (TypeError, ValueError):
                    return None
    return None


def _parse_chat(raw: Any) -> Chat:
    if not isinstance(raw, dict):
        return Chat(wa_chatid="", contact_name="", is_group=False, last_message_at=None)
    wa_chatid = _first_str(raw, ("wa_chatid", "chatid", "id", "jid")) or ""
    contact_name = (
        _first_str(raw, ("contact_name", "name", "pushName", "push_name", "subject")) or ""
    )
    is_group = _first_bool(raw, ("is_group", "isGroup", "group")) or wa_chatid.endswith("@g.us")
    last_message_at = _first_ts(raw, ("last_message_at", "lastMessageAt", "t", "timestamp"))
    return Chat(
        wa_chatid=wa_chatid,
        contact_name=contact_name,
        is_group=is_group,
        last_message_at=last_message_at,
    )


# Baileys/whatsmeow surface several text-bearing message types — the worker's
# 30d filter assumes a normalized "text" string, so we collapse all of them here.
_TEXT_TYPE_ALIASES = frozenset({
    "text",
    "chat",                    # Baileys plain-text
    "conversation",            # whatsmeow plain-text
    "extendedtextmessage",     # Baileys formatted / quoted / link-preview text
    "extendedtext",
})


def _normalize_message_type(raw_type: str | None) -> str:
    if not raw_type:
        return "text"
    lowered = raw_type.lower()
    if lowered in _TEXT_TYPE_ALIASES:
        return "text"
    return lowered


def _parse_message(raw: Any) -> Message:
    if not isinstance(raw, dict):
        return Message(ts=0, from_me=False, type="unknown", text="")
    ts = _first_ts(raw, ("ts", "t", "timestamp", "messageTimestamp")) or 0
    from_me_val = _first_bool(raw, ("from_me", "fromMe", "fromme"))
    from_me = bool(from_me_val) if from_me_val is not None else False
    raw_type = _first_str(raw, ("type", "messageType", "media_type"))
    text_val = _first_str(raw, ("text", "body", "content", "message", "caption")) or ""
    return Message(
        ts=ts,
        from_me=from_me,
        type=_normalize_message_type(raw_type),
        text=text_val,
    )


def _first_str(raw: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _first_bool(raw: dict[str, Any], keys: tuple[str, ...]) -> bool | None:
    for key in keys:
        if key in raw:
            value = raw.get(key)
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, str)):
                try:
                    return bool(int(value))
                except (TypeError, ValueError):
                    if isinstance(value, str):
                        lowered = value.strip().lower()
                        if lowered in ("true", "yes"):
                            return True
                        if lowered in ("false", "no", ""):
                            return False
    return None


def _first_ts(raw: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = raw.get(key)
        ts = _maybe_int(value)
        if ts is not None:
            # Heuristic: uazapi sometimes returns milliseconds — normalize to seconds.
            if ts > 10_000_000_000:
                ts = ts // 1000
            return ts
    return None


def _maybe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            try:
                return int(float(value))
            except ValueError:
                return None
    return None


