# Real-business automation release gate

Requirement recorded **21 October 2026**. This is a release-evaluation requirement, not a claim that a runtime policy gate or real-data study has been implemented/completed. Current synthetic results and test-company acceptance do not satisfy it.

This is a **rollout gate, not a "100% accuracy" guarantee**. Zero observed critical errors is bounded evidence about evaluated cases, not proof about future invoices.

## Minimum dataset

At least **200 distinct representative real invoices, labelled and verified by an accountant**, including a separate **100-invoice held-out set**. The minimum is 200 total: at least 100 development/evaluation invoices plus 100 held-out invoices. Synthetic/generated invoices, reuploads and PDF/photo copies of the same invoice do not increase this count.

Use authorised, private and appropriately anonymised sources. Cover the intended pilot population: different suppliers/layouts, digital PDFs, scans and phone photos, multi-item and mixed-tax invoices, discounts/round-off, poor/missing evidence and supported/unsupported cases. Record representation and subgroup counts; 200 conveniently similar invoices do not establish coverage. Include the expected correct outcome for rejection/review cases, not only successful entries.

Accountant truth includes company/buyer, supplier identity, invoice number/date/financial year, all items/units/quantities/rates/discounts, HSN/tax heads/taxable amounts/totals/round-off, supported treatment, duplicate grouping and the expected review/block/eligible outcome. Labels come from the original and accountant judgement, not unverified model/parser outputs. Resolve label disagreements explicitly and retain dataset/label revisions.

## Held-out discipline

Freeze the split, labels, candidate code/model/configuration and acceptance thresholds before inspecting held-out outcomes. Keep every copy/reupload/page variant of the same invoice in the same split; do not leak held-out aliases, corrections or approved mappings into development. Document supplier/template overlap and any limitations of generalisation.

Use the held-out set only for final evaluation. If its outcomes guide a fix, prompt/model change or mapping correction, it has become development evidence: reserve a new untouched 100-invoice held-out set for the next release claim. Preserve failures in denominators. Do not tune thresholds after seeing held-out results or rerun the same set until it passes and call it unseen.

## Release decision

Dataset size is necessary, not sufficient. Predefine complete-invoice, review/block, coverage and posting-verification criteria before final evaluation. Additional numerical thresholds are not yet specified; do not invent them or approve release using sample size alone.

### Auto-post candidates: zero critical errors

The auto-post candidate subset must have **zero observed critical errors** against accountant-labelled truth. Any one of these fails the real-automation release gate:

- Wrong company/buyer or wrong supplier identity.
- Wrong invoice reference or invoice date.
- Missing, extra or incorrect item lines, including incorrect item identity, quantity, unit, rate or discount affecting the entry.
- Incorrect tax treatment, tax ledger/head/rate or tax amount.
- Incorrect invoice total or unauthorised/hidden balancing or round-off adjustment.
- Duplicate posting, including after retry, timeout, repeated approval, reupload, different source format or restart.

Freeze candidate eligibility and applicable company/master/automation policy before evaluating held-out outcomes. Include every case selected as an auto-post candidate at decision time; report candidate count, share of all held-out invoices, all critical errors and each error type separately. Do not retroactively label a failed candidate as review/unsupported, drop it from the denominator or change its date/reference to pass. Timeout or missing verification is unresolved evidence, not a verified success. A zero-candidate or unevaluated subset does not pass this gate; no minimum candidate count beyond nonempty has yet been agreed, so report its actual size and representativeness explicitly.

Check the final persisted/native voucher, not only extracted fields or a preview. Candidate identity/line/tax/total comparisons use accountant truth and source evidence; duplicate checks include original and repeated delivery across the relevant workflow. Do not deliberately create wrong/duplicate real-business postings to test failure: exercise fault injection in isolated fixtures/test companies and validate the authorised native path separately.

If a critical error is found, stop real-auto-post release, preserve the case, fix the cause and rerun regressions. If held-out feedback guided that fix, use a new untouched held-out set for the next final evaluation. Zero errors observed on a finite sample does not guarantee zero future errors; keep audit, verification, pause and uncertainty controls.

### Evidence applies per policy

Each proposed real-auto-post policy needs representative eligible examples for its actual scope: company, approved suppliers/items, invoice formats/quality, tax treatment, amount limits and relevant operating conditions. Overall dataset size or another policy's passing result cannot substitute for that evidence. Link the policy revision, eligibility rules, candidate counts, subgroup coverage and evaluated code/model/master versions to its rollout decision.

If eligible examples are insufficient or do not represent the policy's scope, the policy **must remain in shadow mode**, even with zero observed critical errors. Shadow decisions are recorded; actual posting still requires human approval. Do not enable auto mode simply because a tiny subset has no errors. Per-policy sufficiency/coverage criteria must be agreed before final evaluation; no numerical per-policy minimum has yet been specified, and the global 200/100 requirement does not automatically satisfy it.

A material policy, supplier/item/master, format or tax-scope expansion requires evidence for the changed scope before auto rollout. Retain the previously evaluated scope separately rather than carrying its passing label onto an untested expansion. Runtime enforcement of this evidence gate is not yet implemented by this document; current company policy settings alone are not evidence of rollout approval.

Report extraction, mapping, accounting and native posting/recovery separately; include critical error counts, abstentions/review rate, subgroup performance, per-bill corrections, active accountant review/exception time, latency and provider cost. Include failures and uncertainty; do not claim production accuracy or time savings from synthetic latency. Compare the same authorised bills with the manual accountant workflow when claiming savings.

### Suggested product gate: at least 50% lower median active handling time

**Target, not a current measured result or marketing claim:** on a matched representative real workload, median Philixa active handling time, including review and corrections, should be at least **50% lower** than the manual baseline.

For the same evaluated invoice set, record manual active handling time and Philixa total active handling time. Philixa time includes upload/intake interaction, source review, corrections, approval, validation/duplicate exceptions, retry/reconciliation work and verification needed to finish the task. Use equivalent completion/accuracy standards in both workflows. Allocate material setup/batch overhead consistently; do not hide it or double-count review/correction time.

Predefine the primary calculation as `1 - median(Philixa total active handling time) / median(manual active handling time) >= 0.50` on the same matched sample. Report sample size, both medians, paired per-invoice results, variability, failure/unresolved counts and subgroup results. Median paired percentage savings is a different statistic and must not be silently substituted. Missing or zero manual baselines cannot establish a pass. Unfinished/error cases must remain visible and cannot be selectively dropped to manufacture a result; predefine their handling before the study.

Use representative accountants/workloads and balance workflow order to reduce familiarity effects. Record processing/waiting wall time separately from active human time; blocking waits that prevent other work should also be disclosed. Synthetic parser/OCR latency and agent QA interaction do not establish accountant time savings. This suggested product target is separate from zero-critical-error safety and per-policy evidence gates: speed does not waive them. No matched real-workload timing study currently substantiates a 50% savings claim.

Real unattended automation remains a release **no-go** until the real dataset, untouched held-out evaluation, agreed quality criteria and native recovery/security checks pass. Reviewed test-company pilots and synthetic validation are separate evidence. Photo/scanned/handwritten auto-post eligibility still requires its own evidence gate; this dataset requirement does not enable any automation policy.
