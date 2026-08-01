# Regime Trading Baseline and Step 9R Cost Stress

Date: 2026-08-01  
Branch: `research/regime-cost-stress-baseline`  
Status: research-only; no strategy promotion

## Baseline controls

- Canonical contract: passed
- Project dependency/compile/config validation: passed
- Orders enabled: `false`
- Router active: `false`
- Baseline engine: Step 9L V3
- Selector: `SIMPLE_EXPECTED_R_SCORE_V1`
- Historical sample: 2026-05-25 through 2026-07-27
- Selected primary triggered rows: 46
- Selected primary sessions: 29
- Selection rule changed: no

The frozen baseline is the existing Step 9R V3-selected primary research book.
The analysis uses the existing candidate-outcome export and does not rerun or
rewrite the canonical ledger, outputs, or source databases.

## Research question

Does the Step 9R V3-selected primary research book remain positive when its
realized baseline transaction-cost burden is doubled, without changing the
selection rule?

## Cost-stress comparison

| Scenario | Net P&L (SEK) | Positive sessions | Max drawdown (SEK) |
|---|---:|---:|---:|
| Existing baseline cost | 47.3019 | 22 / 29 | -7.5814 |
| 1.5x baseline cost | 39.8955 | 21 / 29 | -8.1044 |
| 2.0x baseline cost | 32.4890 | 20 / 29 | -8.6273 |
| 3.0x baseline cost | 17.6762 | 20 / 29 | -9.6733 |

Baseline gross P&L was 62.1147 SEK and the realized baseline cost burden was
14.8128 SEK. At 2x costs, net P&L remains positive at 32.4890 SEK.

Result: **SUPPORTED for this historical sample and this predefined 2x cost
stress.** This is robustness evidence, not evidence of production readiness.

## Look-ahead and provenance controls

- Candidate selection remains the existing V3 selection; no reselection uses
  post-entry outcomes.
- Selected rows passed the existing `model_eligible` and
  `point_in_time_pass` fields.
- Selected feature labels did not exceed the 09:40 cutoff.
- Source and configuration hashes are recorded in the generated ignored output:
  `data/outputs/research/step9r_cost_stress/step9r_cost_stress_20260801.json`.
- The source market database, Step 9R outcome export, summary, path config, and
  stage registry are all hash-pinned in that output.

## Limitations and next decision

This is an in-sample historical robustness check with a limited 29-session
selected sample. It does not establish prospective validity, statistical
significance, liquidity capacity, or live-trading readiness. The next research
decision should be whether to run the same cost-stress protocol on a genuinely
prospective accumulation window before considering any strategy change.
