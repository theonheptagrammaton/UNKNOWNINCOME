"use client";

import { useEffect, useState } from "react";

import { fetchGate, type GateStatus } from "@/lib/api";

// Paper → Live promotion gate (doc §9.5), rendered as a readiness board.
//
// This panel is *informational*: the API refuses a LIVE switch on its own and the
// bot engine refuses to build a live wall on its own. Showing the verdict here is
// the UI layer of "her katmanda reddedilir" — the LIVE button in the status strip
// reads the same verdict and stays disabled while the gate is closed, so a user
// never gets to click a button that the server would only reject.

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2);
  return String(v);
}

export function GatePanel({ gate }: { gate?: GateStatus | null }) {
  const [own, setOwn] = useState<GateStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // When the parent already polls the gate, use its copy; otherwise self-load.
  useEffect(() => {
    if (gate !== undefined) return;
    fetchGate("global")
      .then(setOwn)
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, [gate]);

  const g = gate ?? own;
  const metrics = g?.metrics ?? {};
  const strategies = metrics.strategies ?? [];

  return (
    <section className="flex flex-col gap-3 rounded border border-line bg-graphite p-4">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-fog">
          Live readiness
        </h3>
        <span className="text-xs text-fog-faint">promotion gate · doc §9.5</span>
      </div>

      {!g ? (
        <p className="text-sm text-fog-faint">{err ?? "Loading…"}</p>
      ) : (
        <>
          <div className="flex items-center gap-3">
            <span
              className={`rounded px-3 py-1 text-xs font-bold uppercase tracking-wider ${
                g.passed ? "bg-live/20 text-live" : "bg-loss/15 text-loss"
              }`}
            >
              {g.passed ? "Gate open" : "Gate closed"}
            </span>
            <span className="text-xs text-fog-faint">
              infra {metrics.infra_ready ? "ready" : "not ready"}
            </span>
          </div>

          {!g.passed && g.failures.length > 0 && (
            <ul className="flex flex-col gap-1 border-l-2 border-loss/40 pl-3">
              {g.failures.map((f) => (
                <li key={f} className="text-xs text-fog-muted">
                  {f}
                </li>
              ))}
            </ul>
          )}

          {strategies.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] text-left text-sm">
                <thead className="text-[11px] uppercase tracking-wider text-fog-faint">
                  <tr>
                    <th className="py-1 pr-3 font-normal">Strategy</th>
                    <th className="py-1 pr-3 font-normal">Trades</th>
                    <th className="py-1 pr-3 font-normal">Days</th>
                    <th className="py-1 pr-3 font-normal">PF</th>
                    <th className="py-1 pr-3 font-normal">MaxDD %</th>
                    <th className="py-1 font-normal">Gate</th>
                  </tr>
                </thead>
                <tbody className="tabular-nums">
                  {strategies.map((s) => {
                    const m = s.metrics as Record<string, unknown>;
                    return (
                      <tr key={s.strategy_id} className="border-t border-line/60">
                        <td className="py-1 pr-3 text-fog">{s.strategy_id}</td>
                        <td className="py-1 pr-3 text-fog-muted">{fmt(m.num_trades)}</td>
                        <td className="py-1 pr-3 text-fog-muted">{fmt(m.days)}</td>
                        <td className="py-1 pr-3 text-fog-muted">{fmt(m.profit_factor)}</td>
                        <td className="py-1 pr-3 text-fog-muted">{fmt(m.max_drawdown_pct)}</td>
                        <td className={`py-1 ${s.passed ? "text-live" : "text-loss"}`}>
                          {s.passed ? "open" : "closed"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
