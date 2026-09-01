"""Keep agent instruction files within the default Codex project budget."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_CONTEXT_BYTES = 32 * 1024
INDEX_MARKER = "## Skill Index"


def test_generated_context_files_fit_the_default_instruction_budget() -> None:
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = REPO_ROOT / name
        content = path.read_text(encoding="utf-8")
        assert len(content.encode("utf-8")) < MAX_CONTEXT_BYTES, (
            f"{name} exceeds the 32 KiB project-instruction limit"
        )
        assert INDEX_MARKER in content
