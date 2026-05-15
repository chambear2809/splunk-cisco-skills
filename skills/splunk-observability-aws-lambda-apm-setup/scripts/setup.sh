#!/usr/bin/env bash
set -euo pipefail

# Splunk Observability Cloud AWS Lambda APM Setup
#
# Render-first CLI that mirrors splunk-observability-aws-integration:
#   --render (default), --apply [SECTIONS], --validate [--live],
#   --doctor, --discover-functions, --quickstart, --quickstart-from-live,
#   --explain, --rollback SECTION,
#   --list-runtimes, --list-layer-arns [--json],
#   --gitops-mode, --target FUNCTION,...
#
# File-based secrets only. The Splunk O11y access token is written to
# Secrets Manager or SSM via scripts/write-splunk-token.sh and never
# passed in argv.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
RENDERER="${SCRIPT_DIR}/render_assets.py"
SKILL_NAME="splunk-observability-aws-lambda-apm-setup"
DEFAULT_RENDER_DIR_NAME="splunk-observability-aws-lambda-apm-rendered"

PYTHON_BIN="python3"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
fi

MODE="render"
SECTIONS=""
SPEC=""
OUTPUT_DIR=""
REALM=""
TOKEN_FILE=""
AWS_REGION=""
ACCEPT_BETA=false
ALLOW_LOOSE_TOKEN_PERMS=false
ALLOW_VENDOR_COEXISTENCE=false
GITOPS_MODE=false
TARGET=""
JSON_OUTPUT=false
DRY_RUN=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Observability Cloud — AWS Lambda APM Setup

Usage: $(basename "$0") [MODE] [OPTIONS]

Modes (pick one; --render is the default):
  --render                       Produce the numbered plan tree under --output-dir.
  --apply [SECTIONS]             Apply rendered plan; CSV picks specific sections, or omit for all.
                                 Section names: layer,env,iam,validation.
  --validate [--live]            Static checks of a rendered tree; --live adds probe checks.
  --doctor                       Detect vendor/ADOT/X-Ray conflicts and layer drift.
  --discover-functions           List candidate Lambda functions by tag/runtime (requires AWS CLI).
  --quickstart                   Guided: discover + render + print exact --apply to run next.
  --quickstart-from-live         Snapshot a live function config into template.observed.yaml.
  --explain                      Print the apply plan in plain English; no AWS calls.
  --rollback SECTION             Render reverse commands. Sections: layer, env, iam, all.
  --list-runtimes                Print the supported runtimes catalog.
  --list-layer-arns [--json]     Print published layer ARNs.

Spec / output:
  --spec PATH                    Spec file (YAML or JSON); defaults to template.example.
  --output-dir PATH              Output directory; defaults to ${DEFAULT_RENDER_DIR_NAME}.
  --realm REALM                  Override spec.realm (us0/us1/us2/us3/au0/eu0/eu1/eu2/jp0/sg0).
  --target FUNCTION[,...]        Apply/rollback only the listed function names.

File-based secrets (chmod 600 enforced):
  --token-file PATH              Splunk O11y access token file (for live ops).
  --allow-loose-token-perms      Override chmod-600 check (WARN-only; for scratch tokens).

Behaviour flags:
  --accept-beta                  Acknowledge the layer is BETA; required for render/apply.
  --allow-vendor-coexistence     Downgrade vendor-conflict refusal to WARN (use carefully).
  --gitops-mode                  Emit Terraform + CloudFormation only; no aws-cli/ directory.
  --refresh-layer-manifest       Opt-in live fetch of layer ARN versions from signalfx repo.
  --aws-region REGION            Default AWS region for --discover-functions.
  --dry-run                      Skip live API calls; scaffolding stays render-only.
  --json                         Machine-readable result.
  -h | --help                    Show this help.

Direct-secret flags below are REJECTED with a friendly hint:
  --token --access-token --api-token --o11y-token --sf-token --password

Examples:
  # Render plan from template.example:
  bash $0 --accept-beta --realm us1

  # Quickstart (renders only; prints --apply command):
  bash $0 --quickstart --accept-beta --realm us1

  # Apply after reviewing the rendered plan:
  bash $0 --apply --spec my-spec.yaml --realm us1 --token-file /tmp/splunk_token

  # Rollback (detach layer from one function):
  bash $0 --rollback layer --target my-function --realm us1
EOF
    exit "${exit_code}"
}

