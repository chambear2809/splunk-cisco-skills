# Splunk and Cisco Skills

Production-oriented agent skills and shell automation for Splunk Platform,
Splunk Cloud, Splunk Observability Cloud, Cisco integrations, AppDynamics,
ThousandEyes, Galileo, external collectors, and adjacent operational workflows.

This repo is built for two use cases:

- Agent-driven work in Cursor, Codex, or Claude Code, where the agent reads the
  relevant `SKILL.md`, gathers non-secret inputs, renders a plan, applies only
  the requested change, and validates the result.
- Direct shell use, where an operator runs the same skill scripts from the repo
  root and reviews dry-run, render, preflight, apply, and validation output.

Most workflows are render-first and validation-heavy. Mutating phases are
explicit, secrets stay in local files, and generated plans or manifests are
review artifacts rather than source files.

## Start Here

Run commands from the repository root.

1. Configure local credentials:

   ```bash
   bash skills/shared/scripts/setup_credentials.sh
   ```

   The generated `credentials` file is gitignored. Put passwords, API tokens,
   API keys, and client secrets in `credentials` or separate secret files, not
   in chat and not directly in command-line arguments.

2. Find the right skill:

   ```bash
   rg "Duo|ACI|HEC|OTel|Enterprise Security|Data Manager" \
     SKILL_UX_CATALOG.md skills/*/SKILL.md
   ```

   The main chooser is [`SKILL_UX_CATALOG.md`](SKILL_UX_CATALOG.md). It lists
   every skill, its purpose, the first file to open, a safe `--help` command,
   validation, and deeper docs.

3. Open the skill entry point:

   ```bash
   sed -n '1,180p' skills/<skill-name>/SKILL.md
   ```

4. Inspect the safe first command before changing anything:

   ```bash
   bash skills/<skill-name>/scripts/setup.sh --help
   ```

   Some skills use a different entry point. Use the exact safe first command in
   [`SKILL_UX_CATALOG.md`](SKILL_UX_CATALOG.md) when it differs.

5. Prefer dry-run, render, doctor, or preflight before apply:

   ```bash
   bash skills/cisco-product-setup/scripts/setup.sh \
     --product "Cisco ACI" \
     --dry-run
   ```

6. Validate after setup:

   ```bash
   bash skills/<skill-name>/scripts/validate.sh
   ```

   The catalog shows the validation command when a skill uses a Python
   validator, status command, or documented manual validation path instead.

## Choose A Workflow

