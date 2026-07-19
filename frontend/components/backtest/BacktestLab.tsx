"use client";

import { useEffect, useRef, useState } from "react";

import {
  fetchDataStatus,
  fetchIndicators,
  fetchRun,
  postRun,
  type DataStatusRow,
  type IndicatorDef,
  type RunConfig,
  type RunDetail as RunDetailType,
} from "@/lib/api";
import { defaultConfig } from "@/lib/defaults";

import { RunBuilder } from "./RunBuilder";
import { RunDetail } from "./RunDetail";

const POLL_MS = 800;
const MAX_POLLS = 150; // ~2 min ceiling

export function BacktestLab() {
  const [defs, setDefs] = useState<IndicatorDef[]>([]);
  const [dataRows, setDataRows] = useState<DataStatusRow[]>([]);
  const [config, setConfig] = useState<RunConfig>(() => defaultConfig());
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<RunDetailType | null>(null);
  const cancelled = useRef(false);

  useEffect(() => {
    cancelled.current = false;
    fetchIndicators().then(setDefs).catch(() => setDefs([]));
    fetchDataStatus()
      .then((rows) => {
        setDataRows(rows);
        // Prime the builder with the first available symbol/tf, if any.
        if (rows.length > 0) {
          setConfig((c) => ({ ...c, symbol: rows[0].symbol, tf: rows[0].tf }));
        }
      })
      .catch(() => setDataRows([]));
    return () => {
      cancelled.current = true;
    };
  }, []);

  const onRun = async () => {
    setRunning(true);
    setError(null);
    setRun(null);
    setStatus("queued");
    try {
      const { run_id } = await postRun(config);
      for (let i = 0; i < MAX_POLLS; i++) {
        if (cancelled.current) return;
        await new Promise((r) => setTimeout(r, POLL_MS));
        const detail = await fetchRun(run_id);
        setStatus(detail.status);
        if (detail.status === "done") {
          setRun(detail);
          setRunning(false);
          return;
        }
        if (detail.status === "failed") {
          setError(detail.error ?? "run failed");
          setRunning(false);
          return;
        }
      }
      setError("timed out waiting for the run to finish");
      setRunning(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setRunning(false);
    }
  };

  return (
    <div className="flex flex-col gap-10">
      <section className="flex flex-col gap-4">
        <div className="flex items-baseline justify-between">
          <span className="text-xs uppercase tracking-[0.3em] text-fog-faint">
            Page 1 · Manual mode
          </span>
          <span className="text-xs text-fog-faint">
            {defs.length} indicators · {dataRows.length} data series
          </span>
        </div>
        <h1 className="text-3xl font-semibold tracking-tight">Backtest Lab</h1>
        <RunBuilder
          config={config}
          defs={defs}
          dataRows={dataRows}
          running={running}
          onChange={setConfig}
          onRun={onRun}
        />
        {running && (
          <p className="text-sm text-paper">
            <span className="animate-pulse">●</span> {status}…
          </p>
        )}
        {error && (
          <p className="rounded border border-loss/50 bg-loss/10 px-3 py-2 text-sm text-loss">
            {error}
          </p>
        )}
      </section>

      {run && (
        <div className="border-t border-line pt-8">
          <RunDetail run={run} />
        </div>
      )}
    </div>
  );
}
