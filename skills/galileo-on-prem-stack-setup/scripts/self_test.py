#!/usr/bin/env python3
"""Offline security regressions for the Galileo stack lifecycle engine."""

from __future__ import annotations

import importlib.util
import hashlib
import inspect
import io
import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

import yaml

import retain_resources


ENGINE = Path(__file__).with_name("stack_lifecycle.py")
SPEC = importlib.util.spec_from_file_location("galileo_stack_lifecycle", ENGINE)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def must_reject(callable_value, label: str) -> None:
    try:
        callable_value()
    except MODULE.ContractError:
        return
    raise AssertionError(f"did not reject {label}")


def main() -> None:
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_name:
        root = Path(temp_name)
        regular = root / "regular"
        regular.write_text("sentinel", encoding="utf-8")
        os.chmod(regular, 0o600)
        assert MODULE.secure_read(regular, "regular", private=True)[1] == b"sentinel"

        symlink = root / "symlink"
        symlink.symlink_to(regular)
        must_reject(lambda: MODULE.secure_read(symlink, "symlink", private=True), "symlink")

        hardlink = root / "hardlink"
        os.link(regular, hardlink)
        must_reject(lambda: MODULE.secure_read(regular, "hardlink", private=True), "hardlink")
        hardlink.unlink()

        fifo = root / "fifo"
        os.mkfifo(fifo, 0o600)
        must_reject(lambda: MODULE.secure_read(fifo, "fifo", private=True), "FIFO")

        ancestor = root / "ancestor"
        real_dir = root / "real-dir"
        real_dir.mkdir()
        ancestor.symlink_to(real_dir, target_is_directory=True)
        nested = real_dir / "value"
        nested.write_text("x", encoding="utf-8")
        must_reject(lambda: MODULE.secure_read(ancestor / "value", "ancestor symlink"), "symlink ancestor")

        private_env = root / "private-env"
        private_env.mkdir(mode=0o700)
        env = MODULE.minimal_env(private_env)
        assert "HOME" not in env
        assert "TOKEN" not in " ".join(env)
        assert not any(key.startswith(("AWS_", "AZURE_", "GOOGLE_")) for key in env)
        for secret_shape in (
            "password fixture-only",
            "Authorization: Bearer fixture-token",
            "postgres://user:secret@db.example/database",
            "-----BEGIN PRIVATE KEY-----",
        ):
            must_reject(
                lambda secret_shape=secret_shape: MODULE.reject_secret_like_scalars(secret_shape, "fixture"),
                f"credential-shaped scalar {secret_shape[:12]}",
            )
        kubeconfig = root / "kubeconfig.yaml"
        kubeconfig.write_text(yaml.safe_dump({"apiVersion": "v1", "kind": "Config", "contexts": [{"name": "fixture", "context": {"cluster": "fixture", "user": "fixture"}}], "users": [{"name": "fixture", "user": {"exec": {"command": "aws", "args": ["eks", "get-token"]}}}]}), encoding="utf-8")
        os.chmod(kubeconfig, 0o600)
        must_reject(lambda: MODULE.validate_kubeconfig_auth(kubeconfig, "fixture"), "ambient exec-auth kubeconfig")
        os.chmod(kubeconfig, 0o644)
        must_reject(lambda: MODULE.kubeconfig_path(str(kubeconfig)), "world-readable kubeconfig")

        def chart_archive(name: str = "api") -> Path:
            archive = root / f"{name}.tgz"
            files = {
                "galileo-stack/Chart.yaml": yaml.safe_dump({"apiVersion": "v2", "name": "galileo-stack", "version": "1.2.3", "dependencies": [{"name": name, "version": "1.0.0"}]}).encode(),
                "galileo-stack/templates/workload.yaml": b"apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: api\nspec:\n  template:\n    spec:\n      containers:\n      - name: api\n        image: registry.example/api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",
                "galileo-stack/crds/widgets.yaml": b"apiVersion: apiextensions.k8s.io/v1\nkind: CustomResourceDefinition\nmetadata:\n  name: widgets.example.com\nspec:\n  group: example.com\n  names: {kind: Widget, plural: widgets}\n  scope: Namespaced\n  versions: [{name: v1, served: true, storage: true, schema: {openAPIV3Schema: {type: object}}}]\n",
            }
            with tarfile.open(archive, "w:gz") as handle:
                for path, data in files.items():
                    member = tarfile.TarInfo(path)
                    member.size = len(data)
                    member.mode = 0o600
                    handle.addfile(member, io.BytesIO(data))
            return archive

        chart = chart_archive()
        values = root / "values.yaml"
        values.write_text(yaml.safe_dump({"global": {"disable_crds": True}, "clickhouse-operator": {"global": {"disable_crds": True}}, "rabbitmq-operator": {"global": {"disable_crds": True}}, "sequencing": {"crd_management": {"enabled": False}}}), encoding="utf-8")
        spec_document = {
            "schema_version": 1, "deployment_id": "fixture", "environment": "lab", "installation_method": "helm-cli", "galileo_console_url": "https://console.fixture.example/",
            "target": {"kube_context": "fixture", "api_server": "https://127.0.0.1:6443", "ca_sha256": "b" * 64, "cluster_uid": "uid", "namespace": "galileo", "namespace_create": False, "namespace_uid": "namespace-uid"},
            "stack": {"release_name": "galileo", "chart_archive": str(chart), "chart_sha256": hashlib.sha256(chart.read_bytes()).hexdigest(), "chart_version": "1.2.3", "nonsecret_values_file": str(values), "runtime_secret_value_paths": ["global.runtimeSecret"], "timeout": "120m"},
            "galileoctl": {"enabled": False}, "crds": {"mode": "shared", "upgrade_compatibility_evidence": "", "conversion_evidence": "", "stored_versions_evidence": ""},
            "storage": {"default_class": "test", "classes": [{"name": "test", "minimum_size_gib": 200, "reclaim_policy": "Retain", "allow_expansion": True, "snapshots": True}], "restore_tested": True, "snapshot_evidence": "", "restore_evidence": "", "snapshot_evidence_observed_at": None, "restore_evidence_observed_at": None, "restore_evidence_max_age_days": 90, "operator_claims": []},
            "data_services": {"postgres": "bundled-lab", "redis": "in-cluster-exception", "redis_support_exception": "lab fixture only", "object_store": "in-cluster-minio", "object_store_support_exception": None, "clickhouse_backup_verified": False, "clickhouse_restore_verified": False, "postgres_backup_verified": False, "postgres_restore_verified": False, "postgres_backup_frequency_hours": 24, "object_store_backup_verified": False, "object_store_restore_verified": False, "object_store_nondefault_secret": False, "postgres_backup_evidence": "", "postgres_restore_evidence": "", "clickhouse_backup_evidence": "", "clickhouse_restore_evidence": "", "object_store_backup_evidence": "", "object_store_restore_evidence": "", "object_store_backup_bucket": "", "backup_evidence_observed_at": None, "restore_evidence_observed_at": None, "restore_evidence_max_age_days": 90, "readiness": {"observed_at": None, "postgres": {"ownership": "release-managed", "reachable": False, "tls": False, "authenticated": False, "ha_ready": False, "version": "", "reference": ""}, "redis": {"ownership": "release-managed", "reachable": False, "tls": False, "authenticated": False, "ha_ready": False, "version": "", "reference": "", "persistence_or_rebuild_decision": "lab disposable"}, "object_store": {"ownership": "release-managed", "reachable": False, "tls": False, "authenticated": False, "ha_ready": False, "bucket_exists": False, "version": "", "reference": ""}, "clickhouse": {"ownership": "release-managed", "reachable": False, "tls": False, "authenticated": False, "ha_ready": False, "version": "", "reference": ""}, "rabbitmq": {"ownership": "release-managed", "reachable": False, "tls": False, "authenticated": False, "ha_ready": False, "persistence_ready": False, "version": "", "reference": "", "queue_recovery_reference": "lab disposable"}}},
            "node_pools": {"autoscaler_validated": False, "cse_sizing_reference": "", "production_count_exception": None, "pools": [{"role": "core", "label_value": "galileo-core", "min_nodes": 1, "max_nodes": 10, "min_cpu": "4", "min_memory": "16Gi", "min_ephemeral_storage": "100Gi", "architecture": "amd64", "failure_domains": [], "taints": []}, {"role": "runner", "label_value": "galileo-runner", "min_nodes": 1, "max_nodes": 5, "min_cpu": "8", "min_memory": "32Gi", "min_ephemeral_storage": "200Gi", "architecture": "amd64", "failure_domains": [], "taints": []}]},
            "routing": {"domain": "fixture.example", "console_host": "console.fixture.example", "api_host": "api.fixture.example", "grafana_host": "grafana.fixture.example", "tls_secret_names": ["console-tls", "api-tls", "grafana-tls"], "tls_bindings": [{"host": "console.fixture.example", "secret": "console-tls"}, {"host": "api.fixture.example", "secret": "api-tls"}, {"host": "grafana.fixture.example", "secret": "grafana-tls"}], "ingress_class": "nginx", "gateway_class": None, "load_balancer_lifecycle": "release-managed-staged-handoff", "load_balancer_services": ["ingress-controller"], "prerequisite_load_balancers": [], "load_balancer_addresses": ["192.0.2.20"], "dns_validated": False, "certificate_min_valid_days": 30, "tls_required": True, "streaming_timeout_seconds": 120, "streaming_timeout_controls": [], "public_metrics_blocked": True, "metrics_protection_resources": [], "trace_route_before_api_catchall": True, "routes": ["https://api.fixture.example/healthcheck", "https://console.fixture.example/api/healthcheck", "https://grafana.fixture.example/"]},
            "monitoring": {"enabled": False, "alert_owner": "lab", "expected_components": []}, "authorization": {"rbac_enforced": False, "evidence": "lab-only"},
            "wizard": {"enabled": False, "expected_deployments": [], "triton_required": False, "hpa_required": False, "network_policy_required": False, "gpu_enabled": False, "multi_gpu_cse_reference": "", "multi_gpu_model_support_evidence": ""}, "air_gap": {"enabled": False, "verified_contract_file": None, "verified_contract_sha256": None},
            "coverage": {"enforce_runtime_inventory": True, "reviewed_components": [], "reviewed_schema_or_enable_flags": [], "reviewed_kinds": [], "reviewed_images": [], "reviewed_crds": [], "reviewed_hooks": [], "reviewed_cluster_scoped_kinds": [], "reviewed_pvcs": [], "reviewed_routes": []},
            "exceptions": [], "lab_bootstrap": {"enabled": False, "enable_hostpath_storage": False, "metallb_address_pool": None, "service_cidrs": [], "pod_cidrs": [], "network_nonoverlap_evidence": "", "network_evidence_observed_at": None, "node_labels": {}},
        }
        spec_path = root / "spec.yaml"
        spec_path.write_text(yaml.safe_dump(spec_document), encoding="utf-8")
        unrelated = yaml.safe_load(yaml.safe_dump(spec_document))
        unrelated["routing"]["routes"].append("https://unrelated.example.net/")
        unrelated_path = root / "unrelated.yaml"
        unrelated_path.write_text(yaml.safe_dump(unrelated), encoding="utf-8")
        must_reject(
            lambda: MODULE.load_spec(unrelated_path, "https://console.fixture.example/"),
            "routing outside reviewed sibling domain",
        )
        unsafe_api = yaml.safe_load(yaml.safe_dump(spec_document))
        unsafe_api["target"]["api_server"] = "https://user:pass@127.0.0.1:6443/?token=x"
        unsafe_api_path = root / "unsafe-api.yaml"
        unsafe_api_path.write_text(yaml.safe_dump(unsafe_api), encoding="utf-8")
        must_reject(
            lambda: MODULE.load_spec(unsafe_api_path, "https://console.fixture.example/"),
            "credential-bearing Kubernetes API URL",
        )
        must_reject(
            lambda: MODULE.render(spec_path, "https://console.fixture.example/", root / "incomplete"),
            "deployable render before exact coverage review",
        )
        inspected = MODULE.inspect_chart_action(
            spec_path, "https://console.fixture.example/", root / "discovery"
        )
        coverage = yaml.safe_load(Path(inspected["coverage_review"]).read_text(encoding="utf-8"))
        spec_document["coverage"] = coverage
        spec_path.write_text(yaml.safe_dump(spec_document), encoding="utf-8")
        for method in ("helm-cli", "galileoctl", "deployment-script", "step-by-step"):
            method_spec = yaml.safe_load(yaml.safe_dump(spec_document))
            method_spec["installation_method"] = method
            method_path = root / f"spec-{method}.yaml"
            method_path.write_text(yaml.safe_dump(method_spec), encoding="utf-8")
            method_render = MODULE.render(
                method_path,
                "https://console.fixture.example/",
                root / f"output-{method}",
            )
            MODULE.verify_bundle(Path(method_render["bundle"]))
        rendered = MODULE.render(spec_path, "https://console.fixture.example/", root / "output")
        bundle = Path(rendered["bundle"])
        MODULE.verify_bundle(bundle)
        linked_bundle = root / "linked-bundle"
        linked_bundle.symlink_to(bundle, target_is_directory=True)
        must_reject(lambda: MODULE.verify_bundle(linked_bundle), "symlink bundle root")
        inventory = json.loads((bundle / "runtime-inventory.json").read_text(encoding="utf-8"))
        assert set(inventory["observed_categories"]) == set(MODULE.RUNTIME_CATEGORIES)

        def forged_bundle(relative: str, mutate) -> Path:
            staging = root / f"forged-{relative}"
            shutil.copytree(bundle, staging)
            mutate(staging)
            digest, records = MODULE.bundle_digest(staging)
            manifest_path = staging / "bundle-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.update({"bundle_sha256": digest, "files": records})
            manifest_path.unlink()
            MODULE.write_private(manifest_path, MODULE.json_bytes(manifest))
            destination = root / digest
            staging.rename(destination)
            return destination

        def forge_environment(staging: Path) -> None:
            document = yaml.safe_load((staging / "deployment-spec.yaml").read_text(encoding="utf-8"))
            document["environment"] = "staging"
            (staging / "deployment-spec.yaml").write_bytes(MODULE.yaml_bytes(document))

        def forge_crd_mode(staging: Path) -> None:
            document = yaml.safe_load((staging / "deployment-spec.yaml").read_text(encoding="utf-8"))
            document["crds"]["mode"] = "dedicated"
            (staging / "deployment-spec.yaml").write_bytes(MODULE.yaml_bytes(document))

        def forge_inventory(staging: Path) -> None:
            (staging / "chart-inventory.json").write_text("{}\n", encoding="utf-8")

        def forge_coverage(staging: Path) -> None:
            document = yaml.safe_load((staging / "deployment-spec.yaml").read_text(encoding="utf-8"))
            document["coverage"]["reviewed_kinds"] = []
            (staging / "deployment-spec.yaml").write_bytes(MODULE.yaml_bytes(document))

        for name, mutator in (("environment", forge_environment), ("crd", forge_crd_mode), ("inventory", forge_inventory), ("coverage", forge_coverage)):
            must_reject(lambda name=name, mutator=mutator: MODULE.verify_bundle(forged_bundle(name, mutator)), f"self-rehashed {name} bundle forgery")

        bad_chart = chart_archive("custom-api-sidecar")
        must_reject(lambda: MODULE.inspect_chart(bad_chart, hashlib.sha256(bad_chart.read_bytes()).hexdigest(), "1.2.3", "galileo-stack"), "unknown dependency containing api")

        unknown_nested = root / "unknown-nested.tgz"
        nested_files = {
            "mystery/Chart.yaml": yaml.safe_dump({"apiVersion": "v2", "name": "mystery", "version": "1.0.0"}).encode(),
            "mystery/templates/hook.yaml": b"apiVersion: batch/v1\nkind: Job\nmetadata:\n  name: mystery\n  annotations:\n    helm.sh/hook: pre-install\nspec:\n  template:\n    spec:\n      containers:\n      - name: x\n        image: registry.example/x:1\n",
        }
        nested_bytes = io.BytesIO()
        with tarfile.open(fileobj=nested_bytes, mode="w:gz") as nested_handle:
            for path, data in nested_files.items():
                member = tarfile.TarInfo(path)
                member.size = len(data)
                nested_handle.addfile(member, io.BytesIO(data))
        outer_files = {
            "galileo-stack/Chart.yaml": yaml.safe_dump({"apiVersion": "v2", "name": "galileo-stack", "version": "1.2.3"}).encode(),
            "galileo-stack/charts/mystery-1.0.0.tgz": nested_bytes.getvalue(),
        }
        with tarfile.open(unknown_nested, "w:gz") as outer_handle:
            for path, data in outer_files.items():
                member = tarfile.TarInfo(path)
                member.size = len(data)
                outer_handle.addfile(member, io.BytesIO(data))
        must_reject(lambda: MODULE.inspect_chart(unknown_nested, hashlib.sha256(unknown_nested.read_bytes()).hexdigest(), "1.2.3", "galileo-stack"), "unknown nested chart kind/image/hook")

    must_reject(lambda: MODULE.assert_namespace_binding("old-uid", "new-uid"), "namespace recreation")
    MODULE.assert_namespace_binding("absent", "absent")
    assert MODULE.component_classification("api") == "stack.api"
    assert MODULE.component_classification("api-1.2.3") == "stack.api"
    assert MODULE.component_classification("custom-api-sidecar") == ""
    must_reject(lambda: MODULE.assert_upgrade_direction("9.0.0", "1.2.3"), "chart downgrade")
    must_reject(lambda: MODULE.version_key("1.2.3-rc.1"), "prerelease automated upgrade")
    assert MODULE.helm_process_timeout("120m") == 7320
    assert MODULE.helm_process_timeout("4h") == 14520
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as snapshot_temp:
        snapshot_root = Path(snapshot_temp)
        secret = snapshot_root / "secret.yaml"
        snapshot = snapshot_root / "snapshot.yaml"
        secret.write_text("password: first\n", encoding="utf-8")
        os.chmod(secret, 0o600)
        expected = MODULE.sha256_file(secret)
        secret.write_text("password: changed\n", encoding="utf-8")
        MODULE.snapshot_file(secret, snapshot, "changed secret", private=True)
        must_reject(lambda: MODULE.assert_snapshot_digest(snapshot, expected, "runtime Secret"), "Secret snapshot TOCTOU")
        empty_secret = snapshot_root / "empty-secret.yaml"
        empty_secret.write_text("{}\n", encoding="utf-8")
        os.chmod(empty_secret, 0o600)
        must_reject(lambda: MODULE.validate_runtime_secret_values(empty_secret, "empty runtime Secret"), "empty runtime Secret values")

    production_pools = {
        "environment": "production",
        "node_pools": {
            "autoscaler_validated": True,
            "cse_sizing_reference": "CSE-123",
            "production_count_exception": None,
            "pools": [
                {"role": "core", "label_value": "galileo-core", "min_nodes": 1, "max_nodes": 10, "min_cpu": "4", "min_memory": "16Gi", "min_ephemeral_storage": "100Gi", "architecture": "amd64", "failure_domains": [], "taints": []},
                {"role": "runner", "label_value": "galileo-runner", "min_nodes": 1, "max_nodes": 5, "min_cpu": "8", "min_memory": "32Gi", "min_ephemeral_storage": "200Gi", "architecture": "amd64", "failure_domains": [], "taints": []},
            ],
        },
    }

    def node(name: str, role: str, cpu: str, memory: str, disk: str) -> dict:
        return {"metadata": {"name": name, "labels": {"galileo-node-type": f"galileo-{role}", "kubernetes.io/arch": "amd64", "kubernetes.io/hostname": name}}, "spec": {"taints": []}, "status": {"conditions": [{"type": "Ready", "status": "True"}], "allocatable": {"cpu": cpu, "memory": memory, "ephemeral-storage": disk}}}

    three_node_lab_shape = {"items": [node("core-1", "core", "4", "16Gi", "100Gi"), node("core-2", "core", "4", "16Gi", "100Gi"), node("runner-1", "runner", "8", "32Gi", "200Gi")]}
    must_reject(lambda: MODULE.validate_node_pools(production_pools, three_node_lab_shape), "three-node topology as production")
    production_shape = {"items": [node(f"core-{index}", "core", "4", "16Gi", "100Gi") for index in range(1, 5)] + [node("runner-1", "runner", "8", "32Gi", "200Gi")]}
    assert MODULE.validate_node_pools(production_pools, production_shape) == {"core": 4, "runner": 1}
    retention_documents = [
        {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": {"name": "data"}},
        {"apiVersion": "apps/v1", "kind": "StatefulSet", "metadata": {"name": "db"}, "spec": {"volumeClaimTemplates": [{"metadata": {"name": "data"}}]}},
    ]
    transformed = [retain_resources.retain(document) for document in retention_documents]
    assert MODULE.validate_retention_rendered(transformed) == ["PersistentVolumeClaim/data", "StatefulSet/db"]

    storage = {
        "default_class": "retained",
        "classes": [{"name": "retained", "minimum_size_gib": 200, "reclaim_policy": "Retain", "allow_expansion": True, "snapshots": True}],
        "restore_tested": True,
    }
    claim_documents = [
        {
            "apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": {"name": "standalone"},
            "spec": {"storageClassName": "retained", "accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "200Gi"}}},
        },
        {
            "apiVersion": "apps/v1", "kind": "StatefulSet", "metadata": {"name": "db"},
            "spec": {"replicas": 2, "volumeClaimTemplates": [{"metadata": {"name": "data"}, "spec": {"storageClassName": "retained", "accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "200Gi"}}}}]},
        },
    ]
    expected_claims = MODULE.rendered_claims(claim_documents, storage, "production")

    def live_pvc(name: str, *, request: str = "200Gi", access: list[str] | None = None) -> dict:
        return {
            "metadata": {"name": name, "labels": {"app.kubernetes.io/instance": "galileo"}},
            "spec": {"storageClassName": "retained", "accessModes": access or ["ReadWriteOnce"], "resources": {"requests": {"storage": request}}},
            "status": {"phase": "Bound", "capacity": {"storage": "200Gi"}},
        }

    live_claims = {"items": [live_pvc("standalone"), live_pvc("data-db-0"), live_pvc("data-db-1")]}
    assert MODULE.validate_live_claims(live_claims, expected_claims, {"galileo"}) == ["data-db-0", "data-db-1", "standalone"]
    must_reject(lambda: MODULE.validate_live_claims({"items": live_claims["items"][:-1]}, expected_claims, {"galileo"}), "missing release PVC")
    must_reject(lambda: MODULE.validate_live_claims({"items": live_claims["items"] + [live_pvc("extra")]}, expected_claims, {"galileo"}), "unexpected release PVC")
    wrong_size = {"items": [live_pvc("standalone", request="199Gi"), live_pvc("data-db-0"), live_pvc("data-db-1")]}
    must_reject(lambda: MODULE.validate_live_claims(wrong_size, expected_claims, {"galileo"}), "wrong live PVC request")

    route_documents = [
        {
            "apiVersion": "networking.k8s.io/v1", "kind": "Ingress", "metadata": {"name": "galileo-routes", "annotations": {"nginx.ingress.kubernetes.io/proxy-read-timeout": "120"}},
            "spec": {
                "ingressClassName": "nginx",
                "tls": [
                    {"secretName": "console-tls", "hosts": ["console.fixture.example"]},
                    {"secretName": "api-tls", "hosts": ["api.fixture.example"]},
                    {"secretName": "grafana-tls", "hosts": ["grafana.fixture.example"]},
                ],
                "rules": [
                    {"host": "api.fixture.example", "http": {"paths": [{"path": "/otel/v1/traces"}, {"path": "/"}]}},
                    {"host": "console.fixture.example", "http": {"paths": [{"path": "/"}]}},
                    {"host": "grafana.fixture.example", "http": {"paths": [{"path": "/"}]}},
                ],
            },
        },
        {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "ingress-controller"}, "spec": {"type": "LoadBalancer"}},
        {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": "metrics-protection"}, "spec": {}},
    ]
    routing = {
        "console_host": "console.fixture.example", "api_host": "api.fixture.example", "grafana_host": "grafana.fixture.example",
        "tls_secret_names": ["console-tls", "api-tls", "grafana-tls"], "ingress_class": "nginx", "gateway_class": None,
        "tls_bindings": [{"host": "console.fixture.example", "secret": "console-tls"}, {"host": "api.fixture.example", "secret": "api-tls"}, {"host": "grafana.fixture.example", "secret": "grafana-tls"}],
        "load_balancer_services": ["ingress-controller"],
        "streaming_timeout_controls": [{"kind": "Ingress", "name": "galileo-routes", "annotation": "nginx.ingress.kubernetes.io/proxy-read-timeout", "minimum_seconds": 120}],
        "metrics_protection_resources": [{"kind": "NetworkPolicy", "name": "metrics-protection"}],
        "routes": ["https://api.fixture.example/otel/v1/traces", "https://console.fixture.example/", "https://grafana.fixture.example/"],
    }
    rendered_routing = MODULE.validate_rendered_routing(route_documents, routing, "production")
    assert rendered_routing["resources"] == [{"kind": "Ingress", "name": "galileo-routes"}, {"kind": "Service", "name": "ingress-controller"}]
    identities = {(item["kind"], item["name"]) for item in rendered_routing["resources"]}
    unrelated_live_route = {"metadata": {"name": "unrelated-routes", "uid": "uid", "labels": {"app.kubernetes.io/instance": "other"}}}
    assert not MODULE.release_owned_resource(unrelated_live_route, "Ingress", identities, {"galileo"})
    exact_live_route = {"metadata": {"name": "galileo-routes", "uid": "uid", "labels": {"app.kubernetes.io/instance": "galileo"}}}
    assert MODULE.release_owned_resource(exact_live_route, "Ingress", identities, {"galileo"})
    must_reject(lambda: MODULE.require_tls_key_marker(b"", "console-tls"), "TLS Secret missing tls.key")
    MODULE.require_tls_key_marker(b"present", "console-tls")
    assert MODULE.certificate_dns_name_matches("*.fixture.example", "api.fixture.example")
    assert not MODULE.certificate_dns_name_matches("*.fixture.example", "nested.api.fixture.example")

    assert '"state": "postdeploy-healthy"' not in inspect.getsource(MODULE.status)


if __name__ == "__main__":
    main()
