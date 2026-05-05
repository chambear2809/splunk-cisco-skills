#!/usr/bin/env bash
set -euo pipefail

OUTPUT_DIR=""
JSON_OUTPUT=false
DOCTOR=false

usage() {
    cat <<'EOF'
Validate rendered Splunk AI Agent Monitoring setup output.

Usage:
  validate.sh --output-dir PATH [--json] [--doctor]
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        --json) JSON_OUTPUT=true; shift ;;
        --doctor) DOCTOR=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

if [[ -z "${OUTPUT_DIR}" ]]; then
    echo "ERROR: --output-dir is required." >&2
    exit 1
fi

python3 - "${OUTPUT_DIR}" "${JSON_OUTPUT}" "${DOCTOR}" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

output_dir = Path(sys.argv[1])
json_output = sys.argv[2] == "true"
doctor = sys.argv[3] == "true"

required = [
    "metadata.json",
    "coverage-report.json",
    "coverage-report.md",
    "apply-plan.json",
    "package-catalog.json",
    "runtime/python.env",
    "runtime/requirements.txt",
    "collector/values-ai-agent-monitoring.yaml",
    "collector/splunk-hec-logs-overlay.yaml",
    "kubernetes/deployment-env-patch.yaml",
    "handoff.md",
    "doctor-report.md",
]

errors: list[str] = []
warnings: list[str] = []

for rel in required:
    path = output_dir / rel
    if not path.exists():
        errors.append(f"missing rendered artifact: {rel}")
    elif path.is_file() and path.stat().st_size == 0:
        errors.append(f"empty rendered artifact: {rel}")

if (output_dir / "metadata.json").exists():
    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    errors.extend(metadata.get("errors", []))
    warnings.extend(metadata.get("warnings", []))

if (output_dir / "coverage-report.json").exists():
    coverage_doc = json.loads((output_dir / "coverage-report.json").read_text(encoding="utf-8"))
    coverage = coverage_doc.get("coverage", [])
    if not coverage:
        errors.append("coverage-report.json has no coverage entries")
    for entry in coverage:
        status = entry.get("status")
        if status == "unknown":
            errors.append(f"coverage entry {entry.get('key')} has forbidden unknown status")
        if status == "api_apply" and entry.get("owner") == "Observability UI":
            errors.append(f"UI-only coverage entry {entry.get('key')} must not be api_apply")
        if not entry.get("source_url"):
            errors.append(f"coverage entry {entry.get('key')} lacks source_url")

if (output_dir / "collector/values-ai-agent-monitoring.yaml").exists():
    values = (output_dir / "collector/values-ai-agent-monitoring.yaml").read_text(encoding="utf-8")
    if "send_otlp_histograms: true" not in values:
        errors.append("collector overlay does not enforce send_otlp_histograms: true")

if (output_dir / "apply-plan.json").exists():
    plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
    commands = [" ".join(step.get("command", [])) for step in plan.get("steps", [])]
    joined = "\n".join(commands)
    if "--apply-k8s" not in joined and "--apply-linux" not in joined:
        errors.append("apply plan does not delegate collector through --apply-k8s or --apply-linux")
    if "--apply log_observer_connect" not in joined:
        errors.append("apply plan does not delegate LOC through --apply log_observer_connect")
    forbidden_secret_flags = [" --token ", " --access-token ", " --api-token ", " --o11y-token ", " --sf-token ", " --hec-token ", " --password "]
    for flag in forbidden_secret_flags:
        if flag in f" {joined} ":
            errors.append(f"apply plan contains forbidden direct-secret flag: {flag.strip()}")

payload = {"ok": not errors, "errors": errors, "warnings": warnings, "output_dir": str(output_dir)}
if json_output:
    print(json.dumps(payload, indent=2, sort_keys=True))
else:
    for warning in warnings:
        print(f"WARN: {warning}", file=sys.stderr)
    if errors:
        print("Validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
    else:
        print(f"validate: OK -> {output_dir}")

if doctor and not (output_dir / "doctor-report.md").exists():
    (output_dir / "doctor-report.md").write_text("# Doctor Report\n\nRun --render first.\n", encoding="utf-8")

raise SystemExit(1 if errors else 0)
PY
