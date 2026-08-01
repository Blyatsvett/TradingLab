STEP 8 - PROVISIONAL EXHAUSTIVE REGIME TAXONOMY
================================================

Purpose
-------
Assign exactly one primary point-in-time regime and one active simulation response
to every observed session. This is a provisional research taxonomy, not a validated
strategy router.

Critical timing rule
--------------------
The taxonomy uses the Step 7 feature foundation available at 09:45 and therefore
uses start-labelled five-minute bars only through the 09:40 label. No same-day V1
outcome is used for classification.

Step 7B consequence
-------------------
The frozen legacy V1 used the 09:45-labelled bar and had a material timing impact.
It remains preserved for historical comparison but is not eligible for the future
router. RECOVERY maps to STRICT_POINT_IN_TIME_GAP_RECOVERY_V2_RESEARCH.

Exhaustive active-response rule
-------------------------------
There is no NO_TRADE regime. Every observed session receives an active simulation
response. Incomplete data maps to DATA_LIMITED_DEFENSIVE, a minimum-gross liquid
market-neutral research response.

Regimes
-------
RECOVERY
TREND_UP
TREND_DOWN
RANGE_LOW_VOL
HIGH_VOL_REVERSAL
HIGH_DISPERSION
VOLATILITY_EXPANSION
DEFENSIVE_MIXED
DATA_LIMITED_DEFENSIVE

Outputs
-------
data/regime_taxonomy_summary.csv
data/regime_daily_taxonomy.csv
data/regime_taxonomy_definitions.csv
data/regime_taxonomy_distribution.csv
data/regime_taxonomy_transitions.csv

Run
---
.\run_step8_provisional_regime_taxonomy.ps1

The complete .\run_regime_research.ps1 workflow also runs Step 8 automatically.
