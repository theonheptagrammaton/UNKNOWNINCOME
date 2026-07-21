"""Statistical-honesty layer (Faz 9, doc §23).

The discovery pipeline tries tens of thousands of hypotheses and keeps the best;
the best of many is most likely the luckiest of many. This package measures that
luck so it can be subtracted:

* :mod:`app.research.deflation` — the pure Bailey & López de Prado (2014) math:
  expected maximum Sharpe under the null, the Deflated Sharpe Ratio, and PBO/CSCV.
  No DB, no I/O — reference-tested closed forms.
* :mod:`app.research.registry` — the append-only, cross-scan experiment ledger:
  every hypothesis ever tried is one row, so a genome family's *all-time* trial
  count feeds the deflation math (re-optimizing the same idea costs statistically).
* :mod:`app.research.gate` — Aşama 5.5, the non-negotiable hard gate whose
  thresholds are code constants (loosening requires a commit + an audit row).
"""

from __future__ import annotations
