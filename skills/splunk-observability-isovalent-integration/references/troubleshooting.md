# Troubleshooting

## No `cilium_*` / `hubble_*` / `tetragon_*` metrics in Splunk Observability Cloud

1. Confirm the Splunk OTel collector pods are running and the overlay merged correctly:

```bash
helm get values splunk-otel-collector -n splunk-otel -a | grep prometheus/isovalent
```

You should see all enabled scrape jobs.

2. Check the collector agent logs for scrape errors:

```bash
kubectl -n splunk-otel logs -l app=splunk-otel-collector --tail=200 | grep -E 'cilium|hubble|tetragon|forbidden|scrape'
```

Common errors:

- `endpoints is forbidden`: missing RBAC. The base chart's ClusterRole grants pods + services but not endpoints. **This is the AI Pod skill's known production issue (atl-ocp2)**, not Isovalent's — Isovalent uses pod-based SD, not endpoint-based. If you see this error, either you've added a custom endpoint-SD scrape, or the chart version doesn't grant the expected pod permissions.
- `connection refused`: pod IP correct, port wrong. Confirm the metrics ports match (cilium 9962, hubble 9965, envoy 9964, operator 9963, tetragon 2112, tetragon-operator 2113).
- `no targets matched`: the relabel_configs `keep` rule didn't match any pods. Confirm pod labels: `kubectl -n kube-system get pods --show-labels | grep cilium`.

3. Confirm metrics flow through the `filter/includemetrics` allow-list:

```bash
kubectl -n splunk-otel logs -l app=splunk-otel-collector --tail=500 | grep filter/includemetrics
```

If you see `dropped` lines mentioning `cilium_*` series you expect to receive, add them to `spec.metric_allowlist.extra` and re-render.

## No Tetragon events in `index=cisco_isovalent`

1. Confirm Tetragon is writing files (default file-based path):

```bash
kubectl debug node/<node> --image=ubuntu -- ls -la /host/var/run/cilium/tetragon/
```

If empty, the Tetragon Helm install was misconfigured. Re-run `cisco-isovalent-platform-setup` with `--export-mode file` (or check `helm get values tetragon -n tetragon -a`).

2. Confirm the collector hostPath mount aligns with Tetragon's exportDirectory (this skill's validate.sh does this check; re-run it):

```bash
bash skills/splunk-observability-isovalent-integration/scripts/validate.sh
```

3. Confirm the `splunkhec` exporter is configured:

```bash
helm get values splunk-otel-collector -n splunk-otel -a | grep -A 5 splunkPlatform
```

You should see `logsEnabled: true` and the HEC endpoint.

4. Confirm the HEC token is valid:

```bash
HEC_CURL_CONFIG="$(mktemp)"
chmod 600 "$HEC_CURL_CONFIG"
{ printf 'header = "Authorization: Splunk '; tr -d '\r\n' < "$HEC_TOKEN_FILE"; printf '"\n'; } > "$HEC_CURL_CONFIG"

curl -sS -k -K "$HEC_CURL_CONFIG" \
    "https://$HEC_HOST:8088/services/collector/health"
rm -f "$HEC_CURL_CONFIG"
```

Should return `{"text":"HEC is healthy","code":17}`.

5. Confirm the events are reaching Splunk by searching:

```spl
index=cisco_isovalent | head 5
```

If results are empty but the OTel collector logs show successful exports, check the HEC token's allowed indexes — `cisco_isovalent` must be in the list.

## `kubectl exec ... tetragon ... 2112` is intentionally NOT used

The reference repo's `tests/validate_project_docs.sh` explicitly forbids the `kubectl exec ... tetragon ... 2112` pattern. Use the API server proxy instead:

```bash
kubectl get --raw /api/v1/namespaces/tetragon/services/tetragon:2112/proxy/metrics | head -20
```

This works without exec permissions and is the documented approach.

## OTel collector pods crash on OpenShift with SCC error

Symptom: `Error creating: pods "splunk-otel-collector-..." is forbidden: unable to validate against any security context constraint`.

Fix: grant the `anyuid` SCC to the collector ServiceAccount:

```bash
oc adm policy add-scc-to-user anyuid -z splunk-otel-collector -n splunk-otel
```

The `cisco-isovalent-platform-setup` skill renders an SCC helper script when `distribution: openshift`. Run it before installing the collector.

## Dashboards show "no data" after import

1. Confirm the dashboard's filter (`k8s.cluster.name`) matches your actual cluster name. The base collector's `clusterName` value is set from `spec.cluster_name` in this skill; verify with:

```bash
helm get values splunk-otel-collector -n splunk-otel -a | grep clusterName
```

2. Confirm the dashboard's metric exists in your O11y org:

```bash
O11Y_CURL_CONFIG="$(mktemp)"
chmod 600 "$O11Y_CURL_CONFIG"
{ printf 'header = "X-SF-Token: '; tr -d '\r\n' < "$O11Y_API_TOKEN_FILE"; printf '"\n'; } > "$O11Y_CURL_CONFIG"
trap 'rm -f "$O11Y_CURL_CONFIG"' EXIT

curl -sS -K "$O11Y_CURL_CONFIG" \
    "https://api.us0.signalfx.com/v2/metric?query=cilium_endpoint_state&limit=1" | jq
```

If empty, the metric isn't being received yet (give it 2-3 minutes after collector apply, then check OTel collector logs for scrape errors).

## Legacy fluentd path errors

Symptom: `fluentd: error: cannot load 'splunk_hec' plugin`.

Cause: `fluent-plugin-splunk-hec` was archived 2025-06-24. The plugin's gem may no longer be available in the operator's fluentd image.

Fix: migrate to the file-based path. Re-run both skills with the default `--export-mode file`. The Splunk-side data shape is identical — same sourcetype, same index — only the transport changes.

## Hubble Enterprise vs Hubble Relay confusion

- **Hubble Relay** (part of `cilium/cilium` and `isovalent/cilium-enterprise`): aggregates flows from per-node Hubble agents into a single API endpoint. Provides flow query / `hubble observe` CLI access. In-memory; flows do not persist across restarts.

- **Hubble Enterprise** (separate `isovalent/hubble-enterprise` chart, **private**): adds runtime security event collection (file/network/process events) on top of the basic flow visibility. This is what the Splunk Platform `cisco_isovalent` integration is designed for.

If you see "no Tetragon events" but Hubble flows are working, you may have only Hubble Relay (OSS) and not Hubble Enterprise. Hubble Enterprise requires:

1. A chart-access agreement with Isovalent (`https://isovalent.com/splunk-contact-us/`).
2. `cisco-isovalent-platform-setup --enable-hubble-enterprise` (which currently only emits the contact-link install instructions; you must run the actual `helm install isovalent/hubble-enterprise` after getting access).

For OSS users without Hubble Enterprise, the Tetragon stream alone is sufficient for the `cisco:isovalent:processExec` use case — the events arrive via the standard Tetragon DaemonSet.
