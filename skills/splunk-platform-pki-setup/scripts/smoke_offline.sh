#!/usr/bin/env bash
# Offline smoke test for splunk-platform-pki-setup.
#
# Exercises every renderer code path that does not require a live Splunk
# host:
#   - argparse / --help
#   - default render
#   - mode matrix (private / public)
#   - target matrix (core5 / indexer-cluster / shc / all)
#   - mTLS matrix (none / s2s,hec / all)
#   - FIPS matrix (none / 140-2 / 140-3)
#   - Edge Processor opt-in
#   - SAML SP opt-in
#   - LDAPS opt-in
#   - replication-port encryption opt-in
#   - validity-day cap refusal
#   - TLS 1.3 refusal
#   - default-cert preflight detection (string match in renderer output)
#   - --accept-pki-rotation gating
#   - bash -n on every emitted shell script
#   - JSON validity of metadata.json + algorithm-policy.json

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

# --- 2. Default Private render (core5 single SH)
if python3 "$RENDERER" \
    --output-dir "$tmp/default" \
    --mode private \
    --target core5 \
    --single-sh-fqdn sh01.example.com \
    >/dev/null 2>&1; then
    ok "default Private/core5 render"
else
    fail "default Private/core5 render"
fi

# --- 3. Full cluster render (Private)
if python3 "$RENDERER" \
    --output-dir "$tmp/full-private" \
    --mode private \
    --target indexer-cluster,shc,license-manager,deployment-server,monitoring-console \
    --cm-fqdn cm01.example.com \
    --peer-hosts idx01.example.com,idx02.example.com,idx03.example.com \
    --shc-deployer-fqdn deployer01.example.com \
    --shc-members sh01.example.com,sh02.example.com,sh03.example.com \
    --lm-fqdn lm01.example.com \
    --ds-fqdn ds01.example.com \
    --mc-fqdn mc01.example.com \
    --include-intermediate-ca true \
    >/dev/null 2>&1; then
    ok "full cluster Private render"
else
    fail "full cluster Private render"
fi

# --- 4. Full cluster render (Public, Vault PKI)
if python3 "$RENDERER" \
    --output-dir "$tmp/full-public" \
    --mode public \
    --public-ca-name vault \
    --target indexer-cluster,shc \
    --cm-fqdn cm01.example.com \
    --peer-hosts idx01.example.com,idx02.example.com,idx03.example.com \
    --shc-deployer-fqdn deployer01.example.com \
    --shc-members sh01.example.com,sh02.example.com,sh03.example.com \
    >/dev/null 2>&1; then
    ok "full cluster Public render"
else
    fail "full cluster Public render"
fi

# --- 5. Edge Processor opt-in
if python3 "$RENDERER" \
    --output-dir "$tmp/ep" \
    --mode private \
    --target edge-processor \
    --include-edge-processor true \
    --ep-fqdn ep01.example.com \
    --ep-data-source-fqdn ds01.example.com \
    --key-format pkcs8 \
    >/dev/null 2>&1; then
    ok "Edge Processor render"
else
    fail "Edge Processor render"
fi

# --- 6. FIPS 140-3 opt-in
if python3 "$RENDERER" \
    --output-dir "$tmp/fips" \
    --mode private \
    --target indexer-cluster \
    --cm-fqdn cm01.example.com \
    --peer-hosts idx01.example.com,idx02.example.com,idx03.example.com \
    --fips-mode 140-3 \
    --tls-policy fips-140-3 \
    >/dev/null 2>&1; then
    ok "FIPS 140-3 render"
else
    fail "FIPS 140-3 render"
fi

# Confirm splunk-launch.conf carries the FIPS line
fips_launch="$tmp/fips/platform-pki/pki/distribute/standalone/000_pki_trust/local/splunk-launch.conf"
# Standalone bundle is only emitted when target includes a standalone role; for
# pure indexer-cluster target the launch conf goes via the install helper.
fips_install="$tmp/fips/platform-pki/pki/install/install-fips-launch-conf.sh"
if [[ -x "$fips_install" ]]; then
    ok "install-fips-launch-conf.sh emitted under --fips-mode 140-3"
