import type { RunDetail as RunDetailType } from "@/lib/api";

import { EquityChart } from "./EquityChart";
import { MetricsPanel } from "./MetricsPanel";
import { MonthlyHeatmap } from "./MonthlyHeatmap";
import { PriceChart } from "./PriceChart";
import { Section } from "./Section";
import { TradesTable } from "./TradesTable";

/** Full run report: metrics, price+markers, equity/drawdown, heatmap, trades. */
export function RunDetail({ run }: { run: RunDetailType }) {
  const { metrics, report } = run;
  if (!metrics || !report) {
    return (
      <p className="text-sm text-fog-muted">
        Run <span className="font-mono">{run.id}</span> is {run.status}.
      </p>
    );
  }

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

      <Section title="Price & signals" subtitle="entries ▲ / exits ▽">
        <PriceChart candles={report.candles} markers={report.markers} />
      </Section>

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

      <Section title="Trades" subtitle={`${report.trades.length} round-trips`}>
        <TradesTable trades={report.trades} />
      </Section>
    </div>
  );
}
