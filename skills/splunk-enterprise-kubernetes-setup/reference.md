# Splunk Enterprise Kubernetes Reference

This reference describes what the current renderer and entrypoints do. Use
[coverage.md](coverage.md) for the support boundary and official product scope.

## Current Version Defaults

| Item | Default | Authority |
|---|---|---|
| Splunk Operator for Kubernetes | `3.1.0` | SOK 3.1.0 GitHub release |
| Operator Helm chart | follows `--operator-version` | official Splunk Helm repository |
| Enterprise Helm chart | follows `--operator-version` | official Splunk Helm repository |
| SOK Splunk Enterprise image | `splunk/splunk:10.4.1` | shared platform default plus SOK matrix |
| SOK Kubernetes range | `1.25` through `1.34`, conditional | SOK 3.1.0 release matrix |
| Splunk POD bundle | `10.4.0_1.6.0` | POD 10.4 release notes |
| Render root | `./splunk-enterprise-k8s-rendered/` | repository workflow |

The SOK compatibility check is intentionally verified only for Operator
`3.1.0`. The current release matrix enforced by the skill is:

| Kubernetes | Splunk Enterprise | Separated ingestion |
|---|---|---|
| 1.25-1.33 | 9.4.3 through 10.0.4 | not supported |
| 1.25-1.33 | listed 10.2.x or 10.4.x release lines | supported |
| 1.34 | 9.4.9+, 10.0.4+, or 10.4+ on listed release lines | only with 10.4+ |

The release body is authoritative if another generated documentation page has
not yet caught up:

<https://github.com/splunk/splunk-operator/releases/tag/3.1.0>

`--chart-version` must match `--operator-version` unless a development render
uses `--allow-unverified-versions`. Production rejects that override and
requires the exact official chart archives and CRD release manifest as local,
hash-verified inputs. The renderer snapshots those bytes into the bundle so
validation and mutation consume the reviewed artifacts rather than a later
download.

Verified SOK 3.1.0 artifact SHA-256 values:

| Artifact | SHA-256 |
|---|---|
| Operator chart | `c71c1a7fe495c1122c1b0b1b689a366f759107950130c6fcf1f0c453e5d57efd` |
| Enterprise chart | `0d46b934f78a270b2c9bbacb9f442855f125069800d0a1373eb5f21c54e7fc71` |
| CRD release manifest | `d974a6f2c768ad60d8eb56b2dc571354b4dfe48873cbff4e478ca6aa3e2fb3fe` |

A custom image with an opaque tag or a digest-only reference cannot be matched
to the release matrix. It requires the non-production unverified-version
override; production fails closed. Preserve a numeric Splunk tag before the
digest, for example `splunk:10.4.1@sha256:...`, when compatibility must be
asserted.

POD versions have the form `<Splunk version>_<installer version>`, for example
`10.4.0_1.6.0`. The POD installer bundles Splunk Enterprise, SOK, Kubernetes
services, and OCI images. Those components cannot be selected or upgraded
independently.

### Direct CLI Contract

The help output is authoritative. These tables group the complete public input
surface so production-only requirements are not hidden in examples.

| Shared option | Effect |
|---|---|
| `--target`, `--phase`, `--apply` | Select SOK/POD and render, preflight, apply, status, or all. |
| `--output-dir`, `--dry-run`, `--json` | Select the bundle root or emit a non-mutating plan. |
| `--allow-upgrade` | Record reviewed upgrade intent. SOK can apply a gated upgrade; POD mutation still fails closed. |
| `--confirm-splunk-10-4-upgrade-readiness` | With SOK `--allow-upgrade` to 10.4+, attest restorable platform/KV backups, healthy KV Store server 7.0+, premium compatibility, TLS 1.2+, and target upgrade-note review. Invalid without `--allow-upgrade`. |
| `--allow-unverified-versions` | Explicit SOK/POD unverified-tuple escape hatch after release/compatibility review. Production SOK rejects it, and using it never creates a support claim. |
| `--license-file` | SOK accepts one file; POD accepts comma-separated files. Contents are staged, never copied into documentation. |

| SOK option group | Options and effect |
|---|---|
| Topology | `--architecture`, `--standalone-replicas`, `--indexer-replicas`, `--search-head-replicas`, `--site-count`, `--site-zones`, `--manager-site`, `--search-head-site`, `--manager-zone`, `--search-head-zone` select and constrain S1/C3/M4. |
| Releases/images | `--operator-version`, `--chart-version`, `--operator-image`, `--splunk-version`, `--splunk-image`, `--kubernetes-version`, `--accept-splunk-general-terms`. |
| Reviewed supply chain | `--operator-chart-archive`, `--enterprise-chart-archive`, and `--crd-manifest` must be supplied together and are mandatory in production. |
| Identity/namespace | `--namespace`, `--operator-namespace`, `--operator-scope`, `--watch-namespaces`, `--release-name`, `--operator-release-name`. |
| Exact live target | `--expected-kube-context`, `--expected-api-server`, `--expected-cluster-uid`; all three are mandatory in production. `--eks-cluster-name` plus `--aws-region` can render a bundle-local EKS kubeconfig helper. |
| Storage/profile | `--deployment-profile`, `--storage-class`, `--etc-storage`, `--var-storage`. |
| Licensing/monitoring | `--existing-license-manager`, same-namespace-only `--existing-license-manager-namespace`, and `--disable-monitoring-console`. |
| SmartStore | `--smartstore-provider`, `--smartstore-bucket`, `--smartstore-prefix`, `--smartstore-indexes`, `--smartstore-region`, `--smartstore-endpoint`, `--smartstore-secret-ref`, or AWS IRSA via `--splunk-service-account`, `--splunk-irsa-role-arn`, `--splunk-irsa-token-expiration`, and `--aws-region`; production also requires `--confirm-smartstore-index-inventory` and `--confirm-smartstore-path-ownership`. |
| Reviewed overlays | `--operator-values-overlay`, `--enterprise-values-overlay`; only the constrained allowlist described below is accepted. |
| Separated ingestion | `--indexing-ingestion-separation`, `--ingestor-replicas`, `--queue-provider`, `--queue-name`, `--queue-dlq`, `--queue-region`, `--queue-endpoint`, required `--queue-secret-ref`, `--object-storage-path`, and `--object-storage-endpoint`. `--ingestor-service-account` exists in intake but is rejected by the verified 3.1 path. |

