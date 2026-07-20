"use client";

import { useEffect, useState } from "react";

import { fetchBotSettings, updateBotSettings, type BotSettings } from "@/lib/api";

// Human labels for the risk limits (doc §9.4) shown in the settings panel.
const RISK_LABELS: Record<string, string> = {
  per_trade_pct: "Risk / trade (%)",
  max_concurrent_positions: "Max positions",
  max_daily_loss_pct: "Daily loss halt (%)",
  max_total_drawdown_pct: "Total DD kill (%)",
  consecutive_losses: "Cooldown after N losses",
  cooldown_hours: "Cooldown (h)",
  price_deviation_pct: "Price guard (%)",
  leverage_cap: "Leverage cap",
  leverage_default: "Leverage default",
  liq_buffer_atr_mult: "Liq buffer (×ATR)",
};

const GATE_LABELS: Record<string, string> = {
  min_days: "Min days",
  min_trades: "Min trades",
  min_profit_factor: "Min profit factor",
  max_drawdown_pct: "Max drawdown (%)",
};

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number | string;
  onChange: (v: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] uppercase tracking-wider text-fog-faint">{label}</span>
      <input
        type="number"
        value={value as number}
        onChange={(e) => onChange(Number(e.target.value))}
        className="rounded border border-line bg-void px-2.5 py-1.5 text-sm text-fog outline-none focus:border-fog-faint"
      />
    </label>
  );
}

export function SettingsPanel() {
  const [settings, setSettings] = useState<BotSettings | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchBotSettings()
      .then(setSettings)
      .catch((e) => setMsg(e instanceof Error ? e.message : String(e)));
  }, []);

  const patchRisk = (k: string, v: number) =>
    setSettings((s) => (s ? { ...s, risk_limits: { ...s.risk_limits, [k]: v } } : s));
  const patchGate = (k: string, v: number) =>
    setSettings((s) => (s ? { ...s, promotion_gate: { ...s.promotion_gate, [k]: v } } : s));

  const save = async () => {
    if (!settings) return;
    setBusy(true);
    setMsg(null);
    try {
      const saved = await updateBotSettings(settings);
      setSettings(saved);
      setMsg("Saved. The bot applies limits on its next tick.");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="flex flex-col gap-3 rounded border border-line bg-graphite p-4">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-fog">Settings</h3>
        <span className="text-xs text-fog-faint">risk limits · promotion gate</span>
      </div>

      {!settings ? (
        <p className="text-sm text-fog-faint">{msg ?? "Loading…"}</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {Object.entries(RISK_LABELS).map(([k, label]) => (
              <NumberField
                key={k}
                label={label}
                value={settings.risk_limits[k] ?? 0}
                onChange={(v) => patchRisk(k, v)}
              />
            ))}
          </div>

          <div className="mt-2 flex flex-col gap-2 border-t border-line pt-3">
            <span className="text-[11px] uppercase tracking-wider text-fog-faint">
              Paper → Live promotion gate (doc §9.5)
            </span>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {Object.entries(GATE_LABELS).map(([k, label]) => (
                <NumberField
                  key={k}
                  label={label}
                  value={settings.promotion_gate[k] ?? 0}
                  onChange={(v) => patchGate(k, v)}
                />
              ))}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={save}
              disabled={busy}
              className="rounded bg-fog px-4 py-1.5 text-sm font-semibold text-void hover:bg-fog-muted disabled:opacity-50"
            >
              {busy ? "Saving…" : "Save settings"}
            </button>
            {msg && <span className="text-xs text-fog-muted">{msg}</span>}
          </div>
          <p className="text-xs text-fog-faint">
            API keys are stored encrypted server-side and never sent to the browser (doc §13).
          </p>
        </>
      )}
    </section>
  );
}
