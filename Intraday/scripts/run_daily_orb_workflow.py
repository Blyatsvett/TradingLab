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
    ("Export risk filter shadow report", "Intraday.scripts.research_orb_risk_filter_shadow_report"),
    ("Export position sizing shadow report", "Intraday.scripts.research_orb_position_sizing_shadow_report"),
    ("Export Power BI workbook", "Intraday.scripts.export_powerbi_workbook"),
    ("Validate daily outputs", "Intraday.scripts.validate_daily_outputs"),
]


def run_step(title, module_name, log_file):
    separator = "\n" + "=" * 60 + "\n"
    header = f"{separator}{title.upper()}\n{'=' * 60}\n"

    print(header)
    log_file.write(header)
    log_file.flush()

    result = subprocess.run(
        [sys.executable, "-m", module_name],
        capture_output=True,
        text=True,
    )

    if result.stdout:
        print(result.stdout)
        log_file.write(result.stdout)

    if result.stderr:
        print(result.stderr)
        log_file.write("\n--- STDERR ---\n")
        log_file.write(result.stderr)

    log_file.flush()

    if result.returncode != 0:
        error_message = f"\n❌ Step failed: {title}\nReturn code: {result.returncode}\n"
        print(error_message)
        log_file.write(error_message)
        log_file.flush()
        raise SystemExit(result.returncode)


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