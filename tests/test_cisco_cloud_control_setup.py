"""Regression coverage for cisco-cloud-control-setup."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills/cisco-cloud-control-setup"
SETUP = SKILL_DIR / "scripts/setup.sh"
VALIDATE = SKILL_DIR / "scripts/validate.sh"
RENDER = SKILL_DIR / "scripts/render_assets.py"
TEMPLATE = SKILL_DIR / "template.example"


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
    chunks: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def test_help_advertises_render_execute_and_validate() -> None:
    for script in (SETUP, VALIDATE):
        result = run_cmd("bash", str(script), "--help")
        combined = (result.stdout + result.stderr).lower()
        assert "render" in combined
        assert "execute" in combined
        assert "validate" in combined


def test_render_template_creates_required_artifacts(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    result = run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--validate",
        "--spec",
        str(TEMPLATE),
        "--output-dir",
        str(output_dir),
        "--json",
    )
    payload = json.loads(result.stdout)
    assert payload["output_dir"] == str(output_dir.resolve())

    required = [
        "coverage-report.json",
        "coverage-report.md",
        "apply-plan.json",
        "doctor-report.md",
        "handoff.md",
        "metadata.json",
        "platform/feature-coverage.md",
        "platform/product-integration-matrix.md",
        "platform/admin-readiness.md",
        "api/cloud-control-api-boundary.md",
        "api/workflows-api-readiness.md",
        "data-fabric/cisco-data-fabric-2026-readiness.md",
        "studio/agent-blueprints/network-incident-triage.md",
        "studio/mcp-connector-plan.md",
        "studio/app-builder-briefs/operations-console.md",
        "ai-canvas/board-templates/agentic-operations-readiness.md",
    ]
    for rel in required:
        assert (output_dir / rel).is_file()

    for section in [
        "data-fabric",
        "mcp",
        "agent-observability",
        "observability-content",
        "domain-readiness",
        "cloud-control-studio",
        "ai-canvas",
    ]:
        script = output_dir / "scripts" / f"execute-{section}.sh"
        assert script.is_file()
        assert script.stat().st_mode & 0o111
    assert f'PROJECT_ROOT="${{PROJECT_ROOT:-{REPO_ROOT}}}"' in (
        output_dir / "scripts/execute-data-fabric.sh"
    ).read_text(encoding="utf-8")
    assert (output_dir / "data-fabric/handoff.md").is_file()

    api_text = (output_dir / "api/workflows-api-readiness.md").read_text(encoding="utf-8")
    assert "https://api.meraki.com/api/automate/organizations" in api_text
    assert "OpenAPI" in api_text
    assert "Start API 20/min" in api_text


def test_coverage_rows_use_allowed_statuses_and_required_fields(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    run_cmd("bash", str(SETUP), "--render", "--spec", str(TEMPLATE), "--output-dir", str(output_dir))
    coverage = json.loads((output_dir / "coverage-report.json").read_text(encoding="utf-8"))
    allowed = {
        "delegated_apply",
        "render",
        "ui_handoff",
        "ca_handoff",
        "validate",
        "not_applicable",
    }
    required = {"key", "area", "status", "owner", "source_url", "apply_boundary"}
    rows = coverage["coverage"]
    assert rows
    for row in rows:
        assert row["status"] in allowed
        assert required <= set(row)
    keys = {row["key"] for row in rows}
    for key in {
        "product_meraki",
        "product_catalyst_center",
        "product_nexus_dashboard",
        "product_nexus_hyperfabric",
        "product_intersight",
        "product_catalyst_sd_wan_manager",
        "product_security_cloud_control",
        "product_thousandeyes",
        "product_splunk_cloud",
        "product_collaboration_control_hub",
        "product_cisco_iq",
        "inventory_global_assets",
        "licensing_visibility",
        "rbac",
        "topology",
        "workflows_and_atomics",
        "workflows_api",
        "workflow_targets_account_keys",
        "release_notes_open_issues",
        "data_fabric_machine_data_lake_alpha",
        "data_fabric_built_in_data_catalog",
        "data_fabric_ai_powered_data_management",
        "data_fabric_expanded_federated_search",
        "data_fabric_machine_data_ai_activation",
        "data_fabric_spl2_pipeline_kit",
    }:
        assert key in keys


def test_execute_dry_run_json_emits_secret_free_command_arrays(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    secret = "DIRECT_SECRET_SHOULD_NOT_RENDER"
    result = run_cmd(
        "bash",
        str(SETUP),
        "--execute",
        "data-fabric,mcp,agent-observability,observability-content",
        "--dry-run",
        "--json",
        "--spec",
        str(TEMPLATE),
        "--output-dir",
        str(output_dir),
    )
    payload = json.loads(result.stdout)
    assert payload["selected_sections"] == [
        "data-fabric",
        "mcp",
        "agent-observability",
        "observability-content",
    ]
    for section in payload["sections"]:
        assert isinstance(section["commands"], list)
        for command in section["commands"]:
            assert isinstance(command, list)
            assert command
    text = json.dumps(payload)
    assert secret not in text
    assert "--token" not in text
    assert "--password" not in text
    assert "--api-key" not in text
    assert "--client-secret" not in text
    assert "--private-key" not in text
    mcp = next(section for section in payload["sections"] if section["name"] == "mcp")
    mcp_commands_text = json.dumps(mcp["commands"])
    assert "cisco-thousandeyes-mcp-setup" in mcp_commands_text
    assert "splunk-mcp-server-setup" not in mcp_commands_text
    data_fabric = next(section for section in payload["sections"] if section["name"] == "data-fabric")
    data_fabric_text = json.dumps(data_fabric["commands"])
    assert "splunk-federated-search-setup" not in data_fabric_text
    assert "splunk-edge-processor-setup" not in data_fabric_text
    assert "splunk-spl2-pipeline-kit" in data_fabric_text


def test_splunk_mcp_render_command_requires_explicit_mcp_url(tmp_path: Path) -> None:
    spec = tmp_path / "mcp-url.json"
    spec.write_text(
        json.dumps(
            {
                "api_version": "cisco-cloud-control-setup/v1",
                "mcp": {
                    "enabled": True,
                    "splunk_mcp_enabled": True,
                    "splunk_mcp_url": "https://splunk.example.com:8089/services/mcp",
                    "thousandeyes_mcp_enabled": False,
                },
            }
        ),
        encoding="utf-8",
    )
    result = run_cmd(
        "bash",
        str(SETUP),
        "--execute",
        "mcp",
        "--dry-run",
        "--json",
        "--spec",
        str(spec),
        "--output-dir",
        str(tmp_path / "rendered"),
    )
    payload = json.loads(result.stdout)
    text = json.dumps(payload)
    assert "splunk-mcp-server-setup" in text
    assert "--mcp-url" in text
    assert "https://splunk.example.com:8089/services/mcp" in text
    assert "--no-register-codex" in text
    assert "--no-configure-cursor" in text
    assert "--no-configure-claude" in text


def test_custom_named_studio_and_canvas_artifacts_still_validate(tmp_path: Path) -> None:
    spec = tmp_path / "custom.json"
    spec.write_text(
        json.dumps(
            {
                "api_version": "cisco-cloud-control-setup/v1",
                "studio": {
                    "agent_blueprints": [
                        {
                            "name": "WAN Change Review",
                            "domain": "networking",
                            "objective": "Review WAN change risk before execution.",
                        }
                    ],
                    "app_builder_briefs": [
                        {
                            "name": "Executive Incident Brief",
                            "audience": "Executives",
                            "objective": "Summarize business impact and owner actions.",
                        }
                    ],
                },
                "ai_canvas": {
                    "boards": [
                        {
                            "name": "WAN Readiness Board",
                            "objective": "Coordinate prerequisites for governed WAN changes.",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "rendered with spaces"

    run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--validate",
        "--spec",
        str(spec),
        "--output-dir",
        str(output_dir),
    )

    assert (output_dir / "studio/agent-blueprints/wan-change-review.md").is_file()
    assert (output_dir / "studio/app-builder-briefs/executive-incident-brief.md").is_file()
    assert (output_dir / "ai-canvas/board-templates/wan-readiness-board.md").is_file()


def test_doctor_json_keeps_stdout_machine_readable(tmp_path: Path) -> None:
    result = run_cmd(
        "bash",
        str(SETUP),
        "--doctor",
        "--json",
        "--spec",
        str(TEMPLATE),
        "--output-dir",
        str(tmp_path / "rendered"),
    )

    payload = json.loads(result.stdout)
    assert payload["doctor_report"].endswith("doctor-report.md")
    assert "doctor completed" in result.stderr


def test_execute_without_accept_fails_closed(tmp_path: Path) -> None:
    result = run_cmd(
        "bash",
        str(SETUP),
        "--execute",
        "data-fabric",
        "--output-dir",
        str(tmp_path / "rendered"),
        check=False,
    )
    assert result.returncode != 0
    assert "--accept-execute" in (result.stdout + result.stderr)


def test_direct_secret_flags_are_rejected_without_echoing_value(tmp_path: Path) -> None:
    secret = "DIRECT_SECRET_SHOULD_NOT_ECHO"
    result = run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(tmp_path / "rendered"),
        "--api-key",
        secret,
        check=False,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert secret not in combined
    assert "secret-file" in combined


def test_raw_secret_looking_spec_keys_fail_validation(tmp_path: Path) -> None:
    spec = tmp_path / "bad.yaml"
    spec.write_text(
        "api_version: cisco-cloud-control-setup/v1\ncloud_control:\n  token: SHOULD_NOT_RENDER\n",
        encoding="utf-8",
    )
    result = run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--spec",
        str(spec),
        "--output-dir",
        str(tmp_path / "rendered"),
        check=False,
    )
    assert result.returncode != 0
    assert "SHOULD_NOT_RENDER" not in (result.stdout + result.stderr)
    assert "raw secret-looking key" in (result.stdout + result.stderr)


def test_python_scripts_compile() -> None:
    run_cmd(sys.executable, "-m", "py_compile", str(RENDER))
