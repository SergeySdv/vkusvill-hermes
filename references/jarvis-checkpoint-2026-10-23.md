# Jarvis OAuth pilot checkpoint — 2026-10-23

## Status: deployed pilot, not a finished release

Jarvis's isolated auth broker is deployed on hermes-research-01. The owner
completed the real VkusVill login/consent flow inside Telegram and returned to
the app's “connection saved” screen. The installed CLI reports configured.
client_secret_post succeeded for this particular registered client. This does
not establish the method for all clients, or prove personalized tools work.

Personal tools still fail: orders reports SCHEMA_CHANGED at items/meta validation;
favorite reports SCHEMA_CHANGED through the bridge. Owner says the account is
new with no orders. Empty-account response shape is a hypothesis, not a diagnosis.
No orders, basket links or personal-discount mutations were requested in this test.

## Architecture and deployment evidence

- Main code: /Users/sergei/Projects/vkusvill-hermes, branch
  feat/telegram-oauth-onboarding, version 0.5.0.dev0 (unpublished pilot).
- Operations: /Users/sergei/Projects/hermes-server-operations. Read its AGENTS.md
  and required server context before any server work.
- Server package: /home/sergei-admin/vkusvill-pilot-20261019-edge.
- Active pilot root: /srv/vkusvill-auth/jarvis; private vault is not mounted into
  Hermes. Hermes gets only a scoped bridge credential and wheel manifest.
- Jarvis: /srv/hermes/compose.yaml, container hermes-agent, data /srv/hermes/data.
- Shared infrastructure Caddy: /srv/infrastructure/caddy/compose.yaml and
  Caddyfile, container edge-infra-caddy-1, no longer managed by Buzz Compose.
- Public origin https://vv-jarvis.buzzersteam.net; registered callback
  https://vv-jarvis.buzzersteam.net/oauth/callback. No Cloudflare.
- Owner reported retry phase=applied and successful menu enable. Independent
  HTTPS probes: root 200, /ready and /bridge/status 404, Buzz root 200.
- CLI/bridge isolation diagnostic passed using copied vault/temporary state;
  this alone did not prove production OAuth. Subsequent real login did.
- Production uses a previously built wheel bundle, not automatically this commit.
  Bundle manifest SHA256:
  18ac1e030b99c3d6abf88792713db10cdbd36e93d1465dda3d61ba5aa7b03e38.
- Original deployment plan SHA256 remains
  1a7edc924d01f3f4ab3162f6277ec7996afa387f6b2ec41799eac84ebc58a503.

## Recovery and accepted exception

Fresh Oct23 encrypted Jarvis backup remains on server. Owner explicitly waived
off-host restoration verification because the 1.77 GB download was too slow;
download was stopped. Do not mark that restore verified. Caddy's fresh archive
was downloaded, decrypted, privately extracted and compared with its manifest;
this is not a restored-service boot test. Backup keys stayed on Mac.

The retry installer checks both ciphertext hashes/freshness and records a separate
false restore_verified receipt with a per-stack exception. Earlier failed
attempts retained the vault and restored live service files. Repeat rollback now
retains separate pilot-skill copies rather than colliding with the first copy.
Eleven unrelated containers retained IDs/status but had newer start times; the
owner supplied their exact stable snapshot. reviewed-outside.json permits only
that reviewed baseline; subsequent changes still fail closed. Do not discard
rollback files, disable inventory checks or rerun old migration scripts.

Current maintenance entry point is lib/jarvis_vkusvill-retry.py in the server
package; older wrapper/resume scripts do not include all later corrections.
The dated retry wrapper is not a general installer: archived checks and review
timestamps expire. Do not blindly rerun apply on an already applied pilot.
Sudo still requires the owner; no agent Docker socket or passwordless sudo.

## Next fixes and acceptance criteria

