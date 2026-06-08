---
name: splunk-gcp-ta-setup
description: >-
  Install, render, configure, and validate the Splunk Add-on for Google Cloud
  Platform (Splunk_TA_google-cloudplatform, Splunkbase 3088). Centers on the
  high-value Cloud Logging to Pub/Sub ingestion path, rendering the real
  google_cloud_pubsub input (google:gcp:pubsub:message plus auto-classified
  audit subtypes), a service-account credential runbook, the gcp index, and
  ingestion validation; documents the monitor, billing, bucket, and
  resource-metadata inputs. Use when the user asks about
  Splunk_TA_google-cloudplatform, the Splunk Add-on for Google Cloud Platform,
  GCP audit logs, Cloud Logging, Pub/Sub ingestion, or GCP log onboarding in
  Splunk.
---

# Splunk Add-on for Google Cloud Platform Setup

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Render-first automation for the **Splunk Add-on for Google Cloud Platform**
(`Splunk_TA_google-cloudplatform`, Splunkbase `3088`). This skill centers on the
**Cloud Logging -> Pub/Sub** ingestion path, which is the GCP SIEM/audit feed,
and documents the other inputs (Monitoring, Billing, buckets, resource
metadata).

The add-on runs on the search tier or a heavy forwarder. Run a given Pub/Sub
subscription on a single node to avoid duplicate acknowledgement.

## Primary Feed

| Input | Source type |
| --- | --- |
| `google_cloud_pubsub` | `google:gcp:pubsub:message` |

Cloud Audit Logs delivered through Pub/Sub are auto-classified into
`google:gcp:pubsub:audit:admin_activity`, `:data_access`, `:system_event`, and
`:policy_denied`.

## Credentials

Never paste a service-account key in chat or argv. Prefer **ADC** on a
GCE/GKE collector, or upload a JSON key file in the add-on Configuration tab:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/gcp_sa_key.json
```

See the rendered `account-setup.md` for the service account, IAM roles, and the
Cloud Logging sink -> Pub/Sub export steps.

## Workflow

1. Render reviewable assets (offline):

```bash
bash skills/splunk-gcp-ta-setup/scripts/setup.sh --render \
  --index gcp --project my-gcp-project --subscription splunk-export-sub
```

2. Install the add-on and create the index:

```bash
bash skills/splunk-gcp-ta-setup/scripts/setup.sh --install --create-index --index gcp
```

3. Configure the credential and the Pub/Sub log export (`account-setup.md`),
   then enable the rendered input.

4. Validate:

```bash
bash skills/splunk-gcp-ta-setup/scripts/validate.sh --index gcp
```

See `reference.md` for the full input catalog, credential model, source types,
and placement guardrails. For Cloud Monitoring **metrics** into Splunk
Observability Cloud, use `splunk-observability-gcp-integration` instead.
