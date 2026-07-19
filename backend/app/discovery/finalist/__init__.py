"""Finalist cross-validation (doc §6.1) — second-engine check + disagreement alarm."""

from __future__ import annotations

from app.discovery.finalist.base import FinalistEngine, FinalistResult
from app.discovery.finalist.crosscheck import Alarm, compare, get_finalist_engine

__all__ = ["Alarm", "FinalistEngine", "FinalistResult", "compare", "get_finalist_engine"]
