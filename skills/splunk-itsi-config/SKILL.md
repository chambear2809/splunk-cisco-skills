---
name: splunk-itsi-config
description: Configure and validate an existing, licensed Splunk IT Service Intelligence deployment from repo-local YAML. Use when managing ITSI entities, services, KPIs, dependencies, service trees, selected guarded operations, or ITSI content-pack imports; do not use it to install, upgrade, license, or restart ITSI or install prerequisite apps.
---

# Splunk ITSI Configuration

## Configuration-only boundary

This skill configures an **existing, licensed, healthy ITSI deployment**. It does
not install or upgrade ITSI, install the Splunk App for Content Packs, install a
Technology Add-on or Domain Add-on, apply a license, or restart Splunk.

- Missing or unhealthy ITSI: hand off to
  [`splunk-itsi-setup`](../splunk-itsi-setup/SKILL.md).
- Missing prerequisite app or compatible Content Library API/provider: hand off to
  [`splunk-app-install`](../splunk-app-install/SKILL.md) or the Splunk Cloud app
  request process.
- Missing source data: hand off to the matching source onboarding skill, then
  run [`splunk-data-source-readiness-doctor`](../splunk-data-source-readiness-doctor/SKILL.md).
- ITSI configuration work after those gates pass: remain in this skill.

Do not set `itsi.install_if_missing` or `content_library.install_if_missing` in
new specs. Legacy fields do not grant this skill permission to install apps.
Content-pack import through ITSI is configuration; installation of the ITSI,
legacy Content Library, or prerequisite app packages is not.

Whenever a content-pack workflow is involved, also follow the
[`shared completion gate`](../shared/ta_completion_gate.md). Package visibility
alone is not success: validate its data prerequisites, ITSI objects, shipped
views, macros, saved searches, and documented manual module steps.

## Coverage labels

Do not equate a generic REST payload route with complete product support. This
skill uses these labels:

| Label | Meaning |
| --- | --- |
| `typed` | The local YAML shape, references, preview, apply, and drift checks are implemented for the named fields. |
| `guarded` | A write is non-idempotent, destructive, or operational and requires an explicit safety gate. |
| `read-only` | The workflow performs local work or Splunk GET requests only. |
| `handoff` | Splunk documents the feature, but this skill intentionally sends the operator to another skill or the ITSI UI. |
| `experimental` | A version-shaped passthrough or helper exists, but end-to-end product support is not verified. Use only with exported payload evidence and a reviewed live preview. |
| `unsupported` | The workflow intentionally does not model or mutate the feature. |

Read [`references/product_coverage.md`](references/product_coverage.md) before
claiming feature coverage. It distinguishes the ITSI 4.21 implementation
baseline from the published ITSI 5.0 product and REST documentation. A generic
5.0 endpoint or schema entry is not proof that a new 5.0 UI, AI, or lifecycle
feature is safely automated; the applicable object contract must also be mapped
and validated against a live supported 5.0 deployment.

## Safe operating sequence

Every configuration run follows these gates in order.

### 1. Gather only non-secret intent

Ask for the target credential profile or management URL, platform, team/security
group, service and entity names, dependency order, data indexes/sourcetypes,
KPI signals and thresholds, and optional content packs. Detect installed
versions, licenses, roles, capabilities, and current objects from the target;
do not ask the user to transcribe facts that the read-only APIs can discover.

Never ask for passwords, tokens, API keys, or client secrets in chat. Never put
them in an ITSI spec.

### 2. Create a local spec

Copy the smallest matching starter to the gitignored local intake file, then
edit the copy rather than a committed example:

```bash
cp skills/splunk-itsi-config/templates/beginner.topology.yaml \
  skills/splunk-itsi-config/template.local
```

For a content pack, copy `beginner.content-pack.yaml` instead. Keep the first
run small and keep new services disabled until KPI health and thresholds have
been reviewed. Starter files set `metadata.template: true`; change it to `false`
only after every sample name, search, index, and placeholder has been replaced
and the preview has been reviewed.

### 3. Lint offline

Lint runs before credential loading and makes no network calls:

```bash
bash skills/splunk-itsi-config/scripts/setup.sh \
  --workflow topology \
  --spec skills/splunk-itsi-config/template.local \
  --mode lint
```

Use `--workflow native`, `content-packs`, or `topology` to match the spec. Lint
checks the schema version, structure, strict booleans, duplicate identities,
inline secrets, selected references/graphs, and guarded automation tiers. Apply
repeats lint with stricter template/example/placeholder refusal. Replace starter
values before live preview even when they are not fatal to the basic lint pass.

### 4. Preview and inspect the target read-only