| POD option group | Options and effect |
|---|---|
| Bundle/topology | `--pod-profile`, `--pod-version`, `--controller-ips`, `--worker-ips`, `--primary-search-name`, `--secondary-search-name`. |
| Installer/new cluster | `--installer-path`, independently reviewed `--installer-sha256`, and one-time `--confirm-new-pod-install`. |
| Bastion | `--ssh-user`, `--ssh-private-key-file`. |
| App placement | `--indexer-apps`, `--cluster-manager-apps`, `--search-apps`, `--search-deployer-apps`, `--standalone-apps`, `--premium-apps`, `--itsi-apps`, `--license-manager-apps`. |
| ITSI provenance | `--itsi-source-bundle`, `--itsi-source-sha256`, `--itsi-jdk-sha256`. |
| Routing/TLS | `--ingress-domain` records the name-route suffix. Custom trusted TLS additionally requires `--ingress-certificate-file`, `--ingress-private-key-file`, and `--ingress-ca-file`. |

Use `setup.sh --help` for accepted values and current defaults.

For a verified custom Operator image, the numeric tag must match the Operator
version; the official `-distroless` tag form is also accepted. Production still
requires the selected tag to be digest-pinned.

## Rendered-Bundle Lifecycle

The workflow separates review from mutation:

1. `--phase render` writes `<output-dir>/<target>/`.
2. Review `README.md`, `metadata.json`, all values/configuration, helpers, and
   any copied overlays.
3. `validate.sh` verifies required files, executable shell syntax, and the
   `bundle-manifest.json` SHA-256/mode inventory. SOK also lints/templates charts
   when Helm is available; POD can run strict local-file checks.
4. `--phase preflight`, `apply`, and `status` require the existing, unchanged
   bundle. They do not rerender it.
5. Use `status` after `apply`, or use `all` only when a one-command render and
   deployment has already been approved.

For SOK, `apply.sh` is the only public mutation entrypoint in the bundle. It
verifies the manifest and exact cluster identity, runs preflight, privately
stages the license when present, and then authorizes the internal CRD/Helm
helpers. Direct invocation of those mutation helpers fails closed. POD uses the
snapshotted installer and privately staged external inputs on each helper run.
Both targets emit `bundle-verify.py` to detect ordinary drift and unsafe links;
the bundle root must remain current-user-owned mode `0700`, and every tracked
file must retain current-user ownership and its recorded reviewed mode. This
owner/mode/hash contract is not a cryptographic signature or provenance system.

Do not hand-edit a rendered bundle. For SOK, create a reviewed non-secret
overlay and rerender. POD has no free-form overlay; express supported fields as
CLI inputs or operate the installer outside this skill with an independently
reviewed static configuration.

`--phase render --apply` preflights and applies immediately but does not run the
final status phase. Production workflows should use separate review phases.

## SOK Architecture Rendering

The Enterprise chart SVA switches are:

- `s1`: Standalone CR, normally one replica.
- `c3`: ClusterManager, one IndexerCluster, one SearchHeadCluster, and a
  MonitoringConsole unless disabled.
- `m4`: one ClusterManager, one site-specific IndexerCluster per site, one
  SearchHeadCluster, and a MonitoringConsole unless disabled.

These are the three Helm SVA presets. Upstream Applied SVA guidance also lists
C1/C11, C13, M2/M12, M3/M13, and M14 as direct-CR compositions; they are not
aliases accepted by this renderer. D1/D11 is marked not recommended upstream.
M4 remains a one-region multisite-indexer design: its management and search
tiers are single-zone placements, and it is not regional DR or an
active/standby Cluster Manager topology. Chart 3.1.0's M4 preset is exactly two
indexer sites because its multisite replication/search-factor totals are fixed
at two. The SHC and deployer are assigned a Splunk site and pinned together to
the one selected `--search-head-zone`; the preset is not a stretched multi-zone
search tier. A 3-63-site design or custom RF/SF requires reviewed direct CRs and
is outside this preset renderer.

Upstream notes that SHCs do not have site awareness for artifact replication
and generally recommends `site0` to disable multisite search affinity. The
verified preset accepts only `site1` or `site2`. A `site0` or stretched SHC
design is a direct-CR/specially reviewed scheduling handoff, and zone-failure
search continuity must be tested separately.

Guardrails:

- S1 requires exactly one Standalone; multi-Standalone direct CRs are not this preset.
- C3 requires at least three indexers.
- M4 requires exactly two sites, at least two indexers per site, and exactly two
  unique zone values when zones are supplied.
- C3 and M4 require at least three search heads.
- `--indexer-replicas` is total indexers for C3 and indexers per site for M4.
- `--site-zones` has one unique Kubernetes zone label per M4 site.
- `--manager-zone` controls the Cluster Manager placement;
  `--search-head-zone` pins the SHC and deployer to one zone.

