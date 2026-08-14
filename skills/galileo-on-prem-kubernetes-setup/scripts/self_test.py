#!/usr/bin/env python3
"""Offline security regressions for the Galileo On-Prem parent router."""

from __future__ import annotations

import copy
import os
import tempfile
from pathlib import Path

import render_router as router


def expect_contract_error(callback: object, message: str) -> None:
    try:
        callback()  # type: ignore[operator]
    except router.ContractError:
        return
    raise AssertionError(message)


def main() -> int:
    _, features, *_ = router.load_matrix()
    fixture_dir = router.SKILL_DIR / "evals" / "files"
    good = router.runtime_coverage(
        str(fixture_dir / "runtime-inventory-all-empty-fixture.json"),
        Path("/"), "a" * 64, features,
    )
    if good[1:] != ([], [], [], []):
        raise AssertionError(f"complete runtime fixture did not pass: {good[1:]}")
    bad = router.runtime_coverage(
        str(fixture_dir / "runtime-inventory-unclassified-fixture.json"),
        Path("/"), "a" * 64, features,
    )
    if "does.not.exist" not in bad[1]:
        raise AssertionError("unknown classification did not enter uncovered")
    if "runtime.item.unclassified:image.unknown-component" not in bad[4]:
        raise AssertionError("unknown runtime image did not enter unclassified inventory")

    with tempfile.TemporaryDirectory(prefix="galileo-router-self-test-") as temporary:
        root = Path(os.path.realpath(temporary))
        spec = router.load_data(router.SKILL_DIR / "template.example")
        complete_spec = copy.deepcopy(spec)
        complete_spec["artifacts"]["galileo_stack_sha256"] = "a" * 64
        complete_spec["artifacts"]["stack_runtime_inventory"] = str(
            fixture_dir / "runtime-inventory-all-empty-fixture.json"
        )
        complete_spec_path = root / "complete-spec.json"
        complete_spec_path.write_bytes(router.pretty_bytes(complete_spec))
        complete_spec_path.chmod(0o600)
        _, complete_result, complete_rc = router.render(
            complete_spec_path, root / "complete-output", "", "", "coverage", True
        )
        if complete_rc != 0 or not complete_result["coverage_complete"]:
            raise AssertionError("complete runtime inventory did not pass the CLI coverage contract")

        spec_path = root / "spec.json"
        spec_path.write_bytes(router.pretty_bytes(spec))
        spec_path.chmod(0o600)
        bundle, _, _ = router.render(
            spec_path, root / "output", "", "", "render", True
        )
        router.validate_bundle(bundle)

        # Simulate an attacker changing all four arrays to empty and updating
        # the ordinary file manifest. Bundle validation must recompute semantic
        # coverage from the current matrix and normalized runtime, not trust it.
        coverage_path = bundle / "coverage-report.json"
        coverage = router.load_data(coverage_path)
        for key in (
            "uncovered", "unowned", "duplicate_mutation_owners",
            "unclassified_runtime_inventory",
        ):
            coverage[key] = []
        coverage["coverage_complete"] = True
        coverage["runtime_inventory_supplied"] = True
        forged = router.pretty_bytes(coverage)
        coverage_path.write_bytes(forged)
        coverage_path.chmod(0o600)
        manifest_path = bundle / "bundle-manifest.json"
        manifest = router.load_data(manifest_path)
        row = next(item for item in manifest["files"] if item["path"] == "coverage-report.json")
        row["sha256"] = router.sha256_bytes(forged)
        row["size"] = len(forged)
        manifest_path.write_bytes(router.pretty_bytes(manifest))
        manifest_path.chmod(0o600)
        expect_contract_error(
            lambda: router.validate_bundle(bundle),
            "forged semantic coverage passed after manifest recomputation",
        )

    print("Galileo On-Prem parent self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
