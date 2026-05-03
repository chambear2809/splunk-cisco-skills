#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

APP_ID="7180"
APP_NAME="SplunkAssetRiskIntelligence"
LATEST_RESEARCHED_VERSION="1.2.1"
INSTALL_APP_SCRIPT="${PROJECT_ROOT}/skills/splunk-app-install/scripts/install_app.sh"
VALIDATE_SCRIPT="${SCRIPT_DIR}/validate.sh"
ARI_INDEXES=("ari_staging" "ari_asset" "ari_internal" "ari_ta")
ARI_ROLES=("ari_admin" "ari_analyst")
ARI_CAPABILITIES=(
    "ari_manage_data_source_settings"
    "ari_manage_metric_settings"
    "ari_manage_report_exceptions"
    "ari_dashboard_add_alerts"
    "ari_edit_table_fields"
    "ari_save_filters"
    "ari_manage_filters"
    "ari_manage_homepage_settings"
)

SOURCE="splunkbase"
APP_VERSION=""
LOCAL_FILE=""
NO_RESTART=false
INSTALL=false
VALIDATE=false
MODE_SET=false
DRY_RUN=false
JSON_OUTPUT=false
CREATE_INDEXES=true
PREFLIGHT_ONLY=false
FULL_HANDOFF=false
POST_INSTALL_HANDOFF=false
ADMIN_HANDOFF=false
RISK_HANDOFF=false
RESPONSE_AUDIT_HANDOFF=false
INVESTIGATION_HANDOFF=false
ES_INTEGRATION_HANDOFF=false
EXPOSURE_HANDOFF=false
ADDON_HANDOFF=false
ECHO_HANDOFF=false
UPGRADE_HANDOFF=false
UNINSTALL_HANDOFF=false
PLANNING_REQUESTED=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Asset and Risk Intelligence Setup

Usage: $(basename "$0") [OPTIONS]

Modes:
  --install                     Install/configure only
  --validate                    Validate only
  --dry-run                     Show the plan without changing Splunk
  --json                        Emit JSON with --dry-run

Options:
  --source splunkbase|local
  --app-version VER             Pin a Splunkbase app version
  --file PATH                   Local ARI package path or Splunkbase fallback package path
  --skip-indexes                Do not create ARI indexes during setup
  --preflight-only              Print requirements and compatibility handoff only
  --full-handoff                Include every documented ARI handoff category
  --post-install-handoff        Include ARI post-install initialization handoff
  --admin-handoff               Include ARI admin/data-source handoff
  --risk-handoff                Include ARI risk/compliance handoff
  --response-audit-handoff      Include ARI response/audit/health handoff
  --investigation-handoff       Include ARI investigation workflow handoff
  --es-integration-handoff      Include normal ARI-to-ES integration handoff
  --exposure-analytics-handoff  Include ES Exposure Analytics handoff in output
  --addon-handoff               Include ARI Technical Add-on deployment handoff
  --echo-handoff                Include ARI Echo secondary-search-head handoff
  --upgrade-handoff             Include ARI upgrade lifecycle handoff
  --uninstall-handoff           Include ARI uninstall prerequisite handoff
  --no-restart                  Skip installer restart handling
  --help                        Show this help

