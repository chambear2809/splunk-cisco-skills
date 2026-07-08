# SQL Server DBMon Gateway Routing

Splunk's published DBMon gateway pattern is specifically scoped to Microsoft
SQL Server. Use it when the receiver collector cannot send query events
directly to Splunk Observability Cloud and an existing gateway must own
egress. Keep infrastructure metrics on the normal `signalfx` path and isolate
DBMon query events on a dedicated OTLP/HTTP listener.

Direct-to-Splunk remains this skill's default. Treat gateway routing for
PostgreSQL, Oracle, MySQL, or MariaDB as a documented support gap unless Splunk
Support approves the design.

## Receiver collector

Send only `logs/dbmon` to the gateway. Use the canonical `otlp_http` component
ID; do not copy the mixed `otlphttp`/`otlp_http` spelling that appears in some
older examples.

```yaml
exporters:
  otlp_http/dbmon:
    endpoint: "https://${SPLUNK_GATEWAY_HOST}:7276"
    tls:
      ca_file: "${env:SPLUNK_GATEWAY_CA_FILE}"
      server_name_override: "${env:SPLUNK_GATEWAY_SERVER_NAME}"
    sending_queue:
      batch:
        flush_timeout: 15s
        max_size: 10485760
        sizer: bytes

service:
  pipelines:
    logs/dbmon:
      receivers: [sqlserver/prod]
      processors: [memory_limiter, batch]
      exporters: [otlp_http/dbmon]
```

The receiver collector's `metrics/dbmon` pipeline continues to export through
`signalfx`; do not send infrastructure metrics to the event listener.

## Gateway collector

Bind a dedicated receiver for DBMon logs and forward those logs to the event
endpoint:

```yaml
receivers:
  otlp/dbmon:
    protocols:
      http:
        endpoint: "${env:SPLUNK_LISTEN_INTERFACE}:7276"
        tls:
          cert_file: "${env:SPLUNK_GATEWAY_CERT_FILE}"
          key_file: "${env:SPLUNK_GATEWAY_KEY_FILE}"

exporters:
  otlp_http/dbmon:
    headers:
      X-SF-Token: "${env:SPLUNK_ACCESS_TOKEN}"
      X-splunk-instrumentation-library: dbmon
    logs_endpoint: "${env:SPLUNK_INGEST_URL}/v3/event"
    sending_queue:
      batch:
        flush_timeout: 15s
        max_size: 10485760
        sizer: bytes

service:
  pipelines:
    logs/dbmon:
      receivers: [otlp/dbmon]
      processors: [memory_limiter, batch]
      exporters: [otlp_http/dbmon]
```

## Production checks

- Keep the dedicated listener private. Use TLS, network policy/firewall rules,
  and a narrowly scoped source allow-list for every non-loopback listener.
- Reference certificate/key paths and token environment variables only. Never
  embed PEM data, private keys, or access tokens in collector YAML.
- Run one SQL Server receiver per declared target and one active singleton
  scraper path. A gateway does not make an agent DaemonSet placement safe.
- Validate both collector configurations with the pinned `v0.155.0` binary
  before restart.
- Confirm the receiver collector can connect to the gateway, the gateway can
  reach `https://ingest.<realm>.observability.splunkcloud.com/v3/event`, and
  neither log stream shows authentication, TLS, queue, throttle, or export
  failures.
- Complete product validation in APM > Database monitoring and Infrastructure
  > Datastores. A healthy gateway listener alone does not prove DBMon works.

Official source:
<https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/get-data-in/best-practices-for-configuring-gateway-opentelemetry-collectors>
