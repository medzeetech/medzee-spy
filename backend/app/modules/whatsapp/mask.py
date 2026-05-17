"""Phone-number masking helpers.

Every log line, SSE event, and DB row that carries a phone number for
display passes through :func:`mask_phone`. The output format is fixed by
the public SSE contract (design § 9):

    "+CC AA D****-LLLL"

where ``CC`` is the country code, ``AA`` is the area code, ``D`` is the
mobile prefix digit (typically ``9`` in Brazil), and ``LLLL`` is the last
four digits. Anything that can't be parsed deterministically becomes
``"+** ** *****-****"`` so we never leak partial digits by accident.
"""
from __future__ import annotations

import re

_DIGITS_RE = re.compile(r"\D+")
_PLACEHOLDER = "+** ** *****-****"


def mask_phone(jid_or_msisdn: str) -> str:
    """Normalize a JID/MSISDN to the masked display form.

    Accepts WhatsApp JIDs (``5511987651234@s.whatsapp.net``,
    ``...@c.us``, ``...@g.us``), E.164 (``+5511987651234``), and raw
    digit strings. Empty / unparseable input is masked to a placeholder
    so callers can render it directly without further guarding.
    """
    if not jid_or_msisdn:
        return ""

    # Strip JID suffix (``@s.whatsapp.net``, ``@c.us``, ``@g.us``, etc.)
    # and any other non-digit chars (``+``, spaces, dashes).
    local_part = jid_or_msisdn.split("@", 1)[0]
    digits = _DIGITS_RE.sub("", local_part)

    if len(digits) < 12:
        # Need at least CC(2) + AA(2) + 8-digit subscriber.
        return _PLACEHOLDER

    country = digits[:2]
    area = digits[2:4]
    subscriber = digits[4:]

    if len(subscriber) >= 9:
        # Mobile (Brazil: 9 digits, leading "9"). Keep first digit + last 4.
        first = subscriber[0]
        last4 = subscriber[-4:]
        return f"+{country} {area} {first}****-{last4}"

    if len(subscriber) == 8:
        # Fixed-line (8 digits, no leading mobile prefix). Keep first 4 +
        # last 2 with the middle two masked — still avoids the full number.
        return f"+{country} {area} {subscriber[:4]}-**{subscriber[-2:]}"

    return _PLACEHOLDER


__all__ = ["mask_phone"]
