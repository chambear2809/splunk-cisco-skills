"""Regression coverage for managed host-role app directory ownership."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/splunk-enterprise-host-setup/scripts/setup.sh"


def test_managed_config_creates_and_owns_dedicated_app_root_before_write() -> None:
    source = SETUP.read_text(encoding="utf-8")
    start = source.index("write_splunk_config() {")
    end = source.index("\n}\n\ninstall_package_to_target()", start) + 2
    function = source[start:end]
    assert "install -d -m 750" in function
    assert 'chown "${SERVICE_USER}" "${app_dir}" "${local_dir}"' in function
    assert 'hbs_write_target_file "${EXECUTION_MODE}" "${target_path}"' in function
    assert "ZZZ_cisco_skills_*" in function
    assert '"${app_relative}" == *..*' in function
    assert "chown -R" not in function


def test_host_setup_shell_syntax_is_valid() -> None:
    import subprocess

    result = subprocess.run(["bash", "-n", str(SETUP)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
