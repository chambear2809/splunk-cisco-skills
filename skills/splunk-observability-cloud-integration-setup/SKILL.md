---
name: splunk-observability-cloud-integration-setup
description: >-
  Render, preflight, apply, validate, and diagnose Splunk Platform to Splunk
  Observability Cloud pairing for Splunk Cloud Platform and Splunk Enterprise.
  Covers token-auth enablement, realm checks, Unified Identity or service-account
  pairing, multi-org defaults, Centralized RBAC, Discover Splunk Observability
  Cloud app configuration, Log Observer Connect, Related Content, Real Time
  Metrics, Dashboard Studio O11y metrics, and Splunk_TA_sim modular inputs.
  Use when a user asks to pair Splunk Platform with Splunk Observability Cloud,
  set up Unified Identity or Centralized RBAC, configure the Discover app,
  install the Infrastructure Monitoring Add-on, configure Related Content or
  Log Observer Connect, bring O11y metrics into Splunk with sim, or navigate
  from Splunk Platform into Observability workflows.
---

# Splunk Platform <-> Splunk Observability Cloud Integration Setup

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Single skill that pairs a Splunk Cloud Platform or Splunk Enterprise stack with
Splunk Observability Cloud and configures every navigate-into-O11y surface:
Unified Identity SSO, Centralized RBAC, the in-app Discover app, Related
Content previews in Search & Reporting, Log Observer Connect, Dashboard Studio
O11y metrics, and the Splunk Infrastructure Monitoring Add-on (`sim` SPL
command + streaming modular inputs).

The workflow is render-first by default. Live API changes only happen when the
user explicitly asks for `--apply`.

## Coverage Model

Every rendered section gets an explicit coverage status:

- `api_apply` — a documented public API supports create, update, delete, or validate.
- `api_validate` — a documented public API supports read or validation only.
- `deeplink` — the skill renders a deterministic Splunk / Observability UI link
  and validates referenced data where an API allows.
- `handoff` — the skill renders deterministic operator steps for UI-only or
  cross-skill workflows (e.g., Splunkbase install via `splunk-app-install`).
- `install_apply` — the skill installs or configures a Splunk-side companion
  app via Splunkbase + REST.
- `not_applicable` — the section does not apply to the chosen target
  (e.g., UID on Splunk Enterprise, Discover app on SCP < 10.1.2507).

UI-only steps (multi-org `Make Default`, the SE TLS-certificate paste, the
"Override default organization" user action) render as `deeplink` and never
claim API parity that does not exist.

## Safety Rules

- Never ask for Splunk Observability tokens, Splunk Cloud Platform admin JWTs,
  Splunk passwords, SIM Add-on org tokens, or Log Observer Connect
  service-account passwords in conversation.
- Never pass any secret on the command line or as an environment-variable
  prefix.
- Use `--token-file` for the regular Splunk Observability Cloud API token.
- Use `--admin-token-file` for the Splunk Observability Cloud admin token used
  by Unified Identity pairing and `enable-centralized-rbac`.
- Use `--org-token-file` for the Splunk Observability Cloud org access token
  used by the Splunk Infrastructure Monitoring Add-on account.
- Use `--service-account-password-file` for the Log Observer Connect
  service-account password.
- Token files must be regular, non-empty files with mode `600`. `--apply`
  aborts on symlinks, empty files, or looser permissions.
- Reject direct secret flags such as `--token`, `--access-token`,
  `--api-token`, `--o11y-token`, `--admin-token`, `--org-token`, `--sf-token`,
  `--service-account-password`, and `--password`.
- Prefer `SPLUNK_O11Y_REALM`, `SPLUNK_O11Y_TOKEN_FILE`,
  `SPLUNK_O11Y_ADMIN_TOKEN_FILE`, and `SPLUNK_O11Y_ORG_TOKEN_FILE` from the
  repo `credentials` file when present; these store only realms and token-file
  paths, never token values.
- Strip every secret from `00-09-*.md`, `apply-plan.json`, `payloads/`,
  `current-state.json`, `state/apply-state.json`, and any other rendered
  artifact on disk.
