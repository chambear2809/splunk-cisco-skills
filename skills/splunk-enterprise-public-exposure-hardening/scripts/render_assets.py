#!/usr/bin/env python3
"""Render Splunk Enterprise public-internet-exposure hardening assets.

This renderer is render-first and never embeds secret values in the output.
Secrets (admin password, pass4SymmKey, SSL key password, IdP signing key)
live in operator-managed local files referenced by absolute path; the
rendered apply scripts read those files at apply time.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
from pathlib import Path


# ---------------------------------------------------------------------------
# Closed manifest of every file the renderer is allowed to emit.
# ---------------------------------------------------------------------------

GENERATED_FILES: set[str] = {
    "README.md",
    "metadata.json",
    "preflight.sh",
    "validate.sh",
    # Splunk app payload
    "splunk/apps/000_public_exposure_hardening/default/app.conf",
    "splunk/apps/000_public_exposure_hardening/default/web.conf",
    "splunk/apps/000_public_exposure_hardening/default/server.conf",
    "splunk/apps/000_public_exposure_hardening/default/inputs.conf",
    "splunk/apps/000_public_exposure_hardening/default/outputs.conf",
    "splunk/apps/000_public_exposure_hardening/default/authentication.conf",
    "splunk/apps/000_public_exposure_hardening/default/authorize.conf",
    "splunk/apps/000_public_exposure_hardening/default/limits.conf",
    "splunk/apps/000_public_exposure_hardening/default/commands.conf",
    "splunk/apps/000_public_exposure_hardening/default/props.conf",
    "splunk/apps/000_public_exposure_hardening/default/splunk-launch.conf",
    "splunk/apps/000_public_exposure_hardening/metadata/default.meta",
    "splunk/apps/000_public_exposure_hardening/metadata/local.meta",
    # Apply / rotate helpers
    "splunk/apply-search-head.sh",
    "splunk/apply-hec-tier.sh",
    "splunk/apply-s2s-receiver.sh",
    "splunk/apply-heavy-forwarder.sh",
    "splunk/apply-deployer.sh",
    "splunk/apply-cluster-manager.sh",
    "splunk/apply-license-manager.sh",
    "splunk/rotate-pass4symmkey.sh",
    "splunk/rotate-splunk-secret.sh",
    "splunk/certificates/verify-certs.sh",
    "splunk/certificates/generate-csr-template.sh",
    "splunk/certificates/README.md",
    # Reverse proxy templates
    "proxy/nginx/splunk-web.conf",
    "proxy/nginx/splunk-hec.conf",
    "proxy/nginx/README.md",
    "proxy/haproxy/splunk-web.cfg",
    "proxy/haproxy/splunk-hec.cfg",
    "proxy/haproxy/README.md",
    "proxy/firewall/iptables.rules",
    "proxy/firewall/nftables.conf",
    "proxy/firewall/firewalld.xml",
    "proxy/firewall/aws-sg.json",
    "proxy/firewall/README.md",
    # Operator handoff
    "handoff/operator-checklist.md",
    "handoff/waf-cloudflare.md",
    "handoff/waf-aws.md",
    "handoff/waf-f5-imperva.md",
    "handoff/saml-idp-handoff.md",
    "handoff/duo-mfa-handoff.md",
    "handoff/certificate-procurement.md",
    "handoff/soc-alerting-runbook.md",
    "handoff/backup-and-restore.md",
    "handoff/incident-response-splunk-secret.md",
    "handoff/compliance-control-mapping.md",
}


# ---------------------------------------------------------------------------
# Embedded SVD floor. The renderer ships this so an offline / disconnected
# operator still gets the floor enforcement; --svd-floor-file overrides.
# ---------------------------------------------------------------------------

EMBEDDED_SVD_FLOOR: dict[str, str] = {
    "10.2": "10.2.2",
    "10.0": "10.0.5",
    "9.4": "9.4.10",
    "9.3": "9.3.11",
}


# ---------------------------------------------------------------------------
# Hardened SSL / TLS values shared across web.conf, server.conf, inputs.conf,
# and outputs.conf.
# ---------------------------------------------------------------------------

CIPHER_SUITE = (
    "ECDHE-ECDSA-AES256-GCM-SHA384:"
    "ECDHE-RSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-AES128-GCM-SHA256:"
    "ECDHE-RSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-AES256-SHA384:"
    "ECDHE-RSA-AES256-SHA384:"
    "ECDHE-ECDSA-AES128-SHA256:"
    "ECDHE-RSA-AES128-SHA256"
)

ECDH_CURVES = "prime256v1, secp384r1, secp521r1"

# Default Splunk-shipped server cert fingerprints (subject CN). Preflight
# refuses while these are still in use. The fingerprint set lives in
# references/default-cert-fingerprints.json; this list is the canonical
# subject-CN substring set to look for.
DEFAULT_CERT_SUBJECT_TOKENS = (
    "SplunkServerDefaultCert",
    "SplunkCommonCA",
    "SplunkWebDefaultCert",
)

# High-risk capabilities removed from non-admin roles. See SKILL.md.
PUBLIC_READER_REMOVED_CAPABILITIES = (
    "edit_cmd",
    "edit_cmd_internal",
    "edit_scripted",
    "rest_apps_management",
    "rest_apps_install",
    "rest_properties_set",
    "run_collect",
    "run_mcollect",
    "run_debug_commands",
    "run_msearch",
    "run_sendalert",
    "run_dump",
    "run_custom_command",
    "embed_report",
    "change_authentication",
    "delete_by_keyword",
    "accelerate_search",
    "dispatch_rest_to_indexers",
    "import_apps",
    "install_apps",
    "edit_authentication",
    "edit_user",
    "edit_roles",
    "edit_token_http",
    "edit_token_settings",
    "edit_indexer_cluster",
    "edit_input_defaults",
    "edit_modinput_admon",
    "edit_modinput_monitor",
    "edit_modinput_perfmon",
    "edit_modinput_winhostmon",
    "edit_search_scheduler",
    "edit_remote_apps_management",
    "pattern_detect",
    "request_pstacks",
    "request_remote_tok",
)

# Risky SPL commands marked as is_risky=1 in commands.conf.
RISKY_COMMANDS = (
    "collect",
    "delete",
    "dump",
    "map",
    "mcollect",
    "meventcollect",
    "outputcsv",
    "outputlookup",
    "run",
    "runshellscript",
    "script",
    "sendalert",
    "sendemail",
    "tscollect",
)


# ---------------------------------------------------------------------------
# Argument parsing and validation
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render Splunk Enterprise public-exposure hardening assets.",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--topology",
        choices=("single-search-head", "shc-with-hec", "shc-with-hec-and-hf"),
        default="single-search-head",
    )
    parser.add_argument("--public-fqdn", required=True)
    parser.add_argument("--hec-fqdn", default="")
    parser.add_argument("--proxy-cidr", required=True)
    parser.add_argument("--indexer-cluster-cidr", default="")
    parser.add_argument("--bastion-cidr", default="")
    parser.add_argument("--enable-web", choices=("true", "false"), default="true")
    parser.add_argument("--enable-hec", choices=("true", "false"), default="false")
    parser.add_argument("--enable-s2s", choices=("true", "false"), default="false")
    parser.add_argument("--hec-mtls", choices=("true", "false"), default="false")
    parser.add_argument("--s2s-mtls", choices=("true", "false"), default="true")
    parser.add_argument("--forwarder-mtls", choices=("true", "false"), default="true")
    parser.add_argument("--splunk-home", default="/opt/splunk")
    parser.add_argument("--service-user", default="splunk")
    parser.add_argument("--splunk-version", default="10.2.2")
    parser.add_argument("--tls-policy", choices=("tls12", "tls12_13"), default="tls12")
    parser.add_argument("--enable-tls13", choices=("true", "false"), default="false")
    parser.add_argument("--ca-bundle-path", default="/opt/splunk/etc/auth/cabundle.pem")
    parser.add_argument(
        "--server-cert-path",
        default="/opt/splunk/etc/auth/splunkweb/cert.pem",
    )
    parser.add_argument(
        "--server-key-path",
        default="/opt/splunk/etc/auth/splunkweb/privkey.pem",
    )
    parser.add_argument("--required-sans", default="")
    parser.add_argument(
        "--auth-mode",
        choices=("native", "saml", "reverse-proxy-sso"),
        default="native",
    )
    parser.add_argument("--saml-idp-metadata-path", default="")
    parser.add_argument("--saml-entity-id", default="")
    parser.add_argument("--saml-signature-algorithm", default="RSA-SHA256")
    parser.add_argument("--proxy-sso-trusted-ip", default="")
    parser.add_argument("--min-password-length", type=int, default=14)
    parser.add_argument("--expire-password-days", type=int, default=90)
    parser.add_argument("--lockout-attempts", type=int, default=5)
    parser.add_argument("--lockout-mins", type=int, default=30)
    parser.add_argument("--password-history-count", type=int, default=24)
    parser.add_argument("--public-reader-allowed-indexes", default="main,summary")
    parser.add_argument("--public-reader-srch-jobs-quota", type=int, default=3)
    parser.add_argument("--public-reader-srch-max-time", type=int, default=300)
    parser.add_argument("--public-reader-srch-time-win", type=int, default=86400)
    parser.add_argument("--public-reader-srch-disk-quota", type=int, default=100)
    parser.add_argument("--hec-max-content-length", type=int, default=838860800)
    parser.add_argument("--login-rate-per-minute", type=int, default=5)
    parser.add_argument("--streaming-search-timeout", type=int, default=600)
    parser.add_argument("--admin-password-file", default="")
    parser.add_argument("--pass4symmkey-file", default="")
    parser.add_argument("--ssl-key-password-file", default="")
    parser.add_argument("--saml-signing-cert-file", default="")
    parser.add_argument("--saml-signing-key-file", default="")
    parser.add_argument("--hec-mtls-ca-bundle-file", default="")
    parser.add_argument("--external-probe-cmd", default="")
    parser.add_argument("--svd-floor-file", default="")
    parser.add_argument("--enable-fips", choices=("true", "false"), default="false")
    parser.add_argument("--fips-version", choices=("140-2", "140-3"), default="140-3")
    parser.add_argument(
        "--allowed-unarchive-commands",
        default="",
        help="Comma-separated allowlist for SVD-2026-0302 unarchive commands (defense in depth alongside removing edit_cmd).",
    )
    parser.add_argument("--accept-public-exposure", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

FQDN_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9][A-Za-z0-9\-]{0,62}(?:\.[A-Za-z0-9][A-Za-z0-9\-]{0,62})+$")
CIDR_RE = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$")
SETTING_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
INDEX_NAME_RE = re.compile(r"^[_A-Za-z0-9][A-Za-z0-9_.-]*$")


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


def csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def bool_value(value: str) -> bool:
    return value.lower() == "true"


def bool_conf(value: str) -> str:
    return "1" if bool_value(value) else "0"


def validate_fqdn(value: str, option: str) -> None:
    if not value:
        die(f"{option} is required.")
    if not FQDN_RE.match(value):
        die(f"{option} must be a fully-qualified domain name: {value!r}")


def validate_cidr(value: str, option: str) -> None:
    if not value:
        return
    for entry in csv_list(value):
        if not CIDR_RE.match(entry):
            die(f"{option} contains an invalid IPv4 CIDR: {entry!r}")


def validate_index_name(value: str, option: str) -> None:
    if not INDEX_NAME_RE.match(value):
        die(f"{option} is not a valid Splunk index name: {value!r}")


def validate(args: argparse.Namespace) -> None:
    validate_fqdn(args.public_fqdn, "--public-fqdn")
    if args.hec_fqdn:
        validate_fqdn(args.hec_fqdn, "--hec-fqdn")
    validate_cidr(args.proxy_cidr, "--proxy-cidr")
    validate_cidr(args.indexer_cluster_cidr, "--indexer-cluster-cidr")
    validate_cidr(args.bastion_cidr, "--bastion-cidr")
    if args.enable_hec == "true" and not args.hec_fqdn:
        # HEC can ride on the same FQDN, but warn.
        args.hec_fqdn = args.public_fqdn
    for idx in csv_list(args.public_reader_allowed_indexes):
        validate_index_name(idx, "--public-reader-allowed-indexes")
    if args.hec_max_content_length < 1024:
        die("--hec-max-content-length is unrealistically small.")
    if args.login_rate_per_minute < 1 or args.login_rate_per_minute > 600:
        die("--login-rate-per-minute must be between 1 and 600.")
    if args.streaming_search_timeout < 30 or args.streaming_search_timeout > 86400:
        die("--streaming-search-timeout must be between 30 and 86400 seconds.")
    if args.auth_mode == "saml" and not args.saml_idp_metadata_path:
        die("--saml-idp-metadata-path is required when --auth-mode=saml.")
    if args.auth_mode == "reverse-proxy-sso" and not args.proxy_sso_trusted_ip:
        die("--proxy-sso-trusted-ip is required when --auth-mode=reverse-proxy-sso.")
    if args.tls_policy == "tls12_13" and args.enable_tls13 != "true":
        die("--tls-policy=tls12_13 requires --enable-tls13=true.")


def parse_version(value: str) -> tuple[int, int, int]:
    parts = value.split("-", 1)[0].split(".")
    if len(parts) < 2:
        die(f"unparseable Splunk version: {value!r}")
    nums = []
    for part in parts:
        if not part.isdigit():
            die(f"unparseable Splunk version: {value!r}")
        nums.append(int(part))
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])


def load_svd_floor(args: argparse.Namespace) -> dict[str, str]:
    if args.svd_floor_file:
        try:
            data = json.loads(Path(args.svd_floor_file).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            die(f"could not read --svd-floor-file: {exc}")
        if not isinstance(data, dict):
            die("svd-floor JSON must be an object mapping series to fixed version.")
        return {str(k): str(v) for k, v in data.items()}
    return dict(EMBEDDED_SVD_FLOOR)


def check_svd_floor(args: argparse.Namespace, floor: dict[str, str]) -> None:
    running = parse_version(args.splunk_version)
    series = f"{running[0]}.{running[1]}"
    fixed = floor.get(series)
    if fixed is None:
        # Unknown series: warn via comment but don't refuse — let preflight
        # decide if upgrade is appropriate.
        return
    if running < parse_version(fixed):
        die(
            f"Splunk version {args.splunk_version} is below the SVD floor "
            f"for the {series}.x series ({fixed}). Upgrade before applying "
            "public-exposure hardening."
        )


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

GENERATED_HEADER_PREFIX = "# Rendered by splunk-enterprise-public-exposure-hardening — DO NOT EDIT"


def header(comment_char: str = "#") -> str:
    line = comment_char + GENERATED_HEADER_PREFIX[1:]
    return f"{line}\n"


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def make_script(body: str) -> str:
    return "#!/usr/bin/env bash\n" + header() + "set -euo pipefail\n\n" + body.lstrip()


def clean_render_dir(render_dir: Path) -> None:
    for rel in GENERATED_FILES:
        candidate = render_dir / rel
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink()


def helper_path() -> Path:
    project_root = Path(__file__).resolve().parents[3]
    return project_root / "skills/shared/lib/credential_helpers.sh"


def shared_scripts_path() -> Path:
    project_root = Path(__file__).resolve().parents[3]
    return project_root / "skills/shared/scripts"


# ---------------------------------------------------------------------------
# Splunk app — *.conf renderers
# ---------------------------------------------------------------------------

def tls_versions(args: argparse.Namespace) -> str:
    if args.tls_policy == "tls12_13" and args.enable_tls13 == "true":
        return "tls1.2, tls1.3"
    return "tls1.2"


def render_app_conf(args: argparse.Namespace) -> str:
    return (
        header()
        + "[install]\n"
        "is_configured = 1\n"
        "state = enabled\n\n"
        "[ui]\n"
        "is_visible = 0\n"
        "label = Splunk Public Exposure Hardening\n\n"
        "[launcher]\n"
        "author = splunk-enterprise-public-exposure-hardening\n"
        "description = Hardens an on-prem Splunk Enterprise deployment for public-internet exposure.\n"
        "version = 1.0.0\n\n"
        "[package]\n"
        "id = 000_public_exposure_hardening\n"
        "check_for_updates = 0\n"
    )


def render_web_conf(args: argparse.Namespace) -> str:
    accept_from_parts = ["127.0.0.1"]
    accept_from_parts.extend(csv_list(args.proxy_cidr))
    if args.bastion_cidr:
        accept_from_parts.extend(csv_list(args.bastion_cidr))
    accept_from_parts.append("!*")
    accept_from = ", ".join(accept_from_parts)

    lines = [
        header(),
        "[settings]",
        "# TLS termination policy:",
        "#   - When the public reverse proxy terminates TLS, set",
        "#     enableSplunkWebSSL = false and ensure the proxy↔Splunk",
        "#     channel is on the trusted network.",
        "#   - When Splunk Web terminates TLS itself, set true.",
        "enableSplunkWebSSL = true",
        f"privKeyPath = {args.server_key_path}",
        f"serverCert = {args.server_cert_path}",
        f"sslVersions = {tls_versions(args)}",
        f"cipherSuite = {CIPHER_SUITE}",
        f"ecdhCurves = {ECDH_CURVES}",
        "",
        "# Disable insecure / dangerous defaults",
        "enable_insecure_login = false",
        "enableSplunkWebClientNetloc = false",
        "request.show_tracebacks = false",
        "",
        "# Browser cookies / session",
        "tools.sessions.httponly = true",
        "tools.sessions.secure = true",
        "tools.sessions.forceSecure = true",
        "tools.sessions.timeout = 30",
        "cookieSameSite = strict",
        "x_frame_options_sameorigin = true",
        "",
        "# Reverse-proxy integration",
        "tools.proxy.on = true",
        f"tools.proxy.base = https://{args.public_fqdn}",
        "root_endpoint = /",
        "",
        "# Bind splunkd connection to loopback for single-host hardening.",
        "# For a SHC, leave mgmtHostPort = 0.0.0.0:8089 and rely on acceptFrom.",
        "mgmtHostPort = 127.0.0.1:8089"
        if args.topology == "single-search-head"
        else "# mgmtHostPort retained at default 0.0.0.0:8089 for SHC; firewall and acceptFrom enforce.",
        f"acceptFrom = {accept_from}",
        "",
        "# CORS — empty until explicitly required, then allowlist origins, never *",
        "crossOriginSharingPolicy = ",
        "crossOriginSharingHeaders = ",
        "",
        "# Splunkd connection timing — minimum is 30; lower values are clamped",
        "splunkdConnectionTimeout = 30",
        "",
        "# Tighten exception display",
        "show_exception_in_login = false",
    ]
    if args.auth_mode in ("saml", "reverse-proxy-sso"):
        lines.extend([
            "",
            "# SSO posture",
            "SSOMode = strict",
        ])
        if args.proxy_sso_trusted_ip:
            lines.append(f"trustedIP = {args.proxy_sso_trusted_ip}")
    return "\n".join(lines).rstrip() + "\n"


def render_server_conf(args: argparse.Namespace) -> str:
    accept_from_parts = ["127.0.0.1"]
    accept_from_parts.extend(csv_list(args.proxy_cidr))
    if args.indexer_cluster_cidr:
        accept_from_parts.extend(csv_list(args.indexer_cluster_cidr))
    if args.bastion_cidr:
        accept_from_parts.extend(csv_list(args.bastion_cidr))
    accept_from_parts.append("!*")
    accept_from = ", ".join(accept_from_parts)

    lines = [
        header(),
        "[sslConfig]",
        f"sslVersions = {tls_versions(args)}",
        f"sslVersionsForClient = {tls_versions(args)}",
        f"cipherSuite = {CIPHER_SUITE}",
        f"ecdhCurves = {ECDH_CURVES}",
        "allowSslCompression = false",
        "allowSslRenegotiation = false",
        "sslVerifyServerCert = true",
        f"caCertFile = {args.ca_bundle_path}",
        f"caTrustStorePath = {args.ca_bundle_path}",
        "# sslPassword and pass4SymmKey are NEVER embedded here. The apply",
        "# scripts inject them via splunk btool / splunk edit at apply time",
        "# from the operator-supplied secret files.",
        "# sslPassword = <set by apply-search-head.sh from --ssl-key-password-file>",
        "",
        "[httpServer]",
        "sendStrictTransportSecurityHeader = true",
        "includeSubDomains = true",
        "preload = false",
        "verboseLoginFailMsg = false",
        "forceHttp10 = never",
        "keepAliveIdleTimeout = 7200",
        f"acceptFrom = {accept_from}",
        "crossOriginSharingPolicy = ",
        "crossOriginSharingHeaders = ",
        "",
        "[kvstore]",
        "# 8191 must NEVER be reachable externally. The renderer cannot bind",
        "# the mongo port to loopback for SHC deployments because it is used",
        "# for replication. Host firewall and indexer-cluster CIDR enforce.",
        "disabled = false",
        "",
        "[general]",
        "# pass4SymmKey is rotated by apply-cluster-manager.sh / apply-deployer.sh",
        "# from --pass4symmkey-file. The default 'changeme' is unacceptable.",
        "# pass4SymmKey = <set at apply time>",
        "",
        "# SVD-2026-0302 defense in depth: even with edit_cmd removed from",
        "# non-admin roles, restrict the unarchive-command path to an explicit",
        "# allowlist so a future privilege-escalation cannot pivot to RCE.",
        "# Empty list (default below) means no unarchive command is allowed.",
        f"allowed_unarchive_commands = {args.allowed_unarchive_commands}",
    ]
    if args.topology in ("shc-with-hec", "shc-with-hec-and-hf"):
        lines.extend([
            "",
            "[clustering]",
            "# pass4SymmKey rotated at apply time",
            "",
            "[deployment]",
            "# Deployment-server pass4SymmKey is rotated by",
            "# rotate-pass4symmkey.sh from --pass4symmkey-file.",
            "# pass4SymmKey = <set at apply time>",
        ])
    if args.auth_mode == "reverse-proxy-sso" and args.proxy_sso_trusted_ip:
        lines.extend([
            "",
            "[general]",
            f"trustedIP = {args.proxy_sso_trusted_ip}",
        ])
    return "\n".join(lines).rstrip() + "\n"


def render_inputs_conf(args: argparse.Namespace) -> str:
    if args.enable_hec != "true" and args.enable_s2s != "true":
        return (
            header()
            + "# No HEC or S2S surface enabled by --enable-hec / --enable-s2s.\n"
            "# This stub keeps the file in the closed GENERATED_FILES set so\n"
            "# stale renders are detected.\n"
        )
    lines = [header()]
    if args.enable_hec == "true":
        require_client_cert = "true" if args.hec_mtls == "true" else "false"
        lines.extend([
            "[http]",
            "disabled = 0",
            "enableSSL = 1",
            "port = 8088",
            f"sslVersions = {tls_versions(args)}",
            f"cipherSuite = {CIPHER_SUITE}",
            f"ecdhCurves = {ECDH_CURVES}",
            f"requireClientCert = {require_client_cert}",
            "# When the proxy fronts HEC, this captures the real client IP",
            "# from X-Forwarded-For. HEC bypasses CherryPy tools.proxy.*.",
            "connection_host = proxied_ip",
            "dedicatedIoThreads = 2",
        ])
        if args.hec_mtls == "true" and args.hec_mtls_ca_bundle_file:
            lines.append(f"caCertFile = {args.hec_mtls_ca_bundle_file}")
        elif args.hec_mtls == "true":
            lines.append(f"caCertFile = {args.ca_bundle_path}")
        lines.append("")
    if args.enable_s2s == "true":
        accept_lines = ["127.0.0.1"]
        if args.indexer_cluster_cidr:
            accept_lines.extend(csv_list(args.indexer_cluster_cidr))
        accept_from = ", ".join(accept_lines)
        require_client_cert = "true" if args.s2s_mtls == "true" else "false"
        lines.extend([
            "[splunktcp-ssl://9997]",
            f"requireClientCert = {require_client_cert}",
            f"serverCert = {args.server_cert_path}",
            f"sslVersions = {tls_versions(args)}",
            f"cipherSuite = {CIPHER_SUITE}",
            f"ecdhCurves = {ECDH_CURVES}",
            f"caCertFile = {args.ca_bundle_path}",
            f"acceptFrom = {accept_from}",
            "",
            "[SSL]",
            "# Inputs SSL stanza for compatibility with older forwarders",
            f"serverCert = {args.server_cert_path}",
            f"sslVersions = {tls_versions(args)}",
            f"cipherSuite = {CIPHER_SUITE}",
            f"requireClientCert = {require_client_cert}",
        ])
    return "\n".join(lines).rstrip() + "\n"


def render_outputs_conf(args: argparse.Namespace) -> str:
    if args.topology not in ("shc-with-hec-and-hf",) or args.forwarder_mtls != "true":
        return (
            header()
            + "# No DMZ heavy forwarder mTLS outputs in this topology.\n"
            "# The skill renders mTLS outputs.conf only when --topology\n"
            "# shc-with-hec-and-hf and --forwarder-mtls true.\n"
        )
    indexer_cidr_first = csv_list(args.indexer_cluster_cidr)
    if not indexer_cidr_first:
        return header() + "# --indexer-cluster-cidr empty; outputs.conf not rendered.\n"
    indexer = indexer_cidr_first[0].split("/")[0]
    return (
        header()
        + "[tcpout]\n"
        "defaultGroup = primary_indexers\n"
        "useClientSSLCompression = false\n"
        "\n"
        "[tcpout:primary_indexers]\n"
        "# Replace <indexer-fqdn-N> with real indexer FQDNs after review.\n"
        f"server = {indexer}:9997\n"
        "\n"
        f"[tcpout-server://{indexer}:9997]\n"
        f"clientCert = {args.server_cert_path}\n"
        f"sslRootCAPath = {args.ca_bundle_path}\n"
        "sslVerifyServerCert = true\n"
        "sslCommonNameToCheck = <set per indexer>\n"
        "sslAltNameToCheck = <set per indexer>\n"
        f"sslVersions = {tls_versions(args)}\n"
        f"cipherSuite = {CIPHER_SUITE}\n"
        f"ecdhCurves = {ECDH_CURVES}\n"
    )


def render_authentication_conf(args: argparse.Namespace) -> str:
    lines = [
        header(),
        "[splunk_auth]",
        f"minPasswordLength = {args.min_password_length}",
        "minPasswordUppercase = 1",
        "minPasswordLowercase = 1",
        "minPasswordDigit = 1",
        "minPasswordSpecial = 1",
        f"expirePasswordDays = {args.expire_password_days}",
        "expireAlertDays = 15",
        "expireUserAccounts = true",
        "forceWeakPasswordChange = true",
        "lockoutUsers = true",
        f"lockoutAttempts = {args.lockout_attempts}",
        "lockoutThresholdMins = 5",
        f"lockoutMins = {args.lockout_mins}",
        "enablePasswordHistory = true",
        f"passwordHistoryCount = {args.password_history_count}",
        "",
        "[authentication]",
        f"authType = {'SAML' if args.auth_mode == 'saml' else 'Splunk'}",
    ]
    if args.auth_mode == "saml":
        lines.append("authSettings = saml")
        lines.extend([
            "",
            "[saml]",
            f"entityId = {args.saml_entity_id or 'https://' + args.public_fqdn + '/saml'}",
            f"idpMetaDataPath = {args.saml_idp_metadata_path}",
            "signAuthnRequest = true",
            "signedAssertion = true",
            f"signatureAlgorithm = {args.saml_signature_algorithm}",
            # XSW (XML Signature Wrapping) hardening: require the full SAML",
            # response to be signed, not just the assertion block.",
            "allowPartialSignatures = false",
            # Sign and verify SAML attribute queries (when used).",
            "attributeQueryRequestSigned = true",
            "attributeQueryResponseSigned = true",
            "excludedAutoMappedRoles = admin,sc_admin",
            f"redirectAfterLogoutToUrl = https://{args.public_fqdn}/account/logout",
            "# IdP signing certs are referenced by absolute path on the host.",
            "# The apply-search-head.sh script copies them from the operator file.",
        ])
        if args.saml_signing_cert_file:
            lines.append("# attributeQuerySigningCertPath = /opt/splunk/etc/auth/idp_signing.pem")
    return "\n".join(lines).rstrip() + "\n"


def render_authorize_conf(args: argparse.Namespace) -> str:
    allowed = csv_list(args.public_reader_allowed_indexes) or ["main"]
    lines = [
        header(),
        "# Override the default admin-role lockout exemption. Splunk ships with",
        "# never_lockout = enabled on role_admin which leaves the most-targeted",
        "# account immune to per-user lockout. Public exposure cannot accept this.",
        "[role_admin]",
        "never_lockout = disabled",
        "",
        "# Custom internet-facing reader role. Built from zero — does NOT inherit",
        "# from 'user' so high-risk capabilities are excluded by construction.",
        "[role_public_reader]",
        "importRoles = ",
        "search = enabled",
        "rest_apps_view = enabled",
        "list_settings = enabled",
        "list_search_head_clustering = enabled",
        "schedule_search = enabled",
    ]
    for cap in PUBLIC_READER_REMOVED_CAPABILITIES:
        lines.append(f"{cap} = disabled")
    lines.extend([
        f"srchTimeWin = {args.public_reader_srch_time_win}",
        f"srchDiskQuota = {args.public_reader_srch_disk_quota}",
        f"srchJobsQuota = {args.public_reader_srch_jobs_quota}",
        "rtSrchJobsQuota = 0",
        "cumulativeSrchJobsQuota = 50",
        "cumulativeRTSrchJobsQuota = 0",
        f"srchMaxTime = {args.public_reader_srch_max_time}",
        f"srchIndexesAllowed = {';'.join(allowed)}",
        "srchIndexesDisallowed = _audit;_internal;_introspection;_telemetry",
        "srchIndexesDefault = " + allowed[0],
    ])
    return "\n".join(lines).rstrip() + "\n"


def render_limits_conf(args: argparse.Namespace) -> str:
    return (
        header()
        + "[search]\n"
        "max_searches_per_cpu = 1\n"
        "auto_cancel = 600\n"
        "max_search_time = 14400\n"
        "max_subsearch_time = 300\n"
        "dispatch_dir_warning_size = 5000\n"
        "\n"
        "[searchresults]\n"
        "maxresultrows = 50000\n"
        "\n"
        "[restapi]\n"
        "# Per-IP rate limiting on /services/auth/login lives at the proxy.\n"
        "# These caps slow large bulk REST scrapes server-side.\n"
        "maxresultrows = 50000\n"
        "\n"
        "[http_input]\n"
        f"max_content_length = {args.hec_max_content_length}\n"
    )


def render_commands_conf(args: argparse.Namespace) -> str:
    lines = [header(), "# Mark high-risk SPL commands as risky so Splunk Web prompts the user.\n"]
    for cmd in RISKY_COMMANDS:
        lines.append(f"[{cmd}]")
        lines.append("is_risky = 1")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_props_conf(args: argparse.Namespace) -> str:
    return (
        header()
        + "# SVD-2026-0302 (CVE-2026-20162) RCE mitigation. The advisory's\n"
        "# documented remediation pairs removing the 'edit_cmd' capability\n"
        "# (done in authorize.conf) with the props.conf default below so that\n"
        "# even a privileged caller cannot pivot the unarchive path into a\n"
        "# shell pipeline.\n"
        "[default]\n"
        "unarchive_cmd_start_mode = direct\n"
    )


def render_splunk_launch_conf(args: argparse.Namespace) -> str:
    if args.enable_fips != "true":
        return (
            header()
            + "# splunk-launch.conf overlay. FIPS mode is OFF (default).\n"
            "# Re-render with --enable-fips true to enable FIPS 140-3 mode.\n"
            "# When FIPS is enabled this file emits SPLUNK_FIPS=1 and the\n"
            "# matching SPLUNK_FIPS_VERSION; both must be in $SPLUNK_HOME/etc/\n"
            "# splunk-launch.conf BEFORE the first start of Splunk on the host.\n"
        )
    return (
        header()
        + f"# FIPS {args.fips_version} mode enabled by --enable-fips.\n"
        "# This file MUST be placed at $SPLUNK_HOME/etc/splunk-launch.conf\n"
        "# (NOT inside an app's local/) and Splunk MUST be cold-started after\n"
        "# the change. The host kernel must also be in FIPS mode.\n"
        "# See https://docs.splunk.com/Documentation/Splunk/latest/Security/SecuringSplunkEnterprisewithFIPs\n"
        f"SPLUNK_FIPS=1\nSPLUNK_FIPS_VERSION={args.fips_version}\n"
    )


def render_default_meta(args: argparse.Namespace) -> str:
    return (
        header()
        + "[]\n"
        "access = read : [ ], write : [ admin ]\n"
        "export = none\n"
    )


def render_local_meta(args: argparse.Namespace) -> str:
    return (
        header()
        + "[]\n"
        "access = read : [ admin, role_public_reader ], write : [ admin ]\n"
        "export = none\n"
    )


# ---------------------------------------------------------------------------
# Apply scripts
# ---------------------------------------------------------------------------

def render_apply_search_head(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    pass4_path = shell_quote(args.pass4symmkey_file or "")
    ssl_pass_path = shell_quote(args.ssl_key_password_file or "")
    enable_fips = "true" if args.enable_fips == "true" else "false"
    return make_script(
        f"""splunk_home={splunk_home}
