# Splunk Observability Cloud — GCP Integration Reference

Operator reference for the
[`splunk-observability-gcp-integration`](SKILL.md) skill.

## REST API

- Endpoint: `https://api.<realm>.observability.splunkcloud.com/v2/integration[/{id}]`
- Auth: `X-SF-Token: <admin user API access token>`
- `POST` → create (201), `GET` → read (200), `PUT` → update (200), `DELETE` → (204)
- Integration `type` discriminator: **`GCP`** (exact case)
- WIF source of truth: the official Splunk-generated `gcp_wif_config.json` and
  the REST fields documented below. The Terraform provider is referenced only
  for the separate Service Account key workflow.

## Canonical field set

| Spec field | Wire JSON name | Type | Notes |
|-----------|---------------|------|-------|
| `integration_name` | `name` | string | required |
| `authentication.mode` → `SERVICE_ACCOUNT_KEY` | `authMethod` | enum | `SERVICE_ACCOUNT_KEY` or `WORKLOAD_IDENTITY_FEDERATION` |
| `authentication.project_service_keys[].project_id` | `projectServiceKeys[].projectId` | string | required when SA key mode |
| `authentication.project_service_keys[].key_file` (content) | `projectServiceKeys[].projectKey` | string | **write-only; redacted on GET** |
| `authentication.workload_identity_federation.config_file` (complete JSON document) | `workloadIdentityFederationConfig` | string | official generated `gcp_wif_config.json`, compact/stringified immediately before WIF apply |
| `projects.sync_mode` | `projects.syncMode` | enum | `ALL` or `SELECTED` |
| `projects.selected_project_ids` | `projects.projectIds` | []string | required only for `SELECTED` |
| `connection.poll_rate_seconds` × 1000 | `pollRate` | int64 (ms) | 60000–600000 ms |
| `connection.use_metric_source_project_for_quota` | `useMetricSourceProjectForQuota` | bool | WARN: requires extra IAM role |
| `connection.import_gcp_metrics` | `importGCPMetrics` | bool | default true |
| `services.explicit` | `services` | []string | 32-entry enum |
| `custom_metric_type_domains` | `customMetricTypeDomains` | []string | custom Cloud Monitoring prefixes |
| `exclude_gce_instances_with_labels` | `excludeGceInstancesWithLabels` | []string | label key=value pairs |
| `named_token` | `namedToken` | string | ForceNew in Terraform |
| (enabled) | `enabled` | bool | set false on create, true on update |

Read-only fields (server-populated, stripped on PUT): `created`, `lastUpdated`,
`creator`, `lastUpdatedBy`, `id`.

## `authMethod` values

| Value | Description |
|-------|-------------|
| `SERVICE_ACCOUNT_KEY` | GCP Service Account JSON key per project (default) |
| `WORKLOAD_IDENTITY_FEDERATION` | WIF using the official generated `gcp_wif_config.json` document |

## Services enum (32 entries)

See `references/services-enum.json` for the full list. Notable entries:

```
appengine
bigquery
bigtable
cloudfunctions
cloudsql
compute
container            (GKE)
dataflow
pubsub
run                  (Cloud Run)
spanner
storage
```

The wire accepts any string in the 32-entry enum. When `services` is omitted
from the payload, all built-in services are monitored.

## Credential handling

`projectKey` is **write-only; redacted on GET** by the Splunk API — it is set
but not returned. The skill compares SHA-256 hashes of local key files to
`state/credential-hashes.json` for drift detection. Hash mismatches prompt the
operator to re-apply credentials.

For service-account multi-project mode, pass one repeated `--key-file` per
`project_service_keys` entry in spec order. A missing or mismatched count fails
before the API call; one key is never silently reused for every project.

For WIF, no Service Account key file is required. The skill instead requires
Splunk's official generated file named `gcp_wif_config.json`. It must be an
unchanged, non-empty JSON object in a regular mode-600 file. The client treats
its schema as opaque and sends the entire document as compact JSON encoded in
the string-valued `workloadIdentityFederationConfig` field. There is no realm
principal map and the skill does not construct pool, provider, issuer, or
principal values.

## Conflict matrix

