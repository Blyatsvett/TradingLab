ALL-23 TRADABLE UNIVERSE — STEP 9I V2 / STEP 9I-R V2 / STEP 9J V2
===================================================================

STATUS
------
SIMULATION ONLY. NO ORDER ROUTING. NO AUTOMATIC STRATEGY PROMOTION.

This patch corrects the final tradable architecture:

REGIME SOURCE (11)
- ALFA.ST, ATCO-A.ST, ATCO-B.ST, AZN.ST, BOL.ST, ERIC-B.ST,
  EVO.ST, SAND.ST, SEB-A.ST, SHB-A.ST, SWED-A.ST

TRADABLE CORE 5
- SHB-A.ST, ERIC-B.ST, ALFA.ST, SEB-A.ST, ATCO-A.ST

TRADABLE HOLDOUT 18
- ABB.ST, ASSA-B.ST, VOLV-B.ST, SKF-B.ST, NDA-SE.ST, INVE-B.ST,
  SOBI.ST, GETI-B.ST, ESSITY-B.ST, HM-B.ST, ELUX-B.ST, TEL2-B.ST,
  TELIA.ST, HEXA-B.ST, SSAB-A.ST, SCA-B.ST, CAST.ST, FABG.ST

TOTAL TRADABLE = 23

The Core 5 and Holdout 18 remain separately labelled in reports. All 23 are
eligible for strategy evaluation, but only ticker-contract pairs satisfying the
morning regime, state, group-alignment, volatility, completeness, and guardrail
rules become eligible for EOD trigger evaluation.

WHAT THE PATCH ADDS
-------------------
1. Step 9I V2 prospective shadow router
   - 23 tradable tickers x 8 frozen contracts = 184 morning decisions
   - reuses the existing 29-ticker market-data database
   - uses a NEW immutable ledger: data/step9i_v2_shadow_ledger.db
   - never modifies data/step9i_shadow_ledger.db
   - exports Core 5, Holdout 18, and Combined 23 performance views
   - records leave-one-company-out regime sensitivity for each Core 5 company
     (Atlas Copco removes both A and B source shares for this audit)

2. Step 9I-R V2 historical replay
   - exact morning/EOD replay across all 23 tradable tickers
   - separate historical replay ledger and outputs
   - simulation-only and never confirmatory

3. Step 9J V2 combined-23 challenger research
   - same redesigned Step 9J contracts across all 23 tradable tickers
   - separate Core 5, Holdout 18, and Combined 23 segment performance
   - post-hoc historical discovery only

4. Step 9I V2 preflight
   - writes no morning decision batch
   - checks 29 market-data tickers
   - checks the exact 23-ticker tradable lock
   - reconstructs the 184-row decision grid on the latest available session
   - checks all 23 latest-session 09:40 bars
   - requires the V2 prospective ledger to be empty before the first live seal

INSTALL
-------
Extract the ZIP into:

C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading

Allow new files to be added. Existing V1 files are not replaced.

Windows may block the new PowerShell scripts. Run:

Get-ChildItem . -Filter "*step9*v2*.ps1" | Unblock-File
Unblock-File .\collect_step9i_v2_shadow_data.ps1

TESTS
-----
Run:

.\.venv\Scripts\python.exe -m unittest discover -s tests -v

This patch adds 5 tests.
- Expected after the previously supplied Step 9J patch: Ran 142 tests / OK
- Expected if Step 9J has not been installed: Ran 135 tests / OK

TODAY — SUNDAY 2026-07-26
-------------------------
1. Refresh the shared 29-ticker market-data store:

.\collect_step9i_v2_shadow_data.ps1 -Days 5

2. Run the V2 preflight. It MUST pass before tomorrow:

.\run_step9i_v2_preflight.ps1

Expected central lines:
- 29_market_data_tickers_observed = PASS
- 23_tradable_tickers_locked = PASS
- 184_decision_rows_reconstructed = PASS
- latest_day_has_all_23_0940_bars = PASS
- v2_ledger_empty_before_first_live_day = PASS

