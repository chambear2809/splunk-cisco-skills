---
name: splunk-enterprise-kubernetes-setup
description: >-
  Render, preflight, apply, and validate Splunk Enterprise on Kubernetes using
  either the generic Splunk Operator for Kubernetes Helm workflow or Splunk POD
  on Cisco UCS with the Splunk Kubernetes Installer. Use when the user asks to
  deploy Splunk Enterprise on Kubernetes, run SOK, build S1/C3/M4 on a cluster,
  or prepare Splunk POD cluster-config.yaml and installer commands.
---

# Splunk Enterprise Kubernetes Setup

This skill covers two Kubernetes deployment paths for full Splunk Enterprise:

1. **Splunk Operator for Kubernetes (`sok`)** on an existing Kubernetes cluster.
   The workflow renders CRD, operator Helm, and Splunk Enterprise Helm assets
   for S1, C3, or M4.
2. **Splunk POD (`pod`)** on Cisco UCS using the Splunk Kubernetes Installer.
   The workflow renders `cluster-config.yaml` and installer helper commands for
   POD sizing profiles.

The default behavior is render-only. Apply phases run only when the user asks
for `--phase apply`, `--phase all`, or adds `--apply` to a render run.

## Agent Behavior - Credentials

Never ask for passwords, HEC tokens, SSH private keys, SmartStore access keys,
or license contents in chat.

- Use `template.example` for non-secret planning values such as namespaces,
  release names, profiles, IP addresses, storage class, AWS region, and app
  package paths.
- Store secret values in local-only files or existing Kubernetes secrets.
- Pass file paths or secret names only:
  - `--license-file /path/to/splunk.lic`
  - `--ssh-private-key-file /path/to/key`
  - `--smartstore-secret-ref splunk-smartstore-s3`
- Do not render completed assets containing secrets outside the gitignored
  `./splunk-enterprise-k8s-rendered/` directory unless the user explicitly
  chooses an external path.

For Splunk Enterprise 10.x container images, the SOK path requires explicit
acceptance of the Splunk General Terms:

```bash
bash skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh \
  --target sok \
  --architecture c3 \
  --accept-splunk-general-terms
```

## SOK Workflow

Render reviewable SOK assets:

```bash
bash skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh \
  --target sok \
  --architecture c3 \
  --namespace splunk \
  --operator-namespace splunk-operator \
  --storage-class gp3 \
  --accept-splunk-general-terms
```

Render M4 with SmartStore references:

```bash
bash skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh \
  --target sok \
  --architecture m4 \
  --site-count 3 \
  --site-zones us-west-2a,us-west-2b,us-west-2c \
  --indexer-replicas 3 \
  --smartstore-bucket my-splunk-smartstore \
  --smartstore-region us-west-2 \
  --smartstore-secret-ref splunk-smartstore-s3 \
  --accept-splunk-general-terms
```

For M4, `--indexer-replicas` means indexers per site. Provide one
`--site-zones` value per site using the Kubernetes zone label values for the
cluster, such as `topology.kubernetes.io/zone` values on EKS. If
`--site-zones` is omitted, no zone affinity is rendered.
The renderer enforces clustered SOK minimums for C3 indexers and C3/M4 search
heads before writing assets.

Apply after review:

```bash
bash skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh \
  --target sok \
  --architecture c3 \
  --phase apply \
  --accept-splunk-general-terms
```

The rendered SOK directory includes:

- `crds-install.sh`
- `operator-values.yaml`
- `enterprise-values.yaml`
- `helm-install-operator.sh`
- `helm-install-enterprise.sh`
- optional `eks-update-kubeconfig.sh`
- optional `create-license-configmap.sh`
- `status.sh`

## POD Workflow

Render a POD cluster configuration:

```bash
bash skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh \
  --target pod \
  --pod-profile pod-medium \
  --controller-ips 10.10.10.1,10.10.10.2,10.10.10.3 \
  --worker-ips 10.10.10.4,10.10.10.5,10.10.10.6,10.10.10.7,10.10.10.8,10.10.10.9,10.10.10.10,10.10.10.11,10.10.10.12,10.10.10.13,10.10.10.14 \
  --license-file /path/to/splunk.lic \
  --ssh-private-key-file /path/to/ssh-private-key
```

Render-only POD output can contain placeholder paths and IPs for review. Any
`preflight`, `apply`, or `all` run through `setup.sh` requires concrete
controller IPs, worker IPs, a license file, and a non-placeholder SSH key file.

```bash
bash skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh \
  --target pod \
  --pod-profile pod-medium \
  --phase preflight \
  --controller-ips 10.10.10.1,10.10.10.2,10.10.10.3 \
  --worker-ips 10.10.10.4,10.10.10.5,10.10.10.6,10.10.10.7,10.10.10.8,10.10.10.9,10.10.10.10,10.10.10.11,10.10.10.12,10.10.10.13,10.10.10.14 \
  --license-file /path/to/splunk.lic \
  --ssh-private-key-file /path/to/ssh-private-key
```

```bash
bash skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh \
  --target pod \
  --pod-profile pod-medium \
  --phase apply \
  --controller-ips 10.10.10.1,10.10.10.2,10.10.10.3 \
  --worker-ips 10.10.10.4,10.10.10.5,10.10.10.6,10.10.10.7,10.10.10.8,10.10.10.9,10.10.10.10,10.10.10.11,10.10.10.12,10.10.10.13,10.10.10.14 \
  --license-file /path/to/splunk.lic \
  --ssh-private-key-file /path/to/ssh-private-key
```

The rendered POD directory includes:

- `cluster-config.yaml`
- `preflight.sh`
- `deploy.sh`
- `status-workers.sh`
- `status.sh`
- `get-creds.sh`
- `web-docs.sh`

For `pod-small-es`, `pod-medium-es`, and `pod-large-es`, the ES suffix is a setup
alias only. The rendered static cluster configuration keeps the official Splunk
POD profile name and adds the recommended premium app stanzas for Enterprise
Security.

## Validation

Static rendered-asset validation:

```bash
bash skills/splunk-enterprise-kubernetes-setup/scripts/validate.sh --target sok
```

When Helm is installed locally, SOK validation also runs `helm template` for
the pinned operator and Enterprise chart versions using the rendered values.

Live status validation:

```bash
bash skills/splunk-enterprise-kubernetes-setup/scripts/validate.sh --target pod --live
```

## References

- [reference.md](reference.md) for version defaults, architecture notes, and
  command details
- [template.example](template.example) for non-secret intake values
