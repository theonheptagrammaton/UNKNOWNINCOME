"""Market-data adapters. Exchange-specific code lives only here (doc §2 rule 8)."""

from __future__ import annotations

from app.data.adapters.base import MarketDataAdapter, MarketInfo

__all__ = ["MarketDataAdapter", "MarketInfo"]
