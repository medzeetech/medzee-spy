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

    # Quote-trap diagnostic: Railway-style env entry may keep literal quotes
    # in the value. Warn loudly so deploys don't fail silently with "uazapi
    # unavailable" downstream.
    for name, value in (
        ("API_BASE_URL", settings.API_BASE_URL),
        ("UAZAPI_BASE_URL", settings.UAZAPI_BASE_URL),
        ("SUPABASE_URL", settings.SUPABASE_URL),
    ):
        if value and (value.startswith('"') or value.endswith('"')):
            logger.error(
                "config: %s contains literal quote chars (value starts/ends "
                "with \"). Re-enter in Railway Raw Editor without surrounding "
                "quotes. len=%d head=%r",
                name,
                len(value),
                value[:30],
            )
        elif not value:
            logger.warning("config: %s is empty", name)

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
