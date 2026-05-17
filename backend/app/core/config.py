from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    PROJECT_NAME: str = "MedZee Spy API"
    VERSION: str = "0.1.0"
    DEBUG: bool = False

    # Public base URL of this backend — uazapi needs to reach this to deliver
    # webhook callbacks. In dev, use a tunnel (cloudflared/ngrok) and update
    # API_BASE_URL in .env; localhost will trigger a warning at startup.
    API_BASE_URL: str = "http://localhost:8000"

    ALLOWED_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Supabase — instância compartilhada com o projeto News (D3).
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # WhatsApp via uazapi.com (D1).
    UAZAPI_BASE_URL: str = ""
    UAZAPI_ADMIN_TOKEN: str = ""
    UAZAPI_HTTP_TIMEOUT_S: float = 8.0

    # LLM provider — default Anthropic Claude (D2).
    LLM_PROVIDER: str = "anthropic"
    LLM_MODEL: str = "claude-sonnet-4-6"
    ANTHROPIC_API_KEY: str = ""

    # Extract pipeline tuning (F1 + F3 B3 fix).
    # Hard timeout precisa acomodar o retry budget (~220s no /chat/find) +
    # o fan-out de /message/find por chat — empiricamente até 7 min no
    # free tier. Override por env em prod se necessário.
    EXTRACT_DAYS_WINDOW: int = 30
    EXTRACT_PARALLELISM: int = 5
    EXTRACT_SOFT_TIMEOUT_S: int = 90
    EXTRACT_HARD_TIMEOUT_S: int = 420

    # In-memory session TTL (F1) — sessions older than this in non-terminal
    # status get auto-expired by the background loop in lifespan.
    SESSION_TTL_MINUTES: int = 15


settings = Settings()
