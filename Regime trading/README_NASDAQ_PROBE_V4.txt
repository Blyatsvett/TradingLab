NASDAQ PROBE V4
===============

Replace the existing probe script by extracting this patch into the existing
Regime trading project root.

V4 fixes Nasdaq CSV parsing when the first line contains the Excel-style
separator declaration:

    sep=;

The parser now skips that metadata line and uses semicolon as the delimiter.
It does not modify any SQLite database or research output.
