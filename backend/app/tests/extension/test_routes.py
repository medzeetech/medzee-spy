"""Integration tests for the extension routes (T8 of F8).

Style mirrors ``app/tests/auth/test_auth_routes.py``:

* ``TestClient(app)`` (sync) for HTTP exercising.
* ``app.dependency_overrides`` swaps ``get_current_user_id`` when we want
  to skip the real Supabase JWT layer.
* Repository functions are replaced with :class:`AsyncMock` via
  ``monkeypatch.setattr(<dotted_path>, ...)`` so we never hit Supabase.
* :func:`asyncio.create_task` is replaced with a sync-runner inside the
  service module so the F3 worker trigger is actually awaited before the
  test inspects ``call_args``.

Router wiring: T9 mounts ``extension.routes.router`` at ``/extension``
inside ``app/api/router.py``, so ``TestClient(app)`` reaches
``/api/extension/*`` out of the box — no per-file mount workaround
needed here.

PIVOT (2026-05-24): tests for ``POST /api/extension/pair`` are gone —
that endpoint and the custom JWT pairing dance no longer exist. Auth on
``/messages`` and ``/telemetry`` is now ``get_current_user_id`` (the
standard Supabase JWT validator), exercised via dependency override in
the same shape as ``/status``.
"""
from __future__ import annotations

from typing import Iterator
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import get_current_user_id
from app.main import app
from app.modules.extension import service as ext_service
from app.modules.extension.schemas import ExtensionStatusResponse

# Stable test ids — keep assertions deterministic across runs.
TEST_USER_ID = UUID("22222222-2222-2222-2222-222222222222")


# ─── fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_rate_buckets() -> Iterator[None]:
    """Telemetry rate-limit bucket is module-level — wipe between tests."""
    ext_service._TELEMETRY_RATE_BUCKETS.clear()
    yield
    ext_service._TELEMETRY_RATE_BUCKETS.clear()


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    """Wipe ``app.dependency_overrides`` after every test."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def fake_repository(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace every extension repository function with an AsyncMock.

    PIVOT (2026-05-24): install-registry functions are gone; only
    ``get_or_create_extension_session``, ``insert_telemetry`` and
    ``insert_mobile_lead`` remain.
    """
    session_id = uuid4()
    repo = MagicMock(name="extension_repository", _session_id=session_id)
    repo.get_or_create_extension_session = AsyncMock(return_value=session_id)
    repo.insert_telemetry = AsyncMock(return_value=None)
    repo.insert_mobile_lead = AsyncMock(return_value=None)

    for name in (
        "get_or_create_extension_session",
        "insert_telemetry",
        "insert_mobile_lead",
    ):
        monkeypatch.setattr(
            f"app.modules.extension.repository.{name}",
            getattr(repo, name),
        )
    return repo


