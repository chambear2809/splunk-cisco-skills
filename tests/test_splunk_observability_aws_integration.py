"""Regressions for the Splunk Observability Cloud <-> AWS integration skill.

Covers (lines map to corrections recorded in the plan):

- Render succeeds for the default spec; numbered plan files exist.
- Coverage statuses for every section.
- IAM JSON shape (Version + Statement[]); foundation/polling/streams/tag-sync
  + Cassandra special-case ARN list.
- REST payload conversion: seconds (spec) -> milliseconds (raw API).
- The two distinct namespace-sync arrays (`namespaceSyncRules` for built-in
  AWS namespaces vs `customNamespaceSyncRules` for custom).
- Conflict-matrix enforcement: services vs namespace_sync_rules,
  customCloudwatchNamespaces vs customNamespaceSyncRules,
  metricStreamsManagedExternally requires useMetricStreamsSync.
- Realm rejection: us2-gcp.
- regions: [] rejected (no override flag).
- enableLogsSync rejected with hard error pointing to Splunk_TA_AWS handoff.
- GovCloud / China regions force authentication.mode=security_token.
- CFN template URL: regional vs StackSets.
- Multi-account: N integrations + StackSets.
- Hand-off scripts only render when the corresponding `handoffs.*` is true.
- Splunk Add-on for AWS minimum version (8.1.1) and Lambda layer publisher
  (254067382080) appear in their respective handoff scripts.
- No secret leak in any rendered file (JWT-looking blobs, Bearer tokens, AKIA
  AWS keys, aws_secret_access_key literals).
- setup.sh chmod-600 enforcement and reject-direct-secret behaviour.
- aws_integration_api.py reject-direct-secret behaviour and X-SF-Token header.
- smoke_offline.sh end-to-end exit 0.
- validate.sh --json shape.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import urllib.parse
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills/splunk-observability-aws-integration"
SCRIPTS_DIR = SKILL_DIR / "scripts"
SETUP = SCRIPTS_DIR / "setup.sh"
TEMPLATE = SKILL_DIR / "template.example"


def _load_renderer():
    spec = importlib.util.spec_from_file_location(
        "soai_render_assets", SCRIPTS_DIR / "render_assets.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_apply_state():
    spec = importlib.util.spec_from_file_location(
        "soai_apply_state", SCRIPTS_DIR / "_apply_state.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_api_client():
    spec = importlib.util.spec_from_file_location(
        "soai_aws_integration_api", SCRIPTS_DIR / "aws_integration_api.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _spec(**overrides):
    base = {
        "api_version": "splunk-observability-aws-integration/v1",
        "realm": "us0",
        "integration_name": "test-aws",
        "authentication": {
            "mode": "external_id",
            "aws_account_id": "123456789012",
            "iam_role_name": "TestSplunkRole",
        },
        "regions": ["us-east-1"],
        "services": {"mode": "explicit", "explicit": ["AWS/EC2"]},
        "metric_streams": {"use_metric_streams_sync": True, "cloudformation": True},
    }
    base.update(overrides)
    return base


def _rendered_text(root: Path) -> str:
    chunks: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


# --- Render success ---------------------------------------------------------


def test_render_succeeds_for_default_spec(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    result = renderer.render(spec, tmp_path)
    for name, _ in renderer.NUMBERED_PLAN_FILES:
        assert (tmp_path / name).exists(), f"missing {name}"
    assert (tmp_path / "README.md").exists()
    assert (tmp_path / "architecture.mmd").exists()
    assert (tmp_path / "coverage-report.json").exists()
    assert (tmp_path / "apply-plan.json").exists()
    assert (tmp_path / "payloads/integration-create.json").exists()
    assert (tmp_path / "iam/iam-foundation.json").exists()
    assert (tmp_path / "iam/iam-combined.json").exists()
    assert (tmp_path / "aws/cloudformation-stub.sh").exists()
    assert (tmp_path / "aws/main.tf").exists()
    assert (tmp_path / "scripts/apply-integration.sh").exists()
    assert (tmp_path / "scripts/validate-live.sh").exists()
    assert (tmp_path / "state/apply-state.json").exists()
    assert "coverage" in result["coverage_summary"]["by_status"] or any(
        result["coverage_summary"]["by_status"].values()
    )


def test_render_uses_template_example(tmp_path: Path) -> None:
    """The bundled template.example must render cleanly (used by smoke_offline.sh)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "render_assets.py"),
         "--spec", str(TEMPLATE), "--output-dir", str(tmp_path), "--json"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["coverage_summary"]["total"] > 0


