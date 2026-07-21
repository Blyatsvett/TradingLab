from __future__ import annotations

import pandas as pd

from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.market_regime import calculate_daily_market_regime
from Intraday.core.orb_config import ORB_INITIAL_CAPITAL, ORB_POSITION_SIZE
from Intraday.core.orb_research import (
    filter_to_completed_research_sessions,
    load_normalised_intraday_prices,
)
from Intraday.core.paths import DATA_DIR
from Intraday.core.research_shadow_config import get_research_shadow_definitions
from Intraday.scripts.research_strategy_lab_ticker_optimization import (
    build_all_strategy_candidates,
    discover_downloaded_tickers,
    select_trades_for_strategy_basket,
)


OUTPUT_TRADES_FILE = DATA_DIR / "strategy_lab_shadow_trades.csv"
OUTPUT_LATEST_TRADES_FILE = DATA_DIR / "strategy_lab_shadow_latest_trades.csv"
OUTPUT_DAILY_SUMMARY_FILE = DATA_DIR / "strategy_lab_shadow_daily_summary.csv"
OUTPUT_SUMMARY_FILE = DATA_DIR / "strategy_lab_shadow_summary.csv"
OUTPUT_EQUITY_FILE = DATA_DIR / "strategy_lab_shadow_equity_curve.csv"
OUTPUT_STATUS_FILE = DATA_DIR / "strategy_lab_shadow_status.csv"


REGIME_COLUMNS = [
    "market_gap_regime",
    "market_trend_regime",
    "market_breadth_regime",
    "market_intraday_trend_regime",
    "market_intraday_breadth_regime",
    "market_vwap_breadth_regime",
    "market_volatility_regime",
    "opening_range_regime",
    "composite_regime",
]


TRADE_COLUMNS = [
    "shadow_strategy_id",
    "research_tier",
    "summary_role",
    "strategy_name",
    "basket_tickers",
    "basket_ticker_count",
    "date",
    "ticker",
    "entry_time",
    "entry_price",
    "stop_price",
    "target_price",
    "exit_time",
    "exit_price",
    "exit_reason",
    "net_return",
    "account_return",
    "pnl_sek",
    "risk_pct",
    "target_return_pct",
    "r_multiple_achieved",
    "trade_duration_minutes",
    "setup_name",
    "side",
    "status_note",
] + REGIME_COLUMNS


SUMMARY_COLUMNS = [
    "shadow_strategy_id",
    "research_tier",
    "summary_role",
    "strategy_name",
    "basket_tickers",
    "basket_ticker_count",
    "selected_trades",
    "active_days",
    "first_date",
    "last_date",
    "latest_data_date",
    "latest_trade_count",
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
    "status_note",
]


DAILY_SUMMARY_COLUMNS = [
    "date",
    "shadow_strategy_id",
    "research_tier",
    "summary_role",
    "strategy_name",
    "basket_tickers",
    "basket_ticker_count",
    "selected_trades",
    "total_account_return",
    "total_pnl_sek",
    "avg_trade_account_return",
    "win_rate",
    "profit_factor",
    "max_drawdown",
]


EQUITY_COLUMNS = [
    "shadow_strategy_id",
    "research_tier",
    "summary_role",
    "strategy_name",
    "basket_tickers",
    "basket_ticker_count",
    "trade_number",
    "date",
    "entry_time",
    "ticker",
    "account_return",
    "pnl_sek",
    "cumulative_account_return",
    "equity",
    "running_high",
    "drawdown",
]


STATUS_COLUMNS = [
    "shadow_strategy_id",
    "research_tier",
    "summary_role",
    "strategy_name",
    "basket_tickers_configured",
    "basket_tickers_available",
    "basket_tickers_missing",
    "basket_ticker_count",
    "use_downloaded_universe",
    "selected_trades",
    "latest_data_date",
    "latest_trade_count",
    "ready_for_monday",
    "status_note",
]


def ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    output = df.copy()

    for col in columns:
        if col not in output.columns:
            output[col] = ""

    return output[columns].copy()


