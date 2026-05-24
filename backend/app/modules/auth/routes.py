"""HTTP routes for the auth module (F2 design § 7 / 11).

Thin wrappers over :class:`AuthService` (T7). Routes only:

* validate the body via pydantic schemas (T2);
* call the service;
* translate service exceptions to the HTTP error shapes from design § 11;
* envelope success responses with ``SuccessResponse[...]``.

No business logic here. Logging is also minimal — the service emits the
structured detail (``op``, ``user_id``, ``email_domain``, ``elapsed_ms``).

PIVOT (2026-05-24): the ``POST /me/extension-pairing-token`` endpoint
was removed alongside the rest of the custom JWT pairing dance. The
extension authenticates via Supabase login directly now, so the
frontend no longer needs a separate token to hand off.
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


__all__ = ["router"]