The renderer uses chart role blocks for storage and resources. Treat them as a
starting point, not an SVA capacity certification. Use
`splunk-platform-sizing`, storage performance evidence, failure-domain review,
and explicit capacity approval before production. A reviewed Enterprise
resource overlay may change quantities, but production requires complete
CPU/memory requests equal to limits for every Splunk role and SHC deployer.

## Operator Scope and Namespaces

`--operator-scope namespace` is the default. In that mode:

- `--namespace` and `--operator-namespace` must match.
- `--watch-namespaces` is rejected.
- RBAC is limited to the operator namespace.

For a dedicated operator namespace:

```bash
--operator-scope cluster \
--operator-namespace splunk-operator \
--namespace splunk \
--watch-namespaces splunk
```

Every cluster-scoped watched list must include the Enterprise namespace.
This renderer rejects more than one watched Enterprise namespace per bundle;
multi-namespace Operator tenancy requires the direct Helm/CR handoff described
in [coverage.md](coverage.md).
Preflight verifies namespace and RBAC creation permissions, chart availability,
CRD availability, the live server version, storage class, referenced Secret,
service account, and existing LicenseManager as applicable.

An existing LicenseManager must be in the Enterprise namespace. The namespace
option may be omitted or explicitly set to that same namespace; the strict
bundle rejects a cross-namespace reference even with cluster-scoped RBAC.

When `--eks-cluster-name` is supplied, the rendered helper creates a bundle-local
`kubeconfig`, shows its context, and all generated SOK helpers reuse it. AWS
authentication is an external prerequisite; run `duo-sso` for the approved
account and role before preflight, and do not persist its credentials in the
bundle. The EKS name is validated as 1-100 characters beginning with a letter
or digit and then containing only letters, digits, underscore, or dash.

## SOK Production Profile

`--deployment-profile production` adds fail-closed intake requirements:

- explicit `--storage-class`
- SmartStore bucket plus region or endpoint, a reviewed
  `--smartstore-indexes` inventory (`main` by default), and
  `--confirm-smartstore-index-inventory`
- `--smartstore-secret-ref`, or the AWS IRSA set:
  `--splunk-service-account`, exact `--splunk-irsa-role-arn`, and
  `--aws-region`
- `--confirm-smartstore-path-ownership`, attesting that no other active
  Standalone or indexer cluster shares the reviewed bucket/prefix
- a local `--license-file` or `--existing-license-manager`
- matching official `--operator-chart-archive`,
  `--enterprise-chart-archive`, and `--crd-manifest` inputs
- digest-pinned `--operator-image` and `--splunk-image`; the Splunk reference
  must retain its numeric version tag before `@sha256` so the matrix is provable
- `--expected-kube-context`, `--expected-api-server`, and
  `--expected-cluster-uid`
- for M4, exactly two site zones plus reviewed manager/search Splunk-site
  selections (`site1`/`site2` defaults) and matching manager/search-head zones
- no `--allow-unverified-versions` bypass

This profile does not certify sizing or create buckets, IAM roles, service
accounts, Secrets, storage classes, backups, DNS, ingress controllers, or
certificates. Those are external owner handoffs.

### Licensing

SOK accepts one license file. A local file renders:

- `create-license-configmap.sh`
- a `splunk-licenses` ConfigMap volume
- a Standalone license URL for S1, or a LicenseManager for C3/M4

Alternatively, reference an existing same-namespace LicenseManager; the
namespace option, when supplied, must equal the Enterprise namespace. Do not use
both methods. On a later `--phase apply`, the orchestrator detects
`create-license-configmap.sh` inside the reviewed bundle and runs it without
requiring render inputs to be repeated.

`--existing-license-manager` means a same-namespace Operator-managed v4
LicenseManager CR, not a hostname for a VM, bare-metal server, or otherwise
non-SOK Splunk License Manager. Upstream supports an external manager only
through a shared `pass4SymmKey`, the Operator global Secret, and a mounted
`defaultsUrl` that contains the external URL. This bundle protects
`defaultsUrl`, extra volumes, and global-Secret mutation, and cannot validate
that external manager's health
or license state, so that design is a direct-CR/secret-management handoff.

### SmartStore

The first-class renderer emits one AWS S3 or MinIO/S3-compatible remote volume.
`--smartstore-indexes` is the exact managed-index inventory (`main` by default),
and production requires an explicit completeness attestation. Authentication is
either an existing Secret name or the verified AWS IRSA service-account path.
IRSA is deliberately least-privilege scoped to S1 Standalone or C3/M4 indexer
peers; Cluster Manager, search, licensing, and monitoring pods do not receive
the S3 role. Supply the exact role with `--splunk-irsa-role-arn` and the cluster
region with `--aws-region`. The existing ServiceAccount must carry matching
`eks.amazonaws.com/role-arn` and `eks.amazonaws.com/token-expiration`
annotations, `eks.amazonaws.com/sts-regional-endpoints: "true"`, and either no
audience annotation or `sts.amazonaws.com`. The default token TTL is 3600;
600..86400 is accepted; an explicit ServiceAccount annotation keeps the IRSA
projection deterministic, including at 86400. Status validates the projected
`aws-iam-token` volume, audience/TTL,
read-only mount, role/token environment, regional STS, and an optional exact
AWS region pair on every affected main/init container. EKS Pod Identity and
other cloud identity mechanisms remain separate handoffs. Secret-backed status
comparison uses private temporary storage and never emits access keys.

