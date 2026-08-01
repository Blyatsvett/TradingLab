from __future__ import annotations

import importlib.util
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "step9_morning_v2_support",
    ROOT / "tools" / "step9_morning_v2_support.py",
)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def _prices(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE intraday_prices("
            "datetime TEXT, open REAL, high REAL, low REAL, close REAL, "
            "ticker TEXT, source TEXT, collected_at_utc TEXT)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX ux ON intraday_prices(ticker, datetime)"
        )
        rows = []
        for number in range(29):
            ticker = f"T{number:02d}.ST"
            rows.extend(
                [
                    (
                        "2026-07-29 17:25:00",
                        1,
                        1,
                        1,
                        1,
                        ticker,
                        "x",
                        "",
                    ),
                    (
                        "2026-07-30 09:40:00",
                        2,
                        2,
                        2,
                        2,
                        ticker,
                        "x",
                        "",
                    ),
                    (
                        "2026-07-30 09:45:00",
                        3,
                        3,
                        3,
                        3,
                        ticker,
                        "x",
                        "",
                    ),
                    (
                        "2026-07-30 09:50:00",
                        4,
                        4,
                        4,
                        4,
                        ticker,
                        "x",
                        "",
                    ),
                ]
            )
        connection.executemany(
            "INSERT INTO intraday_prices VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )


def test_snapshot_is_filtered_closed_and_immutable(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    destination = tmp_path / "snap.db"
    _prices(source)
    before = mod._sha256(source)

    result = mod.create_snapshot(
        source,
        destination,
        "2026-07-30",
        "09:40",
    )

    assert result["snapshot_action"] == "CREATED_IMMUTABLE_SNAPSHOT"
    assert result["today_tickers"] == 29
    assert result["max_clock_today"] == "09:40"
    assert mod._sha256(source) == before
    with sqlite3.connect(destination) as connection:
        clocks = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT substr(datetime,12,5) "
                "FROM intraday_prices ORDER BY 1"
            )
        ]
    assert clocks == ["09:40", "17:25"]

    second = mod.create_snapshot(
        source,
        destination,
        "2026-07-30",
        "09:40",
    )
    assert second["snapshot_action"] == "EXISTING_IMMUTABLE_SNAPSHOT_RETURNED"


def test_snapshot_rejects_tamper_and_same_source_destination(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.db"
    destination = tmp_path / "snap.db"
    _prices(source)
    mod.create_snapshot(source, destination, "2026-07-30", "09:40")
    with destination.open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(mod.MorningV2Error, match="hash"):
        mod.create_snapshot(source, destination, "2026-07-30", "09:40")
    with pytest.raises(mod.MorningV2Error, match="different"):
        mod.create_snapshot(source, source, "2026-07-30", "09:40")


def _make_live_ledgers(
    root: Path,
    date: str = "2026-07-31",
) -> dict[str, Path]:
    paths = {
        name: root / f"{name}.db"
        for name in ["i", "l", "s", "r", "t", "u"]
    }
    batch_schema = (
        "CREATE TABLE shadow_decision_batches("
        "batch_id TEXT, session_date TEXT, prospective_status TEXT, "
        "run_mode TEXT, primary_regime TEXT, decision_rows INTEGER, "
        "eligible_rows INTEGER, active_guardrails INTEGER, "
        "batch_payload_hash TEXT, regime_point_in_time_pass INTEGER)"
    )
    for name, eligible in (("i", 0), ("l", 2)):
        with sqlite3.connect(paths[name]) as connection:
            connection.execute(batch_schema)
            connection.execute(
                "CREATE TABLE shadow_decisions("
                "session_date TEXT, contract_eligible INTEGER, "
                "decision_action TEXT, point_in_time_pass INTEGER)"
            )
            connection.execute(
                "INSERT INTO shadow_decision_batches "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    name.upper(),
                    date,
                    mod.CONFIRMATORY,
                    "MORNING_DECISION_SEAL",
                    "RANGE_LOW_VOL",
                    184,
                    eligible,
                    0,
                    "h",
                    1,
                ),
            )
            decision_rows = []
            for index in range(184):
                is_eligible = int(index < eligible)
                decision_rows.append(
                    (
                        date,
                        is_eligible,
                        "ELIGIBLE_PRIMARY" if is_eligible else "INELIGIBLE",
                        1,
                    )
                )
            connection.executemany(
                "INSERT INTO shadow_decisions VALUES (?,?,?,?)",
                decision_rows,
            )
    with sqlite3.connect(paths["s"]) as connection:
        connection.execute(
            "CREATE TABLE step9s_assignments("
            "assignment_id TEXT, session_date TEXT, prospective_status TEXT, "
            "primary_regime TEXT, source_step9l_batch_id TEXT, "
            "point_in_time_pass INTEGER, router_active INTEGER, "
            "order_sent INTEGER)"
        )
        connection.execute(
            "CREATE TABLE step9s_coverage_plans("
            "session_date TEXT, point_in_time_pass INTEGER, "
            "router_active INTEGER, order_sent INTEGER)"
        )
        connection.execute(
            "INSERT INTO step9s_assignments VALUES (?,?,?,?,?,?,?,?)",
            (
                "S",
                date,
                mod.CONFIRMATORY,
                "RANGE_LOW_VOL",
                "L",
                1,
                0,
                0,
            ),
        )
        connection.execute(
            "INSERT INTO step9s_coverage_plans VALUES (?,?,?,?)",
            (date, 1, 0, 0),
        )
    with sqlite3.connect(paths["r"]) as connection:
        connection.execute(
            "CREATE TABLE selector_batches("
            "batch_id TEXT, session_date TEXT, prospective_status TEXT, "
            "evidence_eligible INTEGER, candidate_rows INTEGER, "
            "selected_rows INTEGER, payload_hash TEXT)"
        )
        connection.execute(
            "CREATE TABLE selector_candidates("
            "session_date TEXT, selected INTEGER)"
        )
        connection.execute(
            "INSERT INTO selector_batches VALUES (?,?,?,?,?,?,?)",
            ("R", date, mod.CONFIRMATORY, 1, 2, 1, "h"),
        )
        connection.executemany(
            "INSERT INTO selector_candidates VALUES (?,?)",
            [(date, 1), (date, 0)],
        )
    with sqlite3.connect(paths["t"]) as connection:
        connection.execute(
            "CREATE TABLE step9t_prospective_batches("
            "batch_id TEXT, session_date TEXT, prospective_status TEXT, "
            "source_step9l_batch_id TEXT, source_regime TEXT, "
            "transition_state TEXT, ticker_row_count INTEGER, "
            "point_in_time_pass INTEGER, router_active INTEGER, "
            "order_sent INTEGER, batch_payload_hash TEXT)"
        )
        connection.execute(
            "INSERT INTO step9t_prospective_batches "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "T",
                date,
                mod.T_STATUS,
                "L",
                "RANGE_LOW_VOL",
                "MIXED_TRANSITION",
                29,
                1,
                0,
                0,
                "h",
            ),
        )
        connection.execute(
            "CREATE TABLE step9t_prospective_ticker_archetypes("
            "session_date TEXT, ticker TEXT, point_in_time_pass INTEGER, "
            "router_active INTEGER, order_sent INTEGER)"
        )
        connection.executemany(
            "INSERT INTO step9t_prospective_ticker_archetypes "
            "VALUES (?,?,?,?,?)",
            [
                (date, f"T{number:02d}.ST", 1, 0, 0)
                for number in range(29)
            ],
        )
    with sqlite3.connect(paths["u"]) as connection:
        connection.execute(
            "CREATE TABLE step9u_prospective_assignment_batches("
            "assignment_batch_id TEXT, session_date TEXT, "
            "prospective_status TEXT, source_step9t_batch_id TEXT, "
            "source_regime TEXT, transition_state TEXT, "
            "directional_candidate_rows INTEGER, selected_count INTEGER, "
            "selected_tickers TEXT, "
            "mandatory_control_active INTEGER, point_in_time_pass INTEGER, "
            "router_active INTEGER, order_sent INTEGER, "
            "batch_payload_hash TEXT)"
        )
        connection.execute(
            "INSERT INTO step9u_prospective_assignment_batches "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "U",
                date,
                mod.U_STATUS,
                "T",
                "RANGE_LOW_VOL",
                "MIXED_TRANSITION",
                2,
                2,
                "AAA.ST|BBB.ST",
                0,
                1,
                0,
                0,
                "h",
            ),
        )
        connection.execute(
            "CREATE TABLE step9u_prospective_candidates("
            "session_date TEXT, ticker TEXT, selected INTEGER, "
            "selected_rank INTEGER, point_in_time_pass INTEGER, "
            "router_active INTEGER, order_sent INTEGER)"
        )
        connection.executemany(
            "INSERT INTO step9u_prospective_candidates VALUES (?,?,?,?,?,?,?)",
            [
                (date, "AAA.ST", 1, 1, 1, 0, 0),
                (date, "BBB.ST", 1, 2, 1, 0, 0),
            ],
        )
    return paths


