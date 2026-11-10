# Agent rate resolution — 4 November 2026

Common purchase preparation resolves the explicit bag/bags spelling alias
against an exact item and validated native simple base unit. Quantity and rate
remain unchanged. No arbitrary plural stemming or unit conversions are enabled.
Existing draft revision, preview invalidation and master-enrichment audit apply.

Native history lookup returns per-line rate_checks for provided, suggested,
unresolved and conflicting prices. Agent instructions require consulting scoped
context before asking for rates. Situation routing preserves available rate
suggestions instead of replacing them with a generic rate request. Compact UI
does not demand a manually typed price when an evidenced suggestion exists.

Historical values remain suggestions requiring confirmation; current explicit
prices win. Native identity, freshness, complete history and ambiguity guards
remain active. This is shared workflow logic, not a special price for Cement or
Sharma Traders, and no price is hardcoded.

22 backend tests pass, including automatic bag/bags resolution with unchanged
quantity/rate, plus connector/proposal UI suite. Worker reloaded. Earlier live
saved review verified native historical rate 350.00 sourced from 2026-10-02.
New visual end-to-end acceptance and native posting were not performed here.
