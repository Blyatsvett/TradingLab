# Step 9S Prospective Contingency Shadow V1 — Install and Verification

This patch starts the prospective Contingency Trading shadow operation. It adds a separate immutable Step 9S ledger and does not modify Step 9I, Step 9L, Step 9Q, Step 9R, ORB, or any existing ledger.

## New files

- `RegimeTrading/scripts/step9s_prospective_contingency_shadow_v1.py`
- `config/step9s_prospective_contingency_shadow_v1.json`
- `tests/test_step9s_prospective_contingency_shadow_v1.py`
- `tools/verify_step9s_prospective_contingency_shadow_v1.py`
- `run_step9s_prospective_morning.ps1`
- `run_step9s_prospective_eod.ps1`
- `STEP9S_PROSPECTIVE_CONTINGENCY_SHADOW_V1_README.md`

## Runtime artifacts created later

- `data/step9s_prospective_contingency_shadow_v1.db`
- `data/step9s_prospective_contingency_shadow_v1/`

No runtime database or output is included in the patch.

## Verification evidence in isolated fresh project

- Dedicated prospective tests: 8 passed.
- Step 9S historical + freeze + prospective tests: 13 passed.
- Step 9I V2 compatibility: 7 passed.
- Step 9L V3 compatibility: 11 passed.
- Complete suite, executed in exact stage groups: 254 passed total.
- July 28 morning reconstruction: TREND_DOWN, mandatory SHORT SAND.ST plan at 09:50.
- July 27 lifecycle: two Step 9L natural trades, one mandatory 09:50 control trade.
- Natural July 27 P&L: -4.663401 SEK.
- Mandatory-control July 27 P&L: -1.680024 SEK.
- Protected real source files unchanged.
- Router inactive; no order sent.

## First prospective day

After installation and verification, the first genuinely prospective run should be the next unsealed market morning. Do not backfill the real Step 9S prospective ledger with July 27 or July 28 verification rows.
