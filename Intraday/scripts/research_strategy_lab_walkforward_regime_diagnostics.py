from __future__ import annotations

from pathlib import Path

import pandas as pd

from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.orb_config import ORB_INITIAL_CAPITAL, ORB_POSITION_SIZE
from Intraday.core.paths import DATA_DIR


INPUT_WALKFORWARD_TRADES_FILE = (
    DATA_DIR / "strategy_lab_ticker_walkforward_trades.csv"
)

INPUT_INTRADAY_MARKET_REGIME_FILE = (
    DATA_DIR / "intraday_market_regime.csv"
)

OUTPUT_REGIME_SUMMARY_FILE = (
    DATA_DIR / "strategy_lab_walkforward_regime_summary.csv"
)

OUTPUT_REGIME_PERIOD_SUMMARY_FILE = (
    DATA_DIR / "strategy_lab_walkforward_regime_period_summary.csv"
)

OUTPUT_REGIME_WATCHLIST_FILE = (
    DATA_DIR / "strategy_lab_walkforward_regime_watchlist.csv"
)

OUTPUT_REGIME_MATRIX_FILE = (
    DATA_DIR / "strategy_lab_walkforward_regime_matrix.csv"
)


MIN_TRADES_FOR_REGIME_CANDIDATE = 10
MIN_PERIODS_FOR_REGIME_CANDIDATE = 2
MIN_POSITIVE_PERIOD_SHARE = 0.60


BASE_REGIME_COLUMNS = [
    "gap_regime",
    "trend_regime",
    "breadth_regime",
    "volatility_regime",
    "opening_range_regime",
]


SUMMARY_COLUMNS = [
    "strategy_name",
    "summary_role",
    "regime_dimension",
    "regime_value",
    "basket_tickers",
    "basket_ticker_count",
    "periods_observed",
    "positive_periods",
    "negative_periods",
    "flat_periods",
    "positive_period_share",
    "selected_trades",
    "active_days",
    "first_date",
    "last_date",
    "total_account_return",
    "total_pnl_sek",
    "avg_trade_account_return",
    "median_trade_account_return",
    "best_trade_account_return",
    "worst_trade_account_return",
    "win_rate",
    "profit_factor",
    "max_drawdown",
    "avg_risk_pct",
    "max_risk_pct",
    "regime_candidate",
    "regime_status",
]

PERIOD_COLUMNS = [
    "period_id",
    "strategy_name",
    "summary_role",
    "regime_dimension",
    "regime_value",
    "basket_tickers",
    "basket_ticker_count",
    "selected_trades",
    "active_days",
    "first_date",
    "last_date",
    "total_account_return",
    "total_pnl_sek",
    "avg_trade_account_return",
    "win_rate",
    "profit_factor",
    "max_drawdown",
]

WATCHLIST_COLUMNS = [
    "watchlist_rank",
    "strategy_name",
    "summary_role",
    "regime_dimension",
    "regime_value",
    "basket_tickers",
    "basket_ticker_count",
    "periods_observed",
    "positive_periods",
    "positive_period_share",
    "selected_trades",
    "total_account_return",
    "total_pnl_sek",
    "profit_factor",
    "max_drawdown",
    "regime_status",
]

MATRIX_COLUMNS = [
    "strategy_name",
    "summary_role",
    "regime_dimension",
    "regime_value",
    "metric_name",
    "metric_value",
]


def read_required_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Required input file not found: {path}")

    df = pd.read_csv(path)

    if df.empty:
        raise RuntimeError(f"Required input file is empty: {path}")

    return df


def read_optional_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path)

    if df.empty:
        return pd.DataFrame()

    return df


