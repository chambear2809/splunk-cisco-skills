# Regions and Realms

## Realm <-> AWS STS region mapping

| Realm | AWS STS region | Region name |
|-------|----------------|-------------|
| `us0` | `us-east-1` | US East (N. Virginia) |
| `us1` | `us-west-2` | US West (Oregon) |
| `us2` | `us-east-1` | US East (N. Virginia) |
| `us3` | `us-west-2` | US West (Oregon) |
| `eu0` | `eu-west-1` | Europe (Ireland) |
| `eu1` | `eu-central-1` | Europe (Frankfurt) |
| `eu2` | `eu-west-2` | Europe (London) |
| `au0` | `ap-southeast-2` | Asia Pacific (Sydney) |
| `jp0` | `ap-northeast-1` | Asia Pacific (Tokyo) |
| `sg0` | `ap-southeast-1` | Asia Pacific (Singapore) |

The renderer enforces these are the only AWS-hosted realms. The GCP-hosted
`us2-gcp` realm has no AWS STS region mapping and is rejected.

## Supported AWS regions (4 categories)

### Regular (16; available by default)

`ap-northeast-1`, `ap-northeast-2`, `ap-northeast-3`, `ap-south-1`,
`ap-southeast-1`, `ap-southeast-2`, `ca-central-1`, `eu-central-1`,
`eu-north-1`, `eu-west-1`, `eu-west-2`, `eu-west-3`, `sa-east-1`,
`us-east-1`, `us-east-2`, `us-west-1`, `us-west-2`.

### Optional (10; must be activated AWS-side first)

`af-south-1`, `ap-east-1`, `ap-south-2`, `ap-southeast-3`, `ap-southeast-4`,
`eu-central-2`, `eu-south-1`, `eu-south-2`, `me-central-1`, `me-south-1`.

### GovCloud (2; force `authentication.mode: security_token`)

`us-gov-east-1`, `us-gov-west-1`.

GovCloud caveat: AWS does NOT provide FIPS-compliant tag-retrieval endpoints,
so do not include sensitive data in tags. Splunk Observability prefixes tags
with `aws_tag_` regardless.

### China (2; force `authentication.mode: security_token`)

`cn-north-1`, `cn-northwest-1`.

## `regions: []` is rejected

The canonical Pulumi/Terraform schema rejects an empty `regions` list and
Splunk highly discourages it because new AWS regions auto-onboard and inflate
cost. The renderer FAILs render with no override flag. Enumerate explicitly.

## FedRAMP

Splunk Observability Cloud is **NOT yet FedRAMP-authorized** as of early
2026 (Splunk Cloud Platform is FedRAMP Moderate; Splunk Observability is on
the roadmap). FedRAMP / IL5 customers cannot use this skill against a FedRAMP
environment until Splunk publishes authorization. See:
https://help.splunk.com/en/splunk-observability-cloud/fedramp-support/fedramp-support-for-splunk-observability-cloud
