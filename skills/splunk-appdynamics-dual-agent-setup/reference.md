# Dual Agent Reference

Primary sources:

- https://help.splunk.com/en/appdynamics-on-premises/virtual-appliance-self-hosted/25.10.0/splunk-appdynamics-for-opentelemetry/instrument-applications-with-splunk-appdynamics-for-opentelemetry/enable-opentelemetry-in-the-java-agent
- https://help.splunk.com/en/appdynamics-on-premises/virtual-appliance-self-hosted/25.10.0/splunk-appdynamics-for-opentelemetry/instrument-applications-with-splunk-appdynamics-for-opentelemetry/enable-opentelemetry-in-the-java-agent/enable-dual-signal-mode

Operational contract:

- Render first, then `--apply preflight`, then `--apply collector`, then
  `--apply java`, or use `--apply all` for the collector-first sequence.
- Java Dual Signal configuration uses persistent startup files, not dynamic
  attach, for production apply.
- The default collector endpoint is `http://127.0.0.1:4318` with
  `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`.
- Rollback restores backed-up files and restarts only affected gated services.
