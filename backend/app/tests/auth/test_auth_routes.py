"""Integration tests for the 4 auth routes (T12 of F2).

Style mirrors ``app/tests/whatsapp/test_routes.py``:

* ``TestClient(app)`` (sync) for HTTP exercising.
* ``app.dependency_overrides`` swaps ``get_auth_service`` for an ``AuthService``-
  shaped ``MagicMock`` with ``AsyncMock`` methods. For ``GET/PATCH /me`` we
  also override ``get_current_user_id`` so we bypass FastAPI's ``HTTPBearer``
  layer entirely (no token plumbing needed in tests).
* An autouse fixture clears overrides after each test so suites don't bleed.

Scope: routes only — service exceptions → HTTP shapes, body validation, and
the ``SuccessResponse`` envelope. Service internals live in T11's
``test_auth_service.py``.
"""
from __future__ import annotations

from typing import Iterator
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.security import get_current_user_id
from app.modules.auth.schemas import (
    LoginResponse,
    MeResponse,
    SessionPayload,
    SignupResponse,
    UpdateMeRequest,
    UserPayload,
)
from app.modules.auth.service import (
    EmailAlreadyRegistered,
    InvalidCredentials,
    ProfileCreationFailed,
    ProfileNotFound,
    SupabaseAuthError,
    UserNotInSpy,
    get_auth_service,
)


# ---------------------------------------------------------------------------
# Constants + helpers
# ---------------------------------------------------------------------------


FIXED_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
EMAIL = "dr.x@example.com"


def _session_payload() -> SessionPayload:
    return SessionPayload(
        access_token="access_tok_test",
        refresh_token="refresh_tok_test",
        expires_in=3600,
        token_type="bearer",
    )


def _user_payload() -> UserPayload:
    return UserPayload(id=FIXED_USER_ID, email=EMAIL)


def _me_response() -> MeResponse:
    return MeResponse(
        user_id=FIXED_USER_ID,
        name="Dr X",
        email=EMAIL,
        phone="5511999999999",
        ticket_medio=250.0,
        clinic_segment=None,
    )


def _signup_body(**overrides) -> dict:
    body = {
        "name": "Dr X",
        "email": EMAIL,
        "phone": "5511999999999",
        "password": "hunter2",
        "ticket_medio": 250.0,
    }
    body.update(overrides)
    return body


