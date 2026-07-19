// Backend API client + shared types (doc §12). Mirrors app/backtest/config.py
// and the run report assembled by app/backtest/runner.py.

// The API root is baked at build time (docker-compose sets NEXT_PUBLIC_API_URL);
// REST routes live under /api.
const API_ROOT = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const API_BASE = `${API_ROOT}/api`;

// ── Config (request) ─────────────────────────────────────────────────────────
export type Direction = "long" | "short" | "both";
export type SlippageModel = "fixed_bps" | "atr";
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
  size_pct: number;
  leverage: number;
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
