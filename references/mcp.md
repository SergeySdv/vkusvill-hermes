# MCP implementation and trust boundaries

Live discovery and public reads were inspected on 2026-10-16.
src/vv/schemas.json stores eleven reviewed input schemas. Runtime discovery
checks their structural contract; descriptive prose is not executable policy.
Other discovered tools are not enabled. A new required field fails closed.

The official SDK owns Streamable HTTP, session initialization and protocol framing.
Each CLI operation uses one bounded session; basket refresh batches details in it.
Total request timeout is 90 seconds and SDK read timeout is 30 seconds.
No application-level automatic retries are performed. A mutation timeout is
OUTCOME_UNKNOWN; do not assume cancellation, rollback or server idempotency.

MCP isError is checked before structuredContent; otherwise only a JSON text object
is decoded, never eval. The provider's nested ok/data envelope is separately checked.
Product facts are validated and normalized; remote descriptions remain untrusted.
Schema drift and incompatible product responses return SCHEMA_CHANGED.

The endpoint is fixed to https://mcp.vkusvill.ru/mcp. Development OAuth forwards
credentials only to its trusted origin, never test URLs. SDK/http logs are suppressed at
the CLI boundary. Product text is never passed to a shell or an LLM by this code.
Mutating tools are cart-link creation and personal discounts, never checkout.
Personal discounts require OAuth and explicit `discount personal --confirm`:
the first daily call can generate a selection. Never use it in doctor, discovery,
background checks or retry it automatically on uncertain outcomes.

Current cart lines use product `id`, not `xml_id`. The legacy field is retained
only for reading old snapshots/payloads; it is never guessed or sent. Old checked
baskets require refresh. Equal legacy xml_ids never merge different product ids.
Search no longer advertises xml_id. Orders retain provider products and timestamps;
personal discounts are returned as provider data, not invented normalized records.

Provider schema currently says cart maxItems=30, while its own description says
1–20. The application keeps the stricter 20-item contract. The link parser accepts
only HTTPS vkusvill.ru / www.vkusvill.ru root URLs with a numeric share_basket
query parameter. URLs are not followed automatically.

Availability in a public response cannot establish delivery availability:
the normalized status remains unknown. A user-required availability constraint
blocks the link; otherwise it is an explicit warning.
Strict ingredient exclusions cannot pass merely because a word is absent.

SQLite serializes local revisions; network calls run outside its write locks.
A pending reservation prevents concurrent mutation/reimport and remains after a
process crash. The server offers no reviewed idempotency contract, so an unknown
attempt cannot be retried automatically. A successful fresh request is reused
locally. check_hash is not user consent or an authentication boundary.

Sources:
- [MCP transport](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [MCP tools and errors](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- [Official SDK](https://github.com/modelcontextprotocol/python-sdk)
- [VkusVill endpoint and tool descriptions](https://mcp.vkusvill.ru/mcp)