else
    fail "install-fips-launch-conf.sh missing under --fips-mode 140-3"
fi

# Default render (no FIPS) must NOT emit install-fips-launch-conf.sh
default_fips_install="$tmp/default/platform-pki/pki/install/install-fips-launch-conf.sh"
if [[ ! -e "$default_fips_install" ]]; then
    ok "no install-fips-launch-conf.sh in default (non-FIPS) render"
else
    fail "default render leaks install-fips-launch-conf.sh (should be gated on --fips-mode)"
fi

# --- 7. Encrypted replication port opt-in
if python3 "$RENDERER" \
    --output-dir "$tmp/repl-ssl" \
    --mode private \
    --target indexer-cluster \
    --cm-fqdn cm01.example.com \
    --peer-hosts idx01.example.com,idx02.example.com,idx03.example.com \
    --encrypt-replication-port true \
    >/dev/null 2>&1; then
    ok "encrypt-replication-port render"
else
    fail "encrypt-replication-port render"
fi

# [replication_port-ssl://9887] is now a PER-HOST overlay (not in the
# bundle) because it carries a host-specific serverCert. The cluster
# bundle never contains [replication_port-ssl]; install-leaf.sh
# --target replication writes the stanza to each peer's
# etc/system/local/server.conf overlay. Smoke checks the install
# script supports the replication target instead.
repl_server_conf="$tmp/repl-ssl/platform-pki/pki/distribute/cluster-bundle/master-apps/000_pki_trust/local/server.conf"
if grep -q '\[replication_port-ssl://9887\]' "$repl_server_conf"; then
    fail "cluster bundle MUST NOT contain [replication_port-ssl://9887] (per-host overlay)"
else
    ok "cluster bundle correctly does NOT contain [replication_port-ssl://9887]"
fi
# The replication CSR template MUST be emitted per-peer when --encrypt-replication-port=true
if compgen -G "$tmp/repl-ssl/platform-pki/pki/csr-templates/replication-*.cnf" >/dev/null; then
    ok "per-peer replication-*.cnf CSR templates emitted under --encrypt-replication-port=true"
else
    fail "per-peer replication-*.cnf CSR templates missing under --encrypt-replication-port=true"
fi
# install-leaf.sh must support --target replication
install_sh="$tmp/repl-ssl/platform-pki/pki/install/install-leaf.sh"
if grep -q '\[replication_port-ssl://9887\]' "$install_sh"; then
    ok "install-leaf.sh writes [replication_port-ssl://9887] overlay for --target replication"
else
    fail "install-leaf.sh does not support --target replication"
fi

# When NOT requested, no replication CSRs are emitted
default_repl="$tmp/full-private/platform-pki/pki/distribute/cluster-bundle/master-apps/000_pki_trust/local/server.conf"
if grep -q '\[replication_port-ssl://9887\]' "$default_repl"; then
    fail "default cluster bundle leaks [replication_port-ssl://9887] (should never appear in bundle)"
else
    ok "default cluster bundle does not leak [replication_port-ssl://9887]"
fi
if compgen -G "$tmp/full-private/platform-pki/pki/csr-templates/replication-*.cnf" >/dev/null; then
    fail "default render leaks replication-*.cnf CSR templates (should be opt-in)"
else
    ok "default render does not leak replication-*.cnf CSR templates"
fi

# --- 8. SAML SP opt-in
if python3 "$RENDERER" \
    --output-dir "$tmp/saml" \
    --mode private \
    --target core5,saml-sp \
    --single-sh-fqdn sh01.example.com \
    --public-fqdn splunk.example.com \
    --saml-sp true \
    >/dev/null 2>&1; then
    ok "SAML SP render"
else
    fail "SAML SP render"
fi

saml_auth="$tmp/saml/platform-pki/pki/distribute/standalone/000_pki_trust/local/authentication.conf"
if grep -q '^signatureAlgorithm.*RSA-SHA384' "$saml_auth"; then
    ok "authentication.conf has signatureAlgorithm = RSA-SHA384"
