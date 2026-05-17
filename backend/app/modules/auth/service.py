"""Auth service — signup, login, profile orchestration (F2).

T2 (this commit) ships only the exception hierarchy so T3/T8 can already
import the right types. T7 fills in ``AuthService`` with signup/login/me/
update_me + the F1 bridge.
"""
from __future__ import annotations


class AuthError(Exception):
    """Base error for the auth module."""


class EmailAlreadyRegistered(AuthError):
    """Supabase Auth signaled the email is already in use (409 in routes)."""


class InvalidCredentials(AuthError):
    """Login failed — email or password wrong.

    Intentionally indistinguishable from an unknown email to prevent
    enumeration (mapped to 401 in routes).
    """


class UserNotInSpy(AuthError):
    """Login succeeded against Supabase but the user has no ``app_metadata``
    tag for the Spy project (403 in routes).

    Common case: a News-only subscriber trying to access the Spy app.
    """


class ProfileNotFound(AuthError):
    """``medzee_spy.users_profile`` lookup returned no row (404 in routes)."""


class ProfileCreationFailed(AuthError):
    """Auth user was created but the profile INSERT failed.

    The service is expected to roll back the auth.users row before
    raising this (best-effort). Surfaces as 500 in routes.
    """


class SupabaseAuthError(AuthError):
    """Any unclassified error from ``supabase.auth.*`` calls (400 in routes).

    The wrapped Supabase message is exposed in ``detail`` so the frontend
    can surface a useful hint (e.g. "password is too weak").
    """
