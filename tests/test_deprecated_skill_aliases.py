"""Fail-closed behavioral tests for all manifest-declared compatibility aliases."""

from __future__ import annotations

import json
import re
import stat
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

from skills.shared.skill_catalog import load_catalog


REPO_ROOT = Path(__file__).resolve().parents[1]
ALIASES = tuple(load_catalog().aliases.items())
ENTRYPOINTS = {
    "setup.sh": lambda path: ["bash", str(path), "--phase", "apply"],
    "validate.sh": lambda path: ["bash", str(path), "--live"],
    "render_assets.py": lambda path: [
        sys.executable,
        str(path),
        "--output-dir",
        "must-not-render",
    ],
}


@pytest.mark.parametrize(("legacy", "canonical"), ALIASES)
@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
def test_every_legacy_executable_rejects_operational_invocation_before_io(
    tmp_path: Path,
    legacy: str,
    canonical: str,
    entrypoint: str,
) -> None:
    script = REPO_ROOT / "skills" / legacy / "scripts" / entrypoint
    result = subprocess.run(
        ENTRYPOINTS[entrypoint](script),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr

    assert result.returncode == 2
    assert f"replaced_by '{canonical}'" in output
    assert canonical in output
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(("legacy", "canonical"), ALIASES)
@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
def test_every_legacy_executable_allows_only_visible_help_handoff(
    tmp_path: Path,
    legacy: str,
    canonical: str,
    entrypoint: str,
) -> None:
    script = REPO_ROOT / "skills" / legacy / "scripts" / entrypoint
    command = (
        [sys.executable, str(script), "--help"]
        if entrypoint.endswith(".py")
        else ["bash", str(script), "--help"]
    )
    result = subprocess.run(
        command,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0
    assert f"replaced_by {canonical}" in output
    assert "help-only" in output
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(("legacy", "canonical"), ALIASES)
def test_alias_directory_has_no_independent_docs_templates_or_extra_scripts(
    legacy: str,
    canonical: str,
) -> None:
    skill_dir = REPO_ROOT / "skills" / legacy
    assert not (skill_dir / "reference.md").exists()
    assert not (skill_dir / "template.example").exists()
    assert {path.name for path in (skill_dir / "scripts").iterdir()} == set(
        ENTRYPOINTS
    )
    instructions = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "help-only" in instructions
    assert canonical in instructions
    assert "preserve supported legacy" not in instructions.lower()


STRUCTURED_REGISTRIES = {
    "skills/shared/app_registry.json",
    "skills/shared/skill_product_registry.json",
    "skills/shared/skill_validation_registry.json",
}
GENERATED_ROW_DOCS = {
    "SKILL_REQUIREMENTS.md",
    "SKILL_UX_CATALOG.md",
    "SKILL_VALIDATION_MATRIX.md",
    "SPLUNK_10_5_COMPATIBILITY.md",
    "DEPLOYMENT_ROLE_MATRIX.md",
    "skills/shared/deprecated_skill_aliases.md",
}
# Security-scanner fingerprint registries may contain historical path text,
# but are not operational handoff surfaces.
NON_OPERATIONAL_METADATA = {".gitleaksignore"}
CATALOG_BEGIN = "<!-- BEGIN GENERATED SKILL CATALOG -->"
CATALOG_END = "<!-- END GENERATED SKILL CATALOG -->"


def _alias_pattern(legacy: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9-]){re.escape(legacy)}(?![a-z0-9-])")


def _repo_candidate_paths() -> list[str]:
    """Return all tracked and nonignored untracked repository paths."""

    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    paths: list[str] = []
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        try:
            paths.append(raw_path.decode("utf-8"))
        except UnicodeDecodeError:
            continue
    return sorted(set(paths))


def _has_symlink_component(path: Path) -> bool:
    relative = path.relative_to(REPO_ROOT)
    current = REPO_ROOT
    for component in relative.parts:
        current /= component
        if current.is_symlink():
            return True
    return False


def _decode_text_candidate(path: Path) -> str | None:
    """Decode any regular nonsymlink UTF-8 file; skip binary candidates only."""

    if _has_symlink_component(path):
        return None
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(mode):
        return None
    raw = path.read_bytes()
    if b"\0" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _blank_generated_catalog_region(
    relative: str,
    text: str,
    findings: list[str],
) -> str:
    """Blank exactly one generator-owned catalog region, preserving line numbers."""

    if text.count(CATALOG_BEGIN) != 1 or text.count(CATALOG_END) != 1:
        findings.append(
            f"{relative}:generated-catalog-region: expected exactly one marker pair"
        )
        return text
    start = text.index(CATALOG_BEGIN)
    end = text.index(CATALOG_END, start) + len(CATALOG_END)
    region = text[start:end]
    return text[:start] + ("\n" * region.count("\n")) + text[end:]


@lru_cache(maxsize=None)
def _expected_alias_rows(relative: str) -> dict[str, str]:
    """Render the exact lifecycle row permitted for each manifest alias."""

    catalog = load_catalog()
    if relative == "SKILL_REQUIREMENTS.md":
        return {
            legacy: (
                f"| `{legacy}` (**Deprecated** -> `{canonical}`) | Help-only "
                "compatibility alias. | No independent operational requirements; read "
                "the canonical replacement and use its current safety gates. |"
            )
            for legacy, canonical in catalog.aliases.items()
        }

    if relative == "SKILL_UX_CATALOG.md":
        from skills.shared.scripts.generate_skill_ux_catalog import render_catalog

        rendered = render_catalog()
    elif relative == "SKILL_VALIDATION_MATRIX.md":
        from skills.shared.scripts.generate_skill_validation_matrix import render

        rendered = render()
    elif relative == "SPLUNK_10_5_COMPATIBILITY.md":
        from skills.shared.scripts.generate_splunk_10_5_compatibility import render

        rendered = render()
    elif relative == "DEPLOYMENT_ROLE_MATRIX.md":
        from skills.shared.scripts.generate_deployment_docs import (
            load_registry,
            render_role_matrix,
        )

        rendered = render_role_matrix(load_registry(), catalog)
    elif relative == "skills/shared/deprecated_skill_aliases.md":
        from skills.shared.scripts.generate_skill_catalog import (
            render_alias_migration_doc,
        )

        rendered = render_alias_migration_doc(catalog)
    else:  # pragma: no cover - guarded by GENERATED_ROW_DOCS
        raise AssertionError(f"unsupported generated row document: {relative}")

    rows: dict[str, str] = {}
    for legacy in catalog.aliases:
        matches = [
            line for line in rendered.splitlines() if _alias_pattern(legacy).search(line)
        ]
        if len(matches) != 1:
            raise AssertionError(
                f"{relative} must render exactly one lifecycle row for {legacy}; "
                f"found {len(matches)}"
            )
        rows[legacy] = matches[0]
    return rows


def _blank_expected_alias_rows(relative: str, text: str) -> str:
    expected = set(_expected_alias_rows(relative).values())
    output: list[str] = []
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        ending = raw_line[len(line) :]
        output.append(ending if line in expected else raw_line)
    return "".join(output)


def _structured_registry_offenders(
    relative: str,
    text: str,
) -> list[str]:
    """Reject alias strings outside the exact generated registry identity nodes."""

    catalog = load_catalog()
    payload = json.loads(text)
    findings: list[str] = []

    def walk(value: object, path: tuple[object, ...] = ()):
        if isinstance(value, dict):
            for key, child in value.items():
                for legacy in catalog.aliases:
                    if _alias_pattern(legacy).search(str(key)):
                        yield path + ("<key>", key), legacy
                yield from walk(child, path + (key,))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from walk(child, path + (index,))
        elif isinstance(value, str):
            for legacy in catalog.aliases:
                if _alias_pattern(legacy).search(value):
                    yield path, legacy

    for path, legacy in walk(payload):
        canonical = catalog.aliases[legacy]
        allowed = False
        if relative == "skills/shared/app_registry.json":
            allowed = (
                len(path) == 3
                and path[0] == "skill_topologies"
                and isinstance(path[1], int)
                and path[2] == "skill"
            )
            if allowed:
                topology = payload["skill_topologies"][path[1]]
                no_roles = {
                    role: "none" for role in payload["deployment_roles"]
                }
                allowed = (
                    topology.get("skill") == legacy
                    and topology.get("role_support") == no_roles
                    and topology.get("cloud_pairing") == []
                    and topology.get("notes")
                    == (
                        f"Deprecated help-only compatibility alias for {canonical}; "
                        "retained here only to classify historical placement, not as "
                        "an operational peer."
                    )
                )
        elif relative == "skills/shared/skill_product_registry.json":
            if (
                len(path) == 3
                and path[0] == "skill_records"
                and isinstance(path[1], int)
                and path[2] == "name"
            ):
                record = payload["skill_records"][path[1]]
                allowed = record == {
                    "name": legacy,
                    "status": "deprecated",
                    "replaced_by": canonical,
                }
            else:
                allowed = (
                    len(path) == 6
                    and path[0] == "products"
                    and isinstance(path[1], int)
                    and path[2] == "capabilities"
                    and isinstance(path[3], int)
                    and path[4] == "skills"
                    and isinstance(path[5], int)
                )
                if allowed:
                    product = payload["products"][path[1]]
                    capability = product["capabilities"][path[3]]
                    record = catalog.by_name[legacy]
                    allowed = (
                        product.get("id") == record.product
                        and capability.get("id") == record.capability
                        and capability["skills"][path[5]] == legacy
                    )
        elif relative == "skills/shared/skill_validation_registry.json":
            allowed = (
                len(path) == 2
                and path[0] == "skills"
                and isinstance(path[1], int)
            )
        if not allowed:
            rendered_path = ".".join(str(component) for component in path)
            findings.append(f"{relative}:{rendered_path}: {legacy}")
    return findings


def deprecated_name_offenders(
    *,
    overrides: dict[str, str | bytes] | None = None,
) -> list[str]:
    """Return every exact deprecated name outside an approved lifecycle context."""

    catalog = load_catalog()
    override_content = overrides or {}
    relatives = set(_repo_candidate_paths()) | set(override_content)
    offenders: list[str] = []

    for relative in sorted(relatives):
        path = REPO_ROOT / relative
        if relative.startswith("tests/"):
            continue
        if relative in NON_OPERATIONAL_METADATA:
            continue
        if any(relative.startswith(f"skills/{legacy}/") for legacy in catalog.aliases):
            continue
        if any(
            relative == f".claude/commands/{legacy}.md" for legacy in catalog.aliases
        ):
            continue
        if relative == "skills/catalog.yaml":
            continue

        content = override_content.get(relative)
        if content is None:
            text = _decode_text_candidate(path)
            if text is None:
                continue
        else:
            raw = content.encode("utf-8") if isinstance(content, str) else content
            if b"\0" in raw:
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue

        if relative in STRUCTURED_REGISTRIES:
            offenders.extend(_structured_registry_offenders(relative, text))
            continue
        if relative in {"AGENTS.md", "CLAUDE.md"}:
            text = _blank_generated_catalog_region(relative, text, offenders)
        elif relative in GENERATED_ROW_DOCS:
            text = _blank_expected_alias_rows(relative, text)

        for line_number, line in enumerate(text.splitlines(), start=1):
            for legacy in catalog.aliases:
                if not _alias_pattern(legacy).search(line):
                    continue
                offenders.append(f"{relative}:{line_number}: {legacy}")
    return offenders


def test_repo_operational_docs_and_code_never_handoff_to_deprecated_names() -> None:
    assert deprecated_name_offenders() == []


@pytest.mark.parametrize("relative", ["AGENTS.md", "CLAUDE.md"])
def test_guard_rejects_deprecated_command_in_manual_context_section(
    relative: str,
) -> None:
    legacy = next(iter(load_catalog().aliases))
    content = (REPO_ROOT / relative).read_text(encoding="utf-8")
    content += (
        "\n## Manual operational notes\n\n"
        f"bash skills/{legacy}/scripts/setup.sh --phase apply\n"
    )

    offenders = deprecated_name_offenders(overrides={relative: content})

    assert any(item.startswith(f"{relative}:") and legacy in item for item in offenders)


def test_guard_rejects_deprecated_handoff_in_unrelated_app_registry_field() -> None:
    relative = "skills/shared/app_registry.json"
    legacy = next(iter(load_catalog().aliases))
    payload = json.loads((REPO_ROOT / relative).read_text(encoding="utf-8"))
    payload["rogue_operational_handoff"] = (
        f"bash skills/{legacy}/scripts/setup.sh --phase apply"
    )
    content = json.dumps(payload, indent=2) + "\n"

    offenders = deprecated_name_offenders(overrides={relative: content})

    assert any(
        item.startswith(f"{relative}:") and legacy in item for item in offenders
    )


def test_guard_inventory_includes_cached_and_nonignored_untracked_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=b"tracked.py\0untracked-runbook\0",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert _repo_candidate_paths() == ["tracked.py", "untracked-runbook"]
    assert calls == [
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    ]


@pytest.mark.parametrize(
    "relative",
    [
        "rogue.txt",
        "rogue.bats",
        "rogue.js",
        "rogue.ts",
        "rogue.xml",
        "rogue.conf",
        "extensionless-runbook",
    ],
)
def test_guard_scans_utf8_text_without_an_extension_allowlist(relative: str) -> None:
    legacy = next(iter(load_catalog().aliases))
    content = f"bash skills/{legacy}/scripts/setup.sh --phase apply\n"

    assert deprecated_name_offenders(overrides={relative: content}) == [
        f"{relative}:1: {legacy}"
    ]


def test_guard_skips_only_binary_or_non_utf8_override_content() -> None:
    legacy = next(iter(load_catalog().aliases))
    prefix = f"skills/{legacy}/scripts/setup.sh".encode()

    assert deprecated_name_offenders(
        overrides={
            "nul.bin": prefix + b"\0payload",
            "non-utf8": prefix + b"\xff",
        }
    ) == []
