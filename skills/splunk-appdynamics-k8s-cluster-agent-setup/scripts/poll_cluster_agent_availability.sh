#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# shellcheck disable=SC1091
source "${PROJECT_ROOT}/skills/shared/lib/appdynamics_helpers.sh"
appd_reject_direct_secret_args "$@" || exit $?

usage() {
    cat <<'EOF'
Poll AppDynamics Controller API for Cluster Agent availability.

Required:
  --controller-url URL          AppDynamics Controller URL, or APPD_CONTROLLER_URL
  --application NAME_OR_ID      Business app name/ID, or Server & Infrastructure Monitoring.
                                Repeatable.

Authentication, choose one:
  --token-file FILE             chmod-600 bearer token file, or APPD_OAUTH_TOKEN_FILE
  --account NAME                AppDynamics account, or APPD_ACCOUNT_NAME
  --client-name NAME            API client name, or APPD_API_CLIENT_NAME
  --client-secret-file FILE     chmod-600 API client secret file, or APPD_OAUTH_CLIENT_SECRET_FILE

Discovery alternatives:
  --application-regex REGEX     Discover apps whose name matches REGEX
  --all-applications            Probe all applications returned by /controller/rest/applications

Options:
  --list-applications           List visible applications and exit
  --metric-path PATH            Default path:
                                Application Infrastructure Performance|Root|Individual Nodes|*|Cluster Agent|Availability
                                Override with a copied full metric path for one Cluster Agent.
  --duration-mins N             Metric window. Default: 5
  --interval-seconds N          Seconds between polls. Default: 0
  --iterations N                Poll count. Default: 1
  --threshold N                 Healthy point threshold. Default: 100
  --allowed-bad-points N        Max points below threshold before fail. Default: 2
  --no-data fail|warn|ignore    How to treat missing data. Default: fail
  --health-rule-name NAME       Also check recent health rule violations by name
  --violation-duration-mins N   Violation lookup window. Default: 30
  --json                        Emit JSON lines instead of readable text
  --help                        Show this help

Examples:
  APPD_CONTROLLER_URL=https://example.saas.appdynamics.com \
  APPD_ACCOUNT_NAME=customer1 \
  APPD_API_CLIENT_NAME=cluster-agent-readonly \
  APPD_OAUTH_CLIENT_SECRET_FILE=/secure/appd_client_secret \
    bash skills/splunk-appdynamics-k8s-cluster-agent-setup/scripts/poll_cluster_agent_availability.sh \
      --application 'Server & Infrastructure Monitoring' \
      --metric-path 'Application Infrastructure Performance|Root|Individual Nodes|cluster-agent-demo1-appdynamics|Cluster Agent|Availability' \
      --duration-mins 5

  bash skills/splunk-appdynamics-k8s-cluster-agent-setup/scripts/poll_cluster_agent_availability.sh \
    --controller-url https://example.saas.appdynamics.com \
    --token-file /secure/appd_token \
    --application 'Server & Infrastructure Monitoring' \
    --metric-path 'Application Infrastructure Performance|Root|Individual Nodes|cluster-agent-demo1-appdynamics|Cluster Agent|Availability' \
    --health-rule-name 'Cluster Agent Availability'
EOF
}

