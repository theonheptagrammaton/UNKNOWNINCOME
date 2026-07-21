"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  clearKill,
  engageKill,
  fetchBotStatus,
  fetchDecisions,
  fetchGate,
  fetchPortfolio,
  fetchSignals,
  fetchStrategies,
  setBotMode,
  type BotMode,
  type BotStatus,
  type DecisionRow,
  type GateStatus,
  type Portfolio,
  type SignalRow,
  type StrategyOut,
} from "@/lib/api";
import { fmtDateTime, fmtMoney, fmtNum } from "@/lib/format";

import { ApprovalPanel } from "./ApprovalPanel";
import { GatePanel } from "./GatePanel";
import { StrategyPanel } from "./StrategyPanel";
import { SettingsPanel } from "./SettingsPanel";
import { TrackingPanel } from "./TrackingPanel";

const POLL_MS = 2000;

const MODE_TONE: Record<BotMode, string> = {
  live: "text-live",
  paper: "text-paper",
  off: "text-off",
};

function Panel({
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

// ── Status strip (doc §10.2) ──────────────────────────────────────────────────
function StatusStrip({
  status,
  onMode,
  onKill,
  onClearKill,
  busy,
  gate,
}: {
  status: BotStatus | null;
  onMode: (m: BotMode) => void;
  onKill: () => void;
  onClearKill: () => void;
  busy: boolean;
  gate: GateStatus | null;
}) {
  const [confirmKill, setConfirmKill] = useState(false);
  const mode = status?.global_mode ?? "off";
  const pnl = status?.daily_pnl ?? null;
  const pnlTone = pnl == null ? "text-fog-muted" : pnl >= 0 ? "text-profit" : "text-loss";

  // LIVE is refused at every layer (doc §9.5). This is the UI layer: the button is
  // disabled while the promotion gate is closed, and the tooltip names the reason
  // rather than making the user click into a server-side rejection. The API and the
  // bot engine enforce the same gate independently — this is convenience, not the lock.
  const liveBlocked = gate ? !gate.passed : true;
  const liveReason = !gate
    ? "Checking promotion gate…"
    : gate.passed
      ? undefined
      : `Promotion gate closed (doc §9.5): ${gate.failures.join("; ")}`;

  return (
    <section className="flex flex-col gap-4 rounded border border-line bg-graphite p-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        {/* Global mode switch — impossible-to-miss (doc §10.2) */}
        <div className="flex items-center gap-3">
          <span className="text-[11px] uppercase tracking-wider text-fog-faint">Global mode</span>
          <div className="flex overflow-hidden rounded border border-line">
            {(["off", "paper", "live"] as BotMode[]).map((m) => {
              const active = mode === m;
              const disabled = m === "live" && (!(status?.live_enabled ?? false) || liveBlocked);
              return (
                <button
                  key={m}
                  type="button"
                  disabled={disabled || busy}
                  title={
                    m === "live"
                      ? !(status?.live_enabled ?? false)
                        ? "Live execution is off in config (LIVE_TRADING_ENABLED=false)"
                        : liveReason
                      : undefined
                  }
                  onClick={() => onMode(m)}
                  className={`px-5 py-2 text-sm font-semibold uppercase tracking-wider transition-colors ${
                    active
                      ? m === "live"
                        ? "bg-live text-void"
                        : m === "paper"
                          ? "bg-paper text-void"
                          : "bg-off/40 text-fog"
                      : "text-fog-muted hover:text-fog"
                  } ${disabled ? "cursor-not-allowed opacity-40" : ""}`}
                >
                  {m}
                </button>
              );
            })}
          </div>
        </div>

        {/* Kill switch (channel 1 of 4, doc §9.4) */}
        {status?.killswitch ? (
          <div className="flex items-center gap-3">
            <span className="animate-pulse rounded border border-loss/60 bg-loss/15 px-3 py-1.5 text-sm font-bold uppercase tracking-wider text-loss">
              ⛔ Kill switch engaged
            </span>
            <button
              type="button"
              onClick={onClearKill}
              disabled={busy}
              className="rounded border border-line px-3 py-1.5 text-xs text-fog-muted hover:text-fog"
            >
              Clear
            </button>
          </div>
        ) : confirmKill ? (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                onKill();
                setConfirmKill(false);
              }}
              className="rounded bg-loss px-4 py-2 text-sm font-bold uppercase tracking-wider text-void"
            >
              Confirm kill
            </button>
            <button
              type="button"
              onClick={() => setConfirmKill(false)}
              className="rounded border border-line px-3 py-2 text-xs text-fog-muted hover:text-fog"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setConfirmKill(true)}
            className="rounded border border-loss/50 px-5 py-2 text-sm font-bold uppercase tracking-wider text-loss transition-colors hover:bg-loss/10"
          >
            Kill switch
          </button>
        )}
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Metric label="Effective mode" value={mode.toUpperCase()} tone={MODE_TONE[mode]} />
        <Metric label="Equity" value={fmtMoney(status?.equity ?? null)} />
        <Metric
          label="Daily PnL"
          value={pnl == null ? "—" : `${pnl >= 0 ? "+" : ""}${fmtMoney(pnl)}`}
          tone={pnlTone}
        />
        <Metric label="Regime" value={status?.regime ?? "—"} />
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-fog-faint">
        <span>open positions: {status?.open_positions ?? 0}</span>
        <span>exposure: {fmtMoney(status?.exposure ?? 0)}</span>
        <span>
          live path:{" "}
          {!(status?.live_enabled ?? false)
            ? "off in config"
            : gate?.passed
              ? "gate open"
              : "gate closed"}
        </span>
      </div>
    </section>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] uppercase tracking-wider text-fog-faint">{label}</span>
      <span className={`text-lg font-semibold tabular-nums ${tone ?? "text-fog"}`}>{value}</span>
    </div>
  );
}

