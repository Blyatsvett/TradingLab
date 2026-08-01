# Regime Trading Cleanup and Restructuring Record

Status: core cleanup and restructuring complete  
Last reviewed: 2026-08-01  
Owner: TradingLab project  

## Purpose

This file is a focused working record for the Regime Trading cleanup and
restructuring effort. It preserves the decisions, completed work, validation
evidence, and remaining optional work from the transition from exploratory
development to a maintainable research/backtesting project.

This is a project record, not a replacement for the root working-agreements
file. The single source of truth for repository-wide rules remains:

- `C:\Users\User\Desktop\Kaizen\TradingLab\AGENTS.md`

The current Regime Trading operating guide remains:

- `C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading\docs\ACTIVE_SYSTEM_GUIDE.md`

## Scope and priorities

- Regime Trading is the main active priority.
- Swing, Pattern Trading, and Intraday remain separate projects with their own
  environments and validation commands.
- Trading Beta is the legacy first project and is kept separately for reference.
- Regime Trading currently supports research and backtesting only.
- Live-trading infrastructure may exist for future use, but orders remain
  disabled and the router remains inactive.
- Existing scripts and pipelines were kept available unless they were clearly
  historical documentation, reports, or backup material.

## Completed restructuring

### Repository and project structure

- Regime Trading was identified as the canonical active project.
- Root-level project files were reviewed and the project map was documented.
- Trading Beta was placed in its own folder so its original files no longer sit
  freely in the TradingLab root.
- The root `AGENTS.md` was established as the single project-wide source of
  truth.
- Repository guidance, contribution instructions, release conventions, and
  secondary-project audit documentation were added or consolidated.
- GitHub Actions and branch protection were configured and verified through
  green checks on the merged cleanup pull request.

### Regime Trading pipeline audit

- The canonical Regime Trading pipeline, entry points, stages, tests, data
  flow, and execution boundaries were documented.
- Active wrappers were retained in place where their `$PSScriptRoot` and
  relative-path assumptions made moving them risky.
- Historical wrappers and notes were classified rather than moved by filename
  alone.
- The authoritative documentation is in:
  `C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading\docs\ACTIVE_SYSTEM_GUIDE.md`
  and
  `C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading\docs\FILE_ORGANIZATION_INDEX.md`.

### Validation and environments

- A dependency-free canonical validator was added at:
  `C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading\tools\validate_canonical_pipeline.py`
- The project-level validation runner was integrated at:
  `C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading\tools\run_project_validation.ps1`
- The missing bundled `scipy` dependency was resolved in the Regime Trading
  environment.
- Regime Trading’s full collected test suite passed: 395/395.
- Pattern Trading’s validation passed: 387/387.
- Swing’s validation passed: 4/4.
- Intraday’s independent environment and static validation were verified.
- Each secondary project has its own setup and validation instructions.

### Data organization

The Regime Trading data tree was separated without deleting source material:

- `data/source/` — raw market data and reusable reference data
- `data/ledgers/` — prospective and research databases
- `data/outputs/` — generated research, shadow, collector, KPI, and observer
  outputs
- `data/archives/` — frozen, legacy, and historical research evidence

The migration was performed with reference mapping, copy-based rehearsals, and
preservation of database sidecars and provenance. The supporting records are:

- `C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading\docs\DATA_MIGRATION_MANIFEST_V1.md`
- `C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading\docs\DATA_SEPARATION_MAP.md`
- `C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading\docs\ROOT_DATA_CLASSIFICATION_V1.md`

### Historical documentation and legacy material

- 41 high-confidence historical notes and reports were moved to:
  `C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading\docs\legacy\regime_notes`
- The exact classification is recorded in:
  `C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading\docs\LEGACY_FILE_CLASSIFICATION.md`
- Clearly historical entrypoint archives were separated while operational
  scripts and uncertain wrappers were retained.
- Patch manifests, hotfix notes, installation notes, and uncertain legacy
  wrappers remain available until their references are individually verified.

