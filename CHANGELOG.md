# Changelog

All notable changes should be documented here.

This project follows an `Unreleased` section first. Move entries into a dated
release section when cutting a release.

## Unreleased

### Added

- New `galileo-platform-setup` skill: render-first Galileo SaaS/Enterprise
  integration with Splunk Platform (HEC/OTLP) and Splunk Observability Cloud.
  Covers `export_records` to Splunk HEC, Observe OpenTelemetry/OpenInference
  snippets, Protect invoke snippets, Evaluate/experiment/dataset/metric/
  annotation handoffs, and OTel Collector, dashboard, and detector handoffs;
  supports `--o11y-only` to omit Splunk Platform HEC dependencies. 14 unit
  tests.
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
  - `splunk-cloud-acs-allowlist-setup` (Splunk Cloud ACS IP allowlist
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
  setup, and a two-stage commit (plan + confirm) execution flow gated by
  `SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1`.

### Removed

- Removed `splunk-galileo-integration` skill (deprecated). Its functionality
  has been split into two dedicated skills: `galileo-platform-setup` (Galileo
  Observe, Protect, Evaluate, and Splunk HEC/OTLP/OTel Collector integration)
  and `galileo-agent-control-setup` (Agent Control server, auth, controls,
  Python/TypeScript runtime snippets, and OTel/HEC sink wiring). The old skill
  had a narrower scope and no test coverage; the replacements are render-first,
  fully validated, and MCP-registered.

### Changed

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

- Extended `READ_ONLY_PHASE_SCRIPTS` in `agent/splunk_cisco_skills_mcp/core.py`
  to cover the new render-first skills so MCP-driven runs of read-only phases
  (`render`, `preflight`, `status`, `audit`, `validate`, `bundle-validate`,
  `bundle-status`, `cloud-onboard`) do not require the mutation gate. Any
  `--apply` invocation is still classified as mutating.
- Added `READ_ONLY_UNLESS_APPLY_SCRIPTS` for flag-based skills
  (`splunk-observability-native-ops`, `splunk-observability-dashboard-builder`)
  that gate live mutations behind an explicit `--apply` rather than a
  `--phase` argument.

### Security

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

- Added `app_registry.json` regression tests for unique Splunkbase IDs,
  filesystem<->`skill_topologies` orphan checks, well-formed
  `min_splunk_version` values, and `cisco-scan-setup` script invariants.
- Added bats flag-parsing smoke for `cisco-scan-setup` and the new
  `--skip-data-flow` / `--data-flow-earliest` options on the Cisco Security
  Cloud and Cisco Secure Access validators.
- Added unit tests for the new MCP `_redact_secrets` / `_truncate_and_redact`
  helpers.
