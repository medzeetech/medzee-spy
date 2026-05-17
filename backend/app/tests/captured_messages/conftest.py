"""Shared fixtures for the captured_messages module tests (F4).

Mirrors the F3 (reports) conftest pattern: lazy string-path monkeypatching so
attribute resolution is deferred to fixture-call time. Sibling agents are
concurrently authoring ``app/modules/captured_messages/repository.py`` and
the webhook/TTL/route wiring that depends on it — by patching via dotted
strings (and using ``raising=False`` uniformly) this conftest can be
collected even when those modules are still mid-flight.

Fixtures exposed:

* :func:`fake_captured_repo` — ``SimpleNamespace`` of ``AsyncMock``s for the
  5 public repository coroutines, each patched at the canonical site plus a
  handful of likely re-import sites (whatsapp service, ttl worker, reports
  service).
* :func:`sample_captured_messages` — factory producing realistic
  ``CapturedMessage`` lists (configurable count, window, group flag).
* :func:`sample_uazapi_message_raw` — factory returning raw uazapi webhook
  payload dicts in the 3 known shapes (plain text, extended text, image
  with caption).
* :func:`mock_session_state_with_user` — convenience fixture that constructs
  a fresh ``SessionStore``, inserts a single ``SessionState`` with
  ``user_id`` set, and returns the triple ``(store, session_id, user_id)``
  for webhook tests that depend on the authed-session code path.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.modules.captured_messages.schemas import CapturedMessage
from app.modules.whatsapp.schemas import SessionStatus
from app.modules.whatsapp.state import SessionState, SessionStore


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
    "app.modules.whatsapp.service",              # webhook handler (lazy import)
    "app.workers.ttl_cleanup",                   # TTL cleanup worker
    "app.modules.reports.service",               # report worker adapter
)


@pytest.fixture
def fake_captured_repo(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Replace every public function in ``app.modules.captured_messages.repository``
    with an ``AsyncMock``.

    Patches are applied by **dotted string path** with ``raising=False`` so
    attribute resolution is deferred to fixture-call time — if repository.py
    is still being authored by a sibling agent, the patch becomes a no-op
    rather than a collection-time AttributeError. Tests that actually depend
    on a missing patch target will fail loudly when they try to assert on the
    mock.

    Returns a ``SimpleNamespace`` of the five mocks so tests can write
    ``fake_captured_repo.insert_many.assert_awaited_once_with(...)``.

    Defaults (per task spec):

    * ``insert_many.return_value = 0``  — zero rows inserted
    * ``stats_for_user.return_value = {message_count, conversation_count,
      last_message_at: None}``
    * ``stats_for_session.return_value`` — same shape, all zero/None
    * ``query_window_for_user.return_value = []``
    * ``delete_for_session.return_value = 0``
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
        stats_for_user=stats_for_user,
        stats_for_session=stats_for_session,
        delete_for_session=delete_for_session,
    )


# ─── sample_captured_messages ──────────────────────────────────────────


# How many messages share a single wa_chatid before the factory rolls a new
# "conversation". Matches the task spec: "groups of 5 messages share the
# same wa_chatid".
_MSGS_PER_CONVERSATION: int = 5


@pytest.fixture
def sample_captured_messages():
    """Factory producing realistic ``CapturedMessage`` lists.

    Usage::

        msgs = sample_captured_messages(count=20, days=7)
        msgs = sample_captured_messages(count=50, days=30, with_groups=True)

    Generation rules:

    * ``count`` messages distributed over ``days`` days, with a deterministic
      offset (``random.Random(42)``) so test assertions are stable across runs.
    * Messages are grouped into "conversations" of 5 — every 5 consecutive
      messages share the same ``wa_chatid`` (and ``contact_name``).
    * Within a conversation ``is_from_me`` alternates ``False`` → ``True`` →
      ``False`` …, so the contact always opens the conversation.
    * Timestamps are aware ``datetime`` objects in UTC.
    * ``user_id`` and ``whatsapp_session_id`` default to fresh UUIDs unless
      overridden; passing the same UUID across calls produces a coherent
      per-user fixture set.
    * When ``with_groups=True``, every other conversation uses a ``@g.us``
      jid and a "Grupo …" contact name.
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
            # alternate. This matches the F3 sample_extracted_payload rule.
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


# ─── sample_uazapi_message_raw ─────────────────────────────────────────


