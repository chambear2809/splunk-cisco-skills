#!/usr/bin/env bash
# Shared setup/validation entry point for WideField Security skills.

widefield_usage() {
    local exit_code="${1:-0}"
    cat <<EOF
${WIDEFIELD_DISPLAY_NAME}

Usage: $(basename "$0") [OPTIONS]

Core options:
  --render                  Render reviewable assets
  --validate                Run validation checks
  --apply                   Run documented live actions for this skill
  --accept-apply            Required with --apply
  --dry-run                 Print or simulate actions without live mutation
  --json                    Emit renderer JSON
  --spec PATH               Non-secret spec file
  --output-dir DIR          Render output root

Defaults and target options:
  --index NAME              Splunk index (default: widefield)
  --sourcetype VALUE        Splunk sourcetype (default: widefield:security)
  --hec-source VALUE        HEC source (default: widefield)
  --hec-token-name NAME     HEC token name (default: widefield_security_hec)
  --children LIST           Parent router children
  --evidence-file PATH      Evidence JSON for offline validation

Okta options:
  --okta-org-url URL
  --okta-token-file PATH
  --receiver-url URL
  --hook-name NAME
  --event-types CSV
  --event-hook-id ID
  --verify-event-hook-id ID
  --deactivate-event-hook-id ID
  --hook-auth-header-name NAME
  --hook-auth-secret-file PATH

Splunk options:
  --splunk-platform enterprise|cloud
  --hec-token-file PATH
  --write-hec-token-file PATH

Google SecOps and Saviynt options:
  --google-secops-project ID
  --google-secops-region REGION
  --feed-name NAME
  --saviynt-tenant-url URL

Doctor remediation gates:
  --accept-okta-remediation
  --accept-saviynt-remediation
  --accept-splunk-remediation

Secret values are refused in argv. Use *_file options for credentials.
EOF
    exit "${exit_code}"
}

widefield_reject_inline_secret_option() {
    case "$1" in
        --token|--password|--api-key|--apikey|--client-secret|--secret|--okta-token|--hec-token)
            echo "ERROR: $1 is not allowed. Use a file-backed option such as --okta-token-file or --hec-token-file." >&2
            exit 1
            ;;
    esac
}

widefield_require_arg() {
    local opt="$1" count="$2"
    local next="${3:-}"
    if [[ "${count}" -lt 2 || -z "${next}" || "${next}" == --* ]]; then
        echo "ERROR: ${opt} requires an argument." >&2
        return 1
    fi
}

widefield_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

widefield_file_secret() {
    local path="$1" label="$2"
    if [[ -z "${path}" ]]; then
        echo "ERROR: ${label} is required and must be file-backed." >&2
        exit 1
    fi
    if [[ ! -f "${path}" ]]; then
        echo "ERROR: ${label} not found: ${path}" >&2
        exit 1
    fi
}

widefield_renderer_args() {
    RENDER_ARGS=(
        --output-dir "${OUTPUT_DIR}"
        --index "${INDEX}"
        --sourcetype "${SOURCETYPE}"
        --hec-source "${HEC_SOURCE}"
        --hec-token-name "${HEC_TOKEN_NAME}"
        --okta-org-url "${OKTA_ORG_URL}"
        --receiver-url "${RECEIVER_URL}"
        --hook-name "${HOOK_NAME}"
        --event-types "${EVENT_TYPES}"
        --saviynt-tenant-url "${SAVIYNT_TENANT_URL}"
        --google-secops-project "${GOOGLE_SECOPS_PROJECT}"
        --google-secops-region "${GOOGLE_SECOPS_REGION}"
        --feed-name "${FEED_NAME}"
        --evidence-file "${EVIDENCE_FILE}"
        --children "${CHILDREN}"
    )
    if [[ -n "${SPEC}" ]]; then
        RENDER_ARGS+=(--spec "${SPEC}")
    fi
    if [[ "${DRY_RUN}" == "true" ]]; then
        RENDER_ARGS+=(--dry-run)
    fi
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        RENDER_ARGS+=(--json)
    fi
}

