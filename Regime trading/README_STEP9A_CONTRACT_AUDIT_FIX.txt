STEP 9A CONTRACT AUDIT FIX
==========================

Purpose
-------
Fixes the isolated Step 9A review result where only the first observed session
failed the point-in-time contract gate.

Root causes
-----------
1. The first observed session had no prior-session history, so Step 7 marked the
   feature row as not fully point-in-time-ready. Step 8 correctly routed it to
   DATA_LIMITED_DEFENSIVE, but Step 9A incorrectly required the fallback to pass
   the same prior-history gate as directional strategies.
2. Step 8 and Step 9A both contained portfolio_structure and
   research_risk_multiplier. The merge created suffixed columns and Step 9A
   exported blanks.

Fix
---
- DATA_LIMITED_DEFENSIVE passes only when the explicit data-quality override is
  active and its deterministic defensive contract is executable.
- Directional and other normal playbooks still require a point-in-time-safe
  taxonomy row and an explicit 09:40 router cutoff.
- Contract fields are prefixed before merging, preventing blank exports.
- Data-limited requirements no longer claim that prior-session history is
  required; deterministic static configuration is documented instead.
- Coverage now exports the taxonomy safety flag and an explicit contract-audit
  reason.

No strategy performance logic or production code is changed.
