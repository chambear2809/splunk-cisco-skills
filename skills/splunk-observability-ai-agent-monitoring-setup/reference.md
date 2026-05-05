# Splunk Observability AI Agent Monitoring Setup Reference

## CLI

```bash
bash skills/splunk-observability-ai-agent-monitoring-setup/scripts/setup.sh [MODE] [OPTIONS]
```

Modes:

| Mode | Behavior |
|------|----------|
| `--render` | Default. Writes the rendered plan tree. |
| `--validate` | Validates a rendered tree. Composable with `--render`. |
| `--doctor` | Renders and emits `doctor-report.md` with prioritized fixes. |
| `--discover` | Prints the source/package/product catalog without live mutation. |
| `--refresh-package-catalog` | Queries PyPI for current package metadata and writes `package-catalog-refreshed.json`. |
| `--apply [SECTIONS]` | Renders first, then applies selected safe sections. |

Apply sections: `collector`, `hec`, `loc`, `python-runtime`, `kubernetes-runtime`, `ai-infra-collector`, `dashboards`, `detectors`.

Important options:

| Option | Purpose |
|--------|---------|
| `--spec PATH` | JSON/YAML spec. Defaults to `template.example`. |
| `--output-dir PATH` | Rendered output directory. |
| `--realm REALM` | Override spec realm. |
| `--collector-mode kubernetes|linux` | Pick collector apply path. |
| `--workload-kind deployment\|statefulset\|daemonset` | Kubernetes app workload kind for the runtime handoff patch. |
| `--workload-namespace NAME` | Kubernetes app workload namespace for generated dry-run/apply commands. |
| `--workload-name NAME` | Kubernetes app workload name for the runtime handoff patch. |
| `--container-name NAME` | Target container name inside the app workload. |
| `--frameworks CSV` | Override GenAI framework selection. |
| `--translators CSV` | Override third-party translator selection. |
| `--ai-infra-products CSV` | Override AI Infrastructure Monitoring products. |
| `--enable-content-capture` | Request prompt/response content capture. Requires acceptance. |
| `--accept-content-capture` | Explicitly accept content exposure risk. |
| `--enable-evaluations` | Request instrumentation-side evaluations. Requires acceptance. |
| `--accept-evaluation-cost` | Explicitly accept LLM-as-judge content/cost risk. |
| `--o11y-token-file PATH` | File-backed Splunk Observability token for delegated apply. |
| `--platform-hec-token-file PATH` | File-backed HEC token for collector log exporter. |
| `--service-account-password-file PATH` | File-backed LOC service-account password for delegated LOC apply. |

Direct secret flags such as `--token`, `--access-token`, `--api-token`, `--o11y-token`, `--sf-token`, `--hec-token`, and `--password` are rejected.

## Generated Artifacts

| Path | Contents |
|------|----------|
| `metadata.json` | Render summary, warnings, validation errors, coverage counts. |
| `coverage-report.json` | Machine-readable feature/product coverage ledger. |
| `coverage-report.md` | Human-readable coverage tables. |
| `apply-plan.json` | Apply sections, exact delegated commands, coverage status. |
| `runtime/python.env` | GenAI runtime environment variables. |
| `runtime/requirements.txt` | PyPI package set for selected frameworks/evaluations/translators. |
| `collector/values-ai-agent-monitoring.yaml` | Collector overlay with histogram support. |
| `collector/splunk-hec-logs-overlay.yaml` | Log exporter overlay for evaluation/content events. |
| `kubernetes/deployment-env-patch.yaml` | Strategic-merge env patch for the selected workload/container. |
| `scripts/apply-kubernetes-runtime.sh` | Prints exact `kubectl patch --type strategic` dry-run and apply commands for the rendered workload target. |
| `handoffs/cloud-integration-loc.spec.json` | Delegated Log Observer Connect spec stub. |
| `dashboards/handoff-dashboard.spec.json` | Dashboard-builder handoff spec. |
| `detectors/handoff-native-ops.spec.json` | Native-ops detector handoff spec. |
| `doctor-report.md` | Prioritized remediation checklist. |

## Coverage Statuses

- `delegated_apply`: a repo skill owns safe apply.
- `render`: this skill renders deterministic config/handoff assets.
- `validate`: this skill validates a required condition.
- `deeplink`: deterministic UI path or URL; do not claim API apply.
- `handoff`: clear operator or child-skill instructions.
- `not_applicable`: disabled by spec.

No coverage entry may use `unknown`.
