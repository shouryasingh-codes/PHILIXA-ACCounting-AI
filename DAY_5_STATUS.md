# Day 5 — accepted in the configured practice company

Completed 2026-10-14. Philixa Test now has a backed-up, local GST practice setup. This is acceptance of the supported purchase workflow in this Tally installation, not certification for every accountant/company or GST return filing.

## What works

Saved purchase drafts support domestic regular goods, intra-state CGST + SGST, inter-state IGST, mixed 18%/5% lines, line discounts, proportional pre-tax invoice discounts, paisa arithmetic, and disclosed round-off between -Rs1 and +Rs1. Original taxable amounts, tax totals and grand total must match. Missing/ambiguous masters, unsupported treatments and missing GST unit mappings block posting.

Company-scoped tax profiles and revision checks remain mandatory. Writes still require an explicitly authorized test-company configuration and purchase approval. Unknown delivery uses reconciliation, never blind resend. PHILIXA_GST_PURCHASE_ACCEPTANCE_ENABLED=0 remains an explicit kill switch; accepted code defaults to enabled.

## Real acceptance evidence

- Native Tally company backup: data/day5-native/tally-backup/TDBK1800_100000.001. Before-state exports are retained alongside it.
- Nine clearly prefixed dummy GST masters, separate synthetic supplier/company GSTINs, native Haryana Registration, and BAG-BAGS unit mapping configured locally. No portal/filing credentials were supplied.
- Independently entered/exported UI purchase reference: ui-reference-voucher.xml, originally Rs100 + Rs9 CGST + Rs9 SGST.
- Four final native fixtures: purchase vouchers 12, 13, 14, 15; totals Rs1167, Rs1167, Rs1050 and Rs1051. Tax-ledger amounts, every item, quantities/rates, discounts, HSN/UQC, invoice reference/date and explicit round-off compared to native exports. Initial tax metadata was corrected during acceptance before final export.
- Fresh create using the final XML codec: voucher 17, one matching voucher.
- Full application path: saved draft -> preview -> authorized dummy approval -> installed protocol-v8 helper -> native verification and refreshed snapshot. D5-APP-E2E is verified as voucher 18; draft 8b3e59204f6143b2c5be7dcecd182eba remains visible in Bills.
- Repeated submission did not create another voucher. Mutated amounts/tax/quantity/reference/HSN-unit data fail verification.
- During a standalone acceptance repair, an improperly identified alteration created duplicate dummy voucher 16. It was explicitly cancelled using native Master ID; backup and cancellation response are retained. This repair utility is separate from the application posting path. Earlier failed practice fixtures remain labelled in the company; the six baseline vouchers were not rewritten.

Native financial and tax-detail readback was verified. GSTR-3B classifies the final purchase fixtures under transactions of other GST returns; return filing/ITC reconciliation is not part of this acceptance. UTGST and other Tally versions/company configurations have not received separate native acceptance.

## Fixes found by real Tally

The codec now handles the empty Default Tax Unit, dated GST registrations, SGST/UTGST native head names, empty zero-cess/slab placeholders, native HSN/UQC fields, inventory-projected purchase ledger entries and the XML enum for zero cess. Tax source metadata is preserved.

Master fingerprints normalize XML whitespace/attribute ordering so saving/loading a snapshot does not invent a settings change. Actual tax-master changes still invalidate approval. Read-only validation failures retain their reason and allow a fresh reviewed preview; uncertain posting remains locked.

## Delivered and checked

FastAPI/Pydantic, PostgreSQL/SQLAlchemy/Alembic, existing Redis/ARQ workers, private MinIO intake, structured Gemini extraction, Decimal calculations, existing HTML/JavaScript and native Tally XML remain the stack.

22 focused GST/draft/native-export tests and 3 connection-state tests passed. GST UI persistence/ledger-selection/locked-preview regression passed. Connector 3.5.1 was built, installed with existing pairing preserved, and startup registered. Real live reads and four existing purchase readbacks also passed. The tally-worker was resumed.

Connector SHA256: 42CB873DAE39FB254B8B4BFCC2257DE113634D81CA8AFD43EA251582B3EE2B4C

Evidence: data/day5-native/application-e2e-proof.json, acceptance-report.json, final-*-proof.json, final-*-voucher.xml, codec-final-voucher.xml; data/day5-helper-install-final.json.
