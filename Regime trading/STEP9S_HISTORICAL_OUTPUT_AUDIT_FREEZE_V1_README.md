# Step 9S Historical Output Audit and Freeze V1

Status: verification-only research tooling.

This package adds one verifier and its tests. It does not modify Step 9S replay logic, Step 9I, Step 9L, Step 9Q, Step 9R, ORB, routers, databases, or ledgers.

The verifier independently checks:

- nine-regime registry coverage;
- one assignment per taxonomy session;
- exactly one mandatory coverage trade per session;
- natural/control book separation;
- strategy and control IDs against the registry;
- timestamps, single-trade geometry, pair geometry, costs and P&L fields;
- P&L and performance-table reconciliation;
- source-hash provenance;
- byte-for-byte deterministic replay;
- protected real-file hashes before and after;
- router inactive and no orders.

After all blocking checks pass, it creates a content-addressed freeze directory under:

`data/archives/freezes/step9s_historical_contingency_replay_v1/freeze_v1/<freeze_id>/`

The freeze preserves four interpretation notes: retrospective natural-book selection, unequal regime notionals, expected exact cross-book overlaps, and negative aggregate mandatory-control P&L.
