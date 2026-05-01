#!/usr/bin/env python3
"""Regression tests for Splunk Enterprise Kubernetes asset rendering."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT


RENDERER = (
    REPO_ROOT
    / "skills/splunk-enterprise-kubernetes-setup/scripts/render_assets.py"
)


class SplunkEnterpriseKubernetesRendererTests(unittest.TestCase):
    def run_renderer(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(RENDERER), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

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
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                values = (output_dir / "sok" / "enterprise-values.yaml").read_text(
                    encoding="utf-8"
                )
                self.assertIn(f"  {architecture}:\n    enabled: true", values)
                if architecture == "m4":
                    self.assertIn("allSites:", values)
                if architecture == "c3":
                    self.assertIn("indexerClusters:", values)
                    self.assertIn("searchHeadClusters:", values)

    def test_sok_requires_explicit_terms_for_splunk_10(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--target",
                "sok",
                "--architecture",
                "s1",
                "--output-dir",
                tmpdir,
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

    def test_sok_pins_helm_chart_version_in_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "rendered"
            result = self.run_renderer(
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
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            operator_script = (output_dir / "sok" / "helm-install-operator.sh").read_text(
                encoding="utf-8"
            )
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
            self.assertTrue((output_dir / "sok" / "create-license-configmap.sh").exists())
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
            self.assertFalse((output_dir / "sok" / "create-license-configmap.sh").exists())
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
                "--smartstore-region or --smartstore-endpoint",
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
                "3",
                "--site-zones",
                "us-west-2a,us-west-2b,us-west-2c",
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
            self.assertIn('zone: "us-west-2c"', values)
            self.assertIn("2 indexers per site, 6 total indexers", values)
            self.assertIn("M4 zone pinning: enabled", values)
            self.assertNotIn('zone: "us-west-2"', values)
            search_head_block = values.split("    searchHeadClusters:", 1)[1].split(
                "# Effective M4 defaults:", 1
            )[0]
            self.assertIn("        site: site0", search_head_block)
            self.assertNotIn("zone:", search_head_block)

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

    def test_sok_renders_smartstore_license_and_does_not_leak_secret_contents(self) -> None:
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
            enterprise_values = (output_dir / "sok" / "enterprise-values.yaml").read_text(
                encoding="utf-8"
            )
            self.assertIn(
                'image:\n  repository: "splunk/splunk:10.2.0"\n  imagePullPolicy: "IfNotPresent"',
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

    def test_pod_profiles_render_cluster_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            expected_workers = {
                "pod-small": 8,
                "pod-medium": 11,
                "pod-large": 15,
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
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
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
            self.assertIn("kubernetes-installer-standalone -web --web.port", web_docs)
            self.assertIn("/docs", web_docs)
            self.assertNotIn("Splunk Web:", web_docs)

    def test_pod_es_profile_and_file_paths_do_not_leak_file_contents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            license_file = root / "splunk.lic"
            ssh_key = root / "ssh.key"
            license_file.write_text("LICENSE_SECRET_CONTENT\n", encoding="utf-8")
            ssh_key.write_text("SSH_SECRET_CONTENT\n", encoding="utf-8")
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
            self.assertIn("  - name: es-sh", rendered)
            self.assertIn("      premium:", rendered)
            self.assertIn("./apps/splunk_app_es.tgz", rendered)
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
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                rendered = (output_dir / "pod" / "cluster-config.yaml").read_text(
                    encoding="utf-8"
                )
                metadata = json.loads(
                    (output_dir / "pod" / "metadata.json").read_text(encoding="utf-8")
                )
                self.assertIn(f"profile: {base_profile}", rendered)
                self.assertNotIn(f"profile: {profile}", rendered)
                self.assertIn("  - name: es-shc", rendered)
                self.assertEqual(metadata["pod_profile"], profile)
                self.assertEqual(metadata["pod_base_profile"], base_profile)
                self.assertEqual(metadata["worker_count"], workers)


if __name__ == "__main__":
    unittest.main()
