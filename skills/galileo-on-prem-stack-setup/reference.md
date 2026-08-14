# Galileo On-Prem Stack Setup Reference

## CLI Boundary

Read-only/offline actions:

- `--inspect-chart`, `--render`, `--preflight`, `--status`
- `--plan-rollback`, `--plan-uninstall`
- `--render-lab-bootstrap`, `--preflight-lab-bootstrap`

Permanent fail-closed compatibility sentinels:

- `--apply-install`, `--apply-upgrade`, `--apply-rollback`
- `--apply-uninstall`, `--apply-lab-bootstrap`

Every apply sentinel rejects before bundle/kubeconfig/state I/O, binary
resolution, or subprocess execution. The entrypoint accepts no free-form Helm
or kubectl arguments. `--helm-bin` and `--kubectl-bin` accept one executable
name/path for read-only work only; command strings are rejected.

The Galileo instance console URL is mandatory on every action. Example:
`https://console.demo-v2.galileocloud.io/`.

## Deployment Spec

Start with `template.example`. It records:

- deployment/environment identity and one official installation method;
- exact target context, HTTPS API server, decoded CA SHA-256, `kube-system`
  UID, namespace, and namespace UID;
- exact local Stack archive, SHA-256, chart version, non-secret values, exact
  CSE-reviewed runtime-secret leaf paths, and timeout;
- optional galileoctl handoff, shared/dedicated CRD ownership, storage,
  data-service, node-pool, routing/TLS, monitoring, Wizard/GPU, air-gap,
  authorization, exception, and lab-bootstrap evidence;
- exact reviewed runtime inventory IDs for all nine required categories.

The chart schema, version-matched CSE questionnaire, and entitled archive are
authoritative. This skill does not synthesize proprietary values. Duplicate
YAML keys, aliases, merge keys, unknown spec fields, and populated secret-
shaped non-secret fields are rejected rather than normalized. Chart inspection
does not itself authenticate a proprietary questionnaire or establish a closed
values contract; `cse_values_contract_missing` remains open until an exact
version/hash-bound CSE artifact is supplied.

Shared CRD review requires the chart's exact version-matched controls to disable
every CRD path, including top-level, operator, and sequencing paths. The current
known contract is:

```yaml
global:
  disable_crds: true
clickhouse-operator:
  global:
    disable_crds: true
rabbitmq-operator:
  global:
    disable_crds: true
sequencing:
  crd_management:
    enabled: false
```

The rendered handoff uses `--skip-crds`; active packaged CRDs are separately
derived with values-aware `helm template --include-crds` and compared with the
pre-existing live CRDs. No CRD is created or changed.

## Official Installation Methods

The current Installation Guide defines galileoctl, umbrella Helm CLI,
deployment script, and step-by-step. galileoctl's UI is identified for first
install and its CLI is the workstation/CI alternative. The UI/CLI can install
the umbrella chart; it is not validation-only. Method A/B pinned chart artifact
inspection is supported. Method C has an explicit script/config artifact gap,
and Method D has an explicit ordered chart/release/dependency gap. All four are
non-executing handoffs in this skill. One method owns a release for its full
lifecycle.

## Runtime Secret Contract

The runtime file must be a current-user-owned regular file, one link, and mode
`0600` or stricter. It may contain only exact dotted leaf paths reviewed in the
spec. Keys use dot-free segments, leaves are nonempty strings, and aliases,
merge keys, lists, placeholders, default/sample credentials, and unknown paths
are rejected.

Preflight renders only in private temporary storage. Each leaf is independently
changed to a deterministic, non-secret marker; the resulting render must have
the same object set, metadata, non-Secret manifests, and Secret payload-key
shape. Each leaf must influence classified Secret payload values only. Raw and
marker values are never written to evidence.

If the entitled chart cannot satisfy this proof—or contains other rendered
credential-shaped defaults or plaintext credential placement—the secret
topology remains an explicit CSE handoff gap.

## Connected Preflight Evidence

Evidence is written outside the immutable bundle under immutable private
`.state/<bundle-sha>/generations/<generation-id>/` directories with an atomic
current-generation pointer. It binds:

