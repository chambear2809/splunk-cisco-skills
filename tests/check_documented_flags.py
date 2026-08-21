#!/usr/bin/env python3
"""Verify every flag shown in skill documentation is accepted by the script.

A copy-pasteable command in SKILL.md, reference.md, or a references/**/*.md
annex is a contract. When an example passes a flag the target script never
parses, the command exits non-zero the first time an operator runs it. This
check extracts the flags from documented invocations and compares them against
the flags the invoked script actually parses.
"""

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"

DOC_FILENAMES = ("SKILL.md", "reference.md")

# A documented command line starts with an interpreter or an explicit relative
# path. Requiring that prefix keeps prose that merely names a flag from being
# parsed as an invocation.
COMMAND_LINE_RE = re.compile(
    r"^[ \t]*(?:bash|sh|python3|python)[ \t]+(?P<rest>\S.*)$|"
    r"^[ \t]*(?P<direct>\./\S+\.(?:sh|py))(?P<direct_rest>.*)$"
)

FLAG_RE = re.compile(r"(?<![A-Za-z0-9_-])--([a-z0-9][a-z0-9-]*)")

# Matches a case arm, including alternations and prefix-match arms:
#   --name)            -h|--help)            --name=*)
# Deliberately not anchored to the start of a line so that single-line arms
# such as `--name) require_arg "$1" $# || exit 1; NAME="$2"; shift 2 ;;` are
# detected the same as arms written across several lines.
CASE_ARM_RE = re.compile(
    r"((?:-{1,2}[A-Za-z0-9][A-Za-z0-9-]*(?:=\*)?\|)*"
    r"-{1,2}[A-Za-z0-9][A-Za-z0-9-]*(?:=\*)?)[ \t]*\)"
)

# Some scripts answer `--help` from an `if` guard above the argument loop
# rather than from a `case` arm, e.g.
#   if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then usage; fi
# Those flags are genuinely accepted, so harvest flag literals out of test
# conditions as well.
TEST_CONDITION_RE = re.compile(r"\[\[(.*?)\]\]|\[(.*?)\]", re.DOTALL)

# Dispatchers forward the entire argument vector to a sibling implementation:
#   exec bash "${SCRIPT_DIR}/install_app.sh" "$@"
# The dispatcher itself parses none of those flags, so the sibling's parser has
# to be folded in before judging the documented command.
PASSTHROUGH_RE = re.compile(
    r"""(?:exec[ \t]+)?(?:bash|sh|python3|python)[ \t]+"""
    r"""["']?\$\{?[A-Za-z_][A-Za-z0-9_]*\}?/(?P<target>[A-Za-z0-9_.-]+\.(?:sh|py))["']?"""
    r"""[ \t]+["']?\$@["']?"""
)

MAX_PASSTHROUGH_DEPTH = 4

# Sentinel recorded when a parser builds flag names in a way this checker
# cannot resolve statically. Its presence downgrades the target to "unknown"
# rather than letting an unreadable parser masquerade as a strict allow-list.
OPAQUE_PARSER = "\x00opaque"


def join_continuations(text: str) -> list[tuple[int, str]]:
    """Fold backslash-continued lines into one logical line.

    Documented commands are wrapped for readability, so the flags of a single
    invocation are spread across several physical lines. The first physical
    line number is retained for reporting.
    """
    joined: list[tuple[int, str]] = []
    buffer = ""
    start_line = 0
    for lineno, raw in enumerate(text.splitlines(), 1):
        stripped = raw.rstrip()
        if not buffer:
            start_line = lineno
        if stripped.endswith("\\"):
            buffer += stripped[:-1] + " "
            continue
        joined.append((start_line, buffer + stripped))
        buffer = ""
    if buffer:
        joined.append((start_line, buffer))
    return joined


def documented_invocations(text: str) -> list[tuple[int, str, set[str]]]:
    """Return (line, script token, flags) for each documented command."""
    results: list[tuple[int, str, set[str]]] = []
    for lineno, line in join_continuations(text):
        match = COMMAND_LINE_RE.match(line)
        if match is None:
            continue
        if match.group("direct"):
            script_token = match.group("direct")
            remainder = match.group("direct_rest") or ""
        else:
            rest = match.group("rest")
            parts = rest.split()
            if not parts:
                continue
            script_token = parts[0]
            remainder = " ".join(parts[1:])
        script_token = script_token.strip("\"'")
        if not script_token.endswith((".sh", ".py")):
            continue
        flags = {f"--{name}" for name in FLAG_RE.findall(remainder)}
        if flags:
            results.append((lineno, script_token, flags))
    return results


def resolve_script(script_token: str, skill_dir: Path) -> Path | None:
    """Resolve a documented script token to a file on disk.

    Repository-rooted tokens (``skills/<other-skill>/scripts/x.sh``) are
    cross-skill invocations and must resolve against the repository root, not
    against the skill whose documentation mentions them. Tokens containing a
    shell variable cannot be resolved statically and are skipped.
    """
    if "$" in script_token or "<" in script_token or ">" in script_token:
        return None

    if script_token.startswith("skills/"):
        candidate = REPO_ROOT / script_token
    else:
        candidate = skill_dir / script_token.removeprefix("./")

    try:
        resolved = candidate.resolve()
        resolved.relative_to(REPO_ROOT)
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def bash_accepted_flags(text: str) -> set[str]:
    flags: set[str] = set()
    for arm in CASE_ARM_RE.findall(text):
        for token in arm.split("|"):
            token = token.removesuffix("=*")
            if token.startswith("--"):
                flags.add(token)
    for group_a, group_b in TEST_CONDITION_RE.findall(text):
        condition = group_a or group_b
        for name in FLAG_RE.findall(condition):
            flags.add(f"--{name}")
    return flags


