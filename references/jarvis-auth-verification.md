# Jarvis auth candidate: offline verification

Verified: 2026-10-17 16:03–16:06 UTC (2026-10-18 in Asia/Shanghai).
Branch: `feat/telegram-oauth-onboarding`; base HEAD
`0e0d0d09fd9189be84775741e7ca4d11712fb752`; uncommitted candidate `0.5.0.dev0`.
Target for the later pilot: `hermes-research-01`, Jarvis only.
No SSH, production Compose, DNS, Telegram menu, real credentials or live consent
were used. The operations repository was read only. No commit, push or PR created.

## Results

| Check | Actual result |
| --- | --- |
| Public OAuth discovery and SDK `tools/list` | Resource/issuer checked; all 11 current schemas match the repository; no provider tool calls |
| Ruff lint / format and `git diff --check` | PASS; 52 Python files formatted |
| `uv run --locked --group browser pytest` | 377 passed, one existing Starlette TestClient deprecation warning |
| Wheel/sdist and packaged broker/browser assets | PASS |
| Browser OAuth fixture | Chromium → actual loopback HTTPS app → synthetic consent → callback; success and missing-cookie paths pass, clean final URL and no browser storage secrets |
| Broker process smoke | PASS: installed non-root process, read-only filesystem, no network, scoped capability and no export endpoint |
| Two-instance Caddy/Docker gate | PASS: trusted synthetic CA, HTTP→HTTPS, Host/SNI mismatch, encoded bridge paths and methods, distinct networks/credentials, no agent vault/socket mount, restart and recreation preserve context |
| Error/log canaries | PASS: reflected provider tokens suppressed; callback code/state absent from Caddy runtime/container logs on upstream outage |
| Recovery | PASS: real age encryption/decryption, SQLite-consistent snapshot, fresh restore, key-rotation copy, owner/key/file guards, simulated disk failure and bounded lock |
| Concurrent refresh | PASS in independent processes: one exchange, context preserved; uncertain refresh cannot replay after restart |
| Real Hermes container smoke | PASS on final candidate; preinstalled skill/CLI path, no model or paid API used |
| Native Hermes skill scanner | `safe`, installation allowed without force/bypass |
| Published installer release gate | **BLOCKED as intended**: pin installs 0.4.0, checkout is 0.5.0.dev0; `Installed version differs from checkout`, step 3 |

The release gate did not progress to the new candidate's fresh-install/upgrade
acceptance. Its baseline is now published 0.4.0, and file-integrity comparisons
cover Python/JSON plus HTML/JS/CSS. Unit tests for this gate pass; the genuine
immutable-pin gate is not green and was not bypassed or relabelled successful.

## Provenance and reproduction

Broker image ID:
`sha256:c27941b06141ca289f2af82aabba727ae823db400949c688b1968442c940cb88`.
Installed source and browser assets were hash-compared to the final checkout.
This is a local image ID, not a published registry manifest digest.

Docker Hub returned EOF when pulling Caddy locally. The container gate instead
used `vv-caddy-test`: official Caddy 2.11.7 Linux ARM64 release binary, verified
against the release's SHA-512 checksums, packaged locally using
`e2e/Caddy.Dockerfile`. No production proxy was contacted or changed.
CI is configured for `caddy:2.11.7-alpine`; that registry image and Linux CI jobs
have not been independently run in GitHub during this unpushed turn.

Hermes final-candidate image:
`sha256:eed427d1e240d18d40fe7a937478dfd8fca92558ace319cf8e2d0cde5dcb09cd`.
It reuses the freshly built E2E dependency layer with final source/skill copied in;
no skill pin was rewritten for the release check. Smoke deliberately tests a local
preinstalled candidate, not installation from a published GitHub candidate.

Private local test evidence, ignored by Git:

- `.e2e-results/vv-e2e-c13609eb3790/result.json`: final Hermes smoke.
- `.e2e-results/vv-e2e-4652445da3f6/result.json`: blocked release gate.
- `.e2e-results/caddy-build/checksums.txt`: official Caddy checksum reference.

Disposable containers/networks/volumes were removed after tests. Images and ignored
test artifacts remain local. All credentials, signatures, orders and links used
in automated tests are synthetic. No real cart/share-link/discount mutations ran.

```sh
uv sync --locked --extra broker --group browser
uv run --locked --group browser playwright install chromium
uv run --locked --group browser pytest
make lint build test-broker test-protocol
make broker-build broker-smoke broker-browser
make broker-containers
make e2e-smoke
make release-check
```

Install `age`/`age-keygen` for the encrypted-backup integration test. The last command
must remain blocked until a committed, published candidate and its matching installer
pin exist. Do not disable identity checks to make it green.

## Still open before a pilot

1. Authorized sanitized live baseline of Jarvis/Caddy, exact mounts/UID/networks,
   verified owner/bot, hostname/DNS and registered HTTPS callback/client settings.
2. Server-specific apply/verify/rollback scripts in `hermes-server-operations`,
   reviewed against that baseline; fresh verified encrypted infrastructure backup.
   Current `vv-auth-admin prepare` only creates an idempotent local bundle.
3. Separate permission for commit/push, release version, immutable installer pin/image,
   genuine fresh install and 0.4.0 upgrade; check PR/CI and post-merge results.
4. Human real Telegram mobile/desktop and VkusVill consent; external-browser handoff
   is deliberately unsupported, rather than weakening browser-cookie binding.
5. Controlled Jarvis read-only pilot, targeted live restart, actual backup restore,
   VM reboot test and monitoring/retention integration. No production reboot is authorized.

See the [checkpoint plan](jarvis-auth-implementation-plan.md),
[Jarvis artifacts](../deploy/jarvis/README.md) and
[recovery instructions](broker-recovery.md). Passing offline tests is not live rollout acceptance.
