#!/usr/bin/env bash
set -euo pipefail

# Splunk Observability Cloud <-> AWS integration: primary CLI.
#
# Five-mode UX (matches splunk-observability-cloud-integration-setup):
#   --render (default), --apply [SECTIONS], --validate [--live],
#   --doctor, --discover, --quickstart, --quickstart-from-live, --explain,
#   --rollback SECTION.
#
# File-based-secrets only. The Splunk Observability admin user API access
# token lives in $SPLUNK_O11Y_TOKEN_FILE (chmod 600). For SecurityToken auth
# (GovCloud / China), AWS access keys live in --aws-access-key-id-file and
# --aws-secret-access-key-file.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
RENDERER="${SCRIPT_DIR}/render_assets.py"
API_CLIENT="${SCRIPT_DIR}/aws_integration_api.py"
DEFAULT_RENDER_DIR_NAME="splunk-observability-aws-integration-rendered"

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
AWS_ACCESS_KEY_ID_FILE=""
AWS_SECRET_ACCESS_KEY_FILE=""
ALLOW_LOOSE_TOKEN_PERMS=false
ACCEPT_DRIFT=""
JSON_OUTPUT=false
DRY_RUN=false
PRIVATELINK_DOMAIN=""
CFN_TEMPLATE_URL=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Observability Cloud <-> AWS Integration Setup

Usage: $(basename "$0") [MODE] [OPTIONS]

Modes (pick one; --render is the default):
  --render                       Produce the numbered plan tree under --output-dir (default mode).
  --apply [SECTIONS]             Apply rendered plan; CSV picks specific sections, or omit for all.
                                 Section names: iam, integration, streams, multi_account, validation.
  --validate [--live]            Static checks of a rendered tree; --live adds API checks.
  --doctor                       Run the troubleshooting catalog and emit doctor-report.md.
  --discover                     Read-only sweep that writes current-state.json + drift report.
  --quickstart                   Single-shot greenfield External-ID + Splunk-managed Streams scenario.
  --quickstart-from-live         Adopt an existing live integration into template.observed.yaml.
  --explain                      Print the apply plan in plain English; no API calls.
  --rollback SECTION             Render reverse commands for a previously applied section.
  --list-namespaces              Print the supported AWS service / namespace catalog.
  --list-recommended-stats       Print the per-namespace per-metric stat catalog.

Spec / output:
  --spec PATH                    Spec file (YAML or JSON); defaults to template.example.
  --output-dir PATH              Output directory; defaults to ${DEFAULT_RENDER_DIR_NAME}.
  --realm REALM                  Override spec.realm (us0/us1/us2/us3/au0/eu0/eu1/eu2/jp0/sg0).

PrivateLink / CloudFormation overrides:
  --privatelink-domain {legacy,new}
                                 Override spec.private_link.domain.
  --cfn-template-url URL         Override spec.metric_streams.cloudformation_template_url.

File-based secrets (chmod 600 enforced):
  --token-file PATH              Splunk Observability Cloud admin user API access token.
  --aws-access-key-id-file PATH  AWS access key ID (for authentication.mode=security_token).
  --aws-secret-access-key-file PATH
                                 AWS secret access key (for authentication.mode=security_token).
  --allow-loose-token-perms      Override chmod-600 (emits WARN; for short-lived scratch tokens).

Drift handling:
  --accept-drift FIELD[,FIELD...]
                                 Required for --apply when discover shows the live integration
                                 differs from the rendered spec on a sensitive field.

Output formatting:
  --json                                     Machine-readable result.
  --dry-run                                  Skip live API calls (apply scaffolding stays render-only).
  -h | --help                                Show this help.

Direct-secret flags below are REJECTED with a friendly hint:
  --token --access-token --api-token --o11y-token --admin-token --sf-token
  --external-id --aws-access-key-id --aws-secret-access-key --aws-secret-key
  --password
EOF
    exit "${exit_code}"
}

