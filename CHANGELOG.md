# Changelog

All notable changes should be documented here.

This project follows an `Unreleased` section first. Move entries into a dated
release section when cutting a release.

## Unreleased

### Added

- Generated `SKILL_VALIDATION_MATRIX.md` and its checked-in evidence registry,
  separating interface contracts, direct test references, offline smoke scripts,
  advertised live/strict modes, TA completion requirements, and sanitized
  integration/live/apply results for every skill.
- New `galileo-platform-setup` skill: render-first Galileo SaaS/Enterprise
  integration with Splunk Platform (HEC/OTLP) and Splunk Observability Cloud.
  Covers `export_records` to Splunk HEC, Observe OpenTelemetry/OpenInference
  snippets, Protect invoke snippets, Evaluate/experiment/dataset/metric/
  annotation handoffs, and OTel Collector, dashboard, and detector handoffs;
  supports `--o11y-only` to omit Splunk Platform HEC dependencies, with a
  dedicated regression suite.
- New `galileo-agent-control-setup` skill: render-first Agent Control server
  readiness, file-backed auth templates, controls, Python/TypeScript runtime
  snippets, OTel sink config, custom Splunk HEC event sink, and Observability
  dashboard/detector handoffs. 6 unit tests.
- New `splunk-deployment-server-setup` skill: bootstrap and operate a Splunk
  Enterprise Deployment Server. Covers DS enablement, `phoneHomeIntervalInSecs`
  scaling for fleets up to 10,000+ UFs, REST fleet inspection, HA pair with
  HAProxy, rsync app sync, cascading DS anti-pattern guard, mass client
  re-targeting, staged rollout, and explicit `filterType` rendering for Splunk
  9.4.3+. 10 unit tests.
- New `splunk-search-head-cluster-setup` skill: plan, render, bootstrap, and
  operate an SHC — deployer config push, member `server.conf` generation,
  sequenced bootstrap, rolling restarts (searchable / default / forced),
  captain transfer, KV Store replication monitoring and reset, member add /
  decommission / remove, standalone-to-SHC migration, deployer replacement,
  ES placement on SHC, and failure mode runbooks. 10 unit tests.
- New `splunk-observability-aws-lambda-apm-setup` skill: render-first, full-coverage
  Splunk OpenTelemetry Lambda layer (`signalfx/splunk-otel-lambda`, beta, publisher
  `254067382080`) APM instrumentation for AWS Lambda functions. Covers Node.js
  18/20/22, Python 3.9–3.13, Java 8/11/17/21 on x86_64 and arm64; per-runtime
  `AWS_LAMBDA_EXEC_WRAPPER` wiring; secret-safe `SPLUNK_ACCESS_TOKEN` delivery via
  AWS Secrets Manager or SSM SecureString (resolve references; token value never in
  files or argv); layer ARN baked snapshot with opt-in live refresh; vendor/ADOT
  conflict detection; X-Ray coexistence flag; GovCloud/China refusal; IAM egress
  stub; AWS CLI / Terraform / CloudFormation variants; rollback; discover-functions;
  doctor; and cross-skill handoffs. Fulfills the `handoffs.lambda_apm` stub in
  `splunk-observability-aws-integration`. MCP-registered with render-only default
  classification and `--apply`/`--quickstart` mutation gate. 34 unit tests.

