# Quota-aware agent acceptance — 3 November 2026

Implementation is partial; full rollout acceptance is not complete.

## Verified

- Shared PostgreSQL quota reservations/cooldowns, bounded retries and 120-second scheduling have automated coverage in `scripts/test_groq_quota.py`.
- Existing live dummy supplier selection previously retained the same task/draft with no extra provider request.
- In-app browser acceptance today: model-free context refresh and explicit ₹350 rate selection retained task `b5ac3043472b2080aa3c0c654d5c19c0` and draft `54cabb8c653f35e9c8a848a3d9ff0403`.
- Before context refresh/rate selection: 5 gateway requests, 5,195 prompt tokens, 481 completion tokens. After both operations: identical counts. Draft revision advanced from 2 to 3; Sharma Traders, Cement, 5 bags and ₹350 were saved.
- Browser reload visibly reopened the same compact review: calculated before-tax amount ₹1,750. Invoice/date/tax remain unresolved; no action or native Tally voucher was created.
- Idle worker was restarted; saved state remained available. Active-action preflight was zero.
- Fixed context-status routing: it previously used a planner call. Typed context refresh now runs the existing domain context service directly. Exact legacy `Context status` / `Tally context refresh` commands follow this path only when a saved draft exists.
- Added idempotent context-refresh lifecycle test and worker test asserting the model is never called.
- Latest runs: quota/selection/lifecycle/worker subset 24 tests passed; added worker subset 2 passed. Earlier focused set 27 passed, accounting/receipt subset 25 passed, and chat restore/status-polling JS check passed. Counts overlap and must not be added as unique tests.

## Remaining acceptance

- A fresh end-to-end model-driven conversation is not passed: latest actual planning request returned Groq 403. Do not reinterpret this as quota exhaustion or retry it in a loop.
- Live 120-second wait UI simulation, complete final-review flow, broader context-compaction/capability checks and matched before/after evaluation remain pending.
- Browser screenshot capture failed; accessibility state verified reload, but no screenshot artifact was produced.
- Test shutdown emitted async connection ResourceWarnings in some runs; functional assertions passed, but cleanup needs investigation.
- Default rollout flags remain opt-in. Local review pilot is enabled. No unlimited free usage, overall accuracy or time-saving percentage is claimed.

Reproduce scoped dummy measurement: `docker compose exec -T app python -m scripts.quota_live_acceptance`. Output: `data/quota-ui-acceptance.json`; this reads only the named review dummy and does not call the model or post to Tally.
