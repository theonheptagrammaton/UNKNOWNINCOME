import type { Trade } from "@/lib/api";
import { fmtDateTime, fmtMoney, fmtNum, fmtPct } from "@/lib/format";

/** Realized round-trip trades (doc §6). Rows are clickable to focus the chart. */
export function TradesTable({
  trades,
  selectedIndex = null,
  onSelect,
}: {
  trades: Trade[];
  selectedIndex?: number | null;
  onSelect?: (index: number | null) => void;
}) {
  if (trades.length === 0) {
    return (
      <p className="text-sm text-fog-muted">No trades were taken in this run.</p>
    );
  }
  const clickable = Boolean(onSelect);
  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="w-full min-w-[820px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-fog-faint">
            <th className="px-3 py-2 font-medium">#</th>
            <th className="px-3 py-2 font-medium">Side</th>
            <th className="px-3 py-2 font-medium">Entry</th>
            <th className="px-3 py-2 font-medium">Exit</th>
            <th className="px-3 py-2 text-right font-medium">Entry px</th>
            <th className="px-3 py-2 text-right font-medium">Exit px</th>
            <th className="px-3 py-2 text-right font-medium">Bars</th>
            <th className="px-3 py-2 text-right font-medium">Fees</th>
            <th className="px-3 py-2 text-right font-medium">Funding</th>
            <th className="px-3 py-2 text-right font-medium">Net P&amp;L</th>
            <th className="px-3 py-2 text-right font-medium">Return</th>
          </tr>
        </thead>
        <tbody className="font-mono">
          {trades.map((t, i) => {
            const win = t.net_pnl >= 0;
            const selected = selectedIndex === i;
            return (
              <tr
                key={i}
                onClick={
                  onSelect ? () => onSelect(selected ? null : i) : undefined
                }
                title={clickable ? "Click to focus the chart on this trade" : undefined}
                className={`border-b border-line/60 last:border-0 ${
                  clickable ? "cursor-pointer" : ""
                } ${selected ? "bg-graphite ring-1 ring-inset ring-paper/50" : "hover:bg-graphite"}`}
              >
                <td className="px-3 py-2 text-fog-faint">{i + 1}</td>
                <td className="px-3 py-2">
                  <span
                    className={
                      t.side === "long" ? "text-profit" : "text-loss"
                    }
                  >
                    {t.side}
                  </span>
                </td>
                <td className="px-3 py-2 text-fog-muted">
                  {fmtDateTime(t.entry_ts)}
                </td>
                <td className="px-3 py-2 text-fog-muted">
                  {fmtDateTime(t.exit_ts)}
                  {t.liquidated && (
                    <span
                      className="ml-1 rounded bg-loss/15 px-1 text-[10px] uppercase text-loss"
                      title="Force-closed at the isolated-margin liquidation price"
                    >
                      liq
                    </span>
                  )}
                  {t.forced && !t.liquidated && (
                    <span className="ml-1 text-[10px] uppercase text-fog-faint">
                      eod
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right">{fmtNum(t.entry_price)}</td>
                <td className="px-3 py-2 text-right">{fmtNum(t.exit_price)}</td>
                <td className="px-3 py-2 text-right text-fog-muted">
                  {t.bars_held}
                </td>
                <td className="px-3 py-2 text-right text-fog-muted">
                  {fmtMoney(t.commission)}
                </td>
                <td className="px-3 py-2 text-right text-fog-muted">
                  {fmtMoney(t.funding)}
                </td>
                <td
                  className={`px-3 py-2 text-right ${win ? "text-profit" : "text-loss"}`}
                >
                  {fmtMoney(t.net_pnl)}
                </td>
                <td
                  className={`px-3 py-2 text-right ${win ? "text-profit" : "text-loss"}`}
                >
                  {fmtPct(t.return_pct)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