- exact bundle/chart/non-secret digests and non-verifying runtime-secret
  path/influence contracts (never a raw secret-file digest);
- context, canonical API URL, CA hash, cluster/namespace UIDs;
- Helm version and the exact unsynthesized Kubernetes server patch/prerelease/
  build version passed to Helm, API discovery, release inventory, and 30-minute
  freshness;
- active CRDs and semantic live comparison;
- secret-safe exact rendered resource, image, endpoint, hook, route, expected
  PVC shape,
  node-placement, monitoring, data-service, and Wizard inventories;
- observer capability and non-persisting admission-dry-run capability as
  separate facts;
- unresolved product/integration gates.

Canonical schemas include:

- `galileo-on-prem-stack-rendered-image-inventory/v1`
- `galileo-on-prem-stack-rendered-endpoint-inventory/v1`
- `galileo-on-prem-stack-rendered-resource-inventory/v1`
- `galileo-on-prem-stack-release-contract/v1`

The generation ID is recomputed from its canonical manifest and every private
artifact hash/size; the current pointer additionally binds the exact generation
manifest bytes. This is local tamper evidence, not authenticity—a same-user
writer is not an external approver or signature authority.

Image evidence owns only Stack and optional galileoctl renders; standalone
Agent Control and Luna evidence comes from their child skills. Endpoint rows
are sanitized `host[:port]`, purpose, and source observations—not proof of
no-egress closure. Offline model artifact binding and endpoint source-to-mirror
rewrite evidence are not implemented in this release; air-gap validation must
fail closed with `stack_model_evidence_missing` and
`endpoint_rewrite_evidence_missing`.

## Handoff Candidate and External Attestation

Any local approval YAML is an operator attestation, not authenticated
Galileo/CSE authorization. Quote RFC3339 timestamps so YAML preserves strings:

```yaml
schema_version: 1
action: install
bundle_sha256: <bundle-directory-name>
target:
  kube_context: <exact-context>
  api_server: https://kubernetes.example.invalid:6443
  ca_sha256: <decoded-ca-sha256>
  cluster_uid: <kube-system-uid>
  namespace: galileo
  namespace_uid: <exact-namespace-uid>
  release_name: galileo
approver: <named-operator>
ticket: <external-change-or-Galileo-case>
galileo_cse_approved: true
joint_session: <joint-session-reference>
issued_at: "2026-08-13T12:00:00Z"
expires_at: "2026-08-13T13:00:00Z"
preflight_sha256: <canonical-preflight-sha256>
rendered_resource_inventory_sha256: <canonical-resource-inventory-sha256>
```

The external approval system must authenticate authorization. Preflight emits
`handoff-candidate.json`, not a final or approved packet. It binds exact render,
action, release/target, input digests, recovery warnings, and every unresolved
gate, with `authorized:false` and no executable argv. This release does not
import or authenticate the illustrative attestation above; Galileo/CSE must
bind the candidate and canonical preflight digest externally. The skill never
consumes an attestation as permission to mutate.

## Status Semantics

Status is namespace- and target-bound but never treats unrelated healthy pods
as Galileo health. Without an independently authenticated adoption receipt and
exact live release/resource provenance it reports `unverified-observed` (or a
degraded/absent state), never `installed-observed`. It may report safe resource
metadata for diagnosis. `application_smoke_validated` and `production_ready`
are always false.

Completion remains external: CSE approval, SSO, a working model, persisted
traces, routing/TLS handshakes, semantic monitoring and alert tests,
backup/restore, recovery ownership, application smoke, and agreed soak evidence.

## Known Required Handoffs

- All installation, upgrade, rollback, uninstall, and failed-release recovery
- galileoctl install/operation and all CRD ownership changes
- Hook/migration execution and operator-managed persistence convergence
- TLS key/certificate/chain/handshake verification and exact required-route
  backend contracts when not supplied by a version-matched CSE schema
- Full object-storage bucket/policy validation, semantic monitoring tests, and
  external data-service compatibility
- GPU scheduling, multi-architecture image coverage, and offline model artifact
  checksum/mount/startup verification
- Air-gap image acquisition, scan provenance, endpoint rewrite, and no-egress
  enforcement
- MicroK8s addon, MetalLB, and node-label changes
