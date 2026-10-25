# Deployable Jarvis pilot (2026-10-18)

This extends the [offline verification](jarvis-auth-verification.md) with an explicit
unpublished wheel installation path. It does not change the public Git pin or make
the published release gate green. Candidate version remains `0.5.0.dev0`.

## Implemented

- `deploy/jarvis/build_bundle.py`: allowlisted source/image/skill assets, dependency
  hashes and checksummed wheel; no credentials or network deployment.
- `deploy/jarvis/install_pilot.py`: native Hermes scan without force, hash-checked
  wheel, separate runtime, prior-skill rollback copy, repeat/tamper protection.
- Launcher `VV_PILOT_MANIFEST`: read-only administrator wheel selection; invalid
  manifest fails closed. Pilot setup cannot silently reinstall the older Git pin.
- `vv-auth-admin prepare --local-image`: explicit local immutable-image pilot only.
- `vv-auth-admin menu --action status|enable|restore`: owner-scoped Telegram menu
  with saved prior value and compare-before-restore. No webhook/poller changes.
- Operations repository: owner-run inspect/seed/stage/apply/verify/menu/test-auth/
  test-restart/rollback, plan hashes, backup receipt, isolation checks, shared-Caddy
  approval, targeted recreation and automatic rollback attempt.

The full runbook is `docs/JARVIS-VKUSVILL-PILOT.md` in
`/Users/sergei/Projects/hermes-server-operations`; it is included as `RUNBOOK.md`
in the prepared code-only package. Start with `inspect`, not `apply`.

## Evidence

Verified 2026-10-17 UTC (2026-10-18 client timezone): 387 CLI/auth/browser tests,
15 operations tests, lint/format/build, real Hermes clean installation and upgrade
from actual 0.4.0, repeat installation, local draft-basket preservation, native scan,
broker smoke, two-owner TLS/network/restart tests. Operations apply/rollback tests
mock Docker operations; the actual server deployment is not yet tested.

The same wheel SHA-256 was used in the actual upgrade test and final package:
`efb4ad991af0819a8bf23a7d86b91665e68564c682c537295a4ac243b2a36bf5`.
Final skill scanner allows the bundle with `safe`; the final extra manifest type guards
are covered by unit tests. No real carts, links, personal discounts or orders created.

SSH read-only access confirmed `hermes-research-01`; sudo requires owner interaction.
No live stacks, DNS, OAuth registrations or Telegram settings were changed. DNS lookups
for `vv-jarvis.buzzersteam.net` returned no addresses. Registered HTTPS callback,
the owner's real consent, backup/restore and server acceptance remain mandatory.

See the operations report `changes/2026-10-18-jarvis-vkusvill-pilot-prepared.md`
for exact artifact hashes, commands, baseline limits and rollback paths.
