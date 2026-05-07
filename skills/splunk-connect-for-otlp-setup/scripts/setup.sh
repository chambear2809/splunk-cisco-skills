#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

APP_ID="8704"
APP_NAME="splunk-connect-for-otlp"
APP_VERSION="0.4.1"
KNOWN_SHA256="fde0d93532703e04ab5aa544815d52232ef62afae2c0a55e374dc74d2d58f9d1"
INPUT_TYPE="splunk-connect-for-otlp"

INSTALL_APP_SCRIPT="${PROJECT_ROOT}/skills/splunk-app-install/scripts/install_app.sh"
UNINSTALL_APP_SCRIPT="${PROJECT_ROOT}/skills/splunk-app-install/scripts/uninstall_app.sh"
VALIDATE_SCRIPT="${SCRIPT_DIR}/validate.sh"
DOCTOR_SCRIPT="${SCRIPT_DIR}/doctor.py"
SENDER_RENDERER="${SCRIPT_DIR}/render_sender_assets.py"

DO_INSTALL=false
DO_UPDATE=false
DO_UNINSTALL=false
CONFIGURE_INPUT=false
ENABLE_INPUT=false
DISABLE_INPUT=false
DELETE_INPUT=false
RENDER_SENDER_CONFIG=false
RENDER_HEC_HANDOFF=false
DO_VALIDATE=false
DO_DOCTOR=false
DO_REPAIR=false
DRY_RUN=false
JSON_OUTPUT=false
NO_RESTART=false

OUTPUT_DIR="${PROJECT_ROOT}/splunk-connect-for-otlp-rendered"
LOCAL_PACKAGE=""
INPUT_NAME="default"
GRPC_PORT="4317"
HTTP_PORT="4318"
LISTEN_ADDRESS="0.0.0.0"
ENABLE_SSL="false"
SERVER_CERT=""
SERVER_KEY=""
DISABLED="0"
INDEX="otlp_events"
HOST_VALUE=""
SOURCE_VALUE="otlp"
SOURCETYPE_VALUE="${APP_NAME}"
INTERVAL="0"
EXPECTED_INDEX="otlp_events"
RECEIVER_HOST="otlp-hf.example.com"
SENDER_PROTOCOL="both"
SENDER_TLS="false"
HEC_TOKEN_FILE="/tmp/splunk_otlp_hec_token"
HEC_PLATFORM="${SPLUNK_PLATFORM:-enterprise}"
HEC_TOKEN_NAME="splunk_otlp"
HEC_ALLOWED_INDEXES=""
FIXES=""
EVIDENCE_FILE=""
PACKAGE_FILE=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Connect for OTLP Setup

Usage: $(basename "$0") [OPTIONS]

Lifecycle:
  --install                         Install Splunkbase app 8704
  --update                          Update Splunkbase app 8704
  --uninstall                       Uninstall splunk-connect-for-otlp
  --local-package PATH              Use a verified local 0.4.1 package instead of Splunkbase
  --no-restart                      Pass --no-restart to shared app installer

Modular input:
  --configure-input                 Create/update data/inputs/splunk-connect-for-otlp
  --enable-input                    Enable the input stanza
  --disable-input                   Disable the input stanza
  --delete-input                    Delete the input stanza
  --input-name NAME                 Input stanza name (default: default)
  --grpc-port PORT                  OTLP gRPC port (default: 4317; port 0 rejected)
  --http-port PORT                  OTLP HTTP port (default: 4318; port 0 rejected)
  --listen-address ADDR             Listen address (default: 0.0.0.0)
  --enable-ssl true|false           Enable receiver TLS (default: false)
  --server-cert PATH                Server certificate path for enableSSL
  --server-key PATH                 Server key path for enableSSL
  --index INDEX                     Input-level default index (default: otlp_events)
  --host VALUE
  --source VALUE                    Default source (default: otlp)
  --sourcetype VALUE                Default sourcetype (default: splunk-connect-for-otlp)
  --interval SECONDS                Modular input interval (default: 0)

Sender and HEC handoff:
  --render-sender-config            Render OTel sender examples
  --render-hec-handoff              Render splunk-hec-service-setup helper
  --render                          Render both sender config and HEC handoff
  --receiver-host HOST              Receiver host for sender assets
  --sender-protocol both|grpc|http  Sender protocol examples (default: both)
  --sender-tls true|false           Render HTTPS/TLS sender endpoints
  --hec-token-file PATH             Local token file path reference; value is never read
  --hec-platform enterprise|cloud   HEC setup target (default: SPLUNK_PLATFORM or enterprise)
  --hec-token-name NAME             HEC token name for handoff
  --hec-allowed-indexes CSV         HEC allowed indexes (default: --expected-index)
  --expected-index INDEX            Expected routed index (default: otlp_events)

