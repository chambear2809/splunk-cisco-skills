#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="SplunkEnterpriseSecuritySuite"
APP_ID="263"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"
VALIDATE_SCRIPT="${VALIDATE_SCRIPT:-${SCRIPT_DIR}/validate.sh}"

DO_INSTALL=false
DO_POST_INSTALL=false
DO_VALIDATE=false
ANY_OPERATION=false

SOURCE="auto"
LOCAL_FILE=""
APP_VERSION=""
DEPLOYMENT_TYPE="search_head"
SSL_ENABLEMENT="strict"
POST_INSTALL_DRY_RUN=false
SKIP_ESSINSTALL=false
NO_VALIDATE=false
NO_RESTART=false
ALLOW_CLOUD=false

PREFLIGHT_ONLY=false
SKIP_PREFLIGHT=false
CONFIRM_UPGRADE=false
BACKUP_NOTICE_PATH=""
SET_SHC_LIMITS=false
ALLOW_DEPLOYMENT_CLIENT=false
APPLY_BUNDLE=false
FORCE_APPLY_BUNDLE=false
GENERATE_TA_DIR=""
DEPLOY_TA_CM_URI=""
SHC_TARGET_URI="${SHC_TARGET_URI:-}"
MIN_TMP_GB="${ES_MIN_TMP_GB:-3}"
SHC_MIN_MAX_UPLOAD_SIZE="${ES_SHC_MIN_MAX_UPLOAD_SIZE:-2048}"
SHC_MIN_MAX_CONTENT_LENGTH="${ES_SHC_MIN_MAX_CONTENT_LENGTH:-5000000000}"
SHC_MIN_SPLUNKD_TIMEOUT="${ES_SHC_MIN_SPLUNKD_TIMEOUT:-300}"
# ES 8.5.x is supported on Splunk Enterprise 9.3+ and 10.x (per the 8.5.1
# Splunkbase listing). Override via ES_MIN_PLATFORM_VERSION if the shipped
# package advertises a different floor.
MIN_PLATFORM_VERSION="${ES_MIN_PLATFORM_VERSION:-9.3}"
BACKUP_KVSTORE=false
UNINSTALL=false

SK=""
PREFLIGHT_FAIL=0
PREFLIGHT_WARN=0

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Enterprise Security Install

Usage: $(basename "$0") [OPTIONS]

Operations:
  --install                         Install/update the ES package
  --post-install                    Run the ES essinstall post-install command
  --validate                        Run read-only validation
  --preflight-only                  Run preflight checks and exit
  (no operation flags)              Preflight, install/update, run essinstall, then validate

Options:
  --source auto|splunkbase|local    Package source (default: auto; local package if present)
  --file PATH                       Local ES .spl/.tgz package
  --app-version VER                 Pin a Splunkbase version
  --deployment-type search_head|shc_deployer
                                    essinstall deployment type (default: search_head)
  --ssl-enablement strict|auto|ignore
                                    essinstall SSL behavior (default: strict)
  --dry-run                         Run essinstall --dry-run
  --skip-essinstall                 Install package but skip essinstall
  --skip-preflight                  Skip preflight checks (emits WARN)
  --confirm-upgrade                 Required when an existing ES install is detected
  --backup-notice PATH              Write backup-runbook file to PATH before upgrade
  --set-shc-limits                  On SHC deployer, set web/server limits via REST
  --allow-deployment-client         Allow install when deploymentclient.conf has stanzas
  --apply-bundle                    After SHC essinstall, apply the bundle via deployer SSH profile
  --shc-target-uri URI              SHC member URI for --apply-bundle and post-apply health
                                    (also used by deployer-side apply; or set SHC_TARGET_URI env)
  --generate-ta-for-indexers DIR    Extract Splunk_TA_ForIndexers from the local ES package
  --deploy-ta-for-indexers CM_URI   Apply cluster-manager bundle via cluster-manager SSH profile;
                                    CM_URI host must match SPLUNK_CLUSTER_MANAGER_PROFILE host
  --force-apply-bundle              Apply the cluster-manager bundle even when 'splunk validate
                                    cluster-bundle' returns non-zero (use only after manual review)
  --backup-kvstore                  Run 'splunk backup kvstore' via the deployer/local SSH profile before upgrade
  --uninstall                       Disable removable framework apps and request uninstall of ES and support apps
  --no-validate                     Skip validation in default flow
  --no-restart                      Pass --no-restart to the generic installer
  --allow-cloud                     Permit install attempt on Splunk Cloud targets
  --help                            Show this help text

Examples:
  $(basename "$0")
  $(basename "$0") --preflight-only
  $(basename "$0") --deployment-type shc_deployer --set-shc-limits
  $(basename "$0") --source local --file splunk-ta/splunk-enterprise-security_851.spl
  $(basename "$0") --confirm-upgrade --backup-notice /var/backups/es_upgrade.md
  $(basename "$0") --post-install --dry-run
  $(basename "$0") --validate

EOF
    exit "${exit_code}"
}

