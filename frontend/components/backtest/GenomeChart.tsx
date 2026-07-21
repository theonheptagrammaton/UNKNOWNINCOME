"use client";

import { useEffect, useRef, useState } from "react";

import {
  previewRun,
  type Marker,
  type Metrics,
  type Report,
  type RunConfig,
} from "@/lib/api";
import { fmtPct } from "@/lib/format";

import { PriceChart } from "./PriceChart";
import { TradesTable } from "./TradesTable";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; report: Report; metrics: Metrics | null };

/**
 * On-demand backtest chart for a strategy genome (Discovery leaderboard, Trade Deck).
 * Runs the genome through the synchronous preview endpoint — the exact same engine
 * as a queued run — and draws candles, indicator overlays/sub-panes and entry/exit
 * markers. `extraMarkers` lets a caller overlay live signals on top of the backtest.
 */
export function GenomeChart({
  genome,
  extraMarkers,
  note,
}: {
  genome: RunConfig;
  extraMarkers?: Marker[];
  note?: string;
}) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [selected, setSelected] = useState<number | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    setState({ kind: "loading" });
    setSelected(null);
    previewRun(genome)
      .then((res) => {
        if (!alive) return;
        if (!res.report) {
          setState({ kind: "error", message: "preview returned no report" });
          return;
        }
        setState({ kind: "ready", report: res.report, metrics: res.metrics });
      })
      .catch((e) => {
        if (alive) {
          setState({ kind: "error", message: e instanceof Error ? e.message : String(e) });
        }
      });
    return () => {
      alive = false;
    };
  }, [genome]);

  useEffect(() => {
    if (selected != null) {
      chartRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [selected]);

  if (state.kind === "loading") {
    return (
      <p className="text-sm text-fog-muted">
        <span className="animate-pulse text-paper">●</span> Running preview backtest…
      </p>
    );
  }
  if (state.kind === "error") {
    return (
      <p className="rounded border border-loss/50 bg-loss/10 px-3 py-2 text-sm text-loss">
        Chart preview failed: {state.message}
      </p>
    );
  }

  const { report, metrics } = state;
  const focusTrade =
    selected != null && report.trades[selected]
      ? {
          entry_ts: report.trades[selected].entry_ts,
          exit_ts: report.trades[selected].exit_ts,
        }
      : null;
  // Overlay only live fills that fall inside the drawn window — a signal newer than
  // the latest stored bar has no candle to anchor to, so it is dropped rather than
  // clamped to the edge.
  const lo = report.candles[0]?.time ?? -Infinity;
  const hi = report.candles[report.candles.length - 1]?.time ?? Infinity;
  const liveMarkers =
    extraMarkers?.filter((m) => m.time >= lo && m.time <= hi) ?? [];
  const markers = [...report.markers, ...liveMarkers];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span className="text-[11px] uppercase tracking-wider text-fog-faint">
          {note ?? "Preview backtest · single-pass over the genome's window"}
        </span>
        <span className="text-xs text-fog-faint">
          {report.trades.length} trades · net {fmtPct(metrics?.net_return)} ·{" "}
          {report.bars} bars
        </span>
      </div>

      {extraMarkers && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-fog-faint">
          <span className="flex items-center gap-1.5">
            <span className="text-profit">▲</span>/
            <span className="text-loss">▽</span> backtest fills
          </span>
          <span className="flex items-center gap-1.5" style={{ color: "#d9a441" }}>
            ◆ live bot fills ({liveMarkers.length}
            {extraMarkers.length !== liveMarkers.length
              ? ` shown · ${extraMarkers.length - liveMarkers.length} outside window`
              : ""}
            )
          </span>
        </div>
      )}

      {focusTrade && (
        <div className="flex items-center gap-3 rounded border border-paper/40 bg-paper/10 px-3 py-1.5 text-xs text-paper">
          <span>
            Focused on trade #{(selected ?? 0) + 1} ·{" "}
            <span className="uppercase">{report.trades[selected!].side}</span>
          </span>
          <button
            type="button"
            onClick={() => setSelected(null)}
            className="rounded border border-paper/40 px-2 py-0.5 text-[11px] hover:bg-paper/20"
          >
            Reset zoom
          </button>
        </div>
      )}

      <div ref={chartRef} className="scroll-mt-4">
        <PriceChart
          candles={report.candles}
          markers={markers}
          indicators={report.indicators}
          focusTrade={focusTrade}
        />
      </div>

      <TradesTable
        trades={report.trades}
        selectedIndex={selected}
        onSelect={setSelected}
      />
    </div>
  );
}
