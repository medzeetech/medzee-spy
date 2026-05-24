"""JWT helpers for the Chrome extension auth flow (F8 / §4.4).

Two token types, both HS256 over ``settings.SUPABASE_JWT_SECRET``:

* ``typ='extension_pairing'`` — short TTL (default 15min), emitted by
  ``/api/auth/signup`` (T6). The extension trades it once at
  ``POST /api/extension/pair`` for a refresh token.
* ``typ='extension_refresh'`` — long TTL (default 30d), used by the
  extension as a ``Bearer`` for every subsequent extension call
  (``/messages``, ``/telemetry``, ``/status``).

Why a custom JWT and not Supabase's own access token? The extension is a
distinct trust tier (anonymous, persistent device, no email/password
flow). We need a separate ``typ`` claim we control end-to-end and a
different TTL — same secret keeps the deploy story simple (already in
the Supabase project), but the claim-space is ours.

PyJWT is used (already an indirect dep, version pinned >=2.10). If a
future migration to ``python-jose`` happens, the only surface to change
is this file.
"""
from __future__ import annotations

import logging
import time
from uuid import UUID

import jwt
from fastapi import Header, HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)


# Claim values for the ``typ`` discriminator. Centralised so the decoder
# and emitters can never drift.
PAIRING_TOKEN_TYP = "extension_pairing"
REFRESH_TOKEN_TYP = "extension_refresh"

_ALGORITHM = "HS256"


# ─── helpers ───────────────────────────────────────────────────────────


def _secret() -> str:
    """Return the JWT secret, failing fast if unconfigured.

    Empty string is a deployment misconfiguration — we'd rather 500 the
    pairing handshake than silently sign tokens with an empty key (which
    PyJWT actually accepts).
    """
    secret = settings.SUPABASE_JWT_SECRET
    if not secret:
        raise RuntimeError(
            "SUPABASE_JWT_SECRET is not configured — extension JWT helpers "
            "cannot operate"
        )
    return secret


def _encode(user_id: UUID, typ: str, ttl_s: int) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "typ": typ,
        "iat": now,
        "exp": now + ttl_s,
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def _decode(token: str, *, expected_typ: str) -> UUID:
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        logger.info(
            "ext.security.decode.expired",
            extra={"expected_typ": expected_typ},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "pairing_expired", "reason": "expired"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        logger.info(
            "ext.security.decode.invalid",
            extra={"expected_typ": expected_typ, "reason": str(exc)[:120]},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "pairing_expired", "reason": "invalid"},
        ) from exc

    if payload.get("typ") != expected_typ:
        logger.info(
            "ext.security.decode.wrong_typ",
            extra={
                "expected_typ": expected_typ,
                "actual_typ": payload.get("typ"),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "pairing_expired", "reason": "wrong_typ"},
        )

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "pairing_expired", "reason": "missing_sub"},
        )
    try:
        return UUID(str(sub))
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "pairing_expired", "reason": "bad_sub"},
        ) from exc


# ─── public API ────────────────────────────────────────────────────────


def issue_pairing_token(user_id: UUID) -> str:
    """Emit a short-lived ``extension_pairing`` JWT for ``user_id``.

    TTL controlled by ``settings.EXTENSION_PAIRING_TOKEN_TTL_S`` (default
    15min). Called from ``AuthService.signup`` (T6).
    """
    return _encode(
        user_id,
        typ=PAIRING_TOKEN_TYP,
        ttl_s=settings.EXTENSION_PAIRING_TOKEN_TTL_S,
    )


def decode_pairing_token(token: str) -> UUID:
    """Validate a pairing token and return its ``user_id``.

    Raises :class:`HTTPException` 401 (``code='pairing_expired'``) on any
    failure: expired, wrong ``typ``, malformed payload, bad signature.
    """
    return _decode(token, expected_typ=PAIRING_TOKEN_TYP)


def issue_refresh_token(user_id: UUID) -> str:
    """Emit a long-lived ``extension_refresh`` JWT for ``user_id``.

    TTL controlled by ``settings.EXTENSION_REFRESH_TOKEN_TTL_S`` (default
    30d). Returned by ``POST /api/extension/pair`` (T7).
    """
    return _encode(
        user_id,
        typ=REFRESH_TOKEN_TYP,
        ttl_s=settings.EXTENSION_REFRESH_TOKEN_TTL_S,
    )


def decode_refresh_token(token: str) -> UUID:
    """Validate a refresh token and return its ``user_id``.

    Raises :class:`HTTPException` 401 (``code='pairing_expired'``) on
    failure — same shape as the pairing variant so the frontend can react
    uniformly (re-emit pairing token, retry).
    """
    return _decode(token, expected_typ=REFRESH_TOKEN_TYP)


def get_current_extension_user(authorization: str = Header(...)) -> UUID:
    """FastAPI dependency: parse ``Bearer <refresh_token>`` → ``user_id``.

    On any failure (missing header, wrong scheme, bad token, expired,
    wrong ``typ``) raises 401 with body ``{"code": "pairing_expired"}``.
    The frontend uses this code to silently re-emit a fresh pairing token
    via ``POST /api/auth/me/extension-pairing-token`` and retry.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "pairing_expired", "reason": "missing_bearer"},
        )
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "pairing_expired", "reason": "empty_token"},
        )
    return decode_refresh_token(token)


__all__ = [
    "PAIRING_TOKEN_TYP",
    "REFRESH_TOKEN_TYP",
    "issue_pairing_token",
    "decode_pairing_token",
    "issue_refresh_token",
    "decode_refresh_token",
    "get_current_extension_user",
]
