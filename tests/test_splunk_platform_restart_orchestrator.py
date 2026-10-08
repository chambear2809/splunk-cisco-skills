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


def test_restart_plan_rejects_unknown_profile_before_emitting_default_plan(
    tmp_path: Path,
) -> None:
    credentials = tmp_path / "credentials"
    credentials.write_text(
        "\n".join(
            [
                "SPLUNK_PROFILE=missing",
                "PROFILE_known__SPLUNK_PLATFORM=enterprise",
                "PROFILE_known__SPLUNK_URI=https://known.example.invalid:8089",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["SPLUNK_CREDENTIALS_FILE"] = str(credentials)
    for key in (
        "SPLUNK_PLATFORM",
        "SPLUNK_PROFILE",
        "SPLUNK_SEARCH_API_URI",
        "SPLUNK_TARGET_ROLE",
        "SPLUNK_URI",
    ):
        env.pop(key, None)

    proc = subprocess.run(
        [
            "bash",
            str(SKILL_DIR / "scripts/setup.sh"),
            "--plan-restart",
            "--restart-mode",
            "rest",
            "--allow-rest-fallback",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    assert proc.returncode != 0
    assert "primary credential profile is not defined" in proc.stderr
    assert "decision=" not in proc.stdout
    assert "known.example.invalid" not in proc.stdout + proc.stderr


def test_restart_plan_rejects_unknown_target_role_before_emitting_a_path(
    tmp_path: Path,
) -> None:
    credentials = tmp_path / "credentials"
    credentials.write_text(
        "\n".join(
            [
                "SPLUNK_PLATFORM=enterprise",
                "SPLUNK_URI=https://restart.example.invalid:8089",
                "SPLUNK_TARGET_ROLE=synthetic-unknown-role",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["SPLUNK_CREDENTIALS_FILE"] = str(credentials)
    for key in (
        "SPLUNK_PLATFORM",
        "SPLUNK_PROFILE",
        "SPLUNK_SEARCH_API_URI",
        "SPLUNK_TARGET_ROLE",
        "SPLUNK_URI",
    ):
        env.pop(key, None)

    proc = subprocess.run(
        [
            "bash",
            str(SKILL_DIR / "scripts/setup.sh"),
            "--plan-restart",
            "--restart-mode",
            "auto",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    assert proc.returncode != 0
    assert "Unsupported Splunk restart target role" in proc.stderr
    assert "decision=" not in proc.stdout


def test_restart_plan_rejects_unknown_cli_target_role(
    tmp_path: Path,
) -> None:
    credentials = tmp_path / "credentials"
    credentials.write_text(
        "SPLUNK_PLATFORM=enterprise\nSPLUNK_URI=https://restart.example.invalid:8089\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["SPLUNK_CREDENTIALS_FILE"] = str(credentials)
    for key in (
        "SPLUNK_PLATFORM",
        "SPLUNK_PROFILE",
        "SPLUNK_SEARCH_API_URI",
        "SPLUNK_TARGET_ROLE",
        "SPLUNK_URI",
    ):
        env.pop(key, None)

    proc = subprocess.run(
        [
            "bash",
            str(SKILL_DIR / "scripts/setup.sh"),
            "--plan-restart",
            "--target-role",
            "synthetic-unknown-role",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    assert proc.returncode != 0
    assert "Unsupported Splunk restart target role" in proc.stderr
    assert "decision=" not in proc.stdout


def test_reload_refuses_enterprise_host_command_for_cloud_target(tmp_path: Path) -> None:
    credentials = tmp_path / "credentials"
    credentials.write_text(
        "\n".join(
            [
                "SPLUNK_PLATFORM=cloud",
                "SPLUNK_CLOUD_STACK=example-stack",
                "SPLUNK_SEARCH_API_URI=https://example-stack.splunkcloud.com:8089",
                "SPLUNK_SSH_HOST=stale-enterprise-host.example.invalid",
                "",
            ]
        ),
        encoding="utf-8",
    )
    marker = tmp_path / "target-command-ran"
    fake_home = tmp_path / "fake-splunk"
    (fake_home / "bin").mkdir(parents=True)
    splunk = fake_home / "bin" / "splunk"
    splunk.write_text(
        f"#!/usr/bin/env bash\ntouch {str(marker)!r}\n",
        encoding="utf-8",
    )
    splunk.chmod(0o700)
    env = os.environ.copy()
    env["SPLUNK_CREDENTIALS_FILE"] = str(credentials)
    env["SPLUNK_HOME"] = str(fake_home)
    env["PLATFORM_RESTART_EXECUTION"] = "local"
    for key in (
        "SPLUNK_PLATFORM",
        "SPLUNK_PROFILE",
        "SPLUNK_SEARCH_API_URI",
        "SPLUNK_SSH_HOST",
        "SPLUNK_URI",
    ):
        env.pop(key, None)

    proc = subprocess.run(
        [
            "bash",
            str(SKILL_DIR / "scripts/setup.sh"),
            "--reload",
            "deploy-server",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    assert proc.returncode != 0
    assert "supported only for a resolved Splunk Enterprise target" in proc.stderr
    assert not marker.exists()


def test_reload_refuses_deploy_server_command_for_indexer_role(tmp_path: Path) -> None:
    credentials = tmp_path / "credentials"
    credentials.write_text(
        "\n".join(
            [
                "SPLUNK_PLATFORM=enterprise",
                "SPLUNK_TARGET_ROLE=indexer",
                "SPLUNK_URI=https://indexer.example.invalid:8089",
                "",
            ]
        ),
        encoding="utf-8",
    )
    marker = tmp_path / "target-command-ran"
    fake_home = tmp_path / "fake-splunk"
    (fake_home / "bin").mkdir(parents=True)
    splunk = fake_home / "bin" / "splunk"
    splunk.write_text(
        f"#!/usr/bin/env bash\ntouch {str(marker)!r}\n",
        encoding="utf-8",
    )
    splunk.chmod(0o700)
    env = os.environ.copy()
    env["SPLUNK_CREDENTIALS_FILE"] = str(credentials)
    env["SPLUNK_HOME"] = str(fake_home)
    env["PLATFORM_RESTART_EXECUTION"] = "local"
    for key in (
        "SPLUNK_PLATFORM",
        "SPLUNK_PROFILE",
        "SPLUNK_SEARCH_API_URI",
        "SPLUNK_TARGET_ROLE",
        "SPLUNK_URI",
    ):
        env.pop(key, None)

    proc = subprocess.run(
        [
            "bash",
            str(SKILL_DIR / "scripts/setup.sh"),
            "--reload",
            "deploy-server",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    assert proc.returncode != 0
    assert "incompatible with the selected Splunk target role" in proc.stderr
    assert not marker.exists()


def test_reload_refuses_generic_rest_command_for_indexer_role(tmp_path: Path) -> None:
    credentials = tmp_path / "credentials"
    credentials.write_text(
        "\n".join(
            [
                "SPLUNK_PLATFORM=enterprise",
                "SPLUNK_TARGET_ROLE=indexer",
                "SPLUNK_URI=https://indexer.example.invalid:8089",
                "",
            ]
        ),
        encoding="utf-8",
    )
    marker = tmp_path / "curl-ran"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl = fake_bin / "curl"
    curl.write_text(
        f"#!/usr/bin/env bash\ntouch {str(marker)!r}\n",
        encoding="utf-8",
    )
    curl.chmod(0o700)
    env = os.environ.copy()
    env["SPLUNK_CREDENTIALS_FILE"] = str(credentials)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    for key in (
        "SPLUNK_PLATFORM",
        "SPLUNK_PROFILE",
        "SPLUNK_SEARCH_API_URI",
        "SPLUNK_TARGET_ROLE",
        "SPLUNK_URI",
    ):
        env.pop(key, None)

    proc = subprocess.run(
        [
            "bash",
            str(SKILL_DIR / "scripts/setup.sh"),
            "--reload",
            "/services/server/control/restart",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    assert proc.returncode != 0
    assert "Generic REST reload is incompatible" in proc.stderr
    assert not marker.exists()


def test_reload_rejects_http_error_response_from_generic_rest_endpoint(
    tmp_path: Path,
) -> None:
    credentials = tmp_path / "credentials"
    credentials.write_text(
        "\n".join(
            [
                "SPLUNK_PLATFORM=enterprise",
                "SPLUNK_TARGET_ROLE=search-tier",
                "SPLUNK_URI=https://search.example.invalid:8089",
                "SPLUNK_USER=synthetic-user",
                "SPLUNK_PASS=synthetic-password",
                "SPLUNK_VERIFY_SSL=false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    marker = tmp_path / "reload-request-ran"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl = fake_bin / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        "case \"$*\" in\n"
        "  *services/auth/login*) printf '%s' '<response><sessionKey>synthetic-session</sessionKey></response>' ;;\n"
        f"  *) touch {str(marker)!r}; printf '%s' '500' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    curl.chmod(0o700)
    env = os.environ.copy()
    env["SPLUNK_CREDENTIALS_FILE"] = str(credentials)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    for key in (
        "SPLUNK_PLATFORM",
        "SPLUNK_PROFILE",
        "SPLUNK_SEARCH_API_URI",
        "SPLUNK_TARGET_ROLE",
        "SPLUNK_URI",
        "SPLUNK_USER",
        "SPLUNK_PASS",
    ):
        env.pop(key, None)

    proc = subprocess.run(
        [
            "bash",
            str(SKILL_DIR / "scripts/setup.sh"),
            "--reload",
            "/services/properties/indexes",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    assert proc.returncode != 0
    assert "returned HTTP 500" in proc.stderr
    assert marker.exists()


def test_restart_plan_uses_file_backed_target_role_in_parent_context(
    tmp_path: Path,
) -> None:
    credentials = tmp_path / "credentials"
    credentials.write_text(
        "\n".join(
            [
                "SPLUNK_PLATFORM=enterprise",
                "SPLUNK_TARGET_ROLE=indexer",
                "SPLUNK_URI=https://indexer.example.invalid:8089",
                "SPLUNK_USER=user",
                "SPLUNK_PASS=synthetic-password",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["SPLUNK_CREDENTIALS_FILE"] = str(credentials)
    for key in (
        "SPLUNK_PLATFORM",
        "SPLUNK_PROFILE",
        "SPLUNK_SEARCH_API_URI",
        "SPLUNK_TARGET_ROLE",
        "SPLUNK_URI",
    ):
        env.pop(key, None)

    proc = subprocess.run(
        [
            "bash",
            str(SKILL_DIR / "scripts/setup.sh"),
            "--plan-restart",
            "--restart-mode",
            "auto",
            "--json",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    plan = json.loads(proc.stdout)["restart_plan"]
    assert plan["target_role"] == "indexer"
    assert plan["decision"] == "delegate-splunk-indexer-cluster-setup"


def test_cloud_restart_refuses_indexer_role_before_any_acs_command(
    tmp_path: Path,
) -> None:
    credentials = tmp_path / "credentials"
    credentials.write_text(
        "\n".join(
            [
                "SPLUNK_PLATFORM=cloud",
                "SPLUNK_CLOUD_STACK=example-stack",
                "SPLUNK_SEARCH_API_URI=https://example-stack.splunkcloud.com:8089",
                "SPLUNK_USER=user",
                "SPLUNK_PASS=synthetic-password",
                "",
            ]
        ),
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "acs-command-ran"
    acs = bin_dir / "acs"
    acs.write_text(
        f"#!/usr/bin/env bash\ntouch {str(marker)!r}\n",
        encoding="utf-8",
    )
    acs.chmod(0o700)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["SPLUNK_CREDENTIALS_FILE"] = str(credentials)
    for key in (
        "SPLUNK_PLATFORM",
        "SPLUNK_PROFILE",
        "SPLUNK_SEARCH_API_URI",
        "SPLUNK_TARGET_ROLE",
        "SPLUNK_URI",
    ):
        env.pop(key, None)

    proc = subprocess.run(
        [
            "bash",
            str(SKILL_DIR / "scripts/setup.sh"),
            "--restart",
            "--accept-restart",
            "--target-role",
            "indexer",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    assert proc.returncode != 0
    assert "supports only standalone or search-tier targets" in proc.stderr
    assert not marker.exists()
    assert "synthetic-password" not in proc.stdout + proc.stderr


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


def test_systemd_detection_binds_execstart_to_selected_home_and_fails_closed() -> None:
    helper = REPO_ROOT / "skills/shared/lib/restart_helpers.sh"
    script = f"""
set -euo pipefail
source {helper!s}
_platform_restart_capture() {{
    local raw="$2"
    case "$raw" in
        if*realpath*)
            case "$raw" in
                *"/selected/bin/splunk"*) printf '%s' '/selected/bin/splunk' ;;
                *"/other/bin/splunk"*) printf '%s' '/other/bin/splunk' ;;
            esac
            ;;
        *systemctl*)
            case "$raw" in
                *"/selected/bin/splunk"*)
                    case "$raw" in *wrong.service*) ;; *) printf '%s' 'Splunkd.service' ;; esac
                    ;;
            esac
            ;;
    esac
}}
unset SPLUNK_SYSTEMD_UNIT
[ "$(platform_restart_detect_systemd_unit local /selected)" = 'Splunkd.service' ]
if result="$(platform_restart_detect_systemd_unit local /other 2>/dev/null)"; then
    test -z "$result"
else
    test -z "$result"
fi
SPLUNK_SYSTEMD_UNIT=wrong.service
if result="$(platform_restart_detect_systemd_unit local /selected 2>/dev/null)"; then
    test -z "$result"
else
    test -z "$result"
fi
"""
    proc = subprocess.run(
        ["bash", "-c", script], cwd=REPO_ROOT, text=True, capture_output=True
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_non_systemd_cli_switches_to_binary_owner_with_noninteractive_sudo() -> None:
    helper = REPO_ROOT / "skills/shared/lib/restart_helpers.sh"
    script = f"""
set -euo pipefail
source {helper!s}
hbs_shell_join() {{ printf '%q' "$1"; shift; for arg in "$@"; do printf ' %q' "$arg"; done; }}
runlog=''
_platform_restart_capture() {{
    case "$2" in
        *"test -x"*) return 0 ;;
        *"id -u --"*) printf '%s' '2000' ;;
        *"id -u"*) printf '%s' '1000' ;;
        *"stat -c %u"*) printf '%s' '2000' ;;
        *"stat -c %U"*) printf '%s' 'splunk' ;;
    esac
}}
_platform_restart_run() {{ runlog="$2"; return 0; }}
SPLUNK_OS_USER=splunk
_platform_restart_cli local /selected false
case "$runlog" in *'sudo -n -u splunk'*) ;; *) exit 1 ;; esac
case "$runlog" in *restart*) ;; *) exit 1 ;; esac
"""
    proc = subprocess.run(
        ["bash", "-c", script], cwd=REPO_ROOT, text=True, capture_output=True
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_non_systemd_cli_fails_closed_for_unusable_binary_owner() -> None:
    helper = REPO_ROOT / "skills/shared/lib/restart_helpers.sh"
    script = f"""
set -euo pipefail
source {helper!s}
hbs_shell_join() {{ printf '%q' "$1"; shift; for arg in "$@"; do printf ' %q' "$arg"; done; }}
runs=0
_platform_restart_capture() {{
    case "$2" in
        *"test -x"*) return 0 ;;
        *"id -u"*) printf '%s' '1000' ;;
        *"stat -c %u"*) printf '%s' '2000' ;;
        *"stat -c %U"*) printf '%s' 'user with spaces' ;;
    esac
}}
_platform_restart_run() {{ runs=$((runs + 1)); return 0; }}
SPLUNK_OS_USER='user with spaces'
if _platform_restart_cli local /selected false; then exit 1; fi
test "$runs" -eq 0
"""
    proc = subprocess.run(
        ["bash", "-c", script], cwd=REPO_ROOT, text=True, capture_output=True
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_non_systemd_cli_rejects_root_owned_install_with_other_service_user() -> None:
    helper = REPO_ROOT / "skills/shared/lib/restart_helpers.sh"
    script = f"""
set -euo pipefail
source {helper!s}
hbs_shell_join() {{ printf '%q' "$1"; shift; for arg in "$@"; do printf ' %q' "$arg"; done; }}
runs=0
_platform_restart_capture() {{
    case "$2" in
        *"test -x"*) return 0 ;;
        *"id -u --"*) printf '%s' '2000' ;;
        *"id -u"*) printf '%s' '1000' ;;
        *"stat -c %u"*) printf '%s' '0' ;;
    esac
}}
_platform_restart_run() {{ runs=$((runs + 1)); return 0; }}
SPLUNK_OS_USER=splunk
if _platform_restart_cli local /selected false; then exit 1; fi
test "$runs" -eq 0
"""
    proc = subprocess.run(
        ["bash", "-c", script], cwd=REPO_ROOT, text=True, capture_output=True
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_explicit_systemd_unit_mismatch_aborts_plan(tmp_path: Path) -> None:
    home = tmp_path / "splunk"
    (home / "bin").mkdir(parents=True)
    splunk = home / "bin" / "splunk"
    splunk.write_text("#!/bin/sh\n", encoding="utf-8")
    splunk.chmod(0o755)
    credentials = tmp_path / "credentials"
    credentials.write_text(
        "SPLUNK_PLATFORM=enterprise\nSPLUNK_URI=https://localhost:8089\n"
        "SPLUNK_USER=admin\nSPLUNK_PASS=fixture\nSPLUNK_VERIFY_SSL=false\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "SPLUNK_CREDENTIALS_FILE": str(credentials),
            "PLATFORM_RESTART_EXECUTION": "local",
            "SPLUNK_HOME": str(home),
            "SPLUNK_SYSTEMD_UNIT": "wrong.service",
        }
    )
    proc = subprocess.run(
        [
            "bash",
            str(SKILL_DIR / "scripts/setup.sh"),
            "--plan-restart",
            "--operation",
            "unit mismatch",
            "--restart-mode",
            "auto",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert proc.returncode != 0
    assert "does not match selected Splunk home" in proc.stderr


def test_non_systemd_cli_root_cannot_bypass_missing_service_identity_proof() -> None:
    helper = REPO_ROOT / "skills/shared/lib/restart_helpers.sh"
    script = f"""
set -euo pipefail
source {helper!s}
hbs_shell_join() {{ printf '%q' "$1"; shift; for arg in "$@"; do printf ' %q' "$arg"; done; }}
runs=0
_platform_restart_capture() {{
    case "$2" in
        *"test -x"*) return 0 ;;
        *"id -u"*) printf '%s' '0' ;;
        *"stat -c %u"*) printf '%s' '0' ;;
        *) return 1 ;;
    esac
}}
_platform_restart_run() {{ runs=$((runs + 1)); return 0; }}
unset SPLUNK_OS_USER SPLUNK_REMOTE_SUDO
if _platform_restart_cli local /selected false; then exit 1; fi
test "$runs" -eq 0
"""
    proc = subprocess.run(
        ["bash", "-c", script], cwd=REPO_ROOT, text=True, capture_output=True
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_non_systemd_cli_uses_guarded_sudo_readonly_probes_when_pid_is_denied() -> None:
    helper = REPO_ROOT / "skills/shared/lib/restart_helpers.sh"
    script = f"""
set -euo pipefail
source {helper!s}
hbs_shell_join() {{ printf '%q' "$1"; shift; for arg in "$@"; do printf ' %q' "$arg"; done; }}
runlog=''
_platform_restart_capture() {{
    case "$2" in
        *"test -x"*) return 0 ;;
        *"id -u --"*) return 1 ;;
        *"id -u"*) printf '%s' '1000' ;;
        *"stat -c %u"*"/selected/bin/splunk"*) printf '%s' '1002' ;;
        *"stat -c %u"*"/selected"*) printf '%s' '1002' ;;
        *"sudo -n -- head -n 1 --"*) printf '3983361\n' ;;
        *"head -n 1 --"*"splunkd.pid"*) return 1 ;;
        *"realpath -e"*"/selected/bin/splunkd"*) printf '%s' '/selected/bin/splunkd' ;;
        *"sudo -n -- realpath -e"*) printf '%s' '/selected/bin/splunkd' ;;
        *"realpath -e"*"/proc/3983361/exe"*) return 1 ;;
        *"sudo -n -- stat -c %u"*) printf '%s' '1002' ;;
        *"stat -c %u"*"/proc/3983361"*) return 1 ;;
        *"getent passwd"*) printf '%s' 'splunk' ;;
    esac
}}
_platform_restart_run() {{ runlog="$2"; return 0; }}
SPLUNK_REMOTE_SUDO=true
_platform_restart_cli local /selected false
case "$runlog" in *'sudo -n -u splunk'*) ;; *) exit 1 ;; esac
"""
    proc = subprocess.run(
        ["bash", "-c", script], cwd=REPO_ROOT, text=True, capture_output=True
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_non_systemd_cli_rejects_malformed_first_pid_line() -> None:
    helper = REPO_ROOT / "skills/shared/lib/restart_helpers.sh"
    script = f"""
set -euo pipefail
source {helper!s}
hbs_shell_join() {{ printf '%q' "$1"; shift; for arg in "$@"; do printf ' %q' "$arg"; done; }}
runs=0
_platform_restart_capture() {{
    case "$2" in
        *"test -x"*) return 0 ;;
        *"id -u"*) printf '%s' '1000' ;;
        *"stat -c %u"*) printf '%s' '1002' ;;
        *"head -n 1"*) printf '%s' 'not-a-pid' ;;
    esac
}}
_platform_restart_run() {{ runs=$((runs + 1)); return 0; }}
if _platform_restart_cli local /selected false; then exit 1; fi
test "$runs" -eq 0
"""
    proc = subprocess.run(
        ["bash", "-c", script], cwd=REPO_ROOT, text=True, capture_output=True
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_non_systemd_cli_accepts_first_line_of_multiline_pid_fixture(tmp_path: Path) -> None:
    helper = REPO_ROOT / "skills/shared/lib/restart_helpers.sh"
    fixture = tmp_path / "splunkd.pid"
    fixture.write_text("3983361\n3983362\n", encoding="utf-8")
    script = f"""
set -euo pipefail
source {helper!s}
hbs_shell_join() {{ printf '%q' "$1"; shift; for arg in "$@"; do printf ' %q' "$arg"; done; }}
_platform_restart_capture() {{
    case "$2" in
        *"id -u --"*) return 1 ;;
        *"id -u"*) printf '%s' '1000' ;;
        *"stat -c %u"*) printf '%s' '1002' ;;
        *"head -n 1"*) head -n 1 -- {fixture} ;;
        *"realpath -e"*"/selected/bin/splunkd"*) printf '%s' '/selected/bin/splunkd' ;;
        *"realpath -e"*"/proc/3983361/exe"*) printf '%s' '/selected/bin/splunkd' ;;
        *"stat -c %u"*"/proc/3983361"*) printf '%s' '1002' ;;
        *"getent passwd"*) printf '%s' 'splunk' ;;
    esac
}}
_platform_restart_resolve_cli_owner local /selected /selected/bin/splunk
"""
    proc = subprocess.run(
        ["bash", "-c", script], cwd=REPO_ROOT, text=True, capture_output=True
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def _expected_port_probe_function() -> str:
    setup = (SKILL_DIR / "scripts/setup.sh").read_text(encoding="utf-8")
    start = setup.index("validate_expected_ports_after_restart() {")
    end = setup.index("\nrun_reload() {", start)
    return setup[start:end]


def test_expected_port_probe_uses_plain_remote_python_and_preserves_ssh_helper() -> None:
    function = _expected_port_probe_function()
    script = f"""
set -euo pipefail
{function}
EXPECTED_PORTS=8089
calls=''
log() {{ printf '%s\\n' "$*" >&2; }}
plan_value() {{ case "$1" in execution_mode) printf '%s' ssh ;; splunk_home) printf '%s' /opt/splunk ;; esac; }}
hbs_shell_join() {{ printf '%q' "$1"; shift; for arg in "$@"; do printf ' %q' "$arg"; done; }}
_platform_restart_capture() {{ calls="$2"; case "$1" in ssh) ;; *) exit 20 ;; esac; return 0; }}
validate_expected_ports_after_restart ignored
case "$calls" in
  *"python3 -c"*) ;;
  *) exit 21 ;;
esac
case "$calls" in
  *"splunk cmd"*|*"/bin/splunk"*) exit 22 ;;
esac
"""
    proc = subprocess.run(
        ["bash", "-c", script], cwd=REPO_ROOT, text=True, capture_output=True
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_expected_port_probe_fails_closed_when_remote_listener_is_unavailable() -> None:
    function = _expected_port_probe_function()
    script = f"""
set -euo pipefail
{function}
EXPECTED_PORTS=8089
log() {{ printf '%s\\n' "$*" >&2; }}
plan_value() {{ case "$1" in execution_mode) printf '%s' ssh ;; splunk_home) printf '%s' /opt/splunk ;; esac; }}
hbs_shell_join() {{ printf '%q' "$1"; shift; for arg in "$@"; do printf ' %q' "$arg"; done; }}
_platform_restart_capture() {{ return 1; }}
if validate_expected_ports_after_restart ignored; then exit 30; fi
"""
    proc = subprocess.run(
        ["bash", "-c", script], cwd=REPO_ROOT, text=True, capture_output=True
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "not reachable" in proc.stderr
