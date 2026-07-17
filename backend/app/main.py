"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import settings
from app.core.version import APP_VERSION


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(title="UNKNOWNINCOME API", version=APP_VERSION)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    return app


app = create_app()
