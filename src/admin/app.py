from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
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

    # Serve frontend SPA
    static_dir = Path(__file__).resolve().parent.parent.parent / "static"
    if static_dir.is_dir():
        app.mount("/admin/assets", StaticFiles(directory=str(static_dir / "assets")), name="admin-spa-assets")

        @app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
        async def admin_index():
            return FileResponse(static_dir / "index.html", media_type="text/html")

        @app.get("/admin/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
        async def admin_spa(full_path: str):
            target = (static_dir / full_path).resolve()
            if not str(target).startswith(str(static_dir.resolve())):
                return HTMLResponse("Forbidden", status_code=403)
            if target.is_file():
                return FileResponse(target)
            return FileResponse(static_dir / "index.html", media_type="text/html")

    return app
