# Splunk Enterprise Kubernetes Coverage

This matrix prevents a rendered packet from being mistaken for complete product
support.

## Status Legend

| Status | Meaning |
|---|---|
| First-class | A CLI flag, renderer, guardrail, generated helper, and relevant validation exist in this skill. |
| Overlay | The upstream SOK chart supports the field and the skill preserves a reviewed non-secret Helm values overlay; semantic ownership remains with the operator. |
| Handoff | The product capability is relevant, but another skill, cloud/Cisco owner, or documented manual procedure owns it. |
| Product-managed | The underlying product supplies the capability; this skill may validate access but does not configure it. |
| Unsupported | The product or this skill does not safely support the operation; fail closed. |

Qualifiers such as `constrained`, `package mapping`, and `+ handoff` refine these
base statuses. An Overlay or Handoff row is not successful setup evidence.
Record the owning team, artifact, and readback separately.

## SOK 3.1 Coverage

| Capability | Status | Current coverage and boundary |
|---|---|---|
| Operator/chart/Splunk compatibility | First-class | Verified Operator `3.1.0` matrix, exact GA version/tag checks, live/offline Kubernetes checks, and matching chart/CRD checks. Production requires hash-verified local official chart and CRD snapshots plus digest-pinned Operator/Splunk images and cannot bypass the matrix. |
| CRD OpenAPI/CEL admission | First-class artifact + product-managed enforcement | The exact official 3.1 CRD snapshot, including OpenAPI and `x-kubernetes-validations` rules, is hash-locked, checked, applied before CR dry-run, and enforced by the API server. This is independent of the optional incompatible validation webhook below. |
| Direct manifest/Kustomize installation | Upstream-supported, incompatible handoff | Upstream supports non-Helm installation, but this skill's ownership, upgrade, inventory, and exact object contracts are Helm-only. Do not adopt a direct/Kustomize install into this bundle without a separate migration/ownership design. |
| Splunk General Terms | First-class | Explicit acceptance is required for every SOK render because Operator 3.1 validates the value before reconciling a Splunk CR, including supported 9.4.x images. The flag renders the required Operator value. |
| S1 | First-class, exactly one Standalone | One Standalone, storage, resources, optional local license, SmartStore, and scoped IRSA service account. A multi-replica Standalone CR is not this S1 preset and is rejected; separate independent Standalones require a direct design with distinct data and remote-store ownership. |
| C3 | First-class | ClusterManager, IndexerCluster, SearchHeadCluster, optional LicenseManager, MonitoringConsole, replica minimums. |
| M4 | First-class, exact two-site indexer preset | Chart 3.1.0 fixes the M4 multisite RF/SF totals at two. The skill renders exactly `site1` and `site2`, per-site IndexerClusters in unique zones, and live placement readback. Its SHC and deployer are site-affined and pinned to one selected Kubernetes zone; this is not a stretched multi-zone search tier, and zone-failure search continuity is not established. |
| M4 3-63 sites or custom RF/SF | Direct-CR handoff | These require reviewed direct CRs and factors; they must not be forced through the chart's fixed two-site M4 preset. This skill does not synthesize or validate that custom multisite contract. |
| Search-head `site0` or stretched/multi-zone SHC | Direct-CR / specifically reviewed-overlay handoff | Upstream notes that SHCs do not have site awareness for artifact replication and generally recommends `site0` to disable multisite search affinity. This preset instead site-affines and single-zone-pins the SHC/deployer. An accepted topology-spread overlay cannot remove the protected zone selector, so it may spread pods across nodes only within that zone. A stretched search tier needs a separate CR/scheduling contract and zone-failure testing. |
| C1/C11, C13, M2/M12, M3/M13, M14 | Handoff | Upstream Applied SVA guidance supports these direct-CR compositions, but the Helm chart has presets only for S1/C3/M4 and this renderer does not relabel or synthesize the other topologies. |
| D1/D11 | Unsupported by this renderer | Upstream marks this topology not recommended. Do not present it as a supported preset. |
| v4 CR vocabulary | First-class | New assets use Standalone, ClusterManager, IndexerCluster, SearchHeadCluster, LicenseManager, MonitoringConsole, Queue, ObjectStorage, and IngestorCluster. Legacy ClusterMaster/LicenseMaster output is rejected. |
| Legacy Operator transition (1.0.5 or earlier) | Handoff | Follow the official upgrade/cleanup procedure before using this upgrade path; the skill does not synthesize legacy CR/RBAC conversion. |
| Legacy ClusterMaster/LicenseMaster CR transition | Handoff | New bundles use only ClusterManager/LicenseManager. Existing legacy CRs require the upstream 2.1.0-only maintenance-window conversion/Rsync procedure, backup, RF/SF recovery, validation, and deliberate old-CR cleanup; this skill neither runs that procedure nor accepts the legacy kinds. |
| Namespace-scoped Operator | First-class | Operator and Enterprise must share a namespace. |
| Cluster-scoped Operator | First-class, one deployment namespace | Separate operator namespace with exactly one watched Enterprise namespace per bundle. Cluster-wide Operator/RBAC collisions are inventoried before apply. |
| One Operator / multiple deployment namespaces | Handoff | Upstream cluster-scoped installation supports a comma-separated watch list. This renderer intentionally accepts exactly one watched Enterprise namespace per bundle and does not orchestrate cross-namespace topology, Secret, or licensing ownership; build and validate that fleet through a direct Helm/CR handoff. |
| Multiple Operators / multiple namespaces | Handoff | Use disjoint watch scopes and prove cluster-scoped RBAC/Helm ownership. This bundle rejects an overlapping Operator but does not orchestrate a fleet. |
| Multiple SVAs in one namespace | Handoff | Upstream tenancy pattern is not represented by this bundle's one release/one reviewed topology contract. |
| EKS context | First-class | Bundle-local kubeconfig helper with 1-100-character EKS name validation; AWS authentication remains a handoff. Production also locks exact kubecontext, API server, and `kube-system` UID. |
| Kubernetes distributions | Generic core contract + evidence-qualified handoffs | Upstream reports development/testing on EKS and GKE, customer use on AKS/OpenShift, partner testing on HPE Ezmeral, and generic availability for CNCF-certified distributions. This renderer validates portable Kubernetes primitives, not equal vendor test depth. Distribution-specific identity, ingress/LB, CSI, security/admission, SCC/Route, and support evidence remain platform handoffs. |
| Development/production gates | First-class | Production requires explicit storage, confirmed SmartStore index inventory, licensing/authentication, local artifacts, digest-pinned images, exact cluster identity, and M4 site/zone placement. This is not capacity certification. |
| PVC class/capacity | First-class Kubernetes mechanics + storage handoff | Shared etc/var sizes and StorageClass flags are semantically locked. Status proves exactly two template-derived, Bound claims per StatefulSet ordinal, exact class/access/volume mode/request/capacity/labels, and exact pod mounts. This does not certify a CSI/provider, IOPS/latency/durability, encryption, snapshots, expansion, or HA suitability. Upstream documents EKS EBS/GKE PD/local-PV guidance and only basic-functionality evidence for several third-party systems; storage-owner and sizing evidence remain mandatory. Per-role resizing or migration is a reviewed handoff. |
| Node/runtime prerequisites | Platform-owner evidence | Apply Splunk reference-hardware sizing to allocatable Kubernetes capacity, retain CPU/memory/storage headroom, disable Transparent Huge Pages where required by current guidance, and prove NVMe/SSD-class SmartStore cache latency/IOPS, clock synchronization, failure domains, and node recovery. Resource/PVC syntax and live placement do not attest node tuning or performance. |
| CPU/memory resources | First-class Guaranteed-QoS shape + sizing handoff | Production requires complete CPU/memory request=limit pairs for every Splunk role and the SHC deployer. Reviewed equal-pair overlay values are accepted; live StatefulSet resources are compared to the owning CR using Kubernetes quantity semantics (`1` equals `1000m`) while malformed quantities fail closed. `splunk-platform-sizing` still owns capacity approval. |
| Local license | First-class | One file, ConfigMap helper, Standalone or generated LicenseManager linkage. License contents are never rendered into repository files. |
| License expiry evidence | Fail-on-observed warning + handoff | When a LicenseManager exists, status fails on a current same-UID Operator `Warning/LicenseExpired` Event. Absence of an Event is not positive entitlement proof, and S1 local `licenseUrl` has no LicenseManager event path. Validate active license state through approved Splunk license-owner/API evidence; file hash, mount, and Ready phase alone do not certify entitlement or expiry. |
| Existing same-namespace SOK LicenseManager | First-class | Name and an omitted or explicitly matching namespace for an Operator-managed v4 LicenseManager CR, exact Helm linkage, and live `Ready` preflight. This flag is not an arbitrary external Splunk endpoint. |
| Existing cross-namespace SOK LicenseManager | Handoff / rejected by strict bundle | Upstream object references can name a namespace, but this bundle's one-namespace ownership/status contract rejects a different namespace. Use the one-Operator/multi-namespace direct Helm/CR handoff. |
| External non-SOK License Manager | Upstream-supported handoff | Upstream requires a shared `pass4SymmKey`, the Operator global Secret, and a `defaultsUrl`/volume carrying the external license-manager URL. Those secret/default/volume mutations are protected here, and the skill cannot read back the external manager's health or license state. |
| Existing ClusterManager/MonitoringConsole | Handoff / rejected by strict bundle | Upstream chart values exist, but this renderer locks local `cm`/`mc` topology and rejects replacement references. |
| External indexer cluster | Upstream-supported handoff | Upstream can connect an Operator-managed Standalone, SearchHeadCluster, or LicenseManager to an external indexer cluster through a shared IDXC `pass4SymmKey` and `defaultsUrl`/volume. S1/C3/M4 bundles here own their index tier, protect those fields, and do not validate the external Cluster Manager, peers, RF/SF, or connectivity. |
| MonitoringConsole | First-class | Generated for C3/M4 unless explicitly disabled; status waits on its CR phase. |
| Operator Helm object contract | First-class live readback | Status regenerates both the raw Helm intent and server-side contract, then exactly compares Helm-owned Deployment, ReplicaSet/pod UID lineage, cluster/namespaced RBAC, ServiceAccount, staging PVC, and Service inventory/spec after normalizing documented Helm/Kubernetes defaults and dynamic fields. |
| Splunk workload runtime contract | First-class live readback | Status proves CR UID to StatefulSet to pod ownership, exact role/image/container/port/resource/service-account/PVC/scheduling inventory, OnDelete lifecycle, topology/license environment values, safe upstream 3.1 security contexts, and exact volume sources. Only the reviewed SmartStore init container and App Framework/defaults/license mounts are admitted when their owning CR features require them; injected init, ephemeral, sidecar, host-namespace, hostPath, or arbitrary mounts fail. Equivalent resource quantities are normalized without weakening the contract. An automount-disabled service account may have no API-token projection; when present, exactly one canonical projection and read-only mount are required. |
| Operator probe scripts and workload probes | First-class for verified 3.1.0 | Status verifies the namespace probe ConfigMap identity, exact key inventory, and official 3.1.0 script hashes; every Splunk workload must use the expected ConfigMap/mount and all three exec handlers. Custom probe scripts and arbitrary probe handlers require a versioned direct-CR/support handoff. |
| AWS SmartStore | First-class, single volume with upstream warning | `aws` provider, explicit region, partition-aware HTTPS endpoint, bucket/prefix, exact reviewed index inventory, Secret reference or the scoped AWS IRSA contract. Production requires both inventory/migration and exclusive active bucket/prefix ownership attestations; the renderer cannot discover another deployment using the same remote path. Status reconstructs ConfigMap content, proves StatefulSet revision adoption, verifies CM mounted token and completed manager-app bundle push, and never emits credential values. Upstream labels direct CR index/config installation a temporary method and recommends App Framework; review that product guidance before production acceptance. |
| MinIO/S3-compatible SmartStore | First-class, single volume with upstream warning | `--smartstore-provider minio` requires an explicit HTTPS endpoint. Validate API compatibility, TLS trust, authentication, durability, and the Splunk release externally. The same upstream temporary-method/App Framework recommendation applies. |
| Multiple SmartStore volumes/per-index volume routing | Handoff | Upstream CR supports these patterns, but strict validation intentionally locks one `remote_store` volume and all reviewed indexes to it. |
| SmartStore cache/per-index tuning | Handoff | The strict renderer locks its single-volume/index contract. Additional cache/index tuning requires a separately reviewed design plus sizing, retention, encryption, and recovery evidence. |
| Azure/GCP SmartStore | App Framework + handoff | Official guidance requires Splunk app configuration deployed through App Framework; Azure/GCP are not first-class SmartStore CR provider modes here. |
| Existing-index SmartStore migration | Handoff | Existing local index data must be migrated before CR enablement. Prove migration, `repFactor`, cache, encryption, retention, and restore behavior. |
| Indexing and ingestion separation | First-class, constrained | C3 only; upstream `sqs` or `sqs_cp` queue mode, AWS SQS/DLQ, S3 oversized-message storage, IngestorCluster, Queue/ObjectStorage references, and required Queue Secret authentication. Workload service accounts are rejected in the verified 3.1 path. |
| I&I cloud resource creation | Handoff | Queue, DLQ, bucket, IAM/KMS, endpoints, and the `s3_access_key`/`s3_secret_key` Secret are external. |
| I&I Queue region grammar | First-class | `--queue-region` is checked against the narrower SOK 3.1 Queue CRD OpenAPI grammar, not merely a general AWS-region parser. |
| I&I on M4 or non-AWS providers | Unsupported by this renderer | Do not force through an overlay without a separate supported design and validation workflow. |
| I&I queue/object-store updates | First-class rejection + handoff | Upgrade preflight rejects immutable Queue/ObjectStorage/ref changes. Queue credential volumes are the upstream mutable exception; replacement requires a migration and recovery design. |
| I&I Queue credential volume | First-class workaround | Chart 3.1.0 mis-serializes `queue.sqs.volumes`; the skill renders the documented Queue CR through `extraManifests` and checks the resulting Secret reference. |
| I&I horizontal autoscaling | Handoff | Upstream documents HPA for IngestorCluster, but customer HPA manifests are outside the strict Helm kind allowlist. Metrics and capacity evidence are required. |
| I&I Grafana dashboards | Handoff | Upstream provides an example only. Metrics stack, dashboard lifecycle, and alert ownership remain external. |
| App Framework | Constrained Overlay | `appRepo` can be supplied for supported CRs. The skill copies/hashes it and validates structure, roles/scopes, providers, endpoints, paths, references, polling bounds, and premium settings, but does not inspect packages or app compatibility. |
| App Framework `appInstallPeriodSeconds` | Support-directed direct-CR handoff / rejected | The SOK 3.1 CRD defaults this reconcile install window to 90 seconds and says not to change it unless instructed by Splunk Support. The strict overlay rejects an explicit value; omit the field to retain the default, or use a Support-reviewed direct-CR handoff. |
| App Framework AWS/S3-compatible storage | Secret-backed Overlay; workload identity unvalidated handoff | An existing `secretRef` is the fully reviewed path. Upstream IAM requires identity on both Operator and applicable Splunk pods, but this bundle has no dedicated Operator identity input or exact Operator-pod admission-mutation gate; do not reuse the indexer-only SmartStore IRSA contract. Ambient node identity is an external risk-reviewed handoff. AppRepo `serviceAccount` is absent from v4 and rejected. |
| App Framework Azure Blob | Secret-backed Overlay; managed identity unvalidated handoff | Existing `secretRef` uses `azure_sa_name`/`azure_sa_secret_key`; that shared key grants storage-account-level read/write and has no automated rotation, so custody/rotation are explicit owner obligations. The preferred managed-identity path is not live-validated by this bundle. AppRepo `serviceAccount` is rejected. |
| App Framework GCP Cloud Storage | Secret-backed Overlay; workload identity unvalidated handoff | Existing `secretRef`/`key.json` is supported with external key custody and rotation. Operator-plus-workload identity admission is not live-validated by this bundle. AppRepo `serviceAccount` is rejected. |
| Standalone app local scope | Overlay | Supported upstream through Standalone `appRepo`. |
| Indexer app cluster scope | Overlay | Configure ClusterManager `appRepo` with cluster scope; IndexerCluster has no direct App Framework. |
| Search-head local/cluster scopes | Overlay | Configure SearchHeadCluster `appRepo`; deployer and member placement must be reviewed. |
| LicenseManager/MonitoringConsole/Ingestor apps | Overlay | Local scope on each supported CR. Restart-required Ingestor apps need the documented annotation/label rolling-restart handoff because SOK cannot detect that requirement. |
| Enterprise Security through App Framework | Overlay + security handoff | Automated premium-app support applies to S1, C1/C11, and C3/C13—not M4/M14. Package/version checks, `Splunk_TA_ForIndexers`, and post-install work belong to `splunk-enterprise-security-install` and `splunk-enterprise-security-config`. |
| ITSI on generic SOK | Unsupported in-cluster + handoff | Upstream does not support ITSI installation on SOK. The documented workaround is an externally managed ITSI search tier using SOK indexers. POD's separate ITSI flow is covered below. |
| App polling/manual reconciliation | Overlay + handoff | Poll interval can be overlaid; namespace/per-CR manual-update ConfigMaps and same-CR-type polling consistency remain day-2 operations. |
| App Framework `clusterWithPreConfig` | Unsupported / rejected | The broken legacy scope is explicitly rejected; use supported `local`, `cluster`, or `premiumApps` role mappings. |
| App Framework staging PVC | First-class enforced chart default | The strongly recommended 10Gi RWO persistent staging PVC, exact mount, StorageClass, and identity are validated. This skill does not accept staging-volume replacement overlays. |
| Private image registry/image pull Secrets and policy | First-class images + constrained Operator Overlay | Operator and Enterprise image references/tags/digests are first-class. Runtime locks CR `imagePullPolicy` to `IfNotPresent`; alternate policies are a direct-CR handoff. Only Operator `imagePullSecrets` is accepted by the strict overlay; Enterprise pull-secret configuration and all credentials require a first-class/platform handoff. |
| Distroless Operator image | First-class | A custom Operator image tag matching `3.1.0-distroless` is accepted; production also requires its digest. Runtime/security validation remains operator-owner evidence. |
| Disconnected/air-gapped SOK | Constrained first-class artifacts + handoff | Local reviewed chart/CRD snapshots and mirrored digest-pinned images avoid apply-time public artifact drift. Registry reachability, image mirroring, Helm/CRD acquisition provenance, OS packages, and complete disconnected-cluster proof remain external. |
| Service accounts/workload identity | First-class SmartStore AWS IRSA + handoff | The reviewed IRSA identity is assigned only to S1 Standalone or C3/M4 IndexerCluster peers; CM, SHC/deployer, LM, and MC do not receive S3 permissions. The role ARN, ServiceAccount annotations, regional STS setting, deterministic token TTL, projected volume, injected environment, and mounts are live-validated. I&I is Secret-only in this verified 3.1 path. App Framework Operator identity, EKS Pod Identity, Azure/GCP identity, per-role alternatives, IAM policy contents, and trust bindings remain separate handoffs. |
| Labels and annotations | Constrained Overlay | Accepted when they do not change protected identity/topology contracts. Arbitrary environment variables are protected. |
| Overlay schema/typo detection | First-class | Operator overlays accept only the `splunkOperator` root and ten named keys; Enterprise overlays accept only seven role roots and seven named role keys. Unknown or misspelled Helm values fail before rendering. |
| Automatic SOK product telemetry | Product behavior + policy/egress handoff | Operator 3.1 installs `app_tel_for_sok`, collects CR/resource topology and license information, and attempts transmission every six hours. No SOK-specific Operator opt-out flag is claimed here. Review the Splunk Enterprise telemetry policy, disclosure/approval, DNS/egress, and any supported change separately; arbitrary Operator environment overrides are rejected. |
| Scheduling constraints | First-class for M4 preset zones; constrained Overlay otherwise | Production M4 exact zone selectors are locked. Operator `nodeSelector`/affinity/tolerations and Enterprise affinity/tolerations/topology spread may be overlaid; Enterprise `nodeSelector` and unknown keys are rejected. SHC topology spread does not override the preset's single-zone selector or establish a stretched search tier. |
| Production replica placement | First-class live gate | Replicas within each replicated Splunk StatefulSet must run on distinct Kubernetes nodes. M4 additionally requires every reviewed pod's assigned node to match its expected zone label. For SHC/deployer this proves the intended single-zone placement, not search continuity after that zone fails. |
| Probes and health timing | Protected / handoff | Probe overrides are rejected; live CR/pod waits remain first-class. Use a separately reviewed product/platform design if defaults are insufficient. |
| Services | Protected / handoff | `service` and `serviceTemplate` overrides are rejected. Separate Services/ingress are outside the overlay allowlist and require independent apply/readback. |
| Generated Splunk Services/EndpointSlices | First-class live health | Status enforces exact role Service inventory, owner/selector/safe ClusterIP exposure, expected ports, StatefulSet service linkage, and ready EndpointSlices backed by all expected pods. |
| Ingress and external TLS | Handoff | `extraManifests` and `serviceTemplate` are protected. External ingress must preserve sticky Splunk Web sessions; a forwarder load balancer must resolve to at least two IPs; Indexer Discovery is unsupported; encrypted and clear forwarding should use separate ports; and controller-specific TLS termination limits apply (Ingress NGINX TCP requires end-to-end TLS). DNS, PKI, WAF/LB, and reachability remain external. |
| Splunk internal TLS/PKI | Handoff | Use `splunk-platform-pki-setup` and the supported SOK security documentation. |
| Automatic Splunk TLS certificate lifecycle | Unsupported upstream | SOK does not provide a general automatic Splunk certificate rotation lifecycle. External PKI ownership and renewal evidence are required. |
| FIPS 140-3 compliant cluster | Product prerequisite + handoff | Upstream states that the standard provided Operator and Splunk container images need no modification. The Kubernetes cluster must already have FIPS 140-3-compliant nodes; this skill does not build or attest node crypto posture or end-to-end compliance. |
| Password initialization/rotation | Handoff | The chart/operator manages generated credentials and Secret references; this skill does not set, reveal, or rotate Splunk passwords. |
| Global Secret/manual UI password changes | Product constraint | Preserve the Operator-managed global Secret contract. Manual Splunk Web password changes are not a supported replacement for that lifecycle. |
| HEC enablement/tokens | Handoff | The Operator-managed global Secret and rendered services do not constitute HEC onboarding. Use `splunk-hec-service-setup`, constrain indexes/sources, and prove ingest separately. |
| Ingest Actions | App Framework + handoff | Deliver supported app content only through the validated App Framework path; configuration and outcome validation belong to `splunk-ingest-actions-setup`. |
| Validation webhook | Incompatible handoff | Upstream webhook installation is opt-in through its documented Kustomize/cert-manager path, is not a Helm value, and does not cover every newer CR. Its validators reject documented M4 two-replica sites, non-`Gi` storage quantities, and an empty development StorageClass. Its enablement also mutates the Operator Deployment beyond this bundle's exact Helm/runtime contract. Do not combine it with this profile: status must fail until a separate webhook-aware renderer and compatibility contract exist. |
| OpenShift | Handoff | Upstream has an OpenShift guide, but this renderer has no SCC/Route/platform-specific preflight contract. |
| Kubernetes log/metric collectors | Handoff | Use the Splunk OTel/Kubernetes collection workflow; installing Splunk Enterprise does not onboard cluster telemetry. |
| Kubernetes support-data collectors | Sensitive manual handoff | Upstream `k8s-splunk-collector.sh` and node-local `k8s-systeminfo-collector.sh` gather broad Kubernetes objects, logs, system data, optional Splunk diagnostics, and Secret metadata for support. They are distinct from telemetry collection and are not bundled or run here. Review contents, privileges, free space, retention, redaction, and the approved transfer destination before use. |
| `kubectl-splunk` plugin | Handoff | Optional upstream day-2 client tooling is not installed or validated by this skill. |
| NetworkPolicy, Pod Security, and admission policy | Handoff + exact Splunk workload gate | Additional Kubernetes kinds and policy objects are not accepted through this bundle's overlays. Platform-owner review/apply/readback is required. Splunk workload admission mutations—including sidecars, unsafe security context, host paths, extra/substituted volumes, mounts, or environment—fail except the optional canonical Kubernetes API token and reviewed SmartStore IRSA deltas. Operator Deployment intent and pod lineage are validated, but arbitrary Operator-pod admission mutation is not an identity contract; use a dedicated handoff. |
| PodDisruptionBudget | Compatible external-manifest handoff | Upstream documents a separately managed PDB. This bundle does not render or own it; the platform owner must apply and validate it against maintenance, quorum, and availability requirements. |
| HPA | Incompatible with strict bundle contract | HPA changes replica ownership and conflicts with this bundle's exact replica/status baseline, including documented Ingestor HPA examples. Use a separate autoscaling-aware renderer and capacity contract. |
| Defaults URLs and extra env | Protected / handoff | `defaultsUrl`, `defaultsUrlApps`, `extraEnv`, and `extraEnvs` are rejected to preserve provenance, secrets, and exact runtime identity. Live `SPLUNK_DEFAULTS_URL` must exactly contain the Operator-generated inline-defaults ConfigMap source when the reviewed CR has inline defaults (including M4), followed by the versioned Secret source; prepended remote or arbitrary local sources fail closed. |
| `licenseUrl` and extra volumes/mounts | Protected / handoff | Licensing is owned by first-class flags; arbitrary volumes and mounts are rejected. App Framework's validated storage-volume schema is the narrow exception. |
| Scheduler selection | Protected / handoff | `schedulerName` is outside the strict role allowlist. Custom scheduling policy requires a separately reviewed renderer/platform contract. |
| Cluster DNS domain | Protected / handoff | Operator environment overrides used to change `clusterDomain` are rejected. A non-default cluster domain requires an independently reviewed upstream/platform design. |
| Ephemeral Splunk etc/var storage | Unsupported by this bundle | Generated storage uses `ephemeralStorage: false` and strict validation locks it. |
| `extraManifests` | Protected / handoff | User overlays cannot add arbitrary objects. The renderer itself uses a narrowly validated Queue workaround only. |
| Regional DR / active-standby Cluster Manager | Unsupported upstream | M4 is a one-region multisite indexer design, not regional DR. Cluster Manager resilience is Kubernetes restart recovery, not active/standby management. |
| Workload Management / Indexer Discovery | Unsupported upstream | These capabilities are not supported by the current SOK product boundary. |
| Splunk-to-Splunk receiver service / UF | Handoff | A stable receiver Service is not Indexer Discovery. Configure static/multi-target forwarding with `splunk-universal-forwarder-setup`; SOK does not provide a `splunkforwarder` image path. |
| Forwarding TLS and gateway behavior | Handoff | Web/REST ingress passthrough does not prove Splunk-to-Splunk TLS. Gateway/forwarding certificates, trust, receiver settings, and client validation require a separate PKI/forwarder design. |
| Heavy Forwarder / Deployment Server | Direct-CR handoff | No dedicated CR exists; upstream documents repurposing a Standalone CR. This preset renderer does not validate those roles. Use direct CRs plus `splunk-agent-management-setup` as applicable. |
| Universal Forwarder rollout | Handoff | Use `splunk-universal-forwarder-setup` / `splunk-agent-management-setup`; package deployment and receiver validation are outside SOK install. |
| Day-2 replica scaling | Product-supported handoff | Upstream supports changing CR `replicas` with a patch or `kubectl scale`. This skill owns initial counts and exact status; upgrade preflight rejects live-to-target scaling so a scale operation cannot be hidden inside an upgrade. Scale separately with capacity/health evidence, then render and validate the new baseline. |
| CR reconcile pause/resume | Product-supported handoff / fail closed | Upstream pause annotations stop reconciliation until removed. The strict overlay rejects pause annotations and live gates reject paused CRs. Use only a separately owned break-glass procedure, then remove the annotation and restore health before returning to this workflow. |
| Administrator-managed PVs | Product-supported handoff | Upstream `enterprise.splunk.com/admin-managed-pv: "true"` disables dynamic PV creation and makes PVC templates select pre-created, correctly labelled PVs. This skill does not inventory those labels/bindings or assume their lifecycle; generic annotation passthrough is not first-class authorization for this storage design. |
| New install | First-class | Preflight, reviewed namespace/CRD creation, combined server dry-run, Operator, optional license, Enterprise, and exact status helpers. CRDs must exist before Enterprise resources can be dry-run. |
| Upgrade | First-class safety gate + handoff | `--allow-upgrade` requires healthy CRs/pods/operator and exact ownership; runs Operator dry-run before CRD mutation and Enterprise dry-run after CRD apply but before Helm mutation; rejects downgrade, provenance, storage/topology/reference, and I&I immutable changes. Splunk 10.4+ additionally requires the explicit backup/KV/premium/TLS/release-note attestation. |
| Direct Splunk release-line hops | First-class gate | Same-line, 9.4→10.0/10.2, 10.0→10.2/10.4, and 10.2→10.4 are accepted; other line jumps require an intermediate reviewed upgrade. Exact patch prerequisites remain release-note owned. |
| StatefulSet rollout semantics | First-class live contract + product constraint | Splunk StatefulSets use the Operator's controlled/OnDelete and Parallel lifecycle; generic `kubectl rollout status statefulset` is not readiness evidence. The skill checks exact CR-owned StatefulSet and pod inventory, revisions, readiness, availability, images, probes, security, storage, Services, and EndpointSlices instead. |
| PVC expansion/storage migration | Handoff | Existing claims, StorageClass expansion support, filesystem resize, and migration/recovery are not mutated by this skill. |
| Downgrade | Unsupported upstream | SOK does not support Operator downgrade. |
| Uninstall/PVC deletion | Handoff | No automated destructive path. Review finalizers, PVC retention, SmartStore durability, and backups manually. |
| Backup/restore/DR | Handoff | No backup or restore implementation. Prove license, KV Store/knowledge, app source, index, and object-store recovery separately. |
| Bundle integrity | First-class accidental-drift control | Manifest records every tracked file's SHA-256 and reviewed mode; verifier enforces current-user ownership, exact mode, no-follow regular/single-link reads, strict bundle-root mode, staged snapshots, and helper allowlists. It is not provenance/signing; retain external attestations. |
| Static validation | First-class | Shell syntax, chart pull/lint/template, RBAC mode, kinds/counts/replicas, production QoS/SmartStore/zones, I&I identity/refs, and owner/mode/hash bundle integrity. Strict mode requires Helm. |
| Live validation | First-class platform checks | Compatibility/RBAC/reference/upgrade preflight, exact Helm/CRD/CR/Operator object contracts, CR→StatefulSet→pod ownership/runtime, probe and feature ConfigMap contents, PVCs, Splunk Services/EndpointSlices, CR/pod health, production node placement, M4 zones, and events. SmartStore Secret values are compared only in private temporary storage/in memory and are never emitted. Does not prove ingest/search/app outcomes or search continuity during a zone failure. |

