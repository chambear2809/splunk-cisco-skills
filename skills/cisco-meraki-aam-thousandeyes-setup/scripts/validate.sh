#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: bash skills/cisco-meraki-aam-thousandeyes-setup/scripts/validate.sh [options]

Options:
  --meraki-api-key-file PATH Meraki Dashboard API key file (or MERAKI_API_KEY_FILE)
  --meraki-org-id ID         Meraki organization ID for network/device preflight
  --network-filter TEXT      Case-insensitive Meraki network name/ID filter
  --mx-serial-filter TEXT    Case-insensitive Meraki MX serial filter
  --te-token-file PATH       ThousandEyes bearer token file (or TE_TOKEN_FILE)
  --account-group-id ID      ThousandEyes account group ID (optional)
  --agent-filter TEXT        Case-insensitive agent name/serial/location filter
  --test-filter TEXT         Case-insensitive test name/type/url filter
  --output-dir DIR           Output directory (default: meraki-aam-live-validation)
  --json                     Print compact JSON summary to stdout
  --help                     Show this help

The token is read from a file and passed to curl through a temporary curl config.
No Meraki Dashboard private endpoint is called by this script.
EOF
}

MERAKI_API_KEY_FILE="${MERAKI_API_KEY_FILE:-}"
MERAKI_ORG_ID=""
MERAKI_API_BASE="${MERAKI_API_BASE:-https://api.meraki.com/api/v1}"
NETWORK_FILTER=""
MX_SERIAL_FILTER=""
TE_TOKEN_FILE="${TE_TOKEN_FILE:-}"
ACCOUNT_GROUP_ID=""
AGENT_FILTER=""
TEST_FILTER=""
OUTPUT_DIR="meraki-aam-live-validation"
PRINT_JSON="false"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --meraki-api-key-file)
            MERAKI_API_KEY_FILE="${2:-}"
            shift 2
            ;;
        --meraki-org-id|--organization-id)
            MERAKI_ORG_ID="${2:-}"
            shift 2
            ;;
        --network-filter)
            NETWORK_FILTER="${2:-}"
            shift 2
            ;;
        --mx-serial-filter|--serial-filter)
            MX_SERIAL_FILTER="${2:-}"
            shift 2
            ;;
        --meraki-api-base)
            MERAKI_API_BASE="${2:-}"
            shift 2
            ;;
        --te-token-file)
            TE_TOKEN_FILE="${2:-}"
            shift 2
            ;;
        --account-group-id|--aid)
            ACCOUNT_GROUP_ID="${2:-}"
            shift 2
            ;;
        --agent-filter)
            AGENT_FILTER="${2:-}"
            shift 2
            ;;
        --test-filter)
            TEST_FILTER="${2:-}"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="${2:-}"
            shift 2
            ;;
        --json)
            PRINT_JSON="true"
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ -z "${TE_TOKEN_FILE}" && -z "${MERAKI_API_KEY_FILE}" ]]; then
    echo "ERROR: provide --meraki-api-key-file, --te-token-file, or both." >&2
    exit 2
fi

mkdir -p "${OUTPUT_DIR}"

MERAKI_CURL_CONFIG=""
TE_CURL_CONFIG=""
cleanup() {
    if [[ -n "${MERAKI_CURL_CONFIG}" ]]; then
        rm -f "${MERAKI_CURL_CONFIG}"
    fi
    if [[ -n "${TE_CURL_CONFIG}" ]]; then
        rm -f "${TE_CURL_CONFIG}"
    fi
    return 0
}
trap cleanup EXIT

check_secret_file() {
    local path="$1"
    local label="$2"
    if [[ -z "${path}" || ! -r "${path}" ]]; then
        echo "ERROR: ${label} must point at a readable secret file." >&2
        exit 2
    fi
    python3 - "$path" "$label" <<'PY'
import os
import sys

path, label = sys.argv[1], sys.argv[2]
mode = os.stat(path).st_mode & 0o777
if mode & 0o077:
    print(f"ERROR: {label} permissions are {mode:o}; run: chmod 600 {path}", file=sys.stderr)
    raise SystemExit(2)
PY
}

