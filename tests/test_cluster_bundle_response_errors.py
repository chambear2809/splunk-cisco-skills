"""Structured error handling for indexer cluster bundle REST responses."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HELPERS = REPO_ROOT / "skills/shared/lib/cluster_helpers.sh"


def run_helper(function: str, response: str) -> subprocess.CompletedProcess[str]:
    script = f"""
set -euo pipefail
source {HELPERS!s}
splunk_curl_post() {{ printf '%s' "$MOCK_RESPONSE"; }}
{function} 'https://cm.example:8089' 'session-key'
"""
    return subprocess.run(
        ["bash", "-c", script],
        cwd=REPO_ROOT,
        env={**os.environ, "PATH": "/usr/bin:/bin", "MOCK_RESPONSE": response},
        capture_output=True,
        text=True,
        check=False,
    )


def test_bundle_apply_rejects_http_200_structured_error() -> None:
    response = json.dumps({"messages": [{"type": "ERROR", "text": "Bundle validation is in progress."}]})
    result = run_helper("cluster_bundle_apply", response)
    assert result.returncode != 0
    assert "Bundle validation is in progress." in result.stdout + result.stderr


def test_bundle_validate_rejects_nested_structured_error() -> None:
    response = json.dumps({"entry": [{"content": {"messages": [{"severity": "ERROR", "message": "validation failed"}]}}]})
    result = run_helper("cluster_bundle_validate", response)
    assert result.returncode != 0
    assert "validation failed" in result.stdout + result.stderr


def test_bundle_apply_preserves_success_response() -> None:
    response = json.dumps({"messages": [{"type": "INFO", "text": "Bundle applied"}]})
    result = run_helper("cluster_bundle_apply", response)
    assert result.returncode == 0
    assert json.loads(result.stdout) == json.loads(response)


@pytest.mark.parametrize("response", ["", "not-json", "[]", "null", "42"])
def test_bundle_apply_rejects_malformed_empty_or_nonobject_json(response: str) -> None:
    result = run_helper("cluster_bundle_apply", response)
    assert result.returncode != 0
    assert "bundle response" in (result.stdout + result.stderr).lower()
