#!/usr/bin/env python3
"""Regression tests for the splunk-kvstore-admin-setup renderer and wrapper."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT

RENDERER = REPO_ROOT / "skills/splunk-kvstore-admin-setup/scripts/render_assets.py"
SETUP = REPO_ROOT / "skills/splunk-kvstore-admin-setup/scripts/setup.sh"


class KvstoreAdminTests(unittest.TestCase):
    def run_renderer(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(RENDERER), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def run_setup(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(SETUP), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def test_shc_render_emits_lifecycle_and_governance_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--topology", "shc",
                "--collection-name", "asset_inventory",
                "--collection-fields", "ip:string,risk:number",
                "--lookup-definition-name", "asset_inventory_lookup",
                "--disable-startup-upgrade", "true",
                "--enterprise-version", "10.2.0",
                "--target-kvstore-version", "8.0",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "kvstore"
            for name in (
                "backup.sh", "restore.sh", "clean.sh", "migrate.sh", "upgrade.sh",
                "status.sh", "preflight.sh", "server.conf", "collections.conf", "transforms.conf",
            ):
                self.assertTrue((render_dir / name).exists(), name)
            collections = (render_dir / "collections.conf").read_text(encoding="utf-8")
            transforms = (render_dir / "transforms.conf").read_text(encoding="utf-8")
            server = (render_dir / "server.conf").read_text(encoding="utf-8")
            migrate = (render_dir / "migrate.sh").read_text(encoding="utf-8")
            upgrade = (render_dir / "upgrade.sh").read_text(encoding="utf-8")
            backup = (render_dir / "backup.sh").read_text(encoding="utf-8")
            self.assertIn("[asset_inventory]", collections)
            self.assertIn("field.ip = string", collections)
            self.assertIn("external_type = kvstore", transforms)
            self.assertIn("fields_list = _key, ip, risk", transforms)
            self.assertIn("kvstoreUpgradeOnStartupEnabled = false", server)
            self.assertIn("start-shcluster-migration kvstore -storageEngine wiredTiger", migrate)
            self.assertIn("start-shcluster-upgrade kvstore -version", upgrade)
            self.assertIn("backup kvstore -pointInTime true", backup)
            self.assertIn("spv_require_supported_splunk_home", backup)

    def test_enterprise_106_defer_flag_is_distinct_from_kvserver_upgrade_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--defer-postgres-migration", "true",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            server = (Path(tmpdir) / "kvstore" / "server.conf").read_text(encoding="utf-8")
            self.assertIn("postgresMigrateOnStartup = false", server)
            self.assertNotIn("kvstoreUpgradeOnStartupEnabled", server)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer("--output-dir", tmpdir)
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            server = (Path(tmpdir) / "kvstore" / "server.conf").read_text(encoding="utf-8")
            self.assertNotIn("postgresMigrateOnStartup", server)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--defer-postgres-migration", "true",
                "--disable-startup-upgrade", "true",
                "--enterprise-version", "10.2.0",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            server = (Path(tmpdir) / "kvstore" / "server.conf").read_text(encoding="utf-8")
            self.assertEqual(server.count("[kvstore]"), 1)
            self.assertIn("postgresMigrateOnStartup = false", server)
            self.assertIn("kvstoreUpgradeOnStartupEnabled = false", server)

    def test_setup_wrapper_forwards_enterprise_106_defer_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--phase", "render",
                "--output-dir", tmpdir,
                "--platform", "enterprise",
                "--defer-postgres-migration", "true",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            server = (Path(tmpdir) / "kvstore" / "server.conf").read_text(encoding="utf-8")
            self.assertIn("postgresMigrateOnStartup = false", server)

    def test_auto_backup_renders_authenticated_status_selection_and_polling(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer("--output-dir", tmpdir, "--backup-mode", "auto")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            backup = (Path(tmpdir) / "kvstore" / "backup.sh").read_text(encoding="utf-8")
            self.assertNotIn("show kvstore-status --verbose", backup)
            self.assertIn("show kvstore-status >", backup)
            self.assertIn('type.lower() == "pdl"', backup)
            self.assertIn("cohosted kvstore information", backup.lower())
            self.assertIn("Service Info", backup)
            self.assertIn("-backupParallelJobs true", backup)
            self.assertIn("-pointInTime true", backup)
            self.assertIn("backupRestoreStatus", backup)
            self.assertIn("backupRestoreStatus=Ready", backup)
            self.assertIn("member status is", backup)
            self.assertIn('cohosted_status}" != "ready"', backup)
            self.assertIn("KVSTORE_BACKUP_STATUS_TIMEOUT_SECONDS must be an integer", backup)
            self.assertIn("bounded timeout", backup)

    def test_explicit_point_in_time_refuses_cohosted_and_legacy_path_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pit = self.run_renderer(
                "--output-dir", str(Path(tmpdir) / "pit"),
                "--point-in-time", "true",
            )
            self.assertEqual(pit.returncode, 0, msg=pit.stdout + pit.stderr)
            pit_script = (Path(tmpdir) / "pit" / "kvstore" / "backup.sh").read_text(encoding="utf-8")
            self.assertIn("explicit point-in-time/legacy mode is unsupported for cohosted", pit_script)
            legacy = self.run_renderer(
                "--output-dir", str(Path(tmpdir) / "legacy"),
                "--point-in-time", "false",
            )
            self.assertEqual(legacy.returncode, 0, msg=legacy.stdout + legacy.stderr)
            legacy_script = (Path(tmpdir) / "legacy" / "kvstore" / "backup.sh").read_text(encoding="utf-8")
            self.assertIn('backup kvstore "${backup_archive_args[@]}"', legacy_script)

    def test_parallel_restore_adds_tar_suffix_and_requires_completed_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--backup-mode", "parallel",
                "--backup-archive-name", "kvdump",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            restore = (Path(tmpdir) / "kvstore" / "restore.sh").read_text(encoding="utf-8")
            self.assertIn("restore_archive_name=\"${archive_name}\"", restore)
            self.assertIn('restore_archive_name="${restore_archive_name}.tar.gz"', restore)
            self.assertIn("-restoreParallelJobs true", restore)
            self.assertIn("backup_restore_operation=restore", restore)

    def test_shc_restore_maintenance_is_only_enabled_for_point_in_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            parallel = self.run_renderer(
                "--output-dir", str(Path(tmpdir) / "parallel"),
                "--topology", "shc", "--backup-mode", "parallel",
                "--backup-archive-name", "shc-parallel",
            )
            self.assertEqual(parallel.returncode, 0, msg=parallel.stdout + parallel.stderr)
            parallel_restore = (Path(tmpdir) / "parallel" / "kvstore" / "restore.sh").read_text(encoding="utf-8")
            self.assertIn('if [[ "${selected_backup_mode}" == "point-in-time" ]]', parallel_restore)
            self.assertIn("-restoreParallelJobs true", parallel_restore)
            self.assertIn("point-in-time restore", parallel_restore)

            pit = self.run_renderer(
                "--output-dir", str(Path(tmpdir) / "pit"),
                "--topology", "shc", "--backup-mode", "point-in-time",
                "--backup-archive-name", "shc-pit",
            )
            self.assertEqual(pit.returncode, 0, msg=pit.stdout + pit.stderr)
            pit_restore = (Path(tmpdir) / "pit" / "kvstore" / "restore.sh").read_text(encoding="utf-8")
            self.assertIn('enable kvstore-maintenance-mode', pit_restore)
            self.assertIn('disable kvstore-maintenance-mode', pit_restore)

    def test_shc_restore_runtime_maintenance_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home = root / "splunk"
            (home / "bin").mkdir(parents=True)
            status = root / "status.txt"
            calls = root / "calls.txt"
            fake = home / "bin" / "splunk"
            fake.write_text(
                "#!/bin/sh\n"
                "echo \"$*\" >>\"${FAKE_CALLS}\"\n"
                "if [ \"$1\" = version ]; then echo 'Splunk 10.6.0'; exit 0; fi\n"
                "if [ \"$1\" = show ]; then cat \"${FAKE_STATUS}\"; exit 0; fi\n"
                "if [ \"$1\" = restore ] && [ \"${FAKE_FAIL_RESTORE:-false}\" = true ]; then exit 22; fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            status.write_text("This member:\nstatus : ready\nbackupRestoreStatus : Ready\n", encoding="utf-8")
            env = os.environ | {
                "SPLUNK_PLATFORM": "enterprise",
                "FAKE_STATUS": str(status),
                "FAKE_CALLS": str(calls),
                "KVSTORE_ACCEPT_RESTORE": "true",
                "KVSTORE_BACKUP_STATUS_TIMEOUT_SECONDS": "1",
                "KVSTORE_BACKUP_STATUS_POLL_SECONDS": "1",
            }

            parallel_render = self.run_renderer(
                "--output-dir", str(root / "parallel"), "--platform", "enterprise",
                "--topology", "shc", "--splunk-home", str(home),
                "--backup-mode", "parallel", "--backup-archive-name", "parallel-archive",
            )
            self.assertEqual(parallel_render.returncode, 0, msg=parallel_render.stdout + parallel_render.stderr)
            parallel = subprocess.run(
                ["bash", str(root / "parallel" / "kvstore" / "restore.sh")],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(parallel.returncode, 0, msg=parallel.stdout + parallel.stderr)
            parallel_calls = calls.read_text(encoding="utf-8")
            self.assertIn("restore kvstore -restoreParallelJobs true", parallel_calls)
            self.assertNotIn("enable kvstore-maintenance-mode", parallel_calls)
            self.assertNotIn("disable kvstore-maintenance-mode", parallel_calls)

            pit_render = self.run_renderer(
                "--output-dir", str(root / "pit"), "--platform", "enterprise",
                "--topology", "shc", "--splunk-home", str(home),
                "--backup-mode", "point-in-time", "--backup-archive-name", "pit-archive",
            )
            self.assertEqual(pit_render.returncode, 0, msg=pit_render.stdout + pit_render.stderr)
            calls.write_text("", encoding="utf-8")
            pit = subprocess.run(
                ["bash", str(root / "pit" / "kvstore" / "restore.sh")],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(pit.returncode, 0, msg=pit.stdout + pit.stderr)
            pit_calls = calls.read_text(encoding="utf-8")
            self.assertIn("enable kvstore-maintenance-mode", pit_calls)
            self.assertIn("restore kvstore -pointInTime true", pit_calls)
            self.assertIn("disable kvstore-maintenance-mode", pit_calls)

            calls.write_text("", encoding="utf-8")
            failed = subprocess.run(
                ["bash", str(root / "pit" / "kvstore" / "restore.sh")],
                env=env | {"FAKE_FAIL_RESTORE": "true"},
                capture_output=True, text=True, timeout=30,
            )
            self.assertNotEqual(failed.returncode, 0)
            failed_calls = calls.read_text(encoding="utf-8")
            self.assertIn("enable kvstore-maintenance-mode", failed_calls)
            self.assertNotIn("disable kvstore-maintenance-mode", failed_calls)

    def test_cohosted_ready_and_busy_statuses_drive_runtime_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home = root / "splunk"
            (home / "bin").mkdir(parents=True)
            status = root / "status.txt"
            calls = root / "calls.txt"
            fake = home / "bin" / "splunk"
            fake.write_text(
                "#!/bin/sh\n"
                "echo \"$*\" >>\"${FAKE_CALLS}\"\n"
                "if [ \"$1\" = version ]; then echo 'Splunk 10.6.0'; exit 0; fi\n"
                "if [ \"$1\" = show ]; then cat \"${FAKE_STATUS}\"; exit 0; fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            result = self.run_renderer(
                "--output-dir", str(root / "rendered"),
                "--platform", "enterprise",
                "--splunk-home", str(home),
                "--backup-mode", "auto",
                "--backup-archive-name", "cohosted-backup",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            script = root / "rendered" / "kvstore" / "backup.sh"
            env = os.environ | {
                "SPLUNK_PLATFORM": "enterprise",
                "FAKE_STATUS": str(status),
                "FAKE_CALLS": str(calls),
                "KVSTORE_BACKUP_STATUS_TIMEOUT_SECONDS": "1",
                "KVSTORE_BACKUP_STATUS_POLL_SECONDS": "1",
            }
            status.write_text(
                "This member:\nbackupRestoreStatus : Ready\nstatus : ready\n"
                "Cohosted KVStore Information:\nstatus : ready\nService Info\n type : Pdl\n",
                encoding="utf-8",
            )
            ready = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(ready.returncode, 0, msg=ready.stdout + ready.stderr)
            self.assertIn("backup kvstore -backupParallelJobs true", calls.read_text(encoding="utf-8"))
            status.write_text("This member:\nbackupRestoreStatus : Ready\nstatus : busy\n", encoding="utf-8")
            busy = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(busy.returncode, 0)
            self.assertIn("member status is busy", busy.stdout + busy.stderr)

    def test_explicit_parallel_mode_supports_legacy_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home = root / "splunk"
            (home / "bin").mkdir(parents=True)
            status = root / "status.txt"
            calls = root / "calls.txt"
            fake = home / "bin" / "splunk"
            fake.write_text(
                "#!/bin/sh\n"
                "echo \"$*\" >>\"${FAKE_CALLS}\"\n"
                "if [ \"$1\" = version ]; then echo 'Splunk 10.6.0'; exit 0; fi\n"
                "if [ \"$1\" = show ]; then cat \"${FAKE_STATUS}\"; exit 0; fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            result = self.run_renderer(
                "--output-dir", str(root / "rendered"),
                "--platform", "enterprise",
                "--splunk-home", str(home),
                "--backup-mode", "parallel",
                "--backup-archive-name", "legacy-backup",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            status.write_text("This member:\nstatus : ready\nbackupRestoreStatus : Ready\n", encoding="utf-8")
            env = os.environ | {
                "SPLUNK_PLATFORM": "enterprise",
                "FAKE_STATUS": str(status),
                "FAKE_CALLS": str(calls),
            }
            completed = subprocess.run(
                ["bash", str(root / "rendered" / "kvstore" / "backup.sh")],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stdout + completed.stderr)
            self.assertIn("backup kvstore -backupParallelJobs true", calls.read_text(encoding="utf-8"))

    def test_rejects_arbitrary_enterprise_version_as_kvstore_server_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--topology", "shc",
                "--target-kvstore-version", "10.5",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("supported 7.0 or 8.0.x", result.stderr)

    def test_rejects_removed_startup_upgrade_disable_on_enterprise_10_3_plus(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--enterprise-version", "10.3.0",
                "--disable-startup-upgrade", "true",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("removed and unsupported", result.stderr)

    def test_explicit_enterprise_version_is_checked_by_live_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--platform", "enterprise",
                "--enterprise-version", "10.6.0.5",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            script = (Path(tmpdir) / "kvstore" / "status.sh").read_text(encoding="utf-8")
            self.assertIn("does not match expected", script)
            self.assertIn("expected_enterprise_version=10.6.0.5", script)

    def test_shc_migration_rejects_cohosted_and_already_wiredtiger(self) -> None:
        for label, status in (
            (
                "cohosted",
                "This member:\nstatus : ready\nstorageEngine : wiredTiger\n"
                "Cohosted KVStore Information:\nstatus : ready\ntype : Pdl\n",
            ),
            (
                "wiredtiger",
                "This member:\nstatus : ready\nstorageEngine : wiredTiger\nversion : 7.0\n",
            ),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                home = root / "splunk"
                (home / "bin").mkdir(parents=True)
                status_file = root / "status.txt"
                calls = root / "calls.txt"
                (home / "bin" / "splunk").write_text(
                    "#!/bin/sh\n"
                    "echo \"$*\" >>\"${FAKE_CALLS}\"\n"
                    "if [ \"$1\" = version ]; then echo 'Splunk 10.6.0'; exit 0; fi\n"
                    "if [ \"$1\" = show ]; then cat \"${FAKE_STATUS}\"; exit 0; fi\n"
                    "exit 0\n",
                    encoding="utf-8",
                )
                (home / "bin" / "splunk").chmod(0o755)
                status_file.write_text(status, encoding="utf-8")
                rendered = self.run_renderer(
                    "--output-dir", str(root / "rendered"),
                    "--platform", "enterprise", "--topology", "shc",
                    "--splunk-home", str(home), "--storage-engine", "wiredTiger",
                )
                self.assertEqual(rendered.returncode, 0, msg=rendered.stdout + rendered.stderr)
                env = os.environ | {
                    "SPLUNK_PLATFORM": "enterprise",
                    "FAKE_STATUS": str(status_file),
                    "FAKE_CALLS": str(calls),
                    "KVSTORE_ACCEPT_MIGRATION": "true",
                }
                applied = subprocess.run(
                    ["bash", str(root / "rendered" / "kvstore" / "migrate.sh")],
                    env=env, capture_output=True, text=True, timeout=30,
                )
                self.assertNotEqual(applied.returncode, 0, msg=applied.stdout + applied.stderr)
                self.assertNotIn("start-shcluster-migration", calls.read_text(encoding="utf-8"))

    def test_shc_migration_accepts_verified_legacy_mmapv1(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home = root / "splunk"
            (home / "bin").mkdir(parents=True)
            status_file = root / "status.txt"
            calls = root / "calls.txt"
            (home / "bin" / "splunk").write_text(
                "#!/bin/sh\n"
                "echo \"$*\" >>\"${FAKE_CALLS}\"\n"
                "if [ \"$1\" = version ]; then echo 'Splunk 10.2.0'; exit 0; fi\n"
                "if [ \"$1\" = show ]; then cat \"${FAKE_STATUS}\"; exit 0; fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            (home / "bin" / "splunk").chmod(0o755)
            status_file.write_text(
                "This member:\nstatus : ready\nstorageEngine : mmapv1\nversion : 4.2\n",
                encoding="utf-8",
            )
            rendered = self.run_renderer(
                "--output-dir", str(root / "rendered"),
                "--platform", "enterprise", "--topology", "shc",
                "--splunk-home", str(home), "--storage-engine", "wiredTiger",
            )
            self.assertEqual(rendered.returncode, 0, msg=rendered.stdout + rendered.stderr)
            env = os.environ | {
                "SPLUNK_PLATFORM": "enterprise",
                "FAKE_STATUS": str(status_file),
                "FAKE_CALLS": str(calls),
                "KVSTORE_ACCEPT_MIGRATION": "true",
            }
            applied = subprocess.run(
                ["bash", str(root / "rendered" / "kvstore" / "migrate.sh")],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(applied.returncode, 0, msg=applied.stdout + applied.stderr)
            self.assertIn("start-shcluster-migration kvstore -storageEngine wiredTiger", calls.read_text(encoding="utf-8"))

    def test_shc_upgrade_requires_verified_legacy_7_to_8_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home = root / "splunk"
            (home / "bin").mkdir(parents=True)
            status_file = root / "status.txt"
            calls = root / "calls.txt"
            (home / "bin" / "splunk").write_text(
                "#!/bin/sh\n"
                "echo \"$*\" >>\"${FAKE_CALLS}\"\n"
                "if [ \"$1\" = version ]; then echo 'Splunk 10.6.0'; exit 0; fi\n"
                "if [ \"$1\" = show ]; then cat \"${FAKE_STATUS}\"; exit 0; fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            (home / "bin" / "splunk").chmod(0o755)
            rendered = self.run_renderer(
                "--output-dir", str(root / "rendered"),
                "--platform", "enterprise", "--topology", "shc",
                "--splunk-home", str(home), "--target-kvstore-version", "8.0",
            )
            self.assertEqual(rendered.returncode, 0, msg=rendered.stdout + rendered.stderr)
            env = os.environ | {
                "SPLUNK_PLATFORM": "enterprise",
                "FAKE_STATUS": str(status_file),
                "FAKE_CALLS": str(calls),
                "KVSTORE_ACCEPT_UPGRADE": "true",
            }
            status_file.write_text(
                "This member:\nstatus : ready\nstorageEngine : wiredTiger\nversion : 7.0\n",
                encoding="utf-8",
            )
            valid = subprocess.run(
                ["bash", str(root / "rendered" / "kvstore" / "upgrade.sh")],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(valid.returncode, 0, msg=valid.stdout + valid.stderr)
            self.assertIn("start-shcluster-upgrade kvstore -version 8.0", calls.read_text(encoding="utf-8"))

            status_file.write_text(
                "This member:\nstatus : ready\nstorageEngine : wiredTiger\nversion : 4.2.17\n",
                encoding="utf-8",
            )
            calls.write_text("", encoding="utf-8")
            direct = subprocess.run(
                ["bash", str(root / "rendered" / "kvstore" / "upgrade.sh")],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(direct.returncode, 0, msg=direct.stdout + direct.stderr)
            self.assertIn("start-shcluster-upgrade kvstore -version 8.0", calls.read_text(encoding="utf-8"))

            status_file.write_text(
                "This member:\nstatus : ready\nstorageEngine : wiredTiger\nversion : unknown\n",
                encoding="utf-8",
            )
            calls.write_text("", encoding="utf-8")
            unknown = subprocess.run(
                ["bash", str(root / "rendered" / "kvstore" / "upgrade.sh")],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertNotEqual(unknown.returncode, 0, msg=unknown.stdout + unknown.stderr)
            self.assertNotIn("start-shcluster-upgrade", calls.read_text(encoding="utf-8"))

            for label, invalid_status in (
                ("cohosted", "This member:\nstatus : ready\nstorageEngine : wiredTiger\nversion : 7.0\nCohosted KVStore Information:\nstatus : ready\ntype : Pdl\n"),
                ("equal", "This member:\nstatus : ready\nstorageEngine : wiredTiger\nversion : 8.0\n"),
                ("downgrade", "This member:\nstatus : ready\nstorageEngine : wiredTiger\nversion : 8.0\n"),
                ("unknown-engine", "This member:\nstatus : ready\nstorageEngine : unknown\nversion : 7.0\n"),
            ):
                with self.subTest(label=label):
                    status_file.write_text(invalid_status, encoding="utf-8")
                    calls.write_text("", encoding="utf-8")
                    upgrade_script = root / "rendered" / "kvstore" / "upgrade.sh"
                    if label == "downgrade":
                        rerendered = self.run_renderer(
                            "--output-dir", str(root / "rendered-downgrade"),
                            "--platform", "enterprise", "--topology", "shc",
                            "--splunk-home", str(home), "--target-kvstore-version", "7.0",
                        )
                        self.assertEqual(rerendered.returncode, 0, msg=rerendered.stdout + rerendered.stderr)
                        upgrade_script = root / "rendered-downgrade" / "kvstore" / "upgrade.sh"
                    rejected = subprocess.run(
                        ["bash", str(upgrade_script)],
                        env=env | {"KVSTORE_ACCEPT_UPGRADE": "true"},
                        capture_output=True, text=True, timeout=30,
                    )
                    self.assertNotEqual(rejected.returncode, 0, msg=rejected.stdout + rejected.stderr)
                    self.assertNotIn("start-shcluster-upgrade", calls.read_text(encoding="utf-8"))

    def test_rejects_bad_field_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--collection-name", "c1",
                "--collection-fields", "ip:ipaddress",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Field type", result.stderr)

    def test_rejects_lookup_without_collection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--lookup-definition-name", "orphan_lookup",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires --collection-name", result.stderr)

    def test_restore_refused_without_acceptance_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--platform", "enterprise",
                "--phase", "apply",
                "--operation", "restore",
                "--backup-archive-name", "kvdump.tar.gz",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--accept-kvstore-restore", result.stdout + result.stderr)

    def test_clean_refused_without_acceptance_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--platform", "enterprise",
                "--phase", "apply",
                "--operation", "clean",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--accept-kvstore-clean", result.stdout + result.stderr)

    def test_dry_run_collections_does_not_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--platform", "enterprise",
                "--dry-run",
                "--phase", "apply",
                "--operation", "collections",
                "--collection-name", "asset_inventory",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("DRY RUN", result.stdout + result.stderr)

    def test_cloud_host_lifecycle_apply_exits_before_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            for operation in ("backup", "restore", "clean", "migrate", "upgrade"):
                with self.subTest(operation=operation):
                    output_dir = Path(tmpdir) / operation
                    output_dir.mkdir()
                    sentinel = output_dir / "operator-note.txt"
                    sentinel.write_text("preserve me\n", encoding="utf-8")
                    result = self.run_setup(
                        "--output-dir", str(output_dir),
                        "--platform", "cloud",
                        "--phase", "apply",
                        "--operation", operation,
                    )
                    output = result.stdout + result.stderr
                    self.assertEqual(result.returncode, 2, msg=output)
                    self.assertIn("not customer-managed on Splunk Cloud", output)
                    self.assertFalse((output_dir / "kvstore").exists())
                    self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve me\n")

    def test_auto_platform_resolves_cloud_before_lifecycle_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "rendered"
            env = os.environ.copy()
            env["SPLUNK_PLATFORM"] = "cloud"
            result = subprocess.run(
                [
                    "bash", str(SETUP),
                    "--output-dir", str(output_dir),
                    "--phase", "apply",
                    "--operation", "backup",
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
            self.assertFalse(output_dir.exists())

    def test_cloud_rendered_host_script_is_a_non_mutating_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            splunk_home = Path(tmpdir) / "managed-cloud-must-not-exist"
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--platform", "cloud",
                "--splunk-home", str(splunk_home),
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "kvstore"
            for name in ("backup.sh", "restore.sh", "clean.sh", "migrate.sh", "upgrade.sh"):
                with self.subTest(script=name):
                    script = render_dir / name
                    applied = subprocess.run(
                        ["bash", str(script)],
                        cwd=script.parent,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=60,
                    )
                    self.assertEqual(applied.returncode, 2, msg=applied.stdout + applied.stderr)
                    self.assertIn("Managed Splunk Cloud owns KV Store host lifecycle", applied.stderr)
            self.assertFalse(splunk_home.exists())

    def test_cloud_collection_governance_dry_run_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--platform", "cloud",
                "--dry-run",
                "--phase", "apply",
                "--operation", "collections",
                "--collection-name", "asset_inventory",
                "--collection-fields", "ip:string,risk:number",
                "--lookup-definition-name", "asset_inventory_lookup",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("via REST", result.stdout + result.stderr)
            self.assertIn("on cloud", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