## SOK App Framework Scope Matrix

| Custom resource | local | cluster | premium apps | Skill ownership |
|---|---:|---:|---:|---|
| Standalone | Yes | No | ES only in supported S1/C1 contexts | Overlay + security handoff |
| ClusterManager | Yes | Yes | No; use cluster scope for ES indexer content | Overlay; cluster is the indexer distribution path |
| SearchHeadCluster | Yes | Yes | ES in C3/C13, not M4/M14 | Overlay + security handoff |
| LicenseManager | Yes | No | No | Overlay |
| MonitoringConsole | Yes | No | No | Overlay |
| IngestorCluster | Yes | No | No | Overlay |
| IndexerCluster | No direct App Framework | No direct App Framework | No | Use ClusterManager cluster scope |

App Framework limitations remain in force:

- archives must be `.spl`, `.tgz`, or `.tar.gz`;
- the administrator must inspect, version-check, and enable packages;
- removing an already installed app is not supported;
- package downgrade is not supported;
- a different archive filename for the same internal app is not a safe update
  strategy;
- object-store access should be least-privilege and TLS 1.2 or later; Azure
  shared-key `secretRef` is a documented broader read/write exception whose
  custody and rotation must be explicitly accepted.

Source: <https://splunk.github.io/splunk-operator/AppFramework.html>