The strict first-class contract intentionally locks one remote volume and the
reviewed index list; additional volumes or per-index volume routing are a
separate handoff. The SmartStore CR fields cover Amazon S3 and S3-API-compatible
storage. Upstream explicitly calls direct CR installation of SmartStore indexes
and configuration a temporary method and recommends App Framework for that
content; treat the first-class CR renderer as a guarded implementation of that
documented-but-temporary path, not as a reason to ignore the recommendation.
Azure Blob or GCP SmartStore requires a Splunk configuration app delivered
through App Framework rather than an invented CR provider field. Move existing
local index data to remote storage before enabling SmartStore, and review
internal-index `repFactor=auto`, cache, encryption, retention, and recovery
settings.

### Monitoring Console and Existing Resources

C3 and M4 render a MonitoringConsole by default. Use
`--disable-monitoring-console` only when monitoring is owned elsewhere and the
loss of chart-generated references has been reviewed. The current first-class
existing-resource reference is LicenseManager. Existing ClusterManager or
MonitoringConsole references require a direct Helm/CR handoff and upstream
compatibility review; the strict overlay role-key allowlist rejects them.

Upstream also documents an external indexer-cluster connection for an
Operator-managed Standalone, SearchHeadCluster, or LicenseManager. It requires a
shared IDXC `pass4SymmKey` in the global Secret and a mounted `defaultsUrl` with
the external Cluster Manager URL. S1/C3/M4 bundles here own their index tier and
reject those fields; they do not validate the external manager, peers, RF/SF,
or search/forwarding connectivity.

### Day-2 CR, Storage, Ingress, and FIPS Boundaries

Upstream supports scaling CRs by changing `replicas`, including with
`kubectl scale`. This skill renders the initial replica contract and status
checks it exactly; upgrade preflight rejects a live-to-target replica change.
Perform scaling as a separate capacity-reviewed operation, prove cluster
health, then render and validate a new baseline before another managed phase.

The product also supports per-CR pause annotations and the
`enterprise.splunk.com/admin-managed-pv: "true"` annotation. A pause stops
reconciliation until the annotation is removed; this skill rejects pause
annotations and paused live CRs. Administrator-managed PV mode disables dynamic
PV creation and requires pre-created PVs with the exact selector labels. The
skill does not inventory those labels, bindings, or lifecycle, so generic
annotation passthrough is not authorization for that storage model. Both are
explicit owner handoffs.

Ingress objects remain external to this bundle. A supported design must keep
Splunk Web sessions sticky, make a forwarder load balancer resolve to at least
two IPs, avoid unsupported Indexer Discovery, and use separate clear/encrypted
forwarding ports. TLS behavior is controller-specific: for example, upstream
documents only end-to-end TCP TLS for Kubernetes Ingress NGINX because it does
not terminate TCP gateway traffic. Review certificates on both forwarders and
Splunk endpoints plus DNS, LB/WAF, reachability, and the current controller
version outside this skill.

For FIPS, upstream says the standard provided container images need no change.
The prerequisite is a Kubernetes cluster whose nodes are already FIPS
140-3-compliant. This skill neither builds those nodes nor attests the cluster's
cryptographic compliance; retain platform-owner evidence and use the normal SOK
workflow.

## SOK Indexing and Ingestion Separation

SOK 3.1 adds an ingestion-only tier backed by durable Queue and ObjectStorage
resources. This skill's first-class implementation is limited to C3 and AWS:

- SQS queue and dead-letter queue
- upstream queue mode `sqs` (default) or `sqs_cp`
- S3 object path for oversized messages
- IngestorCluster replicas
- a required existing Queue credential Secret for ClusterManager, index-only
  IndexerCluster, and IngestorCluster

The Queue credential Secret must use the upstream
`s3_access_key`/`s3_secret_key` key contract. This verified SOK 3.1 path requires
an empty workload `serviceAccount`; `--ingestor-service-account` and
`--splunk-service-account` are rejected because the upstream EKS identity path
has not been verified.

`--queue-region` follows the Queue CRD's narrower grammar, not the general AWS
region parser: `(?:us|ap|eu|me|af|sa|ca|cn|il)(?:-[a-z]+){1,3}-[0-9]`.
Validate a new or isolated-region identifier against that exact pattern before
planning the bundle.

The following inputs are mandatory. `--queue-provider` is optional and defaults
to `sqs`; set it explicitly to `sqs_cp` only when that reviewed upstream queue
mode is required.

```text
--indexing-ingestion-separation
--queue-name
--queue-dlq
--queue-region
--queue-secret-ref
--object-storage-path
```

The renderer does not provision SQS, DLQ, S3, IAM, KMS, VPC endpoints, or the
Secret. Validate retention, encryption, retry/DLQ operations, endpoint
reachability, and failure recovery with the AWS and platform owners. Queue
fields are immutable upstream except credential volumes; ObjectStorage fields
are immutable. Treat either change as a replacement/migration design, not a
routine Helm edit. Horizontal Pod Autoscaling and Grafana are documented
upstream extensions but remain separate-manifest/operations handoffs here. HPA
conflicts with this bundle's exact replica/status contract and is not accepted
as first-class validation evidence.

Chart 3.1.0 mis-serializes `queue.sqs.volumes`. When `--queue-secret-ref` is
used, the renderer deliberately emits the documented Queue CR through the
chart's `extraManifests` path and semantic validation checks the resulting
credential volume. Do not replace this with the defective values path.

For an `--allow-upgrade` bundle, preflight rejects chart downgrade and compares
live Queue, ObjectStorage, IndexerCluster, and IngestorCluster immutable fields
with the reviewed target before mutation. Credential-volume rotation remains
the documented mutable Queue exception.

Official resource reference:
<https://splunk.github.io/splunk-operator/IndexIngestionSeparation.html>

## SOK Overlays

Overlay files are copied into the bundle and applied after generated values:

```bash
--operator-values-overlay /reviewed/operator-values.yaml \
--enterprise-values-overlay /reviewed/enterprise-values.yaml
```

