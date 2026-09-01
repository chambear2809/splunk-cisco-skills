# Splunk Platform and Cisco Skills — Claude Code Context

This repository is a working library of Cursor, Codex, and Claude Code agent
skills, MCP tooling, intake templates, reference docs, and shell automation for
planning, rendering, installing, configuring, validating, and handing off Splunk
Platform, Splunk Cloud, Splunk Observability Cloud, Cisco, and adjacent
operational integrations.

It goes well beyond Technology Add-on setup. The catalog covers Cisco product
onboarding, Splunk apps and TAs, Enterprise Security and the broader Splunk
security portfolio, ITSI, SOAR, On-Call, Observability Cloud integrations,
dashboards, detectors, OpenTelemetry collectors, Kubernetes APM
auto-instrumentation, Browser RUM and Session Replay, AWS and ThousandEyes
integrations, HEC, ACS allowlists, PKI, SmartStore, federated search, workload
management, Monitoring Console, license management, indexer clusters, Edge
Processor, Stream, SC4S, SC4SNMP, Universal Forwarders, Linux Splunk Enterprise
hosts, self-managed Kubernetes runtimes, and external-collector topologies.
Most workflows are render-first and validation-heavy, with explicit apply
phases and secret-file guardrails for production changes.

## How To Use This Repo With Claude Code

When the user asks about a Cisco product or Splunk app/workflow, find the matching
skill in the table below and read `skills/<skill-name>/SKILL.md` for complete
instructions. If more detail is needed, also read `skills/<skill-name>/reference.md`.

The user can also invoke skills directly as slash commands (e.g. `/cisco-catalyst-ta-setup`).

For any Splunk TA, add-on, or dashboard companion workflow, do not treat
package install alone as successful setup. Follow
`skills/shared/ta_completion_gate.md`: configure and validate data ingest, then
verify shipped dashboards are visible, macro-aligned, and returning data, or
record explicit evidence that the package ships no pre-built dashboards.

<!-- BEGIN GENERATED SKILL CATALOG -->
<!-- source: skills/catalog.yaml; schema: 1; sha256: 4bb6aab4661bc8efe961cc511cfa370430bd8bc0f0b51fdad0f3a85a9f4a89ff -->
## Skill Index

The complete 168-entry catalog is maintained in `skills/catalog.yaml`. Read the selected skill's `SKILL.md` on demand.

