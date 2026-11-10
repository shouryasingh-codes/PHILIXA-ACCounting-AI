# Day 9 protocol

`golden.json` is hand-authored synthetic truth; do not regenerate expected fields from parser/compiler outputs. Change its version when changing the corpus. `scripts/evaluate_day9.py` generates source PDFs from these inputs and scores actual bytes. PNG/JPEG run the installed local OCR subprocess. No cloud request or real Tally write is used.

Extraction, mapping, accounting and posting have separate denominators. Mapping includes exact, fuzzy, ambiguous, approved alias and changed master cases. Accounting includes valid mixed-rate intra/inter-state cases, invoice discounts and disclosed round-off, plus rejection cases. Simulated posting checks verification, one write on duplicate delivery and tampered voucher rejection. It does not replace native Tally acceptance.

Golden field discrepancies are not observed accountant corrections. Explicit zero evidence is strict: missing is not extracted zero. There is no estimate of human review speed or savings from parser latency. Cloud API cost is zero only for this offline evaluation; local infrastructure cost is excluded. Production measurements store unknown provider billing as null.

For a later accountant study, use the CSV header provided. Obtain permission for anonymised source bills; do not put GSTINs, names or invoice numbers in timing sheets. Use the same bills, balance workflow order and record repeated trials with anonymised IDs. Count all active Philixa upload, review (including corrections) and exception-handling time. Do not count correction time twice. Keep processing wall time separate, since it may overlap other work. Compare error rates as well as speed. Pair savings per bill: `(manual active - total Philixa active) / manual active`; report sample size and dispersion, including negative savings and failures. Missing values remain missing.

Without an accountant and real anonymised bills, mark **synthetic evaluation complete; real-world accuracy unverified; human time savings unmeasured**.

Real unattended automation has a separate minimum: 200 distinct representative accountant-labelled real invoices total, including 100 untouched held-out invoices. Synthetic/generated bills and format duplicates do not count. Freeze labels/split/thresholds before final evaluation; if held-out feedback is used for fixes, replace it with a new untouched held-out set. See `REAL_AUTOMATION_GATE.md` for the full release protocol. The synthetic corpus in this folder does not meet that requirement.

The suggested product target is at least 50% lower median total active Philixa handling time, including review/corrections, than the manual median on the same matched representative real workload. This primary ratio-of-medians target is separate from the descriptive paired per-bill savings formula above; report both clearly if both are used. No current real-workload timing evidence establishes that target as achieved.
