from __future__ import annotations

from itertools import combinations

import pandas as pd

from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.market_regime import (
    attach_market_regime,
    calculate_daily_market_regime,
)
from Intraday.core.orb_config import (
    ORB_ALLOWED_TICKERS,
    ORB_INITIAL_CAPITAL,
    ORB_POSITION_SIZE,
)
from Intraday.core.orb_research import load_normalised_intraday_prices
from Intraday.core.paths import DATA_DIR
from Intraday.scripts.research_intraday_strategy_lab import (
    GAP_DOWN_RECOVERY_NAME,
    ORB_BREAKOUT_NAME,
    ORB_PULLBACK_NAME,
    PREVIOUS_DAY_HIGH_BREAKOUT_NAME,
    VWAP_RECLAIM_NAME,
    build_gap_down_recovery_candidates,
    build_orb_breakout_candidates,
    build_orb_pullback_candidates,
    build_previous_day_high_breakout_candidates,
    build_vwap_reclaim_candidates,
    calculate_daily_references,
    calculate_profit_factor,
    normalise_candidate_columns,
    prepare_prices,
    select_trades_by_strategy,
)


OUTPUT_TICKER_PERFORMANCE_FILE = (
    DATA_DIR / "strategy_lab_ticker_performance.csv"
)
OUTPUT_BASKET_OPTIMIZATION_FILE = (
    DATA_DIR / "strategy_lab_ticker_basket_optimization.csv"
)
OUTPUT_OPTIMIZATION_SUMMARY_FILE = (
    DATA_DIR / "strategy_lab_ticker_optimization_summary.csv"
)
OUTPUT_BASKET_TRADES_FILE = (
    DATA_DIR / "strategy_lab_ticker_basket_trades.csv"
)
OUTPUT_BASKET_EQUITY_FILE = (
    DATA_DIR / "strategy_lab_ticker_basket_equity_curve.csv"
)
OUTPUT_BASKET_REGIME_SUMMARY_FILE = (
    DATA_DIR / "strategy_lab_ticker_basket_regime_summary.csv"
)
OUTPUT_ALL_CANDIDATES_FILE = (
    DATA_DIR / "strategy_lab_ticker_optimization_candidates.csv"
)

STRATEGIES = [
    ORB_BREAKOUT_NAME,
    ORB_PULLBACK_NAME,
    VWAP_RECLAIM_NAME,
    GAP_DOWN_RECOVERY_NAME,
    PREVIOUS_DAY_HIGH_BREAKOUT_NAME,
]

BASKET_SIZES_TO_TEST = [3, 5, 7]

MIN_TRADES_FOR_RESEARCH_CANDIDATE = 20
MIN_ACTIVE_DAYS_FOR_RESEARCH_CANDIDATE = 10

MAX_TICKERS_FOR_COMBO_SEARCH = 10


def ticker_list_to_string(tickers: list[str]) -> str:
    return ", ".join(sorted(tickers))


def make_basket_id(
    strategy_name: str,
    basket_type: str,
    tickers: list[str],
) -> str:
    safe_strategy = strategy_name.replace(" ", "_")
    ticker_part = "_".join(sorted(tickers))
    return f"{basket_type}__{safe_strategy}__{ticker_part}"


def discover_downloaded_tickers(raw_prices: pd.DataFrame) -> list[str]:
    prices = prepare_prices(raw_prices, allowed_tickers=None)
    return sorted(prices["ticker"].dropna().unique())