Preview is the default and is a GET-only live operation:

```bash
bash skills/splunk-itsi-config/scripts/setup.sh \
  --workflow topology \
  --spec skills/splunk-itsi-config/template.local
```

For a brownfield native estate, add the read-only inventory gate:

```bash
bash skills/splunk-itsi-config/scripts/setup.sh \
  --workflow native \
  --spec skills/splunk-itsi-config/template.local \
  --mode inventory \
  --output /tmp/itsi-inventory.json
```

Together, lint, inventory, and preview are the current read-only preflight path.
Inventory covers the object/app/KV Store and supported route information it can
read; preview covers intended object changes and workflow prerequisites. There
is no separate `doctor` command yet. A future unified GET-only doctor should add
target/version, license, fine-grained capability/team access, and bounded data-
readiness checks. Until those checks are implemented, gather or hand them off
explicitly and do not claim doctor-complete evidence.

Catalog discovery and refresh are writes. Set
`content_library.refresh_catalog: true` only for an explicitly approved apply;
preview and validate never refresh the catalog.

### 5. Apply only after explicit approval

Summarize the exact target, creates, updates, guarded actions, warnings, and
manual work. Run apply only after the user explicitly approves that preview:

```bash
bash skills/splunk-itsi-config/scripts/setup.sh \
  --workflow topology \
  --spec skills/splunk-itsi-config/template.local \
  --apply
```

`--mode apply` is not a supported substitute for `--apply`. Never infer apply
permission from a request to inspect, lint, preview, validate, or diagnose.

### 6. Validate and hand off

```bash
bash skills/splunk-itsi-config/scripts/validate.sh \
  --workflow topology \
  --spec skills/splunk-itsi-config/template.local \
  --completion
```

Completion must distinguish clean validation, known manual follow-up, and an
actual failure. Report the target, detected versions, created/updated object
keys, drift, data-readiness evidence, content-pack module work, and the exact
next command or owner. A second preview after apply should report no unexpected
declarative changes.

## Workflow selection

Choose the smallest workflow that expresses the requested outcome:

- `content-packs`: import or validate a pack already available through the live
  ITSI Content Library API. This does not install ITSI, a legacy Content Library
  app, or the pack's prerequisite apps.
- `topology`: create a service tree from plain service, KPI, entity, dependency,
  and optional already-available pack references. This is the default for a new
  service model.
- `native`: manage direct ITSI objects, work from reviewed exports, or use
  advanced inventory, export, prune, cleanup, and guarded operational paths.

Start with [`references/beginner_quickstart.md`](references/beginner_quickstart.md).
Use the workflow-specific references only after choosing a path:

- [`references/native_itsi.md`](references/native_itsi.md)
- [`references/content_packs.md`](references/content_packs.md)
- [`references/topology.md`](references/topology.md)
- [`references/compatibility.md`](references/compatibility.md)
- [`references/product_coverage.md`](references/product_coverage.md)

## Authentication and target safety

The scripts use the Splunk management API, normally HTTPS on port 8089. The
wrappers load the repository credential file, then `~/.splunk/credentials`, or
the file named by `SPLUNK_CREDENTIALS_FILE`.

Supported non-secret connection selectors are:

- `connection.base_url` or `SPLUNK_SEARCH_API_URI`
- `connection.session_key_env` or `SPLUNK_SESSION_KEY`
- `connection.username_env` or `SPLUNK_USERNAME`
- `connection.password_env` or `SPLUNK_PASSWORD`
- `connection.verify_ssl` or `SPLUNK_VERIFY_SSL`
- `connection.allow_insecure_tls` or `SPLUNK_ALLOW_INSECURE_TLS`
- `connection.ca_cert_file` or `SPLUNK_CA_CERT`
- `connection.allow_insecure_http: true` only for a separately accepted,
  short-lived loopback lab endpoint

TLS verification defaults to true. Prefer a private CA bundle over disabling
verification. `verify_ssl: false` is rejected unless the operator also sets
`connection.allow_insecure_tls: true` (or
`SPLUNK_ALLOW_INSECURE_TLS=true`) for an explicitly accepted, short-lived lab
target. Insecure HTTP and disabled certificate verification are never valid
production completion evidence.

Use a session key when possible. Keep username/password values in the credential
file. The spec contains environment variable names, never secret values.

Official ITSI permissions are object- and team-specific. Preview should surface
the missing capability rather than encourage a broad admin credential. Global
objects such as service templates and KPI templates also require Global-team
write access. See the official
[ITSI roles and capabilities](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/administer/4.21/permissions/configure-users-and-roles-in-itsi).

## Native rules

