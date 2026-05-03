#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-cloud-acs-allowlist-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""
FEATURES="search-api,s2s,hec"
CLOUD_PROVIDER="aws"
TARGET_SH=""
ALLOW_ACS_LOCKOUT="false"
STRICT_DRIFT="true"
EMIT_TERRAFORM="false"
FORCE="false"

# Per-feature subnet inputs (IPv4 and IPv6). Empty by default.
ACS_SUBNETS=""
SEARCH_API_SUBNETS=""
HEC_SUBNETS=""
S2S_SUBNETS=""
SEARCH_UI_SUBNETS=""
IDM_API_SUBNETS=""
IDM_UI_SUBNETS=""
ACS_SUBNETS_V6=""
SEARCH_API_SUBNETS_V6=""
HEC_SUBNETS_V6=""
S2S_SUBNETS_V6=""
SEARCH_UI_SUBNETS_V6=""
IDM_API_SUBNETS_V6=""
IDM_UI_SUBNETS_V6=""

# Operator IPs / CIDRs used by the ACS lock-out guard. Optional; when both
# are empty the guard performs outbound public-IP discovery and fails closed
# if discovery returns nothing while the `acs` feature is in the plan.
OPERATOR_IPS=""
OPERATOR_IPS_V6=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Cloud ACS Allowlist Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase render|preflight|apply|status|audit|validate|all
  --apply
  --dry-run
  --json
  --output-dir PATH
  --features CSV (subset of: acs,search-api,hec,s2s,search-ui,idm-api,idm-ui)
  --cloud-provider aws|gcp
  --target-search-head NAME
  --allow-acs-lockout true|false
  --strict-drift true|false
  --emit-terraform true|false
  --force
  --acs-subnets CSV
  --search-api-subnets CSV
  --hec-subnets CSV
  --s2s-subnets CSV
  --search-ui-subnets CSV
  --idm-api-subnets CSV
  --idm-ui-subnets CSV
  --acs-subnets-v6 CSV
  --search-api-subnets-v6 CSV
  --hec-subnets-v6 CSV
  --s2s-subnets-v6 CSV
  --search-ui-subnets-v6 CSV
  --idm-api-subnets-v6 CSV
  --idm-ui-subnets-v6 CSV
  --operator-ip CSV         # IPv4 IP/CIDR(s) the lock-out guard must keep allowed (covers proxy/private-egress paths)
  --operator-ip-v6 CSV      # IPv6 IP/CIDR(s) the lock-out guard must keep allowed
  --help

Examples:
  $(basename "$0") --features search-api,s2s --search-api-subnets 198.51.100.0/24 --s2s-subnets 198.51.100.0/24
  $(basename "$0") --phase audit
  $(basename "$0") --phase apply --emit-terraform true

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --apply) APPLY=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --features) require_arg "$1" $# || exit 1; FEATURES="$2"; shift 2 ;;
        --cloud-provider) require_arg "$1" $# || exit 1; CLOUD_PROVIDER="$2"; shift 2 ;;
        --target-search-head) require_arg "$1" $# || exit 1; TARGET_SH="$2"; shift 2 ;;
        --allow-acs-lockout) require_arg "$1" $# || exit 1; ALLOW_ACS_LOCKOUT="$2"; shift 2 ;;
        --strict-drift) require_arg "$1" $# || exit 1; STRICT_DRIFT="$2"; shift 2 ;;
        --emit-terraform) require_arg "$1" $# || exit 1; EMIT_TERRAFORM="$2"; shift 2 ;;
        --force) FORCE="true"; STRICT_DRIFT="false"; shift ;;
        --acs-subnets) require_arg "$1" $# || exit 1; ACS_SUBNETS="$2"; shift 2 ;;
        --search-api-subnets) require_arg "$1" $# || exit 1; SEARCH_API_SUBNETS="$2"; shift 2 ;;
        --hec-subnets) require_arg "$1" $# || exit 1; HEC_SUBNETS="$2"; shift 2 ;;
        --s2s-subnets) require_arg "$1" $# || exit 1; S2S_SUBNETS="$2"; shift 2 ;;
        --search-ui-subnets) require_arg "$1" $# || exit 1; SEARCH_UI_SUBNETS="$2"; shift 2 ;;
        --idm-api-subnets) require_arg "$1" $# || exit 1; IDM_API_SUBNETS="$2"; shift 2 ;;
        --idm-ui-subnets) require_arg "$1" $# || exit 1; IDM_UI_SUBNETS="$2"; shift 2 ;;
        --acs-subnets-v6) require_arg "$1" $# || exit 1; ACS_SUBNETS_V6="$2"; shift 2 ;;
        --search-api-subnets-v6) require_arg "$1" $# || exit 1; SEARCH_API_SUBNETS_V6="$2"; shift 2 ;;
        --hec-subnets-v6) require_arg "$1" $# || exit 1; HEC_SUBNETS_V6="$2"; shift 2 ;;
        --s2s-subnets-v6) require_arg "$1" $# || exit 1; S2S_SUBNETS_V6="$2"; shift 2 ;;
        --search-ui-subnets-v6) require_arg "$1" $# || exit 1; SEARCH_UI_SUBNETS_V6="$2"; shift 2 ;;
        --idm-api-subnets-v6) require_arg "$1" $# || exit 1; IDM_API_SUBNETS_V6="$2"; shift 2 ;;
        --idm-ui-subnets-v6) require_arg "$1" $# || exit 1; IDM_UI_SUBNETS_V6="$2"; shift 2 ;;
        --operator-ip) require_arg "$1" $# || exit 1; OPERATOR_IPS="$2"; shift 2 ;;
        --operator-ip-v6) require_arg "$1" $# || exit 1; OPERATOR_IPS_V6="$2"; shift 2 ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

