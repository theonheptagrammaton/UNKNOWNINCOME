"use client";

import { useMemo, useState } from "react";

import type { IndicatorDef } from "@/lib/api";

/** Searchable, category-grouped indicator selector (doc §10.1 manual mode). */
export function IndicatorPicker({
  indicators,
  value,
  onChange,
}: {
  indicators: IndicatorDef[];
  value: string;
  onChange: (id: string) => void;
}) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);

  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const filtered = indicators.filter(
      (d) =>
        !needle ||
        d.id.includes(needle) ||
        d.name.toLowerCase().includes(needle) ||
        d.category.includes(needle),
    );
    const by: Record<string, IndicatorDef[]> = {};
    for (const d of filtered) (by[d.category] ??= []).push(d);
    return Object.entries(by).sort(([a], [b]) => a.localeCompare(b));
  }, [indicators, q]);

  const selected = indicators.find((d) => d.id === value);

  return (
    <div className="relative">
      <input
        value={open ? q : selected ? `${selected.id} · ${selected.name}` : q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => {
          setOpen(true);
          setQ("");
        }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="search indicator…"
        className="w-full rounded border border-line bg-void px-3 py-2 text-sm text-fog outline-none focus:border-fog-faint"
      />
      {open && (
        <div className="absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded border border-line bg-graphite shadow-xl">
          {groups.length === 0 && (
            <p className="px-3 py-2 text-xs text-fog-faint">no matches</p>
          )}
          {groups.map(([category, defs]) => (
            <div key={category}>
              <div className="sticky top-0 bg-graphite-2 px-3 py-1 text-[10px] uppercase tracking-wider text-fog-faint">
                {category}
              </div>
              {defs.map((d) => (
                <button
                  key={d.id}
                  type="button"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    onChange(d.id);
                    setOpen(false);
                  }}
                  className={`flex w-full items-center justify-between px-3 py-1.5 text-left text-sm hover:bg-graphite-2 ${
                    d.id === value ? "text-fog" : "text-fog-muted"
                  }`}
                >
                  <span className="font-mono">{d.id}</span>
                  <span className="ml-2 truncate text-xs text-fog-faint">
                    {d.name}
                  </span>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
