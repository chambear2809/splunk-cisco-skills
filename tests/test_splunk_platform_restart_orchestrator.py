from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "splunk-platform-restart-orchestrator"


def test_restart_orchestrator_registry_and_skill_files_are_present() -> None:
    for relative in (
        "SKILL.md",
        "reference.md",
        "template.example",
        "agents/openai.yaml",
        "scripts/setup.sh",
        "scripts/repo_audit.py",
    ):
        assert (SKILL_DIR / relative).exists(), relative

    registry = json.loads(
        (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
    )
    cloud_rows = registry["documentation"]["cloud_matrix_rows"]
    topologies = {entry["skill"]: entry for entry in registry["skill_topologies"]}

    assert any(
        row.get("kind") == "workflow"
        and row.get("skill") == "splunk-platform-restart-orchestrator"
        and row.get("splunkbase_id") == "N/A"
        for row in cloud_rows
    )
    topology = topologies["splunk-platform-restart-orchestrator"]
    assert topology["role_support"]["search-tier"] == "supported"
    assert topology["role_support"]["indexer"] == "supported"
    assert topology["role_support"]["universal-forwarder"] == "supported"
    assert topology["role_support"]["external-collector"] == "none"


def test_setup_plan_json_is_dry_and_does_not_render_secrets(tmp_path: Path) -> None:
    credentials = tmp_path / "credentials"
    sentinel = "top-secret-do-not-render"
    credentials.write_text(
        "\n".join(
            [
                "SPLUNK_PLATFORM=enterprise",
                "SPLUNK_URI=https://localhost:8089",
                "SPLUNK_USER=admin",
                f"SPLUNK_PASS={sentinel}",
                "SPLUNK_VERIFY_SSL=false",
                "",
            ]
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "SPLUNK_CREDENTIALS_FILE": str(credentials),
            "PLATFORM_RESTART_EXECUTION": "local",
            "SPLUNK_HOME": "/definitely/not/splunk",
        }
    )
    proc = subprocess.run(
        [
            "bash",
            str(SKILL_DIR / "scripts/setup.sh"),
            "--plan-restart",
            "--operation",
            "pytest restart plan",
            "--target-role",
            "search-tier",
            "--restart-mode",
            "rest",
            "--allow-rest-fallback",
            "--expected-port",
            "8089,4317",
            "--json",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    assert sentinel not in proc.stdout
    payload = json.loads(proc.stdout)
    plan = payload["restart_plan"]
    assert plan["decision"] == "rest-explicit"
    assert plan["operation"] == "pytest restart plan"
    assert plan["expected_ports"] == ["8089", "4317"]
    assert plan["secrets"] == "not-rendered"

    dry_restart = subprocess.run(
        [
            "bash",
            str(SKILL_DIR / "scripts/setup.sh"),
            "--restart",
            "--dry-run",
            "--operation",
            "pytest dry restart",
            "--restart-mode",
            "none",
            "--json",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    assert sentinel not in dry_restart.stdout
    assert json.loads(dry_restart.stdout)["restart_plan"]["decision"] == "handoff"


def test_repo_audit_classifies_restart_patterns_and_check_passes(tmp_path: Path) -> None:
    proc = subprocess.run(
        [
            "python3",
            str(SKILL_DIR / "scripts/repo_audit.py"),
            "--output-dir",
            str(tmp_path),
            "--check",
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    assert "repo-audit.md" in proc.stdout

    report = json.loads((tmp_path / "repo-audit.json").read_text(encoding="utf-8"))
    assert report["schema"] == "splunk-platform-restart-audit/v1"
    counts = report["counts"]
    for category in (
        "cloud_acs",
        "cluster_safe",
        "direct_rest_restart",
        "out_of_scope",
        "raw_splunk_restart",
        "reload_only",
    ):
        assert category in counts
    assert counts["reload_only"] > 0
    assert counts["cluster_safe"] > 0


def test_shared_restart_helpers_are_the_default_adoption_path() -> None:
    credential_helpers = (
        REPO_ROOT / "skills/shared/lib/credential_helpers.sh"
    ).read_text(encoding="utf-8")
    rest_helpers = (REPO_ROOT / "skills/shared/lib/rest_helpers.sh").read_text(
        encoding="utf-8"
    )
    acs_helpers = (REPO_ROOT / "skills/shared/lib/acs_helpers.sh").read_text(
        encoding="utf-8"
    )
    restart_helpers = (
        REPO_ROOT / "skills/shared/lib/restart_helpers.sh"
    ).read_text(encoding="utf-8")

    assert 'source "${_LIB_DIR}/restart_helpers.sh"' in credential_helpers
    assert "platform_restart_or_exit" in rest_helpers
    assert "platform_reload_or_restart_guidance" in acs_helpers
    assert "PLATFORM_RESTART_ALLOW_REST_FALLBACK" in restart_helpers
    assert '${restart_mode}" == "none"' in restart_helpers
    assert "platform_restart_handoff" in restart_helpers


def test_cluster_and_license_adoption_avoid_default_rest_restart() -> None:
    cluster_helpers = (
        REPO_ROOT / "skills/shared/lib/cluster_helpers.sh"
    ).read_text(encoding="utf-8")
    idxc_renderer = (
        REPO_ROOT / "skills/splunk-indexer-cluster-setup/scripts/render_assets.py"
    ).read_text(encoding="utf-8")
    license_renderer = (
        REPO_ROOT / "skills/splunk-license-manager-setup/scripts/render_assets.py"
    ).read_text(encoding="utf-8")

    assert "/services/cluster/manager/control/default/validate_bundle" in cluster_helpers
    assert "check-restart=true" in cluster_helpers
    assert "/services/server/control/restart" not in idxc_renderer
    assert 'cluster_bundle_validate "${MANAGER_URI}" "${SK}" true' in idxc_renderer
    assert "platform_restart_handoff" in idxc_renderer
    assert "/services/server/control/restart" not in license_renderer
    assert "platform_restart_or_exit" in license_renderer
    assert "platform_restart_handoff" in license_renderer
