# NIM scrape modes

The umbrella supports two NIM scrape modes via `--nim-scrape-mode` (or `spec.nim.scrape_mode`):

- `endpoints` (default, recommended): precise, namespace-scoped, requires `rbac.customRules`.
- `pods`: coarse, label-based, no extra RBAC.

This annex documents the trade-offs.

## Mode `endpoints` (default)

```yaml
receiver_creator/nim:
  watch_observers: [k8s_observer]
  receivers:
    prometheus_simple:
      rule: type == "endpoints" && (namespace == "nvidia-inference" || namespace == "nvidia-nemo") && (labels["app"] == "llama-3.1-70b" || labels["app.kubernetes.io/name"] == "llama-3.1-70b")
      config:
        endpoint: '`endpoint`:8000'
        metrics_path: /metrics
```

Pros:

- Per-Service granularity. The receiver_creator scrapes once per Service endpoint, not once per pod. Across N replicas of the same model, you get N×1 scrape, not N²×1.
- Namespace-scoped. The rule explicitly lists `nvidia-inference` and `nvidia-nemo`, so pods with the same `app` label in other namespaces (e.g. `dev/llama-3.1-70b-test`) are NOT scraped accidentally.
- Service-aware. If you create a Service in front of a multi-replica Deployment, the receiver_creator follows the Service to the underlying pods, so per-pod scraping doesn't break.

Cons:

- Requires `endpoints` + `endpointslices` RBAC. The umbrella's `rbac.customRules` block adds these (see `endpoints-rbac-patch.md`).
- More verbose discovery rule (must enumerate namespaces).

## Mode `pods`

```yaml
receiver_creator/nim:
  watch_observers: [k8s_observer]
  receivers:
    prometheus_simple:
      rule: type == "pod" && (labels["app"] == "llama-3.1-70b" || labels["app.kubernetes.io/name"] == "llama-3.1-70b")
      config:
        endpoint: '`endpoint`:8000'
        metrics_path: /metrics
```

Pros:

- No additional RBAC. The chart's default pod-list RBAC suffices.
- Simpler discovery rule.

Cons:

- Cluster-wide. The rule matches any pod with the `app` label, regardless of namespace. If you have a `dev/llama-3.1-70b-test` pod with the same label, it gets scraped. Usually not catastrophic, but can pollute prod metrics.
- Per-pod scraping. The receiver_creator creates one scrape instance per pod. With 10 replicas, that's 10 scrapes per cycle. (Not per-pod-per-pod, which would be N²; just N.)
- No Service-level grouping. Each pod's metrics are reported independently; you have to group_by(model_name) in SignalFlow.

## Which mode should I use?

Default: `endpoints`. It's the precise, production-correct option.

Use `pods` only if:

- Your cluster has security policy that explicitly forbids endpoint RBAC. Rare.
- You're in a single-namespace cluster where namespace-scoping is unnecessary.
- You're prototyping and want to skip the RBAC step.

For the AI Pod production deployment (atl-ocp2), `endpoints` mode was chosen and the RBAC was applied via the umbrella's customRules patch.

## Mixed mode: per-model overrides

The umbrella does NOT currently support per-model scrape mode overrides. All NIM models use the same mode. If you have a security exception for one specific namespace, hand-edit the rendered overlay to use a per-receiver-instance approach:

```yaml
receivers:
  receiver_creator/nim-prod:
    watch_observers: [k8s_observer]
    receivers:
      prometheus_simple:
        rule: type == "endpoints" && namespace == "nvidia-inference" && labels["app"] == "..."
  receiver_creator/nim-dev:
    watch_observers: [k8s_observer]
    receivers:
      prometheus_simple:
        rule: type == "pod" && namespace == "dev" && labels["app"] == "..."
service:
  pipelines:
    metrics/nvidianim-metrics:
      receivers: [receiver_creator/nim-prod, receiver_creator/nim-dev]
```

## Verifying mode is in effect

After deploy:

```bash
# Check the rendered ConfigMap of the agent DaemonSet
kubectl -n splunk-otel get cm <release>-splunk-otel-collector-agent -o jsonpath='{.data.relay}' | grep -A 5 'receiver_creator/nim:'
```

Look for `type == "endpoints"` (mode endpoints) or `type == "pod"` (mode pods).

```bash
# Check the actual scrape targets
kubectl -n splunk-otel logs daemonset/<release>-splunk-otel-collector-agent --tail=100 \
  | grep -E 'nim|started receiver'
```

You should see one log line per discovered NIM target.

## Anti-patterns

- **Mode `endpoints` without `rbac.customRules`**: the receiver_creator silently fails. NIM metrics never appear. The umbrella's renderer bundles them; if you're hand-editing, don't strip the RBAC block.
- **Mode `pods` with explicit namespace filter**: works but redundant. If you need namespace filtering, use mode `endpoints`.
- **Switching modes after deployment**: works but causes a brief metric gap during agent restart. Plan for ~30s of missing data on the switchover.
