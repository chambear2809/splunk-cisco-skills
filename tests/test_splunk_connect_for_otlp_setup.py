#!/usr/bin/env python3
"""Regression tests for splunk-connect-for-otlp-setup."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills/splunk-connect-for-otlp-setup"
SETUP = SKILL_DIR / "scripts/setup.sh"
VALIDATE = SKILL_DIR / "scripts/validate.sh"
RENDER = SKILL_DIR / "scripts/render_sender_assets.py"
DOCTOR = SKILL_DIR / "scripts/doctor.py"


def run_cmd(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def rendered_text(root: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def test_registry_entry_covers_splunkbase_8704() -> None:
    registry = json.loads((REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8"))
    entry = next(app for app in registry["apps"] if app["splunkbase_id"] == "8704")
    topology = next(item for item in registry["skill_topologies"] if item["skill"] == "splunk-connect-for-otlp-setup")

    assert entry["app_name"] == "splunk-connect-for-otlp"
    assert entry["latest_verified_version"] == "0.4.1"
    assert entry["latest_verified_date"] == "May 6, 2026"
    assert "splunk-connect-for-otlp*.tgz" in entry["package_patterns"]
    assert entry["capabilities"]["needs_custom_rest"] is False
    assert entry["capabilities"]["needs_kvstore"] is False
    assert entry["capabilities"]["needs_python_runtime"] is False
    assert entry["role_support"]["heavy-forwarder"] == "supported"
    assert topology["role_support"]["external-collector"] == "supported"


def test_setup_dry_run_json_includes_safe_full_lifecycle_plan() -> None:
    result = run_cmd(
        "bash",
        str(SETUP),
        "--dry-run",
        "--json",
        "--configure-input",
        "--input-name",
        "otlp-main",
        "--expected-index",
        "otlp_events",
    )
    payload = json.loads(result.stdout)

    assert payload["app"]["splunkbase_id"] == "8704"
    assert payload["operations"] == ["configure-input"]
    assert payload["input"]["grpc_port"] == 4317
    assert payload["input"]["http_port"] == 4318
    assert payload["sender"]["auth_header_format"] == "Authorization: Splunk <HEC_TOKEN>"
    assert payload["sender"]["token_value_rendered"] is False
    assert payload["hec_handoff"]["skill"] == "splunk-hec-service-setup"
    assert "SECRET" not in result.stdout


def test_validate_guards_missing_app_and_unbound_ports() -> None:
    validate_text = VALIDATE.read_text(encoding="utf-8")
    rest_text = (REPO_ROOT / "skills/shared/lib/rest_helpers.sh").read_text(encoding="utf-8")

    assert '${app_version}" == "unknown"' in validate_text
    assert "grpc-listener" in validate_text
    assert "http-listener" in validate_text
    assert "ssh -o BatchMode=yes" in validate_text
    assert "SPLUNK_REST_MAX_TIME" in rest_text


def test_rendered_sender_assets_cover_http_grpc_metadata_and_no_token_values(tmp_path: Path) -> None:
    secret = "SUPER_SECRET_HEC_TOKEN_SHOULD_NOT_RENDER"
    token_file = tmp_path / "hec.token"
    token_file.write_text(secret, encoding="utf-8")
    output_dir = tmp_path / "rendered"

    result = run_cmd(
        "bash",
        str(SETUP),
        "--render-sender-config",
        "--output-dir",
        str(output_dir),
        "--receiver-host",
        "otlp.example.com",
        "--expected-index",
        "otlp_events",
        "--hec-token-file",
        str(token_file),
        "--json",
    )
    payload = json.loads(result.stdout)
    render_dir = output_dir / "splunk-connect-for-otlp"
    combined = rendered_text(render_dir)

    assert payload["receiver"]["grpc_endpoint"] == "otlp.example.com:4317"
    assert (render_dir / "collector-otlp-sender.yaml").is_file()
    assert (render_dir / "sdk-env-http.sh").is_file()
    assert (render_dir / "telemetrygen-smoke.sh").is_file()
    assert secret not in combined
    assert "Authorization=Splunk ${SPLUNK_HEC_TOKEN}" in combined
    assert "Authorization: \"Splunk ${env:SPLUNK_HEC_TOKEN}\"" in combined
    assert f'SPLUNK_HEC_TOKEN_FILE="{token_file}"' in combined
    assert "SPLUNK_HEC_TOKEN_FILE=\"$/" not in combined
    assert "com.splunk.index" in combined
    assert "otlp_events" in combined
    assert "otlp.example.com:4317" in combined
    assert "http://otlp.example.com:4318/v1/logs" in combined
    assert "http://otlp.example.com:4318/v1/metrics" in combined
    assert "http://otlp.example.com:4318/v1/traces" in combined


def test_doctor_classifies_topology_hec_sender_and_internal_failures(tmp_path: Path) -> None:
    evidence = {
        "platform": {"os": "linux", "machine": "x86_64", "cloud_topology": "classic", "tier": "search-tier"},
        "app": {"installed": False},
        "inputs": [
            {
                "name": "otlp-main",
                "disabled": True,
                "grpc_port": 0,
                "http_port": 4318,
                "listen_address": "127.0.0.1",
                "enableSSL": True,
                "serverCert": "",
                "serverKey": "",
            }
        ],
        "hec": {
            "enabled": False,
            "tokens": [{"name": "splunk_otlp", "disabled": True, "allowed_indexes": ["allowed"]}],
        },
        "senders": [
            {
                "name": "bad-http",
                "endpoint": "http://otlp.example.com:4318/v1/trace",
                "headers": {},
                "com.splunk.index": "forbidden",
            }
        ],
        "internal_errors": [
            {"component": "ExecProcessor", "message": "bind: address already in use"},
            {"component": "ModularInputs", "message": "index denied for forbidden"},
        ],
    }
    evidence_file = tmp_path / "evidence.json"
    evidence_file.write_text(json.dumps(evidence), encoding="utf-8")
    output_dir = tmp_path / "doctor"

    result = run_cmd(
        sys.executable,
        str(DOCTOR),
        "--evidence-file",
        str(evidence_file),
        "--output-dir",
        str(output_dir),
        "--expected-index",
        "otlp_events",
        "--json",
    )
    payload = json.loads(result.stdout)
    fix_ids = {item["fix_id"] for item in payload["report"]["findings"]}

    assert "CLOUD_CLASSIC_REQUIRES_IDM_OR_HF" in fix_ids
    assert "APP_MISSING" in fix_ids
    assert "INPUT_DISABLED" in fix_ids
    assert "BAD_PORT" in fix_ids
    assert "BAD_LISTEN_ADDRESS" in fix_ids
    assert "TLS_FILES_MISSING" in fix_ids
    assert "HEC_GLOBAL_DISABLED" in fix_ids
    assert "HEC_TOKEN_DISABLED" in fix_ids
    assert "HEC_ALLOWED_INDEX_MISSING" in fix_ids
    assert "SENDER_AUTH_HEADER_MISSING" in fix_ids
    assert "SENDER_HTTP_PATH_INVALID" in fix_ids
    assert "SENDER_INDEX_FORBIDDEN" in fix_ids
    assert "INTERNAL_BIND_FAILURE" in fix_ids
    assert "INTERNAL_INDEX_DENIED" in fix_ids
    assert (output_dir / "doctor-report.md").is_file()
    assert (output_dir / "fix-plan.json").is_file()


def test_doctor_redacts_token_like_evidence(tmp_path: Path) -> None:
    secret = "SUPER_SECRET_TOKEN_SHOULD_NOT_RENDER"
    evidence = {
        "platform": {"os": "linux", "machine": "x86_64"},
        "inputs": [{"name": "default", "grpc_port": 4317, "http_port": 4318, "listen_address": "0.0.0.0"}],
        "hec": {"tokens": [{"name": "splunk_otlp", "token": secret, "allowed_indexes": ["otlp_events"]}]},
        "senders": [{"name": "sender", "endpoint": "http://otlp.example.com:4318/v1/logs", "headers": {"Authorization": f"Splunk {secret}"}, "com.splunk.index": "otlp_events"}],
    }
    evidence_file = tmp_path / "evidence.json"
    evidence_file.write_text(json.dumps(evidence), encoding="utf-8")
    output_dir = tmp_path / "doctor"

    result = run_cmd(
        sys.executable,
        str(DOCTOR),
        "--evidence-file",
        str(evidence_file),
        "--output-dir",
        str(output_dir),
        "--json",
    )
    combined = result.stdout + rendered_text(output_dir)

    assert secret not in combined
    assert "[REDACTED]" in combined


def test_direct_secret_flags_are_rejected_without_echoing_values(tmp_path: Path) -> None:
    secret = "DIRECT_SECRET_SHOULD_NOT_ECHO"
    result = run_cmd(
        sys.executable,
        str(RENDER),
        "--output-dir",
        str(tmp_path / "rendered"),
        "--token",
        secret,
        check=False,
    )

    assert result.returncode != 0
    assert secret not in result.stdout + result.stderr
    assert "Use --hec-token-file" in result.stdout + result.stderr


def test_package_inspection_constants_match_audited_release_metadata() -> None:
    spec = importlib.util.spec_from_file_location("otlp_doctor", DOCTOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("otlp_doctor", module)
    spec.loader.exec_module(module)

    assert module.KNOWN_SHA256 == "fde0d93532703e04ab5aa544815d52232ef62afae2c0a55e374dc74d2d58f9d1"
    assert module.KNOWN_MD5 == "6190585a3c12cb9f273f7f9f11cdb3be"
    assert module.EXPECTED_FILES == [
        "splunk-connect-for-otlp/README/inputs.conf.spec",
        "splunk-connect-for-otlp/default/app.conf",
        "splunk-connect-for-otlp/default/data/ui/manager/splunk-connect-for-otlp.xml",
        "splunk-connect-for-otlp/default/inputs.conf",
        "splunk-connect-for-otlp/default/props.conf",
        "splunk-connect-for-otlp/linux_x86_64/bin/splunk-connect-for-otlp",
        "splunk-connect-for-otlp/metadata/default.meta",
        "splunk-connect-for-otlp/windows_x86_64/bin/splunk-connect-for-otlp",
    ]
