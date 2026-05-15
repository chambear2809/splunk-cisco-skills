---
name: splunk-observability-azure-integration
description: >-
  Render, apply, validate, discover, and diagnose the Splunk Observability
  Cloud Azure integration (REST type=Azure, poll-based via Azure Monitor API).
  Covers all wire fields from signalfx/signalfx-go (tenantId, appId/secretKey
  via file-only, azureEnvironment AZURE/AZURE_US_GOVERNMENT, subscriptions,
  pollRate 60–600 s, useBatchApi, importAzureMonitor, syncGuestOsNamespaces,
  services ~80-entry enum, additionalServices, customNamespacesPerService,
  resourceFilterRules, namedToken ForceNew), Terraform signalfx_azure_integration
  (provider splunk-terraform/signalfx ~> 9.0, latest 9.28.0), Azure CLI SP
  creation (az ad sp create-for-rbac file-redirected, Monitoring Reader +
  Reader role assignments), Bicep role-assignment template (subscription-scoped
  or management-group-scoped), multi-subscription support, drift detection with
  credential-hash sidecar (appId/secretKey redacted on GET), conflict-matrix
  enforcement (services+additionalServices non-empty, poll_rate 60–600,
  namedToken ForceNew warning), and GovCloud realm guard for AZURE_US_GOVERNMENT.
  Cross-skill handoffs to splunk-app-install (Splunk_TA_microsoft_cloud_services
  Splunkbase 3110 logs), splunk-observability-otel-collector-setup (AKS host
  telemetry), splunk-observability-dashboard-builder (Azure dashboards),
  splunk-observability-native-ops (detectors), splunk-observability-cloud-
  integration-setup (Log Observer Connect), and splunk-hec-service-setup
  (HEC tokens). Use when the user asks to connect Splunk Observability Cloud
  to Azure Monitor metrics, wire the Azure integration, configure Service
  Principal credentials, or set up Azure dashboards and detectors.
---

# Splunk Observability Cloud — Azure Integration Setup

Render-first skill that owns the complete lifecycle of the Splunk O11y Azure
integration. The workflow is render-first by default. The Splunk O11y REST API
is only called when the operator explicitly runs `--apply`.

## Coverage Model

| Section | Coverage status |
|---------|----------------|
| REST payload generation | `api_validate` |
| Terraform `signalfx_azure_integration` | `handoff` |
| Azure CLI SP creation scripts | `handoff` |
| Bicep role-assignment template | `handoff` |
| Drift detection (hash-based) | `api_validate` |
| Conflict matrix enforcement | `api_validate` |
| GovCloud realm guard | `api_validate` |
| `appId` / `secretKey` redacted on GET | `api_validate` |
| Services enum validation | `api_validate` |
| `namedToken` ForceNew warning | `api_validate` |
| Cross-skill handoffs | `handoff` / `not_applicable` |

## Safety Rules

- Never ask for the Azure client secret (`secretKey`) in conversation.
- Never pass `appId` or `secretKey` as CLI arguments or env-var prefixes.
- Use `--app-id-file` and `--secret-file` (chmod 600) for file-based delivery.
- Use `write_secret_file.sh` to create secret files without shell-history exposure.
- Reject direct-secret flags: `--secret`, `--client-secret`, `--token`,
  `--password`, `--app-secret`.
- `appId` and `secretKey` are redacted on `GET /v2/integration/<id>`.
  The skill compares local file hashes to `state/credential-hashes.json`
  rather than server state.

## Five-mode UX

| Mode | Flag | Purpose |
|------|------|---------|
| render | `--render` (default) | Produces the plan tree. No Splunk or Azure API calls. |
| apply | `--apply [SECTIONS]` | Calls `POST/PUT /v2/integration`. Sections: `integration,validation`. |
| validate | `--validate [--live]` | Static plan checks + optional live `GET` probe. |
| doctor | `--doctor` | Services enum, poll-rate, namedToken, GovCloud, credential-hash checks. |
| quickstart | `--quickstart` | Render + print exact `--apply` command. |

Additional modes: `--discover`, `--quickstart-from-live`, `--explain`,
`--rollback`, `--list-services`.

## Primary Workflow

### 1. Copy and edit the spec

```bash
cp skills/splunk-observability-azure-integration/template.example my-azure-spec.yaml
# fill in realm, tenant_id, subscriptions, services
```

### 2. Write Service Principal credentials to files (once)