def build_all_strategy_candidates(
    raw_prices: pd.DataFrame,
    all_tickers: list[str],
    market_regime: pd.DataFrame,
) -> pd.DataFrame:
    prices = prepare_prices(raw_prices, allowed_tickers=all_tickers)
    daily_refs = calculate_daily_references(prices)

    frames = []

    print("\n--- Building all-ticker ORB breakout candidates ---")
    orb_breakout = build_orb_breakout_candidates(
        raw_prices,
        allowed_tickers=all_tickers,
    )
    print(f"{ORB_BREAKOUT_NAME}: {len(orb_breakout)} candidates")
    frames.append(orb_breakout)

    print("\n--- Building all-ticker ORB pullback/retest candidates ---")
    orb_pullback = build_orb_pullback_candidates(prices)
    print(f"{ORB_PULLBACK_NAME}: {len(orb_pullback)} candidates")
    frames.append(orb_pullback)

    print("\n--- Building all-ticker VWAP reclaim candidates ---")
    vwap_reclaim = build_vwap_reclaim_candidates(prices)
    print(f"{VWAP_RECLAIM_NAME}: {len(vwap_reclaim)} candidates")
    frames.append(vwap_reclaim)

    print("\n--- Building all-ticker gap-down recovery candidates ---")
    gap_recovery = build_gap_down_recovery_candidates(prices, daily_refs)
    print(f"{GAP_DOWN_RECOVERY_NAME}: {len(gap_recovery)} candidates")
    frames.append(gap_recovery)

    print("\n--- Building all-ticker previous-day high breakout candidates ---")
    prev_high_breakout = build_previous_day_high_breakout_candidates(
        prices,
        daily_refs,
    )
    print(f"{PREVIOUS_DAY_HIGH_BREAKOUT_NAME}: {len(prev_high_breakout)} candidates")
    frames.append(prev_high_breakout)

    non_empty_frames = [
        frame for frame in frames if frame is not None and not frame.empty
    ]

    if not non_empty_frames:
        return pd.DataFrame()

    candidates = pd.concat(non_empty_frames, ignore_index=True)
    candidates = normalise_candidate_columns(candidates)
    candidates = attach_market_regime(candidates, market_regime, date_col="date")

    return candidates


def select_trades_for_strategy_basket(
    candidates: pd.DataFrame,
    strategy_name: str,
    basket_type: str,
    tickers: list[str],
) -> pd.DataFrame:
    basket_candidates = candidates[
        candidates["strategy_name"].eq(strategy_name)
        & candidates["ticker"].isin(tickers)
    ].copy()

    if basket_candidates.empty:
        return pd.DataFrame()

    selected = select_trades_by_strategy(basket_candidates)

    if selected.empty:
        return selected

    basket_id = make_basket_id(strategy_name, basket_type, tickers)

    selected["basket_id"] = basket_id
    selected["basket_type"] = basket_type
    selected["basket_tickers"] = ticker_list_to_string(tickers)
    selected["basket_ticker_count"] = len(tickers)
    selected["position_size_pct"] = ORB_POSITION_SIZE

    return selected


def build_equity_curve_for_run(
    selected_trades: pd.DataFrame,
    strategy_name: str,
    basket_type: str,
    tickers: list[str],
) -> pd.DataFrame:
    basket_id = make_basket_id(strategy_name, basket_type, tickers)
    basket_tickers = ticker_list_to_string(tickers)

    rows = []

    equity = ORB_INITIAL_CAPITAL
    peak_equity = ORB_INITIAL_CAPITAL

    rows.append(
        {
            "basket_id": basket_id,
            "strategy_name": strategy_name,
            "basket_type": basket_type,
            "basket_tickers": basket_tickers,
            "basket_ticker_count": len(tickers),
            "trade_number": 0,
            "date": "",
            "ticker": "START",
            "entry_time": "",
            "exit_time": "",
            "net_return": 0.0,
            "account_return": 0.0,
            "pnl_sek": 0.0,
            "equity": equity,
            "cumulative_return": 0.0,
            "drawdown_pct": 0.0,
            "position_size_pct": ORB_POSITION_SIZE,
        }
    )

    if selected_trades.empty:
        return pd.DataFrame(rows)

    trades = selected_trades.sort_values("entry_time").reset_index(drop=True)

    for idx, trade in trades.iterrows():
        account_return = float(trade["net_return"]) * ORB_POSITION_SIZE
        pnl_sek = ORB_INITIAL_CAPITAL * account_return

        equity += pnl_sek
        peak_equity = max(peak_equity, equity)

        cumulative_return = (equity / ORB_INITIAL_CAPITAL) - 1.0
        drawdown_pct = (equity / peak_equity) - 1.0

        rows.append(
            {
                "basket_id": basket_id,
                "strategy_name": strategy_name,
                "basket_type": basket_type,
                "basket_tickers": basket_tickers,
                "basket_ticker_count": len(tickers),
                "trade_number": idx + 1,
                "date": trade["date"],
                "ticker": trade["ticker"],
                "entry_time": trade["entry_time"],
                "exit_time": trade["exit_time"],
                "net_return": trade["net_return"],
                "account_return": account_return,
                "pnl_sek": pnl_sek,
                "equity": equity,
                "cumulative_return": cumulative_return,
                "drawdown_pct": drawdown_pct,
                "position_size_pct": ORB_POSITION_SIZE,
            }
        )

    return pd.DataFrame(rows)