Validation, doctor, repair:
  --validate                        Run read-only validation
  --doctor                          Render doctor report and fix plan
  --evidence-file PATH              JSON evidence for doctor
  --package-file PATH               Package file for doctor/package inspection
  --repair --fixes CSV              Apply conservative repair IDs

Other:
  --output-dir PATH                 Rendered output directory
  --dry-run                         Show planned actions without live changes
  --json                            Emit JSON for dry-run, doctor, or renderer workflows
  --help

Direct token flags such as --token, --hec-token, and --authorization are rejected.
EOF
    exit "${exit_code}"
}

require_value() {
    require_arg "$1" "$2" || exit 1
}

reject_secret_flag() {
    log "ERROR: Direct token values are not accepted. Use --hec-token-file."
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) DO_INSTALL=true; shift ;;
        --update) DO_UPDATE=true; shift ;;
        --uninstall) DO_UNINSTALL=true; shift ;;
        --configure-input) CONFIGURE_INPUT=true; shift ;;
        --enable-input) ENABLE_INPUT=true; shift ;;
        --disable-input) DISABLE_INPUT=true; shift ;;
        --delete-input) DELETE_INPUT=true; shift ;;
        --render-sender-config) RENDER_SENDER_CONFIG=true; shift ;;
        --render-hec-handoff) RENDER_HEC_HANDOFF=true; shift ;;
        --render) RENDER_SENDER_CONFIG=true; RENDER_HEC_HANDOFF=true; shift ;;
        --validate) DO_VALIDATE=true; shift ;;
        --doctor) DO_DOCTOR=true; shift ;;
        --repair) DO_REPAIR=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --no-restart) NO_RESTART=true; shift ;;
        --output-dir) require_value "$1" $#; OUTPUT_DIR="$2"; shift 2 ;;
        --local-package) require_value "$1" $#; LOCAL_PACKAGE="$2"; PACKAGE_FILE="$2"; shift 2 ;;
        --input-name) require_value "$1" $#; INPUT_NAME="$2"; shift 2 ;;
        --grpc-port) require_value "$1" $#; GRPC_PORT="$2"; shift 2 ;;
        --http-port) require_value "$1" $#; HTTP_PORT="$2"; shift 2 ;;
        --listen-address) require_value "$1" $#; LISTEN_ADDRESS="$2"; shift 2 ;;
        --enable-ssl) require_value "$1" $#; ENABLE_SSL="$2"; shift 2 ;;
        --server-cert) require_value "$1" $#; SERVER_CERT="$2"; shift 2 ;;
        --server-key) require_value "$1" $#; SERVER_KEY="$2"; shift 2 ;;
        --index) require_value "$1" $#; INDEX="$2"; EXPECTED_INDEX="$2"; shift 2 ;;
        --host) require_value "$1" $#; HOST_VALUE="$2"; shift 2 ;;
        --source) require_value "$1" $#; SOURCE_VALUE="$2"; shift 2 ;;
        --sourcetype) require_value "$1" $#; SOURCETYPE_VALUE="$2"; shift 2 ;;
        --interval) require_value "$1" $#; INTERVAL="$2"; shift 2 ;;
        --expected-index) require_value "$1" $#; EXPECTED_INDEX="$2"; INDEX="$2"; shift 2 ;;
        --receiver-host) require_value "$1" $#; RECEIVER_HOST="$2"; shift 2 ;;
        --sender-protocol) require_value "$1" $#; SENDER_PROTOCOL="$2"; shift 2 ;;
        --sender-tls) require_value "$1" $#; SENDER_TLS="$2"; shift 2 ;;
        --hec-token-file) require_value "$1" $#; HEC_TOKEN_FILE="$2"; shift 2 ;;
        --hec-platform) require_value "$1" $#; HEC_PLATFORM="$2"; shift 2 ;;
        --hec-token-name) require_value "$1" $#; HEC_TOKEN_NAME="$2"; shift 2 ;;
        --hec-allowed-indexes) require_value "$1" $#; HEC_ALLOWED_INDEXES="$2"; shift 2 ;;
        --fixes) require_value "$1" $#; FIXES="$2"; shift 2 ;;
        --evidence-file) require_value "$1" $#; EVIDENCE_FILE="$2"; shift 2 ;;
        --package-file) require_value "$1" $#; PACKAGE_FILE="$2"; shift 2 ;;
        --token|--hec-token|--hec-token-value|--authorization|--splunk-token) reject_secret_flag ;;
        --token=*|--hec-token=*|--hec-token-value=*|--authorization=*|--splunk-token=*) reject_secret_flag ;;
        --help) usage 0 ;;
        *) log "ERROR: Unknown option: $1"; usage 1 ;;
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

