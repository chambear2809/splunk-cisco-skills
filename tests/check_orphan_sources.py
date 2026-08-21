#!/usr/bin/env python3
"""Verify every source URL a skill defines is actually consumed.

Skills bind a claim to its documentation by defining a module-level map of
source URLs and subscripting that map where the claim is rendered. When a claim
is later repointed at a different source, the key it used to cite is left
behind: still defined, read by nothing, and invisible to every other check in
this repository. The URL normally stays alive, so link checking passes. Nothing
renders it, so no reviewer sees it in output. It then rots silently until
someone eventually wires it up to a page that has long since moved on.

An orphan is also a symptom worth chasing rather than deleting. Every orphan
found when this check was written turned out to be a mis-binding, not dead
code: `SOURCE_DOCS["workload_cloud"]` in splunk-admin-doctor was unused because
the Workload management rule cited the generic Cloud Monitoring Console doc
instead, and `SOURCE_URLS["app_builder"]` in cisco-cloud-control-setup was
unused because the App Builder coverage row cited the generic Cloud Control
Studio product page. In both cases the curated doc existed, a claim needed it,
and the wire was never connected. Prefer binding an orphan to the claim it was
curated for; remove it only after confirming no such claim exists.

Scope is deliberately Python-only. Every JSON registry in this repository --
source_packs.json, source-ledger.json, deployment-feature-matrix.json,
app_registry.json, splunkbase_registry_evidence.json -- is loaded and iterated
wholesale, so every key in them is consumed by construction. Scanning them
would produce noise and no signal.
"""

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"

URL_RE = re.compile(r"https?://")

# A map needs enough entries, and enough of them pointing at URLs, to be a
# source registry rather than an incidental constant that happens to hold a
# link. These thresholds are loose on purpose: the two scoping rules below do
# the real work of suppressing false positives.
MIN_ENTRIES = 3
MIN_URL_VALUE_RATIO = 0.6

# Opt out for a key added in the same commit as the code that will consume it.
# Write it on the key's own line:
#     "new_thing": "https://...",  # orphan-source: allow
ALLOW_MARKER = "# orphan-source: allow"

# Orphans that are known, triaged, and owned by other work in flight. Each
# entry is a specific (path, key) pair rather than a skill or file exclusion,
# so a *new* orphan in one of these same files still fails the check. That
# distinction matters: excluding the files wholesale would permanently hide
# this defect class in exactly the two files that had the most of it.
#
# Removing a finding from this list is part of fixing it. A stale entry -- one
# whose key is no longer an orphan -- is itself reported as an error below, so
# this list cannot silently outlive the work it defers.
DEFERRED_ORPHANS: dict[tuple[str, str], str] = {
    # Finding 3 (14 of 46 keys in SOURCE_DOCS, splunk-data-source-readiness-
    # doctor) is resolved and deliberately not listed here. Every one of those
    # keys turned out to be a mis-binding of the same shape: the rules in that
    # catalog are compound, firing on several unrelated trigger paths, and the
    # single `source_doc` field could only cite the page for the rule's
    # headline concern. The fix was a `supporting_docs` field on each rule plus
    # a `validate_catalog()` assertion that every curated doc is cited.
    #
    # Finding 4 (5 of 42 keys in DOC_SOURCES, splunk-observability-deep-native-
    # workflows) is resolved and deliberately not listed here. All five were
    # mis-bindings, matching finding 3: the claim existed, the curated doc
    # existed, and the wire was never connected. Each claim is compound and its
    # single `source` field could only cite one page, so the modern-dashboard
    # coverage row cited the dashboards API while also delegating chart apply,
    # the DXA row cited the events page while also claiming conversion funnels,
    # and the synthetics row cited the generic Synthetics API while planning
    # artifact retrieval. The fix was a `supporting_sources` field on
    # add_coverage/add_handoff, rendered into workflow-handoff.md, so a compound
    # claim can cite every doc it rests on. None were dead code.
}


def is_source_map(node: ast.expr) -> bool:
    """Report whether a dict literal looks like a registry of source URLs."""
    if not isinstance(node, ast.Dict) or len(node.keys) < MIN_ENTRIES:
        return False
    if not all(
        isinstance(key, ast.Constant) and isinstance(key.value, str)
        for key in node.keys
    ):
        return False

    url_values = 0
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            text = value.value
        elif isinstance(value, ast.Dict):
            # Records of the form {"url": ..., "claim": ..., "retrieved": ...}.
            text = " ".join(
                item.value
                for item in value.values
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
        else:
            continue
        if URL_RE.search(text):
            url_values += 1
    return url_values >= max(2, int(MIN_URL_VALUE_RATIO * len(node.values)))


def source_maps(tree: ast.Module) -> dict[str, ast.Dict]:
    """Collect module-level ALL_CAPS source maps.

    SCOPING RULE 1 -- module-level ALL_CAPS names only.
    A source registry in this repository is always a module-level constant.
    Function-local dicts that merely contain URLs are a different thing
    entirely, and their keys are routinely consumed by serializing the whole
    dict rather than by subscript. The concrete case this excludes is the
    `payloads` local in
    skills/splunk-observability-cloud-integration-setup/scripts/render_assets.py,
    which collects API payload shapes and is written straight to
    payloads/api-payload-shapes.json. Every one of its keys is consumed, but a
    subscript-based reader sees none of them. Do not relax this to "any dict
    with URL values" -- that reintroduces exactly that false positive.
    """
    maps: dict[str, ast.Dict] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target]
            value = node.value
        else:
            continue
        if value is None:
            continue
        for target in targets:
            if target.id.isupper() and is_source_map(value):
                maps[target.id] = value
    return maps


