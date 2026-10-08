"""Regressions for Cisco AppDynamics completion validation."""

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "skills/cisco-appdynamics-setup/scripts/validate.sh"


def test_validator_requires_exact_package_owned_view_set() -> None:
    source = VALIDATOR.read_text(encoding="utf-8")
    for view in (
        "audit_log",
        "configuration",
        "dashboard",
        "events",
        "home",
        "ingestion_statistics",
        "inputs",
        "license_usage",
        "status",
        "troubleshooting",
    ):
        assert f'"{view}"' in source
    assert 'acl.get("app") != "Splunk_TA_AppDynamics"' in source
    assert 'content.get("is_visible", content.get("isVisible", True))' in source


def test_validator_does_not_use_total_view_count_as_completion_evidence() -> None:
    source = VALIDATOR.read_text(encoding="utf-8")
    assert 'print(len(json.load(sys.stdin).get("entry", [])))' not in source
    assert "Built-in views are visible: ${view_count}" not in source
    assert "Package-owned shipped views incomplete" in source


def _run_view_validator(tmp_path: Path, payload: dict) -> str:
    source = VALIDATOR.read_text(encoding="utf-8")
    start = source.index("validate_package_owned_views() {")
    end = source.index("\n}\n\nlog \"\"", start) + 2
    function = source[start:end]
    script = tmp_path / "validate-views.sh"
    script.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f"SK=mock SPLUNK_URI=https://example.test:8089 APP_NAME=Splunk_TA_AppDynamics\n"
        f"splunk_curl() {{ cat <<'JSON'\n{json.dumps(payload)}\nJSON\n}}\n"
        f"{function}\nvalidate_package_owned_views\n",
        encoding="utf-8",
    )
    script.chmod(0o700)
    result = subprocess.run(
        ["bash", str(script)],
        env=os.environ.copy(),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_view_validator_ignores_inherited_views_and_allows_hidden_home(tmp_path: Path) -> None:
    names = (
        "audit_log", "configuration", "dashboard", "events", "home",
        "ingestion_statistics", "inputs", "license_usage", "status",
        "troubleshooting",
    )
    entries = [
        {
            "name": name,
            "acl": {"app": "Splunk_TA_AppDynamics"},
            "content": {"is_visible": False if name == "home" else True},
        }
        for name in names
    ]
    entries += [
        {"name": f"inherited_{i}", "acl": {"app": "search"}, "content": {}}
        for i in range(54)
    ]
    assert _run_view_validator(tmp_path, {"entry": entries}) == "10|10|9|9||0"


def test_view_validator_rejects_missing_or_wrongly_owned_view(tmp_path: Path) -> None:
    payload = {
        "entry": [
            {
                "name": "status",
                "acl": {"app": "search"},
                "content": {"is_visible": True},
            }
        ]
    }
    result = _run_view_validator(tmp_path, payload)
    assert result.startswith("0|10|0|9|")
    assert "status" in result
