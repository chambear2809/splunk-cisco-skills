#!/usr/bin/env python3
"""Regression tests for SC4S and SC4SNMP shell scripts."""

import getpass
import json
import stat
import tempfile
import textwrap
from pathlib import Path

from tests.regression_helpers import REPO_ROOT, ShellScriptRegressionBase, write_executable


class SC4xRegressionTests(ShellScriptRegressionBase):
    def test_sc4x_rest_create_requires_enabled_post_readback(self):
        """Deferred regression: a successful create response is not verification."""
        cases = (
            (
                "sc4s",
                self.build_mock_sc4s_env,
                "skills/splunk-connect-for-syslog-setup/scripts/setup.sh",
            ),
            (
                "sc4snmp",
                self.build_mock_sc4snmp_env,
                "skills/splunk-connect-for-snmp-setup/scripts/setup.sh",
            ),
        )
        for name, build_env, script in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                env, state_file = build_env(tmp_path)
                env["SC4X_FORCE_CREATED_HEC_DISABLED"] = "true"

                result = self.run_script(
                    script,
                    "--splunk-prep",
                    "--hec-only",
                    "--hec-url",
                    "https://example.invalid:8088",
                    env=env,
                )

                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, msg=output)
                self.assertIn("could not be verified as enabled", output)
                self.assertNotIn(f"Created HEC token '{name}'.", output)
                state = json.loads(state_file.read_text(encoding="utf-8"))
                self.assertEqual(state["hec_tokens"][name]["disabled"], "true")

    def test_sc4x_hec_observation_failure_cannot_trigger_mutation(self):
        """Deferred regression: exercise production entrypoints with a failing HEC read."""
        cases = (
            (
                "sc4s",
                self.build_mock_sc4s_env,
                "skills/splunk-connect-for-syslog-setup/scripts/setup.sh",
                "skills/splunk-connect-for-syslog-setup/scripts/validate.sh",
            ),
            (
                "sc4snmp",
                self.build_mock_sc4snmp_env,
                "skills/splunk-connect-for-snmp-setup/scripts/setup.sh",
                "skills/splunk-connect-for-snmp-setup/scripts/validate.sh",
            ),
        )
        for name, build_env, script, validator in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                env, _state_file = build_env(tmp_path)
                marker = tmp_path / "hec-mutation-reached"
                env["HEC_MUTATION_MARKER"] = str(marker)
                bin_dir = Path(env["PATH"].split(":", 1)[0])
                write_executable(
                    bin_dir / "curl",
                    """\
                    #!/usr/bin/env python3
                    import os
                    import sys
                    from pathlib import Path
                    from urllib.parse import urlparse

                    args = sys.argv[1:]
                    method = "GET"
                    url = ""
                    i = 0
                    while i < len(args):
                        if args[i] == "-X" and i + 1 < len(args):
                            method = args[i + 1]
                            i += 2
                            continue
                        if args[i] == "-d" and i + 1 < len(args):
                            if method == "GET":
                                method = "POST"
                            i += 2
                            continue
                        if args[i].startswith(("http://", "https://")):
                            url = args[i]
                        i += 1

                    path = urlparse(url).path
                    if path.endswith("/services/auth/login"):
                        sys.stdout.write(
                            "<response><sessionKey>test-session</sessionKey></response>"
                        )
                        raise SystemExit(0)
                    if "/services/data/inputs/http" in path:
                        if method != "GET":
                            Path(os.environ["HEC_MUTATION_MARKER"]).touch()
                            raise SystemExit(0)
                        raise SystemExit(1)
                    raise SystemExit(0)
                    """,
                )

                result = self.run_script(
                    script,
                    "--splunk-prep",
                    "--hec-only",
                    "--hec-url",
                    "https://example.invalid:8088",
                    env=env,
                )

                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, msg=output)
                self.assertIn("Could not inspect HEC token", output)
                self.assertFalse(marker.exists(), msg="HEC mutation followed a failed read")

                validation = self.run_script(validator, env=env)
                validation_output = validation.stdout + validation.stderr
                self.assertNotEqual(validation.returncode, 0, msg=validation_output)
                self.assertIn("Could not inspect HEC token", validation_output)

    def test_sc4x_cloud_acs_list_failure_cannot_trigger_hec_mutation(self):
        """Deferred regression: a failed ACS inventory is not token absence."""
        cases = (
            (
                "sc4s",
                self.build_mock_sc4s_env,
                "skills/splunk-connect-for-syslog-setup/scripts/setup.sh",
            ),
            (
                "sc4snmp",
                self.build_mock_sc4snmp_env,
                "skills/splunk-connect-for-snmp-setup/scripts/setup.sh",
            ),
        )
        for name, build_env, script in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                env, _state_file = build_env(tmp_path)
                bin_dir = Path(env["PATH"].split(":", 1)[0])
                credentials_file = Path(env["SPLUNK_CREDENTIALS_FILE"])
                mutation_marker = tmp_path / "acs-hec-mutation-reached"
                legacy_marker = tmp_path / "acs-legacy-fallback-reached"
                credentials_file.write_text(
                    textwrap.dedent(
                        """\
                        SPLUNK_PLATFORM="cloud"
                        SPLUNK_CLOUD_STACK="example-stack"
                        SPLUNK_SEARCH_API_URI="https://example.invalid:8089"
                        SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
                        SPLUNK_USER="user"
                        SPLUNK_PASS="pass"
                        """
                    ),
                    encoding="utf-8",
                )
                write_executable(
                    bin_dir / "acs",
                    """\
                    #!/usr/bin/env python3
                    import os
                    import sys
                    from pathlib import Path

                    args = sys.argv[1:]
                    command = " ".join(args)
                    if "config current-stack" in command:
                        print("Stack: example-stack")
                        raise SystemExit(0)
                    if "hec-token list" in command and "--help" in args:
                        raise SystemExit(0)
                    if "hec-token list" in command:
                        raise SystemExit(1)
                    if "http-event-collectors" in command:
                        Path(os.environ["ACS_LEGACY_MARKER"]).touch()
                        print('[{"type":"http","status":404}]')
                        raise SystemExit(1)
                    if "hec-token create" in command or "hec-token update" in command:
                        Path(os.environ["ACS_HEC_MUTATION_MARKER"]).touch()
                    if "http-event-collectors create" in command:
                        Path(os.environ["ACS_HEC_MUTATION_MARKER"]).touch()
                    raise SystemExit(0)
                    """,
                )
                env["SPLUNK_PLATFORM"] = "cloud"
                env["ACS_HEC_MUTATION_MARKER"] = str(mutation_marker)
                env["ACS_LEGACY_MARKER"] = str(legacy_marker)

                result = self.run_script(
                    script,
                    "--splunk-prep",
                    "--hec-only",
                    "--hec-url",
                    "https://example.invalid:8088",
                    env=env,
                )

                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, msg=output)
                self.assertIn("Could not inspect HEC token", output)
                self.assertIn("refusing mutation", output)
                self.assertFalse(
                    mutation_marker.exists(),
                    msg="ACS mutation followed a failed token inventory",
                )
                self.assertFalse(
                    legacy_marker.exists(),
                    msg="Modern ACS transport failure incorrectly triggered legacy fallback",
                )

    def test_sc4x_cloud_hec_searches_all_pages_before_create(self):
        """Deferred regression: an existing page-two token is never recreated."""
        cases = (
            (
                "sc4s",
                self.build_mock_sc4s_env,
                "skills/splunk-connect-for-syslog-setup/scripts/setup.sh",
            ),
            (
                "sc4snmp",
                self.build_mock_sc4snmp_env,
                "skills/splunk-connect-for-snmp-setup/scripts/setup.sh",
            ),
        )
        for name, build_env, script in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                env, _state_file = build_env(tmp_path)
                bin_dir = Path(env["PATH"].split(":", 1)[0])
                credentials_file = Path(env["SPLUNK_CREDENTIALS_FILE"])
                page_two_marker = tmp_path / "acs-hec-page-two-reached"
                create_marker = tmp_path / "acs-hec-create-reached"
                credentials_file.write_text(
                    textwrap.dedent(
                        """\
                        SPLUNK_PLATFORM="cloud"
                        SPLUNK_CLOUD_STACK="example-stack"
                        SPLUNK_SEARCH_API_URI="https://example.invalid:8089"
                        SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
                        SPLUNK_USER="user"
                        SPLUNK_PASS="pass"
                        """
                    ),
                    encoding="utf-8",
                )
                write_executable(
                    bin_dir / "acs",
                    """\
                    #!/usr/bin/env python3
                    import json
                    import os
                    import sys
                    from pathlib import Path

                    args = sys.argv[1:]
                    command = " ".join(args)
                    if "config current-stack" in command:
                        print("Stack: example-stack")
                        raise SystemExit(0)
                    if "hec-token list" in command:
                        if "--help" in args:
                            raise SystemExit(0)
                        if "--count" in args and args[args.index("--count") + 1] == "1":
                            print(json.dumps({"tokens": [{"name": "probe", "disabled": False}]}))
                            raise SystemExit(0)
                        offset = int(args[args.index("--offset") + 1])
                        if offset == 0:
                            tokens = [
                                {"name": f"decoy-{number}", "disabled": False}
                                for number in range(100)
                            ]
                        elif offset == 100:
                            Path(os.environ["ACS_PAGE_TWO_MARKER"]).touch()
                            tokens = [
                                {
                                    "name": os.environ["CLOUD_HEC_TOKEN_NAME"],
                                    "disabled": False,
                                }
                            ]
                        else:
                            tokens = []
                        print(json.dumps({"tokens": tokens}))
                        raise SystemExit(0)
                    if "hec-token create" in command or "http-event-collectors create" in command:
                        Path(os.environ["ACS_HEC_CREATE_MARKER"]).touch()
                    if "http-event-collectors" in command:
                        raise SystemExit(1)
                    raise SystemExit(0)
                    """,
                )
                env["SPLUNK_PLATFORM"] = "cloud"
                env["CLOUD_HEC_TOKEN_NAME"] = name
                env["ACS_PAGE_TWO_MARKER"] = str(page_two_marker)
                env["ACS_HEC_CREATE_MARKER"] = str(create_marker)

                result = self.run_script(
                    script,
                    "--splunk-prep",
                    "--hec-only",
                    "--hec-url",
                    "https://example.invalid:8088",
                    env=env,
                )

                output = result.stdout + result.stderr
                self.assertTrue(page_two_marker.exists(), msg=output)
                self.assertFalse(create_marker.exists(), msg="Page-two token was duplicated")
                self.assertNotIn(f"Creating HEC token '{name}'", output)

    def test_sc4x_cloud_record_failure_stops_before_acs_update(self):
        """Deferred regression: a failed REST record cannot authorize ACS update."""
        cases = (
            (
                "sc4s",
                self.build_mock_sc4s_env,
                "skills/splunk-connect-for-syslog-setup/scripts/setup.sh",
            ),
            (
                "sc4snmp",
                self.build_mock_sc4snmp_env,
                "skills/splunk-connect-for-snmp-setup/scripts/setup.sh",
            ),
        )
        for name, build_env, script in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                env, _state_file = build_env(tmp_path)
                bin_dir = Path(env["PATH"].split(":", 1)[0])
                credentials_file = Path(env["SPLUNK_CREDENTIALS_FILE"])
                mutation_marker = tmp_path / "acs-hec-update-reached"
                credentials_file.write_text(
                    textwrap.dedent(
                        """\
                        SPLUNK_PLATFORM="cloud"
                        SPLUNK_CLOUD_STACK="example-stack"
                        SPLUNK_SEARCH_API_URI="https://example.invalid:8089"
                        SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
                        SPLUNK_USER="user"
                        SPLUNK_PASS="pass"
                        """
                    ),
                    encoding="utf-8",
                )
                write_executable(
                    bin_dir / "acs",
                    """\
                    #!/usr/bin/env python3
                    import json
                    import os
                    import sys
                    from pathlib import Path

                    command = " ".join(sys.argv[1:])
                    if "config current-stack" in command:
                        print("Stack: example-stack")
                        raise SystemExit(0)
                    if "hec-token list" in command:
                        token_name = os.environ["CLOUD_HEC_TOKEN_NAME"]
                        print(json.dumps({"tokens": [{"name": token_name, "disabled": False}]}))
                        raise SystemExit(0)
                    if "hec-token create" in command or "hec-token update" in command:
                        Path(os.environ["ACS_HEC_MUTATION_MARKER"]).touch()
                    if "http-event-collectors" in command:
                        raise SystemExit(1)
                    raise SystemExit(0)
                    """,
                )
                write_executable(
                    bin_dir / "curl",
                    """\
                    #!/usr/bin/env python3
                    import sys
                    from urllib.parse import urlparse

                    url = next(
                        (arg for arg in sys.argv[1:] if arg.startswith(("http://", "https://"))),
                        "",
                    )
                    path = urlparse(url).path
                    if path.endswith("/services/auth/login"):
                        print("<response><sessionKey>test-session</sessionKey></response>", end="")
                        raise SystemExit(0)
                    if path.endswith("/services/data/inputs/http"):
                        print("{}")
                        print("200", end="")
                        raise SystemExit(0)
                    raise SystemExit(0)
                    """,
                )
                env["SPLUNK_PLATFORM"] = "cloud"
                env["CLOUD_HEC_TOKEN_NAME"] = name
                env["ACS_HEC_MUTATION_MARKER"] = str(mutation_marker)

                result = self.run_script(
                    script,
                    "--splunk-prep",
                    "--hec-only",
                    "--hec-url",
                    "https://example.invalid:8088",
                    env=env,
                )

                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, msg=output)
                self.assertIn("Could not inspect the default index", output)
                self.assertIn("refusing mutation", output)
                self.assertFalse(
                    mutation_marker.exists(),
                    msg="ACS update followed a failed REST record observation",
                )

    def test_sc4s_setup_smoke_flow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, state_file = self.build_mock_sc4s_env(tmp_path)
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "sc4s.token"
            context_file = tmp_path / "splunk_metadata.csv"
            config_file = tmp_path / "app-workaround.conf"

            context_file.write_text("cisco_asa,index,netfw\n", encoding="utf-8")
            config_file.write_text(
                textwrap.dedent(
                    """\
                    application app-postfilter-cisco_asa_metadata[sc4s-postfilter] {
                      parser { app-postfilter-cisco_asa_metadata(); };
                    };
                    """
                ),
                encoding="utf-8",
            )

            setup_result = self.run_script(
                "skills/splunk-connect-for-syslog-setup/scripts/setup.sh",
                "--splunk-prep",
                "--include-metrics-index",
                "--write-hec-token-file",
                str(token_file),
                "--render-host",
                "--render-k8s",
                "--output-dir",
                str(output_dir),
                "--vendor-port",
                "checkpoint:tcp:9000",
                "--context-file",
                f"splunk_metadata.csv={context_file}",
                "--config-file",
                f"app-workaround.conf={config_file}",
                env=env,
                timeout=300,
            )
            self.assertEqual(setup_result.returncode, 0, msg=setup_result.stdout + setup_result.stderr)
            self.assertTrue(token_file.exists(), msg="Expected the SC4S token file to be written")
            self.assertEqual(token_file.read_text(encoding="utf-8"), "generated-sc4s-token\n")

            host_env = (output_dir / "host" / "env_file").read_text(encoding="utf-8")
            host_compose = (output_dir / "host" / "docker-compose.yml").read_text(encoding="utf-8")
            k8s_values = (output_dir / "k8s" / "values.yaml").read_text(encoding="utf-8")
            k8s_secret = (output_dir / "k8s" / "values.secret.yaml").read_text(encoding="utf-8")

            self.assertIn("SC4S_DEST_SPLUNK_HEC_DEFAULT_URL=https://example.invalid:8088", host_env)
            self.assertIn("SC4S_DEST_SPLUNK_HEC_DEFAULT_TOKEN=generated-sc4s-token", host_env)
            self.assertIn("SC4S_LISTEN_CHECKPOINT_TCP_PORT=9000", host_env)
            self.assertIn("- ./env_file", host_compose)
            self.assertIn("- ./local:/etc/syslog-ng/conf.d/local:z", host_compose)
            rendered_context = (output_dir / "host" / "local" / "context" / "splunk_metadata.csv").read_text(encoding="utf-8")
            self.assertIn("splunk_sc4s_events,index,sc4s", rendered_context)
            self.assertIn("splunk_sc4s_fallback,index,sc4s", rendered_context)
            self.assertIn("cisco_asa,index,netfw", rendered_context)

            self.assertIn('hec_url: "https://example.invalid:8088/services/collector/event"', k8s_values)
            self.assertIn("vendor_product:", k8s_values)
            self.assertIn("name: checkpoint", k8s_values)
            self.assertIn("tcp: [9000]", k8s_values)
            self.assertIn("context_files:", k8s_values)
            self.assertIn("splunk_metadata.csv: |-", k8s_values)
            self.assertIn("splunk_sc4s_events,index,sc4s", k8s_values)
            self.assertIn("splunk_sc4s_fallback,index,sc4s", k8s_values)
            self.assertIn("cisco_asa,index,netfw", k8s_values)
            self.assertIn("config_files:", k8s_values)
            self.assertIn("app-workaround.conf: |-", k8s_values)
            self.assertIn('hec_token: "generated-sc4s-token"', k8s_secret)

            self.assertTrue((output_dir / "host" / "docker-compose.yml").exists())
            self.assertTrue((output_dir / "host" / "compose-up.sh").exists())
            self.assertTrue((output_dir / "k8s" / "helm-install.sh").exists())

            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertIn("sc4s", state["indexes"])
            self.assertIn("netfw", state["indexes"])
            self.assertIn("_metrics", state["indexes"])
            self.assertEqual(state["indexes"]["_metrics"]["datatype"], "metric")
            self.assertIn("sc4s", state["hec_tokens"])
            self.assertEqual(state["hec_tokens"]["sc4s"]["default_index"], "sc4s")

            validate_result = self.run_script(
                "skills/splunk-connect-for-syslog-setup/scripts/validate.sh",
                "--hec-token-name",
                "sc4s",
                env=env,
                timeout=300,
            )
            self.assertEqual(validate_result.returncode, 0, msg=validate_result.stdout + validate_result.stderr)
            self.assertIn("HEC token 'sc4s' exists", validate_result.stdout)
            self.assertIn("SC4S startup event", validate_result.stdout)


    def test_sc4s_setup_uses_ingest_profile_for_hec_management_and_rendering(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _state_file = self.build_mock_sc4s_env(tmp_path)
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "sc4s.token"
            curl_log = tmp_path / "curl.log"

            Path(env["SPLUNK_CREDENTIALS_FILE"]).write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_PLATFORM="enterprise"
                    SPLUNK_TARGET_ROLE="search-tier"
                    SPLUNK_SEARCH_API_URI="https://search.example.invalid:8089"
                    SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    SPLUNK_INGEST_PROFILE="hf"
                    PROFILE_hf__SPLUNK_PLATFORM="enterprise"
                    PROFILE_hf__SPLUNK_TARGET_ROLE="heavy-forwarder"
                    PROFILE_hf__SPLUNK_SEARCH_API_URI="https://hf.example.invalid:8089"
                    PROFILE_hf__SPLUNK_URI="${PROFILE_hf__SPLUNK_SEARCH_API_URI}"
                    PROFILE_hf__SPLUNK_USER="user"
                    PROFILE_hf__SPLUNK_PASS="pass"
                    PROFILE_hf__SPLUNK_HEC_URL="https://hf-hec.example.invalid:8088/services/collector/event"
                    """
                ),
                encoding="utf-8",
            )
            env["CURL_LOG"] = str(curl_log)

            result = self.run_script(
                "skills/splunk-connect-for-syslog-setup/scripts/setup.sh",
                "--splunk-prep",
                "--write-hec-token-file",
                str(token_file),
                "--render-host",
                "--output-dir",
                str(output_dir),
                env=env,
                timeout=900,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("Detected SC4S HEC base URL: https://hf-hec.example.invalid:8088", output)
            self.assertIn(
                "SC4S_DEST_SPLUNK_HEC_DEFAULT_URL=https://hf-hec.example.invalid:8088",
                (output_dir / "host" / "env_file").read_text(encoding="utf-8"),
            )
            curl_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn(
                "https://hf.example.invalid:8089/services/data/inputs/http?output_mode=json",
                curl_requests,
            )
            self.assertNotIn(
                "https://search.example.invalid:8089/services/data/inputs/http?output_mode=json",
                curl_requests,
            )

            curl_log.write_text("", encoding="utf-8")
            validate_result = self.run_script(
                "skills/splunk-connect-for-syslog-setup/scripts/validate.sh",
                "--hec-token-name",
                "sc4s",
                env=env,
                timeout=300,
            )
            self.assertEqual(validate_result.returncode, 0, msg=validate_result.stdout + validate_result.stderr)
            validate_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn(
                "https://hf.example.invalid:8089/services/data/inputs/http?output_mode=json",
                validate_requests,
            )
            self.assertNotIn(
                "https://search.example.invalid:8089/services/data/inputs/http?output_mode=json",
                validate_requests,
            )


    def test_sc4s_clustered_ingest_uses_bundle_managed_hec(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _state_file = self.build_mock_sc4s_env(tmp_path)
            token_file = tmp_path / "sc4s.token"
            curl_log = tmp_path / "curl.log"
            apply_log = tmp_path / "bundle-apply.log"
            splunk_home = tmp_path / "cluster-manager"
            (splunk_home / "bin").mkdir(parents=True)

            write_executable(
                splunk_home / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                printf '%s\\n' "$*" >> "${BUNDLE_APPLY_LOG}"
                exit 0
                """,
            )

            Path(env["SPLUNK_CREDENTIALS_FILE"]).write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_PLATFORM="enterprise"
                    SPLUNK_TARGET_ROLE="search-tier"
                    SPLUNK_SEARCH_API_URI="https://search.example.invalid:8089"
                    SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    SPLUNK_INGEST_PROFILE="idx"
                    SPLUNK_CLUSTER_MANAGER_PROFILE="cm"
                    PROFILE_idx__SPLUNK_PLATFORM="enterprise"
                    PROFILE_idx__SPLUNK_TARGET_ROLE="indexer"
                    PROFILE_idx__SPLUNK_SEARCH_API_URI="https://indexer.example.invalid:8089"
                    PROFILE_idx__SPLUNK_URI="${PROFILE_idx__SPLUNK_SEARCH_API_URI}"
                    PROFILE_idx__SPLUNK_USER="user"
                    PROFILE_idx__SPLUNK_PASS="pass"
                    PROFILE_idx__SPLUNK_HEC_URL="https://idx-hec.example.invalid:8088/services/collector/event"
                    PROFILE_cm__SPLUNK_PLATFORM="enterprise"
                    PROFILE_cm__SPLUNK_SEARCH_API_URI="https://localhost:8089"
                    PROFILE_cm__SPLUNK_URI="${PROFILE_cm__SPLUNK_SEARCH_API_URI}"
                    PROFILE_cm__SPLUNK_USER="cm-user"
                    PROFILE_cm__SPLUNK_PASS="cm-pass"
                    """
                ),
                encoding="utf-8",
            )

            env["CURL_LOG"] = str(curl_log)
            env["SPLUNK_HOME"] = str(splunk_home)
            env["SPLUNK_LOCAL_SUDO"] = "false"
            env["SPLUNK_BUNDLE_OS_USER"] = getpass.getuser()
            env["BUNDLE_APPLY_LOG"] = str(apply_log)

            result = self.run_script(
                "skills/splunk-connect-for-syslog-setup/scripts/setup.sh",
                "--splunk-prep",
                "--hec-only",
                "--write-hec-token-file",
                str(token_file),
                env=env,
                timeout=300,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("Created HEC token 'sc4s' via cluster-manager bundle.", output)
            token_value = token_file.read_text(encoding="utf-8").strip()
            self.assertRegex(token_value, r"^[0-9a-f-]{36}$")

            inputs_conf = (
                splunk_home
                / "etc"
                / "manager-apps"
                / "ZZZ_cisco_skills_hec"
                / "local"
                / "inputs.conf"
            ).read_text(encoding="utf-8")
            self.assertIn("[http]", inputs_conf)
            self.assertIn("[http://sc4s]", inputs_conf)
            self.assertIn("index = sc4s", inputs_conf)
            self.assertIn(f"token = {token_value}", inputs_conf)
            self.assertIn("disabled = 0", inputs_conf)
            apply_text = apply_log.read_text(encoding="utf-8")
            self.assertIn("apply cluster-bundle", apply_text)
            self.assertNotIn("-auth", apply_text)
            self.assertNotIn("cm-pass", apply_text)
            if curl_log.exists():
                self.assertNotIn("/services/data/inputs/http", curl_log.read_text(encoding="utf-8"))

            # This case intentionally ran HEC-only preparation.  Model the
            # indexes as an independently completed prerequisite so the
            # completion validator can retain its strict required-index
            # readback while this test remains focused on bundle-managed HEC.
            state_path = Path(env["SC4S_STATE"])
            state = json.loads(state_path.read_text(encoding="utf-8"))
            for index_name in (
                "sc4s", "print", "osnix", "oswinsec", "oswin", "netipam",
                "netproxy", "netwaf", "netops", "netlb", "netids", "netfw",
                "netdns", "netdlp", "netauth", "infraops", "gitops",
                "fireeye", "epintel", "epav", "email",
            ):
                state["indexes"][index_name] = {"datatype": "event"}
            state_path.write_text(json.dumps(state), encoding="utf-8")

            curl_log.write_text("", encoding="utf-8")
            validate_result = self.run_script(
                "skills/splunk-connect-for-syslog-setup/scripts/validate.sh",
                "--hec-token-name",
                "sc4s",
                env=env,
                timeout=300,
            )
            self.assertEqual(validate_result.returncode, 0, msg=validate_result.stdout + validate_result.stderr)
            self.assertIn("HEC token 'sc4s' exists", validate_result.stdout)
            self.assertNotIn("/services/data/inputs/http", curl_log.read_text(encoding="utf-8"))


    def test_sc4s_validate_reports_wrong_metrics_index_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, state_file = self.build_mock_sc4s_env(tmp_path)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["indexes"]["_metrics"] = {"datatype": "event"}
            state["hec_tokens"]["sc4s"] = {
                "disabled": "false",
                "useACK": "0",
                "indexes": "",
                "index": "sc4s",
                "default_index": "sc4s",
                "token": "generated-sc4s-token",
            }
            state_file.write_text(json.dumps(state), encoding="utf-8")

            validate_result = self.run_script(
                "skills/splunk-connect-for-syslog-setup/scripts/validate.sh",
                "--hec-token-name",
                "sc4s",
                env=env,
            )
            self.assertEqual(validate_result.returncode, 1, msg=validate_result.stdout + validate_result.stderr)
            self.assertIn("exists but is an event index", validate_result.stdout)


    def test_sc4s_setup_enables_existing_disabled_hec_token(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, state_file = self.build_mock_sc4s_env(tmp_path)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["hec_tokens"]["sc4s"] = {
                "disabled": "true",
                "useACK": "0",
                "indexes": "",
                "index": "main",
                "default_index": "main",
                "token": "generated-sc4s-token",
            }
            state_file.write_text(json.dumps(state), encoding="utf-8")

            setup_result = self.run_script(
                "skills/splunk-connect-for-syslog-setup/scripts/setup.sh",
                "--splunk-prep",
                "--hec-only",
                env=env,
            )
            self.assertEqual(setup_result.returncode, 0, msg=setup_result.stdout + setup_result.stderr)
            self.assertIn("exists but is disabled. Enabling it via Splunk REST", setup_result.stdout)
            self.assertIn("Enabled HEC token 'sc4s'.", setup_result.stdout)
            self.assertIn("Updating it to 'sc4s' via Splunk REST", setup_result.stdout)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["hec_tokens"]["sc4s"]["disabled"], "false")
            self.assertEqual(state["hec_tokens"]["sc4s"]["default_index"], "sc4s")


    def test_sc4s_validate_fails_when_default_index_is_main(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, state_file = self.build_mock_sc4s_env(tmp_path)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["indexes"]["sc4s"] = {"datatype": "event"}
            state["hec_tokens"]["sc4s"] = {
                "disabled": "false",
                "useACK": "0",
                "indexes": "",
                "index": "main",
                "default_index": "main",
                "token": "generated-sc4s-token",
            }
            state_file.write_text(json.dumps(state), encoding="utf-8")

            validate_result = self.run_script(
                "skills/splunk-connect-for-syslog-setup/scripts/validate.sh",
                "--hec-token-name",
                "sc4s",
                env=env,
            )
            self.assertEqual(validate_result.returncode, 1, msg=validate_result.stdout + validate_result.stderr)
            self.assertIn("default index is 'main', expected 'sc4s'", validate_result.stdout)


    def test_sc4s_setup_blocks_custom_in_repo_secret_output_dir(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmpdir:
            tmp_path = Path(tmpdir)
            harness_path = tmp_path / "harness"
            harness_path.mkdir()
            env, state_file = self.build_mock_sc4s_env(harness_path)
            token_file = tmp_path / "sc4s.token"
            token_file.write_text("existing-token\n", encoding="utf-8")
            token_file.chmod(0o600)

            output_dir = tmp_path / "dangerous-render"
            result = self.run_script(
                "skills/splunk-connect-for-syslog-setup/scripts/setup.sh",
                "--render-host",
                "--output-dir",
                str(output_dir),
                "--hec-token-file",
                str(token_file),
                env=env,
            )
            self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
            self.assertIn("Refusing to render secret-bearing SC4S outputs inside the repo", result.stdout + result.stderr)


    def test_gitignore_excludes_default_sc4s_render_output(self):
        gitignore_text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/sc4s-rendered/", gitignore_text)


    def test_sc4s_apply_host_compose_pulls_before_up(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _state_file = self.build_mock_sc4s_env(tmp_path)
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "sc4s.token"
            token_file.write_text("existing-token\n", encoding="utf-8")
            token_file.chmod(0o600)

            result = self.run_script(
                "skills/splunk-connect-for-syslog-setup/scripts/setup.sh",
                "--render-host",
                "--output-dir",
                str(output_dir),
                "--hec-token-file",
                str(token_file),
                "--apply-host",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            helper_text = (output_dir / "host" / "compose-up.sh").read_text(encoding="utf-8")
            self.assertIn("compose -f docker-compose.yml pull", helper_text)

            commands = Path(env["SC4S_COMMAND_LOG"]).read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                commands[:2],
                [
                    "docker compose -f docker-compose.yml pull",
                    "docker compose -f docker-compose.yml up -d",
                ],
            )


    def test_sc4s_apply_host_systemd_syncs_runtime_and_restarts_service(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _state_file = self.build_mock_sc4s_env(tmp_path)
            output_dir = tmp_path / "rendered"
            runtime_root = tmp_path / "sc4s-runtime"
            token_file = tmp_path / "sc4s.token"
            context_file = tmp_path / "splunk_metadata.csv"
            config_file = tmp_path / "app-workaround.conf"

            token_file.write_text("existing-token\n", encoding="utf-8")
            token_file.chmod(0o600)
            context_file.write_text("cisco_asa,index,netfw\n", encoding="utf-8")
            config_file.write_text("filter f_local { level(info); };\n", encoding="utf-8")

            (runtime_root / "tls").mkdir(parents=True)
            preserved_file = runtime_root / "tls" / "existing.pem"
            preserved_file.write_text("keep-me\n", encoding="utf-8")

            result = self.run_script(
                "skills/splunk-connect-for-syslog-setup/scripts/setup.sh",
                "--render-host",
                "--host-mode",
                "systemd",
                "--output-dir",
                str(output_dir),
                "--sc4s-root",
                str(runtime_root),
                "--hec-token-file",
                str(token_file),
                "--context-file",
                f"splunk_metadata.csv={context_file}",
                "--config-file",
                f"app-workaround.conf={config_file}",
                "--apply-host",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            runtime_env = (runtime_root / "env_file").read_text(encoding="utf-8")
            copied_context = (runtime_root / "local" / "context" / "splunk_metadata.csv").read_text(encoding="utf-8")
            copied_config = (runtime_root / "local" / "config" / "app-workaround.conf").read_text(encoding="utf-8")
            unit_file = Path(env["SC4S_SYSTEMD_UNIT_DIR"]) / "sc4s.service"

            self.assertIn("SC4S_DEST_SPLUNK_HEC_DEFAULT_TOKEN=existing-token", runtime_env)
            self.assertIn("cisco_asa,index,netfw", copied_context)
            self.assertIn("splunk_sc4s_events,index,sc4s", copied_context)
            self.assertIn("splunk_sc4s_fallback,index,sc4s", copied_context)
            self.assertEqual(copied_config, "filter f_local { level(info); };\n")
            self.assertTrue((runtime_root / "archive").exists())
            self.assertTrue((runtime_root / "tls").exists())
            self.assertEqual(preserved_file.read_text(encoding="utf-8"), "keep-me\n")
            self.assertTrue(unit_file.exists())

            commands = Path(env["SC4S_COMMAND_LOG"]).read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                commands,
                [
                    "systemctl daemon-reload",
                    "systemctl enable sc4s",
                    "systemctl restart sc4s",
                ],
            )


    def test_sc4s_apply_k8s_runs_helm_upgrade_install(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _state_file = self.build_mock_sc4s_env(tmp_path)
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "sc4s.token"
            token_file.write_text("existing-token\n", encoding="utf-8")
            token_file.chmod(0o600)

            result = self.run_script(
                "skills/splunk-connect-for-syslog-setup/scripts/setup.sh",
                "--render-k8s",
                "--output-dir",
                str(output_dir),
                "--hec-token-file",
                str(token_file),
                "--apply-k8s",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            commands = Path(env["SC4S_COMMAND_LOG"]).read_text(encoding="utf-8").splitlines()
            self.assertEqual(commands[:2], ["helm repo add splunk-connect-for-syslog https://splunk.github.io/splunk-connect-for-syslog", "helm repo update"])
            self.assertTrue(
                any(
                    "helm upgrade --install sc4s splunk-connect-for-syslog/splunk-connect-for-syslog --namespace sc4s --create-namespace -f values.yaml"
                    in line
                    for line in commands
                ),
                msg=f"Expected helm upgrade --install in command log, got: {commands}",
            )


    def test_sc4snmp_setup_smoke_flow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, state_file = self.build_mock_sc4snmp_env(tmp_path)
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "sc4snmp.token"
            inventory_file = tmp_path / "inventory.csv"
            scheduler_file = tmp_path / "scheduler-config.yaml"
            traps_file = tmp_path / "traps-config.yaml"

            inventory_file.write_text(
                "address,port,version,community,secret,security_engine,walk_interval,profiles,smart_profiles,delete\n"
                "192.0.2.10,161,2c,public,,,300,if_mib,,false\n",
                encoding="utf-8",
            )
            scheduler_file.write_text(
                textwrap.dedent(
                    """\
                    groups:
                      campus_switches:
                        - address: 192.0.2.10
                          port: 161
                    profiles:
                      if_mib:
                        frequency: 300
                        varBinds:
                          - ['IF-MIB', 'ifDescr']
                    """
                ),
                encoding="utf-8",
            )
            traps_file.write_text(
                textwrap.dedent(
                    """\
                    communities:
                      2c:
                        - public
                    """
                ),
                encoding="utf-8",
            )

            setup_result = self.run_script(
                "skills/splunk-connect-for-snmp-setup/scripts/setup.sh",
                "--splunk-prep",
                "--write-hec-token-file",
                str(token_file),
                "--render-compose",
                "--render-k8s",
                "--output-dir",
                str(output_dir),
                "--dns-server",
                "10.10.10.53",
                "--trap-listener-ip",
                "10.10.10.50",
                "--inventory-file",
                str(inventory_file),
                "--scheduler-file",
                str(scheduler_file),
                "--traps-file",
                str(traps_file),
                env=env,
            )
            self.assertEqual(setup_result.returncode, 0, msg=setup_result.stdout + setup_result.stderr)
            self.assertTrue(token_file.exists(), msg="Expected the SC4SNMP token file to be written")
            self.assertEqual(token_file.read_text(encoding="utf-8"), "generated-sc4snmp-token\n")

            compose_env = (output_dir / "compose" / ".env").read_text(encoding="utf-8")
            compose_file = (output_dir / "compose" / "docker-compose.yml").read_text(encoding="utf-8")
            compose_inventory = (output_dir / "compose" / "config" / "inventory.csv").read_text(encoding="utf-8")
            compose_hec_token = (output_dir / "compose" / "secrets" / "hec_token").read_text(encoding="utf-8")
            k8s_values = (output_dir / "k8s" / "values.yaml").read_text(encoding="utf-8")
            k8s_secret = (output_dir / "k8s" / "values.secret.yaml").read_text(encoding="utf-8")

            self.assertIn("SPLUNK_HEC_HOST=example.invalid", compose_env)
            self.assertIn("SPLUNK_HEC_PORT=8088", compose_env)
            self.assertIn("SPLUNK_HEC_SCHEME=https", compose_env)
            self.assertIn("SPLUNK_HEC_TOKEN_FILE=/app/secrets/tmp/hec_token", compose_env)
            self.assertIn("REDIS_IMAGE=docker.io/redis", compose_env)
            self.assertIn("REDIS_TAG=8.2.2", compose_env)
            self.assertIn("MONGO_IMAGE=docker.io/bitnamilegacy/mongodb", compose_env)
            self.assertIn("MONGO_TAG=7.0.14-debian-12-r3", compose_env)
            self.assertIn("MIBSERVER_IMAGE=ghcr.io/pysnmp/mibs/container", compose_env)
            self.assertIn("MIBSERVER_TAG=latest", compose_env)
            self.assertIn("CONFIG_PATH=/app/config/config.yaml", compose_env)
            self.assertIn("REDIS_URL=redis://redis:6379/1", compose_env)
            self.assertIn("CELERY_BROKER_URL=redis://redis:6379/0", compose_env)
            self.assertIn("MONGO_URI=mongodb://mongo:27017/", compose_env)
            self.assertIn("MIB_SOURCES=http://snmp-mibserver:8000/asn1/@mib@", compose_env)
            self.assertIn("MIB_INDEX=http://snmp-mibserver:8000/index.csv", compose_env)
            self.assertIn("MIB_STANDARD=http://snmp-mibserver:8000/standard.txt", compose_env)
            self.assertIn("TRAPS_PORT=162", compose_env)
            self.assertIn("DNS_SERVER=10.10.10.53", compose_env)
            self.assertIn("INVENTORY_FILE_ABSOLUTE_PATH=/app/inventory/inventory.csv", compose_env)
            self.assertIn("SCHEDULER_CONFIG_FILE_ABSOLUTE_PATH=/app/config/config.yaml", compose_env)
            self.assertIn("TRAPS_CONFIG_FILE_ABSOLUTE_PATH=/app/config/config.yaml", compose_env)
            self.assertIn("SECRET_FOLDER_PATH=/app/secrets/tmp", compose_env)
            self.assertIn("LOCAL_MIBS_PATH=/app/new_mibs/src/vendor", compose_env)
            self.assertIn("image: ${REDIS_IMAGE}:${REDIS_TAG}", compose_file)
            self.assertIn("image: ${MONGO_IMAGE}:${MONGO_TAG}", compose_file)
            self.assertIn("image: ${MIBSERVER_IMAGE}:${MIBSERVER_TAG}", compose_file)
            self.assertIn("container_name: SC4SNMP-inventory", compose_file)
            self.assertIn("command: [inventory]", compose_file)
            self.assertIn("container_name: SC4SNMP-scheduler", compose_file)
            self.assertIn("command: [celery, beat]", compose_file)
            self.assertIn("container_name: SC4SNMP-worker-poller", compose_file)
            self.assertIn("command: [celery, worker-poller]", compose_file)
            self.assertIn("container_name: SC4SNMP-worker-sender", compose_file)
            self.assertIn("command: [celery, worker-sender]", compose_file)
            self.assertIn("container_name: SC4SNMP-worker-trap", compose_file)
            self.assertIn("command: [celery, worker-trap]", compose_file)
            self.assertIn("container_name: SC4SNMP-trap", compose_file)
            self.assertIn("command: [trap]", compose_file)
            self.assertIn("./config/inventory.csv:/app/inventory/inventory.csv:ro", compose_file)
            self.assertIn("./config/scheduler-config.yaml:/app/config/config.yaml:ro", compose_file)
            self.assertIn("./config/traps-config.yaml:/app/config/config.yaml:ro", compose_file)
            self.assertIn("./secrets:/app/secrets/tmp:ro", compose_file)
            self.assertIn("./mibs:/app/new_mibs/src/vendor:ro", compose_file)
            self.assertIn("- snmp-mibserver", compose_file)
            self.assertIn("target: 2162", compose_file)
            self.assertIn("published: 162", compose_file)
            self.assertIn("192.0.2.10,161,2c,public", compose_inventory)
            self.assertEqual(compose_hec_token, "generated-sc4snmp-token\n")
            self.assertEqual(
                stat.S_IMODE((output_dir / "compose" / "secrets" / "hec_token").stat().st_mode),
                0o600,
            )
            self.assertEqual(
                stat.S_IMODE((output_dir / "compose" / "secrets" / "secrets.json.example").stat().st_mode),
                0o600,
            )

            self.assertIn('host: "example.invalid"', k8s_values)
            self.assertIn('port: "8088"', k8s_values)
            self.assertIn('loadBalancerIP: "10.10.10.50"', k8s_values)
            self.assertIn("usemetallb: false", k8s_values)
            self.assertIn('dnsServer: "10.10.10.53"', k8s_values)
            self.assertIn("inventory: |", k8s_values)
            self.assertIn("address,port,version,community", k8s_values)
            self.assertIn("groups:", k8s_values)
            self.assertIn("profiles:", k8s_values)
            self.assertIn("communities:", k8s_values)
            self.assertIn('token: "generated-sc4snmp-token"', k8s_secret)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["indexes"]["em_logs"]["datatype"], "event")
            self.assertEqual(state["indexes"]["netops"]["datatype"], "event")
            self.assertEqual(state["indexes"]["em_metrics"]["datatype"], "metric")
            self.assertEqual(state["indexes"]["netmetrics"]["datatype"], "metric")
            self.assertIn("sc4snmp", state["hec_tokens"])
            self.assertEqual(state["hec_tokens"]["sc4snmp"]["default_index"], "netops")

            validate_result = self.run_script(
                "skills/splunk-connect-for-snmp-setup/scripts/validate.sh",
                "--hec-token-name",
                "sc4snmp",
                env=env,
            )
            self.assertEqual(validate_result.returncode, 0, msg=validate_result.stdout + validate_result.stderr)
            self.assertIn("HEC token 'sc4snmp' exists", validate_result.stdout)
            self.assertIn("SC4SNMP event", validate_result.stdout)


    def test_sc4snmp_setup_uses_ingest_profile_for_hec_management_and_rendering(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _state_file = self.build_mock_sc4snmp_env(tmp_path)
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "sc4snmp.token"
            inventory_file = tmp_path / "inventory.csv"
            scheduler_file = tmp_path / "scheduler-config.yaml"
            traps_file = tmp_path / "traps-config.yaml"
            curl_log = tmp_path / "curl.log"

            inventory_file.write_text(
                "address,port,version,community,secret,security_engine,walk_interval,profiles,smart_profiles,delete\n"
                "192.0.2.10,161,2c,public,,,300,if_mib,,false\n",
                encoding="utf-8",
            )
            scheduler_file.write_text(
                textwrap.dedent(
                    """\
                    groups:
                      campus_switches:
                        - address: 192.0.2.10
                          port: 161
                    profiles:
                      if_mib:
                        frequency: 300
                        varBinds:
                          - ['IF-MIB', 'ifDescr']
                    """
                ),
                encoding="utf-8",
            )
            traps_file.write_text(
                textwrap.dedent(
                    """\
                    communities:
                      2c:
                        - public
                    """
                ),
                encoding="utf-8",
            )

            Path(env["SPLUNK_CREDENTIALS_FILE"]).write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_PLATFORM="enterprise"
                    SPLUNK_TARGET_ROLE="search-tier"
                    SPLUNK_SEARCH_API_URI="https://search.example.invalid:8089"
                    SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    SPLUNK_INGEST_PROFILE="hf"
                    PROFILE_hf__SPLUNK_PLATFORM="enterprise"
                    PROFILE_hf__SPLUNK_TARGET_ROLE="heavy-forwarder"
                    PROFILE_hf__SPLUNK_SEARCH_API_URI="https://hf.example.invalid:8089"
                    PROFILE_hf__SPLUNK_URI="${PROFILE_hf__SPLUNK_SEARCH_API_URI}"
                    PROFILE_hf__SPLUNK_USER="user"
                    PROFILE_hf__SPLUNK_PASS="pass"
                    PROFILE_hf__SPLUNK_HEC_URL="https://hf-hec.example.invalid:8088/services/collector/event"
                    """
                ),
                encoding="utf-8",
            )
            env["CURL_LOG"] = str(curl_log)

            result = self.run_script(
                "skills/splunk-connect-for-snmp-setup/scripts/setup.sh",
                "--splunk-prep",
                "--write-hec-token-file",
                str(token_file),
                "--render-compose",
                "--output-dir",
                str(output_dir),
                "--inventory-file",
                str(inventory_file),
                "--scheduler-file",
                str(scheduler_file),
                "--traps-file",
                str(traps_file),
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("Detected SC4SNMP HEC base URL: https://hf-hec.example.invalid:8088", output)
            self.assertIn(
                "SPLUNK_HEC_HOST=hf-hec.example.invalid",
                (output_dir / "compose" / ".env").read_text(encoding="utf-8"),
            )
            curl_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn(
                "https://hf.example.invalid:8089/services/data/inputs/http?output_mode=json",
                curl_requests,
            )
            self.assertNotIn(
                "https://search.example.invalid:8089/services/data/inputs/http?output_mode=json",
                curl_requests,
            )

            curl_log.write_text("", encoding="utf-8")
            validate_result = self.run_script(
                "skills/splunk-connect-for-snmp-setup/scripts/validate.sh",
                "--hec-token-name",
                "sc4snmp",
                env=env,
            )
            self.assertEqual(validate_result.returncode, 0, msg=validate_result.stdout + validate_result.stderr)
            validate_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn(
                "https://hf.example.invalid:8089/services/data/inputs/http?output_mode=json",
                validate_requests,
            )
            self.assertNotIn(
                "https://search.example.invalid:8089/services/data/inputs/http?output_mode=json",
                validate_requests,
            )


    def test_sc4snmp_clustered_ingest_uses_bundle_managed_hec(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _state_file = self.build_mock_sc4snmp_env(tmp_path)
            token_file = tmp_path / "sc4snmp.token"
            curl_log = tmp_path / "curl.log"
            apply_log = tmp_path / "bundle-apply.log"
            splunk_home = tmp_path / "cluster-manager"
            (splunk_home / "bin").mkdir(parents=True)

            write_executable(
                splunk_home / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                printf '%s\\n' "$*" >> "${BUNDLE_APPLY_LOG}"
                exit 0
                """,
            )

            Path(env["SPLUNK_CREDENTIALS_FILE"]).write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_PLATFORM="enterprise"
                    SPLUNK_TARGET_ROLE="search-tier"
                    SPLUNK_SEARCH_API_URI="https://search.example.invalid:8089"
                    SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    SPLUNK_INGEST_PROFILE="idx"
                    SPLUNK_CLUSTER_MANAGER_PROFILE="cm"
                    PROFILE_idx__SPLUNK_PLATFORM="enterprise"
                    PROFILE_idx__SPLUNK_TARGET_ROLE="indexer"
                    PROFILE_idx__SPLUNK_SEARCH_API_URI="https://indexer.example.invalid:8089"
                    PROFILE_idx__SPLUNK_URI="${PROFILE_idx__SPLUNK_SEARCH_API_URI}"
                    PROFILE_idx__SPLUNK_USER="user"
                    PROFILE_idx__SPLUNK_PASS="pass"
                    PROFILE_idx__SPLUNK_HEC_URL="https://idx-hec.example.invalid:8088/services/collector/event"
                    PROFILE_cm__SPLUNK_PLATFORM="enterprise"
                    PROFILE_cm__SPLUNK_SEARCH_API_URI="https://localhost:8089"
                    PROFILE_cm__SPLUNK_URI="${PROFILE_cm__SPLUNK_SEARCH_API_URI}"
                    PROFILE_cm__SPLUNK_USER="cm-user"
                    PROFILE_cm__SPLUNK_PASS="cm-pass"
                    """
                ),
                encoding="utf-8",
            )

            env["CURL_LOG"] = str(curl_log)
            env["SPLUNK_HOME"] = str(splunk_home)
            env["SPLUNK_LOCAL_SUDO"] = "false"
            env["SPLUNK_BUNDLE_OS_USER"] = getpass.getuser()
            env["BUNDLE_APPLY_LOG"] = str(apply_log)

            result = self.run_script(
                "skills/splunk-connect-for-snmp-setup/scripts/setup.sh",
                "--splunk-prep",
                "--hec-only",
                "--write-hec-token-file",
                str(token_file),
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("Created HEC token 'sc4snmp' via cluster-manager bundle.", output)
            token_value = token_file.read_text(encoding="utf-8").strip()
            self.assertRegex(token_value, r"^[0-9a-f-]{36}$")

            inputs_conf = (
                splunk_home
                / "etc"
                / "manager-apps"
                / "ZZZ_cisco_skills_hec"
                / "local"
                / "inputs.conf"
            ).read_text(encoding="utf-8")
            self.assertIn("[http]", inputs_conf)
            self.assertIn("[http://sc4snmp]", inputs_conf)
            self.assertIn("index = netops", inputs_conf)
            self.assertIn(f"token = {token_value}", inputs_conf)
            self.assertIn("disabled = 0", inputs_conf)
            apply_text = apply_log.read_text(encoding="utf-8")
            self.assertIn("apply cluster-bundle", apply_text)
            self.assertNotIn("-auth", apply_text)
            self.assertNotIn("cm-pass", apply_text)
            if curl_log.exists():
                self.assertNotIn("/services/data/inputs/http", curl_log.read_text(encoding="utf-8"))

            # As above, --hec-only deliberately leaves index ownership to a
            # separate workflow.  Seed that prerequisite in the mock rather
            # than weakening required-index validation.
            state_path = Path(env["SC4SNMP_STATE"])
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["indexes"].update(
                {
                    "em_logs": {"datatype": "event"},
                    "netops": {"datatype": "event"},
                    "em_metrics": {"datatype": "metric"},
                    "netmetrics": {"datatype": "metric"},
                }
            )
            state_path.write_text(json.dumps(state), encoding="utf-8")

            curl_log.write_text("", encoding="utf-8")
            validate_result = self.run_script(
                "skills/splunk-connect-for-snmp-setup/scripts/validate.sh",
                "--hec-token-name",
                "sc4snmp",
                env=env,
            )
            self.assertEqual(validate_result.returncode, 0, msg=validate_result.stdout + validate_result.stderr)
            self.assertIn("HEC token 'sc4snmp' exists", validate_result.stdout)
            self.assertNotIn("/services/data/inputs/http", curl_log.read_text(encoding="utf-8"))


    def test_sc4snmp_validate_reports_wrong_metrics_index_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, state_file = self.build_mock_sc4snmp_env(tmp_path)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["indexes"]["netmetrics"] = {"datatype": "event"}
            state["hec_tokens"]["sc4snmp"] = {
                "disabled": "false",
                "useACK": "0",
                "indexes": "",
                "index": "netops",
                "default_index": "netops",
                "token": "generated-sc4snmp-token",
            }
            state_file.write_text(json.dumps(state), encoding="utf-8")

            validate_result = self.run_script(
                "skills/splunk-connect-for-snmp-setup/scripts/validate.sh",
                "--hec-token-name",
                "sc4snmp",
                env=env,
            )
            self.assertEqual(validate_result.returncode, 1, msg=validate_result.stdout + validate_result.stderr)
            self.assertIn("Index 'netmetrics' exists but is an event index", validate_result.stdout)


    def test_sc4snmp_setup_enables_existing_disabled_hec_token(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, state_file = self.build_mock_sc4snmp_env(tmp_path)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["hec_tokens"]["sc4snmp"] = {
                "disabled": "true",
                "useACK": "0",
                "indexes": "",
                "index": "main",
                "default_index": "main",
                "token": "generated-sc4snmp-token",
            }
            state_file.write_text(json.dumps(state), encoding="utf-8")

            setup_result = self.run_script(
                "skills/splunk-connect-for-snmp-setup/scripts/setup.sh",
                "--splunk-prep",
                "--hec-only",
                env=env,
            )
            self.assertEqual(setup_result.returncode, 0, msg=setup_result.stdout + setup_result.stderr)
            self.assertIn("exists but is disabled. Enabling it via Splunk REST", setup_result.stdout)
            self.assertIn("Enabled HEC token 'sc4snmp'.", setup_result.stdout)
            self.assertIn("Updating it to 'netops' via Splunk REST", setup_result.stdout)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["hec_tokens"]["sc4snmp"]["disabled"], "false")
            self.assertEqual(state["hec_tokens"]["sc4snmp"]["default_index"], "netops")


    def test_sc4snmp_setup_blocks_custom_in_repo_secret_output_dir(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmpdir:
            tmp_path = Path(tmpdir)
            harness_path = tmp_path / "harness"
            harness_path.mkdir()
            env, _state_file = self.build_mock_sc4snmp_env(harness_path)
            token_file = tmp_path / "sc4snmp.token"
            token_file.write_text("existing-token\n", encoding="utf-8")
            token_file.chmod(0o600)

            output_dir = tmp_path / "dangerous-render"
            result = self.run_script(
                "skills/splunk-connect-for-snmp-setup/scripts/setup.sh",
                "--render-compose",
                "--output-dir",
                str(output_dir),
                "--hec-token-file",
                str(token_file),
                env=env,
            )
            self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
            self.assertIn("Refusing to render secret-bearing SC4SNMP outputs inside the repo", result.stdout + result.stderr)


    def test_gitignore_excludes_default_sc4snmp_render_output(self):
        gitignore_text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/sc4snmp-rendered/", gitignore_text)


    def test_sc4snmp_apply_compose_pulls_before_up(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _state_file = self.build_mock_sc4snmp_env(tmp_path)
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "sc4snmp.token"
            token_file.write_text("existing-token\n", encoding="utf-8")
            token_file.chmod(0o600)

            result = self.run_script(
                "skills/splunk-connect-for-snmp-setup/scripts/setup.sh",
                "--render-compose",
                "--output-dir",
                str(output_dir),
                "--hec-token-file",
                str(token_file),
                "--apply-compose",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            helper_text = (output_dir / "compose" / "compose-up.sh").read_text(encoding="utf-8")
            self.assertIn("compose -f docker-compose.yml pull", helper_text)

            commands = Path(env["SC4SNMP_COMMAND_LOG"]).read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                commands[:2],
                [
                    "docker compose -f docker-compose.yml pull",
                    "docker compose -f docker-compose.yml up -d",
                ],
            )


    def test_sc4snmp_apply_k8s_runs_helm_upgrade_install(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _state_file = self.build_mock_sc4snmp_env(tmp_path)
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "sc4snmp.token"
            token_file.write_text("existing-token\n", encoding="utf-8")
            token_file.chmod(0o600)

            result = self.run_script(
                "skills/splunk-connect-for-snmp-setup/scripts/setup.sh",
                "--render-k8s",
                "--output-dir",
                str(output_dir),
                "--hec-token-file",
                str(token_file),
                "--apply-k8s",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            commands = Path(env["SC4SNMP_COMMAND_LOG"]).read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                commands[:2],
                [
                    "helm repo add splunk-connect-for-snmp https://splunk.github.io/splunk-connect-for-snmp",
                    "helm repo update",
                ],
            )
            self.assertTrue(
                any(
                    "helm upgrade --install sc4snmp splunk-connect-for-snmp/splunk-connect-for-snmp --namespace sc4snmp --create-namespace -f values.yaml"
                    in line
                    for line in commands
                ),
                msg=f"Expected helm upgrade --install in command log, got: {commands}",
            )


    def test_sc4snmp_render_compose_without_token_file_creates_placeholder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _state_file = self.build_mock_sc4snmp_env(tmp_path)
            output_dir = tmp_path / "rendered"

            result = self.run_script(
                "skills/splunk-connect-for-snmp-setup/scripts/setup.sh",
                "--render-compose",
                "--output-dir",
                str(output_dir),
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            placeholder = output_dir / "compose" / "secrets" / "hec_token.example"
            self.assertTrue(placeholder.exists(), msg="Expected placeholder token file")
            self.assertIn("<replace-with-hec-token>", placeholder.read_text(encoding="utf-8"))
            self.assertEqual(stat.S_IMODE(placeholder.stat().st_mode), 0o600)


    def test_sc4snmp_render_compose_with_snmpv3_secrets_file_keeps_bind_secret_private(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _state_file = self.build_mock_sc4snmp_env(tmp_path)
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "sc4snmp.token"
            snmpv3_secrets_file = tmp_path / "secrets.json"

            token_file.write_text("existing-token\n", encoding="utf-8")
            token_file.chmod(0o600)
            snmpv3_secrets_file.write_text(
                textwrap.dedent(
                    """\
                    {
                      "lab-user": {
                        "username": "lab-user",
                        "authprotocol": "SHA",
                        "authkey": "secret"
                      }
                    }
                    """
                ),
                encoding="utf-8",
            )
            snmpv3_secrets_file.chmod(0o600)

            result = self.run_script(
                "skills/splunk-connect-for-snmp-setup/scripts/setup.sh",
                "--render-compose",
                "--output-dir",
                str(output_dir),
                "--hec-token-file",
                str(token_file),
                "--snmpv3-secrets-file",
                str(snmpv3_secrets_file),
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            rendered_secrets = output_dir / "compose" / "secrets" / "secrets.json"
            self.assertEqual(rendered_secrets.read_text(encoding="utf-8"), snmpv3_secrets_file.read_text(encoding="utf-8"))
            self.assertEqual(stat.S_IMODE(rendered_secrets.stat().st_mode), 0o600)


    def test_sc4snmp_hec_token_yaml_special_characters_escaped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _state_file = self.build_mock_sc4snmp_env(tmp_path)
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "tricky.token"
            token_file.write_text('ab"cd\\ef', encoding="utf-8")
            token_file.chmod(0o600)

            result = self.run_script(
                "skills/splunk-connect-for-snmp-setup/scripts/setup.sh",
                "--render-k8s",
                "--output-dir",
                str(output_dir),
                "--hec-token-file",
                str(token_file),
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            secret_yaml = (output_dir / "k8s" / "values.secret.yaml").read_text(encoding="utf-8")
            self.assertIn('token: "ab\\"cd\\\\ef"', secret_yaml)

    def test_sc4x_render_rejects_broad_mode_hec_token_with_clear_error(self):
        cases = (
            (
                "sc4s",
                self.build_mock_sc4s_env,
                "skills/splunk-connect-for-syslog-setup/scripts/setup.sh",
                "--render-host",
            ),
            (
                "sc4snmp",
                self.build_mock_sc4snmp_env,
                "skills/splunk-connect-for-snmp-setup/scripts/setup.sh",
                "--render-compose",
            ),
        )
        for name, build_env, script, render_flag in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                env, _state_file = build_env(tmp_path)
                token_file = tmp_path / f"{name}.token"
                token_file.write_text("do-not-expose\n", encoding="utf-8")
                token_file.chmod(0o644)

                result = self.run_script(
                    script,
                    render_flag,
                    "--output-dir",
                    str(tmp_path / "rendered"),
                    "--hec-token-file",
                    str(token_file),
                    env=env,
                )

                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Could not securely read HEC token file", output)
                self.assertIn("mode 0400 or 0600", output)
                self.assertNotIn("do-not-expose", output)


    def test_sc4snmp_validate_unexpected_useack_value(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, state_file = self.build_mock_sc4snmp_env(tmp_path)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["indexes"]["em_logs"] = {"datatype": "event"}
            state["indexes"]["netops"] = {"datatype": "event"}
            state["indexes"]["em_metrics"] = {"datatype": "metric"}
            state["indexes"]["netmetrics"] = {"datatype": "metric"}
            state["hec_tokens"]["sc4snmp"] = {
                "disabled": "false",
                "useACK": "unexpected",
                "indexes": "",
                "index": "netops",
                "token": "test-token",
            }
            state_file.write_text(json.dumps(state), encoding="utf-8")

            result = self.run_script(
                "skills/splunk-connect-for-snmp-setup/scripts/validate.sh",
                "--hec-token-name",
                "sc4snmp",
                env=env,
            )
            output = result.stdout + result.stderr
            self.assertIn("Could not determine HEC ACK state", output)
            self.assertNotIn("unbound variable", output.lower())


    def test_sc4snmp_validate_fails_when_default_index_is_main(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, state_file = self.build_mock_sc4snmp_env(tmp_path)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["indexes"]["em_logs"] = {"datatype": "event"}
            state["indexes"]["netops"] = {"datatype": "event"}
            state["indexes"]["em_metrics"] = {"datatype": "metric"}
            state["indexes"]["netmetrics"] = {"datatype": "metric"}
            state["hec_tokens"]["sc4snmp"] = {
                "disabled": "false",
                "useACK": "0",
                "indexes": "",
                "index": "main",
                "default_index": "main",
                "token": "generated-sc4snmp-token",
            }
            state_file.write_text(json.dumps(state), encoding="utf-8")

            result = self.run_script(
                "skills/splunk-connect-for-snmp-setup/scripts/validate.sh",
                "--hec-token-name",
                "sc4snmp",
                env=env,
            )
            self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
            self.assertIn("default index is 'main', expected 'netops'", result.stdout)


    def test_sc4snmp_render_k8s_without_trap_listener_ip_uses_nodeport(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _state_file = self.build_mock_sc4snmp_env(tmp_path)
            output_dir = tmp_path / "rendered"

            result = self.run_script(
                "skills/splunk-connect-for-snmp-setup/scripts/setup.sh",
                "--render-k8s",
                "--output-dir",
                str(output_dir),
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            values_yaml = (output_dir / "k8s" / "values.yaml").read_text(encoding="utf-8")
            self.assertIn("type: NodePort", values_yaml)
            self.assertNotIn("loadBalancerIP", values_yaml)
            self.assertIn("usemetallb: false", values_yaml)


    def test_sc4x_live_smoke_help(self):
        result = self.run_script_no_env(
            "skills/shared/scripts/smoke_sc4x_live.sh",
            "--help",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("SC4S / SC4SNMP Live Smoke Test", result.stdout)

    def test_sc4x_live_smoke_uses_shared_pinned_ssh_transport(self):
        script_text = (
            REPO_ROOT / "skills/shared/scripts/smoke_sc4x_live.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("hbs_capture_target_cmd ssh", script_text)
        self.assertNotIn("sshpass -f", script_text)
        self.assertNotIn("StrictHostKeyChecking=accept-new", script_text)
