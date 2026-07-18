"""indicator_defs persistence: full registry lands in the table, idempotently."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.indicators.persistence import sync_indicator_defs
from app.indicators.registry import get_registry
from app.models.indicator import IndicatorDefinition


async def _count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(IndicatorDefinition))).scalar()


async def test_sync_persists_full_registry(db_session: AsyncSession) -> None:
    written = await sync_indicator_defs(db_session)
    assert written == len(get_registry())
    assert await _count(db_session) == written

    row = (
        await db_session.execute(
            select(IndicatorDefinition).where(IndicatorDefinition.id == "rsi")
        )
    ).scalar_one()
    assert row.category == "momentum"
    assert row.source == "talib"
    assert row.outputs == ["rsi"]
    assert "timeperiod" in row.params


async def test_sync_is_idempotent(db_session: AsyncSession) -> None:
    first = await sync_indicator_defs(db_session)
    count_after_first = await _count(db_session)
    second = await sync_indicator_defs(db_session)
    count_after_second = await _count(db_session)

    assert first == second
    assert count_after_first == count_after_second, "re-sync duplicated rows"
