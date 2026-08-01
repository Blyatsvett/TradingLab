STEP 9I - PROSPECTIVE SHADOW ROUTER AND IMMUTABLE LEDGERS
=========================================================

STATUS
------
SIMULATION ONLY. NO ORDER ROUTING. NO STRATEGY PROMOTION.

Step 9H remains frozen. Step 9I reuses its locked:
- 18-company cross-sectional holdout universe
- three primary contracts
- two fixed complements
- one same-cohort execution comparator
- two negative guardrails

Step 9I does not optimize or change any Step 9H contract.

PURPOSE
-------
Step 9I creates a genuinely forward shadow record in two stages:

1. MORNING DECISION SEAL
   - uses only completed start-labelled 5-minute bars through 09:40
   - assigns the frozen market regime
   - records every contract x holdout-ticker decision, including no-trade reasons
   - writes an immutable morning batch before any eligible 09:50 entry

2. END-OF-DAY OUTCOME SEAL
   - reads the morning ledger without modifying it
   - evaluates only ticker-contract pairs that were eligible in the morning
   - records hypothetical trades, counterfactual guardrail trades, and no-trigger outcomes
   - writes a separate immutable outcome batch

DATABASES
---------
data/step9i_shadow_intraday_prices.db
    Separate 29-ticker market-data store:
    - 11 original regime-source tickers
    - 18 locked Step 9H holdout tickers

    The collector can bootstrap from the original source DB and the Step 9H
    holdout DB. Those source databases remain read-only.

data/step9i_shadow_ledger.db
    Immutable decision and outcome source of truth.

    Tables:
    - shadow_decision_batches
    - shadow_decisions
    - shadow_outcome_batches
    - shadow_outcomes

IMMUTABILITY RULE
-----------------
A rerun of an already sealed session returns the existing batch. It never
rewrites the morning decision or the end-of-day outcome.

If an attempted insert conflicts with a stored payload hash, Step 9I raises an
ImmutableLedgerConflict and changes nothing.

PROSPECTIVE TIMING RULE
-----------------------
A morning batch receives confirmatory status only when it is actually sealed:

    09:45:00 through 09:49:30 Europe/Stockholm

The earliest intended simulated entry is 09:50, so the decision must be sealed
before that point.

Important:
- A run after 09:49:30 is rejected by default.
- -AllowLateReconstruction permits a clearly labelled non-confirmatory ledger.
- Any use of -AsOf is automatically labelled SIMULATED_CLOCK_RECONSTRUCTION_NOT_CONFIRMATORY.
- Historical and late reconstructions never enter prospective performance statistics.
- If Yahoo or another provider does not deliver the 09:40 bars before the seal
  deadline, no confirmatory batch is created. Step 9I does not pretend delayed
  data was available prospectively.

INSTALLATION
------------
Extract the patch into the existing project root:

C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading

Allow new files to be added. Step 9H files are not replaced by this patch.

Run the full regression suite:

.\.venv\Scripts\python.exe -m unittest discover -s tests -v

Expected after this patch:

Ran 121 tests
OK

ONE-TIME DATA INITIALIZATION
----------------------------
Run:

.\collect_step9i_shadow_data.ps1 -Days 59

This:
- copies available original-regime history from the read-only source DB
- copies available holdout history from the read-only Step 9H DB
- downloads/upserts recent bars for all 29 tickers
- writes only to data/step9i_shadow_intraday_prices.db

DAILY MORNING ROUTINE
---------------------
Near 09:45 Stockholm time:

.\collect_step9i_shadow_data.ps1 -Days 5
.\run_step9i_morning_shadow_router.ps1

A successful true prospective seal should report:

Prospective status : PROSPECTIVE_CONFIRMATORY_ELIGIBLE
Ledger action      : SEALED_NEW_BATCH

If data is not ready, the ledger is not sealed. Retry before 09:49:30.

Do not use -AsOf for a real prospective day. That option exists only for
reconstruction and deterministic testing and is automatically non-confirmatory.

LATE RECONSTRUCTION
-------------------
For operational diagnosis only:

.\run_step9i_morning_shadow_router.ps1 -AllowLateReconstruction

The resulting batch is permanently labelled:

LATE_RECONSTRUCTION_NOT_CONFIRMATORY

It is excluded from the prospective evidence table.

DAILY END-OF-DAY ROUTINE
------------------------
After 17:35 Stockholm time, refresh bars and evaluate:

.\collect_step9i_shadow_data.ps1 -Days 5
.\run_step9i_eod_shadow_evaluator.ps1

The evaluator refuses to seal if an eligible ticker lacks bars through 16:25.
It also refuses to seal if its reconstructed eligibility differs from the
immutable morning ledger.

EXPORTS
-------
The SQLite ledger is the source of truth. CSV files are replaceable exports:

- data/step9i_shadow_decision_batches.csv
- data/step9i_shadow_decisions.csv
- data/step9i_shadow_outcome_batches.csv
- data/step9i_shadow_outcomes.csv
- data/step9i_shadow_contract_registry.csv
- data/step9i_shadow_performance.csv
- data/step9i_shadow_multiple_testing.csv
- data/step9i_shadow_audit.csv
- data/step9i_shadow_summary.csv

Refresh them without changing the ledger:

.\export_step9i_shadow_ledgers.ps1

PRE-REGISTERED STEP 9I REVIEW GATES
-----------------------------------
A primary positive contract or negative guardrail can become ready for human
confirmatory review only after all applicable conditions are met:

- at least 30 prospective trades
- at least 15 prospective sessions
- at least 10 independent companies
- at least 4 independent sectors
- intended P&L direction after costs
- intended profit-factor direction
- date-clustered 95% bootstrap interval entirely in the intended direction
- company-clustered 95% bootstrap interval entirely in the intended direction
- leave-one-date result remains in the intended direction
- leave-one-company result remains in the intended direction
- leave-one-sector result remains in the intended direction
- BH-adjusted q <= 0.10 across the three primary contracts

Controls and the execution comparator cannot pass an advancement gate.

Even a gate-passing result only receives:

READY_FOR_HUMAN_CONFIRMATORY_REVIEW

Step 9I never activates the router automatically.

AUDITS
------
Step 9I exports checks for:
- immutable decision hashes
- immutable outcome hashes
- every outcome having a prior morning decision
- no ineligible morning decision producing a trade
- every confirmatory morning batch being sealed before 09:49:30
- router remaining inactive

RESEARCH BOUNDARY
-----------------
The Step 9I ledger must remain untouched once prospective collection starts.
New hypotheses, thresholds, providers, execution rules, or universes require a
new versioned experiment rather than modification of this ledger.
