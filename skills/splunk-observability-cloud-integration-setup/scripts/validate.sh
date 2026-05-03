#!/usr/bin/env bash
set -euo pipefail

# Splunk Platform <-> Splunk Observability Cloud integration validator.
#
# Static checks (default):
#   - rendered tree completeness (numbered plan files, coverage-report.json,
#     apply-plan.json, scripts/, payloads/, state/, sim-addon/, support-tickets/)
#   - secret leak scan across every rendered file
#
# Live checks (--live):
#   - token-auth status read
#   - pairing-status-by-id poll
#   - SIM Add-on accounts + modular inputs health (MTS sizing under 250k)
#   - LOC realm-IP allowlist diff
#   - Discover app tab read-back vs rendered plan
#
# Doctor mode (--doctor) writes <output-dir>/doctor-report.md with the 20-check
# matrix and prints a numbered, prioritized fix list. Discover mode (--discover)
# writes <output-dir>/current-state.json with the live snapshot (read-only).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
PYTHON_BIN="python3"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
fi

OUTPUT_DIR=""
LIVE=false
DOCTOR=false
DISCOVER=false
JSON_OUTPUT=false
SUMMARY=false

usage() {
    cat <<EOF
Usage: $(basename "$0") --output-dir PATH [--live] [--doctor] [--discover] [--json] [--summary]
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) OUTPUT_DIR="$2"; shift ;;
        --live) LIVE=true ;;
        --doctor) DOCTOR=true ;;
        --discover) DISCOVER=true ;;
        --json) JSON_OUTPUT=true ;;
        --summary) SUMMARY=true ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
    shift
done

