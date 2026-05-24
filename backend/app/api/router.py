from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import settings
from app.modules.auth.routes import router as auth_router
from app.modules.extension.routes import router as extension_router
from app.modules.reports.routes import router as reports_router
from app.modules.whatsapp.routes import router as whatsapp_router


def _assert_uazapi_enabled() -> None:
    """Gate every /api/whatsapp/* route behind the WHATSAPP_PROVIDER flag (F8 / CHX-13).

    When the provider is ``extension`` (the default after F8 cutover), the
    legacy uazapi surface is intentionally disabled — clients hitting any
    ``/api/whatsapp/*`` endpoint get **410 Gone** with a body that points
    them at ``/api/extension/*``. The dependency runs on every request, so
    flipping the flag at runtime (env or test monkeypatch) takes effect
    without re-importing the router.
    """
    if settings.WHATSAPP_PROVIDER != "uazapi":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "provider_disabled",
                "message": "uazapi provider is disabled. Use /api/extension/* endpoints.",
                "use": "/api/extension/*",
            },
        )


api_router = APIRouter()

api_router.include_router(
    whatsapp_router,
    prefix="/whatsapp",
    tags=["whatsapp"],
    dependencies=[Depends(_assert_uazapi_enabled)],
)
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(extension_router, prefix="/extension", tags=["extension"])
api_router.include_router(reports_router, prefix="/reports", tags=["reports"])
