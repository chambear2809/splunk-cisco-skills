---
name: splunk-observability-gcp-integration
description: "Use when the user asks to connect Splunk Observability Cloud to GCP metrics, configure Service Account
  or official generated WIF credentials, manage the GCP REST integration, or set up GCP dashboards,
  detectors, logs, or GKE telemetry handoffs. Render, apply, validate, discover, and diagnose the Splunk
  Observability Cloud GCP integration for Cloud Monitoring metrics. Covers service-account key and
  Workload Identity Federation auth, poll-rate bounds, metric source quota, service enums, custom metric
  domains, label exclusions, namedToken warnings, service-account Terraform and gcloud IAM handoffs,
  multi-project support, credential-hash drift detection, and conflict checks."
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Splunk Observability Cloud — GCP Integration Setup

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

- Connect Splunk Observability Cloud to GCP metrics, configure Service Account or official generated WIF
  credentials, manage the GCP REST integration, or set up GCP dashboards, detectors, logs, or GKE telemetry
  handoffs.
- Preview and review the splunk observability gcp integration workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-observability-gcp-integration/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-observability-gcp-integration/scripts/validate.sh --help
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

## Shared add-on completion gate

If this workflow installs or hands off the registry-listed Splunk GCP add-on or
dashboard companion, follow the
[shared completion gate](../shared/ta_completion_gate.md). Package delivery
alone is not success; validate applicable ingest, macros, and shipped
dashboards against data.

Render-first skill that owns the complete lifecycle of the Splunk O11y GCP
integration. Rendering and rollback-plan review are network-free. Mutations
require explicit `--apply`; `--discover`, `--quickstart-from-live`, and
`--validate --live` are the explicit read-only modes that call the live API.

## Splunk Platform Add-on Verification Boundary

The separate log-ingestion handoff uses Splunkbase `3088`. Its package-derived
baseline is `5.0.2`; the current public release is `5.0.3` and advertises
Splunk 10.5 support, but this repository has not inspected the `5.0.3` package.
The shared installer defaults to verified `5.0.2`; if the handoff explicitly
uses `--accept-unverified-release`, verify the `5.0.3` manifest, modular-input
schema, source types, and dashboards before completion. This warning does not
change the Observability Cloud GCP metrics REST integration owned by this skill.

## Coverage Model

| Section | Coverage status |
|---------|----------------|
| REST payload generation | `api_validate` |
| Terraform `signalfx_gcp_integration` (SA-key mode only) | `handoff` |
| GCloud CLI SA creation scripts | `handoff` |
| GCloud CLI role binding scripts | `handoff` |
| Official `gcp_wif_config.json` validation and REST delivery | `api_apply` / `api_validate` |
| Drift detection (hash-based) | `api_validate` |
| Conflict matrix enforcement | `api_validate` |
| `projectKey` omitted on GET and reconstructed for PUT | `api_validate` |
| Services enum validation | `api_validate` |
| `namedToken` ForceNew warning | `api_validate` |
| Cross-skill handoffs | `handoff` / `not_applicable` |

## Safety Rules

- Never ask for the GCP Service Account JSON key (`projectKey`) in conversation.
- Never pass `projectKey` as a CLI argument or env-var prefix.
- Use `--key-file` (chmod 600) for file-based delivery. Each JSON file is
  securely parsed and mapped by its own `project_id`, independent of flag
  order. Missing, extra, duplicate, or mismatched project coverage fails before
  any live request; a credential is never reused for another project.
- In WIF mode, use only Splunk's official generated file named
  `gcp_wif_config.json`, stored unchanged as a regular mode-600 file. Pass its
  path through `--wif-config-file`; never paste its contents into the spec.
- Do not infer realm principals or construct WIF pool/provider values. The
  generated document is opaque and is sent as compact, stringified JSON in
  `workloadIdentityFederationConfig`.
- Use `write_secret_file.sh` to create secret files without shell-history exposure.
- Reject direct-secret flags: `--secret`, `--password`, `--api-key`,
  `--project-key`, `--token`, `--wif-config`.
- `projectKey` is not returned by `GET /v2/integration/<id>`.
  The skill compares local file hashes to `state/credential-hashes.json`
  rather than server state.
