#!/usr/bin/env bash
# Offline smoke test for splunk-enterprise-public-exposure-hardening.
#
# Exercises every renderer code path that does not require a live Splunk
# host — argparse, default-render, hec+s2s render, SVD-floor refusal,
# JSON dry-run. Runs in a sandboxed temp dir.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RENDERER="${SCRIPT_DIR}/render_assets.py"
SETUP="${SCRIPT_DIR}/setup.sh"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

failed=0
fail() { echo "FAIL: $1" >&2; failed=$((failed + 1)); }
ok()   { echo "OK:   $1"; }

# --- 1. argparse smoke
if python3 "$RENDERER" --help >/dev/null 2>&1; then
    ok "renderer --help"
else
    fail "renderer --help"
fi

if bash "$SETUP" --help >/dev/null 2>&1; then
    ok "setup.sh --help"
else
    fail "setup.sh --help"
fi

# --- 2. default render
if python3 "$RENDERER" \
    --output-dir "$tmp/single" \
    --public-fqdn splunk.example.com \
    --proxy-cidr 10.0.10.0/24 \
    >/dev/null 2>&1; then
    ok "default render"
else
    fail "default render"
fi

# --- 3. file count and structure
count="$(find "$tmp/single/public-exposure" -type f 2>/dev/null | wc -l | tr -d ' ')"
if [[ "$count" == "53" ]]; then
    ok "default render produced 53 files"
else
    fail "default render produced $count files (expected 53)"
fi

# --- 4. shc-with-hec-and-hf
if python3 "$RENDERER" \
    --output-dir "$tmp/full" \
    --topology shc-with-hec-and-hf \
    --public-fqdn splunk.example.com \
    --hec-fqdn hec.example.com \
    --proxy-cidr 10.0.10.0/24 \
    --indexer-cluster-cidr 10.0.20.0/24 \
    --bastion-cidr 10.0.30.0/24 \
    --enable-web true --enable-hec true --enable-s2s true \
    --hec-mtls true \
    >/dev/null 2>&1; then
    ok "shc-with-hec-and-hf render"
else
    fail "shc-with-hec-and-hf render"
fi

# --- 5. SVD-floor refusal
if python3 "$RENDERER" \
    --output-dir "$tmp/old" \
    --public-fqdn splunk.example.com \
    --proxy-cidr 10.0.10.0/24 \
    --splunk-version 9.4.5 \
    >/dev/null 2>"$tmp/svd-err"; then
    fail "SVD-floor refusal did not trigger"
else
    if grep -q "SVD floor" "$tmp/svd-err"; then
        ok "SVD-floor refusal"
    else
        fail "SVD-floor error message did not mention floor"
    fi
fi

# --- 6. dry-run JSON
if dryrun_out="$(python3 "$RENDERER" \
    --output-dir "$tmp/dry" \
    --public-fqdn splunk.example.com \
    --proxy-cidr 10.0.10.0/24 \
    --dry-run --json 2>&1)"; then
    if python3 -c "import json,sys; json.loads(sys.argv[1])" "$dryrun_out" 2>/dev/null; then
        ok "dry-run JSON parses"
    else
        fail "dry-run JSON did not parse"
    fi
else
    fail "dry-run JSON command failed"
fi

# --- 7. setup.sh apply requires --accept-public-exposure
# Note: the shared log() helper writes to stdout, so we capture both streams.
if bash "$SETUP" \
    --phase apply \
    --output-dir "$tmp/apply" \
    --public-fqdn splunk.example.com \
    --proxy-cidr 10.0.10.0/24 \
    >"$tmp/apply-out" 2>&1; then
    fail "setup.sh apply did not refuse without --accept-public-exposure"
else
    if grep -q "accept-public-exposure" "$tmp/apply-out"; then
        ok "setup.sh apply refuses without --accept-public-exposure"
    else
        fail "setup.sh apply refusal message did not mention accept flag"
    fi
fi

# --- 8. rendered shell scripts pass bash -n
shell_failed=0
while IFS= read -r script; do
    if ! bash -n "$script" 2>/dev/null; then
        fail "rendered script syntax error: $script"
        shell_failed=1
    fi
done < <(find "$tmp/full/public-exposure" -name '*.sh' 2>/dev/null)
if [[ "$shell_failed" == "0" ]]; then
    ok "all rendered shell scripts pass bash -n"
fi

