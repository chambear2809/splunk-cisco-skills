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

## Pre-commit

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

CI enforces this same all-files command, so run it locally before pushing.

Hooks include trailing-whitespace, all-tracked JSON/YAML validity, private-key
and pinned Gitleaks detection, `bash -n` on every first-party shell script, the Agent Skills frontmatter and
progressive-disclosure contract, the repo-readiness check (operator catalog links,
agent catalog parity, and symlinks), generated deployment and skill-validation
matrix freshness, `ruff`, and `yamllint`. The full
pytest / bats / shellcheck suite is intentionally not in pre-commit: keep
those in CI and in the explicit commands below for fast local feedback.

## Required Checks

Run the focused checks for the area you changed, then run the full suite before
opening a pull request:

```bash
pre-commit run --all-files
pytest -q
bats tests/*.bats
python3 - <<'PY'
import subprocess
from pathlib import Path
for root in ("agent", "skills", "scripts"):
    for path in sorted(Path(root).rglob("*.sh")):
        subprocess.run(["bash", "-n", str(path)], check=True)
PY
shellcheck --severity=warning $(find agent skills scripts -name '*.sh' -print)
if ls splunk-ta/splunk-cisco-app-navigator-*.tar.gz 1>/dev/null 2>&1; then
  python3 skills/cisco-product-setup/scripts/build_catalog.py --check
else
  echo "SCAN package not in tree; skipping catalog freshness check."
fi
```

The all-files pre-commit run above covers Python linting, tracked JSON/YAML
validation, skill metadata and repository-readiness checks, generated catalog
and matrix freshness, and the private-key and Gitleaks hooks. CI additionally
audits both Python requirement sets, checks complete Git history for secrets,
and runs the compatibility and cross-reference validators.

CI also installs Gitleaks 8.30.1 from its checksum-verified official release
archive and runs `scripts/run_secret_scan.py` against both the tracked tree and
the complete Git history. The reviewed baseline stores only commit-bound
fingerprints and hashes of exact false-positive lines. Never add matched secret
text to `.gitleaksignore` or `.gitleaks-baseline.json`; a changed line must be
removed from the baseline or explicitly re-reviewed.

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

Verify the generated surfaces in the same dependency order:

```bash
python3 skills/shared/scripts/generate_skill_catalog.py --check
python3 skills/shared/scripts/generate_skill_ux_catalog.py --check
python3 skills/shared/scripts/generate_skill_validation_matrix.py --check
python3 skills/shared/scripts/generate_splunk_10_5_compatibility.py --check
python3 skills/shared/scripts/generate_deployment_docs.py --check
```

Do not hand-edit the generated catalog sections in `AGENTS.md` or `CLAUDE.md`,
the flat validation skill list, `skill_product_registry.json`, Claude command
files, Cursor skill links, or generated matrix/catalog documents. Run the
corresponding `--check` commands after regeneration.

## Verifying Documentation URLs

Splunk's documentation CDNs fingerprint the HTTP client below the User-Agent, so
a naive probe reports a live page as dead and invites a needless "fix" that
points operators at the wrong topic. Verify with `curl`:

- `urllib`, `requests`, and other Python HTTP clients always receive `403` from
  `help.splunk.com` regardless of the User-Agent they send. `curl` receives
  `200` for the same URL. Shell out rather than trusting an in-process client.
- Do not send an explicit `Accept` header. `Accept: text/html,...` re-triggers
  the `403`; curl's default `*/*` succeeds.
- `docs.splunk.com` returns `403` to every automated client, so a URL on that
  host cannot be verified directly. Resolve its migrated `help.splunk.com`
  location through the legacy-ID redirector instead:
  `https://help.splunk.com/en/?resourceId=<Product>_<Manual>_<Topic>`, built
  from the old path (`/Documentation/Splunk/9.4.2/Admin/CustomCertsKVstore`
  becomes `Splunk_Admin_CustomCertsKVstore`).
A `200` alone proves nothing. Also confirm the effective URL still matches what
you wrote, and that the page title and body cover the claim being cited. A
live-but-wrong replacement passes every automated check.

### Sitemap membership

`https://help.splunk.com/sitemap.xml` is an index of 17 per-product sitemaps
listing roughly 183,000 real page URLs. Membership in that list is a stronger
signal than a `200`, because it distinguishes a real page from a section root
that merely redirects to its first child. Build the flat list once per sweep:

```bash
curl -sS https://help.splunk.com/sitemap.xml \
  | grep -o 'https://[^< ]*\.xml' | sort -u > /tmp/sitemaps.txt
while read -r s; do curl -sS "$s"; done < /tmp/sitemaps.txt \
  | grep -o '<loc>[^<]*</loc>' | sed -E 's|</?loc>||g' | sort -u > /tmp/allurls.txt
```

Use `sed -E`; BSD `sed` on macOS does not accept `\?` in a basic regex and will
silently leave the `<loc>` tags in place, which makes every exact-match test
fail. Then membership is an exact-match test:

```bash
grep -qxF "$url" /tmp/allurls.txt && echo "exact page" || echo "not a page"
```

A URL that returns `200` but is absent from the list is a section root. It
resolves to whichever child topic currently sorts first, so it can silently
start pointing somewhere else when the vendor reorders the section. Prefer an
exact sitemap entry. If the citing text really does refer to a whole section,
look for an `…-overview` child before settling for the root — Splunk publishes
overview pages for most sections, and those are exact sitemap entries.

The sitemap also lists every documented version of a page, so it is the fastest
way to confirm that a version-pinned citation exists at the version you pinned.

Sitemap membership is deliberately **not** wired into the automated checker
below. It only covers `help.splunk.com`, it answers a citation-quality question
rather than a lifecycle-drift question, and it costs a multi-megabyte crawl per
run. It is a manual-sweep tool.

### Automated check

Two complementary URL audits run weekly from
`.github/workflows/catalog-drift.yml`:

```bash
python3 skills/shared/scripts/audit_documentation_urls.py
python3 skills/shared/scripts/audit_lifecycle_qualifier_urls.py
```

`audit_documentation_urls.py` checks recognized public documentation and
reference hosts across the tracked repository for terminal broken links while
classifying authentication, WAF, server, and transport failures as
unverifiable. `audit_lifecycle_qualifier_urls.py` performs the narrower content
audit that catches vendor lifecycle changes behind `preview`/`beta`/`alpha`
URLs. Both extract URLs per line, so a URL split across adjacent string
literals is only partially seen; keep such URLs reconstructable or write them
on one line.

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
