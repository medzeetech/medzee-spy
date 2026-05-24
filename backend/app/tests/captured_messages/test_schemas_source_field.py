"""Unit tests for the F8 ``source`` field on captured_messages schemas.

The migration ``f8_1_extension_support`` added
``source TEXT NOT NULL DEFAULT 'webhook'`` with a CHECK constraint limiting
values to ``('webhook', 'extension')``. The Python layer mirrors this via
``MessageSource = Literal['webhook','extension']`` on both
:class:`CapturedMessage` (read) and :class:`CapturedMessageInsert` (write)
with default ``'webhook'`` — so the F4 webhook ingestion path keeps working
without any code change, while the F8 extension ingestion path opts in by
passing ``source='extension'``.

Each test exercises both models (write + read) so a regression on either
side fails the same case.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.captured_messages.schemas import (
    CapturedMessage,
    CapturedMessageInsert,
)


def _insert_kwargs() -> dict:
    """Minimal valid kwargs for `CapturedMessageInsert` (no ``source``)."""
    return {
        "user_id": uuid4(),
        "whatsapp_session_id": uuid4(),
        "wa_chatid": "5511900000001@s.whatsapp.net",
        "contact_name": "Paciente Teste",
        "ts": datetime.now(timezone.utc),
        "is_from_me": False,
        "message_type": "text",
        "text": "oi",
        "raw_message_id": "raw-id-abc",
    }


def _read_kwargs() -> dict:
    """Minimal valid kwargs for `CapturedMessage` (no ``source``)."""
    now = datetime.now(timezone.utc)
    return {
        "id": uuid4(),
        **_insert_kwargs(),
        "created_at": now,
    }


def test_source_defaults_to_webhook_when_omitted():
    """Backward compat: F4 callers don't pass ``source``; both models must
    default to ``'webhook'`` so existing webhook-ingestion code keeps
    working without modification."""
    insert = CapturedMessageInsert(**_insert_kwargs())
    read = CapturedMessage(**_read_kwargs())
    assert insert.source == "webhook"
    assert read.source == "webhook"


def test_source_accepts_extension():
    """F8 extension ingestion path passes ``source='extension'`` explicitly
    on both write (insert payload) and read (validated DB row) sides."""
    insert = CapturedMessageInsert(**{**_insert_kwargs(), "source": "extension"})
    read = CapturedMessage(**{**_read_kwargs(), "source": "extension"})
    assert insert.source == "extension"
    assert read.source == "extension"


def test_source_rejects_unknown_value():
    """Pydantic ``Literal`` validation catches typos / drift at the schema
    boundary, before they reach the Postgres CHECK constraint. Anything
    outside ``('webhook','extension')`` raises :class:`ValidationError`."""
    with pytest.raises(ValidationError):
        CapturedMessageInsert(**{**_insert_kwargs(), "source": "other"})
    with pytest.raises(ValidationError):
        CapturedMessage(**{**_read_kwargs(), "source": "other"})
