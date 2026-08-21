"""Focused regressions for Cisco Enterprise Networking setup and validation."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import parse_qs

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/cisco-enterprise-networking-setup/scripts/setup.sh"
VALIDATE = REPO_ROOT / "skills/cisco-enterprise-networking-setup/scripts/validate.sh"
SOURCETYPE_DEFINITION = (
    'sourcetype IN ("cisco:ise*", "cisco:sdwan*", "cisco:dnac*", '
    '"stream:netflow", "cisco:cybervision:*", "meraki:*", "cisco:ios", '
    '"cisco:thousandeyes:metric", "cisco:sgacl:logs", '
    '"cisco:catalyst:center:*", "cisco:ise:analytics*", "tenable:sc*")'
)


FAKE_CURL = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


args = sys.argv[1:]
body = ""
method = "GET"
output_target = None
url = ""
write_code = False

i = 0
while i < len(args):
    arg = args[i]
    if arg == "-d" and i + 1 < len(args):
        body = sys.stdin.read() if args[i + 1] == "@-" else args[i + 1]
        method = "POST"
        i += 2
        continue
    if arg == "-o" and i + 1 < len(args):
        output_target = args[i + 1]
        i += 2
        continue
    if "%{http_code}" in arg:
        write_code = True
    if arg.startswith(("http://", "https://")):
        url = arg
    i += 1

with Path(os.environ["MOCK_CURL_LOG"]).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"url": url, "method": method, "body": body}) + "\n")


def respond(payload="", code=200):
    if output_target == "/dev/null":
        if write_code:
            sys.stdout.write(str(code))
        raise SystemExit(0)
    if payload:
        sys.stdout.write(payload)
    if write_code:
        sys.stdout.write(f"\n{code}")
    raise SystemExit(0)


decoded_path = unquote(urlparse(url).path)

if decoded_path.endswith("/services/auth/login"):
    respond("<response><sessionKey>test-session</sessionKey></response>")

if "/services/apps/local/" in decoded_path:
    app = decoded_path.rsplit("/", 1)[-1]
    if output_target == "/dev/null":
        missing = os.environ.get("MOCK_MISSING_TA") == "1" and app == "TA_cisco_catalyst"
        respond(code=404 if missing else 200)
    version = "3.2.20" if app == "cisco-catalyst-app" else "3.2.44"
    respond(json.dumps({"entry": [{"content": {"version": version}}]}))

if method == "POST" and "/configs/conf-" in decoded_path:
    respond("{}", 200)

if decoded_path.endswith(
    "/cisco-catalyst-app/configs/conf-macros/cisco_catalyst_app_index"
):
    respond(json.dumps({"entry": [{"content": {"definition": os.environ["MOCK_INDEX_DEF"]}}]}))

if decoded_path.endswith(
    "/cisco-catalyst-app/configs/conf-macros/cisco_catalyst_sdwan_index"
):
    respond(json.dumps({"entry": [{"content": {"definition": os.environ["MOCK_SDWAN_DEF"]}}]}))

if decoded_path.endswith(
    "/cisco-catalyst-app/configs/conf-macros/cisco_catalyst_app_sourcetypes"
):
    respond(
        json.dumps(
            {"entry": [{"content": {"definition": os.environ["MOCK_SOURCETYPE_DEF"]}}]}
        )
    )

if decoded_path.endswith(
    "/TA_cisco_catalyst/configs/conf-eventtypes/cisco_sdwan_index"
):
    respond(json.dumps({"entry": [{"content": {"search": os.environ["MOCK_TA_SDWAN_DEF"]}}]}))

if decoded_path.endswith(
    "/cisco-catalyst-app/configs/conf-datamodels/Cisco_Catalyst_App"
):
    respond(json.dumps({"entry": [{"content": {"acceleration": "true"}}]}))

if decoded_path.endswith("/cisco-catalyst-app/data/ui/views"):
    respond(json.dumps({"entry": [{"name": "overview"}]}))

if "/cisco-catalyst-app/saved/searches/" in decoded_path:
    if output_target == "/dev/null":
        respond(code=200)
    respond(
        json.dumps(
            {"entry": [{"content": {"disabled": "0", "cron_schedule": "0 * * * *"}}]}
        )
    )

if decoded_path.endswith("/services/search/jobs") and method == "POST":
    search = parse_qs(body, keep_blank_values=True).get("search", [""])[-1]
    count = "7" if "| tstats count where index=" in search else "0"
    respond(json.dumps({"results": [{"count": count}]}))

print(f"unexpected mock REST request: {method} {url}", file=sys.stderr)
raise SystemExit(91)
'''


def _mock_env(
    tmp_path: Path,
    *,
    index_definition: str = 'index IN ("catalyst_prod", "sdwan-prod")',
    sdwan_definition: str = 'index IN ("sdwan-prod")',
    ta_sdwan_definition: str | None = None,
    missing_ta: bool = False,
) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(FAKE_CURL, encoding="utf-8")
    fake_curl.chmod(0o755)

    credentials = tmp_path / "credentials"
    credentials.write_text(
        'SPLUNK_SEARCH_API_URI="https://example.invalid:8089"\n'
        'SPLUNK_USER="user"\n'
        'SPLUNK_PASS="test-password"\n',
        encoding="utf-8",
    )

    curl_log = tmp_path / "curl.log"
    env = os.environ.copy()
    for key in (
        "SPLUNK_CLOUD_STACK",
        "SPLUNK_PROFILE",
        "SPLUNK_SEARCH_PROFILE",
        "SPLUNK_SEARCH_TARGET_ROLE",
        "SPLUNK_TARGET_ROLE",
    ):
        env.pop(key, None)
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "MOCK_CURL_LOG": str(curl_log),
            "MOCK_INDEX_DEF": index_definition,
            "MOCK_SDWAN_DEF": sdwan_definition,
            "MOCK_TA_SDWAN_DEF": ta_sdwan_definition or sdwan_definition,
            "MOCK_SOURCETYPE_DEF": SOURCETYPE_DEFINITION,
            "MOCK_MISSING_TA": "1" if missing_ta else "0",
            "SPLUNK_CREDENTIALS_FILE": str(credentials),
            "SPLUNK_PLATFORM": "enterprise",
            "SPLUNK_VERIFY_SSL": "true",
        }
    )
    return env, curl_log


def _run(script: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _calls(curl_log: Path) -> list[dict[str, str]]:
    return [json.loads(line) for line in curl_log.read_text(encoding="utf-8").splitlines()]


def _post_form(calls: list[dict[str, str]], path_suffix: str) -> dict[str, list[str]]:
    matches = [
        call
        for call in calls
        if call["method"] == "POST" and call["url"].split("?", 1)[0].endswith(path_suffix)
    ]
    assert len(matches) == 1, matches
    return parse_qs(matches[0]["body"], keep_blank_values=True)


def test_setup_writes_custom_scopes_to_app_macros_and_ta_eventtype(tmp_path: Path) -> None:
    env, curl_log = _mock_env(tmp_path)
    result = _run(
        SETUP,
        env,
        "--macros-only",
        "--custom-indexes",
        "catalyst_prod,sdwan-prod",
        "--app-version",
        "3.2.20",
        "--target-splunk-version",
        "10.5",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    calls = _calls(curl_log)
    expected_all = 'index IN ("catalyst_prod","sdwan-prod")'

    app_index = _post_form(
        calls,
        "/cisco-catalyst-app/configs/conf-macros/cisco_catalyst_app_index",
    )
    app_sdwan = _post_form(
        calls,
        "/cisco-catalyst-app/configs/conf-macros/cisco_catalyst_sdwan_index",
    )
    ta_sdwan = _post_form(
        calls,
        "/TA_cisco_catalyst/configs/conf-eventtypes/cisco_sdwan_index",
    )
    source_types = _post_form(
        calls,
        "/cisco-catalyst-app/configs/conf-macros/cisco_catalyst_app_sourcetypes",
    )

    assert app_index["definition"] == [expected_all]
    assert app_sdwan["definition"] == [expected_all]
    assert ta_sdwan["search"] == [expected_all]
    assert source_types["definition"] == [SOURCETYPE_DEFINITION]


def test_setup_refuses_to_mutate_when_required_ta_is_missing(tmp_path: Path) -> None:
    env, curl_log = _mock_env(tmp_path, missing_ta=True)
    result = _run(
        SETUP,
        env,
        "--macros-only",
        "--app-version",
        "3.2.20",
        "--target-splunk-version",
        "10.5",
    )

    assert result.returncode != 0
    assert "Cisco Catalyst Add-on (TA_cisco_catalyst) not found" in (
        result.stdout + result.stderr
    )
    assert not any("/configs/conf-" in call["url"] for call in _calls(curl_log))


def test_completion_validates_and_queries_configured_custom_indexes(tmp_path: Path) -> None:
    env, curl_log = _mock_env(
        tmp_path,
        index_definition='index IN ("catalyst_prod", sdwan-prod)',
        sdwan_definition="index IN ('sdwan-prod')",
        ta_sdwan_definition='index IN ("sdwan-prod")',
    )
    result = _run(VALIDATE, env, "--completion")

    assert result.returncode == 0, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "Configured dashboard index 'catalyst_prod' accepted" in output
    assert "Configured dashboard index 'sdwan-prod' accepted" in output
    assert "TA cisco_sdwan_index eventtype matches" in output

    searches = {
        parse_qs(call["body"], keep_blank_values=True)["search"][-1]
        for call in _calls(curl_log)
        if call["method"] == "POST"
        and call["url"].split("?", 1)[0].endswith("/services/search/jobs")
    }
    assert searches == {
        '| tstats count where index="catalyst_prod"',
        '| tstats count where index="sdwan-prod"',
    }


@pytest.mark.parametrize(
    ("ta_definition", "expected_error"),
    (
        ("()", "must replace the package's empty () placeholder"),
        ('index IN ("sdwan-b")', "does not match the app"),
    ),
)
def test_completion_rejects_invalid_ta_sdwan_eventtype(
    tmp_path: Path,
    ta_definition: str,
    expected_error: str,
) -> None:
    env, _curl_log = _mock_env(
        tmp_path,
        index_definition='index IN ("core", "sdwan-a", "sdwan-b")',
        sdwan_definition='index IN ("sdwan-a")',
        ta_sdwan_definition=ta_definition,
    )
    result = _run(VALIDATE, env, "--completion")

    assert result.returncode != 0
    assert expected_error in result.stdout + result.stderr
