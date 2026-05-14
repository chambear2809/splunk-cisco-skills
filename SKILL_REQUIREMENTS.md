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

## Cisco Product And App Setup

| Skill | Additional local tooling | Live access and product requirements |
| --- | --- | --- |
| `cisco-appdynamics-setup` | Shared baseline. | Splunk app workflow access; AppDynamics controller and analytics endpoint details; controller credentials/client secrets in files. |
| `cisco-catalyst-enhanced-netflow-setup` | Shared baseline; Splunk Stream placement awareness. | Splunk app workflow access; existing Stream/IPFIX/HSL collection path and Catalyst data prerequisites. |
| `cisco-catalyst-ta-setup` | Shared baseline. | Splunk app workflow access; Catalyst Center, ISE, SD-WAN, or Cyber Vision host/account details; device/API secrets in files. |
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

## Splunk Observability

| Skill | Additional local tooling | Live access and product requirements |
| --- | --- | --- |
| `splunk-observability-ai-agent-monitoring-setup` | `PyYAML`; `kubectl` for Kubernetes runtime apply paths. | Splunk Observability realm and token files; GenAI application/runtime details; optional HEC/Log Observer Connect handoffs. |
| `splunk-observability-aws-integration` | `aws`; optional `terraform`; `curl`. | Authenticated AWS CLI profile/session; Splunk Observability admin/user token files; AWS account/organization permissions for CloudWatch and Metric Streams. |
| `splunk-observability-cisco-ai-pod-integration` | `kubectl` or `oc`, `helm`, `yq`; child-skill tools for Nexus, Intersight, NVIDIA, and OTel collector handoffs. | Splunk Observability token files; Cisco AI Pod cluster access; UCS/Nexus/NVIDIA/NIM/vLLM/storage endpoint details. |
| `splunk-observability-cisco-intersight-integration` | `kubectl` or `oc`; optional `helm`, `jq`, `yq`, `openssl`, `nc` for live checks and troubleshooting. | Splunk Observability token files; Kubernetes namespace access; Intersight API credentials in a Kubernetes Secret. |
| `splunk-observability-cisco-nexus-integration` | `kubectl`, `helm`, `yq`; optional `ssh` and `nc` for device checks. | Splunk Observability token files; Nexus/NX-OS device SSH credentials via Kubernetes Secret; collector cluster access. |
| `splunk-observability-cloud-integration-setup` | `acs`, `curl`, `openssl`; optional `docker` for companion local checks. | Splunk Cloud/Enterprise REST access; Splunk Observability admin/org/user token files; Log Observer Connect and SIM add-on prerequisites. |
| `splunk-observability-dashboard-builder` | `PyYAML` for YAML specs. | Splunk Observability API token file with dashboard permissions; target realm/org. |
| `splunk-observability-database-monitoring-setup` | `kubectl`, `helm`; `PyYAML`. | Splunk Observability token files; database endpoint details; DB credentials in Kubernetes Secrets or local secret files. |
| `splunk-observability-isovalent-integration` | `kubectl` or `oc`, `helm`, `yq`; optional `jq` and `aws`. | Splunk Observability token files; installed Cilium/Tetragon/Hubble stack; optional Splunk HEC token/index for Tetragon logs. |
| `splunk-observability-k8s-auto-instrumentation-setup` | `kubectl`, `helm`; optional `npm` for app/runtime helper snippets. | Splunk Observability token files; OpenTelemetry Operator or Splunk OBI readiness; target workload namespaces. |
| `splunk-observability-k8s-frontend-rum-setup` | `kubectl`; `npm` and `splunk-rum` for source-map helpers. | Splunk RUM token file; Splunk Observability token file for source maps; target frontend workload/ingress access. |
| `splunk-observability-native-ops` | `PyYAML` for YAML specs. | Splunk Observability API token file with detector, alert-routing, synthetics, APM, RUM, or logs permissions; optional On-Call handoff. |
| `splunk-observability-nvidia-gpu-integration` | `kubectl`, `helm`, `yq`. | Splunk Observability token files; NVIDIA GPU Operator or DCGM Exporter in the target cluster. |
| `splunk-observability-otel-collector-setup` | `kubectl` and `helm` for Kubernetes; `ssh`, `scp`, `systemctl`, and `sudo` for Linux host apply; optional `npm` for generated helpers. | Splunk Observability realm/token files; target Kubernetes cluster or Linux host access; optional Splunk HEC token file for platform log export. |
| `splunk-observability-thousandeyes-integration` | `curl`, optional `jq`; `codex` only for MCP/client handoff snippets. | ThousandEyes OAuth/API credentials in files; Splunk Observability token files; TE test/stream/template permissions. |

## Splunk Platform Operations

