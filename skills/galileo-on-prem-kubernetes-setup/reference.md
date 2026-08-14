# Galileo On-Prem Kubernetes parent contract

## Purpose and boundary

This skill is the non-mutating deployment router. It converts reviewed intake
into a deterministic orchestration and coverage packet. It neither inspects nor
changes Kubernetes, Helm, Galileo, external data services, DNS, registries, or
cloud resources. A command shown in a handoff is descriptive evidence, not an
authorization or an executable parent action.

## Deployment specification

`template.example` is JSON and therefore valid YAML. The renderer also accepts
YAML when PyYAML is installed. Its schema is closed: every accepted key is
declared by the renderer, and an unknown key is an error.

The contract records:

- `metadata`: deployment identity, environment, owner, and change record.
- `galileo`: console, API, and base-domain intent.
- `target`: kube context, API/CA/cluster identity, namespace, distribution, and
  Kubernetes version.
- `artifacts`: local chart archives, checksums, questionnaire values, external
  secret-file paths, image/model manifests, runtime inventory, and optional
  ownership evidence.
- `installation`: method, release names, timeout, namespace and CRD ownership,
  and the resolved Agent Control/Luna topology.
- `routing`, `node_pools`, `storage`, and `data_services`: production topology
  intent without cluster mutation. Core `azure-blob` is representable only
  with a written `object_storage.support_exception`, because current umbrella
  and Azure deployment guidance conflict; MinIO remains the unexceptioned AKS
  path documented by the provider guide.
- `monitoring`, `features`, `identity`, `email`, and `air_gap`: optional product
  and completion requirements.
- `operations` and `approvals`: backup, restore, rollback, soak, CSE, and
  cluster-change evidence.

Paths are references only. The parent never reads secret contents, chart
contents, kubeconfigs, or repository credentials. It may use `lstat` to report
whether a referenced path exists and whether a secret path is a safe regular
file. A child is responsible for validating content, exact chart schemas, and
private digests before mutation. Rendering resolves every configured artifact
reference to an absolute path in the normalized specification so the offline
validator can reproduce the same local evidence checks without depending on
the caller's working directory.

`installation.method` uses the same closed enum as the Stack child:
`galileoctl`, `helm-cli`, `deployment-script`, or `step-by-step`. The first
value covers both browser and CLI interfaces of official Method A. Every value
produces an explicit Galileo/CSE joint-session operator handoff; neither the
parent nor any deployment child executes Helm, Kubernetes, registry, cloud, or
storage mutation. No method may be reported as applied from a parent render.

## Validation policy

The renderer rejects:

- missing deployment ID, environment, console URL, kube context, namespace, or
  explicit Stack/galileoctl release names;
- non-HTTPS console/API URLs, URL userinfo, control characters, or traversal in
  deployment/release/namespace identifiers;
- unresolved `TODO`, `CHANGEME`, `REPLACE_ME`, or angle-bracket placeholders;
- unknown keys, invalid types, duplicate list values, or unsupported enums;
- inline keys/tokens/passwords/secrets, suspicious inline credential keys, and
  secret-looking assignments, bearer values, private-key blocks, or
  credential-bearing URLs in any string value;
- a console URL hostname that differs from the console route host, an API URL
  hostname that differs from the API route host, or any configured route/URL
  hostname outside the declared Galileo base domain;
- a shared cluster without `preinstalled-shared` CRD ownership;
- enabled Agent Control or Luna Studio without exactly one of `standalone` or
  `umbrella`; or disabled features with a live topology;
- GPU mode without Wizard, or offline models without Wizard;
- air-gap no-egress without an enabled air-gap profile;
- queue-purge authorization in the deployment plan.

The doctor reports, rather than inventing, missing entitlement files, hashes,
target identity, load-balancing/TLS/storage inputs, backups, approval evidence,
runtime chart inventory, GPU capacity evidence, production HA, restore drills,
and the three-day incident-free production soak.

The current deployment guide labels the pools
`galileo-node-type=galileo-core`,
`galileo-node-type=galileo-runner`, and
`galileo-node-type=galileo-ml`. The renderer fails closed on different values;
a future chart-specific change requires reviewed package/CSE evidence and an
explicit contract revision.

## Immutable bundle

Rendering normalizes the spec, computes its SHA-256 plus the static feature ID
and semantic-contract hashes, and derives the bundle ID from those inputs and
the renderer contract version. Publication uses a sibling temporary directory
and an atomic rename. Directories are mode `0700`; regular files are `0600`.

