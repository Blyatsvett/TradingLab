STEP 7 - POINT-IN-TIME REGIME FEATURE FOUNDATION
=================================================

Purpose
-------
Build one auditable market-state feature row per observed trading session before
creating any permanent regime labels or routing rules.

This is simulation-only research. It does not modify the frozen Gap Recovery V1
strategy, the production ORB system, paper trading, or live execution.

Core point-in-time rule
-----------------------
The daily decision time is 09:45.

The source contains start-labelled five-minute bars. Therefore:

- 09:30 bar information is available at 09:35
- 09:35 bar information is available at 09:40
- 09:40 bar information is available at 09:45
- 09:45 bar information is NOT available at 09:45 and is excluded

Same-day V1 results are joined only as after-session diagnostics. They are never
eligible classifier inputs.

Run Step 7 only
---------------

  .\run_step7_regime_feature_foundation.ps1

Run the complete research workflow
----------------------------------

  .\run_regime_research.ps1

Outputs
-------

  data\regime_feature_foundation_summary.csv
  data\regime_daily_features.csv
  data\regime_feature_definitions.csv
  data\regime_feature_completeness.csv
  data\regime_point_in_time_audit.csv

The five tables are also exported to data\powerbi_exports.xlsx.

Current feature families
------------------------

- Opening-gap breadth and distribution
- Early direction and market breadth
- Early cross-sectional dispersion
- Opening-range and early realized volatility
- Breadth and median-return acceleration
- Previous-session return, breadth, and dispersion
- Two-, five-, and ten-session trend
- Five- and ten-session volatility and drawdown
- Percentage of stocks above five- and ten-session moving averages
- Consecutive positive and negative sessions

Macro/external backlog
----------------------
The feature definitions table also records planned point-in-time fields for:

- OMX/European/US market context
- VIX
- EUR/SEK
- Swedish rates
- Brent crude
- Scheduled macro releases
- Central-bank events

They are marked AFTER_DATA_EXPANSION and cannot enter the initial classifier.

Readiness labels
----------------

FULL_READY
  Full universe coverage, point-in-time audit pass, and ten-session history.

MINIMUM_READY_HISTORY_BUILDING
  Safe and usable for exploratory regime research, but full history or complete
  universe coverage is still building.

PARTIAL / INSUFFICIENT_CROSS_SECTION
  Not suitable for classifier fitting without review.

POINT_IN_TIME_AUDIT_FAILED
  At least one classifier-eligible feature group failed its timestamp gate.

Next research step
------------------
Step 8 will use only audited, eligible fields to create an exhaustive provisional
regime taxonomy. Every regime will later map to an active simulated strategy,
basket, execution method, and risk profile.
