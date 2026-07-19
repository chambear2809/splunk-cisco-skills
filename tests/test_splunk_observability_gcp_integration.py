"""Tests for the splunk-observability-gcp-integration skill.

Covers:
- Valid spec (SA Key mode) renders cleanly (type=GCP, pollRate, shape)
- Valid spec (WIF mode) renders the official config-file contract
- Coverage keys completeness
- REST payload: type=GCP, authMethod, projectServiceKeys placeholder, pollRate in ms
- Terraform: signalfx_gcp_integration resource present only for SA-key mode
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


def _load_api_client():
    spec = importlib.util.spec_from_file_location(
        "sgcp_api", SCRIPTS_DIR / "gcp_integration_api.py"
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


def _write_sa_key(path: Path, project_id: str, *, private_key: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "type": "service_account",
        "project_id": project_id,
        "private_key_id": f"key-{project_id}",
        "private_key": private_key or "-----BEGIN PRIVATE KEY-----\nline-one\nline-two\n-----END PRIVATE KEY-----\n",
        "client_email": f"collector@{project_id}.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)
    return path


def _gcp_live(**overrides) -> dict:
    live = {
        "id": "gcp-id-1",
        "type": "GCP",
        "name": "test-gcp",
        "enabled": True,
        "authMethod": "SERVICE_ACCOUNT_KEY",
        "projectServiceKeys": [
            {"projectId": "project-a"},
            {"projectId": "project-b"},
        ],
        "projects": {"syncMode": "ALL_REACHABLE"},
        "services": ["compute"],
        "pollRate": 300000,
    }
    live.update(overrides)
    return live


def _gcp_plan(
    api,
    tmp_path: Path,
    *,
    action: str = "disable",
    auth_method: str = "service-account",
    integration_name: str = "test-gcp",
    expected_enabled_state: bool = True,
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    plan_path = tmp_path / f"gcp-{action}-plan.json"
    observed_path = tmp_path / f"gcp-{action}-observed.json"
    observed_live = _gcp_live(
        name=integration_name,
        enabled=expected_enabled_state,
    )
    wif_config_raw = '{"type":"external_account","audience":"reviewed"}'
    if auth_method == "wif":
        observed_live["authMethod"] = "WORKLOAD_IDENTITY_FEDERATION"
        observed_live.pop("projectServiceKeys", None)
        observed_live["wifSplunkIdentity"] = "reviewed-read-only-identity"
        observed_live["workloadIdentityFederationConfig"] = wif_config_raw
    api.write_observed_snapshot(
        observed_path,
        realm="us1",
        integrations=[observed_live],
    )
    credential_args = {}
    if action == "disable" and auth_method == "service-account":
        credential_args["key_files"] = [
            str(_write_sa_key(tmp_path / "project-b.json", "project-b")),
            str(_write_sa_key(tmp_path / "project-a.json", "project-a")),
        ]
    elif action == "disable" and auth_method == "wif":
        config = tmp_path / "gcp_wif_config.json"
        config.write_text(wif_config_raw, encoding="utf-8")
        config.chmod(0o600)
        credential_args["wif_config_file"] = str(config)
    rendered = api.render_rollback_plan(
        plan_path,
        realm="us1",
        action=action,
        integration_id="gcp-id-1",
        integration_name=integration_name,
        expected_enabled_state=expected_enabled_state,
        observed_state_file=str(observed_path),
        **credential_args,
    )
    return plan_path, rendered["plan_hash"]


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
            "config_file": "/tmp/gcp_wif_config.json",
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
        assert payload["workloadIdentityFederationConfig"] == (
            "${WORKLOAD_IDENTITY_FEDERATION_CONFIG_FROM_FILE}"
        )
        assert "workloadIdentityPoolId" not in payload
        assert "workloadIdentityProviderId" not in payload
        assert "projectServiceKeys" not in payload

    def test_rest_payload_projects_sync_mode(self, tmp_path):
        self._render(_valid_sa_key_spec(), tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        assert payload["projects"] == {"syncMode": "ALL_REACHABLE"}

    def test_rest_payload_project_key_placeholder(self, tmp_path):
        self._render(_valid_sa_key_spec(), tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        psk = payload.get("projectServiceKeys", [])
        assert len(psk) == 1
        assert "${PROJECT_KEY_FROM_FILE}" in psk[0].get("projectKey", "")

    def test_key_file_overrides_map_manifest_by_project_id_not_flag_order(
        self, tmp_path
    ):
        spec = _valid_sa_key_spec()
        spec["authentication"]["project_service_keys"] = [
            {"project_id": "project-a", "key_file": "/placeholder/a.json"},
            {"project_id": "project-b", "key_file": "/placeholder/b.json"},
        ]
        key_a = _write_sa_key(tmp_path / "a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "b.json", "project-b")
        validated = self.mod.validate_spec(
            spec,
            key_file_overrides=[str(key_b), str(key_a)],
        )
        output = tmp_path / "rendered"
        self.mod.render(validated, output)
        manifest = json.loads(
            (output / "rest" / "project-key-file-manifest.json").read_text()
        )
        assert manifest == [
            {"projectId": "project-a", "keyFile": str(key_a)},
            {"projectId": "project-b", "keyFile": str(key_b)},
        ]

    def test_key_file_override_mapping_rejects_duplicate_and_incomplete_coverage(
        self, tmp_path
    ):
        duplicate_spec = _valid_sa_key_spec()
        duplicate_spec["authentication"]["project_service_keys"] = [
            {"project_id": "project-a", "key_file": "/placeholder/a.json"},
            {"project_id": "project-a", "key_file": "/placeholder/b.json"},
        ]
        with pytest.raises(self.mod.RenderError, match="duplicate project_id"):
            self.mod.validate_spec(duplicate_spec)

        key_a = _write_sa_key(tmp_path / "a.json", "project-a")
        duplicate_a = _write_sa_key(tmp_path / "duplicate-a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "b.json", "project-b")
        key_c = _write_sa_key(tmp_path / "c.json", "project-c")

        def two_project_spec():
            spec = _valid_sa_key_spec()
            spec["authentication"]["project_service_keys"] = [
                {"project_id": "project-a", "key_file": "/placeholder/a.json"},
                {"project_id": "project-b", "key_file": "/placeholder/b.json"},
            ]
            return spec

        with pytest.raises(self.mod.RenderError, match="duplicate project_id"):
            self.mod.validate_spec(
                two_project_spec(),
                key_file_overrides=[str(key_a), str(duplicate_a)],
            )
        with pytest.raises(self.mod.RenderError, match="coverage mismatch.*missing"):
            self.mod.validate_spec(
                two_project_spec(), key_file_overrides=[str(key_a)]
            )
        with pytest.raises(self.mod.RenderError, match="coverage mismatch.*extra"):
            self.mod.validate_spec(
                two_project_spec(),
                key_file_overrides=[str(key_a), str(key_b), str(key_c)],
            )

    def test_rest_payload_poll_rate_milliseconds(self, tmp_path):
        self._render(_valid_sa_key_spec(), tmp_path)
        payload = json.loads((tmp_path / "rest" / "create.json").read_text())
        assert payload["pollRate"] == 300000

    def test_terraform_signalfx_resource(self, tmp_path):
        self._render(_valid_sa_key_spec(), tmp_path)
        tf = (tmp_path / "terraform" / "main.tf").read_text()
        assert "signalfx_gcp_integration" in tf
        assert "poll_rate is in SECONDS" in tf
        assert "poll_rate = 300\n" in tf
        assert "poll_rate = 300000" not in tf

        reference = (SKILL_DIR / "reference.md").read_text(encoding="utf-8")
        assert "poll_rate = 300  # seconds" in reference
        assert "Terraform provider accepts `poll_rate` in **seconds**" in reference
        assert "poll_rate = 300000" not in reference
        assert "Terraform resource is in **milliseconds**" not in reference

    def test_reference_distinguishes_read_and_mutation_tokens(self):
        reference = (SKILL_DIR / "reference.md").read_text(encoding="utf-8")
        assert "any session/User API access token" in reference
        assert "associated with an\n  administrator" in reference
        assert "administrator session/User API access token" not in reference

    def test_wif_does_not_claim_terraform_pool_provider_fields(self, tmp_path):
        self._render(_valid_wif_spec(), tmp_path)
        tf = (tmp_path / "terraform" / "main.tf").read_text()
        assert 'resource "signalfx_gcp_integration"' not in tf
        assert "workload_identity_pool_id" not in tf
        assert "workload_identity_provider_id" not in tf

    def test_gcloud_cli_scripts_rendered(self, tmp_path):
        self._render(_valid_sa_key_spec(), tmp_path)
        assert (tmp_path / "gcloud-cli" / "create-sa.sh").exists()
        assert (tmp_path / "gcloud-cli" / "bind-roles.sh").exists()

    def test_wif_does_not_render_gcloud_pool_provider_claims(self, tmp_path):
        self._render(_valid_wif_spec(), tmp_path)
        assert not (tmp_path / "gcloud-cli").exists()

    def test_state_directory_created(self, tmp_path):
        self._render(_valid_sa_key_spec(), tmp_path)
        assert (tmp_path / "state" / "apply-state.json").exists()
        assert (tmp_path / "state" / "credential-hashes.json").exists()

    def test_coverage_report_exists(self, tmp_path):
        self._render(_valid_sa_key_spec(), tmp_path)
        data = json.loads((tmp_path / "coverage-report.json").read_text())
        assert data["realm"] == "us1"
        assert data["integration_name"] == "test-gcp"
        assert data["auth_method"] == "SERVICE_ACCOUNT_KEY"
        assert data["projects_sync_mode"] == "ALL_REACHABLE"

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

    def test_legacy_wif_pool_provider_fields_rejected(self):
        spec = _valid_wif_spec()
        spec["authentication"]["workload_identity_federation"] = {
            "pool_id": "fabricated-pool",
            "provider_id": "fabricated-provider",
        }
        with pytest.raises(self.mod.RenderError, match="unsupported legacy WIF fields"):
            self.mod.validate_spec(spec)

    def test_selected_projects_require_ids(self):
        spec = _valid_sa_key_spec()
        spec["projects"] = {"sync_mode": "SELECTED", "selected_project_ids": []}
        with pytest.raises(self.mod.RenderError, match="selected_project_ids"):
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


class TestGCPApiSecurity:
    def setup_method(self):
        self.api = _load_api_client()

    def test_provider_apply_state_import_is_concurrency_safe(self, monkeypatch):
        helper_name = "skills.splunk-observability-gcp-integration.scripts._apply_state"
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
                    f"concurrent_gcp_api_{index}",
                    SCRIPTS_DIR / "gcp_integration_api.py",
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
        helper_name = "skills.splunk-observability-gcp-integration.scripts._apply_state"
        probe_name = "gcp_import_overlap_probe"
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
        spec = importlib.util.spec_from_file_location("gcp_import_overlap_api", api_path)
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
                str(SCRIPTS_DIR / "gcp_integration_api.py"),
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
        helper_name = "skills.splunk-observability-gcp-integration.scripts._apply_state"
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
            [sys.executable, str(SCRIPTS_DIR / "gcp_integration_api.py"), "--help"],
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

    @pytest.mark.parametrize("allow_legacy", (False, True))
    def test_current_all_reachable_rejects_empty_present_selected_project_ids(
        self, allow_legacy
    ):
        payload = {
            "projects": {
                "syncMode": "ALL_REACHABLE",
                "selectedProjectIds": [],
            }
        }

        with pytest.raises(self.api.ApiError, match="must be absent"):
            self.api._validate_projects_contract(
                payload,
                allow_legacy=allow_legacy,
            )
        with pytest.raises(self.api.ApiError, match="must be absent"):
            self.api._normalize_projects_contract(payload)

    @pytest.mark.parametrize("allow_legacy", (False, True))
    def test_current_all_reachable_accepts_absent_selected_project_ids(
        self, allow_legacy
    ):
        payload = {"projects": {"syncMode": "ALL_REACHABLE"}}

        self.api._validate_projects_contract(
            payload,
            allow_legacy=allow_legacy,
        )
        assert self.api._normalize_projects_contract(payload)["projects"] == {
            "syncMode": "ALL_REACHABLE"
        }

    def test_legacy_all_empty_project_ids_normalizes_without_ids(self):
        payload = {"projects": {"syncMode": "ALL", "projectIds": []}}

        assert self.api._normalize_projects_contract(payload)["projects"] == {
            "syncMode": "ALL_REACHABLE"
        }

    def test_disable_payload_rejects_current_all_reachable_empty_present_ids(
        self, tmp_path
    ):
        key_a = _write_sa_key(tmp_path / "project-a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "project-b.json", "project-b")
        material = self.api._load_gcp_credential_material(
            [str(key_b), str(key_a)],
            "",
        )
        live = _gcp_live(
            projects={
                "syncMode": "ALL_REACHABLE",
                "selectedProjectIds": [],
            }
        )

        with pytest.raises(self.api.ApiError, match="must be absent"):
            self.api._build_disable_payload(live, material)

    def test_disable_payload_keeps_valid_all_reachable_ids_absent(self, tmp_path):
        key_a = _write_sa_key(tmp_path / "project-a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "project-b.json", "project-b")
        material = self.api._load_gcp_credential_material(
            [str(key_b), str(key_a)],
            "",
        )

        payload = self.api._build_disable_payload(_gcp_live(), material)

        assert payload["projects"] == {"syncMode": "ALL_REACHABLE"}
        assert payload["enabled"] is False

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
                "gcp_integration_api.py",
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
            "https://api.us1.observability.splunkcloud.com/v2/integration?type=GCP&limit=1&offset=0&x=1",
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
        assert (
            self.api._NoRedirectHandler().redirect_request(
                None, None, 302, "moved", {}, "https://evil"
            )
            is None
        )

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
            "https://api.us1.observability.splunkcloud.com/v2/integration/gcp-id-1",
            503,
            "unavailable",
            {"Retry-After": "999999"},
            None,
        )
        sleep = Mock()
        monkeypatch.setattr(self.api, "build_opener", lambda *_: opener)
        monkeypatch.setattr(self.api.time, "sleep", sleep)
        with pytest.raises(self.api.AmbiguousMutationError, match="HTTP 503"):
            self.api._request(
                method,
                "https://api.us1.observability.splunkcloud.com/v2/integration/gcp-id-1",
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
                "?type=GCP&limit=1&offset=0",
                "unused",
            )
        assert opener.open.call_count == 3
        assert sleep.call_count == 2

    @pytest.mark.parametrize(
        "method,failure",
        (
            ("PUT", TimeoutError("read timed out")),
            ("POST", TimeoutError("read timed out")),
            ("DELETE", TimeoutError("read timed out")),
        ),
    )
    def test_mutation_response_read_timeout_is_ambiguous_once(
        self, method, failure, monkeypatch
    ):
        response = Mock(status=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.side_effect = failure
        opener = Mock()
        opener.open.return_value = response
        monkeypatch.setattr(self.api, "build_opener", lambda *_: opener)
        url = "https://api.us1.observability.splunkcloud.com/v2/integration"
        if method != "POST":
            url += "/gcp-id-1"
        with pytest.raises(self.api.AmbiguousMutationError, match="ambiguous"):
            self.api._request(
                method,
                url,
                "unused",
                {"enabled": True} if method != "DELETE" else None,
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
                "PUT",
                "https://api.us1.observability.splunkcloud.com/v2/integration/gcp-id-1",
                "unused",
                {"enabled": True},
            )
        assert opener.open.call_count == 1

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
                "https://api.us1.observability.splunkcloud.com/v2/integration/gcp-id-1",
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
                "https://api.us1.observability.splunkcloud.com/v2/integration/gcp-id-1",
                "unused",
            )
        assert opener.open.call_count == 1

        response.read.return_value = b""
        assert self.api._request(
            "DELETE",
            "https://api.us1.observability.splunkcloud.com/v2/integration/gcp-id-1",
            "unused",
        ) == {}
        assert self.api._request(
            "GET",
            "https://api.us1.observability.splunkcloud.com/v2/integration/gcp-id-1",
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
                "https://api.us1.observability.splunkcloud.com/v2/integration/gcp-id-1",
                "unused",
            )

    def test_redaction_covers_unknown_key_canaries_but_preserves_identifiers(self):
        unsafe_assignment_key = "client_secret=GCP-DICT-KEY-CANARY"
        unsafe_jwt_key = "e30.e30.QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo"
        unsafe_digest_jwt_key = unsafe_jwt_key
        nested_unicode_key = "refresh_t\\u005cu006fken=GCP-NESTED-DICT-KEY-CANARY"
        value = {
            "nested": {
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
            },
            "idempotency_key": "operation-identifier",
            "plan_sha256": "a" * 64,
            "reviewed_state_sha256": "b" * 64,
            "project_key_sha256": {"project-a": "c" * 64},
            "wif_config_sha256": "d" * 64,
            "invalid_internal": {
                "wif_config_sha256": "sk_live_INVALID-INTERNAL-CANARY"
            },
            "client_secret_sha256": "sk_live_CLIENT-SHA-CANARY",
            "private_key_sha256": "sk_live_PRIVATE-SHA-CANARY",
            "credential_sha256": "sk_live-CREDENTIAL-SHA-CANARY",
            "unknown_sha256": "sk_live-UNKNOWN-SHA-CANARY",
            "unsafe_key_container": {
                unsafe_assignment_key: "ordinary value",
                unsafe_jwt_key: "GCP-JWT-DICT-VALUE-CANARY",
                nested_unicode_key: "ordinary value",
            },
            "invalid_digest_maps": {
                "project_key_sha256": {
                    "/tmp/client_secret=GCP-DIGEST-PATH-CANARY": "e" * 64
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
                    "/tmp/client_secr\\u005cu0065t=GCP-NESTED-DIGEST-KEY-CANARY": "a"
                    * 64
                },
            },
        }
        redacted = self.api.redact(value)
        serialized = json.dumps(redacted)
        assert not any(
            canary in serialized
            for canary in (
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
                "GCP-DICT-KEY-CANARY",
                "GCP-JWT-DICT-VALUE-CANARY",
                "GCP-DIGEST-PATH-CANARY",
                unsafe_jwt_key,
                "GCP-NESTED-DICT-KEY-CANARY",
                "GCP-NESTED-DIGEST-KEY-CANARY",
            )
        )
        assert redacted["idempotency_key"] == "operation-identifier"
        assert redacted["plan_sha256"] == "a" * 64
        assert redacted["reviewed_state_sha256"] == "b" * 64
        assert redacted["project_key_sha256"] == {"project-a": "c" * 64}
        assert redacted["wif_config_sha256"] == "d" * 64
        assert redacted["invalid_internal"]["wif_config_sha256"] == "[REDACTED]"
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

    def test_strict_credential_hash_state_preserves_secret_looking_paths(
        self, tmp_path
    ):
        state = tmp_path / "state"
        service_account_path = "/secure/project-key-secret.json"
        wif_path = "/tmp/client-secret-material.json"
        expected = {
            "project_key_sha256": {service_account_path: "a" * 64},
            "wif_config_sha256": {wif_path: "b" * 64},
        }
        self.api._save_cred_hashes(state, expected)
        stored = json.loads((state / "credential-hashes.json").read_text())
        assert stored == expected
        assert self.api._load_cred_hashes(state) == expected
        with pytest.raises(self.api.ApiError, match="schema mismatch"):
            self.api._save_cred_hashes(
                state,
                {**expected, "unknown": {}},
            )
        with pytest.raises(self.api.ApiError, match="lowercase SHA-256"):
            self.api._save_cred_hashes(
                state,
                {
                    "project_key_sha256": {service_account_path: "not-a-hash"},
                    "wif_config_sha256": {},
                },
            )
        with pytest.raises(self.api.ApiError, match="map paths"):
            self.api._save_cred_hashes(
                state,
                {
                    "project_key_sha256": {
                        "/tmp/client_secret=GCP-STATE-PATH-CANARY": "a" * 64
                    },
                    "wif_config_sha256": {},
                },
            )

    @pytest.mark.parametrize(
        "document,error",
        (
            (
                {
                    "project_key_sha256": {},
                    "wif_config_sha256": {},
                    "unknown": {},
                },
                "schema mismatch",
            ),
            (
                {
                    "project_key_sha256": {"/secure/key.json": "bad"},
                    "wif_config_sha256": {},
                },
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
            "pass\u200bword=GCP-ZWSP-CANARY",
            "pa\u034fssword=GCP-CGJ-CANARY",
            "pass\u00adword=GCP-SOFT-HYPHEN-CANARY",
            "to\u200bken=GCP-TOKEN-SPLIT-CANARY",
            "ｃｌｉｅｎｔ＿ｓｅｃｒｅｔ=GCP-NFKC-CANARY",
            "paſſword=GCP-LONG-S-CANARY",
            "refresh_to\u200bken: GCP-YAML-ZWSP-CANARY",
            "client.secret: GCP-DOT-KEY-CANARY",
            "api/token: GCP-SLASH-KEY-CANARY",
            "private key: GCP-PRIVATE-SPACE-CANARY",
            "api key: GCP-API-SPACE-CANARY",
            "access key: GCP-ACCESS-SPACE-CANARY",
            "project key: GCP-PROJECT-SPACE-CANARY",
            "client key: GCP-CLIENT-SPACE-CANARY",
            "secret key: GCP-SECRET-SPACE-CANARY",
            "client_secret(foo)=GCP-PAREN-CANARY",
            "[password]=GCP-BRACKET-CANARY",
            "client_secret" + "x" * 300 + "=GCP-LONG-KEY-CANARY",
            "plan_sha256=GCP-PLAN-DIGEST-CANARY",
            "app_id_sha256: GCP-APP-DIGEST-CANARY",
            "secret_key_sha256=GCP-SECRET-DIGEST-CANARY",
            "project_key_sha256: GCP-PROJECT-DIGEST-CANARY",
            "wif_config_sha256=GCP-WIF-DIGEST-CANARY",
            "reviewed_state_sha256=GCP-REVIEWED-DIGEST-CANARY",
            "Basic dTpw",
            "Bearer abc",
            "e30.e30.QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo",
            r'{"refresh_t\\u005cu006fken":"GCP-NESTED-JSON-KEY-CANARY"}',
            r'"refresh_t\u005cu006fken": GCP-NESTED-YAML-KEY-CANARY',
            r'"refresh_t\x6fken": GCP-X-KEY-CANARY',
            r'"refresh_t\U0000006fken": GCP-U-KEY-CANARY',
            r'{"pass\ud800word":"GCP-SURROGATE-JSON-CANARY"}',
            r'{"refresh_t\u000Aoken":"GCP-ESCAPED-NEWLINE-JSON-CANARY",}',
            r'"refresh_t\u000Aoken": GCP-ESCAPED-NEWLINE-YAML-CANARY',
            r'{"refresh_t\u003Aoken":"GCP-ESCAPED-COLON-JSON-CANARY",}',
            r'"refresh_t\u003Aoken": GCP-ESCAPED-COLON-YAML-CANARY',
            r'{"refresh_t\u003Doken":"GCP-ESCAPED-EQUAL-JSON-CANARY",}',
            r'"refresh_t\u003Doken": GCP-ESCAPED-EQUAL-YAML-CANARY',
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
            "GCP-KEY-CANARY" not in json.dumps(self.api.redact({key: "GCP-KEY-CANARY"}))
            for key in unsafe_keys
        )

        unsafe_mapping_keys = (
            "/tmp/ｃｌｉｅｎｔ＿ｓｅｃｒｅｔ=GCP-MAP-NFKC-CANARY",
            "/tmp/pass\u200bword=GCP-MAP-ZWSP-CANARY",
            "/tmp/pa\u034fssword=GCP-MAP-CGJ-CANARY",
            "/tmp/pass\u00adword=GCP-MAP-SOFT-HYPHEN-CANARY",
            "/tmp/to\u200bken=GCP-MAP-TOKEN-CANARY",
            "/tmp/client_secret(foo)=GCP-MAP-PAREN-CANARY",
            "/tmp/[password]=GCP-MAP-BRACKET-CANARY",
            "/tmp/client_secret" + "x" * 300 + "=GCP-MAP-LONG-CANARY",
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
            self.api._project_live_reviewed_state(_gcp_live(namedToken=value))
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
            ("ordinary tuple value", "password=GCP-TUPLE-CANARY")
        ) == ["ordinary tuple value", "[REDACTED]"]

    def test_output_dlp_and_journal_scrub_malicious_corpus(
        self, tmp_path, capsys
    ):
        corpus = {
            "details": [
                r'{"refresh_t\u000Aoken":"GCP-NEWLINE-CANARY",}',
                r'"refresh_t\u003Aoken": GCP-COLON-CANARY',
                r'"refresh_t\u003Doken": GCP-EQUAL-CANARY',
                r'"refresh_t\noken": GCP-SHORT-N-CANARY',
                r'"refresh_t\roken": GCP-SHORT-R-CANARY',
                r'"refresh_t\boken": GCP-SHORT-B-CANARY',
                r'"refresh_t\foken": GCP-SHORT-F-CANARY',
                "authorization: Bearer abc",
                "Basic dTpw",
                "e30.e30.QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo",
                (
                    "-----BEGIN RSA PRIVATE KEY-----\n"
                    "GCP-PEM-CANARY\n"
                    "-----END RSA PRIVATE KEY-----"
                ),
            ],
            "client_secret=GCP-UNSAFE-DICT-KEY-CANARY": "ordinary",
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
            "gcp-output-dlp",
            "failed",
            corpus,
        )
        print(json.dumps(redacted))
        print(json.dumps(redacted), file=sys.stderr)
        captured = capsys.readouterr()
        journal = (state_dir / "apply-state.json").read_text()
        combined = journal + captured.out + captured.err
        for canary in (
            "GCP-NEWLINE-CANARY",
            "GCP-COLON-CANARY",
            "GCP-EQUAL-CANARY",
            "GCP-SHORT-N-CANARY",
            "GCP-SHORT-R-CANARY",
            "GCP-SHORT-B-CANARY",
            "GCP-SHORT-F-CANARY",
            "GCP-UNSAFE-DICT-KEY-CANARY",
            "GCP-PEM-CANARY",
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
                (r"\n", f"GCP-LONG-N-{size}-CANARY"),
                (r"\r", f"GCP-LONG-R-{size}-CANARY"),
                ("\n", f"GCP-LONG-LF-{size}-CANARY"),
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
            "gcp-bounded-output-dlp",
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
        for marker in ("GCP-LONG-N", "GCP-LONG-R", "GCP-LONG-LF"):
            assert marker not in combined
        assert redacted["safe"] == safe
        assert json.loads(journal)["steps"][-1]["response"]["safe"] == safe

    @pytest.mark.parametrize(
        "unsafe",
        (
            '"' + "a" * 4083 + r"refresh_t\noken" + '": GCP-ARTIFACT-LONG',
            "request failed with Basic dTpw during GCP-ARTIFACT-BASIC",
            "request failed with Bearer " + "A" * 24 + " GCP-ARTIFACT-BEARER",
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
                integrations=[_gcp_live(namedToken=unsafe)],
            )
        captured = capsys.readouterr()
        assert not snapshot_path.exists()
        assert not plan_path.exists()
        assert "ARTIFACT" not in captured.out + captured.err

    def test_known_schema_discover_plan_and_journal_are_exact_and_secret_free(
        self, tmp_path, monkeypatch, capsys
    ):
        live = _gcp_live(
            name="token=production",
            projectServiceKeys=[
                {"projectId": "project-a"},
                {"projectId": "project-b"},
            ],
            includeList=["compute.googleapis.com"],
            whitelist=["legacy.googleapis.com"],
            useMetricSourceProjectForQuota=True,
            importGCPMetrics=True,
            customMetricTypeDomains=["custom.googleapis.com"],
            excludeGCEInstancesWithLabels=["environment"],
            namedToken=r"token rotation completed\nstatus: healthy",
            created=1712345678,
            lastUpdated=1712345688,
            creator="creator-id",
            lastUpdatedBy="updater-id",
            lastUpdatedByName="Updater",
            createdByName="Creator",
            wifSplunkIdentity={"subject": "identity", "audience": "splunk"},
            workloadIdentityPoolId="captured-pool",
            workloadIdentityProviderId="captured-provider",
        )
        expected = self.api._project_live_reviewed_state(live)
        assert expected["projectServiceKeys"] == live["projectServiceKeys"]
        assert expected["name"] == "token=production"
        assert expected["includeList"] == ["compute.googleapis.com"]
        assert expected["whitelist"] == ["legacy.googleapis.com"]
        assert expected["wifSplunkIdentity"] == live["wifSplunkIdentity"]

        monkeypatch.setattr(
            self.api, "list_gcp_integrations", Mock(return_value=[live])
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
            integration_id="gcp-id-1",
            integration_name="token=production",
            expected_enabled_state=True,
            observed_state_file=str(snapshot_path),
        )
        self.api.append_step(
            state_dir,
            "test",
            "known-schema",
            "gcp-known-schema",
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
        assert "GCP-PROJECT-A-OBSERVED-CANARY" not in combined
        assert "GCP-PROJECT-B-OBSERVED-CANARY" not in combined
        assert "token=production" in combined

    @pytest.mark.parametrize(
        "case",
        ("unknown-root", "unknown-project", "suspicious", "response-credential"),
    )
    def test_discover_rejects_unknown_or_suspicious_state_without_artifacts(
        self, case, tmp_path, monkeypatch
    ):
        if case == "unknown-root":
            live = _gcp_live(details={"status": "healthy"})
        elif case == "unknown-project":
            live = _gcp_live(
                projects={"syncMode": "ALL_REACHABLE", "unknown": True}
            )
        elif case == "suspicious":
            live = _gcp_live(namedToken="Bearer abc")
        else:
            live = _gcp_live(
                projectServiceKeys=[
                    {
                        "projectId": "project-a",
                        "projectKey": "GCP-RESPONSE-CREDENTIAL-CANARY",
                    }
                ]
            )
        monkeypatch.setattr(
            self.api, "list_gcp_integrations", Mock(return_value=[live])
        )
        state_dir = tmp_path / "state"
        snapshot_path = state_dir / "observed.json"
        with pytest.raises(self.api.ApiError):
            self.api.discover("us1", "unused", snapshot_path, state_dir)
        assert not snapshot_path.exists()
        assert not (state_dir / "apply-state.json").exists()

    def test_live_nested_schema_error_is_label_only(self, tmp_path, capsys):
        canary = "client_secret=GCP-NESTED-SCHEMA-CANARY"
        snapshot_path = tmp_path / "observed.json"
        with pytest.raises(self.api.ApiError) as error:
            self.api.write_observed_snapshot(
                snapshot_path,
                realm="us1",
                integrations=[
                    _gcp_live(
                        projects={
                            "syncMode": "ALL_REACHABLE",
                            canary: "untrusted",
                        }
                    )
                ],
            )
        print(str(error.value))
        print(str(error.value), file=sys.stderr)
        captured = capsys.readouterr()
        assert canary not in str(error.value) + captured.out + captured.err
        assert not snapshot_path.exists()

    def test_reviewed_projection_never_calls_output_redactor(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            self.api,
            "redact",
            lambda *_args, **_kwargs: pytest.fail("output redactor was called"),
        )
        first = self.api._project_live_reviewed_state(
            _gcp_live(namedToken="ordinary state A")
        )
        second = self.api._project_live_reviewed_state(
            _gcp_live(namedToken="ordinary state B")
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
            {"projectServiceKeys": ["not-an-object"]},
            {"projectServiceKeys": [{}]},
            {"projectServiceKeys": [{"projectId": ""}]},
            {"projectServiceKeys": [{"projectId": 7}]},
            {
                "projectServiceKeys": [
                    {"projectId": "duplicate"},
                    {"projectId": "duplicate"},
                ]
            },
            {"projectServiceKeys": [{"projectId": "project-a", "projectKey": 7}]},
            {"workloadIdentityPoolId": None},
            {"workloadIdentityProviderId": []},
            {"workloadIdentityPoolId": "x" * 4097},
        ),
    )
    def test_reviewed_response_common_project_and_compatibility_shapes_are_exact(
        self, override
    ):
        with pytest.raises(self.api.ApiError, match="response schema mismatch"):
            self.api._project_live_reviewed_state(_gcp_live(**override))
        valid = self.api._project_live_reviewed_state(
            _gcp_live(createdByName=None, lastUpdatedByName=None)
        )
        assert valid["createdByName"] is None
        assert valid["lastUpdatedByName"] is None

    @pytest.mark.parametrize(
        "override",
        (
            {"authMethod": "FUTURE_AUTH"},
            {"pollRate": 59_999},
            {"pollRate": 600_001},
        ),
    )
    def test_disable_rejects_unsupported_auth_or_poll_but_delete_reviews_it(
        self, override, tmp_path
    ):
        snapshot_path = tmp_path / "observed.json"
        self.api.write_observed_snapshot(
            snapshot_path,
            realm="us1",
            integrations=[_gcp_live(**override)],
        )
        key_a = _write_sa_key(tmp_path / "a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "b.json", "project-b")
        disable_path = tmp_path / "disable.json"
        with pytest.raises(self.api.ApiError, match="GCP disable requires"):
            self.api.render_rollback_plan(
                disable_path,
                realm="us1",
                action="disable",
                integration_id="gcp-id-1",
                integration_name="test-gcp",
                expected_enabled_state=True,
                observed_state_file=str(snapshot_path),
                key_files=[str(key_b), str(key_a)],
            )
        assert not disable_path.exists()
        rendered = self.api.render_rollback_plan(
            tmp_path / "delete.json",
            realm="us1",
            action="delete",
            integration_id="gcp-id-1",
            integration_name="test-gcp",
            expected_enabled_state=True,
            observed_state_file=str(snapshot_path),
        )
        assert rendered["plan"]["action"] == "delete"

    def test_singular_wif_is_projected_as_digest_and_never_persisted(
        self, tmp_path, capsys
    ):
        first_raw = json.dumps(
            {"type": "external_account", "audience": "GCP-WIF-A-CANARY"}
        )
        second_raw = json.dumps(
            {"type": "external_account", "audience": "GCP-WIF-B-CANARY"}
        )
        first = _gcp_live(
            authMethod="WORKLOAD_IDENTITY_FEDERATION",
            workloadIdentityFederationConfig=first_raw,
        )
        first.pop("projectServiceKeys")
        second = {
            **first,
            "workloadIdentityFederationConfig": second_raw,
        }
        first_projected = self.api._project_live_reviewed_state(first)
        second_projected = self.api._project_live_reviewed_state(second)
        observation = first_projected["workloadIdentityFederationConfig"]
        assert set(observation) == {"sha256"}
        assert first_projected != second_projected
        assert self.api._reviewed_state_sha256(first_projected) != (
            self.api._reviewed_state_sha256(second_projected)
        )

        state_dir = tmp_path / "state"
        snapshot_path = state_dir / "observed.json"
        snapshot = self.api.write_observed_snapshot(
            snapshot_path, realm="us1", integrations=[first]
        )
        plan_path = state_dir / "delete-plan.json"
        rendered = self.api.render_rollback_plan(
            plan_path,
            realm="us1",
            action="delete",
            integration_id="gcp-id-1",
            integration_name="test-gcp",
            expected_enabled_state=True,
            observed_state_file=str(snapshot_path),
        )
        self.api.append_step(
            state_dir,
            "test",
            "wif-digest",
            "gcp-wif-digest",
            "success",
            first_projected,
        )
        print(json.dumps(rendered))
        print(json.dumps(first_projected), file=sys.stderr)
        captured = capsys.readouterr()
        combined = "\n".join(
            (
                json.dumps(snapshot),
                snapshot_path.read_text(),
                plan_path.read_text(),
                (state_dir / "apply-state.json").read_text(),
                captured.out,
                captured.err,
            )
        )
        assert "GCP-WIF-A-CANARY" not in combined
        assert first_raw not in combined

    def test_wif_identity_accepts_string_or_bounded_string_map(self):
        string_state = self.api._project_live_reviewed_state(
            _gcp_live(wifSplunkIdentity="identity")
        )
        map_state = self.api._project_live_reviewed_state(
            _gcp_live(wifSplunkIdentity={"subject": "identity"})
        )
        assert string_state["wifSplunkIdentity"] == "identity"
        assert map_state["wifSplunkIdentity"] == {"subject": "identity"}
        with pytest.raises(self.api.ApiError, match="schema mismatch"):
            self.api._project_live_reviewed_state(
                _gcp_live(wifSplunkIdentity={"subject": 7})
            )

    def test_wif_live_and_artifact_trust_modes_reject_spoofed_digest_forms(
        self, tmp_path
    ):
        singular_spoof = _gcp_live(
            authMethod="WORKLOAD_IDENTITY_FEDERATION",
            workloadIdentityFederationConfig={"sha256": "a" * 64},
        )
        singular_spoof.pop("projectServiceKeys")
        plural_spoof = _gcp_live(
            authMethod="WORKLOAD_IDENTITY_FEDERATION",
            workloadIdentityFederationConfigs=[
                {"projectId": "project-a", "wifConfigSha256": "b" * 64}
            ],
        )
        plural_spoof.pop("projectServiceKeys")
        for index, spoof in enumerate((singular_spoof, plural_spoof)):
            path = tmp_path / f"spoof-{index}.json"
            with pytest.raises(self.api.ApiError):
                self.api.write_observed_snapshot(
                    path, realm="us1", integrations=[spoof]
                )
            assert not path.exists()

        raw = _gcp_live(
            authMethod="WORKLOAD_IDENTITY_FEDERATION",
            workloadIdentityFederationConfig=(
                '{"type":"external_account","audience":"raw-secret"}'
            ),
        )
        raw.pop("projectServiceKeys")
        with pytest.raises(self.api.ApiError, match="raw WIF"):
            self.api._validate_projected_reviewed_state(raw)

        projected_sa = self.api._project_live_reviewed_state(_gcp_live())
        projected_sa["projectServiceKeys"][0]["projectKey"] = "spoof"
        with pytest.raises(self.api.ApiError, match="projectKey"):
            self.api._validate_projected_reviewed_state(projected_sa)

    def test_wif_local_mismatch_and_plural_or_legacy_disable_fail_before_plan(
        self, tmp_path
    ):
        local = _write_private_text(
            tmp_path / "gcp_wif_config.json",
            '{"type":"external_account","audience":"local"}',
        )
        singular = _gcp_live(
            authMethod="WORKLOAD_IDENTITY_FEDERATION",
            workloadIdentityFederationConfig=(
                '{"type":"external_account","audience":"remote"}'
            ),
        )
        singular.pop("projectServiceKeys")
        singular_snapshot = tmp_path / "singular.json"
        self.api.write_observed_snapshot(
            singular_snapshot, realm="us1", integrations=[singular]
        )
        singular_plan = tmp_path / "singular-plan.json"
        with pytest.raises(self.api.ApiError, match="does not match the local WIF"):
            self.api.render_rollback_plan(
                singular_plan,
                realm="us1",
                action="disable",
                integration_id="gcp-id-1",
                integration_name="test-gcp",
                expected_enabled_state=True,
                observed_state_file=str(singular_snapshot),
                wif_config_file=str(local),
            )
        assert not singular_plan.exists()

        plural = _gcp_live(
            authMethod="WORKLOAD_IDENTITY_FEDERATION",
            workloadIdentityFederationConfigs=[
                {
                    "projectId": "project-a",
                    "wifConfig": (
                        '{"type":"external_account","audience":"plural-a"}'
                    ),
                },
                {
                    "projectId": "project-b",
                    "wifConfig": (
                        '{"type":"external_account","audience":"plural-b"}'
                    ),
                },
            ],
        )
        plural.pop("projectServiceKeys")
        plural_snapshot = tmp_path / "plural.json"
        snapshot = self.api.write_observed_snapshot(
            plural_snapshot, realm="us1", integrations=[plural]
        )
        observations = snapshot["results"][0]["workloadIdentityFederationConfigs"]
        assert all(
            set(observation) == {"projectId", "wifConfigSha256"}
            for observation in observations
        )
        assert "plural-a" not in json.dumps(snapshot)
        assert "plural-b" not in json.dumps(snapshot)
        delete_rendered = self.api.render_rollback_plan(
            tmp_path / "plural-delete.json",
            realm="us1",
            action="delete",
            integration_id="gcp-id-1",
            integration_name="test-gcp",
            expected_enabled_state=True,
            observed_state_file=str(plural_snapshot),
        )
        assert delete_rendered["plan"]["action"] == "delete"
        with pytest.raises(self.api.ApiError, match="plural configuration"):
            self.api.render_rollback_plan(
                tmp_path / "plural-disable.json",
                realm="us1",
                action="disable",
                integration_id="gcp-id-1",
                integration_name="test-gcp",
                expected_enabled_state=True,
                observed_state_file=str(plural_snapshot),
                wif_config_file=str(local),
            )

        legacy = _gcp_live(projects={"syncMode": "ALL", "projectIds": []})
        legacy_snapshot = tmp_path / "legacy.json"
        self.api.write_observed_snapshot(
            legacy_snapshot, realm="us1", integrations=[legacy]
        )
        legacy_delete = self.api.render_rollback_plan(
            tmp_path / "legacy-delete.json",
            realm="us1",
            action="delete",
            integration_id="gcp-id-1",
            integration_name="test-gcp",
            expected_enabled_state=True,
            observed_state_file=str(legacy_snapshot),
        )
        assert legacy_delete["plan"]["reviewed_state"]["projects"] == {
            "syncMode": "ALL",
            "projectIds": [],
        }
        key_a = _write_sa_key(tmp_path / "legacy-a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "legacy-b.json", "project-b")
        with pytest.raises(self.api.ApiError, match="legacy projects"):
            self.api.render_rollback_plan(
                tmp_path / "legacy-disable.json",
                realm="us1",
                action="disable",
                integration_id="gcp-id-1",
                integration_name="test-gcp",
                expected_enabled_state=True,
                observed_state_file=str(legacy_snapshot),
                key_files=[str(key_b), str(key_a)],
            )

    @pytest.mark.parametrize("auth_method", ("service-account", "wif"))
    def test_reinjected_gcp_credentials_reach_the_single_put_body(
        self, auth_method, monkeypatch
    ):
        response = Mock(status=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"id":"gcp-id-1"}'
        opener = Mock()
        opener.open.return_value = response
        monkeypatch.setattr(self.api, "build_opener", lambda *_: opener)
        if auth_method == "service-account":
            payload = _gcp_live(enabled=False)
            payload["projectServiceKeys"][0]["projectKey"] = "GCP-PROJECT-BODY-CANARY"
        else:
            wif_value = (
                '{"type":"external_account",'
                '"audience":"GCP-WIF-BODY-CANARY"}'
            )
            payload = _gcp_live(
                enabled=False,
                authMethod="WORKLOAD_IDENTITY_FEDERATION",
                workloadIdentityFederationConfig=wif_value,
            )
            payload.pop("projectServiceKeys", None)
        self.api.update_integration(
            "us1",
            "unused",
            "gcp-id-1",
            payload,
            _capability=self.api._ROLLBACK_CAPABILITY,
        )
        sent = json.loads(opener.open.call_args.args[0].data.decode("utf-8"))
        if auth_method == "service-account":
            assert sent["projectServiceKeys"][0]["projectKey"] == "GCP-PROJECT-BODY-CANARY"
        else:
            assert sent["workloadIdentityFederationConfig"] == wif_value
        assert "CANARY" not in json.dumps(self.api.redact(payload))

    def test_named_token_and_ordinary_config_remain_in_semantic_fingerprints(self):
        assert self.api._configuration_fingerprint(
            _gcp_live(namedToken="token-name-a"),
            source=self.api._ReviewedStateSource.LIVE_RESPONSE,
        ) != self.api._configuration_fingerprint(
            _gcp_live(namedToken="token-name-b"),
            source=self.api._ReviewedStateSource.LIVE_RESPONSE,
        )
        assert self.api._configuration_fingerprint(
            _gcp_live(customMetricTypeDomains=["custom-a.googleapis.com"]),
            source=self.api._ReviewedStateSource.LIVE_RESPONSE,
        ) != self.api._configuration_fingerprint(
            _gcp_live(customMetricTypeDomains=["custom-b.googleapis.com"]),
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
        value = "gcp-id-1" if lock_kind == "target" else "same-exact-name"
        child = """
