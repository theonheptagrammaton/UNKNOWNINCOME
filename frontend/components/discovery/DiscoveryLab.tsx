"use client";

import { useEffect, useRef, useState } from "react";

import {
  fetchDataStatus,
  fetchLeaderboard,
  fetchScan,
  postScan,
  type Direction,
  type LeaderboardEntry,
  type LeaderboardRow,
  type ScanConfigInput,
} from "@/lib/api";
import { fmtNum, fmtPct } from "@/lib/format";

import { LeaderboardTable } from "./LeaderboardTable";

const TFS = ["1m", "5m", "15m", "1h", "4h", "1d"];
const POLL_MS = 1000;
const MAX_POLLS = 3600; // generous ceiling for a long scan

const inputCls =
  "rounded border border-line bg-void px-3 py-2 text-sm text-fog outline-none focus:border-fog-faint";
const labelCls = "text-[11px] uppercase tracking-wider text-fog-faint";

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className={labelCls}>{label}</span>
      {children}
    </label>
  );
}

function defaultScanConfig(): ScanConfigInput {
  return {
    market: "binance_usdm",
    symbols: [],
    universe_as_of: null,
    timeframes: ["1h"],
    direction: "both",
    top_n_combos: 50,
    optuna_trials: 30,
    fast_mode: true,
    seed: 42,
  };
}

const STAGE_LABELS: Record<string, string> = {
  stage0_universe: "Resolving universe",
  stage1_single_scan: "Stage 1 · Single scan",
  stage2_correlation: "Stage 2 · Correlation elimination",
  stage3_combination: "Stage 3 · Role-based combination",
  stage4_5_optimize_wfo: "Stage 4–5 · Optuna + walk-forward",
  stage6_finalist: "Stage 6 · Leaderboard + finalist check",
  done: "Complete",
};