reject_direct_secret() {
    local name="$1"
    cat >&2 <<EOF
Refusing direct-secret flag --${name}. Use a file-based equivalent instead:
  --token-file PATH   Splunk O11y access token for live API calls
  Then write the token to Secrets Manager or SSM via:
  bash skills/${SKILL_NAME}/scripts/splunk-observability-aws-lambda-apm-rendered/scripts/write-splunk-token.sh
EOF
    exit 2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) MODE="render" ;;
        --apply)
            MODE="apply"
            if [[ $# -ge 2 && "$2" != --* ]]; then
                SECTIONS="$2"; shift
            fi
            ;;
        --validate) MODE="validate" ;;
        --live) export SLAA_VALIDATE_LIVE=true ;;
        --doctor) MODE="doctor" ;;
        --discover-functions) MODE="discover_functions" ;;
        --quickstart) MODE="quickstart" ;;
        --quickstart-from-live) MODE="quickstart_from_live" ;;
        --explain) MODE="explain" ;;
        --rollback) MODE="rollback"; SECTIONS="${2:-}"; [[ -n "${SECTIONS:-}" ]] && shift ;;
        --list-runtimes) MODE="list_runtimes" ;;
        --list-layer-arns) MODE="list_layer_arns" ;;
        --spec) SPEC="$2"; shift ;;
        --output-dir) OUTPUT_DIR="$2"; shift ;;
        --realm) REALM="$2"; shift ;;
        --target) TARGET="$2"; shift ;;
        --token-file) TOKEN_FILE="$2"; shift ;;
        --allow-loose-token-perms) ALLOW_LOOSE_TOKEN_PERMS=true ;;
        --accept-beta) ACCEPT_BETA=true ;;
        --allow-vendor-coexistence) ALLOW_VENDOR_COEXISTENCE=true ;;
        --refresh-layer-manifest) echo "WARN: live layer-manifest refresh is not implemented; using bundled snapshot." >&2 ;;
        --gitops-mode) GITOPS_MODE=true ;;
        --aws-region) AWS_REGION="$2"; shift ;;
        --dry-run) DRY_RUN=true ;;
        --json) JSON_OUTPUT=true ;;
        --token|--access-token|--api-token|--o11y-token|--sf-token|--password) reject_direct_secret "${1#--}" ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
    shift
done

if [[ -z "${SPEC}" ]]; then
    SPEC="${SCRIPT_DIR}/../template.example"
