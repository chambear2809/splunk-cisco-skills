---
name: splunk-itsi-config
description: Skill for previewing, applying, and validating native ITSI objects, selected ITSI content packs, and hybrid ITSI service-tree specs from repo-local YAML files. Use when Codex needs to manage ITSI entities, services, KPIs, dependencies, custom NEAPs, service-template links, or service trees, or when it needs to preview, install, and validate the AWS, Cisco Data Center, Cisco Enterprise Networks, Cisco ThousandEyes, Linux, Splunk AppDynamics, Splunk Observability Cloud, VMware, or Windows ITSI content packs through the official ITSI content-pack REST endpoints.
---

# Splunk ITSI Config

This skill is rooted in `skills/splunk-itsi-config/` and supports these workflow paths:

- Native ITSI automation for entities, services, KPIs, service dependencies, and custom NEAPs.
- Extended native ITSI automation for teams, entity types, service templates, KPI base searches, KPI templates, KPI threshold templates, custom threshold windows and service/KPI links, custom content packs, correlation searches, Event Analytics configuration, maintenance windows, backup jobs, glass tables/icons, deep dives, and home views through typed REST passthrough sections.
- Content-pack automation for preview, install, validate, and guided handoff for selected ITSI content packs.
- Hybrid topology automation for native objects, content packs, template-backed services, and ITSI service-tree dependencies in one run.

## Beginner-First Operating Model

When a user wants ITSI configured but does not already have an ITSI spec, start in guided preview mode:

1. Translate the request into plain ITSI building blocks: business services, supporting technical services, KPIs, entities, dependencies, and optional content packs.
2. Ask only for missing non-secret facts: Splunk platform, management URL, target app/domain, supported source products, index names, sourcetypes, service names, dependency order, and desired KPI signals.
3. Do not ask the user for ITSI REST payload fields unless they are importing or editing exported ITSI objects.
4. Pick the smallest workflow that gets the user to a useful preview:
   - Use `content-packs` when the user has data for a supported packaged domain and wants Splunk-provided defaults quickly.
   - Use `topology` when the user can name services, dependencies, and KPI searches but does not know ITSI object schemas.
   - Use `native` only for direct ITSI object management, exported payloads, custom NEAPs, glass tables, maintenance windows, or other advanced objects.
5. Create or adapt a repo-local YAML spec from the beginner templates, default new services to `enabled: false`, then run preview before any write.
6. Summarize preview output in operator language: what will be created, what prerequisites are missing, which searches/macros/indexes need attention, and what will remain manual.
7. Run `--apply` only when the user explicitly asks to apply or confirms the preview. After apply, run validate and point the user at the generated report.

Useful quickstart files:

- Beginner guide: `references/beginner_quickstart.md`
- Beginner content-pack template: `templates/beginner.content-pack.yaml`
- Beginner topology template: `templates/beginner.topology.yaml`

## Files

- Skill root: `skills/splunk-itsi-config/`
- Native template: `templates/native.example.yaml`
- Content-pack template: `templates/content_packs.example.yaml`
- Topology template: `templates/topology.example.yaml`
- Beginner content-pack template: `templates/beginner.content-pack.yaml`
- Beginner topology template: `templates/beginner.topology.yaml`
- Beginner quickstart reference: `references/beginner_quickstart.md`
- Native references: `references/native_itsi.md`
- Content-pack references: `references/content_packs.md`
- Topology references: `references/topology.md`
- Offline compatibility report: `references/compatibility.md`
- Entry points:
  - `bash scripts/setup.sh --workflow native --spec <path>`
  - `bash scripts/setup.sh --workflow native --spec <path> --apply`
  - `bash scripts/setup.sh --workflow native --spec <path> --mode export --output exported.native.yaml --output-format yaml`
  - `bash scripts/setup.sh --workflow native --spec <path> --mode inventory --output inventory.json`
  - `bash scripts/setup.sh --workflow native --spec <path> --mode prune-plan --output prune-plan.json`
  - `bash scripts/setup.sh --workflow native --spec <path> --mode cleanup-apply --backup-output cleanup-backup.native.yaml`
  - `bash scripts/validate.sh --workflow native --spec <path>`
  - `bash scripts/setup.sh --workflow content-packs --spec <path>`
  - `bash scripts/setup.sh --workflow content-packs --spec <path> --apply`
  - `bash scripts/validate.sh --workflow content-packs --spec <path>`
  - `bash scripts/setup.sh --workflow topology --spec <path>`
  - `bash scripts/setup.sh --workflow topology --spec <path> --apply`
  - `bash scripts/validate.sh --workflow topology --spec <path>`
  - `python3 scripts/topology_glass_table.py --spec-json <path> --output topology-glass.native.yaml --output-format yaml`
  - `python3 scripts/native_offline_smoke.py --spec-json <path>`
  - `python3 scripts/itsi_compatibility_report.py --format markdown`