- New Splunk security portfolio and readiness skills:
  - `splunk-security-portfolio-setup` (router that resolves ES, SOAR,
    Security Essentials, UBA, Attack Analyzer, ARI, and related offerings to
    setup, install-only, bundled ES, or handoff workflows).
  - `splunk-security-essentials-setup` (install and validate Splunk Security
    Essentials `Splunk_Security_Essentials` with content recommendations and
    starter posture dashboards).
  - `splunk-asset-risk-intelligence-setup` (install and validate
    `SplunkAssetRiskIntelligence` indexes, KV Store readiness, ARI roles, and
    ES Exposure Analytics handoff).
  - `splunk-attack-analyzer-setup` (install and validate `Splunk_TA_SAA` +
    `Splunk_App_SAA`, the `saa` index, `saa_indexes` macro, and API key
    handoff).
  - `splunk-uba-setup` (validate legacy UBA integrations, optional Kafka app
    placement, and ES Premier UEBA migration handoff).
  - `splunk-soar-setup` (render and apply Splunk SOAR On-prem single + cluster
    with external PG/GlusterFS/Elasticsearch, SOAR Cloud onboarding helper,
    Automation Broker on Docker/Podman, Splunk-side SOAR apps, and ES
    integration readiness; render-first with explicit apply phases).
- New Splunk platform admin skills:
  - `splunk-indexer-cluster-setup` (single-site, multisite, redundant manager
    bootstrap plus cluster bundle validate/apply/rollback, rolling restart
    modes, peer offline, maintenance, site migration, manager replacement).
  - `splunk-license-manager-setup` (install licenses, activate groups,
    configure peers and pools, audit usage and violations, validate version
    compatibility).
  - `splunk-edge-processor-setup` (Edge Processor instances + control plane,
    Linux install via systemd / no-systemd / Docker, multi-instance scale-out,
    source types / destinations / SPL2 pipelines, apply orchestration).
  - `splunk-cloud-acs-admin-setup` (Splunk Cloud ACS IP allowlist
    management for all seven features with IPv4 and IPv6, subnet limit
    preflight, ACS lock-out protection, drift detection, optional Terraform
    emission).
- New `splunk-observability-native-ops` skill (detectors, alert routing,
  Synthetics, APM, RUM, logs, and On-Call handoffs via a flag-based
  `--render`/`--validate`/`--apply` workflow with coverage tagging).
- New skill `splunk-enterprise-kubernetes-setup` covering Splunk Operator for
  Kubernetes (S1/C3/M4) and Splunk POD on Cisco UCS, with render-first
  preflight/apply/validate phases and `--dry-run`/`--json` output.
- New hardened Splunk platform admin and service skills:
  - `splunk-agent-management-setup` (server classes, deployment apps,
    deployment-client assets, Splunk 10.x Agent Management workflows)
  - `splunk-workload-management-setup` (workload pools, workload rules,
    admission-rule guardrails, Linux cgroups prerequisites)
  - `splunk-hec-service-setup` (reusable HEC token configuration with both
    Splunk Enterprise `inputs.conf` rendering and Splunk Cloud ACS payloads)
  - `splunk-index-lifecycle-smartstore-setup` (SmartStore `indexes.conf`,
    `server.conf`, and `limits.conf` for indexers and cluster managers)
  - `splunk-monitoring-console-setup` (distributed and standalone Monitoring
    Console assets, peer/group review, forwarder monitoring, platform alerts)
  - `splunk-federated-search-setup` (standard and transparent FSS2S, FSS3,
    federated indexes, SHC replication assets — expanded in `cb1ea94` to
    cover the full product surface area)
- New `splunk-enterprise-security-install` skill (essinstall on standalone
  search heads or SHC deployers, TA-for-indexers packaging, preflight,
  post-install validation, `--uninstall`).
- New `splunk-enterprise-security-config` skill (declarative YAML for ES
  indexes, roles, data models, enrichment, detections, RBA, Mission Control,
  exposure analytics, UEBA, SOAR integrations, and configuration health).
- New `splunk-observability-otel-collector-setup` skill (Splunk Distribution
  of OpenTelemetry Collector for Kubernetes and Linux hosts, with HEC token
  handoff helpers).
- New `splunk-observability-dashboard-builder` skill (classic Observability
  dashboard groups, charts, dashboards, and detector links from
  natural-language, JSON, or YAML specs).
