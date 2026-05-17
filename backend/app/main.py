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

    # Always-on config dump via print() to bypass any logger filtering — INFO
    # logs were being dropped by the default root logger config on Railway.
    # Token values are never logged — only length + first/last char fingerprints.
    def _fingerprint(value: str) -> str:
        if not value:
            return "<empty>"
        return f"len={len(value)} first={value[0]!r} last={value[-1]!r}"

    print(
        "CONFIG_DUMP "
        f"API_BASE_URL={settings.API_BASE_URL!r} "
        f"UAZAPI_BASE_URL={settings.UAZAPI_BASE_URL!r} "
        f"UAZAPI_ADMIN_TOKEN=[{_fingerprint(settings.UAZAPI_ADMIN_TOKEN)}] "
        f"SUPABASE_URL={settings.SUPABASE_URL!r} "
        f"SUPABASE_KEY=[{_fingerprint(settings.SUPABASE_KEY)}] "
        f"SUPABASE_SERVICE_ROLE_KEY=[{_fingerprint(settings.SUPABASE_SERVICE_ROLE_KEY)}] "
        f"ANTHROPIC_API_KEY=[{_fingerprint(settings.ANTHROPIC_API_KEY)}]",
        flush=True,
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
