"""HTTP / SSE routes for the WhatsApp module (design § 7).

Thin wrappers on top of :class:`WhatsAppService` (T7) and ``session_store``
(T6). The routes' only jobs are:

* extract the inputs (path/query params, request body, client IP);
* call the service / store;
* translate exceptions into the HTTP shapes defined in design § 10;
* in the SSE case, format the per-event wire frame per design § 9.

No business logic lives here. Everything that touches uazapi, the repository,
or the in-memory state machine is owned by the service / store / worker.

Logging policy
--------------
We log a single structured entry on each route invocation (``op`` +
``session_id`` when relevant). The service logs the detail (provider calls,
elapsed_ms, error classes) so we don't duplicate. We **never** log:

    * request bodies (especially the webhook payload — privacy + size);
    * uazapi tokens / QR codes;
    * full phone numbers (the service emits already-masked values).

Wiring
------
This module exposes a single :data:`router` (``APIRouter``). T12 mounts it
under ``/api/whatsapp`` in ``app/api/router.py``; mounting is intentionally
deferred so the rest of F1 can land without touching the top-level router.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.clients.whatsapp.errors import (
    UazapiBanned,
    UazapiError,
    UazapiTimeout,
    UazapiUnavailable,
)
from app.contracts.responses import SuccessResponse
from app.core.security import get_current_user_id, get_current_user_id_optional
from app.modules.captured_messages.schemas import WhatsappStatusResponse
from app.modules.whatsapp.schemas import (
    TERMINAL_STATUSES,
    CreateSessionResponse,
    SSEEvent,
    UazapiWebhookPayload,
)
from app.modules.whatsapp.service import (
    RateLimitExceeded,
    SessionNotFound,
    WhatsAppService,
    get_service,
)
from app.modules.whatsapp.state import session_store

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Endpoint 1 — POST /sessions (T9, WPP-01 / WPP-02 / WPP-16)
# ---------------------------------------------------------------------------


@router.post(
    "/sessions",
    response_model=SuccessResponse[CreateSessionResponse],
    summary="Create a new WhatsApp session and get a QR Code to scan",
    tags=["whatsapp"],
)
async def create_session(
    request: Request,
    service: WhatsAppService = Depends(get_service),
    user_id: UUID | None = Depends(get_current_user_id_optional),
) -> SuccessResponse[CreateSessionResponse]:
    """Spin up a uazapi instance and return the QR payload.

    Two entry modes:

    * **Anonymous** (no Authorization header): used by ``/spy`` first-time
      flow. ``user_id`` will be linked later when the user signs up.
    * **Authenticated** (Bearer JWT present): used by ``/app/connect``
      for users who already exist. The session is linked to ``user_id``
      at creation time so the webhook ``messages`` event can attribute
      msgs immediately (no race window).

    Translates service-layer errors to HTTP per design § 10:

    ===============================  =========================
    Exception                        HTTP response
    ===============================  =========================
    ``RateLimitExceeded``            429 ``too_many_sessions``
    ``UazapiUnavailable`` / Timeout  503 ``uazapi_unavailable``
    ``UazapiBanned``                 502 ``banned``
    any other ``UazapiError``        503 ``uazapi_unavailable``
    bare ``Exception``               (re-raised → 500)
    ===============================  =========================
    """
    client_ip = request.client.host if request.client else "unknown"
    logger.info(
        "route.create_session.enter",
        extra={
            "op": "create_session",
            "client_ip": client_ip,
            "user_id": str(user_id) if user_id else None,
        },
    )

    try:
        result = await service.create_session(client_ip, user_id=user_id)
    except RateLimitExceeded:
        # WPP-16: caller hit > 3 attempts in 5 minutes.
        raise HTTPException(status_code=429, detail="too_many_sessions")
    except (UazapiUnavailable, UazapiTimeout):
        raise HTTPException(status_code=503, detail="uazapi_unavailable")
    except UazapiBanned:
        raise HTTPException(status_code=502, detail="banned")
    except UazapiError:
        # Any other classified provider error collapses to "unavailable" —
        # we don't leak provider-internal classifications to the client.
        raise HTTPException(status_code=503, detail="uazapi_unavailable")

    return SuccessResponse(data=result)


# ---------------------------------------------------------------------------
# Endpoint 2 — GET /sessions/{session_id}/events (T10, WPP-04/05/14/15)
# ---------------------------------------------------------------------------


@router.get(
    "/sessions/{session_id}/events",
    summary="SSE stream of session lifecycle events",
    tags=["whatsapp"],
)
async def session_events(session_id: UUID) -> StreamingResponse:
    """Server-Sent Events stream for a single session.

    Wire format (design § 9)::

        event: <name>
        data: <json(data)>
        \\n

    Each frame ends with a blank line (``\\n\\n``). Replay-last and terminal
    semantics are handled inside :py:meth:`SessionStore.subscribe`:

    * the first yielded event is ``state.last_event`` when present;
    * the generator returns after a terminal event (``extracted``, ``failed``,
      ``expired``) — closing the stream as required by WPP-15;
    * the ``try/finally`` inside ``subscribe`` detaches the subscriber queue
      when the client disconnects (FastAPI cancels the generator), so we
      don't need explicit cleanup here.
    """
    logger.info(
        "route.session_events.enter",
        extra={"op": "session_events", "session_id": str(session_id)},
    )

    state = await session_store.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="session_not_found")

    async def event_stream() -> AsyncIterator[bytes]:
        event: SSEEvent
        async for event in session_store.subscribe(session_id):
            # ensure_ascii=False so the wire stays compact for any unicode
            # in event payloads (phone masks, names) — SSE is UTF-8 by spec.
            payload = json.dumps(event.data, ensure_ascii=False)
            yield f"event: {event.name}\ndata: {payload}\n\n".encode("utf-8")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # nginx / proxy hint — disable buffering
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# Endpoint 3 — POST /webhook (T11, WPP-06 / WPP-07 / EC-06)
# ---------------------------------------------------------------------------


async def _process_webhook_body(
    body: dict,
    session_id: UUID | None,
    service: WhatsAppService,
) -> None:
    """Lógica compartilhada entre os 2 endpoints de webhook (path-param novo
    e query legado). Loga summary + dispara handle_webhook_event. Sem
    session_id é tratado como probe — só loga e retorna sem dispatch.
    """
    event_hint = body.get("event") or body.get("EventType") or body.get("type") or "?"
    instance = body.get("instance") if isinstance(body.get("instance"), dict) else {}
    status_hint = instance.get("status") or "?"

    if session_id is None:
        # Probe de uazapi (sem session_id no path/query). Não dispatch — só
        # log + 200. Isso evita o cenário em que uazapi testava a URL
        # com body vazio e nossa rota explodia 422, fazendo a uazapi
        # devolver 500 no /webhook de registro.
        logger.info(
            "route.webhook.probe (no session_id) event=%s",
            event_hint,
        )
        return

    if event_hint == "connection" and status_hint == "connecting":
        logger.debug(
            "route.webhook.qr_refresh session_id=%s name=%s",
            session_id,
            instance.get("name"),
        )
    else:
        summary = {
            "EventType": body.get("EventType") or body.get("event"),
            "status": status_hint,
            "name": instance.get("name"),
            "type": body.get("type"),
            "owner": body.get("owner") or "",
            "lastDisconnectReason": instance.get("lastDisconnectReason"),
        }
        logger.info(
            "route.webhook.enter session_id=%s event=%s summary=%s",
            session_id,
            event_hint,
            {k: v for k, v in summary.items() if v not in (None, "")},
        )

    try:
        await service.handle_webhook_event(session_id, body)
    except Exception:
        logger.exception(
            "route.webhook.handler_failed session_id=%s event=%s",
            session_id,
            event_hint,
        )


@router.post(
    "/webhook/{session_id}",
    status_code=200,
    summary="Callback from uazapi — path-param variant (preferido pelo uazapi)",
    tags=["whatsapp", "webhook"],
)
async def uazapi_webhook_path(
    request: Request,
    session_id: UUID,
    service: WhatsAppService = Depends(get_service),
) -> dict:
    """Variante path-param do webhook. Substitui o `?session_id=...` que
    parece causar 500 no registro `/webhook` da uazapi paid (H1 do AUDIT).
    Igual semântica: sempre devolve 200 OK pra não criar retry storm.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    await _process_webhook_body(body, session_id, service)
    return {"status": "ok"}


