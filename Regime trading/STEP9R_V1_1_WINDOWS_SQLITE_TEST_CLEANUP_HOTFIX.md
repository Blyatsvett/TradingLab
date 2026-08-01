# Step 9R V1.1 Windows SQLite Test Cleanup Hotfix

Scope: test-only Windows compatibility repair.

The V1.1 implementation is unchanged. Three test connections used `with sqlite3.connect(...)`, which commits or rolls back but does not close the SQLite file handle. Windows therefore refused to delete the temporary database at `TemporaryDirectory` cleanup.

The hotfix:

- imports `closing` from `contextlib`;
- wraps the three temporary SQLite connections in `closing(...)`;
- changes no Step 9R engine, configuration, database, ledger, model, strategy, router, or outcome logic.

Expected patched test-file SHA-256:

`97a756a92892748851e44799145a6814a1b05d10b3bb2a41f3cdc7f976d66200`