| Skill | Instructions | Lifecycle |
| --- | --- | --- |
| `cisco-product-setup` | `skills/cisco-product-setup/SKILL.md` | Canonical |
| `cisco-collaboration-setup` | `skills/cisco-collaboration-setup/SKILL.md` | Canonical |
| `cisco-cloud-control-setup` | `skills/cisco-cloud-control-setup/SKILL.md` | Canonical |
| `cisco-data-fabric-setup` | `skills/cisco-data-fabric-setup/SKILL.md` | Canonical |
| `cisco-scan-setup` | `skills/cisco-scan-setup/SKILL.md` | Canonical |
| `cisco-catalyst-ta-setup` | `skills/cisco-catalyst-ta-setup/SKILL.md` | Canonical |
| `cisco-catalyst-enhanced-netflow-setup` | `skills/cisco-catalyst-enhanced-netflow-setup/SKILL.md` | Canonical |
| `cisco-appdynamics-setup` | `skills/cisco-appdynamics-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-setup` | `skills/splunk-appdynamics-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-platform-setup` | `skills/splunk-appdynamics-platform-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-controller-admin-setup` | `skills/splunk-appdynamics-controller-admin-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-agent-management-setup` | `skills/splunk-appdynamics-agent-management-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-dual-agent-setup` | `skills/splunk-appdynamics-dual-agent-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-apm-setup` | `skills/splunk-appdynamics-apm-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-k8s-cluster-agent-setup` | `skills/splunk-appdynamics-k8s-cluster-agent-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-infrastructure-visibility-setup` | `skills/splunk-appdynamics-infrastructure-visibility-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-machine-agent-otel-collector-setup` | `skills/splunk-appdynamics-machine-agent-otel-collector-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-database-visibility-setup` | `skills/splunk-appdynamics-database-visibility-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-analytics-setup` | `skills/splunk-appdynamics-analytics-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-eum-setup` | `skills/splunk-appdynamics-eum-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-synthetic-monitoring-setup` | `skills/splunk-appdynamics-synthetic-monitoring-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-log-observer-connect-setup` | `skills/splunk-appdynamics-log-observer-connect-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-alerting-content-setup` | `skills/splunk-appdynamics-alerting-content-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-dashboards-reports-setup` | `skills/splunk-appdynamics-dashboards-reports-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-thousandeyes-integration-setup` | `skills/splunk-appdynamics-thousandeyes-integration-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-tags-extensions-setup` | `skills/splunk-appdynamics-tags-extensions-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-security-ai-setup` | `skills/splunk-appdynamics-security-ai-setup/SKILL.md` | Canonical |
| `splunk-appdynamics-sap-agent-setup` | `skills/splunk-appdynamics-sap-agent-setup/SKILL.md` | Canonical |
| `cisco-security-cloud-setup` | `skills/cisco-security-cloud-setup/SKILL.md` | Canonical |
| `cisco-secure-access-setup` | `skills/cisco-secure-access-setup/SKILL.md` | Canonical |
| `cisco-webex-setup` | `skills/cisco-webex-setup/SKILL.md` | Canonical |
| `cisco-ucs-ta-setup` | `skills/cisco-ucs-ta-setup/SKILL.md` | Canonical |
| `cisco-secure-email-web-gateway-setup` | `skills/cisco-secure-email-web-gateway-setup/SKILL.md` | Canonical |
| `cisco-asa-ta-setup` | `skills/cisco-asa-ta-setup/SKILL.md` | Canonical |
| `cisco-talos-intelligence-setup` | `skills/cisco-talos-intelligence-setup/SKILL.md` | Canonical |
| `cisco-spaces-setup` | `skills/cisco-spaces-setup/SKILL.md` | Canonical |
| `cisco-dc-networking-setup` | `skills/cisco-dc-networking-setup/SKILL.md` | Canonical |
| `cisco-intersight-setup` | `skills/cisco-intersight-setup/SKILL.md` | Canonical |
| `cisco-meraki-ta-setup` | `skills/cisco-meraki-ta-setup/SKILL.md` | Canonical |
| `cisco-meraki-aam-thousandeyes-setup` | `skills/cisco-meraki-aam-thousandeyes-setup/SKILL.md` | Canonical |
| `cisco-enterprise-networking-setup` | `skills/cisco-enterprise-networking-setup/SKILL.md` | Canonical |
| `cisco-thousandeyes-setup` | `skills/cisco-thousandeyes-setup/SKILL.md` | Canonical |
| `cisco-thousandeyes-mcp-setup` | `skills/cisco-thousandeyes-mcp-setup/SKILL.md` | Canonical |
| `cisco-defenseclaw-deskside-setup` | `skills/cisco-defenseclaw-deskside-setup/SKILL.md` | Canonical |
| `cisco-isovalent-platform-setup` | `skills/cisco-isovalent-platform-setup/SKILL.md` | Canonical |
| `widefield-security-setup` | `skills/widefield-security-setup/SKILL.md` | Canonical |
| `widefield-okta-integration-setup` | `skills/widefield-okta-integration-setup/SKILL.md` | Canonical |
| `widefield-saviynt-integration-setup` | `skills/widefield-saviynt-integration-setup/SKILL.md` | Canonical |
| `widefield-splunk-siem-setup` | `skills/widefield-splunk-siem-setup/SKILL.md` | Canonical |
| `widefield-google-secops-setup` | `skills/widefield-google-secops-setup/SKILL.md` | Canonical |
| `widefield-identity-threat-doctor` | `skills/widefield-identity-threat-doctor/SKILL.md` | Canonical |
| `splunk-itsi-setup` | `skills/splunk-itsi-setup/SKILL.md` | Canonical |
| `splunk-itsi-config` | `skills/splunk-itsi-config/SKILL.md` | Canonical |
| `splunk-enterprise-security-install` | `skills/splunk-enterprise-security-install/SKILL.md` | Canonical |
| `splunk-enterprise-security-config` | `skills/splunk-enterprise-security-config/SKILL.md` | Canonical |
| `splunk-security-portfolio-setup` | `skills/splunk-security-portfolio-setup/SKILL.md` | Canonical |
| `splunk-security-essentials-setup` | `skills/splunk-security-essentials-setup/SKILL.md` | Canonical |
| `splunk-security-content-update-setup` | `skills/splunk-security-content-update-setup/SKILL.md` | Canonical |
| `splunk-lookup-file-editing-setup` | `skills/splunk-lookup-file-editing-setup/SKILL.md` | Canonical |
| `splunk-infosec-app-setup` | `skills/splunk-infosec-app-setup/SKILL.md` | Canonical |
| `splunk-pci-compliance-setup` | `skills/splunk-pci-compliance-setup/SKILL.md` | Canonical |
| `splunk-fraud-analytics-setup` | `skills/splunk-fraud-analytics-setup/SKILL.md` | Canonical |
| `splunk-asset-risk-intelligence-setup` | `skills/splunk-asset-risk-intelligence-setup/SKILL.md` | Canonical |
| `splunk-attack-analyzer-setup` | `skills/splunk-attack-analyzer-setup/SKILL.md` | Canonical |
| `splunk-uba-setup` | `skills/splunk-uba-setup/SKILL.md` | Canonical |
| `splunk-ai-assistant-setup` | `skills/splunk-ai-assistant-setup/SKILL.md` | Canonical |
| `splunk-ai-ml-toolkit-setup` | `skills/splunk-ai-ml-toolkit-setup/SKILL.md` | Canonical |
| `splunk-mcp-server-setup` | `skills/splunk-mcp-server-setup/SKILL.md` | Canonical |
| `splunk-admin-doctor` | `skills/splunk-admin-doctor/SKILL.md` | Canonical |
| `splunk-data-source-readiness-doctor` | `skills/splunk-data-source-readiness-doctor/SKILL.md` | Canonical |
| `splunk-supported-addons-setup` | `skills/splunk-supported-addons-setup/SKILL.md` | Canonical |
| `splunk-windows-ta-setup` | `skills/splunk-windows-ta-setup/SKILL.md` | Canonical |
| `splunk-microsoft-cloud-setup` | `skills/splunk-microsoft-cloud-setup/SKILL.md` | Canonical |
| `splunk-aws-ta-setup` | `skills/splunk-aws-ta-setup/SKILL.md` | Canonical |
| `splunk-amazon-kinesis-firehose-setup` | `skills/splunk-amazon-kinesis-firehose-setup/SKILL.md` | Canonical |
| `splunk-okta-ta-setup` | `skills/splunk-okta-ta-setup/SKILL.md` | Canonical |
| `splunk-gcp-ta-setup` | `skills/splunk-gcp-ta-setup/SKILL.md` | Canonical |
| `splunk-servicenow-ta-setup` | `skills/splunk-servicenow-ta-setup/SKILL.md` | Canonical |
| `splunk-google-workspace-ta-setup` | `skills/splunk-google-workspace-ta-setup/SKILL.md` | Canonical |
| `splunk-microsoft-security-ta-setup` | `skills/splunk-microsoft-security-ta-setup/SKILL.md` | Canonical |
| `splunk-microsoft-exchange-ta-setup` | `skills/splunk-microsoft-exchange-ta-setup/SKILL.md` | Canonical |
| `splunk-microsoft-scom-ta-setup` | `skills/splunk-microsoft-scom-ta-setup/SKILL.md` | Canonical |
| `splunk-sysmon-ta-setup` | `skills/splunk-sysmon-ta-setup/SKILL.md` | Canonical |
| `splunk-github-ta-setup` | `skills/splunk-github-ta-setup/SKILL.md` | Canonical |
| `splunk-salesforce-ta-setup` | `skills/splunk-salesforce-ta-setup/SKILL.md` | Canonical |
| `splunk-box-ta-setup` | `skills/splunk-box-ta-setup/SKILL.md` | Canonical |
| `splunk-cyberark-ta-setup` | `skills/splunk-cyberark-ta-setup/SKILL.md` | Canonical |
| `splunk-rsa-securid-ta-setup` | `skills/splunk-rsa-securid-ta-setup/SKILL.md` | Canonical |
| `splunk-security-appliance-ta-setup` | `skills/splunk-security-appliance-ta-setup/SKILL.md` | Canonical |
| `splunk-syslog-web-proxy-ta-setup` | `skills/splunk-syslog-web-proxy-ta-setup/SKILL.md` | Canonical |
| `splunk-vmware-ta-setup` | `skills/splunk-vmware-ta-setup/SKILL.md` | Canonical |
| `splunk-database-ta-setup` | `skills/splunk-database-ta-setup/SKILL.md` | Canonical |
| `splunk-netapp-ontap-ta-setup` | `skills/splunk-netapp-ontap-ta-setup/SKILL.md` | Canonical |
| `splunk-spl2-pipeline-kit` | `skills/splunk-spl2-pipeline-kit/SKILL.md` | Canonical |
| `splunk-ingest-processor-setup` | `skills/splunk-ingest-processor-setup/SKILL.md` | Canonical |
| `splunk-cloud-data-manager-setup` | `skills/splunk-cloud-data-manager-setup/SKILL.md` | Canonical |
| `splunk-db-connect-setup` | `skills/splunk-db-connect-setup/SKILL.md` | Canonical |
| `splunk-app-install` | `skills/splunk-app-install/SKILL.md` | Canonical |
| `splunk-universal-forwarder-setup` | `skills/splunk-universal-forwarder-setup/SKILL.md` | Canonical |
| `splunk-agent-management-setup` | `skills/splunk-agent-management-setup/SKILL.md` | Canonical |
| `splunk-workload-management-setup` | `skills/splunk-workload-management-setup/SKILL.md` | Canonical |
| `splunk-hec-service-setup` | `skills/splunk-hec-service-setup/SKILL.md` | Canonical |
| `splunk-platform-restart-orchestrator` | `skills/splunk-platform-restart-orchestrator/SKILL.md` | Canonical |
| `splunk-connect-for-otlp-setup` | `skills/splunk-connect-for-otlp-setup/SKILL.md` | Canonical |
| `splunk-federated-search-setup` | `skills/splunk-federated-search-setup/SKILL.md` | Canonical |
| `splunk-index-lifecycle-smartstore-setup` | `skills/splunk-index-lifecycle-smartstore-setup/SKILL.md` | Canonical |
| `splunk-kvstore-admin-setup` | `skills/splunk-kvstore-admin-setup/SKILL.md` | Canonical |
| `splunk-cim-data-model-setup` | `skills/splunk-cim-data-model-setup/SKILL.md` | Canonical |
| `splunk-knowledge-objects-setup` | `skills/splunk-knowledge-objects-setup/SKILL.md` | Canonical |
| `splunk-ingest-actions-setup` | `skills/splunk-ingest-actions-setup/SKILL.md` | Canonical |
| `splunk-ddaa-archive-setup` | `skills/splunk-ddaa-archive-setup/SKILL.md` | Canonical |
| `splunk-secure-gateway-setup` | `skills/splunk-secure-gateway-setup/SKILL.md` | Canonical |
| `splunk-dashboard-studio-setup` | `skills/splunk-dashboard-studio-setup/SKILL.md` | Canonical |
| `splunk-monitoring-console-setup` | `skills/splunk-monitoring-console-setup/SKILL.md` | Canonical |
| `splunk-enterprise-host-setup` | `skills/splunk-enterprise-host-setup/SKILL.md` | Canonical |
| `splunk-enterprise-kubernetes-setup` | `skills/splunk-enterprise-kubernetes-setup/SKILL.md` | Canonical |
| `splunk-platform-sizing` | `skills/splunk-platform-sizing/SKILL.md` | Canonical |
| `splunk-observability-otel-collector-setup` | `skills/splunk-observability-otel-collector-setup/SKILL.md` | Canonical |
| `splunk-observability-ai-agent-monitoring-setup` | `skills/splunk-observability-ai-agent-monitoring-setup/SKILL.md` | Canonical |
| `splunk-observability-coding-agent-instrumentation-setup` | `skills/splunk-observability-coding-agent-instrumentation-setup/SKILL.md` | Canonical |
| `splunk-observability-codex-instrumentation-setup` | `skills/splunk-observability-codex-instrumentation-setup/SKILL.md` | Canonical |
| `splunk-observability-claude-code-instrumentation-setup` | `skills/splunk-observability-claude-code-instrumentation-setup/SKILL.md` | Canonical |
| `splunk-observability-database-monitoring-setup` | `skills/splunk-observability-database-monitoring-setup/SKILL.md` | Canonical |
| `splunk-observability-k8s-auto-instrumentation-setup` | `skills/splunk-observability-k8s-auto-instrumentation-setup/SKILL.md` | Canonical |
| `splunk-observability-k8s-frontend-rum-setup` | `skills/splunk-observability-k8s-frontend-rum-setup/SKILL.md` | Canonical |
| `splunk-observability-browser-rum-setup` | `skills/splunk-observability-browser-rum-setup/SKILL.md` | Canonical |
| `splunk-observability-mobile-rum-setup` | `skills/splunk-observability-mobile-rum-setup/SKILL.md` | Canonical |
| `splunk-observability-cloud-integration-setup` | `skills/splunk-observability-cloud-integration-setup/SKILL.md` | Canonical |
| `splunk-observability-thousandeyes-integration` | `skills/splunk-observability-thousandeyes-integration/SKILL.md` | Canonical |
| `galileo-on-prem-kubernetes-setup` | `skills/galileo-on-prem-kubernetes-setup/SKILL.md` | Canonical |
| `galileo-on-prem-stack-setup` | `skills/galileo-on-prem-stack-setup/SKILL.md` | Canonical |
| `galileo-on-prem-agent-control-setup` | `skills/galileo-on-prem-agent-control-setup/SKILL.md` | Canonical |
| `galileo-on-prem-luna-studio-setup` | `skills/galileo-on-prem-luna-studio-setup/SKILL.md` | Canonical |
| `galileo-on-prem-air-gap-setup` | `skills/galileo-on-prem-air-gap-setup/SKILL.md` | Canonical |
| `galileo-mcp-server-setup` | `skills/galileo-mcp-server-setup/SKILL.md` | Canonical |
| `galileo-platform-setup` | `skills/galileo-platform-setup/SKILL.md` | Canonical |
| `galileo-lemonade-instrumentation-setup` | `skills/galileo-lemonade-instrumentation-setup/SKILL.md` | Canonical |
| `lemonade-splunk-otel` | `skills/lemonade-splunk-otel/SKILL.md` | Canonical |
| `galileo-agent-control-setup` | `skills/galileo-agent-control-setup/SKILL.md` | Canonical |
| `splunk-observability-isovalent-integration` | `skills/splunk-observability-isovalent-integration/SKILL.md` | Canonical |
| `splunk-observability-cisco-nexus-integration` | `skills/splunk-observability-cisco-nexus-integration/SKILL.md` | Canonical |
| `splunk-observability-cisco-intersight-integration` | `skills/splunk-observability-cisco-intersight-integration/SKILL.md` | Canonical |
| `splunk-observability-nvidia-gpu-integration` | `skills/splunk-observability-nvidia-gpu-integration/SKILL.md` | Canonical |
| `splunk-observability-cisco-ai-pod-integration` | `skills/splunk-observability-cisco-ai-pod-integration/SKILL.md` | Canonical |
| `splunk-observability-aws-integration` | `skills/splunk-observability-aws-integration/SKILL.md` | Canonical |
| `splunk-observability-azure-integration` | `skills/splunk-observability-azure-integration/SKILL.md` | Canonical |
| `splunk-observability-gcp-integration` | `skills/splunk-observability-gcp-integration/SKILL.md` | Canonical |
| `splunk-observability-aws-lambda-apm-setup` | `skills/splunk-observability-aws-lambda-apm-setup/SKILL.md` | Canonical |
| `splunk-observability-dashboard-builder` | `skills/splunk-observability-dashboard-builder/SKILL.md` | Canonical |
| `splunk-observability-deep-native-workflows` | `skills/splunk-observability-deep-native-workflows/SKILL.md` | Canonical |
| `splunk-observability-native-ops` | `skills/splunk-observability-native-ops/SKILL.md` | Canonical |
| `splunk-observability-synthetics-setup` | `skills/splunk-observability-synthetics-setup/SKILL.md` | Canonical |
| `splunk-observability-slo-setup` | `skills/splunk-observability-slo-setup/SKILL.md` | Canonical |
| `splunk-observability-metrics-pipeline-setup` | `skills/splunk-observability-metrics-pipeline-setup/SKILL.md` | Canonical |
| `splunk-oncall-setup` | `skills/splunk-oncall-setup/SKILL.md` | Canonical |
| `splunk-stream-setup` | `skills/splunk-stream-setup/SKILL.md` | Canonical |
| `splunk-connect-for-syslog-setup` | `skills/splunk-connect-for-syslog-setup/SKILL.md` | Canonical |
| `splunk-connect-for-snmp-setup` | `skills/splunk-connect-for-snmp-setup/SKILL.md` | Canonical |
| `splunk-license-manager-setup` | `skills/splunk-license-manager-setup/SKILL.md` | Canonical |
| `splunk-soar-setup` | `skills/splunk-soar-setup/SKILL.md` | Canonical |
| `splunk-edge-processor-setup` | `skills/splunk-edge-processor-setup/SKILL.md` | Canonical |
| `splunk-indexer-cluster-setup` | `skills/splunk-indexer-cluster-setup/SKILL.md` | Canonical |
| `splunk-search-head-cluster-setup` | `skills/splunk-search-head-cluster-setup/SKILL.md` | Canonical |
| `splunk-deployment-server-setup` | `skills/splunk-deployment-server-setup/SKILL.md` | Canonical |
| `splunk-cloud-acs-admin-setup` | `skills/splunk-cloud-acs-admin-setup/SKILL.md` | Canonical |
| `splunk-cloud-acs-allowlist-setup` | `skills/splunk-cloud-acs-allowlist-setup/SKILL.md` | Canonical |
| `splunk-enterprise-public-exposure-hardening` | `skills/splunk-enterprise-public-exposure-hardening/SKILL.md` | Canonical |
| `splunk-platform-pki-setup` | `skills/splunk-platform-pki-setup/SKILL.md` | Canonical |
<!-- END GENERATED SKILL CATALOG -->

