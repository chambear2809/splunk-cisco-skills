from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "skills/shared/scripts/validate_render_first_skill.sh"


def _view_parser() -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r'dashboard_count="\$\(printf .*?python3 -c \'(.*?)\' "\$\{APP_NAME\}"\)"',
        source,
        re.DOTALL,
    )
    assert match, "view ownership parser is missing"
    return match.group(1)


def _count(payload: object, app: str = "lookup_editor") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _view_parser(), app],
        input=__import__("json").dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )


def test_counts_only_exact_acl_owned_views() -> None:
    payload = {
        "entry": [
            {"content": {"eai:acl.app": "lookup_editor"}},
            {"content": {"eai:acl.app": "other_app"}},
            {"content": {"eai:acl": {"app": "lookup_editor"}}},
            {"acl": {"app": "lookup_editor"}, "content": {}},
            {"content": {"eai:acl.app": None}},
        ]
    }
    result = _count(payload)
    assert result.returncode == 0
    assert result.stdout == "3"


def test_global_only_other_app_does_not_qualify() -> None:
    result = _count({"entry": [{"content": {"eai:acl.app": "other_app"}}]})
    assert result.returncode == 0
    assert result.stdout == "0"


def test_conflicting_acl_shapes_fail_closed() -> None:
    payload = {
        "entry": [
            {
                "content": {"eai:acl.app": "other_app"},
                "acl": {"app": "lookup_editor"},
            }
        ]
    }
    result = _count(payload)
    assert result.returncode == 0
    assert result.stdout == "0"


def test_missing_or_malformed_response_fails_closed() -> None:
    for payload in ({}, {"entry": None}, {"entry": "bad"}, {"entry": ["bad"]}):
        result = _count(payload)
        assert result.returncode == 0
        assert result.stdout == ("0" if isinstance(payload.get("entry"), list) else "INVALID")


def test_require_dashboard_enables_owned_view_check_without_completion_broadening() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'if [[ "${REQUIRE_DASHBOARD}" == "true" ]]; then' in source
    assert '"${REQUIRE_DASHBOARD}" == "true" || "${COMPLETION}" == "true"' not in source
    assert 'content.get("eai:acl.app")' in source
    assert 'content["eai:acl"].get("app")' in source
