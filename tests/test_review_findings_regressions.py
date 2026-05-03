"""Focused regressions for review findings fixed after large skill updates."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ACS_RENDERER = REPO_ROOT / "skills/splunk-cloud-acs-allowlist-setup/scripts/render_assets.py"
IDXC_SETUP = REPO_ROOT / "skills/splunk-indexer-cluster-setup/scripts/setup.sh"
SOAR_SETUP = REPO_ROOT / "skills/splunk-soar-setup/scripts/setup.sh"


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_acs_fedramp_preflight_parser_reads_stdin_once() -> None:
    renderer = load_module(ACS_RENDERER)
    script = renderer.render_preflight(
        {
            "cloud_provider": "aws",
            "target_search_head": "",
            "allow_acs_lockout": False,
        }
    )

    assert "raw = sys.stdin.read()" in script
    assert "json.loads(raw) if raw.strip()" in script
    assert "json.load(sys.stdin) if sys.stdin.read()" not in script


def test_indexer_cluster_migration_phases_require_wrapper_inputs(tmp_path: Path) -> None:
    base = [
        "bash",
        str(IDXC_SETUP),
        "--cluster-manager-uri",
        "https://cm.example.com:8089",
        "--output-dir",
        str(tmp_path),
    ]
    cases = [
        ("replace-manager", [], "--new-manager-uri"),
        ("decommission-site", [], "--site"),
        ("move-peer-to-site", ["--peer-host", "idx01.example.com"], "--new-site"),
        ("migrate-non-clustered", [], "--indexer-host"),
    ]

    for phase, extra_args, expected_flag in cases:
        result = subprocess.run(
            [*base, "--phase", phase, *extra_args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert expected_flag in result.stdout + result.stderr


def test_indexer_cluster_setup_exports_phase_inputs() -> None:
    text = IDXC_SETUP.read_text(encoding="utf-8")

    assert "export NEW_MANAGER_URI" in text
    assert "export SITE" in text
    assert "export PEER_HOST PEER_SSH_USER NEW_SITE" in text
    assert "export INDEXER_HOST" in text


def test_soar_automation_broker_requires_file_based_token(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "bash",
            str(SOAR_SETUP),
            "--phase",
            "automation-broker",
            "--soar-tenant-url",
            "https://example.splunkcloudgc.com/soar",
            "--output-dir",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "--soar-automation-token-file" in result.stdout + result.stderr


def test_soar_setup_exports_automation_broker_env() -> None:
    text = SOAR_SETUP.read_text(encoding="utf-8")

    assert "--soar-automation-token-file|--automation-token-file" in text
    assert "SOAR_AUTOMATION_TOKEN_FILE=\"$(resolve_abs_path" in text
    assert "export SOAR_TENANT_URL SOAR_AUTOMATION_TOKEN_FILE" in text