pass4_file={pass4_path}
ssl_pass_file={ssl_pass_path}
enable_fips={enable_fips}

if [[ ! -x "${{splunk_home}}/bin/splunk" ]]; then
  echo "ERROR: $splunk_home/bin/splunk not found." >&2
  exit 1
fi

src_app="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)/apps/000_public_exposure_hardening"
dst_app="${{splunk_home}}/etc/apps/000_public_exposure_hardening"

if [[ ! -d "$src_app" ]]; then
  echo "ERROR: rendered app not found at $src_app" >&2
  exit 1
fi

# Backup any existing app.
if [[ -d "$dst_app" ]]; then
  ts="$(date +%Y%m%d%H%M%S)"
  mv "$dst_app" "${{dst_app}}.bak.$ts"
fi

mkdir -p "$(dirname "$dst_app")"
cp -R "$src_app" "$dst_app"
chmod -R go-w "$dst_app"

# splunk-launch.conf MUST live at $SPLUNK_HOME/etc/splunk-launch.conf,
# NOT inside an app's default/. The app ships a copy as documentation;
# the apply step copies it to the correct location only when FIPS is
# explicitly enabled. FIPS must be configured BEFORE Splunk's first
# start on this host.
if [[ "$enable_fips" == "true" ]]; then
  if [[ -f "${{splunk_home}}/etc/splunk-launch.conf" ]]; then
    ts="$(date +%Y%m%d%H%M%S)"
    cp -p "${{splunk_home}}/etc/splunk-launch.conf" \\
       "${{splunk_home}}/etc/splunk-launch.conf.bak.$ts"
  fi
  cp "$dst_app/default/splunk-launch.conf" "${{splunk_home}}/etc/splunk-launch.conf"
  echo "FIPS overlay placed at ${{splunk_home}}/etc/splunk-launch.conf."
  echo "Verify the host kernel is in FIPS mode before restart, then cold-start Splunk."
