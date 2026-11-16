"""Exercise SCAN completion without credentials, network calls, or Splunk."""

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "skills/cisco-scan-setup/scripts/validate.sh"
STUB = r"""
log() { echo "$*"; }
warn_if_current_skill_role_unsupported() { :; }
load_splunk_credentials() { SPLUNK_URI=https://example.invalid; }
get_session_key() { echo mock; }
rest_check_app() { return 0; }
rest_get_app_version() { echo 1.0.50; }
rest_check_saved_search() { return 0; }
rest_get_saved_search_value() { echo 1; }
splunk_curl() {
    case "$*" in
        *apps/local*) printf '{"entry":[{"content":{"visible":%s}}]}\n' "${APP_VISIBLE:-true}" ;;
        *conf-products*) echo '{"entry":[{},{}]}' ;;
        *data/ui/views*)
            if [ "${SCAN_MISSING_VIEW:-0}" = 1 ]; then
                echo '{"entry":[]}'
            else
                echo '{"entry":[{"name":"ecosystem_intelligence"},{"name":"cisco_glass_pane"},{"name":"products"},{"name":"user_guide"}]}'
            fi ;;
        *saved/searches*) echo '{"entry":[{"name":"SCAN test"}]}' ;;
        *) echo 200 ;;
    esac
}
rest_oneshot_search() {
    case "$*" in
        *catalog_rows*) echo "${SCAN_LOOKUP_ROWS:-12}" ;;
        *status*) echo 'Dry Run' ;;
        *) echo 1 ;;
    esac
}
"""


def run_validator(tmp_path, *args, **overrides):
    helper = tmp_path / "helpers.sh"
    helper.write_text(STUB)
    script = tmp_path / "validate.sh"
    source = VALIDATOR.read_text().replace(
        'source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"',
        'source "${SCRIPT_DIR}/helpers.sh"',
    )
    # Small mock inventories still meet the normal package-count thresholds.
    source = source.replace("MIN_PRODUCT_COUNT=90", "MIN_PRODUCT_COUNT=2")
    source = source.replace("MIN_SAVED_SEARCH_COUNT=40", "MIN_SAVED_SEARCH_COUNT=1")
    script.write_text(source)
    return subprocess.run(
        ["bash", str(script), *args],
        env={**os.environ, **overrides},
        text=True,
        capture_output=True,
        check=False,
    )


def test_scan_completion_requires_all_shipped_views(tmp_path):
    result = run_validator(tmp_path, "--completion", SCAN_MISSING_VIEW="1")
    assert result.returncode == 1
    assert "FAIL: Shipped view is missing" in result.stdout


def test_hidden_scan_app_cannot_satisfy_completion(tmp_path):
    result = run_validator(tmp_path, "--completion", APP_VISIBLE="false")
    assert result.returncode == 1
    assert "SCAN is hidden" in result.stdout


def test_scan_completion_requires_dashboard_results(tmp_path):
    result = run_validator(tmp_path, "--completion", SCAN_LOOKUP_ROWS="0")
    assert result.returncode == 1
    assert "Dashboard source lookup returns no rows" in result.stdout


def test_scan_diagnostic_mode_preserves_warnings(tmp_path):
    result = run_validator(tmp_path, SCAN_LOOKUP_ROWS="0")
    assert result.returncode == 0
    assert "OK with warnings" in result.stdout


def test_scan_completion_succeeds_with_catalog_and_views(tmp_path):
    result = run_validator(tmp_path, "--completion")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL CHECKS PASSED" in result.stdout