## Splunk POD 10.4 Coverage

| Capability | Status | Current coverage and boundary |
|---|---|---|
| Coupled bundle `10.4.0_1.6.0` | First-class | The installer binary is copied to a private `0500` bundle snapshot; its independently reviewed SHA-256 and exact `-version` output must match metadata. Independent component versions are rejected. |
| Other POD bundle versions | Constrained unverified override | This implementation has a hard floor of `10.2.1_1.5.0` because it always uses the preflight-only command introduced there. `--allow-unverified-versions` permits a reviewed newer/unlisted coupled bundle after release/compatibility review; it never bypasses feature-introduction gates or establishes support. |
| EIST-574 CoreDNS known issue | Handoff | Bounded readiness exposes the failure. The release-note recovery sequence first retries `-deploy`, then uses destructive `-destroy`/`-deploy` if needed. After a partial/existing deployment, this skill automates neither path; use a reviewed manual/vendor handoff and assess data impact first. |
| Small/Medium/Large/X-Large | First-class | Exact controller/worker counts and role comments. |
| ES variants | First-class package/provenance mapping | Adds the supported secondary standalone/SHC, requires two physically distinct Enterprise/ES `.lic` files and matching internal ES/`Splunk_TA_ForIndexers` roots at `8.3.0`, `8.4.1`, or `8.5.1` for Enterprise 10.4, then hands post-install work to the ES skills. |
| ITSI variants | First-class package/provenance mapping | Adds the secondary tier; verifies ITSI 4.21.2 source and JDK archive against reviewed SHA-256 values, exact app inventory/content, OpenJDK 17 x86-64 structure, tier placement, and licenses. Post-install work belongs to `splunk-itsi-setup` / `splunk-itsi-config`. |
| Cisco UCS hardware deployment | Handoff | Cisco Intersight, UCS profiles, Nexus, firmware/drivers, RAID, racks, cabling, and RHEL build are not automated. |
| Static node blueprint | First-class | Exactly three controllers; profile-specific workers; valid unique IPs with no overlap. |
| Pod scheduling and resiliency placement | Product-managed + placement evidence | POD uses soft placement: protected indexer, search-head, and SeaweedFS volume pods prefer separation from peers of the same type, management pods may co-locate, and constraints may fall back during hardware replacement or mount/device shortages. The static profile is not proof of achieved failure-domain separation; capture live worker/pod placement and review it against the hardware and failure model. |
| POD SOK pod compute allocations | Product-managed + external capacity evidence | POD allocates/limits each indexer pod at 36 CPU/96 GB and each search-head pod at 24 CPU/96 GB. Prove node allocatable capacity plus system/failure headroom; the renderer does not attest it. |
| X-Large two-rack placement | External evidence | Two racks/four switches and complete cross-rack reachability are required; worker comments/counts do not prove placement, cabling, or failure domains. |
| Immutable search-tier names | First-class | Explicit primary and secondary names required before live preflight/apply. |
| Generic optional second search tier | Handoff | POD supports a second standalone/SHC without ES/ITSI, but this selector model does not render its identity, worker count, or app scopes. Use the official installer config with vendor review. |
| Secondary-tier generic local/cluster apps | Handoff | ES/ITSI selectors map only their documented package scopes; additional secondary-tier generic apps require a reviewed installer-config handoff. |
| Sole ES/ITSI premium search tier | Unsupported by this renderer | Every `-es`/`-itsi` selector retains a primary core tier and adds the premium tier second. A sole premium tier requires a manual/vendor installer-config handoff. |
| SSH key and local paths | First-class | No-follow regular-file checks, owner/private mode, `ssh-keygen` parsing, and minimum RSA strength; each live helper stages private snapshots before use. |
| Multiple license files | First-class | Comma-separated `.lic` paths; ES/ITSI live profiles require at least two physically distinct Enterprise and premium-product files (duplicate inodes are rejected). |
| App files `.spl`/`.tgz`/`.tar.gz` | First-class guarded inputs | Validates safe tar structure, one internal root per file/scope, duplicate roots, package IDs, size/member limits, and external-file hashes. Product compatibility and configuration still need owner validation. |
| External-input staging | First-class | Every live helper revalidates and copies app/license/key/certificate inputs into a private temporary snapshot, rewrites staged paths, and cleans it afterward. Source ownership/provenance remains external. |
| ClusterManager cluster/local app scopes | First-class | Indexer distribution and ClusterManager-local packages. |
| Primary SHC cluster/deployer-local scopes | First-class | Medium/Large/X-Large. |
| Primary standalone local scope | First-class | Small. |
| ES premium scope | First-class | ES only; indexer-side `Splunk_TA_ForIndexers` is required by the live gate. |
| ITSI search/indexer/LicenseManager mapping | First-class validation, 10.4+ | Exact POD 10.4 inventory and canonical content equality are enforced; `SA-ITSI-Licensechecker` remains LicenseManager-only. License Manager app input is rejected before `10.4.0_1.6.0`. |
| Internal SeaweedFS SmartStore/App Framework | Product-managed + infrastructure evidence | No external provider flags; SOK SmartStore options are rejected. The design uses three managers, at least three filers, one volume per volume worker, and three replicas/two-volume-node tolerance; the renderer does not prove runtime placement/quorum/replication. |
| Retention/cache profile | Product-managed + evidence | Small/Medium/Large: 90-day local cache and one-year SmartStore retention. X-Large: 60-day cache and 180-day retention. Prove observed policy and capacity; do not generalize one-year retention to X-Large. |
| Custom indexes | Handoff through app package + conflict gate | Deliver `indexes.conf` through ClusterManager cluster scope. The linter requires home/cold/thawed paths and rejects POD-owned `repFactor`/`remotePath`. Manage says POD injects one-year frozen retention, while architecture says X-Large is 180 days; require X-Large effective-setting readback and Splunk clarification. |
| Knowledge objects | Product-managed + backup handoff | Installer protects local changes from overwrite but does not provide external backup of every knowledge object. Prove backup/recovery separately. |
| IP-based routing | First-class product default | No certificate flags required. Network reachability remains external. |
| Product-default ingress certificates | Product-managed | Cert Manager renews default certificates on the documented 90-day lifecycle. Validate health; do not replace that claim with custom-certificate ownership. |
| Name-based routing | First-class assertion + product routing, 10.4+ | `--ingress-domain` can be used without custom material on `10.4.0_1.6.0` or later; POD's product certificate works but can produce browser trust warnings. DNS/reachability remain external. Named routes include management APIs on 8089 plus deployer/Prometheus/Perses routes. |
| Custom trusted TLS | First-class crypto gate + handoff | Optional; when selected it requires domain, certificate, private key, and CA bundle. Validates wildcard SAN/hostname, serverAuth/KeyUsage/CA:FALSE, key match/strength, signatures, chain, and >=30-day validity. Issuance/trust/renewal/redeployment remain external. |
| HEC | Handoff | Product exposes TLS HEC; use `splunk-hec-service-setup` plus data-source validation for token, source/index, and load balancing. |
| Splunk-to-Splunk/Universal Forwarder | Handoff | Use `splunk-universal-forwarder-setup` / `splunk-agent-management-setup`; UF 9.4.1+ requires `forcedTimeBasedAutoLB=true` for POD's multi-worker receiver path. |
| Monitoring Console | Product-managed + handoff | Access is product-managed; use `splunk-monitoring-console-setup` for application-level evidence. |
| Prometheus and Perses | Product-managed | POD supplies the monitoring components/routes; this skill does not configure dashboards, retention, alerts, or monitoring outcomes. |
| Splunk Agent Management | Handoff | Agent/forwarder enrollment and policy are separate from POD deployment; use `splunk-agent-management-setup`. |
| Offline OCI payload | Product-managed + handoff | The coupled installer carries its supported image payload. This skill snapshots/verifies the installer but does not independently attest every embedded OCI image or mirror lifecycle. |
| Standard-mode Federated Search | Handoff | Product-supported with POD routing constraints; use `splunk-federated-search-setup`. |
| Transparent Federated Search | Unsupported for POD | Do not claim support. |
| Installer preflight | First-class | Version match plus native static config, file, host, SSH/sudo, OS, time, firewall, and storage checks. |
| Worker/pod readiness | First-class | Bounded polling through `wait-ready.sh`; timeout is configurable by environment variables. Every pod-table row containing a readiness fraction must parse, and punctuation-bearing failure states such as `Init:0/1` fail closed. |
| Verbose pod status | Unsupported / evidence-gated handoff | The official 10.4 POD guide documents `-status` and `-status.workers`, but not `-status.verbose`; the skill does not generate or claim that undocumented invocation. Use only installer-help evidence and a separately reviewed diagnostic handoff. |
| Credential retrieval | First-class sensitive helper | `get-creds.sh`; never capture output in tickets or committed logs. |
| Local installer docs | First-class | `web-docs.sh` uses documented `--web --web.port`. |
| Logs and diag | First-class sensitive helper + manual paths | `diagnostics.sh` runs bounded `-get.logs` and `-get.diag` calls in a separate private temporary directory so mutable outputs do not contaminate the reviewed bundle. Installer audit logs, pod Ansible logs, SOK controller logs, and documented SSH, registry, scheduling, and licensing investigations remain read-only/manual troubleshooting handoffs. |
| Installer kubectl shell | Handoff | Use the documented `-kubectl` command manually; no generated helper currently exists. |
| New install | First-class with attestation | Reviewed static config, native preflight, one-time `--confirm-new-pod-install`, fail-closed status probe, deploy, and readiness wait. Official docs do not define machine-readable no-cluster status semantics. |
| Lockstep upgrade | Manual/vendor handoff | A bundle rendered with `--allow-upgrade` preflights artifacts but `deploy.sh` intentionally refuses mutation because the installer exposes no documented machine-readable topology/version identity. |
| Day-2 app add/update reconciliation | Manual/vendor handoff | Official workflow edits config and reruns `-deploy`; automated reconciliation is intentionally disabled for existing clusters. |
| License renewal | Manual/vendor handoff | New license files, config update, validation, and reconciliation follow the official manage workflow; no automatic renewal helper is exposed. |
| Independent SOK/Splunk/Kubernetes upgrade | Unsupported by POD | Components are coupled in the installer bundle. |
| App removal/downgrade | Unsupported by POD App Framework | Do not promise removal or downgrade automation. |
| Destroy | Unsupported by this skill | Installer `-destroy` permanently removes cluster components and data; no helper is rendered. |
| Backup/restore/DR | Handoff | No automated backup/restore workflow. |
| Bundle integrity | First-class accidental-drift control | POD uses the same current-user owner, recorded-mode, SHA-256, no-follow/single-link verifier, strict bundle root, installer snapshot, and private external-input staging. The manifest is not a signature or adversarial supply-chain proof. |
| Static validation | First-class | Rendered/external hashes, shell/Python syntax, profile/address/name checks, exact installer versions, safe package structure/inventory/provenance, and TLS cryptography/trust. |
| Live validation | First-class platform checks | Native installer preflight followed by bounded worker/pod status polling. Does not prove search, ingestion, ES, ITSI, DNS, or external backup. |

