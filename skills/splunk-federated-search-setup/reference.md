# Splunk Federated Search Reference

## Research Basis

This skill follows current Splunk Federated Search documentation and
configuration references for Splunk Enterprise 10.2 and Splunk Cloud Platform
10.0.2503:

- `federated.conf` provider stanza: `provider://<name>` with `type`,
  `hostPort`, `serviceAccount`, `password`, `mode`, `appContext`,
  `useFSHKnowledgeObjects`, `disabled`.
- `[general]` stanza: `max_preview_generation_duration` and
  `max_preview_generation_inputcount`.
- Federated index stanza: `federated:<index_name>` with `federated.provider`,
  `federated.dataset` (`<type>:<dataset_name>`), `disabled`.
- REST endpoints:
  - `/services/data/federated/settings/general` — global enable/disable.
  - `/services/data/federated/provider` — provider CRUD (FSS2S **and** FSS3).
  - `/services/data/federated/index` — federated index CRUD.
  - Each provider entity supports `/_reload`, `/enable`, and `/disable`.

## Provider Types

Splunk Federated Search ships two provider types:

| `type` | Product | Available on | Configuration surface |
|---|---|---|---|
| `splunk` | Federated Search for Splunk (FSS2S) | Splunk Enterprise + Splunk Cloud | `federated.conf` and REST |
| `aws_s3` | Federated Search for Amazon S3 (FSS3) | Splunk Cloud Platform only | REST + Splunk Web only |

FSS3 cannot be configured through `federated.conf`. Splunk Cloud admins must
POST FSS3 provider definitions to `/services/data/federated/provider` (the
admin user must hold `admin_all_objects`). This skill renders one JSON payload
per FSS3 provider under `aws-s3-providers/<name>.json` plus an AWS
prerequisites README.

## FSS2S Settings (`type = splunk`)

| Setting | Required | Notes |
|---|---|---|
| `name` | yes | Provider name (alphanumeric, underscore, hyphen). |
| `host_port` | yes | Remote search head `host:management_port`. |
| `service_account` | yes | Username on the remote SH. The remote role must read the mapped datasets. |
| `password_file` | yes | Local-only file the apply scripts read; never embedded in rendered files. |
| `mode` | yes | `standard` or `transparent`. |
| `app_context` | standard only | Defaults to `search`. Multiple standard providers can target the same remote host with different `app_context`. Transparent providers ignore this field. |
| `useFSHKnowledgeObjects` | derived | Splunk forces `0` for standard, `1` for transparent regardless of operator input. The renderer emits the documented value. |
| `disabled` | optional | Defaults to false. |

## FSS3 Settings (`type = aws_s3`)

| Setting | Required | Notes |
|---|---|---|
| `name` | yes | Alphanumeric, underscore, hyphen. |
| `aws_account_id` | yes | 12-digit AWS account ID; quote in YAML. |
| `aws_region` | yes | Must match the Splunk Cloud deployment region. |
| `database` | yes | AWS Glue database name (lowercase letters, digits, underscore, hyphen). |
| `data_catalog` | yes | AWS Glue Data Catalog ARN: `arn:aws:glue:<region>:<account>:catalog`. |
| `aws_glue_tables_allowlist` | yes | One or more Glue table names; each must reference a path in `aws_s3_paths_allowlist`. |
| `aws_s3_paths_allowlist` | yes | One or more `s3://...` paths; only end in folders, not file objects. |
| `aws_kms_keys_arn_allowlist` | optional | Required only when S3 buckets or Glue metadata are encrypted with customer-managed KMS keys. |
| `disabled` | optional | Defaults to false. |

The renderer's AWS prerequisites README documents the Splunk Web "Generate
policy" workflow that produces the Glue Data Catalog resource policy, S3
bucket policies, and KMS key policies the AWS administrator must attach
before the FSS3 provider works.

## Mode Selection

Choose **standard mode** when you want explicit remote datasets represented
as local federated indexes. Searches reference the federated index:

```spl
index=federated:remote_main
```

Standard mode supports all FSS2S deployment combinations:

| Local | Remote | Standard mode | Transparent mode |
|---|---|---|---|
| Splunk Enterprise (≥ 8.2) | Splunk Enterprise (≥ 8.2) | yes | yes (≥ 9.0) |
| Splunk Cloud (≥ 8.1.2103) | Splunk Cloud (≥ 8.1.2103) | yes | yes (≥ 8.2.2107) |
| Splunk Enterprise (≥ 8.2) | Splunk Cloud (≥ 8.2.2104) | yes | yes |
| Splunk Cloud (≥ 8.2.2203) | Splunk Enterprise (≥ 9.0.0) | yes | **NOT supported** |