- `enable-centralized-rbac` is destructive and irreversible without Splunk
  Support. This repo has no safe file-backed transport for the required ACS
  token, so cutover is classified as `handoff` and always fails before mutation.
- `bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_o11y_token`
  helps the user create a token file without exposing the secret in shell
  history.

## Primary Workflow

1. Collect non-secret values: target (cloud or enterprise), Splunk Cloud
   stack, Splunk Observability Cloud realm (us0/us1/eu0/eu1/eu2/au0/jp0/sg0/
   us2-gcp), multi-org list, Log Observer Connect service-account username,
   indexes the LOC service account should access, Splunk Infrastructure
   Monitoring Add-on account name and modular-input picks.
2. Create or update a JSON/YAML spec from `template.example`.
3. Render and validate:

   ```bash
   bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
     --render \
     --spec skills/splunk-observability-cloud-integration-setup/template.example \
     --output-dir splunk-observability-cloud-integration-rendered
   ```

4. Review `splunk-observability-cloud-integration-rendered/`:
   - `README.md` — TL;DR and ordered next-step commands.
   - `architecture.mmd` — Mermaid topology of the rendered integration.
   - `00-prerequisites.md` through `09-handoff.md` — numbered per-section plans.
   - `coverage-report.json` — per-section coverage status.
   - `apply-plan.json` — apply ordering with idempotency keys (no secrets).
   - `payloads/` — per-step request bodies for ACS / REST calls.
   - `scripts/` — per-step apply scripts and cross-skill handoff drivers.
   - `support-tickets/` — pre-filled tickets when Splunk Support is required.
   - `sim-addon/` — MTS sizing, plus the curated SignalFlow catalog files.

5. Apply only when explicitly requested:

   ```bash
   bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
     --apply \
     --spec skills/splunk-observability-cloud-integration-setup/template.example \
     --realm us0 \
     --admin-token-file /tmp/splunk_o11y_admin_token \
     --org-token-file /tmp/splunk_o11y_org_token \
     --service-account-password-file /tmp/loc_svc_account_password
   ```

   To run only a subset of sections:

   ```bash
   bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
     --apply pairing,sim_addon \
     --spec my-integration.yaml
   ```

  Centralized RBAC cutover is a fail-closed handoff because no safe file-backed
  transport is implemented. The handoff never places a token on process argv.

## End-User UX (the "easy to use" promise)

Five entry points, ordered by user effort:

- `--quickstart` — renders and validates the common UID + Discover app + SIM
  scenario, then prints explicit supported apply and UI/admin handoffs. It does
  not mutate live state.
- `--render` (default) — produces the numbered plan tree; never touches live
  state.
- `--discover` — writes a read-only rendered-plan inventory scaffold to
  `current-state.json`. It does not currently claim a complete live snapshot.
- `--doctor` — writes the static twenty-check review catalog and a prioritized
  handoff/fix list. Use `--validate --live` for the limited implemented
  token-auth and SIM-account reachability reads.
- `--apply SECTIONS` — applies explicitly named supported sections. Live apply
  without a section list is refused because plans can include UI/admin handoffs.

Plus quality-of-life flags:

- `--enable-token-auth` — flips token authentication on if disabled (auto-
  rendered as a fix from `--doctor`).
- `--explain` — prints the apply plan in plain English with no API calls
  (useful for change-management approvals).
- `--list-sim-templates` / `--render-sim-templates aws_ec2,kubernetes,
  os_hosts,apm` — pick from the curated SignalFlow catalog without writing
  SignalFlow.
- `--make-default-deeplink` — emits the multi-org "Make Default" UI deeplink
  for the named realm (since no API exists).
- `--quickstart-enterprise` — renders and validates the Splunk Enterprise fast
  path; supported mutations must be invoked explicitly afterward.
- `--rollback <section>` — renders (does not auto-run) the reverse-engineered
  commands for steps that have a public reversible API; for irreversible steps
  (`enable-centralized-rbac`, deleted users) it renders a Splunk Support
  ticket template instead.

## Supported Sections

Specs use `api_version: splunk-observability-cloud-integration-setup/v1` and
can include:

