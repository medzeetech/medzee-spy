"""HTTP routes for the Chrome extension ingestion module (F8 / §4.2 / T8).

Four endpoints, mounted at ``/api/extension`` by ``app.api.router`` (T9):

* ``POST   /messages``    — receive a batch of captured messages (Supabase JWT)
* ``GET    /status``      — pairing + last-collection status (Supabase JWT)
* ``POST   /telemetry``   — no-PII operational event (Supabase JWT)
* ``POST   /mobile-lead`` — capture a mobile-redirect lead (no auth)

PIVOT (2026-05-24): the ``POST /pair`` endpoint and the custom
``extension_pairing``/``extension_refresh`` JWT pair are gone. The
extension now logs in directly with email+password via Supabase and uses
the standard Supabase access token as ``Bearer`` on every call. Auth on
``/messages``, ``/status`` and ``/telemetry`` is therefore
``Depends(get_current_user_id)`` from :mod:`app.core.security` — the
same validator the rest of the app uses.

Design contracts kept here, not in the service layer:

* **Version gate (CHX-14):** ``X-Extension-Version`` header on ``/messages``
  must be ``>= settings.EXTENSION_MIN_VERSION``. We check it inline in the
  route layer (small ``_assert_version_ok`` helper) so a malformed/old client
  gets a 409 before the body is even handed to the service. The service does
  its own check too (defense in depth — see ``service._is_outdated``).
* **Error envelopes:** 409 ``extension_outdated`` carries
  ``{code, min_version, client_version}`` so the frontend can render an
  "update the extension" banner with the exact required version.
* **Telemetry rate-limit:** the service raises a 429 ``HTTPException`` with
  ``detail={"code": "rate_limited", ...}``; the route layer just lets the
  exception bubble — no try/except here.
* **204 No Content on telemetry:** the success branch returns ``None`` so
  FastAPI emits an empty body with ``Content-Length: 0`` (the explicit
  ``status_code=204`` on the decorator drives that).

This file deliberately stays thin — all business logic lives in
``service.py`` (T7). Route handlers exist only to translate request shape,
plug in the right dependency, and shape the response envelope.
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status

from app.contracts.responses import SuccessResponse
from app.core.config import settings
from app.core.security import get_current_user_id
from app.modules.extension import service
from app.modules.extension.schemas import (
    ExtensionMessageBatch,
    ExtensionStatusResponse,
    ExtensionTelemetryEvent,
    MobileRedirectLeadCreate,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── helpers ───────────────────────────────────────────────────────────


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a ``"1.2.3"``-style version into a tuple of ints.

    Mirrors ``service._parse_version`` — kept duplicated here to avoid a
    cross-module import for one trivial helper (the service is also
    allowed to re-check, which is the whole point of defense-in-depth).
    """
    try:
        return tuple(int(part) for part in v.split("."))
    except (AttributeError, ValueError):
        return (0,)


def _assert_version_ok(version: str | None) -> None:
    """Raise 409 ``extension_outdated`` when the header is below the floor.

    A missing/empty header is treated as outdated — the extension MUST
    send ``X-Extension-Version`` (CHX-14). Logging the rejection lets
    operators detect older clients still in the wild without snooping
    on the payload.
    """
    min_version = settings.EXTENSION_MIN_VERSION
    client = version or ""
    if _parse_version(client) < _parse_version(min_version):
        logger.info(
            "route.extension.messages.version_gate.rejected",
            extra={
                "client_version": client,
                "min_version": min_version,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "extension_outdated",
                "min_version": min_version,
                "client_version": client,
            },
        )


# ─── POST /messages ────────────────────────────────────────────────────


@router.post(
    "/messages",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive a batch of extension-collected messages (CHX-04)",
)
async def receive_messages(
    batch: ExtensionMessageBatch,
    user_id: UUID = Depends(get_current_user_id),
    x_extension_version: str | None = Header(
        default=None, alias="X-Extension-Version"
    ),
) -> dict:
    """Persist one batch of WhatsApp messages collected by the extension.

    Returns **202 Accepted** with a small summary dict; the final batch
    additionally fires the F3 report worker asynchronously (the response
    does **not** wait for it).

    Version gate (CHX-14) runs **before** the service is called so that
    an outdated client gets a clean 409 without touching the DB. The
    service also has its own check against ``batch.extension_version`` —
    when both are present they should agree, but the header is the
    authoritative source.
    """
    _assert_version_ok(x_extension_version)
    return await service.ingest_batch(user_id, batch)


# ─── GET /status ───────────────────────────────────────────────────────


@router.get(
    "/status",
    response_model=SuccessResponse[ExtensionStatusResponse],
    summary="Pairing + last-collection status for the logged-in user",
)
async def get_status_route(
    user_id: UUID = Depends(get_current_user_id),
) -> SuccessResponse[ExtensionStatusResponse]:
    """Return whether the current user has any extension-sourced collection.

    Uses the standard Supabase user JWT — both the frontend SPA and the
    extension itself hit this endpoint with that same token post-pivot.
    """
    result = await service.get_status(user_id)
    return SuccessResponse(data=result)


# ─── POST /telemetry ───────────────────────────────────────────────────


@router.post(
    "/telemetry",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Persist a no-PII telemetry event (CHX-16)",
)
async def telemetry(
    event: ExtensionTelemetryEvent,
    user_id: UUID = Depends(get_current_user_id),
) -> Response:
    """Record one telemetry event. 204 No Content on success.

    ``ExtensionTelemetryEvent`` is ``extra='forbid'`` (T4), so any
    payload that accidentally carries PII (``text``, ``wa_chatid``,
    ``contact_name``, ``msg_id``) is rejected by Pydantic at the wire
    layer with 422 before this handler runs.

    Rate-limit: the service enforces 60/min/user (CHX-16). When
    exceeded it raises an ``HTTPException(429)`` which FastAPI returns
    directly — the route layer does not catch it.
    """
    await service.record_telemetry(user_id, event)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── POST /mobile-lead ─────────────────────────────────────────────────


@router.post(
    "/mobile-lead",
    status_code=status.HTTP_201_CREATED,
    summary="Capture a mobile-redirect lead (anonymous, no auth)",
)
async def mobile_lead(req: MobileRedirectLeadCreate) -> dict:
    """Save a lead from the mobile block screen.

    No authentication: the table grants INSERT to the ``anon`` role
    (migration ``f8_1``). The Pydantic schema enforces email validity;
    everything else is best-effort string capture (UA, source URL).

    Returns a small JSON object so callers can check ``response.json()
    .get("captured")`` for a friendly UI signal.
    """
    await service.capture_mobile_lead(req)
    return {"captured": True}


__all__ = ["router"]
