# Annotation Surgery

The single most common authoring bug for operator-driven auto-instrumentation is putting the `inject-<lang>` annotation at the wrong path. This reference documents the patch mechanics the rendered `apply-annotations.sh` and `uninstall.sh` scripts use, and how the static validator enforces correctness.

## The right path

For Deployments, StatefulSets, and DaemonSets, the operator webhook inspects the **Pod template**, not the workload object. The annotations MUST live at:

```yaml
spec:
  template:
    metadata:
      annotations:
        instrumentation.opentelemetry.io/inject-java: "splunk-otel/splunk-otel-auto-instrumentation"
```

For Namespaces, the operator inspects the Namespace annotations directly (Namespaces have no pod template). That path is simply:

```yaml
metadata:
  annotations:
    instrumentation.opentelemetry.io/inject-java: "splunk-otel/splunk-otel-auto-instrumentation"
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
          "instrumentation.opentelemetry.io/inject-java": "splunk-otel/splunk-otel-auto-instrumentation"
        }
      }
    }
  }
}
```

This is equivalent to `kubectl edit` adding just those annotation keys. Because it's a strategic merge, **existing annotations on the pod template are preserved**. The patch is idempotent: running it twice is a no-op.

## Backup ConfigMap

Before any strategic-merge patch, the reviewed backup helper reads and validates
every selected workload. It captures only the rendered managed-key union into a
versioned snapshot. Snapshot keys are collision-resistant hashes of the full
workload identity, and each value records the target, complete managed-key list,
and only previously present managed values:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: splunk-otel-auto-instrumentation-annotations-backup
  namespace: splunk-otel
data:
  snapshot-0123456789abcdef0123: '{"apiVersion":"splunk-observability-k8s-auto-instrumentation-setup/annotation-snapshot/v1","target":"Deployment/prod/payments-api","managedKeys":["instrumentation.opentelemetry.io/inject-java"],"values":{}}'
```

The helper creates or resourceVersion-replaces the owned ConfigMap, then reads
it back and validates every selected snapshot before the first workload patch.
Any kubectl failure, malformed JSON, ownership mismatch, incomplete snapshot,
or key collision aborts with no workload mutation. Unrelated annotations are
never copied into the ConfigMap.

## Rollout restart ordering

After patching, `apply-annotations.sh` sequentially runs:

```bash
kubectl rollout restart <kind>/<name>
kubectl rollout status <kind>/<name>   # wait before moving to next workload
```

The `status` wait prevents cascading failure: if one rollout gets stuck (e.g. an init container CrashLoops because of a mis-annotated Go binary), the subsequent workloads are not touched. Operator can debug one failure at a time.

## Uninstall path

`uninstall.sh` reverses the patch. For each target workload:

1. Validate every selected workload and the owned ConfigMap before patching.
2. Require a versioned, correct-target, complete snapshot for every workload;
   missing or corrupt snapshots fail closed.
3. Build one patch containing only that workload's rendered managed keys.
   Previously present values are restored; previously absent keys are `null`.
4. `kubectl rollout restart` and wait.

There is no best-effort fallback. In particular, uninstall never guesses which
keys to null and never includes unrelated annotations.

## Idempotency matrix

| Scenario | Apply behavior | Uninstall behavior |
|----------|----------------|--------------------|
| First run | Writes backup, patches, rolls out | Reverses patch, rolls out |
| Re-run after partial failure | Preserves verified original snapshots, then reapplies selected patches | Requires every selected snapshot before continuing |
| Re-run after full success | Preserves verified original snapshots, then reapplies selected patches | Same as first run while complete snapshots remain |
| After manual `kubectl patch` by operator | Next re-run may restart (if the manual patch drifted the state) | Uninstalls back to backup, not to the manual-patch state |

## Static validation

`validate.sh` (static mode) parses `workload-annotations.yaml` and asserts:

1. Every Deployment/StatefulSet/DaemonSet document has the inject-* annotations at `spec.template.metadata.annotations`.
2. No Deployment/StatefulSet/DaemonSet document has an inject-* annotation at top-level `metadata.annotations`.
3. Every Go-bound workload has `otel-go-auto-target-exe` set.

Any violation fails the static check, which is the gate that runs in CI before apply.