fi
if [[ -z "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="${PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}"
fi

# Pull SPLUNK_O11Y_REALM / SPLUNK_O11Y_TOKEN_FILE from credentials when present.
load_observability_cloud_settings 2>/dev/null || true

if [[ -z "${REALM}" && -n "${SPLUNK_O11Y_REALM:-}" ]]; then
    REALM="${SPLUNK_O11Y_REALM}"
fi
if [[ -z "${TOKEN_FILE}" && -n "${SPLUNK_O11Y_TOKEN_FILE:-}" ]]; then
    TOKEN_FILE="${SPLUNK_O11Y_TOKEN_FILE}"
fi

file_mode_octal() {
    local path="$1"
    "${PYTHON_BIN}" - "${path}" <<'PY'
import os, stat, sys
print(format(stat.S_IMODE(os.stat(sys.argv[1]).st_mode), "03o"))
PY
}

assert_secret_file_perms() {
    local path="$1"
    local label="$2"
    [[ -z "${path}" ]] && return 0
    if [[ ! -f "${path}" ]]; then
        echo "FAIL: ${label} (${path}) does not exist." >&2
        exit 2
    fi
    if [[ ! -s "${path}" ]]; then
        echo "FAIL: ${label} (${path}) is empty." >&2
        exit 2
    fi
    local mode
    mode="$(file_mode_octal "${path}")"
    if [[ "${mode}" != "600" ]]; then
        if [[ "${ALLOW_LOOSE_TOKEN_PERMS}" == "true" ]]; then
            echo "WARN: ${label} (${path}) has loose permissions (${mode}); proceeding under --allow-loose-token-perms." >&2
        else
            echo "FAIL: ${label} (${path}) has loose permissions (${mode}); chmod 600 ${path} (or pass --allow-loose-token-perms)." >&2
            exit 2
        fi
    fi
}

run_renderer() {
    local args=("--spec" "${SPEC}" "--output-dir" "${OUTPUT_DIR}")
    [[ -n "${REALM}" ]] && args+=("--realm" "${REALM}")
    [[ "${ACCEPT_BETA}" == "true" ]] && args+=("--accept-beta")
    [[ "${JSON_OUTPUT}" == "true" ]] && args+=("--json")
    "${PYTHON_BIN}" "${RENDERER}" "${args[@]}"
}

run_validate() {
    local args=(--output-dir "${OUTPUT_DIR}")
    [[ "${SLAA_VALIDATE_LIVE:-}" == "true" ]] && args+=(--live)
    [[ "${JSON_OUTPUT}" == "true" ]] && args+=(--json)
    bash "${SCRIPT_DIR}/validate.sh" "${args[@]}"
}

run_doctor() {
    bash "${SCRIPT_DIR}/doctor.sh" \
        --output-dir "${OUTPUT_DIR}" \
        --realm "${REALM:-us1}" \
        ${TARGET:+--target "${TARGET}"} \
        ${ALLOW_VENDOR_COEXISTENCE:+--allow-vendor-coexistence} \
        ${JSON_OUTPUT:+--json}
}

case "${MODE}" in
    render)
        run_renderer
        ;;
    explain)
        run_renderer
        echo ""
        echo "==> Review the rendered plan in: ${OUTPUT_DIR}"
        echo "==> When ready, apply with:"
        echo "    bash ${0} --apply --spec ${SPEC} --realm ${REALM:-<realm>} --token-file /tmp/splunk_o11y_token"
        ;;
    apply)
        run_renderer
        local_sections="${SECTIONS}"
        if [[ -z "${local_sections}" ]]; then
            local_sections="layer,env,iam,validation"
        fi
        IFS=',' read -ra _sects <<< "${local_sections}"
        for s in "${_sects[@]}"; do
            s="${s// /}"
            [[ -z "${s}" ]] && continue
            echo "==> applying section: ${s}"
            case "${s}" in
                layer|env)
                    if [[ "${DRY_RUN}" == "true" ]]; then
                        echo "(dry-run) would run: bash ${OUTPUT_DIR}/aws-cli/apply-plan.sh (section ${s})"
                    elif [[ "${GITOPS_MODE}" == "true" ]]; then
                        echo "(gitops-mode) Lambda function updates must be applied via terraform/ or cloudformation/ artifacts."
                        echo "  terraform/: ${OUTPUT_DIR}/terraform/main.tf"
                        echo "  cloudformation/: ${OUTPUT_DIR}/cloudformation/snippets.yaml"
                    else
                        cat "${OUTPUT_DIR}/aws-cli/apply-plan.sh"
                        echo ""
                        echo "==> Review above; run: bash ${OUTPUT_DIR}/aws-cli/apply-plan.sh"
                    fi
                    ;;
                iam)
                    if [[ -f "${OUTPUT_DIR}/iam/iam-ingest-egress.json" ]]; then
                        cat "${OUTPUT_DIR}/iam/iam-ingest-egress.json"
                        echo ""
                        echo "==> Attach this IAM policy to the Lambda execution role(s) before running functions."
                    else
                        echo "==> No IAM policy required (local_collector_enabled=true)."
                    fi
                    ;;
                validation)
                    run_validate
                    ;;
                *)
                    echo "Unknown section: ${s}" >&2
                    exit 2
                    ;;
            esac
        done
        ;;
    validate)
        run_validate
        ;;
    doctor)
        run_renderer
        run_doctor
        ;;
    discover_functions)
        region_flag="${AWS_REGION:+--region ${AWS_REGION}}"
        echo "==> Listing Lambda functions..."
        # shellcheck disable=SC2086
        if command -v aws >/dev/null 2>&1; then
            aws lambda list-functions ${region_flag:-} \
                --query 'Functions[].{Name:FunctionName,Runtime:Runtime,Arch:Architectures[0]}' \
                --output table 2>/dev/null || echo "WARN: aws CLI call failed; ensure credentials are configured."
        else
            echo "WARN: aws CLI not installed; cannot discover functions."
        fi
        echo ""
        echo "==> Copy function names into spec.targets and re-run:"
        echo "    bash ${0} --render --spec ${SPEC} --accept-beta"
        ;;
    quickstart)
        echo "==> Quickstart: rendering plan from ${SPEC}..."
        run_renderer
        echo ""
        echo "==> Plan rendered to: ${OUTPUT_DIR}"
        echo ""
        echo "==> Review 01-overview.md and 03-layers.md, then:"
        echo ""
        echo "    # 1. Write the Splunk O11y token to ${SPEC//template.example/}secret backend once:"
        echo "    TOKEN_FILE=/tmp/splunk_o11y_token bash ${OUTPUT_DIR}/scripts/write-splunk-token.sh"
        echo ""
        echo "    # 2. Apply:"
        echo "    bash ${0} --apply --spec ${SPEC} --realm ${REALM:-<realm>} --token-file /tmp/splunk_o11y_token"
        ;;
    quickstart_from_live)
        region_flag="${AWS_REGION:+--region ${AWS_REGION}}"
        echo "==> Snapshotting live Lambda function configuration..."
        if [[ -z "${TARGET}" ]]; then
            echo "ERROR: --target FUNCTION_NAME is required for --quickstart-from-live." >&2
            exit 2
        fi
        mkdir -p "${OUTPUT_DIR}/state"
        if command -v aws >/dev/null 2>&1; then
            # shellcheck disable=SC2086
            aws lambda get-function-configuration \
                --function-name "${TARGET}" \
                ${region_flag:-} \
                > "${OUTPUT_DIR}/state/live-function-config.json" 2>/dev/null \
            && echo "==> Live config written to ${OUTPUT_DIR}/state/live-function-config.json" \
            || echo "WARN: aws CLI call failed; ensure credentials are configured."
        else
            echo "WARN: aws CLI not installed."
        fi
        echo "==> Convert to spec by hand:"
        echo "    cp skills/${SKILL_NAME}/template.example template.observed.yaml"
        echo "    # then fill in targets[] from the live config"
        ;;
    rollback)
        case "${SECTIONS}" in
            layer|"")
                cat <<'ROLLBACK_LAYER'