CONTROLLER_URL="${APPD_CONTROLLER_URL:-}"
ACCOUNT_NAME="${APPD_ACCOUNT_NAME:-}"
CLIENT_NAME="${APPD_API_CLIENT_NAME:-}"
CLIENT_SECRET_FILE="${APPD_OAUTH_CLIENT_SECRET_FILE:-}"
TOKEN_FILE="${APPD_OAUTH_TOKEN_FILE:-}"
METRIC_PATH="${APPD_CLUSTER_AGENT_AVAILABILITY_METRIC_PATH:-Application Infrastructure Performance|Root|Individual Nodes|*|Cluster Agent|Availability}"
DURATION_MINS=5
INTERVAL_SECONDS=0
ITERATIONS=1
THRESHOLD=100
ALLOWED_BAD_POINTS=2
NO_DATA_MODE="fail"
APPLICATION_REGEX="${APPD_APPLICATION_REGEX:-}"
ALL_APPLICATIONS=0
LIST_APPLICATIONS=0
HEALTH_RULE_NAME=""
VIOLATION_DURATION_MINS=30
OUTPUT_JSON=0
APPLICATIONS=()

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
        --application) require_arg "$1" "$#"; APPLICATIONS+=("$2"); shift 2 ;;
        --application=*) APPLICATIONS+=("${1#*=}"); shift ;;
        --application-regex) require_arg "$1" "$#"; APPLICATION_REGEX="$2"; shift 2 ;;
        --application-regex=*) APPLICATION_REGEX="${1#*=}"; shift ;;
        --all-applications) ALL_APPLICATIONS=1; shift ;;
        --list-applications) LIST_APPLICATIONS=1; shift ;;
        --metric-path) require_arg "$1" "$#"; METRIC_PATH="$2"; shift 2 ;;
        --metric-path=*) METRIC_PATH="${1#*=}"; shift ;;
        --duration-mins) require_arg "$1" "$#"; DURATION_MINS="$2"; shift 2 ;;
        --duration-mins=*) DURATION_MINS="${1#*=}"; shift ;;
        --interval-seconds) require_arg "$1" "$#"; INTERVAL_SECONDS="$2"; shift 2 ;;
        --interval-seconds=*) INTERVAL_SECONDS="${1#*=}"; shift ;;
        --iterations) require_arg "$1" "$#"; ITERATIONS="$2"; shift 2 ;;
        --iterations=*) ITERATIONS="${1#*=}"; shift ;;
        --threshold) require_arg "$1" "$#"; THRESHOLD="$2"; shift 2 ;;
        --threshold=*) THRESHOLD="${1#*=}"; shift ;;
        --allowed-bad-points) require_arg "$1" "$#"; ALLOWED_BAD_POINTS="$2"; shift 2 ;;
        --allowed-bad-points=*) ALLOWED_BAD_POINTS="${1#*=}"; shift ;;
        --no-data) require_arg "$1" "$#"; NO_DATA_MODE="$2"; shift 2 ;;
        --no-data=*) NO_DATA_MODE="${1#*=}"; shift ;;
        --health-rule-name) require_arg "$1" "$#"; HEALTH_RULE_NAME="$2"; shift 2 ;;
        --health-rule-name=*) HEALTH_RULE_NAME="${1#*=}"; shift ;;
        --violation-duration-mins) require_arg "$1" "$#"; VIOLATION_DURATION_MINS="$2"; shift 2 ;;
        --violation-duration-mins=*) VIOLATION_DURATION_MINS="${1#*=}"; shift ;;
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

is_nonnegative_int() {
    [[ "$1" =~ ^[0-9]+$ ]]
}

for item in DURATION_MINS ITERATIONS THRESHOLD ALLOWED_BAD_POINTS VIOLATION_DURATION_MINS; do
    value="${!item}"
    if ! is_nonnegative_int "${value}"; then
        echo "FAIL: ${item} must be a non-negative integer; got '${value}'." >&2
        exit 2
    fi
done
if ! is_positive_int "${DURATION_MINS}" || ! is_positive_int "${ITERATIONS}" || ! is_positive_int "${VIOLATION_DURATION_MINS}"; then
    echo "FAIL: duration, iterations, and violation duration must be positive integers." >&2
    exit 2
fi
if ! is_nonnegative_int "${INTERVAL_SECONDS}"; then
    echo "FAIL: INTERVAL_SECONDS must be a non-negative integer; got '${INTERVAL_SECONDS}'." >&2
    exit 2
fi
case "${NO_DATA_MODE}" in
    fail|warn|ignore) ;;
    *)
        echo "FAIL: --no-data must be one of: fail, warn, ignore." >&2
        exit 2
        ;;
esac

if [[ -z "${CONTROLLER_URL}" ]]; then
    echo "FAIL: --controller-url or APPD_CONTROLLER_URL is required." >&2
    exit 2
