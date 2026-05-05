# AWS PrivateLink

Splunk Observability Cloud supports PrivateLink for ingest, API, stream, and
backfill endpoints. **The current Splunk PrivateLink doc (last updated
September 2024) uses the legacy `signalfx.com` domain**; we default to it and
let the operator opt into the new `observability.splunkcloud.com` PrivateLink
hostnames via `--privatelink-domain new` (gated until Splunk publishes
confirmation post-2026-03-24 domain transition).

## Endpoint URL patterns

### Legacy (default, matches current published doc)

| Type | Pattern | Example (us0) |
|------|---------|---------------|
| `ingest` (metrics) | `private-ingest.<realm>.signalfx.com` | `private-ingest.us0.signalfx.com` |
| `ingest` (traces) | `private-ingest.<realm>.signalfx.com/v2/trace` | `private-ingest.us0.signalfx.com/v2/trace` |
| `api` | `http://private-api.<realm>.signalfx.com` | `http://private-api.us0.signalfx.com` |
| `stream` | `private-stream.<realm>.signalfx.com` | `private-stream.us0.signalfx.com` |

### New (gated behind `--privatelink-domain new`)

Replace `signalfx.com` with `observability.splunkcloud.com` in each pattern.

## Cross-region scenario

PrivateLink only works within ONE AWS region. For cross-region workloads:

- Workload region: `ap-south-1` (example)
- Realm STS region: `us-east-1` (us0)

Steps:

1. Create a VPC in the destination region (`us-east-1`) if not already
   present.
2. Use AWS VPC peering to peer the source VPC (`ap-south-1`) to the
   destination VPC (`us-east-1`).
3. Activate AWS PrivateLink in the destination VPC (`us-east-1`) using the
   per-realm VPC endpoint service name.

## VPC endpoint service names (per-realm)

The current Splunk doc enumerates per-realm VPCE service names of the form
`com.amazonaws.vpce.<aws-region>.vpce-svc-...` for ingest / api / stream.
Splunk publishes the table at:
https://help.splunk.com/en/splunk-observability-cloud/manage-data/private-connectivity/private-connectivity-using-aws-privatelink

Override per-realm via the spec when Splunk republishes:

```yaml
private_link:
  enable: true
  endpoint_types: [ingest, api, stream]
  service_name_overrides:
    ingest: com.amazonaws.vpce.us-east-1.vpce-svc-FROM_SPLUNK_DOC
    api: com.amazonaws.vpce.us-east-1.vpce-svc-FROM_SPLUNK_DOC
    stream: com.amazonaws.vpce.us-east-1.vpce-svc-FROM_SPLUNK_DOC
```

## AZ availability

PrivateLink is not present in every AZ within every region. Verify the AZs
in your destination VPC before creating the VPC endpoint.

## Sources

- [Private Connectivity using AWS PrivateLink](https://help.splunk.com/en/splunk-observability-cloud/manage-data/private-connectivity/private-connectivity-using-aws-privatelink)
- [Domain transition guide](https://help.splunk.com/en/splunk-observability-cloud/reference/splunk-observability-cloud-domain-transition-guide)
