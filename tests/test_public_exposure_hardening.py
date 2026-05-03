"""Offline regressions for splunk-enterprise-public-exposure-hardening.

These tests exercise every renderer code path that does not require a
running Splunk host. They focus on the highest-risk classes:

1. Closed GENERATED_FILES set (no stale or unmanaged files emitted).
2. Default-cert detection via subject CN tokens.
3. SVD floor refusal — the renderer must refuse when the running
   Splunk version is below the floor.
4. Forbidden non-existent setting names — the rendered web.conf must
   NOT reference settings that do not exist in any released Splunk
   version (a known class of error).
5. No secret values in any rendered file.
6. metadata.json is valid JSON and contains only non-secret keys.
7. Setup.sh apply requires --accept-public-exposure.
8. All rendered shell scripts pass `bash -n`.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills/splunk-enterprise-public-exposure-hardening"
RENDER_SCRIPT = SKILL_ROOT / "scripts/render_assets.py"
SETUP_SCRIPT = SKILL_ROOT / "scripts/setup.sh"
SMOKE_SCRIPT = SKILL_ROOT / "scripts/smoke_offline.sh"


def _load_render_module():
    spec = importlib.util.spec_from_file_location("spx_render_assets", RENDER_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("spx_render_assets", module)
    spec.loader.exec_module(module)
    return module


render_module = _load_render_module()


def run_render(*args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(RENDER_SCRIPT), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kwargs)


def run_setup(*args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    cmd = ["bash", str(SETUP_SCRIPT), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=REPO_ROOT, **kwargs)


def base_render_args(out: Path, **overrides: str) -> list[str]:
    args = {
        "--output-dir": str(out),
        "--public-fqdn": "splunk.example.com",
        "--proxy-cidr": "10.0.10.0/24",
    }
    args.update(overrides)
    flat: list[str] = []
    for k, v in args.items():
        flat.extend([k, v])
    return flat


def render_dir(out: Path) -> Path:
    return out / "public-exposure"


# ---------------------------------------------------------------------------
# 1. GENERATED_FILES
# ---------------------------------------------------------------------------


def test_generated_files_set_matches_actual_render(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr

    actual: set[str] = set()
    for path in render_dir(out).rglob("*"):
        if path.is_file():
            actual.add(str(path.relative_to(render_dir(out))))

    expected = render_module.GENERATED_FILES
    assert actual == expected, (
        f"GENERATED_FILES set drift detected.\n"
        f"Missing from disk: {sorted(expected - actual)}\n"
        f"Extra on disk:     {sorted(actual - expected)}"
    )


def test_render_produces_props_conf_with_svd_2026_0302_mitigation(tmp_path: Path) -> None:
    """SVD-2026-0302 (CVE-2026-20162) RCE — props.conf must set
    unarchive_cmd_start_mode = direct."""
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    props_conf = (
        render_dir(out)
        / "splunk/apps/000_public_exposure_hardening/default/props.conf"
    ).read_text(encoding="utf-8")
    assert "[default]" in props_conf
    assert "unarchive_cmd_start_mode = direct" in props_conf


def test_server_conf_includes_allowed_unarchive_commands(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(
        *base_render_args(out),
        "--allowed-unarchive-commands",
        "/bin/gunzip,/bin/bunzip2",
    )
    assert result.returncode == 0, result.stderr
    server_conf = (
        render_dir(out)
        / "splunk/apps/000_public_exposure_hardening/default/server.conf"
    ).read_text(encoding="utf-8")
    assert "allowed_unarchive_commands = /bin/gunzip,/bin/bunzip2" in server_conf


def test_server_conf_default_allowed_unarchive_commands_is_empty(tmp_path: Path) -> None:
    """Default behaviour: empty allowlist means no unarchive command is permitted."""
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    server_conf = (
        render_dir(out)
        / "splunk/apps/000_public_exposure_hardening/default/server.conf"
    ).read_text(encoding="utf-8")
    assert re.search(r"^allowed_unarchive_commands\s*=\s*$", server_conf, flags=re.MULTILINE)


def test_server_conf_has_deployment_stanza_for_shc_topology(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(
        *base_render_args(out, **{"--topology": "shc-with-hec"}),
    )
    assert result.returncode == 0, result.stderr
    server_conf = (
        render_dir(out)
        / "splunk/apps/000_public_exposure_hardening/default/server.conf"
    ).read_text(encoding="utf-8")
    assert "[deployment]" in server_conf


def test_authentication_conf_saml_has_xsw_hardening(tmp_path: Path) -> None:
    """SAML must have allowPartialSignatures=false, attributeQuery*Signed=true."""
    out = tmp_path / "out"
    result = run_render(
        *base_render_args(
            out,
            **{
                "--auth-mode": "saml",
                "--saml-idp-metadata-path": "/tmp/idp.xml",
            },
        ),
    )
    assert result.returncode == 0, result.stderr
    auth_conf = (
        render_dir(out)
        / "splunk/apps/000_public_exposure_hardening/default/authentication.conf"
    ).read_text(encoding="utf-8")
    assert "allowPartialSignatures = false" in auth_conf
    assert "attributeQueryRequestSigned = true" in auth_conf
    assert "attributeQueryResponseSigned = true" in auth_conf


def test_fips_opt_in_renders_splunk_launch_conf(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(
        *base_render_args(
            out,
            **{
                "--enable-fips": "true",
                "--fips-version": "140-3",
            },
        ),
    )
    assert result.returncode == 0, result.stderr
    launch_conf = (
        render_dir(out)
        / "splunk/apps/000_public_exposure_hardening/default/splunk-launch.conf"
    ).read_text(encoding="utf-8")
    assert "SPLUNK_FIPS=1" in launch_conf
    assert "SPLUNK_FIPS_VERSION=140-3" in launch_conf


def test_fips_default_off_does_not_set_fips(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    launch_conf = (
        render_dir(out)
        / "splunk/apps/000_public_exposure_hardening/default/splunk-launch.conf"
    ).read_text(encoding="utf-8")
    # The setting must NOT appear at the start of a line (i.e., as actual
    # config). The file does mention SPLUNK_FIPS=1 in a comment explaining
    # what `--enable-fips true` would emit, but that's documentation only.
    assert not re.search(r"^SPLUNK_FIPS=1", launch_conf, flags=re.MULTILINE)


def test_fips_140_2_supported(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(
        *base_render_args(
            out,
            **{
                "--enable-fips": "true",
                "--fips-version": "140-2",
            },
        ),
    )
    assert result.returncode == 0, result.stderr
    launch_conf = (
        render_dir(out)
        / "splunk/apps/000_public_exposure_hardening/default/splunk-launch.conf"
    ).read_text(encoding="utf-8")
    assert "SPLUNK_FIPS_VERSION=140-2" in launch_conf


def test_proxy_denies_sensitive_paths(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    nginx_web = (render_dir(out) / "proxy/nginx/splunk-web.conf").read_text(encoding="utf-8")
    sensitive_patterns = (
        "services/apps",                          # SPL upload + Splunkbase install
        "services/configs/conf-passwords",        # SVD-2026-0303 info disclosure path
        "services/data/inputs/oneshot",           # one-shot file ingest
        "account/insecurelogin",                  # legacy GET-based login
        "debug/",                                 # debug surface
    )
    for pattern in sensitive_patterns:
        assert pattern in nginx_web, (
            f"nginx splunk-web.conf missing deny for sensitive pattern: {pattern}"
        )


def test_proxy_rejects_ansi_escape_codes(tmp_path: Path) -> None:
    """SVD-2025-1203 / CVE-2025-20384 mitigation: deny ANSI ESC + BEL."""
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    nginx_web = (render_dir(out) / "proxy/nginx/splunk-web.conf").read_text(encoding="utf-8")
    # Literal \x1b and \x07 in the rendered nginx regex.
    assert r"\x1b" in nginx_web
    assert r"\x07" in nginx_web


def test_haproxy_rejects_ansi_escape_codes(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    haproxy_web = (render_dir(out) / "proxy/haproxy/splunk-web.cfg").read_text(encoding="utf-8")
    assert r"\x1b" in haproxy_web
    assert r"\x07" in haproxy_web


def test_rotate_pass4symmkey_covers_all_six_stanzas(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    rotate = (render_dir(out) / "splunk/rotate-pass4symmkey.sh").read_text(encoding="utf-8")
    for stanza in (
        "[general]",
        "[clustering]",
        "[shclustering]",
        "[indexer_discovery]",
        "[license_master]",
        "[deployment]",
    ):
        assert stanza in rotate, f"rotate-pass4symmkey.sh missing stanza {stanza}"


def test_render_produces_full_topology(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(
        *base_render_args(
            out,
            **{
                "--topology": "shc-with-hec-and-hf",
                "--hec-fqdn": "hec.example.com",
                "--indexer-cluster-cidr": "10.0.20.0/24",
                "--bastion-cidr": "10.0.30.0/24",
                "--enable-web": "true",
                "--enable-hec": "true",
                "--enable-s2s": "true",
                "--hec-mtls": "true",
            },
        ),
    )
    assert result.returncode == 0, result.stderr
    inputs_conf = (
        render_dir(out)
        / "splunk/apps/000_public_exposure_hardening/default/inputs.conf"
    ).read_text(encoding="utf-8")
    assert "[http]" in inputs_conf
    assert "connection_host = proxied_ip" in inputs_conf
    assert "[splunktcp-ssl://9997]" in inputs_conf
    assert "requireClientCert = true" in inputs_conf
    outputs_conf = (
        render_dir(out)
        / "splunk/apps/000_public_exposure_hardening/default/outputs.conf"
    ).read_text(encoding="utf-8")
    assert "[tcpout]" in outputs_conf
    assert "useClientSSLCompression = false" in outputs_conf


# ---------------------------------------------------------------------------
# 2. SVD floor
# ---------------------------------------------------------------------------


def test_svd_floor_refusal_below_94_floor(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out, **{"--splunk-version": "9.4.5"}))
    assert result.returncode != 0
    assert "SVD floor" in (result.stderr + result.stdout)
    assert "9.4.10" in (result.stderr + result.stdout)


def test_svd_floor_accepts_at_or_above_floor(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out, **{"--splunk-version": "10.2.2"}))
    assert result.returncode == 0, result.stderr


def test_svd_floor_unknown_series_does_not_refuse(tmp_path: Path) -> None:
    out = tmp_path / "out"
    # 8.x is end-of-life; the floor JSON has no entry. The renderer should
    # not refuse on unknown series — it lets preflight decide.
    result = run_render(*base_render_args(out, **{"--splunk-version": "8.0.10"}))
    assert result.returncode == 0, result.stderr


def test_svd_floor_external_override(tmp_path: Path) -> None:
    out = tmp_path / "out"
    floor_path = tmp_path / "floor.json"
    floor_path.write_text(json.dumps({"10.2": "10.2.99"}), encoding="utf-8")
    result = run_render(
        *base_render_args(
            out,
            **{
                "--splunk-version": "10.2.2",
                "--svd-floor-file": str(floor_path),
            },
        ),
    )
    assert result.returncode != 0
    assert "10.2.99" in (result.stderr + result.stdout)


# ---------------------------------------------------------------------------
# 3. Forbidden non-existent setting names
# ---------------------------------------------------------------------------


FORBIDDEN_NONEXISTENT_SETTINGS = (
    "customHttpHeaders",
    "httpd_protect_login_csrf",
    "cookie_csrf",
    "splunkweb.cherrypy.tools.csrf.on",
    "tools.proxy.local",
    "serverRoot",
    "splunkdConnectionHost",
    "trustedProxiesList",
)


def test_web_conf_does_not_reference_nonexistent_settings(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    web_conf = (
        render_dir(out)
        / "splunk/apps/000_public_exposure_hardening/default/web.conf"
    ).read_text(encoding="utf-8")
    for setting in FORBIDDEN_NONEXISTENT_SETTINGS:
        # Real config-key form: setting at column 0 (or after whitespace) followed by '='.
        assert not re.search(
            rf"^\s*{re.escape(setting)}\s*=", web_conf, flags=re.MULTILINE
        ), f"web.conf references non-existent setting: {setting}"


def test_server_conf_does_not_reference_nonexistent_settings(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    server_conf = (
        render_dir(out)
        / "splunk/apps/000_public_exposure_hardening/default/server.conf"
    ).read_text(encoding="utf-8")
    for setting in FORBIDDEN_NONEXISTENT_SETTINGS:
        assert not re.search(
            rf"^\s*{re.escape(setting)}\s*=", server_conf, flags=re.MULTILINE
        ), f"server.conf references non-existent setting: {setting}"


# ---------------------------------------------------------------------------
# 4. Default-cert / known-default detection
# ---------------------------------------------------------------------------


def test_verify_certs_script_refuses_default_subjects(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    verify_certs = (
        render_dir(out) / "splunk/certificates/verify-certs.sh"
    ).read_text(encoding="utf-8")
    for token in ("SplunkServerDefaultCert", "SplunkCommonCA", "SplunkWebDefaultCert"):
        assert token in verify_certs


def test_authorize_conf_disables_admin_lockout_exemption(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    authorize_conf = (
        render_dir(out)
        / "splunk/apps/000_public_exposure_hardening/default/authorize.conf"
    ).read_text(encoding="utf-8")
    # The renderer flips the default never_lockout = enabled to disabled.
    assert "[role_admin]" in authorize_conf
    assert "never_lockout = disabled" in authorize_conf


def test_authorize_conf_removes_high_risk_capabilities(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    authorize_conf = (
        render_dir(out)
        / "splunk/apps/000_public_exposure_hardening/default/authorize.conf"
    ).read_text(encoding="utf-8")
    for cap in (
        "edit_cmd",
        "edit_scripted",
        "rest_apps_management",
        "delete_by_keyword",
        "change_authentication",
        "run_sendalert",
        "run_dump",
        "run_custom_command",
        "embed_report",
        "import_apps",
        "install_apps",
    ):
        assert f"{cap} = disabled" in authorize_conf, (
            f"high-risk capability {cap} not disabled on role_public_reader"
        )


# ---------------------------------------------------------------------------
# 5. Renderer enforces no-secrets-in-output
# ---------------------------------------------------------------------------


def test_no_pem_private_key_blocks_in_rendered_output(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    for path in render_dir(out).rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert "-----BEGIN " not in text or "PRIVATE KEY" not in text, (
                f"rendered file contains a PEM PRIVATE KEY block: {path}"
            )


def test_metadata_json_is_valid_and_does_not_contain_secrets(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    meta_path = render_dir(out) / "metadata.json"
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    secret_keys = {"password", "pass4SymmKey", "pass4symmkey", "token", "secret"}
    flat = json.dumps(data).lower()
    for sk in secret_keys:
        # The string "splunk_version" contains "version" — we want to forbid
        # actual secret keys, so look for `"<key>":` patterns.
        assert f'"{sk}":' not in flat, f"metadata.json contains a secret key: {sk}"


# ---------------------------------------------------------------------------
# 6. setup.sh phase / accept-public-exposure
# ---------------------------------------------------------------------------


def test_setup_apply_requires_accept_public_exposure(tmp_path: Path) -> None:
    out = tmp_path / "out"
    # log() in shared/lib writes to stdout; capture combined output.
    result = run_setup(
        "--phase", "apply",
        "--output-dir", str(out),
        "--public-fqdn", "splunk.example.com",
        "--proxy-cidr", "10.0.10.0/24",
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "accept-public-exposure" in combined, combined


def test_setup_render_only_does_not_require_accept(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_setup(
        "--phase", "render",
        "--output-dir", str(out),
        "--public-fqdn", "splunk.example.com",
        "--proxy-cidr", "10.0.10.0/24",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (render_dir(out) / "metadata.json").is_file()


def test_setup_dry_run_json(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_setup(
        "--phase", "render",
        "--output-dir", str(out),
        "--public-fqdn", "splunk.example.com",
        "--proxy-cidr", "10.0.10.0/24",
        "--dry-run", "--json",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "render_dir" in payload
    assert "svd_floor" in payload


# ---------------------------------------------------------------------------
# 7. All rendered shell scripts pass bash -n
# ---------------------------------------------------------------------------


def test_all_rendered_shell_scripts_parse(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(
        *base_render_args(
            out,
            **{
                "--topology": "shc-with-hec-and-hf",
                "--hec-fqdn": "hec.example.com",
                "--indexer-cluster-cidr": "10.0.20.0/24",
                "--bastion-cidr": "10.0.30.0/24",
                "--enable-web": "true",
                "--enable-hec": "true",
                "--enable-s2s": "true",
                "--hec-mtls": "true",
            },
        ),
    )
    assert result.returncode == 0, result.stderr

    failures: list[str] = []
    for path in render_dir(out).rglob("*.sh"):
        proc = subprocess.run(
            ["bash", "-n", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            failures.append(f"{path}: {proc.stderr}")
    assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# 8. Validation rejects malformed inputs
# ---------------------------------------------------------------------------


def test_render_rejects_invalid_fqdn(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(
        "--output-dir", str(out),
        "--public-fqdn", "not a fqdn",
        "--proxy-cidr", "10.0.10.0/24",
    )
    assert result.returncode != 0
    assert "fqdn" in (result.stderr + result.stdout).lower()


def test_render_rejects_invalid_cidr(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(
        "--output-dir", str(out),
        "--public-fqdn", "splunk.example.com",
        "--proxy-cidr", "not-a-cidr",
    )
    assert result.returncode != 0
    assert "cidr" in (result.stderr + result.stdout).lower()


def test_render_rejects_tls13_without_enable_flag(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(
        "--output-dir", str(out),
        "--public-fqdn", "splunk.example.com",
        "--proxy-cidr", "10.0.10.0/24",
        "--tls-policy", "tls12_13",
        "--enable-tls13", "false",
    )
    assert result.returncode != 0


# ---------------------------------------------------------------------------
# 9. Rendered web.conf has correct critical settings
# ---------------------------------------------------------------------------


def test_web_conf_has_critical_hardening_settings(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    web_conf = (
        render_dir(out)
        / "splunk/apps/000_public_exposure_hardening/default/web.conf"
    ).read_text(encoding="utf-8")

    expected_lines = (
        "enableSplunkWebSSL = true",
        "enable_insecure_login = false",
        "enableSplunkWebClientNetloc = false",  # CVE-2025-20371 SSRF mitigation
        "request.show_tracebacks = false",
        "tools.sessions.httponly = true",
        "tools.sessions.secure = true",
        "tools.sessions.forceSecure = true",
        "cookieSameSite = strict",
        "x_frame_options_sameorigin = true",
        "tools.proxy.on = true",
        "tools.proxy.base = https://splunk.example.com",
        "sslVersions = tls1.2",
    )
    for line in expected_lines:
        assert line in web_conf, f"web.conf is missing critical line: {line}"


def test_server_conf_has_critical_hardening_settings(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    server_conf = (
        render_dir(out)
        / "splunk/apps/000_public_exposure_hardening/default/server.conf"
    ).read_text(encoding="utf-8")

    expected_lines = (
        "[sslConfig]",
        "allowSslCompression = false",
        "allowSslRenegotiation = false",
        "sslVerifyServerCert = true",
        "[httpServer]",
        "sendStrictTransportSecurityHeader = true",
        "verboseLoginFailMsg = false",
    )
    for line in expected_lines:
        assert line in server_conf, f"server.conf is missing critical line: {line}"


# ---------------------------------------------------------------------------
# 10. Smoke script passes
# ---------------------------------------------------------------------------


def test_smoke_offline_script_passes() -> None:
    result = subprocess.run(
        ["bash", str(SMOKE_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"smoke_offline.sh failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# 11. SKILL.md frontmatter validates
# ---------------------------------------------------------------------------


def test_skill_md_frontmatter_passes_repo_check() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tests/check_skill_frontmatter.py")],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# 12. Forbidden settings absent from ALL rendered conf files
# ---------------------------------------------------------------------------


def test_no_forbidden_settings_in_any_conf(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(
        *base_render_args(
            out,
            **{
                "--topology": "shc-with-hec-and-hf",
                "--hec-fqdn": "hec.example.com",
                "--indexer-cluster-cidr": "10.0.20.0/24",
                "--enable-web": "true",
                "--enable-hec": "true",
                "--enable-s2s": "true",
            },
        ),
    )
    assert result.returncode == 0, result.stderr
    for conf in render_dir(out).rglob("*.conf"):
        text = conf.read_text(encoding="utf-8")
        for setting in FORBIDDEN_NONEXISTENT_SETTINGS:
            assert not re.search(
                rf"^\s*{re.escape(setting)}\s*=", text, flags=re.MULTILINE
            ), f"{conf} references non-existent setting: {setting}"


# ---------------------------------------------------------------------------
# 13. Proxy templates have key security headers
# ---------------------------------------------------------------------------


def test_nginx_template_has_security_headers(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    nginx_web = (render_dir(out) / "proxy/nginx/splunk-web.conf").read_text(encoding="utf-8")
    for header in (
        "Strict-Transport-Security",
        "X-Content-Type-Options",
        "Content-Security-Policy",
        "Referrer-Policy",
        "Permissions-Policy",
    ):
        assert header in nginx_web, f"nginx splunk-web.conf is missing header: {header}"
    # Streaming-search timeouts and security mitigations.
    assert "proxy_buffering          off;" in nginx_web or "proxy_buffering off" in nginx_web
    assert "limit_req_zone" in nginx_web
    assert "return_to" in nginx_web  # CVE-2025-20379 mitigation
    # CVE-2025-20384 mitigation now combines CR/LF + ANSI escape rejection.
    # The rendered nginx regex looks like [\r\n\x1b\x07]; check both forms.
    assert "\\r\\n" in nginx_web
    assert "\\x1b" in nginx_web
    assert "\\x07" in nginx_web


def test_haproxy_uses_http_server_close_not_httpclose(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    for cfg in (
        render_dir(out) / "proxy/haproxy/splunk-web.cfg",
        render_dir(out) / "proxy/haproxy/splunk-hec.cfg",
    ):
        text = cfg.read_text(encoding="utf-8")
        assert "option http-server-close" in text, f"{cfg} missing http-server-close"
        # The dangerous variant must NOT be present.
        for line in text.splitlines():
            stripped = line.strip()
            assert stripped != "option httpclose", (
                f"{cfg} uses 'option httpclose' which breaks HEC keepalive"
            )


# ---------------------------------------------------------------------------
# 14. Firewall snippets drop the forbidden public ports
# ---------------------------------------------------------------------------


def test_firewall_iptables_drops_dangerous_ports(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    iptables = (render_dir(out) / "proxy/firewall/iptables.rules").read_text(encoding="utf-8")
    for port in (8089, 8191, 9887, 8065):
        assert (
            f"--dport {port} -j DROP" in iptables
        ), f"iptables rules missing DROP for port {port}"


def test_firewall_nftables_drops_dangerous_ports(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    nftables = (render_dir(out) / "proxy/firewall/nftables.conf").read_text(encoding="utf-8")
    for port in ("8089", "8191", "9887", "8065"):
        assert port in nftables, f"nftables.conf missing port {port}"


# ---------------------------------------------------------------------------
# 15. Required references exist
# ---------------------------------------------------------------------------


def test_all_references_exist() -> None:
    references_dir = SKILL_ROOT / "references"
    required = (
        "tls-hardening.md",
        "reverse-proxy-templates.md",
        "waf-cdn-handoff.md",
        "auth-mfa-saml.md",
        "auth-ldap-hardening.md",
        "network-segmentation.md",
        "role-capability-hardening.md",
        "risky-command-safeguards.md",
        "splunk-secret-rotation.md",
        "cve-svd-tracking.md",
        "cve-svd-floor.json",
        "default-cert-fingerprints.json",
        "threat-intel.md",
        "disa-stig-cross-reference.md",
        "compliance-gap-statement.md",
        "dmz-heavy-forwarder-pattern.md",
        "operator-handoff-checklist.md",
        "setting-name-corrections.md",
        "fips-mode.md",
        "premium-apps-capability-overlay.md",
        "premium-apps-capability-overlay.json",
        "secure-gateway-handoff.md",
        "federated-search-provider-hardening.md",
    )
    missing = [name for name in required if not (references_dir / name).is_file()]
    assert not missing, f"missing references: {missing}"


def test_no_enable_install_apps_myth_in_references() -> None:
    """`enable_install_apps` is not a real Splunk setting. Documentation must
    not claim it exists; the SPL-upload surface is closed via authorize.conf
    capabilities + reverse-proxy denies for /services/apps/*."""
    skill_root = SKILL_ROOT
    found: list[str] = []
    for md_path in skill_root.rglob("*.md"):
        text = md_path.read_text(encoding="utf-8")
        # Match only the form `enable_install_apps = false` claim — accept
        # references that explicitly note the setting does not exist.
        for line in text.splitlines():
            if "enable_install_apps" in line and "does not exist" not in line and "no `enable_install_apps`" not in line and "no enable_install_apps" not in line:
                found.append(f"{md_path.relative_to(skill_root)}: {line.strip()}")
    assert not found, "References still claim enable_install_apps exists:\n" + "\n".join(found)


def test_svd_2025_1203_described_as_ansi_not_crlf() -> None:
    """SVD-2025-1203 is ANSI-escape injection at /en-US/static/, NOT
    CR/LF in headers. Docs must describe it correctly."""
    threat_intel = (SKILL_ROOT / "references/threat-intel.md").read_text(encoding="utf-8")
    cve_tracking = (SKILL_ROOT / "references/cve-svd-tracking.md").read_text(encoding="utf-8")
    for text, name in ((threat_intel, "threat-intel.md"), (cve_tracking, "cve-svd-tracking.md")):
        # Must mention the real attack vector
        assert "ANSI" in text, f"{name} doesn't mention ANSI escape codes for SVD-2025-1203"
        assert "/en-US/static/" in text, (
            f"{name} doesn't mention the /en-US/static/ endpoint for SVD-2025-1203"
        )


def test_cve_svd_floor_json_is_valid() -> None:
    floor_path = SKILL_ROOT / "references/cve-svd-floor.json"
    data = json.loads(floor_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    # v2 structured shape: top-level splunk_enterprise dict.
    assert "splunk_enterprise" in data, "cve-svd-floor.json missing splunk_enterprise key"
    for series, version in data["splunk_enterprise"].items():
        if str(series).startswith("_"):
            continue
        assert re.match(r"^\d+\.\d+$", series)
        assert re.match(r"^\d+\.\d+\.\d+$", version)


def test_embedded_floor_matches_json() -> None:
    floor_path = SKILL_ROOT / "references/cve-svd-floor.json"
    file_floor = json.loads(floor_path.read_text(encoding="utf-8"))
    embedded = render_module.EMBEDDED_SVD_FLOOR
    splunk_enterprise = {
        k: v for k, v in file_floor["splunk_enterprise"].items()
        if not str(k).startswith("_")
    }
    assert splunk_enterprise == embedded, (
        "embedded SVD floor in render_assets.py disagrees with references/cve-svd-floor.json"
    )


def test_cve_svd_floor_json_includes_sg_floor() -> None:
    """SG-app has its own SVD class (SVD-2025-0302 etc.); v2 adds per-branch floor."""
    floor_path = SKILL_ROOT / "references/cve-svd-floor.json"
    data = json.loads(floor_path.read_text(encoding="utf-8"))
    assert "splunk_secure_gateway" in data
    sg = data["splunk_secure_gateway"]
    assert sg["3.9"] == "3.9.10"
    assert sg["3.8"] == "3.8.58"
    assert sg["3.7"] == "3.7.28"


def test_embedded_sg_floor_matches_json() -> None:
    floor_path = SKILL_ROOT / "references/cve-svd-floor.json"
    data = json.loads(floor_path.read_text(encoding="utf-8"))
    file_sg = {
        k: v for k, v in data["splunk_secure_gateway"].items()
        if not str(k).startswith("_")
    }
    assert file_sg == render_module.EMBEDDED_SG_FLOOR


# ---------------------------------------------------------------------------
# LDAP rendering correctness (v2)
# ---------------------------------------------------------------------------


def _ldap_args(out: Path, **overrides: str) -> list[str]:
    base = {
        "--output-dir": str(out),
        "--public-fqdn": "splunk.example.com",
        "--proxy-cidr": "10.0.10.0/24",
        "--auth-mode": "ldap",
        "--ldap-host": "ad.example.com",
        "--ldap-bind-dn": "cn=svc_splunk,ou=Service,dc=example,dc=com",
        "--ldap-bind-password-file": "/tmp/ldap.pwd",
        "--ldap-user-base-dn": "ou=Users,dc=example,dc=com",
        "--ldap-group-base-dn": "ou=Groups,dc=example,dc=com",
        "--ldap-public-reader-group": "SplunkPublicReaders",
    }
    base.update(overrides)
    flat: list[str] = []
    for k, v in base.items():
        flat.extend([k, v])
    return flat


def _ldap_auth_conf(out: Path) -> str:
    return (
        render_dir(out)
        / "splunk/apps/000_public_exposure_hardening/default/authentication.conf"
    ).read_text(encoding="utf-8")


def test_ldap_auth_mode_renders_authentication_conf(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*_ldap_args(out))
    assert result.returncode == 0, result.stderr
    text = _ldap_auth_conf(out)
    assert "authType = LDAP" in text
    assert "authSettings = ldaphost" in text
    assert "[ldaphost]" in text
    assert "[roleMap_ldaphost]" in text


def test_ldap_uses_semicolon_for_multi_tree_dn(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(
        *_ldap_args(
            out,
            **{
                "--ldap-user-base-dn": "ou=US,dc=example,dc=com;ou=EU,dc=example,dc=com",
                "--ldap-group-base-dn": "ou=Groups,dc=example,dc=com",
            },
        ),
    )
    assert result.returncode == 0, result.stderr
    text = _ldap_auth_conf(out)
    # Multi-tree must use ';' (the spec separator) NOT ','.
    assert "userBaseDN = ou=US,dc=example,dc=com;ou=EU,dc=example,dc=com" in text


def test_ldap_uses_lowercase_sizelimit(tmp_path: Path) -> None:
    """Spec spelling is `sizelimit` (lowercase). Splunk silently ignores camelCase."""
    out = tmp_path / "out"
    result = run_render(*_ldap_args(out))
    assert result.returncode == 0, result.stderr
    text = _ldap_auth_conf(out)
    assert re.search(r"^sizelimit = \d+", text, flags=re.MULTILINE), (
        "lowercase 'sizelimit' missing from rendered LDAP stanza"
    )
    assert not re.search(r"^sizeLimit", text, flags=re.MULTILINE), (
        "camelCase 'sizeLimit' should not appear (Splunk silently ignores it)"
    )


def test_ldap_does_not_emit_per_stanza_tls_keys(tmp_path: Path) -> None:
    """LDAP TLS lives in $SPLUNK_HOME/etc/openldap/ldap.conf, NOT in the
    [<authSettings-key>] strategy stanza. Emitting these would mislead operators
    into thinking TLS is configured when it is not."""
    out = tmp_path / "out"
    result = run_render(*_ldap_args(out))
    assert result.returncode == 0, result.stderr
    text = _ldap_auth_conf(out)
    # Strategy block: from [ldaphost] to the next [ section.
    strategy = re.search(
        r"^\[ldaphost\]\n(.*?)(?=^\[)", text, flags=re.MULTILINE | re.DOTALL
    ).group(1)
    for forbidden in ("sslVersions", "cipherSuite", "ecdhCurves"):
        assert not re.search(rf"^{forbidden}\b", strategy, flags=re.MULTILINE), (
            f"{forbidden} must not appear in the LDAP strategy stanza"
        )


def test_ldap_default_anonymous_referrals_off(tmp_path: Path) -> None:
    """Spec default is 1 (insecure); the renderer hardens to 0."""
    out = tmp_path / "out"
    result = run_render(*_ldap_args(out))
    assert result.returncode == 0, result.stderr
    text = _ldap_auth_conf(out)
    assert re.search(r"^anonymous_referrals = 0$", text, flags=re.MULTILINE)


def test_ldap_role_map_direction_splunk_role_on_left(tmp_path: Path) -> None:
    """[roleMap_<strategy>] format is `splunk_role = ldap_group1;ldap_group2`."""
    out = tmp_path / "out"
    result = run_render(*_ldap_args(out))
    assert result.returncode == 0, result.stderr
    text = _ldap_auth_conf(out)
    assert "[roleMap_ldaphost]" in text
    assert re.search(
        r"^role_public_reader = SplunkPublicReaders$", text, flags=re.MULTILINE
    ), "Splunk role on LEFT, LDAP group on RIGHT"


def test_ldap_timelimit_capped_at_30(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*_ldap_args(out, **{"--ldap-time-limit": "60"}))
    assert result.returncode != 0
    assert "time-limit" in (result.stderr + result.stdout).lower()


def test_ldap_network_timeout_must_exceed_timelimit(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(
        *_ldap_args(
            out,
            **{
                "--ldap-time-limit": "20",
                "--ldap-network-timeout": "10",
            },
        ),
    )
    assert result.returncode != 0
    assert "network-timeout" in (result.stderr + result.stdout).lower() or \
           "network_timeout" in (result.stderr + result.stdout).lower()


def test_ldap_cleartext_refused_without_ack(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*_ldap_args(out, **{"--ldap-ssl-enabled": "false"}))
    assert result.returncode != 0
    assert "allow-cleartext-ldap" in (result.stderr + result.stdout)


def test_ldap_cleartext_allowed_with_ack(tmp_path: Path) -> None:
    out = tmp_path / "out"
    args = _ldap_args(out, **{"--ldap-ssl-enabled": "false"})
    args.append("--allow-cleartext-ldap")
    result = run_render(*args)
    assert result.returncode == 0, result.stderr
    text = _ldap_auth_conf(out)
    assert "SSLEnabled = 0" in text


def test_ldap_anonymous_bind_refused_without_ack(tmp_path: Path) -> None:
    """Empty --ldap-bind-dn (anonymous bind) requires --allow-anonymous-ldap-bind."""
    out = tmp_path / "out"
    base = {
        "--output-dir": str(out),
        "--public-fqdn": "splunk.example.com",
        "--proxy-cidr": "10.0.10.0/24",
        "--auth-mode": "ldap",
        "--ldap-host": "ad.example.com",
        "--ldap-user-base-dn": "ou=Users,dc=example,dc=com",
        "--ldap-group-base-dn": "ou=Groups,dc=example,dc=com",
        # Note: --ldap-bind-dn is intentionally absent (default empty).
    }
    flat: list[str] = []
    for k, v in base.items():
        flat.extend([k, v])
    result = run_render(*flat)
    assert result.returncode != 0
    assert "allow-anonymous-ldap-bind" in (result.stderr + result.stdout)


def test_ldap_does_not_embed_bind_password(tmp_path: Path) -> None:
    """Bind password file is referenced, value never appears in any rendered file."""
    out = tmp_path / "out"
    pw_file = tmp_path / "ldap.pwd"
    pw_file.write_text("super-secret-bind-password-value\n", encoding="utf-8")
    result = run_render(*_ldap_args(out, **{"--ldap-bind-password-file": str(pw_file)}))
    assert result.returncode == 0, result.stderr
    for path in render_dir(out).rglob("*"):
        if path.is_file():
            assert "super-secret-bind-password-value" not in path.read_text(
                encoding="utf-8", errors="ignore"
            ), f"bind password leaked into {path}"


def test_ldap_renders_openldap_ldap_conf_example(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*_ldap_args(out))
    assert result.returncode == 0, result.stderr
    stub = (
        render_dir(out)
        / "splunk/apps/000_public_exposure_hardening/default/openldap-ldap.conf.example"
    ).read_text(encoding="utf-8")
    assert "TLS_REQCERT" in stub and "demand" in stub
    assert "TLS_PROTOCOL_MIN" in stub and "3.3" in stub


# ---------------------------------------------------------------------------
# Scripted-auth refusal (v2)
# ---------------------------------------------------------------------------


def test_scripted_auth_refusal_in_preflight(tmp_path: Path) -> None:
    """Default preflight body includes a Scripted-auth refusal step."""
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    preflight = (render_dir(out) / "preflight.sh").read_text(encoding="utf-8")
    assert "authType" in preflight and "Scripted" in preflight
    assert "allow-scripted-auth" in preflight or "allow_scripted_auth" in preflight


def test_scripted_auth_ack_changes_preflight_body(tmp_path: Path) -> None:
    """When --allow-scripted-auth is passed, the preflight WARN-not-fails on Scripted."""
    out = tmp_path / "out"
    args = base_render_args(out)
    args.append("--allow-scripted-auth")
    result = run_render(*args)
    assert result.returncode == 0, result.stderr
    preflight = (render_dir(out) / "preflight.sh").read_text(encoding="utf-8")
    assert "allow_scripted_auth=true" in preflight


# ---------------------------------------------------------------------------
# Premium-apps overlay (v2)
# ---------------------------------------------------------------------------


def test_premium_apps_overlay_doc_and_json_exist() -> None:
    references_dir = SKILL_ROOT / "references"
    assert (references_dir / "premium-apps-capability-overlay.md").is_file()
    assert (references_dir / "premium-apps-capability-overlay.json").is_file()


def test_premium_apps_overlay_json_is_valid_with_pinned_versions() -> None:
    overlay_path = SKILL_ROOT / "references/premium-apps-capability-overlay.json"
    data = json.loads(overlay_path.read_text(encoding="utf-8"))
    assert "tier_a" in data and "tier_b" in data
    for app, body in data["tier_a"].items():
        assert "verified_version" in body, f"{app} missing verified_version"
        assert "source_url" in body, f"{app} missing source_url"
        assert body["source_url"].startswith("http"), (
            f"{app} source_url must be a URL"
        )


def test_es_84_overlay_marks_list_inputs_must_not_remove() -> None:
    """list_inputs is the ES-8.4 special case: ERROR (not WARN) on removal."""
    overlay_path = SKILL_ROOT / "references/premium-apps-capability-overlay.json"
    data = json.loads(overlay_path.read_text(encoding="utf-8"))
    es = data["tier_a"]["SplunkEnterpriseSecuritySuite"]
    assert "list_inputs" in es["must_not_remove"]


def test_role_capability_hardening_links_to_premium_overlay() -> None:
    role_md = (SKILL_ROOT / "references/role-capability-hardening.md").read_text(
        encoding="utf-8"
    )
    # Cross-link must mention the overlay (or its filename).
    assert "premium-apps" in role_md.lower() or \
           "premium apps" in role_md.lower(), \
           "role-capability-hardening.md must cross-link to premium apps overlay"


def test_premium_apps_preflight_step_in_rendered_preflight(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    preflight = (render_dir(out) / "preflight.sh").read_text(encoding="utf-8")
    # Tier-A and Tier-B should both appear as bash variables in the preflight.
    assert "tier_a" in preflight
    assert "tier_b" in preflight


def test_premium_apps_overlay_avoids_known_stale_urls() -> None:
    overlay_path = SKILL_ROOT / "references/premium-apps-capability-overlay.json"
    data = json.loads(overlay_path.read_text(encoding="utf-8"))
    stale = (
        "Documentation/ES/latest/Install/Capabilityreference",
        "Documentation/ARI/latest/Install/RolesAndCapabilities",
    )
    for app, body in data["tier_a"].items():
        for s in stale:
            assert s not in body.get("source_url", ""), (
                f"{app} source_url uses known-stale (404) URL: {s}"
            )


# ---------------------------------------------------------------------------
# Federation rotate helper (v2)
# ---------------------------------------------------------------------------


def test_federation_rotate_helper_in_generated_files(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    fed_rotate = render_dir(out) / "splunk/rotate-federation-service-account.sh"
    assert fed_rotate.is_file()
    assert fed_rotate.stat().st_mode & 0o111, "rotate helper must be executable"


def test_federation_helper_does_not_invoke_pass4symmkey(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    fed_rotate = (render_dir(out) / "splunk/rotate-federation-service-account.sh").read_text(
        encoding="utf-8"
    )
    # Forbidden patterns: cluster-config / shcluster-config rotation, or
    # pass4SymmKey assignment in code (not in comments).
    for line in fed_rotate.splitlines():
        # Skip pure comments.
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        # `splunk edit cluster-config` / `splunk edit shcluster-config`.
        assert not re.search(r"splunk\s+edit\s+(cluster|shcluster)-config", line)
        # pass4SymmKey assignment.
        assert "pass4SymmKey =" not in line


def test_federation_helper_uses_file_based_password(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    fed_rotate = (render_dir(out) / "splunk/rotate-federation-service-account.sh").read_text(
        encoding="utf-8"
    )
    assert "new_password_file" in fed_rotate
    assert "password-file" in fed_rotate


# ---------------------------------------------------------------------------
# SG handoff (v2)
# ---------------------------------------------------------------------------


def test_sg_handoff_doc_uses_correct_spacebridge_url() -> None:
    sg_doc = (SKILL_ROOT / "references/secure-gateway-handoff.md").read_text(
        encoding="utf-8"
    )
    assert "prod.spacebridge.spl.mobi" in sg_doc
    # Must NOT use the old/wrong URL.
    assert "spacebridge.splunk.com" not in sg_doc, (
        "SG handoff references the WRONG spacebridge URL"
    )


def test_sg_handoff_describes_e2e_auth_correctly() -> None:
    sg_doc = (SKILL_ROOT / "references/secure-gateway-handoff.md").read_text(
        encoding="utf-8"
    )
    # Mobile clients authenticate end-to-end to the SG app via ECC + Libsodium.
    assert "ECC" in sg_doc
    assert "Libsodium" in sg_doc or "libsodium" in sg_doc.lower()
    assert "cannot decrypt" in sg_doc.lower()


def test_sg_preflight_step_in_rendered_preflight(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(*base_render_args(out))
    assert result.returncode == 0, result.stderr
    preflight = (render_dir(out) / "preflight.sh").read_text(encoding="utf-8")
    assert "splunk_secure_gateway" in preflight
    assert "3.9.10" in preflight or "3.8.58" in preflight


# ---------------------------------------------------------------------------
# Federation hardening doc (v2)
# ---------------------------------------------------------------------------


def test_federation_hardening_doc_corrects_pass4symmkey_myth() -> None:
    fed_doc = (
        SKILL_ROOT / "references/federated-search-provider-hardening.md"
    ).read_text(encoding="utf-8")
    # Must mention service-account auth.
    assert "service account" in fed_doc.lower() or "service-account" in fed_doc.lower()
    # Must explicitly correct the pass4SymmKey misconception. Accept any of
    # the documented phrasings:
    #   - "uses pass4SymmKey ... It does not"
    #   - "NOT pass4SymmKey"
    #   - "does NOT touch federation credentials"
    correction_phrases = (
        "It does not",
        "NOT pass4SymmKey",
        "not pass4SymmKey",
        "does NOT touch federation",
        "does not use pass4SymmKey",
    )
    assert any(p.lower() in fed_doc.lower() for p in correction_phrases), (
        "federated-search-provider-hardening.md must explicitly correct the pass4SymmKey misconception"
    )


# ---------------------------------------------------------------------------
# Cross-skill table (v2)
# ---------------------------------------------------------------------------


def test_cross_skill_table_lists_handoff_partners() -> None:
    skill_md = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    required_partners = (
        "splunk-hec-service-setup",
        "splunk-enterprise-host-setup",
        "splunk-indexer-cluster-setup",
        "splunk-agent-management-setup",
        "splunk-license-manager-setup",
        "splunk-cloud-acs-allowlist-setup",
        "splunk-federated-search-setup",
        "splunk-monitoring-console-setup",
        "splunk-connect-for-syslog-setup",
        "splunk-connect-for-snmp-setup",
        "splunk-mcp-server-setup",
        "splunk-stream-setup",
        "splunk-index-lifecycle-smartstore-setup",
        "splunk-enterprise-security-config",
    )
    for partner in required_partners:
        assert partner in skill_md, f"SKILL.md cross-skill table missing partner: {partner}"


# ---------------------------------------------------------------------------
# Setting-name corrections (v2 — LDAP misnames)
# ---------------------------------------------------------------------------


def test_setting_name_corrections_includes_ldap_misnames() -> None:
    doc = (SKILL_ROOT / "references/setting-name-corrections.md").read_text(
        encoding="utf-8"
    )
    expected_misnames = (
        "sizeLimit",  # camelCase v lowercase sizelimit
        "bindPassword",
        "enableTLSLDAP",
        "userToRoleMap_",  # SAML-only; not LDAP
        "pass4SymmKey",  # the federation correction
    )
    for misname in expected_misnames:
        assert misname in doc, f"setting-name-corrections.md missing entry: {misname}"


# ---------------------------------------------------------------------------
# Auth-mode list now includes ldap
# ---------------------------------------------------------------------------


def test_auth_mode_choices_include_ldap_and_reject_unknown(tmp_path: Path) -> None:
    """The renderer's --auth-mode accepts 'ldap' (verified via the LDAP rendering
    tests above) AND must REJECT any unknown value with a non-zero exit."""
    out = tmp_path / "out"
    result = run_render(
        "--output-dir", str(out),
        "--public-fqdn", "splunk.example.com",
        "--proxy-cidr", "10.0.10.0/24",
        "--auth-mode", "kerberos",  # NOT a valid Splunk authType
    )
    assert result.returncode != 0, "Renderer accepted an unknown --auth-mode value"
    combined = result.stdout + result.stderr
    # argparse 'choices' rejects with a specific message; accept any of the
    # phrasings used across Python versions.
    assert any(s in combined for s in ("invalid choice", "kerberos", "argument --auth-mode")), (
        f"--auth-mode invalid-choice rejection lacks a clear error: {combined}"
    )


def test_renderer_rejects_invalid_ldap_anonymous_referrals(tmp_path: Path) -> None:
    """--ldap-anonymous-referrals only accepts 0 or 1."""
    out = tmp_path / "out"
    result = run_render(
        *_ldap_args(out, **{"--ldap-anonymous-referrals": "2"}),
    )
    assert result.returncode != 0


def test_renderer_rejects_invalid_ldap_sizelimit(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(
        *_ldap_args(out, **{"--ldap-sizelimit": "0"}),
    )
    assert result.returncode != 0
    assert "sizelimit" in (result.stderr + result.stdout).lower()


def test_renderer_rejects_unlimited_ldap_network_timeout(tmp_path: Path) -> None:
    """Splunk allows -1 (unlimited) per spec, but unlimited blocking is unsafe
    for a public-internet-facing search head."""
    out = tmp_path / "out"
    result = run_render(
        *_ldap_args(out, **{"--ldap-network-timeout": "-1"}),
    )
    assert result.returncode != 0
    combined = result.stderr + result.stdout
    assert "unlimited" in combined.lower() or "-1" in combined


def test_apply_search_head_does_not_unconditionally_assign_unused_pass4_var() -> None:
    """Regression: an earlier version of the cluster-manager helper read the
    pass4SymmKey value into a shell variable (pass4="$(cat ...)") that was then
    immediately unset and never used. The renderer should rely on
    -auth-passphrase-file alone."""
    skill_root = SKILL_ROOT
    render_module_local = render_module
    # Inspect the source of the cluster-manager renderer.
    import inspect
    src = inspect.getsource(render_module_local.render_apply_cluster_manager)
    assert "pass4=\"$(cat" not in src, (
        "render_apply_cluster_manager should not read pass4SymmKey into a shell variable"
    )
