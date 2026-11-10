# Local protocol 11 connector update — 3 November 2026

Completed on the current Windows PC only; not a public release or Windows matrix acceptance.

- Installed connector upgraded from 3.7.1 to hash-pinned 3.8.0 candidate (protocol 11).
- SHA256: `5473307b93b3123e05d8e2e8d3ca820c45e7f4781f244e939e9c346799f0800b` matched existing packaged transport/history/invoice/receipt/MCP acceptance evidence.
- Settings and previous executable copied to a recovery directory; SQLite backed up consistently with integrity check. Existing pairing unchanged, connection settings preserved, installed hash matches candidate, final journal integrity `ok`.
- Standard installer drains old helper and launches registered startup; no force-kill, protection change or voucher posting.
- Live server heartbeat: online, protocol 11, receipt capability and legacy history capability true. Fresh native snapshot read passed after update.
- Corrected status API to choose highest advertised protocol (11 → 2), retain legacy capabilities on 11 and advertise receipt capability. Previously highest-key detection began at 8.

Evidence: `output/connector-380-update-proof.json`, `data/connector-380-live-proof.json`. Recovery directory is recorded in the update proof; credentials are not written to that proof.

The diagnostic initially attempted receipt validation without the required action authorisation; the server rejected it and the caller timed out. No write occurred. That diagnostic was corrected to perform connectivity/native reads only. Receipt validation/posting must use the separately authorised action pipeline; previews are never promoted merely for testing.

No native Receipt Note was created or verified in this update. Existing receipt preview may need regeneration to replace its old protocol-10 blocker. Public signed distribution and supported Windows-version matrix remain separate gates.