def test_status_verify_and_mock_verify_complete_chain(tmp_path: Path) -> None:
    paths = _make_live_ledgers(tmp_path)
    arguments = {
        "prices": tmp_path / "missing.db",
        "step9i": paths["i"],
        "step9l": paths["l"],
        "step9s": paths["s"],
        "step9r": paths["r"],
        "step9t": paths["t"],
        "step9u": paths["u"],
    }
    payload = mod.status("2026-07-31", **arguments)
    assert payload["live_complete"] is True
    assert payload["classification"] == "LIVE_COMPLETE"
    assert payload["step9u"]["selected_tickers"] == ["AAA.ST", "BBB.ST"]
    assert mod.verify(
        "2026-07-31",
        "all",
        **arguments,
    )["verification"] == "PASSED"
    assert mod.verify_mock(
        "2026-07-31",
        **arguments,
    )["mock_complete"] is True


def test_verify_rejects_unsafe_step9u(tmp_path: Path) -> None:
    paths = _make_live_ledgers(tmp_path)
    with sqlite3.connect(paths["u"]) as connection:
        connection.execute(
            "UPDATE step9u_prospective_assignment_batches "
            "SET selected_count=3"
        )
    with pytest.raises(mod.MorningV2Error, match="selected count"):
        mod.verify(
            "2026-07-31",
            "step9u",
            prices=tmp_path / "missing.db",
            step9i=paths["i"],
            step9l=paths["l"],
            step9s=paths["s"],
            step9r=paths["r"],
            step9t=paths["t"],
            step9u=paths["u"],
        )


