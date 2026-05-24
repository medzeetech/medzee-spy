"""Unit tests for ``AuthService`` (T11).

Mirrors the F1 testing style: the service is a thin orchestrator, so we
mock its collaborators (Supabase admin client, repository module, whatsapp
service) and exercise the orchestration logic directly. All fixtures live
in the sibling ``conftest.py`` (shipped in T5).

Patching strategy:
  * ``app.modules.auth.repository.*`` is replaced with ``AsyncMock`` by the
    ``fake_repository`` fixture — the service imports the *module* and calls
    ``repository.<fn>(...)`` so patching at the module-attribute level is
    correct for every consumer.
  * The whatsapp side is patched at the lazy import path used in
    ``_maybe_consume_whatsapp_session`` (``app.modules.whatsapp.service.get_service``).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from gotrue.errors import AuthApiError

from app.modules.auth.schemas import (
    LoginRequest,
    UpdateMeRequest,
)
from app.modules.auth.service import (
    AuthService,
    EmailAlreadyRegistered,
    InvalidCredentials,
    ProfileCreationFailed,
    ProfileNotFound,
    SupabaseAuthError,
    UserNotInSpy,
)

# Stable UUID — matches the one used by the fixture so dict lookups line up.
TEST_USER_ID = UUID("11111111-1111-1111-1111-111111111111")


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #


def _fake_user(
    user_id: UUID = TEST_USER_ID,
    email: str = "x@y.com",
    app_metadata: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=str(user_id),
        email=email,
        app_metadata=app_metadata if app_metadata is not None else {"projects": []},
    )


def _fake_session_response(
    user: SimpleNamespace | None = None,
) -> SimpleNamespace:
    u = user or _fake_user()
    session = SimpleNamespace(
        access_token="access_tok_test",
        refresh_token="refresh_tok_test",
        expires_in=3600,
        token_type="bearer",
        user=u,
    )
    return SimpleNamespace(user=u, session=session)


# --------------------------------------------------------------------------- #
# signup                                                                      #
# --------------------------------------------------------------------------- #


async def test_signup_happy_path(
    fake_supabase_admin: MagicMock,
    fake_repository,
    fake_whatsapp_service: MagicMock,
    valid_signup_request,
) -> None:
    """Wires create_user → app_metadata merge → profile insert → wpp link →
    sign-in. Returns SignupResponse populated from the sign-in payload."""
    session_id = uuid4()
    req = valid_signup_request(whatsapp_session_id=session_id)

    svc = AuthService(supabase=fake_supabase_admin)
    resp = await svc.signup(req)

    # create_user — note ``email_confirm=True`` and normalized email.
    fake_supabase_admin.auth.admin.create_user.assert_called_once()
    (create_arg,), _ = fake_supabase_admin.auth.admin.create_user.call_args
    assert create_arg["email"] == "x@y.com"
    assert create_arg["password"] == "hunter2"
    assert create_arg["email_confirm"] is True

    # update_user_by_id — merged projects must contain 'spy'.
    fake_supabase_admin.auth.admin.update_user_by_id.assert_called_once()
    (uid_arg, md_arg), _ = fake_supabase_admin.auth.admin.update_user_by_id.call_args
    assert uid_arg == str(TEST_USER_ID)
    assert "spy" in md_arg["app_metadata"]["projects"]

    # repository.create_profile — called with normalized kwargs.
    fake_repository.create_profile.assert_awaited_once()
    _, kwargs = fake_repository.create_profile.call_args
    assert kwargs == {
        "name": "Dr X",
        "email": "x@y.com",
        "phone": "5511999999999",
        "ticket_medio": 250.0,
    }
    # First positional arg is the UUID.
    args, _ = fake_repository.create_profile.call_args
    assert args[0] == TEST_USER_ID

    # whatsapp link.
    fake_whatsapp_service.consume_extracted.assert_awaited_once_with(
        session_id, TEST_USER_ID
    )

    # sign-in.
    fake_supabase_admin.auth.sign_in_with_password.assert_called_once_with(
        {"email": "x@y.com", "password": "hunter2"}
    )

    # response envelope.
    assert resp.report_pending is True
    assert resp.session_warning is None
    assert resp.user.id == TEST_USER_ID
    assert resp.session.access_token == "access_tok_test"

    # F8 / CHX-01: signup emits a short-lived extension pairing JWT and
    # the helper resolves the same user_id we just provisioned.
    assert resp.extension_pairing_token, "expected non-empty pairing token"
    from app.modules.extension.security import decode_pairing_token

    assert decode_pairing_token(resp.extension_pairing_token) == TEST_USER_ID


async def test_signup_normalizes_email(
    fake_supabase_admin: MagicMock,
    fake_repository,
    fake_whatsapp_service: MagicMock,
    valid_signup_request,
) -> None:
    """Whitespace + uppercase input must be lower+stripped before reaching
    Supabase or the profile row."""
    req = valid_signup_request(email=" Foo@BAR.COM ")

    svc = AuthService(supabase=fake_supabase_admin)
    await svc.signup(req)

    (create_arg,), _ = fake_supabase_admin.auth.admin.create_user.call_args
    assert create_arg["email"] == "foo@bar.com"

    _, kwargs = fake_repository.create_profile.call_args
    assert kwargs["email"] == "foo@bar.com"


async def test_signup_email_already_registered_raises(
    fake_supabase_admin: MagicMock,
    fake_repository,
    fake_whatsapp_service: MagicMock,
    valid_signup_request,
) -> None:
    """Supabase's duplicate-email response surfaces as EmailAlreadyRegistered."""
    fake_supabase_admin.auth.admin.create_user.side_effect = AuthApiError(
        "User already registered", 400, "user_already_exists"
    )

    svc = AuthService(supabase=fake_supabase_admin)
    with pytest.raises(EmailAlreadyRegistered):
        await svc.signup(valid_signup_request())

    # No downstream side-effects: profile not created, no rollback needed.
    fake_repository.create_profile.assert_not_awaited()
    fake_supabase_admin.auth.admin.delete_user.assert_not_called()