def _is_argument_parser(func: ast.expr) -> bool:
    """Match ``argparse.ArgumentParser`` and repo subclasses like ``JsonArgumentParser``."""
    if isinstance(func, ast.Attribute):
        return func.attr.endswith("ArgumentParser")
    if isinstance(func, ast.Name):
        return func.id.endswith("ArgumentParser")
    return False


def _argparse_provides_help(tree: ast.AST) -> bool:
    """Report whether argparse contributes ``--help`` on its own.

    argparse registers ``-h/--help`` automatically unless a parser opts out
    with ``add_help=False``. Documentation that shows ``--help`` is therefore
    correct even though no ``add_argument("--help")`` call exists.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_argument_parser(node.func):
            continue
        opt_out = next(
            (kw for kw in node.keywords if kw.arg == "add_help"), None
        )
        if opt_out is None:
            return True
        if not (
            isinstance(opt_out.value, ast.Constant) and opt_out.value.value is False
        ):
            return True
    return False


def _loop_constant_values(tree: ast.AST) -> dict[str, set[str]]:
    """Map for-loop variables to the constant strings they iterate over."""
    values: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.For) or not isinstance(node.target, ast.Name):
            continue
        if not isinstance(node.iter, (ast.Tuple, ast.List, ast.Set)):
            continue
        constants = {
            element.value
            for element in node.iter.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
        if constants:
            values.setdefault(node.target.id, set()).update(constants)
    return values


def _expand_joined_str(
    node: ast.JoinedStr, loop_values: dict[str, set[str]]
) -> set[str] | None:
    """Expand ``add_argument(f"--{flag}")`` against its loop's constant list.

    Several lifecycle scripts declare families of mode flags in a loop rather
    than one ``add_argument`` per flag. Returns ``None`` when the interpolation
    cannot be resolved so the caller can fall back to skipping the file instead
    of reporting flags it simply failed to read.
    """
    prefix: list[str] = []
    for part in node.values:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            prefix.append(part.value)
            continue
        if isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name):
            names = loop_values.get(part.value.id)
            if not names:
                return None
            head = "".join(prefix)
            return {f"{head}{name}" for name in names}
        return None
    return set()


def python_accepted_flags(text: str) -> set[str]:
    """Collect argparse option strings via AST so multi-line calls are covered."""
    flags: set[str] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return flags

    loop_values = _loop_constant_values(tree)
    if _argparse_provides_help(tree):
        flags.add("--help")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "add_argument":
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if arg.value.startswith("--"):
                    flags.add(arg.value)
            elif isinstance(arg, ast.JoinedStr):
                expanded = _expand_joined_str(arg, loop_values)
                if expanded is None:
                    # An interpolated flag name we cannot resolve statically.
                    # Marking the parser as opaque keeps the checker from
                    # reporting flags it merely failed to read.
                    flags.add(OPAQUE_PARSER)
                else:
                    flags |= {f for f in expanded if f.startswith("--")}
    return flags


def accepted_flags(path: Path, depth: int = 0) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()

    if path.suffix == ".py":
        flags = python_accepted_flags(text)
    else:
        flags = bash_accepted_flags(text)

    if depth < MAX_PASSTHROUGH_DEPTH:
        for target in PASSTHROUGH_RE.findall(text):
            sibling = path.parent / target
            if sibling.is_file():
                flags |= accepted_flags(sibling, depth + 1)
    return flags


def documentation_files(skill_dir: Path) -> list[Path]:
    """Return the primary docs plus every nested Markdown reference annex."""

    docs = [skill_dir / name for name in DOC_FILENAMES]
    references_dir = skill_dir / "references"
    if references_dir.is_dir():
        docs.extend(sorted(references_dir.rglob("*.md")))
    return [path for path in docs if path.is_file()]


def check_skill(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    cache: dict[Path, set[str]] = {}

    for doc in documentation_files(skill_dir):
        text = doc.read_text(encoding="utf-8")
        for lineno, script_token, flags in documented_invocations(text):
            script = resolve_script(script_token, skill_dir)
            if script is None:
                continue
            if script not in cache:
                cache[script] = accepted_flags(script)
            supported = cache[script]
            if not supported or OPAQUE_PARSER in supported:
                continue
            missing = sorted(flags - supported)
            if missing:
                rel_doc = doc.relative_to(REPO_ROOT)
                rel_script = script.relative_to(REPO_ROOT)
                errors.append(
                    f"{rel_doc}:{lineno}: documents {', '.join(missing)} but "
                    f"{rel_script} does not accept "
                    f"{'them' if len(missing) > 1 else 'it'}"
                )
    return errors


def main() -> int:
    skill_dirs = sorted(
        path.parent for path in SKILLS_DIR.glob("*/SKILL.md")
    )
    if not skill_dirs:
        print("ERROR: no skill directories found under skills/", file=sys.stderr)
        return 1

    errors: list[str] = []
    for skill_dir in skill_dirs:
        errors.extend(check_skill(skill_dir))

    if errors:
        print("Documented flags rejected by their target scripts:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(
        f"All documented command flags across {len(skill_dirs)} skills are "
        "accepted by their target scripts."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
