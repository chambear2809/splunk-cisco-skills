# Enterprise 10.6 conditional review

Review date: 2026-10-07. Scope: the 42 skills marked `conditional` in
`SPLUNK_ENTERPRISE_10_6_COMPATIBILITY.md` (matrix evidence date 2026-10-05).
This report is evidence and an action queue; it does not promote metadata.

## Evidence rules

`E` means the exact selected package has explicit Enterprise 10.6 evidence in
the repository's Splunkbase registry snapshot. `U` means the package or
platform path remains unverified for 10.6. A public newer release, a package
listing without a 10.6 compatibility claim, or a product-level claim does not
qualify a different pinned release. Every `U` row needs the next validation
listed before promotion. “Prerequisite” means access, license, entitlement, or
topology evidence; it is not vendor compatibility evidence.

Source keys (all accessed 2026-10-07):

- **M** — repository matrix and selected package registry snapshots:
  `SPLUNK_ENTERPRISE_10_6_COMPATIBILITY.md`,
  `skills/shared/app_registry.json`, and the relevant skill `SKILL.md`.
- **S** — [Splunk Enterprise 10.6 welcome/release notes](https://help.splunk.com/en/splunk-enterprise/release-notes-and-updates/release-notes/10.6/whats-new/welcome-to-splunk-enterprise-10.6), including the four-part version format and co-hosted PostgreSQL-backed KV Store.
- **C** — [Splunk product compatibility matrix](https://help.splunk.com/en/splunk-enterprise/release-notes-and-updates/compatibility-matrix/splunk-products-version-compatibility/splunk-products-version-compatibility-matrix).
- **U** — [Splunk Enterprise 10.6 upgrade guidance](https://help.splunk.com/en/splunk-enterprise/get-started/install-and-upgrade/10.6/upgrade-or-migrate-splunk-enterprise/how-to-upgrade-splunk-enterprise), including upgrade-path and deployment prerequisites.

## Review table

| Skill | Exact selected package(s) | 10.6 finding | Dependency / next validation | Source/date |
|---|---|---|---|---|
| `cisco-cloud-control-setup` | No fixed package pin; Cisco Cloud Control API workflow | U; no public exact-package evidence | Confirm Cisco Cloud Control API release and Splunk Enterprise 10.6 support; run read-only API and ingest smoke test | M, S, 2026-10-07 |
| `cisco-data-fabric-setup` | No standalone package pin; Cisco Data Fabric handoff | U; product architecture is not package evidence | Obtain Cisco Data Fabric release matrix and validate the selected connector/TA against 10.6 | M, C, 2026-10-07 |
| `cisco-secure-access-setup` | `5558` `cisco-cloud-security` 1.0.57; `7569` `TA-cisco-cloud-security-addon` 1.0.53 | E for 5558; U for 7569 | Install both exact packages together, verify add-on macros/lookups and event search on 10.6 | M, C, 2026-10-07 |
| `widefield-splunk-siem-setup` | No fixed package pin; Widefield SIEM integration | U; no public exact-package evidence | Identify the selected SIEM connector package and obtain its vendor compatibility statement; validate CIM/event mapping | M, C, 2026-10-07 |
| `splunk-enterprise-security-config` | ES dependency `263` `SplunkEnterpriseSecuritySuite` 8.5.1; optional content package `3449` 6.4.0 | U for this configuration workflow; dependencies are E | Validate ES 8.5.1 configuration APIs, content dependencies, and upgrade behavior on Enterprise 10.6 | M, S, U, 2026-10-07 |
| `splunk-fraud-analytics-setup` | Operator-supplied Fraud Analytics `.tgz`; no pinned registry package | U; package is deployment input | Record exact Fraud Analytics package/build and ES version, then run package install and data-model readiness on 10.6 | M, U, 2026-10-07 |
| `splunk-uba-setup` | `4147` `Splunk-UBA-SA-Kafka` 1.4.6 | U; package lists no explicit 10.6 support | Obtain UBA 1.4.6 support statement or a newer exact pin; validate Kafka/ES dependencies and ingestion on 10.6 | M, C, 2026-10-07 |
| `splunk-ai-ml-toolkit-setup` | `2890` MLTK 6.0.2; `4607` mltk-container 5.2.4; `6843` Anomaly Detection 1.1.2; `2884` Linux x86 1.3; `6415` Smart Alerts Assistant 0.1.20; PSC 4.3.4 platform variants | E for MLTK/container/PSC x86_64 and macOS arm64; U for 6843, 2884, 6415 | Validate all nine selected artifacts as a tested set; especially PSC architecture and Python/runtime compatibility | M, C, 2026-10-07 |
| `splunk-amazon-kinesis-firehose-setup` | No fixed package pin; HEC/Firehose service path | U; no exact package evidence | Confirm Enterprise 10.6 HEC and Firehose integration support; run signed delivery and search readback | M, S, 2026-10-07 |
| `splunk-gcp-ta-setup` | `3088` `Splunk_TA_google-cloudplatform`; version not pinned by current skill | U; no exact selected release evidence | Pin a concrete TA release, verify its Splunkbase 10.6 claim, and validate Pub/Sub ingestion and dashboards | M, C, 2026-10-07 |
| `splunk-github-ta-setup` | `6254` `Splunk_TA_github` 4.0.0 | U; package lists no explicit 10.6 support | Obtain 4.0.0 vendor compatibility evidence or pin a supported release; validate API collection, CIM, and shipped views | M, C, 2026-10-07 |
| `splunk-cyberark-ta-setup` | `5160` `Splunk_TA_cyberark_epm` 5.0.0; archived `2891` `Splunk_TA_cyberark` 1.2.0 | E for 2891; U for 5160 | Confirm CyberArk EPM 5.0.0 support and API/runtime prerequisites; validate CEF parsing and dashboards on 10.6 | M, C, 2026-10-07 |
| `splunk-ingest-processor-setup` | No fixed package pin; Splunk Ingest Processor service | U; service compatibility is not package evidence | Confirm tenant/ACS support for Enterprise 10.6 and run HEC/metrics routing readback | M, S, 2026-10-07 |
| `splunk-cloud-data-manager-setup` | No fixed package pin; Cloud Data Manager service | U; no exact package evidence | Confirm C2C/Cloud Data Manager support for 10.6 and validate a non-production routing plan | M, S, 2026-10-07 |
| `splunk-agent-management-setup` | No fixed package pin; Splunk Agent Management control plane | U; no exact package evidence | Confirm agent policy and UF/OTel version matrix for Enterprise 10.6; validate enrollment and policy readback | M, C, 2026-10-07 |
| `splunk-workload-management-setup` | No fixed package pin; Enterprise workload-management configuration | U; feature path lacks exact 10.6 evidence | Validate REST/config endpoint behavior and scheduler/indexer enforcement on a 10.6 lab | M, S, 2026-10-07 |
| `splunk-platform-restart-orchestrator` | No package; platform CLI/API workflow | U; no package claim | Verify 10.6 restart sequencing and health endpoints against upgrade guidance; use plan-only validation first | M, U, 2026-10-07 |
| `splunk-connect-for-otlp-setup` | `8704` `splunk-connect-for-otlp` 0.4.1 | U; package lists no explicit 10.6 support | Obtain package support statement and validate OTLP receiver, HEC export, and dashboards on 10.6 | M, C, 2026-10-07 |
| `splunk-federated-search-setup` | No package; Enterprise Federated Search feature | U for this workflow; 10.6 has a material remote-peer requirement | Upgrade all remote search heads to Enterprise >=10.4, then validate capability exchange and a federated query on 10.6 | M, S, U, 2026-10-07 |
| `splunk-index-lifecycle-smartstore-setup` | No package; SmartStore/index configuration | U; no exact workflow evidence | Validate 10.6 index lifecycle and SmartStore behavior, including co-hosted KV Store upgrade impact, on a disposable cluster | M, S, U, 2026-10-07 |
| `splunk-knowledge-objects-setup` | No package; native knowledge-object REST/config workflow | U; no exact 10.6 workflow evidence | Validate object export/import, macro replication, and permission behavior on Enterprise 10.6 | M, S, U, 2026-10-07 |
| `splunk-ingest-actions-setup` | No fixed package pin; native ingest actions | U; no exact package evidence | Validate action endpoint/schema and HEC/index routing on 10.6 with a canary event | M, S, 2026-10-07 |
| `splunk-ddaa-archive-setup` | No fixed package pin; DDAA archive service/workflow | U; no exact package evidence | Confirm 10.6 archive API and supported storage path; perform archive and restore-readback test | M, S, U, 2026-10-07 |
| `splunk-secure-gateway-setup` | No fixed package pin; Secure Gateway service | U; no exact package evidence | Confirm Enterprise 10.6 Secure Gateway pairing/ACS support and validate registration/readback | M, S, 2026-10-07 |
| `splunk-dashboard-studio-setup` | No package; native Dashboard Studio | U; 10.6 removed Analytics Workspace, which may affect legacy panels | Validate Dashboard Studio v2 rendering and migration of any affected classic dashboards on 10.6 | M, S, 2026-10-07 |
| `splunk-monitoring-console-setup` | No package; native Monitoring Console | U; no exact 10.6 workflow evidence | Validate MC distributed-health checks and version-specific panels on 10.6 | M, S, 2026-10-07 |
| `splunk-observability-ai-agent-monitoring-setup` | No fixed package pin; Observability AI Agent Monitoring service/packages | U; no exact Enterprise package evidence | Confirm supported Splunk platform export path and validate OTLP/HEC telemetry plus UI readback | M, C, 2026-10-07 |
| `splunk-observability-cloud-integration-setup` | `5247` `Splunk_TA_sim` 1.3.1; archived `5608` `splunk_synthetic_monitoring` 1.1.0 | E for 5247; U for 5608 | Confirm whether 5608 is required; if so obtain replacement/support evidence and validate both package paths | M, C, 2026-10-07 |
| `galileo-platform-setup` | No fixed package pin; Galileo platform/API workflow | U; no exact Enterprise package evidence | Confirm Galileo release and HEC/OTLP compatibility with Enterprise 10.6; validate a canary trace/log | M, C, 2026-10-07 |
| `splunk-oncall-setup` | `3546` victorops_app 1.0.43; `4886` TA 2.1.0; `5863` splunkoncall 3.0.0 | E for 3546/4886; U for 5863 (SOAR connector) | Confirm whether 5863 is in scope; validate alert action, adaptive response, and connector separately | M, C, 2026-10-07 |
| `splunk-stream-windows-setup` | Stream app/TA 8.1.6; Windows forwarder package version is input | U; no exact 10.6 package evidence for this Windows path | Validate Stream 8.1.6 with the selected UF/Windows build on Enterprise 10.6, including Npcap and indexed canary | M, C, 2026-10-07 |
| `splunk-connect-for-syslog-setup` | No Splunkbase package; SC4S container/image release is an input | U; no exact image pin evidence | Pin SC4S image and Splunk Connect/OpenTelemetry versions, then run syslog-to-index canary on 10.6 | M, C, 2026-10-07 |
| `splunk-connect-for-snmp-setup` | No Splunkbase package; SC4SNMP container/image release is an input | U; no exact image pin evidence | Pin SC4SNMP image and collector versions, then validate trap ingestion and CIM mapping on 10.6 | M, C, 2026-10-07 |
| `splunk-license-manager-setup` | No package; native License Manager workflow | U; no exact 10.6 workflow evidence | Validate license peer behavior, usage reporting, and version skew rules on Enterprise 10.6 | M, S, 2026-10-07 |
| `splunk-edge-processor-setup` | No fixed package pin; Edge Processor service | U; 10.6 adds SPL2 pipeline functions but does not qualify this workflow | Confirm control-plane/runtime compatibility and validate a pipeline with 10.6-supported functions | M, S, 2026-10-07 |
| `splunk-indexer-cluster-setup` | No package; native indexer-cluster workflow | U; no exact 10.6 workflow evidence | Validate cluster bootstrap, RF/SF, rolling upgrade, and searchable canary on 10.6 | M, S, U, 2026-10-07 |
| `splunk-search-head-cluster-setup` | No package; native SHC workflow | U; 10.6 KV Store backend migration is material | Validate SHC captain election, KV Store migration/health, deployer bundle, and search readback on 10.6 | M, S, U, 2026-10-07 |
| `splunk-deployment-server-setup` | No package; native Deployment Server workflow | U; no exact 10.6 workflow evidence | Validate client enrollment, app deployment, and reload behavior on 10.6 | M, S, 2026-10-07 |
| `splunk-cloud-acs-admin-setup` | No package; ACS API workflow | U for self-managed Enterprise; Cloud-only path | Confirm target is Splunk Cloud rather than self-managed Enterprise; do not transfer Cloud evidence to 10.6 | M, C, 2026-10-07 |
| `splunk-cloud-acs-allowlist-setup` | No package; ACS allowlist API workflow | U for self-managed Enterprise; Cloud-only path | Confirm Cloud tenant/ACS entitlement and separately validate Cloud version; not an Enterprise 10.6 promotion | M, C, 2026-10-07 |
| `splunk-enterprise-public-exposure-hardening` | Optional `3172` ssl_certificate_checker 4.2.0; optional `4603` Splunk Health Assistant 2026.5.23 | U for 3172; E for 4603; hardening logic itself is not package evidence | Validate 10.6 TLS/cipher behavior, exposed endpoints, and optional package compatibility on a lab host | M, S, U, 2026-10-07 |
| `splunk-platform-pki-setup` | Optional `3172` ssl_certificate_checker 4.2.0; `4603` health assistant 2026.5.23 | U for 3172; E for 4603 | Validate certificate checker against 10.6 TLS 1.3/KV Store requirements and confirm health-assistant placement | M, S, U, 2026-10-07 |

## Promotion gate

Promote a row only after the exact selected package/image/service release has a
public vendor compatibility statement or a reproducible vendor-supported lab
result tied to Enterprise 10.6. Record package checksum, platform/OS,
architecture, dependency versions, and the canary/readback result. License,
tenant, entitlement, network, and credentials remain separate prerequisites and
must not be used as substitutes for compatibility evidence.
