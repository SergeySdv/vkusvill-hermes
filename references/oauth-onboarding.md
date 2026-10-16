# OAuth onboarding (development branch)

Auth is implemented in this checkout, NOT in the published 0.3.0 runtime pin.
Use `uv run --locked vv` here until a reviewed release updates the installer.

## Verified contract — 2026-10-16

Public sources (no credentials used):
- https://mcp.vkusvill.ru/mcp
- https://mcp.vkusvill.ru/.well-known/oauth-protected-resource/mcp
- https://oauth.vkusvill.ru/.well-known/oauth-authorization-server
- https://vkusvill.ru/oauth/registration/

Resource: `https://mcp.vkusvill.ru/mcp`; issuer: `https://oauth.vkusvill.ru/`.
Authorization: `/oauth2/auth`; tokens: `/oauth2/token` on the issuer.
Authorization-code, refresh-token and PKCE S256 are advertised. Device auth is
advertised too, but its availability for your client is not established or implemented.
Supported client methods: `none`, `client_secret_basic`, `client_secret_post`.
Resource scopes differ from issuer scopes: specify scopes granted to your client.
Discovery does not establish client-specific permissions or redirect URIs.

Public tool documentation now uses cart `id` instead of `xml_id` and adds personal
discounts. Schema migration is separate; strict SCHEMA_CHANGED checks remain.

## Human-operated login

Register your client on the VkusVill registration page while logged in. Confirm
the exact redirect URI, granted scopes and token authentication method. This CLI
supports only a fixed-port HTTP callback on 127.0.0.1. The example below is NOT a
claim that VkusVill allows that redirect for every client. If it is disallowed, stop.

Create a file OUTSIDE the repository, mode 0600, in a private terminal:

```json
{
  "client_id": "YOUR_REGISTERED_CLIENT_ID",
  "client_secret": "YOUR_CLIENT_SECRET_IF_REQUIRED",
  "token_endpoint_auth_method": "client_secret_post",
  "redirect_uri": "http://127.0.0.1:18765/callback",
  "scope": "YOUR_GRANTED_SCOPES"
}
```

Omit the secret for public clients (`none`). Never paste credentials, the email,
callback URL/code or tokens into chat. Use the same VV_STATE_DIR and VV_PROFILE as
Hermes. Run in a private interactive terminal (not the agent's captured terminal):

```sh
uv run --locked vv auth login --client-file /private/path/vv-oauth-client.json
uv run --locked vv auth status --json
uv run --locked vv doctor --live --json
uv run --locked vv orders list --page 1 --json
uv run --locked vv favorite show --json
```

Open the URL printed to stderr in your browser. Login waits up to 300 seconds,
verifies state and exchanges the code with S256 PKCE. Stdout is sanitized JSON.
Cancellation/timeout preserves the previous session. Shopping never starts consent.

## Remote/container Hermes

The callback must reach the CLI network namespace. Arrange an administrator-managed
SSH local forward from the browser machine to the remote loopback port, plus a
loopback-only container mapping where needed. Match the registered port exactly.
Run login in a private interactive terminal in that environment. Never expose
the callback publicly or paste callbacks into Telegram. If no safe tunnel can be
arranged, stop: device-code and copy/paste callbacks are not implemented.

## Security and behavior

Linux/macOS (POSIX) only. Secrets are stored separately from baskets at
`$VV_STATE_DIR/auth/$VV_PROFILE/session.json`. Defaults are `~/.local/state/vv`
and `default`; the skill launcher overrides the state location. Directories are
0700, files 0600, writes atomic, refresh and MCP calls serialized by a process lock.
Absolute expiry persists across restarts; refresh-token rotation is saved.
This is plaintext storage protected by OS permissions, not encryption against
the account, its agents or root. Protect backups; use a dedicated OS account.
Successful login copies the private client configuration into the store.

Invalid grants require explicit login; no silent public fallback. OAuth discovery
and token redirects are disabled. MCP uses the SDK's same-origin redirect policy;
cross-origin redirects and test endpoints cannot receive credentials. A mutation
is not automatically replayed after 401. No Hermes credential caches are accessed.
Lifecycle uses MCP SDK PKCE/discovery/token models and explicit HTTP exchange
rather than automatic interactive SDK auth, to avoid implicit consent and replay.

Basket checks bind to the login session. Recheck after login/logout/account change;
refresh preserves context. Availability, address prices and delivery remain unknown.
Set a delivery address in the VkusVill account independently.

`vv auth logout --json` deletes local secrets only, not baskets or browser sessions.
Revoke server consent at VkusVill separately. Status is local, not proof of server validity.

## Acceptance

Tests use synthetic tokens and HTTP responses plus a real loopback callback.
Live acceptance requires a registered client, human browser consent and read-only
orders/favorite checks. No real accounts in CI; no checkout or payment commands.
