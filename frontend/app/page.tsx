import Link from "next/link";

export default function Home() {
  return (
    <section className="flex flex-col gap-8">
      <div className="flex flex-col gap-3">
        <h1 className="text-3xl font-semibold tracking-tight">Control surface</h1>
        <p className="max-w-xl text-fog-muted">
          Two surfaces: research strategies in the Lab, run them in the Deck.
          Luxury is the absence of noise, not the absence of data.
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Link
          href="/backtest"
          className="rounded-lg border border-line bg-graphite p-6 transition-colors hover:border-fog-faint"
        >
          <h2 className="text-lg font-medium">Backtest Lab →</h2>
          <p className="mt-2 text-sm text-fog-muted">
            Discover, score and validate strategies.
          </p>
        </Link>
        <Link
          href="/trade"
          className="rounded-lg border border-line bg-graphite p-6 transition-colors hover:border-fog-faint"
        >
          <h2 className="text-lg font-medium">Trade Deck →</h2>
          <p className="mt-2 text-sm text-fog-muted">
            Live / Paper / Off. Signals, positions, kill switch.
          </p>
        </Link>
      </div>
    </section>
  );
}
