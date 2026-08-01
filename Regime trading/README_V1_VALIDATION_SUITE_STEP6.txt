V1 RESEARCH VALIDATION SUITE - STEP 6
=====================================

Module
------
Exposure and capital-efficiency report for:
REGIME_AWARE_GAP_RECOVERY_V1

Research-only status
--------------------
This module does not change V1 selection, entries, exits, stops, targets,
regimes, costs, portfolio capacity, production ORB code, or paper trading.
It measures the selected max-two-position portfolio produced by Step 1.

Measurement window
------------------
Each research date is observed from 09:45 through 16:30, or through the
latest available bar when a session is incomplete.

An open selected position is counted as deployed capital only through the
latest observed bar. It contributes no unrealized PnL.

Main outputs
------------
data\v1_validation_exposure_efficiency_summary.csv
data\v1_validation_exposure_position_detail.csv
data\v1_validation_exposure_interval_detail.csv
data\v1_validation_exposure_daily.csv
data\v1_validation_position_size_scenarios.csv

Important definitions
---------------------
Average deployed capital:
  sum(position size * elapsed exposure time)
  divided by total observed strategy time.

Account capital utilization:
  average deployed capital / 10,000 SEK account capital.

Slot capacity utilization:
  average deployed capital / 2,000 SEK maximum V1 deployment.

Return on average deployed capital:
  realized PnL / time-weighted average deployed capital.

The last metric is a capital-turnover efficiency measure. It is not a
standalone expected investment return and must not be interpreted as a
forecast. It can look high when positions are brief and capital is recycled.

Position-size scenarios
-----------------------
The scenario table scales the same selected trades linearly from 1,000 SEK
to 5,000 SEK per position. Selection is unchanged and there is no compounding.
The scenarios do not model liquidity deterioration or size-dependent slippage.
They are research illustrations, not position-size recommendations.

Run Step 6 only
---------------
.\run_v1_validation_step6.ps1

Run all validation modules
--------------------------
.\run_v1_validation_suite.ps1

Run the complete research workflow
----------------------------------
.\run_regime_research.ps1

Expected unit tests after this patch
------------------------------------
24 tests, all passing.
