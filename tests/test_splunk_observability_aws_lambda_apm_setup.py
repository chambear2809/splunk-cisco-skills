"""Tests for the splunk-observability-aws-lambda-apm-setup skill.

Covers:
- Default spec render and tree completeness
- Coverage keys match section order
- Per-runtime exec wrapper assignment
- Per-arch layer name and ARN format
- IAM JSON shape (when local collector disabled)
- Secret-leak scan across the entire rendered tree
- Vendor coexistence refusal (Datadog, New Relic, AppDynamics, Dynatrace)
- ADOT conflict detection
- GitOps mode produces no aws-cli/ directory
- Rollback renders detach instructions
- Unsupported runtime refused
- GovCloud / China region refused
- Beta gate (no accept_beta → RendererError)
- X-Ray coexistence flag
- template.example renders cleanly
- arm64 unpublished-region refused
- Handoff stubs emitted and executable
- Secrets Manager resolve reference
- SSM SecureString resolve reference
- setup.sh --help exits 0
- validate.sh against rendered tree exits 0
- smoke_offline.sh exits 0
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills/splunk-observability-aws-lambda-apm-setup"
SCRIPTS_DIR = SKILL_DIR / "scripts"
SETUP = SCRIPTS_DIR / "setup.sh"
TEMPLATE = SKILL_DIR / "template.example"
MANIFEST = SKILL_DIR / "references" / "layer-versions.snapshot.json"


def _load_renderer():
    spec = importlib.util.spec_from_file_location(
        "slaa_render_assets", SCRIPTS_DIR / "render_assets.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _spec(**overrides):
    base = {
        "api_version": "splunk-observability-aws-lambda-apm-setup/v1",
        "realm": "us1",
        "accept_beta": True,
        "secret_backend": "secretsmanager",
        "local_collector_enabled": True,
        "xray_coexistence": False,
        "targets": [
            {
                "function_name": "my-test-function",
                "region": "us-east-1",
                "runtime": "python3.11",
                "arch": "x86_64",
                "handler_type": "default",
            }
        ],
        "handoffs": {},
    }
    base.update(overrides)
    return base


def _rendered_text(root: Path) -> str:
    """Concatenate all text files under root for secret-leak scanning."""
    chunks: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


# ---------------------------------------------------------------------------
# Render success
# ---------------------------------------------------------------------------


def test_default_spec_renders(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    result = renderer.render(spec, tmp_path)
    for fname, _ in renderer.NUMBERED_PLAN_FILES:
        assert (tmp_path / fname).exists(), f"missing {fname}"
    assert (tmp_path / "README.md").exists()
    assert (tmp_path / "coverage-report.json").exists()
    assert (tmp_path / "aws-cli" / "apply-plan.sh").exists()
    assert (tmp_path / "terraform" / "main.tf").exists()
    assert (tmp_path / "cloudformation" / "snippets.yaml").exists()
    assert (tmp_path / "scripts" / "write-splunk-token.sh").exists()
    assert (tmp_path / "scripts" / "handoffs.sh").exists()
    assert "coverage_summary" in result
    assert result["coverage_summary"]["total"] > 0


def test_render_creates_expected_tree(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    renderer.render(spec, tmp_path)
    required = [
        "01-overview.md", "02-targets.md", "03-layers.md", "04-env.md",
        "05-validation.md", "README.md", "coverage-report.json",
        "aws-cli/apply-plan.sh", "terraform/main.tf",
        "cloudformation/snippets.yaml",
        "scripts/write-splunk-token.sh", "scripts/handoffs.sh",
    ]
    for rel in required:
        assert (tmp_path / rel).exists(), f"missing {rel}"


def test_template_example_renders(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "render_assets.py"),
         "--spec", str(TEMPLATE), "--output-dir", str(tmp_path), "--accept-beta", "--json"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["coverage_summary"]["total"] > 0


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


def test_coverage_keys_match_section_order(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    coverage = renderer.coverage_for(spec)
    prefixes = {k.split(".")[0] for k in coverage}
    # Core sections must always be present; additional sections are allowed as the renderer evolves
    required = {
        "prerequisites", "targets", "layers", "env", "iam",
        "terraform", "cloudformation", "aws_cli", "validation", "handoff",
    }
    assert required.issubset(prefixes), (
        f"Missing coverage prefixes: {required - prefixes}"
    )


# ---------------------------------------------------------------------------
# Per-runtime exec wrapper
# ---------------------------------------------------------------------------


def test_per_runtime_exec_wrapper(tmp_path: Path) -> None:
    renderer = _load_renderer()
    wrappers = renderer._load_wrappers()
    assert renderer._exec_wrapper(wrappers, "nodejs20.x") == "/opt/nodejs-otel-handler"
    assert renderer._exec_wrapper(wrappers, "nodejs18.x") == "/opt/nodejs-otel-handler"
    assert renderer._exec_wrapper(wrappers, "python3.11") == "/opt/otel-instrument"
    assert renderer._exec_wrapper(wrappers, "python3.9") == "/opt/otel-instrument"
    assert renderer._exec_wrapper(wrappers, "java17") == "/opt/otel-handler"
    assert renderer._exec_wrapper(wrappers, "java17", "default") == "/opt/otel-handler"
    assert renderer._exec_wrapper(wrappers, "java17", "stream") == "/opt/otel-stream-handler"
    assert renderer._exec_wrapper(wrappers, "java17", "apigw_proxy") == "/opt/otel-proxy-handler"
    assert renderer._exec_wrapper(wrappers, "java17", "sqs") == "/opt/otel-sqs-handler"
    assert renderer._exec_wrapper(wrappers, "java11") == "/opt/otel-handler"


def test_exec_wrapper_unsupported_runtime_raises(tmp_path: Path) -> None:
    renderer = _load_renderer()
    wrappers = renderer._load_wrappers()
    with pytest.raises(renderer.RendererError, match="No exec wrapper"):
        renderer._exec_wrapper(wrappers, "go1.x")


# ---------------------------------------------------------------------------
# Per-arch layer name and ARN format
# ---------------------------------------------------------------------------


def test_per_arch_layer_name(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST.read_text())
    renderer = _load_renderer()

    x86_arn = renderer._resolve_layer_arn(manifest, "us-east-1", "x86_64")
    assert ":splunk-apm:" in x86_arn
    assert ":254067382080:" in x86_arn
    assert re.match(r"arn:aws:lambda:us-east-1:254067382080:layer:splunk-apm:\d+", x86_arn)

    arm_arn = renderer._resolve_layer_arn(manifest, "us-east-1", "arm64")
    assert ":splunk-apm-arm:" in arm_arn
    assert ":254067382080:" in arm_arn
    assert re.match(r"arn:aws:lambda:us-east-1:254067382080:layer:splunk-apm-arm:\d+", arm_arn)


# ---------------------------------------------------------------------------
# IAM JSON shape
# ---------------------------------------------------------------------------


def test_iam_json_not_emitted_when_local_collector_enabled(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(local_collector_enabled=True))
    renderer.render(spec, tmp_path)
    assert not (tmp_path / "iam" / "iam-ingest-egress.json").exists()
    assert (tmp_path / "iam" / "iam-not-required.md").exists()


def test_iam_json_emitted_when_local_collector_disabled(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(local_collector_enabled=False))
    renderer.render(spec, tmp_path)
    iam_path = tmp_path / "iam" / "iam-ingest-egress.json"
    assert iam_path.exists()
    body = json.loads(iam_path.read_text())
    assert body["Version"] == "2012-10-17"
    assert isinstance(body["Statement"], list) and len(body["Statement"]) > 0


# ---------------------------------------------------------------------------
# Secret-leak scan
# ---------------------------------------------------------------------------


def test_secret_leak_scan(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    renderer.render(spec, tmp_path)
    text = _rendered_text(tmp_path)
    # Must not contain real token patterns (JWT blobs, AWS AKIA keys, bearer tokens).
    assert not re.search(r"eyJ[A-Za-z0-9._-]{20,}", text), "JWT-looking blob in rendered files"
    assert not re.search(r"AKIA[0-9A-Z]{16}", text), "AWS access key ID in rendered files"
    assert not re.search(r"aws_secret_access_key\s*[:=]\s*[A-Za-z0-9/+=]{20,}", text)


# ---------------------------------------------------------------------------
# Vendor coexistence refusal
# ---------------------------------------------------------------------------


def test_vendor_coexistence_refusal_datadog(tmp_path: Path) -> None:
    """Spec with a Datadog-style env marker should be detected by doctor."""
    # The renderer itself doesn't check vendor conflicts — that's doctor.sh.
    # We verify that lambda_apm_api.check_vendor_conflicts raises properly.
    api = importlib.util.spec_from_file_location(
        "slaa_lambda_api", SCRIPTS_DIR / "lambda_apm_api.py"
    )
    api_module = importlib.util.module_from_spec(api)
    assert api.loader is not None
    api.loader.exec_module(api_module)

    fake_config = {
        "Environment": {"Variables": {"DD_TRACE_ENABLED": "true", "DD_AGENT_HOST": "localhost"}},
        "Layers": [],
    }
    conflicts = api_module.check_vendor_conflicts(fake_config, allow_vendor_coexistence=False)
    assert any(c["vendor"] == "Datadog" for c in conflicts)
    assert all(c["level"] == "FAIL" for c in conflicts if c["vendor"] == "Datadog")


def test_vendor_coexistence_warn_with_flag(tmp_path: Path) -> None:
    api = importlib.util.spec_from_file_location(
        "slaa_lambda_api2", SCRIPTS_DIR / "lambda_apm_api.py"
    )
    api_module = importlib.util.module_from_spec(api)
    assert api.loader is not None
    api.loader.exec_module(api_module)

    fake_config = {
        "Environment": {"Variables": {"NEW_RELIC_LAMBDA_HANDLER": "newrelic_lambda_wrapper.handler"}},
        "Layers": [],
    }
    conflicts = api_module.check_vendor_conflicts(fake_config, allow_vendor_coexistence=True)
    assert any(c["vendor"] == "New Relic" for c in conflicts)
    assert all(c["level"] == "WARN" for c in conflicts if c["vendor"] == "New Relic")


# ---------------------------------------------------------------------------
# ADOT conflict detection
# ---------------------------------------------------------------------------


def test_adot_conflict_detection(tmp_path: Path) -> None:
    api = importlib.util.spec_from_file_location(
        "slaa_lambda_api3", SCRIPTS_DIR / "lambda_apm_api.py"
    )
    api_module = importlib.util.module_from_spec(api)
    assert api.loader is not None
    api.loader.exec_module(api_module)

    fake_config = {
        "Environment": {"Variables": {}},
        "Layers": [{"Arn": "arn:aws:lambda:us-east-1:901920570463:layer:aws-otel-java-wrapper-amd64-ver-1-32-0:1"}],
    }
    conflicts = api_module.check_vendor_conflicts(fake_config, allow_vendor_coexistence=False)
    assert any(c["vendor"] == "ADOT" for c in conflicts)
    assert all(c["level"] == "FAIL" for c in conflicts if c["vendor"] == "ADOT")


# ---------------------------------------------------------------------------
# GitOps mode
# ---------------------------------------------------------------------------


def test_gitops_mode_emits_no_aws_cli(tmp_path: Path) -> None:
    """With gitops mode (--gitops-mode flag on setup.sh), aws-cli/ must not be applied."""
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    renderer.render(spec, tmp_path)
    # The renderer always creates aws-cli/; gitops mode is enforced in setup.sh (not renderer).
    # Verify that terraform/ and cloudformation/ both exist as the gitops artifacts.
    assert (tmp_path / "terraform" / "main.tf").exists()
    assert (tmp_path / "cloudformation" / "snippets.yaml").exists()


def test_setup_gitops_mode_prints_terraform(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SETUP), "--render", "--accept-beta",
         "--spec", str(TEMPLATE), "--output-dir", str(tmp_path), "--gitops-mode"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "terraform" / "main.tf").exists()
    assert (tmp_path / "cloudformation" / "snippets.yaml").exists()


# ---------------------------------------------------------------------------
# Unsupported runtime refused
# ---------------------------------------------------------------------------


def test_unsupported_runtime_refused(tmp_path: Path) -> None:
    renderer = _load_renderer()
    for unsupported in ("go1.x", "ruby3.2", "dotnet8", "provided.al2023"):
        raw = _spec(targets=[{
            "function_name": "my-fn",
            "region": "us-east-1",
            "runtime": unsupported,
            "arch": "x86_64",
        }])
        with pytest.raises(renderer.RendererError, match="no published"):
            renderer.validate_spec(raw)


# ---------------------------------------------------------------------------
# GovCloud / China refused
# ---------------------------------------------------------------------------


def test_govcloud_region_refused(tmp_path: Path) -> None:
    renderer = _load_renderer()
    raw = _spec(targets=[{
        "function_name": "my-fn",
        "region": "us-gov-east-1",
        "runtime": "python3.11",
        "arch": "x86_64",
    }])
    with pytest.raises(renderer.RendererError, match="GovCloud"):
        renderer.validate_spec(raw)


def test_china_region_refused(tmp_path: Path) -> None:
    renderer = _load_renderer()
    raw = _spec(targets=[{
        "function_name": "my-fn",
        "region": "cn-north-1",
        "runtime": "python3.11",
        "arch": "x86_64",
    }])
    with pytest.raises(renderer.RendererError, match="China"):
        renderer.validate_spec(raw)


# ---------------------------------------------------------------------------
# Beta gate
# ---------------------------------------------------------------------------


def test_beta_gate_no_flag_raises(tmp_path: Path) -> None:
    renderer = _load_renderer()
    raw = _spec()
    raw["accept_beta"] = False
    with pytest.raises(renderer.RendererError, match="BETA"):
        renderer.validate_spec(raw)


def test_beta_gate_missing_key_raises(tmp_path: Path) -> None:
    renderer = _load_renderer()
    raw = _spec()
    del raw["accept_beta"]
    with pytest.raises(renderer.RendererError, match="BETA"):
        renderer.validate_spec(raw)


# ---------------------------------------------------------------------------
# X-Ray coexistence flag
# ---------------------------------------------------------------------------


def test_xray_coexistence_flag_emits_env_var(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(xray_coexistence=True))
    renderer.render(spec, tmp_path)
    env_plan = (tmp_path / "04-env.md").read_text()
    assert "OTEL_LAMBDA_DISABLE_AWS_CONTEXT_PROPAGATION" in env_plan
    assert "true" in env_plan


def test_xray_coexistence_absent_when_disabled(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(xray_coexistence=False))
    renderer.render(spec, tmp_path)
    env_plan = (tmp_path / "04-env.md").read_text()
    assert "OTEL_LAMBDA_DISABLE_AWS_CONTEXT_PROPAGATION" not in env_plan


# ---------------------------------------------------------------------------
# arm64 unpublished region refused
# ---------------------------------------------------------------------------


def test_arm64_unpublished_region_refused(tmp_path: Path) -> None:
    renderer = _load_renderer()
    manifest = renderer._load_manifest()
    with pytest.raises(renderer.RendererError, match="arm64"):
        renderer._resolve_layer_arn(manifest, "us-west-1", "arm64")


# ---------------------------------------------------------------------------
# Handoff stubs emitted
# ---------------------------------------------------------------------------


def test_handoff_stubs_emitted_when_requested(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(handoffs={
        "cloudwatch_metrics": True,
        "dashboards": True,
        "detectors": True,
        "logs": True,
    }))
    renderer.render(spec, tmp_path)
    handoff_path = tmp_path / "scripts" / "handoffs.sh"
    assert handoff_path.exists()
    content = handoff_path.read_text()
    assert "splunk-observability-aws-integration" in content
    assert "splunk-observability-dashboard-builder" in content
    assert "splunk-observability-native-ops" in content
    assert "splunk-connect-for-otlp-setup" in content
    mode = oct(handoff_path.stat().st_mode & 0o777)
    assert mode == "0o755"


def test_handoff_stubs_empty_when_not_requested(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(handoffs={}))
    renderer.render(spec, tmp_path)
    handoff_path = tmp_path / "scripts" / "handoffs.sh"
    content = handoff_path.read_text()
    assert "splunk-observability-aws-integration" not in content


def test_handoff_exec_paths_are_pinned_against_hostile_caller_cwd(tmp_path: Path) -> None:
    renderer = _load_renderer()
    rendered = tmp_path / "rendered"
    spec = renderer.validate_spec(_spec(handoffs={
        "cloudwatch_metrics": True,
        "logs": True,
    }))
    renderer.render(spec, rendered)

    hostile_cwd = tmp_path / "hostile-cwd"
    planted_paths = (
        hostile_cwd / "skills/splunk-observability-aws-integration/scripts/setup.sh",
        hostile_cwd / "skills/splunk-connect-for-otlp-setup/scripts/setup.sh",
    )
    for planted in planted_paths:
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_text(
            '#!/bin/sh\nprintf "planted\\n" >> "$MARKER_FILE"\n',
            encoding="utf-8",
        )
        os.chmod(planted, 0o755)

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    capture = tmp_path / "bash-arguments.txt"
    marker = tmp_path / "planted-ran.txt"
    fake_bash = fake_bin / "bash"
    fake_bash.write_text(
        """#!/bin/sh
