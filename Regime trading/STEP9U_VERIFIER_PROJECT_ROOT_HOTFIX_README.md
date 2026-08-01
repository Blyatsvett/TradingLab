# Step 9U verifier project-root hotfix

This hotfix changes only the Step 9U historical verifier bootstrap and the
installed Step 9U manifest hash entry.

It adds the project root to `sys.path` before importing `RegimeTrading` when the
verifier is launched directly from the `tools` directory on Windows.

No strategy, policy, historical output, database, ledger, router, or order
setting is changed.
