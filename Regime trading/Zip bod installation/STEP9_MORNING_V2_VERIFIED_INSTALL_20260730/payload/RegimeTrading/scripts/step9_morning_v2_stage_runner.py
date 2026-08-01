from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def _write_json(payload: dict[str, Any], path: Path | None) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _step9i(args: argparse.Namespace) -> dict[str, Any]:
    from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router as mod

    now = mod._parse_stockholm_datetime(args.as_of)
    target = mod._target_date(args.date, now)
    prices = mod.load_shadow_prices(args.source_db)
    if prices.empty:
        raise mod.ShadowDataNotReady(f"No source prices found at {args.source_db}")
    batches, decisions, inserted = mod.seal_morning_decisions(
        target_date=target,
        now=now,
        prices=prices,
        ledger_db=args.ledger_db,
        source_db=args.source_db,
        allow_late=args.allow_late_reconstruction,
        export_outputs_after=False,
        simulated_clock=bool(args.as_of),
    )
    batch = batches.iloc[0]
    return {
        "stage": "step9i",
        "session_date": target,
        "inserted": bool(inserted),
        "prospective_status": str(batch["prospective_status"]),
        "primary_regime": str(batch["primary_regime"]),
        "decision_rows": int(len(decisions)),
        "eligible_rows": int(decisions["contract_eligible"].astype(bool).sum()),
        "active_guardrails": int(decisions["decision_action"].eq("GUARDRAIL_ACTIVE_AVOID_STRATEGY").sum()),
        "router_active": False,
        "orders_enabled": False,
    }


def _step9l(args: argparse.Namespace) -> dict[str, Any]:
    from RegimeTrading.scripts import step9l_v3_selected_strategy_shadow_engine as mod

    now = mod._parse_stockholm_datetime(args.as_of)
    target = mod._target_date(args.date, now)
    prices = mod.load_shadow_prices(args.source_db)
    if prices.empty:
        raise mod.step9i.ShadowDataNotReady(f"No source prices found at {args.source_db}")
    batches, decisions, inserted = mod.seal_morning_decisions(
        target_date=target,
        now=now,
        prices=prices,
        ledger_db=args.ledger_db,
        source_db=args.source_db,
        allow_late=args.allow_late_reconstruction,
        export_outputs_after=False,
        simulated_clock=bool(args.as_of),
    )
    batch = batches.iloc[0]
    return {
        "stage": "step9l",
        "session_date": target,
        "inserted": bool(inserted),
        "prospective_status": str(batch["prospective_status"]),
        "primary_regime": str(batch["primary_regime"]),
        "decision_rows": int(len(decisions)),
        "eligible_rows": int(decisions["contract_eligible"].astype(bool).sum()),
        "active_guardrails": int(decisions["decision_action"].eq("GUARDRAIL_ACTIVE_AVOID_STRATEGY").sum()),
        "router_active": False,
        "orders_enabled": False,
    }


def _step9s(args: argparse.Namespace) -> dict[str, Any]:
    from RegimeTrading.scripts import step9s_prospective_contingency_shadow_v1 as mod

    now = mod._parse_stockholm_datetime(args.as_of)
    target = mod._target_date(args.date, now)
    batches, plans, inserted = mod.seal_morning_assignment(
        session_date=target,
        now=now,
        source_db=args.source_db,
        step9l_ledger_db=args.step9l_ledger_db,
        ledger_db=args.ledger_db,
        allow_late=args.allow_late_reconstruction,
        simulated_clock=bool(args.as_of),
        export_outputs_after=False,
    )
    batch = batches.iloc[0]
    plan = plans.iloc[0]
    return {
        "stage": "step9s",
        "session_date": target,
        "inserted": bool(inserted),
        "prospective_status": str(batch["prospective_status"]),
        "primary_regime": str(batch["primary_regime"]),
        "natural_strategy_id": str(batch["natural_strategy_id"]),
        "coverage_control_id": str(batch["coverage_control_id"]),
        "mandatory_plan_ticker": str(plan.get("ticker", "")),
        "router_active": False,
        "orders_enabled": False,
    }


def _step9r(args: argparse.Namespace) -> dict[str, Any]:
    from RegimeTrading.scripts import step9r_v1_candidate_ranking_research as mod

    target = str(args.date)
    outputs = mod.run_prospective_morning(
        session_date=target,
        price_db=args.source_db,
        v3_ledger=args.step9l_ledger_db,
        research_db=args.research_db,
        prospective_db=args.ledger_db,
    )
    candidates = outputs["candidates"]
    selections = outputs["selections"]
    return {
        "stage": "step9r",
        "session_date": target,
        "candidate_rows": int(len(candidates)),
        "selected_rows": int(len(selections)),
        "selected_tickers": selections["ticker"].astype(str).tolist() if not selections.empty else [],
        "router_active": False,
        "orders_enabled": False,
    }