- `prerequisites` — static region/realm and FedRAMP/GovCloud/GCP policy
  rendering. Live stack version, trial-stack, operator-role, and Discover-app
  10.1.2507+ checks remain explicit preflight handoffs.
- `token_auth` — token-auth state read + flip, `edit_tokens_settings`
  capability check.
- `pairing` — Splunk Cloud Platform Unified Identity (UID) via `POST
  /adminconfig/v2/observability/sso-pairing`, or Discover-app API-token
  connection. Multi-org is a fail-closed per-org-token handoff plus Make
  Default deeplink; the skill never reuses one token across declared orgs.
  Pairing is not a Splunk Enterprise section; Enterprise uses Log Observer
  Connect separately.
- `centralized_rbac` — `acs observability enable-capabilities` (provisions
  `o11y_admin / o11y_power / o11y_read_only / o11y_usage`) and
  `enable-centralized-rbac`; the `o11y_access` gate role; UID role mapping.
- `related_content_capabilities` — `read_o11y_content`, `write_o11y_content`,
  `EXECUTE_SIGNAL_FLOW`, `READ_APM_DATA`, `READ_BASIC_UI_ACCESS`, `READ_EVENT`
  capability assignments for Real Time Metrics + previews.
- `discover_app` — converges the non-secret Configurations tabs of the
  in-platform Discover Splunk Observability Cloud app: Related Content
  discovery, Field aliasing (Auto Field Mapping), and Automatic UI updates;
  Test related content remains a deeplink. Access tokens are written only by
  service-account `pairing`, preventing a duplicate connection. This section
  also merges Read permission for selected roles.
- `log_observer_connect` — service-account user + role + workload rule;
  Splunk Cloud Platform path or Splunk Enterprise TLS-certificate path.
  Hands off realm-IP allowlist deltas to `splunk-cloud-acs-admin-setup`.
- `dashboard_studio_o11y` — default-connection + capability validations + a
  starter Dashboard Studio JSON snippet using O11y metrics.
- `sim_addon` — installs `Splunk_TA_sim` (Splunkbase 5247), creates the
  `sim_metrics` index when missing, configures the SIM account through the
  TA UCC custom REST handler, renders curated SignalFlow modular inputs from
  the catalog (AWS_EC2, AWS_Lambda, Azure, GCP, Containers, Kubernetes,
  OS_Hosts, APM_Errors, APM_Throughput, RUM, Synthetics), runs MTS sizing
  preflight, and hands off the Splunk Cloud Victoria-stack search-head HEC
  allowlist + the ITSI Content Pack for Splunk Observability Cloud.
- `enterprise_mode` — collapses UID / ACS observability / Discover-app
  Configurations sections to `not_applicable` and switches LOC to the SE
  TLS-cert path.

For per-section flag references and REST payload shapes, read
[reference.md](reference.md) and the focused docs under
[references/](references/).

## Out of Scope (handed off, not duplicated)

- Splunk Add-on for OpenTelemetry Collector (Splunkbase 7125) — handled by
  `splunk-observability-otel-collector-setup`.
- Splunk Synthetic Monitoring Add-on (Splunkbase 5608) — archived; replaced by
  SIM Add-on streams.
- Splunk On-Call wiring — handled by `splunk-oncall-setup`.
- ITSI Content Pack content management — handled by `splunk-itsi-config`.
- Splunk Observability Cloud dashboards / detectors / Synthetics / RUM CRUD —
  handled by `splunk-observability-dashboard-builder` and
  `splunk-observability-native-ops`.
- AppDynamics for Log Observer Connect — separate AppDynamics SaaS workflow.

## Scenarios Gallery

Six worked end-to-end examples, copy/paste-ready:

1. **Cloud quickstart (greenfield)** — `--quickstart` renders and validates a
   fresh SCP plan, then prints supported apply and Related Content handoffs.
2. **Multi-org Cloud** — renders a fail-closed, distinct-token-per-org handoff
   for three O11y orgs on one SCP stack; default-org selection uses a deeplink.
3. **Cloud API-token mode (no UID)** — user API access-token pairing (no
   admin token required); SIM Add-on plus Related Content handoff; appropriate
   for stacks where UID is not yet in scope.
