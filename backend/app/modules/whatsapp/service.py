"""WhatsApp service layer — the orchestrator that wires provider + store +
repository + masking helpers behind a single coherent API.

Design references:
    - § 7.1 — POST /sessions flow (create_session)
    - § 7.3 — webhook handler logic (handle_webhook_event)
    - § 7.4 — DELETE flow (cancel_session)
    - WPP-16 — per-IP rate limit (> 3 PENDING-creation attempts in 5min → 429)
    - WPP-11 — consume + disconnect lifecycle (F2 entry point)

Routes (Wave 4 / T9-T11) are thin wrappers over the methods of
:class:`WhatsAppService`. They translate exceptions raised here into HTTP
status codes; this module does **not** know about FastAPI.

Logging policy
--------------
Every method logs entry + exit with ``op``, ``session_id``, ``status``,
``elapsed_ms``. The following values are **never** logged:

    * ``uazapi_token`` / any provider token
    * ``qr_base64``
    * full phone numbers
    * webhook payload contents

On error we log the error **class name + ``code`` attribute**, never the raw
response body (uazapi sometimes echoes auth headers in 4xx errors).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from app.clients.whatsapp import WhatsAppProvider, get_provider
from app.clients.whatsapp.errors import UazapiError, UazapiUnauthorized
from app.core.config import settings
from app.modules.captured_messages.schemas import CapturedMessageInsert
from app.modules.whatsapp import repository
from app.modules.whatsapp.schemas import (
    CreateSessionResponse,
    ExtractedPayload,
    SessionStatus,
    SSEEvent,
    UazapiWebhookPayload,
)
from app.modules.whatsapp.state import SessionStore, session_store

if TYPE_CHECKING:  # pragma: no cover — type-only imports
    pass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ServiceError(Exception):
    """Base for service-layer errors. Routes map subclasses to HTTP codes."""


class RateLimitExceeded(ServiceError):
    """Raised when an IP exceeds the WPP-16 per-IP creation budget."""


class SessionNotFound(ServiceError):
    """Raised by methods that require an existing session in the store."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# WPP-16: per-IP creation attempts are tracked in monotonic-time windows.
# Defaults are conservative for production (3/5min). Overridable via env
# vars (WPP_RATE_LIMIT_WINDOW_S / WPP_RATE_LIMIT_MAX_ATTEMPTS) so dev/smoke
# pode ficar mais permissivo sem mudar código — necessário porque a gente
# itera no smoke E2E criando várias sessions enquanto debug.
_RATE_LIMIT_WINDOW_S: float = float(
    os.environ.get("WPP_RATE_LIMIT_WINDOW_S", "300")
)
_RATE_LIMIT_MAX_ATTEMPTS: int = int(
    os.environ.get("WPP_RATE_LIMIT_MAX_ATTEMPTS", "20")
)

