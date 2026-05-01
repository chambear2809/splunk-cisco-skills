# Splunk Enterprise Kubernetes Reference

This skill renders assets for Splunk Enterprise on Kubernetes. It does not
attempt to hide the generated commands; review the rendered directory before
running an apply phase.

## Current Defaults

| Item | Default |
|------|---------|
| Splunk Operator for Kubernetes | `3.1.0` |
| Splunk Helm chart version | follows `--operator-version` |
| Splunk Enterprise image | `splunk/splunk:10.2.0` |
| Kubernetes compatibility from SOK 3.1.0 notes | `1.27` through `1.33` |
| Render directory | `./splunk-enterprise-k8s-rendered/` |

Override these with `--operator-version`, `--chart-version`,
`--splunk-version`, and `--splunk-image` when your platform standard requires a
pinned build.

## Splunk Operator Path

The SOK path follows the upstream Helm workflow:

1. Apply CRDs separately because they are no longer shipped inside the operator
   chart.
2. Install or upgrade `splunk/splunk-operator`.
3. Install or upgrade `splunk/splunk-enterprise` with `splunk-operator.enabled`
   disabled because the operator was already installed explicitly.

Rendered SOK helpers:

| File | Purpose |
|------|---------|
| `preflight.sh` | Verifies local `kubectl`, `helm`, and optional `aws` access |
| `crds-install.sh` | Applies the versioned SOK CRD bundle with server-side apply |
| `helm-install-operator.sh` | Adds the Helm repo and installs/upgrades the operator |
| `helm-install-enterprise.sh` | Installs/upgrades the Enterprise release |
| `status.sh` | Shows Helm releases, pods, and Splunk custom resources |
| `eks-update-kubeconfig.sh` | Optional helper when `--eks-cluster-name` is supplied |
| `create-license-configmap.sh` | Optional helper when `--license-file` is supplied |

The Helm install helpers pin both `splunk/splunk-operator` and
`splunk/splunk-enterprise` with `--version`. The validator runs
`helm template` against both charts when Helm is available locally, so chart or
values drift is caught before an apply phase.

SOK 3.x and Splunk Enterprise 10.x require the Splunk General Terms
acknowledgement value:

```text
--accept-sgt-current-at-splunk-com
```

The setup script refuses to render SOK assets for 10.x images unless
`--accept-splunk-general-terms` is present.

## SVA Architectures

The SOK Enterprise chart includes Splunk Validated Architecture switches for:

- `s1` - Single Server Deployment
- `c3` - Distributed Clustered Deployment plus SHC, single site
- `m4` - Distributed Clustered Deployment plus stretched SHC, multi-site

The renderer sets the chart SVA switch and also renders the role blocks that
operators normally tune before production use: storage, resources, replica
counts, license URL, and SmartStore references.

For clustered SOK deployments, the renderer enforces at least three C3 indexers
and at least three C3/M4 search heads. M4 indexer replicas are still per site,
because each M4 site is rendered as a separate `IndexerCluster`.

For M4, `--indexer-replicas` is the replica count for each site-specific
`IndexerCluster`, matching the SOK multisite pattern of one IndexerCluster
resource per site. Total indexers are `--indexer-replicas * --site-count`.
Use `--site-zones` to provide one Kubernetes zone label value per site; do not
reuse the AWS region name as a zone value. When `--site-zones` is omitted, the
renderer omits zone fields entirely so the chart does not create required node
affinity for placeholder zones. The M4 search head cluster is rendered with
`site0` and no Kubernetes zone pinning unless an explicit search head zone is
added manually before apply.

## SmartStore

SmartStore rendering references existing Kubernetes secret names. It never
reads or renders object-store keys.

Example:

```bash
bash skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh \
  --target sok \
  --architecture m4 \
  --smartstore-bucket splunk-smartstore-prod \
  --smartstore-prefix indexes \
  --smartstore-region us-west-2 \
  --smartstore-secret-ref splunk-smartstore-s3 \
  --accept-splunk-general-terms
```

Create the referenced Kubernetes secret through your normal secret-management
workflow before applying the Enterprise release.

## License Handling

For SOK, `--license-file` renders `create-license-configmap.sh` and values that
mount the license from a ConfigMap path. For S1 this is rendered directly on the
standalone. For C3 and M4, the values deploy a `LicenseManager` and let the chart
wire `licenseManagerRef` into clustered resources. The script references the
license file path but never copies license content into tracked files.

For POD, `--license-file` is rendered as a path in `cluster-config.yaml` because
the installer expects the license to be present on the bastion node. Render-only
POD output may contain placeholder paths and IPs. `setup.sh --phase preflight`,
`--phase apply`, `--phase all`, and `--apply` require concrete controller IPs,
worker IPs, a license file, and a non-placeholder SSH key file before invoking
the installer.

## Splunk POD Path

The POD path renders the static cluster configuration expected by the Splunk
Kubernetes Installer:

```text
kubernetes-installer-standalone -static.cluster cluster-config.yaml -deploy
```

Accepted profile selectors:

- `pod-small`
- `pod-medium`
- `pod-large`
- `pod-small-es`
- `pod-medium-es`
- `pod-large-es`

The ES selectors are setup aliases. The rendered `cluster-config.yaml` keeps the
official Splunk POD profile names (`pod-small`, `pod-medium`, or `pod-large`) and
adds the Enterprise Security premium app stanza recommended by Splunk. `pod-small-es`
uses `standalone[].apps.premium`; `pod-medium-es` and `pod-large-es` use a second
`searchheadcluster[].apps.premium` entry. Override the placeholder ES package path
with `--premium-apps`.

Default rendered node counts follow the Splunk POD sizing profiles:

| Selector | Installer profile | Controllers | Workers |
|----------|-------------------|-------------|---------|
| `pod-small` | `pod-small` | 3 | 8 |
| `pod-small-es` | `pod-small` | 3 | 9 |
| `pod-medium` | `pod-medium` | 3 | 11 |
| `pod-medium-es` | `pod-medium` | 3 | 14 |
| `pod-large` | `pod-large` | 3 | 15 |
| `pod-large-es` | `pod-large` | 3 | 18 |

Rendered POD helpers:

| File | Purpose |
|------|---------|
| `preflight.sh` | Runs installer preflight checks |
| `deploy.sh` | Runs installer deployment |
| `status-workers.sh` | Checks worker node readiness |
| `status.sh` | Checks pod status |
| `get-creds.sh` | Retrieves generated admin and HEC credentials locally |
| `web-docs.sh` | Starts the installer local documentation server on the bastion |

The installer prompts for Terms and Conditions acceptance during the first
deployment and can write `termsConditionsAccepted: true` into
`cluster-config.yaml`. Remove that key before sharing the file.

## Official References

- Splunk Operator Helm installation:
  <https://splunk.github.io/splunk-operator/Helm.html>
- Splunk Operator multisite examples:
  <https://splunk.github.io/splunk-operator/MultisiteExamples.html>
- Splunk Operator change log:
  <https://splunk.github.io/splunk-operator/ChangeLog.html>
- Splunk Validated Architecture guidance for SOK:
  <https://help.splunk.com/en/splunk-cloud-platform/splunk-validated-architectures/applied-svas/splunk-operator-for-kubernetes>
- Splunk POD deployment guide:
  <https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.2/deploy-splunk-pod>
- Splunk POD architecture and ES app management:
  <https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.2/splunk-pod-architecture>
  <https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.2/manage-splunk-pod>