# --- Coverage statuses ------------------------------------------------------


def test_coverage_keys_match_section_order(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    coverage = renderer.coverage_for(spec)
    sections_seen = {k.split(".")[0] for k in coverage}
    expected_section_prefixes = {
        "prerequisites", "authentication", "connection", "regions_services",
        "namespaces", "metric_streams", "private_link", "multi_account",
        "validation", "handoff",
    }
    assert sections_seen == expected_section_prefixes


# --- IAM JSON shape ---------------------------------------------------------


def test_iam_policies_have_version_and_statements(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    renderer.render(spec, tmp_path)
    for name in ("iam-foundation.json", "iam-polling.json", "iam-streams.json", "iam-tag-sync.json", "iam-combined.json"):
        body = json.loads((tmp_path / "iam" / name).read_text())
        assert body["Version"] == "2012-10-17"
        assert isinstance(body["Statement"], list) and body["Statement"]


def test_cassandra_uses_explicit_resource_arns(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    renderer.render(spec, tmp_path)
    body = json.loads((tmp_path / "iam/iam-tag-sync.json").read_text())
    cassandra_statements = [
        s for s in body["Statement"] if "cassandra:Select" in (s.get("Action") if isinstance(s.get("Action"), list) else [s.get("Action")])
    ]
    assert cassandra_statements, "Cassandra statement missing"
    resources = cassandra_statements[0]["Resource"]
    assert isinstance(resources, list), "Cassandra Resource must be a list (not '*')"
    assert all(r.startswith("arn:aws:cassandra:") for r in resources)


def test_iam_streams_pass_role_scoped_to_splunk_metric_streams(tmp_path: Path) -> None:
    renderer = _load_renderer()
    body = renderer.render_iam_streams_policy()
    pass_role = next(s for s in body["Statement"] if "iam:PassRole" in (s.get("Action") if isinstance(s.get("Action"), list) else [s.get("Action")]))
    assert pass_role["Resource"] == "arn:aws:iam::*:role/splunk-metric-streams*"


# --- REST payload conversion ------------------------------------------------


def test_rest_payload_uses_milliseconds_for_poll_rates(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(connection={"mode": "polling", "poll_rate_seconds": 60, "metadata_poll_rate_seconds": 600, "adaptive_polling": {"enabled": True, "inactive_seconds": 60}}))
    payload = renderer.render_rest_payload(spec)
    assert payload["pollRate"] == 60_000
    assert payload["metadataPollRate"] == 600_000
    assert payload["inactiveMetricsPollRate"] == 60_000


def test_rest_payload_emits_two_distinct_sync_rule_arrays(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(
        services={"mode": "namespace_filtered", "explicit": [], "namespace_sync_rules": [
            {"namespace": "AWS/EC2", "filter_action": "Include", "filter_source": "filter('env', 'prod')", "default_action": "Exclude"}
        ]},
        custom_namespaces={"simple_list": [], "sync_rules": [
            {"namespace": "MyApp", "filter_action": "Include", "filter_source": "filter('env', 'prod')", "default_action": "Exclude"}
        ]},
    ))
    payload = renderer.render_rest_payload(spec)
    assert "namespaceSyncRules" in payload
    assert "customNamespaceSyncRules" in payload
    assert payload["namespaceSyncRules"][0]["namespace"] == "AWS/EC2"
    assert payload["customNamespaceSyncRules"][0]["namespace"] == "MyApp"


# --- Conflict matrix --------------------------------------------------------


def test_services_explicit_conflicts_with_namespace_sync_rules() -> None:
    renderer = _load_renderer()
    with pytest.raises(renderer.RenderError, match="conflict"):
        renderer.validate_spec(_spec(
            services={"mode": "explicit", "explicit": ["AWS/EC2"], "namespace_sync_rules": [
                {"namespace": "AWS/EC2", "filter_action": "Include", "filter_source": "filter('env', 'prod')"}
            ]},
        ))


def test_custom_simple_list_conflicts_with_sync_rules() -> None:
    renderer = _load_renderer()
    with pytest.raises(renderer.RenderError, match="conflict"):
        renderer.validate_spec(_spec(
            custom_namespaces={"simple_list": ["CWAgent"], "sync_rules": [
                {"namespace": "MyApp", "filter_action": "Include", "filter_source": "filter('env', 'prod')"}
            ]},
        ))


def test_managed_externally_requires_use_metric_streams_sync() -> None:
    renderer = _load_renderer()
    with pytest.raises(renderer.RenderError, match="use_metric_streams_sync=true"):
        renderer.validate_spec(_spec(
            metric_streams={"use_metric_streams_sync": False, "managed_externally": True},
        ))


# --- Realm / region rules ---------------------------------------------------


def test_us2_gcp_realm_rejected() -> None:
    renderer = _load_renderer()
    with pytest.raises(renderer.RenderError, match="us2-gcp"):
        renderer.validate_spec(_spec(realm="us2-gcp"))


def test_empty_regions_rejected_no_override() -> None:
    renderer = _load_renderer()
    with pytest.raises(renderer.RenderError, match="regions cannot be empty"):
        renderer.validate_spec(_spec(regions=[]))


def test_govcloud_region_forces_security_token_auth() -> None:
    renderer = _load_renderer()
    with pytest.raises(renderer.RenderError, match="security_token"):
        renderer.validate_spec(_spec(
            regions=["us-gov-east-1"],
            authentication={"mode": "external_id", "aws_account_id": "123456789012"},
        ))


# --- Deprecated / rejected fields ------------------------------------------


def test_enable_logs_sync_rejected_with_handoff_pointer() -> None:
    renderer = _load_renderer()
    with pytest.raises(renderer.RenderError, match="Splunk_TA_AWS|splunkbase 1876|Splunkbase 1876"):
        renderer.validate_spec(_spec(enable_logs_sync=True))


# --- CloudFormation stub ----------------------------------------------------


def test_cfn_regional_url_is_default(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    renderer.render(spec, tmp_path)
    stub = (tmp_path / "aws/cloudformation-stub.sh").read_text()
    assert "template_metric_streams_regional.yaml" in stub
    assert "o11y-public.s3.amazonaws.com" in stub


def test_cfn_stacksets_url_when_use_stack_sets(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(metric_streams={
        "use_metric_streams_sync": True,
        "cloudformation": True,
        "use_stack_sets": True,
    }))
    renderer.render(spec, tmp_path)
    stub = (tmp_path / "aws/cloudformation-stub.sh").read_text()
    assert "template_metric_streams.yaml" in stub
    assert "create-stack-set" in stub


def test_cfn_template_url_rejects_shell_injection_and_quotes_valid_url(
    tmp_path: Path,
) -> None:
    renderer = _load_renderer()
    with pytest.raises(renderer.RenderError, match="absolute https"):
        renderer.validate_spec(
            _spec(
                metric_streams={
                    "use_metric_streams_sync": True,
                    "cloudformation": True,
                    "cloudformation_template_url": (
                        "https://example.test/template.yaml; touch /tmp/injected"
                    ),
                }
            )
        )

    custom_url = "https://example.test/templates/template;reviewed.yaml"
    spec = renderer.validate_spec(
        _spec(
            metric_streams={
                "use_metric_streams_sync": True,
                "cloudformation": True,
                "cloudformation_template_url": custom_url,
            }
        )
    )
    renderer.render(spec, tmp_path)
    stub = (tmp_path / "aws/cloudformation-stub.sh").read_text(encoding="utf-8")
    assert f"--template-url '{custom_url}'" in stub


def test_streams_rollback_quotes_output_path_without_command_execution(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "command-substitution-ran"
    hostile_output = f"$(touch {marker})"

    result = subprocess.run(
        [
            "bash",
            str(SETUP),
            "--rollback",
            "streams",
            "--output-dir",
            hostile_output,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert "\\$\\(" in result.stdout


# --- Multi-account ----------------------------------------------------------


def test_multi_account_requires_control_and_member_accounts() -> None:
    renderer = _load_renderer()
    with pytest.raises(renderer.RenderError, match="control_account_id"):
        renderer.validate_spec(_spec(multi_account={"enabled": True}))
    with pytest.raises(renderer.RenderError, match="member_accounts"):
        renderer.validate_spec(_spec(multi_account={"enabled": True, "control_account_id": "123"}))


def test_multi_account_renders_stacksets_stub(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(multi_account={
        "enabled": True,
        "control_account_id": "111111111111",
        "member_accounts": [{"aws_account_id": "222222222222", "label": "prod"}],
    }))
    renderer.render(spec, tmp_path)
    stub = (tmp_path / "aws/cloudformation-stacksets-stub.sh").read_text()
    assert "template_metric_streams.yaml" in stub


def test_multi_account_label_rejects_rendered_text_injection() -> None:
    renderer = _load_renderer()
    with pytest.raises(renderer.RenderError, match="label"):
        renderer.validate_spec(_spec(multi_account={
            "enabled": True,
            "control_account_id": "111111111111",
            "member_accounts": [{
                "aws_account_id": "222222222222",
                "label": "prod\n| injected |",
            }],
        }))


# --- Hand-off scripts -------------------------------------------------------


def test_handoff_logs_includes_splunk_ta_aws_min_version(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(handoffs={
        "logs_via_splunk_ta_aws": True,
        "lambda_apm": False,
        "dashboards": False,
        "detectors": False,
        "otel_collector_for_ec2_eks": False,
    }))
    renderer.render(spec, tmp_path)
    body = (tmp_path / "scripts/handoff-logs-splunk-ta-aws.sh").read_text()
    assert "1876" in body
    assert "8.1.1" in body
    assert "Splunk_TA_amazon_security_lake" in body


def test_handoff_lambda_apm_includes_publisher_account(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(handoffs={
        "logs_via_splunk_ta_aws": False,
        "lambda_apm": True,
        "dashboards": False,
        "detectors": False,
        "otel_collector_for_ec2_eks": False,
    }))
    renderer.render(spec, tmp_path)
    body = (tmp_path / "scripts/handoff-lambda-apm.sh").read_text()
    assert "254067382080" in body


def test_handoff_scripts_omitted_when_disabled(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    renderer.render(spec, tmp_path)
    for name in ("handoff-logs-splunk-ta-aws.sh", "handoff-lambda-apm.sh", "handoff-dashboards.sh", "handoff-detectors.sh", "handoff-otel-collector.sh"):
        assert not (tmp_path / "scripts" / name).exists(), f"{name} should not render when handoff is disabled"


# --- Secret-leak scan -------------------------------------------------------


SECRET_RE = re.compile(
    r"eyJ[A-Za-z0-9._-]{20,}|Bearer\s+[A-Za-z0-9._-]{12,}|AKIA[0-9A-Z]{16}|aws_secret_access_key\s*[:=]\s*[A-Za-z0-9/+=]{20,}"
)


def test_no_secret_leak_in_default_render(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    renderer.render(spec, tmp_path)
    text = _rendered_text(tmp_path)
    matches = SECRET_RE.findall(text)
    assert not matches, f"secret-looking content in render: {matches[:5]}"


# --- setup.sh subprocess assertions ----------------------------------------


def test_setup_sh_help_lists_five_modes() -> None:
    out = subprocess.run(["bash", str(SETUP), "--help"], capture_output=True, text=True)
    assert out.returncode == 0
    for mode in ("--render", "--apply", "--discover", "--doctor", "--quickstart"):
        assert mode in out.stdout


def test_setup_sh_rejects_direct_secret_flag() -> None:
    out = subprocess.run(["bash", str(SETUP), "--token", "leak"], capture_output=True, text=True)
    assert out.returncode == 2
    assert "Refusing direct-secret flag --token" in out.stderr
    assert "--token-file" in out.stderr


def test_setup_sh_rejects_aws_secret_access_key() -> None:
    out = subprocess.run(["bash", str(SETUP), "--aws-secret-access-key", "leak"], capture_output=True, text=True)
    assert out.returncode == 2
    assert "Refusing direct-secret flag --aws-secret-access-key" in out.stderr


def test_setup_sh_chmod_600_enforced(tmp_path: Path) -> None:
    token = tmp_path / "loose-token"
    token.write_text("dummy")
    os.chmod(token, 0o644)
    out = subprocess.run(
        ["bash", str(SETUP), "--apply", "integration", "--realm", "us0", "--token-file", str(token)],
        capture_output=True, text=True,
    )
    assert out.returncode == 2
    assert "loose permissions" in out.stderr


def test_setup_sh_chmod_600_passes(tmp_path: Path) -> None:
    """Passing --apply integration with chmod 600 reaches the API client (which then fails on the dummy token, but that's after the chmod gate)."""
    token = tmp_path / "good-token"
    token.write_text("dummy")
    os.chmod(token, 0o600)
    # Run with --dry-run so we don't try to hit a real endpoint.
    out = subprocess.run(
        ["bash", str(SETUP), "--apply", "integration", "--dry-run",
         "--realm", "us0", "--token-file", str(token), "--output-dir", str(tmp_path / "rendered")],
        capture_output=True, text=True,
    )
    # The render+apply path runs; the API client should not complain about chmod.
    assert "loose permissions" not in out.stderr
    # In dry-run we expect the API client to print a "dry-run" result.
    assert out.returncode == 0 or "dry-run" in (out.stdout + out.stderr)


def test_setup_sh_rejects_symlink_even_with_loose_perms_override(tmp_path: Path) -> None:
    token = tmp_path / "token"
    token.write_text("dummy", encoding="utf-8")
    os.chmod(token, 0o600)
    link = tmp_path / "token-link"
    link.symlink_to(token)
    out = subprocess.run(
        [
            "bash",
            str(SETUP),
            "--apply",
            "integration",
            "--dry-run",
            "--realm",
            "us0",
            "--token-file",
            str(link),
            "--allow-loose-token-perms",
            "--output-dir",
            str(tmp_path / "rendered"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 2
    assert "regular, non-symlink" in out.stderr


# --- aws_integration_api.py CLI --------------------------------------------


def test_api_client_rejects_direct_secret_flag() -> None:
    out = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "aws_integration_api.py"),
         "--realm", "us0", "--token-file", "/tmp/x", "--state-dir", "/tmp/x",
         "--token", "leak", "list"],
        capture_output=True, text=True,
    )
    assert out.returncode == 2
    assert "FAIL: refusing direct-secret flag --token" in out.stdout


def test_api_client_uses_x_sf_token_header() -> None:
    body = (SCRIPTS_DIR / "aws_integration_api.py").read_text()
    assert '"X-SF-Token": token' in body or "'X-SF-Token': token" in body


def test_api_client_rejects_http_and_untrusted_https_hosts() -> None:
    api = _load_api_client()
    with pytest.raises(api.ApiError, match="https://api"):
        api._request("GET", "http://api.us0.observability.splunkcloud.com/v2/integration", "secret")
    with pytest.raises(api.ApiError, match="https://api"):
        api._request("GET", "https://attacker.example.test/v2/integration", "secret")
    with pytest.raises(api.ApiError, match="unsupported"):
        api._base_url("us0@attacker.example.test")


def test_api_client_redirect_handler_refuses_redirects() -> None:
    api = _load_api_client()
    handler = api._NoRedirectHandler()
    assert handler.redirect_request(
        None,
        None,
        302,
        "Found",
        {},
        "https://attacker.example.test/steal",
    ) is None


def _live_validation_fixture() -> tuple[dict, dict]:
    desired = {
        "type": "AWSCloudWatch",
        "name": "observability-staging",
        "authMethod": "ExternalId",
        "roleArn": "arn:aws:iam::123456789012:role/SplunkObservabilityStagingRole",
        "regions": ["us-east-1"],
        "services": ["AWS/EC2", "AWS/Lambda", "AWS/ApplicationELB"],
        "customCloudWatchNamespaces": ["ContainerInsights"],
        "metricStatsToSyncs": [],
        "pollRate": 300_000,
        "metadataPollRate": 900_000,
        "inactiveMetricsPollRate": 1_200_000,
        "importCloudWatch": True,
        "enableAwsUsage": False,
        "enableCheckLargeVolume": True,
        "syncCustomNamespacesOnly": False,
        "syncLoadBalancerTargetGroupTags": False,
        "ignoreAllStatusMetrics": False,
        "collectOnlyRecommendedStats": True,
        "useMetricStreamsSync": False,
        "metricStreamsManagedExternally": False,
    }
    live = {
        **desired,
        "id": "integration-id",
        "enabled": True,
        "metricStreamsSyncState": "DISABLED",
    }
    live.pop("useMetricStreamsSync")
    return desired, live


def test_api_client_live_validation_requires_exact_enabled_scope() -> None:
    api = _load_api_client()
    desired, live = _live_validation_fixture()
    assert api.validate_live_integration([live], desired, "123456789012")["id"] == "integration-id"

    with pytest.raises(api.ApiError, match="no live"):
        api.validate_live_integration([], desired, "123456789012")
    with pytest.raises(api.ApiError, match="multiple live"):
        api.validate_live_integration([live, dict(live)], desired, "123456789012")

    for field, value, message in (
        ("enabled", False, "not enabled"),
        ("authMethod", "SecurityToken", "authMethod"),
        ("regions", ["us-west-2"], "regions"),
        ("roleArn", "arn:aws:iam::999999999999:role/Other", "roleArn"),
        ("services", ["AWS/EC2"], "services"),
        ("customCloudWatchNamespaces", [], "customCloudWatchNamespaces"),
        ("pollRate", 60_000, "pollRate"),
        ("enableCheckLargeVolume", False, "enableCheckLargeVolume"),
        ("metricStreamsSyncState", "ENABLED", "polling-only"),
    ):
        changed = dict(live)
        changed[field] = value
        with pytest.raises(api.ApiError, match=message):
            api.validate_live_integration([changed], desired, "123456789012")

    missing_role = dict(live)
    missing_role.pop("roleArn")
    with pytest.raises(api.ApiError, match="roleArn"):
        api.validate_live_integration([missing_role], desired, "123456789012")


def test_api_client_paginates_filtered_integration_list(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_client()
    calls: list[dict[str, list[str]]] = []

    def fake_request(method: str, url: str, token: str):
        assert method == "GET"
        assert token == "token"
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        calls.append(query)
        offset = int(query["offset"][0])
        size = 1000 if offset == 0 else 1
        return {
            "count": 1001,
            "results": [
                {"type": "AWSCloudWatch", "name": f"integration-{offset + index}"}
                for index in range(size)
            ],
        }

    monkeypatch.setattr(api, "_request", fake_request)
    result = api.list_aws_integrations("us1", "token")
    assert len(result) == 1001
    assert len(calls) == 2
    assert all(call["type"] == ["AWSCloudWatch"] for call in calls)
    assert [call["offset"] for call in calls] == [["0"], ["1000"]]


def test_api_client_calls_credential_validation_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_client()
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        api,
        "_request",
        lambda method, url, token: calls.append((method, url, token)) or {},
    )
    api.validate_integration_credentials("us1", "token", "integration/id")
    assert calls == [
        (
            "GET",
            "https://api.us1.observability.splunkcloud.com/v2/integration/validate/integration%2Fid",
            "token",
        )
    ]


def test_api_client_strips_read_back_fields_on_put() -> None:
    api = _load_api_client()
    sample = {
        "name": "test", "type": "AWSCloudWatch",
        "metricStreamsSyncState": "ENABLED",
        "largeVolume": False,
        "created": 1234567890,
        "lastUpdated": 1234567890,
        "id": "ABC",
    }
    stripped = api._strip_read_back(sample)
    for field in api.READ_BACK_FIELDS:
        assert field not in stripped


def test_api_client_diff_returns_three_buckets() -> None:
    api = _load_api_client()
    spec_payload = {"name": "x", "regions": ["us-east-1"], "useMetricStreamsSync": True}
    live_payload = {"name": "x", "regions": ["us-east-1", "us-west-2"], "metricStreamsSyncState": "ENABLED"}
    result = api.diff(spec_payload, live_payload)
    assert "safe_to_converge" in result
    assert "operator_confirm_required" in result
    assert "adopt_from_live" in result


# --- _apply_state -----------------------------------------------------------


def test_apply_state_redacts_token_keys() -> None:
    apply_state = _load_apply_state()
    sample = {"x_sf_token": "ABC", "AWS_SECRET_ACCESS_KEY": "XYZ", "external_id": "DEF"}
    redacted = apply_state.redact(sample)
    for k in sample:
        assert redacted[k] == "[REDACTED]"


def test_apply_state_secret_reader_requires_0600_and_rejects_symlink(
    tmp_path: Path,
) -> None:
    apply_state = _load_apply_state()
    token = tmp_path / "token"
    token.write_text("one-secret-line\n", encoding="utf-8")
    os.chmod(token, 0o600)
    assert apply_state.read_secret_file(token) == "one-secret-line"

    link = tmp_path / "token-link"
    link.symlink_to(token)
    with pytest.raises(PermissionError, match="non-symlink"):
        apply_state.read_secret_file(link, allow_loose=True)

    os.chmod(token, 0o640)
    with pytest.raises(PermissionError, match="loose permissions"):
        apply_state.read_secret_file(token)

    os.chmod(token, 0o600)
    hardlink = tmp_path / "token-hardlink"
    os.link(token, hardlink)
    with pytest.raises(PermissionError, match="exactly one hard link"):
        apply_state.read_secret_file(token, allow_loose=True)


def test_apply_state_secret_reader_is_bounded_and_double_checked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    apply_state = _load_apply_state()
    oversized = tmp_path / "oversized-token"
    oversized.write_bytes(b"x" * (apply_state.MAX_SECRET_BYTES + 1))
    os.chmod(oversized, 0o600)
    with pytest.raises(PermissionError, match="safety limit"):
        apply_state.read_secret_file(oversized)

    token = tmp_path / "racing-token"
    token.write_text("first-value\n", encoding="utf-8")
    os.chmod(token, 0o600)
    original_read = apply_state.os.read
    read_count = 0

    def racing_read(descriptor: int, size: int) -> bytes:
        nonlocal read_count
        chunk = original_read(descriptor, size)
        read_count += 1
        if read_count == 1:
            token.write_text("other-value\n", encoding="utf-8")
        return chunk

    monkeypatch.setattr(apply_state.os, "read", racing_read)
    with pytest.raises(PermissionError, match="changed while it was being read"):
        apply_state.read_secret_file(token)


@pytest.mark.parametrize(
    "bad_value",
    ["token\v", "token\f", "token\x1c", "token\u0085", "token\u2028", "token\u2029"],
)
def test_apply_state_token_parser_rejects_all_line_controls(
    tmp_path: Path,
    bad_value: str,
) -> None:
    apply_state = _load_apply_state()
    token = tmp_path / "controlled-token"
    token.write_text(bad_value, encoding="utf-8")
    os.chmod(token, 0o600)
    with pytest.raises(ValueError, match="printable-ASCII"):
        apply_state.read_secret_file(token)


def test_apply_state_token_parser_allows_only_one_optional_file_terminator(
    tmp_path: Path,
) -> None:
    apply_state = _load_apply_state()
    token = tmp_path / "terminated-token"
    for payload in (b"token-value", b"token-value\n", b"token-value\r\n"):
        token.write_bytes(payload)
        os.chmod(token, 0o600)
        assert apply_state.read_secret_file(token) == "token-value"
    token.write_bytes(b"token-value\n\n")
    os.chmod(token, 0o600)
    with pytest.raises(ValueError, match="at most one trailing"):
        apply_state.read_secret_file(token)


def test_apply_state_uses_private_unpredictable_atomic_temp_file(tmp_path: Path) -> None:
    apply_state = _load_apply_state()
    state_dir = tmp_path / "state"
    apply_state.append_step(
        state_dir,
        section="integration",
        step="create",
        idempotency_key="integration:create",
        result="success",
    )
    state_path = state_dir / "apply-state.json"
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    assert list(state_dir.glob(".apply-state.*")) == []
    source = (SCRIPTS_DIR / "_apply_state.py").read_text(encoding="utf-8")
    assert "NamedTemporaryFile" in source
    assert "os.getpid()" not in source


def test_rendered_state_is_private_and_accepts_first_append(tmp_path: Path) -> None:
    renderer = _load_renderer()
    apply_state = _load_apply_state()
    renderer.render(renderer.validate_spec(_spec()), tmp_path)
    state_dir = tmp_path / "state"
    state_path = state_dir / "apply-state.json"
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    apply_state.append_step(
        state_dir,
        section="integration",
        step="first-live-append",
        idempotency_key="integration:first-live-append",
        result="success",
    )
    assert apply_state.has_step(state_dir, "integration:first-live-append")


def test_apply_state_read_rejects_path_swap_to_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    apply_state = _load_apply_state()
    state_dir = tmp_path / "state"
    apply_state.append_step(
        state_dir,
        section="integration",
        step="trusted",
        idempotency_key="trusted",
        result="success",
    )
    state_path = state_dir / "apply-state.json"
    replacement = tmp_path / "replacement.json"
    replacement.write_text('{"steps": []}\n', encoding="utf-8")
    os.chmod(replacement, 0o600)
    original_open = apply_state.os.open

    def swapping_open(path, flags, *args, **kwargs):
        if Path(path) == state_path:
            state_path.unlink()
            state_path.symlink_to(replacement)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(apply_state.os, "open", swapping_open)
    with pytest.raises(PermissionError, match="safely|changed"):
        apply_state.has_step(state_dir, "trusted")


def test_generated_live_scripts_pin_repo_and_interpreter_paths(tmp_path: Path) -> None:
    renderer = _load_renderer()
    output = tmp_path / "rendered"
    renderer.render(renderer.validate_spec(_spec()), output)
    for name in ("apply-integration.sh", "validate-live.sh"):
        body = (output / "scripts" / name).read_text(encoding="utf-8")
        assert str(SKILL_DIR) in body
        assert str(Path(sys.executable).resolve()) in body
        assert ".venv/bin/python" not in body
        assert "RENDER_DIR}/../skills" not in body


# --- smoke_offline.sh + validate.sh ----------------------------------------


def test_smoke_offline_succeeds() -> None:
    out = subprocess.run(["bash", str(SCRIPTS_DIR / "smoke_offline.sh")], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr + out.stdout
    assert "smoke_offline: OK" in out.stdout


def test_validate_sh_json_output(tmp_path: Path) -> None:
    # First render so validate has files to check.
    subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "render_assets.py"),
         "--spec", str(TEMPLATE), "--output-dir", str(tmp_path)],
        check=True, capture_output=True,
    )
    out = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "validate.sh"), "--output-dir", str(tmp_path), "--json"],
        capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    payload = json.loads(out.stdout)
    assert payload["failures"] == []


def test_validate_sh_doctor_writes_report(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "render_assets.py"),
         "--spec", str(TEMPLATE), "--output-dir", str(tmp_path)],
        check=True, capture_output=True,
    )
    out = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "validate.sh"), "--output-dir", str(tmp_path), "--doctor"],
        capture_output=True, text=True,
    )
    assert out.returncode == 0
    assert (tmp_path / "doctor-report.md").exists()