3. Run the exact all-23 historical replay:

.\run_step9ir_v2_historical_replay.ps1 `
    -StartDate "2026-05-25" `
    -EndDate "2026-07-24" `
    -ResetReplay

4. Run the Step 9J redesign across all 23:

.\run_step9j_v2_combined23_challenger_redesign.ps1 `
    -StartDate "2026-05-25" `
    -EndDate "2026-07-24"

IMPORTANT: Step 9J results do not change tomorrow's live contracts. Tomorrow's
prospective V2 uses only the frozen eight Step 9I contracts.

TOMORROW — MONDAY 2026-07-27 MORNING
------------------------------------
Near 09:45 Stockholm time:

.\collect_step9i_v2_shadow_data.ps1 -Days 5
.\run_step9i_v2_morning_shadow_router.ps1

The morning seal must occur between 09:45:00 and 09:49:30 Stockholm time.
Do not use -AsOf and do not use -AllowLateReconstruction for the genuine live batch.

Desired result:
- Prospective status : PROSPECTIVE_CONFIRMATORY_ELIGIBLE
- Ledger action      : SEALED_NEW_BATCH
- Decisions          : 184

If the provider has not delivered complete 09:40 bars, no confirmatory batch
should be forced. Missing a day is scientifically better than reconstructing it
and pretending it was prospective.

TOMORROW AFTER CLOSE
--------------------
After approximately 17:35 Stockholm time:

.\collect_step9i_v2_shadow_data.ps1 -Days 5
.\run_step9i_v2_eod_shadow_evaluator.ps1

Then refresh exports:

.\export_step9i_v2_shadow_ledgers.ps1

V2 PROSPECTIVE OUTPUTS
----------------------
- data/step9i_v2_shadow_decision_batches.csv
- data/step9i_v2_shadow_decisions.csv
- data/step9i_v2_shadow_decisions_segmented.csv
- data/step9i_v2_shadow_outcome_batches.csv
- data/step9i_v2_shadow_outcomes.csv
- data/step9i_v2_shadow_outcomes_segmented.csv
- data/step9i_v2_shadow_performance.csv
- data/step9i_v2_shadow_segment_performance.csv
- data/step9i_v2_shadow_multiple_testing.csv
- data/step9i_v2_shadow_audit.csv
- data/step9i_v2_shadow_summary.csv
- data/step9i_v2_shadow_universe_summary.csv
- data/step9i_v2_core5_regime_sensitivity.csv

V2 HISTORICAL REPLAY KEY OUTPUTS
--------------------------------
- data/step9ir_v2_replay_contract_performance.csv
- data/step9ir_v2_replay_segment_performance.csv
- data/step9ir_v2_replay_ticker_performance.csv
- data/step9ir_v2_replay_regime_strategy_matrix.csv
- data/step9ir_v2_replay_core5_regime_sensitivity.csv
- data/step9ir_v2_replay_audit.csv

STEP 9J V2 KEY OUTPUTS
----------------------
- data/step9j_v2_challenger_performance.csv
- data/step9j_v2_segment_performance.csv
- data/step9j_v2_challenger_comparisons.csv
- data/step9j_v2_trade_diagnostics.csv
- data/step9j_v2_ticker_performance.csv
- data/step9j_v2_challenger_audit.csv
- data/step9j_v2_summary.csv

RESEARCH BOUNDARY
-----------------
- V1 remains frozen and untouched.
- V2 starts with a new empty prospective ledger.
- Core 5 is labelled in-sample/original-core evidence historically.
- Holdout 18 remains cross-sectional holdout evidence historically.
- Combined 23 is the intended research tradable universe.
- From the first real V2 morning seal onward, all 23 contribute genuinely
  prospective temporal evidence, while their historical provenance stays visible.
