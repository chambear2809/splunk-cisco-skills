#!/usr/bin/env python3
"""Tests for the credential file parser logic extracted from credentials.sh.

Run with: python3 -m unittest tests.test_credentials -v
    or:   python3 -m pytest tests/test_credentials.py -v  (if pytest is installed)
"""
import ast
import os
import re
import textwrap
import unittest


ALLOWED_KEYS = [
    "SPLUNK_PROFILE",
    "SPLUNK_SEARCH_PROFILE",
    "SPLUNK_PLATFORM",
    "SPLUNK_SEARCH_API_URI",
    "SPLUNK_HOST",
    "SPLUNK_MGMT_PORT",
    "SPLUNK_URI",
    "SPLUNK_SSH_HOST",
    "SPLUNK_SSH_PORT",
    "SPLUNK_SSH_USER",
    "SPLUNK_SSH_PASS",
    "SPLUNK_USER",
    "SPLUNK_PASS",
    "SPLUNK_CA_CERT",
    "SPLUNK_CLOUD_STACK",
    "SPLUNK_CLOUD_SEARCH_HEAD",
    "SPLUNK_CLOUD_INDEX_SEARCHABLE_DAYS",
    "ACS_SERVER",
    "STACK_USERNAME",
    "STACK_PASSWORD",
    "STACK_TOKEN",
    "STACK_TOKEN_USER",
    "SPLUNK_USERNAME",
    "SPLUNK_PASSWORD",
    "SB_USER",
    "SB_PASS",
    "SPLUNK_VERIFY_SSL",
    "SPLUNKBASE_VERIFY_SSL",
    "SPLUNKBASE_CA_CERT",
    "APP_DOWNLOAD_VERIFY_SSL",
    "APP_DOWNLOAD_CA_CERT",
]


def parse_credential_file(text: str, selected_profile: str = "") -> dict:
    """Pure-Python reimplementation of _read_credential_file_entries for testing."""
    allowed = set(ALLOWED_KEYS)
    raw_values = {}
    profile_values = {}
    profile_pattern = re.compile(
        r"PROFILE_([A-Za-z0-9][A-Za-z0-9_-]*)__([A-Za-z_][A-Za-z0-9_]*)$"
    )

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in raw_line:
            continue

        key, value = raw_line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            try:
                value = ast.literal_eval(value)
            except Exception:
                value = value[1:-1]

        profile_match = profile_pattern.fullmatch(key)
        if profile_match:
            profile_name, actual_key = profile_match.groups()
            if actual_key not in allowed:
                continue
            profile_values.setdefault(profile_name, {})[actual_key] = value
            continue

        if key not in allowed:
            continue
        raw_values[key] = value

    ref_pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

    def resolve_value(val, prof, stack):
        def repl(match):
            name = match.group(1)
            if name in stack:
                return match.group(0)
            if prof and name in profile_values.get(prof, {}):
                return resolve_value(
                    profile_values[prof][name], prof, stack | {name}
                )
            if name in raw_values:
                return resolve_value(raw_values[name], prof, stack | {name})
            return os.environ.get(name, match.group(0))
        return ref_pattern.sub(repl, val)

    result = {}
    emitted = set()

    if selected_profile and selected_profile in profile_values:
        for k in ALLOWED_KEYS:
            if k not in profile_values[selected_profile]:
                continue
            result[k] = resolve_value(
                profile_values[selected_profile][k], selected_profile, {k}
            )
            emitted.add(k)

    for k in ALLOWED_KEYS:
        if k not in raw_values or k in emitted:
            continue
        result[k] = resolve_value(raw_values[k], selected_profile or None, {k})

    return result


