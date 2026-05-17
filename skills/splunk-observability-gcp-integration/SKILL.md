---
name: splunk-observability-gcp-integration
description: >-
  Render, apply, validate, discover, and diagnose the Splunk Observability Cloud
  GCP integration for Cloud Monitoring metrics. Covers service-account key and
  Workload Identity Federation auth, poll-rate bounds, metric source quota,
  service enums, custom metric domains, label exclusions, namedToken warnings,
  Terraform, gcloud service-account and IAM scripts, multi-project support,
  credential-hash drift detection, and conflict checks. Use when the user asks
  to connect Splunk Observability Cloud to GCP metrics, configure Service
  Account or WIF credentials, manage the GCP REST/Terraform integration, or set
  up GCP dashboards, detectors, logs, or GKE telemetry handoffs.
---

# Splunk Observability Cloud — GCP Integration Setup

Render-first skill that owns the complete lifecycle of the Splunk O11y GCP
integration. The workflow is render-first by default. The Splunk O11y REST API
is only called when the operator explicitly runs `--apply`.

## Coverage Model

| Section | Coverage status |
|---------|----------------|
| REST payload generation | `api_validate` |
| Terraform `signalfx_gcp_integration` | `handoff` |
| GCloud CLI SA creation scripts | `handoff` |
| GCloud CLI role binding scripts | `handoff` |
| WIF pool/provider configuration | `api_validate` |
| Drift detection (hash-based) | `api_validate` |
| Conflict matrix enforcement | `api_validate` |
| `projectKey` redacted on GET | `api_validate` |
| Services enum validation | `api_validate` |
| `namedToken` ForceNew warning | `api_validate` |
| Cross-skill handoffs | `handoff` / `not_applicable` |

## Safety Rules

- Never ask for the GCP Service Account JSON key (`projectKey`) in conversation.
- Never pass `projectKey` as a CLI argument or env-var prefix.
- Use `--key-file` (chmod 600) for file-based delivery.
- Use `write_secret_file.sh` to create secret files without shell-history exposure.
- Reject direct-secret flags: `--secret`, `--password`, `--api-key`,
  `--project-key`, `--token`.
- `projectKey` is redacted on `GET /v2/integration/<id>`.
  The skill compares local file hashes to `state/credential-hashes.json`
  rather than server state.

## Five-mode UX

| Mode | Flag | Purpose |
|------|------|---------|
| render | `--render` (default) | Produces the plan tree. No Splunk or GCP API calls. |
| apply | `--apply [SECTIONS]` | Calls `POST/PUT /v2/integration`. Sections: `integration,validation`. |
| validate | `--validate [--live]` | Static plan checks + optional live `GET` probe. |
| doctor | `--doctor` | Services enum, poll-rate, namedToken, credential-hash checks. |
| quickstart | `--quickstart` | Render + print exact `--apply` command. |

Additional modes: `--discover`, `--quickstart-from-live`, `--explain`,
`--rollback`, `--list-services`.

## Primary Workflow

### 1. Copy and edit the spec

```bash
cp skills/splunk-observability-gcp-integration/template.example my-gcp-spec.yaml
# fill in realm, project_id, services
```

### 2. Write Service Account key to a file (once)

```bash
# Download the SA key from GCP Console or CLI (never put in history):
gcloud iam service-accounts keys create /tmp/gcp-sa-key.json \
  --iam-account=splunk-o11y@${GCP_PROJECT_ID}.iam.gserviceaccount.com
chmod 600 /tmp/gcp-sa-key.json
```

### 3. Render

```bash
bash skills/splunk-observability-gcp-integration/scripts/setup.sh \
  --render \
  --spec my-gcp-spec.yaml \
  --realm us1 \
  --key-file /tmp/gcp-sa-key.json \
  --token-file /tmp/splunk_o11y_token
```

### 4. Review the plan

```
splunk-observability-gcp-integration-rendered/
  README.md               # plan summary + apply command
  rest/create.json        # POST /v2/integration body
  rest/update.json        # PUT /v2/integration/{id} body
  gcloud-cli/create-sa.sh  # gcloud iam sa create (review)
  gcloud-cli/bind-roles.sh # role bindings
  terraform/main.tf       # signalfx_gcp_integration resource
  terraform/variables.tf  # variable declarations
  handoffs/               # cross-skill handoff drivers
  state/                  # populated on apply
  coverage-report.json    # per-section coverage status
  apply-plan.json         # ordered steps
```

### 5. Apply

```bash
bash skills/splunk-observability-gcp-integration/scripts/setup.sh \
  --apply \
  --spec my-gcp-spec.yaml \
  --realm us1 \
  --token-file /tmp/splunk_o11y_token \
  --key-file /tmp/gcp-sa-key.json
```

## Quickstart

```bash
bash skills/splunk-observability-gcp-integration/scripts/setup.sh \
  --quickstart \
  --spec my-gcp-spec.yaml \
  --realm us1
```

## Doctor

```bash
bash skills/splunk-observability-gcp-integration/scripts/setup.sh \
  --doctor \
  --realm us1
```

Doctor checks: services non-empty when explicit mode, poll-rate 60–600,
namedToken ForceNew warning, credential-hash freshness, and `projectKey`
redaction notice.

## Rollback

```bash
bash skills/splunk-observability-gcp-integration/scripts/setup.sh \
  --rollback integration \
  --realm us1 \
  --token-file /tmp/splunk_o11y_token
```

Disables the integration in Splunk O11y (sets `enabled: false`). Use
`--rollback delete` to remove it entirely.

## Workload Identity Federation

WIF allows keyless authentication — no SA JSON key is created or stored.

```yaml
authentication:
  mode: workload_identity_federation
  workload_identity_federation:
    pool_id: "splunk-o11y-pool"
    provider_id: "splunk-o11y-provider"
    splunk_principal: ""  # auto-filled from realm map
```

The Splunk-side principal for your realm is in
`references/wif-splunk-principals.json`. For unknown realms, contact Splunk
Support for the exact principal value.

## Hand-offs

- Logs path → [`splunk-app-install`](../splunk-app-install/SKILL.md) for
  `Splunk_TA_google_cloud` (Splunkbase 3088)
- GKE host telemetry → [`splunk-observability-otel-collector-setup`](../splunk-observability-otel-collector-setup/SKILL.md)
- GCP dashboards → [`splunk-observability-dashboard-builder`](../splunk-observability-dashboard-builder/SKILL.md)
- GCP detectors → [`splunk-observability-native-ops`](../splunk-observability-native-ops/SKILL.md)
- Log Observer Connect → [`splunk-observability-cloud-integration-setup`](../splunk-observability-cloud-integration-setup/SKILL.md)
- HEC tokens → [`splunk-hec-service-setup`](../splunk-hec-service-setup/SKILL.md)

## Out of Scope

- GCP Pub/Sub streaming (not in the Splunk O11y wire contract)
- GCP log ingestion (Splunk_TA_google_cloud, Splunkbase 3088 — handed off)
- GCP China regions — not supported by this integration

## Validation

```bash
bash skills/splunk-observability-gcp-integration/scripts/validate.sh \
  --output-dir splunk-observability-gcp-integration-rendered
```

Static checks: required files, JSON shape (`type: GCP`), no secret-looking
content in rendered files. With `--live`: `GET /v2/integration` probe.
