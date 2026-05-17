from fastapi import APIRouter

from app.modules.auth.routes import router as auth_router
from app.modules.reports.routes import router as reports_router
from app.modules.whatsapp.routes import router as whatsapp_router

api_router = APIRouter()

api_router.include_router(whatsapp_router, prefix="/whatsapp", tags=["whatsapp"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(reports_router, prefix="/reports", tags=["reports"])