import importlib.util
import pathlib
import sys
import time
spec = importlib.util.spec_from_file_location('gcp_lock_child', sys.argv[1])
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
                str(SCRIPTS_DIR / "gcp_integration_api.py"),
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
                    str(SCRIPTS_DIR / "gcp_integration_api.py"),
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

    def test_unserializable_mutation_payload_is_deterministic_before_dispatch(
        self, monkeypatch
    ):
        opener_factory = Mock()
        monkeypatch.setattr(self.api, "build_opener", opener_factory)
        with pytest.raises(self.api.ApiError, match="strict UTF-8 JSON") as exc_info:
            self.api._request(
                "PUT",
                "https://api.us1.observability.splunkcloud.com/v2/integration/gcp-id-1",
                "unused",
                {"enabled": True, "bad": object(), "projectKey": "CANARY"},
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
                {"bad": object(), "privateKey": "CLI-CANARY"},
            )

        monkeypatch.setattr(self.api, "upsert", fail_before_dispatch)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "gcp_integration_api.py",
                "--realm", "us1",
                "--token-file", str(tmp_path / "token"),
                "--state-dir", str(tmp_path / "state"),
                "--payload-file", str(tmp_path / "payload.json"),
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

    def test_missing_plan_or_ack_precedes_token_and_transport(self, tmp_path, monkeypatch):
        token_read = Mock(side_effect=AssertionError("token read"))
        transport = Mock(side_effect=AssertionError("transport"))
        monkeypatch.setattr(self.api, "read_secret_file", token_read)
        monkeypatch.setattr(self.api, "_request", transport)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "gcp_integration_api.py",
                "--realm",
                "us1",
                "--token-file",
                str(tmp_path / "token"),
                "--state-dir",
                str(tmp_path / "state"),
                "--plan-file",
                str(tmp_path / "missing.json"),
                "--integration-id",
                "gcp-id-1",
                "--integration-name",
                "test-gcp",
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
                "gcp_integration_api.py",
                "--realm", "us1",
                "--state-dir", str(tmp_path / "state"),
                "--token-file", str(tmp_path / "token"),
                "--plan-file", str(tmp_path / "plan.json"),
                "--plan-hash", "0" * 64,
                "--integration-id", "gcp-id-1",
                "--accept-disable-integration", "gcp-id-1",
                "--dry-run",
                "--apply",
                "rollback", "disable",
            ],
        )
        assert self.api.main() == 1
        assert "--dry-run is not accepted with rollback" in capsys.readouterr().out
        assert plan_load.call_count == token_read.call_count == transport.call_count == 0

    def test_missing_ack_gate_precedes_token_and_transport(self, tmp_path, monkeypatch):
        plan_path, plan_hash = _gcp_plan(self.api, tmp_path)
        token_read = Mock(side_effect=AssertionError("token read"))
        transport = Mock(side_effect=AssertionError("transport"))
        monkeypatch.setattr(self.api, "read_secret_file", token_read)
        monkeypatch.setattr(self.api, "_request", transport)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "gcp_integration_api.py",
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
                "gcp-id-1",
                "--apply",
                "rollback",
                "disable",
            ],
        )
        assert self.api.main() == 1
        assert token_read.call_count == 0
        assert transport.call_count == 0

    def test_plan_tamper_wrong_action_id_mode_and_symlink(self, tmp_path, monkeypatch):
        plan_path, plan_hash = _gcp_plan(self.api, tmp_path)
        document = json.loads(plan_path.read_text())
        document["integration_name"] = "tampered"
        plan_path.write_text(json.dumps(document), encoding="utf-8")
        plan_path.chmod(0o600)
        with pytest.raises(self.api.ApiError, match="mismatch"):
            self.api.load_rollback_plan(plan_path, plan_hash)

        plan_path, plan_hash = _gcp_plan(self.api, tmp_path)
        live_get = Mock()
        monkeypatch.setattr(self.api, "get_integration", live_get)
        for action, integration_id in (("delete", "gcp-id-1"), ("disable", "other-id")):
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

        plan_path.chmod(0o644)
        with pytest.raises(self.api.ApiError, match="mode-0600"):
            self.api.load_rollback_plan(plan_path, plan_hash)
        plan_path.chmod(0o600)
        link = tmp_path / "plan-link.json"
        link.symlink_to(plan_path)
        with pytest.raises(self.api.ApiError, match="mode-0600"):
            self.api.load_rollback_plan(link, plan_hash)

        document = json.loads(plan_path.read_text())
        document["unknown"] = True
        plan_path.write_text(json.dumps(document), encoding="utf-8")
        plan_path.chmod(0o600)
        with pytest.raises(self.api.ApiError, match="unknown"):
            self.api.load_rollback_plan(
                plan_path,
                self.api.rollback_plan_sha256(
                    {key: value for key, value in document.items() if key != "unknown"}
                ),
            )

    @pytest.mark.parametrize(
        "mutation,error",
        (
            (
                lambda text: text.replace(
                    '"action": "disable",',
                    '"action": "disable",\n  "action": "delete",',
                    1,
                ),
                "duplicate JSON object key",
            ),
            (lambda text: text.replace("{", '{\n  "poison": NaN,', 1), "non-standard JSON"),
            (lambda text: text.replace("{", '{\n  "poison": Infinity,', 1), "non-standard JSON"),
        ),
    )
    def test_plan_strict_json_rejects_duplicate_keys_and_nonfinite_constants(
        self, mutation, error, tmp_path
    ):
        plan_path, _plan_hash = _gcp_plan(self.api, tmp_path)
        plan_path.write_text(mutation(plan_path.read_text()), encoding="utf-8")
        plan_path.chmod(0o600)
        with pytest.raises(self.api.ApiError, match=error):
            self.api.load_rollback_plan(plan_path, "0" * 64)

    def test_plan_exact_name_parent_mode_and_fresh_plan_identity(self, tmp_path):
        parent = tmp_path / "review-parent"
        parent.mkdir(mode=0o755)
        before_mode = parent.stat().st_mode & 0o777
        first, first_hash = _gcp_plan(
            self.api, parent, integration_name="token=production"
        )
        first_document = json.loads(first.read_text())
        assert first_document["integration_name"] == "token=production"
        assert self.api.rollback_plan_sha256(first_document) == first_hash
        assert parent.stat().st_mode & 0o777 == before_mode == 0o755
        second_path = parent / "fresh-plan.json"
        second = self.api.render_rollback_plan(
            second_path,
            realm="us1",
            action="disable",
            integration_id="gcp-id-1",
            integration_name="token=production",
            expected_enabled_state=True,
            observed_state_file=str(parent / "gcp-disable-observed.json"),
            key_files=[
                str(parent / "project-b.json"),
                str(parent / "project-a.json"),
            ],
        )
        assert second["plan"]["plan_id"] != first_document["plan_id"]
        assert second["plan_hash"] != first_hash

    def test_snapshot_and_plan_writers_enforce_exact_loader_size_bounds(
        self, tmp_path, monkeypatch
    ):
        observed = tmp_path / "observed.json"
        self.api.write_observed_snapshot(
            observed, realm="us1", integrations=[_gcp_live()]
        )
        observed_size = len(observed.read_bytes())
        monkeypatch.setattr(self.api, "MAX_OBSERVED_BYTES", observed_size)
        boundary_observed = tmp_path / "boundary-observed.json"
        self.api.write_observed_snapshot(
            boundary_observed, realm="us1", integrations=[_gcp_live()]
        )
        assert len(boundary_observed.read_bytes()) == observed_size

        preserved_observed = _write_private_text(
            tmp_path / "preserved-observed.json", "preserve-observed"
        )
        monkeypatch.setattr(self.api, "MAX_OBSERVED_BYTES", observed_size - 1)
        with pytest.raises(self.api.ApiError, match="observed snapshot exceeds"):
            self.api.write_observed_snapshot(
                preserved_observed, realm="us1", integrations=[_gcp_live()]
            )
        assert preserved_observed.read_text() == "preserve-observed"
        monkeypatch.setattr(self.api, "MAX_OBSERVED_BYTES", observed_size)

        key_a = _write_sa_key(tmp_path / "a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "b.json", "project-b")
        plan_path = tmp_path / "plan.json"
        self.api.render_rollback_plan(
            plan_path,
            realm="us1",
            action="disable",
            integration_id="gcp-id-1",
            integration_name="test-gcp",
            expected_enabled_state=True,
            observed_state_file=str(observed),
            key_files=[str(key_b), str(key_a)],
        )
        plan_size = len(plan_path.read_bytes())
        monkeypatch.setattr(self.api, "MAX_PLAN_BYTES", plan_size)
        boundary_plan = tmp_path / "boundary-plan.json"
        self.api.render_rollback_plan(
            boundary_plan,
            realm="us1",
            action="disable",
            integration_id="gcp-id-1",
            integration_name="test-gcp",
            expected_enabled_state=True,
            observed_state_file=str(observed),
            key_files=[str(key_b), str(key_a)],
        )
        assert len(boundary_plan.read_bytes()) == plan_size

        preserved_plan = _write_private_text(tmp_path / "preserved-plan.json", "preserve-plan")
        monkeypatch.setattr(self.api, "MAX_PLAN_BYTES", plan_size - 1)
        with pytest.raises(self.api.ApiError, match="rollback plan exceeds"):
            self.api.render_rollback_plan(
                preserved_plan,
                realm="us1",
                action="disable",
                integration_id="gcp-id-1",
                integration_name="test-gcp",
                expected_enabled_state=True,
                observed_state_file=str(observed),
                key_files=[str(key_b), str(key_a)],
            )
        assert preserved_plan.read_text() == "preserve-plan"

    def test_observed_snapshot_binds_revision_state_and_strips_credentials(
        self, tmp_path
    ):
        observed = tmp_path / "observed.json"
        live = _gcp_live(
            lastUpdated=1712345678,
            creator="reviewer-id",
            wifSplunkIdentity={"subject": "visible-identity"},
        )
        snapshot = self.api.write_observed_snapshot(
            observed, realm="us1", integrations=[live]
        )
        serialized = json.dumps(snapshot)
        assert observed.stat().st_mode & 0o777 == 0o600
        assert snapshot["results"][0]["lastUpdated"] == 1712345678
        assert snapshot["results"][0]["wifSplunkIdentity"] == {
            "subject": "visible-identity"
        }
        assert "projectKey" not in serialized

        key_a = _write_sa_key(tmp_path / "a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "b.json", "project-b")
        rendered = self.api.render_rollback_plan(
            tmp_path / "plan.json",
            realm="us1",
            action="disable",
            integration_id="gcp-id-1",
            integration_name="test-gcp",
            expected_enabled_state=True,
            observed_state_file=str(observed),
            key_files=[str(key_b), str(key_a)],
        )
        reviewed = rendered["plan"]["reviewed_state"]
        assert reviewed["lastUpdated"] == 1712345678
        assert rendered["plan"]["reviewed_state_sha256"] == (
            self.api._reviewed_state_sha256(reviewed)
        )

    def test_observed_snapshot_rejects_duplicate_identity_and_strict_json(
        self, tmp_path
    ):
        for integrations, error in (
            ([_gcp_live(id="one"), _gcp_live(id="one", name="other")], "repeats integration ID"),
            ([_gcp_live(id="one"), _gcp_live(id="two")], "repeats integration name"),
        ):
            with pytest.raises(self.api.ApiError, match=error):
                self.api.write_observed_snapshot(
                    tmp_path / f"{len(error)}.json",
                    realm="us1",
                    integrations=integrations,
                )

        duplicate = _write_private_text(
            tmp_path / "duplicate-observed.json",
            '{"schema_version":1,"schema_version":1,"provider":"GCP",'
            '"realm":"us1","captured_at":"2026-01-01T00:00:00+00:00",'
            '"count":0,"results":[]}',
        )
        with pytest.raises(self.api.ApiError, match="duplicate JSON object key"):
            self.api.load_observed_snapshot(duplicate, expected_realm="us1")

        nonfinite = _write_private_text(
            tmp_path / "nonfinite-observed.json",
            '{"schema_version":1,"provider":"GCP","realm":"us1",'
            '"captured_at":"2026-01-01T00:00:00+00:00","count":0,'
            '"results":[],"poison":NaN}',
        )
        with pytest.raises(self.api.ApiError, match="non-standard JSON"):
            self.api.load_observed_snapshot(nonfinite, expected_realm="us1")

    def test_offline_cli_prints_the_exact_unredacted_schema_safe_plan(
        self, tmp_path, monkeypatch, capsys
    ):
        observed = tmp_path / "observed.json"
        self.api.write_observed_snapshot(
            observed,
            realm="us1",
            integrations=[_gcp_live(name="token=production")],
        )
        key_a = _write_sa_key(tmp_path / "a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "b.json", "project-b")
        plan_path = tmp_path / "plan.json"
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "gcp_integration_api.py",
                "--realm", "us1",
                "--state-dir", str(tmp_path / "state"),
                "--plan-file", str(plan_path),
                "--integration-id", "gcp-id-1",
                "--integration-name", "token=production",
                "--observed-state-file", str(observed),
                "--key-file", str(key_b),
                "--key-file", str(key_a),
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
            _gcp_plan(self.api, tmp_path / "disable", expected_enabled_state=False)
        plan_path, _ = _gcp_plan(
            self.api,
            tmp_path / "delete",
            action="delete",
            expected_enabled_state=False,
        )
        assert json.loads(plan_path.read_text())["expected_enabled_state"] is False

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
            value = "gcp-id-1" if lock_kind == "target" else "exact-name"
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
        with pytest.raises(
            (PermissionError, self.api.ApiError), match="0600|hardlink|hard link"
        ):
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
            with self.api._target_lock("us1", "gcp-id-1"):
                pass

        root = tmp_path / "safe-lock-root"
        monkeypatch.setattr(self.api, "_account_lock_root_path", lambda: root)
        with pytest.raises(OSError, match="body failure"):
            with self.api._target_lock("us1", "gcp-id-1"):
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
        with tempfile.TemporaryDirectory(prefix="gcp-secure-dir-", dir="/tmp") as raw:
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

    @pytest.mark.parametrize(
        "document,error",
        (
            ([], "schema mismatch"),
            (
                {
                    "schema_version": 1,
                    "provider": "GCP",
                    "realm": "us1",
                    "captured_at": "2026-01-01T00:00:00+00:00",
                    "count": 0,
                },
                "schema mismatch",
            ),
            (
                {
                    "schema_version": 1,
                    "provider": "GCP",
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
                    "provider": "GCP",
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
                    "provider": "GCP",
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
                    "provider": "Azure",
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
                    "provider": "GCP",
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
                    "provider": "GCP",
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

    def test_wif_readback_ids_bind_reviewed_state_but_not_put_postconditions(self):
        without_ids = _gcp_live(
            authMethod="WORKLOAD_IDENTITY_FEDERATION",
            workloadIdentityFederationConfig=(
                '{"type":"external_account","audience":"reviewed"}'
            ),
        )
        without_ids.pop("projectServiceKeys", None)
        with_ids = {
            **without_ids,
            "workloadIdentityPoolId": "pool-readback",
            "workloadIdentityProviderId": "provider-readback",
        }
        assert self.api._configuration_fingerprint(
            with_ids, source=self.api._ReviewedStateSource.LIVE_RESPONSE
        ) == (
            self.api._configuration_fingerprint(
                without_ids, source=self.api._ReviewedStateSource.LIVE_RESPONSE
            )
        )
        assert self.api._reviewed_state_sha256(
            self.api._project_live_reviewed_state(with_ids)
        ) != self.api._reviewed_state_sha256(
            self.api._project_live_reviewed_state(without_ids)
        )
        wire = self.api._strip_read_back(with_ids)
        assert "workloadIdentityPoolId" not in wire
        assert "workloadIdentityProviderId" not in wire

    def test_paginated_resolver_and_cross_page_duplicate(self, monkeypatch):
        pages = [
            {"results": [_gcp_live(id="id-1"), _gcp_live(id="id-2", name="other")], "count": 3},
            {"results": [_gcp_live(id="id-3", name="third")], "count": 3},
        ]
        request = Mock(side_effect=pages)
        monkeypatch.setattr(self.api, "_request", request)
        assert self.api.resolve_legacy_name("us1", "unused", "test-gcp")["id"] == "id-1"
        assert request.call_count == 2

        duplicate_pages = [
            {"results": [_gcp_live(id="id-1")], "count": 2},
            {"results": [_gcp_live(id="id-1", name="again")], "count": 2},
        ]
        monkeypatch.setattr(self.api, "_request", Mock(side_effect=duplicate_pages))
        with pytest.raises(self.api.ApiError, match="repeated integration ID"):
            self.api.list_gcp_integrations("us1", "unused")

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
            self.api.list_gcp_integrations("us1", "unused")

    @pytest.mark.parametrize(
        "item,error",
        (
            (_gcp_live(id=1), "integration ID"),
            (_gcp_live(id=True), "integration ID"),
            (_gcp_live(name=None), "integration name"),
            (_gcp_live(name=7), "integration name"),
            (_gcp_live(name="bad\nname"), "integration name"),
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
            self.api.list_gcp_integrations("us1", "unused")

    @pytest.mark.parametrize(
        "response",
        (
            {"count": 1, "items": [_gcp_live()]},
            {"count": 1, "results": [_gcp_live()], "extra": True},
        ),
    )
    def test_pagination_rejects_undocumented_envelopes(
        self, response, monkeypatch
    ):
        monkeypatch.setattr(self.api, "_request", Mock(return_value=response))
        with pytest.raises(self.api.ApiError, match="official count/results"):
            self.api.list_gcp_integrations("us1", "unused")

    def test_pagination_cap_fails_on_first_bounded_request(self, monkeypatch):
        request = Mock(return_value={"results": [_gcp_live()], "count": 10000})
        monkeypatch.setattr(self.api, "_request", request)
        with pytest.raises(self.api.ApiError, match="10,000 cap"):
            self.api.list_gcp_integrations("us1", "unused")
        assert request.call_count == 1

    def test_legacy_resolver_zero_duplicate_and_upsert_duplicate_fail(self, tmp_path, monkeypatch):
        monkeypatch.setattr(self.api, "list_gcp_integrations", lambda *_: [])
        with pytest.raises(self.api.ApiError, match="no GCP integration"):
            self.api.resolve_legacy_name("us1", "unused", "same")
        duplicates = [_gcp_live(id="id-1", name="same"), _gcp_live(id="id-2", name="same")]
        monkeypatch.setattr(self.api, "list_gcp_integrations", lambda *_: duplicates)
        with pytest.raises(self.api.ApiError, match="multiple GCP integrations"):
            self.api.resolve_legacy_name("us1", "unused", "same")

        key_a = _write_sa_key(tmp_path / "a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "b.json", "project-b")
        monkeypatch.setattr(
            self.api,
            "list_gcp_integrations",
            lambda *_: [_gcp_live(id="id-1"), _gcp_live(id="id-2")],
        )
        update = Mock()
        create = Mock()
        monkeypatch.setattr(self.api, "update_integration", update)
        monkeypatch.setattr(self.api, "create_integration", create)
        with pytest.raises(self.api.ApiError, match="multiple GCP integrations"):
            self.api.upsert(
                "us1",
                "unused",
                _gcp_live(id=None),
                tmp_path / "state",
                key_files=[str(key_b), str(key_a)],
            )
        assert update.call_count == 0
        assert create.call_count == 0

    def test_upsert_waiting_on_rollback_target_lock_cannot_reenable(
        self, tmp_path, monkeypatch
    ):
        key_a = _write_sa_key(tmp_path / "a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "b.json", "project-b")
        target_mutex = threading.Lock()
        decision_observed = threading.Event()
        live = _gcp_live()
        errors = []
        update = Mock()

        target_mutex.acquire()

        def list_before_wait(*_args):
            decision_observed.set()
            return [dict(live)]

        @contextmanager
        def ordered_target_lock(_realm, integration_id):
            assert integration_id == "gcp-id-1"
            target_mutex.acquire()
            try:
                yield tmp_path / "claim-root"
            finally:
                target_mutex.release()

        monkeypatch.setattr(self.api, "list_gcp_integrations", list_before_wait)
        monkeypatch.setattr(self.api, "_target_lock", ordered_target_lock)
        monkeypatch.setattr(self.api, "get_integration", lambda *_: dict(live))
        monkeypatch.setattr(self.api, "update_integration", update)

        def run_upsert():
            try:
                self.api.upsert(
                    "us1",
                    "unused",
                    _gcp_live(id=None),
                    tmp_path / "state",
                    key_files=[str(key_b), str(key_a)],
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

    def test_upsert_name_then_target_lock_covers_update_and_journal(
        self, tmp_path, monkeypatch
    ):
        key_a = _write_sa_key(tmp_path / "a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "b.json", "project-b")
        held = {"name": False, "target": False}
        events = []

        @contextmanager
        def name_lock(_realm, exact_name):
            assert exact_name == "test-gcp"
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
            assert exact_id == "gcp-id-1"
            held["target"] = True
            events.append("target-enter")
            try:
                yield tmp_path / "claim-root"
            finally:
                held["target"] = False
                events.append("target-exit")

        def relist(*_args):
            assert held["name"]
            events.append("list")
            return [_gcp_live()]

        def exact_get(*_args):
            assert held["name"] and held["target"]
            events.append("get")
            return _gcp_live()

        def update(*_args, **_kwargs):
            assert held["name"] and held["target"]
            events.append("put")
            return {"id": "gcp-id-1"}

        def journal(*_args, **_kwargs):
            assert held["name"] and held["target"]
            events.append("journal")

        def record(*_args, **_kwargs):
            assert held["name"] and held["target"]
            events.append("hashes")

        monkeypatch.setattr(self.api, "_name_lock", name_lock)
        monkeypatch.setattr(self.api, "_target_lock", target_lock)
        monkeypatch.setattr(self.api, "list_gcp_integrations", relist)
        monkeypatch.setattr(self.api, "get_integration", exact_get)
        monkeypatch.setattr(self.api, "update_integration", update)
        monkeypatch.setattr(self.api, "append_step", journal)
        monkeypatch.setattr(self.api, "_record_credential_hashes", record)
        assert self.api.upsert(
            "us1",
            "unused",
            _gcp_live(id=None),
            tmp_path / "state",
            key_files=[str(key_b), str(key_a)],
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

    def test_upsert_records_hashes_from_the_exact_sent_key_bytes(
        self, tmp_path, monkeypatch
    ):
        key_a = _write_sa_key(tmp_path / "a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "b.json", "project-b")
        original_a = key_a.read_bytes()
        original_b = key_b.read_bytes()
        captured = {}
        monkeypatch.setattr(
            self.api,
            "list_gcp_integrations",
            Mock(side_effect=[[], [_gcp_live()]]),
        )
        monkeypatch.setattr(self.api, "get_integration", Mock(return_value=_gcp_live()))

        def create_once(_realm, _token, payload):
            captured.update(payload)
            _write_sa_key(
                key_a,
                "project-a",
                private_key="-----BEGIN PRIVATE KEY-----\nswapped-a\n-----END PRIVATE KEY-----\n",
            )
            _write_sa_key(
                key_b,
                "project-b",
                private_key="-----BEGIN PRIVATE KEY-----\nswapped-b\n-----END PRIVATE KEY-----\n",
            )
            return {"id": "gcp-id-1"}

        monkeypatch.setattr(self.api, "create_integration", create_once)
        self.api.upsert(
            "us1",
            "unused",
            _gcp_live(id=None),
            tmp_path / "state",
            key_files=[str(key_b), str(key_a)],
        )
        sent = {
            entry["projectId"]: json.loads(entry["projectKey"])
            for entry in captured["projectServiceKeys"]
        }
        assert sent["project-a"] == json.loads(original_a)
        assert sent["project-b"] == json.loads(original_b)
        stored = json.loads((tmp_path / "state" / "credential-hashes.json").read_text())
        assert stored["project_key_sha256"][str(key_a)] == hashlib.sha256(original_a).hexdigest()
        assert stored["project_key_sha256"][str(key_b)] == hashlib.sha256(original_b).hexdigest()

    def test_wif_upsert_records_hash_from_the_exact_sent_config_bytes(
        self, tmp_path, monkeypatch
    ):
        config = _write_private_text(
            tmp_path / "gcp_wif_config.json",
            '{"type":"external_account","audience":"original"}',
        )
        original = config.read_bytes()
        payload = _gcp_live(
            id=None,
            authMethod="WORKLOAD_IDENTITY_FEDERATION",
            workloadIdentityFederationConfig="${FROM_FILE}",
        )
        payload.pop("projectServiceKeys", None)
        confirmed = {
            **payload,
            "id": "gcp-id-1",
            "workloadIdentityFederationConfig": original.decode("utf-8"),
        }
        captured = {}
        monkeypatch.setattr(
            self.api,
            "list_gcp_integrations",
            Mock(side_effect=[[], [confirmed]]),
        )
        monkeypatch.setattr(self.api, "get_integration", Mock(return_value=confirmed))

        def create_once(_realm, _token, sent):
            captured.update(sent)
            config.write_text(
                '{"type":"external_account","audience":"swapped"}',
                encoding="utf-8",
            )
            config.chmod(0o600)
            return {"id": "gcp-id-1"}

        monkeypatch.setattr(self.api, "create_integration", create_once)
        self.api.upsert(
            "us1",
            "unused",
            payload,
            tmp_path / "state",
            wif_config_file=str(config),
        )
        assert json.loads(captured["workloadIdentityFederationConfig"])["audience"] == "original"
        stored = json.loads((tmp_path / "state" / "credential-hashes.json").read_text())
        assert stored["wif_config_sha256"][str(config)] == hashlib.sha256(original).hexdigest()

    @pytest.mark.parametrize("response", ({}, {"id": "other"}, {"id": 3}))
    def test_upsert_update_invalid_response_id_reconciles_once(
        self, response, tmp_path, monkeypatch
    ):
        key_a = _write_sa_key(tmp_path / "a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "b.json", "project-b")
        update = Mock(return_value=response)
        get = Mock(side_effect=[_gcp_live(), _gcp_live()])
        monkeypatch.setattr(
            self.api, "list_gcp_integrations", Mock(return_value=[_gcp_live()])
        )
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "update_integration", update)
        with pytest.raises(self.api.ApiError, match="operator resolution"):
            self.api.upsert(
                "us1", "unused", _gcp_live(id=None), tmp_path / "state",
                key_files=[str(key_b), str(key_a)],
            )
        assert update.call_count == 1
        assert get.call_count == 2

    def test_upsert_update_postcondition_drift_never_retries_put(
        self, tmp_path, monkeypatch
    ):
        key_a = _write_sa_key(tmp_path / "a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "b.json", "project-b")
        update = Mock(return_value={"id": "gcp-id-1"})
        get = Mock(side_effect=[_gcp_live(), _gcp_live(pollRate=600000)])
        monkeypatch.setattr(
            self.api, "list_gcp_integrations", Mock(return_value=[_gcp_live()])
        )
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "update_integration", update)
        with pytest.raises(self.api.ApiError, match="postcondition"):
            self.api.upsert(
                "us1", "unused", _gcp_live(id=None), tmp_path / "state",
                key_files=[str(key_b), str(key_a)],
            )
        assert update.call_count == 1

    @pytest.mark.parametrize("response", ({}, {"id": 9}))
    def test_upsert_create_requires_server_id_and_reconciles_by_exact_name(
        self, response, tmp_path, monkeypatch
    ):
        key_a = _write_sa_key(tmp_path / "a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "b.json", "project-b")
        create = Mock(return_value=response)
        listing = Mock(side_effect=[[], []])
        monkeypatch.setattr(self.api, "list_gcp_integrations", listing)
        monkeypatch.setattr(self.api, "create_integration", create)
        with pytest.raises(self.api.ApiError, match="operator resolution"):
            self.api.upsert(
                "us1", "unused", _gcp_live(id=None), tmp_path / "state",
                key_files=[str(key_b), str(key_a)],
            )
        assert create.call_count == 1
        assert listing.call_count == 2

    def test_upsert_create_relist_duplicate_fails_without_second_post(
        self, tmp_path, monkeypatch
    ):
        key_a = _write_sa_key(tmp_path / "a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "b.json", "project-b")
        created = _gcp_live(id="created-id")
        listing = Mock(side_effect=[[], [created, _gcp_live(id="other-id")]])
        create = Mock(return_value={"id": "created-id"})
        monkeypatch.setattr(self.api, "list_gcp_integrations", listing)
        monkeypatch.setattr(self.api, "create_integration", create)
        monkeypatch.setattr(self.api, "get_integration", Mock(return_value=created))
        with pytest.raises(self.api.ApiError, match="name uniqueness"):
            self.api.upsert(
                "us1", "unused", _gcp_live(id=None), tmp_path / "state",
                key_files=[str(key_b), str(key_a)],
            )
        assert create.call_count == 1

    @pytest.mark.parametrize("method", ("PUT", "POST"))
    def test_upsert_credential_echo_response_is_one_protocol_failure(
        self, method, tmp_path, monkeypatch, capsys
    ):
        key_a = _write_sa_key(tmp_path / "a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "b.json", "project-b")
        canary = f"GCP-{method}-RESPONSE-CREDENTIAL-CANARY"
        response = _gcp_live(
            projectServiceKeys=[
                {"projectId": "project-a", "projectKey": canary},
                {"projectId": "project-b"},
            ]
        )
        state_dir = tmp_path / "state"
        if method == "PUT":
            monkeypatch.setattr(
                self.api,
                "list_gcp_integrations",
                Mock(return_value=[_gcp_live()]),
            )
            monkeypatch.setattr(
                self.api, "get_integration", Mock(return_value=_gcp_live())
            )
            mutation = Mock(return_value=response)
            monkeypatch.setattr(self.api, "update_integration", mutation)
        else:
            monkeypatch.setattr(
                self.api, "list_gcp_integrations", Mock(return_value=[])
            )
            mutation = Mock(return_value=response)
            monkeypatch.setattr(self.api, "create_integration", mutation)
        with pytest.raises(self.api.ApiError, match="violated the reviewed schema") as error:
            self.api.upsert(
                "us1",
                "unused",
                _gcp_live(id=None),
                state_dir,
                key_files=[str(key_b), str(key_a)],
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

    def test_wif_upsert_ignores_readback_pool_provider_ids_in_postcondition(
        self, tmp_path, monkeypatch
    ):
        config = _write_private_text(
            tmp_path / "gcp_wif_config.json",
            '{"type":"external_account","audience":"reviewed"}',
        )
        live = _gcp_live(
            authMethod="WORKLOAD_IDENTITY_FEDERATION",
            workloadIdentityFederationConfig=(
                '{"type":"external_account","audience":"reviewed"}'
            ),
            wifSplunkIdentity="read-only",
            workloadIdentityPoolId="pool-read-only",
            workloadIdentityProviderId="provider-read-only",
        )
        live.pop("projectServiceKeys", None)
        listing = Mock(side_effect=[[live], [live]])
        update = Mock(return_value={"id": "gcp-id-1"})
        monkeypatch.setattr(self.api, "list_gcp_integrations", listing)
        monkeypatch.setattr(self.api, "get_integration", Mock(return_value=live))
        monkeypatch.setattr(self.api, "update_integration", update)
        payload = {**live, "id": None}
        assert self.api.upsert(
            "us1",
            "unused",
            payload,
            tmp_path / "state",
            wif_config_file=str(config),
        )["result"] == "updated"
        sent = update.call_args.args[3]
        assert "workloadIdentityPoolId" not in sent
        assert "workloadIdentityProviderId" not in sent
        assert "wifSplunkIdentity" not in sent

    def test_service_account_loader_multiline_mapping_and_coverage_failures(self, tmp_path):
        key_a = _write_sa_key(tmp_path / "a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "b.json", "project-b")
        payload = self.api._inject_service_account_keys(
            _gcp_live(id=None),
            self.api._load_service_account_keys_by_project([str(key_b), str(key_a)]),
        )
        entries = payload["projectServiceKeys"]
        assert [entry["projectId"] for entry in entries] == ["project-a", "project-b"]
        assert json.loads(entries[0]["projectKey"])["project_id"] == "project-a"
        assert "\nline-one\n" in json.loads(entries[0]["projectKey"])["private_key"]

        with pytest.raises(self.api.ApiError, match="missing=.*project-b"):
            self.api._inject_service_account_keys(
                _gcp_live(id=None),
                self.api._load_service_account_keys_by_project([str(key_a)]),
            )
        extra = _write_sa_key(tmp_path / "extra.json", "project-extra")
        with pytest.raises(self.api.ApiError, match="extra=.*project-extra"):
            self.api._inject_service_account_keys(
                _gcp_live(id=None),
                self.api._load_service_account_keys_by_project(
                    [str(key_a), str(key_b), str(extra)]
                ),
            )
        duplicate = _write_sa_key(tmp_path / "duplicate.json", "project-a")
        with pytest.raises(self.api.ApiError, match="duplicate.*project-a"):
            self.api._inject_service_account_keys(
                _gcp_live(id=None),
                self.api._load_service_account_keys_by_project(
                    [str(key_a), str(duplicate), str(key_b)]
                ),
            )

    def test_service_account_loader_rejects_mode_symlink_and_mismatch(self, tmp_path):
        key = _write_sa_key(tmp_path / "key.json", "wrong-project")
        key.chmod(0o644)
        with pytest.raises(self.api.ApiError, match="mode 600"):
            self.api.load_gcp_service_account_key(str(key))
        key.chmod(0o600)
        link = tmp_path / "link.json"
        link.symlink_to(key)
        with pytest.raises(self.api.ApiError, match="non-symlink"):
            self.api.load_gcp_service_account_key(str(link))
        with pytest.raises(self.api.ApiError, match="coverage mismatch"):
            self.api._inject_service_account_keys(
                _gcp_live(id=None),
                self.api._load_service_account_keys_by_project([str(key)]),
            )

    @pytest.mark.parametrize(
        "body,error",
        (
            (
                '{"type":"service_account","project_id":"one",'
                '"project_id":"two","private_key_id":"key",'
                '"private_key":"-----BEGIN PRIVATE KEY-----\\nline\\n-----END PRIVATE KEY-----\\n",'
                '"client_email":"one@example.test"}',
                "duplicate JSON object key.*project_id",
            ),
            (
                '{"type":"service_account","project_id":"one",'
                '"private_key_id":"key","private_key":"first",'
                '"private_key":"second","client_email":"one@example.test"}',
                "duplicate JSON object key.*private_key",
            ),
            (
                '{"type":"service_account","project_id":"one",'
                '"private_key_id":"key","private_key":NaN,'
                '"client_email":"one@example.test"}',
                "non-standard JSON constant",
            ),
        ),
    )
    def test_service_account_json_rejects_duplicate_keys_and_nonfinite_values(
        self, body, error, tmp_path, monkeypatch
    ):
        key = _write_private_text(tmp_path / "adversarial.json", body)
        transport = Mock(side_effect=AssertionError("transport"))
        monkeypatch.setattr(self.api, "_request", transport)
        with pytest.raises(self.api.ApiError, match=error):
            self.api.load_gcp_service_account_key(str(key))
        assert transport.call_count == 0

    @pytest.mark.parametrize(
        "body,error",
        (
            ('{"type":"external_account","type":"other"}', "duplicate JSON object key"),
            ('{"type":"external_account","poison":Infinity}', "non-standard JSON constant"),
        ),
    )
    def test_wif_json_rejects_duplicate_keys_and_nonfinite_values(
        self, body, error, tmp_path, monkeypatch
    ):
        config = _write_private_text(tmp_path / "gcp_wif_config.json", body)
        transport = Mock(side_effect=AssertionError("transport"))
        monkeypatch.setattr(self.api, "_request", transport)
        with pytest.raises(self.api.ApiError, match=error):
            self.api.load_wif_config_file(str(config))
        assert transport.call_count == 0

    def test_direct_python_rollback_bypass_fails(self, monkeypatch):
        transport = Mock()
        monkeypatch.setattr(self.api, "_request", transport)
        with pytest.raises(self.api.ApiError, match="direct disable"):
            self.api.disable_integration("us1", "unused", "gcp-id-1")
        with pytest.raises(self.api.ApiError, match="direct delete"):
            self.api.delete_integration("us1", "unused", "gcp-id-1")
        assert transport.call_count == 0

    @pytest.mark.parametrize(
        "payload,error",
        (
            ({}, "explicit Boolean"),
            ({"enabled": "false"}, "explicit Boolean"),
            ({"enabled": False}, "refusing disabling PUT"),
        ),
    )
    def test_update_requires_explicit_enabled_and_capability(
        self, payload, error, monkeypatch
    ):
        transport = Mock()
        monkeypatch.setattr(self.api, "_request", transport)
        with pytest.raises(self.api.ApiError, match=error):
            self.api.update_integration("us1", "unused", "gcp-id-1", payload)
        assert transport.call_count == 0

    def test_normal_enabled_update_remains_allowed(self, monkeypatch):
        transport = Mock(return_value={"id": "gcp-id-1"})
        monkeypatch.setattr(self.api, "_request", transport)
        assert self.api.update_integration(
            "us1", "unused", "gcp-id-1", {"enabled": True}
        ) == {"id": "gcp-id-1"}
        assert transport.call_count == 1

    def test_upsert_cannot_disable_an_existing_integration(
        self, tmp_path, monkeypatch
    ):
        key_a = _write_sa_key(tmp_path / "a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "b.json", "project-b")
        update = Mock()
        monkeypatch.setattr(
            self.api, "list_gcp_integrations", Mock(return_value=[_gcp_live()])
        )
        monkeypatch.setattr(self.api, "update_integration", update)
        with pytest.raises(self.api.ApiError, match="reviewed rollback"):
            self.api.upsert(
                "us1",
                "unused",
                _gcp_live(id=None, enabled=False),
                tmp_path / "state",
                key_files=[str(key_b), str(key_a)],
            )
        assert update.call_count == 0


class TestGCPRollbackMutation:
    def setup_method(self):
        self.api = _load_api_client()

    @pytest.fixture(autouse=True)
    def _isolate_account_lock_root(self, tmp_path, monkeypatch):
        root = tmp_path / "account-lock-root"
        monkeypatch.setattr(self.api, "_account_lock_root_path", lambda: root)
        monkeypatch.setattr(
            self.api,
            "list_gcp_integrations",
            lambda _realm, _token: [_gcp_live()],
        )

    def _apply_kwargs(self, tmp_path, *, action="disable"):
        plan_path, plan_hash = _gcp_plan(self.api, tmp_path, action=action)
        kwargs = {
            "realm": "us1",
            "token": "unused",
            "state_dir": tmp_path / "state",
            "plan_path": plan_path,
            "plan_sha256": plan_hash,
            "action": action,
            "integration_id": "gcp-id-1",
            "apply_gate": True,
            "acknowledge_disable": "gcp-id-1" if action == "disable" else "",
            "acknowledge_delete": "gcp-id-1" if action == "delete" else "",
        }
        if action == "disable":
            kwargs["key_files"] = [
                str(tmp_path / "project-b.json"),
                str(tmp_path / "project-a.json"),
            ]
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
            Mock(
                return_value=_gcp_live(
                    projectServiceKeys=[
                        {
                            "projectId": "project-a",
                            "projectKey": "GCP-PREFLIGHT-CANARY",
                        }
                    ]
                )
            ),
        )
        with pytest.raises(self.api.ApiError, match="response-side projectKey"):
            self.api.apply_rollback(**kwargs)
        assert claim.call_count == 0
        assert update.call_count == 0
        assert not (kwargs["state_dir"] / "apply-state.json").exists()

    def test_response_credentials_in_postcondition_are_one_redacted_failure(
        self, tmp_path, monkeypatch, capsys
    ):
        kwargs = self._apply_kwargs(tmp_path)
        canary = "GCP-POSTCONDITION-RESPONSE-CANARY"
        disabled = _gcp_live(enabled=False)
        bad_disabled = _gcp_live(
            enabled=False,
            projectServiceKeys=[
                {"projectId": "project-a", "projectKey": canary}
            ],
        )
        monkeypatch.setattr(
            self.api,
            "get_integration",
            Mock(side_effect=[_gcp_live(), _gcp_live(), bad_disabled, disabled]),
        )
        update = Mock(return_value=disabled)
        monkeypatch.setattr(self.api, "update_integration", update)
        with pytest.raises(self.api.ApiError, match="response-side projectKey") as error:
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

    def test_wrong_and_fingerprint_drift_preflight_prevent_mutation(self, tmp_path, monkeypatch):
        kwargs = self._apply_kwargs(tmp_path)
        update = Mock()
        monkeypatch.setattr(self.api, "update_integration", update)
        monkeypatch.setattr(self.api, "get_integration", Mock(return_value=_gcp_live(name="wrong")))
        with pytest.raises(self.api.ApiError, match="different integration name"):
            self.api.apply_rollback(**kwargs)
        assert update.call_count == 0
        monkeypatch.setattr(
            self.api,
            "get_integration",
            Mock(side_effect=[_gcp_live(), _gcp_live(pollRate=600000)]),
        )
        with pytest.raises(self.api.ApiError, match="reviewed observed snapshot"):
            self.api.apply_rollback(**kwargs)
        assert update.call_count == 0

    def test_plan_time_revision_drift_and_new_duplicate_name_fail_before_claim(
        self, tmp_path, monkeypatch
    ):
        observed = tmp_path / "observed.json"
        reviewed = _gcp_live(lastUpdated=100)
        self.api.write_observed_snapshot(
            observed, realm="us1", integrations=[reviewed]
        )
        key_a = _write_sa_key(tmp_path / "a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "b.json", "project-b")
        rendered = self.api.render_rollback_plan(
            tmp_path / "plan.json",
            realm="us1",
            action="disable",
            integration_id="gcp-id-1",
            integration_name="test-gcp",
            expected_enabled_state=True,
            observed_state_file=str(observed),
            key_files=[str(key_b), str(key_a)],
        )
        kwargs = {
            "realm": "us1",
            "token": "unused",
            "state_dir": tmp_path / "state",
            "plan_path": tmp_path / "plan.json",
            "plan_sha256": rendered["plan_hash"],
            "action": "disable",
            "integration_id": "gcp-id-1",
            "apply_gate": True,
            "acknowledge_disable": "gcp-id-1",
            "key_files": [str(key_b), str(key_a)],
        }
        update = Mock()
        claim = Mock()
        monkeypatch.setattr(self.api, "update_integration", update)
        monkeypatch.setattr(self.api, "claim_rollback_attempt", claim)
        monkeypatch.setattr(
            self.api,
            "get_integration",
            Mock(return_value=_gcp_live(lastUpdated=101)),
        )
        with pytest.raises(self.api.ApiError, match="reviewed observed snapshot"):
            self.api.apply_rollback(**kwargs)
        assert update.call_count == claim.call_count == 0

        get = Mock()
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(
            self.api,
            "list_gcp_integrations",
            lambda *_: [reviewed, _gcp_live(id="gcp-id-2")],
        )
        with pytest.raises(self.api.ApiError, match="one exact reviewed name"):
            self.api.apply_rollback(**kwargs)
        assert get.call_count == update.call_count == claim.call_count == 0

    @pytest.mark.parametrize("response", ({}, {"id": "other-id"}, {"id": 7}))
    def test_disable_invalid_put_response_id_reconciles_without_retry(
        self, response, tmp_path, monkeypatch
    ):
        kwargs = self._apply_kwargs(tmp_path)
        get = Mock(side_effect=[_gcp_live(), _gcp_live(), _gcp_live()])
        update = Mock(return_value=response)
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "update_integration", update)
        with pytest.raises(self.api.ApiError, match="operator resolution"):
            self.api.apply_rollback(**kwargs)
        assert update.call_count == 1
        assert get.call_count == 3

    def test_credential_binding_and_parse_fail_before_any_live_get(
        self, tmp_path, monkeypatch
    ):
        kwargs = self._apply_kwargs(tmp_path)
        get = Mock()
        update = Mock()
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "update_integration", update)
        _write_sa_key(
            Path(kwargs["key_files"][0]),
            "project-b",
            private_key=(
                "-----BEGIN PRIVATE KEY-----\nsubstituted\n-----END PRIVATE KEY-----\n"
            ),
        )
        with pytest.raises(self.api.ApiError, match="changed since plan review"):
            self.api.apply_rollback(**kwargs)
        assert get.call_count == update.call_count == 0

        malformed = self._apply_kwargs(tmp_path / "malformed")
        Path(malformed["key_files"][0]).write_text("{", encoding="utf-8")
        Path(malformed["key_files"][0]).chmod(0o600)
        with pytest.raises(self.api.ApiError, match="valid UTF-8 JSON"):
            self.api.apply_rollback(**malformed)
        assert get.call_count == update.call_count == 0

    def test_disable_maps_keys_by_project_and_redacts_secrets(self, tmp_path, monkeypatch):
        kwargs = self._apply_kwargs(tmp_path)
        disabled = _gcp_live(enabled=False)
        monkeypatch.setattr(
            self.api,
            "get_integration",
            Mock(side_effect=[_gcp_live(), _gcp_live(), disabled, disabled]),
        )
        captured = {}

        def update_once(_realm, _token, _integration_id, payload, **_kwargs):
            captured.update(payload)
            return _gcp_live(id=_integration_id, enabled=False)

        update = Mock(side_effect=update_once)
        monkeypatch.setattr(self.api, "update_integration", update)
        assert self.api.apply_rollback(**kwargs)["result"] == "disabled"
        assert update.call_count == 1
        parsed = [json.loads(entry["projectKey"]) for entry in captured["projectServiceKeys"]]
        assert [document["project_id"] for document in parsed] == ["project-a", "project-b"]
        private_values = [document["private_key"] for document in parsed]
        combined = kwargs["plan_path"].read_text() + (kwargs["state_dir"] / "apply-state.json").read_text()
        assert all(secret not in combined for secret in private_values)

    def test_disable_reads_each_bound_credential_file_once(
        self, tmp_path, monkeypatch
    ):
        kwargs = self._apply_kwargs(tmp_path)
        original = self.api.read_private_file_bytes
        opened = []

        def counted(path, **options):
            opened.append(str(path))
            return original(path, **options)

        disabled = _gcp_live(enabled=False)
        monkeypatch.setattr(self.api, "read_private_file_bytes", counted)
        monkeypatch.setattr(
            self.api,
            "get_integration",
            Mock(side_effect=[_gcp_live(), _gcp_live(), disabled, disabled]),
        )
        monkeypatch.setattr(
            self.api, "update_integration", Mock(return_value={"id": "gcp-id-1"})
        )
        self.api.apply_rollback(**kwargs)
        credential_opens = [path for path in opened if path in kwargs["key_files"]]
        assert credential_opens == kwargs["key_files"]
        assert all(opened.count(path) == 1 for path in kwargs["key_files"])

    @pytest.mark.parametrize("source_shape", ("missing", "null"))
    def test_missing_or_null_auth_method_is_preserved_for_bound_sa_disable(
        self, source_shape, tmp_path, monkeypatch
    ):
        observed = tmp_path / "observed.json"
        reviewed = _gcp_live()
        if source_shape == "missing":
            reviewed.pop("authMethod")
        else:
            reviewed["authMethod"] = None
        self.api.write_observed_snapshot(
            observed, realm="us1", integrations=[reviewed]
        )
        key_a = _write_sa_key(tmp_path / "a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "b.json", "project-b")
        rendered = self.api.render_rollback_plan(
            tmp_path / "plan.json",
            realm="us1",
            action="disable",
            integration_id="gcp-id-1",
            integration_name="test-gcp",
            expected_enabled_state=True,
            observed_state_file=str(observed),
            key_files=[str(key_b), str(key_a)],
        )
        kwargs = {
            "realm": "us1",
            "token": "unused",
            "state_dir": tmp_path / "state",
            "plan_path": tmp_path / "plan.json",
            "plan_sha256": rendered["plan_hash"],
            "action": "disable",
            "integration_id": "gcp-id-1",
            "apply_gate": True,
            "acknowledge_disable": "gcp-id-1",
            "key_files": [str(key_b), str(key_a)],
        }
        disabled = {**reviewed, "enabled": False}
        monkeypatch.setattr(
            self.api,
            "list_gcp_integrations",
            lambda *_: [reviewed],
        )
        monkeypatch.setattr(
            self.api,
            "get_integration",
            Mock(side_effect=[reviewed, reviewed, disabled, disabled]),
        )
        captured = {}
        monkeypatch.setattr(
            self.api,
            "update_integration",
            Mock(
                side_effect=lambda _r, _t, _i, payload, **_kwargs: captured.update(payload)
                or {"id": _i}
            ),
        )
        assert self.api.apply_rollback(**kwargs)["result"] == "disabled"
        if source_shape == "missing":
            assert "authMethod" not in captured
        else:
            assert captured["authMethod"] is None

    def test_wif_disable_uses_validated_config_loader(self, tmp_path, monkeypatch):
        plan_path, plan_hash = _gcp_plan(self.api, tmp_path, auth_method="wif")
        kwargs = {
            "realm": "us1",
            "token": "unused",
            "state_dir": tmp_path / "state",
            "plan_path": plan_path,
            "plan_sha256": plan_hash,
            "action": "disable",
            "integration_id": "gcp-id-1",
            "apply_gate": True,
            "acknowledge_disable": "gcp-id-1",
            "wif_config_file": str(tmp_path / "gcp_wif_config.json"),
        }
        live = _gcp_live(
            authMethod="WORKLOAD_IDENTITY_FEDERATION",
            workloadIdentityFederationConfig=(
                '{"type":"external_account","audience":"reviewed"}'
            ),
            wifSplunkIdentity="reviewed-read-only-identity",
        )
        live.pop("projectServiceKeys", None)
        disabled = {**live, "enabled": False}
        monkeypatch.setattr(
            self.api,
            "get_integration",
            Mock(side_effect=[live, live, disabled, disabled]),
        )
        captured = {}
        monkeypatch.setattr(
            self.api,
            "update_integration",
            Mock(
                side_effect=lambda _r, _t, _i, payload, **_kwargs: captured.update(payload)
                or {"id": _i}
            ),
        )
        assert self.api.apply_rollback(**kwargs)["result"] == "disabled"
        assert json.loads(captured["workloadIdentityFederationConfig"])["audience"] == "reviewed"
        assert "projectServiceKeys" not in captured
        assert "wifSplunkIdentity" not in captured

    def test_mocked_upsert_plan_and_journal_never_contain_private_key(self, tmp_path, monkeypatch):
        key_a = _write_sa_key(tmp_path / "upsert-a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "upsert-b.json", "project-b")
        private_key = json.loads(key_a.read_text())["private_key"]
        monkeypatch.setattr(
            self.api,
            "list_gcp_integrations",
            Mock(side_effect=[[], [_gcp_live()]]),
        )
        monkeypatch.setattr(self.api, "get_integration", Mock(return_value=_gcp_live()))
        monkeypatch.setattr(
            self.api,
            "create_integration",
            lambda _r, _t, _payload: _gcp_live(id="gcp-id-1"),
        )
        self.api.upsert(
            "us1",
            "unused",
            _gcp_live(id=None),
            tmp_path / "upsert-state",
            key_files=[str(key_b), str(key_a)],
        )
        journal = (tmp_path / "upsert-state" / "apply-state.json").read_text()
        assert private_key not in journal

    def test_put_delete_and_postcondition_each_mutate_once(self, tmp_path, monkeypatch):
        put_kwargs = self._apply_kwargs(tmp_path / "put")
        get = Mock(side_effect=[_gcp_live(), _gcp_live(), _gcp_live()])
        update = Mock(side_effect=self.api.AmbiguousMutationError("ambiguous PUT"))
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "update_integration", update)
        with pytest.raises(self.api.ApiError, match="operator resolution"):
            self.api.apply_rollback(**put_kwargs)
        assert update.call_count == 1
        assert get.call_count == 3

        delete_kwargs = self._apply_kwargs(tmp_path / "delete", action="delete")
        get = Mock(side_effect=[_gcp_live(), _gcp_live(), _gcp_live()])
        delete = Mock(side_effect=self.api.AmbiguousMutationError("ambiguous DELETE"))
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "delete_integration", delete)
        with pytest.raises(self.api.ApiError, match="operator resolution"):
            self.api.apply_rollback(**delete_kwargs)
        assert delete.call_count == 1
        assert get.call_count == 3

        post_kwargs = self._apply_kwargs(tmp_path / "post")
        get = Mock(side_effect=[_gcp_live(), _gcp_live()] + [_gcp_live()] * 5)
        update = Mock(return_value={"id": "gcp-id-1"})
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "update_integration", update)
        monkeypatch.setattr(self.api.time, "sleep", Mock())
        with pytest.raises(self.api.ApiError, match="postcondition"):
            self.api.apply_rollback(**post_kwargs)
        assert update.call_count == 1
        journal = (post_kwargs["state_dir"] / "apply-state.json").read_text()
        assert "bounded disable postcondition polling failed" in journal

    def test_copied_plan_different_plan_and_state_dirs_is_permanently_consumed(
        self, tmp_path, monkeypatch
    ):
        kwargs = self._apply_kwargs(tmp_path / "first")
        update = Mock(side_effect=self.api.AmbiguousMutationError("ambiguous PUT"))
        monkeypatch.setattr(self.api, "get_integration", Mock(return_value=_gcp_live()))
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
        original_loader = self.api._load_gcp_credential_material

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
            return _gcp_live(enabled=enabled)

        def update_once(*_args, **_kwargs):
            mutation_entered.set()
            assert release_mutation.wait(5)
            with state_guard:
                state["enabled"] = False
            return {"id": "gcp-id-1"}

        update = Mock(side_effect=update_once)
        monkeypatch.setattr(self.api, "_load_gcp_credential_material", load_credentials)
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

    def test_disable_rejects_unknown_postcondition_state_without_retry(
        self, tmp_path, monkeypatch
    ):
        kwargs = self._apply_kwargs(tmp_path)
        drifted = _gcp_live(enabled=False, nested={"id": "changed"})
        get = Mock(side_effect=[_gcp_live(), _gcp_live(), drifted, drifted])
        update = Mock(return_value={"id": "gcp-id-1"})
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "update_integration", update)
        with pytest.raises(self.api.ApiError, match="response schema mismatch"):
            self.api.apply_rollback(**kwargs)
        assert update.call_count == 1
        journal = (kwargs["state_dir"] / "apply-state.json").read_text()
        assert "reviewed state response schema mismatch" in journal

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
            confirmed = _gcp_live(enabled=False)
            if scenario == "final-get-error":
                final = self.api.ApiError("final exact GET failed")
            elif scenario == "final-identity-drift":
                final = _gcp_live(enabled=False, name="drifted-name")
            else:
                confirmed = _gcp_live(enabled=False, pollRate=600000)
                final = _gcp_live(enabled=False, pollRate=600000)
            get = Mock(side_effect=[_gcp_live(), _gcp_live(), confirmed, final])
            mutation = Mock(return_value={"id": "gcp-id-1"})
            monkeypatch.setattr(self.api, "update_integration", mutation)
        else:
            final = (
                self.api.ApiError("final exact GET failed")
                if scenario == "final-get-error"
                else _gcp_live(name="drifted-name")
            )
            get = Mock(side_effect=[_gcp_live(), _gcp_live(), {}, final])
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

    def test_claim_failure_and_delete_credentials_abort_before_mutation(
        self, tmp_path, monkeypatch
    ):
        kwargs = self._apply_kwargs(tmp_path / "claim")
        update = Mock()
        monkeypatch.setattr(
            self.api,
            "get_integration",
            Mock(side_effect=[_gcp_live(), _gcp_live()]),
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

        delete_kwargs = self._apply_kwargs(tmp_path / "delete", action="delete")
        credential_load = Mock(side_effect=AssertionError("credential read"))
        get = Mock()
        delete = Mock()
        monkeypatch.setattr(self.api, "_load_gcp_credential_material", credential_load)
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "delete_integration", delete)
        delete_kwargs["key_files"] = [str(tmp_path / "unused.json")]
        with pytest.raises(self.api.ApiError, match="rejects GCP credential"):
            self.api.apply_rollback(**delete_kwargs)
        assert credential_load.call_count == get.call_count == delete.call_count == 0

    def test_polling_lock_scope_and_delete_empty_verification(self, tmp_path, monkeypatch):
        kwargs = self._apply_kwargs(tmp_path / "disable")
        locked = {"active": False}

        @contextmanager
        def lock(_realm, _integration_id):
            locked["active"] = True
            try:
                claim_root = tmp_path / "fake-claim-root"
                claim_root.mkdir(mode=0o700, exist_ok=True)
                yield claim_root
            finally:
                locked["active"] = False

        responses = iter(
            [_gcp_live(), _gcp_live(), _gcp_live(), _gcp_live(enabled=False), _gcp_live(enabled=False)]
        )

        def get_locked(*_args):
            assert locked["active"]
            return next(responses)

        update = Mock(
            side_effect=lambda *_args, **_kwargs: {"id": "gcp-id-1"}
            if locked["active"]
            else pytest.fail("unlocked PUT")
        )

        def append_locked(*_args, **_kwargs):
            assert locked["active"]

        monkeypatch.setattr(self.api, "_target_lock", lock)
        monkeypatch.setattr(self.api, "get_integration", get_locked)
        monkeypatch.setattr(self.api, "update_integration", update)
        monkeypatch.setattr(self.api, "append_step", append_locked)
        monkeypatch.setattr(self.api.time, "sleep", Mock())
        assert self.api.apply_rollback(**kwargs)["result"] == "disabled"
        assert update.call_count == 1
        assert locked["active"] is False

        delete_kwargs = self._apply_kwargs(tmp_path / "delete-ok", action="delete")
        get = Mock(side_effect=[_gcp_live(), _gcp_live(), {}, {}])
        delete = Mock(return_value={})
        monkeypatch.setattr(self.api, "_target_lock", self.api._target_lock)
        monkeypatch.setattr(self.api, "get_integration", get)
        monkeypatch.setattr(self.api, "delete_integration", delete)
        monkeypatch.setattr(self.api, "append_step", Mock())
        assert self.api.apply_rollback(**delete_kwargs)["result"] == "deleted"
        assert delete.call_count == 1
        assert get.call_count == 4


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

    @pytest.mark.parametrize("script_name", ("doctor.sh", "validate.sh"))
    def test_all_reachable_rejects_explicit_empty_selected_project_ids(
        self, script_name, tmp_path
    ):
        rendered_dir = tmp_path / "argv safe ' rendered"
        mod = _load_renderer()
        spec = mod.validate_spec(_valid_sa_key_spec())
        mod.render(spec, rendered_dir)
        create_json = rendered_dir / "rest" / "create.json"
        payload = json.loads(create_json.read_text(encoding="utf-8"))
        payload["projects"]["selectedProjectIds"] = []
        create_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        result = subprocess.run(
            ["bash", str(SCRIPTS_DIR / script_name), "--output-dir", str(rendered_dir)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )

        assert result.returncode != 0
        combined_output = result.stdout + result.stderr
        assert "rest/create.json" in combined_output
        assert "shape validation" in combined_output

    @pytest.mark.parametrize("script_name", ("doctor.sh", "validate.sh"))
    def test_all_reachable_accepts_absent_selected_project_ids(
        self, script_name, tmp_path
    ):
        rendered_dir = tmp_path / "argv safe ' rendered"
        mod = _load_renderer()
        spec = mod.validate_spec(_valid_sa_key_spec())
        mod.render(spec, rendered_dir)
        payload = json.loads(
            (rendered_dir / "rest" / "create.json").read_text(encoding="utf-8")
        )
        assert payload["projects"]["syncMode"] == "ALL_REACHABLE"
        assert "selectedProjectIds" not in payload["projects"]

        result = subprocess.run(
            ["bash", str(SCRIPTS_DIR / script_name), "--output-dir", str(rendered_dir)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
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
            ("--token=GCP-SHELL-CANARY",),
            ("--project-key=GCP-SHELL-CANARY",),
            ("--token", "GCP-SHELL-CANARY"),
            ("--tokne=GCP-SHELL-CANARY",),
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
        assert "GCP-SHELL-CANARY" not in result.stdout + result.stderr

    @pytest.mark.parametrize(
        "arguments",
        (
            ("--token=GCP-PYTHON-CANARY",),
            ("--project-key=GCP-PYTHON-CANARY",),
            ("--tokne=GCP-PYTHON-CANARY",),
        ),
    )
    def test_python_secret_and_unknown_flags_never_echo_values(self, arguments):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "gcp_integration_api.py"), *arguments],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode != 0
        assert "GCP-PYTHON-CANARY" not in result.stdout + result.stderr

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
        unsafe_path = tmp_path / "client_secret=GCP-PATH-ERROR-CANARY"
        safe_path = tmp_path / "client-secret-material.json"

        def invoke(token_path: Path):
            return subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "gcp_integration_api.py"),
                    "--realm",
                    "us1",
                    "--state-dir",
                    str(state_dir),
                    "--token-file",
                    str(token_path),
                    "--integration-id",
                    "gcp-id-1",
                    "get",
                ],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )

        unsafe = invoke(unsafe_path)
        assert unsafe.returncode != 0
        assert "GCP-PATH-ERROR-CANARY" not in unsafe.stdout + unsafe.stderr
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
        valid_key = _write_private_text(tmp_path / "sa-key.json", "{}")
        valid_token = _write_private_text(tmp_path / "token", "test-token\n")
        unsafe_names = (
            "client_secret=GCP-SHELL-PATH-CANARY",
            "e30.e30.QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo",
        )

        for unsafe_name in unsafe_names:
            unsafe_key = tmp_path / unsafe_name
            unsafe_wif = tmp_path / unsafe_name / "gcp_wif_config.json"
            render_cases = (
                ("--key-file", unsafe_key),
                ("--wif-config-file", unsafe_wif),
            )
            apply_cases = (
                ("--key-file", unsafe_key, "--token-file", valid_token),
                ("--wif-config-file", unsafe_wif, "--token-file", valid_token),
                ("--key-file", valid_key, "--token-file", unsafe_key),
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
                        "gcp-id-1",
                        "--integration-name",
                        "test-gcp",
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
                        "gcp-id-1",
                        "--plan-file",
                        str(tmp_path / "unread-plan.json"),
                        "--plan-hash",
                        "a" * 64,
                        "--accept-disable-integration",
                        "gcp-id-1",
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

        loose = tmp_path / "client_secret=GCP-LOOSE-PATH-CANARY"
        loose.write_text("{}", encoding="utf-8")
        loose.chmod(0o644)
        for apply_args in (
            (
                "--integration-name",
                "test-gcp",
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
                "gcp-id-1",
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
                    "gcp-id-1",
                    "--key-file",
                    str(loose),
                    "--output-dir",
                    str(tmp_path / "loose-output"),
                    *(str(value) for value in apply_args),
                ],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            assert result.returncode != 0
            assert "GCP-LOOSE-PATH-CANARY" not in result.stdout + result.stderr
            assert "loose permissions" in result.stdout + result.stderr

    @pytest.mark.parametrize(
        "extra",
        (
            ("--token-file", "/not-opened/token"),
            ("--allow-loose-token-perms",),
            ("--plan-hash", "0" * 64),
            ("--accept-delete-integration", "gcp-id-1"),
        ),
    )
    def test_offline_delete_render_rejects_apply_only_flags_without_file_reads(
        self, extra, tmp_path
    ):
        observed = tmp_path / "observed.json"
        _load_api_client().write_observed_snapshot(
            observed, realm="us1", integrations=[_gcp_live()]
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
                "gcp-id-1",
                "--integration-name",
                "test-gcp",
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
            observed, realm="us1", integrations=[_gcp_live()]
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
                "gcp-id-1",
                "--integration-name",
                "test-gcp",
                "--observed-state-file",
                str(observed),
                "--key-file",
                "/not-opened/project.json",
                "--wif-config-file",
                "/not-opened/gcp_wif_config.json",
                "--output-dir",
                str(tmp_path / "out"),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 2
        assert "reject GCP credential files" in result.stderr

    def test_bare_rollback_renders_only_disable_plan_without_spec_tree(self, tmp_path):
        observed = tmp_path / "observed.json"
        _load_api_client().write_observed_snapshot(
            observed, realm="us1", integrations=[_gcp_live()]
        )
        key_a = _write_sa_key(tmp_path / "project-a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "project-b.json", "project-b")
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
                "gcp-id-1",
                "--integration-name",
                "test-gcp",
                "--observed-state-file",
                str(observed),
                "--key-file",
                str(key_a),
                "--key-file",
                str(key_b),
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
                "gcp-id-1",
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
            observed, realm="us1", integrations=[_gcp_live()]
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
                "gcp-id-1",
                "--integration-name",
                "test-gcp",
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
        assert "--accept-delete-integration gcp-id-1" in result.stdout

    def test_apply_flag_order_cannot_change_rollback_behavior(self, tmp_path):
        common = [
            "--realm",
            "us1",
            "--integration-id",
            "gcp-id-1",
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
            observed, realm="us1", integrations=[_gcp_live()]
        )
        output = tmp_path / "rendered"
        key_a = _write_sa_key(tmp_path / "project-a.json", "project-a")
        key_b = _write_sa_key(tmp_path / "project-b.json", "project-b")
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
                "gcp-id-1",
                "--integration-name",
                "test-gcp",
                "--observed-state-file",
                str(observed),
                "--key-file",
                str(key_a),
                "--key-file",
                str(key_b),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "deprecated" in result.stderr
        plan = json.loads((output / "state" / "rollback-plan.json").read_text())
        assert plan["action"] == "disable"


class TestGCPWIFPreflight:
    def setup_method(self):
        self.api = _load_api_client()

    @pytest.fixture(autouse=True)
    def _isolate_account_lock_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            self.api, "_account_lock_root_path", lambda: tmp_path / "account-lock-root"
        )

    def test_wif_config_is_compact_stringified_json(self, tmp_path):
        config = tmp_path / "gcp_wif_config.json"
        config.write_text('{\n  "audience": "example",\n  "type": "external_account"\n}')
        config.chmod(0o600)
        compact = self.api.load_wif_config_file(str(config))
        assert compact == '{"audience":"example","type":"external_account"}'

    def test_wif_config_rejects_loose_permissions(self, tmp_path):
        config = tmp_path / "gcp_wif_config.json"
        config.write_text('{"type":"external_account"}')
        config.chmod(0o644)
        with pytest.raises(self.api.ApiError, match="mode 600"):
            self.api.load_wif_config_file(str(config))

    def test_wif_config_rejects_corrupt_json(self, tmp_path):
        config = tmp_path / "gcp_wif_config.json"
        config.write_text("not-json")
        config.chmod(0o600)
        with pytest.raises(self.api.ApiError, match="valid UTF-8 JSON"):
            self.api.load_wif_config_file(str(config))

    def test_invalid_wif_config_fails_before_live_lookup(self, tmp_path, monkeypatch):
        config = tmp_path / "gcp_wif_config.json"
        config.write_text("not-json")
        config.chmod(0o600)
        payload = {
            "type": "GCP",
            "name": "test-gcp",
            "authMethod": "WORKLOAD_IDENTITY_FEDERATION",
            "projects": {"syncMode": "ALL"},
            "workloadIdentityFederationConfig": (
                "${WORKLOAD_IDENTITY_FEDERATION_CONFIG_FROM_FILE}"
            ),
        }

        def unexpected_lookup(*_args, **_kwargs):
            pytest.fail("live integration lookup ran before WIF preflight")

        monkeypatch.setattr(self.api, "list_gcp_integrations", unexpected_lookup)
        with pytest.raises(self.api.ApiError, match="valid UTF-8 JSON"):
            self.api.upsert(
                "us1",
                "unused-token",
                payload,
                tmp_path / "state",
                wif_config_file=str(config),
            )

    def test_upsert_sends_stringified_wif_contract(self, tmp_path, monkeypatch):
        config = tmp_path / "gcp_wif_config.json"
        config.write_text('{"type":"external_account","audience":"example"}')
        config.chmod(0o600)
        payload = {
            "type": "GCP",
            "name": "test-gcp",
            "authMethod": "WORKLOAD_IDENTITY_FEDERATION",
            "projects": {"syncMode": "ALL"},
            "workloadIdentityFederationConfig": (
                "${WORKLOAD_IDENTITY_FEDERATION_CONFIG_FROM_FILE}"
            ),
        }
        captured = {}
        list_calls = 0

        def confirmed():
            return {**captured, "id": "created-id", "enabled": True}

        def relist(*_args):
            nonlocal list_calls
            list_calls += 1
            return [] if list_calls == 1 else [confirmed()]

        monkeypatch.setattr(
            self.api,
            "list_gcp_integrations",
            relist,
        )
        monkeypatch.setattr(self.api, "get_integration", lambda *_args: confirmed())

        def capture_create(_realm, _token, body):
            captured.update(body)
            return {"id": "created-id"}

        monkeypatch.setattr(self.api, "create_integration", capture_create)
        self.api.upsert(
            "us1",
            "unused-token",
            payload,
            tmp_path / "state",
            wif_config_file=str(config),
        )
        assert captured["authMethod"] == "WORKLOAD_IDENTITY_FEDERATION"
        assert captured["projects"] == {"syncMode": "ALL_REACHABLE"}
        assert isinstance(captured["workloadIdentityFederationConfig"], str)
        assert json.loads(captured["workloadIdentityFederationConfig"])["type"] == "external_account"
