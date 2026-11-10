# Layout reader candidate — 10 November 2026

Status: candidate implemented; initial real-document gate FAILED. Review pilot OFF. Normal stored-document/browser acceptance NOT PASSED.

## Implemented

- Separate CPU-only PP-StructureV3 image, private internal Docker network, no published port, no application credentials, read-only filesystem, one inference process, 4 GiB/2 CPU budget, 90-second process deadline, bounded input/output. Main backend and RapidOCR venv unchanged.
- Explicit model names/local directories; build-time official artifact acquisition and per-file hashes; resolved dependency versions retained inside image. No inference-time model downloads should be possible on the private network. Runtime acceptance must confirm this.
- Pydantic layout/cell contracts, row/column evidence, original coordinates, raw OCR, strict source references, printed-total checks, one Groq request and no old semantic fallback stacking.
- Existing upload fallback feature flag `PHILIXA_LAYOUT_REVIEW_ENABLED` (default 0), durable test-company job guard, private layout artifact storage, existing draft validation/review state and no action creation.
- Browser crop `bbox` evidence compatibility; field and line geometry retained; Groq invocation is not reported as zero external usage.
- Isolated source-file probe and labelled evaluation harness. Missing labels/results cannot pass the pilot gate.

## Runtime compatibility finding

PaddleX 3.3.13 initializes `ChartRecognition` unconditionally in `layout_parsing/pipeline_v2.py`, even with chart processing disabled. Build inspection confirmed this source behavior. `layout_reader/compat.py` applies an exact, version-bound conditional initialization fix only inside the isolated image, recording before/after source hashes. Changed upstream source fails the build. This changes dependency loading, not invoice contents or extraction decisions.

## Verification evidence

- Combined OCR/layout, quota, invoice and attachment regression run: 110 tests passed (see `data/layout-regression.log`). Existing unclosed database connection ResourceWarnings remain.
- Initial broad run caught an outdated attachment-test fixture missing the current router's required conversational response. Fixture updated; targeted test passed. Router behavior was not changed.
- No live candidate extraction, saved-draft/browser acceptance, held-out accuracy or Tally posting claimed by these tests.

## Commands and rollback

Build: `docker compose -p accounts-dev -f docker-compose.yml -f docker-compose.layout.yml --profile layout-review build layout-reader`

Start only the isolated service: same compose files/profile with `up -d --no-deps layout-reader`.

Integration requires app/document-worker on the internal network, as declared by the override. Do not recreate unrelated services or enable the review flag before acceptance. Default compose and flag 0 preserve the current route. Disable the flag to roll back; source files and saved drafts remain.

Probe: `python -m scripts.probe_invoice_layout SOURCE --output REPORT --url http://layout-reader:8097`; add `--live-model` only for one measured existing-Groq request. It does not insert drafts or post vouchers.

## Outstanding acceptance

- Complete actual image build, verify private-network initialization and source cell coordinates against original images.
- Fresh TimeNet/HANDS/components runs and three-repeat TimeNet correctness, followed by ten distinct labelled held-out layouts.
- Normal MinIO source -> leased worker -> saved review draft -> source crop -> browser reload.
- Report cold/warm latency, peak memory, exact fields/rows, calls and usage. Keep pilot OFF if gates fail. A matching subtotal is not proof of item/supplier identity or real-world accounting accuracy.

## Actual source-file runs (not mocks)

TimeNet PDF hash: `32077a700a3a5ce3dcf8c6a88251ee54def044a8199679af31c643d0deae34ab`. The PDF was not changed for these tests. Expected-answer manifest was not supplied to the reader or model.

