# Step 9U Prospective Contingency Selector Shadow V1

Status: `RESEARCH_ONLY_PROSPECTIVE_SHADOW_CHALLENGER_NOT_PRODUCTION`

Step 9U reads the immutable Step 9T prospective morning batch, applies the frozen Step 9U historical policy, preserves every directional candidate, and selects zero to two shadow candidates with at most one per broad sector. It has no mandatory control book, never modifies Step 9S, and never routes an order.

## Morning contract

Run immediately after Step 9T, between 09:48:05 and 09:49:55 Stockholm time:

```powershell
.\run_step9u_prospective_selection_v1.ps1
```

Only the sealed Step 9T morning transition and archetype rows are read. No 09:50 or EOD outcome is available to selection.

## EOD contract

Run after Step 9T EOD:

```powershell
.\run_step9u_prospective_eod_v1.ps1
.\run_step9u_prospective_audit_v1.ps1
```

Step 9U inherits Step 9T's standardized 09:50-open to final-close counterfactual outcomes, preserving selected and unselected candidate outcomes separately.

## Real outputs

- Ledger: `data/step9u_contingency_selector_prospective_shadow_v1.db`
- Exports: `data/step9u_contingency_selector_prospective_shadow_v1/`

The first real row must be the next unseen market session. Do not backfill July 28 into the real prospective ledger.