The renderer parses exactly one strict PyYAML 6 mapping and rejects aliases,
anchors, directives, duplicate keys, inline credentials, private-key material,
credential-bearing URLs, and Kubernetes Secret objects. Explicit Secret
references such as App Framework `secretRef` and image-pull Secret names are
allowed; create the Secret outside the overlay.

Good overlay candidates include:

- under the sole Operator root `splunkOperator`: `affinity`, `annotations`,
  `imagePullSecrets`, `labels`, `nodeSelector`, `podAnnotations`, `podLabels`,
  `resources`, `terminationGracePeriodSeconds`, and `tolerations`;
- under Enterprise roots `standalone`, `clusterManager`, `indexerCluster`,
  `searchHeadCluster`, `licenseManager`, `monitoringConsole`, or
  `ingestorCluster`: `additionalAnnotations`, `additionalLabels`, `affinity`,
  `resources`, `tolerations`, `topologySpreadConstraints`, and structurally
  validated `appRepo` definitions.

Unknown or misspelled roots/role keys are rejected before Helm so a typo cannot
silently become an ignored chart value.

Protected fields include images, service accounts, identity, storage/topology,
`licenseUrl`, `defaultsUrl`/`defaultsUrlApps`, arbitrary containers/commands/env,
probes, security/host namespaces, services/`serviceTemplate`, arbitrary volumes
or mounts, `extraManifests`, namespaces/watch scope, and the General Terms
setting. `clusterDomain` through Operator environment overrides is therefore a
handoff, not an accepted overlay. `schedulerName` is not in the strict role
allowlist. Generated `ephemeralStorage: false` is locked;
ephemeral Splunk etc/var storage is not a supported first-class mode.

The App Framework validator additionally checks roles/scopes,
provider/storage-type pairs, endpoints, paths, names, references, polling
bounds, and premium-app settings. Helm lint/template and exact live CR readback
still do not prove app compatibility or application behavior.

Enterprise `topologySpreadConstraints` is an accepted overlay field, but it
does not remove the generated M4 search-tier zone selector. It can spread SHC
members across matching nodes inside that zone; it does not establish a
cross-zone SHC. A stretched search tier requires a separate direct-CR or
specifically reviewed scheduling-overlay contract, plus live placement and
zone-failure validation outside this bundle.

### App Framework by Overlay

App Framework is supported on these custom resources:

| Custom resource | Supported scope |
|---|---|
| Standalone | local |
| ClusterManager | local and cluster |
| SearchHeadCluster | local and cluster |
| LicenseManager | local |
| MonitoringConsole | local |
| IngestorCluster | local |
| IndexerCluster | no direct App Framework; distribute through ClusterManager |

Upstream storage providers include AWS/S3-compatible object storage, Azure
Blob, and GCP Cloud Storage. The accepted v4 AppRepo volume schema permits an
optional existing `secretRef`. Provider-IAM/managed identity requires both
Operator and applicable Splunk pod identity and is an unvalidated runtime
handoff here; do not reuse the indexer-only SmartStore IRSA profile. Azure
shared-key Secrets use `azure_sa_name`/`azure_sa_secret_key`, grant
storage-account read/write, and have no automated rotation. GCP `key.json`
custody and rotation are likewise external. AppRepo `serviceAccount` is
rejected. App archives must be `.spl`, `.tgz`, or `.tar.gz`.

The SOK 3.1 CRD defaults `appInstallPeriodSeconds` to 90 and explicitly says not
to change it unless Splunk Support instructs you to do so. The strict overlay
therefore rejects an explicit value. Omit the field to preserve the default; a
Support-directed change is a reviewed direct-CR handoff.

App Framework does not preview compatibility, enable an app, safely remove an
installed app, or support downgrade. Persistent Operator staging storage is an
upstream prerequisite; this bundle preserves and validates its generated 10 Gi
RWO staging PVC and exact mount, and overlay replacement is rejected. Automatic
polling and manual-update ConfigMaps are upstream operations;
this skill does not trigger reconciliation directly.

See [enterprise-values-overlay.example.yaml](enterprise-values-overlay.example.yaml)
and <https://splunk.github.io/splunk-operator/AppFramework.html>.

### SOK Support-Data Collection

The upstream `k8s-splunk-collector.sh` and node-local
`k8s-systeminfo-collector.sh` are support-data tools, not Kubernetes telemetry
onboarding. They can gather broad object inventories, describe output, logs,
node/system information, optional Splunk diagnostics, and Secret metadata.
This skill does not download or execute them. Before manual use, review the
script version and requested privileges, reserve output space, define
retention/redaction, inspect the archive for sensitive data, and approve the
transfer destination. Operational log/metric ingestion remains owned by the
Splunk OTel/Kubernetes collection workflow.

## SOK Rendered Files

