# Splunk Observability Cloud — Azure Integration Reference

Operator reference for the
[`splunk-observability-azure-integration`](SKILL.md) skill.

## REST API

- Endpoint: `https://api.<realm>.observability.splunkcloud.com/v2/integration[/{id}]`
- Auth header: `X-SF-Token`. Read-only `GET` accepts an API-scoped organization
  token or any session/User API access token. `POST`, exact-ID `PUT`, and
  exact-ID `DELETE` require a session/User API access token associated with an
  administrator.
- Successful `GET`, `POST`, `PUT`, and `DELETE` responses are HTTP 200. DELETE
  has no response body; exact-ID GET for a missing integration is HTTP 200 with
  an empty body.
- Collection GET uses the official `count` plus `results` envelope with
  `limit`/`offset` pagination and a documented 10,000-object cap. Name or
  duplicate decisions fail closed at or above that cap.
- Integration `type` discriminator: **`Azure`** (exact case)
- Source of truth for the wire contract: `signalfx/signalfx-go` model
  `integration/model_azure_integration.go` + TF provider `signalfx_azure_integration`.

Authoritative sources: [Splunk Integrations API](https://dev.splunk.com/observability/reference/api/integrations/latest)
and [Microsoft Azure integration guide](https://dev.splunk.com/observability/docs/integrations/msazure_integration_overview/).

## Canonical field set

| Spec field | Wire JSON name | Type | Notes |
|-----------|---------------|------|-------|
| `integration_name` | `name` | string | required |
| `authentication.tenant_id` | `tenantId` | string | required |
| `authentication.app_id_file` (content) | `appId` | string | **omitted on GET** |
| `authentication.secret_file` (content) | `secretKey` | string | **omitted on GET** |
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
| (enabled) | `enabled` | bool | explicit Boolean required on every write |

Read-only fields retained for review and stripped on PUT are `created`,
`lastUpdated`, `creator`, `lastUpdatedBy`, `createdByName`,
`lastUpdatedByName`, and `id`. The timestamps must be JSON integers (not
Booleans); creator IDs are strings; display names may be strings or null.
Responses that unexpectedly contain the documented omitted credentials
`appId` or `secretKey` are protocol violations and are never normalized into a
reviewed state.

Captured implementation evidence uses `customNamespacesPerService` as
`map[string][]string`, despite a conflicting generated-schema map value type;
the skill preserves that observed shape. Every `resourceFilterRules` item is
instead validated as the exact documented `{filter: {source: string}}` object.

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

Azure GET omits `appId` and `secretKey`. Every credential-bearing PUT therefore
reconstructs both fields from explicit, owned, regular mode-600 files. The
client reads each file once, uses those same bytes for the payload and SHA-256
metadata, and rejects missing, partial, changed, symlinked, or insecure inputs
before transport. Credential contents never enter plans, journals, logs, or
terminal output; validated file paths may appear in diagnostic errors.

## Reviewed rollback contract

1. `--discover` performs a read-only, fully paginated GET and privately writes
   `state/current-state.json`. The snapshot is bounded to 4 MiB and has the
   exact schema `schema_version`, `provider`, `realm`, `captured_at`, `count`,
   and `results`.
2. Offline `--rollback disable|delete` requires the snapshot, exact immutable
   server ID, and exact expected name. It selects exactly one `Azure` result and
   writes a bounded 64 KiB mode-600 plan containing a random UUID4 `plan_id`,
   reviewed action/identity/enabled state, complete sanitized `reviewed_state`,
   its SHA-256 fingerprint, and—only for disable—credential-file SHA-256
   bindings. Plans preserve exact schema-safe names.
3. Mutation requires `--apply`, `--plan-hash SHA256`, and exactly one matching
   action-bound acknowledgement: `--accept-disable-integration ID` or
   `--accept-delete-integration ID`. Bare `--rollback` cannot apply. Disable
   requires reviewed `enabled: true`; delete may intentionally review either
   Boolean state and rejects credential inputs.
4. Before a mutation, the client validates credentials from memory, acquires a
   canonical per-user provider/realm/ID lock, re-lists the complete collection
   to prove name uniqueness, and performs two exact-ID reads. Both reads must
   match the reviewed type, ID, name, Boolean enabled state, and complete
   reviewed fingerprint. Only then does the client create an exclusive durable
   consumed marker in the canonical lock root, followed by the plan-adjacent
   receipt and attempt journal. Failure to write either latter record aborts
   before mutation.
5. PUT or DELETE is dispatched exactly once and is never retried. Ambiguous
   status, read, decode, timeout, or incomplete-response failures are reconciled
   with exact-ID GET and still require operator resolution. Disable must observe
   `enabled: false` twice and an unchanged non-enabled configuration
   fingerprint. Delete requires HTTP 200 with zero response bytes and then two
   consecutive HTTP-200 empty exact-ID GETs. Every attempted plan remains
   burned; recovery requires read-only reconciliation and a newly rendered
   plan.

Disable plans additionally require a supported `azureEnvironment` and a
`pollRate` from 60000 through 600000 milliseconds. Delete plans may review an
otherwise well-typed forward-compatible enum or legacy interval because delete
does not reconstruct a credential-bearing provider payload.

All state and lock files are owned regular mode-600 files with symlink-safe
directory traversal. Upsert also serializes its name decision locally and
locks an existing immutable ID. Splunk documents no conditional revision or
ETag operation, so these local controls and repeated reads narrow but cannot
eliminate changes made concurrently from another host. Never recommend delete
when disable is blocked.

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

Pin the provider version reviewed for the operator's environment.

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
