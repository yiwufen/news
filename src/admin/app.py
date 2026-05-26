from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.admin.config import AdminSettings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = AdminSettings()
    from src.admin.users import UserRepository

    repo = UserRepository(settings.db_path)
    if settings.admin_token:
        created = repo.create_default_admin(settings.admin_token)
        if created:
            import logging
            logging.getLogger("uvicorn").info("Default admin user created from ADMIN_TOKEN")
    yield


def create_app() -> FastAPI:
    settings = AdminSettings()

    app = FastAPI(
        title="Knowledge Admin",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from src.admin.routers import (
        articles,
        auth,
        dashboard,
        entities,
        event_clusters,
        health,
        knowledge_units,
        processing,
        users,
    )

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(health.router)
    app.include_router(dashboard.router, prefix="/api/v1")
    app.include_router(entities.router, prefix="/api/v1")
    app.include_router(knowledge_units.router, prefix="/api/v1")
    app.include_router(event_clusters.router, prefix="/api/v1")
    app.include_router(articles.router, prefix="/api/v1")
    app.include_router(processing.router, prefix="/api/v1")

    # Serve frontend SPA (static files built into /app/static in Docker)
    static_dir = Path(__file__).resolve().parent.parent.parent / "static"
    if static_dir.is_dir():
        app.mount("/admin", StaticFiles(directory=str(static_dir), html=True), name="admin-spa")

    return app
