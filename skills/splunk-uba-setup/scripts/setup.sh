#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

KAFKA_APP_ID="4147"
INSTALL_APP_SCRIPT="${PROJECT_ROOT}/skills/splunk-app-install/scripts/install_app.sh"
VALIDATE_SCRIPT="${SCRIPT_DIR}/validate.sh"
UBA_INDEXES=("ueba" "ueba_summaries" "ubaroute" "ers")
SUPPORT_APPS=("SplunkEnterpriseSecuritySuite" "SA-UEBA" "DA-ESS-UEBA" "Splunk_TA_ueba")
EOS_DATE="2025-12-12"
END_OF_SUPPORT_DATE="2027-01-31"

SOURCE="splunkbase"
APP_VERSION=""
LOCAL_FILE=""
NO_RESTART=false
INSTALL=false
VALIDATE=false
MODE_SET=false
DRY_RUN=false
JSON_OUTPUT=false
INSTALL_KAFKA_APP=false
UBA_HOST=""
MIGRATION_HANDOFF=true

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk UBA Setup

Usage: $(basename "$0") [OPTIONS]

Modes:
  --install             Install/configure only
  --validate            Validate only
  --dry-run             Show the plan without changing Splunk
  --json                Emit JSON with --dry-run

Options:
  --install-kafka-app   Install Splunk UBA Kafka Ingestion App
  --source splunkbase|local
  --app-version VER     Pin Splunkbase app version for the Kafka app
  --file PATH           Local Kafka ingestion app package
  --kafka-app-file PATH Local Kafka ingestion app package
  --uba-host HOST       Non-secret existing UBA host for handoff notes
  --migration-handoff   Include ES Premier UEBA migration handoff (default)
  --no-migration-handoff
  --no-restart          Skip installer restart handling
  --help                Show this help

Default with no mode validates readiness and only installs the Kafka app when
--install-kafka-app is supplied.
EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) INSTALL=true; MODE_SET=true; shift ;;
        --validate) VALIDATE=true; MODE_SET=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --install-kafka-app) INSTALL_KAFKA_APP=true; shift ;;
        --source) require_arg "$1" $# || exit 1; SOURCE="$2"; shift 2 ;;
        --app-version) require_arg "$1" $# || exit 1; APP_VERSION="$2"; shift 2 ;;
        --file|--kafka-app-file) require_arg "$1" $# || exit 1; LOCAL_FILE="$2"; shift 2 ;;
        --uba-host) require_arg "$1" $# || exit 1; UBA_HOST="$2"; shift 2 ;;
        --migration-handoff) MIGRATION_HANDOFF=true; shift ;;
        --no-migration-handoff) MIGRATION_HANDOFF=false; shift ;;
        --no-restart) NO_RESTART=true; shift ;;
        --help|-h) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ "${MODE_SET}" != "true" ]]; then
    INSTALL=true
    VALIDATE=true
fi

case "${SOURCE}" in
    splunkbase|local) ;;
    *) echo "ERROR: --source must be splunkbase or local." >&2; exit 1 ;;
esac

KAFKA_INSTALL_CMD=()
VALIDATE_CMD=(bash "${VALIDATE_SCRIPT}")

build_commands() {
    if [[ "${INSTALL_KAFKA_APP}" == "true" ]]; then
        KAFKA_INSTALL_CMD=(bash "${INSTALL_APP_SCRIPT}")
        if [[ "${SOURCE}" == "splunkbase" ]]; then
            KAFKA_INSTALL_CMD+=(--source splunkbase --app-id "${KAFKA_APP_ID}" --no-update)
            [[ -n "${APP_VERSION}" ]] && KAFKA_INSTALL_CMD+=(--app-version "${APP_VERSION}")
        else
            [[ -n "${LOCAL_FILE}" ]] || { echo "ERROR: --source local requires --file for the Kafka app." >&2; exit 1; }
            KAFKA_INSTALL_CMD+=(--source local --file "${LOCAL_FILE}" --no-update)
        fi
        [[ "${NO_RESTART}" == "true" ]] && KAFKA_INSTALL_CMD+=(--no-restart)
        VALIDATE_CMD+=(--kafka-app)
    fi
    [[ -n "${UBA_HOST}" ]] && VALIDATE_CMD+=(--uba-host "${UBA_HOST}")
    return 0
}

join_unit() {
    local IFS=$'\037'
    printf '%s' "$*"
}

