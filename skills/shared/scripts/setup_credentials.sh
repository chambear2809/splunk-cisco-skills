#!/usr/bin/env bash
set -euo pipefail

SETUP_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SETUP_SCRIPT_DIR}/../../.." && pwd)"
CRED_FILE="${PROJECT_ROOT}/credentials"

quote_credential_value() {
    printf '%s' "$1" | python3 -c 'import json, sys; print(json.dumps(sys.stdin.read()), end="")'
}

derive_host_from_uri() {
    python3 - "$1" <<'PY'
import sys
from urllib.parse import urlparse

uri = sys.argv[1].strip()
if not uri:
    print("", end="")
    raise SystemExit(0)

parsed = urlparse(uri)
print(parsed.hostname or "", end="")
PY
}

derive_port_from_uri() {
    python3 - "$1" <<'PY'
import sys
from urllib.parse import urlparse

uri = sys.argv[1].strip()
if not uri:
    print("", end="")
    raise SystemExit(0)

parsed = urlparse(uri)
if parsed.port:
    print(parsed.port, end="")
elif parsed.scheme == "https":
    print("443", end="")
elif parsed.scheme == "http":
    print("80", end="")
else:
    print("", end="")
PY
}

echo "=== Splunk Credentials Setup ==="
echo ""
echo "Credentials will be saved to: ${CRED_FILE}"
echo "(This file is gitignored and will not be committed.)"
echo ""

if [[ -f "${CRED_FILE}" ]]; then
    echo "Credential file already exists."
    read -rp "Overwrite it? [y/N]: " confirm
    case "${confirm}" in
        [yY]|[yY][eE][sS]) ;;
        *) echo "Keeping existing file."; exit 0 ;;
    esac
fi

echo ""
read -rp "Search-tier REST URI (optional; leave blank if this file is only for ACS or if you will set SPLUNK_URI per run): " splunk_uri

splunk_host="$(derive_host_from_uri "${splunk_uri}")"
splunk_mgmt_port="$(derive_port_from_uri "${splunk_uri}")"
if [[ -z "${splunk_mgmt_port}" ]]; then
    splunk_mgmt_port="8089"
fi

echo ""
read -rp "Search-tier admin username (leave blank to skip): " sp_user
sp_pass=""
if [[ -n "${sp_user}" ]]; then
    read -rsp "Search-tier admin password: " sp_pass
    echo ""
fi

splunk_ssh_host=""
splunk_ssh_port="22"
splunk_ssh_user="splunk"
splunk_ssh_pass=""
echo ""
read -rp "Add SSH staging settings for Enterprise installs? [y/N]: " add_ssh
if [[ "${add_ssh}" =~ ^[yY] ]]; then
    read -rp "SSH host: " splunk_ssh_host
    read -rp "SSH port (default: 22): " splunk_ssh_port_input
    splunk_ssh_port="${splunk_ssh_port_input:-22}"
    read -rp "SSH user (default: splunk): " splunk_ssh_user_input
    splunk_ssh_user="${splunk_ssh_user_input:-splunk}"
    read -rsp "SSH password: " splunk_ssh_pass
    echo ""
fi

splunk_cloud_stack=""
splunk_cloud_search_head=""
splunk_cloud_index_searchable_days="90"
acs_server="https://admin.splunk.com"
stack_username=""
stack_password=""
stack_token=""
stack_token_user=""

echo ""
read -rp "Add Splunk Cloud ACS settings? [y/N]: " add_cloud
if [[ "${add_cloud}" =~ ^[yY] ]]; then
    read -rp "Splunk Cloud stack name (URL prefix, required for ACS): " splunk_cloud_stack
    read -rp "Target specific search head prefix (optional): " splunk_cloud_search_head
    read -rp "ACS server URL (default: https://admin.splunk.com): " acs_server_input
    acs_server="${acs_server_input:-https://admin.splunk.com}"
    read -rp "Default searchable days for ACS-created indexes (default: 90): " searchable_days_input
    splunk_cloud_index_searchable_days="${searchable_days_input:-90}"

    echo ""
    echo "ACS authentication setup:"
    echo "  1) Skip for now"
    echo "  2) Store an existing stack token"
    echo "  3) Store stack-local username/password so ACS CLI can create a token"
    read -rp "Choose [1/2/3]: " acs_auth_choice
    case "${acs_auth_choice}" in
        ""|1)
            ;;
        2)
            read -rsp "STACK_TOKEN: " stack_token
            echo ""
            ;;
        3)
            read -rp "STACK_USERNAME: " stack_username
            read -rsp "STACK_PASSWORD: " stack_password
            echo ""
            read -rp "STACK_TOKEN_USER: " stack_token_user
            ;;
        *)
            echo "Unknown ACS authentication choice '${acs_auth_choice}'."
            exit 1
            ;;
    esac
fi