fi

if [[ -n "${TOKEN_FILE}" ]]; then
    appd_assert_secret_file "${TOKEN_FILE}" "AppDynamics OAuth token file"
elif [[ -n "${CLIENT_SECRET_FILE}" ]]; then
    if [[ -z "${ACCOUNT_NAME}" || -z "${CLIENT_NAME}" ]]; then
        echo "FAIL: --account and --client-name are required with --client-secret-file." >&2
        exit 2
    fi
    appd_assert_secret_file "${CLIENT_SECRET_FILE}" "AppDynamics OAuth client secret file"
else
    echo "FAIL: provide --token-file or --client-secret-file." >&2
    exit 2
fi

if [[ "${LIST_APPLICATIONS}" != "1" && "${#APPLICATIONS[@]}" -eq 0 && -z "${APPLICATION_REGEX}" && "${ALL_APPLICATIONS}" != "1" ]]; then
    echo "FAIL: provide --application, --application-regex, or --all-applications." >&2
    exit 2
fi

AUTH_CONFIG="$(mktemp)"
TMP_FILES=("${AUTH_CONFIG}")
# shellcheck disable=SC2329
cleanup() {
    rm -f "${TMP_FILES[@]}"
}
trap cleanup EXIT
chmod 600 "${AUTH_CONFIG}"

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

url_path_segment() {
    python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"
}

normalize_applications() {
    local app_list_file="$1"
    shift
    python3 - "$APPLICATION_REGEX" "$ALL_APPLICATIONS" "$app_list_file" "$@" <<'PY'
import json
import re
import sys

regex = sys.argv[1]
all_apps = sys.argv[2] == "1"
app_list_file = sys.argv[3]
explicit = sys.argv[4:]

for item in explicit:
    print(f"{item}\t{item}")

if not all_apps and not regex:
    raise SystemExit(0)

with open(app_list_file, encoding="utf-8") as handle:
    payload = json.load(handle)
if isinstance(payload, dict):
    apps = payload.get("applications") or payload.get("application") or payload.get("items") or []
else:
    apps = payload
if isinstance(apps, dict):
    apps = [apps]

pattern = re.compile(regex) if regex else None
seen = set(explicit)
for app in apps:
    if not isinstance(app, dict):
        continue
    app_id = str(app.get("id") or "")
    name = str(app.get("name") or app_id)
    if not name:
        continue
    if pattern and not pattern.search(name):
        continue
    key = app_id or name
    if key in seen or name in seen:
        continue
    seen.add(key)
    print(f"{key}\t{name}")
PY
}

