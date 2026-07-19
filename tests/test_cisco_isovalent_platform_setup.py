"""Regressions for cisco-isovalent-platform-setup rendering."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/cisco-isovalent-platform-setup/scripts/setup.sh"
VALIDATE = REPO_ROOT / "skills/cisco-isovalent-platform-setup/scripts/validate.sh"


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


def run_validate(
    output_dir: Path,
    *,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    proc_env = os.environ.copy()
    proc_env.update(env)
    return subprocess.run(
        [
            "bash",
            str(VALIDATE),
            "--output-dir",
            str(output_dir),
            "--live",
            "--kube-context",
            "unit-test",
        ],
        cwd=REPO_ROOT,
        env=proc_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def run_static_validate(output_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(VALIDATE), "--output-dir", str(output_dir)],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def write_fake_live_validation_tools(bin_dir: Path) -> None:
    bin_dir.mkdir()
    helm = bin_dir / "helm"
    helm.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ -n "${FAKE_COMMAND_LOG:-}" ]]; then
    printf 'helm %s\n' "$*" >> "${FAKE_COMMAND_LOG}"
fi
if [[ " $* " == *" list --all-namespaces --deployed --failed --pending --uninstalling --superseded --uninstalled --output json "* ]]; then
    printf '%s\n' "${FAKE_HELM_RELEASES_JSON}"
    exit 0
fi
if [[ " $* " == *" status "* ]]; then
    printf 'legacy helm status should not be used\n' >&2
    exit 3
fi
if [[ " $* " == *" get metadata "* ]]; then
    release=""
    previous=""
    for argument in "$@"; do
        if [[ "${previous}" == "metadata" ]]; then release="${argument}"; break; fi
        previous="${argument}"
    done
    FAKE_RELEASE="${release}" python3 - <<'PY'
import json
import os
import re

release = os.environ["FAKE_RELEASE"]
rows = json.loads(os.environ["FAKE_HELM_RELEASES_JSON"])
row = next(item for item in rows if item.get("name") == release)
match = re.fullmatch(r"(.+)-(v?[0-9].*)", str(row.get("chart") or ""))
if match is None:
    raise SystemExit(2)
payload = {
    "name": release,
    "namespace": row.get("namespace"),
    "chart": match.group(1),
    "version": match.group(2),
    "status": "deployed",
}
override = os.environ.get("FAKE_HELM_METADATA_JSON")
if override:
    payload.update(json.loads(override))
print(json.dumps(payload))
PY
    exit 0
fi
printf 'unexpected helm command: %s\n' "$*" >&2
exit 2
""",
        encoding="utf-8",
    )
    helm.chmod(0o755)

    kubectl = bin_dir / "kubectl"
    kubectl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ -n "${FAKE_COMMAND_LOG:-}" ]]; then
    printf 'kubectl %s\n' "$*" >> "${FAKE_COMMAND_LOG}"
fi
if [[ " $* " == *" version -o json "* ]]; then
    printf '%s\n' "${FAKE_KUBECTL_VERSION_JSON}"
    exit 0
fi
if [[ " $* " == *" -n kube-system get pods -l k8s-app=cilium -o json "* ]]; then
    printf '%s\n' "${FAKE_CILIUM_PODS_JSON}"
    exit 0
fi
if [[ " $* " == *" -n tetragon get pods -l app.kubernetes.io/name=tetragon -o json "* ]]; then
    printf '%s\n' "${FAKE_TETRAGON_PODS_JSON}"
    exit 0
fi
if [[ " $* " == *" get pods -l app.kubernetes.io/instance=hubble-enterprise -o json "* ]]; then
    printf '%s\n' "${FAKE_HUBBLE_ENTERPRISE_PODS_JSON}"
    exit 0
fi
if [[ " $* " == *" get pods -l k8s-app=cilium-dnsproxy -o json "* ]]; then
    printf '%s\n' "${FAKE_DNSPROXY_PODS_JSON}"
    exit 0
fi
if [[ " $* " == *" get statefulsets.apps --all-namespaces -o json "* ]]; then
    printf '%s\n' "${FAKE_STATEFULSETS_JSON}"
    exit 0
fi
if [[ " $* " == *"/pods/"*"/log?"* ]]; then
    if [[ "${FAKE_LOG_FAILURE:-false}" == "true" ]]; then
        printf 'pod log API unavailable\n' >&2
        exit 1
    fi
    if [[ -n "${FAKE_TETRAGON_LOG_TEXT:-}" ]]; then
        printf '%s\n' "${FAKE_TETRAGON_LOG_TEXT}"
    else
        printf 'level=info msg="tetragon running"\n'
    fi
    exit 0
fi
if [[ " $* " == *"/services/cilium-dnsproxy:9967/"* ]]; then
    if [[ "${FAKE_DNSPROXY_PRESENT:-false}" == "true" ]]; then
        if [[ -n "${FAKE_DNSPROXY_METRICS_TEXT:-}" ]]; then
            printf '%s\n' "${FAKE_DNSPROXY_METRICS_TEXT}"
        else
            printf '# HELP fake_dnsproxy_metric fixture\nfake_dnsproxy_metric 1\n'
        fi
        exit 0
    fi
    printf 'Error from server (NotFound): services "cilium-dnsproxy" not found\n' >&2
    exit 1