def normalise_candidate_dates(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()

    if "date" not in output.columns:
        output["date"] = pd.to_datetime(
            output["entry_time"],
            errors="coerce",
        ).dt.strftime("%Y-%m-%d")
    else:
        output["date"] = pd.to_datetime(
            output["date"],
            errors="coerce",
        ).dt.strftime("%Y-%m-%d")

    output = output.dropna(subset=["date"])

    return output


def add_account_return_columns(trades: pd.DataFrame) -> pd.DataFrame:
    output = trades.copy()

    if "net_return" in output.columns:
        output["net_return"] = pd.to_numeric(
            output["net_return"],
            errors="coerce",
        ).fillna(0.0)
    elif "pnl_pct" in output.columns:
        output["net_return"] = pd.to_numeric(
            output["pnl_pct"],
            errors="coerce",
        ).fillna(0.0)
    else:
        output["net_return"] = 0.0

    if "account_return" in output.columns:
        output["account_return"] = pd.to_numeric(
            output["account_return"],
            errors="coerce",
        ).fillna(0.0)
    else:
        output["account_return"] = output["net_return"] * ORB_POSITION_SIZE

    if "pnl_sek" in output.columns:
        output["pnl_sek"] = pd.to_numeric(
            output["pnl_sek"],
            errors="coerce",
        ).fillna(0.0)
    else:
        output["pnl_sek"] = output["account_return"] * ORB_INITIAL_CAPITAL

    for col in [
        "risk_pct",
        "target_return_pct",
        "r_multiple_achieved",
        "trade_duration_minutes",
        "entry_price",
        "stop_price",
        "target_price",
        "exit_price",
    ]:
        if col in output.columns:
            output[col] = pd.to_numeric(output[col], errors="coerce").fillna(0.0)
        else:
            output[col] = 0.0

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


def summarize_trades(group: pd.DataFrame) -> dict:
    if group.empty:
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

    returns = pd.to_numeric(
        group["account_return"],
        errors="coerce",
    ).fillna(0.0)

    pnl = pd.to_numeric(
        group["pnl_sek"],
        errors="coerce",
    ).fillna(0.0)

    risk = pd.to_numeric(
        group["risk_pct"],
        errors="coerce",
    ).fillna(0.0)

    return {
        "selected_trades": int(len(group)),
        "active_days": int(group["date"].nunique()),
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
        "avg_risk_pct": float(risk.mean()) if not risk.empty else 0.0,
        "max_risk_pct": float(risk.max()) if not risk.empty else 0.0,
    }


def add_shadow_metadata(
    selected: pd.DataFrame,
    definition: dict,
    basket_tickers: list[str],
) -> pd.DataFrame:
    output = selected.copy()

    if output.empty:
        return output

    output["shadow_strategy_id"] = definition["shadow_strategy_id"]
    output["research_tier"] = definition["research_tier"]
    output["summary_role"] = definition["summary_role"]
    output["strategy_name"] = definition["strategy_name"]
    output["basket_tickers"] = ", ".join(sorted(basket_tickers))
    output["basket_ticker_count"] = len(basket_tickers)
    output["status_note"] = definition.get("status_note", "")

    return output


def build_summary(
    trades: pd.DataFrame,
    definitions: list[dict],
    latest_data_date: str,
) -> pd.DataFrame:
    rows = []

    for definition in definitions:
        strategy_id = definition["shadow_strategy_id"]

        group = trades[
            trades["shadow_strategy_id"].eq(strategy_id)
        ].copy()

        if group.empty:
            configured_tickers = definition.get("basket_tickers", [])
            basket_tickers_text = ", ".join(sorted(configured_tickers))

            row = {
                "shadow_strategy_id": strategy_id,
                "research_tier": definition["research_tier"],
                "summary_role": definition["summary_role"],
                "strategy_name": definition["strategy_name"],
                "basket_tickers": basket_tickers_text,
                "basket_ticker_count": len(configured_tickers),
                "latest_data_date": latest_data_date,
                "latest_trade_count": 0,
                "status_note": definition.get("status_note", ""),
            }

            row.update(summarize_trades(group))
            rows.append(row)
            continue

        summary = summarize_trades(group)

        latest_trade_count = int(
            group[group["date"].eq(latest_data_date)].shape[0]
        )

        row = {
            "shadow_strategy_id": strategy_id,
            "research_tier": group["research_tier"].iloc[0],
            "summary_role": group["summary_role"].iloc[0],
            "strategy_name": group["strategy_name"].iloc[0],
            "basket_tickers": group["basket_tickers"].iloc[0],
            "basket_ticker_count": int(group["basket_ticker_count"].iloc[0]),
            "latest_data_date": latest_data_date,
            "latest_trade_count": latest_trade_count,
            "status_note": definition.get("status_note", ""),
        }

        row.update(summary)
        rows.append(row)

    summary_df = pd.DataFrame(rows)

    if summary_df.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)

    summary_df = summary_df.sort_values(
        [
            "research_tier",
            "total_account_return",
            "profit_factor",
            "selected_trades",
        ],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)

    return ensure_columns(summary_df, SUMMARY_COLUMNS)


