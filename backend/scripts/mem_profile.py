"""RSS memory profiler for the 72 h paper soak (Faz 8, doc §22.1-4).

Samples a process's resident set size (RSS) over time and decides *flat vs leak* from
the slope of a least-squares fit. Uses ``ps -o rss=`` so there is **no new dependency**
(psutil is not installed) and it works on both Linux (the soak host) and macOS.

    # sample the worker for 72 h, one reading a minute
    python -m scripts.mem_profile --pid $(pgrep -f 'arq app.workers') --hours 72

    # or analyze a CSV captured earlier
    python -m scripts.mem_profile --analyze rss_soak.csv

Verdict heuristic: over the whole run, a leak shows a sustained positive slope. We
call it a **leak** if the fitted growth exceeds ~2 %/hour of the mean RSS *and* the
last-quartile mean is meaningfully above the first-quartile mean; otherwise **flat**.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
from pathlib import Path


def read_rss_kb(pid: int) -> int | None:
    """Resident set size of ``pid`` in KB, or ``None`` if the process is gone."""
    try:
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:  # noqa: BLE001
        return None
    text = out.stdout.strip()
    if not text:
        return None
    try:
        return int(text.split()[0])
    except (ValueError, IndexError):
        return None


def _linfit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Least-squares (slope, intercept) — no numpy needed."""
    n = len(xs)
    if n < 2:
        return 0.0, ys[0] if ys else 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0, my
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False)) / denom
    return slope, my - slope * mx


def analyze(hours: list[float], rss_kb: list[float]) -> str:
    """Return a human verdict line from parallel (hours, rss) samples."""
    if len(rss_kb) < 3:
        return f"insufficient samples ({len(rss_kb)}) — need ≥3 to judge"
    slope_kb_per_h, _ = _linfit(hours, rss_kb)
    mean_kb = sum(rss_kb) / len(rss_kb)
    q = max(1, len(rss_kb) // 4)
    first_q = sum(rss_kb[:q]) / q
    last_q = sum(rss_kb[-q:]) / q
    growth_pct_per_h = (slope_kb_per_h / mean_kb * 100.0) if mean_kb else 0.0
    drift_pct = ((last_q - first_q) / first_q * 100.0) if first_q else 0.0
    leak = growth_pct_per_h > 2.0 and drift_pct > 5.0
    verdict = "LEAK SUSPECTED" if leak else "FLAT"
    return (
        f"{verdict}: {len(rss_kb)} samples over {hours[-1] - hours[0]:.1f}h · "
        f"mean={mean_kb / 1024:.1f}MB · slope={slope_kb_per_h / 1024:+.3f}MB/h "
        f"({growth_pct_per_h:+.2f}%/h) · q1→q4 drift={drift_pct:+.1f}%"
    )


def sample_loop(pid: int, interval: float, hours: float, out_path: Path) -> str:
    """Sample RSS every ``interval`` s for ``hours`` h, appending to a CSV."""
    deadline = time.time() + hours * 3600.0
    hs: list[float] = []
    rss: list[float] = []
    start = time.time()
    new_file = not out_path.exists()
    with out_path.open("a", newline="") as fh:
        writer = csv.writer(fh)
        if new_file:
            writer.writerow(["unix_ts", "hours", "rss_kb"])
        while time.time() < deadline:
            kb = read_rss_kb(pid)
            if kb is None:
                print(f"pid {pid} gone — stopping", file=sys.stderr)
                break
            now = time.time()
            h = (now - start) / 3600.0
            writer.writerow([f"{now:.0f}", f"{h:.4f}", kb])
            fh.flush()
            hs.append(h)
            rss.append(float(kb))
            if len(rss) % 10 == 0:
                print(f"  {h:6.2f}h  rss={kb / 1024:8.1f}MB", flush=True)
            time.sleep(interval)
    return analyze(hs, rss)


def analyze_csv(path: Path) -> str:
    hs: list[float] = []
    rss: list[float] = []
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            hs.append(float(row["hours"]))
            rss.append(float(row["rss_kb"]))
    return analyze(hs, rss)


def main() -> int:
    parser = argparse.ArgumentParser(description="Faz 8 RSS memory profiler")
    parser.add_argument("--pid", type=int, help="process id to sample")
    parser.add_argument("--interval", type=float, default=60.0, help="seconds between samples")
    parser.add_argument("--hours", type=float, default=72.0, help="how long to sample")
    parser.add_argument("--out", default="rss_soak.csv", help="CSV output path")
    parser.add_argument("--analyze", help="analyze an existing CSV and exit")
    args = parser.parse_args()

    if args.analyze:
        print(analyze_csv(Path(args.analyze)))
        return 0
    if not args.pid:
        parser.error("--pid is required unless --analyze is given")
    print(f"sampling pid={args.pid} every {args.interval:.0f}s for {args.hours:.1f}h → {args.out}")
    verdict = sample_loop(args.pid, args.interval, args.hours, Path(args.out))
    print("\n" + verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
