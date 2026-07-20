---
name: splunk-federated-search-setup
description: "Use when configuring Cisco Data Fabric federated search or standalone Splunk Federated Search, cross-
  domain search, federated analytics, S3 data-lake search, or querying data where it resides. Render,
  preflight, apply, and validate FSS2S standard/transparent providers and reviewed legacy FSS3 payloads;
  render 10.5 migration guidance and current Data Management handoffs for S3, Azure, Databricks,
  Snowflake, and DDSS; distinguish Glue, Iceberg REST, and Splunk-native catalogs; preserve handoff-only
  Amazon Security Lake (`aws_lake`) and Cisco SAL (`aws_s3_sal`) identities; and manage supported global-
  switch, status, file, SHC, and REST workflows."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Splunk Federated Search Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ Preflight │ → │ Render/review │ → │ Apply/handoff │ → │ Validate evidence │
└───────────┘   └───────────────┘   └───────────────┘   └─────────────────┘
```

## When to Activate

- Configuring Cisco Data Fabric federated search or standalone Splunk Federated Search, cross-domain search,
  federated analytics, S3 data-lake search, or querying data where it resides. Render, preflight, apply, and
  validate FSS2S.
- Preview and review the splunk federated search setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-federated-search-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-federated-search-setup/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

This skill prepares the Splunk Federated Search product surface across remote
Splunk platform deployments, Amazon S3 data lakes, and current Data Management
app federation handoffs. It renders reviewable assets before any apply phase
and never embeds secrets in the rendered files.

For newer Cisco Data Fabric wording, this is the first-class federated search
route. Data Fabric is broader Splunk Platform architecture; route edge/ingest
pipeline work to Edge Processor, Ingest Processor, or the SPL2 pipeline kit,
and route AI Toolkit / MCP work to their dedicated skills.

Covered:

- **Federated Search for Splunk (FSS2S)** — `type = splunk` providers in
  standard or transparent mode, with multiple providers per render and one
  or more federated indexes per provider. Supports all four documented
  deployment combinations (SE↔SE, SC↔SC, SE↔SC, SC↔SE).
- **Federated Search for Amazon S3 (FSS3)** — `type = aws_s3` providers
  rendered as payload-shaped inventory/migration evidence for reviewed legacy
  provider model (Splunk Cloud Platform only; FSS3 cannot be configured via
  `federated.conf`). Splunk 10.5 documents phased deprecation of legacy FS-S3
  provider/index operations and makes existing indexes read-only after
  migration to Data Management. This skill emits no legacy FSS3 CRUD; new
  designs use current connections and datasets.
- **Data Management app federation handoff** — readiness notes for the current
  connection/dataset model for Amazon S3, Microsoft Azure, Azure Databricks,
  Snowflake, and DDSS. These are UI/activation handoffs until a stable public
  API contract is available. The current overview requires Splunk sales
  activation for each surface; confirm commercial terms per tenant and do not
  infer one universal Data Scan Unit requirement.
- **Amazon S3 catalog choices** — distinguish AWS Glue catalog tables (Iceberg,
  Delta Lake, or non-table JSON/Parquet), Apache Iceberg REST catalogs, and
  Splunk-native catalogs with inferred or operator-defined schema/partitions.
- **Specialized federation handoffs** — accept `type = aws_lake` to record an
  Amazon Security Lake Federated Analytics handoff and `type = aws_s3_sal` to
  record a Cisco Security Analytics and Logging handoff. These entries never
  produce generic `aws_s3` payloads or live CRUD.
- **Global federated-search switch** — enable or disable Federated Search
  for the entire deployment via
  `/services/data/federated/settings/general`.
- **REST apply path** — works on both Splunk Enterprise and Splunk Cloud
  Platform for supported FSS2S providers/indexes. It excludes legacy FSS3 and
  specialized handoffs and refuses legacy-only plans.
- **Live status helper** — REST GET of providers and indexes with
  per-provider `connectivityStatus`, output sanitized so no password
  material is printed.

## Agent Behavior

Never ask for the federated provider service-account password (FSS2S) or for
the Splunk admin password used by the REST apply path in chat. Use local-only
secret files:

```bash
# FSS2S service-account password (one per provider, listed in the spec):
bash skills/shared/scripts/write_secret_file.sh /tmp/federated_provider_password

# REST apply admin password (used by apply-rest.sh and status.sh):
bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_admin_password
```

Credential-bearing REST apply requires a credential-free HTTPS origin and
never follows redirects. Plaintext HTTP is refused unless an operator
explicitly sets `SPLUNK_ALLOW_INSECURE_HTTP=true` for an isolated, short-lived
lab; disabling certificate verification does not authorize HTTP.

Collect non-secret values in `template.example`: provider names, remote
management endpoints, service-account usernames, provider modes, federated
index names, dataset types and names, app contexts, AWS account IDs, AWS
regions, Glue databases, S3 paths, KMS key ARNs, and SHC replication choice.

## Quick Start

### Single provider (back-compat single-flag CLI)

```bash
bash skills/splunk-federated-search-setup/scripts/setup.sh \
  --mode standard \
  --remote-host-port remote-sh.example.com:8089 \
  --service-account federated_svc \
  --provider-name remote_prod \
  --federated-index-name remote_main \
  --dataset-type index \
  --dataset-name main
