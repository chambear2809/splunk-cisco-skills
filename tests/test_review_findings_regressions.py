"""Focused regressions for review findings fixed after large skill updates."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ACS_RENDERER = REPO_ROOT / "skills/splunk-cloud-acs-admin-setup/scripts/render_assets.py"
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


def test_acs_admin_renderer_covers_broader_control_plane(tmp_path: Path) -> None:
    plan_file = tmp_path / "acs-admin-plan.json"
    plan_file.write_text(
        """
{
  "indexes": [{"name": "cisco_netops", "datatype": "event", "searchableDays": 90, "maxDataSizeMB": 0, "selfStorageBucketPath": "s3://bucket/prefix"}],
  "hec_tokens": [{"name": "cisco_netops_hec", "defaultIndex": "cisco_netops", "allowedIndexes": ["cisco_netops"], "disabled": "false", "useAck": "true"}],
  "roles": [{"name": "cisco_netops_role", "capabilities": ["search"], "srchIndexesAllowed": ["cisco_netops"]}],
  "users": [{"name": "cisco_netops_user", "roles": ["cisco_netops_role"], "passwordFile": "/tmp/password"}],
  "app_permissions": [{"name": "search", "read": ["user", "power"], "write": ["admin"]}],
  "outbound_ports": [{"port": 8089, "family": "ipv4", "subnets": ["198.51.100.10/32"]}],
  "ddss_self_storage_locations": [{"bucketName": "bucket-name", "title": "DDSS", "folder": "prefix"}],
  "limits": [{"stanza": "subsearch", "settings": {"maxout": "50000"}}],
  "maintenance_windows": {"preferencesFile": "/tmp/change-freezes.json"},
  "private_connectivity": [{"customerAccountIds": ["112233445566"], "feature": "ingest"}],
  "restarts": {"restartIfRequired": "false", "forceRestart": false}
}
""".strip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "python3",
            str(ACS_RENDERER),
            "--output-dir",
            str(tmp_path / "out"),
            "--admin-plan-file",
            str(plan_file),
            "--features",
            "search-api,hec",
            "--search-api-subnets",
            "198.51.100.0/24",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    render_dir = tmp_path / "out" / "acs-admin"
    assert (render_dir / "inventory.sh").is_file()
    apply_admin = (render_dir / "apply-admin-plan.sh").read_text(encoding="utf-8")
    private_rest = (render_dir / "private-connectivity-rest.sh").read_text(encoding="utf-8")
    commands = (render_dir / "admin-commands.sh").read_text(encoding="utf-8")
    plan = (render_dir / "plan.json").read_text(encoding="utf-8")

    assert "ACCEPT_ACS_ADMIN_MUTATION" in apply_admin
    assert "hec-token create" in commands
    assert "--disabled=false" in commands
    assert "--use-ack=true" in commands
    assert "private-connectivity" in private_rest
    assert '"feature": item["features"]' in private_rest
    assert '"features": [\n          "ingest"\n        ]' in plan
    assert '"restartIfRequired": false' in plan
    assert "User create/update operations were not applied" in apply_admin


def test_acs_admin_renderer_scopes_preflight_and_operations_to_modules(tmp_path: Path) -> None:
    plan_file = tmp_path / "acs-admin-plan.json"
    plan_file.write_text(
        '{"indexes":[{"name":"cisco_netops","datatype":"event"}]}',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "python3",
            str(ACS_RENDERER),
            "--output-dir",
            str(tmp_path / "out"),
            "--modules",
            "allowlists",
            "--admin-plan-file",
            str(plan_file),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "indexes requires module indexes" in result.stderr

    scoped = subprocess.run(
        [
            "python3",
            str(ACS_RENDERER),
            "--output-dir",
            str(tmp_path / "scoped"),
            "--modules",
            "limits,license,observability",
            "--admin-plan-file",
            str(tmp_path / "empty.json"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert scoped.returncode != 0
    assert "does not exist" in scoped.stderr

    (tmp_path / "empty.json").write_text("{}", encoding="utf-8")
    scoped = subprocess.run(
        [
            "python3",
            str(ACS_RENDERER),
            "--output-dir",
            str(tmp_path / "scoped"),
            "--modules",
            "limits,license,observability",
            "--admin-plan-file",
            str(tmp_path / "empty.json"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert scoped.returncode == 0, scoped.stdout + scoped.stderr
    preflight = (tmp_path / "scoped" / "acs-admin" / "preflight.sh").read_text(encoding="utf-8")
    inventory = (tmp_path / "scoped" / "acs-admin" / "inventory.sh").read_text(encoding="utf-8")
    apply_ipv4 = (tmp_path / "scoped" / "acs-admin" / "apply-ipv4.sh").read_text(encoding="utf-8")

    assert "REQUIRED_COMMAND_GROUPS=(license limits observability)" in preflight
    assert "command_group in indexes hec-token" not in preflight
    assert "acs_command license" in inventory
    assert "observability-handoff.json" in inventory
    assert "SKIP: allowlists module is disabled" in apply_ipv4


def test_acs_admin_renderer_rejects_direct_hec_token_secret(tmp_path: Path) -> None:
    plan_file = tmp_path / "acs-admin-plan.json"
    plan_file.write_text(
        '{"hec_tokens":[{"name":"bad","defaultIndex":"main","token":"SECRET"}]}',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "python3",
            str(ACS_RENDERER),
            "--output-dir",
            str(tmp_path / "out"),
            "--admin-plan-file",
            str(plan_file),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "must not contain token or tokenFile" in result.stderr


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
