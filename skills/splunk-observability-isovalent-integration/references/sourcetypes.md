# Splunk sourcetypes for Isovalent

## `cisco:isovalent` (broad)

The skill's default sourcetype for all Tetragon events written to `/var/run/cilium/tetragon/*.log`. Captures every event type Tetragon emits:

- `process_exec` — process execution events
- `process_exit` — process exit events
- `process_kprobe` — kprobe-attached function calls (e.g. tcp_connect)
- `process_uprobe` — uprobe-attached user function calls
- `process_tracepoint` — tracepoint-attached events
- `process_loader` — Tetragon process loader events
- DNS events
- HTTP events
- Network events

Use `cisco:isovalent` for general-purpose Splunk searches that don't care about the event type:

```spl
index=cisco_isovalent sourcetype=cisco:isovalent
| stats count by event_type
```

## `cisco:isovalent:processExec` (specific)

Specifically tagged Tetragon process_exec events. The Cisco Security Cloud App (Splunkbase 7404) Isovalent Runtime Security input expects this sourcetype because it provides field aliases that map raw Tetragon JSON paths to friendly names:

| Field alias | Raw Tetragon path | Description |
|-------------|-------------------|-------------|
| `parent_process_id` | `process_exec.parent.pid` | Parent process PID |
| `pod_image_name` | `process_exec.process.pod.container.image.name` | Pod container image name |
| `pod_name` | `process_exec.process.pod.name` | Pod name |
| `pod_namespace` | `process_exec.process.pod.namespace` | Pod namespace |
| `container_id` | `process_exec.process.pod.container.id` | Container runtime ID |
| `parent_process` | `process_exec.parent.binary + " " + process_exec.parent.arguments` | Parent process command line |
| `process` | `process_exec.process.binary + " " + process_exec.process.arguments` | Process command line |
| `process_name` | `process_exec.process.binary` | Executable name |
| `parent_process_name` | `process_exec.parent.binary` | Parent executable name |
| `cluster_name` | `process_exec.cluster_name` | Kubernetes cluster name |

(Source: Splunking Isovalent Data, Part 1, 2026-02-02.)

These aliases let security analysts write detections like:

```spl
index=cisco_isovalent sourcetype=cisco:isovalent:processExec
process_name IN ("/bin/sh", "/bin/bash", "/bin/dash")
parent_process_name!="*kubelet*"
| stats count by pod_namespace, pod_name, parent_process, process
```

## How the routing works

When `splunk_platform.also_render_processexec_routing: true` (default), the rendered overlay includes routing logic to tag specific events with the more specific sourcetype:

```yaml
agent:
  config:
    processors:
      transform/tetragon-routing:
        log_statements:
          - context: log
            statements:
              - set(attributes["com.splunk.sourcetype"], "cisco:isovalent:processExec") where IsString(attributes["event_type"]) and attributes["event_type"] == "process_exec"
```

This is a transform-processor pipeline addition. The original event also lands as `cisco:isovalent` (broad), so both Splunk searches work in parallel.

(Implementation note: the current renderer ships only the broad sourcetype. The routing is documented here as the design contract; if you need it operationally, add the transform/tetragon-routing block to the overlay manually after render.)

## Index conventions

| Index | Purpose |
|-------|---------|
| `cisco_isovalent` | Tetragon / Hubble Enterprise events (default for both sourcetypes) |
| `cisco_isovalent_metrics` | (optional) if you also want metrics-as-events; default config sends metrics to O11y, not Splunk Platform |

The Cisco Security Cloud App configures `cisco_isovalent` automatically when you run `cisco-security-cloud-setup --product isovalent --install`.

## Cross-reference with O11y

The same Tetragon stream lands in two places:

1. Splunk Platform: as `cisco:isovalent` / `cisco:isovalent:processExec` events in `cisco_isovalent` index. Used for security searches, ad-hoc investigation, Splunk Threat Research Team detections.

2. Splunk Observability Cloud: as `tetragon_*` metric series scraped by the OTel collector from port 2112. Used for dashboards, detectors, alerting on event rates / kernel function call rates.

These are complementary surfaces. Platform-side is for "what happened?" investigation; O11y-side is for "is something abnormal right now?" alerting.