async def test_signup_profile_creation_failure_rolls_back(
    fake_supabase_admin: MagicMock,
    fake_repository,
    fake_whatsapp_service: MagicMock,
    valid_signup_request,
) -> None:
    """If repository.create_profile blows up, delete_user must fire so the
    orphan auth.users row is cleaned up. ProfileCreationFailed propagates."""
    fake_repository.create_profile.side_effect = RuntimeError("boom")

    svc = AuthService(supabase=fake_supabase_admin)
    with pytest.raises(ProfileCreationFailed):
        await svc.signup(valid_signup_request())

    fake_supabase_admin.auth.admin.delete_user.assert_called_once_with(
        str(TEST_USER_ID)
    )


async def test_signup_app_metadata_merges_with_existing(
    fake_supabase_admin: MagicMock,
    fake_repository,
    fake_whatsapp_service: MagicMock,
    valid_signup_request,
) -> None:
    """A user landed with ``projects=['news']`` keeps news and gains spy."""
    user = _fake_user(app_metadata={"projects": ["news"]})
    fake_supabase_admin.auth.admin.create_user.return_value = _fake_session_response(
        user=user
    )

    svc = AuthService(supabase=fake_supabase_admin)
    await svc.signup(valid_signup_request())

    (_, md_arg), _ = fake_supabase_admin.auth.admin.update_user_by_id.call_args
    assert md_arg == {"app_metadata": {"projects": ["news", "spy"]}}


async def test_signup_app_metadata_does_not_duplicate_spy(
    fake_supabase_admin: MagicMock,
    fake_repository,
    fake_whatsapp_service: MagicMock,
    valid_signup_request,
) -> None:
    """Spy already present → idempotent (no double-append)."""
    user = _fake_user(app_metadata={"projects": ["spy"]})
    fake_supabase_admin.auth.admin.create_user.return_value = _fake_session_response(
        user=user
    )

    svc = AuthService(supabase=fake_supabase_admin)
    await svc.signup(valid_signup_request())

    (_, md_arg), _ = fake_supabase_admin.auth.admin.update_user_by_id.call_args
    assert md_arg == {"app_metadata": {"projects": ["spy"]}}


