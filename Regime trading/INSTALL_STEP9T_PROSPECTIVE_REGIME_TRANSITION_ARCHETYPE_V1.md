# Install Step 9T Prospective V1

This patch adds a separate immutable observer ledger. It does not modify the
historical Step 9T replay, Step 9I, Step 9L, Step 9R, Step 9S, or Step 9Q.

The installation gate requires the frozen historical baseline:

- Freeze ID: `92b274cb24cad391`
- Independent audit: `30/30`
- Historical artifact-set SHA-256:
  `92b274cb24cad391324b4023e20c9f9830544f6c63e87b73846ff757ff986aa1`

The installer runs:

1. Historical-freeze verification
2. Installed-file hash verification
3. 20 dedicated Step 9T tests
4. Temporary-ledger lifecycle verifier
5. Protected-file immutability verification
6. Full project suite, expected 277 tests

The real prospective ledger is not created during installation. Its first row
must be created on the next unseen market session.