Default with no mode is install/configure followed by validate.
EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) INSTALL=true; MODE_SET=true; shift ;;
        --validate) VALIDATE=true; MODE_SET=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --source) require_arg "$1" $# || exit 1; SOURCE="$2"; shift 2 ;;
        --app-version) require_arg "$1" $# || exit 1; APP_VERSION="$2"; shift 2 ;;
        --file) require_arg "$1" $# || exit 1; LOCAL_FILE="$2"; shift 2 ;;
        --skip-indexes) CREATE_INDEXES=false; shift ;;
        --preflight-only) PREFLIGHT_ONLY=true; PLANNING_REQUESTED=true; shift ;;
        --full-handoff) FULL_HANDOFF=true; PLANNING_REQUESTED=true; shift ;;
        --post-install-handoff) POST_INSTALL_HANDOFF=true; PLANNING_REQUESTED=true; shift ;;
        --admin-handoff) ADMIN_HANDOFF=true; PLANNING_REQUESTED=true; shift ;;
        --risk-handoff) RISK_HANDOFF=true; PLANNING_REQUESTED=true; shift ;;
        --response-audit-handoff) RESPONSE_AUDIT_HANDOFF=true; PLANNING_REQUESTED=true; shift ;;
        --investigation-handoff) INVESTIGATION_HANDOFF=true; PLANNING_REQUESTED=true; shift ;;
        --es-integration-handoff) ES_INTEGRATION_HANDOFF=true; PLANNING_REQUESTED=true; shift ;;
        --exposure-analytics-handoff) EXPOSURE_HANDOFF=true; PLANNING_REQUESTED=true; shift ;;
        --addon-handoff) ADDON_HANDOFF=true; PLANNING_REQUESTED=true; shift ;;
        --echo-handoff) ECHO_HANDOFF=true; PLANNING_REQUESTED=true; shift ;;
        --upgrade-handoff) UPGRADE_HANDOFF=true; PLANNING_REQUESTED=true; shift ;;
        --uninstall-handoff) UNINSTALL_HANDOFF=true; PLANNING_REQUESTED=true; shift ;;
        --no-restart) NO_RESTART=true; shift ;;
        --help|-h) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ "${FULL_HANDOFF}" == "true" ]]; then
    PREFLIGHT_ONLY=true
    POST_INSTALL_HANDOFF=true
    ADMIN_HANDOFF=true
    RISK_HANDOFF=true
    RESPONSE_AUDIT_HANDOFF=true
    INVESTIGATION_HANDOFF=true
    ES_INTEGRATION_HANDOFF=true
    EXPOSURE_HANDOFF=true
    ADDON_HANDOFF=true
    ECHO_HANDOFF=true
    UPGRADE_HANDOFF=true
    UNINSTALL_HANDOFF=true
fi

if [[ "${MODE_SET}" != "true" && "${PLANNING_REQUESTED}" != "true" ]]; then
    INSTALL=true
    VALIDATE=true
fi

case "${SOURCE}" in
    splunkbase|local) ;;
    *) echo "ERROR: --source must be splunkbase or local." >&2; exit 1 ;;
esac

INSTALL_CMD=()
FALLBACK_CMD=()
VALIDATE_CMD=(bash "${VALIDATE_SCRIPT}")

build_install_command() {
    INSTALL_CMD=()
    [[ "${INSTALL}" == "true" ]] || return 0
    INSTALL_CMD=(bash "${INSTALL_APP_SCRIPT}" --source "${SOURCE}")
    if [[ "${SOURCE}" == "splunkbase" ]]; then
        INSTALL_CMD+=(--app-id "${APP_ID}" --no-update)
        [[ -n "${APP_VERSION}" ]] && INSTALL_CMD+=(--app-version "${APP_VERSION}")
    else
        [[ -n "${LOCAL_FILE}" ]] || { echo "ERROR: --file is required with --source local." >&2; exit 1; }
        INSTALL_CMD+=(--file "${LOCAL_FILE}" --no-update)
    fi
    [[ "${NO_RESTART}" == "true" ]] && INSTALL_CMD+=(--no-restart)
    return 0
}

build_fallback_command() {
    FALLBACK_CMD=()
    [[ "${INSTALL}" == "true" ]] || return 0
    if [[ "${SOURCE}" == "splunkbase" && -n "${LOCAL_FILE}" ]]; then
        FALLBACK_CMD=(bash "${INSTALL_APP_SCRIPT}" --source local --file "${LOCAL_FILE}" --no-update)
        [[ "${NO_RESTART}" == "true" ]] && FALLBACK_CMD+=(--no-restart)
    fi
    return 0
}

join_unit() {
    local IFS=$'\037'
    printf '%s' "$*"
}

append_handoff_phases() {
    [[ "${PREFLIGHT_ONLY}" == "true" ]] && phases+=("preflight")
    [[ "${POST_INSTALL_HANDOFF}" == "true" ]] && phases+=("post-install-handoff")
    [[ "${ADMIN_HANDOFF}" == "true" ]] && phases+=("admin-handoff")
    [[ "${RISK_HANDOFF}" == "true" ]] && phases+=("risk-handoff")
    [[ "${RESPONSE_AUDIT_HANDOFF}" == "true" ]] && phases+=("response-audit-handoff")
    [[ "${INVESTIGATION_HANDOFF}" == "true" ]] && phases+=("investigation-handoff")
    [[ "${ES_INTEGRATION_HANDOFF}" == "true" ]] && phases+=("es-integration-handoff")
    [[ "${EXPOSURE_HANDOFF}" == "true" ]] && phases+=("exposure-analytics-handoff")
    [[ "${ADDON_HANDOFF}" == "true" ]] && phases+=("addon-handoff")
    [[ "${ECHO_HANDOFF}" == "true" ]] && phases+=("echo-handoff")
    [[ "${UPGRADE_HANDOFF}" == "true" ]] && phases+=("upgrade-handoff")
    [[ "${UNINSTALL_HANDOFF}" == "true" ]] && phases+=("uninstall-handoff")
    return 0
}

