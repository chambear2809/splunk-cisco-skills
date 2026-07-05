"""Regression coverage for repo-wide product and feature coverage contracts."""

from __future__ import annotations

import json
import subprocess
import sys

from tests.regression_helpers import REPO_ROOT


AUDIT = REPO_ROOT / "skills/shared/scripts/audit_product_feature_coverage.py"


def test_product_feature_coverage_contract_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(AUDIT), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["summary"]["app_registry:apps"] == payload["summary"]["app_registry:routed_apps"]
    assert payload["summary"]["router_contracts:covered"] == payload["summary"]["router_contracts:expected"]