- Normal native preview/apply/validate is additive. It preserves unmanaged live
  fields and extra KPIs unless an explicitly documented reconciliation path is
  used.
- Core typed coverage is entities, services, embedded KPIs, service
  dependencies, service-template links, custom-threshold-window links, and
  custom NEAP definitions. Consult the coverage matrix for important limits.
- Generic object sections are experimental passthroughs, not schema-complete
  support. Use a payload exported from the same ITSI version and review the live
  preview.
- Service-template REST linking has append-only entity-rule semantics in this
  workflow. Use the ITSI UI when the operator needs replace or keep-existing
  choices.
- `bulk_apply`, glass-table generation, and schema passthrough are advanced and
  remain experimental until validated against the exact live version.
- Export, inventory, and prune-plan are read-only. A prune plan never deletes.
- Cleanup requires a current reviewed plan, explicit candidate IDs, a delete
  ceiling, confirmation strings, and backup output. Protected or unsupported
  objects remain manual review.
- `operational_actions` are non-idempotent. Do not include them in a reusable
  declarative spec. Each invocation requires explicit operator intent and the
  action-specific guards documented in `references/native_itsi.md`.
- A restore, ticket/action execution, episode mutation, retire/restore, bulk
  update, content-pack lifecycle action, threshold recommendation application,
  or destructive transition is never implied by normal configuration intent.

## Content-pack rules

- ITSI, a compatible live Content Library API/provider, and prerequisite apps
  must already be installed or product-provided, enabled, licensed where
  applicable, and healthy. For ITSI 4.21 this normally includes the compatible
  Splunk App for Content Packs. Do not infer ITSI 5.0 packaging from a 4.21 spec.
- Preview and validate are GET-only. Import uses the official ITSI content-pack
  endpoint only after preview and explicit apply approval.
- A catalog refresh is apply-only and opt-in with
  `content_library.refresh_catalog: true`.
- Pack IDs and versions are resolved from the live catalog by exact title or ID.
- Safe import defaults keep imported services and saved searches disabled,
  avoid backfill, use conflict resolution `skip`, and avoid non-empty prefixes.
- Rich profiles add app/input/macro checks. Generic catalog entries provide
  catalog/import visibility plus explicit manual follow-up; they do not imply
  pack-specific data or dashboard validation.
- `configured_outcome` is allowed only for the documented typed blocks and
  guards. Unsupported module wizards, service discovery, alert integrations,
  and sandbox publication remain handoffs.

Supported profile keys currently include:

`aws`, `cisco_data_center`, `cisco_enterprise_networks`,
`cisco_thousandeyes`, `citrix`, `example_glass_tables`,
`ite_work_alert_routing`, `itsi_monitoring_and_alerting`, `linux`,
`microsoft_365`, `microsoft_exchange`,
`netapp_data_ontap_dashboards_reports`, `pivotal_cloud_foundry`, `servicenow`,
`shared_it_infrastructure`, `soar_system_logs`, `splunk_appdynamics`,
`splunk_observability_cloud`, `splunk_as_a_service`,
`splunk_synthetic_monitoring`, `third_party_apm`, `unix_dashboards_reports`,
`vmware`, `vmware_dashboards_reports`, `windows`, and
`windows_dashboards_reports`.

Only AWS, Cisco, Linux, AppDynamics, Observability, VMware, and Windows profiles
currently have richer local readiness checks. All other profiles are catalog-
generic unless `configured_outcome` provides a reviewed typed configuration.

## Topology rules

- A node defines exactly one of `service_ref` or `service`.
- Template-backed nodes use `service` plus `from_template`.
- Reuse shared downstream services with `ref`; duplicate materializations,
  unresolved references, self-dependencies, missing explicit KPI names, and
  cycles fail lint or preview.
- Pack-relative resolution is read-only in preview and must resolve to live
  objects after an approved import.
- Topology cleanup uses the same guarded native cleanup model. Topology-derived
  service titles are protected from unmanaged candidates.
- The glass-table generator creates a review starter only; it is not evidence
  that the visual layout is accepted or useful in the target ITSI version.

## Reports and evidence

Content-pack runs write
`skills/splunk-itsi-config/reports/<timestamp>/content-pack-summary.md`.
Topology runs write
`skills/splunk-itsi-config/reports/<timestamp>/topology-summary.md`.
Native runs emit structured JSON and optional export/inventory/prune artifacts.

Do not report success from package presence or object creation alone. Completion
evidence should include the post-apply validation result, data readiness for KPI
searches, expected service/dependency state, content-pack dashboards or explicit
evidence that none ship, and named manual follow-up with an owner.
