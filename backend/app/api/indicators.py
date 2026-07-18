"""Indicator registry API (doc §5): browse metadata and preview computations."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import settings
from app.indicators.compute import compute_indicator, effective_params
from app.indicators.registry import IndicatorDef, get_indicator, list_indicators

router = APIRouter(prefix="/indicators", tags=["indicators"])

# Hard cap on preview rows so the debug endpoint never dumps a full series.
_MAX_PREVIEW_ROWS = 2000


class IndicatorList(BaseModel):
    count: int
    indicators: list[IndicatorDef]


class ComputeRequest(BaseModel):
    symbol: str
    tf: str
    indicator_id: str
    params: dict[str, float] | None = None
    market: str | None = None
    start_ts: int | None = None
    end_ts: int | None = None
    limit: int = Field(default=500, ge=1, le=_MAX_PREVIEW_ROWS)


class ComputeResponse(BaseModel):
    market: str
    symbol: str
    tf: str
    indicator_id: str
    params: dict[str, float]
    outputs: list[str]
    count: int
    series: list[dict]


@router.get("", response_model=IndicatorList)
def get_indicators(
    category: str | None = Query(default=None),
    source: str | None = Query(default=None),
) -> IndicatorList:
    """List registry entries, optionally filtered by category and/or source."""
    defs = list_indicators(category=category, source=source)
    return IndicatorList(count=len(defs), indicators=defs)


@router.get("/{indicator_id}", response_model=IndicatorDef)
def get_indicator_detail(indicator_id: str) -> IndicatorDef:
    """One indicator definition, or 404 if it is not in the registry."""
    def_ = get_indicator(indicator_id)
    if def_ is None:
        raise HTTPException(status_code=404, detail=f"unknown indicator: {indicator_id!r}")
    return def_


@router.post("/compute", response_model=ComputeResponse)
def compute_preview(body: ComputeRequest) -> ComputeResponse:
    """Debug/preview: compute an indicator over stored data (last ``limit`` bars)."""
    def_ = get_indicator(body.indicator_id)
    if def_ is None:
        raise HTTPException(status_code=404, detail=f"unknown indicator: {body.indicator_id!r}")

    market = body.market or settings.market
    frame = compute_indicator(
        market, body.symbol, body.tf, body.indicator_id, body.params,
        start_ts=body.start_ts, end_ts=body.end_ts,
    )
    frame = frame.tail(body.limit)
    # JSON has no NaN/Inf — replace with null.
    frame = frame.replace([np.inf, -np.inf], np.nan)
    records = [
        {k: (None if (isinstance(v, float) and np.isnan(v)) else v) for k, v in row.items()}
        for row in frame.to_dict(orient="records")
    ]
    return ComputeResponse(
        market=market,
        symbol=body.symbol,
        tf=body.tf,
        indicator_id=body.indicator_id,
        params=effective_params(def_, body.params),
        outputs=def_.outputs,
        count=len(records),
        series=records,
    )
