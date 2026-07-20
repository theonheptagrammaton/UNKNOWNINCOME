"use client";

import { useEffect, useState } from "react";

import {
  fetchBotSettings,
  fetchKeys,
  saveKeys,
  updateBotSettings,
  type BotSettings,
  type KeyStatus,
} from "@/lib/api";

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

// Regime lock modes (doc §8.4): off = no gating, auto = match the live regime,
// or lock the desk to a single regime pool.
const REGIME_MODES = ["off", "auto", "trend", "range", "trend/high", "range/low"] as const;

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

// Exchange API keys (doc §13). This form is the *only* way keys enter the system:
// they are posted once, encrypted server-side with Fernet, and never read back —
// the browser only ever sees a `····last4` mask. Inputs are cleared on save so the
// plaintext does not linger in component state.
function ApiKeysSection() {
  const [status, setStatus] = useState<KeyStatus | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [testnet, setTestnet] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchKeys()
      .then((s) => {
        setStatus(s);
        if (s.testnet !== null) setTestnet(s.testnet);
      })
      .catch((e) => setMsg(e instanceof Error ? e.message : String(e)));
  }, []);

  const submit = async () => {
    if (!apiKey || !apiSecret) {
      setMsg("Both key and secret are required.");
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const saved = await saveKeys(apiKey, apiSecret, testnet);
      setStatus(saved);
      setApiKey("");
      setApiSecret("");
      setMsg(`Stored encrypted (${saved.testnet ? "testnet" : "mainnet"}).`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-2 flex flex-col gap-2 border-t border-line pt-3">
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] uppercase tracking-wider text-fog-faint">
          Exchange API keys (doc §13)
        </span>
        <span className="text-xs text-fog-faint">
          {status?.configured ? `set · ${status.key_mask}` : "not configured"}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1">
          <span className="text-[11px] uppercase tracking-wider text-fog-faint">API key</span>
          <input
            type="password"
            autoComplete="off"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={status?.configured ? "replace stored key" : "paste key"}
            className="rounded border border-line bg-void px-2.5 py-1.5 text-sm text-fog outline-none focus:border-fog-faint"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[11px] uppercase tracking-wider text-fog-faint">API secret</span>
          <input
            type="password"
            autoComplete="off"
            value={apiSecret}
            onChange={(e) => setApiSecret(e.target.value)}
            placeholder={status?.configured ? "replace stored secret" : "paste secret"}
            className="rounded border border-line bg-void px-2.5 py-1.5 text-sm text-fog outline-none focus:border-fog-faint"
          />
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex overflow-hidden rounded border border-line text-xs">
          {[true, false].map((t) => (
            <button
              key={String(t)}
              type="button"
              onClick={() => setTestnet(t)}
              className={`px-3 py-1 uppercase tracking-wider transition-colors ${
                testnet === t ? "bg-fog text-void" : "text-fog-muted hover:text-fog"
              }`}
            >
              {t ? "testnet" : "mainnet"}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={submit}
          disabled={busy}
          className="rounded border border-line px-4 py-1.5 text-sm text-fog hover:border-fog-faint disabled:opacity-50"
        >
          {busy ? "Storing…" : "Store keys"}
        </button>
        {msg && <span className="text-xs text-fog-muted">{msg}</span>}
      </div>

      {!testnet && (
        <p className="text-xs text-loss">
          Mainnet keys trade real capital. Use trade-only keys with withdrawal disabled
          and the VDS IP whitelisted (doc §13).
        </p>
      )}
      <p className="text-xs text-fog-faint">
        Keys are encrypted with Fernet server-side and never sent back to the browser —
        only a <span className="tabular-nums">····last4</span> mask is shown.
      </p>
    </div>
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
  const patchRegime = (mode: string) =>
    setSettings((s) => (s ? { ...s, regime_lock: { mode } } : s));

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
        <span className="text-xs text-fog-faint">risk · promotion · regime</span>
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

          <div className="mt-2 flex flex-col gap-2 border-t border-line pt-3">
            <span className="text-[11px] uppercase tracking-wider text-fog-faint">
              Regime gate (doc §8.4) — bot runs only the pool matching the active regime
            </span>
            <div className="flex flex-wrap overflow-hidden rounded border border-line text-xs">
              {REGIME_MODES.map((m) => {
                const active = (settings.regime_lock?.mode ?? "off") === m;
                return (
                  <button
                    key={m}
                    type="button"
                    onClick={() => patchRegime(m)}
                    className={`px-3 py-1 uppercase tracking-wider transition-colors ${
                      active ? "bg-fog text-void" : "text-fog-muted hover:text-fog"
                    }`}
                  >
                    {m}
                  </button>
                );
              })}
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
          <ApiKeysSection />
        </>
      )}
    </section>
  );
}
