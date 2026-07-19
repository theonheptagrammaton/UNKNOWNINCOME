"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  LineStyle,
  type UTCTimestamp,
} from "lightweight-charts";

import type { Point } from "@/lib/api";
import { CHART } from "@/lib/defaults";
import { fmtDateTime } from "@/lib/format";

const sec = (ms: number) => (ms / 1000) as UTCTimestamp;

/** Equity curve (line) with the drawdown underlay (area, %). */
export function EquityChart({
  equity,
  drawdown,
  initialCash,
}: {
  equity: Point[];
  drawdown: Point[];
  initialCash: number;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      layout: {
        background: { type: ColorType.Solid, color: CHART.bg },
        textColor: CHART.text,
        fontFamily: "inherit",
      },
      grid: {
        vertLines: { color: CHART.grid },
        horzLines: { color: CHART.grid },
      },
      rightPriceScale: { borderColor: CHART.border },
      leftPriceScale: { visible: true, borderColor: CHART.border },
      timeScale: { borderColor: CHART.border, timeVisible: true },
      localization: { timeFormatter: (t: number) => fmtDateTime(t * 1000) },
      autoSize: true,
    });

    // Drawdown as a red area on the left scale (values are ≤ 0 fractions).
    const dd = chart.addAreaSeries({
      priceScaleId: "left",
      lineColor: CHART.loss,
      topColor: "rgba(229,72,77,0.05)",
      bottomColor: "rgba(229,72,77,0.35)",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    dd.setData(drawdown.map((p) => ({ time: sec(p.time), value: p.value })));

    const eq = chart.addLineSeries({
      priceScaleId: "right",
      color: CHART.profit,
      lineWidth: 2,
      priceLineVisible: false,
    });
    eq.setData(equity.map((p) => ({ time: sec(p.time), value: p.value })));

    // Baseline at starting capital.
    eq.createPriceLine({
      price: initialCash,
      color: CHART.muted,
      lineStyle: LineStyle.Dashed,
      lineWidth: 1,
      axisLabelVisible: true,
      title: "start",
    });

    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [equity, drawdown, initialCash]);

  return <div ref={ref} className="h-[300px] w-full" />;
}
