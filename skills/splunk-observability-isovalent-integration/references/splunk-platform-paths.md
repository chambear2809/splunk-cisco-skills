# Splunk Platform paths for Tetragon / Hubble Enterprise

Three paths for routing Tetragon (and optionally Hubble Enterprise) events into Splunk Platform. The skill defaults to the first; the second is an alternative; the third is legacy.

## File-based via OTel filelog receiver (DEFAULT, recommended)

**Production-validated** (atl-ocp2 OpenShift cluster, Splunk OTel chart v0.147.1).

Two coordinated changes:

1. Tetragon (configured by `cisco-isovalent-platform-setup` with `--export-mode file`) writes events to `/var/run/cilium/tetragon/<filename>` on each node.
2. The Splunk OTel collector agent (configured by this skill's overlay) mounts that directory as a hostPath volume and reads the files via the `filelog/tetragon` receiver, then ships through the chart's `splunkhec` exporter to Splunk Platform HEC.

Overlay snippet:

```yaml
agent:
  extraVolumes:
    - name: tetragon
      hostPath:
        path: /var/run/cilium/tetragon
  extraVolumeMounts:
    - name: tetragon
      mountPath: /var/run/cilium/tetragon

splunkPlatform:
  logsEnabled: true
  endpoint: https://hec.example.com:8088/services/collector
  insecureSkipVerify: false

logsCollection:
  containers:
    useSplunkIncludeAnnotation: true
  extraFileLogs:
    filelog/tetragon:
      include: ['/var/run/cilium/tetragon/*.log']
      start_at: beginning
      include_file_path: true
      include_file_name: false
      resource:
        com.splunk.index: cisco_isovalent
        com.splunk.source: /var/run/cilium/tetragon/
        host.name: 'EXPR(env("K8S_NODE_NAME"))'
        com.splunk.sourcetype: cisco:isovalent
```

Pros:

- Officially supported `splunkhec` exporter (per `docs.splunk.com/observability/.../splunk-hec-exporter.html`).
- No fluentd dependency.
- Resilient to OTel collector restarts (Tetragon keeps writing; OTel resumes from checkpoint).
- Clean separation of producer (Tetragon) and consumer (OTel collector).

Cons:

- Requires hostPath mount in OTel collector — may be blocked by OpenShift SCC or PSP.
- Path coordination: the platform-setup skill's `tetragon.exportDirectory` and this skill's `agent.extraVolumes[0].hostPath.path` must match exactly. The validate.sh in this skill checks this alignment.

## stdout via container log collection (alternative)

When OpenShift SCC or PSP blocks hostPath mounts:

```yaml
# Set --export-mode stdout when running cisco-isovalent-platform-setup
# AND set --export-mode stdout when running this skill.
```

The platform-setup skill writes Tetragon Helm values with `export.mode: stdout`. Tetragon prints events to container stdout; the Splunk OTel collector's container log collection picks them up via the chart's `splunkPlatform.logsEnabled: true` (no extraFileLogs needed).

Pros:

- No hostPath mount, no SCC/PSP friction.
- Same `splunkhec` exporter; same Splunk-side ingestion path.

Cons:

- Coupled to container log retention (kubelet rotation, container restart history).
- More noise: stdout includes Tetragon's own startup logs alongside the events. Splunk-side filtering may be needed to separate operational logs from event data.
- Slightly higher overhead at high event volume (everything goes through container log machinery).

## Legacy fluentd splunk_hec (DEPRECATED)

Splunking Isovalent blog (2026-02-02) recipe:

```yaml
tetragon:
  export:
    mode: fluentd
    fluentd:
      output: |-
        @type splunk_hec
        host hec.example.com
        port 8088
        token xxxxx
        default_index cisco_isovalent
        use_ssl false
```

`fluent-plugin-splunk-hec` was archived 2025-06-24. The plugin still works at the time of this writing but receives no further updates and may break on future Splunk HEC API changes.

The skill renders this path behind `--legacy-fluentd-hec` and emits a prominent DEPRECATION WARNING. Plan to migrate to the file-based path.

## Splunk Platform side: Cisco Security Cloud App

Regardless of which transport you pick, the Splunk Platform side is the **Cisco Security Cloud App** (Splunkbase 7404), specifically the Isovalent Runtime Security input. Configure via:

```bash
bash skills/cisco-security-cloud-setup/scripts/setup.sh \
    --product isovalent \
    --install
```

The app provides field aliases on `cisco:isovalent:processExec` events for Splunk Threat Research Team detections. See the Splunking Isovalent blog post for the field mapping table (`parent_process_id`, `pod_image_name`, `cluster_name`, etc.).

## Sourcetype reference

| Sourcetype | Source | Use case |
|-----------|--------|----------|
| `cisco:isovalent` | All Tetragon events (broad) | General-purpose Splunk searches; the skill default |
| `cisco:isovalent:processExec` | Tetragon process_exec events specifically | Cisco Security Cloud App field aliases; TRT detections |

When `splunk_platform.also_render_processexec_routing: true` (default), the rendered overlay includes a routing rule that re-tags events with `process_exec` as `cisco:isovalent:processExec`. Both sourcetypes land in the same `cisco_isovalent` index.
