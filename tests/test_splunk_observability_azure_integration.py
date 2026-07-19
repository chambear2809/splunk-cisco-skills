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

import importlib.machinery
import importlib.util
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

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


def _load_api_client():
    spec = importlib.util.spec_from_file_location(
        "sazure_api", SCRIPTS_DIR / "azure_integration_api.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_private_text(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


def _azure_live(**overrides) -> dict:
    live = {
        "id": "azure-id-1",
        "type": "Azure",
        "name": "test-azure",
        "enabled": True,
        "tenantId": "tenant-1",
        "subscriptions": ["subscription-1"],
        "azureEnvironment": "AZURE",
        "services": ["microsoft.compute/virtualmachines"],
        "pollRate": 300000,
    }
    live.update(overrides)
    return live


def _azure_plan(
    api,
    tmp_path: Path,
    *,
    action: str = "disable",
    integration_name: str = "test-azure",
    expected_enabled_state: bool = True,
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    plan_path = tmp_path / f"azure-{action}-plan.json"
    observed_path = tmp_path / f"azure-{action}-observed.json"
    api.write_observed_snapshot(
        observed_path,
        realm="us1",
        integrations=[
            _azure_live(
                name=integration_name,
                enabled=expected_enabled_state,
            )
        ],
    )
    credential_args = {}
    if action == "disable":
        credential_args = {
            "app_id_file": str(
                _write_private_text(tmp_path / "app-id", "azure-app-id-secret")
            ),
            "secret_file": str(
                _write_private_text(tmp_path / "secret", "azure-secret-value")
            ),
        }
    rendered = api.render_rollback_plan(
        plan_path,
        realm="us1",
        action=action,
        integration_id="azure-id-1",
        integration_name=integration_name,
        expected_enabled_state=expected_enabled_state,
        observed_state_file=str(observed_path),
        **credential_args,
    )
    return plan_path, rendered["plan_hash"]


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

    def test_reference_distinguishes_read_and_mutation_tokens(self):
        reference = (SKILL_DIR / "reference.md").read_text(encoding="utf-8")
        assert "any session/User API access token" in reference
        assert "associated with an\n  administrator" in reference
        assert "administrator session/User API access token" not in reference

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


class TestAzureApiSecurity:
    def setup_method(self):
        self.api = _load_api_client()

    def test_provider_apply_state_imports_ignore_cached_aws_generic_module(self):
        aws_helper_path = (
            REPO_ROOT
            / "skills/splunk-observability-aws-integration/scripts/_apply_state.py"
        )
        gcp_api_path = (
            REPO_ROOT
            / "skills/splunk-observability-gcp-integration/scripts/gcp_integration_api.py"
        )
        azure_name = (
            "skills.splunk-observability-azure-integration.scripts._apply_state"
        )
        gcp_name = "skills.splunk-observability-gcp-integration.scripts._apply_state"
        saved_generic = sys.modules.get("_apply_state")
        saved_azure = sys.modules.get(azure_name)
        saved_gcp = sys.modules.get(gcp_name)
        try:
            aws_spec = importlib.util.spec_from_file_location(
                "_apply_state", aws_helper_path
            )
            assert aws_spec is not None and aws_spec.loader is not None
            aws_helper = importlib.util.module_from_spec(aws_spec)
            sys.modules["_apply_state"] = aws_helper
            aws_spec.loader.exec_module(aws_helper)
            assert not hasattr(aws_helper, "SecureDirectory")

            sys.modules.pop(azure_name, None)
            sys.modules.pop(gcp_name, None)
            azure_api = _load_api_client()
            gcp_spec = importlib.util.spec_from_file_location(
                "collision_gcp_api", gcp_api_path
            )
            assert gcp_spec is not None and gcp_spec.loader is not None
            gcp_api = importlib.util.module_from_spec(gcp_spec)
            gcp_spec.loader.exec_module(gcp_api)

            assert sys.modules["_apply_state"] is aws_helper
            assert Path(azure_api._apply_state.__file__).resolve() == (
                SCRIPTS_DIR / "_apply_state.py"
            ).resolve()
            assert Path(gcp_api._apply_state.__file__).resolve() == (
                gcp_api_path.with_name("_apply_state.py").resolve()
            )
            assert azure_api.SecureDirectory.__module__ == azure_name
            assert gcp_api.SecureDirectory.__module__ == gcp_name
            assert azure_api.SecureDirectory is not gcp_api.SecureDirectory
            assert azure_api.append_step is azure_api._apply_state.append_step
            assert gcp_api.append_step is gcp_api._apply_state.append_step
        finally:
            if saved_generic is None:
                sys.modules.pop("_apply_state", None)
            else:
                sys.modules["_apply_state"] = saved_generic
            if saved_azure is None:
                sys.modules.pop(azure_name, None)
            else:
                sys.modules[azure_name] = saved_azure
            if saved_gcp is None:
                sys.modules.pop(gcp_name, None)
            else:
                sys.modules[gcp_name] = saved_gcp

    def test_provider_apply_state_import_is_concurrency_safe(self, monkeypatch):
        helper_name = (
            "skills.splunk-observability-azure-integration.scripts._apply_state"
        )
        saved_helper = sys.modules.get(helper_name)
        original_exec_module = importlib.machinery.SourceFileLoader.exec_module
        helper_started = threading.Event()
        release_helper = threading.Event()
        premature_completion = threading.Event()
        worker_count = 24
        start = threading.Barrier(worker_count + 1)

        def blocking_exec_module(loader, module):
            if module.__name__ == helper_name:
                helper_started.set()
                assert release_helper.wait(10), "timed out releasing helper import"
            return original_exec_module(loader, module)

        def load_api(index):
            start.wait()
            try:
                spec = importlib.util.spec_from_file_location(
                    f"concurrent_azure_api_{index}",
                    SCRIPTS_DIR / "azure_integration_api.py",
                )
                assert spec is not None and spec.loader is not None
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module, module._apply_state, module.SecureDirectory
            finally:
                if not release_helper.is_set():
                    premature_completion.set()

        monkeypatch.setattr(
            importlib.machinery.SourceFileLoader,
            "exec_module",
            blocking_exec_module,
        )
        sys.modules.pop(helper_name, None)
        try:
            with ThreadPoolExecutor(max_workers=worker_count) as pool:
                futures = [pool.submit(load_api, index) for index in range(worker_count)]
                start.wait()
                try:
                    assert helper_started.wait(5), "helper import did not start"
                    assert not premature_completion.wait(0.5), (
                        "an API load observed a partially initialized helper"
                    )
                finally:
                    release_helper.set()
                results = [future.result(timeout=10) for future in futures]

            helpers = [result[1] for result in results]
            secure_directories = [result[2] for result in results]
            assert len({id(helper) for helper in helpers}) == 1
            assert len({id(value) for value in secure_directories}) == 1
            assert all(
                value is helper.SecureDirectory
                for _, helper, value in results
            )
        finally:
            release_helper.set()
            if saved_helper is None:
                sys.modules.pop(helper_name, None)
            else:
                sys.modules[helper_name] = saved_helper

    def test_provider_apply_state_import_does_not_invert_import_locks(self, tmp_path):
        helper_name = (
            "skills.splunk-observability-azure-integration.scripts._apply_state"
        )
        probe_name = "azure_import_overlap_probe"
        (tmp_path / f"{probe_name}.py").write_text("VALUE = 'ok'\n", encoding="utf-8")
        script = r"""
import importlib
import importlib._bootstrap as bootstrap
import importlib.util
import sys
import threading
import time

api_path, helper_name, probe_dir, probe_name = sys.argv[1:]
sys.path.insert(0, probe_dir)
sys.modules.pop(helper_name, None)
dataclasses_lock = bootstrap._get_module_lock("dataclasses")
dataclasses_lock.acquire()
sys.modules.pop("dataclasses", None)
loaded = []
errors = []

def load_api():
    try:
        spec = importlib.util.spec_from_file_location("azure_import_overlap_api", api_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("API spec unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        loaded.append(module)
    except BaseException as exc:
        errors.append(repr(exc))

worker = threading.Thread(target=load_api, daemon=True)
worker.start()
deadline = time.monotonic() + 5
while not bool(getattr(dataclasses_lock, "waiters", ())) and worker.is_alive():
    if time.monotonic() >= deadline:
        break
    time.sleep(0.005)
if not bool(getattr(dataclasses_lock, "waiters", ())):
    dataclasses_lock.release()
    worker.join(1)
    raise RuntimeError(f"helper did not wait on dataclasses: {errors!r}")
try:
    probe = importlib.import_module(probe_name)
    if probe.VALUE != "ok":
        raise RuntimeError("overlap probe import failed")
finally:
    dataclasses_lock.release()
worker.join(5)
if worker.is_alive():
    raise RuntimeError("provider helper import deadlocked")
if errors or len(loaded) != 1:
    raise RuntimeError(f"provider helper import failed: {errors!r}")
if loaded[0].SecureDirectory.__module__ != helper_name:
    raise RuntimeError("provider helper identity was not preserved")
"""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                str(SCRIPTS_DIR / "azure_integration_api.py"),
                helper_name,
                str(tmp_path),
                probe_name,
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_provider_apply_state_rejects_wrong_cached_origin(
        self, tmp_path, monkeypatch
    ):
        helper_name = (
            "skills.splunk-observability-azure-integration.scripts._apply_state"
        )
        wrong_path = tmp_path / "_apply_state.py"
        wrong_path.write_text("RAISED = False\n", encoding="utf-8")
        wrong_module = SimpleNamespace(
            __file__=str(wrong_path),
            __spec__=SimpleNamespace(origin=str(wrong_path)),
        )
        monkeypatch.setitem(sys.modules, helper_name, wrong_module)
        with pytest.raises(ImportError, match="wrong origin"):
            self.api._load_provider_apply_state()

    def test_direct_api_execution_finds_only_sibling_helper(self, tmp_path):
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "azure_integration_api.py"), "--help"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Traceback" not in result.stdout + result.stderr

    @pytest.fixture(autouse=True)
    def _isolate_account_lock_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            self.api, "_account_lock_root_path", lambda: tmp_path / "account-lock-root"
        )

    @pytest.mark.parametrize(
        "realm",
        (
            "us1@evil.example",
            "us1/path",
            "us1?x=1",
            "us1#fragment",
            "us1%2fevil",
            "us1%40evil",
            "us1%3fevil",
            "us1%23evil",
            "us1%20evil",
            "us1%09evil",
            "us1:443",
            "us1 evil",
        ),
    )
    def test_malicious_realm_precedes_token_and_transport(
        self, realm, tmp_path, monkeypatch
    ):
        token_read = Mock(side_effect=AssertionError("token read"))
        transport = Mock(side_effect=AssertionError("transport"))
        monkeypatch.setattr(self.api, "read_secret_file", token_read)
        monkeypatch.setattr(self.api, "_request", transport)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "azure_integration_api.py",
                "--realm",
                realm,
                "--token-file",
                str(tmp_path / "token"),
                "--state-dir",
                str(tmp_path / "state"),
                "list",
            ],
        )
        assert self.api.main() == 1
        assert token_read.call_count == 0
        assert transport.call_count == 0

    @pytest.mark.parametrize(
        "url",
        (
            "http://api.us1.observability.splunkcloud.com/v2/integration",
            "https://user@api.us1.observability.splunkcloud.com/v2/integration",
            "https://api.us1.observability.splunkcloud.com:443/v2/integration",
            "https://api.us1.observability.splunkcloud.com/v2/integration/extra/path",
            "https://api.us1.observability.splunkcloud.com/v2/integration#fragment",
            "https://api.us1.observability.splunkcloud.com/v2/integration?type=Azure&limit=1&offset=0&x=1",
            "https://api.us1.observability.splunkcloud.com/v2/integration%2fother",
            "https://api.us1.observability.splunkcloud.com/v2/integration%40other",
            "https://api.us1.observability.splunkcloud.com/v2/integration%3fother",
            "https://api.us1.observability.splunkcloud.com/v2/integration%23other",
            "https://api.us1.observability.splunkcloud.com/v2/integration%20other",
            "https://api.us1.observability.splunkcloud.com/v2/integration%09other",
        ),
    )
    def test_final_destination_rejects_unreviewed_urls(self, url):
        with pytest.raises(self.api.ApiError):
            self.api._validate_api_url(url)

    def test_redirect_handler_refuses_redirects(self):
        handler = self.api._NoRedirectHandler()
        assert handler.redirect_request(None, None, 302, "moved", {}, "https://evil") is None

    @pytest.mark.parametrize(
        "raw,expected",
        (("-5", 1), ("1000000", 10), ("not-an-int", 4)),
    )
    def test_get_retry_environment_is_bounded(self, raw, expected, monkeypatch):
        monkeypatch.setenv("O11Y_MAX_RETRIES", raw)
        assert self.api._max_retries() == expected

    @pytest.mark.parametrize(
        "header,expected",
        (("999999", 30.0), ("-1", 1.0), ("NaN", 1.0), ("Infinity", 1.0)),
    )
    def test_retry_after_is_finite_nonnegative_and_capped(
        self, header, expected, monkeypatch
    ):
        monkeypatch.setattr(self.api.random, "random", lambda: 0.0)
        error = self.api.HTTPError(
            "https://api.us1.observability.splunkcloud.com/v2/integration",
            429,
            "retry",
            {"Retry-After": header},
            None,
        )
        assert self.api._retry_after(error, 0) == expected

    @pytest.mark.parametrize("method", ("PUT", "DELETE"))
    def test_transport_mutations_attempt_exactly_once(self, method, monkeypatch):
        opener = Mock()
        opener.open.side_effect = self.api.HTTPError(
            "https://api.us1.observability.splunkcloud.com/v2/integration/azure-id-1",
            503,
            "unavailable",
            {"Retry-After": "999999"},
            None,
        )
        sleep = Mock()
        monkeypatch.setattr(self.api, "build_opener", lambda *_: opener)
        monkeypatch.setattr(self.api.time, "sleep", sleep)
        with pytest.raises(self.api.ApiError, match="HTTP 503"):
            self.api._request(
                method,
                "https://api.us1.observability.splunkcloud.com/v2/integration/azure-id-1",
                "unused",
                {"enabled": False} if method == "PUT" else None,
            )
        assert opener.open.call_count == 1
        assert sleep.call_count == 0

    def test_transport_get_retries_only_to_reviewed_bound(self, monkeypatch):
        opener = Mock()
        opener.open.side_effect = self.api.HTTPError(
            "https://api.us1.observability.splunkcloud.com/v2/integration",
            503,
            "unavailable",
            {"Retry-After": "0"},
            None,
        )
        sleep = Mock()
        monkeypatch.setattr(self.api, "build_opener", lambda *_: opener)
        monkeypatch.setattr(self.api, "_max_retries", lambda: 3)
        monkeypatch.setattr(self.api.time, "sleep", sleep)
        with pytest.raises(self.api.ApiError, match="HTTP 503"):
            self.api._request(
                "GET",
                "https://api.us1.observability.splunkcloud.com/v2/integration"
                "?type=Azure&limit=1&offset=0",
                "unused",
            )
        assert opener.open.call_count == 3
        assert sleep.call_count == 2

    @pytest.mark.parametrize(
        "failure",
        (TimeoutError("read timed out"),),
    )
    def test_mutation_response_read_timeout_is_ambiguous_once(
        self, failure, monkeypatch
    ):
        response = Mock(status=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.side_effect = failure
        opener = Mock()
        opener.open.return_value = response
        monkeypatch.setattr(self.api, "build_opener", lambda *_: opener)
        with pytest.raises(self.api.AmbiguousMutationError, match="ambiguous"):
            self.api._request(
                "PUT",
                "https://api.us1.observability.splunkcloud.com/v2/integration/azure-id-1",
                "unused",
                {"enabled": True},
            )
        assert opener.open.call_count == 1

    def test_mutation_incomplete_read_is_ambiguous_once(self, monkeypatch):
        response = Mock(status=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.side_effect = self.api.http.client.IncompleteRead(b'{"id":', 12)
        opener = Mock()
        opener.open.return_value = response
        monkeypatch.setattr(self.api, "build_opener", lambda *_: opener)
        with pytest.raises(self.api.AmbiguousMutationError, match="ambiguous"):
            self.api._request(
                "DELETE",
                "https://api.us1.observability.splunkcloud.com/v2/integration/azure-id-1",
                "unused",
            )
        assert opener.open.call_count == 1

    def test_unserializable_mutation_payload_fails_before_dispatch(self, monkeypatch):
        opener_factory = Mock()
        monkeypatch.setattr(self.api, "build_opener", opener_factory)
        with pytest.raises(self.api.ApiError, match="strict UTF-8 JSON") as exc_info:
            self.api._request(
                "PUT",
                "https://api.us1.observability.splunkcloud.com/v2/integration/azure-id-1",
                "unused",
                {"enabled": True, "bad": object(), "secretKey": "CANARY"},
            )
        assert not isinstance(exc_info.value, self.api.AmbiguousMutationError)
        assert "CANARY" not in str(exc_info.value)
        assert opener_factory.call_count == 0

    def test_cli_handles_unserializable_payload_without_traceback_or_dispatch(
        self, tmp_path, monkeypatch, capsys
    ):
        opener_factory = Mock()
        monkeypatch.setattr(self.api, "build_opener", opener_factory)
        monkeypatch.setattr(self.api, "read_secret_file", lambda *_args, **_kwargs: "unused")
        monkeypatch.setattr(self.api, "_load_payload_file", lambda *_: {"enabled": True})

        def fail_before_dispatch(*_args, **_kwargs):
            return self.api._request(
                "POST",
                "https://api.us1.observability.splunkcloud.com/v2/integration",
                "unused",
                {"bad": object(), "secretKey": "CLI-CANARY"},
            )

        monkeypatch.setattr(self.api, "upsert", fail_before_dispatch)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "azure_integration_api.py",
                "--realm", "us1",
                "--token-file", str(tmp_path / "token"),
                "--state-dir", str(tmp_path / "state"),
                "--payload-file", str(tmp_path / "payload.json"),
                "--app-id-file", str(tmp_path / "app-id"),
                "--secret-file", str(tmp_path / "secret"),
                "upsert",
            ],
        )
        assert self.api.main() == 1
        output = capsys.readouterr()
        combined = output.out + output.err
        assert "strict UTF-8 JSON" in combined
        assert "CLI-CANARY" not in combined
        assert "Traceback" not in combined
        assert opener_factory.call_count == 0

    @pytest.mark.parametrize("method", ("GET", "PUT"))
    def test_http_204_is_never_a_successful_empty_get(self, method, monkeypatch):
        response = Mock(status=204)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        monkeypatch.setattr(self.api, "build_opener", lambda *_: opener)
        error = self.api.AmbiguousMutationError if method == "PUT" else self.api.ApiError
        with pytest.raises(error, match="HTTP 204"):
            self.api._request(
                method,
                "https://api.us1.observability.splunkcloud.com/v2/integration/azure-id-1",
                "unused",
                {"enabled": True} if method == "PUT" else None,
            )
        assert opener.open.call_count == 1

    @pytest.mark.parametrize("body", (b"{}", b" "))
    def test_delete_accepts_only_a_zero_byte_http_200_body(self, body, monkeypatch):
        response = Mock(status=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = body
        opener = Mock()
        opener.open.return_value = response
        monkeypatch.setattr(self.api, "build_opener", lambda *_: opener)
        with pytest.raises(self.api.AmbiguousMutationError, match="contained a body"):
            self.api._request(
                "DELETE",
                "https://api.us1.observability.splunkcloud.com/v2/integration/azure-id-1",
                "unused",
            )
        assert opener.open.call_count == 1

        response.read.return_value = b""
        assert self.api._request(
            "DELETE",
            "https://api.us1.observability.splunkcloud.com/v2/integration/azure-id-1",
            "unused",
        ) == {}
        assert self.api._request(
            "GET",
            "https://api.us1.observability.splunkcloud.com/v2/integration/azure-id-1",
            "unused",
        ) == {}

    @pytest.mark.parametrize(
        "body,error",
        (
            (b'{"id":"one","id":"two"}', "duplicate JSON object key"),
            (b'{"value":NaN}', "non-standard JSON constant"),
            (b'{"value":Infinity}', "non-standard JSON constant"),
        ),
    )
    def test_successful_api_bodies_use_strict_json(self, body, error, monkeypatch):
        response = Mock(status=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = body
        opener = Mock()
        opener.open.return_value = response
        monkeypatch.setattr(self.api, "build_opener", lambda *_: opener)
        with pytest.raises(self.api.ApiError, match=error):
            self.api._request(
                "GET",
                "https://api.us1.observability.splunkcloud.com/v2/integration/azure-id-1",
                "unused",
            )

    def test_redaction_covers_unknown_key_canaries_but_preserves_identifiers(self):
        unsafe_assignment_key = "client_secret=AZURE-DICT-KEY-CANARY"
        unsafe_jwt_key = "e30.e30.QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo"
        unsafe_digest_jwt_key = unsafe_jwt_key
        nested_unicode_key = (
            "refresh_t\\u005cu006fken=AZURE-NESTED-DICT-KEY-CANARY"
        )
        canaries = {
            "accessKeyId": "ACCESS-CANARY",
            "privateKey": "PRIVATE-CANARY",
            "private_key_id": "PRIVATE-ID-CANARY",
            "credentials": {"value": "CREDENTIALS-CANARY"},
            "projectKey": "PROJECT-CANARY",
            "clientKey": "CLIENT-CANARY",
            "client_secret": "CLIENT-SECRET-CANARY",
            "refresh_token": "REFRESH-TOKEN-CANARY",
            "api_token": "API-TOKEN-CANARY",
            "authorization": "AUTHORIZATION-CANARY",
        }
        value = {
            "nested": canaries,
            "idempotency_key": "operation-identifier",
            "plan_sha256": "a" * 64,
            "reviewed_state_sha256": "b" * 64,
            "app_id_sha256": "c" * 64,
            "valid_internal": {"secret_key_sha256": "d" * 64},
            "invalid_internal": {
                "secret_key_sha256": "sk_live_INVALID-INTERNAL-CANARY"
            },
            "client_secret_sha256": "sk_live_CLIENT-SHA-CANARY",
            "private_key_sha256": "sk_live_PRIVATE-SHA-CANARY",
            "credential_sha256": "sk_live-CREDENTIAL-SHA-CANARY",
            "unknown_sha256": "sk_live-UNKNOWN-SHA-CANARY",
            "unsafe_key_container": {
                unsafe_assignment_key: "ordinary value",
                unsafe_jwt_key: "AZURE-JWT-DICT-VALUE-CANARY",
                nested_unicode_key: "ordinary value",
            },
            "invalid_digest_maps": {
                "project_key_sha256": {
                    "/tmp/client_secret=AZURE-DIGEST-PATH-CANARY": "e" * 64
                },
                "wif_config_sha256": {unsafe_digest_jwt_key: "f" * 64},
            },
            "safe_digest_maps": {
                "project_key_sha256": {
                    "/secure/project-key-secret.json": "e" * 64
                },
                "wif_config_sha256": {
                    "/tmp/client-secret-material.json": "f" * 64
                },
            },
            "nested_escape_digest_maps": {
                "project_key_sha256": {
                    "/tmp/client_secr\\u005cu0065t=AZURE-NESTED-DIGEST-KEY-CANARY": "a"
                    * 64
                },
            },
        }
        redacted = self.api.redact(value)
        serialized = json.dumps(redacted)
        assert not any(secret in serialized for secret in (
            "ACCESS-CANARY",
            "PRIVATE-CANARY",
            "PRIVATE-ID-CANARY",
            "CREDENTIALS-CANARY",
            "PROJECT-CANARY",
            "CLIENT-CANARY",
            "CLIENT-SECRET-CANARY",
            "REFRESH-TOKEN-CANARY",
            "API-TOKEN-CANARY",
            "AUTHORIZATION-CANARY",
            "INVALID-INTERNAL-CANARY",
            "CLIENT-SHA-CANARY",
            "PRIVATE-SHA-CANARY",
            "CREDENTIAL-SHA-CANARY",
            "UNKNOWN-SHA-CANARY",
            "AZURE-DICT-KEY-CANARY",
            "AZURE-JWT-DICT-VALUE-CANARY",
            "AZURE-DIGEST-PATH-CANARY",
            unsafe_jwt_key,
            "AZURE-NESTED-DICT-KEY-CANARY",
            "AZURE-NESTED-DIGEST-KEY-CANARY",
        ))
        assert redacted["idempotency_key"] == "operation-identifier"
        assert redacted["plan_sha256"] == "a" * 64
        assert redacted["reviewed_state_sha256"] == "b" * 64
        assert redacted["app_id_sha256"] == "c" * 64
        assert redacted["valid_internal"]["secret_key_sha256"] == "d" * 64
        assert redacted["invalid_internal"]["secret_key_sha256"] == "[REDACTED]"
        assert redacted["client_secret_sha256"] == "[REDACTED]"
        assert redacted["private_key_sha256"] == "[REDACTED]"
        assert redacted["credential_sha256"] == "[REDACTED]"
        assert redacted["unknown_sha256"] == "[REDACTED]"
        assert redacted["unsafe_key_container"] == {}
        assert redacted["invalid_digest_maps"]["project_key_sha256"] == "[REDACTED]"
        assert redacted["invalid_digest_maps"]["wif_config_sha256"] == "[REDACTED]"
        assert redacted["safe_digest_maps"]["project_key_sha256"] == {
            "/secure/project-key-secret.json": "e" * 64
        }
        assert redacted["safe_digest_maps"]["wif_config_sha256"] == {
            "/tmp/client-secret-material.json": "f" * 64
        }
        assert (
            redacted["nested_escape_digest_maps"]["project_key_sha256"]
            == "[REDACTED]"
        )

    @pytest.mark.parametrize(
        "value,canary",
        (
            ("password=alpha beta", "alpha beta"),
            ('credentials: "quoted alpha beta"', "quoted alpha beta"),
            ("private_key: line one line two", "line one line two"),
            ("accessKeyId=access alpha beta", "access alpha beta"),
            ("client_secret=client alpha beta", "client alpha beta"),
            ("refresh_token=refresh alpha beta", "refresh alpha beta"),
            ("api_token=api alpha beta", "api alpha beta"),
            ("refreshToken=camel refresh alpha", "camel refresh alpha"),
            ("apiToken=camel api alpha", "camel api alpha"),
            ("authorization=auth alpha beta", "auth alpha beta"),
            ("private_key_id=private id alpha", "private id alpha"),
            ('{"refresh_token":"json refresh alpha"}', "json refresh alpha"),
            ("{'apiToken': 'yaml api alpha'}", "yaml api alpha"),
            ('{"refreshToken":"camel json alpha"}', "camel json alpha"),
        ),
    )
    def test_free_form_redaction_consumes_multiword_secret_tails(self, value, canary):
        assert canary not in self.api.redact(value)

    def test_redaction_inspection_closes_unicode_auth_and_assignment_bypasses(self):
        unsafe_values = (
            "pass\u200bword=AZURE-ZWSP-CANARY",
            "pa\u034fssword=AZURE-CGJ-CANARY",
            "pass\u00adword=AZURE-SOFT-HYPHEN-CANARY",
            "to\u200bken=AZURE-TOKEN-SPLIT-CANARY",
            "ｃｌｉｅｎｔ＿ｓｅｃｒｅｔ=AZURE-NFKC-CANARY",
            "paſſword=AZURE-LONG-S-CANARY",
            "refresh_to\u200bken: AZURE-YAML-ZWSP-CANARY",
            "client.secret: AZURE-DOT-KEY-CANARY",
            "api/token: AZURE-SLASH-KEY-CANARY",
            "private key: AZURE-PRIVATE-SPACE-CANARY",
            "api key: AZURE-API-SPACE-CANARY",
            "access key: AZURE-ACCESS-SPACE-CANARY",
            "project key: AZURE-PROJECT-SPACE-CANARY",
            "client key: AZURE-CLIENT-SPACE-CANARY",
            "secret key: AZURE-SECRET-SPACE-CANARY",
            "client_secret(foo)=AZURE-PAREN-CANARY",
            "[password]=AZURE-BRACKET-CANARY",
            "client_secret" + "x" * 300 + "=AZURE-LONG-KEY-CANARY",
            "plan_sha256=AZURE-PLAN-DIGEST-CANARY",
            "app_id_sha256: AZURE-APP-DIGEST-CANARY",
            "secret_key_sha256=AZURE-SECRET-DIGEST-CANARY",
            "project_key_sha256: AZURE-PROJECT-DIGEST-CANARY",
            "wif_config_sha256=AZURE-WIF-DIGEST-CANARY",
            "reviewed_state_sha256=AZURE-REVIEWED-DIGEST-CANARY",
            "Basic dTpw",
            "Bearer abc",
            "e30.e30.QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo",
            r'{"refresh_t\\u005cu006fken":"AZURE-NESTED-JSON-KEY-CANARY"}',
            r'"refresh_t\u005cu006fken": AZURE-NESTED-YAML-KEY-CANARY',
            r'"refresh_t\x6fken": AZURE-X-KEY-CANARY',
            r'"refresh_t\U0000006fken": AZURE-U-KEY-CANARY',
            r'{"pass\ud800word":"AZURE-SURROGATE-JSON-CANARY"}',
            r'{"refresh_t\u000Aoken":"AZURE-ESCAPED-NEWLINE-JSON-CANARY",}',
            r'"refresh_t\u000Aoken": AZURE-ESCAPED-NEWLINE-YAML-CANARY',
            r'{"refresh_t\u003Aoken":"AZURE-ESCAPED-COLON-JSON-CANARY",}',
            r'"refresh_t\u003Aoken": AZURE-ESCAPED-COLON-YAML-CANARY',
            r'{"refresh_t\u003Doken":"AZURE-ESCAPED-EQUAL-JSON-CANARY",}',
            r'"refresh_t\u003Doken": AZURE-ESCAPED-EQUAL-YAML-CANARY',
        )
        assert all(self.api.redact(value) == "[REDACTED]" for value in unsafe_values)

        unsafe_keys = (
            "ｐａｓｓｗｏｒｄ",
            "refresh_t\\u005cu006fken",
            "pass\u200bword",
            "pa\u034fssword",
            "pass\u00adword",
            "to\u200bken",
            "pass\ud800word",
        )
        assert all(
            "AZURE-KEY-CANARY" not in json.dumps(self.api.redact({key: "AZURE-KEY-CANARY"}))
            for key in unsafe_keys
        )

        unsafe_mapping_keys = (
            "/tmp/ｃｌｉｅｎｔ＿ｓｅｃｒｅｔ=AZURE-MAP-NFKC-CANARY",
            "/tmp/pass\u200bword=AZURE-MAP-ZWSP-CANARY",
            "/tmp/pa\u034fssword=AZURE-MAP-CGJ-CANARY",
            "/tmp/pass\u00adword=AZURE-MAP-SOFT-HYPHEN-CANARY",
            "/tmp/to\u200bken=AZURE-MAP-TOKEN-CANARY",
            "/tmp/client_secret(foo)=AZURE-MAP-PAREN-CANARY",
            "/tmp/[password]=AZURE-MAP-BRACKET-CANARY",
            "/tmp/client_secret" + "x" * 300 + "=AZURE-MAP-LONG-CANARY",
            "refresh_t\\u005cu006fken",
            "e30.e30.QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo",
        )
        for key in unsafe_mapping_keys:
            assert self.api.redact(
                {"project_key_sha256": {key: "a" * 64}}
            )["project_key_sha256"] == "[REDACTED]"

        safe_strings = (
            "/secure/project-key-secret.json",
            "/tmp/client-secret-material.json",
            "secret-manager-prod",
            "client-key-material.json",
            r"C:\logs\refresh_token_report.txt",
            "cafe\u0301 diagnostic healthy",
            "status\u200bhealthy",
            r"ordinary safe \\ backslash text",
            "release.v1.abcdefghijklmnop",
            "api.example.abcdefghijklmnop",
            "version.12.1234567890abcdef",
            "not-a-jwt.value.ordinary-diagnostic",
            "status: healthy\npath: /tmp/client-secret-material.json",
            r'"ordinary\u000Afield": healthy',
            r'"ordinary\u003Afield": healthy',
            r'"ordinary\u003Dfield": healthy',
        )
        assert all(self.api.redact(value) == value for value in safe_strings)
        reviewed_states = [
            self.api._project_live_reviewed_state(_azure_live(namedToken=value))
            for value in safe_strings[-8:]
        ]
        assert [state["namedToken"] for state in reviewed_states] == list(
            safe_strings[-8:]
        )
        assert len(
            {self.api._reviewed_state_sha256(state) for state in reviewed_states}
        ) == len(reviewed_states)
        assert self.api.redact(
            {
                "project_key_sha256": {
                    "secret-manager-prod": "b" * 64,
                    "client-key-material.json": "c" * 64,
                }
            }
        )["project_key_sha256"] == {
            "secret-manager-prod": "b" * 64,
            "client-key-material.json": "c" * 64,
        }
        assert self.api.redact(
            ("ordinary tuple value", "password=AZURE-TUPLE-CANARY")
        ) == ["ordinary tuple value", "[REDACTED]"]

    def test_output_dlp_and_journal_scrub_malicious_corpus(
        self, tmp_path, capsys
    ):
        corpus = {
            "details": [
                r'{"refresh_t\u000Aoken":"AZURE-NEWLINE-CANARY",}',
                r'"refresh_t\u003Aoken": AZURE-COLON-CANARY',
                r'"refresh_t\u003Doken": AZURE-EQUAL-CANARY',
                r'"refresh_t\noken": AZURE-SHORT-N-CANARY',
                r'"refresh_t\roken": AZURE-SHORT-R-CANARY',
                r'"refresh_t\boken": AZURE-SHORT-B-CANARY',
                r'"refresh_t\foken": AZURE-SHORT-F-CANARY',
                "authorization: Bearer abc",
                "Basic dTpw",
                "e30.e30.QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo",
                (
                    "-----BEGIN RSA PRIVATE KEY-----\n"
                    "AZURE-PEM-CANARY\n"
                    "-----END RSA PRIVATE KEY-----"
                ),
            ],
            "client_secret=AZURE-UNSAFE-DICT-KEY-CANARY": "ordinary",
            "safe": [
                r"token rotation completed\nstatus: healthy",
                "token rotation completed\nstatus: healthy",
                r"namedToken: production\nstatus: healthy",
                "namedToken: production\nstatus: healthy",
                r"C:\\logs\\refresh_token_report.txt\nstatus: healthy",
                "C:\\logs\\refresh_token_report.txt\nstatus: healthy",
                r"message: token rotation completed\nstatus: healthy",
                "message: token rotation completed\nstatus: healthy",
            ],
        }
        redacted = self.api.redact(corpus)
        state_dir = tmp_path / "state"
        self.api.append_step(
            state_dir,
            "test",
            "output-dlp",
            "azure-output-dlp",
            "failed",
            corpus,
        )
        print(json.dumps(redacted))
        print(json.dumps(redacted), file=sys.stderr)
        captured = capsys.readouterr()
        journal = (state_dir / "apply-state.json").read_text()
        combined = journal + captured.out + captured.err
        for canary in (
            "AZURE-NEWLINE-CANARY",
            "AZURE-COLON-CANARY",
            "AZURE-EQUAL-CANARY",
            "AZURE-SHORT-N-CANARY",
            "AZURE-SHORT-R-CANARY",
            "AZURE-SHORT-B-CANARY",
            "AZURE-SHORT-F-CANARY",
            "AZURE-UNSAFE-DICT-KEY-CANARY",
            "AZURE-PEM-CANARY",
            "Bearer abc",
            "Basic dTpw",
            "e30.e30.QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo",
        ):
            assert canary not in combined
        assert redacted["safe"] == corpus["safe"]
        stored = json.loads(journal)["steps"][-1]["response"]
        assert stored["safe"] == corpus["safe"]

    def test_bounded_quoted_embedded_auth_and_jws_dlp_surfaces(
        self, tmp_path, capsys
    ):
        signature = "MDEyMzQ1Njc4OWFiY2RlZg"
        jws_header = "eyJhbGciOiJIUzI1NiJ9"
        unencoded_header = (
            "eyJhbGciOiJIUzI1NiIsImI2NCI6ZmFsc2UsImNyaXQiOlsiYjY0Il19"
        )
        quoted = [
            '"' + "a" * size + "refresh_t" + escape + 'oken": ' + canary
            for size in (4082, 4083)
            for escape, canary in (
                (r"\n", f"AZURE-LONG-N-{size}-CANARY"),
                (r"\r", f"AZURE-LONG-R-{size}-CANARY"),
                ("\n", f"AZURE-LONG-LF-{size}-CANARY"),
            )
        ]
        unsafe = quoted + [
            "request failed with Basic dTpw during retry",
            "request failed with Bearer " + "A" * 24 + " during retry",
            f"{jws_header}.aGVsbG8.{signature}",
            f"{jws_header}..{signature}",
            f"{unencoded_header}.hello.{signature}",
        ]
        safe = [
            "Basic authentication enabled",
            "Bearer authentication enabled",
            "release.v1.abcdefghijklmnop",
        ]
        payload = {"unsafe": unsafe, "safe": safe}
        redacted = self.api.redact(payload)
        state_dir = tmp_path / "state"
        self.api.append_step(
            state_dir,
            "test",
            "bounded-output-dlp",
            "azure-bounded-output-dlp",
            "failed",
            payload,
        )
        print(json.dumps(redacted))
        print(json.dumps(redacted), file=sys.stderr)
        captured = capsys.readouterr()
        journal = (state_dir / "apply-state.json").read_text()
        combined = json.dumps(redacted) + journal + captured.out + captured.err
        for secret in unsafe:
            assert secret not in combined
        for marker in ("AZURE-LONG-N", "AZURE-LONG-R", "AZURE-LONG-LF"):
            assert marker not in combined
        assert redacted["safe"] == safe
        assert json.loads(journal)["steps"][-1]["response"]["safe"] == safe

    @pytest.mark.parametrize(
        "unsafe",
        (
            '"' + "a" * 4083 + r"refresh_t\noken" + '": AZURE-ARTIFACT-LONG',
            "request failed with Basic dTpw during AZURE-ARTIFACT-BASIC",
            "request failed with Bearer " + "A" * 24 + " AZURE-ARTIFACT-BEARER",
            "eyJhbGciOiJIUzI1NiJ9.aGVsbG8.MDEyMzQ1Njc4OWFiY2RlZg",
            "eyJhbGciOiJIUzI1NiJ9..MDEyMzQ1Njc4OWFiY2RlZg",
            (
                "eyJhbGciOiJIUzI1NiIsImI2NCI6ZmFsc2UsImNyaXQiOlsiYjY0Il19."
                "hello.MDEyMzQ1Njc4OWFiY2RlZg"
            ),
        ),
    )
    def test_new_dlp_classes_fail_semantic_snapshot_before_artifacts(
        self, unsafe, tmp_path, capsys
    ):
        snapshot_path = tmp_path / "observed.json"
        plan_path = tmp_path / "plan.json"
        with pytest.raises(self.api.ApiError):
            self.api.write_observed_snapshot(
                snapshot_path,
                realm="us1",
                integrations=[_azure_live(namedToken=unsafe)],
            )
        captured = capsys.readouterr()
        assert not snapshot_path.exists()
        assert not plan_path.exists()
        assert "ARTIFACT" not in captured.out + captured.err

    def test_known_schema_discover_plan_and_journal_are_exact_and_secret_free(
        self, tmp_path, monkeypatch, capsys
    ):
        live = _azure_live(
            name="token=production",
            useBatchApi=True,
            importAzureMonitor=True,
            syncGuestOsNamespaces=False,
            additionalServices=["microsoft.storage/storageaccounts"],
            customNamespacesPerService={
                "microsoft.compute/virtualmachines": ["custom.namespace"]
            },
            resourceFilterRules=[
                {"filter": {"source": "token bucket rate=100"}}
            ],
            namedToken=r"token rotation completed\nstatus: healthy",
            created=1712345678,
            lastUpdated=1712345688,
            creator="creator-id",
            lastUpdatedBy="updater-id",
            lastUpdatedByName="Updater",
            createdByName="Creator",
        )
        expected = self.api._project_live_reviewed_state(live)
        assert "appId" not in expected
        assert "secretKey" not in expected
        assert expected["name"] == "token=production"
        assert expected["resourceFilterRules"] == live["resourceFilterRules"]

        monkeypatch.setattr(
            self.api, "list_azure_integrations", Mock(return_value=[live])
        )
        state_dir = tmp_path / "state"
        snapshot_path = state_dir / "observed.json"
        snapshot = self.api.discover(
            "us1", "unused", snapshot_path, state_dir
        )
        plan_path = state_dir / "delete-plan.json"
        rendered = self.api.render_rollback_plan(
            plan_path,
            realm="us1",
            action="delete",
            integration_id="azure-id-1",
            integration_name="token=production",
            expected_enabled_state=True,
            observed_state_file=str(snapshot_path),
        )
        self.api.append_step(
            state_dir,
            "test",
            "known-schema",
            "azure-known-schema",
            "success",
            snapshot,
        )
        print(json.dumps(snapshot))
        print(json.dumps(rendered), file=sys.stderr)
        captured = capsys.readouterr()

        assert snapshot["results"] == [expected]
        assert rendered["plan"]["reviewed_state"] == expected
        assert rendered["plan"]["reviewed_state_sha256"] == (
            self.api._reviewed_state_sha256(expected)
        )
        combined = "\n".join(
            (
                json.dumps(snapshot),
                snapshot_path.read_text(),
                json.dumps(rendered),
                plan_path.read_text(),
                (state_dir / "apply-state.json").read_text(),
                captured.out,
                captured.err,
            )
        )
        assert "AZURE-APP-OBSERVED-CANARY" not in combined
        assert "AZURE-SECRET-OBSERVED-CANARY" not in combined
        assert "token=production" in combined

    @pytest.mark.parametrize(
        "case",
        ("unknown-root", "unknown-filter", "suspicious", "response-credential"),
    )
    def test_discover_rejects_unknown_or_suspicious_state_without_artifacts(
        self, case, tmp_path, monkeypatch
    ):
        if case == "unknown-root":
            live = _azure_live(details={"status": "healthy"})
        elif case == "unknown-filter":
            live = _azure_live(
                resourceFilterRules=[
                    {"filter": {"source": "status=healthy", "unknown": True}}
                ]
            )
        elif case == "suspicious":
            live = _azure_live(namedToken="Bearer abc")
        else:
            live = _azure_live(secretKey="AZURE-RESPONSE-CREDENTIAL-CANARY")
        monkeypatch.setattr(
            self.api, "list_azure_integrations", Mock(return_value=[live])
        )
        state_dir = tmp_path / "state"
        snapshot_path = state_dir / "observed.json"
        with pytest.raises(self.api.ApiError):
            self.api.discover("us1", "unused", snapshot_path, state_dir)
        assert not snapshot_path.exists()
        assert not (state_dir / "apply-state.json").exists()

    def test_reviewed_projection_never_calls_output_redactor(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            self.api,
            "redact",
            lambda *_args, **_kwargs: pytest.fail("output redactor was called"),
        )
        first = self.api._project_live_reviewed_state(
            _azure_live(namedToken="ordinary state A")
        )
        second = self.api._project_live_reviewed_state(
            _azure_live(namedToken="ordinary state B")
        )
        assert self.api._reviewed_state_sha256(first) != (
            self.api._reviewed_state_sha256(second)
        )

    @pytest.mark.parametrize(
        "override",
        (
            {"created": True},
            {"lastUpdated": "1712345678"},
            {"creator": None},
            {"lastUpdatedBy": 7},
            {"createdByName": []},
            {"lastUpdatedByName": 7},
            {"resourceFilterRules": ["not-an-object"]},
            {"resourceFilterRules": [{"filter": "not-an-object"}]},
            {"resourceFilterRules": [{"filter": {"source": 7}}]},
        ),
    )
    def test_reviewed_response_common_and_filter_shapes_are_exact(
        self, override
    ):
        with pytest.raises(self.api.ApiError, match="response schema mismatch"):
            self.api._project_live_reviewed_state(_azure_live(**override))
        valid = self.api._project_live_reviewed_state(
            _azure_live(createdByName=None, lastUpdatedByName=None)
        )
        assert valid["createdByName"] is None
        assert valid["lastUpdatedByName"] is None

    @pytest.mark.parametrize(
        "override",
        (
            {"azureEnvironment": "FUTURE_AZURE"},
            {"pollRate": 59_999},
            {"pollRate": 600_001},
        ),
    )
    def test_disable_rejects_unsupported_environment_or_poll_but_delete_reviews_it(
        self, override, tmp_path
    ):
        snapshot_path = tmp_path / "observed.json"
        self.api.write_observed_snapshot(
            snapshot_path,
            realm="us1",
            integrations=[_azure_live(**override)],
        )
        app_id = _write_private_text(tmp_path / "app-id", "app")
        secret = _write_private_text(tmp_path / "secret", "secret")
        disable_path = tmp_path / "disable.json"
        with pytest.raises(self.api.ApiError, match="Azure disable requires"):
            self.api.render_rollback_plan(
                disable_path,
                realm="us1",
                action="disable",
                integration_id="azure-id-1",
                integration_name="test-azure",
                expected_enabled_state=True,
                observed_state_file=str(snapshot_path),
                app_id_file=str(app_id),
                secret_file=str(secret),
            )
        assert not disable_path.exists()
        rendered = self.api.render_rollback_plan(
            tmp_path / "delete.json",
            realm="us1",
            action="delete",
            integration_id="azure-id-1",
            integration_name="test-azure",
            expected_enabled_state=True,
            observed_state_file=str(snapshot_path),
        )
        assert rendered["plan"]["action"] == "delete"

    def test_reinjected_azure_credentials_reach_the_single_put_body(
        self, monkeypatch
    ):
        response = Mock(status=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"id":"azure-id-1"}'
        opener = Mock()
        opener.open.return_value = response
        monkeypatch.setattr(self.api, "build_opener", lambda *_: opener)
        payload = _azure_live(
            enabled=False,
            appId="AZURE-APP-BODY-CANARY",
            secretKey="AZURE-SECRET-BODY-CANARY",
        )
        self.api.update_integration(
            "us1",
            "unused",
            "azure-id-1",
            payload,
            _capability=self.api._ROLLBACK_CAPABILITY,
        )
        sent = json.loads(opener.open.call_args.args[0].data.decode("utf-8"))
        assert sent["appId"] == "AZURE-APP-BODY-CANARY"
        assert sent["secretKey"] == "AZURE-SECRET-BODY-CANARY"
        assert "CANARY" not in json.dumps(self.api.redact(payload))

    def test_named_token_and_ordinary_config_remain_in_semantic_fingerprints(self):
        assert self.api._configuration_fingerprint(
            _azure_live(namedToken="token-name-a"),
            source=self.api._ReviewedStateSource.LIVE_RESPONSE,
        ) != self.api._configuration_fingerprint(
            _azure_live(namedToken="token-name-b"),
            source=self.api._ReviewedStateSource.LIVE_RESPONSE,
        )
        assert self.api._configuration_fingerprint(
            _azure_live(resourceFilterRules=[{"filter": {"source": "status=a"}}]),
            source=self.api._ReviewedStateSource.LIVE_RESPONSE,
        ) != self.api._configuration_fingerprint(
            _azure_live(resourceFilterRules=[{"filter": {"source": "status=b"}}]),
            source=self.api._ReviewedStateSource.LIVE_RESPONSE,
        )

    def test_account_lock_root_ignores_hostile_home_and_uses_uid_passwd(
        self, tmp_path, monkeypatch
    ):
        fresh = _load_api_client()
        passwd_home = tmp_path / "passwd-home"
        monkeypatch.setenv("HOME", str(tmp_path / "hostile-home"))
        monkeypatch.setattr(
            fresh.pwd,
            "getpwuid",
            lambda uid: SimpleNamespace(pw_dir=str(passwd_home), uid=uid),
        )
        assert fresh._account_lock_root_path() == (
            passwd_home
            / ".local"
            / "state"
            / "splunk-cisco-skills"
            / "integration-rollback-locks"
        )

    @pytest.mark.parametrize("lock_kind", ("target", "name"))
    def test_canonical_lock_blocks_a_second_real_process(
        self, lock_kind, tmp_path
    ):
        root = tmp_path / f"{lock_kind}-root"
        ready_one = tmp_path / f"{lock_kind}-ready-one"
        ready_two = tmp_path / f"{lock_kind}-ready-two"
        started_one = tmp_path / f"{lock_kind}-started-one"
        started_two = tmp_path / f"{lock_kind}-started-two"
        release = tmp_path / f"{lock_kind}-release"
        value = "azure-id-1" if lock_kind == "target" else "same-exact-name"
        child = """
import importlib.util
import pathlib
import sys
import time
spec = importlib.util.spec_from_file_location('azure_lock_child', sys.argv[1])
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
root, kind, value, started, ready, release = sys.argv[2:]
api._account_lock_root_path = lambda: pathlib.Path(root)
pathlib.Path(started).touch()
lock = api._target_lock if kind == 'target' else api._name_lock
with lock('us1', value):
    pathlib.Path(ready).touch()
    if release != '-':
        deadline = time.monotonic() + 10
        while not pathlib.Path(release).exists():
            if time.monotonic() >= deadline:
                raise SystemExit('timed out waiting for release')
            time.sleep(0.01)
"""

        def wait_for(path: Path) -> None:
            deadline = time.monotonic() + 5
            while not path.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert path.exists(), f"subprocess did not create {path}"

        first = subprocess.Popen(
            [
                sys.executable,
                "-c",
                child,
                str(SCRIPTS_DIR / "azure_integration_api.py"),
                str(root),
                lock_kind,
                value,
                str(started_one),
                str(ready_one),
                str(release),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        second = None
        try:
            wait_for(started_one)
            wait_for(ready_one)
            second = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    child,
                    str(SCRIPTS_DIR / "azure_integration_api.py"),
                    str(root),
                    lock_kind,
                    value,
                    str(started_two),
                    str(ready_two),
                    "-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            wait_for(started_two)
            time.sleep(0.15)
            assert not ready_two.exists()
            assert second.poll() is None
            release.touch()
            first_out, first_err = first.communicate(timeout=5)
            second_out, second_err = second.communicate(timeout=5)
            assert first.returncode == 0, first_out + first_err
            assert second.returncode == 0, second_out + second_err
            assert ready_two.exists()
        finally:
            release.touch(exist_ok=True)
            for process in (first, second):
                if process is not None and process.poll() is None:
                    process.kill()
                    process.communicate()

    def test_missing_plan_gate_precedes_token_and_transport(self, tmp_path, monkeypatch):
        token_read = Mock(side_effect=AssertionError("token read"))
        transport = Mock(side_effect=AssertionError("transport"))
        monkeypatch.setattr(self.api, "read_secret_file", token_read)
        monkeypatch.setattr(self.api, "_request", transport)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "azure_integration_api.py",
                "--realm",
                "us1",
                "--token-file",
                str(tmp_path / "token"),
                "--state-dir",
                str(tmp_path / "state"),
                "--plan-file",
                str(tmp_path / "missing-plan.json"),
                "--integration-id",
                "azure-id-1",
                "--integration-name",
                "test-azure",
                "--apply",
                "rollback",
                "disable",
            ],
        )
        assert self.api.main() == 1
        assert token_read.call_count == 0
        assert transport.call_count == 0

    def test_rollback_apply_rejects_dry_run_before_plan_token_or_transport(
        self, tmp_path, monkeypatch, capsys
    ):
        token_read = Mock(side_effect=AssertionError("token read"))
        transport = Mock(side_effect=AssertionError("transport"))
        plan_load = Mock(side_effect=AssertionError("plan read"))
        monkeypatch.setattr(self.api, "read_secret_file", token_read)
        monkeypatch.setattr(self.api, "_request", transport)
        monkeypatch.setattr(self.api, "load_rollback_plan", plan_load)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "azure_integration_api.py",
                "--realm", "us1",
                "--state-dir", str(tmp_path / "state"),
                "--token-file", str(tmp_path / "token"),
                "--plan-file", str(tmp_path / "plan.json"),
                "--plan-hash", "0" * 64,
                "--integration-id", "azure-id-1",
                "--accept-disable-integration", "azure-id-1",
                "--dry-run",
                "--apply",
                "rollback", "disable",
            ],
        )
        assert self.api.main() == 1
        assert "--dry-run is not accepted with rollback" in capsys.readouterr().out
        assert plan_load.call_count == token_read.call_count == transport.call_count == 0

    def test_missing_ack_gate_precedes_token_and_transport(self, tmp_path, monkeypatch):
        plan_path, plan_hash = _azure_plan(self.api, tmp_path)
        token_read = Mock(side_effect=AssertionError("token read"))
        transport = Mock(side_effect=AssertionError("transport"))
        monkeypatch.setattr(self.api, "read_secret_file", token_read)
        monkeypatch.setattr(self.api, "_request", transport)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "azure_integration_api.py",
                "--realm",
                "us1",
                "--token-file",
                str(tmp_path / "token"),
                "--state-dir",
                str(tmp_path / "state"),
                "--plan-file",
                str(plan_path),
                "--plan-hash",
                plan_hash,
                "--integration-id",
                "azure-id-1",
                "--apply",
                "rollback",
                "disable",
            ],
        )
        assert self.api.main() == 1
        assert token_read.call_count == 0
        assert transport.call_count == 0

    def test_plan_tamper_wrong_action_and_wrong_id_fail_closed(self, tmp_path, monkeypatch):
        plan_path, plan_hash = _azure_plan(self.api, tmp_path)
        document = json.loads(plan_path.read_text())
        document["integration_name"] = "tampered"
        plan_path.write_text(json.dumps(document), encoding="utf-8")
        plan_path.chmod(0o600)
        with pytest.raises(self.api.ApiError, match="mismatch"):
            self.api.load_rollback_plan(plan_path, plan_hash)

        plan_path, plan_hash = _azure_plan(self.api, tmp_path)
        live_get = Mock()
        monkeypatch.setattr(self.api, "get_integration", live_get)
        for action, integration_id in (("delete", "azure-id-1"), ("disable", "other-id")):
            with pytest.raises(self.api.ApiError, match="flags do not match"):
                self.api.apply_rollback(
                    realm="us1",
                    token="unused",
                    state_dir=tmp_path / "state",
                    plan_path=plan_path,
                    plan_sha256=plan_hash,
                    action=action,
                    integration_id=integration_id,
                    apply_gate=True,
                    acknowledge_disable=integration_id if action == "disable" else "",
                    acknowledge_delete=integration_id if action == "delete" else "",
                )
        assert live_get.call_count == 0

    def test_plan_schema_mode_and_symlink_failures(self, tmp_path):
        plan_path, plan_hash = _azure_plan(self.api, tmp_path)
        plan_path.chmod(0o644)
        with pytest.raises(self.api.ApiError, match="mode-0600"):
            self.api.load_rollback_plan(plan_path, plan_hash)
        plan_path.chmod(0o600)
        symlink = tmp_path / "plan-link.json"
        symlink.symlink_to(plan_path)
        with pytest.raises(self.api.ApiError, match="mode-0600"):
            self.api.load_rollback_plan(symlink, plan_hash)

        document = json.loads(plan_path.read_text())
        document["unknown"] = True
        plan_path.write_text(json.dumps(document), encoding="utf-8")
        plan_path.chmod(0o600)
        with pytest.raises(self.api.ApiError, match="unknown"):
            self.api.load_rollback_plan(
                plan_path,
                self.api.rollback_plan_sha256({k: v for k, v in document.items() if k != "unknown"}),
            )

    @pytest.mark.parametrize(
        "mutation,error",
        (
            (lambda text: text.replace(
                '"action": "disable",',
                '"action": "disable",\n  "action": "delete",',
                1,
            ), "duplicate JSON object key"),
            (lambda text: text.replace("{", '{\n  "poison": NaN,', 1), "non-standard JSON"),
            (lambda text: text.replace("{", '{\n  "poison": Infinity,', 1), "non-standard JSON"),
        ),
    )
    def test_plan_strict_json_rejects_duplicate_keys_and_nonfinite_constants(
        self, mutation, error, tmp_path
    ):
        plan_path, _plan_hash = _azure_plan(self.api, tmp_path)
        plan_path.write_text(mutation(plan_path.read_text()), encoding="utf-8")
        plan_path.chmod(0o600)
        with pytest.raises(self.api.ApiError, match=error):
            self.api.load_rollback_plan(plan_path, "0" * 64)

    def test_plan_exact_name_parent_mode_and_fresh_plan_identity(self, tmp_path):
        parent = tmp_path / "review-parent"
        parent.mkdir(mode=0o755)
        before_mode = parent.stat().st_mode & 0o777
        first, first_hash = _azure_plan(
            self.api, parent, integration_name="token=production"
        )
        first_document = json.loads(first.read_text())
        assert first_document["integration_name"] == "token=production"
        assert self.api.rollback_plan_sha256(first_document) == first_hash
        assert parent.stat().st_mode & 0o777 == before_mode == 0o755
        second_path = parent / "fresh-plan.json"
        app_id = _write_private_text(parent / "app-id", "azure-app-id-secret")
        secret = _write_private_text(parent / "secret", "azure-secret-value")
        second = self.api.render_rollback_plan(
            second_path,
            realm="us1",
            action="disable",
            integration_id="azure-id-1",
            integration_name="token=production",
            expected_enabled_state=True,
            observed_state_file=str(parent / "azure-disable-observed.json"),
            app_id_file=str(app_id),
            secret_file=str(secret),
        )
        assert second["plan"]["plan_id"] != first_document["plan_id"]
        assert second["plan_hash"] != first_hash

    def test_snapshot_and_plan_writers_enforce_exact_loader_size_bounds(
        self, tmp_path, monkeypatch
    ):
        observed = tmp_path / "observed.json"
        self.api.write_observed_snapshot(
            observed, realm="us1", integrations=[_azure_live()]
        )
        observed_size = len(observed.read_bytes())
        monkeypatch.setattr(self.api, "MAX_OBSERVED_BYTES", observed_size)
        boundary_observed = tmp_path / "boundary-observed.json"
        self.api.write_observed_snapshot(
            boundary_observed, realm="us1", integrations=[_azure_live()]
        )
        assert len(boundary_observed.read_bytes()) == observed_size

        preserved_observed = _write_private_text(
            tmp_path / "preserved-observed.json", "preserve-observed"
        )
        monkeypatch.setattr(self.api, "MAX_OBSERVED_BYTES", observed_size - 1)
        with pytest.raises(self.api.ApiError, match="observed snapshot exceeds"):
            self.api.write_observed_snapshot(
                preserved_observed, realm="us1", integrations=[_azure_live()]
            )
        assert preserved_observed.read_text() == "preserve-observed"
        monkeypatch.setattr(self.api, "MAX_OBSERVED_BYTES", observed_size)

        app_id = _write_private_text(tmp_path / "app-id", "app-id")
        secret = _write_private_text(tmp_path / "secret", "secret")
        plan_path = tmp_path / "plan.json"
        self.api.render_rollback_plan(
            plan_path,
            realm="us1",
            action="disable",
            integration_id="azure-id-1",
            integration_name="test-azure",
            expected_enabled_state=True,
            observed_state_file=str(observed),
            app_id_file=str(app_id),
            secret_file=str(secret),
        )
        plan_size = len(plan_path.read_bytes())
        monkeypatch.setattr(self.api, "MAX_PLAN_BYTES", plan_size)
        boundary_plan = tmp_path / "boundary-plan.json"
        self.api.render_rollback_plan(
            boundary_plan,
            realm="us1",
            action="disable",
            integration_id="azure-id-1",
            integration_name="test-azure",
            expected_enabled_state=True,
            observed_state_file=str(observed),
            app_id_file=str(app_id),
            secret_file=str(secret),
        )
        assert len(boundary_plan.read_bytes()) == plan_size

        preserved_plan = _write_private_text(tmp_path / "preserved-plan.json", "preserve-plan")
        monkeypatch.setattr(self.api, "MAX_PLAN_BYTES", plan_size - 1)
        with pytest.raises(self.api.ApiError, match="rollback plan exceeds"):
            self.api.render_rollback_plan(
                preserved_plan,
                realm="us1",
                action="disable",
                integration_id="azure-id-1",
                integration_name="test-azure",
                expected_enabled_state=True,
                observed_state_file=str(observed),
                app_id_file=str(app_id),
                secret_file=str(secret),
            )
        assert preserved_plan.read_text() == "preserve-plan"

    def test_observed_snapshot_binds_human_reviewable_revision_state(self, tmp_path):
        observed = tmp_path / "observed.json"
        live = _azure_live(
            lastUpdated=1712345678,
            creator="reviewer-id",
            resourceFilterRules=[
                {"filter": {"source": "resource.type=virtual-machine"}}
            ],
        )
        snapshot = self.api.write_observed_snapshot(
            observed, realm="us1", integrations=[live]
        )
        assert observed.stat().st_mode & 0o777 == 0o600
        assert snapshot["results"][0]["lastUpdated"] == 1712345678
        assert snapshot["results"][0]["resourceFilterRules"] == (
            live["resourceFilterRules"]
        )
        assert "secretKey" not in json.dumps(snapshot)

        app_id = _write_private_text(tmp_path / "app-id", "app-id")
        secret = _write_private_text(tmp_path / "secret", "secret")
        rendered = self.api.render_rollback_plan(
            tmp_path / "plan.json",
            realm="us1",
            action="disable",
            integration_id="azure-id-1",
            integration_name="test-azure",
            expected_enabled_state=True,
            observed_state_file=str(observed),
            app_id_file=str(app_id),
            secret_file=str(secret),
        )
        reviewed = rendered["plan"]["reviewed_state"]
        assert reviewed["lastUpdated"] == 1712345678
        assert rendered["plan"]["reviewed_state_sha256"] == self.api._reviewed_state_sha256(reviewed)

    def test_observed_snapshot_rejects_duplicate_identity_and_strict_json(
        self, tmp_path
    ):
        for integrations, error in (
            ([_azure_live(id="one"), _azure_live(id="one", name="other")], "repeats integration ID"),
            ([_azure_live(id="one"), _azure_live(id="two")], "repeats integration name"),
        ):
            with pytest.raises(self.api.ApiError, match=error):
                self.api.write_observed_snapshot(
                    tmp_path / f"{len(error)}.json",
                    realm="us1",
                    integrations=integrations,
                )

        duplicate = _write_private_text(
            tmp_path / "duplicate-observed.json",
            '{"schema_version":1,"schema_version":1,"provider":"Azure",'
            '"realm":"us1","captured_at":"2026-01-01T00:00:00+00:00",'
            '"count":0,"results":[]}',
        )
        with pytest.raises(self.api.ApiError, match="duplicate JSON object key"):
            self.api.load_observed_snapshot(duplicate, expected_realm="us1")

        nonfinite = _write_private_text(
            tmp_path / "nonfinite-observed.json",
            '{"schema_version":1,"provider":"Azure","realm":"us1",'
            '"captured_at":"2026-01-01T00:00:00+00:00","count":0,'
            '"results":[],"poison":NaN}',
        )
        with pytest.raises(self.api.ApiError, match="non-standard JSON"):
            self.api.load_observed_snapshot(nonfinite, expected_realm="us1")

    @pytest.mark.parametrize(
        "document,error",
        (
            ([], "schema mismatch"),
            (
                {
                    "schema_version": 1,
                    "provider": "Azure",
                    "realm": "us1",
                    "captured_at": "2026-01-01T00:00:00+00:00",
                    "count": 0,
                },
                "schema mismatch",
            ),
            (
                {
                    "schema_version": 1,
                    "provider": "Azure",
                    "realm": "us1",
                    "captured_at": "2026-01-01T00:00:00+00:00",
                    "count": 0,
                    "results": [],
                    "extra": True,
                },
                "schema mismatch",
            ),
            (
                {
                    "schema_version": True,
                    "provider": "Azure",
                    "realm": "us1",
                    "captured_at": "2026-01-01T00:00:00+00:00",
                    "count": 0,
                    "results": [],
                },
                "schema_version",
            ),
            (
                {
                    "schema_version": 2,
                    "provider": "Azure",
                    "realm": "us1",
                    "captured_at": "2026-01-01T00:00:00+00:00",
                    "count": 0,
                    "results": [],
                },
                "schema_version",
            ),
            (
                {
                    "schema_version": 1,
                    "provider": "GCP",
                    "realm": "us1",
                    "captured_at": "2026-01-01T00:00:00+00:00",
                    "count": 0,
                    "results": [],
                },
                "provider or realm",
            ),
            (
                {
                    "schema_version": 1,
                    "provider": "Azure",
                    "realm": "eu0",
                    "captured_at": "2026-01-01T00:00:00+00:00",
                    "count": 0,
                    "results": [],
                },
                "provider or realm",
            ),
            (
                {
                    "schema_version": 1,
                    "provider": "Azure",
                    "realm": "us1",
                    "captured_at": "2026-01-01T00:00:00+00:00",
                    "count": True,
                    "results": [],
                },
                "count is invalid",
            ),
        ),
    )
    def test_observed_snapshot_requires_exact_typed_envelope(self, document, error):
        with pytest.raises(self.api.ApiError, match=error):
            self.api._validate_observed_snapshot(document, expected_realm="us1")

    def test_offline_cli_prints_the_exact_unredacted_schema_safe_plan(
        self, tmp_path, monkeypatch, capsys
    ):
        observed = tmp_path / "observed.json"
        self.api.write_observed_snapshot(
            observed,
            realm="us1",
            integrations=[_azure_live(name="token=production")],
        )
        app_id = _write_private_text(tmp_path / "app-id", "app-id")
        secret = _write_private_text(tmp_path / "secret", "secret")
        plan_path = tmp_path / "plan.json"
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "azure_integration_api.py",
                "--realm", "us1",
                "--state-dir", str(tmp_path / "state"),
                "--plan-file", str(plan_path),
                "--integration-id", "azure-id-1",
                "--integration-name", "token=production",
                "--observed-state-file", str(observed),
                "--app-id-file", str(app_id),
                "--secret-file", str(secret),
                "rollback", "disable",
            ],
        )
        assert self.api.main() == 0
        printed = json.loads(capsys.readouterr().out)
        on_disk = json.loads(plan_path.read_text())
        assert printed["plan"]["integration_name"] == "token=production"
        assert printed["plan"] == on_disk
        assert printed["plan_hash"] == self.api.rollback_plan_sha256(on_disk)

    def test_disable_plan_requires_enabled_transition_but_delete_allows_disabled(
        self, tmp_path
    ):
        with pytest.raises(self.api.ApiError, match="expected_enabled_state=true"):
            _azure_plan(self.api, tmp_path / "disable", expected_enabled_state=False)
        plan_path, _ = _azure_plan(
            self.api,
            tmp_path / "delete",
            action="delete",
            expected_enabled_state=False,
        )
        assert json.loads(plan_path.read_text())["expected_enabled_state"] is False

    def test_secret_file_mode_and_symlink_failures(self, tmp_path):
        secret = _write_private_text(tmp_path / "secret", "value")
        secret.chmod(0o644)
        with pytest.raises(PermissionError, match="permissions"):
            self.api.read_secret_file(secret)
        secret.chmod(0o600)
        link = tmp_path / "secret-link"
        link.symlink_to(secret)
        with pytest.raises(PermissionError, match="non-symlink"):
            self.api.read_secret_file(link)

    def test_private_reader_loops_short_reads_and_rejects_early_eof(
        self, tmp_path, monkeypatch
    ):
        source = _write_private_text(tmp_path / "stable", "good\nbad\n")
        original_read = self.api.os.read

        def short_read(descriptor, size):
            return original_read(descriptor, min(size, 2))

        monkeypatch.setattr(self.api.os, "read", short_read)
        assert self.api.read_private_file_bytes(source) == b"good\nbad\n"

        calls = 0

        def early_eof(descriptor, size):
            nonlocal calls
            calls += 1
            return original_read(descriptor, min(size, 4)) if calls == 1 else b""

        monkeypatch.setattr(self.api.os, "read", early_eof)
        with pytest.raises(PermissionError, match="short-read"):
            self.api.read_private_file_bytes(source)

    @pytest.mark.parametrize("lock_kind", ("journal", "target", "name"))
    @pytest.mark.parametrize("attack", ("mode", "hardlink"))
    def test_preexisting_lock_mode_and_hardlink_fail_closed(
        self, lock_kind, attack, tmp_path
    ):
        if lock_kind == "journal":
            state_dir = tmp_path / f"journal-{attack}"
            state_dir.mkdir()
            lock_file = state_dir / ".apply-state.lock"
            lock_file.write_bytes(b"")
            lock_file.chmod(0o600)

            def operation():
                self.api.append_step(
                    state_dir, "test", "step", "operation-id", "success"
                )
        else:
            root = tmp_path / "account-lock-root"
            lock = self.api._target_lock if lock_kind == "target" else self.api._name_lock
            value = "azure-id-1" if lock_kind == "target" else "exact-name"
            with lock("us1", value):
                pass
            lock_file = next(root.glob("*.lock"))

            def operation():
                with lock("us1", value):
                    pass

        if attack == "mode":
            lock_file.chmod(0o666)
        else:
            os.link(lock_file, lock_file.with_name(lock_file.name + ".alias"))
        with pytest.raises((PermissionError, self.api.ApiError), match="0600|hardlink|hard link"):
            operation()

    def test_target_lock_rejects_symlink_ancestor_without_masking_body_errors(
        self, tmp_path, monkeypatch
    ):
        actual = tmp_path / "actual"
        actual.mkdir()
        alias = tmp_path / "alias"
        alias.symlink_to(actual, target_is_directory=True)
        monkeypatch.setattr(
            self.api, "_account_lock_root_path", lambda: alias / "locks"
        )
        with pytest.raises(self.api.ApiError, match="symlink"):
            with self.api._target_lock("us1", "azure-id-1"):
                pass

        root = tmp_path / "safe-lock-root"
        monkeypatch.setattr(self.api, "_account_lock_root_path", lambda: root)
        with pytest.raises(OSError, match="body failure"):
            with self.api._target_lock("us1", "azure-id-1"):
                raise OSError("body failure")

    @pytest.mark.parametrize("ancestor_mode", (0o755, 0o1777))
    def test_secure_directory_rejects_untrusted_intermediate_owner(
        self, ancestor_mode, tmp_path, monkeypatch
    ):
        ancestor = tmp_path / "owned"
        leaf = ancestor / "leaf"
        leaf.mkdir(parents=True)
        ancestor_inode = ancestor.stat().st_ino
        state_globals = self.api.secure_private_directory.__globals__
        original_fstat = state_globals["os"].fstat

        def hostile_owner(descriptor):
            metadata = original_fstat(descriptor)
            if metadata.st_ino == ancestor_inode:
                return SimpleNamespace(
                    st_mode=(metadata.st_mode & ~0o7777) | ancestor_mode,
                    st_uid=os.getuid() + 1,
                )
            return metadata

        monkeypatch.setattr(state_globals["os"], "fstat", hostile_owner)
        with pytest.raises(PermissionError, match="untrusted owner"):
            with self.api.secure_private_directory(leaf, create=False):
                pass

    def test_secure_helpers_accept_the_real_root_owned_tmp_alias(self):
        with tempfile.TemporaryDirectory(prefix="azure-secure-dir-", dir="/tmp") as raw:
            directory_path = Path(raw)
            with self.api.secure_private_directory(
                directory_path, create=False
            ) as directory:
                assert Path(os.path.realpath(directory.path)) == Path(
                    os.path.realpath(directory_path)
                )
            target = directory_path / "private.json"
            self.api.write_private_json(target, {"status": "ok"})
            assert json.loads(target.read_text()) == {"status": "ok"}

    def test_paginated_exact_resolver_and_cross_page_duplicate(self, monkeypatch):
        pages = [
            {"results": [_azure_live(id="id-1"), _azure_live(id="id-2", name="other")], "count": 3},
            {"results": [_azure_live(id="id-3", name="third")], "count": 3},
        ]
        request = Mock(side_effect=pages)
        monkeypatch.setattr(self.api, "_request", request)
        resolved = self.api.resolve_legacy_name("us1", "unused", "test-azure")
        assert resolved["id"] == "id-1"
        assert request.call_count == 2

        duplicate_pages = [
            {"results": [_azure_live(id="id-1")], "count": 2},
            {"results": [_azure_live(id="id-1", name="again")], "count": 2},
        ]
        monkeypatch.setattr(self.api, "_request", Mock(side_effect=duplicate_pages))
        with pytest.raises(self.api.ApiError, match="repeated integration ID"):
            self.api.list_azure_integrations("us1", "unused")

    @pytest.mark.parametrize(
        "response,error",
        (
            ({"count": 1}, "official count/results"),
            ({"results": [], "count": 1}, "stopped before complete"),
            ({"results": ["bad"], "count": 1}, "malformed integration page"),
            ({"results": [], "count": []}, "invalid total count"),
        ),
    )
    def test_pagination_malformed_or_incomplete_fails(self, response, error, monkeypatch):
        monkeypatch.setattr(self.api, "_request", Mock(return_value=response))
        with pytest.raises(self.api.ApiError, match=error):
            self.api.list_azure_integrations("us1", "unused")

    @pytest.mark.parametrize(
        "item,error",
        (
            (_azure_live(id=1), "integration ID"),
            (_azure_live(id=True), "integration ID"),
            (_azure_live(name=None), "integration name"),
            (_azure_live(name=7), "integration name"),
            (_azure_live(name="bad\nname"), "integration name"),
        ),
    )
    def test_pagination_rejects_noncanonical_raw_ids_and_names(
        self, item, error, monkeypatch
    ):
        monkeypatch.setattr(
            self.api,
            "_request",
            Mock(return_value={"count": 1, "results": [item]}),
        )
        with pytest.raises(self.api.ApiError, match=error):
            self.api.list_azure_integrations("us1", "unused")

    @pytest.mark.parametrize(
        "response",
        (
            {"count": 1, "items": [_azure_live()]},
            {"count": 1, "results": [_azure_live()], "extra": True},
        ),
    )
    def test_pagination_rejects_undocumented_envelopes(
        self, response, monkeypatch
    ):
        monkeypatch.setattr(self.api, "_request", Mock(return_value=response))
        with pytest.raises(self.api.ApiError, match="official count/results"):
            self.api.list_azure_integrations("us1", "unused")

    def test_pagination_cap_fails_on_first_bounded_request(self, monkeypatch):
        request = Mock(return_value={"results": [_azure_live()], "count": 10000})
        monkeypatch.setattr(self.api, "_request", request)
        with pytest.raises(self.api.ApiError, match="10,000 cap"):
            self.api.list_azure_integrations("us1", "unused")
        assert request.call_count == 1

    def test_legacy_resolver_rejects_zero_and_duplicate_names(self, monkeypatch):
        monkeypatch.setattr(self.api, "list_azure_integrations", lambda *_: [])
        with pytest.raises(self.api.ApiError, match="no Azure integration"):
            self.api.resolve_legacy_name("us1", "unused", "same")
        monkeypatch.setattr(
            self.api,
            "list_azure_integrations",
            lambda *_: [_azure_live(id="id-1", name="same"), _azure_live(id="id-2", name="same")],
        )
        with pytest.raises(self.api.ApiError, match="multiple Azure integrations"):
            self.api.resolve_legacy_name("us1", "unused", "same")

    def test_upsert_duplicate_name_protection(self, tmp_path, monkeypatch):
        app_id = _write_private_text(tmp_path / "app-id", "app-id-value")
        secret = _write_private_text(tmp_path / "secret", "secret-value")
        monkeypatch.setattr(
            self.api,
            "list_azure_integrations",
            lambda *_: [_azure_live(id="id-1"), _azure_live(id="id-2")],
        )
        update = Mock()
        create = Mock()
        monkeypatch.setattr(self.api, "update_integration", update)
        monkeypatch.setattr(self.api, "create_integration", create)
        with pytest.raises(self.api.ApiError, match="multiple Azure integrations"):
            self.api.upsert(
                "us1",
                "unused",
                _azure_live(id=None),
                tmp_path / "state",
                app_id_file=str(app_id),
                secret_file=str(secret),
            )
        assert update.call_count == 0
        assert create.call_count == 0

    @pytest.mark.parametrize(
        "app_id_file,secret_file",
        (("", ""), ("should-not-open", ""), ("", "should-not-open")),
    )
    def test_upsert_requires_both_secure_credential_files_before_live_reads(
        self, app_id_file, secret_file, tmp_path, monkeypatch
    ):
        credential_read = Mock(side_effect=AssertionError("credential read"))
        listing = Mock(side_effect=AssertionError("list"))
        transport = Mock(side_effect=AssertionError("transport"))
        monkeypatch.setattr(self.api, "read_secret_file_material", credential_read)
        monkeypatch.setattr(self.api, "list_azure_integrations", listing)
        monkeypatch.setattr(self.api, "_request", transport)
        with pytest.raises(self.api.ApiError, match="requires both"):
            self.api.upsert(
                "us1",
                "unused",
                _azure_live(
                    id=None,
                    appId="INLINE-APP-CANARY",
                    secretKey="INLINE-SECRET-CANARY",
                ),
                tmp_path / "state",
                app_id_file=app_id_file,
                secret_file=secret_file,
            )
        assert credential_read.call_count == listing.call_count == transport.call_count == 0

    def test_upsert_cli_requires_both_credential_files_before_token_read(
        self, tmp_path, monkeypatch, capsys
    ):
        token_read = Mock(side_effect=AssertionError("token read"))
        upsert = Mock(side_effect=AssertionError("upsert"))
        monkeypatch.setattr(self.api, "read_secret_file", token_read)
        monkeypatch.setattr(self.api, "upsert", upsert)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "azure_integration_api.py",
                "--realm", "us1",
                "--state-dir", str(tmp_path / "state"),
                "--token-file", str(tmp_path / "token"),
                "--payload-file", str(tmp_path / "payload.json"),
                "upsert",
            ],
        )
        assert self.api.main() == 1
        assert "requires both" in capsys.readouterr().out
        assert token_read.call_count == upsert.call_count == 0

    def test_upsert_name_then_target_lock_covers_relist_update_and_journal(
        self, tmp_path, monkeypatch
    ):
        app_id = _write_private_text(tmp_path / "app-id", "app-id-value")
        secret = _write_private_text(tmp_path / "secret", "secret-value")
        held = {"name": False, "target": False}
        events = []

        @contextmanager
        def name_lock(_realm, exact_name):
            assert exact_name == "test-azure"
            held["name"] = True
            events.append("name-enter")
            try:
                yield
            finally:
                held["name"] = False
                events.append("name-exit")

        @contextmanager
        def target_lock(_realm, exact_id):
            assert held["name"]
            assert exact_id == "azure-id-1"
            held["target"] = True
            events.append("target-enter")
            try:
                yield tmp_path / "unused-claim-root"
            finally:
                held["target"] = False
                events.append("target-exit")

        def relist(*_args):
            assert held["name"]
            if "list" not in events:
                assert not held["target"]
            else:
                assert held["target"]
            events.append("list")
            return [_azure_live()]

        def exact_get(*_args):
            assert held["name"] and held["target"]
            events.append("get")
            return _azure_live()

        def update(*_args, **_kwargs):
            assert held["name"] and held["target"]
            events.append("put")
            return _azure_live()

        def journal(*_args, **_kwargs):
            assert held["name"] and held["target"]
            events.append("journal")

        def record(*_args, **_kwargs):
            assert held["name"] and held["target"]
            events.append("hashes")

        monkeypatch.setattr(self.api, "_name_lock", name_lock)
        monkeypatch.setattr(self.api, "_target_lock", target_lock)
        monkeypatch.setattr(self.api, "list_azure_integrations", relist)
        monkeypatch.setattr(self.api, "get_integration", exact_get)
        monkeypatch.setattr(self.api, "update_integration", update)
        monkeypatch.setattr(self.api, "append_step", journal)
        monkeypatch.setattr(self.api, "_record_credential_hashes", record)
        assert self.api.upsert(
            "us1",
            "unused",
            _azure_live(id=None),
            tmp_path / "state",
            app_id_file=str(app_id),
            secret_file=str(secret),
        )["result"] == "updated"
        assert events == [
            "name-enter",
            "list",
            "target-enter",
            "get",
            "put",
            "get",
            "list",
            "journal",
            "hashes",
            "target-exit",
            "name-exit",
        ]

    def test_upsert_waiting_on_rollback_target_lock_cannot_reenable(
        self, tmp_path, monkeypatch
    ):
        app_id = _write_private_text(tmp_path / "app-id", "app-id-value")
        secret = _write_private_text(tmp_path / "secret", "secret-value")
        target_mutex = threading.Lock()
        decision_observed = threading.Event()
        live = _azure_live()
        errors = []
        update = Mock()

        target_mutex.acquire()

        def list_before_wait(*_args):
            decision_observed.set()
            return [dict(live)]

        @contextmanager
        def ordered_target_lock(_realm, integration_id):
            assert integration_id == "azure-id-1"
            target_mutex.acquire()
            try:
                yield tmp_path / "claim-root"
            finally:
                target_mutex.release()

        monkeypatch.setattr(self.api, "list_azure_integrations", list_before_wait)
        monkeypatch.setattr(self.api, "_target_lock", ordered_target_lock)
        monkeypatch.setattr(self.api, "get_integration", lambda *_: dict(live))
        monkeypatch.setattr(self.api, "update_integration", update)

        def run_upsert():
            try:
                self.api.upsert(
                    "us1",
                    "unused",
                    _azure_live(id=None),
                    tmp_path / "state",
                    app_id_file=str(app_id),
                    secret_file=str(secret),
                )
            except Exception as exc:  # captured for assertion in the test thread
                errors.append(exc)

        worker = threading.Thread(target=run_upsert)
        worker.start()
        assert decision_observed.wait(timeout=5)
        live["enabled"] = False
        target_mutex.release()
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert len(errors) == 1
        assert isinstance(errors[0], self.api.ApiError)
        assert "changed while waiting for the target lock" in str(errors[0])
        assert update.call_count == 0

    def test_upsert_records_hashes_from_the_exact_sent_credential_bytes(
        self, tmp_path, monkeypatch
    ):
        app_id = _write_private_text(tmp_path / "app-id", "original-app")
        secret = _write_private_text(tmp_path / "secret", "original-secret")
        captured = {}
        monkeypatch.setattr(
            self.api,
            "list_azure_integrations",
            Mock(side_effect=[[], [_azure_live()]]),
        )
        monkeypatch.setattr(self.api, "get_integration", Mock(return_value=_azure_live()))

        def create_once(_realm, _token, payload):
            captured.update(payload)
            app_id.write_text("swapped-app", encoding="utf-8")
            secret.write_text("swapped-secret", encoding="utf-8")
            return {"id": "azure-id-1"}

        monkeypatch.setattr(self.api, "create_integration", create_once)
        self.api.upsert(
            "us1",
            "unused",
            _azure_live(id=None),
            tmp_path / "state",
            app_id_file=str(app_id),
            secret_file=str(secret),
        )
        stored = json.loads((tmp_path / "state" / "credential-hashes.json").read_text())
        assert captured["appId"] == "original-app"
        assert captured["secretKey"] == "original-secret"
        assert stored["app_id_sha256"] == hashlib.sha256(b"original-app").hexdigest()
        assert stored["secret_sha256"] == hashlib.sha256(b"original-secret").hexdigest()

    @pytest.mark.parametrize(
        "document,error",
        (
            (
                {
                    "app_id_sha256": "0" * 64,
                    "secret_sha256": "1" * 64,
                    "unknown": "2" * 64,
                },
                "schema mismatch",
            ),
            (
                {"app_id_sha256": "bad", "secret_sha256": "1" * 64},
                "lowercase SHA-256",
            ),
        ),
    )
    def test_credential_hash_state_load_rejects_tampered_mode600_json(
        self, document, error, tmp_path
    ):
        state = tmp_path / "state"
        state.mkdir()
        path = _write_private_text(
            state / "credential-hashes.json", json.dumps(document)
        )
        assert path.stat().st_mode & 0o777 == 0o600
        with pytest.raises(self.api.ApiError, match=error):
            self.api._load_cred_hashes(state)
        assert self.api._load_cred_hashes(tmp_path / "absent") == {}

    @pytest.mark.parametrize("response", ({}, {"id": "other"}, {"id": 3}))
    def test_upsert_update_invalid_response_id_reconciles_once(
        self, response, tmp_path, monkeypatch
    ):
        app_id = _write_private_text(tmp_path / "app-id", "app")
        secret = _write_private_text(tmp_path / "secret", "secret")
        update = Mock(return_value=response)
        get = Mock(side_effect=[_azure_live(), _azure_live()])
        monkeypatch.setattr(self.api, "list_azure_integrations", Mock(return_value=[_azure_live()]))
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "update_integration", update)
        with pytest.raises(self.api.ApiError, match="operator resolution"):
            self.api.upsert(
                "us1", "unused", _azure_live(id=None), tmp_path / "state",
                app_id_file=str(app_id), secret_file=str(secret),
            )
        assert update.call_count == 1
        assert get.call_count == 2

    def test_upsert_update_postcondition_drift_never_retries_put(
        self, tmp_path, monkeypatch
    ):
        app_id = _write_private_text(tmp_path / "app-id", "app")
        secret = _write_private_text(tmp_path / "secret", "secret")
        update = Mock(return_value={"id": "azure-id-1"})
        get = Mock(side_effect=[_azure_live(), _azure_live(pollRate=600000)])
        monkeypatch.setattr(self.api, "list_azure_integrations", Mock(return_value=[_azure_live()]))
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "update_integration", update)
        with pytest.raises(self.api.ApiError, match="postcondition"):
            self.api.upsert(
                "us1", "unused", _azure_live(id=None), tmp_path / "state",
                app_id_file=str(app_id), secret_file=str(secret),
            )
        assert update.call_count == 1

    @pytest.mark.parametrize("response", ({}, {"id": 9}))
    def test_upsert_create_requires_server_id_and_reconciles_by_exact_name(
        self, response, tmp_path, monkeypatch
    ):
        app_id = _write_private_text(tmp_path / "app-id", "app")
        secret = _write_private_text(tmp_path / "secret", "secret")
        create = Mock(return_value=response)
        listing = Mock(side_effect=[[], []])
        monkeypatch.setattr(self.api, "list_azure_integrations", listing)
        monkeypatch.setattr(self.api, "create_integration", create)
        with pytest.raises(self.api.ApiError, match="operator resolution"):
            self.api.upsert(
                "us1", "unused", _azure_live(id=None), tmp_path / "state",
                app_id_file=str(app_id), secret_file=str(secret),
            )
        assert create.call_count == 1
        assert listing.call_count == 2

    def test_upsert_create_relist_duplicate_fails_closed_without_second_post(
        self, tmp_path, monkeypatch
    ):
        app_id = _write_private_text(tmp_path / "app-id", "app")
        secret = _write_private_text(tmp_path / "secret", "secret")
        created = _azure_live(id="created-id")
        listing = Mock(
            side_effect=[[], [created, _azure_live(id="other-id")]]
        )
        create = Mock(return_value={"id": "created-id"})
        monkeypatch.setattr(self.api, "list_azure_integrations", listing)
        monkeypatch.setattr(self.api, "create_integration", create)
        monkeypatch.setattr(self.api, "get_integration", Mock(return_value=created))
        with pytest.raises(self.api.ApiError, match="name uniqueness"):
            self.api.upsert(
                "us1", "unused", _azure_live(id=None), tmp_path / "state",
                app_id_file=str(app_id), secret_file=str(secret),
            )
        assert create.call_count == 1

    @pytest.mark.parametrize("method", ("PUT", "POST"))
    def test_upsert_credential_echo_response_is_one_protocol_failure(
        self, method, tmp_path, monkeypatch, capsys
    ):
        app_id = _write_private_text(tmp_path / "app-id", "app")
        secret = _write_private_text(tmp_path / "secret", "secret")
        canary = f"AZURE-{method}-RESPONSE-CREDENTIAL-CANARY"
        response = _azure_live(secretKey=canary)
        state_dir = tmp_path / "state"
        if method == "PUT":
            monkeypatch.setattr(
                self.api,
                "list_azure_integrations",
                Mock(return_value=[_azure_live()]),
            )
            monkeypatch.setattr(
                self.api, "get_integration", Mock(return_value=_azure_live())
            )
            mutation = Mock(return_value=response)
            monkeypatch.setattr(self.api, "update_integration", mutation)
        else:
            monkeypatch.setattr(
                self.api, "list_azure_integrations", Mock(return_value=[])
            )
            mutation = Mock(return_value=response)
            monkeypatch.setattr(self.api, "create_integration", mutation)
        with pytest.raises(self.api.ApiError, match="violated the reviewed schema") as error:
            self.api.upsert(
                "us1",
                "unused",
                _azure_live(id=None),
                state_dir,
                app_id_file=str(app_id),
                secret_file=str(secret),
            )
        print(str(error.value))
        print(str(error.value), file=sys.stderr)
        captured = capsys.readouterr()
        journal = json.loads((state_dir / "apply-state.json").read_text())
        assert mutation.call_count == 1
        assert [step["result"] for step in journal["steps"]] == ["failed"]
        combined = json.dumps(journal) + captured.out + captured.err + str(error.value)
        assert canary not in combined
        assert "success" not in combined

    @pytest.mark.parametrize(
        "payload,error",
        (({}, "explicit Boolean"), ({"enabled": "false"}, "explicit Boolean"), ({"enabled": False}, "refusing disabling PUT")),
    )
    def test_update_requires_explicit_enabled_and_capability(
        self, payload, error, monkeypatch
    ):
        transport = Mock()
        monkeypatch.setattr(self.api, "_request", transport)
        with pytest.raises(self.api.ApiError, match=error):
            self.api.update_integration("us1", "unused", "azure-id-1", payload)
        assert transport.call_count == 0

    def test_normal_enabled_update_remains_allowed(self, monkeypatch):
        transport = Mock(return_value={"enabled": True})
        monkeypatch.setattr(self.api, "_request", transport)
        assert self.api.update_integration(
            "us1", "unused", "azure-id-1", {"enabled": True}
        )["enabled"] is True
        assert transport.call_count == 1

    def test_direct_python_rollback_bypass_fails(self, monkeypatch):
        transport = Mock()
        monkeypatch.setattr(self.api, "_request", transport)
        with pytest.raises(self.api.ApiError, match="direct disable"):
            self.api.disable_integration("us1", "unused", "azure-id-1")
        with pytest.raises(self.api.ApiError, match="direct delete"):
            self.api.delete_integration("us1", "unused", "azure-id-1")
        assert transport.call_count == 0