positive_port() {
    local value="$1" option="$2"
    if [[ ! "${value}" =~ ^[0-9]+$ ]]; then
        log "ERROR: ${option} must be a TCP port number."
        exit 1
    fi
    if (( value < 1 || value > 65535 )); then
        log "ERROR: ${option} must be between 1 and 65535; port 0 is test-only."
        exit 1
    fi
}

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

validate_common_args() {
    validate_choice "${ENABLE_SSL}" true false
    validate_choice "${SENDER_PROTOCOL}" both grpc http
    validate_choice "${SENDER_TLS}" true false
    validate_choice "${HEC_PLATFORM}" enterprise cloud
    positive_port "${GRPC_PORT}" "--grpc-port"
    positive_port "${HTTP_PORT}" "--http-port"
    if [[ "${ENABLE_SSL}" == "true" && ( -z "${SERVER_CERT}" || -z "${SERVER_KEY}" ) ]]; then
        log "ERROR: --enable-ssl true requires --server-cert and --server-key."
        exit 1
    fi
    OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
    if [[ -z "${HEC_ALLOWED_INDEXES}" ]]; then
        HEC_ALLOWED_INDEXES="${EXPECTED_INDEX}"
    fi
}

json_plan() {
    DO_INSTALL="${DO_INSTALL}" DO_UPDATE="${DO_UPDATE}" DO_UNINSTALL="${DO_UNINSTALL}" \
    CONFIGURE_INPUT="${CONFIGURE_INPUT}" ENABLE_INPUT="${ENABLE_INPUT}" \
    DISABLE_INPUT="${DISABLE_INPUT}" DELETE_INPUT="${DELETE_INPUT}" \
    RENDER_SENDER_CONFIG="${RENDER_SENDER_CONFIG}" RENDER_HEC_HANDOFF="${RENDER_HEC_HANDOFF}" \
    DO_VALIDATE="${DO_VALIDATE}" DO_DOCTOR="${DO_DOCTOR}" DO_REPAIR="${DO_REPAIR}" \
    APP_ID="${APP_ID}" APP_NAME="${APP_NAME}" APP_VERSION="${APP_VERSION}" \
    INPUT_NAME="${INPUT_NAME}" GRPC_PORT="${GRPC_PORT}" HTTP_PORT="${HTTP_PORT}" \
    LISTEN_ADDRESS="${LISTEN_ADDRESS}" ENABLE_SSL="${ENABLE_SSL}" INDEX="${INDEX}" \
    SOURCE_VALUE="${SOURCE_VALUE}" SOURCETYPE_VALUE="${SOURCETYPE_VALUE}" \
    OUTPUT_DIR="${OUTPUT_DIR}" EXPECTED_INDEX="${EXPECTED_INDEX}" RECEIVER_HOST="${RECEIVER_HOST}" \
    SENDER_PROTOCOL="${SENDER_PROTOCOL}" SENDER_TLS="${SENDER_TLS}" HEC_TOKEN_FILE="${HEC_TOKEN_FILE}" \
    HEC_PLATFORM="${HEC_PLATFORM}" HEC_TOKEN_NAME="${HEC_TOKEN_NAME}" \
    HEC_ALLOWED_INDEXES="${HEC_ALLOWED_INDEXES}" FIXES="${FIXES}" python3 - <<'PY'
import json
import os

op_names = [
    ("install", "DO_INSTALL"),
    ("update", "DO_UPDATE"),
    ("uninstall", "DO_UNINSTALL"),
    ("configure-input", "CONFIGURE_INPUT"),
    ("enable-input", "ENABLE_INPUT"),
    ("disable-input", "DISABLE_INPUT"),
    ("delete-input", "DELETE_INPUT"),
    ("render-sender-config", "RENDER_SENDER_CONFIG"),
    ("render-hec-handoff", "RENDER_HEC_HANDOFF"),
    ("validate", "DO_VALIDATE"),
    ("doctor", "DO_DOCTOR"),
    ("repair", "DO_REPAIR"),
]
payload = {
    "app": {
        "name": os.environ["APP_NAME"],
        "splunkbase_id": os.environ["APP_ID"],
        "latest_verified_version": os.environ["APP_VERSION"],
    },
    "dry_run": True,
    "operations": [name for name, env in op_names if os.environ.get(env) == "true"],
    "input": {
        "name": os.environ["INPUT_NAME"],
        "grpc_port": int(os.environ["GRPC_PORT"]),
        "http_port": int(os.environ["HTTP_PORT"]),
        "listen_address": os.environ["LISTEN_ADDRESS"],
        "enableSSL": os.environ["ENABLE_SSL"] == "true",
        "index": os.environ["INDEX"],
        "source": os.environ["SOURCE_VALUE"],
        "sourcetype": os.environ["SOURCETYPE_VALUE"],
    },
    "sender": {
        "receiver_host": os.environ["RECEIVER_HOST"],
        "protocol": os.environ["SENDER_PROTOCOL"],
        "tls": os.environ["SENDER_TLS"] == "true",
        "hec_token_file_path_reference": os.environ["HEC_TOKEN_FILE"],
        "expected_index": os.environ["EXPECTED_INDEX"],
        "auth_header_format": "Authorization: Splunk <HEC_TOKEN>",
        "token_value_rendered": False,
    },
    "hec_handoff": {
        "skill": "splunk-hec-service-setup",
        "platform": os.environ["HEC_PLATFORM"],
        "token_name": os.environ["HEC_TOKEN_NAME"],
        "allowed_indexes": os.environ["HEC_ALLOWED_INDEXES"],
        "token_value_rendered": False,
    },
    "repair": {
        "fixes": [item.strip() for item in os.environ["FIXES"].split(",") if item.strip()],
        "conservative": True,
    },
    "output_dir": os.environ["OUTPUT_DIR"],
}
print(json.dumps(payload, indent=2, sort_keys=True))
PY
}

