# Splunk Federated Search Reference

## Research Basis

This skill follows current Splunk Federated Search documentation and
configuration references for Splunk Enterprise 10.4 and Splunk Cloud Platform
10.4.2604:

- `federated.conf` provider stanza: `provider://<name>` with `type`,
  `hostPort`, `serviceAccount`, `password`, `mode`, `appContext`,
  `useFSHKnowledgeObjects`, `allowIndexBasedProviderFiltering`,
  `fedSrchIndexesAllowed`, `useAppContextFromSearch`, `disabled`.
- `[general]` stanza: `max_preview_generation_duration` and
  `max_preview_generation_inputcount`.
- Federated index stanza: `federated:<index_name>` with `federated.provider`,
  `federated.dataset` (`<type>:<dataset_name>`), `disabled`.
- REST endpoints for FSS2S:
  - `/services/data/federated/settings/general` — global enable/disable.
  - `/services/data/federated/provider` — FSS2S provider CRUD.
  - `/services/data/federated/index` — federated index CRUD.
  - Each provider entity supports `/_reload`, `/enable`, and `/disable`.
- Splunk Cloud Platform 10.4.2604+ Amazon S3 federated search uses Data
  Management app connections and datasets. The legacy FSS3 REST provider path
  is not the default 10.4 workflow.

## Provider Types

Splunk Federated Search ships two provider types:

| `type` | Product | Available on | Configuration surface |
|---|---|---|---|
| `splunk` | Federated Search for Splunk (FSS2S) | Splunk Enterprise + Splunk Cloud | `federated.conf` and REST |
| `aws_s3` | Amazon S3 federated dataset handoff | Splunk Cloud Platform 10.4.2604+ | Data Management app |
| `aws_s3` with `fss3_mode=legacy` | Legacy FSS3 | Older Splunk Cloud Platform stacks only | REST + Splunk Web only |

For Cloud 10.4.2604 and newer, this skill renders one JSON handoff per Amazon
S3 provider under `data-management-datasets/<name>.json`. Operators create the
connection and dataset in the Data Management app; this skill does not claim
private Data Management API CRUD. Legacy REST payloads under
`aws-s3-providers/<name>.json` render only when `fss3_mode=legacy`.

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
| `allowIndexBasedProviderFiltering` | optional | Enables transparent-mode provider filtering by federated index. |
| `fedSrchIndexesAllowed` | optional | Semicolon-separated allowlist rendered for Splunk; CLI input may be comma- or semicolon-delimited. |
| `useAppContextFromSearch` | optional | For standard mode, lets Splunk derive provider app context from the local search's app context; use only when those app contexts exist remotely. |
| `disabled` | optional | Defaults to false. |

## Amazon S3 Data Management Settings (`type = aws_s3`)

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

The renderer's Data Management handoff documents the Glue Data Catalog, S3
paths, KMS keys, and federated-index hints that operators need when creating
the Data Management connection and dataset. Legacy Splunk Web "Generate
policy" notes are rendered only in `fss3_mode=legacy`.

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
  directly. Use `--apply-target rest` for FSS2S. For Amazon S3 federated
  datasets on 10.4.2604+, create Data Management connections and datasets from
  `data-management-datasets/<name>.json`.
- **Region support**: Federated Search supports Splunk Cloud Platform on
  AWS, Google Cloud, and Microsoft Azure. Cross-region restrictions vary;
  see the Splunk Cloud Service Description.
- **Amazon S3 region binding**: AWS Glue database, S3 buckets, and KMS keys
  must be compatible with the Splunk Cloud deployment and Data Management
  dataset region constraints.

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

The REST apply path reads each FSS2S provider's `password_file` at apply time
and includes the password value in the form-encoded POST body to Splunk's FSS2S
provider endpoint. Splunk encrypts the value on disk. The Splunk admin password
used to authenticate the REST apply itself comes from
`SPLUNK_REST_PASSWORD_FILE` and is never placed on argv. Amazon S3 Data
Management dataset handoffs are not POSTed by this script.

## Validation

Static validation (`validate.sh`) checks:

- All required rendered files exist.
- `federated.conf.template` has a per-provider password placeholder for every
  `[provider://X]` stanza.
- Each `data-management-datasets/*.json` payload is valid JSON, has
  `type=data_management_dataset`, and includes the required Cloud 10.4.2604
  Data Management dataset handoff keys.
- Each legacy `aws-s3-providers/*.json` payload is valid JSON, has
  `type=aws_s3`, and includes the required legacy FSS3 keys.

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
| `SPLUNK_REST_USER` | Admin user with `admin_all_objects` for REST apply; legacy FSS3 mode also requires this. |
| `SPLUNK_REST_PASSWORD_FILE` | Local-only file containing the admin password. |
| `SPLUNK_VERIFY_SSL` | `true` (default) or `false` for self-signed dev clusters. Canonical name shared with the rest of the skill suite. |
| `SPLUNK_REST_VERIFY_SSL` | Legacy alias for `SPLUNK_VERIFY_SSL`. Honored as a fallback when the canonical variable is unset. Prefer `SPLUNK_VERIFY_SSL` in new automation. |
