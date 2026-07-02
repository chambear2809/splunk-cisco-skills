# Splunk Admin Doctor Reference

The doctor uses `scripts/doctor.py` as the source of truth for:

- `COVERAGE_MANIFEST`: every admin domain and platform applicability.
- `RULE_CATALOG`: every rule, with required fields:
  `id`, `domain`, `platform`, `severity`, `evidence`, `source_doc`,
  `fix_kind`, `preview_command`, `apply_command`, `handoff_skill`, and
  `rollback_or_validation`.
- `validate_catalog()`: structural checks that fail tests when a domain lacks
  a rule or a delegated/manual/diagnose route, when declared coverage differs
  from applicable rules, when a handoff is missing, or when any repository
  skill lacks a disposition.
- `PRODUCT_ROUTE_CATALOG`: product/app aliases and precise specialist routers.
- `CANONICAL_SKILL_ALIASES`: compatibility workflows that resolve to the
  canonical setup skill.

Coverage is not health. `remediation_coverage` describes the available fix or
handoff class. `assessment` is `healthy`, `finding`, `partial`, `unknown`, or
`not_applicable`. A domain is healthy only when every applicable rule has
concrete evidence and none trigger. Missing evidence produces
`SAD-EVIDENCE-INCOMPLETE`; use `--require-complete-evidence` to exit nonzero.

## Coverage Domains

The manifest covers:

- Connectivity and credentials
- Cloud ACS control plane
- Cloud Monitoring Console
- Enterprise health
- Platform lifecycle, supported versions, topology, sizing, runtimes, and sidecars
- Cloud and Enterprise configuration validation
- Monitoring Console
- Indexes and storage
- DDAA, DDSS, SmartStore, archive, restore, and data lifecycle
- Ingest paths, data quality, queues, and loss signals
- Ingest Processor, Edge Processor, Ingest Actions, SPL2, Data Manager, DB Connect, and OTLP
- Agent Management, forwarders, and deployment-server compatibility
- Distributed search and SHC
- Federated Search and Hybrid Search migration
- Indexer clustering
- License/subscription
- Search and scheduler
- Workload management
- Apps and add-ons
- Auth, SSO/SAML, LDAP, MFA, users, roles, and tokens
- TLS/PKI/security hardening
- Audit and compliance
- KV Store, knowledge objects, CIM, and data models
- Dashboard Studio, Secure Gateway, and mobile readiness
- Data-source and semantic readiness, including the TA completion gate
- Backup, DR, support evidence
- Restart and maintenance orchestration
- Product handoffs for the full repository catalog
- Diagnostic evidence completeness

## Evidence Shape

Evidence is JSON and may come from live local Enterprise probes, external
collection, tests, or operator-provided snapshots. Common top-level keys:

- `platform`: `cloud` or `enterprise`
- `rest`: reachability, TLS, status code, capability, and denial hints
- `acs`: Cloud ACS status, allowlist, apps, HEC, indexes, and user/role hints
- `cmc`: Cloud Monitoring Console panel statuses and findings
- `splunkd`, `btool`, `monitoring_console`: Enterprise health and config
- `indexes`, `hec`, `ingest`, `forwarders`
- `distributed_search`, `shc`, `indexer_cluster`
- `license`, `subscription`, `scheduler`, `workload_management`
- `apps`, `auth`, `security`, `kvstore`, `knowledge_objects`
- `backup`, `support`, `premium_products`
- `lifecycle`, `topology`, `runtime`, `capacity`, `sidecars`
- `config_validation`, `audit`, `federated_search`, `dashboards`, `secure_gateway`
- `data_manager`, `ingest_processor`, `edge_processor`, `ingest_actions`, `otlp`, `db_connect`
- `ddaa`, `ddss`, `archive`, `data_readiness`, `cim`, `ocsf`, `products`
- `applicability.rules` and `applicability.domains`: optional boolean maps for
  explicitly marking unlicensed, disabled, unsupported, or unused capabilities
  not applicable to this environment. Unknown rule/domain names fail schema
  validation.

Evidence is redacted before writing under `evidence/`. Secret-like keys and
token-looking values, URI userinfo, and secret query parameters are replaced
with `[REDACTED]`. Rendered files are mode `0600`.

Each coverage-domain row includes `expected_evidence_paths`,
`assessed_rule_ids`, and `unassessed_rule_ids`. An empty list/false/zero is a
valid assessed value; an absent path, `null`, `unknown`, `unavailable`,
`not_assessed`, or `not_collected` is not.
`explicitly_not_applicable_rule_ids` records reviewed applicability exclusions;
optional features must be marked this way rather than silently omitted.

## Current Platform Corrections

- As of 2026-07-02, the shared Enterprise support contract lists 9.3, 9.4,
  10.0, 10.2, and 10.4. Enterprise 9.2 and older are EOS; 10.1 and 10.3 were
  not released Enterprise trains. The doctor derives lifecycle findings from
  `server.version` and the shared version contract.
- Cloud 10.3.2512+ supports configuration validation through the btool REST
  API; it is not `not_applicable`.
- Cloud administrators can manage workload rules, admission rules, and pool
  assignment. The doctor renders an operator checklist instead of a support-only
  classification.
- Cloud SHC and indexer-cluster health are diagnosable through CMC even though
  the underlying clusters remain Splunk-managed.
- Hybrid Search is end-of-life; findings route to Federated Search migration.
- DDAA, DDSS, and SmartStore are distinct lifecycle mechanisms and have
  separate Cloud/Enterprise handoffs.
- Agent Management is the current name for deployment-server/forwarder
  management capabilities; legacy terminology remains in evidence aliases.

## Fix Policy

`direct_fix` means a local checklist or packet that does not mutate Splunk.
`delegated_fix` means the doctor routes work to another skill. `manual_support`
means the output is a runbook or support-ticket packet. `diagnose_only` means
the doctor can identify and explain the issue but does not produce a selectable
fix in v1.

Do not change `apply` to execute another skill or Splunk command unless the
operation is separately designed, tested, gated by explicit flags, classified
in the MCP safety map, and documented here.

## Splunk 10.4 enterprise deployment notes

For Splunk Enterprise `10.4.0`, Splunk Cloud Platform `10.5.2605`, and the
previous Cloud documentation train `10.4.2604` planning,
read this skill alongside
[`../shared/splunk_10_4_enterprise_deployment_notes.md`](../shared/splunk_10_4_enterprise_deployment_notes.md),
the prose companion to the
[`../shared/references/splunk_platform_versions.json`](../shared/references/splunk_platform_versions.json)
version contract.
