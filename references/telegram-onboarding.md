# Telegram self-service connection (unreleased)

One package, two trust zones: install the CLI/skill in Hermes, run the optional
`vkusvill-hermes[broker]` service outside that container. No second agent or LLM.
This implementation targets **one owner and one existing Telegram bot per Hermes
container**, matching the current deployment. It is not a shared-agent multi-user
gateway. Never share instance credentials or volumes between owners.

The first rollout follows the [Jarvis implementation plan](jarvis-auth-implementation-plan.md):
an existing domain and Caddy, no Cloudflare, and no changes to other owners' stacks.
That plan defines acceptance gates; this prototype is not a completed live deployment.

The current offline implementation is `0.5.0.dev0`. For the pilot use the
[existing-Caddy Jarvis artifacts](../deploy/jarvis/README.md), not a second ingress.
[Administrator prepare and encrypted recovery](broker-recovery.md) keep secrets
out of Hermes and do not apply server changes automatically.

## User flow

1. Open the **Мой ВкусВилл** inline Mini App button in the bot's private chat.
   Keep the existing pinned button; it continues to open the same application.
   In the updated pilot, `/vkusvill` without a task instructs the skill to run
   `vv auth connect --send-button --json` and send another owner-only button.
   This uses Hermes's skill slash-command routing, not a new Telegram webhook.
   It is model-mediated and needs real Telegram acceptance after deployment.
   Both the broker and the CLI/skill must be updated; updating just the image
   does not add the flag to the CLI installed in Hermes.
2. The service verifies both the initData HMAC and Telegram's own Ed25519 signature,
   owner ID and 120-second freshness. HMAC alone is insufficient when the agent may
   know its bot token. The production Telegram public key is pinned in code; no
   runtime override or HMAC-only fallback. Clients without `signature` fail closed.
   The assertion is single-use; reopen the Mini App after expiration.
3. On a separate first-party page, enter the personal OAuth client details from
   VkusVill's email. Register the exact displayed HTTPS callback first. Scopes and
   token authentication method must match the granted client, not guessed examples.
4. Continue to VkusVill, consent, and return in the **same browser/WebView**.
   Password/SMS are entered only at VkusVill. A callback without the original
   secure browser cookie is rejected; do not copy callback URLs into chat.
5. The page reports that the connection is stored. Return to Hermes and ask for
   `auth status`, then a read-only `orders list` or `favorite show` verification.
6. Disconnect on the same authenticated page. This deletes the local connection
   and pending login; revoke the server-side consent at VkusVill separately.

Users register their own personal clients under the currently supplied VkusVill
registration rules. A single client for different loyalty cards requires provider
approval. **Acceptance of our HTTPS callback must be confirmed during registration.**
The service does not bypass registration or manufacture client credentials.

## Administrative deployment: once per instance

The agent must not provision its own security boundary. A trusted administrator
deploys the service, sets an HTTPS hostname and the existing bot's private-chat menu.
This does not start another Telegram poller or change the existing webhook.

- Build from this reviewed branch: `docker compose -p vv-user1 -f deploy/broker/compose.yaml build`.
  Supply `VV_PRIVATE_DIR` and `VV_AUTH_DOMAIN` to Compose. The former is an absolute
  host path **outside this repository and outside all agent mounts**.
- Create `broker.json` there from `deploy/broker/broker.example.json`, privately.
  Generate independent random bridge and encryption keys using
  `secrets.token_urlsafe(32)` and `cryptography.fernet.Fernet.generate_key()`.
  Do not print these through an agent terminal, store them in chat, or check them in.
- `broker.json` must be mode 0600, owned by container UID 10001. Create `vault/`
  with mode 0700 and the same owner. Parent host directories must be protected too.
  Docker secrets mounts that ignore owner/mode settings need administrator-managed
  file ownership; the service fails closed rather than relaxing these checks.
- Set `public_origin` to the bare HTTPS origin without a trailing slash,
  `owner_id` to the verified numeric Telegram owner, and `vault_directory` to
  `/var/lib/vv-auth`. Use this owner's bot token. No OAuth user secret is needed
  during deployment: the owner enters it later in the browser.
- Start the service with the Compose file. It exposes no host port for the broker.
  Caddy terminates TLS and proxies only exact public page/action routes. Bridge,
  readiness, health and unknown routes are not publicly proxied.
  The example Caddy container binds ports 80/443; on a host with existing ingress,
  integrate the equivalent routes into that ingress instead of starting competing
  listeners. Three owners need three distinct hostnames/upstreams and vaults.
- Send an entry point only to the configured owner, explicitly.
  Prefer an inline message without replacing the command menu:
  `docker compose -p vv-user1 -f deploy/broker/compose.yaml run --rm vv-auth --config /run/secrets/broker.json --send-connect-button`.
  This sends a message each time explicitly requested. If delivery times out,
  inspect the chat before retrying to avoid duplicate messages. For an existing
  pilot, separately restore the saved menu using its reviewed maintenance tool.
  Legacy `--set-menu` remains opt-in for deployments that intentionally use it.
  Only the legacy flag replaces the menu for that private chat. Coordinate any
  existing Mini App menu before applying it; it is not an automatic startup effect.
- Attach only the matching Hermes container to the project's `agent_bridge`
  network (`vv-user1_agent_bridge`). Keep the service alias `vv-auth`. Do not attach
  multiple owners' brokers to the same agent network.
