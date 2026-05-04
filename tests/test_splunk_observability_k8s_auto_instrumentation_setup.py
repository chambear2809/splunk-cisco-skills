"""Regressions for splunk-observability-k8s-auto-instrumentation-setup rendering.

These tests invoke scripts/setup.sh as a subprocess (the same path an operator
or the MCP wrapper would take) and assert on the rendered output tree.

Every cluster-mutating path is gated; these tests only exercise the render,
dry-run, and static validation paths. No kubectl / helm calls happen.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/setup.sh"
VALIDATE = REPO_ROOT / "skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/validate.sh"
RENDER = REPO_ROOT / "skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/render_assets.py"
TEMPLATE = REPO_ROOT / "skills/splunk-observability-k8s-auto-instrumentation-setup/template.example"


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
    python = REPO_ROOT / ".venv/bin/python3"
    if not python.exists():
        python = Path("python3")
    return subprocess.run(
        [str(python), str(RENDER), *args],
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
        "api_version": "splunk-observability-k8s-auto-instrumentation-setup/v1",
        "realm": "us0",
        "cluster_name": "demo",
        "deployment_environment": "dev",
        "distribution": "generic",
        "instrumentation_crs": [
            {
                "name": "splunk-otel-auto-instrumentation",
                "namespace": "splunk-otel",
                "languages": ["java"],
            }
        ],
        "workload_annotations": [],
    }
    base.update(overrides)
    path.write_text(yaml.safe_dump(base, sort_keys=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Render happy path
# ---------------------------------------------------------------------------


def test_render_happy_path_produces_expected_files(tmp_path: Path) -> None:
    out = tmp_path / "rendered"
    result = run_render(
        "--spec",
        str(TEMPLATE),
        "--output-dir",
        str(out),
        "--realm",
        "us0",
        "--cluster-name",
        "demo",
    )
    assert result.returncode == 0, combined(result)
    expected = {
        "k8s-instrumentation/instrumentation-cr.yaml",
        "k8s-instrumentation/workload-annotations.yaml",
        "k8s-instrumentation/namespace-annotations.yaml",
        "k8s-instrumentation/annotation-backup-configmap.yaml",
        "k8s-instrumentation/preflight-report.md",
        "k8s-instrumentation/apply-instrumentation.sh",
        "k8s-instrumentation/apply-annotations.sh",
        "k8s-instrumentation/uninstall.sh",
        "k8s-instrumentation/verify-injection.sh",
        "k8s-instrumentation/status.sh",
        "k8s-instrumentation/list-instrumented.sh",
        "runbook.md",
        "handoff-collector.sh",
        "metadata.json",
    }
    rendered = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    missing = expected - rendered
    assert not missing, f"missing files: {missing}; got: {rendered}"


def test_render_metadata_has_target_list(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        workload_annotations=[
            {"kind": "Deployment", "namespace": "prod", "name": "a", "language": "java"},
            {"kind": "StatefulSet", "namespace": "prod", "name": "b", "language": "nodejs"},
        ],
    )
    out = tmp_path / "r"
    result = run_render("--spec", str(spec), "--output-dir", str(out))
    assert result.returncode == 0, combined(result)
    meta = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    targets = meta.get("targets") or []
    assert any(t["name"] == "a" for t in targets)
    assert any(t["name"] == "b" for t in targets)


# ---------------------------------------------------------------------------
# Strategic-merge-patch target invariant
# ---------------------------------------------------------------------------


def test_workload_annotations_target_pod_template(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        workload_annotations=[
            {"kind": "Deployment", "namespace": "prod", "name": "web", "language": "java"}
        ],
    )
    out = tmp_path / "r"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    docs = list(
        yaml.safe_load_all((out / "k8s-instrumentation/workload-annotations.yaml").read_text(encoding="utf-8"))
    )
    docs = [d for d in docs if d]
    for doc in docs:
        assert doc["kind"] in {"Deployment", "StatefulSet", "DaemonSet"}, doc
        assert (
            "annotations" in doc["spec"]["template"]["metadata"]
        ), "inject-* must target spec.template.metadata.annotations, never top-level metadata.annotations"
        assert doc.get("metadata", {}).get("annotations") is None or all(
            not k.startswith("instrumentation.opentelemetry.io/")
            for k in (doc["metadata"].get("annotations") or {})
        ), "top-level metadata.annotations must not carry inject-* keys"


# ---------------------------------------------------------------------------
# Preflight fail-render cases
# ---------------------------------------------------------------------------


def test_fargate_without_gateway_fails(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.yaml", distribution="eks/fargate")
    out = tmp_path / "r"
    result = run_render("--spec", str(spec), "--output-dir", str(out), "--dry-run")
    assert result.returncode == 2
    assert "EKS Fargate requires --gateway-endpoint" in combined(result)


def test_go_without_target_exe_fails(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        instrumentation_crs=[{"name": "c", "namespace": "splunk-otel", "languages": ["go"]}],
        workload_annotations=[
            {"kind": "Deployment", "namespace": "prod", "name": "svc", "language": "go"}
        ],
    )
    out = tmp_path / "r"
    result = run_render("--spec", str(spec), "--output-dir", str(out), "--dry-run")
    assert result.returncode == 2
    assert "missing go-target-exe" in combined(result)


def test_dotnet_framework_fails(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        instrumentation_crs=[{"name": "c", "namespace": "splunk-otel", "languages": ["dotnet"]}],
        workload_annotations=[
            {
                "kind": "Deployment",
                "namespace": "prod",
                "name": "legacy",
                "language": "dotnet",
                "dotnet_runtime": "windows-x64",
            }
        ],
    )
    out = tmp_path / "r"
    result = run_render("--spec", str(spec), "--output-dir", str(out), "--dry-run")
    assert result.returncode == 2
    assert "targets .NET Framework or Windows" in combined(result)


def test_multi_cr_without_gate_fails(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        instrumentation_crs=[
            {"name": "dev", "namespace": "splunk-otel", "languages": ["java"]},
            {"name": "prod", "namespace": "splunk-otel", "languages": ["java"]},
        ],
    )
    out = tmp_path / "r"
    result = run_render("--spec", str(spec), "--output-dir", str(out), "--dry-run")
    assert result.returncode == 2
    assert "Multiple Instrumentation CRs require --multi-instrumentation" in combined(result)


def test_multi_cr_with_gate_succeeds(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        operator={
            "multi_instrumentation": True,
            "watch_namespaces": [],
            "webhook_cert_mode": "auto",
            "installation_job_enabled": True,
        },
        instrumentation_crs=[
            {"name": "dev", "namespace": "splunk-otel", "languages": ["java"]},
            {"name": "prod", "namespace": "splunk-otel", "languages": ["java"]},
        ],
    )
    out = tmp_path / "r"
    result = run_render("--spec", str(spec), "--output-dir", str(out))
    assert result.returncode == 0, combined(result)
    # CR yaml contains both documents
    docs = [
        d for d in yaml.safe_load_all((out / "k8s-instrumentation/instrumentation-cr.yaml").read_text())
        if d
    ]
    names = {doc["metadata"]["name"] for doc in docs}
    assert names == {"dev", "prod"}


def test_apply_annotations_requires_accept(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.yaml")
    out = tmp_path / "r"
    result = run_render(
        "--spec", str(spec), "--output-dir", str(out), "--mode", "apply-annotations", "--dry-run"
    )
    assert result.returncode == 2
    assert "--apply-annotations requires --accept-auto-instrumentation" in combined(result)


def test_obi_requires_accept_obi_privileged(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        obi={"enabled": True, "namespaces": [], "exclude_namespaces": [], "version": "", "render_openshift_scc": True},
    )
    out = tmp_path / "r"
    result = run_render(
        "--spec", str(spec), "--output-dir", str(out), "--mode", "apply-instrumentation", "--dry-run"
    )
    assert result.returncode == 2
    assert "OBI requires --accept-obi-privileged" in combined(result)


# ---------------------------------------------------------------------------
# OpenShift SCC and OBI
# ---------------------------------------------------------------------------


def test_openshift_obi_renders_scc(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        distribution="openshift",
        obi={"enabled": True, "namespaces": [], "exclude_namespaces": [], "version": "", "render_openshift_scc": True},
    )
    out = tmp_path / "r"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    scc = out / "k8s-instrumentation/openshift-scc-obi.yaml"
    assert scc.exists()
    body = scc.read_text(encoding="utf-8")
    assert "SecurityContextConstraints" in body
    assert "allowPrivilegedContainer: true" in body


# ---------------------------------------------------------------------------
# GitOps mode
# ---------------------------------------------------------------------------


def test_gitops_mode_skips_apply_scripts(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.yaml")
    out = tmp_path / "r"
    assert run_render("--spec", str(spec), "--output-dir", str(out), "--gitops-mode").returncode == 0
    rendered = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    for forbidden in (
        "k8s-instrumentation/apply-instrumentation.sh",
        "k8s-instrumentation/apply-annotations.sh",
        "k8s-instrumentation/uninstall.sh",
    ):
        assert forbidden not in rendered, f"gitops-mode must omit {forbidden}"
    for required in (
        "k8s-instrumentation/instrumentation-cr.yaml",
        "k8s-instrumentation/workload-annotations.yaml",
        "k8s-instrumentation/annotation-backup-configmap.yaml",
        "k8s-instrumentation/status.sh",
    ):
        assert required in rendered


# ---------------------------------------------------------------------------
# Uninstall script invariants
# ---------------------------------------------------------------------------


def test_uninstall_script_deletes_cr_before_any_helm_uninstall(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.yaml")
    out = tmp_path / "r"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    body = (out / "k8s-instrumentation/uninstall.sh").read_text(encoding="utf-8")
    # Ordered contract: no helm uninstall reference earlier than the otelinst delete.
    lower = body.lower()
    otelinst_idx = lower.find("delete otelinst")
    helm_idx = lower.find("helm uninstall")
    assert otelinst_idx != -1, "uninstall.sh must delete the Instrumentation CR"
    if helm_idx != -1:
        assert otelinst_idx < helm_idx, (
            "delete otelinst must appear before any helm uninstall reference"
        )


# ---------------------------------------------------------------------------
# --discover-workloads shape
# ---------------------------------------------------------------------------


def test_discover_workloads_json_shape(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.yaml")
    out = tmp_path / "r"
    result = run_render(
        "--spec", str(spec), "--output-dir", str(out), "--discover-workloads", "--dry-run", "--json"
    )
    # kubectl/helm may not be installed on the test host -- discovery writes a
    # skeleton payload with empty workloads[] either way. The payload must still
    # be valid JSON with the expected top-level keys.
    assert result.returncode in (0, 2)
    payload = json.loads(result.stdout)
    assert "base_collector_probe" in payload
    assert "discovery" in payload
    assert payload["discovery"].get("api_version") == "splunk-observability-k8s-auto-instrumentation-setup/v1"
    assert "workloads" in payload["discovery"]


# ---------------------------------------------------------------------------
# No-secret scrub
# ---------------------------------------------------------------------------


def test_rendered_scripts_have_no_tokens(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.yaml")
    out = tmp_path / "r"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    import re
    token_re = re.compile(
        r"(?i)(access[_-]?token|api[_-]?token|bearer[_-]?token|hec[_-]?token|sf[_-]?token)"
        r"\s*[:=]\s*[A-Za-z0-9._-]{20,}"
    )
    for sh in out.rglob("*.sh"):
        body = sh.read_text(encoding="utf-8")
        assert not token_re.search(body), f"{sh} contains token-shaped value"


# ---------------------------------------------------------------------------
# Static validate.sh over a fresh render
# ---------------------------------------------------------------------------


def test_static_validate_passes_on_default_render(tmp_path: Path) -> None:
    out = tmp_path / "r"
    render = run_render(
        "--spec",
        str(TEMPLATE),
        "--output-dir",
        str(out),
        "--realm",
        "us0",
        "--cluster-name",
        "demo",
    )
    assert render.returncode == 0, combined(render)
    validate = subprocess.run(
        ["bash", str(VALIDATE), "--output-dir", str(out)],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert validate.returncode == 0, combined(validate)
    assert "Static validation: OK" in combined(validate)


# ---------------------------------------------------------------------------
# setup.sh help + token-flag rejection
# ---------------------------------------------------------------------------


def test_setup_help() -> None:
    result = run_setup("--help")
    assert result.returncode == 0
    assert "Zero-code" not in result.stdout  # not in help title
    assert "Splunk Observability Kubernetes auto-instrumentation setup" in result.stdout


@pytest.mark.parametrize(
    "flag",
    ["--access-token", "--token", "--api-token", "--o11y-token", "--hec-token"],
)
def test_setup_rejects_direct_token_flags(flag: str) -> None:
    result = run_setup("--render", flag, "deadbeef")
    assert result.returncode != 0
    assert flag in combined(result)


# ---------------------------------------------------------------------------
# Multi-language happy path: render + static validate a fully loaded spec
# ---------------------------------------------------------------------------


def test_multi_language_render(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        instrumentation_crs=[
            {
                "name": "multi",
                "namespace": "splunk-otel",
                "languages": ["java", "nodejs", "python", "dotnet", "apache-httpd", "nginx"],
                "profiling_enabled": True,
                "runtime_metrics_enabled": True,
            }
        ],
        workload_annotations=[
            {"kind": "Deployment", "namespace": "p", "name": "j", "language": "java"},
            {"kind": "Deployment", "namespace": "p", "name": "n", "language": "nodejs"},
            {"kind": "Deployment", "namespace": "p", "name": "py", "language": "python"},
            {"kind": "Deployment", "namespace": "p", "name": "d", "language": "dotnet"},
            {"kind": "Deployment", "namespace": "p", "name": "a", "language": "apache-httpd"},
            {"kind": "Deployment", "namespace": "p", "name": "ng", "language": "nginx"},
        ],
    )
    out = tmp_path / "r"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    cr_body = (out / "k8s-instrumentation/instrumentation-cr.yaml").read_text(encoding="utf-8")
    for key in ("java:", "nodejs:", "python:", "dotnet:", "apacheHttpd:", "nginx:"):
        assert key in cr_body, f"CR must include {key} block"
    assert "SPLUNK_PROFILER_ENABLED" in cr_body
    assert "SPLUNK_METRICS_ENABLED" in cr_body


# ---------------------------------------------------------------------------
# Rendered apply-annotations.sh / uninstall.sh: target gating + bash sanity
# (regression coverage for the C2 / H1 bug class -- empty TARGETS produced a
# silent no-op via "${TARGETS[@]:-}" and setup.sh dropped --target X.)
# ---------------------------------------------------------------------------


def render_default(tmp_path: Path) -> Path:
    out = tmp_path / "r"
    spec = write_spec(
        tmp_path / "spec.yaml",
        workload_annotations=[
            {"kind": "Deployment", "namespace": "prod", "name": "payments-api", "language": "java"},
            {"kind": "Deployment", "namespace": "prod", "name": "checkout-web", "language": "nodejs"},
        ],
    )
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    return out


def run_rendered(out: Path, script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(out / "k8s-instrumentation" / script), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_rendered_apply_annotations_requires_target_selection(tmp_path: Path) -> None:
    out = render_default(tmp_path)
    # Without --target / --target-all the rendered script must refuse rather
    # than silently no-op (the bug: ${TARGETS[@]:-} sent [""] to Python).
    result = run_rendered(out, "apply-annotations.sh", "--accept-auto-instrumentation", "--dry-run")
    assert result.returncode != 0
    assert "pass --target" in combined(result)


def test_rendered_uninstall_requires_target_selection(tmp_path: Path) -> None:
    out = render_default(tmp_path)
    result = run_rendered(out, "uninstall.sh", "--accept-auto-instrumentation", "--dry-run")
    assert result.returncode != 0
    assert "pass --target" in combined(result)


def test_rendered_apply_annotations_dry_run_target_all(tmp_path: Path) -> None:
    out = render_default(tmp_path)
    result = run_rendered(
        out,
        "apply-annotations.sh",
        "--accept-auto-instrumentation",
        "--target-all",
        "--dry-run",
    )
    assert result.returncode == 0, combined(result)
    body = combined(result)
    assert "patch Deployment payments-api" in body
    assert "patch Deployment checkout-web" in body


def test_rendered_apply_annotations_dry_run_specific_target(tmp_path: Path) -> None:
    out = render_default(tmp_path)
    result = run_rendered(
        out,
        "apply-annotations.sh",
        "--accept-auto-instrumentation",
        "--target",
        "Deployment/prod/payments-api",
        "--dry-run",
    )
    assert result.returncode == 0, combined(result)
    body = combined(result)
    assert "patch Deployment payments-api" in body
    assert "checkout-web" not in body


def test_rendered_uninstall_dry_run_specific_target(tmp_path: Path) -> None:
    out = render_default(tmp_path)
    result = run_rendered(
        out,
        "uninstall.sh",
        "--accept-auto-instrumentation",
        "--target",
        "Deployment/prod/payments-api",
        "--dry-run",
    )
    assert result.returncode == 0, combined(result)
    body = combined(result)
    assert "patch Deployment payments-api" in body
    assert "checkout-web" not in body


def test_rendered_uninstall_restores_from_backup(tmp_path: Path) -> None:
    """The uninstall script must read the backup ConfigMap and prefer prior values.

    We verify the JSON-decoding restore logic is present in the rendered text;
    the live restore behaviour requires a cluster but the static guarantees are:
    - the script consumes the backup ConfigMap data via kubectl jsonpath
    - the embedded Python parses the prior payload as JSON
    - it falls back to nulling only the managed annotation keys when the
      backup is missing or unparseable
    """
    out = render_default(tmp_path)
    body = (out / "k8s-instrumentation/uninstall.sh").read_text(encoding="utf-8")
    assert "get configmap" in body and "BACKUP_NAME" in body
    assert "jsonpath={.data." in body
    assert "managed_keys" in body
    assert "instrumentation.opentelemetry.io/inject-" in body
    assert "json.loads(prior_text)" in body


def test_rendered_apply_annotations_uses_o_json_for_backup(tmp_path: Path) -> None:
    """The backup ConfigMap must store proper JSON, not kubectl Go map syntax.

    Regression for the H3 ${current:-{}} brace bug and the H2 "backup is
    never restored" gap: apply-annotations.sh must pull annotations through
    `kubectl get -o json | python` so uninstall can parse the backup payload.
    """
    out = render_default(tmp_path)
    body = (out / "k8s-instrumentation/apply-annotations.sh").read_text(encoding="utf-8")
    # Reject the previous broken idiom outright.
    assert "${current:-{}}" not in body, "stale brace expansion still in script"
    # Verify proper JSON capture via -o json + python.
    assert "kubectl_get_pods_o_jsonpath" not in body  # sanity
    assert "get \"${kind}\" \"${name}\" -o json" in body
    assert "json.dumps(annotations)" in body


def test_rendered_status_is_python311_compatible(tmp_path: Path) -> None:
    """status.sh must avoid PEP 701 nested-quote f-strings (Python 3.12+).

    Splunk-shipped Python is commonly 3.9 or 3.13; the rendered status.sh
    must parse on every supported interpreter.
    """
    out = render_default(tmp_path)
    body = (out / "k8s-instrumentation/status.sh").read_text(encoding="utf-8")
    # The previous bug pattern: f"{p["metadata"]...}" requires PEP 701.
    assert 'f"{p["' not in body
    assert 'f"{p[\'' not in body


def test_setup_apply_annotations_forwards_target(tmp_path: Path) -> None:
    """setup.sh --apply-annotations --target X must reach the rendered script.

    Regression for H1: previously setup.sh hardcoded --target-all on the
    apply-annotations dispatch and silently dropped the operator's --target X.
    """
    out = tmp_path / "rendered"
    result = run_setup(
        "--apply-annotations",
        "--accept-auto-instrumentation",
        "--target",
        "Deployment/prod/payments-api",
        "--dry-run",
        "--output-dir",
        str(out),
        "--realm",
        "us0",
        "--cluster-name",
        "demo",
        "--annotate-workload",
        "Deployment/prod/payments-api=java",
        "--annotate-workload",
        "Deployment/prod/checkout-web=nodejs",
    )
    assert result.returncode == 0, combined(result)
    body = combined(result)
    # Only the requested workload should appear in the dry-run output.
    assert "patch Deployment payments-api" in body
    assert "checkout-web" not in body
