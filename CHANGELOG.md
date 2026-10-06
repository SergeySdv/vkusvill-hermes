# Changelog

## 0.3.0 — 2026-10-06

- Pin skill runtime to published CLI commit 3cde6fe (all ten adapters).
- Release installation gate verifies pristine skill bytes, pip commit provenance and installed code.
- Real previous-runtime upgrade with preserved profile baskets, failed download/doctor recovery,
  and repeat installation; no model credentials or real cart mutations.

- Adapters and reviewed input schemas for all ten advertised MCP tools: barcode, discounts,
  recipes, shops, orders and favorite added, with local argument validation and protocol tests.
- Preserve recipe/shop filters and discount terms; map provider auth/not-found errors without raw text.
- OAuth remains unsupported; personal success responses are synthetic-tested, not account-verified.
- Updated skill publication remains separate from CLI publication; main is not changed automatically.

- Protocol regressions for HTTP failures, timeouts, pagination, profile isolation and post-mutation disconnects.
- Fail closed on repeated discovery cursors and ambiguous MCP tool errors after link submission.
- PR container smoke, price-change/uncertain-result model scenarios and repeated evaluation runner.
- Verified OAuth discovery and documented the client-registration gate; OAuth remains unsupported.

- Skill bootstrap/launcher use an explicit environment allowlist instead of inheriting agent secrets.

- Real SDK/CLI protocol tests against an explicitly synthetic local MCP server.
- Digest-pinned disposable Hermes container, candidate skill smoke and opt-in LLM scenarios.
- Trace/state graders, bounded runs, private artifacts and manual container CI workflow.
- Explicit loopback-only test endpoint with synthetic-data warnings; production default unchanged.

## 0.2.0 — 2026-10-05

- Live public MCP search, details, analogs and real basket-share links.
- Reviewed runtime schema checks, normalized snapshots and Decimal estimates.
- Strict constraint gates, fresh-data comparison and pending mutation tracking.
- Live doctor and updated Hermes workflows; no OAuth, checkout or payment.

- Link-based Hermes installation guide, native skill install, and isolated CLI bootstrap.
- Pinned CLI source revision, profile-aware runtime/state, PATH-independent launcher.
- Tests for repeated setup, failed installation, profile paths and literal argument forwarding.

## 0.1.0 — 2026-10-05

- Initial offline vv CLI, SQLite basket revisions, checks, hashes and unknown states.
- Strict local request and provider cart-payload validation.
- Explicit disabled MCP adapters plus developer-only official-SDK discovery helper.
- Hermes skill with current CLI reference and future workflows clearly separated.
- Offline tests, dependency lock, Ruff/pre-commit, build configuration and GitHub CI.
- Original design package retained under references/design/.