validate_choice() {
    local value="$1"; shift
    local allowed
    for allowed in "$@"; do
        [[ "${value}" == "${allowed}" ]] && return 0
    done
    log "ERROR: Invalid value '${value}'. Expected one of: $*"
    exit 1
}

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

validate_args() {
    validate_choice "${PHASE}" render preflight apply status audit validate all
    validate_choice "${CLOUD_PROVIDER}" aws gcp
    validate_choice "${ALLOW_ACS_LOCKOUT}" true false
    validate_choice "${STRICT_DRIFT}" true false
    validate_choice "${EMIT_TERRAFORM}" true false
    if [[ -n "${OUTPUT_DIR}" ]]; then
        OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
    else
        OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
    fi
}

build_renderer_args() {
    RENDER_ARGS=(
        --output-dir "${OUTPUT_DIR}"
        --features "${FEATURES}"
        --cloud-provider "${CLOUD_PROVIDER}"
        --target-search-head "${TARGET_SH}"
        --allow-acs-lockout "${ALLOW_ACS_LOCKOUT}"
        --strict-drift "${STRICT_DRIFT}"
        --emit-terraform "${EMIT_TERRAFORM}"
        --force "${FORCE}"
        --acs-subnets "${ACS_SUBNETS}"
        --search-api-subnets "${SEARCH_API_SUBNETS}"
        --hec-subnets "${HEC_SUBNETS}"
        --s2s-subnets "${S2S_SUBNETS}"
        --search-ui-subnets "${SEARCH_UI_SUBNETS}"
        --idm-api-subnets "${IDM_API_SUBNETS}"
        --idm-ui-subnets "${IDM_UI_SUBNETS}"
        --acs-subnets-v6 "${ACS_SUBNETS_V6}"
        --search-api-subnets-v6 "${SEARCH_API_SUBNETS_V6}"
        --hec-subnets-v6 "${HEC_SUBNETS_V6}"
        --s2s-subnets-v6 "${S2S_SUBNETS_V6}"
        --search-ui-subnets-v6 "${SEARCH_UI_SUBNETS_V6}"
        --idm-api-subnets-v6 "${IDM_API_SUBNETS_V6}"
        --idm-ui-subnets-v6 "${IDM_UI_SUBNETS_V6}"
        --operator-ips "${OPERATOR_IPS}"
        --operator-ips-v6 "${OPERATOR_IPS_V6}"
    )
}

render_dir() {
    printf '%s/allowlist' "${OUTPUT_DIR}"
}

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" "${extra_args[@]}"
}

run_rendered_script() {
    local script_name="$1" dir
    dir="$(render_dir)"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: (cd ${dir} && ./${script_name})"
        return 0
    fi
    if [[ ! -x "${dir}/${script_name}" ]]; then
        log "ERROR: Rendered script is missing or not executable: ${dir}/${script_name}"
        exit 1
    fi
    (cd "${dir}" && "./${script_name}")
}

main() {
    validate_args
    build_renderer_args
    if [[ "${DRY_RUN}" == "true" ]]; then
        if [[ "${JSON_OUTPUT}" == "true" ]]; then
            exec python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run --json
        fi
        python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run
        exit 0
    fi
    case "${PHASE}" in
        render)
            render_assets
            if [[ "${APPLY}" == "true" ]]; then
                run_rendered_script preflight.sh
                run_rendered_script apply-ipv4.sh
                run_rendered_script apply-ipv6.sh
                run_rendered_script wait-for-ready.sh
            fi
            ;;
        preflight) render_assets; run_rendered_script preflight.sh ;;
        apply) render_assets; run_rendered_script preflight.sh; run_rendered_script apply-ipv4.sh; run_rendered_script apply-ipv6.sh; run_rendered_script wait-for-ready.sh ;;
        status) run_rendered_script wait-for-ready.sh ;;
        audit) render_assets; run_rendered_script audit.sh ;;
        validate) render_assets; run_rendered_script audit.sh ;;
        all) render_assets; run_rendered_script preflight.sh; run_rendered_script apply-ipv4.sh; run_rendered_script apply-ipv6.sh; run_rendered_script wait-for-ready.sh; run_rendered_script audit.sh ;;
    esac
}

main "$@"