emit_plan() {
    local phases=()
    [[ "${INSTALL}" == "true" && "${INSTALL_KAFKA_APP}" == "true" ]] && phases+=("install-kafka-app")
    [[ "${MIGRATION_HANDOFF}" == "true" ]] && phases+=("migration-handoff")
    [[ "${VALIDATE}" == "true" ]] && phases+=("validate-readiness")

    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        JSON_PHASES="$(join_unit "${phases[@]}")" \
        JSON_KAFKA_INSTALL_COMMAND="$(join_unit "${KAFKA_INSTALL_CMD[@]}")" \
        JSON_VALIDATE_COMMAND="$(join_unit "${VALIDATE_CMD[@]}")" \
        JSON_UBA_INDEXES="$(join_unit "${UBA_INDEXES[@]}")" \
        JSON_SUPPORT_APPS="$(join_unit "${SUPPORT_APPS[@]}")" \
        INSTALL_KAFKA_APP="${INSTALL_KAFKA_APP}" UBA_HOST="${UBA_HOST}" \
        MIGRATION_HANDOFF="${MIGRATION_HANDOFF}" EOS_DATE="${EOS_DATE}" END_OF_SUPPORT_DATE="${END_OF_SUPPORT_DATE}" \
        python3 - <<'PY'
import json
import os
import sys

sep = "\x1f"
payload = {
    "ok": True,
    "dry_run": True,
    "product": "Splunk User Behavior Analytics",
    "status": "partial",
    "standalone_uba_server_install_supported": False,
    "end_of_sale": os.environ["EOS_DATE"],
    "end_of_support": os.environ["END_OF_SUPPORT_DATE"],
    "migration_target": "Splunk Enterprise Security Premier UEBA",
    "phases": os.environ.get("JSON_PHASES", "").split(sep) if os.environ.get("JSON_PHASES") else [],
    "kafka_app": {
        "app_id": "4147",
        "app_name": "Splunk-UBA-SA-Kafka",
        "install_requested": os.environ.get("INSTALL_KAFKA_APP") == "true",
    },
    "kafka_install_command": os.environ.get("JSON_KAFKA_INSTALL_COMMAND", "").split(sep) if os.environ.get("JSON_KAFKA_INSTALL_COMMAND") else [],
    "validate_command": os.environ.get("JSON_VALIDATE_COMMAND", "").split(sep) if os.environ.get("JSON_VALIDATE_COMMAND") else [],
    "support_apps": os.environ.get("JSON_SUPPORT_APPS", "").split(sep) if os.environ.get("JSON_SUPPORT_APPS") else [],
    "indexes": os.environ.get("JSON_UBA_INDEXES", "").split(sep) if os.environ.get("JSON_UBA_INDEXES") else [],
    "handoff": {
        "uba_host": os.environ.get("UBA_HOST", ""),
        "migration_handoff": os.environ.get("MIGRATION_HANDOFF") == "true",
        "note": "New UEBA work should use Enterprise Security Premier UEBA; standalone UBA server install is not automated.",
    },
}
json.dump(payload, sys.stdout, indent=2, sort_keys=True)
sys.stdout.write("\n")
PY
    else
        echo "Planned phases:"
        printf '  - %s\n' "${phases[@]}"
        if [[ "${INSTALL_KAFKA_APP}" == "true" ]]; then
            printf 'Kafka app install command:\n  %q ' "${KAFKA_INSTALL_CMD[@]}"; echo
        else
            echo "Kafka app install: not requested"
        fi
        printf 'Validate command:\n  %q ' "${VALIDATE_CMD[@]}"; echo
        echo "Standalone UBA: end-of-sale ${EOS_DATE}; end-of-support ${END_OF_SUPPORT_DATE}."
        echo "Migration target: Splunk Enterprise Security Premier UEBA."
    fi
}

emit_status_notes() {
    log "Standalone Splunk UBA end-of-sale: ${EOS_DATE}; end-of-support: ${END_OF_SUPPORT_DATE}."
    log "Migration guidance: route new UEBA work to Splunk Enterprise Security Premier UEBA."
    [[ -n "${UBA_HOST}" ]] && log "Existing UBA host handoff target: ${UBA_HOST}"
}

build_commands

if [[ "${DRY_RUN}" == "true" ]]; then
    emit_plan
    exit 0
fi

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    echo "ERROR: --json is only supported with --dry-run." >&2
    exit 1
fi

warn_if_current_skill_role_unsupported
emit_status_notes

if [[ "${INSTALL}" == "true" && "${INSTALL_KAFKA_APP}" == "true" ]]; then
    "${KAFKA_INSTALL_CMD[@]}"
elif [[ "${INSTALL}" == "true" ]]; then
    log "Kafka app install not requested; continuing with readiness validation/handoff."
fi

if [[ "${VALIDATE}" == "true" ]]; then
    "${VALIDATE_CMD[@]}"
fi
