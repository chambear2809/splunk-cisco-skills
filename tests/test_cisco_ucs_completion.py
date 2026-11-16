"""Check UCS view and health readiness without a Splunk deployment."""

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
STUB = r"""
log() { echo "$*"; }
warn_if_current_skill_role_unsupported() { :; }
load_splunk_credentials() { SPLUNK_URI=https://example.invalid; }
get_session_key() { echo mock; }
rest_check_app() { return 0; }
rest_get_app_version() { echo 5.0.0; }
platform_check_index() { return 0; }
rest_get_conf_value() { echo content; }
rest_list_ta_stanzas() { echo '{"entry":[{}]}'; }
rest_count_conf_stanzas() { echo 1; }
rest_count_live_inputs() { echo 1; }
splunk_curl() {
    case "$*" in
        *apps/local*) printf '{"entry":[{"content":{"visible":%s}}]}\n' "${APP_VISIBLE:-true}" ;;
        *output_mode=json*) echo "$VIEW_RESPONSE" ;;
        *) echo '<feed/>' ;;
    esac
}
rest_oneshot_search() {
    case "$*" in
        *health_events*) echo "${HEALTH_COUNT:-1}" ;;
        *) echo "${INGEST_COUNT:-1}" ;;
    esac
}
"""


def run_validator(tmp_path, views, health="1", visible="true", ingest="1"):
    (tmp_path / "helpers.sh").write_text(STUB)
    source = (ROOT / "skills/cisco-ucs-ta-setup/scripts/validate.sh").read_text()
    source = source.replace(
        'source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"',
        'source "${SCRIPT_DIR}/helpers.sh"',
    )
    script = tmp_path / "validate.sh"
    script.write_text(source)
    return subprocess.run(
        ["bash", str(script), "--completion"],
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "VIEW_RESPONSE": views,
            "HEALTH_COUNT": health,
            "APP_VISIBLE": visible,
            "INGEST_COUNT": ingest,
        },
        check=False,
    )


def test_unrelated_views_cannot_satisfy_ucs_completion(tmp_path):
    result = run_validator(
        tmp_path, '{"entry":[{"name":"a"},{"name":"b"},{"name":"c"}]}'
    )
    assert result.returncode == 1
    assert "UCS shipped view is missing or inaccessible: dashboard" in result.stdout


def test_hidden_ucs_app_cannot_satisfy_completion(tmp_path):
    result = run_validator(tmp_path, '{"entry":[]}', visible="false")
    assert result.returncode == 1
    assert "UCS app is hidden" in result.stdout


def test_missing_optional_monitoring_logs_remain_diagnostic(tmp_path):
    result = run_validator(
        tmp_path,
        '{"entry":[{"name":"dashboard"},{"name":"inputs"},{"name":"configuration"}]}',
        "0",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WARN:" in result.stdout
    assert "Monitoring Dashboard log source has no readable events" in result.stdout


def test_missing_ucs_data_blocks_completion_even_with_healthy_logs(tmp_path):
    result = run_validator(
        tmp_path,
        '{"entry":[{"name":"dashboard"},{"name":"inputs"},{"name":"configuration"}]}',
        ingest="0",
    )
    assert result.returncode == 1
    assert "No cisco:ucs events" in result.stdout


def test_ucs_completion_requires_views_health_and_ingest(tmp_path):
    result = run_validator(
        tmp_path,
        '{"entry":[{"name":"dashboard"},{"name":"inputs"},{"name":"configuration"}]}',
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "cisco:ucs event(s)" in result.stdout
