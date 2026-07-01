#!/usr/bin/env bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# shellcheck disable=SC1091
source "${PROJECT_ROOT}/skills/shared/lib/appdynamics_helpers.sh"
appd_reject_direct_secret_args "$@" || exit $?

usage() {
    cat <<'EOF'
Render or create a disabled AppDynamics health rule for Cluster Agent availability.

The rule targets Server Visibility machines whose names match a pattern, then
evaluates the Cluster Agent availability metric. This avoids enumerating every
Cluster Agent as a separate affected entity.

Required:
  --controller-url URL                  AppDynamics Controller URL, or APPD_CONTROLLER_URL

Authentication, choose one:
  --token-file FILE                     chmod-600 bearer token file, or APPD_OAUTH_TOKEN_FILE
  --account NAME                        AppDynamics account, or APPD_ACCOUNT_NAME
  --client-name NAME                    API client name, or APPD_API_CLIENT_NAME
  --client-secret-file FILE             chmod-600 API client secret file, or APPD_OAUTH_CLIENT_SECRET_FILE

Options:
  --server-alerting-application-id ID   Server health-rule scope ID. Default: auto
                                        or APPD_SERVER_ALERTING_APPLICATION_ID.
  --name NAME                           Default: Cluster Agent Availability
  --server-name-match TEXT              Default: cluster-agent
  --match-to MODE                       STARTS_WITH, ENDS_WITH, CONTAINS,
                                        EQUALS, or MATCH_REG_EX. Default: CONTAINS
  --metric-path PATH                    Default: Cluster Agent|Availability
  --duration-mins N                     Evaluation window. Default: 5
  --wait-mins N                         Wait time after violation. Default: 5
  --enabled                             Create the rule enabled. Default is disabled.
  --apply                               POST the health rule. Default renders JSON only.
  --json                                Emit machine-readable summary.
  --help                                Show this help.

Examples:
  bash skills/splunk-appdynamics-k8s-cluster-agent-setup/scripts/create_cluster_agent_availability_health_rule.sh \
    --controller-url https://example.saas.appdynamics.com \
    --account customer1 \
    --client-name cluster-agent-alerting \
    --client-secret-file /secure/appd_client_secret

  bash skills/splunk-appdynamics-k8s-cluster-agent-setup/scripts/create_cluster_agent_availability_health_rule.sh \
    --apply \
    --controller-url https://example.saas.appdynamics.com \
    --account customer1 \
    --client-name cluster-agent-alerting \
    --client-secret-file /secure/appd_client_secret
EOF
}

CONTROLLER_URL="${APPD_CONTROLLER_URL:-}"
ACCOUNT_NAME="${APPD_ACCOUNT_NAME:-}"
CLIENT_NAME="${APPD_API_CLIENT_NAME:-}"
CLIENT_SECRET_FILE="${APPD_OAUTH_CLIENT_SECRET_FILE:-}"
TOKEN_FILE="${APPD_OAUTH_TOKEN_FILE:-}"
SERVER_ALERTING_APPLICATION_ID="${APPD_SERVER_ALERTING_APPLICATION_ID:-auto}"
RULE_NAME="${APPD_CLUSTER_AGENT_HEALTH_RULE_NAME:-Cluster Agent Availability}"
SERVER_NAME_MATCH="${APPD_CLUSTER_AGENT_SERVER_NAME_MATCH:-cluster-agent}"
MATCH_TO="${APPD_CLUSTER_AGENT_SERVER_MATCH_TO:-CONTAINS}"
METRIC_PATH="${APPD_CLUSTER_AGENT_AVAILABILITY_METRIC_PATH:-Cluster Agent|Availability}"
DURATION_MINS=5
WAIT_MINS=5
ENABLED=false
APPLY=0
OUTPUT_JSON=0

