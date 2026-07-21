"use client";

import { useEffect, useRef, useState } from "react";

import type { RunDetail as RunDetailType } from "@/lib/api";

import { EquityChart } from "./EquityChart";
import { MetricsPanel } from "./MetricsPanel";
import { MonthlyHeatmap } from "./MonthlyHeatmap";
import { PriceChart } from "./PriceChart";
import { Section } from "./Section";
import { TradesTable } from "./TradesTable";

/** Full run report: metrics, price+markers+indicators, equity/drawdown, heatmap, trades. */
export function RunDetail({ run }: { run: RunDetailType }) {
  const { metrics, report } = run;
  const [selected, setSelected] = useState<number | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);

  // Selecting a trade zooms the chart, but the chart sits above the (often
  // scrolled-past) trades table — bring it back into view so the click has a
  // visible effect instead of silently re-framing something off-screen.
  useEffect(() => {
    if (selected != null) {
      chartRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [selected]);

  if (!metrics || !report) {
    return (
      <p className="text-sm text-fog-muted">
        Run <span className="font-mono">{run.id}</span> is {run.status}.
      </p>
    );
  }

  const focusTrade =
    selected != null && report.trades[selected]
      ? {
          entry_ts: report.trades[selected].entry_ts,
          exit_ts: report.trades[selected].exit_ts,
        }
      : null;

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h2 className="text-2xl font-semibold tracking-tight">
          {report.symbol}
        </h2>
        <span className="text-sm uppercase tracking-wider text-fog-muted">
          {report.tf} · {report.direction}
        </span>
        <span className="font-mono text-xs text-fog-faint">
          {report.bars} bars · #{report.config_hash}
        </span>
      </div>

      <MetricsPanel metrics={metrics} cost={report.cost_breakdown} />

      <div ref={chartRef} className="scroll-mt-4">
        <Section
          title="Price & signals"
          subtitle={
            focusTrade
              ? undefined
              : "entries ▲ / exits ▽ · indicators overlaid"
          }
        >
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
          <PriceChart
            candles={report.candles}
            markers={report.markers}
            indicators={report.indicators}
            focusTrade={focusTrade}
          />
        </Section>
      </div>

      <Section title="Equity & drawdown">
        <EquityChart
          equity={report.equity}
          drawdown={report.drawdown}
          initialCash={run.config.capital.initial_cash}
        />
      </Section>

      <Section title="Monthly returns">
        <MonthlyHeatmap data={metrics.monthly_returns} />
      </Section>

      <Section
        title="Trades"
        subtitle={`${report.trades.length} round-trips · click a row to focus the chart`}
      >
        <TradesTable
          trades={report.trades}
          selectedIndex={selected}
          onSelect={setSelected}
        />
      </Section>
    </div>
  );
}
