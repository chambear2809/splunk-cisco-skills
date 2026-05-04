# Annotation Surgery

The single most common authoring bug for operator-driven auto-instrumentation is putting the `inject-<lang>` annotation at the wrong path. This reference documents the patch mechanics the rendered `apply-annotations.sh` and `uninstall.sh` scripts use, and how the static validator enforces correctness.

## The right path

For Deployments, StatefulSets, and DaemonSets, the operator webhook inspects the **Pod template**, not the workload object. The annotations MUST live at:

```yaml
spec:
  template:
    metadata:
      annotations:
        instrumentation.opentelemetry.io/inject-java: "true"
```

For Namespaces, the operator inspects the Namespace annotations directly (Namespaces have no pod template). That path is simply:

```yaml
metadata:
  annotations:
    instrumentation.opentelemetry.io/inject-java: "true"
```

## The wrong path (common bug)

Placing the annotation at `metadata.annotations` on a Deployment does nothing — the webhook fires on pod creation, but the pod inherits annotations from `spec.template.metadata.annotations`, not from the Deployment's top-level annotations. The injection never happens, and there's no error message — a silent failure. Render preflight and static validate both refuse this.

## Strategic merge patch mechanics

`apply-annotations.sh` uses `kubectl patch --type strategic` with a JSON body shaped like:

```json
{
  "spec": {
    "template": {
      "metadata": {
        "annotations": {
          "instrumentation.opentelemetry.io/inject-java": "true"
        }
      }
    }
  }
}
```

This is equivalent to `kubectl edit` adding just those annotation keys. Because it's a strategic merge, **existing annotations on the pod template are preserved**. The patch is idempotent: running it twice is a no-op.

## Backup ConfigMap

Before any strategic-merge patch, the apply script checks whether the backup ConfigMap (default `splunk-otel-auto-instrumentation-annotations-backup` in the CR namespace) has a key for the target workload. If not, it writes the current `spec.template.metadata.annotations` JSON there:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: splunk-otel-auto-instrumentation-annotations-backup
  namespace: splunk-otel
data:
  deployment-prod-payments-api: '{"prometheus.io/scrape":"true"}'
  deployment-prod-checkout-web: '{}'
  statefulset-prod-fraud-score: '{}'
```

The key format is `<kind-lower>-<namespace>-<name>`. The value is the JSON-serialized pre-instrumentation annotation map. Uninstall reverses the patch using this ConfigMap.

## Rollout restart ordering

After patching, `apply-annotations.sh` sequentially runs:

```bash
kubectl rollout restart <kind>/<name>
kubectl rollout status <kind>/<name>   # wait before moving to next workload
```

The `status` wait prevents cascading failure: if one rollout gets stuck (e.g. an init container CrashLoops because of a mis-annotated Go binary), the subsequent workloads are not touched. Operator can debug one failure at a time.

## Uninstall path

`uninstall.sh` reverses the patch. For each target workload:

1. Read the backup ConfigMap key.
2. Build a strategic-merge patch that sets the inject-* annotations to `null` (which removes them under strategic-merge semantics). Also nulls `container-names`, `otel-dotnet-auto-runtime`, `otel-go-auto-target-exe` for safety.
3. `kubectl rollout restart`.

If the backup key is missing, the script falls back to a best-effort revert that strips only the inject-* annotations without attempting to restore other pre-existing annotations.

## Idempotency matrix

| Scenario | Apply behavior | Uninstall behavior |
|----------|----------------|--------------------|
| First run | Writes backup, patches, rolls out | Reverses patch, rolls out |
| Re-run after partial failure | Skips workloads already at desired state; picks up where it left off | Idempotent (missing keys are no-ops) |
| Re-run after full success | No-op (no rollouts) | Same as first run if backup key exists |
| After manual `kubectl patch` by operator | Next re-run may restart (if the manual patch drifted the state) | Uninstalls back to backup, not to the manual-patch state |

## Static validation

`validate.sh` (static mode) parses `workload-annotations.yaml` and asserts:

1. Every Deployment/StatefulSet/DaemonSet document has the inject-* annotations at `spec.template.metadata.annotations`.
2. No Deployment/StatefulSet/DaemonSet document has an inject-* annotation at top-level `metadata.annotations`.
3. Every Go-bound workload has `otel-go-auto-target-exe` set.

Any violation fails the static check, which is the gate that runs in CI before apply.
