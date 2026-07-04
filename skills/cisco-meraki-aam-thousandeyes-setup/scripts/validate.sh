#!/usr/bin/env bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_curl_helpers.sh"

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

if [[ -n "${MERAKI_ORG_ID}" && ! "${MERAKI_ORG_ID}" =~ ^[0-9]+$ ]]; then
    echo "ERROR: --meraki-org-id must be numeric." >&2
    exit 2
fi
if [[ -n "${ACCOUNT_GROUP_ID}" && ! "${ACCOUNT_GROUP_ID}" =~ ^[0-9]+$ ]]; then
    echo "ERROR: --account-group-id must be numeric." >&2
    exit 2
fi
MERAKI_API_BASE="${MERAKI_API_BASE%/}"
if [[ "${MERAKI_API_BASE}" != "https://api.meraki.com/api/v1" ]]; then
    echo "ERROR: --meraki-api-base must be exactly https://api.meraki.com/api/v1." >&2
    exit 2
fi
credential_curl_prepare_transport false

if ! OUTPUT_DIR="$(python3 - "${OUTPUT_DIR}" "${SCRIPT_DIR}" <<'PY'
import json
import os
import stat
import sys
from pathlib import Path

raw, script_dir = sys.argv[1:]
marker_name = ".cisco-meraki-aam-validation-bundle.json"
owner = "cisco-meraki-aam-thousandeyes-setup"
schema = 1
if not raw or not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("ERROR: --output-dir is empty or this platform lacks O_NOFOLLOW")

path = Path(os.path.abspath(raw))
if sys.platform == "darwin" and len(path.parts) > 1 and path.parts[1] in {"tmp", "var"}:
    alias = Path("/") / path.parts[1]
    try:
        alias_info = alias.lstat()
        target = alias.resolve(strict=True)
    except OSError:
        pass
    else:
        if (
            stat.S_ISLNK(alias_info.st_mode)
            and alias_info.st_uid == 0
            and target.parts[:2] == ("/", "private")
        ):
            path = target.joinpath(*path.parts[2:])

repo = Path(script_dir).resolve().parents[2]
protected = {Path("/"), Path.home().resolve(), repo}
if path in protected:
    raise SystemExit(f"ERROR: refusing protected --output-dir: {path}")
if ".." in path.parts:
    raise SystemExit("ERROR: --output-dir must not contain parent traversal")

flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
directory_fd = os.open("/", flags)
created_final = False
try:
    components = path.parts[1:]
    for index, component in enumerate(components):
        try:
            child_fd = os.open(component, flags, dir_fd=directory_fd)
        except FileNotFoundError:
            os.mkdir(component, 0o700, dir_fd=directory_fd)
            child_fd = os.open(component, flags, dir_fd=directory_fd)
            if index == len(components) - 1:
                created_final = True
        os.close(directory_fd)
        directory_fd = child_fd

    info = os.fstat(directory_fd)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise SystemExit("ERROR: validation output bundle must be an owner-only mode-0700 directory")

    entries = set(os.listdir(directory_fd))
    if marker_name not in entries:
        if entries or not created_final and entries:
            raise SystemExit(
                "ERROR: existing --output-dir is not an empty or marker-owned validation bundle"
            )
        payload = json.dumps(
            {"owner": owner, "schema": schema},
            sort_keys=True,
            indent=2,
        ).encode("utf-8") + b"\n"
        marker_fd = os.open(
            marker_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_fd,
        )
        try:
            os.write(marker_fd, payload)
            os.fsync(marker_fd)
        finally:
            os.close(marker_fd)
        os.fsync(directory_fd)

    marker_fd = os.open(
        marker_name,
        os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        dir_fd=directory_fd,
    )
    try:
        marker_info = os.fstat(marker_fd)
        if (
            not stat.S_ISREG(marker_info.st_mode)
            or marker_info.st_nlink != 1
            or stat.S_IMODE(marker_info.st_mode) != 0o600
        ):
            raise SystemExit("ERROR: validation bundle marker is not a private single-link file")
        marker = json.loads(os.read(marker_fd, 65536).decode("utf-8"))
    finally:
        os.close(marker_fd)
    if marker != {"owner": owner, "schema": schema}:
        raise SystemExit("ERROR: validation output bundle marker owner/schema mismatch")
finally:
    os.close(directory_fd)

print(path, end="")
PY
)"; then
    exit 2
fi

MERAKI_CURL_CONFIG=""
TE_CURL_CONFIG=""
ACTIVE_RESPONSE_FILE=""
cleanup() {
    if [[ -n "${MERAKI_CURL_CONFIG}" ]]; then
        rm -f "${MERAKI_CURL_CONFIG}"
    fi
    if [[ -n "${TE_CURL_CONFIG}" ]]; then
        rm -f "${TE_CURL_CONFIG}"
    fi
    if [[ -n "${ACTIVE_RESPONSE_FILE}" ]]; then
        rm -f "${ACTIVE_RESPONSE_FILE}"
    fi
    return 0
}

