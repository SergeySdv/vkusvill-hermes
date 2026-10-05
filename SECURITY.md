# Security

This release performs local operations and contains disabled provider adapters.
It has no token ingestion, OAuth login, live product calls, or cart-link side effect.
Do not put credentials in command arguments, request JSON, logs, fixtures or issues.

Runtime errors use fixed public messages; raw validation inputs and exception
strings are suppressed. SQL uses bound parameters. The CLI never spawns a shell.
Product descriptions must remain untrusted data when the live provider is added.

New state directories/files use POSIX 0700/0600. Use a private directory owned
by the current OS user; existing parent directories are not reconfigured.
SQLite stores shopping intent and preferences, which may be sensitive.
Do not use shared writable paths or untrusted symlinks. The app does not encrypt
state or isolate mutually untrusted processes under the same OS account.
VV_PROFILE is organizational, not authentication.
check_hash prevents accidental stale use; it is not a MAC or consent token.

For future OAuth, use SDK PKCE and a separate secret store. Never consume Hermes
internal token files. Unknown strict constraints must block link creation.
Ambiguous link timeouts must not trigger blind retries.

Report vulnerabilities through private security reporting on the eventual hosting
platform when enabled. If unavailable, request a private contact without posting
exploit data or secrets in public issues. No fabricated maintainer email is supplied.
