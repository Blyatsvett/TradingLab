NASDAQ PHASE 1 PROBE V3

This patch fixes StaleElementReferenceException caused by Nasdaq refreshing the
report list while Selenium iterates WebElement objects.

V3 never keeps report WebElements between browser commands. It takes a rendered
DOM snapshot as plain strings, tries the discovered URL with the browser cookies,
and otherwise locates and clicks the selected report in one atomic JavaScript call.

Extract this ZIP directly into the existing Regime trading project root and allow
replacement of RegimeTrading\scripts\probe_nasdaq_posttrade.py.

Run:
  .\probe_nasdaq_data.ps1

No database or research output is modified.
