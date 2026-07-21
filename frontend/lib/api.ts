// Backend API client + shared types (doc §12). Mirrors app/backtest/config.py
// and the run report assembled by app/backtest/runner.py.

// The API root is baked at build time (docker-compose sets NEXT_PUBLIC_API_URL);
// REST routes live under /api.
const API_ROOT = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const API_BASE = `${API_ROOT}/api`;

// ── Config (request) ─────────────────────────────────────────────────────────
export type Direction = "long" | "short" | "both";
export type SlippageModel = "fixed_bps" | "atr";
export type Sizing = "atr" | "fixed";
export type Primitive =
  | "threshold_cross"
  | "line_cross"
  | "slope"
  | "band_touch"
  | "regime"
  | "pattern";

export interface IndicatorSpec {
  key: string;
  id: string;
  params: Record<string, number>;
}

export interface RuleClause {
  primitive: Primitive;
  args: Record<string, string | number>;
}

export interface Rules {
  long_entry: RuleClause[];
  long_exit: RuleClause[];
  short_entry: RuleClause[];
  short_exit: RuleClause[];
}

export interface CostConfig {
  commission_bps: number;
  slippage_model: SlippageModel;
  slippage_bps: number;
  atr_mult: number;
  atr_length: number;
  funding_enabled: boolean;
}

export interface CapitalConfig {
  initial_cash: number;
  sizing: Sizing;
  per_trade_pct: number; // equity risked per trade (sizing === "atr")
  default_stop_atr_mult: number; // stop = mult × ATR when the exit gives none
  maintenance_margin_rate: number; // for the liquidation model
  size_pct: number; // fraction of equity deployed (sizing === "fixed")
  leverage: number;
}

export interface RiskExitConfig {
  atr_stop_mult: number | null;
  atr_target_mult: number | null;
  atr_length: number;
}

export interface RunConfig {
  market: string;
  symbol: string;
  tf: string;
  start_ts?: number | null;
  end_ts?: number | null;
  direction: Direction;
  indicators: IndicatorSpec[];
  rules: Rules;
  costs: CostConfig;
  capital: CapitalConfig;
  risk_exit?: RiskExitConfig;
  seed: number;
}

// ── Registry ─────────────────────────────────────────────────────────────────
export interface ParamSpec {
  default: number;
  min?: number | null;
  max?: number | null;
  step?: number | null;
  choices?: number[] | null;
  kind: string;
}

export interface IndicatorDef {
  id: string;
  name: string;
  category: string;
  source: string;
  inputs: string[];
  params: Record<string, ParamSpec>;
  outputs: string[];
  signal_templates: string[];
  available: boolean;
}

// ── Report (response) ────────────────────────────────────────────────────────
export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface Point {
  time: number;
  value: number;
}

export interface Marker {
  time: number;
  price: number;
  kind: string;
  forced?: boolean;
}

export interface Trade {
  side: string;
  entry_ts: number;
  exit_ts: number;
  entry_index: number;
  exit_index: number;
  entry_price: number;
  exit_price: number;
  qty: number;
  bars_held: number;
  gross_pnl: number;
  commission: number;
  funding: number;
  slippage_cost: number;
  net_pnl: number;
  return_pct: number;
  forced: boolean;
  liquidated?: boolean;
}

export interface CostBreakdown {
  total_commission: number;
  total_funding: number;
  total_slippage: number;
  commission_on: boolean;
  slippage_on: boolean;
  funding_on: boolean;
  costless: boolean;
}

export interface Report {
  market: string;
  symbol: string;
  tf: string;
  direction: string;
  config_hash: string;
  bars: number;
  candles: Candle[];
  equity: Point[];
  drawdown: Point[];
  position: number[];
  markers: Marker[];
  trades: Trade[];
  cost_breakdown: CostBreakdown;
}

export interface MonthlyReturn {
  year: number;
  month: number;
  return: number | null;
}

export interface Metrics {
  net_return: number | null;
  cagr: number | null;
  sharpe: number | null;
  sortino: number | null;
  calmar: number | null;
  max_drawdown: number | null;
  max_drawdown_bars: number;
  win_rate: number | null;
  profit_factor: number | null;
  expectancy: number | null;
  expectancy_pct: number | null;
  avg_win_loss: number | null;
  num_trades: number;
  exposure: number | null;
  sqn: number | null;
  final_equity: number | null;
  monthly_returns: MonthlyReturn[];
  composite_score: number | null;
  passes_hard_filters: boolean;
  score_components: Record<string, number | null>;
}

