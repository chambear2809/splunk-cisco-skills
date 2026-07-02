# ITSI Product Coverage and Version Posture

Last source review: **2026-07-02**.

This document separates product awareness from verified automation. A feature
appearing in ITSI documentation, a REST schema, or a generic local passthrough
does not by itself make the feature safely automated by this skill.

## Version posture

- **ITSI 4.21 is the current implementation baseline for this skill.** The local
  route model and compatibility notes were developed against the 4.21 REST
  reference, with 4.21.2 named in existing route notes. Unit tests use fake or
  in-memory clients; they are not a live-version certification.
- **Use `vLatest` or the unversioned interface as Splunk recommends.** A payload
  exported from one version is not assumed to be valid on another version.
- **ITSI 5.0 REST documentation is published, but this skill is not live-5.0
  certified.** Splunk published a 5.0 REST reference and schema dated June 30,
  2026. Those sources establish documented route families; they do not prove
  that every new 5.0 product experience has a corresponding safe CRUD contract,
  or that this client's 4.21-shaped payloads have been exercised against 5.0.
  New 5.0 areas remain `handoff` or `experimental` below until their applicable
  object contract is mapped and live contract evidence is recorded.
- Detect the actual Splunk Platform, ITSI, Content Library, and content-pack
  versions before preview. Stop on an unsupported or unknown combination rather
  than coercing a 4.21 payload into a newer object shape.

## Coverage labels

| Label | Evidence required |
| --- | --- |
| `typed` | A defined local shape, reference validation, preview/apply/drift behavior, and focused tests. |
| `guarded` | An explicit second safety decision for a non-idempotent, destructive, or operational call. |
| `read-only` | Local processing or GET requests only; no discovery refresh, dispatch, package operation, or restart. |
| `handoff` | A documented product/UI or another repository skill owns the operation. |
| `experimental` | A helper or passthrough exists, but live support and semantic validation are incomplete. |
| `unsupported` | The workflow intentionally does not model the feature. |

## Current automation matrix