// ── Portfolio ─────────────────────────────────────────────────────────────────
function PortfolioPanel({ portfolio }: { portfolio: Portfolio | null }) {
  const positions = portfolio?.positions ?? [];
  return (
    <Panel title="Portfolio" hint={`${positions.length} open`}>
      {positions.length === 0 ? (
        <p className="text-sm text-fog-faint">No open positions.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-left text-sm">
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
                  <td
                    className={`py-1.5 pr-3 uppercase ${
                      p.side === "long" ? "text-profit" : "text-loss"
                    }`}
                  >
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
      )}
    </Panel>
  );
}

// ── Signal feed (reason + indicator snapshot, doc §10.2) ─────────────────────
function actionTone(action: string): string {
  if (action.includes("long")) return "text-profit";
  if (action.includes("short")) return "text-loss";
  return "text-fog";
}

function SignalFeed({ signals }: { signals: SignalRow[] }) {
  return (
    <Panel title="Signal feed" hint={`${signals.length} recent`}>
      {signals.length === 0 ? (
        <p className="text-sm text-fog-faint">No signals yet.</p>
      ) : (
        <ul className="flex flex-col divide-y divide-line">
          {signals.map((s) => (
            <li key={s.id} className="flex flex-col gap-1 py-2.5">
              <div className="flex items-center justify-between gap-2 text-sm">
                <span className="flex items-center gap-2">
                  <span className={`font-semibold uppercase ${actionTone(s.action)}`}>
                    {s.action.replace("_", " ")}
                  </span>
                  <span className="font-mono text-fog">{s.symbol}</span>
                  <span className="text-fog-faint">{s.tf}</span>
                </span>
                <span
                  className={`text-[11px] uppercase tracking-wider ${
                    s.outcome === "filled" ? "text-profit" : "text-loss"
                  }`}
                >
                  {s.outcome}
                </span>
              </div>
              <div className="flex flex-wrap gap-1 text-[11px] text-fog-muted">
                {Object.entries(s.reason).flatMap(([group, clauses]) =>
                  clauses.map((c, i) => (
                    <span
                      key={`${group}-${i}`}
                      className="rounded border border-line px-1.5 py-0.5 font-mono"
                    >
                      {group}: {c.primitive}
                    </span>
                  )),
                )}
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-fog-faint">
                {Object.entries(s.indicator_snapshot).map(([k, v]) => (
                  <span key={k} className="tabular-nums">
                    {k}={v == null ? "—" : fmtNum(v, 3)}
                  </span>
                ))}
                <span>{fmtDateTime(s.ts)}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

// ── Decision log (accepted + risk-rejected, doc §10.2) ───────────────────────
function DecisionLog({ decisions }: { decisions: DecisionRow[] }) {
  return (
    <Panel title="Decision log" hint={`${decisions.length} entries`}>
      {decisions.length === 0 ? (
        <p className="text-sm text-fog-faint">No decisions recorded yet.</p>
      ) : (
        <ul className="flex flex-col divide-y divide-line text-sm">
          {decisions.map((d, i) => (
            <li key={i} className="flex items-center justify-between gap-3 py-2">
              {d.kind === "signal" ? (
                <>
                  <span className="flex items-center gap-2">
                    <span className={`font-semibold ${actionTone(String(d.action))}`}>
                      {String(d.action).replace("_", " ")}
                    </span>
                    <span className="font-mono text-fog-muted">{String(d.symbol)}</span>
                  </span>
                  <span
                    className={`text-[11px] uppercase tracking-wider ${
                      d.outcome === "filled" ? "text-profit" : "text-loss"
                    }`}
                  >
                    {String(d.outcome)}
                  </span>
                </>
              ) : (
                <>
                  <span className="flex items-center gap-2">
                    <span className="rounded border border-loss/50 px-1.5 py-0.5 text-[11px] uppercase tracking-wider text-loss">
                      risk
                    </span>
                    <span className="text-fog-muted">{String(d.type)}</span>
                    {d.symbol && <span className="font-mono text-fog-faint">{String(d.symbol)}</span>}
                  </span>
                  <span className="text-[11px] text-fog-faint">{fmtDateTime(d.ts)}</span>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

// ── Trade Deck (page 2, doc §10.2) ───────────────────────────────────────────
export function TradeDeck() {
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [signals, setSignals] = useState<SignalRow[]>([]);
  const [decisions, setDecisions] = useState<DecisionRow[]>([]);
  const [strategies, setStrategies] = useState<StrategyOut[]>([]);
  const [gate, setGate] = useState<GateStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const [st, pf, sg, dc, str, gt] = await Promise.all([
        fetchBotStatus(),
        fetchPortfolio(),
        fetchSignals(),
        fetchDecisions(),
        fetchStrategies(),
        fetchGate("global"),
      ]);
      if (!mounted.current) return;
      setStatus(st);
      setPortfolio(pf);
      setSignals(sg.signals);
      setDecisions(dc.decisions);
      setStrategies(str);
      setGate(gt);
      setError(null);
    } catch (e) {
      if (mounted.current) setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => {
      mounted.current = false;
      clearInterval(id);
    };
  }, [refresh]);

  const guard = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-baseline justify-between">
        <span className="text-xs uppercase tracking-[0.3em] text-fog-faint">Page 2</span>
        <span className="text-xs text-fog-faint">Paper trading · UTC internally</span>
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">Trade Deck</h1>

      {error && (
        <p className="rounded border border-loss/50 bg-loss/10 px-3 py-2 text-sm text-loss">
          {error}
        </p>
      )}

      <StatusStrip
        status={status}
        gate={gate}
        busy={busy}
        onMode={(m) => guard(() => setBotMode(m))}
        onKill={() => guard(() => engageKill("ui"))}
        onClearKill={() => guard(() => clearKill())}
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <GatePanel gate={gate} />
        <TrackingPanel />
      </div>

      <ApprovalPanel onChange={refresh} />

      <StrategyPanel strategies={strategies} signals={signals} onChange={refresh} />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <PortfolioPanel portfolio={portfolio} />
        <SignalFeed signals={signals} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <DecisionLog decisions={decisions} />
        <SettingsPanel />
      </div>
    </div>
  );
}
