import type { CostBreakdown, Metrics } from "@/lib/api";
import { fmtMoney, fmtNum, fmtPct } from "@/lib/format";

function Tile({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "profit" | "loss" | "neutral";
}) {
  const color =
    tone === "profit"
      ? "text-profit"
      : tone === "loss"
        ? "text-loss"
        : "text-fog";
  return (
    <div className="flex flex-col gap-1 rounded-md border border-line bg-graphite px-4 py-3">
      <span className="text-[11px] uppercase tracking-wider text-fog-faint">
        {label}
      </span>
      <span className={`font-mono text-lg ${color}`}>{value}</span>
    </div>
  );
}

function signTone(v: number | null | undefined): "profit" | "loss" | "neutral" {
  if (v === null || v === undefined || !Number.isFinite(v)) return "neutral";
  return v > 0 ? "profit" : v < 0 ? "loss" : "neutral";
}

function CostBadges({ cb }: { cb: CostBreakdown }) {
  const badge = (on: boolean, label: string, detail: string) => (
    <span
      key={label}
      className={`inline-flex items-center gap-2 rounded border px-2.5 py-1 text-xs ${
        on
          ? "border-line text-fog-muted"
          : "border-loss/50 bg-loss/10 text-loss"
      }`}
    >
      <span className="uppercase tracking-wider">{label}</span>
      <span className="font-mono">{on ? detail : "OFF"}</span>
    </span>
  );
  return (
    <div className="flex flex-wrap items-center gap-2">
      {cb.costless && (
        <span className="rounded border border-loss bg-loss/15 px-2.5 py-1 text-xs font-semibold uppercase tracking-wider text-loss">
          Costless run
        </span>
      )}
      {badge(cb.commission_on, "Commission", fmtMoney(cb.total_commission))}
      {badge(cb.slippage_on, "Slippage", fmtMoney(cb.total_slippage))}
      {badge(cb.funding_on, "Funding", fmtMoney(cb.total_funding))}
    </div>
  );
}

/** Full §6.3 metric grid + §6.4 composite score + cost model badges. */
export function MetricsPanel({
  metrics,
  cost,
}: {
  metrics: Metrics;
  cost: CostBreakdown;
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="text-xs uppercase tracking-[0.2em] text-fog-faint">
            Composite score
          </span>
          <span className="font-mono text-2xl">
            {fmtNum(metrics.composite_score, 3)}
          </span>
          <span
            className={`rounded-full border px-2.5 py-0.5 text-xs uppercase tracking-wider ${
              metrics.passes_hard_filters
                ? "border-profit/50 text-profit"
                : "border-off/50 text-fog-faint"
            }`}
          >
            {metrics.passes_hard_filters ? "passes filters" : "below filters"}
          </span>
        </div>
        <CostBadges cb={cost} />
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <Tile
          label="Net return"
          value={fmtPct(metrics.net_return)}
          tone={signTone(metrics.net_return)}
        />
        <Tile label="CAGR" value={fmtPct(metrics.cagr)} tone={signTone(metrics.cagr)} />
        <Tile label="Sharpe" value={fmtNum(metrics.sharpe)} tone={signTone(metrics.sharpe)} />
        <Tile label="Sortino" value={fmtNum(metrics.sortino)} tone={signTone(metrics.sortino)} />
        <Tile label="Calmar" value={fmtNum(metrics.calmar)} tone={signTone(metrics.calmar)} />
        <Tile
          label="Max drawdown"
          value={fmtPct(metrics.max_drawdown)}
          tone={metrics.max_drawdown ? "loss" : "neutral"}
        />
        <Tile label="DD duration" value={`${metrics.max_drawdown_bars} bars`} />
        <Tile label="Win rate" value={fmtPct(metrics.win_rate)} />
        <Tile label="Profit factor" value={fmtNum(metrics.profit_factor)} />
        <Tile label="Expectancy" value={fmtMoney(metrics.expectancy)} tone={signTone(metrics.expectancy)} />
        <Tile label="Avg win/loss" value={fmtNum(metrics.avg_win_loss)} />
        <Tile label="Trades" value={String(metrics.num_trades)} />
        <Tile label="Exposure" value={fmtPct(metrics.exposure)} />
        <Tile label="SQN" value={fmtNum(metrics.sqn)} />
        <Tile label="Final equity" value={fmtMoney(metrics.final_equity)} />
      </div>
    </div>
  );
}