def build_daily_summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=DAILY_SUMMARY_COLUMNS)

    rows = []

    group_cols = [
        "date",
        "shadow_strategy_id",
        "research_tier",
        "summary_role",
        "strategy_name",
        "basket_tickers",
        "basket_ticker_count",
    ]

    grouped = trades.groupby(group_cols, dropna=False)

    for keys, group in grouped:
        key_map = dict(zip(group_cols, keys))

        summary = summarize_trades(group)

        rows.append(
            {
                "date": key_map["date"],
                "shadow_strategy_id": key_map["shadow_strategy_id"],
                "research_tier": key_map["research_tier"],
                "summary_role": key_map["summary_role"],
                "strategy_name": key_map["strategy_name"],
                "basket_tickers": key_map["basket_tickers"],
                "basket_ticker_count": key_map["basket_ticker_count"],
                "selected_trades": summary["selected_trades"],
                "total_account_return": summary["total_account_return"],
                "total_pnl_sek": summary["total_pnl_sek"],
                "avg_trade_account_return": summary["avg_trade_account_return"],
                "win_rate": summary["win_rate"],
                "profit_factor": summary["profit_factor"],
                "max_drawdown": summary["max_drawdown"],
            }
        )

    daily = pd.DataFrame(rows)

    daily = daily.sort_values(
        ["date", "research_tier", "shadow_strategy_id"],
        ascending=[True, True, True],
    ).reset_index(drop=True)

    return ensure_columns(daily, DAILY_SUMMARY_COLUMNS)


def build_equity_curve(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=EQUITY_COLUMNS)

    rows = []

    sort_col = "entry_time" if "entry_time" in trades.columns else "date"

    for strategy_id, group in trades.groupby("shadow_strategy_id", dropna=False):
        group = group.copy()
        group[sort_col] = pd.to_datetime(group[sort_col], errors="coerce")
        group = group.sort_values([sort_col, "ticker"]).reset_index(drop=True)

        cumulative_pnl = 0.0
        running_high = ORB_INITIAL_CAPITAL

        for idx, row in group.iterrows():
            pnl_sek = float(row.get("pnl_sek", 0.0))
            account_return = float(row.get("account_return", 0.0))

            cumulative_pnl += pnl_sek
            equity = ORB_INITIAL_CAPITAL + cumulative_pnl
            running_high = max(running_high, equity)

            drawdown = (
                (equity / running_high) - 1.0
                if running_high > 0
                else 0.0
            )

            rows.append(
                {
                    "shadow_strategy_id": strategy_id,
                    "research_tier": row.get("research_tier", ""),
                    "summary_role": row.get("summary_role", ""),
                    "strategy_name": row.get("strategy_name", ""),
                    "basket_tickers": row.get("basket_tickers", ""),
                    "basket_ticker_count": row.get("basket_ticker_count", 0),
                    "trade_number": idx + 1,
                    "date": row.get("date", ""),
                    "entry_time": row.get("entry_time", ""),
                    "ticker": row.get("ticker", ""),
                    "account_return": account_return,
                    "pnl_sek": pnl_sek,
                    "cumulative_account_return": (
                        (equity / ORB_INITIAL_CAPITAL) - 1.0
                    ),
                    "equity": equity,
                    "running_high": running_high,
                    "drawdown": drawdown,
                }
            )

    equity_df = pd.DataFrame(rows)

    return ensure_columns(equity_df, EQUITY_COLUMNS)


