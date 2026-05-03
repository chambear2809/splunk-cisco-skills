"""Offline regressions for Splunk Enterprise Security install controls."""

from __future__ import annotations

import re
import stat
import subprocess
import tarfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SETUP = REPO_ROOT / "skills/splunk-enterprise-security-install/scripts/setup.sh"
TA_GENERATOR = REPO_ROOT / "skills/splunk-enterprise-security-install/scripts/generate_ta_for_indexers.sh"


def run_bash(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", *args],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def make_fake_es_package(path: Path, payload: bytes = b"fake-ta-for-indexers", member_name: str | None = None, extra_members: list[tuple[str, bytes]] | None = None) -> None:
    if member_name is None:
        member_name = (
            "SplunkEnterpriseSecuritySuite/install/splunkcloud/splunk_app_es/"
            "Splunk_TA_ForIndexers-1.2.3.spl"
        )
    payload_path = path.parent / Path(member_name).name
    payload_path.write_bytes(payload)
    extra_paths: list[Path] = []
    try:
        with tarfile.open(path, "w:gz") as tf:
            tf.add(payload_path, arcname=member_name)
            for extra_arcname, extra_payload in extra_members or []:
                extra_path = path.parent / Path(extra_arcname).name
                extra_path.write_bytes(extra_payload)
                extra_paths.append(extra_path)
                tf.add(extra_path, arcname=extra_arcname)
    finally:
        payload_path.unlink(missing_ok=True)
        for extra_path in extra_paths:
            extra_path.unlink(missing_ok=True)


def test_install_help_documents_preflight_and_ta_controls() -> None:
    result = run_bash(str(INSTALL_SETUP), "--help")

    assert result.returncode == 0
    for expected in (
        "--preflight-only",
        "--skip-preflight",
        "--confirm-upgrade",
        "--backup-notice PATH",
        "--set-shc-limits",
        "--apply-bundle",
        "--generate-ta-for-indexers DIR",
        "--deploy-ta-for-indexers CM_URI",
    ):
        assert expected in result.stdout


def test_uninstall_help_does_not_promise_kv_cleanup() -> None:
    result = run_bash(str(INSTALL_SETUP), "--help")

    assert result.returncode == 0
    assert "clear ES KV collections" not in result.stdout
    assert "Disable removable framework apps" in result.stdout


def test_install_setup_rejects_missing_values_for_new_flags() -> None:
    for flag in (
        "--backup-notice",
        "--shc-target-uri",
        "--generate-ta-for-indexers",
        "--deploy-ta-for-indexers",
    ):
        result = run_bash(str(INSTALL_SETUP), flag)

        assert result.returncode == 1, flag
        assert "requires a value" in result.stdout
        assert "unbound variable" not in result.stdout


def test_uninstall_rejects_mixed_actions_before_credentials(tmp_path: Path) -> None:
    cases = (
        ("--install", "--uninstall"),
        ("--uninstall", "--post-install"),
        ("--uninstall", "--validate"),
        ("--uninstall", "--preflight-only"),
        ("--uninstall", "--backup-kvstore"),
        ("--uninstall", "--apply-bundle"),
        ("--uninstall", "--generate-ta-for-indexers", str(tmp_path / "ta")),
        ("--uninstall", "--deploy-ta-for-indexers", "https://cm.example:8089"),
    )
    for args in cases:
        result = run_bash(str(INSTALL_SETUP), *args)

        assert result.returncode == 1, args
        assert "--uninstall must be run by itself" in result.stdout
        assert "Connected to Splunk" not in result.stdout


def _bash_function_body(text: str, name: str) -> str:
    """Return the body of a bash function `name` declared as `name() { ... }`.

    Tracks brace depth to find the matching closing brace, so the test does
    not break when adjacent functions are reordered or new helpers are
    inserted between this function and its old neighbor.
    """
    pattern = re.compile(rf"^{re.escape(name)}\s*\(\)\s*\{{", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        raise AssertionError(f"function {name!r} not found in setup.sh")
    depth = 1
    index = match.end()
    while index < len(text) and depth > 0:
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        index += 1
    if depth != 0:
        raise AssertionError(f"unbalanced braces while reading {name!r} body")
    return text[match.start():index]


def test_uninstall_does_not_target_missioncontrol() -> None:
    text = INSTALL_SETUP.read_text(encoding="utf-8")
    uninstall_block = _bash_function_body(text, "run_uninstall")

    assert '"missioncontrol"' not in uninstall_block
    assert "Keeping missioncontrol installed" in uninstall_block


def test_backup_kvstore_runs_before_install() -> None:
    """KV Store backup must come BEFORE install/upgrade so a failed install
    leaves the operator with a pre-change snapshot."""
    text = INSTALL_SETUP.read_text(encoding="utf-8")
    backup_call = text.find('if [[ "${BACKUP_KVSTORE}" == "true" ]]; then')
    install_call = text.find('if [[ "${DO_INSTALL}" == "true" ]]; then')

    assert backup_call != -1, "backup_kvstore guard not found in setup.sh"
    assert install_call != -1, "install guard not found in setup.sh"
    # Find the workflow-level invocations (after function definitions). The
    # very last occurrences in the file are the executable workflow blocks.
    workflow_backup = text.rfind('if [[ "${BACKUP_KVSTORE}" == "true" ]]; then')
    workflow_install = text.rfind('if [[ "${DO_INSTALL}" == "true" ]]; then')
    assert workflow_backup < workflow_install, (
        "backup_kvstore workflow block must precede install_es_package; "
        f"backup at {workflow_backup}, install at {workflow_install}"
    )


def test_essinstall_detects_runtime_errors_in_http_200_response() -> None:
    """The essinstall HTTP-200 path must surface FATAL/ERROR markers."""
    text = INSTALL_SETUP.read_text(encoding="utf-8")
    assert "essinstall_detect_errors()" in text
    body = _bash_function_body(text, "essinstall_detect_errors")
    assert '"FATAL"' in body and '"ERROR"' in body
    run_body = _bash_function_body(text, "run_essinstall")
    assert "essinstall_detect_errors" in run_body
    assert "essinstall reported runtime error" in run_body


def test_essinstall_detect_errors_flags_fatal_messages_in_stream(tmp_path: Path) -> None:
    """Extract `essinstall_detect_errors` from setup.sh and run it against
    synthetic NDJSON output. This exercises the actual function body, not a
    copy, so a future drift breaks the test instead of silently passing."""
    text = INSTALL_SETUP.read_text(encoding="utf-8")
    body = _bash_function_body(text, "essinstall_detect_errors")

    fake = tmp_path / "probe.sh"
    fake.write_text(
        "set -euo pipefail\n"
        + body
        + "\n"
        + 'fatal_body=$(printf \'%s\\n\' '
        + "'{\"preview\":false,\"messages\":[{\"type\":\"FATAL\",\"text\":\"missing index\"}]}' "
        + "'{\"preview\":false,\"messages\":[{\"type\":\"INFO\",\"text\":\"ok\"}]}'"
        + ")\n"
        + 'essinstall_detect_errors "${fatal_body}" > "$1"\n',
        encoding="utf-8",
    )
    out_path = tmp_path / "out.txt"
    result = subprocess.run(["bash", str(fake), str(out_path)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "FATAL: missing index" in out_path.read_text(encoding="utf-8")

    clean_fake = tmp_path / "probe_clean.sh"
    clean_fake.write_text(
        "set -euo pipefail\n"
        + body
        + "\n"
        + 'clean_body=\'{"preview":false,"messages":[{"type":"INFO","text":"all good"}]}\'\n'
        + 'essinstall_detect_errors "${clean_body}" > "$1"\n',
        encoding="utf-8",
    )
    clean_out = tmp_path / "clean_out.txt"
    result = subprocess.run(["bash", str(clean_fake), str(clean_out)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert clean_out.read_text(encoding="utf-8").strip() == ""


def test_force_apply_bundle_flag_documented_in_help() -> None:
    """--force-apply-bundle must appear in help text and be a recognized flag."""
    result = run_bash(str(INSTALL_SETUP), "--help")
    assert result.returncode == 0
    assert "--force-apply-bundle" in result.stdout


def test_validate_cluster_bundle_returns_nonzero_on_failure() -> None:
    """The validate function must FAIL apply unless --force-apply-bundle is set."""
    text = INSTALL_SETUP.read_text(encoding="utf-8")
    body = _bash_function_body(text, "validate_cluster_bundle_on_cm")
    assert "FORCE_APPLY_BUNDLE" in body, "validate must consult --force-apply-bundle"
    assert "return 1" in body, "validate must be able to return non-zero"


def test_shc_post_apply_health_uses_shc_target_uri() -> None:
    text = INSTALL_SETUP.read_text(encoding="utf-8")
    body = _bash_function_body(text, "shc_post_apply_health")
    assert "${SHC_TARGET_URI:-${SPLUNK_URI}}" in body, (
        "post-apply health must prefer SHC_TARGET_URI when set"
    )


def test_deploy_ta_aborts_on_cm_uri_profile_mismatch() -> None:
    text = INSTALL_SETUP.read_text(encoding="utf-8")
    body = _bash_function_body(text, "deploy_ta_for_indexers")
    assert "extract_uri_host" in body
    assert "does not match" in body


def test_generate_ta_for_indexers_picks_highest_version_when_multiple(tmp_path: Path) -> None:
    """When multiple Splunk_TA_ForIndexers members exist, pick the newest by version."""
    package = tmp_path / "splunk-enterprise-security_fake.spl"
    output_dir = tmp_path / "out"
    primary_member = (
        "SplunkEnterpriseSecuritySuite/install/splunkcloud/splunk_app_es/"
        "Splunk_TA_ForIndexers-1.2.3.spl"
    )
    older_member = (
        "SplunkEnterpriseSecuritySuite/install/splunkcloud/splunk_app_es/"
        "Splunk_TA_ForIndexers-1.0.0.spl"
    )
    make_fake_es_package(
        package,
        payload=b"v123",
        member_name=primary_member,
        extra_members=[(older_member, b"v100")],
    )

    result = run_bash(str(TA_GENERATOR), "--package", str(package), "--output-dir", str(output_dir))

    assert result.returncode == 0, result.stdout
    generated = Path(result.stdout.strip().splitlines()[-1])
    assert generated.name == "Splunk_TA_ForIndexers-1.2.3.spl"
    assert generated.read_bytes() == b"v123"


def test_generate_ta_for_indexers_extracts_nested_member(tmp_path: Path) -> None:
    package = tmp_path / "splunk-enterprise-security_fake.spl"
    output_dir = tmp_path / "out"
    payload = b"ta-for-indexers-package"
    make_fake_es_package(package, payload)

    result = run_bash(str(TA_GENERATOR), "--package", str(package), "--output-dir", str(output_dir))

    assert result.returncode == 0, result.stdout
    generated = Path(result.stdout.strip().splitlines()[-1])
    assert generated == output_dir / "Splunk_TA_ForIndexers-1.2.3.spl"
    assert generated.read_bytes() == payload
    assert stat.S_IMODE(generated.stat().st_mode) == 0o644


def test_generate_ta_for_indexers_refuses_overwrite_without_force(tmp_path: Path) -> None:
    package = tmp_path / "splunk-enterprise-security_fake.spl"
    output_dir = tmp_path / "out"
    make_fake_es_package(package)

    first = run_bash(str(TA_GENERATOR), "--package", str(package), "--output-dir", str(output_dir))
    second = run_bash(str(TA_GENERATOR), "--package", str(package), "--output-dir", str(output_dir))
    forced = run_bash(str(TA_GENERATOR), "--package", str(package), "--output-dir", str(output_dir), "--force")

    assert first.returncode == 0, first.stdout
    assert second.returncode == 1
    assert "already exists" in second.stdout
    assert "Pass --force" in second.stdout
    assert forced.returncode == 0, forced.stdout


def test_generate_ta_for_indexers_reports_missing_embedded_package(tmp_path: Path) -> None:
    package = tmp_path / "splunk-enterprise-security_missing_ta.spl"
    unrelated = tmp_path / "README.txt"
    unrelated.write_text("not the TA", encoding="utf-8")
    try:
        with tarfile.open(package, "w:gz") as tf:
            tf.add(unrelated, arcname="SplunkEnterpriseSecuritySuite/README.txt")
    finally:
        unrelated.unlink(missing_ok=True)

    result = run_bash(str(TA_GENERATOR), "--package", str(package), "--output-dir", str(tmp_path / "out"))

    assert result.returncode == 1
    assert "Splunk_TA_ForIndexers was not found" in result.stdout
