# AppDynamics Coverage

The authoritative coverage source is `appdynamics-taxonomy.yaml`. The renderer
copies matching rows into each skill's `coverage-report.json`.

Coverage is intentionally conservative:

- API operations are marked `api_apply` only when the AppDynamics documentation
  exposes a supported API path.
- Host and local CLI actions are `cli_apply` and require reviewed command plans.
- Kubernetes changes are `k8s_apply` and require explicit rollout acceptance.
- UI-only, support-gated, or third-party operations are `render_runbook` or
  `delegated_apply`.
- Observed-only surfaces are `validate_only`.

The parent fails coverage checks if any row lacks owner, source URL, status,
validation method, or apply boundary.
