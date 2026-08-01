REGIME SYSTEM STEP 9B — BASELINE PLAYBOOK TRADE GENERATION
===========================================================

Purpose
-------
Step 9B converts the Step 9A executable contracts into unconstrained,
mechanical baseline trade simulations. It is a diagnostic generation step,
not a profitability validation and not a shared-account portfolio backtest.

Point-in-time boundary
----------------------
- Router decision time: 09:45
- Latest router input bar label: 09:40
- Start-labelled five-minute bars
- Bars from 09:45 onward may be observed only for signal execution, stops,
  targets, and time exits.
- Close-confirmed signals, such as range re-entry, enter at the next bar open.
- Same-bar stop/target ambiguity uses conservative STOP priority.
- Two-sided volatility breaks that hit both boundaries in one five-minute bar
  are marked ambiguous rather than assigned a fabricated direction.

Scope
-----
- Generates candidates and selected ideas under the playbook-specific limit.
- Generates closed baseline trades and leg-level P&L.
- Uses the Step 9A regime risk multiplier for unconstrained notional sizing.
- Applies the existing 5 bps round-trip baseline cost per leg.
- Reconciles every trade exactly to its leg ledger.
- Produces one timing and execution audit row per taxonomy session.
- Does not combine strategies into one shared cash/capacity account yet.
- Does not promote, freeze, or recommend any playbook.

Pair interpretation refinement
------------------------------
The Step 9A pair language is made mechanically coherent:
- HIGH_DISPERSION: long strongest / short weakest, testing relative-strength
  continuation.
- DEFENSIVE_MIXED: long weaker / short stronger, testing controlled convergence.
- DATA_LIMITED_DEFENSIVE: deterministic minimum-gross hedge with no directional
  inference.

Run only Step 9B
----------------
PowerShell from the project root:

    .\run_step9b_baseline_trade_generation.ps1

Run the complete isolated workflow:

    .\run_regime_research.ps1

Tests
-----

    .\.venv\Scripts\python.exe -m unittest discover -s tests -v

Expected suite after this patch:

    Ran 65 tests
    OK

Outputs
-------
- data\regime_playbook_baseline_summary.csv
- data\regime_playbook_baseline_sessions.csv
- data\regime_playbook_baseline_candidates.csv
- data\regime_playbook_baseline_trades.csv
- data\regime_playbook_baseline_trade_legs.csv
- data\regime_playbook_baseline_performance.csv
- data\regime_playbook_baseline_audit.csv

Success classification
----------------------

    BASELINE_TRADE_GENERATION_READY_FOR_DIAGNOSTIC_REVIEW

This success state means the mechanics, timing audit, and trade/leg
reconciliation passed. It does not mean the combined P&L is positive or that
any individual regime playbook is robust.
