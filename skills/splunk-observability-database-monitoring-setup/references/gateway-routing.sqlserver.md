# SQL Server DBMon Gateway Routing

Splunk's gateway best-practice page focuses on Microsoft SQL Server DBMon
events. Use a dedicated OTLP HTTP path between the collector that runs the
`sqlserver` receiver and the gateway collector, then send from the gateway to
the Splunk Observability `/v3/event` endpoint.

## Receiver Collector

The database receiver collector sends DBMon events as logs to the gateway's
dedicated endpoint:

```yaml
exporters:
  otlphttp/dbmon:
    endpoint: "http://${SPLUNK_GATEWAY_URL}:7276"
    sending_queue:
      batch:
        max_size: 10485760
        sizer: bytes

service:
  pipelines:
    logs/dbmon:
      receivers: [sqlserver]
      processors: [memory_limiter, batch]
      exporters: [otlphttp/dbmon]
```

## Gateway Collector

The gateway receives only DBMon logs on that listener and forwards them to
Splunk Observability Cloud:

```yaml
receivers:
  otlp/dbmon:
    protocols:
      http:
        endpoint: "${SPLUNK_LISTEN_INTERFACE}:7276"

exporters:
  otlphttp/dbmon:
    headers:
      X-SF-Token: "${SPLUNK_ACCESS_TOKEN}"
      X-splunk-instrumentation-library: dbmon
    logs_endpoint: "${SPLUNK_INGEST_URL}/v3/event"
    sending_queue:
      batch:
        max_size: 10485760
        sizer: bytes

service:
  pipelines:
    logs/dbmon:
      receivers: [otlp/dbmon]
      processors: [memory_limiter, batch]
      exporters: [otlphttp/dbmon]
```

This skill renders the direct-to-Splunk pattern by default. Use this reference
when the operator already runs a gateway collector and wants explicit DBMon
event isolation.
