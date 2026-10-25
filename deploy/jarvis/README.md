# Jarvis pilot — prepared artifacts, not a live deployment

Target: `hermes-research-01`, Jarvis only, existing Caddy and
`vv-jarvis.buzzersteam.net`. No Cloudflare and no second public listener.
The package candidate is `0.5.0.dev0`; published skill pin still installs 0.4.0.
Production acceptance still requires the [implementation gates](../../references/jarvis-auth-implementation-plan.md).
An administrator-operated unpublished pilot can now be packaged without changing the
Git release pin: `make pilot-bundle PILOT_OUTPUT=/absolute/new/directory`.
The operations repository has `bin/prepare-vkusvill-pilot`,
`scripts/remote/jarvis-vkusvill` and `docs/JARVIS-VKUSVILL-PILOT.md` for the full package.
It stages the current server configuration and refuses baseline drift, unsafe backup
receipts or unapproved shared Caddy recreation. No live deployment has been performed.

## Offline prepare

Trusted administrator only, outside Hermes. Install the optional `[broker]`
package in a private environment. Supply a private 0600 JSON seed file containing
`public_origin`, verified numeric `owner_id`, and this bot's `bot_token`.
No VkusVill client secret is needed; the user enters that later in the browser.
Never read the seed through the agent or paste its content into chat.

```sh
vv-auth-admin prepare --seed-file /private/jarvis-seed.json \
  --directory /private/jarvis-candidate \
  --image 'registry.example/vv-auth@sha256:REVIEWED_DIGEST'
```

Replace the placeholder with a real 64-hex digest after release review. This creates
only a local 0700 bundle with 0600 broker config, bridge capability and non-secret
manifest, plus an empty private vault directory. Repetition preserves existing
keys byte-for-byte. Changed owner/bot/origin/image or mismatched bridge key fails
without replacing the bundle. Nothing contacts Docker, SSH, DNS or Telegram.

`broker.json` is for the isolated service; `bridge.json` is intentionally for Hermes.
Never mount the bundle directory in Hermes. At the approved installation step,
place config/vault outside agent mounts, owned by service UID 10001, modes 0600/0700.
Make a separate bridge-only copy owned by the actual Hermes UID, mounted read-only.
The container config uses `/var/lib/vv-auth`, not the administrator's host path.

## Integration review, before apply

- Validate `compose.yaml` with `VV_AUTH_IMAGE` set to the same reviewed digest and
  `VV_PRIVATE_DIR` pointing at protected host storage. It has no published ports
  and no Caddy service. Do not run the standalone `deploy/broker/compose.yaml` here.
- Create private, per-instance `vv-jarvis-bridge` and `vv-jarvis-ingress` networks.
  Only Jarvis/auth join bridge; only existing Caddy/auth join ingress. Auth has a
  separate egress network. Never attach any OpenViking or other owner's container.
- Review the current Compose networks first. Adding a network override to a
  service that previously used implicit `default` can disconnect its old network.
  Preserve the complete current network set; do not guess from historical examples.
- Hermes receives only `VV_BROKER_URL=http://vv-auth:8080` and
  `VV_BROKER_KEY_FILE` pointing at its bridge-only mount. The broker-aware launcher
  must already be installed. No Docker socket or OAuth environment variables.
- Add the site in `Caddyfile.site` to the existing configuration. Do not replace
  its global block, existing routes, data volumes or reload mechanism. The fixture
  verifies Caddy 2.11.7. Verify the actual server's version and module support.
- Access logs are discarded for this site. `handle_errors` returns a fixed message
  and the disposable ingress test verifies callback canaries absent from runtime
  logs during an upstream outage. Custom global debug/trace/error logging still
  requires a separate audit on the existing ingress.
- The fixture enables `strict_sni_host on`. Verify unknown-Host/SNI handling in the
  existing Caddy separately: the setting is server-wide, not a blind site addition.
  Obtain explicit review before changing shared TLS behavior.
- Preserve the Caddyfile inode or explicitly review targeted Caddy recreation;
  a reload may otherwise keep an old bind-mounted file. Include this in rollback.
- Set only the verified owner's private-chat Mini App menu after saving the old
  value. Do not change webhook, polling, other chat menus or bots.

The trusted `jarvis-vkusvill` operations script reads the live baseline under owner sudo;
it does not assume historical networks or drop implicit default networks. Use its
`inspect`, `stage`, `apply`, `verify`, `menu`, `test-auth`, `test-restart`, and `rollback`
commands as documented in the operations runbook. It supports the reviewed single-file
Compose layout only; a different layout stops for review. Do not weaken the checks.

The pilot installer validates every bundle hash and uses the native Hermes scanner
without force. Its wheel-specific runtime is selected by an administrator read-only
`VV_PILOT_MANIFEST`; the public `REVISION` is not rewritten. Repeating setup in this
mode verifies the existing runtime rather than installing the old public release.
Previous skill bytes and baskets are preserved. This is distinct from release-gate
acceptance of a published commit, which remains pending.

## Recovery

See [recovery procedures](../../references/broker-recovery.md). `/health` is local
liveness; `/ready` also decrypts local identity/account. Both are internal-only.
No OAuth connection is a normal state, not a reason to restart the container.
Provider outages do not make local readiness fail.