require_arg() {
    local flag="$1"
    local remaining="$2"
    if [[ "${remaining}" -lt 2 ]]; then
        echo "FAIL: ${flag} requires a value." >&2
        exit 2
    fi
}

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --controller-url) require_arg "$1" "$#"; CONTROLLER_URL="$2"; shift 2 ;;
        --controller-url=*) CONTROLLER_URL="${1#*=}"; shift ;;
        --account) require_arg "$1" "$#"; ACCOUNT_NAME="$2"; shift 2 ;;
        --account=*) ACCOUNT_NAME="${1#*=}"; shift ;;
        --client-name) require_arg "$1" "$#"; CLIENT_NAME="$2"; shift 2 ;;
        --client-name=*) CLIENT_NAME="${1#*=}"; shift ;;
        --client-secret-file) require_arg "$1" "$#"; CLIENT_SECRET_FILE="$2"; shift 2 ;;
        --client-secret-file=*) CLIENT_SECRET_FILE="${1#*=}"; shift ;;
        --token-file) require_arg "$1" "$#"; TOKEN_FILE="$2"; shift 2 ;;
        --token-file=*) TOKEN_FILE="${1#*=}"; shift ;;
        --server-alerting-application-id) require_arg "$1" "$#"; SERVER_ALERTING_APPLICATION_ID="$2"; shift 2 ;;
        --server-alerting-application-id=*) SERVER_ALERTING_APPLICATION_ID="${1#*=}"; shift ;;
        --name) require_arg "$1" "$#"; RULE_NAME="$2"; shift 2 ;;
        --name=*) RULE_NAME="${1#*=}"; shift ;;
        --server-name-match) require_arg "$1" "$#"; SERVER_NAME_MATCH="$2"; shift 2 ;;
        --server-name-match=*) SERVER_NAME_MATCH="${1#*=}"; shift ;;
        --match-to) require_arg "$1" "$#"; MATCH_TO="$2"; shift 2 ;;
        --match-to=*) MATCH_TO="${1#*=}"; shift ;;
        --metric-path) require_arg "$1" "$#"; METRIC_PATH="$2"; shift 2 ;;
        --metric-path=*) METRIC_PATH="${1#*=}"; shift ;;
        --duration-mins) require_arg "$1" "$#"; DURATION_MINS="$2"; shift 2 ;;
        --duration-mins=*) DURATION_MINS="${1#*=}"; shift ;;
        --wait-mins) require_arg "$1" "$#"; WAIT_MINS="$2"; shift 2 ;;
        --wait-mins=*) WAIT_MINS="${1#*=}"; shift ;;
        --enabled) ENABLED=true; shift ;;
        --apply) APPLY=1; shift ;;
        --json) OUTPUT_JSON=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *)
            echo "FAIL: unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

is_positive_int() {
    [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

for item in DURATION_MINS WAIT_MINS; do
    value="${!item}"
    if ! is_positive_int "${value}"; then
        echo "FAIL: ${item} must be a positive integer; got '${value}'." >&2
        exit 2
    fi
done
if [[ "${SERVER_ALERTING_APPLICATION_ID}" != "auto" ]] && ! is_positive_int "${SERVER_ALERTING_APPLICATION_ID}"; then
    echo "FAIL: SERVER_ALERTING_APPLICATION_ID must be a positive integer or auto; got '${SERVER_ALERTING_APPLICATION_ID}'." >&2
    exit 2
fi

case "${MATCH_TO}" in
    STARTS_WITH|ENDS_WITH|CONTAINS|EQUALS|MATCH_REG_EX) ;;
    *)
        echo "FAIL: --match-to must be STARTS_WITH, ENDS_WITH, CONTAINS, EQUALS, or MATCH_REG_EX." >&2
        exit 2
        ;;
esac

if [[ -z "${CONTROLLER_URL}" ]]; then
    echo "FAIL: --controller-url or APPD_CONTROLLER_URL is required." >&2
    exit 2
fi
if [[ -z "${RULE_NAME}" || -z "${SERVER_NAME_MATCH}" || -z "${METRIC_PATH}" ]]; then
    echo "FAIL: rule name, server name match, and metric path must be non-empty." >&2
    exit 2
fi

if [[ "${APPLY}" == "1" ]]; then
    if [[ -n "${TOKEN_FILE}" && -n "${CLIENT_SECRET_FILE}" ]]; then
        echo "FAIL: provide either --token-file or --client-secret-file, not both." >&2
        exit 2
    elif [[ -n "${TOKEN_FILE}" ]]; then
        appd_assert_secret_file "${TOKEN_FILE}" "AppDynamics OAuth token file"
    elif [[ -n "${CLIENT_SECRET_FILE}" ]]; then
        if [[ -z "${ACCOUNT_NAME}" || -z "${CLIENT_NAME}" ]]; then
            echo "FAIL: --account and --client-name are required with --client-secret-file." >&2
            exit 2
        fi
        appd_assert_secret_file "${CLIENT_SECRET_FILE}" "AppDynamics OAuth client secret file"
    else
        echo "FAIL: live apply requires --token-file or --client-secret-file." >&2
        exit 2
    fi
fi

