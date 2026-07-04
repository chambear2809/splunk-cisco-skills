# Splunk Admin Doctor Reference

The doctor uses `scripts/doctor.py` as the source of truth for:

- `COVERAGE_MANIFEST`: every admin domain and platform applicability.
- `RULE_CATALOG`: every rule, with required fields:
  `id`, `domain`, `platform`, `severity`, `evidence`, `source_doc`,
  `fix_kind`, `preview_command`, `apply_command`, `handoff_skill`, and
  `rollback_or_validation`.
- `trigger`: exactly one non-empty `any` or `all` predicate group. For `any`,
  one assessed match proves a finding, while every branch must be assessed and
  false to prove health. For `all`, one assessed false branch resolves the
  expression; otherwise every branch must be assessed. Missing branches never
  become implicit health.
- `applies_when`: an optional expression that derives version or feature
  eligibility. A resolved false condition is recorded as derived not
  applicable; missing eligibility evidence keeps the rule applicable and
  unassessed.
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

Only entries in the checked-in optional-domain and optional-rule allowlists may
be set to `false`. Connectivity, evidence completeness, and other baseline
health controls cannot be excluded. This prevents an applicability map from
turning an empty audit into a complete report.

Evidence is redacted before writing under `evidence/`. Secret-like keys and
token-looking values, URI userinfo, and secret query parameters are replaced
with `[REDACTED]`. Input JSON must be a single-link regular file, is read with
no-follow semantics and a size bound, and rejects non-finite JSON numbers.
Rendered files are mode `0600`; output parents cannot traverse symlinks and the
output root must be owned by the current user and not group/world writable.
The emitted `evidence/normalized-evidence.redacted.json` is the validated,
redacted evidence used for evaluation and can include derived diagnostics,
lifecycle facts, and detected-product normalization. It is deliberately not
named or represented as an immutable copy of the source evidence file. Doctor
writes hold a non-blocking bundle lock across cleanup, rendering, and commit.
`artifact-manifest.json` records every committed generated artifact and its
hash; status uses a read lock and rejects a missing, mixed, or tampered bundle.
The next committed render removes the legacy
`evidence/input-evidence.redacted.json` artifact to prevent stale consumers.
`evidence/collection-notes.md` distinguishes a supplied snapshot, bounded local
Enterprise probe, or operator-context-only run and includes the actual
`evidence.collection.notes` as recursively redacted JSON.

Each coverage-domain row includes `expected_evidence_paths`,
`assessed_rule_ids`, and `unassessed_rule_ids`. An empty list/false/zero is a
valid assessed value; an absent path, `null`, `unknown`, `unavailable`,
`not_assessed`, or `not_collected` is not.
`explicitly_not_applicable_rule_ids` records reviewed applicability exclusions;
optional features must be marked this way rather than silently omitted.
`derived_not_applicable_rule_ids` records resolved `applies_when` exclusions.
Doctor reports, coverage reports, fix plans, apply summaries, live plans, and
live final reports carry `schema_version: 1`; status rejects an incompatible
doctor-report schema instead of reporting it as healthy.

For `doctor`, `fix-plan`, and `apply`, select `--platform cloud` or
`--platform enterprise`. `--platform auto` is valid only when the evidence JSON
contains an explicit supported `platform` value or a strict HTTPS management
hostname ends in `.splunkcloud.com`. No other URI, hostname, or missing value
silently defaults to Enterprise. A supplied `--splunk-uri` must be an HTTPS
origin with a hostname and optional valid numeric port; credentials, non-root
paths, query strings, and fragments are rejected. These checks happen before
output cleanup or live collection.

Status has two separate meanings: report/schema validity and assessed platform
health. `report_valid` is true only for a readable, compatible report;
deprecated `ok` aliases that validity result and is not health. `healthy` is
true only when evidence is complete and no findings exist.
`evidence_complete` mirrors report coverage, `severity_counts` summarizes
findings, and `health_status` is `healthy`, `findings`, `incomplete`, or
`findings_and_incomplete`. The `SAD-EVIDENCE-INCOMPLETE` sentinel by itself
produces `incomplete`; any other finding combined with incomplete evidence
produces `findings_and_incomplete`. `highest_severity` and
`health_relevant_finding_count` make status aggregation explicit, while
`strict_ready` is true only when evidence is complete and no high or critical
finding would fail `--strict`. `integrity_verified` is true only after the
artifact manifest and report pass locked integrity and schema checks. Missing
or invalid status sets `report_valid`, deprecated `ok`, `healthy`,
`evidence_complete`, `integrity_verified`, and `strict_ready` false, reports
`health_status: incomplete`, and returns zeroed severity counts. Status exits
`0` for a valid bundle regardless of findings and exits nonzero for missing,
invalid, or unverifiable bundles.

## Current Platform Corrections

- As of 2026-07-02, the shared Enterprise support contract lists 9.3, 9.4,
  10.0, 10.2, and 10.4. Enterprise 9.2 and older are EOS; 10.1 and 10.3 were
  Cloud-only trains. Current Cloud train 10.5 is not in the public Enterprise
  download or release-manual contract yet, so the doctor retains the verified
  10.4 self-managed baseline. The doctor derives lifecycle findings from
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
- A supported release is eligibility evidence, not a finding by itself.
  Cloud/Enterprise configuration-validation findings require an unavailable,
  failed, or error-bearing validation result on an eligible release.

## Live Runner Contract

`scripts/live_validate_all.py` performs one target evidence collection for a
full sweep or doctor-scoped run. Required REST probes must return a successful
2xx status, valid JSON, and the expected Splunk `entry` schema. A 401/403,
transport error, malformed payload, or partial required probe set cannot be
converted into empty healthy evidence.

Profile-derived values replace inherited Splunk environment settings, and
secret-shaped inherited environment variables are removed before child
commands. Live collection rejects HTTP, embedded URI credentials, query or
fragment components, disabled or invalid TLS verification, unknown profile
metadata, and requested/profile platform conflicts before network access.
Named profiles are mandatory by default. `--allow-flat-credentials` is an
explicit compatibility exception for a legacy flat credential file; it does
not weaken URI, TLS, platform, or secret-file validation and should not be used
when the credentials can be migrated to a named profile.

Default child-skill checks validate interfaces only. Checked-in offline smokes
require `--allow-offline-smoke`. The legacy
`--allow-heuristic-live-probes` flag is deliberately rejected until an audited
command safety manifest exists. Reports distinguish `interface-pass`,
`feature-pass`, `partial-pass`, `unassessed`, `intentional-skip`, and `fail`.
Required baseline failures and interrupts record every remaining step as not
run, and fatal collection errors still produce a final JSON/Markdown report.

`checkpoint.json` is private, bounded audit history only. It is never proof
that a current-run step passed, and current-run apply renders are always
regenerated. The deprecated `--force-rerun` compatibility option does not
enable or disable reuse. Recognized run directories use a positive
`--max-retained-runs` total bound (default `50`). Stale or incomplete
non-current runs count toward the bound; the oldest runs beyond it are pruned
at safe lifecycle points while the current run is preserved.

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

For Splunk Enterprise `10.4.1`, Splunk Cloud Platform `10.5.2605`, and the
previous Cloud documentation train `10.4.2604` planning,
read this skill alongside
[`../shared/splunk_10_4_enterprise_deployment_notes.md`](../shared/splunk_10_4_enterprise_deployment_notes.md),
the prose companion to the
[`../shared/references/splunk_platform_versions.json`](../shared/references/splunk_platform_versions.json)
version contract.
