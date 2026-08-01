# Step 9T Prospective Regime-Transition and Archetype Ledger V1

Status: `RESEARCH_ONLY_PROSPECTIVE_OBSERVER_NOT_SELECTOR_NOT_ROUTER_ACTIVE`

## Purpose

This engine prospectively seals the Step 9T market-transition snapshot and one
strategy-archetype observation for every ticker. It is an observer only:

- it does not select trades;
- it does not change Step 9I, Step 9L, Step 9R, or Step 9S;
- it does not route orders;
- it writes only to its own immutable ledger and CSV exports.

## Morning point-in-time contract

- Run after the Step 9L V3 morning batch exists.
- Seal before `09:49:30` Stockholm time.
- Use only completed bars through `09:45`.
- Do not use the 09:50 price or any later information to classify the market or ticker.
- The future standardized 09:50 entry price is attached only during EOD evaluation.

## Daily commands

Morning:

```powershell
.\run_step9t_prospective_snapshot_v1.ps1
```

EOD, after the final collector:

```powershell
.\run_step9t_prospective_eod_v1.ps1
```

Audit:

```powershell
.\run_step9t_prospective_audit_v1.ps1
```

## Outputs

Ledger:

`data\step9t_regime_transition_archetype_prospective_v1.db`

Exports:

`data\step9t_regime_transition_archetype_prospective_v1\`

The ledger has immutable morning batches, immutable ticker archetypes,
immutable EOD batches, and one immutable outcome for every ticker.

## First real session

Do not reconstruct July 28 into the real prospective ledger. The first real row
must be created on the next unseen market session after installation.

## Safety invariants

- Historical freeze ID: `92b274cb24cad391`
- Source duplicate policy: `LATEST_SQLITE_ROWID_PER_TICKER_MINUTE_V1`
- Selection active: false
- Router active: false
- Orders enabled: false