fi

# Inject pass4SymmKey from local file (never argv).
if [[ -n "$pass4_file" && -s "$pass4_file" ]]; then
  pass4="$(cat "$pass4_file")"
  printf '[general]\\npass4SymmKey = %s\\n' "$pass4" \\
    > "$dst_app/local/server.conf.pass4symmkey.fragment"
  unset pass4
fi

# Inject sslPassword from local file (never argv).
if [[ -n "$ssl_pass_file" && -s "$ssl_pass_file" ]]; then
  ssl_pw="$(cat "$ssl_pass_file")"
  mkdir -p "$dst_app/local"
  printf '[sslConfig]\\nsslPassword = %s\\n' "$ssl_pw" \\
    > "$dst_app/local/server.conf.sslpw.fragment"
  unset ssl_pw
fi

# Merge any fragments into local/server.conf.
mkdir -p "$dst_app/local"
: > "$dst_app/local/server.conf"
for frag in "$dst_app/local/server.conf.pass4symmkey.fragment" \\
            "$dst_app/local/server.conf.sslpw.fragment"; do
  [[ -f "$frag" ]] || continue
  cat "$frag" >> "$dst_app/local/server.conf"
  rm -f "$frag"
done

"${{splunk_home}}/bin/splunk" restart
"""
    )


def render_apply_hec_tier(args: argparse.Namespace) -> str:
    return make_script(
        """src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Re-running search-head apply also propagates HEC inputs.conf."
echo "When HEC runs on a separate indexer tier, copy"
echo "  $src_dir/apps/000_public_exposure_hardening"
echo "into the indexer's etc/apps/ (or via the cluster bundle) and restart."
"""
    )


def render_apply_s2s_receiver(args: argparse.Namespace) -> str:
    return make_script(
        """echo "Apply the rendered S2S inputs.conf via the indexer cluster bundle."
echo "Run skills/splunk-indexer-cluster-setup/scripts/setup.sh --phase apply"
echo "after dropping the rendered app under shcluster/apps/ on the deployer."
"""
    )


def render_apply_heavy_forwarder(args: argparse.Namespace) -> str:
    return make_script(
        """splunk_home="${SPLUNK_HOME:-/opt/splunk}"
src_app="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/apps/000_public_exposure_hardening"

if [[ ! -d "$src_app" ]]; then
  echo "ERROR: rendered app missing at $src_app" >&2
  exit 1
fi

dst_app="${splunk_home}/etc/apps/000_public_exposure_hardening"
if [[ -d "$dst_app" ]]; then
  ts="$(date +%Y%m%d%H%M%S)"
  mv "$dst_app" "${dst_app}.bak.$ts"
fi
cp -R "$src_app" "$dst_app"
chmod -R go-w "$dst_app"
"${splunk_home}/bin/splunk" restart
"""
    )


def render_apply_deployer(args: argparse.Namespace) -> str:
    return make_script(
        """splunk_home="${SPLUNK_HOME:-/opt/splunk}"
src_app="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/apps/000_public_exposure_hardening"

if [[ ! -d "$src_app" ]]; then
  echo "ERROR: rendered app missing at $src_app" >&2
  exit 1
fi

# Drop the hardening app under shcluster/apps/. The captain pushes it.
dst_app="${splunk_home}/etc/shcluster/apps/000_public_exposure_hardening"
if [[ -d "$dst_app" ]]; then
  ts="$(date +%Y%m%d%H%M%S)"
  mv "$dst_app" "${dst_app}.bak.$ts"
fi
mkdir -p "$(dirname "$dst_app")"
cp -R "$src_app" "$dst_app"
chmod -R go-w "$dst_app"

echo "App staged at $dst_app."
echo "Run: ${splunk_home}/bin/splunk apply shcluster-bundle -target https://<captain>:8089"
echo "Then validate with skills/splunk-agent-management-setup/scripts/validate.sh"
"""
    )


def render_apply_cluster_manager(args: argparse.Namespace) -> str:
    pass4_path = shell_quote(args.pass4symmkey_file or "")
    return make_script(
        f"""pass4_file={pass4_path}
splunk_home="${{SPLUNK_HOME:-/opt/splunk}}"

if [[ -z "$pass4_file" || ! -s "$pass4_file" ]]; then
  echo "ERROR: --pass4symmkey-file required for cluster manager rotation." >&2
  exit 1
fi

# Rotate the cluster manager pass4SymmKey via splunk btool / edit.
# Reading from file keeps the secret off argv.
pass4="$(cat "$pass4_file")"
"${{splunk_home}}/bin/splunk" edit cluster-config -mode manager \\
  -auth-passphrase-file "$pass4_file" || true
unset pass4
"${{splunk_home}}/bin/splunk" restart
"""
    )


def render_apply_license_manager(args: argparse.Namespace) -> str:
    return make_script(
        """echo "License manager hardening is delegated to splunk-license-manager-setup."
echo "Use that skill's --phase apply to apply the rendered license manager"
echo "configuration alongside this hardening overlay."
"""
    )


def render_rotate_pass4symmkey(args: argparse.Namespace) -> str:
    return make_script(
        """splunk_home="${SPLUNK_HOME:-/opt/splunk}"
secret_file="${1:-}"

if [[ -z "$secret_file" || ! -s "$secret_file" ]]; then
  echo "Usage: $0 /path/to/new_pass4symmkey_file" >&2
  echo "" >&2
  echo "Rotates the pass4SymmKey across every stanza Splunk supports:" >&2
  echo "  [general], [clustering], [shclustering], [indexer_discovery]," >&2
  echo "  [license_master], [deployment]." >&2
  echo "All peers / SHs / forwarders / DCs / license peers / DS clients" >&2
  echo "that share this key must rotate to the same value before the next" >&2
  echo "bundle apply or phone-home." >&2
  exit 2
fi

# Cluster manager (indexer cluster).
"${splunk_home}/bin/splunk" edit cluster-config -mode manager \\
  -auth-passphrase-file "$secret_file" || true

# SHC deployer / SHC member.
"${splunk_home}/bin/splunk" edit shcluster-config \\
  -auth-passphrase-file "$secret_file" || true

# License manager / peer is configured via server.conf [license] pass4SymmKey;
# splunk-edit cannot rotate it on every release, so emit a btool fragment.
local_dir="${splunk_home}/etc/system/local"
mkdir -p "$local_dir"
new_key="$(cat "$secret_file")"
{
  printf '[general]\\npass4SymmKey = %s\\n' "$new_key"
  printf '[clustering]\\npass4SymmKey = %s\\n' "$new_key"
  printf '[shclustering]\\npass4SymmKey = %s\\n' "$new_key"
  printf '[indexer_discovery]\\npass4SymmKey = %s\\n' "$new_key"
  printf '[license_master]\\npass4SymmKey = %s\\n' "$new_key"
  printf '[deployment]\\npass4SymmKey = %s\\n' "$new_key"
} > "$local_dir/server.conf.pass4symmkey.fragment"
unset new_key
echo "Wrote rotation fragment to $local_dir/server.conf.pass4symmkey.fragment"
echo "Merge into etc/system/local/server.conf, then 'splunk restart'."
"""
    )


def render_rotate_splunk_secret(args: argparse.Namespace) -> str:
    return make_script(
        """splunk_home="${SPLUNK_HOME:-/opt/splunk}"