- Give Hermes a **different** 0600 JSON file containing only `{"bridge_key":"…"}`,
  owned by the Hermes process UID, mounted read-only. Set
  `VV_BROKER_URL=http://vv-auth:8080` and `VV_BROKER_KEY_FILE` to that mounted file.
  This instance capability is intentionally accessible to its agent and grants
  access to the owner's allowed MCP operations, **not** export of OAuth secrets,
  browser login or disconnect. Never mount the broker config/encryption key/vault.
- Install this candidate CLI in the Hermes environment for testing. The published
  skill runtime pin still targets 0.4.0 and **does not include broker support**.
  Do not rewrite the immutable installer pin until there is a committed, published
  candidate and a new passing release gate. Do not advertise this as released.

From the candidate checkout, `uv sync --locked --extra broker` installs the optional
service; `uv run vv-auth-web --config /private/broker.json` binds loopback by default.
Production runs use the container entrypoint and administrator-managed HTTPS ingress.
No background secret delivery to the agent, temporary auth files in Hermes, or
OAuth tokens in agent environment variables are used.

## Isolation and limits

- No root on the host, Docker socket, privileged container, host PID namespace,
  auth service writable source/config mount, or shared secret volume for Hermes.
  Root inside an unprivileged agent container is not equivalent to host root, but
  audit capabilities and mounts rather than assuming isolation from container names.
- Browser session cookies: Secure, HttpOnly, SameSite=Lax, host-only, ten-minute TTL.
  All browser POSTs require the configured Origin and JSON, with a 32 KiB body limit.
  OAuth attempt: five-minute TTL, PKCE S256, random state bound to the browser
  session, atomic one-shot consumption before token exchange. Concurrent starts
  supersede prior attempts; failed/cancelled login preserves an existing account.
- Tokens/client config/PKCE are encrypted with Fernet in SQLite, bound to their
  record key, protected by file permissions and cross-process locks. The vault also
  binds to the owner and bot IDs; changing those settings cannot reassign a vault.
  Keys are not
  in the database; protect configuration backups separately. Database encryption
  does not protect against a compromised running broker, host administrator or
  compromised user browser. The service intentionally has no credential-export API.
- Telegram's SDK loads only on the initial identity page; the credential form has
  no external scripts, analytics, persistent browser storage or Telegram sendData.
  Identity still trusts Telegram and the service operator; it is not anonymous E2EE.
- The bridge pins the VkusVill endpoints, checks reviewed MCP schemas and validates
  arguments, requires explicit mutation confirmation and enforces basket limits.
  The existing CLI remains responsible for budget/availability/checked-hash logic.
  A compromised agent can use its own authorized API capability; this architecture
  protects raw secrets and other instances, not an owner's data from their own agent.
- No auto-retry of mutations. Uncertain bridge transport failures become
  OUTCOME_UNKNOWN. Refresh is serialized and persisted before tool calls.
  Login/disconnect changes invalidate basket contexts; refresh retains the context.
- Do not enable HTTP body/header tracing, access/query logs, APM request capture,
  proxy debug logging or error-report attachments. Callback URLs contain codes.
  The service disables access logs and returns sanitized errors. Ingress, host,
  backup and network telemetry need a separate deployment audit.
  The example Caddy config excludes HTTP runtime logs as well as leaving access
  logs disabled: upstream errors must not record callback query strings. If merging
  into an existing proxy, preserve this policy; disabling access logs alone is not enough.
- Service concurrency is bounded; add deployment-level connection/rate limits
  before public exposure. Pin production container images by reviewed digest.
- Legacy terminal OAuth files remain untouched. If migrating a previously logged-in
  agent, revoke those grants and remove the old local credentials privately;
  selecting broker mode alone does not erase historic secret copies/backups.

## Verification / release checklist

Automated tests use synthetic Telegram signatures, OAuth HTTP responses and MCP
data. They cover signature/owner/bot mismatch, freshness/replay, browser binding,
duplicate callback parameters, CSRF, cancellation/failure preservation, encrypted
restart, refresh locking, bridge scope, mutation limits, and CLI without AuthStore.

Run `make test-broker` and `make broker-build broker-smoke`. The latter checks the
installed package and assets as a non-root process in a read-only, network-disabled
container, with disposable synthetic configuration and no real credentials. CI
runs this separately from the existing installer release gate. It does not establish
that an actual Telegram WebView/provider callback works on a public domain.

`make broker-browser` runs Chromium against a real loopback HTTPS app with synthetic
Telegram/provider assertions (self-signed test certificate only). Install Chromium
with `uv run --locked --group browser playwright install chromium` first.
`make broker-containers` runs two isolated synthetic owners through Caddy, validates
the test CA, blocked bridge paths, cross-instance access, restart/recreate and logs.
It publishes no host ports and deletes only its uniquely named disposable stack.
`VV_CADDY_TEST_IMAGE` may select a locally verified Caddy build if Docker Hub is
unavailable; this must be reported, not represented as a test of the production image.

Before production rollout, separately verify with an actual user:
- Provider registration accepts the exact HTTPS callback and client method/scopes.
- The menu opens on target Telegram mobile/desktop clients. The WebView must retain
  its secure cookie through provider navigation; fail closed if it opens a different
  browser. External-browser handoff is not implemented in this version.
- A second Telegram user/bot/agent cannot use the first owner's session/capability.
- No secrets appear in actual gateway/ingress/container/monitoring logs or agent mounts.
- Login, read-only order/favorite, expiry/refresh and disconnect work end to end.
- No personal discount generation, cart link creation, ordering or payment is used
  merely to test login. Browser consent is human-operated, not part of CI.

References: https://core.telegram.org/bots/webapps#validating-data-for-third-party-use
and https://www.rfc-editor.org/rfc/rfc9700.html.
