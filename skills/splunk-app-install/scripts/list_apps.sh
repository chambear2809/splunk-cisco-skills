#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

FILTER=""

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# Accept flags for non-interactive use; anything missing gets prompted
while [[ $# -gt 0 ]]; do
    case "$1" in
        --filter) FILTER="$2"; shift 2 ;;
        --help)
            cat <<EOF
List Installed Splunk Apps (interactive)

Usage: $(basename "$0") [OPTIONS]

Optional flags (skip the corresponding prompt):
  --filter PATTERN   Filter app names (case-insensitive substring)

Credentials are read from the project-root credentials file automatically.
Run: bash ${SCRIPT_DIR}/../../shared/scripts/setup_credentials.sh
EOF
            exit 0 ;;
        *) log "Unknown option: $1"; exit 1 ;;
    esac
done

echo "=== List Installed Splunk Apps ==="
echo ""

if [[ -z "${FILTER}" ]]; then
    echo ""
    read -rp "Filter by name (leave blank for all): " FILTER
fi

if is_splunk_cloud; then
    acs_prepare_context || exit 1

    log "Fetching installed apps from Splunk Cloud via ACS..."
    echo ""

    response=$(acs_command apps list --count 1000 2>/dev/null)

    APP_RESPONSE="${response}" python3 - "${FILTER}" <<'PYEOF'
import json, os, sys

filter_str = sys.argv[1].lower() if len(sys.argv) > 1 else ""

try:
    data = json.loads(os.environ.get("APP_RESPONSE", "{}"))
except (json.JSONDecodeError, ValueError):
    print("ERROR: Could not parse ACS response", file=sys.stderr)
    sys.exit(1)

entries = data.get("apps", [])
apps = []

for entry in entries:
    name = entry.get("name") or entry.get("appID", "")
    version = entry.get("version", "n/a")
    label = entry.get("label", name)
    status = entry.get("status", "unknown")

    if filter_str and filter_str not in name.lower() and filter_str not in label.lower():
        continue

    apps.append((name, version, label, status))

apps.sort(key=lambda x: x[0])

if not apps:
    if filter_str:
        print(f"No apps matching '{filter_str}' found.")
    else:
        print("No apps found.")
    sys.exit(0)

name_w = max(len(a[0]) for a in apps)
ver_w = max(len(a[1]) for a in apps)
label_w = max(len(a[2]) for a in apps)

header = f"{'APP NAME':<{name_w}}  {'VERSION':<{ver_w}}  {'STATUS':<12}  {'LABEL'}"
print(header)
print("-" * len(header))

for name, version, label, status in apps:
    print(f"{name:<{name_w}}  {version:<{ver_w}}  {status:<12}  {label}")

print(f"\nTotal: {len(apps)} app(s)")
PYEOF
    exit 0
fi

load_splunk_credentials

SK=$(get_session_key "${SPLUNK_URI}")

log "Fetching installed apps..."
echo ""

response=$(splunk_curl "${SK}" \
    "${SPLUNK_URI}/services/apps/local?output_mode=json&count=0" 2>/dev/null)

APP_RESPONSE="${response}" python3 - "${FILTER}" <<'PYEOF'
import json, os, sys

filter_str = sys.argv[1].lower() if len(sys.argv) > 1 else ""

try:
    data = json.loads(os.environ.get("APP_RESPONSE", "{}"))
except (json.JSONDecodeError, ValueError):
    print("ERROR: Could not parse Splunk response", file=sys.stderr)
    sys.exit(1)

entries = data.get("entry", [])
apps = []

for entry in entries:
    name = entry.get("name", "")
    content = entry.get("content", {})
    version = content.get("version", "n/a")
    label = content.get("label", name)
    disabled = content.get("disabled", False)
    visible = content.get("visible", True)
    update_available = content.get("update", {})

    if filter_str and filter_str not in name.lower() and filter_str not in label.lower():
        continue

    status = "disabled" if disabled else "enabled"
    apps.append((name, version, label, status))

apps.sort(key=lambda x: x[0])

if not apps:
    if filter_str:
        print(f"No apps matching '{filter_str}' found.")
    else:
        print("No apps found.")
    sys.exit(0)

name_w = max(len(a[0]) for a in apps)
ver_w = max(len(a[1]) for a in apps)
label_w = max(len(a[2]) for a in apps)

header = f"{'APP NAME':<{name_w}}  {'VERSION':<{ver_w}}  {'STATUS':<10}  {'LABEL'}"
print(header)
print("-" * len(header))

for name, version, label, status in apps:
    print(f"{name:<{name_w}}  {version:<{ver_w}}  {status:<10}  {label}")

print(f"\nTotal: {len(apps)} app(s)")
PYEOF