run_or_log() {
    local -a cmd=("$@")
    if [[ "${DRY_RUN}" == "true" ]]; then
        printf 'DRY RUN:'
        printf ' %q' "${cmd[@]}"
        printf '\n'
    else
        "${cmd[@]}"
    fi
}

verify_local_package() {
    local package_path="$1"
    if [[ ! -f "${package_path}" ]]; then
        log "ERROR: Local package not found: ${package_path}"
        exit 1
    fi
    python3 - "${package_path}" "${KNOWN_SHA256}" <<'PY'
from pathlib import Path
import hashlib
import sys

path = Path(sys.argv[1])
expected = sys.argv[2]
actual = hashlib.sha256(path.read_bytes()).hexdigest()
if actual != expected:
    raise SystemExit(
        "ERROR: Local package SHA256 does not match audited splunk-connect-for-otlp 0.4.1 release."
    )
PY
}

run_install() {
    local update_flag="$1"
    local -a cmd=(bash "${INSTALL_APP_SCRIPT}")
    if [[ -n "${LOCAL_PACKAGE}" ]]; then
        verify_local_package "${LOCAL_PACKAGE}"
        cmd+=(--source local --file "${LOCAL_PACKAGE}")
    else
        cmd+=(--source splunkbase --app-id "${APP_ID}")
    fi
    if [[ "${update_flag}" == "true" ]]; then
        cmd+=(--update)
    else
        cmd+=(--no-update)
    fi
    if [[ "${NO_RESTART}" == "true" ]]; then
        cmd+=(--no-restart)
    fi
    run_or_log "${cmd[@]}"
}

run_uninstall() {
    local -a cmd=(bash "${UNINSTALL_APP_SCRIPT}" --app-name "${APP_NAME}")
    if [[ "${NO_RESTART}" == "true" ]]; then
        cmd+=(--no-restart)
    fi
    if [[ "${DRY_RUN}" == "true" ]]; then
        run_or_log "${cmd[@]}"
    else
        printf 'y\n' | "${cmd[@]}"
    fi
}

load_rest_session() {
    load_splunk_credentials || exit 1
    SK="$(get_session_key "${SPLUNK_URI}")"
    if [[ -z "${SK}" ]]; then
        log "ERROR: Unable to obtain Splunk session key."
        exit 1
    fi
}

