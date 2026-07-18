"""
Research-only ticker universes.

IMPORTANT:
These tickers are for Strategy Lab / market-regime / ticker-optimization research only.

They must NOT be used to change the production ORB strategy.
The production ORB basket remains controlled by Intraday/core/orb_config.py.
"""

from Intraday.core.orb_config import ORB_ALLOWED_TICKERS


# Frozen production reference only.
# Do not use this to mutate ORB_ALLOWED_TICKERS.
PRODUCTION_ORB_TICKERS = list(ORB_ALLOWED_TICKERS)


# Broader Swedish large/liquid research universe.
# Used for Strategy Lab, ticker optimization, and market-regime research.
RESEARCH_TICKERS_SWEDEN_LARGE_CAP = sorted(
    set(
        [
            # Current ORB / initial research names
            "ABB.ST",
            "ALFA.ST",
            "ASSA-B.ST",
            "ATCO-A.ST",
            "ERIC-B.ST",
            "EVO.ST",
            "INVE-B.ST",
            "SEB-A.ST",
            "SHB-A.ST",
            "VOLV-B.ST",

            # Additional Swedish large/liquid names for research
            "ATCO-B.ST",
            "AZN.ST",
            "BOL.ST",
            "ELUX-B.ST",
            "ESSITY-B.ST",
            "EQT.ST",
            "GETI-B.ST",
            "HEXA-B.ST",
            "HM-B.ST",
            "KINV-B.ST",
            "LATO-B.ST",
            "LIFCO-B.ST",
            "NDA-SE.ST",
            "NIBE-B.ST",
            "SAND.ST",
            "SAAB-B.ST",
            "SCA-B.ST",
            "SINCH.ST",
            "SKF-B.ST",
            "SWED-A.ST",
            "TEL2-B.ST",
            "TELIA.ST",
        ]
    )
)


def get_research_tickers() -> list[str]:
    return list(RESEARCH_TICKERS_SWEDEN_LARGE_CAP)


def get_production_orb_tickers() -> list[str]:
    return list(PRODUCTION_ORB_TICKERS)