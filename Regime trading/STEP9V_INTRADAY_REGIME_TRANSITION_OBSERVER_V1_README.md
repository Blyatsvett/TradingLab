# Step 9V Intraday Regime Transition Observer V1

Status: `RESEARCH_ONLY_INTRADAY_OBSERVER_NOT_SELECTOR_NOT_ROUTER_ACTIVE`

Step 9V observes fixed intraday checkpoints without changing the frozen Step 9U morning selection.

## Fixed checkpoints

| Checkpoint | Completed source bars through | Counterfactual action price |
|---|---:|---:|
| 10:30 | 10:25 | 10:30 open |
| 11:30 | 11:25 | 11:30 open |
| 13:30 | 13:25 | 13:30 open |
| 15:00 | 14:55 | 15:00 open |

Each checkpoint stores 29 ticker states and reviews only the tickers selected by Step 9U. The review action is `KEEP`, `REDUCE`, or `EXIT`. `EXIT_AND_SWITCH_RESEARCH_ONLY` is preserved only as an EOD counterfactual and can never change a position.

## Live commands

Run one command near each checkpoint:

```powershell
.\run_step9v_checkpoint_v1.ps1 -Checkpoint "10:30"
.\run_step9v_checkpoint_v1.ps1 -Checkpoint "11:30"
.\run_step9v_checkpoint_v1.ps1 -Checkpoint "13:30"
.\run_step9v_checkpoint_v1.ps1 -Checkpoint "15:00"
```

The wrapper refreshes only the raw Step 9I price database, then seals Step 9V. It does not rerun Step 9I, Step 9L, Step 9S, Step 9R, Step 9T, Step 9U, or Step 9Q.

At EOD, after the regular EOD workflow:

```powershell
.\run_step9v_eod_v1.ps1
```

## Research boundary

Step 9U V1 remains the frozen morning challenger. Step 9V cannot select, route, reduce, exit, reverse, or send an order. Its EOD outcomes compare the original Step 9U hold with hypothetical exit, 50% reduce, and switch alternatives.