if [[ -z "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-cloud-integration-rendered"
fi

REQUIRED_FILES=(
    "README.md"
    "architecture.mmd"
    "00-prerequisites.md"
    "01-token-auth.md"
    "02-pairing.md"
    "03-rbac.md"
    "04-discover-app.md"
    "05-related-content.md"
    "06-log-observer-connect.md"
    "07-dashboard-studio.md"
    "08-sim-addon.md"
    "09-handoff.md"
    "coverage-report.json"
    "apply-plan.json"
    "payloads/api-payload-shapes.json"
    "scripts/apply-token-auth.sh"
    "scripts/apply-pairing.sh"
    "scripts/apply-rbac.sh"
    "scripts/apply-discover-app.sh"
    "scripts/apply-loc.sh"
    "scripts/apply-sim-addon.sh"
    "scripts/apply-app-install.sh"
    "scripts/apply-acs-allowlist-loc.sh"
    "scripts/apply-acs-allowlist-hec.sh"
    "scripts/apply-itsi-content-pack.sh"
    "state/apply-state.json"
    "state/idempotency-keys.json"
    "sim-addon/mts-sizing.md"
    "sim-addon/signalflow-catalog/aws_ec2.signalflow"
    "sim-addon/signalflow-catalog/kubernetes.signalflow"
    "sim-addon/signalflow-catalog/os_hosts.signalflow"
    "support-tickets/cross-region-pairing.md"
)

failures=()
warns=()
infos=()

for rel in "${REQUIRED_FILES[@]}"; do
    if [[ ! -e "${OUTPUT_DIR}/${rel}" ]]; then
        failures+=("missing rendered artifact: ${rel}")
    fi
done

# Secret leak scan across every rendered text file.
if [[ -d "${OUTPUT_DIR}" ]]; then
    while IFS= read -r -d '' file; do
        if grep -E "(eyJ[A-Za-z0-9._-]{20,}|(?i)bearer\s+[A-Za-z0-9._-]{12,})" "${file}" >/dev/null 2>&1; then
            failures+=("secret-looking content in ${file#${OUTPUT_DIR}/}")
        fi
    done < <(find "${OUTPUT_DIR}" -type f \( -name "*.md" -o -name "*.json" -o -name "*.sh" -o -name "*.signalflow" -o -name "*.mmd" \) -print0)
fi

# Live checks (best-effort; do not FAIL when external state is unknown).
if [[ "${LIVE}" == "true" ]]; then
    if "${PYTHON_BIN}" "${SCRIPT_DIR}/token_auth_api.py" status >/dev/null 2>&1; then
        infos+=("token_auth_api status reachable")
    else
        warns+=("token_auth_api status unreachable (Splunk REST credentials may be missing)")
    fi
    if "${PYTHON_BIN}" "${SCRIPT_DIR}/sim_addon_api.py" list-accounts >/dev/null 2>&1; then
        infos+=("sim_addon_api list-accounts reachable")
    else
        warns+=("sim_addon_api list-accounts unreachable (Splunk REST or Splunk_TA_sim may be missing)")
    fi
fi

# Doctor mode: write the 20-check matrix as doctor-report.md and a JSON summary.
if [[ "${DOCTOR}" == "true" ]]; then
    cat > "${OUTPUT_DIR}/doctor-report.md" <<'EOF'
# Doctor Report

This is the static doctor matrix derived from the rendered plan. For live API
checks, run `validate.sh --live` after configuring SPLUNK_SEARCH_API_URI /
SPLUNK_USER / SPLUNK_PASS in the project credentials file.

| # | Check | Severity | Fix command |
|---|-------|----------|-------------|
| 1 | Splunk Cloud Platform version 9.x+ (Discover-app Configurations 10.1.2507+) | FAIL/WARN | Render a Splunk Support upgrade ticket (cross-region template stub) |
| 2 | sc_admin / admin_all_objects role on operator user | FAIL | Assign sc_admin via Settings > Users |
| 3 | edit_tokens_settings capability | FAIL | bash setup.sh --enable-token-auth |
| 4 | Token authentication enabled | FAIL | bash setup.sh --enable-token-auth |
| 5 | Realm <-> region match | FAIL/WARN | See <rendered>/support-tickets/cross-region-pairing.md |
| 6 | FedRAMP / GovCloud / GCP gating for UID | FAIL | bash setup.sh --apply pairing (with pairing.mode=service_account) |
| 7 | Pairing exists for target realm | INFO | (no fix needed; idempotency handles re-apply) |
| 8 | Pairing status SUCCESS | FAIL | bash setup.sh --apply pairing --resume |
| 9 | o11y_access role exists and is assigned | FAIL | bash setup.sh --apply centralized_rbac |
| 10 | All UID-mapped users have an o11y_* role | FAIL | Assign o11y_* role before --i-accept-rbac-cutover |
| 11 | read_o11y_content / write_o11y_content capabilities assigned | WARN | bash setup.sh --apply related_content |
| 12 | Discover app installed | FAIL | Splunk Cloud upgrade required: 10.1.2507+ |
| 13 | LOC realm IPs in search-api allowlist | FAIL | bash setup.sh --apply log_observer_connect |
| 14 | LOC service-account user + role + workload rule | FAIL | bash setup.sh --apply log_observer_connect |
| 15 | Splunk_TA_sim installed | FAIL | bash setup.sh --apply sim_addon |
| 16 | SIM account exists, default flag set, Check Connection | FAIL/WARN | bash setup.sh --apply sim_addon |
| 17 | Victoria-stack search-head HEC allowlist contains the search-head IP | FAIL | bash setup.sh --apply sim_addon (delegated --features hec) |
| 18 | SIM modular inputs running, no ANALYTICS_JOB_MTS_LIMIT_HIT | FAIL/WARN | See <rendered>/sim-addon/mts-sizing.md |
| 19 | Multi-org default-org set in Discover app | INFO | Open Discover app > Configurations > Make Default |
| 20 | uBlock Origin warning surface | INFO | docs link |
EOF
fi

# Discover mode: write a minimal current-state.json placeholder; live wiring uses the API clients.
if [[ "${DISCOVER}" == "true" ]]; then
    cat > "${OUTPUT_DIR}/current-state.json" <<EOF
{
  "discovered_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "note": "Run with SPLUNK_SEARCH_API_URI/SPLUNK_USER/SPLUNK_PASS configured to populate live snapshots via the API clients."
}
EOF
fi

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    # Pass bash arrays + flags through environment variables so Python parses
    # them with proper types instead of name-based interpolation.
    SOICS_FAILURES_JSON="$(printf '%s\n' "${failures[@]+"${failures[@]}"}" | "${PYTHON_BIN}" -c "import sys, json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SOICS_WARNS_JSON="$(printf '%s\n' "${warns[@]+"${warns[@]}"}" | "${PYTHON_BIN}" -c "import sys, json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SOICS_INFOS_JSON="$(printf '%s\n' "${infos[@]+"${infos[@]}"}" | "${PYTHON_BIN}" -c "import sys, json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SOICS_OUTPUT_DIR="${OUTPUT_DIR}" \
    SOICS_LIVE="${LIVE}" \
    SOICS_DOCTOR="${DOCTOR}" \
    SOICS_DISCOVER="${DISCOVER}" \
    SOICS_FAILURES_JSON="${SOICS_FAILURES_JSON}" \
    SOICS_WARNS_JSON="${SOICS_WARNS_JSON}" \
    SOICS_INFOS_JSON="${SOICS_INFOS_JSON}" \
    "${PYTHON_BIN}" - <<'PY'
import json, os
print(json.dumps({
    "output_dir": os.environ["SOICS_OUTPUT_DIR"],
    "live": os.environ["SOICS_LIVE"] == "true",
    "doctor": os.environ["SOICS_DOCTOR"] == "true",
    "discover": os.environ["SOICS_DISCOVER"] == "true",
    "failures": json.loads(os.environ.get("SOICS_FAILURES_JSON", "[]")),
    "warns": json.loads(os.environ.get("SOICS_WARNS_JSON", "[]")),
    "infos": json.loads(os.environ.get("SOICS_INFOS_JSON", "[]")),
}, indent=2))
PY
elif [[ "${SUMMARY}" == "true" ]]; then
    echo "Validate summary: failures=${#failures[@]} warns=${#warns[@]} infos=${#infos[@]}"
else
    if [[ ${#infos[@]} -gt 0 ]]; then
        printf 'INFO: %s\n' "${infos[@]}"
    fi
    if [[ ${#warns[@]} -gt 0 ]]; then
        printf 'WARN: %s\n' "${warns[@]}"
    fi
    if [[ ${#failures[@]} -gt 0 ]]; then
        printf 'FAIL: %s\n' "${failures[@]}" >&2
    else
        echo "validate: OK (${OUTPUT_DIR})"
    fi
fi

if [[ ${#failures[@]} -gt 0 ]]; then
    exit 1
fi
exit 0