- New `splunk-universal-forwarder-setup` skill for first-class Universal
  Forwarder runtime bootstrap, official latest-download resolution with
  SHA512 verification, Linux/macOS local or SSH apply, rendered Windows MSI
  handoff, and deployment-server, static-indexer, or Splunk Cloud enrollment.
- Local `splunk-cisco-skills` MCP agent server under `agent/` with
  read-only catalog/skill/template tools, dry-run planning for Cisco product
  setup, and a two-stage commit (plan + confirm) execution flow. It is
  plan-only by default; local execution requires
  `SPLUNK_SKILLS_MCP_ENABLE_EXECUTION=1`, and generic script execution also
  requires `SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION=1` and
  `SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1`.

### Removed

- Removed the deprecated Galileo Splunk integration skill. Its functionality
  has been split into two dedicated skills: `galileo-platform-setup` (Galileo
  Observe, Protect, Evaluate, and Splunk HEC/OTLP/OTel Collector integration)
  and `galileo-agent-control-setup` (Agent Control server, auth, controls,
  Python/TypeScript runtime snippets, and OTel/HEC sink wiring). The old skill
  had a narrower scope and no test coverage; the replacements are render-first,
  fully validated, and MCP-registered.

### Changed

- Synced `cisco-catalyst-ta-setup` to the TA `3.2.44` source contract with 29
  modular inputs, device-scoped SD-WAN BFD API guidance, editable SD-WAN and
  Cyber Vision intervals, account-scoped TLS validation, and the bounded beta
  IOS-XE CLI collector. Added explicit SD-WAN text-syslog guidance and checks
  for `cisco:firewall:logs`, UTD over UDP 514 on affected releases, traditional
  ZBFW syslog rate limits, SC4S/HEC routing, and the separate HSL/Unified
  Logging NetFlow/IPFIX path.

- Hardened the repo-local skills MCP server for an execution-enabled,
  mutation-off registration: added product-first paginated discovery,
  subprocess-free Cisco resolution, curated no-follow resource reads, strict
  value-safe tool/prompt validation, a bounded strict-UTF-8 stdio transport,
  standard protocol errors, supervised process queues/groups, isolated Python
  startup, sanitized child environments, interpreter and secret-file
  attestation, cancellation-safe plan creation, stable dry-run snapshots, and
  an independent generic-execution gate. Committed client registrations now
  explicitly set execution to `1` and both generic/mutation gates to `0`.

- Updated every Galileo workflow for the July 7, 2026 release. The platform
  skill now renders AI Assistant beta and cross-project global-dashboard
  readiness, a payload-v1 generic alert webhook relay for Splunk HEC,
  `galileo>=2.2.0` experiment-group assignment, and large-dataset batched
  processing readiness and handoff assets. The object lifecycle now records
  owner-only exact-ID cleanup ledgers, validates experiment-group membership,
  re-reads exact dataset and prompt IDs after deletion, and narrowly works
  around the Galileo SDK 2.4.0 project permission-enum
  readback mismatch only after exact REST project verification. Galileo OTLP
  defaults now use `/otel/traces`; the MCP catalog is refreshed to server
  `1.28.1`, fails on server-version drift, and
  is now checked weekly with the Galileo product-coverage audit. The audit also
  fails closed when Galileo publishes a release newer than the reviewed
  `2026-07-07` baseline. Rendered MCP clients now use a dependency-free
  stdio-to-Streamable-HTTP bridge with JSON/SSE, session, cancellation,
  redirect, IPv6-loopback, and secret-file safeguards. Agent Control runtime
  and Splunk HEC URLs now reject remote cleartext, embedded credentials,
  ambiguous HEC paths, and authenticated redirects. Observe export supports
  the current JSONL-flat and computed/code-metric options, while webhook
  delivery and search-time deduplication semantics are explicit.

