from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.admin.config import AdminSettings


def create_app() -> FastAPI:
    settings = AdminSettings()

    app = FastAPI(
        title="Knowledge Admin",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Import routers
    from src.admin.routers import articles, dashboard, entities, event_clusters, health, knowledge_units, processing

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
