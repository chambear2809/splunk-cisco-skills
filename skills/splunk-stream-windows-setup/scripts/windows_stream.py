#!/usr/bin/env python3
"""Investigate, plan, deploy, validate, and roll back Splunk Stream on Windows."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parents[1]
TARGET_SCRIPT = SCRIPT_DIR / "Invoke-SplunkStreamWindows.ps1"
WINRM_SCRIPT = SCRIPT_DIR / "Invoke-SplunkStreamWinRM.ps1"
DEFAULT_PACKAGE = REPO_ROOT / "splunk-ta/splunk-add-on-for-stream-forwarders_816.tgz"
EXPECTED_PACKAGE_SHA256 = "1ac54c5bc6424cabf1b3fe9480f82ccb6348fb74e3af109ea8dbcbf88fa9a068"
REQUIRED_ARCHIVE_PATHS = {
    "Splunk_TA_stream/windows_x86_64/bin/streamfwd.exe",
    "Splunk_TA_stream/windows_x86_64/bin/npcap-1.55-oem.exe",
    "Splunk_TA_stream/default/app.conf",
    "Splunk_TA_stream/default/inputs.conf",
}
PLAN_SCHEMA = 1
INVENTORY_SCHEMA = 1


class UserError(RuntimeError):
    """An actionable operator error."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UserError(f"Could not read {label} JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise UserError(f"{label} must be a JSON object: {path}")
    return value


