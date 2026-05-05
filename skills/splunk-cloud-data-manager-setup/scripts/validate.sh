#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"
OUTPUT_DIR="${REPO_ROOT}/splunk-cloud-data-manager-rendered"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      [[ $# -ge 2 ]] || { echo "--output-dir requires a value" >&2; exit 2; }
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --help|-h)
      echo "Usage: validate.sh [--output-dir DIR]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

python3 "${SKILL_DIR}/scripts/render_assets.py" \
  --mode check-rendered \
  --output-dir "${OUTPUT_DIR}"

python3 - "$OUTPUT_DIR" <<'PY'
import json
import pathlib
import sys

output_dir = pathlib.Path(sys.argv[1])
coverage = json.loads((output_dir / "coverage-report.json").read_text())
allowed = {
    "ui_handoff",
    "artifact_validate",
    "artifact_apply",
    "splunk_validate",
    "cloud_validate",
    "handoff",
    "not_applicable",
}
statuses = {row["coverage_status"] for row in coverage}
if statuses - allowed:
    raise SystemExit(f"unknown statuses: {sorted(statuses - allowed)}")
features = {row["feature"] for row in coverage}
if "Data Manager input creation" not in features:
    raise SystemExit("missing Data Manager UI handoff coverage")
source_catalog = json.loads((output_dir / "source-catalog.json").read_text())
expected_ack = [
    "CloudTrail",
    "GuardDuty",
    "SecurityHub",
    "IAM Access Analyzer",
    "CloudWatch Logs",
]
if source_catalog["hec_ack_required_sources"] != expected_ack:
    raise SystemExit("HEC ACK mapping drifted")
print("Data Manager rendered artifacts passed policy validation.")
PY