widefield_render() {
    widefield_renderer_args
    python3 "${RENDER_SCRIPT}" "${RENDER_ARGS[@]}"
}

widefield_render_dir() {
    printf '%s/%s' "${OUTPUT_DIR}" "${WIDEFIELD_SKILL_NAME}"
}

widefield_log() {
    if [[ "${JSON_OUTPUT:-false}" == "true" ]]; then
        printf '%s\n' "$*" >&2
    else
        printf '%s\n' "$*"
    fi
}

widefield_validate_evidence() {
    if [[ -z "${EVIDENCE_FILE}" ]]; then
        widefield_log "WARN: no --evidence-file supplied; offline evidence validation skipped."
        return 0
    fi
    if [[ ! -f "${EVIDENCE_FILE}" ]]; then
        widefield_log "FAIL: evidence file not found: ${EVIDENCE_FILE}"
        return 1
    fi
    if python3 -m json.tool "${EVIDENCE_FILE}" >/dev/null 2>&1; then
        widefield_log "PASS: evidence file is valid JSON"
    else
        widefield_log "FAIL: evidence file is not valid JSON"
        return 1
    fi
    if grep -q "WIDEFIELD_SECURITY" "${EVIDENCE_FILE}"; then
        widefield_log "PASS: evidence references Google SecOps WIDEFIELD_SECURITY"
    else
        widefield_log "WARN: evidence does not reference WIDEFIELD_SECURITY"
    fi
}

widefield_require_https_url() {
    local value="$1" label="$2"
    if [[ ! "${value}" =~ ^https:// ]]; then
        echo "ERROR: ${label} must be an https:// URL." >&2
        exit 1
    fi
}

widefield_okta_http_code() {
    local method="$1" endpoint="$2" payload="${3:-}"
    widefield_file_secret "${OKTA_TOKEN_FILE}" "--okta-token-file"
    python3 - "${method}" "${endpoint}" "${OKTA_TOKEN_FILE}" "${payload}" <<'PY'
import sys
import urllib.error
import urllib.request
from pathlib import Path

method, endpoint, credential_file, payload_arg = sys.argv[1:5]
credential_value = Path(credential_file).read_text(encoding="utf-8").strip()
if not credential_value:
    print("ERROR: --okta-token-file is empty.", file=sys.stderr)
    raise SystemExit(2)
data = None
headers = {
    "Accept": "application/json",
    "Authorization": f"SSWS {credential_value}",
}
if payload_arg:
    if payload_arg.startswith("@"):
        data = Path(payload_arg[1:]).read_bytes()
    else:
        data = payload_arg.encode("utf-8")
    headers["Content-Type"] = "application/json"
request = urllib.request.Request(endpoint, data=data, headers=headers, method=method)
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        print(response.getcode(), end="")
except urllib.error.HTTPError as exc:
    print(exc.code, end="")
except Exception:
    print("000", end="")
PY
}

widefield_validate_okta() {
    if [[ "${DRY_RUN}" == "true" ]]; then
        widefield_log "DRY RUN: would validate Okta event hooks and System Log events."
        return 0
    fi
    if [[ -z "${OKTA_ORG_URL}" || -z "${OKTA_TOKEN_FILE}" ]]; then
        widefield_log "WARN: Okta validation skipped; provide --okta-org-url and --okta-token-file."
        return 0
    fi
    widefield_file_secret "${OKTA_TOKEN_FILE}" "--okta-token-file"
    widefield_require_https_url "${OKTA_ORG_URL}" "--okta-org-url"
    local hooks_code logs_code
    hooks_code=$(widefield_okta_http_code "GET" "${OKTA_ORG_URL%/}/api/v1/eventHooks")
    case "${hooks_code}" in
        200) widefield_log "PASS: Okta event hooks API reachable" ;;
        *) widefield_log "WARN: Okta event hooks API returned HTTP ${hooks_code}" ;;
    esac
    logs_code=$(widefield_okta_http_code "GET" "${OKTA_ORG_URL%/}/api/v1/logs?limit=1")
    case "${logs_code}" in
        200) widefield_log "PASS: Okta System Log API reachable" ;;
        *) widefield_log "WARN: Okta System Log API returned HTTP ${logs_code}" ;;
    esac
}

