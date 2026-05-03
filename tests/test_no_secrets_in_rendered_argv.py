"""Repository-wide regression: rendered scripts MUST NOT leak secrets to argv.

The repo's `AGENTS.md` / `CLAUDE.md` policy forbids putting Splunk admin
passwords, idxc cluster `pass4SymmKey` material, SOAR admin passwords, EP
Bearer tokens, or any other credential on a child process's argv (visible
to other users via `ps` / `/proc/*/cmdline`). The shared helpers in this
repo (`splunk_curl`, `get_session_key_from_password_file`,
`license_helpers.sh`, `cluster_helpers.sh`, `edge_processor_helpers.sh`,
`soar_helpers.sh`) are written to keep secrets off argv via curl
`-K <(...)` / `--data-urlencode @file` / `--netrc-file` patterns.

This test exercises each render-first skill that previously regressed
(splunk-license-manager-setup, splunk-indexer-cluster-setup,
splunk-edge-processor-setup, splunk-soar-setup) and asserts that every
rendered shell script:
  1. Parses with `bash -n`.
  2. Does NOT contain `curl ... -u "<user>:${PASSWORD_VARIABLE}"` or
     `splunk ... -auth admin:${...}` patterns where the password is
     interpolated into argv.
  3. Does NOT contain `curl -H "Authorization: Bearer ${TOKEN}"` or
     `curl -H "ph-auth-token: ${TOKEN}"` style header expansion that
     puts the token literal in curl argv.
  4. Does NOT pass `-secret ${SECRET}` to a remote ssh-driven `splunk`
     command line (cluster pass4SymmKey leak class).

The matchers are intentionally narrow so they only flag actual argv
leaks; comments / docs that mention the patterns are excluded.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


# Each entry: (skill_dir_under_skills, setup_args, rendered_subdir)
# `rendered_subdir` is the path under the output dir that contains the
# rendered shell scripts to scan. Use "" if the scripts live directly under
# the output dir.
RENDER_CASES = [
    pytest.param(
        "splunk-license-manager-setup",
        [
            "--phase", "render",
            "--license-manager-uri", "https://lm01.example.com:8089",
            "--license-files", "/etc/splunk/enterprise.lic",
            "--license-group", "Enterprise",
            "--pool-spec", "name=ent_main,stack_id=enterprise,quota=MAX",
            "--peer-hosts", "idx01.example.com,idx02.example.com",
        ],
        "license",
        id="license-manager",
    ),
    pytest.param(
        "splunk-indexer-cluster-setup",
        [
            "--cluster-manager-uri", "https://cm.example.com:8089",
            "--manager-hosts", "cm.example.com",
            "--peer-hosts", "peer1.example.com,peer2.example.com,peer3.example.com",
            "--sh-hosts", "sh1.example.com",
        ],
        "cluster",
        id="indexer-cluster",
    ),
    pytest.param(
        "splunk-edge-processor-setup",
        [
            "--ep-name", "ep-prod",
            "--ep-tenant-url", "https://stack.splunkcloud.com:8089",
            "--ep-instances", "h1=systemd,h2=systemd",
            "--ep-destinations", "indexer-cloud=type=s2s;host=stack.splunkcloud.com;port=9997",
            "--ep-default-destination", "indexer-cloud",
        ],
        "",
        id="edge-processor",
    ),
    pytest.param(
        "splunk-soar-setup",
        [
            "--soar-platform", "onprem-single",
        ],
        "",
        id="soar",
    ),
]


# Matchers for each leak class. Comment lines (leading optional whitespace
# then `#`) are stripped before matching.
LEAK_PATTERNS = [
    (
        "curl -u with shell-variable password",
        re.compile(
            r"""curl[^|;\n]*?-u\s+["']?[A-Za-z0-9_.\-]+:\$\{?[A-Za-z_][A-Za-z0-9_]*""",
            re.MULTILINE,
        ),
    ),
    (
        "splunk ... -auth admin:${VAR} (CLI auth on argv)",
        re.compile(
            r"""splunk(?:forwarder)?[^|;\n]*?-auth\s+["']?[A-Za-z0-9_.\-]+:\$\{?[A-Za-z_][A-Za-z0-9_]*""",
            re.MULTILINE,
        ),
    ),
    (
        "curl -H 'Authorization: Bearer ${VAR}' (token on argv)",
        re.compile(
            r"""curl[^|;\n]*?-H\s+["']?Authorization:\s+Bearer\s+\$\{?[A-Za-z_][A-Za-z0-9_]*""",
            re.MULTILINE,
        ),
    ),
    (
        "curl -H 'ph-auth-token: ${VAR}' (SOAR token on argv)",
        re.compile(
            r"""curl[^|;\n]*?-H\s+["']?ph-auth-token:\s+\$\{?[A-Za-z_][A-Za-z0-9_]*""",
            re.MULTILINE,
        ),
    ),
    (
        "ssh ... splunk ... -secret ${VAR} (cluster pass4SymmKey leak)",
        re.compile(
            r"""ssh[^|;\n]*?-secret\s+\$\{?[A-Za-z_][A-Za-z0-9_]*""",
            re.MULTILINE,
        ),
    ),
    (
        "psql -c with shell-variable password",
        re.compile(
            r"""psql[^|;\n]*?-c\s+["'][^"']*PASSWORD\s+\\?'\$\{?[A-Za-z_][A-Za-z0-9_]*""",
            re.MULTILINE,
        ),
    ),
]


