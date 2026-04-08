#!/usr/bin/env python3
"""Regression tests for Cisco TA shell scripts."""

import getpass
import json
import os
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.regression_helpers import (
    REPO_ROOT,
    ShellScriptRegressionBase,
    write_executable,
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
            self.assertEqual(
                setup_result.returncode,
                0,
                msg=setup_result.stdout + setup_result.stderr,
            )
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
            self.assertEqual(
                syslog_result.returncode,
                0,
                msg=syslog_result.stdout + syslog_result.stderr,
            )
            self.assertIn(
                "Configuring Cisco Secure Firewall Syslog via secure_firewall_syslog",
                syslog_result.stdout,
            )

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
            self.assertIn(
                "Configuring Cisco Identity Intelligence Webhook via cii_webhook",
                cii_result.stdout,
            )

            validate_result = self.run_script(
                "skills/cisco-security-cloud-setup/scripts/validate.sh",
                env=env,
            )
            self.assertEqual(
                validate_result.returncode,
                0,
                msg=validate_result.stdout + validate_result.stderr,
            )
            self.assertIn(
                "At least one Cisco Security Cloud input is configured",
                validate_result.stdout,
            )

            validate_xdr_result = self.run_script(
                "skills/cisco-security-cloud-setup/scripts/validate.sh",
                "--product",
                "xdr",
                "--name",
                "XDR_Default",
                env=env,
            )
            self.assertEqual(
                validate_xdr_result.returncode,
                0,
                msg=validate_xdr_result.stdout + validate_xdr_result.stderr,
            )
            self.assertIn("sbg_xdr_input 'XDR_Default' is configured", validate_xdr_result.stdout)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["security_cloud_settings"]["loglevel"], "DEBUG")
            self.assertIn("cisco_xdr", state["indexes"])
            self.assertIn("cisco_sfw_ftd_syslog", state["indexes"])
            self.assertIn("cisco_cii", state["indexes"])
            self.assertIn(
                "XDR_Default",
                state["security_cloud_handlers"]["CiscoSecurityCloud_sbg_xdr_input"],
            )
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
            self.assertEqual(
                setup_result.returncode,
                0,
                msg=setup_result.stdout + setup_result.stderr,
            )
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
            self.assertEqual(
                account_result.returncode,
                0,
                msg=account_result.stdout + account_result.stderr,
            )
            self.assertIn("Discovered org ID: org-123", account_result.stdout)
            self.assertIn(
                "Created Cisco Secure Access org account 'org-123'.",
                account_result.stdout,
            )

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
            self.assertEqual(
                settings_result.returncode,
                0,
                msg=settings_result.stdout + settings_result.stderr,
            )
            self.assertIn("Bootstrapped Cisco Secure Access roles.", settings_result.stdout)
            self.assertIn("Recorded Secure Access terms acceptance", settings_result.stdout)
            self.assertIn(
                "Updated Cisco Secure Access app settings for org 'org-123'.",
                settings_result.stdout,
            )

            validate_result = self.run_script(
                "skills/cisco-secure-access-setup/scripts/validate.sh",
                "--org-id",
                "org-123",
                env=env,
            )
            self.assertEqual(
                validate_result.returncode,
                0,
                msg=validate_result.stdout + validate_result.stderr,
            )
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
                any("--app-id 5558" in line for line in install_lines),
                msg="Cisco Secure Access install was not invoked through the shared installer",
            )
            self.assertTrue(curl_log.exists(), msg="Expected mock curl log to be written")

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
            self.assertEqual(
                validate_result.returncode,
                0,
                msg=validate_result.stdout + validate_result.stderr,
            )
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
                splunk_home / "etc" / "manager-apps" / "ZZZ_cisco_skills_hec" / "local" / "inputs.conf"
            ).read_text(encoding="utf-8")
            self.assertIn("[http://thousandeyes]", inputs_conf)
            self.assertIn("index = thousandeyes_metrics", inputs_conf)
            self.assertIn(
                "indexes = thousandeyes_metrics,thousandeyes_traces,thousandeyes_events,thousandeyes_activity,thousandeyes_alerts,thousandeyes_pathvis",
                inputs_conf,
            )
            self.assertIn(
                "apply cluster-bundle -auth cm-user:cm-pass",
                apply_log.read_text(encoding="utf-8"),
            )
            self.assertNotIn("/services/data/inputs/http", curl_log.read_text(encoding="utf-8"))

    def test_thousandeyes_setup_enables_path_visualization_by_default(self):
        script_text = (REPO_ROOT / "skills/cisco-thousandeyes-setup/scripts/setup.sh").read_text(encoding="utf-8")

        self.assertIn("PATHVIS_ENABLED=true", script_text)
        self.assertIn('related_paths "1"', script_text)
        self.assertIn("--no-pathvis", script_text)
        self.assertIn("--hec-url", script_text)

    def test_thousandeyes_configure_account_avoids_eval_for_network_data(self):
        script_text = (REPO_ROOT / "skills/cisco-thousandeyes-setup/scripts/configure_account.sh").read_text(
            encoding="utf-8"
        )

        self.assertNotIn('eval "$(parse_device_authorization_response', script_text)
        self.assertNotIn('eval "$(parse_token_success_response', script_text)
        self.assertNotIn('eval "$(parse_token_error_response', script_text)

    def test_catalyst_configure_account_no_verify_ssl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, curl_log = self._build_configure_account_env(tmp_path)
            password_file = tmp_path / "device_password"

            result = self.run_script(
                "skills/cisco-catalyst-ta-setup/scripts/configure_account.sh",
                "--type",
                "catalyst_center",
                "--name",
                "TestDNAC",
                "--host",
                "https://10.100.0.60",
                "--username",
                "admin",
                "--password-file",
                str(password_file),
                "--no-verify-ssl",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("verify_ssl=False", result.stdout)
            self.assertIn("ta_cisco_catalyst_settings", result.stdout)

            log_text = curl_log.read_text(encoding="utf-8")
            settings_posts = [
                line for line in log_text.splitlines() if "CONF_POST" in line and "ta_cisco_catalyst_settings" in line
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
                "--type",
                "aci",
                "--name",
                "TestACI",
                "--hostname",
                "10.0.0.1",
                "--username",
                "admin",
                "--password-file",
                str(password_file),
                "--no-verify-ssl",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("verify_ssl=False", result.stdout)
            self.assertIn("cisco_dc_networking_app_for_splunk_settings", result.stdout)

            log_text = curl_log.read_text(encoding="utf-8")
            settings_posts = [
                line
                for line in log_text.splitlines()
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
            conf_posts = [line for line in log_text.splitlines() if "CONF_POST" in line]
            self.assertGreaterEqual(
                len(conf_posts),
                2,
                msg=f"Expected settings and account POSTs, got: {conf_posts}",
            )
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
                "--type",
                "catalyst_center",
                "--name",
                "TestDNAC",
                "--host",
                "https://10.100.0.60",
                "--username",
                "admin",
                "--password-file",
                str(password_file),
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertNotIn("verify_ssl", result.stdout)

            log_text = curl_log.read_text(encoding="utf-8")
            settings_posts = [
                line for line in log_text.splitlines() if "CONF_POST" in line and "ta_cisco_catalyst_settings" in line
            ]
            self.assertEqual(
                len(settings_posts),
                0,
                msg="Should not POST to settings conf when --no-verify-ssl is not passed",
            )

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

    # ------------------------------------------------------------------
    # Integration tests for lightly-covered skills
    # ------------------------------------------------------------------

    def test_itsi_validate_reports_missing_core_app(self):
        """splunk-itsi-setup: validate.sh reports failure when SA-ITOA is absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _secrets, _state, _install, _curl = self.build_mock_cisco_skill_env(tmp_path)

            result = self.run_script(
                "skills/splunk-itsi-setup/scripts/validate.sh",
                env=env,
            )
            self.assertNotEqual(
                result.returncode,
                0,
                msg="validate.sh should fail when ITSI is not installed",
            )
            self.assertIn("ITSI", result.stdout)
            self.assertIn("SA-ITOA", result.stdout)

    def test_itsi_validate_passes_when_apps_installed(self):
        """splunk-itsi-setup: validate.sh passes when core apps are present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _secrets, state_file, _install, _curl = self.build_mock_cisco_skill_env(tmp_path)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            for app in ("SA-ITOA", "itsi", "SA-UserAccess", "SA-ITSI-Licensechecker"):
                state["installed_apps"][app] = {"version": "4.19.0"}
            state_file.write_text(json.dumps(state), encoding="utf-8")

            result = self.run_script(
                "skills/splunk-itsi-setup/scripts/validate.sh",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("SA-ITOA installed", result.stdout)
            self.assertIn("KVStore", result.stdout)

    def test_appdynamics_configure_account_requires_mandatory_flags(self):
        """cisco-appdynamics-setup: configure_account.sh fails without required flags."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _secrets, _state, _install, _curl = self.build_mock_cisco_skill_env(tmp_path)

            result = self.run_script(
                "skills/cisco-appdynamics-setup/scripts/configure_account.sh",
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--name", result.stdout + result.stderr)

    def test_appdynamics_configure_account_smoke(self):
        """cisco-appdynamics-setup: configure_account.sh creates account with all flags."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, secrets_dir, state_file, _install, _curl = self.build_mock_cisco_skill_env(tmp_path)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["installed_apps"]["Splunk_TA_AppDynamics"] = {"version": "3.0.0"}
            state_file.write_text(json.dumps(state), encoding="utf-8")

            secret_file = secrets_dir / "appd_secret"
            secret_file.write_text("test-client-secret", encoding="utf-8")

            result = self.run_script(
                "skills/cisco-appdynamics-setup/scripts/configure_account.sh",
                "--name",
                "my_controller",
                "--controller-url",
                "https://appd.example.com",
                "--client-name",
                "splunk_client",
                "--client-secret-file",
                str(secret_file),
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("AppDynamics controller connection", result.stdout)

    def test_appdynamics_configure_analytics_requires_mandatory_flags(self):
        """cisco-appdynamics-setup: configure_analytics.sh fails without required flags."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _secrets, _state, _install, _curl = self.build_mock_cisco_skill_env(tmp_path)

            result = self.run_script(
                "skills/cisco-appdynamics-setup/scripts/configure_analytics.sh",
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--name", result.stdout + result.stderr)

    def test_intersight_configure_account_requires_mandatory_flags(self):
        """cisco-intersight-setup: configure_account.sh fails without required flags."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _secrets, _state, _install, _curl = self.build_mock_cisco_skill_env(tmp_path)

            result = self.run_script(
                "skills/cisco-intersight-setup/scripts/configure_account.sh",
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--name", result.stdout + result.stderr)

    def test_intersight_configure_account_smoke(self):
        """cisco-intersight-setup: configure_account.sh creates account with all flags."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, secrets_dir, state_file, _install, _curl = self.build_mock_cisco_skill_env(tmp_path)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["installed_apps"]["Splunk_TA_Cisco_Intersight"] = {"version": "2.0.0"}
            state_file.write_text(json.dumps(state), encoding="utf-8")

            secret_file = secrets_dir / "intersight_secret"
            secret_file.write_text("test-client-secret", encoding="utf-8")

            result = self.run_script(
                "skills/cisco-intersight-setup/scripts/configure_account.sh",
                "--name",
                "my_intersight",
                "--client-id",
                "test-client-id",
                "--client-secret-file",
                str(secret_file),
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Intersight account", result.stdout)

    def test_enterprise_networking_setup_requires_app(self):
        """cisco-enterprise-networking-setup: setup.sh fails when app is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _secrets, _state, _install, _curl = self.build_mock_cisco_skill_env(tmp_path)

            result = self.run_script(
                "skills/cisco-enterprise-networking-setup/scripts/setup.sh",
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not found", result.stdout + result.stderr)

    def test_enterprise_networking_setup_updates_macros(self):
        """cisco-enterprise-networking-setup: setup.sh updates index macros."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _secrets, state_file, _install, _curl = self.build_mock_cisco_skill_env(tmp_path)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["installed_apps"]["cisco-catalyst-app"] = {"version": "1.0.0"}
            state["installed_apps"]["TA_cisco_catalyst"] = {"version": "3.0.0"}
            state_file.write_text(json.dumps(state), encoding="utf-8")

            result = self.run_script(
                "skills/cisco-enterprise-networking-setup/scripts/setup.sh",
                "--macros-only",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("cisco_catalyst_app_index", result.stdout)
            self.assertIn("Macro update complete", result.stdout)

    def test_enhanced_netflow_setup_rejects_cloud(self):
        """cisco-catalyst-enhanced-netflow-setup: setup.sh rejects Cloud target."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _secrets, _state, _install, _curl = self.build_mock_cisco_skill_env(tmp_path)
            env["SPLUNK_PLATFORM"] = "cloud"

            result = self.run_script(
                "skills/cisco-catalyst-enhanced-netflow-setup/scripts/setup.sh",
                "--install",
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("forwarder", result.stdout.lower() + result.stderr.lower())

    def test_enhanced_netflow_setup_reports_status(self):
        """cisco-catalyst-enhanced-netflow-setup: setup.sh reports not-installed when absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _secrets, state_file, _install, _curl = self.build_mock_cisco_skill_env(tmp_path)
            env["SPLUNK_PLATFORM"] = "enterprise"

            result = self.run_script(
                "skills/cisco-catalyst-enhanced-netflow-setup/scripts/setup.sh",
                env=env,
            )
            self.assertNotEqual(
                result.returncode,
                0,
                msg="setup.sh should fail when the add-on is not installed",
            )
            self.assertIn("not installed", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
