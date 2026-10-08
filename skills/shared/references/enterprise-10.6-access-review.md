# Enterprise 10.6 integration prerequisite review

Review date: 2026-10-07. This is an access and prerequisite inventory for all
108 applicable Enterprise 10.6 workflows (supported, conditional, delegated,
and blocked). It does not promote compatibility metadata or change the
validation ledger. Package availability in the local registry is recorded
separately from proof that a tenant, endpoint, license, hardware platform, or
ingest path is available.

Evidence keys:

- **Package: available** means an exact package or image is named in the
  tracked registry snapshot. This is metadata, not proof of a downloaded binary. **Package: missing pin** means the workflow takes
  an operator-supplied release or is a service/native feature.
- **Access: unproven** means this repository contains no non-secret proof of
  the external endpoint, tenant, entitlement, hardware, or configured ingest
  path. It is not a claim that the product is unavailable.
- A TA or dashboard companion remains incomplete until its input is enabled,
  events land in the expected index/sourcetype, and shipped dashboards (if any)
  are visible, macro-aligned, and returning data. This follows
  `skills/shared/ta_completion_gate.md`.

| Workflow | External endpoint / tenant | License, entitlement, or hardware | Evidence available vs missing | Impact, owner, next action |
|---|---|---|---|---|
| `cisco-cloud-control-setup` | Cisco Cloud Control API URL and tenant | Cisco Cloud Control activation | Package: missing pin; endpoint/tenant evidence unproven | Cisco platform owner: identify release and tenant, then run read-only API and ingest smoke test. |
| `cisco-data-fabric-setup` | Data Fabric/control-plane and selected connector endpoint | Product stage and connector entitlement | Package: missing pin; connector and tenant evidence unproven | Data Fabric owner: select connector release and obtain 10.6 support statement before validation. |
| `cisco-secure-access-setup` | Secure Access tenant/API and event export endpoint | Secure Access subscription | Package 5558 available; companion 7569 available but exact 10.6 evidence is unproven; tenant/access unproven | Cisco security owner: configure both packages, prove account/input, ingest, macros/lookups, and dashboards. |
| `widefield-splunk-siem-setup` | Selected SIEM API/collector endpoint and tenant | WideField SIEM subscription | Package: missing pin; connector and CIM/event evidence unproven | WideField owner: identify connector package and vendor 10.6 statement, then validate event mapping. |
| `splunk-enterprise-security-config` | Local ES REST/config surfaces | ES entitlement; optional content package entitlement | ES package 263 and content 3449 are registry-available; entitlement and 10.6 workflow evidence unproven | Splunk security owner: confirm ES entitlement and validate APIs/content dependencies on 10.6. |
| `splunk-fraud-analytics-setup` | Fraud Analytics data sources and ES endpoints | Fraud Analytics package/build and ES entitlement | Package: operator-supplied; exact build, license, and ingest evidence missing | Fraud owner: record exact `.tgz` and ES version, install in lab, validate data model readiness. |
| `splunk-uba-setup` | UBA services, Kafka, and ES integration endpoints | UBA entitlement and Kafka capacity | Package 4147 available; 10.6 support and entitlement unproven | UBA owner: obtain support statement, confirm Kafka/ES prerequisites, validate ingestion. |
| `splunk-ai-ml-toolkit-setup` | Optional PSC/container/model endpoints | PSC/MLTK entitlement and architecture (x86/arm) | Core MLTK/container/PSC pins available; Anomaly Detection, Linux x86, Smart Alerts evidence incomplete | ML owner: validate the complete selected artifact set, architecture, Python/runtime, and model endpoint. |
| `splunk-amazon-kinesis-firehose-setup` | AWS Firehose delivery stream and Splunk HEC endpoint | AWS account/IAM and HEC authorization | Service path only; exact package and signed delivery evidence unproven | Ingest owner: confirm HEC/Firehose support, configure a canary stream, verify indexed events. |
| `splunk-gcp-ta-setup` | GCP project, Pub/Sub or API endpoint, service account | GCP IAM/project access | Package 3088 listed without a pinned version; credentials, project, and ingest evidence unproven | GCP owner: pin release, verify 10.6 support, configure Pub/Sub input, verify dashboards/data. |
| `splunk-github-ta-setup` | GitHub API URL/org/repository and token file | GitHub API scope/rate entitlement | Package 6254 available; 10.6 support, token, org, and ingest evidence unproven | GitHub owner: obtain support evidence, configure file-based token, validate API collection/CIM/views. |
| `splunk-cyberark-ta-setup` | CyberArk EPM/Vault API endpoint and tenant | CyberArk EPM/Vault license and API role | Archived package 2891 available; EPM 5160 available but 10.6 evidence unproven; tenant unproven | CyberArk owner: confirm EPM release/API role, validate CEF parsing and dashboards. |
| `splunk-ingest-processor-setup` | Ingest Processor tenant/control plane and HEC/metrics destination | Ingest Processor entitlement | Service path only; tenant/ACS access and routing proof unproven | Ingest owner: confirm tenant support and validate HEC/metrics routing with a canary. |
| `splunk-cloud-data-manager-setup` | Cloud Data Manager/C2C tenant and source endpoint | C2C/Data Manager entitlement | Service path only; tenant/source access and 10.6 support unproven | Cloud data owner: confirm tenant, prepare non-production routing plan, verify readback. |
| `splunk-agent-management-setup` | Agent Management control plane and enrollment endpoint | Agent policy entitlement; UF/OTel host capacity | Service path only; policy, enrollment, and version matrix unproven | Agent owner: confirm UF/OTel versions, enroll a canary, and verify policy telemetry. |
| `splunk-workload-management-setup` | Native Enterprise scheduler/indexer endpoints | Workload-management capability/license | Native workflow; 10.6 endpoint and enforcement evidence unproven | Platform owner: run plan-only validation, then prove scheduler/indexer enforcement in lab. |
| `splunk-platform-restart-orchestrator` | Native management/SSH/systemd endpoints | Host sudo/systemd access and maintenance window | Native workflow; 10.6 sequencing evidence is partial | Platform owner: validate plan-only sequencing and health endpoints before any restart. |
| `splunk-connect-for-otlp-setup` | OTLP receiver/export endpoint and HEC/OTLP destination | Collector host/container capacity | Package 8704 available; 10.6 support and telemetry destination evidence unproven | Observability owner: obtain support statement, validate receiver/export and dashboard data. |
| `splunk-federated-search-setup` | Remote search-head peers and federation endpoints | Remote peer admin/capability access | Native workflow; remote peers must be Enterprise >=10.4; peer evidence unproven | Search owner: upgrade/confirm remote peers, validate capability exchange and federated query. |
| `splunk-index-lifecycle-smartstore-setup` | Object-store endpoint/bucket and indexer cluster | S3-compatible IAM, storage capacity, SmartStore entitlement | Native workflow; bucket/IAM and disposable-cluster evidence unproven | Storage owner: validate lifecycle/SmartStore and KV Store interaction on a disposable cluster. |
| `splunk-knowledge-objects-setup` | Native REST/config endpoint | App namespace and role permissions | Native workflow; 10.6 compatibility now lab-tested for core objects, external access is target-specific | Platform owner: keep app/role evidence per target and run status/apply gates. |
| `splunk-ingest-actions-setup` | Native ingest-action endpoint and HEC/index target | Action capability and target permissions | Native workflow; endpoint/schema and canary evidence unproven | Ingest owner: validate action schema and one non-alerting canary event. |
| `splunk-ddaa-archive-setup` | DDAA archive service and object-storage path | Archive entitlement and storage/IAM | Service path only; endpoint, storage, and restore evidence unproven | Archive owner: confirm API/storage support, run archive and restore-readback test. |
| `splunk-secure-gateway-setup` | Secure Gateway control plane and pairing endpoint | Secure Gateway/ACS entitlement | Service path only; tenant pairing evidence unproven | Platform owner: confirm Cloud pairing entitlement and validate registration/readback. |
| `splunk-dashboard-studio-setup` | Native `data/ui/views` endpoint | App namespace and dashboard permissions | Native v2 path lab-tested; legacy Analytics Workspace migration evidence unproven | Dashboard owner: inventory affected classic panels and validate v2 rendering/migration. |
| `splunk-monitoring-console-setup` | Native MC REST/views and distributed peers | MC admin capability and peer access | Standalone MC apply/status, 111 shipped views and representative populated searches passed; distributed health pending | Platform owner: validate MC distributed-health panels on a host with peer access. |
| `splunk-observability-ai-agent-monitoring-setup` | Observability tenant/API and OTLP/HEC export | Observability subscription | Service/package path only; tenant/export evidence unproven | Observability owner: confirm export path and validate telemetry plus UI readback. |
| `splunk-observability-cloud-integration-setup` | Observability realm/API and Splunk integration endpoint | Observability subscription/token file | Package 5247 available; archived 5608 available but support/integration access unproven | Observability owner: determine whether 5608 is required, then validate supported path. |
| `galileo-platform-setup` | Galileo API/control plane and HEC/OTLP endpoint | Galileo subscription/tenant | Service path only; release and tenant evidence unproven | Galileo owner: record release, confirm export compatibility, validate canary trace/log. |
| `splunk-oncall-setup` | On-Call tenant/API and alert-action endpoint | On-Call subscription and integration token | Packages 3546/4886 available; 5863 available but connector support unproven; tenant unproven | On-Call owner: validate alert action and connector separately, without sending notifications. |
| `splunk-stream-windows-setup` | Windows host, Stream endpoints, and index target | Windows/UF version, Npcap, host capture permissions | Stream 8.1.6 package path; exact UF/Windows evidence unproven | Windows owner: pin host/UF versions, validate Npcap/capture and indexed canary. |
| `splunk-connect-for-syslog-setup` | Syslog listener, HEC/index endpoint | SC4S container host and image release | Container path only; image/version and listener evidence unproven | Syslog owner: pin image/collector versions and validate syslog-to-index canary. |
| `splunk-connect-for-snmp-setup` | SNMP trap receiver and HEC/index endpoint | SC4SNMP container host, SNMPv3 credentials, network reachability | Container path only; image/version and trap source evidence unproven | SNMP owner: pin image, use protected credential files, validate trap/CIM mapping. |
| `splunk-license-manager-setup` | Native license-manager peers | License pool/stack entitlement and peer admin access | Enterprise license install/remove, two pool quotas, peer enrollment and usage readback passed and persisted after restart | Platform owner: retain measured license/peer evidence; qualify any additional version-skew topologies separately. |
| `splunk-edge-processor-setup` | Edge Processor control plane and ingest route | Edge Processor entitlement and worker capacity | Service path only; control-plane/runtime evidence unproven | Ingest owner: confirm service support and validate a pipeline with 10.6-supported functions. |
| `splunk-indexer-cluster-setup` | Cluster manager/peer endpoints and replication network | Indexer hardware, RF/SF capacity, cluster admin access | Native workflow; 10.6 bootstrap/rolling-upgrade evidence unproven | Platform owner: validate bootstrap, RF/SF, rolling upgrade, and searchable canary. |
| `splunk-search-head-cluster-setup` | SHC captain/deployer endpoints and replication network | SHC host capacity/admin access; KV Store readiness | Native workflow; KV Store 10.6 migration is material and only core KV gates are proven | Platform owner: validate captain election, deployer bundle, KV migration/health, search readback. |
| `splunk-deployment-server-setup` | Deployment Server/client management endpoints | Client host access and app deployment permissions | Native workflow; enrollment/deployment evidence unproven | Platform owner: validate canary client enrollment, app deployment, and reload. |
| `splunk-cloud-acs-admin-setup` | ACS API and Cloud tenant | Cloud entitlement/admin role | Cloud-only native path; no Enterprise 10.6 applicability evidence | Cloud owner: validate only against a Cloud tenant; do not transfer to Enterprise. |
| `splunk-cloud-acs-allowlist-setup` | ACS allowlist API and Cloud tenant | Cloud ACS entitlement/admin role | Cloud-only native path; no Enterprise 10.6 applicability evidence | Cloud owner: confirm tenant and separately validate Cloud version. |
| `splunk-enterprise-public-exposure-hardening` | Host/network exposure and TLS endpoints | Host root/admin; optional package 3172/4603 | 4603 available; 3172 available but 10.6 evidence unproven; host exposure evidence missing | Security owner: validate TLS/ciphers/exposed endpoints and optional package placement. |
| `splunk-platform-pki-setup` | CA/issuer, host TLS endpoints, KV Store TLS | CA private material and host certificate permissions | 4603 available; 3172 available but 10.6 evidence unproven; CA/issuer evidence missing | Security owner: validate certificate checker against 10.6 TLS/KV requirements using file paths only. |


