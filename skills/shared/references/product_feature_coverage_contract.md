# Product and feature coverage contract

This repository treats product coverage as a production contract, not a naming
claim. A feature is covered only when its tracked source row resolves to a
stable identifier, a current official-source provenance record, one or more
canonical owner skills, an explicit coverage status and automation boundary,
and an on-disk validation surface.

The machine-readable contract is
`skills/shared/product_feature_coverage.json`. The audit reads the real router
catalogs, taxonomy, and Markdown matrices named there; it does not accept the
presence of headings or other marker strings as coverage evidence.

## Semantic gates

| Gate | Required evidence |
| --- | --- |
| Canonical skill catalog | Every skill is present in the generated catalogs. `skill_product_registry.json` must have the same checksum, lifecycle records, products, capabilities, and exactly one product/capability assignment per skill. |
| Complete router inventory | Every canonical skill whose catalog `target` contains the word `router` must appear in the manifest with `inventory_classification: catalog_explicit_router`. Additional product-wide coverage owners are explicitly classified as `coverage_owner`; they cannot hide a missing catalog router. |
| App/package routing | Every `app_registry.json` row routes to an on-disk skill. Numeric Splunkbase entries remain covered by the registry evidence snapshot. |
| Source provenance | Each router names tracked provenance files with an HTTPS source on its explicit approved-host list and a researched/verified date no older than `maximum_source_age_days`. The audit stays offline and verifies the recorded evidence rather than contacting the source. |
| Stable feature identity | Every source row normalizes to a unique router-local identifier. The reviewed feature count and `feature_ids_sha256` fail closed when a product is added, removed, or renamed. |
| Semantic feature contract | `feature_contracts_sha256` independently snapshots each normalized feature ID, name, source and mapped coverage statuses, canonical owners, effective automation boundary, validation evidence, and row-level source URLs. Semantic drift therefore requires review even when the feature ID set is unchanged. |
| Canonical ownership | Every feature has at least one owner in `skills/catalog.yaml` and `skill_product_registry.json`; deprecated aliases cannot own coverage. Generic or UI-owned matrix rows remain the responsibility of their canonical router. |
| Coverage and boundary | Every source status has a manifest contract mapping it to an allowed coverage status and a non-empty automation boundary. Sources with row-level boundaries must keep them populated. |
| Validation surface | Every owner has `skills/<owner>/scripts/validate.sh` and appears in `skill_validation_registry.json`. Taxonomies that provide per-feature validation evidence must keep it populated. |
| Router/catalog parity | Adapters consume every catalog or matrix row, validate internal counts/status declarations/routes, and compare the complete stable-ID set with its reviewed snapshot. |

## Router source adapters

| Product area | Semantic source |
| --- | --- |
| Cisco product catalog and SCAN routes | Generated `skills/cisco-product-setup/catalog.json`, including its pinned SCAN provenance and every product ID |
| Cisco Data Fabric and Cisco/Splunk experience layers | Every feature row in `references/feature-matrix.md`, backed at router level by `references/research-ledger.md` |
| AppDynamics suite feature families | Every row in `references/appdynamics-taxonomy.yaml`, including row-level owner, status, source, validation method, and apply boundary |
| Splunk security portfolio | Every entry in `skills/splunk-security-portfolio-setup/catalog.json`, including its status, routes, notes, and verification date |
| Splunk Observability native surfaces | Every row in the Product Coverage Matrix, including all declared coverage modes, render evidence, and owning follow-up; official source anchors are maintained at router/section level |
| WideField Security adoption | Every delegated child and capability bullet in the parent reference, backed by the parent source-boundary ledger |
| Coding-agent telemetry | Every agent and destination row in the coding-agent router reference, backed by official Codex, Claude Code, and Splunk telemetry sources |
| Splunk Supported Add-ons | Every official glossary entry, including implicit generic install-only handoffs and explicit first-class/delegated routes |
| Galileo On-Prem Kubernetes | Every stable deployment row plus the exact pinned chart's dynamically classified dependencies, images, hooks, CRDs, cluster-scoped objects, API kinds, routes, PVCs, and enable flags |
| Galileo application platform | Every tracked product and integration row for an already-running instance, with Kubernetes deployment delegated to the On-Prem router |

Structured product keys and taxonomy IDs are used directly. Data Fabric and
Observability matrix IDs use a deterministic lowercase slug of the `Surface`
cell. WideField uses stable `child.*` and `capability.*` IDs derived from its
delegation/capability bullets. Coding-agent telemetry uses stable `agent.*` and
`destination.*` IDs from its matrices. Changing any source identity changes
the ID snapshot and requires review.

Provenance granularity is not uniform. AppDynamics has a claim-level
`source_url` on every taxonomy row, and selected Cisco and security catalog
rows carry row-level sources. The Data Fabric and Observability Markdown
matrices, WideField reference, and coding-agent matrices use router- or
section-level research ledgers/source anchors rather than a source URL on each
row; their normalized `row_source_urls` are therefore empty, while router
provenance is independently host-checked and freshness-gated. Other catalog
rows without a claim-level URL similarly fall back to their router's reviewed
provenance. Do not describe those rows as having claim-level sourcing.

The two Galileo adapters consume reviewed JSON matrices with row-level owners,
status, automation boundary, validation evidence, and official source URLs.
The On-Prem matrix is a documentation baseline: its router validator must also
compare a pinned entitled chart archive against the runtime inventory and fail
on any unclassified dependency or Kubernetes surface. The application matrix
is consumed directly by `galileo-platform-setup` so renderer and audit coverage
cannot drift.

## Reviewing catalog changes

When an official source or local router catalog changes:

1. If a canonical skill's catalog target adds or removes the word `router`,
   review and update its inventory classification. A newly explicit router
   cannot pass until it has a semantic manifest entry.
2. Update the source catalog or matrix, its verified/researched date, and its
   source URL evidence.
3. Add a status contract only when a genuinely new coverage state appears.
4. Run the audit with `--json`. It reports the actual feature count,
   `feature_ids_sha256`, and `feature_contracts_sha256` for each router.
5. Review every added, removed, or renamed feature and its owner, boundary, and
   validator before copying the new count and hashes into
   `product_feature_coverage.json`.

Do not update either snapshot merely to make the audit pass. The ID snapshot is
the approval point for product/feature scope drift; the contract snapshot is
the separate approval point for semantic coverage drift.

## Audit command

```bash
python3 skills/shared/scripts/audit_product_feature_coverage.py
```

Use `--json` for machine-readable output. `--as-of YYYY-MM-DD` is available for
reproducible freshness review, and `--manifest PATH` supports isolated
contract-validation tests. The audit is intentionally offline: it checks
tracked contracts and provenance without contacting Splunk, Cisco, Splunkbase,
or tenant APIs.