- Hardened `cloud_batch_uninstall.sh` for production use: strict concrete app
  names, all-target/version preflight before mutation, exact removal plans,
  non-interactive `--yes`, separately acknowledged topology-risk REST fallback,
  URL-encoded app endpoints, bounded tri-state ACS/REST absence verification,
  stop-on-partial-error behavior, and private per-app recovery evidence. ACS
  request acceptance alone is no longer reported as successful removal.

- Made `splunk-dashboard-studio-setup` live and transactional: preflight now
  snapshots the exact view and ACL, status detects content/owner/sharing and
  exact read/write-role drift, and apply verifies the same normalized role sets.
  Ambiguous responses, signals, or ACL/readback failures now use GET-only
  reconciliation: failed creates and updates are retained with private
  before/current snapshots and reviewed recovery guidance because REST has no
  verified conditional restore or delete contract.
- Removed automatic compensating restore POSTs from
  `splunk-knowledge-objects-setup`. Failed existing or new object, ACL, and
  automatic-lookup mutations are retained with private before/current snapshots
  and partial/manual-recovery evidence, eliminating the guard-GET-to-restore-POST
  race that could overwrite a concurrent edit.
- Added fail-closed render-bundle ownership markers for the seven incompatible
  legacy/current skill pairs covering CIM data models, Dashboard Studio, DDAA,
  Ingest Actions, knowledge objects, KV Store, and Secure Gateway. Existing
  output paths remain unchanged; each renderer can adopt its own unmarked
  legacy bundle, but rejects peer-owned or detectably mixed bundles before any
  render/apply workflow can consume stale artifacts.
- Made `splunk-universal-forwarder-setup` render-only by default. Live install,
  upgrade, enrollment, and combined phases now require the explicit
  `--accept-forwarder-mutation` acknowledgement, including rendered apply
  scripts.
- Made Cisco ASA/FTD routing collection-aware: syslog and
  `Splunk_TA_cisco-asa` requests use `cisco-asa-ta-setup`, API/eStreamer
  requests stay on Cisco Security Cloud, and bare ASA/FTD requests return an
  explicit two-owner choice.
- Normalized every skill's `agents/openai.yaml` to the canonical `interface`
  schema and constrained UI descriptions to the supported 25–64 character
  range while preserving skill-specific action prompts.
- Added Splunk Cloud Platform `10.5.2605` support while retaining verified
  Splunk Enterprise/SOK/POD 10.4 baselines; refreshed all 119 public
  Splunkbase registry records against a 10.5 compatibility target, updated
  current package pins and Cloud documentation trains, and kept 14 packages
  explicitly unsupported where their current listings do not certify 10.5.
- Classified all 165 skills for Splunk Cloud 10.5 in machine-readable
  frontmatter and a generated compatibility matrix; added fail-closed audits
  so new or unclassified skills cannot silently inherit platform support.
- Made the generic app installer enforce target-minor compatibility for the
  selected package release and default known apps to repo-verified releases.
  Verified pins and current public releases retain separate platform evidence;
  unsupported or unregistered releases require explicit, auditable overrides.
- Hardened the local MCP contract with strict tool schemas, random expiring
  single-use plan capabilities, executable and full skill-tree integrity
  binding, forced cancellation escalation, a default-off subprocess gate, and
  mutation gating for all generic script execution.
- Pinned the MCP runtime and patched security-sensitive transitive dependencies;
  added Python 3.10/3.14 protocol CI and weekly dependency updates.
- Updated `splunk-mcp-server-setup` for the official Splunk MCP Server 1.2.1
  package with version/checksum verification, pinned `mcp-remote@0.1.38`
  without an `npx` fallback, HTTPS enforcement with loopback-only exceptions,
  and completion checks for the MCP handshake, `splunk_get_info`, and shipped views.
- Marked the official 1.2.1 package as not production-approved after static
  security and protocol review; local mutation/activation requires an explicit
  isolated-evaluation acknowledgement, while production completion remains
  blocked pending vendor fixes.