export interface RunDetail {
  id: string;
  status: string;
  config: RunConfig;
  config_hash: string;
  seed: number;
  metrics: Metrics | null;
  report: Report | null;
  error: string | null;
  created_at: string | null;
}

export interface DataStatusRow {
  market: string;
  symbol: string;
  tf: string;
  first_ts: number | null;
  last_ts: number | null;
  rows: number;
}

// ── Calls ────────────────────────────────────────────────────────────────────
async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export async function fetchIndicators(): Promise<IndicatorDef[]> {
  const data = await getJSON<{ count: number; indicators: IndicatorDef[] }>(
    "/indicators",
  );
  return data.indicators;
}

export async function fetchDataStatus(): Promise<DataStatusRow[]> {
  const data = await getJSON<{ series: DataStatusRow[] }>("/data/status");
  return data.series;
}

export async function postRun(
  config: RunConfig,
): Promise<{ run_id: string; status: string; config_hash: string }> {
  const res = await fetch(`${API_BASE}/backtest/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`run failed → ${res.status}: ${detail}`);
  }
  return res.json();
}

export async function fetchRun(
  id: string,
  includeReport = true,
): Promise<RunDetail> {
  return getJSON<RunDetail>(
    `/backtest/runs/${id}?include_report=${includeReport}`,
  );
}

// ── Discovery (doc §7, §12) ──────────────────────────────────────────────────
export interface ScanConfigInput {
  market: string;
  symbols: string[] | null;
  universe_as_of?: string | null;
  timeframes: string[];
  direction: Direction;
  top_n_combos: number;
  optuna_trials: number;
  fast_mode: boolean;
  seed: number;
  costs?: Partial<CostConfig>;
}

export interface ComboRef {
  trigger: string;
  filter: string;
  exit: string;
  symbol: string;
  tf: string;
}

export interface LeaderboardRow {
  rank?: number;
  combo: ComboRef;
  symbol: string;
  tf: string;
  oos_score: number | null;
  status: string;
  net_return: number | null;
  sharpe: number | null; // raw (rule #14)
  max_drawdown: number | null;
  profit_factor: number | null;
  win_rate: number | null;
  num_trades: number | null;
  composite_score: number | null;
  alarms: number;
  // Aşama 5.5 deflation gate (doc §23)
  dsr: number | null;
  pbo: number | null;
  trials_total: number | null;
  bh_excess: number | null;
  gate_passed: boolean | null;
  scan_id?: string;
}

export interface ScanSummary {
  combos_tried: number;
  num_candidates: number;
  num_alarms: number;
  universe: string[];
  stage_timings: Record<string, number>;
  rows: LeaderboardRow[];
}

export interface WfoLayer {
  train_start: number;
  train_end: number;
  test_start: number;
  test_end: number;
  composite_score: number;
  net_return: number | null;
  num_trades: number;
}

export interface AlarmRow {
  combo_key: string;
  engine: string;
  metric: string;
  primary: number;
  finalist: number;
  rel_diff: number;
  tolerance: number;
}

export interface LeaderboardEntry {
  rank?: number;
  combo: ComboRef;
  genome: RunConfig;
  symbol: string;
  tf: string;
  oos_score: number | null;
  is_score: number | null;
  metrics: Metrics | null;
  wfo_layers: WfoLayer[];
  monte_carlo: { p95_max_drawdown: number; mean_max_drawdown: number; runs: number };
  plateau_ok: boolean;
  survived: boolean;
  status: string;
  alarms: AlarmRow[];
  finalist?: { engine: string; net_return: number; num_trades: number; sharpe: number };
  // Aşama 5.5 deflation gate (doc §23)
  genome_hash: string | null;
  trials_total: number | null;
  dsr: number | null; // deflated Sharpe (probability) — promotion looks here, not raw
  sr_star: number | null;
  pbo: number | null;
  bh_return: number | null;
  bh_excess: number | null;
  gate_passed: boolean | null;
  gate_reasons: string[];
  raw_sharpe: number | null;
}

export interface ScanDetailPayload {
  combos_tried: number;
  num_candidates: number;
  num_alarms: number;
  universe: string[];
  stage_timings: Record<string, number>;
  alarms: AlarmRow[];
  leaderboard: LeaderboardEntry[];
}

export interface ScanDetail {
  id: string;
  status: string;
  stage: string | null;
  progress: number;
  combos_tried: number;
  config: Record<string, unknown>;
  config_hash: string;
  seed: number;
  leaderboard: ScanSummary | null;
  detail: ScanDetailPayload | null;
  error: string | null;
  created_at: string | null;
}

export async function postScan(
  config: ScanConfigInput,
): Promise<{ scan_id: string; status: string; config_hash: string }> {
  const res = await fetch(`${API_BASE}/discovery/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`scan failed → ${res.status}: ${detail}`);
  }
  return res.json();
}

