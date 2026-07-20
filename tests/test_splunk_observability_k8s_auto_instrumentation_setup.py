"""Regressions for splunk-observability-k8s-auto-instrumentation-setup rendering.

These tests invoke scripts/setup.sh as a subprocess (the same path an operator
or the MCP wrapper would take) and assert on the rendered output tree.

Every cluster-mutating path is gated; these tests only exercise the render,
dry-run, and static validation paths. No kubectl / helm calls happen.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/setup.sh"
VALIDATE = REPO_ROOT / "skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/validate.sh"
RENDER = REPO_ROOT / "skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/render_assets.py"
TEMPLATE = REPO_ROOT / "skills/splunk-observability-k8s-auto-instrumentation-setup/template.example"
TEST_OBI_IMAGE = f"registry.example.test/reviewed-obi@sha256:{'b' * 64}"


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
        [sys.executable, str(RENDER), *args],
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
                "languages": ["java", "nodejs"],
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
        "k8s-instrumentation/injection-audit.py",
        "k8s-instrumentation/managed-resource-lifecycle.py",
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


def test_cli_only_render_does_not_load_example_targets(tmp_path: Path) -> None:
    out = tmp_path / "rendered"
    result = run_setup(
        "--render",
        "--output-dir",
        str(out),
        "--realm",
        "us0",
        "--cluster-name",
        "demo",
        "--deployment-environment",
        "dev",
        "--languages",
        "java",
        "--annotate-workload",
        "Deployment/apps/real-api=java",
    )
    assert result.returncode == 0, combined(result)
    metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    assert [row["target"] for row in metadata["targets"]] == ["Deployment/apps/real-api"]
    assert metadata["instrumentation_crs"] == [
        {
            "endpoint": "http://$(SPLUNK_OTEL_AGENT):4317",
            "languages": ["java"],
            "name": "splunk-otel-auto-instrumentation",
            "namespace": "splunk-otel",
        }
    ]
    assert "payments-api" not in (out / "metadata.json").read_text(encoding="utf-8")


def test_shipped_template_is_target_free() -> None:
    template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    assert template["workload_annotations"] == []
    assert template["namespace_annotations"] == {}


def test_cli_namespace_and_single_cr_name_override_all_bindings(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        namespace_annotations={"apps": ["java"]},
        instrumentation_crs=[
            {"name": "old-name", "namespace": "old-namespace", "languages": ["java"]}
        ],
        workload_annotations=[
            {"kind": "Deployment", "namespace": "apps", "name": "api", "language": "java"}
        ],
    )
    out = tmp_path / "rendered"
    result = run_render(
        "--spec",
        str(spec),
        "--output-dir",
        str(out),
        "--namespace",
        "observability",
        "--instrumentation-cr-name",
        "production-auto",
    )
    assert result.returncode == 0, combined(result)
    cr = next(
        doc
        for doc in yaml.safe_load_all(
            (out / "k8s-instrumentation/instrumentation-cr.yaml").read_text(encoding="utf-8")
        )
        if doc
    )
    assert cr["metadata"] == {
        "name": "production-auto",
        "namespace": "observability",
        "labels": {
            "app.kubernetes.io/name": "splunk-otel-auto-instrumentation",
            "app.kubernetes.io/managed-by": (
                "splunk-observability-k8s-auto-instrumentation-setup"
            ),
        },
    }
    workload = next(
        doc
        for doc in yaml.safe_load_all(
            (out / "k8s-instrumentation/workload-annotations.yaml").read_text(encoding="utf-8")
        )
        if doc
    )
    namespace = next(
        doc
        for doc in yaml.safe_load_all(
            (out / "k8s-instrumentation/namespace-annotations.yaml").read_text(encoding="utf-8")
        )
        if doc
    )
    inject_key = "instrumentation.opentelemetry.io/inject-java"
    assert workload["spec"]["template"]["metadata"]["annotations"][inject_key] == (
        "observability/production-auto"
    )
    assert namespace["metadata"]["annotations"][inject_key] == "observability/production-auto"
    backup = yaml.safe_load(
        (out / "k8s-instrumentation/annotation-backup-configmap.yaml").read_text(encoding="utf-8")
    )
    assert backup["metadata"]["namespace"] == "observability"


def test_cli_cr_name_rejects_ambiguous_multi_cr_spec(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        instrumentation_crs=[
            {"name": "dev", "namespace": "splunk-otel", "languages": ["java"]},
            {"name": "prod", "namespace": "splunk-otel", "languages": ["java"]},
        ],
    )
    result = run_render(
        "--spec",
        str(spec),
        "--output-dir",
        str(tmp_path / "rendered"),
        "--instrumentation-cr-name",
        "ambiguous",
        "--multi-instrumentation",
    )
    assert result.returncode != 0
    assert "valid only with one Instrumentation CR" in combined(result)


def test_unimplemented_operator_installation_control_fails_closed(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.yaml")
    result = run_render(
        "--spec",
        str(spec),
        "--output-dir",
        str(tmp_path / "rendered"),
        "--installation-job-enabled",
        "false",
    )
    assert result.returncode == 2, combined(result)
    report = (
        tmp_path / "rendered/k8s-instrumentation/preflight-report.md"
    ).read_text(encoding="utf-8")
    assert "cannot be applied by this overlay" in report

    invalid = run_render(
        "--spec",
        str(spec),
        "--output-dir",
        str(tmp_path / "invalid"),
        "--installation-job-enabled",
        "sometimes",
    )
    assert invalid.returncode == 2
    assert "cannot be applied by this overlay" in (
        tmp_path / "invalid/k8s-instrumentation/preflight-report.md"
    ).read_text(encoding="utf-8")


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


def test_multi_cr_uses_explicit_bindings_without_claiming_operator_control(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        instrumentation_crs=[
            {"name": "dev", "namespace": "splunk-otel", "languages": ["java"]},
            {"name": "prod", "namespace": "splunk-otel", "languages": ["java"]},
        ],
    )
    out = tmp_path / "r"
    result = run_render("--spec", str(spec), "--output-dir", str(out), "--dry-run")
    assert result.returncode == 0, combined(result)


def test_unimplemented_multi_instrumentation_operator_control_fails_closed(tmp_path: Path) -> None:
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
    assert result.returncode == 2
    assert "cannot be applied by this overlay" in (
        out / "k8s-instrumentation/preflight-report.md"
    ).read_text(encoding="utf-8")


def test_sdk_language_is_rejected_as_unsupported(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        instrumentation_crs=[
            {"name": "sdk", "namespace": "splunk-otel", "languages": ["sdk"]}
        ],
        workload_annotations=[
            {"kind": "Deployment", "namespace": "prod", "name": "app", "language": "sdk"}
        ],
    )
    result = run_render("--spec", str(spec), "--output-dir", str(tmp_path / "r"))
    assert result.returncode != 0
    assert "Unsupported language 'sdk'" in combined(result)


def test_workload_binding_must_resolve_a_cr_with_the_language(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        instrumentation_crs=[
            {"name": "java-only", "namespace": "splunk-otel", "languages": ["java"]}
        ],
        workload_annotations=[
            {
                "kind": "Deployment",
                "namespace": "apps",
                "name": "web",
                "language": "nodejs",
                "cr": "splunk-otel/java-only",
            }
        ],
    )
    result = run_render("--spec", str(spec), "--output-dir", str(tmp_path / "r"), "--dry-run")
    assert result.returncode == 2
    assert "does not enable the language" in combined(result)


def test_multi_language_rows_merge_one_workload_manifest(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        workload_annotations=[
            {"kind": "Deployment", "namespace": "apps", "name": "api", "language": "java"},
            {"kind": "Deployment", "namespace": "apps", "name": "api", "language": "nodejs"},
        ],
    )
    out = tmp_path / "rendered"
    result = run_render("--spec", str(spec), "--output-dir", str(out))
    assert result.returncode == 0, combined(result)
    documents = [
        document
        for document in yaml.safe_load_all(
            (out / "k8s-instrumentation/workload-annotations.yaml").read_text(encoding="utf-8")
        )
        if document
    ]
    assert len(documents) == 1
    annotations = documents[0]["spec"]["template"]["metadata"]["annotations"]
    assert set(annotations) == {
        "instrumentation.opentelemetry.io/inject-java",
        "instrumentation.opentelemetry.io/inject-nodejs",
    }
    metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    assert [(row["target"], row["language"]) for row in metadata["targets"]] == [
        ("Deployment/apps/api", "java"),
        ("Deployment/apps/api", "nodejs"),
    ]
    assert len({row["key"] for row in metadata["targets"]}) == 1


def test_duplicate_or_conflicting_workload_rows_fail_closed(tmp_path: Path) -> None:
    duplicate = write_spec(
        tmp_path / "duplicate.yaml",
        workload_annotations=[
            {"kind": "Deployment", "namespace": "apps", "name": "api", "language": "java"},
            {"kind": "Deployment", "namespace": "apps", "name": "api", "language": "java"},
        ],
    )
    duplicate_result = run_render(
        "--spec", str(duplicate), "--output-dir", str(tmp_path / "duplicate"), "--dry-run"
    )
    assert duplicate_result.returncode == 2
    assert "Duplicate workload/language target" in combined(duplicate_result)

    conflict = write_spec(
        tmp_path / "conflict.yaml",
        workload_annotations=[
            {
                "kind": "Deployment",
                "namespace": "apps",
                "name": "api",
                "language": "java",
                "container_names": "api",
            },
            {
                "kind": "Deployment",
                "namespace": "apps",
                "name": "api",
                "language": "nodejs",
                "container_names": "sidecar",
            },
        ],
    )
    conflict_result = run_render(
        "--spec", str(conflict), "--output-dir", str(tmp_path / "conflict"), "--dry-run"
    )
    assert conflict_result.returncode == 2
    assert "conflicting values for managed annotation" in combined(conflict_result)


def test_missing_explicit_cr_binding_fails_closed(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        workload_annotations=[
            {
                "kind": "Deployment",
                "namespace": "apps",
                "name": "api",
                "language": "java",
                "cr": "splunk-otel/does-not-exist",
            }
        ],
    )
    result = run_render("--spec", str(spec), "--output-dir", str(tmp_path / "r"), "--dry-run")
    assert result.returncode == 2
    assert "references missing Instrumentation CR" in combined(result)


def test_default_language_images_are_audited_digest_pins(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        instrumentation_crs=[
            {
                "name": "all-audited",
                "namespace": "splunk-otel",
                "languages": ["java", "nodejs", "python", "dotnet", "go", "apache-httpd"],
            }
        ],
        workload_annotations=[],
    )
    out = tmp_path / "rendered"
    result = run_render("--spec", str(spec), "--output-dir", str(out))
    assert result.returncode == 0, combined(result)
    cr = next(
        doc
        for doc in yaml.safe_load_all(
            (out / "k8s-instrumentation/instrumentation-cr.yaml").read_text(encoding="utf-8")
        )
        if doc
    )
    for block in ("java", "nodejs", "python", "dotnet", "go", "apacheHttpd"):
        assert re.fullmatch(r"\S+@sha256:[0-9a-f]{64}", cr["spec"][block]["image"]), block
    assert cr["spec"]["go"]["image"].startswith(
        "ghcr.io/open-telemetry/opentelemetry-go-instrumentation/autoinstrumentation-go@"
    )


def test_mutable_image_override_is_rejected(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        instrumentation_crs=[
            {
                "name": "mutable",
                "namespace": "splunk-otel",
                "languages": ["java"],
                "images": {"java": "ghcr.io/signalfx/splunk-otel-java:v2.28.0"},
            }
        ],
    )
    result = run_render("--spec", str(spec), "--output-dir", str(tmp_path / "r"), "--dry-run")
    assert result.returncode == 2
    assert "must be pinned by an immutable @sha256 digest" in combined(result)


def test_nginx_without_repository_audited_digest_fails_closed(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        instrumentation_crs=[
            {"name": "nginx", "namespace": "splunk-otel", "languages": ["nginx"]}
        ],
    )
    result = run_render("--spec", str(spec), "--output-dir", str(tmp_path / "r"), "--dry-run")
    assert result.returncode == 2
    assert "No repository-audited default image exists for nginx" in combined(result)


def test_obi_without_reviewed_digest_fails_closed(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        obi={"enabled": True, "version": "", "image": ""},
    )
    result = run_render("--spec", str(spec), "--output-dir", str(tmp_path / "r"), "--dry-run")
    assert result.returncode == 2
    assert "No repository-audited OBI container default exists" in combined(result)

    tagged = write_spec(
        tmp_path / "tagged.yaml",
        obi={"enabled": True, "version": "", "image": "example.test/obi:v1.2.3"},
    )
    tagged_result = run_render(
        "--spec", str(tagged), "--output-dir", str(tmp_path / "tagged"), "--dry-run"
    )
    assert tagged_result.returncode == 2
    assert "OBI image must be pinned" in combined(tagged_result)


def test_apply_annotations_requires_accept(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.yaml")
    out = tmp_path / "r"
    result = run_render(
        "--spec", str(spec), "--output-dir", str(out), "--mode", "apply-annotations", "--dry-run"
    )
    assert result.returncode == 2
    assert "--apply-annotations requires --accept-auto-instrumentation" in combined(result)


def test_apply_instrumentation_preflight_requires_accept_and_explicit_context(
    tmp_path: Path,
) -> None:
    spec = write_spec(tmp_path / "spec.yaml")
    no_accept = run_render(
        "--spec",
        str(spec),
        "--output-dir",
        str(tmp_path / "no-accept"),
        "--mode",
        "apply-instrumentation",
        "--kube-context",
        "prod-context",
        "--dry-run",
    )
    assert no_accept.returncode == 2
    assert "--apply-instrumentation requires --accept-auto-instrumentation" in combined(no_accept)

    no_context = run_render(
        "--spec",
        str(spec),
        "--output-dir",
        str(tmp_path / "no-context"),
        "--mode",
        "apply-instrumentation",
        "--accept-auto-instrumentation",
        "--dry-run",
    )
    assert no_context.returncode == 2
    assert "requires --kube-context CTX" in combined(no_context)


def test_apply_instrumentation_operation_dry_run_needs_no_live_acceptance(
    tmp_path: Path,
) -> None:
    spec = write_spec(tmp_path / "spec.yaml")
    out = tmp_path / "rendered"
    result = run_setup(
        "--apply-instrumentation",
        "--dry-run",
        "--spec",
        str(spec),
        "--output-dir",
        str(out),
    )
    assert result.returncode == 0, combined(result)
    assert "DRY RUN:" in result.stdout


def test_obi_requires_accept_obi_privileged(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        obi={"enabled": True, "namespaces": [], "exclude_namespaces": [], "version": "", "image": TEST_OBI_IMAGE, "render_openshift_scc": True},
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
        obi={"enabled": True, "namespaces": [], "exclude_namespaces": [], "version": "", "image": TEST_OBI_IMAGE, "render_openshift_scc": True},
    )
    out = tmp_path / "r"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    scc = out / "k8s-instrumentation/openshift-scc-obi.yaml"
    assert scc.exists()
    body = scc.read_text(encoding="utf-8")
    assert "SecurityContextConstraints" in body
    assert "allowPrivilegedContainer: true" in body
    obi_docs = [
        document
        for document in yaml.safe_load_all(
            (out / "k8s-instrumentation/obi-daemonset.yaml").read_text(encoding="utf-8")
        )
        if document
    ]
    assert [document["kind"] for document in obi_docs] == ["ServiceAccount", "DaemonSet"]
    assert obi_docs[0]["metadata"]["labels"]["app.kubernetes.io/managed-by"] == (
        "splunk-observability-k8s-auto-instrumentation-setup"
    )
    assert obi_docs[1]["spec"]["template"]["spec"]["nodeSelector"] == {
        "kubernetes.io/os": "linux"
    }
    metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["obi_contract"]["documents"] == obi_docs
    assert metadata["obi_contract"]["scc_documents"] == [
        document for document in yaml.safe_load_all(body) if document
    ]


def test_non_openshift_obi_still_renders_owned_service_account(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        obi={"enabled": True, "image": TEST_OBI_IMAGE, "version": ""},
    )
    out = tmp_path / "rendered"
    result = run_render("--spec", str(spec), "--output-dir", str(out))
    assert result.returncode == 0, combined(result)
    documents = [
        document
        for document in yaml.safe_load_all(
            (out / "k8s-instrumentation/obi-daemonset.yaml").read_text(encoding="utf-8")
        )
        if document
    ]
    assert [document["kind"] for document in documents] == ["ServiceAccount", "DaemonSet"]
    uninstall = (out / "k8s-instrumentation/uninstall.sh").read_text(encoding="utf-8")
    assert "--purge-obi" in uninstall
    assert "obi-lifecycle.py" in uninstall


def test_obi_live_gate_and_safe_purge_contract(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        obi={"enabled": True, "image": TEST_OBI_IMAGE, "version": ""},
    )
    out = tmp_path / "rendered"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    service_account, daemonset = metadata["obi_contract"]["documents"]
    service_account = json.loads(json.dumps(service_account))
    daemonset = json.loads(json.dumps(daemonset))
    service_account["metadata"].update({"uid": "sa-uid", "resourceVersion": "11"})
    daemonset["metadata"].update({"uid": "ds-uid", "resourceVersion": "12"})
    daemonset["metadata"]["generation"] = 3
    daemonset["status"] = {
        "observedGeneration": 3,
        "desiredNumberScheduled": 1,
        "currentNumberScheduled": 1,
        "updatedNumberScheduled": 1,
        "numberReady": 1,
        "numberAvailable": 1,
    }
    nodes = {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            {
                "metadata": {
                    "name": "node-a",
                    "labels": {"kubernetes.io/os": "linux", "kubernetes.io/arch": "amd64"},
                },
                "spec": {},
                "status": {
                    "conditions": [{"type": "Ready", "status": "True"}],
                    "nodeInfo": {
                        "operatingSystem": "linux",
                        "architecture": "amd64",
                        "kernelVersion": "6.1.99-1",
                    },
                },
            }
        ],
    }
    pods = {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            {
                "metadata": {"name": "splunk-obi-abc", "namespace": "splunk-otel"},
                "spec": {
                    "nodeName": "node-a",
                    "containers": [{"name": "obi", "image": TEST_OBI_IMAGE}],
                },
                "status": {
                    "phase": "Running",
                    "conditions": [{"type": "Ready", "status": "True"}],
                },
            }
        ],
    }
    fake = tmp_path / "kubectl"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        f"sa = json.loads({json.dumps(json.dumps(service_account))})\n"
        f"ds = json.loads({json.dumps(json.dumps(daemonset))})\n"
        f"nodes = json.loads({json.dumps(json.dumps(nodes))})\n"
        f"pods = json.loads({json.dumps(json.dumps(pods))})\n"
        "args = sys.argv[1:]\n"
        "if 'get' in args:\n"
        "    resource = args[args.index('get') + 1]\n"
        "    if resource == 'serviceaccount': obj = sa\n"
        "    elif resource == 'daemonset':\n"
        "        obj = ds\n"
        "        if os.environ.get('OBI_DRIFT') == '1': obj['spec']['template']['spec']['containers'][0]['image'] = 'drifted:latest'\n"
        "    elif resource == 'nodes': obj = nodes\n"
        "    elif resource == 'pods': obj = pods\n"
        "    else: raise SystemExit('unexpected get ' + resource)\n"
        "    print(json.dumps(obj))\n"
        "elif 'logs' in args:\n"
        "    if os.environ.get('OBI_LOG_FAILURE') == '1':\n"
        "        print('PRIVATE_PARTIAL_LOG_MARKER')\n"
        "        raise SystemExit(1)\n"
        "    print(os.environ.get('OBI_LOG', '2026-01-01T00:00:00Z healthy'))\n"
        "elif 'delete' in args:\n"
        "    options = json.load(sys.stdin)\n"
        "    assert options['preconditions']['uid'] in {'ds-uid', 'sa-uid'}\n"
        "    with pathlib.Path(os.environ['OBI_DELETE_LOG']).open('a') as handle: handle.write(args[args.index('--raw') + 1] + '\\n')\n"
        "    print('deleted')\n"
        "else:\n"
        "    raise SystemExit('unexpected argv ' + repr(args))\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    delete_log = tmp_path / "deletes"
    env = os.environ.copy()
    env["OBI_DELETE_LOG"] = str(delete_log)
    helper = out / "k8s-instrumentation/obi-lifecycle.py"
    command = [
        sys.executable,
        str(helper),
        "--mode",
        "validate",
        "--metadata",
        str(out / "metadata.json"),
        "--kubectl-bin",
        str(fake),
    ]
    valid = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    assert valid.returncode == 0, combined(valid)
    assert "rollout, node coverage, and bounded logs: OK" in valid.stdout

    fatal = subprocess.run(
        command,
        env=dict(env, OBI_LOG="2026-01-01T00:00:00Z fatal: bpf load failed"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert fatal.returncode != 0
    assert "fatal health rule" in combined(fatal)

    failed_logs = subprocess.run(
        command,
        env=dict(env, OBI_LOG_FAILURE="1"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert failed_logs.returncode != 0
    assert "command output suppressed" in combined(failed_logs)
    assert "PRIVATE_PARTIAL_LOG_MARKER" not in combined(failed_logs)

    drift = subprocess.run(
        command,
        env=dict(env, OBI_DRIFT="1"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert drift.returncode != 0
    assert "managed configuration drifted" in combined(drift)

    purge = subprocess.run(
        [*command[:2], "--mode", "purge", *command[4:]],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert purge.returncode == 0, combined(purge)
    assert delete_log.read_text(encoding="utf-8").splitlines() == [
        "/apis/apps/v1/namespaces/splunk-otel/daemonsets/splunk-obi",
        "/api/v1/namespaces/splunk-otel/serviceaccounts/splunk-obi",
    ]


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
    # Ordered contract: no helm uninstall reference earlier than the
    # ownership-checked, preconditioned Instrumentation delete.
    lower = body.lower()
    otelinst_idx = lower.find("managed-resource-lifecycle.py\" --mode delete")
    helm_idx = lower.find("helm uninstall")
    assert otelinst_idx != -1, "uninstall.sh must safely delete the Instrumentation CR"
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


@pytest.mark.parametrize(
    "extra_env",
    [
        {"java": {"API_TOKEN": "tiny"}},
        {"java": {"OTEL_EXPORTER_OTLP_HEADERS": "X-SF-Token=abcd"}},
        {"java": {"AUTHORIZATION": "Bearer abcd"}},
    ],
)
def test_spec_secret_like_env_is_rejected(tmp_path: Path, extra_env: dict[str, object]) -> None:
    spec = write_spec(
        tmp_path / "secret.yaml",
        instrumentation_crs=[
            {
                "name": "default",
                "namespace": "splunk-otel",
                "languages": ["java"],
                "extra_env": extra_env,
            }
        ],
    )
    result = run_render("--spec", str(spec), "--output-dir", str(tmp_path / "rendered"))
    assert result.returncode != 0
    assert "token-shaped" in combined(result) or "secret-like" in combined(result)


def test_cli_secret_like_env_and_credentialed_endpoint_are_rejected(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.yaml")
    env_result = run_render(
        "--spec",
        str(spec),
        "--output-dir",
        str(tmp_path / "env"),
        "--extra-env",
        "java=HEC_TOKEN=tiny",
    )
    assert env_result.returncode != 0
    assert "secret-like" in combined(env_result)

    endpoint_result = run_render(
        "--spec",
        str(spec),
        "--output-dir",
        str(tmp_path / "endpoint"),
        "--gateway-endpoint",
        "https://user:pass@collector.example.test:4317/v1/traces?token=abcd",
        "--dry-run",
    )
    assert endpoint_result.returncode != 0
    assert "credential" in combined(endpoint_result).lower()


def test_image_pull_secret_name_reference_is_allowed_but_not_material(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        image_pull_secret="private-registry-token",
    )
    out = tmp_path / "rendered"
    result = run_render("--spec", str(spec), "--output-dir", str(out))
    assert result.returncode == 0, combined(result)
    static = subprocess.run(
        ["bash", str(VALIDATE), "--output-dir", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert static.returncode == 0, combined(static)
    cr = next(
        document
        for document in yaml.safe_load_all(
            (out / "k8s-instrumentation/instrumentation-cr.yaml").read_text(encoding="utf-8")
        )
        if document
    )
    assert cr["spec"]["imagePullSecrets"] == [{"name": "private-registry-token"}]


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"cluster_name": ""}, "Missing cluster name"),
        ({"realm": "moon0"}, "Unsupported Splunk Observability realm"),
        ({"namespace": "Bad_Namespace"}, "DNS-1123 label"),
        (
            {
                "instrumentation_crs": [
                    {
                        "name": "default",
                        "namespace": "splunk-otel",
                        "languages": ["java"],
                        "propagators": ["tracecontext", "tracecontext"],
                    }
                ]
            },
            "invalid, duplicate",
        ),
        (
            {
                "instrumentation_crs": [
                    {
                        "name": "default",
                        "namespace": "splunk-otel",
                        "languages": ["java"],
                        "sampler": {"type": "traceidratio", "argument": "1.5"},
                    }
                ]
            },
            "requires an argument from 0 through 1",
        ),
    ],
)
def test_identity_and_telemetry_contract_validation(
    tmp_path: Path, overrides: dict[str, object], expected: str
) -> None:
    spec = write_spec(tmp_path / "spec.yaml", **overrides)
    result = run_render(
        "--spec", str(spec), "--output-dir", str(tmp_path / "rendered"), "--dry-run"
    )
    assert result.returncode == 2
    assert expected in combined(result)


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


def test_static_validate_rejects_mutable_image_tampering(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.yaml")
    out = tmp_path / "rendered"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    cr_path = out / "k8s-instrumentation/instrumentation-cr.yaml"
    body = cr_path.read_text(encoding="utf-8")
    body = re.sub(r"image: \S+@sha256:[0-9a-f]{64}", "image: example.test/java:latest", body, count=1)
    cr_path.write_text(body, encoding="utf-8")
    result = subprocess.run(
        ["bash", str(VALIDATE), "--output-dir", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "not pinned by an immutable @sha256 digest" in combined(result)


def test_static_validate_rejects_obi_contract_tampering(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        obi={"enabled": True, "image": TEST_OBI_IMAGE, "version": ""},
    )
    out = tmp_path / "rendered"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    manifest = out / "k8s-instrumentation/obi-daemonset.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "SPLUNK_OBI_NAMESPACE_EXCLUDE", "SPLUNK_OBI_NAMESPACE_EXCLUDE_DRIFTED", 1
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(VALIDATE), "--output-dir", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "OBI document contract does not exactly match" in combined(result)


def webhook_kubectl_env(
    tmp_path: Path,
    *,
    endpoint_slice_available: bool,
    endpoint_slice_ready: bool = True,
) -> tuple[dict[str, str], Path]:
    ca_bundle = (
        "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tClkyVnlkR2xtYVdOaGRHVXRZbnAwWlhNPQotLS0tLUVORCBDRVJUSUZJQ0FURS0tLS0tCg=="
    )
    operator = "splunk-otel-collector-operator"
    service_name = f"{operator}-webhook"
    webhook = {
        "apiVersion": "admissionregistration.k8s.io/v1",
        "kind": "MutatingWebhookConfiguration",
        "metadata": {"name": f"{operator}-mutation"},
        "webhooks": [
            {
                "name": "mpod.kb.io",
                "admissionReviewVersions": ["v1"],
                "sideEffects": "None",
                "failurePolicy": "Ignore",
                "timeoutSeconds": 10,
                "clientConfig": {
                    "caBundle": ca_bundle,
                    "service": {
                        "name": service_name,
                        "namespace": "splunk-otel",
                        "path": "/mutate-v1-pod",
                        "port": 443,
                    },
                },
                "rules": [
                    {
                        "apiGroups": [""],
                        "apiVersions": ["v1"],
                        "operations": ["CREATE"],
                        "resources": ["pods"],
                        "scope": "Namespaced",
                    }
                ],
            }
        ],
    }
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": service_name, "namespace": "splunk-otel"},
        "spec": {
            "type": "ClusterIP",
            "clusterIP": "172.20.0.10",
            "selector": {"app.kubernetes.io/name": "operator"},
            "ports": [{"port": 443, "protocol": "TCP", "targetPort": "webhook-server"}],
        },
    }
    endpoint_slices = {
        "apiVersion": "v1",
        "kind": "EndpointSliceList",
        "items": [
            {
                "apiVersion": "discovery.k8s.io/v1",
                "kind": "EndpointSlice",
                "metadata": {
                    "name": f"{service_name}-abc",
                    "namespace": "splunk-otel",
                    "labels": {"kubernetes.io/service-name": service_name},
                },
                "addressType": "IPv4",
                "ports": [{"name": "webhook-server", "port": 9443, "protocol": "TCP"}],
                "endpoints": [
                    {
                        "addresses": ["10.0.0.10"],
                        "conditions": {"ready": endpoint_slice_ready},
                    }
                ],
            }
        ],
    }
    endpoints = {
        "apiVersion": "v1",
        "kind": "Endpoints",
        "metadata": {"name": service_name, "namespace": "splunk-otel"},
        "subsets": [
            {
                "addresses": [{"ip": "10.0.0.10"}],
                "ports": [{"name": "webhook-server", "port": 9443, "protocol": "TCP"}],
            }
        ],
    }
    pods = {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            {
                "metadata": {"name": f"{operator}-abc", "namespace": "splunk-otel"},
                "status": {
                    "phase": "Running",
                    "conditions": [{"type": "Ready", "status": "True"}],
                },
            }
        ],
    }
    payloads = {
        "webhook": webhook,
        "service": service,
        "endpointslice": endpoint_slices,
        "endpoints": endpoints,
        "pods": pods,
    }
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    log = tmp_path / "calls.jsonl"
    kubectl = fake_bin / "kubectl"
    kubectl.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "from pathlib import Path\n"
        f"payloads = json.loads({json.dumps(json.dumps(payloads))})\n"
        f"endpoint_slice_available = {endpoint_slice_available!r}\n"
        f"log = Path({str(log)!r})\n"
        "args = sys.argv[1:]\n"
        "with log.open('a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps(args) + '\\n')\n"
        "if 'logs' in args:\n"
        "    raise SystemExit(0)\n"
        "if 'mutatingwebhookconfiguration' in args:\n"
        "    key = 'webhook'\n"
        "elif 'service' in args:\n"
        "    key = 'service'\n"
        "elif 'endpointslice' in args:\n"
        "    if not endpoint_slice_available:\n"
        "        raise SystemExit(1)\n"
        "    key = 'endpointslice'\n"
        "elif 'endpoints' in args:\n"
        "    key = 'endpoints'\n"
        "elif 'pods' in args:\n"
        "    key = 'pods'\n"
        "else:\n"
        "    raise SystemExit(2)\n"
        "print(json.dumps(payloads[key]))\n",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    return env, log


def test_webhook_validation_prefers_ready_endpoint_slice(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.yaml")
    out = tmp_path / "rendered"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    env, log = webhook_kubectl_env(
        tmp_path / "fake", endpoint_slice_available=True, endpoint_slice_ready=True
    )
    result = subprocess.run(
        ["bash", str(VALIDATE), "--output-dir", str(out), "--check-webhook", "--kube-context", "test-context"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, combined(result)
    assert "source=endpointslice" in result.stdout
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert any("endpointslice" in call for call in calls)
    assert not any("endpoints" in call for call in calls)


def test_webhook_validation_falls_back_only_when_endpoint_slice_unavailable(
    tmp_path: Path,
) -> None:
    spec = write_spec(tmp_path / "spec.yaml")
    out = tmp_path / "rendered"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    fallback_env, fallback_log = webhook_kubectl_env(
        tmp_path / "fallback", endpoint_slice_available=False
    )
    fallback = subprocess.run(
        ["bash", str(VALIDATE), "--output-dir", str(out), "--check-webhook", "--kube-context", "test-context"],
        cwd=REPO_ROOT,
        env=fallback_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert fallback.returncode == 0, combined(fallback)
    assert "source=endpoints" in fallback.stdout
    fallback_calls = [
        json.loads(line) for line in fallback_log.read_text(encoding="utf-8").splitlines()
    ]
    assert any("endpointslice" in call for call in fallback_calls)
    assert any("endpoints" in call for call in fallback_calls)

    unready_env, unready_log = webhook_kubectl_env(
        tmp_path / "unready", endpoint_slice_available=True, endpoint_slice_ready=False
    )
    unready = subprocess.run(
        ["bash", str(VALIDATE), "--output-dir", str(out), "--check-webhook", "--kube-context", "test-context"],
        cwd=REPO_ROOT,
        env=unready_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert unready.returncode != 0
    assert "no ready address on the pinned 9443/TCP" in combined(unready)
    unready_calls = [
        json.loads(line) for line in unready_log.read_text(encoding="utf-8").splitlines()
    ]
    assert any("endpointslice" in call for call in unready_calls)
    assert not any("endpoints" in call for call in unready_calls)


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


@pytest.mark.parametrize(
    "flag",
    ["--access-token", "--token", "--api-token", "--o11y-token", "--hec-token", "--api-key"],
)
@pytest.mark.parametrize("entrypoint", [SETUP, VALIDATE])
def test_shell_entrypoints_reject_equals_secret_flags_without_echoing_value(
    flag: str,
    entrypoint: Path,
) -> None:
    synthetic = "TEST_ONLY_" + "EXAMPLE_SECRET_VALUE"
    result = subprocess.run(
        ["bash", str(entrypoint), f"{flag}={synthetic}"],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode != 0
    assert flag in combined(result)
    assert synthetic not in combined(result)


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
                "images": {"nginx": f"registry.example.test/otel-nginx@sha256:{'a' * 64}"},
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
    assert "OTEL_DOTNET_AUTO_HOME" not in cr_body


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


def render_single_java_target(tmp_path: Path) -> Path:
    out = tmp_path / "r"
    spec = write_spec(
        tmp_path / "spec.yaml",
        workload_annotations=[
            {
                "kind": "Deployment",
                "namespace": "prod",
                "name": "payments-api",
                "language": "java",
            }
        ],
    )
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    return out


def render_namespace_java_target(tmp_path: Path) -> Path:
    out = tmp_path / "r"
    spec = write_spec(
        tmp_path / "spec.yaml",
        namespace_annotations={"apps": ["java"]},
        workload_annotations=[],
    )
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    return out


def run_rendered(
    out: Path,
    script: str,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(out / "k8s-instrumentation" / script), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def injection_kubectl_env(
    tmp_path: Path,
    out: Path,
    *,
    include_java_hook: bool = True,
    annotation_drift: bool = False,
    pod_ready: bool = True,
    workload_current: bool = True,
    image_drift: bool = False,
) -> dict[str, str]:
    metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    target = next(row for row in metadata["targets"] if row["name"] == "payments-api")
    expected_annotations = dict(target["annotations"])
    workload_annotations = dict(expected_annotations)
    if annotation_drift:
        workload_annotations["instrumentation.opentelemetry.io/inject-nodejs"] = (
            "splunk-otel/splunk-otel-auto-instrumentation"
        )
    cr = next(
        doc
        for doc in yaml.safe_load_all(
            (out / "k8s-instrumentation/instrumentation-cr.yaml").read_text(encoding="utf-8")
        )
        if doc
    )
    endpoint = next(
        item["value"]
        for item in cr["spec"]["java"]["env"]
        if item["name"] == "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    java_image = cr["spec"]["java"]["image"]
    if image_drift:
        java_image = f"registry.example.test/drifted-java@sha256:{'e' * 64}"
    app_env = [{"name": "OTEL_EXPORTER_OTLP_ENDPOINT", "value": endpoint}]
    if include_java_hook:
        app_env.append(
            {
                "name": "JAVA_TOOL_OPTIONS",
                "value": "-javaagent:/otel-auto-instrumentation-java-app/javaagent.jar",
            }
        )
    workload = {
        "kind": "Deployment",
        "metadata": {"generation": 3},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": "payments"}},
            "template": {"metadata": {"annotations": workload_annotations}},
        },
        "status": {
            "observedGeneration": 3 if workload_current else 2,
            "replicas": 1,
            "readyReplicas": 1,
            "updatedReplicas": 1,
            "availableReplicas": 1,
        },
    }
    pods = {
        "kind": "List",
        "items": [
            {
                "metadata": {
                    "name": "payments-api-abc",
                    "namespace": "prod",
                    "labels": {"app": "payments"},
                    "annotations": expected_annotations,
                },
                "spec": {
                    "initContainers": [
                        {
                            "name": "opentelemetry-auto-instrumentation-java",
                            "image": java_image,
                        }
                    ],
                    "containers": [{"name": "app", "env": app_env}],
                },
                "status": {
                    "phase": "Running",
                    "conditions": [
                        {"type": "Ready", "status": "True" if pod_ready else "False"}
                    ],
                },
            }
        ],
    }
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    kubectl = fake_bin / "kubectl"
    kubectl.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"workload = json.loads({json.dumps(json.dumps(workload))})\n"
        f"pods = json.loads({json.dumps(json.dumps(pods))})\n"
        "print(json.dumps(pods if 'pods' in sys.argv[1:] else workload))\n",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    return env


def namespace_injection_kubectl_env(
    tmp_path: Path,
    out: Path,
    *,
    explicit_opt_out: bool = False,
    stale_opt_out: bool = False,
    namespace_drift: bool = False,
    missing_injection: bool = False,
    pod_ready: bool = True,
    empty_active: bool = False,
    include_terminal: bool = True,
) -> dict[str, str]:
    metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    namespace_target = metadata["namespace_targets"][0]
    namespace_annotations = dict(namespace_target["annotations"])
    if namespace_drift:
        namespace_annotations["instrumentation.opentelemetry.io/inject-java"] = (
            "splunk-otel/not-rendered"
        )
    java_block = metadata["instrumentation_documents"][0]["spec"]["java"]
    endpoint = next(
        item["value"]
        for item in java_block["env"]
        if item["name"] == "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    pod_annotations = (
        {"instrumentation.opentelemetry.io/inject-java": "false"}
        if explicit_opt_out
        else {}
    )
    injected_artifacts = not missing_injection and (not explicit_opt_out or stale_opt_out)
    app_env: list[dict[str, str]] = []
    init_containers: list[dict[str, str]] = []
    if injected_artifacts:
        init_containers.append(
            {
                "name": "opentelemetry-auto-instrumentation-java",
                "image": java_block["image"],
            }
        )
        app_env.extend(
            [
                {"name": "OTEL_EXPORTER_OTLP_ENDPOINT", "value": endpoint},
                {
                    "name": "JAVA_TOOL_OPTIONS",
                    "value": "-javaagent:/otel-auto-instrumentation-java-app/javaagent.jar",
                },
            ]
        )
    active = {
        "metadata": {
            "name": "api-abc",
            "namespace": "apps",
            "annotations": pod_annotations,
        },
        "spec": {
            "initContainers": init_containers,
            "containers": [{"name": "app", "env": app_env}],
        },
        "status": {
            "phase": "Running",
            "conditions": [
                {"type": "Ready", "status": "True" if pod_ready else "False"}
            ],
        },
    }
    terminal = {
        "metadata": {"name": "old-job", "namespace": "apps", "annotations": {}},
        "spec": {"containers": [{"name": "job", "env": []}]},
        "status": {"phase": "Succeeded", "conditions": []},
    }
    pods = [] if empty_active else [active]
    if include_terminal:
        pods.append(terminal)
    namespace_object = {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {"name": "apps", "annotations": namespace_annotations},
    }
    pod_list = {"apiVersion": "v1", "kind": "List", "items": pods}
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    kubectl = fake_bin / "kubectl"
    kubectl.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"namespace = json.loads({json.dumps(json.dumps(namespace_object))})\n"
        f"pods = json.loads({json.dumps(json.dumps(pod_list))})\n"
        "args = sys.argv[1:]\n"
        "if 'pods' in args:\n"
        "    print(json.dumps(pods))\n"
        "elif 'namespace' in args:\n"
        "    print(json.dumps(namespace))\n"
        "else:\n"
        "    raise SystemExit(2)\n",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    return env


def test_rendered_apply_annotations_requires_target_selection(tmp_path: Path) -> None:
    out = render_default(tmp_path)
    # Without --target / --target-all the rendered script must refuse rather
    # than silently no-op (the bug: ${TARGETS[@]:-} sent [""] to Python).
    result = run_rendered(out, "apply-annotations.sh", "--accept-auto-instrumentation", "--dry-run")
    assert result.returncode != 0
    assert "pass --target" in combined(result)


def test_rendered_apply_instrumentation_enforces_live_acceptance_and_context(
    tmp_path: Path,
) -> None:
    out = render_default(tmp_path)
    no_accept = run_rendered(out, "apply-instrumentation.sh", "--allow-current-context")
    assert no_accept.returncode != 0
    assert "--accept-auto-instrumentation is required" in combined(no_accept)

    no_context = run_rendered(
        out,
        "apply-instrumentation.sh",
        "--accept-auto-instrumentation",
    )
    assert no_context.returncode != 0
    assert "pass --kube-context CTX" in combined(no_context)

    preview = run_rendered(out, "apply-instrumentation.sh", "--dry-run")
    assert preview.returncode == 0, combined(preview)
    assert "DRY RUN:" in preview.stdout


def test_rendered_uninstall_requires_target_selection(tmp_path: Path) -> None:
    out = render_default(tmp_path)
    result = run_rendered(out, "uninstall.sh", "--accept-auto-instrumentation", "--dry-run")
    assert result.returncode != 0
    assert "select workload targets" in combined(result)


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
        "--allow-current-context",
        "--dry-run",
    )
    assert result.returncode == 0, combined(result)
    body = combined(result)
    assert "patch Deployment payments-api" in body
    assert "checkout-web" not in body


def test_rendered_apply_rejects_unknown_target(tmp_path: Path) -> None:
    out = render_default(tmp_path)
    result = run_rendered(
        out,
        "apply-annotations.sh",
        "--accept-auto-instrumentation",
        "--target",
        "Deployment/prod/not-rendered",
        "--dry-run",
    )
    assert result.returncode != 0
    assert "absent from metadata.json" in combined(result)


def test_rendered_uninstall_dry_run_specific_target(tmp_path: Path) -> None:
    out = render_default(tmp_path)
    result = run_rendered(
        out,
        "uninstall.sh",
        "--accept-auto-instrumentation",
        "--target",
        "Deployment/prod/payments-api",
        "--allow-current-context",
        "--dry-run",
    )
    assert result.returncode == 0, combined(result)
    body = combined(result)
    assert "complete, owned rollback snapshot" in body
    assert "checkout-web" not in body


def test_rendered_verify_injection_runs_deep_fail_closed_audit(tmp_path: Path) -> None:
    out = render_default(tmp_path)
    success = run_rendered(
        out,
        "verify-injection.sh",
        "--target",
        "Deployment/prod/payments-api",
        "--allow-current-context",
        env=injection_kubectl_env(tmp_path / "success", out),
    )
    assert success.returncode == 0, combined(success)
    assert "exact managed annotations and java evidence" in success.stdout

    missing_hook = run_rendered(
        out,
        "verify-injection.sh",
        "--target",
        "Deployment/prod/payments-api",
        "--allow-current-context",
        env=injection_kubectl_env(tmp_path / "missing", out, include_java_hook=False),
    )
    assert missing_hook.returncode != 0
    assert "JAVA_TOOL_OPTIONS" in combined(missing_hook)

    drifted_image = run_rendered(
        out,
        "verify-injection.sh",
        "--target",
        "Deployment/prod/payments-api",
        "--allow-current-context",
        env=injection_kubectl_env(tmp_path / "image-drift", out, image_drift=True),
    )
    assert drifted_image.returncode != 0
    assert "image does not exactly match" in combined(drifted_image)


def test_rendered_verify_rejects_unknown_target_without_namespace_fallback(tmp_path: Path) -> None:
    out = render_default(tmp_path)
    result = run_rendered(
        out,
        "verify-injection.sh",
        "--target",
        "Deployment/prod/not-rendered",
        "--allow-current-context",
        env=injection_kubectl_env(tmp_path / "unknown", out),
    )
    assert result.returncode != 0
    assert "absent from metadata.json" in combined(result)


def test_validate_check_injection_uses_rendered_deep_auditor(tmp_path: Path) -> None:
    out = render_single_java_target(tmp_path)
    success = subprocess.run(
        [
            "bash",
            str(VALIDATE),
            "--output-dir",
            str(out),
            "--check-injection",
            "--allow-current-context",
        ],
        cwd=REPO_ROOT,
        env=injection_kubectl_env(tmp_path / "validate-success", out),
        capture_output=True,
        text=True,
        check=False,
    )
    assert success.returncode == 0, combined(success)
    assert "exact managed annotations and java evidence" in success.stdout

    missing_hook = subprocess.run(
        [
            "bash",
            str(VALIDATE),
            "--output-dir",
            str(out),
            "--check-injection",
            "--allow-current-context",
        ],
        cwd=REPO_ROOT,
        env=injection_kubectl_env(
            tmp_path / "validate-missing-hook", out, include_java_hook=False
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_hook.returncode != 0
    assert "JAVA_TOOL_OPTIONS" in combined(missing_hook)


def test_live_validation_requires_explicit_context_or_acknowledgement(tmp_path: Path) -> None:
    out = render_single_java_target(tmp_path)
    missing = subprocess.run(
        ["bash", str(VALIDATE), "--output-dir", str(out), "--check-injection"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode != 0
    assert "requires --kube-context CTX" in combined(missing)

    conflict = subprocess.run(
        [
            "bash",
            str(VALIDATE),
            "--output-dir",
            str(out),
            "--check-injection",
            "--kube-context",
            "prod",
            "--allow-current-context",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert conflict.returncode != 0
    assert "conflicts with --allow-current-context" in combined(conflict)


def test_apm_check_is_bound_to_rendered_service_and_realm(tmp_path: Path) -> None:
    out = render_single_java_target(tmp_path)
    metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["apm_services"] == [
        {
            "service": "payments-api",
            "target": "Deployment/prod/payments-api",
            "realm": "us0",
            "cluster_name": "demo",
            "deployment_environment": "dev",
        }
    ]
    base_env = os.environ.copy()
    base_env["SPLUNK_O11Y_TOKEN_FILE"] = str(tmp_path / "must-not-be-read")

    wrong_realm_env = dict(base_env, SPLUNK_O11Y_REALM="eu0")
    wrong_realm = subprocess.run(
        [
            "bash",
            str(VALIDATE),
            "--output-dir",
            str(out),
            "--check-apm",
            "payments-api",
            "--allow-current-context",
        ],
        cwd=REPO_ROOT,
        env=wrong_realm_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert wrong_realm.returncode != 0
    assert "does not exactly match the realm" in combined(wrong_realm)

    arbitrary_env = dict(base_env, SPLUNK_O11Y_REALM="us0")
    arbitrary = subprocess.run(
        [
            "bash",
            str(VALIDATE),
            "--output-dir",
            str(out),
            "--check-apm",
            "not-rendered",
            "--allow-current-context",
        ],
        cwd=REPO_ROOT,
        env=arbitrary_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert arbitrary.returncode != 0
    assert "not allowlisted" in combined(arbitrary)


def test_valid_rendered_apm_service_reaches_scoped_topology_gate(tmp_path: Path) -> None:
    out = render_single_java_target(tmp_path)
    token_file = tmp_path / "token"
    token_file.write_text("test-token-value", encoding="ascii")
    token_file.chmod(0o600)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl = fake_bin / "curl"
    curl.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "out = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])\n"
        "out.write_text(json.dumps({'data': {'nodes': "
        "[{'serviceName': 'payments-api', 'type': 'service'}], 'edges': []}}))\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["SPLUNK_O11Y_REALM"] = "us0"
    env["SPLUNK_O11Y_TOKEN_FILE"] = str(token_file)
    result = subprocess.run(
        [
            "bash",
            str(VALIDATE),
            "--output-dir",
            str(out),
            "--check-apm",
            "payments-api",
            "--allow-current-context",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, combined(result)
    assert "APM topology contains 'payments-api'" in combined(result)


def test_apm_data_envelope_rejects_explicit_partial_error(tmp_path: Path) -> None:
    out = render_single_java_target(tmp_path)
    token_file = tmp_path / "token"
    token_file.write_text("test-token-value", encoding="ascii")
    token_file.chmod(0o600)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl = fake_bin / "curl"
    curl.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "out = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])\n"
        "out.write_text(json.dumps({'data': {'nodes': "
        "[{'serviceName': 'payments-api', 'type': 'service'}]}, "
        "'errors': [{'message': 'partial topology failure'}]}))\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["SPLUNK_O11Y_REALM"] = "us0"
    env["SPLUNK_O11Y_TOKEN_FILE"] = str(token_file)
    result = subprocess.run(
        [
            "bash",
            str(VALIDATE),
            "--output-dir",
            str(out),
            "--check-apm",
            "payments-api",
            "--allow-current-context",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "explicit error payload" in combined(result)


@pytest.mark.parametrize(
    ("fixture_kwargs", "expected"),
    [
        ({"pod_ready": False}, "is not Ready"),
        ({"workload_current": False}, "has not observed the current workload generation"),
    ],
)
def test_validate_check_injection_requires_ready_current_workloads(
    tmp_path: Path,
    fixture_kwargs: dict[str, bool],
    expected: str,
) -> None:
    out = render_single_java_target(tmp_path)
    result = subprocess.run(
        [
            "bash",
            str(VALIDATE),
            "--output-dir",
            str(out),
            "--check-injection",
            "--allow-current-context",
        ],
        cwd=REPO_ROOT,
        env=injection_kubectl_env(tmp_path / "not-ready", out, **fixture_kwargs),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert expected in combined(result)


def test_static_validation_rejects_tampered_rendered_injection_auditor(tmp_path: Path) -> None:
    out = render_default(tmp_path)
    audit = out / "k8s-instrumentation/injection-audit.py"
    audit.write_text("#!/usr/bin/env python3\nraise SystemExit(0)\n", encoding="utf-8")
    result = subprocess.run(
        ["bash", str(VALIDATE), "--output-dir", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "differs from the reviewed skill source" in combined(result)


def test_namespace_annotation_metadata_and_live_audit_cover_active_pods(
    tmp_path: Path,
) -> None:
    out = render_namespace_java_target(tmp_path)
    metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["targets"] == []
    assert metadata["namespace_targets"] == [
        {
            "target": "Namespace/apps",
            "namespace": "apps",
            "languages": ["java"],
            "annotations": {
                "instrumentation.opentelemetry.io/inject-java": (
                    "splunk-otel/splunk-otel-auto-instrumentation"
                )
            },
        }
    ]
    result = subprocess.run(
        [
            "bash",
            str(VALIDATE),
            "--output-dir",
            str(out),
            "--check-injection",
            "--allow-current-context",
        ],
        cwd=REPO_ROOT,
        env=namespace_injection_kubectl_env(tmp_path / "live", out),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, combined(result)
    assert "Namespace/apps: exact java namespace binding on 1 active pod(s)" in result.stdout
    assert "1 terminal/deleting pod(s) excluded" in result.stdout


def test_namespace_annotation_explicit_false_is_audited_opt_out(tmp_path: Path) -> None:
    out = render_namespace_java_target(tmp_path)
    accepted = subprocess.run(
        [
            "bash",
            str(VALIDATE),
            "--output-dir",
            str(out),
            "--check-injection",
            "--allow-current-context",
        ],
        cwd=REPO_ROOT,
        env=namespace_injection_kubectl_env(
            tmp_path / "accepted", out, explicit_opt_out=True
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert accepted.returncode == 0, combined(accepted)
    assert "1 explicit pod-language opt-out(s)" in accepted.stdout

    stale = subprocess.run(
        [
            "bash",
            str(VALIDATE),
            "--output-dir",
            str(out),
            "--check-injection",
            "--allow-current-context",
        ],
        cwd=REPO_ROOT,
        env=namespace_injection_kubectl_env(
            tmp_path / "stale", out, explicit_opt_out=True, stale_opt_out=True
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert stale.returncode != 0
    assert "retains disabled java injection artifacts" in combined(stale)


@pytest.mark.parametrize(
    ("fixture_kwargs", "expected"),
    [
        ({"empty_active": True}, "has no active pods"),
        ({"namespace_drift": True}, "managed annotations drifted"),
        ({"missing_injection": True}, "lacks exact java init container"),
        ({"pod_ready": False}, "is not Ready"),
    ],
)
def test_namespace_annotation_audit_fails_closed(
    tmp_path: Path,
    fixture_kwargs: dict[str, bool],
    expected: str,
) -> None:
    out = render_namespace_java_target(tmp_path)
    result = subprocess.run(
        [
            "bash",
            str(VALIDATE),
            "--output-dir",
            str(out),
            "--check-injection",
            "--allow-current-context",
        ],
        cwd=REPO_ROOT,
        env=namespace_injection_kubectl_env(tmp_path / expected.replace(" ", "-"), out, **fixture_kwargs),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert expected in combined(result)


def test_rendered_namespace_target_selection_and_list_use_deep_audit(tmp_path: Path) -> None:
    out = render_namespace_java_target(tmp_path)
    verify = run_rendered(
        out,
        "verify-injection.sh",
        "--target",
        "Namespace/apps",
        "--allow-current-context",
        env=namespace_injection_kubectl_env(tmp_path / "verify", out),
    )
    assert verify.returncode == 0, combined(verify)
    assert "Namespace/apps: exact java namespace binding" in verify.stdout

    listed = run_rendered(
        out,
        "list-instrumented.sh",
        "--allow-current-context",
        env=namespace_injection_kubectl_env(tmp_path / "list", out),
    )
    assert listed.returncode == 0, combined(listed)
    assert "Namespace/apps\tjava\tsplunk-otel/splunk-otel-auto-instrumentation" in listed.stdout


def test_rendered_list_instrumented_fails_on_injection_drift(tmp_path: Path) -> None:
    out = render_default(tmp_path)
    result = run_rendered(
        out,
        "list-instrumented.sh",
        "--allow-current-context",
        env=injection_kubectl_env(tmp_path / "drift", out, annotation_drift=True),
    )
    assert result.returncode != 0
    assert "managed pod-template annotations drifted" in combined(result)
    assert "TARGET\tLANGUAGE\tCR" not in result.stdout


def test_rendered_uninstall_restores_from_backup(tmp_path: Path) -> None:
    """Uninstall delegates to the reviewed fail-closed restore planner."""
    out = render_default(tmp_path)
    body = (out / "k8s-instrumentation/uninstall.sh").read_text(encoding="utf-8")
    helper = (out / "k8s-instrumentation/annotation-backup.py").read_text(encoding="utf-8")
    assert "--mode restore-plan" in body
    assert "corrupt or incomplete" in helper
    assert "key: prior[key] if key in prior else None" in helper
    assert "current_managed_values" in helper


def test_rendered_apply_annotations_uses_o_json_for_backup(tmp_path: Path) -> None:
    """Apply captures and verifies snapshots before emitting any workload patch."""
    out = render_default(tmp_path)
    body = (out / "k8s-instrumentation/apply-annotations.sh").read_text(encoding="utf-8")
    helper = (out / "k8s-instrumentation/annotation-backup.py").read_text(encoding="utf-8")
    # Reject the previous broken idiom outright.
    assert "${current:-{}}" not in body, "stale brace expansion still in script"
    assert body.index("--mode capture") < body.index("--type strategic")
    assert '"-o", "json"' in helper
    assert '["replace", "-f", "-"],' in helper
    assert "decode_snapshot" in helper


def test_transactional_backup_capture_and_restore_fail_closed(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        workload_annotations=[
            {
                "kind": "Deployment",
                "namespace": "apps",
                "name": "api",
                "language": "java",
                "container_names": "app",
            }
        ],
    )
    out = tmp_path / "rendered"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    state = tmp_path / "state"
    state.mkdir()
    workload = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "api", "namespace": "apps", "resourceVersion": "7"},
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "instrumentation.opentelemetry.io/container-names": "legacy-app",
                        "example.test/unrelated": "preserve-me",
                    }
                }
            }
        },
    }
    (state / "workload.json").write_text(json.dumps(workload), encoding="utf-8")
    kubectl = tmp_path / "kubectl"
    kubectl.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "state = pathlib.Path(os.environ['BACKUP_TEST_STATE'])\n"
        "args = sys.argv[1:]\n"
        "if 'get' in args and 'deployment' in args:\n"
        "    print((state / 'workload.json').read_text())\n"
        "elif 'get' in args and 'configmap' in args:\n"
        "    cm = state / 'configmap.json'\n"
        "    if cm.exists(): print(cm.read_text())\n"
        "elif ('create' in args or 'replace' in args) and '-f' in args:\n"
        "    obj = json.load(sys.stdin)\n"
        "    obj.setdefault('metadata', {})['resourceVersion'] = '2'\n"
        "    (state / 'configmap.json').write_text(json.dumps(obj))\n"
        "    print(json.dumps(obj))\n"
        "else:\n"
        "    raise SystemExit('unexpected kubectl argv: ' + repr(args))\n",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)
    env = os.environ.copy()
    env["BACKUP_TEST_STATE"] = str(state)
    helper = out / "k8s-instrumentation/annotation-backup.py"
    capture = subprocess.run(
        [
            sys.executable,
            str(helper),
            "--mode",
            "capture",
            "--metadata",
            str(out / "metadata.json"),
            "--target-all",
            "--kubectl-bin",
            str(kubectl),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert capture.returncode == 0, combined(capture)
    configmap = json.loads((state / "configmap.json").read_text(encoding="utf-8"))
    metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    key = metadata["targets"][0]["key"]
    snapshot = json.loads(configmap["data"][key])
    assert snapshot["values"] == {
        "instrumentation.opentelemetry.io/container-names": "legacy-app"
    }
    assert "example.test/unrelated" not in json.dumps(snapshot)

    restore = subprocess.run(
        [
            sys.executable,
            str(helper),
            "--mode",
            "restore-plan",
            "--metadata",
            str(out / "metadata.json"),
            "--target-all",
            "--kubectl-bin",
            str(kubectl),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert restore.returncode == 0, combined(restore)
    restore_patch = json.loads(restore.stdout)[0]["patch"]
    assert restore_patch["metadata"] == {"resourceVersion": "7"}
    annotations = restore_patch["spec"]["template"]["metadata"]["annotations"]
    assert annotations == {
        "instrumentation.opentelemetry.io/container-names": "legacy-app",
        "instrumentation.opentelemetry.io/inject-java": None,
    }
    assert "example.test/unrelated" not in annotations

    configmap["data"][key] = "not-json"
    (state / "configmap.json").write_text(json.dumps(configmap), encoding="utf-8")
    corrupt = subprocess.run(
        [
            sys.executable,
            str(helper),
            "--mode",
            "restore-plan",
            "--metadata",
            str(out / "metadata.json"),
            "--target-all",
            "--kubectl-bin",
            str(kubectl),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert corrupt.returncode != 0
    assert "invalid JSON" in combined(corrupt)

    (state / "configmap.json").unlink()
    (state / "workload.json").write_text("{broken", encoding="utf-8")
    invalid_workload = subprocess.run(
        [
            sys.executable,
            str(helper),
            "--mode",
            "capture",
            "--metadata",
            str(out / "metadata.json"),
            "--target-all",
            "--kubectl-bin",
            str(kubectl),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert invalid_workload.returncode != 0
    assert "invalid JSON" in combined(invalid_workload)
    assert not (state / "configmap.json").exists()


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
        "--deployment-environment",
        "dev",
        "--languages",
        "java,nodejs",
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


def test_setup_apply_reuses_existing_packet_without_example_or_identity_inputs(
    tmp_path: Path,
) -> None:
    out = render_default(tmp_path)
    before = (out / "metadata.json").read_text(encoding="utf-8")
    result = run_setup(
        "--apply-annotations",
        "--accept-auto-instrumentation",
        "--target",
        "Deployment/prod/payments-api",
        "--dry-run",
        "--output-dir",
        str(out),
    )
    assert result.returncode == 0, combined(result)
    assert "patch Deployment payments-api" in combined(result)
    assert (out / "metadata.json").read_text(encoding="utf-8") == before


def test_setup_apply_without_rendered_packet_fails_before_cluster_access(tmp_path: Path) -> None:
    out = tmp_path / "missing"
    result = run_setup(
        "--apply-instrumentation",
        "--dry-run",
        "--output-dir",
        str(out),
    )
    assert result.returncode != 0
    assert "No rendered packet exists" in combined(result)


def test_rendered_shell_interpolations_do_not_execute_command_substitution(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "must-not-exist"
    hostile = f"$(touch${{IFS}}{marker})"
    spec = write_spec(
        tmp_path / "spec.yaml",
        cluster_name=hostile,
        workload_annotations=[
            {
                "kind": "Deployment",
                "namespace": "apps",
                "name": "api",
                "language": "java",
            }
        ],
    )
    out = tmp_path / "rendered"
    rendered = run_render(
        "--spec",
        str(spec),
        "--output-dir",
        str(out),
        "--kube-context",
        hostile,
    )
    assert rendered.returncode == 0, combined(rendered)

    invocations = [
        ("apply-instrumentation.sh", ["--dry-run"]),
        (
            "apply-annotations.sh",
            ["--accept-auto-instrumentation", "--target-all", "--dry-run"],
        ),
        (
            "uninstall.sh",
            ["--accept-auto-instrumentation", "--target-all", "--dry-run"],
        ),
    ]
    for script, arguments in invocations:
        result = run_rendered(out, script, *arguments)
        assert result.returncode == 0, combined(result)
        assert not marker.exists(), f"{script} executed a rendered command substitution"
    handoff = subprocess.run(
        ["bash", str(out / "handoff-collector.sh")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert handoff.returncode == 0, combined(handoff)
    assert hostile in handoff.stdout
    assert not marker.exists(), "handoff-collector.sh executed a rendered command substitution"


def test_static_validation_rejects_deleted_workload_target_row(tmp_path: Path) -> None:
    out = render_default(tmp_path)
    metadata_path = out / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert len(metadata["targets"]) > 1
    metadata["targets"].pop()
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    result = subprocess.run(
        ["bash", str(VALIDATE), "--output-dir", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "targets do not exactly match workload-annotations.yaml" in combined(result)


def test_managed_resource_apply_preflights_all_foreign_names_before_mutation(
    tmp_path: Path,
) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        distribution="openshift",
        obi={
            "enabled": True,
            "image": TEST_OBI_IMAGE,
            "version": "",
            "render_openshift_scc": True,
        },
    )
    out = tmp_path / "rendered"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    manifest_paths = [
        out / "k8s-instrumentation/openshift-scc-obi.yaml",
        out / "k8s-instrumentation/instrumentation-cr.yaml",
        out / "k8s-instrumentation/obi-daemonset.yaml",
    ]
    lookup_names = {
        "SecurityContextConstraints": "securitycontextconstraints.security.openshift.io",
        "Instrumentation": "instrumentations.opentelemetry.io",
        "ServiceAccount": "serviceaccounts",
        "DaemonSet": "daemonsets.apps",
    }
    resources = {}
    for manifest in manifest_paths:
        for document in yaml.safe_load_all(manifest.read_text(encoding="utf-8")):
            if not document:
                continue
            live = json.loads(json.dumps(document))
            live["metadata"].update(
                {
                    "uid": f"uid-{document['kind'].lower()}",
                    "resourceVersion": "7",
                }
            )
            resources[lookup_names[document["kind"]]] = live
    resources["daemonsets.apps"]["metadata"]["labels"][
        "app.kubernetes.io/managed-by"
    ] = "foreign-controller"
    resources_path = tmp_path / "resources.json"
    resources_path.write_text(json.dumps(resources), encoding="utf-8")
    mutation_log = tmp_path / "mutations"
    kubectl = tmp_path / "kubectl"
    kubectl.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"resources = json.loads(pathlib.Path({str(resources_path)!r}).read_text())\n"
        f"mutation_log = pathlib.Path({str(mutation_log)!r})\n"
        "args = sys.argv[1:]\n"
        "if 'get' in args:\n"
        "    print(json.dumps(resources[args[args.index('get') + 1]]))\n"
        "elif any(action in args for action in ('create', 'replace', 'delete')):\n"
        "    mutation_log.write_text('mutation attempted')\n"
        "    raise SystemExit(3)\n"
        "else:\n"
        "    raise SystemExit(2)\n",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)
    command = [
        sys.executable,
        str(out / "k8s-instrumentation/managed-resource-lifecycle.py"),
        "--mode",
        "apply",
        "--kubectl-bin",
        str(kubectl),
    ]
    for manifest in manifest_paths:
        command.extend(["--manifest", str(manifest)])
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "ownership labels" in combined(result) or "ambiguous ownership" in combined(result)
    assert not mutation_log.exists(), "a resource mutated before all ownership checks passed"


def test_managed_resource_apply_rolls_back_earlier_create_after_late_race(
    tmp_path: Path,
) -> None:
    spec = write_spec(tmp_path / "spec.yaml")
    out = tmp_path / "rendered"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    labels = {
        "app.kubernetes.io/name": "splunk-otel-auto-instrumentation",
        "app.kubernetes.io/managed-by": (
            "splunk-observability-k8s-auto-instrumentation-setup"
        ),
    }
    service_account = {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {"name": "rollback-test", "namespace": "splunk-otel", "labels": labels},
    }
    instrumentation = {
        "apiVersion": "opentelemetry.io/v1alpha1",
        "kind": "Instrumentation",
        "metadata": {"name": "late-race", "namespace": "splunk-otel", "labels": labels},
        "spec": {},
    }
    first = tmp_path / "service-account.yaml"
    second = tmp_path / "instrumentation.yaml"
    first.write_text(yaml.safe_dump(service_account), encoding="utf-8")
    second.write_text(yaml.safe_dump(instrumentation), encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text("{}", encoding="utf-8")
    events = tmp_path / "events"
    kubectl = tmp_path / "kubectl"
    kubectl.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"state_path = pathlib.Path({str(state)!r})\n"
        f"events = pathlib.Path({str(events)!r})\n"
        "state = json.loads(state_path.read_text())\n"
        "args = sys.argv[1:]\n"
        "def key_for(resource, name): return resource + '/' + name\n"
        "def record(value):\n"
        "    with events.open('a') as handle: handle.write(value + '\\n')\n"
        "if 'get' in args:\n"
        "    index = args.index('get')\n"
        "    item = state.get(key_for(args[index + 1], args[index + 2]))\n"
        "    if item is not None: print(json.dumps(item))\n"
        "elif 'create' in args:\n"
        "    payload = json.load(sys.stdin)\n"
        "    kind = payload['kind']\n"
        "    if kind == 'Instrumentation':\n"
        "        record('race Instrumentation')\n"
        "        raise SystemExit(3)\n"
        "    payload['metadata'].update({'uid': 'service-account-uid', 'resourceVersion': '1'})\n"
        "    state[key_for('serviceaccounts', payload['metadata']['name'])] = payload\n"
        "    state_path.write_text(json.dumps(state))\n"
        "    record('create ServiceAccount')\n"
        "    print('{}')\n"
        "elif 'delete' in args and '--raw' in args:\n"
        "    options = json.load(sys.stdin)\n"
        "    assert options['preconditions'] == {'uid': 'service-account-uid', 'resourceVersion': '1'}\n"
        "    del state['serviceaccounts/rollback-test']\n"
        "    state_path.write_text(json.dumps(state))\n"
        "    record('delete ServiceAccount')\n"
        "    print('{}')\n"
        "else:\n"
        "    raise SystemExit(2)\n",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)
    result = subprocess.run(
        [
            sys.executable,
            str(out / "k8s-instrumentation/managed-resource-lifecycle.py"),
            "--mode",
            "apply",
            "--kubectl-bin",
            str(kubectl),
            "--manifest",
            str(first),
            "--manifest",
            str(second),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert json.loads(state.read_text()) == {}
    assert events.read_text().splitlines() == [
        "create ServiceAccount",
        "race Instrumentation",
        "delete ServiceAccount",
    ]


def test_managed_resource_replace_and_delete_use_uid_rv_preconditions(
    tmp_path: Path,
) -> None:
    spec = write_spec(tmp_path / "spec.yaml")
    out = tmp_path / "rendered"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    manifest = out / "k8s-instrumentation/instrumentation-cr.yaml"
    desired = next(document for document in yaml.safe_load_all(manifest.read_text()) if document)
    live = json.loads(json.dumps(desired))
    live["metadata"].update({"uid": "instrumentation-uid", "resourceVersion": "17"})
    state = tmp_path / "live.json"
    state.write_text(json.dumps(live), encoding="utf-8")
    calls = tmp_path / "calls.jsonl"
    kubectl = tmp_path / "kubectl"
    kubectl.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"state = pathlib.Path({str(state)!r})\n"
        f"calls = pathlib.Path({str(calls)!r})\n"
        "args = sys.argv[1:]\n"
        "if 'get' in args:\n"
        "    if state.exists(): print(state.read_text())\n"
        "elif 'replace' in args:\n"
        "    payload = json.load(sys.stdin)\n"
        "    assert payload['metadata']['uid'] == 'instrumentation-uid'\n"
        "    assert payload['metadata']['resourceVersion'] == '17'\n"
        "    state.write_text(json.dumps(payload))\n"
        "    with calls.open('a') as handle: handle.write(json.dumps({'replace': payload['metadata']}) + '\\n')\n"
        "    print('{}')\n"
        "elif 'delete' in args and '--raw' in args:\n"
        "    options = json.load(sys.stdin)\n"
        "    assert options['preconditions'] == {'uid': 'instrumentation-uid', 'resourceVersion': '17'}\n"
        "    state.unlink()\n"
        "    with calls.open('a') as handle: handle.write(json.dumps({'delete': args[args.index('--raw') + 1]}) + '\\n')\n"
        "    print('{}')\n"
        "else:\n"
        "    raise SystemExit(2)\n",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)
    base = [
        sys.executable,
        str(out / "k8s-instrumentation/managed-resource-lifecycle.py"),
        "--manifest",
        str(manifest),
        "--kubectl-bin",
        str(kubectl),
    ]
    applied = subprocess.run(
        [*base, "--mode", "apply"], capture_output=True, text=True, check=False
    )
    assert applied.returncode == 0, combined(applied)
    deleted = subprocess.run(
        [*base, "--mode", "delete"], capture_output=True, text=True, check=False
    )
    assert deleted.returncode == 0, combined(deleted)
    recorded = [json.loads(line) for line in calls.read_text().splitlines()]
    assert recorded[0]["replace"]["uid"] == "instrumentation-uid"
    assert recorded[1]["delete"].endswith(
        "/namespaces/splunk-otel/instrumentations/splunk-otel-auto-instrumentation"
    )


def test_backup_purge_requires_exact_target_all_key_coverage(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.yaml",
        workload_annotations=[
            {
                "kind": "Deployment",
                "namespace": "apps",
                "name": "api",
                "language": "java",
            }
        ],
    )
    out = tmp_path / "rendered"
    assert run_render("--spec", str(spec), "--output-dir", str(out)).returncode == 0
    metadata = json.loads((out / "metadata.json").read_text())
    row = metadata["targets"][0]
    snapshot = {
        "apiVersion": (
            "splunk-observability-k8s-auto-instrumentation-setup/"
            "annotation-snapshot/v1"
        ),
        "target": row["target"],
        "managedKeys": sorted(row["annotations"]),
        "values": {},
    }
    configmap = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": metadata["backup_configmap"],
            "namespace": metadata["namespace"],
            "uid": "backup-uid",
            "resourceVersion": "29",
            "labels": {
                "app.kubernetes.io/name": "splunk-otel-auto-instrumentation",
                "app.kubernetes.io/managed-by": (
                    "splunk-observability-k8s-auto-instrumentation-setup"
                ),
                "splunk.com/ttl": "7d",
            },
        },
        "data": {
            row["key"]: json.dumps(snapshot, separators=(",", ":")),
            "stale-unselected-snapshot": "{}",
        },
    }
    state = tmp_path / "configmap.json"
    state.write_text(json.dumps(configmap), encoding="utf-8")
    deletion = tmp_path / "deletion.json"
    kubectl = tmp_path / "kubectl"
    kubectl.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"state = pathlib.Path({str(state)!r})\n"
        f"deletion = pathlib.Path({str(deletion)!r})\n"
        "args = sys.argv[1:]\n"
        "if 'get' in args:\n"
        "    if state.exists(): print(state.read_text())\n"
        "elif 'delete' in args and '--raw' in args:\n"
        "    options = json.load(sys.stdin)\n"
        "    deletion.write_text(json.dumps(options))\n"
        "    state.unlink()\n"
        "    print('{}')\n"
        "else:\n"
        "    raise SystemExit(2)\n",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)
    helper = out / "k8s-instrumentation/annotation-backup.py"
    base = [
        sys.executable,
        str(helper),
        "--mode",
        "purge",
        "--metadata",
        str(out / "metadata.json"),
        "--kubectl-bin",
        str(kubectl),
    ]
    partial = subprocess.run(
        [*base, "--target", row["target"]], capture_output=True, text=True, check=False
    )
    assert partial.returncode != 0
    assert "requires --target-all" in combined(partial)
    stale = subprocess.run(
        [*base, "--target-all"], capture_output=True, text=True, check=False
    )
    assert stale.returncode != 0
    assert "key coverage differs" in combined(stale)
    assert state.exists() and not deletion.exists()

    configmap["data"].pop("stale-unselected-snapshot")
    state.write_text(json.dumps(configmap), encoding="utf-8")
    exact = subprocess.run(
        [*base, "--target-all"], capture_output=True, text=True, check=False
    )
    assert exact.returncode == 0, combined(exact)
    options = json.loads(deletion.read_text())
    assert options["preconditions"] == {"uid": "backup-uid", "resourceVersion": "29"}
