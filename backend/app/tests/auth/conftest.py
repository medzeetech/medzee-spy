"""Shared fixtures for auth module tests (F2).

MagicMock-spec'd Supabase admin client, factory-style monkeypatching of the
client getter, and AsyncMock-based monkeypatching of the repository functions.

Fixtures avoid importing the auth.repository module at conftest-collection
time — they patch by dotted string path inside the fixture body, which delays
attribute resolution until the fixture is requested by a test.

The repository return shape for ``get_profile`` mirrors the columns in
``medzee_spy.users_profile`` (per design § 6) so service-layer tests can pass
the dict straight through to ``MeResponse``.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from supabase import Client

from app.modules.auth.schemas import SignupRequest


# Stable test UUID — keeps assertions deterministic across runs.
TEST_USER_ID = UUID("11111111-1111-1111-1111-111111111111")

# PIVOT (2026-05-24): the autouse ``_configure_jwt_secret`` fixture is
# gone — signup no longer mints an extension pairing token, so auth
# tests no longer need ``SUPABASE_JWT_SECRET`` seeded.


# ─── Supabase admin client ─────────────────────────────────────────────


def _build_fake_session(user_id: UUID, email: str) -> SimpleNamespace:
    """Construct a gotrue-shaped response with ``.user`` and ``.session``."""
    user = SimpleNamespace(
        id=str(user_id),
        email=email,
        app_metadata={"projects": []},
    )
    session = SimpleNamespace(
        access_token="access_tok_test",
        refresh_token="refresh_tok_test",
        expires_in=3600,
        token_type="bearer",
        user=user,
    )
    return SimpleNamespace(user=user, session=session)


@pytest.fixture
def fake_supabase_admin() -> MagicMock:
    """A ``MagicMock(spec=Client)`` with the auth.admin surface pre-stubbed.

    Tests can override any return value via
    ``fake_supabase_admin.auth.admin.create_user.return_value = ...`` — the
    last assignment wins. Inspect calls via the same chain
    (``.call_args``, ``.assert_called_once_with(...)``).
    """
    # NOTE: ``spec=Client`` is intentionally **not** used. supabase-py's
    # ``Client.auth`` is a lazy ``@cached_property`` defined per-instance, so
    # it's invisible to ``MagicMock(spec=Client)`` — that spec would block
    # the ``.auth.admin.create_user`` chain that ``auth.service`` calls. Plain
    # MagicMock auto-vivifies the chain instead, which is what we need.
    fake = MagicMock(name="supabase_admin_client")
    # Import kept for type-only documentation — if a future maintainer
    # re-introduces spec=Client, the import is still here for them.
    _ = Client
    default_resp = _build_fake_session(TEST_USER_ID, "x@y.com")
    fake.auth.admin.create_user.return_value = default_resp
    fake.auth.admin.delete_user.return_value = None
    fake.auth.admin.update_user_by_id.return_value = default_resp
    fake.auth.sign_in_with_password.return_value = default_resp

    return fake


@pytest.fixture(autouse=True)
def _patch_fresh_anon_client(
    monkeypatch: pytest.MonkeyPatch,
) -> MagicMock:
    """Mocka ``_fresh_anon_client`` — usado em signup/login pra
    ``sign_in_with_password`` (separado do admin client pra não sujar
    a service_role key; ver auth/service.py).

    Devolve o mesmo mock instanciado uma vez, com ``sign_in_with_password``
    pré-stubbed pra retornar a session canônica. Testes que precisam
    customizar podem usar a fixture explicitamente.
    """
    fake_anon = MagicMock(name="fresh_anon_client")
    default_resp = _build_fake_session(TEST_USER_ID, "x@y.com")
    fake_anon.auth.sign_in_with_password.return_value = default_resp
    monkeypatch.setattr(
        "app.modules.auth.service._fresh_anon_client",
        lambda: fake_anon,
    )
    return fake_anon


@pytest.fixture
def fake_admin_supabase_factory(
    monkeypatch: pytest.MonkeyPatch,
    fake_supabase_admin: MagicMock,
) -> MagicMock:
    """Patch ``get_supabase_admin_client`` to return ``fake_supabase_admin``.

    Patches both the canonical location (``app.clients.supabase``) and any
    re-import the auth.service module may hold. Using ``raising=False`` on the
    service-side patch lets this fixture work before service.py imports the
    symbol — the patch becomes a no-op there in that case.
    """
    monkeypatch.setattr(
        "app.clients.supabase.get_supabase_admin_client",
        lambda: fake_supabase_admin,
    )
    # Auth service may ``from app.clients.supabase import get_supabase_admin_client``
    # at module load — patch that re-bound name too so call sites see the fake.
    monkeypatch.setattr(
        "app.modules.auth.service.get_supabase_admin_client",
        lambda: fake_supabase_admin,
        raising=False,
    )
    return fake_supabase_admin


# ─── Auth repository ───────────────────────────────────────────────────


@pytest.fixture
def fake_repository(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Replace every public function in ``app.modules.auth.repository`` with
    an ``AsyncMock``.

    Patches are applied by **dotted string path** so attribute resolution is
    deferred to fixture-call time — if repository.py is still being authored
    by a sibling agent, conftest collection won't blow up. The patch itself
    will of course fail loudly if a target name is missing when a test
    actually requests this fixture.

    Returns a ``SimpleNamespace`` of the four mocks so tests can write
    ``fake_repository.create_profile.assert_awaited_once_with(...)``.
    """
    create_profile = AsyncMock(return_value=None, name="create_profile")
    get_profile = AsyncMock(
        return_value={
            "user_id": TEST_USER_ID,
            "name": "Dr X",
            "email": "x@y.com",
            "phone": "5511999999999",
            "ticket_medio": 250.0,
            "clinic_segment": None,
        },
        name="get_profile",
    )
    update_profile = AsyncMock(return_value=None, name="update_profile")
    delete_profile = AsyncMock(return_value=None, name="delete_profile")

    # String-based setattr — resolves at call time, not at conftest import.
    monkeypatch.setattr(
        "app.modules.auth.repository.create_profile", create_profile
    )
    monkeypatch.setattr(
        "app.modules.auth.repository.get_profile", get_profile
    )
    monkeypatch.setattr(
        "app.modules.auth.repository.update_profile", update_profile
    )
    monkeypatch.setattr(
        "app.modules.auth.repository.delete_profile", delete_profile
    )

    # Also patch the names as they may be re-imported into auth.service — use
    # raising=False so this is harmless before service.py wires the imports.
    for fn_name, fn_mock in (
        ("create_profile", create_profile),
        ("get_profile", get_profile),
        ("update_profile", update_profile),
        ("delete_profile", delete_profile),
    ):
        monkeypatch.setattr(
            f"app.modules.auth.service.{fn_name}",
            fn_mock,
            raising=False,
        )

    return SimpleNamespace(
        create_profile=create_profile,
        get_profile=get_profile,
        update_profile=update_profile,
        delete_profile=delete_profile,
    )


# ─── Request factories ─────────────────────────────────────────────────


@pytest.fixture
def valid_signup_request():
    """Factory producing a ``SignupRequest`` with sane defaults.

    Override any field via kwargs::

        req = valid_signup_request(email="other@x.com", ticket_medio=None)
    """

    def _factory(**overrides) -> SignupRequest:
        defaults: dict = {
            "name": "Dr X",
            "email": "x@y.com",
            "phone": "5511999999999",
            "password": "hunter2",
            "ticket_medio": 250.0,
        }
        defaults.update(overrides)
        return SignupRequest(**defaults)

    return _factory