export async function fetchScan(
  id: string,
  includeDetail = false,
): Promise<ScanDetail> {
  return getJSON<ScanDetail>(
    `/discovery/scans/${id}?include_detail=${includeDetail}`,
  );
}

export async function fetchLeaderboard(
  sortBy = "oos_score",
  limit = 50,
): Promise<{ count: number; sort_by: string; rows: LeaderboardRow[] }> {
  return getJSON(`/discovery/leaderboard?sort_by=${sortBy}&limit=${limit}`);
}

// ── Strategies (doc §8) + Trade Bot (doc §9, §10) ────────────────────────────
export type BotMode = "off" | "paper" | "live";

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`POST ${path} → ${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export interface StrategyHealth {
  num_trades: number;
  rolling_pf: number | null;
  last_pnl: number | null;
  open_positions: number;
}

export interface StrategyOut {
  id: string;
  name: string;
  mode: BotMode;
  active_version_id: string | null;
  active_version: number | null;
  status: string | null;
  regime: string | null;
  created_from_run_id: string | null;
  created_at: string | null;
  health: StrategyHealth;
}

export interface StrategyVersion {
  id: string;
  strategy_id: string;
  version: number;
  genome: { name: string; config: RunConfig };
  genome_hash: string;
  status: string;
  regime: string | null;
  parent_version_id: string | null;
  source: Record<string, unknown> | null;
  wfo_report: Record<string, unknown> | null;
  created_at: string | null;
}

// A self-generated version awaiting human approval (doc §8.5).
export interface PendingVersion {
  version: StrategyVersion;
  strategy_id: string;
  strategy_name: string;
  active_version: number | null;
  diff: Record<string, { from: unknown; to: unknown }>;
}

export interface BotStatus {
  global_mode: BotMode;
  live_enabled: boolean;
  killswitch: boolean;
  equity: number | null;
  exposure: number;
  daily_pnl: number | null;
  open_positions: number;
  regime: string | null;
}

export interface Position {
  symbol: string;
  side: string;
  qty: number;
  entry_price: number;
  leverage: number;
  entry_ts: number;
  strategy_id: string | null;
}

export interface Portfolio {
  positions: Position[];
  equity: number | null;
  exposure: number;
}

export type ReasonClause = { primitive: string; args: Record<string, unknown> };

export interface SignalRow {
  id: string;
  strategy_id: string;
  strategy_version_id: string;
  ts: number;
  symbol: string;
  tf: string;
  action: string;
  reason: Record<string, ReasonClause[]>;
  indicator_snapshot: Record<string, number | null>;
  outcome: string;
  outcome_detail: Record<string, unknown> | null;
}

export interface DecisionRow {
  kind: "signal" | "risk";
  ts: number;
  type?: string;
  symbol?: string | null;
  detail?: Record<string, unknown>;
  [k: string]: unknown;
}

export interface EquityPoint {
  time: number;
  value: number;
  exposure: number;
}

export interface BotSettings {
  risk_limits: Record<string, number | string>;
  promotion_gate: Record<string, number>;
  regime_lock?: { mode: string };
}

// Strategies
export const fetchStrategies = () => getJSON<StrategyOut[]>("/strategies");
export const fetchStrategy = (id: string) => getJSON<StrategyOut>(`/strategies/${id}`);
export const fetchVersions = (id: string) =>
  getJSON<StrategyVersion[]>(`/strategies/${id}/versions`);
export const addVersion = (id: string, genome: unknown, wfo_report?: unknown) =>
  postJSON<StrategyVersion>(`/strategies/${id}/versions`, { genome, wfo_report });
export const diffVersions = (id: string, a: string, b: string) =>
  getJSON<{ a: number; b: number; changes: Record<string, { from: unknown; to: unknown }> }>(
    `/strategies/${id}/diff?a=${a}&b=${b}`,
  );
export const setStrategyMode = (id: string, mode: BotMode) =>
  postJSON<StrategyOut>(`/strategies/${id}/mode`, { mode });
export const promoteStrategy = (id: string) =>
  postJSON<StrategyOut>(`/strategies/${id}/promote`, {});
export const pauseStrategy = (id: string) =>
  postJSON<StrategyOut>(`/strategies/${id}/pause`, {});
export const retireStrategy = (id: string) =>
  postJSON<StrategyOut>(`/strategies/${id}/retire`, {});
export const convertToStrategy = (body: {
  run_id?: string;
  scan_id?: string;
  rank?: number;
  name?: string;
}) => postJSON<StrategyOut>("/strategies/from-run", body);
export const reloadPlugins = () =>
  postJSON<{ loaded: string[]; primitives: string[] }>("/strategies/reload-plugins", {});

// Self-improvement (doc §8.3–8.5): re-opt, approval queue, approve/reject.
export const fetchPending = () => getJSON<PendingVersion[]>("/strategies/pending");
export const reoptimizeStrategy = (id: string, trials?: number) =>
  postJSON<{ produced: boolean; version: StrategyVersion | null }>(
    `/strategies/${id}/reoptimize`,
    { trials },
  );
export const approveVersion = (id: string, versionId: string) =>
  postJSON<StrategyOut>(`/strategies/${id}/versions/${versionId}/approve`, {});
export const rejectVersion = (id: string, versionId: string) =>
  postJSON<StrategyVersion>(`/strategies/${id}/versions/${versionId}/reject`, {});
export const simulateDegrade = (strategyId: string, trials?: number) =>
  postJSON<{ paused: boolean; verdict: Record<string, unknown>; pending_version: unknown }>(
    "/bot/debug/degrade",
    { strategy_id: strategyId, trials },
  );

// Bot control + reads
export const fetchBotStatus = () => getJSON<BotStatus>("/bot/status");
export const setBotMode = (mode: BotMode) =>
  postJSON<{ mode: BotMode }>("/bot/mode", { mode, scope: "global" });
export const engageKill = (reason = "ui") =>
  postJSON<{ killswitch: boolean }>("/bot/killswitch", { reason });
export const clearKill = () =>
  postJSON<{ killswitch: boolean }>("/bot/killswitch/clear", {});
export const fetchPortfolio = () => getJSON<Portfolio>("/bot/portfolio");
export const fetchSignals = (since = 0) =>
  getJSON<{ signals: SignalRow[] }>(`/bot/signals?since=${since}&limit=100`);
export const fetchDecisions = () =>
  getJSON<{ decisions: DecisionRow[] }>("/bot/decisions?limit=100");
export const fetchBotEquity = () =>
  getJSON<{ points: EquityPoint[] }>("/bot/equity?limit=1000");
export const fetchBotSettings = () => getJSON<BotSettings>("/bot/settings");
export const updateBotSettings = (body: Partial<BotSettings>) =>
  postJSON<BotSettings>("/bot/settings", body);

// ── Live execution (Phase 7, doc §9.2–9.5) ───────────────────────────────────

// Verdict of the paper → live promotion gate (§9.5). `failures` is the list of
// thresholds still unmet — the UI shows them verbatim so a closed gate is never
// a mystery. The API refuses LIVE independently; this only mirrors the reason.
export interface GateStatus {
  passed: boolean;
  scope: "global" | "strategy";
  strategy_id: string | null;
  failures: string[];
  metrics: {
    num_trades?: number;
    days?: number;
    profit_factor?: number | null;
    max_drawdown_pct?: number;
    infra_ready?: boolean;
    strategies?: { strategy_id: string; passed: boolean; metrics: Record<string, unknown> }[];
  };
}

// Live-vs-paper divergence (doc §15/Faz-7). All values are fractions, not %.
export interface TrackingError {
  points: number;
  tracking_error: number | null;
  cum_return_live: number | null;
  cum_return_paper: number | null;
  cum_gap: number | null;
  correlation: number | null;
}

// Masked key view — the plaintext never crosses this boundary (doc §13).
export interface KeyStatus {
  configured: boolean;
  key_mask: string | null;
  testnet: boolean | null;
}

export const fetchGate = (scope: "global" | "strategy" = "global", strategyId?: string) =>
  getJSON<GateStatus>(
    `/bot/gate?scope=${scope}${strategyId ? `&strategy_id=${strategyId}` : ""}`,
  );
export const fetchTracking = () => getJSON<TrackingError>("/bot/tracking");
export const fetchKeys = () => getJSON<KeyStatus>("/bot/keys");
export const saveKeys = (api_key: string, api_secret: string, testnet: boolean) =>
  postJSON<KeyStatus>("/bot/keys", { api_key, api_secret, testnet });
