NASDAQ PROBE V5
===============

Extract this patch into the existing Regime trading project root.

V5 fixes Nasdaq's quoted Excel separator declaration:

    "sep=;"

The parser strips the surrounding quotes, skips the declaration row, and reads
the real semicolon-separated header.

V5 also adds a browser-free way to re-profile the newest downloaded file:

    .\.venv\Scripts\python.exe -m RegimeTrading.scripts.probe_nasdaq_posttrade --profile-latest

No SQLite database or research output is modified.
