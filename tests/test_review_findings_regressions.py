"""Focused regressions for review findings fixed after large skill updates."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ACS_RENDERER = REPO_ROOT / "skills/splunk-cloud-acs-admin-setup/scripts/render_assets.py"
ACS_ALLOWLIST_RENDERER = REPO_ROOT / "skills/splunk-cloud-acs-allowlist-setup/scripts/render_assets.py"
IDXC_SETUP = REPO_ROOT / "skills/splunk-indexer-cluster-setup/scripts/setup.sh"
IDXC_RENDERER = REPO_ROOT / "skills/splunk-indexer-cluster-setup/scripts/render_assets.py"
SOAR_SETUP = REPO_ROOT / "skills/splunk-soar-setup/scripts/setup.sh"


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_acs_fedramp_preflight_parser_fails_closed_on_invalid_status() -> None:
    renderer = load_module(ACS_RENDERER)
    script = renderer.render_preflight(
        {
            "cloud_provider": "aws",
            "acs_server": "https://admin.splunk.com",
            "target_stack": "stack-rendered",
            "target_search_head": "",
            "allow_acs_lockout": False,
        }
    )

    assert "read_acs_status_payload" in script
    assert "parse_acs_status_metadata" in script
    assert "if not text.strip()" in script
    assert "raise SystemExit(1)" in script
    assert "invalid or incomplete stack status" in script
    assert "|| printf '%s' '{}'" not in script


def test_acs_rendered_status_and_allowlist_observations_do_not_fall_back_to_empty() -> None:
    plans = (
        (
            load_module(ACS_RENDERER),
            {
                "cloud_provider": "aws",
                "acs_server": "https://admin.splunk.com",
                "target_stack": "stack-rendered",
                "target_search_head": "",
                "allow_acs_lockout": False,
                "strict_drift": True,
                "modules": ["allowlists"],
                "features": {"search-api": {"ipv4": ["198.51.100.0/24"], "ipv6": []}},
            },
        ),
        (
            load_module(ACS_ALLOWLIST_RENDERER),
            {
                "cloud_provider": "aws",
                "acs_server": "https://admin.splunk.com",
                "target_stack": "stack-rendered",
                "target_search_head": "",
                "allow_acs_lockout": False,
                "strict_drift": True,
                "features": {"search-api": {"ipv4": ["198.51.100.0/24"], "ipv6": []}},
            },
        ),
    )

    for renderer, plan in plans:
        scripts = (
            renderer.render_preflight(plan),
            renderer.render_apply(plan, ipv6=False),
            renderer.render_audit(plan),
        )
        for script in scripts:
            assert "read_acs_allowlist_payload" in script
            assert "parse_acs_allowlist_subnets" in script
            assert "except Exception:\n    print('')" not in script
        wait_script = renderer.render_wait_for_ready(plan)
        assert "acs_stack_status_snapshot" in wait_script
        assert "readiness was not verified" in wait_script
        assert "|| printf '%s' '{}'" not in wait_script
        assert '[[ "${restart_required}" == "true" ]]' in wait_script


def test_acs_admin_apply_requires_verified_absence_and_restart_observation() -> None:
    renderer = load_module(ACS_RENDERER)
    empty_lists = {
        "users": [],
        "app_permissions": [],
        "outbound_ports": [],
        "ddss_self_storage_locations": [],
        "limits": [],
        "private_connectivity": [],
    }
    plan = {
        "acs_server": "https://admin.splunk.com",
        "target_stack": "stack-rendered",
        "target_search_head": None,
        "operations": {
            **empty_lists,
            "indexes": [
                {
                    "name": "synthetic_index",
                    "datatype": "event",
                    "searchableDays": 90,
                    "maxDataSizeMB": 0,
                }
            ],
            "hec_tokens": [
                {
                    "name": "synthetic_hec",
                    "defaultIndex": "synthetic_index",
                    "allowedIndexes": ["synthetic_index"],
                    "disabled": False,
                    "useAck": False,
                }
            ],
            "roles": [{"name": "synthetic_role", "capabilities": ["search"]}],
            "maintenance_windows": {},
            "restarts": {"restartIfRequired": True, "forceRestart": False},
        }
    }

    script = renderer.render_apply_admin_plan(plan)

    assert "observe_acs_admin_resource indexes index synthetic_index" in script
    assert "observe_acs_admin_resource hec-token hec-token synthetic_hec" in script
    assert "observe_acs_admin_resource roles role synthetic_role" in script
    assert "absence was not verified" in script
    assert "if acs_command indexes describe" not in script
    assert "if acs_command hec-token describe" not in script
    assert "if acs_command roles describe" not in script
    assert 'if ! restart_required="$(acs_restart_required 2>/dev/null)"' in script
    assert "|| echo false" not in script
    assert "apply cannot be reported complete" in script


def test_acs_admin_inventory_marks_failed_captures_incomplete() -> None:
    renderer = load_module(ACS_RENDERER)
    script = renderer.render_inventory(
        {
            "acs_server": "https://admin.splunk.com",
            "target_stack": "stack-rendered",
            "target_search_head": None,
            "modules": ["indexes", "private-connectivity"],
        }
    )

    assert "inventory_incomplete=true" in script
    assert "empty or oversized response" in script
    assert "INCOMPLETE: ACS inventory contains unavailable or skipped observations" in script
    assert script.index('if [[ "${inventory_incomplete}" == "true" ]]') < script.index(
        'log "OK: ACS inventory snapshot saved'
    )


def test_acs_rendered_live_scripts_bind_target_search_head_before_context_prepare() -> None:
    admin_renderer = load_module(ACS_RENDERER)
    allowlist_renderer = load_module(ACS_ALLOWLIST_RENDERER)
    base_plan = {
        "cloud_provider": "aws",
        "acs_server": "https://admin.splunk.com",
        "target_stack": "stack-rendered",
        "target_search_head": "sh-i-rendered",
        "allow_acs_lockout": False,
        "strict_drift": True,
        "features": {"search-api": {"ipv4": ["198.51.100.0/24"], "ipv6": []}},
    }
    admin_plan = {
        **base_plan,
        "modules": ["allowlists", "indexes", "restarts", "private-connectivity"],
        "operations": {
            "indexes": [],
            "hec_tokens": [],
            "users": [],
            "roles": [],
            "app_permissions": [],
            "outbound_ports": [],
            "ddss_self_storage_locations": [],
            "limits": [],
            "maintenance_windows": {},
            "private_connectivity": [],
            "restarts": {"restartIfRequired": True, "forceRestart": False},
        },
    }

    scripts = (
        admin_renderer.render_preflight(admin_plan),
        admin_renderer.render_apply(admin_plan, ipv6=False),
        admin_renderer.render_wait_for_ready(admin_plan),
        admin_renderer.render_audit(admin_plan),
        admin_renderer.render_inventory(admin_plan),
        admin_renderer.render_apply_admin_plan(admin_plan),
        admin_renderer.render_private_connectivity_rest(admin_plan),
        allowlist_renderer.render_preflight(base_plan),
        allowlist_renderer.render_apply(base_plan, ipv6=False),
        allowlist_renderer.render_wait_for_ready(base_plan),
        allowlist_renderer.render_audit(base_plan),
    )
    prepare = "if ! acs_prepare_context; then"
    for script in scripts:
        assert "TARGET_STACK=stack-rendered" in script
        assert "TARGET_SH=sh-i-rendered" in script
        assert "ACS_BOUND_SERVER=https://admin.splunk.com" in script
        assert 'export ACS_BOUND_SPLUNK_CLOUD_STACK="${TARGET_STACK}"' in script
        assert 'export ACS_BOUND_SPLUNK_CLOUD_SEARCH_HEAD="${TARGET_SH}"' in script
        assert script.index("ACS_BOUND_SPLUNK_CLOUD_STACK") < script.index(prepare)
        assert "acs_command config use-stack" not in script


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
            "--target-stack",
            "stack-rendered",
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
    assert "acs_rest_curl" in private_rest
    assert "curl -fsS" not in private_rest
    assert '"feature": item["features"]' in private_rest
    assert '"features": [\n          "ingest"\n        ]' in plan
    assert '"restartIfRequired": false' in plan
    assert "user operations require password material and are handoff-only" in apply_admin


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
            "--target-stack",
            "stack-rendered",
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
            "--target-stack",
            "stack-rendered",
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
            "--target-stack",
            "stack-rendered",
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
            "--target-stack",
            "stack-rendered",
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


def test_indexer_cluster_bootstrap_uses_shared_pinned_ssh_policy(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "python3",
            str(IDXC_RENDERER),
            "--output-dir",
            str(tmp_path),
            "--cluster-manager-uri",
            "https://cm.example.com:8089",
            "--manager-hosts",
            "cm.example.com",
            "--peer-hosts",
            "idx01.example.com",
            "--replication-factor",
            "1",
            "--search-factor",
            "1",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    bootstrap = (tmp_path / "cluster/bootstrap/sequenced-bootstrap.sh").read_text(encoding="utf-8")
    assert "hbs_prepare_ssh_trust false" in bootstrap
    assert 'scp "${HBS_SSH_TRUST_ARGS[@]}"' in bootstrap
    assert 'ssh "${HBS_SSH_TRUST_ARGS[@]}"' in bootstrap
    assert "hbs_cleanup_ssh_trust" in bootstrap
    assert "StrictHostKeyChecking=accept-new" not in bootstrap


def test_soar_automation_broker_requires_file_based_token(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "bash",
            str(SOAR_SETUP),
            "--phase",
            "automation-broker",
            "--apply",
            "--soar-tenant-url",
            "https://customer.splunkcloudgc.com/soar",
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
