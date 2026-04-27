from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "skills" / "splunk-itsi-config" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.common import write_yaml  # noqa: E402


class ItsiCommonTests(unittest.TestCase):
    def test_write_yaml_quotes_reserved_scalars_and_mapping_keys_for_roundtrip(self) -> None:
        payload = {
            "correlation_searches": [
                {
                    "title": "Dispatch Window",
                    "payload": {
                        "dispatch.latest_time": "@m",
                        "eai:acl": {"app": "SA-ITOA"},
                        "date_key": "2024-01-01",
                        "numeric_string": "123",
                        "float_string": "1.5",
                        "zero_string": "0",
                        "ip_string": "192.0.2.10",
                        "time_string": "12:34",
                        "2024-01-01": "date-shaped key",
                    },
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tempdir:
            spec_path = Path(tempdir) / "exported.native.yaml"
            json_path = Path(tempdir) / "exported.native.json"
            write_yaml(spec_path, payload)

            completed = subprocess.run(
                [
                    "ruby",
                    str(SCRIPTS_DIR / "spec_to_json.rb"),
                    "--spec",
                    str(spec_path),
                    "--output",
                    str(json_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            parsed = json.loads(json_path.read_text(encoding="utf-8"))

        self.assertEqual(parsed, payload)


if __name__ == "__main__":
    unittest.main()
