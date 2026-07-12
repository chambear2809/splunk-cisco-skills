"""Regression coverage for the generated skill UX catalog."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"
CATALOG_PATH = REPO_ROOT / "SKILL_UX_CATALOG.md"
GENERATOR = REPO_ROOT / "skills/shared/scripts/generate_skill_ux_catalog.py"
PRODUCT_REGISTRY = SKILLS_DIR / "shared" / "skill_product_registry.json"


def skill_names() -> set[str]:
    return {
        path.name
        for path in SKILLS_DIR.iterdir()
        if path.is_dir()
        and path.name != "shared"
        and not path.name.startswith(".")
        and (path / "SKILL.md").is_file()
    }


def product_registry() -> dict[str, Any]:
    return json.loads(PRODUCT_REGISTRY.read_text(encoding="utf-8"))


def classified_skills() -> list[str]:
    return [
        skill
        for product in product_registry()["products"]
        for capability in product["capabilities"]
        for skill in capability["skills"]
    ]


def product_for(skill_name: str) -> str:
    for product in product_registry()["products"]:
        for capability in product["capabilities"]:
            if skill_name in capability["skills"]:
                return product["name"]
    raise AssertionError(f"unclassified skill: {skill_name}")


class SkillUXCatalogTests(unittest.TestCase):
    def test_catalog_is_current(self) -> None:
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_catalog_covers_every_skill_once(self) -> None:
        text = CATALOG_PATH.read_text(encoding="utf-8")
        rows = re.findall(r"^\| `([^`]+)` \|", text, flags=re.MULTILINE)

        self.assertEqual(set(rows), skill_names())
        self.assertEqual(len(rows), len(set(rows)))

    def test_product_registry_covers_every_skill_once(self) -> None:
        names = classified_skills()

        self.assertEqual(set(names), skill_names())
        self.assertEqual(len(names), len(set(names)))

    def test_catalog_follows_registry_product_order(self) -> None:
        text = CATALOG_PATH.read_text(encoding="utf-8")
        headings = re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
        product_headings = [
            heading
            for heading in headings
            if heading not in {"How To Use This Catalog", "Product Index"}
        ]
        expected = [product["name"] for product in product_registry()["products"]]

        self.assertEqual(product_headings, expected)

    def test_ambiguous_skills_have_explicit_product_owners(self) -> None:
        expected = {
            "cisco-appdynamics-setup": "Splunk Platform",
            "cisco-talos-intelligence-setup": (
                "Splunk Enterprise Security and Security Portfolio"
            ),
            "galileo-agent-control-setup": "Splunk Observability Cloud",
            "galileo-mcp-server-setup": "Splunk Observability Cloud",
            "galileo-platform-setup": "Splunk Observability Cloud",
            "splunk-cloud-acs-admin-setup": "Splunk Cloud Platform",
            "splunk-enterprise-host-setup": "Splunk Enterprise",
            "splunk-itsi-config": "Splunk IT Service Intelligence",
            "splunk-microsoft-security-ta-setup": "Splunk Platform",
            "splunk-observability-otel-collector-setup": "Splunk Observability Cloud",
            "splunk-oncall-setup": "Splunk On-Call",
            "splunk-security-appliance-ta-setup": "Splunk Platform",
            "splunk-soar-setup": "Splunk SOAR",
        }

        for skill_name, product_name in expected.items():
            with self.subTest(skill=skill_name):
                self.assertEqual(product_for(skill_name), product_name)

    def test_catalog_keeps_operator_safe_path_visible(self) -> None:
        text = CATALOG_PATH.read_text(encoding="utf-8")

        self.assertIn("Safe first command", text)
        self.assertIn("Validation", text)
        self.assertIn("never paste secrets into chat or argv", text)
        self.assertIn("Canonical skill directories remain flat", text)


if __name__ == "__main__":
    unittest.main()
