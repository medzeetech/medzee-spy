from fastapi import APIRouter

from app.modules.whatsapp.routes import router as whatsapp_router

api_router = APIRouter()

api_router.include_router(whatsapp_router, prefix="/whatsapp", tags=["whatsapp"])