reject_direct_secret() {
    local name="$1"
    cat >&2 <<EOF
Refusing direct-secret flag --${name}. Use a file-based equivalent instead:
  --token-file PATH                          Splunk Observability admin user API access token
  --aws-access-key-id-file PATH              AWS access key ID (for security_token auth)
  --aws-secret-access-key-file PATH          AWS secret access key (for security_token auth)
The token / key file must be chmod 600. Use:
  bash skills/shared/scripts/write_secret_file.sh /tmp/<name>
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
        --live) export SOAI_VALIDATE_LIVE=true ;;
        --doctor) MODE="doctor" ;;
        --discover) MODE="discover" ;;
        --quickstart) MODE="quickstart" ;;
        --quickstart-from-live) MODE="quickstart_from_live" ;;
        --explain) MODE="explain" ;;
        --rollback) MODE="rollback"; SECTIONS="$2"; shift ;;
        --list-namespaces) MODE="list_namespaces" ;;
        --list-recommended-stats) MODE="list_recommended_stats" ;;
        --spec) SPEC="$2"; shift ;;
        --output-dir) OUTPUT_DIR="$2"; shift ;;
        --realm) REALM="$2"; shift ;;
        --privatelink-domain) PRIVATELINK_DOMAIN="$2"; shift ;;
        --cfn-template-url) CFN_TEMPLATE_URL="$2"; shift ;;
        --token-file) TOKEN_FILE="$2"; shift ;;
        --aws-access-key-id-file) AWS_ACCESS_KEY_ID_FILE="$2"; shift ;;
        --aws-secret-access-key-file) AWS_SECRET_ACCESS_KEY_FILE="$2"; shift ;;
        --allow-loose-token-perms) ALLOW_LOOSE_TOKEN_PERMS=true ;;
        --accept-drift) ACCEPT_DRIFT="$2"; shift ;;
        --json) JSON_OUTPUT=true ;;
        --dry-run) DRY_RUN=true ;;
        --token|--access-token|--api-token|--o11y-token|--admin-token|--sf-token|--external-id) reject_direct_secret "${1#--}" ;;
        --aws-access-key-id|--aws-secret-access-key|--aws-secret-key|--password) reject_direct_secret "${1#--}" ;;
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
import os
import stat
import sys

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
    [[ -n "${PRIVATELINK_DOMAIN}" ]] && args+=("--privatelink-domain" "${PRIVATELINK_DOMAIN}")
    [[ -n "${CFN_TEMPLATE_URL}" ]] && args+=("--cfn-template-url" "${CFN_TEMPLATE_URL}")
    [[ "${JSON_OUTPUT}" == "true" ]] && args+=("--json")
    "${PYTHON_BIN}" "${RENDERER}" "${args[@]}"
}

run_renderer_explain() {
    local args=("--spec" "${SPEC}" "--output-dir" "${OUTPUT_DIR}" "--explain")
    [[ -n "${REALM}" ]] && args+=("--realm" "${REALM}")
    [[ -n "${PRIVATELINK_DOMAIN}" ]] && args+=("--privatelink-domain" "${PRIVATELINK_DOMAIN}")
    [[ -n "${CFN_TEMPLATE_URL}" ]] && args+=("--cfn-template-url" "${CFN_TEMPLATE_URL}")
    "${PYTHON_BIN}" "${RENDERER}" "${args[@]}"
}

run_validate() {
    local args=(--output-dir "${OUTPUT_DIR}")
    [[ "${SOAI_VALIDATE_LIVE:-}" == "true" ]] && args+=(--live)
    [[ "${MODE}" == "doctor" ]] && args+=(--doctor)
    [[ "${MODE}" == "discover" ]] && args+=(--discover)
    [[ "${JSON_OUTPUT}" == "true" ]] && args+=(--json)
    bash "${SCRIPT_DIR}/validate.sh" "${args[@]}"
}

run_section_apply() {
    local section="$1"
    case "${section}" in
        iam)
            cat "${OUTPUT_DIR}/iam/iam-trust.json" 2>/dev/null || true
            cat "${OUTPUT_DIR}/iam/iam-combined.json"
            echo ""
            echo "==> Operator: deploy these IAM policies to the AWS account before continuing."
            ;;
        integration)
            assert_secret_file_perms "${TOKEN_FILE}" "--token-file"
            assert_secret_file_perms "${AWS_ACCESS_KEY_ID_FILE}" "--aws-access-key-id-file"
            assert_secret_file_perms "${AWS_SECRET_ACCESS_KEY_FILE}" "--aws-secret-access-key-file"
            export SPLUNK_O11Y_REALM="${REALM}"
            export SPLUNK_O11Y_TOKEN_FILE="${TOKEN_FILE}"
            [[ -n "${AWS_ACCESS_KEY_ID_FILE}" ]] && export SPLUNK_AWS_ACCESS_KEY_ID_FILE="${AWS_ACCESS_KEY_ID_FILE}"
            [[ -n "${AWS_SECRET_ACCESS_KEY_FILE}" ]] && export SPLUNK_AWS_SECRET_ACCESS_KEY_FILE="${AWS_SECRET_ACCESS_KEY_FILE}"
            [[ -n "${ACCEPT_DRIFT}" ]] && export SOAI_ACCEPT_DRIFT="${ACCEPT_DRIFT}"
            local extra=()
            [[ "${DRY_RUN}" == "true" ]] && extra+=("--dry-run")
            [[ "${ALLOW_LOOSE_TOKEN_PERMS}" == "true" ]] && extra+=("--allow-loose-token-perms")
            "${PYTHON_BIN}" "${API_CLIENT}" \
                --realm "${REALM}" \
                --token-file "${TOKEN_FILE}" \
                --state-dir "${OUTPUT_DIR}/state" \
                --payload-file "${OUTPUT_DIR}/payloads/integration-create.json" \
                "${extra[@]}" \
                upsert
            ;;
        streams|metric_streams)
            bash "${OUTPUT_DIR}/scripts/apply-cloudformation.sh"
            ;;
        multi_account)
            bash "${OUTPUT_DIR}/scripts/apply-multi-account.sh"
            ;;
        validation|discover)
            assert_secret_file_perms "${TOKEN_FILE}" "--token-file"
            "${PYTHON_BIN}" "${API_CLIENT}" \
                --realm "${REALM}" \
                --token-file "${TOKEN_FILE}" \
                --state-dir "${OUTPUT_DIR}/state" \
                discover --output "${OUTPUT_DIR}/current-state.json"
            ;;
        *)
            echo "Unknown section: ${section}" >&2
            exit 2
            ;;
    esac
}

