// Display formatting. Timestamps are UTC internally; the UI renders them in
// Europe/Istanbul (doc §2 rule 5).

const IST = "Europe/Istanbul";

const dateTimeFmt = new Intl.DateTimeFormat("en-GB", {
  timeZone: IST,
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

const dateFmt = new Intl.DateTimeFormat("en-GB", {
  timeZone: IST,
  year: "numeric",
  month: "short",
  day: "2-digit",
});

/** Format a UTC millisecond timestamp as an Istanbul-local date-time. */
export function fmtDateTime(ms: number): string {
  return dateTimeFmt.format(new Date(ms));
}

/** Format a UTC millisecond timestamp as an Istanbul-local date. */
export function fmtDate(ms: number): string {
  return dateFmt.format(new Date(ms));
}

/** A metric that may be null (JSON has no NaN/Inf) → em dash. */
export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** Fraction → percent string, e.g. 0.1234 → "12.34%". */
export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `${(v * 100).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}%`;
}

/** Money with thousands separators. */
export function fmtMoney(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

export function monthLabel(month: number): string {
  return MONTHS[month - 1] ?? String(month);
}