## Splunk MCP Server

If `.mcp.json` exists at the project root, the Splunk MCP server is available as the
`splunk-mcp` tool through the tracked `splunk-mcp-rendered/run-splunk-mcp.js`
bridge. The local token file (`splunk-mcp-rendered/.env.splunk-mcp`) only exists
after running the `splunk-mcp-server-setup` skill. Use MCP search tools for live
Splunk queries when available.

<!-- BEGIN GENERATED LOCAL SKILL MCP SAFETY -->
<!-- source: skills/catalog.yaml#shared_sections.local_skill_mcp_server; schema: 1; sha256: 4bb6aab4661bc8efe961cc511cfa370430bd8bc0f0b51fdad0f3a85a9f4a89ff -->
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

The code-level execution default is off, while the committed Claude
Code/Cursor registrations and Codex helper explicitly set
`SPLUNK_SKILLS_MCP_ENABLE_EXECUTION=1`. Pure-Python product resolution and
bounded skill discovery never launch subprocesses. Dry-run planning does.
Generic script execution is always mutation-gated and additionally requires
both `SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION=1` and
`SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1`; committed registrations explicitly keep
both at `0`. All execution tools require a matching plan hash and literal
Boolean confirmation.

Plans are also bound to the complete `skills/` dependency-tree snapshot and
revalidated after the execution lock is acquired. Changes to shared helpers,
catalogs, policies, or delegated scripts invalidate the plan.

Plans are single-use and stored in memory for the MCP server session: a plan
is consumed when it executes, and the entire plan store is lost if the server
restarts. If a plan hash is rejected as unknown, re-run the plan step to get a
fresh hash. `SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1` is a server-wide toggle — it
enables mutating execution for all clients connected to that server process.
Do not enable it on the normal shared registration; start a separately reviewed
single-operator server when mutation is intentionally required.
<!-- END GENERATED LOCAL SKILL MCP SAFETY -->

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
