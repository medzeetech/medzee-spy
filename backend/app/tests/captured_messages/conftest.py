"""Shared fixtures for the captured_messages module tests.

Lazy string-path monkeypatching so attribute resolution is deferred to
fixture-call time.

Fixtures exposed:

* :func:`fake_captured_repo` — ``SimpleNamespace`` of ``AsyncMock``s for the
  public repository coroutines, each patched at the canonical site plus a
  handful of likely re-import sites (TTL worker, reports service).
* :func:`sample_captured_messages` — factory producing realistic
  ``CapturedMessage`` lists (configurable count, window, group flag).
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.modules.captured_messages.schemas import CapturedMessage


# ─── PT-BR snippet pools (small, deterministic via random.Random(42)) ──


_FROM_ME_SNIPPETS: tuple[str, ...] = (
    "Olá! Tudo bem? Como posso te ajudar?",
    "Claro, podemos agendar para essa semana. Qual horário fica melhor?",
    "O valor da consulta de avaliação é R$ 250.",
    "Sim, atendemos por convênio. Qual o seu plano?",
    "Vou confirmar a disponibilidade e já te retorno.",
    "Perfeito! Sua consulta está confirmada para amanhã às 14h.",
)
_FROM_THEM_SNIPPETS: tuple[str, ...] = (
    "Oi, gostaria de saber o valor da consulta.",
    "Vocês aceitam parcelamento?",
    "Quanto custa o tratamento de canal?",
    "Tem horário disponível essa semana?",
    "Atendem por convênio?",
    "Onde fica a clínica?",
    "Obrigada, vou pensar e te retorno!",
)


# ─── fake_captured_repo ────────────────────────────────────────────────


# Re-import sites that may ``from .repository import <name>`` at module load.
# Patches are applied with ``raising=False`` so they're a no-op until the
# referenced module exists & binds the symbol.
_REPO_REIMPORT_SITES: tuple[str, ...] = (
    "app.modules.captured_messages.repository",  # canonical
    "app.workers.ttl_cleanup",                   # TTL cleanup worker
    "app.modules.reports.service",               # report worker adapter
)


@pytest.fixture
def fake_captured_repo(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Replace every public function in ``app.modules.captured_messages.repository``
    with an ``AsyncMock``.

    Patches are applied by **dotted string path** with ``raising=False`` so
    attribute resolution is deferred to fixture-call time.

    Returns a ``SimpleNamespace`` of the mocks so tests can write
    ``fake_captured_repo.insert_many.assert_awaited_once_with(...)``.
    """
    empty_stats: dict[str, int | None] = {
        "message_count": 0,
        "conversation_count": 0,
        "last_message_at": None,
    }

    insert_many = AsyncMock(return_value=0, name="insert_many")
    query_window_for_user = AsyncMock(
        return_value=[], name="query_window_for_user"
    )
    query_last_n_per_chat = AsyncMock(
        return_value=[], name="query_last_n_per_chat"
    )
    stats_for_user = AsyncMock(
        return_value=dict(empty_stats), name="stats_for_user"
    )
    stats_for_session = AsyncMock(
        return_value=dict(empty_stats), name="stats_for_session"
    )
    delete_for_session = AsyncMock(return_value=0, name="delete_for_session")

    targets: tuple[tuple[str, AsyncMock], ...] = (
        ("insert_many", insert_many),
        ("query_window_for_user", query_window_for_user),
        ("query_last_n_per_chat", query_last_n_per_chat),
        ("stats_for_user", stats_for_user),
        ("stats_for_session", stats_for_session),
        ("delete_for_session", delete_for_session),
    )

    for site in _REPO_REIMPORT_SITES:
        for fn_name, fn_mock in targets:
            monkeypatch.setattr(
                f"{site}.{fn_name}",
                fn_mock,
                raising=False,
            )

    return SimpleNamespace(
        insert_many=insert_many,
        query_window_for_user=query_window_for_user,
        query_last_n_per_chat=query_last_n_per_chat,
        stats_for_user=stats_for_user,
        stats_for_session=stats_for_session,
        delete_for_session=delete_for_session,
    )


# ─── sample_captured_messages ──────────────────────────────────────────


# How many messages share a single wa_chatid before the factory rolls a new
# "conversation".
_MSGS_PER_CONVERSATION: int = 5


@pytest.fixture
def sample_captured_messages():
    """Factory producing realistic ``CapturedMessage`` lists.

    Usage::

        msgs = sample_captured_messages(count=20, days=7)
        msgs = sample_captured_messages(count=50, days=30, with_groups=True)
    """

    def _factory(
        *,
        count: int = 20,
        days: int = 7,
        user_id: UUID | None = None,
        session_id: UUID | None = None,
        with_groups: bool = False,
    ) -> list[CapturedMessage]:
        if count < 0:
            raise ValueError("count must be >= 0")
        if days <= 0:
            raise ValueError("days must be > 0")

        uid = user_id or uuid4()
        sid = session_id or uuid4()
        rng = random.Random(42)
        now = datetime.now(timezone.utc)
        window_seconds = days * 24 * 60 * 60

        messages: list[CapturedMessage] = []
        for i in range(count):
            conv_index = i // _MSGS_PER_CONVERSATION
            in_conv_index = i % _MSGS_PER_CONVERSATION

            is_group = with_groups and (conv_index % 2 == 1)
            if is_group:
                wa_chatid = f"55119000{conv_index:04d}@g.us"
                contact_name = f"Grupo Pacientes {conv_index + 1}"
            else:
                wa_chatid = f"55119000{conv_index:04d}@s.whatsapp.net"
                contact_name = f"Paciente {conv_index + 1}"

            # Contact opens (in_conv_index == 0 → from_me=False), then we
            # alternate.
            from_me = (in_conv_index % 2) == 1
            pool = _FROM_ME_SNIPPETS if from_me else _FROM_THEM_SNIPPETS
            text = rng.choice(pool)

            offset = rng.randint(0, window_seconds)
            ts = now - timedelta(seconds=offset)
            created_at = ts + timedelta(milliseconds=10)

            messages.append(
                CapturedMessage(
                    id=uuid4(),
                    user_id=uid,
                    whatsapp_session_id=sid,
                    wa_chatid=wa_chatid,
                    contact_name=contact_name,
                    ts=ts,
                    is_from_me=from_me,
                    message_type="text",
                    text=text,
                    raw_message_id=uuid4().hex,
                    created_at=created_at,
                )
            )

        return messages

    return _factory