AUTH_CONFIG="$(mktemp)"
PAYLOAD_FILE="$(mktemp)"
RESPONSE_FILE="$(mktemp)"
TMP_FILES=("${AUTH_CONFIG}" "${PAYLOAD_FILE}" "${RESPONSE_FILE}")
# shellcheck disable=SC2329
cleanup() {
    rm -f "${TMP_FILES[@]}"
}
trap cleanup EXIT
chmod 600 "${AUTH_CONFIG}" "${PAYLOAD_FILE}" "${RESPONSE_FILE}"

if [[ "${APPLY}" == "1" ]]; then
    if [[ -n "${TOKEN_FILE}" ]]; then
        ACCESS_TOKEN="$(tr -d '\r\n' < "${TOKEN_FILE}")"
    else
        TOKEN_JSON="$(appd_controller_oauth_token "${CONTROLLER_URL}" "${ACCOUNT_NAME}" "${CLIENT_NAME}" "${CLIENT_SECRET_FILE}")"
        ACCESS_TOKEN="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("access_token", ""))' <<<"${TOKEN_JSON}")"
    fi
    if [[ -z "${ACCESS_TOKEN}" ]]; then
        echo "FAIL: AppDynamics OAuth token is empty." >&2
        exit 1
    fi
    printf 'header = "Authorization: Bearer %s"\n' "${ACCESS_TOKEN}" > "${AUTH_CONFIG}"
    unset ACCESS_TOKEN TOKEN_JSON
fi

url_path_segment() {
    python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"
}

discover_server_alerting_application_id() {
    local role_name="Server Monitoring Administrator"
    local encoded_role_name
    local role_file
    encoded_role_name="$(url_path_segment "${role_name}")"
    role_file="$(mktemp)"
    TMP_FILES+=("${role_file}")
    chmod 600 "${role_file}"

    if ! appd_curl -fsS -K "${AUTH_CONFIG}" \
        "$(appd_controller_api_url "${CONTROLLER_URL}" "/controller/api/rbac/v1/roles/name/${encoded_role_name}?include-permissions=true")" \
        > "${role_file}"; then
        echo "FAIL: could not auto-discover Server Visibility health-rule application id from RBAC role '${role_name}'." >&2
        echo "Pass --server-alerting-application-id ID if the API client cannot read RBAC roles." >&2
        exit 1
    fi

    python3 - "${role_file}" <<'PY'
import json
import sys

role = json.load(open(sys.argv[1], encoding="utf-8"))
for permission in role.get("permissions") or []:
    if permission.get("entityType") != "APPLICATION":
        continue
    if permission.get("action") not in {"CONFIG_SIM", "VIEW_SIM"}:
        continue
    entity_id = permission.get("entityId")
    if isinstance(entity_id, int) and entity_id > 0:
        print(entity_id)
        raise SystemExit(0)
raise SystemExit(1)
PY
}

if [[ "${SERVER_ALERTING_APPLICATION_ID}" == "auto" && "${APPLY}" == "1" ]]; then
    if ! SERVER_ALERTING_APPLICATION_ID="$(discover_server_alerting_application_id)"; then
        exit 1
    fi
fi

if [[ "${SERVER_ALERTING_APPLICATION_ID}" == "auto" ]]; then
    SERVER_ALERTING_APPLICATION_ID="<auto-discovered-at-apply>"
fi

CREATE_URL="$(appd_controller_api_url "${CONTROLLER_URL}" "/controller/alerting/rest/v1/applications/${SERVER_ALERTING_APPLICATION_ID}/health-rules")"

python3 - "${RULE_NAME}" "${ENABLED}" "${DURATION_MINS}" "${WAIT_MINS}" "${SERVER_NAME_MATCH}" "${MATCH_TO}" "${METRIC_PATH}" > "${PAYLOAD_FILE}" <<'PY'
import json
import sys

