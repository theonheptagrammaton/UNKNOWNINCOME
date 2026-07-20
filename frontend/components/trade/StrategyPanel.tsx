"use client";

import { useState } from "react";

import {
  addVersion,
  diffVersions,
  fetchVersions,
  pauseStrategy,
  promoteStrategy,
  reoptimizeStrategy,
  retireStrategy,
  setStrategyMode,
  simulateDegrade,
  type BotMode,
  type StrategyOut,
  type StrategyVersion,
} from "@/lib/api";
import { fmtNum } from "@/lib/format";

const STATUS_TONE: Record<string, string> = {
  candidate: "border-line text-fog-muted",
  paper: "border-paper/50 text-paper",
  live: "border-live/50 text-live",
  retired: "border-line text-fog-faint line-through",
};

function ModeSwitch({
  mode,
  disabled,
  onSet,
}: {
  mode: BotMode;
  disabled: boolean;
  onSet: (m: BotMode) => void;
}) {
  return (
    <div className="flex overflow-hidden rounded border border-line text-xs">
      {(["off", "paper", "live"] as BotMode[]).map((m) => {
        const active = mode === m;
        const isLive = m === "live";
        return (
          <button
            key={m}
            type="button"
            disabled={disabled || isLive}
            title={isLive ? "Live is disabled until Phase 7 (no live adapter yet)" : undefined}
            onClick={() => onSet(m)}
            className={`px-3 py-1 uppercase tracking-wider transition-colors ${
              active
                ? isLive
                  ? "bg-live text-void"
                  : m === "paper"
                    ? "bg-paper text-void"
                    : "bg-off/40 text-fog"
                : "text-fog-muted hover:text-fog"
            } ${isLive ? "cursor-not-allowed opacity-40" : ""}`}
          >
            {m}
          </button>
        );
      })}
    </div>
  );
}

