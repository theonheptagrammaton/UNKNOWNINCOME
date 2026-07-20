"use client";

import type { Primitive, RuleClause } from "@/lib/api";

type Field = {
  name: string;
  kind: "operand" | "number" | "text" | "enum";
  options?: string[];
};

// Argument schema per §5.4 primitive — drives the dynamic form fields.
const PRIMITIVE_ARGS: Record<Primitive, Field[]> = {
  line_cross: [
    { name: "a", kind: "operand" },
    { name: "b", kind: "operand" },
    { name: "direction", kind: "enum", options: ["up", "down", "cross"] },
  ],
  threshold_cross: [
    { name: "x", kind: "operand" },
    { name: "level", kind: "number" },
    { name: "direction", kind: "enum", options: ["up", "down", "cross"] },
  ],
  slope: [
    { name: "x", kind: "operand" },
    { name: "lookback", kind: "number" },
    { name: "direction", kind: "enum", options: ["up", "down", "flat"] },
  ],
  band_touch: [
    { name: "price", kind: "operand" },
    { name: "upper", kind: "operand" },
    { name: "lower", kind: "operand" },
    {
      name: "mode",
      kind: "enum",
      options: [
        "touch_upper", "touch_lower", "break_upper",
        "break_lower", "revert_upper", "revert_lower",
      ],
    },
  ],
  regime: [
    { name: "x", kind: "operand" },
    { name: "rule", kind: "text" },
  ],
  pattern: [
    { name: "series", kind: "operand" },
    { name: "direction", kind: "enum", options: ["any", "bullish", "bearish"] },
  ],
};

const PRIMITIVES = Object.keys(PRIMITIVE_ARGS) as Primitive[];

/** Names of the operand-kind args for a primitive (empty for unknown/plugin ones). */
export function operandArgNames(primitive: string): string[] {
  const fields = PRIMITIVE_ARGS[primitive as Primitive];
  return fields ? fields.filter((f) => f.kind === "operand").map((f) => f.name) : [];
}

function defaultArgs(primitive: Primitive, operands: string[]): RuleClause["args"] {
  const args: RuleClause["args"] = {};
  for (const f of PRIMITIVE_ARGS[primitive]) {
    if (f.kind === "operand") args[f.name] = operands[0] ?? "close";
    else if (f.kind === "number") args[f.name] = f.name === "level" ? 0 : 1;
    else if (f.kind === "enum") args[f.name] = f.options![0];
    else args[f.name] = "gt:0";
  }
  return args;
}

const inputCls =
  "rounded border border-line bg-void px-2 py-1 text-xs text-fog outline-none focus:border-fog-faint";

/** Edit one entry/exit clause list (AND-combined signal primitives). */
export function RuleBuilder({
  label,
  clauses,
  operands,
  onChange,
}: {
  label: string;
  clauses: RuleClause[];
  operands: string[];
  onChange: (clauses: RuleClause[]) => void;
}) {
  const update = (i: number, next: RuleClause) =>
    onChange(clauses.map((c, j) => (j === i ? next : c)));
  const remove = (i: number) => onChange(clauses.filter((_, j) => j !== i));
  const add = () =>
    onChange([...clauses, { primitive: "line_cross", args: defaultArgs("line_cross", operands) }]);

  return (
    <div className="flex flex-col gap-2 rounded border border-line bg-graphite p-3">
      <div className="flex items-center justify-between">
        <span className="text-xs uppercase tracking-wider text-fog-muted">
          {label}
        </span>
        <button
          type="button"
          onClick={add}
          className="text-xs text-fog-faint hover:text-fog"
        >
          + clause
        </button>
      </div>
      {clauses.length === 0 && (
        <p className="text-xs text-fog-faint">no clauses — never triggers</p>
      )}
      {clauses.map((clause, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2">
          <select
            value={clause.primitive}
            onChange={(e) => {
              const p = e.target.value as Primitive;
              update(i, { primitive: p, args: defaultArgs(p, operands) });
            }}
            className={inputCls}
          >
            {PRIMITIVES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          {PRIMITIVE_ARGS[clause.primitive].map((f) => {
            const val = clause.args[f.name];
            const setVal = (v: string | number) =>
              update(i, { ...clause, args: { ...clause.args, [f.name]: v } });
            if (f.kind === "operand") {
              const cur = String(val);
              // A referenced operand can go stale (indicator renamed/removed or
              // switched to multi-output). Surface it as a marked option instead
              // of silently mismatching the <select>, so the user can re-pick.
              const dangling = cur !== "" && !operands.includes(cur);
              return (
                <select
                  key={f.name}
                  value={cur}
                  onChange={(e) => setVal(e.target.value)}
                  className={`${inputCls} ${dangling ? "border-loss text-loss" : ""}`}
                  title={f.name}
                >
                  {dangling && <option value={cur}>{cur} (unknown)</option>}
                  {operands.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
              );
            }
            if (f.kind === "enum") {
              return (
                <select
                  key={f.name}
                  value={String(val)}
                  onChange={(e) => setVal(e.target.value)}
                  className={inputCls}
                  title={f.name}
                >
                  {f.options!.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
              );
            }
            if (f.kind === "number") {
              return (
                <input
                  key={f.name}
                  type="number"
                  value={Number(val)}
                  onChange={(e) => setVal(Number(e.target.value))}
                  className={`${inputCls} w-20`}
                  title={f.name}
                />
              );
            }
            return (
              <input
                key={f.name}
                value={String(val)}
                onChange={(e) => setVal(e.target.value)}
                className={`${inputCls} w-24`}
                title={f.name}
                placeholder="gt:25"
              />
            );
          })}
          <button
            type="button"
            onClick={() => remove(i)}
            className="text-xs text-fog-faint hover:text-loss"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
