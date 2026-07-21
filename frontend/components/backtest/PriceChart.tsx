"use client";

import { useEffect, useMemo, useRef } from "react";
import {
  createChart,
  ColorType,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";

import type { Candle, IndicatorSeries, Marker } from "@/lib/api";
import { CHART } from "@/lib/defaults";
import { fmtDateTime } from "@/lib/format";

const sec = (ms: number) => (ms / 1000) as UTCTimestamp;

// Distinct hues that read on the graphite background. Assigned deterministically in
// draw order so the legend and the lines always agree.
const LINE_PALETTE = [
  "#d9a441", // gold (accent)
  "#5b9bd5", // blue
  "#c678dd", // violet
  "#4ec9b0", // teal
  "#e0af68", // amber
  "#7fb069", // green
  "#d78f5b", // orange
  "#8f9be0", // periwinkle
];

const PRICE_SCALE_WIDTH = 64; // align every pane's plot area to the same left edge
const SUB_PANE_HEIGHT = 130;

function toMarker(m: Marker): SeriesMarker<Time> {
  const long = m.kind.startsWith("long");
  const entry = m.kind.endsWith("entry");
  const live = m.live === true; // live bot fills render in gold to stand apart
  if (entry) {
    return {
      time: sec(m.time),
      position: long ? "belowBar" : "aboveBar",
      color: live ? CHART.accent : long ? CHART.profit : CHART.loss,
      shape: long ? "arrowUp" : "arrowDown",
      text: live ? (long ? "Live Long" : "Live Short") : long ? "Long" : "Short",
    };
  }
  return {
    time: sec(m.time),
    position: long ? "aboveBar" : "belowBar",
    color: live ? CHART.accent : CHART.muted,
    shape: long ? "arrowDown" : "arrowUp",
    text: live ? "Live Close" : m.forced ? "Close·EOD" : "Close",
  };
}

// Flatten every line across every indicator into draw order and stamp a colour, so
// the same colour map feeds both the chart and the legend.
type ColoredLine = { key: string; id: string; name: string; color: string };
function colorize(indicators: IndicatorSeries[]): {
  overlays: (IndicatorSeries & { colors: string[] })[];
  panes: (IndicatorSeries & { colors: string[] })[];
  legend: ColoredLine[];
} {
  let i = 0;
  const legend: ColoredLine[] = [];
  const withColors = indicators.map((ind) => {
    const colors = ind.lines.map((l) => {
      const color = LINE_PALETTE[i % LINE_PALETTE.length];
      i += 1;
      legend.push({ key: ind.key, id: ind.id, name: l.name, color });
      return color;
    });
    return { ...ind, colors };
  });
  return {
    overlays: withColors.filter((ind) => ind.pane === "price"),
    panes: withColors.filter((ind) => ind.pane === "separate"),
    legend,
  };
}

/**
 * Candlestick price chart with entry/exit markers, indicator overlays, and synced
 * oscillator sub-panes. `focusTrade` zooms the whole stack to a single round-trip.
 */
export function PriceChart({
  candles,
  markers,
  indicators = [],
  focusTrade = null,
}: {
  candles: Candle[];
  markers: Marker[];
  indicators?: IndicatorSeries[];
  focusTrade?: { entry_ts: number; exit_ts: number } | null;
}) {
  const priceRef = useRef<HTMLDivElement>(null);
  const subWrapRef = useRef<HTMLDivElement>(null);
  const mainChartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  const { overlays, panes, legend } = useMemo(
    () => colorize(indicators),
    [indicators],
  );

  useEffect(() => {
    if (!priceRef.current || !subWrapRef.current) return;
    const subWrap = subWrapRef.current;
    subWrap.innerHTML = "";
    const disposers: (() => void)[] = [];
    const charts: IChartApi[] = [];

    const baseOptions = (showTime: boolean) => ({
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
      rightPriceScale: { borderColor: CHART.border, minimumWidth: PRICE_SCALE_WIDTH },
      timeScale: {
        borderColor: CHART.border,
        timeVisible: true,
        visible: showTime,
      },
      localization: { timeFormatter: (t: number) => fmtDateTime(t * 1000) },
      autoSize: true,
    });

    const hasPanes = panes.length > 0;

    // ── Main price pane ───────────────────────────────────────────────────────
    const main = createChart(priceRef.current, baseOptions(!hasPanes));
    mainChartRef.current = main;
    charts.push(main);
    const candleSeries: ISeriesApi<"Candlestick"> = main.addCandlestickSeries({
      upColor: CHART.profit,
      downColor: CHART.loss,
      borderVisible: false,
      wickUpColor: CHART.profit,
      wickDownColor: CHART.loss,
    });
    candleSeries.setData(
      candles.map((c) => ({
        time: sec(c.time),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    );
    candleSeriesRef.current = candleSeries; // markers are set in their own effect

    // Price-scale overlays (moving averages, bands, VWAP) on the candle pane.
    for (const ind of overlays) {
      ind.lines.forEach((line, li) => {
        const s = main.addLineSeries({
          color: ind.colors[li],
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        s.setData(line.points.map((p) => ({ time: sec(p.time), value: p.value })));
      });
    }

    // ── Oscillator sub-panes (own scale, synced time axis) ────────────────────
    panes.forEach((ind, pi) => {
      const bottom = pi === panes.length - 1;
      const wrap = document.createElement("div");
      wrap.className = "relative border-t border-line";
      wrap.style.height = `${SUB_PANE_HEIGHT}px`;
      const label = document.createElement("div");
      label.className =
        "pointer-events-none absolute left-2 top-1 z-10 text-[10px] uppercase tracking-wider";
      label.style.color = CHART.muted;
      label.textContent = `${ind.key} · ${ind.id}`;
      const mount = document.createElement("div");
      mount.style.height = `${SUB_PANE_HEIGHT}px`;
      wrap.appendChild(label);
      wrap.appendChild(mount);
      subWrap.appendChild(wrap);

      const sub = createChart(mount, baseOptions(bottom));
      charts.push(sub);
      // Whitespace spine over every candle time so the sub-pane's logical indexing
      // matches the main pane exactly — an oscillator line that starts after warm-up
      // would otherwise shift the shared logical range and misalign the panes in time.
      sub
        .addLineSeries({ lastValueVisible: false, priceLineVisible: false })
        .setData(candles.map((c) => ({ time: sec(c.time) })));
      ind.lines.forEach((line, li) => {
        const s = sub.addLineSeries({
          color: ind.colors[li],
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        s.setData(line.points.map((p) => ({ time: sec(p.time), value: p.value })));
      });
    });

    // ── Time-axis sync across every pane (guarded against feedback) ───────────
    let syncing = false;
    for (const source of charts) {
      source.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (syncing || !range) return;
        syncing = true;
        for (const other of charts) {
          if (other !== source) other.timeScale().setVisibleLogicalRange(range);
        }
        syncing = false;
      });
    }
    main.timeScale().fitContent();

    disposers.push(() => {
      for (const c of charts) c.remove();
      mainChartRef.current = null;
      candleSeriesRef.current = null;
      subWrap.innerHTML = "";
    });
    return () => disposers.forEach((d) => d());
  }, [candles, overlays, panes]);

  // Markers update on their own — a live poll refreshing them must not rebuild the
  // whole chart. `candles` in the deps re-applies them after a rebuild recreates
  // the series (which the build effect, running first, has already done).
  useEffect(() => {
    const series = candleSeriesRef.current;
    if (!series) return;
    const sorted = [...markers].sort((a, b) => a.time - b.time);
    series.setMarkers(sorted.map(toMarker));
  }, [markers, candles]);

  // Zoom the whole stack to one trade's window (sync mirrors it to the sub-panes).
  useEffect(() => {
    const chart = mainChartRef.current;
    if (!chart) return;
    if (!focusTrade) {
      chart.timeScale().fitContent();
      return;
    }
    const span = focusTrade.exit_ts - focusTrade.entry_ts;
    const barMs =
      candles.length > 1 ? candles[1].time - candles[0].time : 60_000;
    const pad = Math.max(span * 0.5, barMs * 12);
    chart.timeScale().setVisibleRange({
      from: sec(focusTrade.entry_ts - pad),
      to: sec(focusTrade.exit_ts + pad),
    });
  }, [focusTrade, candles]);

  return (
    <div className="flex flex-col gap-2">
      {legend.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-fog-muted">
          {legend.map((l) => (
            <span key={`${l.key}-${l.name}`} className="flex items-center gap-1.5">
              <span
                className="inline-block h-0.5 w-4 rounded"
                style={{ backgroundColor: l.color }}
              />
              <span className="font-mono">
                {l.key}
                <span className="text-fog-faint">·{l.name}</span>
              </span>
            </span>
          ))}
        </div>
      )}
      <div ref={priceRef} className="h-[420px] w-full" />
      <div ref={subWrapRef} className="w-full" />
    </div>
  );
}