def run(command: list[str], *, timeout: int = 300, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise UserError(f"Required command is not installed: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise UserError(f"Command timed out after {timeout} seconds: {command[0]}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise UserError(f"Command failed ({command[0]}, exit {result.returncode}): {detail}")
    return result


def parse_target_json(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        candidate = line.strip().lstrip("\ufeff")
        if not candidate.startswith("{"):
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise UserError(f"The Windows target did not return a JSON result. Output: {output[-2000:]}")


def ps_quote(value: str) -> str:
    if "\r" in value or "\n" in value:
        raise UserError("PowerShell argument values must not contain newlines.")
    return "'" + value.replace("'", "''") + "'"


def encoded_powershell(command: str) -> str:
    return base64.b64encode(command.encode("utf-16le")).decode("ascii")


def stable_inventory(inventory: dict[str, Any]) -> dict[str, Any]:
    """Select security- and deployment-relevant fields while excluding timestamps."""
    keys = (
        "schema_version",
        "computer_name",
        "os",
        "is_administrator",
        "splunk",
        "npcap",
        "network_adapters",
        "stream",
        "transport_services",
        "reachability",
    )
    return {key: inventory.get(key) for key in keys}


def inventory_hash(inventory: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json(stable_inventory(inventory)))


def parse_version(value: str) -> tuple[int, ...]:
    found = re.findall(r"\d+", value or "")
    return tuple(int(item) for item in found[:4])


def validate_https_url(value: str, option: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UserError(f"{option} must be an absolute HTTP or HTTPS URL.")
    if parsed.username or parsed.password or parsed.fragment:
        raise UserError(f"{option} must not contain credentials or a fragment.")


def validate_host_port(value: int, option: str) -> None:
    if value < 1 or value > 65535:
        raise UserError(f"{option} must be from 1 to 65535.")


def validate_secret_file(path_value: str, option: str) -> None:
    if not path_value:
        return
    path = Path(path_value).expanduser()
    if not path.is_file():
        raise UserError(f"{option} does not exist: {path}")
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise UserError(f"{option} must not be readable by group or others: chmod 600 {path}")


def verify_vendor_package(path: Path) -> str:
    if not path.is_file():
        raise UserError(f"Stream forwarder package not found: {path}")
    digest = sha256_file(path)
    if digest != EXPECTED_PACKAGE_SHA256:
        raise UserError(
            f"Vendor package SHA-256 mismatch for {path}. Expected {EXPECTED_PACKAGE_SHA256}, got {digest}."
        )
    return digest


def prepare_windows_zip(package: Path, output: Path) -> str:
    """Safely convert the reviewed vendor tgz into a PowerShell-friendly ZIP."""
    verify_vendor_package(package)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    seen: set[str] = set()
    try:
        with tarfile.open(package, mode="r:gz") as archive, zipfile.ZipFile(
            temporary, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as destination:
            for member in archive.getmembers():
                normalized = PurePosixPath(member.name)
                if normalized.is_absolute() or ".." in normalized.parts:
                    raise UserError(f"Unsafe archive path: {member.name}")
                if not normalized.parts or normalized.parts[0] != "Splunk_TA_stream":
                    raise UserError(f"Unexpected archive root: {member.name}")
                name = normalized.as_posix().rstrip("/")
                if member.isdir():
                    if name:
                        destination.writestr(name + "/", b"")
                    continue
                if not member.isfile():
                    raise UserError(f"Unsupported link or special file in vendor archive: {member.name}")
                source = archive.extractfile(member)
                if source is None:
                    raise UserError(f"Could not read archive member: {member.name}")
                if name in seen:
                    raise UserError(f"Duplicate file in vendor archive: {member.name}")
                info = zipfile.ZipInfo(name)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (member.mode & 0xFFFF) << 16
                with destination.open(info, mode="w") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
                seen.add(name)
        missing = sorted(REQUIRED_ARCHIVE_PATHS - seen)
        if missing:
            raise UserError("Vendor archive is missing required Windows content: " + ", ".join(missing))
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return sha256_file(output)


def target_parameters(operation: str, config: dict[str, Any], package_path: str = "") -> list[str]:
    parameters = ["-Operation", operation]
    mapping = (
        ("splunk_home", "-SplunkHome"),
        ("stream_app_url", "-StreamAppUrl"),
        ("bind_ip", "-BindIp"),
        ("port", "-Port"),
        ("ssl_verify", "-SslVerify"),
        ("netflow_ip", "-NetflowIp"),
        ("netflow_port", "-NetflowPort"),
        ("netflow_decoder", "-NetflowDecoder"),
        ("staged_package_sha256", "-ExpectedPackageSha256"),
        ("plan_hash", "-PlanHash"),
        ("transaction_id", "-TransactionId"),
        ("npcap_policy", "-NpcapPolicy"),
    )
    for key, option in mapping:
        value = config.get(key)
        if value is not None and value != "":
            parameters.extend([option, str(value).lower() if isinstance(value, bool) else str(value)])
    if package_path:
        parameters.extend(["-PackagePath", package_path])
    if config.get("accept_mutation"):
        parameters.append("-AcceptMutation")
    return parameters


def powershell_invocation(script_path: str, parameters: list[str]) -> str:
    rendered_tokens = []
    for value in parameters:
        if re.fullmatch(r"-[A-Za-z][A-Za-z0-9]*", value):
            rendered_tokens.append(value)
        else:
            rendered_tokens.append(ps_quote(value))
    rendered = " ".join(rendered_tokens)
    return f"& {ps_quote(script_path)} {rendered}"


def ssh_options(args: argparse.Namespace, *, scp: bool = False) -> list[str]:
    if not args.host or not args.ssh_user:
        raise UserError("--host and --ssh-user are required for SSH.")
    port_option = "-P" if scp else "-p"
    options = [port_option, str(args.ssh_port), "-o", "BatchMode=yes"]
    if args.ssh_key_file:
        key = Path(args.ssh_key_file).expanduser()
        if not key.is_file():
            raise UserError(f"SSH key file not found: {key}")
        options.extend(["-i", str(key)])
    if args.known_hosts_file:
        known_hosts = Path(args.known_hosts_file).expanduser()
        if not known_hosts.exists() and not args.accept_new_host_key:
            raise UserError(f"Known-hosts file not found: {known_hosts}")
        known_hosts.parent.mkdir(parents=True, exist_ok=True)
        options.extend(["-o", f"UserKnownHostsFile={known_hosts}"])
    elif not args.accept_new_host_key:
        raise UserError("SSH requires --known-hosts-file, or explicit --accept-new-host-key for first contact.")
    options.extend(
        ["-o", "StrictHostKeyChecking=accept-new" if args.accept_new_host_key else "StrictHostKeyChecking=yes"]
    )
    return options


def run_local(script: Path, parameters: list[str], package: Path | None, timeout: int) -> dict[str, Any]:
    executable = shutil.which("powershell.exe") or shutil.which("pwsh")
    if not executable:
        raise UserError("Local Windows execution requires powershell.exe or pwsh.")
    command = [executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    local_parameters = [str(package) if value == "__PACKAGE__" and package else value for value in parameters]
    result = run(command + local_parameters, timeout=timeout)
    return parse_target_json(result.stdout)


def run_ssh(args: argparse.Namespace, script: Path, parameters: list[str], package: Path | None, timeout: int) -> dict[str, Any]:
    remote = f"{args.ssh_user}@{args.host}"
    stage_id = "splunk-stream-" + uuid.uuid4().hex
    remote_dir = f"C:/Windows/Temp/{stage_id}"
    remote_script = f"{remote_dir}/{script.name}"
    ssh_base = ["ssh"] + ssh_options(args)
    scp_base = ["scp"] + ssh_options(args, scp=True)
    create = f"New-Item -ItemType Directory -Path {ps_quote(remote_dir)} -Force | Out-Null"
    run(ssh_base + [remote, "powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_powershell(create)], timeout=60)
    try:
        run(scp_base + [str(script), f"{remote}:{remote_script}"], timeout=timeout)
        remote_package = ""
        if package:
            remote_package = f"{remote_dir}/{package.name}"
            run(scp_base + [str(package), f"{remote}:{remote_package}"], timeout=timeout)
        remote_parameters = [remote_package if value == "__PACKAGE__" else value for value in parameters]
        invoke = "$ErrorActionPreference='Stop'; " + powershell_invocation(remote_script, remote_parameters)
        result = run(
            ssh_base + [remote, "powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_powershell(invoke)],
            timeout=timeout,
        )
        return parse_target_json(result.stdout)
    finally:
        cleanup = f"Remove-Item -LiteralPath {ps_quote(remote_dir)} -Recurse -Force -ErrorAction SilentlyContinue"
        run(
            ssh_base + [remote, "powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_powershell(cleanup)],
            timeout=60,
            check=False,
        )


def aws(args: argparse.Namespace, command: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    if not args.region:
        raise UserError("--region is required for AWS Systems Manager.")
    base = ["aws"]
    if args.aws_profile:
        base.extend(["--profile", args.aws_profile])
    return run(base + command + ["--region", args.region], timeout=timeout)


def run_ssm(args: argparse.Namespace, script: Path, parameters: list[str], package: Path | None, timeout: int) -> dict[str, Any]:
    if not args.instance_id or not re.fullmatch(r"i-[0-9a-fA-F]+", args.instance_id):
        raise UserError("--instance-id must be a valid EC2 instance ID for SSM.")
    if not args.staging_s3_uri or not re.fullmatch(r"s3://[^/\s]+(?:/[^\s]*)?", args.staging_s3_uri):
        raise UserError("--staging-s3-uri must be an s3://bucket/prefix URI for SSM staging.")
    stage_id = "splunk-stream/" + uuid.uuid4().hex
    base_uri = args.staging_s3_uri.rstrip("/") + "/" + stage_id
    uploads: list[str] = []
    local_files = [script] + ([package] if package else [])
    try:
        urls: dict[str, str] = {}
        for local_path in local_files:
            object_uri = base_uri + "/" + local_path.name
            aws(args, ["s3", "cp", str(local_path), object_uri, "--only-show-errors"], timeout=timeout)
            uploads.append(object_uri)
            presigned = aws(args, ["s3", "presign", object_uri, "--expires-in", "3600"], timeout=60).stdout.strip()
            if not presigned.startswith("http"):
                raise UserError(f"Could not create a presigned staging URL for {object_uri}.")
            urls[local_path.name] = presigned

        remote_dir = f"C:/Windows/Temp/splunk-stream-{uuid.uuid4().hex}"
        remote_script = remote_dir + "/" + script.name
        download_lines = [
            "$ErrorActionPreference='Stop'",
            f"New-Item -ItemType Directory -Path {ps_quote(remote_dir)} -Force | Out-Null",
            f"Invoke-WebRequest -UseBasicParsing -Uri {ps_quote(urls[script.name])} -OutFile {ps_quote(remote_script)}",
        ]
        remote_package = ""
        if package:
            remote_package = remote_dir + "/" + package.name
            download_lines.append(
                f"Invoke-WebRequest -UseBasicParsing -Uri {ps_quote(urls[package.name])} -OutFile {ps_quote(remote_package)}"
            )
        remote_parameters = [remote_package if value == "__PACKAGE__" else value for value in parameters]
        download_lines.append("try { " + powershell_invocation(remote_script, remote_parameters) + " } finally { "
                              + f"Remove-Item -LiteralPath {ps_quote(remote_dir)} -Recurse -Force -ErrorAction SilentlyContinue }}")
        payload = json.dumps({"commands": ["; ".join(download_lines)]}, separators=(",", ":"))
        sent = aws(
            args,
            [
                "ssm", "send-command", "--instance-ids", args.instance_id,
                "--document-name", "AWS-RunPowerShellScript", "--comment", "Splunk Stream Windows setup",
                "--parameters", payload, "--output", "json",
            ],
            timeout=60,
        )
        response = json.loads(sent.stdout)
        command_id = response["Command"]["CommandId"]
        deadline = time.monotonic() + timeout
        terminal = {"Success", "Cancelled", "TimedOut", "Failed", "Cancelling"}
        invocation: dict[str, Any] = {}
        while time.monotonic() < deadline:
            try:
                polled = aws(
                    args,
                    ["ssm", "get-command-invocation", "--command-id", command_id, "--instance-id", args.instance_id, "--output", "json"],
                    timeout=60,
                )
            except UserError as exc:
                if "InvocationDoesNotExist" in str(exc):
                    time.sleep(1)
                    continue
                raise
            invocation = json.loads(polled.stdout)
            if invocation.get("Status") in terminal:
                break
            time.sleep(2)
        else:
            raise UserError(f"SSM command {command_id} did not complete within {timeout} seconds.")
        if invocation.get("Status") != "Success":
            detail = invocation.get("StandardErrorContent") or invocation.get("StandardOutputContent") or "no output"
            raise UserError(f"SSM command {command_id} ended with {invocation.get('Status')}: {detail}")
        return parse_target_json(invocation.get("StandardOutputContent", ""))
    finally:
        for object_uri in uploads:
            try:
                aws(args, ["s3", "rm", object_uri, "--only-show-errors"], timeout=60)
            except UserError as exc:
                print(f"WARNING: Could not remove temporary SSM staging object {object_uri}: {exc}", file=sys.stderr)


def run_winrm(args: argparse.Namespace, script: Path, parameters: list[str], package: Path | None, timeout: int) -> dict[str, Any]:
    executable = shutil.which("pwsh") or shutil.which("powershell.exe")
    if not executable:
        raise UserError("WinRM execution requires PowerShell (pwsh or powershell.exe) on the controller.")
    if not args.computer_name:
        raise UserError("--computer-name is required for WinRM.")
    if args.winrm_authentication == "Basic" and not args.winrm_use_ssl:
        raise UserError("WinRM Basic authentication is permitted only with --winrm-use-ssl.")
    validate_secret_file(args.winrm_password_file, "--winrm-password-file")
    if bool(args.winrm_user) != bool(args.winrm_password_file):
        raise UserError("--winrm-user and --winrm-password-file must be supplied together.")
    command = [
        executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(WINRM_SCRIPT),
        "-ComputerName", args.computer_name, "-TargetScript", str(script),
        "-OperationArgumentsJson", json.dumps(parameters, separators=(",", ":")),
        "-Authentication", args.winrm_authentication,
    ]
    if package:
        command.extend(["-PackagePath", str(package)])
    if args.winrm_use_ssl:
        command.append("-UseSSL")
    if args.winrm_port:
        command.extend(["-Port", str(args.winrm_port)])
    if args.winrm_user:
        command.extend(["-CredentialUser", args.winrm_user, "-CredentialPasswordFile", args.winrm_password_file])
    result = run(command, timeout=timeout)
    return parse_target_json(result.stdout)


def execute_script(
    args: argparse.Namespace, script: Path, parameters: list[str], package: Path | None = None
) -> dict[str, Any]:
    if not script.is_file():
        raise UserError(f"PowerShell payload not found: {script}")
    timeout = args.timeout
    if args.transport == "local":
        return run_local(script, parameters, package, timeout)
    if args.transport == "ssh":
        return run_ssh(args, script, parameters, package, timeout)
    if args.transport == "ssm":
        return run_ssm(args, script, parameters, package, timeout)
    if args.transport == "winrm":
        return run_winrm(args, script, parameters, package, timeout)
    raise UserError(f"Unsupported execution transport: {args.transport}")


def execute_target(
    args: argparse.Namespace, operation: str, config: dict[str, Any], package: Path | None = None
) -> dict[str, Any]:
    parameters = target_parameters(operation, config, "__PACKAGE__" if package else "")
    return execute_script(args, TARGET_SCRIPT, parameters, package)


def make_plan(args: argparse.Namespace, inventory: dict[str, Any], package: Path, staged_zip: Path) -> dict[str, Any]:
    if inventory.get("schema_version") != INVENTORY_SCHEMA:
        raise UserError(f"Unsupported inventory schema: {inventory.get('schema_version')}")
    validate_https_url(args.stream_app_url, "--stream-app-url")
    validate_host_port(args.port, "--port")
    if args.netflow_port:
        validate_host_port(args.netflow_port, "--netflow-port")
        if not args.netflow_ip:
            raise UserError("--netflow-ip is required when --netflow-port is set.")
    if args.bind_ip != "auto" and not re.fullmatch(r"[0-9A-Fa-f:.]+", args.bind_ip):
        raise UserError("--bind-ip must be 'auto' or a literal IPv4/IPv6 address.")

    vendor_hash = verify_vendor_package(package)
    staged_hash = prepare_windows_zip(package, staged_zip)
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    splunk = inventory.get("splunk") or {}
    os_info = inventory.get("os") or {}
    service = splunk.get("service") or {}
    runtime = splunk.get("runtime_type") or "absent"
    version = str(splunk.get("version") or "")

    if not inventory.get("is_administrator"):
        blockers.append({"code": "administrator_required", "message": "The execution identity is not a local administrator."})
    if not os_info.get("is_server"):
        blockers.append({"code": "windows_server_required", "message": "Splunk Stream is supported on Windows Server, not this Windows client OS."})
    if "64" not in str(os_info.get("architecture") or ""):
        blockers.append({"code": "x64_required", "message": "The reviewed Stream package contains Windows x86-64 binaries only."})
    if runtime == "absent":
        blockers.append(
            {
                "code": "splunk_runtime_required",
                "message": "Install a Windows x64 Universal Forwarder with splunk-universal-forwarder-setup, then investigate again.",
            }
        )
    elif runtime == "enterprise" and parse_version(version) >= (10, 4):
        blockers.append(
            {
                "code": "enterprise_10_4_service_identity_conflict",
                "message": "Windows Splunk Enterprise 10.4+ cannot use the service identities required by Splunk Stream. Use a LocalSystem Universal Forwarder capture tier.",
            }
        )
    if runtime != "absent" and not service.get("stream_account_supported"):
        blockers.append(
            {
                "code": "unsupported_service_account",
                "message": f"Splunk service account {service.get('start_name') or 'unknown'} is neither LocalSystem nor a verified direct local Administrator.",
            }
        )
    reachability = inventory.get("reachability") or {}
    if reachability.get("tested") and not reachability.get("tcp_succeeded"):
        blockers.append(
            {
                "code": "stream_app_unreachable",
                "message": "The Windows host cannot reach the supplied Splunk Stream app endpoint. Fix DNS, routing, firewall, or TLS reachability first.",
            }
        )
    adapters = [item for item in (inventory.get("network_adapters") or []) if item.get("status") == "Up"]
    if not adapters:
        blockers.append({"code": "no_active_adapter", "message": "No active network adapter is available for packet capture."})
    if args.ssl_verify == "false":
        warnings.append({"code": "tls_verification_disabled", "message": "TLS verification is disabled; use only for a reviewed temporary certificate exception."})
    if (inventory.get("npcap") or {}).get("installed") and args.npcap_policy == "upgrade":
        warnings.append({"code": "shared_driver_change", "message": "Npcap may be shared. Confirm dependent products before upgrading it."})

    plan: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA,
        "workflow": "splunk-stream-windows-setup",
        "status": "ready" if not blockers else "blocked",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "inventory_file": str(Path(args.inventory_file).expanduser().resolve()),
        "inventory_hash": inventory_hash(inventory),
        "target": {
            "computer_name": inventory.get("computer_name"),
            "runtime_type": runtime,
            "splunk_version": version,
            "service_name": service.get("name"),
            "service_account": service.get("start_name"),
        },
        "transport": args.transport,
        "package": {
            "vendor_archive": str(package.resolve()),
            "vendor_sha256": vendor_hash,
            "staged_zip": str(staged_zip.resolve()),
            "staged_package_sha256": staged_hash,
            "version": "8.1.6",
        },
        "configuration": {
            "splunk_home": splunk.get("home") or "",
            "stream_app_url": args.stream_app_url.rstrip("/") + "/",
            "bind_ip": args.bind_ip,
            "port": args.port,
            "ssl_verify": args.ssl_verify,
            "netflow_ip": args.netflow_ip,
            "netflow_port": args.netflow_port,
            "netflow_decoder": args.netflow_decoder,
            "npcap_policy": args.npcap_policy,
        },
        "actions": [
            "Revalidate the investigation fingerprint immediately before mutation.",
            "Verify the staged Stream TA package hash and Windows x64 payload.",
            "Install bundled Npcap only according to the reviewed Npcap policy.",
            "Stop Splunk, transactionally replace Splunk_TA_stream, preserve local configuration, and restart Splunk.",
            "Validate the driver, service, streamfwd process, effective configuration, endpoint reachability, and logs.",
            "Run parent splunk-stream-setup completion validation for indexed data and shipped dashboards.",
        ],
        "blockers": blockers,
        "warnings": warnings,
        "transaction_id": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:12],
        "prerequisite_handoffs": {
            "missing_runtime": "splunk-universal-forwarder-setup --target-os windows --target-arch x64",
            "fleet_distribution": "splunk-agent-management-setup or splunk-deployment-server-setup",
            "search_and_index_tiers": "splunk-stream-setup",
        },
    }
    plan["plan_hash"] = sha256_bytes(canonical_json(plan))
    return plan


def verify_plan(plan: dict[str, Any]) -> None:
    supplied = plan.get("plan_hash")
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    calculated = sha256_bytes(canonical_json(unsigned))
    if not supplied or supplied != calculated:
        raise UserError(f"Plan hash is invalid. Expected calculated hash {calculated}.")
    if plan.get("schema_version") != PLAN_SCHEMA or plan.get("workflow") != "splunk-stream-windows-setup":
        raise UserError("The plan does not belong to the supported Splunk Stream Windows workflow.")


def config_from_plan(plan: dict[str, Any], *, accept_mutation: bool = False) -> dict[str, Any]:
    config = dict(plan.get("configuration") or {})
    config.update(
        {
            "staged_package_sha256": (plan.get("package") or {}).get("staged_package_sha256"),
            "plan_hash": plan.get("plan_hash"),
            "transaction_id": plan.get("transaction_id"),
            "accept_mutation": accept_mutation,
        }
    )
    return config


def cmd_investigate(args: argparse.Namespace) -> int:
    config = {"splunk_home": args.splunk_home, "stream_app_url": args.stream_app_url}
    if args.stream_app_url:
        validate_https_url(args.stream_app_url, "--stream-app-url")
    inventory = execute_target(args, "Investigate", config)
    if inventory.get("schema_version") != INVENTORY_SCHEMA:
        raise UserError(f"Unexpected inventory schema returned by target: {inventory.get('schema_version')}")
    inventory["inventory_hash"] = inventory_hash(inventory)
    output = Path(args.output_dir).expanduser().resolve() / "inventory.json"
    write_json(output, inventory)
    print(json.dumps({"status": "investigated", "inventory_file": str(output), "inventory_hash": inventory["inventory_hash"], "inventory": inventory}, indent=2, sort_keys=True))
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    inventory_path = Path(args.inventory_file).expanduser().resolve()
    inventory = read_json(inventory_path, "inventory")
    output_dir = Path(args.output_dir).expanduser().resolve()
    package = Path(args.package).expanduser().resolve()
    staged_zip = output_dir / "staging/Splunk_TA_stream-8.1.6-windows-x64.zip"
    plan = make_plan(args, inventory, package, staged_zip)
    plan_path = output_dir / "plan.json"
    write_json(plan_path, plan)
    print(json.dumps({"status": plan["status"], "plan_file": str(plan_path), "plan_hash": plan["plan_hash"], "blockers": plan["blockers"], "warnings": plan["warnings"]}, indent=2, sort_keys=True))
    return 0 if plan["status"] == "ready" else 2


def cmd_bootstrap_uf(args: argparse.Namespace) -> int:
    if not args.accept_forwarder_mutation:
        raise UserError("Universal Forwarder prerequisite apply requires --accept-forwarder-mutation.")
    inventory_path = Path(args.inventory_file).expanduser().resolve()
    prior = read_json(inventory_path, "inventory")
    if (prior.get("splunk") or {}).get("runtime_type") != "absent":
        raise UserError("The reviewed inventory does not show a missing Splunk runtime; do not bootstrap over an existing installation.")
    current = execute_target(args, "Investigate", {"stream_app_url": args.stream_app_url})
    if inventory_hash(current) != inventory_hash(prior):
        raise UserError("Target inventory drifted before the Universal Forwarder prerequisite. Investigate again.")

    render_dir = Path(args.uf_render_dir).expanduser().resolve()
    metadata = read_json(render_dir / "metadata.json", "Universal Forwarder render metadata")
    if metadata.get("workflow") != "splunk-universal-forwarder-setup":
        raise UserError("The prerequisite metadata does not belong to splunk-universal-forwarder-setup.")
    expected = {
        "target_os": "windows",
        "target_arch": "x64",
        "package_type": "msi",
        "service_user": "LocalSystem",
        "v1_apply": "render-only",
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise UserError(f"Universal Forwarder metadata {key} must be {value!r}, found {metadata.get(key)!r}.")
    script = render_dir / "install-universal-forwarder.ps1"
    package = Path(args.uf_msi).expanduser().resolve()
    if not package.is_file() or package.suffix.lower() != ".msi":
        raise UserError(f"Reviewed Universal Forwarder MSI not found: {package}")
    expected_hash = str(metadata.get("package_sha256") or "")
    actual_hash = sha256_file(package)
    if not expected_hash or actual_hash != expected_hash:
        raise UserError(f"Universal Forwarder MSI hash does not match rendered metadata. Expected {expected_hash or '<missing>'}, got {actual_hash}.")

    result = execute_script(args, script, ["-PackagePath", "__PACKAGE__"], package)
    after = execute_target(args, "Investigate", {"stream_app_url": args.stream_app_url})
    if (after.get("splunk") or {}).get("runtime_type") != "universal-forwarder":
        raise UserError("Universal Forwarder prerequisite script returned, but reinvestigation did not find the runtime.")
    output = Path(args.output_dir).expanduser().resolve() / "inventory.json"
    after["inventory_hash"] = inventory_hash(after)
    write_json(output, after)
    print(json.dumps({"status": "universal-forwarder-ready", "prerequisite": result, "inventory_file": str(output), "inventory_hash": after["inventory_hash"], "inventory": after}, indent=2, sort_keys=True))
    return 0


def load_apply_plan(args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    plan_path = Path(args.plan_file).expanduser().resolve()
    plan = read_json(plan_path, "plan")
    verify_plan(plan)
    if plan.get("status") != "ready":
        messages = "; ".join(item.get("message", "") for item in plan.get("blockers", []))
        raise UserError(f"Plan is blocked and cannot be applied: {messages}")
    package = Path((plan.get("package") or {}).get("staged_zip", "")).expanduser().resolve()
    if not package.is_file():
        raise UserError(f"Staged Windows package not found: {package}")
    actual = sha256_file(package)
    expected = (plan.get("package") or {}).get("staged_package_sha256")
    if actual != expected:
        raise UserError(f"Staged Windows package hash changed. Expected {expected}, got {actual}.")
    if args.transport and args.transport != plan.get("transport"):
        raise UserError(f"Apply transport {args.transport} does not match reviewed plan transport {plan.get('transport')}.")
    args.transport = plan.get("transport")
    return plan, package


def cmd_apply(args: argparse.Namespace) -> int:
    if not args.accept_stream_mutation:
        raise UserError("Apply requires --accept-stream-mutation after plan review.")
    plan, package = load_apply_plan(args)
    config = config_from_plan(plan)
    current = execute_target(args, "Investigate", config)
    current_hash = inventory_hash(current)
    if current_hash != plan.get("inventory_hash"):
        raise UserError(
            "Target inventory drifted after planning. "
            f"Planned {plan.get('inventory_hash')}, current {current_hash}. Re-run investigate and plan."
        )
    config["accept_mutation"] = True
    result = execute_target(args, "Apply", config, package)
    if not result.get("success"):
        raise UserError("Windows apply returned an unsuccessful validation result.")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    plan = read_json(Path(args.plan_file).expanduser().resolve(), "plan")
    verify_plan(plan)
    args.transport = args.transport or plan.get("transport")
    config = config_from_plan(plan)
    result = execute_target(args, "Validate", config)
    if not result.get("success"):
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    if args.completion:
        parent = REPO_ROOT / "skills/splunk-stream-setup/scripts/validate.sh"
        completed = run(["bash", str(parent), "--completion"], timeout=args.timeout, check=False)
        if completed.stdout:
            print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, file=sys.stderr, end="")
        if completed.returncode != 0:
            print(json.dumps(result, indent=2, sort_keys=True))
            return completed.returncode
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    if not args.accept_stream_rollback:
        raise UserError("Rollback requires --accept-stream-rollback after reviewing the transaction journal.")
    plan = read_json(Path(args.plan_file).expanduser().resolve(), "plan")
    verify_plan(plan)
    args.transport = args.transport or plan.get("transport")
    config = config_from_plan(plan, accept_mutation=True)
    result = execute_target(args, "Rollback", config)
    if not result.get("success"):
        raise UserError("Windows rollback did not restore a validated prior state.")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def add_transport_arguments(parser: argparse.ArgumentParser, *, optional: bool = False) -> None:
    parser.add_argument("--transport", choices=("local", "ssh", "winrm", "ssm"), required=not optional)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--host", default="", help="Windows SSH host or IP")
    parser.add_argument("--ssh-user", default="")
    parser.add_argument("--ssh-port", type=int, default=22)
    parser.add_argument("--ssh-key-file", default="")
    parser.add_argument("--known-hosts-file", default="")
    parser.add_argument("--accept-new-host-key", action="store_true")
    parser.add_argument("--computer-name", default="", help="WinRM computer name")
    parser.add_argument("--winrm-use-ssl", action="store_true")
    parser.add_argument("--winrm-port", type=int, default=0)
    parser.add_argument("--winrm-authentication", choices=("Default", "Kerberos", "Negotiate", "Basic", "CredSSP"), default="Default")
    parser.add_argument("--winrm-user", default="")
    parser.add_argument("--winrm-password-file", default="")
    parser.add_argument("--instance-id", default="")
    parser.add_argument("--region", default="")
    parser.add_argument("--aws-profile", default="")
    parser.add_argument("--staging-s3-uri", default="")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Investigation-first Splunk Stream 8.1.6 deployment for Windows Server.",
        epilog=(
            "Actions: investigate, plan (render-only), bootstrap-uf, apply, validate, "
            "and rollback. Review the plan before any mutation."
        ),
    )
    sub = root.add_subparsers(dest="command", required=True)

    investigate = sub.add_parser("investigate", help="Collect a non-mutating Windows/Splunk/Npcap/transport inventory")
    add_transport_arguments(investigate)
    investigate.add_argument("--splunk-home", default="")
    investigate.add_argument("--stream-app-url", default="")
    investigate.add_argument("--output-dir", default="rendered/splunk-stream-windows")
    investigate.set_defaults(func=cmd_investigate)

    plan = sub.add_parser("plan", help="Generate a drift-bound, reviewable installation plan")
    plan.add_argument("--inventory-file", required=True)
    plan.add_argument("--output-dir", default="rendered/splunk-stream-windows")
    plan.add_argument("--package", default=str(DEFAULT_PACKAGE))
    plan.add_argument("--transport", choices=("local", "ssh", "winrm", "ssm"), required=True)
    plan.add_argument("--stream-app-url", required=True)
    plan.add_argument("--bind-ip", default="auto")
    plan.add_argument("--port", type=int, default=8889)
    plan.add_argument("--ssl-verify", choices=("true", "false"), default="true")
    plan.add_argument("--netflow-ip", default="")
    plan.add_argument("--netflow-port", type=int, default=0)
    plan.add_argument("--netflow-decoder", choices=("netflow", "sflow"), default="netflow")
    plan.add_argument("--npcap-policy", choices=("install-if-missing", "preserve", "upgrade"), default="install-if-missing")
    plan.set_defaults(func=cmd_plan)

    prerequisite = sub.add_parser("bootstrap-uf", help="Execute a reviewed Windows Universal Forwarder child-skill handoff")
    add_transport_arguments(prerequisite)
    prerequisite.add_argument("--inventory-file", required=True)
    prerequisite.add_argument("--uf-render-dir", required=True)
    prerequisite.add_argument("--uf-msi", required=True)
    prerequisite.add_argument("--stream-app-url", default="")
    prerequisite.add_argument("--output-dir", default="rendered/splunk-stream-windows")
    prerequisite.add_argument("--accept-forwarder-mutation", action="store_true")
    prerequisite.set_defaults(func=cmd_bootstrap_uf)

    apply = sub.add_parser("apply", help="Apply an unchanged reviewed plan")
    add_transport_arguments(apply, optional=True)
    apply.add_argument("--plan-file", required=True)
    apply.add_argument("--accept-stream-mutation", action="store_true")
    apply.set_defaults(func=cmd_apply)

    validate = sub.add_parser("validate", help="Validate Windows capture and optionally the end-to-end completion gate")
    add_transport_arguments(validate, optional=True)
    validate.add_argument("--plan-file", required=True)
    validate.add_argument("--completion", action="store_true")
    validate.set_defaults(func=cmd_validate)

    rollback = sub.add_parser("rollback", help="Restore the transaction's prior Splunk_TA_stream directory")
    add_transport_arguments(rollback, optional=True)
    rollback.add_argument("--plan-file", required=True)
    rollback.add_argument("--accept-stream-rollback", action="store_true")
    rollback.set_defaults(func=cmd_rollback)
    return root


def main() -> int:
    args = parser().parse_args()
    if hasattr(args, "timeout") and args.timeout < 30:
        raise UserError("--timeout must be at least 30 seconds.")
    if hasattr(args, "ssh_port"):
        validate_host_port(args.ssh_port, "--ssh-port")
    if getattr(args, "winrm_port", 0):
        validate_host_port(args.winrm_port, "--winrm-port")
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except UserError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