fi
if [[ " $* " == *" get --raw "*"/metrics"* ]]; then
    if [[ -n "${FAKE_MISSING_METRIC_PATH:-}" && " $* " == *"${FAKE_MISSING_METRIC_PATH}"* ]]; then
        printf 'Error from server (NotFound): metrics service not found\n' >&2
        exit 1
    fi
    if [[ -n "${FAKE_HIVE_HEALTH_PATH:-}" && " $* " == *"${FAKE_HIVE_HEALTH_PATH}"* ]]; then
        printf '%s\n' "${FAKE_HIVE_METRICS_TEXT}"
        exit 0
    fi
    if [[ "${FAKE_LARGE_METRICS_RESPONSE:-false}" == "true" ]]; then
        i=0
        while [[ "${i}" -lt 5000 ]]; do
            printf '# HELP filler_%s synthetic fixture\n' "${i}"
            i=$((i + 1))
        done
        printf 'openmetrics_fixture{kind="scientific"} -1.25e+06 123\n'
        exit 0
    fi
    if [[ -n "${FAKE_METRICS_TEXT:-}" ]]; then
        printf '%s\n' "${FAKE_METRICS_TEXT}"
        exit 0
    fi
    printf '# HELP fake_metric fixture\nfake_metric 1\n'
    exit 0