export function DiscoveryLab() {
  const [config, setConfig] = useState<ScanConfigInput>(() => defaultScanConfig());
  const [symbolsText, setSymbolsText] = useState("");
  const [knownSymbols, setKnownSymbols] = useState<string[]>([]);

  const [running, setRunning] = useState(false);
  const [stage, setStage] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [combosTried, setCombosTried] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const [entries, setEntries] = useState<LeaderboardEntry[] | null>(null);
  const [scanId, setScanId] = useState<string | null>(null);
  const [history, setHistory] = useState<LeaderboardRow[]>([]);
  const [scanMeta, setScanMeta] = useState<{
    candidates: number;
    alarms: number;
    universe: string[];
    timings: Record<string, number>;
  } | null>(null);
  const cancelled = useRef(false);

  useEffect(() => {
    cancelled.current = false;
    fetchDataStatus()
      .then((rows) => setKnownSymbols([...new Set(rows.map((r) => r.symbol))].sort()))
      .catch(() => setKnownSymbols([]));
    fetchLeaderboard()
      .then((r) => setHistory(r.rows))
      .catch(() => setHistory([]));
    return () => {
      cancelled.current = true;
    };
  }, []);

  const patch = (p: Partial<ScanConfigInput>) => setConfig((c) => ({ ...c, ...p }));

  const toggleTf = (tf: string) => {
    const has = config.timeframes.includes(tf);
    patch({
      timeframes: has
        ? config.timeframes.filter((t) => t !== tf)
        : [...config.timeframes, tf],
    });
  };

  const onRun = async () => {
    const symbols = symbolsText
      .split(/[\s,]+/)
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean);
    setRunning(true);
    setError(null);
    setEntries(null);
    setScanMeta(null);
    setStage("queued");
    setProgress(0);
    setCombosTried(0);

    try {
      const payload: ScanConfigInput = {
        ...config,
        symbols: symbols.length > 0 ? symbols : null,
      };
      const { scan_id } = await postScan(payload);
      setScanId(scan_id);
      for (let i = 0; i < MAX_POLLS; i++) {
        if (cancelled.current) return;
        await new Promise((r) => setTimeout(r, POLL_MS));
        const scan = await fetchScan(scan_id);
        setStage(scan.stage);
        setProgress(scan.progress);
        setCombosTried(scan.combos_tried);
        if (scan.status === "done") {
          const full = await fetchScan(scan_id, true);
          setEntries(full.detail?.leaderboard ?? []);
          setScanMeta({
            candidates: full.detail?.num_candidates ?? 0,
            alarms: full.detail?.num_alarms ?? 0,
            universe: full.detail?.universe ?? [],
            timings: full.detail?.stage_timings ?? {},
          });
          setCombosTried(full.combos_tried);
          setRunning(false);
          fetchLeaderboard().then((r) => setHistory(r.rows)).catch(() => {});
          return;
        }
        if (scan.status === "failed") {
          setError(scan.error ?? "scan failed");
          setRunning(false);
          return;
        }
      }
      setError("timed out waiting for the scan to finish");
      setRunning(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setRunning(false);
    }
  };

  const stageLabel = stage ? (STAGE_LABELS[stage] ?? stage) : "";

  return (
    <div className="flex flex-col gap-10">
      <section className="flex flex-col gap-4">
        <div className="flex items-baseline justify-between">
          <span className="text-xs uppercase tracking-[0.3em] text-fog-faint">
            Page 1 · Auto mode
          </span>
          <span className="text-xs text-fog-faint">
            Progressive elimination · Aşama 0–6
          </span>
        </div>
        <h1 className="text-3xl font-semibold tracking-tight">Discovery</h1>

        {/* Scan builder */}
        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Labeled label="Symbols (blank = latest universe snapshot)">
              <input
                list="disc-symbols"
                value={symbolsText}
                onChange={(e) => setSymbolsText(e.target.value)}
                placeholder="BTCUSDT ETHUSDT …"
                className={inputCls}
              />
              <datalist id="disc-symbols">
                {knownSymbols.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            </Labeled>
            <Labeled label="Universe as-of (survivorship; optional)">
              <input
                type="date"
                value={config.universe_as_of ?? ""}
                onChange={(e) => patch({ universe_as_of: e.target.value || null })}
                className={inputCls}
              />
            </Labeled>
          </div>

          <div className="flex flex-col gap-2">
            <span className={labelCls}>Timeframes</span>
            <div className="flex flex-wrap gap-2">
              {TFS.map((tf) => {
                const on = config.timeframes.includes(tf);
                return (
                  <button
                    key={tf}
                    type="button"
                    onClick={() => toggleTf(tf)}
                    className={`rounded border px-3 py-1.5 text-xs transition-colors ${
                      on
                        ? "border-fog bg-fog text-void"
                        : "border-line text-fog-muted hover:text-fog"
                    }`}
                  >
                    {tf}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <Labeled label="Direction">
              <select
                value={config.direction}
                onChange={(e) => patch({ direction: e.target.value as Direction })}
                className={inputCls}
              >
                <option value="long">long</option>
                <option value="short">short</option>
                <option value="both">both</option>
              </select>
            </Labeled>
            <Labeled label="Top-N combos">
              <input
                type="number"
                value={config.top_n_combos}
                onChange={(e) => patch({ top_n_combos: Number(e.target.value) })}
                className={inputCls}
              />
            </Labeled>
            <Labeled label="Optuna trials">
              <input
                type="number"
                value={config.optuna_trials}
                onChange={(e) => patch({ optuna_trials: Number(e.target.value) })}
                className={inputCls}
              />
            </Labeled>
            <Labeled label="Seed">
              <input
                type="number"
                value={config.seed}
                onChange={(e) => patch({ seed: Number(e.target.value) })}
                className={inputCls}
              />
            </Labeled>
            <label className="flex items-center gap-2 self-end pb-2">
              <input
                type="checkbox"
                checked={config.fast_mode}
                onChange={(e) => patch({ fast_mode: e.target.checked })}
                className="h-4 w-4 accent-paper"
              />
              <span className="text-sm text-fog-muted">Fast mode</span>
            </label>
          </div>

          <div>
            <button
              type="button"
              onClick={onRun}
              disabled={running}
              className="rounded bg-fog px-6 py-2.5 text-sm font-semibold text-void transition-colors hover:bg-fog-muted disabled:cursor-not-allowed disabled:opacity-50"
            >
              {running ? "Scanning…" : "Run discovery scan"}
            </button>
            {config.fast_mode && (
              <span className="ml-3 text-xs text-paper">
                fast mode: small universe/period for development
              </span>
            )}
          </div>
        </div>

        {/* Live progress */}
        {running && (
          <div className="flex flex-col gap-2 rounded border border-line bg-graphite p-4">
            <div className="flex items-center justify-between text-sm">
              <span className="text-fog">
                <span className="animate-pulse text-paper">●</span> {stageLabel || "queued"}
              </span>
              <span className="text-fog-faint">
                {Math.round(progress * 100)}% · {combosTried} combos tried
              </span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded bg-void">
              <div
                className="h-full bg-paper transition-all"
                style={{ width: `${Math.max(2, progress * 100)}%` }}
              />
            </div>
          </div>
        )}
        {error && (
          <p className="rounded border border-loss/50 bg-loss/10 px-3 py-2 text-sm text-loss">
            {error}
          </p>
        )}
      </section>

      {/* Current scan leaderboard */}
      {entries && (
        <div className="flex flex-col gap-4 border-t border-line pt-8">
          <div className="flex items-baseline justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-fog">
              Leaderboard
            </h3>
            <span className="text-xs text-fog-faint">
              {entries.length} finalists · {scanMeta?.candidates ?? 0} candidates ·{" "}
              {combosTried} combos tried · {scanMeta?.alarms ?? 0} alarms
            </span>
          </div>
          {scanMeta && (
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-fog-faint">
              <span>universe: {scanMeta.universe.join(", ") || "—"}</span>
              {Object.entries(scanMeta.timings).map(([k, v]) => (
                <span key={k}>
                  {k}: {fmtNum(v, 2)}s
                </span>
              ))}
            </div>
          )}
          <LeaderboardTable entries={entries} scanId={scanId ?? undefined} />
        </div>
      )}

      {/* Cross-scan history (before a run this session) */}
      {!entries && history.length > 0 && (
        <div className="flex flex-col gap-4 border-t border-line pt-8">
          <div className="flex items-baseline justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-fog">
              Recent finalists
            </h3>
            <span className="text-xs text-fog-faint">across completed scans</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="text-[11px] uppercase tracking-wider text-fog-faint">
                <tr>
                  <th className="py-2 pr-3">Combo</th>
                  <th className="py-2 pr-3">Sym</th>
                  <th className="py-2 pr-3">TF</th>
                  <th className="py-2 pr-3 text-right">OOS</th>
                  <th className="py-2 pr-3 text-right">Net</th>
                  <th className="py-2 pr-3 text-right">Sharpe</th>
                  <th className="py-2 pr-3 text-right">Trades</th>
                  <th className="py-2 pr-3">Status</th>
                </tr>
              </thead>
              <tbody className="text-fog-muted">
                {history.map((r, i) => (
                  <tr key={i} className="border-t border-line">
                    <td className="py-2 pr-3 font-mono text-xs text-fog">
                      {r.combo.trigger}+{r.combo.filter}+{r.combo.exit}
                    </td>
                    <td className="py-2 pr-3">{r.symbol}</td>
                    <td className="py-2 pr-3">{r.tf}</td>
                    <td className="py-2 pr-3 text-right">{fmtNum(r.oos_score, 3)}</td>
                    <td className="py-2 pr-3 text-right">{fmtPct(r.net_return)}</td>
                    <td className="py-2 pr-3 text-right">{fmtNum(r.sharpe, 2)}</td>
                    <td className="py-2 pr-3 text-right">{r.num_trades ?? "—"}</td>
                    <td className="py-2 pr-3">{r.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
