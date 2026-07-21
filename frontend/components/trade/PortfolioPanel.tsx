"use client";

// Portfolio panel (doc §24.6): allocation ring, correlation heatmap (>0.70 red),
// net-exposure bars with a visible cap line, contribution table, and plain-sentence
// concentration warnings. Reads the /api/bot/portfolio snapshot.

import type {
  AllocationRow,
  ContributionRow,
  CorrelationMatrix,
  NetExposureRow,
  Portfolio,
} from "@/lib/api";
import { fmtNum } from "@/lib/format";

const RING_COLORS = ["#3fb57f", "#d9a441", "#6aa4e0", "#c77dbb", "#8a8f98", "#4bb2b0"];

function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3 rounded border border-line bg-graphite p-4">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-fog">{title}</h3>
        {hint && <span className="text-xs text-fog-faint">{hint}</span>}
      </div>
      {children}
    </section>
  );
}

// ── Allocation ring — target capital share per live strategy ───────────────────
function AllocationRing({ allocations }: { allocations: AllocationRow[] }) {
  const rows = allocations.filter((a) => a.target_share > 0);
  const total = rows.reduce((s, a) => s + a.target_share, 0);
  if (rows.length === 0 || total <= 0) {
    return <p className="text-sm text-fog-faint">No live allocations yet.</p>;
  }
  const r = 42;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <div className="flex flex-wrap items-center gap-6">
      <svg viewBox="0 0 110 110" className="h-28 w-28 shrink-0 -rotate-90">
        <circle cx="55" cy="55" r={r} fill="none" stroke="#26282d" strokeWidth="12" />
        {rows.map((a, i) => {
          const frac = a.target_share / total;
          const dash = frac * c;
          const seg = (
            <circle
              key={a.strategy_id}
              cx="55"
              cy="55"
              r={r}
              fill="none"
              stroke={RING_COLORS[i % RING_COLORS.length]}
              strokeWidth="12"
              strokeDasharray={`${dash} ${c - dash}`}
              strokeDashoffset={-offset}
            />
          );
          offset += dash;
          return seg;
        })}
      </svg>
      <ul className="flex flex-col gap-1.5 text-sm">
        {rows.map((a, i) => (
          <li key={a.strategy_id} className="flex items-center gap-2">
            <span
              className="h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: RING_COLORS[i % RING_COLORS.length] }}
            />
            <span className="text-fog">{a.name}</span>
            <span className="tabular-nums text-fog-muted">
              {fmtNum(a.target_share * 100, 1)}%
            </span>
            <span className="text-[11px] text-fog-faint">
              (target {fmtNum(a.target * 100, 1)}% of equity)
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Correlation heatmap — live + paper; |ρ| > 0.70 rendered red ────────────────
function corrCell(rho: number): { bg: string; text: string } {
  const mag = Math.min(Math.abs(rho), 1);
  if (mag > 0.7) {
    return { bg: `rgba(229, 72, 77, ${0.25 + mag * 0.55})`, text: "#f4f5f6" };
  }
  return { bg: `rgba(154, 158, 166, ${mag * 0.3})`, text: "#9a9ea6" };
}

function CorrelationHeatmap({ correlation }: { correlation: CorrelationMatrix }) {
  const { labels, matrix } = correlation;
  if (!labels || labels.length === 0) {
    return <p className="text-sm text-fog-faint">Need ≥2 strategies with return history.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="border-separate border-spacing-1 text-[11px]">
        <thead>
          <tr>
            <th />
            {labels.map((l) => (
              <th key={l} className="px-1 pb-1 text-fog-faint font-normal">
                <span className="block max-w-[64px] truncate" title={l}>
                  {l}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, i) => (
            <tr key={labels[i]}>
              <td className="pr-1 text-right text-fog-faint">
                <span className="block max-w-[80px] truncate" title={labels[i]}>
                  {labels[i]}
                </span>
              </td>
              {row.map((v, j) => {
                const { bg, text } = corrCell(v);
                return (
                  <td
                    key={`${i}-${j}`}
                    className="h-8 w-10 rounded text-center tabular-nums"
                    style={{ backgroundColor: bg, color: text }}
                    title={`${labels[i]} · ${labels[j]} = ${fmtNum(v, 2)}`}
                  >
                    {fmtNum(v, 2)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Net exposure bars — per symbol, with the cap line visible ──────────────────
function NetExposureBars({ rows }: { rows: NetExposureRow[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-fog-faint">No open exposure.</p>;
  }
  const cap = rows[0]?.cap_pct ?? 35;
  const scale = Math.max(cap * 1.2, ...rows.map((r) => Math.abs(r.net_pct) * 1.1));
  return (
    <div className="flex flex-col gap-2">
      {rows.map((r) => {
        const width = Math.min(Math.abs(r.net_pct) / scale, 1) * 100;
        const over = Math.abs(r.net_pct) > r.cap_pct;
        const capLeft = Math.min(r.cap_pct / scale, 1) * 100;
        return (
          <div key={r.symbol} className="flex items-center gap-3 text-sm">
            <span className="w-20 shrink-0 font-mono text-fog">{r.symbol}</span>
            <div className="relative h-4 flex-1 rounded bg-void">
              <div
                className={`h-4 rounded ${
                  over ? "bg-loss" : r.side === "long" ? "bg-profit" : "bg-paper"
                }`}
                style={{ width: `${width}%` }}
              />
              {/* Cap line (doc §24.6 — tavan çizgisi görünür) */}
              <div
                className="absolute top-[-2px] h-5 w-px bg-fog"
                style={{ left: `${capLeft}%` }}
                title={`cap ${fmtNum(r.cap_pct, 0)}%`}
              />
            </div>
            <span
              className={`w-24 shrink-0 text-right tabular-nums ${
                over ? "text-loss" : "text-fog-muted"
              }`}
            >
              {r.net_pct >= 0 ? "+" : ""}
              {fmtNum(r.net_pct, 1)}% {r.side}
            </span>
          </div>
        );
      })}
      <p className="text-[11px] text-fog-faint">
        Vertical line = {fmtNum(cap, 0)}% single-symbol cap.
      </p>
    </div>
  );
}

// ── Contribution table ─────────────────────────────────────────────────────────
function ContributionTable({ rows }: { rows: ContributionRow[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-fog-faint">No contributions yet.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[420px] text-left text-sm">
        <thead className="text-[11px] uppercase tracking-wider text-fog-faint">
          <tr>
            <th className="py-1.5 pr-3">Strategy</th>
            <th className="py-1.5 pr-3">Mode</th>
            <th className="py-1.5 pr-3 text-right">Weight</th>
            <th className="py-1.5 pr-3 text-right">Return ctb.</th>
            <th className="py-1.5 pr-3 text-right">Risk ctb.</th>
          </tr>
        </thead>
        <tbody className="text-fog-muted">
          {rows.map((r) => (
            <tr key={r.strategy_id} className="border-t border-line">
              <td className="py-1.5 pr-3 text-fog">{r.name}</td>
              <td className="py-1.5 pr-3 uppercase text-[11px]">{r.mode}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums">
                {fmtNum(r.weight * 100, 1)}%
              </td>
              <td
                className={`py-1.5 pr-3 text-right tabular-nums ${
                  r.return_contribution >= 0 ? "text-profit" : "text-loss"
                }`}
              >
                {fmtNum(r.return_contribution * 100, 3)}%
              </td>
              <td className="py-1.5 pr-3 text-right tabular-nums">
                {fmtNum(r.risk_contribution * 100, 3)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Positions table (netted, one per symbol on the venue) ──────────────────────
function PositionsTable({ portfolio }: { portfolio: Portfolio }) {
  const positions = portfolio.positions ?? [];
  if (positions.length === 0) {
    return <p className="text-sm text-fog-faint">No open positions.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[420px] text-left text-sm">
        <thead className="text-[11px] uppercase tracking-wider text-fog-faint">
          <tr>
            <th className="py-1.5 pr-3">Symbol</th>
            <th className="py-1.5 pr-3">Side</th>
            <th className="py-1.5 pr-3 text-right">Qty</th>
            <th className="py-1.5 pr-3 text-right">Entry</th>
            <th className="py-1.5 pr-3 text-right">Lev</th>
          </tr>
        </thead>
        <tbody className="text-fog-muted">
          {positions.map((p, i) => (
            <tr key={i} className="border-t border-line">
              <td className="py-1.5 pr-3 font-mono text-fog">{p.symbol}</td>
              <td className={`py-1.5 pr-3 uppercase ${p.side === "long" ? "text-profit" : "text-loss"}`}>
                {p.side}
              </td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{fmtNum(p.qty, 4)}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{fmtNum(p.entry_price, 2)}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{fmtNum(p.leverage, 1)}×</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PortfolioPanel({ portfolio }: { portfolio: Portfolio | null }) {
  const warnings = portfolio?.concentration_warnings ?? [];
  const method = portfolio?.method ?? "equal_risk";
  const gate = portfolio?.correlation_gate;
  const gatedCount = gate?.rows.filter((r) => r.gated).length ?? 0;

  return (
    <div className="flex flex-col gap-4">
      {warnings.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {warnings.map((w, i) => (
            <p
              key={i}
              className="rounded border border-loss/50 bg-loss/10 px-3 py-2 text-sm text-loss"
            >
              ⚠ {w}
            </p>
          ))}
        </div>
      )}

      <Section title="Allocation" hint={`method: ${method}`}>
        <AllocationRing allocations={portfolio?.allocations ?? []} />
      </Section>

      <Section
        title="Correlation"
        hint={
          gate
            ? `gate |ρ|>${fmtNum(gate.threshold, 2)}${gatedCount ? ` · ${gatedCount} gated` : ""}`
            : undefined
        }
      >
        <CorrelationHeatmap
          correlation={portfolio?.correlation ?? { labels: [], matrix: [] }}
        />
      </Section>

      <Section title="Net exposure">
        <NetExposureBars rows={portfolio?.net_exposure ?? []} />
      </Section>

      <Section title="Contributions">
        <ContributionTable rows={portfolio?.contributions ?? []} />
      </Section>

      <Section title="Positions" hint={`${portfolio?.positions?.length ?? 0} open`}>
        {portfolio ? <PositionsTable portfolio={portfolio} /> : null}
      </Section>
    </div>
  );
}