## POD Profile Matrix

| Selector | Base profile written | Controllers | Workers | Secondary search tier |
|---|---|---:|---:|---|
| `pod-small` | `pod-small` | 3 | 8 | none |
| `pod-small-es` | `pod-small` | 3 | 9 | one ES standalone |
| `pod-small-itsi` | `pod-small` | 3 | 9 | one ITSI standalone |
| `pod-medium` | `pod-medium` | 3 | 11 | none |
| `pod-medium-es` | `pod-medium` | 3 | 14 | one three-member ES SHC |
| `pod-medium-itsi` | `pod-medium` | 3 | 14 | one three-member ITSI SHC |
| `pod-large` | `pod-large` | 3 | 15 | none |
| `pod-large-es` | `pod-large` | 3 | 18 | one three-member ES SHC |
| `pod-large-itsi` | `pod-large` | 3 | 18 | one three-member ITSI SHC |
| `pod-xlarge` | `pod-xlarge` | 3 | 30 | none |
| `pod-xlarge-es` | `pod-xlarge` | 3 | 33 | one three-member ES SHC |
| `pod-xlarge-itsi` | `pod-xlarge` | 3 | 33 | one three-member ITSI SHC |

## External Evidence Required for Production

Regardless of target, a production handoff should include:

- exact product, chart, image, installer, and Kubernetes versions;
- rendered bundle hash and validation result;
- kubecontext/cluster identity or POD node inventory;
- sizing and storage latency/throughput evidence;
- failure-domain, disruption, and capacity review;
- license ownership and expiry plan;
- workload identity/Secret ownership without secret values;
- object-store/queue encryption, retention, lifecycle, and recovery;
- DNS, TLS, ingress/load-balancer, firewall, and egress evidence;
- backup and restoration evidence;
- post-deploy search, ingestion, monitoring, and app validation;
- rollback or supported recovery plan and named owners.

