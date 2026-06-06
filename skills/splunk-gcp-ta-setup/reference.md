# Splunk Add-on for Google Cloud Platform Reference

Grounded in the `Splunk_TA_google-cloudplatform` package (Splunkbase app `3088`,
verified version `5.0.2`).

## Package Model

- App / package id: `Splunk_TA_google-cloudplatform`
- Splunkbase ID: `3088`
- Modular inputs (default `inputs.conf`): `google_cloud_pubsub`,
  `google_cloud_pubsub_lite`, `google_cloud_pubsub_based_bucket`,
  `google_cloud_monitor`, `google_cloud_billing`, `google_cloud_bucket_metadata`,
  `google_cloud_resource_metadata` (+ cloud_storage / vpc_access / kubernetes
  variants).
- Credential endpoint (`restmap.conf`): `google_credentials`
  (`google_cloud_credentials.conf`: `google_credentials` JSON key, `account_type`,
  `adc_account`).

## Primary Feed: Cloud Logging -> Pub/Sub

`google_cloud_pubsub` fields (`inputs.conf.spec`): `google_credentials_name`,
`google_project`, `google_subscriptions`, `index`, `sourcetype`
(default `google:gcp:pubsub:message`).

Cloud Audit Logs delivered through Pub/Sub are auto-classified by the add-on:

| Source type | CIM |
| --- | --- |
| `google:gcp:pubsub:message` | depends on log type |
| `google:gcp:pubsub:audit:admin_activity` | Change |
| `google:gcp:pubsub:audit:data_access` | Change |
| `google:gcp:pubsub:audit:system_event` | Change |
| `google:gcp:pubsub:audit:policy_denied` | Change / Authentication |

Setup: create a Pub/Sub topic + subscription, add a Cloud Logging sink to the
topic (for example all `cloudaudit.googleapis.com` logs), and grant the service
account `roles/pubsub.subscriber` on the subscription.

## Other Inputs

`google_cloud_monitor` (Cloud Monitoring metrics), `google_cloud_billing`,
`google_cloud_pubsub_based_bucket`, `google_cloud_bucket_metadata`, and the
`google_cloud_resource_metadata*` family are configured through the add-on UCC
Configuration UI. Other documented source types include
`google:gcp:billing:report`, `google:gcp:buckets:*`, and `google:gcp:compute:*`.

## Credential Model

- **Service account key (JSON):** uploaded in the add-on
  Configuration > Google Credentials tab; stored encrypted.
- **Application Default Credentials (ADC):** set `adc_account = 1` when the
  collector runs on GCE/GKE with an attached service account (no stored key).
- Least-privilege IAM: `roles/pubsub.subscriber` (+ `roles/pubsub.viewer`);
  `roles/monitoring.viewer` only for Cloud Monitoring metrics.

## Index Model

| Index | Purpose | Default |
| --- | --- | --- |
| Event index | Pub/Sub log messages and audit subtypes | `gcp` |

## Placement Guardrails

- Run on the search tier or a dedicated heavy forwarder.
- Run a given Pub/Sub subscription on a single input/node; the add-on
  acknowledges messages it pulls, so duplicate inputs drop or duplicate data.
- Use a dedicated subscription per input.
- Store the service-account key only via the add-on credential (encrypted), or
  use ADC; never in conf files or argv.

## Relationship To Observability

- This skill is the **Splunk Platform log** path (Cloud Logging -> Pub/Sub).
- `splunk-observability-gcp-integration` covers Cloud Monitoring **metrics**
  into Splunk Observability Cloud (a different product surface).

## Handoffs

- `splunk-app-install` installs the package from Splunkbase (`3088`).
- `splunk-observability-gcp-integration` for GCP metrics into Observability.

## Sources

- https://splunkbase.splunk.com/app/3088
- https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/google-cloud-platform
