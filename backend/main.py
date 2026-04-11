from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.config import PROJECT_ROOT
from backend.config import get_settings
from backend.router import api_router


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Action research collaboration prototype.",
    )
    application.mount(
        "/static",
        StaticFiles(directory=PROJECT_ROOT / "frontend"),
        name="static",
    )
    application.include_router(api_router)
    return application


app = create_app()