widefield_splunk_session() {
    if ! load_splunk_credentials; then
        widefield_log "WARN: Splunk credentials not configured; Splunk validation skipped."
        return 1
    fi
    SK=$(get_session_key "${SPLUNK_URI}") || {
        widefield_log "WARN: could not authenticate to Splunk REST API."
        return 1
    }
    return 0
}

widefield_validate_splunk() {
    if [[ "${DRY_RUN}" == "true" ]]; then
        widefield_log "DRY RUN: would validate Splunk index, HEC token, searches, and WideField events."
        return 0
    fi
    widefield_splunk_session || return 0
    if platform_check_index "${SK}" "${SPLUNK_URI}" "${INDEX}"; then
        widefield_log "PASS: Splunk index exists: ${INDEX}"
    else
        widefield_log "WARN: Splunk index missing: ${INDEX}"
    fi
    local hec_state count
    hec_state=$(rest_get_hec_token_state "${SK}" "${SPLUNK_URI}" "${HEC_TOKEN_NAME}" 2>/dev/null || echo "unknown")
    widefield_log "INFO: HEC token ${HEC_TOKEN_NAME}: ${hec_state}"
    count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" \
        "search index=${INDEX} sourcetype=${SOURCETYPE} | stats count as count" "count")
    widefield_log "INFO: WideField event count in ${INDEX}/${SOURCETYPE}: ${count}"
}

widefield_validate_google() {
    if [[ "${DRY_RUN}" == "true" ]]; then
        widefield_log "DRY RUN: would validate Google SecOps WIDEFIELD_SECURITY evidence."
        return 0
    fi
    widefield_validate_evidence
}

widefield_validate_saviynt() {
    if [[ "${DRY_RUN}" == "true" ]]; then
        widefield_log "DRY RUN: would validate Saviynt remediation evidence."
        return 0
    fi
    widefield_validate_evidence
}

widefield_validate_doctor() {
    widefield_validate_splunk
    widefield_validate_okta
    widefield_validate_evidence || true
}

widefield_validate() {
    case "${WIDEFIELD_KIND}" in
        parent) widefield_validate_doctor ;;
        okta) widefield_validate_okta ;;
        saviynt) widefield_validate_saviynt ;;
        splunk) widefield_validate_splunk ;;
        google) widefield_validate_google ;;
        doctor) widefield_validate_doctor ;;
        *) widefield_log "WARN: unknown WideField kind ${WIDEFIELD_KIND}; no validation run." ;;
    esac
}