| Product area | Status | What this skill can do | Important limit or handoff |
| --- | --- | --- | --- |
| Offline spec gate | `read-only` | Parse and lint native, content-pack, and topology specs before credentials or network access. | Lint success does not prove that an ITSI-version-specific passthrough payload is accepted by a live host. |
| Target inventory and drift | `read-only` | Preview desired changes; inventory object/app/KV Store state; export supported object shapes; produce a prune plan. | Read-only paths must remain GET-only. A prune plan is not permission to delete. |
| Entities | `typed` | Additive create/update of identifiers, informational fields, entity-type references, Global ownership, description, and reviewed schema payload fields. | ITSI entities are Global objects; non-Global `sec_grp` is rejected. Data-backed discovery quality and entity vital metrics need live validation; generic entity-management policy/rule shapes are experimental. |
| Entity discovery, imports, and lifecycle | Discovery is `read-only`; policies/rules are `experimental`; retirement/restore is `guarded`; import wizards are `handoff` | Inventory selected entity-discovery searches and retirable targets; pass through same-version policy/rule payloads; retire or restore explicit entities with one-run guards. | CSV, search, and recurring-import schedules; merge/overwrite choices; rule quality; and vital-metric coverage require product workflow or live validation. Never retire every eligible entity when target discovery is incomplete. |
| Services and embedded KPIs | `typed` | Additive service/KPI upsert, entity rules, tags, thresholds, KPI importance, and selected typed search fields. | The local SPL preflight is heuristic. Completion requires a bounded live search and proof that the threshold/entity fields and recent data exist. Removing omitted KPIs is not implied. |
| KPI sources, calculations, and thresholding | Core search/calculation/static-threshold fields are `typed`; templates, adaptive/entity thresholds, and recommendation helpers are `experimental` or `guarded` | Configure selected event/metrics KPI search fields, split/entity fields, calculations, gap severity, importance, static levels, threshold windows, and reviewed recommendation payloads. | Time policies, adaptive/outlier model quality, per-entity threshold version support, threshold propagation, and health-score effects require live target evidence. Deprecated metric anomaly detection is migration-only. |
| Service dependencies and topology trees | `typed` | Resolve services and KPI references, materialize dependency edges, reuse shared nodes, and reject topology cycles/self-dependencies. | Native and topology specs must be linted before apply; large-scale product topology discovery remains a separate data/modeling exercise. |
| Service-template links | `typed` with UI `handoff` | Link an existing service to an existing template and validate the link. | The REST path used here has append-only entity-rule behavior. Use the UI for replace/keep-existing decisions. Creating and propagating a template from a service is not claimed as a fully typed workflow. |
| Service-template creation, propagation, and sandboxes | `experimental` / `handoff` | Pass through same-version template or sandbox-shaped objects and link selected existing templates. | Template propagation, tag synchronization, sandbox discovery/edit/publish, service enablement, and merge choices are product workflows. A generic sandbox route is not lifecycle automation. |
| KPI base searches, KPI templates, threshold templates | `experimental` | Pass through an export-shaped object and use it from a reviewed service/KPI payload. | Exact fields and propagation semantics are version-specific. Use same-version exports and live preview. |
| Custom threshold windows and links | Link is `typed`; object payload is `experimental`; stop/disconnect is `guarded` | Associate existing services/KPIs with a reviewed window; invoke separately approved stop/disconnect helpers. | Recurrence and window schema must come from same-version evidence. Operational helpers are not reusable desired state. |
| Teams and permissions | Team payload is `experimental`; RBAC is `handoff` | Read or pass through team-shaped objects. | Role creation, inherited capabilities, Global-team access, and least-privilege design require Splunk authorization governance. Do not infer access from a successful login. |
| Correlation searches and KPI alerting | Correlation payload is `experimental`; KPI alert behavior is part of reviewed KPI config plus live `handoff` | Pass through selected correlation-search fields and preserve route-specific naming/filter behavior. | KPI and multi-KPI alert firing, schedule, lag, suppression, normalized fields, and action credentials require bounded search and live episode evidence. |
| Event Analytics and NEAPs | Custom baseline NEAP path is `typed`; advanced filters/splits/breaks/actions and 5.0 priority are `experimental` | Manage custom aggregation-policy intent while protecting managed/default policies; carry same-version advanced fields through reviewed payloads. | Smart Mode, action rules, episode fields, split/break semantics, priority ordering, and cross-team episode sharing require exact-version product validation. |
| Episodes, notable events, actions, tickets, and exports | Inventory is `read-only`; mutations are `guarded` | Bounded readback plus explicitly approved comments, field changes, action execution, ticket links, and export lifecycle helpers. | These calls are operational and often non-idempotent. Keep them out of reusable configuration specs and require one-run intent. |
| Maintenance windows | `experimental` | Pass through a same-version maintenance payload and inspect selected status information. | Service/entity scope, team access, recurrence, time zone, dependency impact, and safety buffers require operator review. |
| Service Analyzer home views, glass tables, icons, and deep dives | `experimental` | Pass through exported objects; generate a starter glass-table payload for review. | A generated or accepted payload does not prove a useful visual layout, working drilldown, or data-populated panel. Validate in the ITSI UI. |
| Backup jobs | Readback/export is `read-only`; job payload is `experimental`; restore is `guarded`/`handoff` | Inventory or pass through a reviewed backup-job shape. | Local export is not equivalent to an ITSI recovery backup. Restore can overwrite matching objects and requires ITSI dependency, permission, and service-template-sync checks. |
| Runtime health and outcome validation | `read-only` / `handoff` | Compare managed fields, inspect selected status/count endpoints, and run heuristic SPL checks. | Object equality does not prove KPI summary freshness, health scores, entity matching, backfill completion, episode grouping, maintenance activation, or populated visualizations. Completion needs bounded live searches and product evidence. |
| Predictive analytics and model training | `read-only` / `handoff` | Inventory relevant KPI/threshold posture and document MLTK/PSC prerequisites. | Training, retraining, model acceptance, drift/outlier quality, and migration from deprecated anomaly detection remain ITSI/MLTK product workflows; use [`splunk-ai-ml-toolkit-setup`](../../splunk-ai-ml-toolkit-setup/SKILL.md) for platform prerequisites. |
| ITSI admin health and upgrade diagnostics | `read-only` / `handoff`; raw upgrade-precheck route is `experimental` | Inventory app/KV Store/object state and report missing readiness evidence. | Configuration Assistant, NATS/Event Analytics health, license/core-app repair, upgrade orchestration, and platform restart belong to [`splunk-admin-doctor`](../../splunk-admin-doctor/SKILL.md) or [`splunk-itsi-setup`](../../splunk-itsi-setup/SKILL.md). Never mutate ITSI KV Store collections directly. |
| Content Library catalog and pack preview | `read-only` | Read catalog, detail, status, installed version, and ITSI pack preview without refreshing discovery. | A compatible provider/API must already exist. Content Packs app 2.5 explicitly lists ITSI 4.20.x and 4.21.x compatibility. The 5.0 UI update does not prove that the legacy discovery endpoint or app is bundled; version-gate 5.0 until the live catalog route and documented provider are confirmed. A stale catalog is reported, and refresh is a separately approved apply-only write. |
| Content-pack import | `typed` for the import envelope; profile checks vary | Resolve exact live title/ID/version, preview, import with conservative defaults, and validate installed visibility. | ITSI, a compatible Content Library API, and prerequisite apps must already exist. Generic profiles do not imply pack-specific data, dashboard, macro, or module validation. |
| Post-pack configured outcomes | Typed blocks plus `guarded` dispatches | Update existing macros/saved searches/conf stanzas, selected data-model acceleration, dashboard/navigation XML, staged lookups, and reviewed dispatch/import tasks. | Each block retains its own platform and safety limits. Module wizards, alert-integration wizards, service discovery, and sandbox publication are handoffs. |
| Cleanup | `guarded` | Recompute a prune plan, require candidate IDs/limits/confirmations, write a backup artifact, and delete only eligible reviewed keys. | Unsupported, keyless, shipped, and protected objects remain manual review. A local export is not guaranteed to be a complete restore point. |
| Bulk updates and time shifts | `experimental` and `guarded` | Use documented helper routes for explicitly selected payloads. | Response semantics, concurrency, partial failures, and product-version behavior require live evidence. Prefer normal typed paths. |
| Sandboxes, refresh queues, upgrade prechecks, and user preferences | `experimental` | Pass through objects when an operator supplies an export from the same live version. | These families are not all present in the official generic object list. Route probing is not proof of supported CRUD semantics. |
| Event iQ summarization and feedback records | `read-only` / apply-blocked | Inventory or validate same-version `summarization` and `summarization_feedback` records. | The 5.0 REST reference models asynchronous episode summary requests/results and per-user feedback, not ordinary titled desired state. Declarative apply rejects these sections. |
| Event iQ Diagnose summarization rules | `experimental`, ITSI 5.0 only | Pass through a reviewed, same-version `summarization_rule` payload. | The route can update attached NEAP action rules, and the official reference contains suspect copied examples. Require 5.0 detection, an exported payload, an explicit experimental gate, and live round-trip validation. |
| Entity relationship objects | `unsupported` | None. | The 4.21 REST documentation describes relationship object types as unused; this skill does not manage them. |
| ITSI install, upgrade, license, restart, and package topology | `handoff` | Detect that a prerequisite is missing or unhealthy. | Use `splunk-itsi-setup`, `splunk-app-install`, Splunk Cloud Support, and topology-specific restart/deployment workflows. |