if [[ -n "${MERAKI_API_KEY_FILE}" ]]; then
    check_secret_file "${MERAKI_API_KEY_FILE}" "--meraki-api-key-file"
    MERAKI_CURL_CONFIG="$(mktemp)"
    chmod 600 "${MERAKI_CURL_CONFIG}"
    { printf 'header = "X-Cisco-Meraki-API-Key: '; tr -d '\r\n' < "${MERAKI_API_KEY_FILE}"; printf '"\n'; } > "${MERAKI_CURL_CONFIG}"

    MERAKI_API_BASE="${MERAKI_API_BASE%/}"
    curl -sS -f "${MERAKI_API_BASE}/organizations?perPage=1000" \
        -K "${MERAKI_CURL_CONFIG}" \
        -H "Accept: application/json" \
        -o "${OUTPUT_DIR}/meraki-organizations.json"

    if [[ -n "${MERAKI_ORG_ID}" ]]; then
        curl -sS -f "${MERAKI_API_BASE}/organizations/${MERAKI_ORG_ID}/networks?perPage=1000" \
            -K "${MERAKI_CURL_CONFIG}" \
            -H "Accept: application/json" \
            -o "${OUTPUT_DIR}/meraki-networks.json"

        curl -sS -f "${MERAKI_API_BASE}/organizations/${MERAKI_ORG_ID}/devices?perPage=1000" \
            -K "${MERAKI_CURL_CONFIG}" \
            -H "Accept: application/json" \
            -o "${OUTPUT_DIR}/meraki-devices.json"
    fi
fi

if [[ -n "${TE_TOKEN_FILE}" ]]; then
    check_secret_file "${TE_TOKEN_FILE}" "--te-token-file"
    TE_CURL_CONFIG="$(mktemp)"
    chmod 600 "${TE_CURL_CONFIG}"
    { printf 'header = "Authorization: Bearer '; tr -d '\r\n' < "${TE_TOKEN_FILE}"; printf '"\n'; } > "${TE_CURL_CONFIG}"

    query=""
    if [[ -n "${ACCOUNT_GROUP_ID}" ]]; then
        query="?aid=${ACCOUNT_GROUP_ID}"
    fi

    curl -sS -f "https://api.thousandeyes.com/v7/agents${query}" \
        -K "${TE_CURL_CONFIG}" \
        -H "Accept: application/hal+json, application/json" \
        -o "${OUTPUT_DIR}/agents.json"

    curl -sS -f "https://api.thousandeyes.com/v7/tests${query}" \
        -K "${TE_CURL_CONFIG}" \
        -H "Accept: application/hal+json, application/json" \
        -o "${OUTPUT_DIR}/tests.json"
fi

python3 - "$OUTPUT_DIR" "$AGENT_FILTER" "$TEST_FILTER" "$NETWORK_FILTER" "$MX_SERIAL_FILTER" "$PRINT_JSON" <<'PY'
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
agent_filter = sys.argv[2].lower()
test_filter = sys.argv[3].lower()
network_filter = sys.argv[4].lower()
mx_serial_filter = sys.argv[5].lower()
print_json = sys.argv[6] == "true"

SUPPORTED_MX_MODELS = {
    "MX67", "MX67W", "MX67C", "MX68", "MX68W", "MX68CW", "MX75", "MX85",
    "MX95", "MX105", "MX250", "MX450", "C8111-G2", "C8111-C-G2",
    "C8121-G2", "C8121-W-G2", "C8121-CW-G2", "C8455-G2",
}


def normalize_mx_model(model):
    value = str(model or "").upper()
    if value in SUPPORTED_MX_MODELS:
        return value
    for suffix in ("-NA", "-WW", "-RW", "-EU"):
        if value.endswith(suffix):
            candidate = value[: -len(suffix)]
            if candidate in SUPPORTED_MX_MODELS:
                return candidate
    return value


def load(name):
    path = out / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{name} is not JSON: {exc}")


def first_list(payload, preferred):
    if isinstance(payload, dict):
        for key in preferred:
            value = payload.get(key)
            if isinstance(value, list):
                return value
        embedded = payload.get("_embedded")
        if isinstance(embedded, dict):
            for value in embedded.values():
                if isinstance(value, list):
                    return value
    if isinstance(payload, list):
        return payload
    return []


def text_match(item, needle, keys):
    if not needle:
        return True
    haystack = " ".join(str(item.get(key, "")) for key in keys).lower()
    return needle in haystack


agents = first_list(load("agents.json"), ["agents"])
tests = first_list(load("tests.json"), ["tests"])
meraki_orgs = first_list(load("meraki-organizations.json"), ["organizations"])
meraki_networks = first_list(load("meraki-networks.json"), ["networks"])
meraki_devices = first_list(load("meraki-devices.json"), ["devices"])

matching_agents = [
    agent
    for agent in agents
    if text_match(
        agent,
        agent_filter,
        ["agentName", "name", "location", "serialNumber", "hostname", "agentState", "agentType"],
    )
]
matching_tests = [
    test
    for test in tests
    if text_match(test, test_filter, ["testName", "name", "type", "url", "server", "target"])
]
matching_networks = [
    network
    for network in meraki_networks
    if text_match(network, network_filter, ["name", "id", "networkId", "productTypes", "tags", "timeZone"])
]
matching_network_ids = {
    str(network.get("id") or network.get("networkId"))
    for network in matching_networks
    if network.get("id") or network.get("networkId")
}


def is_mx_device(device):
    model = str(device.get("model", "")).upper()
    return model.startswith("MX") or model.startswith("C8")