class TestAzureRollbackMutation:
    def setup_method(self):
        self.api = _load_api_client()

    @pytest.fixture(autouse=True)
    def _isolate_account_lock_root(self, tmp_path, monkeypatch):
        root = tmp_path / "account-lock-root"
        monkeypatch.setattr(self.api, "_account_lock_root_path", lambda: root)
        monkeypatch.setattr(
            self.api,
            "list_azure_integrations",
            lambda _realm, _token: [_azure_live()],
        )

    def _apply_kwargs(self, tmp_path, *, action="disable"):
        plan_path, plan_hash = _azure_plan(self.api, tmp_path, action=action)
        kwargs = {
            "realm": "us1",
            "token": "unused",
            "state_dir": tmp_path / "state",
            "plan_path": plan_path,
            "plan_sha256": plan_hash,
            "action": action,
            "integration_id": "azure-id-1",
            "apply_gate": True,
            "acknowledge_disable": "azure-id-1" if action == "disable" else "",
            "acknowledge_delete": "azure-id-1" if action == "delete" else "",
        }
        if action == "disable":
            kwargs["app_id_file"] = str(tmp_path / "app-id")
            kwargs["secret_file"] = str(tmp_path / "secret")
        return kwargs

    def test_response_credentials_fail_preflight_before_claim_or_mutation(
        self, tmp_path, monkeypatch
    ):
        kwargs = self._apply_kwargs(tmp_path)
        claim = Mock()
        update = Mock()
        monkeypatch.setattr(self.api, "claim_rollback_attempt", claim)
        monkeypatch.setattr(self.api, "update_integration", update)
        monkeypatch.setattr(
            self.api,
            "get_integration",
            Mock(return_value=_azure_live(secretKey="AZURE-PREFLIGHT-CANARY")),
        )
        with pytest.raises(self.api.ApiError, match="response-side credential"):
            self.api.apply_rollback(**kwargs)
        assert claim.call_count == 0
        assert update.call_count == 0
        assert not (kwargs["state_dir"] / "apply-state.json").exists()

    def test_response_credentials_in_postcondition_are_one_redacted_failure(
        self, tmp_path, monkeypatch, capsys
    ):
        kwargs = self._apply_kwargs(tmp_path)
        canary = "AZURE-POSTCONDITION-RESPONSE-CANARY"
        disabled = _azure_live(enabled=False)
        monkeypatch.setattr(
            self.api,
            "get_integration",
            Mock(
                side_effect=[
                    _azure_live(),
                    _azure_live(),
                    _azure_live(enabled=False, secretKey=canary),
                    disabled,
                ]
            ),
        )
        update = Mock(return_value=disabled)
        monkeypatch.setattr(self.api, "update_integration", update)
        with pytest.raises(self.api.ApiError, match="response-side credential") as error:
            self.api.apply_rollback(**kwargs)
        print(str(error.value))
        print(str(error.value), file=sys.stderr)
        captured = capsys.readouterr()
        journal_text = (kwargs["state_dir"] / "apply-state.json").read_text()
        steps = json.loads(journal_text)["steps"]
        assert update.call_count == 1
        assert sum(step["result"] == "failed" for step in steps) == 1
        assert all(step["result"] != "success" for step in steps)
        assert canary not in journal_text + captured.out + captured.err

    def test_wrong_or_drifted_preflight_prevents_mutation(self, tmp_path, monkeypatch):
        kwargs = self._apply_kwargs(tmp_path)
        update = Mock()
        monkeypatch.setattr(self.api, "update_integration", update)
        monkeypatch.setattr(
            self.api,
            "get_integration",
            Mock(return_value=_azure_live(type="GCP")),
        )
        with pytest.raises(self.api.ApiError, match="wrong provider"):
            self.api.apply_rollback(**kwargs)
        assert update.call_count == 0

        monkeypatch.setattr(
            self.api,
            "get_integration",
            Mock(side_effect=[_azure_live(), _azure_live(pollRate=600000)]),
        )
        with pytest.raises(self.api.ApiError, match="reviewed observed snapshot"):
            self.api.apply_rollback(**kwargs)
        assert update.call_count == 0

    def test_plan_time_revision_drift_and_new_duplicate_name_fail_before_claim(
        self, tmp_path, monkeypatch
    ):
        observed = tmp_path / "observed.json"
        reviewed = _azure_live(lastUpdated=100)
        self.api.write_observed_snapshot(
            observed, realm="us1", integrations=[reviewed]
        )
        app_id = _write_private_text(tmp_path / "app-id", "app")
        secret = _write_private_text(tmp_path / "secret", "secret")
        rendered = self.api.render_rollback_plan(
            tmp_path / "plan.json",
            realm="us1",
            action="disable",
            integration_id="azure-id-1",
            integration_name="test-azure",
            expected_enabled_state=True,
            observed_state_file=str(observed),
            app_id_file=str(app_id),
            secret_file=str(secret),
        )
        kwargs = {
            "realm": "us1",
            "token": "unused",
            "state_dir": tmp_path / "state",
            "plan_path": tmp_path / "plan.json",
            "plan_sha256": rendered["plan_hash"],
            "action": "disable",
            "integration_id": "azure-id-1",
            "apply_gate": True,
            "acknowledge_disable": "azure-id-1",
            "app_id_file": str(app_id),
            "secret_file": str(secret),
        }
        update = Mock()
        claim = Mock()
        monkeypatch.setattr(self.api, "update_integration", update)
        monkeypatch.setattr(self.api, "claim_rollback_attempt", claim)
        monkeypatch.setattr(
            self.api,
            "get_integration",
            Mock(return_value=_azure_live(lastUpdated=101)),
        )
        with pytest.raises(self.api.ApiError, match="reviewed observed snapshot"):
            self.api.apply_rollback(**kwargs)
        assert update.call_count == claim.call_count == 0

        get = Mock()
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(
            self.api,
            "list_azure_integrations",
            lambda *_: [reviewed, _azure_live(id="azure-id-2")],
        )
        with pytest.raises(self.api.ApiError, match="one exact reviewed name"):
            self.api.apply_rollback(**kwargs)
        assert get.call_count == update.call_count == claim.call_count == 0

    @pytest.mark.parametrize(
        "response",
        ({}, {"id": "other-id"}, {"id": 7}),
    )
    def test_disable_invalid_put_response_id_reconciles_without_retry(
        self, response, tmp_path, monkeypatch
    ):
        kwargs = self._apply_kwargs(tmp_path)
        get = Mock(side_effect=[_azure_live(), _azure_live(), _azure_live()])
        update = Mock(return_value=response)
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "update_integration", update)
        with pytest.raises(self.api.ApiError, match="operator resolution"):
            self.api.apply_rollback(**kwargs)
        assert update.call_count == 1
        assert get.call_count == 3

    def test_real_target_lock_uses_injected_canonical_root(self, tmp_path):
        root = tmp_path / "account-lock-root"
        with self.api._target_lock("us1", "azure-id-1") as yielded:
            assert yielded.path == root
            lock_files = list(root.glob("*.lock"))
            assert len(lock_files) == 1
            assert lock_files[0].stat().st_mode & 0o777 == 0o600

    def test_credential_binding_and_parse_fail_before_any_live_get(
        self, tmp_path, monkeypatch
    ):
        kwargs = self._apply_kwargs(tmp_path)
        get = Mock()
        update = Mock()
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "update_integration", update)
        Path(kwargs["secret_file"]).write_text("substituted-secret", encoding="utf-8")
        Path(kwargs["secret_file"]).chmod(0o600)
        with pytest.raises(self.api.ApiError, match="changed since plan review"):
            self.api.apply_rollback(**kwargs)
        assert get.call_count == 0
        assert update.call_count == 0

        kwargs = self._apply_kwargs(tmp_path / "malformed")
        Path(kwargs["app_id_file"]).write_bytes(b"\xff")
        Path(kwargs["app_id_file"]).chmod(0o600)
        with pytest.raises(self.api.ApiError, match="UTF-8"):
            self.api.apply_rollback(**kwargs)
        assert get.call_count == 0
        assert update.call_count == 0

    def test_disable_reinjects_credentials_and_redacts_plan_and_journal(self, tmp_path, monkeypatch):
        kwargs = self._apply_kwargs(tmp_path)
        disabled = _azure_live(enabled=False)
        monkeypatch.setattr(
            self.api,
            "get_integration",
            Mock(side_effect=[_azure_live(), _azure_live(), disabled, disabled]),
        )
        captured = {}

        def update_once(_realm, _token, _integration_id, payload, **_kwargs):
            captured.update(payload)
            return _azure_live(id=_integration_id, enabled=False)

        update = Mock(side_effect=update_once)
        monkeypatch.setattr(self.api, "update_integration", update)
        result = self.api.apply_rollback(**kwargs)
        assert result["result"] == "disabled"
        assert update.call_count == 1
        assert captured["appId"] == "azure-app-id-secret"
        assert captured["secretKey"] == "azure-secret-value"
        assert captured["enabled"] is False
        combined = kwargs["plan_path"].read_text() + (kwargs["state_dir"] / "apply-state.json").read_text()
        assert "azure-app-id-secret" not in combined
        assert "azure-secret-value" not in combined

    def test_disable_reads_each_bound_credential_file_once(self, tmp_path, monkeypatch):
        kwargs = self._apply_kwargs(tmp_path)
        original = self.api.read_secret_file_material
        opened = []

        def counted(path):
            opened.append(str(path))
            return original(path)

        disabled = _azure_live(enabled=False)
        monkeypatch.setattr(self.api, "read_secret_file_material", counted)
        monkeypatch.setattr(
            self.api,
            "get_integration",
            Mock(side_effect=[_azure_live(), _azure_live(), disabled, disabled]),
        )
        monkeypatch.setattr(
            self.api, "update_integration", Mock(return_value={"id": "azure-id-1"})
        )
        self.api.apply_rollback(**kwargs)
        assert opened == [kwargs["app_id_file"], kwargs["secret_file"]]

    def test_mocked_upsert_journal_never_contains_secrets(self, tmp_path, monkeypatch):
        app_id = _write_private_text(tmp_path / "upsert-app", "upsert-app-secret")
        secret = _write_private_text(tmp_path / "upsert-secret", "upsert-secret-value")
        monkeypatch.setattr(
            self.api,
            "list_azure_integrations",
            Mock(side_effect=[[], [_azure_live()]]),
        )
        monkeypatch.setattr(self.api, "get_integration", Mock(return_value=_azure_live()))
        monkeypatch.setattr(
            self.api,
            "create_integration",
            lambda _r, _t, _payload: _azure_live(id="azure-id-1"),
        )
        self.api.upsert(
            "us1",
            "unused",
            _azure_live(id=None),
            tmp_path / "upsert-state",
            app_id_file=str(app_id),
            secret_file=str(secret),
        )
        journal = (tmp_path / "upsert-state" / "apply-state.json").read_text()
        assert "upsert-app-secret" not in journal
        assert "upsert-secret-value" not in journal

    def test_put_error_is_one_attempt_then_exact_id_reconciliation(self, tmp_path, monkeypatch):
        kwargs = self._apply_kwargs(tmp_path)
        get = Mock(side_effect=[_azure_live(), _azure_live(), _azure_live()])
        update = Mock(side_effect=self.api.AmbiguousMutationError("ambiguous PUT"))
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "update_integration", update)
        with pytest.raises(self.api.ApiError, match="operator resolution"):
            self.api.apply_rollback(**kwargs)
        assert update.call_count == 1
        assert get.call_count == 3
        journal = (kwargs["state_dir"] / "apply-state.json").read_text()
        assert "reconciliation requires operator resolution" in journal

    def test_copied_plan_different_state_dir_is_permanently_consumed(
        self, tmp_path, monkeypatch
    ):
        kwargs = self._apply_kwargs(tmp_path / "first")
        get = Mock(return_value=_azure_live())
        update = Mock(side_effect=self.api.AmbiguousMutationError("ambiguous PUT"))
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "update_integration", update)
        with pytest.raises(self.api.ApiError, match="operator resolution"):
            self.api.apply_rollback(**kwargs)
        copied_dir = tmp_path / "copied-plan"
        copied_dir.mkdir()
        copied_plan = copied_dir / "reviewed-plan.json"
        shutil.copyfile(kwargs["plan_path"], copied_plan)
        copied_plan.chmod(0o600)
        replay = {
            **kwargs,
            "plan_path": copied_plan,
            "state_dir": tmp_path / "different-state-dir",
        }
        with pytest.raises(self.api.ApiError, match="already been attempted"):
            self.api.apply_rollback(**replay)
        assert update.call_count == 1

    def test_target_lock_serializes_copied_plan_across_output_dirs(
        self, tmp_path, monkeypatch
    ):
        first = self._apply_kwargs(tmp_path / "output-a")
        copy_dir = tmp_path / "output-b"
        copy_dir.mkdir()
        copied_plan = copy_dir / "rollback-plan.json"
        shutil.copyfile(first["plan_path"], copied_plan)
        copied_plan.chmod(0o600)
        second = {
            **first,
            "plan_path": copied_plan,
            "state_dir": copy_dir / "state",
        }
        state = {"enabled": True}
        state_guard = threading.Lock()
        get_calls = 0
        unexpected_get = threading.Event()
        mutation_entered = threading.Event()
        release_mutation = threading.Event()
        second_credentials_loaded = threading.Event()
        credential_loads = 0
        original_loader = self.api._load_azure_credential_material

        def load_credentials(*args):
            nonlocal credential_loads
            material = original_loader(*args)
            with state_guard:
                credential_loads += 1
                if credential_loads == 2:
                    second_credentials_loaded.set()
            return material

        def exact_get(*_args):
            nonlocal get_calls
            with state_guard:
                get_calls += 1
                if get_calls >= 3:
                    unexpected_get.set()
                enabled = state["enabled"]
            return _azure_live(enabled=enabled)

        def update_once(*_args, **_kwargs):
            mutation_entered.set()
            assert release_mutation.wait(5)
            with state_guard:
                state["enabled"] = False
            return {"id": "azure-id-1"}

        update = Mock(side_effect=update_once)
        monkeypatch.setattr(self.api, "_load_azure_credential_material", load_credentials)
        monkeypatch.setattr(self.api, "get_integration", exact_get)
        monkeypatch.setattr(self.api, "update_integration", update)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(self.api.apply_rollback, **first)
            assert mutation_entered.wait(5)
            second_future = pool.submit(self.api.apply_rollback, **second)
            assert second_credentials_loaded.wait(5)
            assert not unexpected_get.wait(0.15)
            release_mutation.set()
            assert first_future.result(timeout=5)["result"] == "disabled"
            with pytest.raises(self.api.ApiError):
                second_future.result(timeout=5)
        assert update.call_count == 1

    def test_delete_error_is_one_attempt_then_exact_id_reconciliation(self, tmp_path, monkeypatch):
        kwargs = self._apply_kwargs(tmp_path, action="delete")
        get = Mock(side_effect=[_azure_live(), _azure_live(), _azure_live()])
        delete = Mock(side_effect=self.api.AmbiguousMutationError("ambiguous DELETE"))
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "delete_integration", delete)
        with pytest.raises(self.api.ApiError, match="operator resolution"):
            self.api.apply_rollback(**kwargs)
        assert delete.call_count == 1
        assert get.call_count == 3

    def test_unexpected_disable_postcondition_never_retries_put(self, tmp_path, monkeypatch):
        kwargs = self._apply_kwargs(tmp_path)
        get = Mock(side_effect=[_azure_live(), _azure_live()] + [_azure_live()] * 5)
        update = Mock(return_value={"id": "azure-id-1"})
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "update_integration", update)
        monkeypatch.setattr(self.api.time, "sleep", Mock())
        with pytest.raises(self.api.ApiError, match="postcondition"):
            self.api.apply_rollback(**kwargs)
        assert update.call_count == 1
        journal = (kwargs["state_dir"] / "apply-state.json").read_text()
        assert "bounded disable postcondition polling failed" in journal

    def test_disable_rejects_stable_post_put_configuration_drift(
        self, tmp_path, monkeypatch
    ):
        kwargs = self._apply_kwargs(tmp_path)
        drifted = _azure_live(enabled=False, pollRate=600000)
        get = Mock(side_effect=[_azure_live(), _azure_live(), drifted, drifted])
        update = Mock(return_value={"id": "azure-id-1"})
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "update_integration", update)
        with pytest.raises(self.api.ApiError, match="configuration fingerprint changed"):
            self.api.apply_rollback(**kwargs)
        assert update.call_count == 1
        journal = (kwargs["state_dir"] / "apply-state.json").read_text()
        assert "configuration fingerprint changed during disable" in journal

    @pytest.mark.parametrize(
        "action,scenario",
        (
            ("disable", "final-get-error"),
            ("disable", "final-identity-drift"),
            ("disable", "fingerprint-drift"),
            ("delete", "final-get-error"),
            ("delete", "final-identity-drift"),
        ),
    )
    def test_late_postmutation_verification_failures_are_journaled_once(
        self, action, scenario, tmp_path, monkeypatch
    ):
        kwargs = self._apply_kwargs(tmp_path, action=action)
        if action == "disable":
            confirmed = _azure_live(enabled=False)
            if scenario == "final-get-error":
                final = self.api.ApiError("final exact GET failed")
            elif scenario == "final-identity-drift":
                final = _azure_live(enabled=False, name="drifted-name")
            else:
                confirmed = _azure_live(enabled=False, pollRate=600000)
                final = _azure_live(enabled=False, pollRate=600000)
            get = Mock(side_effect=[_azure_live(), _azure_live(), confirmed, final])
            mutation = Mock(return_value={"id": "azure-id-1"})
            monkeypatch.setattr(self.api, "update_integration", mutation)
        else:
            final = (
                self.api.ApiError("final exact GET failed")
                if scenario == "final-get-error"
                else _azure_live(name="drifted-name")
            )
            get = Mock(side_effect=[_azure_live(), _azure_live(), {}, final])
            mutation = Mock(return_value={})
            monkeypatch.setattr(self.api, "delete_integration", mutation)
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api.time, "sleep", Mock())
        with pytest.raises(self.api.ApiError):
            self.api.apply_rollback(**kwargs)
        assert mutation.call_count == 1
        steps = json.loads(
            (kwargs["state_dir"] / "apply-state.json").read_text()
        )["steps"]
        failed = [entry for entry in steps if entry.get("result") == "failed"]
        assert len(failed) == 1
        assert failed[0]["step"] == action

    def test_claim_failure_aborts_before_http_mutation(self, tmp_path, monkeypatch):
        kwargs = self._apply_kwargs(tmp_path)
        update = Mock()
        monkeypatch.setattr(
            self.api, "get_integration", Mock(side_effect=[_azure_live(), _azure_live()])
        )
        monkeypatch.setattr(self.api, "update_integration", update)
        monkeypatch.setattr(
            self.api,
            "claim_rollback_attempt",
            Mock(side_effect=PermissionError("claim write failed")),
        )
        with pytest.raises(self.api.ApiError, match="claim write failed"):
            self.api.apply_rollback(**kwargs)
        assert update.call_count == 0

    def test_delete_rejects_credential_flags_without_reads_or_mutation(
        self, tmp_path, monkeypatch
    ):
        kwargs = self._apply_kwargs(tmp_path, action="delete")
        credential_read = Mock(side_effect=AssertionError("credential read"))
        get = Mock()
        delete = Mock()
        monkeypatch.setattr(self.api, "read_secret_file_material", credential_read)
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "delete_integration", delete)
        kwargs["app_id_file"] = str(tmp_path / "unused-app")
        with pytest.raises(self.api.ApiError, match="rejects Azure credential"):
            self.api.apply_rollback(**kwargs)
        assert credential_read.call_count == 0
        assert get.call_count == 0
        assert delete.call_count == 0

    def test_disable_postcondition_polling_and_lock_scope(self, tmp_path, monkeypatch):
        kwargs = self._apply_kwargs(tmp_path)
        locked = {"active": False}

        @contextmanager
        def lock(_realm, _integration_id):
            assert not locked["active"]
            locked["active"] = True
            try:
                claim_root = tmp_path / "fake-claim-root"
                claim_root.mkdir(mode=0o700, exist_ok=True)
                yield claim_root
            finally:
                locked["active"] = False

        responses = iter(
            [_azure_live(), _azure_live(), _azure_live(), _azure_live(enabled=False), _azure_live(enabled=False)]
        )

        def get_locked(*_args):
            assert locked["active"]
            return next(responses)

        update = Mock(side_effect=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()) if not locked["active"] else {"id": "azure-id-1"})
        journal = Mock(side_effect=lambda *_args, **_kwargs: assert_locked(locked))

        def assert_locked(flag):
            assert flag["active"]

        monkeypatch.setattr(self.api, "_target_lock", lock)
        monkeypatch.setattr(self.api, "get_integration", get_locked)
        monkeypatch.setattr(self.api, "update_integration", update)
        monkeypatch.setattr(self.api, "append_step", journal)
        monkeypatch.setattr(self.api.time, "sleep", Mock())
        assert self.api.apply_rollback(**kwargs)["result"] == "disabled"
        assert update.call_count == 1
        assert journal.call_count == 1
        assert locked["active"] is False

    def test_delete_verifies_two_http_200_empty_reads(self, tmp_path, monkeypatch):
        kwargs = self._apply_kwargs(tmp_path, action="delete")
        get = Mock(side_effect=[_azure_live(), _azure_live(), {}, {}])
        delete = Mock(return_value={})
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "delete_integration", delete)
        assert self.api.apply_rollback(**kwargs)["result"] == "deleted"
        assert delete.call_count == 1
        assert get.call_count == 4


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

    @pytest.mark.parametrize(
        "mode",
        (
            "--render",
            "--validate",
            "--doctor",
            "--discover",
            "--quickstart",
            "--quickstart-from-live",
            "--explain",
            "--list-services",
        ),
    )
    @pytest.mark.parametrize("apply_first", (False, True))
    def test_apply_conflicts_with_every_separate_primary_mode_in_either_order(
        self, mode, apply_first, tmp_path
    ):
        ordered = ["--apply", mode] if apply_first else [mode, "--apply"]
        result = subprocess.run(
            ["bash", str(SETUP), *ordered, "--output-dir", str(tmp_path / "out")],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 2
        assert "--apply conflicts with a separate primary mode" in result.stderr

    @pytest.mark.parametrize(
        "arguments",
        (
            ("--token=AZURE-SHELL-CANARY",),
            ("--client-secret=AZURE-SHELL-CANARY",),
            ("--token", "AZURE-SHELL-CANARY"),
            ("--tokne=AZURE-SHELL-CANARY",),
        ),
    )
    def test_shell_secret_and_unknown_flags_never_echo_values(self, arguments):
        result = subprocess.run(
            ["bash", str(SETUP), *arguments],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode != 0
        assert "AZURE-SHELL-CANARY" not in result.stdout + result.stderr

    @pytest.mark.parametrize(
        "arguments",
        (
            ("--token=AZURE-PYTHON-CANARY",),
            ("--client-secret=AZURE-PYTHON-CANARY",),
            ("--tokne=AZURE-PYTHON-CANARY",),
        ),
    )
    def test_python_secret_and_unknown_flags_never_echo_values(self, arguments):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "azure_integration_api.py"), *arguments],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode != 0
        assert "AZURE-PYTHON-CANARY" not in result.stdout + result.stderr

    def test_python_cli_sanitizes_unsafe_token_paths_and_keeps_safe_paths(
        self, tmp_path, monkeypatch
    ):
        for name in (
            "SPLUNK_ACCESS_TOKEN",
            "SPLUNK_REALM",
            "SPLUNK_O11Y_TOKEN_FILE",
            "SPLUNK_O11Y_REALM",
            "O11Y_ACCESS_TOKEN",
            "O11Y_REALM",
        ):
            monkeypatch.delenv(name, raising=False)
        state_dir = tmp_path / "nonexistent-state"
        unsafe_path = tmp_path / "client_secret=AZURE-PATH-ERROR-CANARY"
        safe_path = tmp_path / "client-secret-material.json"

        def invoke(token_path: Path):
            return subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "azure_integration_api.py"),
                    "--realm",
                    "us1",
                    "--state-dir",
                    str(state_dir),
                    "--token-file",
                    str(token_path),
                    "--integration-id",
                    "azure-id-1",
                    "get",
                ],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )

        unsafe = invoke(unsafe_path)
        assert unsafe.returncode != 0
        assert "AZURE-PATH-ERROR-CANARY" not in unsafe.stdout + unsafe.stderr
        assert "could not be opened safely" not in unsafe.stdout + unsafe.stderr

        safe = invoke(safe_path)
        assert safe.returncode != 0
        assert str(safe_path) in safe.stdout + safe.stderr
        assert "could not be opened safely" in safe.stdout + safe.stderr

    def test_setup_rollback_never_echoes_unsafe_credential_paths(
        self, tmp_path, monkeypatch
    ):
        for name in (
            "SPLUNK_ACCESS_TOKEN",
            "SPLUNK_REALM",
            "SPLUNK_O11Y_TOKEN_FILE",
            "SPLUNK_O11Y_REALM",
            "O11Y_ACCESS_TOKEN",
            "O11Y_REALM",
        ):
            monkeypatch.delenv(name, raising=False)
        observed = _write_private_text(tmp_path / "observed.json", "{}")
        valid_app = _write_private_text(tmp_path / "app-id", "test-app-id\n")
        valid_secret = _write_private_text(tmp_path / "secret", "test-secret\n")
        valid_token = _write_private_text(tmp_path / "token", "test-token\n")
        unsafe_names = (
            "client_secret=AZURE-SHELL-PATH-CANARY",
            "e30.e30.QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo",
        )

        for unsafe_name in unsafe_names:
            unsafe = tmp_path / unsafe_name
            render_cases = (
                ("--app-id-file", unsafe, "--secret-file", valid_secret),
                ("--app-id-file", valid_app, "--secret-file", unsafe),
            )
            apply_cases = (
                (
                    "--app-id-file",
                    unsafe,
                    "--secret-file",
                    valid_secret,
                    "--token-file",
                    valid_token,
                ),
                (
                    "--app-id-file",
                    valid_app,
                    "--secret-file",
                    unsafe,
                    "--token-file",
                    valid_token,
                ),
                (
                    "--app-id-file",
                    valid_app,
                    "--secret-file",
                    valid_secret,
                    "--token-file",
                    unsafe,
                ),
            )
            for credentials in render_cases:
                result = subprocess.run(
                    [
                        "bash",
                        str(SETUP),
                        "--rollback",
                        "disable",
                        "--realm",
                        "us1",
                        "--integration-id",
                        "azure-id-1",
                        "--integration-name",
                        "test-azure",
                        "--observed-state-file",
                        str(observed),
                        "--output-dir",
                        str(tmp_path / "render-output"),
                        *(str(value) for value in credentials),
                    ],
                    capture_output=True,
                    text=True,
                    cwd=str(REPO_ROOT),
                )
                assert result.returncode != 0
                assert unsafe_name not in result.stdout + result.stderr
            for credentials in apply_cases:
                result = subprocess.run(
                    [
                        "bash",
                        str(SETUP),
                        "--rollback",
                        "disable",
                        "--apply",
                        "--realm",
                        "us1",
                        "--integration-id",
                        "azure-id-1",
                        "--plan-file",
                        str(tmp_path / "unread-plan.json"),
                        "--plan-hash",
                        "a" * 64,
                        "--accept-disable-integration",
                        "azure-id-1",
                        "--output-dir",
                        str(tmp_path / "apply-output"),
                        *(str(value) for value in credentials),
                    ],
                    capture_output=True,
                    text=True,
                    cwd=str(REPO_ROOT),
                )
                assert result.returncode != 0
                assert unsafe_name not in result.stdout + result.stderr

        loose = tmp_path / "client_secret=AZURE-LOOSE-PATH-CANARY"
        loose.write_text("test-only\n", encoding="utf-8")
        loose.chmod(0o644)
        for apply_args in (
            (
                "--integration-name",
                "test-azure",
                "--observed-state-file",
                observed,
            ),
            (
                "--apply",
                "--plan-file",
                tmp_path / "unread-plan.json",
                "--plan-hash",
                "a" * 64,
                "--accept-disable-integration",
                "azure-id-1",
                "--token-file",
                valid_token,
            ),
        ):
            result = subprocess.run(
                [
                    "bash",
                    str(SETUP),
                    "--rollback",
                    "disable",
                    "--realm",
                    "us1",
                    "--integration-id",
                    "azure-id-1",
                    "--app-id-file",
                    str(loose),
                    "--secret-file",
                    str(valid_secret),
                    "--output-dir",
                    str(tmp_path / "loose-output"),
                    *(str(value) for value in apply_args),
                ],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            assert result.returncode != 0
            assert "AZURE-LOOSE-PATH-CANARY" not in result.stdout + result.stderr
            assert "loose permissions" in result.stdout + result.stderr

    @pytest.mark.parametrize(
        "extra",
        (
            ("--token-file", "/not-opened/token"),
            ("--allow-loose-token-perms",),
            ("--plan-hash", "0" * 64),
            ("--accept-delete-integration", "azure-id-1"),
        ),
    )
    def test_offline_delete_render_rejects_apply_only_flags_without_file_reads(
        self, extra, tmp_path
    ):
        observed = tmp_path / "observed.json"
        _load_api_client().write_observed_snapshot(
            observed, realm="us1", integrations=[_azure_live()]
        )
        result = subprocess.run(
            [
                "bash",
                str(SETUP),
                "--rollback",
                "delete",
                "--realm",
                "us1",
                "--integration-id",
                "azure-id-1",
                "--integration-name",
                "test-azure",
                "--observed-state-file",
                str(observed),
                "--output-dir",
                str(tmp_path / "out"),
                *extra,
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 2
        assert not (tmp_path / "out" / "state" / "rollback-plan.json").exists()

    def test_delete_render_rejects_credential_paths_without_opening_them(self, tmp_path):
        observed = tmp_path / "observed.json"
        _load_api_client().write_observed_snapshot(
            observed, realm="us1", integrations=[_azure_live()]
        )
        result = subprocess.run(
            [
                "bash",
                str(SETUP),
                "--rollback",
                "delete",
                "--realm",
                "us1",
                "--integration-id",
                "azure-id-1",
                "--integration-name",
                "test-azure",
                "--observed-state-file",
                str(observed),
                "--app-id-file",
                "/not-opened/app-id",
                "--secret-file",
                "/not-opened/secret",
                "--output-dir",
                str(tmp_path / "out"),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 2
        assert "reject Azure credential files" in result.stderr

    def test_bare_rollback_renders_only_disable_plan_without_spec_tree(self, tmp_path):
        observed = tmp_path / "observed.json"
        _load_api_client().write_observed_snapshot(
            observed, realm="us1", integrations=[_azure_live()]
        )
        app_id = _write_private_text(tmp_path / "app-id", "app-id")
        secret = _write_private_text(tmp_path / "secret", "secret")
        output = tmp_path / "out"
        template_before = TEMPLATE.read_bytes()
        result = subprocess.run(
            [
                "bash",
                str(SETUP),
                "--rollback",
                "--realm",
                "us1",
                "--integration-id",
                "azure-id-1",
                "--integration-name",
                "test-azure",
                "--observed-state-file",
                str(observed),
                "--app-id-file",
                str(app_id),
                "--secret-file",
                str(secret),
                "--output-dir",
                str(output),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads((output / "state" / "rollback-plan.json").read_text())[
            "action"
        ] == "disable"
        assert not (output / "rest").exists()
        assert TEMPLATE.read_bytes() == template_before

    def test_bare_rollback_refuses_apply_with_exact_message(self, tmp_path):
        result = subprocess.run(
            [
                "bash",
                str(SETUP),
                "--rollback",
                "--apply",
                "--realm",
                "us1",
                "--integration-id",
                "azure-id-1",
                "--output-dir",
                str(tmp_path / "out"),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 2
        assert (
            "rollback action was not explicit; use --rollback disable or --rollback delete"
            in result.stderr
        )

    def test_rollback_delete_is_offline_render_only(self, tmp_path):
        observed = tmp_path / "observed.json"
        _load_api_client().write_observed_snapshot(
            observed, realm="us1", integrations=[_azure_live()]
        )
        output = tmp_path / "rendered"
        result = subprocess.run(
            [
                "bash",
                str(SETUP),
                "--rollback",
                "delete",
                "--output-dir",
                str(output),
                "--realm",
                "us1",
                "--integration-id",
                "azure-id-1",
                "--integration-name",
                "test-azure",
                "--observed-state-file",
                str(observed),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        plan = json.loads((output / "state" / "rollback-plan.json").read_text())
        assert plan["action"] == "delete"
        assert "--accept-delete-integration azure-id-1" in result.stdout

    def test_apply_flag_order_cannot_change_rollback_behavior(self, tmp_path):
        common = [
            "--realm",
            "us1",
            "--integration-id",
            "azure-id-1",
            "--output-dir",
            str(tmp_path / "out"),
        ]
        commands = (
            ["bash", str(SETUP), "--apply", "--rollback", "delete", *common],
            ["bash", str(SETUP), "--rollback", "delete", "--apply", *common],
        )
        results = [
            subprocess.run(command, capture_output=True, text=True, cwd=str(REPO_ROOT))
            for command in commands
        ]
        assert [result.returncode for result in results] == [2, 2]
        assert all("--token-file and --plan-hash" in result.stderr for result in results)

    def test_rollback_integration_alias_warns_and_renders_disable(self, tmp_path):
        observed = tmp_path / "observed.json"
        _load_api_client().write_observed_snapshot(
            observed, realm="us1", integrations=[_azure_live()]
        )
        output = tmp_path / "rendered"
        app_id = _write_private_text(tmp_path / "app-id", "azure-app-id-secret")
        secret = _write_private_text(tmp_path / "secret", "azure-secret-value")
        result = subprocess.run(
            [
                "bash",
                str(SETUP),
                "--rollback",
                "integration",
                "--output-dir",
                str(output),
                "--realm",
                "us1",
                "--integration-id",
                "azure-id-1",
                "--integration-name",
                "test-azure",
                "--observed-state-file",
                str(observed),
                "--app-id-file",
                str(app_id),
                "--secret-file",
                str(secret),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "deprecated" in result.stderr
        plan = json.loads((output / "state" / "rollback-plan.json").read_text())
        assert plan["action"] == "disable"


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
