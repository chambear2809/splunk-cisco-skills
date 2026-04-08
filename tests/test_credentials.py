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
    "SPLUNK_INGEST_PROFILE",
    "SPLUNK_DEPLOYER_PROFILE",
    "SPLUNK_CLUSTER_MANAGER_PROFILE",
    "SPLUNK_PLATFORM",
    "SPLUNK_DELIVERY_PLANE",
    "SPLUNK_TARGET_ROLE",
    "SPLUNK_SEARCH_TARGET_ROLE",
    "SPLUNK_SEARCH_API_URI",
    "SPLUNK_HOST",
    "SPLUNK_MGMT_PORT",
    "SPLUNK_URI",
    "SPLUNK_HEC_URL",
    "SPLUNK_SSH_HOST",
    "SPLUNK_SSH_PORT",
    "SPLUNK_SSH_USER",
    "SPLUNK_SSH_PASS",
    "SPLUNK_REMOTE_TMPDIR",
    "SPLUNK_REMOTE_SUDO",
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
    profile_pattern = re.compile(r"PROFILE_([A-Za-z0-9][A-Za-z0-9_-]*)__([A-Za-z_][A-Za-z0-9_]*)$")

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
            except (ValueError, SyntaxError):
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
                return resolve_value(profile_values[prof][name], prof, stack | {name})
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
            result[k] = resolve_value(profile_values[selected_profile][k], selected_profile, {k})
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

    def test_profile_can_derive_uri_from_profile_host(self):
        text = textwrap.dedent("""\
            PROFILE_onprem__SPLUNK_HOST="10.110.253.5"
            PROFILE_onprem__SPLUNK_SEARCH_API_URI="https://${SPLUNK_HOST}:8089"
            PROFILE_onprem__SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
        """)
        result = parse_credential_file(text, "onprem")
        self.assertEqual(result["SPLUNK_HOST"], "10.110.253.5")
        self.assertEqual(result["SPLUNK_SEARCH_API_URI"], "https://10.110.253.5:8089")
        self.assertEqual(result["SPLUNK_URI"], "https://10.110.253.5:8089")

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

    def test_target_role_keys_are_allowed(self):
        text = textwrap.dedent("""\
            SPLUNK_TARGET_ROLE="search-tier"
            SPLUNK_SEARCH_TARGET_ROLE="heavy-forwarder"
        """)
        result = parse_credential_file(text)
        self.assertEqual(result["SPLUNK_TARGET_ROLE"], "search-tier")
        self.assertEqual(result["SPLUNK_SEARCH_TARGET_ROLE"], "heavy-forwarder")

    def test_profile_target_role_selection(self):
        text = textwrap.dedent("""\
            PROFILE_cloud__SPLUNK_TARGET_ROLE="search-tier"
            PROFILE_hf__SPLUNK_TARGET_ROLE="heavy-forwarder"
        """)
        cloud = parse_credential_file(text, "cloud")
        hf = parse_credential_file(text, "hf")
        self.assertEqual(cloud["SPLUNK_TARGET_ROLE"], "search-tier")
        self.assertEqual(hf["SPLUNK_TARGET_ROLE"], "heavy-forwarder")

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

    def test_remote_bootstrap_keys_allowed(self):
        text = textwrap.dedent("""\
            SPLUNK_REMOTE_TMPDIR="/var/tmp"
            SPLUNK_REMOTE_SUDO="true"
        """)
        result = parse_credential_file(text)
        self.assertEqual(result["SPLUNK_REMOTE_TMPDIR"], "/var/tmp")
        self.assertEqual(result["SPLUNK_REMOTE_SUDO"], "true")


class TestCredentialFileRoundtrip(unittest.TestCase):
    """Test that the example credentials file parses without errors."""

    def test_example_file_parses(self):
        example_path = os.path.join(os.path.dirname(__file__), "..", "credentials.example")
        if not os.path.exists(example_path):
            self.skipTest("credentials.example not found")
        with open(example_path, encoding="utf-8") as f:
            text = f.read()
        result = parse_credential_file(text)
        self.assertIn("SPLUNK_HOST", result)
        self.assertEqual(result["SPLUNK_HOST"], "your-splunk-host")


