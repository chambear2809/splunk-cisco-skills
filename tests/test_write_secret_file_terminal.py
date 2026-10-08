"""Terminal and noninteractive guards for write_secret_file.sh."""

from __future__ import annotations

import os
import pty
import select
import fcntl
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WRITER = REPO_ROOT / "skills/shared/scripts/write_secret_file.sh"


def _run_pty(output: Path, responses: list[str]) -> tuple[int, str]:
    master, slave = pty.openpty()
    flags = fcntl.fcntl(master, fcntl.F_GETFL)
    fcntl.fcntl(master, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    proc = subprocess.Popen(
        ["bash", str(WRITER), str(output)],
        cwd=REPO_ROOT,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
    )
    os.close(slave)
    transcript = bytearray()
    try:
        for index, response in enumerate(responses):
            marker = b"Confirm Secret: " if index else b"Secret: "
            while True:
                ready, _, _ = select.select([master], [], [], 10)
                assert ready, transcript.decode(errors="replace")
                chunk = os.read(master, 4096)
                transcript.extend(chunk)
                if marker in transcript:
                    break
            os.write(master, response.encode() + b"\r")
        proc.wait(timeout=10)
    finally:
        os.close(master)
    return proc.returncode, transcript.decode(errors="replace")


def test_terminal_prompts_hide_matching_confirmation_and_writes_mode_600(tmp_path: Path) -> None:
    output = tmp_path / "secret"
    rc, transcript = _run_pty(output, ["SYNTHETIC_TERMINAL_SECRET", "SYNTHETIC_TERMINAL_SECRET"])
    assert rc == 0, transcript
    assert output.read_text(encoding="utf-8") == "SYNTHETIC_TERMINAL_SECRET\n"
    assert output.stat().st_mode & 0o777 == 0o600
    assert "SYNTHETIC_TERMINAL_SECRET" not in transcript


def test_terminal_mismatch_refuses_without_publishing_file(tmp_path: Path) -> None:
    output = tmp_path / "secret"
    rc, transcript = _run_pty(output, ["FIRST_SYNTHETIC_SECRET", "SECOND_SYNTHETIC_SECRET"])
    assert rc != 0
    assert not output.exists()


def test_noninteractive_pipe_is_rejected_without_output_file(tmp_path: Path) -> None:
    output = tmp_path / "secret"
    result = subprocess.run(
        ["bash", str(WRITER), str(output)],
        input="PIPE_SECRET\nPIPE_SECRET\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "non-interactive stdin" in result.stderr
    assert not output.exists()