## Complete applicable workflow inventory

The ledger contains 108 applicable rows: 59 supported, 42 conditional, 6
delegated, and 1 blocked. The table below covers each row exactly once. The
external prerequisite column is intentionally conservative: unknown/unchecked
means that the repository did not verify a tenant, endpoint, entitlement, hardware,
or ingest path for that workflow. It does not convert a supported or delegated
row into a blocker. The detailed conditional rows above retain their
workflow-specific package and next-action notes.

| Workflow | Ledger compatibility | Functional status | External prerequisite evidence |
|---|---|---|---|
| cisco-product-setup | delegated | pending | unknown/unchecked |
| cisco-collaboration-setup | delegated | pending | unknown/unchecked |
| cisco-cloud-control-setup | conditional | pending | unknown/unchecked |
| cisco-data-fabric-setup | conditional | pending | unknown/unchecked |
| cisco-scan-setup | supported | pending | unknown/unchecked |
| cisco-catalyst-ta-setup | supported | pending | unknown/unchecked |
| cisco-catalyst-enhanced-netflow-setup | supported | pending | unknown/unchecked |
| cisco-appdynamics-setup | supported | pending | unknown/unchecked |
| splunk-appdynamics-setup | delegated | pending | unknown/unchecked |
| cisco-security-cloud-setup | supported | pending | unknown/unchecked |
| cisco-secure-access-setup | conditional | pending | unknown/unchecked |
| cisco-webex-setup | supported | pending | unknown/unchecked |
| cisco-ucs-ta-setup | supported | pending | unknown/unchecked |
| cisco-secure-email-web-gateway-setup | supported | pending | unknown/unchecked |
| cisco-asa-ta-setup | supported | pending | unknown/unchecked |
| cisco-talos-intelligence-setup | supported | pending | unknown/unchecked |
| cisco-spaces-setup | supported | pending | unknown/unchecked |
| cisco-dc-networking-setup | supported | pending | unknown/unchecked |
| cisco-intersight-setup | supported | pending | unknown/unchecked |
| cisco-meraki-ta-setup | supported | pending | unknown/unchecked |
| cisco-enterprise-networking-setup | supported | pending | unknown/unchecked |
| cisco-thousandeyes-setup | supported | pending | unknown/unchecked |
| widefield-security-setup | delegated | pending | unknown/unchecked |
| widefield-splunk-siem-setup | conditional | pending | unknown/unchecked |
| splunk-itsi-setup | supported | blocked | External blocker documented in ledger |
| splunk-itsi-config | supported | pending | unknown/unchecked |
| splunk-enterprise-security-install | supported | blocked | unknown/unchecked |
| splunk-enterprise-security-config | conditional | pending | unknown/unchecked |
| splunk-security-portfolio-setup | delegated | pending | unknown/unchecked |
| splunk-security-essentials-setup | supported | pending | unknown/unchecked |
| splunk-security-content-update-setup | supported | pending | unknown/unchecked |
| splunk-lookup-file-editing-setup | supported | pending | unknown/unchecked |
| splunk-infosec-app-setup | supported | pending | unknown/unchecked |
| splunk-pci-compliance-setup | supported | blocked | unknown/unchecked |
| splunk-fraud-analytics-setup | conditional | pending | unknown/unchecked |
| splunk-asset-risk-intelligence-setup | supported | blocked | unknown/unchecked |
| splunk-attack-analyzer-setup | supported | pending | unknown/unchecked |
| splunk-uba-setup | conditional | blocked | unknown/unchecked |
| splunk-ai-assistant-setup | supported | pending | unknown/unchecked |
| splunk-ai-ml-toolkit-setup | conditional | pending | unknown/unchecked |
| splunk-mcp-server-setup | supported | pending | unknown/unchecked |
| splunk-admin-doctor | supported | pass | See linked ledger evidence; remaining variants are qualified |
| splunk-data-source-readiness-doctor | supported | pass | See linked ledger evidence; remaining variants are qualified |
| splunk-supported-addons-setup | supported | pending | unknown/unchecked |
| splunk-windows-ta-setup | supported | pending | unknown/unchecked |
| splunk-microsoft-cloud-setup | supported | pending | unknown/unchecked |
| splunk-aws-ta-setup | supported | pending | unknown/unchecked |
| splunk-amazon-kinesis-firehose-setup | conditional | pending | unknown/unchecked |
| splunk-okta-ta-setup | supported | pending | unknown/unchecked |
| splunk-gcp-ta-setup | conditional | pending | unknown/unchecked |
| splunk-servicenow-ta-setup | supported | pending | unknown/unchecked |
| splunk-google-workspace-ta-setup | supported | pending | unknown/unchecked |
| splunk-microsoft-security-ta-setup | supported | pending | unknown/unchecked |
| splunk-microsoft-exchange-ta-setup | supported | pending | unknown/unchecked |
| splunk-microsoft-scom-ta-setup | supported | pending | unknown/unchecked |
| splunk-sysmon-ta-setup | supported | pending | unknown/unchecked |
| splunk-github-ta-setup | conditional | pending | unknown/unchecked |
| splunk-salesforce-ta-setup | supported | pending | unknown/unchecked |
| splunk-box-ta-setup | supported | pending | unknown/unchecked |
| splunk-cyberark-ta-setup | conditional | pending | unknown/unchecked |
| splunk-rsa-securid-ta-setup | supported | pending | unknown/unchecked |
| splunk-security-appliance-ta-setup | supported | pending | unknown/unchecked |
| splunk-syslog-web-proxy-ta-setup | supported | pending | unknown/unchecked |
| splunk-vmware-ta-setup | supported | pending | unknown/unchecked |
| splunk-database-ta-setup | supported | pending | unknown/unchecked |
| splunk-netapp-ontap-ta-setup | supported | pending | unknown/unchecked |
| splunk-ingest-processor-setup | conditional | pending | unknown/unchecked |
| splunk-cloud-data-manager-setup | conditional | pending | unknown/unchecked |
| splunk-db-connect-setup | supported | pending | unknown/unchecked |
| splunk-app-install | supported | pass | See linked ledger evidence; remaining variants are qualified |
| splunk-universal-forwarder-setup | supported | pass | See linked ledger evidence; remaining variants are qualified |
| splunk-agent-management-setup | conditional | pending | unknown/unchecked |
| splunk-workload-management-setup | conditional | pending | unknown/unchecked |
| splunk-hec-service-setup | supported | pass | See linked ledger evidence; remaining variants are qualified |
| splunk-platform-restart-orchestrator | conditional | pending | unknown/unchecked |
| splunk-connect-for-otlp-setup | conditional | pending | unknown/unchecked |
| splunk-federated-search-setup | conditional | pending | unknown/unchecked |
| splunk-index-lifecycle-smartstore-setup | conditional | pending | unknown/unchecked |
| splunk-kvstore-admin-setup | supported | partial | See linked ledger evidence; remaining variants are qualified |
| splunk-cim-data-model-setup | supported | pending | unknown/unchecked |
| splunk-knowledge-objects-setup | conditional | pass | See linked ledger evidence; remaining variants are qualified |
| splunk-ingest-actions-setup | conditional | pending | unknown/unchecked |
| splunk-ddaa-archive-setup | conditional | pending | unknown/unchecked |
| splunk-secure-gateway-setup | conditional | pending | unknown/unchecked |
| splunk-dashboard-studio-setup | conditional | pass | See linked ledger evidence; remaining variants are qualified |
| splunk-monitoring-console-setup | conditional | pass | See linked ledger evidence; remaining variants are qualified |
| splunk-enterprise-host-setup | supported | pass | See linked ledger evidence; remaining variants are qualified |
| splunk-enterprise-kubernetes-setup | blocked | partial | See linked ledger evidence; remaining variants are qualified |
| splunk-observability-otel-collector-setup | supported | pending | unknown/unchecked |
| splunk-observability-ai-agent-monitoring-setup | conditional | pending | unknown/unchecked |
| splunk-observability-coding-agent-instrumentation-setup | delegated | pending | unknown/unchecked |
| splunk-observability-cloud-integration-setup | conditional | pending | unknown/unchecked |
| galileo-platform-setup | conditional | pending | unknown/unchecked |
| splunk-oncall-setup | conditional | pending | unknown/unchecked |
| splunk-stream-setup | supported | pending | unknown/unchecked |
| splunk-stream-windows-setup | conditional | pending | unknown/unchecked |
| splunk-connect-for-syslog-setup | conditional | pending | unknown/unchecked |
| splunk-connect-for-snmp-setup | conditional | pending | unknown/unchecked |
| splunk-license-manager-setup | conditional | pass | unknown/unchecked |
| splunk-soar-setup | supported | pending | unknown/unchecked |
| splunk-edge-processor-setup | conditional | pending | unknown/unchecked |
| splunk-indexer-cluster-setup | conditional | pending | unknown/unchecked |
| splunk-search-head-cluster-setup | conditional | pending | unknown/unchecked |
| splunk-deployment-server-setup | conditional | pending | unknown/unchecked |
| splunk-cloud-acs-admin-setup | conditional | pending | unknown/unchecked |
| splunk-cloud-acs-allowlist-setup | conditional | pending | unknown/unchecked |
| splunk-enterprise-public-exposure-hardening | conditional | pending | unknown/unchecked |
| splunk-platform-pki-setup | conditional | partial | See linked ledger evidence; remaining variants are qualified |

