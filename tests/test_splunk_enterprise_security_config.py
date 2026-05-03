"""Regression tests for the Splunk Enterprise Security config engine."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = REPO_ROOT / "skills/splunk-enterprise-security-config/scripts/es_config_engine.py"
EXAMPLE_SPEC = REPO_ROOT / "skills/splunk-enterprise-security-config/templates/es-config.example.yaml"
ES_PACKAGE = REPO_ROOT / "splunk-ta/splunk-enterprise-security_851.spl"


def load_engine():
    spec = importlib.util.spec_from_file_location("es_config_engine", ENGINE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


engine = load_engine()


def actions_by_operation(plan: dict[str, object], operation: str) -> list[dict[str, object]]:
    return [action for action in plan["actions"] if action["operation"] == operation]  # type: ignore[index]


def test_yaml_spec_parses_and_normalizes_example() -> None:
    spec = engine.read_spec(str(EXAMPLE_SPEC))
    plan = engine.PlanBuilder(spec).build()

    assert plan["summary"]["actions"] > 40
    assert set(engine.TOP_LEVEL_SECTIONS).issubset(plan["normalized_spec"])
    assert any(action["target"] == "ea_discovery" for action in plan["actions"])
    assert any(action["section"] == "ta_for_indexers" for action in plan["actions"])
    assert any(action["section"] == "content_governance" for action in plan["actions"])


def test_json_spec_preview_output_round_trips(tmp_path: Path) -> None:
    spec_path = tmp_path / "es-config.json"
    spec_path.write_text(
        json.dumps(
            {
                "baseline": {"enabled": True, "lookup_order": True},
                "indexes": {"groups": ["exposure"]},
                "detections": {"custom": [{"name": "Custom Test", "search": "| makeresults"}]},
            }
        ),
        encoding="utf-8",
    )

    parsed = engine.read_spec(str(spec_path))
    preview = engine.Runner(REPO_ROOT, parsed).preview()

    assert preview["mode"] == "preview"
    assert any(action["target"] == "ea_discovery" for action in preview["actions"])
    detection = next(action for action in preview["actions"] if action["target"] == "Custom Test")
    assert detection["payload"]["disabled"] == "1"


@pytest.mark.parametrize(
    "spec_text",
    (
        "connection:\n  password: no\n",
        "integrations:\n  soar:\n    token: no\n",
        "threat_intel:\n  feeds:\n    - name: bad\n      api_key: no\n",
    ),
)
def test_specs_reject_inline_secret_material(tmp_path: Path, spec_text: str) -> None:
    spec_path = tmp_path / "bad.yaml"
    spec_path.write_text(spec_text, encoding="utf-8")

    with pytest.raises(engine.EsConfigError, match="secret-file|inline passwords|Do not put"):
        engine.read_spec(str(spec_path))


def test_programmatic_runner_and_planbuilder_also_reject_inline_secrets() -> None:
    bad_spec = {"integrations": {"soar": {"token": "no"}}}

    # Programmatic callers bypass read_spec(). normalize_spec() must still block inline
    # secrets so Runner/PlanBuilder cannot be used as an escape hatch.
    with pytest.raises(engine.EsConfigError, match="secret-file|inline passwords|Do not put"):
        engine.Runner(REPO_ROOT, bad_spec)
    with pytest.raises(engine.EsConfigError, match="secret-file|inline passwords|Do not put"):
        engine.PlanBuilder(bad_spec).build()


def test_summarize_saved_search_requires_correlation_flag_to_mark_correlation() -> None:
    scheduled_only = engine.summarize_saved_search({"name": "nightly_export", "is_scheduled": 1})
    correlation = engine.summarize_saved_search(
        {"name": "auth_brute_force", "action.correlationsearch.enabled": 1}
    )

    assert scheduled_only["is_correlation_search"] is False
    assert correlation["is_correlation_search"] is True


def test_example_yaml_covers_every_top_level_section() -> None:
    spec = engine.read_spec(str(EXAMPLE_SPEC))
    plan = engine.PlanBuilder(spec).build()
    sections_used = {action["section"] for action in plan["actions"]}

    # Every declared top-level section should have at least one action emitted by
    # the example spec; otherwise the documentation drifts from the engine.
    expected = set(engine.TOP_LEVEL_SECTIONS)
    missing = expected - sections_used
    assert not missing, f"Example YAML missing actions for sections: {sorted(missing)}"
    # And the example should not advertise sections the engine does not declare.
    extra = sections_used - expected
    assert not extra, f"Example YAML uses unknown sections: {sorted(extra)}"


def test_urgency_matrix_writes_to_urgency_conf() -> None:
    plan = engine.PlanBuilder(
        {
            "urgency": {
                "matrix": [
                    {"stanza": "high|high", "urgency": "critical"},
                    {"stanza": "low|low", "urgency": "informational"},
                ]
            }
        }
    ).build()

    actions = [a for a in plan["actions"] if a["section"] == "urgency"]
    assert len(actions) == 2
    assert all(a["operation"] == "set_conf" for a in actions)
    assert all(a["app"] == engine.THREAT_APP for a in actions)
    assert all("configs/conf-urgency" in a["endpoint"] for a in actions)
    assert {a["payload"]["urgency"] for a in actions} == {"critical", "informational"}


def test_adaptive_response_writes_to_alert_actions_conf() -> None:
    plan = engine.PlanBuilder(
        {
            "adaptive_response": {
                "app": "SplunkEnterpriseSecuritySuite",
                "notable": {"default_owner": "unassigned", "default_status": "1"},
                "risk": {"param._risk_score": "25"},
            }
        }
    ).build()

    actions = {a["target"]: a for a in plan["actions"] if a["section"] == "adaptive_response"}
    assert set(actions) == {"alert_actions://notable", "alert_actions://risk"}
    for target, action in actions.items():
        assert action["operation"] == "set_conf"
        assert "configs/conf-alert_actions" in action["endpoint"]
        stanza = target.split("://", 1)[1]
        assert stanza in action["endpoint"]


def test_notable_suppressions_require_search() -> None:
    plan = engine.PlanBuilder(
        {
            "notable_suppressions": [
                {"name": "good", "search": "index=notable tag=scanner", "enabled": False},
                {"name": "bad_no_search"},
            ]
        }
    ).build()

    actions = [a for a in plan["actions"] if a["section"] == "notable_suppressions"]
    diagnostics = [d for d in plan["diagnostics"] if d["section"] == "notable_suppressions"]
    assert [a["target"] for a in actions] == ["notable_suppression://good"]
    assert actions[0]["payload"]["search"] == "index=notable tag=scanner"
    assert actions[0]["payload"]["disabled"] == "1"
    assert diagnostics and diagnostics[0]["target"] == "bad_no_search"


def test_log_review_statuses_dispositions_and_settings() -> None:
    plan = engine.PlanBuilder(
        {
            "log_review": {
                "statuses": [{"name": "5", "label": "Resolved", "end": True}],
                "dispositions": [{"name": "1", "label": "True Positive"}],
                "settings": {"default_owner": "unassigned"},
            }
        }
    ).build()

    # ES 8.x stores status definitions in reviewstatuses.conf under
    # SA-ThreatIntelligence, so log_review.statuses / log_review.dispositions
    # are routed there rather than to log_review.conf under the ES top-level app.
    log_review_actions = [a for a in plan["actions"] if a["section"] == "log_review"]
    status_action = next(a for a in log_review_actions if a["target"] == "5")
    disposition_action = next(a for a in log_review_actions if a["target"] == "1")
    settings_action = next(a for a in log_review_actions if a["target"] == "incident_review")

    for action in (status_action, disposition_action, settings_action):
        assert action["app"] == engine.THREAT_APP
    assert "configs/conf-reviewstatuses/5" in status_action["endpoint"]
    assert status_action["payload"]["status_type"] == "notable"
    assert status_action["payload"]["end"] == "1"
    assert "configs/conf-reviewstatuses/1" in disposition_action["endpoint"]
    assert disposition_action["payload"]["status_type"] == "investigation"
    assert "configs/conf-log_review/incident_review" in settings_action["endpoint"]


def test_review_statuses_top_level_section_honors_status_type_mapping() -> None:
    plan = engine.PlanBuilder(
        {
            "review_statuses": {
                "notable": [
                    {"id": "6", "label": "On Hold", "end": False, "rank": 55},
                ],
                "investigation": [
                    {"id": "10", "label": "Legal Hold", "end": True, "editable": False},
                ],
            }
        }
    ).build()

    actions = [a for a in plan["actions"] if a["section"] == "review_statuses"]
    by_target = {a["target"]: a for a in actions}
    assert by_target["6"]["payload"]["status_type"] == "notable"
    assert by_target["6"]["payload"]["rank"] == "55"
    assert by_target["10"]["payload"]["status_type"] == "investigation"
    assert by_target["10"]["payload"]["editable"] == "0"
    for action in actions:
        assert action["app"] == engine.THREAT_APP
        assert "configs/conf-reviewstatuses" in action["endpoint"]


def test_workflow_actions_write_through_post_endpoint() -> None:
    plan = engine.PlanBuilder(
        {
            "workflow_actions": [
                {
                    "name": "open_servicenow_incident",
                    "app": "SA-ThreatIntelligence",
                    "display_location": "event_menu",
                    "fields": ["src", "dest"],
                    "label": "Open ServiceNow incident",
                    "link_uri": "https://example/incident?src=$src$",
                    "link_method": "get",
                    "type": "link",
                },
            ]
        }
    ).build()

    action = next(a for a in plan["actions"] if a["section"] == "workflow_actions")
    assert action["operation"] == "post_endpoint"
    assert action["endpoint"].endswith("/data/ui/workflow-actions/open_servicenow_incident")
    assert action["payload"]["link.uri"].startswith("https://example/")
    assert action["payload"]["fields"] == "src,dest"


def test_kv_collections_emit_field_and_acceleration_payload() -> None:
    plan = engine.PlanBuilder(
        {
            "kv_collections": [
                {
                    "name": "custom_asset_enrichment",
                    "fields": {"ip": "string", "owner": "string"},
                    "accelerated_fields": {"by_ip": {"ip": 1}},
                    "replicate": True,
                }
            ]
        }
    ).build()

    action = next(a for a in plan["actions"] if a["section"] == "kv_collections")
    assert action["operation"] == "set_kv_collection"
    assert action["endpoint"].endswith("/storage/collections/config/custom_asset_enrichment")
    assert action["payload"]["field.ip"] == "string"
    assert action["payload"]["replicate"] == "1"
    # JSON-encoded accelerated index
    assert '"ip"' in action["payload"]["accelerated_fields.by_ip"]


def test_intelligence_management_writes_mission_control_stanza() -> None:
    plan = engine.PlanBuilder(
        {
            "intelligence_management": {
                "subscribed": True,
                "enclave_ids": ["a", "b"],
                "is_talos_query_enabled": False,
                "im_scs_url": "https://tim.example.invalid",
                "tenant_pairing_required": True,
            }
        }
    ).build()

    actions = [a for a in plan["actions"] if a["section"] == "intelligence_management"]
    main = next(a for a in actions if a["operation"] == "set_conf")
    handoff = next(a for a in actions if a["operation"] == "handoff")
    assert main["payload"]["enclave_ids"] == "a,b"
    # Splunk REST/.conf expects "1"/"0" for booleans; the engine now
    # serializes through splunk_bool() instead of the Python repr.
    assert main["payload"]["is_talos_query_enabled"] == "0"
    assert main["payload"]["subscribed"] == "1"
    assert main["app"] == engine.MISSION_CONTROL_APP
    assert handoff["apply_supported"] is False


def test_es_ai_and_dlx_settings_emit_per_stanza_writes() -> None:
    plan = engine.PlanBuilder(
        {
            "es_ai_settings": {
                "settings": {"ai_triage_enabled": True, "is_ai_assistant_active": True},
                "triage_agent_dispatch_settings": {"max_findings_per_run": 20},
            },
            "dlx_settings": {
                "scheduler": {"poll_interval": 30},
                "search": {"confidence_threshold": 50},
            },
        }
    ).build()

    ai_actions = {a["target"]: a for a in plan["actions"] if a["section"] == "es_ai_settings"}
    assert ai_actions["settings"]["payload"]["ai_triage_enabled"] == "1"
    assert ai_actions["triage_agent_dispatch_settings"]["payload"]["max_findings_per_run"] == "20"

    dlx_actions = {a["target"]: a for a in plan["actions"] if a["section"] == "dlx_settings"}
    assert dlx_actions["scheduler"]["payload"]["poll_interval"] == "30"
    assert dlx_actions["search"]["payload"]["confidence_threshold"] == "50"
    for action in dlx_actions.values():
        assert action["app"] == "dlx-app"


def test_findings_intermediate_settings_write_to_threat_intel_app() -> None:
    plan = engine.PlanBuilder(
        {"findings": {"intermediate_findings": {"use_current_time": True}}}
    ).build()

    action = next(a for a in plan["actions"] if a["section"] == "findings")
    assert action["target"] == "intermediate_findings"
    assert action["app"] == engine.THREAT_APP
    assert action["payload"]["use_current_time"] == "1"


def test_detection_acl_emits_set_acl_action() -> None:
    plan = engine.PlanBuilder(
        {
            "detections": {
                "custom": [
                    {
                        "name": "Custom Detection",
                        "search": "| makeresults",
                        "acl": {
                            "sharing": "global",
                            "owner": "nobody",
                            "read": "*",
                            "write": ["admin", "ess_admin"],
                        },
                    }
                ]
            }
        }
    ).build()

    acl_action = next(a for a in plan["actions"] if a["operation"] == "set_acl")
    assert acl_action["endpoint"].endswith("/saved/searches/Custom%20Detection/acl")
    assert "/servicesNS/nobody/" in acl_action["endpoint"]
    assert acl_action["payload"]["sharing"] == "global"
    assert acl_action["payload"]["perms.read"] == "*"
    assert acl_action["payload"]["perms.write"] == "admin,ess_admin"


def test_use_cases_governance_macros_eventtypes_tags_emit_writes() -> None:
    plan = engine.PlanBuilder(
        {
            "use_cases": [{"name": "access_protection", "category": "access"}],
            "governance": [{"name": "pci", "label": "PCI DSS"}],
            "macros": [{"name": "sec_indexes", "definition": "(index=notable OR index=risk)"}],
            "eventtypes": [{"name": "priv_logins", "search": "tag=authentication action=success"}],
            "tags": [{"field": "user_category", "value": "privileged", "tags": ["es_privileged"]}],
        }
    ).build()

    section_to_op = {a["section"]: a["operation"] for a in plan["actions"]}
    assert section_to_op["use_cases"] == "set_conf"
    assert section_to_op["governance"] == "set_conf"
    assert section_to_op["macros"] == "set_macro"
    assert section_to_op["eventtypes"] == "set_eventtype"
    assert section_to_op["tags"] == "set_tag"


def test_navigation_writes_data_ui_nav() -> None:
    plan = engine.PlanBuilder(
        {"navigation": {"app": "SplunkEnterpriseSecuritySuite", "xml": "<nav/>"}}
    ).build()

    action = next(a for a in plan["actions"] if a["section"] == "navigation")
    assert action["operation"] == "set_navigation"
    assert action["endpoint"].endswith("/data/ui/nav/default")
    assert action["payload"]["eai:data"] == "<nav/>"


def test_glass_table_handoff_when_xml_contains_secret_material() -> None:
    benign_plan = engine.PlanBuilder(
        {"glass_tables": [{"name": "ok_board", "xml": "<dashboard><label>OK</label></dashboard>"}]}
    ).build()
    suspicious_plan = engine.PlanBuilder(
        {
            "glass_tables": [
                {"name": "leaky_board", "xml": '<dashboard><search password="hunter2" /></dashboard>'}
            ]
        }
    ).build()

    ok_action = next(a for a in benign_plan["actions"] if a["section"] == "glass_tables")
    leak_action = next(a for a in suspicious_plan["actions"] if a["section"] == "glass_tables")

    assert ok_action["operation"] == "set_view"
    assert ok_action["apply_supported"] is True
    assert leak_action["operation"] == "handoff"
    assert leak_action["apply_supported"] is False


def test_content_library_install_and_subscription_plan() -> None:
    plan = engine.PlanBuilder(
        {
            "content_library": {
                "install": True,
                "app_ids": {"content_update": "3449"},
                "escu": {
                    "subscription": "enterprise",
                    "auto_update": True,
                    "enabled_stories": ["endpoint_security"],
                    "enabled_detections": ["ESCU - Detect New Local Admin Account"],
                },
                "content_packs": [{"name": "cloud_security", "enabled": True}],
            }
        }
    ).build()

    actions = [a for a in plan["actions"] if a["section"] == "content_library"]
    install_actions = [a for a in actions if a["operation"] == "install_app"]
    assert [a["target"] for a in install_actions] == [engine.CONTENT_UPDATE_APP]
    assert install_actions[0]["apply_supported"] is True
    assert install_actions[0]["payload"]["app_id"] == "3449"

    subscription = next(a for a in actions if a["target"] == "subscription")
    assert subscription["payload"]["subscription"] == "enterprise"
    assert subscription["payload"]["auto_update"] == "1"

    enablement_targets = {
        a["target"] for a in actions if a["operation"] == "set_saved_search"
    }
    assert "endpoint_security" in enablement_targets
    assert "ESCU - Detect New Local Admin Account" in enablement_targets

    pack = next(a for a in actions if a["target"] == "cloud_security")
    assert pack["payload"]["disabled"] == "0"


def test_content_library_cloud_install_stays_handoff() -> None:
    plan = engine.PlanBuilder(
        {
            "connection": {"platform": "cloud"},
            "content_library": {"install": True, "app_ids": {"SA-ContentLibrary": "9999"}},
        }
    ).build()

    install_actions = [a for a in plan["actions"] if a["operation"] == "install_app"]
    assert {a["target"] for a in install_actions} == {
        engine.CONTENT_UPDATE_APP,
        engine.CONTENT_LIBRARY_APP,
    }
    assert all(a["apply_supported"] is False for a in install_actions)


def test_correlation_metadata_written_alongside_saved_search() -> None:
    plan = engine.PlanBuilder(
        {
            "detections": {
                "custom": [
                    {
                        "name": "Custom Detection",
                        "search": "| makeresults",
                        "correlation_metadata": {
                            "rule_name": "Custom Detection",
                            "security_domain": "access",
                            "severity": "high",
                            "drilldown_name": "View $src$",
                            "drilldown_search": "search src=$src$",
                        },
                    }
                ]
            }
        }
    ).build()

    detection_actions = [a for a in plan["actions"] if a["section"] == "detections"]
    operations = {a["operation"] for a in detection_actions}
    assert "create_saved_search" in operations
    assert "set_correlation_metadata" in operations
    meta = next(a for a in detection_actions if a["operation"] == "set_correlation_metadata")
    assert meta["endpoint"].endswith("/admin/correlationsearches/Custom%20Detection")
    assert meta["payload"]["security_domain"] == "access"
    assert meta["payload"]["drilldown_name"] == "View $src$"


def test_post_endpoint_driven_apply_reaches_correct_rest_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def create_index(self, payload):  # pragma: no cover - not exercised here
            return "created"

        def set_global_conf(self, conf, stanza, payload):
            calls.append(("set_global_conf", f"{conf}/{stanza}", dict(payload)))
            return "updated"

        def set_conf(self, app, conf, stanza, payload):
            calls.append(("set_conf", f"{app}:{conf}/{stanza}", dict(payload)))
            return "updated"

        def set_saved_search(self, app, name, payload, create_missing=True):
            calls.append(
                (
                    "set_saved_search",
                    f"{app}:{name}:{create_missing}",
                    dict(payload),
                )
            )
            return "updated"

        def set_role(self, *_args, **_kwargs):  # pragma: no cover
            return "updated"

        def post_endpoint(self, path, payload):
            calls.append(("post_endpoint", path, dict(payload)))
            return "updated"

        def request(self, *_args, **_kwargs):  # pragma: no cover
            return {}

    monkeypatch.setattr(engine, "SplunkClient", FakeClient)
    runner = engine.Runner(
        REPO_ROOT,
        {
            "urgency": {"matrix": [{"stanza": "high|high", "urgency": "critical"}]},
            "eventtypes": [{"name": "et1", "search": "foo"}],
            "tags": [{"field": "user_category", "value": "privileged", "tags": ["es_privileged"]}],
            "navigation": {"xml": "<nav/>"},
            "glass_tables": [{"name": "board", "xml": "<dashboard/>"}],
        },
    )
    runner.apply()

    ops = [call[0] for call in calls]
    # The urgency/alert_actions/log_review stanzas go through set_conf.
    assert ops.count("set_conf") >= 1
    # Eventtype/tag/navigation/glass-table all land on post_endpoint.
    post_paths = [call[1] for call in calls if call[0] == "post_endpoint"]
    assert any("saved/eventtypes/et1" in p for p in post_paths)
    assert any("saved/fvtags/user_category%3Dprivileged" in p for p in post_paths)
    assert any("data/ui/nav/default" in p for p in post_paths)
    assert any("data/ui/views/board" in p for p in post_paths)


def test_looks_like_secret_detects_common_patterns() -> None:
    assert engine._looks_like_secret('password="hunter2"') is True
    assert engine._looks_like_secret("api_key=abcdef123456") is True
    assert (
        engine._looks_like_secret("-----BEGIN PRIVATE KEY-----\nMIIC...")
        is True
    )
    assert engine._looks_like_secret("<dashboard><label>OK</label></dashboard>") is False
    assert engine._looks_like_secret("") is False


def test_plan_covers_documented_sections_without_writes_for_handoffs() -> None:
    spec = {
        "baseline": {"enabled": True, "lookup_order": True, "managed_roles": ["ess_analyst"]},
        "indexes": {"groups": ["core"], "custom": [{"name": "custom_sec"}]},
        "roles": [{"name": "ess_analyst", "allowed_indexes": ["main", "risk"], "default_indexes": ["main"]}],
        "data_models": [
            {
                "name": "Authentication",
                "acceleration": True,
                "constraint": {"macro": "cim_Authentication_indexes", "indexes": ["auth"]},
            }
        ],
        "assets": [{"name": "assets", "lookup_definition": "assets_lookup", "lookup_file": "assets.csv"}],
        "identities": [{"name": "identities", "lookup_definition": "identities_lookup"}],
        "threat_intel": {"threatlists": [{"name": "feed", "url": "https://example.invalid/feed.csv"}]},
        "detections": {
            "inventory": True,
            "existing": [{"name": "Existing Detection", "enabled": False}],
            "custom": [{"name": "Custom Detection", "search": "| makeresults"}],
        },
        "risk": {"factors": [{"name": "vip", "score": 20}]},
        "mission_control": {"queues": [{"name": "tier1"}]},
        "integrations": {
            "soar": {"enabled": True, "tenant_pairing_required": True},
            "behavioral_analytics": {
                "local_conf": {
                    "app": "SplunkEnterpriseSecuritySuite",
                    "conf": "cloud_integrations",
                    "stanza": "behavioral_analytics",
                    "values": {"disabled": 1},
                }
            },
        },
        "ta_for_indexers": {"enabled": True},
        "content_governance": {"test_mode": False, "content_importer": {"disabled": 0}, "content_versioning": "inventory"},
        "validation": {"searches": [{"name": "risk_smoke", "search": "| tstats count where index=risk"}]},
    }

    plan = engine.PlanBuilder(spec).build()
    sections = {action["section"] for action in plan["actions"]}

    assert set(spec).issubset(sections)
    assert actions_by_operation(plan, "set_role")
    assert actions_by_operation(plan, "set_macro")
    assert actions_by_operation(plan, "set_lookup_definition")
    assert actions_by_operation(plan, "create_saved_search")
    assert actions_by_operation(plan, "set_saved_search")
    assert any(not action["apply_supported"] for action in plan["actions"] if action["section"] == "mission_control")
    assert any(not action["apply_supported"] for action in plan["actions"] if action["section"] == "integrations")
    assert any(not action["apply_supported"] for action in plan["actions"] if action["section"] == "ta_for_indexers")


def test_lookup_upload_apply_and_handoff_guards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lookup_file = tmp_path / "assets.csv"
    lookup_file.write_text("ip,priority\n192.0.2.10,high\n", encoding="utf-8")
    plan = engine.PlanBuilder(
        {
            "assets": [
                {
                    "name": "corp_assets",
                    "lookup_file": "corp_assets.csv",
                    "lookup_definition": "corp_assets_lookup",
                    "lookup_upload": {
                        "apply": True,
                        "file": str(lookup_file),
                        "acl": {"sharing": "app", "read": "*", "write": "admin"},
                    },
                }
            ]
        }
    ).build()

    upload_action = next(a for a in plan["actions"] if a["operation"] == "upload_lookup_file")
    assert upload_action["target"] == "corp_assets.csv"
    assert upload_action["apply_supported"] is True
    assert upload_action["payload"]["acl"]["sharing"] == "app"

    calls: list[tuple[str, object, object]] = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def set_conf(self, app, conf, stanza, payload):
            calls.append(("set_conf", f"{app}:{conf}/{stanza}", dict(payload)))
            return "updated"

        def upload_lookup_file(self, app, payload):
            calls.append(("upload_lookup_file", app, dict(payload)))
            return "uploaded:lookup_file_acl,lookup_definition_acl"

    monkeypatch.setattr(engine, "SplunkClient", FakeClient)
    result = engine.Runner(REPO_ROOT, {"assets": plan["normalized_spec"]["assets"]}).apply()

    assert any(call[0] == "upload_lookup_file" for call in calls)
    assert any(item["status"].startswith("uploaded") for item in result["results"])

    missing = engine.PlanBuilder(
        {
            "assets": [
                {
                    "name": "missing_assets",
                    "lookup_file": "missing.csv",
                    "lookup_definition": "missing_assets_lookup",
                    "lookup_upload": {"apply": True, "file": str(tmp_path / "missing.csv")},
                }
            ]
        }
    ).build()
    missing_action = next(a for a in missing["actions"] if a["operation"] == "lookup_file_handoff")
    assert missing_action["apply_supported"] is False
    assert "required_inputs" in missing_action["payload"]

    cloud = engine.PlanBuilder(
        {
            "connection": {"platform": "cloud"},
            "identities": [
                {
                    "name": "cloud_identities",
                    "lookup_file": "identities.csv",
                    "lookup_definition": "cloud_identities_lookup",
                    "lookup_upload": {"apply": True, "file": str(lookup_file)},
                }
            ],
        }
    ).build()
    cloud_action = next(a for a in cloud["actions"] if a["operation"] == "lookup_file_handoff")
    assert cloud_action["apply_supported"] is False
    assert "Splunk Cloud" in cloud_action["reason"]


def test_asset_identity_builder_generating_searches_are_guarded_and_splunk_safe() -> None:
    plan = engine.PlanBuilder(
        {
            "assets": [
                {
                    "name": "ldap_assets",
                    "lookup_file": "ldap_assets.csv",
                    "lookup_definition": "ldap_assets_lookup",
                    "ldap": {"profile": "corp_directory"},
                    "generating_search": {
                        "name": "ES - Generate LDAP Assets Lookup",
                        "search": "| inputlookup ldap_assets_source.csv | outputlookup ldap_assets.csv",
                        "cron_schedule": "17 */6 * * *",
                        "dispatch_earliest_time": "-6h",
                    },
                }
            ]
        }
    ).build()

    search_action = next(a for a in plan["actions"] if a["operation"] == "create_saved_search")
    assert search_action["section"] == "assets"
    assert search_action["app"] == engine.IDENTITY_APP
    assert search_action["target"] == "ES - Generate LDAP Assets Lookup"
    assert search_action["payload"]["disabled"] == "1"
    assert search_action["payload"]["is_scheduled"] == "1"
    assert search_action["payload"]["cron_schedule"] == "17 */6 * * *"
    assert search_action["payload"]["dispatch.earliest_time"] == "-6h"
    assert not any(str(key).startswith("es_") for key in search_action["payload"])

    handoff = engine.PlanBuilder(
        {
            "identities": [
                {
                    "name": "ldap_identities",
                    "lookup_file": "ldap_identities.csv",
                    "lookup_definition": "ldap_identities_lookup",
                    "ldap": {"profile": "corp_directory"},
                }
            ]
        }
    ).build()
    action = next(a for a in handoff["actions"] if a["operation"] == "search_builder_handoff")
    assert action["apply_supported"] is False
    assert "generating_search.search" in action["payload"]["required_inputs"]
    assert action["payload"]["builder_type"] == "ldap"

    no_outputlookup = engine.PlanBuilder(
        {
            "assets": [
                {
                    "name": "cloud_assets",
                    "lookup_definition": "cloud_assets_lookup",
                    "cloud_provider": {"provider": "aws"},
                    "generating_search": {"search": "| makeresults"},
                }
            ]
        }
    ).build()
    warnings = [d for d in no_outputlookup["diagnostics"] if d["section"] == "assets"]
    assert any("outputlookup" in d["message"] for d in warnings)


def test_threat_intel_upload_guards_and_sanitized_handoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    upload_file = tmp_path / "iocs.csv"
    upload_file.write_text("ip,description\n203.0.113.10,test\n", encoding="utf-8")
    spec = {
        "threat_intel": {
            "uploads": [
                {"name": "local_iocs", "file": str(upload_file), "format": "csv", "apply": True}
            ]
        }
    }
    plan = engine.PlanBuilder(spec).build()
    upload = next(a for a in plan["actions"] if a["operation"] == "upload_threat_intel")
    assert upload["apply_supported"] is True

    class UploadClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def upload_threat_intel(self, payload):
            assert payload["format"] == "csv"
            return "uploaded"

    monkeypatch.setattr(engine, "SplunkClient", UploadClient)
    assert engine.Runner(REPO_ROOT, spec).apply()["results"][0]["status"] == "uploaded"

    class UnsupportedClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def upload_threat_intel(self, _payload):
            raise engine.HandoffRequired("endpoint missing token=supersecret")

    monkeypatch.setattr(engine, "SplunkClient", UnsupportedClient)
    failed = engine.Runner(REPO_ROOT, spec).apply()["results"][0]
    assert failed["status"] == "handoff"
    assert "supersecret" not in failed["reason"]
    assert "[REDACTED]" in failed["reason"]

    invalid = engine.PlanBuilder(
        {"threat_intel": {"uploads": [{"name": "bad", "file": str(upload_file), "format": "json", "apply": True}]}}
    ).build()
    invalid_action = next(a for a in invalid["actions"] if a["operation"] == "threat_intel_upload")
    assert invalid_action["apply_supported"] is False
    assert "format" in invalid_action["reason"]


def test_mission_control_validate_and_apply_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    class ValidateClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def inventory(self) -> dict[str, object]:
            return {"apps": {}, "indexes": {}}

        def endpoint_status(self, path: str) -> dict[str, object]:
            return {"supported": "queues" in path, "entry_count": 1 if "queues" in path else 0}

        def app_exists(self, _app: str) -> bool:
            return True

    monkeypatch.setattr(engine, "SplunkClient", ValidateClient)
    result = engine.Runner(
        REPO_ROOT,
        {
            "mission_control": {
                "queues": [{"name": "tier1"}],
                "response_templates": [{"name": "triage"}],
            }
        },
    ).validate()

    mc_checks = [item for item in result["checks"] if item["operation"].endswith("_api")]
    assert {item["target"]: item["api_supported"] for item in mc_checks} == {"tier1": True, "triage": False}

    class ApplyClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, *_args, **_kwargs):
            raise KeyError("missioncontrol")

    monkeypatch.setattr(engine, "SplunkClient", ApplyClient)
    apply_result = engine.Runner(
        REPO_ROOT,
        {"mission_control": {"queues": [{"name": "tier1", "apply": True}]}},
    ).apply()
    assert apply_result["results"][0]["status"] == "handoff"
    assert "Mission Control API endpoint" in apply_result["results"][0]["reason"]


def test_mission_control_workload_pool_and_rbac_lockdown_are_guarded() -> None:
    plan = engine.PlanBuilder(
        {
            "mission_control": {
                "search": {"workload_pool": "soc_analyst_queue_pool", "unsupported_field": "handoff"},
                "rbac_lockdown": {
                    "apply": False,
                    "enabled": True,
                    "lock": True,
                    "roles": ["ess_analyst"],
                    "indexes": ["notable", "test_notable"],
                },
            }
        }
    ).build()

    workload = next(
        a
        for a in plan["actions"]
        if a["section"] == "mission_control" and a["target"] == "mc_search/aq_sid_caching"
    )
    assert workload["operation"] == "set_conf"
    assert workload["app"] == engine.MISSION_CONTROL_APP
    assert workload["payload"] == {"workload_pool": "soc_analyst_queue_pool"}

    unsupported = next(a for a in plan["actions"] if a["operation"] == "mission_control_setting_handoff")
    assert unsupported["apply_supported"] is False
    assert unsupported["payload"]["requested_field"] == "unsupported_field"

    lockdown = next(a for a in plan["actions"] if a["target"] == "lock_unlock_resources://default")
    assert lockdown["operation"] == "rbac_lockdown_handoff"
    assert lockdown["apply_supported"] is False
    assert "rbac_lockdown.apply: true" in lockdown["payload"]["required_inputs"]

    apply_plan = engine.PlanBuilder(
        {
            "mission_control": {
                "rbac_lockdown": {
                    "apply": True,
                    "enabled": True,
                    "lock": False,
                    "roles": ["user", "power"],
                }
            }
        }
    ).build()
    apply_action = next(a for a in apply_plan["actions"] if a["target"] == "lock_unlock_resources://default")
    assert apply_action["operation"] == "set_conf"
    assert apply_action["apply_supported"] is True
    assert apply_action["payload"]["disabled"] == "0"
    assert apply_action["payload"]["lock"] == "0"
    assert apply_action["payload"]["roles"] == "user,power"


def test_exposure_analytics_population_processing_and_handoffs() -> None:
    plan = engine.PlanBuilder(
        {
            "exposure_analytics": {
                "asset_identity_population": {
                    "assets": {
                        "enabled": True,
                        "cron_schedule": "*/15 * * * *",
                        "max_populate": 1000,
                        "fields": ["ip", "mac", "nt_host"],
                    },
                    "identities": {"enabled": False},
                },
                "processing_searches": [
                    {"name": "ea_srch_ip_asset_process", "enabled": True, "cron_schedule": "*/5 * * * *"}
                ],
                "sources": [{"name": "cloud_inventory_source", "entity_type": "asset"}],
                "enrichment_rules": [{"name": "asset_owner_enrichment"}],
            }
        }
    ).build()

    saved_searches = [a for a in plan["actions"] if a["operation"] == "set_saved_search"]
    by_target = {a["target"]: a for a in saved_searches}
    assert by_target["ea_gen_es_lookup_assets"]["app"] == engine.EXPOSURE_ANALYTICS_APP
    assert by_target["ea_gen_es_lookup_assets"]["payload"]["disabled"] == "0"
    assert by_target["ea_gen_es_lookup_assets"]["payload"]["cron_schedule"] == "*/15 * * * *"
    # Population search must be enabled via is_scheduled (the documented
    # Splunk REST field), not the legacy enableSched .conf key.
    assert by_target["ea_gen_es_lookup_assets"]["payload"]["is_scheduled"] == "1"
    assert "enableSched" not in by_target["ea_gen_es_lookup_assets"]["payload"]
    assert by_target["ea_gen_es_lookup_identities"]["payload"]["disabled"] == "1"
    assert by_target["ea_srch_ip_asset_process"]["payload"]["is_scheduled"] == "1"
    assert "enableSched" not in by_target["ea_srch_ip_asset_process"]["payload"]

    macros = {a["target"]: a for a in plan["actions"] if a["operation"] == "set_macro"}
    assert macros["ea_es_assets_max_populate"]["payload"]["definition"] == "1000"
    assert macros["ea_es_assets_fields"]["payload"]["definition"] == "ip,mac,nt_host"

    schema_checks = [a for a in plan["actions"] if a["operation"] == "exposure_schema_check"]
    assert {a["payload"]["object_type"] for a in schema_checks} == {"source", "enrichment_rule"}
    assert all(a["apply_supported"] is False for a in schema_checks)
    assert all(a["payload"]["schema_classification"] == "missing_endpoint" for a in schema_checks)


def test_ta_for_indexers_deploy_requires_two_phase_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    guarded = engine.PlanBuilder(
        {"ta_for_indexers": {"enabled": True, "deploy": True, "replace_existing": False}}
    ).build()
    deploy = next(a for a in guarded["actions"] if a["operation"] == "deploy_ta_for_indexers")
    assert deploy["apply_supported"] is False
    assert "confirm_id" in deploy["payload"]["handoff"]
    assert "backup_export" in ",".join(deploy["payload"]["handoff"]["required_inputs"])

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

    def fake_deploy(_self, _client, action):
        assert action.payload["replace_existing"] is True
        assert action.payload["backup_export"] == "ta-before.json"
        assert action.payload["conflict_checks_clean"] is True
        return "generated:/tmp/Splunk_TA_ForIndexers.spl"

    monkeypatch.setattr(engine, "SplunkClient", FakeClient)
    monkeypatch.setattr(engine.Runner, "_deploy_ta_for_indexers", fake_deploy)
    spec = {
        "ta_for_indexers": {
            "enabled": True,
            "deploy": True,
            "replace_existing": True,
            "overwrite_policy": "replace_existing",
            "backup_export": "ta-before.json",
            "conflict_checks_clean": True,
        }
    }
    confirm = next(
        a for a in engine.PlanBuilder(spec).build()["actions"] if a["operation"] == "deploy_ta_for_indexers"
    )["payload"]["handoff"]["confirm_id"]
    spec["ta_for_indexers"]["confirm_id"] = confirm
    result = engine.Runner(REPO_ROOT, spec).apply()
    assert any(item["status"].startswith("generated:") for item in result["results"])


def test_content_versioning_safe_toggle_and_handoff() -> None:
    plan = engine.PlanBuilder(
        {"content_governance": {"content_versioning": {"apply": True, "mode": "production", "enabled": True}}}
    ).build()
    action = next(a for a in plan["actions"] if a["section"] == "content_governance")
    assert action["operation"] == "set_conf"
    assert action["app"] == "SA-ContentVersioning"
    assert action["payload"]["mode"] == "production"
    assert action["payload"]["disabled"] == "0"

    rollback = engine.PlanBuilder(
        {"content_governance": {"content_versioning": {"rollback": "previous"}}}
    ).build()
    handoff = next(a for a in rollback["actions"] if a["operation"] == "content_versioning_handoff")
    assert handoff["apply_supported"] is False
    assert "confirm_id" in handoff["payload"]
    assert "backup" in ",".join(handoff["payload"]["required_inputs"])


def test_integration_preflight_secret_files_are_file_only_and_sanitized(tmp_path: Path) -> None:
    secret_file = tmp_path / "soar-password.txt"
    secret_file.write_text("super-secret-value", encoding="utf-8")
    secret_file.chmod(0o600)
    missing_file = tmp_path / "missing-token.txt"

    plan = engine.PlanBuilder(
        {
            "integrations": {
                "soar": {
                    "enabled": True,
                    "preflight": True,
                    "password_file": str(secret_file),
                    "token_file": str(missing_file),
                    "tenant_pairing": {"host": "https://soar.example.com", "role_mapping": ["ess_analyst"]},
                }
            }
        },
        tmp_path,
    ).build()

    preflight = next(a for a in plan["actions"] if a["operation"] == "integration_preflight")
    checks = {item["key"]: item for item in preflight["payload"]["secret_file_checks"]}
    assert checks["password_file"]["exists"] is True
    assert checks["password_file"]["secure_permissions"] is True
    assert checks["token_file"]["exists"] is False
    assert "super-secret-value" not in json.dumps(preflight)
    handoff = next(a for a in plan["actions"] if a["operation"] == "handoff" and a["section"] == "integrations")
    assert str(secret_file) in handoff["payload"]["blocking_secret_files"]
    assert str(missing_file) in handoff["payload"]["blocking_secret_files"]


def test_cloud_support_evidence_package_is_handoff_only() -> None:
    plan = engine.PlanBuilder(
        {
            "connection": {"platform": "cloud", "cloud_support": {"evidence_package": True}},
            "content_library": {"install": True},
            "integrations": {"splunk_cloud_connect": {"enabled": True, "support_required": True}},
        }
    ).build()

    evidence = next(a for a in plan["actions"] if a["operation"] == "cloud_support_evidence")
    assert evidence["apply_supported"] is False
    assert evidence["payload"]["requested_apps"]
    assert "app inventory" in evidence["payload"]["acs_supported_operations"]
    assert "Support-managed" in evidence["reason"]


def test_mission_control_private_overrides_are_allowlisted_or_confirm_gated() -> None:
    safe = engine.PlanBuilder(
        {
            "mission_control": {
                "private_overrides": [
                    {
                        "conf": "mc_search",
                        "stanza": "aq_sid_caching",
                        "values": {"workload_pool": "soc_analyst_queue_pool"},
                    }
                ]
            }
        }
    ).build()
    safe_action = next(a for a in safe["actions"] if a["target"] == "mc_search/aq_sid_caching")
    assert safe_action["operation"] == "set_conf"
    assert safe_action["apply_supported"] is True

    blocked_spec = {
        "mission_control": {
            "private_overrides": [
                {
                    "conf": "mc_rate_limit",
                    "stanza": "limits",
                    "values": {"burst": "10"},
                    "private_override": True,
                    "apply": True,
                    "backup_export": "mc-before.json",
                }
            ]
        }
    }
    blocked = engine.PlanBuilder(blocked_spec).build()
    handoff = next(a for a in blocked["actions"] if a["operation"] == "private_override_handoff")
    assert handoff["apply_supported"] is False
    confirm = handoff["payload"]["confirm_id"]
    blocked_spec["mission_control"]["private_overrides"][0]["confirm_id"] = confirm
    allowed = engine.PlanBuilder(blocked_spec).build()
    private_apply = next(a for a in allowed["actions"] if a["target"] == "mc_rate_limit/limits")
    assert private_apply["operation"] == "set_conf"
    assert private_apply["apply_supported"] is True


def test_exposure_analytics_schema_create_only_and_conflicts() -> None:
    plan = engine.PlanBuilder(
        {
            "exposure_analytics": {
                "sources": [
                    {"name": "missing_endpoint", "apply": True, "conflict_policy": "create_only"},
                    {
                        "name": "new_source",
                        "apply": True,
                        "conflict_policy": "create_only",
                        "endpoint": "/servicesNS/nobody/exposure-analytics/configs/conf-ea_sources",
                        "entity_type": "asset",
                    },
                    {
                        "name": "update_source",
                        "apply": True,
                        "conflict_policy": "create_only",
                        "endpoint": "/servicesNS/nobody/exposure-analytics/configs/conf-ea_sources/update_source",
                        "operation": "update",
                    },
                ],
                "enrichment_rules": [
                    {
                        "name": "new_rule",
                        "apply": True,
                        "conflict_policy": "create_only",
                        "endpoint": "/servicesNS/nobody/exposure-analytics/configs/conf-ea_enrichment_rules",
                        "rule_type": "lookup",
                    }
                ],
            }
        }
    ).build()

    apply_actions = [a for a in plan["actions"] if a["operation"] == "exposure_schema_apply"]
    assert {a["target"] for a in apply_actions} == {"new_source", "new_rule"}
    checks = {a["target"]: a for a in plan["actions"] if a["operation"] == "exposure_schema_check"}
    assert checks["missing_endpoint"]["payload"]["schema_classification"] == "missing_endpoint"
    assert checks["update_source"]["payload"]["schema_classification"] == "manual_resolution_required"


def test_content_versioning_destructive_apply_requires_confirm_id() -> None:
    spec = {
        "content_governance": {
            "content_versioning": {
                "rollback": {
                    "target": "previous",
                    "endpoint": "/servicesNS/nobody/SA-ContentVersioning/content/rollback",
                    "apply": True,
                    "backup_export": "content-before.json",
                }
            }
        }
    }
    preview = engine.PlanBuilder(spec).build()
    handoff = next(a for a in preview["actions"] if a["operation"] == "content_versioning_handoff")
    assert handoff["apply_supported"] is False
    spec["content_governance"]["content_versioning"]["rollback"]["confirm_id"] = handoff["payload"]["confirm_id"]
    allowed = engine.PlanBuilder(spec).build()
    action = next(a for a in allowed["actions"] if a["operation"] == "content_versioning_destructive_apply")
    assert action["apply_supported"] is True
    assert action["payload"]["object"]["target"] == "previous"


def test_package_conf_coverage_classifies_local_es_package() -> None:
    if not ES_PACKAGE.exists():
        pytest.skip("Local ES package is not present.")

    manifest = engine.package_conf_coverage_manifest(REPO_ROOT)
    families = {item["name"]: item for item in manifest["families"]}

    assert manifest["package_present"] is True
    assert manifest["unclassified"] == []
    for family in ("analyticstories", "app_permissions", "managed_configurations", "mc_search"):
        assert family in families
        assert families[family]["managed_by"] == "package_conf_coverage"
        assert families[family]["stanza_count"] > 0
    assert families["savedsearches"]["managed_by"] == "detections"
    assert families["cloud_integrations"]["managed_by"] == "integrations"


def test_package_conf_coverage_plan_and_live_inventory() -> None:
    plan = engine.PlanBuilder(
        {
            "package_conf_coverage": {
                "inventory": True,
                "include_live": True,
                "families": ["analyticstories"],
                "max_entries_per_family": 2,
            }
        }
    ).build()
    action = next(a for a in plan["actions"] if a["section"] == "package_conf_coverage")
    assert action["operation"] == "package_conf_inventory"
    assert action["apply_supported"] is False

    class FakePackageConfClient(engine.SplunkClient):
        def __init__(self, project_root: Path, spec: dict[str, object]) -> None:
            self.project_root = project_root
            self.spec = spec

        def safe_entries(self, path: str) -> list[dict[str, object]]:
            if "conf-analyticstories" in path:
                return [
                    {"name": "analytic_story://one", "secret": "hidden"},
                    {"name": "analytic_story://two"},
                    {"name": "analytic_story://three"},
                ]
            return []

    inventory = FakePackageConfClient(
        REPO_ROOT,
        {
            "package_conf_coverage": {
                "include_live": True,
                "families": ["analyticstories"],
                "max_entries_per_family": 2,
            }
        },
    ).package_conf_coverage_inventory()

    assert [item["name"] for item in inventory["families"]] == ["analyticstories"]
    assert inventory["live"][0]["name"] == "analyticstories"
    live_entries = inventory["live"][0]["apps"][0]["entries"]
    assert len(live_entries) == 2
    assert "secret" not in live_entries[0]


def test_empty_brownfield_export_round_trips_without_spurious_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    class EmptyInventoryClient(engine.SplunkClient):
        def __init__(self, project_root: Path, spec: dict[str, object]) -> None:
            self.project_root = project_root
            self.spec = spec

        def app_exists(self, _app: str) -> bool:
            return False

        def index_exists(self, _index: str) -> bool:
            return False

        def safe_entries(self, _path: str) -> list[dict[str, object]]:
            return []

        def endpoint_status(self, _path: str) -> dict[str, object]:
            return {"supported": False, "entry_count": 0}

    monkeypatch.setattr(engine, "SplunkClient", EmptyInventoryClient)
    exported = engine.Runner(REPO_ROOT, {}).export()["export"]
    roundtrip = engine.PlanBuilder(exported).build()

    assert not roundtrip["diagnostics"]
    assert exported["content_library"].get("escu", {}) == {}
    assert "test_mode" not in exported["content_governance"]
    assert exported["package_conf_coverage"]["families"] == "all"
    assert not any(
        action["section"] == "content_library" and action["operation"] == "set_conf"
        for action in roundtrip["actions"]
    )


def test_conf_and_stanza_uses_endpoint_stanza_for_encoded_inputs() -> None:
    action = engine.Action(
        section="baseline",
        operation="set_conf",
        target="app_permissions_manager://enforce_es_permissions",
        app="SplunkEnterpriseSecuritySuite",
        endpoint="/servicesNS/nobody/SplunkEnterpriseSecuritySuite/configs/conf-inputs/app_permissions_manager%3A%2F%2Fenforce_es_permissions",
        payload={"disabled": "0"},
    )

    assert engine.Runner._conf_and_stanza(action) == ("inputs", "app_permissions_manager://enforce_es_permissions")


def test_apply_uses_mocked_rest_client_and_preserves_handoffs(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []

    class FakeClient:
        def __init__(self, project_root: Path, spec: dict[str, object]) -> None:
            calls.append(("init", project_root, bool(spec)))

        def create_index(self, payload: dict[str, object]) -> str:
            calls.append(("create_index", payload["name"]))
            return "created"

        def set_global_conf(self, conf: str, stanza: str, payload: dict[str, object]) -> str:
            calls.append(("set_global_conf", conf, stanza, payload))
            return "updated"

        def set_conf(self, app: str, conf: str, stanza: str, payload: dict[str, object]) -> str:
            calls.append(("set_conf", app, conf, stanza, payload))
            return "updated"

        def set_saved_search(
            self,
            app: str,
            name: str,
            payload: dict[str, object],
            create_missing: bool = True,
        ) -> str:
            calls.append(("set_saved_search", app, name, create_missing, payload))
            return "created" if create_missing else "updated"

        def set_role(self, name: str, payload: dict[str, object]) -> str:
            calls.append(("set_role", name, payload))
            return "updated"

    monkeypatch.setattr(engine, "SplunkClient", FakeClient)
    spec = {
        "baseline": True,
        "indexes": [{"name": "custom_sec"}],
        "roles": [{"name": "ess_analyst", "allowed_indexes": ["main"]}],
        "detections": {
            "existing": [{"name": "Existing Detection", "enabled": False}],
            "custom": [{"name": "Custom Detection", "search": "| makeresults"}],
        },
        "ta_for_indexers": {"enabled": True},
    }

    result = engine.Runner(REPO_ROOT, spec).apply()

    assert result["mode"] == "apply"
    assert any(item["status"] == "handoff" for item in result["results"])
    assert ("create_index", "custom_sec") in calls
    assert any(call[:3] == ("set_saved_search", "SplunkEnterpriseSecuritySuite", "Existing Detection") and call[3] is False for call in calls)
    assert any(call[:3] == ("set_saved_search", "SplunkEnterpriseSecuritySuite", "Custom Detection") and call[3] is True for call in calls)


def test_validate_runs_declarative_search_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def inventory(self) -> dict[str, object]:
            return {"apps": {}, "indexes": {}}

        def index_exists(self, _index: str) -> bool:
            return True

        def app_exists(self, _app: str) -> bool:
            return True

        def run_search(self, search: str) -> dict[str, object]:
            if "bad" in search:
                raise engine.EsConfigError("search failed password=supersecret")
            return {"event_count": 2}

    monkeypatch.setattr(engine, "SplunkClient", FakeClient)
    result = engine.Runner(
        REPO_ROOT,
        {
            "validation": {
                "searches": [
                    {"name": "good_check", "search": "| makeresults"},
                    {"name": "bad_check", "search": "| bad"},
                ]
            }
        },
    ).validate()

    assert result["search_checks"][0] == {
        "name": "good_check",
        "search": "| makeresults",
        "ok": True,
        "event_count": 2,
        "expect_rows": True,
        "min_event_count": 1,
    }
    failed = result["search_checks"][1]
    assert failed["name"] == "bad_check"
    assert failed["ok"] is False
    assert failed["event_count"] == 0
    assert "supersecret" not in failed["error"]
    assert "[REDACTED]" in failed["error"]


def test_validate_marks_zero_event_searches_failed_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    class ZeroResultClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def inventory(self) -> dict[str, object]:
            return {"apps": {}, "indexes": {}}

        def index_exists(self, _index: str) -> bool:
            return True

        def app_exists(self, _app: str) -> bool:
            return True

        def run_search(self, _search: str) -> dict[str, object]:
            return {"event_count": 0}

    monkeypatch.setattr(engine, "SplunkClient", ZeroResultClient)
    result = engine.Runner(
        REPO_ROOT,
        {
            "validation": {
                "searches": [
                    {"name": "smoke", "search": "| tstats count where index=notable"},
                    {"name": "presence_only", "search": "| metadata type=hosts", "expect_rows": False},
                    {"name": "needs_five", "search": "| makeresults count=2", "min_event_count": 5},
                ]
            }
        },
    ).validate()

    smoke = result["search_checks"][0]
    assert smoke["ok"] is False, "zero-event default smoke check must fail"
    assert smoke["event_count"] == 0
    assert smoke["min_event_count"] == 1
    assert "expected at least 1" in smoke.get("reason", "")

    # expect_rows=False explicitly relaxes to min_event_count=0.
    presence_only = result["search_checks"][1]
    assert presence_only["ok"] is True
    assert presence_only["min_event_count"] == 0

    # min_event_count=5 with 0 results fails.
    needs_five = result["search_checks"][2]
    assert needs_five["ok"] is False
    assert needs_five["min_event_count"] == 5


def test_inventory_and_export_include_extended_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeInventoryClient(engine.SplunkClient):
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def app_exists(self, app: str) -> bool:
            return app in {
                engine.APP_NAME,
                engine.THREAT_APP,
                engine.UTILS_APP,
                engine.AUDIT_APP,
                engine.CONTENT_UPDATE_APP,
                engine.CONTENT_LIBRARY_APP,
                engine.EXPOSURE_ANALYTICS_APP,
            }

        def index_exists(self, index: str) -> bool:
            return index in {"risk", "notable"}

        def endpoint_status(self, path: str) -> dict[str, object]:
            return {"supported": "missioncontrol" in path, "entry_count": 0}

        def safe_entries(self, path: str) -> list[dict[str, object]]:
            if "data/lookup-table-files" in path:
                return [
                    {
                        "name": "assets.csv",
                        "acl": {"sharing": "app", "perms": {"read": ["*"], "write": ["admin"]}},
                    }
                ]
            if "conf-transforms" in path:
                return [
                    {
                        "name": "assets_lookup",
                        "filename": "assets.csv",
                        "fields_list": "ip,priority",
                        "acl": {"sharing": "app"},
                    }
                ]
            if "conf-inputs" in path and engine.IDENTITY_APP in path:
                return [
                    {
                        "name": "identity_manager://assets",
                        "target": "asset",
                        "url": "lookup://assets_lookup",
                        "category": "corporate",
                    }
                ]
            if "conf-urgency" in path:
                return [{"name": "high|high", "urgency": "critical", "secret": "hidden"}]
            if "conf-alert_actions" in path:
                return [{"name": "risk", "param._risk_score": "25"}]
            if "conf-notable_suppressions" in path:
                return [{"name": "notable_suppression://scanner", "search": "index=notable"}]
            if "conf-log_review" in path:
                return [{"name": "status:5", "label": "Resolved"}]
            if "conf-use_cases" in path:
                return [{"name": "access_protection", "category": "access"}]
            if "conf-governance" in path:
                return [{"name": "pci", "label": "PCI DSS"}]
            if f"{engine.EXPOSURE_ANALYTICS_APP}/admin/macros" in path:
                return [
                    {"name": "ea_es_assets_max_populate", "definition": "500000"},
                    {"name": "ea_es_assets_fields", "definition": "ip,mac,nt_host"},
                ]
            if "admin/macros" in path:
                return [{"name": "sec_indexes", "definition": "index=risk"}]
            if "saved/eventtypes" in path:
                return [{"name": "priv_logins", "search": "tag=authentication"}]
            if "saved/fvtags" in path:
                return [{"name": "user_category=privileged", "es_privileged": "enabled"}]
            if "data/ui/nav" in path:
                return [{"name": "default", "eai:data": "<nav/>"}]
            if "data/ui/views" in path:
                return [{"name": "soc_overview", "eai:data": "<dashboard/>"}]
            if "conf-escu_subscription" in path:
                return [{"name": "subscription", "subscription": "enterprise"}]
            if f"{engine.CONTENT_UPDATE_APP}/saved/searches" in path:
                return [{"name": "ESCU - Detect New Local Admin Account", "actions": "risk"}]
            if "conf-content_packs" in path:
                return [{"name": "cloud_security", "disabled": "0"}]
            if f"{engine.EXPOSURE_ANALYTICS_APP}/saved/searches" in path:
                return [
                    {
                        "name": "ea_gen_es_lookup_assets",
                        "disabled": "0",
                        "cron_schedule": "*/15 * * * *",
                    },
                    {
                        "name": "ea_gen_es_lookup_identities",
                        "disabled": "1",
                        "cron_schedule": "*/30 * * * *",
                    },
                ]
            if f"{engine.EXPOSURE_ANALYTICS_APP}/configs/conf-ea_sources" in path:
                return [{"name": "cloud_inventory_source", "entity_type": "asset"}]
            if f"{engine.EXPOSURE_ANALYTICS_APP}/configs/conf-ea_enrichment_rules" in path:
                return [{"name": "asset_owner_enrichment", "rule_type": "lookup"}]
            if f"{engine.EXPOSURE_ANALYTICS_APP}/configs/conf-restmap" in path:
                return [{"name": "ea_sources", "handler": "exposure_analytics"}]
            if f"{engine.EXPOSURE_ANALYTICS_APP}/configs/conf-transforms" in path:
                return [{"name": "entity_discovery_assets", "filename": "entity_discovery_assets.csv"}]
            if f"{engine.MISSION_CONTROL_APP}/configs/conf-mc_search" in path:
                return [{"name": "aq_sid_caching", "workload_pool": "soc_analyst_queue_pool"}]
            if f"{engine.MISSION_CONTROL_APP}/configs/conf-inputs" in path:
                return [
                    {
                        "name": "lock_unlock_resources://default",
                        "disabled": "1",
                        "lock": "1",
                        "roles": "user,power",
                        "indexes": "notable,test_notable",
                    }
                ]
            return []

    fake_inventory = FakeInventoryClient(REPO_ROOT, {})
    inventory = fake_inventory.inventory()

    for section in (
        "urgency",
        "adaptive_response",
        "notable_suppressions",
        "log_review",
        "use_cases",
        "governance",
        "macros",
        "eventtypes",
        "tags",
        "navigation",
        "glass_tables",
        "exposure_analytics",
        "content_library",
    ):
        assert section in inventory
    assert "secret" not in inventory["urgency"][0]
    assert inventory["content_library"]["apps"][engine.CONTENT_UPDATE_APP] is True

    monkeypatch.setattr(engine, "SplunkClient", FakeInventoryClient)
    exported = engine.Runner(REPO_ROOT, {}).export()["export"]

    assert exported["urgency"]["matrix"][0]["urgency"] == "critical"
    assert exported["notable_suppressions"][0]["name"] == "scanner"
    assert exported["content_library"]["apps"][engine.CONTENT_LIBRARY_APP] is True
    assert exported["content_library"]["content_packs"][0]["name"] == "cloud_security"
    assert exported["exposure_analytics"]["asset_identity_population"]["assets"]["max_populate"] == "500000"
    assert exported["mission_control"]["search"]["workload_pool"] == "soc_analyst_queue_pool"
    assert exported["mission_control"]["rbac_lockdown"]["roles"] == ["user", "power"]
    assert exported["assets"][0]["lookup_file"] == "assets.csv"
    assert exported["tags"][0] == {"field": "user_category", "value": "privileged", "tags": ["es_privileged"]}
    assert exported["navigation"]["xml"] == "<nav/>"

    roundtrip = engine.PlanBuilder(exported).build()
    assert not roundtrip["diagnostics"]


def test_content_library_apply_installs_missing_escu(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class Completed:
        returncode = 0
        stdout = "installed"

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def app_exists(self, _app: str) -> bool:
            return False

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        return Completed()

    monkeypatch.setattr(engine, "SplunkClient", FakeClient)
    monkeypatch.setattr(engine.subprocess, "run", fake_run)

    result = engine.Runner(
        REPO_ROOT,
        {"content_library": {"install": True, "app_ids": {"content_update": "3449"}}},
    ).apply()

    assert result["results"] == [
        {"target": engine.CONTENT_UPDATE_APP, "operation": "install_app", "status": "installed"}
    ]
    assert calls
    assert calls[0][-5:] == ["--source", "splunkbase", "--app-id", "3449", "--update"]


def test_local_es_package_exposure_indexes_match_engine_truth() -> None:
    if not ES_PACKAGE.exists():
        pytest.skip("Local ES package is not present.")

    with tarfile.open(ES_PACKAGE) as outer:
        nested = outer.extractfile("SplunkEnterpriseSecuritySuite/install/exposure-analytics_8.5.0-1462.tgz")
        assert nested is not None
        nested_bytes = nested.read()

    with tarfile.open(fileobj=io.BytesIO(nested_bytes), mode="r:gz") as inner:
        indexes_conf = inner.extractfile("exposure-analytics/default/indexes.conf")
        assert indexes_conf is not None
        indexes_text = indexes_conf.read().decode("utf-8", errors="replace")

    assert "[ea_discovery]" in indexes_text
    assert "[es_discovery]" not in indexes_text
    assert "ea_discovery" in engine.INDEX_GROUPS["exposure"]
    assert "es_discovery" not in engine.INDEX_GROUPS["exposure"]
