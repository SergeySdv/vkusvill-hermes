# Confirmed empty-account responses

Owner-run diagnostic on hermes-research-01 at 2026-10-24T15:54:21Z confirmed:

- orders: successful MCP envelope, data contains `orders: []` and a metadata
  object; the CLI incorrectly required the list under `items`.
- favorite: successful MCP envelope, `data: []`; the generic envelope decoder
  incorrectly required an object. This was not an OAuth rejection.
- Both input schemas match. No refresh, vault writes or service restart occurred.

Orders now normalize `orders` to canonical `items`, preserving metadata and
requiring an array of objects. Ambiguous dual lists and malformed pagination
remain errors. The previously accepted `items` representation is unchanged.
Only a successful favorite response with an exactly empty array normalizes to
`{"product": null}`. Other tools, nonempty favorite arrays, null data, provider
errors and authentication failures are not reclassified as empty accounts.

Regression tests cover both observed shapes through the real MCP SDK against a
local synthetic server, malformed alternatives and nonempty synthetic orders.
No production tokens or customer records are fixtures.

Deployment requires the coordinated broker/CLI update, preserving the vault.
After deployment request only orders and favorite: expect success with empty
items and null product. Do not create baskets or change favorites for this test.
Live rollout and automatic refresh verification are separate acceptance steps.
