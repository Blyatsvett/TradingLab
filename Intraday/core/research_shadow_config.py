from __future__ import annotations

from copy import deepcopy

from Intraday.core.orb_config import ORB_ALLOWED_TICKERS


"""
Research shadow strategy definitions.

IMPORTANT:
These are research-only / shadow-only strategy definitions.

They do NOT modify:
- production ORB ticker basket
- paper_trades.csv
- live/paper ORB scanner
- ORB production config

Production ORB remains controlled by Intraday/core/orb_config.py.
"""


# Strategy names must match Strategy Lab output names.
ORB_BREAKOUT_NAME = "01_ORB_BREAKOUT_BASELINE"
ORB_PULLBACK_NAME = "02_ORB_PULLBACK_RETEST"
VWAP_RECLAIM_NAME = "03_VWAP_RECLAIM"
GAP_DOWN_RECOVERY_NAME = "04_GAP_DOWN_RECOVERY"
PREVIOUS_DAY_HIGH_BREAKOUT_NAME = "05_PREVIOUS_DAY_HIGH_BREAKOUT"


TIER_PRODUCTION_REFERENCE = "PRODUCTION_REFERENCE"
TIER_ACTIVE_SHADOW = "ACTIVE_SHADOW"
TIER_WATCHLIST = "WATCHLIST"
TIER_DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"


RESEARCH_SHADOW_DEFINITIONS = [
    {
        "shadow_strategy_id": "ORB_PRODUCTION_REFERENCE_CURRENT_BASKET",
        "strategy_name": ORB_BREAKOUT_NAME,
        "summary_role": "current_orb_basket",
        "research_tier": TIER_PRODUCTION_REFERENCE,
        "basket_tickers": list(ORB_ALLOWED_TICKERS),
        "use_downloaded_universe": False,
        "status_note": (
            "Frozen ORB production basket. Reference only. "
            "Production/paper logic remains separate."
        ),
    },
    {
        "shadow_strategy_id": "PDH_ACTIVE_BEST5",
        "strategy_name": PREVIOUS_DAY_HIGH_BREAKOUT_NAME,
        "summary_role": "best_combo_5",
        "research_tier": TIER_ACTIVE_SHADOW,
        "basket_tickers": [
            "ATCO-A.ST",
            "BOL.ST",
            "GETI-B.ST",
            "HEXA-B.ST",
            "SINCH.ST",
        ],
        "use_downloaded_universe": False,
        "status_note": (
            "Main new active shadow candidate from ticker optimization "
            "and walk-forward validation."
        ),
    },
    {
        "shadow_strategy_id": "PDH_DIAGNOSTIC_ALL_DOWNLOADED",
        "strategy_name": PREVIOUS_DAY_HIGH_BREAKOUT_NAME,
        "summary_role": "all_downloaded",
        "research_tier": TIER_DIAGNOSTIC_ONLY,
        "basket_tickers": [],
        "use_downloaded_universe": True,
        "status_note": (
            "Diagnostic broad-universe Previous-day High Breakout. "
            "Useful for regime learning, not a trading candidate."
        ),
    },
    {
        "shadow_strategy_id": "GAP_RECOVERY_WATCH_BEST7",
        "strategy_name": GAP_DOWN_RECOVERY_NAME,
        "summary_role": "best_combo_7",
        "research_tier": TIER_WATCHLIST,
        "basket_tickers": [
            "ATCO-A.ST",
            "ATCO-B.ST",
            "AZN.ST",
            "BOL.ST",
            "EVO.ST",
            "SAND.ST",
            "SWED-A.ST",
        ],
        "use_downloaded_universe": False,
        "status_note": (
            "Gap-down Recovery watchlist strategy. Interesting but needs "
            "more forward trades."
        ),
    },
    {
        "shadow_strategy_id": "PULLBACK_DIAGNOSTIC_ALL_DOWNLOADED",
        "strategy_name": ORB_PULLBACK_NAME,
        "summary_role": "all_downloaded",
        "research_tier": TIER_DIAGNOSTIC_ONLY,
        "basket_tickers": [],
        "use_downloaded_universe": True,
        "status_note": (
            "Diagnostic Pullback strategy. Weak overall, but useful for "
            "regime learning."
        ),
    },
    {
        "shadow_strategy_id": "VWAP_DIAGNOSTIC_BEST5",
        "strategy_name": VWAP_RECLAIM_NAME,
        "summary_role": "best_combo_5",
        "research_tier": TIER_DIAGNOSTIC_ONLY,
        "basket_tickers": [
            "HM-B.ST",
            "NDA-SE.ST",
            "NIBE-B.ST",
            "SAND.ST",
            "SHB-A.ST",
        ],
        "use_downloaded_universe": False,
        "status_note": (
            "Diagnostic VWAP strategy. Low-priority research only."
        ),
    },
]


def get_research_shadow_definitions() -> list[dict]:
    return deepcopy(RESEARCH_SHADOW_DEFINITIONS)