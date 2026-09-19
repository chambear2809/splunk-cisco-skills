#!/usr/bin/env python3
"""Regression tests for Splunk platform administration skill renderers."""

from __future__ import annotations

import json
import os
import shlex
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

    def write_fake_splunk(self, root: Path, *, btool_mode: str = "inventory") -> Path:
        """Create a synthetic Splunk CLI for generated lifecycle helpers."""
        splunk_home = root / "fake-splunk"
        bin_dir = splunk_home / "bin"
        bin_dir.mkdir(parents=True)
        old_logs_output = {
            "fail": "",
            "absent": "",
            "present": "[old_logs]\nmaxTotalDataSizeMB = 100\n",
            "misdirected_retention": (
                "[old_logs]\n[other_index]\nmaxTotalDataSizeMB = 100\n"
            ),
            "misdirected_disabled": "",
            "inventory": "",
            "empty_inventory": "",
            "sensitive": "",
        }[btool_mode]
        old_logs_returncode = "7" if btool_mode == "fail" else "0"
        if btool_mode == "sensitive":
            inventory_output = (
                "[main]\n"
                "password=UNQUOTED_SYNTHETIC\n"
                'remote.s3.secret_key = "QUOTED SYNTHETIC VALUE"\n'
                "secret_key=NO_SPACE_SYNTHETIC\n"
                "homePath = /synthetic/main/db\n"
            )
        elif btool_mode == "empty_inventory":
            inventory_output = ""
        else:
            inventory_output = "[main]\nmaxTotalDataSizeMB = 100\n"
        disabled_output = (
            "[disabled_index]\n[other_index]\ndisabled = 1\n"
            if btool_mode == "misdirected_disabled"
            else "[disabled_index]\ndisabled = 1\n"
        )
        config_marker = shlex.quote(str(root / "smartstore-config-called"))
        script = f"""#!/usr/bin/env bash
set -u
if [[ "${{1:-}}" == "version" ]]; then
    printf '%s\\n' 'Splunk 10.4.0'
    exit 0
fi
if [[ "${{1:-}}" == "restart" || "${{1:-}}" == "remove" || "${{1:-}}" == "disable" ]]; then
    exit 0
fi
if [[ "${{1:-}}" == "show" && "${{2:-}}" == "cluster-bundle-status" ]]; then
    printf '%s\\n' 'status=complete'
    exit 0
fi
if [[ "${{1:-}}" == "btool" ]]; then
    target="${{4:-}}"
    if [[ "${{2:-}}" == "indexes" && "${{3:-}}" == "list" ]]; then
        case "${{target}}" in
            ""|--debug)
                printf '%s' {shlex.quote(inventory_output)}
                exit 0
                ;;
            old_logs)
                printf '%s' {shlex.quote(old_logs_output)}
                exit {old_logs_returncode}
                ;;
            bounded_*)
                exit 0
                ;;
            disabled_index)
                printf '%s' {shlex.quote(disabled_output)}
                exit 0
                ;;
            volume:remote_store)
                printf '%b' '[volume:remote_store]\\nstorageType = remote\\npath = s3://synthetic/path\\n'
                exit 0
                ;;
            main)
                printf '%b' '[main]\\nrepFactor = auto\\nremotePath = volume:remote_store/$_index_name\\n'
                exit 0
                ;;
        esac
    fi
    if [[ "${{2:-}}" == "server" || "${{2:-}}" == "limits" ]]; then
        : > {config_marker}
        exit 0
    fi
fi
printf '%s\\n' 'unsupported synthetic Splunk command' >&2
exit 9
"""
        splunk_path = bin_dir / "splunk"
        splunk_path.write_text(script, encoding="utf-8")
        splunk_path.chmod(0o700)
        return splunk_home

    def render_and_run_status(
        self,
        output_dir: Path,
        splunk_home: Path,
        *args: str,
    ) -> subprocess.CompletedProcess:
        result = self.run_renderer(
            SMARTSTORE_RENDERER,
            "--output-dir",
            str(output_dir),
            "--splunk-home",
            str(splunk_home),
            *args,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        status = output_dir / "smartstore" / "status.sh"
        return subprocess.run(
            ["bash", str(status)],
            cwd=status.parent,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
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
            data_management_handoff = (render_dir / "data-management-federation-handoff.md").read_text(encoding="utf-8")
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
            self.assertIn("Federated Search for Microsoft Azure", data_management_handoff)
            self.assertIn("Federated Search for Azure Databricks", data_management_handoff)
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

            # Transparent providers explicitly do not use federated indexes.
            # Legacy FSS3 definitions are migration evidence only and therefore
            # do not appear in this file-based FSS2S configuration.
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
            apply_script = (render_dir / "apply-cluster-manager.sh").read_text(encoding="utf-8")

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
            self.assertIn("spv_require_supported_splunk_home", apply_script)
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

    def test_index_lifecycle_inventory_renders_reports_without_remote_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                SMARTSTORE_RENDERER,
                "--output-dir",
                tmpdir,
                "--operation",
                "inventory",
                "--indexes",
                "all",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "smartstore"
            self.assertTrue((render_dir / "index-lifecycle-report.md").exists())
            self.assertTrue((render_dir / "index-dependency-report.json").exists())
            searches = (render_dir / "collection-searches.spl").read_text(encoding="utf-8")
            metadata = json.loads((render_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertIn("/services/data/indexes", searches)
            self.assertIn("splunk_httpinput", searches)
            self.assertIn("/services/authorization/roles", searches)
            self.assertEqual(metadata["operation"], "inventory")
            self.assertEqual(metadata["indexes"], "all")

    def test_index_lifecycle_inventory_status_does_not_require_smartstore_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            splunk_home = self.write_fake_splunk(root)
            status_result = self.render_and_run_status(
                root / "render",
                splunk_home,
                "--operation",
                "inventory",
                "--indexes",
                "all",
            )
            self.assertEqual(status_result.returncode, 0, msg=status_result.stdout + status_result.stderr)
            self.assertIn("[main]", status_result.stdout)
            self.assertFalse((root / "smartstore-config-called").exists())
            preflight = subprocess.run(
                ["bash", str(root / "render" / "smartstore" / "preflight.sh")],
                cwd=root / "render" / "smartstore",
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(preflight.returncode, 0, msg=preflight.stdout + preflight.stderr)

    def test_index_lifecycle_setup_refuses_stale_status_for_another_operation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "render"
            splunk_home = self.write_fake_splunk(root)
            marker = root / "splunk-command-ran"
            splunk_path = splunk_home / "bin" / "splunk"
            splunk_path.write_text(
                "#!/usr/bin/env bash\n"
                f"touch {shlex.quote(str(marker))}\n"
                "exit 0\n",
                encoding="utf-8",
            )
            splunk_path.chmod(0o700)
            rendered = self.run_renderer(
                SMARTSTORE_RENDERER,
                "--output-dir",
                str(output_dir),
                "--splunk-home",
                str(splunk_home),
                "--platform",
                "enterprise",
                "--deployment",
                "standalone",
                "--operation",
                "inventory",
                "--indexes",
                "all",
            )
            self.assertEqual(rendered.returncode, 0, msg=rendered.stdout + rendered.stderr)

            status = subprocess.run(
                [
                    "bash",
                    str(SMARTSTORE_SETUP),
                    "--output-dir",
                    str(output_dir),
                    "--phase",
                    "status",
                    "--platform",
                    "enterprise",
                    "--deployment",
                    "standalone",
                    "--operation",
                    "delete-index",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )

            self.assertNotEqual(status.returncode, 0)
            self.assertIn("operation does not match the rendered metadata", status.stderr)
            self.assertFalse(marker.exists())

            target_override = subprocess.run(
                [
                    "bash",
                    str(SMARTSTORE_SETUP),
                    "--output-dir",
                    str(output_dir),
                    "--phase",
                    "status",
                    "--operation",
                    "inventory",
                    "--indexes",
                    "different_index",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertNotEqual(target_override.returncode, 0)
            self.assertIn("render-affecting overrides are refused", target_override.stderr)
            self.assertFalse(marker.exists())

    def test_index_lifecycle_retention_helper_refuses_wrong_rendered_operation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "render"
            splunk_home = self.write_fake_splunk(root)
            marker = root / "splunk-command-ran"
            splunk_path = splunk_home / "bin" / "splunk"
            splunk_path.write_text(
                "#!/usr/bin/env bash\n"
                f"touch {shlex.quote(str(marker))}\n"
                "exit 0\n",
                encoding="utf-8",
            )
            splunk_path.chmod(0o700)
            rendered = self.run_renderer(
                SMARTSTORE_RENDERER,
                "--output-dir",
                str(output_dir),
                "--splunk-home",
                str(splunk_home),
                "--platform",
                "enterprise",
                "--deployment",
                "standalone",
                "--operation",
                "inventory",
                "--indexes",
                "all",
            )
            self.assertEqual(rendered.returncode, 0, msg=rendered.stdout + rendered.stderr)

            apply_result = subprocess.run(
                ["bash", str(output_dir / "smartstore" / "apply-retention-enterprise.sh")],
                cwd=output_dir / "smartstore",
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )

            self.assertNotEqual(apply_result.returncode, 0)
            self.assertIn("metadata does not match", apply_result.stderr)
            self.assertFalse(marker.exists())

    def test_index_lifecycle_helper_refuses_same_operation_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "render"
            splunk_home = self.write_fake_splunk(root)
            marker = root / "splunk-command-ran"
            splunk_path = splunk_home / "bin" / "splunk"
            splunk_path.write_text(
                "#!/usr/bin/env bash\n"
                f"touch {shlex.quote(str(marker))}\n"
                "exit 0\n",
                encoding="utf-8",
            )
            splunk_path.chmod(0o700)
            rendered = self.run_renderer(
                SMARTSTORE_RENDERER,
                "--output-dir",
                str(output_dir),
                "--splunk-home",
                str(splunk_home),
                "--platform",
                "enterprise",
                "--deployment",
                "standalone",
                "--operation",
                "retention",
                "--indexes",
                "old_logs",
                "--max-total-data-size-mb",
                "100",
                "--restart-splunk",
                "false",
            )
            self.assertEqual(rendered.returncode, 0, msg=rendered.stdout + rendered.stderr)
            render_dir = output_dir / "smartstore"
            metadata_path = render_dir / "metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["status_identity_sha256"] = "0" * 64
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            apply_result = subprocess.run(
                ["bash", str(render_dir / "apply-retention-enterprise.sh")],
                cwd=render_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )

            self.assertNotEqual(apply_result.returncode, 0)
            self.assertIn("status identity does not match", apply_result.stderr)
            self.assertFalse(marker.exists())

    def test_index_lifecycle_retention_status_reads_requested_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            splunk_home = self.write_fake_splunk(root, btool_mode="present")
            status_result = self.render_and_run_status(
                root / "render",
                splunk_home,
                "--operation",
                "retention",
                "--deployment",
                "standalone",
                "--indexes",
                "old_logs",
                "--max-total-data-size-mb",
                "100",
            )
            self.assertEqual(status_result.returncode, 0, msg=status_result.stdout + status_result.stderr)
            self.assertIn("Post-activation btool readback matched all rendered settings.", status_result.stdout)

    def test_index_lifecycle_status_rejects_settings_from_another_stanza(self) -> None:
        cases = (
            (
                "retention",
                "misdirected_retention",
                ("--indexes", "old_logs", "--max-total-data-size-mb", "100"),
                "requested value was not observed",
            ),
            (
                "disable-index",
                "misdirected_disabled",
                ("--indexes", "disabled_index"),
                "disabled=true was not observed",
            ),
        )
        for operation, btool_mode, extra_args, expected_text in cases:
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                splunk_home = self.write_fake_splunk(root, btool_mode=btool_mode)
                status_result = self.render_and_run_status(
                    root / "render",
                    splunk_home,
                    "--operation",
                    operation,
                    "--deployment",
                    "standalone",
                    *extra_args,
                )
                self.assertEqual(status_result.returncode, 1)
                self.assertIn(expected_text, status_result.stderr)

    def test_index_lifecycle_inventory_empty_readback_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            splunk_home = self.write_fake_splunk(root, btool_mode="empty_inventory")
            status_result = self.render_and_run_status(
                root / "render",
                splunk_home,
                "--operation",
                "inventory",
                "--indexes",
                "all",
            )
            self.assertEqual(status_result.returncode, 2)
            self.assertIn("returned no index stanzas", status_result.stderr)

    def test_index_lifecycle_smartstore_status_reads_remote_and_index_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            splunk_home = self.write_fake_splunk(root)
            status_result = self.render_and_run_status(
                root / "render",
                splunk_home,
                "--operation",
                "smartstore",
                "--deployment",
                "standalone",
                "--remote-path",
                "s3://synthetic/path",
                "--indexes",
                "main",
            )
            self.assertEqual(status_result.returncode, 0, msg=status_result.stdout + status_result.stderr)
            self.assertIn("Post-activation btool readback matched all rendered settings.", status_result.stdout)
            self.assertTrue((root / "smartstore-config-called").exists())

    def test_index_lifecycle_retention_all_status_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            splunk_home = self.write_fake_splunk(root, btool_mode="present")
            status_result = self.render_and_run_status(
                root / "render",
                splunk_home,
                "--operation",
                "retention",
                "--deployment",
                "standalone",
                "--indexes",
                "all",
                "--max-total-data-size-mb",
                "100",
            )
            self.assertEqual(status_result.returncode, 2)
            self.assertIn("requires explicit --indexes", status_result.stderr)

    def test_index_lifecycle_cluster_status_reports_peer_verification_handoff(self) -> None:
        cases = (
            ("retention", ("--indexes", "old_logs", "--max-total-data-size-mb", "100")),
            ("smartstore", ("--remote-path", "s3://synthetic/path", "--indexes", "main")),
            ("disable-index", ("--indexes", "disabled_index")),
            ("delete-index", ("--indexes", "old_logs")),
        )
        for operation, extra_args in cases:
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                splunk_home = self.write_fake_splunk(root)
                status_args = (
                    "--operation",
                    operation,
                    "--deployment",
                    "cluster",
                    *extra_args,
                )
                status_result = self.render_and_run_status(root / "render", splunk_home, *status_args)
                self.assertEqual(status_result.returncode, 2, msg=status_result.stdout + status_result.stderr)
                self.assertIn("peer", status_result.stderr.lower())
                self.assertIn("status=complete", status_result.stdout)

    def test_index_lifecycle_cluster_retention_all_reports_control_plane_and_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            splunk_home = self.write_fake_splunk(root)
            status_result = self.render_and_run_status(
                root / "render",
                splunk_home,
                "--operation",
                "retention",
                "--deployment",
                "cluster",
                "--indexes",
                "all",
                "--max-total-data-size-mb",
                "100",
            )
            self.assertEqual(status_result.returncode, 2, msg=status_result.stdout + status_result.stderr)
            self.assertIn("status=complete", status_result.stdout)
            self.assertIn("No target-specific settings", status_result.stderr)

    def test_index_lifecycle_disable_status_reads_disabled_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            splunk_home = self.write_fake_splunk(root)
            status_result = self.render_and_run_status(
                root / "render",
                splunk_home,
                "--operation",
                "disable-index",
                "--deployment",
                "standalone",
                "--indexes",
                "disabled_index",
            )
            self.assertEqual(status_result.returncode, 0, msg=status_result.stdout + status_result.stderr)
            self.assertIn("Post-disable btool readback verified", status_result.stdout)

    def test_index_lifecycle_delete_status_distinguishes_readback_failure_absence_and_presence(self) -> None:
        for mode, expected_returncode, expected_text in (
            ("fail", 1, "btool readback failed"),
            ("absent", 0, "VERIFIED ABSENT: old_logs"),
            ("present", 1, "still finds index stanza"),
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                splunk_home = self.write_fake_splunk(root, btool_mode=mode)
                status_result = self.render_and_run_status(
                    root / "render",
                    splunk_home,
                    "--operation",
                    "delete-index",
                    "--deployment",
                    "standalone",
                    "--indexes",
                    "old_logs",
                )
                self.assertEqual(
                    status_result.returncode,
                    expected_returncode,
                    msg=status_result.stdout + status_result.stderr,
                )
                self.assertIn(expected_text, status_result.stdout + status_result.stderr)

    def test_index_lifecycle_delete_success_diagnostic_bounds_index_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            splunk_home = self.write_fake_splunk(root, btool_mode="absent")
            long_name = "bounded_" + ("a" * 200)
            status_result = self.render_and_run_status(
                root / "render",
                splunk_home,
                "--operation",
                "delete-index",
                "--deployment",
                "standalone",
                "--indexes",
                long_name,
            )
            self.assertEqual(status_result.returncode, 0, msg=status_result.stdout + status_result.stderr)
            self.assertIn(f"VERIFIED ABSENT: {long_name[:128]}...", status_result.stdout)
            self.assertNotIn(long_name, status_result.stdout)

    def test_index_lifecycle_delete_apply_then_status_verifies_absence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            splunk_home = self.write_fake_splunk(root, btool_mode="absent")
            evidence = root / "evidence.json"
            owner = root / "owner.txt"
            backup = root / "backup.txt"
            evidence.write_text('{"safe_to_delete_indexes":["old_logs"]}', encoding="utf-8")
            owner.write_text("approved\n", encoding="utf-8")
            backup.write_text("backup complete\n", encoding="utf-8")
            result = self.run_renderer(
                SMARTSTORE_RENDERER,
                "--output-dir",
                str(root / "render"),
                "--splunk-home",
                str(splunk_home),
                "--operation",
                "delete-index",
                "--deployment",
                "standalone",
                "--indexes",
                "old_logs",
                "--evidence-file",
                str(evidence),
                "--owner-approval-file",
                str(owner),
                "--backup-evidence-file",
                str(backup),
                "--accept-destructive-index-delete",
                "--confirm-token",
                "DELETE_INDEX:old_logs",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = root / "render" / "smartstore"
            apply_result = subprocess.run(
                ["bash", str(render_dir / "apply-delete-index.sh")],
                cwd=render_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(apply_result.returncode, 0, msg=apply_result.stdout + apply_result.stderr)
            self.assertIn("VERIFIED ABSENT: old_logs", apply_result.stdout)
            self.assertIn("Post-delete btool readback", apply_result.stdout)
            status_result = subprocess.run(
                ["bash", str(render_dir / "status.sh")],
                cwd=render_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(status_result.returncode, 0, msg=status_result.stdout + status_result.stderr)
            self.assertIn("VERIFIED ABSENT: old_logs", status_result.stdout)
            self.assertIn("Post-delete btool readback", status_result.stdout)

    def test_index_lifecycle_staged_only_apply_remains_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            splunk_home = self.write_fake_splunk(root, btool_mode="present")
            result = self.run_renderer(
                SMARTSTORE_RENDERER,
                "--output-dir",
                str(root / "render"),
                "--splunk-home",
                str(splunk_home),
                "--operation",
                "retention",
                "--deployment",
                "standalone",
                "--indexes",
                "old_logs",
                "--max-total-data-size-mb",
                "100",
                "--restart-splunk",
                "false",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = root / "render" / "smartstore"
            apply_result = subprocess.run(
                ["bash", str(render_dir / "apply-retention-enterprise.sh")],
                cwd=render_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(apply_result.returncode, 2)
            self.assertIn("restart is disabled", apply_result.stderr)

    def test_index_lifecycle_staged_and_manual_handoffs_remain_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            splunk_home = self.write_fake_splunk(root)
            result = self.run_renderer(
                SMARTSTORE_RENDERER,
                "--output-dir",
                str(root / "render"),
                "--splunk-home",
                str(splunk_home),
                "--operation",
                "archive",
                "--deployment",
                "standalone",
                "--indexes",
                "old_logs",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            status_result = subprocess.run(
                ["bash", str(root / "render" / "smartstore" / "status.sh")],
                cwd=root / "render" / "smartstore",
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(status_result.returncode, 2)
            self.assertIn("manual handoff", status_result.stderr)

    def test_index_lifecycle_clean_data_status_does_not_claim_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            splunk_home = self.write_fake_splunk(root)
            status_result = self.render_and_run_status(
                root / "render",
                splunk_home,
                "--operation",
                "clean-data",
                "--deployment",
                "standalone",
                "--indexes",
                "old_logs",
            )
            self.assertEqual(status_result.returncode, 2)
            self.assertIn("no supported independent readback", status_result.stderr)
            self.assertNotIn("VERIFIED", status_result.stdout + status_result.stderr)

    def test_index_lifecycle_inventory_status_omits_sensitive_assignment_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            splunk_home = self.write_fake_splunk(root, btool_mode="sensitive")
            status_result = self.render_and_run_status(
                root / "render",
                splunk_home,
                "--operation",
                "inventory",
                "--indexes",
                "all",
            )
            self.assertEqual(status_result.returncode, 0, msg=status_result.stdout + status_result.stderr)
            self.assertIn("[main]", status_result.stdout)
            for synthetic_value in (
                "UNQUOTED_SYNTHETIC",
                "QUOTED SYNTHETIC VALUE",
                "NO_SPACE_SYNTHETIC",
            ):
                self.assertNotIn(synthetic_value, status_result.stdout + status_result.stderr)

    def test_index_lifecycle_cloud_retention_renders_acs_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                SMARTSTORE_RENDERER,
                "--output-dir",
                tmpdir,
                "--platform",
                "cloud",
                "--operation",
                "retention",
                "--stack",
                "my-stack",
                "--indexes",
                "rtp_idx",
                "--searchable-days",
                "90",
                "--archival-retention-days",
                "365",
                "--max-data-size-mb",
                "2048",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            payload = json.loads((Path(tmpdir) / "smartstore" / "acs-index-update-payload.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["operation"], "retention")
            self.assertEqual(
                payload["indexes"][0],
                {
                    "datatype": "event",
                    "maxDataSizeMB": 2048,
                    "name": "rtp_idx",
                    "searchableDays": 90,
                    "splunkArchivalRetentionDays": 365,
                },
            )

    def test_index_lifecycle_cloud_inventory_requires_parseable_collection_or_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            token_file = root / "acs-token"
            token_file.write_text("synthetic-token\n", encoding="utf-8")
            token_file.chmod(0o600)
            curl = bin_dir / "curl"
            curl.write_text(
                """#!/usr/bin/env python3
import os
import sys
from pathlib import Path

args = sys.argv[1:]
target = args[args.index("-o") + 1]
Path(target).write_text(os.environ.get("ACS_BODY", ""), encoding="utf-8")
sys.stdout.write("200")
""",
                encoding="utf-8",
            )
            curl.chmod(0o700)
            render_dir = root / "render"
            result = self.run_renderer(
                SMARTSTORE_RENDERER,
                "--output-dir",
                str(render_dir),
                "--platform",
                "cloud",
                "--operation",
                "inventory",
                "--stack",
                "my-stack",
                "--indexes",
                "all",
                "--acs-token-file",
                str(token_file),
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            status_script = render_dir / "smartstore" / "status.sh"
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"

            for body in ("", "not-json", '"scalar"'):
                with self.subTest(body=body):
                    env["ACS_BODY"] = body
                    status = subprocess.run(
                        ["bash", str(status_script)],
                        cwd=status_script.parent,
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=30,
                    )
                    self.assertNotEqual(status.returncode, 0)
                    self.assertIn("ACS index inventory", status.stderr)

            for body in ("{}", "[]"):
                with self.subTest(body=body):
                    env["ACS_BODY"] = body
                    status = subprocess.run(
                        ["bash", str(status_script)],
                        cwd=status_script.parent,
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=30,
                    )
                    self.assertEqual(status.returncode, 0, msg=status.stdout + status.stderr)

    def test_index_lifecycle_cloud_retention_status_without_expected_fields_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            result = self.run_renderer(
                SMARTSTORE_RENDERER,
                "--output-dir",
                str(root),
                "--platform",
                "cloud",
                "--operation",
                "retention",
                "--stack",
                "my-stack",
                "--indexes",
                "rtp_idx",
                "--searchable-days",
                "90",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = root / "smartstore"
            (render_dir / "acs-index-update-payload.json").write_text(
                json.dumps(
                    {
                        "operation": "retention",
                        "indexes": [{"name": "rtp_idx", "datatype": "event"}],
                    }
                ),
                encoding="utf-8",
            )
            status_result = subprocess.run(
                ["bash", str(render_dir / "status.sh")],
                cwd=render_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(status_result.returncode, 2)
            self.assertIn("no expected settings", status_result.stderr)
            self.assertNotIn("VERIFIED", status_result.stdout + status_result.stderr)

    def test_index_lifecycle_cloud_status_rejects_wrong_named_index_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            token_file = root / "acs-token"
            token_file.write_text("synthetic-token\n", encoding="utf-8")
            token_file.chmod(0o600)
            curl = bin_dir / "curl"
            curl.write_text(
                """#!/usr/bin/env python3
import os
import sys
from pathlib import Path

args = sys.argv[1:]
target = args[args.index("-o") + 1]
Path(target).write_text(os.environ["ACS_BODY"], encoding="utf-8")
sys.stdout.write("200")
""",
                encoding="utf-8",
            )
            curl.chmod(0o700)
            output_dir = root / "render"
            rendered = self.run_renderer(
                SMARTSTORE_RENDERER,
                "--output-dir",
                str(output_dir),
                "--platform",
                "cloud",
                "--operation",
                "retention",
                "--stack",
                "reviewed-stack",
                "--indexes",
                "requested_index",
                "--searchable-days",
                "90",
                "--archival-retention-days",
                "365",
                "--acs-token-file",
                str(token_file),
            )
            self.assertEqual(rendered.returncode, 0, msg=rendered.stdout + rendered.stderr)
            render_dir = output_dir / "smartstore"
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["ACS_BODY"] = json.dumps(
                {
                    "name": "different_index",
                    "datatype": "event",
                    "searchableDays": 90,
                    "splunkArchivalRetentionDays": 365,
                }
            )

            status_result = subprocess.run(
                ["bash", str(render_dir / "status.sh")],
                cwd=render_dir,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )

            self.assertNotEqual(status_result.returncode, 0)
            self.assertIn("nonmatching index record", status_result.stderr)

    def test_index_lifecycle_rejects_delete_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                SMARTSTORE_RENDERER,
                "--output-dir",
                tmpdir,
                "--operation",
                "delete-index",
                "--indexes",
                "all",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--indexes all is not allowed", result.stderr)

    def test_index_lifecycle_delete_apply_fails_without_accept_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence = Path(tmpdir) / "evidence.json"
            owner = Path(tmpdir) / "owner.txt"
            backup = Path(tmpdir) / "backup.txt"
            evidence.write_text('{"safe_to_delete_indexes":["old_logs"]}', encoding="utf-8")
            owner.write_text("approved\n", encoding="utf-8")
            backup.write_text("backup complete\n", encoding="utf-8")
            result = self.run_renderer(
                SMARTSTORE_RENDERER,
                "--output-dir",
                tmpdir,
                "--operation",
                "delete-index",
                "--deployment",
                "standalone",
                "--indexes",
                "old_logs",
                "--evidence-file",
                str(evidence),
                "--owner-approval-file",
                str(owner),
                "--backup-evidence-file",
                str(backup),
                "--confirm-token",
                "DELETE_INDEX:old_logs",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            script = Path(tmpdir) / "smartstore" / "apply-delete-index.sh"
            apply_result = subprocess.run(
                ["bash", str(script)],
                cwd=script.parent,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertNotEqual(apply_result.returncode, 0)
            self.assertIn("--accept-destructive-index-delete is required", apply_result.stderr)

    def test_index_lifecycle_delete_apply_blocks_protected_default_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence = Path(tmpdir) / "evidence.json"
            owner = Path(tmpdir) / "owner.txt"
            backup = Path(tmpdir) / "backup.txt"
            evidence.write_text('{"safe_to_delete_indexes":["main"]}', encoding="utf-8")
            owner.write_text("approved\n", encoding="utf-8")
            backup.write_text("backup complete\n", encoding="utf-8")
            result = self.run_renderer(
                SMARTSTORE_RENDERER,
                "--output-dir",
                tmpdir,
                "--operation",
                "delete-index",
                "--deployment",
                "standalone",
                "--indexes",
                "main",
                "--evidence-file",
                str(evidence),
                "--owner-approval-file",
                str(owner),
                "--backup-evidence-file",
                str(backup),
                "--accept-destructive-index-delete",
                "--confirm-token",
                "DELETE_INDEX:main",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            script = Path(tmpdir) / "smartstore" / "apply-delete-index.sh"
            apply_result = subprocess.run(
                ["bash", str(script)],
                cwd=script.parent,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertNotEqual(apply_result.returncode, 0)
            self.assertIn("default index requires non-production test evidence", apply_result.stderr)

    def test_index_lifecycle_blocks_internal_and_sensitive_delete_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            internal = self.run_renderer(
                SMARTSTORE_RENDERER,
                "--output-dir",
                tmpdir,
                "--operation",
                "delete-index",
                "--indexes",
                "_internal",
            )
            self.assertNotEqual(internal.returncode, 0)
            self.assertIn("internal index", internal.stderr)

        with tempfile.TemporaryDirectory() as tmpdir:
            evidence = Path(tmpdir) / "evidence.json"
            owner = Path(tmpdir) / "owner.txt"
            backup = Path(tmpdir) / "backup.txt"
            evidence.write_text('{"safe_to_delete_indexes":["risk"]}', encoding="utf-8")
            owner.write_text("approved\n", encoding="utf-8")
            backup.write_text("backup complete\n", encoding="utf-8")
            result = self.run_renderer(
                SMARTSTORE_RENDERER,
                "--output-dir",
                tmpdir,
                "--operation",
                "delete-index",
                "--deployment",
                "standalone",
                "--indexes",
                "risk",
                "--evidence-file",
                str(evidence),
                "--owner-approval-file",
                str(owner),
                "--backup-evidence-file",
                str(backup),
                "--accept-destructive-index-delete",
                "--confirm-token",
                "DELETE_INDEX:risk",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            script = Path(tmpdir) / "smartstore" / "apply-delete-index.sh"
            apply_result = subprocess.run(
                ["bash", str(script)],
                cwd=script.parent,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertNotEqual(apply_result.returncode, 0)
            self.assertIn("ES/ITSI/ARI-sensitive index", apply_result.stderr)

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
            preflight = (render_dir / "preflight.sh").read_text(encoding="utf-8")

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
            self.assertIn("spv_require_supported_splunk_home", preflight)
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
