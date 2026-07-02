# ITSI API Compatibility Notes

This is an API-path and version posture summary, not a certification that every
ITSI product feature is automated. Read
[`product_coverage.md`](product_coverage.md) for the feature-level matrix,
limits, ITSI 5.0 posture, and official source ledger.

Render the deterministic implementation inventory when a machine-readable or
reviewable point-in-time report is useful:

```bash
python3 skills/splunk-itsi-config/scripts/itsi_compatibility_report.py \
  --format markdown
```

The report is offline evidence about local code paths, not a live target
certification. Detect the target version, routes, capabilities, and object
semantics before apply.

## Baseline

- Documentation baseline: ITSI 4.21 REST API reference and schema.
- Existing route notes include behavior observed for ITSI 4.21.2.
- The local automated tests use fake or in-memory clients. They verify request
  construction and workflow logic, not live compatibility across all supported
  Splunk Platform and ITSI combinations.
- Splunk recommends `vLatest` or an unversioned interface for ITSI APIs. The
  client probes the documented route family and compatible fallback where the
  implementation explicitly supports one.
- Splunk also publishes an ITSI 5.0 REST reference and schema. This repository
  has not recorded live 5.0 contract evidence, so the current implementation
  baseline remains 4.21.
- Export-shaped payloads are version-specific. Do not reuse a 4.21 passthrough
  payload on ITSI 5.0 without mapping it to the 5.0 schema and obtaining a clean
  live preview.

Official baseline sources:

- [ITSI 4.21 REST API reference](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/leverage-rest-apis/4.21/itsi-rest-api-reference/itsi-rest-api-reference)
- [ITSI 4.21 REST API schema](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/leverage-rest-apis/4.21/itsi-rest-api-schema/itsi-rest-api-schema)
- [ITSI 5.0 REST API reference](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/leverage-rest-apis/5.0/itsi-rest-api-reference/itsi-rest-api-reference)
- [ITSI 5.0 REST API schema](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/leverage-rest-apis/5.0/itsi-rest-api-schema/itsi-rest-api-schema)
- [ITSI release notes and resources](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/release-notes-and-resources)

## Compatibility classifications

| Area | Classification | Compatibility statement |
| --- | --- | --- |
| Entities, services, embedded KPIs, dependencies | `typed` | Local fields and additive drift behavior are implemented. Live data/search semantics still require target validation. |
| Service-template and custom-threshold links | `typed` with limits | Link routes are modeled. Template entity-rule choice semantics and version-shaped window objects retain UI/export handoffs. |
| Topology DSL | `typed` | Compiles local trees to services and dependency edges; it is not a product topology-discovery API. |
| Content-pack catalog/detail/status/preview | `read-only` | Uses live ITSI catalog data without discovery refresh in preview/validate. A stale catalog is reported. |
| Content-pack import | `typed envelope` | Uses the selected live catalog ID/version and conservative defaults. It does not install ITSI, Content Library, or prerequisite app packages. |
| Native export, inventory, prune-plan | `read-only` | Optional route families can be unavailable by version/entitlement; unavailability must be reported rather than promoted to support. |
| Generic ITSI/Event Management/maintenance/backup/view objects | `experimental passthrough` | Route and payload helpers exist, but exact schema, mutability, permissions, and lifecycle semantics are not claimed across versions. |
| Episode/action/ticket/export helpers and cleanup | `guarded` | Operational or destructive behavior requires explicit guards. It is not reusable idempotent desired state. |
| Relationship object types documented as unused | `unsupported` | Not managed by this skill. |
| ITSI 5.0-only experiences and AI features | `handoff` / `experimental` | Tracked in the product matrix. Published 5.0 REST documentation does not by itself prove that each new experience has a mapped, safe object contract; live evidence is still required. |

## Preflight requirements

Before a live preview or apply, detect and report:

- Splunk Platform and ITSI versions;
- ITSI license/app enablement and KV Store health;
- current user roles, object capabilities, and target-team access;
- Content Library and pack versions when packs are requested;
- availability of every route family needed by the selected spec; and
- any payload section that relies on same-version export evidence.

If any required combination is unknown, stop with a handoff. Do not treat a
404, a generic payload passthrough, or a successful fake-client test as evidence
that the product feature is supported.

## Read-only contract

`lint`, `preview`, `validate`, `export`, `inventory`, and `prune-plan` are
read-only. In particular, content catalog discovery and refresh endpoints use
POST and are excluded from those modes. A requested
`content_library.refresh_catalog: true` is apply-only and must be visible in the
approved preview as an intended write.

## ITSI 5.0

Splunk's official
[ITSI 5.0 new-features page](https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/release-notes-and-resources/5.0/release-notes/new-features-in-splunk-it-service-intelligence)
describes a new guided installer/home experience, expanded alert integrations,
AI service and KPI discovery, content-pack lifecycle changes, Episode Review and
central-admin changes, revised RBAC, Event iQ Detect and Diagnose, enrichment,
and maintenance improvements. The REST reference and schema are published, but
each new product area still needs an applicable object-contract mapping and live
validation before it becomes typed automation here. See `product_coverage.md`.
