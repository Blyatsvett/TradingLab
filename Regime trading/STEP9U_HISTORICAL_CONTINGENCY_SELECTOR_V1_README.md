# Step 9U Historical Contingency Selector V1

Step 9U is a separately versioned contingency challenger built on the frozen Step 9T historical observer dataset.

It does not alter Step 9S. Step 9S remains the frozen contingency benchmark, including its natural and mandatory-control books.

## Run

```powershell
.\run_step9u_historical_contingency_selector_v1.ps1
```

## Verified development replay

- Sessions/regimes/transitions: 62/9/6
- Morning-complete directional candidates: 970
- Selectable challengers: 158
- Blocked negative controls: 79
- Selected: 73 candidates across 43 sessions
- Complete/incomplete selected outcomes: 71/2
- Standardized selected diagnostic P&L: +388.299731 SEK
- Average selected outcome: +5.469010 SEK
- Selected outcome win rate: 63.38%
- Positive complete-traded-session rate: 73.81%
- Maximum diagnostic drawdown: -32.369267 SEK
- July 28 selections: 0

These values are retrospective, in-sample, and non-confirmatory. They do not justify promotion.

## Safety

- Mandatory control active: false
- Router active: false
- Orders enabled: false
- No source or frozen artifact is modified

## Feasible-oracle diagnostic hotfix

`step9u_selection_regret.csv` uses a future-information diagnostic oracle that may select zero to two positive candidates and obeys the same maximum-one-position-per-sector constraint as Step 9U. It never influences selection. The resulting opportunity cost is non-negative by construction.

