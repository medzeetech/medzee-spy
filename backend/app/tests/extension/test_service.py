"""Unit tests for ``app.modules.extension.service`` (F8-T7).

Patching strategy mirrors ``backend/app/tests/auth/test_auth_service.py``:

* Repository functions (in both ``app.modules.extension.repository`` and
  the cross-module ``app.modules.captured_messages.repository``) are
  replaced with :class:`unittest.mock.AsyncMock` via
  ``monkeypatch.setattr(<dotted_path>, AsyncMock(...))``. Because
  ``service`` does ``from app.modules.extension import repository`` and
  then calls ``repository.fn(...)``, patching at the module-attribute
  level reaches every consumer.
* The report worker fan-out is gated by patching the **lazy import**
  ``app.modules.reports.service.get_report_service`` so we don't drag in
  ``reports.repository`` (which talks to Supabase at module load).
* :class:`asyncio.create_task` is also stubbed to a synchronous fake when
  a test wants to assert ``trigger_generate`` was scheduled — otherwise
  pytest emits ``"Task was destroyed but it is pending"`` warnings as
  the loop tears down.
* ``settings.SUPABASE_JWT_SECRET`` is configured via the autouse fixture
  so ``pair_extension`` can decode tokens minted by ``issue_pairing_token``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.modules.extension import service as ext_service
from app.modules.extension.schemas import (
    ExtensionMessage,
    ExtensionMessageBatch,
    ExtensionPairRequest,
    ExtensionTelemetryEvent,
    MobileRedirectLeadCreate,
)
from app.modules.extension.security import (
    issue_pairing_token,
    issue_refresh_token,
)

TEST_SECRET = "test-jwt-secret-svc-extension-0123456789"


@pytest.fixture(autouse=True)
def _configure_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test needs a valid JWT secret to mint/decode pairing tokens."""
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", TEST_SECRET)


@pytest.fixture(autouse=True)
def _reset_rate_buckets() -> None:
    """Clean the in-memory rate-limit dict between tests so per-user
    counters don't bleed across test cases.
    """
    ext_service._TELEMETRY_RATE_BUCKETS.clear()
    yield
    ext_service._TELEMETRY_RATE_BUCKETS.clear()


# ─── helpers ───────────────────────────────────────────────────────────


def _make_message(
    wa_msg_id: str = "msg-1",
    wa_chatid: str = "5511999999999@c.us",
    text: str | None = "oi",
) -> ExtensionMessage:
    return ExtensionMessage(
        wa_chatid=wa_chatid,
        wa_msg_id=wa_msg_id,
        ts=datetime(2026, 5, 24, 10, 0, tzinfo=timezone.utc),
        is_from_me=False,
        message_type="text",
        text=text,
        contact_name="Maria",
        wa_is_group=False,
    )


def _make_batch(
    *,
    batch_index: int = 0,
    total_batches: int = 1,
    extension_version: str = "1.0.0",
    messages: list[ExtensionMessage] | None = None,
) -> ExtensionMessageBatch:
    return ExtensionMessageBatch(
        batch_id=f"batch-{batch_index}",
        batch_index=batch_index,
        total_batches=total_batches,
        extension_version=extension_version,
        messages=messages if messages is not None else [_make_message()],
    )


