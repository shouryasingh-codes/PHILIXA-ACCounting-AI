# Philixa prompt package and decision evaluation

Date: 4 November 2026. Scope: existing supported task agent, no native posting.

## Diagnosis from source and saved task evidence

- `task_agent_model.py` previously held a single long inline prompt, no example
  library and no reproducible baseline-versus-revised decision harness. Saved task
  `936f607587fae1eed52e0d69b40da47e` demonstrated a model asking for complete
  purchase details before running any draft/context tool. Prompting and bounded
  runtime feedback address this failure mode; prompting cannot guarantee a tool call.
- Read requests previously inherited `verified_entry` completion rules. Tool-group
  selection and completion checks therefore disagreed with stock intent. Stock
  read routing now recognises bounded English/Hinglish/Hindi inventory questions,
  including a topic switch out of a purchase without modifying its saved task.
- The known bag/bags issue was an exact-unit comparison, not a language-model
  limitation. Native simple-unit resolution, history lookup and explicit-price
  preservation remain domain code. Historical rates still require confirmation.
- Context resumes had cleared observations, and generic model summaries could
  hide domain questions/results. Current saved context is hydrated; provider/quota
  failures remain visible instead of being hidden by an old proposal.
- Expanded worker tests exposed unnecessary draft hydration during status-only
  refresh. Situation capture now runs only for actual bounded situation evidence.
- Worker outages, Educational Mode rejection and live-stock timeouts are transport
  or environment issues. No number of prompt examples resolves them. The live
  stock timeout and broader connector/environment coverage remain separate work.

## Implemented package

`app/services/task_agent_prompt_baseline.py` freezes the original prompt verbatim.
`task_agent_prompts.py` separates core instructions, tool guidance, response style
and deterministic example selection. `task_agent_examples.json` contains 13
synthetic development examples; no customer bills, credentials or native identities.

The model, strict response schema, 2,048 completion ceiling, single transport
attempt and shared quota gateway are preserved. The complete system prompt,
selected examples, tool schemas and task evidence enter the gateway's existing
token reservation. Selection uses no model, network call or vector database.

Selection is capability-scoped, stable and bounded to at most three examples and
5,500 serialized example characters. Default is two examples. Unavailable tool
examples are excluded. IDs, exact message/context, explicit facts, next action,
response guidance and forbidden assumptions are stored per example. Tool and
document contents cannot rewrite core instructions or the example selector.

Per-response usage includes prompt version, prompt SHA256 and selected example
IDs. Existing task-run usage persistence retains these references. Examples do
not execute tools and cannot bypass server permissions, exact company identity,
grounding, arithmetic, duplicates, revisions, approval or journal reconciliation.

## Evaluation and reproduction

The held-out file is separate from runtime examples:
`scripts/fixtures/agent_prompts/heldout.json`. Its 12 cases include new products,
new quantities, Hindi, topic change, explicit prices/corrections, ambiguous identity,
bill-pending receipt, stale/offline evidence, conflicting rates, unsupported filing
and document instruction injection. Runtime selection never reads this file.

Commands inside the app container:

```sh
python -m scripts.evaluate_agent_prompts
python -m scripts.evaluate_agent_prompts --live
python -m scripts.evaluate_agent_prompts --live --resume
```

The first command is **offline contract replay**, not an AI benchmark. It validates
the grader, actual tool schemas, grounding, expected fields and prompt budgets.
It makes zero provider calls; passing identical replay decisions under both
prompts is not evidence of improved model behaviour.

Live mode compares single next decisions for both frozen prompts, alternating
order. It never calls a domain adapter. Confirmed free tier, shared gateway and
the existing 50-call local daily cap are required. Calls reserve AgentRun budget
atomically with the production advisory lock. Unsent quota deferrals release the
local call reservation; uncertain/transmitted calls are never blindly replayed.
Resume skips completed calls and refuses changed dataset/prompt/config hashes.
Quota stops preserve partial evidence and the actual provider retry time.

Artifacts:
- `data/agent-prompt-evaluation.json`: offline contract and estimated budget report.
- `data/agent-prompt-evaluation-live.json`: actual decisions, errors, usage, latency,
  prompt fingerprints, quota waits and unverified cases.

Measured checks cover next action, permitted/schema-valid tool arguments, explicit
fields and source quotes, invented/changed fields, expected disclosure and forbidden
success claims. User questions are represented by decision kind. Genuine repeated
questions across a complete multi-turn study, active review time and accountant
time savings are not established by single-decision evaluation; those remain null.

## Rollout and rollback

Default: `PHILIXA_AGENT_PROMPT_VERSION=baseline`. Existing flow remains available.
Pilot: set `PHILIXA_AGENT_PROMPT_VERSION=v2`; optionally set
`PHILIXA_AGENT_EXAMPLE_COUNT=0..3`. Restart the relevant worker after changing env
or cached example files. Unknown versions fail closed. Rollback to `baseline`
restores the exact frozen original instructions and disables examples.

This implementation does not switch real-company write flags or automation policy,
install a model, add paid services, or authorise native test vouchers. Do not promote
the revised prompt merely because offline replay passed. Inspect paired live
results and run the full browser review/reload workflow before wider rollout.

## Limits

This is a small synthetic next-decision evaluation, not representative accounting
accuracy. No real-accountant timing study or production release claim follows.
Example selection is intentionally simple capability/lexical selection; changing
models or adding more examples requires a new frozen comparison. Unsupported
valuation, layouts and native adapter limitations remain explicit review cases.

## Final verification checkpoint

- Paired live evaluation completed: baseline 8/12 versus v2 11/12 strict
  next-decision checks. Each version made 12 actual model calls. Both chose a
  fresh read instead of the rubric's preferred saved-stock answer in one case.
  No held-out-driven prompt changes were made during evaluation.
- Actual input/output usage: baseline 22,282 / 1,112 tokens; v2 23,490 / 1,065.
  Revised prompting did not reduce total tokens on this dataset. Median measured
  provider-call latency was 1,045.5ms baseline and 1,407ms revised; these are small
  samples and include network/provider queue effects, not accountant handling time.
- Final combined agent regression suite: 49 tests passed. Separate accounting/
  stock/quota/recovery suite: 51 tests passed. Suite counts can overlap; do not
  sum these as distinct test coverage. Revised-prompt process checks and UI
  regressions also passed.
- Worker reloaded with baseline as the default. v2 remains opt-in pending fresh
  browser acceptance and resolution/evaluation of the remaining behaviour.
- No native Tally posting was performed in this implementation/evaluation.
