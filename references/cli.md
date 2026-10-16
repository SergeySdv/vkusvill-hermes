# CLI reference

The maintained executable contract is [skills/vkusvill/references/cli.md](../skills/vkusvill/references/cli.md).
It travels with the Hermes skill. references/design/ contains the original proposal,
including commands not implemented by this release.

## Development OAuth commands

The published 0.3.0 pin does not include these commands yet.
`vv auth login --client-file PATH [--timeout 300]` requires a private interactive
terminal and a mode-0600 registered-client JSON file. `vv auth status --json`
reports local session state without tokens. `vv auth logout --json` removes local
secrets only. See [OAuth onboarding](oauth-onboarding.md) for remote callbacks and
registration requirements. Shopping commands never initiate login implicitly.