- Small PP-DocLayout-S: no table detected for TimeNet and HANDS. Source layout output labelled the TimeNet table as image. Candidate not accepted.
- Official larger PP-DocLayout_plus-L: TimeNet table recovered with six numeric item rows, rates/amounts/units and printed totals; source cell coordinates retained. Reader process measured roughly 18–19 seconds and 1.5–1.7 GiB peak RSS. These are observed page/process runs, not general performance guarantees or a warm persistent-model benchmark.
- Initial model reservation was 9693 tokens, exceeding free-profile minute capacity. Removing redundant keys/duplicated schema text reduced it below 5500; nonempty source cells were retained and local schema validation stayed mandatory.
- Two diagnostic calls initially used empty `groq_api_key` while this deployment configures `ai_api_key`; ledger recorded HTTP401. Fixed and consolidated production/probe interpretation in one helper with a regression test for generic-key-only configuration.
- Live4 selected the six item rows and correct header references but marked annotation rows unclear; full acceptance blocked.
- Live5 returned six quantities/rates/amounts/units and matching printed subtotal 326100.00, tax 58698.00, total 384798.00, but incorrectly selected GSTIN-only cells as party names and labelled line amounts tax-inclusive. This is NOT a passed invoice. Party-name identifier evidence now rejects; unresolved tax basis is unsupported review evidence. No values were hand-filled to repair the run.
- Final repeat1 was rejected by the provider (most recent content-free ledger entry after that run: HTTP400); no successful final-configuration repeatability established. The provider's exact rejection cause remains unproven.
- HANDS with larger reader: ambiguous table-cell order; normalization rejected it. No table ordering was guessed to force a draft.

Consequently no pilot enablement, durable original-document retry, new saved review draft or browser-success claim is made. Three clean final repetitions and ten labelled distinct held-out layouts remain pending; the gate failed before those release checks. No Tally posting was performed.

Raw isolated artifacts: `data/public-invoice-preparation/layout-*.json` and `.reader.json`. Dependency/model provenance: `data/layout-reader-*-*.json`, `data/layout-reader-resolved-requirements.txt`, pinned `layout_reader/requirements.lock`, build logs. Public rollout remains disabled.

## Resumed verification

- Locked dependency image build completed. Running artifact ID: `sha256:391301d02c32c9cb0d5964b4b2f1a1ea001d8d5275bb8e7294e8edfb2a8defda`. App flags were explicitly checked: layout review 0, legacy semantic review 0.
- Numeric source grounding now assigns OCR tokens to cells using unique geometric overlap, before checking their numeric values. This fixes double-claiming tokens at overlapping row boundaries without selecting a source token by its expected amount. TimeNet's item quantities/rates/amounts/HSNs are grounded; an unrelated stamp counter remains unconfirmed. Unconfirmed selected numeric evidence is rejected.
- Large provider error bodies used to be truncated before JSON parsing, hiding the error code. Bounded full JSON parsing now exposes HTTP status and allowlisted error code without leaking generated document content. Latest fresh locked-runtime run confirmed HTTP400 / `json_validate_failed`; reader took 85 seconds in that run, versus earlier 18–19 seconds. Performance is variable and has not passed a representative benchmark.
- A flat, source-reference-only transport was added to reduce nested output burden; canonical row/evidence checks are unchanged. Its isolated fresh-model diagnostic still returned `json_validate_failed`. Another diagnostic reached local validation but did not establish a passed result. No successful final-configuration extraction or repeated end-to-end acceptance is claimed.
- Current focused source/layout/transport/quota suite passed 55 tests. Latest broad regression passed 118 tests in 94.647 seconds (`data/layout-regression-current.log`). A subsequently added durable-scope guard test also passed: absent job scope cannot call the reader/model. These tests do not establish live invoice accuracy.
- Accuracy gate is separate from the full pilot gate. Held-out accuracy alone cannot enable release without repeatability, resource, worker/browser, crop and regression evidence. Missing acceptance evidence stays pending.

The remaining blocker is reliable final model interpretation/structured output, plus HANDS cell-order ambiguity. Stored-document/browser rollout and ten-layout held-out evaluation remain unpassed. No source values were edited or inserted by hand, and no Tally writes were performed.

## Current contract verification