emit_json_plan() {
    local install_join=""
    local fallback_join=""
    local validate_join=""
    if ((${#INSTALL_CMD[@]} > 0)); then
        install_join="$(join_unit "${INSTALL_CMD[@]}")"
    fi
    if ((${#FALLBACK_CMD[@]} > 0)); then
        fallback_join="$(join_unit "${FALLBACK_CMD[@]}")"
    fi
    if [[ "${VALIDATE}" == "true" ]]; then
        validate_join="$(join_unit "${VALIDATE_CMD[@]}")"
    fi

    JSON_PHASES="$(join_unit "${phases[@]}")" \
    JSON_INSTALL_COMMAND="${install_join}" \
    JSON_FALLBACK_COMMAND="${fallback_join}" \
    JSON_VALIDATE_COMMAND="${validate_join}" \
    APP_ID="${APP_ID}" \
    APP_NAME="${APP_NAME}" \
    LATEST_RESEARCHED_VERSION="${LATEST_RESEARCHED_VERSION}" \
    CREATE_INDEXES="${CREATE_INDEXES}" \
    PREFLIGHT_ONLY="${PREFLIGHT_ONLY}" \
    POST_INSTALL_HANDOFF="${POST_INSTALL_HANDOFF}" \
    ADMIN_HANDOFF="${ADMIN_HANDOFF}" \
    RISK_HANDOFF="${RISK_HANDOFF}" \
    RESPONSE_AUDIT_HANDOFF="${RESPONSE_AUDIT_HANDOFF}" \
    INVESTIGATION_HANDOFF="${INVESTIGATION_HANDOFF}" \
    ES_INTEGRATION_HANDOFF="${ES_INTEGRATION_HANDOFF}" \
    EXPOSURE_HANDOFF="${EXPOSURE_HANDOFF}" \
    ADDON_HANDOFF="${ADDON_HANDOFF}" \
    ECHO_HANDOFF="${ECHO_HANDOFF}" \
    UPGRADE_HANDOFF="${UPGRADE_HANDOFF}" \
    UNINSTALL_HANDOFF="${UNINSTALL_HANDOFF}" \
    python3 - <<'PY'
import json
import os
import sys

sep = "\x1f"

def env_bool(name: str) -> bool:
    return os.environ.get(name) == "true"

def env_list(name: str) -> list[str]:
    value = os.environ.get(name, "")
    return value.split(sep) if value else []

sources = {
    "product": "https://www.splunk.com/en_us/products/asset-and-risk-intelligence.html",
    "splunkbase_app": "https://splunkbase.splunk.com/app/7180",
    "install": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/install-splunk-asset-and-risk-intelligence/install-and-set-up-splunk-asset-and-risk-intelligence",
    "requirements": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/introduction-and-system-requirements/system-requirements-and-performance-impact-for-splunk-asset-and-risk-intelligence",
    "compatibility": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/introduction-and-system-requirements/splunk-asset-and-risk-intelligence-product-compatibility-matrix",
    "indexes": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/install-splunk-asset-and-risk-intelligence/create-indexes-for-splunk-asset-and-risk-intelligence",
    "initialize_data": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/install-splunk-asset-and-risk-intelligence/initialize-data-for-splunk-asset-and-risk-intelligence",
    "roles_capabilities": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/install-splunk-asset-and-risk-intelligence/set-up-roles-and-capabilities-for-splunk-asset-and-risk-intelligence",
    "admin_onboarding": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/getting-started-with-administration/splunk-asset-and-risk-intelligence-onboarding-guide-for-admins",
    "data_sources": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/set-up-data-sources/add-or-modify-a-data-source-in-splunk-asset-and-risk-intelligence",
    "event_searches": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/set-up-data-sources/create-and-modify-event-searches-in-splunk-asset-and-risk-intelligence",
    "data_source_activation": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/set-up-data-sources/activate-data-sources-in-splunk-asset-and-risk-intelligence",
    "source_priorities": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/set-up-data-sources/assign-data-source-priorities-in-splunk-asset-and-risk-intelligence",
    "field_priorities": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/set-up-data-sources/assign-data-source-priorities-in-splunk-asset-and-risk-intelligence",
    "field_mappings": "https://help.splunk.com/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/manage-data-source-field-mappings/data-source-field-mapping-reference",
    "metrics": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/manage-metrics-and-risk/create-and-manage-metrics-in-splunk-asset-and-risk-intelligence",
    "metric_exceptions": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/investigate-assets-and-assess-risk-in-splunk-asset-and-risk-intelligence/1.2/assess-risk-using-metrics/assess-risk-using-metrics-in-splunk-asset-and-risk-intelligence",
    "risk_scoring": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/manage-metrics-and-risk/create-and-manage-risk-scoring-rules-in-splunk-asset-and-risk-intelligence",
    "responses": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/respond-to-discoveries/add-and-manage-responses-in-splunk-asset-and-risk-intelligence",
    "audit": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/audit-configurations-and-operational-logs/monitor-export-and-share-audit-data-in-splunk-asset-and-risk-intelligence",
    "investigation": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/investigate-assets-and-assess-risk/1.2/discover-and-investigate-assets/investigate-assets-and-identities-in-splunk-asset-and-risk-intelligence",
    "es_integration": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/investigate-assets-and-assess-risk/1.2/discover-and-investigate-assets/use-splunk-asset-and-risk-intelligence-data-with-splunk-enterprise-security",
    "exposure_analytics": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/configure-splunk-asset-and-risk-intelligence-with-splunk-enterprise-security-exposure-analytics/using-splunk-asset-and-risk-intelligence-after-upgrading-to-splunk-enterprise-security-8.5/configure-exposure-analytics-to-use-with-splunk-asset-and-risk-intelligence",
    "addon_install": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/splunk-add-on-for-asset-and-risk-intelligence/1.2/install-and-configure/install-the-splunk-add-on-for-asset-and-risk-intelligence",
    "addon_known_sources": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/splunk-add-on-for-asset-and-risk-intelligence/1.2/manage/known-data-sources-available-for-the-splunk-add-on-for-asset-and-risk-intelligence",
    "addon_collected_data": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/splunk-add-on-for-asset-and-risk-intelligence/1.2/manage/data-collected-by-the-splunk-add-on-for-asset-and-risk-intelligence",
    "addon_windows": "https://splunkbase.splunk.com/app/7214",
    "addon_linux": "https://splunkbase.splunk.com/app/7416",
    "addon_macos": "https://splunkbase.splunk.com/app/7417",
    "echo_intro": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/splunk-asset-and-risk-intelligence-echo/1.2/introduction/get-started-with-splunk-asset-and-risk-intelligence-echo",
    "echo_install": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/splunk-asset-and-risk-intelligence-echo/1.2/install-and-configure/install-splunk-asset-and-risk-intelligence-echo",
    "echo_sync": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/splunk-asset-and-risk-intelligence-echo/1.2/manage/manage-synchronization-between-splunk-asset-and-risk-intelligence-echo-and-the-primary-search-head",
    "upgrade": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/upgrade-splunk-asset-and-risk-intelligence/upgrade-splunk-asset-and-risk-intelligence",
    "uninstall": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/install-splunk-asset-and-risk-intelligence/uninstall-splunk-asset-and-risk-intelligence",
    "troubleshooting": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/troubleshooting/troubleshoot-splunk-asset-and-risk-intelligence",
    "api_reference": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/api-reference/splunk-rest-api-reference-for-splunk-asset-and-risk-intelligence",
    "release_notes": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/release-notes",
}

payload = {
    "ok": True,
    "dry_run": True,
    "product": "Splunk Asset and Risk Intelligence",
    "app_id": os.environ["APP_ID"],
    "app_name": os.environ["APP_NAME"],
    "latest_researched_version": os.environ["LATEST_RESEARCHED_VERSION"],
    "restricted_download": True,
    "phases": env_list("JSON_PHASES"),
    "install_command": env_list("JSON_INSTALL_COMMAND"),
    "fallback_install_command": env_list("JSON_FALLBACK_COMMAND"),
    "validate_command": env_list("JSON_VALIDATE_COMMAND"),
    "requirements": {
        "hardware_checklist": [
            "search head sizing and indexer sizing from official ARI requirements",
            "best-performance guidance: multiple indexers, sufficient IOPS, and capacity planning before production use",
        ],
        "kvstore_required": True,
        "deployment_paths": ["Splunk Cloud Platform", "Splunk Enterprise single search head", "Splunk Enterprise search head cluster"],
        "restart_required": True,
        "usage_data_notice": "ARI can collect product usage data; review the official share-data guidance before production rollout.",
        "restricted_entitlement": "Splunkbase app 7180 is restricted to approved downloaders; use --file for entitled local packages.",
    },
    "compatibility": {
        "splunkbase_latest": {"ari_version": "1.2.1", "splunk_platform": "9.0 through 10.3"},
        "docs_signal": {"ari_versions": "1.2.x / 1.1.3", "splunk_platform": "9.1.3+ including 10.x"},
        "validation_behavior": "Warn, do not hard-fail, when the platform is below 9.1.3 because official sources have different compatibility signals.",
    },
    "indexes": {
        "required": ["ari_staging", "ari_asset", "ari_internal", "ari_ta"],
        "create_requested": env_bool("CREATE_INDEXES"),
        "automated": True,
        "destructive_actions": False,
    },
    "required_indexes": ["ari_staging", "ari_asset", "ari_internal", "ari_ta"],
    "roles": {
        "included": ["ari_admin", "ari_analyst"],
        "validation": "Read-only role presence checks; user assignment stays with Splunk role administration.",
    },
    "capabilities": {
        "ari_admin_defaults": [
            "ari_manage_data_source_settings",
            "ari_manage_metric_settings",
            "ari_manage_report_exceptions",
            "ari_dashboard_add_alerts",
            "ari_edit_table_fields",
            "ari_save_filters",
            "ari_manage_filters",
            "ari_manage_homepage_settings",
        ],
        "validation": "Read-only capability visibility checks; no role edits are performed.",
    },
    "handoffs": {
        "preflight": {
            "selected": env_bool("PREFLIGHT_ONLY"),
            "surfaces": [
                "search head and indexer sizing",
                "KV Store",
                "platform compatibility",
                "Splunk Cloud, Enterprise, and SHC install path",
                "restart requirement",
                "usage-data notice",
                "restricted entitlement",
            ],
        },
        "post_install": {
            "selected": env_bool("POST_INSTALL_HANDOFF"),
            "surfaces": [
                "restart",
                "Post-install configuration",
                "internal lookups",
                "enrichment rules",
                "ari_admin and ari_analyst",
                "ARI capabilities",
            ],
        },
        "admin": {
            "selected": env_bool("ADMIN_HANDOFF"),
            "surfaces": [
                "company subnet directories",
                "user directories",
                "known data sources",
                "custom data sources",
                "event searches",
                "data source activation",
                "source priorities",
                "field priorities",
                "field mappings",
                "custom fields",
                "discovery searches",
                "saved filters",
                "asset types",
                "identity types",
                "entity zones",
                "ephemeral discovery",
                "vulnerability key mode",
                "transparent federated-search mode",
                "inventory retention",
                "data deletion danger-zone warning",
            ],
        },
        "risk_compliance": {
            "selected": env_bool("RISK_HANDOFF"),
            "surfaces": [
                "known metrics",
                "custom metrics",
                "metric logic",
                "metric split fields",
                "metric exceptions",
                "cybersecurity frameworks",
                "risk scoring filters",
                "risk scoring rules",
                "identity risk scoring",
                "risk processing settings",
            ],
        },
        "response_audit": {
            "selected": env_bool("RESPONSE_AUDIT_HANDOFF"),
            "surfaces": [
                "responses",
                "response actions",
                "alerts from metric defects",
                "audit reports",
                "operational logs",
                "data export",
                "license usage",
                "operational health",
            ],
        },
        "investigation": {
            "selected": env_bool("INVESTIGATION_HANDOFF"),
            "surfaces": [
                "asset investigation",
                "identity investigation",
                "IP investigation",
                "MAC investigation",
                "software investigation",
                "vulnerability investigation",
                "subnet investigation",
                "activity views",
                "anomaly reports",
                "attack surface explorer",
                "notes",
                "field reference",
            ],
        },
        "es_integration": {
            "selected": env_bool("ES_INTEGRATION_HANDOFF"),
            "surfaces": [
                "normal ARI-to-ES integration",
                "asset sync",
                "identity sync",
                "swim lanes",
                "workflow actions",
                "ari_lookup_host()",
                "ari_lookup_ip()",
                "ES field mapping",
                "ari_risk_score",
                "ES risk factors",
            ],
        },
        "exposure_analytics": {
            "selected": env_bool("EXPOSURE_HANDOFF"),
            "surfaces": [
                "Splunk Asset and Risk Intelligence - Asset",
                "Splunk Asset and Risk Intelligence - IP",
                "Splunk Asset and Risk Intelligence - Mac",
                "Splunk Asset and Risk Intelligence - User",
                "turn off ARI Enterprise Security integration after Exposure Analytics migration",
                "route implementation detail through splunk-enterprise-security-config",
            ],
        },
        "addon": {
            "selected": env_bool("ADDON_HANDOFF"),
            "surfaces": [
                "Windows technical add-on 7214",
                "Linux technical add-on 7416",
                "macOS technical add-on 7417",
                "indexer package placement without local inputs",
                "Universal Forwarder package placement with local inputs.conf",
                "ari_ta data validation",
                "known data sources: Asset, Software, Encryption",
            ],
        },
        "echo": {
            "selected": env_bool("ECHO_HANDOFF"),
            "surfaces": [
                "secondary search head install",
                "restricted Splunkbase access",
                "post-install initialization",
                "primary-to-secondary connection",
                "inventory sync",
                "asset association sync",
                "metric sync",
                "synchronization history",
            ],
        },
        "upgrade": {
            "selected": env_bool("UPGRADE_HANDOFF"),
            "surfaces": [
                "backup app and KV stores",
                "disable processing searches",
                "upgrade package",
                "rerun post-install configuration",
                "re-enable processing searches",
                "browser cache and bump guidance",
            ],
        },
        "uninstall": {
            "selected": env_bool("UNINSTALL_HANDOFF"),
            "surfaces": [
                "remove Enterprise Security integration first",
                "do not remove ARI indexes by default",
                "require explicit operator intent for data cleanup",
            ],
        },
    },
    "related_products": {
        "technical_addons": [
            {"platform": "Windows", "splunkbase_id": "7214", "latest_researched_version": "1.2.0", "deployment": "indexer supported; Universal Forwarder handoff with local inputs.conf"},
            {"platform": "Linux", "splunkbase_id": "7416", "latest_researched_version": "1.2.0", "deployment": "indexer supported; Universal Forwarder handoff with local inputs.conf"},
            {"platform": "macOS", "splunkbase_id": "7417", "latest_researched_version": "1.2.0", "deployment": "indexer supported; Universal Forwarder handoff with local inputs.conf"},
        ],
        "echo": {
            "documented": True,
            "restricted": True,
            "splunkbase_id": None,
            "automation": "Documented handoff only until package ID/name is locally verified.",
            "sync": ["inventory", "asset associations", "metrics"],
        },
    },
    "es_modes": {
        "normal_integration": {
            "selected": env_bool("ES_INTEGRATION_HANDOFF"),
            "items": ["asset and identity sync", "swim lanes", "workflow actions", "lookup macros", "field mapping", "risk factors"],
        },
        "exposure_analytics_8_5_plus": {
            "selected": env_bool("EXPOSURE_HANDOFF"),
            "entity_discovery_sources": [
                "Splunk Asset and Risk Intelligence - Asset",
                "Splunk Asset and Risk Intelligence - IP",
                "Splunk Asset and Risk Intelligence - Mac",
                "Splunk Asset and Risk Intelligence - User",
            ],
            "handoff_skill": "splunk-enterprise-security-config",
        },
    },
    "lifecycle": {
        "upgrade": ["backup app and KV stores", "disable processing searches", "upgrade", "rerun post-install configuration", "re-enable processing searches", "browser cache/bump guidance"],
        "uninstall": ["remove ES integration first", "no index removal by default", "no data cleanup without explicit operator intent"],
    },
    "sources": sources,
}

json.dump(payload, sys.stdout, indent=2, sort_keys=True)
sys.stdout.write("\n")
PY
}

emit_handoff_text() {
    local phases_text
    phases_text="$(join_unit "${phases[@]}")"
    JSON_PHASES="${phases_text}" python3 - <<'PY'
import os

sep = "\x1f"
phases = os.environ.get("JSON_PHASES", "").split(sep) if os.environ.get("JSON_PHASES") else []
print("Splunk Asset and Risk Intelligence handoff plan")
if phases:
    print("Selected phases:")
    for phase in phases:
        print(f"  - {phase}")
else:
    print("Selected phases: none")
print("")
print("Coverage:")
print("  - install app 7180 and create ari_staging, ari_asset, ari_internal, ari_ta when install mode is selected")
print("  - validate app presence/version, platform version, KV Store, indexes, roles, capabilities, saved searches, ari_ta data, ES hints, and related-product evidence")
print("  - keep UI/API configuration, role assignment, Echo connection credentials, and UF deployment details as operator handoffs")
print("  - avoid data cleanup, index removal, app removal, and ES integration changes unless an operator explicitly performs them outside this setup workflow")
PY
}

emit_plan() {
    local phases=()
    [[ "${INSTALL}" == "true" ]] && phases+=("install")
    [[ "${CREATE_INDEXES}" == "true" && "${INSTALL}" == "true" ]] && phases+=("create-indexes")
    [[ "${VALIDATE}" == "true" ]] && phases+=("validate")
    append_handoff_phases

    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        emit_json_plan
    else
        echo "Planned phases:"
        printf '  - %s\n' "${phases[@]}"
        if [[ "${INSTALL}" == "true" ]]; then
            printf 'Install command:\n  %q ' "${INSTALL_CMD[@]}"; echo
        fi
        if [[ "${VALIDATE}" == "true" ]]; then
            printf 'Validate command:\n  %q ' "${VALIDATE_CMD[@]}"; echo
        fi
        echo "ARI indexes: ${ARI_INDEXES[*]}"
        echo "ARI roles: ${ARI_ROLES[*]}"
        echo "ARI capabilities: ${ARI_CAPABILITIES[*]}"
        echo "Restricted download note: provide --file if Splunkbase access is unavailable."
        echo "Compatibility note: warn, do not hard-fail, when Splunk platform is below 9.1.3 because Splunkbase and ARI docs differ."
    fi
}

ensure_session() {
    if [[ -n "${SK:-}" ]]; then
        return 0
    fi
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK="$(get_session_key "${SPLUNK_URI}")" || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
}

create_indexes_if_needed() {
    local idx
    [[ "${CREATE_INDEXES}" == "true" ]] || return 0
    ensure_session
    for idx in "${ARI_INDEXES[@]}"; do
        if platform_check_index "${SK}" "${SPLUNK_URI}" "${idx}" 2>/dev/null; then
            log "Index '${idx}' already exists."
        else
            log "Creating ARI index '${idx}'."
            platform_create_index "${SK}" "${SPLUNK_URI}" "${idx}" "512000" "event"
        fi
    done
}

build_install_command
build_fallback_command

if [[ "${DRY_RUN}" == "true" ]]; then
    emit_plan
    exit 0
fi

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    echo "ERROR: --json is only supported with --dry-run." >&2
    exit 1
fi

warn_if_current_skill_role_unsupported

if [[ "${PLANNING_REQUESTED}" == "true" && "${INSTALL}" != "true" && "${VALIDATE}" != "true" ]]; then
    phases=()
    append_handoff_phases
    emit_handoff_text
    exit 0
fi

if [[ "${INSTALL}" == "true" ]]; then
    if ! "${INSTALL_CMD[@]}"; then
        if [[ -n "${FALLBACK_CMD[0]+set}" ]]; then
            echo "WARN: Splunkbase install failed; trying local fallback package." >&2
            "${FALLBACK_CMD[@]}"
        else
            exit 1
        fi
    fi
    create_indexes_if_needed
fi

if [[ "${EXPOSURE_HANDOFF}" == "true" ]]; then
    log "Exposure Analytics handoff: use splunk-enterprise-security-config to configure ARI Asset, IP, Mac, and User entity discovery sources."
fi

if [[ "${PLANNING_REQUESTED}" == "true" ]]; then
    phases=()
    append_handoff_phases
    emit_handoff_text
fi

if [[ "${VALIDATE}" == "true" ]]; then
    "${VALIDATE_CMD[@]}"
fi
