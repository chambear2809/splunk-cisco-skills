"""Regressions for Splunk Observability native operations rendering."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/splunk-observability-native-ops/scripts/setup.sh"
O11Y_API = REPO_ROOT / "skills/splunk-observability-native-ops/scripts/o11y_native_api.py"
EXAMPLE_JSON_SPEC = REPO_ROOT / "skills/splunk-observability-native-ops/templates/native-ops.example.json"
EXAMPLE_YAML_SPEC = REPO_ROOT / "skills/splunk-observability-native-ops/templates/native-ops.example.yaml"


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


def write_spec(path: Path, **overrides: object) -> Path:
    spec: dict[str, object] = {
        "api_version": "splunk-observability-native-ops/v1",
        "realm": "us0",
        "teams": [],
        "detectors": [],
        "alert_routing": [],
        "muting_rules": [],
        "slo_links": [],
        "synthetics": [],
        "apm": [],
        "rum": [],
        "logs": [],
        "on_call": [],
    }
    spec.update(overrides)
    path.write_text(json.dumps(spec, indent=2, sort_keys=True), encoding="utf-8")
    return path


def rendered_text(root: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(root.rglob("*")) if path.is_file())


@pytest.mark.parametrize("spec_path", [EXAMPLE_JSON_SPEC, EXAMPLE_YAML_SPEC])
def test_example_specs_render_coverage_plan_payloads_deeplinks_and_handoff(
    tmp_path: Path,
    spec_path: Path,
) -> None:
    output_dir = tmp_path / "rendered"

    result = run_setup("--render", "--validate", "--spec", str(spec_path), "--output-dir", str(output_dir), "--realm", "us0")

    assert result.returncode == 0, combined_output(result)
    assert (output_dir / "coverage-report.json").is_file()
    assert (output_dir / "apply-plan.json").is_file()
    assert (output_dir / "deeplinks.json").is_file()
    assert (output_dir / "handoff.md").is_file()
    assert (output_dir / "payloads/detectors/checkout-p95-latency.json").is_file()

    coverage = json.loads((output_dir / "coverage-report.json").read_text(encoding="utf-8"))
    plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
    object_types = {item["object_type"] for item in coverage["objects"]}
    assert {"detector", "synthetic_test", "apm_service_map", "rum_session", "logs_chart", "on_call"} <= object_types
    assert coverage["summary"]["api_apply"] >= 1
    assert coverage["summary"]["api_validate"] >= 1
    assert coverage["summary"]["deeplink"] >= 1
    assert coverage["summary"]["handoff"] >= 1
    assert not any("{test_id}" in action["path"] for action in plan["actions"])


def test_direct_secret_flags_and_inline_secret_fields_are_rejected(tmp_path: Path) -> None:
    result = run_setup("--validate", "--spec", str(EXAMPLE_JSON_SPEC), "--token", "inline-secret")

    assert result.returncode == 1
    assert "--token-file" in combined_output(result)
    assert "process listings" in combined_output(result)

    equals_result = run_setup("--validate", "--spec", str(EXAMPLE_JSON_SPEC), "--token=INLINE_SECRET_SHOULD_NOT_LEAK")
    assert equals_result.returncode == 1
    assert "--token-file" in combined_output(equals_result)
    assert "INLINE_SECRET_SHOULD_NOT_LEAK" not in combined_output(equals_result)

    secret_spec = write_spec(
        tmp_path / "secret.json",
        detectors=[
            {
                "name": "Bad detector",
                "program_text": "data('cpu.utilization').publish(label='cpu')",
                "rules": [{"detect_label": "cpu", "severity": "Major", "notifications": []}],
                "token": "SHOULD_NOT_RENDER",
            }
        ],
    )
    inline_result = run_setup("--validate", "--spec", str(secret_spec))

    assert inline_result.returncode == 1
    assert "Inline secret field" in combined_output(inline_result)
    assert "SHOULD_NOT_RENDER" not in combined_output(inline_result)


def test_token_values_never_appear_in_rendered_output(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    token_file = tmp_path / "o11y-token"
    token_file.write_text("O11Y_NATIVE_SECRET_SHOULD_NOT_RENDER", encoding="utf-8")

    result = run_setup(
        "--render",
        "--apply",
        "--dry-run",
        "--spec",
        str(EXAMPLE_JSON_SPEC),
        "--output-dir",
        str(output_dir),
        "--realm",
        "us0",
        "--token-file",
        str(token_file),
    )

    assert result.returncode == 0, combined_output(result)
    assert "O11Y_NATIVE_SECRET_SHOULD_NOT_RENDER" not in rendered_text(output_dir)
    assert "O11Y_NATIVE_SECRET_SHOULD_NOT_RENDER" not in combined_output(result)


def test_detector_payloads_include_rules_notifications_teams_and_delay_fields(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    spec_path = write_spec(
        tmp_path / "detector.json",
        detectors=[
            {
                "name": "Checkout p95 latency",
                "description": "Alert when checkout latency exceeds the SLO budget.",
                "program_text": "latency = data('service.request.duration').percentile(95).publish(label='latency')\ndetect(when(latency > threshold(750))).publish('latency_high')",
                "team_ids": ["Gteam123"],
                "min_delay": 60000,
                "max_delay": 120000,
                "rules": [
                    {
                        "detect_label": "latency_high",
                        "severity": "Critical",
                        "notifications": [{"type": "Email", "email": "o11y-alerts@example.com"}],
                    }
                ],
            }
        ],
    )
    result = run_setup("--render", "--spec", str(spec_path), "--output-dir", str(output_dir))

    assert result.returncode == 0, combined_output(result)
    payload = json.loads((output_dir / "payloads/detectors/checkout-p95-latency.json").read_text(encoding="utf-8"))
    validate_payload = json.loads(
        (output_dir / "payloads/detectors/checkout-p95-latency.validate.json").read_text(encoding="utf-8")
    )
    plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))

    assert payload["name"] == "Checkout p95 latency"
    assert "programText" in payload
    assert payload["teams"] == ["Gteam123"]
    assert payload["minDelay"] == 60000
    assert payload["maxDelay"] == 120000
    assert payload["rules"][0]["severity"] == "Critical"
    assert payload["rules"][0]["notifications"][0]["type"] == "Email"
    assert validate_payload["programText"] == payload["programText"]
    assert any(action["path"] == "/detector/validate" for action in plan["actions"])
    assert not any(action["path"] in {"/detector/events", "/detector/incidents"} for action in plan["actions"])


def test_alert_routing_renders_team_policy_and_detector_recipients(tmp_path: Path) -> None:
    spec_path = write_spec(
        tmp_path / "routing.json",
        alert_routing=[
            {
                "kind": "team_notification_policy",
                "name": "Checkout team policy",
                "team_id": "team-123",
                "notification_policy": {"default": [{"type": "TeamEmail"}]},
            },
            {
                "kind": "detector_recipients",
                "name": "Checkout detector recipients",
                "detector_id": "detector-123",
                "rules": [
                    {
                        "detect_label": "latency_high",
                        "severity": "Critical",
                        "notifications": [{"type": "Team", "team_id": "team-123"}],
                    }
                ],
            },
        ],
    )
    output_dir = tmp_path / "rendered"
    result = run_setup("--render", "--spec", str(spec_path), "--output-dir", str(output_dir))

    assert result.returncode == 0, combined_output(result)
    plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
    actions = {(action["action"], action["path"]) for action in plan["actions"]}
    assert ("update-team-notification-policy", "/team/team-123") in actions
    assert ("update-detector-recipients", "/detector/detector-123") in actions
    team_payload = json.loads((output_dir / "payloads/alert-routing/checkout-team-policy.json").read_text(encoding="utf-8"))
    detector_payload = json.loads(
        (output_dir / "payloads/alert-routing/checkout-detector-recipients.json").read_text(encoding="utf-8")
    )
    assert "notificationLists" in team_payload
    assert detector_payload["rules"][0]["notifications"][0]["team"] == "team-123"
    assert "team_id" not in detector_payload["rules"][0]["notifications"][0]


def test_alert_routing_detector_recipients_reject_team_display_names(tmp_path: Path) -> None:
    spec_path = write_spec(
        tmp_path / "bad-routing.json",
        alert_routing=[
            {
                "kind": "detector_recipients",
                "name": "Bad detector recipients",
                "detector_id": "detector-123",
                "rules": [
                    {
                        "detect_label": "latency_high",
                        "severity": "Critical",
                        "notifications": [{"type": "Team", "team": "Checkout SRE"}],
                    }
                ],
            }
        ],
    )

    result = run_setup("--render", "--spec", str(spec_path), "--output-dir", str(tmp_path / "rendered"))

    assert result.returncode == 1
    assert "team_id" in combined_output(result)


def test_detector_notifications_accept_api_native_team_field_with_id(tmp_path: Path) -> None:
    spec_path = write_spec(
        tmp_path / "team-field.json",
        detectors=[
            {
                "name": "Team field detector",
                "program_text": "x = data('cpu.utilization').publish(label='x')\ndetect(when(x > threshold(90))).publish('high')",
                "rules": [
                    {
                        "detect_label": "high",
                        "severity": "Major",
                        "notifications": [{"type": "Team", "team": "Gteam123"}],
                    }
                ],
            }
        ],
    )
    output_dir = tmp_path / "rendered"

    result = run_setup("--render", "--spec", str(spec_path), "--output-dir", str(output_dir))

    assert result.returncode == 0, combined_output(result)
    payload = json.loads((output_dir / "payloads/detectors/team-field-detector.json").read_text(encoding="utf-8"))
    assert payload["rules"][0]["notifications"][0]["team"] == "Gteam123"


def test_synthetics_render_all_test_types_run_lookup_and_artifact_commands(tmp_path: Path) -> None:
    spec_path = write_spec(
        tmp_path / "synthetics.json",
        synthetics=[
            {"kind": "browser", "name": "Browser", "url": "https://example.com", "id": "browser-1", "run_now": True},
            {"kind": "api", "name": "API", "endpoint": "https://api.example.com/health"},
            {"kind": "http", "name": "HTTP", "url": "https://example.com/health"},
            {"kind": "ssl", "name": "SSL", "host": "example.com"},
            {"kind": "port", "name": "Port", "host": "example.com", "port": 443},
            {"kind": "run", "name": "Browser run lookup", "test_id": "browser-1"},
            {
                "kind": "artifact",
                "name": "Browser waterfall",
                "test_id": "browser-1",
                "location_id": "aws-us-east-1",
                "timestamp": 4102444800000,
                "run_id": "run-1",
                "filename": "network.har",
            },
        ],
    )
    output_dir = tmp_path / "rendered"
    result = run_setup("--render", "--spec", str(spec_path), "--output-dir", str(output_dir))

    assert result.returncode == 0, combined_output(result)
    plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
    paths = {action["path"] for action in plan["actions"]}
    urls = {action["url"] for action in plan["actions"]}
    for kind in ("browser", "api", "http", "ssl", "port"):
        assert f"/tests/{kind}" in paths or f"/tests/{kind}/browser-1" in paths
    assert "/tests/browser-1/run_now" in paths
    assert "/tests/browser-1/runs" in paths
    assert "/tests/browser-1/artifacts/aws-us-east-1/4102444800000/run-1/network.har" in paths
    assert any("/v2/synthetics/tests/browser" in url for url in urls)
    assert not any(path.startswith("/synthetics/tests") for path in paths)
    assert not any("{" in path or "}" in path for path in paths)
    assert all(action["service"] == "synthetics" for action in plan["actions"] if action["object_type"].startswith("synthetic"))
    assert "waterfall detail" in (output_dir / "handoff.md").read_text(encoding="utf-8")


def test_missing_trace_and_synthetic_run_ids_render_handoff_not_placeholder_actions(tmp_path: Path) -> None:
    spec_path = write_spec(
        tmp_path / "placeholder-guards.json",
        synthetics=[
            {"kind": "run", "name": "Missing run selector"},
            {"kind": "artifact", "name": "Missing artifact selector"},
        ],
        apm=[{"kind": "trace", "name": "Missing trace selector"}],
    )
    output_dir = tmp_path / "rendered"

    result = run_setup("--render", "--validate", "--spec", str(spec_path), "--output-dir", str(output_dir))

    assert result.returncode == 0, combined_output(result)
    plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
    paths = [action["path"] for action in plan["actions"]]
    assert not any("{" in path or "}" in path for path in paths)
    assert not any(action["object_type"] in {"synthetic_run", "synthetic_artifact", "apm_trace"} for action in plan["actions"])
    handoff = (output_dir / "handoff.md").read_text(encoding="utf-8")
    assert "Synthetic run lookup requires a concrete test ID or run ID" in handoff
    assert "Trace download requires a concrete trace ID" in handoff


def test_apm_rum_and_logs_render_validate_deeplink_or_handoff_not_false_apply(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    result = run_setup("--render", "--spec", str(EXAMPLE_JSON_SPEC), "--output-dir", str(output_dir))

    assert result.returncode == 0, combined_output(result)
    plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
    coverage = json.loads((output_dir / "coverage-report.json").read_text(encoding="utf-8"))

    assert any(action["action"] == "validate-apm-topology" and action["path"] == "/apm/topology/checkout" for action in plan["actions"])
    assert any(action["action"] == "download-apm-trace" and action["path"].endswith("/latest") for action in plan["actions"])
    assert any(action["action"] == "validate-rum-metric-metadata" for action in plan["actions"])
    assert any(
        item["object_type"] == "rum_session" and item["coverage"] == "api_validate"
        for item in coverage["objects"]
    )
    for item in coverage["objects"]:
        if item["object_type"] in {"rum_session", "logs_chart"}:
            assert item["coverage"] in {"api_validate", "deeplink", "handoff"}
            assert item["coverage"] != "api_apply"
        if item["object_type"] == "slo":
            assert item["coverage"] in {"deeplink", "handoff"}


def test_on_call_schedules_are_handoff_and_explicit_api_requests_are_separate(tmp_path: Path) -> None:
    spec_path = write_spec(
        tmp_path / "oncall.json",
        on_call=[
            {"kind": "rotation", "name": "Primary rotation", "team": "Checkout SRE", "shifts": []},
            {"kind": "api_request", "name": "List teams", "method": "GET", "path": "/teams"},
        ],
    )
    output_dir = tmp_path / "rendered"
    result = run_setup("--render", "--apply", "--dry-run", "--json", "--spec", str(spec_path), "--output-dir", str(output_dir))

    assert result.returncode == 0, combined_output(result)
    dry_run = json.loads(result.stdout)
    assert any(
        item["service"] == "on_call" and item["path"] == "/teams" and item["coverage"] == "api_validate"
        for item in dry_run["sequence"]
    )
    coverage = json.loads((output_dir / "coverage-report.json").read_text(encoding="utf-8"))
    assert any(item["object_type"] == "on_call" and item["coverage"] == "handoff" for item in coverage["objects"])
    assert any(item["object_type"] == "on_call" and item["coverage"] == "api_validate" for item in coverage["objects"])


def test_dry_run_json_is_deterministic_and_has_no_network_responses(tmp_path: Path) -> None:
    first = run_setup(
        "--render",
        "--validate",
        "--apply",
        "--dry-run",
        "--json",
        "--spec",
        str(EXAMPLE_JSON_SPEC),
        "--output-dir",
        str(tmp_path / "first"),
        "--realm",
        "eu0",
    )
    second = run_setup(
        "--render",
        "--validate",
        "--apply",
        "--dry-run",
        "--json",
        "--spec",
        str(EXAMPLE_JSON_SPEC),
        "--output-dir",
        str(tmp_path / "second"),
        "--realm",
        "eu0",
    )

    assert first.returncode == 0, combined_output(first)
    assert second.returncode == 0, combined_output(second)
    first_json = json.loads(first.stdout)
    second_json = json.loads(second.stdout)
    assert first_json == second_json
    assert first_json["dry_run"] is True
    assert "responses" not in first_json


def test_validate_rendered_output_without_spec(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    render = run_setup("--render", "--spec", str(EXAMPLE_JSON_SPEC), "--output-dir", str(output_dir))
    assert render.returncode == 0, combined_output(render)

    validate = run_setup("--validate", "--output-dir", str(output_dir), "--json")

    assert validate.returncode == 0, combined_output(validate)
    result = json.loads(validate.stdout)
    assert result["rendered"]["ok"] is True


def test_apply_runner_rejects_stale_placeholder_actions(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    render = run_setup("--render", "--spec", str(EXAMPLE_JSON_SPEC), "--output-dir", str(output_dir))
    assert render.returncode == 0, combined_output(render)

    plan_path = output_dir / "apply-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["actions"][0]["path"] = "/tests/{test_id}/runs"
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8")

    result = subprocess.run(
        ["python3", str(O11Y_API), "apply", "--plan-dir", str(output_dir), "--dry-run", "--realm", "us0"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 1
    assert "unresolved placeholder" in combined_output(result)


def test_validate_and_apply_reject_malformed_action_paths(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    render = run_setup("--render", "--spec", str(EXAMPLE_JSON_SPEC), "--output-dir", str(output_dir))
    assert render.returncode == 0, combined_output(render)

    plan_path = output_dir / "apply-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["actions"][0]["path"] = "detector"
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8")

    validate = run_setup("--validate", "--output-dir", str(output_dir))
    assert validate.returncode == 1
    assert "path must start with '/'" in combined_output(validate)

    apply = subprocess.run(
        ["python3", str(O11Y_API), "apply", "--plan-dir", str(output_dir), "--dry-run", "--realm", "us0"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert apply.returncode == 1
    assert "path must start with '/'" in combined_output(apply)
