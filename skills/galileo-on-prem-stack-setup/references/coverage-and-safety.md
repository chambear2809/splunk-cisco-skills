# Coverage and Safety Review

## Installation Methods

The official guide defines four methods: galileoctl, umbrella Helm CLI,
deployment script, and step-by-step charts. galileoctl can
install the platform umbrella chart as well as validate/operate it. This skill
recognizes all four methods and inspects pinned Method A/B chart artifacts; it
performs none of them. Method C remains an unresolved handoff until its exact
script/config artifacts are hashed and statically reviewed. Method D remains
unresolved until its ordered chart/release/dependency inventory is supplied.
For first install, use the galileoctl UI as the method table
requires; use the CLI workstation/CI alternative only with exact current
release and Galileo/CSE authorization. Never assign two methods ownership of
the same release or call the raw Helm path vendor-recommended.

## Chart-Derived Coverage

Review every chart dependency and every runtime kind, image, CRD, hook,
cluster-scoped kind, PVC and route. Classification is exact and version-bound;
the official "31 subcharts" statement is not a substitute for inspecting the
entitled archive.

Review schema/enable/config switches from every nested `values*.yaml` and
`values.schema.json`. All recursively unpacked template and helper files are
scanned, and the handoff renderer rejects Helm `lookup` because it makes the
operator-session render depend on unbound live cluster state.

Classify normal containers, init containers, hook jobs and test pods. For
air-gapped use, require digest-bound mirrors for all of them, including the
sequencing kubectl image. Reject mutable `latest` references.
Bootstrap air-gap evidence with a read-only connected preflight whose chart,
non-secret values, non-verifying runtime Secret path/influence contracts,
target, canonical redacted render inventory, and image rows
are the exact intended final inputs. The final air-gap-enabled preflight must
equal the embedded `stack_seed` and exact `stack_images`; aggregate air-gap
images may additionally contain standalone Agent Control/Luna child evidence.

## CRDs

There are three independent CRD paths:

1. Helm's `crds/` directory;
2. operator subchart templates; and
3. the sequencing CRD-management hook.

Shared ownership disables all three and compares normalized packaged/installed
schemas. Dedicated ownership inventories the exact values-aware CRD set,
ordering, schemas, and cluster scope for a Galileo/CSE handoff. This skill never
installs, changes, waits on, or deletes a CRD.

## Storage and Data

Review each rendered PVC, StatefulSet claim template, and declared
operator-created volume against an explicit StorageClass. This release records
expected claim names/shapes only. Exact live controller UID, retained VCT,
release-ownership, PV claimRef/UID, and extra-claim provenance are not proven by
the active preflight; `persistent_claim_provenance_incomplete` remains open.
Production requires safe retention, expansion, snapshots and successful
restore evidence. Snapshot-capability evidence must be current; restore-drill
evidence uses its separate CSE-reviewed maximum age. Data-service backup
evidence must satisfy its daily/frequency policy, while restore evidence uses
the independently reviewed drill interval. All references and RFC3339 times
must be explicit. `Delete`
reclaim is blocked unless a named, action-specific
exception is approved; the skill itself never removes data.

Production PostgreSQL may be external HA or CSE-reviewed self-hosted HA with
daily backup and restore evidence. PostgreSQL, ClickHouse, and object-store
backup/restore references, the object-store backup bucket identifier, and a
fresh observation time are mandatory. Managed/external HA Redis is preferred;
in-cluster Redis requires a written Galileo support exception because it is not
officially supported. Core object storage may use S3, GCS, S3-compatible
storage, or retained in-cluster MinIO with non-default secrets and backup
evidence. The umbrella and Azure guides conflict on Azure Blob core support;
reject it by default, but represent an explicitly Galileo/CSE-approved
resolution as `external-azure-blob-exception` with written support evidence.
Never create or purge
object-store buckets, external databases, or RabbitMQ queues here.

## Routing and TLS

Review API, console, Grafana and optional service routes, including the
version-matched required `/api/galileo`, `/ingest-service`, and
`/otel/v1/traces` contracts. Observe DNS and certificate metadata without
disabling TLS verification. Exact backend/pathType semantics, metrics denial,
certificate-key-chain-handshake proof, CORS, and NextAuth alignment remain
explicit CSE handoff gates unless supplied by a version-matched contract.

For production preflight and the operator handoff, bind every prerequisite
controller/LoadBalancer Service by exact namespace, name, UID, and address set.
A release-managed LoadBalancer needs a staged manual handoff; an unrelated
same-name Service in another namespace never satisfies evidence.

## Wizard and GPU

CPU-only mode must render no `nvidia.com/gpu` request. GPU inventory observes
allocatable capacity and reviewed ML placement intent only. It does not prove
NVIDIA device-plugin DaemonSet/pod readiness, free schedulable capacity, exact
Wizard workload binding, or an inference smoke test; those remain explicit
machine-readable handoff gates. A GPU request is optional under Kubernetes
extended-resource semantics, but when present it must equal the limit. Require
an externally verified offline-model artifact/checksum contract when
disconnected. Static validation is never live GPU evidence.

## Monitoring

When enabled, declare every expected Prometheus, Grafana, Fluent Bit,
Prometheus Adapter, kube-state-metrics, Alertmanager, and explicitly selected
VictoriaLogs component. Bind exact workload, Service, rule/dashboard/storage,
and other resource kind/name identities plus persistence intent. A bare
monitoring boolean or an undeclared recognized component fails preflight.

## galileoctl

Review the in-cluster console as a separate pinned-release handoff. Its UI/CLI
can then drive official Method A for platform installation. Default the console to port-forward-only,
authentication enabled, namespace-scoped RBAC, no sample credentials, and no
management roles. Any Secret-read, pod-exec, cluster role, public route, or
temporary management-role capability needs explicit review and acceptance.
Persist its audit trail when required and gate/redact support-bundle creation.

## Uninstall

Inventory release hooks and data resources for the manual uninstall handoff.
Automated uninstall is disabled. galileoctl installation is a nonmutating handoff in this
skill; it is never a second automated Helm mutation. Never mutate unrelated namespace PVCs; leave namespace,
PVCs, PVs, CRDs, buckets, and databases intact.
