export type Mode = "live" | "paper" | "off";

/**
 * Human label for a bot mode. The effective mode is the lower of the global
 * and per-strategy switches: Off < Paper < Live (doc §9.6).
 */
export function modeLabel(mode: Mode): string {
  const labels: Record<Mode, string> = {
    live: "Live",
    paper: "Paper",
    off: "Off",
  };
  return labels[mode];
}