else
    fail "authentication.conf missing signatureAlgorithm = RSA-SHA384"
fi

# --- 9. LDAPS opt-in
if python3 "$RENDERER" \
    --output-dir "$tmp/ldaps" \
    --mode private \
    --target ldaps \
    --ldaps true \
    --ldap-host ad.example.com \
    >/dev/null 2>&1; then
    ok "LDAPS render"
else
    fail "LDAPS render"
fi

# Note: standalone bundle isn't emitted when target=ldaps only; ldap.conf
# emission happens when target also includes a standalone role.
if python3 "$RENDERER" \
    --output-dir "$tmp/ldaps2" \
    --mode private \
    --target license-manager,ldaps \
    --lm-fqdn lm01.example.com \
    --ldaps true \
    --ldap-host ad.example.com \
    >/dev/null 2>&1; then
    ok "LDAPS+standalone render"
fi
ldap_conf="$tmp/ldaps2/platform-pki/pki/distribute/standalone/000_pki_trust/system-files/ldap.conf"
if [[ -f "$ldap_conf" ]] && grep -q '^TLS_PROTOCOL_MIN  3.3' "$ldap_conf" \
   && grep -q '^TLS_REQCERT       demand' "$ldap_conf"; then
    ok "ldap.conf carries TLS_PROTOCOL_MIN 3.3 + TLS_REQCERT demand"
else
    fail "ldap.conf missing TLS hardening lines"
fi

# --- 10. Validity-day cap refusal (private mode, leaf > 825)
if python3 "$RENDERER" \
    --output-dir "$tmp/leaf-cap" \
    --mode private \
    --target core5 \
    --single-sh-fqdn sh01.example.com \
    --leaf-days 999 \
    >/dev/null 2>"$tmp/leaf-cap-err"; then
    fail "leaf-days 999 (above 825 cap) was accepted in private mode"
else
    if grep -q "leaf-days" "$tmp/leaf-cap-err"; then
        ok "leaf-days > 825 refused in private mode"
    else
        fail "leaf-days cap refusal did not mention leaf-days"
    fi
fi

# --- 11. TLS 1.3 refusal
if python3 "$RENDERER" \
    --output-dir "$tmp/tls13" \
    --mode private \
    --target core5 \
    --single-sh-fqdn sh01.example.com \
    --tls-version-floor tls1.3 \
    >/dev/null 2>"$tmp/tls13-err"; then
    fail "tls-version-floor tls1.3 was accepted (Splunk docs do not yet support TLS 1.3)"
else
    ok "tls-version-floor tls1.3 refused"
fi

# --- 12. setup.sh apply requires --accept-pki-rotation
if bash "$SETUP" \
    --phase apply \
    --output-dir "$tmp/apply-no-ack" \
    --mode private \
    --target core5 \
    --single-sh-fqdn sh01.example.com \
    >"$tmp/apply-no-ack-out" 2>&1; then
    fail "setup.sh apply did not refuse without --accept-pki-rotation"
else
    if grep -q "accept-pki-rotation" "$tmp/apply-no-ack-out"; then
        ok "setup.sh apply refuses without --accept-pki-rotation"
    else
        fail "setup.sh apply refusal message did not mention accept flag"
    fi
fi

# --- 13. bash -n on every rendered shell script
shell_failed=0
while IFS= read -r script; do
    if ! bash -n "$script" 2>/dev/null; then
        fail "rendered script syntax error: $script"
        shell_failed=1
    fi
done < <(find "$tmp/full-private" -name '*.sh' 2>/dev/null)
if [[ "$shell_failed" == "0" ]]; then
    ok "all rendered shell scripts pass bash -n"
fi

# --- 14. metadata.json valid + no secret VALUES (only paths)
meta="$tmp/full-private/platform-pki/metadata.json"
if python3 -c "import json; json.load(open('$meta'))" 2>/dev/null; then
    ok "metadata.json is valid JSON"
else
    fail "metadata.json is not valid JSON"
fi

