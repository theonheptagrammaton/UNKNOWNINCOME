"""REST + WS API routers."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import backtest, data, discovery, health, indicators

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(data.router)
api_router.include_router(indicators.router)
api_router.include_router(backtest.router)
api_router.include_router(discovery.router)