append_form_pair() {
    local key="$1" value="$2" pair
    pair="$(form_urlencode_pairs "${key}" "${value}")" || exit 1
    if [[ -z "${FORM_BODY:-}" ]]; then
        FORM_BODY="${pair}"
    else
        FORM_BODY="${FORM_BODY}&${pair}"
    fi
}

configure_input() {
    local FORM_BODY=""
    append_form_pair grpc_port "${GRPC_PORT}"
    append_form_pair http_port "${HTTP_PORT}"
    append_form_pair listen_address "${LISTEN_ADDRESS}"
    append_form_pair enableSSL "$(if [[ "${ENABLE_SSL}" == "true" ]]; then printf '1'; else printf '0'; fi)"
    append_form_pair serverCert "${SERVER_CERT}"
    append_form_pair serverKey "${SERVER_KEY}"
    append_form_pair disabled "${DISABLED}"
    append_form_pair index "${INDEX}"
    append_form_pair source "${SOURCE_VALUE}"
    append_form_pair sourcetype "${SOURCETYPE_VALUE}"
    append_form_pair interval "${INTERVAL}"
    if [[ -n "${HOST_VALUE}" ]]; then
        append_form_pair host "${HOST_VALUE}"
    fi
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: upsert ${INPUT_TYPE}://${INPUT_NAME} on ${APP_NAME}"
        return 0
    fi
    load_rest_session
    rest_create_input "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "${INPUT_TYPE}" "${INPUT_NAME}" "${FORM_BODY}"
}

set_input_state() {
    local state="$1"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: set ${INPUT_TYPE}://${INPUT_NAME} disabled=${state}"
        return 0
    fi
    load_rest_session
    rest_apply_input_enable_state "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "${INPUT_TYPE}" "${INPUT_NAME}" "${state}"
}

delete_input() {
    local endpoint encoded_name resp http_code
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: delete ${INPUT_TYPE}://${INPUT_NAME}"
        return 0
    fi
    load_rest_session
    endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/data/inputs/${INPUT_TYPE}"
    encoded_name="$(_urlencode "${INPUT_NAME}")"
    resp="$(splunk_curl "${SK}" -X DELETE "${endpoint}/${encoded_name}?output_mode=json" -w '\n%{http_code}' 2>/dev/null || true)"
    http_code="$(echo "${resp}" | tail -1)"
    case "${http_code}" in
        200|204|404) ;;
        *) log "ERROR: Delete ${INPUT_TYPE}://${INPUT_NAME} failed (HTTP ${http_code})"; exit 1 ;;
    esac
}

render_sender_config() {
    local -a cmd=(
        python3 "${SENDER_RENDERER}"
        --output-dir "${OUTPUT_DIR}"
        --receiver-host "${RECEIVER_HOST}"
        --grpc-port "${GRPC_PORT}"
        --http-port "${HTTP_PORT}"
        --sender-protocol "${SENDER_PROTOCOL}"
        --sender-tls "${SENDER_TLS}"
        --hec-token-file "${HEC_TOKEN_FILE}"
        --index "${EXPECTED_INDEX}"
        --source "${SOURCE_VALUE}"
        --sourcetype "${SOURCETYPE_VALUE}"
    )
    if [[ "${DRY_RUN}" == "true" ]]; then
        cmd+=(--dry-run)
    fi
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        cmd+=(--json)
    fi
    run_or_log "${cmd[@]}"
}

render_hec_handoff() {
    local dir script token_file_arg
    dir="${OUTPUT_DIR}/${APP_NAME}"
    script="${dir}/render-hec-handoff.sh"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: render ${script}"
        return 0
    fi
    mkdir -p "${dir}"
    token_file_arg=""
    if [[ -n "${HEC_TOKEN_FILE}" ]]; then
        token_file_arg="--token-file ${HEC_TOKEN_FILE}"
    fi
    cat > "${script}" <<EOF
#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT}"
exec bash "\${PROJECT_ROOT}/skills/splunk-hec-service-setup/scripts/setup.sh" \\
  --platform "${HEC_PLATFORM}" \\
  --phase render \\
  --token-name "${HEC_TOKEN_NAME}" \\
  --description "Managed for splunk-connect-for-otlp" \\
  --default-index "${EXPECTED_INDEX}" \\
  --allowed-indexes "${HEC_ALLOWED_INDEXES}" \\
  --source "${SOURCE_VALUE}" \\
  --sourcetype "${SOURCETYPE_VALUE}" \\
  --output-dir "${OUTPUT_DIR}/hec-service" \\
  ${token_file_arg}
EOF
    chmod 755 "${script}"
    log "Rendered HEC handoff to ${script}"
}

