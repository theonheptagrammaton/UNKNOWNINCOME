import { StatusChip } from "@/components/StatusChip";

export default function TradeDeckPage() {
  return (
    <section className="flex flex-col gap-4">
      <span className="text-xs uppercase tracking-[0.3em] text-fog-faint">
        Page 2
      </span>
      <div className="flex items-center gap-4">
        <h1 className="text-3xl font-semibold tracking-tight">Trade Deck</h1>
        <StatusChip mode="off" />
      </div>
      <p className="max-w-xl text-fog-muted">
        Status strip, portfolio, signal feed and kill switch arrive in Phase 5.
        This is the empty shell.
      </p>
    </section>
  );
}
