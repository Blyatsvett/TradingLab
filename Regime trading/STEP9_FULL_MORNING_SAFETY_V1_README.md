# Step 9 Full Morning Safety V1

This operational layer coordinates the complete prospective morning sequence:

1. Step 9I V2 data collection and morning seal
2. Step 9L V3 morning seal
3. Step 9S frozen contingency benchmark assignment
4. Step 9R V1.1 prospective candidate ranking
5. Existing Step 9T -> Step 9U controlled point-in-time wrapper
6. Step 9Q read-only workbook snapshot

It does not modify strategy logic, candidate ranking, sizing, immutable ledgers, routing, or order behavior.

The wrapper is restart-aware for Steps 9I, 9L, 9S and 9R: a valid existing session row is verified and skipped rather than rerun. Step 9T and Step 9U remain protected by their narrower point-in-time wrapper.

Step 9Q is reporting-only. If Step 9Q fails because Excel has the workbook open, all sealed strategy ledgers remain valid; close Excel and retry only Step 9Q.

Important distinction:

- Step 9S has exactly one mandatory benchmark/control plan per sealed session.
- Step 9U has no mandatory control and may select zero to two candidates.
- Neither engine routes orders.
