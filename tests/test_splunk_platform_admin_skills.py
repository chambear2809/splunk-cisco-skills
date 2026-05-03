#!/usr/bin/env python3
"""Regression tests for Splunk platform administration skill renderers."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT


FEDERATED_RENDERER = REPO_ROOT / "skills/splunk-federated-search-setup/scripts/render_assets.py"
SMARTSTORE_RENDERER = REPO_ROOT / "skills/splunk-index-lifecycle-smartstore-setup/scripts/render_assets.py"
MONITORING_RENDERER = REPO_ROOT / "skills/splunk-monitoring-console-setup/scripts/render_assets.py"
FEDERATED_SETUP = REPO_ROOT / "skills/splunk-federated-search-setup/scripts/setup.sh"
SMARTSTORE_SETUP = REPO_ROOT / "skills/splunk-index-lifecycle-smartstore-setup/scripts/setup.sh"
MONITORING_SETUP = REPO_ROOT / "skills/splunk-monitoring-console-setup/scripts/setup.sh"


class SplunkPlatformAdminRendererTests(unittest.TestCase):
    def run_renderer(self, renderer: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(renderer), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def read_all_assets(self, render_dir: Path) -> str:
        return "\n".join(
            path.read_text(encoding="utf-8")
            for path in render_dir.iterdir()
            if path.is_file()
        )

    def test_admin_setup_wrappers_return_success_for_render_phase(self) -> None:
        cases = [
            (
                FEDERATED_SETUP,
                ["--remote-host-port", "remote-sh.example.com:8089", "--service-account", "federated_svc"],
                "federated-search/federated.conf.template",
            ),
            (SMARTSTORE_SETUP, ["--remote-path", "s3://splunk-smartstore/test"], "smartstore/indexes.conf.template"),
            (
                MONITORING_SETUP,
                ["--search-peers", "idx01.example.com:8089", "--peer-username", "admin"],
                "monitoring-console/splunk_monitoring_console_assets.conf",
            ),
        ]
        for setup_script, extra_args, expected_asset in cases:
            with self.subTest(setup_script=setup_script.name), tempfile.TemporaryDirectory() as tmpdir:
                result = subprocess.run(
                    ["bash", str(setup_script), "--output-dir", tmpdir, *extra_args],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                self.assertTrue((Path(tmpdir) / expected_asset).exists())

    def test_federated_standard_renders_provider_index_and_shc_replication(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            password_file = Path(tmpdir) / "federated.secret"
            password_file.write_text("SUPER_SECRET_FEDERATED_PASSWORD\n", encoding="utf-8")
            result = self.run_renderer(
                FEDERATED_RENDERER,
                "--output-dir",
                tmpdir,
                "--mode",
                "standard",
                "--remote-host-port",
                "remote-sh.example.com:8089",
                "--service-account",
                "federated_svc",
                "--password-file",
                str(password_file),
                "--provider-name",
                "remote_prod",
                "--federated-index-name",
                "remote_metrics",
                "--dataset-type",
                "metricindex",
                "--dataset-name",
                "metrics",
                "--max-preview-generation-duration",
                "55",
                "--max-preview-generation-inputcount",
                "500000",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "federated-search"
            federated_conf = (render_dir / "federated.conf.template").read_text(encoding="utf-8")
            indexes_conf = (render_dir / "indexes.conf").read_text(encoding="utf-8")
            server_conf = (render_dir / "server.conf").read_text(encoding="utf-8")
            all_assets = self.read_all_assets(render_dir)

            self.assertIn("[provider://remote_prod]", federated_conf)
            self.assertIn("mode = standard", federated_conf)
            self.assertIn("max_preview_generation_duration = 55", federated_conf)
            self.assertIn("max_preview_generation_inputcount = 500000", federated_conf)
            # Renderer was rewritten to emit per-provider password placeholders so
            # multiple providers can each substitute independently from their own
            # password_file. The single-provider back-compat CLI flow uses the
            # provided --provider-name (here `remote_prod`) to derive the token.
            self.assertIn("password = __FEDERATED_PASSWORD_FILE_BASE64__REMOTE_PROD__", federated_conf)
            self.assertIn("[federated:remote_metrics]", indexes_conf)
            self.assertIn("federated.dataset = metricindex:metrics", indexes_conf)
            self.assertIn("conf_replication_include.indexes = true", server_conf)
            self.assertNotIn("SUPER_SECRET_FEDERATED_PASSWORD", all_assets)

    def test_federated_rejects_standard_mode_fsh_knowledge_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                FEDERATED_RENDERER,
                "--output-dir",
                tmpdir,
                "--mode",
                "standard",
                "--remote-host-port",
                "remote-sh.example.com:8089",
                "--service-account",
                "federated_svc",
                "--use-fsh-knowledge-objects",
                "true",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("valid only for transparent mode", result.stderr)

    def test_federated_transparent_omits_federated_index_definition(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                FEDERATED_RENDERER,
                "--output-dir",
                tmpdir,
                "--mode",
                "transparent",
                "--remote-host-port",
                "remote-sh.example.com:8089",
                "--service-account",
                "federated_svc",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            indexes_conf = (Path(tmpdir) / "federated-search" / "indexes.conf").read_text(encoding="utf-8")
            federated_conf = (Path(tmpdir) / "federated-search" / "federated.conf.template").read_text(encoding="utf-8")

            # Renderer's wording was tightened in the multi-provider rewrite:
            # transparent providers explicitly do not use federated indexes, and
            # FSS3 federated indexes are created via REST. Both notes appear in
            # the rendered indexes.conf placeholder file.
            self.assertIn("Transparent-mode providers do not use federated indexes.", indexes_conf)
            self.assertNotIn("[federated:", indexes_conf)
            self.assertIn("useFSHKnowledgeObjects = 1", federated_conf)

    def test_federated_rejects_fsh_knowledge_objects_for_standard_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                FEDERATED_RENDERER,
                "--output-dir",
                tmpdir,
                "--mode",
                "standard",
                "--remote-host-port",
                "remote-sh.example.com:8089",
                "--service-account",
                "federated_svc",
                "--use-fsh-knowledge-objects",
                "true",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("valid only for transparent mode", result.stderr)

    def test_smartstore_cluster_s3_render_keeps_keys_out_of_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            access_key_file = Path(tmpdir) / "access.key"
            secret_key_file = Path(tmpdir) / "secret.key"
            access_key_file.write_text("AKIA_TEST_SECRET\n", encoding="utf-8")
            secret_key_file.write_text("VERY_SECRET_S3_KEY\n", encoding="utf-8")
            result = self.run_renderer(
                SMARTSTORE_RENDERER,
                "--output-dir",
                tmpdir,
                "--deployment",
                "cluster",
                "--remote-provider",
                "s3",
                "--remote-path",
                "s3://splunk-smartstore/cluster-a",
                "--indexes",
                "main,summary",
                "--max-global-data-size-mb",
                "1048576",
                "--cache-size-mb",
                "262144",
                "--eviction-policy",
                "lru",
                "--eviction-padding-mb",
                "1024",
                "--index-hotlist-recency-secs",
                "86400",
                "--s3-auth-region",
                "us-east-1",
                "--s3-tsidx-compression",
                "true",
                "--s3-encryption",
                "sse-kms",
                "--s3-kms-key-id",
                "arn:aws:kms:us-east-1:111122223333:key/example",
                "--s3-ssl-verify-server-cert",
                "true",
                "--bucket-localize-max-timeout-sec",
                "600",
                "--s3-access-key-file",
                str(access_key_file),
                "--s3-secret-key-file",
                str(secret_key_file),
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "smartstore"
            indexes_conf = (render_dir / "indexes.conf.template").read_text(encoding="utf-8")
            server_conf = (render_dir / "server.conf").read_text(encoding="utf-8")
            limits_conf = (render_dir / "limits.conf").read_text(encoding="utf-8")
            all_assets = self.read_all_assets(render_dir)

            self.assertIn("[volume:remote_store]", indexes_conf)
            self.assertIn("storageType = remote", indexes_conf)
            self.assertIn("path = s3://splunk-smartstore/cluster-a", indexes_conf)
            self.assertIn("remotePath = volume:remote_store/$_index_name", indexes_conf)
            self.assertIn("repFactor = auto", indexes_conf)
            self.assertIn("maxGlobalDataSizeMB = 1048576", indexes_conf)
            self.assertIn("hotlist_recency_secs = 86400", indexes_conf)
            self.assertIn("remote.s3.auth_region = us-east-1", indexes_conf)
            self.assertIn("remote.s3.tsidx_compression = true", indexes_conf)
            self.assertIn("remote.s3.encryption = sse-kms", indexes_conf)
            self.assertIn("remote.s3.kms.key_id = arn:aws:kms:us-east-1:111122223333:key/example", indexes_conf)
            self.assertIn("remote.s3.sslVerifyServerCert = true", indexes_conf)
            self.assertIn("remote.s3.access_key = __SMARTSTORE_S3_ACCESS_KEY_FROM_FILE__", indexes_conf)
            self.assertIn("eviction_policy = lru", server_conf)
            self.assertIn("max_cache_size = 262144", server_conf)
            self.assertIn("eviction_padding = 1024", server_conf)
            self.assertIn("[remote_storage]", limits_conf)
            self.assertIn("bucket_localize_max_timeout_sec = 600", limits_conf)
            self.assertNotIn("AKIA_TEST_SECRET", all_assets)
            self.assertNotIn("VERY_SECRET_S3_KEY", all_assets)

    def test_smartstore_rejects_mismatched_remote_path_scheme(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                SMARTSTORE_RENDERER,
                "--output-dir",
                tmpdir,
                "--remote-provider",
                "gcs",
                "--remote-path",
                "s3://wrong-provider/path",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must start with gs://", result.stderr)

    def test_smartstore_rejects_provider_specific_settings_for_wrong_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                SMARTSTORE_RENDERER,
                "--output-dir",
                tmpdir,
                "--remote-provider",
                "gcs",
                "--remote-path",
                "gs://splunk-smartstore/cluster-a",
                "--s3-endpoint",
                "https://s3.example.com",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("remote.s3 settings", result.stderr)

    def test_monitoring_console_distributed_render_avoids_password_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                MONITORING_RENDERER,
                "--output-dir",
                tmpdir,
                "--mode",
                "distributed",
                "--enable-auto-config",
                "true",
                "--enable-forwarder-monitoring",
                "true",
                "--enable-platform-alerts",
                "true",
                "--platform-alerts",
                "Near Critical Disk Usage,Search Peer Not Responding",
                "--search-peers",
                "cm01.example.com:8089,idx01.example.com:8089",
                "--search-groups",
                "managers=cm01.example.com:8089;indexers=idx01.example.com:8089",
                "--default-search-group",
                "indexers",
                "--peer-username",
                "admin",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "monitoring-console"
            assets_conf = (render_dir / "splunk_monitoring_console_assets.conf").read_text(encoding="utf-8")
            distsearch = (render_dir / "distsearch.conf").read_text(encoding="utf-8")
            savedsearches = (render_dir / "savedsearches.conf").read_text(encoding="utf-8")
            peer_helper = (render_dir / "add-search-peers.sh").read_text(encoding="utf-8")
            metadata = (render_dir / "metadata.json").read_text(encoding="utf-8")

            self.assertIn("mc_auto_config = enabled", assets_conf)
            self.assertIn("[distributedSearch]", distsearch)
            self.assertIn("servers = https://cm01.example.com:8089,https://idx01.example.com:8089", distsearch)
            self.assertIn("[distributedSearch:managers]\ndefault = false\nservers = cm01.example.com:8089", distsearch)
            self.assertIn("[distributedSearch:indexers]\ndefault = true\nservers = idx01.example.com:8089", distsearch)
            self.assertIn("default = true", distsearch)
            self.assertIn("[DMC Forwarder - Build Asset Table]", savedsearches)
            self.assertIn("[Near Critical Disk Usage]", savedsearches)
            self.assertIn("cm01.example.com:8089", peer_helper)
            self.assertIn("peer_scheme=https", peer_helper)
            self.assertIn('echo "Peer: ${peer_scheme}://${peer}"', peer_helper)
            self.assertIn("process argument", peer_helper)
            self.assertNotIn("-remotePassword", peer_helper)
            self.assertNotIn("peer_password", metadata)

    def test_monitoring_console_rejects_savedsearch_stanza_injection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                MONITORING_RENDERER,
                "--output-dir",
                tmpdir,
                "--enable-platform-alerts",
                "true",
                "--platform-alerts",
                "Good Alert,[evil]",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must not contain brackets", result.stderr)


if __name__ == "__main__":
    unittest.main()
