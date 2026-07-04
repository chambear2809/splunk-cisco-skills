"""Regression tests for the continuous live validation runner."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.regression_helpers import REPO_ROOT


RUNNER_PATH = REPO_ROOT / "skills/splunk-admin-doctor/scripts/live_validate_all.py"

spec = importlib.util.spec_from_file_location("splunk_live_validation", RUNNER_PATH)
runner = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


class LiveValidationRunnerTests(unittest.TestCase):
    def test_profile_metadata_uses_json_encoder_not_shell_interpolation(self) -> None:
        script = runner.SPLUNK_PROFILE_METADATA_SCRIPT
        self.assertIn("json.dumps", script)
        self.assertIn('os.environ.get("SPLUNK_PROFILE"', script)
        self.assertNotIn('"profile": "${SPLUNK_PROFILE', script)
        self.assertNotIn("cat <<EOF", script)
        self.assertLess(
            script.index("cannot securely open credential file"),
            script.index("_list_credential_profiles_from_file"),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "profile-probe.sh"
            script_path.write_text(script, encoding="utf-8")
            syntax = subprocess.run(
                ["bash", "-n", str(script_path)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_profile_metadata_requires_an_exact_named_profile_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            credential_file = Path(tmpdir) / "credentials"
            credential_file.write_text(
                "\n".join(
                    (
                        "PROFILE_exact__SPLUNK_PLATFORM=cloud",
                        "PROFILE_exact__SPLUNK_URI=https://splunk.example.test:8089",
                        "PROFILE_exact__SPLUNK_VERIFY_SSL=true",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            credential_file.chmod(0o600)
            env = os.environ.copy()
            env.update(
                {
                    "SPLUNK_CREDENTIALS_FILE": str(credential_file),
                    "SPLUNK_PROFILE": "exact",
                }
            )
            exact = subprocess.run(
                ["bash", "-c", runner.SPLUNK_PROFILE_METADATA_SCRIPT, "profile-probe", "false"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            env["SPLUNK_PROFILE"] = "missing"
            missing = subprocess.run(
                ["bash", "-c", runner.SPLUNK_PROFILE_METADATA_SCRIPT, "profile-probe", "false"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(exact.returncode, 0, exact.stderr)
        self.assertEqual(json.loads(exact.stdout)["profile"], "exact")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("does not exist", missing.stderr)

    def test_flat_credentials_require_the_explicit_compatibility_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            credential_file = Path(tmpdir) / "credentials"
            credential_file.write_text(
                "SPLUNK_PLATFORM=cloud\n"
                "SPLUNK_URI=https://splunk.example.test:8089\n"
                "SPLUNK_VERIFY_SSL=true\n",
                encoding="utf-8",
            )
            credential_file.chmod(0o600)
            env = os.environ.copy()
            env.update(
                {
                    "SPLUNK_CREDENTIALS_FILE": str(credential_file),
                    "SPLUNK_PROFILE": "legacy",
                }
            )
            denied = subprocess.run(
                ["bash", "-c", runner.SPLUNK_PROFILE_METADATA_SCRIPT, "profile-probe", "false"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            allowed = subprocess.run(
                ["bash", "-c", runner.SPLUNK_PROFILE_METADATA_SCRIPT, "profile-probe", "true"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(denied.returncode, 0)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertEqual(json.loads(allowed.stdout)["splunk_uri"], "https://splunk.example.test:8089")

    def test_flat_compatibility_gate_never_allows_absent_or_unsafe_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            real_file = root / "real-credentials"
            real_file.write_text(
                "SPLUNK_PLATFORM=cloud\nSPLUNK_URI=https://splunk.example.test:8089\n",
                encoding="utf-8",
            )
            real_file.chmod(0o600)
            symlink_file = root / "credentials-link"
            symlink_file.symlink_to(real_file)
            insecure_file = root / "credentials-insecure"
            insecure_file.write_text(real_file.read_text(encoding="utf-8"), encoding="utf-8")
            insecure_file.chmod(0o644)
            candidates = (root / "absent", symlink_file, insecure_file)
            for credential_file in candidates:
                with self.subTest(credential_file=credential_file):
                    env = os.environ.copy()
                    env.update(
                        {
                            "SPLUNK_CREDENTIALS_FILE": str(credential_file),
                            "SPLUNK_PROFILE": "legacy",
                        }
                    )
                    completed = subprocess.run(
                        ["bash", "-c", runner.SPLUNK_PROFILE_METADATA_SCRIPT, "profile-probe", "true"],
                        cwd=REPO_ROOT,
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("credential", completed.stderr.lower())

    def test_command_timeout_terminates_the_entire_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            marker = Path(tmpdir) / "grandchild-survived"
            with self.assertRaises(subprocess.TimeoutExpired):
                runner.run_command(
                    [
                        "bash",
                        "-c",
                        '(sleep 0.4; touch "$1") & wait',
                        "process-group-test",
                        str(marker),
                    ],
                    profile="test",
                    timeout_seconds=0.05,
                )
            time.sleep(0.55)
            self.assertFalse(marker.exists())

    def test_detached_descendant_cannot_hold_output_pipes_open(self) -> None:
        source = (
            "import os,time\n"
            "if os.fork() == 0:\n"
            "    os.setsid()\n"
            "    time.sleep(1.5)\n"
            "    os._exit(0)\n"
            "os._exit(0)\n"
        )
        started = time.monotonic()
        completed = runner.run_command(
            ["python3", "-c", source],
            profile="test",
            timeout_seconds=5,
        )
        elapsed = time.monotonic() - started

        self.assertEqual(completed.returncode, 98)
        self.assertIn("detached descendant", completed.stderr)
        self.assertLess(elapsed, 1.0)

    def test_interrupt_flag_terminates_active_command_without_handler_io(self) -> None:
        runner._STOP_REQUESTED = False
        timer = threading.Timer(0.1, lambda: setattr(runner, "_STOP_REQUESTED", True))
        timer.start()
        started = time.monotonic()
        try:
            with self.assertRaises(runner.RunnerInterrupted):
                runner.run_command(
                    ["python3", "-c", "import time; time.sleep(10)"],
                    profile="test",
                    timeout_seconds=20,
                )
        finally:
            timer.cancel()
            runner._STOP_REQUESTED = False
        self.assertLess(time.monotonic() - started, 2.0)

    def test_o11y_probe_uses_descriptor_bound_secret_and_pinned_transport(self) -> None:
        script = runner.O11Y_PROBE_SCRIPT
        self.assertIn("credential_curl_write_header_config", script)
        self.assertIn("curl -q -sS", script)
        self.assertIn("--max-filesize 4194304", script)
        self.assertIn("ulimit -f 4096", script)
        self.assertIn('"${CREDENTIAL_CURL_TRANSPORT_ARGS[@]}"', script)
        self.assertIn("unsupported SPLUNK_O11Y_REALM", script)
        self.assertNotIn("token_value=", script)
        self.assertNotIn("cat \"${SPLUNK_O11Y_TOKEN_FILE}\"", script)
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "o11y-probe.sh"
            script_path.write_text(script, encoding="utf-8")
            syntax = subprocess.run(
                ["bash", "-n", str(script_path)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_rest_probe_caps_transport_and_normalizes_a_root_uri(self) -> None:
        script = runner.SPLUNK_REST_PROBE_SCRIPT
        self.assertIn("--max-filesize 4194304", script)
        self.assertIn("ulimit -f 4096", script)
        self.assertIn('"${SPLUNK_URI%/}${endpoint}"', script)
        self.assertLess(script.index("curl() ("), script.index("get_session_key"))
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "rest-probe.sh"
            script_path.write_text(script, encoding="utf-8")
            syntax = subprocess.run(
                ["bash", "-n", str(script_path)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_plan_covers_every_skill_with_read_only_entrypoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            steps = runner.build_plan(
                profile="onprem_2535",
                run_dir=run_dir,
                allow_apply=True,
            )

        skills = {
            path.name
            for path in (REPO_ROOT / "skills").iterdir()
            if path.is_dir() and path.name != "shared" and (path / "SKILL.md").is_file()
        }
        planned_skills = {step.skill for step in steps if step.skill}

        self.assertTrue(skills.issubset(planned_skills))
        self.assertTrue(any(step.category == "baseline" for step in steps))
        self.assertTrue(any(step.category == "doctor" for step in steps))
        self.assertTrue(any(step.category == "apply" for step in steps))
        self.assertIn("splunk-admin-doctor:doctor-live-evidence", {step.step_id for step in steps})

    def test_apply_steps_are_checkpointable_and_explicitly_mark_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            steps = runner.build_apply_steps(Path(tmpdir), allow_apply=True)

        by_id = {step.step_id: step for step in steps}
        self.assertEqual(set(by_id), {"splunk-admin-doctor:render-fix-plan"})
        step = by_id["splunk-admin-doctor:render-fix-plan"]
        self.assertFalse(step.mutates)
        self.assertIn("--phase", step.command)
        self.assertIn("fix-plan", step.command)
        self.assertIn("rollback_or_validation", step.metadata)
        for step in steps:
            self.assertIn("rollback_or_validation", step.metadata) if step.category == "apply" and not step.skip_reason else None

    def test_plan_reuses_one_collected_evidence_bundle_without_duplicate_probes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            baseline_steps = runner.build_baseline_steps("onprem_2535", run_dir)
            apply_steps = runner.build_apply_steps(run_dir, allow_apply=True)

        baseline_by_id = {step.step_id: step for step in baseline_steps}
        self.assertEqual(set(baseline_by_id), {"baseline-live-evidence-gate"})
        gate = baseline_by_id["baseline-live-evidence-gate"]
        self.assertEqual(gate.mode, "evidence-gate")
        self.assertEqual(gate.command[0], "[internal]")
        self.assertFalse(any(step.mode.startswith(("ssh:", "rest:")) for step in baseline_steps))

        self.assertTrue(apply_steps)
        self.assertFalse(any(step.mutates for step in apply_steps))
        self.assertFalse(any(step.mode.startswith("ssh") for step in apply_steps))

    def test_profile_gate_fails_closed_before_any_network_or_ssh_probe(self) -> None:
        unsafe_profiles = [
            {
                "platform": "cloud",
                "splunk_uri": "http://splunk.example.test:8089",
                "verify_ssl": "true",
            },
            {
                "platform": "enterprise",
                "splunk_uri": "https://splunk.example.test:8089",
                "verify_ssl": "false",
            },
            {
                "metadata_error": "credential profile does not exist",
                "platform": "enterprise",
                "splunk_uri": "https://splunk.example.test:8089",
                "verify_ssl": "true",
            },
        ]
        for metadata in unsafe_profiles:
            with self.subTest(metadata=metadata), tempfile.TemporaryDirectory() as tmpdir:
                with (
                    mock.patch.object(runner, "profile_metadata", return_value=metadata),
                    mock.patch.object(runner, "rest_probe") as rest_probe,
                    mock.patch.object(runner, "ssh_cli_probe") as ssh_probe,
                ):
                    evidence = runner.collect_live_evidence(
                        "test_profile",
                        Path(tmpdir),
                        "enterprise" if metadata.get("platform") == "enterprise" else "cloud",
                    )
                self.assertTrue(evidence["collection"]["fatal_errors"])
                rest_probe.assert_not_called()
                ssh_probe.assert_not_called()

    def test_profile_gate_rejects_platform_conflicts_and_embedded_credentials(self) -> None:
        with mock.patch.object(
            runner,
            "profile_metadata",
            return_value={
                "platform": "cloud",
                "splunk_uri": "https://admin:secret@splunk.example.test:8089",
                "verify_ssl": "true",
            },
        ):
            evidence = runner.profile_gate_evidence("cloud_profile", "enterprise")
        errors = " ".join(evidence["collection"]["fatal_errors"])
        self.assertIn("conflicts", errors)
        self.assertIn("must not embed credentials", errors)

    def test_profile_gate_accepts_root_path_and_valid_dns_or_ip_hosts(self) -> None:
        for uri in (
            "https://splunk.example.test:8089/",
            "https://127.0.0.1:8089",
            "https://[2001:db8::1]:8089/",
        ):
            with self.subTest(uri=uri), mock.patch.object(
                runner,
                "profile_metadata",
                return_value={
                    "platform": "enterprise",
                    "splunk_uri": uri,
                    "verify_ssl": "true",
                },
            ):
                evidence = runner.profile_gate_evidence("enterprise_profile", "enterprise")
            self.assertEqual(evidence["collection"]["fatal_errors"], [])

    def test_profile_gate_rejects_malformed_hosts_paths_and_control_whitespace(self) -> None:
        invalid_uris = (
            "https://bad_host.example:8089",
            "https://-bad.example:8089",
            "https://bad..example:8089",
            "https://splunk.example.test:8089/services",
            "https://splunk.example.test:8089?token=x",
            "https://splunk.example.test:8089#fragment",
            " https://splunk.example.test:8089",
            "https://splunk.example.test:8089\n",
            "https://splunk.example.test:0",
            "https://splunk.example.test:99999",
        )
        for uri in invalid_uris:
            with self.subTest(uri=repr(uri)), mock.patch.object(
                runner,
                "profile_metadata",
                return_value={
                    "platform": "enterprise",
                    "splunk_uri": uri,
                    "verify_ssl": "true",
                },
            ):
                evidence = runner.profile_gate_evidence("enterprise_profile", "enterprise")
            self.assertTrue(evidence["collection"]["fatal_errors"])

    def test_rest_http_and_schema_failures_never_become_healthy_evidence(self) -> None:
        ok = runner.RestProbeResult(
            payload={"entry": []},
            process_returncode=0,
            curl_returncode=0,
            http_status=200,
            json_valid=True,
            entry_schema_valid=True,
        )
        unauthorized = runner.RestProbeResult(
            payload={"messages": [{"type": "ERROR"}]},
            process_returncode=22,
            curl_returncode=0,
            http_status=401,
            json_valid=True,
            entry_schema_valid=False,
            error="HTTP 401",
        )
        malformed = runner.RestProbeResult(
            payload={"unexpected": []},
            process_returncode=0,
            curl_returncode=0,
            http_status=200,
            json_valid=True,
            entry_schema_valid=False,
            error="response did not match expected schema",
        )

        def probe_for(endpoint: str, **_kwargs):
            if endpoint.startswith("/services/server/info"):
                return unauthorized
            if endpoint.startswith("/services/apps/local"):
                return malformed
            return ok

        metadata = {
            "platform": "cloud",
            "splunk_uri": "https://splunk.example.test:8089",
            "verify_ssl": "true",
        }
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch.object(runner, "profile_metadata", return_value=metadata),
            mock.patch.object(runner, "rest_probe", side_effect=probe_for) as rest_mock,
        ):
            evidence = runner.collect_live_evidence("cloud_profile", Path(tmpdir), "cloud")

        self.assertTrue(evidence["rest"]["denied"])
        self.assertIn("server_info", evidence["rest"]["probe_errors"])
        self.assertIn("apps", evidence["rest"]["probe_errors"])
        self.assertIsNone(evidence["apps"]["installed"])
        self.assertIsNone(evidence["monitoring_console"]["installed"])
        self.assertEqual(rest_mock.call_count, 3)

    def test_enterprise_version_failure_stops_remaining_ssh_probes(self) -> None:
        ok = runner.RestProbeResult(
            payload={"entry": []},
            process_returncode=0,
            curl_returncode=0,
            http_status=200,
            json_valid=True,
            entry_schema_valid=True,
        )
        metadata = {
            "platform": "enterprise",
            "splunk_uri": "https://splunk.example.test:8089",
            "verify_ssl": "true",
        }
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch.object(runner, "profile_metadata", return_value=metadata),
            mock.patch.object(runner, "rest_probe", return_value=ok),
            mock.patch.object(runner, "ssh_cli_probe", return_value=("", "denied", 255)) as ssh_probe,
        ):
            evidence = runner.collect_live_evidence(
                "enterprise_profile",
                Path(tmpdir),
                "enterprise",
            )

        self.assertEqual(ssh_probe.call_count, 1)
        self.assertEqual(
            evidence["remote_splunk_home"]["checks"]["version"]["returncode"],
            255,
        )
        self.assertTrue(evidence["collection"]["required_errors"])

    def test_enterprise_evidence_gate_requires_successful_ssh_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "evidence.json"
            runner.write_json(
                path,
                {
                    "platform": "enterprise",
                    "collection": {"fatal_errors": []},
                    "rest": {"reachable": True, "probe_errors": []},
                    "remote_splunk_home": {
                        "checks": {"version": {"returncode": 255}},
                    },
                },
            )
            failed = runner.run_internal_evidence_gate(path)
            runner.write_json(
                path,
                {
                    "platform": "enterprise",
                    "collection": {"fatal_errors": []},
                    "rest": {"reachable": True, "probe_errors": []},
                    "remote_splunk_home": {
                        "checks": {"version": {"returncode": 0}},
                    },
                },
            )
            passed = runner.run_internal_evidence_gate(path)

        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("version evidence", failed.stderr)
        self.assertEqual(passed.returncode, 0)

    def test_validation_environment_drops_inherited_credentials(self) -> None:
        inherited = {
            "SPLUNK_URI": "https://wrong.example.test:8089",
            "SPLUNK_PASSWORD": "secret",
            "GH_TOKEN": "gh-secret",
            "AUTHORIZATION_HEADER": "Bearer secret",
            "AWS_ACCESS_KEY_ID": "AKIAEXAMPLE",
            "AWS_SECRET_ACCESS_KEY": "aws-secret",
            "MY_TOKEN_FILE": "/safe/token-file",
        }
        with mock.patch.dict(os.environ, inherited, clear=False):
            env = runner.validation_env("selected_profile")
        for key in inherited:
            if key != "MY_TOKEN_FILE":
                self.assertNotIn(key, env)
        self.assertEqual(env["MY_TOKEN_FILE"], "/safe/token-file")
        self.assertEqual(env["SPLUNK_PROFILE"], "selected_profile")

    def test_selected_and_skipped_skill_scope_cannot_expand_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            doctor_only = runner.build_plan(
                profile="onprem_2535",
                run_dir=run_dir,
                allow_apply=True,
                selected_skills={"splunk-admin-doctor"},
            )
            other_only = runner.build_plan(
                profile="onprem_2535",
                run_dir=run_dir,
                allow_apply=True,
                selected_skills={"splunk-hec-service-setup"},
            )
            doctor_skipped = runner.build_plan(
                profile="onprem_2535",
                run_dir=run_dir,
                allow_apply=True,
                skip_skills={"splunk-admin-doctor"},
            )

        self.assertIn("splunk-admin-doctor:render-fix-plan", {step.step_id for step in doctor_only})
        self.assertNotIn("splunk-admin-doctor:render-fix-plan", {step.step_id for step in other_only})
        self.assertNotIn("splunk-admin-doctor:render-fix-plan", {step.step_id for step in doctor_skipped})
        self.assertFalse(any(step.mutates for step in doctor_only + other_only + doctor_skipped))

    def test_cloud_plan_omits_enterprise_ssh_and_targets_cloud_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            steps = runner.build_plan(
                profile="cloud_profile",
                run_dir=Path(tmpdir),
                allow_apply=True,
                platform="cloud",
                selected_skills={"splunk-admin-doctor"},
            )

        self.assertFalse(any(step.mode.startswith("ssh") for step in steps))
        self.assertFalse(any(step.mutates for step in steps))
        doctor_step = next(step for step in steps if step.step_id == "splunk-admin-doctor:doctor-live-evidence")
        platform_index = doctor_step.command.index("--platform")
        self.assertEqual(doctor_step.command[platform_index + 1], "cloud")

    def test_commands_do_not_use_direct_secret_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            steps = runner.build_plan(profile="onprem_2535", run_dir=Path(tmpdir), allow_apply=True)

        for step in steps:
            with self.subTest(step=step.step_id):
                self.assertFalse(runner.command_uses_direct_secret(step.command), step.command)
                rendered = runner.shell_join(step.command)
                self.assertNotIn("SPLUNK_PASS=", rendered)
                self.assertNotIn("STACK_TOKEN=", rendered)
                self.assertNotIn("SPLUNK_O11Y_TOKEN=", rendered)

    def test_redaction_covers_common_secret_shapes(self) -> None:
        text = "\n".join(
            [
                "Authorization: Bearer abcdefghijklmnop",
                "sessionKey=123456789abcdef",
                '"token": "SUPER_SECRET_VALUE_12345"',
                "password = hunter2hunter2",
                "https://admin:uri-password@example.test:8089/services",
                '"pass4SymmKey": "symmetric-secret-value"',
                '"sslPassword": "ssl-password-value"',
                '"privateKeyPassword": "private-key-password-value"',
                "db_password=db-password-value",
                "admin_token=x",
                "-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----",
                "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.signature",
                "token=x",
                "password=x",
                "secret=x",
                "Authorization=Basic abc",
                "Authorization: Basic abc",
                "authorization_header=x",
                '"token": "x"',
                '"password": "line-one\nline-two"',
                "--token cli-x -p cli-y -P=cli-z -t cli-q",
                "https://example.test/path?token=query-x&safe=y",
            ]
        )
        redacted = runner.redact(text)
        self.assertNotIn("abcdefghijklmnop", redacted)
        self.assertNotIn("123456789abcdef", redacted)
        self.assertNotIn("SUPER_SECRET_VALUE_12345", redacted)
        self.assertNotIn("hunter2hunter2", redacted)
        self.assertNotIn("uri-password", redacted)
        self.assertNotIn("symmetric-secret-value", redacted)
        self.assertNotIn("ssl-password-value", redacted)
        self.assertNotIn("private-key-password-value", redacted)
        self.assertNotIn("db-password-value", redacted)
        self.assertNotIn("admin_token=x", redacted)
        self.assertNotIn("private-material", redacted)
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9", redacted)
        for leaked in (
            "token=x",
            "password=x",
            "secret=x",
            "Basic abc",
            "authorization_header=x",
            '"token": "x"',
            "line-one",
            "line-two",
            "cli-x",
            "cli-y",
            "cli-z",
            "cli-q",
            "query-x",
        ):
            self.assertNotIn(leaked, redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_execute_step_redacts_rejected_secret_argv_from_result_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            step = runner.ValidationStep(
                step_id="unsafe-command",
                category="read-only",
                command=["tool", "--token", "CLI_SECRET_VALUE"],
            )
            result = runner.execute_step(
                step,
                profile="test",
                run_dir=run_dir,
                ledger_path=run_dir / "ledger.jsonl",
                quiet=True,
            )
            stderr = (run_dir / result.stderr_log).read_text(encoding="utf-8")

        self.assertNotIn("CLI_SECRET_VALUE", result.command)
        self.assertNotIn("CLI_SECRET_VALUE", stderr)
        self.assertIn("[REDACTED]", result.command)
        self.assertTrue(runner.command_uses_direct_secret(["tool", "-p=short-secret"]))

    def test_full_plan_and_long_strings_redact_within_a_hard_timeout(self) -> None:
        child_source = r'''
import json
import runpy
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

namespace = runpy.run_path(sys.argv[1])
with tempfile.TemporaryDirectory() as tmpdir:
    steps = namespace["build_plan"](
        profile="performance_profile",
        run_dir=Path(tmpdir),
        allow_apply=True,
    )
payload = json.dumps([asdict(step) for step in steps])
payload += "\n" + ("a" * 1_000_000)
payload += "\n{\"description\":\"" + ("b" * 1_000_000) + "\"}"
payload += "\nNONSECRET_TAIL_MARKER_8675309"
started = time.monotonic()
redacted = namespace["redact"](payload)
elapsed = time.monotonic() - started
if not redacted.endswith("NONSECRET_TAIL_MARKER_8675309") or elapsed >= 2.0:
    raise SystemExit(f"redaction regression: steps={len(steps)} elapsed={elapsed:.3f}s")
'''
        completed = subprocess.run(
            [sys.executable, "-c", child_source, str(RUNNER_PATH)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=8,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)

    def test_redaction_preserves_structural_checkpoint_step_ids_with_token(self) -> None:
        step_id = "splunk-hec-service-setup:apply-ssh-token-no-restart"
        payload = {
            "steps": {
                step_id: {
                    "status": "pass",
                    "metadata": {"hec_token": "SUPER_SECRET_TOKEN_VALUE"},
                }
            },
            "api_key/path": "short-secret",
        }

        redacted = runner.redact_obj(payload)
        row = redacted["steps"][step_id]
        self.assertIsInstance(row, dict)
        self.assertEqual("pass", row["status"])
        self.assertEqual("[REDACTED]", row["metadata"]["hec_token"])
        self.assertEqual("[REDACTED]", redacted["api_key/path"])

    def test_cookie_values_are_redacted_in_structures_assignments_and_headers(self) -> None:
        structured = runner.redact_obj(
            {
                "cookie": "c1",
                "set_cookie": "c2",
                "tracking_cookie": "x",
                "cookie_policy": "allow",
            }
        )
        self.assertEqual(structured["cookie"], "[REDACTED]")
        self.assertEqual(structured["set_cookie"], "[REDACTED]")
        self.assertEqual(structured["tracking_cookie"], "[REDACTED]")
        self.assertEqual(structured["cookie_policy"], "allow")

        rendered = runner.redact(
            "cookie=c1\n"
            "set_cookie=x\n"
            '"cookie":"q"\n'
            "Cookie: session=c1; theme=c2\n"
            "< Set-Cookie: session=x; Path=/; HttpOnly\n"
            "> Cookie: authorization=y; preference=z"
        )
        self.assertIn("cookie=[REDACTED]", rendered)
        self.assertIn("set_cookie=[REDACTED]", rendered)
        self.assertIn('"cookie":"[REDACTED]"', rendered)
        self.assertIn("Cookie: [REDACTED]", rendered)
        self.assertIn("< Set-Cookie: [REDACTED]", rendered)
        self.assertNotIn("session=c1", rendered)
        self.assertNotIn("authorization=y", rendered)

        benign = "I baked a cookie today and set cookie preferences in settings."
        self.assertEqual(runner.redact(benign), benign)

    def test_high_confidence_bare_secret_values_are_redacted(self) -> None:
        github_values = [
            f"gh{prefix}_{'A1' * 12}"
            for prefix in ("p", "o", "u", "s", "r")
        ]
        github_values.append(f"github_pat_{'B2_' * 10}")
        aws_values = [f"AKIA{'A1' * 8}", f"ASIA{'B2' * 8}"]
        slack_values = [
            "xoxb-" + "1234567890-abcdefghijklmnop",
            "xoxp-" + "1234567890-qrstuvwxyzabcdef",
        ]
        splunk_session = f"Splunk {'Ab1' * 11}"
        secret_values = [*github_values, *aws_values, *slack_values, splunk_session]

        rendered = runner.redact("\n".join(secret_values))
        for secret in secret_values:
            self.assertNotIn(secret, rendered)
        self.assertEqual(rendered.count("[REDACTED]"), len(secret_values))

        benign = (
            "Splunk Enterprise and Splunk Observability Cloud are products.\n"
            "ghp_short is an example label, not a token."
        )
        self.assertEqual(runner.redact(benign), benign)

    def test_json_artifacts_are_redacted_and_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "evidence.json"
            runner.write_json(
                path,
                {
                    "clientSecret": "CLIENT_SECRET_VALUE",
                    "uri": "https://admin:URI_PASSWORD@example.test:8089/services",
                },
            )
            rendered = path.read_text(encoding="utf-8")
            mode = path.stat().st_mode & 0o777

        self.assertEqual(mode, 0o600)
        self.assertNotIn("CLIENT_SECRET_VALUE", rendered)
        self.assertNotIn("URI_PASSWORD", rendered)

    def test_secure_writers_reject_symlink_destinations_and_parents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            victim = root / "victim.txt"
            victim.write_text("do-not-touch\n", encoding="utf-8")
            victim.chmod(0o600)
            destination = root / "evidence.json"
            destination.symlink_to(victim)

            with self.assertRaises(OSError):
                runner.write_json(destination, {"status": "pass"})
            with self.assertRaises(OSError):
                runner.append_jsonl(destination, {"status": "pass"})
            self.assertEqual("do-not-touch\n", victim.read_text(encoding="utf-8"))

            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaises(OSError):
                runner.write_text_secure(linked_parent / "log.txt", "unsafe\n")
            self.assertFalse((real_parent / "log.txt").exists())

    def test_secure_parent_creation_tolerates_two_process_mkdir_race(self) -> None:
        child_source = r'''
import runpy
import sys
import time
from pathlib import Path

namespace = runpy.run_path(sys.argv[1])
root = Path(sys.argv[2])
worker = sys.argv[3]
real_mkdir = namespace["os"].mkdir

def delayed_mkdir(path, mode=0o777, *, dir_fd=None):
    time.sleep(0.15)
    return real_mkdir(path, mode, dir_fd=dir_fd)

namespace["os"].mkdir = delayed_mkdir
(root / f"ready-{worker}").write_text("ready\n", encoding="utf-8")
barrier = root / "start"
deadline = time.monotonic() + 5
while not barrier.exists():
    if time.monotonic() >= deadline:
        raise SystemExit("start barrier timed out")
    time.sleep(0.01)
namespace["write_json"](
    root / "new-output" / "shared" / f"worker-{worker}.json",
    {"worker": worker},
)
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", child_source, str(RUNNER_PATH), str(root), worker],
                    cwd=REPO_ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for worker in ("one", "two")
            ]
            try:
                deadline = time.monotonic() + 5
                while not all((root / f"ready-{worker}").is_file() for worker in ("one", "two")):
                    if time.monotonic() >= deadline:
                        self.fail("concurrent writer processes did not reach the start barrier")
                    time.sleep(0.01)
                (root / "start").touch()
                completed = [process.communicate(timeout=5) for process in processes]
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.communicate()

            for process, (stdout, stderr) in zip(processes, completed):
                self.assertEqual(process.returncode, 0, stderr or stdout)
            for worker in ("one", "two"):
                result = root / "new-output" / "shared" / f"worker-{worker}.json"
                self.assertEqual(json.loads(result.read_text(encoding="utf-8"))["worker"], worker)
                self.assertEqual(result.stat().st_mode & 0o777, 0o600)

    def test_two_cli_processes_safely_create_first_output_lock(self) -> None:
        child_source = r'''
import os
import sys
import time
from pathlib import Path

root = Path(sys.argv[1])
worker = sys.argv[2]
runner_path = sys.argv[3]
output_dir = sys.argv[4]
(root / f"cli-ready-{worker}").write_text("ready\n", encoding="utf-8")
barrier = root / "cli-start"
deadline = time.monotonic() + 5
while not barrier.exists():
    if time.monotonic() >= deadline:
        raise SystemExit("CLI start barrier timed out")
    time.sleep(0.01)
os.execv(
    sys.executable,
    [
        sys.executable,
        runner_path,
        "--plan-only",
        "--platform",
        "cloud",
        "--skill",
        "splunk-hec-service-setup",
        "--output-dir",
        output_dir,
        "--quiet",
    ],
)
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "new-cli-output"
            processes = [
                subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        child_source,
                        str(root),
                        worker,
                        str(RUNNER_PATH),
                        str(output_dir),
                    ],
                    cwd=REPO_ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for worker in ("one", "two")
            ]
            try:
                deadline = time.monotonic() + 5
                while not all(
                    (root / f"cli-ready-{worker}").is_file()
                    for worker in ("one", "two")
                ):
                    if time.monotonic() >= deadline:
                        self.fail("CLI processes did not reach the start barrier")
                    time.sleep(0.01)
                (root / "cli-start").touch()
                completed = [process.communicate(timeout=10) for process in processes]
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.communicate()

            self.assertIn(0, [process.returncode for process in processes])
            for process, (stdout, stderr) in zip(processes, completed):
                self.assertIn(process.returncode, {0, 2}, stderr or stdout)
                self.assertNotIn("No such file", stderr)
                self.assertNotIn("FileNotFoundError", stderr)
                if process.returncode == 2:
                    self.assertIn("another live validation runner", stderr)
            lock_path = output_dir / ".live-validation.lock"
            self.assertTrue(lock_path.is_file())
            self.assertEqual(lock_path.stat().st_mode & 0o777, 0o600)

    def test_secure_writers_reject_hardlink_destinations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            victim = root / "victim.txt"
            victim.write_text("do-not-touch\n", encoding="utf-8")
            victim.chmod(0o600)
            destination = root / "ledger.jsonl"
            os.link(victim, destination)

            with self.assertRaises(OSError):
                runner.write_text_secure(destination, "replacement\n")
            with self.assertRaises(OSError):
                runner.append_jsonl(destination, {"status": "pass"})
            self.assertEqual("do-not-touch\n", victim.read_text(encoding="utf-8"))

    def test_secure_append_replaces_private_file_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = Path(tmpdir) / "nested" / "ledger.jsonl"
            runner.append_jsonl(ledger, {"sequence": 1})
            original_inode = ledger.stat().st_ino
            runner.append_jsonl(ledger, {"sequence": 2})

            rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([{"sequence": 1}, {"sequence": 2}], rows)
            self.assertEqual(0o600, ledger.stat().st_mode & 0o777)
            self.assertNotEqual(original_inode, ledger.stat().st_ino)

    def test_checkpoint_is_audit_only_and_apply_render_runs_every_time(self) -> None:
        step = runner.ValidationStep(
            step_id="apply-step",
            category="apply",
            command=["true"],
            mode="render-current-plan",
        )

        def successful_result(current_step, **_kwargs):
            return runner.StepResult(
                step_id=current_step.step_id,
                category=current_step.category,
                skill=current_step.skill,
                mode=current_step.mode,
                status="pass",
                command="true",
                read_only=True,
                mutates=False,
                returncode=0,
                started_at="now",
                ended_at="now",
                duration_seconds=0,
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            args = runner.parse_args(
                [
                    "--once",
                    "--allow-apply",
                    "--skill",
                    "splunk-hec-service-setup",
                    "--output-dir",
                    tmpdir,
                    "--quiet",
                ]
            )
            with (
                mock.patch.object(runner, "build_plan", return_value=[step]),
                mock.patch.object(runner, "execute_step", side_effect=successful_result) as execute,
            ):
                first = runner.run_once(args, iteration=1)
                second = runner.run_once(args, iteration=2)

        self.assertEqual(execute.call_count, 2)
        self.assertEqual(first["totals"], {"pass": 1})
        self.assertEqual(second["totals"], {"pass": 1})
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertFalse(hasattr(runner, "checkpoint_result_is_reusable"))

    def test_skill_summary_distinguishes_interface_partial_and_unassessed(self) -> None:
        def result(step: runner.ValidationStep, status: str) -> runner.StepResult:
            return runner.StepResult(
                step_id=step.step_id,
                category=step.category,
                skill=step.skill,
                mode=step.mode,
                status=status,
                command="true",
                read_only=True,
                mutates=False,
                returncode=0 if status == "pass" else None,
                started_at="now",
                ended_at="now",
                duration_seconds=0,
            )

        help_step = runner.ValidationStep(
            "skill:help", "read-only", ["true"], skill="skill", mode="setup-help"
        )
        feature_step = runner.ValidationStep(
            "skill:status", "read-only", ["true"], skill="skill", mode="phase:status"
        )
        interface = runner.summarize_skill_status([result(help_step, "pass")], [help_step])
        self.assertEqual(interface["skill"]["status"], "interface-pass")

        unassessed = runner.summarize_skill_status(
            [result(help_step, "pass"), result(feature_step, "intentional-skip")],
            [help_step, feature_step],
        )
        self.assertEqual(unassessed["skill"]["status"], "unassessed")

        second_feature = runner.ValidationStep(
            "skill:validate", "read-only", ["true"], skill="skill", mode="phase:validate"
        )
        partial = runner.summarize_skill_status(
            [
                result(feature_step, "pass"),
                result(second_feature, "intentional-skip"),
            ],
            [feature_step, second_feature],
        )
        self.assertEqual(partial["skill"]["status"], "partial-pass")

    def test_btool_findings_are_live_environment_constraints_not_auth_failures(self) -> None:
        step = runner.ValidationStep(
            step_id="baseline-ssh-btool-check",
            category="baseline",
            command=["bash", "-c", "splunk btool check"],
            mode="ssh:btool-check",
        )
        invalid_key = (
            "Checking: /opt/splunk/etc/apps/search/local/passwords.conf\n"
            "Invalid key in stanza [organization] in /opt/splunk/etc/apps/"
            "Splunk_TA_cisco_meraki/local/splunk_ta_cisco_meraki_organization.conf, line 4: base_url"
        )
        no_spec = "No spec file for: /opt/splunk/etc/apps/vendor/local/example.conf"

        self.assertEqual(
            "live_environment_constraint",
            runner.classify_failure(step, 1, invalid_key, ""),
        )
        self.assertEqual(
            "live_environment_constraint",
            runner.classify_failure(step, 1, no_spec, ""),
        )

    def test_connectivity_failures_are_environment_constraints(self) -> None:
        step = runner.ValidationStep(
            step_id="splunk-hec-service-setup:cleanup-ssh-validation-token",
            category="apply-cleanup",
            command=["bash", "-c", "ssh cleanup"],
            mode="ssh:cleanup-hec",
        )

        self.assertEqual(
            "live_environment_constraint",
            runner.classify_failure(step, 255, "", ""),
        )
        self.assertEqual(
            "live_environment_constraint",
            runner.classify_failure(step, 1, "ERROR: Cannot reach 10.0.0.1:8089 (connection refused or timed out).", ""),
        )

    def test_code_bugs_cannot_be_downgraded_to_intentional_skip(self) -> None:
        step = runner.ValidationStep(
            step_id="broken-command",
            category="read-only",
            command=["missing-command"],
            required=False,
            final_on_failure="intentional-skip",
        )
        classification = runner.classify_failure(step, 127, "", "missing-command: command not found")

        self.assertEqual(classification, "code_bug")
        self.assertFalse(runner.should_intentional_skip(step, classification))

    def test_plan_only_does_not_collect_live_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            args = runner.parse_args(
                [
                    "--plan-only",
                    "--platform",
                    "enterprise",
                    "--output-dir",
                    tmpdir,
                    "--quiet",
                ]
            )
            with mock.patch.object(runner, "collect_live_evidence") as collect:
                payload = runner.run_once(args)

        collect.assert_not_called()
        self.assertTrue(payload["steps"])
        self.assertEqual(runner.payload_exit_code(payload), 0)

    def test_plan_only_requires_explicit_platform_and_cli_exits_zero_when_valid(self) -> None:
        with self.assertRaisesRegex(ValueError, "explicit --platform"):
            runner.validate_runner_args(runner.parse_args(["--plan-only"]))

        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code = runner.main(
                [
                    "--plan-only",
                    "--platform",
                    "cloud",
                    "--skill",
                    "splunk-hec-service-setup",
                    "--output-dir",
                    tmpdir,
                    "--quiet",
                ]
            )
        self.assertEqual(exit_code, 0)

    def test_selected_interface_only_skill_does_not_probe_the_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            args = runner.parse_args(
                [
                    "--once",
                    "--skill",
                    "splunk-hec-service-setup",
                    "--output-dir",
                    tmpdir,
                    "--quiet",
                ]
            )
            with (
                mock.patch.object(runner, "collect_live_evidence") as collect,
                mock.patch.object(runner, "profile_gate_evidence") as profile_gate,
                mock.patch.object(runner, "build_plan", return_value=[]),
            ):
                payload = runner.run_once(args)
        collect.assert_not_called()
        profile_gate.assert_not_called()
        self.assertEqual(payload["planned_steps"], 0)

    def test_unknown_skill_selector_is_rejected_before_output_or_probes(self) -> None:
        args = runner.parse_args(["--skill", "not-a-skill", "--output-dir", "/tmp/not-used"])
        with (
            mock.patch.object(runner, "load_checkpoint") as checkpoint,
            mock.patch.object(runner, "collect_live_evidence") as collect,
        ):
            with self.assertRaises(ValueError):
                runner.run_once(args)
        checkpoint.assert_not_called()
        collect.assert_not_called()

    def test_runner_rejects_contradictory_execution_modes(self) -> None:
        for argv, message in (
            (["--once", "--watch"], "cannot be combined"),
            (["--max-iterations", "2"], "requires --watch"),
        ):
            with self.subTest(argv=argv):
                with self.assertRaisesRegex(ValueError, message):
                    runner.validate_runner_args(runner.parse_args(argv))

    def test_source_discovered_live_modes_have_no_execution_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            default_steps = runner.read_only_mode_steps(
                "splunk-monitoring-console-setup",
                Path(tmpdir),
            )
        self.assertFalse(any(step.mode.startswith("phase:") for step in default_steps))
        self.assertFalse(hasattr(runner, "default_spec_for_skill"))

        args = runner.parse_args(["--allow-heuristic-live-probes"])
        with self.assertRaisesRegex(ValueError, "audited, checked-in safety manifest"):
            runner.validate_runner_args(args)

    def test_fatal_profile_error_writes_final_report_without_running_children(self) -> None:
        fatal_evidence = {
            "platform": "cloud",
            "collection": {"fatal_errors": ["TLS verification disabled"]},
            "rest": {"reachable": None},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            args = runner.parse_args(
                [
                    "--once",
                    "--skill",
                    "splunk-admin-doctor",
                    "--output-dir",
                    tmpdir,
                    "--quiet",
                ]
            )
            with (
                mock.patch.object(runner, "collect_live_evidence", return_value=fatal_evidence),
                mock.patch.object(runner, "execute_step") as execute,
            ):
                payload = runner.run_once(args)
            report_path = Path(payload["output_dir"]) / "final-report.json"
            self.assertTrue(report_path.is_file())
        execute.assert_not_called()
        self.assertEqual(payload["totals"]["fail"], 1)
        self.assertFalse(payload["execution_complete"])

    def test_rerun_command_preserves_scope_and_safety_flags(self) -> None:
        args = runner.parse_args(
            [
                "--profile",
                "cloud_profile",
                "--allow-apply",
                "--allow-flat-credentials",
                "--force-rerun",
                "--max-retained-runs",
                "7",
                "--stop-on-failure",
                "--allow-offline-smoke",
                "--skill",
                "splunk-admin-doctor",
                "--skip-skill",
                "splunk-hec-service-setup",
            ]
        )
        command = runner.build_rerun_command(
            args,
            effective_platform="cloud",
            output_dir=Path("/tmp/output"),
        )
        for expected in (
            "--allow-apply",
            "--allow-flat-credentials",
            "--force-rerun",
            "--max-retained-runs 7",
            "--stop-on-failure",
            "--allow-offline-smoke",
            "--skill splunk-admin-doctor",
            "--skip-skill splunk-hec-service-setup",
            "--once",
        ):
            self.assertIn(expected, command)

    def test_output_lock_rejects_concurrent_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "runs"
            with runner.exclusive_output_lock(output):
                with self.assertRaises(RuntimeError):
                    with runner.exclusive_output_lock(output):
                        pass

    def test_command_output_is_bounded(self) -> None:
        completed = runner.run_command(
            ["python3", "-c", "print('x' * 10000)"],
            profile="test",
            timeout_seconds=10,
            max_output_bytes=1024,
        )
        self.assertLess(len(completed.stdout), 1200)
        self.assertIn("dropped", completed.stdout)

    def test_retention_cli_is_bounded_and_uses_canonical_name(self) -> None:
        self.assertEqual(
            runner.parse_args([]).max_retained_runs,
            runner.DEFAULT_MAX_RETAINED_RUNS,
        )
        self.assertEqual(runner.parse_args(["--retain-runs", "7"]).max_retained_runs, 7)
        for value in ("0", str(runner.MAX_RETAIN_RUNS + 1)):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "max-retained-runs"):
                runner.validate_runner_args(runner.parse_args(["--max-retained-runs", value]))

    def test_retention_bounds_complete_and_incomplete_runs_without_touching_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            runs_dir = output_dir / "runs"
            runs_dir.mkdir(parents=True, mode=0o700)
            names = [
                "20260101T000001Z-iter1",
                "20260101T000002Z-iter1",
                "20260101T000003Z-iter1",
                "20260101T000004Z-iter1",
            ]
            for index, name in enumerate(names, start=1):
                path = runs_dir / name
                path.mkdir(mode=0o700)
                (path / ("final-report.json" if index % 2 else "run-start.json")).write_text(
                    "{}\n",
                    encoding="utf-8",
                )
                os.utime(path, ns=(index, index))

            unrecognized = runs_dir / "operator-notes"
            unrecognized.mkdir(mode=0o700)
            external = Path(tmpdir) / "external"
            external.mkdir(mode=0o700)
            marker = external / "do-not-touch"
            marker.write_text("safe\n", encoding="utf-8")
            linked_name = runs_dir / "20260101T000005Z-iter1"
            linked_name.symlink_to(external, target_is_directory=True)

            removed = runner.prune_run_history(
                output_dir,
                runs_dir / names[0],
                retain_runs=2,
            )

            self.assertEqual(set(removed), {names[1], names[2]})
            self.assertTrue((runs_dir / names[0]).is_dir())
            self.assertTrue((runs_dir / names[3]).is_dir())
            self.assertTrue(unrecognized.is_dir())
            self.assertTrue(linked_name.is_symlink())
            self.assertEqual(marker.read_text(encoding="utf-8"), "safe\n")

    def test_retention_refuses_to_cross_a_filesystem_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            runs_dir.mkdir(mode=0o700)
            candidate = runs_dir / "20260101T000001Z-iter1"
            candidate.mkdir(mode=0o700)
            (candidate / "run-start.json").write_text("{}\n", encoding="utf-8")
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            parent_fd = os.open(runs_dir, flags)
            real_fstat = os.fstat

            def changed_device(descriptor):
                metadata = real_fstat(descriptor)
                if descriptor == parent_fd:
                    return metadata
                values = list(metadata)
                values[2] = metadata.st_dev + 1
                return os.stat_result(values)

            try:
                with mock.patch.object(runner.os, "fstat", side_effect=changed_device):
                    with self.assertRaisesRegex(OSError, "filesystem boundary"):
                        runner._remove_tree_at(parent_fd, candidate.name)
            finally:
                os.close(parent_fd)

            self.assertTrue(candidate.is_dir())

    def test_payload_exit_code_fails_closed_on_incomplete_or_malformed_runs(self) -> None:
        self.assertEqual(runner.payload_exit_code({}), 1)
        self.assertEqual(runner.payload_exit_code({"totals": {}, "execution_complete": False}), 1)
        self.assertEqual(
            runner.payload_exit_code({"totals": {"fail": 1}, "execution_complete": True}),
            1,
        )
        self.assertEqual(
            runner.payload_exit_code({"totals": {"pass": 1}, "execution_complete": True}),
            0,
        )

    def test_stop_request_cannot_return_success_after_a_completed_payload(self) -> None:
        args = runner.parse_args(["--once"])

        def completed_after_signal(_args, *, iteration):
            del iteration
            runner._STOP_REQUESTED = True
            return {"totals": {"pass": 1}, "execution_complete": True}

        try:
            with mock.patch.object(runner, "run_once", side_effect=completed_after_signal):
                self.assertEqual(runner._run_locked(args), 1)
        finally:
            runner._STOP_REQUESTED = False


if __name__ == "__main__":
    unittest.main()