write_api_json() {
    local url="$1" auth_config="$2" accept_header="$3" output_name="$4" allowed_prefix="$5"
    if [[ ! "${output_name}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*\.json$ ]]; then
        echo "ERROR: internal API evidence filename is unsafe: ${output_name}" >&2
        return 2
    fi
    if ! credential_curl_validate_url "${url}" false; then
        echo "ERROR: refusing credential-bearing request to an unsafe URL." >&2
        return 2
    fi
    if [[ "${url}" != "${allowed_prefix}"* ]]; then
        echo "ERROR: refusing credential-bearing request outside its pinned API origin/path." >&2
        return 2
    fi
    ACTIVE_RESPONSE_FILE="$(mktemp "${OUTPUT_DIR}/.${output_name}.XXXXXX")"
    chmod 600 "${ACTIVE_RESPONSE_FILE}"
    if ! curl -q -sS -f "${url}" \
        -K "${auth_config}" \
        -H "Accept: ${accept_header}" \
        -o "${ACTIVE_RESPONSE_FILE}" \
        --connect-timeout 10 --max-time 120 \
        "${CREDENTIAL_CURL_TRANSPORT_ARGS[@]}"; then
        rm -f "${ACTIVE_RESPONSE_FILE}"
        ACTIVE_RESPONSE_FILE=""
        return 1
    fi
    python3 - "${ACTIVE_RESPONSE_FILE##*/}" "${output_name}" "${OUTPUT_DIR}" <<'PY'
import json
import os
import stat
import sys

source_name, destination_name, parent = sys.argv[1:]
marker_name = ".cisco-meraki-aam-validation-bundle.json"
flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
parent_fd = os.open(
    parent,
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
)
try:
    parent_stat = os.fstat(parent_fd)
    if (
        not stat.S_ISDIR(parent_stat.st_mode)
        or stat.S_IMODE(parent_stat.st_mode) != 0o700
        or parent_stat.st_uid != os.geteuid()
    ):
        raise SystemExit("ERROR: API evidence directory is not a private owned directory")
    marker_fd = os.open(marker_name, flags, dir_fd=parent_fd)
    try:
        marker_stat = os.fstat(marker_fd)
        marker = json.loads(os.read(marker_fd, 65536).decode("utf-8"))
        if (
            not stat.S_ISREG(marker_stat.st_mode)
            or marker_stat.st_nlink != 1
            or stat.S_IMODE(marker_stat.st_mode) != 0o600
            or marker != {"owner": "cisco-meraki-aam-thousandeyes-setup", "schema": 1}
        ):
            raise SystemExit("ERROR: API evidence bundle marker is invalid")
    finally:
        os.close(marker_fd)
    source_fd = os.open(source_name, flags, dir_fd=parent_fd)
    try:
        source_stat = os.fstat(source_fd)
        if (
            not stat.S_ISREG(source_stat.st_mode)
            or source_stat.st_nlink != 1
            or stat.S_IMODE(source_stat.st_mode) != 0o600
        ):
            raise SystemExit("ERROR: API response staging file is unsafe")
    finally:
        os.close(source_fd)
    try:
        destination_fd = os.open(destination_name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        destination_fd = None
    if destination_fd is not None:
        try:
            destination_stat = os.fstat(destination_fd)
            if (
                not stat.S_ISREG(destination_stat.st_mode)
                or destination_stat.st_nlink != 1
                or stat.S_IMODE(destination_stat.st_mode) != 0o600
            ):
                raise SystemExit("ERROR: API evidence destination is unsafe")
        finally:
            os.close(destination_fd)
    os.replace(source_name, destination_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    os.fsync(parent_fd)
finally:
    os.close(parent_fd)
PY
    ACTIVE_RESPONSE_FILE=""
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
    credential_curl_write_header_config \
        "${MERAKI_API_KEY_FILE}" "X-Cisco-Meraki-API-Key" "${MERAKI_CURL_CONFIG}"

    write_api_json "${MERAKI_API_BASE}/organizations?perPage=1000" \
        "${MERAKI_CURL_CONFIG}" "application/json" "meraki-organizations.json" \
        "${MERAKI_API_BASE}/"

    if [[ -n "${MERAKI_ORG_ID}" ]]; then
        write_api_json "${MERAKI_API_BASE}/organizations/${MERAKI_ORG_ID}/networks?perPage=1000" \
            "${MERAKI_CURL_CONFIG}" "application/json" "meraki-networks.json" \
            "${MERAKI_API_BASE}/"

        write_api_json "${MERAKI_API_BASE}/organizations/${MERAKI_ORG_ID}/devices?perPage=1000" \
            "${MERAKI_CURL_CONFIG}" "application/json" "meraki-devices.json" \
            "${MERAKI_API_BASE}/"
    fi
fi

if [[ -n "${TE_TOKEN_FILE}" ]]; then
    check_secret_file "${TE_TOKEN_FILE}" "--te-token-file"
    TE_CURL_CONFIG="$(mktemp)"
    chmod 600 "${TE_CURL_CONFIG}"
    credential_curl_write_header_config \
        "${TE_TOKEN_FILE}" "Authorization" "${TE_CURL_CONFIG}" "Bearer "

    query=""
    if [[ -n "${ACCOUNT_GROUP_ID}" ]]; then
        query="?aid=${ACCOUNT_GROUP_ID}"
    fi

    write_api_json "https://api.thousandeyes.com/v7/agents${query}" \
        "${TE_CURL_CONFIG}" "application/hal+json, application/json" "agents.json" \
        "https://api.thousandeyes.com/v7/"

    write_api_json "https://api.thousandeyes.com/v7/tests${query}" \
        "${TE_CURL_CONFIG}" "application/hal+json, application/json" "tests.json" \
        "https://api.thousandeyes.com/v7/"
fi

python3 - "$OUTPUT_DIR" "$AGENT_FILTER" "$TEST_FILTER" "$NETWORK_FILTER" "$MX_SERIAL_FILTER" "$PRINT_JSON" <<'PY'
import json
import os
import stat
import sys
from pathlib import Path

out = Path(sys.argv[1])
agent_filter = sys.argv[2].lower()
test_filter = sys.argv[3].lower()
network_filter = sys.argv[4].lower()
mx_serial_filter = sys.argv[5].lower()
print_json = sys.argv[6] == "true"
marker_name = ".cisco-meraki-aam-validation-bundle.json"
read_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
bundle_fd = os.open(
    out,
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
)
bundle_info = os.fstat(bundle_fd)
if (
    not stat.S_ISDIR(bundle_info.st_mode)
    or bundle_info.st_uid != os.geteuid()
    or stat.S_IMODE(bundle_info.st_mode) != 0o700
):
    raise SystemExit("ERROR: validation output bundle is not a private owned directory")
marker_fd = os.open(marker_name, read_flags, dir_fd=bundle_fd)
try:
    marker_info = os.fstat(marker_fd)
    marker = json.loads(os.read(marker_fd, 65536).decode("utf-8"))
finally:
    os.close(marker_fd)
if (
    not stat.S_ISREG(marker_info.st_mode)
    or marker_info.st_nlink != 1
    or stat.S_IMODE(marker_info.st_mode) != 0o600
    or marker != {"owner": "cisco-meraki-aam-thousandeyes-setup", "schema": 1}
):
    raise SystemExit("ERROR: validation output bundle marker is invalid")

loaded_names = set()


def read_private_file(name):
    try:
        descriptor = os.open(name, read_flags, dir_fd=bundle_fd)
    except FileNotFoundError:
        return None
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size > 64 * 1024 * 1024
        ):
            raise SystemExit(f"ERROR: unsafe validation evidence file: {name}")
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            or after.st_nlink != 1
        ):
            raise SystemExit(f"ERROR: validation evidence changed during read: {name}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def atomic_private_write(name, content):
    if "/" in name or name in {"", ".", ".."}:
        raise SystemExit("ERROR: unsafe summary output name")
    try:
        existing_fd = os.open(name, read_flags, dir_fd=bundle_fd)
    except FileNotFoundError:
        existing_fd = None
    if existing_fd is not None:
        try:
            existing = os.fstat(existing_fd)
            if (
                not stat.S_ISREG(existing.st_mode)
                or existing.st_nlink != 1
                or stat.S_IMODE(existing.st_mode) != 0o600
            ):
                raise SystemExit(f"ERROR: unsafe summary destination: {name}")
        finally:
            os.close(existing_fd)
    temporary = f".{name}.{os.getpid()}.{os.urandom(16).hex()}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        0o600,
        dir_fd=bundle_fd,
    )
    created = True
    try:
        payload = content.encode("utf-8")
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise SystemExit(f"ERROR: short summary write: {name}")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, name, src_dir_fd=bundle_fd, dst_dir_fd=bundle_fd)
        created = False
        os.fsync(bundle_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if created:
            try:
                os.unlink(temporary, dir_fd=bundle_fd)
            except FileNotFoundError:
                pass

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
    raw = read_private_file(name)
    if raw is None:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{name} is not JSON: {exc}")
    loaded_names.add(name)
    return payload


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

atomic_private_write("summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n")

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
atomic_private_write("summary.md", "\n".join(lines) + "\n")

failures = []
if "meraki-organizations.json" in loaded_names and not meraki_orgs:
    failures.append("Meraki API returned no organizations")
if "meraki-networks.json" in loaded_names and not matching_networks:
    failures.append("no Meraki networks matched the requested organization/filter")
if "meraki-devices.json" in loaded_names and not any(
    normalize_mx_model(device.get("model")) in SUPPORTED_MX_MODELS
    for device in matching_mx_devices
):
    failures.append("no supported MX/C8 devices matched the requested filters")
if "agents.json" in loaded_names and not matching_agents:
    failures.append("no ThousandEyes agents matched the requested filters")
if "tests.json" in loaded_names and not matching_tests:
    failures.append("no ThousandEyes tests matched the requested filters")

if print_json:
    print(json.dumps(summary, indent=2, sort_keys=True))
else:
    print(f"Wrote validation evidence to {out}")
if failures:
    for failure in failures:
        print(f"ERROR: {failure}", file=sys.stderr)
    raise SystemExit(1)
os.close(bundle_fd)
PY
