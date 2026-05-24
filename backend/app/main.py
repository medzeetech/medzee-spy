import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.workers.ttl_cleanup import ttl_cleanup_loop

# Force INFO-level logs to surface in Railway. uvicorn doesn't touch the root
# logger by default, so any third-party / app-side logger.info call gets
# dropped (root threshold = WARNING). force=True overrides any prior config.
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s [%(name)s] %(message)s",
    force=True,
)

# Silenciar libs ruidosas que logam uma linha INFO em cada request HTTP.
# Mantemos nossos próprios logs de rota/serviço que trazem mais contexto.
for noisy in ("httpx", "httpcore", "hpack"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
        f"SUPABASE_URL={settings.SUPABASE_URL!r} "
        f"SUPABASE_KEY=[{_fingerprint(settings.SUPABASE_KEY)}] "
        f"SUPABASE_SERVICE_ROLE_KEY=[{_fingerprint(settings.SUPABASE_SERVICE_ROLE_KEY)}] "
        f"ANTHROPIC_API_KEY=[{_fingerprint(settings.ANTHROPIC_API_KEY)}]",
        flush=True,
    )

    for name, value in (
        ("API_BASE_URL", settings.API_BASE_URL),
        ("SUPABASE_URL", settings.SUPABASE_URL),
    ):
        if value and (value.startswith('"') or value.endswith('"')):
            logger.error(
                "config: %s contains literal quote chars — re-enter without "
                "surrounding quotes in Railway Raw Editor.",
                name,
            )

    # F4-T7 + F8: captured_messages TTL cleanup worker. Runs once every 24h;
    # cancelled on shutdown. Rolling-window deletion (delete rows older than
    # CAPTURED_MESSAGES_TTL_DAYS, default 30).
    ttl_task = asyncio.create_task(ttl_cleanup_loop(), name="ttl_cleanup")
    logger.info("captured_messages TTL cleanup loop started")

    try:
        yield
    finally:
        ttl_task.cancel()
        try:
            await ttl_task
        except (asyncio.CancelledError, Exception):
            pass
        logger.info("captured_messages TTL cleanup loop stopped")


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
