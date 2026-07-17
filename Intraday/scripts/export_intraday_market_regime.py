from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.market_regime import calculate_daily_market_regime
from Intraday.core.orb_research import load_normalised_intraday_prices
from Intraday.core.paths import DATA_DIR


OUTPUT_FILE = DATA_DIR / "intraday_market_regime.csv"


def main() -> None:
    print("\n=== EXPORT INTRADAY MARKET REGIME ===")
    print("Diagnostic only. This does not change strategy decisions.")

    prices = load_normalised_intraday_prices()

    regime = calculate_daily_market_regime(prices)

    if regime.empty:
        print("No market regime rows created.")
        return

    export_csv_for_power_bi(regime, OUTPUT_FILE)

    print(f"Rows exported: {len(regime)}")
    print(f"First date: {regime['date'].min()}")
    print(f"Last date : {regime['date'].max()}")

    print("\n=== LATEST REGIME ROWS ===")
    display_columns = [
        "date",
        "n_tickers",
        "avg_gap_pct",
        "avg_return_from_previous_close",
        "avg_full_day_range_pct",
        "breadth_positive_from_previous_close",
        "market_gap_regime",
        "market_trend_regime",
        "market_breadth_regime",
        "market_volatility_regime",
        "composite_regime",
    ]

    print(regime[display_columns].tail(10).to_string(index=False))

    print(f"\nSaved -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()