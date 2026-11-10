# Local photo OCR — review workflow

Enabled locally through PHILIXA_LOCAL_OCR_ENABLED=1. JPEG/PNG images use an isolated RapidOCR 3.10.0 / PP-OCRv6-small CPU runtime. Bills are not transmitted to Gemini/Groq on this path. Digital PDFs keep the existing extraction route. Scanned-PDF support is not part of this local image adapter.

## Setup

The application and document worker must use the same Python/container image. Create `/app/data/local-ocr-venv` using `python -m venv --system-site-packages`, then install `requirements-local-ocr.txt` using that environment's pip. Document worker mounts this environment read-only. Configure PHILIXA_LOCAL_OCR_PYTHON for a different isolated runtime location. With local mode enabled, a missing runtime is an explicit error; no silent cloud upload occurs.

## Implemented

Invoice table rows are grouped using OCR boxes and recognized column headers. Header label/value geometry keeps buyer/seller and totals separate. Unsupported/incomplete layouts fail closed. GST table columns cannot silently shift if HSN is unreadable. Decimal arithmetic and GSTIN checksum validation produce review warnings; existing Tally master/tax/total gates remain authoritative before posting.

Every local line field preserves source text, confidence, page, original-image bounding box and dimensions. Low-confidence cells are re-read from an enlarged bounded crop. Re-read results are suggestions, not silent replacements. Exact Tally item/unit matches can provide an additional unit suggestion. Bills UI displays the original crop and an explicit suggestion-selection button. Saved corrections retain original source evidence and revision audit history.

## Verified and limits

Matching dummy PNG and JPEG passed upload -> ARQ worker -> needs_review saved draft. Their quantity/rate/discount/tax/total match INR 1,167. Original unit `qags` was re-read as `bags`; browser crop showed `bags`; explicit unit selection saved and survived reload. No Tally posting action was created.

Second digital invoice layout OCR tokens preserve three quantities 50/200/100 and total INR 42,461. Synthetic mild blur extracted the expected total. A synthetic tilted case had an unreadable HSN header and is rejected for manual review rather than shifting columns. These are small synthetic/document-derived fixtures, not a real-accountant accuracy benchmark. Handwriting, arbitrary layouts, camera photographs, severe blur and broad Hindi-language accuracy remain unverified. Local OCR is review-first, not autonomous posting.