### Reproducibility

- Local market-data acquisition and restoration procedures were documented.
- A fresh snapshot and isolated restore rehearsal was completed successfully.
- Snapshot SHA256:
  `747f98cdaa4f522161b0b76864dfb3957a723e6af6a7ad5a3ea6ddf5e0cb7ff4`
- The restored copy passed static project validation, compilation, canonical
  contract checks, configuration checks, and restored-path checks.
- The live data tree was not modified by the rehearsal.
- Evidence is recorded in:
  `C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading\docs\DATA_RESTORE_REHEARSAL_20260801.md`

## Research branch completed alongside cleanup

After the cleanup baseline was merged to `main`, a fresh branch was created:

- `research/regime-cost-stress-baseline`

That branch contains a research-only Step 9R cost-stress analysis. It did not
change the strategy, selection rule, router, order state, or canonical
pipeline.

Research question:

> Does the existing Step 9R V3-selected primary research book remain positive
> if its already-realized transaction-cost burden is doubled?

Controls recorded:

- Same historical selected trades and unchanged selection rule
- Baseline, 1.5x, 2x, and 3x cost scenarios
- Model-eligibility and point-in-time checks
- Feature-label cutoff at 09:40 to reduce look-ahead risk
- Input-file hashes and data provenance
- Research/backtesting-only execution
- Router inactive and orders disabled

Result for the historical sample:

- Existing baseline net: 47.30 SEK
- Net with doubled costs: 32.49 SEK
- Net with tripled costs: 17.68 SEK
- The predefined doubled-cost stress remained positive, so the result was
  recorded as `SUPPORTED` for this sample.

The implementation and report are:

- `C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading\tools\run_step9r_cost_stress_research.py`
- `C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading\docs\research\REGIME_BASELINE_AND_STEP9R_COST_STRESS_20260801.md`

This is historical in-sample robustness evidence, not proof of prospective
performance or live-trading readiness.

## Current state

The core cleanup and restructuring is complete and merged into `main` through
the cleanup pull request:

- Commit: `7b4ae5a`
- Message: `feat: complete Regime validation and legacy cleanup (#2)`

The current research branch contains the two new research files listed above.
The generated JSON result is intentionally ignored by Git because it is a
reproducible output rather than source code:

- `data/outputs/research/step9r_cost_stress/step9r_cost_stress_20260801.json`

## Remaining optional work

There is no urgent structural blocker. The remaining items are quality and
maintainability improvements:

1. Deeper manifest cleanup — review stale hashes, historical path strings, and
   old manifest references while preserving provenance.
2. Additional legacy-wrapper classification — inspect remaining V1, Step 7–9,
   Step 9I/9L, and gap-recovery wrappers individually before any move.
3. Shared utility refactoring — identify genuinely duplicated helpers and
   consolidate them only after the canonical pipeline has a stable baseline.

Approximate effort:

- Manifest cleanup: 1–3 hours
- Additional wrapper classification: 2–6 hours
- Shared utility refactoring: 1–3 days, with the highest regression risk

These items should be handled as separate, reviewable changes. Refactoring
shared utilities should wait until the current validation baseline and research
workflow are stable.

## Operating rules for future work

- Keep changes additive and reversible.
- Do not delete historical evidence merely because it is old.
- Do not move an operational script without mapping wrappers, tests, scheduled
  tasks, docs, manifests, and generated path references.
- Treat SQLite databases and sidecars as one unit.
- Keep raw data, generated outputs, credentials, and local environments out of
  Git.
- Record strategy changes with costs, data range, provenance, and look-ahead
  protections.
- Run the narrowest relevant tests after every code or path change.
- Keep all research branches and experiments explicitly research/backtesting-
  only unless the user separately authorizes live-trading work.

## Recommended next step

Commit and publish the current research branch through GitHub Desktop, open a
pull request into `main`, and let the green checks verify the new research
record. After that, continue research work; treat the three cleanup items above
as optional backlog rather than prerequisites.
