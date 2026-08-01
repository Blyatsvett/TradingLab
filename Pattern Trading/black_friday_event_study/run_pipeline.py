from src.analyze import run_analysis
from src.build_event_panel import build_event_panel
from src.download_prices import download_all_prices


def main() -> None:
    print("\nSTEP 1 — Downloading adjusted daily prices")
    prices = download_all_prices()
    print(f"Downloaded {len(prices):,} price rows.")

    print("\nSTEP 2 — Building Black Friday event panels")
    panel, windows = build_event_panel()
    print(f"Built {len(panel):,} event-day rows and {len(windows):,} event windows.")

    print("\nSTEP 3 — Running statistical summaries")
    outputs = run_analysis()

    print("\nCompleted.")
    print("Open the CSV files in output/ or connect to event_study.db.")
    print("\nGroup summary preview:")
    print(outputs["group_summary"].head(15).to_string(index=False))


if __name__ == "__main__":
    main()