Column-role sample references now use uniform zero-or-one integer arrays, with local cardinality validation. Focused layout, gateway and semantic tests: 54 passed. A fresh Groq call against the previously captured actual TimeNet reader output passed provider JSON validation but failed source-role validation: `Column sample must be an unmerged item cell`. This is a cached-reader diagnostic, not fresh end-to-end acceptance. No review draft or Tally action was created. Candidate remains OFF; model cell-role accuracy and full worker/browser acceptance are still unresolved. Report: `data/public-invoice-preparation/layout-column-list-diagnostic.json`.

## Source-reference contract fix and runtime check

- Source IDs are constrained by shared JSON Schema `$defs` enums, avoiding repeated enum token expansion. Samples are zero-or-one reference arrays, locally cardinality-checked; all row, source grounding and arithmetic checks remain.
- Fresh model over cached actual TimeNet reader evidence produced six rows and printed subtotal 326100.00 / IGST 58698.00 / total 384798.00. This is **not** full upload acceptance. Supplier evidence is the source text TimeNet, not a verified legal master identity. OCR description imperfections remain review issues.
- 103 regression tests passed (277.129s); focused layout tests passed separately after source-enum assertions.
- Installed PaddleX flags.py reads `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK`, not the previously configured `DISABLE_MODEL_SOURCE_CHECK`. Corrected Dockerfile, runtime and Compose environment; actual container log confirms hoster checks skipped. Running image retains old source files with the corrected Compose environment, so a rebuilt artifact remains required before release.
- Fresh end-to-end probes: first ReadTimeout (~125s); second HTTP 504 (~96.6s). Candidate performance gate failed; flags stay OFF. No upload review success, no Tally writes claimed.

Third fresh PDF run: reader completed in 42573ms, peak RSS 1750476KiB; full interpretation still rejected invalid column sample (48583ms overall). Therefore three-repeat acceptance remains failed, not passed. Subsequent diagnostic deferred on minute quota; no bypass. Source-reference audit callback and private probe wire capture added to retain the next invalid mapping without replacing model output. Original upload remains unresolved and feature OFF.

## Column-role revision (2026-11-10)

Model wire format now selects explicit table/column identities rather than arbitrary item samples. Column-grouped context retains all source cells and row identities. Runtime reconstruction maps each role to each actual item row and reuses source/row/arithmetic validation. Source-only money-reference candidates exclude labels/percentages. Description validation rejects serial-only rows; source-derived description candidates exclude numeric/quantity columns. Explicit MODIFIED TEST COPY text cannot be removed by model classification. No vendor name, expected amounts or answer manifest are extraction inputs.

Fresh failures remain evidence, not passes: layout-columns-fresh1 had correct numeric columns but selected subtotal/tax labels; layout-columns-final1 selected serials as description; layout-columns-final2 reader completed 22091ms/1650408KiB but model rejected with json_validate_failed. A cached-reader model run had previously returned a numerically correct result with serial descriptions; the new serial guard prevents that false acceptance. Thus current 20B interpretation has NOT met repeatability acceptance and the upload is not fixed/released. Candidate flag stays OFF. Tally actions/vouchers were not created.

During editing, a Windows encoding exception truncated the source file; restored from verified prior editing records, compiled and retested, then used UTF-8 atomic replacement for subsequent edits. No app restart or feature enable happened during the truncated interval. The recovery is not an OCR acceptance result.

Final regression after restoration and column/money/description guards: 108 tests passed in 71.996 seconds. ResourceWarning reported open test DB connections; no test failures. Live end-to-end acceptance remains failed; do not enable candidate or claim upload fixed.

## Explicit local enablement
User explicitly requested enabling the new path despite failed acceptance. Local .env PHILIXA_LAYOUT_REVIEW_ENABLED=1; app/document-worker recreated with layout Compose overlay. Worker flag 1 and reader /health HTTP 200 verified; test-company scope and source/calculation validation remain. This is experimental review enablement, NOT accuracy acceptance or public release. No posting was authorised/enabled by this change. Existing failed upload requires an explicit retry to create a new extraction generation.