run_validate() {
    local -a cmd=(
        bash "${VALIDATE_SCRIPT}"
        --input-name "${INPUT_NAME}"
        --expected-index "${EXPECTED_INDEX}"
        --grpc-port "${GRPC_PORT}"
        --http-port "${HTTP_PORT}"
    )
    if [[ -n "${PACKAGE_FILE}" ]]; then
        cmd+=(--package-file "${PACKAGE_FILE}")
    fi
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        cmd+=(--json)
    fi
    if [[ "${DRY_RUN}" == "true" ]]; then
        cmd+=(--dry-run)
    fi
    run_or_log "${cmd[@]}"
}

run_doctor() {
    local -a cmd=(
        python3 "${DOCTOR_SCRIPT}"
        --output-dir "${OUTPUT_DIR}"
        --expected-index "${EXPECTED_INDEX}"
    )
    if [[ -n "${EVIDENCE_FILE}" ]]; then
        cmd+=(--evidence-file "${EVIDENCE_FILE}")
    fi
    if [[ -n "${PACKAGE_FILE}" ]]; then
        cmd+=(--package-file "${PACKAGE_FILE}")
    fi
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        cmd+=(--json)
    fi
    if [[ "${DRY_RUN}" == "true" ]]; then
        cmd+=(--dry-run)
    fi
    run_or_log "${cmd[@]}"
}

run_repair() {
    local fix
    if [[ -z "${FIXES}" ]]; then
        log "ERROR: --repair requires --fixes FIX_ID[,FIX_ID]."
        exit 1
    fi
    IFS=',' read -r -a fix_array <<< "${FIXES}"
    for fix in "${fix_array[@]}"; do
        fix="${fix//[[:space:]]/}"
        case "${fix}" in
            APP_MISSING) run_install false ;;
            APP_OUTDATED) run_install true ;;
            INPUT_MISSING|BAD_PORT|BAD_LISTEN_ADDRESS) configure_input ;;
            INPUT_DISABLED) set_input_state 0 ;;
            HEC_GLOBAL_DISABLED|HEC_TOKEN_MISSING|HEC_TOKEN_DISABLED|HEC_ALLOWED_INDEX_MISSING)
                render_hec_handoff
                ;;
            TLS_SENDER_RECEIVER_MISMATCH|SENDER_INDEX_FORBIDDEN|SENDER_AUTH_HEADER_MISSING|SENDER_HTTP_PATH_INVALID|SENDER_PORT_MISMATCH)
                render_sender_config
                ;;
            *)
                log "No automated repair for ${fix}; see doctor fix plan."
                ;;
        esac
    done
}

main() {
    validate_common_args
    if [[ "${DRY_RUN}" == "true" && "${JSON_OUTPUT}" == "true" ]]; then
        json_plan
        exit 0
    fi
    [[ "${DO_INSTALL}" == "true" ]] && run_install false
    [[ "${DO_UPDATE}" == "true" ]] && run_install true
    [[ "${DO_UNINSTALL}" == "true" ]] && run_uninstall
    [[ "${CONFIGURE_INPUT}" == "true" ]] && configure_input
    [[ "${ENABLE_INPUT}" == "true" ]] && set_input_state 0
    [[ "${DISABLE_INPUT}" == "true" ]] && set_input_state 1
    [[ "${DELETE_INPUT}" == "true" ]] && delete_input
    [[ "${RENDER_SENDER_CONFIG}" == "true" ]] && render_sender_config
    [[ "${RENDER_HEC_HANDOFF}" == "true" ]] && render_hec_handoff
    [[ "${DO_VALIDATE}" == "true" ]] && run_validate
    [[ "${DO_DOCTOR}" == "true" ]] && run_doctor
    [[ "${DO_REPAIR}" == "true" ]] && run_repair
    if [[ "${DO_INSTALL}${DO_UPDATE}${DO_UNINSTALL}${CONFIGURE_INPUT}${ENABLE_INPUT}${DISABLE_INPUT}${DELETE_INPUT}${RENDER_SENDER_CONFIG}${RENDER_HEC_HANDOFF}${DO_VALIDATE}${DO_DOCTOR}${DO_REPAIR}" != *true* ]]; then
        usage 1
    fi
}

main "$@"