def _step9t(args: argparse.Namespace) -> dict[str, Any]:
    from RegimeTrading.scripts import step9t_prospective_regime_transition_archetype_v1 as mod

    now = mod._parse_stockholm_datetime(args.as_of)
    target = mod._target_date(args.date, now)
    batches, archetypes, inserted = mod.seal_morning_snapshot(
        session_date=target,
        now=now,
        source_db=args.source_db,
        step9l_ledger_db=args.step9l_ledger_db,
        ledger_db=args.ledger_db,
        allow_late=args.allow_late_reconstruction,
        simulated_clock=bool(args.as_of),
        export_outputs_after=False,
    )
    batch = batches.iloc[0]
    return {
        "stage": "step9t",
        "session_date": target,
        "inserted": bool(inserted),
        "prospective_status": str(batch["prospective_status"]),
        "source_regime": str(batch["source_regime"]),
        "transition_state": str(batch["transition_state"]),
        "ticker_rows": int(len(archetypes)),
        "complete_tickers": int(archetypes["morning_status"].eq("MORNING_COMPLETE").sum()),
        "router_active": False,
        "orders_enabled": False,
    }


def _step9u(args: argparse.Namespace) -> dict[str, Any]:
    from RegimeTrading.scripts import step9u_prospective_contingency_selector_v1 as mod

    now = mod._parse_stockholm_datetime(args.as_of)
    target = mod._target_date(args.date, now)
    batches, candidates, inserted = mod.seal_morning_selection(
        session_date=target,
        now=now,
        step9t_ledger_db=args.step9t_ledger_db,
        ledger_db=args.ledger_db,
        allow_late=args.allow_late_reconstruction,
        simulated_clock=bool(args.as_of),
        export_outputs_after=False,
    )
    batch = batches.iloc[0]
    selected = candidates[candidates["selected"].astype(int).eq(1)].sort_values("selected_rank")
    return {
        "stage": "step9u",
        "session_date": target,
        "inserted": bool(inserted),
        "prospective_status": str(batch["prospective_status"]),
        "source_regime": str(batch["source_regime"]),
        "transition_state": str(batch["transition_state"]),
        "candidate_rows": int(len(candidates)),
        "selected_rows": int(len(selected)),
        "selected_tickers": selected["ticker"].astype(str).tolist() if not selected.empty else [],
        "mandatory_control_active": False,
        "router_active": False,
        "orders_enabled": False,
    }


def _export(args: argparse.Namespace) -> dict[str, Any]:
    from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router as step9i
    from RegimeTrading.scripts import step9l_v3_selected_strategy_shadow_engine as step9l
    from RegimeTrading.scripts import step9s_prospective_contingency_shadow_v1 as step9s
    from RegimeTrading.scripts import step9t_prospective_regime_transition_archetype_v1 as step9t
    from RegimeTrading.scripts import step9u_prospective_contingency_selector_v1 as step9u

    step9i.export_shadow_outputs(args.step9i_ledger_db)
    step9l.export_shadow_outputs(args.step9l_ledger_db)
    step9s.export_outputs(args.step9s_ledger_db)
    step9t.export_outputs(args.step9t_ledger_db)
    step9u.export_outputs(args.step9u_ledger_db)
    return {
        "stage": "exports",
        "session_date": str(args.date),
        "status": "PASSED",
        "router_active": False,
        "orders_enabled": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fast, no-export Step 9 Morning V2 stage runner.")
    sub = parser.add_subparsers(dest="stage", required=True)

    def common(child: argparse.ArgumentParser) -> None:
        child.add_argument("--date", required=True)
        child.add_argument("--as-of", default="")
        child.add_argument("--allow-late-reconstruction", action="store_true")
        child.add_argument("--json-out", type=Path)

    for name in ["step9i", "step9l"]:
        child = sub.add_parser(name)
        common(child)
        child.add_argument("--source-db", type=Path, required=True)
        child.add_argument("--ledger-db", type=Path, required=True)

    child = sub.add_parser("step9s")
    common(child)
    child.add_argument("--source-db", type=Path, required=True)
    child.add_argument("--step9l-ledger-db", type=Path, required=True)
    child.add_argument("--ledger-db", type=Path, required=True)

    child = sub.add_parser("step9r")
    common(child)
    child.add_argument("--source-db", type=Path, required=True)
    child.add_argument("--step9l-ledger-db", type=Path, required=True)
    child.add_argument("--research-db", type=Path, required=True)
    child.add_argument("--ledger-db", type=Path, required=True)

    child = sub.add_parser("step9t")
    common(child)
    child.add_argument("--source-db", type=Path, required=True)
    child.add_argument("--step9l-ledger-db", type=Path, required=True)
    child.add_argument("--ledger-db", type=Path, required=True)

    child = sub.add_parser("step9u")
    common(child)
    child.add_argument("--step9t-ledger-db", type=Path, required=True)
    child.add_argument("--ledger-db", type=Path, required=True)

    child = sub.add_parser("export-all")
    child.add_argument("--date", required=True)
    child.add_argument("--json-out", type=Path)
    child.add_argument("--step9i-ledger-db", type=Path, required=True)
    child.add_argument("--step9l-ledger-db", type=Path, required=True)
    child.add_argument("--step9s-ledger-db", type=Path, required=True)
    child.add_argument("--step9t-ledger-db", type=Path, required=True)
    child.add_argument("--step9u-ledger-db", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    handlers = {
        "step9i": _step9i,
        "step9l": _step9l,
        "step9s": _step9s,
        "step9r": _step9r,
        "step9t": _step9t,
        "step9u": _step9u,
        "export-all": _export,
    }
    payload = handlers[args.stage](args)
    _write_json(payload, args.json_out)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
