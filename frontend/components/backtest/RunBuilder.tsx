"use client";

import type {
  DataStatusRow,
  Direction,
  IndicatorDef,
  IndicatorSpec,
  RiskExitConfig,
  RuleClause,
  RunConfig,
  SlippageModel,
} from "@/lib/api";

import { IndicatorPicker } from "./IndicatorPicker";
import { operandArgNames, RuleBuilder } from "./RuleBuilder";
import { Section } from "./Section";

const PRICE_FIELDS = ["open", "high", "low", "close", "volume"];
const TFS = ["1m", "5m", "15m", "1h", "4h", "1d"];

const inputCls =
  "rounded border border-line bg-void px-3 py-2 text-sm text-fog outline-none focus:border-fog-faint";
const labelCls = "text-[11px] uppercase tracking-wider text-fog-faint";

function Labeled({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className={labelCls}>{label}</span>
      {children}
      {hint && <span className="text-[11px] leading-tight text-fog-faint">{hint}</span>}
    </label>
  );
}

// Epoch-ms ⇄ yyyy-mm-dd (UTC) for the date-range inputs. Empty string ⇒ null (unbounded).
function msToDate(ms: number | null | undefined): string {
  return ms ? new Date(ms).toISOString().slice(0, 10) : "";
}
function dateToMs(value: string): number | null {
  return value ? Date.parse(`${value}T00:00:00Z`) : null;
}

function operandsFor(indicators: IndicatorSpec[], defs: IndicatorDef[]): string[] {
  const ops = [...PRICE_FIELDS];
  for (const spec of indicators) {
    const def = defs.find((d) => d.id === spec.id);
    const outs = def?.outputs ?? [];
    if (outs.length <= 1) ops.push(spec.key);
    else for (const o of outs) ops.push(`${spec.key}.${o}`);
  }
  return ops;
}

const RULE_LISTS = ["long_entry", "long_exit", "short_entry", "short_exit"] as const;

// Rewrite operand references (bare ``oldKey`` and ``oldKey.output``) when an
// indicator key is renamed, so rules never dangle after an edit.
function renameOperand(clauses: RuleClause[], oldKey: string, newKey: string): RuleClause[] {
  return clauses.map((c) => {
    const args = { ...c.args };
    for (const arg of operandArgNames(c.primitive)) {
      const v = args[arg];
      if (v === oldKey) args[arg] = newKey;
      else if (typeof v === "string" && v.startsWith(`${oldKey}.`))
        args[arg] = `${newKey}${v.slice(oldKey.length)}`;
    }
    return { ...c, args };
  });
}

// Operand names referenced by any clause that the current operand set can't
// resolve — these would fail the run server-side (unknown operand).
function danglingOperands(rules: RunConfig["rules"], operands: string[]): string[] {
  const known = new Set(operands);
  const out = new Set<string>();
  for (const list of RULE_LISTS) {
    for (const c of rules[list]) {
      for (const arg of operandArgNames(c.primitive)) {
        const v = c.args[arg];
        if (typeof v === "string" && v !== "" && !known.has(v)) out.add(v);
      }
    }
  }
  return [...out];
}

const RISK_EXIT_DEFAULT = { atr_stop_mult: 2.0, atr_target_mult: 3.0, atr_length: 14 };

