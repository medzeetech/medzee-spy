import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.modules.whatsapp.state import session_store

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.API_BASE_URL.startswith("http://localhost"):
        logger.warning(
            "API_BASE_URL=%s is local — uazapi cannot deliver webhooks. "
            "Run cloudflared/ngrok and set API_BASE_URL to the tunnel URL in .env.",
            settings.API_BASE_URL,
        )

    # Always-on config dump: logs URL prefixes + token lengths so we can
    # diagnose env-var formatting issues (literal quotes from Railway dashboard,
    # accidental empties) without restarting blind. Token values are never
    # logged — only length + first/last char as fingerprints.
    def _fingerprint(value: str) -> str:
        if not value:
            return "<empty>"
        first = value[0] if value else ""
        last = value[-1] if value else ""
        return f"len={len(value)} first={first!r} last={last!r}"

    logger.info(
        "config dump: API_BASE_URL=%r UAZAPI_BASE_URL=%r "
        "UAZAPI_ADMIN_TOKEN=%s SUPABASE_URL=%r SUPABASE_KEY=%s "
        "SUPABASE_SERVICE_ROLE_KEY=%s ANTHROPIC_API_KEY=%s",
        settings.API_BASE_URL,
        settings.UAZAPI_BASE_URL,
        _fingerprint(settings.UAZAPI_ADMIN_TOKEN),
        settings.SUPABASE_URL,
        _fingerprint(settings.SUPABASE_KEY),
        _fingerprint(settings.SUPABASE_SERVICE_ROLE_KEY),
        _fingerprint(settings.ANTHROPIC_API_KEY),
    )

    for name, value in (
        ("API_BASE_URL", settings.API_BASE_URL),
        ("UAZAPI_BASE_URL", settings.UAZAPI_BASE_URL),
        ("SUPABASE_URL", settings.SUPABASE_URL),
    ):
        if value and (value.startswith('"') or value.endswith('"')):
            logger.error(
                "config: %s contains literal quote chars — re-enter without "
                "surrounding quotes in Railway Raw Editor.",
                name,
            )

    session_store.start_expire_loop()
    logger.info("session_store TTL expire loop started")
    try:
        yield
    finally:
        await session_store.stop_expire_loop()
        logger.info("session_store TTL expire loop stopped")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/health")
async def health_check():
    return {"status": "ok"}
