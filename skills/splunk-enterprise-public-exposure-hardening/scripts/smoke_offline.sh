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
if [[ "$count" == "51" ]]; then
    ok "default render produced 51 files"
else
    fail "default render produced $count files (expected 51)"
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

if [[ "$failed" -gt 0 ]]; then
    echo "SMOKE FAILED: $failed check(s) failed." >&2
    exit 1
fi

echo "SMOKE PASSED."
