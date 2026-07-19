"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  CrosshairMode,
  type IChartApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";

import type { Candle, Marker } from "@/lib/api";
import { CHART } from "@/lib/defaults";
import { fmtDateTime } from "@/lib/format";

const sec = (ms: number) => (ms / 1000) as UTCTimestamp;

function toMarker(m: Marker): SeriesMarker<Time> {
  const long = m.kind.startsWith("long");
  const entry = m.kind.endsWith("entry");
  if (entry) {
    return {
      time: sec(m.time),
      position: long ? "belowBar" : "aboveBar",
      color: long ? CHART.profit : CHART.loss,
      shape: long ? "arrowUp" : "arrowDown",
      text: long ? "Long" : "Short",
    };
  }
  return {
    time: sec(m.time),
    position: long ? "aboveBar" : "belowBar",
    color: CHART.muted,
    shape: long ? "arrowDown" : "arrowUp",
    text: m.forced ? "Close·EOD" : "Close",
  };
}

/** Candlestick price chart with entry/exit markers (lightweight-charts). */
export function PriceChart({
  candles,
  markers,
}: {
  candles: Candle[];
  markers: Marker[];
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart: IChartApi = createChart(ref.current, {
      layout: {
        background: { type: ColorType.Solid, color: CHART.bg },
        textColor: CHART.text,
        fontFamily: "inherit",
      },
      grid: {
        vertLines: { color: CHART.grid },
        horzLines: { color: CHART.grid },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: CHART.border },
      timeScale: { borderColor: CHART.border, timeVisible: true },
      localization: { timeFormatter: (t: number) => fmtDateTime(t * 1000) },
      autoSize: true,
    });

    const series = chart.addCandlestickSeries({
      upColor: CHART.profit,
      downColor: CHART.loss,
      borderVisible: false,
      wickUpColor: CHART.profit,
      wickDownColor: CHART.loss,
    });
    series.setData(
      candles.map((c) => ({
        time: sec(c.time),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    );

    const sorted = [...markers].sort((a, b) => a.time - b.time);
    series.setMarkers(sorted.map(toMarker));
    chart.timeScale().fitContent();

    return () => chart.remove();
  }, [candles, markers]);

  return <div ref={ref} className="h-[420px] w-full" />;
}
