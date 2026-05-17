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
from app.clients.whatsapp.errors import UazapiError
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
        callback_url = (
            f"{self._callback_base_url}/api/whatsapp/webhook"
            f"?session_id={session_id}"
        )

        try:
            await self._provider.register_webhook(
                provider_session.session_token, callback_url
            )
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
        except UazapiError as exc:
            # Mark whatever made it into the DB as failed (best effort).
            await self._safe_mark_failed(session_id, getattr(exc, "code", "unknown"))
            logger.warning(
                "service.create_session.post_provider_failed",
                extra={
                    "op": "create_session",
                    "session_id": str(session_id),
                    "error_class": type(exc).__name__,
                    "error_code": getattr(exc, "code", "unknown"),
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
            )
            raise

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
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return response

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
            # F4 pivot (2026-05-17): extract_30d_pipeline está deprecated
            # (vide STATE.md D4/B3/D8 + workers/extract.py docstring). NÃO
            # disparamos mais o F1 pull-history aqui — F4 captura as
            # mensagens forward via webhook event='messages', e o relatório
            # é on-demand via POST /api/reports/generate. Re-habilitar o
            # callsite abaixo só se um dia migrarmos pra provider com
            # /chat/find funcional.
            #
            # asyncio.create_task(
            #     self._run_extract(session_id),
            #     name=f"extract-{session_id}",
            # )
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

        Looks up the session; raises :class:`SessionNotFound` if missing.
        If already in a terminal status, returns silently (idempotent).
        Otherwise: best-effort ``provider.disconnect``, publish ``expired``,
        mark the state + DB row as ``expired``.
        """
        started = time.monotonic()
        logger.info(
            "service.cancel_session.enter",
            extra={"op": "cancel_session", "session_id": str(session_id)},
        )

        state = await self._store.get(session_id)
        if state is None:
            raise SessionNotFound(str(session_id))

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
        """Hand off the cached extract to F2 + finalize the session.

        Sequence (WPP-11):
            1. Verify the session still exists in memory.
            2. Link the (anonymous) DB row to the user that just signed up.
            3. Pull the payload out of the store (also marks it CONSUMED).
            4. Persist the consumed status.
            5. Best-effort ``provider.disconnect`` — keeps WhatsApp number free.
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

        state = await self._store.get(session_id)
        if state is None:
            logger.warning(
                "service.consume_extracted.unknown_session",
                extra={
                    "op": "consume_extracted",
                    "session_id": str(session_id),
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
            )
            return None

        # Capture the entry status BEFORE step 2 transitions it to CONSUMED.
        # Releasing the provider slot is ONLY safe when the extract worker
        # has cleanly finished (entry_status == EXTRACTED). Any other state
        # means either: extract still running (EXTRACTING/CONNECTED — killing
        # the instance would crash the in-flight worker), already cleaned up
        # by upstream (FAILED/EXPIRED), or rare re-entry (CONSUMED).
        # Letting the uazapi instance live to its natural 1h TTL when we
        # arrive mid-extract is far better than yanking it out — gives the
        # worker a chance to complete even when the signup races ahead.
        entry_status = state.status
        should_release_slot = entry_status == SessionStatus.EXTRACTED

        # 1. Link user (will be required for RLS on future reads).
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

        # 1b. F4 pivot: NÃO criamos mais placeholder de reports aqui.
        # No fluxo F3 (deprecated) o signup criava um row 'generating' pra
        # frontend já mostrar "Análise IA em curso". Mas em F4 o relatório
        # é on-demand (user clica botão "Gerar relatório"), não auto. Criar
        # placeholder aqui causa o "stuck em 95%" porque polling vê
        # 'generating' eterno sem nunca um worker rodar.
        #
        # Em vez disso: APENAS linkar user_id em rows preexistentes (caso
        # raro de re-signup após desconectar). Não-rows = no-op silencioso.
        try:
            from app.modules.reports import repository as reports_repo
            await reports_repo.link_user(session_id, user_id)
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

        # 2. Consume the in-memory payload (also marks state.consumed).
        payload = await self._store.consume(session_id)

        # 3. Persist the consumed status (best effort).
        try:
            await repository.mark_consumed(session_id)
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "service.consume_extracted.mark_consumed_failed",
                extra={
                    "op": "consume_extracted",
                    "session_id": str(session_id),
                },
            )

        # 4. Free the WhatsApp number AND the provider slot — only when
        # the extract worker has cleanly handed off (status was EXTRACTED).
        # In every other state we let the uazapi 1h TTL run its course;
        # killing the instance mid-extract is exactly what made the smoke
        # fail at 23s instead of completing.
        if should_release_slot:
            await self._release_provider_slot(
                state.uazapi_token, session_id=session_id, op="consume_extracted"
            )
        else:
            logger.info(
                "service.consume_extracted.release_skipped",
                extra={
                    "op": "consume_extracted",
                    "session_id": str(session_id),
                    "entry_status": entry_status.value,
                    "reason": "extract not done yet OR slot already freed upstream",
                },
            )

        logger.info(
            "service.consume_extracted.exit",
            extra={
                "op": "consume_extracted",
                "session_id": str(session_id),
                "status": SessionStatus.CONSUMED.value,
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
    """Normalize a single uazapi message dict into a :class:`CapturedMessageInsert`.

    Tolerates three known shapes (and falls back to ``message_type='other'``
    with ``text=None`` for anything we don't yet model):

    1. **Plain text** — ``message.conversation``
    2. **Extended text** (replies, mentions, formatting) — ``message.extendedTextMessage.text``
    3. **Image with caption** — ``message.imageMessage.caption``

    Returns ``None`` on any shape we can't safely attribute (missing chatid,
    missing/invalid timestamp, non-dict input). The caller treats ``None``
    as "skip this row, keep going".
    """
    if not isinstance(raw, dict):
        return None

    key = raw.get("key") or {}
    if not isinstance(key, dict):
        key = {}

    wa_chatid = key.get("remoteJid") or raw.get("remoteJid")
    if not wa_chatid:
        return None

    raw_message_id = key.get("id") or raw.get("id")
    is_from_me = bool(key.get("fromMe") or raw.get("fromMe"))

    ts_unix = raw.get("messageTimestamp") or raw.get("timestamp")
    if ts_unix is None:
        return None
    try:
        ts = datetime.fromtimestamp(int(ts_unix), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None

    msg = raw.get("message")
    text: str | None = None
    message_type: str = "other"
    if isinstance(msg, dict):
        if "conversation" in msg and isinstance(msg["conversation"], str):
            text = msg["conversation"]
            message_type = "text"
        elif "extendedTextMessage" in msg:
            ext = msg["extendedTextMessage"]
            if isinstance(ext, dict):
                inner_text = ext.get("text")
                if isinstance(inner_text, str):
                    text = inner_text
                message_type = "text"
        elif "imageMessage" in msg:
            img = msg["imageMessage"]
            if isinstance(img, dict):
                caption = img.get("caption")
                if isinstance(caption, str):
                    text = caption
            message_type = "image"
        elif "audioMessage" in msg:
            message_type = "audio"
        elif "videoMessage" in msg:
            message_type = "video"
        elif "stickerMessage" in msg:
            message_type = "sticker"
        elif "documentMessage" in msg:
            message_type = "document"

    contact_name = raw.get("pushName") or raw.get("notify")
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


__all__ = [
    "WhatsAppService",
    "ServiceError",
    "RateLimitExceeded",
    "SessionNotFound",
    "get_service",
]
