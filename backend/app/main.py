import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.modules.whatsapp.state import session_store
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

    # F4-T7: captured_messages TTL cleanup worker (sibling to the in-memory
    # session expire loop above). Runs once every 24h; cancelled on shutdown.
    ttl_task = asyncio.create_task(ttl_cleanup_loop(), name="ttl_cleanup")
    logger.info("captured_messages TTL cleanup loop started")

    # Recovery: re-spawnar o poll fallback de connection pra cada sessão
    # ainda em 'pending' no DB. Sem isso, qualquer redeploy do backend mata
    # a poll task em memória — usuário escaneia QR depois e nada acontece
    # (webhook quebrado + poll perdido = travado em 'pending' eterno).
    #
    # PRÉ-VALIDAÇÃO de token: antes de respawnar o poll, dá um get_status
    # rápido. Se vier 401 (token rotacionado pela uazapi), marca a row como
    # failed e PULA. Sem isso, polls zumbis ficam martelando 401 por
    # max_wait_s (10min) e gastam quota — foi o problema observado em
    # produção (logs do paid mostraram 5+min de 401 em loop).
    try:
        from app.clients.whatsapp import get_provider
        from app.clients.whatsapp.errors import UazapiUnauthorized
        from app.modules.whatsapp import repository as whatsapp_repo
        from app.modules.whatsapp.service import get_service
        from uuid import UUID

        pending_rows = await whatsapp_repo.find_pending()
        if pending_rows:
            svc = get_service()
            provider = get_provider()
            respawned = 0
            invalidated = 0
            for row in pending_rows:
                row_id = UUID(str(row["id"]))
                token = row.get("uazapi_token")
                if not token:
                    try:
                        await whatsapp_repo.mark_failed(row_id, "no_token")
                    except Exception:
                        pass
                    invalidated += 1
                    continue

                # Pré-validação rápida: dispara get_status, se vier 401
                # marca failed direto e pula. Outras exceções tratamos como
                # transient e respawnamos o poll normalmente (ele tem retry).
                try:
                    await provider.get_status(token)
                except UazapiUnauthorized:
                    try:
                        await whatsapp_repo.mark_failed(row_id, "token_invalid")
                    except Exception:
                        pass
                    invalidated += 1
                    continue
                except Exception:
                    # Transient — vale respawnar e o poll cuida.
                    pass

                user_id_raw = row.get("user_id")
                row_user_id = UUID(str(user_id_raw)) if user_id_raw else None
                await session_store.create(
                    row_id,
                    uazapi_token=token,
                    qr_base64="",
                    user_id=row_user_id,
                )
                asyncio.create_task(
                    svc._poll_connection_fallback(row_id, token),
                    name=f"poll-connection-recovery-{row_id}",
                )
                respawned += 1

            logger.info(
                "startup_recovery.complete respawned=%d invalidated=%d total=%d",
                respawned,
                invalidated,
                len(pending_rows),
            )
    except Exception:
        logger.exception("startup_recovery.failed (ignored)")

    try:
        yield
    finally:
        ttl_task.cancel()
        try:
            await ttl_task
        except (asyncio.CancelledError, Exception):
            pass
        logger.info("captured_messages TTL cleanup loop stopped")
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
