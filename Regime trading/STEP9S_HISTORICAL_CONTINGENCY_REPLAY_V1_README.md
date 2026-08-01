# Step 9S Historical Contingency Replay V1

Status: `RESEARCH_ONLY_HISTORICAL_REPLAY_NOT_ROUTER_ACTIVE`

This module keeps two separate research books:

1. Natural strategy book: frozen trigger-based strategy outputs.
2. Mandatory coverage-control book: exactly one deterministic shadow trade per recognized session.

The mandatory control is not presented as a natural signal. Its purpose is to eliminate missing trade observations so forced activity can be compared with the trigger-filtered strategy.

## Safety

- Reads the taxonomy, frozen research CSVs, and price database read-only.
- Writes only new Step 9S historical output CSV/JSON files.
- Does not access or modify Step 9I or Step 9L ledgers.
- Does not modify Step 9I, Step 9L, Step 9Q, Step 9R, or ORB.
- Does not route or send orders.

## Expected historical result on the frozen 60-session sample

- Nine regimes assigned.
- 59 natural strategy trades across 38 sessions.
- 60 mandatory coverage trades across 60 sessions.
- 100% mandatory trade coverage.
- Natural strategy P&L: approximately +39.577580 SEK.
- Mandatory coverage-control P&L: approximately -46.896768 SEK.

The books must remain separate. The figures are historical research outputs, not prospective performance claims.
