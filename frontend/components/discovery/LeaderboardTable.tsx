"use client";

import { Fragment, useState } from "react";
import Link from "next/link";

import { convertToStrategy, type LeaderboardEntry } from "@/lib/api";
import { fmtDate, fmtNum, fmtPct } from "@/lib/format";

type SortKey =
  | "rank"
  | "oos_score"
  | "net_return"
  | "sharpe"
  | "max_drawdown"
  | "profit_factor"
  | "win_rate"
  | "num_trades";

const COLUMNS: { key: SortKey; label: string; align: "left" | "right" }[] = [
  { key: "rank", label: "#", align: "left" },
  { key: "oos_score", label: "OOS", align: "right" },
  { key: "net_return", label: "Net", align: "right" },
  { key: "sharpe", label: "Sharpe", align: "right" },
  { key: "max_drawdown", label: "MaxDD", align: "right" },
  { key: "profit_factor", label: "PF", align: "right" },
  { key: "win_rate", label: "Win", align: "right" },
  { key: "num_trades", label: "Trades", align: "right" },
];

function metricValue(e: LeaderboardEntry, key: SortKey): number {
  if (key === "rank") return e.rank ?? 0;
  if (key === "oos_score") return e.oos_score ?? -Infinity;
  const m = e.metrics;
  if (!m) return -Infinity;
  const v = m[key as keyof typeof m];
  return typeof v === "number" ? v : -Infinity;
}