function StrategyEditor({
  strategy,
  onSaved,
}: {
  strategy: StrategyOut;
  onSaved: () => void;
}) {
  const [versions, setVersions] = useState<StrategyVersion[] | null>(null);
  const [draft, setDraft] = useState("");
  const [diff, setDiff] = useState<Record<string, { from: unknown; to: unknown }> | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const vs = await fetchVersions(strategy.id);
    setVersions(vs);
    if (vs[0]) setDraft(JSON.stringify(vs[0].genome, null, 2));
    if (vs.length >= 2) {
      const d = await diffVersions(strategy.id, vs[1].id, vs[0].id);
      setDiff(d.changes);
    } else {
      setDiff(null);
    }
  };

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const genome = JSON.parse(draft);
      const v = await addVersion(strategy.id, genome);
      setMsg(`Saved version ${v.version} (hot-reloaded)`);
      await load();
      onSaved();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const exportJson = () => {
    const blob = new Blob([draft], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${strategy.name.replace(/\s+/g, "_")}.genome.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const importJson = (file: File) => {
    file.text().then(setDraft);
  };

  return (
    <div className="mt-3 flex flex-col gap-3 border-t border-line pt-3">
      {versions === null ? (
        <button
          type="button"
          onClick={load}
          className="self-start rounded border border-line px-3 py-1.5 text-xs text-fog-muted hover:text-fog"
        >
          Load editor · versions · diff
        </button>
      ) : (
        <>
          <div className="flex items-center justify-between">
            <span className="text-[11px] uppercase tracking-wider text-fog-faint">
              Genome (raw JSON — edit → save = new immutable version)
            </span>
            <div className="flex gap-2">
              <label className="cursor-pointer rounded border border-line px-2 py-1 text-[11px] text-fog-muted hover:text-fog">
                Import
                <input
                  type="file"
                  accept="application/json"
                  className="hidden"
                  onChange={(e) => e.target.files?.[0] && importJson(e.target.files[0])}
                />
              </label>
              <button
                type="button"
                onClick={exportJson}
                className="rounded border border-line px-2 py-1 text-[11px] text-fog-muted hover:text-fog"
              >
                Export
              </button>
            </div>
          </div>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            spellCheck={false}
            rows={12}
            className="w-full rounded border border-line bg-void p-3 font-mono text-xs text-fog outline-none focus:border-fog-faint"
          />
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={save}
              disabled={busy}
              className="rounded bg-fog px-4 py-1.5 text-xs font-semibold text-void hover:bg-fog-muted disabled:opacity-50"
            >
              {busy ? "Saving…" : "Save new version"}
            </button>
            {msg && <span className="text-xs text-fog-muted">{msg}</span>}
          </div>

          <div className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wider text-fog-faint">
              Versions ({versions.length})
            </span>
            <div className="flex flex-wrap gap-1.5">
              {versions.map((v) => (
                <span
                  key={v.id}
                  className="rounded border border-line px-2 py-0.5 font-mono text-[11px] text-fog-muted"
                  title={v.genome_hash}
                >
                  v{v.version}·{v.status}
                </span>
              ))}
            </div>
          </div>

          {diff && (
            <div className="flex flex-col gap-1">
              <span className="text-[11px] uppercase tracking-wider text-fog-faint">
                Diff (prev → latest)
              </span>
              {Object.keys(diff).length === 0 ? (
                <span className="text-xs text-fog-faint">no changes</span>
              ) : (
                <ul className="flex flex-col gap-0.5 font-mono text-[11px] text-fog-muted">
                  {Object.entries(diff).map(([k, c]) => (
                    <li key={k}>
                      <span className="text-fog-faint">{k}</span>: {JSON.stringify(c.from)} →{" "}
                      <span className="text-fog">{JSON.stringify(c.to)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function StrategyCard({ strategy, onChange }: { strategy: StrategyOut; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const h = strategy.health;

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      onChange();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col rounded border border-line bg-void p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-fog">{strategy.name}</span>
            <span
              className={`rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${
                STATUS_TONE[strategy.status ?? "candidate"] ?? "border-line text-fog-muted"
              }`}
            >
              {strategy.status ?? "—"}
            </span>
            <span className="text-[11px] text-fog-faint">v{strategy.active_version ?? "—"}</span>
            {strategy.regime && (
              <span
                className="rounded border border-line px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-fog-muted"
                title="Suited market regime (doc §8.4)"
              >
                {strategy.regime}
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-fog-faint">
            <span>trades: {h.num_trades}</span>
            <span>rolling PF: {fmtNum(h.rolling_pf, 2)}</span>
            <span>last pnl: {fmtNum(h.last_pnl, 2)}</span>
            <span>open: {h.open_positions}</span>
          </div>
        </div>
        <ModeSwitch
          mode={strategy.mode}
          disabled={busy}
          onSet={(m) => act(() => setStrategyMode(strategy.id, m))}
        />
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy || strategy.status === "live" || strategy.status === "retired"}
          onClick={() => act(() => promoteStrategy(strategy.id))}
          className="rounded border border-line px-2.5 py-1 text-[11px] text-fog-muted hover:text-fog disabled:opacity-40"
        >
          Promote
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => act(() => pauseStrategy(strategy.id))}
          className="rounded border border-line px-2.5 py-1 text-[11px] text-fog-muted hover:text-fog disabled:opacity-40"
        >
          Pause
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => act(() => retireStrategy(strategy.id))}
          className="rounded border border-line px-2.5 py-1 text-[11px] text-fog-muted hover:text-fog disabled:opacity-40"
        >
          Retire
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => act(() => reoptimizeStrategy(strategy.id))}
          title="WFO re-optimize on the latest data → a pending-approval version (doc §8.3)"
          className="rounded border border-line px-2.5 py-1 text-[11px] text-fog-muted hover:text-fog disabled:opacity-40"
        >
          Re-optimize
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => act(() => simulateDegrade(strategy.id))}
          title="Simulate degradation (doc §8.5): pause + generate a proposal (dev only)"
          className="rounded border border-line px-2.5 py-1 text-[11px] text-fog-faint hover:text-loss disabled:opacity-40"
        >
          Simulate degrade
        </button>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="rounded border border-line px-2.5 py-1 text-[11px] text-fog-muted hover:text-fog"
        >
          {open ? "Close editor" : "Edit genome"}
        </button>
      </div>

      {open && <StrategyEditor strategy={strategy} onSaved={onChange} />}
    </div>
  );
}

export function StrategyPanel({
  strategies,
  onChange,
}: {
  strategies: StrategyOut[];
  onChange: () => void;
}) {
  return (
    <section className="flex flex-col gap-3 rounded border border-line bg-graphite p-4">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-fog">Strategies</h3>
        <span className="text-xs text-fog-faint">
          {strategies.length} · convert from Discovery leaderboard
        </span>
      </div>
      {strategies.length === 0 ? (
        <p className="text-sm text-fog-faint">
          No strategies yet. Use “Convert to strategy” on the Discovery leaderboard.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {strategies.map((s) => (
            <StrategyCard key={s.id} strategy={s} onChange={onChange} />
          ))}
        </div>
      )}
    </section>
  );
}