set_operation() {
    ANY_OPERATION=true
    case "$1" in
        install) DO_INSTALL=true ;;
        post-install) DO_POST_INSTALL=true ;;
        validate) DO_VALIDATE=true ;;
    esac
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) set_operation install; shift ;;
        --post-install) set_operation post-install; shift ;;
        --validate) set_operation validate; shift ;;
        --source)
            require_arg "$1" $# || exit 1
            SOURCE="$2"
            shift 2
            ;;
        --file)
            require_arg "$1" $# || exit 1
            LOCAL_FILE="$2"
            SOURCE="local"
            shift 2
            ;;
        --app-version)
            require_arg "$1" $# || exit 1
            APP_VERSION="$2"
            shift 2
            ;;
        --deployment-type)
            require_arg "$1" $# || exit 1
            DEPLOYMENT_TYPE="$2"
            shift 2
            ;;
        --ssl-enablement)
            require_arg "$1" $# || exit 1
            SSL_ENABLEMENT="$2"
            shift 2
            ;;
        --dry-run) POST_INSTALL_DRY_RUN=true; shift ;;
        --skip-essinstall) SKIP_ESSINSTALL=true; shift ;;
        --preflight-only) PREFLIGHT_ONLY=true; ANY_OPERATION=true; shift ;;
        --skip-preflight) SKIP_PREFLIGHT=true; shift ;;
        --confirm-upgrade) CONFIRM_UPGRADE=true; shift ;;
        --backup-notice)
            require_arg "$1" $# || exit 1
            BACKUP_NOTICE_PATH="$2"
            shift 2
            ;;
        --set-shc-limits) SET_SHC_LIMITS=true; shift ;;
        --allow-deployment-client) ALLOW_DEPLOYMENT_CLIENT=true; shift ;;
        --apply-bundle) APPLY_BUNDLE=true; ANY_OPERATION=true; shift ;;
        --force-apply-bundle) FORCE_APPLY_BUNDLE=true; shift ;;
        --shc-target-uri)
            require_arg "$1" $# || exit 1
            SHC_TARGET_URI="$2"
            shift 2
            ;;
        --generate-ta-for-indexers)
            require_arg "$1" $# || exit 1
            GENERATE_TA_DIR="$2"
            ANY_OPERATION=true
            shift 2
            ;;
        --deploy-ta-for-indexers)
            require_arg "$1" $# || exit 1
            DEPLOY_TA_CM_URI="$2"
            ANY_OPERATION=true
            shift 2
            ;;
        --backup-kvstore) BACKUP_KVSTORE=true; ANY_OPERATION=true; shift ;;
        --uninstall) UNINSTALL=true; ANY_OPERATION=true; shift ;;
        --no-validate) NO_VALIDATE=true; shift ;;
        --no-restart) NO_RESTART=true; shift ;;
        --allow-cloud) ALLOW_CLOUD=true; shift ;;
        --help|-h) usage 0 ;;
        *)
            log "ERROR: Unknown option '$1'"
            usage 1
            ;;
    esac
done

case "${SOURCE}" in
    auto|splunkbase|local) ;;
    *)
        log "ERROR: --source must be auto, splunkbase, or local."
        exit 1
        ;;
esac

case "${DEPLOYMENT_TYPE}" in
    search_head|shc_deployer) ;;
    *)
        log "ERROR: --deployment-type must be search_head or shc_deployer."
        exit 1
        ;;
esac

case "${SSL_ENABLEMENT}" in
    strict|auto|ignore) ;;
    *)
        log "ERROR: --ssl-enablement must be strict, auto, or ignore."
        exit 1
        ;;
esac

if [[ "${DEPLOYMENT_TYPE}" == "shc_deployer" && "${SSL_ENABLEMENT}" == "auto" ]]; then
    log "ERROR: --ssl-enablement auto is not allowed for SHC deployer installs."
    exit 1
fi