## Verified access blockers and boundaries

## Observed access evidence

- The project `credentials` file exists with mode 0600. Its key-name inventory
  includes Splunk Enterprise, ACS, Observability, Galileo, AppDynamics, and
  Cloud/stack fields; values were not read into this review.
- The protected lab file
  `/tmp/splunk106-validation-20261007-113722/secondary-access/target-credentials`
  exists with mode 0600 and contains the Splunk host, search URI, platform,
  home, TLS, and CA-certificate fields needed by the validated Enterprise
  10.6 lab. This proves access to that lab target only.
- The lab target and the legacy 10.4.3 host have independent validation
  evidence in the KV/core artifacts; that evidence is not generalized to
  vendor tenants, Cloud tenants, or external products.

Only the following external credential prerequisites were observed missing.
This is based on field-name and path-presence checks; no secret values were
read or recorded.

| Affected workflow(s) | Source and missing prerequisite | Verification | Next action |
|---|---|---|---|
| splunk-observability-ai-agent-monitoring-setup, splunk-observability-cloud-integration-setup | credentials:SPLUNK_O11Y_TOKEN_FILE | Field exists in credentials, but its configured file path does not exist (Path.exists=False) | Observability owner supplies a protected token file, then proves tenant/export and UI readback. |
| galileo-platform-setup | credentials:GALILEO_API_KEY_FILE | pending | unknown/unchecked |
| cisco-appdynamics-setup, splunk-appdynamics-setup | credentials:APPD_CLIENT_SECRET_FILE | Field exists in credentials, but its configured file path does not exist (Path.exists=False) | AppDynamics owner supplies a protected client-secret file, then proves controller/account access. |
| splunk-oncall-setup | Required On-Call fields SPLUNK_ONCALL_API_ID, SPLUNK_ONCALL_API_KEY_FILE, and SPLUNK_ONCALL_REST_INTEGRATION_KEY_FILE | pending | unknown/unchecked |

The blocked ledger row splunk-enterprise-kubernetes-setup remains a product
and hardware gate, not a claim that a credential is missing: its ledger entry
requires a dedicated supported Enterprise 10.6.0.5 lab and available product
dependencies, while the recorded evidence is an older isolated Enterprise
10.4.1/SOK run. No newer Cisco UCS or SOK/POD dependency evidence was observed.
This is a compatibility evidence gap, not a blanket access blocker.


## Promotion and ownership rule

An unavailable prerequisite blocks only the affected integration workflow. It
does not block native core Enterprise validation or an AWS workflow that has
independent access evidence. Package presence is also insufficient: the owner
must record the external endpoint/tenant, entitlement or hardware prerequisite,
file-based credential path, enabled input, indexed canary, and dashboard
readback where applicable. Never record secret values in this review.
