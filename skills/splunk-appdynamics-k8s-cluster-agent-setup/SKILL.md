---
name: splunk-appdynamics-k8s-cluster-agent-setup
description: >-
  Render, validate, and gate Splunk AppDynamics Kubernetes Cluster Agent,
  Kubernetes auto-instrumentation, and Splunk OpenTelemetry Collector setup
  through the Cluster Agent, including dual-signal combined-agent plans for
  Java, .NET Core Linux, Node.js, Machine Agent handoff, and Splunk
  Observability Cloud export validation. Use when the user asks for
  AppDynamics Cluster Agent, Kubernetes monitoring, AppDynamics Kubernetes
  auto-instrumentation, Splunk OTel Collector through Cluster Agent, O11y
  export, or workload rollout validation.
---

# Splunk AppDynamics Kubernetes Cluster Agent Setup

Kubernetes mutations require `--accept-k8s-rollout`. Render mode writes Helm
values, O11y collector values, secret templates, combined-agent workload
patches, and validation runbooks without touching the active cluster.

```bash
bash skills/splunk-appdynamics-k8s-cluster-agent-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-k8s-cluster-agent-setup/scripts/validate.sh
```

Read-only Controller API validation for Cluster Agent availability can be run
with file-backed credentials:

```bash
bash skills/splunk-appdynamics-k8s-cluster-agent-setup/scripts/poll_cluster_agent_availability.sh \
  --application 'Server & Infrastructure Monitoring' \
  --duration-mins 5
```

The probe defaults to
`Application Infrastructure Performance|Root|Individual Nodes|*|Cluster Agent|Availability`
so it can read every visible Cluster Agent under Server Visibility. Pass
`--metric-path` only when you want to pin validation to a copied full path for
one Cluster Agent.

A disabled Server Visibility health rule for Cluster Agent availability can be
rendered first, then applied after the API client has Server health-rule
permissions:

```bash
bash skills/splunk-appdynamics-k8s-cluster-agent-setup/scripts/create_cluster_agent_availability_health_rule.sh

bash skills/splunk-appdynamics-k8s-cluster-agent-setup/scripts/create_cluster_agent_availability_health_rule.sh \
  --apply
```

Typical flow:

1. Edit `template.example` or pass `--spec <file>` with Controller, cluster,
   Splunk Observability realm, token file path, and workload targets.
2. Render first and review `cluster-agent-values.yaml`,
   `splunk-otel-collector-values.yaml`, `dual-signal-workload-env.yaml`, and
   `cluster-agent-rollout-plan.sh`.
3. Keep O11y tokens, the Controller password, and the Controller access key
   file-backed. The rollout plan uses `--set-file`; it does not render values.
4. Execute the reviewed rollout only after explicit approval:

```bash
bash skills/splunk-appdynamics-k8s-cluster-agent-setup/scripts/setup.sh \
  --apply rollout --accept-k8s-rollout --spec path/to/spec.yaml
```

The wrapper renders and then executes `cluster-agent-rollout-plan.sh` with the
mutation gate enabled. Running that rendered script directly remains dry-run by
default and requires `K8S_APPLY=1` before it mutates Kubernetes.

Controller URLs default to HTTPS. Plain HTTP requires the explicit
`accept_insecure_controller_http: true` exception. The O11y validation API is
restricted to `https://api.<realm>.signalfx.com`; a reviewed proxy additionally
requires `splunk_otel_collector.accept_custom_api_url: true`. Live O11y
validation fails when its chmod-600 token file, Helm-release pods, readiness, or
collector log access is unavailable; it never reports a skipped probe as a pass.
