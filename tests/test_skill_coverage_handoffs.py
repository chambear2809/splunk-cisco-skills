#!/usr/bin/env python3
"""Coverage-gap handoff tests for render-only skill planners."""

from __future__ import annotations

import json
import subprocess
import sys

from tests.regression_helpers import REPO_ROOT


def run_python_script(rel_path: str, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / rel_path), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_enterprise_host_rolling_plan_serializes_clustered_indexer_waves() -> None:
    result = run_python_script(
        "skills/splunk-enterprise-host-setup/scripts/rolling_upgrade_plan.py",
        "--role",
        "indexer-peer",
        "--hosts",
        "idx01.example.com,idx02.example.com",
        "--cluster-manager-host",
        "cm01.example.com",
        "--cluster-manager-uri",
        "https://cm01.example.com:8089",
        "--admin-password-file",
        "/tmp/splunk_admin_password",
        "--json",
    )

    payload = json.loads(result.stdout)
    assert payload["workflow"] == "splunk-enterprise-host-rolling-upgrade"
    assert [wave["hosts"] for wave in payload["waves"]] == [
        ["idx01.example.com"],
        ["idx02.example.com"],
    ]
    first_upgrade = payload["waves"][0]["upgrade"][0]
    assert "SPLUNK_SSH_HOST=idx01.example.com" in first_upgrade
    assert "--host-bootstrap-role indexer-peer" in first_upgrade
    assert any("cluster-status" in gate for gate in payload["waves"][0]["postcheck"])


def test_ai_assistant_cloud_onboarding_plan_keeps_cloud_ui_gate_explicit() -> None:
    result = run_python_script(
        "skills/splunk-ai-assistant-setup/scripts/cloud_onboarding_plan.py",
        "--platform",
        "cloud",
        "--stack",
        "example-stack",
        "--json",
    )

    payload = json.loads(result.stdout)
    assert payload["workflow"] == "splunk-ai-assistant-cloud-onboarding"
    assert payload["platform"] == "cloud"
    assert any(step["automation"] == "manual-gate" for step in payload["steps"])
    assert any("app ID 7245" in detail for step in payload["steps"] for detail in step.get("details", []))


def test_enhanced_netflow_setup_renders_stream_receiver_handoff_json() -> None:
    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "skills/cisco-catalyst-enhanced-netflow-setup/scripts/setup.sh"),
            "--stream-receiver-plan",
            "--forwarder-ip",
            "10.0.10.25",
            "--splunk-web-url",
            "https://splunk.example.com:8000",
            "--netflow-port",
            "9995",
            "--json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["workflow"] == "cisco-catalyst-enhanced-netflow-stream-receiver-handoff"
    assert payload["receiver"]["forwarder_ip"] == "10.0.10.25"
    assert payload["receiver"]["netflow_port"] == "9995"
    commands = "\n".join(step["command"] for step in payload["steps"])
    assert "skills/splunk-stream-setup/scripts/setup.sh" in commands
    assert "--netflow-port 9995" in commands
