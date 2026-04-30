# Contributing

Thanks for helping improve the Splunk Cisco skills library. This repo contains
agent instructions and shell automation that can touch production Splunk
deployments, so changes need to be reviewable, tested, and conservative.

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
pip install -r requirements-dev.txt
```

Install shell tooling used by CI:

```bash
brew install bats-core shellcheck
```

On Linux, install the equivalent `bats` and `shellcheck` packages for your
distribution.

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
ruff check skills/ tests/
yamllint -c .yamllint.yml .github/workflows/ skills/splunk-itsi-config/templates skills/splunk-itsi-config/agents
python3 skills/shared/scripts/generate_deployment_docs.py --check
if ls splunk-ta/splunk-cisco-app-navigator-*.tar.gz 1>/dev/null 2>&1; then
  python3 skills/cisco-product-setup/scripts/build_catalog.py --check
else
  echo "SCAN package not in tree; skipping catalog freshness check."
fi
python3 tests/check_skill_frontmatter.py
python3 tests/check_repo_readiness.py
```

If the SCAN package is not present in your local `splunk-ta/` cache, the catalog
freshness check may not be meaningful. In that case, say so in the pull request.

## New Or Changed Skills

When adding a skill under `skills/<skill-name>/`, include:

- `SKILL.md` with YAML frontmatter where `name` matches the directory
- `scripts/setup.sh` and/or `scripts/validate.sh` when automation exists
- `reference.md` when product behavior or operational details exceed the short
  skill instructions
- `template.example` for workflows that require product owners to provide
  non-secret configuration values
- tests for argument parsing, dry runs, credential handling, and any shared
  helper behavior

Also update:

- `README.md`, `AGENTS.md`, and `CLAUDE.md` skill catalogs
- `.cursor/skills/<skill-name>` symlink
- `.claude/commands/<skill-name>.md`
- `skills/shared/app_registry.json` when the skill maps to a Splunk app or
  deployment topology
- generated deployment docs when registry placement changes

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
