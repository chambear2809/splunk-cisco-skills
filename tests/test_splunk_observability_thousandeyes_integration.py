"""Regressions for splunk-observability-thousandeyes-integration rendering."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/splunk-observability-thousandeyes-integration/scripts/setup.sh"


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
