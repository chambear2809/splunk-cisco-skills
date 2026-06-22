# Skill Requirements

This catalog documents the software and access requirements for each skill.
Use it before running a skill so the operator can install the right local
tools, prepare the right credentials files, and avoid discovering missing
workflow dependencies halfway through an apply.

## Shared Baseline

All skills assume:

- `bash`, `curl`, `python3`, and the repository root as the working directory.
- A repo virtual environment with `pip install -r requirements-agent.txt` when
  using the local MCP server or YAML-heavy Python renderers.
- A local `credentials` file or `SPLUNK_CREDENTIALS_FILE`, mode `0600`, plus
  separate secret files for tokens, passwords, API keys, and client secrets.
- Splunk Enterprise management REST access on `8089`, or Splunk Cloud ACS plus
  search-tier REST allow-list access, for live app install/configure/validate
  workflows.
- A Splunkbase/splunk.com account when the workflow downloads public Splunk
  apps or TAs.

Development and CI additionally require:

- `pip install -r requirements-dev.txt -r requirements-agent.txt`
- `bats`, `shellcheck`, `ruff`, `yamllint`, and `pre-commit` for the documented
  local check suite.

Environment-specific notes:

- AWS live workflows require an authenticated AWS CLI profile or session with
  the right target account, organization, and regional permissions. Use your
  local organization's SSO or credential broker outside this repository.
- Kubernetes apply/validate paths require the right `kubectl` or `oc` context.
- Cloud and Observability tokens must be referenced by file path, never pasted
  into shell arguments or chat.
- Splunk TA, add-on, and dashboard companion setup skills must satisfy the
  shared `skills/shared/ta_completion_gate.md`: data ingest must be configured
  and validated, and any pre-built dashboards must be visible, macro-aligned,
  and returning data, or explicitly documented as not shipped by the package.

## Cisco Product And App Setup

| Skill | Additional local tooling | Live access and product requirements |
| --- | --- | --- |
| `cisco-appdynamics-setup` | Shared baseline. | Splunk app workflow access; AppDynamics controller and analytics endpoint details; controller credentials/client secrets in files. |
| `cisco-catalyst-enhanced-netflow-setup` | Shared baseline; Splunk Stream placement awareness. | Splunk app workflow access; existing Stream/IPFIX/HSL collection path and Catalyst data prerequisites. |
| `cisco-catalyst-ta-setup` | Shared baseline. | Splunk app workflow access; Catalyst Center, ISE, SD-WAN, or Cyber Vision host/account details; device/API secrets in files. |
| `cisco-cloud-control-setup` | Shared baseline; `PyYAML` for YAML intake specs. | Cisco Cloud Control entitlement/readiness context; Cloud Control Studio and AI Canvas access for UI handoffs; Splunk child-skill access inherits from Data Fabric, MCP, Observability, and Cisco domain workflows. |
| `cisco-dc-networking-setup` | Shared baseline. | Splunk app workflow access; ACI/APIC, Nexus Dashboard, or Nexus 9K account details; device/API secrets in files. |
| `cisco-enterprise-networking-setup` | Shared baseline. | Splunk app workflow access; Cisco Enterprise Networking app installed; macro/index values for Catalyst/ISE dashboard searches. |
| `cisco-intersight-setup` | Shared baseline. | Splunk app workflow access; Cisco Intersight account/API material stored in files. |
| `cisco-isovalent-platform-setup` | `kubectl`, `helm`; optional `aws` for EKS helpers. | Kubernetes cluster-admin style access; Cilium/Tetragon chart access; Isovalent Enterprise chart/license/pull secret when using Enterprise mode. |
| `cisco-meraki-ta-setup` | Shared baseline. | Splunk app workflow access; Meraki organization details and API key file. |
| `cisco-product-setup` | Shared baseline. | SCAN catalog present; requirements inherit from the routed product setup skill. |
| `cisco-scan-setup` | Shared baseline. | Splunk app workflow access; SCAN package/catalog sync access when refreshing the Cisco product catalog. |
| `cisco-secure-access-setup` | Shared baseline. | Splunk app workflow access; Secure Access org/account details; event add-on prerequisites; client secrets in files. |
| `cisco-secure-email-web-gateway-setup` | Shared baseline; SC4S or file-monitor handoff tools when using collector paths. | Splunk app workflow access; ESA/WSA source details; collector/index/macro placement decisions. |
| `cisco-security-cloud-setup` | Shared baseline. | Splunk app workflow access; Cisco Security Cloud product variant details and input credentials in files. |
| `cisco-spaces-setup` | Shared baseline. | Splunk app workflow access; Cisco Spaces account, firehose/meta stream details, and activation token file. |
| `cisco-talos-intelligence-setup` | Shared baseline. | Splunk Enterprise Security Cloud readiness; Talos service account and capability mapping details. |
| `cisco-thousandeyes-mcp-setup` | `node`, `npx`, `mcp-remote`; `codex` when registering Codex; `curl` for endpoint checks. | ThousandEyes MCP/API token material in files; target MCP clients available for registration. |
| `cisco-thousandeyes-setup` | Shared baseline; `curl` for ThousandEyes/API checks. | Splunk app workflow access; ThousandEyes OAuth/account details; HEC and dashboard prerequisites. |
| `cisco-ucs-ta-setup` | Shared baseline. | Splunk app workflow access; UCS Manager host/account details and password file. |
| `cisco-webex-setup` | Shared baseline. | Splunk app workflow access; Webex OAuth app, scopes, organization IDs, and secret files. |

