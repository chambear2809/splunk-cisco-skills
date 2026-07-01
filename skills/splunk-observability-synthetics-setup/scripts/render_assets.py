#!/usr/bin/env python3
"""Render focused Observability wrapper assets for Synthetics, SLOs, and MPM."""

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    if path.suffix == ".sh":
        path.chmod(0o755)


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def render_synthetics(args: argparse.Namespace, output: Path) -> list[str]:
    payload = {
        "name": args.name,
        "url": args.url or "https://example.com",
        "frequency": int(args.frequency),
        "locations": [args.location],
    }
    spec = {
        "api_version": "splunk-observability-native-ops/v1",
        "realm": args.realm,
        "synthetics": [
            {
                "kind": args.kind,
                "name": args.name,
                "payload": payload,
                "run_now": bool(args.run_now),
                "artifacts": [
                    {
                        "run_id": "latest",
                        "location_id": args.location,
                        "filename": "network.har",
                    }
                ],
            }
        ],
    }
    files = [
        "synthetics-plan.md",
        "native-ops-spec.json",
        "delegate-native-ops.sh",
        "waterfall-handoff.md",
        "metadata.json",
    ]
    write(
        output / "synthetics-plan.md",
        f"""# Synthetic Monitoring Plan

Test name: `{args.name}`
Kind: `{args.kind}`
URL: `{args.url or 'https://example.com'}`
Realm: `{args.realm}`
Location: `{args.location}`
Frequency: `{args.frequency}` minutes

Review `native-ops-spec.json`, then render or apply through
`splunk-observability-native-ops`.
""",
    )
    write(output / "native-ops-spec.json", json.dumps(spec, indent=2, sort_keys=True))
    write(
        output / "delegate-native-ops.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
REPO_ROOT="${{SPLUNK_CISCO_SKILLS_ROOT:-$(git -C "${{SCRIPT_DIR}}" rev-parse --show-toplevel 2>/dev/null || pwd)}}"
MODE="${{1:---render}}"
case "${{MODE}}" in
  --render|--apply) shift ;;
  *) MODE=--render ;;
esac
exec bash "${{REPO_ROOT}}/skills/splunk-observability-native-ops/scripts/setup.sh" \
  "${{MODE}}" --validate --spec "${{SCRIPT_DIR}}/native-ops-spec.json" \
  --realm {shlex.quote(args.realm)} "$@"
""",
    )
    write(
        output / "waterfall-handoff.md",
        """# Synthetic Waterfall Handoff

After the test runs, use `splunk-observability-native-ops` to list runs and
retrieve waterfall, HAR, screenshot, filmstrip, or video artifacts when the
test/run coordinates are known.
""",
    )
    write(output / "metadata.json", json.dumps({"skill": "splunk-observability-synthetics-setup", "files": files, "spec": spec}, indent=2, sort_keys=True))
    return files


def render_slo(args: argparse.Namespace, output: Path) -> list[str]:
    payload = {
        "name": args.name,
        "type": "RequestBased",
        "inputs": [
            {
                "sli_source": args.sli_source,
                "service": args.service or "<service-name>",
                "environment": args.environment,
            }
        ],
        "targets": [{"target": float(args.target), "window": args.window}],
    }
    spec = {
        "api_version": "splunk-observability-deep-native-workflows/v1",
        "realm": args.realm,
        "context": {"service": args.service, "environment": args.environment},
        "workflows": [
            {
                "surface": "slo_creation",
                "name": args.name,
                "service": args.service,
                "environment": args.environment,
                "payload": payload,
                "checks": ["sli_source", "error_budget", "burn_rate_detectors", "dashboard_links"],
            }
        ],
    }
    files = [
        "slo-plan.md",
        "slo-payload-intent.json",
        "deep-native-workflow-spec.json",
        "delegate-deep-native-workflows.sh",
        "metadata.json",
    ]
    write(
        output / "slo-plan.md",
        f"""# SLO Setup Plan

SLO name: `{args.name}`
Service: `{args.service or '<service-name>'}`
Environment: `{args.environment}`
Target: `{args.target}`
Window: `{args.window}`
SLI source: `{args.sli_source}`

