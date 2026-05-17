"""Unit tests for `mask_phone` — covers design § 9 contract for masked
phone display strings.

Format target: ``"+CC AA D****-LLLL"`` for mobile (subscriber length >= 9),
``"+CC AA FFFF-**LL"`` for fixed-line (subscriber length == 8), and a fixed
placeholder ``"+** ** *****-****"`` for anything unparseable.
"""
from __future__ import annotations

from app.modules.whatsapp.mask import mask_phone


def test_mask_phone_jid_13_digits_mobile() -> None:
    """Canonical WhatsApp JID (13 digits: CC=55, AA=11, mobile 9XXXXXXXX)
    masks to first-digit + last-four pattern."""
    assert mask_phone("5511987651234@s.whatsapp.net") == "+55 11 9****-1234"


def test_mask_phone_12_digits_fixed_line() -> None:
    """12-digit input (no mobile prefix '9') routes through the fixed-line
    branch: first 4 + masked middle + last 2."""
    # Empirically determined from the implementation:
    #   "551187651234" → country=55, area=11, subscriber=87651234 (8 digits)
    #   → "+55 11 8765-**34"
    assert mask_phone("551187651234") == "+55 11 8765-**34"


def test_mask_phone_e164_form() -> None:
    """E.164 with leading '+' is normalized before masking."""
    assert mask_phone("+5511987651234") == "+55 11 9****-1234"


def test_mask_phone_bare_digits() -> None:
    """Plain digit string (no JID suffix, no '+') still masks correctly."""
    assert mask_phone("5511987651234") == "+55 11 9****-1234"


def test_mask_phone_empty_string_returns_empty() -> None:
    """Empty input short-circuits to '' (defensive — callers may pass None-ish)."""
    assert mask_phone("") == ""


def test_mask_phone_invalid_short_returns_placeholder() -> None:
    """Non-digit or too-short input returns the fixed placeholder so we
    never leak partial digits to the UI/logs."""
    assert mask_phone("abc") == "+** ** *****-****"
    assert mask_phone("5511") == "+** ** *****-****"
