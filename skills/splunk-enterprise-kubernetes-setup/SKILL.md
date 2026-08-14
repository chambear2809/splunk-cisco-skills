---
name: splunk-enterprise-kubernetes-setup
description: "Use when planning, installing, upgrading, or validating either runtime. Render, preflight, apply, and
  validate Splunk Enterprise on Kubernetes with Splunk Operator for Kubernetes 3.1.0 or Splunk POD
  10.4.0_1.6.0 on Cisco UCS. Covers SOK S1/C3/M4, guarded C3 indexing and ingestion separation, reviewed
  Helm overlays, and POD Small through X-Large with ES, ITSI, and TLS variants."
compatibility: "Splunk Cloud Platform 10.5.2605: not applicable. This self-managed runtime workflow remains on the public Splunk Enterprise or Universal Forwarder 10.4 baseline."
metadata:
  splunk_cloud_10_5: "self-managed-10.4"
  compatibility_verified: "2026-07-02"
---

# Splunk Enterprise Kubernetes Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
+-- Preflight --+ -> +-- Render/review --+ -> +-- Apply/handoff --+ -> +-- Validate evidence --+
```

## When to Activate

- Planning, installing, upgrading, or validating either runtime.
- Preview and review the splunk enterprise kubernetes setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-enterprise-kubernetes-setup/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

Use this skill for customer-managed Splunk Enterprise on Kubernetes. Resolve the
target before rendering:

1. `sok` installs the Splunk Operator and Splunk Enterprise Helm charts on an
   existing Kubernetes cluster.
2. `pod` drives the coupled Splunk POD installer on pre-built Cisco UCS
   infrastructure.

Do not map POD sizes to SVA names. POD requires an explicit `--pod-profile`.
Read [coverage.md](coverage.md) before promising a feature: it distinguishes
first-class flags from reviewed overlays, external handoffs, and unsupported
operations.

## Supported Baselines

- SOK: Operator and charts `3.1.0`, Splunk Enterprise `10.4.1` by default.
  The renderer enforces the current 3.1.0 release matrix. Kubernetes 1.25-1.34
  is supported subject to the Splunk version rules in the official release.
- POD: coupled bundle `10.4.0_1.6.0`. Do not independently select its SOK,
  Kubernetes, or Splunk Enterprise versions. The implementation hard-rejects
  bundles older than `10.2.1_1.5.0` because its native preflight-only command
  is mandatory; name-based routing and License Manager apps require
  `10.4.0_1.6.0` or later.
- Python 3.9+ with PyYAML 6.x, Bash, `kubectl`, and Helm are required for SOK live phases. POD live
  phases require the executable installer on the bastion.

Version truth comes from the official release pages, not a generic latest
Splunk default:

- <https://github.com/splunk/splunk-operator/releases/tag/3.1.0>
- <https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.4/splunk-pod-release-notes>

## Secret and Safety Rules

Never request or place passwords, HEC tokens, private keys, object-store keys,
or license contents in chat, templates, overlays, or command arguments.

- Pass license and private-key paths only. POD private keys must not be readable
  or writable by group or others; use mode `0600` or stricter.
- Reference existing Kubernetes Secrets and, where the verified path permits
  it, service accounts by name. The SOK 3.1 separated-ingestion path in this
  skill is a deliberate exception: it requires Queue Secret authentication and
  rejects workload-identity service accounts because that upstream path has not
  been verified.
- Keep overlays non-secret. Use a secret manager, an explicitly supported
  workload-identity path, or a separately created Kubernetes Secret for
  credentials.
- Treat `get-creds.sh`, POD logs, and diagnostic bundles as sensitive output.
- Confirm the target kubecontext, namespace, release names, storage class,
  object-store path, and upgrade intent before a live phase.
- Never automate POD destruction or SOK downgrade. Those are explicit external
  handoffs.

The default output directory, `./splunk-enterprise-k8s-rendered/`, is ignored by
Git. An external output path is the operator's responsibility.

## Phase Contract

The default phase is `render` and does not contact or mutate a cluster.

- `render` writes a private reviewable bundle and `bundle-manifest.json`. The
  manifest records each tracked file's SHA-256 and mode; live helpers require
  the bundle root and tracked files to remain owned by the current user at the
  reviewed modes. This detects accidental drift and unsafe replacement, but is
  not a cryptographic signature or external provenance attestation.
- `preflight`, `apply`, and `status` operate on an existing bundle and reject
  file drift. They do not rerender it.
- `apply` runs preflight first, but post-apply readiness is a separate `status`
  phase.
- `all` renders, preflights, applies, and waits for status in one command. Use it
  only when every input has already been reviewed.
- `--apply` on a render run applies immediately but does not run the final status
  phase. Prefer the explicit phases for production.
- SOK overlays are the supported customization mechanism. Editing rendered
  files invalidates bundle integrity.
- The POD installer may add `termsConditionsAccepted: true` to
  `cluster-config.yaml`; `deploy.sh` refreshes the bundle hash afterward. Remove
  that field only from a separate copy made for sharing.

Dry-run plans do not render or execute; use `--dry-run --json` for a
machine-readable preview.

## SOK Workflow

Collect the SVA, Kubernetes server version, namespaces/RBAC scope, storage,
license ownership, SmartStore authentication, topology zones, sizing, and
upgrade intent.

For EKS work in this repository, authenticate to the approved AWS account and
role with `duo-sso` before preflight. Never capture the resulting credentials in
the rendered bundle or logs.

Namespace-scoped mode is the default and requires the operator and Enterprise
namespace to be the same. For separate namespaces, use a cluster-scoped operator
and include the Enterprise namespace in `--watch-namespaces`.

A fresh SOK bundle creates an absent namespace explicitly. A healthy Active,
non-terminating namespace may already exist so reviewed SmartStore/Queue/App
Framework Secrets, IRSA ServiceAccounts, image-pull references, or an existing
LicenseManager can be staged; the bundle leaves that namespace's metadata
unchanged. Exact Helm, Operator, and global CR collision checks prevent this
from becoming an existing-deployment adoption path. Use `--allow-upgrade` only
for the exact already-managed Helm releases; its preflight proves release,
Operator, CR, and namespace ownership before mutation. Fresh preflight also
inventories `enterprise.splunk.com` CRDs cluster-wide. No CRDs is the normal
creation path. If any exist, the complete live CRD set and normalized specs must
exactly equal the SHA-verified reviewed 3.1.0 release manifest, every CRD must be
established on reviewed stored versions, and no SOK CR may exist anywhere in
the cluster, except an explicitly reviewed existing LicenseManager identity.
Partial, drifted, extra, unreadable, terminating, or otherwise populated
inventories fail before namespace or CRD mutation. `validate.sh --live` retains
its separate existing-deployment readback mode and is not an apply bypass.
The LicenseManager exception requires an exact v4 API identity, a separate
currently deployed Helm owner release, complete API-server identity, no
deletion/pause/admin-managed-PV state, current generation, and a clean `Ready`
status.
For the remote development path, `apply.sh` downloads the pinned CRD manifest
once into a private staging directory, verifies its SHA-256, and uses that same
staged file for preflight comparison, server-side apply, and the Established
wait. Production uses the hash-verified local CRD snapshot in the reviewed
bundle. Generated Helm inventory helpers detect Helm 3 versus Helm 4 and fail
closed if compatibility discovery or release listing fails.

The chart exposes first-class SVA presets only for S1, C3, and M4. The upstream
CRDs can compose C1/C11, C13, M2/M12, M3/M13, and M14, but this skill does not
claim those direct-CR topologies as rendered presets. D1/D11 is not recommended
by the upstream Applied SVA guidance. Use the explicit handoff in
[coverage.md](coverage.md) instead of relabeling one of the three presets.
The verified chart 3.1.0 M4 preset is exactly two sites because it hardcodes
multisite RF/SF totals of two. Its SHC and deployer are site-affined and pinned
to one selected Kubernetes zone, so this is not a stretched multi-zone search
tier and does not establish search continuity through that zone's failure. M4
with 3-63 sites or custom factors, and SHC `site0`/stretched scheduling, are
direct-CR or specifically reviewed-overlay handoffs, not preset overrides.

Render a development C3 bundle:

```bash
bash skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh \
  --target sok \
  --architecture c3 \
  --kubernetes-version 1.33 \
  --accept-splunk-general-terms
