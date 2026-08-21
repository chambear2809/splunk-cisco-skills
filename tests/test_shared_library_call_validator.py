"""Regression tests for the shared shell-library call validator itself."""

from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / "tests/check_shared_library_calls.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("shared_library_call_checker", CHECKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_multiple_heredocs_on_one_command_are_all_removed() -> None:
    checker = load_checker()
    source = """render <<FIRST 3<<'SECOND'
shared_one should_not_count
FIRST
shared_two should_not_count
SECOND
real_helper argument
"""

    stripped = checker.strip_comments_and_heredocs(source)

    assert "shared_one" not in stripped
    assert "shared_two" not in stripped
    assert "real_helper argument" in stripped


def test_nested_sibling_sources_are_traversed_without_mutating_iteration(
    tmp_path: Path,
) -> None:
    checker = load_checker()
    main = tmp_path / "main.sh"
    first = tmp_path / "first.sh"
    second = tmp_path / "second.sh"
    main.write_text("source first.sh\nlocal_helper\n", encoding="utf-8")
    first.write_text("source second.sh\n", encoding="utf-8")
    second.write_text("local_helper() { :; }\n", encoding="utf-8")

    errors = checker.check_script(
        main,
        shared_defines={"shared.sh": {"local_helper"}},
        shared_sources={"shared.sh": set()},
        all_shared_functions={"local_helper"},
    )

    assert errors == []
