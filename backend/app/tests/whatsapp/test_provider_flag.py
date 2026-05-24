"""Integration tests for the ``WHATSAPP_PROVIDER`` flag gate (F8-T9 / CHX-13).

The gate lives in ``app/api/router.py`` as a router-level dependency
(``_assert_uazapi_enabled``) attached to the ``whatsapp_router``. When
``settings.WHATSAPP_PROVIDER != 'uazapi'`` every ``/api/whatsapp/*`` route
short-circuits with **410 Gone** before its own handler runs — including
the webhook callbacks, which is fine because uazapi isn't sending traffic
when the extension provider is the active one.

The dependency is evaluated **on every request**, not at import-time, so a
plain ``monkeypatch.setattr(settings, "WHATSAPP_PROVIDER", "...")`` flips
the behaviour for the current test without touching the global ``app``
instance or re-registering routes.

Why each test exists:

1. ``test_uazapi_routes_pass_when_provider_is_uazapi`` — proves the gate is
   provider-conditional (no 410 in compat mode). We can't assert a specific
   2xx because the route still needs Supabase, so we just assert "not 410".
2. ``test_uazapi_post_sessions_returns_410_when_provider_is_extension`` —
   the canonical case: legacy POST /sessions is gone.
3. ``test_uazapi_sse_events_returns_410_when_provider_is_extension`` — the
   SSE endpoint must also be gated, not just JSON routes.
4. ``test_uazapi_webhook_returns_410_when_provider_is_extension`` — webhook
   path is gated too (uazapi isn't calling it in extension mode anyway).
5. ``test_extension_routes_not_gated_by_provider_flag`` — smoke that
   ``/api/extension/*`` keeps working when provider=extension (just confirm
   the response is **not** 410; 401/422 are both acceptable signals).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


# ─── fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def client() -> TestClient:
    """Sync TestClient — the app is built once at import time, but the
    dependency re-reads ``settings.WHATSAPP_PROVIDER`` per request so a
    monkeypatch in the test body is enough to flip behaviour."""
    return TestClient(app)


# ─── tests ─────────────────────────────────────────────────────────────


def test_uazapi_routes_pass_when_provider_is_uazapi(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``WHATSAPP_PROVIDER=uazapi`` → gate is a no-op, route runs.

    We hit ``POST /api/whatsapp/sessions`` which does need Supabase to
    fully respond, so we only assert the gate didn't fire (status ≠ 410).
    Anything else — 200, 4xx for missing config, 5xx from the provider —
    proves the request reached the handler.
    """
    monkeypatch.setattr(settings, "WHATSAPP_PROVIDER", "uazapi")

    response = client.post("/api/whatsapp/sessions")

    assert response.status_code != 410, response.text


def test_uazapi_post_sessions_returns_410_when_provider_is_extension(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``WHATSAPP_PROVIDER=extension`` → POST /sessions returns 410 + body."""
    monkeypatch.setattr(settings, "WHATSAPP_PROVIDER", "extension")

    response = client.post("/api/whatsapp/sessions")

    assert response.status_code == 410, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["code"] == "provider_disabled"
    assert detail["message"] == (
        "uazapi provider is disabled. Use /api/extension/* endpoints."
    )
    assert detail["use"] == "/api/extension/*"


def test_uazapi_sse_events_returns_410_when_provider_is_extension(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SSE endpoints are gated too — the dependency runs before the
    StreamingResponse handshake, so the client never opens the stream."""
    monkeypatch.setattr(settings, "WHATSAPP_PROVIDER", "extension")

    response = client.get(
        "/api/whatsapp/sessions/11111111-1111-1111-1111-111111111111/events"
    )

    assert response.status_code == 410, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "provider_disabled"
    assert detail["use"] == "/api/extension/*"


def test_uazapi_webhook_returns_410_when_provider_is_extension(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The webhook path is gated as well. uazapi isn't pushing events when
    the active provider is the extension, so 410'ing the route is safe."""
    monkeypatch.setattr(settings, "WHATSAPP_PROVIDER", "extension")

    response = client.post("/api/whatsapp/webhook", json={})

    assert response.status_code == 410, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "provider_disabled"


def test_extension_routes_not_gated_by_provider_flag(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Smoke: ``/api/extension/*`` keeps responding while provider=extension.

    We hit ``POST /api/extension/mobile-lead`` with a malformed body so the
    Pydantic layer rejects it with 422 — that proves the route is reachable
    (the gate would have shadowed it with 410 before validation ran).
    """
    monkeypatch.setattr(settings, "WHATSAPP_PROVIDER", "extension")

    response = client.post(
        "/api/extension/mobile-lead", json={"email": "not-an-email"}
    )

    assert response.status_code != 410, response.text
    # Bonus signal: the route ran far enough to invoke Pydantic validation.
    assert response.status_code == 422, response.text
