"""Regressions for splunk-observability-k8s-frontend-rum-setup rendering.

These tests invoke scripts/setup.sh and scripts/render_assets.py as
subprocesses (the same path an operator or the MCP wrapper would take) and
assert on the rendered output tree.

Every cluster-mutating path is gated; these tests only exercise the render,
dry-run, and static validation paths. No kubectl calls happen.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills/splunk-observability-k8s-frontend-rum-setup"
SETUP = SKILL_DIR / "scripts/setup.sh"
VALIDATE = SKILL_DIR / "scripts/validate.sh"
RENDER = SKILL_DIR / "scripts/render_assets.py"
TEMPLATE = SKILL_DIR / "template.example"
REFERENCES_DIR = SKILL_DIR / "references"


def python_bin() -> str:
    venv = REPO_ROOT / ".venv/bin/python3"
    return str(venv if venv.exists() else "python3")


def run_setup(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SETUP), *args],
        cwd=cwd or REPO_ROOT,
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
        "api_version": "splunk-observability-k8s-frontend-rum-setup/v1",
        "realm": "us0",
        "application_name": "demo-app",
        "deployment_environment": "dev",
        "version": "0.1.0",
        "agent_version": "v1",
        "endpoints": {"domain": "splunkcloud"},
        "workloads": [
            {
                "kind": "Deployment",
                "namespace": "demo",
                "name": "web",
                "injection_mode": "nginx-configmap",
            }
        ],
        "instrumentations": {
            "modules": {"webvitals": True, "errors": True},
        },
        "session_replay": {"enabled": False},
        "source_maps": {"enabled": True, "bundler": "cli", "ci_provider": "github_actions"},
        "handoffs": {
            "dashboard_builder": True,
            "native_ops": True,
            "cloud_integration": True,
        },
    }
    base.update(overrides)
    path.write_text(yaml.safe_dump(base, sort_keys=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Render happy path
# ---------------------------------------------------------------------------


def test_render_template_example_produces_expected_files(tmp_path: Path) -> None:
    out = tmp_path / "rendered"
    result = run_render("--spec", str(TEMPLATE), "--output-dir", str(out))
    assert result.returncode == 0, combined(result)
    rendered = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    expected_subset = {
        "metadata.json",
        "preflight-report.md",
        "runbook.md",
        "k8s-rum/injection-backup-configmap.yaml",
        "k8s-rum/apply-injection.sh",
        "k8s-rum/uninstall-injection.sh",
        "k8s-rum/verify-injection.sh",
        "k8s-rum/status.sh",
        "handoff-dashboards.sh",
        "handoff-dashboards.spec.yaml",
        "handoff-detectors.sh",
        "handoff-detectors.spec.yaml",
        "handoff-cloud-integration.sh",
        "source-maps/sourcemap-upload.sh",
        "source-maps/github-actions.yaml",
    }
    missing = expected_subset - rendered
    assert not missing, f"missing files: {missing}; got: {sorted(rendered)}"


def test_metadata_records_target_workloads(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        workloads=[
            {"kind": "Deployment", "namespace": "ns1", "name": "a", "injection_mode": "nginx-configmap"},
            {"kind": "Deployment", "namespace": "ns2", "name": "b", "injection_mode": "init-container"},
        ],
    )
    out = tmp_path / "r"
    result = run_render("--spec", str(spec), "--output-dir", str(out))
    assert result.returncode == 0, combined(result)
    meta = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    targets = meta.get("targets") or []
    names = {(t["name"], t["injection_mode"]) for t in targets}
    assert ("a", "nginx-configmap") in names
    assert ("b", "init-container") in names
    assert meta["agent_version"] == "v1"
    assert meta["session_replay_enabled"] is False
    assert meta["source_maps_enabled"] is True


# ---------------------------------------------------------------------------
# Per-mode manifest correctness
# ---------------------------------------------------------------------------


def test_nginx_configmap_mode_emits_sub_filter(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.yaml")
    out = tmp_path / "r"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    cm_text = (out / "k8s-rum/nginx-rum-configmap-web.yaml").read_text(encoding="utf-8")
    assert "sub_filter '</head>'" in cm_text
    assert "sub_filter_types text/html;" in cm_text
    assert "Accept-Encoding" in cm_text
    patch = yaml.safe_load((out / "k8s-rum/nginx-deployment-patch-web.yaml").read_text())
    volumes = patch["spec"]["template"]["spec"]["volumes"]
    assert any(v["name"] == "splunk-rum-nginx-conf" for v in volumes)
    # The default mount overrides /etc/nginx/conf.d/default.conf so the
    # rendered server block does not collide with the image's stock default.
    container = patch["spec"]["template"]["spec"]["containers"][0]
    mount = next(m for m in container["volumeMounts"] if m["name"] == "splunk-rum-nginx-conf")
    assert mount["mountPath"] == "/etc/nginx/conf.d/default.conf"
    assert mount["subPath"] == "splunk-rum.conf"


def test_nginx_configmap_mode_honors_custom_conf_path(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        workloads=[
            {
                "kind": "Deployment",
                "namespace": "demo",
                "name": "web",
                "injection_mode": "nginx-configmap",
                "nginx_conf_path": "/etc/nginx/conf.d/snippets/rum.conf",
            }
        ],
    )
    out = tmp_path / "r"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    patch = yaml.safe_load((out / "k8s-rum/nginx-deployment-patch-web.yaml").read_text())
    container = patch["spec"]["template"]["spec"]["containers"][0]
    mount = next(m for m in container["volumeMounts"] if m["name"] == "splunk-rum-nginx-conf")
    assert mount["mountPath"] == "/etc/nginx/conf.d/snippets/rum.conf"


def test_ingress_snippet_mode_emits_annotation(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        workloads=[
            {
                "kind": "Deployment",
                "namespace": "demo",
                "name": "web",
                "injection_mode": "ingress-snippet",
                "ingress_name": "web",
            }
        ],
    )
    out = tmp_path / "r"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    patch = yaml.safe_load((out / "k8s-rum/ingress-snippet-patch-web.yaml").read_text())
    annotations = patch["metadata"]["annotations"]
    assert "nginx.ingress.kubernetes.io/configuration-snippet" in annotations
    assert "sub_filter" in annotations["nginx.ingress.kubernetes.io/configuration-snippet"]


def test_undo_patch_uses_strategic_delete(tmp_path: Path) -> None:
    """Each injection-mode patch has a paired undo patch using $patch: delete.

    Merge keys (per the K8s strategic-merge schema):
      - volumes        merge key = name
      - volumeMounts   merge key = mountPath
      - containers     merge key = name
      - initContainers merge key = name
    """
    spec = write_spec(tmp_path / "spec.yaml")
    out = tmp_path / "r"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    undo_path = out / "k8s-rum/nginx-deployment-undo-web.yaml"
    assert undo_path.exists(), "nginx-configmap mode must render an undo patch"
    undo = yaml.safe_load(undo_path.read_text())
    volumes = undo["spec"]["template"]["spec"]["volumes"]
    assert any(v.get("$patch") == "delete" and v.get("name") == "splunk-rum-nginx-conf" for v in volumes)
    container = undo["spec"]["template"]["spec"]["containers"][0]
    mounts = container["volumeMounts"]
    # volumeMounts $patch: delete must use mountPath as the merge key.
    assert any(m.get("$patch") == "delete" and m.get("mountPath") for m in mounts)
    assert all("name" not in m for m in mounts), \
        "volumeMounts $patch entries must NOT carry name (merge key is mountPath)"


def test_init_container_mode_uses_utility_image(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        workloads=[
            {
                "kind": "Deployment",
                "namespace": "demo",
                "name": "web",
                "injection_mode": "init-container",
                "image": "gcr.io/distroless/static-debian12",
            }
        ],
    )
    out = tmp_path / "r"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    patch = yaml.safe_load((out / "k8s-rum/initcontainer-patch-web.yaml").read_text())
    init_containers = patch["spec"]["template"]["spec"]["initContainers"]
    assert init_containers[0]["name"] == "splunk-rum-rewriter"
    assert init_containers[0]["image"] == "busybox:1.36"
    annotations = patch["metadata"].get("annotations") or {}
    assert annotations.get("splunk.com/rum-distroless-detected") == "true"


def test_runtime_config_mode_emits_window_config(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        workloads=[
            {
                "kind": "Deployment",
                "namespace": "demo",
                "name": "web",
                "injection_mode": "runtime-config",
            }
        ],
    )
    out = tmp_path / "r"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    cm = yaml.safe_load((out / "k8s-rum/runtime-config-configmap-web.yaml").read_text())
    js = cm["data"]["rum-config.js"]
    assert "window.SPLUNK_RUM_CONFIG = {" in js
    assert "applicationName: \"demo-app\"" in js
    bootstrap = (out / "k8s-rum/bootstrap-snippet-web.html").read_text(encoding="utf-8")
    assert 'src="/rum-config.js"' in bootstrap


def test_multi_workload_mixed_mode(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        workloads=[
            {"kind": "Deployment", "namespace": "ns", "name": "a", "injection_mode": "nginx-configmap"},
            {"kind": "Deployment", "namespace": "ns", "name": "b", "injection_mode": "init-container"},
            {"kind": "Deployment", "namespace": "ns", "name": "c", "injection_mode": "runtime-config"},
        ],
    )
    out = tmp_path / "r"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    rendered = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert "k8s-rum/nginx-rum-configmap-a.yaml" in rendered
    assert "k8s-rum/initcontainer-patch-b.yaml" in rendered
    assert "k8s-rum/runtime-config-configmap-c.yaml" in rendered


# ---------------------------------------------------------------------------
# Session Replay gating
# ---------------------------------------------------------------------------


def test_session_replay_requires_acceptance(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        session_replay={"enabled": True, "recorder": "splunk", "sampler_ratio": 0.5},
    )
    out = tmp_path / "r"
    result = run_render("--spec", str(spec), "--output-dir", str(out))
    assert result.returncode == 2
    assert "session_replay.enabled: true requires --accept-session-replay-enterprise" in combined(result)


def test_session_replay_renders_when_accepted(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        session_replay={
            "enabled": True,
            "recorder": "splunk",
            "sampler_ratio": 0.5,
            "mask_all_inputs": True,
            "mask_all_text": True,
        },
    )
    out = tmp_path / "r"
    result = run_render(
        "--spec", str(spec), "--output-dir", str(out),
        "--accept-session-replay-enterprise",
    )
    assert result.returncode == 0, combined(result)
    cm_text = (out / "k8s-rum/nginx-rum-configmap-web.yaml").read_text(encoding="utf-8")
    assert "SplunkSessionRecorder.init(" in cm_text
    assert "recorder: \"splunk\"" in cm_text
    assert "ratio: 0.5" in cm_text


def test_session_replay_omitted_by_default(tmp_path: Path) -> None:
    out = tmp_path / "r"
    assert run_render("--spec", str(TEMPLATE), "--output-dir", str(out)).returncode == 0
    cm_text = (out / "k8s-rum/nginx-rum-configmap-checkout-web.yaml").read_text(encoding="utf-8")
    assert "SplunkSessionRecorder.init(" not in cm_text


# ---------------------------------------------------------------------------
# Frustration Signals knobs
# ---------------------------------------------------------------------------


def test_frustration_signals_full_surface_renders(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        instrumentations={
            "modules": {"webvitals": True, "errors": True},
            "frustration_signals": {
                "rage_click": {"enabled": True, "count": 5, "timeframe_seconds": 2},
                "dead_click": {"enabled": True, "time_window_ms": 1500},
                "error_click": {"enabled": True, "time_window_ms": 1200},
                "thrashed_cursor": {"enabled": True, "thrashing_score_threshold": 0.7},
            },
        },
    )
    out = tmp_path / "r"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    cm_text = (out / "k8s-rum/nginx-rum-configmap-web.yaml").read_text(encoding="utf-8")
    assert "rageClick: {count: 5" in cm_text
    assert "deadClick: {timeWindowMs: 1500}" in cm_text
    assert "errorClick: {timeWindowMs: 1200}" in cm_text
    assert "thrashingScoreThreshold: 0.7" in cm_text


# ---------------------------------------------------------------------------
# Source-map helper
# ---------------------------------------------------------------------------


def test_source_map_helper_rendered_when_enabled(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        source_maps={"enabled": True, "bundler": "webpack", "ci_provider": "gitlab_ci"},
    )
    out = tmp_path / "r"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    sh = (out / "source-maps/sourcemap-upload.sh").read_text(encoding="utf-8")
    assert "splunk-rum sourcemaps inject" in sh
    assert "SPLUNK_O11Y_TOKEN_FILE" in sh
    assert (out / "source-maps/gitlab-ci.yaml").exists()
    assert (out / "source-maps/splunk.webpack.js").exists()
    # github-actions snippet should NOT be rendered when ci_provider=gitlab_ci.
    assert not (out / "source-maps/github-actions.yaml").exists()


def test_source_map_helper_omitted_when_disabled(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.yaml", source_maps={"enabled": False})
    out = tmp_path / "r"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    assert not (out / "source-maps").exists() or not any(
        (out / "source-maps").rglob("*")
    )


# ---------------------------------------------------------------------------
# Version-pin enforcement
# ---------------------------------------------------------------------------


def test_latest_version_rejected_without_flag(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.yaml", agent_version="latest")
    out = tmp_path / "r"
    result = run_render("--spec", str(spec), "--output-dir", str(out))
    assert result.returncode == 2
    assert "REJECTED in production" in combined(result)


def test_latest_version_allowed_with_flag(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.yaml", agent_version="latest")
    out = tmp_path / "r"
    result = run_render("--spec", str(spec), "--output-dir", str(out), "--allow-latest-version")
    assert result.returncode == 0, combined(result)


# ---------------------------------------------------------------------------
# GitOps mode
# ---------------------------------------------------------------------------


def test_gitops_mode_omits_imperative_scripts(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.yaml")
    out = tmp_path / "r"
    assert run_render(
        "--spec", str(spec), "--output-dir", str(out), "--gitops-mode",
    ).returncode == 0
    rendered = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert "k8s-rum/apply-injection.sh" not in rendered
    assert "k8s-rum/uninstall-injection.sh" not in rendered
    assert "source-maps/sourcemap-upload.sh" not in rendered
    # The YAML manifests are still rendered.
    assert "k8s-rum/nginx-rum-configmap-web.yaml" in rendered
    assert "k8s-rum/injection-backup-configmap.yaml" in rendered


# ---------------------------------------------------------------------------
# Secret-flag rejection
# ---------------------------------------------------------------------------


SECRET_FLAGS = [
    "--rum-token",
    "--access-token",
    "--token",
    "--bearer-token",
    "--api-token",
    "--o11y-token",
    "--sf-token",
    "--hec-token",
    "--platform-hec-token",
    "--api-key",
]


@pytest.mark.parametrize("flag", SECRET_FLAGS)
def test_setup_rejects_secret_flags(flag: str) -> None:
    result = run_setup("--render", flag, "supersecretvalue1234567890")
    assert result.returncode != 0
    output = combined(result).lower()
    assert "secret" in output or "tokenfile" in output or "token" in output


@pytest.mark.parametrize("flag", SECRET_FLAGS)
def test_render_rejects_secret_flags(flag: str) -> None:
    result = run_render("--spec", str(TEMPLATE), flag, "supersecretvalue1234567890")
    assert result.returncode != 0
    assert "secret" in combined(result).lower() or "chmod" in combined(result).lower()


# ---------------------------------------------------------------------------
# JS payload shape
# ---------------------------------------------------------------------------


def test_tracer_field_wraps_sampler(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        instrumentations={
            "modules": {"webvitals": True, "errors": True},
            "tracer": {"sampler_type": "session_based", "sampler_ratio": 0.25},
        },
    )
    out = tmp_path / "r"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    cm_text = (out / "k8s-rum/nginx-rum-configmap-web.yaml").read_text(encoding="utf-8")
    assert "tracer: { sampler: new SplunkRum.SessionBasedSampler({ ratio: 0.25 }) }" in cm_text


def test_runtime_config_substitutes_tracer(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        workloads=[
            {
                "kind": "Deployment",
                "namespace": "demo",
                "name": "web",
                "injection_mode": "runtime-config",
            }
        ],
    )
    out = tmp_path / "r"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    cm = yaml.safe_load((out / "k8s-rum/runtime-config-configmap-web.yaml").read_text())
    js = cm["data"]["rum-config.js"]
    assert "tracer: { sampler:" in js
    assert "__TRACER_" not in js


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_static_validate_passes_after_render(tmp_path: Path) -> None:
    out = tmp_path / "r"
    assert run_render("--spec", str(TEMPLATE), "--output-dir", str(out)).returncode == 0
    result = subprocess.run(
        ["bash", str(VALIDATE), "--output-dir", str(out)],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, combined(result)
    assert "Static validation: OK" in combined(result)


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------


def test_reference_files_exist() -> None:
    expected = {
        "injection-modes.md",
        "session-replay-privacy.md",
        "frustration-signals.md",
        "manual-instrumentation.md",
        "source-maps.md",
        "apm-linking.md",
        "csp-and-https.md",
        "discovery-workflow.md",
        "realms-and-endpoints.md",
        "framework-notes.md",
        "multi-workload.md",
        "troubleshooting.md",
        "gitops-mode.md",
    }
    actual = {p.name for p in REFERENCES_DIR.glob("*.md")}
    missing = expected - actual
    assert not missing, f"missing reference annexes: {missing}"


def test_manual_instrumentation_snippets_look_like_js() -> None:
    """Light sanity check that manual-instrumentation.md contains real JS examples."""
    text = (REFERENCES_DIR / "manual-instrumentation.md").read_text(encoding="utf-8")
    assert "SplunkRum.setGlobalAttributes" in text
    assert "SplunkRum.error" in text
    assert "componentDidCatch" in text
    assert "errorHandler" in text


# ---------------------------------------------------------------------------
# Setup.sh guidance and help
# ---------------------------------------------------------------------------


def test_setup_help_lists_modes() -> None:
    result = run_setup("--help")
    assert result.returncode == 0
    out = combined(result)
    for flag in ("--render", "--guided", "--discover-frontend-workloads",
                 "--apply-injection", "--uninstall-injection", "--validate",
                 "--accept-frontend-injection",
                 "--accept-session-replay-enterprise",
                 "--allow-latest-version"):
        assert flag in out, f"--help is missing {flag}"


def test_setup_render_default_when_no_mode(tmp_path: Path) -> None:
    out = tmp_path / "r"
    result = run_setup(
        "--realm", "us0",
        "--application-name", "demo",
        "--workload", "Deployment/demo/web=nginx-configmap",
        "--output-dir", str(out),
    )
    assert result.returncode == 0, combined(result)
    assert (out / "metadata.json").exists()
