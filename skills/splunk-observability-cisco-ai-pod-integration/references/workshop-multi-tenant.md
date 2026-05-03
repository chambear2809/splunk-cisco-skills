# Workshop / multi-tenant mode

When `--workshop-mode true`, the umbrella renders a multi-tenant variant designed for Cisco's AI Pod customer workshops, where one cluster hosts multiple tenant namespaces and each tenant's metrics need to be isolated by `tenant` label.

## What changes in workshop mode

Three things:

1. **Tenant ServiceAccount per namespace**. Each tenant namespace gets its own ServiceAccount + Role + RoleBinding so tenants can't list pods/services outside their namespace.
2. **Tenant attribution processor**. The OTel agent adds a `tenant` resource attribute derived from the pod's namespace name (e.g. `tenant-alice`, `tenant-bob`).
3. **Tenant-scoped dashboards**. Dashboards filter by the `tenant` attribute so each tenant only sees their own metrics in the same O11y org.

## Workshop setup script

The umbrella renders `scripts/install-workshop-tenants.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Create a Splunk OTel ServiceAccount per tenant namespace.
TENANTS=("alice" "bob" "carol")

for tenant in "${TENANTS[@]}"; do
    namespace="tenant-${tenant}"
    
    kubectl create namespace "${namespace}" --dry-run=client -o yaml | kubectl apply -f -
    kubectl label namespace "${namespace}" tenant="${tenant}" --overwrite
    
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: splunk-otel-tenant
  namespace: ${namespace}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: splunk-otel-tenant
  namespace: ${namespace}
rules:
  - apiGroups: [""]
    resources: ["pods", "services", "endpoints"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: splunk-otel-tenant
  namespace: ${namespace}
subjects:
  - kind: ServiceAccount
    name: splunk-otel-tenant
    namespace: ${namespace}
roleRef:
  kind: Role
  name: splunk-otel-tenant
  apiGroup: rbac.authorization.k8s.io
EOF
done
```

The umbrella renders this with the actual tenant names from `spec.workshop.tenants` (default: 3 tenants).

## OTel agent config additions for workshop mode

The umbrella's overlay adds a `transform/tenant` processor:

```yaml
processors:
  transform/tenant:
    metric_statements:
      - context: resource
        statements:
          - set(attributes["tenant"], attributes["k8s.namespace.name"])
            where IsMatch(attributes["k8s.namespace.name"], "^tenant-.*$")
service:
  pipelines:
    metrics:
      processors: [..., transform/tenant, batch]
```

Every metric from a `tenant-*` namespace gets a `tenant` resource attribute. Other namespaces (e.g. `kube-system`) don't get this attribute, which means default dashboards can filter by `tenant.exists()` to scope to tenant workloads.

## Tenant-scoped dashboards

The umbrella renders one extra dashboard `dashboards/workshop-tenant-overview.signalflow.yaml`:

```yaml
name: "Workshop Tenant Overview"
description: "Per-tenant view of GPU, NIM, vLLM, network metrics."
filters:
  - property: tenant
    value: ${TENANT_NAME}
charts:
  - name: GPU utilization
    program_text: |
      data('DCGM_FI_DEV_GPU_UTIL', filter=filter('tenant', '${TENANT_NAME}'))
        .mean_by(['gpu'])
        .publish('per_gpu_util')
```

In workshop mode, each tenant gets one copy of this dashboard with their tenant name pre-filled. The dashboard-builder skill supports parameterized dashboards via the `${TENANT_NAME}` placeholder.

## RBAC isolation

The OTel collector ServiceAccount STILL has cluster-wide list-pods access (required to discover NIM/vLLM/etc. across all namespaces). The per-tenant ServiceAccounts created by the workshop script are NOT used by the OTel collector itself; they're used by the tenant's own application pods if the workshop curriculum requires them.

If you need TRUE cross-tenant RBAC isolation (no single SA reads all namespaces), you'd need one OTel agent DaemonSet per tenant. That's much more complex and not currently supported by the umbrella; reach out for guidance if needed.

## Tenant lifecycle

Adding a tenant after initial setup:

```bash
TENANT=daniel
kubectl create namespace "tenant-${TENANT}"
kubectl label namespace "tenant-${TENANT}" tenant="${TENANT}"
# Re-run the workshop script (it's idempotent), or just create the SA/Role/RoleBinding manually.
# The OTel agent's transform/tenant processor will pick up the new namespace automatically.
```

Removing a tenant:

```bash
kubectl delete namespace "tenant-${TENANT}"
```

The OTel agent will stop emitting metrics from the namespace; existing series in O11y will eventually age out per the org's retention policy.

## Anti-patterns

- **Using the same OTel access token across tenant clusters**: workshop mode is a single-cluster, single-O11y-org pattern. Don't apply this to multi-cluster setups; use one collector per cluster, each with its own access token, and aggregate at the O11y dashboard layer.
- **Tenant names with special characters**: stick to `[a-z0-9-]` for namespace and tenant attribute compatibility.
- **Storing per-tenant credentials in a single Secret**: each tenant should have isolated credentials if they're connecting to external services. Don't share a single AWS key across all tenants.