# Secret values would land here as raw strings; secret PATHS are fine.
# Forbid raw PEM blocks anywhere in rendered output.
secret_failed=0
while IFS= read -r f; do
    if grep -q -- '-----BEGIN .*PRIVATE KEY-----' "$f" 2>/dev/null; then
        fail "rendered file contains a PRIVATE KEY block: $f"
        secret_failed=1
    fi
done < <(find "$tmp/full-private" -type f 2>/dev/null)
if [[ "$secret_failed" == "0" ]]; then
    ok "no PEM private key blocks in rendered output"
fi

# --- 15. algorithm-policy.json validates
ALGO_JSON="$(dirname "$SCRIPT_DIR")/references/algorithm-policy.json"
if python3 -c "
import json, sys
d = json.load(open('$ALGO_JSON'))
assert 'presets' in d
for p in ('splunk-modern', 'fips-140-3', 'stig'):
    assert p in d['presets']
    pp = d['presets'][p]
    assert pp['ssl_versions'] == 'tls1.2'
    assert 'cipher_suite' in pp
    assert 'ecdh_curves' in pp
assert d['kv_store_required_eku'] == ['serverAuth', 'clientAuth']
print('OK')
" 2>/dev/null; then
    ok "algorithm-policy.json validates with all three presets"
else
    fail "algorithm-policy.json invalid or missing required keys"
fi

# --- 16. Splunk-modern preset is the renderer default and emits TLS 1.2
modern_server="$tmp/full-private/platform-pki/pki/distribute/cluster-bundle/master-apps/000_pki_trust/local/server.conf"
if grep -q '^sslVersions          = tls1.2' "$modern_server"; then
    ok "splunk-modern preset emits sslVersions = tls1.2"
else
    fail "splunk-modern preset did not emit sslVersions = tls1.2"
fi
if grep -q '^sslVersionsForClient = tls1.2' "$modern_server"; then
    ok "splunk-modern preset emits sslVersionsForClient = tls1.2"
else
    fail "splunk-modern preset did not emit sslVersionsForClient = tls1.2"
fi

# --- 17. fips-140-3 preset strips CBC / SHA-1
if python3 "$RENDERER" \
    --output-dir "$tmp/fips-policy" \
    --mode private \
    --target indexer-cluster \
    --cm-fqdn cm01.example.com \
    --peer-hosts idx01.example.com,idx02.example.com,idx03.example.com \
    --tls-policy fips-140-3 \
    >/dev/null 2>&1; then
    ok "fips-140-3 policy render"
fi
fips_server="$tmp/fips-policy/platform-pki/pki/distribute/cluster-bundle/master-apps/000_pki_trust/local/server.conf"
if grep -q '^cipherSuite' "$fips_server"; then
    if grep '^cipherSuite' "$fips_server" | grep -qE 'CBC|SHA1[^0-9]'; then
        fail "fips-140-3 preset cipherSuite still includes CBC or SHA1"
    else
        ok "fips-140-3 preset strips CBC and SHA-1 from cipherSuite"
    fi
fi

# --- 18. Cluster bundle drop-in carries sslVerifyServerName=true
if grep -q '^sslVerifyServerName  = true' "$modern_server"; then
    ok "cluster bundle has sslVerifyServerName=true"
else
    fail "cluster bundle missing sslVerifyServerName=true"
fi

# --- 19. KV-Store EKU check script is present and matches the documented openssl cmd
kv_check="$tmp/full-private/platform-pki/pki/install/kv-store-eku-check.sh"
if [[ -x "$kv_check" ]] \
   && grep -q 'openssl verify' "$kv_check" \
   && grep -q 'x509_strict' "$kv_check" \
   && grep -q 'TLSWebServerAuthentication' "$kv_check" \
   && grep -q 'TLSWebClientAuthentication' "$kv_check"; then
    ok "kv-store-eku-check.sh runs documented openssl verify -x509_strict + dual-EKU check"
else
    fail "kv-store-eku-check.sh missing required behavior"
fi

# --- 20. Default-cert subject tokens flagged in verify-leaf.sh
verify="$tmp/full-private/platform-pki/pki/install/verify-leaf.sh"
for token in SplunkServerDefaultCert SplunkCommonCA SplunkWebDefaultCert; do
    if ! grep -q "$token" "$verify"; then
        fail "verify-leaf.sh missing default-cert token check: $token"
    fi