```bash
# Create the Azure SP and save credentials (never put secrets in history):
az ad sp create-for-rbac \
  --name splunk-observability-o11y \
  --role "Monitoring Reader" \
  --scopes "/subscriptions/${AZ_SUB_ID}" \
  --years 2 --output json > /tmp/azure-sp.json && chmod 600 /tmp/azure-sp.json

# Extract and write app ID (not a secret, but keep consistent):
jq -r .appId /tmp/azure-sp.json > /tmp/azure-app-id.txt && chmod 600 /tmp/azure-app-id.txt

# Write the client secret to a separate file:
jq -r .password /tmp/azure-sp.json > /tmp/azure-secret.txt && chmod 600 /tmp/azure-secret.txt

rm /tmp/azure-sp.json
```

### 3. Render

```bash
bash skills/splunk-observability-azure-integration/scripts/setup.sh \
  --render \
  --spec my-azure-spec.yaml \
  --realm us1 \
  --app-id-file /tmp/azure-app-id.txt \
  --secret-file /tmp/azure-secret.txt \
  --token-file /tmp/splunk_o11y_token
```

### 4. Review the plan

```
splunk-observability-azure-integration-rendered/
  01-overview.md          # plan summary + apply command
  02-services.md          # services subscription plan
  03-auth.md              # SP auth plan
  04-validation.md        # validation steps
  rest/create.json        # POST /v2/integration body
  rest/update.json        # PUT /v2/integration/{id} body
  azure-cli/create-sp.sh  # az ad sp create-for-rbac (review)
  azure-cli/grant-reader.sh # role assignment
  bicep/role-assignment.bicep # Bicep subscription-scope role assignment
  terraform/main.tf       # signalfx_azure_integration resource
  terraform/variables.tf  # variable declarations
  handoffs/               # cross-skill handoff drivers
  coverage-report.json    # per-section coverage status
```

### 5. Apply

```bash
bash skills/splunk-observability-azure-integration/scripts/setup.sh \
  --apply \
  --spec my-azure-spec.yaml \
  --realm us1 \
  --token-file /tmp/splunk_o11y_token \
  --app-id-file /tmp/azure-app-id.txt \
  --secret-file /tmp/azure-secret.txt
```

## Quickstart

```bash
bash skills/splunk-observability-azure-integration/scripts/setup.sh \
  --quickstart \
  --spec my-azure-spec.yaml \
  --realm us1
```

## Doctor

```bash
bash skills/splunk-observability-azure-integration/scripts/setup.sh \
  --doctor \
  --realm us1
```

Doctor checks: services non-empty, poll-rate 60–600, namedToken ForceNew
warning, `AZURE_US_GOVERNMENT` + non-GovCloud realm mismatch, credential-hash
freshness, and `appId`/`secretKey` redaction notice.

## Rollback

```bash
bash skills/splunk-observability-azure-integration/scripts/setup.sh \
  --rollback integration \
  --realm us1 \
  --token-file /tmp/splunk_o11y_token
```

Disables the integration in Splunk O11y (sets `enabled: false`). Use
`--rollback delete` to remove it entirely.

## Hand-offs

- Logs path → [`splunk-app-install`](../splunk-app-install/SKILL.md) for
  `Splunk_TA_microsoft_cloud_services` (Splunkbase 3110)
- AKS host telemetry → [`splunk-observability-otel-collector-setup`](../splunk-observability-otel-collector-setup/SKILL.md)
- Azure dashboards → [`splunk-observability-dashboard-builder`](../splunk-observability-dashboard-builder/SKILL.md)
- Azure detectors → [`splunk-observability-native-ops`](../splunk-observability-native-ops/SKILL.md)
- Log Observer Connect → [`splunk-observability-cloud-integration-setup`](../splunk-observability-cloud-integration-setup/SKILL.md)
- HEC tokens → [`splunk-hec-service-setup`](../splunk-hec-service-setup/SKILL.md)
- AppDynamics on Azure → [`cisco-appdynamics-setup`](../cisco-appdynamics-setup/SKILL.md)

## Out of Scope

- Azure Event Hub streaming (not in the Splunk O11y wire contract as a separate
  integration type; `importAzureMonitor` controls metric-vs-metadata-only)
- Azure log ingestion (Splunk_TA_microsoft_cloud_services, Splunkbase 3110 — handed off)
- Managed Identity authentication (Splunk O11y requires a Service Principal)
- Workload Identity Federation for Azure (not in the wire contract)
- Azure China (AzureChinaCloud) — not supported by this integration

## Validation

```bash
bash skills/splunk-observability-azure-integration/scripts/validate.sh \
  --output-dir splunk-observability-azure-integration-rendered
```

Static checks: required files, JSON shape (`type: Azure`), no secret-looking
content in rendered files. With `--live`: `GET /v2/integration` probe.