| Skill | Additional local tooling | Live access and product requirements |
| --- | --- | --- |
| `splunk-admin-doctor` | `acs` for Cloud checks; optional `ssh`; `curl`. | Splunk Cloud ACS or Enterprise REST access; admin-domain permissions for the areas being diagnosed. |
| `splunk-agent-management-setup` | Shared baseline. | Splunk Enterprise deployment server or deployment-app file target access; server class/app ownership details. |
| `splunk-ai-assistant-setup` | Shared baseline. | Splunk app workflow access; Splunk AI Assistant entitlement and activation/onboarding details. |
| `splunk-app-install` | `acs`; optional `ssh`, `scp`, and `sshpass` for Enterprise remote staging. | Splunk Enterprise REST or Splunk Cloud ACS access; Splunkbase credentials or local package path. |
| `splunk-cloud-acs-allowlist-setup` | `acs`; optional `terraform`; `curl` for source-IP discovery. | Splunk Cloud ACS stack permissions; exact allowlist feature/subnet plan; lock-out protection review. |
| `splunk-cloud-data-manager-setup` | `aws`, `az`, `gcloud`, and `terraform` only for the cloud artifact families being validated/applied. | Data Manager-generated CloudFormation/ARM/Terraform artifacts; cloud-provider permissions; HEC/index prerequisites. |
| `splunk-edge-processor-setup` | `docker` for local/container handoffs; `systemctl` for Linux service paths. | Splunk Cloud or Enterprise Edge Processor control-plane access; EP instance host permissions. |
| `splunk-enterprise-host-setup` | `ssh`, `sudo`; package checksum tools from the host OS. | Target Linux hosts; Splunk Enterprise package access; role/topology settings for search/indexer/HF/cluster membership. |
| `splunk-enterprise-kubernetes-setup` | `kubectl`, `helm`; `aws` for optional EKS kubeconfig helper. | Kubernetes cluster access; Splunk Operator for Kubernetes or Splunk POD installer/bastion access. |
| `splunk-enterprise-public-exposure-hardening` | `openssl`, `nc`, `curl`; optional `aws`/ACS/firewall/WAF handoff tools. | On-prem Splunk Enterprise admin access; reverse proxy/firewall/WAF ownership; explicit public-exposure acceptance. |
| `splunk-federated-search-setup` | `PyYAML`; `curl`. | Splunk Enterprise REST access for federated provider/index configuration; remote provider details and credentials files. |
| `splunk-hec-service-setup` | Shared baseline. | Splunk Enterprise REST or Splunk Cloud ACS access; HEC index/token naming plan; HEC receiver URL decisions. |
| `splunk-index-lifecycle-smartstore-setup` | Shared baseline. | Splunk Enterprise indexer or cluster-manager access; object store bucket/remote volume details and credentials handoff. |
| `splunk-indexer-cluster-setup` | `ssh`, `scp`, `sudo`; `curl`. | Cluster manager/peer/search head admin access; bundle apply and rolling-restart authority. |
| `splunk-itsi-config` | `PyYAML`; optional `ssh`, `scp`, and `sshpass` for content/file staging. | ITSI REST access; `SA-ITOA` and content-pack readiness; native object specs and ownership lookups. |
| `splunk-itsi-setup` | Shared baseline. | Splunk app workflow access; ITSI package/Splunkbase entitlement and license readiness. |
| `splunk-license-manager-setup` | `curl`; optional SSH/file-copy tooling for license file placement. | Splunk Enterprise license manager and peer admin access; license file(s) available locally. |
| `splunk-mcp-server-setup` | `node`, `npm`/`npx`, `mcp-remote`; `codex` for Codex registration. | Splunk MCP Server app package/install access; Splunk bearer token file or token-minting permissions; target MCP clients. |
| `splunk-monitoring-console-setup` | Shared baseline. | Splunk Enterprise Monitoring Console and peer REST access; distributed mode peer/group details. |
| `splunk-platform-restart-orchestrator` | Shared baseline; optional `acs`, `ssh`, `sshpass`, `systemctl`, and noninteractive `sudo` depending on target topology. | Splunk Cloud ACS or Splunk Enterprise management access; host-local restart/reload authority or an operator handoff path; target role/topology details. |
| `splunk-platform-pki-setup` | `openssl`, `jq`; optional `ssh`, `scp`, and `sudo` for distribution/rotation handoffs. | Private CA or public CSR workflow inputs; per-component hostname/SAN inventory; Vault/AD CS/EJBCA/ACME handoffs when used. |
| `splunk-workload-management-setup` | `systemctl` for local Linux readiness checks. | Splunk Enterprise workload-management capable hosts; Linux cgroup/systemd prerequisites; pool/rule/admission plan. |
