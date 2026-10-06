# Install for Hermes Agent

When the user asks to install this integration from its link, complete both the
skill installation and its isolated CLI setup. The user's installation request
authorizes these steps; ordinary shopping requests do not trigger installation.

Repository: https://github.com/SergeySdv/vkusvill-hermes
Skill: SergeySdv/vkusvill-hermes/skills/vkusvill

## 1. Identify the actual Hermes environment

Run in the terminal backend that will execute this skill, as the Hermes user.
Use its active HERMES_HOME (default ~/.hermes); do not assume the host machine's
home is also the container's home. For a named profile, resolve its real home
before proceeding and pass HERMES_HOME consistently to setup and the launcher.

Need Python 3.11+ with venv/pip, Git, and network access to GitHub and the Python
package index. If missing, use the environment's supported dependency installation
procedure. Do not modify Hermes's own Python environment or use sudo by default.
If the skill store and terminal backend are on different machines, install the
skill through the Hermes host and make its scripts available inside the terminal
backend too. Run setup in that backend; do not claim a host-only install is ready.

## 2. Install the skill through Hermes

Use the native skills hub install tool, or this CLI command when available:

```sh
hermes skills install SergeySdv/vkusvill-hermes/skills/vkusvill
```

Allow the normal scanner and installation policy to run. Do not suppress findings
or use --force to bypass them. If an existing skill conflicts, inspect the
difference and preserve local customizations rather than overwrite blindly.
Install the entire referenced bundle, not only SKILL.md. It includes
references/cli.md, references/workflows.md and scripts/setup.py, scripts/runtime.py,
scripts/vv.py. Older Hermes versions may need the complete directory copied from
a reviewed clone; report if native installation is unavailable.

## 3. Install the CLI in an isolated environment

Using the actual installed skill path reported by Hermes, run:

```sh
python3 "$HERMES_HOME/skills/vkusvill/scripts/setup.py"
python3 "$HERMES_HOME/skills/vkusvill/scripts/vv.py" doctor --live --json
```

The commands assume HERMES_HOME has been set to the active absolute home.
If installed under a category/custom skills directory, use that actual path.

Setup uses stdlib venv + pip, pins the CLI to a full reviewed Git commit, and
keeps it under HERMES_HOME/integrations/vkusvill/. It does not need uv or a global
vv on PATH. Python dependencies follow the package version ranges; uv.lock
remains the reproducible development environment, not a pip requirements file.
VV_RUNTIME_ROOT optionally overrides the managed runtime directory.
An unchanged, successfully installed runtime is reused. State is kept separately
under integrations/vkusvill/state unless VV_STATE_DIR is explicitly set.
Setup does not configure OAuth or consume credentials.

This skill pins CLI 0.3.0, commit `02bee28cd9f5a7fc563da9635ee4d5519873c936`,
which contains all ten adapters. Setup must report the expected revision, and
`vv product barcode --help`, `vv discount search --help`, `vv recipe search --help`,
`vv shop search --help`, `vv orders list --help`, `vv favorite show --help` must exist.

Before publishing the skill, run `make release-check`. This verifies the unchanged
candidate through Hermes's native guard/install APIs and checks actual installed
source files and pip commit provenance, not only help text or a successful doctor.
The test does not download the candidate skill from GitHub; repeat `make e2e-install`
after publication to verify the public installation path as well.

## 4. Verify and report honestly

- Setup must return ok=true; launcher doctor must return ok=true.
- Check that vkusvill is visible through skills_list or hermes skills list.
- Load the installed skill with skill_view. If the current session does not
  refresh discovery, start a new conversation and use /vkusvill.
- Verify cli_version is 0.3.0 and live.public_mcp=ok.
- Explain that public search/details/analogs/cart links work without login.
  Authenticated stock, address-specific prices and delivery costs remain unknown.
- If the user requested a functional test, search for their products, inspect
  details, import a request, run check --refresh and create a link with its hash.
  Do not report an order or payment; this produces a share link only.

## Updating an existing 0.1.0 installation

Refresh the skill bundle through the native Hermes skill manager after reviewing
local edits and scanner results. Ensure scripts/runtime.py matches this repository:
the older bootstrap pins the offline CLI and must not be reused for this release.
Run the new scripts/setup.py: it creates a new revision-specific environment and
preserves the shared basket state. Then run launcher doctor --live and confirm
0.3.0. Old check hashes require a new check --refresh.

A bare link can also mean “read this”; the reliable user request is:
“Установи себе этот скилл вместе с CLI по инструкции INSTALL.md: <repository URL>”.

[Hermes native installation documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/).
