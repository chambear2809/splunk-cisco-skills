"""Evidence gates must never turn compatibility or missing access into a live pass."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location("validation_ledger", ROOT / "skills/shared/scripts/generate_enterprise_10_6_validation_ledger.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_complete_catalog_and_separate_results():
    result = module().build()
    assert result["skill_count"] == 169
    assert sum(result["compatibility_counts"].values()) == 169
    assert sum(result["functional_counts"].values()) == 169
    for row in result["workflows"]:
        assert row["required_evidence"]
        assert row["cleanup"]
        if row["enterprise_compatibility"] == "supported" and row["observation"] is None:
            assert row["functional_status"] == "pending"


@pytest.mark.parametrize("observation", [
    {"status": "pass", "notes": "installed only"},
    {"status": "blocked", "notes": "no access"},
    {"status": "pass", "notes": "invalid reference", "last_verified": "2026-10-07", "evidence": ["../secrets"]},
])
def test_incomplete_or_unsafe_evidence_rejected(tmp_path, observation):
    value = module()
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps({"schema_version": 1, "enterprise_version": "10.6.0.5", "assessment_date": "2026-10-07", "workflows": {"splunk-app-install": observation}}))
    value.EVIDENCE = path
    with pytest.raises(ValueError):
        value.build()


def test_check_rejects_tampered_generated_ledger(tmp_path, monkeypatch):
    value = module()
    json_output = tmp_path / "ledger.json"
    markdown_output = tmp_path / "ledger.md"
    payload = value.build()
    json_output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    markdown_output.write_text(value.markdown(payload), encoding="utf-8")
    value.JSON_OUTPUT = json_output
    value.MD_OUTPUT = markdown_output
    monkeypatch.setattr(sys, "argv", ["generate_enterprise_10_6_validation_ledger.py", "--check"])
    assert value.main() == 0

    markdown_output.write_text(markdown_output.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
    assert value.main() == 1