export function RunBuilder({
  config,
  defs,
  dataRows,
  running,
  onChange,
  onRun,
}: {
  config: RunConfig;
  defs: IndicatorDef[];
  dataRows: DataStatusRow[];
  running: boolean;
  onChange: (config: RunConfig) => void;
  onRun: () => void;
}) {
  const patch = (p: Partial<RunConfig>) => onChange({ ...config, ...p });
  const patchCost = (p: Partial<RunConfig["costs"]>) =>
    patch({ costs: { ...config.costs, ...p } });
  const patchCap = (p: Partial<RunConfig["capital"]>) =>
    patch({ capital: { ...config.capital, ...p } });
  const re: RiskExitConfig = config.risk_exit ?? RISK_EXIT_DEFAULT;
  const patchRisk = (p: Partial<RiskExitConfig>) =>
    patch({ risk_exit: { ...re, ...p } });

  const symbols = [...new Set(dataRows.map((r) => r.symbol))].sort();
  const operands = operandsFor(config.indicators, defs);
  const dangling = danglingOperands(config.rules, operands);

  const cap = config.capital;
  const isAtr = cap.sizing === "atr";
  // §6.2 red-tag: a run with no commission *and* no slippage is "costless" (misleading).
  const commissionOff = config.costs.commission_bps <= 0;
  const slippageOff =
    config.costs.slippage_model === "fixed_bps"
      ? config.costs.slippage_bps <= 0
      : config.costs.atr_mult <= 0;
  const costless = commissionOff && slippageOff;
  const overLeverage = cap.leverage > 10;

  // ── Indicators ──────────────────────────────────────────────────────────
  const setIndicator = (i: number, next: IndicatorSpec) =>
    patch({ indicators: config.indicators.map((s, j) => (j === i ? next : s)) });
  const renameKey = (i: number, newKey: string) => {
    const oldKey = config.indicators[i].key;
    const indicators = config.indicators.map((s, j) => (j === i ? { ...s, key: newKey } : s));
    const rules = { ...config.rules };
    for (const list of RULE_LISTS) rules[list] = renameOperand(config.rules[list], oldKey, newKey);
    patch({ indicators, rules });
  };
  const removeIndicator = (i: number) =>
    patch({ indicators: config.indicators.filter((_, j) => j !== i) });
  const addIndicator = () =>
    patch({
      indicators: [
        ...config.indicators,
        { key: `ind_${config.indicators.length + 1}`, id: "ema", params: { timeperiod: 20 } },
      ],
    });
  const pickIndicator = (i: number, id: string) => {
    const def = defs.find((d) => d.id === id);
    const params: Record<string, number> = {};
    if (def) for (const [name, spec] of Object.entries(def.params)) params[name] = spec.default;
    setIndicator(i, { ...config.indicators[i], id, params });
  };

  return (
    <div className="flex flex-col gap-8">
      {/* ── Market & range ─────────────────────────────────────────────── */}
      <Section title="Market & range" subtitle="what to test, over which window">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Labeled label="Symbol">
            <input
              list="symbols"
              value={config.symbol}
              onChange={(e) => patch({ symbol: e.target.value.toUpperCase() })}
              className={inputCls}
            />
            <datalist id="symbols">
              {symbols.map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
          </Labeled>
          <Labeled label="Timeframe">
            <select
              value={config.tf}
              onChange={(e) => patch({ tf: e.target.value })}
              className={inputCls}
            >
              {TFS.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Labeled>
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
          <Labeled label="Start" hint="UTC · blank = earliest">
            <input
              type="date"
              value={msToDate(config.start_ts)}
              onChange={(e) => patch({ start_ts: dateToMs(e.target.value) })}
              className={inputCls}
            />
          </Labeled>
          <Labeled label="End" hint="UTC · blank = latest">
            <input
              type="date"
              value={msToDate(config.end_ts)}
              onChange={(e) => patch({ end_ts: dateToMs(e.target.value) })}
              className={inputCls}
            />
          </Labeled>
          <Labeled label="Seed" hint="same seed = same run">
            <input
              type="number"
              value={config.seed}
              onChange={(e) => patch({ seed: Number(e.target.value) })}
              className={inputCls}
            />
          </Labeled>
        </div>
      </Section>

      {/* ── Indicators ─────────────────────────────────────────────────── */}
      <Section title="Indicators" subtitle="each is addressed by its key in the rules below">
        <div className="flex flex-col gap-2">
          <button
            type="button"
            onClick={addIndicator}
            className="self-end text-xs text-fog-faint hover:text-fog"
          >
            + indicator
          </button>
          {config.indicators.map((spec, i) => {
            const def = defs.find((d) => d.id === spec.id);
            return (
              <div
                key={i}
                className="flex flex-wrap items-end gap-2 rounded border border-line bg-graphite p-3"
              >
                <div className="w-28">
                  <span className={labelCls}>key</span>
                  <input
                    value={spec.key}
                    onChange={(e) => renameKey(i, e.target.value)}
                    className={`${inputCls} w-full`}
                  />
                </div>
                <div className="min-w-[220px] flex-1">
                  <span className={labelCls}>indicator</span>
                  <IndicatorPicker
                    indicators={defs}
                    value={spec.id}
                    onChange={(id) => pickIndicator(i, id)}
                  />
                </div>
                {def &&
                  Object.entries(def.params).map(([name, pspec]) => (
                    <div key={name} className="w-24">
                      <span className={labelCls}>{name}</span>
                      <input
                        type="number"
                        step={pspec.step ?? 1}
                        value={spec.params[name] ?? pspec.default}
                        onChange={(e) =>
                          setIndicator(i, {
                            ...spec,
                            params: { ...spec.params, [name]: Number(e.target.value) },
                          })
                        }
                        className={`${inputCls} w-full`}
                      />
                    </div>
                  ))}
                <button
                  type="button"
                  onClick={() => removeIndicator(i)}
                  className="pb-2 text-xs text-fog-faint hover:text-loss"
                >
                  ✕
                </button>
              </div>
            );
          })}
        </div>
      </Section>

      {/* ── Rules ──────────────────────────────────────────────────────── */}
      <Section title="Rules" subtitle="signals evaluate at bar close, fill next open">
        <div className="grid gap-3 md:grid-cols-2">
          <RuleBuilder
            label="Long entry"
            clauses={config.rules.long_entry}
            operands={operands}
            onChange={(c) => patch({ rules: { ...config.rules, long_entry: c } })}
          />
          <RuleBuilder
            label="Long exit"
            clauses={config.rules.long_exit}
            operands={operands}
            onChange={(c) => patch({ rules: { ...config.rules, long_exit: c } })}
          />
          <RuleBuilder
            label="Short entry"
            clauses={config.rules.short_entry}
            operands={operands}
            onChange={(c) => patch({ rules: { ...config.rules, short_entry: c } })}
          />
          <RuleBuilder
            label="Short exit"
            clauses={config.rules.short_exit}
            operands={operands}
            onChange={(c) => patch({ rules: { ...config.rules, short_exit: c } })}
          />
        </div>
      </Section>

      {/* ── Risk & sizing ──────────────────────────────────────────────── */}
      <Section
        title="Risk & sizing"
        subtitle="how big each position is — the model the live bot also uses"
      >
        <p className="text-xs leading-relaxed text-fog-muted">
          These settings decide position size and stops <em>identically</em> in the backtest and
          in paper/live trading, so a validated strategy behaves the same when it goes live.
          The default is <span className="text-fog">ATR risk</span>: each trade risks a fixed
          slice of equity to its stop.
        </p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          <Labeled label="Sizing" hint={isAtr ? "risk % of equity to the stop" : "deploy a fixed % of equity"}>
            <select
              value={cap.sizing}
              onChange={(e) => patchCap({ sizing: e.target.value as "atr" | "fixed" })}
              className={inputCls}
            >
              <option value="atr">ATR risk (recommended)</option>
              <option value="fixed">Fixed fraction</option>
            </select>
          </Labeled>
          {isAtr ? (
            <>
              <Labeled label="Risk / trade %" hint="equity lost if the stop is hit">
                <input
                  type="number"
                  step={0.25}
                  value={cap.per_trade_pct}
                  onChange={(e) => patchCap({ per_trade_pct: Number(e.target.value) })}
                  className={inputCls}
                />
              </Labeled>
              <Labeled label="Stop (× ATR)" hint="stop distance = mult × ATR at entry">
                <input
                  type="number"
                  step={0.5}
                  value={re.atr_stop_mult ?? cap.default_stop_atr_mult}
                  onChange={(e) => patchRisk({ atr_stop_mult: Number(e.target.value) })}
                  className={inputCls}
                />
              </Labeled>
              <Labeled label="Target (× ATR)" hint="blank = no take-profit">
                <input
                  type="number"
                  step={0.5}
                  value={re.atr_target_mult ?? ""}
                  onChange={(e) =>
                    patchRisk({
                      atr_target_mult: e.target.value === "" ? null : Number(e.target.value),
                    })
                  }
                  className={inputCls}
                />
              </Labeled>
            </>
          ) : (
            <Labeled label="Size %" hint="fraction of equity as notional">
              <input
                type="number"
                step={0.05}
                value={cap.size_pct}
                onChange={(e) => patchCap({ size_pct: Number(e.target.value) })}
                className={inputCls}
              />
            </Labeled>
          )}
          <Labeled label="Leverage" hint="hard cap 10× · liquidation modeled">
            <input
              type="number"
              step={0.5}
              value={cap.leverage}
              onChange={(e) => patchCap({ leverage: Number(e.target.value) })}
              className={`${inputCls} ${overLeverage ? "border-loss text-loss" : ""}`}
            />
          </Labeled>
          <Labeled label="Initial cash">
            <input
              type="number"
              value={cap.initial_cash}
              onChange={(e) => patchCap({ initial_cash: Number(e.target.value) })}
              className={inputCls}
            />
          </Labeled>
        </div>
        {overLeverage && (
          <p className="text-xs text-loss">
            Leverage above the 10× hard cap — the live risk wall will refuse it (rule #11).
          </p>
        )}
      </Section>

      {/* ── Costs ──────────────────────────────────────────────────────── */}
      <Section title="Costs" subtitle="on by default — a costless run is a fiction">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          <Labeled label="Commission (bps)" hint="per side · Binance taker ≈ 4">
            <input
              type="number"
              value={config.costs.commission_bps}
              onChange={(e) => patchCost({ commission_bps: Number(e.target.value) })}
              className={inputCls}
            />
          </Labeled>
          <Labeled label="Slippage model">
            <select
              value={config.costs.slippage_model}
              onChange={(e) => patchCost({ slippage_model: e.target.value as SlippageModel })}
              className={inputCls}
            >
              <option value="fixed_bps">fixed_bps</option>
              <option value="atr">atr</option>
            </select>
          </Labeled>
          {config.costs.slippage_model === "fixed_bps" ? (
            <Labeled label="Slippage (bps)">
              <input
                type="number"
                value={config.costs.slippage_bps}
                onChange={(e) => patchCost({ slippage_bps: Number(e.target.value) })}
                className={inputCls}
              />
            </Labeled>
          ) : (
            <Labeled label="ATR mult">
              <input
                type="number"
                step={0.01}
                value={config.costs.atr_mult}
                onChange={(e) => patchCost({ atr_mult: Number(e.target.value) })}
                className={inputCls}
              />
            </Labeled>
          )}
          <label className="flex items-center gap-2 self-end pb-2">
            <input
              type="checkbox"
              checked={config.costs.funding_enabled}
              onChange={(e) => patchCost({ funding_enabled: e.target.checked })}
              className="h-4 w-4 accent-profit"
            />
            <span className="text-sm text-fog-muted">Funding</span>
          </label>
        </div>
        {costless && (
          <p className="rounded border border-loss/40 bg-loss/10 px-3 py-2 text-xs text-loss">
            ⚠ Costless run — commission and slippage are both zero. Results will overstate
            profitability; turn costs on before trusting them (doc §6.2).
          </p>
        )}
        {!config.costs.funding_enabled && (
          <p className="text-xs text-fog-faint">
            Funding is off — a perpetual-futures backtest without funding is a rent-free
            fantasy (doc §6.2).
          </p>
        )}
      </Section>

      {/* ── Run ────────────────────────────────────────────────────────── */}
      <div className="flex flex-col gap-2">
        {dangling.length > 0 && (
          <p className="text-xs text-loss">
            Unknown operand{dangling.length > 1 ? "s" : ""}:{" "}
            <span className="font-mono">{dangling.join(", ")}</span> — referenced by a rule but
            not produced by any indicator. Fix the highlighted operand{dangling.length > 1 ? "s" : ""}{" "}
            before running.
          </p>
        )}
        <button
          type="button"
          onClick={onRun}
          disabled={running || dangling.length > 0}
          className="w-fit rounded bg-fog px-6 py-2.5 text-sm font-semibold text-void transition-colors hover:bg-fog-muted disabled:cursor-not-allowed disabled:opacity-50"
        >
          {running ? "Running…" : "Run backtest"}
        </button>
      </div>
    </div>
  );
}
