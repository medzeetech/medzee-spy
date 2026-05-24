"""Unit tests for ``app.modules.extension.security`` (F8-T4).

JWT round-trips, ``typ`` discrimination, expiry handling, and the
``get_current_extension_user`` FastAPI dependency contract.

Strategy:

* Set ``settings.SUPABASE_JWT_SECRET`` to a test value via a fixture so
  the helpers can sign/verify without depending on env config.
* For the expiry test we monkeypatch
  ``settings.EXTENSION_PAIRING_TOKEN_TTL_S`` to a negative value so
  ``issue_pairing_token`` emits an already-expired JWT — avoids
  ``time.sleep`` in tests.
* ``get_current_extension_user`` is exercised by calling it directly
  with an ``authorization`` string. It is a plain function decorated as
  a FastAPI dependency, so direct invocation is fine.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.modules.extension import security


TEST_SECRET = "test-jwt-secret-deadbeef-0123456789"


@pytest.fixture(autouse=True)
def _configure_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure every test runs with a usable ``SUPABASE_JWT_SECRET``."""
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", TEST_SECRET)


# ─── pairing token round-trip ──────────────────────────────────────────


def test_issue_and_decode_pairing_token_roundtrip() -> None:
    uid = uuid4()
    token = security.issue_pairing_token(uid)
    decoded = security.decode_pairing_token(token)
    assert decoded == uid


# ─── typ discrimination ────────────────────────────────────────────────


def test_decode_pairing_token_rejects_refresh_typ() -> None:
    """A refresh token must NOT pass ``decode_pairing_token``."""
    uid = uuid4()
    refresh_token = security.issue_refresh_token(uid)

    with pytest.raises(HTTPException) as exc_info:
        security.decode_pairing_token(refresh_token)
    assert exc_info.value.status_code == 401
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "pairing_expired"


# ─── expiry handling ───────────────────────────────────────────────────


def test_decode_pairing_token_rejects_expired_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative TTL emits a JWT already past its ``exp``."""
    monkeypatch.setattr(settings, "EXTENSION_PAIRING_TOKEN_TTL_S", -10)
    uid = uuid4()
    expired = security.issue_pairing_token(uid)

    with pytest.raises(HTTPException) as exc_info:
        security.decode_pairing_token(expired)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["code"] == "pairing_expired"  # type: ignore[index]


# ─── refresh token end-to-end via dependency ───────────────────────────


def test_issue_refresh_token_roundtrip_via_get_current_extension_user() -> None:
    uid = uuid4()
    token = security.issue_refresh_token(uid)
    decoded = security.get_current_extension_user(
        authorization=f"Bearer {token}"
    )
    assert decoded == uid
    assert isinstance(decoded, UUID)


# ─── dependency error cases ────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_header",
    [
        "",  # empty
        "Token abc",  # wrong scheme
        "Bearer ",  # empty token
        "Bearer notajwt",  # malformed JWT
    ],
)
def test_get_current_extension_user_raises_401_on_bad_header(
    bad_header: str,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        security.get_current_extension_user(authorization=bad_header)
    assert exc_info.value.status_code == 401
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "pairing_expired"
