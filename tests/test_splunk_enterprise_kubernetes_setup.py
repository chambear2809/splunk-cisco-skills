#!/usr/bin/env python3
"""Regression tests for Splunk Enterprise Kubernetes asset rendering."""

from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
import os
import shutil
import tarfile
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT


RENDERER = (
    REPO_ROOT / "skills/splunk-enterprise-kubernetes-setup/scripts/render_assets.py"
)
VALIDATOR = REPO_ROOT / "skills/splunk-enterprise-kubernetes-setup/scripts/validate.sh"
POD_ARTIFACTS = (
    REPO_ROOT / "skills/splunk-enterprise-kubernetes-setup/scripts/pod_artifacts.py"
)


class SplunkEnterpriseKubernetesRendererTests(unittest.TestCase):
    def run_renderer(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(RENDERER), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    @staticmethod
    def embedded_renderer_code(assignment_name: str) -> str:
        tree = ast.parse(RENDERER.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if any(
                isinstance(target, ast.Name) and target.id == assignment_name
                for target in node.targets
            ):
                value = ast.literal_eval(node.value)
                if isinstance(value, str):
                    return value
        raise AssertionError(f"embedded renderer assignment not found: {assignment_name}")

    @staticmethod
    def write_app_archive(
        path: Path,
        roots: list[str],
        extras: dict[str, tuple[bytes, int]] | None = None,
        version: str | None = None,
    ) -> None:
        extras = extras or {}
        with tarfile.open(path, "w:gz") as archive:
            for root in roots:
                if f"{root}/default/app.conf" in extras:
                    continue
                launcher = f"[launcher]\nversion = {version}\n" if version else ""
                payload = f"{launcher}[package]\nid = {root}\n".encode()
                member = tarfile.TarInfo(f"{root}/default/app.conf")
                member.size = len(payload)
                member.mode = 0o644
                archive.addfile(member, io.BytesIO(payload))
            for name, (payload, mode) in extras.items():
                member = tarfile.TarInfo(name)
                member.size = len(payload)
                member.mode = mode
                archive.addfile(member, io.BytesIO(payload))

    def test_sok_s1_c3_m4_render_architecture_switches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            for architecture in ("s1", "c3", "m4"):
                output_dir = Path(tmpdir) / architecture
                result = self.run_renderer(
                    "--target",
                    "sok",
                    "--architecture",
                    architecture,
                    "--output-dir",
                    str(output_dir),
                    "--accept-splunk-general-terms",
                )
                self.assertEqual(
                    result.returncode, 0, msg=result.stdout + result.stderr
                )
                values = (output_dir / "sok" / "enterprise-values.yaml").read_text(
                    encoding="utf-8"
                )
                self.assertIn(f"  {architecture}:\n    enabled: true", values)
                if architecture == "m4":
                    self.assertIn("allSites:", values)
                if architecture == "c3":
                    self.assertIn("indexerClusters:", values)
                    self.assertIn("searchHeadClusters:", values)

    def test_sok_live_crd_contract_compares_complete_normalized_spec(self) -> None:
        contract_code = self.embedded_renderer_code("cr_contract_code")
        catalog = {
            "standalones": "Standalone",
            "clustermanagers": "ClusterManager",
            "indexerclusters": "IndexerCluster",
            "searchheadclusters": "SearchHeadCluster",
            "licensemanagers": "LicenseManager",
            "monitoringconsoles": "MonitoringConsole",
            "ingestorclusters": "IngestorCluster",
            "queues": "Queue",
            "objectstorages": "ObjectStorage",
        }

        def version(name: str, storage: bool) -> dict[str, object]:
            return {
                "name": name,
                "served": True,
                "storage": storage,
                "schema": {
                    "openAPIV3Schema": {
                        "type": "object",
                        "properties": {
                            "spec": {
                                "type": "object",
                                "properties": {
                                    "image": {"type": "string"},
                                    "replicas": {"type": "integer"},
                                },
                            },
                            "status": {"type": "object"},
                        },
                    }
                },
                "subresources": {"status": {}},
                "additionalPrinterColumns": [
                    {
                        "name": "Phase",
                        "type": "string",
                        "description": "Current phase",
                        "jsonPath": ".status.phase",
                    }
                ],
            }

        reviewed_crds = []
        live_crds = []
        for plural, kind in catalog.items():
            conversion: object = None
            if plural == "standalones":
                conversion = {
                    "strategy": "Webhook",
                    "webhook": {
                        "clientConfig": {
                            "service": {
                                "name": "webhook-service",
                                "namespace": "splunk-operator",
                                "path": "/convert",
                            }
                        },
                        "conversionReviewVersions": ["v1"],
                    },
                }
            reviewed = {
                "apiVersion": "apiextensions.k8s.io/v1",
                "kind": "CustomResourceDefinition",
                "metadata": {"name": f"{plural}.enterprise.splunk.com"},
                "spec": {
                    "group": "enterprise.splunk.com",
                    "names": {"kind": kind, "plural": plural},
                    "scope": "Namespaced",
                    "conversion": conversion,
                    "versions": [version("v3", False), version("v4", True)],
                },
            }
            live = json.loads(json.dumps(reviewed))
            live_spec = live["spec"]
            live_spec["names"]["singular"] = kind.lower()
            live_spec["names"]["listKind"] = kind + "List"
            live_spec["preserveUnknownFields"] = False
            if conversion is None:
                live_spec["conversion"] = {"strategy": "None"}
            else:
                live_spec["conversion"]["webhook"]["clientConfig"]["service"][
                    "port"
                ] = 443
            for live_version in live_spec["versions"]:
                live_version["deprecated"] = False
            live_spec["versions"].reverse()
            live["status"] = {
                "conditions": [
                    {"type": "Established", "status": "True"},
                    {"type": "NamesAccepted", "status": "True"},
                ],
                "storedVersions": ["v4"],
            }
            reviewed_crds.append(reviewed)
            live_crds.append(live)

        expected_enterprise = {
            "apiVersion": "enterprise.splunk.com/v4",
            "kind": "Standalone",
            "metadata": {"name": "s1", "namespace": "splunk"},
            "spec": {"image": "splunk/splunk:10.4.0", "replicas": 1},
        }
        live_standalone = json.loads(json.dumps(expected_enterprise))
        live_standalone["metadata"].update(
            {
                "annotations": {
                    "meta.helm.sh/release-name": "splunk-enterprise",
                    "meta.helm.sh/release-namespace": "splunk",
                },
                "generation": 1,
                "resourceVersion": "7",
                "uid": "standalone-uid",
            }
        )
        live_standalone["status"] = {
            "phase": "Ready",
            "replicas": 1,
            "readyReplicas": 1,
        }
        standalone_schema = next(
            item
            for item in reviewed_crds
            if item["metadata"]["name"] == "standalones.enterprise.splunk.com"
        )["spec"]["versions"][1]["schema"]["openAPIV3Schema"]["properties"][
            "spec"
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            expected_path = root / "expected.yaml"
            crd_path = root / "crds.yaml"
            live_path = root / "live.json"
            expected_path.write_text(json.dumps(expected_enterprise), encoding="utf-8")
            crd_path.write_text(
                json.dumps({"apiVersion": "v1", "kind": "List", "items": reviewed_crds}),
                encoding="utf-8",
            )

            def run_contract(
                candidate_crds: list[dict[str, object]],
            ) -> subprocess.CompletedProcess:
                live_path.write_text(
                    json.dumps(
                        {
                            "items": [live_standalone],
                            "schemas": {"Standalone": standalone_schema},
                            "crds": candidate_crds,
                        }
                    ),
                    encoding="utf-8",
                )
                return subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        contract_code,
                        str(expected_path),
                        str(live_path),
                        str(crd_path),
                        "splunk-enterprise",
                        "splunk",
                        "",
                        "",
                    ],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )

            accepted = run_contract(live_crds)
            self.assertEqual(
                accepted.returncode, 0, msg=accepted.stdout + accepted.stderr
            )

            def mutated_live() -> list[dict[str, object]]:
                return json.loads(json.dumps(live_crds))

            drift_cases = {
                "conversion": lambda spec: spec["conversion"].update(
                    {"strategy": "None"}
                ),
                "preserveUnknownFields": lambda spec: spec.update(
                    {"preserveUnknownFields": True}
                ),
                "subresources": lambda spec: next(
                    item for item in spec["versions"] if item["name"] == "v4"
                )["subresources"].update(
                    {
                        "scale": {
                            "specReplicasPath": ".spec.replicas",
                            "statusReplicasPath": ".status.replicas",
                        }
                    }
                ),
                "additionalPrinterColumns": lambda spec: next(
                    item for item in spec["versions"] if item["name"] == "v4"
                )["additionalPrinterColumns"][0].update(
                    {"jsonPath": ".status.message"}
                ),
                "deprecated": lambda spec: next(
                    item for item in spec["versions"] if item["name"] == "v4"
                ).update({"deprecated": True}),
                "deprecationWarning": lambda spec: next(
                    item for item in spec["versions"] if item["name"] == "v4"
                ).update({"deprecationWarning": "use another version"}),
                "selectableFields": lambda spec: next(
                    item for item in spec["versions"] if item["name"] == "v4"
                ).update({"selectableFields": [{"jsonPath": ".spec.image"}]}),
            }
            for field, mutate in drift_cases.items():
                with self.subTest(field=field):
                    candidate = mutated_live()
                    standalone = next(
                        item
                        for item in candidate
                        if item["metadata"]["name"]
                        == "standalones.enterprise.splunk.com"
                    )
                    mutate(standalone["spec"])
                    rejected = run_contract(candidate)
                    self.assertNotEqual(rejected.returncode, 0)
                    self.assertIn(field, rejected.stderr)

            for status_field in ("Established", "NamesAccepted", "storedVersions"):
                with self.subTest(status_field=status_field):
                    candidate = mutated_live()
                    standalone = next(
                        item
                        for item in candidate
                        if item["metadata"]["name"]
                        == "standalones.enterprise.splunk.com"
                    )
                    if status_field == "storedVersions":
                        standalone["status"]["storedVersions"] = ["v99"]
                    else:
                        condition = next(
                            item
                            for item in standalone["status"]["conditions"]
                            if item["type"] == status_field
                        )
                        condition["status"] = "False"
                    rejected = run_contract(candidate)
                    self.assertNotEqual(rejected.returncode, 0)
                    self.assertIn("not established", rejected.stderr)

            live_standalone["metadata"]["annotations"][
                "enterprise.splunk.com/admin-managed-pv"
            ] = "true"
            rejected_admin_pv = run_contract(live_crds)
            self.assertNotEqual(rejected_admin_pv.returncode, 0)
            self.assertIn("admin-managed PVs", rejected_admin_pv.stderr)
            live_standalone["metadata"]["annotations"].pop(
                "enterprise.splunk.com/admin-managed-pv"
            )

    def test_sok_upgrade_requires_one_deployed_helm_release(self) -> None:
        guard = self.embedded_renderer_code("upgrade_guard_code")

        def check(rows: list[dict[str, str]]) -> subprocess.CompletedProcess:
            return subprocess.run(
                [
                    sys.executable,
                    "-c",
                    guard,
                    "splunk-enterprise",
                    "3.1.0",
                    "splunk-enterprise",
                    "splunk-operator",
                ],
                input=json.dumps(rows),
                capture_output=True,
                text=True,
                check=False,
            )

        base = {
            "name": "splunk-enterprise",
            "namespace": "splunk-operator",
            "status": "deployed",
            "chart": "splunk-enterprise-3.0.0",
        }
        self.assertEqual(check([base]).returncode, 0)
        self.assertNotEqual(check([]).returncode, 0)
        for mutation in (
            {"status": "pending-upgrade"},
            {"status": "failed"},
            {"namespace": "other"},
        ):
            with self.subTest(mutation=mutation):
                self.assertNotEqual(check([{**base, **mutation}]).returncode, 0)
        self.assertNotEqual(check([base, base]).returncode, 0)

    def test_sok_service_and_placement_live_contracts(self) -> None:
        controller_guard = self.embedded_renderer_code("controller_health_code")
        pod_guard = self.embedded_renderer_code("pod_health_code")
        service_guard = self.embedded_renderer_code("service_health_code")
        pvc_guard = self.embedded_renderer_code("pvc_health_code")
        placement_guard = self.embedded_renderer_code("placement_health_code")
        license_event_guard = self.embedded_renderer_code("license_event_code")
        contracts = [
            {
                "name": "splunk-cm-cluster-manager",
                "count": 1,
                "owner_kind": "ClusterManager",
                "owner_name": "cm",
            },
            {
                "name": "splunk-idxc-indexer",
                "count": 3,
                "owner_kind": "IndexerCluster",
                "owner_name": "idxc",
            },
        ]
        statefulsets = {
            "items": [
                {
                    "metadata": {
                        "name": contract["name"],
                        "generation": 3,
                        "uid": f"{contract['name']}-uid",
                        "ownerReferences": [
                            {
                                "apiVersion": "enterprise.splunk.com/v4",
                                "kind": contract["owner_kind"],
                                "name": contract["owner_name"],
                                "controller": True,
                                "uid": f"{contract['owner_name']}-uid",
                            }
                        ],
                    },
                    "spec": {
                        "replicas": contract["count"],
                        "serviceName": f"{contract['name']}-headless",
                        "podManagementPolicy": "Parallel",
                        "updateStrategy": {"type": "OnDelete"},
                        "selector": {
                            "matchLabels": {
                                "app.kubernetes.io/instance": contract["name"]
                            }
                        },
                        "template": {
                            "metadata": {
                                "labels": {
                                    "app.kubernetes.io/instance": contract["name"]
                                }
                            },
                            "spec": {
                                "affinity": {
                                    "podAntiAffinity": {
                                        "preferredDuringSchedulingIgnoredDuringExecution": [
                                            {
                                                "weight": 100,
                                                "podAffinityTerm": {
                                                    "labelSelector": {
                                                        "matchExpressions": [
                                                            {
                                                                "key": "app.kubernetes.io/instance",
                                                                "operator": "In",
                                                                "values": [
                                                                    contract["name"]
                                                                ],
                                                            }
                                                        ]
                                                    },
                                                    "topologyKey": (
                                                        "kubernetes.io/hostname"
                                                    ),
                                                },
                                            }
                                        ]
                                    }
                                },
                                "schedulerName": "default-scheduler",
                                "securityContext": {
                                    "fsGroup": 41812,
                                    "fsGroupChangePolicy": "OnRootMismatch",
                                    "runAsNonRoot": True,
                                    "runAsUser": 41812,
                                },
                                "containers": [
                                    {"name": "splunk", "image": "splunk:10.4.0"}
                                ]
                            },
                        },
                        "volumeClaimTemplates": [
                            {
                                "metadata": {
                                    "name": claim,
                                    "labels": {
                                        "app.kubernetes.io/instance": contract["name"]
                                    },
                                },
                                "spec": {
                                    "accessModes": ["ReadWriteOnce"],
                                    "volumeMode": "Filesystem",
                                    "storageClassName": "gp3",
                                    "resources": {
                                        "requests": {
                                            "storage": (
                                                "10Gi" if claim == "pvc-etc" else "100Gi"
                                            )
                                        }
                                    },
                                },
                            }
                            for claim in ("pvc-etc", "pvc-var")
                        ],
                    },
                    "status": {
                        "observedGeneration": 3,
                        "currentReplicas": contract["count"],
                        "updatedReplicas": contract["count"],
                        "readyReplicas": contract["count"],
                        "availableReplicas": contract["count"],
                        "currentRevision": "rev-1",
                        "updateRevision": "rev-1",
                    },
                }
                for contract in contracts
            ]
        }
        custom_resources = {
            "items": [
                {
                    "apiVersion": "enterprise.splunk.com/v4",
                    "kind": contract["owner_kind"],
                    "metadata": {
                        "name": contract["owner_name"],
                        "uid": f"{contract['owner_name']}-uid",
                    },
                    "spec": {
                        "livenessInitialDelaySeconds": 300,
                        "readinessInitialDelaySeconds": 10,
                        "resources": {
                            "requests": {"cpu": "1", "memory": "1Gi"},
                            "limits": {"cpu": "1", "memory": "1Gi"},
                        }
                    },
                }
                for contract in contracts
            ]
        }
        for resource in custom_resources["items"]:
            if resource["kind"] == "IndexerCluster":
                resource["spec"]["clusterManagerRef"] = {"name": "cm"}
                resource["spec"]["affinity"] = {
                    "nodeAffinity": {
                        "requiredDuringSchedulingIgnoredDuringExecution": {
                            "nodeSelectorTerms": [
                                {
                                    "matchExpressions": [
                                        {
                                            "key": "workload",
                                            "operator": "In",
                                            "values": ["splunk"],
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                }
                resource["spec"]["tolerations"] = [
                    {
                        "key": "workload",
                        "operator": "Equal",
                        "value": "splunk",
                        "effect": "NoSchedule",
                    }
                ]
                resource["spec"]["topologySpreadConstraints"] = [
                    {
                        "maxSkew": 1,
                        "topologyKey": "topology.kubernetes.io/zone",
                        "whenUnsatisfiable": "ScheduleAnyway",
                        "labelSelector": {
                            "matchLabels": {"app": "splunk-indexer"}
                        },
                    }
                ]
            elif resource["kind"] == "ClusterManager":
                resource["status"] = {
                    "bundlePushInfo": {"needToPushManagerApps": False}
                }
                resource["spec"]["smartstore"] = {
                    "defaults": {"volumeName": "remote_store"},
                    "indexes": [
                        {
                            "name": "main",
                            "remotePath": "$_index_name",
                            "volumeName": "remote_store",
                        }
                    ],
                    "volumes": [
                        {
                            "name": "remote_store",
                            "path": "splunk-test/indexes",
                            "endpoint": "https://s3.us-east-1.amazonaws.com",
                            "region": "us-east-1",
                            "secretRef": "smartstore-credentials",
                        }
                    ],
                }
                resource["spec"]["appRepo"] = {
                    "appSources": [{"name": "cluster-apps"}]
                }
                resource["spec"]["defaults"] = (
                    "splunk:\n"
                    "  site: site1\n"
                    "  multisite_master: localhost\n"
                    "  all_sites: site1,site2\n"
                )
                statefulsets["items"][0]["spec"]["template"]["metadata"][
                    "annotations"
                ] = {"defaultConfigRev": "12"}
        indexer_spec = custom_resources["items"][1]["spec"]
        indexer_pod_spec = statefulsets["items"][1]["spec"]["template"]["spec"]
        indexer_pod_spec["affinity"]["nodeAffinity"] = json.loads(
            json.dumps(indexer_spec["affinity"]["nodeAffinity"])
        )
        indexer_pod_spec["tolerations"] = json.loads(
            json.dumps(indexer_spec["tolerations"])
        )
        indexer_pod_spec["topologySpreadConstraints"] = json.loads(
            json.dumps(indexer_spec["topologySpreadConstraints"])
        )
        role_by_suffix = {
            "cluster-manager": "splunk_cluster_master",
            "indexer": "splunk_indexer",
        }
        for stateful in statefulsets["items"]:
            role_suffix = (
                "cluster-manager"
                if stateful["metadata"]["name"].endswith("-cluster-manager")
                else "indexer"
            )
            port_values = {
                "http-splunkweb": 8000,
                "https-splunkd": 8089,
            }
            if role_suffix == "indexer":
                port_values.update({"http-hec": 8088, "tcp-s2s": 9997})
            container = stateful["spec"]["template"]["spec"]["containers"][0]
            container.update(
                {
                    "ports": [
                        {
                            "name": port_name,
                            "containerPort": port,
                            "protocol": "TCP",
                        }
                        for port_name, port in sorted(port_values.items())
                    ],
                    "env": [
                        {"name": "SPLUNK_HOME", "value": "/opt/splunk"},
                        {"name": "SPLUNK_START_ARGS", "value": "--accept-license"},
                        {
                            "name": "SPLUNK_DEFAULTS_URL",
                            "value": "/mnt/splunk-secrets/default.yml",
                        },
                        {
                            "name": "SPLUNK_HOME_OWNERSHIP_ENFORCEMENT",
                            "value": "false",
                        },
                        {
                            "name": "SPLUNK_ROLE",
                            "value": role_by_suffix[role_suffix],
                        },
                        {
                            "name": "SPLUNK_DECLARATIVE_ADMIN_PASSWORD",
                            "value": "true",
                        },
                        {
                            "name": "SPLUNK_OPERATOR_K8_LIVENESS_DRIVER_FILE_PATH",
                            "value": "/tmp/splunk_operator_k8s/probes/k8_liveness_driver.sh",
                        },
                        {
                            "name": "SPLUNK_GENERAL_TERMS",
                            "value": "--accept-sgt-current-at-splunk-com",
                        },
                        {
                            "name": "SPLUNK_SKIP_CLUSTER_BUNDLE_PUSH",
                            "value": "true",
                        },
                    ],
                    "resources": {
                        "requests": {"cpu": "1", "memory": "1Gi"},
                        "limits": {"cpu": "1", "memory": "1Gi"},
                    },
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "capabilities": {
                            "add": ["NET_BIND_SERVICE"],
                            "drop": ["ALL"],
                        },
                        "privileged": False,
                        "runAsNonRoot": True,
                        "runAsUser": 41812,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "volumeMounts": [
                        {"name": "pvc-etc", "mountPath": "/opt/splunk/etc"},
                        {"name": "pvc-var", "mountPath": "/opt/splunk/var"},
                        {
                            "name": "splunk-splunk-probe-configmap",
                            "mountPath": "/mnt/probes",
                        },
                        {
                            "name": "mnt-splunk-secrets",
                            "mountPath": "/mnt/splunk-secrets",
                        },
                    ],
                }
            )
            if role_suffix == "cluster-manager":
                container["env"].insert(
                    0,
                    {"name": "SPLUNK_CLUSTER_MASTER_URL", "value": "localhost"},
                )
                container["env"].insert(
                    1, {"name": "SPLUNK_SITE", "value": "site0"}
                )
                container["env"].insert(
                    2,
                    {
                        "name": "SPLUNK_MULTISITE_MASTER",
                        "value": "splunk-cm-cluster-manager-service",
                    },
                )
                for env_item in container["env"]:
                    if env_item["name"] == "SPLUNK_DEFAULTS_URL":
                        env_item["value"] = (
                            "/mnt/splunk-defaults/default.yml,"
                            "/mnt/splunk-secrets/default.yml"
                        )
            else:
                container["env"].insert(
                    0,
                    {
                        "name": "SPLUNK_CLUSTER_MASTER_URL",
                        "value": "splunk-cm-cluster-manager-service",
                    },
                )
            for probe_name, script_name in (
                ("livenessProbe", "livenessProbe.sh"),
                ("readinessProbe", "readinessProbe.sh"),
                ("startupProbe", "startupProbe.sh"),
            ):
                container[probe_name] = {
                    "exec": {"command": [f"/mnt/probes/{script_name}"]},
                    "initialDelaySeconds": (
                        300
                        if probe_name == "livenessProbe"
                        else 10
                        if probe_name == "readinessProbe"
                        else 40
                    ),
                    "timeoutSeconds": 5,
                    "periodSeconds": 5,
                    "failureThreshold": (
                        12 if probe_name == "startupProbe" else 3
                    ),
                }
                if probe_name in {"livenessProbe", "startupProbe"}:
                    container[probe_name]["timeoutSeconds"] = 30
                    container[probe_name]["periodSeconds"] = 30
            stateful["spec"]["template"]["spec"]["volumes"] = [
                {
                    "name": "splunk-splunk-probe-configmap",
                    "configMap": {"name": "splunk-splunk-probe-configmap"},
                },
                {
                    "name": "mnt-splunk-secrets",
                    "secret": {
                        "secretName": f"{stateful['metadata']['name']}-secret-v1"
                    },
                },
            ]
            if role_suffix == "cluster-manager":
                container["volumeMounts"].append(
                    {
                        "name": "mnt-splunk-operator",
                        "mountPath": "/mnt/splunk-operator/local/",
                    }
                )
                container["volumeMounts"].append(
                    {
                        "name": "mnt-splunk-defaults",
                        "mountPath": "/mnt/splunk-defaults",
                    }
                )
                container["volumeMounts"].append(
                    {
                        "name": "operator-staging",
                        "mountPath": "/operator-staging/",
                    }
                )
                stateful["spec"]["template"]["spec"]["volumes"].append(
                    {
                        "name": "mnt-splunk-operator",
                        "configMap": {
                            "name": "splunk-cm-clustermanager-smartstore",
                            "defaultMode": 420,
                            "items": [
                                {
                                    "key": item,
                                    "path": item,
                                    "mode": 420,
                                }
                                for item in (
                                    "indexes.conf",
                                    "server.conf",
                                    "conftoken",
                                )
                            ],
                        },
                    }
                )
                stateful["spec"]["template"]["spec"]["volumes"].append(
                    {"name": "operator-staging", "emptyDir": {}}
                )
                stateful["spec"]["template"]["spec"]["volumes"].append(
                    {
                        "name": "mnt-splunk-defaults",
                        "configMap": {
                            "name": "splunk-cm-indexer-defaults",
                            "defaultMode": 420,
                        },
                    }
                )
                stateful["spec"]["template"]["spec"]["initContainers"] = [
                    {
                        "name": "init",
                        "image": "splunk:10.4.0",
                        "imagePullPolicy": "IfNotPresent",
                        "command": [
                            "bash",
                            "-c",
                            "mkdir -p /opt/splk/etc/manager-apps/"
                            "splunk-operator/local && ln -sfn "
                            "/mnt/splunk-operator/local/indexes.conf "
                            "/opt/splk/etc/manager-apps/splunk-operator/local/"
                            "indexes.conf && ln -sfn "
                            "/mnt/splunk-operator/local/server.conf "
                            "/opt/splk/etc/manager-apps/splunk-operator/local/"
                            "server.conf",
                        ],
                        "volumeMounts": [
                            {"name": "pvc-etc", "mountPath": "/opt/splk/etc"}
                        ],
                        "resources": {
                            "requests": {"cpu": "250m", "memory": "128Mi"},
                            "limits": {"cpu": "1", "memory": "512Mi"},
                        },
                        "securityContext": json.loads(
                            json.dumps(container["securityContext"])
                        ),
                    }
                ]
        probe_data = {
            "livenessProbe.sh": "#!/bin/sh\nexit 0\n",
            "readinessProbe.sh": "#!/bin/sh\nexit 0\n",
            "startupProbe.sh": "#!/bin/sh\nexit 0\n",
        }
        probe_hashes = {
            name: hashlib.sha256(value.encode("utf-8")).hexdigest()
            for name, value in probe_data.items()
        }
        probe_config_map = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "splunk-splunk-probe-configmap",
                "namespace": "splunk",
                "uid": "probe-configmap-uid",
            },
            "data": probe_data,
        }
        owner_reference = {
            "apiVersion": "enterprise.splunk.com/v4",
            "kind": "ClusterManager",
            "name": "cm",
            "uid": "cm-uid",
            "controller": True,
        }
        defaults_config_map = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "splunk-cm-indexer-defaults",
                "namespace": "splunk",
                "uid": "defaults-configmap-uid",
                "resourceVersion": "12",
                "ownerReferences": [owner_reference],
            },
            "data": {
                "default.yml": custom_resources["items"][0]["spec"]["defaults"]
            },
        }
        smartstore_access_key = "test-access-key"
        smartstore_secret_key = "test-secret-key"
        smartstore_indexes = (
            "[default]\n"
            "repFactor = auto\n"
            "maxDataSize = auto\n"
            "homePath = $SPLUNK_DB/$_index_name/db\n"
            "coldPath = $SPLUNK_DB/$_index_name/colddb\n"
            "thawedPath = $SPLUNK_DB/$_index_name/thaweddb\n"
            "remotePath = volume:remote_store/$_index_name\n"
            " \n"
            "[volume:remote_store]\n"
            "storageType = remote\n"
            "path = s3://splunk-test/indexes\n"
            f"remote.s3.access_key = {smartstore_access_key}\n"
            f"remote.s3.secret_key = {smartstore_secret_key}\n"
            "remote.s3.endpoint = https://s3.us-east-1.amazonaws.com\n"
            "remote.s3.auth_region = us-east-1\n"
            " \n"
            "[main]\n"
            "remotePath = volume:remote_store/$_index_name\n"
        )
        smartstore_config_map = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "splunk-cm-clustermanager-smartstore",
                "namespace": "splunk",
                "uid": "smartstore-configmap-uid",
                "resourceVersion": "13",
                "ownerReferences": [owner_reference],
            },
            "data": {
                "indexes.conf": smartstore_indexes,
                "server.conf": "",
                "conftoken": "1700000000",
            },
        }
        license_bytes = b"test-license-content\n"
        license_config_map = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "splunk-licenses",
                "namespace": "splunk",
                "uid": "license-configmap-uid",
                "resourceVersion": "14",
            },
            "data": {"splunk.lic": license_bytes.decode("utf-8")},
        }
        config_maps = {
            "items": [
                probe_config_map,
                defaults_config_map,
                smartstore_config_map,
                license_config_map,
            ]
        }
        smartstore_secret = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": "smartstore-credentials",
                "namespace": "splunk",
                "uid": "smartstore-secret-uid",
                "resourceVersion": "17",
            },
            "data": {
                "s3_access_key": base64.b64encode(
                    smartstore_access_key.encode("utf-8")
                ).decode("ascii"),
                "s3_secret_key": base64.b64encode(
                    smartstore_secret_key.encode("utf-8")
                ).decode("ascii"),
            },
        }
        controller_command = [
            sys.executable,
            "-c",
            controller_guard,
            json.dumps(contracts),
            "splunk:10.4.0",
            json.dumps(probe_hashes),
            "splunk",
            "--accept-sgt-current-at-splunk-com",
            json.dumps(
                {
                    "name": "splunk.lic",
                    "sha256": hashlib.sha256(license_bytes).hexdigest(),
                }
            ),
        ]

        def controller_input(candidate: dict[str, object]) -> str:
            return "\n".join(
                json.dumps(value)
                for value in (
                    candidate,
                    custom_resources,
                    config_maps,
                    smartstore_secret,
                )
            )

        controllers_healthy = subprocess.run(
            controller_command,
            input=controller_input(statefulsets),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            controllers_healthy.returncode, 0, msg=controllers_healthy.stderr
        )
        semantically_equal_resources = json.loads(json.dumps(statefulsets))
        semantically_equal_resources["items"][0]["spec"]["template"]["spec"][
            "containers"
        ][0]["resources"]["requests"]["cpu"] = "1000m"
        accepted_resources = subprocess.run(
            controller_command,
            input=controller_input(semantically_equal_resources),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            accepted_resources.returncode, 0, msg=accepted_resources.stderr
        )
        malformed_resources = json.loads(json.dumps(statefulsets))
        malformed_resources["items"][0]["spec"]["template"]["spec"][
            "containers"
        ][0]["resources"]["requests"]["cpu"] = "1K"
        rejected_resources = subprocess.run(
            controller_command,
            input=controller_input(malformed_resources),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(rejected_resources.returncode, 0)
        for mutation in (
            ("updateStrategy", {"type": "RollingUpdate"}),
            ("podManagementPolicy", "OrderedReady"),
            (
                "persistentVolumeClaimRetentionPolicy",
                {"whenDeleted": "Delete", "whenScaled": "Retain"},
            ),
        ):
            drifted_statefulsets = json.loads(json.dumps(statefulsets))
            drifted_statefulsets["items"][0]["spec"][mutation[0]] = mutation[1]
            rejected_controller = subprocess.run(
                controller_command,
                input=controller_input(drifted_statefulsets),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(rejected_controller.returncode, 0)
        for drift_index, drifted_statefulsets in enumerate(
            (
                json.loads(json.dumps(statefulsets)),
                json.loads(json.dumps(statefulsets)),
            )
        ):
            if drift_index == 0:
                drifted_statefulsets["items"][0]["metadata"]["ownerReferences"][0][
                    "uid"
                ] = "wrong-uid"
            else:
                drifted_statefulsets["items"][0]["status"]["availableReplicas"] = 0
            rejected_controller = subprocess.run(
                controller_command,
                input=controller_input(drifted_statefulsets),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(rejected_controller.returncode, 0)
        unsafe_statefulsets = []
        injected_sidecar = json.loads(json.dumps(statefulsets))
        injected_sidecar["items"][0]["spec"]["template"]["spec"][
            "containers"
        ].append({"name": "injected", "image": "sidecar:latest"})
        unsafe_statefulsets.append(injected_sidecar)
        added_capability = json.loads(json.dumps(statefulsets))
        added_capability["items"][0]["spec"]["template"]["spec"]["containers"][
            0
        ]["securityContext"] = {"capabilities": {"add": ["SYS_ADMIN"]}}
        unsafe_statefulsets.append(added_capability)
        injected_env_from = json.loads(json.dumps(statefulsets))
        injected_env_from["items"][0]["spec"]["template"]["spec"]["containers"][
            0
        ]["envFrom"] = [{"secretRef": {"name": "attacker-env"}}]
        unsafe_statefulsets.append(injected_env_from)
        injected_environment = json.loads(json.dumps(statefulsets))
        injected_environment["items"][0]["spec"]["template"]["spec"][
            "containers"
        ][0]["env"].append({"name": "LD_PRELOAD", "value": "/tmp/evil.so"})
        unsafe_statefulsets.append(injected_environment)
        changed_terms = json.loads(json.dumps(statefulsets))
        for env_item in changed_terms["items"][0]["spec"]["template"]["spec"][
            "containers"
        ][0]["env"]:
            if env_item.get("name") == "SPLUNK_GENERAL_TERMS":
                env_item["value"] = ""
        unsafe_statefulsets.append(changed_terms)
        lifecycle_hook = json.loads(json.dumps(statefulsets))
        lifecycle_hook["items"][0]["spec"]["template"]["spec"]["containers"][
            0
        ]["lifecycle"] = {"postStart": {"exec": {"command": ["/tmp/evil"]}}}
        unsafe_statefulsets.append(lifecycle_hook)
        disabled_probe = json.loads(json.dumps(statefulsets))
        disabled_probe["items"][0]["spec"]["template"]["spec"]["containers"][0][
            "livenessProbe"
        ]["periodSeconds"] = 2_147_483_647
        disabled_probe["items"][0]["spec"]["template"]["spec"]["containers"][0][
            "livenessProbe"
        ]["failureThreshold"] = 2_147_483_647
        unsafe_statefulsets.append(disabled_probe)
        ungraceful_shutdown = json.loads(json.dumps(statefulsets))
        ungraceful_shutdown["items"][0]["spec"]["template"]["spec"][
            "terminationGracePeriodSeconds"
        ] = 0
        unsafe_statefulsets.append(ungraceful_shutdown)
        for scheduling_field in (
            "affinity",
            "tolerations",
            "topologySpreadConstraints",
        ):
            missing_scheduling = json.loads(json.dumps(statefulsets))
            missing_scheduling["items"][1]["spec"]["template"]["spec"].pop(
                scheduling_field, None
            )
            unsafe_statefulsets.append(missing_scheduling)
        overlapping_mount = json.loads(json.dumps(statefulsets))
        overlapping_mount["items"][0]["spec"]["template"]["spec"]["containers"][
            0
        ]["volumeMounts"].append(
            {
                "name": "injected-config",
                "mountPath": "/opt/splunk/etc/system/local",
            }
        )
        overlapping_mount["items"][0]["spec"]["template"]["spec"][
            "volumes"
        ].append(
            {"name": "injected-config", "configMap": {"name": "injected"}}
        )
        unsafe_statefulsets.append(overlapping_mount)
        executable_mount = json.loads(json.dumps(statefulsets))
        executable_mount["items"][0]["spec"]["template"]["spec"]["containers"][
            0
        ]["volumeMounts"].append(
            {
                "name": "injected-bin",
                "mountPath": "/opt/splunk/bin",
            }
        )
        executable_mount["items"][0]["spec"]["template"]["spec"][
            "volumes"
        ].append({"name": "injected-bin", "configMap": {"name": "injected"}})
        unsafe_statefulsets.append(executable_mount)
        remote_defaults = json.loads(json.dumps(statefulsets))
        for env_item in remote_defaults["items"][0]["spec"]["template"]["spec"][
            "containers"
        ][0]["env"]:
            if env_item.get("name") == "SPLUNK_DEFAULTS_URL":
                env_item["value"] = (
                    "https://attacker.invalid/default.yml,"
                    "/mnt/splunk-secrets/default.yml"
                )
        unsafe_statefulsets.append(remote_defaults)
        missing_probe = json.loads(json.dumps(statefulsets))
        missing_probe["items"][0]["spec"]["template"]["spec"]["containers"][
            0
        ].pop("readinessProbe")
        unsafe_statefulsets.append(missing_probe)
        substituted_probe_source = json.loads(json.dumps(statefulsets))
        substituted_probe_source["items"][0]["spec"]["template"]["spec"][
            "volumes"
        ][0]["configMap"]["name"] = "attacker-probes"
        unsafe_statefulsets.append(substituted_probe_source)
        substituted_secret = json.loads(json.dumps(statefulsets))
        substituted_secret["items"][0]["spec"]["template"]["spec"]["volumes"][
            1
        ]["secret"]["secretName"] = "attacker-secret"
        unsafe_statefulsets.append(substituted_secret)
        tampered_smartstore_init = json.loads(json.dumps(statefulsets))
        tampered_smartstore_init["items"][0]["spec"]["template"]["spec"][
            "initContainers"
        ][0]["command"] = ["bash", "-c", "touch /tmp/pwned"]
        unsafe_statefulsets.append(tampered_smartstore_init)
        tampered_smartstore_volume = json.loads(json.dumps(statefulsets))
        for volume in tampered_smartstore_volume["items"][0]["spec"]["template"][
            "spec"
        ]["volumes"]:
            if volume.get("name") == "mnt-splunk-operator":
                volume["configMap"]["name"] = "attacker-smartstore"
        unsafe_statefulsets.append(tampered_smartstore_volume)
        tampered_app_staging = json.loads(json.dumps(statefulsets))
        for volume in tampered_app_staging["items"][0]["spec"]["template"]["spec"][
            "volumes"
        ]:
            if volume.get("name") == "operator-staging":
                volume.pop("emptyDir")
                volume["secret"] = {"secretName": "attacker-apps"}
        unsafe_statefulsets.append(tampered_app_staging)
        for unsafe_stateful in unsafe_statefulsets:
            rejected_workload = subprocess.run(
                controller_command,
                input=controller_input(unsafe_stateful),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(rejected_workload.returncode, 0)
        tampered_probe_config = json.loads(json.dumps(probe_config_map))
        tampered_probe_config["data"]["readinessProbe.sh"] = "#!/bin/sh\nexit 1\n"
        rejected_probe_content = subprocess.run(
            controller_command,
            input="\n".join(
                json.dumps(value)
                for value in (
                    statefulsets,
                    custom_resources,
                    {
                        "items": [
                            tampered_probe_config,
                            defaults_config_map,
                            smartstore_config_map,
                            license_config_map,
                        ]
                    },
                    smartstore_secret,
                )
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(rejected_probe_content.returncode, 0)
        for config_name, data_key in (
            ("splunk-cm-indexer-defaults", "default.yml"),
            ("splunk-cm-clustermanager-smartstore", "indexes.conf"),
        ):
            tampered_maps = json.loads(json.dumps(config_maps))
            for config_map in tampered_maps["items"]:
                if config_map["metadata"]["name"] == config_name:
                    config_map["data"][data_key] += "\n# tampered"
            rejected_config_data = subprocess.run(
                controller_command,
                input="\n".join(
                    json.dumps(value)
                    for value in (
                        statefulsets,
                        custom_resources,
                        tampered_maps,
                        smartstore_secret,
                    )
                ),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(rejected_config_data.returncode, 0)
        stale_config_maps = json.loads(json.dumps(config_maps))
        for config_map in stale_config_maps["items"]:
            if config_map["metadata"]["name"] == "splunk-cm-indexer-defaults":
                config_map["metadata"]["resourceVersion"] = "99"
        rejected_stale_defaults = subprocess.run(
            controller_command,
            input="\n".join(
                json.dumps(value)
                for value in (
                    statefulsets,
                    custom_resources,
                    stale_config_maps,
                    smartstore_secret,
                )
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(rejected_stale_defaults.returncode, 0)
        tampered_license_maps = json.loads(json.dumps(config_maps))
        for config_map in tampered_license_maps["items"]:
            if config_map["metadata"]["name"] == "splunk-licenses":
                config_map["data"]["splunk.lic"] = "changed-license\n"
        rejected_license_content = subprocess.run(
            controller_command,
            input="\n".join(
                json.dumps(value)
                for value in (
                    statefulsets,
                    custom_resources,
                    tampered_license_maps,
                    smartstore_secret,
                )
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(rejected_license_content.returncode, 0)
        pending_bundle_resources = json.loads(json.dumps(custom_resources))
        pending_bundle_resources["items"][0]["status"]["bundlePushInfo"][
            "needToPushManagerApps"
        ] = True
        rejected_pending_bundle = subprocess.run(
            controller_command,
            input="\n".join(
                json.dumps(value)
                for value in (
                    statefulsets,
                    pending_bundle_resources,
                    config_maps,
                    smartstore_secret,
                )
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(rejected_pending_bundle.returncode, 0)
        tampered_smartstore_secret = json.loads(json.dumps(smartstore_secret))
        tampered_smartstore_secret["data"]["s3_secret_key"] = base64.b64encode(
            b"changed-secret-key"
        ).decode("ascii")
        rejected_secret_data = subprocess.run(
            controller_command,
            input="\n".join(
                json.dumps(value)
                for value in (
                    statefulsets,
                    custom_resources,
                    config_maps,
                    tampered_smartstore_secret,
                )
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(rejected_secret_data.returncode, 0)
        runtime_pods = {"items": []}
        for contract, stateful in zip(contracts, statefulsets["items"]):
            for ordinal in range(contract["count"]):
                pod_spec = json.loads(
                    json.dumps(stateful["spec"]["template"]["spec"])
                )
                pod_spec["nodeName"] = f"runtime-node-{ordinal}"
                pod_spec["volumes"].extend(
                    {
                        "name": claim,
                        "persistentVolumeClaim": {
                            "claimName": f"{claim}-{contract['name']}-{ordinal}"
                        },
                    }
                    for claim in ("pvc-etc", "pvc-var")
                )
                kube_api_name = f"kube-api-access-{ordinal:05d}"
                pod_spec["volumes"].append(
                    {
                        "name": kube_api_name,
                        "projected": {
                            "defaultMode": 420,
                            "sources": [
                                {
                                    "serviceAccountToken": {
                                        "expirationSeconds": 3607,
                                        "path": "token",
                                    }
                                },
                                {
                                    "configMap": {
                                        "name": "kube-root-ca.crt",
                                        "items": [
                                            {"key": "ca.crt", "path": "ca.crt"}
                                        ],
                                    }
                                },
                                {
                                    "downwardAPI": {
                                        "items": [
                                            {
                                                "path": "namespace",
                                                "fieldRef": {
                                                    "apiVersion": "v1",
                                                    "fieldPath": "metadata.namespace",
                                                },
                                            }
                                        ]
                                    }
                                },
                            ],
                        },
                    }
                )
                for container in [
                    *pod_spec.get("containers", []),
                    *pod_spec.get("initContainers", []),
                ]:
                    container.setdefault("volumeMounts", []).append(
                        {
                            "name": kube_api_name,
                            "readOnly": True,
                            "mountPath": (
                                "/var/run/secrets/kubernetes.io/serviceaccount"
                            ),
                        }
                    )
                init_statuses = [
                    {
                        "name": init["name"],
                        "image": init["image"],
                        "imageID": "docker-pullable://splunk@sha256:init",
                        "state": {"terminated": {"exitCode": 0}},
                    }
                    for init in pod_spec.get("initContainers", [])
                ]
                runtime_pods["items"].append(
                    {
                        "metadata": {
                            "name": f"{contract['name']}-{ordinal}",
                            "uid": f"runtime-{contract['name']}-{ordinal}",
                            "ownerReferences": [
                                {
                                    "apiVersion": "apps/v1",
                                    "kind": "StatefulSet",
                                    "name": contract["name"],
                                    "uid": f"{contract['name']}-uid",
                                    "controller": True,
                                }
                            ],
                        },
                        "spec": pod_spec,
                        "status": {
                            "phase": "Running",
                            "conditions": [{"type": "Ready", "status": "True"}],
                            "containerStatuses": [
                                {
                                    "name": "splunk",
                                    "ready": True,
                                    "imageID": (
                                        "docker-pullable://splunk@sha256:main"
                                    ),
                                }
                            ],
                            "initContainerStatuses": init_statuses,
                        },
                    }
                )
        pod_command = [
            sys.executable,
            "-c",
            pod_guard,
            json.dumps(
                [
                    {"prefix": f"{contract['name']}-", "count": contract["count"]}
                    for contract in contracts
                ]
            ),
            "splunk:10.4.0",
            "{}",
        ]

        def pod_input(candidate: dict[str, object]) -> str:
            return "\n".join(
                json.dumps(value) for value in (statefulsets, candidate, {})
            )

        healthy_runtime_pods = subprocess.run(
            pod_command,
            input=pod_input(runtime_pods),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            healthy_runtime_pods.returncode,
            0,
            msg=healthy_runtime_pods.stderr,
        )
        token_automount_disabled = json.loads(json.dumps(runtime_pods))
        for pod in token_automount_disabled["items"]:
            pod["spec"]["volumes"] = [
                volume
                for volume in pod["spec"]["volumes"]
                if not volume.get("name", "").startswith("kube-api-access-")
            ]
            for container in [
                *pod["spec"].get("containers", []),
                *pod["spec"].get("initContainers", []),
            ]:
                container["volumeMounts"] = [
                    mount
                    for mount in container.get("volumeMounts", [])
                    if not mount.get("name", "").startswith("kube-api-access-")
                ]
        accepted_without_api_token = subprocess.run(
            pod_command,
            input=pod_input(token_automount_disabled),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            accepted_without_api_token.returncode,
            0,
            msg=accepted_without_api_token.stderr,
        )
        irsa_statefulsets = json.loads(json.dumps(statefulsets))
        irsa_runtime_pods = json.loads(json.dumps(runtime_pods))
        irsa_name = "splunk-smartstore"
        irsa_role = "arn:aws:iam::123456789012:role/splunk-smartstore"
        irsa_contract = {
            "namespace": "splunk",
            "region": "us-east-1",
            "role_arn": irsa_role,
            "service_account": irsa_name,
            "token_expiration": 3600,
        }
        for stateful in irsa_statefulsets["items"]:
            if stateful["metadata"]["name"].endswith("-indexer"):
                stateful["spec"]["template"]["spec"]["serviceAccountName"] = (
                    irsa_name
                )
        injected_env = [
            {"name": "AWS_STS_REGIONAL_ENDPOINTS", "value": "regional"},
            {"name": "AWS_DEFAULT_REGION", "value": "us-east-1"},
            {"name": "AWS_REGION", "value": "us-east-1"},
            {"name": "AWS_ROLE_ARN", "value": irsa_role},
            {
                "name": "AWS_WEB_IDENTITY_TOKEN_FILE",
                "value": "/var/run/secrets/eks.amazonaws.com/serviceaccount/token",
            },
        ]
        injected_mount = {
            "name": "aws-iam-token",
            "readOnly": True,
            "mountPath": "/var/run/secrets/eks.amazonaws.com/serviceaccount",
        }
        injected_volume = {
            "name": "aws-iam-token",
            "projected": {
                "defaultMode": 420,
                "sources": [
                    {
                        "serviceAccountToken": {
                            "audience": "sts.amazonaws.com",
                            "expirationSeconds": 3600,
                            "path": "token",
                        }
                    }
                ],
            },
        }
        for pod in irsa_runtime_pods["items"]:
            if "-indexer-" not in pod["metadata"]["name"]:
                continue
            pod_spec = pod["spec"]
            pod_spec["serviceAccountName"] = irsa_name
            pod_spec["volumes"].append(json.loads(json.dumps(injected_volume)))
            for container in [
                *pod_spec.get("containers", []),
                *pod_spec.get("initContainers", []),
            ]:
                container.setdefault("env", []).extend(
                    json.loads(json.dumps(injected_env))
                )
                container.setdefault("volumeMounts", []).append(
                    json.loads(json.dumps(injected_mount))
                )
        irsa_service_account = {
            "apiVersion": "v1",
            "kind": "ServiceAccount",
            "metadata": {
                "name": irsa_name,
                "namespace": "splunk",
                "uid": "splunk-smartstore-uid",
                "annotations": {
                    "eks.amazonaws.com/role-arn": irsa_role,
                    "eks.amazonaws.com/token-expiration": "3600",
                    "eks.amazonaws.com/sts-regional-endpoints": "true",
                },
            },
        }
        irsa_pod_command = [*pod_command[:-1], json.dumps(irsa_contract)]

        def irsa_pod_input(candidate: dict[str, object]) -> str:
            return "\n".join(
                json.dumps(value)
                for value in (
                    irsa_statefulsets,
                    candidate,
                    irsa_service_account,
                )
            )

        healthy_irsa_pods = subprocess.run(
            irsa_pod_command,
            input=irsa_pod_input(irsa_runtime_pods),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            healthy_irsa_pods.returncode, 0, msg=healthy_irsa_pods.stderr
        )
        tampered_irsa_pods = json.loads(json.dumps(irsa_runtime_pods))
        for env in tampered_irsa_pods["items"][1]["spec"]["containers"][0]["env"]:
            if env.get("name") == "AWS_ROLE_ARN":
                env["value"] = "arn:aws:iam::123456789012:role/attacker"
        rejected_irsa_pods = subprocess.run(
            irsa_pod_command,
            input=irsa_pod_input(tampered_irsa_pods),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(rejected_irsa_pods.returncode, 0)
        for irsa_mutation in (
            "missing-env",
            "duplicate-env",
            "partial-region",
            "wrong-ttl",
            "wrong-audience",
            "writable-mount",
            "container-credentials",
        ):
            candidate = json.loads(json.dumps(irsa_runtime_pods))
            indexer_pod = candidate["items"][1]
            main = indexer_pod["spec"]["containers"][0]
            if irsa_mutation == "missing-env":
                main["env"] = [
                    entry
                    for entry in main["env"]
                    if entry.get("name") != "AWS_WEB_IDENTITY_TOKEN_FILE"
                ]
            elif irsa_mutation == "duplicate-env":
                main["env"].append({"name": "AWS_ROLE_ARN", "value": irsa_role})
            elif irsa_mutation == "partial-region":
                main["env"] = [
                    entry
                    for entry in main["env"]
                    if entry.get("name") != "AWS_REGION"
                ]
            elif irsa_mutation in {"wrong-ttl", "wrong-audience"}:
                for volume in indexer_pod["spec"]["volumes"]:
                    if volume.get("name") == "aws-iam-token":
                        token = volume["projected"]["sources"][0][
                            "serviceAccountToken"
                        ]
                        if irsa_mutation == "wrong-ttl":
                            token["expirationSeconds"] = 7200
                        else:
                            token["audience"] = "attacker.example"
            elif irsa_mutation == "writable-mount":
                for mount in main["volumeMounts"]:
                    if mount.get("name") == "aws-iam-token":
                        mount["readOnly"] = False
            else:
                main["env"].append(
                    {
                        "name": "AWS_CONTAINER_CREDENTIALS_FULL_URI",
                        "value": "http://169.254.170.23/v1/credentials",
                    }
                )
            rejected_irsa_delta = subprocess.run(
                irsa_pod_command,
                input=irsa_pod_input(candidate),
                capture_output=True,
                text=True,
                check=False,
            )
            with self.subTest(irsa_mutation=irsa_mutation):
                self.assertNotEqual(rejected_irsa_delta.returncode, 0)
        license_manager = {
            "apiVersion": "enterprise.splunk.com/v4",
            "kind": "LicenseManager",
            "metadata": {
                "name": "lm",
                "namespace": "splunk",
                "uid": "lm-uid",
            },
        }
        license_event_command = [
            sys.executable,
            "-c",
            license_event_guard,
            "lm",
            "splunk",
        ]
        healthy_license_events = subprocess.run(
            license_event_command,
            input=f"{json.dumps(license_manager)}\n{json.dumps({'items': []})}",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            healthy_license_events.returncode,
            0,
            msg=healthy_license_events.stderr,
        )
        expired_event = {
            "type": "Warning",
            "reason": "LicenseExpired",
            "involvedObject": {
                "apiVersion": "enterprise.splunk.com/v4",
                "kind": "LicenseManager",
                "name": "lm",
                "namespace": "splunk",
                "uid": "lm-uid",
            },
        }
        rejected_expired_license = subprocess.run(
            license_event_command,
            input=(
                f"{json.dumps(license_manager)}\n"
                f"{json.dumps({'items': [expired_event]})}"
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(rejected_expired_license.returncode, 0)
        for runtime_mutation in (
            "main",
            "init",
            "init-status",
            "kube-token-source",
            "extra-volume",
        ):
            tampered_runtime = json.loads(json.dumps(runtime_pods))
            first_runtime = tampered_runtime["items"][0]
            if runtime_mutation == "main":
                first_runtime["spec"]["containers"][0]["workingDir"] = "/tmp"
            elif runtime_mutation == "init":
                first_runtime["spec"]["initContainers"][0]["command"] = [
                    "bash",
                    "-c",
                    "touch /tmp/pwned",
                ]
            elif runtime_mutation == "init-status":
                first_runtime["status"]["initContainerStatuses"][0]["state"][
                    "terminated"
                ]["exitCode"] = 1
            elif runtime_mutation == "kube-token-source":
                for volume in first_runtime["spec"]["volumes"]:
                    if volume.get("name", "").startswith("kube-api-access-"):
                        volume["projected"]["sources"][1]["configMap"][
                            "name"
                        ] = "attacker-root-ca"
            else:
                first_runtime["spec"]["volumes"].append(
                    {"name": "unmounted-secret", "secret": {"secretName": "evil"}}
                )
            rejected_runtime = subprocess.run(
                pod_command,
                input=pod_input(tampered_runtime),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(rejected_runtime.returncode, 0)
        pods = {"items": []}
        for contract in contracts:
            role = "cm" if "cluster-manager" in contract["name"] else "idx"
            for ordinal in range(contract["count"]):
                pod_ip = f"10.1.{1 if role == 'cm' else 2}.{ordinal + 1}"
                pods["items"].append(
                    {
                        "metadata": {
                            "name": f"{contract['name']}-{ordinal}",
                            "namespace": "splunk",
                            "uid": f"{contract['name']}-{ordinal}-uid",
                            "labels": {
                                "role": role,
                                "app.kubernetes.io/instance": contract["name"],
                            },
                            "ownerReferences": [
                                {
                                    "apiVersion": "apps/v1",
                                    "kind": "StatefulSet",
                                    "name": contract["name"],
                                    "uid": f"{contract['name']}-uid",
                                    "controller": True,
                                }
                            ],
                        },
                        "spec": {
                            "nodeName": f"node-{role}-{ordinal}",
                            "volumes": [
                                {
                                    "name": claim,
                                    "persistentVolumeClaim": {
                                        "claimName": (
                                            f"{claim}-{contract['name']}-{ordinal}"
                                        )
                                    },
                                }
                                for claim in ("pvc-etc", "pvc-var")
                            ],
                        },
                        "status": {
                            "podIP": pod_ip,
                            "podIPs": [{"ip": pod_ip}],
                        },
                    }
                )
        pvcs = {"items": []}
        for contract in contracts:
            for ordinal in range(contract["count"]):
                for claim, size in (("pvc-etc", "10Gi"), ("pvc-var", "100Gi")):
                    pvc_name = f"{claim}-{contract['name']}-{ordinal}"
                    pvcs["items"].append(
                        {
                            "apiVersion": "v1",
                            "kind": "PersistentVolumeClaim",
                            "metadata": {
                                "name": pvc_name,
                                "namespace": "splunk",
                                "uid": f"{pvc_name}-uid",
                                "labels": {
                                    "app.kubernetes.io/instance": contract["name"]
                                },
                            },
                            "spec": {
                                "accessModes": ["ReadWriteOnce"],
                                "volumeMode": "Filesystem",
                                "storageClassName": "gp3",
                                "resources": {"requests": {"storage": size}},
                                "volumeName": f"pv-{pvc_name}",
                            },
                            "status": {
                                "phase": "Bound",
                                "capacity": {"storage": size},
                            },
                        }
                    )
        healthy_pvcs = subprocess.run(
            [
                sys.executable,
                "-c",
                pvc_guard,
                json.dumps(contracts),
                "splunk",
                "10Gi",
                "100Gi",
                "gp3",
            ],
            input="\n".join(
                json.dumps(value) for value in (statefulsets, pvcs, pods)
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(healthy_pvcs.returncode, 0, msg=healthy_pvcs.stderr)
        expanded_pvcs = json.loads(json.dumps(pvcs))
        expanded_pvcs["items"][0]["spec"]["resources"]["requests"][
            "storage"
        ] = "20Gi"
        expanded_pvcs["items"][0]["status"]["capacity"]["storage"] = "20Gi"
        rejected_expansion = subprocess.run(
            [
                sys.executable,
                "-c",
                pvc_guard,
                json.dumps(contracts),
                "splunk",
                "10Gi",
                "100Gi",
                "gp3",
            ],
            input="\n".join(
                json.dumps(value)
                for value in (statefulsets, expanded_pvcs, pods)
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(rejected_expansion.returncode, 0)
        services = {"items": []}
        slices = {"items": []}
        for contract in contracts:
            role = "cm" if "cluster-manager" in contract["name"] else "idx"
            suffixes = (
                ("service",)
                if "cluster-manager" in contract["name"]
                else ("headless", "service")
            )
            ports = {
                "http-splunkweb": 8000,
                "https-splunkd": 8089,
            }
            if role == "idx":
                ports.update({"http-hec": 8088, "tcp-s2s": 9997})
            for suffix in suffixes:
                service_name = f"{contract['name']}-{suffix}"
                services["items"].append(
                    {
                        "apiVersion": "v1",
                        "kind": "Service",
                        "metadata": {
                            "name": service_name,
                            "namespace": "splunk",
                            "uid": f"{service_name}-uid",
                            "ownerReferences": [
                                {
                                    "apiVersion": "enterprise.splunk.com/v4",
                                    "kind": contract["owner_kind"],
                                    "name": contract["owner_name"],
                                    "controller": True,
                                    "uid": f"{contract['owner_name']}-uid",
                                }
                            ],
                        },
                        "spec": {
                            "type": "ClusterIP",
                            "clusterIP": "None" if suffix == "headless" else "10.0.0.1",
                            "selector": {
                                "app.kubernetes.io/instance": contract["name"]
                            },
                            "ports": [
                                {
                                    "name": port_name,
                                    "port": port,
                                    "targetPort": port,
                                    "protocol": "TCP",
                                }
                                for port_name, port in sorted(ports.items())
                            ],
                        },
                    }
                )
                slices["items"].append(
                    {
                        "apiVersion": "discovery.k8s.io/v1",
                        "kind": "EndpointSlice",
                        "addressType": "IPv4",
                        "metadata": {
                            "name": f"{service_name}-slice",
                            "namespace": "splunk",
                            "uid": f"{service_name}-slice-uid",
                            "labels": {
                                "kubernetes.io/service-name": service_name,
                                "endpointslice.kubernetes.io/managed-by": (
                                    "endpointslice-controller.k8s.io"
                                ),
                            },
                            "ownerReferences": [
                                {
                                    "apiVersion": "v1",
                                    "kind": "Service",
                                    "name": service_name,
                                    "uid": f"{service_name}-uid",
                                    "controller": True,
                                }
                            ],
                        },
                        "ports": [
                            {"name": name, "port": port, "protocol": "TCP"}
                            for name, port in sorted(ports.items())
                        ],
                        "endpoints": [
                            {
                                "conditions": {"ready": True},
                                "targetRef": {
                                    "apiVersion": "v1",
                                    "kind": "Pod",
                                    "name": f"{contract['name']}-{ordinal}",
                                    "namespace": "splunk",
                                    "uid": f"{contract['name']}-{ordinal}-uid",
                                },
                                "addresses": [f"10.1.{1 if role == 'cm' else 2}.{ordinal + 1}"],
                            }
                            for ordinal in range(contract["count"])
                        ],
                    }
                )
        service_input = "\n".join(
            json.dumps(value) for value in (statefulsets, services, slices, pods)
        )
        healthy = subprocess.run(
            [sys.executable, "-c", service_guard, json.dumps(contracts), "splunk"],
            input=service_input,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(healthy.returncode, 0, msg=healthy.stderr)
        swapped_ports = json.loads(json.dumps(services))
        for port in swapped_ports["items"][0]["spec"]["ports"]:
            if port["name"] == "http-splunkweb":
                port["targetPort"] = 8089
            elif port["name"] == "https-splunkd":
                port["targetPort"] = 8000
        forged_addresses = json.loads(json.dumps(slices))
        forged_addresses["items"][0]["endpoints"][0]["addresses"] = ["10.9.9.9"]
        wrong_service_owner = json.loads(json.dumps(services))
        wrong_service_owner["items"][0]["metadata"]["ownerReferences"][0][
            "uid"
        ] = "wrong-uid"
        wrong_bootstrap_policy = json.loads(json.dumps(services))
        wrong_bootstrap_policy["items"][0]["spec"][
            "publishNotReadyAddresses"
        ] = True
        wrong_internal_policy = json.loads(json.dumps(services))
        wrong_internal_policy["items"][0]["spec"]["internalTrafficPolicy"] = "Local"
        wrong_pod_owner = json.loads(json.dumps(pods))
        wrong_pod_owner["items"][0]["metadata"]["ownerReferences"][0]["uid"] = (
            "wrong-uid"
        )
        for candidate_services, candidate_slices, candidate_pods in (
            (swapped_ports, slices, pods),
            (services, forged_addresses, pods),
            (wrong_service_owner, slices, pods),
            (wrong_bootstrap_policy, slices, pods),
            (wrong_internal_policy, slices, pods),
            (services, slices, wrong_pod_owner),
        ):
            rejected_identity = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    service_guard,
                    json.dumps(contracts),
                    "splunk",
                ],
                input="\n".join(
                    json.dumps(value)
                    for value in (
                        statefulsets,
                        candidate_services,
                        candidate_slices,
                        candidate_pods,
                    )
                ),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(rejected_identity.returncode, 0)
        missing_slice = json.loads(json.dumps(slices))
        missing_slice["items"].pop()
        unhealthy = subprocess.run(
            [sys.executable, "-c", service_guard, json.dumps(contracts), "splunk"],
            input="\n".join(
                json.dumps(value)
                for value in (statefulsets, services, missing_slice, pods)
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(unhealthy.returncode, 0)
        broadened = json.loads(json.dumps(services))
        broadened["items"][0]["spec"]["selector"] = {
            "app.kubernetes.io/managed-by": "splunk-operator"
        }
        broad_pods = json.loads(json.dumps(pods))
        for pod in broad_pods["items"]:
            pod["metadata"]["labels"]["app.kubernetes.io/managed-by"] = (
                "splunk-operator"
            )
        broad_slices = json.loads(json.dumps(slices))
        broad_slices["items"][0]["endpoints"].append(
            {
                "conditions": {"ready": True},
                "targetRef": {
                    "kind": "Pod",
                    "name": "splunk-idxc-indexer-0",
                },
                "addresses": ["10.1.9.9"],
            }
        )
        rejected_broad_selector = subprocess.run(
            [sys.executable, "-c", service_guard, json.dumps(contracts), "splunk"],
            input="\n".join(
                json.dumps(value)
                for value in (statefulsets, broadened, broad_slices, broad_pods)
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(rejected_broad_selector.returncode, 0)

        nodes = {
            "items": [
                {
                    "metadata": {
                        "name": pod["spec"]["nodeName"],
                        "labels": {"topology.kubernetes.io/zone": "zone-a"},
                    }
                }
                for pod in pods["items"]
            ]
        }
        placement_contracts = [
            {
                "prefix": f"{contract['name']}-",
                "count": contract["count"],
                "zone": "zone-a",
            }
            for contract in contracts
        ]
        placed = subprocess.run(
            [
                sys.executable,
                "-c",
                placement_guard,
                json.dumps(placement_contracts),
                "true",
            ],
            input=json.dumps(pods) + "\n" + json.dumps(nodes),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(placed.returncode, 0, msg=placed.stderr)
        colocated = json.loads(json.dumps(pods))
        colocated["items"][-1]["spec"]["nodeName"] = colocated["items"][-2]["spec"]["nodeName"]
        rejected = subprocess.run(
            [
                sys.executable,
                "-c",
                placement_guard,
                json.dumps(placement_contracts),
                "true",
            ],
            input=json.dumps(colocated) + "\n" + json.dumps(nodes),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(rejected.returncode, 0)

    def test_sok_operator_live_contract_detects_helm_object_drift(self) -> None:
        guard = self.embedded_renderer_code("operator_contract_code")
        expected = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": "splunk-operator-controller-manager",
                "namespace": "splunk-operator",
                "labels": {"app": "splunk-operator"},
            },
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": "splunk-operator"}},
                "template": {
                    "metadata": {"labels": {"app": "splunk-operator"}},
                    "spec": {
                        "containers": [
                            {
                                "name": "manager",
                                "image": "operator:3.1.0",
                                "ports": [
                                    {"name": "http", "containerPort": 8080}
                                ],
                                "livenessProbe": {
                                    "httpGet": {"path": "/healthz", "port": 8081},
                                    "initialDelaySeconds": 15,
                                    "periodSeconds": 20,
                                },
                            }
                        ]
                    },
                },
            },
        }
        server_expected = json.loads(json.dumps(expected))
        server_probe = server_expected["spec"]["template"]["spec"]["containers"][0][
            "livenessProbe"
        ]
        server_probe.update(
            {"timeoutSeconds": 1, "successThreshold": 1, "failureThreshold": 3}
        )
        server_probe["httpGet"]["scheme"] = "HTTP"
        server_expected["spec"]["template"]["spec"]["containers"][0]["ports"][
            0
        ]["protocol"] = "TCP"
        live = json.loads(json.dumps(server_expected))
        live["metadata"].update(
            {
                "annotations": {
                    "meta.helm.sh/release-name": "splunk-operator",
                    "meta.helm.sh/release-namespace": "splunk-operator",
                },
                "uid": "uid",
                "resourceVersion": "7",
            }
        )
        live["status"] = {"readyReplicas": 1}
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_path = root / "raw.yaml"
            expected_path = root / "expected.yaml"
            live_path = root / "live.json"
            raw_path.write_text(json.dumps(expected), encoding="utf-8")
            expected_path.write_text(json.dumps(server_expected), encoding="utf-8")
            mock = root / "kubectl"
            mock.write_text(
                "#!/bin/sh\n"
                "if printf '%s\\n' \"$@\" | grep -Fxq deployments; then\n"
                "  cat \"$MOCK_OPERATOR_LIVE\"\n"
                "else\n"
                "  printf '{\"items\":[]}\\n'\n"
                "fi\n",
                encoding="utf-8",
            )
            mock.chmod(0o700)

            def run_contract(item: dict[str, object]) -> subprocess.CompletedProcess:
                live_path.write_text(
                    json.dumps({"items": [item]}), encoding="utf-8"
                )
                environment = os.environ.copy()
                environment["PATH"] = f"{root}:{environment['PATH']}"
                environment["MOCK_OPERATOR_LIVE"] = str(live_path)
                return subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        guard,
                        str(raw_path),
                        str(expected_path),
                        "splunk-operator",
                        "splunk-operator",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=environment,
                )

            healthy = run_contract(live)
            self.assertEqual(healthy.returncode, 0, msg=healthy.stderr)
            drifted = json.loads(json.dumps(live))
            drifted["spec"]["replicas"] = 2
            rejected = run_contract(drifted)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("differs", rejected.stderr)
            extra_label = json.loads(json.dumps(live))
            extra_label["metadata"]["labels"]["injected"] = "true"
            rejected_label = run_contract(extra_label)
            self.assertNotEqual(rejected_label.returncode, 0)
            self.assertIn("raw Helm intent", rejected_label.stderr)
            extra_container = json.loads(json.dumps(live))
            extra_container["spec"]["template"]["spec"]["containers"].append(
                {"name": "injected", "image": "sidecar:latest"}
            )
            rejected_container = run_contract(extra_container)
            self.assertNotEqual(rejected_container.returncode, 0)
            self.assertIn("inventory", rejected_container.stderr)
            merged_host_port = json.loads(json.dumps(live))
            merged_host_port["spec"]["template"]["spec"]["containers"][0][
                "ports"
            ][0]["hostPort"] = 80
            merged_server_expected = json.loads(json.dumps(server_expected))
            merged_server_expected["spec"]["template"]["spec"]["containers"][0][
                "ports"
            ][0]["hostPort"] = 80
            expected_path.write_text(
                json.dumps(merged_server_expected), encoding="utf-8"
            )
            rejected_host_port = run_contract(merged_host_port)
            self.assertNotEqual(rejected_host_port.returncode, 0)
            self.assertIn("host port/IP", rejected_host_port.stderr)
            merged_paused = json.loads(json.dumps(live))
            merged_paused["spec"]["paused"] = True
            paused_server_expected = json.loads(json.dumps(server_expected))
            paused_server_expected["spec"]["paused"] = True
            expected_path.write_text(
                json.dumps(paused_server_expected), encoding="utf-8"
            )
            rejected_paused = run_contract(merged_paused)
            self.assertNotEqual(rejected_paused.returncode, 0)
            self.assertIn("spec.paused", rejected_paused.stderr)

    def test_sok_10_4_upgrade_requires_explicit_readiness_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = [
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                tmpdir,
                "--allow-upgrade",
                "--accept-splunk-general-terms",
            ]
            rejected = self.run_renderer(*base)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn(
                "--confirm-splunk-10-4-upgrade-readiness", rejected.stderr
            )
            accepted = self.run_renderer(
                *base, "--confirm-splunk-10-4-upgrade-readiness"
            )
            self.assertEqual(
                accepted.returncode, 0, msg=accepted.stdout + accepted.stderr
            )

    def test_sok_requires_explicit_terms_for_every_reconcile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            for splunk_version in ("9.4.9", "10.4.0"):
                with self.subTest(splunk_version=splunk_version):
                    result = self.run_renderer(
                        "--target",
                        "sok",
                        "--architecture",
                        "s1",
                        "--output-dir",
                        str(Path(tmpdir) / splunk_version),
                        "--splunk-version",
                        splunk_version,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("--accept-splunk-general-terms", result.stderr)

    def test_sok_requires_terms_for_custom_splunk_10_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                tmpdir,
                "--splunk-version",
                "9.4.0",
                "--splunk-image",
                "registry.example.com/splunk/splunk:10.2.0",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--accept-splunk-general-terms", result.stderr)

    def test_sok_does_not_certify_an_opaque_custom_image_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rejected = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                tmpdir,
                "--splunk-image",
                "registry.example.com/splunk/splunk:latest",
                "--accept-splunk-general-terms",
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("unable to parse version", rejected.stderr)

            reviewed = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                tmpdir,
                "--splunk-image",
                "registry.example.com/splunk/splunk:latest",
                "--allow-unverified-versions",
                "--accept-splunk-general-terms",
            )
            self.assertEqual(
                reviewed.returncode, 0, msg=reviewed.stdout + reviewed.stderr
            )

    def test_sok_enforces_release_3_1_compatibility_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cases = (
                ("k8s-1.25-splunk-9.4.3", "1.25", "9.4.3", True, ""),
                ("k8s-1.34-splunk-9.4.9", "1.34", "9.4.9", True, ""),
                (
                    "k8s-1.34-splunk-9.4.8",
                    "1.34",
                    "9.4.8",
                    False,
                    "Kubernetes 1.34 requires Splunk Enterprise",
                ),
                (
                    "k8s-1.35-splunk-10.4.0",
                    "1.35",
                    "10.4.0",
                    False,
                    "supports Kubernetes 1.25 through 1.34",
                ),
                (
                    "k8s-1.33-unlisted-future-splunk",
                    "1.33",
                    "11.0.0",
                    False,
                    "listed 10.2.x and 10.4.x release lines",
                ),
            )
            for name, kubernetes, splunk, supported, message in cases:
                with self.subTest(name=name):
                    args = [
                        "--target",
                        "sok",
                        "--architecture",
                        "s1",
                        "--output-dir",
                        str(Path(tmpdir) / name),
                        "--kubernetes-version",
                        kubernetes,
                        "--splunk-version",
                        splunk,
                    ]
                    args.append("--accept-splunk-general-terms")
                    result = self.run_renderer(*args)
                    if supported:
                        self.assertEqual(
                            result.returncode,
                            0,
                            msg=result.stdout + result.stderr,
                        )
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(message, result.stderr)

    def test_sok_production_cannot_bypass_unsupported_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                tmpdir,
                "--operator-version",
                "3.2.0",
                "--allow-unverified-versions",
                "--deployment-profile",
                "production",
                "--kubernetes-version",
                "1.34",
                "--storage-class",
                "gp3",
                "--smartstore-bucket",
                "prod-smartstore",
                "--smartstore-region",
                "us-east-1",
                "--existing-license-manager",
                "lm",
                "--splunk-service-account",
                "splunk-workload",
                "--confirm-smartstore-index-inventory",
                "--confirm-smartstore-path-ownership",
                "--accept-splunk-general-terms",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "Production SOK cannot bypass the verified compatibility matrix",
                result.stderr,
            )

    def test_sok_rejects_chart_mismatch_unless_explicitly_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "rendered"
            rejected = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                str(output_dir),
                "--operator-version",
                "3.1.0",
                "--chart-version",
                "3.0.0",
                "--accept-splunk-general-terms",
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn(
                "--chart-version must match --operator-version",
                rejected.stderr,
            )
            overridden = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                str(output_dir),
                "--operator-version",
                "3.1.0",
                "--chart-version",
                "3.0.0",
                "--allow-unverified-versions",
                "--accept-splunk-general-terms",
            )
            self.assertEqual(
                overridden.returncode,
                0,
                msg=overridden.stdout + overridden.stderr,
            )
            operator_script = (
                output_dir / "sok" / "helm-install-operator.sh"
            ).read_text(encoding="utf-8")
            enterprise_script = (
                output_dir / "sok" / "helm-install-enterprise.sh"
            ).read_text(encoding="utf-8")
            self.assertIn("--version 3.0.0", operator_script)
            self.assertIn("--version 3.0.0", enterprise_script)
            self.assertIn(
                "helm repo add splunk https://splunk.github.io/splunk-operator/ --force-update",
                operator_script,
            )
            self.assertIn(
                "helm repo add splunk https://splunk.github.io/splunk-operator/ --force-update",
                enterprise_script,
            )

    def test_sok_rejects_out_of_schema_counts_regions_and_eks_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cases = (
                (["--etc-storage", "1K"], "--etc-storage"),
                (
                    ["--standalone-replicas", "2147483648"],
                    "--standalone-replicas",
                ),
                (["--site-count", "64"], "--site-count"),
                (
                    [
                        "--architecture",
                        "c3",
                        "--indexing-ingestion-separation",
                        "--queue-name",
                        "events",
                        "--queue-dlq",
                        "events-dlq",
                        "--queue-region",
                        "eusc-de-east-1",
                        "--queue-secret-ref",
                        "queue-secret",
                        "--object-storage-path",
                        "events/archive",
                    ],
                    "--queue-region",
                ),
                (
                    ["--eks-cluster-name", "invalid cluster", "--aws-region", "us-east-1"],
                    "--eks-cluster-name",
                ),
                (
                    ["--eks-cluster-name", "", "--aws-region", "us-east-1"],
                    "EKS cluster name must not be empty",
                ),
            )
            for index, (extra, message) in enumerate(cases):
                with self.subTest(extra=extra):
                    result = self.run_renderer(
                        "--target",
                        "sok",
                        "--architecture",
                        "s1",
                        "--output-dir",
                        str(Path(tmpdir) / str(index)),
                        "--accept-splunk-general-terms",
                        *extra,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(message, result.stderr)

    def test_sok_removes_stale_optional_helpers_on_rerender(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "rendered"
            license_file = root / "splunk.lic"
            license_file.write_text("LICENSE_SECRET_CONTENT\n", encoding="utf-8")

            first = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                str(output_dir),
                "--license-file",
                str(license_file),
                "--eks-cluster-name",
                "demo",
                "--aws-region",
                "us-west-2",
                "--accept-splunk-general-terms",
            )
            self.assertEqual(first.returncode, 0, msg=first.stdout + first.stderr)
            self.assertTrue(
                (output_dir / "sok" / "create-license-configmap.sh").exists()
            )
            self.assertTrue((output_dir / "sok" / "eks-update-kubeconfig.sh").exists())

            second = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                str(output_dir),
                "--accept-splunk-general-terms",
            )
            self.assertEqual(second.returncode, 0, msg=second.stdout + second.stderr)
            self.assertFalse(
                (output_dir / "sok" / "create-license-configmap.sh").exists()
            )
            self.assertFalse((output_dir / "sok" / "eks-update-kubeconfig.sh").exists())

    def test_sok_rejects_invalid_kubernetes_names_before_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                tmpdir,
                "--namespace",
                "splunk;touch",
                "--accept-splunk-general-terms",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("valid Kubernetes DNS label", result.stderr)

    def test_sok_rejects_direct_renderer_missing_cloud_region_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            eks_result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                tmpdir,
                "--eks-cluster-name",
                "demo",
                "--accept-splunk-general-terms",
            )
            self.assertNotEqual(eks_result.returncode, 0)
            self.assertIn("--aws-region is required", eks_result.stderr)

            smartstore_result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                tmpdir,
                "--smartstore-bucket",
                "splunk-smartstore-prod",
                "--accept-splunk-general-terms",
            )
            self.assertNotEqual(smartstore_result.returncode, 0)
            self.assertIn(
                "--smartstore-region is required for the aws SmartStore provider",
                smartstore_result.stderr,
            )

    def test_m4_site_zones_are_explicit_and_indexers_are_per_site(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "rendered"
            result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "m4",
                "--output-dir",
                str(output_dir),
                "--indexer-replicas",
                "2",
                "--site-count",
                "2",
                "--site-zones",
                "us-west-2a,us-west-2b",
                "--aws-region",
                "us-west-2",
                "--accept-splunk-general-terms",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            values = (output_dir / "sok" / "enterprise-values.yaml").read_text(
                encoding="utf-8"
            )
            self.assertIn('zone: "us-west-2a"', values)
            self.assertIn('zone: "us-west-2b"', values)
            self.assertIn("2 indexers per site, 4 total indexers", values)
            self.assertIn("M4 zone pinning: enabled", values)
            self.assertNotIn('zone: "us-west-2"', values)
            search_head_block = values.split("    searchHeadClusters:", 1)[1].split(
                "# Effective M4 defaults:", 1
            )[0]
            self.assertIn("        site: site2", search_head_block)
            self.assertNotIn("zone:", search_head_block)

            unsupported_factor_contract = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "m4",
                "--output-dir",
                str(Path(tmpdir) / "three-sites"),
                "--site-count",
                "3",
                "--accept-splunk-general-terms",
            )
            self.assertNotEqual(unsupported_factor_contract.returncode, 0)
            self.assertIn(
                "fixes multisite replication and search factor totals at 2",
                unsupported_factor_contract.stderr,
            )

    def test_m4_without_site_zones_omits_zone_affinity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "rendered"
            result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "m4",
                "--output-dir",
                str(output_dir),
                "--accept-splunk-general-terms",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            values = (output_dir / "sok" / "enterprise-values.yaml").read_text(
                encoding="utf-8"
            )
            self.assertIn("M4 zone pinning: not rendered", values)
            self.assertNotIn("zone:", values)

    def test_sok_rejects_undersized_clustered_replicas(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            c3_result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "c3",
                "--output-dir",
                tmpdir,
                "--indexer-replicas",
                "1",
                "--accept-splunk-general-terms",
            )
            self.assertNotEqual(c3_result.returncode, 0)
            self.assertIn("at least 3 for SOK C3", c3_result.stderr)

            m4_result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "m4",
                "--output-dir",
                tmpdir,
                "--search-head-replicas",
                "1",
                "--accept-splunk-general-terms",
            )
            self.assertNotEqual(m4_result.returncode, 0)
            self.assertIn("at least 3 for SOK C3/M4", m4_result.stderr)

    def test_sok_renders_smartstore_license_and_does_not_leak_secret_contents(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            license_file = root / "splunk.lic"
            key_file = root / "smartstore.key"
            license_file.write_text("LICENSE_SECRET_CONTENT\n", encoding="utf-8")
            key_file.write_text("SMARTSTORE_SECRET_CONTENT\n", encoding="utf-8")
            output_dir = root / "rendered"

            result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "m4",
                "--output-dir",
                str(output_dir),
                "--license-file",
                str(license_file),
                "--smartstore-bucket",
                "splunk-smartstore-prod",
                "--smartstore-prefix",
                "indexes",
                "--smartstore-region",
                "us-west-2",
                "--smartstore-secret-ref",
                "ss-secret",
                "--accept-splunk-general-terms",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            rendered = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (output_dir / "sok").glob("*")
                if path.is_file()
            )
            enterprise_values = (
                output_dir / "sok" / "enterprise-values.yaml"
            ).read_text(encoding="utf-8")
            self.assertIn(
                'image:\n  repository: "splunk/splunk:10.4.0"\n  imagePullPolicy: "IfNotPresent"',
                enterprise_values,
            )
            self.assertNotIn('\nimagePullPolicy: "IfNotPresent"', enterprise_values)
            self.assertIn('path: "splunk-smartstore-prod/indexes"', rendered)
            self.assertIn('secretRef: "ss-secret"', rendered)
            self.assertIn("licenseManager:\n  enabled: true", rendered)
            self.assertIn('  name: "lm"', rendered)
            self.assertIn("create configmap splunk-licenses", rendered)
            self.assertNotIn("LICENSE_SECRET_CONTENT", rendered)
            self.assertNotIn("SMARTSTORE_SECRET_CONTENT", rendered)

    def test_sok_s1_local_license_status_does_not_wait_for_licensemanager(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            license_file = root / "splunk.lic"
            license_file.write_text("test-license\n", encoding="utf-8")
            result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                str(root / "rendered"),
                "--license-file",
                str(license_file),
                "--accept-splunk-general-terms",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            status = (root / "rendered" / "sok" / "status.sh").read_text(
                encoding="utf-8"
            )
            self.assertIn("Ready standalone", status)
            self.assertNotIn("Ready licensemanager", status)

    def test_sok_production_requires_storage_smartstore_license_and_identity(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            common = [
                "--target",
                "sok",
                "--architecture",
                "c3",
                "--output-dir",
                tmpdir,
                "--deployment-profile",
                "production",
                "--accept-splunk-general-terms",
            ]
            gate_cases = (
                ((), "--storage-class is required"),
                (("--storage-class", "gp3"), "--smartstore-bucket is required"),
                (
                    (
                        "--storage-class",
                        "gp3",
                        "--smartstore-bucket",
                        "prod-smartstore",
                        "--smartstore-region",
                        "us-east-1",
                    ),
                    "requires --license-file or --existing-license-manager",
                ),
                (
                    (
                        "--storage-class",
                        "gp3",
                        "--smartstore-bucket",
                        "prod-smartstore",
                        "--smartstore-region",
                        "us-east-1",
                        "--existing-license-manager",
                        "lm",
                    ),
                    "requires --smartstore-secret-ref or --splunk-service-account",
                ),
                (
                    (
                        "--storage-class",
                        "gp3",
                        "--smartstore-bucket",
                        "prod-smartstore",
                        "--smartstore-region",
                        "us-east-1",
                        "--existing-license-manager",
                        "lm",
                        "--smartstore-secret-ref",
                        "smartstore-credentials",
                        "--confirm-smartstore-index-inventory",
                    ),
                    "requires --confirm-smartstore-path-ownership",
                ),
            )
            for extra, message in gate_cases:
                with self.subTest(message=message):
                    result = self.run_renderer(*common, *extra)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(message, result.stderr)

    def test_sok_s1_rejects_multiple_standalones(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--standalone-replicas",
                "2",
                "--output-dir",
                tmpdir,
                "--accept-splunk-general-terms",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires exactly one Standalone", result.stderr)

    def test_sok_smartstore_irsa_is_role_scoped_and_reviewed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "irsa"
            common = (
                "--target",
                "sok",
                "--architecture",
                "c3",
                "--output-dir",
                str(output_dir),
                "--namespace",
                "splunk",
                "--operator-namespace",
                "splunk",
                "--smartstore-bucket",
                "prod-smartstore",
                "--smartstore-region",
                "us-east-1",
                "--aws-region",
                "us-east-1",
                "--splunk-service-account",
                "splunk-smartstore",
                "--accept-splunk-general-terms",
            )
            missing_role = self.run_renderer(*common)
            self.assertNotEqual(missing_role.returncode, 0)
            self.assertIn("requires --splunk-irsa-role-arn", missing_role.stderr)

            role_arn = "arn:aws:iam::123456789012:role/splunk-smartstore"
            rendered = self.run_renderer(
                *common,
                "--splunk-irsa-role-arn",
                role_arn,
                "--splunk-irsa-token-expiration",
                "3600",
            )
            self.assertEqual(rendered.returncode, 0, msg=rendered.stderr)
            values = (output_dir / "sok" / "enterprise-values.yaml").read_text()
            self.assertEqual(
                values.count('serviceAccount: "splunk-smartstore"'), 1
            )
            self.assertRegex(
                values,
                r'(?s)indexerCluster:.*serviceAccount: "splunk-smartstore"',
            )
            for block in ("clusterManager:", "searchHeadCluster:", "monitoringConsole:"):
                section = values.split(block, 1)[1].split("\n\n", 1)[0]
                self.assertNotIn("serviceAccount:", section)
            metadata = json.loads((output_dir / "sok" / "metadata.json").read_text())
            self.assertEqual(metadata["splunk_irsa_role_arn"], role_arn)
            self.assertEqual(metadata["splunk_irsa_token_expiration"], 3600)
            preflight = (output_dir / "sok" / "preflight.sh").read_text()
            self.assertIn("eks.amazonaws.com/role-arn", preflight)
            self.assertIn("eks.amazonaws.com/token-expiration", preflight)
            self.assertIn("eks.amazonaws.com/sts-regional-endpoints", preflight)
            self.assertIn("kubectl create --dry-run=server", preflight)
            self.assertIn("AWS_WEB_IDENTITY_TOKEN_FILE", preflight)

            max_ttl = self.run_renderer(
                *common,
                "--output-dir",
                str(Path(tmpdir) / "max-ttl"),
                "--splunk-irsa-role-arn",
                role_arn,
                "--splunk-irsa-token-expiration",
                "86400",
            )
            self.assertEqual(max_ttl.returncode, 0, msg=max_ttl.stderr)

    def test_sok_production_resources_and_m4_zone_placement(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            common = [
                "--target",
                "sok",
                "--architecture",
                "m4",
                "--output-dir",
                tmpdir,
                "--deployment-profile",
                "production",
                "--storage-class",
                "gp3",
                "--smartstore-bucket",
                "prod-smartstore",
                "--smartstore-prefix",
                "deployment-a",
                "--smartstore-region",
                "us-east-1",
                "--existing-license-manager",
                "lm",
                "--existing-license-manager-namespace",
                "splunk",
                "--operator-scope",
                "cluster",
                "--splunk-service-account",
                "splunk-workload",
                "--confirm-smartstore-index-inventory",
                "--confirm-smartstore-path-ownership",
                "--accept-splunk-general-terms",
            ]
            missing_zones = self.run_renderer(*common)
            self.assertNotEqual(missing_zones.returncode, 0)
            self.assertIn(
                "Production M4 requires --site-zones, --manager-zone, and --search-head-zone",
                missing_zones.stderr,
            )

            rendered = self.run_renderer(
                *common,
                "--site-count",
                "2",
                "--site-zones",
                "us-east-1a,us-east-1b",
                "--manager-zone",
                "us-east-1a",
                "--search-head-zone",
                "us-east-1b",
                "--kubernetes-version",
                "1.34",
            )
            self.assertNotEqual(rendered.returncode, 0)
            self.assertIn(
                "Production SOK requires reviewed local chart archives and a CRD manifest",
                rendered.stderr,
            )

    def test_sok_namespace_and_cluster_scope_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cross_namespace_lm = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                str(Path(tmpdir) / "cross-namespace-lm"),
                "--existing-license-manager",
                "lm",
                "--existing-license-manager-namespace",
                "licensing",
                "--operator-scope",
                "cluster",
                "--accept-splunk-general-terms",
            )
            self.assertNotEqual(cross_namespace_lm.returncode, 0)
            self.assertIn(
                "one-Operator/multi-namespace external-LicenseManager handoff",
                cross_namespace_lm.stderr,
            )
            namespace_mismatch = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                str(Path(tmpdir) / "mismatch"),
                "--namespace",
                "splunk",
                "--operator-namespace",
                "splunk-operator",
                "--accept-splunk-general-terms",
            )
            self.assertNotEqual(namespace_mismatch.returncode, 0)
            self.assertIn("Namespace-scoped SOK requires", namespace_mismatch.stderr)

            missing_watch = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                str(Path(tmpdir) / "missing-watch"),
                "--namespace",
                "splunk",
                "--operator-namespace",
                "splunk-operator",
                "--operator-scope",
                "cluster",
                "--watch-namespaces",
                "other-team",
                "--accept-splunk-general-terms",
            )
            self.assertNotEqual(missing_watch.returncode, 0)
            self.assertIn(
                "must include the Splunk Enterprise namespace", missing_watch.stderr
            )

            output_dir = Path(tmpdir) / "cluster-scope"
            cluster_scope = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                str(output_dir),
                "--namespace",
                "splunk",
                "--operator-namespace",
                "splunk-operator",
                "--operator-scope",
                "cluster",
                "--watch-namespaces",
                "splunk",
                "--accept-splunk-general-terms",
            )
            self.assertEqual(
                cluster_scope.returncode,
                0,
                msg=cluster_scope.stdout + cluster_scope.stderr,
            )
            operator_values = (output_dir / "sok" / "operator-values.yaml").read_text(
                encoding="utf-8"
            )
            namespaces = (output_dir / "sok" / "namespace.yaml").read_text(
                encoding="utf-8"
            )
            metadata = json.loads(
                (output_dir / "sok" / "metadata.json").read_text(encoding="utf-8")
            )
            preflight = (output_dir / "sok" / "preflight.sh").read_text(
                encoding="utf-8"
            )
            self.assertIn("clusterWideAccess: true", operator_values)
            self.assertIn('watchNamespaces: "splunk"', operator_values)
            self.assertIn("name: splunk-operator", namespaces)
            self.assertIn("name: splunk", namespaces)
            self.assertEqual(metadata["operator_scope"], "cluster")
            self.assertEqual(metadata["watch_namespaces"], ["splunk"])
            self.assertIn('"resource": "clusterroles"', preflight)
            self.assertIn('"resource": "clusterrolebindings"', preflight)
            self.assertIn("SelfSubjectAccessReview", preflight)

    def test_sok_renders_indexing_ingestion_separation_resources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "c3",
                "--output-dir",
                tmpdir,
                "--kubernetes-version",
                "1.34",
                "--indexing-ingestion-separation",
                "--ingestor-replicas",
                "4",
                "--queue-secret-ref",
                "queue-credentials",
                "--queue-name",
                "splunk-ingest",
                "--queue-dlq",
                "splunk-ingest-dlq",
                "--queue-region",
                "us-east-1",
                "--queue-endpoint",
                "https://sqs.us-east-1.amazonaws.com",
                "--object-storage-path",
                "large-events/deployment-a",
                "--object-storage-endpoint",
                "https://s3.us-east-1.amazonaws.com",
                "--accept-splunk-general-terms",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "sok"
            values = (render_dir / "enterprise-values.yaml").read_text(encoding="utf-8")
            metadata = json.loads(
                (render_dir / "metadata.json").read_text(encoding="utf-8")
            )
            status = (render_dir / "status.sh").read_text(encoding="utf-8")
            self.assertIn(
                "kind: Queue\n    metadata:\n      name: ingest-queue", values
            )
            self.assertIn(
                'objectStorage:\n  enabled: true\n  name: "ingest-object-storage"',
                values,
            )
            self.assertIn(
                'ingestorCluster:\n  enabled: true\n  name: "ingestor"\n  replicaCount: 4',
                values,
            )
            self.assertEqual(values.count('name: "ingest-queue"'), 2)
            self.assertEqual(values.count('name: "ingest-object-storage"'), 3)
            self.assertNotIn("serviceAccount: ingest-workload", values)
            self.assertIn('secretRef: "queue-credentials"', values)
            self.assertTrue(metadata["indexing_ingestion_separation"])
            self.assertIn("Ready ingestorcluster", status)

            secret_result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "c3",
                "--output-dir",
                str(Path(tmpdir) / "queue-secret"),
                "--indexing-ingestion-separation",
                "--queue-provider",
                "sqs_cp",
                "--queue-name",
                "splunk-ingest",
                "--queue-dlq",
                "splunk-ingest-dlq",
                "--queue-region",
                "us-east-1",
                "--queue-secret-ref",
                "queue-credentials",
                "--object-storage-path",
                "large-events/deployment-a",
                "--allow-upgrade",
                "--confirm-splunk-10-4-upgrade-readiness",
                "--accept-splunk-general-terms",
            )
            self.assertEqual(
                secret_result.returncode,
                0,
                msg=secret_result.stdout + secret_result.stderr,
            )
            secret_dir = Path(tmpdir) / "queue-secret" / "sok"
            secret_values = (secret_dir / "enterprise-values.yaml").read_text(
                encoding="utf-8"
            )
            secret_preflight = (secret_dir / "preflight.sh").read_text(encoding="utf-8")
            self.assertIn("extraManifests:", secret_values)
            self.assertIn('provider: "sqs_cp"', secret_values)
            self.assertIn('secretRef: "queue-credentials"', secret_values)
            self.assertNotIn("volumes:\n        authRegion:", secret_values)
            self.assertIn("unsupported immutable change", secret_preflight)
            self.assertIn("chart downgrade is unsupported", secret_preflight)

            unsupported = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "c3",
                "--output-dir",
                str(Path(tmpdir) / "unsupported"),
                "--splunk-version",
                "10.2.0",
                "--kubernetes-version",
                "1.34",
                "--indexing-ingestion-separation",
                "--queue-secret-ref",
                "queue-credentials",
                "--queue-name",
                "splunk-ingest",
                "--queue-dlq",
                "splunk-ingest-dlq",
                "--queue-region",
                "us-east-1",
                "--object-storage-path",
                "large-events/deployment-a",
                "--accept-splunk-general-terms",
            )
            self.assertNotEqual(unsupported.returncode, 0)
            self.assertIn(
                "Kubernetes 1.34 requires Splunk Enterprise", unsupported.stderr
            )
            self.assertIn("10.4+", unsupported.stderr)

    def test_sok_copies_and_applies_values_overlays(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            operator_overlay = root / "operator-extra.yaml"
            enterprise_overlay = root / "enterprise-extra.yaml"
            operator_overlay.write_text(
                "splunkOperator:\n  podLabels:\n    test-overlay: operator\n",
                encoding="utf-8",
            )
            enterprise_overlay.write_text(
                "standalone:\n  additionalLabels:\n    test-overlay: enterprise\n",
                encoding="utf-8",
            )
            output_dir = root / "rendered"
            result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                str(output_dir),
                "--operator-values-overlay",
                str(operator_overlay),
                "--enterprise-values-overlay",
                str(enterprise_overlay),
                "--accept-splunk-general-terms",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = output_dir / "sok"
            self.assertEqual(
                (render_dir / "operator-values-overlay.yaml").read_bytes(),
                operator_overlay.read_bytes(),
            )
            self.assertEqual(
                (render_dir / "enterprise-values-overlay.yaml").read_bytes(),
                enterprise_overlay.read_bytes(),
            )
            self.assertEqual(
                (render_dir / "operator-values-overlay.yaml").stat().st_mode & 0o777,
                0o600,
            )
            self.assertEqual(
                (render_dir / "enterprise-values-overlay.yaml").stat().st_mode & 0o777,
                0o600,
            )
            operator_script = (render_dir / "helm-install-operator.sh").read_text(
                encoding="utf-8"
            )
            enterprise_script = (render_dir / "helm-install-enterprise.sh").read_text(
                encoding="utf-8"
            )
            self.assertIn(
                "values_args+=(--values operator-values-overlay.yaml)",
                operator_script,
            )
            self.assertIn(
                "values_args+=(--values enterprise-values-overlay.yaml)",
                enterprise_script,
            )
            self.assertLess(
                operator_script.index("--values operator-values.yaml"),
                operator_script.index("--values operator-values-overlay.yaml"),
            )
            self.assertLess(
                enterprise_script.index("--values enterprise-values.yaml"),
                enterprise_script.index("--values enterprise-values-overlay.yaml"),
            )

    def test_sok_rejects_inline_secrets_in_values_overlays(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            unsafe = root / "unsafe.yaml"
            unsafe.write_text(
                "clusterManager:\n  additionalAnnotations:\n"
                "    example.com/password: exposed\n",
                encoding="utf-8",
            )
            rejected = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                str(root / "rejected"),
                "--enterprise-values-overlay",
                str(unsafe),
                "--accept-splunk-general-terms",
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("literal or ambiguous sensitive field", rejected.stderr)

            safe = root / "safe.yaml"
            safe.write_text(
                "clusterManager:\n  appRepo:\n"
                "    defaults:\n      scope: cluster\n      volumeName: apps\n"
                "    appSources:\n      - name: indexer-apps\n"
                "        location: indexers/\n"
                "    volumes:\n      - name: apps\n        storageType: s3\n"
                "        provider: aws\n        region: us-east-1\n"
                "        path: splunk-apps/indexers\n"
                "        endpoint: https://s3.us-east-1.amazonaws.com\n"
                "        secretRef: existing-credentials\n",
                encoding="utf-8",
            )
            accepted = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                str(root / "accepted"),
                "--enterprise-values-overlay",
                str(safe),
                "--accept-splunk-general-terms",
            )
            self.assertEqual(
                accepted.returncode, 0, msg=accepted.stdout + accepted.stderr
            )

    def test_rendered_bundle_manifests_cover_every_asset_with_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            targets = (
                (
                    "sok",
                    [
                        "--target",
                        "sok",
                        "--architecture",
                        "s1",
                        "--accept-splunk-general-terms",
                    ],
                ),
                ("pod", ["--target", "pod", "--pod-profile", "pod-small"]),
            )
            for target, args in targets:
                with self.subTest(target=target):
                    output_dir = Path(tmpdir) / target
                    result = self.run_renderer(
                        *args,
                        "--output-dir",
                        str(output_dir),
                    )
                    self.assertEqual(
                        result.returncode,
                        0,
                        msg=result.stdout + result.stderr,
                    )
                    render_dir = output_dir / target
                    manifest = json.loads(
                        (render_dir / "bundle-manifest.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertEqual(manifest["algorithm"], "sha256")
                    expected_files = {
                        path.name
                        for path in render_dir.iterdir()
                        if path.is_file() and path.name != "bundle-manifest.json"
                    }
                    self.assertEqual(set(manifest["files"]), expected_files)
                    for name, digest in manifest["files"].items():
                        self.assertEqual(
                            digest,
                            hashlib.sha256(
                                (render_dir / name).read_bytes()
                            ).hexdigest(),
                        )

    def test_pod_profiles_render_cluster_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            expected_workers = {
                "pod-small": 8,
                "pod-medium": 11,
                "pod-large": 15,
                "pod-xlarge": 30,
            }
            for profile, workers in expected_workers.items():
                output_dir = Path(tmpdir) / profile
                result = self.run_renderer(
                    "--target",
                    "pod",
                    "--pod-profile",
                    profile,
                    "--output-dir",
                    str(output_dir),
                )
                self.assertEqual(
                    result.returncode, 0, msg=result.stdout + result.stderr
                )
                cluster_config = (output_dir / "pod" / "cluster-config.yaml").read_text(
                    encoding="utf-8"
                )
                self.assertIn(f"profile: {profile}", cluster_config)
                self.assertIn("kind: KubernetesCluster", cluster_config)
                self.assertIn("controllers:", cluster_config)
                self.assertIn("workers:", cluster_config)
                metadata = json.loads(
                    (output_dir / "pod" / "metadata.json").read_text(encoding="utf-8")
                )
                self.assertEqual(metadata["pod_base_profile"], profile)
                self.assertEqual(metadata["worker_count"], workers)

    def test_pod_web_docs_helper_starts_local_docs_server(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "rendered"
            result = self.run_renderer(
                "--target",
                "pod",
                "--pod-profile",
                "pod-small",
                "--output-dir",
                str(output_dir),
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            web_docs = (output_dir / "pod" / "web-docs.sh").read_text(encoding="utf-8")
            self.assertIn("kubernetes-installer-standalone --web --web.port", web_docs)
            self.assertNotIn("kubernetes-installer-standalone -web ", web_docs)
            self.assertIn("/docs", web_docs)
            self.assertNotIn("Splunk Web:", web_docs)

    def test_pod_es_profile_and_file_paths_do_not_leak_file_contents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            license_file = root / "splunk.lic"
            ssh_key = root / "ssh.key"
            license_file.write_text("LICENSE_SECRET_CONTENT\n", encoding="utf-8")
            ssh_key.write_text("SSH_SECRET_CONTENT\n", encoding="utf-8")
            ssh_key.chmod(0o600)
            output_dir = root / "rendered"

            result = self.run_renderer(
                "--target",
                "pod",
                "--pod-profile",
                "pod-small-es",
                "--output-dir",
                str(output_dir),
                "--license-file",
                str(license_file),
                "--ssh-private-key-file",
                str(ssh_key),
                "--premium-apps",
                "/apps/splunk_app_es.tgz",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            rendered = (output_dir / "pod" / "cluster-config.yaml").read_text(
                encoding="utf-8"
            )
            metadata = json.loads(
                (output_dir / "pod" / "metadata.json").read_text(encoding="utf-8")
            )
            self.assertIn("profile: pod-small", rendered)
            self.assertNotIn("profile: pod-small-es", rendered)
            self.assertIn('  - name: "es-sh"', rendered)
            self.assertIn("      premium:", rendered)
            self.assertIn('        - "/apps/splunk_app_es.tgz"', rendered)
            self.assertNotIn("enterpriseSecurity:", rendered)
            self.assertEqual(metadata["pod_profile"], "pod-small-es")
            self.assertEqual(metadata["pod_base_profile"], "pod-small")
            self.assertEqual(metadata["worker_count"], 9)
            self.assertEqual(rendered.count("Indexer C245"), 3)
            self.assertIn(str(license_file), rendered)
            self.assertIn(str(ssh_key), rendered)
            self.assertNotIn("LICENSE_SECRET_CONTENT", rendered)
            self.assertNotIn("SSH_SECRET_CONTENT", rendered)

    def test_pod_medium_large_es_profiles_keep_official_profile_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            expected = {
                "pod-medium-es": ("pod-medium", 14),
                "pod-large-es": ("pod-large", 18),
            }
            for profile, (base_profile, workers) in expected.items():
                output_dir = Path(tmpdir) / profile
                result = self.run_renderer(
                    "--target",
                    "pod",
                    "--pod-profile",
                    profile,
                    "--output-dir",
                    str(output_dir),
                )
                self.assertEqual(
                    result.returncode, 0, msg=result.stdout + result.stderr
                )
                rendered = (output_dir / "pod" / "cluster-config.yaml").read_text(
                    encoding="utf-8"
                )
                metadata = json.loads(
                    (output_dir / "pod" / "metadata.json").read_text(encoding="utf-8")
                )
                self.assertIn(f"profile: {base_profile}", rendered)
                self.assertNotIn(f"profile: {profile}", rendered)
                self.assertIn('  - name: "es-shc"', rendered)
                self.assertEqual(metadata["pod_profile"], profile)
                self.assertEqual(metadata["pod_base_profile"], base_profile)
                self.assertEqual(metadata["worker_count"], workers)

    def test_pod_xlarge_and_itsi_profiles_use_current_bundle_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            expected = {
                "pod-xlarge": ("pod-xlarge", 30),
                "pod-xlarge-es": ("pod-xlarge", 33),
                "pod-xlarge-itsi": ("pod-xlarge", 33),
            }
            for profile, (base_profile, worker_count) in expected.items():
                with self.subTest(profile=profile):
                    output_dir = Path(tmpdir) / profile
                    result = self.run_renderer(
                        "--target",
                        "pod",
                        "--pod-profile",
                        profile,
                        "--output-dir",
                        str(output_dir),
                    )
                    self.assertEqual(
                        result.returncode,
                        0,
                        msg=result.stdout + result.stderr,
                    )
                    config = (output_dir / "pod" / "cluster-config.yaml").read_text(
                        encoding="utf-8"
                    )
                    metadata = json.loads(
                        (output_dir / "pod" / "metadata.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertIn(f"profile: {base_profile}", config)
                    self.assertEqual(metadata["worker_count"], worker_count)
                    self.assertEqual(config.count("  - address:"), worker_count + 3)

            unsupported = self.run_renderer(
                "--target",
                "pod",
                "--pod-profile",
                "pod-xlarge",
                "--pod-version",
                "10.2.1_1.5.0",
                "--output-dir",
                str(Path(tmpdir) / "unsupported"),
            )
            self.assertNotEqual(unsupported.returncode, 0)
            self.assertIn("POD X-Large and ITSI require", unsupported.stderr)

    def test_pod_itsi_profile_renders_secondary_tier_and_app_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "rendered"
            result = self.run_renderer(
                "--target",
                "pod",
                "--pod-profile",
                "pod-medium-itsi",
                "--output-dir",
                str(output_dir),
                "--primary-search-name",
                "core-search",
                "--secondary-search-name",
                "itsi-search",
                "--itsi-apps",
                "/apps/itsi-core.tgz,/apps/itsi-content.tgz",
                "--itsi-jdk-sha256",
                "0" * 64,
                "--license-manager-apps",
                "/apps/SA-ITSI-Licensechecker.tgz,/apps/SA-UserAccess.tgz",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            config = (output_dir / "pod" / "cluster-config.yaml").read_text(
                encoding="utf-8"
            )
            metadata = json.loads(
                (output_dir / "pod" / "metadata.json").read_text(encoding="utf-8")
            )
            self.assertIn('  - name: "core-search"', config)
            self.assertIn('  - name: "itsi-search"', config)
            self.assertIn('        - "/apps/itsi-core.tgz"', config)
            self.assertIn('        - "/apps/itsi-content.tgz"', config)
            self.assertIn("licensemanager:\n  apps:\n    local:", config)
            self.assertIn('      - "/apps/SA-ITSI-Licensechecker.tgz"', config)
            self.assertIn('      - "/apps/SA-UserAccess.tgz"', config)
            self.assertNotIn("premium:", config)
            self.assertEqual(metadata["pod_profile"], "pod-medium-itsi")
            self.assertEqual(metadata["pod_base_profile"], "pod-medium")
            self.assertEqual(metadata["worker_count"], 14)

    def test_pod_tls_requires_certificate_and_key_and_never_embeds_contents(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            certificate = root / "fullchain.pem"
            private_key = root / "privkey.pem"
            certificate.write_text("CERTIFICATE_SECRET_CONTENT\n", encoding="utf-8")
            private_key.write_text("PRIVATE_KEY_SECRET_CONTENT\n", encoding="utf-8")
            private_key.chmod(0o600)

            unpaired = self.run_renderer(
                "--target",
                "pod",
                "--pod-profile",
                "pod-small",
                "--output-dir",
                str(root / "unpaired"),
                "--ingress-certificate-file",
                str(certificate),
            )
            self.assertNotEqual(unpaired.returncode, 0)
            self.assertIn("must be provided together", unpaired.stderr)

            output_dir = root / "rendered"
            paired = self.run_renderer(
                "--target",
                "pod",
                "--pod-profile",
                "pod-small",
                "--output-dir",
                str(output_dir),
                "--ingress-certificate-file",
                str(certificate),
                "--ingress-private-key-file",
                str(private_key),
                "--ingress-ca-file",
                str(certificate),
                "--ingress-domain",
                "pod.example.com",
            )
            self.assertEqual(paired.returncode, 0, msg=paired.stdout + paired.stderr)
            config = (output_dir / "pod" / "cluster-config.yaml").read_text(
                encoding="utf-8"
            )
            self.assertIn("certificate:\n  ingress:", config)
            self.assertIn(f'    certificate: "{certificate}"', config)
            self.assertIn(f'    privateKey: "{private_key}"', config)
            self.assertNotIn("CERTIFICATE_SECRET_CONTENT", config)
            self.assertNotIn("PRIVATE_KEY_SECRET_CONTENT", config)

    def test_pod_enforces_exact_unique_controller_and_worker_ip_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            two_controllers = self.run_renderer(
                "--target",
                "pod",
                "--pod-profile",
                "pod-small",
                "--output-dir",
                str(Path(tmpdir) / "controllers"),
                "--controller-ips",
                "10.0.0.1,10.0.0.2",
            )
            self.assertNotEqual(two_controllers.returncode, 0)
            self.assertIn("requires exactly 3 addresses", two_controllers.stderr)

            seven_workers = self.run_renderer(
                "--target",
                "pod",
                "--pod-profile",
                "pod-small",
                "--output-dir",
                str(Path(tmpdir) / "workers"),
                "--worker-ips",
                ",".join(f"10.0.1.{item}" for item in range(1, 8)),
            )
            self.assertNotEqual(seven_workers.returncode, 0)
            self.assertIn("requires exactly 8 addresses", seven_workers.stderr)

            overlap = self.run_renderer(
                "--target",
                "pod",
                "--pod-profile",
                "pod-small",
                "--output-dir",
                str(Path(tmpdir) / "overlap"),
                "--controller-ips",
                "10.0.0.1,10.0.0.2,10.0.0.3",
                "--worker-ips",
                "10.0.0.3,10.0.1.2,10.0.1.3,10.0.1.4,10.0.1.5,10.0.1.6,10.0.1.7,10.0.1.8",
            )
            self.assertNotEqual(overlap.returncode, 0)
            self.assertIn(
                "Controller and worker IP addresses must be unique", overlap.stderr
            )

            output_dir = Path(tmpdir) / "valid"
            valid = self.run_renderer(
                "--target",
                "pod",
                "--pod-profile",
                "pod-small",
                "--output-dir",
                str(output_dir),
                "--controller-ips",
                "10.0.0.1,10.0.0.2,10.0.0.3",
                "--worker-ips",
                ",".join(f"10.0.1.{item}" for item in range(1, 9)),
            )
            self.assertEqual(valid.returncode, 0, msg=valid.stdout + valid.stderr)
            config = (output_dir / "pod" / "cluster-config.yaml").read_text(
                encoding="utf-8"
            )
            self.assertEqual(config.count("# Controller C225"), 3)
            self.assertEqual(config.count("  - address:"), 11)

    def test_pod_metadata_is_bundle_specific_and_omits_sok_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            installer_path = Path(tmpdir) / "kubernetes-installer-standalone"
            installer_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            installer_path.chmod(0o700)
            installer = str(installer_path)
            installer_sha256 = hashlib.sha256(installer_path.read_bytes()).hexdigest()
            result = self.run_renderer(
                "--target",
                "pod",
                "--pod-profile",
                "pod-xlarge",
                "--output-dir",
                tmpdir,
                "--pod-version",
                "10.4.0_1.6.0",
                "--installer-path",
                installer,
                "--installer-sha256",
                installer_sha256,
                "--json",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            metadata = json.loads(
                (Path(tmpdir) / "pod" / "metadata.json").read_text(encoding="utf-8")
            )
            self.assertIsNone(payload["architecture"])
            self.assertIsNone(payload["versions"]["chart"])
            self.assertIsNone(payload["versions"]["splunk_operator"])
            self.assertIsNone(payload["versions"]["splunk_image"])
            self.assertEqual(payload["versions"]["splunk_enterprise"], "10.4.0")
            self.assertEqual(payload["versions"]["pod_bundle"], "10.4.0_1.6.0")
            self.assertEqual(payload["versions"]["pod_installer"], "1.6.0")
            self.assertEqual(metadata["pod_version"], "10.4.0_1.6.0")
            self.assertEqual(metadata["bundled_splunk_version"], "10.4.0")
            self.assertEqual(metadata["installer_version"], "1.6.0")
            self.assertEqual(metadata["installer_path"], installer)
            self.assertEqual(metadata["worker_count"], 30)
            for sok_key in ("operator_version", "chart_version", "splunk_image"):
                self.assertNotIn(sok_key, metadata)

    def test_pod_default_config_has_no_fake_optional_app_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--target",
                "pod",
                "--pod-profile",
                "pod-medium",
                "--output-dir",
                tmpdir,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            config = (Path(tmpdir) / "pod" / "cluster-config.yaml").read_text(
                encoding="utf-8"
            )
            for placeholder in (
                "/path/to/indexer-app.tgz",
                "./path/to/myapp.tgz",
                "/path/to/sh-app.tar.gz",
                "./apps/splunk_app_es.tgz",
            ):
                self.assertNotIn(placeholder, config)
            self.assertIn("clustermanager:\n  apps:\n    cluster:\n      []", config)
            self.assertIn("searchheadcluster:", config)
            self.assertGreaterEqual(config.count("[]"), 4)

    def test_sok_overlay_and_endpoint_guards_cover_flow_json_and_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cases = {
                "misspelled-role.yaml": (
                    "standalnoe:\n  additionalLabels:\n    example.com/intent: ignored\n"
                ),
                "escaped-image.yaml": '{"im\\u0061ge":{"repository":"splunk/splunk:11.0.0"}}\n',
                "namespace.yaml": "standalone: {namespaceOverride: kube-system}\n",
                "secret.yaml": (
                    "extraManifests:\n"
                    "  - apiVersion: v1\n"
                    "    kind: &secret_kind Secret\n"
                    "    stringData: {credential: supersecret}\n"
                ),
                "hidden-pem.yaml": (
                    "standalone:\n  extraEnv:\n"
                    "    - name: HARMLESS_BLOB\n"
                    "      value: |\n"
                    "        -----BEGIN PRIVATE KEY-----\n"
                    "        concealed\n"
                    "        -----END PRIVATE KEY-----\n"
                ),
                "hidden-cloud-key.yaml": (
                    "standalone:\n  additionalLabels:\n"
                    "    harmless: AKIAIOSFODNN7EXAMPLE\n"
                ),
            }
            for filename, content in cases.items():
                with self.subTest(filename=filename):
                    overlay = root / filename
                    overlay.write_text(content, encoding="utf-8")
                    result = self.run_renderer(
                        "--target",
                        "sok",
                        "--architecture",
                        "s1",
                        "--output-dir",
                        str(root / (filename + ".out")),
                        "--enterprise-values-overlay",
                        str(overlay),
                        "--accept-splunk-general-terms",
                    )
                    self.assertNotEqual(result.returncode, 0)

            endpoint = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                str(root / "endpoint"),
                "--smartstore-endpoint",
                "https://s3.example.test?X-Amz-Signature=secret",
                "--accept-splunk-general-terms",
            )
            self.assertNotEqual(endpoint.returncode, 0)
            self.assertIn("query string or fragment", endpoint.stderr)

    def test_verified_private_images_accept_matching_digest_pins(self) -> None:
        digest = "a" * 64
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                tmpdir,
                "--splunk-image",
                f"registry.example/splunk:10.4.0@sha256:{digest}",
                "--operator-image",
                f"registry.example/operator:3.1.0@sha256:{digest}",
                "--accept-splunk-general-terms",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

    def test_sok_rejects_malformed_oci_image_references(self) -> None:
        digest = "a" * 64
        with tempfile.TemporaryDirectory() as tmpdir:
            cases = (
                "https://registry.example/splunk:10.4.0",
                "registry.example/Upper/splunk:10.4.0",
                "registry.example/splunk:10.4.0 trailing",
                f"registry.example/splunk:10.4.0@sha256:{digest.upper()}",
                "registry.example:70000/splunk:10.4.0",
                "example.com:/splunk:10.4.0",
            )
            for index, image in enumerate(cases):
                with self.subTest(image=image):
                    result = self.run_renderer(
                        "--target",
                        "sok",
                        "--architecture",
                        "s1",
                        "--output-dir",
                        str(Path(tmpdir) / str(index)),
                        "--splunk-image",
                        image,
                        "--allow-unverified-versions",
                        "--accept-splunk-general-terms",
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("--splunk-image", result.stderr)

    def test_sok_app_repo_requires_source_local_premium_properties(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            overlay = root / "premium-default.yaml"
            overlay.write_text(
                "standalone:\n  appRepo:\n"
                "    defaults:\n      scope: premiumApps\n      volumeName: apps\n"
                "      premiumAppsProps:\n        type: enterpriseSecurity\n"
                "    appSources:\n      - name: es\n        location: es/\n"
                "    volumes:\n      - name: apps\n        storageType: s3\n"
                "        provider: aws\n        region: us-east-1\n"
                "        path: splunk-apps/es\n"
                "        endpoint: https://s3.us-east-1.amazonaws.com\n"
                "        secretRef: existing-credentials\n",
                encoding="utf-8",
            )
            result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                str(root / "out"),
                "--enterprise-values-overlay",
                str(overlay),
                "--accept-splunk-general-terms",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("defaults are malformed", result.stderr)

    def test_sok_app_install_period_is_support_directed_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            overlay = root / "support-directed.yaml"
            overlay.write_text(
                "standalone:\n  appRepo:\n    appInstallPeriodSeconds: 30\n",
                encoding="utf-8",
            )
            result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                str(root / "out"),
                "--enterprise-values-overlay",
                str(overlay),
                "--accept-splunk-general-terms",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("support-directed only", result.stderr)

    def test_sok_admin_managed_pv_annotation_requires_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            overlay = root / "admin-pv.yaml"
            overlay.write_text(
                "standalone:\n  additionalAnnotations:\n"
                "    enterprise.splunk.com/admin-managed-pv: 'true'\n",
                encoding="utf-8",
            )
            result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                str(root / "out"),
                "--enterprise-values-overlay",
                str(overlay),
                "--accept-splunk-general-terms",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("admin-managed PVs", result.stderr)

    def test_sok_rejects_overlay_identity_injection_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for index, annotation in enumerate(
                (
                    "eks.amazonaws.com/role-arn",
                    "eks.amazonaws.com/audience",
                    "eks.amazonaws.com/token-expiration",
                    "eks.amazonaws.com/sts-regional-endpoints",
                    "eks.amazonaws.com/skip-containers",
                )
            ):
                overlay = root / f"identity-{index}.yaml"
                overlay.write_text(
                    "standalone:\n  additionalAnnotations:\n"
                    f"    {annotation}: reviewed-override\n",
                    encoding="utf-8",
                )
                result = self.run_renderer(
                    "--target",
                    "sok",
                    "--architecture",
                    "s1",
                    "--output-dir",
                    str(root / f"out-{index}"),
                    "--enterprise-values-overlay",
                    str(overlay),
                    "--accept-splunk-general-terms",
                )
                with self.subTest(annotation=annotation):
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("EKS identity injection", result.stderr)

    def test_sok_app_repo_matches_operator_3_1_semantics(self) -> None:
        volume = (
            "      - name: apps\n        storageType: s3\n"
            "        provider: aws\n        region: us-east-1\n"
            "        path: splunk-apps/local\n"
            "        endpoint: https://s3.us-east-1.amazonaws.com\n"
            "        secretRef: existing-credentials\n"
        )
        cases = {
            "invalid-default-scope": (
                "monitoringConsole:\n  appRepo:\n"
                "    defaults:\n      scope: cluster\n      volumeName: apps\n"
                "    appSources:\n      - name: local\n        location: local/\n"
                "        scope: local\n"
                "    volumes:\n" + volume
            ),
            "concatenated-source-collision": (
                "standalone:\n  appRepo:\n"
                "    defaults:\n      scope: local\n"
                "    appSources:\n      - name: one\n        location: bc\n"
                "        volumeName: a\n      - name: two\n        location: c\n"
                "        volumeName: ab\n"
                "    volumes:\n"
                + volume.replace("name: apps", "name: a")
                + volume.replace("name: apps", "name: ab")
            ),
            "invalid-endpoint-port": (
                "standalone:\n  appRepo:\n"
                "    defaults:\n      scope: local\n      volumeName: apps\n"
                "    appSources:\n      - name: local\n        location: local/\n"
                "    volumes:\n"
                + volume.replace(
                    "https://s3.us-east-1.amazonaws.com",
                    "https://s3.us-east-1.amazonaws.com:99999",
                )
            ),
            "oversized-secret-reference": (
                "standalone:\n  appRepo:\n"
                "    defaults:\n      scope: local\n      volumeName: apps\n"
                "    appSources:\n      - name: local\n        location: local/\n"
                "    volumes:\n"
                + volume.replace("existing-credentials", "a" * 254)
            ),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for name, content in cases.items():
                with self.subTest(name=name):
                    overlay = root / f"{name}.yaml"
                    overlay.write_text(content, encoding="utf-8")
                    result = self.run_renderer(
                        "--target",
                        "sok",
                        "--architecture",
                        "s1",
                        "--output-dir",
                        str(root / f"{name}.out"),
                        "--enterprise-values-overlay",
                        str(overlay),
                        "--accept-splunk-general-terms",
                    )
                    self.assertNotEqual(result.returncode, 0)

    def test_bundle_verifier_rejects_symlinks_hardlinks_and_fifos(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for attack in ("symlink", "hardlink", "fifo"):
                with self.subTest(attack=attack):
                    output = root / attack
                    rendered = self.run_renderer(
                        "--target",
                        "sok",
                        "--architecture",
                        "s1",
                        "--output-dir",
                        str(output),
                        "--accept-splunk-general-terms",
                    )
                    self.assertEqual(
                        rendered.returncode,
                        0,
                        msg=rendered.stdout + rendered.stderr,
                    )
                    bundle = output / "sok"
                    victim = bundle / "README.md"
                    original = root / f"{attack}-original"
                    victim.replace(original)
                    if attack == "symlink":
                        victim.symlink_to(original)
                    elif attack == "hardlink":
                        os.link(original, victim)
                    else:
                        os.mkfifo(victim)
                    checked = subprocess.run(
                        [
                            sys.executable,
                            str(bundle / "bundle-verify.py"),
                            "verify",
                            str(bundle),
                            "sok",
                        ],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=5,
                    )
                    self.assertNotEqual(checked.returncode, 0)
                    self.assertIn("ERROR:", checked.stderr)

    def test_bundle_verifier_rejects_permission_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rendered = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                tmpdir,
                "--accept-splunk-general-terms",
            )
            self.assertEqual(
                rendered.returncode, 0, msg=rendered.stdout + rendered.stderr
            )
            bundle = Path(tmpdir) / "sok"
            (bundle / "apply.sh").chmod(0o777)
            checked = subprocess.run(
                [
                    sys.executable,
                    str(bundle / "bundle-verify.py"),
                    "verify",
                    str(bundle),
                    "sok",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn("owner/mode differs", checked.stderr)

    def test_pod_rejects_invalid_ssh_users(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            for index, user in enumerate(("", "Root", "bad user", "a" * 33)):
                with self.subTest(user=user):
                    result = self.run_renderer(
                        "--target",
                        "pod",
                        "--pod-profile",
                        "pod-small",
                        "--output-dir",
                        str(Path(tmpdir) / str(index)),
                        "--ssh-user",
                        user,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("--ssh-user", result.stderr)

    def test_pod_rejects_non_unicast_node_addresses(self) -> None:
        invalid = ("0.0.0.0", "127.0.0.1", "169.254.1.2", "224.0.0.1", "255.255.255.255")
        with tempfile.TemporaryDirectory() as tmpdir:
            valid_controllers = ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
            valid_workers = [f"10.0.1.{index}" for index in range(1, 9)]
            for index, address in enumerate(invalid):
                with self.subTest(address=address):
                    controllers = [address, *valid_controllers[1:]]
                    result = self.run_renderer(
                        "--target",
                        "pod",
                        "--pod-profile",
                        "pod-small",
                        "--output-dir",
                        str(Path(tmpdir) / str(index)),
                        "--controller-ips",
                        ",".join(controllers),
                        "--worker-ips",
                        ",".join(valid_workers),
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("non-unicast", result.stderr)

    def test_bundle_integrity_tracks_external_input_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            license_file = root / "splunk.lic"
            key = root / "ssh.key"
            installer = root / "installer"
            license_file.write_text("reviewed\n", encoding="utf-8")
            key.write_text("key\n", encoding="utf-8")
            key.chmod(0o600)
            installer.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            installer.chmod(0o700)
            installer_sha256 = hashlib.sha256(installer.read_bytes()).hexdigest()
            output = root / "out"
            rendered = self.run_renderer(
                "--target",
                "pod",
                "--pod-profile",
                "pod-small",
                "--output-dir",
                str(output),
                "--license-file",
                str(license_file),
                "--ssh-private-key-file",
                str(key),
                "--installer-path",
                str(installer),
                "--installer-sha256",
                installer_sha256,
            )
            self.assertEqual(
                rendered.returncode, 0, msg=rendered.stdout + rendered.stderr
            )
            license_file.write_text("changed\n", encoding="utf-8")
            checked = subprocess.run(
                [
                    "bash",
                    str(VALIDATOR),
                    "--target",
                    "pod",
                    "--output-dir",
                    str(output),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn("external file drift", checked.stderr + checked.stdout)

    def test_pod_rejects_profile_inapplicable_apps_and_unknown_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            too_old = self.run_renderer(
                "--target",
                "pod",
                "--pod-profile",
                "pod-small",
                "--output-dir",
                str(Path(tmpdir) / "too-old"),
                "--pod-version",
                "10.0.0_1.4.0",
                "--allow-unverified-versions",
            )
            self.assertNotEqual(too_old.returncode, 0)
            self.assertIn("requires bundle 10.2.1_1.5.0 or later", too_old.stderr)
            for feature_args, message in (
                (("--ingress-domain", "pod.example.com"), "name-based routing"),
                (
                    ("--license-manager-apps", "/apps/lm-app.tgz"),
                    "License Manager apps",
                ),
            ):
                feature_too_old = self.run_renderer(
                    "--target",
                    "pod",
                    "--pod-profile",
                    "pod-small",
                    "--output-dir",
                    str(Path(tmpdir) / message.replace(" ", "-")),
                    "--pod-version",
                    "10.2.1_1.5.0",
                    "--allow-unverified-versions",
                    *feature_args,
                )
                self.assertNotEqual(feature_too_old.returncode, 0)
                self.assertIn(message, feature_too_old.stderr)
            wrong_scope = self.run_renderer(
                "--target",
                "pod",
                "--pod-profile",
                "pod-small",
                "--output-dir",
                str(Path(tmpdir) / "scope"),
                "--search-apps",
                "/apps/not-used.tgz",
            )
            self.assertNotEqual(wrong_scope.returncode, 0)
            self.assertIn("not used by POD Small", wrong_scope.stderr)
            unknown = self.run_renderer(
                "--target",
                "pod",
                "--pod-profile",
                "pod-small",
                "--output-dir",
                str(Path(tmpdir) / "version"),
                "--pod-version",
                "10.5.0_1.7.0",
            )
            self.assertNotEqual(unknown.returncode, 0)
            self.assertIn("Unverified POD bundle", unknown.stderr)

    def test_pod_readiness_parser_rejects_unparsed_init_status(self) -> None:
        tree = ast.parse(RENDERER.read_text(encoding="utf-8"))
        guards = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if any(
                isinstance(target, ast.Name) and target.id == "pod_health_code"
                for target in node.targets
            ):
                value = ast.literal_eval(node.value)
                if isinstance(value, str):
                    guards.append(value)
        pod_guard = guards[-1]
        workers = "\n".join(f"worker-{index} Ready" for index in range(1, 9))
        healthy_rows = [
            "splunk-idx-indexer-0 1/1 Running",
            "splunk-idx-indexer-1 1/1 Running",
            "splunk-idx-indexer-2 1/1 Running",
            "splunk-core-search-standalone-0 1/1 Running",
            "splunk-cm-cluster-manager-0 1/1 Running",
            "splunk-lm-license-manager-0 1/1 Running",
            "splunk-mc-monitoring-console-0 1/1 Running",
            "seaweedfs-master-0 1/1 Running",
        ]
        expected_roles = {
            "indexer": 3,
            "search": 1,
            "cluster_manager": 1,
            "license_manager": 1,
            "monitoring_console": 1,
            "deployer": 0,
        }

        def check(rows: list[str]) -> subprocess.CompletedProcess:
            environment = os.environ.copy()
            environment["POD_WORKERS_STATUS"] = workers
            environment["POD_PODS_STATUS"] = "\n".join(rows)
            return subprocess.run(
                [sys.executable, "-c", pod_guard, "8", json.dumps(expected_roles)],
                capture_output=True,
                text=True,
                check=False,
                env=environment,
            )

        self.assertEqual(check(healthy_rows).returncode, 0)
        self.assertNotEqual(
            check([*healthy_rows, "coredns-abc 0/1 Init:0/1"]).returncode,
            0,
        )

    def test_pod_artifact_validator_rejects_empty_es_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            indexer = root / "indexer.tgz"
            premium = root / "premium.tgz"
            for path, app_root in (
                (indexer, "Splunk_TA_ForIndexers"),
                (premium, "SplunkEnterpriseSecuritySuite"),
            ):
                with tarfile.open(path, "w:gz") as archive:
                    member = tarfile.TarInfo(app_root + "/")
                    member.type = tarfile.DIRTYPE
                    archive.addfile(member)
            metadata = root / "metadata.json"
            metadata.write_text(
                json.dumps(
                    {
                        "pod_profile": "pod-small-es",
                        "indexer_apps": [str(indexer)],
                        "premium_apps": [str(premium)],
                    }
                ),
                encoding="utf-8",
            )
            checked = subprocess.run(
                ["python3", str(POD_ARTIFACTS), str(metadata)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn("no regular files", checked.stderr)

    def test_pod_index_apps_enforce_smartstore_managed_index_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cases = {
                "valid": (
                    b"[orders]\n"
                    b"homePath = $SPLUNK_DB/$_index_name/db\n"
                    b"coldPath = $SPLUNK_DB/$_index_name/colddb\n"
                    b"thawedPath = $SPLUNK_DB/$_index_name/thaweddb\n",
                    True,
                    "",
                ),
                "replication": (
                    b"[orders]\n"
                    b"homePath = $SPLUNK_DB/$_index_name/db\n"
                    b"coldPath = $SPLUNK_DB/$_index_name/colddb\n"
                    b"thawedPath = $SPLUNK_DB/$_index_name/thaweddb\n"
                    b"repFactor = auto\n",
                    False,
                    "must not set repfactor",
                ),
                "missing-paths": (
                    b"[orders]\nhomePath = $SPLUNK_DB/$_index_name/db\n",
                    False,
                    "missing required coldpath, thawedpath",
                ),
            }
            for name, (indexes_conf, succeeds, message) in cases.items():
                with self.subTest(name=name):
                    archive = root / f"{name}.tgz"
                    self.write_app_archive(
                        archive,
                        [f"indexes_{name.replace('-', '_')}"],
                        {
                            f"indexes_{name.replace('-', '_')}/default/indexes.conf": (
                                indexes_conf,
                                0o644,
                            )
                        },
                    )
                    metadata = root / f"{name}.json"
                    metadata.write_text(
                        json.dumps(
                            {
                                "pod_profile": "pod-small",
                                "indexer_apps": [str(archive)],
                            }
                        ),
                        encoding="utf-8",
                    )
                    checked = subprocess.run(
                        [sys.executable, str(POD_ARTIFACTS), str(metadata)],
                        cwd=REPO_ROOT,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(
                        checked.returncode == 0,
                        succeeds,
                        msg=checked.stdout + checked.stderr,
                    )
                    if message:
                        self.assertIn(message, checked.stderr)

    def test_pod_itsi_repacked_inventory_matches_source_bundle(self) -> None:
        source_roots = {
            "itsi",
            "DA-ITSI-APPSERVER",
            "DA-ITSI-DATABASE",
            "DA-ITSI-EUEM",
            "DA-ITSI-LB",
            "DA-ITSI-OS",
            "DA-ITSI-STORAGE",
            "DA-ITSI-VIRTUALIZATION",
            "DA-ITSI-WEBSERVER",
            "SA-IndexCreation",
            "SA-ITOA",
            "SA-ITSI-AI-Summarization",
            "SA-ITSI-AlertCorrelation",
            "SA-ITSI-AT-Recommendations",
            "SA-ITSI-ATAD",
            "SA-ITSI-CustomModuleViz",
            "SA-ITSI-DriftDetection",
            "SA-ITSI-Licensechecker",
            "SA-ITSI-MetricAD",
            "SA-UserAccess",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "itsi-4.21.2.spl"
            self.write_app_archive(source, sorted(source_roots), version="4.21.2")
            archives = {}
            for app_root in sorted(source_roots):
                archive = root / f"{app_root}.tgz"
                self.write_app_archive(archive, [app_root], version="4.21.2")
                archives[app_root] = archive
            jdk = root / "jdk.tgz"
            elf = bytearray(8192)
            elf[:4] = b"\x7fELF"
            elf[4] = 2
            elf[5] = 1
            elf[16:18] = (3).to_bytes(2, "little")
            elf[18:20] = (62).to_bytes(2, "little")
            elf[20:24] = (1).to_bytes(4, "little")
            elf[32:40] = (64).to_bytes(8, "little")
            elf[52:54] = (64).to_bytes(2, "little")
            elf[54:56] = (56).to_bytes(2, "little")
            elf[56:58] = (1).to_bytes(2, "little")
            elf[64:68] = (1).to_bytes(4, "little")
            elf[68:72] = (5).to_bytes(4, "little")
            elf[72:80] = (0).to_bytes(8, "little")
            elf[96:104] = len(elf).to_bytes(8, "little")
            elf[104:112] = len(elf).to_bytes(8, "little")
            self.write_app_archive(
                jdk,
                ["jdk"],
                {
                    "jdk/default/app.conf": (
                        b"[install]\nstate = enabled\nis_configured = true\n\n"
                        b"[ui]\nshow_in_nav = false\n",
                        0o644,
                    ),
                    "jdk/metadata/default.meta": (
                        b"[]\naccess = read : [ * ], write : [ admin ]\n"
                        b"export = system\n\n[savedsearches]\nowner = admin\n\n"
                        b"[governance]\naccess = read : [ * ], write : [ * ]\n",
                        0o644,
                    ),
                    "jdk/release": (b'JAVA_VERSION="17.0.12"\n', 0o644),
                    "jdk/bin/java": (bytes(elf), 0o755),
                    "jdk/bin/javac": (bytes(elf), 0o755),
                },
            )
            search_apps = [jdk] + [
                archives[name]
                for name in sorted(source_roots - {"SA-ITSI-Licensechecker"})
            ]
            metadata = root / "metadata.json"
            payload = {
                "pod_profile": "pod-small-itsi",
                "itsi_source_bundle": str(source),
                "itsi_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "itsi_jdk_sha256": hashlib.sha256(jdk.read_bytes()).hexdigest(),
                "itsi_apps": [str(path) for path in search_apps],
                "indexer_apps": [str(archives["SA-IndexCreation"])],
                "license_manager_apps": [
                    str(archives["SA-ITSI-Licensechecker"]),
                    str(archives["SA-UserAccess"]),
                ],
            }
            metadata.write_text(json.dumps(payload), encoding="utf-8")
            valid = subprocess.run(
                ["python3", str(POD_ARTIFACTS), str(metadata)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(valid.returncode, 0, msg=valid.stdout + valid.stderr)
            payload["itsi_apps"] = payload["itsi_apps"][:-1]
            metadata.write_text(json.dumps(payload), encoding="utf-8")
            incomplete = subprocess.run(
                ["python3", str(POD_ARTIFACTS), str(metadata)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(incomplete.returncode, 0)
            self.assertIn("inventory is incomplete", incomplete.stderr)

    @unittest.skipUnless(shutil.which("openssl"), "openssl is required")
    def test_pod_tls_artifacts_require_matching_wildcard_keypair(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ca_config = root / "ca.cnf"
            ca_config.write_text(
                "[req]\ndistinguished_name=dn\nx509_extensions=v3_ca\nprompt=no\n"
                "[dn]\nCN=POD Test CA\n[v3_ca]\n"
                "basicConstraints=critical,CA:TRUE\n"
                "keyUsage=critical,keyCertSign,cRLSign\n"
                "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid:always\n",
                encoding="utf-8",
            )
            ca_certificate = root / "ca.pem"
            ca_key = root / "ca.key"
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-days",
                    "90",
                    "-keyout",
                    str(ca_key),
                    "-out",
                    str(ca_certificate),
                    "-config",
                    str(ca_config),
                ],
                check=True,
                capture_output=True,
            )
            config = root / "leaf.cnf"
            config.write_text(
                "[req]\ndistinguished_name=dn\nx509_extensions=v3\nprompt=no\n"
                "[dn]\nCN=*.pod.example.com\n[v3]\n"
                "subjectAltName=DNS:*.pod.example.com\n"
                "basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\n"
                "extendedKeyUsage=serverAuth\n",
                encoding="utf-8",
            )
            certificate = root / "cert.pem"
            key = root / "key.pem"
            request = root / "leaf.csr"
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-new",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-keyout",
                    str(key),
                    "-out",
                    str(request),
                    "-config",
                    str(config),
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "openssl",
                    "x509",
                    "-req",
                    "-in",
                    str(request),
                    "-CA",
                    str(ca_certificate),
                    "-CAkey",
                    str(ca_key),
                    "-CAcreateserial",
                    "-days",
                    "40",
                    "-out",
                    str(certificate),
                    "-extfile",
                    str(config),
                    "-extensions",
                    "v3",
                ],
                check=True,
                capture_output=True,
            )
            key.chmod(0o600)
            metadata = root / "metadata.json"
            payload = {
                "pod_profile": "pod-small",
                "ingress_certificate_file": str(certificate),
                "ingress_private_key_file": str(key),
                "ingress_domain": "pod.example.com",
                "ingress_ca_file": str(ca_certificate),
            }
            metadata.write_text(json.dumps(payload), encoding="utf-8")
            valid = subprocess.run(
                ["python3", str(POD_ARTIFACTS), str(metadata)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(valid.returncode, 0, msg=valid.stdout + valid.stderr)

            other_key = root / "other.key"
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "RSA", "-out", str(other_key)],
                check=True,
                capture_output=True,
            )
            payload["ingress_private_key_file"] = str(other_key)
            metadata.write_text(json.dumps(payload), encoding="utf-8")
            mismatch = subprocess.run(
                ["python3", str(POD_ARTIFACTS), str(metadata)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(mismatch.returncode, 0)
            self.assertIn("do not match", mismatch.stderr)


if __name__ == "__main__":
    unittest.main()