case "${MODE}" in
    render)
        run_renderer
        ;;
    explain)
        run_renderer_explain
        ;;
    apply)
        run_renderer
        local_sections="${SECTIONS}"
        if [[ -z "${local_sections}" ]]; then
            local_sections="iam,integration,streams,multi_account,validation"
        fi
        IFS=',' read -ra _sects <<< "${local_sections}"
        for s in "${_sects[@]}"; do
            s="${s// /}"
            [[ -z "${s}" ]] && continue
            echo "==> applying section: ${s}"
            if [[ "${DRY_RUN}" == "true" && "${s}" != "integration" ]]; then
                echo "(dry-run) would apply ${s}"
                continue
            fi
            run_section_apply "${s}"
        done
        ;;
    validate)
        run_validate
        ;;
    doctor)
        run_renderer
        run_validate
        ;;
    discover)
        run_renderer
        run_section_apply discover || true
        run_validate
        ;;
    quickstart)
        run_renderer
        for s in iam integration streams validation; do
            echo "==> quickstart applying: ${s}"
            run_section_apply "${s}" || true
        done
        ;;
    quickstart_from_live)
        # Fetch the live integration and write it to template.observed.yaml.
        assert_secret_file_perms "${TOKEN_FILE}" "--token-file"
        : "${REALM:?--realm or SPLUNK_O11Y_REALM is required for --quickstart-from-live}"
        mkdir -p "${OUTPUT_DIR}/state"
        "${PYTHON_BIN}" "${API_CLIENT}" \
            --realm "${REALM}" \
            --token-file "${TOKEN_FILE}" \
            --state-dir "${OUTPUT_DIR}/state" \
            discover --output "${OUTPUT_DIR}/current-state.json"
        echo "==> live snapshot written to ${OUTPUT_DIR}/current-state.json"
        echo "==> review and convert by hand into template.observed.yaml; the renderer's"
        echo "    field naming mirrors the canonical Pulumi/Terraform schema."
        ;;
    rollback)
        case "${SECTIONS}" in
            integration)
                cat <<EOF
# Rollback (render-only): integration
# DELETE the AWSCloudWatch integration via the REST API. Requires the
# integration ID from a prior --discover or the apply-state.json record.
${PYTHON_BIN} ${API_CLIENT} \\
    --realm \${SPLUNK_O11Y_REALM} \\
    --token-file \${SPLUNK_O11Y_TOKEN_FILE} \\
    --state-dir ${OUTPUT_DIR}/state \\
    --integration-id \${INTEGRATION_ID} \\
    delete
EOF
                ;;
            streams|metric_streams)
                cat <<EOF
# Rollback (render-only): streams
# Tear down the per-region CloudFormation stacks deployed for Metric Streams.
for region in $(bash -c "tail -n +1 ${OUTPUT_DIR}/03-regions-services.md | grep -Eo 'us-[a-z0-9-]+|eu-[a-z0-9-]+|ap-[a-z0-9-]+|ca-[a-z0-9-]+' | sort -u"); do
  aws cloudformation delete-stack \\
    --stack-name SplunkObservability-MetricStreams-\${region} \\
    --region \${region}
done
EOF
                ;;
            *)
                echo "Unknown rollback section: ${SECTIONS}" >&2
                exit 2
                ;;
        esac
        ;;
    list_namespaces)
        "${PYTHON_BIN}" "${RENDERER}" --spec "${SPEC}" --output-dir "${OUTPUT_DIR}" --list-namespaces --json
        ;;
    list_recommended_stats)
        "${PYTHON_BIN}" "${RENDERER}" --spec "${SPEC}" --output-dir "${OUTPUT_DIR}" --list-recommended-stats --json
        ;;
    *)
        echo "Unknown mode: ${MODE}" >&2
        usage 1
        ;;
esac