# Rollback: detach Splunk Lambda APM layer
# Replace FUNCTION_NAME and REGION. Review before running.

# 1. Get current layer ARNs:
aws lambda get-function-configuration \
  --function-name ${FUNCTION_NAME} \
  --region ${REGION} \
  --query 'Layers[].Arn'

# 2. Re-apply with non-Splunk layers only (omit the splunk-apm* ARN):
aws lambda update-function-configuration \
  --function-name ${FUNCTION_NAME} \
  --region ${REGION} \
  --layers ${OTHER_LAYER_ARNS}
ROLLBACK_LAYER
                ;;
            env)
                cat <<'ROLLBACK_ENV'
# Rollback: remove Splunk env vars from Lambda function
# Replace FUNCTION_NAME and REGION. Review before running.
# WARNING: This resets ALL env vars. Capture originals first.

# 1. Capture originals:
aws lambda get-function-configuration \
  --function-name ${FUNCTION_NAME} \
  --region ${REGION} \
  --query 'Environment.Variables' > /tmp/original-env-${FUNCTION_NAME}.json

# 2. Build a cleaned env dict (remove Splunk-added vars):
python3 - /tmp/original-env-${FUNCTION_NAME}.json <<'PY'
import json, sys
env = json.load(open(sys.argv[1]))
splunk_keys = {
    "AWS_LAMBDA_EXEC_WRAPPER", "SPLUNK_REALM", "SPLUNK_ACCESS_TOKEN",
    "OTEL_SERVICE_NAME", "SPLUNK_LAMBDA_LOCAL_COLLECTOR_ENABLED",
    "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_LAMBDA_DISABLE_AWS_CONTEXT_PROPAGATION",
    "SPLUNK_TRACE_RESPONSE_HEADER_ENABLED",
}
cleaned = {k: v for k, v in env.items() if k not in splunk_keys}
print("Variables=" + json.dumps(cleaned))
PY

# 3. Apply the cleaned env (pipe the output of step 2 as the value):
# aws lambda update-function-configuration \
#   --function-name ${FUNCTION_NAME} \
#   --region ${REGION} \
#   --environment 'Variables=<output from step 2>'
ROLLBACK_ENV
                ;;
            iam)
                cat <<'ROLLBACK_IAM'
# Rollback: detach Splunk ingest-egress IAM policy
# Only applies when local_collector_enabled=false (direct OTLP mode).
# Replace ROLE_NAME and POLICY_ARN.

# 1. Find attached policies:
aws iam list-attached-role-policies --role-name ${ROLE_NAME}

# 2. Detach the Splunk policy (if it was added by this skill):
# aws iam detach-role-policy \
#   --role-name ${ROLE_NAME} \
#   --policy-arn ${POLICY_ARN}

# 3. Optionally delete the managed policy:
# aws iam delete-policy --policy-arn ${POLICY_ARN}
ROLLBACK_IAM
                ;;
            all)
                echo "==> Rollback all sections (layer → env → iam)."
                echo "==> Run each in order and verify function health between steps."
                echo ""
                bash "${0}" --rollback layer --target "${TARGET:-\${FUNCTION_NAME}}"
                echo ""
                bash "${0}" --rollback env --target "${TARGET:-\${FUNCTION_NAME}}"
                echo ""
                bash "${0}" --rollback iam --target "${TARGET:-\${FUNCTION_NAME}}"
                ;;
            *)
                echo "Unknown rollback section: ${SECTIONS}. Supported: layer, env, iam, all" >&2
                exit 2
                ;;
        esac
        ;;
    list_runtimes)
        "${PYTHON_BIN}" "${RENDERER}" --spec "${SPEC}" --output-dir "${OUTPUT_DIR}" --list-runtimes
        ;;
    list_layer_arns)
        local_json="${JSON_OUTPUT}"
        if [[ "${local_json}" == "true" ]]; then
            "${PYTHON_BIN}" "${RENDERER}" --spec "${SPEC}" --output-dir "${OUTPUT_DIR}" --list-layer-arns --json
        else
            "${PYTHON_BIN}" "${RENDERER}" --spec "${SPEC}" --output-dir "${OUTPUT_DIR}" --list-layer-arns
        fi
        ;;
    *)
        echo "Unknown mode: ${MODE}" >&2
        usage 1
        ;;
esac
