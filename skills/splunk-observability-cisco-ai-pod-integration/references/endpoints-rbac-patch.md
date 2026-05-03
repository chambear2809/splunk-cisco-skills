# Endpoints RBAC patch

The umbrella conditionally emits an `rbac.customRules` block in the rendered overlay when `nim_scrape_mode: endpoints` (the default). This annex documents why and what.

## The problem

The Splunk OTel collector chart's default ClusterRole grants pod-list cluster-wide. It does NOT grant **endpoint** list cluster-wide.

When the umbrella's NIM scrape uses `kubernetes_sd_configs.role: endpoints` (the precise mode), the OTel agent needs to list endpoints in the NIM-hosting namespaces (`nvidia-inference`, `nvidia-nemo`, etc.). Without this RBAC, scrapes fail silently with `forbidden: endpoints is forbidden` in the agent log, and NIM metrics never appear in O11y.

This was the #1 production failure in the atl-ocp2 deployment.

## The fix

The umbrella adds a `rbac.customRules` block to the rendered Helm values overlay:

```yaml
rbac:
  customRules:
    - apiGroups: [""]
      resources: ["endpoints"]
      verbs: ["get", "list", "watch"]
    - apiGroups: ["discovery.k8s.io"]
      resources: ["endpointslices"]
      verbs: ["get", "list", "watch"]
```

The chart merges these into the existing ClusterRole. After `helm upgrade`, the rendered ClusterRole includes both the chart's defaults AND these custom rules.

## Why both `endpoints` and `endpointslices`?

- `endpoints` (core API): the legacy resource. Older Kubernetes versions and the upstream Prometheus discovery default to this.
- `endpointslices` (discovery.k8s.io API): the modern, scalable resource. Kubernetes v1.21+ prefers this; some discovery code paths bypass `endpoints` entirely and go straight to `endpointslices`.

The OTel collector's Kubernetes service discovery code evaluates BOTH paths depending on chart version + collector version. To be safe, grant both. The cost is zero (read-only access on a non-secret resource).

## Why is this only emitted when `nim_scrape_mode: endpoints`?

In `nim_scrape_mode: pods` mode, the umbrella's NIM scrape uses pod-based discovery (matching label `app: <model-name>`), which only requires pod-list permission. Endpoint RBAC isn't needed.

The endpoint RBAC has a small but non-zero security cost: it grants the OTel collector ServiceAccount the ability to enumerate Kubernetes Service endpoints across all namespaces. This is read-only and not particularly sensitive (Service endpoints are essentially public IP/port lists), but it's still a privilege expansion. The umbrella avoids granting it when not needed.

## Verification

After `helm upgrade`:

```bash
kubectl auth can-i --as system:serviceaccount:splunk-otel:splunk-otel-collector \
  list endpoints -n nvidia-inference
# Expected: yes

kubectl auth can-i --as system:serviceaccount:splunk-otel:splunk-otel-collector \
  list endpointslices.discovery.k8s.io -n nvidia-inference
# Expected: yes
```

If both are `yes` but NIM metrics still don't appear, the issue is elsewhere. Check the OTel agent logs:

```bash
kubectl -n splunk-otel logs daemonset/<release>-splunk-otel-collector-agent --tail=300 \
  | grep -E 'nim|forbidden|endpoints'
```

## What if the chart deploy fails to apply customRules?

Older versions of the splunk-otel-collector chart (pre v0.95) didn't expose `rbac.customRules`. If you're on an older chart, hand-edit the ClusterRole post-install:

```bash
kubectl edit clusterrole splunk-otel-collector
# Add the two rules from above to the rules: list.
```

Then restart the agent DaemonSet:

```bash
kubectl -n splunk-otel rollout restart daemonset/<release>-splunk-otel-collector-agent
```

The skill assumes chart v0.95+; older versions will silently ignore `rbac.customRules`.

## Anti-patterns

- **Granting cluster-admin to the OTel ServiceAccount**: WORKS but is massive privilege escalation. NEVER.
- **Using a separate "scraper" ServiceAccount with broader RBAC**: doesn't work; the chart's discovery code uses the chart's default SA.
- **Disabling NIM scrape entirely** to avoid the RBAC need: defeats the purpose. Use `nim_scrape_mode: pods` if you really need to avoid endpoint RBAC; you'll get less precise scrape targeting but fewer permissions needed.

## Production atl-ocp2 timeline

Original deployment: missing endpoint RBAC. NIM scrape silently failed. No metrics appeared in O11y.

Investigation: tail the agent logs, see `forbidden: endpoints is forbidden`. RBAC patch crafted, applied via custom kubectl edit.

Codified: the umbrella now emits `rbac.customRules` automatically. Future deployments don't repeat the problem.

## Test coverage

`tests/test_splunk_observability_cisco_ai_pod_integration.py::test_rbac_custom_rules_emitted_when_endpoints_mode` asserts that the rendered overlay contains the rbac block when `nim_scrape_mode=endpoints`, and `test_rbac_custom_rules_omitted_when_pods_mode` asserts the opposite for the alternative mode.
