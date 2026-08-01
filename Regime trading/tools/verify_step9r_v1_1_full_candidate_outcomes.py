from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from RegimeTrading.scripts import step9r_v1_candidate_ranking_research as step9r


PRICE_DB = ROOT / "data" / "step9i_shadow_intraday_prices.db"
V3_LEDGER = ROOT / "data" / "step9l_v3_selected_strategy_shadow_ledger.db"
RESEARCH_DB = ROOT / "data" / "ledgers" / "research" / "step9r_candidate_ranking_research_v1.db"


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise step9r.Step9RError(message)


def load_historical() -> pd.DataFrame:
    with closing(sqlite3.connect(f"file:{RESEARCH_DB.resolve().as_posix()}?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only = ON")
        frame = pd.read_sql_query(
            "SELECT * FROM candidate_outcomes ORDER BY date, contract_id, v3_rank, ticker",
            connection,
        )
    for column in [
        "model_eligible", "valid_setup", "winning_trade", "selected_by_v3",
        "counterfactual_trade_generated", "point_in_time_pass",
    ]:
        if column in frame:
            frame[column] = frame[column].map(step9r._bool)
    return frame


def build_temp_morning_db(path: Path, historical: pd.DataFrame, exact_july27: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    train = historical[
        historical["model_eligible"] & historical["date"].astype(str).lt("2026-07-27")
    ].copy()
    current = exact_july27[exact_july27["model_eligible"].map(step9r._bool)].copy()
    current["simple_expected_r"] = step9r.simple_expected_r_scores(train, current)
    current = current.sort_values(
        ["simple_expected_r", "ranking_metric", "ticker"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
    current["research_rank"] = range(1, len(current) + 1)
    selected = step9r._select_up_to_two(current, "simple_expected_r", require_positive=True)
    selected_keys = set(zip(selected["contract_id"].astype(str), selected["ticker"].astype(str)))
    current["selected"] = current.apply(
        lambda row: (str(row["contract_id"]), str(row["ticker"])) in selected_keys,
        axis=1,
    )
    current["selection_reason"] = np.where(
        current["selected"],
        "TOP_POSITIVE_EXPECTED_R_UP_TO_TWO",
        "NOT_TOP_TWO_OR_NONPOSITIVE_EXPECTED_R",
    )

    with closing(sqlite3.connect(path)) as connection:
        step9r._ensure_prospective_schema(connection)
        connection.execute(
            "INSERT INTO selector_batches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "S9R-2026-07-27-MORNING", "2026-07-27", "2026-07-27T09:47:00+02:00",
                step9r.EXPERIMENT_ID, step9r.SELECTOR_MODEL,
                str(train["date"].max()), int(train["date"].nunique()), len(train),
                step9r.CONFIRMATORY_STATUS, 1, len(current), len(selected),
                file_hash(PRICE_DB), file_hash(V3_LEDGER), "VERIFIER_BATCH_HASH",
            ),
        )
        for row in current.to_dict("records"):
            candidate_id = f"S9R-2026-07-27-MORNING|{row['contract_id']}|{row['ticker']}"
            connection.execute(
                "INSERT INTO selector_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    candidate_id, "S9R-2026-07-27-MORNING", "2026-07-27",
                    str(row["contract_id"]), str(row["ticker"]), str(row["test_role"]),
                    int(row["v3_rank"]), float(row["ranking_metric"]),
                    float(row["simple_expected_r"]), int(row["research_rank"]),
                    int(bool(row["selected"])), str(row["selection_reason"]), 1,
                    "{}", f"VERIFIER-{candidate_id}",
                ),
            )
        connection.commit()
    return current, selected


def main() -> None:
    protected = [PRICE_DB, V3_LEDGER, RESEARCH_DB]
    before = {str(path): file_hash(path) for path in protected}

    with closing(sqlite3.connect(f"file:{RESEARCH_DB.resolve().as_posix()}?mode=ro", uri=True)) as connection:
        require(connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "Research DB integrity failed.")

    historical = load_historical()
    require(len(historical) == 396, f"Expected 396 historical candidate rows, found {len(historical)}.")
    require(not historical.duplicated(["date", "contract_id", "ticker"]).any(), "Duplicate historical candidate keys.")
    primary = historical[historical["model_eligible"]].copy()
    require(len(primary) == 193, f"Expected 193 model-eligible candidates, found {len(primary)}.")
    require(primary["point_in_time_pass"].all(), "A model-eligible row failed point-in-time validation.")
    require(primary["max_router_source_label"].astype(str).le(step9r.LATEST_FEATURE_LABEL).all(), "Late feature label found.")

    # Recompute walk-forward selector comparisons from the current source.
    predictions = step9r.build_walk_forward_predictions(historical)
    comparisons = step9r.build_selector_comparisons(predictions).set_index("model")
    require(abs(float(comparisons.loc["CURRENT_V3_RANK_SAME_OOS_WINDOW", "total_pnl_sek"]) - 28.942419) < 1e-5, "V3 OOS result changed.")
    require(abs(float(comparisons.loc["SIMPLE_EXPECTED_R_SCORE", "total_pnl_sek"]) - 20.243710) < 1e-5, "Simple expected-R result changed.")
    require(float(comparisons.loc["CURRENT_V3_RANK_SAME_OOS_WINDOW", "total_pnl_sek"]) > float(comparisons.loc["SIMPLE_EXPECTED_R_SCORE", "total_pnl_sek"]), "Expected-R unexpectedly beats frozen V3.")

    # Current-source exact replay of the authoritative July 27 session.
    replay = step9r.replay_exact_v3(
        price_db=PRICE_DB,
        v3_ledger=V3_LEDGER,
        taxonomy_ledger=V3_LEDGER,
        start_date="2026-07-27",
        end_date="2026-07-27",
        rebuild_missing_taxonomy=False,
    )
    exact = step9r.build_candidate_outcomes(replay)
    stored = historical[historical["date"].astype(str).eq("2026-07-27")].copy()
    require(len(exact) == 32 and len(stored) == 32, "July 27 candidate row count mismatch.")
    core = [
        "date", "contract_id", "ticker", "test_role", "primary_regime", "direction",
        "ranking_metric", "v3_rank", "selected_by_v3", "valid_setup",
        "counterfactual_trade_generated", "entry_time", "entry_price", "stop_price",
        "target_price", "exit_time", "exit_price", "exit_reason",
        "risk_capped_net_pnl_sek", "net_r_after_costs", "winning_trade", "model_eligible",
    ]
    a = stored[core].sort_values(["date", "contract_id", "ticker"]).reset_index(drop=True)
    b = exact[core].sort_values(["date", "contract_id", "ticker"]).reset_index(drop=True)
    for column in core:
        if pd.api.types.is_numeric_dtype(a[column]) or pd.api.types.is_numeric_dtype(b[column]):
            require(
                np.allclose(
                    pd.to_numeric(a[column], errors="coerce"),
                    pd.to_numeric(b[column], errors="coerce"),
                    equal_nan=True, rtol=1e-10, atol=1e-10,
                ),
                f"July 27 numeric mismatch: {column}",
            )
        else:
            require(
                a[column].fillna("").astype(str).equals(b[column].fillna("").astype(str)),
                f"July 27 text mismatch: {column}",
            )

    with tempfile.TemporaryDirectory() as temp_dir:
        db = Path(temp_dir) / "step9r_v1_1_verifier.db"
        morning, selected = build_temp_morning_db(db, historical, exact)
        with (
            patch.object(step9r, "replay_exact_v3", return_value=replay),
            patch.object(step9r, "build_candidate_outcomes", return_value=exact),
            patch.object(step9r, "export_csv_for_power_bi"),
        ):
            selected_outcomes = step9r.run_prospective_eod("2026-07-27", prospective_db=db)
            selected_outcomes_again = step9r.run_prospective_eod("2026-07-27", prospective_db=db)
        with closing(sqlite3.connect(db)) as connection:
            all_outcomes = pd.read_sql_query("SELECT * FROM selector_candidate_outcomes", connection)
            selected_stored = pd.read_sql_query("SELECT * FROM selector_outcomes", connection)
        require(len(morning) == 23, f"Expected 23 morning candidates, found {len(morning)}.")
        require(len(selected) == 2, f"Expected 2 shadow selections, found {len(selected)}.")
        require(len(all_outcomes) == 23, f"Expected 23 all-candidate outcomes, found {len(all_outcomes)}.")
        require(len(selected_stored) == 2, f"Expected 2 selected outcomes, found {len(selected_stored)}.")
        require(len(selected_outcomes) == 2 and len(selected_outcomes_again) == 2, "EOD idempotency failed.")
        require(set(selected_stored["ticker"]) == {"ALFA.ST", "FABG.ST"}, "Unexpected July 27 selector tickers.")
        require(abs(float(all_outcomes["risk_capped_net_pnl_sek"].sum()) + 21.5842618067) < 1e-7, "All-candidate P&L mismatch.")
        require(abs(float(selected_stored["risk_capped_net_pnl_sek"].sum()) + 2.5497520131) < 1e-7, "Selected P&L mismatch.")

    after = {str(path): file_hash(path) for path in protected}
    require(before == after, "A protected real file changed during verification.")

    print("STEP9R_V1_1_FULL_CANDIDATE_OUTCOME_VERIFICATION: PASSED")
    print("HISTORICAL_CANDIDATES: 396 TOTAL / 193 MODEL-ELIGIBLE")
    print("JULY27_EXACT_REPLAY: 32/32 ROWS MATCHED")
    print("CURRENT_RANK_OOS_PNL_SEK: 28.942419")
    print("SIMPLE_EXPECTED_R_OOS_PNL_SEK: 20.243710")
    print("JULY27_PROSPECTIVE_CANDIDATES: 23")
    print("JULY27_SHADOW_SELECTIONS: ALFA.ST / FABG.ST")
    print("JULY27_ALL_CANDIDATE_OUTCOMES: 23 / -21.584262 SEK")
    print("JULY27_SELECTED_OUTCOMES: 2 / -2.549752 SEK")
    print("EOD_IDEMPOTENCY: PASSED")
    print("PROTECTED REAL FILES: BYTE-FOR-BYTE UNCHANGED")
    print("ROUTER ACTIVE: FALSE")
    print("NO ORDER WAS SENT")


if __name__ == "__main__":
    main()