| Goal | Start with | First useful command |
|------|------------|----------------------|
| I know a Cisco product but not the Splunk app or TA | [`cisco-product-setup`](skills/cisco-product-setup/) | `bash skills/cisco-product-setup/scripts/setup.sh --product "Cisco ACI" --dry-run` |
| I already know the Splunkbase app or local package | [`splunk-app-install`](skills/splunk-app-install/) | `bash skills/splunk-app-install/scripts/install_app.sh --help` |
| I need Enterprise Security, SOAR, ARI, Attack Analyzer, UBA, or security routing | [`splunk-security-portfolio-setup`](skills/splunk-security-portfolio-setup/) | `bash skills/splunk-security-portfolio-setup/scripts/setup.sh --help` |
| I need Splunk Cloud app installs, indexes, restarts, or allowlists | [`splunk-app-install`](skills/splunk-app-install/), [`splunk-hec-service-setup`](skills/splunk-hec-service-setup/), [`splunk-cloud-acs-allowlist-setup`](skills/splunk-cloud-acs-allowlist-setup/) | `bash skills/splunk-cloud-acs-allowlist-setup/scripts/setup.sh --help` |
| I need Splunk Enterprise hosts, forwarders, clusters, or deployment server work | [`splunk-enterprise-host-setup`](skills/splunk-enterprise-host-setup/), [`splunk-universal-forwarder-setup`](skills/splunk-universal-forwarder-setup/), [`splunk-indexer-cluster-setup`](skills/splunk-indexer-cluster-setup/), [`splunk-search-head-cluster-setup`](skills/splunk-search-head-cluster-setup/) | `rg "host|forwarder|indexer|search head|deployment server" SKILL_UX_CATALOG.md` |
| I need Splunk Enterprise on Kubernetes | [`splunk-enterprise-kubernetes-setup`](skills/splunk-enterprise-kubernetes-setup/) | `bash skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh --help` |
| I need SC4S, SC4SNMP, Stream, OTLP, Edge Processor, or external collection | [`splunk-connect-for-syslog-setup`](skills/splunk-connect-for-syslog-setup/), [`splunk-connect-for-snmp-setup`](skills/splunk-connect-for-snmp-setup/), [`splunk-connect-for-otlp-setup`](skills/splunk-connect-for-otlp-setup/), [`splunk-edge-processor-setup`](skills/splunk-edge-processor-setup/) | `rg "SC4S|SC4SNMP|Stream|OTLP|Edge Processor" SKILL_UX_CATALOG.md` |
| I need Splunk Observability Cloud, OTel, APM, RUM, DBMon, AWS, Azure, or GCP | Search the `splunk-observability-*` skills | `rg "Observability|OTel|AWS|Azure|GCP|RUM|DBMon" SKILL_UX_CATALOG.md` |
| I need Splunk Platform paired with Splunk Observability Cloud | [`splunk-observability-cloud-integration-setup`](skills/splunk-observability-cloud-integration-setup/) | `bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh --help` |
| I need AppDynamics product coverage | [`splunk-appdynamics-setup`](skills/splunk-appdynamics-setup/) | `bash skills/splunk-appdynamics-setup/scripts/setup.sh --help` |
| I need Galileo or Agent Control wired to Splunk | [`galileo-platform-setup`](skills/galileo-platform-setup/) or [`galileo-agent-control-setup`](skills/galileo-agent-control-setup/) | `bash skills/galileo-platform-setup/scripts/setup.sh --help` |
| I need a broad admin health check | [`splunk-admin-doctor`](skills/splunk-admin-doctor/) | `bash skills/splunk-admin-doctor/scripts/setup.sh --help` |

For the exhaustive operator catalog, use
[`SKILL_UX_CATALOG.md`](SKILL_UX_CATALOG.md). For local tooling and live-access
requirements by skill, use [`SKILL_REQUIREMENTS.md`](SKILL_REQUIREMENTS.md).

## How The Repo Operates

The normal path is:

1. Choose the skill.
2. Collect non-secret inputs from `template.example` when the skill has one.
3. Keep secrets in `credentials` or chmod-600 secret files.
4. Run `--help`, dry-run, render, doctor, or preflight.
5. Review generated artifacts.
6. Apply only when the plan and target are correct.
7. Validate the deployment.

Agents should ask only for non-secret values in conversation, such as hostnames,
IP addresses, account names, organization IDs, index names, regions, and
feature choices. Secrets should come from `credentials` or flags such as
`--password-file`, `--api-token-file`, `--secret-file`, or equivalent
skill-specific options.

Generated plans, manifests, package caches, live-validation checkpoints, and
local intake files are intentionally gitignored under paths such as
`splunk-*-rendered/`, `sc4s-rendered/`, `sc4snmp-rendered/`, `splunk-ta/`, and
`template.local`.

## Credentials And Targets

All scripts load deployment settings from a project-root `credentials` file
first, fall back to `~/.splunk/credentials`, and honor
`SPLUNK_CREDENTIALS_FILE` when you need an alternate file.

For a single target, run the setup helper:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

For multiple targets, define profile-prefixed keys and select one with
`SPLUNK_PROFILE`:

```bash
SPLUNK_PROFILE="cloud"

PROFILE_cloud__SPLUNK_PLATFORM="cloud"
PROFILE_cloud__SPLUNK_TARGET_ROLE="search-tier"
PROFILE_cloud__SPLUNK_SEARCH_API_URI="https://my-stack.stg.splunkcloud.com:8089"
PROFILE_cloud__SPLUNK_CLOUD_STACK="my-stack"
PROFILE_cloud__ACS_SERVER="https://staging.admin.splunk.com"

PROFILE_hf__SPLUNK_PLATFORM="enterprise"
PROFILE_hf__SPLUNK_TARGET_ROLE="heavy-forwarder"
PROFILE_hf__SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
```

