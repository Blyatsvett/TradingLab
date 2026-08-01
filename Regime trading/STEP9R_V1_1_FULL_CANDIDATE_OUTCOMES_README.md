# Step 9R V1.1 — Full Prospective Candidate Outcomes

Status: `RESEARCH_ONLY_SHADOW_NOT_PRODUCTION`

## Purpose

This patch completes the original Step 9R candidate-ranking roadmap without changing Step 9L V3.

It keeps the existing morning 0–2 expected-R selector, but changes prospective EOD research so that **every morning candidate** receives one immutable counterfactual outcome row. Selected portfolio outcomes remain stored separately for direct selector comparison.

## Changes

- Adds `selector_candidate_outcomes` to the Step 9R prospective SQLite schema.
- Stores all candidate EOD outcomes, including unselected and non-triggered candidates.
- Preserves the existing `selector_outcomes` table as the selected-only portfolio view.
- Fails loudly when a morning candidate cannot be reconciled to the exact V3 EOD replay.
- Verifies candidate-count versus all-outcome-count equality.
- Keeps identical EOD reruns idempotent and rejects conflicts.
- Adds `step9r_v1_prospective_candidate_outcomes.csv`.
- Changes categorical model preprocessing to train-only levels for strict walk-forward hygiene.
- Does not alter the currently reproduced model comparison results.

## Safety boundaries

- Step 9L V3 remains frozen and is not replaced.
- Step 9I, Step 9L, Step 9Q, Step 9S, ORB, and their ledgers are not modified.
- Existing Step 9R database rows are not deleted or rewritten.
- The new table is additive and created only when Step 9R opens its own prospective database.
- Router active: false.
- Orders enabled: false.
- Strategies promoted: 0.

## Verified research state

- Historical candidate rows: 396.
- Model-eligible primary candidates: 193.
- Current V3 rank, same OOS window: +28.942419 SEK.
- Simple expected-R, same OOS window: +20.243710 SEK.
- July 27 exact replay: 32/32 rows matched current stored outcomes.
- July 27 expected-R shadow selection: ALFA.ST and FABG.ST.
- July 27 all-candidate outcomes: 23 rows, -21.584262 SEK.
- July 27 selected outcomes: 2 rows, -2.549752 SEK.

These are historical/late-reconstruction results and are not prospective promotion evidence.
