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
            self.assertIn("apply cluster-bundle -auth cm-user:cm-pass", apply_log.read_text(encoding="utf-8"))
            if curl_log.exists():
                self.assertNotIn("/services/data/inputs/http", curl_log.read_text(encoding="utf-8"))

            curl_log.write_text("", encoding="utf-8")
            validate_result = self.run_script(
                "skills/splunk-connect-for-syslog-setup/scripts/validate.sh",
                "--hec-token-name",
                "sc4s",
                env=env,
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
                0o644,
            )
            self.assertEqual(
                stat.S_IMODE((output_dir / "compose" / "secrets" / "secrets.json.example").stat().st_mode),
                0o644,
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
            self.assertIn("apply cluster-bundle -auth cm-user:cm-pass", apply_log.read_text(encoding="utf-8"))
            if curl_log.exists():
                self.assertNotIn("/services/data/inputs/http", curl_log.read_text(encoding="utf-8"))

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
            self.assertEqual(stat.S_IMODE(placeholder.stat().st_mode), 0o644)


    def test_sc4snmp_render_compose_with_snmpv3_secrets_file_makes_bind_secret_readable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _state_file = self.build_mock_sc4snmp_env(tmp_path)
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "sc4snmp.token"
            snmpv3_secrets_file = tmp_path / "secrets.json"

            token_file.write_text("existing-token\n", encoding="utf-8")
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
            self.assertEqual(stat.S_IMODE(rendered_secrets.stat().st_mode), 0o644)


    def test_sc4snmp_hec_token_yaml_special_characters_escaped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _state_file = self.build_mock_sc4snmp_env(tmp_path)
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "tricky.token"
            token_file.write_text('ab"cd\\ef', encoding="utf-8")

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

    def test_sc4x_live_smoke_uses_sshpass_file_instead_of_password_flag(self):
        script_text = (
            REPO_ROOT / "skills/shared/scripts/smoke_sc4x_live.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("sshpass -f", script_text)
        self.assertNotIn("sshpass -p", script_text)