- Aligned all `SKILL.md` frontmatter with the Agent Skills description limit
  and tightened the PKI skill body to stay under the progressive-disclosure
  line-count guidance.
- Refreshed Cisco Secure Access skill to install both the dashboard app and
  the Secure Access add-on (`TA-cisco-cloud-security-addon`) and reflect both
  apps in the README/AGENTS/CLAUDE catalogs.
- Expanded `cisco-product-setup` reference to document the `spaces` route and
  the optional `cisco-catalyst-enhanced-netflow-setup` companion path.
- Aligned `splunk-enterprise-host-setup` SKILL.md role names with the actual
  CLI values (`standalone-search-tier`, `standalone-indexer`, etc.).
- Bounded the `cisco-dc-networking-setup` data-flow validation search with
  `earliest=-1h@h latest=now` so the success/warn message matches the query.
- Added contributor-readiness, security, ownership, and validation guardrails.
- Tightened the MCP `read_only` heuristic: `--dry-run` and `--list-products`
  are honored only for the `cisco-product-setup` scripts that actually
  implement them; other scripts are always treated as mutating.
- Added catalog-aware allowlist for `plan_cisco_product_setup` so non-secret
  catalog fields are accepted regardless of regex shape; added a regression
  test that catches future catalog edits adding secret-shaped non-secret keys.
- Made MCP plans single-use: a plan hash is consumed when it executes, so
  destructive commands cannot be replayed and concurrent execute calls for
  the same hash do not double-run.
- Bounded MCP subprocess stdout/stderr at 256 KiB per stream during execution
  to prevent unbounded memory growth from chatty scripts; timeouts now
  SIGTERM then SIGKILL with a short grace and report `timed_out` in the
  response.
- Replaced `_frontmatter` ad-hoc parser with `yaml.safe_load`.
- Pinned ShellCheck CI install to a SHA-256 of the upstream archive.
- Restored stderr routing on Cisco ThousandEyes Cloud-warning lines.
- Tightened `--custom-indexes` validation in the Cisco Enterprise Networking
  setup to reject any value that is not a valid Splunk index name.
- Added `*)` fallback to the Cisco product validation phase so unknown route
  types fail loudly instead of silently succeeding.
- Promoted a single-use cleanup-trap pattern (`hbs_append_cleanup_trap`) in
  Cisco Spaces and Cisco ThousandEyes scripts so prior EXIT/INT/TERM traps
  are preserved.

### Documentation

- Added explicit Agent Skills specification, best-practices, and evaluation
  callouts to the README, contributor guide, and pull request template.
- Documented in `splunk-mcp-server-setup` why the rendered Bearer header is
  written as the literal `${SPLUNK_MCP_TOKEN}` placeholder: `mcp-remote`
  performs `${VAR}` substitution at runtime and this keeps the token out of
  argv (process listings).
- Added Splunk Cloud Victoria vs Classic guidance to `ARCHITECTURE.md` and a
  per-skill stack-type sensitivity table.
- Added new `reference.md` files for `splunk-itsi-setup` and
  `splunk-ai-assistant-setup` covering version compatibility, topology
  placement, Splunk Cloud vs Enterprise differences, REST/KV surface checked
  by `validate.sh`, and known operational caveats.

### Schema

- Added optional `min_splunk_version` field to `apps[]` entries in
  `skills/shared/app_registry.json` (string of the form ``MAJOR.MINOR`` or
  ``MAJOR.MINOR.PATCH``). Seeded for `SA-ITOA`, `SplunkEnterpriseSecuritySuite`,
  and `Splunk_AI_Assistant_Cloud`. Missing/empty means "no declared minimum."

### Agent / MCP

- Replaced script-name/flag read-only heuristics with a fail-closed rule: every
  generic skill-script and typed product execution plan is potentially mutating.
  Product dry-runs require only the execution gate; executing any resulting
  plan also requires the mutation gate, and generic plans require all three.
