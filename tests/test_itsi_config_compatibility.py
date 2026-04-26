from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "skills" / "splunk-itsi-config" / "scripts" / "itsi_compatibility_report.py"


def load_report_module():
    spec = importlib.util.spec_from_file_location("itsi_compatibility_report", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class ItsiCompatibilityReportTests(unittest.TestCase):
    def test_report_covers_supported_guarded_and_excluded_categories(self) -> None:
        module = load_report_module()
        statuses = {row["status"] for row in module.COMPATIBILITY_ROWS}
        rendered = module.render_markdown()

        self.assertEqual({"supported", "guarded", "excluded"}, statuses)
        self.assertIn("event_management_interface", rendered)
        self.assertIn("allow_operational_action", rendered)
        self.assertIn("notable_event_group", rendered)


if __name__ == "__main__":
    unittest.main()
