# Splunk TA Skills — Codex Context

This repository is a working library of Cursor, Codex, and Codex agent skills plus
shell scripts for installing, configuring, and validating Splunk apps and Technology
Add-ons on Splunk Cloud and self-managed Splunk Enterprise deployments, and for
bootstrapping Linux Splunk Enterprise hosts.

## How To Use This Repo With Codex

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
| `splunk-ai-assistant-setup` | `Splunk_AI_Assistant_Cloud` | Install and configure Splunk AI Assistant for SPL; drive Enterprise cloud-connected onboarding |
| `splunk-mcp-server-setup` | `Splunk_MCP_Server` | Install and configure Splunk MCP Server settings, tokens, and shared Cursor/Codex/Codex bridge bundles |
| `splunk-app-install` | Any app or TA | Install, list, or uninstall Splunk apps |
| `splunk-enterprise-host-setup` | Splunk Enterprise runtime | Bootstrap Linux Splunk Enterprise hosts as search-tier, indexer, heavy-forwarder, cluster-manager, indexer-peer, SHC deployer, or SHC member |
| `splunk-stream-setup` | Splunk Stream stack | Install and configure Splunk Stream components |
| `splunk-connect-for-syslog-setup` | SC4S external collector | Prepare Splunk HEC/indexes and render or apply Docker, Podman, systemd, or Helm assets for Splunk Connect for Syslog |
| `splunk-connect-for-snmp-setup` | SC4SNMP external collector | Prepare Splunk HEC/indexes and render or apply Docker Compose or Helm assets for Splunk Connect for SNMP |

## Splunk MCP Server

If `.mcp.json` exists at the project root, the Splunk MCP server is available as the
`splunk-mcp` tool. This path (`splunk-mcp-rendered/run-splunk-mcp.sh`) only exists
after running the `splunk-mcp-server-setup` skill. Use MCP search tools for live
Splunk queries when available.

## Credentials

All scripts load deployment settings from a project-root `credentials` file first,
fall back to `~/.splunk/credentials`, and honor `SPLUNK_CREDENTIALS_FILE` for alternate
files. Run `bash skills/shared/scripts/setup_credentials.sh` to create the file
interactively, or copy and edit `credentials.example`.

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
   handled by instructing the user to create a temporary file:
   ```bash
   echo "the_secret" > /tmp/secret_file && chmod 600 /tmp/secret_file
   ```
   Then pass the file path to the script (e.g., `--password-file /tmp/secret_file`).
   Instruct the user to delete the file after use.

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
