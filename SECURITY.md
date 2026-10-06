# Security

The CLI calls the official public VkusVill MCP for search, details, analogs and
cart-share links. It does not authenticate, accept tokens, place orders or pay.
Never put credentials in command arguments, shopping requests, fixtures or issues.

Only reviewed tool schemas are enabled. Provider data is untrusted, cannot execute
code and is never interpolated into shell commands. Errors suppress raw input
and exception strings. SQLite uses bound parameters and private newly created files.
See references/mcp.md for transport, schema, timeout and link-origin protections.

Use a private state directory owned by the current OS user. Parent directories
are not reconfigured. Shopping preferences may be sensitive; state is not encrypted.
Avoid shared writable paths and untrusted symlinks. VV_PROFILE is organizational,
not authentication. check_hash prevents accidental stale use, not malicious edits
by the file owner. No multiple-user credential sharing is supported.

Public availability/address/prices are not authenticated. Strict unknown
constraints block links. A pending/unknown link attempt must not be retried
blindly; no order or payment can occur through the available commands.
For future OAuth, use SDK PKCE and a separate secret store; do not read Hermes caches.

The skill bootstrap installs a pinned CLI source in an isolated environment only
after an installation request. Dependencies use pyproject ranges; the development
lock is separate. Native Hermes installation scanning must not be bypassed.

Bootstrap subprocesses and the skill launcher inherit only an explicit environment
allowlist: OS paths/temp/locale, named Hermes/vv settings and proxy/CA settings.
Model keys, Telegram tokens, arbitrary VV_* variables, Python import overrides,
SSH agents and pip index overrides are not forwarded. Proxy URLs may themselves
contain credentials: configure them only when needed. This limits environment
inheritance, not filesystem access or credentials in user-level Git/pip config.

Use private vulnerability reporting on the hosting platform when available.
Otherwise request private contact without publishing secrets or exploit details.
