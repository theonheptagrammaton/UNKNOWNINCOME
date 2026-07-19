import type { MonthlyReturn } from "@/lib/api";
import { fmtPct, monthLabel } from "@/lib/format";

/** Monthly-return heatmap (doc §6.3): year rows × 12 month columns. */
export function MonthlyHeatmap({ data }: { data: MonthlyReturn[] }) {
  if (data.length === 0) {
    return <p className="text-sm text-fog-muted">No monthly data.</p>;
  }
  const years = [...new Set(data.map((d) => d.year))].sort();
  const lookup = new Map<string, number | null>();
  let maxAbs = 0;
  for (const d of data) {
    lookup.set(`${d.year}-${d.month}`, d.return);
    if (d.return !== null && Number.isFinite(d.return)) {
      maxAbs = Math.max(maxAbs, Math.abs(d.return));
    }
  }

  const cellColor = (r: number | null | undefined): string => {
    if (r === null || r === undefined || !Number.isFinite(r) || maxAbs === 0)
      return "transparent";
    const intensity = Math.min(1, Math.abs(r) / maxAbs);
    const alpha = 0.12 + intensity * 0.6;
    return r >= 0
      ? `rgba(63,181,127,${alpha})`
      : `rgba(229,72,77,${alpha})`;
  };

  return (
    <div className="overflow-x-auto">
      <table className="border-separate border-spacing-1 text-xs">
        <thead>
          <tr>
            <th className="px-2 py-1 text-left text-fog-faint"></th>
            {Array.from({ length: 12 }, (_, i) => (
              <th
                key={i}
                className="px-2 py-1 text-center font-medium text-fog-faint"
              >
                {monthLabel(i + 1)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="font-mono">
          {years.map((year) => (
            <tr key={year}>
              <td className="px-2 py-1 text-fog-muted">{year}</td>
              {Array.from({ length: 12 }, (_, i) => {
                const r = lookup.get(`${year}-${i + 1}`);
                const present = r !== undefined;
                return (
                  <td
                    key={i}
                    title={present ? fmtPct(r) : ""}
                    className="h-8 w-14 rounded text-center text-[10px] text-fog"
                    style={{
                      backgroundColor: present ? cellColor(r) : "transparent",
                      border: present
                        ? "1px solid transparent"
                        : "1px solid var(--color-line)",
                    }}
                  >
                    {present && r !== null ? fmtPct(r, 1) : ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
