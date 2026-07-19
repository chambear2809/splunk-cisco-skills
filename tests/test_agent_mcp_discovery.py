"""Focused tests for the read-only MCP discovery surface."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent.splunk_cisco_skills_mcp import discovery
from skills.shared.skill_catalog import load_catalog


REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_fake_repository(
    root: Path, skills: tuple[str, ...] = ("demo-skill",)
) -> None:
    skills_root = root / "skills"
    (skills_root / "shared").mkdir(parents=True)
    registry = {
        "schema_version": 2,
        "skill_records": [
            {"name": name, "status": "canonical", "replaced_by": None}
            for name in skills
        ],
        "products": [
            {
                "id": "demo-product",
                "name": "Demo Product",
                "description": "A test-only product.",
                "capabilities": [
                    {
                        "id": "demo-capability",
                        "name": "Demo Capability",
                        "skills": list(skills),
                    }
                ],
            }
        ],
    }
    (skills_root / "shared" / "skill_product_registry.json").write_text(
        json.dumps(registry), encoding="utf-8"
    )
    for name in skills:
        skill_root = skills_root / name
        (skill_root / "scripts").mkdir(parents=True)
        (skill_root / "templates").mkdir()
        (skill_root / "references").mkdir()
        (skill_root / "SKILL.md").write_text(
            "---\n"
            f"name: {name}\n"
            f"description: Discover {name} safely.\n"
            "---\n\n"
            "# Instructions\n",
            encoding="utf-8",
        )
        (skill_root / "reference.md").write_text("# Reference\n", encoding="utf-8")
        (skill_root / "references" / "details.json").write_text(
            '{"safe": true}\n', encoding="utf-8"
        )
        (skill_root / "template.example").write_text(
            "name: example\n", encoding="utf-8"
        )
        (skill_root / "templates" / "unicode.yaml").write_text(
            "name: éx\n", encoding="utf-8"
        )
        for script_name in ("setup.sh", "validate.sh", "render_assets.py"):
            script = skill_root / "scripts" / script_name
            script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            script.chmod(0o755)


class DiscoveryRepositoryTests(unittest.TestCase):
    def test_search_is_product_first_bounded_and_paginated(self) -> None:
        first = discovery.search_skills(limit=7)

        catalog = load_catalog()
        self.assertEqual(first["total"], len(catalog.skills) - len(catalog.aliases))
        self.assertEqual(len(first["skills"]), 7)
        self.assertRegex(first["revision"], r"^[0-9a-f]{64}$")
        self.assertIsNotNone(first["next_cursor"])
        second = discovery.search_skills(limit=7, cursor=first["next_cursor"])
        self.assertTrue(
            {item["skill"] for item in first["skills"]}.isdisjoint(
                item["skill"] for item in second["skills"]
            )
        )
        for item in first["skills"]:
            self.assertEqual(
                set(item),
                {
                    "skill",
                    "description",
                    "status",
                    "replaced_by",
                    "product",
                    "capability",
                },
            )
            self.assertEqual(item["status"], "canonical")
            self.assertIsNone(item["replaced_by"])

    def test_search_filters_by_product_capability_and_query(self) -> None:
        cloud = discovery.search_skills(product="Splunk Cloud Platform", limit=100)
        cisco = discovery.search_skills(capability="cisco-integrations", limit=100)
        exact = discovery.search_skills(query="cisco-product-setup", limit=10)

        self.assertGreater(cloud["total"], 0)
        self.assertTrue(
            all(
                item["product"]["id"] == "splunk-cloud-platform"
                for item in cloud["skills"]
            )
        )
        self.assertGreater(cisco["total"], 0)
        self.assertTrue(
            all(
                item["capability"]["id"] == "cisco-integrations"
                for item in cisco["skills"]
            )
        )
        self.assertEqual(exact["skills"][0]["skill"], "cisco-product-setup")

    def test_generic_search_prefers_canonical_but_exact_alias_still_resolves(
        self,
    ) -> None:
        generic = discovery.search_skills(query="kvstore", limit=10)
        generic_names = [item["skill"] for item in generic["skills"]]
        exact = discovery.search_skills(query="splunk-kvstore-admin", limit=10)
        legacy_manifest = discovery.get_skill_manifest("splunk-kvstore-admin")

        self.assertIn("splunk-kvstore-admin-setup", generic_names)
        self.assertNotIn("splunk-kvstore-admin", generic_names)
        self.assertEqual(exact["skills"][0]["skill"], "splunk-kvstore-admin")
        self.assertEqual(exact["skills"][0]["status"], "deprecated")
        self.assertEqual(
            exact["skills"][0]["replaced_by"], "splunk-kvstore-admin-setup"
        )
        self.assertEqual(legacy_manifest["status"], "deprecated")
        self.assertEqual(
            legacy_manifest["replaced_by"], "splunk-kvstore-admin-setup"
        )

    def test_search_rejects_bad_limits_filters_and_cursors(self) -> None:
        with self.assertRaises(discovery.InvalidDiscoveryRequest):
            discovery.search_skills(limit=0)
        with self.assertRaises(discovery.InvalidDiscoveryRequest):
            discovery.search_skills(limit=True)  # type: ignore[arg-type]
        with self.assertRaises(discovery.DiscoveryNotFound):
            discovery.search_skills(product="not-a-real-product")

        first = discovery.search_skills(limit=1)
        cursor = first["next_cursor"]
        self.assertIsNotNone(cursor)
        assert cursor is not None
        replacement = "A" if cursor[-1] != "A" else "B"
        with self.assertRaises(discovery.InvalidCursor):
            discovery.search_skills(limit=1, cursor=cursor[:-1] + replacement)
        with self.assertRaises(discovery.InvalidCursor):
            discovery.search_skills(query="different", limit=1, cursor=cursor)

    def test_manifest_exposes_only_curated_entrypoints(self) -> None:
        manifest = discovery.get_skill_manifest("cisco-product-setup")
        paths = {entry["path"] for entry in manifest["entrypoints"]}

        self.assertEqual(
            paths,
            {"scripts/setup.sh", "scripts/validate.sh"},
        )
        self.assertNotIn("scripts/build_catalog.py", paths)
        self.assertEqual(manifest["product"]["id"], "shared-and-cross-product")
        self.assertEqual(
            {item["kind"] for item in manifest["resources"]},
            {"instructions", "reference", "template"},
        )
        self.assertNotIn(
            "read-only",
            {entry["risk"] for entry in manifest["entrypoints"]},
        )

    def test_file_listing_and_bounded_read_use_byte_offsets(self) -> None:
        listing = discovery.list_skill_files("splunk-stream-setup", "template", limit=2)
        self.assertEqual(len(listing["files"]), 2)
        self.assertGreater(listing["total"], 2)
        self.assertIsNotNone(listing["next_cursor"])

        first = discovery.read_skill_file(
            "cisco-product-setup", "SKILL.md", offset=0, max_bytes=64
        )
        second = discovery.read_skill_file(
            "cisco-product-setup",
            "SKILL.md",
            offset=first["next_offset"],
            max_bytes=64,
        )
        self.assertLessEqual(len(first["text"].encode("utf-8")), 64)
        self.assertEqual(second["offset"], first["next_offset"])
        self.assertGreater(second["next_offset"], second["offset"])

    def test_file_read_rejects_traversal_and_non_resource_files(self) -> None:
        cases = (
            "../README.md",
            "/etc/passwd",
            "references\\details.md",
            "scripts/setup.sh",
            ".hidden.md",
        )
        for path in cases:
            with self.subTest(path=path):
                with self.assertRaises(
                    (discovery.InvalidDiscoveryRequest, discovery.UnsafeDiscoveryPath)
                ):
                    discovery.read_skill_file("cisco-product-setup", path)

    def test_pure_python_cisco_resolver_matches_current_ranking(self) -> None:
        resolved = discovery.resolve_cisco_product("Cisco ACI")
        ambiguous = discovery.resolve_cisco_product("ASA")
        missing = discovery.resolve_cisco_product("definitely-not-a-cisco-product")

        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["matches"][0]["id"], "cisco_aci")
        self.assertEqual(ambiguous["status"], "ambiguous")
        self.assertEqual(
            [item["id"] for item in ambiguous["matches"]],
            ["cisco_asa_ftd_syslog", "cisco_secure_firewall"],
        )
        self.assertEqual(
            missing, {"status": "not_found", "query": missing["query"], "matches": []}
        )


class DiscoverySecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        _write_fake_repository(self.root, ("alpha-skill", "beta-skill"))
        self.service = discovery.SkillDiscovery(self.root)

    def test_catalog_json_duplicate_keys_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            discovery.DiscoveryCatalogError,
            "duplicate JSON key",
        ):
            discovery._load_catalog_json(
                '{"schema_version":1,"schema_version":2}',
                label="test catalog",
            )

    def test_revision_changes_and_invalidates_existing_cursor(self) -> None:
        first = self.service.search_skills(limit=1)
        cursor = first["next_cursor"]
        self.assertIsNotNone(cursor)
        skill_md = self.root / "skills" / "alpha-skill" / "SKILL.md"
        skill_md.write_text(
            skill_md.read_text(encoding="utf-8").replace("safely", "very safely"),
            encoding="utf-8",
        )
        os.utime(skill_md, None)

        changed = self.service.search_skills(limit=1)
        self.assertNotEqual(changed["revision"], first["revision"])
        with self.assertRaises(discovery.InvalidCursor):
            self.service.search_skills(limit=1, cursor=cursor)

    def test_symlinks_hidden_files_and_binary_templates_are_not_exposed(self) -> None:
        outside = self.root / "outside.yaml"
        outside.write_text("secret: outside\n", encoding="utf-8")
        templates = self.root / "skills" / "alpha-skill" / "templates"
        (templates / "linked.yaml").symlink_to(outside)
        (templates / ".hidden.yaml").write_text("hidden: true\n", encoding="utf-8")
        (templates / "binary.yaml").write_bytes(b"safe-prefix\x00binary")

        listing = self.service.list_skill_files("alpha-skill", "template", limit=100)
        paths = {item["path"] for item in listing["files"]}
        self.assertNotIn("templates/linked.yaml", paths)
        self.assertNotIn("templates/.hidden.yaml", paths)
        self.assertNotIn("templates/binary.yaml", paths)
        with self.assertRaises(discovery.UnsafeDiscoveryPath):
            self.service.read_skill_file("alpha-skill", "templates/linked.yaml")

    def test_manifest_excludes_executable_helpers(self) -> None:
        manifest = self.service.get_skill_manifest("alpha-skill")
        self.assertEqual(
            [item["path"] for item in manifest["entrypoints"]],
            ["scripts/setup.sh", "scripts/validate.sh"],
        )

    def test_frontmatter_aliases_are_rejected(self) -> None:
        skill_md = self.root / "skills" / "alpha-skill" / "SKILL.md"
        skill_md.write_text(
            "---\n"
            "name: alpha-skill\n"
            "description: &description Unsafe alias source.\n"
            "duplicated: *description\n"
            "---\n\n"
            "# Instructions\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            discovery.DiscoveryCatalogError, "YAML aliases are not allowed"
        ):
            self.service.search_skills()

    def test_frontmatter_duplicate_keys_are_rejected(self) -> None:
        skill_md = self.root / "skills" / "alpha-skill" / "SKILL.md"
        skill_md.write_text(
            "---\n"
            "name: alpha-skill\n"
            "description: First description.\n"
            "description: Shadowed description.\n"
            "---\n\n"
            "# Instructions\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            discovery.DiscoveryCatalogError, "duplicate frontmatter key"
        ):
            self.service.search_skills()

    def test_utf8_chunking_rejects_partial_character_offsets(self) -> None:
        path = "templates/unicode.yaml"
        full = self.service.read_skill_file("alpha-skill", path, max_bytes=100)
        byte_offset = full["text"].encode("utf-8").index("é".encode("utf-8"))

        with self.assertRaises(discovery.DiscoveryLimitExceeded):
            self.service.read_skill_file(
                "alpha-skill", path, offset=byte_offset, max_bytes=1
            )
        with self.assertRaises(discovery.InvalidDiscoveryRequest):
            self.service.read_skill_file(
                "alpha-skill", path, offset=byte_offset + 1, max_bytes=4
            )

    def test_resource_inventory_is_cached_by_stable_file_identity(self) -> None:
        with mock.patch.object(
            self.service,
            "_validate_utf8_descriptor",
            wraps=self.service._validate_utf8_descriptor,
        ) as validate:
            first = self.service.list_skill_files("alpha-skill", "template", limit=100)
            first_calls = validate.call_count
            second = self.service.list_skill_files("alpha-skill", "template", limit=100)

        self.assertGreater(first_calls, 0)
        self.assertEqual(validate.call_count, first_calls)
        self.assertEqual(first["files"], second["files"])

    def test_resource_inventory_enforces_aggregate_byte_cap_before_reading(
        self,
    ) -> None:
        templates = self.root / "skills" / "alpha-skill" / "templates"
        file_size = 7 * 1024 * 1024
        for index in range(5):
            with (templates / f"huge-{index}.yaml").open("wb") as handle:
                handle.truncate(file_size)

        with self.assertRaises(discovery.DiscoveryLimitExceeded):
            self.service.list_skill_files("alpha-skill", "template", limit=100)

    def test_resource_revision_changes_when_template_identity_changes(self) -> None:
        before = self.service.list_skill_files("alpha-skill", "template", limit=100)
        template = self.root / "skills" / "alpha-skill" / "templates" / "unicode.yaml"
        template.write_text("name: àx\n", encoding="utf-8")

        after = self.service.list_skill_files("alpha-skill", "template", limit=100)
        page = self.service.read_skill_file("alpha-skill", "templates/unicode.yaml")

        self.assertNotEqual(before["revision"], after["revision"])
        self.assertEqual(page["revision"], after["revision"])


if __name__ == "__main__":
    unittest.main()