def _strip_comments(text: str) -> str:
    """Return `text` with shell comment lines removed.

    A comment line is one whose first non-whitespace character is `#`.
    Inline `#` after code is left in place because shell quoting can
    legitimately contain `#`. The leak matchers do not care about the
    surrounding text either way; this is purely to reduce false positives
    from comments that talk about the leak class they are protecting.
    """
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


def _render(skill: str, args: list[str], output_dir: Path) -> None:
    setup = REPO_ROOT / "skills" / skill / "scripts" / "setup.sh"
    cmd = ["bash", str(setup), *args, "--output-dir", str(output_dir)]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, (
        f"rendering {skill} failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def _all_shell_scripts(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.sh") if p.is_file())


@pytest.mark.parametrize("skill, setup_args, rendered_subdir", RENDER_CASES)
def test_rendered_shell_scripts_are_syntactically_valid(
    tmp_path: Path,
    skill: str,
    setup_args: list[str],
    rendered_subdir: str,
) -> None:
    output_dir = tmp_path / skill
    _render(skill, setup_args, output_dir)

    scan_root = output_dir / rendered_subdir if rendered_subdir else output_dir
    scripts = _all_shell_scripts(scan_root)
    assert scripts, f"{skill}: no rendered .sh files under {scan_root}"

    for script in scripts:
        result = subprocess.run(
            ["bash", "-n", str(script)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"{skill}: rendered script failed bash -n: {script}\n{result.stderr}"
        )


@pytest.mark.parametrize("skill, setup_args, rendered_subdir", RENDER_CASES)
def test_rendered_shell_scripts_do_not_leak_secrets_to_argv(
    tmp_path: Path,
    skill: str,
    setup_args: list[str],
    rendered_subdir: str,
) -> None:
    """Block re-introduction of the argv-secrets pattern.

    When this test fails for a new skill, the fix is to feed the secret
    via curl `-K <(...)`, `--data-urlencode @file`, `--netrc-file`, or
    `--header @file` rather than expanding the shell variable into argv.
    See `skills/shared/lib/license_helpers.sh` and
    `skills/shared/lib/cluster_helpers.sh` for the established patterns.
    """
    output_dir = tmp_path / skill
    _render(skill, setup_args, output_dir)

    scan_root = output_dir / rendered_subdir if rendered_subdir else output_dir
    scripts = _all_shell_scripts(scan_root)
    assert scripts, f"{skill}: no rendered .sh files under {scan_root}"

    failures: list[str] = []
    for script in scripts:
        body = script.read_text(encoding="utf-8")
        body_no_comments = _strip_comments(body)
        for label, pattern in LEAK_PATTERNS:
            for match in pattern.finditer(body_no_comments):
                failures.append(
                    f"{script.relative_to(output_dir)}: {label}: {match.group(0)!r}"
                )

    assert not failures, (
        f"{skill}: rendered scripts leak secrets to argv:\n  - "
        + "\n  - ".join(failures)
    )


def test_shared_helpers_do_not_use_curl_minus_u_or_minus_auth() -> None:
    """The four shared helper libraries refactored in this changeset MUST
    use the `splunk_curl` / `--netrc-file` / `--data-urlencode @file`
    pattern instead of `curl -u user:pass` or `splunk ... -auth user:pw`.
    This complements the per-renderer test above by pinning the helpers
    themselves.
    """
    helpers = [
        REPO_ROOT / "skills/shared/lib/license_helpers.sh",
        REPO_ROOT / "skills/shared/lib/cluster_helpers.sh",
        REPO_ROOT / "skills/shared/lib/edge_processor_helpers.sh",
        REPO_ROOT / "skills/shared/lib/soar_helpers.sh",
    ]

    failures: list[str] = []
    for helper in helpers:
        text = helper.read_text(encoding="utf-8")
        text_no_comments = _strip_comments(text)
        for label, pattern in LEAK_PATTERNS:
            for match in pattern.finditer(text_no_comments):
                failures.append(
                    f"{helper.relative_to(REPO_ROOT)}: {label}: {match.group(0)!r}"
                )

    assert not failures, (
        "shared helpers leak secrets to argv:\n  - " + "\n  - ".join(failures)
    )