new_secret="${1:-}"

if [[ -z "$new_secret" || ! -s "$new_secret" ]]; then
  echo "Usage: $0 /path/to/new_splunk_secret_file" >&2
  echo "" >&2
  echo "This is a destructive rotation. Read references/splunk-secret-rotation.md" >&2
  echo "BEFORE running. Backup $splunk_home/etc/auth/splunk.secret first." >&2
  exit 2
fi

ts="$(date +%Y%m%d%H%M%S)"
backup="${splunk_home}/etc/auth/splunk.secret.bak.$ts"
cp -p "${splunk_home}/etc/auth/splunk.secret" "$backup"
chmod 0400 "$backup"

# 1. Decrypt all encrypted credentials with the OLD secret. Operator-driven.
echo "STEP 1: decrypt encrypted credentials with old secret. See references/splunk-secret-rotation.md"
echo "STEP 2: install new secret, restart, re-encrypt."

install -m 0400 -o splunk -g splunk "$new_secret" "${splunk_home}/etc/auth/splunk.secret"
"${splunk_home}/bin/splunk" restart
"""
    )


def render_verify_certs(args: argparse.Namespace) -> str:
    cert = shell_quote(args.server_cert_path)
    fqdn = shell_quote(args.public_fqdn)
    sans = shell_quote(args.required_sans or args.public_fqdn)
    return make_script(
        f"""cert={cert}
fqdn={fqdn}
required_sans={sans}

if [[ ! -s "$cert" ]]; then
  echo "ERROR: certificate file not found or empty: $cert" >&2
  exit 1
fi

# Refuse default Splunk-shipped subject CNs.
subject="$(openssl x509 -in "$cert" -noout -subject 2>/dev/null || true)"
case "$subject" in
  *SplunkServerDefaultCert*|*SplunkCommonCA*|*SplunkWebDefaultCert*)
    echo "ERROR: still using a default Splunk-shipped certificate ($subject). Replace before public exposure." >&2
    exit 2
    ;;
esac

# Expiry & key strength.
not_after="$(openssl x509 -in "$cert" -noout -enddate | sed 's/^notAfter=//')"
echo "notAfter: $not_after"
openssl x509 -in "$cert" -noout -checkend 0 \\
  || {{ echo "ERROR: certificate is expired" >&2; exit 3; }}

key_alg="$(openssl x509 -in "$cert" -noout -text | awk '/Public Key Algorithm/ {{print $4; exit}}')"
key_bits="$(openssl x509 -in "$cert" -noout -text | awk '/Public-Key:/ {{gsub("[(:bit)]","",$2); print $2; exit}}')"
echo "key: $key_alg ${{key_bits}}-bit"

case "$key_alg" in
  rsaEncryption)
    if [[ "${{key_bits:-0}}" -lt 2048 ]]; then
      echo "ERROR: RSA key < 2048 bits" >&2
      exit 4
    fi
    ;;
esac

sig_alg="$(openssl x509 -in "$cert" -noout -text | awk '/Signature Algorithm/ {{print $3; exit}}')"
echo "sig: $sig_alg"
case "$sig_alg" in
  *sha1With*|*md5With*)
    echo "ERROR: unsupported signature algorithm $sig_alg" >&2
    exit 5
    ;;
esac

# Hostname / SAN verification.
sans_in_cert="$(openssl x509 -in "$cert" -noout -ext subjectAltName 2>/dev/null || true)"
echo "$sans_in_cert"
IFS=',' read -ra wanted <<<"$required_sans"
for want in "${{wanted[@]}}"; do
  want_trim="${{want// /}}"
  [[ -z "$want_trim" ]] && continue
  if ! grep -q "DNS:$want_trim" <<<"$sans_in_cert"; then
    echo "ERROR: required SAN $want_trim missing from certificate." >&2
    exit 6
  fi
done

# Chain verification (best-effort against system trust store).
openssl verify -untrusted "$cert" "$cert" >/dev/null 2>&1 || \\
  echo "WARN: openssl verify against system store failed; provide --CAfile bundle if necessary."

echo "OK: certificate sanity passed for $fqdn."
"""
    )


def render_generate_csr_template(args: argparse.Namespace) -> str:
    sans = csv_list(args.required_sans or args.public_fqdn)
    san_lines = "\n".join(f"DNS.{i+1} = {san}" for i, san in enumerate(sans))
    fqdn = shell_quote(args.public_fqdn)
    return make_script(
        f"""fqdn={fqdn}
out_dir="${{1:-./csr}}"

mkdir -p "$out_dir"

cat > "$out_dir/openssl.cnf" <<'EOF'
[req]
default_bits       = 2048
default_md         = sha256
prompt             = no
distinguished_name = dn
req_extensions     = req_ext

[dn]
CN = REPLACE_WITH_FQDN
O  = REPLACE_WITH_ORG
OU = Splunk Enterprise

[req_ext]
subjectAltName = @alt_names
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth

[alt_names]
{san_lines}
EOF

sed -i.bak "s/REPLACE_WITH_FQDN/$fqdn/g" "$out_dir/openssl.cnf"
rm -f "$out_dir/openssl.cnf.bak"

echo "CSR template at $out_dir/openssl.cnf."
echo "Generate the key + CSR with:"
echo "  openssl req -newkey rsa:2048 -nodes \\\\"
echo "    -keyout $out_dir/server.key -out $out_dir/server.csr \\\\"
echo "    -config $out_dir/openssl.cnf"
"""
    )


def render_certificates_readme(args: argparse.Namespace) -> str:
    return (
        f"# Certificate Helpers\n\n"
        f"`verify-certs.sh` checks the existing leaf certificate at\n"
        f"`{args.server_cert_path}` for default-Splunk subjects, expiry, key\n"
        f"strength (≥ 2048-bit RSA / P-256 ECDSA), signature algorithm\n"
        "(SHA-256+), and required SANs.\n\n"
        "`generate-csr-template.sh` emits an `openssl.cnf` ready for\n"
        "`openssl req -newkey rsa:2048 ... -config ./csr/openssl.cnf`.\n\n"
        "Production note: certificate procurement is operator-driven. The skill\n"
        "does NOT call out to a CA. See `handoff/certificate-procurement.md`.\n"
    )


# ---------------------------------------------------------------------------
# Reverse proxy templates
# ---------------------------------------------------------------------------

def render_nginx_web(args: argparse.Namespace) -> str:
    fqdn = args.public_fqdn
    rate = args.login_rate_per_minute
    streaming = args.streaming_search_timeout
    bastion_allow = ""
    if args.bastion_cidr:
        bastion_allow = "\n".join(
            f"        allow {cidr};" for cidr in csv_list(args.bastion_cidr)
        ) + "\n        deny all;\n"
    else:
        bastion_allow = "        # No --bastion-cidr provided; admin-path lockdown left to operator.\n"
    return f"""# Rendered by splunk-enterprise-public-exposure-hardening — DO NOT EDIT
# Splunk Web reverse proxy vhost (nginx). TLS terminates here, browser
# security headers originate here, and all known SVD-class mitigations
# (header sanitisation, return_to allowlist, per-IP rate limit) live here.

map $http_upgrade $connection_upgrade {{
    default upgrade;
    ''      close;
}}

# Per-IP rate limit on auth endpoints (Splunk has no CAPTCHA).
limit_req_zone $binary_remote_addr zone=splunk_login:10m rate={rate}r/m;

server {{
    listen 80;
    server_name {fqdn};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl http2;
    server_name {fqdn};

    # TLS — replace the cert paths to match your operator-provided files.
    ssl_certificate     /etc/ssl/private/splunk/{fqdn}.fullchain.pem;
    ssl_certificate_key /etc/ssl/private/splunk/{fqdn}.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers off;
    ssl_ecdh_curve      prime256v1:secp384r1:secp521r1;
    ssl_session_cache   shared:SSL:50m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;
    ssl_stapling        on;
    ssl_stapling_verify on;

    # Browser security headers — Splunk Web has no customHttpHeaders setting,
    # so HSTS/CSP/etc. originate here only.
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options    "nosniff" always;
    add_header Content-Security-Policy   "frame-ancestors 'self'" always;
    add_header Referrer-Policy           "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy        "geolocation=(), microphone=(), camera=()" always;

    # Drop attacker-supplied proxy headers BEFORE writing our own.
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host  $host;
    proxy_set_header Host              $host;
    proxy_set_header Upgrade           $http_upgrade;
    proxy_set_header Connection        $connection_upgrade;

    # Strip backend Server / X-Powered-By to avoid leaking version info.
    proxy_hide_header  Server;
    proxy_hide_header  X-Powered-By;
    proxy_hide_header  X-Splunk-Version;

    proxy_http_version       1.1;
    proxy_buffering          off;
    proxy_request_buffering  off;
    proxy_read_timeout       {streaming}s;
    proxy_send_timeout       {streaming}s;
    proxy_connect_timeout    30s;
    client_max_body_size     64m;

    # SVD-2025-1203 / CVE-2025-20384 mitigation: strip ANSI escape codes
    # and CR/LF in forwarded headers (log injection at /en-US/static/).
    # ESC = \\x1b, BEL = \\x07.
    if ($http_user_agent ~ "[\\r\\n\\x1b\\x07]") {{
        return 400;
    }}
    if ($request_uri ~ "[\\x1b\\x07]") {{
        return 400;
    }}

    # CVE-2025-20379: only allow same-origin local-path return_to values.
    if ($arg_return_to ~* "^https?://") {{
        return 400;
    }}

    # Sensitive REST/UI paths that the public must never reach. Even though
    # capability hardening covers these inside Splunk, denying at the edge
    # leaves no surface to exploit.
    location ~ ^/services/apps/(local|appinstall|remote) {{
        return 404;
    }}
    location ~ ^/services/configs/conf-passwords {{
        return 404;
    }}
    location ~ ^/services/data/inputs/oneshot {{
        return 404;
    }}
    location ~ ^/(en-US/)?account/insecurelogin {{
        return 404;
    }}
    location ~ ^/(en-US/)?debug/ {{
        return 404;
    }}

    # Per-IP rate limit on the login endpoint.
    location = /en-US/account/login {{
        limit_req zone=splunk_login burst=10 nodelay;
        add_header Cache-Control "no-store" always;
        proxy_pass http://splunk_web_upstream;
    }}

    # Lock down admin paths to a bastion CIDR (operator-supplied).
    location ~ ^/(en-US/manager|en-US/account/(?!login)|services/?($|admin|configs)|servicesNS) {{
{bastion_allow}        proxy_pass http://splunk_web_upstream;
    }}

    location / {{
        proxy_pass http://splunk_web_upstream;
    }}
}}

upstream splunk_web_upstream {{
    server 127.0.0.1:8000;
    keepalive 32;
}}
"""


def render_nginx_hec(args: argparse.Namespace) -> str:
    fqdn = args.hec_fqdn or args.public_fqdn
    body_size_mb = max(args.hec_max_content_length // (1024 * 1024), 64)
    mtls_block = ""
    if args.hec_mtls == "true":
        mtls_block = """    # HEC mTLS — replace with the CA bundle that signs your client certs.
    ssl_client_certificate /etc/ssl/private/splunk/hec_client_ca.pem;
    ssl_verify_client      on;
    ssl_verify_depth       3;
"""
    return f"""# Rendered by splunk-enterprise-public-exposure-hardening — DO NOT EDIT
# HEC reverse proxy vhost (nginx). Tuned for 800MB Splunk default and
# disables WAF body inspection by sizing client_max_body_size match.

server {{
    listen 80;
    server_name {fqdn};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl http2;
    server_name {fqdn};

    ssl_certificate     /etc/ssl/private/splunk/{fqdn}.fullchain.pem;
    ssl_certificate_key /etc/ssl/private/splunk/{fqdn}.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers off;
{mtls_block}
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options    "nosniff" always;
    add_header Cache-Control             "no-store" always;

    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Host              $host;

    proxy_http_version       1.1;
    proxy_buffering          off;
    proxy_request_buffering  off;
    proxy_read_timeout       60s;
    proxy_send_timeout       60s;
    client_max_body_size     {body_size_mb}m;

    # /services/collector/health is unauthenticated by design; allow upstream
    # health checks but rate-limit aggressively to deter scrapers.
    location = /services/collector/health {{
        proxy_pass https://splunk_hec_upstream;
    }}

    location /services/collector {{
        proxy_pass https://splunk_hec_upstream;
    }}

    location / {{
        return 404;
    }}
}}

upstream splunk_hec_upstream {{
    server 127.0.0.1:8088;
    keepalive 32;
}}
"""


def render_nginx_readme(args: argparse.Namespace) -> str:
    return (
        "# nginx vhosts\n\n"
        "Files:\n"
        "- `splunk-web.conf` — Splunk Web reverse proxy vhost.\n"
        "- `splunk-hec.conf` — HEC reverse proxy vhost.\n\n"
        "Both vhosts assume nginx 1.24+. Drop them under\n"
        "`/etc/nginx/conf.d/` and reload nginx after replacing the\n"
        "`/etc/ssl/private/splunk/...` certificate paths with operator-supplied\n"
        "files.\n\n"
        "Critical knobs that are NON-obvious:\n\n"
        "- `proxy_buffering off` and `proxy_request_buffering off` keep\n"
        "  streaming search results flowing without delaying the response\n"
        "  until the search completes.\n"
        "- `proxy_read_timeout` and `proxy_send_timeout` are higher than the\n"
        "  AWS ALB 60 s and Cloudflare-Free 100 s defaults that otherwise\n"
        "  cause 524s on long searches.\n"
        "- The `Upgrade` / `Connection` map is included even though core\n"
        "  Splunk Web does not use WebSockets — Splunk Secure Gateway and\n"
        "  Mission Control do.\n"
        "- The `splunkweb_csrf_token_*` cookie MUST flow through to the\n"
        "  browser; do NOT add Cloudflare Page Rules or WAF rules that strip\n"
        "  it or auth POSTs return `CSRF validation failed`.\n"
        "- `client_max_body_size` on the HEC vhost matches Splunk's\n"
        "  `[http_input] max_content_length` (800 MB default) so HEC POSTs\n"
        "  are not 413-ed at the edge.\n"
    )


def render_haproxy_web(args: argparse.Namespace) -> str:
    fqdn = args.public_fqdn
    streaming = args.streaming_search_timeout
    return f"""# Rendered by splunk-enterprise-public-exposure-hardening — DO NOT EDIT
