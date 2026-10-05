# Contributing

Use Python 3.11+ and uv. Run uv sync --locked, make check and make build.
Enable pre-commit with uv run pre-commit install. Commit dependency changes with
their updated uv.lock. CI uses the same lock and checks Python 3.11–3.14.

Keep CLI argument parsing, application policy, models, persistence and MCP adapters
separate. No LLM, shell interpolation, implicit browser login, order or payment.
Use Decimal for quantities/prices. Do not infer missing facts.

Tests must be offline and exercise behavior. Synthetic test data must remain
clearly separated from live provider claims. Never record credentials in fixtures.
Before enabling a new MCP tool, review schemas and sanitized response fixtures.
New live link tests require an explicit user request; ordinary tests never create links.

Update the active skill references and changelog when commands change.
references/design/ preserves the supplied original package; do not confuse future
design commands with the implemented API.
