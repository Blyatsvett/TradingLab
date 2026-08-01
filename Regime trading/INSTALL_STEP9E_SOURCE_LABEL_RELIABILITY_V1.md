# Install and verify

Run from VS Code PowerShell. Do not rerun the already sealed July 28 morning engines.

## 1. Activate the environment

```powershell
cd "C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading"
.\.venv\Scripts\Activate.ps1
```

## 2. Verify the downloaded patch hash

```powershell
$Patch = "$env:USERPROFILE\Downloads\pre_step9s_step9e_source_label_reliability_patch_v1_20260728.zip"
$HashFile = "$Patch.sha256"
$ExpectedHash = ((Get-Content $HashFile -Raw).Split()[0]).ToLower()
$ActualHash = (Get-FileHash -Algorithm SHA256 $Patch).Hash.ToLower()
if ($ActualHash -ne $ExpectedHash) {
    throw "Patch SHA-256 mismatch. Expected $ExpectedHash but found $ActualHash"
}
$ActualHash
```

## 3. Back up the two files that will be replaced

```powershell
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Backup = Join-Path $PWD "patch_backups\step9e_source_label_reliability_$Stamp"
New-Item -ItemType Directory -Force "$Backup\RegimeTrading\scripts" | Out-Null
New-Item -ItemType Directory -Force "$Backup\tests" | Out-Null
Copy-Item "RegimeTrading\scripts\step9e_instrument_sector_taxonomy.py" "$Backup\RegimeTrading\scripts\"
Copy-Item "tests\test_step9e_instrument_sector_taxonomy.py" "$Backup\tests\"
Write-Host "Backup created at: $Backup"
```

## 4. Install the patch

```powershell
Expand-Archive -Path $Patch -DestinationPath $PWD -Force
```

Only these executable/test files are installed:

- `RegimeTrading\scripts\step9e_instrument_sector_taxonomy.py`
- `tests\test_step9e_instrument_sector_taxonomy.py`
- `tools\verify_step9e_source_label_reliability.py`

No database is included.

## 5. Run the targeted regression tests

```powershell
python -m pytest -q tests\test_step9e_instrument_sector_taxonomy.py
```

Expected final line:

```text
10 passed
```

## 6. Run isolated real-data validation

These commands use temporary ledgers and a temporary workbook. They do not rerun or write the real Step 9I/Step 9L ledgers.

```powershell
python tools\verify_step9e_source_label_reliability.py step9i
python tools\verify_step9e_source_label_reliability.py step9l
python tools\verify_step9e_source_label_reliability.py step9q
```

Each command must end with:

```text
PROTECTED_DATABASE_HASHES: UNCHANGED
No real ledger was written and no order was sent.
```

## 7. Run the complete suite in stable groups

```powershell
python -m pytest -q `
  tests\test_step7_regime_feature_foundation.py `
  tests\test_step7b_v1_regime_timing_comparison.py `
  tests\test_step8_provisional_regime_taxonomy.py `
  tests\test_step9_playbook_specifications.py `
  tests\test_step9b_baseline_trade_generation.py `
  tests\test_step9c_playbook_loss_diagnostics.py `
  tests\test_step9d_regime_strategy_challenger_matrix.py `
  tests\test_step9e_instrument_sector_taxonomy.py `
  tests\test_step9f_sector_ticker_strategy_experiments.py `
  tests\test_step9g_state_filtered_contract_experiments.py `
  tests\test_step9h_cross_sectional_holdout_transport.py

python -m pytest -q `
  tests\test_step9i_prospective_shadow_router.py `
  tests\test_step9i_v2_core5_plus_holdout18.py `
  tests\test_step9ir_historical_walk_forward_replay.py `
  tests\test_step9j_challenger_regime_strategy_redesign.py `
  tests\test_step9k_high_dispersion_strategy_research.py `
  tests\test_step9l_compare_step9i_v2.py `
  tests\test_step9l_selected_strategy_shadow_engine.py `
  tests\test_step9l_v2_compare_step9i_v2.py `
  tests\test_step9l_v2_selected_strategy_shadow_engine.py `
  tests\test_step9l_v3_compare_step9i_v2.py `
  tests\test_step9l_v3_selected_strategy_shadow_engine.py

python -m pytest -q `
  tests\test_step9m_high_vol_reversal_strategy_research.py `
  tests\test_step9n_trend_regimes_strategy_research.py `
  tests\test_step9o_trend_asymmetry_catchup_study.py

python -m pytest -q `
  tests\test_step9q_b_lite_live_trade_feed.py `
  tests\test_step9q_powerbi_excel_feed.py

python -m pytest -q tests\test_step9r_v1_candidate_ranking_research.py

python -m pytest -q `
  tests\test_v1_validation_concentration.py `
  tests\test_v1_validation_execution_stress.py `
  tests\test_v1_validation_exposure_efficiency.py `
  tests\test_v1_validation_exposure_reconciliation.py `
  tests\test_v1_validation_parameter_robustness.py `
  tests\test_v1_validation_portfolio.py `
  tests\test_v1_validation_provider_quality.py
```

Expected totals by block:

```text
86 passed
70 passed
30 passed
13 passed
14 passed
28 passed
```

Total: `241 passed`.

Do not run Step 9I or Step 9L morning against their real ledger as part of installation verification. The next real run should be the normal once-only prospective morning routine for the next unsealed session.
