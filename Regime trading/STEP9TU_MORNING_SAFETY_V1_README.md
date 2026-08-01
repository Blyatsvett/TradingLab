# Step 9T -> Step 9U Morning Safety V1

Operational tooling only. It does not alter Step 9T, Step 9U, Step 9S, selection rules, historical freezes, ledgers, routing, or order behavior.

## Tonight

```powershell
.\run_step9tu_tonight_preflight_v1.ps1 -NextSessionDate "2026-07-30"
```

This runs focused Step 9T/9U tests and the temporary end-to-end lifecycle verifier. It never creates the real Step 9U prospective ledger.

## Morning readiness

Run around 09:46 Stockholm time, after Step 9L is sealed and the collector has data through 09:45:

```powershell
.\run_step9tu_morning_readiness_v1.ps1
```

This is read-only. It computes the exact Step 9T transition and frozen Step 9U candidate selection in memory, but writes no prospective ledger.

## Live point-in-time seal

Launch once at 09:47:45 Stockholm time:

```powershell
.\run_step9tu_live_morning_v1.ps1
```

The wrapper computes a fresh read-only preview, waits for 09:48:00, seals Step 9T, waits until at least 09:48:05, seals Step 9U, then verifies the two immutable ledgers exactly match the preview. A named mutex prevents double-click execution and Windows sleep is suppressed while the wrapper runs.

Never rerun Step 9T after it has sealed. If Step 9T succeeds and Step 9U fails, repair/retry only Step 9U before 09:49:55.
