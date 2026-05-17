# Splunk Edge Processor Reference

## Research Basis

- Splunk Edge Processor is supported on **both** Splunk Cloud Platform tenants
  and Splunk Enterprise 10.0+ data management nodes.
- An EP instance is `splunk-edge` running as a Linux process or systemd
  service. The control plane provides token-bearing install commands the
  operator copies onto the host.
- Pipelines use SPL2 with `$pipeline` blocks. Partition definition uses
  Keep / Remove on a field condition. Shared templates and compatibility lint
  come from `splunk-spl2-pipeline-kit` using the `edgeProcessor` profile.
- Source types ingest data via:
  - **Splunk forwarder S2S** receiver (port configurable; usually 9997).
  - **HTTP Event Collector** receiver (with HEC token authentication).
  - **Syslog** receiver (TCP/UDP).
- Destinations:
  - **Splunk platform S2S** — host:port + index routing rules
    (Default / Specify-for-no-index / Specify-for-all).
  - **Splunk platform HEC** — HEC URL + token (file-based).
  - **Amazon S3** — bucket + prefix + auth (IAM role for EC2-hosted EP, or
    access-key/secret pair via file-based secret).
  - **syslog** — TCP/UDP target + framing.
- Default destination is REQUIRED — without one, unprocessed data is dropped.
- TLS / mTLS for data sources requires PEM certs (server cert/key/CA, plus
  client cert for mTLS).
- FIPS-compliant mode is supported for non-containerized Edge Processor
  instances and is not supported for containerized EP deployments.
- Privileged-port handling: ports < 1024 require root or capability grant.
- Multi-instance scale-out + DNS-driven outputs.conf is the documented
  best-practice for forwarders sending to many EPs.

Official references:

- Set up an Edge Processor (Cloud):
  <https://docs.splunk.com/Documentation/SplunkCloud/9.3.2408/EdgeProcessor/CreateNode>
- Set up an Edge Processor (Enterprise):
  <https://help.splunk.com/en/splunk-enterprise/process-data-at-the-edge/use-edge-processors-for-splunk-enterprise/10.2/administer-edge-processors/set-up-an-edge-processor>
- Set up an Edge Processor in a Docker container:
  <https://help.splunk.com/en/data-management/process-data-at-the-edge/use-edge-processors-for-splunk-cloud-platform/administer-edge-processors/set-up-an-edge-processor-in-a-docker-container>
- Create pipelines for Edge Processors:
  <https://help.splunk.com/en/data-management/transform-and-route-data/use-edge-processors-for-splunk-cloud-platform/9.2.2406/working-with-pipelines/create-pipelines-for-edge-processors>
- Edge Processor pipeline syntax:
  <https://help.splunk.com/en/data-management/transform-and-route-data/use-edge-processors-for-splunk-cloud-platform/9.2.2406/working-with-pipelines/edge-processor-pipeline-syntax>
- Add or manage destinations:
  <https://help.splunk.com/en/data-management/process-data-at-the-edge/use-edge-processors-for-splunk-cloud-platform/administer-edge-processors>
- Send data from Edge Processors to Amazon S3:
  <https://help.splunk.com/en/data-management/transform-and-route-data/use-edge-processors-for-splunk-enterprise/10.2/send-data-out-from-edge-processors/send-data-from-edge-processors-to-amazon-s3>
- Get syslog data into an Edge Processor:
  <https://docs.splunk.com/Documentation/SplunkCloud/latest/EdgeProcessor/SyslogSource>
- Configure HEC token authentication in the Edge Processor service:
  <https://help.splunk.com/en/data-management/collect-http-event-data/send-hec-data-to-and-from-edge-processor/send-data-to-edge-processor-with-hec/configure-hec-token-authentication-in-the-edge-processor-service>
- Verify your Edge Processor and pipeline configurations:
  <https://help.splunk.com/en/splunk-cloud-platform/process-data-at-the-edge/use-edge-processors-for-splunk-cloud-platform/10.2.2510/monitor-system-health-and-activity/verify-your-edge-processor-and-pipeline-configurations>

## Pipeline Templates

The skill renders starter SPL2 pipeline templates under `pipelines/templates/`
by reading the shared `splunk-spl2-pipeline-kit` `edgeProcessor` catalog. The
  catalog includes filter, route, redact, hash, sample, lookup, JSON extraction,
  timestamp, OCSF, stats, S3 archive, and compatibility-lint starters. If the
  shared kit is unavailable, the renderer falls back to the legacy
  filter/mask/sample/route starters.

Fork-and-edit any of these into your own `pipelines/<name>.spl2` source file
and reference them in `--ep-pipelines` specs.

Run `splunk-spl2-pipeline-kit --phase lint --profile edgeProcessor` against
edited pipelines before previewing them in the EP UI. The lint pass checks for
required `$pipeline`, `from $source`, `into $destination`, PCRE2 named capture
style, SPL1-shaped conversion gaps, and Ingest Processor-only constructs such
as `logs_to_metrics` and `decrypt`. Edge Processor `stats` is supported and
newer EP versions add state-window behavior that operators must review.

## Current Release Guardrails

- FIPS mode: non-containerized Edge Processor only.
- Health metric rename: prefer `export_destination_errors_total`; older
  `exporter_error_count` references are stale.
- Source type sync: review plans over 4000 source types; current Cloud EP docs
  increased the sync limit from 1000 to 4000.
- S2S destinations: use bulk indexer configuration for large indexer lists
  where available.
- S3 destinations: review Parquet and gzip compression settings.

## systemd Unit

The rendered `host/<host>/install-with-systemd.sh` script writes a
`/etc/systemd/system/splunk-edge.service` unit with:

```
[Unit]
Description=Splunk Edge Processor
After=network.target

[Service]
Type=simple
User=<service_user>
Group=<service_cgroup>
WorkingDirectory=<install_dir>/splunk-edge
ExecStart=<install_dir>/splunk-edge/bin/splunk-edge run
Restart=on-failure
KillMode=mixed

[Install]
WantedBy=multi-user.target
```

`KillMode=mixed` ensures graceful shutdown on `systemctl restart`.

## Sizing Preflight

The skill compares `--ep-target-daily-gb` against documented per-instance
soft limits and warns when planned data volume exceeds capacity.

| Daily volume | Recommended instances |
|--------------|-----------------------|
| <= 100 GB    | 1                     |
| 100-500 GB   | 2-3                   |
| 500-1500 GB  | 3-5                   |
| > 1500 GB    | contact Splunk Sizing |

These are operational guidelines; actual capacity depends on pipeline
complexity (mask / route / regex), TLS overhead, and destination latency.

## ACS Allowlist Hand-off

When the destination type is `s2s` or `hec` and the EP instance ships data to
a Splunk Cloud destination, the EP instances' egress IPs must be on the
matching ACS allowlist. The skill emits a stub at
`handoffs/acs-allowlist.json` listing every EP instance host (the operator
expands each to its `/32` egress IP) targeting the appropriate features. The
operator promotes the stub into a `splunk-cloud-acs-allowlist-setup` plan and
applies it before the destination becomes reachable.

## Out of Scope

- Live automated SPL-to-SPL2 conversion (use Splunk's in-product tool; the
  shared kit renders static review warnings only).
- Multi-tenant org management on Splunk Cloud.
- Kafka and Azure Event Hubs destinations (not yet in the public EP catalog).
- EP control-plane RBAC management.
- Containerized FIPS mode.
