# Milvus, storage, Redfish details

This annex documents the deployment specifics for the AI Pod's optional Milvus, storage, and Redfish scrape targets.

## Milvus

The umbrella expects Milvus to be deployed via the official Helm chart (`milvus/milvus`). The chart exposes `metrics` Service by default. If you've used a different chart or hand-rolled deployment, ensure:

- Pod label `app.kubernetes.io/name: milvus` is set.
- A Service exists pointing at port 9091 (Milvus's default Prometheus port).
- The OTel agent's namespace has RBAC to list endpoints in the Milvus namespace (handled by the umbrella's `rbac.customRules` patch when `--nim-scrape-mode endpoints`).

### Standalone vs Cluster mode

Milvus can run in two modes:

- **Standalone**: single pod, all components in one container. Metrics are mixed; you'll see `milvus_proxy_*` and `milvus_querynode_*` from the same pod.
- **Cluster**: separate pods per component (proxy, querynode, datanode, indexnode, rootcoord, etc.). Each pod is scraped independently; metrics include a `role` label.

The umbrella's discovery rule matches both modes (label-based, not pod-name-based).

## NetApp Trident

Trident is the NetApp-supplied CSI driver for Kubernetes. Common topology:

- Trident Controller pod (one per cluster, in `trident` namespace).
- Trident Node pods (one per node).
- ONTAP backend (external; Trident talks to it via REST).

The umbrella scrapes the Controller's Prometheus endpoint on port 17001. The Node pods don't expose Prometheus by default; if you need per-node IOPS, install the NetApp Performance Pack separately.

### RBAC for Trident scrape

The umbrella's RBAC patch (`rbac.customRules`) grants endpoint list across all namespaces. If you've restricted RBAC to specific namespaces, ensure `trident` is in the allowed list.

## Pure Portworx

Portworx is Pure Storage's container-native storage. It runs as a DaemonSet (`portworx` in `kube-system` or its own namespace).

The umbrella scrapes the Portworx daemon's Prometheus endpoint on port 17018. Default selector:

```yaml
rule: type == "pod" && labels["name"] == "portworx"
```

If you've labeled your Portworx pods differently (e.g. `app.kubernetes.io/name: portworx`), update the umbrella's spec.

### Portworx vs OpenShift Container Storage (OCS)

OCS is Red Hat's offering based on Ceph. The umbrella does NOT include an OCS scrape; OCS uses Rook + Ceph Manager Prometheus exporters with different ports and labels. If your AI Pod uses OCS instead of Portworx, hand-edit the overlay to add an OCS scrape target.

## Redfish

The umbrella's Redfish scrape assumes a Redfish exporter is deployed in-cluster, polling Cisco UCS BMCs over Redfish API. Common deployment:

```yaml
# Redfish exporter Deployment
- name: redfish-exporter
  image: mrlhansen/redfish_exporter:latest
  ports:
    - containerPort: 9610
  env:
    - name: REDFISH_USERNAME
      valueFrom: { secretKeyRef: { name: redfish-creds, key: username } }
    - name: REDFISH_PASSWORD
      valueFrom: { secretKeyRef: { name: redfish-creds, key: password } }
  volumeMounts:
    - name: targets
      mountPath: /etc/redfish_exporter
```

The exporter reads target BMC IPs from a config file (`/etc/redfish_exporter/targets.yaml`).

### Discovery: Service vs static_configs

The Redfish exporter exposes metrics via Prometheus's "scrape with target" pattern: scraper passes a `target` query string parameter, exporter queries that target's BMC, returns metrics. This means standard `endpoint`-based discovery doesn't work.

The umbrella uses `static_configs` instead:

```yaml
prometheus_simple:
  config:
    static_configs:
      - targets: ['redfish-exporter.cisco-ai-pod.svc:9610']
        labels: { redfish_target: ucs-bmc-1 }
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [redfish_target]
        target_label: instance
      - target_label: __address__
        replacement: redfish-exporter.cisco-ai-pod.svc:9610
```

For multi-BMC fleets, repeat the static_configs block per BMC. The skill renders one entry by default; hand-edit for multi-BMC.

## Out of band BMC vs in-band IPMI

Redfish requires the BMC to be reachable at the API level (HTTPS port 5000 or 8443 typically). If your AI Pod's UCS chassis BMCs are NOT on the cluster's network (typical secure deployments), you'll need:

- A jump host that has BMC access AND can be reached from the cluster.
- Or, ingest via Cisco Intersight (the Intersight skill ingests UCS hardware health from Intersight, which already has out-of-band BMC access). This is the recommended pattern: skip Redfish and use Intersight for hardware health.

If you have both Intersight and Redfish, the metrics overlap. Use Intersight as primary; Redfish as fallback for environments where Intersight isn't available.

## Cardinality consideration

Each Redfish-monitored chassis = ~30 metrics (per sensor: temperature, fan, PSU, memory health, drive health, etc.). For 10 chassis = 300 series. Combined with NIM/vLLM/Milvus/storage, total cardinality ~1500-2000 MTS for a fully-instrumented AI Pod.

## Disabling individual scrapes

```yaml
milvus: { enabled: false }
storage:
  trident: { enabled: false }
  portworx: { enabled: true }
redfish: { enabled: false }       # rely on Intersight for hardware health
```

The umbrella renders only enabled scrape jobs.
