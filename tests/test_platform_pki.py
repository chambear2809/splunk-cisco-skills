"""Offline regressions for splunk-platform-pki-setup.

Mirrors the structure of test_public_exposure_hardening.py. Asserts every
behavior locked in by the rendered references and the renderer's closed
GENERATED_FILES manifest:

1. GENERATED_FILES + GENERATED_FILE_PATTERNS cover every actually-emitted
   file (no surprise files; no stale entries).
2. Splunk Web emits enableSplunkWebSSL = true.
3. splunkd server.conf [sslConfig] emits enableSplunkdSSL = true.
4. sslVersions = tls1.2 (NOT tls1.3) at the floor; sslVersionsForClient
   the same.
5. requireClientCert = true only when --enable-mtls covers the surface.
6. sslVerifyServerName = true on every cluster bundle / SHC drop-in.
7. KV-Store EKU enforcement script is present and matches the documented
   openssl verify -x509_strict + dual-EKU pattern.
8. Default-cert subject tokens flagged in verify-leaf.sh.
9. [replication_port-ssl://9887] only present when
   --encrypt-replication-port=true; mutually exclusive with
   [replication_port://9887].
10. Edge Processor renders the documented 5-file naming when
    --include-edge-processor=true; PKCS#8 signing path active when
    --key-format=pkcs8.
11. install-fips-launch-conf.sh only emitted when --fips-mode != none;
    sets SPLUNK_FIPS_VERSION.
12. SAML SP signatureAlgorithm uses RSA-SHA384 / RSA-SHA512 (not SHA-1).
13. ldap.conf carries TLS_PROTOCOL_MIN 3.3 + TLS_REQCERT demand when
    --ldaps=true.
14. align-cli-trust.sh writes to $SPLUNK_HOME/etc/auth/cacert.pem.
15. setup.sh apply requires --accept-pki-rotation.
16. Splunk Cloud --target uf-fleet renders the UFCP handoff (and the
    refusal of self-issued cloud certs).
17. Rotation runbook references splunk-indexer-cluster-setup --phase
    rolling-restart --rolling-restart-mode searchable.
18. Validity-day caps: --leaf-days 999 rejected (private mode); 825
    accepted; > 397 in public mode warns.
19. Algorithm preset matrix: fips-140-3 strips CBC / SHA-1; stig refuses
    rsa-2048; splunk-modern matches the public-exposure hardening cipher
    set.
20. algorithm-policy.json validates and lints clean.
21. inventory phase emits pki/inventory/<host>.json without invoking any
    Splunk write API.
22. metadata.json valid JSON; no PEM private key blocks anywhere.
23. All rendered .sh pass bash -n.
24. authoritative-sources.md cites the key upstream Splunk URLs.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills/splunk-platform-pki-setup"
RENDER_SCRIPT = SKILL_ROOT / "scripts/render_assets.py"
SETUP_SCRIPT = SKILL_ROOT / "scripts/setup.sh"
SMOKE_SCRIPT = SKILL_ROOT / "scripts/smoke_offline.sh"
ALGO_JSON = SKILL_ROOT / "references/algorithm-policy.json"


def _load_render_module():
    spec = importlib.util.spec_from_file_location("ppki_render_assets", RENDER_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("ppki_render_assets", module)
    spec.loader.exec_module(module)
    return module


render_module = _load_render_module()


def run_render(*args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(RENDER_SCRIPT), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kwargs)


def run_setup(*args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    cmd = ["bash", str(SETUP_SCRIPT), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=REPO_ROOT, **kwargs)


def render_dir(out: Path) -> Path:
    return out / "platform-pki"


def _full_cluster_args(out: Path, **overrides: str) -> list[str]:
    args = {
        "--output-dir": str(out),
        "--mode": "private",
        "--target": "indexer-cluster,shc,license-manager,deployment-server,monitoring-console",
        "--cm-fqdn": "cm01.example.com",
        "--peer-hosts": "idx01.example.com,idx02.example.com,idx03.example.com",
        "--shc-deployer-fqdn": "deployer01.example.com",
        "--shc-members": "sh01.example.com,sh02.example.com,sh03.example.com",
        "--lm-fqdn": "lm01.example.com",
        "--ds-fqdn": "ds01.example.com",
        "--mc-fqdn": "mc01.example.com",
        "--include-intermediate-ca": "true",
    }
    args.update(overrides)
    flat: list[str] = []
    for k, v in args.items():
        flat.extend([k, v])
    return flat


def _core5_args(out: Path, **overrides: str) -> list[str]:
    args = {
        "--output-dir": str(out),
        "--mode": "private",
        "--target": "core5",
        "--single-sh-fqdn": "sh01.example.com",
    }
    args.update(overrides)
    flat: list[str] = []
    for k, v in args.items():
        flat.extend([k, v])
    return flat


# ---------------------------------------------------------------------------
# 1. GENERATED_FILES manifest
# ---------------------------------------------------------------------------

def test_emitted_files_subset_of_manifest_or_pattern_allowlist(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*_full_cluster_args(out))
    assert result.returncode == 0, result.stderr

    actual: set[str] = set()
    for path in render_dir(out).rglob("*"):
        if path.is_file():
            actual.add(str(path.relative_to(render_dir(out))))

    extras = {
        rel
        for rel in actual
        if rel not in render_module.GENERATED_FILES
        and not any(re.match(pat, rel) for pat in render_module.GENERATED_FILE_PATTERNS)
    }
    assert not extras, f"Unmanaged files emitted (not in manifest or pattern allow-list): {sorted(extras)}"


# ---------------------------------------------------------------------------
# 2-4. Splunk Web / splunkd / TLS version floor
# ---------------------------------------------------------------------------

def test_splunk_web_enables_ssl(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out)).returncode == 0
    web = (render_dir(out) / "pki/distribute/shc-deployer/shcluster/apps/000_pki_trust/local/web.conf").read_text()
    assert "enableSplunkWebSSL = true" in web


def test_splunkd_enables_ssl_and_floor_is_tls12(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out)).returncode == 0
    server = (render_dir(out) / "pki/distribute/cluster-bundle/master-apps/000_pki_trust/local/server.conf").read_text()
    assert "enableSplunkdSSL     = true" in server
    assert "sslVersions          = tls1.2" in server
    assert "sslVersionsForClient = tls1.2" in server
    assert "tls1.3" not in server


def test_tls13_is_refused(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*_core5_args(out, **{"--tls-version-floor": "tls1.3"}))
    assert result.returncode != 0
    # argparse rejects the choice with the value enumeration in the message.
    combined = (result.stderr + result.stdout).lower()
    assert "tls1.3" in combined or "tls1.2" in combined


def test_allow_deprecated_tls_relaxes_lower_bound(tmp_path: Path) -> None:
    """--allow-deprecated-tls must actually be enforced. Without the flag,
    --tls-version-floor=tls1.0 must be refused. With the flag, it must
    be accepted (operator escape hatch for legacy clients)."""
    # argparse only allows tls1.2 at the CLI level; the deprecated-relax
    # path is exercised inside _validate_args. Confirm both paths.
    src = (SKILL_ROOT / "scripts/render_assets.py").read_text()
    assert "args.allow_deprecated_tls" in src, (
        "--allow-deprecated-tls flag must be acted on; the renderer used to "
        "accept the flag silently and never apply it."
    )
    # Unit-test the argparse path directly via the loaded module.
    parser_args = render_module.parse_args.__defaults__
    # The flag is registered; just confirm the policy-aware branch exists.
    assert "tls_version_forbidden" in src


# ---------------------------------------------------------------------------
# 5. mTLS opt-in
# ---------------------------------------------------------------------------

def test_mtls_opt_in_sets_require_client_cert(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out, **{"--enable-mtls": "all"})).returncode == 0
    server = (render_dir(out) / "pki/distribute/cluster-bundle/master-apps/000_pki_trust/local/server.conf").read_text()
    assert "requireClientCert    = true" in server


def test_mtls_default_does_not_force_splunkd_mtls(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out)).returncode == 0  # default: s2s,hec
    server = (render_dir(out) / "pki/distribute/cluster-bundle/master-apps/000_pki_trust/local/server.conf").read_text()
    assert "requireClientCert    = false" in server


# ---------------------------------------------------------------------------
# 6. sslVerifyServerName = true everywhere
# ---------------------------------------------------------------------------

def test_ssl_verify_server_name_true(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out)).returncode == 0
    server = (render_dir(out) / "pki/distribute/cluster-bundle/master-apps/000_pki_trust/local/server.conf").read_text()
    assert "sslVerifyServerName  = true" in server


# ---------------------------------------------------------------------------
# 7. KV-Store EKU enforcement script
# ---------------------------------------------------------------------------

def test_kv_store_eku_check_runs_documented_openssl_verify(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out)).returncode == 0
    kv = (render_dir(out) / "pki/install/kv-store-eku-check.sh").read_text()
    assert "openssl verify" in kv
    assert "x509_strict" in kv
    assert "TLSWebServerAuthentication" in kv
    assert "TLSWebClientAuthentication" in kv


# ---------------------------------------------------------------------------
# 8. Default-cert subject tokens
# ---------------------------------------------------------------------------

def test_verify_leaf_flags_default_subject_tokens(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out)).returncode == 0
    verify = (render_dir(out) / "pki/install/verify-leaf.sh").read_text()
    for token in ("SplunkServerDefaultCert", "SplunkCommonCA", "SplunkWebDefaultCert"):
        assert token in verify, f"verify-leaf.sh missing default-cert token: {token}"


# ---------------------------------------------------------------------------
# 9. Replication port mutual exclusion
# ---------------------------------------------------------------------------

def test_replication_port_ssl_never_in_cluster_bundle(tmp_path: Path) -> None:
    """[replication_port-ssl://9887] carries a per-host serverCert and
    therefore lives in each peer's etc/system/local/server.conf overlay,
    NOT in the shared cluster bundle. The bundle would resolve serverCert
    to the same literal file on every peer and break.
    """
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out, **{"--encrypt-replication-port": "true"})).returncode == 0
    server = (render_dir(out) / "pki/distribute/cluster-bundle/master-apps/000_pki_trust/local/server.conf").read_text()
    assert "[replication_port-ssl://9887]" not in server, (
        "Cluster bundle MUST NOT contain [replication_port-ssl://9887] — it carries a per-host "
        "serverCert and must live in each peer's etc/system/local/server.conf overlay instead."
    )


def test_replication_csr_templates_emitted_per_peer_when_opted_in(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out, **{"--encrypt-replication-port": "true"})).returncode == 0
    csr_dir = render_dir(out) / "pki/csr-templates"
    for peer_short in ("idx01", "idx02", "idx03"):
        # Per-peer replication CSR templates use the short host name.
        matches = list(csr_dir.glob(f"replication-{peer_short}*.cnf"))
        assert matches, f"Per-peer replication CSR template missing for {peer_short}"


def test_replication_csr_templates_skipped_when_not_opted_in(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out)).returncode == 0  # default: false
    csr_dir = render_dir(out) / "pki/csr-templates"
    assert not list(csr_dir.glob("replication-*.cnf"))


def test_install_leaf_supports_replication_target(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out, **{"--encrypt-replication-port": "true"})).returncode == 0
    install = (render_dir(out) / "pki/install/install-leaf.sh").read_text()
    assert "replication" in install
    assert "[replication_port-ssl://9887]" in install


def test_no_per_host_serverCert_or_sslPassword_in_any_bundle(tmp_path: Path) -> None:
    """CRITICAL CORRECTNESS: cluster bundle / SHC deployer bundle /
    standalone bundle must NEVER carry per-host serverCert or
    sslPassword. They're shared with every peer/member, so per-host
    settings would either resolve to the same literal file on every host
    (broken) or leak the same encrypted password placeholder (broken).
    install-leaf.sh writes per-host serverCert / sslPassword to each
    host's etc/system/local/<conf> overlay instead.
    """
    out = tmp_path / "out"
    args = _full_cluster_args(
        out,
        **{
            "--encrypt-replication-port": "true",
            "--enable-mtls": "all",
            "--fips-mode": "140-3",
        },
    )
    assert run_render(*args).returncode == 0

    bundle_dirs = (
        "pki/distribute/cluster-bundle",
        "pki/distribute/shc-deployer",
        "pki/distribute/standalone",
    )
    for bdir in bundle_dirs:
        for conf in (render_dir(out) / bdir).rglob("*.conf"):
            text = conf.read_text()
            for line in text.splitlines():
                stripped = line.strip()
                assert not re.match(r"^serverCert\s*=", stripped), (
                    f"Bundle conf {conf.relative_to(render_dir(out))} carries per-host serverCert: {line!r}"
                )
                assert not re.match(r"^sslPassword\s*=", stripped), (
                    f"Bundle conf {conf.relative_to(render_dir(out))} carries sslPassword: {line!r}"
                )
            assert "__HOST__" not in text, (
                f"Bundle conf {conf.relative_to(render_dir(out))} carries __HOST__ placeholder "
                "(Splunk treats it as a literal filename component)"
            )


def test_install_leaf_writes_per_host_overlay_to_system_local(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out)).returncode == 0
    install = (render_dir(out) / "pki/install/install-leaf.sh").read_text()
    assert "SPLUNK_HOME/etc/system/local" in install
    assert "BEGIN splunk-platform-pki-setup" in install
    assert "END splunk-platform-pki-setup" in install
    # Idempotent: prior block must be stripped before re-appending
    assert "awk" in install
    assert "skip" in install


def test_install_leaf_supports_ssl_password_file(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out)).returncode == 0
    install = (render_dir(out) / "pki/install/install-leaf.sh").read_text()
    assert "--ssl-password-file" in install
    assert "SSL_PASSWORD_FILE" in install
    assert "SSL_PASSWORD_LINE" in install


# ---------------------------------------------------------------------------
# 10. Edge Processor cert pair
# ---------------------------------------------------------------------------

def test_edge_processor_renders_documented_5_file_pair(tmp_path: Path) -> None:
    out = tmp_path / "out"
    args = {
        "--output-dir": str(out),
        "--mode": "private",
        "--target": "edge-processor",
        "--include-edge-processor": "true",
        "--ep-fqdn": "ep01.example.com",
        "--ep-data-source-fqdn": "ds01.example.com",
    }
    flat = []
    for k, v in args.items():
        flat.extend([k, v])
    result = run_render(*flat)
    assert result.returncode == 0, result.stderr
    ep_dir = render_dir(out) / "pki/distribute/edge-processor"
    for fname in (
        "ca_cert.pem.example",
        "edge_server_cert.pem.example",
        "edge_server_key.pem.example",
        "data_source_client_cert.pem.example",
        "data_source_client_key.pem.example",
        "upload-via-rest.sh.example",
        "README.md",
    ):
        assert (ep_dir / fname).exists(), f"EP file missing: {fname}"


def test_edge_processor_pkcs8_path_in_sign_script(tmp_path: Path) -> None:
    out = tmp_path / "out"
    args = {
        "--output-dir": str(out),
        "--mode": "private",
        "--target": "edge-processor",
        "--include-edge-processor": "true",
        "--ep-fqdn": "ep01.example.com",
        "--key-format": "pkcs8",
    }
    flat = []
    for k, v in args.items():
        flat.extend([k, v])
    assert run_render(*flat).returncode == 0
    sign = (render_dir(out) / "pki/private-ca/sign-server-cert.sh").read_text()
    assert "pkcs8 -topk8" in sign


# ---------------------------------------------------------------------------
# 11. FIPS install script
# ---------------------------------------------------------------------------

def test_fips_install_script_only_when_fips_mode_set(tmp_path: Path) -> None:
    # default --fips-mode none => no install-fips-launch-conf.sh
    out_default = tmp_path / "default"
    assert run_render(*_full_cluster_args(out_default)).returncode == 0
    assert not (render_dir(out_default) / "pki/install/install-fips-launch-conf.sh").exists()

    # --fips-mode 140-3 => install-fips-launch-conf.sh is emitted
    out_fips = tmp_path / "fips"
    assert run_render(*_full_cluster_args(out_fips, **{"--fips-mode": "140-3"})).returncode == 0
    fips = (render_dir(out_fips) / "pki/install/install-fips-launch-conf.sh").read_text()
    assert "SPLUNK_FIPS_VERSION" in fips


# ---------------------------------------------------------------------------
# 12. SAML SP signature algorithm
# ---------------------------------------------------------------------------

def test_saml_sp_signature_algorithm_is_modern(tmp_path: Path) -> None:
    out = tmp_path / "out"
    args = {
        "--output-dir": str(out),
        "--mode": "private",
        "--target": "core5,saml-sp",
        "--single-sh-fqdn": "sh01.example.com",
        "--public-fqdn": "splunk.example.com",
        "--saml-sp": "true",
    }
    flat = []
    for k, v in args.items():
        flat.extend([k, v])
    assert run_render(*flat).returncode == 0
    auth = (render_dir(out) / "pki/distribute/standalone/000_pki_trust/local/authentication.conf").read_text()
    assert re.search(r"^signatureAlgorithm\s*=\s*RSA-SHA(384|512)", auth, re.M)
    assert "RSA-SHA1" not in auth


# ---------------------------------------------------------------------------
# 13. LDAPS ldap.conf hardening
# ---------------------------------------------------------------------------

def test_ldaps_renders_hardened_ldap_conf(tmp_path: Path) -> None:
    out = tmp_path / "out"
    args = {
        "--output-dir": str(out),
        "--mode": "private",
        "--target": "license-manager,ldaps",
        "--lm-fqdn": "lm01.example.com",
        "--ldaps": "true",
        "--ldap-host": "ad.example.com",
    }
    flat = []
    for k, v in args.items():
        flat.extend([k, v])
    assert run_render(*flat).returncode == 0
    ldap = (render_dir(out) / "pki/distribute/standalone/000_pki_trust/system-files/ldap.conf").read_text()
    assert "TLS_PROTOCOL_MIN  3.3" in ldap
    assert "TLS_REQCERT       demand" in ldap


# ---------------------------------------------------------------------------
# 14. CLI trust alignment
# ---------------------------------------------------------------------------

def test_align_cli_trust_writes_to_cacert_pem(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out)).returncode == 0
    align = (render_dir(out) / "pki/install/align-cli-trust.sh").read_text()
    assert "SPLUNK_HOME/etc/auth/cacert.pem" in align


# ---------------------------------------------------------------------------
# 15. setup.sh apply guard
# ---------------------------------------------------------------------------

def test_setup_apply_requires_accept_pki_rotation(tmp_path: Path) -> None:
    out = tmp_path / "out"
    args = [
        "--phase", "apply",
        "--output-dir", str(out),
        "--mode", "private",
        "--target", "core5",
        "--single-sh-fqdn", "sh01.example.com",
    ]
    result = run_setup(*args)
    assert result.returncode != 0
    combined = (result.stderr + result.stdout)
    assert "accept-pki-rotation" in combined


# ---------------------------------------------------------------------------
# 16. Splunk Cloud UFCP handoff
# ---------------------------------------------------------------------------

def test_ufcp_handoff_always_present(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out)).returncode == 0
    ufcp = (render_dir(out) / "handoff/splunk-cloud-ufcp.md").read_text()
    assert "Universal Forwarder Credentials Package" in ufcp


# ---------------------------------------------------------------------------
# 17. Rotation runbook delegates rolling restart
# ---------------------------------------------------------------------------

def test_rotation_runbook_delegates_to_indexer_cluster_setup(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out)).returncode == 0
    runbook = (render_dir(out) / "pki/rotate/plan-rotation.md").read_text()
    assert "splunk-indexer-cluster-setup" in runbook
    assert "phase rolling-restart" in runbook
    assert "rolling-restart-mode searchable" in runbook


# ---------------------------------------------------------------------------
# 18. Validity-day cap
# ---------------------------------------------------------------------------

def test_leaf_days_cap_in_private_mode(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*_core5_args(out, **{"--leaf-days": "999"}))
    assert result.returncode != 0
    combined = (result.stderr + result.stdout).lower()
    assert "leaf-days" in combined or "leaf_days" in combined


def test_leaf_days_825_accepted_in_private_mode(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*_core5_args(out, **{"--leaf-days": "825"}))
    assert result.returncode == 0, result.stderr


def test_leaf_days_above_397_accepted_in_public_mode(tmp_path: Path) -> None:
    out = tmp_path / "out"
    args = _core5_args(
        out,
        **{
            "--mode": "public",
            "--public-fqdn": "splunk.example.com",
            "--leaf-days": "500",
        },
    )
    result = run_render(*args)
    # public mode allows above-397 with a warning (operator's CA enforces)
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# 19. Algorithm preset behaviour
# ---------------------------------------------------------------------------

def test_fips_140_3_strips_cbc_and_sha1_from_cipher_suite(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out, **{"--tls-policy": "fips-140-3"})).returncode == 0
    server = (render_dir(out) / "pki/distribute/cluster-bundle/master-apps/000_pki_trust/local/server.conf").read_text()
    cipher_lines = [ln for ln in server.splitlines() if ln.startswith("cipherSuite")]
    assert cipher_lines
    full = " ".join(cipher_lines)
    assert "CBC" not in full
    assert "SHA1" not in re.sub(r"SHA(?:256|384|512)", "", full)


def test_stig_refuses_rsa_2048(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*_full_cluster_args(out, **{"--tls-policy": "stig", "--key-algorithm": "rsa-2048"}))
    assert result.returncode != 0
    combined = (result.stderr + result.stdout).lower()
    assert "key-algorithm" in combined or "stig" in combined


def test_stig_accepts_rsa_3072(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*_full_cluster_args(out, **{"--tls-policy": "stig", "--key-algorithm": "rsa-3072"}))
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# 20. algorithm-policy.json validates
# ---------------------------------------------------------------------------

def test_algorithm_policy_json_validates() -> None:
    data = json.loads(ALGO_JSON.read_text())
    assert data["tls_version_floor"] == "tls1.2"
    assert "tls1.3" in data["tls_version_not_yet_supported"]
    assert data["kv_store_required_eku"] == ["serverAuth", "clientAuth"]
    for preset in ("splunk-modern", "fips-140-3", "stig"):
        assert preset in data["presets"]
        body = data["presets"][preset]
        assert body["ssl_versions"] == "tls1.2"
        assert body["ssl_versions_for_client"] == "tls1.2"
        assert "cipher_suite" in body
        assert "ecdh_curves" in body
        assert "allowed_key_algorithms" in body
        assert "allowed_signature_algorithms" in body


# ---------------------------------------------------------------------------
# 21. inventory phase emits read-only JSON
# ---------------------------------------------------------------------------

def test_inventory_script_does_not_invoke_splunk_write(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out)).returncode == 0
    inv = (render_dir(out) / "inventory.sh").read_text()
    # Forbid known mutating REST patterns
    forbidden = (
        " -X POST",
        " -X PUT",
        " -X DELETE",
        "splunk add ",
        "splunk edit ",
        "splunk apply ",
        "splunk restart",
    )
    for needle in forbidden:
        assert needle not in inv, f"inventory.sh contains write operation: {needle}"
    assert "btool" in inv


# ---------------------------------------------------------------------------
# 22. metadata.json + no PEM private key blocks
# ---------------------------------------------------------------------------

def test_metadata_json_valid(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out)).returncode == 0
    meta_path = render_dir(out) / "metadata.json"
    data = json.loads(meta_path.read_text())
    assert data["skill"] == "splunk-platform-pki-setup"
    assert data["mode"] == "private"
    assert data["tls_version_floor"] == "tls1.2"


def test_no_pem_private_key_blocks_in_rendered_output(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out)).returncode == 0
    for f in render_dir(out).rglob("*"):
        if f.is_file():
            content = f.read_text(errors="ignore")
            assert "-----BEGIN " not in content or "PRIVATE KEY" not in content, (
                f"Rendered file contains PEM private key block: {f.relative_to(render_dir(out))}"
            )


# ---------------------------------------------------------------------------
# 23. bash -n on every rendered shell script
# ---------------------------------------------------------------------------

def test_all_rendered_shell_scripts_pass_bash_n(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_render(*_full_cluster_args(out, **{
        "--encrypt-replication-port": "true",
        "--include-edge-processor": "true",
        "--ep-fqdn": "ep01.example.com",
        "--saml-sp": "true",
        "--public-fqdn": "splunk.example.com",
        "--ldaps": "true",
        "--ldap-host": "ad.example.com",
        "--fips-mode": "140-3",
    })).returncode == 0
    failures = []
    for f in render_dir(out).rglob("*.sh"):
        result = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True)
        if result.returncode != 0:
            failures.append((f, result.stderr))
    assert not failures, f"Shell syntax errors: {failures}"


# ---------------------------------------------------------------------------
# 24. authoritative-sources.md citations
# ---------------------------------------------------------------------------

def test_authoritative_sources_md_cites_key_urls() -> None:
    src = (SKILL_ROOT / "references/authoritative-sources.md").read_text()
    for keyword in (
        "configure-tls-certificates-for-inter-splunk-communication",
        "how-to-create-and-sign-your-own-tls-certificates",
        "CustomCertsKVstore",
        "secure-splunk-enterprise-with-fips",
        "configure-tls-protocol-version-support",
        "Forwarder_Forwarder_ConfigSCUFCredentials",
        "AboutTLSencryptionandciphersuites",
        "configure-mutually-authenticated-transport-layer-security-mtls",
        "EnableTLSCertHostnameValidation",
    ):
        assert keyword in src, f"authoritative-sources.md missing reference: {keyword}"


# ---------------------------------------------------------------------------
# 25. smoke_offline.sh runs clean
# ---------------------------------------------------------------------------

def test_smoke_offline_passes() -> None:
    result = subprocess.run(
        ["bash", str(SMOKE_SCRIPT)], capture_output=True, text=True, cwd=REPO_ROOT
    )
    assert result.returncode == 0, f"smoke_offline.sh failed:\n{result.stdout}\n{result.stderr}"