global
    log /dev/log local0
    daemon
    tune.ssl.default-dh-param 2048

defaults
    mode http
    timeout connect 30s
    timeout client  {streaming}s
    timeout server  {streaming}s
    option httplog
    option http-server-close
    # NEVER 'option httpclose' — breaks HEC keepalive.

frontend splunk_web_https
    bind :443 ssl crt /etc/haproxy/ssl/{fqdn}.pem alpn h2,http/1.1
    http-request set-header X-Forwarded-Proto https
    http-request set-header X-Forwarded-Host  %[req.hdr(host)]
    http-request set-header X-Forwarded-For   %[src]
    http-request del-header X-Splunk-Form-Key

    # SVD-2025-1203 / CVE-2025-20384 — log injection: drop ANSI / CR / LF
    # in any forwarded header or URI (the canonical sink is /en-US/static/).
    http-request deny if {{ req.hdrs -m reg [\\x07\\x1b\\r\\n] }}
    http-request deny if {{ url -m reg [\\x07\\x1b] }}

    # CVE-2025-20379 — return_to open redirect: deny absolute URLs.
    http-request deny if {{ url_param(return_to) -m reg ^https?:// }}

    # Sensitive REST/UI paths the public must never reach.
    http-request deny if {{ path_beg /services/apps/local }}
    http-request deny if {{ path_beg /services/apps/appinstall }}
    http-request deny if {{ path_beg /services/apps/remote }}
    http-request deny if {{ path_beg /services/configs/conf-passwords }}
    http-request deny if {{ path_beg /services/data/inputs/oneshot }}
    http-request deny if {{ path_beg /account/insecurelogin }} || {{ path_beg /en-US/account/insecurelogin }}
    http-request deny if {{ path_beg /debug/ }} || {{ path_beg /en-US/debug/ }}

    # Browser security headers
    http-response set-header Strict-Transport-Security "max-age=31536000; includeSubDomains"
    http-response set-header X-Content-Type-Options nosniff
    http-response set-header Content-Security-Policy "frame-ancestors 'self'"
    http-response set-header Referrer-Policy "strict-origin-when-cross-origin"
    http-response set-header Permissions-Policy "geolocation=(), microphone=(), camera=()"

    default_backend splunk_web_pool

backend splunk_web_pool
    option httpchk GET /en-US/account/login
    server sh01 127.0.0.1:8000 check
"""


def render_haproxy_hec(args: argparse.Namespace) -> str:
    fqdn = args.hec_fqdn or args.public_fqdn
    body_bytes = args.hec_max_content_length
    return f"""# Rendered by splunk-enterprise-public-exposure-hardening — DO NOT EDIT
global
    log /dev/log local0

defaults
    mode http
    timeout connect 10s
    timeout client  60s
    timeout server  60s
    option http-server-close
    option httplog
    log global

frontend splunk_hec_https
    bind :443 ssl crt /etc/haproxy/ssl/{fqdn}.pem
    maxconn 5000
    # Match Splunk's HEC max_content_length default to avoid edge 413s.
    http-request set-var(txn.max_body_bytes) int({body_bytes})
    http-response set-header Strict-Transport-Security "max-age=31536000; includeSubDomains"

    acl is_hec path_beg /services/collector
    use_backend splunk_hec_pool if is_hec
    default_backend hec_404

backend splunk_hec_pool
    option httpchk GET /services/collector/health
    server hec01 127.0.0.1:8088 check ssl verify none

backend hec_404
    http-request deny deny_status 404
"""


def render_haproxy_readme(args: argparse.Namespace) -> str:
    return (
        "# HAProxy configurations\n\n"
        "Both `splunk-web.cfg` and `splunk-hec.cfg` use\n"
        "`option http-server-close`. NEVER replace this with\n"
        "`option httpclose` — it breaks HEC keepalive and causes\n"
        "intermittent ingest failures.\n\n"
        "If you co-locate Web and HEC behind a single HAProxy frontend, merge\n"
        "the two `frontend` blocks and route by SNI / `path_beg`.\n"
    )


def render_iptables(args: argparse.Namespace) -> str:
    proxy_cidrs = csv_list(args.proxy_cidr)
    indexer_cidrs = csv_list(args.indexer_cluster_cidr) if args.indexer_cluster_cidr else []
    bastion_cidrs = csv_list(args.bastion_cidr) if args.bastion_cidr else []
    drop_ports = (8089, 8191, 9887, 8065)
    rules = [
        "# Rendered by splunk-enterprise-public-exposure-hardening — DO NOT EDIT",
        "*filter",
        ":INPUT DROP [0:0]",
        ":FORWARD DROP [0:0]",
        ":OUTPUT ACCEPT [0:0]",
        "-A INPUT -i lo -j ACCEPT",
        "-A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT",
        "-A INPUT -p tcp --dport 80 -j ACCEPT",
        "-A INPUT -p tcp --dport 443 -j ACCEPT",
    ]
    for cidr in proxy_cidrs:
        rules.append(f"-A INPUT -s {cidr} -p tcp --dport 8000 -j ACCEPT")
        rules.append(f"-A INPUT -s {cidr} -p tcp --dport 8088 -j ACCEPT")
    for cidr in indexer_cidrs:
        rules.append(f"-A INPUT -s {cidr} -p tcp --dport 8089 -j ACCEPT")
        rules.append(f"-A INPUT -s {cidr} -p tcp --dport 8191 -j ACCEPT")
        rules.append(f"-A INPUT -s {cidr} -p tcp --dport 9887 -j ACCEPT")
        rules.append(f"-A INPUT -s {cidr} -p tcp --dport 9997 -j ACCEPT")
    for cidr in bastion_cidrs:
        rules.append(f"-A INPUT -s {cidr} -p tcp --dport 8089 -j ACCEPT")
    for port in drop_ports:
        rules.append(f"-A INPUT -p tcp --dport {port} -j DROP")
    rules.append("COMMIT")
    return "\n".join(rules) + "\n"


def render_nftables(args: argparse.Namespace) -> str:
    proxy_cidrs = csv_list(args.proxy_cidr)
    indexer_cidrs = csv_list(args.indexer_cluster_cidr) if args.indexer_cluster_cidr else []
    bastion_cidrs = csv_list(args.bastion_cidr) if args.bastion_cidr else []
    proxy_set = ", ".join(proxy_cidrs) or "127.0.0.1"
    private_lines: list[str] = []
    for cidr in indexer_cidrs:
        private_lines.append(f"        ip saddr {cidr} tcp dport {{ 8089, 8191, 9887, 9997 }} accept")
    for cidr in bastion_cidrs:
        private_lines.append(f"        ip saddr {cidr} tcp dport 8089 accept")
    private_block = "\n".join(private_lines) if private_lines else "        # No internal CIDRs configured."
    return f"""# Rendered by splunk-enterprise-public-exposure-hardening — DO NOT EDIT
table inet splunk_public_exposure {{
    chain input {{
        type filter hook input priority 0; policy drop;
        ct state established,related accept
        iif lo accept
        tcp dport {{ 80, 443 }} accept
        ip saddr {{ {proxy_set} }} tcp dport {{ 8000, 8088 }} accept
{private_block}
        tcp dport {{ 8089, 8191, 9887, 8065 }} drop
    }}
}}
"""


def render_firewalld(args: argparse.Namespace) -> str:
    return """<?xml version="1.0" encoding="utf-8"?>
<!-- Rendered by splunk-enterprise-public-exposure-hardening — DO NOT EDIT -->
<zone>
  <short>splunk-public-exposure</short>
  <description>Hardened zone for an internet-facing Splunk Enterprise host.</description>
  <service name="ssh"/>
  <port port="80" protocol="tcp"/>
  <port port="443" protocol="tcp"/>
  <rule family="ipv4">
    <port port="8089" protocol="tcp"/>
    <reject/>
  </rule>
  <rule family="ipv4">
    <port port="8191" protocol="tcp"/>
    <reject/>
  </rule>
  <rule family="ipv4">
    <port port="9887" protocol="tcp"/>
    <reject/>
  </rule>
  <rule family="ipv4">
    <port port="8065" protocol="tcp"/>
    <reject/>
  </rule>
</zone>
"""


def render_aws_sg(args: argparse.Namespace) -> dict:
    proxy_cidrs = csv_list(args.proxy_cidr)
    indexer_cidrs = csv_list(args.indexer_cluster_cidr) if args.indexer_cluster_cidr else []
    bastion_cidrs = csv_list(args.bastion_cidr) if args.bastion_cidr else []
    rules: list[dict] = [
        {
            "Description": "HTTPS from the world (proxy listener)",
            "FromPort": 443,
            "ToPort": 443,
            "IpProtocol": "tcp",
            "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
        },
        {
            "Description": "HTTP redirect from the world",
            "FromPort": 80,
            "ToPort": 80,
            "IpProtocol": "tcp",
            "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
        },
    ]
    for cidr in proxy_cidrs:
        rules.append({
            "Description": "Splunk Web 8000 from proxy CIDR",
            "FromPort": 8000,
            "ToPort": 8000,
            "IpProtocol": "tcp",
            "IpRanges": [{"CidrIp": cidr}],
        })
        rules.append({
            "Description": "HEC 8088 from proxy CIDR",
            "FromPort": 8088,
            "ToPort": 8088,
            "IpProtocol": "tcp",
            "IpRanges": [{"CidrIp": cidr}],
        })
    for cidr in indexer_cidrs:
        rules.append({
            "Description": "splunkd / KV / replication / S2S from indexer CIDR",
            "FromPort": 8089,
            "ToPort": 9997,
            "IpProtocol": "tcp",
            "IpRanges": [{"CidrIp": cidr}],
        })
    for cidr in bastion_cidrs:
        rules.append({
            "Description": "splunkd 8089 from bastion CIDR",
            "FromPort": 8089,
            "ToPort": 8089,
            "IpProtocol": "tcp",
            "IpRanges": [{"CidrIp": cidr}],
        })
    return {
        "GroupName": "splunk-public-exposure",
        "Description": "Rendered by splunk-enterprise-public-exposure-hardening",
        "IpPermissions": rules,
    }


def render_firewall_readme(args: argparse.Namespace) -> str:
    return (
        "# Firewall snippets\n\n"
        "Files:\n"
        "- `iptables.rules` — `iptables-restore` syntax.\n"
        "- `nftables.conf`  — `nft -f` syntax.\n"
        "- `firewalld.xml`  — drop-in zone for `firewall-cmd`.\n"
        "- `aws-sg.json`    — AWS Security Group ingress rules\n"
        "  (apply via `aws ec2 authorize-security-group-ingress --cli-input-json`).\n\n"
        "All snippets explicitly drop public traffic to ports `8089`,\n"
        "`8191`, `8065`, and `9887`. The validate phase performs an external\n"
        "probe (`--external-probe-cmd`) to confirm those drops are real.\n"
    )


# ---------------------------------------------------------------------------
# Operator handoff Markdown — concise, action-oriented, link out for depth.
# ---------------------------------------------------------------------------

def render_operator_checklist(args: argparse.Namespace) -> str:
    return f"""# Operator Handoff Checklist

This is the single file the operator runs through before turning the
internet-facing FQDN `{args.public_fqdn}` live. Items are grouped by
when in the timeline they must happen.

## T-30 days

- [ ] Procure CA-signed certificate from a public CA (Let's Encrypt,
      DigiCert, Sectigo, etc.). RSA ≥ 2048-bit or ECDSA P-256+, SHA-256+
      signature. CN/SAN must match `{args.public_fqdn}` plus any extra
      SANs needed.
- [ ] Establish CAA records: only your CA may issue.
- [ ] Stand up the IdP-side SAML config and require MFA. See
      `handoff/saml-idp-handoff.md` and `handoff/duo-mfa-handoff.md`.
- [ ] Set up the WAF / CDN of choice. See `handoff/waf-cloudflare.md`,
      `handoff/waf-aws.md`, `handoff/waf-f5-imperva.md`.

## T-7 days

- [ ] Subscribe to https://advisory.splunk.com/ and the CISA KEV feed.
- [ ] Confirm Splunk version is ≥ the SVD floor in
      `references/cve-svd-floor.json`. Upgrade first if not.
- [ ] Rotate `splunk.secret` if it has ever been pulled out of the host
      via backups or container images. See
      `handoff/incident-response-splunk-secret.md`.
- [ ] Rotate every `pass4SymmKey` (cluster, SHC, license, indexer
      discovery) and confirm none equals `changeme` or any default.
- [ ] Configure encrypted backups for `$SPLUNK_HOME/etc` and indexes,
      and TEST the restore. See `handoff/backup-and-restore.md`.

## T-1 day (cutover)

- [ ] Run `bash preflight.sh` — must exit zero.
- [ ] Confirm SOC alerting is live on `_audit` and `_internal`. See
      `handoff/soc-alerting-runbook.md`.
- [ ] DNS records cut over (forward + reverse + CAA + DNSSEC).
- [ ] Enable HSTS preload submission (post-cutover).
- [ ] Document break-glass admin procedure in your incident-response
      runbook.

## T+0 (live)

- [ ] Run `bash validate.sh` — must exit zero.
- [ ] External port probe: `8089`, `8191`, `8065`, `9887` all
      unreachable from the internet.
- [ ] Confirm Splunk Web login is rate-limited per IP at the proxy.
- [ ] Confirm WAF blocks a known-bad request pattern.
- [ ] Confirm SOC sees the first login event in `_audit`.

## Ongoing

- [ ] Patch within 30 days of every Splunk advisory; re-run preflight
      after each upgrade.
- [ ] Rotate TLS certs ≤ 30 days before expiry.
- [ ] Re-run validate at least monthly and on every config change.
- [ ] Decide on Splunk Secure Gateway / Mobile / SC4S / MCP server
      exposure separately — those each need their own threat model.
"""


def render_waf_cloudflare(args: argparse.Namespace) -> str:
    return f"""# Cloudflare WAF / CDN Handoff

Splunk Enterprise has no native CAPTCHA and lockout is per-user. The
Cloudflare layer in front of `{args.public_fqdn}` is what stops
credential stuffing and DDoS.

## Required configuration

1. **Managed Rules**: enable Cloudflare WAF Managed Ruleset and OWASP
   Core Ruleset 4.x. Score threshold ≤ 25.
2. **Rate Limiting** on `https://{args.public_fqdn}/en-US/account/login`:
   {args.login_rate_per_minute} requests / minute / IP, action: block
   for 15 minutes.
3. **Bot Fight Mode**: enable, but allowlist your HEC user-agents
   (Splunk SDKs, OTel exporters, Universal Forwarder UAs) so HEC ingest
   is not blocked.
4. **Geo Fence** (operator-defined): allowlist countries where users
   live; deny others.
5. **IP Reputation**: enable Cloudflare's threat-score block at score
   ≥ 30.
6. **Body Size**: raise the Free / Pro 128 KB body inspection cap on
   `/services/collector*` to at least 100 MB. Free plan cannot — use
   Pro+ for HEC.
7. **Read Timeout**: only Enterprise plan can extend the default 100 s
   Proxy Read Timeout. Set to ≥ {args.streaming_search_timeout} s for
   long searches.
8. **Cookie Rules**: do NOT scrub `splunkweb_csrf_token_*`.
9. **Page Rules**: cache bypass on `/en-US/`, `/services/`,
   `/servicesNS/`, `/static/app/...`.
10. **TLS**: enable "Full (Strict)" SSL mode so Cloudflare verifies the
    origin cert.

## Things that will silently break

- Cloudflare's default Page Rule "Browser Integrity Check" can challenge
  legit forwarder traffic — disable on HEC paths.
- `Cache Everything` Page Rule on `/static/` is fine; on `/en-US/` will
  cache CSRF tokens — do NOT enable.
- Free / Pro 100 s Proxy Read Timeout will 524 long searches.
"""


def render_waf_aws(args: argparse.Namespace) -> str:
    return f"""# AWS WAF + CloudFront / ALB Handoff

## CloudFront in front of ALB

1. CloudFront distribution → ALB origin. TLS 1.2+ only on the viewer
   protocol.
2. ALB idle timeout: raise from 60 s default to ≥
   {args.streaming_search_timeout} s. Splunk searches stream chunked.
3. ALB target group health check: `GET /en-US/account/login`, expect
   200.
4. WAF web ACL associated with CloudFront:
   - `AWSManagedRulesCommonRuleSet`
   - `AWSManagedRulesKnownBadInputsRuleSet`
   - `AWSManagedRulesAmazonIpReputationList`
   - `AWSManagedRulesATPRuleSet` (account takeover protection)
   - **Custom rate-based rule**: 5 / minute / IP on
     `URI = /en-US/account/login`, scope-down to `METHOD = POST`.

## HEC body inspection allowance

Default WAF body inspection caps are 8 KB. HEC batches routinely exceed
this. Add a custom WAF rule that DOES NOT inspect the body for
URI matching `/services/collector*` and increase the size to 64 KB on
the rest. Without this, AWS WAF returns 403 to HEC clients.

## Logging

- Enable WAF logging to a separate S3 bucket.
- Route ALB access logs to a different S3 bucket than CloudTrail.
- Forward both to the SOC SIEM (Splunk Enterprise's `_internal` is not
  the right place to store these — they describe the protective layer).
"""


def render_waf_f5_imperva(args: argparse.Namespace) -> str:
    return f"""# F5 BIG-IP / Imperva WAF Handoff

## F5 BIG-IP ASM

- Enable ASM with the "Splunk Enterprise" template if available, or the
  "OWASP Top 10" template otherwise.
- Set HTTP profile `request-timeout` to {args.streaming_search_timeout}
  seconds for long searches.
- Add a session policy that requires SAML SSO with MFA (Access Policy
  Manager / APM).
- Enable IP intelligence and bot signature detection.
- Add a custom XFF policy: F5 inserts its own XFF and trusts only its
  own SNAT range.

## Imperva Cloud

- Custom rule: rate-limit 5 / minute / IP on `/en-US/account/login`.
- Custom rule: deny if any header contains `\\r` or `\\n` (CVE-2025-20384).
- Custom rule: deny if `return_to` query parameter starts with
  `http://` or `https://` (CVE-2025-20379).
- Allowlist Splunk SDK / forwarder user-agents on HEC paths so the
  built-in bot mitigation does not block ingest.
- Origin cert pinning for backend integrity.
"""


def render_saml_idp_handoff(args: argparse.Namespace) -> str:
    return f"""# SAML IdP Handoff

## What you must configure on the IdP side

1. **Entity ID**: `{args.saml_entity_id or 'https://' + args.public_fqdn + '/saml'}`
2. **ACS URL**: `https://{args.public_fqdn}/saml/acs`
3. **SLO URL**: `https://{args.public_fqdn}/saml/logout`
4. **NameID**: `urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress`
5. **Signed AuthnRequest**: required.
6. **Signed assertions**: required (`signedAssertion = true`).
7. **Signature algorithm**: `{args.saml_signature_algorithm}` (no SHA-1).
8. **MFA enforcement**: ALL users must complete MFA at the IdP. Splunk
   has no native WebAuthn, so the IdP is the FIDO2 surface.
9. **Group → role mapping**: do NOT map any IdP group to `admin` or
   `sc_admin`. Splunk's `excludedAutoMappedRoles = admin,sc_admin`
   stops accidental privilege escalation through SAML.

## Hardening against XSW (XML signature wrapping)

- Use a recent SAML library (Splunk's built-in SAML in 9.4+ is
  hardened).
- Reject any unsigned assertion or AuthnResponse.
- Validate `Issuer`, `InResponseTo`, `Recipient`, `NotBefore`,
  `NotOnOrAfter`. Splunk does this when `signedAssertion = true` is
  set.

## Break-glass admin

Local Splunk admin (with strong password + IdP-required MFA) MUST exist
in case the IdP itself goes down. The skill renames the stock `admin`
user; rename to something org-specific (e.g. `breakglass_<initials>`)
post-bootstrap.
"""


def render_duo_mfa_handoff(args: argparse.Namespace) -> str:
    return """# Duo MFA Handoff

Splunk has native Duo Web SDK integration in `web.conf` but the modern
recommendation is **Duo Universal Prompt with passkeys / security
keys** through the SAML IdP rather than Duo Web SDK in Splunk Web.

## Recommended path

1. Use Okta / Entra ID / Auth0 as the SAML IdP.
2. Configure Duo as the MFA factor in the IdP (Universal Prompt).
3. Require WebAuthn / passkeys / security keys at the IdP. Push and
   SMS are NOT acceptable for an internet-facing administrative
   surface.
4. Map IdP groups to Splunk roles via SAML attribute statements. Never
   map any group to `admin` or `sc_admin`.

## Native Duo Web SDK

Splunk supports `[authentication] authType = SAML` plus Duo
authentication scheme natively. If your IdP cannot host Duo, configure
Splunk's native Duo:

- Generate Duo Web ikey / skey / akey in the Duo Admin Panel.
- Place ikey, skey, akey in `web.conf` `[authentication_extra_args]`
  via the apply-search-head.sh fragment mechanism. Never put them on
  argv or in chat.
- Require Duo for all users via `[role_*]` settings.
"""


def render_certificate_procurement(args: argparse.Namespace) -> str:
    return f"""# Certificate Procurement

The skill does not call out to a CA. The operator must:

1. Generate a CSR using the rendered `splunk/certificates/generate-csr-template.sh`.
2. Submit the CSR to your CA (Let's Encrypt / DigiCert / Sectigo / internal).
3. Receive the leaf certificate plus the chain.
4. Combine into a fullchain PEM:
   `cat leaf.pem intermediate.pem root.pem > {args.public_fqdn}.fullchain.pem`
5. Place the fullchain at `{args.server_cert_path}` (or whatever path
   you configured), and the private key at `{args.server_key_path}`
   with mode 0400 owned by `{args.service_user}`.
6. Run `splunk/certificates/verify-certs.sh` — it must exit zero.
7. Update the proxy nginx / HAProxy templates to point at the same fullchain
   plus key files.

## Required certificate properties

- ≥ 2048-bit RSA, or P-256/P-384 ECDSA.
- SHA-256 or stronger signature.
- Subject CN = `{args.public_fqdn}`.
- Subject Alt Names: at minimum `{args.required_sans or args.public_fqdn}`.
- Not expired; not yet beyond NotBefore.
- Chain validates against your CA's root.

## Rotation

Rotate ≤ 30 days before expiry. Test the rotation in a staging copy
first; restart Splunk after the rotation.
"""


def render_soc_alerting_runbook(args: argparse.Namespace) -> str:
    return """# SOC Alerting Runbook

The hardening posture is monitored from the SIEM, not Splunk Web. The
following alerts MUST fire on the events emitted by the rendered
config.

## Auth events

```
index=_audit action=login_attempt info=failed
| stats count by user, src_ip, _time
| where count > 10 within 5m
```

## Capability changes

```
index=_internal sourcetype=splunkd_audit action=update info=capability_change
```

## App installs / uploads

```
index=_internal source=*splunkd.log "Installing app" OR "Removing app"
```

## splunk.secret access

File integrity monitoring on `$SPLUNK_HOME/etc/auth/splunk.secret`. Any
read by a non-`splunk` user is suspect.

## TLS handshake failures spike

```
index=_internal source=*splunkd.log component=SSLConfig log_level=ERROR
| stats count by host, _time
```

## Capability check drift

Run weekly:

```
| rest /services/authorization/capabilities
| where role!="admin" AND (capability="edit_cmd" OR capability="run_sendalert")
```

## Recommended escalation

1. Three failed login alerts within 5 minutes from the same IP →
   auto-block at the WAF for 1 hour.
2. Any capability drift → page on-call.
3. Any `splunk.secret` access alert → page security on-call AND
   initiate `handoff/incident-response-splunk-secret.md`.
"""


def render_backup_and_restore(args: argparse.Namespace) -> str:
    return """# Backup and Restore

## What to back up

- `$SPLUNK_HOME/etc/` — every search head, indexer, deployer, license
  manager.
- KV store snapshots (`splunk backup kvstore` on each SHC member).
- Index buckets (only `_audit`, `_internal` if you do not have a
  separate SIEM; otherwise the SIEM owns them).
- TLS leaf cert + private key (encrypted).
- `$SPLUNK_HOME/etc/auth/splunk.secret` — encrypted; required for
  decrypting backed-up config files.

## Encryption at rest

Use the OS / cloud encryption layer (LUKS, EBS encryption, GCS
customer-managed keys) plus a separate per-backup symmetric key.
Never put the symmetric key in the same backup target as the data.

## Restore drill

Run the full restore on a staging host quarterly:

1. Restore `$SPLUNK_HOME/etc` to staging.
2. Restore the matching `splunk.secret`.
3. Start Splunk; verify role / app / TLS posture.
4. Restore one indexer's bucket; verify search.
5. Document the runbook deltas.

## Retention

- Daily: 30 days.
- Weekly: 12 weeks.
- Monthly: 12 months.
- Annual: 7 years (legal hold).
"""


def render_incident_response_splunk_secret(args: argparse.Namespace) -> str:
    return """# Incident Response — `splunk.secret` Compromise

If you have any reason to believe `splunk.secret` has leaked
(adversary access to backup, container image, or the host
filesystem), assume every encrypted credential in `etc/` is
compromised. Splunk advisories SVD-2026-0207 and SVD-2026-0203
documented `_internal` paths that leaked it via debug log content.

## Step 1 — Contain

- Block all outbound from the affected host pending forensics.
- Rotate any credentials that you can NOT undo in step 2 (e.g. cloud
  IAM keys referenced by Splunk inputs).

## Step 2 — Inventory the encrypted material

Encrypted credentials live in:
- `etc/system/local/server.conf` (`pass4SymmKey`, `sslPassword`)
- `etc/system/local/inputs.conf` and per-app `inputs.conf`
- `etc/system/local/outputs.conf`
- `etc/passwd` (Splunk-managed `$1$...` style)
- `etc/apps/*/local/*.conf` for any `password`, `token`,
  `clientSecret`, `apikey` field
- `etc/auth/passwd.d/`

## Step 3 — Decrypt with the OLD secret

Use the running Splunk on the original host (or a staging clone with
the old `splunk.secret`) to decrypt every credential into a temporary
plaintext list. NEVER store this list outside of memory or an
encrypted volume.

## Step 4 — Replace `splunk.secret`

```bash
bash splunk/rotate-splunk-secret.sh /tmp/new_splunk_secret_file
```

## Step 5 — Re-encrypt every credential

Each credential must be re-saved through Splunk so the new secret
encrypts it (e.g. `splunk edit licenser-localpeer`,
`splunk add forward-server`, `splunk edit user`).

## Step 6 — Restart and validate

`splunk restart` on the affected host; re-run the rendered
`validate.sh`.

## Step 7 — Post-incident

- Audit who had access to the original `splunk.secret`.
- File a security review.
- Rotate any HEC tokens, API keys, and app credentials that were
  re-encrypted.
"""


def render_compliance_control_mapping(args: argparse.Namespace) -> str:
    return """# Compliance Control Mapping

The skill maps DISA STIG Splunk Enterprise 8.x for Linux V2R2 controls
to the rendered configuration. It does NOT certify PCI / HIPAA /
FedRAMP / SOC 2 — Splunk Enterprise self-hosted inherits NO third-party
attestations.

| Control | Rendered overlay | Notes |
|---|---|---|
| V-251680 | web.conf `enableSplunkWebSSL = true` | HTTPS for UI |
| V-251681 | inputs.conf `[splunktcp-ssl]` `requireClientCert = true` | mTLS S2S |
| V-251682 | server.conf `[sslConfig]` requires `sslVerifyServerCert = true` | TLS verify peer |
| V-251683 | authentication.conf SAML stanza | DoD CAC via SAML/PKI |
| V-251684 | authorize.conf `never_lockout = disabled` on admin | Lockable admin |
| V-251685 | authentication.conf `[splunk_auth]` complexity + history | Password policy |
| V-251686 | authentication.conf `expirePasswordDays = 90` | Aging |
| V-251687 | authentication.conf `enablePasswordHistory = true` | History |
| V-251688 | authorize.conf removed capabilities | Least privilege |
| V-251689 | TLS 1.2+ only, SHA-256+ | Crypto policy |
| V-251690 | server.conf `caCertFile` operator-supplied | DoD-approved CAs |
| V-251691 | server.conf `[httpServer] verboseLoginFailMsg = false` | No info disclosure |
| V-251692 | authentication.conf SAML + IdP MFA | PKI auth |

## PCI DSS 4.0 mapping

- 1.x — covered by firewall snippets and `acceptFrom`.
- 2.x — covered by default-cert refusal and pass4SymmKey rotation.
- 3.x — operator owns at-rest encryption (backup/restore handoff).
- 4.x — TLS 1.2+ everywhere, HSTS at proxy.
- 6.x — SVD floor enforcement.
- 7.x — `role_public_reader` + admin-only RBAC.
- 8.x — IdP MFA.
- 10.x — `_audit` ingest + SOC alerting handoff.
- 11.x — operator-owned scanning + validate.sh.
- 12.x — operator-owned policy / training.

## HIPAA Security Rule

- §164.308 — administrative safeguards: operator-owned.
- §164.310 — physical safeguards: operator-owned (DC).
- §164.312 — technical safeguards:
  - (a) access control: `role_public_reader` + IdP MFA.
  - (b) audit controls: `_audit` + SOC handoff.
  - (c) integrity: `enableDataIntegrityControl` (set in indexes.conf
    by your indexer skill).
  - (d) authentication: SAML + IdP MFA.
  - (e) transmission security: TLS 1.2+ everywhere.

## FedRAMP

Splunk Enterprise self-hosted is NOT in any FedRAMP boundary. Splunk
Cloud (the SaaS offering) is FedRAMP High since 2024-09-13. To run
FedRAMP-bound workloads on this hardening overlay, your org must own
the FedRAMP authorization for the host.

## SOC 2

Operator-owned end-to-end. The skill provides evidence artifacts (the
rendered `metadata.json`, `validate-report.json`, audit logs) but the
SOC 2 auditor needs your org's broader operational controls.
"""


# ---------------------------------------------------------------------------
# Preflight + validate (rendered into the output dir, not under splunk/).
# ---------------------------------------------------------------------------

def render_preflight(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    fqdn = shell_quote(args.public_fqdn)
    proxy_cidr = shell_quote(args.proxy_cidr)
    probe = shell_quote(args.external_probe_cmd or "")
    helper = shell_quote(helper_path())
    cert_path = shell_quote(args.server_cert_path)
    return make_script(
        f"""splunk_home={splunk_home}
fqdn={fqdn}
proxy_cidr={proxy_cidr}
external_probe={probe}
cert_path={cert_path}
helper={helper}

failures=0

fail() {{
  echo "FAIL: $1" >&2
  failures=$((failures + 1))
}}

ok() {{
  echo "OK:   $1"
}}

# 1. Default-cert detection
subject="$(openssl x509 -in "$cert_path" -noout -subject 2>/dev/null || true)"
case "$subject" in
  *SplunkServerDefaultCert*|*SplunkCommonCA*|*SplunkWebDefaultCert*)
    fail "default Splunk-shipped certificate still in use ($subject)"
    ;;
  *)
    ok "no default Splunk-shipped certificate detected"
    ;;
esac

# 2. Certificate sanity
script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
verify_script="$script_dir/splunk/certificates/verify-certs.sh"
if [[ -x "$verify_script" ]]; then
  if "$verify_script" >/tmp/verify_certs.log 2>&1; then
    ok "verify-certs.sh passed"
  else
    fail "verify-certs.sh failed: see /tmp/verify_certs.log"
  fi
else
  fail "verify-certs.sh missing or not executable"
fi

# 3. Splunk version vs SVD floor (recorded in metadata.json)
running_version="$("${{splunk_home}}/bin/splunk" version 2>/dev/null | awk '/Splunk/ {{print $2; exit}}' || true)"
if [[ -z "$running_version" ]]; then
  fail "could not determine Splunk version"
else
  ok "Splunk version: $running_version"
fi

# 4. pass4SymmKey not default
if "${{splunk_home}}/bin/splunk" btool server list general 2>/dev/null \\
   | grep -q '^pass4SymmKey *= *changeme'; then
  fail "pass4SymmKey is the default 'changeme'"
else
  ok "pass4SymmKey is not the default literal"
fi

# 5. splunk.secret posture
secret_file="${{splunk_home}}/etc/auth/splunk.secret"
if [[ ! -f "$secret_file" ]]; then
  fail "splunk.secret missing"
else
  perms="$(stat -c '%a' "$secret_file" 2>/dev/null || stat -f '%A' "$secret_file" 2>/dev/null)"
  if [[ "$perms" != "400" && "$perms" != "0400" ]]; then
    fail "splunk.secret mode is $perms (expected 400)"
  else
    ok "splunk.secret mode is $perms"
  fi
fi

# 6. sslPassword not default
if "${{splunk_home}}/bin/splunk" btool server list sslConfig 2>/dev/null \\
   | grep -q '^sslPassword *= *password *$'; then
  fail "sslConfig sslPassword is the literal 'password'"
else
  ok "sslConfig sslPassword is not the default literal"
fi

# 7. admin role lockout posture
if "${{splunk_home}}/bin/splunk" btool authorize list role_admin 2>/dev/null \\
   | grep -q '^never_lockout *= *enabled'; then
  fail "[role_admin] never_lockout = enabled (Splunk default; must be disabled)"
else
  ok "[role_admin] never_lockout != enabled"
fi

# 8. High-risk capabilities on non-admin roles
forbidden_caps="edit_cmd edit_scripted rest_apps_management delete_by_keyword change_authentication run_sendalert run_dump run_custom_command"
btool="$("${{splunk_home}}/bin/splunk" btool authorize list 2>/dev/null || true)"
current_role=""
while IFS= read -r line; do
  case "$line" in
    \\[role_*\\])
      current_role="$line"
      ;;
    *)
      for cap in $forbidden_caps; do
        if [[ "$current_role" != "[role_admin]" && "$line" == "$cap = enabled" ]]; then
          fail "non-admin role $current_role has $cap = enabled"
        fi
      done
      ;;
  esac