class TestCredentialParserParity(unittest.TestCase):
    """Verify the Python reimplementation in this file matches the embedded
    Python in skills/shared/lib/credentials.sh."""

    CREDENTIALS_SH = os.path.join(
        os.path.dirname(__file__),
        "..",
        "skills",
        "shared",
        "lib",
        "credentials.sh",
    )

    @classmethod
    def _extract_embedded_python(cls) -> str:
        """Extract the heredoc Python from _read_credential_file_entries."""
        with open(cls.CREDENTIALS_SH, encoding="utf-8") as f:
            content = f.read()

        start = content.index('python3 - "$file_path" "$selected_profile" <<\'PY\'\n')
        start = content.index("\n", start) + 1
        end = content.index("\nPY\n", start)
        return content[start:end]

    def _run_embedded_parser(self, cred_text: str, profile: str = "") -> dict[str, str]:
        import subprocess
        import tempfile

        embedded_py = self._extract_embedded_python()
        wrapper = (
            "import ast\nimport os\nimport re\nimport sys\npath = sys.argv[1]\nselected_profile = sys.argv[2].strip()\n"
        )
        body = embedded_py.split("selected_profile = sys.argv[2].strip()\n", 1)[-1]
        script = wrapper + body

        with tempfile.NamedTemporaryFile(mode="w", suffix=".credentials", delete=False, encoding="utf-8") as cred_f:
            cred_f.write(cred_text)
            cred_path = cred_f.name

        try:
            result = subprocess.run(
                ["python3", "-c", script, cred_path, profile],
                capture_output=True,
                check=True,
            )
            pairs = result.stdout.split(b"\0")
            parsed = {}
            i = 0
            while i + 1 < len(pairs):
                key = pairs[i].decode("utf-8")
                value = pairs[i + 1].decode("utf-8")
                if key:
                    parsed[key] = value
                i += 2
            return parsed
        finally:
            os.unlink(cred_path)

    PARITY_CASES = [
        (
            "flat keys",
            textwrap.dedent("""\
                SPLUNK_HOST="myhost"
                SPLUNK_MGMT_PORT="8089"
                SPLUNK_USER="admin"
            """),
            "",
        ),
        (
            "profile override",
            textwrap.dedent("""\
                SPLUNK_HOST="default-host"
                PROFILE_prod__SPLUNK_HOST="prod-host"
                PROFILE_prod__SPLUNK_USER="admin"
            """),
            "prod",
        ),
        (
            "variable references",
            textwrap.dedent("""\
                SPLUNK_HOST="myhost"
                SPLUNK_MGMT_PORT="8089"
                SPLUNK_SEARCH_API_URI="https://${SPLUNK_HOST}:${SPLUNK_MGMT_PORT}"
            """),
            "",
        ),
        (
            "single quotes",
            textwrap.dedent("""\
                SPLUNK_HOST='quoted-host'
                SPLUNK_USER='admin'
            """),
            "",
        ),
        (
            "unquoted values",
            textwrap.dedent("""\
                SPLUNK_HOST=barehost
                SPLUNK_MGMT_PORT=8089
            """),
            "",
        ),
        (
            "comments and blanks",
            textwrap.dedent("""\
                # This is a comment
                SPLUNK_HOST="myhost"

                # Another comment
                SPLUNK_USER="admin"
            """),
            "",
        ),
        (
            "profile with cross-references",
            textwrap.dedent("""\
                SPLUNK_HOST="global-host"
                PROFILE_lab__SPLUNK_HOST="lab-host"
                PROFILE_lab__SPLUNK_SEARCH_API_URI="https://${SPLUNK_HOST}:8089"
            """),
            "lab",
        ),
    ]

    def test_parity_across_cases(self):
        if not os.path.exists(self.CREDENTIALS_SH):
            self.skipTest("credentials.sh not found")

        for label, cred_text, profile in self.PARITY_CASES:
            with self.subTest(case=label):
                embedded_result = self._run_embedded_parser(cred_text, profile)
                reimpl_result = parse_credential_file(cred_text, profile)
                self.assertEqual(
                    reimpl_result,
                    embedded_result,
                    f"Parity mismatch for case '{label}'",
                )

    def test_example_file_parity(self):
        example_path = os.path.join(os.path.dirname(__file__), "..", "credentials.example")
        if not os.path.exists(example_path):
            self.skipTest("credentials.example not found")
        if not os.path.exists(self.CREDENTIALS_SH):
            self.skipTest("credentials.sh not found")

        with open(example_path, encoding="utf-8") as f:
            text = f.read()

        embedded_result = self._run_embedded_parser(text)
        reimpl_result = parse_credential_file(text)
        self.assertEqual(reimpl_result, embedded_result)


if __name__ == "__main__":
    unittest.main()