```

For separate namespaces, render cluster-scoped RBAC with
`--operator-scope cluster`, distinct operator/Enterprise namespaces, and the
Enterprise namespace in `--watch-namespaces`.

`--deployment-profile production` is a guardrail, not sizing approval. It
requires reviewed local 3.1 charts/CRDs, digest-pinned images, exact cluster
identity, Guaranteed-QoS role resources, storage, licensing, complete
SmartStore inventory/migration and exclusive-path attestations, and Secret or
reviewed AWS IRSA authentication. IRSA requires the service account, exact role
ARN, token TTL, AWS region, matching annotations, and regional STS; it is scoped
only to S1 Standalone or C3/M4 indexers and is server-dry-run/live validated.
Production M4 also locks its two site/zone placements. Follow the complete
intake and command in [reference.md](reference.md#sok-production-profile) and
[template.example](template.example); capacity, path ownership across clusters,
and zone-failure continuity remain external evidence.

### Advanced SOK Options

C3 indexing/ingestion separation and constrained, non-secret overlays are
advanced fail-closed paths. Read the complete
[separated-ingestion contract](reference.md#sok-indexing-and-ingestion-separation),
[overlay rules](reference.md#sok-overlays), and [coverage boundaries](coverage.md)
before selecting either path.

### Review, Validate, and Apply SOK

```bash
bash skills/splunk-enterprise-kubernetes-setup/scripts/validate.sh \
  --target sok

