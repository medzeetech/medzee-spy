"""Unit tests for ``app.modules.extension.schemas`` (F8-T4).

Locks in the wire-shape contracts from design §4.2:

* ``ExtensionMessage`` accepts the canonical payload and rejects unknown
  fields (``extra='forbid'`` guard).
* ``ExtensionTelemetryEvent`` rejects PII keys — this is the load-bearing
  privacy guard for CHX-16, so we test multiple PII names individually
  rather than relying on one generic "extra='forbid'" smoke.
* ``ExtensionMessageBatch`` enforces the ``batch_index >= 0`` and
  ``total_batches >= 1`` floors.
* ``ExtensionPairRequest`` / ``ExtensionPairResponse`` round-trip JSON so
  the HTTP layer can rely on ``model_dump_json`` ↔ ``model_validate_json``
  symmetry.
* ``MobileRedirectLeadCreate`` requires ``email``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.modules.extension.schemas import (
    ExtensionMessage,
    ExtensionMessageBatch,
    ExtensionPairRequest,
    ExtensionPairResponse,
    ExtensionTelemetryEvent,
    MobileRedirectLeadCreate,
)


# ─── ExtensionMessage ──────────────────────────────────────────────────


def test_extension_message_accepts_valid_payload() -> None:
    msg = ExtensionMessage(
        wa_chatid="5511999999999@c.us",
        wa_msg_id="ABCD1234",
        ts=datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc),
        is_from_me=False,
        message_type="text",
        text="oi doutor",
        contact_name="Paciente X",
        wa_is_group=False,
    )
    assert msg.wa_msg_id == "ABCD1234"
    assert msg.message_type == "text"
    assert msg.is_from_me is False


def test_extension_message_rejects_extra_field() -> None:
    """``extra='forbid'`` must reject unknown keys with ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        ExtensionMessage(
            wa_chatid="5511999999999@c.us",
            wa_msg_id="ABCD1234",
            ts=datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc),
            is_from_me=False,
            foo="unexpected",  # type: ignore[call-arg]
        )
    # Pydantic v2 names this error 'extra_forbidden'.
    assert any(
        err["type"] == "extra_forbidden" for err in exc_info.value.errors()
    )


# ─── ExtensionTelemetryEvent (PII guard) ───────────────────────────────


@pytest.mark.parametrize(
    "forbidden_key,forbidden_value",
    [
        ("text", "oi paciente"),
        ("wa_chatid", "5511999999999@c.us"),
        ("contact_name", "Paciente X"),
        ("msg_id", "ABCD1234"),
    ],
)
def test_extension_telemetry_event_rejects_pii_fields(
    forbidden_key: str, forbidden_value: str
) -> None:
    """CHX-16 privacy guard — these keys must never reach telemetry."""
    payload = {
        "event": "collect_failed",
        "extension_version": "1.0.0",
        forbidden_key: forbidden_value,
    }
    with pytest.raises(ValidationError) as exc_info:
        ExtensionTelemetryEvent(**payload)
    assert any(
        err["type"] == "extra_forbidden" for err in exc_info.value.errors()
    )


# ─── ExtensionMessageBatch ─────────────────────────────────────────────


def test_extension_message_batch_index_and_total_floors() -> None:
    base_msg = dict(
        wa_chatid="5511999999999@c.us",
        wa_msg_id="ABCD",
        ts=datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc),
        is_from_me=False,
    )

    # Happy: batch_index=0, total_batches=1 → OK.
    ok = ExtensionMessageBatch(
        batch_id="b1",
        batch_index=0,
        total_batches=1,
        extension_version="1.0.0",
        messages=[ExtensionMessage(**base_msg)],
    )
    assert ok.batch_index == 0
    assert ok.total_batches == 1

    # batch_index < 0 is rejected.
    with pytest.raises(ValidationError):
        ExtensionMessageBatch(
            batch_id="b1",
            batch_index=-1,
            total_batches=1,
            extension_version="1.0.0",
            messages=[],
        )

    # total_batches < 1 is rejected.
    with pytest.raises(ValidationError):
        ExtensionMessageBatch(
            batch_id="b1",
            batch_index=0,
            total_batches=0,
            extension_version="1.0.0",
            messages=[],
        )


# ─── ExtensionPairRequest / ExtensionPairResponse ──────────────────────


def test_extension_pair_request_roundtrips_json() -> None:
    req = ExtensionPairRequest(
        pairing_token="jwt.payload.sig",
        extension_install_id="11111111-2222-3333-4444-555555555555",
        extension_version="1.0.0",
        user_agent="Mozilla/5.0 ...",
    )
    raw = req.model_dump_json()
    rt = ExtensionPairRequest.model_validate_json(raw)
    assert rt == req


def test_extension_pair_response_roundtrips_json() -> None:
    uid = uuid4()
    resp = ExtensionPairResponse(refresh_token="jwt.refresh.sig", user_id=uid)
    raw = resp.model_dump_json()
    rt = ExtensionPairResponse.model_validate_json(raw)
    assert rt.refresh_token == "jwt.refresh.sig"
    assert rt.user_id == uid


# ─── MobileRedirectLeadCreate ──────────────────────────────────────────


def test_mobile_redirect_lead_requires_email() -> None:
    # Happy path: email is provided.
    ok = MobileRedirectLeadCreate(email="dr.x@example.com")
    assert ok.email == "dr.x@example.com"
    assert ok.user_agent is None

    # Missing email → ValidationError on the ``email`` field.
    with pytest.raises(ValidationError) as exc_info:
        MobileRedirectLeadCreate()  # type: ignore[call-arg]
    assert any(err["loc"] == ("email",) for err in exc_info.value.errors())