rule_name, enabled, duration, wait, server_match, match_to, metric_path = sys.argv[1:]
payload = {
    "name": rule_name,
    "enabled": enabled == "true",
    "useDataFromLastNMinutes": int(duration),
    "waitTimeAfterViolation": int(wait),
    "scheduleName": "Always",
    "affects": {
        "affectedEntityType": "SERVERS",
        "serverSelectionCriteria": {
            "selectServersBy": "AFFECTED_SERVERS",
            "affectedServers": {
                "severSelectionScope": "SERVERS_MATCHING_PATTERN",
                "patternMatcher": {
                    "matchTo": match_to,
                    "matchValue": server_match,
                    "shouldNot": False,
                },
            },
        },
    },
    "evalCriterias": {
        "criticalCriteria": {
            "conditionAggregationType": "ALL",
            "conditionExpression": None,
            "conditions": [
                {
                    "name": "Cluster Agent availability below 100 or no data",
                    "shortName": "A",
                    "evaluateToTrueOnNoData": True,
                    "evalDetail": {
                        "evalDetailType": "SINGLE_METRIC",
                        "metricAggregateFunction": "MINIMUM",
                        "metricPath": metric_path,
                        "metricEvalDetail": {
                            "metricEvalDetailType": "SPECIFIC_TYPE",
                            "compareCondition": "LESS_THAN_SPECIFIC_VALUE",
                            "compareValue": 100,
                        },
                    },
                    "triggerEnabled": False,
                    "minimumTriggers": 0,
                }
            ],
            "evalMatchingCriteria": None,
        },
        "warningCriteria": None,
    },
}
print(json.dumps(payload, indent=2, sort_keys=True))
PY

if [[ "${APPLY}" != "1" ]]; then
    if [[ "${OUTPUT_JSON}" == "1" ]]; then
        python3 - "${CREATE_URL}" "${PAYLOAD_FILE}" <<'PY'
import json
import sys

print(json.dumps({"apply": False, "url": sys.argv[1], "payload": json.load(open(sys.argv[2]))}, sort_keys=True))
PY
    else
        echo "DRY_RUN: would POST to ${CREATE_URL}"
        echo "DRY_RUN: health rule defaults to enabled=${ENABLED}"
        python3 -m json.tool "${PAYLOAD_FILE}"
    fi
    exit 0
fi

EXISTING_LIST_FILE="$(mktemp)"
TMP_FILES+=("${EXISTING_LIST_FILE}")
chmod 600 "${EXISTING_LIST_FILE}"
HTTP_CODE="$(appd_curl -sS -o "${EXISTING_LIST_FILE}" -w '%{http_code}' -K "${AUTH_CONFIG}" "${CREATE_URL}")"
if [[ "${HTTP_CODE}" != "200" ]]; then
    if [[ "${OUTPUT_JSON}" == "1" ]]; then
        python3 - "${HTTP_CODE}" "${CREATE_URL}" "${EXISTING_LIST_FILE}" <<'PY'
import json
import sys

http_code, url, path = sys.argv[1:]
text = open(path, errors="replace").read()
try:
    body = json.loads(text)
except Exception:
    body = {"raw": text}
print(json.dumps({"status": "FAIL", "http_code": int(http_code), "url": url, "response": body}, sort_keys=True))
PY
    else
        echo "FAIL: AppDynamics health rule list returned HTTP ${HTTP_CODE}."
        sed -n '1,240p' "${EXISTING_LIST_FILE}"
    fi
    exit 1
fi

EXISTING_RULE_ID="$(python3 - "${EXISTING_LIST_FILE}" "${RULE_NAME}" <<'PY'
import json
import sys

rules = json.load(open(sys.argv[1], encoding="utf-8"))
for rule in rules if isinstance(rules, list) else []:
    if rule.get("name") == sys.argv[2]:
        print(rule.get("id"))
        break
PY
)"

if [[ -n "${EXISTING_RULE_ID}" ]]; then
    EXISTING_DETAIL_FILE="$(mktemp)"
    TMP_FILES+=("${EXISTING_DETAIL_FILE}")
    chmod 600 "${EXISTING_DETAIL_FILE}"
    EXISTING_URL="$(appd_controller_api_url "${CONTROLLER_URL}" "/controller/alerting/rest/v1/applications/${SERVER_ALERTING_APPLICATION_ID}/health-rules/${EXISTING_RULE_ID}")"
    HTTP_CODE="$(appd_curl -sS -o "${EXISTING_DETAIL_FILE}" -w '%{http_code}' -K "${AUTH_CONFIG}" "${EXISTING_URL}")"
    if [[ "${HTTP_CODE}" != "200" ]]; then
        if [[ "${OUTPUT_JSON}" == "1" ]]; then
            python3 - "${HTTP_CODE}" "${EXISTING_URL}" "${EXISTING_DETAIL_FILE}" <<'PY'
import json
import sys

http_code, url, path = sys.argv[1:]
text = open(path, errors="replace").read()
try:
    body = json.loads(text)
except Exception:
    body = {"raw": text}
