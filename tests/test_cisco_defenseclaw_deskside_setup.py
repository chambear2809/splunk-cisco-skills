from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "cisco-defenseclaw-deskside-setup"


def test_deskside_setup_requires_pinned_ssh_and_explicit_replacement() -> None:
    setup = (SKILL_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")

    assert "StrictHostKeyChecking=yes" in setup
    assert "GlobalKnownHostsFile=/dev/null" in setup
    assert "ssh-keygen -F" in setup
    assert "--replace-active-model" in setup
    assert "--connector none" in setup
    assert "Qwen3.6-27B-GGUF" in setup
    assert "--release VERSION or --release latest is required with --apply" in setup
    assert "http://127.0.0.1:13305/api/v1" in setup
    assert "--guardrail-mode" in setup
    assert "--provider lm_studio" in setup
    assert "defenseclaw setup codex" in setup
    assert "skill-scanner mcp-scanner" in setup
    assert "codex --strict-config --version" in setup
    assert "trap rollback ERR" in setup
    assert "Timed out waiting for one Lemonade inference model to become ready." in setup
    assert "config_existed=false" in setup


def test_deskside_validation_can_run_a_bounded_inference_canary() -> None:
    validator = (SKILL_ROOT / "scripts" / "validate.sh").read_text(encoding="utf-8")

    assert "--check-inference" in validator
    assert "--expect-mode" in validator
    assert "Qwen3.6-27B-GGUF" in validator
    assert "lm_studio" in validator
    assert "max_tokens: 2" in validator
    assert "StrictHostKeyChecking=yes" in validator


def test_deskside_skill_documentation_states_the_container_boundary() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "does not publish an OCI runtime image" in skill
    assert "stable server API on port 13305" in skill
    assert "observe mode" in skill
