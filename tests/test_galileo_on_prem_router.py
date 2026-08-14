"""Security and coverage regressions for the Galileo On-Prem parent router."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "skills/galileo-on-prem-kubernetes-setup"
SETUP = SKILL / "scripts/setup.sh"
VALIDATE = SKILL / "scripts/validate.sh"
MATRIX = SKILL / "references/deployment-feature-matrix.json"
CONSOLE_URL = "https://console.demo-v2.galileocloud.io/"
RUNTIME_CATEGORIES = {
    "dependency": "stack.base",
    "schema_or_enable_flag": "install.values.questionnaire",
    "image": "stack.api",
    "crd": "crd.helm-directory",
    "hook_or_migration": "data.postgresql-migrations",
    "cluster_scoped_object": "galileoctl.rbac",
    "api_kind": "stack.data-service",
    "service_or_route": "routing.ingress-resources",
    "persistence": "data.clickhouse",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_private(path: Path, value: str | bytes) -> Path:
    if isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_bytes(value)
    path.chmod(0o600)
    return path


def run(
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        list(args),
        cwd=REPO_ROOT,
        env=process_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )


def matrix_owners() -> dict[str, list[str]]:
    payload = json.loads(MATRIX.read_text(encoding="utf-8"))
    return {row["id"]: row["owners"] for row in payload["features"]}


def build_fixture(
    root: Path,
    *,
    runtime: bool = True,
    secret_mode: int = 0o600,
) -> tuple[Path, Path, str]:
    inputs = root / "inputs"
    secrets = root / "secrets"
    inputs.mkdir(mode=0o700)
    secrets.mkdir(mode=0o700)

    stack = write_private(inputs / "galileo-stack-1.0.0.tgz", b"fixture-stack")
    galileoctl = write_private(inputs / "galileoctl-1.0.0.tgz", b"fixture-galileoctl")
    values = write_private(inputs / "values-fixture-umbrella.yaml", "global:\n  customer_name: fixture\n")
    sentinel = "GALILEO_ROUTER_SECRET_SENTINEL_8b5fd70d"
    secret_values = write_private(secrets / "secret-values.yaml", f"password: {sentinel}\n")
    repository = write_private(secrets / "repository-credentials", f"token={sentinel}\n")
    secret_values.chmod(secret_mode)

    owners = matrix_owners()
    runtime_path = inputs / "runtime-inventory.json"
    runtime_payload = {
        "schema_version": 1,
        "chart_sha256": sha256(stack),
        "generated_by": "galileo-on-prem-stack-setup",
        "observed_categories": sorted(RUNTIME_CATEGORIES),
        "observed_empty_categories": {},
        "items": [
            {
                "id": f"fixture.{category.replace('_', '-')}",
                "category": category,
                "classification_id": feature_id,
                "owners": owners[feature_id],
                "source_ref": f"fixture/{category}",
            }
            for category, feature_id in sorted(RUNTIME_CATEGORIES.items())
        ],
    }
    write_private(runtime_path, json.dumps(runtime_payload, indent=2, sort_keys=True) + "\n")

    spec: dict[str, Any] = {
        "api_version": "galileo.ai/on-prem-deployment/v1",
        "kind": "GalileoOnPremDeploymentPlan",
        "metadata": {
            "deployment_id": "router-fixture",
            "environment": "lab",
            "profile": "connected-cpu",
            "owner": "platform-engineering",
            "change_ticket": "LAB-ROUTER-1",
        },
        "galileo": {
            "console_url": CONSOLE_URL,
            "api_url": "https://api.demo-v2.galileocloud.io/",
            "domain": "demo-v2.galileocloud.io",
        },
        "target": {
            "kube_context": "fixture-context",
            "api_server": "https://192.0.2.10:16443/",
            "ca_sha256": "1" * 64,
            "kube_system_uid": "fixture-kube-system-uid",
            "namespace": "galileo",
            "namespace_uid": "",
            "distribution": "microk8s",
            "kubernetes_version": "1.31.14",
        },
        "artifacts": {
            "galileo_stack_chart": str(stack),
            "galileo_stack_sha256": sha256(stack),
            "galileoctl_chart": str(galileoctl),
            "galileoctl_sha256": sha256(galileoctl),
            "agent_control_chart": "",
            "agent_control_sha256": "",
            "agent_control_ownership_evidence": "",
            "luna_studio_chart": "",
            "luna_studio_sha256": "",
            "luna_studio_ownership_evidence": "",
            "questionnaire_values_file": str(values),
            "secret_values_file": str(secret_values),
            "repository_credentials_file": str(repository),
            "image_manifest": "",
            "model_bundle": "",
            "stack_runtime_inventory": str(runtime_path) if runtime else "",
        },
        "installation": {
            "method": "helm-cli",
            "stack_release": "galileo",
            "galileoctl_release": "galileoctl",
            "timeout": "120m",
            "namespace_create": True,
            "shared_cluster": False,
            "crd_ownership": "dedicated",
            "child_ownership": {"agent_control": "disabled", "luna_studio": "disabled"},
        },
        "routing": {
            "mode": "ingress",
            "tls_mode": "customer-certificate",
            "certificate_secret": "galileo-tls",
            "ingress_class": "nginx",
            "gateway_class": "",
            "load_balancer_address": "192.0.2.200",
            "public_hosts": {
                "console": "console.demo-v2.galileocloud.io",
                "api": "api.demo-v2.galileocloud.io",
                "galileoctl": "",
                "agent_control": "",
                "luna_studio": "",
            },
        },
        "node_pools": {
            "core": {"minimum_nodes": 3, "labels": ["galileo-node-type=galileo-core"], "taints": []},
            "runner": {"minimum_nodes": 1, "labels": ["galileo-node-type=galileo-runner"], "taints": []},
            "ml": {"minimum_nodes": 0, "labels": ["galileo-node-type=galileo-ml"], "taints": []},
        },
        "storage": {
            "default_class": "fixture-retain",
            "require_explicit_class": True,
            "data_class": "fixture-retain",
            "object_store_class": "fixture-retain",
            "snapshot_class": "fixture-snapshots",
            "reclaim_policy": "Retain",
        },
        "data_services": {
            "postgres": {"mode": "external", "version": "16", "ha": True, "backup_evidence": "backup/postgres/fixture"},
            "redis": {"mode": "external", "version": "7", "ha": True, "cluster_mode": False},
            "object_storage": {
                "provider": "s3-compatible",
                "mode": "external",
                "backup_evidence": "backup/object/fixture",
                "support_exception": "",
            },
            "clickhouse": {"backup_evidence": "backup/clickhouse/fixture"},
            "rabbitmq": {"queue_purge_allowed": False},
        },
        "monitoring": {"prometheus": True, "grafana": True, "fluent_bit": True, "alerts": True, "owner": "platform-engineering"},
        "features": {
            "wizard": {"enabled": False, "gpu_enabled": False, "offline_models": False},
            "agent_control": {"enabled": False, "topology": "disabled"},
            "luna_studio": {"enabled": False, "topology": "disabled", "training_mode": "disabled"},
            "platform_postdeploy": {"enabled": True},
            "mcp": {"enabled": False},
            "lemonade": {"enabled": False},
        },
        "identity": {"sso_mode": "oidc", "first_admin_owner": "platform-admin@example.invalid", "break_glass_documented": True},
        "email": {"mode": "smtp", "sender": "galileo@example.invalid", "test_requires_approval": True},
        "air_gap": {"enabled": False, "registry": "", "no_egress": False, "architectures": ["amd64"]},
        "operations": {"backups_verified": True, "restore_drill": True, "rollback_approved": False, "soak_days": 0, "production_gate": False},
        "approvals": {"cse_values_approved": False, "cse_ticket": "", "cluster_change_approved": False, "exceptions": []},
    }
    spec_path = write_private(inputs / "deployment.json", json.dumps(spec, indent=2, sort_keys=True) + "\n")
    return spec_path, root / "rendered", sentinel


def render_complete(root: Path) -> tuple[Path, subprocess.CompletedProcess[str], str]:
    spec, output, sentinel = build_fixture(root)
    result = run(
        "bash",
        str(SETUP),
        "--coverage",
        "--validate",
        "--spec",
        str(spec),
        "--galileo-console-url",
        CONSOLE_URL,
        "--output-dir",
        str(output),
        "--json",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    return Path(payload["bundle_dir"]), result, sentinel


def rewrite_manifest_rows(bundle: Path, names: set[str]) -> None:
    manifest_path = bundle / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_name = {row["path"]: row for row in manifest["files"]}
    for name in names:
        target = bundle / name
        by_name[name]["sha256"] = sha256(target)
        by_name[name]["size"] = target.stat().st_size
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_path.chmod(0o600)


def test_help_and_mutation_options_are_fail_closed(tmp_path: Path) -> None:
    help_result = run("bash", str(SETUP), "--help")
    assert help_result.returncode == 0
    assert "--galileo-console-url" in help_result.stdout
    assert "never calls Kubernetes" in help_result.stdout

    output = tmp_path / "must-not-exist"
    mutation = run("bash", str(SETUP), "--apply", "--output-dir", str(output))
    assert mutation.returncode != 0
    assert not output.exists()


def test_galileoctl_method_a_interfaces_render_source_backed_handoffs(
    tmp_path: Path,
) -> None:
    spec, output, _ = build_fixture(tmp_path)
    payload = json.loads(spec.read_text(encoding="utf-8"))
    payload["installation"]["method"] = "galileoctl"
    spec.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    spec.chmod(0o600)

    result = run(
        "bash",
        str(SETUP),
        "--render",
        "--spec",
        str(spec),
        "--galileo-console-url",
        CONSOLE_URL,
        "--output-dir",
        str(output),
        "--json",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    bundle = Path(json.loads(result.stdout)["bundle_dir"])
    plan = json.loads((bundle / "orchestration-plan.json").read_text(encoding="utf-8"))
    stack = next(row for row in plan["nodes"] if row["id"] == "stack")
    assert stack["installation_method"] == "galileoctl"
    assert "Method A" in stack["requested_action"]
    assert "dry run" in stack["requested_action"]


def test_unknown_installation_method_is_rejected_before_output(tmp_path: Path) -> None:
    spec, output, _ = build_fixture(tmp_path)
    payload = json.loads(spec.read_text(encoding="utf-8"))
    payload["installation"]["method"] = "galileoctl-latest-no-preflight"
    spec.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    spec.chmod(0o600)

    result = run(
        "bash",
        str(SETUP),
        "--render",
        "--spec",
        str(spec),
        "--galileo-console-url",
        CONSOLE_URL,
        "--output-dir",
        str(output),
    )
    assert result.returncode != 0
    assert "installation.method" in result.stdout + result.stderr
    assert not output.exists()


def test_core_azure_blob_requires_written_support_decision(tmp_path: Path) -> None:
    spec, output, _ = build_fixture(tmp_path)
    payload = json.loads(spec.read_text(encoding="utf-8"))
    payload["data_services"]["object_storage"]["provider"] = "azure-blob"
    spec.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    spec.chmod(0o600)

    blocked = run(
        "bash",
        str(SETUP),
        "--render",
        "--spec",
        str(spec),
        "--galileo-console-url",
        CONSOLE_URL,
        "--output-dir",
        str(output),
    )
    assert blocked.returncode != 0
    assert "Azure Blob" in blocked.stdout + blocked.stderr
    assert not output.exists()

    payload["data_services"]["object_storage"]["support_exception"] = (
        "GALILEO-CASE-123: exact chart version supports core Azure Blob"
    )
    spec.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    allowed = run(
        "bash",
        str(SETUP),
        "--render",
        "--spec",
        str(spec),
        "--galileo-console-url",
        CONSOLE_URL,
        "--output-dir",
        str(output),
    )
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr


@pytest.mark.parametrize(
    ("provider", "mode"),
    [("minio", "external"), ("aws-s3", "bundled"), ("gcs", "bundled")],
)
def test_object_storage_provider_and_ownership_mode_cannot_conflict(
    tmp_path: Path, provider: str, mode: str
) -> None:
    spec, output, _ = build_fixture(tmp_path)
    payload = json.loads(spec.read_text(encoding="utf-8"))
    payload["data_services"]["object_storage"].update(
        {"provider": provider, "mode": mode}
    )
    spec.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    spec.chmod(0o600)
    result = run(
        "bash",
        str(SETUP),
        "--render",
        "--spec",
        str(spec),
        "--galileo-console-url",
        CONSOLE_URL,
        "--output-dir",
        str(output),
    )
    assert result.returncode != 0
    assert "object_storage" in result.stdout + result.stderr
    assert not output.exists()


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("helm-cli", "immutable Stack bundle"),
        ("deployment-script", "hashed vendor script"),
        ("step-by-step", "ordered-chart operator handoff"),
    ],
)
def test_other_official_installation_methods_have_exact_ownership_handoffs(
    tmp_path: Path, method: str, expected: str
) -> None:
    spec, output, _ = build_fixture(tmp_path)
    payload = json.loads(spec.read_text(encoding="utf-8"))
    payload["installation"]["method"] = method
    spec.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    spec.chmod(0o600)

    result = run(
        "bash",
        str(SETUP),
        "--render",
        "--spec",
        str(spec),
        "--galileo-console-url",
        CONSOLE_URL,
        "--output-dir",
        str(output),
        "--json",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    bundle = Path(json.loads(result.stdout)["bundle_dir"])
    plan = json.loads((bundle / "orchestration-plan.json").read_text(encoding="utf-8"))
    stack = next(row for row in plan["nodes"] if row["id"] == "stack")
    assert stack["installation_method"] == method
    assert expected in stack["requested_action"]


def test_complete_runtime_inventory_renders_deterministically_and_without_secrets(tmp_path: Path) -> None:
    bundle, first, sentinel = render_complete(tmp_path)
    second = run(
        "bash",
        str(SETUP),
        "--coverage",
        "--spec",
        str(tmp_path / "inputs/deployment.json"),
        "--galileo-console-url",
        CONSOLE_URL,
        "--output-dir",
        str(tmp_path / "rendered"),
        "--json",
    )
    assert second.returncode == 0, second.stdout + second.stderr
    assert json.loads(first.stdout)["bundle_id"] == json.loads(second.stdout)["bundle_id"]
    assert json.loads(first.stdout)["bundle_dir"] == json.loads(second.stdout)["bundle_dir"]

    validation = run("bash", str(VALIDATE), "--output-dir", str(bundle), "--json")
    assert validation.returncode == 0, validation.stdout + validation.stderr
    coverage = json.loads((bundle / "coverage-report.json").read_text(encoding="utf-8"))
    for key in ("uncovered", "unowned", "duplicate_mutation_owners", "unclassified_runtime_inventory"):
        assert coverage[key] == []
    combined = first.stdout + first.stderr + second.stdout + second.stderr
    assert sentinel not in combined
    for path in bundle.rglob("*"):
        if path.is_file():
            assert sentinel.encode() not in path.read_bytes(), path


def test_parent_never_invokes_external_deployment_or_network_tools(tmp_path: Path) -> None:
    spec, output, _ = build_fixture(tmp_path)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir(mode=0o700)
    marker = tmp_path / "external-command-was-called"
    for name in ("helm", "kubectl", "ssh", "curl"):
        executable = fake_bin / name
        executable.write_text(
            f"#!/usr/bin/env bash\nprintf '%s\\n' {name} >> {marker!s}\nexit 97\n",
            encoding="utf-8",
        )
        executable.chmod(0o700)
    result = run(
        "bash",
        str(SETUP),
        "--render",
        "--spec",
        str(spec),
        "--galileo-console-url",
        CONSOLE_URL,
        "--output-dir",
        str(output),
        env={"PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not marker.exists()


def test_missing_or_mismatched_runtime_inventory_blocks_coverage(tmp_path: Path) -> None:
    missing_root = tmp_path / "missing"
    missing_root.mkdir(mode=0o700)
    spec, output, _ = build_fixture(missing_root, runtime=False)
    missing = run(
        "bash", str(SETUP), "--coverage", "--spec", str(spec),
        "--galileo-console-url", CONSOLE_URL, "--output-dir", str(output), "--json",
    )
    assert missing.returncode == 2, missing.stdout + missing.stderr
    assert "runtime.inventory.pending" in missing.stdout

    mismatch_root = tmp_path / "mismatch"
    mismatch_root.mkdir(mode=0o700)
    spec, output, _ = build_fixture(mismatch_root)
    runtime_path = mismatch_root / "inputs/runtime-inventory.json"
    runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime_payload["chart_sha256"] = "f" * 64
    runtime_path.write_text(json.dumps(runtime_payload), encoding="utf-8")
    runtime_path.chmod(0o600)
    mismatch = run(
        "bash", str(SETUP), "--coverage", "--spec", str(spec),
        "--galileo-console-url", CONSOLE_URL, "--output-dir", str(output), "--json",
    )
    assert mismatch.returncode == 2, mismatch.stdout + mismatch.stderr
    assert "runtime.inventory.chart-digest-mismatch" in mismatch.stdout


@pytest.mark.parametrize("unsafe", ["mode", "symlink", "hardlink", "fifo"])
def test_unsafe_secret_files_are_reported_as_blocking_gaps(tmp_path: Path, unsafe: str) -> None:
    root = tmp_path / unsafe
    root.mkdir(mode=0o700)
    spec, output, _ = build_fixture(root)
    spec_payload = json.loads(spec.read_text(encoding="utf-8"))
    secret = Path(spec_payload["artifacts"]["secret_values_file"])
    if unsafe == "mode":
        secret.chmod(0o644)
    elif unsafe == "symlink":
        target = root / "secrets/real-secret"
        secret.rename(target)
        secret.symlink_to(target)
    elif unsafe == "hardlink":
        os.link(secret, root / "secrets/second-link")
    else:
        secret.unlink()
        os.mkfifo(secret, 0o600)
    result = run(
        "bash", str(SETUP), "--doctor", "--spec", str(spec),
        "--galileo-console-url", CONSOLE_URL, "--output-dir", str(output), "--json",
    )
    assert result.returncode == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    gaps = json.loads((Path(payload["bundle_dir"]) / "gap-register.json").read_text(encoding="utf-8"))["gaps"]
    assert any(row["key"] == "secret-path.secret_values_file" for row in gaps)


def test_bundle_rejects_extra_file_mode_and_content_drift(tmp_path: Path) -> None:
    extra_root = tmp_path / "extra"
    extra_root.mkdir(mode=0o700)
    bundle, _, _ = render_complete(extra_root)
    write_private(bundle / "untracked", "unexpected\n")
    extra = run("bash", str(VALIDATE), "--output-dir", str(bundle))
    assert extra.returncode != 0
    assert "extra" in (extra.stdout + extra.stderr).lower()

    mode_root = tmp_path / "mode"
    mode_root.mkdir(mode=0o700)
    bundle, _, _ = render_complete(mode_root)
    (bundle / "status.json").chmod(0o644)
    mode = run("bash", str(VALIDATE), "--output-dir", str(bundle))
    assert mode.returncode != 0
    assert "mode" in (mode.stdout + mode.stderr).lower()

    drift_root = tmp_path / "drift"
    drift_root.mkdir(mode=0o700)
    bundle, _, _ = render_complete(drift_root)
    with (bundle / "status.json").open("ab") as handle:
        handle.write(b" ")
    drift = run("bash", str(VALIDATE), "--output-dir", str(bundle))
    assert drift.returncode != 0
    assert "drift" in (drift.stdout + drift.stderr).lower()


def test_consistently_rehashed_forged_coverage_is_recomputed_and_rejected(tmp_path: Path) -> None:
    bundle, _, _ = render_complete(tmp_path)
    coverage_path = bundle / "coverage-report.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["unclassified_runtime_inventory"] = []
    coverage["coverage_complete"] = True
    coverage_path.write_text(json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    coverage_path.chmod(0o600)

    runtime_path = bundle / "runtime-inventory.normalized.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["items"][0]["classification_id"] = "not-a-reviewed-feature"
    runtime["status"] = "classified"
    runtime_path.write_text(json.dumps(runtime, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    runtime_path.chmod(0o600)

    # Update the untrusted manifest too. Validation must still derive the result
    # from the checked-in matrix and normalized runtime inventory.
    rewrite_manifest_rows(bundle, {"coverage-report.json", "runtime-inventory.normalized.json"})
    result = run("bash", str(VALIDATE), "--output-dir", str(bundle))
    assert result.returncode != 0
    assert any(
        word in (result.stdout + result.stderr).lower()
        for word in ("coverage", "runtime", "identity", "classification")
    )


def test_rehashed_forged_gaps_state_and_doctor_are_recomputed_and_rejected(tmp_path: Path) -> None:
    spec, output, _ = build_fixture(tmp_path)
    spec_payload = json.loads(spec.read_text(encoding="utf-8"))
    spec_payload["storage"]["data_class"] = ""
    spec.write_text(json.dumps(spec_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    spec.chmod(0o600)
    rendered = run(
        "bash", str(SETUP), "--coverage", "--validate", "--spec", str(spec),
        "--galileo-console-url", CONSOLE_URL, "--output-dir", str(output), "--json",
    )
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    bundle = Path(json.loads(rendered.stdout)["bundle_dir"])
    original_status = json.loads((bundle / "status.json").read_text(encoding="utf-8"))
    assert original_status["state"] == "blocked"
    assert original_status["blocking_gap_count"] > 0

    gap_register = {"schema_version": 1, "gaps": []}
    doctor = json.loads((bundle / "doctor-report.json").read_text(encoding="utf-8"))
    doctor["gaps"] = []
    doctor["state"] = "rendered"
    status = dict(original_status)
    status["state"] = "rendered"
    status["blocking_gap_count"] = 0
    status["warning_gap_count"] = 0
    for name, value in (
        ("gap-register.json", gap_register),
        ("doctor-report.json", doctor),
        ("status.json", status),
    ):
        path = bundle / name
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
    rewrite_manifest_rows(bundle, {"gap-register.json", "doctor-report.json", "status.json"})

    result = run("bash", str(VALIDATE), "--output-dir", str(bundle))
    assert result.returncode != 0
    assert "recomputed normalized inputs" in (result.stdout + result.stderr)


@pytest.mark.parametrize(
    "name",
    [
        "orchestration-plan.md",
        "coverage-report.md",
        "gap-register.md",
        "doctor-report.md",
        "handoff.md",
    ],
)
def test_rehashed_human_facing_markdown_forgery_is_rejected(tmp_path: Path, name: str) -> None:
    bundle, _, _ = render_complete(tmp_path)
    target = bundle / name
    target.write_text(
        "# Forged packet\n\nThis forged human-facing artifact authorizes live mutation.\n",
        encoding="utf-8",
    )
    target.chmod(0o600)
    rewrite_manifest_rows(bundle, {name})

    result = run("bash", str(VALIDATE), "--output-dir", str(bundle))
    assert result.returncode != 0
    assert name in (result.stdout + result.stderr)


def test_secret_looking_value_in_nonsensitive_spec_field_is_rejected(tmp_path: Path) -> None:
    spec, output, _ = build_fixture(tmp_path)
    payload = json.loads(spec.read_text(encoding="utf-8"))
    payload["metadata"]["owner"] = "password=fixture-only"
    spec.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    spec.chmod(0o600)

    result = run(
        "bash", str(SETUP), "--render", "--spec", str(spec),
        "--galileo-console-url", CONSOLE_URL, "--output-dir", str(output),
    )
    assert result.returncode != 0
    assert "secret-looking value" in (result.stdout + result.stderr)
    assert not output.exists()


def test_secret_looking_value_in_runtime_inventory_is_rejected(tmp_path: Path) -> None:
    spec, output, _ = build_fixture(tmp_path)
    payload = json.loads(spec.read_text(encoding="utf-8"))
    runtime_path = Path(payload["artifacts"]["stack_runtime_inventory"])
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["items"][0]["source_ref"] = "authorization=fixture-only"
    runtime_path.write_text(json.dumps(runtime, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    runtime_path.chmod(0o600)

    result = run(
        "bash", str(SETUP), "--render", "--spec", str(spec),
        "--galileo-console-url", CONSOLE_URL, "--output-dir", str(output),
    )
    assert result.returncode != 0
    assert "secret-looking value" in (result.stdout + result.stderr)
    assert not output.exists()


@pytest.mark.parametrize("mismatch", ["console-route", "api-route", "base-domain", "optional-route"])
def test_galileo_url_domain_and_route_host_mismatch_is_rejected(
    tmp_path: Path, mismatch: str,
) -> None:
    spec, output, _ = build_fixture(tmp_path)
    payload = json.loads(spec.read_text(encoding="utf-8"))
    if mismatch == "console-route":
        payload["routing"]["public_hosts"]["console"] = "other.demo-v2.galileocloud.io"
    elif mismatch == "api-route":
        payload["routing"]["public_hosts"]["api"] = "other.demo-v2.galileocloud.io"
    elif mismatch == "base-domain":
        payload["galileo"]["domain"] = "unrelated.example.invalid"
    else:
        payload["routing"]["public_hosts"]["galileoctl"] = "galileoctl.unrelated.example.invalid"
    spec.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    spec.chmod(0o600)

    result = run(
        "bash", str(SETUP), "--render", "--spec", str(spec),
        "--galileo-console-url", CONSOLE_URL, "--output-dir", str(output),
    )
    assert result.returncode != 0
    message = result.stdout + result.stderr
    assert "hostname" in message or "subdomain" in message
    assert not output.exists()


def test_normalized_bundle_binds_configured_artifact_paths_absolutely(tmp_path: Path) -> None:
    bundle, _, _ = render_complete(tmp_path)
    payload = json.loads((bundle / "deployment-spec.normalized.json").read_text(encoding="utf-8"))
    for key, value in payload["artifacts"].items():
        if key.endswith("_sha256") or not value:
            continue
        assert Path(value).is_absolute(), key


def test_matrix_has_stable_complete_contract_rows() -> None:
    payload = json.loads(MATRIX.read_text(encoding="utf-8"))
    assert payload["feature_count"] == len(payload["features"]) == 110
    ids = [row["id"] for row in payload["features"]]
    assert len(ids) == len(set(ids))
    for row in payload["features"]:
        assert row["owners"]
        assert row["automation_boundary"].strip()
        assert row["validation_evidence"].strip()
        assert row["source_urls"]
        assert all(url.startswith("https://helm.galileo.ai/") for url in row["source_urls"])
    official = payload["official_source_inventory"]
    assert len(official) == 32
    official_urls = {source["url"] for source in official}
    assert len(official_urls) == len(official)
    assert official_urls == {
        url for row in payload["features"] for url in row["source_urls"]
    }
    ledger = (
        REPO_ROOT
        / "skills"
        / "galileo-on-prem-kubernetes-setup"
        / "references"
        / "source-ledger.md"
    ).read_text(encoding="utf-8")
    assert all(url in ledger for url in official_urls)
    by_id = {row["id"]: row for row in payload["features"]}
    cli_boundary = by_id["galileoctl.interface.cli"]["automation_boundary"]
    assert "required first-install UI" in cli_boundary
