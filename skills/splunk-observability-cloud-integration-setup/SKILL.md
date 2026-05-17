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
- Token files must be `chmod 600`. `--apply` aborts when any token file is
  looser, with a `chmod 600 <path>` hint. Override only with
  `--allow-loose-token-perms` (emits a WARN — use only for short-lived scratch
  tokens).
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
  Support; `--apply rbac` refuses to run that step unless
  `--i-accept-rbac-cutover` is also passed AND the renderer's preflight has
  confirmed every UID-mapped user already holds an `o11y_*` role.
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
     --apply pairing,related_content,sim_addon \
     --spec my-integration.yaml
   ```

   To enable Centralized RBAC (destructive cutover):

   ```bash
   bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
     --apply rbac \
     --i-accept-rbac-cutover \
     --spec my-integration.yaml \
     --admin-token-file /tmp/splunk_o11y_admin_token
   ```

## End-User UX (the "easy to use" promise)

Five entry points, ordered by user effort:

- `--quickstart` — single-shot: prompts only for non-secret values; auto-renders
  + applies the most common UID + Discover app + SIM scenario; calls
  `--validate` at the end. Refuses `enable-centralized-rbac` (operator must
  opt in via `--apply rbac --i-accept-rbac-cutover` separately).
- `--render` (default) — produces the numbered plan tree; never touches live
  state.
- `--discover` — read-only sweep that polls live state from ACS + O11y + the
  Splunk REST surface, writes `current-state.json`, and emits a delta report
  against the rendered plan.
- `--doctor` — diagnoses an existing integration (twenty catalog checks) and
  emits a prioritized fix list with the exact `setup.sh` command for each fix.
- `--apply [SECTIONS]` — applies the rendered plan; without arguments runs
  every section in dependency order; with `--apply pairing,rbac` runs only the
  named sections.

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
- `--quickstart-enterprise` — Splunk Enterprise fast path (SA + SIM +
  Related Content; UID, Centralized RBAC, and the Discover app are skipped
  automatically with clear `not_applicable` messaging).
- `--rollback <section>` — renders (does not auto-run) the reverse-engineered
  commands for steps that have a public reversible API; for irreversible steps
  (`enable-centralized-rbac`, deleted users) it renders a Splunk Support
  ticket template instead.

## Supported Sections

Specs use `api_version: splunk-observability-cloud-integration-setup/v1` and
can include:

- `prerequisites` — version checks, region/realm map, FedRAMP/GovCloud/GCP
  carve-out, trial-stack rejection for LOC, Discover-app version preflight
  (10.1.2507+).
- `token_auth` — token-auth state read + flip, `edit_tokens_settings`
  capability check.
- `pairing` — Unified Identity (UID) via `acs observability pair` and `POST
  /adminconfig/v2/observability/sso-pairing`, or Service Account (SA) API-
  token connection. Multi-org pairing + Make Default deeplink. SE = SA only.
- `centralized_rbac` — `acs observability enable-capabilities` (provisions
  `o11y_admin / o11y_power / o11y_read_only / o11y_usage`) and
  `enable-centralized-rbac`; the `o11y_access` gate role; UID role mapping.
- `related_content_capabilities` — `read_o11y_content`, `write_o11y_content`,
  `EXECUTE_SIGNAL_FLOW`, `READ_APM_DATA`, `READ_BASIC_UI_ACCESS`, `READ_EVENT`
  capability assignments for Real Time Metrics + previews.
- `discover_app` — the five Configurations tabs of the in-platform Discover
  Splunk Observability Cloud app: Related Content discovery, Test related
  content, Field aliasing (Auto Field Mapping toggle), Automatic UI updates,
  Access tokens. Read-permission grant on the app to selected roles.
- `log_observer_connect` — service-account user + role + workload rule;
  Splunk Cloud Platform path or Splunk Enterprise TLS-certificate path.
  Hands off realm-IP allowlist deltas to `splunk-cloud-acs-allowlist-setup`.
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

1. **Cloud quickstart (greenfield)** — `--quickstart` against a fresh SCP
   stack with one O11y org; UID + SIM Add-on + Discover app + Related
   Content; about three prompts.
2. **Multi-org Cloud** — three O11y orgs paired to one SCP stack; enables
   Centralized RBAC; user picks which org becomes default via the rendered
   deeplink.
3. **Cloud SA-only (no UID)** — Service Account pairing only (no admin
   token required); SIM Add-on + Related Content; appropriate for stacks
   where UID is not yet in scope.
4. **Migrate SA -> UID** — existing SA-only customer wants Unified Identity;
   renderer detects existing SA connection, renders a numbered migration
   plan (pair UID, validate, instruct user to delete old SA via Discover
   app deeplink, optionally `enable-centralized-rbac`).
5. **Splunk Enterprise** — `--quickstart-enterprise` (SA + SIM + Related
   Content + LOC SE TLS path); UID/RBAC/Discover-app sections marked
   `not_applicable`; renders the cert-extraction helper + Workload Rule.
6. **Inherit existing integration** — `--discover` first, then `--doctor`
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
  `skills/splunk-cloud-acs-allowlist-setup/scripts/setup.sh --phase render
  --features search-api --search-api-subnets <pre-baked-realm-IPs>`.
- ACS Splunk Cloud Victoria-stack search-head HEC allowlist (SIM Add-on
  prerequisite) ➜ `skills/splunk-cloud-acs-allowlist-setup/scripts/setup.sh
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
  secret CLI flag, and redacts every token, password, JWT, and pairing-id
  from the rendered artifacts on disk.

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
