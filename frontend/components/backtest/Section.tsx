import type { ReactNode } from "react";

/** A titled data panel — the Silent Luxury shell around dense content. */
export function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-fog">
          {title}
        </h3>
        {subtitle && (
          <span className="text-xs text-fog-faint">{subtitle}</span>
        )}
      </div>
      {children}
    </section>
  );
}
