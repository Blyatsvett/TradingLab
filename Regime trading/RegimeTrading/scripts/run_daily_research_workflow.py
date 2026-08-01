from __future__ import annotations

import subprocess
import sys
from datetime import datetime

from RegimeTrading.core.paths import LOG_DIR


COMMANDS = [
    ("Sync isolated intraday database", "RegimeTrading.scripts.sync_intraday_database"),
    (
        "Run regime-aware gap recovery research",
        "RegimeTrading.scripts.research_regime_aware_gap_recovery",
    ),
    (
        "Run V1 validation suite step 1 portfolio simulation",
        "RegimeTrading.scripts.v1_validation_portfolio",
    ),
    (
        "Run V1 validation suite step 2 concentration and leave-one-out",
        "RegimeTrading.scripts.v1_validation_concentration",
    ),
    (
        "Run V1 validation suite step 3 execution and cost stress testing",
        "RegimeTrading.scripts.v1_validation_execution_stress",
    ),
    (
        "Run V1 validation suite step 4 parameter robustness grid",
        "RegimeTrading.scripts.v1_validation_parameter_robustness",
    ),
    (
        "Run V1 validation suite step 5 provider quality and completeness gates",
        "RegimeTrading.scripts.v1_validation_provider_quality",
    ),
    (
        "Run V1 validation suite step 6 exposure and capital efficiency",
        "RegimeTrading.scripts.v1_validation_exposure_efficiency",
    ),
    (
        "Run V1 validation suite step 6 reconciliation gate",
        "RegimeTrading.scripts.v1_validation_exposure_reconciliation",
    ),
    (
        "Run Step 7 point-in-time regime feature foundation",
        "RegimeTrading.scripts.step7_regime_feature_foundation",
    ),
    (
        "Run Step 7B strict versus legacy V1 regime timing comparison",
        "RegimeTrading.scripts.step7b_v1_regime_timing_comparison",
    ),
    (
        "Run Step 8 provisional exhaustive regime taxonomy",
        "RegimeTrading.scripts.step8_provisional_regime_taxonomy",
    ),
    (
        "Run Step 9A executable playbook specifications",
        "RegimeTrading.scripts.step9_playbook_specifications",
    ),
    (
        "Run Step 9B baseline playbook trade generation",
        "RegimeTrading.scripts.step9b_baseline_trade_generation",
    ),
    (
        "Run Step 9C playbook loss-driver diagnostics",
        "RegimeTrading.scripts.step9c_playbook_loss_diagnostics",
    ),
    (
        "Run Step 9D regime by strategy challenger matrix",
        "RegimeTrading.scripts.step9d_regime_strategy_challenger_matrix",
    ),
    (
        "Run Step 9E instrument, sector and ticker-characteristic taxonomy",
        "RegimeTrading.scripts.step9e_instrument_sector_taxonomy",
    ),
    (
        "Run Step 9F regime by strategy by sector and ticker experiments",
        "RegimeTrading.scripts.step9f_sector_ticker_strategy_experiments",
    ),
    (
        "Run Step 9G pre-registered state-filtered contract experiments",
        "RegimeTrading.scripts.step9g_state_filtered_contract_experiments",
    ),
    (
        "Run Step 9H locked cross-sectional holdout transport",
        "RegimeTrading.scripts.step9h_cross_sectional_holdout_transport",
    ),
    ("Export Power BI workbook", "RegimeTrading.scripts.export_powerbi_workbook"),
    ("Validate research outputs", "RegimeTrading.scripts.validate_outputs"),
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
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    if result.stdout is not None:
        for line in result.stdout:
            print(line, end="")
            log_file.write(line)
            log_file.flush()

    return_code = result.wait()
    if return_code != 0:
        raise RuntimeError(
            f"Step failed: {title} ({module_name}) with return code {return_code}"
        )

    print(f"\nOK: {title}")
    log_file.write(f"\nOK: {title}\n")
    log_file.flush()


def main() -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_path = LOG_DIR / f"regime_research_workflow_{timestamp}.txt"

    with open(log_path, "w", encoding="utf-8") as log_file:
        start_message = (
            "\nRUNNING ISOLATED REGIME TRADING RESEARCH WORKFLOW\n"
            f"Started at: {datetime.now()}\n"
            f"Log file  : {log_path}\n"
        )
        print(start_message)
        log_file.write(start_message)

        for title, module_name in COMMANDS:
            run_step(title, module_name, log_file)

        end_message = (
            "\nRegime trading research workflow complete\n"
            f"Finished at: {datetime.now()}\n"
            f"Log saved : {log_path}\n"
        )
        print(end_message)
        log_file.write(end_message)

    print(f"\nLog saved -> {log_path}")


if __name__ == "__main__":
    main()
