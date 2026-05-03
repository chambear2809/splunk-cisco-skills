#!/usr/bin/env bash
# Offline smoke test for the splunk-oncall-setup skill.
#
# Renders both example specs into temp dirs, validates the output, asserts
# every documented artifact exists, asserts canonical coverage tags, and
# exercises the REST endpoint sender + splunk_side_install render-only paths
# against the bundled templates. Never makes network calls.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

YAML_SPEC="${SKILL_DIR}/templates/oncall.example.yaml"
JSON_SPEC="${SKILL_DIR}/templates/oncall.example.json"
REST_SPEC="${SKILL_DIR}/templates/rest-alert.example.yaml"
SPLUNK_SIDE_SPEC="${SKILL_DIR}/templates/splunk-side.example.yaml"

TMP_YAML="$(mktemp -d)"
TMP_JSON="$(mktemp -d)"
TMP_KEY="$(mktemp)"
trap 'rm -rf "${TMP_YAML}" "${TMP_JSON}" "${TMP_KEY}"' EXIT

echo "fake-integration-key-for-smoke" > "${TMP_KEY}"
chmod 600 "${TMP_KEY}"

# Render + validate from YAML spec.
bash "${SCRIPT_DIR}/setup.sh" \
    --render --validate \
    --spec "${YAML_SPEC}" \
    --output-dir "${TMP_YAML}" \
    --json >/dev/null

# Render + validate from JSON spec.
bash "${SCRIPT_DIR}/setup.sh" \
    --render --validate \
    --spec "${JSON_SPEC}" \
    --output-dir "${TMP_JSON}" \
    --json >/dev/null

# Required artifacts in both rendered trees.
required=(
    coverage-report.json
    apply-plan.json
    deeplinks.json
    handoff.md
    metadata.json
)
for dir in "${TMP_YAML}" "${TMP_JSON}"; do
    for file in "${required[@]}"; do
        [[ -f "${dir}/${file}" ]] || {
            echo "FAIL: ${dir} missing ${file}" >&2
            exit 1
        }
    done
done

# YAML render must include the documented Splunkbase IDs in coverage notes.
for app_id in 3546 4886 5863; do
    grep -q "splunkbase_id\".*${app_id}" "${TMP_YAML}/coverage-report.json" \
        || grep -q "${app_id}" "${TMP_YAML}/coverage-report.json" \
        || { echo "FAIL: coverage-report.json missing Splunkbase ${app_id}" >&2; exit 1; }
done

# YAML render must include the four indexes the Add-on macros expect.
for idx in victorops_users victorops_teams victorops_oncall victorops_incidents; do
    grep -q "${idx}" "${TMP_YAML}/payloads/splunk_side/splunk-side.json" \
        || { echo "FAIL: splunk-side payload missing ${idx}" >&2; exit 1; }
done

# YAML apply-plan must include both alert_rules and reporting_v2_incidents
# rate buckets so the API client governs them at their documented limits.
grep -q '"rate_bucket": "alert_rules"' "${TMP_YAML}/apply-plan.json" \
    || { echo "FAIL: apply-plan missing alert_rules rate bucket" >&2; exit 1; }
grep -q '"rate_bucket": "reporting_v2_incidents"' "${TMP_YAML}/apply-plan.json" \
    || { echo "FAIL: apply-plan missing reporting_v2_incidents rate bucket" >&2; exit 1; }

# Direct secret flag rejection.
if bash "${SCRIPT_DIR}/setup.sh" --render --spec "${YAML_SPEC}" --api-key INLINE 2>/dev/null; then
    echo "FAIL: --api-key was not rejected" >&2
    exit 1
fi

# REST endpoint sender dry-run round-trip.
bash "${SCRIPT_DIR}/setup.sh" \
    --send-alert \
    --rest-alert-spec "${REST_SPEC}" \
    --integration-key-file "${TMP_KEY}" \
    --routing-key checkout \
    --dry-run >/dev/null

# Self-test path is also dry-runnable.
bash "${SCRIPT_DIR}/setup.sh" \
    --send-alert --self-test \
    --integration-key-file "${TMP_KEY}" \
    --routing-key checkout \
    --dry-run >/dev/null

# Splunk-side install renders without --apply.
bash "${SCRIPT_DIR}/splunk_side_install.sh" \
    --spec "${SPLUNK_SIDE_SPEC}" --json >/dev/null

# Apply-plan never references a missing payload file.
python3 - "${TMP_YAML}" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
plan = json.loads((root / "apply-plan.json").read_text(encoding="utf-8"))
missing = []
for action in plan["actions"]:
    payload_file = action.get("payload_file")
    if payload_file and not (root / payload_file).is_file():
        missing.append(payload_file)
if missing:
    sys.exit(f"FAIL: missing payload files: {missing}")
PY

echo "splunk-oncall-setup offline smoke OK"