@pytest.fixture
def sample_uazapi_message_raw():
    """Factory returning raw uazapi webhook payload dicts.

    uazapi's ``messages`` webhook delivers a wrapper of the form::

        {
          "key": {"id": "...", "remoteJid": "...", "fromMe": False, "participant": None},
          "messageTimestamp": <unix int>,
          "pushName": "Paciente X",
          "message": { <one of: conversation | extendedTextMessage | imageMessage | ... > }
        }

    This factory exposes three convenience builders for the shapes the F4
    webhook parser must recognize:

    * ``.make_text(text='oi', from_me=False, raw_message_id=None)`` —
      ``message.conversation`` shape (plain text).
    * ``.make_extended(text='oi formatado', from_me=False, raw_message_id=None)``
      — ``message.extendedTextMessage.text`` shape (formatted text /
      replies).
    * ``.make_image(caption='foto', from_me=False, raw_message_id=None)`` —
      ``message.imageMessage`` shape with a ``caption`` field.

    ``messageTimestamp`` is a unix INT in seconds (uazapi convention).
    ``raw_message_id`` defaults to a fresh ``uuid4().hex`` if not provided.
    """
    factory = SimpleNamespace()

    def _wrapper(
        *,
        message: dict,
        from_me: bool,
        raw_message_id: str | None,
        push_name: str,
        remote_jid: str,
    ) -> dict:
        now = datetime.now(timezone.utc)
        return {
            "key": {
                "id": raw_message_id or uuid4().hex,
                "remoteJid": remote_jid,
                "fromMe": from_me,
                "participant": None,
            },
            "messageTimestamp": int(now.timestamp()),
            "pushName": push_name,
            "message": message,
        }

    def make_text(
        text: str = "oi",
        from_me: bool = False,
        raw_message_id: str | None = None,
        push_name: str = "Paciente Teste",
        remote_jid: str = "5511900000001@s.whatsapp.net",
    ) -> dict:
        return _wrapper(
            message={"conversation": text},
            from_me=from_me,
            raw_message_id=raw_message_id,
            push_name=push_name,
            remote_jid=remote_jid,
        )

    def make_extended(
        text: str = "oi formatado",
        from_me: bool = False,
        raw_message_id: str | None = None,
        push_name: str = "Paciente Teste",
        remote_jid: str = "5511900000001@s.whatsapp.net",
    ) -> dict:
        return _wrapper(
            message={
                "extendedTextMessage": {
                    "text": text,
                    "contextInfo": {},
                }
            },
            from_me=from_me,
            raw_message_id=raw_message_id,
            push_name=push_name,
            remote_jid=remote_jid,
        )

    def make_image(
        caption: str = "foto",
        from_me: bool = False,
        raw_message_id: str | None = None,
        push_name: str = "Paciente Teste",
        remote_jid: str = "5511900000001@s.whatsapp.net",
    ) -> dict:
        return _wrapper(
            message={
                "imageMessage": {
                    "caption": caption,
                    "mimetype": "image/jpeg",
                    "url": "https://example.invalid/img.jpg",
                }
            },
            from_me=from_me,
            raw_message_id=raw_message_id,
            push_name=push_name,
            remote_jid=remote_jid,
        )

    factory.make_text = make_text
    factory.make_extended = make_extended
    factory.make_image = make_image
    return factory


# ─── mock_session_state_with_user ──────────────────────────────────────


@pytest.fixture
def mock_session_state_with_user() -> tuple[SessionStore, UUID, UUID]:
    """Build a fresh ``SessionStore`` with a single authed ``SessionState``.

    Useful for webhook tests that exercise the ``state.user_id is not None``
    path (i.e. messages can be attributed to a real user). Returns the
    triple ``(store, session_id, user_id)`` so tests can pass the store to
    the webhook handler and assert against the IDs directly.

    The state is inserted with status ``CONSUMED`` (post-F2 entry) since
    that's the only status under which ``user_id`` will be populated in
    production flow.
    """
    store = SessionStore()
    session_id = uuid4()
    user_id = uuid4()
    state = SessionState(
        session_id=session_id,
        uazapi_token="tok_test_abcdef",  # nosec: deterministic test fixture
        status=SessionStatus.CONSUMED,
        user_id=user_id,
    )
    # Direct dict insert — bypasses the public ``create`` API which expects
    # a QR code and resets status to PENDING. Safe because this fixture owns
    # the store instance end-to-end.
    store._sessions[session_id] = state
    return store, session_id, user_id
