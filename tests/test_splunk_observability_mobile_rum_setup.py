"""Regressions for splunk-observability-mobile-rum-setup."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

from agent.splunk_cisco_skills_mcp import core


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills/splunk-observability-mobile-rum-setup"
SETUP = SKILL_DIR / "scripts/setup.sh"
VALIDATE = SKILL_DIR / "scripts/validate.sh"
RENDER = SKILL_DIR / "scripts/render_assets.py"
TEMPLATE = SKILL_DIR / "template.example"


def python_bin() -> str:
    venv = REPO_ROOT / ".venv/bin/python3"
    return str(venv if venv.exists() else "python3")


def run_setup(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SETUP), *args],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def run_render(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [python_bin(), str(RENDER), *args],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def combined(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stdout or "") + (result.stderr or "")


def write_spec(path: Path, **overrides: object) -> Path:
    base: dict[str, object] = {
        "api_version": "splunk-observability-mobile-rum-setup/v1",
        "realm": "us0",
        "rum_token_ref": "SPLUNK_O11Y_RUM_TOKEN_FILE",
        "org_access_token_ref": "SPLUNK_O11Y_TOKEN_FILE",
        "source_mode": "render-snippets",
        "platforms": [
            {
                "platform": "ios",
                "app_root": str(path.parent / "ios-app"),
                "bundle_id": "com.example.ios",
                "app_name": "ios-demo",
                "deployment_environment": "dev",
                "app_version": "1.0.0",
                "validation_urls": ["https://api.example.com/health"],
            }
        ],
    }
    base.update(overrides)
    path.write_text(json.dumps(base, indent=2), encoding="utf-8")
    return path


def load_render_module():
    spec = importlib.util.spec_from_file_location("mobile_rum_render_assets", RENDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_render_template_example_produces_expected_files(tmp_path: Path) -> None:
    out = tmp_path / "rendered"
    result = run_render("--spec", str(TEMPLATE), "--output-dir", str(out))
    assert result.returncode == 0, combined(result)
    rendered = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}

    expected = {
        "metadata.json",
        "preflight-report.md",
        "runbook.md",
        "version-lock.json",
        "handoff-browser-rum.sh",
        "handoff-auto-instrumentation.sh",
        "ios/ios-checkout-ios/SplunkRumBootstrap.swift",
        "ios/ios-checkout-ios/dsym-upload.sh",
        "android/android-checkout-android/build.gradle.kts.snippet",
        "android/android-checkout-android/mapping-upload.sh",
        "react_native/react_native-checkout-rn/package.json.snippet",
        "flutter/flutter-checkout-flutter/pubspec.yaml.snippet",
    }
    assert not expected - rendered

    corpus = "\n".join(p.read_text(encoding="utf-8") for p in out.rglob("*") if p.is_file())
    assert 'exact: "2.2.3"' in corpus
    assert "com.splunk:splunk-otel-android:2.3.0" in corpus
    assert "com.splunk:rum-mapping-file-plugin:2.3.0" in corpus
    assert 'id("com.splunk.rum-mapping-file-plugin") version "2.3.0"' in corpus
    assert 'id("com.splunk.rum-okhttp3-auto-plugin") version "2.3.0"' in corpus
    assert 'id("com.splunk.rum-httpurlconnection-auto-plugin") version "2.3.0"' in corpus
    assert "com.splunk.rum.mapping" not in corpus
    assert '"@splunk/otel-react-native": "1.0.0"' in corpus
    assert "splunk_otel_flutter: 1.0.1" in corpus
    assert "splunk_otel_flutter_session_replay: 1.0.1" in corpus
    assert "splunk-rum ios upload" in corpus
    assert "splunk-rum android upload" in corpus
    assert "--app-id=" in corpus
    assert "--version-code=" in corpus
    assert "splunk-rum android upload-with-manifest" in corpus
    assert "React Native JS bundle source-map upload support" in corpus
    assert "splunk-rum sourcemaps upload" not in corpus
    assert "AgentConfiguration(" in corpus
    assert "EndpointConfiguration(" in corpus
    assert "SplunkRumConfiguration" not in corpus
    assert "SplunkRum.init" not in corpus
    assert "SplunkRum.install(agentConfiguration, moduleConfigurations)" in corpus
    assert "EndpointConfiguration.forRum" in corpus
    assert "SplunkRum.instance.install" in corpus


@pytest.mark.parametrize("platform, expected", [
    ("ios", "SplunkAgent"),
    ("android", "com.splunk:splunk-otel-android:2.3.0"),
    ("react_native", "@splunk/otel-react-native"),
    ("flutter", "splunk_otel_flutter"),
])
def test_single_platform_render(platform: str, expected: str, tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        platforms=[
            {
                "platform": platform,
                "app_root": str(tmp_path / platform),
                "app_name": f"{platform}-demo",
                "deployment_environment": "qa",
                "app_version": "2.0.0",
                "bundle_id": "com.example.demo",
                "application_id": "com.example.demo",
            }
        ],
    )
    out = tmp_path / "out"
    result = run_render("--spec", str(spec), "--output-dir", str(out))
    assert result.returncode == 0, combined(result)
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in out.rglob("*") if p.is_file())
    assert expected in corpus
    metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["platforms"][0]["platform"] == platform


def test_render_patches_and_apply_patches_are_gated(tmp_path: Path) -> None:
    app_root = tmp_path / "ios-app"
    app_root.mkdir()
    spec = write_spec(
        tmp_path / "spec.yaml",
        source_mode="render-patches",
        platforms=[
            {
                "platform": "ios",
                "app_root": str(app_root),
                "bundle_id": "com.example.ios",
                "app_name": "ios-demo",
                "deployment_environment": "dev",
                "app_version": "1.0.0",
            }
        ],
    )
    out = tmp_path / "out"
    result = run_setup("--render-patches", "--spec", str(spec), "--output-dir", str(out))
    assert result.returncode == 0, combined(result)
    assert (out / "source-patches/ios-ios-demo.patch").is_file()
    assert (out / "apply-source-patches.sh").is_file()

    denied = run_setup("--apply-patches", "--spec", str(spec), "--output-dir", str(tmp_path / "denied"))
    assert denied.returncode != 0
    assert "accept-mobile-rum-source-edit" in combined(denied)

    init = subprocess.run(["git", "init"], cwd=app_root, text=True, capture_output=True, check=False)
    assert init.returncode == 0, init.stderr
    applied = run_setup(
        "--apply-patches",
        "--accept-mobile-rum-source-edit",
        "--spec",
        str(spec),
        "--output-dir",
        str(tmp_path / "applied"),
    )
    assert applied.returncode == 0, combined(applied)
    assert (app_root / "splunk-rum/SplunkRumBootstrap.swift").is_file()


def test_negative_inputs_are_rejected(tmp_path: Path) -> None:
    direct = run_setup("--rum-token", "abcdefghijklmnopqrstuvwxyz1234567890")
    assert direct.returncode != 0
    assert "Direct token flag" in combined(direct)

    raw_token_spec = write_spec(tmp_path / "token.yaml", rum_token="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890")
    raw = run_render("--spec", str(raw_token_spec), "--output-dir", str(tmp_path / "raw"))
    assert raw.returncode != 0
    assert "inline token" in combined(raw)

    latest_spec = write_spec(tmp_path / "latest.yaml", versions={"ios_agent": "latest"})
    latest = run_render("--spec", str(latest_spec), "--output-dir", str(tmp_path / "latest"))
    assert latest.returncode != 0
    assert "not pinned" in combined(latest)

    wildcard_spec = write_spec(tmp_path / "wildcard.yaml", versions={"ios_agent": "2.+"})
    wildcard = run_render("--spec", str(wildcard_spec), "--output-dir", str(tmp_path / "wildcard"))
    assert wildcard.returncode != 0
    assert "not pinned" in combined(wildcard)

    flutter_replay_latest_spec = write_spec(
        tmp_path / "flutter-replay-latest.yaml",
        versions={"flutter_session_replay": "latest"},
        platforms=[
            {
                "platform": "flutter",
                "app_name": "flutter-demo",
                "deployment_environment": "dev",
                "app_version": "1.0.0",
                "application_id": "com.example.flutter",
            }
        ],
    )
    flutter_replay_latest = run_render(
        "--spec",
        str(flutter_replay_latest_spec),
        "--output-dir",
        str(tmp_path / "flutter-replay-latest"),
    )
    assert flutter_replay_latest.returncode != 0
    assert "platforms[0].versions.flutter_session_replay" in combined(flutter_replay_latest)


def test_session_replay_gate_and_sampling(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "sr.yaml",
        platforms=[
            {
                "platform": "react_native",
                "app_name": "rn-demo",
                "deployment_environment": "prod",
                "app_version": "1.0.0",
                "application_id": "com.example.rn",
                "session_replay": {"enabled": True},
            }
        ],
    )
    denied = run_render("--spec", str(spec), "--output-dir", str(tmp_path / "denied"))
    assert denied.returncode != 0
    assert "accept-session-replay-enterprise" in combined(denied)

    out = tmp_path / "out"
    ok = run_render(
        "--spec",
        str(spec),
        "--output-dir",
        str(out),
        "--accept-session-replay-enterprise",
    )
    assert ok.returncode == 0, combined(ok)
    session_text = (out / "react_native/react_native-rn-demo/SessionReplayControls.ts").read_text()
    assert "samplingRate: 0.2" in session_text
    package_text = (out / "react_native/react_native-rn-demo/package.json.snippet").read_text()
    assert '"@splunk/otel-session-replay-react-native": "1.0.0"' in package_text
    provider_text = (out / "react_native/react_native-rn-demo/SplunkRumProvider.tsx").read_text()
    assert "new SessionReplayModuleConfiguration(true, 0.2)" in provider_text
    assert "agentConfiguration" in provider_text
    assert "config={rumConfig}" not in provider_text

    bad_sample_spec = write_spec(
        tmp_path / "bad-sample.yaml",
        platforms=[
            {
                "platform": "flutter",
                "app_name": "flutter-demo",
                "deployment_environment": "prod",
                "app_version": "1.0.0",
                "application_id": "com.example.flutter",
                "session_replay": {"enabled": True, "sampling_rate": 1.5},
            }
        ],
    )
    bad = run_render(
        "--spec",
        str(bad_sample_spec),
        "--output-dir",
        str(tmp_path / "bad"),
        "--accept-session-replay-enterprise",
    )
    assert bad.returncode != 0
    assert "sampling_rate" in combined(bad)

    flutter_spec = write_spec(
        tmp_path / "flutter-sr.yaml",
        platforms=[
            {
                "platform": "flutter",
                "app_name": "flutter-demo",
                "deployment_environment": "prod",
                "app_version": "1.0.0",
                "application_id": "com.example.flutter",
                "session_replay": {"enabled": True},
            }
        ],
    )
    flutter_out = tmp_path / "flutter-out"
    flutter_ok = run_render(
        "--spec",
        str(flutter_spec),
        "--output-dir",
        str(flutter_out),
        "--accept-session-replay-enterprise",
    )
    assert flutter_ok.returncode == 0, combined(flutter_ok)
    pubspec = (flutter_out / "flutter/flutter-flutter-demo/pubspec.yaml.snippet").read_text()
    assert "splunk_otel_flutter_session_replay: 1.0.1" in pubspec
    flutter_dart = (flutter_out / "flutter/flutter-flutter-demo/splunk_rum.dart").read_text()
    assert "SessionReplayModuleConfiguration" in flutter_dart
    assert "samplingRate: 0.2" in flutter_dart


def test_platform_requirement_guards(tmp_path: Path) -> None:
    low_rn = write_spec(
        tmp_path / "rn-low.yaml",
        platforms=[
            {
                "platform": "react_native",
                "app_name": "rn-low",
                "deployment_environment": "dev",
                "app_version": "1.0.0",
                "application_id": "com.example.rn",
                "requirements": {"react_native": "0.74.0", "react": "18.2.0", "android_min_api": 24},
            }
        ],
    )
    result = run_render("--spec", str(low_rn), "--output-dir", str(tmp_path / "rn-low"))
    assert result.returncode != 0
    assert "React Native must be 0.75.0" in combined(result)

    low_android = write_spec(
        tmp_path / "android-low.yaml",
        platforms=[
            {
                "platform": "android",
                "app_name": "android-low",
                "deployment_environment": "dev",
                "app_version": "1.0.0",
                "application_id": "com.example.android",
                "requirements": {"android_min_api": 21},
            }
        ],
    )
    result = run_render("--spec", str(low_android), "--output-dir", str(tmp_path / "android-low"))
    assert result.returncode != 0
    assert "below the default supported floor 24" in combined(result)


def test_validate_and_server_timing_regex(tmp_path: Path) -> None:
    out = tmp_path / "rendered"
    assert run_render("--spec", str(TEMPLATE), "--output-dir", str(out)).returncode == 0
    static = subprocess.run(
        ["bash", str(VALIDATE), "--output-dir", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert static.returncode == 0, static.stdout + static.stderr

    valid = subprocess.run(
        [
            "bash",
            str(VALIDATE),
            "--output-dir",
            str(out),
            "--check-server-timing-header",
            'Server-Timing: traceparent;desc="00-1234567890abcdef1234567890abcdef-1234567890abcdef-01"',
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert valid.returncode == 0, valid.stdout + valid.stderr

    malformed = subprocess.run(
        [
            "bash",
            str(VALIDATE),
            "--output-dir",
            str(out),
            "--check-server-timing-header",
            'Server-Timing: traceparent;desc="00-nope-1234-01"',
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert malformed.returncode != 0
    assert "invalid" in (malformed.stdout + malformed.stderr)

    missing = subprocess.run(
        [
            "bash",
            str(VALIDATE),
            "--output-dir",
            str(out),
            "--check-server-timing-header",
            "Date: Tue, 19 May 2026 00:00:00 GMT",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode != 0
    assert "missing" in (missing.stdout + missing.stderr)
    assert (out / "handoff-auto-instrumentation.sh").is_file()

    module = load_render_module()
    multi = module.server_timing_traceparent_status(
        "\n".join(
            [
                'Server-Timing: traceparent;desc="00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"',
                'Server-Timing: traceparent;desc="00-cccccccccccccccccccccccccccccccc-dddddddddddddddd-01"',
            ]
        )
    )
    assert multi["status"] == "valid"
    assert multi["traceparent"] == "00-cccccccccccccccccccccccccccccccc-dddddddddddddddd-01"


def test_mcp_classification_and_secret_rejection() -> None:
    readonly = core.plan_skill_script(
        "splunk-observability-mobile-rum-setup",
        "setup.sh",
        ["--render"],
    )
    assert readonly["read_only"] is True

    patches = core.plan_skill_script(
        "splunk-observability-mobile-rum-setup",
        "setup.sh",
        ["--render-patches"],
    )
    assert patches["read_only"] is True

    apply_plan = core.plan_skill_script(
        "splunk-observability-mobile-rum-setup",
        "setup.sh",
        ["--apply-patches", "--accept-mobile-rum-source-edit"],
    )
    assert apply_plan["read_only"] is False

    with pytest.raises(core.SkillMCPError, match="Direct secret flag"):
        core.plan_skill_script(
            "splunk-observability-mobile-rum-setup",
            "setup.sh",
            ["--rum-token", "secret-value"],
        )
