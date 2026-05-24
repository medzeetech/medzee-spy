"""Pydantic schemas + enums for the auth module (F2).

Requests are normalized in the service layer (email lower+strip, etc.) — pydantic
here just enforces shape. Responses envelope what the frontend's
``@supabase/supabase-js`` ``setSession`` expects + the profile payload.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


# ─── Requests ──────────────────────────────────────────────────────────


class SignupRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str = Field(min_length=10, max_length=20)
    password: str = Field(min_length=6, max_length=128)
    ticket_medio: float | None = Field(default=None, ge=0)

    @field_validator("name", "phone")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class LoginRequest(BaseModel):
    email: EmailStr
    # Loose validation — Supabase Auth is the source of truth.
    password: str = Field(min_length=1, max_length=128)


class UpdateMeRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, min_length=10, max_length=20)
    ticket_medio: float | None = Field(default=None, ge=0)
    clinic_segment: Literal["saude", "odonto", "outro"] | None = None


# ─── Responses ─────────────────────────────────────────────────────────


class SessionPayload(BaseModel):
    """Subset of the Supabase auth session — the frontend stores these.

    ``access_token`` + ``refresh_token`` go straight into
    ``supabase.auth.setSession``. ``expires_in`` is informational (Supabase
    auto-refreshes via the refresh token).
    """

    access_token: str
    refresh_token: str
    expires_in: int
    token_type: Literal["bearer"] = "bearer"


class UserPayload(BaseModel):
    id: UUID
    email: EmailStr


class SignupResponse(BaseModel):
    user: UserPayload
    session: SessionPayload
    # F8 / CHX-01: short-lived JWT the frontend hands to the Chrome
    # extension on first install. Always present — the extension flow is
    # the default and emitting an unused token costs nothing.
    extension_pairing_token: str


class LoginResponse(BaseModel):
    user: UserPayload
    session: SessionPayload


class MeResponse(BaseModel):
    user_id: UUID
    name: str
    email: EmailStr
    phone: str
    ticket_medio: float | None = None
    clinic_segment: str | None = None
