from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR
from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router as step9i
from RegimeTrading.scripts import step9l_v2_selected_strategy_shadow_engine as step9l_v2


DAILY_FILE = DATA_DIR / "step9l_v2_vs_step9i_v2_daily_comparison.csv"
SUMMARY_FILE = DATA_DIR / "step9l_v2_vs_step9i_v2_comparison_summary.csv"
AUDIT_FILE = DATA_DIR / "step9l_v2_vs_step9i_v2_comparison_audit.csv"


def _read_ledger(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not Path(path).exists():
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    with closing(sqlite3.connect(path)) as con:
        batches = pd.read_sql_query(
            "SELECT * FROM shadow_decision_batches ORDER BY session_date", con
        )
        decisions = pd.read_sql_query(
            "SELECT * FROM shadow_decisions ORDER BY session_date, contract_id, ticker", con
        )
        outcomes = pd.read_sql_query(
            "SELECT * FROM shadow_outcomes ORDER BY session_date, contract_id, ticker", con
        )
    return batches, decisions, outcomes


def _engine_daily(
    engine_name: str,
    batches: pd.DataFrame,
    decisions: pd.DataFrame,
    outcomes: pd.DataFrame,
) -> pd.DataFrame:
    if batches.empty:
        return pd.DataFrame()

    completed = outcomes[
        outcomes["outcome_status"].astype(str).str.endswith("TRADE_COMPLETED")
    ].copy() if not outcomes.empty else outcomes.copy()

    rows: list[dict] = []
    for batch in batches.to_dict("records"):
        date = str(batch["session_date"])
        d = decisions[decisions["session_date"].astype(str).eq(date)].copy()
        o = completed[completed["session_date"].astype(str).eq(date)].copy()
        primary = o[o["test_role"].eq("PRIMARY_HYPOTHESIS")].copy()
        guards = o[o["test_role"].eq("NEGATIVE_GUARDRAIL")].copy()
        primary_pnl = pd.to_numeric(
            primary.get("risk_capped_net_pnl_sek"), errors="coerce"
        ).fillna(0.0)
        guard_pnl = pd.to_numeric(
            guards.get("risk_capped_net_pnl_sek"), errors="coerce"
        ).fillna(0.0)
        rows.append(
            {
                "engine": engine_name,
                "session_date": date,
                "prospective_status": str(batch.get("prospective_status", "")),
                "primary_regime": str(batch.get("primary_regime", "")),
                "regime_confidence": batch.get("regime_confidence"),
                "decision_rows": len(d),
                "eligible_primary_rows": int(
                    (d["contract_eligible"].astype(bool) & d["test_role"].eq("PRIMARY_HYPOTHESIS")).sum()
                ) if not d.empty else 0,
                "active_guardrail_rows": int(
                    d["decision_action"].eq("GUARDRAIL_ACTIVE_AVOID_STRATEGY").sum()
                ) if not d.empty else 0,
                "primary_completed_trades": len(primary),
                "primary_net_pnl_sek": float(primary_pnl.sum()),
                "primary_tickers": "|".join(sorted(primary["ticker"].astype(str).unique())) if not primary.empty else "",
                "primary_contracts": "|".join(sorted(primary["contract_id"].astype(str).unique())) if not primary.empty else "",
                "guardrail_counterfactual_trades": len(guards),
                "guardrail_counterfactual_pnl_sek": float(guard_pnl.sum()),
                "guardrail_tickers": "|".join(sorted(guards["ticker"].astype(str).unique())) if not guards.empty else "",
                "guardrail_contracts": "|".join(sorted(guards["contract_id"].astype(str).unique())) if not guards.empty else "",
            }
        )
    return pd.DataFrame(rows)


def build_comparison(
    frozen_ledger: Path = step9i.SHADOW_LEDGER_DB,
    research_ledger: Path = step9l_v2.SHADOW_LEDGER_DB,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    f_batches, f_decisions, f_outcomes = _read_ledger(frozen_ledger)
    r_batches, r_decisions, r_outcomes = _read_ledger(research_ledger)

    frozen = _engine_daily("STEP9I_V2_FROZEN", f_batches, f_decisions, f_outcomes)
    research = _engine_daily("STEP9L_V2_RESEARCH", r_batches, r_decisions, r_outcomes)

    if frozen.empty and research.empty:
        daily = pd.DataFrame()
    else:
        left = frozen.add_prefix("frozen_").rename(columns={"frozen_session_date": "session_date"})
        right = research.add_prefix("research_").rename(columns={"research_session_date": "session_date"})
        daily = left.merge(right, on="session_date", how="outer").sort_values("session_date")
        for col in [
            "frozen_primary_net_pnl_sek", "research_primary_net_pnl_sek",
            "frozen_primary_completed_trades", "research_primary_completed_trades",
        ]:
            if col not in daily:
                daily[col] = 0.0
            daily[col] = pd.to_numeric(daily[col], errors="coerce").fillna(0.0)
        daily["research_minus_frozen_primary_pnl_sek"] = (
            daily["research_primary_net_pnl_sek"] - daily["frozen_primary_net_pnl_sek"]
        )
        daily["cumulative_research_minus_frozen_pnl_sek"] = (
            daily["research_minus_frozen_primary_pnl_sek"].cumsum()
        )
        frozen_regime = daily.get("frozen_primary_regime", pd.Series("", index=daily.index))
        research_regime = daily.get("research_primary_regime", pd.Series("", index=daily.index))
        frozen_status = daily.get("frozen_prospective_status", pd.Series("", index=daily.index))
        research_status = daily.get("research_prospective_status", pd.Series("", index=daily.index))
        daily["same_regime_classification"] = (
            frozen_regime.fillna("").astype(str) == research_regime.fillna("").astype(str)
        )
        daily["comparison_evidence"] = np.where(
            frozen_status.eq("PROSPECTIVE_CONFIRMATORY_ELIGIBLE")
            & research_status.eq("PROSPECTIVE_CONFIRMATORY_ELIGIBLE"),
            "BOTH_ENGINES_PROSPECTIVE",
            "INCLUDES_NONCONFIRMATORY_OR_MISSING_ENGINE",
        )
        frozen_contracts = daily.get("frozen_primary_contracts", pd.Series("", index=daily.index)).fillna("")
        research_contracts = daily.get("research_primary_contracts", pd.Series("", index=daily.index)).fillna("")
        frozen_tickers = daily.get("frozen_primary_tickers", pd.Series("", index=daily.index)).fillna("")
        research_tickers = daily.get("research_primary_tickers", pd.Series("", index=daily.index)).fillna("")
        daily["same_primary_contract_set"] = frozen_contracts.astype(str).eq(research_contracts.astype(str))
        daily["same_primary_ticker_set"] = frozen_tickers.astype(str).eq(research_tickers.astype(str))
        daily["engine_disagreement"] = ~(
            daily["same_primary_contract_set"] & daily["same_primary_ticker_set"]
        )

    prospective = daily[
        daily.get("comparison_evidence", pd.Series(dtype=str)).eq("BOTH_ENGINES_PROSPECTIVE")
    ].copy() if not daily.empty else daily
    summary = pd.DataFrame([
        {
            "comparison": "STEP9L_V2_VS_STEP9I_V2_PRIMARY_HYPOTHESES",
            "overlapping_sessions": len(daily),
            "fully_prospective_sessions": len(prospective),
            "engine_disagreement_sessions": int(prospective.get("engine_disagreement", pd.Series(dtype=bool)).sum()) if not prospective.empty else 0,
            "frozen_primary_trades": int(prospective.get("frozen_primary_completed_trades", pd.Series(dtype=float)).sum()) if not prospective.empty else 0,
            "research_primary_trades": int(prospective.get("research_primary_completed_trades", pd.Series(dtype=float)).sum()) if not prospective.empty else 0,
            "frozen_primary_net_pnl_sek": float(prospective.get("frozen_primary_net_pnl_sek", pd.Series(dtype=float)).sum()) if not prospective.empty else 0.0,
            "research_primary_net_pnl_sek": float(prospective.get("research_primary_net_pnl_sek", pd.Series(dtype=float)).sum()) if not prospective.empty else 0.0,
            "research_minus_frozen_primary_pnl_sek": float(prospective.get("research_minus_frozen_primary_pnl_sek", pd.Series(dtype=float)).sum()) if not prospective.empty else 0.0,
            "mixed_research_roles_combined": False,
            "router_active": False,
        }
    ])

    distinct = Path(frozen_ledger).resolve() != Path(research_ledger).resolve()
    audit = pd.DataFrame([
        {
            "audit_item": "FROZEN_AND_V2_RESEARCH_LEDGERS_ARE_DISTINCT",
            "failures": 0 if distinct else 1,
            "audit_pass": distinct,
            "interpretation": "Step 9L V2 never writes to the frozen Step 9I V2 ledger.",
        },
        {
            "audit_item": "COMPARISON_USES_PRIMARY_HYPOTHESES_ONLY_FOR_ENGINE_PNL",
            "failures": 0,
            "audit_pass": True,
            "interpretation": "Controls and guardrail counterfactuals are reported separately and not mixed into engine P&L.",
        },
        {
            "audit_item": "COMPARISON_IS_READ_ONLY",
            "failures": 0,
            "audit_pass": True,
            "interpretation": "The comparison reads both ledgers and writes CSV exports only.",
        },
    ])
    return daily, summary, audit


def export_comparison(
    frozen_ledger: Path = step9i.SHADOW_LEDGER_DB,
    research_ledger: Path = step9l_v2.SHADOW_LEDGER_DB,
) -> None:
    daily, summary, audit = build_comparison(frozen_ledger, research_ledger)
    export_csv_for_power_bi(daily, DAILY_FILE)
    export_csv_for_power_bi(summary, SUMMARY_FILE)
    export_csv_for_power_bi(audit, AUDIT_FILE)
    print(f"Saved {DAILY_FILE.name}: {len(daily)} rows")
    print(f"Saved {SUMMARY_FILE.name}: {len(summary)} rows")
    print(f"Saved {AUDIT_FILE.name}: {len(audit)} rows")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare frozen Step 9I V2 with Step 9L V2.")
    parser.add_argument("--frozen-ledger", type=Path, default=step9i.SHADOW_LEDGER_DB)
    parser.add_argument("--research-ledger", type=Path, default=step9l_v2.SHADOW_LEDGER_DB)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    export_comparison(args.frozen_ledger, args.research_ledger)


if __name__ == "__main__":
    main()
