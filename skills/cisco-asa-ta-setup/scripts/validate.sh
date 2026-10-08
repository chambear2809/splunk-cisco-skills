#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

RENDERED_DIR=""
LIVE=false
STRICT=false
INDEX="cisco_asa"
SOURCETYPE="cisco:asa"

usage() {
    cat <<EOF
Cisco ASA TA Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --rendered-dir PATH      Rendered root or cisco-asa-ta profile directory
  --live                   Run read-only Splunk REST/search checks
  --strict, --completion   Require live app, index, event, and shipped-dashboard evidence
  --index INDEX            Index for live checks
  --sourcetype SOURCETYPE  Sourcetype for live checks
  --help                   Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --rendered-dir) [[ $# -ge 2 ]] || { echo "ERROR: --rendered-dir requires a value." >&2; exit 1; }; RENDERED_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --strict|--completion) STRICT=true; shift ;;
        --index) [[ $# -ge 2 ]] || { echo "ERROR: --index requires a value." >&2; exit 1; }; INDEX="$2"; shift 2 ;;
        --sourcetype) [[ $# -ge 2 ]] || { echo "ERROR: --sourcetype requires a value." >&2; exit 1; }; SOURCETYPE="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        --token|--password|--api-key|--session-key) echo "ERROR: secrets must not be passed on argv." >&2; exit 1 ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

if [[ "${STRICT}" == "true" && "${LIVE}" != "true" ]]; then
    echo "ERROR: --strict/--completion requires --live." >&2
    exit 1
fi
if [[ "${STRICT}" == "true" && ! "${INDEX}" =~ ^[A-Za-z0-9_.:-]+$ ]]; then
    echo "ERROR: --index contains unsafe SPL characters." >&2
    exit 1
fi

cmd=(bash "${REPO_ROOT}/skills/shared/scripts/validate_render_first_skill.sh" --skill-name cisco-asa-ta-setup --profile-dir cisco-asa-ta --default-output cisco-asa-ta-rendered --app-name Splunk_TA_cisco-asa --index "${INDEX}" --sourcetypes "${SOURCETYPE}")
[[ -n "${RENDERED_DIR}" ]] && cmd+=(--rendered-dir "${RENDERED_DIR}")
[[ "${LIVE}" == "true" ]] && cmd+=(--live)
"${cmd[@]}"

if [[ "${STRICT}" == "true" ]]; then
    # The shared render validator intentionally treats live readiness gaps as
    # diagnostics. Recheck completion-critical ASA evidence locally.
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/skills/shared/lib/credential_helpers.sh"
    completion_failures=0
    if ! load_splunk_credentials || ! SK=$(get_session_key "${SPLUNK_URI}"); then
        echo "FAIL: could not authenticate for ASA completion validation" >&2
        exit 1
    fi
    if ! rest_check_app "${SK}" "${SPLUNK_URI}" "Splunk_TA_cisco-asa" 2>/dev/null; then
        echo "FAIL: Splunk_TA_cisco-asa is not installed" >&2
        completion_failures=$((completion_failures + 1))
    fi
    if ! platform_check_index "${SK}" "${SPLUNK_URI}" "${INDEX}" 2>/dev/null; then
        echo "FAIL: ASA index is missing: ${INDEX}" >&2
        completion_failures=$((completion_failures + 1))
    fi
    event_count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" \
        "| tstats count where index=${INDEX} sourcetype=\"${SOURCETYPE}\"" "count" 2>/dev/null || echo "0")
    if [[ ! "${event_count}" =~ ^[0-9]+$ || "${event_count}" -eq 0 ]]; then
        echo "FAIL: no ${SOURCETYPE} events found in ${INDEX}" >&2
        completion_failures=$((completion_failures + 1))
    fi

    # ASA 6.1.2 ships cisco_asa_dashboard.xml.  Fetch the exact view and
    # validate visibility/query identity before executing its panel searches.
    dashboard_tmp=$(mktemp)
    query_tmp=$(mktemp)
    app_tmp=$(mktemp)
    chmod 600 "${dashboard_tmp}" "${query_tmp}" "${app_tmp}"
    trap 'rm -f "${dashboard_tmp}" "${query_tmp}" "${app_tmp}"' EXIT INT TERM
    app_uri="${SPLUNK_URI%/}/services/apps/local/Splunk_TA_cisco-asa?output_mode=json"
    if ! splunk_curl "${SK}" --connect-timeout 5 --max-time 15 --max-filesize 1048576 \
        "${app_uri}" -w '\n%{http_code}' >"${app_tmp}" 2>/dev/null; then
        echo "FAIL: could not read ASA app visibility" >&2
        completion_failures=$((completion_failures + 1))
    else
        app_http_code=$(tail -n 1 "${app_tmp}")
        sed '$d' "${app_tmp}" >"${app_tmp}.body"
        mv "${app_tmp}.body" "${app_tmp}"
        if ! python3 - "${app_tmp}" <<'PY'
import json, sys
from pathlib import Path
try:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    entries = payload.get("entry", [])
    content = entries[0].get("content", {}) if len(entries) == 1 else {}
    visible = content.get("is_visible", content.get("visible"))
    if len(entries) != 1 or visible is None or str(visible).strip().lower() not in {"1", "true", "yes"}:
        raise ValueError
except (OSError, ValueError, TypeError, IndexError, json.JSONDecodeError):
    raise SystemExit(1)
PY
        then
            echo "FAIL: ASA app is missing or hidden (visibility readback failed, HTTP ${app_http_code})" >&2
            completion_failures=$((completion_failures + 1))
        fi
        app_version=$(python3 - "${app_tmp}" <<'PY'
import json, sys
try:
    entries = json.load(open(sys.argv[1], encoding="utf-8")).get("entry", [])
    print(str(entries[0].get("content", {}).get("version", "")) if len(entries) == 1 else "")
except Exception:
    print("")
PY
)
        [[ -n "${app_version}" ]] || completion_failures=$((completion_failures + 1))
    fi
    view_uri="${SPLUNK_URI%/}/servicesNS/nobody/Splunk_TA_cisco-asa/data/ui/views/cisco_asa_dashboard?output_mode=json"
    if ! splunk_curl "${SK}" --connect-timeout 5 --max-time 15 --max-filesize 2097152 \
        "${view_uri}" -w '\n%{http_code}' >"${dashboard_tmp}" 2>/dev/null; then
        echo "FAIL: could not read shipped ASA dashboard" >&2
        completion_failures=$((completion_failures + 1))
    else
        view_http_code=$(tail -n 1 "${dashboard_tmp}")
        sed '$d' "${dashboard_tmp}" >"${dashboard_tmp}.body"
        mv "${dashboard_tmp}.body" "${dashboard_tmp}"
        if [[ "${view_http_code}" != "200" ]]; then
            echo "FAIL: shipped ASA dashboard is missing (HTTP ${view_http_code})" >&2
            completion_failures=$((completion_failures + 1))
        elif ! python3 - "${dashboard_tmp}" "${query_tmp}" "${INDEX}" <<'PY'
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

body_path, query_path, index_name = sys.argv[1:]
try:
    payload = json.loads(Path(body_path).read_text(encoding="utf-8"))
    entries = payload.get("entry", [])
    if len(entries) != 1 or entries[0].get("name") != "cisco_asa_dashboard":
        raise ValueError("dashboard identity mismatch")
    content = entries[0].get("content", {}) or {}
    def truthy(value):
        return str(value).strip().lower() in {"1", "true", "yes"}
    if truthy(content.get("disabled")):
        raise ValueError("dashboard disabled")
    if "isDashboard" in content and not truthy(content["isDashboard"]):
        raise ValueError("view is not a dashboard")
    if "isVisible" in content and not truthy(content["isVisible"]):
        raise ValueError("dashboard hidden")
    if str(content.get("displayFor", "")).strip().lower() in {"none", "hidden"}:
        raise ValueError("dashboard hidden")
    acl = entries[0].get("acl") or content.get("eai:acl") or {}
    if not isinstance(acl, dict) or acl.get("app") != "Splunk_TA_cisco-asa":
        raise ValueError("dashboard ACL app mismatch")
    xml_text = content.get("eai:data") or content.get("data") or ""
    root = ET.fromstring(xml_text)
    queries = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].lower() == "query" and (node.text or "").strip():
            queries.append(" ".join((node.text or "").split()))
    if not queries:
        raise ValueError("dashboard has no executable searches")
    # Persist the resolved form. The shipped dashboard uses both the index
    # wildcard and tokenized limits; raw XML must never reach Splunk.
    defaults = {}
    for input_node in root.iter():
        if input_node.tag.rsplit("}", 1)[-1].lower() != "input":
            continue
        token = input_node.get("token")
        default_node = next((child for child in input_node if child.tag.rsplit("}", 1)[-1].lower() == "default"), None)
        if not token or default_node is None:
            continue
        children = list(default_node)
        if children:
            for child in children:
                defaults[f"{token}.{child.tag.rsplit('}', 1)[-1]}"] = " ".join((child.text or "").split())
        else:
            defaults[token] = " ".join((default_node.text or "").split())
    resolved_queries = []
    for query in queries:
        normalized = re.sub(r"\bindex\s+IN\s+\$index\$", f'index IN ("{index_name}")', query, flags=re.IGNORECASE)
        normalized = re.sub(r"\bindex\s+IN\s+\$INDEX\$", f'index IN ("{index_name}")', normalized, flags=re.IGNORECASE)
        normalized = normalized.replace("$index$", f'"{index_name}"').replace("$INDEX$", f'"{index_name}"')
        normalized = normalized.replace("index=*", f'index="{index_name}"')
        normalized = re.sub(r"\$([A-Za-z_][A-Za-z0-9_.]*)\$", lambda match: defaults.get(match.group(1), match.group(0)), normalized)
        if re.search(r"\$[A-Za-z_][A-Za-z0-9_.]*\$", normalized):
            raise ValueError("dashboard query has an unresolved token")
        if normalized == "| rest services/apps/local/Splunk_TA_cisco-asa splunk_server=local| fields version":
            kind = "version"
        elif re.search(r"\|\s*pivot\s+", normalized, re.IGNORECASE):
            pivot_name = re.search(r"\|\s*pivot\s+([A-Za-z0-9_]+)\s+", normalized, re.IGNORECASE)
            if not pivot_name or pivot_name.group(1) not in {"Network_Traffic", "Network_Sessions", "Authentication", "Change", "Certificates", "Intrusion_Detection", "Alerts"}:
                raise ValueError("dashboard contains an unsupported pivot")
            kind = "optional"
        elif re.search(r"\bindex(?:\s*=|\s+IN\s+)", normalized) and ("by index" in normalized or "dedup index" in normalized):
            kind = "metadata"
        elif re.search(r"\bindex(?:\s*=|\s+IN\s+)", normalized):
            kind = "primary"
        else:
            raise ValueError("dashboard query does not resolve a supported context")
        resolved_queries.append(f"{kind}\t{normalized}")
    Path(query_path).write_text("\n".join(resolved_queries) + "\n", encoding="utf-8")
except (OSError, ValueError, TypeError, json.JSONDecodeError, ET.ParseError):
    raise SystemExit(1)
PY
        then
            echo "FAIL: shipped ASA dashboard is missing, hidden, disabled, or has no index-bound queries" >&2
            completion_failures=$((completion_failures + 1))
        else
            asa_dashboard_oneshot() {
                local dashboard_search="$1" dashboard_field="${2:-count}" dashboard_body
                # Dashboard XML permits a bare generating search such as
                # `index IN (...)`; the jobs endpoint requires an explicit
                # search command for that form.
                if [[ ! "${dashboard_search}" =~ ^[[:space:]]*(\||search[[:space:]]) ]]; then
                    dashboard_search="search ${dashboard_search}"
                fi
                dashboard_body=$(form_urlencode_pairs \
                    search "${dashboard_search}" exec_mode oneshot output_mode json \
                    earliest_time "-24h" latest_time "now") || return 1
                splunk_curl_post "${SK}" "${dashboard_body}" \
                    "${SPLUNK_URI%/}/servicesNS/nobody/Splunk_TA_cisco-asa/search/jobs" 2>/dev/null \
                    | python3 -c 'import json,sys
import math
try:
    payload=json.load(sys.stdin)
    if payload.get("messages") and any(str(m.get("type", "")).lower() == "error" for m in payload["messages"] if isinstance(m, dict)):
        print("ERR:search response error")
        raise SystemExit
    results=payload.get("results", [])
    field=sys.argv[1]
    if field == "rows":
        print(len(results))
        raise SystemExit
    if field == "data":
        total=0.0
        found=False
        for row in results:
            for name in ("count", "Event count", "Total"):
                if name in row:
                    try:
                        total += float(row[name])
                        found=True
                    except (TypeError, ValueError):
                        pass
        print(int(total) if found and math.isfinite(total) and total >= 0 else "0")
        raise SystemExit
    value=results[0].get(field, "") if results else "0"
    if field == "version":
        print(str(value))
        raise SystemExit
    number=float(value)
    print(int(number) if math.isfinite(number) and number >= 0 else "0")
except (ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError):
    print("ERR:invalid search response")' "${dashboard_field}"
            }
            dashboard_query_number=0
            while IFS=$'\t' read -r dashboard_query_kind dashboard_query; do
                [[ -n "${dashboard_query}" ]] || continue
                dashboard_query_number=$((dashboard_query_number + 1))
                if [[ "${dashboard_query_kind}" == "version" ]]; then
                    dashboard_query_count=$(asa_dashboard_oneshot \
                        "${dashboard_query} | stats values(version) as version" version 2>/dev/null || echo "ERR")
                    if [[ "${dashboard_query_count}" != "${app_version}" ]]; then
                        echo "FAIL: ASA dashboard version query did not match installed app" >&2
                        completion_failures=$((completion_failures + 1))
                    fi
                    continue
                fi
                dashboard_query_field="data"
                [[ "${dashboard_query_kind}" == "metadata" ]] && dashboard_query_field="rows"
                dashboard_query_count=$(asa_dashboard_oneshot "${dashboard_query}" "${dashboard_query_field}" 2>/dev/null || echo "ERR")
                if [[ "${dashboard_query_count}" == ERR* ]]; then
                    echo "FAIL: ASA dashboard query ${dashboard_query_number} failed" >&2
                    completion_failures=$((completion_failures + 1))
                elif [[ "${dashboard_query_kind}" == "primary" && ( ! "${dashboard_query_count}" =~ ^[0-9]+$ || "${dashboard_query_count}" -eq 0 ) ]]; then
                    echo "FAIL: ASA dashboard query ${dashboard_query_number} returned no data" >&2
                    completion_failures=$((completion_failures + 1))
                elif [[ "${dashboard_query_kind}" == "metadata" && ( ! "${dashboard_query_count}" =~ ^[0-9]+$ || "${dashboard_query_count}" -eq 0 ) ]]; then
                    echo "FAIL: ASA dashboard metadata query ${dashboard_query_number} returned no rows" >&2
                    completion_failures=$((completion_failures + 1))
                fi
            done <"${query_tmp}"
            [[ "${dashboard_query_number}" -gt 0 ]] || completion_failures=$((completion_failures + 1))
        fi
    fi
    [[ "${completion_failures}" -eq 0 ]]
fi