def _patch_repository(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Replace every extension repository function with an AsyncMock."""
    session_id = uuid4()
    mocks = SimpleNamespace(
        upsert_install=AsyncMock(return_value=None),
        get_install=AsyncMock(return_value=None),
        get_install_for_user=AsyncMock(return_value=None),
        touch_install=AsyncMock(return_value=None),
        get_or_create_extension_session=AsyncMock(return_value=session_id),
        insert_telemetry=AsyncMock(return_value=None),
        insert_mobile_lead=AsyncMock(return_value=None),
        _session_id=session_id,
    )
    for name in (
        "upsert_install",
        "get_install",
        "get_install_for_user",
        "touch_install",
        "get_or_create_extension_session",
        "insert_telemetry",
        "insert_mobile_lead",
    ):
        monkeypatch.setattr(
            f"app.modules.extension.repository.{name}",
            getattr(mocks, name),
        )
    return mocks


def _patch_insert_many(
    monkeypatch: pytest.MonkeyPatch, return_value: int = 0
) -> AsyncMock:
    """Replace ``captured_messages.repository.insert_many`` (the symbol
    re-imported into ``extension.service``) with an AsyncMock.

    The service imports the function directly via ``from ... import
    insert_many`` so we patch the local binding inside service.
    """
    mock = AsyncMock(return_value=return_value)
    monkeypatch.setattr(
        "app.modules.extension.service.insert_many", mock
    )
    return mock


def _patch_report_service(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub ``get_report_service()`` so ``trigger_generate`` is a mock.

    Also replace ``asyncio.create_task`` inside service with a thin shim
    that invokes the coroutine synchronously and returns a sentinel —
    this both prevents "Task pending" warnings and lets us assert the
    method was awaited with the right arguments.
    """
    fake_service = MagicMock(name="report_service")
    fake_service.trigger_generate = AsyncMock(return_value=uuid4())

    def _factory():
        return fake_service

    # Patch at the dotted path used by service's lazy import.
    monkeypatch.setattr(
        "app.modules.reports.service.get_report_service",
        _factory,
        raising=False,
    )

    # Replace asyncio.create_task with a sync-runner so the test loop
    # actually awaits trigger_generate before assertions.
    def _sync_create_task(coro, *args, **kwargs):
        # Schedule + drain immediately so the mock is awaited before
        # the test inspects ``call_args``. Returning a SimpleNamespace
        # keeps the surface compatible (callers don't inspect the task).
        import asyncio as _aio

        loop = _aio.get_event_loop()
        task = loop.create_task(coro)
        return task

    monkeypatch.setattr(
        "app.modules.extension.service.asyncio.create_task",
        _sync_create_task,
    )
    return fake_service


# ─── pair_extension ────────────────────────────────────────────────────


async def test_pair_extension_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid pairing token → upserts install + returns refresh token."""
    repo = _patch_repository(monkeypatch)
    uid = uuid4()
    token = issue_pairing_token(uid)
    req = ExtensionPairRequest(
        pairing_token=token,
        extension_install_id="install-abc",
        extension_version="1.0.0",
        user_agent="Mozilla/5.0",
    )

    resp = await ext_service.pair_extension(req)

    assert resp.user_id == uid
    assert isinstance(resp.refresh_token, str) and resp.refresh_token
    # Decoding the response refresh token must yield the same uid.
    from app.modules.extension.security import decode_refresh_token

    assert decode_refresh_token(resp.refresh_token) == uid

    repo.upsert_install.assert_awaited_once()
    kwargs = repo.upsert_install.await_args.kwargs
    assert kwargs["extension_version"] == "1.0.0"
    assert kwargs["user_agent"] == "Mozilla/5.0"
    # install_id + user_id are passed positionally OR by keyword depending
    # on style; the call uses kwargs in service.py.
    assert kwargs.get("install_id") == "install-abc" or repo.upsert_install.await_args.args[0] == "install-abc"


async def test_pair_extension_rejects_expired_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An expired pairing token must raise 401 before any repo write."""
    repo = _patch_repository(monkeypatch)
    monkeypatch.setattr(settings, "EXTENSION_PAIRING_TOKEN_TTL_S", -10)
    expired = issue_pairing_token(uuid4())
    req = ExtensionPairRequest(
        pairing_token=expired, extension_install_id="install-x"
    )

    with pytest.raises(HTTPException) as exc:
        await ext_service.pair_extension(req)
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "pairing_expired"  # type: ignore[index]
    repo.upsert_install.assert_not_awaited()


async def test_pair_extension_rejects_wrong_typ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refresh token must NOT pass the pairing decoder."""
    repo = _patch_repository(monkeypatch)
    refresh = issue_refresh_token(uuid4())
    req = ExtensionPairRequest(
        pairing_token=refresh, extension_install_id="install-x"
    )

    with pytest.raises(HTTPException) as exc:
        await ext_service.pair_extension(req)
    assert exc.value.status_code == 401
    repo.upsert_install.assert_not_awaited()


async def test_pair_extension_upserts_with_correct_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upsert call must carry install_id, user_id, version, UA."""
    repo = _patch_repository(monkeypatch)
    uid = uuid4()
    token = issue_pairing_token(uid)
    req = ExtensionPairRequest(
        pairing_token=token,
        extension_install_id="install-42",
        extension_version="1.2.3",
        user_agent="UA-test",
    )

    await ext_service.pair_extension(req)

    repo.upsert_install.assert_awaited_once_with(
        install_id="install-42",
        user_id=uid,
        extension_version="1.2.3",
        user_agent="UA-test",
    )


# ─── ingest_batch ──────────────────────────────────────────────────────


async def test_ingest_batch_non_final_does_not_fire_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``batch_index < total_batches - 1`` no report worker fires."""
    _patch_repository(monkeypatch)
    insert_many_mock = _patch_insert_many(monkeypatch, return_value=1)
    report_service = _patch_report_service(monkeypatch)

    uid = uuid4()
    batch = _make_batch(batch_index=0, total_batches=3)
    out = await ext_service.ingest_batch(uid, batch)

    assert out["is_final"] is False
    assert out["received"] == 1
    insert_many_mock.assert_awaited_once()
    report_service.trigger_generate.assert_not_called()


async def test_ingest_batch_final_fires_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Final batch persists and schedules trigger_generate exactly once."""
    _patch_repository(monkeypatch)
    insert_many_mock = _patch_insert_many(monkeypatch, return_value=1)
    report_service = _patch_report_service(monkeypatch)

    uid = uuid4()
    batch = _make_batch(batch_index=2, total_batches=3)
    out = await ext_service.ingest_batch(uid, batch)

    assert out["is_final"] is True
    insert_many_mock.assert_awaited_once()
    # Drain pending tasks so the AsyncMock is actually awaited.
    import asyncio as _aio

    pending = [
        t
        for t in _aio.all_tasks()
        if t is not _aio.current_task() and not t.done()
    ]
    if pending:
        await _aio.gather(*pending, return_exceptions=True)

    report_service.trigger_generate.assert_awaited_once_with(
        uid, mode="last_n_per_chat", n_per_chat=30
    )


async def test_ingest_batch_maps_messages_correctly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``wa_msg_id`` → ``raw_message_id`` and ``source='extension'``."""
    repo = _patch_repository(monkeypatch)
    insert_many_mock = _patch_insert_many(monkeypatch, return_value=2)
    _patch_report_service(monkeypatch)

    uid = uuid4()
    messages = [
        _make_message(wa_msg_id="wa-1", text="hello"),
        _make_message(wa_msg_id="wa-2", text="world"),
    ]
    batch = _make_batch(messages=messages)

    await ext_service.ingest_batch(uid, batch)

    inserts = insert_many_mock.await_args.args[0]
    assert len(inserts) == 2
    assert inserts[0].raw_message_id == "wa-1"
    assert inserts[1].raw_message_id == "wa-2"
    for ins in inserts:
        assert ins.source == "extension"
        assert ins.user_id == uid
        assert ins.whatsapp_session_id == repo._session_id


async def test_ingest_batch_rejects_outdated_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``extension_version < EXTENSION_MIN_VERSION`` → 409 outdated."""
    _patch_repository(monkeypatch)
    insert_many_mock = _patch_insert_many(monkeypatch)
    monkeypatch.setattr(settings, "EXTENSION_MIN_VERSION", "2.0.0")

    batch = _make_batch(extension_version="1.0.0")
    with pytest.raises(HTTPException) as exc:
        await ext_service.ingest_batch(uuid4(), batch)
    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "extension_outdated"
    assert detail["min_version"] == "2.0.0"
    insert_many_mock.assert_not_awaited()


async def test_ingest_batch_empty_messages_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty messages list → insert_many called with [], received=0."""
    _patch_repository(monkeypatch)
    insert_many_mock = _patch_insert_many(monkeypatch, return_value=0)
    _patch_report_service(monkeypatch)

    batch = _make_batch(messages=[])
    out = await ext_service.ingest_batch(uuid4(), batch)

    assert out["received"] == 0
    insert_many_mock.assert_awaited_once()
    passed = insert_many_mock.await_args.args[0]
    assert passed == []


# ─── record_telemetry ──────────────────────────────────────────────────


async def test_record_telemetry_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One event → repository.insert_telemetry called once."""
    repo = _patch_repository(monkeypatch)
    uid = uuid4()
    event = ExtensionTelemetryEvent(
        event="collect_started", extension_version="1.0.0"
    )

    await ext_service.record_telemetry(uid, event)
    repo.insert_telemetry.assert_awaited_once_with(uid, event)


async def test_record_telemetry_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After ``EXTENSION_TELEMETRY_RATE_PER_MINUTE`` calls the next raises 429."""
    repo = _patch_repository(monkeypatch)
    monkeypatch.setattr(settings, "EXTENSION_TELEMETRY_RATE_PER_MINUTE", 3)
    uid = uuid4()
    event = ExtensionTelemetryEvent(
        event="collect_started", extension_version="1.0.0"
    )

    for _ in range(3):
        await ext_service.record_telemetry(uid, event)

    with pytest.raises(HTTPException) as exc:
        await ext_service.record_telemetry(uid, event)
    assert exc.value.status_code == 429
    assert exc.value.detail["code"] == "rate_limited"  # type: ignore[index]
    assert repo.insert_telemetry.await_count == 3


async def test_record_telemetry_collect_failed_logs_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``collect_failed`` event lands as a WARNING for alerting."""
    _patch_repository(monkeypatch)
    uid = uuid4()
    event = ExtensionTelemetryEvent(
        event="collect_failed",
        extension_version="1.0.0",
        reason="wa_internals_changed",
        chats_total=10,
        chats_processed=3,
    )

    with caplog.at_level(logging.WARNING, logger=ext_service.logger.name):
        await ext_service.record_telemetry(uid, event)

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        r.name == ext_service.logger.name
        and r.message.endswith("collect_failed")
        for r in warning_records
    )