If one workflow needs a primary Cloud target plus a paired heavy forwarder or
search tier, keep `SPLUNK_PROFILE` on the primary target and set
`SPLUNK_SEARCH_PROFILE` for the paired REST target:

```bash
SPLUNK_PROFILE="cloud"
SPLUNK_SEARCH_PROFILE="hf"
SPLUNK_TARGET_ROLE="search-tier"
SPLUNK_SEARCH_TARGET_ROLE="heavy-forwarder"
```

For Splunk Cloud, set search-tier REST only when the workflow needs app-specific
configuration or validation:

```bash
SPLUNK_SEARCH_API_URI="https://your-stack.splunkcloud.com:8089"
SPLUNK_CLOUD_STACK="your-stack-name"
ACS_SERVER="https://admin.splunk.com"
```

For Splunk Observability Cloud, keep the token value in a separate file:

```bash
SPLUNK_O11Y_REALM="us0"
SPLUNK_O11Y_TOKEN_FILE="/tmp/splunk_o11y_api_token"
```

Create secret files without putting secret values in shell history:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_o11y_api_token
```

## Splunk Cloud And Enterprise

The automation separates platform target from deployment role:

- Splunk Enterprise uses direct management REST on port `8089`; remote local
  package installs stage local packages over SSH before installing the
  server-local path.
- Splunk Cloud uses ACS for app installs, app uninstalls, index creation, and
  restarts.
- Splunk Cloud search-tier REST is used for TA-specific account setup, input
  enablement, macros, saved searches, KV Store access, and validation after the
  search API allowlist permits the source IP.
- External collectors, forwarders, OTel collectors, Edge Processor instances,
  Stream forwarders, SC4S, and SC4SNMP run on customer-managed infrastructure,
  even when their destination is Splunk Cloud.

Use [`DEPLOYMENT_ROLE_MATRIX.md`](DEPLOYMENT_ROLE_MATRIX.md) to decide where a
package or workflow belongs. Use
[`CLOUD_DEPLOYMENT_MATRIX.md`](CLOUD_DEPLOYMENT_MATRIX.md) for Cloud-specific
install and configuration behavior.

## Package Policy

`splunk-ta/` is the local package and review cache.

- For public apps, prefer Splunkbase installs. In Splunk Cloud, ACS should fetch
  the compatible Splunkbase release when the app is published there.
- For Enterprise, install from Splunkbase, a URL, or a local `.tgz`, `.tar.gz`,
  `.spl`, `.rpm`, or `.deb` package.
- Use private package uploads only for private or pre-vetted apps that do not
  have a public Splunkbase path.
- Unpacked copies under `splunk-ta/_unpacked/` are review-only artifacts.
- If a package is not Splunk Cloud-compatible as shipped, treat that as a
  package limitation instead of silently repacking it.

## Requirements

Minimum local environment:

- `bash`, `curl`, and `python3`
- `pip install -r requirements-agent.txt` for the local MCP agent server
- Cursor, Codex, or Claude Code for agent-driven use
- Splunk Enterprise REST access on `8089`, or Splunk Cloud ACS plus optional
  search-tier REST access on `8089`, for live app and TA workflows
- a `splunk.com` account for Splunkbase downloads when installing public apps

Common workflow-specific tools include `acs`, `kubectl`, `helm`, `yq`, Docker
or Podman, Terraform, `aws`, `az`, `gcloud`, `node`, `mcp-remote`, and
`splunk-rum`. See [`SKILL_REQUIREMENTS.md`](SKILL_REQUIREMENTS.md) for the
per-skill matrix.

For Splunk Cloud workflows, install the ACS CLI:

```bash
brew install acs
```

For development and CI:

```bash
pip install -r requirements-dev.txt -r requirements-agent.txt
pre-commit run --all-files
```

## Local MCP Agent Server

The repo includes a local MCP server named `splunk-cisco-skills`. It exposes
skill discovery, skill instructions, templates, Cisco product resolution,
dry-run planning, and gated script execution to MCP-capable clients.

Set up its Python environment:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-agent.txt
```