Review `slo-payload-intent.json` before using the downstream `/slo/validate`
and `/slo` action plan emitted by `splunk-observability-deep-native-workflows`.
""",
    )
    write(output / "slo-payload-intent.json", json.dumps(payload, indent=2, sort_keys=True))
    write(output / "deep-native-workflow-spec.json", json.dumps(spec, indent=2, sort_keys=True))
    write(
        output / "delegate-deep-native-workflows.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
bash skills/splunk-observability-deep-native-workflows/scripts/setup.sh --render --validate --spec "${{SCRIPT_DIR}}/deep-native-workflow-spec.json" --realm {shlex.quote(args.realm)}
""",
    )
    write(output / "metadata.json", json.dumps({"skill": "splunk-observability-slo-setup", "files": files, "spec": spec}, indent=2, sort_keys=True))
    return files


def render_mpm(args: argparse.Namespace, output: Path) -> list[str]:
    dimensions = split_csv(args.dimensions)
    intent = {
        "name": args.name,
        "metric": args.metric,
        "action": args.action,
        "dimensions": dimensions,
        "exceptions": [],
    }
    spec = {
        "api_version": "splunk-observability-deep-native-workflows/v1",
        "realm": args.realm,
        "workflows": [
            {
                "surface": "metrics_pipeline_management",
                "name": args.name,
                "metric": args.metric,
                "action": args.action,
                "dimensions": dimensions,
                "checks": ["metric_usage", "mts_cardinality", "impact_preview", "exception_review"],
                "intent": intent,
            }
        ],
    }
    files = [
        "metrics-pipeline-plan.md",
        "mpm-intent.json",
        "deep-native-workflow-spec.json",
        "delegate-deep-native-workflows.sh",
        "metadata.json",
    ]
    write(
        output / "metrics-pipeline-plan.md",
        f"""# Metrics Pipeline Management Plan

Workflow: `{args.name}`
Metric: `{args.metric}`
Action: `{args.action}`
Dimensions: `{', '.join(dimensions) if dimensions else '<none>'}`

Use this for Observability Cloud MPM. Use OTel Collector, Edge Processor,
Ingest Processor, or SPL2 skills for broader telemetry pipeline processing.
""",
    )
    write(output / "mpm-intent.json", json.dumps(intent, indent=2, sort_keys=True))
    write(output / "deep-native-workflow-spec.json", json.dumps(spec, indent=2, sort_keys=True))
    write(
        output / "delegate-deep-native-workflows.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
bash skills/splunk-observability-deep-native-workflows/scripts/setup.sh --render --validate --spec "${{SCRIPT_DIR}}/deep-native-workflow-spec.json" --realm {shlex.quote(args.realm)}
""",
    )
    write(output / "metadata.json", json.dumps({"skill": "splunk-observability-metrics-pipeline-setup", "files": files, "spec": spec}, indent=2, sort_keys=True))
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", choices=["synthetics", "slo", "mpm"], required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--realm", default="us0")
    parser.add_argument("--name", required=True)
    parser.add_argument("--kind", default="browser")
    parser.add_argument("--url", default="")
    parser.add_argument("--frequency", default="5")
    parser.add_argument("--location", default="aws-us-east-1")
    parser.add_argument("--run-now", action="store_true")
    parser.add_argument("--service", default="")
    parser.add_argument("--environment", default="prod")
    parser.add_argument("--target", default="99.9")
    parser.add_argument("--window", default="30d")
    parser.add_argument("--sli-source", default="apm_service")
    parser.add_argument("--metric", default="service.request.duration")
    parser.add_argument("--action", default="aggregate")
    parser.add_argument("--dimensions", default="service.name,deployment.environment")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    output = Path(args.output_dir).expanduser().resolve()
    if args.surface == "synthetics":
        files = render_synthetics(args, output)
    elif args.surface == "slo":
        files = render_slo(args, output)
    else:
        files = render_mpm(args, output)

    result = {"ok": True, "surface": args.surface, "output_dir": str(output), "files": files}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Rendered {args.surface} assets to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
