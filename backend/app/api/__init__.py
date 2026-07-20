"""REST + WS API routers."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import backtest, bot, data, discovery, health, indicators, strategies

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(data.router)
api_router.include_router(indicators.router)
api_router.include_router(backtest.router)
api_router.include_router(discovery.router)
api_router.include_router(strategies.router)
api_router.include_router(bot.router)
