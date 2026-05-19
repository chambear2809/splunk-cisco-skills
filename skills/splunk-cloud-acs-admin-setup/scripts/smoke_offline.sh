#!/usr/bin/env bash
# Offline smoke test for splunk-cloud-acs-admin-setup. Exercises the
# renderer with no live Splunk Cloud access and asserts every rendered file
# is well-formed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_OUT="$(mktemp -d)"
trap 'rm -rf "${TMP_OUT}"' EXIT
PLAN_FILE="${TMP_OUT}/admin-plan.json"

cat > "${PLAN_FILE}" <<'JSON'
{
  "indexes": [
    {
      "name": "cisco_netops",
      "datatype": "event",
      "searchableDays": 90,
      "maxDataSizeMB": 0,
      "selfStorageBucketPath": "s3://example-bucket/splunk"
    }
  ],
  "hec_tokens": [
    {
      "name": "cisco_netops_hec",
      "defaultIndex": "cisco_netops",
      "allowedIndexes": ["cisco_netops"],
      "defaultSourceType": "cisco:test"
    }
  ],
  "roles": [
    {
      "name": "cisco_netops_role",
      "capabilities": ["search"],
      "srchIndexesAllowed": ["cisco_netops"],
      "srchIndexesDefault": ["cisco_netops"]
    }
  ],
  "users": [
    {
      "name": "cisco_netops_user",
      "roles": ["cisco_netops_role"],
      "passwordFile": "/tmp/not-read-by-renderer"
    }
  ],
  "app_permissions": [
    {
      "name": "search",
      "read": ["user", "power", "admin"],
      "write": ["admin"]
    }
  ],
  "outbound_ports": [
    {
      "port": 8089,
      "family": "ipv4",
      "subnets": ["198.51.100.10/32"]
    }
  ],
  "ddss_self_storage_locations": [
    {
      "bucketName": "example-bucket",
      "title": "Example DDSS",
      "folder": "splunk"
    }
  ],
  "limits": [
    {
      "stanza": "subsearch",
      "settings": {
        "maxout": "50000"
      }
    }
  ],
  "maintenance_windows": {
    "preferencesFile": "/tmp/change-freezes.json"
  },
  "private_connectivity": [
    {
      "customerAccountIds": ["112233445566"],
      "features": ["ingest", "search"]
    }
  ],
  "restarts": {
    "restartIfRequired": true
  }
}
JSON

bash "${SCRIPT_DIR}/setup.sh" \
    --phase render \
    --output-dir "${TMP_OUT}" \
    --admin-plan-file "${PLAN_FILE}" \
    --features search-api,s2s,hec,acs \
    --search-api-subnets 198.51.100.0/24 \
    --s2s-subnets 198.51.100.0/24,203.0.113.0/24 \
    --hec-subnets 203.0.113.0/24 \
    --acs-subnets 198.51.100.10/32 \
    --allow-acs-lockout true \
    --emit-terraform true \
    >/dev/null

render_dir="${TMP_OUT}/acs-admin"
required=(README.md admin-commands.sh apply-admin-plan.sh metadata.json plan.json preflight.sh apply-ipv4.sh apply-ipv6.sh inventory.sh private-connectivity-rest.sh wait-for-ready.sh audit.sh terraform-snippets.tf)
for file in "${required[@]}"; do
    [[ -f "${render_dir}/${file}" ]] || { echo "FAIL: missing ${file}" >&2; exit 1; }
done

