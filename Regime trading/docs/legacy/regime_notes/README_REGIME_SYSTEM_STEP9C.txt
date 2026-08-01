REGIME SYSTEM STEP 9C — PLAYBOOK LOSS-DRIVER DIAGNOSTICS
=========================================================

Purpose
-------
Step 9C explains why the unconstrained Step 9B baseline made or lost money.
It is a diagnostic layer, not an optimizer, not a shared-account simulation,
and not a strategy-promotion step.

The output is designed to distinguish among:
- signal-direction failure,
- poor stop/target geometry,
- excessive cost drag,
- weak profit capture after favorable excursion,
- concentration in a few trades or dates,
- pair-direction evidence,
- and samples that are still too small for inference.

Point-in-time and execution treatment
-------------------------------------
- Step 9C does not alter any Step 8 classification or Step 9B trade.
- It reads the already point-in-time-safe Step 9B entries and exits.
- For single-name MFE/MAE, the entry-labelled five-minute bar is excluded
  because the trigger may have occurred inside that bar and its earlier high
  or low cannot safely be attributed to the open trade.
- Excursion metrics use subsequent bars and are bounded by the realized trade
  result when the trade exits inside its entry bar.
- Pair diagnostics use synchronized five-minute closes because pair execution
  in Step 9B is close-observed.
- Post-exit horizon metrics are diagnostics only and never rewrite the trade.

Diagnostics
-----------
1. Trade-level enrichment
   - Actual MFE and MAE while the trade was open
   - MFE/MAE through the playbook time cutoff
   - Return at the original time cutoff
   - Favorable-excursion capture
   - Stopped trades that later recovered
   - Confidence, entry-time, duration, ticker, and direction labels

2. Standardized single-name target controls
   - 0.50R, 0.75R, 1.00R, 1.25R, 1.50R, and 2.00R
   - Same entry, stop, cost, time cutoff, and conservative stop priority
   - These are diagnostic counterfactuals, not optimized replacements

3. Pair-direction controls
   - Baseline direction versus the exact opposite direction
   - Same entry and exit timestamps
   - This isolates direction sign only; it does not re-simulate the opposite
     strategy's own stop and target path

4. Cost sensitivity
   - 0, 1, 2.5, 5, 7.5, and 10 bps round-trip modeled costs
   - Break-even cost by playbook

5. Concentration and robustness
   - Top-trade and top-day P&L shares
   - Leave-one-day-out remaining P&L
   - Diagnostic slices by exit reason, direction, confidence, entry time,
     duration, and ticker/pair

Screening actions
-----------------
Each playbook receives one transparent research action:

    KEEP
    MODIFY
    INVERT
    REPLACE
    INSUFFICIENT_SAMPLE

These labels are screening decisions, not final strategy selections.
A minimum of eight trades is required even for the first descriptive screening
classification. Eight trades is not enough for validation or live use.

Run only Step 9C
----------------
PowerShell from the project root:

    .\run_step9c_playbook_loss_diagnostics.ps1

Run the complete isolated workflow:

    .\run_regime_research.ps1

Tests
-----

    .\.venv\Scripts\python.exe -m unittest discover -s tests -v

Expected suite after this patch:

    Ran 70 tests
    OK

Outputs
-------
- data\regime_playbook_diagnostic_summary.csv
- data\regime_playbook_trade_diagnostics.csv
- data\regime_playbook_diagnostics.csv
- data\regime_playbook_diagnostic_slices.csv
- data\regime_playbook_target_scenarios.csv
- data\regime_playbook_cost_scenarios.csv
- data\regime_playbook_leave_one_day_out.csv
- data\regime_playbook_pair_direction_controls.csv

Success classification
----------------------

    LOSS_DRIVERS_DIAGNOSTIC_READY_FOR_PLAYBOOK_REDESIGN

This means every Step 9B trade was enriched from its intraday price path and
all diagnostic invariants passed. It does not mean any strategy is profitable,
robust, or selected as the final response for its regime.
