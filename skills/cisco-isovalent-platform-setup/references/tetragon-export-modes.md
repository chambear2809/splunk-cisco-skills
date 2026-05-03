# Tetragon export modes

The skill renders Tetragon Helm values with one of three export modes, controlled by `--export-mode` or `tetragon.export.mode` in the spec.

## `file` (default, recommended)

```yaml
tetragon:
  exportDirectory: /var/run/cilium/tetragon
  exportFilename: tetragon.log
```

Tetragon writes structured JSON events to `/var/run/cilium/tetragon/tetragon.log` on each node (with rotation per the chart's defaults).

This is the **production-validated path** that pairs with `splunk-observability-isovalent-integration`'s OTel collector overlay:

```yaml
agent:
  extraVolumes:
    - name: tetragon
      hostPath:
        path: /var/run/cilium/tetragon
  extraVolumeMounts:
    - name: tetragon
      mountPath: /var/run/cilium/tetragon

logsCollection:
  extraFileLogs:
    filelog/tetragon:
      include:
        - /var/run/cilium/tetragon/*.log
      start_at: beginning
      include_file_path: true
      resource:
        com.splunk.index: cisco_isovalent
        com.splunk.source: /var/run/cilium/tetragon/
        host.name: 'EXPR(env("K8S_NODE_NAME"))'
        com.splunk.sourcetype: cisco:isovalent
```

The Splunk OTel collector's filelog receiver picks up the files and ships through the `splunkhec` exporter to Splunk Platform HEC. **No fluentd dependency.** Splunk-side ingestion is handled by `cisco-security-cloud-setup` with `PRODUCT=isovalent`.

Pros:

- Clean separation: Tetragon writes files, OTel reads files. No shared lifecycle.
- Resilient to OTel collector restarts (Tetragon keeps writing; OTel resumes from checkpoint).
- Officially supported `splunkhec` exporter.

Cons:

- Requires hostPath mount in OTel collector (may be blocked by SCC/PSP policies).
- One extra step to confirm the host paths align between Tetragon and OTel collector.

## `stdout` (alternative when hostPath is blocked)

```yaml
tetragon:
  export:
    mode: stdout
```

Tetragon prints events to container stdout. The OTel collector's container log collection picks them up. No hostPath mount required.

Use when:

- OpenShift SCC or Pod Security Policy blocks hostPath mounts.
- You want simpler RBAC (no extra volume permissions).

Trade-offs:

- Coupled to container log retention (kubelet rotation, container restart history).
- More noise: stdout includes Tetragon's own startup logs alongside the events.
- Slightly higher overhead at high event volume (everything goes through container log machinery).

## `fluentd` (DEPRECATED; legacy only)

```yaml
tetragon:
  export:
    mode: fluentd
    fluentd:
      output: |-
        @type splunk_hec
        host PLACEHOLDER_HEC_HOST
        port 8088
        token PLACEHOLDER_HEC_TOKEN
        default_index PLACEHOLDER_INDEX
        use_ssl false
```

This is the recipe shown in the Splunking Isovalent blog (2026-02-02) but it depends on `fluent-plugin-splunk-hec`, which was **archived 2025-06-24**. The plugin still works at the time of this writing but receives no further updates and may break on future Splunk HEC API changes.

The skill renders this mode behind `--export-mode fluentd` and surfaces a prominent **DEPRECATION WARNING** in the rendered metadata.

Migration: switch to `--export-mode file` (default). The Splunk-side data shape is identical — same sourcetype, same index — only the transport layer changes.

## Choosing a mode

| Constraint | Recommended mode |
|------------|------------------|
| New install on standard K8s | `file` |
| OpenShift with strict SCC | `stdout` |
| Existing fluentd-based pipeline | `file` (migrate from `fluentd`) |
| You absolutely cannot change anything | `fluentd` (with DEPRECATION caveat) |
