#!/usr/bin/env bash
set -euo pipefail

SETUP_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SETUP_SCRIPT_DIR}/../../.." && pwd)"
CRED_FILE="${PROJECT_ROOT}/credentials"

quote_credential_value() {
    printf '%s' "$1" | python3 -c 'import json, sys; print(json.dumps(sys.stdin.read()), end="")'
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

read -rp "Splunk admin username: " sp_user
read -rsp "Splunk admin password: " sp_pass
echo ""

echo ""
read -rp "Do you also want to add Splunkbase (splunk.com) credentials? [y/N]: " add_sb
sb_user=""
sb_pass=""
if [[ "${add_sb}" =~ ^[yY] ]]; then
    read -rp "Splunkbase username: " sb_user
    read -rsp "Splunkbase password: " sb_pass
    echo ""
fi

sp_user_q=$(quote_credential_value "${sp_user}")
sp_pass_q=$(quote_credential_value "${sp_pass}")
sb_user_q=$(quote_credential_value "${sb_user}")
sb_pass_q=$(quote_credential_value "${sb_pass}")

cat > "${CRED_FILE}" <<EOF
# Splunk credential file — chmod 600
# Used by skill scripts for REST API authentication.
# Do NOT commit this file to version control.
# Values are stored as literal strings. Shell expressions are not executed.
SPLUNK_USER=${sp_user_q}
SPLUNK_PASS=${sp_pass_q}
SB_USER=${sb_user_q}
SB_PASS=${sb_pass_q}
EOF

chmod 600 "${CRED_FILE}"

echo ""
echo "Credentials saved to ${CRED_FILE} (mode 600)"
echo "Scripts will read from this file automatically."
