"use client";

import { useCallback, useEffect, useState } from "react";

import {
  approveVersion,
  fetchPending,
  rejectVersion,
  type PendingVersion,
} from "@/lib/api";
import { fmtNum } from "@/lib/format";

// Pull a nested number out of the WFO report for the summary line.
function reportNum(report: Record<string, unknown> | null, path: string[]): number | null {
  let cur: unknown = report;
  for (const key of path) {
    if (cur && typeof cur === "object" && key in (cur as Record<string, unknown>)) {
      cur = (cur as Record<string, unknown>)[key];
    } else {
      return null;
    }
  }
  return typeof cur === "number" ? cur : null;
}

function PendingCard({
  pending,
  onChange,
}: {
  pending: PendingVersion;
  onChange: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const v = pending.version;
  const report = v.wfo_report;
  const survived = reportNum(report, ["survived"]) ?? report?.survived;
  const oos = reportNum(report, ["oos_score"]);
  const p95 = reportNum(report, ["monte_carlo", "p95_max_drawdown"]);
  const reason = (v.source?.reason as string) ?? "reopt";

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      onChange();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const diffEntries = Object.entries(pending.diff);

  return (
    <div className="flex flex-col gap-2 rounded border border-paper/40 bg-void p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-col gap-0.5">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-fog">{pending.strategy_name}</span>
            <span className="rounded border border-paper/50 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-paper">
              pending approval
            </span>
          </div>
          <span className="text-[11px] text-fog-faint">
            v{pending.active_version ?? "—"} → v{v.version} · {reason}
            {v.regime ? ` · regime ${v.regime}` : ""}
          </span>
        </div>
        <span
          className={`rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${
            survived
              ? "border-profit/50 text-profit"
              : "border-loss/50 text-loss"
          }`}
        >
          {survived ? "survived §6.5" : "did not survive §6.5"}
        </span>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-fog-faint">
        <span>OOS score: {fmtNum(oos, 3)}</span>
        <span>MC 95% maxDD: {p95 == null ? "—" : `${fmtNum(p95 * 100, 1)}%`}</span>
      </div>

      {diffEntries.length > 0 && (
        <div className="flex flex-col gap-0.5">
          <span className="text-[11px] uppercase tracking-wider text-fog-faint">
            Parameter changes
          </span>
          <ul className="flex flex-col gap-0.5 font-mono text-[11px] text-fog-muted">
            {diffEntries.slice(0, 8).map(([k, c]) => (
              <li key={k}>
                <span className="text-fog-faint">{k}</span>: {JSON.stringify(c.from)} →{" "}
                <span className="text-fog">{JSON.stringify(c.to)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-1 flex items-center gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => act(() => approveVersion(pending.strategy_id, v.id))}
          className="rounded bg-paper px-3 py-1 text-xs font-semibold uppercase tracking-wider text-void hover:opacity-90 disabled:opacity-50"
        >
          Approve → paper
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => act(() => rejectVersion(pending.strategy_id, v.id))}
          className="rounded border border-line px-3 py-1 text-xs uppercase tracking-wider text-fog-muted hover:text-fog disabled:opacity-50"
        >
          Reject
        </button>
        {err && <span className="text-[11px] text-loss">{err}</span>}
      </div>
    </div>
  );
}

export function ApprovalPanel({ onChange }: { onChange: () => void }) {
  const [pending, setPending] = useState<PendingVersion[]>([]);

  const refresh = useCallback(async () => {
    try {
      setPending(await fetchPending());
    } catch {
      /* transient; the outer deck surfaces errors */
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 4000);
    return () => clearInterval(id);
  }, [refresh]);

  const handleChange = () => {
    refresh();
    onChange();
  };

  if (pending.length === 0) return null; // quiet until there is something to approve

  return (
    <section className="flex flex-col gap-3 rounded border border-paper/40 bg-graphite p-4">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-paper">
          Approval queue
        </h3>
        <span className="text-xs text-fog-faint">
          {pending.length} self-generated version{pending.length === 1 ? "" : "s"} · doc §8.5
        </span>
      </div>
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        {pending.map((p) => (
          <PendingCard key={p.version.id} pending={p} onChange={handleChange} />
        ))}
      </div>
    </section>
  );
}
