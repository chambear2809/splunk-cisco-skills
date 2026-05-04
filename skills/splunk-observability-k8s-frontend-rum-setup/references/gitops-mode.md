# GitOps Mode

`--gitops-mode` is for operators whose Kubernetes deployments flow through
Argo CD, Flux, or any other declarative GitOps controller. In this mode the
renderer emits ONLY YAML manifests; the imperative `apply-injection.sh`,
`uninstall-injection.sh`, and `sourcemap-upload.sh` shell scripts are
omitted so the rendered tree is safe to commit and have a controller apply.

## Usage

```bash
bash skills/splunk-observability-k8s-frontend-rum-setup/scripts/setup.sh \
    --render --gitops-mode \
    --output-dir frontend-rum
```

## What gets rendered

| File | Rendered in --gitops-mode? |
|------|----------------------------|
| `k8s-rum/nginx-rum-configmap-<workload>.yaml` | yes |
| `k8s-rum/nginx-deployment-patch-<workload>.yaml` | yes |
| `k8s-rum/ingress-snippet-patch-<workload>.yaml` | yes |
| `k8s-rum/initcontainer-configmap-<workload>.yaml` | yes |
| `k8s-rum/initcontainer-patch-<workload>.yaml` | yes |
| `k8s-rum/runtime-config-configmap-<workload>.yaml` | yes |
| `k8s-rum/runtime-config-deployment-patch-<workload>.yaml` | yes |
| `k8s-rum/bootstrap-snippet-<workload>.html` | yes |
| `k8s-rum/injection-backup-configmap.yaml` | yes (placeholder; not populated by the controller) |
| `k8s-rum/apply-injection.sh` | **omitted** |
| `k8s-rum/uninstall-injection.sh` | **omitted** |
| `k8s-rum/verify-injection.sh` | yes (read-only; safe in any pipeline) |
| `k8s-rum/status.sh` | yes (read-only) |
| `source-maps/sourcemap-upload.sh` | **omitted** |
| `source-maps/github-actions.yaml` | yes |
| `source-maps/gitlab-ci.yaml` | yes |
| `source-maps/splunk.webpack.js` | yes |
| `runbook.md`, `preflight-report.md`, `metadata.json` | yes |
| `handoff-*.sh` | yes (read-only stubs that just print pointers) |

## Patch vs full deployment

The patch files (`*-deployment-patch-*.yaml`) are **strategic-merge patches**.
They contain only the fields RUM injection needs to add — `spec.template.spec.containers[*].volumeMounts`,
`spec.template.spec.volumes`, `spec.template.spec.initContainers` — not the
full Deployment. Apply with `kubectl apply --type=strategic` or the
GitOps-controller equivalent.

For Argo CD, the recommended pattern is:

1. Keep your application's full Deployment manifest in the GitOps repo.
2. Add a Kustomize overlay (or Helm post-renderer) that strategic-merges the
   rendered patch on top.
3. Sync.

Example Kustomize overlay:

```yaml
# kustomization.yaml
resources:
  - ../base
  - frontend-rum/k8s-rum/nginx-rum-configmap-checkout-web.yaml

patches:
  - path: frontend-rum/k8s-rum/nginx-deployment-patch-checkout-web.yaml
    target:
      kind: Deployment
      name: checkout-web
```

For Flux, use a `Kustomization` resource pointing at the same Kustomize
overlay.

For pure-Helm setups, render with `--gitops-mode` and feed the output through
a Helm post-renderer (`kustomize` again is fine here).

## Backup ConfigMap in GitOps mode

The rendered `injection-backup-configmap.yaml` is a placeholder — it lists
the target workloads but does NOT contain the original Deployment YAML.
That's because GitOps controllers re-apply on every sync, so a "backup"
is always available via `git revert` rather than via a runtime ConfigMap.

To uninstall RUM in a GitOps repo:

1. Remove the `frontend-rum/` directory from your Kustomize / Helm input.
2. Sync. The controller deletes the ConfigMap and reverts the strategic-merge
   patch.
3. Trigger a rollout restart to pick up the reverted Deployment.

## Source maps in GitOps

The `source-maps/sourcemap-upload.sh` helper is omitted because GitOps repos
shouldn't carry runnable shell scripts that hit external APIs. Instead:

- Commit the `source-maps/github-actions.yaml` or `source-maps/gitlab-ci.yaml`
  to your CI pipeline (NOT to the GitOps deploy repo).
- The CI pipeline runs the `splunk-rum sourcemaps inject + upload` commands
  during the build step.
- The GitOps repo gets the deployable artifact (the K8s manifests).

## Validation in GitOps mode

`validate.sh` works the same — pointed at the rendered `--output-dir`. The
static checks pass on the YAML-only tree. The `--live` checks need network
access from wherever you run them; typically that's a separate validation job
in CI rather than the GitOps controller.

## Idempotency

Every rendered manifest is fully declarative — re-applying produces no
change. The renderer hashes the spec into `metadata.json.spec_digest` so
GitOps controllers can detect drift between the spec and what's deployed.