The bundle contains:

- `.galileo-on-prem-kubernetes-setup`
- `metadata.json`
- `deployment-spec.normalized.json`
- `feature-matrix.json`
- `runtime-inventory.normalized.json`
- `orchestration-plan.json` and `.md`
- `coverage-report.json` and `.md`
- `source-ledger.json`
- `gap-register.json` and `.md`
- `doctor-report.json` and `.md`
- `status.json`
- `handoff.md`
- `bundle-manifest.json`

The manifest hashes every other file. An existing bundle is verified and
reused; it is never overwritten. Validation recomputes the runtime
classification, coverage, local artifact evidence, gap register, state,
metadata, orchestration, source ledger, status, handoff, and every Markdown
rendering, then requires exact bytes and an exactly regenerated manifest.
Status and validation fail on extra files, symlinks, non-regular files, mode
drift, checksum drift, any rehashed derived-report forgery, bundle/spec
mismatch, or an ambiguous output root.

## Coverage contract

`references/deployment-feature-matrix.json` is the reviewed static inventory.
Every row has a stable ID, product domain, canonical owner, allowed status,
automation boundary, validation evidence, official source URLs, and review
date. The renderer validates row completeness and uniqueness and publishes:

- `feature_count`
- `feature_ids_sha256`
- `feature_contracts_sha256`
- `uncovered`
- `unowned`
- `duplicate_mutation_owners`
- `unclassified_runtime_inventory`

Static rows cover documented surfaces; they do not prove the exact private
chart package. `artifacts.stack_runtime_inventory` must point to a Stack child
JSON report conforming to the closed runtime contract below. The parent derives
`unclassified_runtime_inventory` from that report. Missing evidence is reported
as `runtime.inventory.pending`; any nonempty derived array blocks completion.

The Stack child report uses this closed shape:

```json
{
  "schema_version": 1,
  "chart_sha256": "64 lowercase hex characters",
  "generated_by": "galileo-on-prem-stack-setup",
  "observed_categories": [
    "dependency", "schema_or_enable_flag", "image", "crd",
    "hook_or_migration", "cluster_scoped_object", "api_kind",
    "service_or_route", "persistence"
  ],
  "observed_empty_categories": {
    "crd": "No CRDs were present in this exact archive."
  },
  "items": [
    {
      "id": "image.galileo-api.main",
      "category": "image",
      "classification_id": "stack.api",
      "owners": ["galileo-on-prem-stack-setup"],
      "source_ref": "templates/api-deployment.yaml"
    }
  ]
}
```

Every observed category must contain at least one item or an explicit nonempty
`observed_empty_categories` explanation. Item IDs are unique. A classification
must reference one of the 110 reviewed matrix IDs; its owner set must exactly
match the matrix row. The chart digest must match the deployment spec. Unknown
fields, unsupported classifications, or synthetic summary-only counts do not
qualify.

## Orchestration and state

The plan is a dependency graph, not a script:

1. Verify supply-chain evidence with `galileo-on-prem-air-gap-setup` when the
   deployment is air-gapped.
2. Render and connected-preflight through `galileo-on-prem-stack-setup`, then
   take its exact evidence packet to a Galileo/CSE joint session for any change.
3. Render and read-only validate Agent Control and Luna Studio through their
   owning skills, then use their Galileo/CSE joint-session handoffs for any
   mutation. An umbrella topology emits an overlay that returns to a new
   immutable Stack bundle; it never creates a second release.
4. After Stack health evidence, delegate tenant/model/trace completion to
   `galileo-platform-setup` and optional MCP/runtime/instrumentation owners.

The parent may report only `rendered` or `blocked`. Child workflows may report
their own scoped render, preflight, read-only observation, or handoff states;
they cannot claim that a lifecycle mutation ran. No single child status may assert
`production-ready`; that label requires a separate consolidated completion
review of every gate below and is not emitted automatically by this skill
family.

## Production completion

Production readiness remains blocked until the exact chart/package inventory
is classified, infrastructure and data persistence pass child validation,
Galileo has approved values and cluster changes, SSO and a working model
integration are verified, traces persist, monitoring and smoke tests pass,
backup/restore evidence exists, and at least three incident-free days are
recorded. A current lab render cannot satisfy those gates.