summarize_metric_response() {
    local app_id="$1"
    local app_name="$2"
    local response_file="$3"
    python3 - "${app_id}" "${app_name}" "${response_file}" "${THRESHOLD}" "${ALLOWED_BAD_POINTS}" "${NO_DATA_MODE}" "${OUTPUT_JSON}" <<'PY'
import json
import sys

app_id, app_name, path = sys.argv[1], sys.argv[2], sys.argv[3]
threshold = float(sys.argv[4])
allowed_bad = int(sys.argv[5])
no_data_mode = sys.argv[6]
as_json = sys.argv[7] == "1"

payload = json.load(open(path, encoding="utf-8"))
if isinstance(payload, list):
    series = payload
elif isinstance(payload, dict):
    series = (
        payload.get("metric-data-v2")
        or payload.get("metric-data-v2s")
        or payload.get("metricData")
        or payload.get("metricDataV2")
        or payload.get("items")
        or []
    )
    if isinstance(series, dict):
        series = [series]
else:
    series = []

def point_value(point):
    for key in ("current", "value", "max", "min"):
        value = point.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None

results = []
if not series:
    status = "FAIL" if no_data_mode == "fail" else ("WARN" if no_data_mode == "warn" else "OK")
    results.append(
        {
            "application_id": app_id,
            "application_name": app_name,
            "metric_path": None,
            "status": status,
            "points": 0,
            "bad_points": 0,
            "latest": None,
            "message": "metric path returned no series",
        }
    )
else:
    for item in series:
        values = item.get("metricValues") or item.get("metric-values") or item.get("metricValue") or []
        if isinstance(values, dict):
            values = [values]
        usable = [point_value(point) for point in values if isinstance(point, dict)]
        usable = [value for value in usable if value is not None]
        bad = [value for value in usable if value < threshold]
        if not usable:
            status = "FAIL" if no_data_mode == "fail" else ("WARN" if no_data_mode == "warn" else "OK")
            message = "series has no datapoints"
        elif len(bad) > allowed_bad:
            status = "FAIL"
            message = f"{len(bad)} point(s) below threshold {threshold:g}"
        elif bad:
            status = "WARN"
            message = f"{len(bad)} point(s) below threshold {threshold:g}, within allowance"
        else:
            status = "OK"
            message = "all points healthy"
        results.append(
            {
                "application_id": app_id,
                "application_name": app_name,
                "metric_path": item.get("metricPath") or item.get("metric-path"),
                "metric_name": item.get("metricName") or item.get("metric-name"),
                "status": status,
                "points": len(usable),
                "bad_points": len(bad),
                "latest": usable[-1] if usable else None,
                "minimum": min(usable) if usable else None,
                "maximum": max(usable) if usable else None,
                "message": message,
            }
        )

exit_code = 0
if any(item["status"] == "FAIL" for item in results):
    exit_code = 1
elif any(item["status"] == "WARN" for item in results):
    exit_code = 3

if as_json:
    for item in results:
        print(json.dumps(item, sort_keys=True))
else:
    for item in results:
        metric = item.get("metric_path") or "<no metric>"
        latest = "none" if item.get("latest") is None else f"{item['latest']:g}"
        print(
            f"{item['status']}: app={app_name} metric={metric} "
            f"points={item['points']} bad={item['bad_points']} latest={latest} - {item['message']}"
        )

raise SystemExit(exit_code)
PY
}

summarize_violations() {
    local app_name="$1"
    local response_file="$2"
    python3 - "${app_name}" "${response_file}" "${HEALTH_RULE_NAME}" "${OUTPUT_JSON}" <<'PY'
import json
import sys

app_name, path, health_rule_name = sys.argv[1], sys.argv[2], sys.argv[3]
as_json = sys.argv[4] == "1"

payload = json.load(open(path, encoding="utf-8"))
if isinstance(payload, list):
    violations = payload
elif isinstance(payload, dict):
    violations = payload.get("policy-violation") or payload.get("policyViolations") or payload.get("items") or []
    if isinstance(violations, dict):
        violations = [violations]
else:
    violations = []

matches = []
for violation in violations:
    if not isinstance(violation, dict):
        continue
    name = str(violation.get("name") or "")
    triggered = violation.get("triggeredEntityDefinition") or {}
    triggered_name = str(triggered.get("name") or "")
    if health_rule_name and health_rule_name not in name and health_rule_name not in triggered_name:
        continue
    matches.append(violation)

status = "WARN" if matches else "OK"
if as_json:
    print(json.dumps({"application_name": app_name, "health_rule_name": health_rule_name, "status": status, "violation_count": len(matches)}, sort_keys=True))
else:
    print(f"{status}: app={app_name} health_rule={health_rule_name} recent_violations={len(matches)}")
PY
}

APP_LIST_FILE=""
if [[ -n "${APPLICATION_REGEX}" || "${ALL_APPLICATIONS}" == "1" || "${LIST_APPLICATIONS}" == "1" ]]; then
    APP_LIST_FILE="$(mktemp)"
    TMP_FILES+=("${APP_LIST_FILE}")
    appd_curl -fsS -K "${AUTH_CONFIG}" "$(appd_controller_api_url "${CONTROLLER_URL}" "/controller/rest/applications?output=JSON")" > "${APP_LIST_FILE}"
fi

if [[ "${LIST_APPLICATIONS}" == "1" ]]; then
    python3 - "${APP_LIST_FILE}" "${OUTPUT_JSON}" <<'PY'