export function LeaderboardTable({
  entries,
  scanId,
}: {
  entries: LeaderboardEntry[];
  scanId?: string;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("rank");
  const [asc, setAsc] = useState(true);
  const [open, setOpen] = useState<number | null>(null);

  const sorted = [...entries].sort((a, b) => {
    const d = metricValue(a, sortKey) - metricValue(b, sortKey);
    return asc ? d : -d;
  });

  const onSort = (key: SortKey) => {
    if (key === sortKey) setAsc((v) => !v);
    else {
      setSortKey(key);
      setAsc(key === "rank"); // ranks read best ascending; metrics best descending
    }
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] text-left text-sm">
        <thead className="text-[11px] uppercase tracking-wider text-fog-faint">
          <tr>
            <th className="py-2 pr-3">Combo (trigger + filter + exit)</th>
            <th className="py-2 pr-3">TF</th>
            {COLUMNS.map((c) => (
              <th
                key={c.key}
                onClick={() => onSort(c.key)}
                className={`cursor-pointer select-none py-2 pr-3 hover:text-fog ${
                  c.align === "right" ? "text-right" : ""
                } ${sortKey === c.key ? "text-fog" : ""}`}
              >
                {c.label}
                {sortKey === c.key ? (asc ? " ▲" : " ▼") : ""}
              </th>
            ))}
            <th className="py-2 pr-3">Status</th>
            <th className="py-2 pr-3 text-right">⚠</th>
          </tr>
        </thead>
        <tbody className="text-fog-muted">
          {sorted.map((e) => {
            const key = `${e.combo.trigger}+${e.combo.filter}+${e.combo.exit}@${e.symbol}:${e.tf}`;
            const isOpen = open === e.rank;
            const candidate = e.status === "candidate";
            return (
              <Fragment key={key}>
                <tr
                  onClick={() => setOpen(isOpen ? null : (e.rank ?? null))}
                  className="cursor-pointer border-t border-line hover:bg-graphite"
                >
                  <td className="py-2 pr-3">
                    <span className="font-mono text-xs text-fog">
                      {e.combo.trigger} + {e.combo.filter} + {e.combo.exit}
                    </span>
                    <span className="ml-2 text-[11px] text-fog-faint">{e.symbol}</span>
                  </td>
                  <td className="py-2 pr-3">{e.tf}</td>
                  <td className="py-2 pr-3">{e.rank}</td>
                  <td className="py-2 pr-3 text-right">{fmtNum(e.oos_score, 3)}</td>
                  <td
                    className={`py-2 pr-3 text-right ${
                      (e.metrics?.net_return ?? 0) >= 0 ? "text-profit" : "text-loss"
                    }`}
                  >
                    {fmtPct(e.metrics?.net_return)}
                  </td>
                  <td className="py-2 pr-3 text-right">{fmtNum(e.metrics?.sharpe, 2)}</td>
                  <td className="py-2 pr-3 text-right">{fmtPct(e.metrics?.max_drawdown)}</td>
                  <td className="py-2 pr-3 text-right">{fmtNum(e.metrics?.profit_factor, 2)}</td>
                  <td className="py-2 pr-3 text-right">{fmtPct(e.metrics?.win_rate)}</td>
                  <td className="py-2 pr-3 text-right">{e.metrics?.num_trades ?? "—"}</td>
                  <td className="py-2 pr-3">
                    <span className={candidate ? "text-profit" : "text-fog-faint"}>
                      {e.status}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-right">
                    {e.alarms.length > 0 ? (
                      <span className="text-loss">{e.alarms.length}</span>
                    ) : (
                      <span className="text-fog-faint">—</span>
                    )}
                  </td>
                </tr>
                {isOpen && (
                  <tr className="border-t border-line bg-void">
                    <td colSpan={COLUMNS.length + 4} className="p-4">
                      <EntryDetail entry={e} scanId={scanId} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ConvertButton({ scanId, rank }: { scanId?: string; rank?: number }) {
  const [state, setState] = useState<"idle" | "busy" | "done" | "error">("idle");
  const [msg, setMsg] = useState<string | null>(null);

  if (!scanId || rank === undefined) {
    return (
      <button
        type="button"
        disabled
        title="Open this scan's leaderboard to convert an entry"
        className="cursor-not-allowed rounded border border-line px-4 py-2 text-xs text-fog-faint opacity-60"
      >
        Convert to strategy →
      </button>
    );
  }

  const convert = async () => {
    setState("busy");
    setMsg(null);
    try {
      const s = await convertToStrategy({ scan_id: scanId, rank });
      setState("done");
      setMsg(`Created “${s.name}” as a candidate.`);
    } catch (e) {
      setState("error");
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        onClick={convert}
        disabled={state === "busy" || state === "done"}
        className="rounded bg-fog px-4 py-2 text-xs font-semibold text-void transition-colors hover:bg-fog-muted disabled:opacity-50"
      >
        {state === "busy" ? "Converting…" : state === "done" ? "Converted ✓" : "Convert to strategy →"}
      </button>
      {msg && <span className="text-xs text-fog-muted">{msg}</span>}
      {state === "done" && (
        <Link href="/trade" className="text-xs text-paper underline hover:text-fog">
          Open Trade Deck
        </Link>
      )}
    </div>
  );
}

function EntryDetail({ entry, scanId }: { entry: LeaderboardEntry; scanId?: string }) {
  const g = entry.genome;
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 md:grid-cols-3">
        {/* Genome */}
        <div className="flex flex-col gap-1">
          <span className="text-[11px] uppercase tracking-wider text-fog-faint">Genome</span>
          <div className="rounded border border-line bg-graphite p-3 text-xs text-fog-muted">
            <div className="font-mono text-fog">
              {g.indicators.map((i) => `${i.key}=${i.id}`).join("  ")}
            </div>
            <div className="mt-1">
              risk exit: ATR stop ×{g.risk_exit?.atr_stop_mult ?? "—"} · target ×
              {g.risk_exit?.atr_target_mult ?? "—"}
            </div>
            <div>
              direction: {g.direction} · leverage: {g.capital.leverage}× · seed: {g.seed}
            </div>
          </div>
        </div>

        {/* Robustness */}
        <div className="flex flex-col gap-1">
          <span className="text-[11px] uppercase tracking-wider text-fog-faint">
            Robustness (§6.5)
          </span>
          <div className="rounded border border-line bg-graphite p-3 text-xs text-fog-muted">
            <div>
              plateau:{" "}
              <span className={entry.plateau_ok ? "text-profit" : "text-loss"}>
                {entry.plateau_ok ? "ok" : "failed"}
              </span>
            </div>
            <div>
              MC 95% worst drawdown: {fmtPct(entry.monte_carlo.p95_max_drawdown)} ·{" "}
              {entry.monte_carlo.runs} runs
            </div>
            <div>
              IS score: {fmtNum(entry.is_score, 3)} · OOS score: {fmtNum(entry.oos_score, 3)}
            </div>
          </div>
        </div>

        {/* Finalist cross-check */}
        <div className="flex flex-col gap-1">
          <span className="text-[11px] uppercase tracking-wider text-fog-faint">
            Finalist cross-check (§6.1)
          </span>
          <div className="rounded border border-line bg-graphite p-3 text-xs text-fog-muted">
            {entry.finalist ? (
              <div>
                engine: {entry.finalist.engine} · net {fmtPct(entry.finalist.net_return)} ·
                sharpe {fmtNum(entry.finalist.sharpe, 2)}
              </div>
            ) : (
              <div>not cross-validated (outside top-K)</div>
            )}
            {entry.alarms.length === 0 ? (
              <div className="mt-1 text-profit">engines agree</div>
            ) : (
              entry.alarms.map((a, i) => (
                <div key={i} className="mt-1 text-loss">
                  ⚠ {a.metric}: primary {fmtNum(a.primary, 3)} vs {fmtNum(a.finalist, 3)} (rel{" "}
                  {fmtNum(a.rel_diff, 2)} &gt; {fmtNum(a.tolerance, 2)})
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Walk-forward layers */}
      {entry.wfo_layers.length > 0 && (
        <div className="flex flex-col gap-1">
          <span className="text-[11px] uppercase tracking-wider text-fog-faint">
            Walk-forward layers ({entry.wfo_layers.length})
          </span>
          <div className="overflow-x-auto">
            <table className="min-w-[520px] text-left text-xs text-fog-muted">
              <thead className="text-fog-faint">
                <tr>
                  <th className="py-1 pr-4">Test window</th>
                  <th className="py-1 pr-4 text-right">OOS score</th>
                  <th className="py-1 pr-4 text-right">Net</th>
                  <th className="py-1 pr-4 text-right">Trades</th>
                </tr>
              </thead>
              <tbody>
                {entry.wfo_layers.map((l, i) => (
                  <tr key={i}>
                    <td className="py-1 pr-4">
                      {fmtDate(l.test_start)} → {fmtDate(l.test_end)}
                    </td>
                    <td className="py-1 pr-4 text-right">{fmtNum(l.composite_score, 3)}</td>
                    <td className="py-1 pr-4 text-right">{fmtPct(l.net_return)}</td>
                    <td className="py-1 pr-4 text-right">{l.num_trades}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <ConvertButton scanId={scanId} rank={entry.rank} />
    </div>
  );
}
