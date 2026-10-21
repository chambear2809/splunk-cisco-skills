"""Focused offline regressions for generated ACS command paths."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "skills/splunk-cloud-acs-admin-setup/scripts/setup.sh"


def _render(tmp_path: Path, *extra: str) -> Path:
    args = [
        "bash", str(SETUP), "--phase", "render", "--output-dir", str(tmp_path),
        "--target-stack", "synthetic-stack",
    ]
    if "--modules" not in extra:
        args += [
            "--features", "search-api",
            "--search-api-subnets", "198.51.100.0/24",
            "--search-api-subnets-v6", "2001:db8::/64",
        ]
    args += list(extra)
    subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return tmp_path / "acs-admin"


def _run_mocked(script: Path, tmp_path: Path, *, malformed: bool = False) -> subprocess.CompletedProcess[str]:
    original = script.read_text(encoding="utf-8")
    marker = next(line for line in original.splitlines() if line.startswith("source "))
    mock = r'''
acs_prepare_context() { return 0; }
acs_command() {
  printf '%s\n' "$*" >> "${ACS_TEST_LOG}"
  if [[ "${ACS_MOCK_BAD:-false}" == "true" ]]; then
    printf '[{"type":"http","response":"{\\"unexpected\\":true}"}]'
    return 0
  fi
  case "$1 $2 $3" in
    'ip-allowlist describe search-api'|'ip-allowlist-v6 describe search-api')
      printf '[{"type":"http","response":"{\\"subnets\\":[]}"}]' ;;
    'ip-allowlist create search-api'|'ip-allowlist-v6 create search-api')
      return 0 ;;
    *) return 1 ;;
  esac
}
'''
    test_script = script.parent / f"{script.name}.test.sh"
    test_script.write_text(
        original.replace(marker, marker + "\n" + mock, 1), encoding="utf-8"
    )
    test_script.chmod(0o700)
    env = os.environ.copy()
    log_path = tmp_path / "commands.log"
    log_path.write_text("", encoding="utf-8")
    env.update({"ACS_TEST_LOG": str(log_path), "ACS_MOCK_BAD": str(malformed).lower()})
    return subprocess.run(["bash", str(test_script)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)


def test_generated_apply_paths_use_describe_and_bind_feature(tmp_path: Path) -> None:
    rendered = _render(tmp_path)
    for name, expected in (("apply-ipv4.sh", "ip-allowlist describe search-api"), ("apply-ipv6.sh", "ip-allowlist-v6 describe search-api")):
        result = _run_mocked(rendered / name, tmp_path)
        assert result.returncode == 0, result.stderr
        commands = (tmp_path / "commands.log").read_text(encoding="utf-8").splitlines()
        assert expected in commands
        subnet = "2001:db8::/64" if name == "apply-ipv6.sh" else "198.51.100.0/24"
        assert expected.replace(" describe ", " create ") + f" --subnets {subnet}" in commands
        assert all(" search-api " in f" {line} " for line in commands)
        assert not any("delete" in line for line in commands)

    bad = _run_mocked(rendered / "apply-ipv4.sh", tmp_path, malformed=True)
    assert bad.returncode != 0
    commands = (tmp_path / "commands.log").read_text(encoding="utf-8")
    assert "create" not in commands and "delete" not in commands


def test_generated_license_inventory_is_unassessed_without_cli_call(tmp_path: Path) -> None:
    rendered = _render(tmp_path, "--modules", "license")
    inventory = rendered / "inventory.sh"
    original = inventory.read_text(encoding="utf-8")
    marker = next(line for line in original.splitlines() if line.startswith("source "))
    mock = (
        'acs_prepare_context() { return 0; }\n'
        'acs_command() {\n'
        '  printf "%s\\n" "$*" >> "${ACS_TEST_LOG}";\n'
        '  if [[ "${1:-} ${2:-} ${3:-}" == "status current-stack " ]]; then\n'
        '    printf "%s\\n" \'[{"type":"http","response":"{\\"infrastructure\\":{\\"status\\":\\"Ready\\"},\\"messages\\":{\\"restartRequired\\":false}}"}]\';\n'
        '    return 0;\n'
        '  fi\n'
        '  return 1;\n'
        '}\n'
    )
    test_inventory = tmp_path / "inventory.test.sh"
    test_inventory.write_text(original.replace(marker, marker + "\n" + mock, 1), encoding="utf-8")
    test_inventory.chmod(0o700)
    env = os.environ.copy()
    env["ACS_TEST_LOG"] = str(tmp_path / "license-commands.log")
    result = subprocess.run(["bash", str(test_inventory)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    inventory_dirs = sorted((tmp_path / "inventory").glob("*"))
    assert inventory_dirs
    license_state = json.loads((inventory_dirs[-1] / "license.json").read_text(encoding="utf-8"))
    assert license_state["status"] == "unassessed"
    assert "tenant entitlement evidence" in license_state["reason"]
    commands = (tmp_path / "license-commands.log").read_text(encoding="utf-8").splitlines()
    assert not any(line == "license" or line.startswith("license ") for line in commands)


def test_generated_audit_reads_both_families_without_mutation(tmp_path: Path) -> None:
    rendered = _render(tmp_path)
    result = _run_mocked(rendered / "audit.sh", tmp_path)
    # The mock returns empty live lists, so the planned subnets must be reported
    # as a mismatch after both read-only observations complete.
    assert result.returncode == 1, result.stderr
    assert "MISMATCH:" in result.stdout
    commands = (tmp_path / "commands.log").read_text(encoding="utf-8").splitlines()
    assert commands == [
        "ip-allowlist describe search-api",
        "ip-allowlist-v6 describe search-api",
    ]
    malformed = _run_mocked(rendered / "audit.sh", tmp_path, malformed=True)
    assert malformed.returncode == 2
    assert "INCOMPLETE:" in malformed.stderr
    commands = (tmp_path / "commands.log").read_text(encoding="utf-8")
    assert "create" not in commands and "delete" not in commands
