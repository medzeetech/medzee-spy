from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ``extra='ignore'`` tolerates stray legacy env vars left over from
    # earlier provider integrations that may still linger in production
    # .env files. They no longer affect behavior.
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "MedZee Spy API"
    VERSION: str = "0.1.0"
    DEBUG: bool = False

    # Public base URL of this backend (frontend / extension CORS gate).
    API_BASE_URL: str = "http://localhost:8000"

    ALLOWED_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Supabase — instância compartilhada com o projeto News (D3).
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # F8: Chrome extension tuning.
    # Pairing token TTL (curto: user precisa instalar a extensão em ~15min).
    EXTENSION_PAIRING_TOKEN_TTL_S: int = 15 * 60
    # Refresh token TTL (longo: extensão fica autenticada 30d).
    EXTENSION_REFRESH_TOKEN_TTL_S: int = 30 * 24 * 60 * 60
    # Versão mínima aceita da extensão (CHX-14). Floor: 1.0.0.
    EXTENSION_MIN_VERSION: str = "1.0.0"
    # Telemetry rate-limit (eventos por minuto por user, CHX-16).
    EXTENSION_TELEMETRY_RATE_PER_MINUTE: int = 60
    # JWT secret for extension pairing/refresh tokens (HS256). Required when
    # F8 endpoints are live. Default empty allows local dev / tests to seed it
    # via env or monkeypatch; production deploys must set this explicitly.
    SUPABASE_JWT_SECRET: str = ""

    # LLM provider — default Anthropic Claude (D2).
    LLM_PROVIDER: str = "anthropic"
    LLM_MODEL: str = "claude-sonnet-4-6"
    ANTHROPIC_API_KEY: str = ""


settings = Settings()
