# Implementation brief — 0.2.0

The original design remains unchanged under references/design/.
This release implements the public vertical slice for Hermes:
search → details → local request → refreshed check → share link.

## Boundaries

Hermes owns selection, preferences and user-facing reasoning. The CLI contains no
LLM. Provider is a protocol; MCPProvider uses the official SDK, Streamable HTTP,
initialize/list_tools/call_tool and strict reviewed schema comparison.
No new server, daemon or parallel agent is needed for this workflow.

## Implemented

- Public search with pagination, product details and analogs.
- Sanitized input schemas captured from live tools/list, packaged with the CLI.
- JSON-in-text and structured-content decoding, MCP and provider error handling.
- Real product snapshots, distinct id/xml_id, Decimal estimates and quantities.
- Basket checks with explicit blocking/nonblocking unknown statuses.
- Fresh read before link, material snapshot comparison and hash/revision checks.
- SQLite pending-attempt reservation before the side effect; network work outside
  write transactions. Uncertain results block retry and edits.
- Actual provider share links accepted only on the reviewed HTTPS origin/path.
- Link-based installation with a pinned CLI revision and live doctor verification.

## Scope limits

Public catalog only; stock/address/personal prices remain unverified.
No OAuth credentials, login, recipes, discounts or order-history commands.
No checkout/payment. Strict composition exclusions fail closed; substring absence
does not prove safety. Only whole sale units for шт and kg/g for кг are converted.
Unknown availability blocks only when explicitly required.
Goods estimate does not include delivery or guarantee regional prices.
The existing check hash schema safely invalidates old offline reports: recheck.

## Remaining work

Trusted SDK OAuth onboarding and separate secret storage, authenticated catalog
scope, richer unit/step evidence, and an explicit reviewed recovery procedure for
unknown link outcomes. Do not add blind mutation retries.
A universal MCP server wrapper can later call the same application/provider layer;
the current delivery and acceptance target is Hermes skill + CLI.