## Authentication

The scripts talk to the Splunk management port through the REST API.

The shell wrappers load the repository credential file first, then fall back to
`~/.splunk/credentials` or `SPLUNK_CREDENTIALS_FILE` through the shared credential
helper. They export only the variables needed by the Python client.

Provide non-secret connection data directly in the spec or through the credential
file/environment:

- `connection.base_url` or `SPLUNK_SEARCH_API_URI`
- `connection.session_key_env` or `SPLUNK_SESSION_KEY`
- `connection.username_env` or `SPLUNK_USERNAME`
- `connection.password_env` or `SPLUNK_PASSWORD`

Use a session key when possible. If you use username/password, keep the secret
values in the credential file; the wrappers prefer Splunk REST credentials from
`SPLUNK_USER` / `SPLUNK_PASS` and export them as `SPLUNK_USERNAME` /
`SPLUNK_PASSWORD` for this client. Never put passwords, tokens, or API keys in
an ITSI YAML spec or in chat.

## Native Workflow Rules

- Preview is the default.
- `--apply` is required for writes.
- Native read-only modes are available through `setup.sh --workflow native --mode export|inventory|prune-plan`. `export` writes a brownfield native spec skeleton, `inventory` reports live ITSI object counts/app versions/KV Store status, and `prune-plan` reports unmanaged live objects without deleting anything.
- Guarded cleanup is available through `setup.sh --workflow native --mode cleanup-apply --backup-output <path>`. It recomputes the current prune plan, requires `cleanup.allow_destroy: true`, `cleanup.confirm: DELETE_UNMANAGED_ITSI_OBJECTS`, a matching `cleanup.plan_id`, positive `cleanup.max_deletes`, and explicit `cleanup.candidate_ids`. The CLI writes a live export backup before deleting.
- `python3 scripts/native_offline_smoke.py --spec-json <path>` runs native preview/apply/validate/export/inventory/prune-plan against an in-memory ITSI-shaped client. Use it for regression checks without touching a live ITSI instance.
- Upserts are additive and idempotent for the managed fields in the spec.
- Delete behavior is limited to guarded cleanup candidates from a fresh prune plan. Unsupported cleanup candidates, including content-pack authorship objects, glass-table icons, and KPI entity thresholds, are reported for manual review rather than deleted.
- Validation diagnostics include field-level diffs for managed drift where the live object exists.
- Preview/apply/validate emit warning diagnostics for obvious KPI/correlation-search preflight issues, such as searches without explicit index constraints or threshold fields not visible in the SPL text.
- Core `entities`, `services`, and service `kpis` support typed convenience fields and also merge additional top-level ITSI schema fields plus `payload` into the REST body. Local DSL keys such as `depends_on`, `service_template`, and threshold helpers are not sent as raw schema fields.
- Extended object sections set common ITSI fields (`title`, `description`, `sec_grp`, `object_type`) and merge additional top-level fields plus `payload` into the REST request body. Use exported ITSI payload fields when managing version-specific object shapes.
- Keyed updates on the generic ITSI, Event Management, maintenance, and backup/restore route families set `is_partial_data=1` so unmanaged fields are preserved. Full-payload special routes such as `kpi_entity_threshold`, icon collection, and content-pack authorship do not use that parameter.
- Service template links are applied through the ITSI service template link endpoint after services exist and before dependencies are validated or merged.
- `custom_threshold_window_links` are applied after services exist by resolving window/service/KPI titles or live IDs and calling the ITSI custom-threshold-window service/KPI association endpoint only for missing links.
- `entity_type_titles` on entities resolve against live entity types or entity types declared earlier in the same spec.
- Custom content packs use the ITSI content pack authorship API. Backup jobs, maintenance windows, Event Analytics, and glass-table icons use their documented ITSI route families rather than the default object route.
- Event Management sections (`event_management_states`, `correlation_searches`, `notable_event_email_templates`, and `neaps`) use the ITSI `event_management_interface` and its `filter_data` lookup parameter. Creates are wrapped in the documented `data` envelope; keyed updates send the object payload directly.
- Deep dive updates preserve the existing owner fields in the payload because Splunk requires those fields on keyed deep-dive updates.
- Operational Event Analytics records and append-only APIs, such as notable events, notable event groups, comments, and ticket/action execution, are intentionally excluded from the idempotent upsert model.
- ITSI action/helper APIs such as entity retire/restore, threshold recommendations, custom threshold window stop/disconnect, and bulk time-offset shifts are intentionally excluded from the normal idempotent upsert model.
- Guarded `operational_actions` can run selected non-idempotent helper APIs only when every action sets `allow_operational_action: true`. Use these for explicit operator-driven retire/restore, custom-threshold stop/disconnect, recommendation-apply, or time-offset-shift work; they are not part of normal config drift validation. Custom-threshold disconnect also requires `disconnect_all: true` because the documented endpoint has no selective request payload; `entity_retire_retirable` also requires `retire_all_retirable: true` because it retires every entity currently marked retirable.
- Service dependencies are applied in a second pass after services exist.
- Custom NEAPs use the ITSI event management interface. Managed, packaged, and default NEAPs are protected from overwrite in v1.