# --- credentials.example documentation -------------------------------------


def test_credentials_example_mentions_o11y_token_file() -> None:
    body = (REPO_ROOT / "credentials.example").read_text()
    assert "SPLUNK_O11Y_TOKEN_FILE" in body
    assert "SPLUNK_O11Y_REALM" in body


# --- references library exists ---------------------------------------------


def test_required_reference_files_exist() -> None:
    expected = [
        "connection-options.md", "iam-permissions.md", "regions-and-realms.md",
        "cloudformation-templates.md", "terraform.md", "recommended-stats.yaml",
        "namespaces-catalog.md", "adaptive-polling.md", "metric-streams.md",
        "privatelink.md", "multi-account.md", "troubleshooting.md",
        "error-catalog.md", "api-fields.md", "handoffs.md",
    ]
    for name in expected:
        assert (SKILL_DIR / "references" / name).exists(), f"missing references/{name}"


def test_skill_md_frontmatter_well_formed() -> None:
    body = (SKILL_DIR / "SKILL.md").read_text()
    assert body.startswith("---\n")
    # Frontmatter ends with a `---\n` on its own line.
    assert "\n---\n" in body
    assert "name: splunk-observability-aws-integration" in body


def test_template_example_is_valid_yaml_per_validate_spec() -> None:
    renderer = _load_renderer()
    spec = renderer.load_spec(TEMPLATE)
    renderer.validate_spec(spec)