| File | Purpose |
|---|---|
| `README.md` | Bundle summary and review points |
| `metadata.json` | versions, topology, scope, profile, and source metadata |
| `bundle-manifest.json` | tracked-file SHA-256 and reviewed-mode inventory plus external-input hashes |
| `bundle-verify.py` | no-follow owner/mode/hash accidental-drift verifier used by live helpers; not a signature/provenance system |
| `namespace.yaml` | required namespace objects |
| `compatibility-check.py` | embedded 3.1 matrix check |
| `verify-cluster.sh` | exact reviewed kubecontext/API-server/cluster-UID guard |
| `preflight.sh` | context, compatibility, RBAC, dependency, and reference checks |
| `server-dry-run.sh` | phase-selectable `operator`, `enterprise`, or `all` Helm server-side dry-run used in minimal-mutation ordering |
| `apply.sh` | sole public mutation orchestrator; verifies, preflights, stages the license, then invokes internal helpers |
| `crds-install.sh` | versioned server-side CRD apply |
| `operator-values.yaml` | generated Operator values |
| `enterprise-values.yaml` | generated Enterprise values |
| `*-values-overlay.yaml` | optional copied, reviewed overlays |
| `splunk-operator-chart.tgz`, `splunk-enterprise-chart.tgz`, `splunk-operator-crds.yaml` | production-required snapshots of reviewed official artifacts |
| `helm-install-operator.sh` | guarded Operator install/upgrade |
| `helm-install-enterprise.sh` | server dry-run plus guarded Enterprise install/upgrade |
| `create-license-configmap.sh` | optional internal local-license helper; invoke through `apply.sh` |
| `eks-update-kubeconfig.sh` | optional bundle-local EKS context |
| `status.sh` | exact Helm/CRD/CR/Operator-object/Service/EndpointSlice/StatefulSet/pod identity, placement, and health validation plus events |

### SOK Apply and Status Ordering

The Enterprise resources cannot be server-dry-run before their CRDs exist. For
a new install, `apply.sh` verifies the bundle/cluster, creates the reviewed
namespaces and CRDs, then runs `server-dry-run.sh all` before either Helm install.
For an upgrade, it runs the Operator dry-run before any CRD mutation, applies
the reviewed CRDs, then runs the Enterprise dry-run against the new schemas
before changing either Helm release. This is the minimum-mutation ordering; the
CRD apply is deliberately the only mutation that can precede the Enterprise
dry-run on an upgrade.

Status regenerates the Operator server-side contract and exactly compares all
Helm-owned Deployments, ClusterRoles/Bindings, Roles/Bindings, ServiceAccounts,
staging PVCs, and Services after normalizing the documented dynamic
Helm/Kubernetes-assigned fields. It
also verifies the exact generated Splunk child Service inventory, safe
ClusterIP exposure and ports/selectors/owners, and ready EndpointSlices backed
by expected pods. In production, replicas within every replicated Splunk
StatefulSet must occupy distinct nodes. For M4, each reviewed pod's assigned
node must also carry its expected `topology.kubernetes.io/zone` label. The SHC
and deployer are expected in the same selected zone, so this readback does not
establish search continuity if that zone fails.

Every SOK render requires explicit acceptance through
`--accept-splunk-general-terms`, which renders
`--accept-sgt-current-at-splunk-com` into the Operator configuration. Operator
3.1 validates this before reconciling a Splunk CR, including supported 9.4.x
images.

For any SOK upgrade whose target resolves to Splunk Enterprise 10.4 or later,
`--allow-upgrade` must be paired with
`--confirm-splunk-10-4-upgrade-readiness`. The confirmation records that a
restorable platform and KV Store backup exists, the KV Store server is healthy
and version 7.0 or later, premium apps/add-ons are compatible, TLS 1.2 or later
is in use, and the target release's upgrade notes were reviewed. It is rejected
without `--allow-upgrade`; it does not replace the backup or test evidence.

The direct Splunk release-line gate permits same-line upgrades and these line
hops only: 9.4 to 10.0 or 10.2; 10.0 to 10.2 or 10.4; and 10.2 to 10.4. Other
line changes require the documented intermediate line first. Live Operator
1.0.5 or earlier requires the official 1.1.0 upgrade/cleanup handoff before a
3.1 upgrade. Separately, a deployment that still uses ClusterMaster or
LicenseMaster CRs requires the upstream 2.1.0-only maintenance-window
conversion/Rsync procedure before using this Manager-only renderer. Exact patch
support and release prerequisites still come from the target release notes.

## POD 10.4 Profiles

POD selectors with `-es` or `-itsi` are skill aliases; the static configuration
keeps the official base profile.

| Selector base | Max ingest | Base workers | ES/ITSI workers | Total nodes including 3 controllers and bastion |
|---|---:|---:|---:|---:|
| `pod-small` | 500 GB/day | 8 | 9 | 12 / 13 |
| `pod-medium` | 1 TB/day | 11 | 14 | 15 / 18 |
| `pod-large` | 2.5 TB/day | 15 | 18 | 19 / 22 |
| `pod-xlarge` | 10 TB/day | 30 | 33 | 34 / 37 |

Base topologies are:

- Small: one standalone search head, three indexers, four volume workers.
- Medium: three search heads, four indexers, four volume workers.
- Large: three search heads, seven indexers, five volume workers.
- X-Large: three search heads, seventeen indexers, ten volume workers.
- ES or ITSI adds one Small standalone or a three-member secondary SHC.

Every selector in this skill keeps the primary core search tier. A sole
ES/ITSI tier without that primary tier is not modeled. The product may accept
other second-tier layouts, but generic second tiers and sole-premium designs are
manual/vendor handoffs.

POD sizing and storage facts that remain external evidence:

- POD's SOK configuration allocates/limits each indexer pod at 36 CPU/96 GB and
  each search-head pod at 24 CPU/96 GB; prove matching allocatable capacity plus
  system/failure headroom;
- Small/Medium/Large use a 90-day local cache and one-year SmartStore retention;
  X-Large uses a 60-day cache and 180-day SmartStore retention;
- SeaweedFS uses three managers, at least three filers, one volume process per
  volume worker, and three replicas for two-volume-node failure tolerance;
- X-Large spans two racks and four switches with complete cross-rack
  reachability.

The renderer validates the static address/count blueprint. It does not prove
CPU/RAM, RAID, process placement, SeaweedFS quorum/replication, retention, rack
placement, or failure tolerance.