if [[ "${UNINSTALL}" == "true" ]]; then
    uninstall_conflicts=()
    [[ "${DO_INSTALL}" == "true" ]] && uninstall_conflicts+=("--install")
    [[ "${DO_POST_INSTALL}" == "true" ]] && uninstall_conflicts+=("--post-install")
    [[ "${DO_VALIDATE}" == "true" ]] && uninstall_conflicts+=("--validate")
    [[ "${PREFLIGHT_ONLY}" == "true" ]] && uninstall_conflicts+=("--preflight-only")
    [[ "${BACKUP_KVSTORE}" == "true" ]] && uninstall_conflicts+=("--backup-kvstore")
    [[ "${SET_SHC_LIMITS}" == "true" ]] && uninstall_conflicts+=("--set-shc-limits")
    [[ "${APPLY_BUNDLE}" == "true" ]] && uninstall_conflicts+=("--apply-bundle")
    [[ -n "${GENERATE_TA_DIR}" ]] && uninstall_conflicts+=("--generate-ta-for-indexers")
    [[ -n "${DEPLOY_TA_CM_URI}" ]] && uninstall_conflicts+=("--deploy-ta-for-indexers")
    if ((${#uninstall_conflicts[@]} > 0)); then
        log "ERROR: --uninstall must be run by itself. Remove conflicting flags: ${uninstall_conflicts[*]}"
        exit 1
    fi
fi

if [[ "${ANY_OPERATION}" == "false" ]]; then
    DO_INSTALL=true
    DO_POST_INSTALL=true
    if [[ "${NO_VALIDATE}" == "false" ]]; then
        DO_VALIDATE=true
    fi
fi

if [[ "${SKIP_ESSINSTALL}" == "true" ]]; then
    DO_POST_INSTALL=false
fi

ensure_session() {
    if [[ -n "${SK}" ]]; then
        return 0
    fi
    load_splunk_credentials || {
        log "ERROR: Splunk credentials are required."
        exit 1
    }
    warn_if_current_skill_role_unsupported
    SK="$(get_session_key "${SPLUNK_URI}")" || {
        log "ERROR: Could not authenticate to Splunk REST API."
        exit 1
    }
}

server_version() {
    splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/server/info?output_mode=json" 2>/dev/null \
        | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    entries = data.get("entry", [])
    print(entries[0].get("content", {}).get("version", "unknown") if entries else "unknown", end="")
except Exception:
    print("unknown", end="")
' 2>/dev/null || echo "unknown"
}

preflight_pass() { log "  PASS: $*"; }
preflight_warn() { log "  WARN: $*"; PREFLIGHT_WARN=$((PREFLIGHT_WARN + 1)); }
preflight_fail() { log "  FAIL: $*"; PREFLIGHT_FAIL=$((PREFLIGHT_FAIL + 1)); }

preflight_kvstore() {
    local status
    status="$(splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/kvstore/status?output_mode=json" 2>/dev/null \
        | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    entries = data.get("entry", [])
    print(entries[0].get("content", {}).get("current", {}).get("status", "unknown") if entries else "unknown", end="")
except Exception:
    print("unknown", end="")
' 2>/dev/null || echo "unknown")"
    case "${status}" in
        ready) preflight_pass "KV Store status is ready" ;;
        *) preflight_fail "KV Store status is '${status}'; ES requires a healthy KV Store" ;;
    esac
}

preflight_tmp_space() {
    local report
    report="$(splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/server/status/partitions-space?output_mode=json" 2>/dev/null \
        | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    tmp_free = None
    for entry in data.get('entry', []):
        content = entry.get('content', {}) or {}
        mount = content.get('mount_point') or entry.get('name') or ''
        if mount != '/tmp':
            continue
        free = content.get('free_mb', content.get('free', 0))
        try:
            tmp_free = float(free) / 1024.0
        except (TypeError, ValueError):
            tmp_free = None
        break
    if tmp_free is None:
        # /tmp is not reported as a distinct mount; ES extracts under /tmp at
        # install time so we can't substitute a sibling mount's free space and
        # call it equivalent. Surface 'unknown' so the operator knows we did
        # not actually validate the space requirement.
        print('unknown', end='')
    else:
        print(f'{tmp_free:.2f}', end='')
except Exception:
    print('error', end='')
" 2>/dev/null || echo "error")"
    if [[ "${report}" == "unknown" ]]; then
        preflight_warn "/tmp partition was not reported by REST; could not verify ES installer needs ~${MIN_TMP_GB} GB free. Run 'df -h /tmp' on the host and free space if needed."
        return 0
    fi
    if [[ "${report}" == "error" ]]; then
        preflight_warn "Could not parse /services/server/status/partitions-space; skipping /tmp space check."
        return 0
    fi
    if awk -v f="${report}" -v m="${MIN_TMP_GB}" 'BEGIN { exit (f+0 < m+0) }'; then
        preflight_pass "/tmp has ${report} GB free (need ${MIN_TMP_GB} GB)"
    else
        preflight_fail "Only ${report} GB free on /tmp; ES installer needs ~${MIN_TMP_GB} GB"
    fi
}

preflight_license() {
    local license_group
    license_group="$(splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/licenser/groups?output_mode=json" 2>/dev/null \
        | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    for entry in data.get("entry", []):
        content = entry.get("content", {}) or {}
        if content.get("is_active") in (True, 1, "1"):
            print(entry.get("name", "unknown"), end="")
            raise SystemExit(0)
    print("", end="")
except SystemExit:
    raise
except Exception:
    print("error", end="")
' 2>/dev/null || echo "error")"
    case "${license_group}" in
        ""|error) preflight_warn "Could not identify an active Splunk license group; ES requires a valid Splunk Enterprise license" ;;
        *) preflight_pass "Active license group: ${license_group}" ;;
    esac

    # ES requires a premium entitlement (SKU-level). We can't perfectly detect
    # entitlement from the licenser REST alone, but we can inspect licenser/stack
    # feature labels for anything containing "enterprise_security" or fall back
    # to the licenser/messages stream for entitlement warnings.
    local sku_hint
    sku_hint="$(splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/licenser/stack?output_mode=json" 2>/dev/null \
        | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    found = []
    for entry in data.get("entry", []):
        content = entry.get("content", {}) or {}
        features = content.get("features") or []
        if isinstance(features, dict):
            features = list(features.keys())
        for feat in features:
            label = str(feat).lower()
            if "enterprise_security" in label or label.endswith("_es"):
                found.append(str(feat))
    print(",".join(found), end="")
except Exception:
    print("", end="")
' 2>/dev/null || echo "")"
    if [[ -n "${sku_hint}" ]]; then
        preflight_pass "Splunk license stack advertises ES entitlement: ${sku_hint}"
    else
        preflight_warn "No ES entitlement feature detected in the license stack; confirm a valid ES SKU is applied"
    fi
}

preflight_platform_version() {
    local version major minor
    version="$(server_version)"
    if [[ -z "${version}" || "${version}" == "unknown" ]]; then
        preflight_warn "Could not determine Splunk platform version; ES ${APP_NAME} requires Splunk >= ${MIN_PLATFORM_VERSION}"
        return 0
    fi
    # Derive major.minor from e.g. 10.2.1 or 9.3.2.4
    if ! [[ "${version}" =~ ^([0-9]+)\.([0-9]+) ]]; then
        preflight_warn "Platform version '${version}' is not in the expected major.minor form"
        return 0
    fi
    major="${BASH_REMATCH[1]}"
    minor="${BASH_REMATCH[2]}"
    local min_major min_minor
    if ! [[ "${MIN_PLATFORM_VERSION}" =~ ^([0-9]+)\.([0-9]+) ]]; then
        preflight_warn "ES_MIN_PLATFORM_VERSION='${MIN_PLATFORM_VERSION}' is malformed; skipping platform-version check"
        return 0
    fi
    min_major="${BASH_REMATCH[1]}"
    min_minor="${BASH_REMATCH[2]}"
    if (( major > min_major )) || (( major == min_major && minor >= min_minor )); then
        preflight_pass "Splunk platform version ${version} meets ES floor ${MIN_PLATFORM_VERSION}"
    else
        preflight_fail "Splunk platform version ${version} is below the ES floor ${MIN_PLATFORM_VERSION}; upgrade Splunk Enterprise before installing ES"
    fi
}

preflight_deploymentclient() {
    local count
    count="$(splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/configs/conf-deploymentclient?output_mode=json" 2>/dev/null \
        | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    count = 0
    for entry in data.get("entry", []):
        name = entry.get("name", "")
        if name in ("default", "default-autolb", "general", "", None):
            continue
        content = entry.get("content", {}) or {}
        if content.get("targetUri") or content.get("serverClasses"):
            count += 1
    print(count, end="")
except Exception:
    print("0", end="")
' 2>/dev/null || echo "0")"
    if [[ "${count}" -gt 0 ]]; then
        if [[ "${ALLOW_DEPLOYMENT_CLIENT}" == "true" ]]; then
            preflight_warn "deploymentclient.conf has ${count} active stanza(s); proceeding because --allow-deployment-client is set"
        else
            preflight_fail "deploymentclient.conf has ${count} active stanza(s); remove them or re-run with --allow-deployment-client"
        fi
    else
        preflight_pass "deploymentclient.conf has no active managed-host stanzas"
    fi
}