4. **Migrate API-token -> UID** — an existing API-token customer wants Unified Identity;
   renderer detects the existing connection and renders a numbered migration
   plan (pair UID, validate, instruct user to delete old SA via Discover
   app deeplink, optionally `enable-centralized-rbac`).
5. **Splunk Enterprise** — `--quickstart-enterprise` renders SIM plus LOC
   service-account/TLS assets without mutating; UID/RBAC/Discover-app sections are
   marked `not_applicable`.
6. **Inherit existing integration** — use `--discover` for a rendered-plan
   inventory scaffold, `--validate --live` for limited reachability, then `--doctor`
   to identify drift and gaps, then targeted `--apply <section>` to
   converge to the rendered plan.

## Useful Commands

Validate a draft spec:

```bash
bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
  --validate \
  --spec skills/splunk-observability-cloud-integration-setup/template.example
```

Render without applying:

```bash
bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
  --render \
  --spec skills/splunk-observability-cloud-integration-setup/template.example \
  --output-dir splunk-observability-cloud-integration-rendered
```

Diagnose an existing integration:

```bash
bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
  --doctor \
  --realm us0 \
  --admin-token-file /tmp/splunk_o11y_admin_token
```

List the curated SignalFlow modular-input catalog:

```bash
bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
  --list-sim-templates
```

## Hand-offs to Other Skills

- App install ➜ `skills/splunk-app-install/scripts/install_app.sh --source
  splunkbase --app-id 5247` (Splunk_TA_sim).
- ACS Log Observer Connect realm-IP allowlist deltas ➜
  `skills/splunk-cloud-acs-admin-setup/scripts/setup.sh --phase render
  --features search-api --search-api-subnets <pre-baked-realm-IPs>`.
- ACS Splunk Cloud Victoria-stack search-head HEC allowlist (SIM Add-on
  prerequisite) ➜ `skills/splunk-cloud-acs-admin-setup/scripts/setup.sh
  --phase render --features hec`.
- ITSI Content Pack for Splunk Observability Cloud ➜
  `skills/splunk-itsi-config/SKILL.md`.
- Splunk Observability Cloud dashboards, detectors, Log Observer Connect
  queries, Synthetics, RUM ➜
  `skills/splunk-observability-dashboard-builder/SKILL.md` and
  `skills/splunk-observability-native-ops/SKILL.md`.
- OTel collection on Kubernetes and Linux ➜
  `skills/splunk-observability-otel-collector-setup/SKILL.md`.
- Splunk On-Call detector recipients ➜ `skills/splunk-oncall-setup/SKILL.md`.

## Compliance and Security Baseline

- Splunk Cloud Platform Unified Identity is supported in AWS regions only;
  GovCloud and GCP regions are excluded. The skill marks UID sections
  `not_applicable` when GovCloud or GCP is detected and renders a Service
  Account fallback plan.
- Cross-region pairing (e.g., us0 realm to us-west-2 region) requires Splunk
  Account team approval; the preflight WARNs and emits a
  `support-tickets/cross-region-pairing.md` template.
- FedRAMP / IL5 customers cannot use UID against the public commercial O11y
  realms; the skill renders a `support-tickets/fedramp-il5-readiness.md`
  template instead of attempting the pair call.
- The skill never asks for nor logs secret material, refuses every direct
  secret CLI flag, and redacts every token, password, JWT, and authorization
  value from rendered artifacts. Non-secret pairing job IDs are retained in
  mode-600 apply state so asynchronous status polling can resume safely.

## MCP Tools

This skill includes checked-in, read-only Splunk MCP custom tools generated
from `mcp_tools.source.yaml`.

Validate or regenerate the tool artifact:

```bash
python3 skills/shared/scripts/mcp_tools.py validate skills/splunk-observability-cloud-integration-setup
python3 skills/shared/scripts/mcp_tools.py generate skills/splunk-observability-cloud-integration-setup
```

Load the tools into Splunk MCP Server:

```bash
bash skills/splunk-observability-cloud-integration-setup/scripts/load_mcp_tools.sh
```

The loader uses the supported `/mcp_tools` REST batch endpoint by default. Use
`--allow-legacy-kv` only for older MCP Server app versions that lack that
endpoint.
