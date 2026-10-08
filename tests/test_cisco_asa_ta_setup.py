"""Focused regressions for the shipped Cisco ASA 6.1.2 dashboard gate."""

from pathlib import Path
import json
import re
import subprocess
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "skills/cisco-asa-ta-setup/scripts/validate.sh"
REFERENCE = REPO_ROOT / "skills/cisco-asa-ta-setup/reference.md"
SKILL = REPO_ROOT / "skills/cisco-asa-ta-setup/SKILL.md"


def _embedded_dashboard_parser() -> str:
    source = VALIDATOR.read_text(encoding="utf-8")
    match = re.search(
        r'elif ! python3 - "\$\{dashboard_tmp\}" "\$\{query_tmp\}" "\$\{INDEX\}" <<\'PY\'\n(.*?)\nPY',
        source,
        re.DOTALL,
    )
    assert match
    return match.group(1)


def _embedded_app_visibility_parser() -> str:
    source = VALIDATOR.read_text(encoding="utf-8")
    match = re.search(r'if ! python3 - "\$\{app_tmp\}" <<\'PY\'\n(.*?)\nPY', source, re.DOTALL)
    assert match
    return match.group(1)


def _run_dashboard_parser(payload: dict, index: str = "asa_validation") -> tuple[int, str]:
    parser = _embedded_dashboard_parser()
    with tempfile.TemporaryDirectory() as tmp:
        body = Path(tmp) / "body.json"
        queries = Path(tmp) / "queries.txt"
        body.write_text(json.dumps(payload), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-", str(body), str(queries), index],
            input=parser,
            text=True,
            capture_output=True,
        )
        return result.returncode, queries.read_text(encoding="utf-8") if queries.exists() else ""


def test_completion_reads_exact_shipped_asa_dashboard_view() -> None:
    source = VALIDATOR.read_text(encoding="utf-8")
    assert "/servicesNS/nobody/Splunk_TA_cisco-asa/data/ui/views/cisco_asa_dashboard" in source
    assert "entries[0].get(\"name\") != \"cisco_asa_dashboard\"" in source
    assert 'acl.get("app")' in source
    assert 'acl.get("app") != "Splunk_TA_cisco-asa"' in source


def test_realistic_shipped_xml_tokens_are_resolved_before_execution() -> None:
    """Mirror the shipped 6.1.2 view shape without committing the archive."""
    fixture = """<dashboard version=\"1.1\">
      <fieldset><input token=\"index\"><default>asa_validation</default></input>
        <input token=\"no_of_message_id\"><default>10</default></input></fieldset>
      <row><panel><table><search><query>
        | tstats count where index=* sourcetype=\"cisco:asa\" by host
        | head $no_of_message_id$
      </query></search></table></panel></row>
    </dashboard>"""
    payload = {
        "entry": [{
            "name": "cisco_asa_dashboard",
            "acl": {"app": "Splunk_TA_cisco-asa"},
            "content": {"disabled": False, "isDashboard": True, "isVisible": True, "eai:data": fixture},
        }],
    }
    code, queries = _run_dashboard_parser(payload)
    assert code == 0
    assert 'index="asa_validation"' in queries
    assert "$no_of_message_id$" not in queries
    assert "optional\t| pivot" not in queries


def test_dashboard_parser_executes_realistic_version_primary_and_optional_queries() -> None:
    xml = """<form><fieldset><input token=\"log_time\"><default><earliest>-4h@m</earliest><latest>now</latest></default></input></fieldset>
      <panel><search><query>| rest services/apps/local/Splunk_TA_cisco-asa splunk_server=local| fields version</query></search></panel>
      <panel><search><query>index IN $index$ | timechart count(message_id) as \"Event count\"</query></search></panel>
      <panel><search><query>| pivot Network_Sessions All_Sessions count(All_Sessions) AS \"Count\" FILTER sourcetype in (\"cisco:asa\")</query></search></panel></form>"""
    payload = {"entry": [{"name": "cisco_asa_dashboard", "acl": {"app": "Splunk_TA_cisco-asa"}, "content": {"eai:data": xml}}]}
    code, queries = _run_dashboard_parser(payload, "asa_validation_20261008")
    assert code == 0
    assert "version\t| rest services/apps/local/Splunk_TA_cisco-asa" in queries
    assert 'primary\tindex IN ("asa_validation_20261008")' in queries
    assert "optional\t| pivot Network_Sessions" in queries


def test_dashboard_parser_rejects_unknown_tokens_pivots_and_foreign_acl() -> None:
    base = "<form><panel><search><query>index IN $unknown$ | stats count</query></search></panel></form>"
    for acl, xml in [
        ({"app": "other-app"}, base.replace("$unknown$", "$index$")),
        ({"app": "Splunk_TA_cisco-asa"}, base),
        ({"app": "Splunk_TA_cisco-asa"}, base.replace("$unknown$", "$index$").replace("stats count", "| pivot Unknown Dataset count(x)")),
    ]:
        payload = {"entry": [{"name": "cisco_asa_dashboard", "acl": acl, "content": {"eai:data": xml}}]}
        code, _ = _run_dashboard_parser(payload)
        assert code != 0


