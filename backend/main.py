from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.api.router import api_router
from backend.core.config import PROJECT_ROOT
from backend.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Backend scaffold for an action-research facilitation system.",
    )
    application.mount(
        "/static",
        StaticFiles(directory=PROJECT_ROOT / "backend" / "static"),
        name="static",
    )
    application.include_router(api_router)
    return application


app = create_app()