Source:
<https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.4/splunk-pod-architecture>

## POD Live Input Gates

Render-only output may contain example IPs and placeholder paths. A one-command
live run (`--phase all` or render plus `--apply`) requires:

- exactly three unique controller IPs
- the exact profile-specific worker count, with no duplicates or overlap
- the executable installer path
- an independently reviewed installer SHA-256 matching the snapshotted binary
- an installer `-version` result matching `--pod-version`
- one or more `.lic` files; live ES/ITSI profiles require two physically
  distinct Enterprise and premium-product license files
- a private SSH key with mode `0600` or stricter
- an explicit immutable primary search-tier name
- an explicit immutable secondary name for ES/ITSI
- every supplied app package to exist locally
- `--confirm-new-pod-install` before `deploy.sh` may mutate a new cluster

`preflight`, `apply`, and `status` against an existing bundle require only the
correct `--target pod` and output directory; they use the profile, installer,
and other inputs already embedded and integrity-checked during render.

## POD Static Configuration and App Scopes

| CLI input | Static configuration destination |
|---|---|
| `--indexer-apps` | `clustermanager.apps.cluster` |
| `--cluster-manager-apps` | `clustermanager.apps.local` |
| `--search-apps` | primary `searchheadcluster[].apps.cluster` |
| `--search-deployer-apps` | primary `searchheadcluster[].apps.local` |
| `--standalone-apps` | primary `standalone[].apps.local` |
| `--premium-apps` | secondary ES `apps.premium` |
| `--itsi-apps` | secondary ITSI standalone local or SHC cluster scope |
| `--license-manager-apps` | `licensemanager.apps.local` |

Optional app lists render as empty lists, not fake package paths. ES live
workflows require `--premium-apps`, `--indexer-apps` including matching
`Splunk_TA_ForIndexers`, and two physically distinct Enterprise/ES `.lic`
files. The `premium` scope is ES-only.

This implementation requires POD `10.2.1_1.5.0` or later because every live
workflow uses the installer preflight-only command introduced in that bundle.
License Manager app input and name-based routing require `10.4.0_1.6.0` or
later; `--allow-unverified-versions` does not bypass either feature gate.

ITSI live workflows require:

- at least Enterprise and ITSI license files, comma-separated through
  `--license-file`
- repackaged ITSI sub-apps and the OpenJDK 17 custom app in `--itsi-apps`
- `SA-IndexCreation` and `SA-UserAccess` in the ITSI search-tier list
- `SA-IndexCreation` in `--indexer-apps`
- `SA-ITSI-Licensechecker` and `SA-UserAccess` in
  `--license-manager-apps`; Licensechecker must not be on the search tier

App Framework reconciliation is installer-managed against POD's internal
SeaweedFS. App removal and downgrade are not supported. Duplicate package
internal names and app compatibility must be reviewed before deployment.

For custom indexes, the Manage guide says POD automatically injects
`frozenTimePeriodInSecs=31536000` (one year), while the architecture documents
180-day retention for X-Large. The skill's `indexes.conf` linter requires
home/cold/thawed paths and rejects POD-owned `repFactor`/`remotePath`, but it
cannot resolve that product-documentation conflict. Require effective-setting
readback and Splunk guidance before accepting X-Large custom-index retention.

Source:
<https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.4/manage-splunk-pod>

## POD TLS, Routing, and Access

IP routing is the product default. Name routing can use the POD-provided
certificate without custom material; `--ingress-domain` records the reviewed
DNS suffix, and browsers can warn unless that certificate is trusted. A custom
wildcard certificate is optional and supplies trusted name-based TLS. When a
custom certificate is used, the domain, chain, private key, and CA bundle are
all mandatory:

```yaml
certificate:
  ingress:
    certificate: /absolute/path/fullchain.pem
    privateKey: /absolute/path/privkey.pem
```

The skill validates the wildcard SAN against the domain, certificate chain,
server purpose/key usage, CA:FALSE, key match and strength, signatures, at least
30 days of remaining validity, and private-file ownership/mode. It does not
create DNS records, issue/renew certificates, distribute trust, or perform the
official post-renewal redeployment. Current component access includes:

| Component | Default port |
|---|---:|
| primary SHC / HEC | 443 |
| secondary SHC | 8100 |
| Small standalone 1 / 2 | 8000 / 8001 |
| Cluster Manager | 1443 |
| License Manager | 2443 |
| Monitoring Console | 3443 |
| Perses | 3000 |
| Splunk-to-Splunk | 9997 |
| name-routed Splunk management API | 8089 |

POD also supplies named routes for management APIs, deployer, Prometheus, and
Perses according to the official route table. Do not infer equivalent access
from IP routing: the management API is exposed through named routing, not as a
general worker-IP port. HEC token management, DNS, firewall/load balancing,
certificate renewal, and application validation remain separate handoffs.

Universal Forwarder configuration is not part of POD deployment. Use
`splunk-universal-forwarder-setup` or `splunk-agent-management-setup`; UF 9.4.1
and later require `forcedTimeBasedAutoLB=true` for the POD multi-worker receiver
path.

Source:
<https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.4/network-routing-and-ingress-for-splunk-pod>

## POD Cisco CVD Prerequisites

The software skill assumes the validated infrastructure is already prepared:

- Cisco UCS C225 M8S for bastion, controller, and search-head roles
- Cisco UCS C245 M8SX for indexer and volume roles
- Nexus N9K-C9336C-FX2 switching; X-Large spans two racks/four switches
- Cisco Intersight server profiles and current validated VIC/enic drivers
- RHEL 9.6, passwordless sudo, non-interactive SSH, Chrony active
- SELinux, firewalld, and Transparent Huge Pages disabled as documented
- exact RAID, ext4, `/data/shared`, and `/data/storage` layouts
- allocatable capacity and headroom for POD's 36 CPU/96 GB indexer-pod and
  24 CPU/96 GB search-head-pod allocations/limits