# --- 9. confirm web.conf does NOT contain non-existent settings
web_conf="$tmp/single/public-exposure/splunk/apps/000_public_exposure_hardening/default/web.conf"
forbidden_settings=(
    "customHttpHeaders"
    "httpd_protect_login_csrf"
    "cookie_csrf"
    "splunkdConnectionHost"
    "serverRoot"
    "tools.proxy.local"
    "trustedProxiesList"
    "splunkweb.cherrypy.tools.csrf.on"
)
forbid_failed=0
for setting in "${forbidden_settings[@]}"; do
    # match only when the setting appears as a config key, not in a comment.
    # The setting should NOT appear at the start of a line followed by '='.
    if grep -E "^[[:space:]]*${setting}[[:space:]]*=" "$web_conf" >/dev/null 2>&1; then
        fail "web.conf references non-existent setting: $setting"
        forbid_failed=1
    fi
done
if [[ "$forbid_failed" == "0" ]]; then
    ok "web.conf does not reference non-existent settings"
fi

# --- 10. confirm no secret value patterns in any rendered file
secret_failed=0
while IFS= read -r f; do
    # PEM private key block
    if grep -q -- '-----BEGIN .*PRIVATE KEY-----' "$f" 2>/dev/null; then
        fail "rendered file contains a PRIVATE KEY block: $f"
        secret_failed=1
    fi
done < <(find "$tmp/full/public-exposure" -type f 2>/dev/null)
if [[ "$secret_failed" == "0" ]]; then
    ok "no PEM private key blocks in rendered output"
fi

# --- 11. metadata.json is valid JSON and records non-secret config only
meta="$tmp/full/public-exposure/metadata.json"
if python3 -c "import json; data=json.load(open('$meta'))" 2>/dev/null; then
    ok "metadata.json is valid JSON"
else
    fail "metadata.json is not valid JSON"
fi

if grep -E '"password"|"pass4SymmKey"|"token"' "$meta" >/dev/null 2>&1; then
    fail "metadata.json appears to contain a secret value"
else
    ok "metadata.json contains only non-secret keys"
fi

# --- 12. props.conf ships SVD-2026-0302 mitigation
props="$tmp/single/public-exposure/splunk/apps/000_public_exposure_hardening/default/props.conf"
if grep -q '^unarchive_cmd_start_mode = direct' "$props"; then
    ok "props.conf has SVD-2026-0302 mitigation (unarchive_cmd_start_mode=direct)"
else
    fail "props.conf missing unarchive_cmd_start_mode=direct"
fi

# --- 13. server.conf has allowed_unarchive_commands and [deployment]
server_conf="$tmp/full/public-exposure/splunk/apps/000_public_exposure_hardening/default/server.conf"
if grep -q '^allowed_unarchive_commands' "$server_conf"; then
    ok "server.conf has allowed_unarchive_commands key"
else
    fail "server.conf missing allowed_unarchive_commands"
fi
if grep -q '^\[deployment\]' "$server_conf"; then
    ok "server.conf has [deployment] stanza for SHC topologies"
else
    fail "server.conf missing [deployment] stanza"
fi

# --- 14. authentication.conf SAML hardening
# default render doesn't enable SAML; full topology might not either.
# Render a SAML topology specifically.
saml_dir="$tmp/saml"
python3 "$RENDERER" \
    --output-dir "$saml_dir" \
    --public-fqdn splunk.example.com \
    --proxy-cidr 10.0.10.0/24 \
    --auth-mode saml \
    --saml-idp-metadata-path /tmp/idp.xml \
    >/dev/null 2>&1
saml_auth="$saml_dir/public-exposure/splunk/apps/000_public_exposure_hardening/default/authentication.conf"
if grep -q '^allowPartialSignatures = false' "$saml_auth" && \
   grep -q '^attributeQueryRequestSigned = true' "$saml_auth" && \
   grep -q '^attributeQueryResponseSigned = true' "$saml_auth"; then
    ok "authentication.conf SAML stanza has XSW-hardening flags"
else
    fail "authentication.conf SAML stanza missing XSW-hardening flags"
fi

# --- 15. FIPS opt-in renders splunk-launch.conf with SPLUNK_FIPS=1
fips_dir="$tmp/fips"
python3 "$RENDERER" \
    --output-dir "$fips_dir" \
    --public-fqdn splunk.example.com \
    --proxy-cidr 10.0.10.0/24 \
    --enable-fips true \
    >/dev/null 2>&1
