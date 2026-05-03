# Collector overlay reference

The skill renders a single-file YAML overlay (`splunk-otel-overlay/values.overlay.yaml`) that the operator merges into the base collector values from `splunk-observability-otel-collector-setup` via `yq` deep-merge. This annex documents the overlay structure.

## Top-level shape

```yaml
clusterName: lab-cluster
distribution: kubernetes              # or openshift, eks, gke
operator:
  enabled: false                       # the OTel operator collides with Cilium; off by default
operatorcrds:
  installed: false
gateway:
  enabled: false                       # collector pushes direct to O11y
agent:
  extraVolumes: [...]                  # hostPath mount for /var/run/cilium/tetragon (file mode)
  extraVolumeMounts: [...]
  config:
    extensions:
      k8s_observer: { auth_type: serviceAccount, observe_pods: true }
    receivers:
      kubeletstats: { collection_interval: 30s, insecure_skip_verify: true }
      prometheus/isovalent_cilium: { ... }   # 9962
      prometheus/isovalent_hubble: { ... }   # 9965
      prometheus/isovalent_envoy: { ... }    # 9964
      prometheus/isovalent_operator: { ... } # 9963
      prometheus/isovalent_tetragon: { ... } # 2112
      prometheus/isovalent_tetragon_operator: { ... } # 2113
      prometheus/isovalent_dnsproxy: { ... } # 9967, optional
    processors:
      filter/includemetrics: { metrics: { include: { match_type: strict, metric_names: [...] } } }
      resourcedetection: { detectors: [system], system: { hostname_sources: [os] } }
    service:
      pipelines:
        metrics:
          exporters: [signalfx]
          receivers: [...all enabled prometheus/isovalent_*..., kubeletstats, hostmetrics, otlp]
          processors: [memory_limiter, batch, filter/includemetrics, resourcedetection, resource]
splunkPlatform:
  logsEnabled: true                    # only in file/stdout export modes
logsCollection:
  containers:
    useSplunkIncludeAnnotation: true
  extraFileLogs:
    filelog/tetragon: { ... }          # only in file mode
```

## yq deep-merge

```bash
yq eval-all '. as $item ireduce ({}; . * $item)' \
    splunk-observability-otel-rendered/k8s/values.yaml \
    splunk-observability-isovalent-rendered/splunk-otel-overlay/values.overlay.yaml \
    > /tmp/merged-values.yaml
```

The merge is right-biased — overlay keys win when both files set the same key. This means:

- `operator.enabled: false` (from the overlay) wins over the base collector's `operator.enabled: true` default.
- `gateway.enabled: false` wins.
- `agent.config.receivers` is **merged** at the receiver level — base receivers and overlay receivers coexist.
- `agent.config.service.pipelines.metrics.receivers` is **replaced** entirely by the overlay's list (yq's `*` operator concats lists, but the resulting list gets de-duplicated by the OTel collector at parse time; this still requires care if the base list has receivers we want to preserve).

For a more controlled merge, use `yq eval-all 'select(fileIndex == 0) * select(fileIndex == 1)' base.yaml overlay.yaml`.

## Subtractive overrides explained

`operator.enabled: false`: the OTel operator manages auto-instrumentation CRDs (`Instrumentation`). Cilium ships its own CRDs (`CiliumNetworkPolicy`, `CiliumClusterwideNetworkPolicy`, `TracingPolicy`, etc.); having the OTel operator running alongside is not strictly a conflict, but it adds a Deployment + RBAC the Isovalent integration doesn't need. Off by default.

`operatorcrds.installed: false`: matches `operator.enabled: false`.

`gateway.enabled: false`: the collector pushes direct to O11y from each agent pod. A gateway adds latency and a single point of failure; not needed for the typical Isovalent integration size.

## Distribution-specific overrides

When `distribution: openshift`:

- `kubeletstats.insecure_skip_verify: true` (REQUIRED — kubelet self-signed certs).
- The base collector skill's `cloudProvider: ""` (set elsewhere) for bare-metal OpenShift.
- The base collector's certmanager subchart is off by default in the AI Pod / Isovalent profile (OpenShift manages certs).

When `distribution: eks`:

- `cloudProvider: aws` and `distribution: eks` resolve cluster name automatically (per the base collector skill's `distribution_allows_cluster_autodetect`).

## Adding a custom scrape job

If you have an Isovalent component not in the seven default scrape jobs (e.g. a custom DaemonSet exposing Prometheus metrics), add it to the overlay manually after render:

```yaml
agent:
  config:
    receivers:
      prometheus/my-custom-job:
        config:
          scrape_configs:
            - job_name: 'my-custom'
              scrape_interval: 30s
              metrics_path: /metrics
              kubernetes_sd_configs:
                - role: pod
              relabel_configs:
                - source_labels: [__meta_kubernetes_pod_label_my_app]
                  action: keep
                  regex: my-app
                - source_labels: [__meta_kubernetes_pod_ip]
                  target_label: __address__
                  replacement: ${__meta_kubernetes_pod_ip}:9100
    service:
      pipelines:
        metrics:
          receivers:
            - prometheus/my-custom-job
            # ...keep the rest of the receivers list...
```

Also add the relevant metric names to `spec.metric_allowlist.extra` so they pass the `filter/includemetrics` processor.
