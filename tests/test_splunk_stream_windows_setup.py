#!/usr/bin/env python3
"""Regression coverage for the Splunk Stream Windows child skill."""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path
from unittest import mock

import pytest

from tests.regression_helpers import REPO_ROOT


SCRIPT = REPO_ROOT / "skills/splunk-stream-windows-setup/scripts/windows_stream.py"
TARGET_PS = REPO_ROOT / "skills/splunk-stream-windows-setup/scripts/Invoke-SplunkStreamWindows.ps1"
WINRM_PS = REPO_ROOT / "skills/splunk-stream-windows-setup/scripts/Invoke-SplunkStreamWinRM.ps1"

SPEC = importlib.util.spec_from_file_location("splunk_stream_windows", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def inventory(*, runtime: str = "universal-forwarder", version: str = "10.4.0", account_ok: bool = True) -> dict:
    service_name = "SplunkForwarder" if runtime == "universal-forwarder" else "Splunkd"
    if runtime == "absent":
        service_name = ""
    return {
        "schema_version": 1,
        "checked_at": "2026-09-10T12:00:00Z",
        "computer_name": "WIN-CAPTURE-01",
        "execution_identity": "NT AUTHORITY\\SYSTEM",
        "is_administrator": True,
        "os": {
            "caption": "Microsoft Windows Server 2022 Datacenter",
            "version": "10.0.20348",
            "build_number": "20348",
            "architecture": "64-bit",
            "product_type": 3,
            "is_server": True,
            "manufacturer": "Amazon EC2",
            "model": "t3.large",
        },
        "splunk": {
            "home": "" if runtime == "absent" else r"C:\Program Files\SplunkUniversalForwarder",
            "runtime_type": runtime,
            "version": "" if runtime == "absent" else version,
            "executable_present": runtime != "absent",
            "service": {
                "name": service_name,
                "state": "Absent" if runtime == "absent" else "Running",
                "start_mode": "Auto",
                "start_name": "LocalSystem" if account_ok else "NT SERVICE\\splunkforwarder",
                "local_system": account_ok,
                "direct_local_administrator": False,
                "stream_account_supported": account_ok,
            },
        },
        "npcap": {
            "installed": False,
            "service_state": "Absent",
            "version": "",
            "winpcap_compatible": False,
            "watchdog_task_present": False,
        },
        "network_adapters": [
            {
                "name": "Ethernet",
                "description": "ENA",
                "interface_index": 4,
                "status": "Up",
                "mac_address": "00-11-22-33-44-55",
                "addresses": ["10.0.0.10"],
            }
        ],
        "stream": {
            "app_path": "",
            "installed": False,
            "version": "",
            "process_running": False,
            "configuration": {"inputs": {}, "streamfwd": {}},
        },
        "transport_services": {"openssh": "Running", "winrm": "Running", "ssm": "Running"},
        "reachability": {
            "tested": True,
            "host": "splunk.example.com",
            "port": 8000,
            "tcp_succeeded": True,
            "http_succeeded": True,
            "http_status": 200,
            "error": "",
        },
    }


def plan_args(tmp_path: Path, transport: str = "ssm") -> argparse.Namespace:
    return argparse.Namespace(
        inventory_file=str(tmp_path / "inventory.json"),
        stream_app_url="https://splunk.example.com:8000/en-US/custom/splunk_app_stream",
        bind_ip="auto",
        port=8889,
        ssl_verify="true",
        netflow_ip="",
        netflow_port=0,
        netflow_decoder="netflow",
        npcap_policy="install-if-missing",
        transport=transport,
    )


def make_plan(tmp_path: Path, state: dict) -> dict:
    args = plan_args(tmp_path)
    package = tmp_path / "stream.tgz"
    staged = tmp_path / "stream.zip"
    package.write_bytes(b"vendor")
    with mock.patch.object(MODULE, "verify_vendor_package", return_value="a" * 64), mock.patch.object(
        MODULE, "prepare_windows_zip", return_value="b" * 64
    ):
        return MODULE.make_plan(args, state, package, staged)


def test_help_exposes_investigation_before_apply() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0
    assert "investigate" in result.stdout
    assert "plan" in result.stdout
    assert "apply" in result.stdout
    assert result.stdout.index("investigate") < result.stdout.index("apply")


def test_plan_parser_does_not_require_a_transport_execution_timeout(tmp_path: Path) -> None:
    args = MODULE.parser().parse_args(
        [
            "plan",
            "--inventory-file",
            str(tmp_path / "inventory.json"),
            "--transport",
            "ssm",
            "--stream-app-url",
            "https://splunk.example.com:8000/en-US/custom/splunk_app_stream",
        ]
    )
    assert not hasattr(args, "timeout")


def test_ready_plan_is_hash_bound_and_routes_parent_children(tmp_path: Path) -> None:
    plan = make_plan(tmp_path, inventory())
    assert plan["status"] == "ready"
    assert plan["transport"] == "ssm"
    assert plan["target"]["runtime_type"] == "universal-forwarder"
    assert plan["prerequisite_handoffs"]["missing_runtime"].startswith("splunk-universal-forwarder-setup")
    assert plan["prerequisite_handoffs"]["search_and_index_tiers"] == "splunk-stream-setup"
    MODULE.verify_plan(plan)

    plan["configuration"]["ssl_verify"] = "false"
    with pytest.raises(MODULE.UserError, match="Plan hash is invalid"):
        MODULE.verify_plan(plan)


def test_plan_blocks_missing_runtime_and_names_uf_handoff(tmp_path: Path) -> None:
    plan = make_plan(tmp_path, inventory(runtime="absent", version=""))
    assert plan["status"] == "blocked"
    blockers = {item["code"]: item["message"] for item in plan["blockers"]}
    assert "splunk_runtime_required" in blockers
    assert "splunk-universal-forwarder-setup" in blockers["splunk_runtime_required"]


def test_plan_blocks_windows_enterprise_104_service_conflict(tmp_path: Path) -> None:
    plan = make_plan(tmp_path, inventory(runtime="enterprise", version="10.4.0.123"))
    assert plan["status"] == "blocked"
    assert "enterprise_10_4_service_identity_conflict" in {item["code"] for item in plan["blockers"]}


def test_plan_blocks_unverified_service_account_and_unreachable_endpoint(tmp_path: Path) -> None:
    state = inventory(account_ok=False)
    state["reachability"]["tcp_succeeded"] = False
    plan = make_plan(tmp_path, state)
    codes = {item["code"] for item in plan["blockers"]}
    assert {"unsupported_service_account", "stream_app_unreachable"} <= codes


def test_inventory_fingerprint_ignores_timestamp_but_detects_runtime_drift() -> None:
    first = inventory()
    second = json.loads(json.dumps(first))
    second["checked_at"] = "2026-09-10T13:00:00Z"
    assert MODULE.inventory_hash(first) == MODULE.inventory_hash(second)
    second["splunk"]["service"]["start_name"] = "NT SERVICE\\splunkforwarder"
    assert MODULE.inventory_hash(first) != MODULE.inventory_hash(second)


def test_archive_conversion_rejects_traversal_and_emits_required_windows_payload(tmp_path: Path) -> None:
    bad = tmp_path / "bad.tgz"
    with tarfile.open(bad, "w:gz") as archive:
        member = tarfile.TarInfo("Splunk_TA_stream/../../escape")
        member.size = 1
        archive.addfile(member, io.BytesIO(b"x"))
    with mock.patch.object(MODULE, "EXPECTED_PACKAGE_SHA256", MODULE.sha256_file(bad)):
        with pytest.raises(MODULE.UserError, match="Unsafe archive path"):
            MODULE.prepare_windows_zip(bad, tmp_path / "bad.zip")

    good = tmp_path / "good.tgz"
    with tarfile.open(good, "w:gz") as archive:
        for name in sorted(MODULE.REQUIRED_ARCHIVE_PATHS):
            payload = b"version = 8.1.6\n" if name.endswith("app.conf") else b"payload"
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    destination = tmp_path / "good.zip"
    with mock.patch.object(MODULE, "EXPECTED_PACKAGE_SHA256", MODULE.sha256_file(good)):
        digest = MODULE.prepare_windows_zip(good, destination)
    assert digest == MODULE.sha256_file(destination)
    with __import__("zipfile").ZipFile(destination) as archive:
        assert MODULE.REQUIRED_ARCHIVE_PATHS <= set(archive.namelist())


def test_powershell_remote_invocation_keeps_named_parameters_and_quotes_values() -> None:
    rendered = MODULE.powershell_invocation(
        r"C:\Windows\Temp\Invoke.ps1",
        ["-Operation", "Apply", "-StreamAppUrl", "https://example.test/a'b", "-AcceptMutation"],
    )
    assert "-Operation 'Apply'" in rendered
    assert "-AcceptMutation" in rendered
    assert "'https://example.test/a''b'" in rendered
    assert "'-Operation'" not in rendered


def test_windows_scripts_contain_transaction_transport_and_driver_guards() -> None:
    target = TARGET_PS.read_text(encoding="utf-8")
    winrm = WINRM_PS.read_text(encoding="utf-8")
    controller = SCRIPT.read_text(encoding="utf-8")

    for required in (
        "Assert-Administrator",
        "ExpectedPackageSha256",
        "Enterprise 10.4+",
        "Start-Process -FilePath $Installer",
        "npcap_installed_by_transaction",
        "Set-ConfStanza",
        "compensation-failed",
        "streamfwd_process_running",
    ):
        assert required in target
    assert "Copy-Item -LiteralPath $PackagePath" in winrm
    assert "Basic authentication requires -UseSSL" in winrm
    assert "StrictHostKeyChecking=yes" in controller
    assert "AWS-RunPowerShellScript" in controller
    assert '"s3", "rm"' in controller


def test_parent_routes_windows_capture_work_to_child() -> None:
    parent = (REPO_ROOT / "skills/splunk-stream-setup/SKILL.md").read_text(encoding="utf-8")
    child = (REPO_ROOT / "skills/splunk-stream-windows-setup/SKILL.md").read_text(encoding="utf-8")
    assert "splunk-stream-windows-setup" in parent
    assert "investigation" in parent.lower()
    assert "splunk-universal-forwarder-setup" in child
    assert "bootstrap-uf" in child
    assert "splunk-agent-management-setup" in child
    assert "splunk-deployment-server-setup" in child
    assert "--completion" in child
