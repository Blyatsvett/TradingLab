# Release and tagging conventions

Release automation is intentionally deferred while the projects remain in research/backtesting.

When a reproducible milestone is ready, use annotated tags with this format:

```text
regime-v0.1.0
swing-v0.1.0
pattern-v0.1.0
intraday-v0.1.0
```

Use semantic versioning within each project:

- `v0.x.y` for research milestones before a stable contract exists.
- Increment `x` for a materially changed strategy, data contract, or incompatible workflow.
- Increment `y` for compatible fixes, documentation, or reproducibility improvements.

Tag only commits that have passed the relevant CI checks and have documented data/configuration assumptions. Tags identify code and configuration; local datasets and generated outputs remain outside Git and must be referenced through a snapshot or provenance note.