1. **Restore Hermes command menu; separate onboarding button.** menu enable
   replaced the owner's primary command-menu button with VkusVill. menu restore
   exists and was suggested, but execution is not confirmed. Add an explicit
   owner-only inline Web App button in a message without replacing bot commands.
   Preserve Telegram initData authentication; a plain external URL is not an
   equivalent substitute. Test both desktop and mobile Telegram, original menu,
   owner restrictions, duplicate installation and rollback.
2. **Simplify client setup.** Remove the technical auth-method selector from the
   normal VkusVill form; keep client_secret_post as the tested pilot method.
   Do not remove POST secret transport or put secrets in URLs. Preserve an
   explicit reviewed advanced configuration if other client methods are needed;
   do not silently retry credential methods. Test submitted method, masked input,
   secret clearing and absence of secrets from logs/model/bridge responses.
3. **Fix session/error UX.** Cookie max_age is 600 seconds. Reloading /connect
   without a valid session returned raw AUTH_REQUIRED JSON. Errors are currently
   rendered above the form, outside the viewport when submitting from the bottom.
   Add visible submitting/success/error state near the action, expiry recovery
   guidance/page and safe duplicate-submit handling. Reopen through Telegram to
   establish a new session; do not bypass cookie/state/PKCE validation. Test
   expiry before submit, refresh while expired, failed request, and callback
   within the same WebView. Never put credentials in browser persistent storage.
4. **Empty-account compatibility.** First collect sanitized structural evidence
   inside the broker: envelope status, field names/types and list lengths only.
   No raw personal payloads, tokens, client secret or callback query in chat/logs.
   Current read_tool accepts items=[] with meta=dict, but rejects missing meta;
   provider_data rejects successful data=null. Determine actual orders/favorite
   responses before normalizing them. Add fixtures and negative tests distinguishing
   legitimate empty results from AUTH_REQUIRED, malformed envelope and genuine
   SCHEMA_CHANGED. Do not convert arbitrary errors to “no orders”.

## Testing and rollout sequence

Checkpoint validation: Ruff PASS, full local pytest suite PASS (389 tests),
uv build PASS for wheel/sdist 0.5.0.dev0, staged diff whitespace check PASS.
One Starlette/httpx deprecation warning remains. These local tests do not prove
successful reads against the real empty account. Operations Jarvis suite: 44
tests PASS. Operations checkpoint commit: b3a8ca8. No live changes or push made
while taking this checkpoint. Heuristic staged credential scan found no private
key, age identity or Telegram-token patterns; this is not a comprehensive audit.

1. Reproduce each issue with unit/browser tests; retain strict token isolation.
2. Run lint, local regression tests, synthetic broker tests. Historical container
   gate passed with vv-caddy-test image; default image had a capability issue.
   Do not claim those results as a current full deployment test.
3. Build/review a new wheel/image bundle. Source edits do not update the running
   pilot. Follow operations backup, scoped deployment and rollback procedures;
   preserve vault/context/baskets. Never reinstall the published older Git pin
   over the wheel-based pilot.
4. Real acceptance: reopen app, connect, get configured, call orders/favorite on
   empty account, then exercise a populated account separately if available.
   No purchasing or cart creation is required. Test cancellation, wrong owner,
   expired session, and restart/recreate persistence in an approved window.
5. Verify token lifetime/refresh from actual provider behavior. Metadata advertises
   refresh support, while the supplied article describes 24-hour tokens and manual
   reauthorization; do not promise refresh merely from metadata. Consent “up to a
   year” does not establish access-token lifetime.

## Secrets and scope

No client ID/secret, bot token, access/refresh token, vault, seed or receipt with
private material belongs in Git. Keep this checkpoint distinct from a stable
release. No push, merge, new release or working-service modification is requested
by this checkpoint commit. Continue with UI/menu and empty-account fixes next.

## Follow-up working tree: testing an already connected account

