---
name: splunk-federated-search-setup
description: >-
  Use when configuring Splunk Federated Search. Render, preflight, apply, and
  validate the full product surface: Federated Search for Splunk (FSS2S,
  type=splunk) in standard or transparent mode with multiple providers and
  federated indexes per render, Federated Search for Amazon S3 (FSS3,
  type=aws_s3, Splunk Cloud Platform only) via REST payloads with AWS
  prerequisites, file-based apply for Splunk Enterprise standalone search heads
  or SHC deployers, REST-based apply that works on Splunk Enterprise and Splunk
  Cloud, the global federated-search enable/disable switch, and a status helper
  that reports per-provider connectivityStatus.
---

# Splunk Federated Search Setup

This skill prepares the entire Splunk Federated Search product surface across
remote Splunk platform deployments and Amazon S3 data lakes. It renders
reviewable assets before any apply phase and never embeds secrets in the
rendered files.

Covered:

- **Federated Search for Splunk (FSS2S)** — `type = splunk` providers in
  standard or transparent mode, with multiple providers per render and one
  or more federated indexes per provider. Supports all four documented
  deployment combinations (SE↔SE, SC↔SC, SE↔SC, SC↔SE).
- **Federated Search for Amazon S3 (FSS3)** — `type = aws_s3` providers
  rendered as REST payloads (Splunk Cloud Platform only; FSS3 cannot be
  configured via `federated.conf`).
- **Global federated-search switch** — enable or disable Federated Search
  for the entire deployment via
  `/services/data/federated/settings/general`.
- **REST apply path** — works on both Splunk Enterprise and Splunk Cloud
  Platform without shell access on the target.
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

The REST apply POSTs each FSS2S provider, each FSS3 provider, and each
federated index. On HTTP 409 (already exists) it re-POSTs to the keyed
endpoint to update the existing entity in place.

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
| `aws-s3-providers/<name>.json` | REST payload per FSS3 provider, plus an AWS prerequisites README |
| `apply-search-head.sh` | File-based apply on a standalone Enterprise SH |
| `apply-shc-deployer.sh` | File-based apply through the SHC deployer bundle |
| `apply-rest.sh` | REST apply for Splunk Enterprise OR Splunk Cloud |
| `global-enable.sh` / `global-disable.sh` | Toggle the global federated-search switch |
| `status.sh` | REST GET per provider, prints `connectivityStatus` |
| `preflight.sh` | Local btool sanity checks |
| `metadata.json` | Machine-readable plan summary, including warnings |

Read `reference.md` before choosing standard vs transparent mode and before
mixing FSS2S deployment combinations.
