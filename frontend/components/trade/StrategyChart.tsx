"use client";

import { useEffect, useMemo, useState } from "react";

import {
  fetchVersions,
  type Marker,
  type RunConfig,
  type SignalRow,
  type StrategyOut,
  type StrategyVersion,
} from "@/lib/api";
import { GenomeChart } from "@/components/backtest/GenomeChart";

// Live decision actions (bot engine) → the marker kinds PriceChart understands.
const ACTION_KIND: Record<string, string> = {
  open_long: "long_entry",
  open_short: "short_entry",
  close_long: "long_exit",
  close_short: "short_exit",
};

/**
 * The strategy's live chart in the Trade Deck: its active genome's indicators over
 * the full stored history (so recent bars — where the bot actually trades — are in
 * view), with the bot's real fills for this symbol overlaid on top of the backtest.
 */
export function StrategyChart({
  strategy,
  signals,
}: {
  strategy: StrategyOut;
  signals: SignalRow[];
}) {
  const [version, setVersion] = useState<StrategyVersion | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setVersion(null);
    setError(null);
    fetchVersions(strategy.id)
      .then((vs) => {
        if (!alive) return;
        const active =
          vs.find((v) => v.id === strategy.active_version_id) ?? vs[0] ?? null;
        if (!active) setError("this strategy has no saved version yet");
        setVersion(active);
      })
      .catch((e) => {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, [strategy.id, strategy.active_version_id]);

  // Draw over the full stored history so live signals (recent) share the time axis.
  const genome: RunConfig | null = useMemo(() => {
    if (!version) return null;
    return { ...version.genome.config, start_ts: null, end_ts: null };
  }, [version]);

  const liveMarkers: Marker[] = useMemo(() => {
    if (!genome) return [];
    return signals
      .filter((s) => s.symbol === genome.symbol && s.outcome === "filled")
      .map((s) => ({
        time: s.ts,
        price: 0, // unused by the renderer; markers anchor on time
        kind: ACTION_KIND[s.action] ?? "long_entry",
        live: true,
      }));
  }, [signals, genome]);

  if (error) {
    return (
      <p className="rounded border border-loss/50 bg-loss/10 px-3 py-2 text-sm text-loss">
        {error}
      </p>
    );
  }
  if (!genome) {
    return (
      <p className="text-sm text-fog-muted">
        <span className="animate-pulse text-paper">●</span> Loading strategy genome…
      </p>
    );
  }

  return (
    <GenomeChart
      genome={genome}
      extraMarkers={liveMarkers}
      note={`${strategy.name} · v${strategy.active_version ?? "—"} · ${genome.symbol} ${genome.tf} · indicators over stored history, live fills overlaid`}
    />
  );
}
