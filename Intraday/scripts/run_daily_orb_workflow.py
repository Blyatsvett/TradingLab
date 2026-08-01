import subprocess
import sys
from datetime import datetime
from pathlib import Path

from Intraday.core.paths import DATA_DIR


LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)


COMMANDS = [
    ("Download intraday prices", "Intraday.scripts.download_intraday_prices"),
    ("Run ORB scanner", "Intraday.scripts.orb_daily_scanner"),

    ("Update existing paper trades", "Intraday.scripts.update_paper_trades"),
    ("Auto-create triggered paper trades", "Intraday.scripts.auto_create_triggered_paper_trades"),
    ("Update paper trades after new entries", "Intraday.scripts.update_paper_trades"),
    ("Add paper trade config metadata", "Intraday.scripts.add_paper_trade_config_metadata"),

    ("Show paper trade summary", "Intraday.scripts.paper_trade_summary"),
    ("Export paper account equity curve", "Intraday.scripts.export_paper_account_equity_curve"),
    ("Export strategy config snapshot", "Intraday.scripts.export_strategy_config_snapshot"),
    ("Export workflow run audit", "Intraday.scripts.export_workflow_run_audit"),
    ("Export intraday market regime", "Intraday.scripts.export_intraday_market_regime"),
    ("Run intraday strategy lab", "Intraday.scripts.research_intraday_strategy_lab"),
    ("Export Strategy Lab daily shadow report", "Intraday.scripts.research_strategy_lab_daily_shadow_report"),
    ("Run regime-aware gap recovery research", "Intraday.scripts.research_regime_aware_gap_recovery"),
    ("Export risk filter shadow report", "Intraday.scripts.research_orb_risk_filter_shadow_report"),
    ("Export position sizing shadow report", "Intraday.scripts.research_orb_position_sizing_shadow_report"),
    ("Compare Strategy Lab ORB baseline", "Intraday.scripts.compare_strategy_lab_orb_baseline"),
    ("Export daily research review", "Intraday.scripts.export_daily_research_review"),
    ("Export Power BI workbook", "Intraday.scripts.export_powerbi_workbook"),
    ("Validate daily outputs", "Intraday.scripts.validate_daily_outputs"),
]


def run_step(title: str, module_name: str, log_file) -> None:
    print(f"\n=== {title.upper()} ===")
    log_file.write(f"\n=== {title.upper()} ===\n")
    log_file.flush()

    result = subprocess.Popen(
        [sys.executable, "-m", module_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    output_lines = []

    if result.stdout is not None:
        for line in result.stdout:
            print(line, end="")
            log_file.write(line)
            log_file.flush()
            output_lines.append(line)

    return_code = result.wait()

    if return_code != 0:
        raise RuntimeError(
            f"Step failed: {title} ({module_name}) "
            f"with return code {return_code}"
        )

    print(f"\nOK: {title}")
    log_file.write(f"\nOK: {title}\n")
    log_file.flush()


def main():
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_path = LOG_DIR / f"orb_workflow_{timestamp}.txt"

    with open(log_path, "w", encoding="utf-8") as log_file:
        start_message = (
            "\n🚀 RUNNING DAILY ORB WORKFLOW\n"
            f"Started at: {datetime.now()}\n"
            f"Log file  : {log_path}\n"
        )

        print(start_message)
        log_file.write(start_message)
        log_file.flush()

        for title, module_name in COMMANDS:
            run_step(title, module_name, log_file)

        end_message = (
            "\n✅ Daily ORB workflow complete\n"
            f"Finished at: {datetime.now()}\n"
            f"Log saved : {log_path}\n"
        )

        print(end_message)
        log_file.write(end_message)

    print(f"\nLog saved -> {log_path}")


if __name__ == "__main__":
    main()