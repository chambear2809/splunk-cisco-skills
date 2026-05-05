# Splunk Admin Doctor Reference

The doctor uses `scripts/doctor.py` as the source of truth for:

- `COVERAGE_MANIFEST`: every admin domain and platform applicability.
- `RULE_CATALOG`: every rule, with required fields:
  `id`, `domain`, `platform`, `severity`, `evidence`, `source_doc`,
  `fix_kind`, `preview_command`, `apply_command`, `handoff_skill`, and
  `rollback_or_validation`.
- `validate_catalog()`: structural checks that fail tests when a domain lacks
  a rule or a delegated/manual/diagnose route.

## Coverage Domains

The manifest covers:

- Connectivity and credentials
- Cloud ACS control plane
- Cloud Monitoring Console
- Enterprise health
- Monitoring Console
- Indexes and storage
- Ingest paths
- Forwarder and deployment server
- Distributed search and SHC
- Indexer clustering
- License/subscription
- Search and scheduler
- Workload management
- Apps and add-ons
- Auth, users, roles, tokens
- TLS/PKI/security hardening
- KV Store and knowledge objects
- Backup, DR, support evidence
- Premium product handoffs

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

Evidence is redacted before writing under `evidence/`. Secret-like keys and
token-looking values are replaced with `[REDACTED]`.

## Fix Policy

`direct_fix` means a local checklist or packet that does not mutate Splunk.
`delegated_fix` means the doctor routes work to another skill. `manual_support`
means the output is a runbook or support-ticket packet. `diagnose_only` means
the doctor can identify and explain the issue but does not produce a selectable
fix in v1.

Do not change `apply` to execute another skill or Splunk command unless the
operation is separately designed, tested, gated by explicit flags, classified
in the MCP safety map, and documented here.