## Splunk AppDynamics

| Skill | Additional local tooling | Live access and product requirements |
| --- | --- | --- |
| `splunk-appdynamics-setup` | Shared baseline; `PyYAML`. | AppDynamics Controller URL/account details for routing; no secrets in specs; child requirements inherit from selected owner skill. |
| `splunk-appdynamics-platform-setup` | Shared baseline; optional `ssh` and platform CLIs for reviewed runbooks. | AppDynamics On-Premises or Virtual Appliance admin access; Enterprise Console mutation acceptance for platform changes. |
| `splunk-appdynamics-controller-admin-setup` | Shared baseline; `curl`. | AppDynamics Controller admin/API access; OAuth client secrets and passwords in chmod-600 files. |
| `splunk-appdynamics-agent-management-setup` | Shared baseline; optional `ssh` for reviewed host execution. | Smart Agent and Agent Management access; target host inventory; remote execution requires explicit acceptance. |
| `splunk-appdynamics-dual-agent-setup` | Shared baseline; optional `ssh`; host shell tools (`systemctl`, container runtime, or PowerShell) as declared by target runtime. | Target host inventory; Java service startup config path; Machine Agent bundled collector path; Splunk O11y token file and AppDynamics OTel API key file; host mutation, remote execution, app restart, and full restart strategy require explicit acceptance. |
| `splunk-appdynamics-apm-setup` | Shared baseline. | AppDynamics Controller API access; application/tier/runtime details; runtime source edits handled by downstream owners. |
| `splunk-appdynamics-k8s-cluster-agent-setup` | `kubectl` or `oc`; optional `helm`. | Kubernetes cluster access; AppDynamics Controller account secret in Kubernetes; rollout requires explicit acceptance. |
| `splunk-appdynamics-infrastructure-visibility-setup` | Shared baseline; optional host access for Machine Agent runbooks. | Controller access; host/container/network visibility details; host secrets in files. |
| `splunk-appdynamics-machine-agent-otel-collector-setup` | Shared baseline; optional `ssh`; host shell tools for service/container restart. | Machine Agent install path and install type (`rpm`, `zip`, `docker`, or `windows_zip`); collector config path; service or container identity; Splunk O11y token file and AppDynamics OTel API key file; host mutation and remote execution require explicit acceptance. |
| `splunk-appdynamics-database-visibility-setup` | Shared baseline; `curl`. | Database Visibility API access; database credentials in chmod-600 files referenced by collector specs. |
| `splunk-appdynamics-analytics-setup` | Shared baseline; `curl`. | Analytics endpoint/global account; Events API key file; custom event publishing requires explicit acceptance. |
| `splunk-appdynamics-eum-setup` | Shared baseline; optional app build tooling for source-map upload runbooks. | EUM app keys; source edits require explicit acceptance; source-map upload tokens in files. |
| `splunk-appdynamics-synthetic-monitoring-setup` | `kubectl` or container runtime for Private Synthetic Agent paths. | Synthetic Monitoring access; PSA secrets in files or Kubernetes Secrets; private agent rollout reviewed before apply. |
| `splunk-appdynamics-log-observer-connect-setup` | Shared baseline; Splunk Platform tools inherit from delegated skills. | AppDynamics LOC access; Splunk Cloud/Enterprise service-account and allow-list readiness. |
| `splunk-appdynamics-alerting-content-setup` | Shared baseline. | Controller API access for health rules, policies, actions, and export snapshots. |
| `splunk-appdynamics-dashboards-reports-setup` | Shared baseline. | Controller API/UI access for dashboards, reports, schedules, and War Rooms. |
| `splunk-appdynamics-thousandeyes-integration-setup` | Shared baseline; optional `curl` for API probes. | AppDynamics Controller and ThousandEyes access; tokens, passwords, OAuth client secrets, and API keys in chmod-600 files. |
| `splunk-appdynamics-tags-extensions-setup` | Shared baseline; optional host access for Machine Agent extensions. | Controller tag API access; extension and third-party connector details; secrets in files. |
| `splunk-appdynamics-security-ai-setup` | Shared baseline; downstream Observability/Cisco AI tools as needed. | Secure Application or Observability for AI entitlement/readiness; GPU and Cisco AI Pod handoff context. |
| `splunk-appdynamics-sap-agent-setup` | Shared baseline; SAP Basis tools handled by operator runbooks. | SAP system details, transport/authorization readiness, and AppDynamics Controller access; SAP credentials in files. |

## Collectors And Forwarders

