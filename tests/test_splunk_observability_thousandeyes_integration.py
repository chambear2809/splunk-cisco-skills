"""Regressions for splunk-observability-thousandeyes-integration rendering."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/splunk-observability-thousandeyes-integration/scripts/setup.sh"
TE_CLIENT_PATH = (
    REPO_ROOT
    / "skills/splunk-observability-thousandeyes-integration/scripts/te_api_client.py"
)
BUNDLE_MARKER = ".splunk-observability-thousandeyes-bundle.json"


def load_te_client():
    spec = importlib.util.spec_from_file_location("test_te_api_client", TE_CLIENT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TE_CLIENT = load_te_client()


def run_setup(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        ["bash", str(SETUP), *args],
        cwd=REPO_ROOT,
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def rendered_text(root: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def write_spec(path: Path, **overrides: object) -> Path:
    spec: dict[str, object] = {
        "api_version": "splunk-observability-thousandeyes-integration/v1",
        "realm": "us0",
        "account_group_id": "1234",
        "stream": {
            "enabled": True,
            "signal": "metric",
            "endpoint_type": "http",
            "data_model_version": "v2",
            "filters": {"test_types": ["http-server", "agent-to-server"]},
        },
        "apm_connector": {"enabled": True},
        "tests": [],
        "alert_rules": [],
        "labels": [],
        "tags": [],
        "te_dashboards": [],
        "templates": [],
        "dashboards": {"enabled": True},
        "detectors": {
            "enabled": True,
            "thresholds": {
                "agent-to-server": {"latency_ms_max": 200, "loss_pct_max": 1.0},
                "http-server": {"availability_floor": 0.99, "duration_p95_ms": 1000},
            },
        },
        "handoffs": {
            "dashboard_builder": True,
            "native_ops": True,
            "mcp_setup": True,
            "splunk_platform_ta": True,
        },
    }
    spec.update(overrides)
    path.write_text(json.dumps(spec, indent=2, sort_keys=True), encoding="utf-8")
    return path


def ensure_create_args(
    tmp_path: Path,
    *,
    identity_fields: str = "name",
    key: str = "asset",
) -> argparse.Namespace:
    tmp_path.mkdir(parents=True, exist_ok=True)
    payload = tmp_path / f"{key.replace(':', '-')}.json"
    payload.write_text(json.dumps({"name": "stable-asset", "type": "generic"}), encoding="utf-8")
    return argparse.Namespace(
        payload_file=str(payload),
        secret_placeholder="",
        secret_file="",
        value_placeholder="",
        value=None,
        identity_fields=identity_fields,
        identity_optional_fields="",
        identity_constant=[],
        id_keys="id",
        state_dir=str(tmp_path / "state"),
        key=key,
        collection_path="assets",
        create_path="assets",
        account_group_id="1234",
    )


def test_render_produces_payloads_and_handoffs(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--validate", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    for f in (
        "te-payloads/stream.json",
        "te-payloads/connector.json",
        "te-payloads/apm-operation.json",
        "dashboards/http-server.signalflow.yaml",
        "dashboards/agent-to-server.signalflow.yaml",
        "scripts/apply-stream.sh",
        "scripts/apply-apm-connector.sh",
        "scripts/te-api-client.py",
        "scripts/handoff-dashboards.sh",
        "scripts/handoff-detectors.sh",
        "scripts/handoff-mcp.sh",
        "scripts/handoff-ta.sh",
        "metadata.json",
    ):
        assert (output / f).is_file(), f"Missing rendered file: {f}"
    stream = json.loads((output / "te-payloads" / "stream.json").read_text(encoding="utf-8"))
    assert stream["type"] == "opentelemetry"
    assert stream["dataModelVersion"] == "v2"
    # X-SF-Token MUST be a placeholder, never an inline token value.
    assert stream["customHeaders"]["X-SF-Token"].startswith("${")
    # Stream URL must derive from spec.realm.
    assert stream["streamEndpointUrl"] == "https://ingest.us0.signalfx.com/v2/datapoint/otlp"


def test_render_does_not_require_configured_live_token_file(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    missing_token = tmp_path / "not-created-until-apply"

    result = run_setup(
        "--render",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
        env={"SPLUNK_O11Y_TOKEN_FILE": str(missing_token)},
    )

    assert result.returncode == 0, combined_output(result)
    assert (output / "te-payloads/stream.json").is_file()
    assert not missing_token.exists()


def test_template_handlebars_enforcement(tmp_path: Path) -> None:
    """TE Templates with plain-text credentials must fail render-time."""
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        templates=[
            {
                "name": "Bad template",
                "description": "...",
                "template_body": {
                    "credentials": {"api_key": "PLAINTEXT_SHOULD_BE_REJECTED"},
                },
            }
        ],
    )
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 1
    assert "Handlebars" in combined_output(result)
    assert "PLAINTEXT_SHOULD_BE_REJECTED" not in rendered_text(output) if output.exists() else True


def test_template_handlebars_placeholder_accepted(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        templates=[
            {
                "name": "Good template",
                "description": "...",
                "template_body": {
                    "credentials": {"api_key": "{{te_credentials.api_key}}"},
                },
            }
        ],
    )
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    assert (output / "te-payloads/templates/good-template.json").is_file()


@pytest.mark.parametrize(
    "flag", ["--te-token", "--o11y-token", "--access-token", "--token", "--bearer-token", "--api-token", "--sf-token"]
)
def test_direct_secret_flags_are_rejected(flag: str, tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), flag, "INLINE_SHOULD_NOT_LEAK")
    assert result.returncode == 1
    assert "-token-file" in combined_output(result)
    assert "INLINE_SHOULD_NOT_LEAK" not in combined_output(result)


def test_token_values_never_appear_in_rendered_output(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    te_token = tmp_path / "te-token"
    te_token.write_text("TE_BEARER_TOKEN_SHOULD_NOT_LEAK", encoding="utf-8")
    te_token.chmod(0o600)
    o11y_ingest = tmp_path / "o11y-ingest-token"
    o11y_ingest.write_text("O11Y_INGEST_TOKEN_SHOULD_NOT_LEAK", encoding="utf-8")
    o11y_ingest.chmod(0o600)
    o11y_api = tmp_path / "o11y-api-token"
    o11y_api.write_text("O11Y_API_TOKEN_SHOULD_NOT_LEAK", encoding="utf-8")
    o11y_api.chmod(0o600)
    result = run_setup(
        "--render",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
        "--te-token-file",
        str(te_token),
        "--o11y-ingest-token-file",
        str(o11y_ingest),
        "--o11y-api-token-file",
        str(o11y_api),
    )
    assert result.returncode == 0, combined_output(result)
    text = rendered_text(output)
    assert "TE_BEARER_TOKEN_SHOULD_NOT_LEAK" not in text
    assert "O11Y_INGEST_TOKEN_SHOULD_NOT_LEAK" not in text
    assert "O11Y_API_TOKEN_SHOULD_NOT_LEAK" not in text


def test_rendered_apply_path_uses_fixed_origin_client_and_keeps_token_values_off_argv(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)

    scripts = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((output / "scripts").glob("*.sh"))
    )
    forbidden = (
        'TE_TOKEN="$(cat "${TE_TOKEN_FILE}")"',
        'O11Y_API_TOKEN="$(cat "${O11Y_API_TOKEN_FILE}")"',
        '-H "Authorization: Bearer ${TE_TOKEN}"',
        '-H "X-SF-Token: ${O11Y_API_TOKEN}"',
        "os.environ['TE_TOKEN']",
    )
    for needle in forbidden:
        assert needle not in scripts
    assert 'TE_API_CLIENT="$(dirname "${BASH_SOURCE[0]}")/te-api-client.py"' in scripts
    assert '--token-file "${TE_TOKEN_FILE}"' in scripts
    assert "--secret-file \"${O11Y_INGEST_TOKEN_FILE}\"" in scripts
    assert "--secret-file \"${O11Y_API_TOKEN_FILE}\"" in scripts
    assert "TE_CURL_CONFIG" not in scripts

    client = (output / "scripts/te-api-client.py").read_text(encoding="utf-8")
    assert 'API_BASE = "https://api.thousandeyes.com/v7"' in client
    assert "class NoRedirectHandler" in client
    assert "urllib.parse.urlencode({'aid': account_group_id})" in client
    assert "response.status < 200 or response.status >= 300" in client
    assert "payload_sha256" in client

    signalflow = (output / "scripts/validate-signalflow.sh").read_text(encoding="utf-8")
    assert "curl -q --fail-with-body" in signalflow
    assert "--proto '=https' --proto-redir '=https' --max-redirs 0 --globoff" in signalflow
    assert "os.O_NOFOLLOW" in signalflow
    assert "os.O_EXCL" in signalflow
    assert "os.O_TRUNC" not in signalflow
    assert "st_nlink != 1" in signalflow
    assert "changed while it was read" in signalflow
    assert "tr -d" not in signalflow
    syntax = subprocess.run(
        ["bash", "-n", str(output / "scripts/validate-signalflow.sh")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr


def test_all_live_apply_scripts_require_mutation_acceptance_and_account_scope(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)

    for name in (
        "apply-stream.sh",
        "apply-apm-connector.sh",
        "apply-tests.sh",
        "apply-alert-rules.sh",
        "apply-template.sh",
    ):
        script = (output / "scripts" / name).read_text(encoding="utf-8")
        assert 'ACCEPT_TE_MUTATIONS:-false' in script
        assert 'TE_ACCOUNT_GROUP_ID="1234"' in script
        assert 'TE_API_CLIENT="$(dirname "${BASH_SOURCE[0]}")/te-api-client.py"' in script


def test_unproven_label_tag_and_te_dashboard_apply_surfaces_fail_closed(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        labels=[{"name": "checkout", "color": "#0066cc"}],
        tags=[{"name": "tier:1"}],
        te_dashboards=[{"name": "Checkout", "widgets": []}],
    )
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)

    labels_tags = (output / "scripts/apply-labels-tags.sh").read_text(encoding="utf-8")
    te_dashboards = (output / "scripts/apply-te-dashboards.sh").read_text(encoding="utf-8")
    for script in (labels_tags, te_dashboards):
        assert "disabled until authoritative ID/readback schemas are encoded" in script
        assert "no changes were made" in script
        assert "curl " not in script
        assert "ensure-create" not in script


@pytest.mark.parametrize(
    ("override", "expected"),
    (
        (
            {"stream": {"enabled": True, "mode": "all", "endpoint_url": "https://example.invalid/otlp"}},
            "refusing to send an ingest token to an override origin",
        ),
        (
            {"apm_connector": {"enabled": True, "api_url": "https://example.invalid"}},
            "refusing to send a User API token to an override origin",
        ),
    ),
)
def test_noncanonical_o11y_token_destinations_are_rejected(
    override: dict[str, object], expected: str, tmp_path: Path
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", **override)
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 1
    assert expected in combined_output(result)


def test_idempotent_re_render(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    args = ["--render", "--spec", str(spec), "--output-dir", str(output)]
    first = run_setup(*args)
    assert first.returncode == 0, combined_output(first)
    first_stream = (output / "te-payloads/stream.json").read_text(encoding="utf-8")
    second = run_setup(*args)
    assert second.returncode == 0, combined_output(second)
    assert (output / "te-payloads/stream.json").read_text(encoding="utf-8") == first_stream


def test_per_test_type_dashboards_use_canonical_metrics(tmp_path: Path) -> None:
    """Each rendered dashboard spec must reference the canonical TE OTel v2 metric set."""
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        stream={
            "enabled": True,
            "signal": "metric",
            "endpoint_type": "http",
            "data_model_version": "v2",
            "filters": {"test_types": ["bgp", "voice", "http-server"]},
        },
    )
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    bgp = (output / "dashboards/bgp.signalflow.yaml").read_text(encoding="utf-8")
    voice = (output / "dashboards/voice.signalflow.yaml").read_text(encoding="utf-8")
    http = (output / "dashboards/http-server.signalflow.yaml").read_text(encoding="utf-8")
    assert "bgp.path_changes.count" in bgp
    assert "rtp.client.request.mos" in voice
    assert "http.server.request.availability" in http


def test_alert_rule_payloads_use_v7_expression_model(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        alert_rules=[
            {
                "name": "Checkout HTTP latency",
                "test_type": "http-server",
                "expression": "((responseTime > 500 ms))",
                "severity": "Major",
                "min_sources": 2,
                "rounds_violating_required": 2,
                "rounds_violating_out_of": 3,
                "notifications": [
                    {"type": "email", "recipients": ["alerts@example.com"]},
                    {
                        "type": "custom-webhook",
                        "integrationId": "te-webhook-op-123",
                        "integrationName": "AppDynamics custom events",
                    },
                ],
            }
        ],
    )
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)

    payload = json.loads(
        (output / "te-payloads/alert-rules/checkout-http-latency.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["alertType"] == "http-server"
    assert payload["expression"] == "((responseTime > 500 ms))"
    assert payload["severity"] == "major"
    assert payload["minimumSources"] == 2
    assert payload["roundsViolatingRequired"] == 2
    assert payload["roundsViolatingOutOf"] == 3
    assert payload["notifications"]["email"]["recipients"] == ["alerts@example.com"]
    assert payload["notifications"]["customWebhook"][0]["integrationType"] == "custom-webhook"
    assert payload["notifications"]["customWebhook"][0]["integrationId"] == "te-webhook-op-123"
    assert "threshold" not in payload
    assert "windowSeconds" not in payload


def test_alert_rule_requires_expression(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        alert_rules=[
            {
                "name": "Missing expression",
                "test_type": "http-server",
                "severity": "major",
            }
        ],
    )
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 1
    assert "expression is required" in combined_output(result)


# ---------------------------------------------------------------------------
# Exclusive render bundle + durable ensure-create journal regressions
# ---------------------------------------------------------------------------


def test_render_bundle_marker_preserves_private_state_across_rerender(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    first = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert first.returncode == 0, combined_output(first)

    marker = output / BUNDLE_MARKER
    marker_data = json.loads(marker.read_text(encoding="utf-8"))
    assert marker_data == {
        "bundle_root": str(output.resolve()),
        "schema": 1,
        "skill": "splunk-observability-thousandeyes-integration",
    }
    assert marker.stat().st_mode & 0o777 == 0o600

    state = output / "state"
    state.mkdir(mode=0o700)
    retained = state / "stream.json"
    retained.write_text('{"id":"stream-123","status":"verified"}\n', encoding="utf-8")
    retained.chmod(0o600)
    before = retained.read_bytes()

    second = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert second.returncode == 0, combined_output(second)
    assert retained.read_bytes() == before
    assert retained.stat().st_mode & 0o777 == 0o600


def test_renderer_refuses_unmarked_nonempty_output_without_deleting(tmp_path: Path) -> None:
    output = tmp_path / "not-a-bundle"
    managed = output / "scripts"
    managed.mkdir(parents=True)
    sentinel = managed / "do-not-delete.txt"
    sentinel.write_text("owned by somebody else\n", encoding="utf-8")
    spec = write_spec(tmp_path / "spec.json")

    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 1
    assert "non-empty unmarked output directory" in combined_output(result)
    assert sentinel.read_text(encoding="utf-8") == "owned by somebody else\n"
    assert not (output / BUNDLE_MARKER).exists()


@pytest.mark.parametrize("unsafe_root", [Path("/"), Path.home(), REPO_ROOT])
def test_renderer_refuses_root_home_and_repository_roots(
    unsafe_root: Path, tmp_path: Path
) -> None:
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup(
        "--render",
        "--spec",
        str(spec),
        "--output-dir",
        str(unsafe_root),
    )
    assert result.returncode == 1
    assert "refusing unsafe output bundle root" in combined_output(result)


def test_renderer_rejects_symlink_output_and_managed_directory(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json")
    victim = tmp_path / "victim"
    victim.mkdir()
    sentinel = victim / "sentinel"
    sentinel.write_text("preserve\n", encoding="utf-8")
    output_link = tmp_path / "output-link"
    output_link.symlink_to(victim, target_is_directory=True)

    root_result = run_setup(
        "--render", "--spec", str(spec), "--output-dir", str(output_link)
    )
    assert root_result.returncode == 1
    assert "must not be a symlink" in combined_output(root_result)
    assert sentinel.read_text(encoding="utf-8") == "preserve\n"

    output = tmp_path / "rendered"
    initial = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert initial.returncode == 0, combined_output(initial)
    shutil.rmtree(output / "dashboards")
    (output / "dashboards").symlink_to(victim, target_is_directory=True)
    rerender = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rerender.returncode == 1
    assert "never a link or file" in combined_output(rerender)
    assert sentinel.read_text(encoding="utf-8") == "preserve\n"


def test_renderer_rejects_hardlinked_marker_and_managed_file(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json")

    marker_output = tmp_path / "marker-output"
    initial = run_setup(
        "--render", "--spec", str(spec), "--output-dir", str(marker_output)
    )
    assert initial.returncode == 0, combined_output(initial)
    os.link(marker_output / BUNDLE_MARKER, tmp_path / "marker-hardlink")
    marker_retry = run_setup(
        "--render", "--spec", str(spec), "--output-dir", str(marker_output)
    )
    assert marker_retry.returncode == 1
    assert "single-link regular file" in combined_output(marker_retry)

    file_output = tmp_path / "file-output"
    initial = run_setup("--render", "--spec", str(spec), "--output-dir", str(file_output))
    assert initial.returncode == 0, combined_output(initial)
    external = tmp_path / "external-content"
    external.write_text("must survive\n", encoding="utf-8")
    linked = file_output / "scripts/hardlinked-content"
    os.link(external, linked)
    retry = run_setup("--render", "--spec", str(spec), "--output-dir", str(file_output))
    assert retry.returncode == 1
    assert "single-link regular files" in combined_output(retry)
    assert external.read_text(encoding="utf-8") == "must survive\n"
    assert linked.exists()


def test_generated_create_flows_always_supply_stable_identity(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        tests=[{"type": "http-server", "name": "Checkout", "url": "https://example.com"}],
        alert_rules=[
            {
                "name": "Checkout alert",
                "test_type": "http-server",
                "expression": "((responseTime > 500 ms))",
            }
        ],
        templates=[
            {
                "name": "Checkout template",
                "template_body": {"credentials": {"api_key": "{{te.api_key}}"}},
            }
        ],
    )
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    scripts = rendered_text(output / "scripts")
    assert "--identity-fields ''" not in scripts
    for expected in (
        "--identity-fields type,signal,endpointType,streamEndpointUrl,dataModelVersion",
        "--identity-optional-fields testMatch,filters",
        "--identity-fields type,name,target",
        '"--identity-fields", "testName"',
        '"--identity-constant", f"type={item[\'type\']}"',
        "--identity-fields ruleName,alertType",
        "--identity-fields name",
    ):
        assert expected in scripts


def test_ensure_create_rejects_empty_identity_before_any_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = ensure_create_args(tmp_path, identity_fields="")
    calls: list[str] = []

    def unexpected_request(method: str, *_args: object, **_kwargs: object):
        calls.append(method)
        raise AssertionError("API request must not run without stable identity")

    monkeypatch.setattr(TE_CLIENT, "api_request", unexpected_request)
    with pytest.raises(TE_CLIENT.ApplyError, match="authoritative, non-empty"):
        TE_CLIENT.ensure_create(args, "token")
    assert calls == []
    assert not Path(args.state_dir).exists()


def test_ensure_create_journals_before_post_and_blocks_retry_after_missing_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = ensure_create_args(tmp_path)
    calls: list[str] = []

    def fake_request(method: str, *_args: object, **_kwargs: object):
        calls.append(method)
        if method == "GET":
            return 200, []
        state_path = Path(args.state_dir) / "asset.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["status"] == "in_progress"
        assert state["manual_reconcile"] is True
        assert state_path.stat().st_mode & 0o777 == 0o600
        assert Path(args.state_dir).stat().st_mode & 0o777 == 0o700
        return 201, {}

    monkeypatch.setattr(TE_CLIENT, "api_request", fake_request)
    with pytest.raises(TE_CLIENT.ApplyError, match="without a usable ID"):
        TE_CLIENT.ensure_create(args, "token")
    state = TE_CLIENT.read_state(Path(args.state_dir), "asset")
    assert state is not None
    assert state["status"] == "ambiguous"
    assert state["manual_reconcile"] is True
    assert "no usable object ID" in state["reason"]
    assert calls.count("POST") == 1

    call_count = len(calls)
    with pytest.raises(TE_CLIENT.ApplyError, match="automatic POST retry is blocked"):
        TE_CLIENT.ensure_create(args, "token")
    assert len(calls) == call_count
    assert calls.count("POST") == 1


def test_ensure_create_marks_transport_and_readback_outcomes_ambiguous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport_args = ensure_create_args(tmp_path / "transport", key="transport")
    transport_calls: list[str] = []

    def transport_failure(method: str, *_args: object, **_kwargs: object):
        transport_calls.append(method)
        if method == "GET":
            return 200, []
        raise TE_CLIENT.ApplyError("connection reset after send")

    monkeypatch.setattr(TE_CLIENT, "api_request", transport_failure)
    with pytest.raises(TE_CLIENT.ApplyError, match="manual reconciliation"):
        TE_CLIENT.ensure_create(transport_args, "token")
    transport_state = TE_CLIENT.read_state(Path(transport_args.state_dir), "transport")
    assert transport_state is not None and transport_state["status"] == "ambiguous"
    assert transport_calls.count("POST") == 1

    readback_root = tmp_path / "readback"
    readback_root.mkdir()
    readback_args = ensure_create_args(readback_root, key="readback")
    readback_calls: list[str] = []

    def missing_readback(method: str, *_args: object, **_kwargs: object):
        readback_calls.append(method)
        if method == "POST":
            return 201, {"id": "created-123"}
        return 200, []

    monkeypatch.setattr(TE_CLIENT, "api_request", missing_readback)
    with pytest.raises(TE_CLIENT.ApplyError, match="exact collection readback failed"):
        TE_CLIENT.ensure_create(readback_args, "token")
    readback_state = TE_CLIENT.read_state(Path(readback_args.state_dir), "readback")
    assert readback_state is not None
    assert readback_state["status"] == "ambiguous"
    assert readback_state["id"] == "created-123"
    call_count = len(readback_calls)
    with pytest.raises(TE_CLIENT.ApplyError, match="automatic POST retry is blocked"):
        TE_CLIENT.ensure_create(readback_args, "token")
    assert len(readback_calls) == call_count
    assert readback_calls.count("POST") == 1


def test_ensure_create_refuses_duplicate_identity_and_hardlinked_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = ensure_create_args(tmp_path)
    calls: list[str] = []

    def duplicate_readback(method: str, *_args: object, **_kwargs: object):
        calls.append(method)
        assert method == "GET"
        return 200, [
            {"id": "one", "name": "stable-asset"},
            {"id": "two", "name": "stable-asset"},
        ]

    monkeypatch.setattr(TE_CLIENT, "api_request", duplicate_readback)
    with pytest.raises(TE_CLIENT.ApplyError, match="multiple live objects"):
        TE_CLIENT.ensure_create(args, "token")
    assert calls == ["GET"]
    assert not (Path(args.state_dir) / "asset.json").exists()

    state_dir = tmp_path / "hardlink-state"
    TE_CLIENT.write_state(state_dir, "asset", {"status": "ambiguous"})
    os.link(state_dir / "asset.json", tmp_path / "state-hardlink")
    with pytest.raises(TE_CLIENT.ApplyError, match="single-link regular file"):
        TE_CLIENT.read_state(state_dir, "asset")


def test_ensure_create_serializes_concurrent_process_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = ensure_create_args(tmp_path)
    remote: list[dict[str, str]] = []
    request_lock = threading.Lock()
    post_count = 0

    def fake_request(method: str, *_args: object, **_kwargs: object):
        nonlocal post_count
        if method == "GET":
            with request_lock:
                return 200, list(remote)
        time.sleep(0.1)
        with request_lock:
            post_count += 1
            created = {"id": "created-once", "name": "stable-asset"}
            remote.append(created)
            return 201, dict(created)

    monkeypatch.setattr(TE_CLIENT, "api_request", fake_request)
    results: list[str] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            results.append(TE_CLIENT.ensure_create(args, "token"))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert results == ["created-once", "created-once"]
    assert post_count == 1


def test_stream_selector_and_test_type_are_part_of_stable_identity() -> None:
    stream = {
        "type": "opentelemetry",
        "signal": "metric",
        "endpointType": "http",
        "streamEndpointUrl": "https://ingest.us0.signalfx.com/v2/datapoint/otlp",
        "dataModelVersion": "v2",
        "filters": {"testTypes": ["http-server"]},
    }
    identity = TE_CLIENT.stable_identity(
        stream,
        ("type", "signal", "endpointType", "streamEndpointUrl", "dataModelVersion"),
        ("testMatch", "filters"),
    )
    wrong_selector = {**stream, "filters": {"testTypes": ["agent-to-server"]}}
    assert TE_CLIENT.find_identity_matches([wrong_selector], identity) == []
    assert TE_CLIENT.find_identity_matches([stream], identity) == [stream]

    test_identity = TE_CLIENT.stable_identity(
        {"testName": "Checkout"},
        ("testName",),
        constants={"type": "http-server"},
    )
    wrong_type = {"id": "other", "testName": "Checkout", "type": "agent-to-server"}
    assert TE_CLIENT.find_identity_matches([wrong_type], test_identity) == []
    assert TE_CLIENT.extract_id({"headers": [{"id": "nested-wrong"}]}, ("id",)) is None


def test_template_deploy_fails_before_any_post_action(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        templates=[
            {
                "name": "Safe template",
                "template_body": {"credentials": {"api_key": "{{te.api_key}}"}},
            }
        ],
    )
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    script = (output / "scripts/apply-template.sh").read_text(encoding="utf-8")
    assert "automated template deploy is disabled" in script
    assert "post-action" not in script
    assert script.index("automated template deploy is disabled") < script.index("ensure-create")


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_signalflow_auth_config_refuses_link_replacement_without_truncation(
    link_kind: str, tmp_path: Path
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)

    token = tmp_path / "o11y-token"
    token.write_text("private-token-value\n", encoding="utf-8")
    token.chmod(0o600)
    victim = tmp_path / f"{link_kind}-victim"
    victim.write_text("must-not-be-truncated\n", encoding="utf-8")
    attack_dir = tmp_path / f"{link_kind}-work"
    attack_dir.mkdir()
    config_path = attack_dir / "o11y-curl.conf"
    if link_kind == "symlink":
        config_path.symlink_to(victim)
    else:
        os.link(victim, config_path)

    fake_bin = tmp_path / f"{link_kind}-bin"
    fake_bin.mkdir()
    fake_mktemp = fake_bin / "mktemp"
    fake_mktemp.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "${ATTACK_DIR:?}"\n',
        encoding="utf-8",
    )
    fake_mktemp.chmod(0o700)
    env = {
        **os.environ,
        "ATTACK_DIR": str(attack_dir),
        "O11Y_API_TOKEN_FILE": str(token),
        "REALM": "us0",
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }
    result = subprocess.run(
        ["bash", str(output / "scripts/validate-signalflow.sh")],
        cwd=output,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode != 0
    assert victim.read_text(encoding="utf-8") == "must-not-be-truncated\n"
