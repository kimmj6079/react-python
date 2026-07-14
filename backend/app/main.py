from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, items
from app.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(title=settings.project_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(items.router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
