"""Critical offline lifecycle regressions for the Galileo On-Prem Stack skill."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import importlib.util
import inspect
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "skills" / "galileo-on-prem-stack-setup"
ENGINE = SKILL / "scripts" / "stack_lifecycle.py"
SPEC = importlib.util.spec_from_file_location("test_galileo_stack_lifecycle", ENGINE)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_complete_offline_security_regression_suite() -> None:
    """Includes semantic bundle forgery, secret, downgrade, route, and PVC gates."""
    result = subprocess.run(
        ["bash", str(SKILL / "scripts" / "validate.sh"), "--self-test"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_quoted_crd_and_gpu_static_profile_fail_closed() -> None:
    documents = MODULE.rendered_documents(
        b'apiVersion: apiextensions.k8s.io/v1\nkind: "CustomResourceDefinition"\nmetadata:\n  name: widgets.example.com\n',
        "quoted CRD",
    )
    assert any(document.get("kind") == "CustomResourceDefinition" for document in documents)

    gpu_workload = [{
        "kind": "Deployment",
        "metadata": {"name": "wizard"},
        "spec": {"template": {"spec": {"containers": [{
            "name": "wizard",
            "resources": {"requests": {"nvidia.com/gpu": "1"}, "limits": {"nvidia.com/gpu": "1"}},
        }]}}},
    }]
    with pytest.raises(MODULE.ContractError, match="CPU-only"):
        MODULE.validate_gpu_rendering(gpu_workload, {"gpu_enabled": False}, [])


def test_action_status_and_uninstall_are_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    assert MODULE.release_observation_state([{"status": "deployed"}], False, None) == "unverified-observed"
    assert MODULE.release_observation_state([], False, None) == "absent-observed"
    assert MODULE.release_observation_state([{"status": "pending-upgrade"}], False, None) == "unverified-degraded-observed"
    assert MODULE.release_observation_state([{"status": "deployed"}], True, {"status": "failed"}) == "unverified-degraded-observed"
    with pytest.raises(MODULE.ContractError, match="strictly newer"):
        MODULE.assert_upgrade_direction("9.0.0", "1.2.3")

    manifest = {"bundle_sha256": "a" * 64}
    spec = {"stack": {"release_name": "galileo"}, "target": {"namespace": "galileo"}}
    monkeypatch.setattr(MODULE, "verify_bundle", lambda _path: (manifest, spec))
    monkeypatch.setattr(MODULE, "load_exact_plan", lambda *_args: {"execution": "manual-handoff-only"})
    with pytest.raises(MODULE.ContractError, match="automated uninstall is disabled"):
        MODULE.uninstall(argparse.Namespace(bundle="/fixture"))

    handoff_plan = MODULE.canonical_apply_plan(
        {
            "deployment_id": "fixture", "environment": "production", "installation_method": "galileoctl",
            "crds": {"mode": "shared"}, "stack": {"release_name": "galileo"},
            "target": {"namespace": "galileo"},
            "routing": {"load_balancer_lifecycle": "external-preinstalled"},
        },
        "f" * 64,
    )
    assert handoff_plan["method"] == "galileoctl"
    assert handoff_plan["automated_by_this_skill"] is False
    assert "UI for first install" in handoff_plan["operator_handoff"]
    assert "handoff" in handoff_plan["next_action"]
    staged_plan = MODULE.canonical_apply_plan(
        {
            "deployment_id": "fixture", "environment": "production", "installation_method": "helm-cli",
            "crds": {"mode": "shared"}, "stack": {"release_name": "galileo"},
            "target": {"namespace": "galileo"},
            "routing": {"load_balancer_lifecycle": "release-managed-staged-handoff"},
        },
        "f" * 64,
    )
    assert staged_plan["automated_by_this_skill"] is False
    assert staged_plan["candidate_for_automation"] is False
    assert "LoadBalancer" in staged_plan["operator_handoff"]


def test_all_mutation_entrypoints_reject_before_io_or_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    touched = False

    def forbidden(*_args: object, **_kwargs: object) -> object:
        nonlocal touched
        touched = True
        raise AssertionError("mutation sentinel performed I/O or subprocess work")

    for name in (
        "verify_bundle", "secure_read", "safe_input_file", "resolve_executable",
        "run_checked", "write_private", "ensure_private_directory",
    ):
        monkeypatch.setattr(MODULE, name, forbidden)
    monkeypatch.chdir(tmp_path)
    before = sorted(tmp_path.rglob("*"))
    for flag in (
        "--apply-install", "--apply-upgrade", "--apply-rollback",
        "--apply-uninstall", "--apply-lab-bootstrap",
    ):
        assert MODULE.main([
            flag,
            "--galileo-console-url",
            "https://console.demo-v2.galileocloud.io/",
        ]) == 2
        assert touched is False
        assert sorted(tmp_path.rglob("*")) == before


def test_strict_yaml_rejects_duplicate_alias_merge_and_nested_duplicates() -> None:
    for document in (
        "release: one\nrelease: two\n",
        "target:\n  namespace: one\n  namespace: two\n",
        "base: &base\n  enabled: true\ncopy: *base\n",
        "base: &base\n  enabled: true\ncopy:\n  <<: *base\n",
    ):
        with pytest.raises(yaml.YAMLError):
            MODULE.strict_yaml_load(document)


def test_helm_context_and_nondeterminism_scanner_is_closed() -> None:
    assert MODULE.unbound_helm_action_reason(" .Release.Name ") == ""
    assert MODULE.unbound_helm_action_reason(" .Release.Namespace ") == ""
    for action in (
        ".Release.IsInstall",
        ".Release.Revision",
        "$release := .Release",
        "$root := .",
        'index .Release "IsUpgrade"',
        'index .Capabilities "APIVersions"',
        'dig "Release" "Revision" 0 $root',
        "randInt 1 10",
        "derivePassword 1 long seed user site",
        'shuffle (list "a" "b")',
    ):
        assert MODULE.unbound_helm_action_reason(action), action


def test_each_runtime_secret_leaf_must_influence_only_secret_payload() -> None:
    actual = b"""apiVersion: v1