# Every shell script must be syntactically valid.
for script in "${render_dir}"/*.sh; do
    bash -n "${script}" || { echo "FAIL: shell syntax error in ${script}" >&2; exit 1; }
done

# plan.json must parse and contain expected features.
python3 - "${render_dir}/plan.json" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1]))
expected = {"search-api", "s2s", "hec", "acs"}
got = set(plan["features"].keys())
assert got == expected, f"unexpected features {got!r}, want {expected!r}"
assert plan["allow_acs_lockout"] is True
assert plan["features"]["search-api"]["ipv4"] == ["198.51.100.0/24"]
assert plan["operations"]["indexes"][0]["selfStorageBucketPath"] == "s3://example-bucket/splunk"
assert plan["operations"]["private_connectivity"][0]["customerAccountIds"] == ["112233445566"]
assert plan["operations"]["users"][0]["applySupported"] is False
assert "license" in plan["modules"]
assert "observability" in plan["modules"]
PY

# CLI subcommand syntax must use `describe` not `list`, and `ip-allowlist-v6`
# top-level group for IPv6 (per Splunk ACS CLI v2.17.0+ docs).
grep -q "CLI_GROUP='ip-allowlist'" "${render_dir}/apply-ipv4.sh" \
    || { echo "FAIL: apply-ipv4.sh must set CLI_GROUP='ip-allowlist'" >&2; exit 1; }
grep -q "CLI_GROUP='ip-allowlist-v6'" "${render_dir}/apply-ipv6.sh" \
    || { echo "FAIL: apply-ipv6.sh must set CLI_GROUP='ip-allowlist-v6'" >&2; exit 1; }
# shellcheck disable=SC2016
grep -q '"\${CLI_GROUP}" describe' "${render_dir}/apply-ipv4.sh" \
    || { echo "FAIL: apply-ipv4.sh must call CLI_GROUP describe (not list)" >&2; exit 1; }
grep -q 'ip-allowlist-v6 describe' "${render_dir}/audit.sh" \
    || { echo "FAIL: audit.sh must use 'ip-allowlist-v6 describe' for IPv6" >&2; exit 1; }
# Live state must NOT use the old (invented) `ip-allowlist list-v6/create-v6/delete-v6` subcommand names
# (they were superseded by the documented `ip-allowlist-v6 describe/create/delete` group).
if grep -E 'ip-allowlist (list-v6|create-v6|delete-v6)' "${render_dir}/"*.sh >/dev/null 2>&1; then
    echo "FAIL: rendered scripts must not use 'ip-allowlist {list,create,delete}-v6' (use 'ip-allowlist-v6 {describe,create,delete}')" >&2
    exit 1
fi

# Lock-out preflight must use Python ipaddress for CIDR containment, not naive grep.
grep -q 'import ipaddress' "${render_dir}/preflight.sh" \
    || { echo "FAIL: preflight.sh must use ipaddress module for CIDR containment" >&2; exit 1; }

# Terraform resource type must be the documented plural `scp_ip_allowlists`.
grep -q 'scp_ip_allowlists' "${render_dir}/terraform-snippets.tf" \
    || { echo "FAIL: terraform-snippets.tf must use scp_ip_allowlists (plural)" >&2; exit 1; }
if grep -q 'scp_ip_allowlist_v6' "${render_dir}/terraform-snippets.tf"; then
    echo "FAIL: terraform-snippets.tf must NOT use invented scp_ip_allowlist_v6 type" >&2
    exit 1
fi

grep -q 'ACCEPT_ACS_ADMIN_MUTATION' "${render_dir}/apply-admin-plan.sh" \
    || { echo "FAIL: apply-admin-plan.sh must require ACCEPT_ACS_ADMIN_MUTATION" >&2; exit 1; }
grep -q 'private-connectivity' "${render_dir}/private-connectivity-rest.sh" \
    || { echo "FAIL: private-connectivity-rest.sh must use ACS private-connectivity REST endpoint" >&2; exit 1; }
grep -q '"feature": item\["features"\]' "${render_dir}/private-connectivity-rest.sh" \
    || { echo "FAIL: private-connectivity-rest.sh must send the documented feature array" >&2; exit 1; }
grep -q 'acs_command license' "${render_dir}/inventory.sh" \
    || { echo "FAIL: inventory.sh must include acs license inventory" >&2; exit 1; }
grep -q 'observability-handoff.json' "${render_dir}/inventory.sh" \
    || { echo "FAIL: inventory.sh must include observability handoff coverage" >&2; exit 1; }
grep -q 'hec-token create' "${render_dir}/admin-commands.sh" \
    || { echo "FAIL: admin-commands.sh must include HEC token command review" >&2; exit 1; }

echo "PASS: splunk-cloud-acs-admin-setup offline smoke OK"