@pytest.mark.parametrize(
    ("stage", "table", "column", "value", "message"),
    [
        (
            "s",
            "step9s_coverage_plans",
            "order_sent",
            1,
            "coverage-plan",
        ),
        (
            "t",
            "step9t_prospective_ticker_archetypes",
            "router_active",
            1,
            "ticker-row",
        ),
        (
            "u",
            "step9u_prospective_candidates",
            "point_in_time_pass",
            0,
            "point-in-time",
        ),
    ],
)
def test_verify_mock_rejects_unsafe_detail_rows(
    tmp_path: Path,
    stage: str,
    table: str,
    column: str,
    value: int,
    message: str,
) -> None:
    paths = _make_live_ledgers(tmp_path)
    with sqlite3.connect(paths[stage]) as connection:
        connection.execute(f'UPDATE "{table}" SET "{column}"=?', (value,))
    with pytest.raises(mod.MorningV2Error, match=message):
        mod.verify_mock(
            "2026-07-31",
            prices=tmp_path / "missing.db",
            step9i=paths["i"],
            step9l=paths["l"],
            step9s=paths["s"],
            step9r=paths["r"],
            step9t=paths["t"],
            step9u=paths["u"],
        )


def test_verify_mock_rejects_unrecognized_evidence_status(
    tmp_path: Path,
) -> None:
    paths = _make_live_ledgers(tmp_path)
    with sqlite3.connect(paths["t"]) as connection:
        connection.execute(
            "UPDATE step9t_prospective_batches SET prospective_status='UNKNOWN'"
        )
    with pytest.raises(mod.MorningV2Error, match="unrecognized"):
        mod.verify_mock(
            "2026-07-31",
            prices=tmp_path / "missing.db",
            step9i=paths["i"],
            step9l=paths["l"],
            step9s=paths["s"],
            step9r=paths["r"],
            step9t=paths["t"],
            step9u=paths["u"],
        )