- Added a product/capability registry-backed discovery contract with opaque
  pagination, bounded file reads, curated entrypoints, and resource revisions.

### Security

- Added a shared fail-closed curl policy for Splunkbase, AppDynamics, Edge
  Processor, SOAR, ThousandEyes, Meraki, and Observability probes: user curl
  configuration is ignored, credential-bearing redirects are disabled or
  followed only after credentials are stripped, protocols are constrained,
  secret files/configs use no-follow single-link checks, and transfer
  timeouts are bounded. Enterprise/Forwarder package downloads now use the
  same curl isolation and HTTPS policy; plaintext mirrors require the warned
  `APP_DOWNLOAD_ALLOW_HTTP=true` lab-only override.
- Credential-bearing Splunk REST paths now reject plaintext HTTP by default,
  keep `SPLUNK_VERIFY_SSL=false` separate from transport authorization, and
  require the warned `SPLUNK_ALLOW_INSECURE_HTTP=true` opt-in for isolated
  short-lived labs. Curl protocols and redirects are constrained, and direct
  MCP-loader, MCP bearer-validation, deployment-bundle, and Deployment Server
  clients use the same policy. Generated Dashboard Studio, Federated Search
  status/toggle, DDAA, ACS private-connectivity, and Platform PKI shell clients
  now also ignore user curl configuration, disable URL globbing, reject
  credential-bearing redirects, and validate credential-free HTTPS origins.
- Removed shell `eval` from Deployment Server and Search Head Cluster rendered
  artifact validators so hostile output-directory names remain data, not code.
- Hardened shared coding-agent telemetry output writes against symlink,
  hardlink, parent-path, and target-swap attacks with descriptor-relative,
  no-follow, atomic replacement and mode validation.
- MCP server now redacts subprocess output before returning it to the model:
  `Authorization` headers, JWT tokens, PEM private-key blocks, and
  `password=`/`token=`/`api_key=`/etc. KV-style secrets are replaced with
  `[REDACTED]` markers in `execute_plan` responses, `resolve_cisco_product`
  raw-stdout fallbacks, and Cisco product dry-run error messages. This is
  defense-in-depth; scripts must still avoid echoing secrets.
- `registry_helpers.sh` now surfaces JSON parse / read errors as a single-line
  warning to stderr instead of silently swallowing them, so a corrupt
  registry no longer turns every role-aware check into "no metadata found"
  with no diagnostic.

### Tests

- Added bidirectional ownership regressions for all seven incompatible render
  pairs, plus marker-contract drift, unmarked mixed-bundle refusal, compatible
  legacy adoption, and dry-run non-mutation coverage.
- Extended the skill metadata validator to enforce canonical
  `agents/openai.yaml` interface fields, action-prompt skill references, and UI
  description lengths. Its dependency-free fallback now understands the
  nested mappings used by the repository.
- Added regressions for Universal Forwarder mutation gates, ASA/FTD route
  selection, plaintext REST rejection and lab opt-in, validator path
  injection, atomic coding-agent output safety, and generated authenticated
  Splunk/ACS curl transport policy.
- Added a repo-readiness guard that keeps the Agent Skills specification
  callouts present in README, CONTRIBUTING, and the pull request template.
- Expanded `tests/check_skill_frontmatter.py` to enforce Agent Skills
  frontmatter fields, name syntax, description length, compatibility metadata,
  and `SKILL.md` progressive-disclosure size limits.
- Added `app_registry.json` regression tests for unique Splunkbase IDs,
  filesystem<->`skill_topologies` orphan checks, well-formed
  `min_splunk_version` values, and `cisco-scan-setup` script invariants.
- Added bats flag-parsing smoke for `cisco-scan-setup` and the new
  `--skip-data-flow` / `--data-flow-earliest` options on the Cisco Security
  Cloud and Cisco Secure Access validators.
- Added unit tests for the new MCP `_redact_secrets` / `_truncate_and_redact`
  helpers.