# Re-exported alias kept for backwards compatibility with the route layer.
from app.modules.whatsapp.schemas import TERMINAL_STATUSES as _TERMINAL_STATUSES  # noqa: E402,F401


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class WhatsAppService:
    """Single entry point for the WhatsApp module business logic.

    The constructor takes the collaborators explicitly so tests can inject
    fakes/mocks. The module-level :func:`get_service` factory wires the
    production defaults (real provider + singleton store + production
    callback base URL from settings).
    """

    def __init__(
        self,
        provider: WhatsAppProvider,
        store: SessionStore,
        *,
        callback_base_url: str,
    ) -> None:
        self._provider = provider
        self._store = store
        self._callback_base_url = callback_base_url.rstrip("/")
        # IP -> list of monotonic timestamps of recent create attempts.
        # Pruned in-place on every check; no separate GC needed because
        # IPs that stop hitting us simply stop having entries appended.
        self._rate_buckets: dict[str, list[float]] = {}
        self._rate_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # 1. create_session                                                  #
    # ------------------------------------------------------------------ #

    async def create_session(
        self, client_ip: str, *, user_id: UUID | None = None
    ) -> CreateSessionResponse:
        """Create a fresh WhatsApp session and return the QR payload.

        Flow (design § 7.1):
            1. WPP-16 rate-limit check by IP.
            2. ``provider.create_session()`` → ``ProviderSession``.
            3. Generate ``session_id = uuid4()``.
            4. Register the per-session webhook on uazapi.
            5. Persist the row in ``medzee.whatsapp_sessions`` (status=pending).
               If ``user_id`` is provided (authenticated /app/connect flow),
               the row is linked at insert time so subsequent webhook
               ``messages`` events can attribute msgs without a race.
            6. Register the in-memory state with the QR (and user_id).
            7. Return the public response.

        On any ``UazapiError`` after step 2 we make a *best effort* to mark
        the just-created session as failed in the DB so we don't leave dead
        rows lying around. We then re-raise the original exception so the
        route can translate it into the correct HTTP status (503/502/504).
        """
        started = time.monotonic()
        logger.info(
            "service.create_session.enter",
            extra={
                "op": "create_session",
                "client_ip": client_ip,
                "user_id": str(user_id) if user_id else None,
            },
        )

        await self._enforce_rate_limit(client_ip)

        # Step 2: provider call (may raise UazapiError — let it propagate
        # since no DB row exists yet).
        try:
            provider_session = await self._provider.create_session()
        except UazapiError as exc:
            logger.warning(
                "service.create_session.provider_failed",
                extra={
                    "op": "create_session",
                    "error_class": type(exc).__name__,
                    "error_code": getattr(exc, "code", "unknown"),
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
            )
            raise

        # Steps 3-6: persist + state. If anything here raises, we still need
        # to try and clean up the DB row (best effort).
        session_id = uuid4()
        # URL com path-param (não-query). Alguns providers de webhook rejeitam
        # URLs com `?` na validação interna — uazapi paid mostrou 500 constante
        # em /webhook registro com a URL de query. Path-param é o padrão da
        # maioria dos providers modernos (Stripe, MP, Twilio). Endpoint legado
        # `/api/whatsapp/webhook?session_id=...` segue funcionando.
        callback_url = (
            f"{self._callback_base_url}/api/whatsapp/webhook/{session_id}"
        )

        # Webhook setup é NÃO-FATAL: se falhar (após retry interno), o QR
        # ainda é entregue. O webhook só deixa de receber eventos live, mas o
        # usuário consegue escanear e conectar. F1 trigger (auto-extract pós
        # connected) DEPENDE do webhook — em ambientes sem callbacks, o user
        # pode usar o botão "Gerar relatório" (F4 on-demand) como fallback.
        try:
            await self._provider.register_webhook(
                provider_session.session_token, callback_url
            )
            webhook_ok = True
        except UazapiError as exc:
            webhook_ok = False
            logger.warning(
                "service.create_session.webhook_setup_failed",
                extra={
                    "op": "create_session",
                    "session_id": str(session_id),
                    "error_class": type(exc).__name__,
                    "error_code": getattr(exc, "code", "unknown"),
                },
            )

        # Persistência (DB + store) é FATAL: se falhar, não temos como
        # rastrear a sessão. Antes de re-raise, libera o slot na uazapi pra
        # não acumular instâncias órfãs na cota.
        try:
            await repository.create(
                session_id,
                uazapi_token=provider_session.session_token,
                status="pending",
                user_id=user_id,
            )
            await self._store.create(
                session_id,
                uazapi_token=provider_session.session_token,
                qr_base64=provider_session.qr_base64,
                user_id=user_id,
            )
        except Exception as exc:
            await self._release_provider_slot(
                provider_session.session_token,
                session_id=session_id,
                op="create_session.persistence_failed",
            )
            await self._safe_mark_failed(
                session_id, getattr(exc, "code", "persistence_failed")
            )
            logger.warning(
                "service.create_session.post_provider_failed",
                extra={
                    "op": "create_session",
                    "session_id": str(session_id),
                    "error_class": type(exc).__name__,
                    "error_code": getattr(exc, "code", "unknown"),
                    "webhook_ok": webhook_ok,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
            )
            raise

        # Fallback de detecção de connect via polling. Roda em paralelo ao
        # webhook: se webhook chega primeiro, o poll detecta o status já
        # transicionado e sai cedo. Se webhook está quebrado (tier do uazapi
        # com 5xx no /webhook), o poll é o ÚNICO caminho de disparar F1.
        # Sem isso, o usuário escaneia o QR e nada acontece no backend.
        asyncio.create_task(
            self._poll_connection_fallback(
                session_id, provider_session.session_token
            ),
            name=f"poll-connection-{session_id}",
        )

        response = CreateSessionResponse(
            session_id=session_id,
            qr=provider_session.qr_base64,
            status="pending",
        )
        logger.info(
            "service.create_session.exit",
            extra={
                "op": "create_session",
                "session_id": str(session_id),
                "status": SessionStatus.PENDING.value,
                "webhook_ok": webhook_ok,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return response

    # ------------------------------------------------------------------ #
    # 1b. _poll_connection_fallback — webhook-independent connection detect #
    # ------------------------------------------------------------------ #

    async def _poll_connection_fallback(
        self,
        session_id: UUID,
        session_token: str,
        *,
        poll_interval_s: float = 5.0,
        max_wait_s: float = 600.0,
    ) -> None:
        """Polls uazapi ``/instance/status`` até detectar ``connected`` ou
        até ``max_wait_s`` (default 10min — tempo razoável pro usuário
        escanear o QR).

        Idempotente em relação ao webhook:
          - Se o webhook chegar primeiro, o store transita para CONNECTED.
            O loop detecta ``state.status != PENDING`` e sai sem bater na
            uazapi de novo.
          - Se o webhook nunca chegar (tier com 5xx no /webhook), o loop
            detecta o ``connected`` na uazapi e chama
            :meth:`_handle_connection_event` com um payload sintético
            (mesmo shape do webhook), reusando 100% do código de transição.

        Tarefa é fire-and-forget. Erros transientes do uazapi são
        silenciados e re-tentados no próximo tick.
        """
        elapsed = 0.0
        ticks = 0
        try:
            while elapsed < max_wait_s:
                state = await self._store.get(session_id)
                if state is None:
                    # Sessão sumiu (cancel manual, expiry). Para.
                    return
                if state.status != SessionStatus.PENDING:
                    # Algo já transicionou — webhook chegou, ou expirou,
                    # ou fail downstream. Não precisamos mais polar.
                    logger.info(
                        "service.poll_connection.exit_state_changed",
                        extra={
                            "op": "poll_connection",
                            "session_id": str(session_id),
                            "current_status": state.status.value,
                            "ticks": ticks,
                        },
                    )
                    return

                try:
                    payload = await self._provider.get_status(session_token)
                except UazapiUnauthorized:
                    # Token rotacionado/morto pela uazapi — terminal. Polling
                    # nunca mais vai dar verde. Marca a sessão como failed e
                    # sai. Sem isso o loop fica em zumbi infinito martelando
                    # 401 por max_wait_s minutos.
                    logger.warning(
                        "service.poll_connection.token_invalid_exit",
                        extra={
                            "op": "poll_connection",
                            "session_id": str(session_id),
                            "tick": ticks,
                            "elapsed_s": int(elapsed),
                        },
                    )
                    try:
                        await self._safe_mark_failed(session_id, "token_invalid")
                    except Exception:
                        pass
                    return
                except UazapiError as exc:
                    # Transient — próximo tick tenta de novo. Log de classe
                    # de erro pra distinguir 5xx transitório do 401 acima.
                    logger.info(
                        "service.poll_connection.tick_error",
                        extra={
                            "op": "poll_connection",
                            "session_id": str(session_id),
                            "tick": ticks,
                            "error_class": type(exc).__name__,
                            "error_code": getattr(exc, "code", "unknown"),
                        },
                    )
                    await asyncio.sleep(poll_interval_s)
                    elapsed += poll_interval_s
                    ticks += 1
                    continue

                # Diagnóstico: log do shape RAW pra confirmar como o uazapi paid
                # entrega o status (a documentação varia). Quando confirmarmos
                # o shape estável, podemos baixar pra DEBUG.
                _instance_block = (
                    payload.get("instance") if isinstance(payload, dict) and isinstance(payload.get("instance"), dict) else {}
                )
                logger.info(
                    "service.poll_connection.tick",
                    extra={
                        "op": "poll_connection",
                        "session_id": str(session_id),
                        "tick": ticks,
                        "elapsed_s": int(elapsed),
                        "payload_keys": sorted(payload.keys()) if isinstance(payload, dict) else None,
                        "top_status": payload.get("status") if isinstance(payload, dict) else None,
                        "instance_status": _instance_block.get("status"),
                        "loggedIn": (payload.get("data") or {}).get("loggedIn") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else None,
                    },
                )

                if _payload_says_connected(payload):
                    logger.info(
                        "service.poll_connection.detected_connected",
                        extra={
                            "op": "poll_connection",
                            "session_id": str(session_id),
                            "ticks": ticks,
                            "elapsed_s": int(elapsed),
                        },
                    )
                    await self._handle_connection_event(session_id, payload)
                    return

                await asyncio.sleep(poll_interval_s)
                elapsed += poll_interval_s
                ticks += 1

            logger.warning(
                "service.poll_connection.timeout",
                extra={
                    "op": "poll_connection",
                    "session_id": str(session_id),
                    "elapsed_s": int(elapsed),
                    "max_wait_s": int(max_wait_s),
                },
            )
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "service.poll_connection.unhandled",
                extra={"op": "poll_connection", "session_id": str(session_id)},
            )

    # ------------------------------------------------------------------ #
    # 2. handle_webhook_event                                            #
    # ------------------------------------------------------------------ #

    async def handle_webhook_event(
        self, session_id: UUID, payload: dict[str, Any]
    ) -> None:
        """Route a uazapi webhook callback to the right handler (design § 7.3).

        Event routing:
            * ``connection`` (and connection-shaped legacy payloads) →
              :meth:`_handle_connection_event` (M1 lifecycle).
            * ``messages`` / ``messages.upsert`` / ``message`` →
              :meth:`_handle_messages_event` (F4 forward-capture).
            * Anything else → silently ignored (debug log).

        The route MUST NOT raise — uazapi retries aggressively on any
        non-2xx response, which becomes a retry-storm if we let exceptions
        bubble. Both handlers are expected to swallow their own errors.
        """
        event = (
            payload.get("event")
            or payload.get("EventType")
            or payload.get("type")
            or ""
        )
        event_lower = str(event).lower()

        # Connection-shaped payloads sometimes lack a clean event name
        # (older uazapi tiers stuff ``loggedIn`` directly in the body), so
        # we keep a "smells like connection" fallback to preserve M1 behavior.
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        smells_like_connection = (
            "connection" in event_lower
            or "connected" in event_lower
            or (isinstance(data, dict) and ("loggedIn" in data or "logged_in" in data))
        )

        if smells_like_connection:
            await self._handle_connection_event(session_id, payload)
            return

        if (
            event_lower.startswith("messages")
            or event_lower == "message"
            or "msg" in event_lower
            or "chat" in event_lower
        ):
            await self._handle_messages_event(session_id, payload)
            return

        # Diagnóstico: log TODO event desconhecido em INFO (era DEBUG, oculto em
        # prod). Permite identificar event names que uazapi paid manda mas a
        # gente ainda não roteia (ex: presence.update, chats.upsert, etc).
        logger.info(
            "service.webhook.unknown_event event=%r session_id=%s keys=%s",
            event,
            session_id,
            list(payload.keys()) if isinstance(payload, dict) else "<not-dict>",
        )

    # ------------------------------------------------------------------ #
    # 2a. _handle_connection_event                                       #
    # ------------------------------------------------------------------ #

    async def _handle_connection_event(
        self, session_id: UUID, payload: dict[str, Any]
    ) -> None:
        """Process a connection-shaped uazapi webhook.

        * ``loggedIn=True`` → mark the session connected, publish ``connected``
          via SSE, and **fire-and-forget** the extract task (T8).
        * ``loggedIn=False`` AND current status is ``CONNECTED`` → treat as
          a post-connection drop: publish ``failed`` with ``code=disconnected``
          and mark the session failed.

        Unknown sessions are a silent no-op — uazapi may deliver to a
        session that's already been expired locally; we do not want to leak
        a 404 nor let the webhook retry hammer us.
        """
        started = time.monotonic()

        # Defensive parsing: uazapi's webhook payload shape varies (different
        # event types, tier configurations, sometimes flat fields, sometimes
        # nested under "data"). Sniff the most-likely keys.
        event = (
            payload.get("event")
            or payload.get("EventType")
            or payload.get("type")
            or ""
        )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

        # Status hint pra evitar logar repetidamente o QR refresh
        # (a uazapi free manda um connection event com status=connecting a
        # cada ~20s; nenhum age — só inunda os logs).
        _instance = payload.get("instance") if isinstance(payload.get("instance"), dict) else {}
        _status = str(_instance.get("status") or "").lower()
        _log_level = (
            logger.debug
            if event.lower() == "connection" and _status == "connecting"
            else logger.info
        )
        _log_level(
            "service.webhook.enter session_id=%s event=%s status=%s",
            session_id,
            event,
            _status or "?",
        )

        state = await self._store.get(session_id)
        if state is None:
            logger.info(
                "service.webhook.unknown_session session_id=%s elapsed_ms=%d",
                session_id,
                int((time.monotonic() - started) * 1000),
            )
            return

        # Resolve loggedIn from any of the shapes we've seen.
        instance_block = (
            payload.get("instance") if isinstance(payload.get("instance"), dict) else {}
        )
        instance_status = str(instance_block.get("status") or "").lower()
        type_field = str(payload.get("type") or "").lower()

        if instance_status == "connected":
            logged_in = True
        elif instance_status == "disconnected" or type_field == "loggedout":
            logged_in = False
        else:
            # Legacy fall-backs (older docs, other tiers).
            logged_in = (
                data.get("loggedIn")
                if data.get("loggedIn") is not None
                else data.get("logged_in")
            )
            if logged_in is None:
                logged_in = data.get("connected") or data.get("connection") == "open"

        if logged_in is True:
            # uazapi puts the phone number in `owner` at the top level; fall
            # back to legacy fields if the shape ever changes.
            jid_candidate = (
                payload.get("owner")
                or data.get("jid")
                or data.get("phone")
                or data.get("number")
                or ""
            )
            if not jid_candidate and isinstance(data.get("user"), dict):
                jid_candidate = (
                    data["user"].get("id") or data["user"].get("phone") or ""
                )
            # Store the unmasked number (per product decision 2026-05-17).
            # Strip the WhatsApp suffix when present (e.g. "5511...@s.whatsapp.net"),
            # uazapi free already delivers just digits in ``owner``. The column /
            # kwarg name ``phone_masked`` is kept so we don't have to migrate the
            # DB or the in-memory state schema — only the *value* changed.
            phone = str(jid_candidate).split("@", 1)[0]
            await self._store.update(
                session_id,
                status=SessionStatus.CONNECTED,
                phone_masked=phone,
            )
            await repository.mark_status(
                session_id,
                "connected",
                phone_masked=phone,
                connected_at=datetime.now(timezone.utc),
            )
            await self._store.publish(
                session_id, SSEEvent(name="connected", data={"phone": phone})
            )
            # F9 (2026-05-19): trigger persistente pra popular captured_messages.
            # Roda em background enquanto user preenche LeadForm (signup linka
            # user_id depois). Loop interno aguarda user_id, depois faz ciclos
            # de pull + insert até captured_messages ter dados (até 30min).
            # Quando user clica "Gerar relatório" pós-login, ReportService já
            # encontra dados em captured_messages → caminho rápido (~17s) sem
            # warmup uazapi.
            try:
                from app.workers.extract import fill_captured_messages_loop
                asyncio.create_task(
                    fill_captured_messages_loop(session_id),
                    name=f"fill-cm-{session_id}",
                )
                logger.info(
                    "service.webhook.fill_loop_dispatched",
                    extra={
                        "op": "handle_webhook_event",
                        "session_id": str(session_id),
                    },
                )
            except Exception:
                logger.warning(
                    "service.webhook.fill_loop_dispatch_failed",
                    extra={
                        "op": "handle_webhook_event",
                        "session_id": str(session_id),
                    },
                    exc_info=True,
                )

            logger.info(
                "service.webhook.connected",
                extra={
                    "op": "handle_webhook_event",
                    "session_id": str(session_id),
                    "status": SessionStatus.CONNECTED.value,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
            )
            return

        if logged_in is False and state.status == SessionStatus.CONNECTED:
            await self._store.publish(
                session_id,
                SSEEvent(
                    name="failed",
                    data={
                        "code": "disconnected",
                        "message": "WhatsApp session disconnected after connect",
                    },
                ),
            )
            await self._store.update(
                session_id,
                status=SessionStatus.FAILED,
                failed_code="disconnected",
            )
            await self._safe_mark_failed(session_id, "disconnected")
            logger.info(
                "service.webhook.disconnected",
                extra={
                    "op": "handle_webhook_event",
                    "session_id": str(session_id),
                    "status": SessionStatus.FAILED.value,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
            )
            return

        # Other connection sub-states are ignored — uazapi sends
        # `loggedIn=False` for every QR refresh, which is normal.
        logger.debug(
            "service.webhook.connection_noop",
            extra={
                "op": "handle_webhook_event",
                "session_id": str(session_id),
                "logged_in": logged_in,
                "status": state.status.value,
            },
        )

    # ------------------------------------------------------------------ #
    # 2b. _handle_messages_event — F4 forward-capture                    #
    # ------------------------------------------------------------------ #

    async def _handle_messages_event(
        self, session_id: UUID, payload: dict[str, Any]
    ) -> None:
        """Parse + persist each incoming/outgoing WhatsApp message (F4 T5).

        uazapi forwards both inbound and outbound messages as a ``messages``
        event (or ``messages.upsert``). We parse each entry, normalize it
        into :class:`CapturedMessageInsert`, and batch-insert via the
        captured_messages repository.

        Failure mode: any exception is **logged and swallowed**. The webhook
        route must always return 2xx so uazapi doesn't retry-storm.
        """
        # Diagnóstico: SEMPRE loga entrada do handler em INFO pra ver no
        # Railway. Diagnosticar "0 msgs capturadas" exige saber se este
        # path roda ou se o webhook nem dispara messages event.
        logger.info(
            "service.webhook.messages.enter",
            extra={
                "session_id": str(session_id),
                "payload_keys": list(payload.keys()) if isinstance(payload, dict) else None,
            },
        )

        state = await self._store.get(session_id)
        if state is None:
            logger.warning(
                "captured.messages.unknown_session",
                extra={"session_id": str(session_id)},
            )
            return

        if state.user_id is None:
            # Race: webhook arrived before signup linked a user_id. We don't
            # have anywhere safe to attribute these rows (FK to auth.users
            # is mandatory), so drop them. uazapi will keep forwarding new
            # ones as the user keeps using WhatsApp.
            logger.warning(
                "captured.messages.no_user_linked",
                extra={"session_id": str(session_id)},
            )
            return

        # The messages array can live at the top level (variant A) or under
        # ``data`` (variant B). Look in both. Also try ``message`` singular
        # (some uazapi tiers send 1 msg at a time as object, not list).
        raw_msgs = payload.get("messages")
        if raw_msgs is None:
            data_block = payload.get("data")
            if isinstance(data_block, dict):
                raw_msgs = data_block.get("messages") or data_block.get("message")
        if raw_msgs is None and isinstance(payload.get("message"), dict):
            raw_msgs = [payload["message"]]
        # Variant: uazapi paid pode mandar a msg solta no body (sem chave
        # 'messages'), com 'key' direto no topo.
        if raw_msgs is None and isinstance(payload.get("key"), dict):
            raw_msgs = [payload]
        # Wrap a single dict into a list pra uniformizar.
        if isinstance(raw_msgs, dict):
            raw_msgs = [raw_msgs]
        if not isinstance(raw_msgs, list):
            logger.info(
                "service.webhook.messages.no_messages_array",
                extra={
                    "session_id": str(session_id),
                    "payload_keys": list(payload.keys()),
                },
            )
            return

        logger.info(
            "service.webhook.messages.parsed_count",
            extra={
                "session_id": str(session_id),
                "raw_count": len(raw_msgs),
            },
        )

        inserts: list[CapturedMessageInsert] = []
        for raw in raw_msgs:
            parsed = _parse_uazapi_message(
                raw, session_id=session_id, user_id=state.user_id
            )
            if parsed is not None:
                inserts.append(parsed)

        if not inserts:
            logger.warning(
                "service.webhook.messages.zero_parsed",
                extra={
                    "session_id": str(session_id),
                    "raw_count": len(raw_msgs),
                    "first_raw_keys": (
                        list(raw_msgs[0].keys()) if raw_msgs and isinstance(raw_msgs[0], dict) else None
                    ),
                },
            )
            return

        try:
            from app.modules.captured_messages import repository as captured_repo  # noqa: WPS433
            inserted = await captured_repo.insert_many(inserts)
            logger.info(
                "service.webhook.messages",
                extra={
                    "session_id": str(session_id),
                    "user_id": str(state.user_id),
                    "count_received": len(raw_msgs),
                    "count_inserted": inserted,
                },
            )
        except Exception:
            # Swallow — webhook MUST stay 200 OK so uazapi doesn't retry-storm.
            logger.exception(
                "captured.messages.insert_failed",
                extra={
                    "session_id": str(session_id),
                    "user_id": str(state.user_id),
                    "count_received": len(raw_msgs),
                },
            )

    # ------------------------------------------------------------------ #
    # 3. _run_extract — fire-and-forget worker wrapper                   #
    # ------------------------------------------------------------------ #

    async def _run_extract(self, session_id: UUID) -> None:
        """Run the extract pipeline as a background task.

        Imports the worker lazily for two reasons:
            * avoid an import cycle (worker → service via `_fail`/`_finalize`)
            * keep this module importable even if T8 hasn't landed yet —
              an ``ImportError`` is logged and we exit cleanly so the rest
              of the service stays usable.
        """
        try:
            from app.workers.extract import extract_30d_pipeline  # noqa: WPS433
        except ImportError:
            logger.warning(
                "service.run_extract.worker_missing",
                extra={
                    "op": "_run_extract",
                    "session_id": str(session_id),
                    "reason": "app.workers.extract not available (T8 pending)",
                },
            )
            return

        try:
            await extract_30d_pipeline(session_id)
        except Exception:  # pragma: no cover — the worker handles its own errors
            logger.exception(
                "service.run_extract.unhandled",
                extra={"op": "_run_extract", "session_id": str(session_id)},
            )

    # ------------------------------------------------------------------ #
    # 4. cancel_session                                                  #
    # ------------------------------------------------------------------ #

    async def cancel_session(self, session_id: UUID) -> None:
        """Manual cancellation (design § 7.4).

        Resolution order:
          1. In-memory store (authoritative when present).
          2. **DB fallback**: se o store esvaziou (reinicio do backend), lê
             a row em ``whatsapp_sessions`` e usa o ``uazapi_token`` lá pra
             liberar o slot + marcar ``disconnected``. Sem fallback o user
             ficaria preso em "connected" eterno após qualquer redeploy.
          3. ``SessionNotFound`` só se NEM memória NEM DB têm a sessão.

        Se já estiver em status terminal (consumed/failed/expired/disconnected),
        retorna silenciosamente (idempotente).
        """
        started = time.monotonic()
        logger.info(
            "service.cancel_session.enter",
            extra={"op": "cancel_session", "session_id": str(session_id)},
        )

        state = await self._store.get(session_id)
        if state is None:
            # Fallback DB: store vazio pós-redeploy. Tenta pegar token do banco.
            row = await repository.get(session_id)
            if row is None:
                raise SessionNotFound(str(session_id))

            db_status = str(row.get("status") or "").lower()
            if db_status in {"consumed", "failed", "expired", "disconnected"}:
                logger.info(
                    "service.cancel_session.db_already_terminal",
                    extra={
                        "op": "cancel_session",
                        "session_id": str(session_id),
                        "db_status": db_status,
                    },
                )
                return

            token = row.get("uazapi_token")
            if token:
                await self._release_provider_slot(
                    token, session_id=session_id, op="cancel_session.fallback"
                )
            try:
                await repository.mark_status(session_id, "disconnected")
            except Exception:  # pragma: no cover — defensive
                logger.exception(
                    "service.cancel_session.fallback_repo_failed",
                    extra={"op": "cancel_session", "session_id": str(session_id)},
                )

            logger.info(
                "service.cancel_session.exit",
                extra={
                    "op": "cancel_session",
                    "session_id": str(session_id),
                    "status": "disconnected",
                    "path": "db_fallback",
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
            )
            return

        if state.status in _TERMINAL_STATUSES:
            logger.info(
                "service.cancel_session.already_terminal",
                extra={
                    "op": "cancel_session",
                    "session_id": str(session_id),
                    "status": state.status.value,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
            )
            return

        # Best effort — provider may already be gone (banned, network blip…).
        await self._release_provider_slot(
            state.uazapi_token, session_id=session_id, op="cancel_session"
        )

        await self._store.publish(
            session_id, SSEEvent(name="expired", data={"reason": "cancelled"})
        )
        await self._store.update(session_id, status=SessionStatus.EXPIRED)
        try:
            await repository.mark_status(session_id, "expired")
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "service.cancel_session.repo_failed",
                extra={"op": "cancel_session", "session_id": str(session_id)},
            )

        logger.info(
            "service.cancel_session.exit",
            extra={
                "op": "cancel_session",
                "session_id": str(session_id),
                "status": SessionStatus.EXPIRED.value,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            },
        )

    # ------------------------------------------------------------------ #
    # 5. consume_extracted — F2 entry point                              #
    # ------------------------------------------------------------------ #

    async def consume_extracted(
        self, session_id: UUID, user_id: UUID
    ) -> ExtractedPayload | None:
        """Hand off da sessão anônima pro user recém-criado.

        **F5 pivot (2026-05-19)**: o comportamento antigo (mark_consumed +
        release_provider_slot) destruía a sessão imediatamente após o
        signup. Fazia sentido no F1+F2 original (extract auto rodava antes
        e o relatório já estava pronto), mas no F5 a sessão precisa
        SOBREVIVER ao signup pra:
          - webhook continuar capturando mensagens em `captured_messages`
          - user gerar quantos relatórios on-demand quiser depois
          - dashboard mostrar status "connected" em vez de cair pra
            empty state pós-signup

        Sequência nova:
            1. Verifica sessão em memória.
            2. Linka user_id na DB row (necessário pra RLS + queries
               futuras de captured_messages).
            3. Cria placeholder de reports row (se ainda não existe), pro
               frontend pollar `/api/reports/latest` enquanto worker corre.
            4. Devolve payload do store (se houver — F1 deprecated path).

        REMOVIDO em F5: mark_consumed (mudava status pra terminal) e
        release_provider_slot (chamava delete_instance). Session segue
        viva como `connected`/`extracted` até user desconectar manualmente
        ou uazapi/WhatsApp encerrar de fato.
        """
        started = time.monotonic()
        logger.info(
            "service.consume_extracted.enter",
            extra={
                "op": "consume_extracted",
                "session_id": str(session_id),
                "user_id": str(user_id),
            },
        )

        # 1. Link user na DB SEMPRE — mesmo se o session_store em memória
        # tiver perdido o state (reinício do Railway entre connect e signup).
        # Bug observado em prod (2026-05-19 01:51:23): row whatsapp_sessions
        # existia no DB com status=connected mas user_id=NULL porque o
        # consume_extracted retornava early quando state era None. Resultado:
        # /api/whatsapp/status (filtra por user_id) nunca achava a session →
        # frontend mostrava "WhatsApp não conectado" mesmo com uazapi vivo.
        try:
            await repository.link_user(session_id, user_id)
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "service.consume_extracted.link_user_failed",
                extra={
                    "op": "consume_extracted",
                    "session_id": str(session_id),
                    "user_id": str(user_id),
                },
            )

        state = await self._store.get(session_id)
        if state is None:
            # Store em memória zerou (provável reinício do backend). DB já
            # foi linkado acima — frontend vai ver session ativa no /status.
            # Sem state em memória não há payload pra devolver nem SSE pra
            # publicar, mas o user segue com a session funcional.
            logger.warning(
                "service.consume_extracted.unknown_session_db_linked",
                extra={
                    "op": "consume_extracted",
                    "session_id": str(session_id),
                    "user_id": str(user_id),
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "note": "DB linkado, store em memória vazio (provável restart)",
                },
            )
            return None

        # F8 REVOGADO: consume_extracted não dispara mais worker de
        # relatório. Se existir alguma row de report órfã (de teste antigo
        # ou re-conexão), apenas linka user_id pra evitar leak de RLS.
        # Relatório real é gerado quando user clica "Gerar relatório" no
        # dashboard pós-login.
        try:
            from app.modules.reports import repository as reports_repo

            existing = await reports_repo.get_existing_for_session(session_id)
            if existing is not None:
                await reports_repo.link_user(session_id, user_id)
                logger.info(
                    "service.consume_extracted.linked_orphan_report",
                    extra={
                        "op": "consume_extracted",
                        "session_id": str(session_id),
                        "user_id": str(user_id),
                        "report_id": str(existing.get("id")),
                        "report_status": existing.get("status"),
                    },
                )
        except Exception:
            logger.warning(
                "service.consume_extracted.report_link_failed",
                extra={
                    "op": "consume_extracted",
                    "session_id": str(session_id),
                    "user_id": str(user_id),
                },
                exc_info=True,
            )

        # F9 (2026-05-19): re-dispatch fill loop pra cobrir restart do backend
        # entre webhook 'connected' e signup. A task original (criada em
        # _handle_connection_event) morreu junto com o processo. O loop é
        # idempotente: confere stats_for_session ANTES de pull e sai cedo se
        # captured_messages já tiver dados.
        try:
            from app.modules.captured_messages import repository as cm_repo
            from app.workers.extract import fill_captured_messages_loop

            cm_stats = await cm_repo.stats_for_session(session_id)
            if cm_stats.get("message_count", 0) == 0:
                asyncio.create_task(
                    fill_captured_messages_loop(session_id),
                    name=f"fill-cm-resume-{session_id}",
                )
                logger.info(
                    "service.consume_extracted.fill_loop_dispatched",
                    extra={
                        "op": "consume_extracted",
                        "session_id": str(session_id),
                        "user_id": str(user_id),
                    },
                )
            else:
                logger.info(
                    "service.consume_extracted.captured_already_populated",
                    extra={
                        "op": "consume_extracted",
                        "session_id": str(session_id),
                        "user_id": str(user_id),
                        "message_count": cm_stats.get("message_count"),
                    },
                )
        except Exception:
            logger.warning(
                "service.consume_extracted.fill_loop_dispatch_failed",
                extra={
                    "op": "consume_extracted",
                    "session_id": str(session_id),
                    "user_id": str(user_id),
                },
                exc_info=True,
            )

        # 2. Pega payload do store SEM marcar consumed.
        # `_store.consume()` marca o state em memória como CONSUMED — mas
        # a session no DB fica como está (connected/extracted). Em memória
        # podemos limpar pra liberar o subscriber bus do SSE; o DB segue
        # autoritativo pra UX (dashboard /status, captured_messages).
        payload = await self._store.consume(session_id)

        # F5: mark_consumed REMOVIDO. Status no DB segue connected/extracted
        # indefinidamente — webhook continua capturando msgs, user pode
        # gerar relatórios on-demand quantas vezes quiser.
        #
        # F5: release_provider_slot REMOVIDO. Manter a instância uazapi viva
        # pós-signup é essencial pro forward-capture funcionar. Quando user
        # quiser desconectar, ele clica "Desconectar" na UI (cancel_session
        # cuida do delete_instance correto).

        logger.info(
            "service.consume_extracted.exit",
            extra={
                "op": "consume_extracted",
                "session_id": str(session_id),
                "preserved_status": state.status.value,
                "had_payload": payload is not None,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return payload

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #

    async def _enforce_rate_limit(self, client_ip: str) -> None:
        """Append ``now`` to the bucket, prune stale entries, enforce cap.

        Uses ``time.monotonic`` so we are immune to wall-clock jumps. A
        single lock guards the whole bucket dict — contention is tiny since
        each call is O(window/avg_arrival_rate).
        """
        now = time.monotonic()
        async with self._rate_lock:
            bucket = self._rate_buckets.setdefault(client_ip, [])
            # Prune anything older than the window — in-place rebuild keeps
            # the list short without copying the world.
            cutoff = now - _RATE_LIMIT_WINDOW_S
            fresh = [ts for ts in bucket if ts >= cutoff]
            fresh.append(now)
            self._rate_buckets[client_ip] = fresh

            if len(fresh) > _RATE_LIMIT_MAX_ATTEMPTS:
                logger.warning(
                    "service.rate_limit.exceeded",
                    extra={
                        "op": "create_session",
                        "client_ip": client_ip,
                        "attempts": len(fresh),
                        "window_s": int(_RATE_LIMIT_WINDOW_S),
                    },
                )
                raise RateLimitExceeded("too_many_sessions")

    async def _release_provider_slot(
        self,
        session_token: str,
        *,
        session_id: UUID,
        op: str,
    ) -> None:
        """Free the provider's device slot (disconnect + delete in one call).

        WPP-11 demands disconnect on session finalization. uazapi's
        ``DELETE /instance`` does both atomically and removes the database
        row, freeing the tenant's device-slot for the next visitor. We don't
        need a separate disconnect call. Best-effort: if delete fails we log
        and continue — the session is already in a terminal state and the
        free-tier auto-deletes after 1h anyway.
        """
        try:
            await self._provider.delete_instance(session_token)
        except UazapiError as exc:
            logger.warning(
                "service.release_slot.delete_failed",
                extra={
                    "op": op,
                    "session_id": str(session_id),
                    "error_class": type(exc).__name__,
                    "error_code": getattr(exc, "code", "unknown"),
                },
            )

    async def _safe_mark_failed(self, session_id: UUID, code: str) -> None:
        """Try to mark a session as failed; swallow secondary errors."""
        try:
            await repository.mark_failed(session_id, code)
        except Exception:  # pragma: no cover — best effort
            logger.warning(
                "service.safe_mark_failed.swallowed",
                extra={
                    "op": "safe_mark_failed",
                    "session_id": str(session_id),
                    "code": code,
                },
            )


# ---------------------------------------------------------------------------
# Module-level factory (memoized)
# ---------------------------------------------------------------------------

_service_singleton: WhatsAppService | None = None


def get_service() -> WhatsAppService:
    """Return the process-wide :class:`WhatsAppService` singleton.

    Memoized — the first call wires the production provider, the singleton
    in-memory store, and the configured callback base URL. Subsequent calls
    return the same instance so the rate-limit buckets are shared across
    requests.

    Tests that need a fresh instance can simply construct ``WhatsAppService``
    directly with mocks; they should not poke at this singleton.
    """
    global _service_singleton
    if _service_singleton is None:
        _service_singleton = WhatsAppService(
            provider=get_provider(),
            store=session_store,
            callback_base_url=settings.API_BASE_URL,
        )
    return _service_singleton


# ---------------------------------------------------------------------------
# uazapi message parser (F4 T5)
# ---------------------------------------------------------------------------


def _parse_uazapi_message(
    raw: Any,
    *,
    session_id: UUID,
    user_id: UUID,
) -> CapturedMessageInsert | None:
    """Normalize a single uazapi message dict into :class:`CapturedMessageInsert`.

    Suporta DOIS shapes diferentes (uazapi varia entre canais):

    **Shape A — Baileys/webhook nested**:
    ```
    {key: {remoteJid, id, fromMe}, messageTimestamp,
     message: {conversation | extendedTextMessage.text | imageMessage.caption | ...}}
    ```

    **Shape B — uazapi REST flat** (do /message/find e webhooks recentes):
    ```
    {chatid, messageid, messageTimestamp, fromMe, sender, senderName,
     text, content, messageType: "StickerMessage" | "conversation" | ...}
    ```

    LID handling: quando ``chatid`` termina com ``@lid`` (locally-anchored
    identity de contatos novos do WhatsApp), aceita mas loga warning —
    futuras versões podem mapear via /chat/details (wa_chatlid field).

    Returns ``None`` em payload sem chatid OU sem timestamp válido. Caller
    pula o item.
    """
    if not isinstance(raw, dict):
        return None

    # --- chatid: pode vir flat (shape B) ou em key.remoteJid (shape A) ---
    key = raw.get("key") if isinstance(raw.get("key"), dict) else {}
    wa_chatid = (
        raw.get("chatid")          # uazapi REST flat
        or key.get("remoteJid")    # Baileys webhook nested
        or raw.get("remoteJid")    # webhook flat (fallback)
    )
    if not wa_chatid:
        return None
    wa_chatid = str(wa_chatid)

    # LID detection: contato novo do WhatsApp pode vir como @lid em vez do
    # @s.whatsapp.net que conhecemos. Salvamos como veio mas logamos pra
    # observabilidade. Solução completa exige cache LID↔JID via /chat/details.
    if wa_chatid.endswith("@lid"):
        logger.info(
            "captured.parse.lid_chatid",
            extra={
                "session_id": str(session_id),
                "wa_chatid": wa_chatid,
            },
        )

    # --- messageid e fromMe (shape A nested, shape B flat) ---
    raw_message_id = (
        raw.get("messageid")  # uazapi flat
        or key.get("id")
        or raw.get("id")
    )
    is_from_me = bool(
        raw.get("fromMe")  # flat (presente em ambos shapes B e webhook)
        or key.get("fromMe")
    )

    # --- timestamp: pode vir em segundos OU milissegundos ---
    ts_unix = (
        raw.get("messageTimestamp")
        or raw.get("timestamp")
        or raw.get("ts")
    )
    if ts_unix is None:
        return None
    try:
        ts_int = int(ts_unix)
    except (TypeError, ValueError):
        return None
    # Heurística: >10^10 = milissegundos. uazapi REST manda em ms.
    if ts_int > 10_000_000_000:
        ts_int = ts_int // 1000
    try:
        ts = datetime.fromtimestamp(ts_int, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None

    # --- text + message_type: shape A (nested message) OU shape B (flat text + messageType) ---
    text: str | None = None
    message_type: str = "other"

    flat_text = raw.get("text")
    flat_type = raw.get("messageType")
    if isinstance(flat_text, str) and flat_text:
        text = flat_text
    if isinstance(flat_type, str) and flat_type:
        # uazapi REST manda capitalized ("StickerMessage", "ImageMessage").
        # Normalizamos pra valores compatíveis com nosso MessageType enum.
        lowered = flat_type.lower().replace("message", "")
        if lowered in ("conversation", "extendedtext", "extendedtextmessage", "chat", ""):
            message_type = "text"
        elif lowered in ("image", "audio", "video", "sticker", "document"):
            message_type = lowered
        else:
            message_type = "other"

    # Shape A (Baileys nested) — só executado se flat não preencheu.
    msg = raw.get("message")
    if (text is None or message_type == "other") and isinstance(msg, dict):
        if "conversation" in msg and isinstance(msg["conversation"], str):
            text = text or msg["conversation"]
            message_type = "text"
        elif "extendedTextMessage" in msg:
            ext = msg["extendedTextMessage"]
            if isinstance(ext, dict):
                inner_text = ext.get("text")
                if isinstance(inner_text, str):
                    text = text or inner_text
                message_type = "text"
        elif "imageMessage" in msg:
            img = msg["imageMessage"]
            if isinstance(img, dict):
                caption = img.get("caption")
                if isinstance(caption, str):
                    text = text or caption
            message_type = "image"
        elif "audioMessage" in msg:
            message_type = "audio"
        elif "videoMessage" in msg:
            message_type = "video"
        elif "stickerMessage" in msg:
            message_type = "sticker"
        elif "documentMessage" in msg:
            message_type = "document"

    # --- contact_name: pushName/notify (webhook) ou senderName (REST) ---
    contact_name = (
        raw.get("senderName")
        or raw.get("pushName")
        or raw.get("notify")
    )
    if contact_name is not None and not isinstance(contact_name, str):
        contact_name = None

    return CapturedMessageInsert(
        user_id=user_id,
        whatsapp_session_id=session_id,
        wa_chatid=str(wa_chatid),
        contact_name=contact_name,
        ts=ts,
        is_from_me=is_from_me,
        message_type=message_type,  # type: ignore[arg-type]  # narrowed to MessageType by schema
        text=text,
        raw_message_id=str(raw_message_id) if raw_message_id is not None else None,
    )


def _payload_says_connected(payload: Any) -> bool:
    """Verdadeiro se o payload sinaliza conexão estabelecida.

    Aceita o shape do webhook (``{'instance': {'status': 'connected'}}``) E
    o shape do GET /instance/status quando os campos vêm flat. Usado pelo
    poll fallback pra reusar :meth:`_handle_connection_event` sem precisar
    sintetizar um payload — passamos o que veio direto.
    """
    if not isinstance(payload, dict):
        return False
    instance = payload.get("instance")
    if isinstance(instance, dict):
        status = str(instance.get("status") or "").lower()
        if status == "connected":
            return True
    status = str(payload.get("status") or "").lower()
    if status == "connected":
        return True
    data = payload.get("data") if isinstance(payload.get("data"), dict) else None
    if data:
        status = str(data.get("status") or data.get("state") or "").lower()
        if status in ("connected", "open"):
            return True
        if data.get("loggedIn") is True or data.get("logged_in") is True:
            return True
    return False


# F8 REVOGADO (2026-05-19): pre-generate no webhook complicou demais.
# Voltamos pro fluxo simples: user clica "Gerar relatório" no dashboard
# pós-login. Caminho conhecido e estável (~17s).


__all__ = [
    "WhatsAppService",
    "ServiceError",
    "RateLimitExceeded",
    "SessionNotFound",
    "get_service",
]
