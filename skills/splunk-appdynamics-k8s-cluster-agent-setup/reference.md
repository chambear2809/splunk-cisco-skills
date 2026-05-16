# Kubernetes Cluster Agent Reference

Primary sources:

- https://help.splunk.com/en/appdynamics-saas/infrastructure-visibility/26.4.0/monitor-kubernetes-with-the-cluster-agent/use-the-cluster-agent
- https://help.splunk.com/en/appdynamics-saas/infrastructure-visibility/26.4.0/monitor-kubernetes-with-the-cluster-agent/permissions-required-for-cluster-agent-and-infrastructure-visibility
- https://help.splunk.com/en/appdynamics-saas/infrastructure-visibility/26.4.0/monitor-kubernetes-with-the-cluster-agent/installation-overview/cluster-agent-and-the-operator-compatibility-matrix
- https://help.splunk.com/en/appdynamics-on-premises/infrastructure-visibility/26.4.0/monitor-kubernetes-with-the-cluster-agent/installation-overview/install-splunk-otel-collector-using-cluster-agent
- https://help.splunk.com/en/appdynamics-saas/application-performance-monitoring/26.4.0/splunk-appdynamics-for-opentelemetry/instrument-applications-with-splunk-appdynamics-for-opentelemetry/monitor-applications-and-infrastructure-with-combined-agent
- https://help.splunk.com/en/appdynamics-saas/application-performance-monitoring/26.4.0/splunk-appdynamics-for-opentelemetry/instrument-applications-with-splunk-appdynamics-for-opentelemetry/enable-opentelemetry-in-the-java-agent/enable-dual-signal-mode
- https://help.splunk.com/en/appdynamics-saas/application-performance-monitoring/26.4.0/splunk-appdynamics-for-opentelemetry/instrument-applications-with-splunk-appdynamics-for-opentelemetry/enable-opentelemetry-in-the-.net-agent/enable-the-combined-mode-for-.net-agent
- https://help.splunk.com/en/appdynamics-on-premises/application-performance-monitoring/26.3.0/splunk-appdynamics-for-opentelemetry/instrument-applications-with-splunk-appdynamics-for-opentelemetry/enable-opentelemetry-in-the-node.js-agent/dual-signal-mode-for-node.js-combined-agent
- https://help.splunk.com/en/appdynamics-saas/infrastructure-visibility/26.4.0/machine-agent/combined-agent-for-infrastructure-visibility

The renderer emits Helm values, RBAC review, workload instrumentation patches,
rollout plans, and validation steps for Cluster Agent registration,
auto-instrumentation, combined-agent dual-signal workload environment, and
Splunk OTel Collector wiring to Splunk Observability Cloud.

Generated artifacts:

- `cluster-agent-values.yaml`: AppDynamics Cluster Agent chart values with
  `installSplunkOtelCollector`, Controller secret placeholders, instrumentation
  targets, and O11y collector values.
- `splunk-otel-collector-values.yaml`: standalone collector values for review or
  handoff to the Splunk OTel Collector skill.
- `splunk-otel-secret-template.yaml`: Kubernetes Secret template with token
  placeholder only.
- `workload-instrumentation-patches.yaml`: GitOps-friendly workload patches.
- `dual-signal-workload-env.yaml`: exact env vars rendered per workload.
- `combined-agent-o11y-runbook.md`: language and mode guidance for dual,
  OTel-only, and AppDynamics-only rollouts.
- `cluster-agent-rollout-plan.sh`: dry-run by default; live mutation requires
  `K8S_APPLY=1` after the skill has been invoked with `--accept-k8s-rollout`.
- `cluster-agent-validation-probes.sh` and `o11y-export-validation.sh`: live
  Kubernetes and Splunk Observability validation probes.