async def test_signup_whatsapp_session_consume_fails(
    fake_supabase_admin: MagicMock,
    fake_repository,
    fake_whatsapp_service: MagicMock,
    valid_signup_request,
) -> None:
    """If consume_extracted raises, signup still completes — the response
    just carries session_warning='whatsapp_session_unavailable'."""
    fake_whatsapp_service.consume_extracted = AsyncMock(
        side_effect=RuntimeError("uazapi down")
    )

    req = valid_signup_request(whatsapp_session_id=uuid4())

    svc = AuthService(supabase=fake_supabase_admin)
    resp = await svc.signup(req)

    assert resp.report_pending is False
    assert resp.session_warning == "whatsapp_session_unavailable"
    # User is still fully provisioned (sign-in completed).
    fake_supabase_admin.auth.sign_in_with_password.assert_called_once()


async def test_signup_whatsapp_session_none(
    fake_supabase_admin: MagicMock,
    fake_repository,
    fake_whatsapp_service: MagicMock,
    valid_signup_request,
) -> None:
    """No session_id → consume_extracted not invoked; result is a clean
    no-warning envelope with report_pending=False."""
    req = valid_signup_request(whatsapp_session_id=None)

    svc = AuthService(supabase=fake_supabase_admin)
    resp = await svc.signup(req)

    fake_whatsapp_service.consume_extracted.assert_not_called()
    assert resp.report_pending is False
    assert resp.session_warning is None


async def test_signup_password_too_weak_supabase_error(
    fake_supabase_admin: MagicMock,
    fake_repository,
    fake_whatsapp_service: MagicMock,
    valid_signup_request,
) -> None:
    """A generic AuthApiError that isn't the duplicate-email family maps to
    SupabaseAuthError carrying the upstream message."""
    fake_supabase_admin.auth.admin.create_user.side_effect = AuthApiError(
        "Password is too weak", 422, "weak_password"
    )

    svc = AuthService(supabase=fake_supabase_admin)
    with pytest.raises(SupabaseAuthError) as excinfo:
        await svc.signup(valid_signup_request())

    assert "Password is too weak" in str(excinfo.value)


async def test_signup_with_whatsapp_session_links_user_to_session_store(
    fake_supabase_admin,
    fake_admin_supabase_factory,
    fake_repository,
    fake_whatsapp_service,
    valid_signup_request,
    monkeypatch,
):
    """F4-07: when signup arrives with whatsapp_session_id, AuthService must
    populate SessionState.user_id in the in-memory store so future webhook
    `messages` events can attribute new msgs to the right user."""
    session_id = uuid4()
    # Patch session_store.update to capture the call
    store_update = AsyncMock()
    monkeypatch.setattr(
        "app.modules.whatsapp.state.session_store.update",
        store_update,
    )

    svc = AuthService(supabase=fake_supabase_admin)
    req = valid_signup_request(whatsapp_session_id=session_id)
    response = await svc.signup(req)

    # The link call should have happened with the new user_id
    store_update.assert_awaited_once()
    args, kwargs = store_update.call_args
    assert args[0] == session_id
    assert kwargs.get("user_id") is not None
    # And the returned user_id should match what we linked
    assert kwargs["user_id"] == response.user.id


async def test_signup_without_whatsapp_session_skips_store_link(
    fake_supabase_admin,
    fake_admin_supabase_factory,
    fake_repository,
    fake_whatsapp_service,
    valid_signup_request,
    monkeypatch,
):
    """When whatsapp_session_id is None, no store update call should happen
    (avoids polluting the store with linkage for sessions that don't exist)."""
    store_update = AsyncMock()
    monkeypatch.setattr(
        "app.modules.whatsapp.state.session_store.update",
        store_update,
    )

    svc = AuthService(supabase=fake_supabase_admin)
    req = valid_signup_request(whatsapp_session_id=None)
    await svc.signup(req)

    store_update.assert_not_awaited()


# --------------------------------------------------------------------------- #
# login                                                                       #
# --------------------------------------------------------------------------- #


async def test_login_happy_path(
    fake_supabase_admin: MagicMock,
    fake_repository,
) -> None:
    """sign_in returns a user tagged with 'spy' → LoginResponse passes through."""
    user = _fake_user(app_metadata={"projects": ["spy"]})
    fake_supabase_admin.auth.sign_in_with_password.return_value = (
        _fake_session_response(user=user)
    )

    svc = AuthService(supabase=fake_supabase_admin)
    resp = await svc.login(LoginRequest(email="x@y.com", password="hunter2"))

    assert resp.user.id == TEST_USER_ID
    assert resp.user.email == "x@y.com"
    assert resp.session.access_token == "access_tok_test"


