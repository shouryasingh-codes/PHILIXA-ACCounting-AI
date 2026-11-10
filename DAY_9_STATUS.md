# Day 9 — synthetic evaluation complete

## Extraction follow-up — 20 October 2026

The previously identified supplier-header, explicit invoice-discount and low-confidence unit-reading gaps have been fixed and rerun against the **unchanged day9-v1 golden manifest**. Latest complete runs pass **166/166 fields and 6/6 exact files** (four digital PDFs, one actual PNG OCR and one actual JPEG OCR). Mapping remains 7/7, accounting 8/8 and simulated posting 4/4. See `data/day9/report.json` for the exact run timestamp, current source hashes, runtimes and latency; prior failing reports remain under `data/day9/runs/`.

PDF extraction now accepts supplier names that begin with Supplier/Seller/Vendor without mistaking them for labelled fields. Explicit invoice/bill/overall discount amounts, including zero, are read without deriving a discount from a total discrepancy. Conflicting or percentage discount evidence is not converted to an amount.

For low-confidence photo unit cells, two differently resized source crops must independently return the same alphabetic text with confidence at least 0.98 before that reading is used. Initial text, original confidence, bbox and both crop readings remain in source evidence. This uses the same local OCR model at two scales, not independent model validation. No Tally master or spelling dictionary substitutes a value; original low confidence still triggers review. One crop, disagreeing crops or low-confidence rereads leave the original value unchanged.

**50 regression tests passed** across evidence fixes, local OCR, extraction, evaluation metrics and controlled automation. The initial new test had an incorrect warnings lookup; it was corrected and the full suite rerun successfully. Known teardown ResourceWarnings do not indicate assertion failures. No cloud provider was called or real Tally voucher posted. Existing cached extractions/reviewed drafts are preserved rather than silently rewritten.

The report display now derives its pass/fail and gap wording from the latest results, instead of retaining the old failure description. This closes the bounded technical gaps; **real-world accuracy and accountant time savings remain unverified**. Real anonymised bills and an accountant evaluation are still needed. Photo review/automation gates remain unchanged.

## Historical first evaluation (superseded by the follow-up above)

Final report verified on **20 October 2026 (IST)**. **Real-world accuracy remains unverified.** No real anonymised bill/accountant study was available. Human time savings are unmeasured.

## Reproducible results

- Hand-authored corpus: `scripts/fixtures/day9/golden.json` (`day9-v1`). Four GST digital PDFs, including intra/inter-state mixed-rate lines, invoice discounts and nonzero round-off; PNG and JPEG generated from the first synthetic bill and passed through actual local OCR.
- Latest extraction: **154/166 strict fields correct; 0/6 complete files exact**. Mapping **7/7**, accounting **8/8** (four valid and four rejection cases), simulated posting **4/4**. These stage denominators are separate; downstream stages use golden inputs, not OCR outputs.
- **Extraction quality gate failed.** Missing supplier-header and invoice-discount evidence, plus `bags` read as `qags`, are retained in the report. Missing explicit zero discount is counted strictly even when accounting can default it to zero; discrepancies are not observed/necessarily required human edits.
- A prior run had a JPEG timeout (**128/166** fields); it was preserved with its source files under `data/day9/runs/2026-10-15T190618-prior-timeout`. The latest complete run and its original PDFs/images are archived separately under `data/day9/runs/`.
- Source/fixture hashes, generated-input hashes, Python/PyMuPDF/local OCR package versions and ONNX model hashes are recorded. Local OCR uses the existing isolated RapidOCR/ONNX runtime. No provider API call or new subscription was used; external API cost for the benchmark is $0, excluding local infrastructure cost.

Run again:

`docker compose exec -T app python -m scripts.evaluate_day9`

`docker compose exec -T app python -m scripts.build_day9_canvas`

Outputs: `data/day9/report.json`, `data/day9/report.md`, generated inputs, run archives and an embedded-data report canvas. `--skip-photos` deliberately marks the run partial, not complete. Posting uses an in-memory Tally transport and isolated SQLite journal; **no new real Tally voucher was posted for Day 9**.

## App measurements

- Added append-only `bill_evaluation_metrics` through additive migration `y1r8s9t0u1v2`.
- Draft saves record server-calculated field correction counts; equivalent numeric formatting does not count as a correction. These counts cover measurements from this implementation onward, not historical edits.
- Review time samples are company/workspace/user scoped and deduplicated by event ID. The browser counts visible, focused, recently active review intervals, excluding busy/idle gaps. Samples are estimates, may miss closed-tab intervals and are not an accountant time study. Agent QA interaction is not treated as human-accountant benchmark data.
- Extraction attempts record duration, outcome, method and provider-cost availability. Cached/local-only attempts record zero external API cost; unknown cloud billing remains null rather than becoming zero. Historic uninstrumented provider usage is not reconstructed.
- Posting records queued/result events and queue-to-result duration when available. Existing approval, policy, duplicate and uncertain-posting guards remain in place.
- Bills now has **Review metrics**. Browser verification confirmed a real review-time POST and a visible persisted result, with absent processing/cost measurements displayed as unmeasured/unknown. A missing POST default discovered during browser testing was fixed, and the browser asset version was bumped.

## Validation and deployment

- **53 backend tests passed** across evaluation, drafts, review queue, extraction and Day 8 automation. The expanded **6 evaluation tests** also passed, including actual cached extraction telemetry. The added test overlaps the earlier evaluation suite; do not add the two suite totals as distinct tests.
- **7 JavaScript suites passed**: active-review meter, evaluation UI and existing drafts/GST/review/memory/automation UI.
- Tests use scoped synthetic DB fixtures; native posting is mocked. Existing test teardown may emit psycopg ResourceWarnings; assertions completed successfully.
- Fixed evaluation-runtime subprocess cleanup on timeout and preserved failed-run evidence.
- Document and Tally workers had exited after the multi-day system clock jump (ARQ negative expiry). After confirming no queued extraction, no active Tally action and a paused automation policy, those two workers were restarted. Recovery/sync ticks were healthy. The unrelated general reminder worker was not restarted or used by Day 9.
- PostgreSQL, private originals, existing vouchers and connector pairing were preserved. Automation remains paused.

## Accountant evaluation next

Use `scripts/fixtures/day9/accountant-study-template.csv` and its README with authorised anonymised bills. Compare the same bills in balanced workflow order, include upload/review/corrections/exceptions, keep overlapping processing wall time separate and report errors as well as speed. Missing manual/review timings remain null; no savings percentage is fabricated.

Day 9 completes measurement and a reproducible synthetic evaluation. It **does not resolve the extraction gaps or establish production readiness**. Review gates should remain active while those gaps are addressed.