preflight_admin() {
    local result
    result="$(splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/authentication/current-context?output_mode=json" 2>/dev/null \
        | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    entries = data.get("entry", [])
    content = entries[0].get("content", {}) if entries else {}
    roles = set(content.get("roles") or [])
    caps = set(content.get("capabilities") or [])
    if {"admin", "sc_admin"} & roles:
        print("role_admin", end="")
    elif {"edit_local_apps", "admin_all_objects", "install_apps"} & caps:
        print("cap_admin", end="")
    else:
        print("no", end="")
except Exception:
    print("error", end="")
' 2>/dev/null || echo "error")"
    case "${result}" in
        role_admin) preflight_pass "Calling user holds admin or sc_admin role" ;;
        cap_admin) preflight_pass "Calling user holds edit_local_apps / admin_all_objects / install_apps capability" ;;
        no) preflight_fail "Calling user lacks admin/sc_admin role and edit_local_apps capability" ;;
        *) preflight_warn "Could not determine calling-user capabilities" ;;
    esac
}

detect_es_version() {
    rest_get_app_version "${SK}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null || true
}

preflight_upgrade_confirmation() {
    local current
    current="$(detect_es_version)"
    if [[ -z "${current}" ]]; then
        preflight_pass "No existing ${APP_NAME} detected; fresh install"
        return 0
    fi
    log "  INFO: Existing ${APP_NAME} version detected: ${current}"
    if [[ "${CONFIRM_UPGRADE}" != "true" ]]; then
        preflight_fail "ES is already installed. Re-run with --confirm-upgrade to proceed with an in-place upgrade (ES 8.x upgrades are one-way; back up the search head and KV Store first)"
        return 0
    fi
    preflight_pass "Upgrade confirmed via --confirm-upgrade (existing version: ${current})"
}

write_backup_notice() {
    [[ -n "${BACKUP_NOTICE_PATH}" ]] || return 0
    local parent
    parent="$(dirname "${BACKUP_NOTICE_PATH}")"
    if [[ -n "${parent}" && ! -d "${parent}" ]]; then
        mkdir -p "${parent}" 2>/dev/null || true
    fi
    log "Writing ES pre-upgrade backup runbook to ${BACKUP_NOTICE_PATH}"
    cat >"${BACKUP_NOTICE_PATH}" <<'EOF'
# Splunk Enterprise Security Pre-Upgrade Backup Runbook
#
# ES 8.x upgrades are one-way. Run these commands on the ES search head
# (or deployer for SHC) BEFORE starting the install.

# 1. Back up app content (run on standalone SH or every SHC member).
tar -czf /var/backups/es_apps_$(date +%Y%m%d_%H%M%S).tgz -C "$SPLUNK_HOME/etc" apps

# 2. Back up the KV Store (run on standalone SH, or on the SHC captain).
"$SPLUNK_HOME/bin/splunk" backup kvstore --archive-name es_kvstore_$(date +%Y%m%d_%H%M%S)

# 3. On SHC deployer, also back up etc/shcluster/apps.
tar -czf /var/backups/shcluster_apps_$(date +%Y%m%d_%H%M%S).tgz -C "$SPLUNK_HOME/etc/shcluster" apps

# 4. Record current ES version for rollback reference.
"$SPLUNK_HOME/bin/splunk" display app SplunkEnterpriseSecuritySuite

# 5. Verify every backup archive exists, is non-empty, and is readable by
#    the account that will restore it before you proceed with the upgrade.
EOF
}

conf_global_value() {
    local conf="$1" stanza="$2" key="$3"
    local encoded_stanza
    encoded_stanza="$(_urlencode "${stanza}")"
    splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/configs/conf-${conf}/${encoded_stanza}?output_mode=json" 2>/dev/null \
        | python3 -c '
import json, sys
field = sys.argv[1]
try:
    data = json.load(sys.stdin)
    entries = data.get("entry", [])
    print(entries[0].get("content", {}).get(field, "") if entries else "", end="")
except Exception:
    print("", end="")
' "${key}" 2>/dev/null || true
}

set_conf_global_value() {
    local conf="$1" stanza="$2" key="$3" value="$4"
    local encoded_stanza body response http_code
    encoded_stanza="$(_urlencode "${stanza}")"
    body="$(form_urlencode_pairs "${key}" "${value}")" || return 1
    response="$(splunk_curl_post "${SK}" "${body}" \
        "${SPLUNK_URI}/services/configs/conf-${conf}/${encoded_stanza}" \
        -w '\n%{http_code}' 2>/dev/null || echo "000")"
    http_code="$(printf '%s\n' "${response}" | tail -1)"
    case "${http_code}" in
        200|201) return 0 ;;
        *)
            log "ERROR: Failed to set ${conf}/[${stanza}] ${key}=${value} (HTTP ${http_code})"
            return 1
            ;;
    esac
}

