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
from typing import AsyncIterator
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


@router.post(
    "/webhook",
    status_code=200,
    summary="Callback from uazapi.com — forwarded to the session bus",
    tags=["whatsapp", "webhook"],
)
async def uazapi_webhook(
    request: Request,
    session_id: UUID = Query(
        ..., description="UUID from the registered callback URL"
    ),
    service: WhatsAppService = Depends(get_service),
) -> dict:
    """Receive a uazapi callback and dispatch it to the service.

    Contract (design § 7.3 / EC-06):

    * **Always** return 200 ``{"status": "ok"}``. Anything else makes uazapi
      retry indefinitely, which would amplify a transient error into a
      stampede.
    * Must return in < 5s. The service already schedules the heavy extract
      work via :py:func:`asyncio.create_task`, so calling
      :py:meth:`handle_webhook_event` is itself fast.
    * Unknown ``session_id`` → silently no-op.

    We accept the raw JSON body as ``dict`` rather than a Pydantic-validated
    model because uazapi's wire schema is loosely documented — the field
    names and shape vary across event types and tier configurations. A
    strict model would 422 the request, prompting uazapi to retry-storm.
    The service is responsible for sniffing what it needs out of the payload.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    event_hint = body.get("event") or body.get("EventType") or body.get("type") or "?"
    instance = body.get("instance") if isinstance(body.get("instance"), dict) else {}
    status_hint = instance.get("status") or "?"

    # QR refreshes (status=connecting) chegam a cada ~20s e o payload inclui
    # o base64 do QR (3-5KB). Eles não trazem informação acionável: o
    # ``handle_webhook_event`` só age em ``connected`` / ``disconnected``.
    # Mantemos um DEBUG pra debug local mas não polui prod.
    if event_hint == "connection" and status_hint == "connecting":
        logger.debug(
            "route.webhook.qr_refresh session_id=%s name=%s",
            session_id,
            instance.get("name"),
        )
    else:
        # Summary curto pra eventos acionáveis (connected, disconnected,
        # LoggedOut, etc). NUNCA loga o qrcode nem o token.
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
        # Swallow + log: webhook must stay 2xx so uazapi doesn't retry-storm.
        logger.exception(
            "route.webhook.handler_failed session_id=%s event=%s",
            session_id,
            event_hint,
        )

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
        return SuccessResponse(data=WhatsappStatusResponse(connected=False))

    session_id = UUID(str(session["id"]))
    stats = await captured_repo.stats_for_session(session_id)

    return SuccessResponse(
        data=WhatsappStatusResponse(
            connected=session.get("status") == "connected",
            session_id=session_id,
            connected_since=session.get("connected_at"),
            message_count=stats["message_count"],
            conversation_count=stats["conversation_count"],
            last_message_at=stats["last_message_at"],
        )
    )


__all__ = ["router"]