| Skill | Additional local tooling | Live access and product requirements |
| --- | --- | --- |
| `splunk-connect-for-otlp-setup` | Shared baseline. | Splunk app workflow access for app `8704`; HEC token/index readiness; OTLP sender endpoint details. |
| `splunk-connect-for-snmp-setup` | `docker` or `podman` for Compose paths; `kubectl` and `helm` for Kubernetes paths. | HEC token/index readiness; SNMP polling/trap source details; Kubernetes or container host access. |
| `splunk-connect-for-syslog-setup` | `docker` or `podman` for host paths; `kubectl` and `helm` for Kubernetes paths; `sudo` for system host setup. | HEC token/index readiness; syslog source/network port planning; Kubernetes or collector host access. |
| `splunk-stream-setup` | Shared baseline. | Splunk app workflow access; Stream Forwarder host/network placement; packet capture or NetFlow/IPFIX source access. |
| `splunk-universal-forwarder-setup` | `ssh`, `sudo`; `sshpass` for password-based remote bootstrap. | Target Linux/macOS/Windows hosts; Splunk package or Splunk Cloud credentials package; deployment server or indexer output details. |

## Security And Response

| Skill | Additional local tooling | Live access and product requirements |
| --- | --- | --- |
| `splunk-asset-risk-intelligence-setup` | Shared baseline. | Splunk app workflow access; ARI app package or Splunkbase access; KV Store and ES Exposure Analytics readiness. |
| `splunk-attack-analyzer-setup` | Shared baseline. | Splunk app workflow access; Attack Analyzer app/add-on packages; `saa` index and API key handoff. |
| `splunk-enterprise-security-config` | `PyYAML`; optional `ssh`, `scp`, and `sshpass` for package/content staging. | Splunk Enterprise Security REST access; ES app installed or install handoff permitted; lookup/threat/intel files supplied locally. |
| `splunk-enterprise-security-install` | Optional `ssh` and `scp` for deployer/indexer staging; Bats/ShellCheck only for local tests. | ES package or Splunkbase access; search head or SHC deployer admin access; KV Store backup/restart permissions. |
| `splunk-oncall-setup` | `PyYAML` for YAML specs. | Splunk On-Call API ID, API key file, REST endpoint integration key file, routing keys, and optional Splunk-side app workflow access. |
| `splunk-security-essentials-setup` | Shared baseline. | Splunk app workflow access; Splunk Security Essentials package or Splunkbase access. |
| `splunk-security-portfolio-setup` | Shared baseline. | Product routing access; requirements inherit from the selected ES, SOAR, SSE, UBA, Attack Analyzer, or ARI workflow. |
| `splunk-soar-setup` | `docker` or `podman`; `systemctl`; optional `ssh`, `scp`, and `sudo` for remote/on-prem setup. | SOAR package or Cloud onboarding details; external PostgreSQL/GlusterFS/Elasticsearch details when clustering; Automation Broker host access. |
| `splunk-uba-setup` | Shared baseline. | Splunk UBA/UEBA environment details; optional Kafka app placement; ES Premier UEBA migration context. |
| `widefield-security-setup` | Shared baseline. | WideField adoption context; child-skill requirements inherit from Okta, Saviynt, Splunk SIEM, Google SecOps, and identity-threat doctor workflows. |
| `widefield-okta-integration-setup` | Shared baseline. | Okta org URL; Okta API token in a chmod 600 file; WideField receiver URL for documented event hook apply; Shared Signals/OIN setup evidence for UI handoffs. |
| `widefield-saviynt-integration-setup` | Shared baseline. | Saviynt tenant URL and remediation evidence; live mutation requires official Saviynt or customer-provided API documentation before enabling apply. |
| `widefield-splunk-siem-setup` | Shared baseline; `splunk-hec-service-setup` for token lifecycle. | Splunk Enterprise REST or Splunk Cloud ACS access; HEC token value file for Enterprise or write-token file for Cloud; target WideField index/source/sourcetype plan. |
| `widefield-google-secops-setup` | Shared baseline. | Google SecOps project/feed context and evidence for log type `WIDEFIELD_SECURITY`; live feed creation requires documented API coverage before enabling apply. |
| `widefield-identity-threat-doctor` | Shared baseline. | WideField events in Splunk, Okta System Log access via token file, Google SecOps/Saviynt evidence JSON; destructive remediation is target-skill gated. |

## Splunk Observability

