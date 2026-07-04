#!/usr/bin/env python3
"""Regression tests for the splunk-knowledge-objects-setup renderer and wrapper."""

from __future__ import annotations

import ast
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT

RENDERER = REPO_ROOT / "skills/splunk-knowledge-objects-setup/scripts/render_assets.py"
SETUP = REPO_ROOT / "skills/splunk-knowledge-objects-setup/scripts/setup.sh"
STATE_HELPER = REPO_ROOT / "skills/splunk-knowledge-objects-setup/scripts/transaction_state.py"


FAKE_CURL = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

args = sys.argv[1:]
url = next((arg for arg in args if arg.startswith(("http://", "https://"))), "")
state_path = Path(os.environ["KO_FAKE_STATE"])
log_path = Path(os.environ["KO_CURL_LOG"])
state = json.loads(state_path.read_text(encoding="utf-8"))
body = sys.stdin.read()
method = "DELETE" if "DELETE" in args else ("POST" if "-d" in args or any(a.startswith("--data") for a in args) else "GET")

with log_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"url": url, "method": method, "body": body}) + "\n")

def save():
    state_path.write_text(json.dumps(state), encoding="utf-8")

def emit(payload, code="200"):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    if "-o" in args or "--output" in args:
        print(code, end="")
    elif "-w" in args or "--write-out" in args:
        print(text, end="")
        print()
        print(code, end="")
    else:
        print(text, end="")

path = unquote(urlsplit(url).path)
if path.endswith("/services/auth/login"):
    emit("<response><sessionKey>test-session</sessionKey></response>")
elif path.endswith("/services/apps/local/search"):
    emit({"entry": [{"name": "search", "content": {}}]})
elif path.endswith("/services/authentication/current-context"):
    emit({"entry": [{"name": "admin", "content": {"username": "admin", "capabilities": ["admin_all_objects"]}}]})
elif state.get("fail_collection") and path.endswith("/configs/conf-macros") and method == "GET":
    emit({"messages": [{"type": "ERROR"}]}, "403")
elif path.endswith("/configs/conf-macros"):
    if method == "POST":
        form = parse_qs(body, keep_blank_values=True)
        state["object_exists"] = True
        state["object_content"] = {key: values[-1] for key, values in form.items() if key != "name"}
        save()
        emit({"entry": [{"name": form.get("name", [""])[-1]}]}, "201")
    else:
        emit({"entry": []})
elif path.endswith("/configs/conf-macros/net_idx/acl"):
    if method == "POST":
        if state.get("fail_acl"):
            if state.get("inject_concurrent_state"):
                state["object_content"]["concurrent_field"] = "external-value"
                state["acl"]["perms"]["write"] = ["concurrent-role"]
                save()
            emit({"messages": [{"type": "ERROR"}]}, "500")
        else:
            form = parse_qs(body, keep_blank_values=True)
            state["acl"] = {
                "owner": form.get("owner", [state["acl"]["owner"]])[-1],
                "sharing": form.get("sharing", [state["acl"]["sharing"]])[-1],
                "perms": {
                    "read": form.get("perms.read", ["*"]),
                    "write": form.get("perms.write", []),
                },
            }
            save()
            emit({"entry": [{"content": state["acl"]}]})
    elif state.get("object_exists"):
        emit({"entry": [{"name": "net_idx", "content": state["acl"]}]})
    else:
        emit({"messages": []}, "404")
