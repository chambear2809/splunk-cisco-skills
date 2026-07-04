#!/usr/bin/env python3
"""Production-safety regressions for the Splunk Cloud batch uninstaller."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT

SCRIPT = REPO_ROOT / "skills/shared/scripts/cloud_batch_uninstall.sh"
REST_HELPERS = REPO_ROOT / "skills/shared/lib/rest_helpers.sh"
SINGLE_UNINSTALL = REPO_ROOT / "skills/splunk-app-install/scripts/uninstall_app.sh"


ACS_FAKE = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

state_path = Path(os.environ["BATCH_STATE"])
log_path = Path(os.environ["BATCH_ACS_LOG"])
marker_path = Path(os.environ["BATCH_UNINSTALL_MARKER"])
state = json.loads(state_path.read_text(encoding="utf-8"))
command = " ".join(sys.argv[1:])
with log_path.open("a", encoding="utf-8") as handle:
    handle.write(command + "\n")

def save():
    state_path.write_text(json.dumps(state), encoding="utf-8")

if "config current-stack" in command:
    print("Current Search Head: shc1")
    raise SystemExit(0)

if "apps describe " in command:
    app = command.split("apps describe ", 1)[1].split()[0]
    if marker_path.exists() and (
        os.environ.get("BATCH_FINAL_AMBIGUOUS") == "true"
        or os.environ.get("BATCH_FINAL_ACS_AMBIGUOUS") == "true"
    ):
        print("backend unavailable", file=sys.stderr)
        raise SystemExit(2)
    if marker_path.exists() and os.environ.get("BATCH_FINAL_ACS_ABSENT") == "true":
        print("app not found", file=sys.stderr)
        raise SystemExit(1)
    version = state.get("apps", {}).get(app)
    if version is None:
        print(os.environ.get("BATCH_ACS_NOT_FOUND_OUTPUT", "app not found"), file=sys.stderr)
        raise SystemExit(1)
    describe_count = sum(
        f"apps describe {app}" in line
        for line in log_path.read_text(encoding="utf-8").splitlines()
    )
    if (
        app == os.environ.get("BATCH_CHANGE_VERSION_APP")
        and describe_count >= 2
    ):
        version = os.environ.get("BATCH_CHANGED_VERSION", "9.9.9")
    print(json.dumps({"name": app, "version": version, "status": "installed"}))
    raise SystemExit(0)

if "apps uninstall " in command:
    app = command.split("apps uninstall ", 1)[1].split()[0]
    marker_path.touch()
    if app == os.environ.get("BATCH_FAIL_APP"):
        print("injected ACS failure", file=sys.stderr)
        raise SystemExit(2)
    if os.environ.get("BATCH_ACS_REMOVE", "true") == "true":
        state.get("apps", {}).pop(app, None)
        save()
    raise SystemExit(0)

raise SystemExit(0)
'''


CURL_FAKE = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

state_path = Path(os.environ["BATCH_STATE"])
log_path = Path(os.environ["BATCH_CURL_LOG"])
marker_path = Path(os.environ["BATCH_UNINSTALL_MARKER"])
state = json.loads(state_path.read_text(encoding="utf-8"))
args = sys.argv[1:]
url = next((arg for arg in args if arg.startswith(("http://", "https://"))), "")
method = "DELETE" if "DELETE" in args else "GET"
with log_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"method": method, "url": url}) + "\n")

path = unquote(urlsplit(url).path)
if path.endswith("/services/auth/login"):
    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
    raise SystemExit(0)

marker = "/services/apps/local/"
if marker in path:
    app = path.split(marker, 1)[1].split("/", 1)[0]
    if method == "DELETE":
        state.get("apps", {}).pop(app, None)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        sys.stdout.write("200")
        raise SystemExit(int(os.environ.get("BATCH_REST_DELETE_RC", "0")))
    if marker_path.exists() and (
        os.environ.get("BATCH_FINAL_AMBIGUOUS") == "true"
        or os.environ.get("BATCH_FINAL_REST_HTTP")
    ):
        code = os.environ.get("BATCH_FINAL_REST_HTTP", "503")
        sys.stdout.write('{"messages":[]}\n' + code)
        raise SystemExit(0)
    version = state.get("apps", {}).get(app)
    if version is None:
        sys.stdout.write("{}\n404")
    else:
        sys.stdout.write(json.dumps({"entry": [{"name": app, "content": {"version": version}}]}) + "\n200")
    raise SystemExit(0)

raise SystemExit(0)
'''


def write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    path.chmod(0o755)


class CloudBatchUninstallTests(unittest.TestCase):
    def environment(
        self, root: Path, apps: dict[str, str], **overrides: str
    ) -> tuple[dict[str, str], Path, Path, Path, Path]:
        bin_dir = root / "bin"
        bin_dir.mkdir()
        write_executable(bin_dir / "acs", ACS_FAKE)
        write_executable(bin_dir / "curl", CURL_FAKE)
        write_executable(bin_dir / "nc", "#!/usr/bin/env bash\nexit 0\n")
        credentials = root / "credentials"
        credentials.write_text(
            'SPLUNK_PLATFORM="cloud"\n'
            'SPLUNK_CLOUD_STACK="example-stack"\n'
            'ACS_SERVER="https://staging.admin.splunk.com"\n'
            'STACK_TOKEN="token"\n'
            'SPLUNK_SEARCH_API_URI="https://example-stack.splunkcloud.com:8089"\n'
            'SPLUNK_USER="user"\n'
            'SPLUNK_PASS="pass"\n',
            encoding="utf-8",
        )
        state = root / "state.json"
        state.write_text(json.dumps({"apps": apps}), encoding="utf-8")
        acs_log = root / "acs.log"
        curl_log = root / "curl.log"
        marker = root / "uninstall-requested"
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{bin_dir}:{env['PATH']}",
                "SPLUNK_CREDENTIALS_FILE": str(credentials),
                "BATCH_STATE": str(state),
                "BATCH_ACS_LOG": str(acs_log),
                "BATCH_CURL_LOG": str(curl_log),
                "BATCH_UNINSTALL_MARKER": str(marker),
                "BATCH_ACS_REMOVE": "true",
                **overrides,
            }
        )
        return env, state, acs_log, curl_log, marker

    def run_batch(
        self, root: Path, env: dict[str, str], *args: str
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        evidence = root / "evidence.json"
        result = subprocess.run(
            [
                "bash",
                str(SCRIPT),
                "--no-restart",
                "--verify-attempts",
                "1",
                "--verify-interval",
                "0",
                "--evidence-file",
                str(evidence),
                *args,
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        return result, evidence

    def test_rejects_unsafe_or_ambiguous_app_names_before_tools_run(self) -> None:
        for app in ("", ".", "..", "-option", "bad/name", "bad name"):
            with self.subTest(app=app), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                env, _state, acs_log, _curl_log, _marker = self.environment(
                    root, {"safe_app": "1.0.0"}
                )
                result, _evidence = self.run_batch(root, env, "--yes", app)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid app name", result.stdout + result.stderr)
                self.assertFalse(acs_log.exists())

    def test_noninteractive_run_requires_yes_after_exact_all_target_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            env, state, acs_log, _curl_log, _marker = self.environment(
                root, {"app_a": "1.0.0", "app_b": "2.0.0"}
            )
            result, evidence = self.run_batch(root, env, "app_a", "app_b")
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("=== Exact Removal Plan ===", output)
            self.assertIn("app_a version=1.0.0", output)
            self.assertIn("app_b version=2.0.0", output)
            self.assertIn("requires --yes", output)
            self.assertEqual(json.loads(state.read_text(encoding="utf-8"))["apps"], {"app_a": "1.0.0", "app_b": "2.0.0"})
            self.assertNotIn("apps uninstall", acs_log.read_text(encoding="utf-8"))
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertFalse(payload["mutation_started"])
            self.assertEqual(stat.S_IMODE(evidence.stat().st_mode), 0o600)

    def test_preflights_every_target_then_stops_on_partial_acs_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            env, _state, acs_log, _curl_log, _marker = self.environment(
                root,
                {"app_a": "1.0.0", "app_b": "2.0.0", "app_c": "3.0.0"},
                BATCH_FAIL_APP="app_b",
            )
            result, evidence = self.run_batch(
                root, env, "--yes", "app_a", "app_b", "app_c"
            )
            self.assertNotEqual(result.returncode, 0)
            commands = acs_log.read_text(encoding="utf-8").splitlines()
            first_uninstall = next(i for i, line in enumerate(commands) if "apps uninstall" in line)
            for app in ("app_a", "app_b", "app_c"):
                self.assertTrue(
                    any(f"apps describe {app}" in line for line in commands[:first_uninstall])
                )
            self.assertTrue(any("apps uninstall app_a" in line for line in commands))
            self.assertTrue(any("apps uninstall app_b" in line for line in commands))
            self.assertFalse(any("apps uninstall app_c" in line for line in commands))
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            rows = {row["app"]: row for row in payload["apps"]}
            self.assertEqual(rows["app_b"]["acs_uninstall"], "failed-rc-2")
            self.assertEqual(rows["app_c"]["acs_uninstall"], "not-attempted")
            self.assertEqual(payload["result"], "failed")

    def test_evidence_destination_is_proved_before_any_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            env, state, acs_log, _curl_log, _marker = self.environment(
                root, {"app_a": "1.0.0"}
            )
            protected = root / "protected.json"
            protected.write_text("unchanged", encoding="utf-8")
            (root / "evidence.json").symlink_to(protected)
            result, _evidence = self.run_batch(root, env, "--yes", "app_a")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing symlink evidence file", result.stdout + result.stderr)
            self.assertEqual(protected.read_text(encoding="utf-8"), "unchanged")
            self.assertEqual(json.loads(state.read_text(encoding="utf-8"))["apps"], {"app_a": "1.0.0"})
            self.assertNotIn("apps uninstall", acs_log.read_text(encoding="utf-8"))

    def test_evidence_rejects_symlink_parent_components_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            env, state, acs_log, _curl_log, _marker = self.environment(
                root, {"app_a": "1.0.0"}
            )
            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            evidence = linked_parent / "evidence.json"
            result = subprocess.run(
                [
                    "bash",
                    str(SCRIPT),
                    "--no-restart",
                    "--verify-attempts",
                    "1",
                    "--verify-interval",
                    "0",
                    "--evidence-file",
                    str(evidence),
                    "--yes",
                    "app_a",
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "refusing symlink/non-directory evidence parent component",
                result.stdout + result.stderr,
            )
            self.assertFalse((real_parent / "evidence.json").exists())
            self.assertEqual(
                json.loads(state.read_text(encoding="utf-8"))["apps"],
                {"app_a": "1.0.0"},
            )
            self.assertNotIn("apps uninstall", acs_log.read_text(encoding="utf-8"))

    def test_persistent_app_requires_separate_rest_fallback_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            env, _state, _acs_log, curl_log, _marker = self.environment(
                root, {"app_a": "1.0.0"}, BATCH_ACS_REMOVE="false"
            )
            result, evidence = self.run_batch(root, env, "--yes", "app_a")
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Direct REST DELETE was not authorized", output)
            calls = [json.loads(line) for line in curl_log.read_text(encoding="utf-8").splitlines()]
            self.assertFalse(any(call["method"] == "DELETE" for call in calls))
            row = json.loads(evidence.read_text(encoding="utf-8"))["apps"][0]
            self.assertEqual(row["rest_fallback"], "refused-no-explicit-gate")
            self.assertIn("STILL PRESENT", output)

    def test_explicit_rest_fallback_deletes_then_proves_absence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            env, state, _acs_log, curl_log, _marker = self.environment(
                root, {"app_a": "1.0.0"}, BATCH_ACS_REMOVE="false"
            )
            result, evidence = self.run_batch(
                root, env, "--yes", "--accept-rest-fallback", "app_a"
            )
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("TOPOLOGY RISK ACCEPTED", output)
            self.assertIn("VERIFIED ABSENT", output)
            self.assertEqual(json.loads(state.read_text(encoding="utf-8"))["apps"], {})
            calls = [json.loads(line) for line in curl_log.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(call["method"] == "DELETE" for call in calls))
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["result"], "succeeded")
            self.assertTrue(payload["rest_fallback_accepted"])

    def test_rest_delete_transport_failure_never_becomes_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            env, state, _acs_log, curl_log, _marker = self.environment(
                root,
                {"app_a": "1.0.0"},
                BATCH_ACS_REMOVE="false",
                BATCH_REST_DELETE_RC="28",
            )
            result, evidence = self.run_batch(
                root, env, "--yes", "--accept-rest-fallback", "app_a"
            )
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("REST fallback failed or was ambiguous", output)
            self.assertEqual(json.loads(state.read_text(encoding="utf-8"))["apps"], {})
            calls = [
                json.loads(line)
                for line in curl_log.read_text(encoding="utf-8").splitlines()
            ]
            self.assertTrue(any(call["method"] == "DELETE" for call in calls))
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["result"], "failed")
            self.assertIn("ambiguous-rc-28", payload["apps"][0]["rest_fallback"])

    def test_acs_rc_zero_never_succeeds_when_final_verification_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            env, _state, _acs_log, _curl_log, _marker = self.environment(
                root,
                {"app_a": "1.0.0"},
                BATCH_ACS_REMOVE="true",
                BATCH_FINAL_AMBIGUOUS="true",
            )
            result, evidence = self.run_batch(root, env, "--yes", "app_a")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("VERIFICATION AMBIGUOUS", result.stdout + result.stderr)
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["result"], "failed")
            self.assertIn("ambiguous", payload["apps"][0]["final_verification"])

    def test_rest_only_404_never_proves_absence_when_acs_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            env, _state, _acs_log, _curl_log, _marker = self.environment(
                root,
                {"app_a": "1.0.0"},
                BATCH_ACS_REMOVE="true",
                BATCH_FINAL_ACS_AMBIGUOUS="true",
            )
            result, evidence = self.run_batch(root, env, "--yes", "app_a")
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("REST-only HTTP 404 is insufficient", output)
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["result"], "failed")
            self.assertIn("ambiguous", payload["apps"][0]["final_verification"])

    def test_wrong_app_or_unrelated_nested_404_is_not_definitive_acs_absence(self) -> None:
        for acs_output in (
            "app wrong_app not found",
            '{"error": {"code": 404, "message": "unrelated nested error"}}',
            '[{"type": "diagnostic", "statusCode": 404}]',
        ):
            with self.subTest(acs_output=acs_output), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                env, _state, _acs_log, _curl_log, _marker = self.environment(
                    root,
                    {"app_a": "1.0.0"},
                    BATCH_ACS_REMOVE="true",
                    BATCH_ACS_NOT_FOUND_OUTPUT=acs_output,
                )
                result, evidence = self.run_batch(root, env, "--yes", "app_a")
                self.assertNotEqual(result.returncode, 0)
                row = json.loads(evidence.read_text(encoding="utf-8"))["apps"][0]
                self.assertIn("ambiguous", row["final_verification"])

    def test_exact_named_and_top_level_http_404_prove_acs_absence(self) -> None:
        for acs_output in (
            "app app_a not found",
            '[{"type": "http", "response": "{\\"code\\": 404}"}]',
        ):
            with self.subTest(acs_output=acs_output), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                env, _state, _acs_log, _curl_log, _marker = self.environment(
                    root,
                    {"app_a": "1.0.0"},
                    BATCH_ACS_REMOVE="true",
                    BATCH_ACS_NOT_FOUND_OUTPUT=acs_output,
                )
                result, evidence = self.run_batch(root, env, "--yes", "app_a")
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                payload = json.loads(evidence.read_text(encoding="utf-8"))
                self.assertEqual(payload["result"], "succeeded")

    def test_acs_absent_rest_present_disagreement_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            env, _state, _acs_log, _curl_log, _marker = self.environment(
                root,
                {"app_a": "1.0.0"},
                BATCH_ACS_REMOVE="false",
                BATCH_FINAL_ACS_ABSENT="true",
            )
            result, evidence = self.run_batch(root, env, "--yes", "app_a")
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("CHANNEL DISAGREEMENT / PRESENT", output)
            row = json.loads(evidence.read_text(encoding="utf-8"))["apps"][0]
            self.assertIn("channel-disagreement", row["final_verification"])

    def test_auth_and_server_errors_are_not_classified_as_absence(self) -> None:
        for http_code in ("401", "403", "500", "503"):
            with self.subTest(http_code=http_code), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                env, _state, _acs_log, _curl_log, _marker = self.environment(
                    root,
                    {"app_a": "1.0.0"},
                    BATCH_ACS_REMOVE="true",
                    BATCH_FINAL_ACS_AMBIGUOUS="true",
                    BATCH_FINAL_REST_HTTP=http_code,
                )
                result, evidence = self.run_batch(root, env, "--yes", "app_a")
                self.assertNotEqual(result.returncode, 0)
                row = json.loads(evidence.read_text(encoding="utf-8"))["apps"][0]
                self.assertIn("ambiguous", row["final_verification"])

    def test_exact_version_is_revalidated_immediately_before_each_acs_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            env, state, acs_log, _curl_log, _marker = self.environment(
                root,
                {"app_a": "1.0.0", "app_b": "2.0.0"},
                BATCH_CHANGE_VERSION_APP="app_b",
                BATCH_CHANGED_VERSION="2.0.1",
            )
            result, evidence = self.run_batch(
                root, env, "--yes", "app_a", "app_b"
            )
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("changed or became ambiguous", output)
            commands = acs_log.read_text(encoding="utf-8").splitlines()
            app_a_uninstall = next(
                index for index, command in enumerate(commands)
                if "apps uninstall app_a" in command
            )
            self.assertTrue(
                any("apps describe app_a" in command for command in commands[:app_a_uninstall])
            )
            self.assertFalse(any("apps uninstall app_b" in command for command in commands))
            self.assertEqual(
                json.loads(state.read_text(encoding="utf-8"))["apps"],
                {"app_b": "2.0.0"},
            )
            rows = {
                row["app"]: row
                for row in json.loads(evidence.read_text(encoding="utf-8"))["apps"]
            }
            self.assertEqual(rows["app_b"]["acs_uninstall"], "refused-repreflight")

    def test_single_cloud_uninstall_delegates_to_hardened_batch_engine(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            env, state, _acs_log, _curl_log, _marker = self.environment(
                root, {"app_a": "1.0.0"}
            )
            evidence = root / "single-evidence.json"
            result = subprocess.run(
                [
                    "bash",
                    str(SINGLE_UNINSTALL),
                    "--app-name",
                    "app_a",
                    "--yes",
                    "--no-restart",
                    "--verify-attempts",
                    "1",
                    "--verify-interval",
                    "0",
                    "--evidence-file",
                    str(evidence),
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("ACS-authoritative batch uninstall state machine", output)
            self.assertIn("verified absent", output.lower())
            self.assertEqual(json.loads(state.read_text(encoding="utf-8"))["apps"], {})
            self.assertEqual(
                json.loads(evidence.read_text(encoding="utf-8"))["result"],
                "succeeded",
            )

    def test_all_app_rest_paths_are_segment_encoded(self) -> None:
        rest_helpers = REST_HELPERS.read_text(encoding="utf-8")
        batch = SCRIPT.read_text(encoding="utf-8")
        single = SINGLE_UNINSTALL.read_text(encoding="utf-8")
        self.assertIn('encoded_app=$(_urlencode "${app}")', rest_helpers)
        self.assertIn('encoded="$(_urlencode "${app}")"', batch)
        self.assertIn('encoded_app=$(_urlencode "${app}")', single)
        self.assertNotIn("/services/apps/local/${app}?", batch)
        self.assertIn("../../shared/scripts/cloud_batch_uninstall.sh", single)
        self.assertIn("--accept-rest-fallback", single)
        self.assertNotIn("Attempting direct search-tier REST DELETE as fallback", single)


if __name__ == "__main__":
    unittest.main()
