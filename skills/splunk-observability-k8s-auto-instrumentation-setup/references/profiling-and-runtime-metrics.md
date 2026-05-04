# AlwaysOn Profiling and Runtime Metrics

Splunk extends upstream OpenTelemetry auto-instrumentation with two optional features: **AlwaysOn Profiling** (low-overhead CPU + memory profiles sampled continuously) and **runtime metrics** (language-runtime gauges + counters such as JVM heap / GC, Node event loop, container cpu). Both are wired through env vars on the Instrumentation CR.

## Chart-level auto-wire

The base `splunk-otel-collector` Helm chart exposes a single boolean:

```yaml
splunkObservability:
  profilingEnabled: true
```

When this is set at the chart level, the chart injects `SPLUNK_PROFILER_ENABLED=true` and `SPLUNK_PROFILER_MEMORY_ENABLED=true` into the chart-rendered default Instrumentation CR. This skill's `--profiling-enabled` does the same thing on the **per-CR** blocks it renders, so the two paths compose.

## Per-CR env vars

| Env var | Values | Applies to | Notes |
|---------|--------|------------|-------|
| `SPLUNK_PROFILER_ENABLED` | `true`/`false` | Java, Node.js, .NET | Master profiling switch |
| `SPLUNK_PROFILER_MEMORY_ENABLED` | `true`/`false` | Java, Node.js | Memory profiles in addition to CPU |
| `SPLUNK_PROFILER_CALL_STACK_INTERVAL` | ms integer | Java | Default `10000` (10s between samples) |
| `SPLUNK_METRICS_ENABLED` | `true`/`false` | Java, Node.js | Runtime metrics emitted on the SignalFx-protocol endpoint |
| `SPLUNK_METRICS_ENDPOINT` | URL | Java, Node.js | Default `http://$(SPLUNK_OTEL_AGENT):9943/v2/datapoint` (agent DaemonSet 9943) |

## JDK compatibility

Java profiling requires **JDK 8u262 or newer**. Two JVM families are explicitly unsupported:

- Oracle JDK 8 (any update) — the JFR API is closed-source.
- IBM J9 — async-profiler cannot attach.

Preflight warns when the spec metadata mentions those JVMs so you can fix the runtime before rolling out.

## Runtime metrics endpoint

`$(SPLUNK_OTEL_AGENT):9943/v2/datapoint` is the SignalFx-protocol port on the Splunk OTel Collector agent DaemonSet. If you run gateway-only (EKS Fargate, or any topology without the DaemonSet), override `SPLUNK_METRICS_ENDPOINT` to the gateway Service DNS on the same port.

## Overhead

- CPU profiling: ~1-3% CPU overhead at default interval.
- Memory profiling: ~3-8% overhead; disable in very hot paths.
- Runtime metrics: <1%.

## Observed dashboards

After profiling lands in O11y, the **APM -> Services -> <your service> -> Profiling** tab shows flame graphs per pod. Runtime metrics land on the **Services -> Runtime Metrics** charts (JVM heap, GC pauses, Node event loop lag, etc.).

## Source references

- Splunk Observability Cloud docs: AlwaysOn Profiling configuration (per-language).
- `github.com/signalfx/splunk-otel-collector-chart` — `splunkObservability.profilingEnabled`.
- `github.com/signalfx/splunk-otel-java` — JFR-based profiler, 8u262+ requirement.