| Skill | Additional local tooling | Live access and product requirements |
| --- | --- | --- |
| `galileo-agent-control-setup` | Shared baseline; optional Python and TypeScript package managers for applying rendered runtime snippets. | Standalone Agent Control server URL and API/admin key files; optional Splunk HEC token file, Splunk Observability token file, and target realm for sinks, dashboards, and detectors. |
| `galileo-mcp-server-setup` | `node`, `npx`, `mcp-remote`; `codex` when registering Codex; optional `curl` and Python for live MCP probes. | Galileo API key material in files or client secret stores; target MCP clients (Cursor, VS Code, Codex, Claude Code, AWS Kiro). Render and probe phases avoid inline secrets. |
| `galileo-platform-setup` | Shared baseline; `curl` for healthcheck/readiness probes; `galileo` Python SDK for object lifecycle apply; optional `galileo-protect` for legacy Protect stage creation. | Galileo API key file, project/log-stream/dataset/prompt/experiment/metric details, Agent Observability Controls inventory, and legacy Protect stage details; optional Splunk HEC token file, Splunk Observability token file, and target realm for HEC export, OTel Collector, dashboards, and detectors. |
| `splunk-observability-ai-agent-monitoring-setup` | `PyYAML`; `kubectl` for Kubernetes runtime apply paths. | Splunk Observability realm and token files; GenAI application/runtime details; optional HEC/Log Observer Connect handoffs. |
| `splunk-observability-aws-integration` | `aws`; optional `terraform`; `curl`. | Authenticated AWS CLI profile/session; Splunk Observability admin/user token files; AWS account/organization permissions for CloudWatch and Metric Streams. |
| `splunk-observability-aws-lambda-apm-setup` | `aws`; optional `terraform`; `curl`. | Authenticated AWS CLI profile/session; Splunk Observability ingest token file; AWS Lambda function names, regions, runtimes; AWS Secrets Manager or SSM write permission for token storage. |
| `splunk-observability-azure-integration` | `az`; optional `terraform`; `curl`. | Authenticated Azure CLI session; Splunk Observability admin/user token files; Azure Service Principal (appId/secretKey via file) or Workload Identity; Azure subscription IDs and tenant ID. |
| `splunk-observability-cisco-ai-pod-integration` | `kubectl` or `oc`, `helm`, `yq`; child-skill tools for Nexus, Intersight, NVIDIA, and OTel collector handoffs. | Splunk Observability token files; Cisco AI Pod cluster access; UCS/Nexus/NVIDIA/NIM/vLLM/storage endpoint details. |
| `splunk-observability-cisco-intersight-integration` | `kubectl` or `oc`; optional `helm`, `jq`, `yq`, `openssl`, `nc` for live checks and troubleshooting. | Splunk Observability token files; Kubernetes namespace access; Intersight API credentials in a Kubernetes Secret. |
| `splunk-observability-cisco-nexus-integration` | `kubectl`, `helm`, `yq`; optional `ssh` and `nc` for device checks. | Splunk Observability token files; Nexus/NX-OS device SSH credentials via Kubernetes Secret; collector cluster access. |
| `splunk-observability-cloud-integration-setup` | `acs`, `curl`, `openssl`; optional `docker` for companion local checks. | Splunk Cloud/Enterprise REST access; Splunk Observability admin/org/user token files; Log Observer Connect and SIM add-on prerequisites. |
| `splunk-observability-dashboard-builder` | `PyYAML` for YAML specs. | Splunk Observability API token file with dashboard permissions; target realm/org. |
| `splunk-observability-deep-native-workflows` | `PyYAML` for YAML specs. | Splunk Observability realm; optional token files only for downstream owning skills if API apply is later executed. |
| `splunk-observability-database-monitoring-setup` | `kubectl`, `helm`; `PyYAML`. | Splunk Observability token files; database endpoint details; DB credentials in Kubernetes Secrets or local secret files. |
| `splunk-observability-gcp-integration` | `gcloud`; optional `terraform`; `curl`. | Authenticated gcloud CLI session; Splunk Observability admin/user token files; GCP Service Account key file (chmod 600) or Workload Identity Federation pool/provider; GCP project IDs. |
| `splunk-observability-isovalent-integration` | `kubectl` or `oc`, `helm`, `yq`; optional `jq` and `aws`. | Splunk Observability token files; installed Cilium/Tetragon/Hubble stack; optional Splunk HEC token/index for Tetragon logs. |
| `splunk-observability-browser-rum-setup` | `npm`/frontend build tooling and optional `splunk-rum` for source-map uploads. | Splunk Browser RUM token reference for build/runtime; Splunk Observability API token file for source maps; deployed frontend URL for validation. |
| `splunk-observability-k8s-auto-instrumentation-setup` | `kubectl`, `helm`; optional `npm` for app/runtime helper snippets. | Splunk Observability token files; OpenTelemetry Operator or Splunk OBI readiness; target workload namespaces. |
| `splunk-observability-k8s-frontend-rum-setup` | `kubectl`; `npm` and `splunk-rum` for source-map helpers. | Splunk RUM token file; Splunk Observability token file for source maps; target frontend workload/ingress access. |
| `splunk-observability-metrics-pipeline-setup` | Shared baseline; delegates deeper rendering to `splunk-observability-deep-native-workflows`. | Splunk Observability realm and metric/cardinality intent; token file only if downstream API apply is requested. |
| `splunk-observability-mobile-rum-setup` | Mobile app build context; optional `splunk-rum`, Xcode tooling for dSYMs, Android Gradle build output for mapping files, Node/Expo tooling for React Native, Flutter/Dart tooling for Flutter. | Splunk RUM token file or build-time token reference; Splunk Observability token file for dSYM/mapping upload helpers; local app source roots when rendering or applying source patches. |
| `splunk-observability-native-ops` | `PyYAML` for YAML specs. | Splunk Observability API token file with detector, alert-routing, synthetics, APM, RUM, or logs permissions; optional On-Call handoff. |
| `splunk-observability-nvidia-gpu-integration` | `kubectl`, `helm`, `yq`. | Splunk Observability token files; NVIDIA GPU Operator or DCGM Exporter in the target cluster. |
| `splunk-observability-otel-collector-setup` | `kubectl` and `helm` for Kubernetes; `ssh`, `scp`, `systemctl`, and `sudo` for Linux host apply; optional `npm` for generated helpers. | Splunk Observability realm/token files; target Kubernetes cluster or Linux host access; optional Splunk HEC token file for platform log export. |
| `splunk-observability-slo-setup` | Shared baseline; delegates deeper rendering to `splunk-observability-deep-native-workflows`. | Splunk Observability realm, SLI source, target/window, and service or metric details; token file only if downstream API apply is requested. |
| `splunk-observability-synthetics-setup` | Shared baseline; delegates API apply to `splunk-observability-native-ops`. | Splunk Observability realm, Synthetic test target URL, location, and frequency; API token file only for downstream live apply/run retrieval. |
| `splunk-observability-thousandeyes-integration` | `curl`, optional `jq`; `codex` only for MCP/client handoff snippets. | ThousandEyes OAuth/API credentials in files; Splunk Observability token files; TE test/stream/template permissions. |