preflight_shc_limit() {
    local conf="$1" stanza="$2" key="$3" minimum="$4"
    local current
    current="$(conf_global_value "${conf}" "${stanza}" "${key}")"
    if [[ -z "${current}" ]]; then
        preflight_warn "Could not read ${conf}.conf [${stanza}] ${key}; SHC deployer needs it >= ${minimum}"
        return 0
    fi
    if ! [[ "${current}" =~ ^[0-9]+$ ]]; then
        preflight_warn "${conf}.conf [${stanza}] ${key} is '${current}' (non-integer); SHC deployer needs >= ${minimum}"
        return 0
    fi
    if (( current >= minimum )); then
        preflight_pass "${conf}.conf [${stanza}] ${key} is ${current} (>= ${minimum})"
        return 0
    fi
    if [[ "${SET_SHC_LIMITS}" == "true" ]]; then
        log "  Adjusting ${conf}.conf [${stanza}] ${key} from ${current} to ${minimum}"
        if set_conf_global_value "${conf}" "${stanza}" "${key}" "${minimum}"; then
            preflight_pass "${conf}.conf [${stanza}] ${key} now ${minimum}"
        else
            preflight_fail "${conf}.conf [${stanza}] ${key} is ${current}; tried to set ${minimum} but the REST write failed"
        fi
    else
        preflight_fail "${conf}.conf [${stanza}] ${key} is ${current}; SHC deployer requires >= ${minimum} (re-run with --set-shc-limits to auto-correct)"
    fi
}

preflight_shc_limits() {
    [[ "${DEPLOYMENT_TYPE}" == "shc_deployer" ]] || return 0
    preflight_shc_limit "web" "settings" "max_upload_size" "${SHC_MIN_MAX_UPLOAD_SIZE}"
    preflight_shc_limit "server" "httpServer" "max_content_length" "${SHC_MIN_MAX_CONTENT_LENGTH}"
    preflight_shc_limit "server" "settings" "splunkdConnectionTimeout" "${SHC_MIN_SPLUNKD_TIMEOUT}"
}

run_preflight() {
    log ""
    log "--- Preflight ---"
    ensure_session
    preflight_admin
    preflight_platform_version
    preflight_license
    preflight_kvstore
    preflight_tmp_space
    preflight_deploymentclient
    preflight_upgrade_confirmation
    preflight_shc_limits
    write_backup_notice
    log "  Preflight summary: FAIL=${PREFLIGHT_FAIL} WARN=${PREFLIGHT_WARN}"
    if (( PREFLIGHT_FAIL > 0 )); then
        log "ERROR: Preflight failed. Address the issues above, or re-run with --skip-preflight to override (not recommended for production)."
        return 1
    fi
    return 0
}

run_generate_ta_for_indexers() {
    [[ -n "${GENERATE_TA_DIR}" ]] || return 0
    log ""
    log "--- Generate Splunk_TA_ForIndexers ---"
    local helper="${SCRIPT_DIR}/generate_ta_for_indexers.sh"
    local args=("--output-dir" "${GENERATE_TA_DIR}" "--force")
    if [[ -n "${LOCAL_FILE}" ]]; then
        args+=("--package" "${LOCAL_FILE}")
    fi
    bash "${helper}" "${args[@]}"
}

apply_shc_bundle() {
    [[ "${APPLY_BUNDLE}" == "true" ]] || return 0
    log ""
    log "--- Apply SHC Bundle ---"
    if [[ "${DEPLOYMENT_TYPE}" != "shc_deployer" ]]; then
        log "  SKIP: --apply-bundle only runs with --deployment-type shc_deployer"
        return 0
    fi
    local deployer_profile
    deployer_profile="$(resolve_deployer_credential_profile 2>/dev/null || true)"
    if [[ -z "${deployer_profile}" ]]; then
        log "  INFO: SPLUNK_DEPLOYER_PROFILE is not configured in the credentials file."
        log "        Emitting handoff instructions for manual apply on the deployer host:"
        log "          \$SPLUNK_HOME/bin/splunk apply shcluster-bundle --answer-yes \\"
        log "              -target <shc-member-uri>:<mgmt-port>"
        return 0
    fi
    if [[ -z "${SHC_TARGET_URI}" ]]; then
        log "  WARN: --shc-target-uri / SHC_TARGET_URI is not set; cannot run apply-bundle via profile."
        log "        Run on the deployer host manually:"
        log "          \$SPLUNK_HOME/bin/splunk apply shcluster-bundle --answer-yes -target <uri>"
        return 0
    fi
    log "  Running 'splunk apply shcluster-bundle' via deployer profile '${deployer_profile}' -> ${SHC_TARGET_URI}"
    if deployment_bundle_apply_on_profile "${deployer_profile}" "shc" "${SHC_TARGET_URI}" "" ""; then
        log "  PASS: SHC bundle applied"
        shc_post_apply_health
    else
        log "  FAIL: apply-bundle failed. See the output above for details."
        return 1
    fi
}

shc_post_apply_health() {
    ensure_session
    # /services/shcluster/status only returns useful data on a member or
    # captain. In the SHC deployer workflow, SPLUNK_URI is typically the
    # deployer (which 404s here), so prefer SHC_TARGET_URI when set.
    local health_uri="${SHC_TARGET_URI:-${SPLUNK_URI}}"
    log "  Checking post-apply SHC cluster status via ${health_uri}..."
    local status_json summary
    status_json="$(splunk_curl "${SK}" \
        "${health_uri}/services/shcluster/status?output_mode=json" 2>/dev/null || true)"
    if [[ -z "${status_json}" ]]; then
        log "  WARN: Could not read /services/shcluster/status from ${health_uri}; cluster-health verification skipped."
        if [[ "${health_uri}" == "${SPLUNK_URI}" ]]; then
            log "        Tip: pass --shc-target-uri https://<member>:8089 (or set SHC_TARGET_URI) to query a member directly."
        fi
        return 0
    fi
    summary="$(printf '%s' "${status_json}" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    entries = data.get("entry") or []
    content = entries[0].get("content", {}) if entries else {}
    captain = content.get("captain") or {}
    members = content.get("members") or []
    total = len(members) if isinstance(members, list) else int(members or 0)
    ready = 0
    if isinstance(members, list):
        for m in members:
            if str(m.get("status") or "").lower() in ("up", "captain", "ready"):
                ready += 1
    captain_label = captain.get("label") or captain.get("hostname") or "unknown"
    print(f"captain={captain_label} members={ready}/{total}", end="")
except Exception:
    print("unparseable", end="")
' 2>/dev/null || echo "unparseable")"
    case "${summary}" in
        unparseable|"") log "  WARN: SHC status response could not be parsed" ;;
        *) log "  SHC status: ${summary}" ;;
    esac
}