def build_status(
    definitions: list[dict],
    trades: pd.DataFrame,
    all_tickers: list[str],
    latest_data_date: str,
) -> pd.DataFrame:
    rows = []

    downloaded_set = set(all_tickers)

    for definition in definitions:
        strategy_id = definition["shadow_strategy_id"]

        use_downloaded_universe = bool(
            definition.get("use_downloaded_universe", False)
        )

        configured_tickers = list(definition.get("basket_tickers", []))

        if use_downloaded_universe:
            available_tickers = list(all_tickers)
            missing_tickers = []
        else:
            available_tickers = [
                ticker for ticker in configured_tickers
                if ticker in downloaded_set
            ]
            missing_tickers = sorted(
                set(configured_tickers) - downloaded_set
            )

        group = trades[
            trades["shadow_strategy_id"].eq(strategy_id)
        ].copy()

        latest_trade_count = int(
            group[group["date"].eq(latest_data_date)].shape[0]
        ) if not group.empty else 0

        ready_for_monday = (
            len(available_tickers) > 0
            and len(missing_tickers) == 0
        )

        rows.append(
            {
                "shadow_strategy_id": strategy_id,
                "research_tier": definition["research_tier"],
                "summary_role": definition["summary_role"],
                "strategy_name": definition["strategy_name"],
                "basket_tickers_configured": ", ".join(sorted(configured_tickers)),
                "basket_tickers_available": ", ".join(sorted(available_tickers)),
                "basket_tickers_missing": ", ".join(sorted(missing_tickers)),
                "basket_ticker_count": len(available_tickers),
                "use_downloaded_universe": use_downloaded_universe,
                "selected_trades": int(len(group)),
                "latest_data_date": latest_data_date,
                "latest_trade_count": latest_trade_count,
                "ready_for_monday": ready_for_monday,
                "status_note": definition.get("status_note", ""),
            }
        )

    return ensure_columns(pd.DataFrame(rows), STATUS_COLUMNS)


