# Splunk Observability Cloud — GCP Integration Reference

Operator reference for the
[`splunk-observability-gcp-integration`](SKILL.md) skill.

## REST API

- Endpoint: `https://api.<realm>.observability.splunkcloud.com/v2/integration[/{id}]`
- Auth header: `X-SF-Token`. Read-only `GET` accepts an API-scoped organization
  token or any session/User API access token. `POST`, exact-ID `PUT`, and
  exact-ID `DELETE` require a session/User API access token associated with an
  administrator.
- Successful `GET`, `POST`, `PUT`, and `DELETE` responses are HTTP 200. DELETE
  has no response body; exact-ID GET for a missing integration is HTTP 200 with
  an empty body.
- Collection GET uses the official `count` plus `results` envelope with
  `limit`/`offset` pagination and a documented 10,000-object cap. Name or
  duplicate decisions fail closed at or above that cap.
- Integration `type` discriminator: **`GCP`** (exact case)
- WIF source of truth for this skill: the official Splunk-generated
  `gcp_wif_config.json` and the REST fields documented below.

Authoritative sources: [Splunk Integrations API](https://dev.splunk.com/observability/reference/api/integrations/latest),
[GCP integration guide](https://dev.splunk.com/observability/docs/integrations/gcp_integration_overview/),
the [SignalFx Go integration model](https://pkg.go.dev/github.com/signalfx/signalfx-go/integration),
and the official [SignalFx Terraform GCP integration resource](https://registry.terraform.io/providers/splunk-terraform/signalfx/latest/docs/resources/gcp_integration).

## Canonical field set

| Spec field | Wire JSON name | Type | Notes |
|-----------|---------------|------|-------|
| `integration_name` | `name` | string | required |
| `authentication.mode` → `SERVICE_ACCOUNT_KEY` | `authMethod` | enum | `SERVICE_ACCOUNT_KEY` or `WORKLOAD_IDENTITY_FEDERATION` |
| `authentication.project_service_keys[].project_id` | `projectServiceKeys[].projectId` | string | required when SA key mode |
| `authentication.project_service_keys[].key_file` (content) | `projectServiceKeys[].projectKey` | string | **write-only; not returned on GET** |
| `authentication.workload_identity_federation.config_file` (complete JSON document) | `workloadIdentityFederationConfig` | string | official generated `gcp_wif_config.json`, compact/stringified immediately before WIF apply |
| `projects.sync_mode` | `projects.syncMode` | enum | `ALL_REACHABLE` or `SELECTED` |
| `projects.selected_project_ids` | `projects.selectedProjectIds` | []string | emitted only for `SELECTED` |
| `connection.poll_rate_seconds` × 1000 | `pollRate` | int64 (ms) | 60000–600000 ms |
| `connection.use_metric_source_project_for_quota` | `useMetricSourceProjectForQuota` | bool | WARN: requires extra IAM role |
| `connection.import_gcp_metrics` | `importGCPMetrics` | bool | default true |
| `services.explicit` | `services` | []string | 32-entry enum |
| `custom_metric_type_domains` | `customMetricTypeDomains` | []string | custom Cloud Monitoring prefixes |
| `exclude_gce_instances_with_labels` | `excludeGCEInstancesWithLabels` | []string | label keys without the `gcp_label_` prefix |
| (response compatibility) | `includeList` | []string | retained exactly for drift review |
| (deprecated response compatibility) | `whitelist` | []string | retained exactly for drift review |
| `named_token` | `namedToken` | string | ForceNew in Terraform |
| (enabled) | `enabled` | bool | explicit Boolean required on every write |

Common read-only fields retained for review and stripped on PUT are `created`,
`lastUpdated`, `creator`, `lastUpdatedBy`, `createdByName`,
`lastUpdatedByName`, and `id`. Timestamps are exact JSON integers; creator IDs
are strings; display names may be strings or null. Captured compatibility
responses also contain bounded string `workloadIdentityPoolId` and
`workloadIdentityProviderId`; they remain reviewed but are stripped from PUT.
`wifSplunkIdentity` is accepted as a bounded string or string-to-string map and
is also stripped. `projectServiceKeys` response entries require unique,
non-empty `projectId` values and must omit `projectKey`; a returned
`projectKey` is a protocol violation, not a redaction placeholder.

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

`projectKey` is write-only and is not returned by GET. The skill compares
SHA-256 hashes of local key files to
`state/credential-hashes.json` for drift detection. Hash mismatches prompt the
operator to re-apply credentials.

For service-account multi-project mode, every regular mode-600 JSON file is
strictly parsed once and mapped by its `project_id`, independent of file order.
Required fields are `type`, `project_id`, `private_key_id`, multiline-capable
`private_key`, and `client_email`. Missing, extra, duplicate, or mismatched
project coverage fails before a live read or mutation; one key is never reused
for another project.

For WIF, no Service Account key file is required. The skill instead requires
Splunk's official generated file named `gcp_wif_config.json`. It must be an
unchanged, non-empty JSON object in a regular mode-600 file. The client treats
its schema as opaque and sends the entire document as compact JSON encoded in
the string-valued `workloadIdentityFederationConfig` field. There is no realm
principal map and the skill does not construct pool, provider, issuer, or
principal values. Credential contents never enter plans, journals, logs, or
terminal output; validated file paths may appear in diagnostic errors.

When a live response exposes singular `workloadIdentityFederationConfig`, the
client strict-parses it and persists only a canonical semantic SHA-256
observation. A disable plan binds that observation to both the exact local file
bytes and the local canonical JSON digest. After both apply preflight reads
match, the PUT preserves the exact raw live string so whitespace or member
ordering is not rewritten. Placeholder, missing, mismatched, or malformed WIF
observations fail closed. Deprecated plural
`workloadIdentityFederationConfigs` is projected as unique project IDs plus
per-config digests for delete review; disable refuses it because one singular
file cannot reconstruct it exactly.

## Projects compatibility

New renders and every POST/PUT emit only `ALL_REACHABLE`, or `SELECTED` with
`selectedProjectIds`. `selectedProjectIds` is omitted for `ALL_REACHABLE`.
Legacy client input `ALL` plus `projectIds` is normalized only for ordinary new
provisioning writes. A live legacy shape is preserved exactly for delete review,
while rollback disable refuses it rather than silently migrating it. Mixed
legacy/current fields fail closed and new writes never emit legacy fields.

For rollback, missing or null `authMethod` may select service-account credential
validation, but the field remains missing or null in the enabled-only PUT; it
is never synthesized. Service-account live state may use `projectServiceKeys`
without a `projects` object. WIF requires the current projects contract.
Mixed WIF/service-account state, deprecated plural WIF state, and legacy
`projectIds` all block disable before claim or mutation.

## Reviewed rollback contract

1. `--discover` performs a read-only, fully paginated GET and privately writes
   `state/current-state.json`. The snapshot is bounded to 4 MiB and has the
   exact schema `schema_version`, `provider`, `realm`, `captured_at`, `count`,
   and `results`.
2. Offline `--rollback disable|delete` requires the snapshot, exact immutable
   server ID, and exact expected name. It selects exactly one `GCP` result and
   writes a bounded 64 KiB mode-600 plan containing a random UUID4 `plan_id`,
   reviewed action/identity/enabled state, complete sanitized `reviewed_state`,
   its SHA-256 fingerprint, and—only for disable—secret-free auth method and
   credential SHA-256 bindings. Plans preserve exact schema-safe names.
3. Mutation requires `--apply`, `--plan-hash SHA256`, and exactly one matching
   action-bound acknowledgement: `--accept-disable-integration ID` or
   `--accept-delete-integration ID`. Bare `--rollback` cannot apply. Disable
   requires reviewed `enabled: true`; delete may intentionally review either
   Boolean state and rejects all credential inputs.
4. Before a mutation, the client validates and retains credential material in
   memory, acquires a canonical per-user provider/realm/ID lock, re-lists the
   complete collection to prove name uniqueness, and performs two exact-ID
   reads. Both reads must match the reviewed type, ID, name, Boolean enabled
   state, and complete reviewed fingerprint. Only then does the client create
   an exclusive durable consumed marker in the canonical lock root, followed by
   the plan-adjacent receipt and attempt journal. Failure to write either latter
   record aborts before mutation.
5. PUT or DELETE is dispatched exactly once and is never retried. Ambiguous
   status, read, decode, timeout, or incomplete-response failures are reconciled
   with exact-ID GET and still require operator resolution. Disable must observe
   `enabled: false` twice and an unchanged non-enabled configuration
   fingerprint. Delete requires HTTP 200 with zero response bytes and then two
   consecutive HTTP-200 empty exact-ID GETs. Every attempted plan remains
   burned; recovery requires read-only reconciliation and a newly rendered
   plan.

Disable plans additionally require a supported `authMethod` (with the
documented missing/null service-account compatibility) and a `pollRate` from
60000 through 600000 milliseconds. Delete plans may review a well-typed future
enum or legacy interval because delete does not reconstruct an authentication
payload.

All state and lock files are owned regular mode-600 files with symlink-safe
directory traversal. Upsert also serializes its name decision locally and
locks an existing immutable ID. Splunk documents no conditional revision or
ETag operation, so these local controls and repeated reads narrow but cannot
eliminate changes made concurrently from another host. Never recommend delete
when disable is blocked.

## Conflict matrix

| Rule | Enforcement |
|------|------------|
| `mode=service_account_key` + `workload_identity_federation` block populated | FAIL |
| `mode=workload_identity_federation` + `project_service_keys` populated | FAIL |
| WIF mode without official `gcp_wif_config.json`, with corrupt JSON, a renamed/symlinked file, or permissions other than 600 | FAIL before live mutation |
| Legacy spec `pool_id`, `provider_id`, or `splunk_principal` fields | FAIL; the generated WIF document is opaque |
| `services.explicit` non-empty + `services.mode=all_built_in` | FAIL |
| `project_service_keys` empty when `mode=service_account_key` | FAIL |
| `projects.sync_mode=SELECTED` without IDs, or `ALL_REACHABLE` with IDs | FAIL |
| `poll_rate_seconds` outside 60–600 | FAIL |
| `use_metric_source_project_for_quota=true` | WARN — requires `roles/serviceusage.serviceUsageConsumer` |
| `named_token` differs from live value | WARN (ForceNew — integration will be recreated) |

## Terraform

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

  poll_rate = 300  # seconds (60-600; default 300)

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

Pin the reviewed provider version according to your environment. The upstream
[SignalFx Terraform GCP integration resource](https://registry.terraform.io/providers/splunk-terraform/signalfx/latest/docs/resources/gcp_integration)
supports WIF and projects arguments. This skill intentionally generates WIF
through its reviewed REST path and does not currently generate a Terraform WIF
resource.

The Terraform provider accepts `poll_rate` in **seconds** (60–600, default 300)
and converts it to the REST API's millisecond `pollRate` wire field.

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

The REST path is authoritative for WIF in this skill. The upstream provider
supports WIF/projects, but this skill does not currently emit its WIF resource
or gcloud pool/provider scripts.

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
