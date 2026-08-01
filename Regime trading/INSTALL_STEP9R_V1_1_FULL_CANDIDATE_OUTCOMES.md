# Installation scope

The patch replaces only:

- `RegimeTrading/scripts/step9r_v1_candidate_ranking_research.py`
- `config/step9r_candidate_ranking_research_v1.json`
- `tests/test_step9r_v1_candidate_ranking_research.py`

It adds:

- `tools/verify_step9r_v1_1_full_candidate_outcomes.py`
- `STEP9R_V1_1_FULL_CANDIDATE_OUTCOMES_README.md`

No databases, ledgers, generated CSV outputs, Step 9L files, Step 9S files, or order-routing files are included.

Run the dedicated tests and verifier before resuming prospective Step 9R. Do not rerun Step 9I or Step 9L because a Step 9R test or verifier fails.
