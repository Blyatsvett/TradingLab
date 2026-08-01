# STEP9_FULL_LIVE_MORNING_ORCHESTRATOR_V2

## Purpose

This package replaces the sequential Step 9 morning launcher with a
dependency-driven, bounded, and recoverable orchestrator. It preserves the
audited Step 9I through Step 9U engine logic, point-in-time cutoffs, evidence
labels, and immutable ledgers.

The package does not contain a database or ledger. It does not modify the
production/paper ORB project. Routing and orders remain disabled.

## Live morning path

1. The primary scheduled task starts at 09:44:20 Stockholm time.
2. The watchdog starts at 09:44:50 and waits behind the session mutex.
3. At 09:45:02 the existing 29-ticker collector refreshes the source database.
4. The orchestrator verifies database integrity, 29 observed session tickers,
   and data readiness through 09:45.
5. It creates two immutable SQLite snapshots:
   - through 09:40 for Step 9I, Step 9L, Step 9S, and Step 9R;
   - through 09:45 for Step 9T.
6. Step 9I and Step 9L run concurrently.
7. After Step 9L passes canonical verification:
   - Step 9S starts before its frozen deadline;
   - Step 9T starts at or after its frozen 09:48 decision time.
8. Step 9U starts immediately after Step 9T passes verification.
9. Step 9R runs after the deadline-critical Step 9T/9U path.
10. Exports and Step 9Q reporting run only after the live decision chain is
    sealed and verified.

The fast stage runner calls existing frozen seal functions with
`export_outputs_after=False`. This defers reporting work; it does not change a
strategy, candidate, selection, or sealed ledger payload.

## Recovery and isolated mock fallback

Every native child has a timeout. The orchestrator tracks and drains children
before fallback. If a primary process dies, the watchdog can recover an
abandoned mutex, terminate only verified orphaned V2 children, inspect already
sealed stages, and continue safely.

If the live chain remains incomplete:

- every valid live seal is preserved;
- the live session is classified as `LIVE_PARTIAL` or `LIVE_FAILED`;
- SQLite databases are copied with the SQLite backup API into a unique,
  short-path clone below `C:\Users\User\S9M`;
- immutable snapshot manifests, cutoffs, and hashes are independently checked;
- if a trusted live snapshot is unavailable, only the isolated mock price
  database is refreshed with bounded retries (never the real price database);
- only absent stages are reconstructed at their original simulated times;
- the mock result is labelled `MOCK_REHEARSAL`;
- canonical structural verification must pass;
- source databases and all `-wal`/`-shm` sidecars are re-hashed afterward;
- mock output is never merged into a real prospective ledger.

A mock fallback preserves research evidence but never becomes confirmatory
evidence.

## Point-in-time policy

Morning readiness preserves the audited engine contract:

- SQLite integrity must pass;
- all 29 universe tickers must be observed for the session;
- the global source maximum must reach 09:45;
- snapshots may contain no session row later than their declared cutoff.

Exact 09:40 and 09:45 per-ticker bar counts are retained as diagnostics. The
orchestrator does not silently invent, forward-fill, or change the frozen
engine's data eligibility rules.

## Installation and qualification

The outer installer:

- verifies a hard-coded package-manifest hash;
- checks every payload hash;
- compiles every Python file without importing project engines;
- parses every PowerShell file and requires ASCII-safe bytes for Windows
  PowerShell 5.1;
- verifies the audited transitive runtime closure before writing;
- runs focused package tests before writing;
- blocks installation during the live morning window;
- backs up every destination outside the project;
- installs files transactionally and rolls back on any failure;
- verifies protected SQLite files and sidecars stayed byte-for-byte unchanged;
- does not register scheduled tasks.

After installation, the full tonight preflight must pass without skip flags.
Only then should the separate registration script create the next session's
primary and watchdog tasks.

## Operational boundaries

- Do not run the V1 morning launcher beside V2.
- Never delete, replace, or reset a real Step 9 ledger.
- Never rerun an already sealed stage merely because a later stage failed.
- Do not use late reconstruction on the live path.
- Keep the computer on, awake, signed in, and connected to the internet.
- Locking the screen is allowed.
- Router active: false.
- Orders enabled: false.