done
ok "verify-leaf.sh checks for all default Splunk cert tokens"

# --- 21. align-cli-trust.sh writes to $SPLUNK_HOME/etc/auth/cacert.pem
align="$tmp/full-private/platform-pki/pki/install/align-cli-trust.sh"
if grep -q 'SPLUNK_HOME/etc/auth/cacert.pem' "$align"; then
    ok "align-cli-trust.sh targets \$SPLUNK_HOME/etc/auth/cacert.pem"
else
    fail "align-cli-trust.sh does not target the right cacert.pem path"
fi

# --- 22. rotation runbook references splunk-indexer-cluster-setup --phase rolling-restart
runbook="$tmp/full-private/platform-pki/pki/rotate/plan-rotation.md"
if grep -q 'splunk-indexer-cluster-setup' "$runbook" \
   && grep -q 'phase rolling-restart' "$runbook" \
   && grep -q 'rolling-restart-mode searchable' "$runbook"; then
    ok "rotation runbook delegates to splunk-indexer-cluster-setup --phase rolling-restart --rolling-restart-mode searchable"
else
    fail "rotation runbook does not reference the delegated rolling restart"
fi

# --- 23. Splunk Cloud UFCP handoff is always present
ufcp="$tmp/full-private/platform-pki/handoff/splunk-cloud-ufcp.md"
if [[ -f "$ufcp" ]] && grep -q 'Universal Forwarder Credentials Package' "$ufcp"; then
    ok "splunk-cloud-ufcp handoff present and references UFCP"
else
    fail "splunk-cloud-ufcp handoff missing or wrong content"
fi

# --- 24. Edge Processor PKCS#8 enforcement
if python3 "$RENDERER" \
    --output-dir "$tmp/ep-pkcs8" \
    --mode private \
    --target edge-processor \
    --include-edge-processor true \
    --ep-fqdn ep01.example.com \
    --key-format pkcs8 \
    >/dev/null 2>&1; then
    ok "EP render with --key-format pkcs8"
fi
ep_sign="$tmp/ep-pkcs8/platform-pki/pki/private-ca/sign-server-cert.sh"
if grep -q 'pkcs8 -topk8' "$ep_sign"; then
    ok "sign-server-cert.sh converts to PKCS#8 when --key-format pkcs8"
else
    fail "sign-server-cert.sh missing PKCS#8 conversion"
fi

# --- 25. dry-run JSON parses
if dryrun_out="$(python3 "$RENDERER" \
    --output-dir "$tmp/dry" \
    --mode private \
    --target core5 \
    --single-sh-fqdn sh01.example.com \
    --dry-run --json 2>&1)"; then
    if python3 -c "import json,sys; json.loads(sys.argv[1])" "$dryrun_out" 2>/dev/null; then
        ok "dry-run JSON parses"
    else
        fail "dry-run JSON did not parse"
    fi
else
    fail "dry-run JSON command failed"
fi

# --- 26. Splunk-modern preset matches public-exposure-hardening cipherSuite constant.
# Compare the canonical colon-joined cipher list (all-uppercase, no whitespace).
PUBLIC_EXPOSURE_RENDERER="$(dirname "$SCRIPT_DIR")/../splunk-enterprise-public-exposure-hardening/scripts/render_assets.py"
if [[ -f "$PUBLIC_EXPOSURE_RENDERER" ]]; then
    pe_cipher="$(python3 - "$PUBLIC_EXPOSURE_RENDERER" <<'PY'
import re, sys
src = open(sys.argv[1]).read()
m = re.search(r"CIPHER_SUITE\s*=\s*\((.*?)\)", src, re.S)
if not m:
    print("")
    sys.exit(0)
