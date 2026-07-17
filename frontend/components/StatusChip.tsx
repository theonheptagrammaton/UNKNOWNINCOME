import { modeLabel, type Mode } from "@/lib/mode";

const styles: Record<Mode, string> = {
  live: "border-live/40 text-live",
  paper: "border-paper/40 text-paper",
  off: "border-off/40 text-off",
};

/** Compact mode indicator for the Trade Deck status strip. */
export function StatusChip({ mode }: { mode: Mode }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium uppercase tracking-wider ${styles[mode]}`}
    >
      {modeLabel(mode)}
    </span>
  );
}