fips_launch="$fips_dir/public-exposure/splunk/apps/000_public_exposure_hardening/default/splunk-launch.conf"
if grep -q '^SPLUNK_FIPS=1' "$fips_launch" && \
   grep -q '^SPLUNK_FIPS_VERSION=140-3' "$fips_launch"; then
    ok "FIPS opt-in renders SPLUNK_FIPS=1 + SPLUNK_FIPS_VERSION=140-3"
else
    fail "FIPS opt-in did not produce expected splunk-launch.conf"
fi

# Default (no FIPS) splunk-launch.conf must NOT contain SPLUNK_FIPS=1.
default_launch="$tmp/single/public-exposure/splunk/apps/000_public_exposure_hardening/default/splunk-launch.conf"
if grep -q '^SPLUNK_FIPS=1' "$default_launch"; then
    fail "default render leaks SPLUNK_FIPS=1 (should be gated on --enable-fips)"
else
    ok "default render does not enable FIPS"
fi

# --- 16. proxy templates have sensitive-path denies
nginx_web="$tmp/full/public-exposure/proxy/nginx/splunk-web.conf"
deny_failed=0
for pattern in 'services/apps' 'services/configs/conf-passwords' 'services/data/inputs/oneshot' 'account/insecurelogin' 'debug/'; do
    if ! grep -F "$pattern" "$nginx_web" >/dev/null 2>&1; then
        fail "nginx splunk-web.conf missing deny for pattern: $pattern"
        deny_failed=1
    fi
done
if [[ "$deny_failed" == "0" ]]; then
    ok "nginx splunk-web.conf denies sensitive paths"
fi

# --- 17. proxy strips ANSI escape codes (literal \x1b / \x07 in nginx regex)
if grep -F '\x1b' "$nginx_web" >/dev/null 2>&1 && grep -F '\x07' "$nginx_web" >/dev/null 2>&1; then
    ok "nginx splunk-web.conf rejects ANSI/BEL in headers/URI"
else
    fail "nginx splunk-web.conf missing ANSI escape rejection"
fi

# --- 18. rotate-pass4symmkey.sh covers all 6 stanzas
rotate="$tmp/full/public-exposure/splunk/rotate-pass4symmkey.sh"
rotate_failed=0
for stanza in '\[general\]' '\[clustering\]' '\[shclustering\]' '\[indexer_discovery\]' '\[license_master\]' '\[deployment\]'; do
    if ! grep -q "$stanza" "$rotate"; then
        fail "rotate-pass4symmkey.sh missing stanza $stanza"
        rotate_failed=1
    fi
done
if [[ "$rotate_failed" == "0" ]]; then
    ok "rotate-pass4symmkey.sh covers all six pass4SymmKey stanzas"
fi

# --- 19. LDAP rendering — correct spec syntax
ldap_dir="$tmp/ldap"
python3 "$RENDERER" \
    --output-dir "$ldap_dir" \
    --public-fqdn splunk.example.com \
    --proxy-cidr 10.0.10.0/24 \
    --auth-mode ldap \
    --ldap-host ad.example.com \
    --ldap-bind-dn "cn=svc_splunk,ou=Service,dc=example,dc=com" \
    --ldap-bind-password-file /tmp/ldap.pwd \
    --ldap-user-base-dn "ou=Users,dc=example,dc=com" \
    --ldap-group-base-dn "ou=Groups,dc=example,dc=com" \
    --ldap-public-reader-group "SplunkPublicReaders" \
    >/dev/null 2>&1
ldap_auth="$ldap_dir/public-exposure/splunk/apps/000_public_exposure_hardening/default/authentication.conf"
if grep -q '^authType = LDAP' "$ldap_auth" \
   && grep -q '^\[ldaphost\]$' "$ldap_auth" \
   && grep -q '^\[roleMap_ldaphost\]$' "$ldap_auth" \
   && grep -q '^role_public_reader = SplunkPublicReaders$' "$ldap_auth" \
   && grep -q '^anonymous_referrals = 0' "$ldap_auth" \
   && grep -q '^sizelimit = 1000' "$ldap_auth"; then
    ok "LDAP rendering: authType + strategy + roleMap (Splunk-role-on-LEFT) + anon-referrals=0 + lowercase sizelimit"