done <<<"$btool"
ok "scanned non-admin roles for high-risk capabilities"

# 9. enableSplunkWebClientNetloc must be false (CVE-2025-20371)
if "${{splunk_home}}/bin/splunk" btool web list settings 2>/dev/null \\
   | grep -q '^enableSplunkWebClientNetloc *= *true'; then
  fail "enableSplunkWebClientNetloc = true (CVE-2025-20371 SSRF)"
else
  ok "enableSplunkWebClientNetloc != true"
fi

# 10. request.show_tracebacks must be false
if "${{splunk_home}}/bin/splunk" btool web list settings 2>/dev/null \\
   | grep -q '^request.show_tracebacks *= *true'; then
  fail "request.show_tracebacks = true (leaks stack traces)"
else
  ok "request.show_tracebacks != true"
fi

# 11. crossOriginSharingPolicy not '*'
if "${{splunk_home}}/bin/splunk" btool web list settings 2>/dev/null \\
   | grep -q '^crossOriginSharingPolicy *= *\\*'; then
  fail "crossOriginSharingPolicy = * (wildcard CORS not allowed)"
else
  ok "crossOriginSharingPolicy is not wildcard"
fi

# 12. verboseLoginFailMsg must be false
if "${{splunk_home}}/bin/splunk" btool server list httpServer 2>/dev/null \\
   | grep -q '^verboseLoginFailMsg *= *true'; then
  fail "[httpServer] verboseLoginFailMsg = true (username enumeration oracle)"
