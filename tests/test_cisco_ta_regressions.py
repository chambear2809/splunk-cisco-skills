#!/usr/bin/env python3
"""Regression tests for Cisco TA and host bootstrap shell scripts."""

import getpass
import io
import json
import os
import subprocess
import tarfile
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from tests.regression_helpers import (
    REPO_ROOT,
    ShellScriptRegressionBase,
    sha512_hex,
    write_executable,
    write_mock_curl,
    write_remote_shell_mocks,
)


class CiscoTARegressionTests(ShellScriptRegressionBase):
    def test_security_cloud_smoke_flow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, secrets_dir, state_file, install_log, curl_log = self.build_mock_cisco_skill_env(tmp_path)

            setup_result = self.run_script(
                "skills/cisco-security-cloud-setup/scripts/setup.sh",
                "--install",
                "--set-log-level",
                "DEBUG",
                "--no-restart",
                env=env,
            )
            self.assertEqual(setup_result.returncode, 0, msg=setup_result.stdout + setup_result.stderr)
            self.assertIn("Set CiscoSecurityCloud log level to DEBUG.", setup_result.stdout)
            self.assertIn("Installed app: CiscoSecurityCloud", setup_result.stdout)

            xdr_result = self.run_script(
                "skills/cisco-security-cloud-setup/scripts/configure_product.sh",
                "--product",
                "xdr",
                "--set",
                "region",
                "us",
                "--set",
                "auth_method",
                "client_id",
                "--set",
                "client_id",
                "example-client-id",
                "--set",
                "xdr_import_time_range",
                "7 days ago",
                "--secret-file",
                "refresh_token",
                str(secrets_dir / "xdr_refresh_token"),
                env=env,
            )
            self.assertEqual(xdr_result.returncode, 0, msg=xdr_result.stdout + xdr_result.stderr)
            self.assertIn("Configuring Cisco XDR via xdr", xdr_result.stdout)

            syslog_result = self.run_script(
                "skills/cisco-security-cloud-setup/scripts/configure_product.sh",
                "--product",
                "secure_firewall_syslog",
                "--set",
                "type",
                "udp",
                "--set",
                "port",
                "514",
                "--set",
                "sourcetype",
                "cisco:sfw:syslog",
                "--set",
                "event_types",
                "connection,security",
                env=env,
            )
            self.assertEqual(syslog_result.returncode, 0, msg=syslog_result.stdout + syslog_result.stderr)
            self.assertIn("Configuring Cisco Secure Firewall Syslog via secure_firewall_syslog", syslog_result.stdout)

            cii_result = self.run_script(
                "skills/cisco-security-cloud-setup/scripts/configure_product.sh",
                "--product",
                "cii_webhook",
                "--set",
                "cii_client_id",
                "cii-client-id",
                "--set",
                "cii_api_url",
                "https://cii.example/api",
                "--set",
                "cii_token_url",
                "https://cii.example/token",
                "--set",
                "cii_audience",
                "api://cii",
                "--set",
                "integration_method",
                "webhook",
                "--set",
                "hec_url",
                "https://splunk.example:8088",
                "--secret-file",
                "cii_client_secret",
                str(secrets_dir / "cii_client_secret"),
                env=env,
            )
            self.assertEqual(cii_result.returncode, 0, msg=cii_result.stdout + cii_result.stderr)
            self.assertIn("Configuring Cisco Identity Intelligence Webhook via cii_webhook", cii_result.stdout)

            validate_result = self.run_script(
                "skills/cisco-security-cloud-setup/scripts/validate.sh",
                env=env,
            )
            self.assertEqual(validate_result.returncode, 0, msg=validate_result.stdout + validate_result.stderr)
            self.assertIn("At least one Cisco Security Cloud input is configured", validate_result.stdout)

            validate_xdr_result = self.run_script(
                "skills/cisco-security-cloud-setup/scripts/validate.sh",
                "--product",
                "xdr",
                "--name",
                "XDR_Default",
                env=env,
            )
            self.assertEqual(validate_xdr_result.returncode, 0, msg=validate_xdr_result.stdout + validate_xdr_result.stderr)
            self.assertIn("sbg_xdr_input 'XDR_Default' is configured", validate_xdr_result.stdout)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["security_cloud_settings"]["loglevel"], "DEBUG")
            self.assertIn("cisco_xdr", state["indexes"])
            self.assertIn("cisco_sfw_ftd_syslog", state["indexes"])
            self.assertIn("cisco_cii", state["indexes"])
            self.assertIn("XDR_Default", state["security_cloud_handlers"]["CiscoSecurityCloud_sbg_xdr_input"])
            self.assertIn(
                "SecureFirewall_Syslog_Default",
                state["security_cloud_handlers"]["CiscoSecurityCloud_sbg_sfw_syslog_input"],
            )
            self.assertIn(
                "CII_Webhook_Default",
                state["security_cloud_handlers"]["CiscoSecurityCloud_sbg_cii_input"],
            )

            install_lines = install_log.read_text(encoding="utf-8").splitlines()
            self.assertTrue(
                any("--app-id 7404" in line for line in install_lines),
                msg="Cisco Security Cloud install was not invoked through the shared installer",
            )
            self.assertTrue(curl_log.exists(), msg="Expected mock curl log to be written")


    def test_secure_access_smoke_flow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, secrets_dir, state_file, install_log, curl_log = self.build_mock_cisco_skill_env(tmp_path)

            setup_result = self.run_script(
                "skills/cisco-secure-access-setup/scripts/setup.sh",
                "--install",
                "--no-restart",
                env=env,
            )
            self.assertEqual(setup_result.returncode, 0, msg=setup_result.stdout + setup_result.stderr)
            self.assertIn("Installed app: cisco-cloud-security", setup_result.stdout)

            account_result = self.run_script(
                "skills/cisco-secure-access-setup/scripts/configure_account.sh",
                "--discover-org-id",
                "--base-url",
                "https://api.us.security.cisco.com",
                "--timezone",
                "UTC",
                "--storage-region",
                "us",
                "--api-key-file",
                str(secrets_dir / "sa_api_key"),
                "--api-secret-file",
                str(secrets_dir / "sa_api_secret"),
                "--investigate-index",
                "cisco_secure_access_investigate",
                "--privateapp-index",
                "cisco_secure_access_private_apps",
                "--appdiscovery-index",
                "cisco_secure_access_app_discovery",
                env=env,
            )
            self.assertEqual(account_result.returncode, 0, msg=account_result.stdout + account_result.stderr)
            self.assertIn("Discovered org ID: org-123", account_result.stdout)
            self.assertIn("Created Cisco Secure Access org account 'org-123'.", account_result.stdout)

            settings_result = self.run_script(
                "skills/cisco-secure-access-setup/scripts/configure_settings.sh",
                "--org-id",
                "org-123",
                "--bootstrap-roles",
                "--accept-terms",
                "--apply-dashboard-defaults",
                "--cloudlock-name",
                "Cloudlock_Default",
                "--cloudlock-url",
                "https://cloudlock.example",
                "--cloudlock-token-file",
                str(secrets_dir / "cloudlock_token"),
                "--cloudlock-start-date",
                "20/03/2026",
                "--cloudlock-incident-details",
                "true",
                "--cloudlock-ueba",
                "false",
                "--destination-list",
                "123",
                "Important list",
                "cs_admin",
                "--dns-index",
                "cisco_secure_access_dns",
                "--proxy-index",
                "cisco_secure_access_proxy",
                "--firewall-index",
                "cisco_secure_access_firewall",
                env=env,
            )
            self.assertEqual(settings_result.returncode, 0, msg=settings_result.stdout + settings_result.stderr)
            self.assertIn("Bootstrapped Cisco Secure Access roles.", settings_result.stdout)
            self.assertIn("Recorded Secure Access terms acceptance", settings_result.stdout)
            self.assertIn("Updated Cisco Secure Access app settings for org 'org-123'.", settings_result.stdout)

            validate_result = self.run_script(
                "skills/cisco-secure-access-setup/scripts/validate.sh",
                "--org-id",
                "org-123",
                env=env,
            )
            self.assertEqual(validate_result.returncode, 0, msg=validate_result.stdout + validate_result.stderr)
            for expected in (
                "Org account 'org-123' exists",
                "Terms acceptance record present",
                "Dashboard search interval configured: 12",
                "Refresh rate configured: 0",
                "Cloudlock settings present: Cloudlock_Default (active)",
                "Selected destination lists configured: 1",
                "S3-backed indexes configured",
            ):
                self.assertIn(expected, validate_result.stdout)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertTrue(state["secure_access"]["roles_bootstrapped"])
            self.assertEqual(
                state["secure_access"]["collections"]["global_org"][0]["orgId"],
                "org-123",
            )
            self.assertEqual(
                state["secure_access"]["collections"]["dashboard_settings"][0]["search_interval"],
                "12",
            )
            self.assertEqual(
                state["secure_access"]["collections"]["refresh_rate"][0]["refresh_rate"],
                "0",
            )
            self.assertEqual(
                state["secure_access"]["collections"]["cloudlock_settings"][0]["configName"],
                "Cloudlock_Default",
            )
            self.assertEqual(
                state["secure_access"]["collections"]["selected_destination_lists"][0]["orgId"],
                "org-123",
            )
            self.assertEqual(
                state["secure_access"]["collections"]["s3_indexes"][0]["dns_index"],
                "cisco_secure_access_dns",
            )

            install_lines = install_log.read_text(encoding="utf-8").splitlines()
            self.assertTrue(
                any("--app-id 7569" in line for line in install_lines),
                msg="Cisco Secure Access add-on install was not invoked through the shared installer",
            )
            self.assertTrue(
                any("--app-id 5558" in line for line in install_lines),
                msg="Cisco Secure Access install was not invoked through the shared installer",
            )
            self.assertTrue(curl_log.exists(), msg="Expected mock curl log to be written")

    def test_secure_access_json_payload_keeps_secrets_off_python_argv(self):
        script_text = (
            REPO_ROOT / "skills/cisco-secure-access-setup/scripts/configure_account.sh"
        ).read_text(encoding="utf-8")

        self.assertNotIn('python3 - "$@"', script_text)
        self.assertIn('printf \'%s\\0\' "${arg}"', script_text)
        self.assertIn('chmod 600 "${args_file}"', script_text)


    def test_thousandeyes_hec_management_uses_ingest_profile_on_enterprise(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            state_file = tmp_path / "thousandeyes_state.json"
            curl_log = tmp_path / "curl.log"

            state_file.write_text(json.dumps({"hec_tokens": {}}), encoding="utf-8")
            credentials_file.write_text(
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

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path
                from urllib.parse import parse_qs, urlparse

                state_path = Path(os.environ["TE_STATE_FILE"])
                state = json.loads(state_path.read_text(encoding="utf-8"))
                args = sys.argv[1:]
                method = "GET"
                data = ""
                url = ""
                write_code = False
                output_target = None

                def save() -> None:
                    state_path.write_text(json.dumps(state), encoding="utf-8")

                def out(body: str = "", code: int | None = None) -> None:
                    if output_target == "/dev/null" and write_code and code is not None:
                        sys.stdout.write(str(code))
                        raise SystemExit(0)
                    if body:
                        sys.stdout.write(body)
                    if write_code and code is not None:
                        sys.stdout.write(f"\\n{code}")
                    raise SystemExit(0)

                i = 0
                while i < len(args):
                    arg = args[i]
                    if arg == "-X" and i + 1 < len(args):
                        method = args[i + 1]
                        i += 2
                        continue
                    if arg == "-d" and i + 1 < len(args):
                        if args[i + 1] == "@-":
                            data = sys.stdin.read()
                        else:
                            data = args[i + 1]
                        if method == "GET":
                            method = "POST"
                        i += 2
                        continue
                    if arg == "-o" and i + 1 < len(args):
                        output_target = args[i + 1]
                        i += 2
                        continue
                    if "%{http_code}" in arg:
                        write_code = True
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                    i += 1

                if url:
                    with Path(os.environ["CURL_LOG"]).open("a", encoding="utf-8") as handle:
                        handle.write(url + "\\n")

                parsed = urlparse(url)
                path = parsed.path

                if path.endswith("/services/auth/login"):
                    out("<response><sessionKey>test-session</sessionKey></response>")

                if "/services/apps/local/ta_cisco_thousandeyes" in path:
                    if write_code:
                        out(code=200)
                    out(json.dumps({"entry": [{"name": "ta_cisco_thousandeyes", "content": {"version": "1.0.0"}}]}))

                if path.endswith("/services/data/inputs/http") and method == "POST":
                    body = parse_qs(data, keep_blank_values=True)
                    name = body.get("name", ["thousandeyes"])[-1]
                    state["hec_tokens"][name] = {"default_index": "thousandeyes_metrics"}
                    save()
                    out("", 201)

                if path.endswith("/services/data/inputs/http"):
                    entries = [
                        {
                            "name": f"http://{name}",
                            "content": {
                                "default_index": token.get("default_index", "thousandeyes_metrics"),
                                "index": token.get("default_index", "thousandeyes_metrics"),
                            },
                        }
                        for name, token in sorted(state["hec_tokens"].items())
                    ]
                    out(json.dumps({"entry": entries}))

                out("", 200)
                """,
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
            env["TE_STATE_FILE"] = str(state_file)
            env["CURL_LOG"] = str(curl_log)

            result = self.run_script(
                "skills/cisco-thousandeyes-setup/scripts/setup.sh",
                "--hec-only",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("HEC token 'thousandeyes' created via REST.", output)
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
                "skills/cisco-thousandeyes-setup/scripts/validate.sh",
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


    def test_thousandeyes_clustered_ingest_uses_bundle_managed_hec(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            curl_log = tmp_path / "curl.log"
            apply_log = tmp_path / "bundle-apply.log"
            splunk_home = tmp_path / "cluster-manager"
            (splunk_home / "bin").mkdir(parents=True)

            credentials_file.write_text(
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

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path
                from urllib.parse import urlparse

                args = sys.argv[1:]
                url = ""
                for arg in args:
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg

                if url:
                    with Path(os.environ["CURL_LOG"]).open("a", encoding="utf-8") as handle:
                        handle.write(url + "\\n")

                if urlparse(url).path.endswith("/services/auth/login"):
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                    raise SystemExit(0)

                raise SystemExit(0)
                """,
            )
            write_executable(
                splunk_home / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                printf '%s\\n' "$*" >> "${BUNDLE_APPLY_LOG}"
                exit 0
                """,
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
            env["CURL_LOG"] = str(curl_log)
            env["SPLUNK_HOME"] = str(splunk_home)
            env["SPLUNK_LOCAL_SUDO"] = "false"
            env["SPLUNK_BUNDLE_OS_USER"] = getpass.getuser()
            env["BUNDLE_APPLY_LOG"] = str(apply_log)

            result = self.run_script(
                "skills/cisco-thousandeyes-setup/scripts/setup.sh",
                "--hec-only",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("HEC token 'thousandeyes' created via cluster-manager bundle.", output)
            inputs_conf = (
                splunk_home
                / "etc"
                / "manager-apps"
                / "ZZZ_cisco_skills_hec"
                / "local"
                / "inputs.conf"
            ).read_text(encoding="utf-8")
            self.assertIn("[http://thousandeyes]", inputs_conf)
            self.assertIn("index = thousandeyes_metrics", inputs_conf)
            self.assertIn("indexes = thousandeyes_metrics,thousandeyes_traces,thousandeyes_events,thousandeyes_activity,thousandeyes_alerts,thousandeyes_pathvis", inputs_conf)
            apply_text = apply_log.read_text(encoding="utf-8")
            self.assertIn("apply cluster-bundle", apply_text)
            self.assertNotIn("-auth", apply_text)
            self.assertNotIn("cm-pass", apply_text)
            self.assertNotIn("/services/data/inputs/http", curl_log.read_text(encoding="utf-8"))


    def test_thousandeyes_setup_enables_path_visualization_by_default(self):
        script_text = (REPO_ROOT / "skills/cisco-thousandeyes-setup/scripts/setup.sh").read_text(encoding="utf-8")

        self.assertIn("PATHVIS_ENABLED=true", script_text)
        self.assertIn('related_paths "1"', script_text)
        self.assertIn("--no-pathvis", script_text)
        self.assertIn("--hec-url", script_text)


    def test_thousandeyes_configure_account_avoids_eval_for_network_data(self):
        script_text = (
            REPO_ROOT / "skills/cisco-thousandeyes-setup/scripts/configure_account.sh"
        ).read_text(encoding="utf-8")

        self.assertNotIn('eval "$(parse_device_authorization_response', script_text)
        self.assertNotIn('eval "$(parse_token_success_response', script_text)
        self.assertNotIn('eval "$(parse_token_error_response', script_text)

    def test_thousandeyes_configure_account_does_not_put_bearer_token_on_curl_argv(self):
        script_text = (
            REPO_ROOT / "skills/cisco-thousandeyes-setup/scripts/configure_account.sh"
        ).read_text(encoding="utf-8")

        self.assertNotIn('-H "Authorization: Bearer ${bearer_token}"', script_text)
        self.assertIn('chmod 600 "${auth_config}"', script_text)
        self.assertIn('-K "${auth_config}"', script_text)
        self.assertIn('rm -f "${auth_config}"', script_text)

    def test_configure_scripts_reject_direct_secret_cli_values(self):
        cases = [
            ("skills/cisco-catalyst-ta-setup/scripts/configure_account.sh", "--password", "--password-file"),
            ("skills/cisco-catalyst-ta-setup/scripts/configure_account.sh", "--api-token", "--api-token-file"),
            ("skills/cisco-dc-networking-setup/scripts/configure_account.sh", "--password", "--password-file"),
            ("skills/cisco-appdynamics-setup/scripts/configure_account.sh", "--client-secret", "--client-secret-file"),
            ("skills/cisco-appdynamics-setup/scripts/configure_analytics.sh", "--analytics-secret", "--analytics-secret-file"),
            ("skills/cisco-intersight-setup/scripts/configure_account.sh", "--client-secret", "--client-secret-file"),
            ("skills/cisco-meraki-ta-setup/scripts/configure_account.sh", "--api-key", "--api-key-file"),
            ("skills/cisco-spaces-setup/scripts/configure_stream.sh", "--token", "--token-file"),
        ]

        for script, option, file_option in cases:
            with self.subTest(script=script, option=option):
                result = self.run_script_no_env(script, option, "not-a-real-secret")
                self.assertNotEqual(result.returncode, 0)
                output = result.stdout + result.stderr
                self.assertIn(f"{option} would expose a secret in process listings", output)
                self.assertIn(file_option, output)


    def test_catalyst_configure_account_no_verify_ssl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, curl_log = self._build_configure_account_env(tmp_path)
            password_file = tmp_path / "device_password"

            result = self.run_script(
                "skills/cisco-catalyst-ta-setup/scripts/configure_account.sh",
                "--type", "catalyst_center",
                "--name", "TestDNAC",
                "--host", "https://10.100.0.60",
                "--username", "admin",
                "--password-file", str(password_file),
                "--no-verify-ssl",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("verify_ssl=False", result.stdout)
            self.assertIn("ta_cisco_catalyst_settings", result.stdout)

            log_text = curl_log.read_text(encoding="utf-8")
            settings_posts = [
                line for line in log_text.splitlines()
                if "CONF_POST" in line and "ta_cisco_catalyst_settings" in line
            ]
            self.assertTrue(
                len(settings_posts) > 0,
                msg="Expected a POST to ta_cisco_catalyst_settings conf",
            )
            self.assertTrue(
                any("verify_ssl" in line and "False" in line for line in settings_posts),
                msg=f"Expected verify_ssl=False in settings POST, got: {settings_posts}",
            )


    def test_dc_networking_configure_account_no_verify_ssl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, curl_log = self._build_configure_account_env(tmp_path)
            password_file = tmp_path / "device_password"

            result = self.run_script(
                "skills/cisco-dc-networking-setup/scripts/configure_account.sh",
                "--type", "aci",
                "--name", "TestACI",
                "--hostname", "10.0.0.1",
                "--username", "admin",
                "--password-file", str(password_file),
                "--no-verify-ssl",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("verify_ssl=False", result.stdout)
            self.assertIn("cisco_dc_networking_app_for_splunk_settings", result.stdout)

            log_text = curl_log.read_text(encoding="utf-8")
            settings_posts = [
                line for line in log_text.splitlines()
                if "CONF_POST" in line and "cisco_dc_networking_app_for_splunk_settings" in line
            ]
            self.assertTrue(
                len(settings_posts) > 0,
                msg="Expected a POST to cisco_dc_networking_app_for_splunk_settings conf",
            )
            self.assertTrue(
                any("verify_ssl" in line and "False" in line for line in settings_posts),
                msg=f"Expected verify_ssl=False in settings POST, got: {settings_posts}",
            )
            conf_posts = [
                line for line in log_text.splitlines()
                if "CONF_POST" in line
            ]
            self.assertGreaterEqual(len(conf_posts), 2, msg=f"Expected settings and account POSTs, got: {conf_posts}")
            self.assertIn(
                "cisco_dc_networking_app_for_splunk_settings",
                conf_posts[0],
                msg=f"Expected verify_ssl settings POST before account create, got: {conf_posts}",
            )
            self.assertIn(
                "cisco_dc_networking_app_for_splunk_aci_account",
                conf_posts[1],
                msg=f"Expected account POST after verify_ssl settings POST, got: {conf_posts}",
            )


    def test_catalyst_configure_account_without_ssl_flag_skips_setting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, curl_log = self._build_configure_account_env(tmp_path)
            password_file = tmp_path / "device_password"

            result = self.run_script(
                "skills/cisco-catalyst-ta-setup/scripts/configure_account.sh",
                "--type", "catalyst_center",
                "--name", "TestDNAC",
                "--host", "https://10.100.0.60",
                "--username", "admin",
                "--password-file", str(password_file),
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertNotIn("verify_ssl", result.stdout)

            log_text = curl_log.read_text(encoding="utf-8")
            settings_posts = [
                line for line in log_text.splitlines()
                if "CONF_POST" in line and "ta_cisco_catalyst_settings" in line
            ]
            self.assertEqual(
                len(settings_posts), 0,
                msg="Should not POST to settings conf when --no-verify-ssl is not passed",
            )

    def test_intersight_validate_reads_vendor_settings_conf_for_ssl_validation(self):
        script_text = (
            REPO_ROOT / "skills/cisco-intersight-setup/scripts/validate.sh"
        ).read_text(encoding="utf-8")

        self.assertIn(
            '"Splunk_TA_Cisco_Intersight_settings" "verify_ssl" "ssl_validation"',
            script_text,
        )
        self.assertNotIn(
            '"splunk_ta_cisco_intersight_settings" "verify_ssl" "ssl_validation"',
            script_text,
        )

    def test_product_setup_meraki_macro_uses_valid_in_syntax(self):
        script_text = (
            REPO_ROOT / "skills/cisco-product-setup/scripts/setup.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('definition="index IN (${index_name})"', script_text)
        self.assertNotIn('definition="index IN(${index_name})"', script_text)


    def test_meraki_setup_devices_group_includes_all_supported_device_inputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, curl_log = self._build_meraki_setup_env(tmp_path)

            result = self.run_script(
                "skills/cisco-meraki-ta-setup/scripts/setup.sh",
                "--enable-inputs",
                "--account",
                "CVF",
                "--index",
                "meraki",
                "--input-type",
                "devices",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Device inputs enabled (7 inputs).", result.stdout)
            self.assertIn("Live input status: total=7, enabled=7, disabled=0", result.stdout)

            log_text = curl_log.read_text(encoding="utf-8")
            expected_types = [
                "cisco_meraki_devices",
                "cisco_meraki_devices_availabilities",
                "cisco_meraki_device_availabilities_change_history",
                "cisco_meraki_device_uplink_addresses_by_device",
                "cisco_meraki_devices_uplinks_loss_and_latency",
                "cisco_meraki_power_modules_statuses_by_device",
                "cisco_meraki_firmware_upgrades",
            ]
            for input_type in expected_types:
                self.assertIn(
                    f"INPUT_POST type={input_type}",
                    log_text,
                    msg=f"Expected device input enablement for {input_type}",
                )

    def _build_configure_account_env(self, tmp_path: Path) -> tuple[dict, Path]:
        """Build a mock environment for configure_account.sh integration tests."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        curl_log = tmp_path / "curl.log"
        credentials_file = tmp_path / "credentials"
        password_file = tmp_path / "device_password"

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
        password_file.write_text("device-secret", encoding="utf-8")

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
            import json
            import os
            import sys
            from pathlib import Path
            from urllib.parse import parse_qs, urlparse, unquote

            log_path = Path(os.environ["CURL_LOG"])
            args = sys.argv[1:]
            method = "GET"
            data = ""
            url = ""
            write_code = False
            output_target = None

            def log(msg: str) -> None:
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(msg + "\\n")

            def out(body: str = "", code: int | None = None) -> None:
                if output_target == "/dev/null" and write_code and code is not None:
                    sys.stdout.write(str(code))
                    raise SystemExit(0)
                if body:
                    sys.stdout.write(body)
                if write_code and code is not None:
                    sys.stdout.write(f"\\n{code}")
                raise SystemExit(0)

            i = 0
            while i < len(args):
                arg = args[i]
                if arg == "-d" and i + 1 < len(args):
                    if args[i + 1] == "@-":
                        data = sys.stdin.read()
                    else:
                        data = args[i + 1]
                    if method == "GET":
                        method = "POST"
                    i += 2
                    continue
                if arg == "-o" and i + 1 < len(args):
                    output_target = args[i + 1]
                    i += 2
                    continue
                if "%{http_code}" in arg:
                    write_code = True
                if arg.startswith("http://") or arg.startswith("https://"):
                    url = arg
                i += 1

            parsed = urlparse(url)
            path = parsed.path
            log(f"URL={url} METHOD={method} DATA={data!r}")

            if "/services/auth/login" in path:
                out("<response><sessionKey>test-session</sessionKey></response>")

            if ("_account" in path or "_settings" in path) and method == "POST":
                log(f"CONF_POST path={path} data={data!r}")
                out("", 200)

            out("", 200)
            """,
        )

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["CURL_LOG"] = str(curl_log)
        env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
        env["SPLUNK_PLATFORM"] = "enterprise"

        return env, curl_log

    def _build_meraki_setup_env(self, tmp_path: Path) -> tuple[dict, Path]:
        """Build a mock environment for Meraki setup.sh input enablement tests."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        curl_log = tmp_path / "curl.log"
        state_file = tmp_path / "state.json"
        credentials_file = tmp_path / "credentials"

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
        state_file.write_text(json.dumps({"inputs": {}}), encoding="utf-8")

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
            import json
            import os
            import sys
            from pathlib import Path
            from urllib.parse import parse_qs, urlparse, unquote

            state_path = Path(os.environ["MOCK_STATE"])
            log_path = Path(os.environ["CURL_LOG"])
            state = json.loads(state_path.read_text(encoding="utf-8"))

            args = sys.argv[1:]
            method = "GET"
            data = ""
            url = ""
            write_code = False
            output_target = None

            def log(msg: str) -> None:
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(msg + "\\n")

            def save() -> None:
                state_path.write_text(json.dumps(state), encoding="utf-8")

            def out(body: str = "", code: int | None = None) -> None:
                if output_target == "/dev/null" and write_code and code is not None:
                    sys.stdout.write(str(code))
                    raise SystemExit(0)
                if body:
                    sys.stdout.write(body)
                if write_code and code is not None:
                    sys.stdout.write(f"\\n{code}")
                raise SystemExit(0)

            def decode_form(raw: str) -> dict[str, str]:
                parsed_body = parse_qs(raw, keep_blank_values=True)
                return {key: values[-1] for key, values in parsed_body.items()}

            i = 0
            while i < len(args):
                arg = args[i]
                if arg == "-d" and i + 1 < len(args):
                    if args[i + 1] == "@-":
                        data = sys.stdin.read()
                    else:
                        data = args[i + 1]
                    if method == "GET":
                        method = "POST"
                    i += 2
                    continue
                if arg == "-o" and i + 1 < len(args):
                    output_target = args[i + 1]
                    i += 2
                    continue
                if "%{http_code}" in arg:
                    write_code = True
                if arg.startswith("http://") or arg.startswith("https://"):
                    url = arg
                i += 1

            parsed = urlparse(url)
            path = parsed.path
            log(f"URL={url} METHOD={method} DATA={data!r}")

            if "/services/auth/login" in path:
                out("<response><sessionKey>test-session</sessionKey></response>")

            if "/services/apps/local/Splunk_TA_cisco_meraki" in path:
                if output_target == "/dev/null" and write_code:
                    out(code=200)
                out(json.dumps({"entry": [{"name": "Splunk_TA_cisco_meraki", "content": {"version": "3.3.0"}}]}))

            if path.endswith("/services/data/inputs/all"):
                entries = []
                for name, content in state["inputs"].items():
                    entries.append(
                        {
                            "name": name,
                            "acl": {"app": "Splunk_TA_cisco_meraki"},
                            "content": content,
                        }
                    )
                out(json.dumps({"entry": entries}))

            if "/servicesNS/nobody/Splunk_TA_cisco_meraki/data/inputs/" in path:
                suffix = path.split("/servicesNS/nobody/Splunk_TA_cisco_meraki/data/inputs/", 1)[1]
                parts = suffix.split("/")
                input_type = parts[0]
                existing_name = unquote(parts[1]) if len(parts) > 1 else ""

                if method == "GET":
                    exists = existing_name in state["inputs"]
                    if output_target == "/dev/null" and write_code:
                        out(code=200 if exists else 404)
                    if exists:
                        out(
                            json.dumps(
                                {
                                    "entry": [
                                        {
                                            "name": existing_name,
                                            "acl": {"app": "Splunk_TA_cisco_meraki"},
                                            "content": state["inputs"][existing_name],
                                        }
                                    ]
                                }
                            )
                        )
                    out(json.dumps({"entry": []}))

                body = decode_form(data)
                input_name = existing_name or body.pop("name", "")
                content = state["inputs"].get(input_name, {})
                content.update(body)
                content.setdefault("disabled", "0")
                state["inputs"][input_name] = content
                save()
                log(f"INPUT_POST type={input_type} name={input_name} data={data!r}")
                out("", 200 if existing_name else 201)

            out("", 200)
            """,
        )

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["CURL_LOG"] = str(curl_log)
        env["MOCK_STATE"] = str(state_file)
        env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
        env["SPLUNK_PLATFORM"] = "enterprise"

        return env, curl_log


    def test_host_bootstrap_validate_local_mode_uses_localhost_for_rest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            splunk_home = tmp_path / "splunk"
            (splunk_home / "bin").mkdir(parents=True)
            curl_log = tmp_path / "curl.log"
            credentials_file = tmp_path / "credentials"
            password_file = tmp_path / "admin_password"
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()

            credentials_file.write_text('SPLUNK_HOST="wrong.example.com"\n', encoding="utf-8")
            password_file.write_text("changeme\n", encoding="utf-8")

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                url = ""
                for arg in reversed(sys.argv[1:]):
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                        break
                with Path(os.environ["CURL_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(url + "\\n")
                if url.endswith("/services/auth/login"):
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                elif "/services/server/info" in url:
                    sys.stdout.write('{"entry":[{"name":"server-info"}]}')
                """,
            )
            write_executable(
                splunk_home / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                case "$1" in
                    status) echo "splunkd is running"; exit 0 ;;
                    version) echo "Splunk 10.0.0"; exit 0 ;;
                    btool) exit 0 ;;
                    show) exit 0 ;;
                    *) exit 0 ;;
                esac
                """,
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "CURL_LOG": str(curl_log),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/validate.sh",
                "--execution", "local",
                "--host-bootstrap-role", "standalone-search-tier",
                "--splunk-home", str(splunk_home),
                "--service-user", current_user,
                "--admin-password-file", str(password_file),
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            curl_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn("https://localhost:8089/services/auth/login", curl_requests)
            self.assertIn("https://localhost:8089/services/server/info?output_mode=json", curl_requests)
            self.assertNotIn("wrong.example.com", curl_requests)


    def test_host_bootstrap_validate_heavy_forwarder_accepts_server_list_without_mode_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            splunk_home = tmp_path / "splunk"
            (splunk_home / "bin").mkdir(parents=True)
            curl_log = tmp_path / "curl.log"
            credentials_file = tmp_path / "credentials"
            password_file = tmp_path / "admin_password"
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()

            credentials_file.write_text("", encoding="utf-8")
            password_file.write_text("changeme\n", encoding="utf-8")

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                url = ""
                for arg in reversed(sys.argv[1:]):
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                        break
                with Path(os.environ["CURL_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(url + "\\n")
                if url.endswith("/services/auth/login"):
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                elif "/services/server/info" in url:
                    sys.stdout.write('{"entry":[{"name":"server-info"}]}')
                """,
            )
            write_executable(
                splunk_home / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                if [[ "$1" == "status" ]]; then
                    echo "splunkd is running"
                    exit 0
                fi
                if [[ "$1" == "version" ]]; then
                    echo "Splunk 10.0.0"
                    exit 0
                fi
                if [[ "$1" == "btool" && "$2" == "outputs" ]]; then
                    cat <<'EOF'
[tcpout]
defaultGroup = default-autolb-group
indexAndForward = false
[tcpout:default-autolb-group]
server = idx01.example.com:9997,idx02.example.com:9997
EOF
                    exit 0
                fi
                exit 0
                """,
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "CURL_LOG": str(curl_log),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/validate.sh",
                "--execution", "local",
                "--host-bootstrap-role", "heavy-forwarder",
                "--splunk-home", str(splunk_home),
                "--service-user", current_user,
                "--admin-password-file", str(password_file),
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("outputs.conf uses a static server list", result.stdout)


    def test_host_bootstrap_setup_requires_current_shc_member_for_existing_cluster(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            credentials_file = tmp_path / "credentials"
            credentials_file.write_text("", encoding="utf-8")
            env = os.environ.copy()
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "cluster",
                "--execution", "local",
                "--deployment-mode", "clustered",
                "--host-bootstrap-role", "shc-member",
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--current-shc-member-uri", result.stdout + result.stderr)


    def test_host_bootstrap_setup_cluster_adds_shc_member_without_inline_auth(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            splunk_home = tmp_path / "splunk"
            (splunk_home / "bin").mkdir(parents=True)
            credentials_file = tmp_path / "credentials"
            password_file = tmp_path / "admin_password"
            shc_secret_file = tmp_path / "shc_secret"
            idxc_secret_file = tmp_path / "idxc_secret"
            cmd_log = tmp_path / "splunk_args.log"
            stdin_log = tmp_path / "splunk_stdin.log"
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()

            credentials_file.write_text("", encoding="utf-8")
            password_file.write_text("changeme\n", encoding="utf-8")
            shc_secret_file.write_text("shc-secret\n", encoding="utf-8")
            idxc_secret_file.write_text("idxc-secret\n", encoding="utf-8")

            write_executable(
                splunk_home / "bin" / "splunk",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path

                args = sys.argv[1:]
                stdin_data = sys.stdin.read()
                with Path(os.environ["SPLUNK_CMD_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(args) + "\\n")
                with Path(os.environ["SPLUNK_STDIN_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"args": args, "stdin": stdin_data}) + "\\n")
                if args and args[0] == "status":
                    sys.stdout.write("splunkd is running")
                """,
            )

            env = os.environ.copy()
            env.update(
                {
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_LOCAL_SUDO": "false",
                    "SPLUNK_CMD_LOG": str(cmd_log),
                    "SPLUNK_STDIN_LOG": str(stdin_log),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "cluster",
                "--execution", "local",
                "--deployment-mode", "clustered",
                "--host-bootstrap-role", "shc-member",
                "--splunk-home", str(splunk_home),
                "--service-user", current_user,
                "--admin-password-file", str(password_file),
                "--shc-secret-file", str(shc_secret_file),
                "--idxc-secret-file", str(idxc_secret_file),
                "--deployer-uri", "https://deployer.example.com:8089",
                "--cluster-manager-uri", "https://cm.example.com:8089",
                "--current-shc-member-uri", "https://sh1.example.com:8089",
                "--advertise-host", "sh2.example.com",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            server_conf = splunk_home / "etc" / "system" / "local" / "server.conf"
            self.assertTrue(server_conf.exists())
            server_conf_text = server_conf.read_text(encoding="utf-8")
            self.assertIn("mgmt_uri = https://sh2.example.com:8089", server_conf_text)
            self.assertIn("conf_deploy_fetch_url = https://deployer.example.com:8089", server_conf_text)
            self.assertIn("pass4SymmKey = shc-secret", server_conf_text)
            self.assertIn("manager_uri = https://cm.example.com:8089", server_conf_text)
            self.assertIn("pass4SymmKey = idxc-secret", server_conf_text)

            command_lines = cmd_log.read_text(encoding="utf-8").splitlines()
            self.assertTrue(
                any("add" in line and "shcluster-member" in line for line in command_lines),
                msg=f"Expected add shcluster-member command, got: {command_lines}",
            )
            self.assertTrue(
                all("-auth" not in line and "-secret" not in line and "shc-secret" not in line and "idxc-secret" not in line for line in command_lines),
                msg=f"Did not expect inline auth or secret arguments, got: {command_lines}",
            )

            stdin_lines = stdin_log.read_text(encoding="utf-8")
            self.assertIn("admin\\nchangeme", stdin_lines)
            self.assertIn("current_member_uri", command_lines[-1] if command_lines else "")


    def test_host_bootstrap_setup_rejects_deb_auto_with_custom_home(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            credentials_file = tmp_path / "credentials"
            package_file = tmp_path / "splunk-10.0.0-linux-amd64.deb"
            password_file = tmp_path / "admin_password"

            credentials_file.write_text("", encoding="utf-8")
            package_file.write_text("deb-package-placeholder", encoding="utf-8")
            password_file.write_text("changeme\n", encoding="utf-8")

            env = os.environ.copy()
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "install",
                "--execution", "local",
                "--host-bootstrap-role", "standalone-search-tier",
                "--source", "local",
                "--file", str(package_file),
                "--package-type", "auto",
                "--splunk-home", str(tmp_path / "custom-splunk"),
                "--admin-password-file", str(password_file),
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("DEB installs only support /opt/splunk", result.stdout + result.stderr)


    def test_host_bootstrap_setup_rejects_existing_non_splunk_custom_tgz_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            credentials_file = tmp_path / "credentials"
            package_file = tmp_path / "splunk-10.0.0-linux-x86_64.tgz"
            password_file = tmp_path / "admin_password"
            target_home = tmp_path / "existing-target"

            credentials_file.write_text("", encoding="utf-8")
            package_file.write_text("tgz-package-placeholder", encoding="utf-8")
            password_file.write_text("changeme\n", encoding="utf-8")
            target_home.mkdir()

            env = os.environ.copy()
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "install",
                "--execution", "local",
                "--host-bootstrap-role", "standalone-search-tier",
                "--source", "local",
                "--file", str(package_file),
                "--package-type", "auto",
                "--splunk-home", str(target_home),
                "--admin-password-file", str(password_file),
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already exists but is not a Splunk install", result.stdout + result.stderr)


    def test_host_bootstrap_remote_staging_uses_user_tmp_before_privileged_tmpdir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            local_file = tmp_path / "pkg.tgz"
            local_file.write_text("package", encoding="utf-8")
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            cmd_log = tmp_path / "cmd.log"
            sshpass_log = tmp_path / "sshpass.log"

            write_executable(
                bin_dir / "sshpass",
                """\
                #!/usr/bin/env bash
                printf '%s\n' "$*" >> "${SSHPASS_LOG}"
                exit 0
                """,
            )

            helper_script = textwrap.dedent(
                f"""\
                source "{REPO_ROOT / 'skills/shared/lib/host_bootstrap_helpers.sh'}"
                load_splunk_ssh_credentials() {{ :; }}
                hbs_run_target_cmd() {{
                    printf '%s\\n' "$2" >> "{cmd_log}"
                    return 0
                }}
                export SPLUNK_SSH_USER="bootstrap"
                export SPLUNK_SSH_HOST="hf.example.com"
                export SPLUNK_SSH_PORT="22"
                export SPLUNK_SSH_PASS="secret"
                export SPLUNK_REMOTE_TMPDIR="/var/tmp/splunk"
                result="$(hbs_stage_file_for_execution ssh "{local_file}" "pkg.tgz")"
                printf '%s\\n' "$result"
                """
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "SSHPASS_LOG": str(sshpass_log),
                }
            )

            result = subprocess.run(
                ["bash", "-c", helper_script],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), "/var/tmp/splunk/pkg.tgz")

            sshpass_text = sshpass_log.read_text(encoding="utf-8")
            self.assertIn("scp", sshpass_text)
            self.assertIn("/tmp/pkg.tgz.stage.", sshpass_text)
            self.assertNotIn("hf.example.com:/var/tmp/splunk/pkg.tgz", sshpass_text)

            cmd_text = cmd_log.read_text(encoding="utf-8")
            self.assertIn("mkdir -p /var/tmp/splunk", cmd_text)
            self.assertIn("install -m 600 /tmp/pkg.tgz.stage.", cmd_text)
            self.assertIn("/var/tmp/splunk/pkg.tgz", cmd_text)


    def test_host_bootstrap_remote_staging_reports_noninteractive_sudo_requirement(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            local_file = tmp_path / "pkg.tgz"
            local_file.write_text("package", encoding="utf-8")
            bin_dir = tmp_path / "bin"
            remote_root = tmp_path / "remote-root"
            bin_dir.mkdir()

            write_remote_shell_mocks(bin_dir)
            write_executable(
                bin_dir / "sshpass",
                """\
                #!/usr/bin/env bash
                shift 2
                if [[ "${1:-}" == "scp" ]]; then
                    exit 0
                fi
                if [[ "${1:-}" == "ssh" ]]; then
                    shift
                    exec "$(dirname "$0")/ssh" "$@"
                fi
                exec "$@"
                """,
            )

            helper_script = textwrap.dedent(
                f"""\
                source "{REPO_ROOT / 'skills/shared/lib/host_bootstrap_helpers.sh'}"
                load_splunk_ssh_credentials() {{ :; }}
                export SPLUNK_SSH_USER="bootstrap"
                export SPLUNK_SSH_HOST="hf.example.com"
                export SPLUNK_SSH_PORT="22"
                export SPLUNK_SSH_PASS="secret"
                export REMOTE_ROOT="{remote_root}"
                hbs_stage_file_for_execution ssh "{local_file}" "pkg.tgz"
                """
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "REMOTE_ROOT": str(remote_root),
                    "REMOTE_SUDO_MODE": "require_stdin",
                }
            )

            result = subprocess.run(
                ["bash", "-lc", helper_script],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("either use the -S option", result.stdout + result.stderr)


    def test_host_bootstrap_install_preserves_local_package_and_cleans_user_seed_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()
            credentials_file = tmp_path / "credentials"
            password_file = tmp_path / "admin_password"
            package_file = tmp_path / "splunk-10.0.0-linux-x86_64.tgz"
            splunk_home = tmp_path / "installed-splunk"
            package_root = tmp_path / "package-root" / "splunk"
            (package_root / "bin").mkdir(parents=True)

            credentials_file.write_text("", encoding="utf-8")
            password_file.write_text("changeme\n", encoding="utf-8")

            write_executable(
                bin_dir / "sudo",
                """\
                #!/usr/bin/env bash
                exec "$@"
                """,
            )
            write_executable(
                bin_dir / "chown",
                """\
                #!/usr/bin/env bash
                exit 0
                """,
            )
            write_executable(
                package_root / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                case "$1" in
                    start|restart) echo "started"; exit 0 ;;
                    status) echo "splunkd is running"; exit 0 ;;
                    version) echo "Splunk 10.0.0"; exit 0 ;;
                    enable) exit 0 ;;
                    *) exit 0 ;;
                esac
                """,
            )

            with tarfile.open(package_file, "w:gz") as archive:
                archive.add(package_root, arcname="splunk")

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_LOCAL_SUDO": "false",
                }
            )

            install_args = (
                "--phase", "install",
                "--execution", "local",
                "--host-bootstrap-role", "standalone-search-tier",
                "--source", "local",
                "--file", str(package_file),
                "--splunk-home", str(splunk_home),
                "--service-user", current_user,
                "--admin-password-file", str(password_file),
                "--no-boot-start",
            )

            first_result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                *install_args,
                env=env,
            )
            self.assertEqual(first_result.returncode, 0, msg=first_result.stdout + first_result.stderr)
            self.assertTrue(package_file.exists(), msg="Local package should not be deleted after install")
            self.assertFalse((splunk_home / "etc/system/local/user-seed.conf").exists())
            self.assertEqual(list((splunk_home / "etc/system/local").glob("user-seed.conf.bak.*")), [])

            stale_backup = splunk_home / "etc/system/local/user-seed.conf.bak.stale"
            stale_backup.parent.mkdir(parents=True, exist_ok=True)
            stale_backup.write_text("stale", encoding="utf-8")
            package_file.write_text("not-a-tarball\n", encoding="utf-8")

            second_result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                *install_args,
                env=env,
            )
            self.assertEqual(second_result.returncode, 0, msg=second_result.stdout + second_result.stderr)
            self.assertTrue(package_file.exists(), msg="Local package should remain after repeated install runs")
            self.assertIn("already matches the requested package", second_result.stdout)
            self.assertFalse(stale_backup.exists(), msg="Repeated same-version install should clean stale user-seed backups")

    def test_host_bootstrap_install_rejects_unsafe_tgz_members(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()
            credentials_file = tmp_path / "credentials"
            password_file = tmp_path / "admin_password"
            package_file = tmp_path / "splunk-10.0.0-linux-x86_64.tgz"
            splunk_home = tmp_path / "installed-splunk"
            escape_path = tmp_path / "escaped.txt"

            credentials_file.write_text("", encoding="utf-8")
            password_file.write_text("changeme\n", encoding="utf-8")
            with tarfile.open(package_file, "w:gz") as archive:
                data = b"escape"
                info = tarfile.TarInfo("../escaped.txt")
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

            env = os.environ.copy()
            env.update(
                {
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_LOCAL_SUDO": "false",
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "install",
                "--execution", "local",
                "--host-bootstrap-role", "standalone-search-tier",
                "--source", "local",
                "--file", str(package_file),
                "--splunk-home", str(splunk_home),
                "--service-user", current_user,
                "--admin-password-file", str(password_file),
                "--no-boot-start",
                env=env,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Unsafe package archive member", result.stdout + result.stderr)
            self.assertFalse(escape_path.exists())


    def test_host_bootstrap_install_upgrades_tgz_without_admin_password_and_preserves_local_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()
            credentials_file = tmp_path / "credentials"
            package_file = tmp_path / "splunk-10.1.0-linux-x86_64.tgz"
            splunk_home = tmp_path / "installed-splunk"
            package_root = tmp_path / "package-root" / "splunk"
            cmd_log = tmp_path / "splunk.log"

            credentials_file.write_text("", encoding="utf-8")
            (splunk_home / "bin").mkdir(parents=True)
            (splunk_home / "etc/test").mkdir(parents=True)
            (package_root / "bin").mkdir(parents=True)
            (package_root / "etc/test").mkdir(parents=True)

            (splunk_home / "etc/test/default.txt").write_text("old-default\n", encoding="utf-8")
            (splunk_home / "etc/test/local-only.conf").write_text("keep-me\n", encoding="utf-8")
            (package_root / "etc/test/default.txt").write_text("new-default\n", encoding="utf-8")

            write_executable(
                splunk_home / "bin" / "splunk",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                command = sys.argv[1] if len(sys.argv) > 1 else ""
                with Path(os.environ["SPLUNK_CMD_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(f"old:{command}\\n")
                if command == "version":
                    sys.stdout.write("Splunk 10.0.0")
                elif command == "status":
                    sys.stdout.write("splunkd is running")
                elif command in {"stop", "start", "restart"}:
                    sys.stdout.write(command)
                raise SystemExit(0)
                """,
            )
            write_executable(
                package_root / "bin" / "splunk",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                command = sys.argv[1] if len(sys.argv) > 1 else ""
                with Path(os.environ["SPLUNK_CMD_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(f"new:{command}\\n")
                if command == "version":
                    sys.stdout.write("Splunk 10.1.0")
                elif command == "status":
                    sys.stdout.write("splunkd is running")
                elif command in {"stop", "start", "restart"}:
                    sys.stdout.write(command)
                raise SystemExit(0)
                """,
            )

            with tarfile.open(package_file, "w:gz") as archive:
                archive.add(package_root, arcname="splunk")

            env = os.environ.copy()
            env.update(
                {
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_LOCAL_SUDO": "false",
                    "SPLUNK_CMD_LOG": str(cmd_log),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "install",
                "--execution", "local",
                "--host-bootstrap-role", "standalone-search-tier",
                "--source", "local",
                "--file", str(package_file),
                "--splunk-home", str(splunk_home),
                "--service-user", current_user,
                "--no-boot-start",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Upgrading Splunk from 10.0.0 to 10.1.0", result.stdout)
            self.assertEqual((splunk_home / "etc/test/default.txt").read_text(encoding="utf-8"), "new-default\n")
            self.assertEqual((splunk_home / "etc/test/local-only.conf").read_text(encoding="utf-8"), "keep-me\n")

            commands = cmd_log.read_text(encoding="utf-8").splitlines()
            self.assertIn("old:version", commands)
            self.assertIn("old:stop", commands)
            self.assertIn("new:start", commands)
            self.assertLess(commands.index("old:stop"), commands.index("new:start"))


    def test_host_bootstrap_install_warns_that_clustered_upgrades_are_per_host_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()
            credentials_file = tmp_path / "credentials"
            package_file = tmp_path / "splunk-10.1.0-linux-x86_64.tgz"
            splunk_home = tmp_path / "cluster-manager"
            package_root = tmp_path / "package-root" / "splunk"

            credentials_file.write_text("", encoding="utf-8")
            (splunk_home / "bin").mkdir(parents=True)
            (package_root / "bin").mkdir(parents=True)

            write_executable(
                splunk_home / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                case "$1" in
                    version) echo "Splunk 10.0.0"; exit 0 ;;
                    status) echo "splunkd is running"; exit 0 ;;
                    stop|start|restart) echo "$1"; exit 0 ;;
                    *) exit 0 ;;
                esac
                """,
            )
            write_executable(
                package_root / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                case "$1" in
                    version) echo "Splunk 10.1.0"; exit 0 ;;
                    status) echo "splunkd is running"; exit 0 ;;
                    stop|start|restart) echo "$1"; exit 0 ;;
                    *) exit 0 ;;
                esac
                """,
            )

            with tarfile.open(package_file, "w:gz") as archive:
                archive.add(package_root, arcname="splunk")

            env = os.environ.copy()
            env.update(
                {
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_LOCAL_SUDO": "false",
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "install",
                "--execution", "local",
                "--host-bootstrap-role", "cluster-manager",
                "--deployment-mode", "clustered",
                "--source", "local",
                "--file", str(package_file),
                "--splunk-home", str(splunk_home),
                "--service-user", current_user,
                "--no-boot-start",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Clustered upgrades are per-host only", result.stdout)


    def test_host_bootstrap_install_upgrades_remote_rpm_without_admin_password(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            remote_root = tmp_path / "remote-root"
            remote_home = remote_root / "opt/splunk"
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()
            credentials_file = tmp_path / "credentials"
            admin_password_file = tmp_path / "admin-password"
            package_file = tmp_path / "splunk-10.1.0-linux-x86_64.rpm"
            cmd_log = tmp_path / "splunk.log"
            install_log = tmp_path / "rpm.log"
            new_splunk = tmp_path / "new-rpm-splunk"

            bin_dir.mkdir()
            (remote_home / "bin").mkdir(parents=True)
            credentials_file.write_text("", encoding="utf-8")
            admin_password_file.write_text("changeme", encoding="utf-8")
            package_file.write_text("rpm-package-placeholder", encoding="utf-8")

            write_remote_shell_mocks(bin_dir)
            write_executable(
                remote_home / "bin" / "splunk",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                command = sys.argv[1] if len(sys.argv) > 1 else ""
                with Path(os.environ["SPLUNK_CMD_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(f"old:{command}\\n")
                if command == "version":
                    sys.stdout.write("Splunk 10.0.0")
                elif command == "status":
                    sys.stdout.write("splunkd is running")
                elif command in {"stop", "start", "restart"}:
                    sys.stdout.write(command)
                raise SystemExit(0)
                """,
            )
            write_executable(
                new_splunk,
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                command = sys.argv[1] if len(sys.argv) > 1 else ""
                with Path(os.environ["SPLUNK_CMD_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(f"new:{command}\\n")
                if command == "version":
                    sys.stdout.write("Splunk 10.1.0")
                elif command == "status":
                    sys.stdout.write("splunkd is running")
                elif command in {"stop", "start", "restart"}:
                    sys.stdout.write(command)
                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "rpm",
                f"""\
                #!/usr/bin/env bash
                printf '%s\\n' "$*" >> "{install_log}"
                install -m 755 "{new_splunk}" "${{REMOTE_ROOT}}/opt/splunk/bin/splunk"
                """,
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "REMOTE_ROOT": str(remote_root),
                    "SPLUNK_CMD_LOG": str(cmd_log),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_SSH_HOST": "idx01.example.com",
                    "SPLUNK_SSH_PORT": "22",
                    "SPLUNK_SSH_USER": current_user,
                    "SPLUNK_SSH_PASS": "ssh-password",
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "install",
                "--execution", "ssh",
                "--host-bootstrap-role", "standalone-search-tier",
                "--source", "local",
                "--file", str(package_file),
                "--package-type", "rpm",
                "--advertise-host", "idx01.example.com",
                "--service-user", current_user,
                "--admin-password-file", str(admin_password_file),
                "--no-boot-start",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Upgrading Splunk from 10.0.0 to 10.1.0", result.stdout)
            self.assertIn("-Uvh", install_log.read_text(encoding="utf-8"))

            commands = cmd_log.read_text(encoding="utf-8").splitlines()
            self.assertIn("old:stop", commands)
            self.assertIn("new:start", commands)


    def test_host_bootstrap_install_upgrades_remote_deb_without_admin_password(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            remote_root = tmp_path / "remote-root"
            remote_home = remote_root / "opt/splunk"
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()
            credentials_file = tmp_path / "credentials"
            admin_password_file = tmp_path / "admin-password"
            package_file = tmp_path / "splunk-10.1.0-linux-amd64.deb"
            cmd_log = tmp_path / "splunk.log"
            install_log = tmp_path / "dpkg.log"
            new_splunk = tmp_path / "new-deb-splunk"

            bin_dir.mkdir()
            (remote_home / "bin").mkdir(parents=True)
            credentials_file.write_text("", encoding="utf-8")
            admin_password_file.write_text("changeme", encoding="utf-8")
            package_file.write_text("deb-package-placeholder", encoding="utf-8")

            write_remote_shell_mocks(bin_dir)
            write_executable(
                remote_home / "bin" / "splunk",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                command = sys.argv[1] if len(sys.argv) > 1 else ""
                with Path(os.environ["SPLUNK_CMD_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(f"old:{command}\\n")
                if command == "version":
                    sys.stdout.write("Splunk 10.0.0")
                elif command == "status":
                    sys.stdout.write("splunkd is running")
                elif command in {"stop", "start", "restart"}:
                    sys.stdout.write(command)
                raise SystemExit(0)
                """,
            )
            write_executable(
                new_splunk,
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                command = sys.argv[1] if len(sys.argv) > 1 else ""
                with Path(os.environ["SPLUNK_CMD_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(f"new:{command}\\n")
                if command == "version":
                    sys.stdout.write("Splunk 10.1.0")
                elif command == "status":
                    sys.stdout.write("splunkd is running")
                elif command in {"stop", "start", "restart"}:
                    sys.stdout.write(command)
                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "dpkg",
                f"""\
                #!/usr/bin/env bash
                printf '%s\\n' "$*" >> "{install_log}"
                install -m 755 "{new_splunk}" "${{REMOTE_ROOT}}/opt/splunk/bin/splunk"
                """,
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "REMOTE_ROOT": str(remote_root),
                    "SPLUNK_CMD_LOG": str(cmd_log),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_SSH_HOST": "sh01.example.com",
                    "SPLUNK_SSH_PORT": "22",
                    "SPLUNK_SSH_USER": current_user,
                    "SPLUNK_SSH_PASS": "ssh-password",
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "install",
                "--execution", "ssh",
                "--host-bootstrap-role", "standalone-search-tier",
                "--source", "local",
                "--file", str(package_file),
                "--package-type", "deb",
                "--advertise-host", "sh01.example.com",
                "--service-user", current_user,
                "--admin-password-file", str(admin_password_file),
                "--no-boot-start",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Upgrading Splunk from 10.0.0 to 10.1.0", result.stdout)
            self.assertIn("-i", install_log.read_text(encoding="utf-8"))

            commands = cmd_log.read_text(encoding="utf-8").splitlines()
            self.assertIn("old:stop", commands)
            self.assertIn("new:start", commands)


    def test_host_bootstrap_install_remote_deb_reports_noninteractive_sudo_requirement(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            remote_root = tmp_path / "remote-root"
            remote_home = remote_root / "opt/splunk"
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()
            credentials_file = tmp_path / "credentials"
            package_file = tmp_path / "splunk-10.1.0-linux-amd64.deb"

            bin_dir.mkdir()
            (remote_home / "bin").mkdir(parents=True)
            credentials_file.write_text("", encoding="utf-8")
            package_file.write_text("deb-package-placeholder", encoding="utf-8")

            write_remote_shell_mocks(bin_dir)
            write_executable(
                remote_home / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                case "$1" in
                    version) echo "Splunk 10.0.0"; exit 0 ;;
                    status) echo "splunkd is running"; exit 0 ;;
                    stop|start|restart) echo "$1"; exit 0 ;;
                    *) exit 0 ;;
                esac
                """,
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "REMOTE_ROOT": str(remote_root),
                    "REMOTE_SUDO_MODE": "require_stdin",
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_SSH_HOST": "sh01.example.com",
                    "SPLUNK_SSH_PORT": "22",
                    "SPLUNK_SSH_USER": current_user,
                    "SPLUNK_SSH_PASS": "ssh-password",
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "install",
                "--execution", "ssh",
                "--host-bootstrap-role", "standalone-search-tier",
                "--source", "local",
                "--file", str(package_file),
                "--package-type", "deb",
                "--advertise-host", "sh01.example.com",
                "--service-user", current_user,
                "--no-boot-start",
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            combined = result.stdout + result.stderr
            self.assertTrue(
                "either use the -S option" in combined
                or "a password is required" in combined,
                msg=combined,
            )


    def test_host_bootstrap_configure_heavy_forwarder_does_not_require_admin_password(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            splunk_home = tmp_path / "splunk"
            (splunk_home / "bin").mkdir(parents=True)
            credentials_file = tmp_path / "credentials"
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()

            credentials_file.write_text("", encoding="utf-8")

            write_executable(
                bin_dir / "sudo",
                """\
                #!/usr/bin/env bash
                exec "$@"
                """,
            )
            write_executable(
                splunk_home / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                case "$1" in
                    status) echo "splunkd is running"; exit 0 ;;
                    restart|start) exit 0 ;;
                    *) exit 0 ;;
                esac
                """,
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_LOCAL_SUDO": "false",
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "configure",
                "--execution", "local",
                "--host-bootstrap-role", "heavy-forwarder",
                "--splunk-home", str(splunk_home),
                "--service-user", current_user,
                "--server-list", "idx01.example.com:9997",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            outputs_conf = (splunk_home / "etc/system/local/outputs.conf").read_text(encoding="utf-8")
            self.assertIn("server = idx01.example.com:9997", outputs_conf)


    def test_host_bootstrap_cluster_manager_does_not_require_admin_password(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            splunk_home = tmp_path / "splunk"
            (splunk_home / "bin").mkdir(parents=True)
            credentials_file = tmp_path / "credentials"
            idxc_secret_file = tmp_path / "idxc_secret"
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()

            credentials_file.write_text("", encoding="utf-8")
            idxc_secret_file.write_text("idxc-secret\n", encoding="utf-8")

            write_executable(
                bin_dir / "sudo",
                """\
                #!/usr/bin/env bash
                exec "$@"
                """,
            )
            write_executable(
                splunk_home / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                case "$1" in
                    status) echo "splunkd is running"; exit 0 ;;
                    restart|start) exit 0 ;;
                    *) exit 0 ;;
                esac
                """,
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_LOCAL_SUDO": "false",
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "cluster",
                "--execution", "local",
                "--deployment-mode", "clustered",
                "--host-bootstrap-role", "cluster-manager",
                "--splunk-home", str(splunk_home),
                "--service-user", current_user,
                "--idxc-secret-file", str(idxc_secret_file),
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            server_conf = (splunk_home / "etc/system/local/server.conf").read_text(encoding="utf-8")
            self.assertIn("mode = manager", server_conf)


    def test_host_bootstrap_download_without_url_resolves_latest_official_tgz_and_verifies_sha512(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            curl_log = tmp_path / "curl.log"
            mock_state_file = tmp_path / "mock-curl-state.json"
            package_name = "splunk-10.2.1-c892b66d163d-linux-amd64.tgz"
            old_package_name = "splunk-10.1.0-abcdef123456-linux-amd64.tgz"
            package_url = f"https://download.splunk.com/products/splunk/releases/10.2.1/linux/{package_name}"
            old_package_url = f"https://download.splunk.com/products/splunk/releases/10.1.0/linux/{old_package_name}"
            sha_url = f"{package_url}.sha512"
            old_sha_url = f"{old_package_url}.sha512"
            package_content = "tgz-package"
            metadata_path = REPO_ROOT / "splunk-ta" / ".latest-splunk-enterprise-tgz.json"
            package_path = REPO_ROOT / "splunk-ta" / package_name

            self.addCleanup(lambda: package_path.unlink(missing_ok=True))
            self.addCleanup(lambda: metadata_path.unlink(missing_ok=True))

            credentials_file.write_text("", encoding="utf-8")
            write_mock_curl(bin_dir / "curl")
            mock_state_file.write_text(
                json.dumps(
                    {
                        "text": {
                            "https://www.splunk.com/en_us/download/splunk-enterprise.html": textwrap.dedent(
                                f"""\
                                Splunk Enterprise 10.2.1
                                wget -O {old_package_name} "{old_package_url}"
                                {old_package_url}
                                {old_sha_url}
                                wget -O {package_name} "{package_url}"
                                {package_url}
                                {sha_url}
                                """
                            ),
                            sha_url: f"{sha512_hex(package_content)}  {package_name}\n",
                            old_sha_url: f"{sha512_hex('older-package')}  {old_package_name}\n",
                        },
                        "files": {
                            package_url: package_content,
                        },
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "CURL_LOG": str(curl_log),
                    "MOCK_CURL_STATE": str(mock_state_file),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "download",
                "--execution", "local",
                "--source", "auto",
                "--package-type", "tgz",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Resolved latest Splunk Enterprise 10.2.1 package", result.stdout)
            self.assertIn("Verifying", result.stdout)
            self.assertTrue(package_path.exists())
            self.assertTrue(metadata_path.exists())

            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["version"], "10.2.1")
            self.assertEqual(metadata["package_url"], package_url)
            self.assertEqual(metadata["sha512"], sha512_hex(package_content))

            curl_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn("https://www.splunk.com/en_us/download/splunk-enterprise.html", curl_requests)
            self.assertIn(package_url, curl_requests)
            self.assertIn(sha_url, curl_requests)
            self.assertNotIn(old_package_url, curl_requests)


    def test_host_bootstrap_download_without_url_resolves_latest_official_deb_when_requested(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            curl_log = tmp_path / "curl.log"
            mock_state_file = tmp_path / "mock-curl-state.json"
            package_name = "splunk-10.2.1-c892b66d163d-linux-amd64.deb"
            package_url = f"https://download.splunk.com/products/splunk/releases/10.2.1/linux/{package_name}"
            sha_url = f"{package_url}.sha512"
            package_content = "deb-package"
            package_path = REPO_ROOT / "splunk-ta" / package_name
            metadata_path = REPO_ROOT / "splunk-ta" / ".latest-splunk-enterprise-deb.json"

            self.addCleanup(lambda: package_path.unlink(missing_ok=True))
            self.addCleanup(lambda: metadata_path.unlink(missing_ok=True))

            credentials_file.write_text("", encoding="utf-8")
            write_mock_curl(bin_dir / "curl")
            mock_state_file.write_text(
                json.dumps(
                    {
                        "text": {
                            "https://www.splunk.com/en_us/download/splunk-enterprise.html": textwrap.dedent(
                                f"""\
                                Splunk Enterprise 10.2.1
                                wget -O {package_name} "{package_url}"
                                {package_url}
                                {sha_url}
                                """
                            ),
                            sha_url: f"{sha512_hex(package_content)}  {package_name}\n",
                        },
                        "files": {
                            package_url: package_content,
                        },
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "CURL_LOG": str(curl_log),
                    "MOCK_CURL_STATE": str(mock_state_file),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "download",
                "--execution", "local",
                "--source", "remote",
                "--package-type", "deb",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Resolved latest Splunk Enterprise 10.2.1 package", result.stdout)
            self.assertTrue(package_path.exists())
            self.assertTrue(metadata_path.exists())

            curl_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn("https://www.splunk.com/en_us/download/splunk-enterprise.html", curl_requests)
            self.assertIn(package_url, curl_requests)
            self.assertIn(sha_url, curl_requests)


    def test_host_bootstrap_download_without_url_auto_selects_deb_from_remote_target_os(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            curl_log = tmp_path / "curl.log"
            mock_state_file = tmp_path / "mock-curl-state.json"
            package_name = "splunk-10.2.1-c892b66d163d-linux-amd64.deb"
            package_url = f"https://download.splunk.com/products/splunk/releases/10.2.1/linux/{package_name}"
            sha_url = f"{package_url}.sha512"
            package_path = REPO_ROOT / "splunk-ta" / package_name
            metadata_path = REPO_ROOT / "splunk-ta" / ".latest-splunk-enterprise-deb.json"

            self.addCleanup(lambda: package_path.unlink(missing_ok=True))
            self.addCleanup(lambda: metadata_path.unlink(missing_ok=True))

            credentials_file.write_text("", encoding="utf-8")
            write_mock_curl(bin_dir / "curl")
            write_executable(
                bin_dir / "sshpass",
                """\
                #!/usr/bin/env bash
                shift 2
                exec "$@"
                """,
            )
            write_executable(
                bin_dir / "ssh",
                """\
                #!/usr/bin/env bash
                printf 'ID=ubuntu\nID_LIKE=debian\n'
                """,
            )
            mock_state_file.write_text(
                json.dumps(
                    {
                        "text": {
                            "https://www.splunk.com/en_us/download/splunk-enterprise.html": textwrap.dedent(
                                f"""\
                                Splunk Enterprise 10.2.1
                                wget -O {package_name} "{package_url}"
                                {package_url}
                                {sha_url}
                                """
                            ),
                            sha_url: f"{sha512_hex('deb-package-remote')}  {package_name}\n",
                        },
                        "files": {
                            package_url: "deb-package-remote",
                        },
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "CURL_LOG": str(curl_log),
                    "MOCK_CURL_STATE": str(mock_state_file),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_SSH_HOST": "cm01.example.com",
                    "SPLUNK_SSH_USER": "splunk",
                    "SPLUNK_SSH_PASS": "ssh-password",
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "download",
                "--execution", "ssh",
                "--source", "remote",
                "--package-type", "auto",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Auto-selected deb", result.stdout)
            self.assertIn("Resolved latest Splunk Enterprise 10.2.1 package", result.stdout)
            self.assertTrue(package_path.exists())


    def test_host_bootstrap_download_without_url_fails_when_page_version_disagrees_with_package_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            mock_state_file = tmp_path / "mock-curl-state.json"
            package_name = "splunk-10.1.0-abcdef123456-linux-amd64.tgz"
            package_url = f"https://download.splunk.com/products/splunk/releases/10.1.0/linux/{package_name}"
            sha_url = f"{package_url}.sha512"

            credentials_file.write_text("", encoding="utf-8")
            write_mock_curl(bin_dir / "curl")
            mock_state_file.write_text(
                json.dumps(
                    {
                        "text": {
                            "https://www.splunk.com/en_us/download/splunk-enterprise.html": textwrap.dedent(
                                f"""\
                                Splunk Enterprise 10.2.1
                                wget -O {package_name} "{package_url}"
                                {package_url}
                                {sha_url}
                                """
                            ),
                            sha_url: f"{sha512_hex('bad-package')}  {package_name}\n",
                        },
                        "files": {
                            package_url: "bad-package",
                        },
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "MOCK_CURL_STATE": str(mock_state_file),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "download",
                "--execution", "local",
                "--source", "remote",
                "--package-type", "tgz",
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Failed to resolve the latest official Splunk Enterprise tgz package", result.stdout + result.stderr)


    def test_host_bootstrap_download_without_url_can_use_stale_latest_metadata_when_allowed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            curl_log = tmp_path / "curl.log"
            mock_state_file = tmp_path / "mock-curl-state.json"
            package_name = "splunk-10.2.1-c892b66d163d-linux-amd64.tgz"
            package_url = f"https://download.splunk.com/products/splunk/releases/10.2.1/linux/{package_name}"
            sha_url = f"{package_url}.sha512"
            package_content = "stale-tgz-package"
            package_path = REPO_ROOT / "splunk-ta" / package_name
            metadata_path = REPO_ROOT / "splunk-ta" / ".latest-splunk-enterprise-tgz.json"

            self.addCleanup(lambda: package_path.unlink(missing_ok=True))
            self.addCleanup(lambda: metadata_path.unlink(missing_ok=True))

            credentials_file.write_text("", encoding="utf-8")
            metadata_path.write_text(
                json.dumps(
                    {
                        "cached_at": "2026-03-22T00:00:00Z",
                        "cached_at_epoch": int(time.time()),
                        "package_type": "tgz",
                        "package_url": package_url,
                        "sha512": sha512_hex(package_content),
                        "sha512_url": sha_url,
                        "source_page_url": "https://www.splunk.com/en_us/download/splunk-enterprise.html",
                        "version": "10.2.1",
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            write_mock_curl(bin_dir / "curl")
            mock_state_file.write_text(
                json.dumps(
                    {
                        "fail": [
                            "https://www.splunk.com/en_us/download/splunk-enterprise.html",
                        ],
                        "files": {
                            package_url: package_content,
                        },
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "CURL_LOG": str(curl_log),
                    "MOCK_CURL_STATE": str(mock_state_file),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "download",
                "--execution", "local",
                "--source", "remote",
                "--package-type", "tgz",
                "--allow-stale-latest",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("attempting stale metadata fallback", result.stdout)
            self.assertTrue(package_path.exists())
            curl_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn("https://www.splunk.com/en_us/download/splunk-enterprise.html", curl_requests)
            self.assertIn(package_url, curl_requests)
            self.assertNotIn(sha_url, curl_requests)


    def test_host_bootstrap_download_without_url_fails_without_allow_stale_latest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            mock_state_file = tmp_path / "mock-curl-state.json"

            credentials_file.write_text("", encoding="utf-8")
            write_mock_curl(bin_dir / "curl")
            mock_state_file.write_text(
                json.dumps(
                    {
                        "fail": [
                            "https://www.splunk.com/en_us/download/splunk-enterprise.html",
                        ],
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "MOCK_CURL_STATE": str(mock_state_file),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "download",
                "--execution", "local",
                "--source", "remote",
                "--package-type", "tgz",
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--allow-stale-latest", result.stdout + result.stderr)


    def test_host_bootstrap_download_without_url_rejects_stale_metadata_older_than_30_days(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            mock_state_file = tmp_path / "mock-curl-state.json"
            package_name = "splunk-10.2.1-c892b66d163d-linux-amd64.tgz"
            package_url = f"https://download.splunk.com/products/splunk/releases/10.2.1/linux/{package_name}"
            metadata_path = REPO_ROOT / "splunk-ta" / ".latest-splunk-enterprise-tgz.json"

            self.addCleanup(lambda: metadata_path.unlink(missing_ok=True))

            credentials_file.write_text("", encoding="utf-8")
            metadata_path.write_text(
                json.dumps(
                    {
                        "cached_at": "2026-01-01T00:00:00Z",
                        "cached_at_epoch": int(time.time()) - (31 * 24 * 60 * 60),
                        "package_type": "tgz",
                        "package_url": package_url,
                        "sha512": sha512_hex("stale-package"),
                        "sha512_url": f"{package_url}.sha512",
                        "source_page_url": "https://www.splunk.com/en_us/download/splunk-enterprise.html",
                        "version": "10.2.1",
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            write_mock_curl(bin_dir / "curl")
            mock_state_file.write_text(
                json.dumps(
                    {
                        "fail": [
                            "https://www.splunk.com/en_us/download/splunk-enterprise.html",
                        ],
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "MOCK_CURL_STATE": str(mock_state_file),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "download",
                "--execution", "local",
                "--source", "remote",
                "--package-type", "tgz",
                "--allow-stale-latest",
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("older than 30 days", result.stdout + result.stderr)


    def test_host_bootstrap_smoke_latest_resolution_checks_live_metadata_without_downloading_package(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            curl_log = tmp_path / "curl.log"
            mock_state_file = tmp_path / "mock-curl-state.json"
            package_name = "splunk-10.2.1-c892b66d163d-linux-amd64.tgz"
            package_url = f"https://download.splunk.com/products/splunk/releases/10.2.1/linux/{package_name}"
            sha_url = f"{package_url}.sha512"
            package_path = REPO_ROOT / "splunk-ta" / package_name
            metadata_path = REPO_ROOT / "splunk-ta" / ".latest-splunk-enterprise-tgz.json"

            package_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            self.addCleanup(lambda: package_path.unlink(missing_ok=True))
            self.addCleanup(lambda: metadata_path.unlink(missing_ok=True))

            credentials_file.write_text("", encoding="utf-8")
            write_mock_curl(bin_dir / "curl")
            mock_state_file.write_text(
                json.dumps(
                    {
                        "text": {
                            "https://www.splunk.com/en_us/download/splunk-enterprise.html": textwrap.dedent(
                                f"""\
                                <h1>Splunk Enterprise 10.2.1</h1>
                                <a data-link="{package_url}" data-wget='wget -O {package_name} &#34;{package_url}&#34;' data-sha512="{sha_url}" data-version="10.2.1" href="#">
                                  Download Now
                                </a>
                                """
                            ),
                            sha_url: f"{sha512_hex('smoke-only')}  {package_name}\n",
                        },
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "CURL_LOG": str(curl_log),
                    "MOCK_CURL_STATE": str(mock_state_file),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/smoke_latest_resolution.sh",
                "--package-type", "tgz",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Smoke check passed for tgz (live)", result.stdout)
            self.assertIn(package_url, result.stdout)
            self.assertIn(sha_url, result.stdout)
            self.assertFalse(package_path.exists())
            self.assertFalse(metadata_path.exists())

            curl_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn("https://www.splunk.com/en_us/download/splunk-enterprise.html", curl_requests)
            self.assertIn(sha_url, curl_requests)
            self.assertNotIn(package_url + "\n", curl_requests)


if __name__ == "__main__":
    unittest.main()
