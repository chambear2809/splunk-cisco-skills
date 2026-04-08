#!/usr/bin/env python3
"""Direct unit tests for skills/shared/lib/shell_helpers.py.

These complement the indirect coverage shell_helpers gets through the
bash regression tests by exercising each Python function in isolation.
"""

import contextlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HELPERS_PATH = REPO_ROOT / "skills" / "shared" / "lib" / "shell_helpers.py"

sys.path.insert(0, str(HELPERS_PATH.parent))
import shell_helpers  # noqa: E402


class TestFormUrlencodePairs(unittest.TestCase):
    """Tests for form_urlencode_pairs()."""

    def test_single_pair(self):
        self.assertEqual(shell_helpers.form_urlencode_pairs(["key", "val"]), "key=val")

    def test_multiple_pairs(self):
        result = shell_helpers.form_urlencode_pairs(["a", "1", "b", "2"])
        self.assertEqual(result, "a=1&b=2")

    def test_special_characters_encoded(self):
        result = shell_helpers.form_urlencode_pairs(["user name", "a&b=c"])
        self.assertEqual(result, "user+name=a%26b%3Dc")

    def test_empty_value(self):
        result = shell_helpers.form_urlencode_pairs(["key", ""])
        self.assertEqual(result, "key=")

    def test_odd_number_of_args_raises(self):
        with self.assertRaises(SystemExit) as ctx:
            shell_helpers.form_urlencode_pairs(["only_key"])
        self.assertEqual(ctx.exception.code, 1)

    def test_empty_args(self):
        self.assertEqual(shell_helpers.form_urlencode_pairs([]), "")

    def test_unicode_values(self):
        result = shell_helpers.form_urlencode_pairs(["name", "caf\u00e9"])
        self.assertIn("caf", result)
        self.assertIn("%", result)

    def test_slash_and_at_encoded(self):
        result = shell_helpers.form_urlencode_pairs(["url", "http://a@b/c"])
        self.assertNotIn("@", result.split("=", 1)[1])
        self.assertNotIn("/", result.split("=", 1)[1])


class TestUrlencode(unittest.TestCase):
    """Tests for urlencode()."""

    def test_plain_string(self):
        self.assertEqual(shell_helpers.urlencode("hello"), "hello")

    def test_spaces_encoded(self):
        self.assertEqual(shell_helpers.urlencode("hello world"), "hello%20world")

    def test_slash_encoded(self):
        self.assertEqual(shell_helpers.urlencode("a/b"), "a%2Fb")

    def test_empty_string(self):
        self.assertEqual(shell_helpers.urlencode(""), "")

    def test_already_encoded_chars(self):
        result = shell_helpers.urlencode("%20")
        self.assertEqual(result, "%2520")


class TestIsSensitiveKey(unittest.TestCase):
    """Tests for _is_sensitive_key()."""

    def test_plain_password(self):
        self.assertTrue(shell_helpers._is_sensitive_key("password"))

    def test_mixed_case(self):
        self.assertTrue(shell_helpers._is_sensitive_key("Password"))

    def test_prefixed_key(self):
        self.assertTrue(shell_helpers._is_sensitive_key("admin_password"))

    def test_api_key_with_underscore(self):
        self.assertTrue(shell_helpers._is_sensitive_key("api_key"))

    def test_client_secret(self):
        self.assertTrue(shell_helpers._is_sensitive_key("client-secret"))

    def test_session_key(self):
        self.assertTrue(shell_helpers._is_sensitive_key("sessionKey"))

    def test_non_sensitive(self):
        self.assertFalse(shell_helpers._is_sensitive_key("hostname"))

    def test_non_sensitive_name(self):
        self.assertFalse(shell_helpers._is_sensitive_key("username"))

    def test_integer_key(self):
        self.assertFalse(shell_helpers._is_sensitive_key(42))


class TestRedactJson(unittest.TestCase):
    """Tests for _redact_json()."""

    def test_simple_dict(self):
        data = {"name": "admin", "password": "s3cret"}
        result = shell_helpers._redact_json(data)
        self.assertEqual(result["name"], "admin")
        self.assertEqual(result["password"], "REDACTED")

    def test_nested_dict(self):
        data = {"auth": {"token": "abc123", "user": "me"}}
        result = shell_helpers._redact_json(data)
        self.assertEqual(result["auth"]["token"], "REDACTED")
        self.assertEqual(result["auth"]["user"], "me")

    def test_list_of_dicts(self):
        data = [{"secret": "x"}, {"name": "y"}]
        result = shell_helpers._redact_json(data)
        self.assertEqual(result[0]["secret"], "REDACTED")
        self.assertEqual(result[1]["name"], "y")

    def test_non_dict_passthrough(self):
        self.assertEqual(shell_helpers._redact_json("plain"), "plain")
        self.assertEqual(shell_helpers._redact_json(42), 42)

    def test_empty_dict(self):
        self.assertEqual(shell_helpers._redact_json({}), {})


