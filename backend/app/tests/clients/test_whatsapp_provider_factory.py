"""Unit tests for the WhatsApp provider factory dispatch (F8-T3).

Verifies that ``get_provider()`` reads ``settings.WHATSAPP_PROVIDER`` at
call-time and returns the correct adapter instance, and that the
``ExtensionProvider`` short-circuits uazapi-specific calls with
``ProviderNotApplicable`` (CHX-13).
"""
from __future__ import annotations

import pytest

from app.clients.whatsapp import get_provider
from app.clients.whatsapp.errors import ProviderNotApplicable
from app.clients.whatsapp.extension import ExtensionProvider
from app.clients.whatsapp.uazapi import UazapiProvider
from app.core.config import settings


def test_get_provider_returns_extension_when_flag_is_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "WHATSAPP_PROVIDER", "extension")

    provider = get_provider()

    assert isinstance(provider, ExtensionProvider)


def test_get_provider_returns_uazapi_when_flag_is_uazapi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "WHATSAPP_PROVIDER", "uazapi")

    provider = get_provider()

    assert isinstance(provider, UazapiProvider)


async def test_extension_provider_create_session_raises_not_applicable() -> None:
    provider = ExtensionProvider()

    with pytest.raises(ProviderNotApplicable):
        await provider.create_session()
