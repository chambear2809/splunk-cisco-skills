#!/usr/bin/env bash
set -euo pipefail

if [[ "$-" == *x* ]]; then
    echo "ERROR: shell xtrace is enabled; refusing to load or process credential files." >&2
    exit 2
fi

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
load_observability_cloud_settings

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
    if [[ -L "${path}" || ! -f "${path}" ]]; then
        echo "FAIL: ${label} (${path}) must be a regular, non-symlink file." >&2
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
    # Content, backend size, link-count, and stable-fingerprint validation is
    # performed by the generated descriptor-bound writer immediately before use.
}

validate_aws_region() {
    local region="$1"
    [[ -z "${region}" ]] && return 0
    if ! "${PYTHON_BIN}" - "${SCRIPT_DIR}/../references/layer-versions.snapshot.json" "${region}" <<'PY'
import json
import sys

manifest = json.loads(open(sys.argv[1], encoding="utf-8").read())
raise SystemExit(0 if sys.argv[2] in manifest.get("x86_64", {}) else 1)
PY
    then
        echo "ERROR: unsupported commercial AWS Lambda region: ${region}" >&2
        exit 2
    fi
}

run_renderer() {
    local args=("--spec" "${SPEC}" "--output-dir" "${OUTPUT_DIR}")
    [[ -n "${REALM}" ]] && args+=("--realm" "${REALM}")
    [[ "${ACCEPT_BETA}" == "true" ]] && args+=("--accept-beta")
    [[ "${GITOPS_MODE}" == "true" ]] && args+=("--gitops-mode")
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
    local args=(--output-dir "${OUTPUT_DIR}" --realm "${REALM:-us1}")
    [[ -n "${TARGET}" ]] && args+=(--target "${TARGET}")
    [[ "${ALLOW_VENDOR_COEXISTENCE}" == "true" ]] && args+=(--allow-vendor-coexistence)
    [[ "${JSON_OUTPUT}" == "true" ]] && args+=(--json)
    bash "${SCRIPT_DIR}/doctor.sh" "${args[@]}"
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
        mutation_sections=()
        run_iam=false
        run_validation=false
        IFS=',' read -ra _sects <<< "${local_sections}"
        for s in "${_sects[@]}"; do
            s="${s// /}"
            [[ -z "${s}" ]] && continue
            case "${s}" in
                layer|env) mutation_sections+=("${s}") ;;
                iam) run_iam=true ;;
                validation) run_validation=true ;;
                *)
                    echo "Unknown section: ${s}" >&2
                    exit 2
                    ;;
            esac
        done

        if [[ "${#mutation_sections[@]}" -gt 0 ]]; then
            mutation_csv="$(IFS=,; echo "${mutation_sections[*]}")"
            echo "==> applying Lambda mutation sections: ${mutation_csv}"
            if [[ "${DRY_RUN}" == "true" ]]; then
                echo "(dry-run) would run APPLY_SECTIONS=${mutation_csv} TARGET_FILTER=${TARGET:-<all>} ${OUTPUT_DIR}/aws-cli/apply-plan.sh"
            elif [[ "${GITOPS_MODE}" == "true" ]]; then
                echo "HANDOFF: gitops mode does not mutate Lambda functions directly."
                echo "  Merge and apply: ${OUTPUT_DIR}/terraform/main.tf"
                echo "  Or merge and deploy: ${OUTPUT_DIR}/cloudformation/snippets.yaml"
            else
                if [[ "${mutation_csv}" == *env* && -n "${TOKEN_FILE}" ]]; then
                    assert_secret_file_perms "${TOKEN_FILE}" "Splunk O11y token"
                    TOKEN_FILE="${TOKEN_FILE}" \
                    ALLOW_LOOSE_TOKEN_PERMS="${ALLOW_LOOSE_TOKEN_PERMS}" \
                        bash "${OUTPUT_DIR}/scripts/write-splunk-token.sh"
                fi
                APPLY_SECTIONS="${mutation_csv}" TARGET_FILTER="${TARGET}" \
                    bash "${OUTPUT_DIR}/aws-cli/apply-plan.sh"
            fi
        fi

        if [[ "${run_iam}" == "true" ]]; then
            echo "==> applying section: iam"
            if [[ -f "${OUTPUT_DIR}/iam/iam-ingest-egress.json" ]]; then
                cat "${OUTPUT_DIR}/iam/iam-ingest-egress.json"
                echo ""
                echo "HANDOFF: attach this policy to each Lambda execution role; no role ARN is available for safe automatic attachment."
            else
                echo "==> No IAM policy required (local_collector_enabled=true)."
            fi
        fi

        if [[ "${run_validation}" == "true" ]]; then
            echo "==> applying section: validation"
            run_validate
        fi
        ;;
    validate)
        run_validate
        ;;
    doctor)
        run_renderer
        run_doctor
        ;;
    discover_functions)
        validate_aws_region "${AWS_REGION}"
        region_args=()
        [[ -n "${AWS_REGION}" ]] && region_args+=(--region "${AWS_REGION}")
        echo "==> Listing Lambda functions..."
        if command -v aws >/dev/null 2>&1; then
            aws lambda list-functions "${region_args[@]}" \
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
        echo "==> Snapshotting live Lambda function configuration..."
        if [[ -z "${TARGET}" ]]; then
            echo "ERROR: --target FUNCTION_NAME is required for --quickstart-from-live." >&2
            exit 2
        fi
        snapshot_dir="${OUTPUT_DIR}/state"
        if [[ -L "${snapshot_dir}" ]]; then
            echo "ERROR: refusing symlink state directory: ${snapshot_dir}" >&2
            exit 2
        fi
        mkdir -p "${snapshot_dir}"
        chmod 700 "${snapshot_dir}"
        if command -v aws >/dev/null 2>&1; then
            umask 077
            raw_snapshot="$(mktemp "${snapshot_dir}/.live-function-raw.XXXXXX")"
            clean_snapshot="$(mktemp "${snapshot_dir}/.live-function-clean.XXXXXX")"
            cleanup_live_snapshot() {
                rm -f -- "${raw_snapshot:-}" "${clean_snapshot:-}"
            }
            trap cleanup_live_snapshot EXIT
            region_args=()
            if [[ -n "${AWS_REGION}" ]]; then
                validate_aws_region "${AWS_REGION}"
                region_args+=(--region "${AWS_REGION}")
            fi
            if ! aws lambda get-function-configuration \
                --function-name "${TARGET}" \
                "${region_args[@]}" \
                --output json > "${raw_snapshot}"; then
                echo "ERROR: aws CLI snapshot failed; no live-state artifact was retained." >&2
                exit 1
            fi
            "${PYTHON_BIN}" - "${raw_snapshot}" "${clean_snapshot}" <<'PY'