validate_cluster_bundle_on_cm() {
    local cm_profile
    cm_profile="$(resolve_cluster_manager_credential_profile 2>/dev/null || true)"
    [[ -n "${cm_profile}" ]] || return 0
    log "  Running 'splunk validate cluster-bundle' via cluster-manager profile '${cm_profile}'..."
    local execution_mode script splunk_home
    execution_mode="$(deployment_run_with_profile "${cm_profile}" deployment_execution_mode_for_profile "")"
    splunk_home="$(deployment_run_with_profile "${cm_profile}" printf '%s' "${SPLUNK_HOME:-/opt/splunk}")"
    script="$(cat <<EOF
set -euo pipefail
"${splunk_home}/bin/splunk" validate cluster-bundle
EOF
)"
    if deployment_run_with_profile "${cm_profile}" \
        hbs_run_target_cmd_with_stdin "${execution_mode}" \
        "$(deployment_run_with_profile "${cm_profile}" hbs_prefix_with_sudo "${execution_mode}" 'bash -s --')" \
        "${script}"; then
        log "  PASS: cluster-bundle validation reported no issues"
        return 0
    fi
    if [[ "${FORCE_APPLY_BUNDLE}" == "true" ]]; then
        log "  WARN: 'splunk validate cluster-bundle' returned non-zero; --force-apply-bundle is set, proceeding anyway."
        return 0
    fi
    log "  FAIL: 'splunk validate cluster-bundle' returned non-zero. Address the issues above, or"
    log "        re-run with --force-apply-bundle after manual review (not recommended)."
    return 1
}

extract_uri_host() {
    # Strip scheme, port, and path: "https://cm.example:8089/path" -> "cm.example"
    local raw="${1:-}"
    raw="${raw#http://}"
    raw="${raw#https://}"
    raw="${raw%%/*}"
    raw="${raw%%:*}"
    printf '%s' "${raw}"
}

deploy_ta_for_indexers() {
    [[ -n "${DEPLOY_TA_CM_URI}" ]] || return 0
    log ""
    log "--- Deploy Splunk_TA_ForIndexers ---"
    local cm_profile
    cm_profile="$(resolve_cluster_manager_credential_profile 2>/dev/null || true)"
    if [[ -z "${cm_profile}" ]]; then
        log "  INFO: SPLUNK_CLUSTER_MANAGER_PROFILE is not configured in the credentials file."
        log "        Emitting handoff instructions for manual deployment:"
        log "          1. scp <generated>.spl <cm-host>:\$SPLUNK_HOME/etc/manager-apps/"
        log "          2. ssh <cm-host> 'cd \$SPLUNK_HOME/etc/manager-apps && tar -xzf <package> && rm <package>'"
        log "          3. ssh <cm-host> '\$SPLUNK_HOME/bin/splunk apply cluster-bundle --answer-yes'"
        return 0
    fi
    # Reject silent target mismatch: CM_URI host must match the profile's host.
    # Otherwise the operator thinks they are targeting CM_URI while the SSH
    # profile actually runs the command on a different cluster manager.
    local profile_host cm_uri_host
    profile_host="$(deployment_run_with_profile "${cm_profile}" printf '%s' "${SPLUNK_SSH_HOST:-${SPLUNK_HOST:-}}" 2>/dev/null || printf '')"
    cm_uri_host="$(extract_uri_host "${DEPLOY_TA_CM_URI}")"
    if [[ -n "${profile_host}" && -n "${cm_uri_host}" && "${profile_host}" != "${cm_uri_host}" ]]; then
        log "  ERROR: --deploy-ta-for-indexers CM_URI host '${cm_uri_host}' does not match"
        log "         SPLUNK_CLUSTER_MANAGER_PROFILE host '${profile_host}'."
        log "         Fix the CM_URI argument or update the cluster-manager profile to match."
        return 1
    fi
    log "  INFO: cluster-manager profile '${cm_profile}' detected (host: ${profile_host:-unknown})."
    log "        Stage the Splunk_TA_ForIndexers package under"
    log "        \$SPLUNK_HOME/etc/manager-apps/Splunk_TA_ForIndexers BEFORE this step."
    log "        (Use --generate-ta-for-indexers DIR to extract the package.)"
    if ! validate_cluster_bundle_on_cm; then
        return 1
    fi
    log "  Running 'splunk apply cluster-bundle' via cluster-manager profile '${cm_profile}'"
    if deployment_bundle_apply_on_profile "${cm_profile}" "idxc" "${DEPLOY_TA_CM_URI}" "" ""; then
        log "  PASS: cluster-bundle applied"
    else
        log "  FAIL: apply-bundle failed. See the output above for details."
        return 1
    fi
}

backup_kvstore() {
    [[ "${BACKUP_KVSTORE}" == "true" ]] || return 0
    log ""
    log "--- KV Store Backup ---"
    local profile
    profile="$(resolve_deployer_credential_profile 2>/dev/null || true)"
    if [[ -z "${profile}" ]]; then
        log "  INFO: SPLUNK_DEPLOYER_PROFILE is not configured; emitting handoff."
        log "        Run on the target host manually:"
        log "          \$SPLUNK_HOME/bin/splunk backup kvstore --archive-name es_kvstore_\$(date +%Y%m%d_%H%M%S)"
        return 0
    fi
    local archive_name
    archive_name="es_kvstore_$(date +%Y%m%d_%H%M%S)"
    log "  Running 'splunk backup kvstore --archive-name ${archive_name}' via profile '${profile}'"
    local execution_mode splunk_home script
    execution_mode="$(deployment_run_with_profile "${profile}" deployment_execution_mode_for_profile "")"
    splunk_home="$(deployment_run_with_profile "${profile}" printf '%s' "${SPLUNK_HOME:-/opt/splunk}")"
    script="$(cat <<EOF
set -euo pipefail
"${splunk_home}/bin/splunk" backup kvstore --archive-name $(printf '%q' "${archive_name}")
EOF
)"
    if deployment_run_with_profile "${profile}" \
        hbs_run_target_cmd_with_stdin "${execution_mode}" \
        "$(deployment_run_with_profile "${profile}" hbs_prefix_with_sudo "${execution_mode}" 'bash -s --')" \
        "${script}"; then
        log "  PASS: KV Store backup archive '${archive_name}' requested"
    else
        log "  FAIL: KV Store backup failed. See output above."
        return 1
    fi
}

