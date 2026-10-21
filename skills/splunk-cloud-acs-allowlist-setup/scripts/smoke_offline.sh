#!/usr/bin/env bash
# Offline smoke test for splunk-cloud-acs-allowlist-setup. Exercises the
# renderer with no live Splunk Cloud access and asserts every rendered file
# is well-formed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_OUT="$(mktemp -d)"
trap 'rm -rf "${TMP_OUT}"' EXIT

bash "${SCRIPT_DIR}/setup.sh" \
    --phase render \
    --output-dir "${TMP_OUT}" \
    --target-stack synthetic-stack \
    --features search-api,s2s,hec,acs \
    --search-api-subnets 198.51.100.0/24 \
    --s2s-subnets 198.51.100.0/24,203.0.113.0/24 \
    --hec-subnets 203.0.113.0/24 \
    --acs-subnets 198.51.100.10/32 \
    --allow-acs-lockout true \
    --emit-terraform true \
    >/dev/null

render_dir="${TMP_OUT}/allowlist"
required=(README.md metadata.json plan.json preflight.sh apply-ipv4.sh apply-ipv6.sh wait-for-ready.sh audit.sh terraform-snippets.tf)
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
PY

# CLI subcommand syntax must use `describe` not `list`, and `ip-allowlist-v6`
# top-level group for IPv6 (per Splunk ACS CLI v2.17.0+ docs).
grep -q "CLI_GROUP='ip-allowlist'" "${render_dir}/apply-ipv4.sh" \
    || { echo "FAIL: apply-ipv4.sh must set CLI_GROUP='ip-allowlist'" >&2; exit 1; }
grep -q "CLI_GROUP='ip-allowlist-v6'" "${render_dir}/apply-ipv6.sh" \
    || { echo "FAIL: apply-ipv6.sh must set CLI_GROUP='ip-allowlist-v6'" >&2; exit 1; }
# Verify the executable helper command shape for IPv4 and IPv6 with a mocked
# ACS response. Malformed observations must fail closed.
ACS_TEST_LOG="${TMP_OUT}/acs-command.log"
export ACS_TEST_LOG
# shellcheck source=skills/shared/lib/acs_helpers.sh
source "${SCRIPT_DIR}/../../shared/lib/acs_helpers.sh"
acs_command() {
    printf '%s\n' "$*" >> "${ACS_TEST_LOG}"
    case "$1 $2 $3" in
        'ip-allowlist describe search-api') printf '[{"type":"http","response":"{\\"subnets\\":[\\"198.51.100.0/24\\"]}"}]' ;;
        'ip-allowlist-v6 describe search-api') printf '[{"type":"http","response":"{\\"subnets\\":[\\"2001:db8::/64\\"]}"}]' ;;
        *) return 1 ;;
    esac
}
[[ "$(acs_ipallowlist_describe search-api)" == '198.51.100.0/24' ]] \
    || { echo "FAIL: IPv4 describe did not parse the mocked response" >&2; exit 1; }
[[ "$(acs_ipallowlist_describe_v6 search-api)" == '2001:db8::/64' ]] \
    || { echo "FAIL: IPv6 describe did not parse the mocked response" >&2; exit 1; }
grep -qx 'ip-allowlist describe search-api' "${ACS_TEST_LOG}" \
    || { echo "FAIL: IPv4 helper must use describe" >&2; exit 1; }
grep -qx 'ip-allowlist-v6 describe search-api' "${ACS_TEST_LOG}" \
    || { echo "FAIL: IPv6 helper must use the top-level v6 describe" >&2; exit 1; }
acs_command() { printf '[{"type":"http","response":"{\\"unexpected\\":true}"}]'; }
if acs_ipallowlist_describe search-api >/dev/null 2>&1; then
    echo "FAIL: malformed allowlist response was accepted" >&2
    exit 1
fi
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

echo "PASS: splunk-cloud-acs-allowlist-setup offline smoke OK"