def test_app_visibility_parser_rejects_hidden_or_missing_app() -> None:
    parser = _embedded_app_visibility_parser()
    with tempfile.TemporaryDirectory() as tmp:
        body = Path(tmp) / "app.json"
        for payload in ({"entry": [{"content": {"is_visible": False}}]}, {"entry": []}):
            body.write_text(json.dumps(payload), encoding="utf-8")
            result = subprocess.run([sys.executable, "-", str(body)], input=parser, text=True, capture_output=True)
            assert result.returncode != 0


def test_primary_metric_parser_rejects_zero_filled_timechart_and_accepts_positive_total() -> None:
    source = VALIDATOR.read_text(encoding="utf-8")
    parser = source.split("| python3 -c '", 1)[1].split("' \"${dashboard_field}\"", 1)[0]
    for field, payload, expected in [
        ("data", {"results": [{"Event count": "0"}, {"Event count": "0"}]}, "0"),
        ("data", {"results": [{"Event count": "0"}, {"Event count": "4"}]}, "4"),
        ("data", {"results": [{"Total": "0"}]}, "0"),
        ("data", {"results": [{"Total": "4"}]}, "4"),
        ("data", {"results": [{"count": "4"}]}, "4"),
        ("version", {"results": [{"version": "6.1.2"}]}, "6.1.2"),
        ("rows", {"results": []}, "0"),
        ("data", {"messages": [{"type": "ERROR", "text": "fixture failure"}], "results": []}, "ERR:search response error"),
    ]:
        result = subprocess.run(
            [sys.executable, "-c", parser, field], input=json.dumps(payload),
            text=True, capture_output=True, check=True,
        )
        assert result.stdout.strip() == expected


def test_completion_rejects_missing_disabled_or_hidden_dashboard() -> None:
    source = VALIDATOR.read_text(encoding="utf-8")
    assert "view_http_code" in source
    assert 'content.get("disabled")' in source
    assert 'content["isDashboard"]' in source
    assert 'content["isVisible"]' in source
    assert '"dashboard hidden"' in source


def test_completion_binds_dashboard_queries_to_index_and_requires_data() -> None:
    source = VALIDATOR.read_text(encoding="utf-8")
    assert 'replace("$index$", f\'"{index_name}"\')' in source
    assert 'replace("$INDEX$", f\'"{index_name}"\')' in source
    assert 'defaults.get(match.group(1), match.group(0))' in source
    assert "dashboard query does not resolve a supported context" in source
    assert "asa_dashboard_oneshot" in source
    assert 'field == "data"' in source
    assert '"Event count", "Total"' in source
    assert '"${dashboard_query_kind}" == "metadata"' in source
    assert "dashboard query ${dashboard_query_number} returned no data" in source
    assert 'kind = "optional"' in source
    assert 'kind = "version"' in source
    assert 'stats values(version) as version' in source
    assert 'dashboard version query did not match installed app' in source
    assert 'if field == "version"' in source
    assert '/servicesNS/nobody/Splunk_TA_cisco-asa/search/jobs' in source
    assert 'dashboard_search="search ${dashboard_search}"' in source
    assert 'unsupported pivot' in source
    assert 'unsafe SPL characters' in source


def test_completion_rejects_unresolved_tokens_foreign_acl_and_hidden_app() -> None:
    source = VALIDATOR.read_text(encoding="utf-8")
    assert 're.search(r"\\$[A-Za-z_][A-Za-z0-9_.]*\\$", normalized)' in source
    assert 'acl.get("app") != "Splunk_TA_cisco-asa"' in source
    assert "services/apps/local/Splunk_TA_cisco-asa" in source
    assert "is_visible" in source


def test_primary_panel_data_uses_metric_fields_not_result_row_count() -> None:
    source = VALIDATOR.read_text(encoding="utf-8")
    # A timechart can return rows whose Event count is zero.  The validator
    # must sum the dashboard's numeric fields instead of counting those rows.
    assert 'for name in ("count", "Event count", "Total")' in source
    assert '"${dashboard_query_kind}" == "primary"' in source
    assert "coalesce(count,1)" not in source


def test_asa_docs_record_shipped_dashboard_contract() -> None:
    reference = REFERENCE.read_text(encoding="utf-8")
    skill = SKILL.read_text(encoding="utf-8")
    assert "cisco_asa_dashboard" in reference
    assert "enabled, visible" in reference
    assert "cisco_asa_dashboard" in skill
    assert "generic no-dashboard claim" in skill