import json
import sys

app_list_file, output_json = sys.argv[1], sys.argv[2] == "1"
payload = json.load(open(app_list_file, encoding="utf-8"))
if isinstance(payload, dict):
    apps = payload.get("applications") or payload.get("application") or payload.get("items") or []
else:
    apps = payload
if isinstance(apps, dict):
    apps = [apps]

for app in apps:
    if not isinstance(app, dict):
        continue
    item = {"id": app.get("id"), "name": app.get("name")}
    if output_json:
        print(json.dumps(item, sort_keys=True))
    else:
        print(f"{item['id']}\t{item['name']}")
PY
    exit 0
fi

APP_SPECS_FILE="$(mktemp)"
TMP_FILES+=("${APP_SPECS_FILE}")
if [[ -n "${APP_LIST_FILE}" ]]; then
    normalize_applications "${APP_LIST_FILE}" ${APPLICATIONS[@]+"${APPLICATIONS[@]}"} > "${APP_SPECS_FILE}"
else
    normalize_applications /dev/null ${APPLICATIONS[@]+"${APPLICATIONS[@]}"} > "${APP_SPECS_FILE}"
fi

if [[ ! -s "${APP_SPECS_FILE}" ]]; then
    echo "FAIL: no applications matched the requested selection." >&2
    exit 1
fi

overall_status=0
for ((iteration = 1; iteration <= ITERATIONS; iteration++)); do
    if [[ "${OUTPUT_JSON}" != "1" ]]; then
        printf 'Poll %d/%d: metric=%s window=%sm threshold=%s allowed_bad_points=%s\n' \
            "${iteration}" "${ITERATIONS}" "${METRIC_PATH}" "${DURATION_MINS}" "${THRESHOLD}" "${ALLOWED_BAD_POINTS}"
    fi

    while IFS=$'\t' read -r app_id app_name; do
        [[ -z "${app_id}" ]] && continue
        encoded_app="$(url_path_segment "${app_id}")"
        metric_url="$(appd_controller_api_url "${CONTROLLER_URL}" "/controller/rest/applications/${encoded_app}/metric-data-v2")"
        metric_response="$(mktemp)"
        TMP_FILES+=("${metric_response}")
        appd_curl -fsS -G -K "${AUTH_CONFIG}" "${metric_url}" \
            --data-urlencode "metric-path=${METRIC_PATH}" \
            --data-urlencode "time-range-type=BEFORE_NOW" \
            --data-urlencode "duration-in-mins=${DURATION_MINS}" \
            --data-urlencode "rollup=false" \
            --data-urlencode "output=JSON" > "${metric_response}"
        set +e
        summarize_metric_response "${app_id}" "${app_name}" "${metric_response}"
        code=$?
        set -e
        if [[ "${code}" -ne 0 ]]; then
            if [[ "${code}" -eq 1 ]]; then
                overall_status=1
            elif [[ "${overall_status}" -eq 0 ]]; then
                overall_status=3
            fi
        fi

        if [[ -n "${HEALTH_RULE_NAME}" ]]; then
            violations_url="$(appd_controller_api_url "${CONTROLLER_URL}" "/controller/rest/applications/${encoded_app}/problems/healthrule-violations")"
            violations_response="$(mktemp)"
            TMP_FILES+=("${violations_response}")
            appd_curl -fsS -G -K "${AUTH_CONFIG}" "${violations_url}" \
                --data-urlencode "time-range-type=BEFORE_NOW" \
                --data-urlencode "duration-in-mins=${VIOLATION_DURATION_MINS}" \
                --data-urlencode "output=JSON" > "${violations_response}"
            summarize_violations "${app_name}" "${violations_response}" || true
        fi
    done < "${APP_SPECS_FILE}"

    if [[ "${iteration}" -lt "${ITERATIONS}" && "${INTERVAL_SECONDS}" -gt 0 ]]; then
        sleep "${INTERVAL_SECONDS}"
    fi
done

exit "${overall_status}"