widefield_okta_payload_file() {
    local output_file="$1"
    python3 - "${output_file}" "${HOOK_NAME}" "${RECEIVER_URL}" "${EVENT_TYPES}" "${HOOK_AUTH_HEADER_NAME}" "${HOOK_AUTH_SECRET_FILE}" <<'PY'
import json
import sys
from pathlib import Path

out, name, uri, raw_events, header_name, secret_file = sys.argv[1:7]
events = [item.strip() for item in raw_events.split(",") if item.strip()]
payload = {
    "name": name,
    "events": {"type": "EVENT_TYPE", "items": events},
    "channel": {
        "type": "HTTP",
        "version": "1.0.0",
        "config": {"uri": uri},
    },
}
if header_name and secret_file:
    header_value = Path(secret_file).read_text(encoding="utf-8").strip()
    payload["channel"]["config"]["authScheme"] = {
        "type": "HEADER",
        "key": header_name,
        "value": header_value,
    }
Path(out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

widefield_apply_okta() {
    if [[ "${DRY_RUN}" == "true" ]]; then
        widefield_log "DRY RUN: would apply Okta event hook action."
        return 0
    fi
    widefield_file_secret "${OKTA_TOKEN_FILE}" "--okta-token-file"
    if [[ -n "${HOOK_AUTH_SECRET_FILE}" ]]; then
        widefield_file_secret "${HOOK_AUTH_SECRET_FILE}" "--hook-auth-secret-file"
    fi
    if [[ -z "${OKTA_ORG_URL}" ]]; then
        echo "ERROR: --okta-org-url is required for Okta apply." >&2
        exit 1
    fi
    widefield_require_https_url "${OKTA_ORG_URL}" "--okta-org-url"
    local endpoint method payload http_code tmp
    if [[ -n "${VERIFY_EVENT_HOOK_ID}" ]]; then
        endpoint="${OKTA_ORG_URL%/}/api/v1/eventHooks/${VERIFY_EVENT_HOOK_ID}/lifecycle/verify"
        method="POST"
        payload=""
    elif [[ -n "${DEACTIVATE_EVENT_HOOK_ID}" ]]; then
        endpoint="${OKTA_ORG_URL%/}/api/v1/eventHooks/${DEACTIVATE_EVENT_HOOK_ID}/lifecycle/deactivate"
        method="POST"
        payload=""
    else
        if [[ -z "${RECEIVER_URL}" ]]; then
            echo "ERROR: --receiver-url is required to create or update an Okta event hook." >&2
            exit 1
        fi
        widefield_require_https_url "${RECEIVER_URL}" "--receiver-url"
        tmp="$(mktemp)"
        chmod 600 "${tmp}"
        widefield_okta_payload_file "${tmp}"
        payload="@${tmp}"
        if [[ -n "${EVENT_HOOK_ID}" ]]; then
            endpoint="${OKTA_ORG_URL%/}/api/v1/eventHooks/${EVENT_HOOK_ID}"
            method="PUT"
        else
            endpoint="${OKTA_ORG_URL%/}/api/v1/eventHooks"
            method="POST"
        fi
    fi
    http_code=$(widefield_okta_http_code "${method}" "${endpoint}" "${payload}")
    rm -f "${tmp:-}"
    case "${http_code}" in
        200|201|204) widefield_log "Okta event hook action succeeded (HTTP ${http_code})." ;;
        *) echo "ERROR: Okta event hook action failed (HTTP ${http_code})." >&2; exit 1 ;;
    esac
}

widefield_apply_splunk_dashboard() {
    local view_name="widefield_security_overview"
    local encoded body http_code resp dashboard_path
    dashboard_path="$(widefield_render_dir)/splunk-dashboard.xml"
    [[ -f "${dashboard_path}" ]] || return 0
    encoded=$(_urlencode "${view_name}")
    body=$(form_urlencode_pairs "eai:data" "$(cat "${dashboard_path}")") || return 1
    resp=$(splunk_curl_post "${SK}" "${body}" \
        "${SPLUNK_URI}/servicesNS/nobody/search/data/ui/views/${encoded}" \
        -w '\n%{http_code}' 2>/dev/null)
    http_code=$(echo "${resp}" | tail -1)
    if [[ "${http_code}" != "200" ]]; then
        body=$(form_urlencode_pairs name "${view_name}" "eai:data" "$(cat "${dashboard_path}")") || return 1
        resp=$(splunk_curl_post "${SK}" "${body}" \
            "${SPLUNK_URI}/servicesNS/nobody/search/data/ui/views" \
            -w '\n%{http_code}' 2>/dev/null)
        http_code=$(echo "${resp}" | tail -1)
    fi
    case "${http_code}" in
        200|201|409) widefield_log "Installed dashboard ${view_name}." ;;
        *) echo "ERROR: Dashboard install failed (HTTP ${http_code})." >&2; return 1 ;;
    esac
}

widefield_apply_splunk_knowledge() {
    local macro_body search_body
    macro_body=$(form_urlencode_pairs definition "index=${INDEX} sourcetype=${SOURCETYPE}") || return 1
    rest_set_conf "${SK}" "${SPLUNK_URI}" "search" "macros" "widefield_security_events" "${macro_body}"
    search_body=$(form_urlencode_pairs \
        search "index=${INDEX} sourcetype=${SOURCETYPE} | spath | stats count by event_type severity" \
        description "WideField Security event type summary" \
        disabled "1" \
        is_scheduled "0") || return 1
    rest_set_conf "${SK}" "${SPLUNK_URI}" "search" "savedsearches" "WideField Security - Event Type Summary" "${search_body}"
    widefield_apply_splunk_dashboard
}

