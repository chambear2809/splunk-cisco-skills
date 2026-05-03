#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/cisco-isovalent-platform-rendered"
DEFAULT_SPEC="${SKILL_DIR}/template.example"

usage() {
    cat <<'EOF'
Cisco Isovalent Platform Setup

Usage:
  bash skills/cisco-isovalent-platform-setup/scripts/setup.sh [mode] [options]

Modes:
  --render               Render Helm values and install scripts (default)
  --apply [STEPS]        Render then apply selected steps; STEPS is comma-
                         separated (cilium, tetragon, dnsproxy,
                         hubble-enterprise, timescape). With no list, applies
                         cilium and tetragon only.
  --validate             Run static validation against an already-rendered output
  --dry-run              Show the plan without writing
  --json                 Emit JSON dry-run output
  --explain              Print plan in plain English

Options:
  --spec PATH            YAML or JSON spec (default: template.example)
  --output-dir DIR       Rendered output directory
  --edition oss|enterprise
                         Override spec.edition. OSS = cilium/* from helm.cilium.io.
                         Enterprise = isovalent/* from helm.isovalent.com (license required).
  --eks-mirror           Use the AWS-published OCI mirror for Cilium (EKS Hybrid Nodes).
  --enable-dnsproxy      Render cilium-dnsproxy values + install (Enterprise only).
  --enable-hubble-enterprise
                         Render hubble-enterprise values + contact-link install (Enterprise only; private chart).
  --enable-timescape     Render hubble-timescape values + install (Enterprise only).
  --export-mode file|stdout|fluentd
                         Tetragon export mode (default: file). 'fluentd' is DEPRECATED.
  --isovalent-license-file PATH    Required for --edition enterprise.
  --isovalent-pull-secret-file PATH (Optional, for the Isovalent private registry.)
  --render-eksctl-example          Render an eksctl BYOCNI example script.
  --allow-loose-token-perms        Skip the chmod-600 permission preflight on license/pull-secret files.
  --help                 Show this help

Direct license/secret flags such as --license, --license-key, --pull-secret are rejected.
EOF
}

bool_text() {
    if [[ "$1" == "true" ]]; then printf 'true'; else printf 'false'; fi
}

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

MODE_RENDER=true
MODE_APPLY=false
APPLY_STEPS=""
MODE_VALIDATE=false
DRY_RUN=false
JSON_OUTPUT=false
EXPLAIN=false

OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
SPEC="${DEFAULT_SPEC}"
EDITION=""
EKS_MIRROR="false"
ENABLE_DNSPROXY="false"
ENABLE_HUBBLE_ENT="false"
ENABLE_TIMESCAPE="false"
EXPORT_MODE=""
ISOVALENT_LICENSE_FILE=""
ISOVALENT_PULL_SECRET_FILE=""
RENDER_EKSCTL_EXAMPLE="false"
ALLOW_LOOSE_TOKEN_PERMS=false

if [[ $# -eq 0 ]]; then
    usage
    exit 0
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) MODE_RENDER=true; shift ;;
        --apply)
            MODE_APPLY=true; MODE_RENDER=true
            if [[ $# -ge 2 && ! "$2" =~ ^-- ]]; then
                APPLY_STEPS="$2"
                shift 2
            else
                shift
            fi
            ;;
        --validate) MODE_VALIDATE=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --explain) EXPLAIN=true; shift ;;
        --spec) require_arg "$1" "$#" || exit 1; SPEC="$2"; shift 2 ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --edition) require_arg "$1" "$#" || exit 1; EDITION="$2"; shift 2 ;;
        --eks-mirror) EKS_MIRROR="true"; shift ;;
        --enable-dnsproxy) ENABLE_DNSPROXY="true"; shift ;;
        --enable-hubble-enterprise) ENABLE_HUBBLE_ENT="true"; shift ;;
        --enable-timescape) ENABLE_TIMESCAPE="true"; shift ;;
        --export-mode) require_arg "$1" "$#" || exit 1; EXPORT_MODE="$2"; shift 2 ;;
        --isovalent-license-file) require_arg "$1" "$#" || exit 1; ISOVALENT_LICENSE_FILE="$2"; shift 2 ;;
        --isovalent-pull-secret-file) require_arg "$1" "$#" || exit 1; ISOVALENT_PULL_SECRET_FILE="$2"; shift 2 ;;
        --render-eksctl-example) RENDER_EKSCTL_EXAMPLE="true"; shift ;;
        --allow-loose-token-perms) ALLOW_LOOSE_TOKEN_PERMS=true; shift ;;
        --license|--license-key)
            reject_secret_arg "$1" "--isovalent-license-file"
            exit 1
            ;;
        --pull-secret)
            reject_secret_arg "$1" "--isovalent-pull-secret-file"
            exit 1
            ;;
        --help|-h) usage; exit 0 ;;
        *)
            log "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"

_token_perm_octal() {
    local target="$1" mode=""
    mode="$(stat -f '%A' "${target}" 2>/dev/null)" && { printf '%s' "${mode}"; return 0; }
    mode="$(stat -c '%a' "${target}" 2>/dev/null)" && { printf '%s' "${mode}"; return 0; }
    printf ''
}

_check_token_perms() {
    local label="$1" path="$2"
    [[ -n "${path}" && -r "${path}" ]] || return 0
    local mode
    mode="$(_token_perm_octal "${path}")"
    if [[ -z "${mode}" ]]; then
        log "  WARN: Could not stat ${label} (${path}); skipping permission check."
        return 0
    fi
    if [[ "${mode}" != "600" && "${mode}" != "0600" ]]; then
        if [[ "${ALLOW_LOOSE_TOKEN_PERMS:-false}" == "true" ]]; then
            log "  WARN: ${label} permissions are ${mode}; --allow-loose-token-perms is set, proceeding."
            return 0
        fi
        log "ERROR: ${label} (${path}) is mode ${mode}; secrets must be mode 600."
        log "       Run 'chmod 600 ${path}' to fix."
        return 1
    fi
}

[[ -n "${ISOVALENT_LICENSE_FILE}" ]] && { _check_token_perms "--isovalent-license-file" "${ISOVALENT_LICENSE_FILE}" || exit 1; }
[[ -n "${ISOVALENT_PULL_SECRET_FILE}" ]] && { _check_token_perms "--isovalent-pull-secret-file" "${ISOVALENT_PULL_SECRET_FILE}" || exit 1; }

# Enterprise apply requires the license file. We check at --apply time so
# --render is friction-free.
if [[ "${MODE_APPLY}" == "true" ]]; then
    EFFECTIVE_EDITION="${EDITION:-$(python3 -c "import json,sys;
try:
    import yaml
    with open(sys.argv[1]) as f: spec = yaml.safe_load(f.read())
except (ModuleNotFoundError, ImportError):
    with open(sys.argv[1]) as f: spec = json.load(f)
print((spec or {}).get('edition', 'oss'))" "${SPEC}" 2>/dev/null || echo "oss")}"
    if [[ "${EFFECTIVE_EDITION}" == "enterprise" && -z "${ISOVALENT_LICENSE_FILE}" ]]; then
        log "ERROR: --apply with --edition enterprise requires --isovalent-license-file."
        exit 1
    fi
fi

if [[ "${EXPLAIN}" == "true" ]]; then
    cat <<EXPLAIN
Cisco Isovalent Platform Setup -- execution plan
================================================
  Spec:                     ${SPEC}
  Output directory:         ${OUTPUT_DIR}
  Edition:                  ${EDITION:-<from spec, default oss>}
  EKS-AWS mirror:           ${EKS_MIRROR}
  Enable DNS proxy:         ${ENABLE_DNSPROXY}
  Enable Hubble Enterprise: ${ENABLE_HUBBLE_ENT}
  Enable Timescape:         ${ENABLE_TIMESCAPE}
  Tetragon export mode:     ${EXPORT_MODE:-<from spec, default file>}
  License file:             ${ISOVALENT_LICENSE_FILE:-<not set>}
  Pull-secret file:         ${ISOVALENT_PULL_SECRET_FILE:-<not set>}
  Apply steps:              ${APPLY_STEPS:-<cilium,tetragon when --apply>}
  Mode: render=$(bool_text "${MODE_RENDER}") apply=$(bool_text "${MODE_APPLY}") validate=$(bool_text "${MODE_VALIDATE}")
EXPLAIN
    exit 0
fi

RENDER_ARGS=(
    --output-dir "${OUTPUT_DIR}"
    --spec "${SPEC}"
    --edition "${EDITION}"
    --eks-mirror "${EKS_MIRROR}"
    --enable-dnsproxy "${ENABLE_DNSPROXY}"
    --enable-hubble-enterprise "${ENABLE_HUBBLE_ENT}"
    --enable-timescape "${ENABLE_TIMESCAPE}"
    --export-mode "${EXPORT_MODE}"
    --isovalent-license-file "${ISOVALENT_LICENSE_FILE}"
    --isovalent-pull-secret-file "${ISOVALENT_PULL_SECRET_FILE}"
    --render-eksctl-example "${RENDER_EKSCTL_EXAMPLE}"
)
if [[ "${DRY_RUN}" == "true" ]]; then
    RENDER_ARGS+=(--dry-run)
fi
if [[ "${JSON_OUTPUT}" == "true" ]]; then
    RENDER_ARGS+=(--json)
fi

if [[ "${MODE_RENDER}" == "true" ]]; then
    python3 "${SCRIPT_DIR}/render_assets.py" "${RENDER_ARGS[@]}"
fi

if [[ "${DRY_RUN}" == "true" ]]; then
    exit 0
fi

if [[ "${MODE_VALIDATE}" == "true" ]]; then
    bash "${SCRIPT_DIR}/validate.sh" --output-dir "${OUTPUT_DIR}"
fi

run_step() {
    local step="$1" script="$2"
    local script_path="${OUTPUT_DIR}/scripts/${script}"
    if [[ ! -f "${script_path}" ]]; then
        log "  Skipping ${step}: ${script_path} not present."
        return 0
    fi
    log "Applying ${step}: ${script_path}"
    bash "${script_path}"
}

if [[ "${MODE_APPLY}" == "true" ]]; then
    STEPS="${APPLY_STEPS:-cilium,tetragon}"
    IFS=',' read -ra _STEPS_ARR <<< "${STEPS}"
    for step in "${_STEPS_ARR[@]}"; do
        step="$(echo "${step}" | tr -d '[:space:]')"
        case "${step}" in
            cilium)             run_step cilium install-cilium.sh ;;
            tetragon)           run_step tetragon install-tetragon.sh ;;
            dnsproxy)           run_step dnsproxy install-cilium-dnsproxy.sh ;;
            hubble-enterprise)  run_step hubble-enterprise install-hubble-enterprise.sh ;;
            timescape)          run_step timescape install-hubble-timescape.sh ;;
            "" )                ;;
            *)
                log "ERROR: Unknown apply step: ${step}"
                exit 1
                ;;
        esac
    done
fi