Claude Code and Cursor use the committed `.mcp.json` and `.cursor/mcp.json`.
Codex stores MCP servers in user config, so register this repo once:

```bash
bash agent/register-codex-splunk-cisco-skills-mcp.sh
```

Read-only plans can run after explicit client confirmation. Mutating setup,
install, or configure scripts require the MCP server to start with:

```bash
SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1 python3 agent/run-splunk-cisco-skills-mcp.py
```

Execution still requires a previously generated plan hash and explicit
confirmation from the client.

## Repository Map

```text
README.md                         # operator-facing entry point
SKILL_UX_CATALOG.md                # generated skill chooser and safe commands
SKILL_REQUIREMENTS.md              # generated local-tool and live-access matrix
DEPLOYMENT_ROLE_MATRIX.md          # where apps and workflows belong
CLOUD_DEPLOYMENT_MATRIX.md         # Splunk Cloud install/config behavior
ARCHITECTURE.md                    # internal design and helper boundaries
credentials.example                # documented credential keys and profiles
agent/                             # repo-local MCP server
skills/<skill>/SKILL.md            # skill trigger, instructions, and workflow
skills/<skill>/reference.md        # longer skill-specific reference when present
skills/<skill>/template.example    # non-secret intake worksheet when present
skills/<skill>/scripts/            # shell and Python automation
skills/shared/                     # shared registry, helpers, and generators
splunk-ta/                         # local package cache; binaries ignored
tests/                             # Python and Bats regression coverage
rules/credential-handling.mdc      # secret-handling rule
```

## What To Read Next

| Question | Read |
|----------|------|
| Which skill should I use first? | [`SKILL_UX_CATALOG.md`](SKILL_UX_CATALOG.md) |
| What tools and access does a skill need? | [`SKILL_REQUIREMENTS.md`](SKILL_REQUIREMENTS.md) |
| Where should this app or workflow run? | [`DEPLOYMENT_ROLE_MATRIX.md`](DEPLOYMENT_ROLE_MATRIX.md) |
| How does Splunk Cloud differ from Enterprise? | [`CLOUD_DEPLOYMENT_MATRIX.md`](CLOUD_DEPLOYMENT_MATRIX.md) |
| How is the repo organized internally? | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| How do I demo the workflows? | [`DEMO_SCRIPTS.md`](DEMO_SCRIPTS.md) |
| How do I contribute safely? | [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`SECURITY.md`](SECURITY.md) |

For a specific skill, read:

1. `skills/<skill>/SKILL.md`
2. `skills/<skill>/reference.md` when present
3. `skills/<skill>/scripts/*`

## Scope

This repo focuses on repeatable skills for Splunk apps and TAs, Splunk
administration, customer-managed collectors, Observability Cloud integrations,
Cisco product onboarding, AppDynamics, ThousandEyes, and Galileo workflows.

It does not try to replace vendor-managed control planes or UI-only product
surfaces. When a workflow cannot safely apply a change through supported REST,
shell, IaC, or generated assets, the skill renders a reviewed operator handoff
instead.

## Agent Skills Compliance

This repository follows the public
[Agent Skills specification](https://agentskills.io/specification), including
the published guidance for
[best practices](https://agentskills.io/skill-creation/best-practices) and
[evaluating skills](https://agentskills.io/skill-creation/evaluating-skills).

Compliance is enforced through `tests/check_skill_frontmatter.py` for the
`SKILL.md` contract and `tests/check_repo_readiness.py` for catalog links,
agent command links, local artifact guardrails, and this specification callout.

Before opening a pull request, read [`CONTRIBUTING.md`](CONTRIBUTING.md), run
the documented checks, and report security issues through the process in
[`SECURITY.md`](SECURITY.md), not public issues.
