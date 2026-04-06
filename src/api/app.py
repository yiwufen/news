"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.config import get_config
from src.api.dependencies import get_orchestrator
from src.api.models.responses import APIError, ErrorDetail
from src.api.routes import context, health, session, task


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    orchestrator = get_orchestrator()
    yield
    orchestrator.shutdown()


def create_app() -> FastAPI:
    """Create FastAPI application."""
    config = get_config()

    app = FastAPI(
        title=config.api_title,
        description=config.api_description,
        version=config.api_version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:  # type: ignore[misc]
        return JSONResponse(
            status_code=exc.status_code,
            content=APIError(
                error=ErrorDetail(
                    code=f"HTTP_{exc.status_code}",
                    message=str(exc.detail),
                ),
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:  # type: ignore[misc]
        return JSONResponse(
            status_code=500,
            content=APIError(
                error=ErrorDetail(
                    code="INTERNAL_ERROR",
                    message="An internal error occurred",
                ),
            ).model_dump(),
        )

    app.include_router(health.router)
    app.include_router(session.router, prefix="/api/v1")
    app.include_router(task.router, prefix="/api/v1")
    app.include_router(context.router, prefix="/api/v1")

    return app


app = create_app()