else
    fail "LDAP rendering missing one of: authType=LDAP, [ldaphost], [roleMap_ldaphost], role_public_reader=, anonymous_referrals=0, sizelimit"
fi

# --- 20. LDAP stanza must NOT contain sslVersions / cipherSuite / ecdhCurves
# (those keys do not apply to LDAP per spec; LDAP TLS lives in ldap.conf).
strategy_block="$(awk '/^\[ldaphost\]$/,/^\[roleMap_/' "$ldap_auth")"
if grep -q '^sslVersions' <<<"$strategy_block" \
   || grep -q '^cipherSuite' <<<"$strategy_block" \
   || grep -q '^ecdhCurves' <<<"$strategy_block"; then
    fail "LDAP strategy stanza must NOT contain sslVersions/cipherSuite/ecdhCurves"
else
    ok "LDAP strategy stanza correctly omits sslVersions / cipherSuite / ecdhCurves"
fi

# --- 21. openldap-ldap.conf.example exists and pins TLS_PROTOCOL_MIN 3.3
openldap_stub="$ldap_dir/public-exposure/splunk/apps/000_public_exposure_hardening/default/openldap-ldap.conf.example"
if grep -q '^TLS_REQCERT       demand' "$openldap_stub" \
   && grep -q '^TLS_PROTOCOL_MIN  3.3' "$openldap_stub"; then
    ok "openldap-ldap.conf.example pins TLS_REQCERT demand + TLS_PROTOCOL_MIN 3.3"
else
    fail "openldap-ldap.conf.example missing TLS hardening lines"
fi

# --- 22. LDAP cleartext refusal
if python3 "$RENDERER" \
    --output-dir "$tmp/ldap-cleartext" \
    --public-fqdn splunk.example.com \
    --proxy-cidr 10.0.10.0/24 \
    --auth-mode ldap \
    --ldap-host ad.example.com \
    --ldap-ssl-enabled false \
    --ldap-bind-dn "cn=svc,dc=example,dc=com" \
    --ldap-bind-password-file /tmp/ldap.pwd \
    --ldap-user-base-dn "ou=Users,dc=example,dc=com" \
    --ldap-group-base-dn "ou=Groups,dc=example,dc=com" \
    >/dev/null 2>"$tmp/ldap-cleartext-err"; then
    fail "LDAP cleartext rendering succeeded without --allow-cleartext-ldap"
else
    if grep -q "allow-cleartext-ldap" "$tmp/ldap-cleartext-err"; then
        ok "LDAP cleartext refused without --allow-cleartext-ldap ack"
    else
        fail "LDAP cleartext refusal message did not mention the ack flag"
    fi
fi

# --- 23. LDAP timelimit > 30 refused
if python3 "$RENDERER" \
    --output-dir "$tmp/ldap-tl" \
    --public-fqdn splunk.example.com \
    --proxy-cidr 10.0.10.0/24 \
    --auth-mode ldap \
    --ldap-host ad.example.com \
    --ldap-bind-dn "cn=svc,dc=example,dc=com" \
    --ldap-bind-password-file /tmp/ldap.pwd \
    --ldap-user-base-dn "ou=Users,dc=example,dc=com" \
    --ldap-group-base-dn "ou=Groups,dc=example,dc=com" \
    --ldap-time-limit 60 \
    >/dev/null 2>"$tmp/ldap-tl-err"; then
    fail "LDAP --ldap-time-limit > 30 was accepted"
else
    if grep -q "time-limit" "$tmp/ldap-tl-err"; then
        ok "LDAP --ldap-time-limit > 30 refused per spec hard cap"
    else
        fail "LDAP timelimit refusal message did not mention --ldap-time-limit"
    fi
fi

# --- 24. Federation rotate helper present and reads from a file
fed_rotate="$tmp/full/public-exposure/splunk/rotate-federation-service-account.sh"
if [[ -x "$fed_rotate" ]] \
   && grep -q 'federated' "$fed_rotate" \
   && grep -q 'service_account' "$fed_rotate" \
   && grep -q 'new_password_file' "$fed_rotate" \
   && grep -q 'password-file' "$fed_rotate"; then
    ok "rotate-federation-service-account.sh present and uses --password-file"
else
    fail "rotate-federation-service-account.sh missing or doesn't use file-based password"
fi