## Splunk Platform Operations

| Skill | Additional local tooling | Live access and product requirements |
| --- | --- | --- |
| `splunk-admin-doctor` | `acs` for Cloud checks; optional `ssh`; `curl`. | Splunk Cloud ACS or Enterprise REST access; admin-domain permissions for the areas being diagnosed. |
| `splunk-data-source-readiness-doctor` | Shared baseline. | Evidence JSON from readiness collection searches; expected index/sourcetype/macro contracts; optional ES, ITSI, ARI, CIM, OCSF, and dashboard inventory exports. |
| `splunk-supported-addons-setup` | Shared baseline. | Supported-addons profile decisions; Splunkbase access for package install handoffs; target indexes, source types, forwarder rollout, HEC, and readiness requirements inherit from the resolved profile. |
| `splunk-windows-ta-setup` | Shared baseline. | Splunk app workflow access for `Splunk_TA_windows` install and index creation; Windows Universal Forwarder fleet for inputs; deployment-server/Agent Management access for forwarder rollout. Render phase needs no Splunk credentials. |
| `splunk-microsoft-cloud-setup` | Shared baseline. | Splunk app workflow access for `splunk_ta_o365` and `Splunk_TA_microsoft-cloudservices`; Azure Entra ID app registration (tenant ID, client ID) and client secret in a file configured through the add-on; search-tier or heavy-forwarder placement. Render phase needs no Splunk credentials. |
| `splunk-aws-ta-setup` | Shared baseline. | Splunk app workflow access for `Splunk_TA_aws`; AWS IAM role on the collector host or an access key + secret-key file configured through the add-on; SQS/S3 notification details; search-tier or heavy-forwarder placement. Render phase needs no Splunk credentials. |
| `splunk-okta-ta-setup` | Shared baseline. | Splunk app workflow access for `Splunk_TA_okta_identity_cloud`; Okta org domain plus an OAuth 2.0 client-credentials app (client secret in a file) or an API token in a file, configured through the add-on; search-tier or heavy-forwarder placement. Render phase needs no Splunk credentials. |
| `splunk-gcp-ta-setup` | Shared baseline. | Splunk app workflow access for `Splunk_TA_google-cloudplatform`; a GCP service-account JSON key file (or ADC on the collector host) and a Pub/Sub subscription fed by a Cloud Logging sink, configured through the add-on; search-tier or heavy-forwarder placement. Render phase needs no Splunk credentials. |
| `splunk-servicenow-ta-setup` | Shared baseline. | Splunk app workflow access for `Splunk_TA_snow`; a ServiceNow instance URL and a read-only integration user password (basic) or OAuth client secret in a file, configured through the add-on; search-tier or heavy-forwarder placement. Render phase needs no Splunk credentials. |
| `splunk-google-workspace-ta-setup` | Shared baseline. | Splunk app workflow access for `Splunk_TA_Google_Workspace`; Google service-account domain-wide delegation and certificate/private key in a local file, configured through the add-on; BigQuery dataset access for Gmail logs; search-tier or heavy-forwarder placement. Render phase needs no Splunk credentials. |
| `splunk-microsoft-security-ta-setup` | Shared baseline. | Splunk app workflow access for `Splunk_TA_MS_Security`; Entra app registration with client secret in a local file, selected Defender API permissions, and Event Hub namespace details if streaming is enabled; search-tier or heavy-forwarder placement. Render phase needs no Splunk credentials. |
| `splunk-microsoft-exchange-ta-setup` | Shared baseline; Windows Universal Forwarder or deployment-server rollout tooling for Exchange host collection. | Splunk app workflow access for the Microsoft Exchange add-on bundle and Exchange Indexes package; Exchange Client Access, Mailbox, SMTP, IIS, Windows, Perfmon, and Active Directory data collection ownership. Render phase needs no Splunk credentials. |
| `splunk-microsoft-scom-ta-setup` | Shared baseline; Windows/SCOM host access for PowerShell modular input ownership. | Splunk app workflow access for `Splunk_TA_microsoft-scom`; SCOM management server details and add-on account material configured through protected add-on storage or local secret files. Render phase needs no Splunk credentials. |
| `splunk-sysmon-ta-setup` | Shared baseline; Universal Forwarder or deployment-server rollout tooling for endpoint mode. | Splunk app workflow access for `Splunk_TA_microsoft_sysmon`; Microsoft Sysmon installed on endpoints or Windows Event Collector ownership; choose direct endpoint or WEC collection, not both for the same hosts. Render phase needs no Splunk credentials. |
| `splunk-github-ta-setup` | Shared baseline; SC4S/HEC tooling when using GHES or Cloud audit streaming handoffs. | Splunk app workflow access for `Splunk_TA_github`; GitHub PAT or GitHub App token in a local file configured through the add-on; HEC token/index plan for streaming audit logs; search-tier or heavy-forwarder placement. Render phase needs no Splunk credentials. |
| `cisco-asa-ta-setup` | Shared baseline; SC4S/syslog receiver tooling or customer syslog ownership. | Splunk app workflow access for `Splunk_TA_cisco-asa`; Cisco ASA or FTD syslog sender ownership; exact `cisco:asa` source typing and CIM Network_Traffic/Intrusion_Detection readiness evidence. Render phase needs no Splunk credentials. |
| `splunk-salesforce-ta-setup` | Shared baseline. | Splunk app workflow access for `Splunk_TA_salesforce`; Salesforce connected-app/OAuth credential material entered through the add-on account flow; search-tier or heavy-forwarder placement. Render phase needs no Splunk credentials. |
| `splunk-box-ta-setup` | Shared baseline. | Splunk app workflow access for `Splunk_TA_box`; Box OAuth/JWT credential material entered through the add-on account flow; reviewed folder scope for file ingestion; search-tier or heavy-forwarder placement. Render phase needs no Splunk credentials. |
| `splunk-cyberark-ta-setup` | Shared baseline; SC4S/syslog tooling for EPV/PTA. | Splunk app workflow access for CyberArk EPM and optional archived EPV/PTA parser package; EPM API credential material entered through the add-on account flow; EPV/PTA transport owned by SC4S/syslog with exact source types. Render phase needs no Splunk credentials. |
| `splunk-rsa-securid-ta-setup` | Shared baseline; SC4S/syslog tooling for Authentication Manager. | Splunk app workflow access for RSA CAS and AM packages; CAS credential material entered through the add-on account flow; AM transport owned by SC4S/syslog with exact source types. Render phase needs no Splunk credentials. |
| `splunk-security-appliance-ta-setup` | Shared baseline; Universal Forwarder, file monitor, or SC4S/syslog tooling depending on selected product. | Splunk app workflow access for Carbon Black and Symantec Endpoint Protection add-ons; file/syslog transport ownership, endpoint/security index selection, and readiness-doctor handoff details. Render phase needs no Splunk credentials. |
| `splunk-syslog-web-proxy-ta-setup` | Shared baseline; Universal Forwarder, Windows UF, or SC4S/syslog tooling depending on selected product. | Splunk app workflow access for selected web/proxy/parser add-ons; file monitor ownership for web servers, Windows UF ownership for IIS, and SC4S/syslog ownership for appliances. Render phase needs no Splunk credentials. |
| `splunk-amazon-kinesis-firehose-setup` | Shared baseline; Splunk HEC service tooling and AWS owner handoff. | HEC token/index plan, Firehose delivery stream ownership, IAM permissions, S3 backup bucket details, CloudWatch delivery metrics access, and strict source/sourcetype readiness evidence. Render phase needs no Splunk or AWS credentials. |
| `splunk-security-content-update-setup` | Shared baseline. | Enterprise Security search-head placement, `DA-ESS-ContentUpdate` install or upgrade planning, analytic story inventory access, and correlation-search activation review. Render phase needs no Splunk credentials. |
| `splunk-lookup-file-editing-setup` | Shared baseline. | Splunk App for Lookup File Editing install planning, CSV/KV Store lookup inventory access, SHC allowRestReplay backup-replication review, app health checks, and knowledge-object/KV Store handoffs. Render phase needs no Splunk credentials. |
| `splunk-infosec-app-setup` | Shared baseline. | InfoSec App install readiness, Lookup Editor dependency planning, security data-source checklist, dashboard and macro validation access, and CIM/data-model readiness details. Render phase needs no Splunk credentials. |
| `splunk-pci-compliance-setup` | Shared baseline. | PCI Compliance app install planning, cardholder data environment index and macro intake, CIM/data-model prerequisites, roles, reports, and dashboard evidence ownership. Render phase needs no Splunk credentials. |
| `splunk-fraud-analytics-setup` | Shared baseline. | Fraud Analytics app install planning, Enterprise Security and RBA prerequisites, Lookup File Editing dependency, fraud use-case intake, risk index details, and correlation-search review ownership. Render phase needs no Splunk credentials. |
| `splunk-vmware-ta-setup` | Shared baseline; optional local VMware package files for install handoffs; syslog collector tooling when ESXi logs are included. | Splunk app workflow access for VMware package placement; vCenter host/account details with credentials in local files; DCN/heavy-forwarder ownership and ESXi syslog receiver details. Render phase needs no Splunk credentials. |
| `splunk-database-ta-setup` | Shared baseline; optional local database TA package files for install handoffs. | Splunk app workflow access for Microsoft SQL Server, MySQL, and Oracle add-on package placement; DB Connect ownership for database connection identities; SQL Server host/file/perfmon input ownership; render phase needs no Splunk credentials. |
| `splunk-netapp-ontap-ta-setup` | Shared baseline; optional local ONTAP package files for install handoffs. | Splunk app workflow access for NetApp ONTAP package placement; ONTAP management endpoint/account ownership configured through protected add-on storage or local secret files; scheduler/worker placement and ITSI storage handoff details. Render phase needs no Splunk credentials. |
| `splunk-spl2-pipeline-kit` | Shared baseline. | SPL2 pipeline files or desired template profile; no Splunk tenant credentials required for offline render/lint. |
| `splunk-ingest-processor-setup` | Shared baseline. | Splunk Cloud Platform Victoria Experience tenant details; Ingest Processor entitlement/provisioning status; source type, destination, index, lookup, and service-account readiness details. |
| `splunk-agent-management-setup` | Shared baseline. | Splunk Enterprise deployment server or deployment-app file target access; server class/app ownership details. |
| `splunk-ai-assistant-setup` | Shared baseline. | Splunk app workflow access; Splunk AI Assistant entitlement and activation/onboarding details. |
| `splunk-ai-ml-toolkit-setup` | Shared baseline; `PyYAML` for YAML specs. | Splunk app workflow access; Splunkbase access for AI Toolkit, PSC, and DSDL packages; external DSDL runtime ownership for Docker, Kubernetes, OpenShift, HPC, GPU, or air-gapped handoffs. |
| `splunk-app-install` | `acs`; optional `ssh`, `scp`, and `sshpass` for Enterprise remote staging. | Splunk Enterprise REST or Splunk Cloud ACS access; Splunkbase credentials or local package path. |
| `splunk-cloud-acs-admin-setup` | `acs`; `curl` for source-IP discovery and ACS private-connectivity REST; optional `terraform`. | Splunk Cloud ACS stack permissions; exact allowlist/admin plan; lock-out protection review; local JSON admin plan for broader ACS operations; use the Observability pairing handoff for Unified Identity/RBAC apply. |
| `splunk-cloud-acs-allowlist-setup` | `acs`; optional `terraform`; `curl` for source-IP discovery. | Compatibility alias for allowlist-only plans; prefer `splunk-cloud-acs-admin-setup` for new ACS work. |
| `splunk-cloud-data-manager-setup` | `aws`, `az`, `gcloud`, and `terraform` only for the cloud artifact families being validated/applied. | Data Manager-generated CloudFormation/ARM/Terraform artifacts; cloud-provider permissions; HEC/index prerequisites. |
| `splunk-db-connect-setup` | Java `17` or `21` for Enterprise/customer-managed runtimes; Splunk-managed JRE validation for Cloud Victoria; JDBC driver packages or Splunkbase access for supported driver add-ons. | Splunk DB Connect topology plan; database endpoints; secret files or external references for DB identities; Cloud outbound allowlist details when applicable. |
| `splunk-edge-processor-setup` | `docker` for local/container handoffs; `systemctl` for Linux service paths. | Splunk Cloud or Enterprise Edge Processor control-plane access; EP instance host permissions. |
| `splunk-enterprise-host-setup` | `ssh`, `sudo`; package checksum tools from the host OS. | Target Linux hosts; Splunk Enterprise package access; role/topology settings for search/indexer/HF/cluster membership. |
| `splunk-enterprise-kubernetes-setup` | `kubectl`, `helm`; `aws` for optional EKS kubeconfig helper. | Kubernetes cluster access; Splunk Operator for Kubernetes or Splunk POD installer/bastion access. |
| `splunk-platform-sizing` | `python3`. | None; offline sizing calculator (no Splunk connection or credentials required). |
| `splunk-enterprise-public-exposure-hardening` | `openssl`, `nc`, `curl`; optional `aws`/ACS/firewall/WAF handoff tools. | On-prem Splunk Enterprise admin access; reverse proxy/firewall/WAF ownership; explicit public-exposure acceptance. |
| `splunk-federated-search-setup` | `PyYAML`; `curl`. | Splunk Enterprise REST access for federated provider/index configuration; remote provider details and credentials files. |
| `splunk-hec-service-setup` | Shared baseline. | Splunk Enterprise REST or Splunk Cloud ACS access; HEC index/token naming plan; HEC receiver URL decisions. |
| `splunk-index-lifecycle-smartstore-setup` | Shared baseline. | Splunk Enterprise indexer or cluster-manager access; object store bucket/remote volume details and credentials handoff. |
| `splunk-kvstore-admin` | Shared baseline. | Splunk search-head (or SHC) management access; `splunk` CLI on the host for KV Store backup/restore/migrate/resync; splunkd auth handled interactively, never in argv. |
| `splunk-cim-data-model` | Shared baseline. | Search-head (or SHC deployer) access; `Splunk_SA_CIM` installed; indexer capacity for acceleration; REST/CLI access for reload and rebuild. |
| `splunk-knowledge-objects` | Shared baseline. | Search-head (or SHC deployer) access; broad read for inventory and `admin_all_objects` for ownership/sharing reassignment. |
| `splunk-ingest-actions` | Shared baseline. | Ingest Actions access (UI or `/services/data/ingest/rulesets`); `list_ingest_rulesets`/`edit_ingest_rulesets` capabilities; S3/filesystem destination details and credentials handoff for RFS. |
| `splunk-ddaa-archive` | Shared baseline; `curl`. | Splunk Cloud stack with DDAA entitlement; ACS API token in a file; restore is UI-only. |
| `splunk-secure-gateway` | Shared baseline; `curl`. | Outbound 443 to `prod.spacebridge.spl.mobi`; token (JWT) authentication enabled; Connected Experiences apps and optional MDM for device rollout. |
| `splunk-dashboard-studio` | Shared baseline. | Search-head (or Cloud search-tier) REST access to `data/ui/views`; app/owner namespace and SPL for panels. |
| `splunk-kvstore-admin-setup` | Shared baseline; host `splunk` CLI for lifecycle operations (local or over SSH). | Search head / SHC admin access; `splunk login` on the host for backup/restore/clean/migrate/upgrade; REST access for collection and lookup-definition governance. |
| `splunk-cim-data-model-setup` | Shared baseline. | Splunk REST access; `Splunk_SA_CIM` installed or install handoff; index/sourcetype details for acceleration and CIM eventtype/tag mapping. |
| `splunk-knowledge-objects-setup` | Shared baseline. | Splunk REST access to the target app; role list for ACLs; CSV lookup placement on the search tier or via the lookup editor. |
| `splunk-ingest-actions-setup` | Shared baseline. | Splunk REST access with `edit_ingest_rulesets`; S3 bucket and access/secret key files for RFS routing; topology-appropriate ruleset deploy step. |
| `splunk-ddaa-archive-setup` | `acs`. | Splunk Cloud stack with DDAA enabled; ACS stack permissions; searchable vs archival retention plan (archival > searchable, <= 3650 days). |
| `splunk-secure-gateway-setup` | Shared baseline; `nc` or `curl` for egress checks. | Splunk REST access to enable/disable the app; outbound 443 to the Spacebridge host; MDM provider for fleet device registration. |
| `splunk-dashboard-studio-setup` | Shared baseline. | Splunk REST access to `data/ui/views` in the target app; dashboard JSON or search details; role list for ACLs. |
| `splunk-indexer-cluster-setup` | `ssh`, `scp`, `sudo`; `curl`. | Cluster manager/peer/search head admin access; bundle apply and rolling-restart authority. |
| `splunk-search-head-cluster-setup` | `ssh`, `scp`, `sudo`; `curl`; `python3`. | Deployer and all SHC member admin access; SHC shared secret file; rolling-restart authority; KV Store reset acceptance if needed. |
| `splunk-deployment-server-setup` | `ssh`, `rsync`, `curl`; `python3`. | Splunk Enterprise admin access on DS host; `phoneHome` tuning authority; HA pair networking if applicable. |
| `splunk-itsi-config` | `PyYAML`; optional `ssh`, `scp`, and `sshpass` for content/file staging. | ITSI REST access; `SA-ITOA` and content-pack readiness; native object specs and ownership lookups. |
| `splunk-itsi-setup` | Shared baseline. | Splunk app workflow access; ITSI package/Splunkbase entitlement and license readiness. |
| `splunk-license-manager-setup` | `curl`; optional SSH/file-copy tooling for license file placement. | Splunk Enterprise license manager and peer admin access; license file(s) available locally. |
| `splunk-mcp-server-setup` | `node`, `npm`/`npx`, `mcp-remote`; `codex` for Codex registration. | Splunk MCP Server app package/install access; Splunk bearer token file or token-minting permissions; target MCP clients. |
| `splunk-monitoring-console-setup` | Shared baseline. | Splunk Enterprise Monitoring Console and peer REST access; distributed mode peer/group details. |
| `splunk-platform-restart-orchestrator` | Shared baseline; optional `acs`, `ssh`, `sshpass`, `systemctl`, and noninteractive `sudo` depending on target topology. | Splunk Cloud ACS or Splunk Enterprise management access; host-local restart/reload authority or an operator handoff path; target role/topology details. |
| `splunk-platform-pki-setup` | `openssl`, `jq`; optional `ssh`, `scp`, and `sudo` for distribution/rotation handoffs. | Private CA or public CSR workflow inputs; per-component hostname/SAN inventory; Vault/AD CS/EJBCA/ACME handoffs when used. |
| `splunk-workload-management-setup` | `systemctl` for local Linux readiness checks. | Splunk Enterprise workload-management capable hosts; Linux cgroup/systemd prerequisites; pool/rule/admission plan. |