## ITSI 4.21 feature posture

The official 4.21 release material documents features including Content Packs
2.5 compatibility, Splunk V2 API support, backup/restore dependency prechecks,
entity adaptive thresholds, recurring maintenance windows, navigation links,
and the Cisco Enterprise Networks content pack.

| 4.21 feature | Local posture |
| --- | --- |
| Content Packs 2.5.x | Catalog/import envelope is typed; richer validation exists only for named profiles. Prerequisite app installation is a handoff. |
| Splunk V2 APIs | Compatibility consideration only. Do not claim every custom/local route has V2 contract coverage. |
| Backup/restore dependency prechecks | Product-owned. Local inventory can provide evidence, but the product precheck and restore UI/API remain authoritative. |
| Adaptive thresholds for entities | Experimental payload/readback only; no claim of typed recommendation lifecycle or model-quality validation. |
| Recurring maintenance windows | Experimental same-version payload; validate recurrence, time zone, scope, and impacted KPIs live. |
| Navigation links for service templates and entity types | Experimental schema passthrough; validate rendering and target URLs in the UI. |
| Cisco Enterprise Networks content pack | Named profile with prerequisite/input/macro checks plus documented module handoffs; completion still requires live data and dashboard/service evidence. |

## ITSI 5.0 feature posture