# --- 25. Federation helper does NOT actively use pass4SymmKey for federation.
# The script's usage block may reference 'rotate-pass4symmkey.sh' (the OTHER
# helper) by filename; that's fine. What we forbid is the script actually
# calling splunk edit cluster-config / shcluster-config or writing
# pass4SymmKey itself.
if grep -E '(splunk\s+edit\s+(cluster|shcluster)-config|pass4SymmKey\s*=)' "$fed_rotate" >/dev/null 2>&1; then
    fail "rotate-federation-service-account.sh appears to invoke pass4SymmKey rotation"
else
    ok "rotate-federation-service-account.sh does not invoke pass4SymmKey rotation"
fi

# --- 26. SG handoff doc exists and references prod.spacebridge.spl.mobi
REPO_ROOT_REFS="$(dirname "$SCRIPT_DIR")/references"
sg_doc="$REPO_ROOT_REFS/secure-gateway-handoff.md"
if grep -q 'prod.spacebridge.spl.mobi' "$sg_doc"; then
    ok "secure-gateway-handoff.md references prod.spacebridge.spl.mobi"
else
    fail "secure-gateway-handoff.md missing prod.spacebridge.spl.mobi"
fi
if grep -qi 'spacebridge\.splunk\.com' "$sg_doc"; then
    fail "secure-gateway-handoff.md references the WRONG spacebridge URL (spacebridge.splunk.com)"
else
    ok "secure-gateway-handoff.md does not reference the wrong spacebridge URL"
fi
if grep -q 'ECC' "$sg_doc" && grep -qi 'libsodium\|ecies' "$sg_doc"; then
    ok "secure-gateway-handoff.md describes ECC + Libsodium ECIES E2E auth"
else
    fail "secure-gateway-handoff.md missing E2E auth description"
fi

# --- 27. Federation provider hardening doc exists and documents the
#        service-account auth (NOT pass4SymmKey)
fed_doc="$REPO_ROOT_REFS/federated-search-provider-hardening.md"
if grep -qi 'service.account' "$fed_doc" \
   && grep -qi 'NOT.*pass4SymmKey\|not.*pass4SymmKey\|does NOT' "$fed_doc"; then
    ok "federated-search-provider-hardening.md correctly says federation is NOT pass4SymmKey"
else
    fail "federated-search-provider-hardening.md missing the 'NOT pass4SymmKey' correction"
fi

# --- 28. SVD-floor JSON includes the SG floor
floor_json="$REPO_ROOT_REFS/cve-svd-floor.json"
if python3 -c "
import json, sys
d = json.load(open('$floor_json'))
assert 'splunk_secure_gateway' in d, 'missing splunk_secure_gateway top-level key'
sg = d['splunk_secure_gateway']
for branch in ('3.9', '3.8', '3.7'):
    assert branch in sg, f'missing {branch} branch'
print('OK')
" 2>/dev/null; then
    ok "cve-svd-floor.json includes splunk_secure_gateway floor with 3.9/3.8/3.7 branches"
else
    fail "cve-svd-floor.json missing splunk_secure_gateway floor"
fi

# --- 29. premium-apps overlay JSON validates and pins versions
overlay_json="$REPO_ROOT_REFS/premium-apps-capability-overlay.json"
if python3 -c "
import json, sys
d = json.load(open('$overlay_json'))
assert 'tier_a' in d and 'tier_b' in d
for app, body in d['tier_a'].items():
    assert 'verified_version' in body, f'{app} missing verified_version'
    assert 'source_url' in body, f'{app} missing source_url'
print('OK')
" 2>/dev/null; then
    ok "premium-apps-capability-overlay.json validates with pinned versions for all Tier-A apps"
else
    fail "premium-apps-capability-overlay.json invalid or missing pinned versions"
fi

# --- 30. list_inputs is in ES 8.4 must_not_remove
if python3 -c "
import json, sys
d = json.load(open('$overlay_json'))
es = d['tier_a'].get('SplunkEnterpriseSecuritySuite', {})
assert 'list_inputs' in es.get('must_not_remove', []), 'list_inputs not flagged'
print('OK')
" 2>/dev/null; then
    ok "premium-apps overlay flags list_inputs as must_not_remove for ES 8.4"
else
    fail "premium-apps overlay missing list_inputs in ES 8.4 must_not_remove"
fi

if [[ "$failed" -gt 0 ]]; then
    echo "SMOKE FAILED: $failed check(s) failed." >&2
    exit 1
fi

echo "SMOKE PASSED."
