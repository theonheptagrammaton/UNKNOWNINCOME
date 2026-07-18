"""REST + WS API routers."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import data, health, indicators

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(data.router)
api_router.include_router(indicators.router)