## Official Sources

### SOK

- Release matrix: <https://github.com/splunk/splunk-operator/releases/tag/3.1.0>
- Getting started/platform evidence: <https://splunk.github.io/splunk-operator/GettingStarted.html>
- Install modes: <https://splunk.github.io/splunk-operator/Install.html>
- Release change log/events: <https://splunk.github.io/splunk-operator/ChangeLog.html>
- Applied SVA scope: <https://help.splunk.com/en/splunk-enterprise/get-started/splunk-validated-architectures/applied-svas/splunk-operator-for-kubernetes>
- Multisite indexer and search-head examples: <https://splunk.github.io/splunk-operator/MultisiteExamples.html>
- Helm: <https://splunk.github.io/splunk-operator/Helm.html>
- Custom resources: <https://splunk.github.io/splunk-operator/CustomResources.html>
- App Framework: <https://splunk.github.io/splunk-operator/AppFramework.html>
- SOK 3.1 CRD schema: <https://github.com/splunk/splunk-operator/blob/3.1.0/config/crd/bases/enterprise.splunk.com_standalones.yaml>
- Premium apps: <https://splunk.github.io/splunk-operator/PremiumApps.html>
- Indexing and ingestion separation: <https://splunk.github.io/splunk-operator/IndexIngestionSeparation.html>
- SmartStore: <https://splunk.github.io/splunk-operator/SmartStore.html>
- Storage classes: <https://splunk.github.io/splunk-operator/StorageClass.html>
- Passwords and AWS IRSA: <https://splunk.github.io/splunk-operator/PasswordManagement.html>
- Product telemetry: <https://splunk.github.io/splunk-operator/Telemetry.html>
- Kubernetes support-data collectors: <https://splunk.github.io/splunk-operator/K8SCollectors.html>
- AWS IRSA admission webhook: <https://github.com/aws/amazon-eks-pod-identity-webhook>
- Security: <https://splunk.github.io/splunk-operator/Security.html>
- Ingress: <https://splunk.github.io/splunk-operator/Ingress.html>
- External License Manager/indexer examples: <https://splunk.github.io/splunk-operator/Examples.html>
- Legacy CR terminology transition: <https://splunk.github.io/splunk-operator/BiasLanguageMigration.html>
- Upgrades: <https://splunk.github.io/splunk-operator/SplunkOperatorUpgrade.html>
- Validation webhook: <https://splunk.github.io/splunk-operator/ValidationWebhook.html>

### Splunk POD

- Release notes: <https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.4/splunk-pod-release-notes>
- Architecture: <https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.4/splunk-pod-architecture>
- Requirements: <https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.4/splunk-pod-requirements>
- Deploy: <https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.4/deploy-splunk-pod>
- Manage: <https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.4/manage-splunk-pod>
- Network and ingress: <https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.4/network-routing-and-ingress-for-splunk-pod>
- Upgrade: <https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.4/upgrade-splunk-pod>
- Troubleshoot: <https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.4/troubleshoot-splunk-pod>
- Cisco CVD: <https://www.cisco.com/c/en/us/td/docs/unified_computing/ucs/UCS_CVDs/cisco_ucs_splunk_pod.html>