| Rule | Enforcement |
|------|------------|
| `mode=service_account_key` + `workload_identity_federation` block populated | FAIL |
| `mode=workload_identity_federation` + `project_service_keys` populated | FAIL |
| WIF mode without official `gcp_wif_config.json`, with corrupt JSON, a renamed/symlinked file, or permissions other than 600 | FAIL before live mutation |
| Legacy `pool_id`, `provider_id`, or `splunk_principal` fields | FAIL; unsupported fabricated contract |
| `services.explicit` non-empty + `services.mode=all_built_in` | FAIL |
| `project_service_keys` empty when `mode=service_account_key` | FAIL |
| `projects.sync_mode=SELECTED` without project IDs, or `ALL` with project IDs | FAIL |
| `poll_rate_seconds` outside 60–600 | FAIL |
| `use_metric_source_project_for_quota=true` | WARN — requires `roles/serviceusage.serviceUsageConsumer` |
| `named_token` differs from live value | WARN (ForceNew — integration will be recreated) |

## Terraform (Service Account key mode only)

```hcl
terraform {
  required_providers {
    signalfx = {
      source  = "splunk-terraform/signalfx"
      version = "~> 9.0"
    }
  }
}

resource "signalfx_gcp_integration" "this" {
  name    = var.integration_name
  enabled = true

  poll_rate = 300000  # milliseconds

  project_service_keys {
    project_id  = var.project_id
    project_key = var.project_key  # sensitive; deliver via TF_VAR or vault
  }

  services = [
    "compute",
    "container",
    "pubsub",
    "storage",
  ]
}
```

Pin the reviewed provider version according to your environment.

Note: `poll_rate` in the Terraform resource is in **milliseconds** (unlike Azure
where it is seconds). Check provider docs for the exact version you use.

## GCloud CLI Service Account creation

```bash
# Create the SA
gcloud iam service-accounts create splunk-observability-o11y \
  --display-name "Splunk Observability O11y" \
  --project "${GCP_PROJECT_ID}"

# Grant the Monitoring Viewer role
gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member="serviceAccount:splunk-observability-o11y@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/monitoring.viewer"

# Grant the Compute Viewer role (resource discovery)
gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member="serviceAccount:splunk-observability-o11y@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/compute.viewer"

# Download the key
gcloud iam service-accounts keys create /tmp/splunk-gcp-sa-key.json \
  --iam-account="splunk-observability-o11y@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
chmod 600 /tmp/splunk-gcp-sa-key.json
```

Required IAM roles per project:
- `roles/monitoring.viewer` — read Cloud Monitoring metrics
- `roles/compute.viewer` — GCE resource discovery
- `roles/serviceusage.serviceUsageConsumer` — only if `use_metric_source_project_for_quota=true`

## WIF configuration

Do not use a generic gcloud recipe or a realm-to-principal lookup to create the
Splunk side of this trust. Obtain the official `gcp_wif_config.json` from the
supported Splunk integration workflow, store it unchanged with mode 600, and
pass only its path:

```bash
chmod 600 /secure/path/gcp_wif_config.json
bash skills/splunk-observability-gcp-integration/scripts/setup.sh \
  --apply --spec my-wif-spec.yaml --realm us1 \
  --token-file /secure/path/splunk_o11y_token \
  --wif-config-file /secure/path/gcp_wif_config.json
```

The REST path is authoritative for WIF in this skill. No Terraform resource or
gcloud pool/provider script is emitted for WIF because those field mappings are
not part of the verified contract represented here.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| No metrics in O11y | Wrong SA key or missing roles | Re-apply with fresh key file; verify IAM roles |
| `projectKey` drift | SA key rotated | Hash mismatch detected by doctor; re-apply |
| Services empty (explicit mode) | No services listed | Add services or set mode=all_built_in |
| `namedToken` changed | ForceNew: integration recreated | Expected; old integration stops flowing data immediately |
| Rate limited | Poll rate too fast | Increase `poll_rate_seconds` (300+ recommended) |
| WIF auth failure | Missing, modified, malformed, insecure, or stale generated config | Download a fresh official `gcp_wif_config.json`, keep it unchanged with mode 600, and re-apply |
| `use_metric_source_project_for_quota` 403 | Missing `roles/serviceusage.serviceUsageConsumer` | Add the role or set the flag to false |
| Custom metric not appearing | Not in `customMetricTypeDomains` | Add the metric type prefix |
