"""Integration tests for ``POST /api/auth/me/extension-pairing-token`` (F8-T6).

The endpoint mints a fresh ``extension_pairing`` JWT for the authenticated
caller. Tested concerns:

1. Happy path: an authenticated user gets 200 + a valid token round-trippable
   via ``decode_pairing_token``.
2. Auth guard: no Bearer header → 401/403 (FastAPI's ``HTTPBearer`` rejects
   before our handler runs).
3. Idempotency: two consecutive calls return *distinct* tokens (different
   ``iat``/``exp`` claims) — both decodable.
4. Token sub claim equals the requesting user_id.

Style mirrors ``test_auth_routes.py``: ``TestClient`` + ``app.dependency_overrides``
to bypass the real Supabase-backed ``get_current_user_id``. The JWT secret is
seeded by the autouse fixture in ``conftest.py``.
"""
from __future__ import annotations

import time
from typing import Iterator
from uuid import UUID

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import get_current_user_id
from app.main import app
from app.modules.extension.security import (
    PAIRING_TOKEN_TYP,
    decode_pairing_token,
)


FIXED_USER_ID = UUID("00000000-0000-0000-0000-0000000000a1")
ENDPOINT = "/api/auth/me/extension-pairing-token"


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    """Reset dependency overrides between tests so suites don't bleed."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def authed_client(client: TestClient) -> TestClient:
    """Bypass ``HTTPBearer`` + Supabase by forcing ``get_current_user_id``."""
    app.dependency_overrides[get_current_user_id] = lambda: FIXED_USER_ID
    return client


# ─── 1. Happy path ─────────────────────────────────────────────────────


def test_authenticated_user_gets_200_and_valid_token(
    authed_client: TestClient,
) -> None:
    response = authed_client.post(ENDPOINT)

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "ok"
    token = body["data"]["extension_pairing_token"]
    assert isinstance(token, str) and token, "expected a non-empty JWT"

    # The token must decode cleanly via the extension's helper (same secret,
    # ``typ='extension_pairing'``, not expired).
    decoded_uid = decode_pairing_token(token)
    assert decoded_uid == FIXED_USER_ID


# ─── 2. Unauthenticated → 401 (or 403 on this FastAPI pin) ─────────────


def test_unauthenticated_request_is_rejected(client: TestClient) -> None:
    """No Authorization header → FastAPI's ``HTTPBearer`` short-circuits.

    On the current pin this surfaces as **403 Forbidden** (``Not authenticated``),
    but spec-wise the contract is "unauthenticated calls are rejected", so we
    accept either code — same shape as ``test_get_me_without_token_returns_401_or_403``.
    """
    response = client.post(ENDPOINT)

    assert response.status_code in (401, 403)


# ─── 3. Idempotency: distinct iat/exp across consecutive calls ─────────


def test_consecutive_calls_return_distinct_tokens(
    authed_client: TestClient,
) -> None:
    """Two back-to-back calls must mint two *different* JWTs.

    JWT ``iat`` is second-resolution. We sleep just past the second boundary
    between calls so the encoded payload differs deterministically — relying
    on monotonic execution time alone is flaky on fast machines.
    """
    r1 = authed_client.post(ENDPOINT)
    assert r1.status_code == 200
    token1 = r1.json()["data"]["extension_pairing_token"]

    # Bump the clock past the next ``iat`` boundary.
    time.sleep(1.05)

    r2 = authed_client.post(ENDPOINT)
    assert r2.status_code == 200
    token2 = r2.json()["data"]["extension_pairing_token"]

    assert token1 != token2, "consecutive emissions must produce distinct JWTs"

    # Decode both raw (no verify_exp toggling — they're fresh) to inspect
    # the claim values; both must point at the same user but carry
    # different ``iat``/``exp``.
    p1 = jwt.decode(
        token1, settings.SUPABASE_JWT_SECRET, algorithms=["HS256"]
    )
    p2 = jwt.decode(
        token2, settings.SUPABASE_JWT_SECRET, algorithms=["HS256"]
    )
    assert p1["sub"] == p2["sub"] == str(FIXED_USER_ID)
    assert p1["typ"] == p2["typ"] == PAIRING_TOKEN_TYP
    assert p1["iat"] != p2["iat"]
    assert p1["exp"] != p2["exp"]

    # And both tokens must still round-trip via the production decoder.
    assert decode_pairing_token(token1) == FIXED_USER_ID
    assert decode_pairing_token(token2) == FIXED_USER_ID


# ─── 4. Round-trip: token.sub == requesting user_id ────────────────────


def test_token_decodes_to_requesting_user_id(
    authed_client: TestClient,
) -> None:
    """``decode_pairing_token`` must yield the same UUID we authenticated as."""
    response = authed_client.post(ENDPOINT)
    assert response.status_code == 200

    token = response.json()["data"]["extension_pairing_token"]
    decoded = decode_pairing_token(token)
    assert decoded == FIXED_USER_ID
    assert isinstance(decoded, UUID)
