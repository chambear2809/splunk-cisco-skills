# Contributing

Thanks for helping improve the Splunk Cisco skills library. This repo contains
agent instructions and shell automation that can touch production Splunk
deployments, so changes need to be reviewable, tested, and conservative.

This project follows the public
[Agent Skills specification](https://agentskills.io/specification), including
the creator guidance for
[best practices](https://agentskills.io/skill-creation/best-practices) and
[evaluating skills](https://agentskills.io/skill-creation/evaluating-skills).
Changes to skills should preserve that contract: concise trigger metadata,
progressive disclosure, script-backed repeatable workflows where appropriate,
and tests or evals that show the skill still behaves as intended.

## Before You Start

- Do not commit credentials, tokens, package binaries, rendered deployment
  output, `template.local`, or local `credentials` files.
- Do not paste secrets into issues, pull requests, comments, tests, fixtures, or
  docs examples.
- For secrets needed during local testing, use:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/example_secret
```

- For multi-line secrets or JSON material, use:

```bash
bash skills/shared/scripts/write_secret_file.sh --editor /tmp/example_secret
```

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt -r requirements-agent.txt
```

`requirements-agent.txt` provides `mcp[cli]` and `PyYAML`, which are required
to run `tests/test_agent_mcp_core.py` and to launch the local MCP agent server
described in the README. Skipping it leaves the dev venv unable to import
`agent.splunk_cisco_skills_mcp`.

Install shell tooling used by CI:

```bash
brew install bats-core shellcheck
```

On Linux, install the equivalent `bats` and `shellcheck` packages for your
distribution.

## Pre-commit (Optional but Recommended)

The repo ships a `.pre-commit-config.yaml` that wires up the lightweight
checks below into git pre-commit hooks. Install once:

```bash
pip install pre-commit
pre-commit install
```

Run against the whole tree at any time:

```bash
pre-commit run --all-files
```

Hooks include trailing-whitespace, JSON/YAML validity, private-key detection,
`bash -n` on every skill script, the Agent Skills frontmatter and
progressive-disclosure contract, the repo-readiness check (operator catalog links,
agent catalog parity, and symlinks), generated deployment and skill-validation
matrix freshness, `ruff`, and `yamllint`. The full
pytest / bats / shellcheck suite is intentionally not in pre-commit: keep
those in CI and in the explicit commands below for fast local feedback.

## Required Checks

Run the focused checks for the area you changed, then run the full suite before
opening a pull request:

```bash
pytest -q
bats tests/*.bats
python3 - <<'PY'
import subprocess
from pathlib import Path
for path in sorted(Path("skills").rglob("*.sh")):
    subprocess.run(["bash", "-n", str(path)], check=True)
PY
shellcheck --severity=warning $(find skills -name '*.sh' -print)
ruff check skills/ tests/ agent/
yamllint -c .yamllint.yml .github/ skills/splunk-itsi-config/templates skills/splunk-itsi-config/agents
python3 skills/shared/scripts/generate_skill_catalog.py --check
python3 skills/shared/scripts/generate_deployment_docs.py --check
python3 skills/shared/scripts/generate_skill_ux_catalog.py --check
python3 skills/shared/scripts/audit_skill_validation.py
python3 skills/shared/scripts/generate_skill_validation_matrix.py --check
python3 skills/shared/scripts/generate_splunk_10_5_compatibility.py --check
if ls splunk-ta/splunk-cisco-app-navigator-*.tar.gz 1>/dev/null 2>&1; then
  python3 skills/cisco-product-setup/scripts/build_catalog.py --check
else
  echo "SCAN package not in tree; skipping catalog freshness check."
fi
python3 tests/check_skill_frontmatter.py
python3 tests/check_repo_readiness.py
```

For MCP changes, also run the focused contract suites:

```bash
pytest -q tests/test_agent_mcp_core.py tests/test_agent_mcp_discovery.py tests/test_agent_mcp_protocol.py
```

If the SCAN package is not present in your local `splunk-ta/` cache, the catalog
freshness check may not be meaningful. In that case, say so in the pull request.

## New Or Changed Skills

When adding a skill under `skills/<skill-name>/`, include:

- `SKILL.md` with Agent Skills YAML frontmatter where `name` matches the
  directory, uses lowercase letters/digits/single hyphens, and the
  `description` is non-empty, <=1024 characters, and includes a clear
  `Use when` trigger
- Concise `SKILL.md` body content: keep the main file under 500 lines and move
  detailed reference material to `reference.md` or `references/`
- `agents/openai.yaml` using the canonical `interface` mapping with a
  25–64-character `short_description` and a concise `default_prompt` that
  explicitly invokes `$<skill-name>`
- `scripts/setup.sh` and/or `scripts/validate.sh` when automation exists
- `reference.md` when product behavior or operational details exceed the short
  skill instructions
- `template.example` for workflows that require product owners to provide
  non-secret configuration values
- tests for argument parsing, dry runs, credential handling, and any shared
  helper behavior

Add the skill identity exactly once to `skills/catalog.yaml`. Supply its stable
path, target, purpose, command summary, primary product and capability, and
lifecycle status there. For a deprecated compatibility alias, also set
`replaced_by` and a concise `migration` boundary; the replacement must be
canonical and share the alias's product and capability. State which legacy
behaviors map to the replacement and which are intentionally unsupported.

Maintain only the richer validated extensions that apply:

- add the skill's tool/access contract to `SKILL_REQUIREMENTS.md`
- add package and deployment-topology data to
  `skills/shared/app_registry.json`
- add sanitized integration or live evidence under `evidence` in
  `skills/shared/skill_validation_registry.json` only when a target, ISO date,
  and reviewable evidence file or URL are available
- update `README.md` only when the operator entry flow, routing table, or
  repo-level documentation links change

Then regenerate in dependency order:

```bash
python3 skills/shared/scripts/generate_skill_catalog.py --write
python3 skills/shared/scripts/generate_skill_ux_catalog.py --write
python3 skills/shared/scripts/generate_skill_validation_matrix.py --write
python3 skills/shared/scripts/generate_splunk_10_5_compatibility.py --write
python3 skills/shared/scripts/generate_deployment_docs.py --write
```

Do not hand-edit the generated catalog sections in `AGENTS.md` or `CLAUDE.md`,
the flat validation skill list, `skill_product_registry.json`, Claude command
files, Cursor skill links, or generated matrix/catalog documents. Run the
corresponding `--check` commands after regeneration.

## Shell Script Rules

- Start scripts with `#!/usr/bin/env bash` and `set -euo pipefail`.
- Source shared helpers through `skills/shared/lib/credential_helpers.sh`.
- Prefer `require_arg`, `reject_secret_arg`, `read_secret_file`,
  `splunk_curl`, `splunk_curl_post`, and the platform helpers already in
  `skills/shared/lib/`.
- Never accept direct secret values through command-line flags. Use
  `--password-file`, `--api-key-file`, `--client-secret-file`, `--token-file`,
  or `--secret-file FIELD PATH`.
- Keep destructive operations explicit, logged, and covered by tests.

## Pull Request Expectations

Every pull request should include:

- A short description of the workflow or bug being changed
- Test commands run locally, or a clear explanation for anything skipped
- Screenshots or sanitized command output only when it adds value
- Notes about live Splunk, ACS, EKS, EC2, or other external resources touched
- Confirmation that no secrets or local rendered artifacts were committed