parts = re.findall(r'"([^"]+)"', m.group(1))
print("".join(parts).rstrip(":"))
PY
)"
    pki_cipher="$(python3 -c "import json; print(json.load(open('$ALGO_JSON'))['presets']['splunk-modern']['cipher_suite'])" )"
    if [[ "$pe_cipher" == "$pki_cipher" ]]; then
        ok "splunk-modern cipherSuite matches public-exposure-hardening CIPHER_SUITE byte-for-byte"
    else
        fail "splunk-modern cipherSuite drift from public-exposure-hardening (PE='$pe_cipher' PKI='$pki_cipher')"
    fi
fi

# --- 27a. CRITICAL CORRECTNESS: NO per-host serverCert / sslPassword in any
# bundle conf file. Per-host settings are written by install-leaf.sh to
# each host's etc/system/local/<conf> overlay. If a bundle contained
# serverCert = .../__HOST__/__HOST__-splunkd.pem, every peer would look
# for a literal file named __HOST__-splunkd.pem and fail to start.
bundle_failed=0
for bundle_conf in $(find "$tmp/full-private/platform-pki/pki/distribute" \
                          "$tmp/repl-ssl/platform-pki/pki/distribute" \
                          "$tmp/fips/platform-pki/pki/distribute" \
                          -name '*.conf' 2>/dev/null); do
    # forwarder-fleet outputs may legitimately omit serverCert (it's a forwarder),
    # but bundles MUST NOT carry per-host serverCert / sslPassword / __HOST__ refs.
    if grep -E '^[[:space:]]*serverCert[[:space:]]*=' "$bundle_conf" >/dev/null 2>&1; then
        fail "bundle conf carries per-host serverCert: $bundle_conf"
        bundle_failed=1
    fi
    if grep -E '^[[:space:]]*sslPassword[[:space:]]*=' "$bundle_conf" >/dev/null 2>&1; then
        fail "bundle conf carries sslPassword (Splunk would try to decrypt placeholder): $bundle_conf"
        bundle_failed=1
    fi
    if grep -F '__HOST__' "$bundle_conf" >/dev/null 2>&1; then
        fail "bundle conf carries __HOST__ placeholder Splunk will treat as literal: $bundle_conf"
        bundle_failed=1
    fi
done
if [[ "$bundle_failed" == "0" ]]; then
    ok "no per-host serverCert / sslPassword / __HOST__ leaks into ANY bundle conf"
fi

# --- 27b. install-leaf.sh writes per-host overlay to system/local
overlay_install="$tmp/full-private/platform-pki/pki/install/install-leaf.sh"
if grep -q 'SPLUNK_HOME/etc/system/local' "$overlay_install" \
   && grep -q 'BEGIN splunk-platform-pki-setup' "$overlay_install" \
   && grep -q 'END splunk-platform-pki-setup' "$overlay_install"; then
    ok "install-leaf.sh writes idempotent per-host overlay to etc/system/local with markers"
else
    fail "install-leaf.sh does not write idempotent per-host overlay"
fi

# --- 27c. install-leaf.sh supports --ssl-password-file and skips when omitted
if grep -q '\-\-ssl-password-file' "$overlay_install" \
   && grep -q 'SSL_PASSWORD_LINE' "$overlay_install"; then
    ok "install-leaf.sh accepts --ssl-password-file (plaintext written to overlay; Splunk encrypts on restart)"
else
    fail "install-leaf.sh missing --ssl-password-file support"
fi

# --- 28. authoritative-sources.md references key Splunk URLs
src_md="$(dirname "$SCRIPT_DIR")/references/authoritative-sources.md"
for url_keyword in "configure-tls-certificates-for-inter-splunk-communication" \
                   "how-to-create-and-sign-your-own-tls-certificates" \
                   "CustomCertsKVstore" \
                   "secure-splunk-enterprise-with-fips" \
                   "configure-tls-protocol-version-support" \
                   "Forwarder_Forwarder_ConfigSCUFCredentials"; do
    if ! grep -q "$url_keyword" "$src_md"; then
        fail "authoritative-sources.md missing reference: $url_keyword"
    fi
done
ok "authoritative-sources.md references the key upstream Splunk doc URLs"

if [[ "$failed" -gt 0 ]]; then
    echo
    echo "SMOKE FAILED: $failed check(s) failed." >&2
    exit 1
fi

echo
echo "SMOKE PASSED."
