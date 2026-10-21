"""Verify final HEC details after preparation changes the token configuration."""

import json
import tempfile
from pathlib import Path

from tests.regression_helpers import ShellScriptRegressionBase


class SC4xHECSnapshotTests(ShellScriptRegressionBase):
    def test_final_details_and_secret_file_follow_default_index_update(self):
        cases = (
            (
                "sc4s",
                "sc4s",
                self.build_mock_sc4s_env,
                "skills/splunk-connect-for-syslog-setup/scripts/setup.sh",
            ),
            (
                "sc4snmp",
                "netops",
                self.build_mock_sc4snmp_env,
                "skills/splunk-connect-for-snmp-setup/scripts/setup.sh",
            ),
        )
        for name, expected_index, build_env, script in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                env, state_file = build_env(tmp_path)
                token_value = f"synthetic-{name}-snapshot-token"
                state = json.loads(state_file.read_text(encoding="utf-8"))
                state["hec_tokens"][name] = {
                    "disabled": "true",
                    "useACK": "0",
                    "indexes": "",
                    "index": "main",
                    "default_index": "main",
                    "token": token_value,
                }
                state_file.write_text(json.dumps(state), encoding="utf-8")
                token_file = tmp_path / "hec.token"

                result = self.run_script(
                    script,
                    "--splunk-prep",
                    "--hec-only",
                    "--write-hec-token-file",
                    str(token_file),
                    env=env,
                )

                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0, msg=output)
                self.assertIn(f"HEC token '{name}' default index: {expected_index}", output)
                self.assertNotIn(f"HEC token '{name}' default index: main", output)
                self.assertNotIn(token_value, output)
                self.assertEqual(token_file.read_text(encoding="utf-8"), token_value + "\n")
                self.assertEqual(token_file.stat().st_mode & 0o777, 0o600)
                final = json.loads(state_file.read_text(encoding="utf-8"))["hec_tokens"][name]
                self.assertEqual(final["disabled"], "false")
                self.assertEqual(final["default_index"], expected_index)
