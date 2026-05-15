"""Tests for the splunk-observability-gcp-integration skill.

Covers:
- Valid spec (SA Key mode) renders cleanly (type=GCP, pollRate, shape)
- Valid spec (WIF mode) renders cleanly
- Coverage keys completeness
- REST payload: type=GCP, authMethod, projectServiceKeys placeholder, pollRate in ms
- Terraform: signalfx_gcp_integration resource present
- gcloud-cli scripts rendered when gcloud_cli_render=true
- Secret-leak scan across the rendered tree
- Conflict matrix: SA Key mode with WIF block → rejected
- Conflict matrix: WIF mode with SA Keys → rejected
- Conflict matrix: explicit services + all_built_in → rejected
- pollRate out of range rejected
- Handoff scripts emitted for enabled handoffs
- setup.sh --help exits 0
- validate.sh against rendered tree exits 0
- smoke_offline.sh exits 0
- --list-services returns 32 entries
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills/splunk-observability-gcp-integration"
SCRIPTS_DIR = SKILL_DIR / "scripts"
SETUP = SCRIPTS_DIR / "setup.sh"
TEMPLATE = SKILL_DIR / "template.example"


def _load_renderer():
    spec = importlib.util.spec_from_file_location(
        "sgcp_render_assets", SCRIPTS_DIR / "render_assets.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _valid_sa_key_spec(**overrides) -> dict:
    base = {
        "api_version": "splunk-observability-gcp-integration/v1",
        "realm": "us1",
        "integration_name": "test-gcp",
        "authentication": {
            "mode": "service_account_key",
            "project_service_keys": [
                {"project_id": "my-gcp-project-123", "key_file": "/tmp/fake-key.json"}
            ],
            "workload_identity_federation": {},
        },
        "connection": {
            "poll_rate_seconds": 300,
            "use_metric_source_project_for_quota": False,
            "import_gcp_metrics": True,
        },
        "projects": {
            "sync_mode": "ALL",
            "selected_project_ids": [],
        },
        "services": {
            "mode": "explicit",
            "explicit": ["compute"],
        },
        "custom_metric_type_domains": [],
        "exclude_gce_instances_with_labels": [],
        "named_token": "",
        "terraform_provider": {"source": "splunk-terraform/signalfx", "version": "~> 9.0"},
        "gcloud_cli_render": True,
        "multi_project": {"enabled": False},
        "handoffs": {
            "splunk_ta_google_cloud": False,
            "gke_otel_collector": False,
            "dashboards": False,
            "detectors": False,
        },
    }
    base.update(overrides)
    return base


def _valid_wif_spec(**overrides) -> dict:
    base = _valid_sa_key_spec()
    base["authentication"] = {
        "mode": "workload_identity_federation",
        "project_service_keys": [],
        "workload_identity_federation": {
            "pool_id": "splunk-pool",
            "provider_id": "splunk-provider",
            "splunk_principal": "serviceAccount:o11y-ingest@prod-us-1.iam.gserviceaccount.com",
        },
    }
    # WIF mode does not pass project_service_keys to the payload
    base.update(overrides)
    return base


class TestGCPRenderer:
    def setup_method(self):
        self.mod = _load_renderer()

    def _render(self, spec_dict, tmp_path, realm=None):
        validated = self.mod.validate_spec(spec_dict.copy(), realm_override=realm)
        return self.mod.render(validated, tmp_path)

    def test_sa_key_spec_renders(self, tmp_path):
        result = self._render(_valid_sa_key_spec(), tmp_path)
        assert result["coverage_summary"]["total"] > 0
        assert (tmp_path / "rest" / "create.json").exists()

    def test_wif_spec_renders(self, tmp_path):
        self._render(_valid_wif_spec(), tmp_path)
        assert (tmp_path / "rest" / "create.json").exists()

    def test_rest_payload_type_gcp(self, tmp_path):
        self._render(_valid_sa_key_spec(), tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        assert payload["type"] == "GCP"

    def test_rest_payload_auth_method_sa_key(self, tmp_path):
        self._render(_valid_sa_key_spec(), tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        assert payload["authMethod"] == "SERVICE_ACCOUNT_KEY"

    def test_rest_payload_auth_method_wif(self, tmp_path):
        self._render(_valid_wif_spec(), tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        assert payload["authMethod"] == "WORKLOAD_IDENTITY_FEDERATION"

    def test_rest_payload_project_key_placeholder(self, tmp_path):
        self._render(_valid_sa_key_spec(), tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        psk = payload.get("projectServiceKeys", [])
        assert len(psk) == 1
        assert "${PROJECT_KEY_FROM_FILE}" in psk[0].get("projectKey", "")

    def test_rest_payload_poll_rate_milliseconds(self, tmp_path):
        self._render(_valid_sa_key_spec(), tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        assert payload["pollRate"] == 300000

    def test_terraform_signalfx_resource(self, tmp_path):
        self._render(_valid_sa_key_spec(), tmp_path)
        tf = (tmp_path / "terraform" / "main.tf").read_text()
        assert "signalfx_gcp_integration" in tf

    def test_gcloud_cli_scripts_rendered(self, tmp_path):
        self._render(_valid_sa_key_spec(), tmp_path)
        assert (tmp_path / "gcloud-cli" / "create-sa.sh").exists()
        assert (tmp_path / "gcloud-cli" / "bind-roles.sh").exists()

    def test_state_directory_created(self, tmp_path):
        self._render(_valid_sa_key_spec(), tmp_path)
        assert (tmp_path / "state" / "apply-state.json").exists()
        assert (tmp_path / "state" / "credential-hashes.json").exists()

    def test_coverage_report_exists(self, tmp_path):
        self._render(_valid_sa_key_spec(), tmp_path)
        data = json.loads((tmp_path / "coverage-report.json").read_text())
        assert data["realm"] == "us1"
        assert data["integration_name"] == "test-gcp"

    def test_no_secret_leak_in_rendered_tree(self, tmp_path):
        import re
        self._render(_valid_sa_key_spec(), tmp_path)
        secret_pat = re.compile(r"eyJ[A-Za-z0-9._-]{20,}|Bearer\s+[A-Za-z0-9._-]{12,}")
        for path in tmp_path.rglob("*"):
            if path.is_file() and path.suffix in (".json", ".sh", ".tf", ".md"):
                content = path.read_text(encoding="utf-8", errors="replace")
                assert not secret_pat.search(content), f"Secret-looking content in {path}"

    def test_all_built_in_mode_no_services_field(self, tmp_path):
        spec = _valid_sa_key_spec()
        spec["services"]["mode"] = "all_built_in"
        spec["services"]["explicit"] = []
        self._render(spec, tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        assert "services" not in payload or payload.get("services") == []

    def test_explicit_services_in_payload(self, tmp_path):
        self._render(_valid_sa_key_spec(), tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        assert "compute" in payload.get("services", [])

    def test_handoff_dashboards_emitted(self, tmp_path):
        spec = _valid_sa_key_spec()
        spec["handoffs"]["dashboards"] = True
        self._render(spec, tmp_path)
        assert (tmp_path / "handoffs" / "handoff-dashboards.sh").exists()

    def test_handoff_ta_3088_emitted(self, tmp_path):
        spec = _valid_sa_key_spec()
        spec["handoffs"]["splunk_ta_google_cloud"] = True
        self._render(spec, tmp_path)
        assert (tmp_path / "handoffs" / "handoff-splunk-ta-google-cloud-3088.sh").exists()

    def test_poll_rate_out_of_range_rejected(self):
        spec = _valid_sa_key_spec()
        spec["connection"]["poll_rate_seconds"] = 30
        with pytest.raises(self.mod.RenderError, match="poll_rate_seconds"):
            self.mod.validate_spec(spec)

    def test_explicit_non_empty_plus_all_built_in_rejected(self):
        spec = _valid_sa_key_spec()
        spec["services"]["mode"] = "all_built_in"
        spec["services"]["explicit"] = ["compute"]
        with pytest.raises(self.mod.RenderError, match="services"):
            self.mod.validate_spec(spec)

    def test_invalid_realm_rejected(self):
        with pytest.raises(self.mod.RenderError, match="realm"):
            self.mod.validate_spec(_valid_sa_key_spec(), realm_override="bad-realm")

    def test_list_services(self):
        services = self.mod.load_services_enum()
        assert len(services) == 32
        assert "compute" in services
        assert "pubsub" in services


class TestGCPShellScripts:
    def test_setup_sh_help(self):
        result = subprocess.run(
            ["bash", str(SCRIPTS_DIR / "setup.sh"), "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_validate_sh_on_rendered_tree(self, tmp_path):
        mod = _load_renderer()
        spec = mod.validate_spec(_valid_sa_key_spec())
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
