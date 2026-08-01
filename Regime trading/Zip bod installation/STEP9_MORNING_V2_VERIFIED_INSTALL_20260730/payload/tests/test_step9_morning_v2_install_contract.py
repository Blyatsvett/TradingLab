from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8-sig")


def test_live_orchestrator_parallelizes_i_l_and_has_safe_fallback() -> None:
    text = _read("run_step9_full_live_morning_v2.ps1")
    assert 'Start-StageProcess -Stage "step9i"' in text
    assert 'Start-StageProcess -Stage "step9l"' in text
    assert "run_step9_morning_mock_fallback_v2.ps1" in text
    assert "--allow-late-reconstruction" not in text
    assert "Get-OrphanedSessionChildProcesses" in text
    assert "MOCK_" in text and "MORNING_V2_FALLBACK_" in text
    assert "ROUTER ACTIVE: FALSE" in text
    assert "NO ORDER WAS SENT" in text
    assert 'Start-StageProcess -Stage "step9r"' in text
    assert "DEFERRED_BECAUSE_STEP9U_NOT_VERIFIED" not in text
    assert text.index('Start-StageProcess -Stage "step9r"') < text.index(
        "Wait-UntilStockholm -Target $Step9TDecisionTime"
    )


def test_live_orchestrator_uses_immutable_snapshots_and_wall_timeouts() -> None:
    text = _read("run_step9_full_live_morning_v2.ps1")
    assert "prices_through_0940.db" in text
    assert "prices_through_0945.db" in text
    assert "$ElapsedBeforeWait" in text
    assert "$RemainingMilliseconds" in text
    assert "DEFERRED MORNING EXPORTS" in text
    assert text.index("Finish-StageProcess -Job $UJob") < text.index(
        "DEFERRED MORNING EXPORTS"
    )


def test_fallback_is_isolated_bounded_and_prohibits_merge() -> None:
    text = _read("run_step9_morning_mock_fallback_v2.ps1")
    assert 'Join-Path $env:USERPROFILE "S9M"' in text
    assert "MOCK_REHEARSAL" in text
    assert 'real_ledger_merge = "PROHIBITED"' in text
    assert "REAL DATABASES AND SIDECARS: BYTE-FOR-BYTE UNCHANGED" in text
    assert "--allow-late-reconstruction" in text
    assert "--db" in text and "$MockPriceDb" in text
    assert "MockDataRecoveryLatestStart" in text
    assert '"18:00:00"' in text
    assert "The fallback result file must be written inside the real logs" in text
    assert "(?:db|sqlite|sqlite3)" in text
    assert "*.sqlite3-journal" in text


def test_scheduler_requires_preflight_and_builds_primary_watchdog() -> None:
    text = _read("register_step9_morning_v2_tasks.ps1")
    assert "09:44:20" in text
    assert "09:44:50" in text
    assert '-Role "PRIMARY"' in text
    assert '-Role "WATCHDOG"' in text
    assert "WakeToRun" in text
    assert "STEP9_MORNING_V2_PREFLIGHT_QUALIFIED" in text
    assert "databases_and_sidecars_unchanged" in text
    assert "$ReceiptTemp" in text
    assert "New-StockholmInstant" in text
    assert "machine_local_target" in text
    assert "New-TimeSpan -Hours 4" in text
    assert "replaced_task_recovery_xml" in text


def test_preflight_is_full_or_diagnostic_and_does_not_write_bytecode() -> None:
    text = _read("run_step9_full_tonight_preflight_v2.ps1")
    assert '"compile-files"' in text
    assert '"py_compile"' not in text
    assert '"no:cacheprovider"' in text
    assert "STEP9_MORNING_V2_PREFLIGHT_DIAGNOSTIC_ONLY" in text
    assert "STEP9_MORNING_V2_PREFLIGHT_QUALIFIED" in text
    assert "databases_and_sidecars_unchanged" in text
    assert "(?:db|sqlite|sqlite3)" in text


def test_validation_compares_full_semantics_and_times_critical_stages() -> None:
    validation = _read("run_step9_morning_v2_validation.ps1")
    support = _read("tools/step9_morning_v2_support.py")
    assert 'deadline_critical_stages = @("step9i", "step9l", "step9s", "step9t", "step9u")' in validation
    assert 'noncritical_stages = @("step9r")' in validation
    assert "IL_DECISION_FIELDS" in support
    assert "U_CANDIDATE_FIELDS" in support
    assert "step9s_coverage_plan" in support
    assert "step9r_candidates" in support
    assert "step9t_archetypes" in support
    assert "step9u_candidates" in support
    assert "ISOLATED COLLECTOR BENCHMARK" in validation
    assert "CollectorPlanningSeconds" in validation
    assert "Step9SLatestStartMargin" in validation
    assert "Step9TLatestStartMargin" in validation
    assert "Step9ULatestStartMargin" in validation
    assert '"fixture-db"' in validation
    assert "AuthenticFixtureDb" in validation
    assert "SourcePrice0940" in validation
    assert "SourcePrice0945" in validation
    assert "morning_price_snapshot_hash" not in support.split(
        "T_BATCH_FIELDS = (", 1
    )[1].split(")", 1)[0]


def test_all_powershell_process_waits_are_bounded() -> None:
    powershell = list(ROOT.rglob("*.ps1"))
    assert powershell
    for path in powershell:
        assert "WaitForExit()" not in path.read_text(encoding="utf-8-sig")


def test_stage_runner_disables_exports_on_deadline_critical_path() -> None:
    text = _read("RegimeTrading/scripts/step9_morning_v2_stage_runner.py")
    assert text.count("export_outputs_after=False") >= 5
    assert '"export-all"' in text
