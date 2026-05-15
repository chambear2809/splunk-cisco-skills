# Splunk Observability Cloud — Azure Integration Reference

Operator reference for the
[`splunk-observability-azure-integration`](SKILL.md) skill.

## REST API

- Endpoint: `https://api.<realm>.observability.splunkcloud.com/v2/integration[/{id}]`
- Auth: `X-SF-Token: <admin user API access token>`
- `POST` → create (201), `GET` → read (200), `PUT` → update (200), `DELETE` → (204)
- Integration `type` discriminator: **`Azure`** (exact case)
- Source of truth for the wire contract: `signalfx/signalfx-go` model
  `integration/model_azure_integration.go` + TF provider `signalfx_azure_integration`.

## Canonical field set

| Spec field | Wire JSON name | Type | Notes |
|-----------|---------------|------|-------|
| `integration_name` | `name` | string | required |
| `authentication.tenant_id` | `tenantId` | string | required |
| `authentication.app_id_file` (content) | `appId` | string | **redacted on GET** |
| `authentication.secret_file` (content) | `secretKey` | string | **redacted on GET** |
| `azure_environment` | `azureEnvironment` | enum | `AZURE` or `AZURE_US_GOVERNMENT` |
| `subscriptions[]` | `subscriptions` | []string | required; ≥1 |
| `connection.poll_rate_seconds` × 1000 | `pollRate` | int64 (ms) | 60000–600000 ms |
| `connection.use_batch_api` | `useBatchApi` | *bool | |
| `connection.import_azure_monitor` | `importAzureMonitor` | *bool | default true |
| `connection.sync_guest_os_namespaces` | `syncGuestOsNamespaces` | bool | |
| `services.explicit` | `services` | []string | lowercase `microsoft.<rp>/<type>` |
| `services.additional_services` | `additionalServices` | []string | arbitrary namespace |
| `services.custom_namespaces_per_service` | `customNamespacesPerService` | map[string][]string | |
| `resource_filter_rules[].filter_source` | `resourceFilterRules[].filter.source` | string | SignalFlow filter expr |
| `named_token` | `namedToken` | string | ForceNew in Terraform |
| (enabled) | `enabled` | bool | set false on create, true on update |

Read-only fields (server-populated, stripped on PUT): `created`, `lastUpdated`,
`creator`, `lastUpdatedBy`, `id`.

## `azureEnvironment` valid values

| Value | Description |
|-------|-------------|
| `AZURE` | Commercial Azure (default) |
| `AZURE_US_GOVERNMENT` | Azure US Government Cloud |

Azure Germany and Azure China are **not** supported.

## Services enum

See `references/services-enum.json` for the full ~80-entry list. Notable entries:

```
microsoft.compute/virtualmachines
microsoft.compute/virtualmachinescalesets
microsoft.containerservice/managedclusters  (AKS)
microsoft.storage/storageaccounts
microsoft.sql/servers/databases
microsoft.web/sites  (App Service)
microsoft.eventhub/namespaces
microsoft.servicebus/namespaces
microsoft.network/loadbalancers
microsoft.network/applicationgateways
microsoft.keyvault/vaults
microsoft.cache/redis
microsoft.devices/iothubs
```

The wire accepts any `microsoft.<rp>/<type>` string. The built-in `services`
enum is documented but the server permits `additionalServices` for non-enumerated
namespaces.

## Credential handling

`appId` and `secretKey` are **redacted on GET** by the Splunk API — they are set
but not returned. The skill compares SHA-256 hashes of local credential files to
`state/credential-hashes.json` for drift detection. Hash mismatches prompt the
operator to re-apply credentials.

## Conflict matrix

| Rule | Enforcement |
|------|------------|
| `services` empty AND `additional_services` empty | FAIL — must subscribe to ≥1 service |
| `azure_environment=AZURE_US_GOVERNMENT` with non-GovCloud realm | WARN |
| `poll_rate_seconds` outside 60–600 | FAIL |
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

resource "signalfx_azure_integration" "this" {
  name        = var.integration_name
  enabled     = true
  tenant_id   = var.tenant_id
  app_id      = var.app_id      # sensitive; deliver via TF_VAR or vault
  secret_key  = var.secret_key  # sensitive; deliver via TF_VAR or vault
  environment = "azure"         # or "azure_us_government"
  subscriptions = var.subscriptions

  services = [
    "microsoft.compute/virtualmachines",
    "microsoft.containerservice/managedclusters",
    "microsoft.storage/storageaccounts",
  ]

  poll_rate = 300   # seconds (TF converts; wire is ms)
}
```

Latest provider version: `9.28.0`. Pin to `~> 9.0`.

## Azure CLI SP creation

```bash
az ad sp create-for-rbac \
  --name splunk-observability-o11y \
  --role "Monitoring Reader" \
  --scopes "/subscriptions/${AZ_SUB_ID}" \
  --years 2 --output json > /tmp/sp.json && chmod 600 /tmp/sp.json

SP_OBJ=$(az ad sp show --id "$(jq -r .appId /tmp/sp.json)" --query id -o tsv)
az role assignment create \
  --assignee-object-id "$SP_OBJ" \
  --assignee-principal-type ServicePrincipal \
  --role Reader \
  --scope "/subscriptions/${AZ_SUB_ID}"
```

Required roles per subscription:
- `Monitoring Reader` (id `43d0d8ad-25c7-4714-9337-8ba259a9fe05`) — read metrics
- `Reader` (id `acdd72a7-3385-48ef-bd42-f606fba81ae7`) — resource discovery

## Bicep role-assignment snippet

```bicep
targetScope = 'subscription'
param spObjectId string
var monitoringReader = '43d0d8ad-25c7-4714-9337-8ba259a9fe05'
resource ra 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, spObjectId, monitoringReader)
  properties: {
    principalId: spObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions', monitoringReader)
  }
}
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| No metrics in O11y | Wrong `tenantId` or `appId` | Re-run `--apply` with fresh credential files |
| `appId`/`secretKey` drift | Credentials rotated | Hash mismatch detected by doctor; re-apply |
| Services empty | No `services` or `additional_services` | Add at least one service |
| `namedToken` changed | ForceNew: integration recreated | Expected; old integration stops flowing data immediately |
| `AZURE_US_GOVERNMENT` + wrong realm | Realm must be a GovCloud realm | Contact Splunk for GovCloud org |
| Rate limited | Poll rate too fast | Increase `poll_rate_seconds` (300+ recommended) |