else
  ok "[httpServer] verboseLoginFailMsg != true"
fi

# 13. DNS resolution
if getent hosts "$fqdn" >/dev/null 2>&1 || nslookup "$fqdn" >/dev/null 2>&1; then
  ok "DNS forward resolution works for $fqdn"
else
  fail "DNS forward resolution failed for $fqdn"
fi

# 14. External probe (ports must be UNREACHABLE from outside)
if [[ -n "$external_probe" ]]; then
  for port in 8089 8191 9887 8065; do
    if eval "$external_probe $fqdn $port" >/dev/null 2>&1; then
      fail "port $port is reachable from outside (must be blocked)"
    else
      ok "port $port is unreachable from outside"
    fi
  done
else
  echo "WARN: no --external-probe-cmd; skipping external port probe."
fi

# 15. TLS scan (basic)
if openssl s_client -connect "$fqdn:443" -tls1 </dev/null >/dev/null 2>&1; then
  fail "TLS 1.0 still negotiates on $fqdn:443"
else
  ok "TLS 1.0 not negotiated"
fi
if openssl s_client -connect "$fqdn:443" -tls1_1 </dev/null >/dev/null 2>&1; then
  fail "TLS 1.1 still negotiates on $fqdn:443"
else
  ok "TLS 1.1 not negotiated"
fi

# 16. HSTS header present at proxy
hsts="$(curl -sk -I "https://$fqdn/" 2>/dev/null | tr -d '\\r' | awk -F': ' 'tolower($1)=="strict-transport-security"{{print $2}}')"
if [[ -n "$hsts" ]]; then
  ok "HSTS header present: $hsts"
else
  fail "HSTS header missing on https://$fqdn/"
fi

# 17. Log-injection probe — SVD-2025-1203 / CVE-2025-20384 (ANSI escape +
# CR/LF at /en-US/static/). Proxy must reject ESC \\x1b, BEL \\x07, CR/LF.
status_ansi="$(curl -sk -o /dev/null -w '%{{http_code}}' \\
  -H $'User-Agent: probe\\x1b[31mred' \\
  "https://$fqdn/en-US/static/" 2>/dev/null || true)"
status_crlf="$(curl -sk -o /dev/null -w '%{{http_code}}' \\
  -H $'X-Forwarded-For: 1.2.3.4\\r\\nX-Injected: yes' \\
  "https://$fqdn/en-US/account/login" 2>/dev/null || true)"
case "$status_ansi" in
  400|401|403|404)
    ok "proxy rejected ANSI escape in headers (status $status_ansi)"
    ;;
  *)
    fail "proxy accepted ANSI escape in headers (status $status_ansi)"
    ;;
esac
case "$status_crlf" in
  400|401|403)
    ok "proxy rejected CR/LF in headers (status $status_crlf)"
    ;;
  *)
    fail "proxy accepted CR/LF in headers (status $status_crlf)"
    ;;
esac

# 18. return_to redirect probe (proxy must reject absolute URLs)
status="$(curl -sk -o /dev/null -w '%{{http_code}}' \\
  "https://$fqdn/en-US/account/login?return_to=https://attacker.example.com/" 2>/dev/null || true)"
case "$status" in
  400|403|404)
    ok "proxy rejected absolute return_to (status $status)"
    ;;
  *)
    fail "proxy accepted absolute return_to (status $status)"
    ;;
esac

# 19. WAF/proxy reachable
status="$(curl -sk -o /dev/null -w '%{{http_code}}' "https://$fqdn/en-US/account/login" 2>/dev/null || true)"
if [[ "$status" == "200" ]]; then
  ok "Splunk Web login page reachable (200)"
else
  fail "Splunk Web login page returned $status"
fi

# 20. CSRF cookie unmodified
ck="$(curl -sk -I "https://$fqdn/en-US/account/login" 2>/dev/null | tr -d '\\r' | awk 'tolower($1)=="set-cookie:"' | grep -E 'splunkweb_csrf_token_' || true)"
if [[ -n "$ck" ]]; then
  ok "splunkweb_csrf_token cookie returned through proxy"
else
  fail "splunkweb_csrf_token cookie missing — proxy is stripping it"
fi

# 21. Sensitive-path denies. Proxy must drop these at the edge regardless
# of authentication state so the surface cannot be probed.
for path in /services/apps/local /services/apps/appinstall \\
            /services/configs/conf-passwords /services/data/inputs/oneshot \\
            /account/insecurelogin /en-US/account/insecurelogin /debug/refresh; do
  status="$(curl -sk -o /dev/null -w '%{{http_code}}' "https://$fqdn$path" 2>/dev/null || true)"
  case "$status" in
    403|404)
      ok "proxy denies $path (status $status)"
      ;;
    *)
      fail "proxy reachable for sensitive path $path (status $status)"
      ;;
  esac
done

if [[ "$failures" -gt 0 ]]; then
  echo "PREFLIGHT FAILED: $failures check(s) failed." >&2
  exit 1
fi

echo "PREFLIGHT PASSED."
"""
    )


def render_validate(args: argparse.Namespace) -> str:
    fqdn = shell_quote(args.public_fqdn)
    probe = shell_quote(args.external_probe_cmd or "")
    return make_script(
        f"""fqdn={fqdn}
external_probe={probe}

report="${{1:-./validate-report.json}}"
checks=()
failures=0

record() {{
  local name="$1" status="$2" detail="$3"
  checks+=("{{\\"check\\":\\"$name\\",\\"status\\":\\"$status\\",\\"detail\\":\\"$detail\\"}}")
  if [[ "$status" != "ok" ]]; then
    failures=$((failures + 1))
  fi
}}

# HTTPS-only redirect
loc="$(curl -ski -o /dev/null -w '%{{redirect_url}} %{{http_code}}' "http://$fqdn/" 2>/dev/null || true)"
case "$loc" in
  https://*\\ 301)
    record https_redirect ok "$loc"
    ;;
  *)
    record https_redirect fail "$loc"
    ;;
esac

