# Dual Agent Reference

Primary sources:

- https://help.splunk.com/en/appdynamics-on-premises/virtual-appliance-self-hosted/26.1.0/splunk-appdynamics-for-opentelemetry/instrument-applications-with-splunk-appdynamics-for-opentelemetry/enable-opentelemetry-in-the-java-agent
- https://help.splunk.com/en/appdynamics-on-premises/virtual-appliance-self-hosted/26.1.0/splunk-appdynamics-for-opentelemetry/instrument-applications-with-splunk-appdynamics-for-opentelemetry/enable-opentelemetry-in-the-java-agent/enable-dual-signal-mode

Documented mode surface at 26.1.0:

- Dual Signal mode requires Java Agent 25.6.0 or higher. Hybrid mode requires
  22.3.0 or higher. The 25.10.0 page stated a single "25.9 or later" baseline for
  both; 26.1.0 replaced that with these per-mode minimums.
- Dual Signal accepts either `-Dagent.deployment.mode=dual` or
  `-Dappdynamics.opentelemetry.enabled=true`. This skill renders the former.
- Hybrid mode uses `-Dappdynamics.opentelemetry.enabled=true` on Java Agent
  22.3.0 through 25.4.0, and `-Dagent.deployment.mode=hybrid` from 25.6.0.
- 26.1.0 documents two modes. "OpenTelemetry Only Mode", which the 25.10.0 page
  listed as a third mode that does not register with the Controller, is gone.
  Workloads that should emit OpenTelemetry without Controller registration belong
  in `splunk-observability-k8s-auto-instrumentation-setup`, not here.

Operational contract:

- Render first, then `--apply preflight`, then `--apply collector`, then
  `--apply java`, or use `--apply all` for the collector-first sequence.
- Java Dual Signal configuration uses persistent startup files, not dynamic
  attach, for production apply.
- The default collector endpoint is `http://127.0.0.1:4318` with
  `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`.
- Rollback restores backed-up files and restarts only affected gated services.
