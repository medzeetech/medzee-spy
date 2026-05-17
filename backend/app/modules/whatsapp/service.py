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
import time
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from app.clients.whatsapp import WhatsAppProvider, get_provider
from app.clients.whatsapp.errors import UazapiError
from app.core.config import settings
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
_RATE_LIMIT_WINDOW_S: float = 300.0   # 5 minutes
_RATE_LIMIT_MAX_ATTEMPTS: int = 3     # > 3 in the window → reject

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

    async def create_session(self, client_ip: str) -> CreateSessionResponse:
        """Create a fresh WhatsApp session and return the QR payload.

        Flow (design § 7.1):
            1. WPP-16 rate-limit check by IP.
            2. ``provider.create_session()`` → ``ProviderSession``.
            3. Generate ``session_id = uuid4()``.
            4. Register the per-session webhook on uazapi.
            5. Persist the row in ``medzee.whatsapp_sessions`` (status=pending).
            6. Register the in-memory state with the QR.
            7. Return the public response.

        On any ``UazapiError`` after step 2 we make a *best effort* to mark
        the just-created session as failed in the DB so we don't leave dead
        rows lying around. We then re-raise the original exception so the
        route can translate it into the correct HTTP status (503/502/504).
        """
        started = time.monotonic()
        logger.info(
            "service.create_session.enter",
            extra={"op": "create_session", "client_ip": client_ip},
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
            )
            await self._store.create(
                session_id,
                uazapi_token=provider_session.session_token,
                qr_base64=provider_session.qr_base64,
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
        """Process a uazapi webhook callback (design § 7.3).

        Only ``event="connection"`` is meaningful in M1:

        * ``loggedIn=True`` → mark the session connected, publish ``connected``
          via SSE, and **fire-and-forget** the extract task (T8).
        * ``loggedIn=False`` AND current status is ``CONNECTED`` → treat as
          a post-connection drop: publish ``failed`` with ``code=disconnected``
          and mark the session failed.

        Unknown sessions are a silent no-op — uazapi may deliver to a
        session that's already been expired locally; we do not want to leak
        a 404 nor let the webhook retry hammer us.

        Any other event (e.g. ``messages``) is ignored — M1 pulls history
        via REST in the extract pipeline.
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

        logger.info(
            "service.webhook.enter session_id=%s event=%s keys=%s data_keys=%s",
            session_id,
            event,
            list(payload.keys()) if isinstance(payload, dict) else "<not-dict>",
            list(data.keys()) if isinstance(data, dict) else "<not-dict>",
        )

        state = await self._store.get(session_id)
        if state is None:
            logger.info(
                "service.webhook.unknown_session session_id=%s elapsed_ms=%d",
                session_id,
                int((time.monotonic() - started) * 1000),
            )
            return

        # uazapi (confirmed via captured payloads) sends connection webhooks
        # with this shape:
        #     {
        #       "EventType": "connection",
        #       "instance": {"name": "...", "status": "connected"|"disconnected"},
        #       "instanceName": "...",
        #       "owner": "5511XXXXXXXX",      # set when status=connected
        #       "token": "...",
        #       "type": "LoggedOut"           # present on logout
        #     }
        is_connection_event = (
            "connection" in event.lower()
            or "connected" in event.lower()
            or "loggedIn" in data
            or "logged_in" in data
        )

        if not is_connection_event:
            logger.info(
                "service.webhook.ignored_event session_id=%s event=%s",
                session_id, event,
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
                session_id, "connected", phone_masked=phone
            )
            await self._store.publish(
                session_id, SSEEvent(name="connected", data={"phone": phone})
            )
            # Fire-and-forget the extract pipeline. We deliberately do not
            # await it — the webhook handler must return < 5s (design § 7.3).
            # The worker module is imported lazily inside `_run_extract` so
            # this file remains importable even before T8 lands.
            asyncio.create_task(
                self._run_extract(session_id),
                name=f"extract-{session_id}",
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
        # If the session is already in FAILED / EXPIRED / CONSUMED, some other
        # path (extract failure cleanup, TTL expire loop, cancel_session, or
        # a previous consume_extracted call) already issued `DELETE /instance`
        # on the provider. Reissuing it would just be a stale-token 401 in
        # uazapi and pollute the logs with `service.release_slot.delete_failed`.
        # EXTRACTED is the happy-path entry (payload cached, slot still ours)
        # — we DO release in that case.
        entry_status = state.status
        already_released = entry_status in {
            SessionStatus.FAILED,
            SessionStatus.EXPIRED,
            SessionStatus.CONSUMED,
        }

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

        # 1b. F3 §REPORT-12: link the user to the report row if it exists.
        # The report row is created by the extract → report worker as soon as
        # the payload is cached; on the happy path it's already there by the
        # time signup arrives. If the worker hasn't created the row yet (race),
        # this no-ops and the worker will pick up user_id when it later reads
        # whatsapp_sessions.user_id. Lazy import avoids a circular dep.
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

        # 4. Free the WhatsApp number AND the provider slot (best effort) —
        # but only if no upstream path already deleted the uazapi instance.
        if already_released:
            logger.info(
                "service.consume_extracted.release_skipped",
                extra={
                    "op": "consume_extracted",
                    "session_id": str(session_id),
                    "entry_status": entry_status.value,
                    "reason": "provider instance already deleted upstream",
                },
            )
        else:
            await self._release_provider_slot(
                state.uazapi_token, session_id=session_id, op="consume_extracted"
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


__all__ = [
    "WhatsAppService",
    "ServiceError",
    "RateLimitExceeded",
    "SessionNotFound",
    "get_service",
]