def summarize_strategy_basket(
    selected_trades: pd.DataFrame,
    candidates: pd.DataFrame,
    strategy_name: str,
    basket_type: str,
    tickers: list[str],
) -> dict:
    basket_id = make_basket_id(strategy_name, basket_type, tickers)

    basket_candidates = candidates[
        candidates["strategy_name"].eq(strategy_name)
        & candidates["ticker"].isin(tickers)
    ].copy()

    equity_curve = build_equity_curve_for_run(
        selected_trades=selected_trades,
        strategy_name=strategy_name,
        basket_type=basket_type,
        tickers=tickers,
    )

    candidate_count = len(basket_candidates)
    selected_count = len(selected_trades)

    if selected_trades.empty:
        return {
            "basket_id": basket_id,
            "strategy_name": strategy_name,
            "basket_type": basket_type,
            "basket_tickers": ticker_list_to_string(tickers),
            "basket_ticker_count": len(tickers),
            "candidate_trades": candidate_count,
            "selected_trades": 0,
            "active_days": 0,
            "first_date": "",
            "last_date": "",
            "final_equity": ORB_INITIAL_CAPITAL,
            "total_return": 0.0,
            "total_pnl_sek": 0.0,
            "win_rate": 0.0,
            "avg_trade": 0.0,
            "median_trade": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "avg_risk_pct": 0.0,
            "max_risk_pct": 0.0,
            "target_count": 0,
            "stop_count": 0,
            "close_count": 0,
            "meets_min_trades": False,
            "meets_min_active_days": False,
            "research_candidate": False,
        }

    trades = selected_trades.copy()
    pnl_sek = trades["net_return"] * ORB_POSITION_SIZE * ORB_INITIAL_CAPITAL
    exit_reasons = trades["exit_reason"].astype(str).str.lower()

    final_equity = float(equity_curve["equity"].iloc[-1])
    total_return = (final_equity / ORB_INITIAL_CAPITAL) - 1.0
    active_days = int(trades["date"].nunique())

    meets_min_trades = selected_count >= MIN_TRADES_FOR_RESEARCH_CANDIDATE
    meets_min_active_days = active_days >= MIN_ACTIVE_DAYS_FOR_RESEARCH_CANDIDATE

    research_candidate = (
        meets_min_trades
        and meets_min_active_days
        and total_return > 0
        and calculate_profit_factor(pnl_sek) > 1.0
    )

    return {
        "basket_id": basket_id,
        "strategy_name": strategy_name,
        "basket_type": basket_type,
        "basket_tickers": ticker_list_to_string(tickers),
        "basket_ticker_count": len(tickers),
        "candidate_trades": candidate_count,
        "selected_trades": selected_count,
        "active_days": active_days,
        "first_date": trades["date"].min(),
        "last_date": trades["date"].max(),
        "final_equity": final_equity,
        "total_return": total_return,
        "total_pnl_sek": float(pnl_sek.sum()),
        "win_rate": float((trades["net_return"] > 0).mean()),
        "avg_trade": float(trades["net_return"].mean()),
        "median_trade": float(trades["net_return"].median()),
        "best_trade": float(trades["net_return"].max()),
        "worst_trade": float(trades["net_return"].min()),
        "profit_factor": calculate_profit_factor(pnl_sek),
        "max_drawdown": float(equity_curve["drawdown_pct"].min()),
        "avg_risk_pct": float(trades["risk_pct"].mean()),
        "max_risk_pct": float(trades["risk_pct"].max()),
        "target_count": int((exit_reasons == "target").sum()),
        "stop_count": int((exit_reasons == "stop").sum()),
        "close_count": int((exit_reasons == "close").sum()),
        "meets_min_trades": meets_min_trades,
        "meets_min_active_days": meets_min_active_days,
        "research_candidate": research_candidate,
    }


