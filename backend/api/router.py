from fastapi import APIRouter

from backend.api.routes.dialogue import router as dialogue_router
from backend.api.routes.frontend import router as frontend_router
from backend.api.routes.health import router as health_router

api_router = APIRouter()
api_router.include_router(frontend_router)
api_router.include_router(health_router, tags=["health"])
api_router.include_router(dialogue_router, prefix="/dialogue", tags=["dialogue"])