import json
import os
import sys

allowed = {
    "Architectures",
    "FunctionName",
    "Handler",
    "LastUpdateStatus",
    "Layers",
    "MemorySize",
    "PackageType",
    "Role",
    "Runtime",
    "State",
    "Timeout",
    "TracingConfig",
}
with open(sys.argv[1], encoding="utf-8") as source:
    raw = json.load(source)
if not isinstance(raw, dict):
    raise SystemExit("AWS Lambda configuration response must be an object")
sanitized = {key: raw[key] for key in sorted(allowed) if key in raw}
with open(sys.argv[2], "w", encoding="utf-8") as destination:
    json.dump(sanitized, destination, indent=2)
    destination.write("\n")
    destination.flush()
    os.fsync(destination.fileno())
PY
            snapshot_path="${snapshot_dir}/live-function-config.json"
            chmod 600 "${clean_snapshot}"
            mv -f "${clean_snapshot}" "${snapshot_path}"
            clean_snapshot=""
            rm -f -- "${raw_snapshot}"
            raw_snapshot=""
            trap - EXIT
            echo "==> Redacted live config written to ${snapshot_path} (mode 600; Environment excluded)"
        else
            echo "ERROR: aws CLI not installed; cannot create a live snapshot." >&2
            exit 2
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
  --function-name "${FUNCTION_NAME}" \
  --region "${REGION}" \
  --query 'Layers[].Arn'

# 2. Re-apply with non-Splunk layers only (omit the splunk-apm* ARN):
aws lambda update-function-configuration \
  --function-name "${FUNCTION_NAME}" \
  --region "${REGION}" \
  --layers ${OTHER_LAYER_ARNS}
ROLLBACK_LAYER
                ;;
            env)
                cat <<'ROLLBACK_ENV'
# Rollback: remove Splunk env vars from Lambda function
# Replace FUNCTION_NAME and REGION. Review before running.
# The temporary files contain the function's full environment and may contain
# secrets. They are unpredictable, mode 600, and removed automatically.

# 1. Create private temporary files and capture the current environment:
umask 077
ROLLBACK_ENV_FILE="$(mktemp "${TMPDIR:-/tmp}/splunk-lambda-env.XXXXXX")"
CLEAN_ENV_FILE="$(mktemp "${TMPDIR:-/tmp}/splunk-lambda-clean-env.XXXXXX")"
cleanup_rollback_env() {
  rm -f "${ROLLBACK_ENV_FILE:-}" "${CLEAN_ENV_FILE:-}"
}
trap cleanup_rollback_env EXIT HUP INT TERM

aws lambda get-function-configuration \
  --function-name "${FUNCTION_NAME}" \
  --region "${REGION}" \
  --query 'Environment.Variables' \
  --output json > "${ROLLBACK_ENV_FILE}"

# 2. Build a private AWS CLI environment document without Splunk-owned keys:
python3 - "${ROLLBACK_ENV_FILE}" "${CLEAN_ENV_FILE}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    env = json.load(source) or {}
splunk_keys = {
    "AWS_LAMBDA_EXEC_WRAPPER", "SPLUNK_REALM", "SPLUNK_ACCESS_TOKEN",
    "OTEL_SERVICE_NAME", "SPLUNK_LAMBDA_LOCAL_COLLECTOR_ENABLED",
    "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_LAMBDA_DISABLE_AWS_CONTEXT_PROPAGATION",
    "SPLUNK_TRACE_RESPONSE_HEADER_ENABLED",
}
cleaned = {k: v for k, v in env.items() if k not in splunk_keys}
with open(sys.argv[2], "w", encoding="utf-8") as destination:
    json.dump({"Variables": cleaned}, destination)
PY

# 3. Review the key names if needed, then apply without printing values:
# python3 -c 'import json,sys; print("\n".join(sorted(json.load(open(sys.argv[1]))["Variables"])))' "${CLEAN_ENV_FILE}"
aws lambda update-function-configuration \
  --function-name "${FUNCTION_NAME}" \
  --region "${REGION}" \
  --environment "file://${CLEAN_ENV_FILE}"
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
