# Splunk TA Skills — Claude Code Context

This repository is a working library of Cursor, Codex, and Claude Code agent skills plus
shell scripts for installing, configuring, and validating Splunk apps and Technology
Add-ons on Splunk Cloud and self-managed Splunk Enterprise deployments, and for
bootstrapping Linux Splunk Enterprise hosts.

## How To Use This Repo With Claude Code

When the user asks about a Cisco product or Splunk app/workflow, find the matching
skill in the table below and read `skills/<skill-name>/SKILL.md` for complete
instructions. If more detail is needed, also read `skills/<skill-name>/reference.md`.

The user can also invoke skills directly as slash commands (e.g. `/cisco-catalyst-ta-setup`).

## Skill Catalog

| Skill | Target | Main purpose |
|-------|--------|--------------|
| `cisco-product-setup` | Cisco product catalog workflow | Resolve a Cisco product name from SCAN, classify gaps, and delegate install/configure/validate to the matching Cisco setup skill |
| `cisco-scan-setup` | `splunk-cisco-app-navigator` | Install and validate the Splunk Cisco App Navigator (SCAN) catalog app; trigger catalog sync from S3 |
| `cisco-catalyst-ta-setup` | `TA_cisco_catalyst` | Configure Catalyst Center, ISE, SD-WAN, and Cyber Vision inputs |
| `cisco-catalyst-enhanced-netflow-setup` | `splunk_app_stream_ipfix_cisco_hsl` | Install and validate optional Enhanced Netflow mappings for extra dashboards |
| `cisco-appdynamics-setup` | `Splunk_TA_AppDynamics` | Configure AppDynamics controller and analytics connections, inputs, and dashboards |
| `cisco-security-cloud-setup` | `CiscoSecurityCloud` | Install and configure product-specific Cisco Security Cloud inputs with dashboard-ready defaults |
| `cisco-secure-access-setup` | `cisco-cloud-security` | Install and configure Secure Access org accounts, app settings, and dashboard prerequisites |
| `cisco-spaces-setup` | `ta_cisco_spaces` | Configure Cisco Spaces meta stream accounts, firehose inputs, and activation tokens |
| `cisco-dc-networking-setup` | `cisco_dc_networking_app_for_splunk` | Configure ACI, Nexus Dashboard, and Nexus 9K data collection |
| `cisco-intersight-setup` | `Splunk_TA_Cisco_Intersight` | Configure Cisco Intersight account, index, and inputs |
| `cisco-meraki-ta-setup` | `Splunk_TA_cisco_meraki` | Configure Meraki organization account, index, and polling inputs |
| `cisco-enterprise-networking-setup` | `cisco-catalyst-app` | Configure the visualization app's macros and related app settings |
| `cisco-thousandeyes-setup` | `ta_cisco_thousandeyes` | Configure ThousandEyes OAuth, HEC, streaming/polling inputs, and dashboards |
| `splunk-itsi-setup` | `SA-ITOA` | Install and validate Splunk ITSI; integration readiness for ThousandEyes |
| `splunk-itsi-config` | Native ITSI objects, service trees, and supported ITSI content packs | Preview, apply, and validate ITSI entities, services, KPIs, dependencies, template links, service trees, NEAPs, and selected content packs from YAML specs |
| `splunk-enterprise-security-install` | `SplunkEnterpriseSecuritySuite` | Install, post-install, and validate Splunk Enterprise Security on standalone search heads or SHC deployers |
| `splunk-enterprise-security-config` | Splunk Enterprise Security configuration | Configure ES indexes, roles, data models, enrichment, detections, and operational validation |
| `splunk-ai-assistant-setup` | `Splunk_AI_Assistant_Cloud` | Install and configure Splunk AI Assistant for SPL; drive Enterprise cloud-connected onboarding |
| `splunk-mcp-server-setup` | `Splunk_MCP_Server` | Install and configure Splunk MCP Server settings, tokens, and shared Cursor/Codex/Claude Code bridge bundles |
| `splunk-app-install` | Any app or TA | Install, list, or uninstall Splunk apps |
| `splunk-agent-management-setup` | Splunk Agent Management | Render, apply, and validate server classes, deployment apps, and deployment client assets |
| `splunk-workload-management-setup` | Splunk Workload Management | Render and validate workload pools, workload rules, admission-rule guardrails, and Linux workload prerequisites |
| `splunk-hec-service-setup` | Splunk HTTP Event Collector | Prepare reusable HEC token configuration, allowed indexes, Enterprise inputs.conf assets, and Splunk Cloud ACS payloads |
| `splunk-federated-search-setup` | Splunk Federated Search | Render and validate self-managed Splunk-to-Splunk standard or transparent providers, standard-mode federated indexes, and SHC replication assets |
| `splunk-index-lifecycle-smartstore-setup` | Splunk Index Lifecycle / SmartStore | Render and validate SmartStore `indexes.conf`, `server.conf`, and `limits.conf` assets for indexers or cluster managers |
| `splunk-monitoring-console-setup` | Splunk Monitoring Console | Render and validate self-managed distributed or standalone Monitoring Console assets, including auto-config, peer/group review, forwarder monitoring, and platform alerts |
| `splunk-enterprise-host-setup` | Splunk Enterprise runtime | Bootstrap Linux Splunk Enterprise hosts as search-tier, indexer, heavy-forwarder, cluster-manager, indexer-peer, SHC deployer, or SHC member |
| `splunk-enterprise-kubernetes-setup` | Splunk Enterprise on Kubernetes | Render, preflight, apply, and validate SOK S1/C3/M4 or Splunk POD on Cisco UCS |
| `splunk-observability-otel-collector-setup` | Splunk Observability Cloud OTel Collector | Render, apply, and validate Splunk Distribution of OpenTelemetry Collector assets for Kubernetes clusters and Linux hosts, including Splunk Platform HEC token handoff helpers |
| `splunk-observability-dashboard-builder` | Splunk Observability Cloud dashboards | Render, validate, and optionally apply classic Observability dashboard groups, charts, and dashboards from natural-language, JSON, or YAML specs |
| `splunk-stream-setup` | Splunk Stream stack | Install and configure Splunk Stream components |
| `splunk-connect-for-syslog-setup` | SC4S external collector | Prepare Splunk HEC/indexes and render or apply Docker, Podman, systemd, or Helm assets for Splunk Connect for Syslog |
| `splunk-connect-for-snmp-setup` | SC4SNMP external collector | Prepare Splunk HEC/indexes and render or apply Docker Compose or Helm assets for Splunk Connect for SNMP |

