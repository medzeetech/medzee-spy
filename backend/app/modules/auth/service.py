"""Auth service — signup, login, profile orchestration (F2).

T7 fills in :class:`AuthService` (signup/login/me/update_me + the F1 bridge).
The exception hierarchy lives at the top of this file so routes (T8) and
tests (T11/T12) can import the right types regardless of import order.

Logging policy mirrors the F1 service:

* ``op``, ``user_id`` (UUID, safe), ``email_domain``, ``status``, ``elapsed_ms``
  are emitted on entry/exit.
* ``password``, ``access_token``, ``refresh_token``, and full ``email`` are
  **never** logged. Supabase responses are not echoed.
"""
from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID

from gotrue.errors import AuthApiError

from app.clients.supabase import get_supabase_admin_client
from app.modules.auth import repository
from app.modules.auth.schemas import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    SessionPayload,
    SignupRequest,
    SignupResponse,
    UpdateMeRequest,
    UserPayload,
)

logger = logging.getLogger(__name__)


# ─── Exceptions ────────────────────────────────────────────────────────


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


# ─── Helpers ───────────────────────────────────────────────────────────


_SPY_PROJECT_TAG = "spy"


def _email_domain(email: str) -> str:
    _, _, domain = email.partition("@")
    return domain or "unknown"


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _is_already_registered(exc: AuthApiError) -> bool:
    """Best-effort match against the Supabase 'duplicate email' family."""
    message = (getattr(exc, "message", None) or str(exc) or "").lower()
    code = (getattr(exc, "code", None) or "").lower()
    if code in {
        "user_already_exists",
        "email_address_already_in_use",
        "email_exists",
    }:
        return True
    return (
        "already registered" in message
        or "already been registered" in message
        or "user already exists" in message
    )


def _is_invalid_credentials(exc: AuthApiError) -> bool:
    message = (getattr(exc, "message", None) or str(exc) or "").lower()
    code = (getattr(exc, "code", None) or "").lower()
    return code == "invalid_credentials" or "invalid login credentials" in message


def _projects_from(app_metadata: Any) -> list[str]:
    md = app_metadata if isinstance(app_metadata, dict) else {}
    raw = md.get("projects")
    return list(raw) if isinstance(raw, list) else []


def _session_payload_from(session: Any) -> SessionPayload:
    return SessionPayload(
        access_token=getattr(session, "access_token"),
        refresh_token=getattr(session, "refresh_token"),
        expires_in=int(getattr(session, "expires_in", 3600)),
    )


def _user_payload_from(user: Any) -> UserPayload:
    return UserPayload(id=UUID(str(user.id)), email=str(user.email))


# ─── Service ───────────────────────────────────────────────────────────


