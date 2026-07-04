#!/usr/bin/env python3
"""Regression tests for incompatible legacy/current render-bundle ownership."""

from __future__ import annotations

import ast
import json
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from tests.regression_helpers import REPO_ROOT
from skills.shared.render_bundle_ownership import bundle_contract

MARKER = ".splunk-skill-bundle.json"


@dataclass(frozen=True)
class Renderer:
    skill: str
    child: str
    args: tuple[str, ...]

    @property
    def script(self) -> Path:
        return REPO_ROOT / "skills" / self.skill / "scripts" / "render_assets.py"


PAIRS = (
    (
        Renderer("splunk-cim-data-model", "cim", ()),
        Renderer("splunk-cim-data-model-setup", "cim", ("--datamodel", "Authentication")),
    ),
    (
        Renderer(
            "splunk-dashboard-studio",
            "dashboard-studio",
            ("--title", "Ownership test", "--panel", "Count::single::index=_internal | stats count"),
        ),
        Renderer(
            "splunk-dashboard-studio-setup",
            "dashboard-studio",
            ("--dashboard-name", "ownership_test", "--search", "index=_internal | stats count"),
        ),
    ),
    (
        Renderer(
            "splunk-ddaa-archive",
            "ddaa",
            (
                "--stack",
                "test",
                "--index",
                "main",
                "--searchable-days",
                "30",
                "--archival-retention-days",
                "90",
            ),
        ),
        Renderer(
            "splunk-ddaa-archive-setup",
            "ddaa",
            ("--index", "main", "--searchable-days", "30", "--archival-retention-days", "90"),
        ),
    ),
    (
        Renderer("splunk-ingest-actions", "ingest-actions", ()),
        Renderer(
            "splunk-ingest-actions-setup",
            "ingest-actions",
            (
                "--ruleset-sourcetype",
                "test",
                "--ruleset-name",
                "drop_debug",
                "--rule-type",
                "drop",
                "--drop-regex",
                "debug",
            ),
        ),
    ),
    (
        Renderer("splunk-knowledge-objects", "knowledge-objects", ()),
        Renderer(
            "splunk-knowledge-objects-setup",
            "knowledge-objects",
            ("--object-kind", "macro", "--name", "ownership_test", "--definition", "index=main"),
        ),
    ),
    (
        Renderer("splunk-kvstore-admin", "kvstore", ()),
        Renderer("splunk-kvstore-admin-setup", "kvstore", ()),
    ),
    (
        Renderer("splunk-secure-gateway", "secure-gateway", ()),
        Renderer("splunk-secure-gateway-setup", "secure-gateway", ()),
    ),
)


class RenderBundleOwnershipTests(unittest.TestCase):
    def run_renderer(self, renderer: Renderer, output_dir: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(renderer.script), "--output-dir", str(output_dir), *renderer.args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def test_each_owner_can_rerender_but_incompatible_peer_is_rejected(self) -> None:
        for pair in PAIRS:
            for first, second in (pair, tuple(reversed(pair))):
                with self.subTest(first=first.skill, second=second.skill), tempfile.TemporaryDirectory() as tmp:
                    output_dir = Path(tmp)
                    initial = self.run_renderer(first, output_dir)
                    self.assertEqual(initial.returncode, 0, msg=initial.stdout + initial.stderr)

                    marker = output_dir / first.child / MARKER
                    payload = json.loads(marker.read_text(encoding="utf-8"))
                    self.assertEqual(payload["schema"], 1)
                    self.assertEqual(payload["owner"], first.skill)
                    self.assertEqual(payload["incompatible_peer"], second.skill)

                    rerender = self.run_renderer(first, output_dir)
                    self.assertEqual(rerender.returncode, 0, msg=rerender.stdout + rerender.stderr)

                    rejected = self.run_renderer(second, output_dir)
                    output = rejected.stdout + rejected.stderr
                    self.assertNotEqual(rejected.returncode, 0, msg=output)
                    self.assertIn(f"owned by '{first.skill}'", output)
                    self.assertIn("different --output-dir", output)

    def test_registered_file_contracts_match_every_renderer(self) -> None:
        for first, second in PAIRS:
            for renderer, peer in ((first, second), (second, first)):
                with self.subTest(skill=renderer.skill):
                    tree = ast.parse(renderer.script.read_text(encoding="utf-8"))
                    generated_node = next(
                        node.value
                        for node in tree.body
                        if isinstance(node, ast.Assign)
                        and any(
                            isinstance(target, ast.Name) and target.id == "GENERATED_FILES"
                            for target in node.targets
                        )
                    )
                    generated_files = frozenset(ast.literal_eval(generated_node))
                    registered_peer, registered_files = bundle_contract(renderer.skill)
                    self.assertEqual(registered_peer, peer.skill)
                    self.assertEqual(registered_files, generated_files)

    def test_unmarked_legacy_mixed_bundle_is_rejected_without_deleting_files(self) -> None:
        first, second = PAIRS[0]
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            render_dir = output_dir / first.child
            render_dir.mkdir()
            own_file = render_dir / "apply.sh"
            peer_file = render_dir / "validate-tstats.sh"
            own_file.write_text("own\n", encoding="utf-8")
            peer_file.write_text("peer\n", encoding="utf-8")

            rejected = self.run_renderer(first, output_dir)
            output = rejected.stdout + rejected.stderr
            self.assertNotEqual(rejected.returncode, 0, msg=output)
            self.assertIn("unowned render bundle", output)
            self.assertIn(second.skill, output)
            self.assertEqual(own_file.read_text(encoding="utf-8"), "own\n")
            self.assertEqual(peer_file.read_text(encoding="utf-8"), "peer\n")
            self.assertFalse((render_dir / MARKER).exists())

    def test_unmarked_bundle_from_same_owner_is_adopted_for_compatibility(self) -> None:
        owner, _ = PAIRS[0]
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            render_dir = output_dir / owner.child
            render_dir.mkdir()
            (render_dir / "apply.sh").write_text("old generated content\n", encoding="utf-8")

            adopted = self.run_renderer(owner, output_dir)
            self.assertEqual(adopted.returncode, 0, msg=adopted.stdout + adopted.stderr)
            payload = json.loads((render_dir / MARKER).read_text(encoding="utf-8"))
            self.assertEqual(payload["owner"], owner.skill)

    def test_valid_owner_marker_does_not_hide_stale_peer_artifacts(self) -> None:
        owner, peer = PAIRS[0]
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            initial = self.run_renderer(owner, output_dir)
            self.assertEqual(initial.returncode, 0, msg=initial.stdout + initial.stderr)

            render_dir = output_dir / owner.child
            peer_file = render_dir / "validate-tstats.sh"
            peer_file.write_text("stale peer artifact\n", encoding="utf-8")

            rejected = self.run_renderer(owner, output_dir)
            output = rejected.stdout + rejected.stderr
            self.assertNotEqual(rejected.returncode, 0, msg=output)
            self.assertIn(f"unique to '{peer.skill}'", output)
            self.assertEqual(peer_file.read_text(encoding="utf-8"), "stale peer artifact\n")

    def test_dry_run_does_not_claim_an_empty_bundle(self) -> None:
        owner, _ = PAIRS[0]
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "rendered"
            result = self.run_renderer(
                Renderer(owner.skill, owner.child, (*owner.args, "--dry-run")), output_dir
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertFalse(output_dir.exists())


if __name__ == "__main__":
    unittest.main()