run_uninstall() {
    [[ "${UNINSTALL}" == "true" ]] || return 0
    log ""
    log "--- ES Uninstall ---"
    ensure_session
    local framework_apps=(
        "DA-ESS-AccessProtection"
        "DA-ESS-EndpointProtection"
        "DA-ESS-IdentityManagement"
        "DA-ESS-NetworkProtection"
        "DA-ESS-ThreatIntelligence"
        "DA-ESS-UEBA"
        "SA-AccessProtection"
        "SA-AuditAndDataProtection"
        "SA-ContentVersioning"
        "SA-Detections"
        "SA-EndpointProtection"
        "SA-EntitlementManagement"
        "SA-IdentityManagement"
        "SA-NetworkProtection"
        "SA-TestModeControl"
        "SA-ThreatIntelligence"
        "SA-UEBA"
        "SA-Utils"
        "dlx-app"
        "exposure-analytics"
        "ocsf_cim_addon_for_splunk"
        "splunk_cloud_connect"
    )
    log "  Disabling removable framework apps before uninstall..."
    for app in "${framework_apps[@]}"; do
        if rest_check_app "${SK}" "${SPLUNK_URI}" "${app}" 2>/dev/null; then
            if splunk_curl_post "${SK}" "" \
                "${SPLUNK_URI}/services/apps/local/${app}/disable" >/dev/null 2>&1; then
                log "    disabled ${app}"
            else
                log "    WARN: could not disable ${app}"
            fi
        fi
    done
    log "  Keeping missioncontrol installed; Splunk ES 8.x documents it as part of Enterprise Security."
    log "  Uninstalling ${APP_NAME} and removable support apps..."
    local apps_to_remove=("${APP_NAME}" "${framework_apps[@]}")
    local remover="${APP_INSTALL_SCRIPT}"
    local uninstall_log
    for app in "${apps_to_remove[@]}"; do
        if rest_check_app "${SK}" "${SPLUNK_URI}" "${app}" 2>/dev/null; then
            uninstall_log="$(mktemp)"
            if bash "${remover}" --uninstall --app-name "${app}" --no-restart \
                >"${uninstall_log}" 2>&1; then
                log "    removed ${app}"
            else
                log "    WARN: uninstall request failed for ${app}; remove it manually from \$SPLUNK_HOME/etc/apps"
                # Surface installer diagnostics so the operator can see why.
                while IFS= read -r line; do
                    log "      ${app}: ${line}"
                done <"${uninstall_log}"
            fi
            rm -f "${uninstall_log}"
        fi
    done
    log "  Uninstall complete. Restart Splunk to finalize."
    log "  Re-run with --uninstall --no-validate to skip the post-uninstall validation pass."
}

find_local_es_package() {
    local package_dir

    if [[ -n "${LOCAL_FILE}" ]]; then
        printf '%s' "${LOCAL_FILE}"
        return 0
    fi

    package_dir="${SCRIPT_DIR}/../../../splunk-ta"
    [[ -d "${package_dir}" ]] || return 0

    find "${package_dir}" -maxdepth 1 -type f \
        \( -name 'splunk-enterprise-security_*.spl' -o -name 'splunk-enterprise-security_*.tgz' -o -name 'splunk-enterprise-security_*.tar.gz' \) \
        | sort -V | tail -1
}

install_from_splunkbase() {
    local args=("--source" "splunkbase" "--app-id" "${APP_ID}" "--update")
    if [[ -n "${APP_VERSION}" ]]; then
        args+=("--app-version" "${APP_VERSION}")
    fi
    if [[ "${NO_RESTART}" == "true" ]]; then
        args+=("--no-restart")
    fi
    bash "${APP_INSTALL_SCRIPT}" "${args[@]}"
}

install_from_local() {
    local package_file args
    package_file="$(find_local_es_package)"
    if [[ -z "${package_file}" || ! -f "${package_file}" ]]; then
        log "ERROR: Local ES package not found. Expected splunk-ta/splunk-enterprise-security_*.spl or pass --file."
        exit 1
    fi
    log "Installing local ES package: ${package_file}"
    args=("--source" "local" "--file" "${package_file}" "--update")
    if [[ "${NO_RESTART}" == "true" ]]; then
        args+=("--no-restart")
    fi
    bash "${APP_INSTALL_SCRIPT}" "${args[@]}"
}

install_es_package() {
    if is_splunk_cloud && [[ "${ALLOW_CLOUD}" != "true" ]]; then
        log "ERROR: This target appears to be Splunk Cloud."
        log "       ES Cloud installation is normally coordinated with Splunk Support."
        log "       Re-run with --allow-cloud only when you have an explicitly supported ACS process."
        exit 1
    fi

    case "${SOURCE}" in
        auto)
            if [[ -n "${APP_VERSION}" ]]; then
                log "Pinned app version requested; installing ${APP_NAME} from Splunkbase app ${APP_ID}..."
                install_from_splunkbase
                return 0
            fi
            if [[ -n "$(find_local_es_package)" ]]; then
                log "Local ES package detected in splunk-ta/; using local package."
                install_from_local
            else
                log "No local ES package found; installing ${APP_NAME} from Splunkbase app ${APP_ID}..."
                install_from_splunkbase
            fi
            ;;
        splunkbase)
            log "Installing ${APP_NAME} from Splunkbase app ${APP_ID}..."
            if install_from_splunkbase; then
                return 0
            fi
            log "Splunkbase install failed; falling back to local ES package in splunk-ta/."
            install_from_local
            ;;
        local)
            install_from_local
            ;;
    esac
}

