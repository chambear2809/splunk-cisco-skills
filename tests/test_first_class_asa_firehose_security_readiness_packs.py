#!/usr/bin/env python3
"""Render/validate coverage for first-class ASA, Firehose, and security app skills."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.regression_helpers import REPO_ROOT


CORE_RENDERED_FILES = {
    "metadata.json",
    "profile-plan.md",
    "handoffs.md",
    "install-commands.sh",
    "validation-searches.spl",
    "readiness-evidence-template.json",
}

SKILL_CASES = {
    "cisco-asa-ta-setup": {
        "required_flags": [
            "--render",
            "--json",
            "--output-dir",
            "--index",
            "--sourcetype",
            "--syslog-owner",
            "--sc4s-vendor-product",
            "--include-ftd",
        ],
        "render_args": ["--include-ftd", "--index", "cisco_asa_test"],
        "required_files": ["syslog-receiver-checklist.md"],
        "expected_metadata": {"include_ftd": True},
    },
    "splunk-amazon-kinesis-firehose-setup": {
        "required_flags": [
            "--render",
            "--json",
            "--output-dir",
            "--index",
            "--hec-token-name",
            "--source-profile",
            "--s3-backup-bucket",
            "--buffer-size-mb",
            "--buffer-interval-sec",
            "--use-ack",
        ],
        "render_args": [
            "--source-profile",
            "raw-json",
            "--s3-backup-bucket",
            "s3://example-firehose-backup",
            "--use-ack",
            "true",
        ],
        "required_files": ["cloudwatch-delivery-metrics.spl", "firehose-destination-settings.json.template"],
        "expected_metadata": {
            "selected_source": "aws:firehose:raw-json",
            "selected_sourcetype": "_json",
        },
        "expected_evidence": {
            "selected_source": "aws:firehose:raw-json",
            "selected_sourcetype": "_json",
        },
    },
    "splunk-security-content-update-setup": {
        "required_flags": ["--platform", "--es-app", "--story-filter", "--activation-policy"],
        "render_args": ["--platform", "cloud", "--story-filter", "ransomware"],
        "required_files": [],
    },
    "splunk-fraud-analytics-setup": {
        "required_flags": ["--platform", "--es-app", "--fraud-use-case", "--risk-index", "--transaction-index"],
        "render_args": ["--fraud-use-case", "account_takeover", "--transaction-index", "payments"],
        "required_files": [],
    },
    "splunk-pci-compliance-setup": {
        "required_flags": ["--platform", "--es-app", "--cde-indexes", "--pci-macro", "--installer-profile"],
        "render_args": ["--cde-indexes", "cardholder,auth", "--pci-macro", "pci_indexes"],
        "required_files": [],
        "expected_evidence": {"expected_indexes": ["cardholder", "auth"]},
    },
    "splunk-infosec-app-setup": {
        "required_flags": ["--platform", "--es-app", "--security-indexes", "--cloud-idm-required"],
        "render_args": ["--cloud-idm-required", "true", "--security-indexes", "netfw,endpoint,identity"],
        "required_files": ["cloud-idm-support-note.md"],
        "expected_evidence": {"expected_indexes": ["netfw", "endpoint", "identity"]},
    },
    "splunk-lookup-file-editing-setup": {
        "required_flags": ["--platform", "--es-app", "--lookup-owner-app", "--lookup-scope", "--shc-mode"],
        "render_args": ["--lookup-scope", "both", "--shc-mode", "true"],
        "required_files": ["shc-allow-rest-replay-runbook.md"],
    },
}


def run_bash(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["bash", str(script), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_new_first_class_skill_help_surfaces_required_flags() -> None:
    common_flags = [
        "--render",
        "--install",
        "--validate",
        "--all",
        "--dry-run",
        "--live",
        "--json",
        "--output-dir",
        "--help",
    ]
    for skill, case in SKILL_CASES.items():
        with subprocess.Popen(
            ["bash", str(REPO_ROOT / "skills" / skill / "scripts/setup.sh"), "--help"],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as proc:
            stdout, stderr = proc.communicate(timeout=30)
        assert proc.returncode == 0, stdout + stderr
        for flag in common_flags + case["required_flags"]:
            assert flag in stdout, f"{skill} help is missing {flag}"


def test_new_first_class_skills_emit_executable_dry_run_action_plans(tmp_path: Path) -> None:
    local_package = tmp_path / "fraud-analytics.tgz"
    local_package.write_text("placeholder package for dry-run planning\n", encoding="utf-8")
    token_file = tmp_path / "hec-token.txt"
    token_file.write_text("placeholder-token\n", encoding="utf-8")

    command_cases = {
        "cisco-asa-ta-setup": {
            "args": ["--all", "--dry-run", "--json"],
            "phase": "install",
            "install_contains": ["--app-id", "1620"],
        },
        "splunk-amazon-kinesis-firehose-setup": {
            "args": [
                "--all",
                "--dry-run",
                "--json",
                "--platform",
                "enterprise",
                "--token-file",
                str(token_file),
                "--source-profile",
                "raw-json",
            ],
            "phase": "hec-apply",
            "install_contains": ["splunk-hec-service-setup/scripts/setup.sh", "--source", "aws:firehose:raw-json", "--sourcetype", "_json"],
        },
        "splunk-security-content-update-setup": {
            "args": ["--all", "--dry-run", "--json"],
            "phase": "install",
            "install_contains": ["--app-id", "3449"],
        },
        "splunk-fraud-analytics-setup": {
            "args": ["--all", "--dry-run", "--json", "--file", str(local_package)],
            "phase": "install",
            "install_contains": ["--source", "local", "--file", str(local_package)],
        },
        "splunk-pci-compliance-setup": {
            "args": ["--all", "--dry-run", "--json", "--installer-profile", "enterprise-security"],
            "phase": "install",
            "install_contains": ["--app-id", "2897"],
        },
        "splunk-infosec-app-setup": {
            "args": ["--all", "--dry-run", "--json"],
            "phase": "install",
            "install_contains": ["--app-id", "4240"],
        },
        "splunk-lookup-file-editing-setup": {
            "args": ["--all", "--dry-run", "--json"],
            "phase": "install",
            "install_contains": ["--app-id", "1724"],
        },
    }

    for skill, case in command_cases.items():
        result = run_bash(REPO_ROOT / "skills" / skill / "scripts/setup.sh", *case["args"])
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["dry_run"] is True
        assert payload["skill_name"] == skill
        assert "render" in payload["phases"]
        assert case["phase"] in payload["phases"]
        assert "validate" in payload["phases"]
        assert payload["render_command"][:2] == ["python3", str(REPO_ROOT / "skills" / skill / "scripts/render_assets.py")]
        assert payload["validate_command"][:2] == ["bash", str(REPO_ROOT / "skills" / skill / "scripts/validate.sh")]
        joined_install = " ".join(payload["install_command"])
        for expected in case["install_contains"]:
            assert expected in joined_install


def test_new_first_class_skills_render_and_validate_without_live_credentials(tmp_path: Path) -> None:
    for skill, case in SKILL_CASES.items():
        with subprocess.Popen(
            [
                "bash",
                str(REPO_ROOT / "skills" / skill / "scripts/setup.sh"),
                "--render",
                "--json",
                "--output-dir",
                str(tmp_path),
                *case["render_args"],
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as proc:
            stdout, stderr = proc.communicate(timeout=60)
        assert proc.returncode == 0, stdout + stderr
        assert "SUPER_SECRET" not in stdout
        payload = json.loads(stdout)
        assert payload["ok"] is True
        rendered_dir = Path(payload["output_dir"])
        assert rendered_dir.is_dir()
        assert CORE_RENDERED_FILES.issubset(set(payload["files"]))
        for required_file in case["required_files"]:
            assert required_file in payload["files"]

        metadata = json.loads((rendered_dir / "metadata.json").read_text(encoding="utf-8"))
        evidence = json.loads((rendered_dir / "readiness-evidence-template.json").read_text(encoding="utf-8"))
        assert metadata["skill_name"] == skill
        assert evidence["handoffs"]
        for key, value in case.get("expected_metadata", {}).items():
            assert metadata[key] == value
        for key, value in case.get("expected_evidence", {}).items():
            assert evidence[key] == value

        validate = run_bash(
            REPO_ROOT / "skills" / skill / "scripts/validate.sh",
            "--rendered-dir",
            str(tmp_path),
        )
        assert "FAIL: 0" in validate.stdout
        assert "Splunk Authentication" not in validate.stdout
