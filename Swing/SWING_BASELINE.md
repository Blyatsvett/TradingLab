# Swing consolidation baseline

## Frozen legacy result

The historical research branch ranked the 52-stock universe by five-session
momentum, excluded stock-level bear regimes, selected the top two stocks and
reranked every three sessions. It applied close-to-next-open returns while using
the same closing price in the signal. Its reported result is preserved as a
research upper bound and is not treated as executable performance.

## Canonical v1 contract

- Source table: raw adjusted daily OHLCV from `prices`.
- Signal timestamp: after session T closes.
- Execution timestamp: open of the next exchange session T+1.
- Signal: cross-sectional z-score of five-session momentum.
- Eligibility: valid momentum and, by default, no stock-level bear regime.
- Portfolio: top two eligible stocks, equal target weights.
- Rebalance cadence: every three exchange sessions.
- Holding behavior: positions remain continuously invested between rebalance
  opens and earn open-to-next-open returns.
- Costs: basis points per traded side applied to actual risky-weight changes.
- Calendar: all exchange sessions from the first executable signal onward.
- Features and realized returns are kept in separate tables.

## Non-goals for v1

- No parameter optimization.
- No market-regime router.
- No intraday ORB integration.
- No production orders.
- No claim that the supplied historical universe is survivorship-bias free.