elif path.endswith("/configs/conf-macros/net_idx"):
    if method == "DELETE":
        if state.get("fail_delete"):
            emit({"messages": [{"type": "ERROR"}]}, "500")
        else:
            state["object_exists"] = False
            state["object_content"] = {}
            save()
            emit({}, "200")
    elif method == "POST":
        if not state.get("object_exists"):
            emit({"messages": []}, "404")
        else:
            form = parse_qs(body, keep_blank_values=True)
            state["object_content"].update({key: values[-1] for key, values in form.items()})
            save()
            emit({"entry": [{"name": "net_idx"}]})
    elif state.get("object_exists"):
        snapshot = json.loads(json.dumps(state["object_content"]))
        state["existing_object_gets"] = state.get("existing_object_gets", 0) + 1
        if state.get("inject_after_rollback_snapshot") and state["existing_object_gets"] >= 2:
            state["object_content"]["changed_after_read"] = "external-value"
        if state.get("concurrent_definition_after_rollback_snapshot") and state["existing_object_gets"] >= 2:
            state["object_content"]["definition"] = "index=concurrent"
        save()
        emit({"entry": [{"name": "net_idx", "content": snapshot}]})
    else:
        emit({"messages": []}, "404")
else:
    print(f"unexpected fake curl request: {method} {url}", file=sys.stderr)
    raise SystemExit(91)