## Content-Pack Workflow Rules

- On `--apply`, the workflow can bootstrap Splunk IT Service Intelligence (`SA-ITOA`) by delegating to the generic app-install path described by `../splunk-itsi-setup/SKILL.md`, using Splunkbase app `1841` by default.
- Preview and validate remain read-only. If ITSI is missing, they stop and tell the operator to rerun with `--apply` or install app `1841` manually first.
- On Splunk Enterprise `--apply`, the workflow can bootstrap the Splunk App for Content Packs (`DA-ITSI-ContentLibrary`) by calling the shared installer in `../splunk-app-install/scripts/install_app.sh`.
- If the packaged `5391` archive is rejected by the REST app-install endpoint because it contains multiple top-level apps, the workflow falls back to a Splunk CLI install path on the target host.
- Before catalog lookup, the workflow refreshes Content Library discovery through `DA-ITSI-ContentLibrary/content_library/discovery` when that endpoint is available.
- For the content-pack API, the client probes `/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/content_pack` first and falls back to `/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack` on hosts that expose the legacy route family.
- The default Enterprise bootstrap path installs Splunkbase app `5391`. Override the source with `content_library.source: local` and `content_library.local_file: /absolute/path/to/package.spl` if you need to use a local package instead.
- Preview and validate remain read-only. If `DA-ITSI-ContentLibrary` is missing, they stop and tell the operator to rerun with `--apply` on Splunk Enterprise.
- If `DA-ITSI-ContentLibrary` is missing on Splunk Cloud, stop and guide the operator to open a Splunk Support / Cloud App Request for app `5391`.
- After ITSI bootstrap or validation, the workflow checks the bundled ITSI app set (`SA-ITOA`, `itsi`, `SA-UserAccess`, `SA-ITSI-Licensechecker`) plus KV Store readiness and key ITSI collections.
- Prerequisite health check failures are surfaced in the JSON/report output and cause the CLI wrappers to return a nonzero exit code.
- Pack IDs and versions are discovered live from the ITSI content-pack catalog.
- Pack resolution is by exact catalog title, not hardcoded package ID.
- For validation, the workflow resolves the live bundled content-pack app from profile-specific app candidates instead of assuming the catalog ID matches the installed app name.
- Profiles that ship known companion dashboard apps report those as additional bundle-aware checks.
- The workflow always calls the official content-pack `preview` endpoint before install.
- Install requests default to:
  - `resolution: skip`
  - `enabled: false`
  - `saved_search_action: disable`
  - `install_all: true`
  - `backfill: false`
  - `prefix: ""`
- Post-install module flows remain guided in v1. The skill stops at install, validation, and a generated handoff report.

## Topology Workflow Rules

- The topology workflow is hybrid. It can combine `packs`, native `entities` / `services` / `neaps`, and a top-level `topology` block in one spec.
- Preview is the default. `--apply` is required for writes.
- The workflow reuses the content-pack bootstrap, ITSI health checks, and pack validation path before native object upserts and topology materialization.
- `topology.roots` uses a nested DSL that compiles to ITSI `services_depends_on` edges.
- `python3 scripts/topology_glass_table.py --spec-json <path> --output <path>` generates a starter native `glass_tables` spec from the same topology tree for operator review and later apply.
- A topology node must define either `service_ref` or `service`.
- Template-backed nodes use `service` plus `from_template`, where `from_template` resolves a content-pack profile and logical template title.
- Shared downstream services are expressed with `ref` nodes; duplicate materialized nodes that resolve to the same service title are rejected.
- Preview can resolve pack-relative services and templates from the content-pack `preview` response even when they are not installed yet.
- Apply and validate require live template and service resolution for anything that must exist in ITSI after install.
- Self-dependencies, missing references, missing explicit KPI names, and cycles fail the run.
- No delete or prune behavior is implemented in v1.

## Supported Content-Pack Profiles

- `aws`
- `cisco_data_center`
- `cisco_enterprise_networks`
- `cisco_thousandeyes`
- `linux`
- `splunk_appdynamics`
- `splunk_observability_cloud`
- `vmware`
- `windows`

Each profile has preset app checks, input-readiness checks, and guided next steps.

## Reports

Every content-pack run writes a report under `reports/<timestamp>/content-pack-summary.md`.

Every topology run writes a report under `reports/<timestamp>/topology-summary.md`.

Use that report to hand off the remaining module-driven steps after install.
