# GitOps Mode

`--gitops-mode` tells this skill to emit **only self-contained YAML**. The imperative helper scripts (`apply-instrumentation.sh`, `apply-annotations.sh`, `uninstall.sh`) are not rendered; those responsibilities move to the operator's CD tooling (Argo CD, Flux, Rancher Fleet, kustomize-driven CI, etc.).

## What's emitted

```
splunk-observability-k8s-auto-instrumentation-rendered/
  k8s-instrumentation/
    instrumentation-cr.yaml
    obi-daemonset.yaml                # only when --enable-obi
    openshift-scc-obi.yaml            # only when --distribution openshift AND --enable-obi
    namespace-annotations.yaml
    workload-annotations.yaml
    annotation-backup-configmap.yaml  # template only; GitOps system must preserve before changing
    preflight-report.md
    verify-injection.sh               # kept; read-only diagnostic
    status.sh                         # kept; read-only diagnostic
    list-instrumented.sh              # kept; read-only diagnostic
  runbook.md                          # GitOps-tailored runbook
  metadata.json
```

## What's NOT emitted

- `apply-instrumentation.sh` (apply this via your CD system)
- `apply-annotations.sh` (same)
- `uninstall.sh` (same)

## Argo CD pattern

1. Commit `k8s-instrumentation/*.yaml` to a git repo tracked by an Argo CD `Application`.
2. Use `syncPolicy.automated` with `prune: true` so removing a workload annotation from git drives a revert.
3. Add a `syncOptions: [ServerSideApply=true]` so strategic-merge-patch semantics work server-side (important for preserving existing annotations).

Example Application manifest:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: splunk-otel-auto-instrumentation
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/your-org/platform-iac
    path: clusters/prod/auto-instrumentation
    targetRevision: main
  destination:
    server: https://kubernetes.default.svc
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - ServerSideApply=true
    - CreateNamespace=false
```

## Flux pattern

Flux's Kustomization controller also supports `spec.serverSideApply: true` (v1.2+). Commit the same YAML and reference it from a Kustomization:

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: splunk-otel-auto-instrumentation
spec:
  interval: 5m
  path: ./clusters/prod/auto-instrumentation
  prune: true
  serverSideApply: true
  sourceRef:
    kind: GitRepository
    name: platform-iac
```

## Kustomize pattern

If you don't use Argo or Flux, commit the YAML under a `kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
- instrumentation-cr.yaml
- namespace-annotations.yaml
- workload-annotations.yaml
- annotation-backup-configmap.yaml
# - obi-daemonset.yaml                # uncomment when OBI is enabled
# - openshift-scc-obi.yaml            # uncomment when OpenShift + OBI
```

Apply with `kubectl apply -k .` in your CD pipeline.

## Backup ConfigMap in a GitOps world

The backup ConfigMap is still rendered, but the GitOps system applies an empty template. The "write original annotations to the ConfigMap before patching" step that the imperative `apply-annotations.sh` runs is NOT executed.

Alternatives:

1. **Accept that uninstall is best-effort**: the CD system removing the annotations triggers a rollout that strips `inject-*` from pods. Any pre-existing non-inject annotations on the pod template are preserved because strategic merge does not touch them. The backup ConfigMap is not needed for correctness in this case.
2. **Run a one-shot job from CI** that snapshots current annotations into the ConfigMap before the CD system reconciles. This is rarely worth the complexity; pattern 1 is usually sufficient.

## Uninstall in a GitOps world

Uninstalling auto-instrumentation is just removing the annotation keys from the committed YAML. The CD system reconciles, strategic-merge-patch removes the keys, and pods roll on the next Deployment/StatefulSet change. For immediate effect, `kubectl rollout restart` the targeted workloads after the commit reconciles.

To delete the Instrumentation CRs themselves, remove `instrumentation-cr.yaml` from the resources list. The CD system reconciles, `kubectl delete otelinst` runs, and the CRs disappear. **Always delete CRs BEFORE uninstalling the base collector chart**, otherwise the CRs orphan and the CRD cleanup on chart uninstall may fail.

## Runbook differences in GitOps mode

The rendered `runbook.md` in GitOps mode replaces the "run `apply-instrumentation.sh`" step with "commit and push `instrumentation-cr.yaml` to git; wait for CD reconciliation; confirm via `status.sh`". Every other diagnostic and verify step is unchanged.