class TestCredentialParsing(unittest.TestCase):
    def test_simple_flat_keys(self):
        text = textwrap.dedent("""\
            SPLUNK_HOST="myhost"
            SPLUNK_MGMT_PORT="8089"
        """)
        result = parse_credential_file(text)
        self.assertEqual(result["SPLUNK_HOST"], "myhost")
        self.assertEqual(result["SPLUNK_MGMT_PORT"], "8089")

    def test_ignores_unknown_keys(self):
        text = 'UNKNOWN_KEY="secret"\nSPLUNK_HOST="ok"\n'
        result = parse_credential_file(text)
        self.assertNotIn("UNKNOWN_KEY", result)
        self.assertEqual(result["SPLUNK_HOST"], "ok")

    def test_ignores_comments_and_blanks(self):
        text = "# comment\n\nSPLUNK_HOST=myhost\n# another\n"
        result = parse_credential_file(text)
        self.assertEqual(result["SPLUNK_HOST"], "myhost")
        self.assertEqual(len(result), 1)

    def test_variable_reference(self):
        text = textwrap.dedent("""\
            SB_USER="admin"
            SPLUNK_USERNAME="${SB_USER}"
        """)
        result = parse_credential_file(text)
        self.assertEqual(result["SPLUNK_USERNAME"], "admin")

    def test_profile_selection(self):
        text = textwrap.dedent("""\
            SPLUNK_HOST="default-host"
            PROFILE_cloud__SPLUNK_HOST="cloud-host"
            PROFILE_cloud__SPLUNK_PLATFORM="cloud"
            PROFILE_onprem__SPLUNK_HOST="onprem-host"
        """)
        result = parse_credential_file(text, "cloud")
        self.assertEqual(result["SPLUNK_HOST"], "cloud-host")
        self.assertEqual(result["SPLUNK_PLATFORM"], "cloud")

    def test_profile_falls_back_to_flat(self):
        text = textwrap.dedent("""\
            SB_USER="shared-user"
            PROFILE_cloud__SPLUNK_PLATFORM="cloud"
        """)
        result = parse_credential_file(text, "cloud")
        self.assertEqual(result["SPLUNK_PLATFORM"], "cloud")
        self.assertEqual(result["SB_USER"], "shared-user")

    def test_cross_reference_in_profile(self):
        text = textwrap.dedent("""\
            STACK_USERNAME="admin"
            PROFILE_cloud__SPLUNK_USER="${STACK_USERNAME}"
        """)
        result = parse_credential_file(text, "cloud")
        self.assertEqual(result["SPLUNK_USER"], "admin")

    def test_circular_reference_does_not_loop(self):
        text = textwrap.dedent("""\
            SPLUNK_HOST="${SPLUNK_URI}"
            SPLUNK_URI="${SPLUNK_HOST}"
        """)
        result = parse_credential_file(text)
        self.assertIn("SPLUNK_HOST", result)
        self.assertIn("SPLUNK_URI", result)

    def test_unquoted_values(self):
        text = "SPLUNK_HOST=myhost\nSPLUNK_MGMT_PORT=8089\n"
        result = parse_credential_file(text)
        self.assertEqual(result["SPLUNK_HOST"], "myhost")
        self.assertEqual(result["SPLUNK_MGMT_PORT"], "8089")

    def test_single_quoted_values(self):
        text = "SPLUNK_HOST='myhost'\n"
        result = parse_credential_file(text)
        self.assertEqual(result["SPLUNK_HOST"], "myhost")

    def test_empty_profile_returns_flat(self):
        text = textwrap.dedent("""\
            SPLUNK_HOST="flat-host"
            PROFILE_cloud__SPLUNK_HOST="cloud-host"
        """)
        result = parse_credential_file(text, "")
        self.assertEqual(result["SPLUNK_HOST"], "flat-host")

    def test_verify_ssl_key_allowed(self):
        text = 'SPLUNK_VERIFY_SSL="true"\n'
        result = parse_credential_file(text)
        self.assertEqual(result["SPLUNK_VERIFY_SSL"], "true")

    def test_tls_ca_and_external_tls_keys_allowed(self):
        text = textwrap.dedent("""\
            SPLUNK_CA_CERT="/tmp/splunk-ca.pem"
            SPLUNKBASE_VERIFY_SSL="false"
            SPLUNKBASE_CA_CERT="/tmp/splunkbase-ca.pem"
            APP_DOWNLOAD_VERIFY_SSL="true"
            APP_DOWNLOAD_CA_CERT="/tmp/download-ca.pem"
        """)
        result = parse_credential_file(text)
        self.assertEqual(result["SPLUNK_CA_CERT"], "/tmp/splunk-ca.pem")
        self.assertEqual(result["SPLUNKBASE_VERIFY_SSL"], "false")
        self.assertEqual(result["SPLUNKBASE_CA_CERT"], "/tmp/splunkbase-ca.pem")
        self.assertEqual(result["APP_DOWNLOAD_VERIFY_SSL"], "true")
        self.assertEqual(result["APP_DOWNLOAD_CA_CERT"], "/tmp/download-ca.pem")


class TestCredentialFileRoundtrip(unittest.TestCase):
    """Test that the example credentials file parses without errors."""

    def test_example_file_parses(self):
        example_path = os.path.join(
            os.path.dirname(__file__), "..", "credentials.example"
        )
        if not os.path.exists(example_path):
            self.skipTest("credentials.example not found")
        with open(example_path) as f:
            text = f.read()
        result = parse_credential_file(text)
        self.assertIn("SPLUNK_HOST", result)
        self.assertEqual(result["SPLUNK_HOST"], "your-splunk-host")


if __name__ == "__main__":
    unittest.main()
