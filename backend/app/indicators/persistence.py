"""Sync the in-code indicator registry into the ``indicator_defs`` table."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.indicators.registry import get_registry
from app.models.indicator import IndicatorDefinition

logger = logging.getLogger(__name__)


async def sync_indicator_defs(session: AsyncSession) -> int:
    """Upsert every registry entry into ``indicator_defs`` (idempotent).

    Returns the number of rows written. Existing rows are updated in place so the
    table always reflects the current registry without duplicating entries.
    """
    registry = get_registry()
    existing = {
        row.id: row
        for row in (await session.execute(select(IndicatorDefinition))).scalars().all()
    }

    for def_ in registry.values():
        payload = {
            "name": def_.name,
            "category": def_.category,
            "source": def_.source,
            "inputs": list(def_.inputs),
            "params": {k: v.model_dump() for k, v in def_.params.items()},
            "outputs": list(def_.outputs),
            "signal_templates": list(def_.signal_templates),
            "available": def_.available,
        }
        row = existing.get(def_.id)
        if row is None:
            session.add(IndicatorDefinition(id=def_.id, **payload))
        else:
            for key, value in payload.items():
                setattr(row, key, value)

    await session.commit()
    logger.info("indicator_defs synced: %d entries", len(registry))
    return len(registry)