bash skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh \
  --target sok \
  --phase preflight

bash skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh \
  --target sok \
  --phase apply

bash skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh \
  --target sok \
  --phase status
```

If the reviewed bundle contains `create-license-configmap.sh`, the apply phase
detects and executes it from the bundle; do not repeat render inputs on an
existing-bundle phase. Existing Helm releases fail closed unless the bundle was
rendered with `--allow-upgrade`. Upgrade preflight rejects chart downgrades and
immutable Queue/ObjectStorage/reference changes. An upgrade still requires an
external backup, release-note review, and recovery plan; SOK does not support
downgrade. When the target Splunk release is 10.4 or later, `--allow-upgrade`
also requires `--confirm-splunk-10-4-upgrade-readiness`. That attests a
restorable platform and KV Store backup, a healthy KV Store server at version
7.0 or later, compatible premium apps/add-ons, TLS 1.2 or later, and review of
the target release's upgrade notes. The confirmation flag is invalid without
`--allow-upgrade`.

`server-dry-run.sh` accepts `operator`, `enterprise`, or `all`. Upgrade apply
uses the least-mutating valid order: Operator server dry-run before CRD changes,
then reviewed CRD apply, then Enterprise server dry-run against the resulting
schemas, before either Helm release is mutated. A new install creates the
reviewed namespaces/CRDs first because the Enterprise resources need their
APIs, then runs the combined server dry-run before Helm install.

## Splunk POD Workflow

POD assumes Cisco CVD infrastructure already exists. The installer preflight
does not replace Cisco Intersight, network, RAID, RHEL, DNS, certificate, or
capacity ownership. Review [coverage.md](coverage.md), the current CVD, and the
complete [POD reference](reference.md#pod-104-profiles) before live work.

Select `pod-small`, `pod-medium`, `pod-large`, or `pod-xlarge`, optionally with
the first-class `-es` or `-itsi` suffix. Do not infer capacity, rack resilience,
storage behavior, or retention solely from the rendered node count; retain the
external Cisco/Splunk infrastructure evidence described in
[reference.md](reference.md#pod-cisco-cvd-prerequisites).

A live bundle requires exact unique controller and worker IPs, the reviewed
installer and SHA-256, license and SSH-key files, and immutable search-tier
names. A first deployment also requires `--confirm-new-pod-install`; it is a
narrow attestation for the exact reviewed node set, not permission to overwrite
an existing or partial deployment.

```bash
bash skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh \
  --target pod \
  --pod-profile pod-medium \
  --phase all \
  --pod-version 10.4.0_1.6.0 \
  --confirm-new-pod-install \
  --installer-path /opt/splunk-pod/kubernetes-installer-standalone \
  --installer-sha256 '<independently-reviewed-64-hex-sha256>' \
  --controller-ips "${CONTROLLER_IPS}" \
  --worker-ips "${WORKER_IPS}" \
  --primary-search-name core-shc \
  --license-file /secure/path/splunk.lic \
  --ssh-private-key-file /secure/path/pod-ssh-key