Choose **transparent mode** for migration-style hybrid search. Transparent
providers do **not** use federated indexes and have command restrictions
(see [About Federated Search for Splunk](https://help.splunk.com/en/?resourceId=Splunk_FederatedSearch_fss2sAbout)).

The renderer enforces these documented restrictions:

- A federated index cannot reference a transparent-mode provider.
- Multiple transparent-mode providers cannot share a remote `host_port`.
- Mixed standard+transparent providers cannot share a remote `host_port`.
- Multiple standard-mode providers can share a remote `host_port` only
  when they have distinct `app_context` values.

## Standard-Mode Knowledge Object Coordination

Standard-mode federated searches blend FSH knowledge objects with the remote
SH's knowledge objects. If federated searches will reference any of the
following, install matching definitions on every remote SH (or on every SHC
member) before relying on those searches:

- Lookups (CSV, KV Store, external, geospatial)
- Calculated fields
- Eventtypes
- Tags
- Field aliases
- Search macros that the federated portion of the search invokes

Otherwise the remote leg of the search returns unenriched events.

## Service Account Capabilities

The service-account role on each remote deployment must:

- Read the mapped datasets (`index`, `metricindex`, `savedsearch`,
  `lastjob`, `datamodel`).
- For transparent mode against an SHC, hold the
  `list_search_head_clustering` capability so Splunk can detect duplicate
  transparent providers across cluster members.
- Have search permissions sufficient to run the largest expected federated
  search (transparent mode searches inherit the local user's permissions
  for non-index targets; remote indexes are governed by the service account).

## Splunk Cloud Considerations

- **IP allow-list**: Splunk Cloud Federated Search Heads (local or remote)
  require the *Search head API access* IP allow-list use case to permit
  every IP/CIDR that runs `apply-rest.sh`, `status.sh`, or the global
  toggle scripts.
- **No file edits**: Splunk Cloud customers cannot edit `federated.conf`
  directly. Use `--apply-target rest` for FSS2S, and POST FSS3 providers
  through `apply-rest.sh` (which reads the rendered
  `aws-s3-providers/<name>.json` payloads).
- **Region support**: Federated Search supports Splunk Cloud Platform on
  AWS, Google Cloud, and Microsoft Azure. Cross-region restrictions vary;
  see the Splunk Cloud Service Description.
- **FSS3 region binding**: AWS Glue database, S3 buckets, and KMS keys must
  be in the same region as the Splunk Cloud deployment.

## Search Head Cluster (FSS2S)

For standard mode on Splunk Enterprise SHC:

1. Push the rendered app through the deployer first so every SHC member
   honors `[shclustering] conf_replication_include.indexes = true`.
2. Then create or deploy federated index definitions.

Creating federated indexes before this replication setting exists can leave
SHC members with inconsistent federated index definitions.

## Service Account Handling

The remote provider service-account password is never embedded in rendered
files. The renderer writes a stable per-provider placeholder (e.g.
`__FEDERATED_PASSWORD_FILE_BASE64__REMOTE_PROD__`) into
`federated.conf.template`; the apply scripts substitute the password from the
local-only `password_file` declared per provider in the spec, then write
`federated.conf` with mode `0600`.

The REST apply path reads each provider's `password_file` at apply time and
includes the password value in the form-encoded POST body to
`/services/data/federated/provider` (Splunk's own endpoint encrypts the value
to `splunk.secret` on disk). The Splunk admin password used to authenticate
the REST apply itself comes from `SPLUNK_REST_PASSWORD_FILE` and is never
placed on argv.

## Validation

Static validation (`validate.sh`) checks:

- All required rendered files exist.
- `federated.conf.template` has a per-provider password placeholder for every
  `[provider://X]` stanza.
- Each `aws-s3-providers/*.json` payload is valid JSON, has `type=aws_s3`,
  and includes the required FSS3 keys.

Live validation (`validate.sh --live`) additionally runs `status.sh`, which
GETs `/services/data/federated/provider`, `/services/data/federated/index`,
and `/services/data/federated/settings/general`, surfacing per-provider
`connectivityStatus` (`valid`, `invalid`, or `unknown`). Output is sanitized
so no password material is printed.

## REST Apply Environment

The REST apply scripts (`apply-rest.sh`, `status.sh`, `global-enable.sh`,
`global-disable.sh`) read these environment variables — never argv — for
authentication:

| Variable | Purpose |
|---|---|
| `SPLUNK_REST_URI` | `https://<search-head>:<management-port>` |
| `SPLUNK_REST_USER` | Admin user with `admin_all_objects` (FSS3 requires this). |
| `SPLUNK_REST_PASSWORD_FILE` | Local-only file containing the admin password. |
| `SPLUNK_VERIFY_SSL` | `true` (default) or `false` for self-signed dev clusters. Canonical name shared with the rest of the skill suite. |
| `SPLUNK_REST_VERIFY_SSL` | Legacy alias for `SPLUNK_VERIFY_SSL`. Honored as a fallback when the canonical variable is unset. Prefer `SPLUNK_VERIFY_SSL` in new automation. |
