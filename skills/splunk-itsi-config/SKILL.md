---
name: splunk-itsi-config
description: Skill for previewing, applying, and validating native ITSI objects, selected ITSI content packs, and hybrid ITSI service-tree specs from repo-local YAML files. Use when Codex needs to manage ITSI entities, services, KPIs, dependencies, custom NEAPs, service-template links, or service trees, or when it needs to preview, install, and validate the AWS, Cisco Data Center, Cisco Enterprise Networks, Cisco ThousandEyes, Linux, Splunk AppDynamics, Splunk Observability Cloud, VMware, or Windows ITSI content packs through the official ITSI content-pack REST endpoints.
---

# Splunk ITSI Config

This skill is rooted in `skills/splunk-itsi-config/` and supports three workflows:

- Native ITSI automation for entities, services, KPIs, service dependencies, and custom NEAPs.
- Content-pack automation for preview, install, validate, and guided handoff for selected ITSI content packs.
- Hybrid topology automation for native objects, content packs, template-backed services, and ITSI service-tree dependencies in one run.

## Files

- Skill root: `skills/splunk-itsi-config/`
- Native template: `templates/native.example.yaml`
- Content-pack template: `templates/content_packs.example.yaml`
- Topology template: `templates/topology.example.yaml`
- Native references: `references/native_itsi.md`
- Content-pack references: `references/content_packs.md`
- Topology references: `references/topology.md`
- Entry points:
  - `bash scripts/setup.sh --workflow native --spec <path>`
  - `bash scripts/setup.sh --workflow native --spec <path> --apply`
  - `bash scripts/validate.sh --workflow native --spec <path>`
  - `bash scripts/setup.sh --workflow content-packs --spec <path>`
  - `bash scripts/setup.sh --workflow content-packs --spec <path> --apply`
  - `bash scripts/validate.sh --workflow content-packs --spec <path>`
  - `bash scripts/setup.sh --workflow topology --spec <path>`
  - `bash scripts/setup.sh --workflow topology --spec <path> --apply`
  - `bash scripts/validate.sh --workflow topology --spec <path>`

## Authentication

The scripts talk to the Splunk management port through the REST API.

Provide connection data either directly in the spec or through environment variables:

- `connection.base_url` or `SPLUNK_SEARCH_API_URI`
- `connection.session_key_env` or `SPLUNK_SESSION_KEY`
- `connection.username_env` or `SPLUNK_USERNAME`
- `connection.password_env` or `SPLUNK_PASSWORD`

Use a session key when possible. If you use username/password, the skill reads them from environment variables only. It never asks for secrets in chat.

## Native Workflow Rules

- Preview is the default.
- `--apply` is required for writes.
- Upserts are additive and idempotent for the managed fields in the spec.
- No delete or prune behavior is implemented in v1.
- Service dependencies are applied in a second pass after services exist.
- Managed or packaged NEAPs are protected from overwrite in v1.

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
