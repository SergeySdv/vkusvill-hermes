# Implementation brief: offline scaffold 0.1.0

This implementation derives from the supplied vkusvill-hermes-design.zip.
The original brief, candidate skill, contracts, examples and proposed evals are
preserved without edits under references/design/. They describe a broader future
product; the active CLI contract is skills/vkusvill/references/cli.md.

## Implemented

- Python/Typer entry point, Pydantic local models, official MCP SDK v1 dependency.
- Product adapters that fail explicitly; no fabricated catalog responses.
- SQLite transactions, profile namespaces, parameterized SQL, private new files.
- Import as unverified local intent, duplicate normalization, revisions and state reset.
- Local check with pass/unknown evidence, 15-minute expiry and content hash.
- Link preconditions; link_created reserved, no external mutation in this version.
- Typed cart payload limits independent of human quantities.
- Stable JSON envelope and sanitized error boundary, offline tests, CI and packaging.
- Developer-only SDK discovery function with pagination; not called by doctor or
  normal CLI commands. Unit-tested with an isolated test double, not the live service.

## Deliberate differences from the original target architecture

Import does not yet resolve provider facts. It preserves product_id and human
quantity as unverified intent and rejects additional facts instead. Offline check
can mark the local revision checked, but its unknown results cannot authorize link.
No prices are calculated without verified facts. OAuth, credential storage,
product normalization, authenticated catalog context and real cart-link creation
are pending. There is no auth login command yet.

The only production path to link currently ends in REVIEW_REQUIRED or
NOT_IMPLEMENTED; no code writes link_created. This prevents an offline scaffold
from presenting unverified information as a successful provider action.

## TODO: live MCP discovery and reviewed contracts

1. Explicitly run public tools/list through discover_public, inspect/sanitize its
   output, and save reviewed input/output schemas with source and timestamp.
   Do not install server-returned prompts or auto-enable discovered tools.
2. Review authenticated schemas separately after trusted OAuth onboarding.
   Use SDK OAuth + PKCE, secret storage outside repository/argv/logs, bounded timeouts,
   and verified catalog/account scope. Do not read Hermes token internals.
3. Wire only the four allowlisted tools in mcp_provider.TOOLS. Compare schemas
   before use. require_schema/unpack_result are helpers, not domain validators.
4. Implement product snapshots and Decimal prices, verified id → xml_id mappings,
   unit conversion, quantity steps and deduplication by verified SKU. Reapply
   CartPayload limits after conversion/aggregation. Add captured sanitized fixtures.
5. Implement refresh with pass/fail/unknown and evidence. Strict unknown blocks
   link. Hash verified snapshots, catalogue scope and constraints. Validate freshness.
6. Before link, re-fetch required data and compare with the checked snapshot.
   Return REVIEW_REQUIRED with a safe diff on material changes.
7. Implement transactional revision checks around the network operation. Persist
   only a real provider link after host/scheme validation. Do not hold an SQLite
   write lock across a long network call; use revision compare-and-swap.
   Ambiguous mutation timeout → OUTCOME_UNKNOWN, no automatic retry.
8. Test successful checked → link_created and repeated link reuse with a test
   provider, concurrency, catalog changes and ambiguous outcomes. Only then enable
   the live transition. No order/payment commands.
9. Run installation and acceptance scenarios in the actual Hermes terminal backend.

Read-only retries: at most two retries with backoff, no infinite authentication
retry. This is a future local policy, not a claimed provider rate limit.
The original proposed agent evals are not reported as executed.