def normalise_date_column(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()

    if "date" not in output.columns:
        if "entry_time" in output.columns:
            output["date"] = pd.to_datetime(
                output["entry_time"],
                errors="coerce",
            ).dt.strftime("%Y-%m-%d")
        else:
            raise ValueError("Could not find date or entry_time column.")

    output["date"] = pd.to_datetime(output["date"], errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )

    output = output.dropna(subset=["date"])

    return output


def attach_market_regime_if_needed(trades: pd.DataFrame) -> pd.DataFrame:
    output = trades.copy()

    existing_regime_columns = [
        col for col in BASE_REGIME_COLUMNS if col in output.columns
    ]

    if existing_regime_columns:
        return output

    regime = read_optional_csv(INPUT_INTRADAY_MARKET_REGIME_FILE)

    if regime.empty:
        print(
            "WARNING: No regime columns found in trades and "
            "intraday_market_regime.csv was not available."
        )
        return output

    regime = normalise_date_column(regime)

    regime_columns = [
        col for col in BASE_REGIME_COLUMNS if col in regime.columns
    ]

    if not regime_columns:
        print(
            "WARNING: intraday_market_regime.csv exists but contains "
            "no recognized regime columns."
        )
        return output

    merge_cols = ["date"] + regime_columns

    output = output.merge(
        regime[merge_cols].drop_duplicates(subset=["date"]),
        on="date",
        how="left",
    )

    return output


def build_combined_regime_columns(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()

    if {"trend_regime", "breadth_regime"}.issubset(output.columns):
        output["trend_breadth_regime"] = (
            output["trend_regime"].astype(str)
            + " | "
            + output["breadth_regime"].astype(str)
        )

    if {"gap_regime", "trend_regime"}.issubset(output.columns):
        output["gap_trend_regime"] = (
            output["gap_regime"].astype(str)
            + " | "
            + output["trend_regime"].astype(str)
        )

    if {"opening_range_regime", "trend_regime"}.issubset(output.columns):
        output["opening_range_trend_regime"] = (
            output["opening_range_regime"].astype(str)
            + " | "
            + output["trend_regime"].astype(str)
        )

    return output


def discover_regime_columns(df: pd.DataFrame) -> list[str]:
    candidates = []

    for col in df.columns:
        col_lower = col.lower()

        if col in BASE_REGIME_COLUMNS:
            candidates.append(col)
            continue

        if col in {
            "trend_breadth_regime",
            "gap_trend_regime",
            "opening_range_trend_regime",
        }:
            candidates.append(col)
            continue

        if col_lower.endswith("_regime") and col not in candidates:
            unique_count = df[col].dropna().astype(str).nunique()

            if 1 < unique_count <= 30:
                candidates.append(col)

    ordered = []

    preferred_order = [
        "gap_regime",
        "trend_regime",
        "breadth_regime",
        "volatility_regime",
        "opening_range_regime",
        "trend_breadth_regime",
        "gap_trend_regime",
        "opening_range_trend_regime",
    ]

    for col in preferred_order:
        if col in candidates and col not in ordered:
            ordered.append(col)

    for col in candidates:
        if col not in ordered:
            ordered.append(col)

    return ordered


def add_account_return_columns(trades: pd.DataFrame) -> pd.DataFrame:
    output = trades.copy()

    if "account_return" in output.columns:
        output["trade_account_return"] = pd.to_numeric(
            output["account_return"],
            errors="coerce",
        ).fillna(0.0)

    elif "net_return" in output.columns:
        output["trade_account_return"] = (
            pd.to_numeric(output["net_return"], errors="coerce").fillna(0.0)
            * ORB_POSITION_SIZE
        )

    elif "pnl_pct" in output.columns:
        output["trade_account_return"] = (
            pd.to_numeric(output["pnl_pct"], errors="coerce").fillna(0.0)
            * ORB_POSITION_SIZE
        )

    else:
        raise ValueError(
            "Could not find account_return, net_return, or pnl_pct column."
        )

    if "pnl_sek" in output.columns:
        output["trade_pnl_sek"] = pd.to_numeric(
            output["pnl_sek"],
            errors="coerce",
        ).fillna(0.0)
    else:
        output["trade_pnl_sek"] = (
            output["trade_account_return"] * ORB_INITIAL_CAPITAL
        )

    if "risk_pct" in output.columns:
        output["risk_pct"] = pd.to_numeric(
            output["risk_pct"],
            errors="coerce",
        ).fillna(0.0)
    else:
        output["risk_pct"] = 0.0

    return output


def calculate_profit_factor(returns: pd.Series) -> float:
    values = pd.to_numeric(returns, errors="coerce").fillna(0.0)

    gains = float(values[values > 0].sum())
    losses = float(values[values < 0].sum())

    if losses < 0:
        return gains / abs(losses)

    if gains > 0:
        return 999.0

    return 0.0


def calculate_max_drawdown(returns: pd.Series) -> float:
    values = pd.to_numeric(returns, errors="coerce").fillna(0.0)

    if values.empty:
        return 0.0

    equity = ORB_INITIAL_CAPITAL * (1.0 + values.cumsum())
    running_high = equity.cummax()
    drawdown = (equity / running_high) - 1.0

    return float(drawdown.min())


def summarize_group(group: pd.DataFrame) -> dict:
    returns = pd.to_numeric(
        group["trade_account_return"],
        errors="coerce",
    ).fillna(0.0)

    pnl = pd.to_numeric(
        group["trade_pnl_sek"],
        errors="coerce",
    ).fillna(0.0)

    selected_trades = int(len(group))
    active_days = int(group["date"].nunique()) if "date" in group.columns else 0

    if selected_trades == 0:
        return {
            "selected_trades": 0,
            "active_days": 0,
            "first_date": "",
            "last_date": "",
            "total_account_return": 0.0,
            "total_pnl_sek": 0.0,
            "avg_trade_account_return": 0.0,
            "median_trade_account_return": 0.0,
            "best_trade_account_return": 0.0,
            "worst_trade_account_return": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "avg_risk_pct": 0.0,
            "max_risk_pct": 0.0,
        }

    return {
        "selected_trades": selected_trades,
        "active_days": active_days,
        "first_date": str(group["date"].min()),
        "last_date": str(group["date"].max()),
        "total_account_return": float(returns.sum()),
        "total_pnl_sek": float(pnl.sum()),
        "avg_trade_account_return": float(returns.mean()),
        "median_trade_account_return": float(returns.median()),
        "best_trade_account_return": float(returns.max()),
        "worst_trade_account_return": float(returns.min()),
        "win_rate": float((returns > 0).mean()),
        "profit_factor": calculate_profit_factor(returns),
        "max_drawdown": calculate_max_drawdown(returns),
        "avg_risk_pct": float(group["risk_pct"].mean()),
        "max_risk_pct": float(group["risk_pct"].max()),
    }


def classify_regime_status(row: pd.Series) -> str:
    if row["selected_trades"] < MIN_TRADES_FOR_REGIME_CANDIDATE:
        return "INSUFFICIENT_TRADES"

    if row["periods_observed"] < MIN_PERIODS_FOR_REGIME_CANDIDATE:
        return "INSUFFICIENT_PERIODS"

    if (
        row["total_account_return"] > 0
        and row["profit_factor"] > 1.25
        and row["positive_period_share"] >= MIN_POSITIVE_PERIOD_SHARE
    ):
        return "PROMISING_REGIME"

    if (
        row["total_account_return"] > 0
        and row["profit_factor"] > 1.0
    ):
        return "MIXED_POSITIVE"

    if (
        row["total_account_return"] < 0
        and row["profit_factor"] < 0.9
    ):
        return "WEAK_REGIME"

    return "NEUTRAL_OR_MIXED"


def build_period_regime_summary(
    trades: pd.DataFrame,
    regime_columns: list[str],
) -> pd.DataFrame:
    rows = []

    for regime_col in regime_columns:
        temp = trades.copy()
        temp[regime_col] = temp[regime_col].fillna("unknown").astype(str)

        group_cols = [
            "period_id",
            "strategy_name",
            "summary_role",
            regime_col,
        ]

        optional_cols = [
            "basket_tickers",
            "basket_ticker_count",
        ]

        for col in optional_cols:
            if col in temp.columns:
                group_cols.append(col)

        grouped = temp.groupby(group_cols, dropna=False)

        for keys, group in grouped:
            if not isinstance(keys, tuple):
                keys = (keys,)

            key_map = dict(zip(group_cols, keys))

            summary = summarize_group(group)

            row = {
                "period_id": key_map.get("period_id", ""),
                "strategy_name": key_map.get("strategy_name", ""),
                "summary_role": key_map.get("summary_role", ""),
                "regime_dimension": regime_col,
                "regime_value": key_map.get(regime_col, "unknown"),
                "basket_tickers": key_map.get("basket_tickers", ""),
                "basket_ticker_count": key_map.get("basket_ticker_count", 0),
            }

            row.update(summary)
            rows.append(row)

    if not rows:
        return pd.DataFrame(columns=PERIOD_COLUMNS)

    period_summary = pd.DataFrame(rows)

    return period_summary[PERIOD_COLUMNS]


def build_regime_summary(
    trades: pd.DataFrame,
    period_summary: pd.DataFrame,
    regime_columns: list[str],
) -> pd.DataFrame:
    rows = []

    for regime_col in regime_columns:
        temp = trades.copy()
        temp[regime_col] = temp[regime_col].fillna("unknown").astype(str)

        group_cols = [
            "strategy_name",
            "summary_role",
            regime_col,
        ]

        optional_cols = [
            "basket_tickers",
            "basket_ticker_count",
        ]

        for col in optional_cols:
            if col in temp.columns:
                group_cols.append(col)

        grouped = temp.groupby(group_cols, dropna=False)

        for keys, group in grouped:
            if not isinstance(keys, tuple):
                keys = (keys,)

            key_map = dict(zip(group_cols, keys))

            strategy_name = key_map.get("strategy_name", "")
            summary_role = key_map.get("summary_role", "")
            regime_value = key_map.get(regime_col, "unknown")
            basket_tickers = key_map.get("basket_tickers", "")
            basket_ticker_count = key_map.get("basket_ticker_count", 0)

            summary = summarize_group(group)

            matching_periods = period_summary[
                period_summary["strategy_name"].eq(strategy_name)
                & period_summary["summary_role"].eq(summary_role)
                & period_summary["regime_dimension"].eq(regime_col)
                & period_summary["regime_value"].eq(regime_value)
                & period_summary["basket_tickers"].eq(basket_tickers)
            ].copy()

            periods_observed = int(matching_periods["period_id"].nunique())

            positive_periods = int(
                (
                    pd.to_numeric(
                        matching_periods["total_account_return"],
                        errors="coerce",
                    ).fillna(0.0)
                    > 0
                ).sum()
            )

            negative_periods = int(
                (
                    pd.to_numeric(
                        matching_periods["total_account_return"],
                        errors="coerce",
                    ).fillna(0.0)
                    < 0
                ).sum()
            )

            flat_periods = max(
                periods_observed - positive_periods - negative_periods,
                0,
            )

            positive_period_share = (
                positive_periods / periods_observed
                if periods_observed > 0
                else 0.0
            )

            row = {
                "strategy_name": strategy_name,
                "summary_role": summary_role,
                "regime_dimension": regime_col,
                "regime_value": regime_value,
                "basket_tickers": basket_tickers,
                "basket_ticker_count": basket_ticker_count,
                "periods_observed": periods_observed,
                "positive_periods": positive_periods,
                "negative_periods": negative_periods,
                "flat_periods": flat_periods,
                "positive_period_share": positive_period_share,
            }

            row.update(summary)
            rows.append(row)

    if not rows:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)

    summary_df = pd.DataFrame(rows)

    summary_df["regime_status"] = summary_df.apply(
        classify_regime_status,
        axis=1,
    )

    summary_df["regime_candidate"] = summary_df["regime_status"].eq(
        "PROMISING_REGIME"
    )

    summary_df = summary_df.sort_values(
        [
            "regime_candidate",
            "total_account_return",
            "profit_factor",
            "selected_trades",
            "positive_period_share",
        ],
        ascending=[False, False, False, False, False],
    ).reset_index(drop=True)

    return summary_df[SUMMARY_COLUMNS]


def build_regime_watchlist(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame(columns=WATCHLIST_COLUMNS)

    watchlist = summary[
        summary["regime_status"].isin(
            [
                "PROMISING_REGIME",
                "MIXED_POSITIVE",
                "WEAK_REGIME",
            ]
        )
    ].copy()

    if watchlist.empty:
        return pd.DataFrame(columns=WATCHLIST_COLUMNS)

    watchlist["sort_candidate"] = watchlist["regime_status"].eq(
        "PROMISING_REGIME"
    )

    watchlist = watchlist.sort_values(
        [
            "sort_candidate",
            "total_account_return",
            "profit_factor",
            "selected_trades",
        ],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)

    watchlist["watchlist_rank"] = watchlist.index + 1

    return watchlist[WATCHLIST_COLUMNS]


def build_regime_matrix(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame(columns=MATRIX_COLUMNS)

    metric_columns = [
        "selected_trades",
        "total_account_return",
        "profit_factor",
        "max_drawdown",
        "positive_period_share",
    ]

    rows = []

    for _, row in summary.iterrows():
        for metric_name in metric_columns:
            rows.append(
                {
                    "strategy_name": row["strategy_name"],
                    "summary_role": row["summary_role"],
                    "regime_dimension": row["regime_dimension"],
                    "regime_value": row["regime_value"],
                    "metric_name": metric_name,
                    "metric_value": row[metric_name],
                }
            )

    return pd.DataFrame(rows, columns=MATRIX_COLUMNS)


def main() -> None:
    print("\n=== STRATEGY LAB WALK-FORWARD REGIME DIAGNOSTICS ===")
    print("Research-only. This does not modify ORB paper/live trading.")
    print("Uses walk-forward test trades only.")
    print("Current regime labels are diagnostic, not live-tradeable filters.")

    trades = read_required_csv(INPUT_WALKFORWARD_TRADES_FILE)

    trades = normalise_date_column(trades)
    trades = attach_market_regime_if_needed(trades)
    trades = build_combined_regime_columns(trades)
    trades = add_account_return_columns(trades)

    if "evaluation_phase" in trades.columns:
        trades = trades[trades["evaluation_phase"].eq("test")].copy()

    required_columns = [
        "strategy_name",
        "summary_role",
        "period_id",
        "date",
    ]

    missing_required = [
        col for col in required_columns if col not in trades.columns
    ]

    if missing_required:
        raise ValueError(
            f"Missing required columns in walk-forward trades: {missing_required}"
        )

    regime_columns = discover_regime_columns(trades)

    if not regime_columns:
        raise RuntimeError(
            "No regime columns found. Run export_intraday_market_regime first, "
            "then rerun the walk-forward script if needed."
        )

    print("\nRegime dimensions found:")
    for col in regime_columns:
        print(f"- {col}")

    print(f"\nWalk-forward test trades loaded: {len(trades)}")
    print(f"Strategies: {trades['strategy_name'].nunique()}")
    print(f"Summary roles: {trades['summary_role'].nunique()}")
    print(f"Periods: {trades['period_id'].nunique()}")

    period_summary = build_period_regime_summary(
        trades=trades,
        regime_columns=regime_columns,
    )

    regime_summary = build_regime_summary(
        trades=trades,
        period_summary=period_summary,
        regime_columns=regime_columns,
    )

    watchlist = build_regime_watchlist(regime_summary)
    matrix = build_regime_matrix(regime_summary)

    export_csv_for_power_bi(
        regime_summary,
        OUTPUT_REGIME_SUMMARY_FILE,
        columns=SUMMARY_COLUMNS,
    )

    export_csv_for_power_bi(
        period_summary,
        OUTPUT_REGIME_PERIOD_SUMMARY_FILE,
        columns=PERIOD_COLUMNS,
    )

    export_csv_for_power_bi(
        watchlist,
        OUTPUT_REGIME_WATCHLIST_FILE,
        columns=WATCHLIST_COLUMNS,
    )

    export_csv_for_power_bi(
        matrix,
        OUTPUT_REGIME_MATRIX_FILE,
        columns=MATRIX_COLUMNS,
    )

    print("\n=== TOP REGIME SUMMARY ===")

    display_summary_cols = [
        "strategy_name",
        "summary_role",
        "regime_dimension",
        "regime_value",
        "periods_observed",
        "positive_periods",
        "selected_trades",
        "total_account_return",
        "profit_factor",
        "max_drawdown",
        "regime_status",
    ]

    print(
        regime_summary[display_summary_cols]
        .head(30)
        .to_string(index=False)
    )

    print("\n=== REGIME WATCHLIST ===")

    if watchlist.empty:
        print("No regime watchlist entries found.")
    else:
        display_watchlist_cols = [
            "watchlist_rank",
            "strategy_name",
            "summary_role",
            "regime_dimension",
            "regime_value",
            "periods_observed",
            "positive_periods",
            "selected_trades",
            "total_account_return",
            "profit_factor",
            "max_drawdown",
            "regime_status",
        ]

        print(
            watchlist[display_watchlist_cols]
            .head(30)
            .to_string(index=False)
        )

    print(f"\nSaved regime summary        -> {OUTPUT_REGIME_SUMMARY_FILE}")
    print(f"Saved regime period summary -> {OUTPUT_REGIME_PERIOD_SUMMARY_FILE}")
    print(f"Saved regime watchlist      -> {OUTPUT_REGIME_WATCHLIST_FILE}")
    print(f"Saved regime matrix         -> {OUTPUT_REGIME_MATRIX_FILE}")


if __name__ == "__main__":
    main()