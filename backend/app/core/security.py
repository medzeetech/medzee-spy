from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.clients.supabase import get_supabase_client

bearer_scheme = HTTPBearer()


async def get_current_user_id_optional(request: Request) -> UUID | None:
    """Like :func:`get_current_user_id` but returns ``None`` when the request
    has no/invalid Authorization header instead of raising.

    Used by endpoints that work for both anonymous and authenticated users:
    e.g. ``POST /api/whatsapp/sessions`` — called from ``/spy`` (anon, signup
    will link later) AND from ``/app/connect`` (authenticated, link
    immediately so webhook ``messages`` already has the user).
    """
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    try:
        supabase = get_supabase_client()
        user_response = supabase.auth.get_user(token)
        user = getattr(user_response, "user", None)
        if user is None or getattr(user, "id", None) is None:
            return None
        return UUID(str(user.id))
    except Exception:
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    supabase = get_supabase_client()
    try:
        user_response = supabase.auth.get_user(credentials.credentials)
        return user_response.user
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> UUID:
    supabase = get_supabase_client()
    try:
        user_response = supabase.auth.get_user(credentials.credentials)
        user = user_response.user
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_token",
        )
    if user is None or getattr(user, "id", None) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_token",
        )
    return UUID(str(user.id))
