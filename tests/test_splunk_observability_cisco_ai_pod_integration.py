"""Regressions for splunk-observability-cisco-ai-pod-integration (umbrella) rendering."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/splunk-observability-cisco-ai-pod-integration/scripts/setup.sh"
VALIDATE = REPO_ROOT / "skills/splunk-observability-cisco-ai-pod-integration/scripts/validate.sh"


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


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def test_default_template_renders_composed_overlay(tmp_path: Path) -> None:
    """The umbrella's default render should compose all three children and add AI-Pod blocks."""
    output = tmp_path / "rendered"
    result = run_setup("--render", "--validate", "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    # Composed overlay.
    overlay_path = output / "splunk-otel-overlay/values.overlay.yaml"
    assert overlay_path.is_file()
    overlay = overlay_path.read_text(encoding="utf-8")
    # Must include children's contributions:
    #   - cisco_os from Nexus child (via clusterReceiver)
    #   - receiver_creator/dcgm-cisco from GPU child
    #   - intersight pipeline overlay from Intersight child
    assert "cisco_os:" in overlay
    assert "receiver_creator/dcgm-cisco:" in overlay
    # CRITICAL: receiver_creator/nvidia must NEVER appear (chart autodetect collision).
    assert "receiver_creator/nvidia:" not in overlay
    # AI-Pod-specific additions.
    assert "k8s_attributes/nim" in overlay
    # Child render outputs preserved for debugging.
    for child in (
        "splunk-observability-cisco-nexus-integration",
        "splunk-observability-cisco-intersight-integration",
        "splunk-observability-nvidia-gpu-integration",
    ):
        assert (output / "child-renders" / child / "metadata.json").is_file(), f"Missing child render: {child}"


def test_endpoints_mode_emits_rbac_custom_rules(tmp_path: Path) -> None:
    """When --nim-scrape-mode endpoints, rbac.customRules MUST be present."""
    output = tmp_path / "rendered"
    result = run_setup(
        "--render",
        "--validate",
        "--nim-scrape-mode",
        "endpoints",
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, combined_output(result)
    overlay = (output / "splunk-otel-overlay/values.overlay.yaml").read_text(encoding="utf-8")
    assert "customRules" in overlay
    assert "endpointslices" in overlay
    assert "discovery.k8s.io" in overlay


def test_receiver_creator_mode_does_not_emit_rbac_patch(tmp_path: Path) -> None:
    """receiver_creator NIM scrape mode does not need the RBAC patch."""
    output = tmp_path / "rendered"
    result = run_setup(
        "--render",
        "--nim-scrape-mode",
        "receiver_creator",
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, combined_output(result)
    overlay = (output / "splunk-otel-overlay/values.overlay.yaml").read_text(encoding="utf-8")
    assert "customRules" not in overlay


def test_openshift_distribution_applies_required_defaults(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    result = run_setup(
        "--render",
        "--validate",
        "--distribution",
        "openshift",
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, combined_output(result)
    overlay = (output / "splunk-otel-overlay/values.overlay.yaml").read_text(encoding="utf-8")
    assert "insecure_skip_verify: true" in overlay
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    warnings = " ".join(metadata.get("warnings", []))
    assert "OpenShift" in warnings


def test_dcgm_pod_labels_patch_passed_through(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    result = run_setup(
        "--render",
        "--enable-dcgm-pod-labels",
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, combined_output(result)
    # Patch files passed through from the GPU child.
    for f in (
        "dcgm-pod-labels-patch/01-cluster-role.yaml",
        "dcgm-pod-labels-patch/04-daemonset-env-patch.yaml",
    ):
        assert (output / f).is_file(), f"Missing patch file passed through from GPU child: {f}"


def test_workshop_mode_renders_multi_tenant_script(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    result = run_setup("--render", "--workshop-mode", "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    workshop = (output / "workshop/multi-tenant.sh").read_text(encoding="utf-8")
    assert "ClusterRoleBinding" in workshop
    assert "splunk-otel-collector" in workshop
    assert "for i in $(seq 1" in workshop


def test_explain_composition_script_lists_all_children(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    result = run_setup("--render", "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    explain = (output / "scripts/explain-composition.sh").read_text(encoding="utf-8")
    assert "splunk-observability-cisco-nexus-integration" in explain
    assert "splunk-observability-cisco-intersight-integration" in explain
    assert "splunk-observability-nvidia-gpu-integration" in explain


def test_intersight_pipeline_merged_into_composite_overlay(tmp_path: Path) -> None:
    """Regression: the umbrella's load_child_overlay must walk EVERY *.yaml file in
    each child's splunk-otel-overlay/ dir, not just values.overlay.yaml.

    The Intersight child writes its OTLP-receiver overlay to a dedicated file
    (intersight-pipeline.yaml) so it doesn't collide with values.overlay.yaml
    blocks from sibling children. Earlier the umbrella only loaded the
    values.overlay.yaml filename, silently dropping the Intersight contribution
    even though the Intersight render itself succeeded.

    The visible footprint of the Intersight contribution in the composed overlay
    is the addition of `otlp` to the agent's metrics pipeline receivers list.
    The chart's default already defines `otlp` as a receiver; the Intersight
    child's job is to wire it INTO the metrics pipeline so OTLP-pushed Intersight
    metrics actually get exported.
    """
    output = tmp_path / "rendered"
    result = run_setup("--render", "--validate", "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)

    intersight_overlay_dir = (
        output
        / "child-renders/splunk-observability-cisco-intersight-integration/splunk-otel-overlay"
    )
    yaml_files = list(intersight_overlay_dir.glob("*.yaml"))
    assert yaml_files, "Intersight child wrote no overlay yaml files"
    # The bug surface depended on the Intersight child using a non-default
    # filename. Confirm at least one such file exists.
    non_default = [p for p in yaml_files if p.name != "values.overlay.yaml"]
    assert non_default, (
        "Intersight child no longer uses a non-default filename; the regression "
        "test's value is reduced. Either update the test or restore the original "
        "naming so this regression keeps signaling."
    )

    overlay = (output / "splunk-otel-overlay/values.overlay.yaml").read_text(encoding="utf-8")
    # The child's overlay adds 'otlp' to the metrics pipeline receivers list.
    # If the umbrella's load_child_overlay() drops the file, this is the line
    # that disappears from the composed overlay.
    assert "        metrics:\n          receivers:\n          - otlp\n" in overlay, (
        "Composed overlay's agent.config.service.pipelines.metrics.receivers is "
        "missing 'otlp'. The Intersight child's pipeline overlay was silently "
        "dropped during composition; load_child_overlay() likely failed to walk "
        f"all *.yaml files. Intersight child files: {[p.name for p in yaml_files]}"
    )


def test_live_validate_propagates_to_children_and_catches_intersight_export_errors() -> None:
    script = VALIDATE.read_text(encoding="utf-8")
    assert "command -v oc" in script
    assert "child_args+=(--live)" in script
    assert "unknown service opentelemetry.proto.collector.metrics.v1.MetricsService" in script
    assert "receiver_creator/nvidia" in script


def test_setup_exposes_existing_collector_apply_path() -> None:
    script = SETUP.read_text(encoding="utf-8")
    assert "--apply-existing-collector" in script
    assert "apply_existing_collector.py" in script
    assert "--set splunkObservability.accessToken" not in script


def test_existing_collector_apply_removes_stale_nvidia_and_forces_otlp_metrics() -> None:
    script = (
        REPO_ROOT
        / "skills/splunk-observability-cisco-ai-pod-integration/scripts/apply_existing_collector.py"
    ).read_text(encoding="utf-8")
    assert "receiver_creator/nvidia" in script
    assert "receiver_creator/dcgm-cisco" in script
    assert "prune_nexus_without_secret" in script
    assert "cisco-nexus-ssh" in script
    assert "metrics_receivers.insert(0, \"otlp\")" in script
    assert "--set-file" in script
    assert "--force-conflicts" in script
    assert "accessToken" in script


def test_all_rendered_shell_scripts_have_valid_bash_syntax(tmp_path: Path) -> None:
    """Regression: every rendered .sh file must pass `bash -n`.

    Catches a class of silent bash-quoting failures in the renderer's f-strings,
    e.g. echo "...accessToken=\"\\$(cat ...)\"" which produced nested unbalanced
    quotes that bash rejects with "syntax error near unexpected token '('".
    Operators only see this error when they actually run the handoff script;
    a static `bash -n` catches it before publication.
    """
    output = tmp_path / "rendered"
    result = run_setup("--render", "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)

    failures: list[tuple[Path, str]] = []
    for script in sorted(output.rglob("*.sh")):
        check = subprocess.run(
            ["bash", "-n", str(script)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if check.returncode != 0:
            failures.append((script, check.stderr.strip()))

    assert not failures, "Rendered shell scripts failed bash -n syntax check:\n" + "\n".join(
        f"  - {p.relative_to(output)}: {err}" for p, err in failures
    )


def test_hec_handoff_uses_correct_splunk_hec_service_setup_flags(tmp_path: Path) -> None:
    """Regression: the HEC handoff must use --token-name (not --hec-token-name) and
    --platform enterprise|cloud. splunk-hec-service-setup's setup.sh has no
    --hec-token-name flag; using it makes the handoff a no-op that fails at runtime.

    HEC handoff is opt-in via splunk_platform_logs.enabled in the spec, so we
    write a custom spec that enables it and re-render.
    """
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(
        "api_version: splunk-observability-cisco-ai-pod-integration/v1\n"
        "realm: us0\n"
        "cluster_name: test-cluster\n"
        "splunk_platform_logs:\n"
        "  enabled: true\n"
        "  hec_index: cisco_ai_pod\n"
        "  hec_token_name: splunk_otel_ai_pod_logs\n",
        encoding="utf-8",
    )
    output = tmp_path / "rendered"
    result = run_setup("--render", "--spec", str(spec_path), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    handoff_path = output / "scripts/handoff-hec-token.sh"
    assert handoff_path.is_file(), (
        f"HEC handoff script missing despite splunk_platform_logs.enabled=true. "
        f"Scripts emitted: {[p.name for p in (output / 'scripts').iterdir()]}"
    )
    handoff = handoff_path.read_text(encoding="utf-8")
    # Required: correct flags from splunk-hec-service-setup/scripts/setup.sh
    assert "--token-name " in handoff, (
        "HEC handoff is missing --token-name; splunk-hec-service-setup has no --hec-token-name flag"
    )
    assert "--platform " in handoff, "HEC handoff must specify --platform enterprise|cloud"
    assert "--default-index " in handoff
    assert "--allowed-indexes " in handoff
    # Negative: the broken flag must not appear.
    assert "--hec-token-name" not in handoff, (
        "HEC handoff is using the non-existent --hec-token-name flag"
    )


@pytest.mark.parametrize(
    "flag",
    [
        "--intersight-key-id",
        "--intersight-key",
        "--api-key",
        "--client-secret",
        "--o11y-token",
        "--access-token",
        "--token",
        "--bearer-token",
        "--api-token",
        "--sf-token",
        "--platform-hec-token",
        "--hec-token",
    ],
)
def test_direct_secret_flags_are_rejected(flag: str) -> None:
    result = run_setup("--render", flag, "INLINE_SHOULD_NOT_LEAK")
    assert result.returncode == 1
    assert "INLINE_SHOULD_NOT_LEAK" not in combined_output(result)


def test_idempotent_re_render(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    args = ["--render", "--output-dir", str(output)]
    first = run_setup(*args)
    second = run_setup(*args)
    assert first.returncode == 0, combined_output(first)
    assert second.returncode == 0, combined_output(second)
    first_overlay = (output / "splunk-otel-overlay/values.overlay.yaml").read_text(encoding="utf-8")
    assert (output / "splunk-otel-overlay/values.overlay.yaml").read_text(encoding="utf-8") == first_overlay
