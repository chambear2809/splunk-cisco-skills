"""Regressions for cisco-isovalent-platform-setup rendering."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/cisco-isovalent-platform-setup/scripts/setup.sh"


def run_setup(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    return subprocess.run(
        ["bash", str(SETUP), *args],
        cwd=REPO_ROOT,
        env=proc_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def write_spec(path: Path, **overrides: object) -> Path:
    spec: dict[str, object] = {
        "api_version": "cisco-isovalent-platform-setup/v1",
        "edition": "oss",
        "cluster_name": "lab-cluster",
        "namespaces": {
            "cilium": "kube-system",
            "tetragon": "tetragon",
        },
        "tetragon": {
            "export": {"mode": "file", "directory": "/var/run/cilium/tetragon", "filename": "tetragon.log"},
        },
        "tracing_policy": {"enabled": True, "name": "network-monitoring"},
    }
    spec.update(overrides)
    path.write_text(json.dumps(spec, indent=2, sort_keys=True), encoding="utf-8")
    return path


def write_fake_k8s_tools(bin_dir: Path, log_path: Path) -> None:
    bin_dir.mkdir()
    for name in ("helm", "kubectl"):
        script = bin_dir / name
        script.write_text(
            "#!/usr/bin/env bash\n"
            f"printf '{name} %s\\n' \"$*\" >> {log_path}\n"
            "exit 0\n",
            encoding="utf-8",
        )
        script.chmod(0o755)


def test_oss_render_produces_helm_values_and_install_scripts(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--validate", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    for f in (
        "helm/cilium-values.yaml",
        "helm/tetragon-values.yaml",
        "helm/tracing-policy.yaml",
        "scripts/install-cilium.sh",
        "scripts/install-tetragon.sh",
        "scripts/preflight.sh",
        "feature-catalog.json",
        "feature-matrix.md",
        "coverage-report.json",
        "environment-profiles.json",
        "environment-profiles.md",
        "apply-plan.json",
        "doctor-report.md",
        "metadata.json",
    ):
        assert (output / f).is_file(), f"Missing rendered file: {f}"
    install_cilium = (output / "scripts/install-cilium.sh").read_text(encoding="utf-8")
    # OSS edition uses cilium/cilium chart from helm.cilium.io.
    assert "helm.cilium.io" in install_cilium
    assert "cilium/cilium" in install_cilium
    # Enterprise chart name must NOT appear in OSS render.
    assert "isovalent/cilium-enterprise" not in install_cilium
    assert "ISOVALENT_LICENSE_FILE" not in install_cilium
    cilium = (output / "helm/cilium-values.yaml").read_text(encoding="utf-8")
    assert "kubeProxyReplacement: true" in cilium
    assert "method: cronJob" in cilium


def test_feature_catalog_has_zero_missing_product_rows(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    coverage = json.loads((output / "coverage-report.json").read_text(encoding="utf-8"))
    catalog = json.loads((output / "feature-catalog.json").read_text(encoding="utf-8"))
    allowed = set(catalog["allowed_statuses"])
    assert coverage["missing_features"] == []
    assert coverage["unsupported_without_reason"] == []
    assert coverage["target_feature_count"] == coverage["covered_feature_count"]
    for feature in coverage["features"]:
        assert feature["status"] in allowed
        if feature["status"] in {"unsupported_with_reason", "not_applicable", "gated_private"}:
            assert feature["reason"]


def test_apply_plan_commands_reference_rendered_scripts(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    plan = json.loads((output / "apply-plan.json").read_text(encoding="utf-8"))
    for step in plan["steps"]:
        command = step["command"]
        assert command[0] == "bash"
        assert Path(command[1]).is_file(), f"{step['section']} command points to a missing script"


def test_help_lists_lifecycle_modes_and_gates() -> None:
    result = run_setup("--help")
    assert result.returncode == 0
    help_text = result.stdout
    for text in (
        "--discover",
        "--preflight",
        "--doctor",
        "--backup",
        "--upgrade-plan",
        "--rollback-plan",
        "--uninstall-plan",
        "--feature-matrix",
        "--accept-k8s-apply",
        "--accept-isovalent-disruptive-change",
        "--kube-context",
    ):
        assert text in help_text


def test_enterprise_render_uses_isovalent_charts(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", edition="enterprise")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    install_cilium = (output / "scripts/install-cilium.sh").read_text(encoding="utf-8")
    assert "helm.isovalent.com" in install_cilium
    assert "isovalent/cilium-enterprise" in install_cilium
    assert "--set-file \"enterprise.license=${ISOVALENT_LICENSE_FILE}\"" in install_cilium
    assert '$(cat "${ISOVALENT_LICENSE_FILE}")' not in install_cilium


def test_private_chart_sections_are_gated_until_access_verified(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        edition="enterprise",
        apply={"sections": "hubble,timescape"},
    )
    result = run_setup(
        "--render",
        "--enable-hubble-enterprise",
        "--enable-timescape",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, combined_output(result)
    coverage = json.loads((output / "coverage-report.json").read_text(encoding="utf-8"))
    statuses = {feature["id"]: feature["status"] for feature in coverage["features"]}
    assert statuses["isovalent.hubble_enterprise"] == "gated_private"
    assert statuses["isovalent.hubble_timescape"] == "gated_private"
    assert "exit 1" in (output / "scripts/apply-hubble.sh").read_text(encoding="utf-8")
    assert "exit 1" in (output / "scripts/install-hubble-timescape.sh").read_text(encoding="utf-8")
    plan = json.loads((output / "apply-plan.json").read_text(encoding="utf-8"))
    steps = {step["section"]: step for step in plan["steps"]}
    assert steps["hubble"]["command_class"] == "gated_private"
    assert steps["timescape"]["command_class"] == "gated_private"
    assert steps["hubble"]["requires_accept_k8s_apply"] is False
    assert steps["timescape"]["requires_accept_k8s_apply"] is False
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["enable_hubble_enterprise"] is True
    assert metadata["enable_timescape"] is True
    assert "private" in " ".join(metadata.get("warnings", [])).lower()


def test_private_chart_access_verified_enables_hubble_and_timescape_apply(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        edition="enterprise",
        apply={"sections": "hubble,timescape"},
    )
    result = run_setup(
        "--render",
        "--enable-hubble-enterprise",
        "--enable-timescape",
        "--private-chart-access-verified",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, combined_output(result)
    coverage = json.loads((output / "coverage-report.json").read_text(encoding="utf-8"))
    statuses = {feature["id"]: feature["status"] for feature in coverage["features"]}
    assert statuses["isovalent.hubble_enterprise"] == "helm_apply"
    assert statuses["isovalent.hubble_timescape"] == "helm_apply"
    hubble = (output / "scripts/apply-hubble.sh").read_text(encoding="utf-8")
    timescape = (output / "scripts/install-hubble-timescape.sh").read_text(encoding="utf-8")
    assert 'show values "isovalent/hubble-enterprise"' in hubble
    assert 'upgrade --install hubble-enterprise "isovalent/hubble-enterprise"' in hubble
    assert 'show values "isovalent/hubble-timescape"' in timescape
    assert 'upgrade --install hubble-timescape "isovalent/hubble-timescape"' in timescape
    plan = json.loads((output / "apply-plan.json").read_text(encoding="utf-8"))
    steps = {step["section"]: step for step in plan["steps"]}
    assert steps["hubble"]["command_class"] == "mutating"
    assert steps["timescape"]["command_class"] == "mutating"
    assert steps["hubble"]["requires_accept_k8s_apply"] is True
    assert steps["timescape"]["requires_accept_k8s_apply"] is True
    assert steps["hubble"]["requires_isovalent_license_file"] is True
    assert steps["timescape"]["requires_isovalent_license_file"] is True


def test_enterprise_only_sections_in_oss_render_as_gated_scripts(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", apply={"sections": "dnsproxy,timescape"})
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    plan = json.loads((output / "apply-plan.json").read_text(encoding="utf-8"))
    steps = {step["section"]: step for step in plan["steps"]}
    for section in ("dnsproxy", "timescape"):
        command = steps[section]["command"]
        assert command[0] == "bash"
        assert Path(command[1]).is_file()
        assert steps[section]["command_class"] == "gated_private"
        assert steps[section]["requires_accept_k8s_apply"] is False
    assert "exit 1" in (output / "scripts/install-cilium-dnsproxy.sh").read_text(encoding="utf-8")
    assert "exit 1" in (output / "scripts/install-hubble-timescape.sh").read_text(encoding="utf-8")


def test_openshift_distribution_renders_scc_assets(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", distribution="openshift")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    assert (output / "k8s/openshift-scc.yaml").is_file()
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    profiles = json.loads((output / "environment-profiles.json").read_text(encoding="utf-8"))
    assert metadata["distribution"] == "openshift"
    assert "openshift" in profiles


@pytest.mark.parametrize(
    "distribution",
    ["eks-byocni", "openshift", "aks-byocni", "gke", "rke2", "k3s", "generic"],
)
def test_representative_distribution_profiles_render(tmp_path: Path, distribution: str) -> None:
    output = tmp_path / f"rendered-{distribution}"
    spec = write_spec(tmp_path / f"spec-{distribution}.json", distribution=distribution)
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    coverage = json.loads((output / "coverage-report.json").read_text(encoding="utf-8"))
    assert coverage["distribution"] == distribution
    assert coverage["distribution_profile"]["supported_install_path"]


def test_scoped_cilium_sections_render_non_empty_value_overlays(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    expected = {
        "gateway-api": "gatewayAPI:\n  enabled: true",
        "ingress": "ingressController:\n  enabled: true",
        "egress-gateway": "egressGateway:\n  enabled: true",
        "bgp": "bgpControlPlane:\n  enabled: true",
        "l2-announcements": "l2announcements:\n  enabled: true",
        "encryption": "encryption:\n  enabled: true",
        "host-firewall": "hostFirewall:\n  enabled: true",
    }
    for section, needle in expected.items():
        overlay = (output / f"helm/cilium-section-{section}-values.yaml").read_text(encoding="utf-8")
        script = (output / f"scripts/apply-{section}.sh").read_text(encoding="utf-8")
        assert needle in overlay
        assert f"cilium-section-{section}-values.yaml" in script


def test_clustermesh_uses_cilium_cli_not_generic_helm_reapply(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    script = (output / "scripts/apply-clustermesh.sh").read_text(encoding="utf-8")
    assert "cilium clustermesh enable" in script
    assert "cilium clustermesh connect" in script
    assert "helm upgrade --install cilium" not in script


def test_runtime_policy_bundle_contains_claimed_observe_only_policy_types(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    policy = (output / "helm/tetragon-runtime-policies.yaml").read_text(encoding="utf-8")
    assert "kind: TracingPolicyNamespaced" in policy
    assert "security_file_open" in policy
    assert "__sys_setuid" in policy
    assert "__sys_setgid" in policy
    assert "action:" not in policy


def test_tetragon_default_export_mode_file(tmp_path: Path) -> None:
    """Default Tetragon export mode is `file` -- coordinates with the integration skill."""
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    tetragon = (output / "helm/tetragon-values.yaml").read_text(encoding="utf-8")
    assert "exportDirectory: /var/run/cilium/tetragon" in tetragon
    assert "exportFilename: tetragon.log" in tetragon
    assert "exportFilePerm: '644'" in tetragon


def test_legacy_fluentd_emits_deprecation_warning(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup(
        "--render",
        "--spec",
        str(spec),
        "--export-mode",
        "fluentd",
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, combined_output(result)
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    warnings = " ".join(metadata.get("warnings", []))
    assert "DEPRECATED" in warnings
    assert "2025-06-24" in warnings


@pytest.mark.parametrize("flag", ["--license", "--license-key", "--pull-secret"])
def test_direct_secret_flags_are_rejected(flag: str) -> None:
    result = run_setup("--render", flag, "INLINE_SHOULD_NOT_LEAK")
    assert result.returncode == 1
    assert "isovalent" in combined_output(result).lower()
    assert "INLINE_SHOULD_NOT_LEAK" not in combined_output(result)


@pytest.mark.parametrize("flag", ["--isovalent-license-file", "--isovalent-pull-secret-file"])
def test_secret_file_flags_must_point_to_readable_files(tmp_path: Path, flag: str) -> None:
    missing = tmp_path / "missing-secret"
    result = run_setup("--render", flag, str(missing))
    assert result.returncode != 0
    assert "not readable or does not exist" in combined_output(result)


def test_live_commands_require_kube_context_or_explicit_current_context(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--discover", "--spec", str(spec), "--output-dir", str(tmp_path / "rendered"))
    assert result.returncode != 0
    assert "--kube-context" in combined_output(result)


def test_apply_without_k8s_acceptance_refuses_before_mutation(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup(
        "--apply",
        "tetragon",
        "--allow-current-context",
        "--spec",
        str(spec),
        "--output-dir",
        str(tmp_path / "rendered"),
    )
    assert result.returncode != 0
    assert "requires --accept-k8s-apply" in combined_output(result)


def test_disruptive_apply_requires_second_gate(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup(
        "--apply",
        "cilium",
        "--accept-k8s-apply",
        "--allow-current-context",
        "--spec",
        str(spec),
        "--output-dir",
        str(tmp_path / "rendered"),
    )
    assert result.returncode != 0
    assert "--accept-isovalent-disruptive-change" in combined_output(result)


@pytest.mark.parametrize("distribution", ["aks-managed-cilium", "gke-dataplane-v2"])
def test_managed_cilium_profiles_make_cilium_discover_only(tmp_path: Path, distribution: str) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        distribution=distribution,
        apply={"sections": "cilium,tetragon"},
    )
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    plan = json.loads((output / "apply-plan.json").read_text(encoding="utf-8"))
    steps = {step["section"]: step for step in plan["steps"]}
    assert steps["cilium"]["command_class"] == "discover_only"
    assert steps["cilium"]["automation"] == "none"
    assert steps["cilium"]["requires_accept_k8s_apply"] is False
    assert steps["cilium"]["requires_accept_isovalent_disruptive_change"] is False
    assert steps["tetragon"]["command_class"] == "mutating"

    install_cilium = (output / "scripts/install-cilium.sh").read_text(encoding="utf-8")
    assert f"ERROR: {distribution} uses a provider-managed Cilium dataplane." in install_cilium
    assert "Helm-replace provider-owned Cilium" in install_cilium
    assert "upgrade --install cilium" not in install_cilium


@pytest.mark.parametrize("distribution", ["aks-managed-cilium", "gke-dataplane-v2"])
def test_managed_cilium_apply_fails_closed_before_helm_upgrade(tmp_path: Path, distribution: str) -> None:
    fake_bin = tmp_path / "bin"
    log_path = tmp_path / "commands.log"
    write_fake_k8s_tools(fake_bin, log_path)
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        distribution=distribution,
        apply={"sections": "cilium"},
    )
    result = run_setup(
        "--apply",
        "cilium",
        "--dry-run",
        "--kube-context",
        "unit-test",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
        env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0
    assert "provider-managed Cilium dataplane" in combined_output(result)
    command_log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    assert "upgrade --install cilium" not in command_log


def test_unavailable_apply_step_fails_instead_of_silent_skip(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup(
        "--apply",
        "dnsproxy",
        "--dry-run",
        "--kube-context",
        "unit-test",
        "--spec",
        str(spec),
        "--output-dir",
        str(tmp_path / "rendered"),
    )
    assert result.returncode != 0
    output = combined_output(result)
    assert "Cilium DNSProxy is gated" in output
    assert "requested apply step 'dnsproxy' is not available" not in output


def test_backup_uses_namespace_scoped_helm_get_and_history() -> None:
    setup = SETUP.read_text(encoding="utf-8")
    assert 'helm_release_namespace()' in setup
    assert 'get values "${release}" -n "${namespace}" -a' in setup
    assert 'history "${release}" -n "${namespace}"' in setup
    assert 'get values "${release}" -A' not in setup
    assert 'history "${release}" -A' not in setup


def test_apply_dry_run_uses_fake_helm_and_kubectl_without_acceptance(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    log_path = tmp_path / "commands.log"
    write_fake_k8s_tools(fake_bin, log_path)
    spec = write_spec(tmp_path / "spec.json")
    output = tmp_path / "rendered"
    result = run_setup(
        "--apply",
        "tetragon",
        "--dry-run",
        "--kube-context",
        "unit-test",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
        env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, combined_output(result)
    command_log = log_path.read_text(encoding="utf-8")
    assert "helm --kube-context unit-test upgrade --install tetragon" in command_log
    assert "--dry-run" in command_log
    assert "kubectl --context unit-test apply -f" in command_log
    assert "--dry-run=server" in command_log
    state = json.loads((output / "state/live-action-state.json").read_text(encoding="utf-8"))
    assert state["kube_context"] == "unit-test"


def test_gated_private_apply_prints_runbook_without_k8s_acceptance_or_license(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json", edition="enterprise")
    result = run_setup(
        "--apply",
        "hubble",
        "--enable-hubble-enterprise",
        "--kube-context",
        "unit-test",
        "--spec",
        str(spec),
        "--output-dir",
        str(tmp_path / "rendered"),
    )
    output = combined_output(result)
    assert result.returncode != 0
    assert "private chart" in output.lower()
    assert "requires --accept-k8s-apply" not in output
    assert "--isovalent-license-file" not in output


def test_verified_private_apply_requires_acceptance_then_license(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json", edition="enterprise")
    no_accept = run_setup(
        "--apply",
        "hubble",
        "--enable-hubble-enterprise",
        "--private-chart-access-verified",
        "--kube-context",
        "unit-test",
        "--spec",
        str(spec),
        "--output-dir",
        str(tmp_path / "rendered-no-accept"),
    )
    assert no_accept.returncode != 0
    assert "requires --accept-k8s-apply" in combined_output(no_accept)

    no_license = run_setup(
        "--apply",
        "hubble",
        "--enable-hubble-enterprise",
        "--private-chart-access-verified",
        "--accept-k8s-apply",
        "--kube-context",
        "unit-test",
        "--spec",
        str(spec),
        "--output-dir",
        str(tmp_path / "rendered-no-license"),
    )
    assert no_license.returncode != 0
    assert "requires --isovalent-license-file" in combined_output(no_license)


def test_spec_apply_sections_drive_apply_execution_when_cli_omits_steps(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    log_path = tmp_path / "commands.log"
    write_fake_k8s_tools(fake_bin, log_path)
    spec = write_spec(tmp_path / "spec.json", apply={"sections": "runtime-policies"})
    output = tmp_path / "rendered"
    result = run_setup(
        "--apply",
        "--dry-run",
        "--kube-context",
        "unit-test",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
        env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, combined_output(result)
    command_log = log_path.read_text(encoding="utf-8")
    assert "tetragon-runtime-policies.yaml" in command_log
    assert "upgrade --install cilium" not in command_log
    assert "upgrade --install tetragon" not in command_log


def test_enterprise_scoped_cilium_apply_scripts_include_repo_and_secret_file_guards(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", edition="enterprise", apply={"sections": "gateway-api"})
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    script = (output / "scripts/apply-gateway-api.sh").read_text(encoding="utf-8")
    assert "helm.isovalent.com" in script
    assert "isovalent/cilium-enterprise" in script
    assert 'SET_FILE_ARGS+=(--set-file "enterprise.license=${ISOVALENT_LICENSE_FILE}")' in script
    assert 'imagePullSecrets[0].name=isovalent-pull-secret' in script
    assert script.index('create namespace "${NAMESPACE}"') < script.index("create secret generic isovalent-pull-secret")
    assert '$(cat "${ISOVALENT_LICENSE_FILE}")' not in script


def test_idempotent_re_render(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    args = ["--render", "--spec", str(spec), "--output-dir", str(output)]
    first = run_setup(*args)
    second = run_setup(*args)
    assert first.returncode == 0, combined_output(first)
    assert second.returncode == 0, combined_output(second)
    first_cilium = (output / "helm/cilium-values.yaml").read_text(encoding="utf-8")
    assert (output / "helm/cilium-values.yaml").read_text(encoding="utf-8") == first_cilium


def test_dry_run_json(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup(
        "--render",
        "--spec",
        str(spec),
        "--cluster-name",
        "isovalent-demo",
        "--dry-run",
        "--json",
        "--output-dir",
        str(tmp_path / "rendered"),
    )
    assert result.returncode == 0, combined_output(result)
    plan = json.loads(result.stdout)
    assert plan["skill"] == "cisco-isovalent-platform-setup"
    assert plan["edition"] == "oss"
    assert plan["cluster_name"] == "isovalent-demo"


def test_cluster_name_override_lands_in_values_and_metadata(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup(
        "--render",
        "--spec",
        str(spec),
        "--cluster-name",
        "isovalent-demo",
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, combined_output(result)
    cilium = (output / "helm/cilium-values.yaml").read_text(encoding="utf-8")
    tetragon = (output / "helm/tetragon-values.yaml").read_text(encoding="utf-8")
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert "name: isovalent-demo" in cilium
    assert "clusterName: isovalent-demo" in tetragon
    assert metadata["cluster_name"] == "isovalent-demo"
