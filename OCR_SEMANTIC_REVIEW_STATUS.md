# OCR -> GPT-OSS20B isolated review experiment

Date: 2026-11-10. Status: feature-flagged upload fallback implemented, default OFF; live extraction acceptance NOT PASSED.

## Scope

`app/services/ocr_semantic_invoice.py` is an interpreter called by the local OCR upload path only when PHILIXA_OCR_SEMANTIC_REVIEW_ENABLED=1 and the existing parser cannot read the layout. The flag remains OFF; normal uploads are not yet switched over. It accepts RapidOCR text/boxes and asks existing Groq GPT-OSS20B to identify fields through source token IDs. All values are reconstructed locally from referenced tokens. Pydantic rejects missing/extra structure, bad references and duplicate quantity evidence. Missing fields stay missing. Numeric ambiguity, incomplete coverage and arithmetic mismatches become review issues.

Every result is review-only (`requires_review=true`, `posting_allowed=false`). It cannot create a draft, choose a company, invoke tools, approve an action or post a voucher. OCR confidence is explicitly separate from unverified semantic interpretation. A matching total is not proof of supplier/row correctness.

## Execution

`scripts/probe_ocr_semantic_invoice.py SOURCE --output REPORT` performs a dry-run estimate with no provider call. `--live` enables one transmitted attempt using the existing shared quota gateway, existing key and the fixed GPT-OSS20B baseline. There is no automatic retry, format fallback, paid-provider fallback, quota bypass or permanent configuration change. Optional `--json-mode` / `--text-mode` are explicit diagnostic experiments; the same local Pydantic/evidence checks always apply. Text transport only accepts an entire JSON object or an enclosing JSON fence; partial JSON and surrounding prose are rejected.

Too-large input is rejected, not silently truncated. Source data is not given SQL/XML/shell/tool execution. Output files are local diagnostic artifacts with document data; they are not public API responses.

## Verified evidence

- Contract, source-only numeric reconstruction, invalid/duplicated references, missing fields, arithmetic mismatch, tax-inclusive basis, malicious source text, oversized/invalid geometry, coverage, duplicate taxes, truncation/refusal and one-attempt transport have automated tests in `scripts/test_ocr_semantic_invoice.py`.
- 66 tests passed: adapter plus existing local OCR, retail OCR, transport, PostgreSQL quota and invoice-extraction regressions. The integration suite also emitted existing unclosed-connection ResourceWarnings; no test failure was reported.
- Real RapidOCR tokens for the failed TimeNet adapted public invoice were used; expected amounts were NOT included in the model prompt or inserted into a draft.
- Additional token sets were obtained from the unchanged public SCTCE source, pages 4 (HANDS laptop/case) and 3 (computer components). No new invoice was fabricated.

## Live results: do not label these a pass

- Several invoice-schema requests were rejected by Groq with HTTP 400 / `json_validate_failed`. A minimal structured transport probe succeeded; this is not evidence of invoice accuracy. Exact provider root cause remains unproven.
- One TimeNet JSON-mode response passed shape validation but returned zero item rows, combined supplier address with the name and referenced repeated totals. Local checks reported unresolved coverage/ambiguous numeric sources. Expected six rows were not recovered.
- A computer-components strict-schema response also returned zero rows / unresolved coverage. It is NOT a successful extraction.
- A plain-text transport candidate failed local output validation. Quota deferrals were also observed and did not transmit requests.
- Latest context encoding is a readable `id|box|text` transcript instead of a dense JSON array. Its first live run was quota-deferred; a later admitted run still failed with HTTP400 / json_validate_failed. Its extraction acceptance is NOT passed.

Raw diagnostic JSON is under `data/public-invoice-preparation/semantic-*.json`. Reports correspond to the prompt/format at their run time; they must not be presented as held-out performance for the latest prompt. Prompt development examples are not a held-out benchmark.

## Remaining work before any rollout

1. Resolve provider output failures and incomplete row coverage with a controlled, versioned evaluation; do not manually fill extraction results.
2. Handle OCR source loss: TimeNet's full legal supplier name was not present in its captured OCR tokens. An LLM must not invent the missing legal name from the logo/address. Recover source evidence or require review.
3. Compare complete field/row results against original pages, then evaluate unseen layouts; record latency, usage and corrections.
4. Only after acceptance connect this adapter to the durable document worker with authenticated document/company scope and normal draft validation. Existing OCR and Tally posting paths currently remain unchanged.

There is no claim of 100% accuracy, successful end-to-end posting, or a completed production OCR fix.


## 10 November continuation

- Added a flat source-reference transport schema and semantic column-heading mapping. Application code reconstructs cells from OCR geometry; deskew and wrapped row descriptions preserve original source coordinates.
- Replaying one actual successful provider selection against the original OCR tokens recovered six rows and reconciled subtotal 326100.00 + IGST 58698.00 = total 384798.00. This was an adapter replay, NOT a persisted upload draft or repeatable live acceptance.
- Fresh strict-schema calls recorded in semantic-final-timenet.json and semantic-consistent-timenet.json returned empty column/header selections. Local checks rejected them with Invoice columns unresolved. A prompt inconsistency about nested fields versus flat keys was removed, but the subsequent call still failed. Root cause of unreliable model selection remains open.
- 66 regression tests passed on the current implementation. Three additional upload-fallback tests passed in a 21-test adapter suite: supported legacy layouts make zero model calls, unresolved semantic layouts return 422 without a result, and empty column maps are rejected.
- Feature flag NOT enabled, durable document retry NOT performed, no normal-upload success claimed, and no Tally posting performed.
- Remaining: obtain reliable source selections on fresh calls, test independent layouts, then enable limited review fallback and retry the original stored document through the normal durable worker. Missing legal supplier text remains unresolved source evidence.
