"""Precompiled regex keyword patterns used by deterministic funnel staging.

Kept separate from :mod:`metrics` so the patterns can be reused by future
LLM-context-builder code (F3 T7) and unit-tested in isolation (F3 T19).

Patterns are case-insensitive and operate on raw Portuguese-pt-BR clinic
message text.
"""
from __future__ import annotations

import re
from typing import Final

# Stage 4 — "Receberam info / valor": clinic sent pricing or value-related info.
# Matches either a literal "R$" followed by a digit, or one of the value lemmas.
KW_VALUE: Final[re.Pattern[str]] = re.compile(
    r"\bR\$\s?\d|\b(valor|preç[oa]|investimento|consulta|orçamento|particular)\b",
    re.IGNORECASE,
)

# Stage 5 — "Agendamento confirmado": clinic confirmed a booking.
KW_BOOKED: Final[re.Pattern[str]] = re.compile(
    r"\b(agendad[oa]|confirmad[oa]|marcad[oa]|reservei|reservar|nos vemos|ver vc|consultório)\b",
    re.IGNORECASE,
)