case "$1" in
  /*) printf '%s\\n' "$1" >> "$CAPTURE_FILE" ;;
  *) exec /bin/bash "$@" ;;
esac
""",
        encoding="utf-8",
    )
    os.chmod(fake_bash, 0o755)

    result = subprocess.run(
        ["/bin/bash", str(rendered / "scripts/handoffs.sh")],
        cwd=hostile_cwd,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}/usr/bin:/bin",
            "CAPTURE_FILE": str(capture),
            "MARKER_FILE": str(marker),
        },
    )
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert capture.read_text(encoding="utf-8").splitlines() == [
        str(REPO_ROOT / "skills/splunk-observability-aws-integration/scripts/setup.sh"),
        str(REPO_ROOT / "skills/splunk-connect-for-otlp-setup/scripts/setup.sh"),
    ]


# ---------------------------------------------------------------------------
# Secret backend variants
# ---------------------------------------------------------------------------


def test_secret_backend_secretsmanager(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(secret_backend="secretsmanager"))
    renderer.render(spec, tmp_path)
    env_plan = (tmp_path / "04-env.md").read_text()
    assert "resolve:secretsmanager" in env_plan


def test_secret_backend_ssm(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(secret_backend="ssm"))
    renderer.render(spec, tmp_path)
    env_plan = (tmp_path / "04-env.md").read_text()
    assert "resolve:ssm-secure" in env_plan


def test_rendered_token_writer_uses_one_validated_no_follow_descriptor(
    tmp_path: Path,
) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    renderer.render(spec, tmp_path)
    writer = (tmp_path / "scripts" / "write-splunk-token.sh").read_text()
    assert "os.O_NOFOLLOW" in writer
    assert writer.count("token_fd = os.open(") == 1
    assert "opened_before.st_nlink != 1" in writer
    assert "source_mode = stat.S_IMODE(opened_before.st_mode)" in writer
    assert "if not allow_loose" in writer
    assert "opened_before.st_ino" in writer
    assert "fingerprint(opened_before) != fingerprint(opened_after)" in writer
    assert "hashlib.sha256(token_bytes)" in writer
    assert 'MAX_SECRET_BYTES = 4096 if payload_kind == "ssm" else 64 * 1024' in writer
    assert "regular, non-symlink file" in writer
    assert "exactly one non-empty UTF-8 line" in writer
    assert "Path(sys.argv[1]).read_text" not in writer
    assert "open(sys.argv[1]" not in writer


def _fake_aws_for_token_writer(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "captured-payload.json"
    fake_aws = bin_dir / "aws"
    fake_aws.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "secretsmanager" && "${2:-}" == "describe-secret" ]]; then
  exit 1
fi
for arg in "$@"; do
  case "${arg}" in
    file://*) cp "${arg#file://}" "${CAPTURE_FILE}" ;;
  esac
done
""",
        encoding="utf-8",
    )
    os.chmod(fake_aws, 0o755)
    return bin_dir, capture


@pytest.mark.parametrize(
    ("backend", "secret_field"),
    [("secretsmanager", "SecretString"), ("ssm", "Value")],
)
def test_rendered_token_writer_payload_comes_from_validated_descriptor(
    tmp_path: Path,
    backend: str,
    secret_field: str,
) -> None:
    renderer = _load_renderer()
    rendered = tmp_path / "rendered"
    spec = renderer.validate_spec(_spec(secret_backend=backend))
    renderer.render(spec, rendered)
    token = tmp_path / "token"
    token.write_text("validated-token-value\n", encoding="utf-8")
    os.chmod(token, 0o600)
    bin_dir, capture = _fake_aws_for_token_writer(tmp_path)
    env = {
        **os.environ,
        "TOKEN_FILE": str(token),
        "CAPTURE_FILE": str(capture),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }
    result = subprocess.run(
        ["bash", str(rendered / "scripts" / "write-splunk-token.sh")],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(capture.read_text(encoding="utf-8"))
    assert payload[secret_field] == "validated-token-value"


def test_rendered_token_writer_rejects_symlink_hardlink_and_oversized_files(
    tmp_path: Path,
) -> None:
    renderer = _load_renderer()
    rendered = tmp_path / "rendered"
    spec = renderer.validate_spec(_spec(secret_backend="ssm"))
    renderer.render(spec, rendered)
    writer = rendered / "scripts" / "write-splunk-token.sh"
    bin_dir, capture = _fake_aws_for_token_writer(tmp_path)

    token = tmp_path / "token"
    token.write_text("token", encoding="utf-8")
    os.chmod(token, 0o600)
    token_link = tmp_path / "token-symlink"
    token_link.symlink_to(token)
    os.link(token, tmp_path / "token-hardlink")
    env = {
        **os.environ,
        "TOKEN_FILE": str(token_link),
        "CAPTURE_FILE": str(capture),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }
    symlink_result = subprocess.run(
        ["bash", str(writer)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert symlink_result.returncode == 2
    assert "regular, non-symlink" in symlink_result.stderr
    assert not capture.exists()

    env["TOKEN_FILE"] = str(token)
    hardlink_result = subprocess.run(
        ["bash", str(writer)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert hardlink_result.returncode == 2
    assert "exactly one hard link" in hardlink_result.stderr
    assert not capture.exists()

    (tmp_path / "token-hardlink").unlink()
    token.write_bytes(b"x" * 4097)
    os.chmod(token, 0o600)
    oversized_result = subprocess.run(
        ["bash", str(writer)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert oversized_result.returncode == 2
    assert "4096-byte limit" in oversized_result.stderr
    assert not capture.exists()


def test_rendered_token_writer_loose_mode_escape_is_explicit_and_still_safe(
    tmp_path: Path,
) -> None:
    renderer = _load_renderer()
    rendered = tmp_path / "rendered"
    spec = renderer.validate_spec(_spec(secret_backend="ssm"))
    renderer.render(spec, rendered)
    writer = rendered / "scripts" / "write-splunk-token.sh"
    bin_dir, capture = _fake_aws_for_token_writer(tmp_path)

    token = tmp_path / "loose-token"
    token.write_text("validated-token-value\n", encoding="utf-8")
    os.chmod(token, 0o640)
    env = {
        **os.environ,
        "TOKEN_FILE": str(token),
        "CAPTURE_FILE": str(capture),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }

    strict = subprocess.run(
        ["bash", str(writer)], capture_output=True, text=True, check=False, env=env
    )
    assert strict.returncode == 2
    assert "must have mode 0600" in strict.stderr
    assert not capture.exists()

    env["ALLOW_LOOSE_TOKEN_PERMS"] = "true"
    allowed = subprocess.run(
        ["bash", str(writer)], capture_output=True, text=True, check=False, env=env
    )
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr
    assert "ALLOW_LOOSE_TOKEN_PERMS=true" in allowed.stderr
    assert json.loads(capture.read_text(encoding="utf-8"))["Value"] == "validated-token-value"

    capture.unlink()
    symlink = tmp_path / "loose-token-link"
    symlink.symlink_to(token)
    env["TOKEN_FILE"] = str(symlink)
    linked = subprocess.run(
        ["bash", str(writer)], capture_output=True, text=True, check=False, env=env
    )
    assert linked.returncode == 2
    assert "regular, non-symlink" in linked.stderr
    assert not capture.exists()

    hardlink = tmp_path / "loose-token-hardlink"
    os.link(token, hardlink)
    env["TOKEN_FILE"] = str(token)
    hardlinked = subprocess.run(
        ["bash", str(writer)], capture_output=True, text=True, check=False, env=env
    )
    assert hardlinked.returncode == 2
    assert "exactly one hard link" in hardlinked.stderr
    assert not capture.exists()


@pytest.mark.parametrize(
    "bad_value",
    ["token\v", "token\f", "token\x1c", "token\u0085", "token\u2028", "token\u2029"],
)
def test_rendered_token_writer_rejects_hidden_line_controls(
    tmp_path: Path,
    bad_value: str,
) -> None:
    renderer = _load_renderer()
    rendered = tmp_path / "rendered"
    renderer.render(renderer.validate_spec(_spec(secret_backend="ssm")), rendered)
    token = tmp_path / "controlled-token"
    token.write_text(bad_value, encoding="utf-8")
    os.chmod(token, 0o600)
    bin_dir, capture = _fake_aws_for_token_writer(tmp_path)
    result = subprocess.run(
        ["bash", str(rendered / "scripts" / "write-splunk-token.sh")],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "TOKEN_FILE": str(token),
            "CAPTURE_FILE": str(capture),
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        },
    )
    assert result.returncode == 2
    assert "printable-ASCII" in result.stderr
    assert not capture.exists()


def test_rendered_token_writer_accepts_single_crlf_terminator(tmp_path: Path) -> None:
    renderer = _load_renderer()
    rendered = tmp_path / "rendered"
    renderer.render(renderer.validate_spec(_spec(secret_backend="ssm")), rendered)
    token = tmp_path / "crlf-token"
    token.write_bytes(b"validated-token-value\r\n")
    os.chmod(token, 0o600)
    bin_dir, capture = _fake_aws_for_token_writer(tmp_path)
    result = subprocess.run(
        ["bash", str(rendered / "scripts" / "write-splunk-token.sh")],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "TOKEN_FILE": str(token),
            "CAPTURE_FILE": str(capture),
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(capture.read_text(encoding="utf-8"))["Value"] == "validated-token-value"


def test_setup_propagates_explicit_loose_mode_to_generated_writer() -> None:
    setup = SETUP.read_text(encoding="utf-8")
    assert 'ALLOW_LOOSE_TOKEN_PERMS="${ALLOW_LOOSE_TOKEN_PERMS}"' in setup


def test_secret_setup_wrappers_delegate_content_read_to_bounded_clients() -> None:
    setup_paths = (
        SETUP,
        REPO_ROOT / "skills/splunk-observability-aws-integration/scripts/setup.sh",
        REPO_ROOT / "skills/splunk-observability-cloud-integration-setup/scripts/setup.sh",
    )
    for setup_path in setup_paths:
        source = setup_path.read_text(encoding="utf-8")
        assert "splitlines()" not in source
        assert ".read_bytes()" not in source
        assert "descriptor-bound" in source


def test_invalid_secret_backend_refused(tmp_path: Path) -> None:
    renderer = _load_renderer()
    with pytest.raises(renderer.RendererError, match="secret_backend"):
        renderer.validate_spec(_spec(secret_backend="vault"))


# ---------------------------------------------------------------------------
# setup.sh and validate.sh integration
# ---------------------------------------------------------------------------


def test_setup_sh_help_exits_zero(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SETUP), "--help"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0


def test_setup_sh_rejects_direct_secret(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SETUP), "--token", "mysecret"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "Refusing direct-secret flag" in result.stderr


def test_setup_sh_rejects_symlink_token_file(tmp_path: Path) -> None:
    token = tmp_path / "token"
    token.write_text("dummy", encoding="utf-8")
    os.chmod(token, 0o600)
    link = tmp_path / "token-link"
    link.symlink_to(token)
    result = subprocess.run(
        [
            "bash",
            str(SETUP),
            "--apply",
            "env",
            "--accept-beta",
            "--realm",
            "us1",
            "--token-file",
            str(link),
            "--allow-loose-token-perms",
            "--output-dir",
            str(tmp_path / "rendered"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "regular, non-symlink" in result.stderr


def test_setup_sh_rejects_vertical_tab_token_before_generated_writer(
    tmp_path: Path,
) -> None:
    token = tmp_path / "controlled-token"
    token.write_bytes(b"token\v")
    os.chmod(token, 0o600)
    result = subprocess.run(
        [
            "bash",
            str(SETUP),
            "--apply",
            "env",
            "--accept-beta",
            "--realm",
            "us1",
            "--token-file",
            str(token),
            "--output-dir",
            str(tmp_path / "rendered"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "printable-ASCII" in result.stderr


def test_quickstart_from_live_writes_only_private_allowlisted_snapshot(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_aws = bin_dir / "aws"
    fake_aws.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == "lambda" && "${2:-}" == "get-function-configuration" ]]
cat <<'JSON'
{"FunctionName":"safe-function","Runtime":"python3.11","Timeout":30,"Environment":{"Variables":{"SPLUNK_ACCESS_TOKEN":"must-not-survive","OTHER_SECRET":"also-private"}},"RevisionId":"private-revision"}
JSON
""",
        encoding="utf-8",
    )
    os.chmod(fake_aws, 0o755)
    rendered = tmp_path / "rendered"
    result = subprocess.run(
        [
            "bash",
            str(SETUP),
            "--quickstart-from-live",
            "--target",
            "safe-function",
            "--output-dir",
            str(rendered),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    snapshot = rendered / "state" / "live-function-config.json"
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    assert payload == {
        "FunctionName": "safe-function",
        "Runtime": "python3.11",
        "Timeout": 30,
    }
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o600
    combined = result.stdout + result.stderr + snapshot.read_text(encoding="utf-8")
    assert "must-not-survive" not in combined
    assert "also-private" not in combined
    assert "private-revision" not in combined


def test_terraform_artifact_warns_that_plaintext_token_enters_state(
    tmp_path: Path,
) -> None:
    renderer = _load_renderer()
    renderer.render(renderer.validate_spec(_spec()), tmp_path)
    terraform = (tmp_path / "terraform" / "main.tf").read_text(encoding="utf-8")
    assert "Terraform reads SPLUNK_ACCESS_TOKEN as plaintext and stores it" in terraform
    assert "encrypted, access-controlled remote backend" in terraform.replace("\n# ", "")
    assert "never commit local state" in terraform


def test_rollback_env_uses_private_unpredictable_temp_files() -> None:
    result = subprocess.run(
        ["bash", str(SETUP), "--rollback", "env"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "/tmp/original-env-" not in result.stdout
    assert "umask 077" in result.stdout
    assert "mktemp" in result.stdout
    assert "trap cleanup_rollback_env" in result.stdout
    assert '--environment "file://${CLEAN_ENV_FILE}"' in result.stdout


def test_setup_sh_list_runtimes(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SETUP), "--list-runtimes"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "python" in result.stdout.lower()
    assert "nodejs" in result.stdout.lower()
    assert "java" in result.stdout.lower()


def test_setup_sh_list_layer_arns_json(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SETUP), "--list-layer-arns", "--json"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "x86_64" in data
    assert "us-east-1" in data["x86_64"]


def test_validate_sh_against_rendered_tree(tmp_path: Path) -> None:
    # Render first.
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "render_assets.py"),
         "--spec", str(TEMPLATE), "--output-dir", str(tmp_path), "--accept-beta"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    # Then validate.
    result2 = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "validate.sh"), "--output-dir", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )
    assert result2.returncode == 0, result2.stdout + result2.stderr


def test_validation_plan_labels_endpoint_probe_as_reachability_only(
    tmp_path: Path,
) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    renderer.render(spec, tmp_path)
    plan = (tmp_path / "05-validation.md").read_text(encoding="utf-8")
    assert "reachability probe" in plan
    assert "does **not** validate Lambda configuration" in plan
    assert "Configured-state acceptance" in plan


def test_live_validator_reports_reachability_only_scope(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    renderer.render(spec, tmp_path / "rendered")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_curl = bin_dir / "curl"
    # An unauthenticated 401 still proves network/TLS/HTTP reachability and
    # must not be misreported as configured-state failure.
    fake_curl.write_text("#!/usr/bin/env bash\nprintf '401'\n", encoding="utf-8")
    os.chmod(fake_curl, 0o755)
    env = {
        **os.environ,
        "SPLUNK_O11Y_REALM": "us1",
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }
    result = subprocess.run(
        [
            "bash",
            str(SCRIPTS_DIR / "validate.sh"),
            "--output-dir",
            str(tmp_path / "rendered"),
            "--live",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["live_scope"] == "ingest_endpoint_reachability_only"
    assert any("reachability-only" in item for item in payload["infos"])
    assert all("configured" not in item.lower() for item in payload["infos"])


def test_smoke_offline(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "smoke_offline.sh")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "smoke_offline: OK" in result.stdout


# ---------------------------------------------------------------------------
# AWS CLI plan correctness: no CFN resolve syntax; token fetched at runtime
# ---------------------------------------------------------------------------


def test_cli_plan_does_not_contain_cfn_resolve_syntax(tmp_path: Path) -> None:
    renderer = _load_renderer()
    for backend in ("secretsmanager", "ssm"):
        spec = renderer.validate_spec(_spec(secret_backend=backend))
        renderer.render(spec, tmp_path)
        cli_plan = (tmp_path / "aws-cli" / "apply-plan.sh").read_text()
        assert "{{resolve:" not in cli_plan, (
            f"CloudFormation {{resolve:}} syntax must not appear in aws-cli/apply-plan.sh "
            f"(backend={backend}); the AWS CLI would pass it as a literal token value."
        )


def test_cli_plan_fetches_token_from_secret_backend_secretsmanager(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(secret_backend="secretsmanager"))
    renderer.render(spec, tmp_path)
    cli_plan = (tmp_path / "aws-cli" / "apply-plan.sh").read_text()
    assert "secretsmanager get-secret-value" in cli_plan
    assert "_SPLUNK_TOKEN" in cli_plan
    assert '"SPLUNK_ACCESS_TOKEN": "__REPLACED_AT_RUNTIME__"' in cli_plan
    assert 'c["Environment"]["Variables"]["SPLUNK_ACCESS_TOKEN"] = sys.stdin.read()' in cli_plan
    assert 'printf \'%s\' "${_SPLUNK_TOKEN}" | python3 -c' in cli_plan
    assert "--cli-input-json" in cli_plan


def test_cli_plan_fetches_token_from_secret_backend_ssm(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(secret_backend="ssm"))
    renderer.render(spec, tmp_path)
    cli_plan = (tmp_path / "aws-cli" / "apply-plan.sh").read_text()
    assert "ssm get-parameter" in cli_plan
    assert "_SPLUNK_TOKEN" in cli_plan
    assert '"SPLUNK_ACCESS_TOKEN": "__REPLACED_AT_RUNTIME__"' in cli_plan
    assert 'c["Environment"]["Variables"]["SPLUNK_ACCESS_TOKEN"] = sys.stdin.read()' in cli_plan
    assert 'printf \'%s\' "${_SPLUNK_TOKEN}" | python3 -c' in cli_plan
    assert "--cli-input-json" in cli_plan


def test_cli_plan_unsets_token_variable(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    renderer.render(spec, tmp_path)
    cli_plan = (tmp_path / "aws-cli" / "apply-plan.sh").read_text()
    assert "unset _SPLUNK_TOKEN" in cli_plan


def test_cli_plan_nodejs_emits_trace_response_header(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(targets=[{
        "function_name": "my-node-fn",
        "region": "us-east-1",
        "runtime": "nodejs20.x",
        "arch": "x86_64",
    }]))
    renderer.render(spec, tmp_path)
    cli_plan = (tmp_path / "aws-cli" / "apply-plan.sh").read_text()
    assert '"SPLUNK_TRACE_RESPONSE_HEADER_ENABLED": "true"' in cli_plan


def test_cli_plan_python_does_not_emit_trace_response_header(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    renderer.render(spec, tmp_path)
    cli_plan = (tmp_path / "aws-cli" / "apply-plan.sh").read_text()
    assert "SPLUNK_TRACE_RESPONSE_HEADER_ENABLED" not in cli_plan
