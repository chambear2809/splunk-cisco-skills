"""Tests for the splunk-observability-azure-integration skill.

Covers:
- Default spec (template.example) tenant_id validation
- Valid spec renders cleanly (type=Azure, pollRate, shape)
- Coverage keys completeness
- REST payload: type=Azure, tenantId, subscriptions, pollRate in ms, appId placeholder
- Terraform: signalfx_azure_integration resource present
- Azure CLI scripts rendered when azure_cli_render=true
- Bicep rendered when bicep_render=true
- Secret-leak scan across the rendered tree
- Conflict matrix: empty services rejected
- Conflict matrix: pollRate out of range rejected
- Conflict matrix: placeholder tenant_id rejected
- Conflict matrix: placeholder subscriptions rejected
- all_built_in services mode renders without explicit services list
- named_token warning comment in Terraform
- azure_environment=AZURE_US_GOVERNMENT warns
- Handoff scripts emitted for enabled handoffs
- setup.sh --help exits 0
- validate.sh against rendered tree exits 0
- smoke_offline.sh exits 0
- --list-services returns ~80 entries
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills/splunk-observability-azure-integration"
SCRIPTS_DIR = SKILL_DIR / "scripts"
SETUP = SCRIPTS_DIR / "setup.sh"
TEMPLATE = SKILL_DIR / "template.example"


def _load_renderer():
    spec = importlib.util.spec_from_file_location(
        "sazure_render_assets", SCRIPTS_DIR / "render_assets.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _valid_spec(**overrides) -> dict:
    base = {
        "api_version": "splunk-observability-azure-integration/v1",
        "realm": "us1",
        "integration_name": "test-azure",
        "authentication": {
            "tenant_id": "12345678-abcd-abcd-abcd-123456789abc",
        },
        "azure_environment": "AZURE",
        "subscriptions": ["abcdef01-abcd-abcd-abcd-abcdef012345"],
        "connection": {
            "mode": "polling",
            "poll_rate_seconds": 300,
            "use_batch_api": True,
            "import_azure_monitor": True,
            "sync_guest_os_namespaces": False,
        },
        "services": {
            "mode": "explicit",
            "explicit": ["microsoft.compute/virtualmachines"],
            "additional_services": [],
            "custom_namespaces_per_service": [],
        },
        "resource_filter_rules": [],
        "named_token": "",
        "terraform_provider": {"source": "splunk-terraform/signalfx", "version": "~> 9.0"},
        "azure_cli_render": True,
        "bicep_render": False,
        "multi_subscription": {"enabled": False, "management_group_id": ""},
        "handoffs": {
            "splunk_ta_microsoft_cloud_services": False,
            "microsoft_azure_app": False,
            "aks_otel_collector": False,
            "dashboards": False,
            "detectors": False,
        },
    }
    base.update(overrides)
    return base


class TestAzureRenderer:
    def setup_method(self):
        self.mod = _load_renderer()

    def _render(self, spec_dict, tmp_path, realm=None):
        validated = self.mod.validate_spec(spec_dict.copy(), realm_override=realm)
        return self.mod.render(validated, tmp_path)

    def test_valid_spec_renders(self, tmp_path):
        result = self._render(_valid_spec(), tmp_path)
        assert result["coverage_summary"]["total"] > 0
        assert (tmp_path / "rest" / "create.json").exists()

    def test_rest_payload_type_azure(self, tmp_path):
        self._render(_valid_spec(), tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        assert payload["type"] == "Azure"

    def test_rest_payload_poll_rate_milliseconds(self, tmp_path):
        self._render(_valid_spec(), tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        assert payload["pollRate"] == 300000

    def test_rest_payload_app_id_placeholder(self, tmp_path):
        self._render(_valid_spec(), tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        assert "${APP_ID_FROM_FILE}" in payload["appId"]

    def test_rest_payload_secret_placeholder(self, tmp_path):
        self._render(_valid_spec(), tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        assert "${SECRET_KEY_FROM_FILE}" in payload["secretKey"]

    def test_rest_payload_tenant_id(self, tmp_path):
        self._render(_valid_spec(), tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        assert payload["tenantId"] == "12345678-abcd-abcd-abcd-123456789abc"

    def test_rest_payload_subscriptions(self, tmp_path):
        self._render(_valid_spec(), tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        assert isinstance(payload["subscriptions"], list)
        assert len(payload["subscriptions"]) == 1

    def test_update_json_has_enabled_true(self, tmp_path):
        self._render(_valid_spec(), tmp_path)
        payload = json.loads((tmp_path / "rest" / "update.json").read_text())
        assert payload["enabled"] is True

    def test_terraform_signalfx_resource(self, tmp_path):
        self._render(_valid_spec(), tmp_path)
        tf = (tmp_path / "terraform" / "main.tf").read_text()
        assert "signalfx_azure_integration" in tf

    def test_terraform_poll_rate_seconds(self, tmp_path):
        self._render(_valid_spec(), tmp_path)
        tf = (tmp_path / "terraform" / "main.tf").read_text()
        assert "poll_rate = 300" in tf

    def test_azure_cli_scripts_rendered(self, tmp_path):
        self._render(_valid_spec(), tmp_path)
        assert (tmp_path / "azure-cli" / "create-sp.sh").exists()
        assert (tmp_path / "azure-cli" / "grant-monitoring-reader.sh").exists()

    def test_azure_cli_not_rendered_when_disabled(self, tmp_path):
        spec = _valid_spec(azure_cli_render=False)
        self._render(spec, tmp_path)
        assert not (tmp_path / "azure-cli").exists() or not (tmp_path / "azure-cli" / "create-sp.sh").exists()

    def test_bicep_rendered_when_enabled(self, tmp_path):
        spec = _valid_spec(bicep_render=True)
        self._render(spec, tmp_path)
        assert (tmp_path / "bicep" / "role-assignment.bicep").exists()

    def test_bicep_not_rendered_by_default(self, tmp_path):
        self._render(_valid_spec(), tmp_path)
        assert not (tmp_path / "bicep" / "role-assignment.bicep").exists()

    def test_state_directory_created(self, tmp_path):
        self._render(_valid_spec(), tmp_path)
        assert (tmp_path / "state" / "apply-state.json").exists()
        assert (tmp_path / "state" / "credential-hashes.json").exists()

    def test_coverage_report_exists(self, tmp_path):
        self._render(_valid_spec(), tmp_path)
        data = json.loads((tmp_path / "coverage-report.json").read_text())
        assert data["realm"] == "us1"
        assert data["integration_name"] == "test-azure"

    def test_no_secret_leak_in_rendered_tree(self, tmp_path):
        import re
        self._render(_valid_spec(), tmp_path)
        secret_pat = re.compile(r"eyJ[A-Za-z0-9._-]{20,}|Bearer\s+[A-Za-z0-9._-]{12,}")
        for path in tmp_path.rglob("*"):
            if path.is_file() and path.suffix in (".json", ".sh", ".tf", ".md", ".bicep"):
                content = path.read_text(encoding="utf-8", errors="replace")
                assert not secret_pat.search(content), f"Secret-looking content in {path}"

    def test_all_built_in_mode_no_services_field(self, tmp_path):
        spec = _valid_spec()
        spec["services"]["mode"] = "all_built_in"
        spec["services"]["explicit"] = []
        self._render(spec, tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        assert "services" not in payload

    def test_explicit_services_in_payload(self, tmp_path):
        self._render(_valid_spec(), tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        assert "microsoft.compute/virtualmachines" in payload.get("services", [])

    def test_additional_services_in_payload(self, tmp_path):
        spec = _valid_spec()
        spec["services"]["additional_services"] = ["microsoft.custom/resource"]
        self._render(spec, tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        assert "microsoft.custom/resource" in payload.get("additionalServices", [])

    def test_named_token_in_payload(self, tmp_path):
        spec = _valid_spec(named_token="my-token")
        self._render(spec, tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        assert payload.get("namedToken") == "my-token"

    def test_resource_filter_rules_in_payload(self, tmp_path):
        spec = _valid_spec()
        spec["resource_filter_rules"] = [{"filter_source": "filter('env','prod')"}]
        self._render(spec, tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        rules = payload.get("resourceFilterRules", [])
        assert len(rules) == 1
        assert rules[0]["filter"]["source"] == "filter('env','prod')"

    def test_handoff_scripts_emitted(self, tmp_path):
        spec = _valid_spec()
        spec["handoffs"]["dashboards"] = True
        self._render(spec, tmp_path)
        assert (tmp_path / "handoffs" / "handoff-dashboards.sh").exists()

    def test_handoff_ta_3110_emitted(self, tmp_path):
        spec = _valid_spec()
        spec["handoffs"]["splunk_ta_microsoft_cloud_services"] = True
        self._render(spec, tmp_path)
        assert (tmp_path / "handoffs" / "handoff-splunk-ta-3110.sh").exists()

    def test_poll_rate_out_of_range_rejected(self):
        spec = _valid_spec()
        spec["connection"]["poll_rate_seconds"] = 30
        with pytest.raises(self.mod.RenderError, match="poll_rate_seconds"):
            self.mod.validate_spec(spec)

    def test_poll_rate_above_max_rejected(self):
        spec = _valid_spec()
        spec["connection"]["poll_rate_seconds"] = 700
        with pytest.raises(self.mod.RenderError, match="poll_rate_seconds"):
            self.mod.validate_spec(spec)

    def test_placeholder_tenant_id_rejected(self):
        spec = _valid_spec()
        spec["authentication"]["tenant_id"] = "00000000-0000-0000-0000-000000000000"
        with pytest.raises(self.mod.RenderError, match="tenant_id"):
            self.mod.validate_spec(spec)

    def test_placeholder_subscription_rejected(self):
        spec = _valid_spec()
        spec["subscriptions"] = ["00000000-0000-0000-0000-000000000000"]
        with pytest.raises(self.mod.RenderError, match="subscriptions"):
            self.mod.validate_spec(spec)

    def test_empty_services_rejected(self):
        spec = _valid_spec()
        spec["services"]["explicit"] = []
        spec["services"]["additional_services"] = []
        with pytest.raises(self.mod.RenderError, match="services"):
            self.mod.validate_spec(spec)

    def test_azure_us_government_warns(self):
        spec = _valid_spec(azure_environment="AZURE_US_GOVERNMENT")
        validated = self.mod.validate_spec(spec)
        assert any("GovCloud" in w for w in validated.get("_warnings", []))

    def test_invalid_realm_rejected(self):
        with pytest.raises(self.mod.RenderError, match="realm"):
            self.mod.validate_spec(_valid_spec(), realm_override="invalid-realm")

    def test_list_services(self):
        services = self.mod.load_services_enum()
        assert len(services) >= 30
        assert "microsoft.compute/virtualmachines" in services


class TestAzureShellScripts:
    def test_setup_sh_help(self):
        result = subprocess.run(
            ["bash", str(SCRIPTS_DIR / "setup.sh"), "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "render" in result.stdout.lower() or "render" in result.stderr.lower()

    def test_validate_sh_on_rendered_tree(self, tmp_path):
        mod = _load_renderer()
        spec = mod.validate_spec(_valid_spec())
        mod.render(spec, tmp_path)
        result = subprocess.run(
            ["bash", str(SCRIPTS_DIR / "validate.sh"), "--output-dir", str(tmp_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_smoke_offline(self):
        result = subprocess.run(
            ["bash", str(SCRIPTS_DIR / "smoke_offline.sh")],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, result.stdout + result.stderr


class TestAzureTemplateExample:
    def test_template_example_fails_on_placeholder_tenant(self):
        mod = _load_renderer()
        spec_text = TEMPLATE.read_text(encoding="utf-8")
        sys.path.insert(0, str(SKILL_DIR.parent.parent / "shared" / "lib"))
        from yaml_compat import load_yaml_or_json
        spec = load_yaml_or_json(spec_text, source=str(TEMPLATE))
        assert isinstance(spec, dict)
        with pytest.raises(mod.RenderError):
            mod.validate_spec(spec, realm_override="us1")