async def test_login_invalid_credentials_raises(
    fake_supabase_admin: MagicMock,
    fake_repository,
) -> None:
    """Supabase's 'invalid login credentials' family raises InvalidCredentials."""
    fake_supabase_admin.auth.sign_in_with_password.side_effect = AuthApiError(
        "Invalid login credentials", 400, "invalid_credentials"
    )

    svc = AuthService(supabase=fake_supabase_admin)
    with pytest.raises(InvalidCredentials):
        await svc.login(LoginRequest(email="x@y.com", password="hunter2"))


async def test_login_user_not_in_spy_raises(
    fake_supabase_admin: MagicMock,
    fake_repository,
) -> None:
    """A News-only subscriber (no 'spy' tag) is rejected with UserNotInSpy."""
    user = _fake_user(app_metadata={"projects": ["news"]})
    fake_supabase_admin.auth.sign_in_with_password.return_value = (
        _fake_session_response(user=user)
    )

    svc = AuthService(supabase=fake_supabase_admin)
    with pytest.raises(UserNotInSpy):
        await svc.login(LoginRequest(email="x@y.com", password="hunter2"))


# --------------------------------------------------------------------------- #
# get_me / update_me                                                          #
# --------------------------------------------------------------------------- #


async def test_get_me_returns_profile(
    fake_supabase_admin: MagicMock,
    fake_repository,
) -> None:
    """Repository returns a dict → straight-through MeResponse construction."""
    svc = AuthService(supabase=fake_supabase_admin)
    me = await svc.get_me(TEST_USER_ID)

    assert me.user_id == TEST_USER_ID
    assert me.name == "Dr X"
    assert me.email == "x@y.com"
    assert me.phone == "5511999999999"
    assert me.ticket_medio == 250.0


async def test_get_me_profile_missing_raises_not_found(
    fake_supabase_admin: MagicMock,
    fake_repository,
) -> None:
    """get_profile → None ⇒ ProfileNotFound (mapped to 404 in routes)."""
    fake_repository.get_profile.return_value = None

    svc = AuthService(supabase=fake_supabase_admin)
    with pytest.raises(ProfileNotFound):
        await svc.get_me(TEST_USER_ID)


async def test_update_me_calls_repo_with_filtered_fields(
    fake_supabase_admin: MagicMock,
    fake_repository,
) -> None:
    """``UpdateMeRequest.model_dump(exclude_none=True)`` is what hits the
    repo — name=None gets dropped, the rest goes through verbatim."""
    req = UpdateMeRequest(phone="5511888887777", clinic_segment="odonto")

    svc = AuthService(supabase=fake_supabase_admin)
    await svc.update_me(TEST_USER_ID, req)

    fake_repository.update_profile.assert_awaited_once()
    args, kwargs = fake_repository.update_profile.call_args
    assert args[0] == TEST_USER_ID
    # No ``name`` key — it was None and exclude_none dropped it.
    assert "name" not in kwargs
    assert kwargs == {
        "phone": "5511888887777",
        "clinic_segment": "odonto",
    }


# --------------------------------------------------------------------------- #
# _merge_projects static helper                                               #
# --------------------------------------------------------------------------- #


def test_merge_projects_static_helper() -> None:
    """Pure helper — exhaustive coverage in a single test since each branch
    is one line. Note: NOT async; the helper is sync/static."""
    # None metadata → seed empty dict, append new tag.
    assert AuthService._merge_projects(None, "spy") == {"projects": ["spy"]}

    # Empty dict, no projects key → seed list with the tag.
    assert AuthService._merge_projects({}, "spy") == {"projects": ["spy"]}

    # Existing list with one different entry → tag appended.
    assert AuthService._merge_projects(
        {"projects": ["news"]}, "spy"
    ) == {"projects": ["news", "spy"]}

    # Tag already present → idempotent (no duplicate).
    assert AuthService._merge_projects(
        {"projects": ["spy"]}, "spy"
    ) == {"projects": ["spy"]}

    # Non-dict input is treated like None — defensive against gotrue oddities.
    assert AuthService._merge_projects("not-a-dict", "spy") == {"projects": ["spy"]}
