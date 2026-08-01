# STEP9T_REGIME_TRANSITION_ARCHETYPE_RESEARCH_V1 — Build Specification

**Status:** `RESEARCH_ONLY_READ_ONLY_NOT_ROUTER_ACTIVE`

## Purpose

Create a separate research layer that answers two questions without changing the
existing opening-regime decision:

1. How did the market state evolve between the immutable 09:45 regime decision
   and the first prospective 09:50 observation?
2. Which strategy archetype did each ticker qualify for using only information
   available by 09:50, and what was its later counterfactual outcome?

Step 9T observes and records. It does not route orders, replace Step 9I/9L,
change Step 9S trades, or influence Step 9R selection in V1.

## Files to add

- `RegimeTrading/scripts/step9t_regime_transition_archetype_research_v1.py`
- `config/step9t_regime_transition_archetype_research_v1.json`
- `tests/test_step9t_regime_transition_archetype_research_v1.py`
- `run_step9t_historical_replay_v1.ps1`
- `run_step9t_prospective_snapshot_v1.ps1`
- `run_step9t_eod_v1.ps1`
- `STEP9T_REGIME_TRANSITION_ARCHETYPE_RESEARCH_V1_README.md`

## Separate outputs only

- Historical outputs:
  `data/step9t_regime_transition_archetype_research_v1/`
- Prospective immutable ledger:
  `data/step9t_regime_transition_archetype_prospective_v1.db`

All source databases and existing ledgers must be opened read-only.

## Point-in-time contract

- Opening regime remains the sealed 09:45 Step 9L V3 regime.
- Step 9T snapshot time is 09:50.
- Only bars labelled through 09:45 may influence Step 9T morning features.
- The 09:50 bar may provide the standardized shadow entry price, but no 09:50
  high, low, or close may influence the morning classification.
- A normal prospective snapshot must be sealed shortly after the 09:45 bar is
  complete.
- Late reconstruction must be labelled non-confirmatory.
- Step 9T must never rewrite the opening regime.

## Session-level transition features

Calculate from the complete 29-ticker universe, with explicit coverage counts:

- Advancer and decliner shares from 09:30 open to 09:45 close
- Median 09:30–09:45 return
- Median 09:40–09:45 return
- Recovery share among early losers
- Continuation share among early winners
- Opening-range midpoint reclaim share
- Early-leader failure share
- Cross-sectional return dispersion
- Optional sector-level breadth summaries
- Missing/incomplete ticker count

Initial diagnostic transition labels:

- `BROAD_RECOVERY`
- `WEAKNESS_PERSISTING`
- `BULLISH_CONTINUATION`
- `LEADER_FAILURE`
- `MIXED_TRANSITION`
- `DATA_LIMITED_TRANSITION`

The thresholds must live in configuration, be frozen before prospective use,
and must not be optimized from July 28 alone.

## Ticker-level archetypes

Classify every ticker using morning-only information. Preserve both the
individual flags and one deterministic primary archetype:

1. `BULLISH_CONTINUATION_LONG`
2. `BEARISH_CONTINUATION_SHORT`
3. `LAGGARD_RECOVERY_LONG`
4. `LEADER_REVERSAL_SHORT`
5. `NO_CLEAR_SETUP`

Suggested deterministic priority when multiple flags are true:

1. Laggard recovery
2. Leader reversal
3. Bullish continuation
4. Bearish continuation
5. No clear setup

The priority is merely a V1 diagnostic convention and must be recorded in the
configuration.

## EOD counterfactual outcomes

For V1, use a standardized diagnostic outcome rather than pretending all
archetypes share one production contract:

- Entry: 09:50 bar open
- Direction: determined by archetype
- Exit: final available session close
- Frozen notional and cost assumptions
- Preserve maximum favorable excursion and maximum adverse excursion
- Preserve zero/ambiguous outcomes for `NO_CLEAR_SETUP`
- Keep these results separate from Step 9L, Step 9S, and Step 9R P&L

MFE and MAE allow later stop/target research without repeatedly reconstructing
the raw intraday path.

## Historical build sequence

### Phase H1 — feature and archetype replay

1. Reconstruct the current verified project in a fresh extraction.
2. Read frozen taxonomy and sealed Step 9L regimes read-only.
3. Compute one transition snapshot per historical session.
4. Produce one ticker-archetype row for each universe ticker and session.
5. Evaluate standardized EOD outcomes.
6. Include July 28 as:
   `RETROSPECTIVE_NON_CONFIRMATORY_DIAGNOSTIC`.
7. Reconcile the July 28 outputs against the existing 29-ticker performance CSV.
8. Produce session, regime, transition-state, and archetype summaries.

### Phase H2 — audit and freeze

1. Verify exactly one session transition row per session.
2. Verify expected ticker row counts or explicit missing-data rows.
3. Verify no morning feature uses a bar later than 09:45.
4. Verify all EOD returns reconcile with source bars.
5. Verify deterministic reruns.
6. Freeze the historical artifact set with SHA-256 hashes.

## Prospective build sequence

### Morning snapshot

1. Complete normal 09:45 routine: collector, Step 9I, Step 9L, Step 9S, Step 9R.
2. Refresh the collector shortly after 09:50 so the 09:45 bar is complete.
3. Run Step 9T snapshot once.
4. Seal the opening regime, transition features, and ticker archetypes.
5. Do not change any same-day strategy or selected trade.

### EOD

1. Run the final collector.
2. Complete the normal engine EOD routine.
3. Run Step 9T EOD once.
4. Seal all ticker counterfactual outcomes.
5. Run Step 9Q final snapshot separately.

## Required ledger properties

- One immutable transition batch per session
- One immutable ticker-archetype row per session/ticker
- One immutable outcome row per ticker-archetype row
- Identical rerun returns the existing row
- Conflicting rerun fails loudly
- Database-level UPDATE and DELETE protection
- Source database hashes and batch hashes stored as provenance
- Explicit router-active and order-sent fields fixed to false

## Required tests

1. No bar later than 09:45 affects the morning snapshot.
2. The sealed Step 9L regime is copied but never modified.
3. Exactly one transition batch is created per session.
4. Every ticker is represented or explicitly marked incomplete.
5. Archetype assignment is deterministic.
6. July 28 reconciles with the existing market-performance export.
7. Identical morning and EOD reruns are idempotent.
8. Conflicting reruns fail.
9. Late reconstruction is non-confirmatory.
10. Source databases and existing ledgers remain byte-for-byte unchanged.
11. SQLite handles close correctly on Windows.
12. Full project compatibility suite passes.

## Acceptance gate

V1 is complete only when:

- Historical replay and July 28 reconciliation pass.
- Historical artifacts are frozen.
- Prospective temporary-ledger lifecycle passes.
- Existing Step 9I, Step 9L, Step 9Q, Step 9R, and Step 9S tests still pass.
- No protected file changes.
- No order is sent.

## Future use

After enough unseen sessions, Step 9T can test whether transition state improves
the mapping from opening regime to strategy. It must not influence Step 9S or
Step 9R until a separately versioned promotion decision is supported by unseen
evidence.
