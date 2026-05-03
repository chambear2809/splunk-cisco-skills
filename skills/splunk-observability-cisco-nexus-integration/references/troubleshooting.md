# Troubleshooting

## No `cisco.device.up` metric in Splunk Observability Cloud

1. Confirm the cluster-receiver pod is running:

```bash
kubectl -n splunk-otel get pods -l component=k8s-cluster-receiver
```

2. Confirm the Secret `cisco-nexus-ssh` exists in the same namespace:

```bash
kubectl -n splunk-otel get secret cisco-nexus-ssh -o yaml
```

3. Tail the cluster-receiver logs for cisco_os errors:

```bash
kubectl -n splunk-otel logs deployment/<release>-splunk-otel-collector-k8s-cluster-receiver --tail=200 \
  | grep -E 'cisco_os|ssh|auth'
```

Common errors:

- `ssh: handshake failed: ssh: unable to authenticate`: wrong username/password. Verify the Secret values.
- `dial tcp <host>:22: i/o timeout`: cluster-receiver pod can't reach the Nexus management IP. Check NetworkPolicy + Nexus management ACL.
- `unmarshal error in cisco_os config`: collector chart version is too old; cisco_os v0.149.0+ format mismatch. Pin a newer chart.

## SSH connectivity from cluster-receiver

Most SSH issues are network-reachability problems, not auth problems. Test directly:

```bash
kubectl -n splunk-otel exec deployment/<release>-splunk-otel-collector-k8s-cluster-receiver -- \
  nc -zv <nexus-mgmt-ip> 22
```

If `nc` reports success but the receiver still fails, the issue is auth or device permissions. Try a manual SSH from the same pod:

```bash
kubectl -n splunk-otel exec -it deployment/<release>-splunk-otel-collector-k8s-cluster-receiver -- \
  ssh -v -o StrictHostKeyChecking=no splunk-otel@<nexus-mgmt-ip>
```

(Note: the cluster-receiver image may not include an SSH client; use a debug pod with the same SA + namespace if needed.)

## Interface status always shows 0

Some Nexus models report `system.network.interface.status` as a string (`"up"`/`"down"`) instead of a numeric. The cisco_os receiver maps strings to 0/1 as of v0.149.0; older versions may produce string-typed metric points which the signalfx exporter rejects.

Check the collector logs for `unsupported value type` errors. If present, update to receiver v0.149.0+.

## Per-interface metrics not appearing

The `interfaces` scraper enumerates interfaces via `show interface brief`. If your Nexus device's role doesn't permit `show interface brief`, the scraper silently skips it (no error, no data).

Test from a Nexus admin shell:

```
nexus# show interface brief
```

If empty or permission-denied, grant the SSH user the `network-operator` role:

```
nexus# config terminal
nexus(config)# username splunk-otel role network-operator
```

## Receiver flooding the collector logs

If `otelcol_receiver_refused_metric_points{receiver="cisco_os"}` is non-zero, the cluster-receiver's memory_limiter is back-pressuring the receiver. Either:

- Increase memory_limit on the cluster-receiver: bump `clusterReceiver.resources.limits.memory` from 200Mi to 500Mi.
- Increase `collection_interval` to reduce scrape frequency (60s -> 120s).
- Disable noisy scrapers via `spec.scrapers.<name>.metrics.<metric>.enabled: false`.

## Multi-tenant clusters

If the cluster-receiver runs in a shared namespace and you want different Nexus credentials per tenant, create per-tenant Secrets and per-tenant cisco_os receiver instances (one per Secret/credential set). The receiver name has to be unique (e.g. `cisco_os/tenant-a`, `cisco_os/tenant-b`); the skill renders only one by default — hand-edit the overlay for multi-tenant deployments.

## Coordination with cisco-dc-networking-setup

If you ALSO ran `cisco-dc-networking-setup` (the Splunk Platform TA path), there is no overlap of work. The two skills produce non-conflicting artifacts:

- `cisco-dc-networking-setup` produces ACI/Nexus Dashboard/Nexus 9K modular inputs in Splunk Platform.
- This skill produces OTel collector overlay assets for O11y.

Both can run side-by-side without deconfliction.