def build_ticker_performance(
    candidates: pd.DataFrame,
    all_tickers: list[str],
) -> pd.DataFrame:
    rows = []

    for strategy_name in STRATEGIES:
        for ticker in all_tickers:
            selected = select_trades_for_strategy_basket(
                candidates=candidates,
                strategy_name=strategy_name,
                basket_type="single_ticker",
                tickers=[ticker],
            )

            row = summarize_strategy_basket(
                selected_trades=selected,
                candidates=candidates,
                strategy_name=strategy_name,
                basket_type="single_ticker",
                tickers=[ticker],
            )

            row["ticker"] = ticker
            rows.append(row)

    ticker_performance = pd.DataFrame(rows)

    if ticker_performance.empty:
        return ticker_performance

    ticker_performance = ticker_performance.sort_values(
        ["strategy_name", "total_return", "profit_factor"],
        ascending=[True, False, False],
    ).reset_index(drop=True)

    ticker_performance["ticker_rank_within_strategy"] = (
        ticker_performance.groupby("strategy_name").cumcount() + 1
    )

    return ticker_performance


def build_basket_optimization(
    candidates: pd.DataFrame,
    all_tickers: list[str],
    ticker_performance: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    current_orb_tickers = [
        ticker for ticker in ORB_ALLOWED_TICKERS if ticker in all_tickers
    ]

    total_specs = 0

    strategy_specs = {}

    for strategy_name in STRATEGIES:
        ranked = ticker_performance[
            ticker_performance["strategy_name"].eq(strategy_name)
        ].copy()

        ranked = ranked.sort_values(
            ["research_candidate", "total_return", "profit_factor", "selected_trades"],
            ascending=[False, False, False, False],
        )

        top_strategy_tickers = (
            ranked["ticker"]
            .dropna()
            .astype(str)
            .head(MAX_TICKERS_FOR_COMBO_SEARCH)
            .tolist()
        )

        basket_specs = []
        basket_specs.append(("current_orb_basket", current_orb_tickers))
        basket_specs.append(("all_downloaded", all_tickers))

        for basket_size in BASKET_SIZES_TO_TEST:
            if basket_size <= len(top_strategy_tickers):
                for ticker_combo in combinations(top_strategy_tickers, basket_size):
                    basket_specs.append((f"combo_{basket_size}", list(ticker_combo)))

        strategy_specs[strategy_name] = basket_specs
        total_specs += len(basket_specs)

    completed = 0

    print(
        f"\nTesting {total_specs} strategy/basket combinations "
        f"using top {MAX_TICKERS_FOR_COMBO_SEARCH} tickers per strategy..."
    )

    for strategy_name in STRATEGIES:
        for basket_type, tickers in strategy_specs[strategy_name]:
            completed += 1

            selected = select_trades_for_strategy_basket(
                candidates=candidates,
                strategy_name=strategy_name,
                basket_type=basket_type,
                tickers=tickers,
            )

            row = summarize_strategy_basket(
                selected_trades=selected,
                candidates=candidates,
                strategy_name=strategy_name,
                basket_type=basket_type,
                tickers=tickers,
            )

            row["combo_search_ticker_count"] = (
                MAX_TICKERS_FOR_COMBO_SEARCH
                if basket_type.startswith("combo_")
                else len(all_tickers)
            )

            rows.append(row)

            if completed % 250 == 0:
                print(f"Completed {completed}/{total_specs}")

    optimization = pd.DataFrame(rows)

    if optimization.empty:
        return optimization

    optimization = optimization.sort_values(
        ["strategy_name", "basket_type", "total_return", "profit_factor"],
        ascending=[True, True, False, False],
    ).reset_index(drop=True)

    optimization["basket_rank_within_strategy_type"] = (
        optimization.groupby(["strategy_name", "basket_type"]).cumcount() + 1
    )

    return optimization


def build_optimization_summary(
    optimization: pd.DataFrame,
) -> pd.DataFrame:
    if optimization.empty:
        return optimization

    rows = []

    reference_types = [
        "current_orb_basket",
        "all_downloaded",
    ]

    combo_types = [
        f"combo_{size}" for size in BASKET_SIZES_TO_TEST
    ]

    for strategy_name in STRATEGIES:
        strategy_rows = optimization[
            optimization["strategy_name"].eq(strategy_name)
        ].copy()

        for basket_type in reference_types:
            reference = strategy_rows[
                strategy_rows["basket_type"].eq(basket_type)
            ].copy()

            if reference.empty:
                continue

            row = reference.iloc[0].to_dict()
            row["summary_role"] = basket_type
            rows.append(row)

        for basket_type in combo_types:
            combos = strategy_rows[
                strategy_rows["basket_type"].eq(basket_type)
            ].copy()

            if combos.empty:
                continue

            combos = combos.sort_values(
                ["total_return", "profit_factor", "max_drawdown"],
                ascending=[False, False, False],
            )

            best = combos.iloc[0].to_dict()
            best["summary_role"] = f"best_{basket_type}"
            rows.append(best)

    summary = pd.DataFrame(rows)

    if summary.empty:
        return summary

    summary = summary.sort_values(
        ["strategy_name", "summary_role"]
    ).reset_index(drop=True)

    return summary


def build_key_basket_outputs(
    candidates: pd.DataFrame,
    optimization_summary: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if optimization_summary.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    trade_frames = []
    equity_frames = []

    for _, row in optimization_summary.iterrows():
        tickers = [
            ticker.strip()
            for ticker in str(row["basket_tickers"]).split(",")
            if ticker.strip()
        ]

        selected = select_trades_for_strategy_basket(
            candidates=candidates,
            strategy_name=row["strategy_name"],
            basket_type=row["summary_role"],
            tickers=tickers,
        )

        if not selected.empty:
            selected["summary_role"] = row["summary_role"]
            trade_frames.append(selected)

        equity = build_equity_curve_for_run(
            selected_trades=selected,
            strategy_name=row["strategy_name"],
            basket_type=row["summary_role"],
            tickers=tickers,
        )

        equity["summary_role"] = row["summary_role"]
        equity_frames.append(equity)

    trades = (
        pd.concat(trade_frames, ignore_index=True)
        if trade_frames
        else pd.DataFrame()
    )

    equity_curve = (
        pd.concat(equity_frames, ignore_index=True)
        if equity_frames
        else pd.DataFrame()
    )

    regime_summary = build_basket_regime_summary(trades)

    return trades, equity_curve, regime_summary


def build_basket_regime_summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()

    regime_dimensions = [
        "market_gap_regime",
        "market_trend_regime",
        "market_breadth_regime",
        "market_volatility_regime",
        "composite_regime",
    ]

    rows = []

    for dimension in regime_dimensions:
        if dimension not in trades.columns:
            continue

        grouped = trades.groupby(
            [
                "basket_id",
                "strategy_name",
                "basket_type",
                "basket_tickers",
                dimension,
            ],
            dropna=False,
        )

        for keys, group in grouped:
            basket_id, strategy_name, basket_type, basket_tickers, regime_value = keys

            pnl_sek = group["net_return"] * ORB_POSITION_SIZE * ORB_INITIAL_CAPITAL

            rows.append(
                {
                    "basket_id": basket_id,
                    "strategy_name": strategy_name,
                    "basket_type": basket_type,
                    "basket_tickers": basket_tickers,
                    "regime_dimension": dimension,
                    "regime_value": regime_value,
                    "trades": int(len(group)),
                    "active_days": int(group["date"].nunique()),
                    "total_account_return": float(
                        (group["net_return"] * ORB_POSITION_SIZE).sum()
                    ),
                    "total_pnl_sek": float(pnl_sek.sum()),
                    "win_rate": float((group["net_return"] > 0).mean()),
                    "avg_trade": float(group["net_return"].mean()),
                    "profit_factor": calculate_profit_factor(pnl_sek),
                    "best_trade": float(group["net_return"].max()),
                    "worst_trade": float(group["net_return"].min()),
                }
            )

    regime_summary = pd.DataFrame(rows)

    if regime_summary.empty:
        return regime_summary

    regime_summary = regime_summary.sort_values(
        ["strategy_name", "basket_type", "regime_dimension", "total_account_return"],
        ascending=[True, True, True, False],
    ).reset_index(drop=True)

    return regime_summary


def print_top_results(
    optimization_summary: pd.DataFrame,
    ticker_performance: pd.DataFrame,
) -> None:
    print("\n=== STRATEGY-SPECIFIC BASKET SUMMARY ===")

    display_columns = [
        "strategy_name",
        "summary_role",
        "basket_ticker_count",
        "basket_tickers",
        "selected_trades",
        "active_days",
        "total_return",
        "profit_factor",
        "max_drawdown",
        "win_rate",
        "avg_trade",
        "research_candidate",
    ]

    print(optimization_summary[display_columns].to_string(index=False))

    print("\n=== TOP INDIVIDUAL TICKERS BY STRATEGY ===")

    top_tickers = ticker_performance[
        ticker_performance["ticker_rank_within_strategy"] <= 5
    ].copy()

    ticker_columns = [
        "strategy_name",
        "ticker_rank_within_strategy",
        "ticker",
        "selected_trades",
        "active_days",
        "total_return",
        "profit_factor",
        "max_drawdown",
        "win_rate",
        "avg_trade",
        "research_candidate",
    ]

    print(top_tickers[ticker_columns].to_string(index=False))


def main() -> None:
    print("\n=== STRATEGY LAB TICKER OPTIMIZATION ===")
    print("Research-only. This does not modify ORB paper/live trading.")
    print("Tests strategy-specific ticker universes.")
    print(f"Initial capital: {ORB_INITIAL_CAPITAL:.2f} SEK")
    print(f"Position size: {ORB_POSITION_SIZE:.2%}")
    print(f"Current ORB basket: {ticker_list_to_string(ORB_ALLOWED_TICKERS)}")

    raw_prices = load_normalised_intraday_prices()

    all_tickers = discover_downloaded_tickers(raw_prices)

    print(f"Downloaded ticker universe: {ticker_list_to_string(all_tickers)}")
    print(f"Downloaded ticker count: {len(all_tickers)}")

    market_regime = calculate_daily_market_regime(raw_prices)

    candidates = build_all_strategy_candidates(
        raw_prices=raw_prices,
        all_tickers=all_tickers,
        market_regime=market_regime,
    )

    if candidates.empty:
        print("No candidates created.")
        return

    print(f"\nTotal all-strategy candidates: {len(candidates)}")

    print("\nBuilding individual ticker performance...")
    ticker_performance = build_ticker_performance(
        candidates=candidates,
        all_tickers=all_tickers,
    )

    print("\nBuilding basket optimization...")
    basket_optimization = build_basket_optimization(
        candidates=candidates,
        all_tickers=all_tickers,
        ticker_performance=ticker_performance,
    )

    optimization_summary = build_optimization_summary(basket_optimization)

    print("\nBuilding key basket trade/equity/regime outputs...")
    basket_trades, basket_equity, basket_regime_summary = build_key_basket_outputs(
        candidates=candidates,
        optimization_summary=optimization_summary,
    )

    export_csv_for_power_bi(ticker_performance, OUTPUT_TICKER_PERFORMANCE_FILE)
    export_csv_for_power_bi(basket_optimization, OUTPUT_BASKET_OPTIMIZATION_FILE)
    export_csv_for_power_bi(optimization_summary, OUTPUT_OPTIMIZATION_SUMMARY_FILE)
    export_csv_for_power_bi(basket_trades, OUTPUT_BASKET_TRADES_FILE)
    export_csv_for_power_bi(basket_equity, OUTPUT_BASKET_EQUITY_FILE)
    export_csv_for_power_bi(basket_regime_summary, OUTPUT_BASKET_REGIME_SUMMARY_FILE)
    export_csv_for_power_bi(candidates, OUTPUT_ALL_CANDIDATES_FILE)

    print_top_results(
        optimization_summary=optimization_summary,
        ticker_performance=ticker_performance,
    )

    print(f"\nSaved ticker performance -> {OUTPUT_TICKER_PERFORMANCE_FILE}")
    print(f"Saved basket optimization -> {OUTPUT_BASKET_OPTIMIZATION_FILE}")
    print(f"Saved summary             -> {OUTPUT_OPTIMIZATION_SUMMARY_FILE}")
    print(f"Saved basket trades       -> {OUTPUT_BASKET_TRADES_FILE}")
    print(f"Saved basket equity       -> {OUTPUT_BASKET_EQUITY_FILE}")
    print(f"Saved regime summary      -> {OUTPUT_BASKET_REGIME_SUMMARY_FILE}")
    print(f"Saved candidates          -> {OUTPUT_ALL_CANDIDATES_FILE}")


if __name__ == "__main__":
    main()