Local changes after the checkpoint (not yet deployed): the ordinary form uses
client_secret_post without a selector; connected accounts hide the setup form;
expired form sessions receive an HTML recovery page, while API calls still fail
closed. Submission progress/errors appear beside the action and secrets are cleared
after submission. A separate explicit `--send-connect-button` broker action sends
an owner-only inline Web App message without changing the primary command menu.
The advanced API still accepts explicitly specified supported client methods.

Do not disconnect, replace credentials, copy the production vault into development,
or redo OAuth just to test UI. Synthetic tests use temporary encrypted vaults and
fake credentials, then connect once and reopen/expire the browser session while
asserting that account context and token-exchange count remain unchanged.

After a reviewed scoped rollout, test the real account non-destructively:

1. Restore the previously saved command menu using the installed maintenance
   entry point; separately send the inline Web App button with the new broker.
   This requires an operations integration review, not rerunning the old installer.
2. Open that button: expect connected status and no credential-entry form.
   Close/reopen and repeat; no new consent or secret entry should be needed.
3. Check auth status, then orders and favorite only. Capture sanitized response
   shapes inside the broker if SCHEMA_CHANGED persists, never token/response bodies.
4. Compare context/configured state before and after. Browser-session expiration
   must not disconnect the stored account. Expired access tokens are a separate case.
5. Restart persistence, failed/cancelled login, populated account, destructive
   disconnect and rollback tests belong in a synthetic deployment first. A live
   restart requires its own approved window and backup/rollback review.

Empty-account normalization remains deliberately unchanged until actual response
shapes are observed. Existing items=[] plus meta={} is valid already. Do not
translate missing metadata, null payloads or provider errors into invented empty
results. Production was not modified by these local follow-up changes.

### My VkusVill follow-up (after the UI pilot deployment)

Owner confirmed UI update applied with account preserved, command menu restored
and separate inline button delivered and pinned. That pinned button remains valid.
The next local revision changes new button labels to «Мой ВкусВилл», hides setup
instructions for configured accounts, and provides `auth connect --send-button`.
The skill instructs bare `/vkusvill` to call that command, using Hermes's normal
skill slash routing. This is not a deterministic native command handler; confirm
real Telegram routing after deployment. Reference:
https://hermes-agent.nousresearch.com/docs/guides/work-with-skills .

The new POST /bridge/connect requires the instance credential and an empty body;
it accepts no user-supplied recipient, message or URL. Delivery is owner-only,
duplicate requests within 60 seconds are suppressed, and uncertain delivery is
not retried automatically. No bot token crosses the bridge. Public Caddy routes
remain unchanged and must continue excluding all /bridge endpoints.

Tests cover CLI explicit send opt-in, owner restriction, duplicate suppression,
uncertain delivery, no account-context change and cancelling disconnect. Targeted
broker/browser/hardening tests, lint and build pass. This next revision is local:
deploying only its broker image is insufficient. Update the matching CLI runtime,
pilot manifest and skill through the scanner with rollback, preserving vault and
cart state. Do not reuse the previous dated image-only activation script.
Existing pinned messages are not edited or deleted by the new send operation.

### Subsequent deployment confirmed by owner

The coordinated update is now applied according to the owner's server output:
broker, CLI and skill updated; account preserved; other containers and command
menu unchanged. Stage: `/srv/vkusvill-auth/jarvis/my-update-1792745062322095311`.
Its 4100-byte encrypted auth backup was independently restored offline on Mac
before activation; record equality and configured status passed, no provider
request made. The owner subsequently reported the Telegram flow appears to work.
This supersedes the local-only status above; individual live UI cases have not
all been independently verified. Full local pytest suite and lint passed before
deployment, alongside operations updater tests (21 tests, 6 subtests).

Next: investigate orders/favorite SCHEMA_CHANGED on the owner's empty account.
Collect only sanitized keys/types/list lengths at the provider and broker boundary;
distinguish explicit empty data from missing fields, access errors or malformed
responses. Add regression fixtures for observed valid empty responses while
preserving failures for incompatible schemas. Do not reset authorization, create
orders or fabricate empty results to make the checks pass.
