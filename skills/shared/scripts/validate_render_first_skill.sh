#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
# shellcheck disable=SC1091
source "${REPO_ROOT}/skills/shared/lib/credential_helpers.sh"

SKILL_NAME=""
PROFILE_DIR=""
DEFAULT_OUTPUT=""
APP_NAME=""
INDEX=""
SOURCETYPES=""
RENDERED_DIR=""
LIVE=false

usage() {
    cat <<EOF
Render-first skill validation

Usage: $(basename "$0") --skill-name NAME --profile-dir DIR --default-output DIR [OPTIONS]

Options:
  --rendered-dir PATH     Rendered root or profile directory
  --app-name NAME         App name to check with --live
  --index INDEX           Index to check with --live
  --sourcetypes LIST      Comma-separated sourcetypes for --live search checks
  --live                  Run read-only Splunk REST/search checks using existing credentials
  --help                  Show this help
EOF
}

require_value() {
    if [[ $# -lt 2 || -z "${2:-}" ]]; then
        echo "ERROR: $1 requires a value." >&2
        exit 1
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skill-name) require_value "$1" "${2:-}"; SKILL_NAME="$2"; shift 2 ;;
        --profile-dir) require_value "$1" "${2:-}"; PROFILE_DIR="$2"; shift 2 ;;
        --default-output) require_value "$1" "${2:-}"; DEFAULT_OUTPUT="$2"; shift 2 ;;
        --rendered-dir) require_value "$1" "${2:-}"; RENDERED_DIR="$2"; shift 2 ;;
        --app-name) require_value "$1" "${2:-}"; APP_NAME="$2"; shift 2 ;;
        --index) require_value "$1" "${2:-}"; INDEX="$2"; shift 2 ;;
        --sourcetypes) require_value "$1" "${2:-}"; SOURCETYPES="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --help|-h) usage; exit 0 ;;
        --token|--password|--api-key|--session-key)
            echo "ERROR: secrets must not be passed on argv." >&2
            exit 1
            ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

[[ -n "${SKILL_NAME}" && -n "${PROFILE_DIR}" && -n "${DEFAULT_OUTPUT}" ]] || {
    echo "ERROR: --skill-name, --profile-dir, and --default-output are required." >&2
    exit 1
}

if [[ -z "${RENDERED_DIR}" ]]; then
    RENDERED_DIR="${REPO_ROOT}/${DEFAULT_OUTPUT}/${PROFILE_DIR}"
elif [[ -f "${RENDERED_DIR}/metadata.json" ]]; then
    :
else
    RENDERED_DIR="${RENDERED_DIR%/}/${PROFILE_DIR}"
fi

PASS=0
WARN=0
FAIL=0
pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }

scan_rendered_dir() {
    local pattern="$1"
    local output_file="$2"
    if command -v rg >/dev/null 2>&1; then
        rg -n "${pattern}" "${RENDERED_DIR}" >"${output_file}" 2>/dev/null
    else
        grep -RInE "${pattern}" "${RENDERED_DIR}" >"${output_file}" 2>/dev/null
    fi
}

log "=== ${SKILL_NAME} Render Validation ==="

if [[ ! -d "${RENDERED_DIR}" ]]; then
    fail "Rendered directory not found: ${RENDERED_DIR}"
else
    pass "Rendered directory exists: ${RENDERED_DIR}"
    for file in metadata.json profile-plan.md handoffs.md install-commands.sh validation-searches.spl readiness-evidence-template.json; do
        if [[ -s "${RENDERED_DIR}/${file}" ]]; then
            pass "Rendered ${file}"
        else
            fail "Missing rendered ${file}"
        fi
    done
    if python3 -m json.tool "${RENDERED_DIR}/metadata.json" >/dev/null 2>&1; then
        pass "metadata.json is valid JSON"
    else
        fail "metadata.json is invalid JSON"
    fi
    if python3 -m json.tool "${RENDERED_DIR}/readiness-evidence-template.json" >/dev/null 2>&1; then
        pass "readiness evidence template is valid JSON"
    else
        fail "readiness evidence template is invalid JSON"
    fi
    if scan_rendered_dir "SUPER_SECRET|PASSWORD_VALUE|TOKEN_VALUE|API_KEY_VALUE" "/tmp/render-first-secret-scan.$$"; then
        fail "Rendered files contain placeholder text that looks like a secret value"
        sed 's/^/    /' "/tmp/render-first-secret-scan.$$" >&2
    else
        pass "Rendered files contain no obvious secret values"
    fi
    rm -f "/tmp/render-first-secret-scan.$$"
    if scan_rendered_dir "\\{\\{[A-Za-z0-9_]+\\}\\}" "/tmp/render-first-placeholder-scan.$$"; then
        fail "Rendered files contain unresolved template placeholders"
        sed 's/^/    /' "/tmp/render-first-placeholder-scan.$$" >&2
    else
        pass "Rendered files contain no unresolved template placeholders"
    fi
    rm -f "/tmp/render-first-placeholder-scan.$$"
fi

if [[ "${LIVE}" == "true" ]]; then
    log ""
    log "--- Live read-only checks ---"
    if ! load_splunk_credentials; then
        fail "Could not load Splunk credentials"
    elif ! SK=$(get_session_key "${SPLUNK_URI}"); then
        fail "Could not authenticate to Splunk REST API"
    else
        if [[ -n "${APP_NAME}" && "${APP_NAME}" != "N/A" ]]; then
            if rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null; then
                version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null || echo "unknown")
                pass "App installed: ${APP_NAME} (${version})"
            else
                warn "App not found: ${APP_NAME}"
            fi
        fi
        if [[ -n "${INDEX}" ]]; then
            if platform_check_index "${SK}" "${SPLUNK_URI}" "${INDEX}" 2>/dev/null; then
                pass "Index exists: ${INDEX}"
            else
                warn "Index not found: ${INDEX}"
            fi
        fi
        if [[ -n "${INDEX}" && -n "${SOURCETYPES}" ]]; then
            IFS=',' read -r -a st_array <<<"${SOURCETYPES}"
            st_clause=""
            for st in "${st_array[@]}"; do
                [[ -z "${st}" ]] && continue
                if [[ -n "${st_clause}" ]]; then
                    st_clause+=","
                fi
                st_clause+="\"${st}\""
            done
            if [[ -n "${st_clause}" ]]; then
                count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" \
                    "| tstats count where index=${INDEX} sourcetype IN (${st_clause})" "count" 2>/dev/null || echo "0")
                if [[ "${count}" =~ ^[0-9]+$ && "${count}" -gt 0 ]]; then
                    pass "Recent matching events in ${INDEX}: ${count}"
                else
                    warn "No matching events found in ${INDEX}"
                fi
            fi
        fi
    fi
fi

log ""
log "=== Validation Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"
[[ "${FAIL}" -eq 0 ]]