@router.get(
    "/webhook/{session_id}",
    status_code=200,
    summary="Probe handler — alguns webhook providers fazem GET antes do POST",
    tags=["whatsapp", "webhook"],
)
async def uazapi_webhook_probe(session_id: UUID) -> dict:
    """Resposta vazia 200 OK pra qualquer GET. uazapi pode estar validando o
    callback URL via GET antes de aceitar o registro — se a gente devolver
    405 Method Not Allowed, o registro 500-a.
    """
    logger.info("route.webhook.get_probe session_id=%s", session_id)
    return {"status": "ok"}


@router.post(
    "/webhook",
    status_code=200,
    summary="Callback from uazapi.com (legacy query-param) — forwarded to session bus",
    tags=["whatsapp", "webhook"],
)
async def uazapi_webhook(
    request: Request,
    session_id: UUID | None = Query(
        default=None,
        description="UUID from the registered callback URL (legacy — agora também pode vir como path /webhook/{session_id})",
    ),
    service: WhatsAppService = Depends(get_service),
) -> dict:
    """Rota legada com session_id via query string. Aceita também probe
    SEM session_id (retorna 200 + log), pra evitar 422 quando a uazapi
    testa o URL na hora do registro.

    Contract (design § 7.3 / EC-06): SEMPRE 200 OK pra impedir retry storm.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    await _process_webhook_body(body, session_id, service)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Endpoint 4 — DELETE /sessions/{session_id} (T11, WPP-12)
# ---------------------------------------------------------------------------


@router.delete(
    "/sessions/{session_id}",
    summary="Cancel an in-progress session",
    tags=["whatsapp"],
)
async def cancel_session(
    session_id: UUID,
    service: WhatsAppService = Depends(get_service),
) -> dict:
    """Manually cancel a session (frontend calls this on /spy unload).

    Responses:

    * ``200 {"status": "cancelled"}`` — session was active and got cancelled.
    * ``200 {"status": "already_terminal"}`` — session existed but was
      already in a terminal status (``consumed``/``failed``/``expired``/
      ``extracted``); the service is a silent no-op in that case so we
      detect it by sniffing the state *before* calling the service.
    * ``404 session_not_found`` — no such session in memory.
    """
    logger.info(
        "route.cancel_session.enter",
        extra={"op": "cancel_session", "session_id": str(session_id)},
    )

    # Peek state to distinguish "already terminal" from "cancelled" — the
    # service's cancel_session() does not raise in the terminal case, so
    # we have to check ourselves to return a meaningful status string.
    state = await session_store.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="session_not_found")

    if state.status in TERMINAL_STATUSES:
        return {"status": "already_terminal"}

    try:
        await service.cancel_session(session_id)
    except SessionNotFound:
        # Race: session vanished between the peek and the service call.
        raise HTTPException(status_code=404, detail="session_not_found")

    return {"status": "cancelled"}


# ---------------------------------------------------------------------------
# Endpoint 5 — GET /status (F4-T6, F4-14)
# ---------------------------------------------------------------------------


@router.get(
    "/status",
    response_model=SuccessResponse[WhatsappStatusResponse],
    summary="Estado atual da conexão WhatsApp do usuário autenticado",
    tags=["whatsapp"],
)
async def whatsapp_status(
    user_id: UUID = Depends(get_current_user_id),
) -> SuccessResponse[WhatsappStatusResponse]:
    """Retorna se o usuário tem uma sessão WhatsApp ativa + stats das msgs.

    Política (F4 design § Forward-Capture):

    * Nenhuma session ainda → ``{connected: false}`` (defaults zeram o resto).
    * Session existe e ``status == 'connected'`` → ``{connected: true, ...}``
      com session_id, connected_since e os counts de mensagens já capturadas.
    * Session existe mas ``status != 'connected'`` → ``{connected: false,
      session_id, connected_since (último valor conhecido), ...stats}`` — o
      front pode exibir "desconectado, tem X msgs do último período conectado".

    O import de ``captured_messages.repository`` é lazy porque o módulo está
    sendo construído em paralelo (T4) e podemos rodar a app mesmo se o stats
    helper ainda não tiver carregado em algum cenário de import circular.
    """
    logger.info(
        "route.whatsapp_status.enter",
        extra={"op": "whatsapp_status", "user_id": str(user_id)},
    )

    from app.modules.whatsapp import repository as whatsapp_repo
    from app.modules.captured_messages import repository as captured_repo

    session = await whatsapp_repo.get_active_for_user(user_id)
    if session is None:
        logger.info(
            "route.whatsapp_status.no_session",
            extra={"op": "whatsapp_status", "user_id": str(user_id)},
        )
        return SuccessResponse(data=WhatsappStatusResponse(connected=False))

    session_id = UUID(str(session["id"]))
    stats = await captured_repo.stats_for_session(session_id)

    # Connected = WhatsApp ainda ativo, mesmo durante/após o F1 extract.
    # Sem isso, a UI mostra "WhatsApp não conectado" durante 'extracting'/
    # 'extracted', confundindo o usuário (o WhatsApp tá conectado no celular
    # dele, só o nosso pipeline tá processando).
    _ALIVE_STATUSES = {"connected", "extracting", "extracted"}
    db_status = str(session.get("status") or "")
    is_connected = db_status in _ALIVE_STATUSES

    # Diagnóstico: SEMPRE loga o status final pra debug fácil sem SQL.
    # Importante quando user diz "wpp conectado mas dashboard não mostra" —
    # confere se é 'pending' (poll não detectou), 'failed' (algum 401),
    # 'disconnected' (cleanup), ou se de fato é 'connected/extracting/extracted'.
    logger.info(
        "route.whatsapp_status.resolved",
        extra={
            "op": "whatsapp_status",
            "user_id": str(user_id),
            "session_id": str(session_id),
            "db_status": db_status,
            "is_connected": is_connected,
            "captured_message_count": stats["message_count"],
            "captured_conversation_count": stats["conversation_count"],
            "connected_at": str(session.get("connected_at") or ""),
        },
    )
    return SuccessResponse(
        data=WhatsappStatusResponse(
            connected=is_connected,
            session_id=session_id,
            connected_since=session.get("connected_at"),
            message_count=stats["message_count"],
            conversation_count=stats["conversation_count"],
            last_message_at=stats["last_message_at"],
        )
    )


# ---------------------------------------------------------------------------
# Endpoint 6 — GET /uazapi-stats (UI proxy de /chat/find)
# ---------------------------------------------------------------------------


@router.get(
    "/uazapi-stats",
    summary="Totais ao vivo via uazapi /chat/find (chat_count + message_count)",
    tags=["whatsapp"],
)
async def whatsapp_uazapi_stats(
    user_id: UUID = Depends(get_current_user_id),
) -> dict:
    """Retorna as contagens em tempo real direto da uazapi.

    Diferente de :func:`whatsapp_status` (que lê o snapshot local de
    ``captured_messages``), este endpoint proxia ``POST /chat/find`` no
    provider e expõe o bloco ``totalChatsStats``. Usado pela página de
    Conexão pra polar a cada N segundos e refletir o que o WhatsApp tem
    HOJE — sem depender do webhook ``messages`` chegar.

    Responses:

    * 404 ``no_active_session``     — usuário sem sessão WhatsApp.
    * 409 ``not_connected``         — sessão existe mas não está conectada.
    * 502 ``uazapi_unavailable``    — provider retornou erro (5xx, timeout).
    * 200 ``{ chat_count, message_count, raw }`` — sucesso.

    O front nunca deve confiar cegamente em ``chat_count``/``message_count``:
    a estrutura do ``totalChatsStats`` varia por tier uazapi, então também
    devolvemos o ``raw`` pra debug/exibição secundária.
    """
    logger.info(
        "route.whatsapp_uazapi_stats.enter",
        extra={"op": "whatsapp_uazapi_stats", "user_id": str(user_id)},
    )

    from app.clients.whatsapp import get_provider
    from app.modules.whatsapp import repository as whatsapp_repo

    session = await whatsapp_repo.get_active_for_user(user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="no_active_session")
    # Mesma regra do /status: WhatsApp segue conectado durante e após o
    # F1 extract (status transita pra extracting/extracted). Sem essa
    # expansão, o dashboard ficava com 0/0/0 logo após connect porque o
    # extract muda o status em milissegundos depois de 'connected'.
    _ALIVE_STATUSES = {"connected", "extracting", "extracted"}
    db_status = str(session.get("status") or "")
    if db_status not in _ALIVE_STATUSES:
        raise HTTPException(status_code=409, detail="not_connected")

    token = session.get("uazapi_token")
    if not token:
        raise HTTPException(status_code=409, detail="missing_token")

    provider = get_provider()
    try:
        payload = await provider.get_chat_totals(token)
    except (UazapiUnavailable, UazapiTimeout):
        raise HTTPException(status_code=502, detail="uazapi_unavailable")
    except UazapiError:
        raise HTTPException(status_code=502, detail="uazapi_unavailable")

    stats = payload.get("totalChatsStats") if isinstance(payload, dict) else None
    stats = stats if isinstance(stats, dict) else {}

    chat_count = _extract_total(stats.get("total_chats"))
    message_count = _extract_total(stats.get("total_messages"))

    # Diagnóstico: loga shape do totalChatsStats (sem PII) pra confirmar
    # quais chaves a uazapi paga manda neste tier. Se ``chat_count`` ou
    # ``message_count`` vier 0 com chats reais, é aqui que confirmamos
    # a estrutura e ajustamos a extração.
    logger.info(
        "route.whatsapp_uazapi_stats.payload",
        extra={
            "op": "whatsapp_uazapi_stats",
            "user_id": str(user_id),
            "top_keys": sorted(payload.keys()) if isinstance(payload, dict) else None,
            "stats_keys": sorted(stats.keys()),
            "total_chats_raw": stats.get("total_chats"),
            "total_messages_raw": stats.get("total_messages"),
            "chat_count": chat_count,
            "message_count": message_count,
        },
    )

    return {
        "chat_count": chat_count,
        "message_count": message_count,
        "raw": stats,
    }


def _extract_total(node: Any) -> int:
    """Aceita várias formas de ``totalChatsStats.*``: ``int`` direto,
    ``{"total": N, ...}`` ou aninhado uma vez. Retorna 0 quando não bate."""
    if isinstance(node, int):
        return node
    if isinstance(node, dict):
        total = node.get("total")
        if isinstance(total, int):
            return total
        if isinstance(total, (str, float)):
            try:
                return int(total)
            except (TypeError, ValueError):
                return 0
    if isinstance(node, (str, float)):
        try:
            return int(node)
        except (TypeError, ValueError):
            return 0
    return 0


__all__ = ["router"]
