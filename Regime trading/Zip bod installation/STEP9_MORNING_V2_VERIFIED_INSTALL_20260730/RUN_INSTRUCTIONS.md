# STEP9 Morning V2 — Run Instructions

1. Extract the verified ZIP to a temporary location.
2. Open Windows PowerShell and move to the real project:

```powershell
cd "C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading"
.\.venv\Scripts\Activate.ps1
Set-ExecutionPolicy -Scope Process Bypass
```

3. Run the qualified preflight for the next intended market session:

```powershell
.\run_step9_full_tonight_preflight_v2.ps1 -NextSessionDate "2026-08-03"
```

4. Register tasks only if the output contains:

```text
STEP9_FULL_TONIGHT_PREFLIGHT_V2: QUALIFIED
```

Then run:

```powershell
.\register_step9_morning_v2_tasks.ps1 -Date "2026-08-03"
```

Do not run the old V1 launcher. Do not manually run live morning or EOD engines during installation. The package does not auto-register scheduled tasks, activate the router, or send orders.
