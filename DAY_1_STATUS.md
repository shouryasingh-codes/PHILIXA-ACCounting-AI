# Day 1 — Chat context and intent routing

Implemented and regression-tested on 2026-10-11.

## Behavior

- Detail replies such as `Cement`, `quantity 8 bags`, and `rate 350 per bag` retain the latest operation's conversation context.
- The interpreter and accounting scope guard use the same topic boundary. A purchase detail reply no longer becomes an inventory adjustment because the current message omits `purchase`.
- Fresh purchase/stock/report instructions start a new context; older sale or GST constraints do not leak into them. Purchase Register/report names cannot establish a purchase operation.
- GST, sale/return/delete and negation restrictions remain effective through multiple detail turns. Explicit removal/addition/physical-count requests keep their own routing.
- Structured form/selection requests retain their existing field and approval behavior.

## Verified flow

1. `Supplier se Cement purchase karna hai` → missing quantity/unit/rate form.
2. `quantity 8 bags` → same purchase, missing rate form.
3. `rate 350 per bag` → unapproved purchase preview, total 2800.00.

The integration test runs the real business graph and database-backed purchase preview. It verifies that only a `preview` action exists; no action is queued or posted by these text messages.

## Validation

116 tests passed across context, purchase synchronization, stock/count, XML, business graph, MCP routing and supplier-read suites. Development app health returned HTTP 200.

```powershell
docker compose exec -T app python -m unittest scripts.test_business_context scripts.test_tally_sync scripts.test_tally.XmlTests scripts.test_tally_count scripts.test_business_graph scripts.test_mcp_business scripts.test_tally_reads scripts.test_tally_suppliers -q
```

AI provider responses and Tally transport are mocked in these tests. They validate history delivery, deterministic guards, routing and approval boundaries; they do not measure live model extraction accuracy or certify real Tally posting. No paid provider calls, real Tally writes, or outbound messages were needed for this verification.

Conversation context remains bounded by the existing 10-turn request limit. This change does not introduce a new durable conversation-draft schema. Sales preview/posting is the subsequent milestone.
