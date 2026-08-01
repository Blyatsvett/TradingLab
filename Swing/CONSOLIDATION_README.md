# Canonical Swing pipeline

Status: active, research-only. The canonical pipeline is a backtest; it does not place production orders.

Run from the `Swing` project root:

```bash
python -m scripts.run_canonical_backtest
python -m unittest discover -s tests -v
```

The pipeline writes Power BI-ready CSV tables to `outputs/canonical/`.
Legacy scripts remain in place and are not imported by the canonical runner.
