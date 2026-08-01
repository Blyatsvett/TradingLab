# Step 9R V1.1 Windows SQLite Verifier Cleanup Hotfix

This test/verifier-only hotfix changes one file:

- `tools/verify_step9r_v1_1_full_candidate_outcomes.py`

It replaces SQLite context-manager usage with explicit-close semantics via `contextlib.closing`. This allows Windows to delete the verifier's temporary SQLite database after verification.

It does not modify Step 9R engine code, configuration, tests, models, strategies, databases, ledgers, Step 9I, Step 9L, Step 9Q, Step 9S, ORB, routing, or orders.

Audited source verifier hash before hotfix:

`605944a2a13e2717cbc3a8f0040bdd1c6dd49074924f75cfd39d7168a4452d63`

Hotfixed verifier hash:

`3c2dc81fda9866785c2e39612fd25690a01aea662b2a5ad5629ca137802c94d2`