# ─── capture_mobile_lead ───────────────────────────────────────────────


async def test_capture_mobile_lead_inserts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service forwards the request straight to repository.insert_mobile_lead."""
    repo = _patch_repository(monkeypatch)
    req = MobileRedirectLeadCreate(
        email="user@example.com",
        user_agent="Mozilla/5.0 (iPhone)",
        source_url="https://medzee.com/spy",
    )

    await ext_service.capture_mobile_lead(req)
    repo.insert_mobile_lead.assert_awaited_once_with(req)


# ─── get_status ────────────────────────────────────────────────────────


async def test_get_status_unpaired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No install row → paired=False, defaults zeroed."""
    repo = _patch_repository(monkeypatch)
    repo.get_install_for_user.return_value = None

    resp = await ext_service.get_status(uuid4())

    assert resp.paired is False
    assert resp.last_collection_at is None
    assert resp.last_collection_message_count == 0
    assert resp.extension_min_version == settings.EXTENSION_MIN_VERSION


async def test_get_status_paired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Install row present → paired=True + populated stats."""
    repo = _patch_repository(monkeypatch)
    last_seen = datetime(2026, 5, 23, 9, 0, tzinfo=timezone.utc)
    repo.get_install_for_user.return_value = {
        "install_id": "install-z",
        "user_id": str(uuid4()),
        "last_seen_at": last_seen.isoformat(),
    }
    fake_stats = AsyncMock(
        return_value={
            "message_count": 142,
            "conversation_count": 7,
            "last_message_at": last_seen,
        }
    )
    monkeypatch.setattr(
        "app.modules.captured_messages.repository.stats_for_user",
        fake_stats,
    )

    resp = await ext_service.get_status(uuid4())

    assert resp.paired is True
    assert resp.last_collection_message_count == 142
    assert resp.last_collection_at == last_seen
    fake_stats.assert_awaited_once()