widefield_apply_splunk() {
    if [[ "${DRY_RUN}" == "true" ]]; then
        widefield_log "DRY RUN: would create Splunk index, HEC token, macro, saved search, and dashboard."
        return 0
    fi
    if [[ "${SPLUNK_PLATFORM}" == "enterprise" ]]; then
        widefield_file_secret "${HEC_TOKEN_FILE}" "--hec-token-file"
    else
        widefield_file_secret "${WRITE_HEC_TOKEN_FILE}" "--write-hec-token-file"
    fi
    widefield_render
    widefield_splunk_session || exit 1
    platform_create_index "${SK}" "${SPLUNK_URI}" "${INDEX}" "512000" "event"
    local hec_cmd=(
        bash "${_PROJECT_ROOT}/skills/splunk-hec-service-setup/scripts/setup.sh"
        --platform "${SPLUNK_PLATFORM}"
        --phase apply
        --token-name "${HEC_TOKEN_NAME}"
        --description "WideField Security HEC"
        --default-index "${INDEX}"
        --allowed-indexes "${INDEX}"
        --source "${HEC_SOURCE}"
        --sourcetype "${SOURCETYPE}"
    )
    if [[ "${SPLUNK_PLATFORM}" == "enterprise" ]]; then
        hec_cmd+=(--token-file "${HEC_TOKEN_FILE}")
    else
        hec_cmd+=(--write-token-file "${WRITE_HEC_TOKEN_FILE}")
    fi
    "${hec_cmd[@]}"
    widefield_apply_splunk_knowledge
}

widefield_apply_parent() {
    local child skill
    IFS=',' read -r -a child_array <<< "${CHILDREN}"
    for child in "${child_array[@]}"; do
        case "${child}" in
            okta) skill="widefield-okta-integration-setup" ;;
            saviynt) skill="widefield-saviynt-integration-setup" ;;
            splunk) skill="widefield-splunk-siem-setup" ;;
            google) skill="widefield-google-secops-setup" ;;
            doctor) skill="widefield-identity-threat-doctor" ;;
            "") continue ;;
            *) echo "ERROR: unknown child '${child}'." >&2; exit 1 ;;
        esac
        if [[ "${DRY_RUN}" == "true" ]]; then
            widefield_log "DRY RUN: would delegate to skills/${skill}/scripts/setup.sh --render --validate with non-secret target context."
        else
            bash "${_PROJECT_ROOT}/skills/${skill}/scripts/setup.sh" --render --validate \
                --output-dir "${OUTPUT_DIR}" \
                --index "${INDEX}" \
                --sourcetype "${SOURCETYPE}" \
                --hec-source "${HEC_SOURCE}" \
                --hec-token-name "${HEC_TOKEN_NAME}" \
                --okta-org-url "${OKTA_ORG_URL}" \
                --receiver-url "${RECEIVER_URL}" \
                --hook-name "${HOOK_NAME}" \
                --event-types "${EVENT_TYPES}" \
                --saviynt-tenant-url "${SAVIYNT_TENANT_URL}" \
                --google-secops-project "${GOOGLE_SECOPS_PROJECT}" \
                --google-secops-region "${GOOGLE_SECOPS_REGION}" \
                --feed-name "${FEED_NAME}" \
                --evidence-file "${EVIDENCE_FILE}"
        fi
    done
}

widefield_apply_unsupported() {
    echo "ERROR: ${WIDEFIELD_DISPLAY_NAME} has no documented live mutation path in this repository. Render handoffs and attach official/customer API references before apply." >&2
    exit 1
}

widefield_apply_doctor() {
    if [[ "${ACCEPT_OKTA_REMEDIATION}" != "true" && "${ACCEPT_SAVIYNT_REMEDIATION}" != "true" && "${ACCEPT_SPLUNK_REMEDIATION}" != "true" ]]; then
        echo "ERROR: doctor remediation is gated. Provide a target-specific --accept-*-remediation flag after reviewing rendered command packets." >&2
        exit 1
    fi
    echo "ERROR: destructive doctor remediation is not implemented without target-specific documented runbooks. Use rendered handoffs." >&2
    exit 1
}