print(json.dumps({"status": "FAIL", "http_code": int(http_code), "url": url, "response": body}, sort_keys=True))
PY
        else
            echo "FAIL: AppDynamics existing health rule readback returned HTTP ${HTTP_CODE}."
            sed -n '1,240p' "${EXISTING_DETAIL_FILE}"
        fi
        exit 1
    fi

    python3 - "${SERVER_ALERTING_APPLICATION_ID}" "${EXISTING_DETAIL_FILE}" "${PAYLOAD_FILE}" "${OUTPUT_JSON}" <<'PY'
import json
import sys

app_id, path, desired_path, as_json = sys.argv[1:]
body = json.load(open(path, encoding="utf-8"))
desired = json.load(open(desired_path, encoding="utf-8"))
compared_fields = (
    "name", "enabled", "useDataFromLastNMinutes", "waitTimeAfterViolation",
    "scheduleName", "affects", "evalCriterias",
)
drift = {
    field: {"actual": body.get(field), "desired": desired.get(field)}
    for field in compared_fields
    if body.get(field) != desired.get(field)
}
summary = {
    "status": "DRIFT" if drift else "EXISTS_MATCHING",
    "server_alerting_application_id": int(app_id),
    "id": body.get("id"),
    "name": body.get("name"),
    "enabled": body.get("enabled"),
    "affects": body.get("affects"),
    "drift": drift,
}
if as_json == "1":
    print(json.dumps(summary, sort_keys=True))
elif drift:
    print(
        "FAIL: health rule exists but differs from the reviewed payload "
        f"id={summary['id']} fields={','.join(sorted(drift))}"
    )
else:
    print(
        "OK: matching health rule already exists "
        f"id={summary['id']} name={summary['name']} enabled={summary['enabled']} "
        f"server_alerting_application_id={summary['server_alerting_application_id']}"
    )
raise SystemExit(1 if drift else 0)
PY
    exit 0
fi

HTTP_CODE="$(appd_curl -sS -o "${RESPONSE_FILE}" -w '%{http_code}' \
    -K "${AUTH_CONFIG}" \
    -X POST "${CREATE_URL}" \
    -H "Content-Type: application/json" \
    --data-binary @"${PAYLOAD_FILE}")"

if [[ "${HTTP_CODE}" != "200" && "${HTTP_CODE}" != "201" ]]; then
    if [[ "${OUTPUT_JSON}" == "1" ]]; then
        python3 - "${HTTP_CODE}" "${CREATE_URL}" "${RESPONSE_FILE}" <<'PY'
import json
import sys

http_code, url, path = sys.argv[1:]
text = open(path, errors="replace").read()
try:
    body = json.loads(text)
except Exception:
    body = {"raw": text}
print(json.dumps({"status": "FAIL", "http_code": int(http_code), "url": url, "response": body}, sort_keys=True))
PY
    else
        echo "FAIL: AppDynamics health rule create returned HTTP ${HTTP_CODE}."
        sed -n '1,240p' "${RESPONSE_FILE}"
        if grep -q "Not enough permissions on Application Id" "${RESPONSE_FILE}"; then
            cat >&2 <<'EOF'

The API client can authenticate, but it lacks permission to create/read Server
health rules. Grant the client Alert & Respond health-rule permissions for the
Server/Infrastructure health-rule scope, then rerun with --apply.
EOF
        elif grep -q "affectType SERVERS not supported" "${RESPONSE_FILE}"; then
            cat >&2 <<'EOF'

The selected application id is an APM application, not the Server health-rule
scope. Use --server-alerting-application-id with the controller's server scope.
EOF
        fi
    fi
    exit 1
fi

python3 - "${HTTP_CODE}" "${SERVER_ALERTING_APPLICATION_ID}" "${RESPONSE_FILE}" "${RULE_NAME}" "${OUTPUT_JSON}" <<'PY'
import json
import sys

http_code, app_id, path, expected_name, as_json = sys.argv[1:]
body = json.load(open(path, encoding="utf-8"))
if not body.get("id") or body.get("name") != expected_name:
    raise SystemExit("FAIL: create returned 2xx but did not return the expected health-rule id/name")
summary = {
    "status": "OK",
    "http_code": int(http_code),
    "server_alerting_application_id": int(app_id),
    "id": body.get("id"),
    "name": body.get("name"),
    "enabled": body.get("enabled"),
    "affects": body.get("affects"),
}
if as_json == "1":
    print(json.dumps(summary, sort_keys=True))
else:
    print(
        "OK: created health rule "
        f"id={summary['id']} name={summary['name']} enabled={summary['enabled']} "
        f"server_alerting_application_id={summary['server_alerting_application_id']}"
    )
PY
