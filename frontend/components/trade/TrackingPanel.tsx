"use client";

import { useEffect, useState } from "react";

import { fetchTracking, type TrackingError } from "@/lib/api";

// Live-vs-paper divergence (doc §15/Faz-7: canlı-paper sapma izleme).
//
// A live strategy and its paper twin run the same genome on the same signals, so
// their returns should track. A widening gap means live execution (slippage, latency,
// partial fills, funding timing) is drifting from the simulation — the earliest honest
// warning that backtest expectations no longer describe reality.
//
// The backend returns fractions; we render percentages. Correlation stays a raw ratio.

function pct(v: number | null): string {
  return v === null ? "—" : `${(v * 100).toFixed(2)}%`;
}

function ratio(v: number | null): string {
  return v === null ? "—" : v.toFixed(3);
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] uppercase tracking-wider text-fog-faint">{label}</span>
      <span className={`text-base font-semibold tabular-nums ${tone ?? "text-fog"}`}>{value}</span>
    </div>
  );
}

export function TrackingPanel() {
  const [data, setData] = useState<TrackingError | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      fetchTracking()
        .then(setData)
        .catch((e) => setErr(e instanceof Error ? e.message : String(e)));
    load();
    const id = setInterval(load, 15_000);
    return () => clearInterval(id);
  }, []);

  const gap = data?.cum_gap ?? null;
  const gapTone = gap === null ? undefined : gap >= 0 ? "text-profit" : "text-loss";

  return (
    <section className="flex flex-col gap-3 rounded border border-line bg-graphite p-4">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-fog">
          Live vs paper
        </h3>
        <span className="text-xs text-fog-faint">
          {data ? `${data.points} aligned points` : "tracking error"}
        </span>
      </div>

      {!data ? (
        <p className="text-sm text-fog-faint">{err ?? "Loading…"}</p>
      ) : data.points < 2 ? (
        <p className="text-sm text-fog-faint">
          Not enough overlapping equity snapshots yet — tracking error needs live and paper
          running side by side.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <Stat label="Tracking error" value={pct(data.tracking_error)} />
            <Stat label="Cum. gap (live−paper)" value={pct(gap)} tone={gapTone} />
            <Stat label="Correlation" value={ratio(data.correlation)} />
            <Stat label="Live return" value={pct(data.cum_return_live)} />
            <Stat label="Paper return" value={pct(data.cum_return_paper)} />
          </div>
          <p className="text-xs text-fog-faint">
            Tracking error is the stdev of the per-tick return difference. A rising value with
            falling correlation means live execution is drifting from the simulation.
          </p>
        </>
      )}
    </section>
  );
}