# HSTS
hsts="$(curl -sk -I "https://$fqdn/" 2>/dev/null | tr -d '\\r' | awk -F': ' 'tolower($1)=="strict-transport-security"{{print $2}}')"
if [[ -n "$hsts" ]]; then
  record hsts_header ok "$hsts"
else
  record hsts_header fail "missing"
fi

# CSP
csp="$(curl -sk -I "https://$fqdn/" 2>/dev/null | tr -d '\\r' | awk -F': ' 'tolower($1)=="content-security-policy"{{print $2}}')"
if [[ -n "$csp" ]]; then
  record csp_header ok "$csp"
else
  record csp_header fail "missing"
fi

# X-Content-Type-Options
xcto="$(curl -sk -I "https://$fqdn/" 2>/dev/null | tr -d '\\r' | awk -F': ' 'tolower($1)=="x-content-type-options"{{print $2}}')"
if [[ "$xcto" == "nosniff" ]]; then
  record xcto_header ok "nosniff"
else
  record xcto_header fail "$xcto"
fi

# TLS 1.0 / 1.1 absent
if openssl s_client -connect "$fqdn:443" -tls1 </dev/null >/dev/null 2>&1; then
  record tls10_absent fail "negotiated"
else
  record tls10_absent ok "blocked"
fi
if openssl s_client -connect "$fqdn:443" -tls1_1 </dev/null >/dev/null 2>&1; then
  record tls11_absent fail "negotiated"
else
  record tls11_absent ok "blocked"
fi

# External port probe
if [[ -n "$external_probe" ]]; then
  for port in 8089 8191 9887 8065; do
    if eval "$external_probe $fqdn $port" >/dev/null 2>&1; then
      record "port_${{port}}_blocked" fail "reachable"
    else
      record "port_${{port}}_blocked" ok "unreachable"
    fi
  done
else
  record external_probe skip "no --external-probe-cmd configured"
fi

# Header-injection probe
status="$(curl -sk -o /dev/null -w '%{{http_code}}' -H $'X-Forwarded-For: 1.2.3.4\\r\\nX-Injected: yes' "https://$fqdn/en-US/account/login" 2>/dev/null || true)"
if [[ "$status" =~ ^(400|401|403)$ ]]; then
  record header_injection ok "$status"
else
  record header_injection fail "$status"
fi

# return_to redirect probe
status="$(curl -sk -o /dev/null -w '%{{http_code}}' "https://$fqdn/en-US/account/login?return_to=https://attacker.example.com/" 2>/dev/null || true)"
if [[ "$status" =~ ^(400|403|404)$ ]]; then
  record return_to_redirect ok "$status"
else
  record return_to_redirect fail "$status"
fi

# CSRF cookie pass-through
ck="$(curl -sk -I "https://$fqdn/en-US/account/login" 2>/dev/null | tr -d '\\r' | grep -ic 'splunkweb_csrf_token_')"
if [[ "$ck" -gt 0 ]]; then
  record csrf_cookie ok "present"
else
  record csrf_cookie fail "stripped"
fi

# Per-IP rate limit on login (best-effort: 12 rapid POSTs should trigger 429/503)
hit429=0
for i in $(seq 1 12); do
  status="$(curl -sk -o /dev/null -w '%{{http_code}}' -X POST -d 'username=alice&password=fake' "https://$fqdn/en-US/account/login" 2>/dev/null || true)"
  if [[ "$status" =~ ^(429|503)$ ]]; then
    hit429=1
    break
  fi
done
if [[ "$hit429" == "1" ]]; then
  record login_rate_limit ok "blocked at proxy"
else
  record login_rate_limit fail "not enforced — operator must add rate-limit at proxy / WAF"
fi

# Emit JSON report
{{
  printf '{{"checks":['
  printf '%s' "$(IFS=,; echo "${{checks[*]}}")"
  printf '],"failures":%d}}' "$failures"
}} > "$report"

if [[ "$failures" -gt 0 ]]; then
  echo "VALIDATE FAILED: $failures check(s) failed. See $report" >&2
  exit 1
fi

echo "VALIDATE PASSED. Report: $report"
"""
    )


# ---------------------------------------------------------------------------
# README + metadata
# ---------------------------------------------------------------------------

def render_readme(args: argparse.Namespace) -> str:
    return f"""# Splunk Public Exposure Hardening — Rendered Assets

Public FQDN: `{args.public_fqdn}`{(f"`\nHEC FQDN: `{args.hec_fqdn}`" if args.hec_fqdn else '')}
Topology:    `{args.topology}`
Splunk version target: `{args.splunk_version}` (SVD floor enforced)

## What is here

- `splunk/apps/000_public_exposure_hardening/` — the Splunk app to drop
  into `$SPLUNK_HOME/etc/apps/` (or the SHC deployer's
  `shcluster/apps/`). Contains `web.conf`, `server.conf`, `inputs.conf`,
  `outputs.conf`, `authentication.conf`, `authorize.conf`, `limits.conf`,
  `commands.conf`, plus `metadata/{{default,local}}.meta`.
- `splunk/apply-*.sh` — role-aware apply scripts. The search-head one
  injects `pass4SymmKey` and `sslPassword` from operator-supplied local
  files at apply time (never argv).
- `splunk/rotate-*.sh` — `pass4SymmKey` and `splunk.secret` rotation
  helpers.
- `splunk/certificates/` — `verify-certs.sh` (refuses default Splunk
  certs, weak keys, expired) and `generate-csr-template.sh`.
- `proxy/nginx/` — production nginx vhosts for Splunk Web and HEC with
  TLS, browser security headers, header sanitisation, return_to
  allowlist, per-IP rate limit, streaming-safe timeouts, WebSocket
  plumbing.
- `proxy/haproxy/` — HAProxy equivalents.
- `proxy/firewall/` — iptables / nftables / firewalld / AWS SG snippets
  that drop 8089 / 8191 / 8065 / 9887 from the public CIDR.
- `handoff/` — operator checklist and per-platform WAF / SAML / Duo /
  certificate / SOC / backup / incident-response / compliance docs.
- `preflight.sh` — 20-step pre-deploy check; fail-closed.
- `validate.sh` — live post-deploy validation; emits
  `validate-report.json`.

## How to apply

1. Run `bash preflight.sh` — must exit 0.
2. On the search head, run
   `bash splunk/apply-search-head.sh` (the parent setup.sh wraps this
   when `--phase apply --accept-public-exposure` is passed).
3. On the SHC deployer, run `bash splunk/apply-deployer.sh` then
   `splunk apply shcluster-bundle`.
4. Run `bash validate.sh` — must exit 0.

## Safety

- The renderer never embeds secret values in any rendered file.
- The apply scripts read pass4SymmKey, sslPassword, and SAML signing
  certs from local file paths only.
- `metadata.json` records non-secret configuration parameters used to
  produce this directory.
"""


def render_metadata(args: argparse.Namespace, floor: dict[str, str]) -> dict:
    return {
        "skill": "splunk-enterprise-public-exposure-hardening",
        "topology": args.topology,
        "public_fqdn": args.public_fqdn,
        "hec_fqdn": args.hec_fqdn,
        "proxy_cidr": args.proxy_cidr,
        "indexer_cluster_cidr": args.indexer_cluster_cidr,
        "bastion_cidr": args.bastion_cidr,
        "enable_web": args.enable_web == "true",
        "enable_hec": args.enable_hec == "true",
        "enable_s2s": args.enable_s2s == "true",
        "hec_mtls": args.hec_mtls == "true",
        "splunk_home": args.splunk_home,
        "splunk_version": args.splunk_version,
        "tls_policy": args.tls_policy,
        "auth_mode": args.auth_mode,
        "min_password_length": args.min_password_length,
        "lockout_attempts": args.lockout_attempts,
        "lockout_mins": args.lockout_mins,
        "hec_max_content_length": args.hec_max_content_length,
        "login_rate_per_minute": args.login_rate_per_minute,
        "streaming_search_timeout": args.streaming_search_timeout,
        "enable_fips": args.enable_fips == "true",
        "fips_version": args.fips_version if args.enable_fips == "true" else None,
        "allowed_unarchive_commands": args.allowed_unarchive_commands,
        "svd_floor": floor,
        "accept_public_exposure_required_at_apply": True,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def emit_all(args: argparse.Namespace, render_dir: Path, floor: dict[str, str]) -> list[str]:
    files: dict[str, str | bytes] = {
        "README.md": render_readme(args),
        "metadata.json": json.dumps(render_metadata(args, floor), indent=2, sort_keys=True) + "\n",
        # Splunk app
        "splunk/apps/000_public_exposure_hardening/default/app.conf": render_app_conf(args),
        "splunk/apps/000_public_exposure_hardening/default/web.conf": render_web_conf(args),
        "splunk/apps/000_public_exposure_hardening/default/server.conf": render_server_conf(args),
        "splunk/apps/000_public_exposure_hardening/default/inputs.conf": render_inputs_conf(args),
        "splunk/apps/000_public_exposure_hardening/default/outputs.conf": render_outputs_conf(args),
        "splunk/apps/000_public_exposure_hardening/default/authentication.conf": render_authentication_conf(args),
        "splunk/apps/000_public_exposure_hardening/default/authorize.conf": render_authorize_conf(args),
        "splunk/apps/000_public_exposure_hardening/default/limits.conf": render_limits_conf(args),
        "splunk/apps/000_public_exposure_hardening/default/commands.conf": render_commands_conf(args),
        "splunk/apps/000_public_exposure_hardening/default/props.conf": render_props_conf(args),
        "splunk/apps/000_public_exposure_hardening/default/splunk-launch.conf": render_splunk_launch_conf(args),
        "splunk/apps/000_public_exposure_hardening/metadata/default.meta": render_default_meta(args),
        "splunk/apps/000_public_exposure_hardening/metadata/local.meta": render_local_meta(args),
        # Reverse-proxy templates
        "proxy/nginx/splunk-web.conf": render_nginx_web(args),
        "proxy/nginx/splunk-hec.conf": render_nginx_hec(args),
        "proxy/nginx/README.md": render_nginx_readme(args),
        "proxy/haproxy/splunk-web.cfg": render_haproxy_web(args),
        "proxy/haproxy/splunk-hec.cfg": render_haproxy_hec(args),
        "proxy/haproxy/README.md": render_haproxy_readme(args),
        "proxy/firewall/iptables.rules": render_iptables(args),
        "proxy/firewall/nftables.conf": render_nftables(args),
        "proxy/firewall/firewalld.xml": render_firewalld(args),
        "proxy/firewall/aws-sg.json": json.dumps(render_aws_sg(args), indent=2) + "\n",
        "proxy/firewall/README.md": render_firewall_readme(args),
        # Handoff docs
        "handoff/operator-checklist.md": render_operator_checklist(args),
        "handoff/waf-cloudflare.md": render_waf_cloudflare(args),
        "handoff/waf-aws.md": render_waf_aws(args),
        "handoff/waf-f5-imperva.md": render_waf_f5_imperva(args),
        "handoff/saml-idp-handoff.md": render_saml_idp_handoff(args),
        "handoff/duo-mfa-handoff.md": render_duo_mfa_handoff(args),
        "handoff/certificate-procurement.md": render_certificate_procurement(args),
        "handoff/soc-alerting-runbook.md": render_soc_alerting_runbook(args),
        "handoff/backup-and-restore.md": render_backup_and_restore(args),
        "handoff/incident-response-splunk-secret.md": render_incident_response_splunk_secret(args),
        "handoff/compliance-control-mapping.md": render_compliance_control_mapping(args),
    }

    executable_files: dict[str, str] = {
        "preflight.sh": render_preflight(args),
        "validate.sh": render_validate(args),
        "splunk/apply-search-head.sh": render_apply_search_head(args),
        "splunk/apply-hec-tier.sh": render_apply_hec_tier(args),
        "splunk/apply-s2s-receiver.sh": render_apply_s2s_receiver(args),
        "splunk/apply-heavy-forwarder.sh": render_apply_heavy_forwarder(args),
        "splunk/apply-deployer.sh": render_apply_deployer(args),
        "splunk/apply-cluster-manager.sh": render_apply_cluster_manager(args),
        "splunk/apply-license-manager.sh": render_apply_license_manager(args),
        "splunk/rotate-pass4symmkey.sh": render_rotate_pass4symmkey(args),
        "splunk/rotate-splunk-secret.sh": render_rotate_splunk_secret(args),
        "splunk/certificates/verify-certs.sh": render_verify_certs(args),
        "splunk/certificates/generate-csr-template.sh": render_generate_csr_template(args),
        "splunk/certificates/README.md": render_certificates_readme(args),
    }

    written: list[str] = []
    for rel, content in files.items():
        if rel not in GENERATED_FILES:
            die(f"renderer tried to emit unmanaged file {rel!r}")
        if isinstance(content, bytes):
            (render_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            (render_dir / rel).write_bytes(content)
        else:
            write_file(render_dir / rel, content)
        written.append(rel)

    for rel, content in executable_files.items():
        if rel not in GENERATED_FILES:
            die(f"renderer tried to emit unmanaged executable file {rel!r}")
        write_file(render_dir / rel, content, executable=True)
        written.append(rel)

    missing = sorted(GENERATED_FILES - set(written))
    if missing:
        die(f"renderer omitted required files: {missing}")
    return sorted(written)


def main() -> None:
    args = parse_args()
    validate(args)
    floor = load_svd_floor(args)
    check_svd_floor(args, floor)

    render_dir = Path(args.output_dir).expanduser().resolve() / "public-exposure"

    if args.dry_run:
        plan = {
            "render_dir": str(render_dir),
            "topology": args.topology,
            "public_fqdn": args.public_fqdn,
            "files_count": len(GENERATED_FILES),
            "svd_floor": floor,
        }
        if args.json:
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            for k, v in plan.items():
                print(f"{k}: {v}")
        return

    render_dir.mkdir(parents=True, exist_ok=True)
    clean_render_dir(render_dir)
    written = emit_all(args, render_dir, floor)

    if args.json:
        print(json.dumps({"render_dir": str(render_dir), "files": written}, indent=2))
    else:
        print(f"Rendered {len(written)} files under {render_dir}")


if __name__ == "__main__":
    main()