- three SeaweedFS managers, at least three filers, one volume process per
  volume worker, and the documented three-replica policy
- full all-to-all reachability, including across both X-Large racks, plus
  reviewed DNS/TLS routing

The installer does not configure RAID. Use its preflight as evidence, not as a
replacement for the CVD build record.

Sources:

- <https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.4/splunk-pod-requirements>
- <https://www.cisco.com/c/en/us/td/docs/unified_computing/ucs/UCS_CVDs/cisco_ucs_splunk_pod.html>

## POD Rendered Files and Lifecycle

| File | Purpose |
|---|---|
| `README.md` | reviewed profile, version, input, and lifecycle summary |
| `cluster-config.yaml` | static installer blueprint |
| `metadata.json` | coupled version, profile, counts, reviewed inputs, and installer digest |
| `bundle-manifest.json` | tracked-file SHA-256/reviewed-mode map plus external-input hashes |
| `bundle-verify.py` | current-user owner, exact-mode, no-follow hash verifier used by POD helpers; an accidental-drift control, not a signature |
| `kubernetes-installer-reviewed` | private `0500` snapshot of the reviewed installer binary |
| `pod-inputs.py` | no-follow validation and private staging of every external app/license/key/certificate input |
| `pod-artifacts.py` | archive, ES/ITSI, indexes.conf, JDK, SSH-key, and TLS validation |
| `preflight.sh` | installer digest/version match, artifact gates, and native installer preflight |
| `deploy.sh` | guarded new install only; upgrade/app reconciliation fails closed |
| `status-workers.sh` | worker status |
| `status.sh` | pod status |
| `wait-ready.sh` | bounded worker/pod convergence loop |
| `get-creds.sh` | sensitive local admin/HEC credential retrieval |
| `web-docs.sh` | installer-local documentation server |
| `diagnostics.sh` | bounded sensitive `-get.logs`/`-get.diag` collection into a separate private temporary directory |

`deploy.sh` is deliberately new-install-only and requires an independently
reviewed installer SHA-256 plus `--confirm-new-pod-install`. For upgrade, render
with `--allow-upgrade` to collect artifact/preflight evidence, then follow the
official lockstep runbook and vendor review outside this helper; `deploy.sh`
will refuse mutation. All bundled components upgrade together. License renewal,
day-2 app add/update, certificate redeployment, app deletion/downgrade, and
restoration are likewise manual/vendor workflows. The skill intentionally does
not expose `-destroy`; destruction permanently removes the cluster and data.

The POD bundle includes its supported OCI payload and product-managed
Prometheus/Perses components, but this skill does not independently inventory
offline images or configure dashboards/alerts. Splunk Agent Management is a
separate application workflow. The installer `-kubectl` shell remains a manual
troubleshooting handoff; use the documented status helpers, bounded readiness, logs, and
diagnostics before escalating.

The 10.4.0_1.6.0 release notes list EIST-574, in which CoreDNS may be absent on
a new-cluster deployment. `wait-ready.sh` surfaces the resulting non-readiness.
The documented sequence first retries `-deploy`, then, if necessary, uses the
destructive `-destroy`/`-deploy` fallback. Once status indicates a partial or
existing deployment, this skill automates neither recovery path; use a reviewed
manual/vendor handoff and complete the data-impact review first.

Upgrade source:
<https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.4/upgrade-splunk-pod>

## Validation Commands

```bash
# Static SOK checks; add --strict to require Helm semantic validation.
bash skills/splunk-enterprise-kubernetes-setup/scripts/validate.sh \
  --target sok

# Strict POD checks reject placeholders, bad package placement, and unresolved files.
bash skills/splunk-enterprise-kubernetes-setup/scripts/validate.sh \
  --target pod \
  --strict

# Live checks capture status before emitting one JSON result.
bash skills/splunk-enterprise-kubernetes-setup/scripts/validate.sh \
  --target sok \
  --live \
  --json
```

Validation does not replace end-to-end ingest/search checks, Enterprise
Security or ITSI post-install validation, backup restoration tests, or external
cloud/Cisco readiness evidence.

## Additional Official References

- SOK Helm installation: <https://splunk.github.io/splunk-operator/Helm.html>
- SOK multisite indexer/search-head examples: <https://splunk.github.io/splunk-operator/MultisiteExamples.html>
- SOK upgrade behavior: <https://splunk.github.io/splunk-operator/SplunkOperatorUpgrade.html>
- SOK App Framework: <https://splunk.github.io/splunk-operator/AppFramework.html>
- SOK 3.1 CRD schema: <https://github.com/splunk/splunk-operator/blob/3.1.0/config/crd/bases/enterprise.splunk.com_standalones.yaml>
- SOK premium apps: <https://splunk.github.io/splunk-operator/PremiumApps.html>
- SOK indexing/ingestion separation: <https://splunk.github.io/splunk-operator/IndexIngestionSeparation.html>
- SOK security/TLS: <https://splunk.github.io/splunk-operator/Security.html>
- SOK ingress: <https://splunk.github.io/splunk-operator/Ingress.html>
- SOK external License Manager/indexer examples: <https://splunk.github.io/splunk-operator/Examples.html>
- SOK legacy CR terminology transition: <https://splunk.github.io/splunk-operator/BiasLanguageMigration.html>
- POD deployment: <https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.4/deploy-splunk-pod>
- POD troubleshooting: <https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.4/troubleshoot-splunk-pod>