Splunk's official ITSI 5.0 new-features page and announcement describe the
following product capabilities. The 5.0 REST reference and schema are now
published. These areas are tracked so the skill does not silently ignore new
product coverage, but a broad REST publication is not enough to promote an area
to typed automation: the applicable object schema, mutability, permissions,
lifecycle semantics, and live behavior must all be verified.

| ITSI 5.0 area | Local status | Safe treatment now |
| --- | --- | --- |
| New guided installer and ITSI Home/Mission Control | `handoff` | Installation and first-run UI remain product/`splunk-itsi-setup` work. The config skill may report readiness only. |
| Broader alert integrations and AI-assisted field discovery/mapping | `handoff` | Model normalized correlation-search intent only when the operator provides documented fields; perform mapping and connection setup in the supported UI/integration workflow. |
| AI-powered Service and KPI Discovery preview with sandbox review | `handoff` / `experimental` | Do not equate generic sandbox routes with support for the 5.0 AI workflow. Use the product preview UI and publish only after review. |
| Content Library interface and pack lifecycle improvements | `handoff` pending route/provider evidence | Continue conservative catalog preview/import only after the version-compatible provider and live routes are confirmed. Do not infer that Content Packs app 2.5 or its legacy discovery endpoint is bundled with 5.0, and do not automate upgrade/removal semantics from the 4.21 contract. |
| New alert/event Data Model Definition | `handoff` pending object mapping | Track data normalization readiness; do not infer fields or migration payloads from a generic schema publication. |
| Redesigned Episode Review, saved/shared views, episode split and merge | `handoff`; existing limited helpers remain `guarded` | Use the UI for new collaborative workflows until a supported API and idempotent safety model are verified. |
| Central Admin Console | `handoff` | Report relevant configuration gaps, but do not claim console-wide settings automation. |
| Improved notable event aggregation policies | `experimental` for export-shaped payloads | Existing custom NEAP support does not establish coverage for new 5.0 policy controls or learning settings. |
| Team ownership, shared services/episodes, cross-team dependencies, and fine-grained actions | `handoff` / version-gated | Detect roles/capabilities/team access and preserve least privilege; do not infer 5.0 owner/shared-team semantics from legacy `sec_grp`. Do not migrate authorization automatically. |
| Event iQ Detect, feedback learning, retraining, and topology-aware correlation | `handoff` | Generic feedback/summarization routes do not establish this workflow's control plane or model-quality semantics. Use product workflows and capture validation evidence. |
| Event iQ Diagnose summaries, likely cause, recommendations, and change context | `handoff`; record/rule routes are `read-only` or `experimental` | The 5.0 REST reference documents summarization, feedback, and rule routes, but this skill has no typed LLM/evaluation workflow claim. Validate entitlement, privacy, data flow, and product output in ITSI. |
| Third-party CMDB/change enrichment | `handoff` | Onboard and validate source integrations separately; document field and ownership mappings without inventing private APIs. |
| Structured key-value service/template/sandbox tags and migration | `handoff` / version-gated | Legacy tag payload awareness is not typed 5.0 structured-tag support. Use the product workflow until validation, limits, migration, and template-sync behavior are modeled and live-tested. |
| Flexible recurring/multi-day maintenance, external CIs, outage import, and ServiceNow sync | `handoff` / `experimental` | Use same-version documented payloads only for the basic explicit-object shape; keep recurrence, targeting rules, external CIs, imports, and synchronization in the product workflow. Validate calendar semantics and suppression effects in ITSI. |
| Dynatrace, Zabbix, Oracle Enterprise Manager, and Datadog alert integrations | `handoff` | Onboard credentials and map/normalize alerts through the documented ITSI 5.0 data-integration workflow. The local generic data-integration-template passthrough is not equivalent to supported connection setup. |

