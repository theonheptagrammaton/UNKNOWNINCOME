import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "UNKNOWNINCOME",
  description: "Autonomous backtest & trading system",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-void text-fog antialiased">
        <div className="mx-auto flex min-h-screen max-w-6xl flex-col px-6">
          <header className="flex items-center justify-between border-b border-line py-5">
            <Link
              href="/"
              className="text-sm font-semibold tracking-[0.2em] text-fog"
            >
              UNKNOWNINCOME
            </Link>
            <nav className="flex gap-6 text-sm text-fog-muted">
              <Link href="/backtest" className="transition-colors hover:text-fog">
                Backtest Lab
              </Link>
              <Link href="/trade" className="transition-colors hover:text-fog">
                Trade Deck
              </Link>
            </nav>
          </header>
          <main className="flex-1 py-12">{children}</main>
          <footer className="border-t border-line py-5 text-xs text-fog-faint">
            Phase 0 — skeleton · UTC internally, Europe/Istanbul in UI
          </footer>
        </div>
      </body>
    </html>
  );
}
