"""HTTP routes for the auth module (F2 design § 7 / 11).

Thin wrappers over :class:`AuthService` (T7). Routes only:

* validate the body via pydantic schemas (T2);
* call the service;
* translate service exceptions to the HTTP error shapes from design § 11;
* envelope success responses with ``SuccessResponse[...]``.

No business logic here. Logging is also minimal — the service emits the
structured detail (``op``, ``user_id``, ``email_domain``, ``elapsed_ms``).
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.contracts.responses import SuccessResponse
from app.core.security import get_current_user_id
from app.modules.auth.schemas import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    SignupRequest,
    SignupResponse,
    UpdateMeRequest,
)
from app.modules.auth.service import (
    AuthService,
    EmailAlreadyRegistered,
    InvalidCredentials,
    ProfileCreationFailed,
    ProfileNotFound,
    SupabaseAuthError,
    UserNotInSpy,
    get_auth_service,
)
from app.modules.extension.schemas import ExtensionPairingTokenResponse
from app.modules.extension.security import issue_pairing_token

logger = logging.getLogger(__name__)

router = APIRouter()


# ── POST /signup ──────────────────────────────────────────────────────


@router.post(
    "/signup",
    response_model=SuccessResponse[SignupResponse],
    summary="Sign a new user up + (optional) link a WhatsApp session",
)
async def signup(
    req: SignupRequest,
    service: AuthService = Depends(get_auth_service),
) -> SuccessResponse[SignupResponse]:
    try:
        result = await service.signup(req)
    except EmailAlreadyRegistered:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email_already_registered",
        )
    except ProfileCreationFailed:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="profile_creation_failed",
        )
    except SupabaseAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc) or "supabase_auth_error",
        )
    return SuccessResponse(data=result)


# ── POST /login ───────────────────────────────────────────────────────


@router.post(
    "/login",
    response_model=SuccessResponse[LoginResponse],
    summary="Authenticate and return a Supabase session pair",
)
async def login(
    req: LoginRequest,
    service: AuthService = Depends(get_auth_service),
) -> SuccessResponse[LoginResponse]:
    try:
        result = await service.login(req)
    except InvalidCredentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_credentials",
        )
    except UserNotInSpy:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user_not_in_spy",
        )
    except SupabaseAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc) or "supabase_auth_error",
        )
    return SuccessResponse(data=result)


# ── GET /me ───────────────────────────────────────────────────────────


@router.get(
    "/me",
    response_model=SuccessResponse[MeResponse],
    summary="Return the current user's profile",
)
async def get_me(
    user_id: UUID = Depends(get_current_user_id),
    service: AuthService = Depends(get_auth_service),
) -> SuccessResponse[MeResponse]:
    try:
        result = await service.get_me(user_id)
    except ProfileNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="profile_not_found",
        )
    return SuccessResponse(data=result)


# ── PATCH /me ─────────────────────────────────────────────────────────


@router.patch(
    "/me",
    response_model=SuccessResponse[MeResponse],
    summary="Partial update of the current user's profile",
)
async def patch_me(
    req: UpdateMeRequest,
    user_id: UUID = Depends(get_current_user_id),
    service: AuthService = Depends(get_auth_service),
) -> SuccessResponse[MeResponse]:
    try:
        result = await service.update_me(user_id, req)
    except ProfileNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="profile_not_found",
        )
    return SuccessResponse(data=result)


# ── POST /me/extension-pairing-token ──────────────────────────────────


@router.post(
    "/me/extension-pairing-token",
    response_model=SuccessResponse[ExtensionPairingTokenResponse],
    summary="Re-emit a short-lived extension pairing JWT (CHX-15)",
)
async def issue_extension_pairing_token(
    user_id: UUID = Depends(get_current_user_id),
) -> SuccessResponse[ExtensionPairingTokenResponse]:
    """Mint a fresh ``extension_pairing`` JWT for the authenticated user.

    Idempotent — each call returns a brand-new token (different ``iat``/
    ``exp``). The frontend hits this silently when the extension probe
    reports ``paired=false`` despite the user being already signed in,
    typically because the original token emitted at signup expired.
    """
    token = issue_pairing_token(user_id)
    return SuccessResponse(
        data=ExtensionPairingTokenResponse(extension_pairing_token=token)
    )


__all__ = ["router"]