def is_wholesale_consumed(tree: ast.Module, map_name: str) -> bool:
    """Report whether the whole map is consumed without naming its keys.

    SCOPING RULE 2 -- any bare `Name` load counts as wholesale consumption.
    A map that is read as a value, rather than subscripted, may have every key
    consumed by a path this checker cannot follow. Three real patterns depend
    on this:

      * `for key, value in sorted(SOURCE_RECORDS.items())` in
        cisco-data-fabric-setup renders every record into a source ledger.
      * `{"source_urls": SOURCE_URLS}` in
        splunk-observability-ai-agent-monitoring-setup dumps the whole map into
        coverage-report.json.
      * `SOURCE_URLS[surface["source"]]` in cisco-cloud-control-setup looks a
        key up dynamically. This one does *not* trip the rule, and must not --
        the subscripted `Name` is exempted below, and the key resolves anyway
        because the literal lives in the driving data structure and so is found
        by the ordinary literal scan.

    Treating a bare load as total consumption is deliberately conservative: it
    trades the ability to find orphans in a handful of maps for never reporting
    a key that some untraceable path does in fact read. A check that cries wolf
    is worse than no check.
    """
    subscripted: set[int] = set()
    for node in ast.walk(tree):
        # `MAP["key"]` and `MAP.get("key")` name their key explicitly, so the
        # `Name` load underneath them is not evidence of wholesale use.
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            if node.value.id == map_name:
                subscripted.add(id(node.value))
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == map_name and node.attr == "get":
                subscripted.add(id(node.value))

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Name)
            and node.id == map_name
            and isinstance(node.ctx, ast.Load)
            and id(node) not in subscripted
        ):
            return True
    return False


def consumed_literals(tree: ast.Module, definition: ast.Dict) -> set[str]:
    """Every string literal in the file except this map's own key positions.

    Matching on literal presence rather than on subscript syntax is what makes
    indirect consumption resolve: a key named in a driving table and reached via
    `MAP[row["source"]]` still appears as a literal somewhere in the file.
    """
    key_nodes = {id(key) for key in definition.keys}
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in key_nodes
    }


def check_file(path: Path) -> tuple[list[str], set[tuple[str, str]]]:
    """Return (errors, orphan keys seen) for one Python file."""
    rel = str(path.relative_to(REPO_ROOT))
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, UnicodeDecodeError, SyntaxError):
        return [], set()

    lines = source.splitlines()
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()

    for map_name, definition in source_maps(tree).items():
        if is_wholesale_consumed(tree, map_name):
            continue
        literals = consumed_literals(tree, definition)
        for key in definition.keys:
            assert isinstance(key, ast.Constant)
            name = key.value
            if name in literals:
                continue
            line = lines[key.lineno - 1] if key.lineno <= len(lines) else ""
            if ALLOW_MARKER in line:
                continue
            seen.add((rel, name))
            if (rel, name) in DEFERRED_ORPHANS:
                continue
            errors.append(
                f"{rel}:{key.lineno}: {map_name}[{name!r}] is defined but never "
                f"consumed; bind it to the claim it was curated for, or remove it"
            )
    return errors, seen


def main() -> int:
    paths = sorted(
        path
        for path in SKILLS_DIR.rglob("*.py")
        if "__pycache__" not in path.parts
    )
    if not paths:
        print("ERROR: no Python files found under skills/", file=sys.stderr)
        return 1

    errors: list[str] = []
    all_orphans: set[tuple[str, str]] = set()
    for path in paths:
        file_errors, seen = check_file(path)
        errors.extend(file_errors)
        all_orphans |= seen

    # A deferred entry that is no longer an orphan has been fixed, and leaving
    # it listed would let the next orphan with that name pass unnoticed.
    stale = sorted(set(DEFERRED_ORPHANS) - all_orphans)
    for rel, name in stale:
        errors.append(
            f"{rel}: {name!r} is listed in DEFERRED_ORPHANS but is no longer an "
            f"orphan; remove the entry from tests/check_orphan_sources.py"
        )

    if errors:
        print("Orphaned source references:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    deferred = len(DEFERRED_ORPHANS)
    print(
        f"All source-map keys across {len(paths)} skill modules are consumed "
        f"({deferred} triaged orphans deferred)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
