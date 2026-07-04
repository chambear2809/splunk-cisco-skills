#!/usr/bin/env python3
"""Regression tests for the splunk-dashboard-studio-setup renderer and wrapper."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT

RENDERER = REPO_ROOT / "skills/splunk-dashboard-studio-setup/scripts/render_assets.py"
SETUP = REPO_ROOT / "skills/splunk-dashboard-studio-setup/scripts/setup.sh"
STATE_HELPER = REPO_ROOT / "skills/splunk-dashboard-studio-setup/scripts/transaction_state.py"


FAKE_CURL = r'''#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

args = sys.argv[1:]
url = next((arg for arg in args if arg.startswith(("http://", "https://"))), "")
state_path = Path(os.environ["DASHBOARD_FAKE_STATE"])
log_path = Path(os.environ["DASHBOARD_CURL_LOG"])
state = json.loads(state_path.read_text(encoding="utf-8"))
body = sys.stdin.read()
method = "DELETE" if "DELETE" in args else ("POST" if "-d" in args else "GET")

with log_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"url": url, "method": method, "body": body}) + "\n")

def save():
    state_path.write_text(json.dumps(state), encoding="utf-8")

def emit(payload, code="200"):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    if "-w" in args or "--write-out" in args:
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
    emit({"entry": [{"name": "admin", "content": {"capabilities": ["admin_all_objects"]}}]})
elif path.endswith("/data/ui/views") and method == "GET":
    if state.get("fail_collection"):
        emit({"messages": [{"type": "ERROR"}]}, "403")
    else:
        entries = ([{"name": "net_overview", "content": {}}] if state.get("view_exists") else [])
        emit({"entry": entries})
elif path.endswith("/data/ui/views") and method == "POST":
    form = parse_qs(body, keep_blank_values=True)
    response_code = str(state.pop("content_write_response_code", "201"))
    state["view_exists"] = True
    state["view_content"] = form.get("eai:data", [""])[-1]
    state["mutated"] = True
    if state.pop("fail_readback_after_write", False):
        state["fail_next_view_read"] = 1
    if state.pop("inject_local_error_after_content", False):
        Path(os.environ["DASHBOARD_ERROR_MARKER"]).touch()
    save()
    emit({"entry": [{"name": form.get("name", [""])[-1]}]}, response_code)
elif path.endswith("/data/ui/views/net_overview/acl"):
    if method == "POST":
        if state.get("sleep_acl_seconds"):
            time.sleep(float(state["sleep_acl_seconds"]))
        remaining = int(state.get("fail_acl_count", 0))
        if remaining:
            state["fail_acl_count"] = remaining - 1
            if state.get("concurrent_content_on_acl_failure"):
                state["view_content"] = state["concurrent_content_on_acl_failure"]
            save()
            emit({"messages": [{"type": "ERROR"}]}, "500")
        else:
            form = parse_qs(body, keep_blank_values=True)
            state["acl"] = {
                "owner": form.get("owner", [state["acl"]["owner"]])[-1],
                "sharing": form.get("sharing", [state["acl"]["sharing"]])[-1],
                "perms": {
                    "read": form.get("perms.read", state["acl"]["perms"].get("read", [])),
                    "write": form.get("perms.write", state["acl"]["perms"].get("write", [])),
                },
            }
            if state.pop("fail_readback_after_acl_write", False):
                state["fail_next_view_read"] = 1
            save()
            emit({"entry": [{"content": state["acl"]}]})
    elif state.get("view_exists"):
        acl_snapshot = json.loads(json.dumps(state["acl"]))
        if (
            state.get("mutated")
            and int(state.get("fail_acl_count", 0)) == 0
            and state.pop("inject_after_reconcile_acl_get", False)
        ):
            state["view_content"] = state["concurrent_content_after_reconcile"]
            save()
        emit({"entry": [{"name": "net_overview", "content": acl_snapshot}]})
    else:
        emit({"messages": []}, "404")
elif path.endswith("/data/ui/views/net_overview"):
    if method == "DELETE":
        if state.get("fail_delete"):
            emit({"messages": [{"type": "ERROR"}]}, "500")
        else:
            state["view_exists"] = False
            state["view_content"] = ""
            save()
            emit({}, "200")
    elif method == "POST":
        form = parse_qs(body, keep_blank_values=True)
        proposed = form.get("eai:data", [""])[-1]
        response_code = str(state.pop("content_write_response_code", "200"))
        if state.get("fail_restore_content") and proposed == state.get("original_content"):
            emit({"messages": [{"type": "ERROR"}]}, "500")
        else:
            state["view_exists"] = True
            state["view_content"] = proposed
            state["mutated"] = True
            if state.pop("fail_readback_after_write", False):
                state["fail_next_view_read"] = 1
            if state.pop("inject_local_error_after_content", False):
                Path(os.environ["DASHBOARD_ERROR_MARKER"]).touch()
            save()
            emit({"entry": [{"name": "net_overview"}]}, response_code)
    elif int(state.get("fail_next_view_read", 0)):
        state["fail_next_view_read"] = int(state["fail_next_view_read"]) - 1
        save()
        emit({"messages": [{"type": "ERROR"}]}, "500")
    elif state.get("view_exists"):
        emit({"entry": [{"name": "net_overview", "content": {"eai:data": state["view_content"]}}]})
    else:
        emit({"messages": []}, "404")
else:
    print(f"unexpected fake curl request: {method} {url}", file=sys.stderr)
    raise SystemExit(91)
'''


class DashboardStudioTests(unittest.TestCase):
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
        error_marker = root / "inject-error"
        python_wrapper = bin_dir / "python3"
        python_wrapper.write_text(
            "#!/usr/bin/env bash\n"
            'if [[ -f "${DASHBOARD_ERROR_MARKER}" && "${1:-}" == "${DASHBOARD_STATE_HELPER}" ]]; then\n'
            '  rm -f -- "${DASHBOARD_ERROR_MARKER}"\n'
            "  exit 97\n"
            "fi\n"
            'exec "${DASHBOARD_REAL_PYTHON}" "$@"\n',
            encoding="utf-8",
        )
        python_wrapper.chmod(0o755)
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
                "DASHBOARD_FAKE_STATE": str(state_path),
                "DASHBOARD_CURL_LOG": str(log_path),
                "DASHBOARD_ERROR_MARKER": str(error_marker),
                "DASHBOARD_REAL_PYTHON": sys.executable,
                "DASHBOARD_STATE_HELPER": str(STATE_HELPER),
            }
        )
        return env, state_path, log_path

    def run_live_setup(
        self, root: Path, state: dict, *args: str
    ) -> tuple[subprocess.CompletedProcess, Path, Path]:
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

    def rendered_view(self, root: Path, search: str) -> str:
        seed = root / "seed"
        result = self.run_renderer(
            "--output-dir",
            str(seed),
            "--dashboard-name",
            "net_overview",
            "--search",
            search,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        return (seed / "dashboard-studio" / "view.xml").read_text(encoding="utf-8")

    def test_build_from_search_emits_version2_xml_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--dashboard-name", "net_overview",
                "--title", "Network Overview",
                "--search", "index=netfw | stats count by action",
                "--viz-type", "splunk.column",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "dashboard-studio"
            view = (render_dir / "view.xml").read_text(encoding="utf-8")
            definition = json.loads((render_dir / "dashboard.json").read_text(encoding="utf-8"))
            self.assertIn('<dashboard version="2"', view)
            self.assertIn("<![CDATA[", view)
            self.assertEqual(definition["visualizations"]["viz_primary"]["type"], "splunk.column")
            self.assertEqual(
                definition["dataSources"]["ds_primary"]["options"]["query"],
                "index=netfw | stats count by action",
            )

    def test_definition_file_used_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            defn = Path(tmpdir) / "def.json"
            defn.write_text(json.dumps({"title": "Custom", "visualizations": {}, "dataSources": {}, "layout": {}}), encoding="utf-8")
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--dashboard-name", "custom_dash",
                "--definition-file", str(defn),
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            dashboard = json.loads((Path(tmpdir) / "dashboard-studio" / "dashboard.json").read_text(encoding="utf-8"))
            self.assertEqual(dashboard["title"], "Custom")

    def test_requires_search_or_definition(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer("--output-dir", tmpdir, "--dashboard-name", "empty_dash")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Provide --search", result.stderr)

    def test_rejects_invalid_definition_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = Path(tmpdir) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            result = self.run_renderer(
                "--output-dir", tmpdir, "--dashboard-name", "d", "--definition-file", str(bad),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not valid JSON", result.stderr)

    def test_dry_run_apply_does_not_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir, "--dry-run", "--phase", "apply",
                "--dashboard-name", "net_overview",
                "--search", "index=netfw | stats count",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("DRY RUN", result.stdout + result.stderr)

    def test_rejects_unsafe_owner_and_app_namespace_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            unsafe_owner = self.run_setup(
                "--output-dir",
                tmpdir,
                "--dashboard-name",
                "net_overview",
                "--search",
                "index=main",
                "--owner",
                "../../nobody",
            )
            self.assertNotEqual(unsafe_owner.returncode, 0)
            self.assertIn("safe non-empty Splunk username", unsafe_owner.stdout + unsafe_owner.stderr)

            unsafe_app = self.run_setup(
                "--output-dir",
                tmpdir,
                "--dashboard-name",
                "net_overview",
                "--search",
                "index=main",
                "--app-name",
                "search/../../system",
            )
            self.assertNotEqual(unsafe_app.returncode, 0)
            self.assertIn("safe namespace segment", unsafe_app.stdout + unsafe_app.stderr)

            wildcard_owner = self.run_setup(
                "--output-dir",
                tmpdir,
                "--dashboard-name",
                "net_overview",
                "--search",
                "index=main",
                "--owner",
                "-",
            )
            self.assertNotEqual(wildcard_owner.returncode, 0)

            unsafe_role = self.run_setup(
                "--output-dir",
                tmpdir,
                "--dashboard-name",
                "net_overview",
                "--search",
                "index=main",
                "--read-roles",
                "power user",
            )
            self.assertNotEqual(unsafe_role.returncode, 0)
            self.assertIn("ACL roles", unsafe_role.stdout + unsafe_role.stderr)

    def test_status_queries_exact_live_view_and_acl_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            search = "index=netfw | stats count"
            desired = self.rendered_view(root, search)
            state = {
                "view_exists": True,
                "view_content": desired,
                "acl": {"owner": "nobody", "sharing": "app", "perms": {"read": ["*"], "write": []}},
            }
            result, _state_path, log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "status",
                "--dashboard-name",
                "net_overview",
                "--search",
                search,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            evidence_path = root / "rendered" / "dashboard-studio" / "state" / "live-status.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertTrue(evidence["live_query"])
            self.assertTrue(evidence["match"])
            self.assertTrue(evidence["view"]["content_matches"])
            self.assertTrue(evidence["acl"]["owner_matches"])
            self.assertTrue(evidence["acl"]["sharing_matches"])
            self.assertTrue(evidence["acl"]["read_roles_match"])
            self.assertTrue(evidence["acl"]["write_roles_match"])
            self.assertEqual(evidence["acl"]["actual"]["read"], ["*"])
            self.assertEqual(evidence["acl"]["actual"]["write"], [])
            calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            live_calls = [call for call in calls if not call["url"].endswith("/services/auth/login")]
            self.assertTrue(any(call["url"].split("?", 1)[0].endswith("/data/ui/views/net_overview") for call in live_calls))
            self.assertTrue(any(call["url"].split("?", 1)[0].endswith("/data/ui/views/net_overview/acl") for call in live_calls))
            self.assertFalse(any(call["method"] in {"POST", "DELETE"} for call in live_calls))

    def test_status_fails_on_content_drift_and_writes_hash_only_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            secret_marker = "sensitive-search-marker"
            state = {
                "view_exists": True,
                "view_content": f'<dashboard version="2"><definition>{secret_marker}</definition></dashboard>',
                "acl": {"owner": "nobody", "sharing": "app", "perms": {"read": ["*"], "write": []}},
            }
            result, _state_path, _log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "status",
                "--dashboard-name",
                "net_overview",
                "--search",
                "index=netfw | stats count",
            )
            self.assertNotEqual(result.returncode, 0)
            evidence_path = root / "rendered" / "dashboard-studio" / "state" / "live-status.json"
            evidence_text = evidence_path.read_text(encoding="utf-8")
            evidence = json.loads(evidence_text)
            self.assertFalse(evidence["match"])
            self.assertFalse(evidence["view"]["content_matches"])
            self.assertNotIn(secret_marker, evidence_text)

    def test_status_fails_on_owner_and_sharing_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            search = "index=netfw | stats count"
            desired = self.rendered_view(root, search)
            state = {
                "view_exists": True,
                "view_content": desired,
                "acl": {"owner": "analyst", "sharing": "user", "perms": {"read": [], "write": []}},
            }
            result, _state_path, _log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "status",
                "--dashboard-name",
                "net_overview",
                "--search",
                search,
            )
            self.assertNotEqual(result.returncode, 0)
            evidence_path = root / "rendered" / "dashboard-studio" / "state" / "live-status.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertTrue(evidence["view"]["content_matches"])
            self.assertFalse(evidence["acl"]["owner_matches"])
            self.assertFalse(evidence["acl"]["sharing_matches"])

    def test_status_fails_on_exact_read_or_write_role_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            search = "index=netfw | stats count"
            desired = self.rendered_view(root, search)
            state = {
                "view_exists": True,
                "view_content": desired,
                "acl": {
                    "owner": "nobody",
                    "sharing": "app",
                    "perms": {"read": ["power", "user"], "write": ["admin"]},
                },
            }
            result, _state_path, _log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "status",
                "--dashboard-name",
                "net_overview",
                "--search",
                search,
                "--read-roles",
                "user,power,power",
                "--write-roles",
                "power",
            )
            self.assertNotEqual(result.returncode, 0)
            evidence = json.loads(
                (root / "rendered" / "dashboard-studio" / "state" / "live-status.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(evidence["acl"]["read_roles_match"])
            self.assertFalse(evidence["acl"]["write_roles_match"])
            self.assertEqual(evidence["acl"]["expected"]["read"], ["power", "user"])
            self.assertEqual(evidence["acl"]["expected"]["write"], ["power"])

    def test_apply_preflight_failure_makes_no_rest_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = {
                "fail_collection": True,
                "view_exists": False,
                "view_content": "",
                "acl": {"owner": "admin", "sharing": "user", "perms": {"read": [], "write": []}},
            }
            result, _state_path, log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "apply",
                "--dashboard-name",
                "net_overview",
                "--search",
                "index=main",
            )
            self.assertNotEqual(result.returncode, 0)
            evidence_path = root / "rendered" / "dashboard-studio" / "state" / "apply-evidence.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["failure_step"], "preflight")
            self.assertEqual(evidence["rollback"], "not-required")
            calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            live_calls = [call for call in calls if not call["url"].endswith("/services/auth/login")]
            self.assertFalse(any(call["method"] in {"POST", "DELETE"} for call in live_calls))

    def test_acl_failure_retains_new_view_for_reviewed_manual_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = {
                "fail_acl_count": 1,
                "view_exists": False,
                "view_content": "",
                "acl": {"owner": "admin", "sharing": "user", "perms": {"read": [], "write": []}},
            }
            result, state_path, log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "apply",
                "--dashboard-name",
                "net_overview",
                "--search",
                "index=main",
            )
            self.assertNotEqual(result.returncode, 0)
            final_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(final_state["view_exists"])
            evidence_path = root / "rendered" / "dashboard-studio" / "state" / "apply-evidence.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["failure_step"], "acl-write")
            self.assertEqual(evidence["rollback"], "partial")
            self.assertTrue(evidence["partial_failure"])
            self.assertTrue(evidence["manual_cleanup"]["required"])
            calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertFalse(any(call["method"] == "DELETE" for call in calls))

    def test_apply_succeeds_only_after_exact_content_and_acl_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            search = "index=main | stats count"
            desired = self.rendered_view(root, search)
            state = {
                "view_exists": False,
                "view_content": "",
                "acl": {"owner": "admin", "sharing": "user", "perms": {"read": [], "write": []}},
            }
            result, state_path, _log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "apply",
                "--dashboard-name",
                "net_overview",
                "--search",
                search,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            final_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(final_state["view_content"], desired)
            self.assertEqual(final_state["acl"]["owner"], "nobody")
            self.assertEqual(final_state["acl"]["sharing"], "app")
            self.assertEqual(final_state["acl"]["perms"]["read"], ["*"])
            self.assertEqual(final_state["acl"]["perms"]["write"], [""])
            readback_path = root / "rendered" / "dashboard-studio" / "state" / "apply-readback.json"
            readback = json.loads(readback_path.read_text(encoding="utf-8"))
            self.assertTrue(readback["match"])
            self.assertTrue(readback["acl"]["read_roles_match"])
            self.assertTrue(readback["acl"]["write_roles_match"])
            evidence_path = root / "rendered" / "dashboard-studio" / "state" / "apply-evidence.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["result"], "succeeded")
            self.assertEqual(evidence["rollback"], "not-required")

    def test_readback_failure_retains_existing_view_with_private_recovery_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            original_content = '<dashboard version="2"><label>Previous</label><definition><![CDATA[{}]]></definition></dashboard>\n'
            original_acl = {
                "owner": "admin",
                "sharing": "user",
                "perms": {"read": ["power"], "write": ["admin"]},
            }
            state = {
                "fail_readback_after_acl_write": True,
                "view_exists": True,
                "view_content": original_content,
                "original_content": original_content,
                "acl": original_acl,
            }
            result, state_path, log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "apply",
                "--dashboard-name",
                "net_overview",
                "--search",
                "index=main | stats count",
                "--accept-overwrite",
            )
            self.assertNotEqual(result.returncode, 0)
            final_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertNotEqual(final_state["view_content"], original_content)
            self.assertEqual(final_state["acl"]["owner"], "nobody")
            self.assertEqual(final_state["acl"]["sharing"], "app")
            evidence_path = root / "rendered" / "dashboard-studio" / "state" / "apply-evidence.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["failure_step"], "readback")
            self.assertEqual(evidence["rollback"], "partial")
            self.assertTrue(evidence["manual_cleanup"]["required"])
            cleanup = Path(evidence["manual_cleanup"]["private_snapshot_path"])
            self.assertEqual(cleanup.stat().st_mode & 0o777, 0o700)
            for name in ("view-before.raw", "acl-before.raw", "view-current.raw", "acl-current.raw"):
                self.assertEqual((cleanup / name).stat().st_mode & 0o777, 0o600)
            calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            content_posts = [
                call for call in calls
                if call["method"] == "POST"
                and call["url"].split("?", 1)[0].endswith("/data/ui/views/net_overview")
            ]
            acl_posts = [
                call for call in calls
                if call["method"] == "POST"
                and call["url"].split("?", 1)[0].endswith("/data/ui/views/net_overview/acl")
            ]
            self.assertEqual(len(content_posts), 1)
            self.assertEqual(len(acl_posts), 1)

    def test_rollback_failure_writes_private_redacted_partial_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            secret_marker = "super-sensitive-dashboard-search"
            state = {
                "fail_acl_count": 1,
                "view_exists": False,
                "view_content": "",
                "acl": {"owner": "admin", "sharing": "user", "perms": {"read": [], "write": []}},
            }
            result, state_path, _log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "apply",
                "--dashboard-name",
                "net_overview",
                "--search",
                f"index={secret_marker}",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(json.loads(state_path.read_text(encoding="utf-8"))["view_exists"])
            evidence_path = root / "rendered" / "dashboard-studio" / "state" / "apply-evidence.json"
            evidence_text = evidence_path.read_text(encoding="utf-8")
            evidence = json.loads(evidence_text)
            self.assertEqual(evidence["rollback"], "partial")
            self.assertTrue(evidence["partial_failure"])
            self.assertTrue(evidence["redacted"])
            self.assertTrue(evidence["manual_cleanup"]["required"])
            self.assertNotIn(secret_marker, evidence_text)
            self.assertEqual(evidence_path.stat().st_mode & 0o777, 0o600)

    def test_ambiguous_content_response_reconciles_without_restore_post(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            original_content = '<dashboard version="2"><label>Original</label><definition><![CDATA[{}]]></definition></dashboard>\n'
            original_acl = {
                "owner": "admin",
                "sharing": "user",
                "perms": {"read": ["power"], "write": ["admin"]},
            }
            state = {
                "content_write_response_code": 500,
                "view_exists": True,
                "view_content": original_content,
                "original_content": original_content,
                "acl": original_acl,
            }
            result, state_path, log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "apply",
                "--dashboard-name",
                "net_overview",
                "--search",
                "index=main | stats count",
                "--accept-overwrite",
            )
            self.assertNotEqual(result.returncode, 0)
            final_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertNotEqual(final_state["view_content"], original_content)
            self.assertEqual(final_state["acl"], original_acl)
            evidence_path = root / "rendered" / "dashboard-studio" / "state" / "apply-evidence.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["failure_step"], "content-write")
            self.assertEqual(evidence["rollback"], "partial")
            self.assertTrue(evidence["manual_cleanup"]["required"])
            self.assertTrue(any(event["step"] == "content-write-reconcile" for event in evidence["events"]))
            calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            content_posts = [
                call for call in calls
                if call["method"] == "POST"
                and call["url"].split("?", 1)[0].endswith("/data/ui/views/net_overview")
            ]
            self.assertEqual(len(content_posts), 1)

    def test_concurrent_content_change_refuses_destructive_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            concurrent_content = '<dashboard version="2"><label>Concurrent</label><definition><![CDATA[{}]]></definition></dashboard>\n'
            state = {
                "fail_acl_count": 1,
                "concurrent_content_on_acl_failure": concurrent_content,
                "view_exists": False,
                "view_content": "",
                "acl": {"owner": "admin", "sharing": "user", "perms": {"read": [], "write": []}},
            }
            result, state_path, _log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "apply",
                "--dashboard-name",
                "net_overview",
                "--search",
                "index=main",
            )
            self.assertNotEqual(result.returncode, 0)
            final_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(final_state["view_exists"])
            self.assertEqual(final_state["view_content"], concurrent_content)
            evidence_path = root / "rendered" / "dashboard-studio" / "state" / "apply-evidence.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["rollback"], "partial")
            self.assertTrue(evidence["partial_failure"])
            self.assertTrue(evidence["concurrent_or_unverifiable"])
            self.assertTrue(any(event["step"] == "rollback-view" and event["status"] == "manual-cleanup-required" for event in evidence["events"]))

    def test_unexpected_local_error_after_content_write_retains_state_for_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            original_content = '<dashboard version="2"><label>Original</label><definition><![CDATA[{}]]></definition></dashboard>\n'
            original_acl = {
                "owner": "admin",
                "sharing": "user",
                "perms": {"read": ["power"], "write": ["admin"]},
            }
            state = {
                "inject_local_error_after_content": True,
                "view_exists": True,
                "view_content": original_content,
                "original_content": original_content,
                "acl": original_acl,
            }
            result, state_path, _log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "apply",
                "--dashboard-name",
                "net_overview",
                "--search",
                "index=main",
                "--accept-overwrite",
            )
            self.assertNotEqual(result.returncode, 0)
            final_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(final_state["view_exists"])
            self.assertNotEqual(final_state["view_content"], original_content)
            self.assertEqual(final_state["acl"], original_acl)
            evidence_path = root / "rendered" / "dashboard-studio" / "state" / "apply-evidence.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["failure_step"], "unexpected-exit")
            self.assertEqual(evidence["rollback"], "partial")
            self.assertTrue(evidence["manual_cleanup"]["required"])

    def test_concurrent_edit_after_reconcile_get_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            original = '<dashboard version="2"><label>Original</label></dashboard>\n'
            concurrent = '<dashboard version="2"><label>Concurrent after GET</label></dashboard>\n'
            state = {
                "fail_acl_count": 1,
                "inject_after_reconcile_acl_get": True,
                "concurrent_content_after_reconcile": concurrent,
                "view_exists": True,
                "view_content": original,
                "acl": {
                    "owner": "admin",
                    "sharing": "user",
                    "perms": {"read": ["power"], "write": ["admin"]},
                },
            }
            result, state_path, log_path = self.run_live_setup(
                root,
                state,
                "--phase",
                "apply",
                "--dashboard-name",
                "net_overview",
                "--search",
                "index=main",
                "--accept-overwrite",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["view_content"], concurrent)
            calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            content_posts = [
                call for call in calls
                if call["method"] == "POST"
                and call["url"].split("?", 1)[0].endswith("/data/ui/views/net_overview")
            ]
            self.assertEqual(len(content_posts), 1)

    def test_failure_reconciliation_has_no_restore_or_delete_implementation(self) -> None:
        setup = SETUP.read_text(encoding="utf-8")
        helper = STATE_HELPER.read_text(encoding="utf-8")
        self.assertNotIn("rollback_existing_view", setup)
        self.assertNotIn("view-form", helper)
        self.assertNotIn("acl-form", helper)
        self.assertNotIn("-X DELETE", setup)

    def test_sigint_and_sigterm_are_routed_through_exit_compensation(self) -> None:
        setup = SETUP.read_text(encoding="utf-8")
        self.assertIn("trap 'transaction_exit_trap $?' EXIT", setup)
        self.assertIn("trap 'exit 130' INT", setup)
        self.assertIn("trap 'exit 143' TERM", setup)

    def test_transaction_helper_uses_python310_compatible_timezone(self) -> None:
        helper = STATE_HELPER.read_text(encoding="utf-8")
        self.assertNotIn("from datetime import UTC", helper)
        self.assertIn("timezone.utc", helper)


if __name__ == "__main__":
    unittest.main()
