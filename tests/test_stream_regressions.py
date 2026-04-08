#!/usr/bin/env python3
"""Regression tests for Splunk Stream shell scripts."""

import json
import os
import tempfile
import textwrap
from pathlib import Path

from tests.regression_helpers import (
    REPO_ROOT,
    ShellScriptRegressionBase,
    write_executable,
)


class StreamRegressionTests(ShellScriptRegressionBase):
    def test_stream_indexes_only_cloud_mode_uses_acs_without_session_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            acs_log = tmp_path / "acs.log"
            credentials_file = tmp_path / "credentials"

            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                log_path = Path(os.environ["ACS_LOG"])
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(" ".join(sys.argv[1:]) + "\\n")

                args = sys.argv[1:]
                if "indexes" in args and "describe" in args:
                    raise SystemExit(1)
                raise SystemExit(0)
                """,
            )

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_CLOUD_STACK="example-stack"
                    ACS_SERVER="https://staging.admin.splunk.com"
                    STACK_TOKEN="token"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["ACS_LOG"] = str(acs_log)
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/setup.sh",
                "--indexes-only",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            acs_output = acs_log.read_text(encoding="utf-8")
            self.assertIn("indexes create --name netflow", acs_output)
            self.assertIn("indexes create --name stream", acs_output)

    def test_stream_role_topology_matches_split_package_model(self):
        registry = json.loads((REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8"))

        stream_topology = next(
            entry for entry in registry.get("skill_topologies", []) if entry.get("skill") == "splunk-stream-setup"
        )
        self.assertEqual(
            stream_topology["role_support"],
            {
                "search-tier": "required",
                "indexer": "supported",
                "heavy-forwarder": "required",
                "universal-forwarder": "supported",
                "external-collector": "none",
            },
        )
        self.assertEqual(
            stream_topology["cloud_pairing"],
            ["heavy-forwarder", "universal-forwarder"],
        )

        stream_apps = {
            app["app_name"]: app["role_support"]
            for app in registry.get("apps", [])
            if app.get("skill") == "splunk-stream-setup"
        }
        self.assertEqual(
            stream_apps["splunk_app_stream"],
            {
                "search-tier": "required",
                "indexer": "none",
                "heavy-forwarder": "none",
                "universal-forwarder": "none",
                "external-collector": "none",
            },
        )
        self.assertEqual(
            stream_apps["Splunk_TA_stream"],
            {
                "search-tier": "none",
                "indexer": "none",
                "heavy-forwarder": "required",
                "universal-forwarder": "supported",
                "external-collector": "none",
            },
        )
        self.assertEqual(
            stream_apps["Splunk_TA_stream_wire_data"],
            {
                "search-tier": "supported",
                "indexer": "required",
                "heavy-forwarder": "supported",
                "universal-forwarder": "none",
                "external-collector": "none",
            },
        )

    def test_stream_app_registry_uses_current_splunkbase_ids(self):
        registry = json.loads((REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8"))
        stream_entries = {
            app["app_name"]: app["splunkbase_id"]
            for app in registry.get("apps", [])
            if app.get("skill") == "splunk-stream-setup"
        }

        self.assertEqual(stream_entries["splunk_app_stream"], "1809")
        self.assertEqual(stream_entries["Splunk_TA_stream"], "5238")
        self.assertEqual(stream_entries["Splunk_TA_stream_wire_data"], "5234")

    def test_stream_validate_search_tier_downgrades_forwarder_checks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env = self._build_mock_stream_validate_env(
                tmp_path,
                target_role="search-tier",
                state={
                    "apps": {
                        "splunk_app_stream": {"version": "8.1.6"},
                    },
                    "indexes": [],
                    "configs": {},
                    "counts": {"source=stream": 0, "index=netflow": 0},
                    "kvstore_status": "ready",
                },
            )

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/validate.sh",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn(
                "Splunk TA Stream (Forwarder) is not installed on this search-tier target",
                result.stdout,
            )
            self.assertIn(
                "Forwarder-side streamfwd validation is skipped on the search tier",
                result.stdout,
            )
            self.assertNotIn("FAIL: Splunk TA Stream (Forwarder) not installed", result.stdout)
            self.assertNotIn("FAIL: streamfwd.conf stanza not found", result.stdout)

    def test_stream_validate_heavy_forwarder_downgrades_search_tier_app_requirement(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env = self._build_mock_stream_validate_env(
                tmp_path,
                target_role="heavy-forwarder",
                state={
                    "apps": {
                        "Splunk_TA_stream": {"version": "8.1.6"},
                    },
                    "indexes": [],
                    "configs": {
                        "streamfwd:streamfwd": {
                            "ipAddr": "10.1.1.10",
                            "port": "8889",
                            "netflowReceiver.0.port": "9995",
                        },
                        "inputs:streamfwd://streamfwd": {
                            "splunk_stream_app_location": "https://stream.example/en-us/custom/splunk_app_stream/",
                            "sslVerifyServerCert": "false",
                            "disabled": "0",
                        },
                    },
                    "counts": {"source=stream": 0, "index=netflow": 0},
                    "kvstore_status": "ready",
                },
            )

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/validate.sh",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn(
                "Splunk Stream search-tier app is not installed on this forwarder target",
                result.stdout,
            )
            self.assertIn("streamfwd.conf stanza exists", result.stdout)
            self.assertIn("KV Store check skipped on heavy-forwarder", result.stdout)
            self.assertNotIn("FAIL: Splunk Stream not installed", result.stdout)

    def test_stream_validate_indexer_focuses_on_wire_data_requirements(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env = self._build_mock_stream_validate_env(
                tmp_path,
                target_role="indexer",
                state={
                    "apps": {
                        "Splunk_TA_stream_wire_data": {"version": "8.1.6"},
                    },
                    "indexes": [],
                    "configs": {},
                    "counts": {"source=stream": 0, "index=netflow": 0},
                    "kvstore_status": "ready",
                },
            )

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/validate.sh",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Splunk TA Stream Wire Data installed", result.stdout)
            self.assertIn(
                "Splunk TA Stream (Forwarder) is not installed on this indexer target",
                result.stdout,
            )
            self.assertIn(
                "Forwarder-side streamfwd validation is skipped on the indexer tier",
                result.stdout,
            )
            self.assertIn("KV Store check skipped on indexer", result.stdout)
            self.assertNotIn("FAIL: Splunk TA Stream (Forwarder) not installed", result.stdout)

    def test_stream_validate_hybrid_cloud_profile_stays_search_tier_focused(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env = self._build_mock_stream_validate_env(
                tmp_path,
                state={
                    "apps": {
                        "splunk_app_stream": {"version": "8.1.6"},
                    },
                    "indexes": [],
                    "configs": {},
                    "counts": {"source=stream": 0, "index=netflow": 0},
                    "kvstore_status": "ready",
                },
                credentials_text=textwrap.dedent(
                    """\
                    SPLUNK_PROFILE="cloud"
                    SPLUNK_SEARCH_PROFILE="hf"
                    PROFILE_cloud__SPLUNK_PLATFORM="cloud"
                    PROFILE_cloud__SPLUNK_CLOUD_STACK="example-stack"
                    PROFILE_cloud__ACS_SERVER="https://staging.admin.splunk.com"
                    PROFILE_cloud__STACK_TOKEN="token"
                    PROFILE_cloud__STACK_USERNAME="stack-user"
                    PROFILE_cloud__STACK_PASSWORD="stack-pass"
                    PROFILE_cloud__SPLUNK_TARGET_ROLE="search-tier"
                    PROFILE_hf__SPLUNK_PLATFORM="enterprise"
                    PROFILE_hf__SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
                    PROFILE_hf__SPLUNK_USER="hf-user"
                    PROFILE_hf__SPLUNK_PASS="hf-pass"
                    PROFILE_hf__SPLUNK_TARGET_ROLE="heavy-forwarder"
                    SPLUNK_SEARCH_TARGET_ROLE="heavy-forwarder"
                    """
                ),
                acs_search_head="shc1",
            )

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/validate.sh",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn(
                "Splunk TA Stream (Forwarder) is not installed on this search-tier target",
                result.stdout,
            )
            self.assertIn(
                "Forwarder-side streamfwd validation is skipped on the search tier",
                result.stdout,
            )
            self.assertNotIn(
                "search-tier app is not installed on this forwarder target",
                result.stdout,
            )
            self.assertNotIn("KV Store check skipped on heavy-forwarder", result.stdout)

    def test_configure_streams_help_does_not_require_profile_selection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            credentials_file = tmp_path / "credentials"

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    PROFILE_cloud__SPLUNK_PLATFORM="cloud"
                    PROFILE_cloud__SPLUNK_SEARCH_API_URI="https://stack.stg.splunkcloud.com:8089"
                    PROFILE_cloud__SPLUNK_CLOUD_STACK="stack"
                    PROFILE_onprem__SPLUNK_PLATFORM="enterprise"
                    PROFILE_onprem__SPLUNK_SEARCH_API_URI="https://onprem.example.com:8089"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/configure_streams.sh",
                "--help",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("Usage:", result.stdout)
            self.assertNotIn("Multiple credential profiles are defined", output)

    def test_configure_streams_rejects_forwarder_roles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            credentials_file = tmp_path / "credentials"

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    SPLUNK_TARGET_ROLE="heavy-forwarder"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/configure_streams.sh",
                "--list",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, msg=output)
            self.assertIn("search-tier only", output)
            self.assertIn("heavy-forwarder", output)
            self.assertNotIn("Could not authenticate", output)

    def test_configure_streams_uses_refreshed_cloud_stream_web_uri(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            curl_log = tmp_path / "curl.log"

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_PROFILE="cloud"
                    SPLUNK_SEARCH_PROFILE="hf"
                    PROFILE_cloud__SPLUNK_PLATFORM="cloud"
                    PROFILE_cloud__SPLUNK_CLOUD_STACK="stack"
                    PROFILE_cloud__SPLUNK_CLOUD_SEARCH_HEAD="shc1"
                    PROFILE_cloud__ACS_SERVER="https://staging.admin.splunk.com"
                    PROFILE_cloud__STACK_TOKEN="token"
                    PROFILE_cloud__SPLUNK_USER="cloud-user"
                    PROFILE_cloud__SPLUNK_PASS="cloud-pass"
                    PROFILE_cloud__SPLUNK_TARGET_ROLE="search-tier"
                    PROFILE_hf__SPLUNK_PLATFORM="enterprise"
                    PROFILE_hf__SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
                    PROFILE_hf__SPLUNK_USER="hf-user"
                    PROFILE_hf__SPLUNK_PASS="hf-pass"
                    PROFILE_hf__SPLUNK_TARGET_ROLE="heavy-forwarder"
                    """
                ),
                encoding="utf-8",
            )

            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "nc",
                """\
                #!/usr/bin/env bash
                exit 0
                """,
            )
            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                log_path = Path(os.environ["CURL_LOG"])
                args = sys.argv[1:]
                url = next((arg for arg in args if arg.startswith("http://") or arg.startswith("https://")), "")
                joined = " ".join(args)

                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(url + "\\n")

                if "/services/auth/login" in url and "-d" in args:
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                    raise SystemExit(0)

                if "/servicesNS/nobody/splunk_app_stream/storage/collections/data/streams" in url and "%{http_code}" in joined:
                    sys.stdout.write("\\n404")
                    raise SystemExit(0)

                if "/en-US/custom/splunk_app_stream/streams" in url and "%{http_code}" in joined:
                    sys.stdout.write('{"streams":[{"id":"dns","enabled":true,"index":"stream"}]}\\n200')
                    raise SystemExit(0)

                if "/services/auth/login" in url and "%{http_code}" in joined:
                    sys.stdout.write("200")
                    raise SystemExit(0)

                if "/services/server/info" in url and "%{http_code}" in joined:
                    sys.stdout.write("200")
                    raise SystemExit(0)

                raise SystemExit(0)
                """,
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
            env["CURL_LOG"] = str(curl_log)
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
            env["SPLUNK_SKIP_ALLOWLIST"] = "true"

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/configure_streams.sh",
                "--list",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("dns", output)

            curl_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn(
                "https://shc1.stack.stg.splunkcloud.com:443/en-US/custom/splunk_app_stream/streams?output_mode=json",
                curl_requests,
            )
            self.assertNotIn(
                "https://hf.example.com:443/en-US/custom/splunk_app_stream/streams?output_mode=json",
                curl_requests,
            )

    def test_stream_setup_install_prefers_splunkbase_before_local_fallback_in_legacy_mode(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            ta_cache = tmp_path / "splunk-ta"
            ta_cache.mkdir()
            install_log = tmp_path / "install.log"
            credentials_file = tmp_path / "credentials"
            registry_file = tmp_path / "app_registry.json"
            app_install_script = tmp_path / "fake_install_app.sh"

            for filename in (
                "splunk-app-for-stream_816.tgz",
                "splunk-add-on-for-stream-forwarders_816.tgz",
                "splunk-add-on-for-stream-wire-data_816.tgz",
            ):
                (ta_cache / filename).write_text("placeholder", encoding="utf-8")

            registry_file.write_text(
                textwrap.dedent(
                    """\
                    {
                      "apps": [
                        {
                          "skill": "splunk-stream-setup",
                          "app_name": "splunk_app_stream",
                          "splunkbase_id": "1809"
                        },
                        {
                          "skill": "splunk-stream-setup",
                          "app_name": "Splunk_TA_stream",
                          "splunkbase_id": "5238"
                        },
                        {
                          "skill": "splunk-stream-setup",
                          "app_name": "Splunk_TA_stream_wire_data",
                          "splunkbase_id": "5234"
                        }
                      ]
                    }
                    """
                ),
                encoding="utf-8",
            )

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_SEARCH_API_URI="https://example.invalid:8089"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    """
                ),
                encoding="utf-8",
            )

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import sys

                args = " ".join(sys.argv[1:])
                if "/services/auth/login" in args and "-d @-" in args:
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                elif "/services/server/info" in args and "%{http_code}" in args:
                    sys.stdout.write("200")
                elif "/services/apps/local/" in args and "%{http_code}" in args:
                    sys.stdout.write("404")
                elif "/services/auth/login" in args and "%{http_code}" in args:
                    sys.stdout.write("200")
                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "nc",
                """\
                #!/usr/bin/env bash
                exit 0
                """,
            )
            write_executable(
                app_install_script,
                """\
                #!/usr/bin/env bash
                set -euo pipefail
                printf '%s\\n' "$*" >> "${INSTALL_LOG}"
                if [[ "$*" == *"--source splunkbase --app-id 5238"* ]]; then
                    exit 1
                fi
                exit 0
                """,
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
            env["TA_CACHE"] = str(ta_cache)
            env["REGISTRY_FILE"] = str(registry_file)
            env["APP_INSTALL_SCRIPT"] = str(app_install_script)
            env["INSTALL_LOG"] = str(install_log)

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/setup.sh",
                "--install",
                "--legacy-all-in-one",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            install_lines = install_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                install_lines,
                [
                    "--source splunkbase --app-id 1809 --no-update --no-restart",
                    "--source splunkbase --app-id 5238 --no-update --no-restart",
                    f"--source local --file {ta_cache / 'splunk-add-on-for-stream-forwarders_816.tgz'} --no-update --no-restart",
                    "--source splunkbase --app-id 5234 --no-update --no-restart",
                ],
            )

    def test_stream_setup_install_requires_declared_role_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            ta_cache = tmp_path / "splunk-ta"
            ta_cache.mkdir()
            credentials_file = tmp_path / "credentials"
            registry_file = tmp_path / "app_registry.json"

            for filename in (
                "splunk-app-for-stream_816.tgz",
                "splunk-add-on-for-stream-forwarders_816.tgz",
                "splunk-add-on-for-stream-wire-data_816.tgz",
            ):
                (ta_cache / filename).write_text("placeholder", encoding="utf-8")

            registry_file.write_text('{"apps": []}', encoding="utf-8")
            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_SEARCH_API_URI="https://example.invalid:8089"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    """
                ),
                encoding="utf-8",
            )

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import sys

                args = " ".join(sys.argv[1:])
                if "/services/auth/login" in args and "-d @-" in args:
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                elif "/services/server/info" in args and "%{http_code}" in args:
                    sys.stdout.write("200")
                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "nc",
                """\
                #!/usr/bin/env bash
                exit 0
                """,
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
            env["TA_CACHE"] = str(ta_cache)
            env["REGISTRY_FILE"] = str(registry_file)

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/setup.sh",
                "--install",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1, msg=output)
            self.assertIn("requires a declared deployment role", output)

    def test_stream_setup_install_scopes_packages_to_declared_search_tier_role(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            ta_cache = tmp_path / "splunk-ta"
            ta_cache.mkdir()
            install_log = tmp_path / "install.log"
            credentials_file = tmp_path / "credentials"
            registry_file = tmp_path / "app_registry.json"
            app_install_script = tmp_path / "fake_install_app.sh"

            for filename in (
                "splunk-app-for-stream_816.tgz",
                "splunk-add-on-for-stream-forwarders_816.tgz",
                "splunk-add-on-for-stream-wire-data_816.tgz",
            ):
                (ta_cache / filename).write_text("placeholder", encoding="utf-8")

            registry_file.write_text(
                textwrap.dedent(
                    """\
                    {
                      "apps": [
                        {
                          "skill": "splunk-stream-setup",
                          "app_name": "splunk_app_stream",
                          "splunkbase_id": "1809",
                          "role_support": {
                            "search-tier": "required",
                            "indexer": "none",
                            "heavy-forwarder": "none",
                            "universal-forwarder": "none",
                            "external-collector": "none"
                          }
                        },
                        {
                          "skill": "splunk-stream-setup",
                          "app_name": "Splunk_TA_stream",
                          "splunkbase_id": "5238",
                          "role_support": {
                            "search-tier": "none",
                            "indexer": "none",
                            "heavy-forwarder": "required",
                            "universal-forwarder": "supported",
                            "external-collector": "none"
                          }
                        },
                        {
                          "skill": "splunk-stream-setup",
                          "app_name": "Splunk_TA_stream_wire_data",
                          "splunkbase_id": "5234",
                          "role_support": {
                            "search-tier": "supported",
                            "indexer": "required",
                            "heavy-forwarder": "supported",
                            "universal-forwarder": "none",
                            "external-collector": "none"
                          }
                        }
                      ]
                    }
                    """
                ),
                encoding="utf-8",
            )

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_SEARCH_API_URI="https://example.invalid:8089"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    SPLUNK_TARGET_ROLE="search-tier"
                    """
                ),
                encoding="utf-8",
            )

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import sys

                args = " ".join(sys.argv[1:])
                if "/services/auth/login" in args and "-d @-" in args:
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                elif "/services/server/info" in args and "%{http_code}" in args:
                    sys.stdout.write("200")
                elif "/services/apps/local/" in args and "%{http_code}" in args:
                    sys.stdout.write("404")
                elif "/services/auth/login" in args and "%{http_code}" in args:
                    sys.stdout.write("200")
                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "nc",
                """\
                #!/usr/bin/env bash
                exit 0
                """,
            )
            write_executable(
                app_install_script,
                """\
                #!/usr/bin/env bash
                set -euo pipefail
                printf '%s\\n' "$*" >> "${INSTALL_LOG}"
                exit 0
                """,
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
            env["TA_CACHE"] = str(ta_cache)
            env["REGISTRY_FILE"] = str(registry_file)
            env["APP_INSTALL_SCRIPT"] = str(app_install_script)
            env["INSTALL_LOG"] = str(install_log)

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/setup.sh",
                "--install",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Active deployment role: search-tier", result.stdout)

            install_lines = install_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                install_lines,
                [
                    "--source splunkbase --app-id 1809 --no-update --no-restart",
                    "--source splunkbase --app-id 5234 --no-update --no-restart",
                ],
            )

    def test_stream_setup_full_setup_requires_split_phases_on_role_scoped_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            credentials_file = tmp_path / "credentials"

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_SEARCH_API_URI="https://example.invalid:8089"
                    SPLUNK_TARGET_ROLE="search-tier"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/setup.sh",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1, msg=output)
            self.assertIn("Full Stream setup spans multiple runtime roles", output)