## Splunk MCP Server

If `.mcp.json` exists at the project root, the Splunk MCP server is available as the
`splunk-mcp` tool through the tracked `splunk-mcp-rendered/run-splunk-mcp.js`
bridge. The local token file (`splunk-mcp-rendered/.env.splunk-mcp`) only exists
after running the `splunk-mcp-server-setup` skill. Use MCP search tools for live
Splunk queries when available.

## Local Skill MCP Server

The project also exposes a local `splunk-cisco-skills` MCP server through
`agent/run-splunk-cisco-skills-mcp.py`. Install its Python dependencies with:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-agent.txt
```

If an internal pip index does not mirror the MCP SDK, install from public PyPI
explicitly:

```bash
pip install --index-url https://pypi.org/simple -r requirements-agent.txt
```

The launcher automatically prefers `.venv/bin/python` when the repo-local venv
exists, so Claude Code and Cursor do not need to inherit an activated shell.
Claude Code reads `.mcp.json`; Cursor reads `.cursor/mcp.json`; Codex needs a
one-time registration with `bash agent/register-codex-splunk-cisco-skills-mcp.sh`.

This server provides read-only skill catalog, template, product-resolution, and
planning tools by default. Read-only plans can run with explicit confirmation.
Mutating setup, install, or configure scripts are disabled unless the MCP server
process is started with `SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1`; all execution tools
require a matching plan hash and explicit confirmation.

Plans are single-use and stored in memory for the MCP server session: a plan
is consumed when it executes, and the entire plan store is lost if the server
restarts. If a plan hash is rejected as unknown, re-run the plan step to get a
fresh hash. `SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1` is a server-wide toggle — it
enables mutating execution for all clients connected to that server process.

## Credentials

All scripts load deployment settings from a project-root `credentials` file first,
fall back to `~/.splunk/credentials`, and honor `SPLUNK_CREDENTIALS_FILE` for alternate
files. Run `bash skills/shared/scripts/setup_credentials.sh` to create the file
interactively, or copy and edit `credentials.example`.

Splunk Observability Cloud skills read `SPLUNK_O11Y_REALM` and
`SPLUNK_O11Y_TOKEN_FILE` from the same credentials file. Store only the realm
and token-file path there; keep the Observability API token value in a separate
chmod 600 file.

## Secure Credential Handling Rules

### Agent Rules

1. **NEVER ask** the user for passwords, API keys, tokens, client secrets, or any
   other secret in conversation. This includes Splunk credentials, device passwords,
   Meraki API keys, Intersight client secrets, Splunkbase passwords, and any other
   sensitive value.

2. **NEVER pass** `SPLUNK_USER`, `SPLUNK_PASS`, `SB_USER`, `SB_PASS`, or any secret
   as an environment variable prefix in shell commands. For example, do NOT run:
   `SPLUNK_PASS="secret" bash script.sh`

3. **NEVER pass** secrets as command-line arguments (e.g., `--password mysecret`).
   Use file-based alternatives instead (`--password-file /path/to/file`).

4. **Splunk credentials** are stored in the project-root `credentials` file
   (chmod 600, gitignored) and read automatically by all skill scripts via the
   shared credential helper library at `skills/shared/lib/credential_helpers.sh`.
   The library also falls back to `~/.splunk/credentials` if the project file
   does not exist.

5. If Splunk credentials are not yet configured, guide the user to run:
   ```bash
   bash skills/shared/scripts/setup_credentials.sh
   ```
   Or copy and edit the example:
   ```bash
   cp credentials.example credentials && chmod 600 credentials
   ```

6. **Device credentials** (device passwords, API keys, client secrets) should be
   handled by instructing the user to create a temporary file without putting
   the secret in shell history:
   ```bash
   bash skills/shared/scripts/write_secret_file.sh /tmp/secret_file
   ```
   Then pass the file path to the script (e.g., `--password-file /tmp/secret_file`).
   Instruct the user to delete the file after use.

   Splunk Observability Cloud API tokens follow the same pattern: set
   `SPLUNK_O11Y_TOKEN_FILE` to the local file path, never to the token value.

7. You MAY freely ask for non-secret values: account names, hostnames, IP addresses,
   regions, index names, organization IDs, client IDs, and other configuration values
   that are not credentials.

## Key Reference Files

- `README.md` — full overview, workflow, and platform notes
- `ARCHITECTURE.md` — topology and component placement
- `CLOUD_DEPLOYMENT_MATRIX.md` — Cloud-specific deployment model
- `DEPLOYMENT_ROLE_MATRIX.md` — cross-platform role placement
- `credentials.example` — credentials file template
- `skills/shared/app_registry.json` — Splunkbase IDs and app metadata
