# Machine Agent OTel Collector Reference

Primary sources:

- https://help.splunk.com/en/appdynamics-on-premises/infrastructure-visibility/26.6.0/machine-agent/combined-agent-for-infrastructure-visibility
- https://help.splunk.com/en/appdynamics-on-premises/infrastructure-visibility/26.6.0/machine-agent/configure-the-machine-agent/access-machine-agent-docker-images
- https://help.splunk.com/en/appdynamics-on-premises/infrastructure-visibility/26.6.0/machine-agent/install-the-machine-agent/windows-install-using-zip-with-bundled-jre
- https://help.splunk.com/en/appdynamics-on-premises/virtual-appliance-self-hosted/25.7.0/splunk-appdynamics-for-opentelemetry/configure-the-opentelemetry-collector/collector-configuration-sample

Operational contract:

- `--apply preflight` validates target paths, install type, receiver ports, and
  destination file references without mutation.
- `--apply collector` writes the collector config, restarts the collector, and
  validates local OTLP ports and exporter health checks.
- Rollback restores the previous collector config from `backup-manifest.json`
  and restarts only the affected collector service or container.