def device_matches(device):
    if mx_serial_filter and mx_serial_filter not in str(device.get("serial", "")).lower():
        return False
    if network_filter:
        network_id = str(device.get("networkId", ""))
        if network_id in matching_network_ids:
            return True
        return text_match(device, network_filter, ["name", "serial", "model", "networkId", "tags"])
    return True


mx_devices = [device for device in meraki_devices if is_mx_device(device)]
matching_mx_devices = [device for device in mx_devices if device_matches(device)]

summary = {
    "meraki_organization_count": len(meraki_orgs),
    "meraki_network_count": len(meraki_networks),
    "matching_meraki_network_count": len(matching_networks),
    "meraki_mx_device_count": len(mx_devices),
    "matching_meraki_mx_device_count": len(matching_mx_devices),
    "agent_count": len(agents),
    "matching_agent_count": len(matching_agents),
    "test_count": len(tests),
    "matching_test_count": len(matching_tests),
    "matching_agents": [
        {
            "agentId": agent.get("agentId"),
            "agentName": agent.get("agentName") or agent.get("name"),
            "agentState": agent.get("agentState"),
            "agentType": agent.get("agentType"),
            "serialNumber": agent.get("serialNumber"),
            "location": agent.get("location"),
            "utilization": agent.get("utilization"),
        }
        for agent in matching_agents
    ],
    "matching_meraki_networks": [
        {
            "id": network.get("id") or network.get("networkId"),
            "name": network.get("name"),
            "productTypes": network.get("productTypes"),
            "tags": network.get("tags"),
            "timeZone": network.get("timeZone"),
        }
        for network in matching_networks
    ],
    "matching_meraki_mx_devices": [
        {
            "serial": device.get("serial"),
            "name": device.get("name"),
            "model": device.get("model"),
            "normalizedModel": normalize_mx_model(device.get("model")),
            "networkId": device.get("networkId"),
            "supportedForAam": normalize_mx_model(device.get("model")) in SUPPORTED_MX_MODELS,
        }
        for device in matching_mx_devices
    ],
    "matching_tests": [
        {
            "testId": test.get("testId"),
            "testName": test.get("testName") or test.get("name"),
            "type": test.get("type"),
            "enabled": test.get("enabled"),
            "url": test.get("url"),
            "server": test.get("server"),
        }
        for test in matching_tests
    ],
}

(out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

lines = [
    "# Meraki AAM ThousandEyes Live Validation",
    "",
    f"- Meraki organizations returned: {summary['meraki_organization_count']}",
    f"- Meraki networks returned: {summary['meraki_network_count']}",
    f"- Matching Meraki networks: {summary['matching_meraki_network_count']}",
    f"- Meraki MX/C8 devices returned: {summary['meraki_mx_device_count']}",
    f"- Matching Meraki MX/C8 devices: {summary['matching_meraki_mx_device_count']}",
    f"- Agents returned: {summary['agent_count']}",
    f"- Matching agents: {summary['matching_agent_count']}",
    f"- Tests returned: {summary['test_count']}",
    f"- Matching tests: {summary['matching_test_count']}",
    "",
    "## Matching Meraki Networks",
    "",
]
if summary["matching_meraki_networks"]:
    for network in summary["matching_meraki_networks"]:
        lines.append(
            f"- `{network.get('id')}` {network.get('name')} productTypes={network.get('productTypes')}"
        )
else:
    lines.append("- None or Meraki organization ID not supplied.")
lines.extend(["", "## Matching Meraki MX Devices", ""])
if summary["matching_meraki_mx_devices"]:
    for device in summary["matching_meraki_mx_devices"]:
        lines.append(
            f"- `{device.get('serial')}` {device.get('model')} supportedForAam={device.get('supportedForAam')} "
            f"{device.get('name')} networkId={device.get('networkId')}"
        )
else:
    lines.append("- None or Meraki organization ID not supplied.")
lines.extend([
    "",
    "## Matching Agents",
    "",
])
if summary["matching_agents"]:
    for agent in summary["matching_agents"]:
        lines.append(
            f"- `{agent.get('agentId')}` `{agent.get('agentState')}` "
            f"`{agent.get('agentType')}` {agent.get('agentName')} serial={agent.get('serialNumber')}"
        )
else:
    lines.append("- None")
lines.extend(["", "## Matching Tests", ""])
if summary["matching_tests"]:
    for test in summary["matching_tests"]:
        lines.append(
            f"- `{test.get('testId')}` `{test.get('type')}` enabled={test.get('enabled')} "
            f"{test.get('testName')} {test.get('url') or test.get('server') or ''}"
        )
else:
    lines.append("- None")
(out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

if print_json:
    print(json.dumps(summary, indent=2, sort_keys=True))
else:
    print(f"Wrote validation evidence to {out}")
PY
