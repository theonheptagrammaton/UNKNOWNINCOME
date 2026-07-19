import type { RunConfig } from "@/lib/api";

// The EMA9×EMA21 reference strategy (doc §15 Faz 3 KABUL) — a ready-to-run
// starting point so the builder is never empty.
export function defaultConfig(symbol = "BTCUSDT", tf = "1h"): RunConfig {
  return {
    market: "binance_usdm",
    symbol,
    tf,
    start_ts: null,
    end_ts: null,
    direction: "both",
    indicators: [
      { key: "ema_fast", id: "ema", params: { timeperiod: 9 } },
      { key: "ema_slow", id: "ema", params: { timeperiod: 21 } },
    ],
    rules: {
      long_entry: [
        {
          primitive: "line_cross",
          args: { a: "ema_fast", b: "ema_slow", direction: "up" },
        },
      ],
      long_exit: [
        {
          primitive: "line_cross",
          args: { a: "ema_fast", b: "ema_slow", direction: "down" },
        },
      ],
      short_entry: [
        {
          primitive: "line_cross",
          args: { a: "ema_fast", b: "ema_slow", direction: "down" },
        },
      ],
      short_exit: [
        {
          primitive: "line_cross",
          args: { a: "ema_fast", b: "ema_slow", direction: "up" },
        },
      ],
    },
    costs: {
      commission_bps: 4,
      slippage_model: "fixed_bps",
      slippage_bps: 5,
      atr_mult: 0.05,
      atr_length: 14,
      funding_enabled: true,
    },
    capital: { initial_cash: 10000, size_pct: 1.0, leverage: 1.0 },
    seed: 42,
  };
}

// Palette pulled from the Silent Luxury tokens (globals.css) — lightweight-charts
// needs literal colours, not CSS variables.
export const CHART = {
  bg: "#08090a",
  text: "#9a9ea6",
  grid: "#1c1e22",
  border: "#26282d",
  profit: "#3fb57f",
  loss: "#e5484d",
  muted: "#61656c",
  accent: "#d9a441",
};