## Required handoffs

Stop configuration and produce an explicit handoff when any of these is true:

- ITSI is absent, disabled, unlicensed, on an unsupported platform version, or
  requires upgrade/restart.
- KV Store is unhealthy or required ITSI apps/collections are unavailable.
- The authenticated user lacks the object capability or team write access.
- A prerequisite Content Library provider, TA, SA, DA, dashboard app, data input, index,
  macro, or lookup is missing.
- The requested operation is UI-driven, product-preview, undocumented/private,
  or lacks a mapped and live-validated object contract for the target version.
- A same-version export or live preview cannot establish the shape and impact of
  an experimental payload.

## Official source ledger

- [Splunk IT Service Intelligence documentation hub](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence)
- [ITSI 4.21 REST API reference](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/leverage-rest-apis/4.21/itsi-rest-api-reference/itsi-rest-api-reference)
- [ITSI 4.21 REST API schema](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/leverage-rest-apis/4.21/itsi-rest-api-schema/itsi-rest-api-schema)
- [ITSI 5.0 REST API reference](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/leverage-rest-apis/5.0/itsi-rest-api-reference/itsi-rest-api-reference)
- [ITSI 5.0 REST API schema](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/leverage-rest-apis/5.0/itsi-rest-api-schema/itsi-rest-api-schema)
- [New features in ITSI 5.0](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/release-notes-and-resources/5.0/release-notes/new-features-in-splunk-it-service-intelligence)
- [Known issues in ITSI 5.0](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/release-notes-and-resources/5.0/release-notes/known-issues-in-splunk-it-service-intelligence)
- [Removed and deprecated features in ITSI 5.0](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/release-notes-and-resources/5.0/release-notes/removed-features-in-splunk-it-service-intelligence)
- [Create teams in ITSI 5.0](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/administer/5.0/teams/create-teams-in-itsi)
- [Schedule maintenance downtime in ITSI 5.0](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/administer/5.0/maintenance-windows/schedule-maintenance-downtime-in-itsi)
- [Add tags to a service in ITSI 5.0](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/visualize-and-assess-service-health/5.0/create-services/add-tags-to-a-service-in-itsi)
- [Configure aggregation-policy priority in ITSI 5.0](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/detect-and-act-on-notable-events/5.0/event-aggregation/configure-priority-for-aggregation-policies-in-itsi)
- [Overview of enrichment policies in ITSI 5.0](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/detect-and-act-on-notable-events/5.0/third-party-alerting/overview-of-enrichment-policies-in-itsi)
- [Splunk App for Content Packs 2.5 compatibility](https://help.splunk.com/en/splunk-it-service-intelligence/content-packs-for-itsi-and-ite/splunk-app-for-content-pack/2.5/overview-of-the-splunk-app-for-content-packs)
- [ITSI release notes and new features](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/release-notes-and-resources)
- [ITSI roles and capabilities](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/administer/4.21/permissions/configure-users-and-roles-in-itsi)
- [Overview of service templates](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/visualize-and-assess-service-health/4.20/service-templates/overview-of-service-templates-in-itsi)
- [Maintenance windows in ITSI](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/administer/4.21/maintenance-windows/overview-of-maintenance-windows-in-itsi)
- [Install content packs](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/discover-and-integrate-it-components/4.20/content-packs/install-content-packs)
- [Backup and restore](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/administer/4.21/backup-and-restore)
- [Set up predictive analytics in ITSI](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/visualize-and-assess-service-health/4.20/predictive-analytics/set-up-predictive-analytics-in-itsi)
- [Introducing Splunk IT Service Intelligence 5.0](https://www.splunk.com/en_us/blog/observability/introducing-splunk-it-service-intelligence-5-0.html)
