from fastapi import APIRouter

from app.modules.auth.routes import router as auth_router
from app.modules.extension.routes import router as extension_router
from app.modules.reports.routes import router as reports_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(extension_router, prefix="/extension", tags=["extension"])
api_router.include_router(reports_router, prefix="/reports", tags=["reports"])
