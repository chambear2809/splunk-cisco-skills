# Workshop / Multi-Tenant Mode

Workshop mode renders an OpenShift helper for an existing set of participant
namespaces. It does not create participant namespaces, add tenant attributes to
collector pipelines, or render tenant-specific dashboards.

## Intake

Configure the mode in the spec:

```yaml
workshop_mode:
  enabled: true
  participant_namespace_prefix: workshop-participant
  participant_count: 30
```

Alternatively, `--workshop-mode` enables the helper while the prefix and count
continue to come from the spec defaults. The namespace prefix must be a
lowercase Kubernetes name prefix no longer than 50 characters. Participant
count must be from 1 through 1000.

## Rendered Helper

When workshop mode is enabled, the umbrella renders
`workshop/multi-tenant.sh`. Run it from the rendered bundle after review:

```bash
bash splunk-observability-cisco-ai-pod-rendered/workshop/multi-tenant.sh
```

The helper also accepts reviewed prefix and count overrides as positional
arguments:

```bash
bash splunk-observability-cisco-ai-pod-rendered/workshop/multi-tenant.sh \
  workshop-participant 30
```

Before changing anything, it verifies that every expected namespace already
exists (`<prefix>-1` through `<prefix>-<count>`). If any namespace is absent,
the helper exits without performing the per-namespace loop.

For each existing namespace, it:

1. creates a `splunk-otel-collector` ServiceAccount when absent;
2. applies a ClusterRoleBinding to the existing
   `splunk-otel-collector` ClusterRole; and
3. grants the `splunk-otel-collector` SCC to that ServiceAccount with `oc`.

The helper requires an authenticated `oc` session and sufficient permissions
to create ServiceAccounts and ClusterRoleBindings and to grant an SCC. Review
the cluster-wide role binding and SCC implications before running it.

## Scope Boundary

The current workshop mode is a shared cluster-receiver access pattern. It does
not provide hard telemetry isolation between participants, provision one
collector per tenant, or create per-tenant Splunk Observability organizations
or tokens. Use separate collectors and appropriately scoped destinations when
hard tenant isolation is required.

The umbrella's standard AI-Pod dashboards still filter on
`k8s.cluster.name`; workshop mode does not add a `tenant` resource processor or
`workshop-tenant-overview.signalflow.yaml`.

## Lifecycle

Provision or remove participant namespaces through the workshop's owning
cluster workflow. Re-render the bundle after changing the configured prefix or
count, then review and rerun the helper. Deleting a participant namespace also
deletes its namespaced ServiceAccount, but the cluster-scoped
`splunk-otel-collector-<namespace>` ClusterRoleBinding must be reviewed and
removed separately if it is no longer needed.