'''


class KnowledgeObjectsTests(unittest.TestCase):
    def test_transaction_helper_uses_python_310_compatible_utc(self) -> None:
        source = STATE_HELPER.read_text(encoding="utf-8")
        ast.parse(source, filename=str(STATE_HELPER), feature_version=(3, 10))
        self.assertIn("timezone.utc", source)
        self.assertNotIn("datetime.UTC", source)

    def test_transactional_rollback_has_no_object_or_props_delete_path(self) -> None:
        source = SETUP.read_text(encoding="utf-8")
        helper = STATE_HELPER.read_text(encoding="utf-8")
        self.assertNotIn("-X DELETE", source)
        self.assertNotIn("delete_endpoint", source)
        self.assertIn("automatic whole-stanza DELETE is disabled", source)
        self.assertNotIn("update_existing_conf_body", source)
        self.assertNotIn("rollback-form", helper)
        self.assertNotIn("acl-form", helper)

    def run_renderer(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(RENDERER), *args],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=60,
        )

    def run_setup(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(SETUP), *args],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=60,
        )

    def live_environment(self, root: Path, state: dict) -> tuple[dict[str, str], Path, Path]:
        bin_dir = root / "bin"
        bin_dir.mkdir()
        fake_curl = bin_dir / "curl"
        fake_curl.write_text(FAKE_CURL, encoding="utf-8")
        fake_curl.chmod(0o755)
        credentials = root / "credentials"
        credentials.write_text(
            'SPLUNK_PLATFORM="enterprise"\n'
            'SPLUNK_SEARCH_API_URI="https://splunk.example.invalid:8089"\n'
            'SPLUNK_USER="admin"\n'
            'SPLUNK_PASS="test-only"\n',
            encoding="utf-8",
        )
        state_path = root / "state.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        log_path = root / "curl.jsonl"
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{bin_dir}:{env['PATH']}",
                "SPLUNK_CREDENTIALS_FILE": str(credentials),
                "KO_FAKE_STATE": str(state_path),
                "KO_CURL_LOG": str(log_path),
            }
        )
        return env, state_path, log_path

    def run_live_setup(self, root: Path, state: dict, *args: str) -> tuple[subprocess.CompletedProcess, Path, Path]:
        env, state_path, log_path = self.live_environment(root, state)
        result = subprocess.run(
            ["bash", str(SETUP), "--output-dir", str(root / "rendered"), *args],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        return result, state_path, log_path

    def test_macro_with_args_renders_arity_stanza(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--object-kind", "macro",
                "--name", "net_idx",
                "--args", "a,b",
                "--definition", "index IN ($a$,$b$)",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            macros = (Path(tmpdir) / "knowledge-objects" / "macros.conf").read_text(encoding="utf-8")
            self.assertIn("[net_idx(2)]", macros)
            self.assertIn("args = a, b", macros)

    def test_csv_lookup_emits_transform_props_and_stub(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--object-kind", "lookup",
                "--name", "asset_lookup",
                "--lookup-type", "csv",
                "--lookup-filename", "assets.csv",
                "--fields-list", "ip,risk",
                "--auto-lookup-sourcetype", "cisco:ise",
                "--lookup-output-fields", "risk",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "knowledge-objects"
            transforms = (render_dir / "transforms.conf").read_text(encoding="utf-8")
            props = (render_dir / "props.conf").read_text(encoding="utf-8")
            self.assertIn("filename = assets.csv", transforms)
            self.assertIn("LOOKUP-asset_lookup = asset_lookup OUTPUT risk", props)
            self.assertTrue((render_dir / "lookup-stub.csv").exists())

    def test_savedsearch_requires_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir, "--object-kind", "savedsearch", "--name", "S1",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--search is required", result.stderr)

    def test_global_sharing_refused_without_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--phase", "apply",
                "--object-kind", "macro",
                "--name", "net_idx",
                "--definition", "index IN (a)",
                "--sharing", "global",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--accept-global-sharing", result.stdout + result.stderr)

    def test_dry_run_apply_does_not_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--dry-run", "--phase", "apply",
                "--object-kind", "macro",
                "--name", "net_idx",
                "--definition", "index IN (a)",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("DRY RUN", result.stdout + result.stderr)

    def test_status_queries_live_content_and_acl_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = {
                "object_exists": True,
                "object_content": {"definition": "index=main", "iseval": "0"},
                "acl": {"owner": "nobody", "sharing": "app", "perms": {"read": ["*"], "write": []}},
            }
            result, _state_path, log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "status",
                "--object-kind",
                "macro",
                "--name",
                "net_idx",
                "--definition",
                "index=main",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            evidence_path = root / "rendered" / "knowledge-objects" / "state" / "live-status.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(stat.S_IMODE(evidence_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(evidence_path.parent.stat().st_mode), 0o700)
            self.assertTrue(evidence["live_query"])
            self.assertTrue(evidence["match"])
            self.assertEqual(evidence["acl"]["actual"]["owner"], "nobody")
            calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            live_calls = [call for call in calls if not call["url"].endswith("/services/auth/login")]
            self.assertTrue(any("/configs/conf-macros/net_idx" in call["url"] for call in live_calls))
            self.assertFalse(any(call["method"] in {"POST", "DELETE"} for call in live_calls))

    def test_private_status_uses_owner_namespace_and_private_default_acl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = {
                "object_exists": True,
                "object_content": {"definition": "index=main", "iseval": "0"},
                "acl": {"owner": "admin@example.com", "sharing": "user", "perms": {"read": [], "write": []}},
            }
            result, _state_path, log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "status",
                "--object-kind",
                "macro",
                "--name",
                "net_idx",
                "--definition",
                "index=main",
                "--sharing",
                "user",
                "--owner",
                "admin@example.com",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(
                any("/servicesNS/admin%40example.com/search/configs/conf-macros/net_idx" in call["url"] for call in calls)
            )

    def test_apply_preflight_failure_makes_no_rest_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = {
                "fail_collection": True,
                "object_exists": False,
                "object_content": {},
                "acl": {"owner": "nobody", "sharing": "app", "perms": {"read": ["*"], "write": []}},
            }
            result, _state_path, log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "apply",
                "--object-kind",
                "macro",
                "--name",
                "net_idx",
                "--definition",
                "index=main",
            )
            self.assertNotEqual(result.returncode, 0)
            evidence_path = root / "rendered" / "knowledge-objects" / "state" / "apply-evidence.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["failure_step"], "preflight")
            self.assertEqual(evidence["rollback"], "not-required")
            calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            live_calls = [call for call in calls if not call["url"].endswith("/services/auth/login")]
            self.assertFalse(any(call["method"] in {"POST", "DELETE"} for call in live_calls))

    def test_acl_failure_retains_new_content_with_private_manual_cleanup_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = {
                "fail_acl": True,
                "object_exists": False,
                "object_content": {},
                "acl": {"owner": "admin", "sharing": "user", "perms": {"read": [], "write": []}},
            }
            result, state_path, log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "apply",
                "--object-kind",
                "macro",
                "--name",
                "net_idx",
                "--definition",
                "index=main",
            )
            self.assertNotEqual(result.returncode, 0)
            final_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(final_state["object_exists"])
            calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertFalse(any(call["method"] == "DELETE" for call in calls))
            evidence_path = root / "rendered" / "knowledge-objects" / "state" / "apply-evidence.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["failure_step"], "acl-write")
            self.assertEqual(evidence["rollback"], "partial")
            self.assertTrue(evidence["partial_failure"])
            self.assertTrue(evidence["manual_cleanup_required"])
            cleanup_path = Path(evidence["manual_cleanup_path"])
            self.assertTrue(cleanup_path.is_dir())
            self.assertEqual(stat.S_IMODE(cleanup_path.stat().st_mode), 0o700)
            for name in ("object-before.raw", "object-current.raw", "object-post-write.raw", "acl-current.raw"):
                snapshot = cleanup_path / name
                self.assertTrue(snapshot.is_file(), name)
                self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o600)
            self.assertIn("MANUAL RECOVERY REQUIRED", result.stdout + result.stderr)
            self.assertTrue(any(item["step"] == "rollback-object" and item["status"] == "refused" for item in evidence["events"]))

    def test_acl_failure_retains_existing_content_with_private_recovery_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prior_acl = {"owner": "nobody", "sharing": "app", "perms": {"read": ["*"], "write": ["admin"]}}
            state = {
                "fail_acl": True,
                "object_exists": True,
                "object_content": {"definition": "index=old", "iseval": "1"},
                "acl": prior_acl,
            }
            result, state_path, log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "apply",
                "--object-kind",
                "macro",
                "--name",
                "net_idx",
                "--definition",
                "index=new",
            )
            self.assertNotEqual(result.returncode, 0)
            final_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(final_state["object_content"], {"definition": "index=new", "iseval": "0"})
            self.assertEqual(final_state["acl"], prior_acl)
            evidence_path = root / "rendered" / "knowledge-objects" / "state" / "apply-evidence.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["rollback"], "partial")
            self.assertTrue(evidence["manual_cleanup_required"])
            cleanup = Path(evidence["manual_cleanup_path"])
            for name in (
                "object-before.raw",
                "object-current.raw",
                "acl-before.raw",
                "acl-current.raw",
            ):
                self.assertTrue((cleanup / name).is_file())
                self.assertEqual(stat.S_IMODE((cleanup / name).stat().st_mode), 0o600)
            self.assertTrue(any(item["step"] == "rollback-object" and item["status"] == "refused" for item in evidence["events"]))
            self.assertTrue(any(item["step"] == "rollback-acl" and item["status"] == "unchanged" for item in evidence["events"]))
            calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            object_posts = [
                call for call in calls
                if call["method"] == "POST"
                and call["url"].split("?", 1)[0].endswith("/configs/conf-macros/net_idx")
            ]
            self.assertEqual(len(object_posts), 1)

    def test_owner_traversal_is_rejected_before_render_or_authentication(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            result = self.run_setup(
                "--output-dir",
                str(root / "rendered"),
                "--dry-run",
                "--object-kind",
                "macro",
                "--name",
                "net_idx",
                "--definition",
                "index=main",
                "--sharing",
                "user",
                "--owner",
                "../../nobody",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--owner must be", result.stdout + result.stderr)
            self.assertFalse((root / "rendered").exists())

    def test_dot_path_segments_are_rejected_before_render_or_authentication(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cases = (
                (
                    "app",
                    ("--object-kind", "macro", "--name", "net_idx", "--definition", "index=main", "--app-name", ".."),
                    "--app-name",
                ),
                (
                    "name",
                    ("--object-kind", "macro", "--name", "..", "--definition", "index=main"),
                    "--name",
                ),
                (
                    "sourcetype",
                    (
                        "--object-kind",
                        "lookup",
                        "--name",
                        "asset_lookup",
                        "--lookup-filename",
                        "assets.csv",
                        "--auto-lookup-sourcetype",
                        "..",
                    ),
                    "--auto-lookup-sourcetype",
                ),
            )
            for label, args, expected in cases:
                with self.subTest(label=label):
                    output_dir = root / label
                    result = self.run_setup("--output-dir", str(output_dir), "--dry-run", *args)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(expected, result.stdout + result.stderr)
                    self.assertFalse(output_dir.exists())

    def test_concurrent_field_and_acl_prevent_new_object_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = {
                "fail_acl": True,
                "inject_concurrent_state": True,
                "object_exists": False,
                "object_content": {},
                "acl": {"owner": "admin", "sharing": "user", "perms": {"read": [], "write": []}},
            }
            result, state_path, log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "apply",
                "--object-kind",
                "macro",
                "--name",
                "net_idx",
                "--definition",
                "index=main",
            )
            self.assertNotEqual(result.returncode, 0)
            final_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(final_state["object_exists"])
            self.assertEqual(final_state["object_content"]["concurrent_field"], "external-value")
            calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            object_deletes = [
                call
                for call in calls
                if call["method"] == "DELETE" and call["url"].split("?", 1)[0].endswith("/configs/conf-macros/net_idx")
            ]
            self.assertEqual(object_deletes, [])
            evidence_path = root / "rendered" / "knowledge-objects" / "state" / "apply-evidence.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["rollback"], "partial")
            self.assertTrue(evidence["partial_failure"])
            self.assertTrue(
                any(
                    item["step"] == "rollback-object"
                    and item["status"] == "refused"
                    and "retained" in item["detail"].lower()
                    for item in evidence["events"]
                )
            )

    def test_state_change_after_rollback_read_still_never_deletes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = {
                "fail_acl": True,
                "inject_after_rollback_snapshot": True,
                "object_exists": False,
                "object_content": {},
                "acl": {"owner": "admin", "sharing": "user", "perms": {"read": [], "write": []}},
            }
            result, state_path, log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "apply",
                "--object-kind",
                "macro",
                "--name",
                "net_idx",
                "--definition",
                "index=main",
            )
            self.assertNotEqual(result.returncode, 0)
            final_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(final_state["object_exists"])
            self.assertEqual(final_state["object_content"]["changed_after_read"], "external-value")
            calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertFalse(any(call["method"] == "DELETE" for call in calls))
            evidence = json.loads(
                (root / "rendered" / "knowledge-objects" / "state" / "apply-evidence.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(evidence["manual_cleanup_required"])
            self.assertEqual(evidence["rollback"], "partial")

    def test_existing_object_race_after_reconcile_get_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = {
                "fail_acl": True,
                "concurrent_definition_after_rollback_snapshot": True,
                "object_exists": True,
                "object_content": {"definition": "index=old", "iseval": "1"},
                "acl": {
                    "owner": "nobody",
                    "sharing": "app",
                    "perms": {"read": ["*"], "write": ["admin"]},
                },
            }
            result, state_path, log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "apply",
                "--object-kind",
                "macro",
                "--name",
                "net_idx",
                "--definition",
                "index=new",
            )
            self.assertNotEqual(result.returncode, 0)
            final = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(final["object_content"]["definition"], "index=concurrent")
            calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            object_posts = [
                call for call in calls
                if call["method"] == "POST"
                and call["url"].split("?", 1)[0].endswith("/configs/conf-macros/net_idx")
            ]
            self.assertEqual(len(object_posts), 1)
            evidence = json.loads(
                (root / "rendered" / "knowledge-objects" / "state" / "apply-evidence.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(evidence["rollback"], "partial")
            self.assertTrue(evidence["manual_cleanup_required"])


if __name__ == "__main__":
    unittest.main()