widefield_apply() {
    if [[ "${ACCEPT_APPLY}" != "true" ]]; then
        echo "ERROR: --apply requires --accept-apply." >&2
        exit 1
    fi
    case "${WIDEFIELD_KIND}" in
        parent) widefield_apply_parent ;;
        okta) widefield_apply_okta ;;
        splunk) widefield_apply_splunk ;;
        saviynt|google) widefield_apply_unsupported ;;
        doctor) widefield_apply_doctor ;;
        *) widefield_apply_unsupported ;;
    esac
}

widefield_parse_common() {
    RENDER=false
    VALIDATE=false
    APPLY=false
    ACCEPT_APPLY=false
    DRY_RUN=false
    JSON_OUTPUT=false
    SPEC=""
    OUTPUT_DIR="${_PROJECT_ROOT}/${WIDEFIELD_RENDER_ROOT}"
    INDEX="widefield"
    SOURCETYPE="widefield:security"
    HEC_SOURCE="widefield"
    HEC_TOKEN_NAME="widefield_security_hec"
    CHILDREN="okta,saviynt,splunk,google,doctor"
    EVIDENCE_FILE=""
    OKTA_ORG_URL=""
    OKTA_TOKEN_FILE=""
    RECEIVER_URL=""
    HOOK_NAME="widefield_security_detect_and_remediate"
    EVENT_TYPES="user.session.start,user.authentication.sso,user.account.privilege.grant,application.user_membership.add"
    EVENT_HOOK_ID=""
    VERIFY_EVENT_HOOK_ID=""
    DEACTIVATE_EVENT_HOOK_ID=""
    HOOK_AUTH_HEADER_NAME=""
    HOOK_AUTH_SECRET_FILE=""
    SPLUNK_PLATFORM="enterprise"
    HEC_TOKEN_FILE=""
    WRITE_HEC_TOKEN_FILE=""
    GOOGLE_SECOPS_PROJECT=""
    GOOGLE_SECOPS_REGION="us"
    FEED_NAME="widefield-security"
    SAVIYNT_TENANT_URL=""
    ACCEPT_OKTA_REMEDIATION=false
    ACCEPT_SAVIYNT_REMEDIATION=false
    ACCEPT_SPLUNK_REMEDIATION=false

    while [[ $# -gt 0 ]]; do
        widefield_reject_inline_secret_option "$1"
        case "$1" in
            --render) RENDER=true; shift ;;
            --validate) VALIDATE=true; shift ;;
            --apply) APPLY=true; shift ;;
            --accept-apply) ACCEPT_APPLY=true; shift ;;
            --dry-run) DRY_RUN=true; shift ;;
            --json) JSON_OUTPUT=true; shift ;;
            --spec) widefield_require_arg "$1" $# "$2" || exit 1; SPEC="$2"; shift 2 ;;
            --output-dir) widefield_require_arg "$1" $# "$2" || exit 1; OUTPUT_DIR="$(widefield_abs_path "$2")"; shift 2 ;;
            --index) widefield_require_arg "$1" $# "$2" || exit 1; INDEX="$2"; shift 2 ;;
            --sourcetype) widefield_require_arg "$1" $# "$2" || exit 1; SOURCETYPE="$2"; shift 2 ;;
            --hec-source) widefield_require_arg "$1" $# "$2" || exit 1; HEC_SOURCE="$2"; shift 2 ;;
            --hec-token-name) widefield_require_arg "$1" $# "$2" || exit 1; HEC_TOKEN_NAME="$2"; shift 2 ;;
            --children) widefield_require_arg "$1" $# "$2" || exit 1; CHILDREN="$2"; shift 2 ;;
            --evidence-file) widefield_require_arg "$1" $# "$2" || exit 1; EVIDENCE_FILE="$(widefield_abs_path "$2")"; shift 2 ;;
            --okta-org-url) widefield_require_arg "$1" $# "$2" || exit 1; OKTA_ORG_URL="$2"; shift 2 ;;
            --okta-token-file) widefield_require_arg "$1" $# "$2" || exit 1; OKTA_TOKEN_FILE="$(widefield_abs_path "$2")"; shift 2 ;;
            --receiver-url) widefield_require_arg "$1" $# "$2" || exit 1; RECEIVER_URL="$2"; shift 2 ;;
            --hook-name) widefield_require_arg "$1" $# "$2" || exit 1; HOOK_NAME="$2"; shift 2 ;;
            --event-types) widefield_require_arg "$1" $# "$2" || exit 1; EVENT_TYPES="$2"; shift 2 ;;
            --event-hook-id) widefield_require_arg "$1" $# "$2" || exit 1; EVENT_HOOK_ID="$2"; shift 2 ;;
            --verify-event-hook-id) widefield_require_arg "$1" $# "$2" || exit 1; VERIFY_EVENT_HOOK_ID="$2"; shift 2 ;;
            --deactivate-event-hook-id) widefield_require_arg "$1" $# "$2" || exit 1; DEACTIVATE_EVENT_HOOK_ID="$2"; shift 2 ;;
            --hook-auth-header-name) widefield_require_arg "$1" $# "$2" || exit 1; HOOK_AUTH_HEADER_NAME="$2"; shift 2 ;;
            --hook-auth-secret-file) widefield_require_arg "$1" $# "$2" || exit 1; HOOK_AUTH_SECRET_FILE="$(widefield_abs_path "$2")"; shift 2 ;;
            --splunk-platform) widefield_require_arg "$1" $# "$2" || exit 1; SPLUNK_PLATFORM="$2"; shift 2 ;;
            --hec-token-file) widefield_require_arg "$1" $# "$2" || exit 1; HEC_TOKEN_FILE="$(widefield_abs_path "$2")"; shift 2 ;;
            --write-hec-token-file) widefield_require_arg "$1" $# "$2" || exit 1; WRITE_HEC_TOKEN_FILE="$(widefield_abs_path "$2")"; shift 2 ;;
            --google-secops-project) widefield_require_arg "$1" $# "$2" || exit 1; GOOGLE_SECOPS_PROJECT="$2"; shift 2 ;;
            --google-secops-region) widefield_require_arg "$1" $# "$2" || exit 1; GOOGLE_SECOPS_REGION="$2"; shift 2 ;;
            --feed-name) widefield_require_arg "$1" $# "$2" || exit 1; FEED_NAME="$2"; shift 2 ;;
            --saviynt-tenant-url) widefield_require_arg "$1" $# "$2" || exit 1; SAVIYNT_TENANT_URL="$2"; shift 2 ;;
            --accept-okta-remediation) ACCEPT_OKTA_REMEDIATION=true; shift ;;
            --accept-saviynt-remediation) ACCEPT_SAVIYNT_REMEDIATION=true; shift ;;
            --accept-splunk-remediation) ACCEPT_SPLUNK_REMEDIATION=true; shift ;;
            --help|-h) widefield_usage 0 ;;
            *) echo "ERROR: Unknown option: $1" >&2; widefield_usage 1 ;;
        esac
    done

    case "${SPLUNK_PLATFORM}" in
        enterprise|cloud) ;;
        *) echo "ERROR: --splunk-platform must be enterprise or cloud." >&2; exit 1 ;;
    esac

    if [[ "${RENDER}" == "false" && "${VALIDATE}" == "false" && "${APPLY}" == "false" ]]; then
        case "${WIDEFIELD_DEFAULT_ACTION:-render}" in
            validate) VALIDATE=true ;;
            *) RENDER=true ;;
        esac
    fi
}

widefield_main() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}")" && pwd)"
    _PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
    RENDER_SCRIPT="${SCRIPT_DIR}/render_assets.py"
    widefield_parse_common "$@"
    if [[ "${RENDER}" == "true" ]]; then
        widefield_render
    fi
    if [[ "${VALIDATE}" == "true" ]]; then
        widefield_validate
    fi
    if [[ "${APPLY}" == "true" ]]; then
        widefield_apply
    fi
}