kind: Secret
metadata: {name: runtime}
stringData: {used: first}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: api}
spec: {}
"""
    used_shadow = actual.replace(b"used: first", b"used: changed")
    shape, changed = MODULE.validate_secret_leaf_influence(
        actual, used_shadow, "used leaf"
    )
    assert MODULE.SHA_RE.fullmatch(shape)
    assert changed == ["/runtime/stringData/used"]
    with pytest.raises(MODULE.ContractError, match="unused"):
        MODULE.validate_secret_leaf_influence(actual, actual, "unused second leaf")
    outside_secret = actual.replace(b"name: api", b"name: changed-api")
    with pytest.raises(MODULE.ContractError, match="Secret payload"):
        MODULE.validate_secret_leaf_influence(actual, outside_secret, "structural leaf")


def test_handoff_contract_never_contains_executable_argv() -> None:
    source = inspect.getsource(MODULE.preflight)
    assert '"operator_command_argv": None' in source
    assert '"authorized": False' in source
    assert '"production_ready": False' in source
    assert '"state": "preflight-passed"' not in source


def test_approval_schema_and_secret_sentinel_are_closed(tmp_path: Path) -> None:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    approval = {
        "schema_version": 1,
        "action": "install",
        "bundle_sha256": "a" * 64,
        "target": {
            "kube_context": "fixture", "api_server": "https://127.0.0.1:6443",
            "ca_sha256": "b" * 64, "cluster_uid": "cluster-uid",
            "namespace": "galileo", "namespace_uid": "namespace-uid", "release_name": "galileo",
        },
        "approver": "Galileo CSE",
        "ticket": "CASE-123",
        "galileo_cse_approved": True,
        "joint_session": "SESSION-123",
        "issued_at": MODULE.utc_text(now),
        "expires_at": MODULE.utc_text(now + dt.timedelta(hours=1)),
    }

    def write(document: dict, name: str) -> Path:
        path = tmp_path / name
        path.write_text(yaml.safe_dump(document), encoding="utf-8")
        os.chmod(path, 0o600)
        return path

    # Local YAML cannot authenticate Galileo/CSE. The handoff-only release
    # intentionally has no approval importer, so this remains illustrative.
    assert write(approval, "illustrative-only.yaml").exists()
    assert not hasattr(MODULE, "load_approval")


def test_rendered_image_evidence_contract_rejects_tampering() -> None:
    spec = {
        "target": {
            "kube_context": "fixture", "api_server": "https://127.0.0.1:6443",
            "ca_sha256": "b" * 64, "cluster_uid": "cluster-uid", "namespace": "galileo",
        },
        "stack": {
            "release_name": "galileo", "chart_version": "1.2.3", "chart_sha256": "c" * 64,
            "nonsecret_values_file": "inputs/values.yaml",
        },
        "galileoctl": {"enabled": False},
    }
    manifest = {
        "bundle_sha256": "a" * 64,
        "files": [{"path": "inputs/values.yaml", "sha256": "d" * 64}],
    }
    created = "2026-08-13T12:00:00Z"
    image = "registry.example/api@sha256:" + "e" * 64
    preflight = {
        "secret_contract_sha256": "f" * 64,
        "galileoctl_secret_contract_sha256": "",
        "target": {"namespace_uid": "namespace-uid"},
        "created_at": created,
        "rendered_images": [image],
    }
    evidence = {
        "schema": MODULE.IMAGE_EVIDENCE_SCHEMA,
        "generated_by": "galileo-on-prem-stack-setup",
        "source_bundle_sha256": "a" * 64,
        "charts": [{"name": "galileo-stack", "release": "galileo", "version": "1.2.3", "sha256": "c" * 64}],
        "inputs": {
            "stack_nonsecret_values_sha256": "d" * 64,
            "stack_secret_contract_sha256": "f" * 64,
            "galileoctl_nonsecret_values_sha256": "",
            "galileoctl_secret_contract_sha256": "",
        },
        "redacted_render_sha256": "1" * 64,
        "target": {
            "context": "fixture", "api_server": "https://127.0.0.1:6443", "ca_sha256": "b" * 64,
            "kube_system_uid": "cluster-uid", "namespace": "galileo", "namespace_uid": "namespace-uid",
        },
        "created_at": created,
        "items": [{
            "release": "galileo", "source_object": "Deployment/api", "container_type": "container",
            "container": "api", "image": image, "digest": "sha256:" + "e" * 64,
            "eligible_architectures": ["amd64"],
        }],
    }
    raw = MODULE.json_bytes(evidence)
    assert MODULE.validate_rendered_image_evidence(evidence, raw, spec, manifest, preflight) == evidence
    tampered = json.loads(raw)
    tampered["items"][0]["release"] = "other"
    with pytest.raises(MODULE.ContractError):
        MODULE.validate_rendered_image_evidence(tampered, MODULE.json_bytes(tampered), spec, manifest, preflight)


def test_gpu_limits_only_and_partial_resume_fails_closed() -> None:
    workload = [{
        "kind": "Deployment",
        "metadata": {"name": "wizard"},
        "spec": {"template": {"spec": {
            "nodeSelector": {"galileo-node-type": "galileo-ml"},
            "containers": [{
                "name": "wizard",
                "image": "registry.example/wizard@sha256:" + "a" * 64,
                "resources": {"limits": {"nvidia.com/gpu": "1"}},
            }],
            "imagePullSecrets": [{"name": "registry-secret"}],
        }}},
    }, {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "wizard"}, "spec": {}}]
    wizard = {
        "enabled": True, "expected_deployments": ["wizard"], "gpu_enabled": True,
        "gpu_resource": "nvidia.com/gpu", "triton_required": False,
        "hpa_required": False, "network_policy_required": False,
        "multi_gpu_cse_reference": "", "multi_gpu_model_support_evidence": "",
    }
    MODULE.validate_gpu_rendering(workload, wizard, [{}])
    request_only = json.loads(json.dumps(workload))
    request_only[0]["spec"]["template"]["spec"]["containers"][0]["resources"] = {
        "requests": {"nvidia.com/gpu": "1"},
    }
    with pytest.raises(MODULE.ContractError, match="positive GPU limit"):
        MODULE.validate_gpu_rendering(request_only, wizard, [{}])

    target = [{"chart": "galileo-stack-2.0.0", "status": "deployed"}]
    old = [{"chart": "galileo-stack-1.0.0", "status": "deployed"}]
    assert MODULE.release_operation_mode([], "install", "galileo-stack", "2.0.0", "Stack") == "install"
    with pytest.raises(MODULE.ContractError, match="partial resume"):
        MODULE.release_operation_mode(target, "install", "galileo-stack", "2.0.0", "Stack")
    assert MODULE.release_operation_mode(old, "upgrade", "galileo-stack", "2.0.0", "Stack") == "upgrade"
    with pytest.raises(MODULE.ContractError, match="partial resume"):
        MODULE.release_operation_mode(target, "upgrade", "galileo-stack", "2.0.0", "Stack")


def test_exact_kubernetes_patch_version_and_hard_taints_are_bound() -> None:
    raw, normalized, major, minor, patch = MODULE.canonical_kubernetes_server_version(
        {
            "serverVersion": {
                "major": "1",
                "minor": "31+",
                "gitVersion": "v1.31.14-gke.1020000+vendor.1",
            }
        }
    )
    assert (raw, normalized, major, minor, patch) == (
        "v1.31.14-gke.1020000+vendor.1",
        "1.31.14-gke.1020000+vendor.1",
        1,
        31,
        14,
    )
    assert MODULE.validate_simple_chart_kube_constraint(">=1.31.5", "1.31.14")
    with pytest.raises(MODULE.ContractError, match="does not satisfy"):
        MODULE.validate_simple_chart_kube_constraint("<1.31.5", "1.31.14")
    assert MODULE.validate_simple_chart_kube_constraint(">=1.31.14-0", "1.31.14-rc.1")
    with pytest.raises(MODULE.ContractError, match="does not satisfy"):
        MODULE.validate_simple_chart_kube_constraint(">=1.31.14", "1.31.14-rc.1")

    pool = {
        "role": "core",
        "label_value": "galileo-core",
        "architecture": "amd64",
        "min_nodes": 1,
        "max_nodes": 1,
        "min_cpu": "4",
        "min_memory": "16Gi",
        "min_ephemeral_storage": "100Gi",
        "taints": ["dedicated=galileo:NoSchedule"],
        "failure_domains": [],
    }
    node = {
        "metadata": {
            "name": "core-0",
            "labels": {
                "galileo-node-type": "galileo-core",
                "kubernetes.io/arch": "amd64",
                "kubernetes.io/hostname": "core-0",
            },
        },
        "spec": {
            "taints": [{
                "key": "dedicated", "value": "galileo", "effect": "NoSchedule",
            }],
        },
        "status": {
            "conditions": [{"type": "Ready", "status": "True"}],
            "allocatable": {
                "cpu": "4", "memory": "16Gi", "ephemeral-storage": "100Gi",
            },
        },
    }
    pool_spec = {
        "environment": "lab",
        "node_pools": {"pools": [pool]},
    }
    assert MODULE.validate_node_pools(pool_spec, {"items": [node]}) == {"core": 1}
    tainted = json.loads(json.dumps(node))
    tainted["spec"]["taints"].append({
        "key": "maintenance", "value": "true", "effect": "NoExecute",
    })
    with pytest.raises(MODULE.ContractError, match="unreviewed hard taint"):
        MODULE.validate_node_pools(pool_spec, {"items": [tainted]})


def test_air_gap_seed_to_final_contract_is_exact() -> None:
    digest = "sha256:" + "e" * 64
    mirror = "registry.internal/galileo/api"
    image = mirror + "@" + digest
    spec = {
        "target": {
            "kube_context": "fixture", "api_server": "https://127.0.0.1:6443",
            "ca_sha256": "b" * 64, "cluster_uid": "cluster-uid",
            "namespace": "galileo", "namespace_uid": "namespace-uid",
        },
        "stack": {
            "release_name": "galileo", "chart_version": "1.2.3", "chart_sha256": "c" * 64,
        },
        "galileoctl": {"enabled": False},
    }
    charts = MODULE.image_evidence_charts(spec)
    inputs = {
        "stack_nonsecret_values_sha256": "d" * 64,
        "stack_secret_contract_sha256": "f" * 64,
        "galileoctl_nonsecret_values_sha256": "",
        "galileoctl_secret_contract_sha256": "",
    }
    target = {
        "context": "fixture", "api_server": "https://127.0.0.1:6443", "ca_sha256": "b" * 64,
        "kube_system_uid": "cluster-uid", "namespace": "galileo", "namespace_uid": "namespace-uid",
    }
    items = [{
        "release": "galileo", "source_object": "Deployment/api", "container_type": "container",
        "container": "api", "image": image, "digest": digest,
        "eligible_architectures": ["amd64"],
    }]
    seed = {
        "evidence_sha256": "1" * 64, "source_bundle_sha256": "2" * 64,
        "charts": charts, "inputs": inputs, "redacted_render_sha256": "3" * 64,
        "target": target, "items": items,
    }
    stack_row = {
        "source": "vendor.example/galileo/api", "source_digest": digest,
        "mirror": mirror, "mirror_digest": digest,
        "archive_file": "images/0000.oci.tar", "archive_sha256": "4" * 64,
        "architectures": ["amd64"], "uses": ["runtime"],
        "scan_attestation_file": "scans/0000.json",
        "source_scan_attestation_sha256": "5" * 64, "scan_attestation_sha256": "6" * 64,
    }
    contract = {
        "schema": "galileo-on-prem-air-gap-bundle/v1", "bundle_sha256": "7" * 64,
        "stack_bundle_sha256": "2" * 64, "stack_image_evidence_sha256": "1" * 64,
        "charts": [{"name": "galileo-stack", "version": "1.2.3", "sha256": "c" * 64}],
        "images": [stack_row], "stack_seed": seed, "stack_images": [stack_row],
    }
    current = {
        "charts": charts, "inputs": inputs, "redacted_render_sha256": "3" * 64,
        "target": target, "items": items,
    }
    MODULE.validate_air_gap_contract(
        contract, spec, current,
        {"stack_nonsecret_values_sha256": "d" * 64, "galileoctl_nonsecret_values_sha256": ""},
    )
    forged = json.loads(json.dumps(contract))
    forged["stack_seed"]["inputs"]["stack_secret_contract_sha256"] = "9" * 64
    with pytest.raises(MODULE.ContractError, match="inputs"):
        MODULE.validate_air_gap_contract(forged, spec, current)
    wrong_mirror = json.loads(json.dumps(contract))
    wrong_mirror["stack_images"][0]["mirror"] = "registry.internal/galileo/other"
    with pytest.raises(MODULE.ContractError, match="aggregate|mirrors"):
        MODULE.validate_air_gap_contract(wrong_mirror, spec, current)


def test_lookup_endpoint_and_external_load_balancer_contracts_are_closed() -> None:
    with pytest.raises(MODULE.ContractError, match="Helm lookup"):
        MODULE.reject_cluster_dependent_helm_templates([
            (
                "galileo-stack/charts/api-1.0.0.tgz!/api/templates/_helpers.tpl",
                b'{{- $existing := lookup "v1" "Secret" .Release.Namespace "runtime" -}}\n',
            ),
        ])
    MODULE.reject_cluster_dependent_helm_templates([
        ("galileo-stack/templates/deployment.yaml", b"apiVersion: apps/v1\nkind: Deployment\n"),
    ])
    for action in (
        b"{{ .Capabilities.APIVersions.Has \"example/v1\" }}",
        b"{{ .Release.IsUpgrade }}",
        b"{{ randAlphaNum 32 }}",
    ):
        with pytest.raises(MODULE.ContractError, match="rejects"):
            MODULE.reject_cluster_dependent_helm_templates([
                ("galileo-stack/templates/_helpers.tpl", action),
            ])
    with pytest.raises(MODULE.ContractError, match="Helm lookup"):
        MODULE.reject_unbound_helm_value_actions(
            {"rendered": '{{ lookup "v1" "Secret" "ns" "name" }}'},
            "fixture-values",
        )
    source = inspect.getsource(MODULE.preflight)
    assert 'template_args + ["--skip-crds"]' in source
    assert 'template_args + ["--include-crds"]' in source

    secret_url = "postgres://runtime-user:sentinel-password@db.internal.example:5432/galileo?token=secret"
    endpoint_items = MODULE.rendered_endpoint_items(
        [("galileo", [{
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "runtime"},
            "data": {"database-url": base64.b64encode(secret_url.encode()).decode()},
        }, {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "api"},
            "spec": {"template": {"spec": {"containers": [{
                "name": "api",
                "env": [{"name": "BROKER_HOST", "value": "rabbitmq.internal.example:5672"}],
                "args": ["--telemetry-endpoint=collector.internal.example:4317"],
            }]}}},
        }])],
        [],
    )
    assert {item["host"] for item in endpoint_items} == {
        "collector.internal.example:4317", "rabbitmq.internal.example:5672",
    }
    serialized = json.dumps(endpoint_items)
    for sentinel in ("runtime-user", "sentinel-password", "cache-user", "cache-secret", "token="):
        assert sentinel not in serialized


def test_rendered_secret_placement_and_endpoint_evidence_never_persist_literals() -> None:
    marker = "fake-secret-8f3d"
    unsafe_documents = [
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "unsafe"},
            "data": {"admin_password": marker},
        },
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "unsafe"},
            "spec": {"template": {"spec": {"containers": [{
                "name": "app",
                "image": "registry.example/app@sha256:" + "a" * 64,
                "env": [{"name": "DATABASE_PASSWORD", "value": marker}],
            }]}}},
        },
        {
            "apiVersion": "example.invalid/v1",
            "kind": "Example",
            "metadata": {"name": "unsafe"},
            "spec": {"credential": {"value": marker}},
        },
    ]
    for document in unsafe_documents:
        with pytest.raises(MODULE.ContractError, match="credential|plaintext"):
            MODULE.validate_rendered_secret_placement([document])

    safe = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "safe"},
        "spec": {"template": {"spec": {
            "automountServiceAccountToken": False,
            "imagePullSecrets": [{"name": "registry-secret"}],
            "containers": [{
                "name": "app",
                "image": "registry.example/app@sha256:" + "a" * 64,
                "env": [{
                    "name": "DATABASE_PASSWORD",
                    "valueFrom": {"secretKeyRef": {"name": "runtime", "key": "password"}},
                }],
                "envFrom": [{"secretRef": {"name": "runtime", "optional": False}}],
            }],
            "volumes": [
                {
                    "name": "runtime-secret",
                    "secret": {"secretName": "runtime", "optional": False},
                },
                {
                    "name": "projected",
                    "projected": {"sources": [{"serviceAccountToken": {"tokenExpirationSeconds": 600}}]},
                },
            ],
        }}},
    }
    MODULE.validate_rendered_secret_placement([safe])
    ordinary_secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "api-secret"},
        "type": "Opaque",
        "stringData": {"runtime": marker},
    }
    MODULE.validate_rendered_secret_placement([ordinary_secret])

    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "runtime"},
        "stringData": {"server": marker, "api_url": f"https://{marker}.example.invalid"},
    }
    MODULE.validate_rendered_secret_placement([secret])
    for env_name in ("AWS_SECRET_ACCESS_KEY", "NEXTAUTH_SECRET"):
        unsafe_env = json.loads(json.dumps(safe))
        unsafe_env["spec"]["template"]["spec"]["containers"][0]["env"] = [{
            "name": env_name,
            "value": marker,
        }]
        with pytest.raises(MODULE.ContractError, match="plaintext credential env"):
            MODULE.validate_rendered_secret_placement([unsafe_env])
    secret_with_unsafe_metadata = json.loads(json.dumps(secret))
    secret_with_unsafe_metadata["metadata"]["annotations"] = {
        "example.invalid/client-secret": marker,
    }
    with pytest.raises(MODULE.ContractError, match="credential"):
        MODULE.validate_rendered_secret_placement([secret_with_unsafe_metadata])
    for field in ("secretRef", "secretKeyRef"):
        unsafe_custom_ref = {
            "apiVersion": "example.invalid/v1",
            "kind": "Widget",
            "metadata": {"name": "unsafe-ref"},
            "spec": {field: {"password": marker}},
        }
        with pytest.raises(MODULE.ContractError, match="credential"):
            MODULE.validate_rendered_secret_placement([unsafe_custom_ref])
        with pytest.raises(MODULE.ContractError, match="credential"):
            MODULE.canonical_redacted_manifest([unsafe_custom_ref])
    for parent, field in (("credentials", "name"), ("auth", "key")):
        unsafe_identifier = {
            "apiVersion": "example.invalid/v1",
            "kind": "Widget",
            "metadata": {"name": "unsafe-identifier"},
            "spec": {parent: {field: marker}},
        }
        with pytest.raises(MODULE.ContractError, match="credential"):
            MODULE.validate_rendered_secret_placement([unsafe_identifier])
        with pytest.raises(MODULE.ContractError, match="credential"):
            MODULE.canonical_redacted_manifest([unsafe_identifier])
    items = MODULE.rendered_endpoint_items([("galileo", [secret])], [])
    output = json.dumps(items) + MODULE.canonical_redacted_manifest([secret]).decode()
    assert marker not in output


def test_nonsecret_values_reject_literal_credential_taxonomy(tmp_path: Path) -> None:
    marker = "fake-secret-8f3d"
    for key in (
        "awsSecretAccessKey",
        "AWS_SECRET_ACCESS_KEY",
        "licenseKey",
        "signingKey",
        "encryptionKey",
        "sessionSecret",
        "nextauthSecret",
        "clientSecret",
        "cookieSecret",
        "privateKey",
        "jwtSecret",
        "databaseSecret",
        "redisSecret",
        "secretKey",
        "awsSecretKey",
        "webhookSecret",
        "sharedSecret",
        "encryptionSecret",
        "oauthSecret",
        "secretValue",
        "clientSecretValue",
        "databasePasswordValue",
        "accessTokenValue",
        "apiKeyValue",
        "credentialValue",
        "privateKeyValue",
        "jwtSecretValue",
    ):
        path = tmp_path / f"{key}.yaml"
        path.write_text(yaml.safe_dump({"application": {key: marker}}))
        with pytest.raises(MODULE.ContractError, match="secret-like field"):
            MODULE.validate_values_no_secrets(path)

        nested_path = tmp_path / f"{key}-nested.yaml"
        nested_path.write_text(yaml.safe_dump({"application": {key: {"value": marker}}}))
        with pytest.raises(MODULE.ContractError, match="secret-like field"):
            MODULE.validate_values_no_secrets(nested_path)

    nested_literals = (
        {"credentials": {"value": marker}},
        {"awsSecretAccessKey": {"value": marker}},
        {"clientSecret": {"literal": marker}},
        {"authorization": {"value": marker}},
        {"password": [marker]},
    )
    for index, value in enumerate(nested_literals):
        path = tmp_path / f"nested-{index}.yaml"
        path.write_text(yaml.safe_dump({"application": value}))
        with pytest.raises(MODULE.ContractError, match="secret-like field"):
            MODULE.validate_values_no_secrets(path)

    references = tmp_path / "references.yaml"
    references.write_text(
        yaml.safe_dump(
            {
                "application": {
                    "existingSecret": "runtime-secret",
                    "databaseSecretName": "database-secret",
                    "credentials": {"existingSecret": "runtime-secret"},
                    "automountServiceAccountToken": False,
                    "serviceAccountToken": True,
                    "tokenExpirationSeconds": 600,
                    "secretRef": {"name": "runtime-secret", "optional": False},
                    "secretKeyRef": {
                        "name": "runtime-secret",
                        "key": "password",
                        "optional": False,
                    },
                }
            }
        )
    )
    assert MODULE.validate_values_no_secrets(references)["application"]["existingSecret"] == "runtime-secret"

    for key in (
        "jwtSecret",
        "databaseSecret",
        "redisSecret",
        "secretKey",
        "awsSecretKey",
        "webhookSecret",
        "sharedSecret",
        "encryptionSecret",
        "oauthSecret",
        "secretValue",
        "clientSecretValue",
        "databasePasswordValue",
        "accessTokenValue",
        "apiKeyValue",
        "credentialValue",
        "privateKeyValue",
        "jwtSecretValue",
    ):
        rendered = {
            "apiVersion": "example.invalid/v1",
            "kind": "Widget",
            "metadata": {"name": "unsafe"},
            "spec": {key: {"value": marker}},
        }
        with pytest.raises(MODULE.ContractError, match="credential"):
            MODULE.validate_rendered_secret_placement([rendered])
        with pytest.raises(MODULE.ContractError, match="credential"):
            MODULE.canonical_redacted_manifest([rendered])
        config_map = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "unsafe"},
            "data": {key: marker},
        }
        with pytest.raises(MODULE.ContractError, match="credential"):
            MODULE.validate_rendered_secret_placement([config_map])
        env = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "unsafe"},
            "spec": {"template": {"spec": {"containers": [{
                "name": "app",
                "image": "registry.example/app@sha256:" + "a" * 64,
                "env": [{"name": key, "value": marker}],
            }]}}},
        }
        with pytest.raises(MODULE.ContractError, match="credential|plaintext"):
            MODULE.validate_rendered_secret_placement([env])

    for stem in (
        "secret",
        "password",
        "passwd",
        "token",
        "apiKey",
        "accessKey",
        "privateKey",
        "credential",
        "authorization",
    ):
        for suffix in ("Value", "Data", "Config"):
            variants = {
                stem + suffix,
                (stem + "_" + suffix).upper(),
                (stem + "-" + suffix).lower(),
                "prefix." + stem + "." + suffix,
            }
            for variant in variants:
                assert MODULE.classify_key((variant,), "rendered") == "secret_literal"

    assert MODULE.classify_key(
        ("automountServiceAccountToken",), "kubernetes-structural"
    ) == "structural_nonsecret"
    assert MODULE.classify_key(
        ("tokenExpirationSeconds",), "kubernetes-structural"
    ) == "structural_nonsecret"


def test_evidence_generation_commit_is_atomic_and_preserves_prior(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    os.chmod(tmp_path, 0o700)
    state_dir = tmp_path / ".state" / ("a" * 64)
    MODULE.ensure_private_directory(state_dir, tmp_path)
    first_id, first_dir = MODULE.commit_evidence_generation(
        state_dir,
        "a" * 64,
        "2026-08-13T12:00:00Z",
        (("preflight.json", b"{\"first\":true}\n"),),
    )
    pointer_before = (state_dir / "current.json").read_bytes()
    first_before = {
        path.name: path.read_bytes() for path in first_dir.iterdir() if path.is_file()
    }
    original_write = MODULE.write_private
    calls = 0

    def interrupted(path: Path, body: bytes, mode: int = 0o600) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic interrupted evidence write")
        original_write(path, body, mode)

    monkeypatch.setattr(MODULE, "write_private", interrupted)
    with pytest.raises(OSError, match="synthetic interrupted"):
        MODULE.commit_evidence_generation(
            state_dir,
            "a" * 64,
            "2026-08-13T12:01:00Z",
            (("preflight.json", b"{\"second\":true}\n"),),
        )
    assert (state_dir / "current.json").read_bytes() == pointer_before
    assert {
        path.name: path.read_bytes() for path in first_dir.iterdir() if path.is_file()
    } == first_before
    assert MODULE.verified_evidence_generation(
        state_dir, first_id, "a" * 64
    ) == first_dir
    assert MODULE.verified_current_evidence_generation(
        state_dir, "a" * 64
    ) == (first_id, first_dir)
    assert not list((state_dir / "generations").glob(".pending-*"))

    manifest_path = first_dir / "generation-manifest.json"
    preflight_path = first_dir / "preflight.json"
    original_manifest = manifest_path.read_bytes()
    original_preflight = preflight_path.read_bytes()
    forged_preflight = b'{"forged":true}\n'
    preflight_path.write_bytes(forged_preflight)
    forged_manifest = json.loads(original_manifest)
    forged_manifest["files"][0]["sha256"] = MODULE.sha256_bytes(forged_preflight)
    forged_manifest["files"][0]["size"] = len(forged_preflight)
    manifest_path.write_bytes(MODULE.json_bytes(forged_manifest))
    with pytest.raises(MODULE.ContractError, match="generation ID differs"):
        MODULE.verified_evidence_generation(state_dir, first_id, "a" * 64)

    preflight_path.write_bytes(original_preflight)
    manifest_path.write_bytes(original_manifest)
    duplicate_manifest = json.loads(original_manifest)
    duplicate_manifest["files"].append(dict(duplicate_manifest["files"][0]))
    manifest_path.write_bytes(MODULE.json_bytes(duplicate_manifest))
    with pytest.raises(MODULE.ContractError, match="path is invalid"):
        MODULE.verified_evidence_generation(state_dir, first_id, "a" * 64)
    manifest_path.write_bytes(original_manifest)

    routing = {
        "prerequisite_load_balancers": [{
            "namespace": "ingress-system",
            "name": "ingress-controller",
            "uid": "service-uid-123",
            "addresses": ["192.0.2.200"],
        }],
        "load_balancer_addresses": ["192.0.2.200"],
    }
    exact = {
        "metadata": {"namespace": "ingress-system", "name": "ingress-controller", "uid": "service-uid-123"},
        "spec": {"type": "LoadBalancer"},
        "status": {"loadBalancer": {"ingress": [{"ip": "192.0.2.200"}]}},
    }
    spoof = {
        "metadata": {"namespace": "other", "name": "ingress-controller", "uid": "spoof-uid"},
        "spec": {"type": "LoadBalancer"},
        "status": {"loadBalancer": {"ingress": [{"ip": "192.0.2.200"}]}},
    }
    rows, addresses = MODULE.validate_prerequisite_load_balancer_services(
        {"items": [spoof, exact]}, routing,
    )
    assert rows == [{
        "namespace": "ingress-system", "name": "ingress-controller",
        "uid": "service-uid-123", "addresses": ["192.0.2.200"],
    }]
    assert addresses == {"192.0.2.200"}
    with pytest.raises(MODULE.ContractError, match="absent"):
        MODULE.validate_prerequisite_load_balancer_services({"items": [spoof]}, routing)
    changed_uid = json.loads(json.dumps(exact))
    changed_uid["metadata"]["uid"] = "recreated-uid"
    with pytest.raises(MODULE.ContractError, match="UID changed"):
        MODULE.validate_prerequisite_load_balancer_services({"items": [changed_uid]}, routing)
    routing_source = inspect.getsource(MODULE.validate_routing_prerequisites)
    assert '"--all-namespaces"' not in routing_source
    assert 'row["name"]' in routing_source
    assert 'row["namespace"]' in routing_source
    assert '"--namespace"' in routing_source


def test_lab_target_and_unused_cluster_cidr_overlap_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = {
        "apiVersion": "v1",
        "kind": "Config",
        "current-context": "microk8s",
        "contexts": [{"name": "microk8s", "context": {"cluster": "microk8s", "user": "admin"}}],
        "clusters": [{"name": "microk8s", "cluster": {
            "server": "https://127.0.0.1:16443",
            "certificate-authority-data": base64.b64encode(b"local-ca").decode(),
        }}],
        "users": [{"name": "admin", "user": {"client-certificate-data": "fixture"}}],
    }

    def fake_run(command: list[str], _env: dict[str, str], **_kwargs: object) -> bytes:
        if command[-1] == "config":
            return yaml.safe_dump(config).encode()
        return json.dumps({"metadata": {"uid": "local-cluster-uid"}}).encode()

    monkeypatch.setattr(MODULE, "run_checked", fake_run)
    with pytest.raises(MODULE.ContractError, match="differs"):
        MODULE.validate_microk8s_cli_target(
            "/snap/bin/microk8s", {}, tmp_path,
            "https://192.0.2.40:16443", "a" * 64, "remote-cluster-uid",
        )

    now = MODULE.utc_text(MODULE.utc_now())
    with pytest.raises(MODULE.ContractError, match="overlaps"):
        MODULE.validate_metallb_nonoverlap(
            "10.152.183.200-10.152.183.210",
            {"items": []}, {"items": []}, {"items": []}, [],
            ["10.152.183.0/24"], ["10.1.0.0/16"],
            "reviewed MicroK8s network CIDRs", now,
        )


def test_operator_generated_pvc_requires_exact_direct_controller_owner() -> None:
    expected = [{
        "source": "ClickHouseInstallation/analytics",
        "name": "data",
        "storage_class": "retained",
        "requested_bytes": 200 * 2**30,
        "access_modes": ["ReadWriteOnce"],
        "replicas": 1,
        "operator_generated": True,
        "expected_pvc_names": ["data-analytics-0"],
        "expected_pvc_owners": [{
            "pvc_name": "data-analytics-0", "kind": "StatefulSet", "name": "analytics-shard-0",
        }],
    }]
    pvc = {
        "metadata": {
            "name": "data-analytics-0",
            "labels": {"app.kubernetes.io/instance": "galileo"},
            "ownerReferences": [{
                "apiVersion": "apps/v1", "kind": "StatefulSet", "name": "analytics-shard-0",
                "uid": "statefulset-uid", "controller": True,
            }],
        },
        "spec": {
            "storageClassName": "retained", "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": "200Gi"}},
        },
        "status": {"phase": "Bound", "capacity": {"storage": "200Gi"}},
    }
    assert MODULE.validate_live_claims({"items": [pvc]}, expected, {"galileo"}) == ["data-analytics-0"]
    wrong_owner = json.loads(json.dumps(pvc))
    wrong_owner["metadata"]["ownerReferences"][0]["name"] = "unrelated"
    with pytest.raises(MODULE.ContractError, match="direct controller owner"):
        MODULE.validate_live_claims({"items": [wrong_owner]}, expected, {"galileo"})


def test_dedicated_crd_upgrade_rejects_version_removal_and_schema_narrowing() -> None:
    live = {
        "spec": {"versions": [{
            "name": "v1", "served": True, "storage": True,
            "schema": {"openAPIV3Schema": {
                "type": "object", "properties": {"mode": {"type": "string", "enum": ["a", "b"]}},
            }},
        }]},
        "status": {"storedVersions": ["v1"]},
    }
    removed = {"spec": {"versions": []}}
    with pytest.raises(MODULE.ContractError, match="removes served/storage/stored"):
        MODULE.crd_upgrade_diff("widgets.example", live, removed)
    narrowed = json.loads(json.dumps(live))
    narrowed["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["mode"]["enum"] = ["a"]
    with pytest.raises(MODULE.ContractError, match="narrowed enum"):
        MODULE.crd_upgrade_diff("widgets.example", live, narrowed)


def test_wizard_cpu_multi_deployment_and_multi_gpu_contracts() -> None:
    def deployment(name: str, gpu_limit: int | None = None) -> dict:
        resources = {"limits": {"nvidia.com/gpu": str(gpu_limit)}} if gpu_limit else {}
        return {
            "apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": name},
            "spec": {"template": {"spec": {
                "nodeSelector": {"galileo-node-type": "galileo-ml"} if gpu_limit else {},
                "containers": [{"name": name, "image": "example.invalid/wizard", "resources": resources}],
            }}},
        }

    cpu_documents = [
        deployment("wizard-a"), deployment("wizard-b"), deployment("triton-runtime"),
        {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "wizard-a"}, "spec": {}},
        {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "wizard-b"}, "spec": {}},
        {"apiVersion": "autoscaling/v2", "kind": "HorizontalPodAutoscaler", "metadata": {"name": "wizard-a"}, "spec": {"scaleTargetRef": {"name": "wizard-a"}}},
        {"apiVersion": "autoscaling/v2", "kind": "HorizontalPodAutoscaler", "metadata": {"name": "wizard-b"}, "spec": {"scaleTargetRef": {"name": "wizard-b"}}},
        {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": "wizard-a"}, "spec": {}},
        {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": "wizard-b"}, "spec": {}},
    ]
    cpu_wizard = {
        "enabled": True, "expected_deployments": ["wizard-a", "wizard-b"],
        "gpu_enabled": False, "gpu_resource": "nvidia.com/gpu",
        "triton_required": True, "hpa_required": True, "network_policy_required": True,
        "multi_gpu_cse_reference": "", "multi_gpu_model_support_evidence": "",
    }
    result = MODULE.validate_gpu_rendering(cpu_documents, cpu_wizard, [])
    assert result["expected_deployments"] == ["wizard-a", "wizard-b"]
    disabled = dict(cpu_wizard, enabled=False, expected_deployments=[], triton_required=False, hpa_required=False, network_policy_required=False)
    with pytest.raises(MODULE.ContractError, match="Wizard-disabled"):
        MODULE.validate_gpu_rendering(cpu_documents, disabled, [])

    multi_documents = [
        deployment("wizard-gpu", 2),
        {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "wizard-gpu"}, "spec": {}},
    ]
    multi_wizard = {
        "enabled": True, "expected_deployments": ["wizard-gpu"], "gpu_enabled": True,
        "gpu_resource": "nvidia.com/gpu", "triton_required": False,
        "hpa_required": False, "network_policy_required": False,
        "multi_gpu_cse_reference": "CSE-123", "multi_gpu_model_support_evidence": "MODEL-456",
    }
    one_gpu = [{"spec": {"taints": []}, "status": {"allocatable": {"nvidia.com/gpu": "1"}}}]
    with pytest.raises(MODULE.ContractError, match="multi-GPU"):
        MODULE.validate_gpu_rendering(multi_documents, multi_wizard, one_gpu)
    two_gpu = [{"spec": {"taints": []}, "status": {"allocatable": {"nvidia.com/gpu": "2"}}}]
    assert MODULE.validate_gpu_rendering(multi_documents, multi_wizard, two_gpu)["max_gpu_limit"] == 2


def test_monitoring_requires_exact_component_resource_identities() -> None:
    documents = [
        {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "galileo-grafana"}, "spec": {}},
        {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "galileo-grafana"}, "spec": {}},
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "galileo-grafana-dashboards"}, "data": {}},
        {"apiVersion": "apps/v1", "kind": "DaemonSet", "metadata": {"name": "galileo-fluent-bit"}, "spec": {}},
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "galileo-fluent-bit-config"}, "data": {}},
    ]
    monitoring = {
        "enabled": True,
        "expected_components": [
            {
                "name": "grafana", "workloads": ["galileo-grafana"],
                "services": ["galileo-grafana"],
                "required_kinds": ["ConfigMap", "Deployment", "Service"],
                "resources": [
                    {"kind": "Deployment", "name": "galileo-grafana"},
                    {"kind": "Service", "name": "galileo-grafana"},
                    {"kind": "ConfigMap", "name": "galileo-grafana-dashboards"},
                ],
                "persistence_required": False,
            },
            {
                "name": "fluent-bit", "workloads": ["galileo-fluent-bit"], "services": [],
                "required_kinds": ["ConfigMap", "DaemonSet"],
                "resources": [
                    {"kind": "DaemonSet", "name": "galileo-fluent-bit"},
                    {"kind": "ConfigMap", "name": "galileo-fluent-bit-config"},
                ],
                "persistence_required": False,
            },
        ],
    }
    result = MODULE.validate_monitoring_rendering(documents, monitoring)
    assert [row["name"] for row in result["components"]] == ["fluent-bit", "grafana"]
    undeclared = json.loads(json.dumps(monitoring))
    undeclared["expected_components"] = undeclared["expected_components"][:1]
    with pytest.raises(MODULE.ContractError, match="component set"):
        MODULE.validate_monitoring_rendering(documents, undeclared)
