"""FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import settings
from app.core.db import SessionLocal, init_models
from app.core.logging import configure_logging
from app.core.version import APP_VERSION
from app.indicators.persistence import sync_indicator_defs


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create schema and sync the indicator registry (tolerant if DB is down)."""
    await init_models()
    try:
        async with SessionLocal() as session:
            await sync_indicator_defs(session)
    except Exception as exc:  # pragma: no cover - startup resilience
        import logging

        logging.getLogger(__name__).warning("indicator_defs sync skipped: %s", exc)
    yield


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    configure_logging()
    app = FastAPI(title="UNKNOWNINCOME API", version=APP_VERSION, lifespan=lifespan)

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