def main() -> None:
    print("\n=== STRATEGY LAB DAILY SHADOW REPORT ===")
    print("Research-only. This does not modify ORB paper/live trading.")
    print("Production ORB paper trades remain separate.")
    print("Recommended use: run after market close for clean daily research output.")

    definitions = get_research_shadow_definitions()

    raw_prices = load_normalised_intraday_prices()
    raw_prices = filter_to_completed_research_sessions(
        raw_prices,
        verbose=True,
    )
    all_tickers = discover_downloaded_tickers(raw_prices)

    print(f"\nDownloaded ticker count: {len(all_tickers)}")
    print(", ".join(all_tickers))

    market_regime = calculate_daily_market_regime(raw_prices)

    candidates = build_all_strategy_candidates(
        raw_prices=raw_prices,
        all_tickers=all_tickers,
        market_regime=market_regime,
    )

    if candidates.empty:
        raise RuntimeError("No Strategy Lab candidates were created.")

    candidates = normalise_candidate_dates(candidates)

    latest_data_date = str(sorted(candidates["date"].dropna().unique())[-1])

    print(f"\nLatest candidate date: {latest_data_date}")
    print(f"Total candidates     : {len(candidates)}")
    print(f"Shadow definitions   : {len(definitions)}")

    selected_frames = []

    downloaded_set = set(all_tickers)

    for definition in definitions:
        strategy_id = definition["shadow_strategy_id"]
        strategy_name = definition["strategy_name"]
        summary_role = definition["summary_role"]

        use_downloaded_universe = bool(
            definition.get("use_downloaded_universe", False)
        )

        if use_downloaded_universe:
            basket_tickers = list(all_tickers)
        else:
            basket_tickers = [
                ticker for ticker in definition.get("basket_tickers", [])
                if ticker in downloaded_set
            ]

        print(
            f"\nSelecting {strategy_id}: "
            f"{strategy_name}, {summary_role}, "
            f"{len(basket_tickers)} tickers"
        )

        if not basket_tickers:
            print(f"WARNING: No available tickers for {strategy_id}")
            continue

        selected = select_trades_for_strategy_basket(
            candidates=candidates,
            strategy_name=strategy_name,
            basket_type=summary_role,
            tickers=basket_tickers,
        )

        selected = normalise_candidate_dates(selected) if not selected.empty else selected
        selected = add_account_return_columns(selected) if not selected.empty else selected

        selected = add_shadow_metadata(
            selected=selected,
            definition=definition,
            basket_tickers=basket_tickers,
        )

        print(f"Selected historical trades: {len(selected)}")

        if not selected.empty:
            selected_frames.append(selected)

    if selected_frames:
        trades = pd.concat(selected_frames, ignore_index=True)
        trades = normalise_candidate_dates(trades)
        trades = add_account_return_columns(trades)

        if "entry_time" in trades.columns:
            trades["entry_time"] = pd.to_datetime(
                trades["entry_time"],
                errors="coerce",
            )
            trades = trades.sort_values(
                ["entry_time", "shadow_strategy_id", "ticker"],
            ).reset_index(drop=True)
    else:
        trades = pd.DataFrame(columns=TRADE_COLUMNS)

    latest_trades = trades[trades["date"].eq(latest_data_date)].copy()

    summary = build_summary(
        trades=trades,
        definitions=definitions,
        latest_data_date=latest_data_date,
    )

    daily_summary = build_daily_summary(trades)
    equity_curve = build_equity_curve(trades)

    status = build_status(
        definitions=definitions,
        trades=trades,
        all_tickers=all_tickers,
        latest_data_date=latest_data_date,
    )

    trades_export = ensure_columns(trades, TRADE_COLUMNS)
    latest_export = ensure_columns(latest_trades, TRADE_COLUMNS)

    export_csv_for_power_bi(trades_export, OUTPUT_TRADES_FILE)
    export_csv_for_power_bi(latest_export, OUTPUT_LATEST_TRADES_FILE)
    export_csv_for_power_bi(daily_summary, OUTPUT_DAILY_SUMMARY_FILE)
    export_csv_for_power_bi(summary, OUTPUT_SUMMARY_FILE)
    export_csv_for_power_bi(equity_curve, OUTPUT_EQUITY_FILE)
    export_csv_for_power_bi(status, OUTPUT_STATUS_FILE)

    print("\n=== DAILY SHADOW STATUS ===")

    display_status_cols = [
        "shadow_strategy_id",
        "research_tier",
        "summary_role",
        "basket_ticker_count",
        "selected_trades",
        "latest_data_date",
        "latest_trade_count",
        "ready_for_monday",
    ]

    print(status[display_status_cols].to_string(index=False))

    print("\n=== DAILY SHADOW SUMMARY ===")

    display_summary_cols = [
        "shadow_strategy_id",
        "research_tier",
        "selected_trades",
        "latest_trade_count",
        "total_account_return",
        "profit_factor",
        "max_drawdown",
        "win_rate",
    ]

    print(summary[display_summary_cols].to_string(index=False))

    print(f"\nSaved shadow trades        -> {OUTPUT_TRADES_FILE}")
    print(f"Saved latest shadow trades -> {OUTPUT_LATEST_TRADES_FILE}")
    print(f"Saved daily summary        -> {OUTPUT_DAILY_SUMMARY_FILE}")
    print(f"Saved summary              -> {OUTPUT_SUMMARY_FILE}")
    print(f"Saved equity curve         -> {OUTPUT_EQUITY_FILE}")
    print(f"Saved status               -> {OUTPUT_STATUS_FILE}")


if __name__ == "__main__":
    main()