fi
printf 'unexpected kubectl command: %s\n' "$*" >&2
exit 2
""",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)


def ready_pod_inventory(name: str, container: str) -> str:
    return json.dumps(
        {
            "items": [
                {
                    "metadata": {"name": name},
                    "spec": {"containers": [{"name": container}]},
                    "status": {
                        "phase": "Running",
                        "containerStatuses": [{"name": container, "ready": True}],
                    },
                }
            ]
        }
    )


def live_validation_env(bin_dir: Path, *, edition: str = "oss") -> dict[str, str]:
    cilium_version = "1.18.8" if edition == "enterprise" else "1.18.10"
    tetragon_version = "1.18.1" if edition == "enterprise" else "1.7.0"
    return {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_HELM_RELEASES_JSON": json.dumps(
            [
                {
                    "name": "cilium",
                    "namespace": "kube-system",
                    "status": "deployed",
                    "chart": f"cilium-{cilium_version}",
                },
                {
                    "name": "tetragon",
                    "namespace": "tetragon",
                    "status": "deployed",
                    "chart": f"tetragon-{tetragon_version}",
                },
            ]
        ),
        "FAKE_CILIUM_PODS_JSON": ready_pod_inventory("cilium-agent-abc", "cilium-agent"),
        "FAKE_TETRAGON_PODS_JSON": ready_pod_inventory("tetragon-abc", "tetragon"),
        "FAKE_HUBBLE_ENTERPRISE_PODS_JSON": ready_pod_inventory(
            "hubble-enterprise-abc", "hubble-enterprise"
        ),
        "FAKE_DNSPROXY_PODS_JSON": ready_pod_inventory("cilium-dnsproxy-abc", "dnsproxy"),
        "FAKE_STATEFULSETS_JSON": json.dumps({"items": []}),
        "FAKE_KUBECTL_VERSION_JSON": json.dumps(
            {
                "clientVersion": {"major": "1", "minor": "35"},
                "serverVersion": {"major": "1", "minor": "34"},
            }
        ),
    }


def timescape_statefulset_inventory(
    owner: str,
    *,
    namespace: str = "kube-system",
    status_overrides: dict[str, object] | None = None,
) -> str:
    status: dict[str, object] = {
        "observedGeneration": 3,
        "currentReplicas": 2,
        "updatedReplicas": 2,
        "readyReplicas": 2,
        "currentRevision": "timescape-rev-a",
        "updateRevision": "timescape-rev-a",
    }
    status.update(status_overrides or {})
    return json.dumps(
        {
            "items": [
                {
                    "metadata": {
                        "name": "hubble-timescape",
                        "namespace": namespace,
                        "generation": 3,
                        "annotations": {"meta.helm.sh/release-name": owner},
                        "labels": {"app.kubernetes.io/name": "hubble-timescape"},
                    },
                    "spec": {
                        "replicas": 2,
                        "template": {
                            "spec": {
                                "containers": [
                                    {"name": "timescape", "image": "example.invalid/hubble-timescape:test"}
                                ]
                            }
                        },
                    },
                    "status": status,
                }
            ]
        }
    )


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
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["helm_charts"]["cilium"]["version"] == "1.18.10"
    assert metadata["helm_charts"]["tetragon"]["version"] == "1.7.0"
    assert '--version "1.18.10"' in install_cilium
    assert '--version "1.7.0"' in (output / "scripts/install-tetragon.sh").read_text(
        encoding="utf-8"
    )


def test_validate_dry_run_is_rejected_for_missing_or_tampered_packets(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"
    missing_result = run_setup("--validate", "--dry-run", "--output-dir", str(missing))
    assert missing_result.returncode != 0
    assert "--validate cannot be combined with --dry-run" in combined_output(missing_result)
    assert not missing.exists()

    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    metadata_path = output / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["skill"] = "tampered-skill"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    tampered = run_setup("--validate", "--dry-run", "--output-dir", str(output))
    assert tampered.returncode != 0
    assert "--validate cannot be combined with --dry-run" in combined_output(tampered)


def test_gke_oss_render_rejects_known_bad_cilium_1_18_8_baseline(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", distribution="gke")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    install = (output / "scripts/install-cilium.sh").read_text(encoding="utf-8")
    assert metadata["helm_charts"]["cilium"]["version"] == "1.18.10"
    assert '--version "1.18.10"' in install
    assert '--version "1.18.8"' not in install


def test_rendered_helm_contract_is_exact_version_atomic_and_recorded(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", edition="enterprise")
    result = run_setup(
        "--render",
        "--enable-dnsproxy",
        "--enable-hubble-enterprise",
        "--enable-timescape",
        "--private-chart-access-verified",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, combined_output(result)

    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["helm_charts"]["cilium"]["version"] == "1.18.8"
    assert metadata["helm_charts"]["tetragon"]["version"] == "1.18.1"
    assert metadata["helm_charts"]["cilium-dnsproxy"]["version"] == "1.18.8"
    assert metadata["helm_charts"]["hubble-enterprise"]["version"] == "1.18.8"
    assert metadata["helm_charts"]["hubble-timescape"]["version"] == "1.18.8"
    assert all(item["archive_sha256"] is None for item in metadata["helm_charts"].values())
    assert "does not distribute upstream chart archives" in metadata["chart_provenance_gap"]

    expected_versions = {
        "install-cilium.sh": "1.18.8",
        "install-tetragon.sh": "1.18.1",
        "install-cilium-dnsproxy.sh": "1.18.8",
        "install-hubble-enterprise.sh": "1.18.8",
        "install-hubble-timescape.sh": "1.18.8",
    }
    for script_name, version in expected_versions.items():
        script = (output / "scripts" / script_name).read_text(encoding="utf-8")
        assert f'--version "{version}"' in script
        assert '--atomic --wait --timeout "10m" --history-max 10' in script
        assert "show chart" in script
        assert 'HELM_DRY_RUN+=(--hide-secret)' in script
        assert "requires upgrade --hide-secret support" in script


def test_static_validation_rejects_tampered_chart_contract(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    metadata_path = output / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["helm_charts"]["cilium"]["version"] = "1.18.7"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    result = run_static_validate(output)

    assert result.returncode != 0
    assert "must pin audited version 1.18.10" in combined_output(result)


@pytest.mark.parametrize(
    "namespace",
    (
        "UpperCase",
        "-leading",
        "trailing-",
        "contains.dot",
        "$(touch-should-never-run)",
        "a" * 64,
    ),
)
def test_render_rejects_unsafe_or_invalid_namespace_values(tmp_path: Path, namespace: str) -> None:
    spec = write_spec(
        tmp_path / "spec.json",
        namespaces={"cilium": namespace, "tetragon": "tetragon"},
    )
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(tmp_path / "rendered"))
    assert result.returncode != 0
    assert "DNS-1123" in combined_output(result)


@pytest.mark.parametrize("minimum", ("5", "5.x", "5.10;id", "$(id)", "5.10\ncommand"))
def test_render_rejects_unsafe_kernel_minimum(tmp_path: Path, minimum: str) -> None:
    spec = write_spec(
        tmp_path / "spec.json",
        kernel_preflight={"enable": True, "minimum_version": minimum},
    )
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(tmp_path / "rendered"))
    assert result.returncode != 0
    assert "numeric major.minor" in combined_output(result)


def test_validated_namespace_and_kernel_are_rendered_as_safe_variables(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        namespaces={
            "cilium": "network-system",
            "tetragon": "runtime-system",
            "hubble_enterprise": "hubble-system",
            "cilium_dnsproxy": "dns-system",
            "hubble_timescape": "timescape-system",
        },
        kernel_preflight={"enable": True, "minimum_version": "6.1.2"},
    )
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    install = (output / "scripts/install-cilium.sh").read_text(encoding="utf-8")
    preflight = (output / "scripts/preflight.sh").read_text(encoding="utf-8")
    assert "DEFAULT_NAMESPACE=network-system" in install
    assert 'NAMESPACE="${1:-${DEFAULT_NAMESPACE}}"' in install
    assert "MINIMUM_KERNEL=6.1.2" in preflight
    assert 'awk -v min="${MINIMUM_KERNEL}"' in preflight


def test_kernel_preflight_compares_major_minor_and_patch(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        kernel_preflight={"enable": True, "minimum_version": "6.1.2"},
    )
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    kubectl = fake_bin / "kubectl"
    kubectl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"get nodes"* ]]; then
    printf '%s\n' \\
        $'below-patch\t6.1.0-test' \\
        $'exact-patch\t6.1.2-test' \\
        $'newer-minor\t6.2.0-test' \\
        $'older-minor\t6.0.99-test'
elif [[ "$*" == *" get ds aws-node"* ]]; then
    exit 1
else
    exit 2
fi
""",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    result = subprocess.run(
        ["bash", str(output / "scripts/preflight.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert "below-patch\t6.1.0-test\tWARN" in result.stdout
    assert "exact-patch\t6.1.2-test\tOK" in result.stdout
    assert "newer-minor\t6.2.0-test\tOK" in result.stdout
    assert "older-minor\t6.0.99-test\tWARN" in result.stdout


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


def test_static_validation_fails_closed_on_incomplete_tetragon_file_export(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    values_path = output / "helm/tetragon-values.yaml"
    values = values_path.read_text(encoding="utf-8")
    values_path.write_text(values.replace("  exportFilename: tetragon.log\n", ""), encoding="utf-8")

    result = subprocess.run(
        ["bash", str(VALIDATE), "--output-dir", str(output)],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode != 0
    assert "file export requires tetragon.exportFilename" in combined_output(result)


def test_static_validation_rejects_incomplete_fluentd_mapping(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup(
        "--render",
        "--export-mode",
        "fluentd",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert rendered.returncode == 0, combined_output(rendered)
    (output / "helm/tetragon-values.yaml").write_text(
        "tetragon:\n  clusterName: lab-cluster\n  export:\n    mode: fluentd\n",
        encoding="utf-8",
    )

    result = run_static_validate(output)

    assert result.returncode != 0
    assert "requires tetragon.export.fluentd mapping" in combined_output(result)


def test_static_validation_rejects_inline_fluentd_token_without_echoing_it(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup(
        "--render",
        "--export-mode",
        "fluentd",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert rendered.returncode == 0, combined_output(rendered)
    values = output / "helm/tetragon-values.yaml"
    synthetic = "SYNTHETIC_INLINE_TOKEN_MUST_NOT_APPEAR"
    values.write_text(
        values.read_text(encoding="utf-8").replace("PLACEHOLDER_HEC_TOKEN", synthetic),
        encoding="utf-8",
    )

    result = run_static_validate(output)

    assert result.returncode != 0
    assert "must remain PLACEHOLDER_HEC_TOKEN" in combined_output(result)
    assert synthetic not in combined_output(result)


def test_structured_scrub_rejects_inline_yaml_license_without_echoing_value(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    values = output / "helm/cilium-values.yaml"
    synthetic = "SYNTHETIC_LICENSE_VALUE_MUST_NOT_APPEAR"
    values.write_text(
        values.read_text(encoding="utf-8") + f"enterprise:\n  license: {synthetic}\n",
        encoding="utf-8",
    )

    result = run_static_validate(output)

    assert result.returncode != 0
    assert "inline credential material found" in combined_output(result)
    assert "enterprise.license" in combined_output(result)
    assert synthetic not in combined_output(result)


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


def test_live_validation_fails_when_required_helm_release_is_missing(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin)
    env["FAKE_HELM_RELEASES_JSON"] = json.dumps(
        [
            {
                "name": "tetragon",
                "namespace": "tetragon",
                "status": "deployed",
                "chart": "tetragon-1.7.0",
            }
        ]
    )

    result = run_validate(output, env=env)

    assert result.returncode != 0
    assert "required Helm release cilium is not installed" in combined_output(result)


def test_live_validation_rejects_chart_version_drift(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin)
    releases = json.loads(env["FAKE_HELM_RELEASES_JSON"])
    next(item for item in releases if item["name"] == "cilium")["chart"] = "cilium-1.18.7"
    env["FAKE_HELM_RELEASES_JSON"] = json.dumps(releases)

    result = run_validate(output, env=env)

    assert result.returncode != 0
    assert "did not confirm a current deployed release for cilium" in combined_output(result)


def test_live_validation_rejects_unsupported_kubectl_server_skew(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin)
    env["FAKE_KUBECTL_VERSION_JSON"] = json.dumps(
        {
            "clientVersion": {"major": "1", "minor": "36"},
            "serverVersion": {"major": "1", "minor": "34"},
        }
    )

    result = run_validate(output, env=env)

    assert result.returncode != 0
    assert "outside the supported +/-1 minor skew" in combined_output(result)


def test_live_validation_fails_closed_on_malformed_kubectl_version_json(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin)
    env["FAKE_KUBECTL_VERSION_JSON"] = json.dumps({"clientVersion": {}, "serverVersion": {}})

    result = run_validate(output, env=env)

    assert result.returncode != 0
    assert "kubectl major version is not Kubernetes 1.x" in combined_output(result)


def test_live_validation_uses_helm3_helm4_status_flags_without_all(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    command_log = tmp_path / "commands.log"
    env = live_validation_env(fake_bin)
    env["FAKE_COMMAND_LOG"] = str(command_log)

    result = run_validate(output, env=env)

    assert result.returncode == 0, combined_output(result)
    helm_list = next(
        line for line in command_log.read_text(encoding="utf-8").splitlines() if " list " in line
    )
    for flag in (
        "--deployed",
        "--failed",
        "--pending",
        "--uninstalling",
        "--superseded",
        "--uninstalled",
    ):
        assert flag in helm_list
    assert " --all " not in helm_list


def test_live_helm_status_is_fresh_and_does_not_echo_private_notes(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    base_env = os.environ.copy()
    base_env.update(live_validation_env(fake_bin))
    private_marker = "HELM_NOTES_CUSTOMER_DATA_MUST_NOT_APPEAR"

    for fresh_status, should_pass in (("deployed", True), ("failed", False)):
        env = base_env | {
            "FAKE_HELM_METADATA_JSON": json.dumps(
                {"status": fresh_status, "notes": private_marker}
            )
        }
        result = subprocess.run(
            [
                "bash",
                str(VALIDATE),
                "--output-dir",
                str(output),
                "--live",
                "--kube-context",
                "unit-test",
            ],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert (result.returncode == 0) is should_pass, result.stdout
        assert private_marker not in result.stdout
        if should_pass:
            assert "current Helm status deployed" in result.stdout
        else:
            assert "did not confirm a current deployed release" in result.stdout
            assert "command output suppressed" in result.stdout


def test_live_helm_metadata_is_authoritative_over_stale_list_status(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin)
    releases = json.loads(env["FAKE_HELM_RELEASES_JSON"])
    for release in releases:
        release["status"] = "failed"
    env["FAKE_HELM_RELEASES_JSON"] = json.dumps(releases)

    result = run_validate(output, env=env)

    assert result.returncode == 0, combined_output(result)
    assert "current Helm status deployed" in combined_output(result)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("name", "wrong-release"),
        ("namespace", "wrong-namespace"),
        ("chart", "wrong-chart"),
        ("version", "0.0.0"),
    ),
)
def test_live_helm_metadata_rejects_current_identity_drift(
    tmp_path: Path, field: str, value: str
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin)
    env["FAKE_HELM_METADATA_JSON"] = json.dumps({field: value})

    result = run_validate(output, env=env)

    assert result.returncode != 0
    assert "did not confirm a current deployed release" in combined_output(result)


def test_enterprise_helm_dry_run_hides_license_or_fails_before_render(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", edition="enterprise")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    helm = fake_bin / "helm"
    helm.write_text(
        """#!/usr/bin/env python3
import os
import pathlib
import sys

args = sys.argv[1:]
with open(os.environ["HELM_COMMAND_LOG"], "a", encoding="utf-8") as stream:
    stream.write(" ".join(args) + "\\n")
if args[:2] == ["upgrade", "--help"]:
    if os.environ.get("SUPPORT_HIDE_SECRET") == "true":
        print("      --hide-secret   hide Kubernetes Secrets during dry-run")
    raise SystemExit(0)
if args[:2] in (["repo", "add"], ["repo", "update"]):
    raise SystemExit(0)
if args[:2] == ["show", "chart"]:
    print("name: cilium-enterprise")
    raise SystemExit(0)
if args[:2] == ["show", "values"]:
    print("enterprise:\\n  license: {}")
    raise SystemExit(0)
if args and args[0] == "upgrade":
    if "--hide-secret" not in args and "--set-file" in args:
        assignment = args[args.index("--set-file") + 1]
        path = pathlib.Path(assignment.split("=", 1)[1])
        sys.stdout.write(path.read_text(encoding="utf-8"))
    print("dry-run complete")
    raise SystemExit(0)
print("unexpected fake Helm command", file=sys.stderr)
raise SystemExit(2)
""",
        encoding="utf-8",
    )
    helm.chmod(0o755)
    command_log = tmp_path / "helm-commands.log"
    license_path = tmp_path / "enterprise-license"
    license_marker = "unit-test-license-material-must-not-appear"
    license_path.write_text(license_marker, encoding="utf-8")
    license_path.chmod(0o600)
    base_env = os.environ.copy()
    base_env.update(
        {
            "PATH": f"{fake_bin}:{base_env['PATH']}",
            "K8S_APPLY_DRY_RUN": "true",
            "ISOVALENT_LICENSE_FILE": str(license_path),
            "HELM_COMMAND_LOG": str(command_log),
        }
    )
    install = output / "scripts/install-cilium.sh"

    supported = subprocess.run(
        ["bash", str(install)],
        cwd=REPO_ROOT,
        env=base_env | {"SUPPORT_HIDE_SECRET": "true"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert supported.returncode == 0, supported.stdout
    assert license_marker not in supported.stdout
    assert "--dry-run --hide-secret" in command_log.read_text(encoding="utf-8")

    command_log.unlink()
    unsupported = subprocess.run(
        ["bash", str(install)],
        cwd=REPO_ROOT,
        env=base_env | {"SUPPORT_HIDE_SECRET": "false"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert unsupported.returncode != 0
    assert "requires upgrade --hide-secret support" in unsupported.stdout
    assert license_marker not in unsupported.stdout
    assert "upgrade --install" not in command_log.read_text(encoding="utf-8")


def test_live_validation_accepts_large_openmetrics_response_without_pipefail_false_failure(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin)
    env["FAKE_LARGE_METRICS_RESPONSE"] = "true"

    result = run_validate(output, env=env)

    assert result.returncode == 0, combined_output(result)
    assert "returned no Prometheus/OpenMetrics samples" not in combined_output(result)


def test_live_validation_accepts_prometheus_openmetrics_numeric_forms(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin)
    env["FAKE_METRICS_TEXT"] = "\n".join(
        (
            "metric_zero 0",
            "metric_negative -1",
            "metric_fraction .5",
            "metric_positive_inf +Inf",
            "metric_negative_inf -Inf",
            "metric_nan NaN",
            'metric_scientific{escaped="value\\\"x"} 1.2e-3 123 # {trace_id="abc"} 1.0',
        )
    )

    result = run_validate(output, env=env)

    assert result.returncode == 0, combined_output(result)
    assert "samples=7" in combined_output(result)


@pytest.mark.parametrize(
    "metric_path",
    (
        "/services/cilium-agent:9962/proxy/metrics",
        "/services/hubble-metrics:9965/proxy/metrics",
        "/services/cilium-envoy:9964/proxy/metrics",
        "/services/cilium-operator:9963/proxy/metrics",
    ),
)
def test_live_validation_rejects_positive_degraded_or_failed_hive_status_without_echoing_labels(
    tmp_path: Path,
    metric_path: str,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin)
    marker = "SYNTHETIC_LABEL_MUST_NOT_APPEAR"
    env["FAKE_HIVE_HEALTH_PATH"] = metric_path
    env["FAKE_HIVE_METRICS_TEXT"] = "\n".join(
        (
            f'cilium_hive_status{{status="degraded",cell="{marker}"}} 1',
            'cilium_hive_status{status="failed"} 2.0e+00',
            'cilium_hive_status{status="ok"} 124',
            'cilium_hive_status{status="stopped"} 15',
        )
    )

    result = run_validate(output, env=env)

    assert result.returncode != 0
    output_text = combined_output(result)
    assert "cilium_hive_status rule=degraded-or-failed-positive count=3" in output_text
    assert marker not in output_text
    assert 'status="degraded"' not in output_text


def test_live_validation_allows_zero_degraded_and_positive_stopped_hive_status(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin)
    env["FAKE_HIVE_HEALTH_PATH"] = "/services/cilium-operator:9963/proxy/metrics"
    env["FAKE_HIVE_METRICS_TEXT"] = "\n".join(
        (
            'cilium_hive_status{status="degraded"} 0',
            'cilium_hive_status{status="failed"} 0',
            'cilium_hive_status{status="ok"} 10',
            'cilium_hive_status{status="stopped"} 2',
        )
    )

    result = run_validate(output, env=env)

    assert result.returncode == 0, combined_output(result)


def test_live_validation_rejects_duplicate_release_names_across_namespaces(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin)
    releases = json.loads(env["FAKE_HELM_RELEASES_JSON"])
    releases.append(
        {
            "name": "cilium",
            "namespace": "shadow-system",
            "status": "deployed",
            "chart": "cilium-1.18.10",
        }
    )
    env["FAKE_HELM_RELEASES_JSON"] = json.dumps(releases)

    result = run_validate(output, env=env)

    assert result.returncode != 0
    output_text = combined_output(result)
    assert "duplicate Helm releases named cilium found across namespaces" in output_text
    assert "kube-system/cilium-1.18.10" in output_text
    assert "shadow-system/cilium-1.18.10" in output_text


def test_live_validation_rejects_wrong_chart_hidden_behind_core_release_name(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin)
    releases = json.loads(env["FAKE_HELM_RELEASES_JSON"])
    next(item for item in releases if item["name"] == "cilium")["chart"] = "nginx-18.0.0"
    env["FAKE_HELM_RELEASES_JSON"] = json.dumps(releases)

    result = run_validate(output, env=env)

    assert result.returncode != 0
    assert "did not confirm a current deployed release for cilium in kube-system" in combined_output(result)


def test_live_validation_rejects_wrong_chart_hidden_behind_addon_release_name(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", edition="enterprise")
    rendered = run_setup(
        "--render",
        "--enable-dnsproxy",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin, edition="enterprise")
    releases = json.loads(env["FAKE_HELM_RELEASES_JSON"])
    releases.append(
        {
            "name": "cilium-dnsproxy",
            "namespace": "kube-system",
            "status": "deployed",
            "chart": "nginx-18.0.0",
        }
    )
    env["FAKE_HELM_RELEASES_JSON"] = json.dumps(releases)
    env["FAKE_DNSPROXY_PRESENT"] = "true"

    result = run_validate(output, env=env)

    assert result.returncode != 0
    assert "did not confirm a current deployed release for cilium-dnsproxy in kube-system" in combined_output(result)


def test_live_validation_rejects_enabled_addon_in_unexpected_namespace(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", edition="enterprise")
    rendered = run_setup(
        "--render",
        "--enable-dnsproxy",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin, edition="enterprise")
    releases = json.loads(env["FAKE_HELM_RELEASES_JSON"])
    releases.append(
        {
            "name": "cilium-dnsproxy",
            "namespace": "shadow-system",
            "status": "deployed",
            "chart": "cilium-dnsproxy-1.18.8",
        }
    )
    env["FAKE_HELM_RELEASES_JSON"] = json.dumps(releases)
    env["FAKE_DNSPROXY_PRESENT"] = "true"

    result = run_validate(output, env=env)

    assert result.returncode != 0
    assert "did not confirm a current deployed release for cilium-dnsproxy in kube-system" in combined_output(result)


def enabled_enterprise_addon_releases(env: dict[str, str]) -> None:
    releases = json.loads(env["FAKE_HELM_RELEASES_JSON"])
    releases.extend(
        (
            {
                "name": "hubble-enterprise",
                "namespace": "kube-system",
                "status": "deployed",
                "chart": "hubble-enterprise-1.18.8",
            },
            {
                "name": "cilium-dnsproxy",
                "namespace": "kube-system",
                "status": "deployed",
                "chart": "cilium-dnsproxy-1.18.8",
            },
        )
    )
    env["FAKE_HELM_RELEASES_JSON"] = json.dumps(releases)
    env["FAKE_DNSPROXY_PRESENT"] = "true"


def test_live_validation_accepts_ready_enabled_enterprise_addons(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", edition="enterprise")
    rendered = run_setup(
        "--render",
        "--enable-hubble-enterprise",
        "--enable-dnsproxy",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin, edition="enterprise")
    enabled_enterprise_addon_releases(env)

    result = run_validate(output, env=env)

    assert result.returncode == 0, combined_output(result)
    assert "Hubble Enterprise: 1/1 ready" in combined_output(result)
    assert "Cilium DNSProxy: 1/1 ready" in combined_output(result)


def test_live_validation_uses_each_rendered_addon_namespace(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        edition="enterprise",
        namespaces={
            "cilium": "kube-system",
            "tetragon": "tetragon",
            "hubble_enterprise": "hubble-system",
            "cilium_dnsproxy": "dns-system",
            "hubble_timescape": "timescape-system",
        },
    )
    rendered = run_setup(
        "--render",
        "--enable-hubble-enterprise",
        "--enable-dnsproxy",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    command_log = tmp_path / "commands.log"
    env = live_validation_env(fake_bin, edition="enterprise")
    enabled_enterprise_addon_releases(env)
    releases = json.loads(env["FAKE_HELM_RELEASES_JSON"])
    next(item for item in releases if item["name"] == "hubble-enterprise")["namespace"] = "hubble-system"
    next(item for item in releases if item["name"] == "cilium-dnsproxy")["namespace"] = "dns-system"
    env["FAKE_HELM_RELEASES_JSON"] = json.dumps(releases)
    env["FAKE_COMMAND_LOG"] = str(command_log)

    result = run_validate(output, env=env)

    assert result.returncode == 0, combined_output(result)
    commands = command_log.read_text(encoding="utf-8")
    assert "-n hubble-system get pods -l app.kubernetes.io/instance=hubble-enterprise" in commands
    assert "-n dns-system get pods -l k8s-app=cilium-dnsproxy" in commands
    assert "app.kubernetes.io/instance=cilium-dnsproxy" not in commands
    assert "/namespaces/dns-system/services/cilium-dnsproxy:9967/" in commands


def test_live_validation_rejects_dnsproxy_degraded_hive_status_with_safe_summary(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", edition="enterprise")
    rendered = run_setup(
        "--render",
        "--enable-dnsproxy",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin, edition="enterprise")
    releases = json.loads(env["FAKE_HELM_RELEASES_JSON"])
    releases.append(
        {
            "name": "cilium-dnsproxy",
            "namespace": "kube-system",
            "status": "deployed",
            "chart": "cilium-dnsproxy-1.18.8",
        }
    )
    env["FAKE_HELM_RELEASES_JSON"] = json.dumps(releases)
    env["FAKE_DNSPROXY_PRESENT"] = "true"
    marker = "DNSPROXY_LABEL_MUST_NOT_APPEAR"
    env["FAKE_DNSPROXY_METRICS_TEXT"] = "\n".join(
        (
            f'cilium_hive_status{{status="degraded",cell="{marker}"}} 1',
            'cilium_hive_status{status="ok"} 7',
        )
    )

    result = run_validate(output, env=env)

    assert result.returncode != 0
    output_text = combined_output(result)
    assert "cilium-dnsproxy:9967: cilium_hive_status rule=degraded-or-failed-positive count=1" in output_text
    assert marker not in output_text


@pytest.mark.parametrize(
    ("env_key", "expected_error"),
    (
        ("FAKE_HUBBLE_ENTERPRISE_PODS_JSON", "no Hubble Enterprise pods matched"),
        ("FAKE_DNSPROXY_PODS_JSON", "unready Cilium DNSProxy pods"),
    ),
)
def test_live_validation_rejects_missing_or_unready_enabled_addon_pods(
    tmp_path: Path,
    env_key: str,
    expected_error: str,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", edition="enterprise")
    rendered = run_setup(
        "--render",
        "--enable-hubble-enterprise",
        "--enable-dnsproxy",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin, edition="enterprise")
    enabled_enterprise_addon_releases(env)
    if env_key == "FAKE_HUBBLE_ENTERPRISE_PODS_JSON":
        env[env_key] = json.dumps({"items": []})
    else:
        payload = json.loads(env[env_key])
        payload["items"][0]["status"]["containerStatuses"][0]["ready"] = False
        env[env_key] = json.dumps(payload)

    result = run_validate(output, env=env)

    assert result.returncode != 0
    assert expected_error in combined_output(result)


def test_live_validation_fails_when_required_metrics_endpoint_is_missing(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin)
    env["FAKE_MISSING_METRIC_PATH"] = "/services/tetragon:2112/proxy/metrics"

    result = run_validate(output, env=env)

    assert result.returncode != 0
    assert "tetragon:2112 metrics not reachable" in combined_output(result)


def test_live_validation_accepts_cilium_bundled_timescape_without_standalone_release(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", edition="enterprise")
    rendered = run_setup(
        "--render",
        "--enable-timescape",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin, edition="enterprise")
    env["FAKE_STATEFULSETS_JSON"] = timescape_statefulset_inventory("cilium")

    result = run_validate(output, env=env)

    assert result.returncode == 0, combined_output(result)
    assert "bundled with cilium release" in combined_output(result)
    assert "hubble-timescape: optional release not installed" not in combined_output(result)
    assert "Live validation passed all required checks" in combined_output(result)


@pytest.mark.parametrize(
    ("owner", "namespace", "expected_error"),
    [
        (
            "unrelated-release",
            "kube-system",
            "has Helm owner unrelated-release, expected cilium",
        ),
        (
            "cilium",
            "shadow-system",
            "is outside expected namespace kube-system",
        ),
    ],
)
def test_live_validation_rejects_uncorrelated_bundled_timescape_workload(
    tmp_path: Path,
    owner: str,
    namespace: str,
    expected_error: str,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", edition="enterprise")
    rendered = run_setup(
        "--render",
        "--enable-timescape",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin, edition="enterprise")
    env["FAKE_STATEFULSETS_JSON"] = timescape_statefulset_inventory(
        owner,
        namespace=namespace,
    )

    result = run_validate(output, env=env)

    assert result.returncode != 0
    assert expected_error in combined_output(result)


def test_live_validation_rejects_stale_in_progress_timescape_rollout(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", edition="enterprise")
    rendered = run_setup(
        "--render",
        "--enable-timescape",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin, edition="enterprise")
    env["FAKE_STATEFULSETS_JSON"] = timescape_statefulset_inventory(
        "cilium",
        status_overrides={
            "observedGeneration": 2,
            "updatedReplicas": 1,
            "updateRevision": "timescape-rev-b",
        },
    )

    result = run_validate(output, env=env)

    assert result.returncode != 0
    output_text = combined_output(result)
    assert "rollout is incomplete" in output_text
    assert "observed-generation-stale" in output_text
    assert "updated-replicas-mismatch" in output_text
    assert "revision-mismatch" in output_text


def test_live_validation_retains_standalone_timescape_release_support(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", edition="enterprise")
    rendered = run_setup(
        "--render",
        "--enable-timescape",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin, edition="enterprise")
    releases = json.loads(env["FAKE_HELM_RELEASES_JSON"])
    releases.append(
        {
            "name": "hubble-timescape",
            "namespace": "hubble-timescape",
            "status": "deployed",
            "chart": "hubble-timescape-1.18.8",
        }
    )
    env["FAKE_HELM_RELEASES_JSON"] = json.dumps(releases)
    env["FAKE_STATEFULSETS_JSON"] = timescape_statefulset_inventory(
        "hubble-timescape", namespace="hubble-timescape"
    )

    result = run_validate(output, env=env)

    assert result.returncode == 0, combined_output(result)
    assert "hubble-timescape (hubble-timescape): chart hubble-timescape-1.18.8" in combined_output(result)
    assert "Helm owner hubble-timescape" in combined_output(result)


def test_live_validation_allows_disabled_enterprise_addons_to_be_absent(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)

    result = run_validate(output, env=live_validation_env(fake_bin))

    assert result.returncode == 0, combined_output(result)
    output_text = combined_output(result)
    assert "cilium-dnsproxy: optional release not installed" in output_text
    assert "hubble-enterprise: optional release not installed" in output_text
    assert "hubble-timescape: optional add-on not installed" in output_text


@pytest.mark.parametrize("distribution", ["aks-managed-cilium", "gke-dataplane-v2"])
def test_live_validation_explicitly_gates_provider_managed_cilium_without_helm_probes(
    tmp_path: Path,
    distribution: str,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", distribution=distribution)
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    command_log = tmp_path / "commands.log"
    env = live_validation_env(fake_bin)
    env["FAKE_COMMAND_LOG"] = str(command_log)
    releases = json.loads(env["FAKE_HELM_RELEASES_JSON"])
    env["FAKE_HELM_RELEASES_JSON"] = json.dumps(
        [item for item in releases if item["name"] != "cilium"]
    )

    result = run_validate(output, env=env)

    assert result.returncode != 0
    output_text = combined_output(result)
    assert f"provider-managed Cilium live evidence is unsupported for {distribution}" in output_text
    assert "required Helm release cilium" not in output_text
    assert "Tetragon agent: 1/1 ready" in output_text
    commands = command_log.read_text(encoding="utf-8")
    for forbidden in (
        "status cilium ",
        "k8s-app=cilium",
        "/services/cilium-agent:9962/",
        "/services/hubble-metrics:9965/",
        "/services/cilium-envoy:9964/",
        "/services/cilium-operator:9963/",
        "/services/cilium-dnsproxy:9967/",
    ):
        assert forbidden not in commands


def test_live_validation_fails_closed_when_tetragon_pod_logs_are_unreadable(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin)
    env["FAKE_LOG_FAILURE"] = "true"

    result = run_validate(output, env=env)

    assert result.returncode != 0
    assert "Tetragon pod log API failed" in combined_output(result)


def test_live_validation_rejects_fatal_tetragon_log_rules_without_echoing_log_content(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    fake_bin = tmp_path / "bin"
    write_fake_live_validation_tools(fake_bin)
    env = live_validation_env(fake_bin)
    env["FAKE_TETRAGON_LOG_TEXT"] = "\n".join(
        (
            "panic: workload-payload-marker-one",
            "level=fatal msg=workload-payload-marker-two",
            "runtime error workload-payload-marker-three",
            "exporter failed workload-payload-marker-four",
        )
    )

    result = run_validate(output, env=env)

    assert result.returncode != 0
    output_text = combined_output(result)
    assert "matched recent fatal log rule(s): panic,fatal,runtime-error,export-error" in output_text
    assert "workload-payload-marker" not in output_text


def test_live_validator_does_not_execute_in_pods_or_read_helm_values() -> None:
    validator = VALIDATE.read_text(encoding="utf-8")
    assert "kubectl exec" not in validator
    assert "helm get values" not in validator
    assert "get secrets" not in validator


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
