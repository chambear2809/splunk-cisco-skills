#!/usr/bin/env python3
"""Diagnose Splunk Connect for OTLP evidence and render a conservative fix plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import tarfile
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urlparse


APP_NAME = "splunk-connect-for-otlp"
LATEST_VERSION = "0.4.1"
KNOWN_SHA256 = "fde0d93532703e04ab5aa544815d52232ef62afae2c0a55e374dc74d2d58f9d1"
KNOWN_MD5 = "6190585a3c12cb9f273f7f9f11cdb3be"
EXPECTED_FILES = [
    "splunk-connect-for-otlp/README/inputs.conf.spec",
    "splunk-connect-for-otlp/default/app.conf",
    "splunk-connect-for-otlp/default/data/ui/manager/splunk-connect-for-otlp.xml",
    "splunk-connect-for-otlp/default/inputs.conf",
    "splunk-connect-for-otlp/default/props.conf",
    "splunk-connect-for-otlp/linux_x86_64/bin/splunk-connect-for-otlp",
    "splunk-connect-for-otlp/metadata/default.meta",
    "splunk-connect-for-otlp/windows_x86_64/bin/splunk-connect-for-otlp",
]
SIGNAL_PATHS = {"/v1/logs", "/v1/metrics", "/v1/traces"}
TOKEN_RE = re.compile(r"(Authorization\s*[:=]\s*Splunk\s+)[A-Za-z0-9._:-]+", re.I)
SECRET_KEY_RE = re.compile(r"(token|password|secret|authorization)", re.I)


@dataclass
class Finding:
    fix_id: str
    severity: str
    title: str
    detail: str
    recommended_action: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk Connect for OTLP doctor reports.")
    parser.add_argument("--evidence-file", default="")
    parser.add_argument("--package-file", default="")
    parser.add_argument("--output-dir", default="splunk-connect-for-otlp-rendered")
    parser.add_argument("--expected-index", default="otlp_events")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def redact_text(value: str) -> str:
    return TOKEN_RE.sub(r"\1[REDACTED]", value)


def redact_value(key: str, value: object) -> object:
    if isinstance(value, dict):
        return {k: redact_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(key, item) for item in value]
    if isinstance(value, str):
        if SECRET_KEY_RE.search(key) and value and not value.startswith("/"):
            return "[REDACTED]"
        return redact_text(value)
    return value


def load_evidence(path: str) -> dict:
    if not path:
        return {
            "platform": {
                "os": platform.system().lower(),
                "machine": platform.machine().lower(),
            },
            "app": {},
            "inputs": [],
            "hec": {},
            "senders": [],
            "internal_errors": [],
        }
    with Path(path).expanduser().open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SystemExit("ERROR: evidence file must contain a JSON object.")
    return data


def truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "enabled", "on"}
    return False


def add(findings: list[Finding], fix_id: str, severity: str, title: str, detail: str, action: str) -> None:
    findings.append(
        Finding(
            fix_id=fix_id,
            severity=severity,
            title=title,
            detail=redact_text(detail),
            recommended_action=redact_text(action),
        )
    )


def as_list(value: object) -> list:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def port_value(raw: object) -> int | None:
    try:
        return int(str(raw))
    except Exception:
        return None


def token_allowed_indexes(hec: dict) -> set[str]:
    allowed: set[str] = set()
    for key in ("allowed_indexes", "indexes"):
        for item in as_list(hec.get(key)):
            if isinstance(item, str):
                allowed.update(part.strip() for part in item.split(",") if part.strip())
    for token in as_list(hec.get("tokens")):
        if isinstance(token, dict):
            for key in ("allowed_indexes", "indexes"):
                for item in as_list(token.get(key)):
                    if isinstance(item, str):
                        allowed.update(part.strip() for part in item.split(",") if part.strip())
    return allowed


def inspect_package(path: str) -> dict[str, object]:
    if not path:
        return {}
    package = Path(path).expanduser()
    data = package.read_bytes()
    names: list[str] = []
    with tarfile.open(package, "r:*") as archive:
        for member in archive.getmembers():
            if member.isfile():
                names.append(member.name.lstrip("./"))
    return {
        "path": str(package),
        "sha256": hashlib.sha256(data).hexdigest(),
        "md5": hashlib.md5(data).hexdigest(),
        "files": sorted(names),
        "expected_files": EXPECTED_FILES,
        "matches_known_sha256": hashlib.sha256(data).hexdigest() == KNOWN_SHA256,
        "matches_known_md5": hashlib.md5(data).hexdigest() == KNOWN_MD5,
        "missing_expected_files": sorted(set(EXPECTED_FILES) - set(names)),
        "extra_files": sorted(set(names) - set(EXPECTED_FILES)),
    }


def analyze_package(findings: list[Finding], package_info: dict[str, object]) -> None:
    if not package_info:
        return
    if package_info.get("sha256") != KNOWN_SHA256:
        add(
            findings,
            "PACKAGE_HASH_MISMATCH",
            "high",
            "Local package hash does not match audited 0.4.1 release",
            "The supplied package SHA256 differs from the Splunkbase/GitHub release hash.",
            "Use Splunkbase app 8704 or a local package whose SHA256 matches the audited release.",
        )
    if package_info.get("missing_expected_files"):
        add(
            findings,
            "PACKAGE_CONTENTS_MISMATCH",
            "high",
            "Local package is missing expected files",
            "The archive does not contain the audited Splunk Connect for OTLP file list.",
            "Re-download the app from Splunkbase or GitHub release v0.4.1 and re-run inspection.",
        )


def analyze_platform(findings: list[Finding], evidence: dict) -> None:
    platform_info = evidence.get("platform") if isinstance(evidence.get("platform"), dict) else {}
    os_name = str(platform_info.get("os", "")).lower()
    machine = str(platform_info.get("machine", "")).lower()
    tier = str(platform_info.get("tier", "")).lower()
    cloud_topology = str(platform_info.get("cloud_topology", "")).lower()
    inbound_reachable = platform_info.get("inbound_reachable")

    if os_name in {"darwin", "macos", "mac"}:
        add(
            findings,
            "PLATFORM_UNSUPPORTED_LOCAL_BINARY",
            "high",
            "Package has no macOS modular-input binary",
            "The audited package contains Linux x86_64 and Windows x86_64 binaries only.",
            "Run the input on Linux/Windows Splunk Enterprise or use a customer-managed heavy forwarder.",
        )
    if os_name == "windows" and not truthy(platform_info.get("windows_executable_verified")):
        add(
            findings,
            "PLATFORM_UNSUPPORTED_LOCAL_BINARY",
            "medium",
            "Windows executable naming needs verification",
            "The package contains windows_x86_64/bin/splunk-connect-for-otlp without a .exe suffix.",
            "Verify modular input execution on Windows before production cutover.",
        )
    if machine and machine not in {"x86_64", "amd64"}:
        add(
            findings,
            "PLATFORM_UNSUPPORTED_LOCAL_BINARY",
            "high",
            "Package has no binary for this architecture",
            f"Detected architecture {machine}; the audited package only includes x86_64 binaries.",
            "Use an x86_64 Splunk runtime tier or request an upstream package for this architecture.",
        )
    if cloud_topology == "classic" and tier in {"search-tier", "search_head", "search-head"}:
        add(
            findings,
            "CLOUD_CLASSIC_REQUIRES_IDM_OR_HF",
            "high",
            "Splunk Cloud Classic search-tier input execution is disallowed",
            "Classic Cloud add-on placement requires IDM or customer-managed heavy forwarder for ingestion add-ons.",
            "Move Splunk Connect for OTLP execution to IDM or a customer-managed heavy forwarder.",
        )
    if cloud_topology == "victoria" and inbound_reachable is False:
        add(
            findings,
            "WRONG_TIER",
            "high",
            "Victoria topology has unresolved inbound reachability",
            "Direct Cloud execution is only acceptable when OTLP senders can reach the listener.",
            "Default to a customer-managed heavy forwarder and validate firewall/LB/TLS reachability.",
        )


def analyze_app(findings: list[Finding], evidence: dict) -> None:
    app = evidence.get("app") if isinstance(evidence.get("app"), dict) else {}
    installed = app.get("installed")
    if installed is False:
        add(
            findings,
            "APP_MISSING",
            "high",
            "Splunk Connect for OTLP is not installed",
            "The app metadata was not visible through Splunk REST.",
            "Install Splunkbase app 8704 through splunk-app-install.",
        )
    version = str(app.get("version", "") or "")
    if version and version != LATEST_VERSION:
        add(
            findings,
            "APP_OUTDATED",
            "medium",
            "Installed app version is not the audited release",
            f"Installed version is {version}; audited release is {LATEST_VERSION}.",
            "Update Splunkbase app 8704 through splunk-app-install.",
        )
    if truthy(app.get("disabled")):
        add(
            findings,
            "APP_DISABLED",
            "high",
            "Splunk Connect for OTLP app is disabled",
            "Splunk reports the app disabled.",
            "Enable the app through supported app management and restart if required.",
        )


def analyze_inputs(findings: list[Finding], evidence: dict) -> None:
    inputs = as_list(evidence.get("inputs"))
    if not inputs:
        add(
            findings,
            "INPUT_MISSING",
            "high",
            "No splunk-connect-for-otlp modular input stanza found",
            "The input endpoint returned no configured stanzas.",
            "Create a reviewed input stanza with ports 4317/4318 and explicit index routing.",
        )
        return
    bound_ports = {port_value(item.get("port")) for item in as_list(evidence.get("bound_ports")) if isinstance(item, dict)}
    for input_item in inputs:
        if not isinstance(input_item, dict):
            continue
        name = str(input_item.get("name", "default"))
        if truthy(input_item.get("disabled")):
            add(
                findings,
                "INPUT_DISABLED",
                "high",
                "OTLP modular input is disabled",
                f"Input {name} is disabled.",
                "Enable the input after validating ports, TLS, and HEC token routing.",
            )
        for field in ("grpc_port", "http_port"):
            port = port_value(input_item.get(field))
            if port is None or port < 1 or port > 65535:
                add(
                    findings,
                    "BAD_PORT",
                    "high",
                    "OTLP input has an invalid port",
                    f"Input {name} field {field} is {input_item.get(field)!r}; port 0 is test-only.",
                    "Reconfigure with non-zero TCP ports, normally 4317 and 4318.",
                )
            elif port in bound_ports:
                add(
                    findings,
                    "PORT_CONFLICT",
                    "high",
                    "OTLP listener port appears to be in use",
                    f"Input {name} field {field} uses port {port}, which evidence marks as already bound.",
                    "Identify the conflicting process and free or change the port before enabling the input.",
                )
        listen_address = str(input_item.get("listen_address", ""))
        if listen_address in {"", "127.0.0.1", "localhost"}:
            add(
                findings,
                "BAD_LISTEN_ADDRESS",
                "medium",
                "OTLP listen address may block remote senders",
                f"Input {name} listen_address is {listen_address or '<blank>'}.",
                "Use 0.0.0.0 or a reachable interface address for remote senders.",
            )
        tls_enabled = truthy(input_item.get("enableSSL"))
        cert = str(input_item.get("serverCert", "") or "")
        key = str(input_item.get("serverKey", "") or "")
        if tls_enabled and (not cert or not key):
            add(
                findings,
                "TLS_FILES_MISSING",
                "high",
                "TLS is enabled without both certificate and key paths",
                f"Input {name} has enableSSL enabled but serverCert/serverKey is incomplete.",
                "Provide readable serverCert and serverKey paths or disable TLS and re-render senders as HTTP.",
            )


def analyze_hec(findings: list[Finding], evidence: dict, expected_index: str) -> None:
    hec = evidence.get("hec") if isinstance(evidence.get("hec"), dict) else {}
    if hec.get("global_disabled") is True or hec.get("enabled") is False:
        add(
            findings,
            "HEC_GLOBAL_DISABLED",
            "high",
            "HEC is globally disabled",
            "Splunk HTTP Event Collector is disabled or unavailable.",
            "Use splunk-hec-service-setup to enable HEC and manage token settings.",
        )
    tokens = [token for token in as_list(hec.get("tokens")) if isinstance(token, dict)]
    if "tokens" in hec and not tokens:
        add(
            findings,
            "HEC_TOKEN_MISSING",
            "high",
            "No HEC token visible to the OTLP app",
            "The HEC token collection returned no token records.",
            "Render a splunk-hec-service-setup handoff for the expected index.",
        )
    for token in tokens:
        token_name = str(token.get("name", "<unknown>"))
        if truthy(token.get("disabled")):
            add(
                findings,
                "HEC_TOKEN_DISABLED",
                "high",
                "HEC token is disabled",
                f"HEC token {token_name} is disabled.",
                "Enable or rotate the token through splunk-hec-service-setup.",
            )
    allowed = token_allowed_indexes(hec)
    if allowed and expected_index not in allowed and "*" not in allowed:
        add(
            findings,
            "HEC_ALLOWED_INDEX_MISSING",
            "high",
            "Expected index is not allowed by the HEC token",
            f"Expected index {expected_index} is absent from allowed indexes {sorted(allowed)}.",
            "Update the HEC token allowed-index list through splunk-hec-service-setup.",
        )


def analyze_senders(findings: list[Finding], evidence: dict, expected_index: str) -> None:
    hec = evidence.get("hec") if isinstance(evidence.get("hec"), dict) else {}
    allowed = token_allowed_indexes(hec)
    for sender in as_list(evidence.get("senders")):
        if not isinstance(sender, dict):
            continue
        name = str(sender.get("name", "<sender>"))
        headers = sender.get("headers") if isinstance(sender.get("headers"), dict) else {}
        auth = str(headers.get("Authorization") or sender.get("authorization") or "")
        if not auth:
            add(
                findings,
                "SENDER_AUTH_HEADER_MISSING",
                "high",
                "Sender is missing the Splunk HEC Authorization header",
                f"Sender {name} does not declare Authorization: Splunk <token>.",
                "Re-render sender assets and load the HEC token from a local token file at runtime.",
            )
        elif not auth.lower().startswith("splunk "):
            add(
                findings,
                "SENDER_AUTH_HEADER_MISSING",
                "high",
                "Sender uses the wrong Authorization header scheme",
                f"Sender {name} does not use the Splunk HEC auth scheme.",
                "Use Authorization: Splunk <HEC_TOKEN>.",
            )
        endpoint = str(sender.get("endpoint", ""))
        parsed = urlparse(endpoint)
        if parsed.scheme in {"http", "https"}:
            if parsed.path and parsed.path not in SIGNAL_PATHS:
                add(
                    findings,
                    "SENDER_HTTP_PATH_INVALID",
                    "high",
                    "Sender uses an invalid OTLP HTTP path",
                    f"Sender {name} endpoint path is {parsed.path}; expected one of {sorted(SIGNAL_PATHS)}.",
                    "Use /v1/logs, /v1/metrics, or /v1/traces for OTLP HTTP senders.",
                )
            if parsed.port and parsed.port != 4318 and sender.get("expected_http_port", 4318) == 4318:
                add(
                    findings,
                    "SENDER_PORT_MISMATCH",
                    "medium",
                    "HTTP sender is not using the configured HTTP port",
                    f"Sender {name} points to HTTP port {parsed.port}; default receiver HTTP port is 4318.",
                    "Re-render sender assets using the receiver's configured http_port.",
                )
        elif endpoint and ":4318" in endpoint and str(sender.get("protocol", "")).lower() == "grpc":
            add(
                findings,
                "SENDER_PORT_MISMATCH",
                "medium",
                "gRPC sender appears to point at the HTTP port",
                f"Sender {name} is marked gRPC but endpoint is {endpoint}.",
                "Use host:4317 for gRPC or switch the sender to OTLP HTTP.",
            )
        resource_attributes = sender.get("resource_attributes")
        resource_index = ""
        if isinstance(resource_attributes, dict):
            resource_index = str(resource_attributes.get("com.splunk.index", "") or "")
        sender_index = str(sender.get("com.splunk.index") or sender.get("index") or resource_index)
        if sender_index and allowed and sender_index not in allowed and "*" not in allowed:
            add(
                findings,
                "SENDER_INDEX_FORBIDDEN",
                "high",
                "Sender routes to an index the HEC token does not allow",
                f"Sender {name} uses com.splunk.index={sender_index}; allowed indexes are {sorted(allowed)}.",
                "Use an allowed com.splunk.index value or update the HEC token allowed-index list.",
            )
        elif not sender_index:
            add(
                findings,
                "SENDER_INDEX_FORBIDDEN",
                "medium",
                "Sender does not explicitly set com.splunk.index",
                f"Sender {name} has no explicit com.splunk.index.",
                f"Set com.splunk.index={expected_index} and smoke-test routing before relying on defaults.",
            )


def analyze_internal_errors(findings: list[Finding], evidence: dict) -> None:
    for err in as_list(evidence.get("internal_errors")):
        if isinstance(err, dict):
            component = str(err.get("component", ""))
            message = str(err.get("message", ""))
        else:
            component = ""
            message = str(err)
        haystack = f"{component} {message}".lower()
        if "bind" in haystack or "address already in use" in haystack:
            add(
                findings,
                "INTERNAL_BIND_FAILURE",
                "high",
                "Recent _internal bind failure",
                message,
                "Check listener port conflicts and restart the modular input after correction.",
            )
        elif "index" in haystack and ("denied" in haystack or "not allowed" in haystack):
            add(
                findings,
                "INTERNAL_INDEX_DENIED",
                "high",
                "Recent _internal index-denied failure",
                message,
                "Align com.splunk.index with the HEC token allowed-index list.",
            )
        elif "auth" in haystack or "unauthorized" in haystack or "forbidden" in haystack:
            add(
                findings,
                "INTERNAL_AUTH_FAILURE",
                "high",
                "Recent _internal auth failure",
                message,
                "Check the sender Authorization header and HEC token visibility.",
            )
        elif any(marker in haystack for marker in ("execprocessor", "modularinputs", APP_NAME)):
            add(
                findings,
                "INTERNAL_EXEC_ERROR",
                "medium",
                "Recent _internal modular input error",
                message,
                "Review the app input stanza, platform binary support, and splunkd logs.",
            )


def build_findings(evidence: dict, package_info: dict[str, object], expected_index: str) -> list[Finding]:
    findings: list[Finding] = []
    analyze_platform(findings, evidence)
    analyze_package(findings, package_info)
    analyze_app(findings, evidence)
    analyze_inputs(findings, evidence)
    analyze_hec(findings, evidence, expected_index)
    analyze_senders(findings, evidence, expected_index)
    analyze_internal_errors(findings, evidence)
    return findings


def fix_plan(findings: list[Finding]) -> list[dict[str, str]]:
    seen: set[str] = set()
    fixes: list[dict[str, str]] = []
    for finding in findings:
        if finding.fix_id in seen:
            continue
        seen.add(finding.fix_id)
        fixes.append(
            {
                "fix_id": finding.fix_id,
                "severity": finding.severity,
                "recommended_action": finding.recommended_action,
            }
        )
    return fixes


def render_markdown(title: str, findings: list[Finding], evidence: dict, package_info: dict[str, object]) -> str:
    lines = [
        f"# {title}",
        "",
        f"App: `{APP_NAME}`",
        f"Audited release: `{LATEST_VERSION}`",
        "",
    ]
    if package_info:
        lines.extend(
            [
                "## Package Inspection",
                "",
                f"- SHA256 matches audited package: `{package_info.get('matches_known_sha256')}`",
                f"- MD5 matches audited package: `{package_info.get('matches_known_md5')}`",
                f"- Missing expected files: `{package_info.get('missing_expected_files')}`",
                "",
            ]
        )
    lines.extend(["## Findings", ""])
    if not findings:
        lines.extend(["No findings were detected from the supplied evidence.", ""])
    for finding in findings:
        lines.extend(
            [
                f"### {finding.fix_id}: {finding.title}",
                "",
                f"- Severity: `{finding.severity}`",
                f"- Detail: {finding.detail}",
                f"- Recommended action: {finding.recommended_action}",
                "",
            ]
        )
    lines.extend(["## Evidence Summary", "", "```json"])
    lines.append(json.dumps(redact_value("", evidence), indent=2, sort_keys=True))
    lines.extend(["```", ""])
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    evidence = load_evidence(args.evidence_file)
    package_info = inspect_package(args.package_file) if args.package_file else {}
    findings = build_findings(evidence, package_info, args.expected_index)
    report = {
        "app": APP_NAME,
        "latest_verified_version": LATEST_VERSION,
        "findings": [asdict(item) for item in findings],
        "finding_count": len(findings),
        "evidence": redact_value("", evidence),
        "package": package_info,
    }
    plan = {
        "app": APP_NAME,
        "fixes": fix_plan(findings),
        "conservative": True,
    }
    if not args.dry_run:
        output_dir = Path(args.output_dir).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "doctor-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (output_dir / "fix-plan.json").write_text(
            json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (output_dir / "doctor-report.md").write_text(
            render_markdown("Splunk Connect for OTLP Doctor Report", findings, evidence, package_info),
            encoding="utf-8",
        )
        (output_dir / "fix-plan.md").write_text(
            render_markdown("Splunk Connect for OTLP Fix Plan", findings, {"fixes": plan["fixes"]}, {}),
            encoding="utf-8",
        )
    if args.json or args.dry_run:
        print(json.dumps({"report": report, "fix_plan": plan}, indent=2, sort_keys=True))
    else:
        print(f"Rendered doctor report and fix plan to {Path(args.output_dir).expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