```

App archives, ES/ITSI versions and license separation, app scopes, and optional
customer TLS material are all strict validation gates. Follow the exact
requirements in [reference.md](reference.md#pod-static-configuration-and-app-scopes)
and [reference.md](reference.md#pod-tls-routing-and-access); do not infer package
identity from filenames.

Automated POD upgrade, day-2 app reconciliation, removal, downgrade,
certificate redeployment, and destruction are intentionally disabled. Keep
these as documented Cisco/Splunk operator handoffs. Universal Forwarder rollout
is also separate and must use `splunk-universal-forwarder-setup` or
`splunk-agent-management-setup`. The full fresh-deploy and handoff lifecycle is
in [reference.md](reference.md#pod-rendered-files-and-lifecycle).

## Validation

Static validation checks bundle integrity and shell helpers. SOK additionally
pulls, lints, templates, and semantically checks both pinned charts when Helm is
available; `--strict` requires Helm. POD checks profile, node counts, addresses,
immutable names, and local references. Strict POD validation also runs the
archive, ES/ITSI provenance, and ingress cryptographic gates described above.

```bash
bash skills/splunk-enterprise-kubernetes-setup/scripts/validate.sh \
  --target pod \
  --strict

bash skills/splunk-enterprise-kubernetes-setup/scripts/validate.sh \
  --target sok \
  --live \
  --json
```

Live SOK validation runs compatibility/RBAC/reference preflight and waits on
Splunk custom-resource phases. It also exactly compares the Operator's
Helm-owned Deployment, RBAC, ServiceAccount, staging PVC, and Services with a
fresh server dry-run; validates the expected Splunk child Service inventory and
ready EndpointSlices; and checks StatefulSet/pod placement. Production requires
replicas of each replicated StatefulSet on distinct nodes, while M4 additionally
checks every reviewed pod against its node's expected zone. The preset expects
the SHC/deployer in one zone, so this does not prove search continuity after a
zone failure. Live POD validation
reruns native preflight and then uses the generated bounded readiness loop over
both worker and pod status.
Validation does not prove application-level search, ingest, premium-app setup,
backup quality, DNS propagation, client trust, or external cloud/Cisco
configuration; record those as separate evidence.

Do not confuse operational telemetry with the upstream SOK support-data
collectors. `k8s-splunk-collector.sh` and node-local
`k8s-systeminfo-collector.sh` can capture sensitive cluster, log, system,
diagnostic, and Secret-metadata evidence. They are manual support handoffs:
review privileges, disk space, redaction, retention, archive contents, and the
approved recipient before use. This skill never runs them automatically.

## References

- [reference.md](reference.md), [coverage.md](coverage.md), and [template.example](template.example)
- [operator overlay](operator-values-overlay.example.yaml) and [Enterprise overlay](enterprise-values-overlay.example.yaml)
