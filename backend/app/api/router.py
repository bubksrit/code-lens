from fastapi import APIRouter
from backend.app.api.routes_health import router as health_router
from backend.app.api.routes_investigate import router as investigate_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(investigate_router)