echo ""
read -rp "Do you also want to add Splunkbase / splunk.com credentials? [y/N]: " add_sb
sb_user=""
sb_pass=""
splunk_com_user=""
splunk_com_pass=""
if [[ "${add_sb}" =~ ^[yY] ]]; then
    read -rp "Splunkbase / splunk.com username: " sb_user
    read -rsp "Splunkbase / splunk.com password: " sb_pass
    echo ""

    read -rp "Store separate Splunk.com credentials for ACS app operations? [y/N]: " add_explicit_splunk_com
    if [[ "${add_explicit_splunk_com}" =~ ^[yY] ]]; then
        read -rp "SPLUNK_USERNAME: " splunk_com_user
        read -rsp "SPLUNK_PASSWORD: " splunk_com_pass
        echo ""
    fi
fi

splunk_host_q=$(quote_credential_value "${splunk_host}")
splunk_mgmt_port_q=$(quote_credential_value "${splunk_mgmt_port}")
splunk_uri_q=$(quote_credential_value "${splunk_uri}")
sp_user_q=$(quote_credential_value "${sp_user}")
sp_pass_q=$(quote_credential_value "${sp_pass}")
splunk_ssh_host_q=$(quote_credential_value "${splunk_ssh_host}")
splunk_ssh_port_q=$(quote_credential_value "${splunk_ssh_port}")
splunk_ssh_user_q=$(quote_credential_value "${splunk_ssh_user}")
splunk_ssh_pass_q=$(quote_credential_value "${splunk_ssh_pass}")
splunk_cloud_stack_q=$(quote_credential_value "${splunk_cloud_stack}")
splunk_cloud_search_head_q=$(quote_credential_value "${splunk_cloud_search_head}")
splunk_cloud_index_searchable_days_q=$(quote_credential_value "${splunk_cloud_index_searchable_days}")
acs_server_q=$(quote_credential_value "${acs_server}")
stack_username_q=$(quote_credential_value "${stack_username}")
stack_password_q=$(quote_credential_value "${stack_password}")
stack_token_q=$(quote_credential_value "${stack_token}")
stack_token_user_q=$(quote_credential_value "${stack_token_user}")
sb_user_q=$(quote_credential_value "${sb_user}")
sb_pass_q=$(quote_credential_value "${sb_pass}")
splunk_com_user_q=$(quote_credential_value "${splunk_com_user}")
splunk_com_pass_q=$(quote_credential_value "${splunk_com_pass}")

cat > "${CRED_FILE}" <<EOF
# Splunk credential file — chmod 600
# Used by skill scripts for REST API, ACS, and Splunkbase authentication.
# Do NOT commit this file to version control.
# Values are stored as literal strings. Shell expressions are not executed.
SPLUNK_HOST=${splunk_host_q}
SPLUNK_MGMT_PORT=${splunk_mgmt_port_q}
SPLUNK_URI=${splunk_uri_q}
SPLUNK_USER=${sp_user_q}
SPLUNK_PASS=${sp_pass_q}
SPLUNK_SSH_HOST=${splunk_ssh_host_q}
SPLUNK_SSH_PORT=${splunk_ssh_port_q}
SPLUNK_SSH_USER=${splunk_ssh_user_q}
SPLUNK_SSH_PASS=${splunk_ssh_pass_q}
SPLUNK_CLOUD_STACK=${splunk_cloud_stack_q}
SPLUNK_CLOUD_SEARCH_HEAD=${splunk_cloud_search_head_q}
SPLUNK_CLOUD_INDEX_SEARCHABLE_DAYS=${splunk_cloud_index_searchable_days_q}
ACS_SERVER=${acs_server_q}
STACK_USERNAME=${stack_username_q}
STACK_PASSWORD=${stack_password_q}
STACK_TOKEN=${stack_token_q}
STACK_TOKEN_USER=${stack_token_user_q}
SB_USER=${sb_user_q}
SB_PASS=${sb_pass_q}
SPLUNK_USERNAME=${splunk_com_user_q}
SPLUNK_PASSWORD=${splunk_com_pass_q}
EOF

chmod 600 "${CRED_FILE}"

echo ""
echo "Credentials saved to ${CRED_FILE} (mode 600)"
echo "Scripts will read from this file automatically."
if [[ "${add_cloud}" =~ ^[yY] ]]; then
    echo "Cloud note: ACS app installs and index management use the ACS CLI, while app-specific TA setup still needs search-api access if you plan to configure the search tier over REST."
fi
if [[ "${add_cloud}" =~ ^[yY] && "${add_ssh}" =~ ^[yY] ]]; then
    echo "Hybrid note: because this file contains both Cloud and Enterprise targets, interactive scripts will prompt when a run is ambiguous. For non-interactive runs, you can override with SPLUNK_PLATFORM=cloud or SPLUNK_PLATFORM=enterprise."
fi
