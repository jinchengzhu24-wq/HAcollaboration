from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.sessions import router as sessions_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(sessions_router, prefix="/sessions", tags=["sessions"])