essinstall_search() {
    local search="| essinstall --deployment_type ${DEPLOYMENT_TYPE} --ssl_enablement ${SSL_ENABLEMENT}"
    if [[ "${POST_INSTALL_DRY_RUN}" == "true" ]]; then
        search="${search} --dry-run"
    fi
    printf '%s' "${search}"
}

essinstall_detect_errors() {
    # Splunk's search/jobs/export endpoint returns HTTP 200 even when the SPL
    # command itself emits FATAL/ERROR messages (job-level errors are surfaced
    # in the streamed JSON, not the HTTP status). Inspect the NDJSON stream
    # for error markers and print a compact summary on stdout. Empty stdout
    # means no error markers were found.
    local body="$1"
    [[ -n "${body}" ]] || return 0
    printf '%s\n' "${body}" | python3 -c '
import json, sys
errors = []
seen = set()
for raw in sys.stdin:
    line = raw.strip()
    if not line:
        continue
    try:
        event = json.loads(line)
    except (TypeError, ValueError):
        continue
    if not isinstance(event, dict):
        continue
    messages = event.get("messages") or []
    if isinstance(messages, dict):
        messages = [messages]
    if not isinstance(messages, list):
        continue
    for message in messages:
        if not isinstance(message, dict):
            continue
        kind = str(message.get("type") or "").upper()
        text = str(message.get("text") or "").strip()
        if kind in {"FATAL", "ERROR"}:
            key = (kind, text)
            if key in seen:
                continue
            seen.add(key)
            errors.append(f"{kind}: {text}" if text else kind)
for line in errors:
    print(line)
' 2>/dev/null
}

run_essinstall() {
    local search body response code output errors

    ensure_session
    search="$(essinstall_search)"
    log "Running ES post-install search: ${search}"

    body="$(form_urlencode_pairs search "${search}" output_mode "json")" || exit 1
    response="$(splunk_curl_post "${SK}" "${body}" \
        "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/search/jobs/export" \
        -w '\n%{http_code}' 2>/dev/null || echo "000")"
    code="$(printf '%s\n' "${response}" | tail -1)"
    output="$(printf '%s\n' "${response}" | sed '$d')"

    case "${code}" in
        200|201)
            if [[ -n "${output}" ]]; then
                log "essinstall returned output:"
                sanitize_response "${output}" 25 >&2
            fi
            errors="$(essinstall_detect_errors "${output}")"
            if [[ -n "${errors}" ]]; then
                log "ERROR: essinstall reported runtime error(s) in stream output (HTTP 200):"
                while IFS= read -r line; do
                    [[ -n "${line}" ]] && log "  ${line}"
                done <<<"${errors}"
                exit 1
            fi
            ;;
        *)
            log "ERROR: essinstall failed (HTTP ${code})."
            if [[ -n "${output}" ]]; then
                sanitize_response "${output}" 25 >&2
            fi
            exit 1
            ;;
    esac
}

log "=== Splunk Enterprise Security Install ==="
log ""

# Decide whether a Splunk REST session is needed. The generate-only path is
# fully offline (reads a local ES package) so it does not require credentials.
NEEDS_SPLUNK_SESSION=false
if [[ "${PREFLIGHT_ONLY}" == "true" \
    || "${DO_INSTALL}" == "true" \
    || "${DO_POST_INSTALL}" == "true" \
    || "${DO_VALIDATE}" == "true" \
    || "${APPLY_BUNDLE}" == "true" \
    || "${UNINSTALL}" == "true" ]]; then
    NEEDS_SPLUNK_SESSION=true
fi

if [[ "${NEEDS_SPLUNK_SESSION}" == "true" ]]; then
    ensure_session
    log "Connected to Splunk ${SPLUNK_URI} (version: $(server_version))"
fi

if [[ "${PREFLIGHT_ONLY}" == "true" ]]; then
    if ! run_preflight; then
        exit 1
    fi
    log ""
    log "Preflight complete (PREFLIGHT_ONLY). Skipping install, post-install, and validation."
    exit 0
fi

# KV Store backup must run BEFORE any install/upgrade so a failed install does
# not leave the operator without a pre-change archive. ES 8.x upgrades are
# one-way; an interrupted install can corrupt KV collections.
if [[ "${BACKUP_KVSTORE}" == "true" ]]; then
    if [[ "${DO_INSTALL}" == "true" ]]; then
        log "  INFO: Backing up KV Store before install/upgrade."
    fi
    backup_kvstore
fi

if [[ "${DO_INSTALL}" == "true" ]]; then
    if [[ "${SKIP_PREFLIGHT}" == "true" ]]; then
        log "WARN: --skip-preflight was set; skipping ES install preflight checks."
    elif ! run_preflight; then
        exit 1
    fi
    install_es_package
    # The generic installer can restart Splunk, which invalidates prior sessions.
    SK=""
fi

if [[ "${DO_POST_INSTALL}" == "true" ]]; then
    run_essinstall
fi

if [[ -n "${GENERATE_TA_DIR}" ]]; then
    run_generate_ta_for_indexers
fi

if [[ "${APPLY_BUNDLE}" == "true" ]]; then
    apply_shc_bundle
fi

if [[ -n "${DEPLOY_TA_CM_URI}" ]]; then
    deploy_ta_for_indexers
fi

if [[ "${UNINSTALL}" == "true" ]]; then
    run_uninstall
fi

if [[ "${DO_VALIDATE}" == "true" && "${UNINSTALL}" != "true" ]]; then
    bash "${VALIDATE_SCRIPT}"
fi

log ""
log "Splunk Enterprise Security install workflow complete."
