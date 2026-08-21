#!/usr/bin/env python3
"""Verify every shared-library helper a skill script calls is actually sourced.

Skill scripts pull helpers in by sourcing modules under ``skills/shared/lib``.
Because ``credential_helpers.sh`` is a shim that re-sources nine sibling
modules, a script can call a helper it never sourced directly and still work --
until someone sources a narrower module instead. This check resolves the source
graph transitively and fails when a script calls a shared helper that is not
reachable from the modules it sources.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SHARED_LIB_DIR = REPO_ROOT / "skills" / "shared" / "lib"
SKILLS_DIR = REPO_ROOT / "skills"

FUNCTION_DEF_RE = re.compile(
    r"^[ \t]*(?:function[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*\([ \t]*\)[ \t]*\{",
    re.MULTILINE,
)
FUNCTION_KEYWORD_DEF_RE = re.compile(
    r"^[ \t]*function[ \t]+([A-Za-z_][A-Za-z0-9_]*)[ \t]*\{",
    re.MULTILINE,
)

# Only match real `source path.sh` / `. path.sh` statements. Embedded Python in
# heredocs contains tokens such as `source_fd = os.open(...)` and
# `source_dir="..."`, so require a separating space and a .sh suffix.
SOURCE_RE = re.compile(
    r"""(?:^|[;&|(){}]|\bthen\b|\belse\b|\bdo\b)[ \t]*"""
    r"""(?:source|\.)[ \t]+"""
    r"""(?P<path>[^\s;&|)]+\.sh)""",
    re.MULTILINE,
)

HEREDOC_START_RE = re.compile(
    r"<<-?[ \t]*(?P<quote>['\"]?)(?P<tag>[A-Za-z_][A-Za-z0-9_]*)(?P=quote)"
)

# Operators and openers that end one command and begin another. Splitting on
# these turns each line into segments whose leading word sits in command
# position, which is where a helper invocation must appear.
COMMAND_SPLIT_RE = re.compile(r"&&|\|\||\$\(|[;|(){}`!]")

# Compound-command keywords may sit in front of the real command word.
COMMAND_PREFIX_KEYWORDS = frozenset(
    {
        "if",
        "then",
        "else",
        "elif",
        "do",
        "while",
        "until",
        "time",
        "exec",
        "command",
        "builtin",
    }
)

LEADING_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*[ \t]+")
LEADING_WORD_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?![A-Za-z0-9_=])")


def leading_command_word(segment: str) -> str | None:
    """Return the command word a segment invokes, if any.

    Strips environment-assignment prefixes and compound-command keywords so
    that ``if foo``, ``FOO=1 bar`` and ``exec baz`` all resolve to the command
    actually being run. The ``=`` exclusion in ``LEADING_WORD_RE`` keeps plain
    assignments such as ``foo=bar`` from registering as a call to ``foo``.
    """
    text = segment.strip()
    while text:
        assignment = LEADING_ASSIGNMENT_RE.match(text)
        if assignment is not None:
            text = text[assignment.end() :]
            continue
        match = LEADING_WORD_RE.match(text)
        if match is None:
            return None
        word = match.group(1)
        if word in COMMAND_PREFIX_KEYWORDS:
            text = text[match.end() :].lstrip()
            continue
        return word
    return None


def command_words(text: str) -> dict[str, int]:
    """Map every command word in ``text`` to the line of its first use."""
    first_use: dict[str, int] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        for segment in COMMAND_SPLIT_RE.split(line):
            word = leading_command_word(segment)
            if word is not None and word not in first_use:
                first_use[word] = lineno
    return first_use


def strip_comments_and_heredocs(text: str) -> str:
    """Blank out full-line comments and heredoc bodies.

    Skill scripts render shell and Python into heredocs. Those bodies are data,
    not calls made by the enclosing script, so leaving them in would attribute
    a rendered artifact's helper usage to the renderer.
    """
    lines = text.splitlines()
    out: list[str] = []
    pending_tags: list[str] = []
    active_tag: str | None = None

    for raw in lines:
        if active_tag is not None:
            if raw.strip() == active_tag:
                active_tag = pending_tags.pop(0) if pending_tags else None
            out.append("")
            continue

        stripped = raw.lstrip()
        if stripped.startswith("#"):
            out.append("")
            continue

        out.append(raw)

        # A single line may open several heredocs; consume them in order.
        opened_tags = [m.group("tag") for m in HEREDOC_START_RE.finditer(raw)]
        if opened_tags:
            active_tag = opened_tags[0]
            pending_tags.extend(opened_tags[1:])

    return "\n".join(out)


def function_definitions(text: str) -> set[str]:
    return set(FUNCTION_DEF_RE.findall(text)) | set(
        FUNCTION_KEYWORD_DEF_RE.findall(text)
    )


def sourced_basenames(text: str) -> set[str]:
    """Return the basenames of shell files this text sources.

    Paths are interpolated (``${_LIB_DIR}/credentials.sh``,
    ``${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh``), so resolving
    them literally is unreliable. Shared-library basenames are unique across
    the tree, which makes basename matching both sound and interpolation-proof.
    """
    return {Path(m.group("path")).name for m in SOURCE_RE.finditer(text)}


def build_shared_library_index() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Map each shared module to the functions it defines and modules it sources."""
    defines: dict[str, set[str]] = {}
    sources: dict[str, set[str]] = {}
    for path in sorted(SHARED_LIB_DIR.glob("*.sh")):
        text = strip_comments_and_heredocs(path.read_text(encoding="utf-8"))
        defines[path.name] = function_definitions(text)
        sources[path.name] = sourced_basenames(text)
    return defines, sources


def reachable_modules(
    entry_points: set[str], sources: dict[str, set[str]]
) -> set[str]:
    """Transitively expand sourced modules.

    Several modules source their dependencies from inside an ``if`` guard
    (``cluster_helpers.sh``, ``license_helpers.sh``, ``soar_helpers.sh``).
    Conditional sourcing still makes the helpers available, so the walk stays
    flow-insensitive on purpose rather than trying to prove the branch is taken.
    """
    seen: set[str] = set()
    queue = [name for name in entry_points if name in sources]
    while queue:
        module = queue.pop()
        if module in seen:
            continue
        seen.add(module)
        queue.extend(child for child in sources.get(module, ()) if child in sources)
    return seen


def iter_skill_scripts() -> list[Path]:
    return sorted(
        path
        for path in SKILLS_DIR.rglob("*.sh")
        if SHARED_LIB_DIR not in path.parents
    )


def check_script(
    path: Path,
    shared_defines: dict[str, set[str]],
    shared_sources: dict[str, set[str]],
    all_shared_functions: set[str],
) -> list[str]:
    text = strip_comments_and_heredocs(path.read_text(encoding="utf-8"))

    local_definitions = function_definitions(text)
    sourced = sourced_basenames(text)

    # A skill may source a sibling script in its own directory; fold in the
    # helpers that file defines so locally-shared code is not misreported.
    local_dir = path.parent
    pending_local = list(sourced)
    inspected_local: set[str] = set()
    while pending_local:
        basename = pending_local.pop()
        if basename in inspected_local:
            continue
        inspected_local.add(basename)
        if basename in shared_defines:
            continue
        sibling = local_dir / basename
        if sibling.is_file():
            sibling_text = strip_comments_and_heredocs(
                sibling.read_text(encoding="utf-8")
            )
            local_definitions |= function_definitions(sibling_text)
            sibling_sources = sourced_basenames(sibling_text)
            sourced |= sibling_sources
            pending_local.extend(sibling_sources - inspected_local)

    modules = reachable_modules(sourced, shared_sources)
    available: set[str] = set()
    for module in modules:
        available |= shared_defines.get(module, set())

    candidates = (all_shared_functions - available) - local_definitions
    if not candidates:
        return []

    called = command_words(text)
    unresolved = candidates & called.keys()
    if not unresolved:
        return []

    rel = path.relative_to(REPO_ROOT)
    errors: list[str] = []
    for name in sorted(unresolved):
        providers = sorted(
            module for module, funcs in shared_defines.items() if name in funcs
        )
        errors.append(
            f"{rel}:{called[name]}: calls shared helper '{name}' but does not "
            f"source {' or '.join(providers)}"
        )
    return errors


def main() -> int:
    shared_defines, shared_sources = build_shared_library_index()
    if not shared_defines:
        print("ERROR: no shared library modules found", file=sys.stderr)
        return 1

    all_shared_functions: set[str] = set()
    for funcs in shared_defines.values():
        all_shared_functions |= funcs

    scripts = iter_skill_scripts()
    if not scripts:
        print("ERROR: no skill shell scripts found", file=sys.stderr)
        return 1

    errors: list[str] = []
    for script in scripts:
        errors.extend(
            check_script(
                script, shared_defines, shared_sources, all_shared_functions
            )
        )

    if errors:
        print("Unresolved shared-library helper calls:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(
        f"All {len(scripts)} skill shell scripts resolve their "
        f"{len(all_shared_functions)} shared-library helper calls."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