@pytest.fixture
def fake_insert_many(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Replace ``captured_messages.insert_many`` re-imported into service."""
    mock = AsyncMock(return_value=1)
    monkeypatch.setattr("app.modules.extension.service.insert_many", mock)
    return mock


@pytest.fixture
def fake_report_service(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub the lazy-imported report service + make create_task synchronous.

    The service does ``from app.modules.reports.service import
    get_report_service`` only inside the final-batch branch, so we patch
    the dotted path with ``raising=False`` to side-step the deferred
    import. ``asyncio.create_task`` is replaced with a shim that creates
    the task on the current event loop — we then drain pending tasks in
    the test body before asserting ``trigger_generate`` was awaited.
    """
    fake_svc = MagicMock(name="report_service")
    fake_svc.trigger_generate = AsyncMock(return_value=uuid4())

    monkeypatch.setattr(
        "app.modules.reports.service.get_report_service",
        lambda: fake_svc,
        raising=False,
    )

    def _sync_create_task(coro, *args, **kwargs):
        import asyncio as _aio

        loop = _aio.get_event_loop()
        return loop.create_task(coro)

    monkeypatch.setattr(
        "app.modules.extension.service.asyncio.create_task",
        _sync_create_task,
    )
    return fake_svc


@pytest.fixture
def client() -> TestClient:
    """Sync TestClient — no auth overrides by default."""
    return TestClient(app)


# ─── helpers ───────────────────────────────────────────────────────────


def _message(wa_msg_id: str = "wa-1") -> dict:
    return {
        "wa_chatid": "5511999999999@c.us",
        "wa_msg_id": wa_msg_id,
        "ts": "2026-05-24T10:00:00+00:00",
        "is_from_me": False,
        "message_type": "text",
        "text": "oi",
        "contact_name": "Maria",
        "wa_is_group": False,
    }


def _batch(
    *,
    batch_index: int = 0,
    total_batches: int = 1,
    extension_version: str = "1.0.0",
    messages: list[dict] | None = None,
) -> dict:
    return {
        "batch_id": f"batch-{batch_index}",
        "batch_index": batch_index,
        "total_batches": total_batches,
        "extension_version": extension_version,
        "messages": messages if messages is not None else [_message()],
    }


# ───────────────────────────────────────────────────────────────────────
# POST /api/extension/messages
# ───────────────────────────────────────────────────────────────────────


def test_messages_happy_path(
    client: TestClient,
    fake_repository: MagicMock,
    fake_insert_many: AsyncMock,
    fake_report_service: MagicMock,
) -> None:
    """Valid Supabase JWT + valid version + single-batch → 202 + summary."""
    fake_insert_many.return_value = 1
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    response = client.post(
        "/api/extension/messages",
        json=_batch(),
        headers={"X-Extension-Version": "1.0.0"},
    )

    assert response.status_code == 202, response.text
    body = response.json()
    # Service returns a plain dict — no SuccessResponse envelope on 202.
    assert body["received"] == 1
    assert body["is_final"] is True
    assert body["batch_index"] == 0
    fake_insert_many.assert_awaited_once()


def test_messages_missing_auth_returns_4xx(
    client: TestClient, fake_repository: MagicMock
) -> None:
    """No Authorization header → 401/403 (HTTPBearer rejects)."""
    response = client.post(
        "/api/extension/messages",
        json=_batch(),
        headers={"X-Extension-Version": "1.0.0"},
    )

    # ``HTTPBearer(auto_error=True)`` (default in core.security) returns
    # 403 ``Not authenticated`` when the header is missing; accept either.
    assert response.status_code in (401, 403), response.text


def test_messages_outdated_version_409(
    client: TestClient,
    fake_repository: MagicMock,
    fake_insert_many: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``X-Extension-Version=0.9.0`` < min ``1.0.0`` → 409 extension_outdated.

    Auth dependency is bypassed via ``dependency_overrides`` so we can be
    sure the 409 originates from the version gate (CHX-14), not from the
    auth layer.
    """
    monkeypatch.setattr(settings, "EXTENSION_MIN_VERSION", "1.0.0")
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    response = client.post(
        "/api/extension/messages",
        json=_batch(extension_version="0.9.0"),
        headers={"X-Extension-Version": "0.9.0"},
    )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["code"] == "extension_outdated"
    assert detail["min_version"] == "1.0.0"
    fake_insert_many.assert_not_awaited()


def test_messages_final_batch_fires_worker(
    client: TestClient,
    fake_repository: MagicMock,
    fake_insert_many: AsyncMock,
    fake_report_service: MagicMock,
) -> None:
    """Final batch (``batch_index == total_batches - 1``) → trigger_generate fires."""
    import asyncio as _aio

    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    response = client.post(
        "/api/extension/messages",
        json=_batch(batch_index=2, total_batches=3),
        headers={"X-Extension-Version": "1.0.0"},
    )

    assert response.status_code == 202, response.text
    assert response.json()["is_final"] is True

    # The service schedules ``trigger_generate`` via ``asyncio.create_task``
    # — drain any pending tasks created by the call so the mock is awaited
    # before the assertion.
    async def _drain():
        pending = [
            t
            for t in _aio.all_tasks()
            if t is not _aio.current_task() and not t.done()
        ]
        if pending:
            await _aio.gather(*pending, return_exceptions=True)

    try:
        loop = _aio.get_event_loop()
    except RuntimeError:
        loop = _aio.new_event_loop()
    loop.run_until_complete(_drain())

    fake_report_service.trigger_generate.assert_awaited_once_with(
        TEST_USER_ID, mode="last_n_per_chat", n_per_chat=30, batch_id="batch-2"
    )


def test_messages_non_final_batch_does_not_fire_worker(
    client: TestClient,
    fake_repository: MagicMock,
    fake_insert_many: AsyncMock,
    fake_report_service: MagicMock,
) -> None:
    """Non-final batch → ``trigger_generate`` is NOT called."""
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    response = client.post(
        "/api/extension/messages",
        json=_batch(batch_index=0, total_batches=3),
        headers={"X-Extension-Version": "1.0.0"},
    )

    assert response.status_code == 202, response.text
    assert response.json()["is_final"] is False
    fake_report_service.trigger_generate.assert_not_called()


def test_messages_extra_field_in_message_422(
    client: TestClient, fake_repository: MagicMock
) -> None:
    """``ExtensionMessage`` is ``extra='forbid'`` — a stray ``foo`` → 422."""
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
    msg = _message()
    msg["foo"] = "bar"  # unknown field

    response = client.post(
        "/api/extension/messages",
        json=_batch(messages=[msg]),
        headers={"X-Extension-Version": "1.0.0"},
    )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail
    locs_joined = ".".join(
        str(part) for err in detail for part in (err.get("loc") or [])
    )
    assert "foo" in locs_joined


# ───────────────────────────────────────────────────────────────────────
# POST /api/extension/telemetry
# ───────────────────────────────────────────────────────────────────────


def test_telemetry_happy_path_204(
    client: TestClient, fake_repository: MagicMock
) -> None:
    """Valid event → 204 No Content + repository called once."""
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    response = client.post(
        "/api/extension/telemetry",
        json={"event": "collect_started", "extension_version": "1.0.0"},
    )

    assert response.status_code == 204, response.text
    assert response.content == b""
    fake_repository.insert_telemetry.assert_awaited_once()


def test_telemetry_pii_field_422(
    client: TestClient, fake_repository: MagicMock
) -> None:
    """PII field (``text``) → Pydantic 422 (``extra='forbid'``)."""
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    response = client.post(
        "/api/extension/telemetry",
        json={
            "event": "collect_started",
            "extension_version": "1.0.0",
            "text": "should not be here",  # PII leak attempt
        },
    )

    assert response.status_code == 422, response.text
    fake_repository.insert_telemetry.assert_not_awaited()


def test_telemetry_pii_wa_chatid_422(
    client: TestClient, fake_repository: MagicMock
) -> None:
    """PII field (``wa_chatid``) → 422 as well — verifies the guard is broad."""
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    response = client.post(
        "/api/extension/telemetry",
        json={
            "event": "collect_failed",
            "extension_version": "1.0.0",
            "wa_chatid": "5511999999999@c.us",
        },
    )

    assert response.status_code == 422
    fake_repository.insert_telemetry.assert_not_awaited()


def test_telemetry_rate_limited_429(
    client: TestClient,
    fake_repository: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After ``EXTENSION_TELEMETRY_RATE_PER_MINUTE`` calls → 429."""
    monkeypatch.setattr(settings, "EXTENSION_TELEMETRY_RATE_PER_MINUTE", 3)
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    body = {"event": "collect_started", "extension_version": "1.0.0"}

    for _ in range(3):
        r = client.post("/api/extension/telemetry", json=body)
        assert r.status_code == 204, r.text

    r = client.post("/api/extension/telemetry", json=body)
    assert r.status_code == 429, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["code"] == "rate_limited"
    assert fake_repository.insert_telemetry.await_count == 3


# ───────────────────────────────────────────────────────────────────────
# GET /api/extension/status
# ───────────────────────────────────────────────────────────────────────


def test_status_unauthenticated_4xx(client: TestClient) -> None:
    """No Authorization header → 401 or 403 (HTTPBearer rejects)."""
    response = client.get("/api/extension/status")

    assert response.status_code in (401, 403), response.text


def test_status_authenticated_200(
    client: TestClient,
    fake_repository: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authenticated user → 200 with the ExtensionStatusResponse shape.

    Patches ``get_status`` on the service module directly because the
    underlying call into ``captured_messages.stats_for_user`` is fragile
    to mock at the route layer (it lives behind a lazy import). The test
    still exercises the full route → service → response envelope path.
    """
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    fake_status = ExtensionStatusResponse(
        paired=True,
        last_collection_at=None,
        last_collection_message_count=42,
        extension_min_version="1.0.0",
    )
    monkeypatch.setattr(
        ext_service,
        "get_status",
        AsyncMock(return_value=fake_status),
    )

    response = client.get("/api/extension/status")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["message"] == "ok"
    data = payload["data"]
    assert data["paired"] is True
    assert data["last_collection_message_count"] == 42
    assert data["extension_min_version"] == "1.0.0"


# ───────────────────────────────────────────────────────────────────────
# POST /api/extension/mobile-lead
# ───────────────────────────────────────────────────────────────────────


def test_mobile_lead_no_auth_201(
    client: TestClient, fake_repository: MagicMock
) -> None:
    """No auth header required — 201 + ``{captured: true}`` + repo called."""
    response = client.post(
        "/api/extension/mobile-lead",
        json={
            "email": "user@example.com",
            "user_agent": "Mozilla/5.0 (iPhone)",
            "source_url": "https://medzee.com/spy",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json() == {"captured": True}
    fake_repository.insert_mobile_lead.assert_awaited_once()


def test_mobile_lead_invalid_email_422(client: TestClient) -> None:
    """Malformed email → Pydantic ``EmailStr`` rejects with 422."""
    response = client.post(
        "/api/extension/mobile-lead",
        json={"email": "not-an-email"},
    )

    assert response.status_code == 422