def test_runtime_manifest_hashes_and_exclusive_glob(tmp_path: Path) -> None:
    dependency = tmp_path / "engine.py"
    dependency.write_text("VALUE = 1\n", encoding="utf-8")
    summary = tmp_path / "freeze" / "one" / "summary.json"
    summary.parent.mkdir(parents=True)
    summary.write_text("{}\n", encoding="utf-8")
    manifest = tmp_path / "runtime.json"
    manifest.write_text(
        json.dumps(
            {
                "files": {
                    "engine.py": mod._sha256(dependency),
                    "freeze/one/summary.json": mod._sha256(summary),
                },
                "exclusive_globs": {
                    "freeze/*/summary.json": [
                        "freeze/one/summary.json",
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    result = mod.verify_runtime_manifest(manifest, root=tmp_path)
    assert result["files_checked"] == 2
    assert result["exclusive_globs_checked"] == 1

    extra = tmp_path / "freeze" / "two" / "summary.json"
    extra.parent.mkdir(parents=True)
    extra.write_text("{}\n", encoding="utf-8")
    with pytest.raises(mod.MorningV2Error, match="glob inventory"):
        mod.verify_runtime_manifest(manifest, root=tmp_path)


def test_sqlite_backup_is_distinct_integral_and_read_only(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.db"
    destination = tmp_path / "backup.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE evidence(value TEXT)")
        connection.execute("INSERT INTO evidence VALUES ('sealed')")
    before = mod._sha256(source)
    result = mod.sqlite_backup(source, destination)
    assert result["status"] == "SQLITE_READ_ONLY_BACKUP_CREATED"
    assert mod._sha256(source) == before
    with sqlite3.connect(destination) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT value FROM evidence").fetchone()[0] == "sealed"
    with pytest.raises(mod.MorningV2Error, match="different"):
        mod.sqlite_backup(source, source)


def test_authentic_price_fixture_is_hash_pinned_and_materialized(
    tmp_path: Path,
) -> None:
    fixture_csv = tmp_path / "prices.csv"
    fixture_manifest = tmp_path / "prices.manifest.json"
    destination = tmp_path / "fixture.db"
    header = ",".join(mod.PRICE_FIXTURE_COLUMNS)
    rows = [
        (
            f"2026-07-30 09:45:00,1,2,0.5,1.5,T{number:02d}.ST,"
            "TEST,2026-07-30 07:45:52"
        )
        for number in range(29)
    ]
    fixture_csv.write_text(
        header + "\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )
    fixture_manifest.write_text(
        json.dumps(
            {
                "fixture_id": "TEST_AUTHENTIC_FIXTURE",
                "purpose": "ISOLATED_SEMANTIC_EQUIVALENCE_ONLY",
                "session_date": "2026-07-30",
                "cutoff": "09:45",
                "columns": list(mod.PRICE_FIXTURE_COLUMNS),
                "row_count": 29,
                "ticker_count": 29,
                "exact_0945_ticker_count": 29,
                "csv_sha256": mod._sha256(fixture_csv),
                "router_active": False,
                "orders_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    result = mod.build_price_fixture_db(
        fixture_csv,
        fixture_manifest,
        destination,
    )
    assert result["status"] == "AUTHENTIC_VALIDATION_PRICE_FIXTURE_MATERIALIZED"
    assert result["today_rows"] == 29
    assert result["today_tickers"] == 29
    assert result["router_active"] is False
    assert result["orders_enabled"] is False
    with sqlite3.connect(destination) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    tampered = tmp_path / "tampered.csv"
    shutil.copy2(fixture_csv, tampered)
    tampered.write_text(
        tampered.read_text(encoding="utf-8") + "tampered\n",
        encoding="utf-8",
    )
    with pytest.raises(mod.MorningV2Error, match="hash"):
        mod.build_price_fixture_db(
            tampered,
            fixture_manifest,
            tmp_path / "tampered.db",
        )


def test_compile_files_writes_no_bytecode(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text("answer = 42\n", encoding="utf-8")
    result = mod.compile_files([source])
    assert result["status"] == "PYTHON_SOURCE_COMPILE_CHECK_PASSED"
    assert result["bytecode_written"] is False
    assert not (tmp_path / "__pycache__").exists()


def _comparison_ledgers(root: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    stage_names = {
        "step9i": "i",
        "step9l": "l",
        "step9s": "s",
        "step9r": "r",
        "step9t": "t",
        "step9u": "u",
    }
    tables_by_stage: dict[str, dict[str, tuple[str, ...]]] = {}
    for _, (long_stage, table, fields, _) in (
        mod.SEMANTIC_COMPARISON_SPECS.items()
    ):
        stage = stage_names[long_stage]
        tables_by_stage.setdefault(stage, {})[table] = fields

    for stage, tables in tables_by_stage.items():
        path = root / f"{stage}.db"
        paths[stage] = path
        with sqlite3.connect(path) as connection:
            for table, fields in tables.items():
                columns = list(fields) + ["volatile_only"]
                connection.execute(
                    f'CREATE TABLE "{table}"('
                    + ",".join(f'"{column}" TEXT' for column in columns)
                    + ")"
                )
                values = []
                for column in columns:
                    if column == "session_date":
                        values.append("2026-07-30")
                    elif column == "row_json":
                        values.append(
                            json.dumps(
                                {
                                    "feature": "frozen",
                                    "prospective_status": mod.CONFIRMATORY,
                                    "evidence_eligible": True,
                                }
                            )
                        )
                    elif column == "volatile_only":
                        values.append("volatile")
                    else:
                        values.append(f"{stage}:{table}:{column}:frozen")
                connection.execute(
                    f'INSERT INTO "{table}" VALUES ('
                    + ",".join("?" for _ in columns)
                    + ")",
                    values,
                )
    return paths


@pytest.mark.parametrize(
    ("stage", "table", "expected_failure"),
    [
        ("s", "step9s_coverage_plans", "step9s_coverage_plan"),
        ("r", "selector_candidates", "step9r_candidates"),
        ("t", "step9t_prospective_ticker_archetypes", "step9t_archetypes"),
        ("u", "step9u_prospective_candidates", "step9u_candidates"),
    ],
)
def test_compare_validation_catches_material_semantic_changes(
    tmp_path: Path,
    stage: str,
    table: str,
    expected_failure: str,
) -> None:
    reference_root = tmp_path / "reference"
    candidate_root = tmp_path / "candidate"
    reference_root.mkdir()
    candidate_root.mkdir()
    reference = _comparison_ledgers(reference_root)
    candidate: dict[str, Path] = {}
    for name, path in reference.items():
        candidate[name] = candidate_root / path.name
        shutil.copy2(path, candidate[name])

    clean = mod.compare_validation(
        "2026-07-30",
        candidate["i"],
        candidate["l"],
        candidate["s"],
        candidate["r"],
        candidate["t"],
        candidate["u"],
        reference["i"],
        reference["l"],
        reference["s"],
        reference["r"],
        reference["t"],
        reference["u"],
    )
    assert clean["status"] == "PASSED"

    with sqlite3.connect(candidate[stage]) as connection:
        long_stage = f"step9{stage}"
        fields = next(
            fields
            for _, (spec_stage, spec_table, fields, _) in (
                mod.SEMANTIC_COMPARISON_SPECS.items()
            )
            if spec_stage == long_stage and spec_table == table
        )
        material_column = next(
            column
            for column in fields
            if column not in {"session_date", "row_json"}
        )
        connection.execute(
            f'UPDATE "{table}" SET "{material_column}"=?',
            ("materially-changed",),
        )
    changed = mod.compare_validation(
        "2026-07-30",
        candidate["i"],
        candidate["l"],
        candidate["s"],
        candidate["r"],
        candidate["t"],
        candidate["u"],
        reference["i"],
        reference["l"],
        reference["s"],
        reference["r"],
        reference["t"],
        reference["u"],
    )
    assert changed["status"] == "FAILED"
    assert expected_failure in changed["failed"]


def test_compare_validation_ignores_reconstruction_evidence_and_hash_cascades(
    tmp_path: Path,
) -> None:
    reference_root = tmp_path / "reference"
    candidate_root = tmp_path / "candidate"
    reference_root.mkdir()
    candidate_root.mkdir()
    reference = _comparison_ledgers(reference_root)
    candidate: dict[str, Path] = {}
    for name, path in reference.items():
        candidate[name] = candidate_root / path.name
        shutil.copy2(path, candidate[name])

    with sqlite3.connect(candidate["r"]) as connection:
        row = connection.execute(
            "SELECT row_json FROM selector_candidates"
        ).fetchone()
        payload = json.loads(str(row[0]))
        payload["prospective_status"] = (
            "SIMULATED_CLOCK_RECONSTRUCTION_NOT_CONFIRMATORY"
        )
        payload["evidence_eligible"] = False
        connection.execute(
            "UPDATE selector_candidates SET row_json=?",
            (json.dumps(payload),),
        )
    for path in candidate.values():
        with sqlite3.connect(path) as connection:
            for table_row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall():
                connection.execute(
                    f'UPDATE "{table_row[0]}" SET volatile_only=?',
                    ("candidate-provenance",),
                )

    result = mod.compare_validation(
        "2026-07-30",
        candidate["i"],
        candidate["l"],
        candidate["s"],
        candidate["r"],
        candidate["t"],
        candidate["u"],
        reference["i"],
        reference["l"],
        reference["s"],
        reference["r"],
        reference["t"],
        reference["u"],
    )
    assert result["status"] == "PASSED"