class TestRedactText(unittest.TestCase):
    """Tests for _redact_text()."""

    def test_key_equals_value(self):
        result = shell_helpers._redact_text("password=hunter2")
        self.assertIn("REDACTED", result)
        self.assertNotIn("hunter2", result)

    def test_key_colon_value(self):
        result = shell_helpers._redact_text('token: "abc123"')
        self.assertIn("REDACTED", result)
        self.assertNotIn("abc123", result)

    def test_non_sensitive_preserved(self):
        result = shell_helpers._redact_text("hostname=splunk.local")
        self.assertIn("splunk.local", result)

    def test_multiple_sensitive_keys(self):
        text = "password=x&secret=y&name=z"
        result = shell_helpers._redact_text(text)
        self.assertNotIn("=x", result)
        self.assertNotIn("=y", result)
        self.assertIn("name=z", result)


class TestSanitizeResponse(unittest.TestCase):
    """Tests for sanitize_response()."""

    def test_json_body(self):
        body = json.dumps({"password": "secret", "status": "ok"})
        result = shell_helpers.sanitize_response(body)
        parsed = json.loads(result)
        self.assertEqual(parsed["password"], "REDACTED")
        self.assertEqual(parsed["status"], "ok")

    def test_plain_text_fallback(self):
        result = shell_helpers.sanitize_response("token=abc123")
        self.assertIn("REDACTED", result)
        self.assertNotIn("abc123", result)

    def test_max_lines_truncation(self):
        body = "\n".join(f"line{i}" for i in range(50))
        result = shell_helpers.sanitize_response(body, max_lines=5)
        self.assertEqual(len(result.splitlines()), 5)

    def test_empty_string(self):
        result = shell_helpers.sanitize_response("")
        self.assertEqual(result, "")

    def test_nested_json_redaction(self):
        body = json.dumps({"outer": {"apikey": "k", "info": "safe"}})
        result = shell_helpers.sanitize_response(body)
        parsed = json.loads(result)
        self.assertEqual(parsed["outer"]["apikey"], "REDACTED")
        self.assertEqual(parsed["outer"]["info"], "safe")


class TestCLIDispatch(unittest.TestCase):
    """Tests for the CLI dispatcher via subprocess."""

    def _run(self, *args, stdin_text=None, fd3_text=None):
        """Run shell_helpers.py as a subprocess."""
        cmd = [sys.executable, str(HELPERS_PATH), *args]
        env = os.environ.copy()
        if fd3_text is not None:
            r_fd, w_fd = os.pipe()
            os.write(w_fd, fd3_text.encode())
            os.close(w_fd)
            os.set_inheritable(r_fd, True)
            env["_FD3_READ"] = str(r_fd)
            cmd_str = (
                f"import os, sys; "
                f"os.dup2(int(os.environ['_FD3_READ']), 3); "
                f"sys.argv = {[str(HELPERS_PATH), *list(args)]!r}; "
                f"exec(open({str(HELPERS_PATH)!r}).read())"
            )
            try:
                result = subprocess.run(
                    [sys.executable, "-c", cmd_str],
                    capture_output=True,
                    text=True,
                    env=env,
                    close_fds=False,
                )
            finally:
                with contextlib.suppress(OSError):
                    os.close(r_fd)
            return result
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            input=stdin_text,
        )

    def test_form_urlencode_pairs_cli(self):
        r = self._run("form_urlencode_pairs", "a", "1", "b", "2")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "a=1&b=2")

    def test_urlencode_cli(self):
        r = self._run("urlencode", "hello world")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "hello%20world")

    def test_curl_config_escape_cli(self):
        r = self._run("curl_config_escape", 'a\\b"c')
        self.assertEqual(r.returncode, 0)
        self.assertIn("\\\\", r.stdout)
        self.assertIn('\\"', r.stdout)

    def test_sanitize_response_cli(self):
        body = json.dumps({"password": "x", "ok": True})
        r = self._run("sanitize_response", fd3_text=body)
        self.assertEqual(r.returncode, 0)
        parsed = json.loads(r.stdout)
        self.assertEqual(parsed["password"], "REDACTED")

    def test_sanitize_response_cli_max_lines(self):
        body = "\n".join(f"line{i}" for i in range(50))
        r = self._run("sanitize_response", "3", fd3_text=body)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(r.stdout.strip().splitlines()), 3)

    def test_is_splunk_package_valid(self):
        with tempfile.NamedTemporaryFile(suffix=".tgz", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            with tarfile.open(tmp_path, "w:gz") as tar:
                import io

                info = tarfile.TarInfo(name="test.txt")
                info.size = 4
                tar.addfile(info, io.BytesIO(b"test"))
            r = self._run("is_splunk_package", tmp_path)
            self.assertEqual(r.returncode, 0)
        finally:
            os.unlink(tmp_path)

    def test_is_splunk_package_invalid(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as tmp:
            tmp.write("not a tarball")
            tmp_path = tmp.name
        try:
            r = self._run("is_splunk_package", tmp_path)
            self.assertEqual(r.returncode, 1)
        finally:
            os.unlink(tmp_path)

    def test_unknown_subcommand(self):
        r = self._run("no_such_command")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Unknown subcommand", r.stderr)

    def test_no_subcommand(self):
        r = subprocess.run(
            [sys.executable, str(HELPERS_PATH)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("Usage", r.stderr)


if __name__ == "__main__":
    unittest.main()
