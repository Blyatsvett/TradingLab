STEP 7B - STRICT 09:40 VS LEGACY <=09:45 V1 REGIME TIMING
============================================================

Purpose
-------
Quantify whether the frozen Gap Recovery V1 early-market regime used information
from the 09:45-labelled five-minute bar that was not complete at the 09:45
decision time.

The frozen V1 implementation is preserved. This module builds a separate strict
shadow calculation and compares both implementations session by session,
candidate by candidate, trade by trade, and at max-two-position portfolio level.

Comparison
----------

Legacy frozen V1
  Uses bar labels through and including 09:45.

Strict point-in-time shadow
  Uses bar labels through and including 09:40. With start-labelled five-minute
  bars, the 09:40 bar becomes available at 09:45.

The only intended difference is the latest early-regime input bar. Gap rules,
opening range, entry trigger, stop, target, execution logic, costs, position size,
and portfolio capacity remain unchanged.

Run Step 7B only
----------------

  .\run_step7b_v1_regime_timing_comparison.ps1

Run the complete workflow
-------------------------

  .\run_regime_research.ps1

Outputs
-------

  data\regime_v1_timing_comparison_summary.csv
  data\regime_v1_timing_comparison_daily.csv
  data\regime_v1_timing_comparison_candidates.csv
  data\regime_v1_timing_comparison_trades.csv

The four tables are also exported to data\powerbi_exports.xlsx.

Interpretation
--------------

STRICT_0940_AND_LEGACY_0945_IDENTICAL
  No observed regime, trading-action, trade, or portfolio difference.

LABEL_DIFFERENCES_NO_TRADING_IMPACT
  Some detailed regime labels changed, but the favorable gate and all trading
  actions remained unchanged.

LIMITED_V1_TIMING_IMPACT_VERSIONED_FIX_RECOMMENDED
  A small number of actions or a small amount of P&L changed. Preserve V1 and
  create a strict point-in-time V2 for forward simulation.

MATERIAL_V1_TIMING_IMPACT_VERSIONED_FIX_REQUIRED
  The unavailable 09:45-labelled bar materially changed eligibility, trades, or
  portfolio results. V1 remains frozen as historical research, while a strict V2
  must become the point-in-time candidate for the regime-adaptive system.

Step 7 audit clarification
--------------------------
The first observed session has no earlier session in the local dataset. This is
now reported as NOT_APPLICABLE_NO_PRIOR_SESSION rather than a failed timestamp
audit. It remains history-limited, but it is not look-ahead leakage.

Safety boundary
---------------
- Simulation only.
- No production ORB files.
- No live or paper orders.
- Frozen Gap Recovery V1 is not modified.
