REGIME-ADAPTIVE INTRADAY SYSTEM ROADMAP
=======================================

Main objective
--------------
Classify each trading day from information available at the decision time, then
activate an appropriate simulated strategy, basket, execution method, and risk
profile for that market regime. Every regime must ultimately have an active
response.

Completed foundation
--------------------
1. Realistic max-two-position portfolio simulation
2. Profit concentration and leave-one-out validation
3. Execution and cost stress testing
4. Parameter robustness testing
5. Yahoo/Nasdaq provider-quality gates
6. Exposure and capital-efficiency analysis with exact reconciliation

Completed regime foundation
---------------------------
7. Point-in-time regime feature foundation
7B. Strict 09:40 versus legacy 09:45 timing comparison

Current step
------------
8. Exhaustive provisional regime taxonomy with an active response for every session

Next steps
----------
9. Build and simulate the candidate playbooks mapped to each regime
10. Compare competing playbooks within each regime
11. Daily strategy and basket router
12. Unified multi-strategy portfolio simulation
13. Walk-forward unseen simulation

Research principles
-------------------
- Simulation-only until explicitly changed in a future project phase
- No look-ahead information
- Every model and playbook is versioned
- Frozen strategies are never silently edited
- Same-day outcomes are diagnostics, not classifier inputs
- Every regime receives an active response, although risk may vary by regime


STEP 9H - LOCKED CROSS-SECTIONAL HOLDOUT TRANSPORT
---------------------------------------------------
Freeze three primary Step 9G contracts and test them on 18 new companies in a separate holdout database.
The original market-regime taxonomy remains frozen. Results accumulate without threshold changes and never activate the router.