class AuthService:
    """Single entry point for auth business logic.

    Collaborators (Supabase admin client) are injected so tests can pass a
    :class:`unittest.mock.MagicMock`. The module-level :func:`get_auth_service`
    factory wires the production singleton.
    """

    def __init__(self, supabase: Any | None = None) -> None:
        self._supabase = supabase if supabase is not None else get_supabase_admin_client()

    # ── Signup ────────────────────────────────────────────────────────

    async def signup(self, req: SignupRequest) -> SignupResponse:
        """Create an auth user + profile + (optional) link a WhatsApp session.

        Sequence (AUTH-01..AUTH-10):
            1. Normalize email.
            2. ``auth.admin.create_user(email_confirm=True)`` — bypasses the
               email confirmation flow so the user is immediately usable.
            3. Merge ``'spy'`` into ``app_metadata.projects``.
            4. ``repository.create_profile`` — on failure, delete the auth
               user (best-effort) and raise :class:`ProfileCreationFailed`.
            5. ``_maybe_consume_whatsapp_session`` — non-fatal: failures only
               populate ``session_warning``.
            6. ``auth.sign_in_with_password`` to mint a session pair the
               frontend can stuff into ``supabase.auth.setSession``.
            7. Return the envelope.
        """
        started = time.monotonic()
        email = _normalize_email(req.email)
        logger.info(
            "service.auth.signup.enter",
            extra={"op": "signup", "email_domain": _email_domain(email)},
        )

        # Step 2 — create the auth user.
        try:
            create_response = self._supabase.auth.admin.create_user(
                {
                    "email": email,
                    "password": req.password,
                    "email_confirm": True,
                }
            )
        except AuthApiError as exc:
            if _is_already_registered(exc):
                logger.info(
                    "service.auth.signup.email_duplicate",
                    extra={
                        "op": "signup",
                        "email_domain": _email_domain(email),
                    },
                )
                raise EmailAlreadyRegistered(email) from exc
            logger.warning(
                "service.auth.signup.supabase_error",
                extra={
                    "op": "signup",
                    "email_domain": _email_domain(email),
                    "error_code": getattr(exc, "code", None),
                },
            )
            raise SupabaseAuthError(getattr(exc, "message", None) or str(exc)) from exc

        auth_user = getattr(create_response, "user", None) or create_response
        user_id = UUID(str(auth_user.id))

        # Step 3 — merge app_metadata.projects.
        merged_metadata = self._merge_projects(
            getattr(auth_user, "app_metadata", None), _SPY_PROJECT_TAG
        )
        try:
            self._supabase.auth.admin.update_user_by_id(
                str(user_id), {"app_metadata": merged_metadata}
            )
        except AuthApiError as exc:
            # Roll back: the auth user exists but we couldn't tag it. Without
            # the tag, login would later 403. Cleaner to delete + bubble up.
            self._safe_delete_auth_user(user_id)
            logger.warning(
                "service.auth.signup.metadata_failed",
                extra={
                    "op": "signup",
                    "user_id": str(user_id),
                    "error_code": getattr(exc, "code", None),
                },
            )
            raise SupabaseAuthError(getattr(exc, "message", None) or str(exc)) from exc

        # Step 4 — persist the profile (rollback the auth user on failure).
        try:
            await repository.create_profile(
                user_id,
                name=req.name,
                email=email,
                phone=req.phone,
                ticket_medio=req.ticket_medio,
            )
        except Exception as exc:
            self._safe_delete_auth_user(user_id)
            logger.exception(
                "service.auth.signup.profile_failed",
                extra={"op": "signup", "user_id": str(user_id)},
            )
            raise ProfileCreationFailed(str(user_id)) from exc

        # Step 4b — F4-07: link user_id em SessionStore in-memory pra o
        # webhook ``messages`` da uazapi conseguir atribuir cada msg nova
        # ao usuário recém-criado. Lazy import + best-effort: se falhar,
        # signup ainda completa; só perdemos captura até o user
        # reconectar.
        if req.whatsapp_session_id is not None:
            try:
                from app.modules.whatsapp.state import session_store
                await session_store.update(
                    req.whatsapp_session_id, user_id=user_id
                )
            except Exception:
                logger.warning(
                    "service.auth.signup.session_store_link_failed",
                    extra={
                        "op": "signup",
                        "user_id": str(user_id),
                        "session_id": str(req.whatsapp_session_id),
                    },
                    exc_info=True,
                )

        # Step 5 — bridge with F1 (non-fatal).
        report_pending, session_warning = await self._maybe_consume_whatsapp_session(
            req.whatsapp_session_id, user_id
        )

        # Step 6 — sign in to obtain session tokens.
        try:
            sign_in_response = self._supabase.auth.sign_in_with_password(
                {"email": email, "password": req.password}
            )
        except AuthApiError as exc:
            # The profile + auth user are already in place. The frontend can
            # recover by calling /auth/login. Surface as 400 so they know to.
            logger.warning(
                "service.auth.signup.sign_in_failed",
                extra={
                    "op": "signup",
                    "user_id": str(user_id),
                    "error_code": getattr(exc, "code", None),
                },
            )
            raise SupabaseAuthError(getattr(exc, "message", None) or str(exc)) from exc

        session = _session_payload_from(getattr(sign_in_response, "session"))
        user_payload = _user_payload_from(getattr(sign_in_response, "user", auth_user))

        logger.info(
            "service.auth.signup.exit",
            extra={
                "op": "signup",
                "user_id": str(user_id),
                "report_pending": report_pending,
                "session_warning": session_warning,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return SignupResponse(
            user=user_payload,
            session=session,
            report_pending=report_pending,
            session_warning=session_warning,
        )

    # ── Login ─────────────────────────────────────────────────────────

    async def login(self, req: LoginRequest) -> LoginResponse:
        """Sign in + verify the user is tagged for the Spy project.

        Sequence (AUTH-11..AUTH-13):
            1. ``auth.sign_in_with_password``.
            2. 401 path: any "invalid login credentials" error.
            3. 403 path: user has no ``'spy'`` in ``app_metadata.projects``.
            4. Return the envelope.
        """
        started = time.monotonic()
        email = _normalize_email(req.email)
        logger.info(
            "service.auth.login.enter",
            extra={"op": "login", "email_domain": _email_domain(email)},
        )

        try:
            response = self._supabase.auth.sign_in_with_password(
                {"email": email, "password": req.password}
            )
        except AuthApiError as exc:
            if _is_invalid_credentials(exc):
                # Indistinct from "unknown email" by design (AUTH-12).
                raise InvalidCredentials() from exc
            logger.warning(
                "service.auth.login.supabase_error",
                extra={
                    "op": "login",
                    "email_domain": _email_domain(email),
                    "error_code": getattr(exc, "code", None),
                },
            )
            raise SupabaseAuthError(getattr(exc, "message", None) or str(exc)) from exc

        user = getattr(response, "user", None)
        if user is None:
            raise InvalidCredentials()

        projects = _projects_from(getattr(user, "app_metadata", None))
        if _SPY_PROJECT_TAG not in projects:
            logger.info(
                "service.auth.login.user_not_in_spy",
                extra={
                    "op": "login",
                    "user_id": str(user.id),
                    "projects": projects,
                },
            )
            raise UserNotInSpy(str(user.id))

        session = _session_payload_from(getattr(response, "session"))
        logger.info(
            "service.auth.login.exit",
            extra={
                "op": "login",
                "user_id": str(user.id),
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return LoginResponse(
            user=_user_payload_from(user),
            session=session,
        )

    # ── Me ────────────────────────────────────────────────────────────

    async def get_me(self, user_id: UUID) -> MeResponse:
        profile = await repository.get_profile(user_id)
        if profile is None:
            raise ProfileNotFound(str(user_id))
        return MeResponse(
            user_id=user_id,
            name=profile["name"],
            email=profile["email"],
            phone=profile["phone"],
            ticket_medio=profile.get("ticket_medio"),
            clinic_segment=profile.get("clinic_segment"),
        )

    async def update_me(self, user_id: UUID, req: UpdateMeRequest) -> MeResponse:
        fields = req.model_dump(exclude_none=True)
        if not fields:
            return await self.get_me(user_id)
        await repository.update_profile(user_id, **fields)
        return await self.get_me(user_id)

    # ── Internals ─────────────────────────────────────────────────────

    async def _maybe_consume_whatsapp_session(
        self, session_id: UUID | None, user_id: UUID
    ) -> tuple[bool, str | None]:
        """Return ``(report_pending, session_warning)``.

        ``None`` for the session id is a happy-path no-op (signup without a
        prior /spy run). Any other failure surfaces as a warning string but
        does **not** raise — signup must complete even if the F1 link fails.

        Lazy-imports :mod:`app.modules.whatsapp.service` to avoid an import
        cycle (whatsapp.service may one day import auth helpers).
        """
        if session_id is None:
            return (False, None)
        try:
            from app.modules.whatsapp.service import get_service as get_whatsapp_service
        except ImportError:
            logger.warning(
                "service.auth.signup.whatsapp_module_missing",
                extra={"op": "signup", "user_id": str(user_id)},
            )
            return (False, "whatsapp_session_unavailable")

        try:
            wpp = get_whatsapp_service()
            payload = await wpp.consume_extracted(session_id, user_id)
            return (payload is not None, None)
        except Exception:
            logger.warning(
                "service.auth.signup.consume_whatsapp_failed",
                extra={
                    "op": "signup",
                    "user_id": str(user_id),
                    "session_id": str(session_id),
                },
                exc_info=True,
            )
            return (False, "whatsapp_session_unavailable")

    @staticmethod
    def _merge_projects(app_metadata: Any, new: str) -> dict[str, Any]:
        md = dict(app_metadata) if isinstance(app_metadata, dict) else {}
        projects = list(md.get("projects") or [])
        if new not in projects:
            projects.append(new)
        md["projects"] = projects
        return md

    def _safe_delete_auth_user(self, user_id: UUID) -> None:
        """Best-effort rollback of an auth.users row.

        Surfaces nothing — if this fails we leak an orphan but the user-
        facing operation still raises so the caller sees an error.
        """
        try:
            self._supabase.auth.admin.delete_user(str(user_id))
        except Exception:
            logger.exception(
                "service.auth.rollback_failed",
                extra={"op": "rollback", "user_id": str(user_id)},
            )


# ─── Factory ───────────────────────────────────────────────────────────


_service_singleton: AuthService | None = None


def get_auth_service() -> AuthService:
    """Return the process-wide :class:`AuthService` singleton.

    Memoized. Tests that need a fresh instance should construct
    :class:`AuthService` directly with mocks rather than poking at this.
    """
    global _service_singleton
    if _service_singleton is None:
        _service_singleton = AuthService()
    return _service_singleton


__all__ = [
    "AuthService",
    "AuthError",
    "EmailAlreadyRegistered",
    "InvalidCredentials",
    "UserNotInSpy",
    "ProfileNotFound",
    "ProfileCreationFailed",
    "SupabaseAuthError",
    "get_auth_service",
]