- Newly rendered provisioning payloads include `projects.syncMode`; `SELECTED`
  also includes the reviewed project ID list. Rollback preserves a valid
  service-account live object that omits `projects`, while WIF requires a
  validated projects contract.

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
  --realm us1
```

### 4. Review the plan

```
splunk-observability-gcp-integration-rendered/
  README.md               # plan summary + apply command
  rest/create.json        # POST /v2/integration body
  rest/update.json        # PUT /v2/integration/{id} body
  rest/wif-config-file-manifest.json # file path only; no WIF contents
  gcloud-cli/create-sa.sh  # gcloud iam sa create (review)
  gcloud-cli/bind-roles.sh # role bindings
  terraform/main.tf       # SA-key resource; WIF intentionally uses the REST path
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
`projects.syncMode`, namedToken ForceNew warning, credential-hash freshness,
and WIF file existence, JSON integrity, filename, regular-file status, and mode.

## Rollback

Rollback is a three-step snapshot, offline review, and exact-plan apply
workflow. It never resolves a mutation target by name.

### 1. Capture a read-only observed snapshot

```bash
bash skills/splunk-observability-gcp-integration/scripts/setup.sh \
  --discover \
  --realm us1 \
  --token-file /secure/splunk_o11y_token \
  --output-dir gcp-live
```

### 2. Render and review a disable plan offline

```bash
bash skills/splunk-observability-gcp-integration/scripts/setup.sh \
  --rollback disable \
  --realm us1 \
  --integration-id SERVER_ASSIGNED_ID \
  --integration-name EXACT_NAME \
  --observed-state-file gcp-live/state/current-state.json \
  --key-file /secure/project-a.json \
  --key-file /secure/project-b.json \
  --plan-file gcp-live/state/disable-plan.json
```

For WIF, replace every `--key-file` with one
`--wif-config-file /secure/gcp_wif_config.json`. The renderer reads credentials
only to validate them and bind secret-free SHA-256 metadata; it makes no
network request. Review the exact JSON and printed hash.

### 3. Apply that exact reviewed plan

```bash
bash skills/splunk-observability-gcp-integration/scripts/setup.sh \
  --rollback disable --apply \
  --realm us1 \
  --integration-id SERVER_ASSIGNED_ID \
  --plan-file gcp-live/state/disable-plan.json \
  --plan-hash REVIEWED_SHA256 \
  --accept-disable-integration SERVER_ASSIGNED_ID \
  --token-file /secure/splunk_o11y_admin_token \
  --key-file /secure/project-a.json \
  --key-file /secure/project-b.json
```

Disable is only an enabled-to-disabled transition and reconstructs the live
authentication shape from the reviewed credential mode. Delete requires a
separately rendered `--rollback delete` plan and
`--accept-delete-integration SERVER_ASSIGNED_ID`; it rejects all key and WIF
files. Never use delete as a workaround when disable is blocked. Bare
`--rollback` renders a disable plan but cannot be applied, and
`--rollback integration` remains only as a deprecated disable alias.

See [reference.md](reference.md#reviewed-rollback-contract) for plan schema,
locking, replay, reconciliation, compatibility, and remote-race behavior.

## Workload Identity Federation

WIF avoids a Service Account private key. Obtain `gcp_wif_config.json` from
Splunk's supported integration workflow and keep it unchanged. The skill does
not generate that document and does not infer any realm identity.

```yaml
authentication:
  mode: workload_identity_federation
  workload_identity_federation:
    config_file: "/secure/path/gcp_wif_config.json"
```

```bash
chmod 600 /secure/path/gcp_wif_config.json
bash skills/splunk-observability-gcp-integration/scripts/setup.sh \
  --apply --spec my-wif-spec.yaml --realm us1 \
  --token-file /secure/path/splunk_o11y_token \
  --wif-config-file /secure/path/gcp_wif_config.json
```

The live request uses `authMethod: WORKLOAD_IDENTITY_FEDERATION` and injects
the complete document as compact/stringified JSON in
`workloadIdentityFederationConfig`. The upstream SignalFx Terraform provider
supports WIF and projects arguments. This skill intentionally keeps WIF on its
reviewed REST path and does not currently generate the Terraform WIF resource
or gcloud pool/provider scripts.

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
