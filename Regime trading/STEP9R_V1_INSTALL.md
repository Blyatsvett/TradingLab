# Step 9R V1 — Candidate-ranking research and 0–2 shadow selector

## Purpose

Step 9R V1 addresses the selection problem without changing the frozen Step 9L V3 engine.
It:

1. preserves every valid V3 candidate and its exact counterfactual outcome;
2. replays the exact V3 contracts historically;
3. audits whether the current V3 rank predicts outcome;
4. builds a transparent walk-forward expected-R score;
5. compares statistical challengers;
6. prospectively shadow-selects zero, one, or two candidates;
7. never replaces V3 automatically.

## Safety contract

Step 9R is `RESEARCH_ONLY_SHADOW_NOT_PRODUCTION`.

- Step 9I and Step 9L source files are not modified.
- V3 remains the frozen baseline and continues its normal daily process.
- Source price and ledger databases are opened read-only during research replay.
- Guardrails are preserved for diagnostics but excluded from model training and primary P&L.
- The selector cannot send orders and is not router-active.
- Historical results are non-confirmatory.
- July 27, 2026 remains a late reconstruction and is not prospective evidence.

## Install

1. Back up the project folder.
2. Extract the patch ZIP directly into:

   `C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading`

3. Allow the new Step 9R files to be added. The patch does not replace Step 9I, Step 9L, Step 9Q, or ORB files.

If Windows blocks the wrappers:

```powershell
Unblock-File .\run_step9r_v1_historical_research.ps1
Unblock-File .\run_step9r_v1_prospective_shadow.ps1
Unblock-File .\run_step9r_v1_eod_shadow.ps1
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover `
    -s tests `
    -p "test_step9r*.py" `
    -v

.\.venv\Scripts\python.exe -m unittest discover `
    -s tests `
    -p "test_step9l*.py" `
    -v

.\.venv\Scripts\python.exe -m unittest discover `
    -s tests `
    -p "test_step9q*.py" `
    -v
```

## Historical research run

```powershell
.\run_step9r_v1_historical_research.ps1 `
    -StartDate "2026-05-25" `
    -EndDate "2026-07-27"
```

This performs the exact candidate replay first and then starts a fresh Python process for the walk-forward models.

Outputs:

- `data\step9r_candidate_ranking_research_v1.db`
- `data\outputs\research\step9r\step9r_v1_candidate_outcomes.csv`
- `data\outputs\research\step9r\step9r_v1_current_rank_audit.csv`
- `data\outputs\research\step9r\step9r_v1_rank_bucket_performance.csv`
- `data\outputs\research\step9r\step9r_v1_daily_selection_diagnostics.csv`
- `data\outputs\research\step9r\step9r_v1_selection_regret.csv`
- `data\outputs\research\step9r\step9r_v1_selector_walk_forward_predictions.csv`
- `data\outputs\research\step9r\step9r_v1_selector_comparisons.csv`
- `data\outputs\research\step9r\step9r_v1_audit.csv`
- `data\outputs\research\step9r\step9r_v1_summary.csv`

## Normal prospective daily sequence

Run the existing collection and frozen morning engines exactly as before. After Step 9L V3 has sealed its morning batch, run:

```powershell
.\run_step9r_v1_prospective_shadow.ps1 `
    -Date "YYYY-MM-DD"
```

The selector records all eligible V3 primary candidates, assigns a locked point-in-time expected-R score, and shadow-selects 0–2 candidates. It does not affect V3.

At EOD, first run the normal Step 9I and Step 9L evaluators. Then run:

```powershell
.\run_step9r_v1_eod_shadow.ps1 `
    -Date "YYYY-MM-DD"
```

Prospective outputs are stored separately in:

- `data\step9r_prospective_selector_shadow_v1.db`
- `data\outputs\research\step9r\step9r_v1_prospective_candidates.csv`
- `data\outputs\research\step9r\step9r_v1_prospective_selections.csv`
- `data\outputs\research\step9r\step9r_v1_prospective_outcomes.csv`

## Metric interpretation

- **All-candidate win rate:** outcome quality of every triggered, model-eligible primary candidate. It measures the strategy/candidate pool, not only the selected portfolio.
- **V3-selected win rate and P&L:** result from the frozen current rank and maximum-two selection.
- **Oracle up-to-two P&L:** impossible-to-trade hindsight benchmark selecting up to two profitable candidates. It is only an upper bound.
- **Selection regret:** oracle P&L minus actual selected P&L. It measures opportunity lost through ranking/selection.
- **Coverage failure:** no valid primary candidate existed. Under the contingency objective, this is not counted as a successful day merely because capital was preserved.

## First validated research result

For 2026-05-25 through 2026-07-27, the exact replay produced 45 sessions, 193 valid primary candidates, 167 triggered counterfactuals, a 45.5% all-candidate win rate, +1.32 SEK all-candidate P&L, +47.30 SEK frozen V3-selected P&L, and +106.50 SEK oracle up-to-two P&L. The four authoritative July 27 V3 trades reconciled with zero failures.

The current V3 rank beat every first-generation walk-forward challenger in the available out-of-sample comparison. Therefore Step 9R does **not** replace V3. The transparent expected-R score remains a prospective shadow challenger while evidence accumulates.

July 27 exact full-EOD primary replay contained 23 valid and triggered candidates, three winners, a 13.0% win rate, -21.58 SEK all-candidate P&L, and -4.66 SEK frozen V3-selected P&L. This corrects the earlier incomplete 11.1% estimate.