def _login_body(**overrides) -> dict:
    body = {"email": EMAIL, "password": "hunter2"}
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_service() -> MagicMock:
    """``AuthService``-shaped MagicMock with AsyncMock methods.

    Default returns are happy-path stubs; tests set ``side_effect`` /
    ``return_value`` per case.
    """
    svc = MagicMock(name="AuthService")
    svc.signup = AsyncMock(
        name="signup",
        return_value=SignupResponse(
            user=_user_payload(),
            session=_session_payload(),
        ),
    )
    svc.login = AsyncMock(
        name="login",
        return_value=LoginResponse(
            user=_user_payload(), session=_session_payload()
        ),
    )
    svc.get_me = AsyncMock(name="get_me", return_value=_me_response())
    svc.update_me = AsyncMock(name="update_me", return_value=_me_response())
    return svc


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    """Wipe ``app.dependency_overrides`` after every test."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(fake_service: MagicMock) -> TestClient:
    """Sync TestClient with ``get_auth_service`` overridden.

    For ``GET/PATCH /me`` tests that need an authenticated principal, the test
    body additionally installs an override for ``get_current_user_id``.
    """
    app.dependency_overrides[get_auth_service] = lambda: fake_service
    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /api/auth/signup
# ---------------------------------------------------------------------------


def test_post_signup_happy_path(client: TestClient, fake_service: MagicMock) -> None:
    """Service returns SignupResponse → 200 SuccessResponse envelope."""
    response = client.post("/api/auth/signup", json=_signup_body())

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "ok"
    data = body["data"]
    assert data["user"]["id"] == str(FIXED_USER_ID)
    assert data["user"]["email"] == EMAIL
    assert data["session"]["access_token"] == "access_tok_test"
    assert data["session"]["refresh_token"] == "refresh_tok_test"
    assert data["session"]["expires_in"] == 3600
    assert data["session"]["token_type"] == "bearer"
    # PIVOT (2026-05-24): signup no longer ships an extension pairing
    # token — the extension authenticates via Supabase login directly.
    assert "extension_pairing_token" not in data
    fake_service.signup.assert_awaited_once()


def test_post_signup_invalid_body_422(client: TestClient, fake_service: MagicMock) -> None:
    """Empty body → 422 with ``detail`` listing the missing required fields."""
    response = client.post("/api/auth/signup", json={})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail, "expected non-empty pydantic error list"
    missing_fields = {tuple(err["loc"][-1:])[0] for err in detail}
    # name/email/phone/password are required; ticket_medio is optional.
    assert {"name", "email", "phone", "password"}.issubset(missing_fields)
    fake_service.signup.assert_not_awaited()


def test_post_signup_email_duplicate_409(
    client: TestClient, fake_service: MagicMock
) -> None:
    """EmailAlreadyRegistered → 409 detail='email_already_registered'."""
    fake_service.signup.side_effect = EmailAlreadyRegistered(EMAIL)

    response = client.post("/api/auth/signup", json=_signup_body())

    assert response.status_code == 409
    assert response.json() == {"detail": "email_already_registered"}


def test_post_signup_profile_failure_500(
    client: TestClient, fake_service: MagicMock
) -> None:
    """ProfileCreationFailed → 500 detail='profile_creation_failed'."""
    fake_service.signup.side_effect = ProfileCreationFailed(str(FIXED_USER_ID))

    response = client.post("/api/auth/signup", json=_signup_body())

    assert response.status_code == 500
    assert response.json() == {"detail": "profile_creation_failed"}


def test_post_signup_supabase_error_400(
    client: TestClient, fake_service: MagicMock
) -> None:
    """SupabaseAuthError → 400 with the wrapped Supabase message as detail."""
    fake_service.signup.side_effect = SupabaseAuthError("password is too weak")

    response = client.post("/api/auth/signup", json=_signup_body())

    assert response.status_code == 400
    assert response.json() == {"detail": "password is too weak"}


# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------


def test_post_login_happy_path(client: TestClient, fake_service: MagicMock) -> None:
    """LoginResponse → 200 SuccessResponse envelope."""
    response = client.post("/api/auth/login", json=_login_body())

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "ok"
    data = body["data"]
    assert data["user"]["id"] == str(FIXED_USER_ID)
    assert data["user"]["email"] == EMAIL
    assert data["session"]["access_token"] == "access_tok_test"
    fake_service.login.assert_awaited_once()


def test_post_login_invalid_credentials_401(
    client: TestClient, fake_service: MagicMock
) -> None:
    """InvalidCredentials → 401 detail='invalid_credentials'."""
    fake_service.login.side_effect = InvalidCredentials()

    response = client.post("/api/auth/login", json=_login_body())

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_credentials"}


def test_post_login_user_not_in_spy_403(
    client: TestClient, fake_service: MagicMock
) -> None:
    """UserNotInSpy → 403 detail='user_not_in_spy'."""
    fake_service.login.side_effect = UserNotInSpy(str(FIXED_USER_ID))

    response = client.post("/api/auth/login", json=_login_body())

    assert response.status_code == 403
    assert response.json() == {"detail": "user_not_in_spy"}


def test_post_login_supabase_error_400(
    client: TestClient, fake_service: MagicMock
) -> None:
    """SupabaseAuthError → 400 with the wrapped message as detail."""
    fake_service.login.side_effect = SupabaseAuthError("rate limited")

    response = client.post("/api/auth/login", json=_login_body())

    assert response.status_code == 400
    assert response.json() == {"detail": "rate limited"}


# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------


def test_get_me_without_token_returns_401_or_403(
    client: TestClient, fake_service: MagicMock
) -> None:
    """No Authorization header → FastAPI ``HTTPBearer`` rejects the request.

    With ``HTTPBearer(auto_error=True)`` (the default — see
    ``app/core/security.py``), a missing/empty Authorization header yields
    **403 Forbidden** with ``detail == 'Not authenticated'``. We accept either
    401 or 403 because some FastAPI/Starlette combos emit 401 here, but on the
    current pin it is **403**. ``get_current_user_id`` is NOT overridden so
    the real auth dependency runs and short-circuits before the service.
    """
    response = client.get("/api/auth/me")

    assert response.status_code in (401, 403)
    # Document the actual code observed in CI for this pin: 403 Not authenticated.
    fake_service.get_me.assert_not_awaited()


def test_get_me_authenticated_200(client: TestClient, fake_service: MagicMock) -> None:
    """Authenticated principal → 200 SuccessResponse[MeResponse]."""
    app.dependency_overrides[get_current_user_id] = lambda: FIXED_USER_ID

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "ok"
    data = body["data"]
    assert data["user_id"] == str(FIXED_USER_ID)
    assert data["name"] == "Dr X"
    assert data["email"] == EMAIL
    assert data["phone"] == "5511999999999"
    assert data["ticket_medio"] == 250.0
    assert data["clinic_segment"] is None
    fake_service.get_me.assert_awaited_once_with(FIXED_USER_ID)


def test_get_me_profile_not_found_404(
    client: TestClient, fake_service: MagicMock
) -> None:
    """ProfileNotFound → 404 detail='profile_not_found'."""
    app.dependency_overrides[get_current_user_id] = lambda: FIXED_USER_ID
    fake_service.get_me.side_effect = ProfileNotFound(str(FIXED_USER_ID))

    response = client.get("/api/auth/me")

    assert response.status_code == 404
    assert response.json() == {"detail": "profile_not_found"}


# ---------------------------------------------------------------------------
# PATCH /api/auth/me
# ---------------------------------------------------------------------------


def test_patch_me_partial_200(client: TestClient, fake_service: MagicMock) -> None:
    """Partial update → 200 envelope; service called with UpdateMeRequest.

    Only ``phone`` is sent; the other fields on ``UpdateMeRequest`` must
    surface as ``None`` so the service's ``model_dump(exclude_none=True)``
    sees a single key.
    """
    app.dependency_overrides[get_current_user_id] = lambda: FIXED_USER_ID

    response = client.patch("/api/auth/me", json={"phone": "5511999999999"})

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "ok"
    assert body["data"]["phone"] == "5511999999999"

    fake_service.update_me.assert_awaited_once()
    args, _kwargs = fake_service.update_me.call_args
    # Signature: update_me(user_id, UpdateMeRequest)
    assert args[0] == FIXED_USER_ID
    sent: UpdateMeRequest = args[1]
    assert isinstance(sent, UpdateMeRequest)
    assert sent.phone == "5511999999999"
    assert sent.name is None
    assert sent.ticket_medio is None
    assert sent.clinic_segment is None