```

### Multi-provider via YAML spec

```bash
bash skills/splunk-federated-search-setup/scripts/setup.sh \
  --spec skills/splunk-federated-search-setup/template.example \
  --output-dir splunk-federated-search-rendered
```

### Apply file-based (standalone search head)

```bash
bash skills/splunk-federated-search-setup/scripts/setup.sh \
  --spec my-fss-spec.yaml \
  --phase apply \
  --apply-target search-head
```

### Apply through SHC deployer

```bash
bash skills/splunk-federated-search-setup/scripts/setup.sh \
  --spec my-fss-spec.yaml \
  --phase apply \
  --apply-target shc-deployer
# Operator then runs: splunk apply shcluster-bundle -target https://<member>:8089
```

### Apply via REST (Splunk Enterprise OR Splunk Cloud)

```bash
export SPLUNK_REST_URI=https://search-head.example.com:8089
export SPLUNK_REST_USER=admin
export SPLUNK_REST_PASSWORD_FILE=/tmp/splunk_admin_password
bash skills/splunk-federated-search-setup/scripts/setup.sh \
  --spec my-fss-spec.yaml \
  --phase apply \
  --apply-target rest
```

The REST apply POSTs supported FSS2S providers and their standard-mode
federated indexes. On HTTP 409 (already exists) it re-POSTs to the keyed
endpoint to update the existing entity in place. It never POSTs legacy FSS3,
`aws_lake`, or `aws_s3_sal` objects.

Legacy `aws_s3` is inventory/migration-only on the 10.5 baseline. Review
`legacy-fss3-migration.md`; no apply path is generated for those providers or
indexes.

### Render specialized federation handoffs

```bash
bash skills/splunk-federated-search-setup/scripts/setup.sh \
  --provider 'type=aws_lake,name=amazon_security_lake' \
  --provider 'type=aws_s3_sal,name=cisco_sal' \
  --output-dir splunk-federated-search-rendered
```

This renders intent and readiness only. It does not create either provider or
allow a `federated_indexes` entry to target a handoff-only provider.

### Global federated-search toggle

```bash
# Required env: SPLUNK_REST_URI, SPLUNK_REST_USER, SPLUNK_REST_PASSWORD_FILE
bash skills/splunk-federated-search-setup/scripts/setup.sh \
  --phase global-toggle \
  --global-toggle disable
```

### Live status

```bash
bash skills/splunk-federated-search-setup/scripts/setup.sh \
  --phase status
# Or after rendering:
bash skills/splunk-federated-search-setup/scripts/validate.sh --live
```

## What It Renders

| File | Purpose |
|---|---|
| `federated.conf.template` | One `[provider://X]` stanza per FSS2S provider, with per-provider password placeholder |
| `indexes.conf` | One `[federated:X]` stanza per FSS2S federated index |
| `server.conf` | `[shclustering] conf_replication_include.indexes = true` for SHC deployer use |
| `aws-s3-providers/<name>.json` | Payload-shaped inventory/migration evidence per reviewed legacy FSS3 provider; never consumed by apply scripts |
| `data-management-federation-handoff.md` | Current Data Management app federation handoff for Amazon S3, Microsoft Azure, Azure Databricks, Snowflake, and DDSS, including S3 catalog and format distinctions |
| `specialized-federation-handoff.md` | Dedicated `aws_lake` Amazon Security Lake and `aws_s3_sal` Cisco SAL readiness without CRUD |
| `legacy-fss3-migration.md` | Splunk 10.5 phased-deprecation inventory and migration checklist for legacy `aws_s3` providers |
| `apply-search-head.sh` | File-based apply on a standalone Enterprise SH |
| `apply-shc-deployer.sh` | Fail-closed handoff to `splunk-search-head-cluster-setup`; staging files alone is not reported as a completed SHC bundle apply |
| `apply-rest.sh` | REST apply for supported FSS2S on Splunk Enterprise or Splunk Cloud; refuses legacy-only plans |
| `global-enable.sh` / `global-disable.sh` | Toggle the global federated-search switch |
| `status.sh` | REST GET per provider, prints `connectivityStatus` |
| `preflight.sh` | Local btool sanity checks |
| `metadata.json` | Machine-readable plan summary, including warnings |

Read `reference.md` before choosing standard vs transparent mode and before
mixing FSS2S deployment combinations.
