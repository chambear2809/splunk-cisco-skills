from __future__ import annotations

import os
import sys
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "skills" / "splunk-itsi-config" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.common import ValidationError, infer_platform, macro_mentions_indexes  # noqa: E402
from lib.content_packs import (  # noqa: E402
    CONTENT_LIBRARY_APP,
    ITSI_APP,
    PACK_PROFILES,
    ContentPackWorkflow,
    ShellContentLibraryInstaller,
    build_install_payload,
    resolve_catalog_entry,
    validate_profile,
)

HEALTHY_ITSI_APPS = {ITSI_APP, "itsi", "SA-UserAccess", "SA-ITSI-Licensechecker"}


class FakeContentPackClient:
    def __init__(
        self,
        *,
        apps: set[str] | None = None,
        app_versions: dict[str, str] | None = None,
        catalog: list[dict] | None = None,
        previews: dict[tuple[str, str], object] | None = None,
        macros: dict[tuple[str, str], dict] | None = None,
        macro_lists: dict[str, list[dict]] | None = None,
        inputs: dict[str, list[dict]] | None = None,
        confs: dict[tuple[str, str, str], dict] | None = None,
        endpoints: dict[tuple[str, str], list[dict]] | None = None,
        kvstore_status_value: str | None = "ready",
        kvstore_collections: dict[tuple[str, str], dict[str, str]] | None = None,
    ):
        self.apps = set(apps or set())
        self.app_versions = dict(app_versions or {})
        self.catalog = list(catalog or [])
        self.previews = dict(previews or {})
        self.macros = dict(macros or {})
        self.macro_lists = dict(macro_lists or {})
        self.inputs = dict(inputs or {})
        self.confs = dict(confs or {})
        self.endpoints = dict(endpoints or {})
        self.kvstore_status_value = kvstore_status_value
        self.kvstore_collections = dict(kvstore_collections or {})
        self.install_requests: list[tuple[str, str, dict]] = []

    def get_app(self, app_name: str):
        if app_name not in self.apps:
            return None
        return {"name": app_name, "version": self.app_versions.get(app_name, "1.0.0")}

    def app_exists(self, app_name: str) -> bool:
        return app_name in self.apps

    def get_app_version(self, app_name: str) -> str | None:
        app = self.get_app(app_name)
        if not app:
            return None
        return str(app["version"])

    def first_installed_app(self, candidates: list[str]) -> str | None:
        for candidate in candidates:
            if candidate in self.apps:
                return candidate
        return None

    def content_pack_catalog(self) -> list[dict]:
        return list(self.catalog)

    def preview_content_pack(self, pack_id: str, version: str):
        return self.previews[(pack_id, version)]

    def install_content_pack(self, pack_id: str, version: str, payload: dict):
        self.install_requests.append((pack_id, version, payload))
        return {"installed": True, "id": pack_id, "version": version}

    def get_macro(self, app_name: str, macro_name: str):
        return self.macros.get((app_name, macro_name))

    def list_macros(self, app_name: str):
        return list(self.macro_lists.get(app_name, []))

    def list_inputs(self, app_name: str):
        return list(self.inputs.get(app_name, []))

    def get_conf_stanza(self, app_name: str, conf_name: str, stanza_name: str):
        return self.confs.get((app_name, conf_name, stanza_name))

    def list_endpoint_entries(self, app_name: str, endpoint_name: str):
        return list(self.endpoints.get((app_name, endpoint_name), []))

    def kvstore_status(self) -> str | None:
        return self.kvstore_status_value

    def kvstore_collection_health(self, app_name: str, collection_name: str) -> dict[str, str]:
        return dict(self.kvstore_collections.get((app_name, collection_name), {"status": "ok", "message": "accessible"}))


class FakeContentLibraryInstaller:
    def __init__(self, *, should_install: bool = True, message: str = "Installed via fake installer."):
        self.should_install = should_install
        self.message = message
        self.calls: list[dict] = []

    def install(self, spec: dict, client: FakeContentPackClient):
        self.calls.append(spec)
        if self.should_install:
            client.apps.add(CONTENT_LIBRARY_APP)
        return {
            "attempted": True,
            "installed": self.should_install,
            "source": "splunkbase",
            "app_id": "5391",
            "message": self.message,
        }


class FakeItsiInstaller:
    def __init__(self, *, should_install: bool = True, message: str = "Installed ITSI via fake installer."):
        self.should_install = should_install
        self.message = message
        self.calls: list[dict] = []

    def install(self, spec: dict, client: FakeContentPackClient):
        self.calls.append(spec)
        if self.should_install:
            client.apps.update(HEALTHY_ITSI_APPS)
        return {
            "attempted": True,
            "installed": self.should_install,
            "source": "splunkbase",
            "app_id": "1841",
            "message": self.message,
        }


class ContentPackTests(unittest.TestCase):
    def test_infer_platform_uses_credential_file_url_when_spec_is_auto(self) -> None:
        with patch.dict(os.environ, {"SPLUNK_SEARCH_API_URI": "https://example.splunkcloud.com:8089"}, clear=True):
            self.assertEqual(infer_platform({"connection": {"platform": "auto", "base_url": ""}}), "cloud")

    def test_infer_platform_respects_explicit_platform_over_environment_url(self) -> None:
        with patch.dict(os.environ, {"SPLUNK_SEARCH_API_URI": "https://example.splunkcloud.com:8089"}, clear=True):
            self.assertEqual(infer_platform({"connection": {"platform": "enterprise", "base_url": ""}}), "enterprise")

    def test_infer_platform_uses_environment_platform_when_spec_is_auto(self) -> None:
        with patch.dict(os.environ, {"SPLUNK_PLATFORM": "cloud"}, clear=True):
            self.assertEqual(infer_platform({"connection": {"platform": "auto", "base_url": ""}}), "cloud")

    def test_shell_installer_falls_back_to_cli_for_multi_app_bundle_after_rest_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            bundle_path = Path(tempdir) / "splunk-app-for-content-packs_250.spl"
            source_root = Path(tempdir) / "bundle-src"
            (source_root / "DA-ITSI-ContentLibrary").mkdir(parents=True)
            (source_root / "DA-ITSI-CP-vmware-dashboards").mkdir(parents=True)
            (source_root / "DA-ITSI-ContentLibrary" / "default.meta").write_text("", encoding="utf-8")
            (source_root / "DA-ITSI-CP-vmware-dashboards" / "default.meta").write_text("", encoding="utf-8")
            with tarfile.open(bundle_path, "w:gz") as archive:
                archive.add(source_root / "DA-ITSI-ContentLibrary", arcname="DA-ITSI-ContentLibrary")
                archive.add(source_root / "DA-ITSI-CP-vmware-dashboards", arcname="DA-ITSI-CP-vmware-dashboards")

            commands: list[list[str]] = []
            command_envs: list[dict[str, str]] = []

            def runner(command, **kwargs):
                commands.append(command)
                command_envs.append(dict(kwargs.get("env") or {}))
                if command[:2] == ["bash", str(installer_script)]:
                    return subprocess.CompletedProcess(
                        command,
                        1,
                        stdout=(
                            f"[2026-04-23 11:35:00] Existing package found: {bundle_path}\n"
                            "[2026-04-23 11:36:05] ERROR: Invalid app contents: archive contains more than one immediate subdirectory: "
                            " and DA-ITSI-CP-vmware-dashboards\n"
                        ),
                        stderr="",
                    )
                return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

            installer_script = Path(tempdir) / "install_app.sh"
            installer_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            client = SimpleNamespace(config=SimpleNamespace(username="splunk", password="changeme"))
            installer = ShellContentLibraryInstaller(script_path=installer_script, runner=runner)
            spec = {
                "connection": {"base_url": "https://127.0.0.1:8089", "verify_ssl": False},
                "content_library": {"require_present": True, "source": "splunkbase", "app_id": "5391"},
            }

            result = installer.install(spec, client)

            self.assertEqual(result["source"], "local-extract")
            self.assertEqual(commands[0][0], "bash")
            self.assertEqual(commands[1][:2], ["bash", "-lc"])
            self.assertIn("tar -xf", commands[1][2])
            self.assertIn("cp -R", commands[1][2])
            self.assertIn("printf '%s\\n%s\\n'", commands[1][2])
            self.assertIn('"$splunk_bin" restart', commands[1][2])
            self.assertNotIn("-auth", commands[1][2])
            self.assertNotIn("changeme", commands[1][2])
            self.assertNotIn("SPLUNK_PASSWORD", command_envs[1])
            self.assertNotIn("SPLUNK_PASS", command_envs[1])

    def test_shell_installer_extracts_multi_app_bundle_over_ssh_after_rest_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            bundle_path = Path(tempdir) / "splunk-app-for-content-packs_250.spl"
            source_root = Path(tempdir) / "bundle-src"
            (source_root / "DA-ITSI-ContentLibrary").mkdir(parents=True)
            (source_root / "DA-ITSI-CP-vmware-dashboards").mkdir(parents=True)
            (source_root / "DA-ITSI-ContentLibrary" / "default.meta").write_text("", encoding="utf-8")
            (source_root / "DA-ITSI-CP-vmware-dashboards" / "default.meta").write_text("", encoding="utf-8")
            with tarfile.open(bundle_path, "w:gz") as archive:
                archive.add(source_root / "DA-ITSI-ContentLibrary", arcname="DA-ITSI-ContentLibrary")
                archive.add(source_root / "DA-ITSI-CP-vmware-dashboards", arcname="DA-ITSI-CP-vmware-dashboards")

            commands: list[list[str]] = []
            command_envs: list[dict[str, str]] = []

            def runner(command, **kwargs):
                commands.append(command)
                command_envs.append(dict(kwargs.get("env") or {}))
                if command[0] == "bash":
                    return subprocess.CompletedProcess(
                        command,
                        1,
                        stdout=(
                            f"[2026-04-23 11:35:00] Existing package found: {bundle_path}\n"
                            "[2026-04-23 11:36:05] ERROR: Invalid app contents: archive contains more than one immediate subdirectory: "
                            " and DA-ITSI-CP-vmware-dashboards\n"
                        ),
                        stderr="",
                    )
                return subprocess.CompletedProcess(command, 0, stdout="Installed extracted app DA-ITSI-ContentLibrary\n", stderr="")

            installer_script = Path(tempdir) / "install_app.sh"
            installer_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            client = SimpleNamespace(config=SimpleNamespace(username="splunk", password="changeme"))
            installer = ShellContentLibraryInstaller(script_path=installer_script, runner=runner)
            spec = {
                "connection": {"base_url": "https://10.110.253.20:8089", "verify_ssl": False},
                "content_library": {"require_present": True, "source": "splunkbase", "app_id": "5391"},
            }

            previous_env = {key: os.environ.get(key) for key in ("SPLUNK_SSH_HOST", "SPLUNK_SSH_USER", "SPLUNK_SSH_PASS")}
            os.environ["SPLUNK_SSH_HOST"] = "10.110.253.20"
            os.environ["SPLUNK_SSH_USER"] = "splunk"
            os.environ["SPLUNK_SSH_PASS"] = "changeme"
            try:
                result = installer.install(spec, client)
            finally:
                for key, value in previous_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

            self.assertEqual(result["source"], "ssh-extract")
            self.assertEqual(commands[0][0], "bash")
            self.assertEqual(commands[1][:2], ["sshpass", "-f"])
            self.assertEqual(commands[1][3], "scp")
            self.assertEqual(commands[2][:2], ["sshpass", "-f"])
            self.assertEqual(commands[2][3], "scp")
            self.assertEqual(commands[3][:2], ["sshpass", "-f"])
            self.assertEqual(commands[3][3], "ssh")
            self.assertIn("tar -xf", commands[3][-1])
            self.assertIn("cp -R", commands[3][-1])
            self.assertNotIn("install app", commands[3][-1])
            self.assertIn("nohup", commands[3][-1])
            self.assertIn("Triggered Splunk restart in background", commands[3][-1])
            self.assertIn("printf '%s\\n%s\\n'", commands[3][-1])
            self.assertNotIn("-auth", commands[3][-1])
            command_text = "\n".join(" ".join(str(part) for part in command) for command in commands)
            self.assertNotIn("changeme", command_text)
            for command_env in command_envs[1:]:
                self.assertNotIn("SPLUNK_PASSWORD", command_env)
                self.assertNotIn("SPLUNK_PASS", command_env)
                self.assertNotIn("SPLUNK_SSH_PASS", command_env)

    def test_shell_installer_cleans_remote_secrets_when_ssh_extract_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            bundle_path = Path(tempdir) / "splunk-app-for-content-packs_250.spl"
            bundle_path.write_text("placeholder", encoding="utf-8")
            commands: list[list[str]] = []

            def runner(command, **kwargs):
                commands.append(command)
                if command[0] == "bash":
                    return subprocess.CompletedProcess(command, 1, stdout=f"Existing package found: {bundle_path}\n", stderr="")
                if len(command) > 3 and command[0] == "sshpass" and command[1] == "-f" and command[3] == "scp":
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                if (
                    len(command) > 3
                    and command[0] == "sshpass"
                    and command[1] == "-f"
                    and command[3] == "ssh"
                    and str(command[-1]).startswith("rm -f ")
                ):
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                return subprocess.CompletedProcess(command, 255, stdout="", stderr="connection lost")

            installer_script = Path(tempdir) / "install_app.sh"
            installer_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            client = SimpleNamespace(config=SimpleNamespace(username="splunk", password="changeme"))
            installer = ShellContentLibraryInstaller(script_path=installer_script, runner=runner)
            spec = {
                "connection": {"base_url": "https://10.110.253.20:8089", "verify_ssl": False},
                "content_library": {"require_present": True, "source": "splunkbase", "app_id": "5391"},
            }

            previous_env = {key: os.environ.get(key) for key in ("SPLUNK_SSH_HOST", "SPLUNK_SSH_USER", "SPLUNK_SSH_PASS")}
            os.environ["SPLUNK_SSH_HOST"] = "10.110.253.20"
            os.environ["SPLUNK_SSH_USER"] = "splunk"
            os.environ["SPLUNK_SSH_PASS"] = "changeme"
            try:
                with self.assertRaises(ValidationError):
                    installer._cli_install_bundle(bundle_path, spec, client, installer._build_env(spec, client))
            finally:
                for key, value in previous_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

            self.assertEqual(commands[-1][3], "ssh")
            self.assertTrue(str(commands[-1][-1]).startswith("rm -f "))
            self.assertIn(".auth", commands[-1][-1])
            command_text = "\n".join(" ".join(str(part) for part in command) for command in commands)
            self.assertNotIn("changeme", command_text)

    def test_shell_installer_build_env_maps_supported_auth_variables(self) -> None:
        client = SimpleNamespace(config=SimpleNamespace(username="admin", password="changeme", session_key="token-123"))
        installer = ShellContentLibraryInstaller()
        spec = {"connection": {"base_url": "https://example.com:8089", "verify_ssl": False, "session_key_env": "CUSTOM_SK"}}

        env = installer._build_env(spec, client)

        self.assertEqual(env["SPLUNK_SEARCH_API_URI"], "https://example.com:8089")
        self.assertEqual(env["SPLUNK_URI"], "https://example.com:8089")
        self.assertEqual(env["SPLUNK_USERNAME"], "admin")
        self.assertEqual(env["SPLUNK_PASSWORD"], "changeme")
        self.assertEqual(env["SPLUNK_USER"], "admin")
        self.assertEqual(env["SPLUNK_PASS"], "changeme")
        self.assertEqual(env["SPLUNK_SESSION_KEY"], "token-123")
        self.assertEqual(env["SPLUNK_VERIFY_SSL"], "false")

    def test_shell_installer_build_env_inherits_verify_ssl_from_environment(self) -> None:
        client = SimpleNamespace(config=SimpleNamespace(username="admin", password="changeme", session_key=None))
        installer = ShellContentLibraryInstaller()
        spec = {"connection": {"base_url": "https://example.com:8089"}}

        with patch.dict("os.environ", {"SPLUNK_VERIFY_SSL": "false"}, clear=False):
            env = installer._build_env(spec, client)

        self.assertEqual(env["SPLUNK_VERIFY_SSL"], "false")

    def test_resolve_catalog_entry_uses_exact_title_and_latest_version(self) -> None:
        catalog = [
            {"id": "DA-ITSI-CP-cisco-thousandeyes", "title": "Cisco ThousandEyes", "version": "1.0.0"},
            {"id": "DA-ITSI-CP-cisco-thousandeyes", "title": "Cisco ThousandEyes", "version": "1.0.1"},
            {"id": "DA-ITSI-CP-cisco-thousandeyes-lab", "title": "Cisco ThousandEyes Lab", "version": "9.9.9"},
        ]

        entry = resolve_catalog_entry(catalog, "Cisco ThousandEyes")

        self.assertEqual(entry["version"], "1.0.1")
        self.assertEqual(entry["id"], "DA-ITSI-CP-cisco-thousandeyes")

    def test_resolve_catalog_entry_accepts_exact_title_aliases(self) -> None:
        catalog = [
            {"id": "DA-ITSI-CP-aws-dashboards", "title": "AWS Dashboards and Reports", "version": "1.6.1"},
        ]

        entry = resolve_catalog_entry(
            catalog,
            ["Amazon Web Services Dashboards and Reports", "AWS Dashboards and Reports"],
        )

        self.assertEqual(entry["id"], "DA-ITSI-CP-aws-dashboards")
        self.assertEqual(entry["title"], "AWS Dashboards and Reports")

    def test_resolve_catalog_entry_reports_empty_live_catalog_cleanly(self) -> None:
        with self.assertRaises(ValidationError) as error:
            resolve_catalog_entry([], "Splunk AppDynamics")

        self.assertIn("catalog is empty", str(error.exception))
        self.assertIn("DA-ITSI-ContentLibrary", str(error.exception))

    def test_aws_profile_resolves_live_catalog_title_alias(self) -> None:
        client = FakeContentPackClient(
            apps=HEALTHY_ITSI_APPS | {CONTENT_LIBRARY_APP, "Splunk_TA_aws"},
            catalog=[{"id": "DA-ITSI-CP-aws-dashboards", "title": "AWS Dashboards and Reports", "version": "1.6.1", "installed_versions": []}],
            previews={("DA-ITSI-CP-aws-dashboards", "1.6.1"): {"dashboards": [{"id": "aws-overview"}]}},
            macros={
                ("DA-ITSI-CP-aws-dashboards", "aws-account-summary"): {"definition": 'index="summary"'},
                ("DA-ITSI-CP-aws-dashboards", "aws-sourcetype-index-summary"): {"definition": 'index="summary"'},
            },
            inputs={"Splunk_TA_aws": [{"title": "aws_description://prod", "disabled": 0}]},
        )
        spec = {"connection": {"platform": "enterprise"}, "packs": [{"profile": "aws", "summary_indexes": ["summary"]}]}

        with tempfile.TemporaryDirectory() as tempdir:
            workflow = ContentPackWorkflow(client, tempdir)
            result = workflow.run(spec, "preview")

        self.assertEqual(result["runs"][0]["title"], "AWS Dashboards and Reports")
        self.assertEqual(result["runs"][0]["pack_id"], "DA-ITSI-CP-aws-dashboards")

    def test_install_payload_uses_safe_defaults_and_boolean_serialization(self) -> None:
        payload = build_install_payload(
            {
                "resolution": "skip",
                "enabled": False,
                "saved_search_action": "disable",
                "install_all": True,
                "backfill": False,
                "prefix": "CP-",
            }
        )

        self.assertEqual(
            payload,
            {
                "content": {},
                "resolution": "skip",
                "enabled": False,
                "saved_search_action": "disable",
                "install_all": True,
                "backfill": False,
                "prefix": "CP-",
            },
        )

    def test_missing_content_library_guidance_differs_for_enterprise_and_cloud(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            enterprise_client = FakeContentPackClient(apps=HEALTHY_ITSI_APPS)
            enterprise_workflow = ContentPackWorkflow(enterprise_client, tempdir)
            enterprise_spec = {"connection": {"platform": "enterprise"}, "content_library": {"require_present": True}, "packs": []}
            with self.assertRaises(ValidationError) as enterprise_error:
                enterprise_workflow.run(enterprise_spec, "preview")
            self.assertIn("--apply", str(enterprise_error.exception))

            cloud_client = FakeContentPackClient(apps=HEALTHY_ITSI_APPS)
            cloud_workflow = ContentPackWorkflow(cloud_client, tempdir)
            cloud_spec = {"connection": {"platform": "cloud"}, "content_library": {"require_present": True}, "packs": []}
            with self.assertRaises(ValidationError) as cloud_error:
                cloud_workflow.run(cloud_spec, "preview")
            self.assertIn("Cloud App Request", str(cloud_error.exception))

    def test_missing_itsi_guidance_requires_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            workflow = ContentPackWorkflow(FakeContentPackClient(apps={CONTENT_LIBRARY_APP}), tempdir)
            spec = {"connection": {"platform": "enterprise"}, "content_library": {"require_present": True}, "packs": []}
            with self.assertRaises(ValidationError) as error:
                workflow.run(spec, "preview")
        self.assertIn("--apply", str(error.exception))
        self.assertIn("1841", str(error.exception))

    def test_apply_bootstraps_missing_itsi_before_content_library(self) -> None:
        itsi_installer = FakeItsiInstaller()
        content_library_installer = FakeContentLibraryInstaller(message="Installed content library for test.")
        client = FakeContentPackClient(
            apps={"cisco_dc_networking_app_for_splunk"},
            catalog=[{"id": "DA-ITSI-CP-cisco-data-center", "title": "Cisco Data Center", "version": "1.0.0", "installed_versions": []}],
            previews={("DA-ITSI-CP-cisco-data-center", "1.0.0"): {"service": [{"id": "svc-1"}]}},
            inputs={
                "cisco_dc_networking_app_for_splunk": [
                    {"title": "cisco_nexus_dashboard://advisories_prod", "disabled": 0},
                    {"title": "cisco_nexus_dashboard://anomalies_prod", "disabled": 0},
                    {"title": "cisco_nexus_dashboard://fabrics_prod", "disabled": 0},
                    {"title": "cisco_nexus_dashboard://switches_prod", "disabled": 0},
                ]
            },
        )
        spec = {"connection": {"platform": "enterprise"}, "packs": [{"profile": "cisco_data_center"}]}

        with tempfile.TemporaryDirectory() as tempdir:
            workflow = ContentPackWorkflow(
                client,
                tempdir,
                content_library_installer=content_library_installer,
                itsi_installer=itsi_installer,
            )
            result = workflow.run(spec, "apply")

        self.assertEqual(len(itsi_installer.calls), 1)
        self.assertEqual(len(content_library_installer.calls), 1)
        self.assertTrue(result["itsi"]["installed_in_this_run"])
        self.assertTrue(result["content_library"]["installed_in_this_run"])
        self.assertEqual(len(client.install_requests), 1)

    def test_apply_missing_itsi_respects_disabled_bootstrap(self) -> None:
        client = FakeContentPackClient(apps={CONTENT_LIBRARY_APP})
        spec = {
            "connection": {"platform": "enterprise"},
            "itsi": {"require_present": True, "install_if_missing": False},
            "content_library": {"require_present": True},
            "packs": [],
        }

        with tempfile.TemporaryDirectory() as tempdir:
            workflow = ContentPackWorkflow(client, tempdir, itsi_installer=FakeItsiInstaller())
            with self.assertRaises(ValidationError) as error:
                workflow.run(spec, "apply")

        self.assertIn("Automatic bootstrap is disabled", str(error.exception))

    def test_apply_bootstraps_missing_content_library_on_enterprise(self) -> None:
        installer = FakeContentLibraryInstaller(message="Installed content library for test.")
        client = FakeContentPackClient(
            apps=HEALTHY_ITSI_APPS | {"cisco_dc_networking_app_for_splunk"},
            catalog=[{"id": "DA-ITSI-CP-cisco-data-center", "title": "Cisco Data Center", "version": "1.0.0", "installed_versions": []}],
            previews={("DA-ITSI-CP-cisco-data-center", "1.0.0"): {"service": [{"id": "svc-1"}]}},
            inputs={
                "cisco_dc_networking_app_for_splunk": [
                    {"title": "cisco_nexus_dashboard://advisories_prod", "disabled": 0},
                    {"title": "cisco_nexus_dashboard://anomalies_prod", "disabled": 0},
                    {"title": "cisco_nexus_dashboard://fabrics_prod", "disabled": 0},
                    {"title": "cisco_nexus_dashboard://switches_prod", "disabled": 0},
                ]
            },
        )
        spec = {"connection": {"platform": "enterprise"}, "content_library": {"require_present": True}, "packs": [{"profile": "cisco_data_center"}]}

        with tempfile.TemporaryDirectory() as tempdir:
            workflow = ContentPackWorkflow(client, tempdir, content_library_installer=installer)
            result = workflow.run(spec, "apply")

        self.assertEqual(len(installer.calls), 1)
        self.assertTrue(result["content_library"]["installed_in_this_run"])
        self.assertEqual(len(client.install_requests), 1)

    def test_apply_missing_content_library_respects_disabled_bootstrap(self) -> None:
        client = FakeContentPackClient(apps=HEALTHY_ITSI_APPS)
        spec = {
            "connection": {"platform": "enterprise"},
            "content_library": {"require_present": True, "install_if_missing": False},
            "packs": [],
        }

        with tempfile.TemporaryDirectory() as tempdir:
            workflow = ContentPackWorkflow(client, tempdir, content_library_installer=FakeContentLibraryInstaller())
            with self.assertRaises(ValidationError) as error:
                workflow.run(spec, "apply")

        self.assertIn("Automatic bootstrap is disabled", str(error.exception))

    def test_workflow_reports_itsi_health_checks(self) -> None:
        client = FakeContentPackClient(
            apps={ITSI_APP, CONTENT_LIBRARY_APP},
            kvstore_status_value="failed",
            kvstore_collections={
                (ITSI_APP, "itsi_services"): {"status": "ok", "message": "accessible"},
                (ITSI_APP, "itsi_kpi_template"): {"status": "missing", "message": "not found"},
                (ITSI_APP, "itsi_notable_event_group"): {"status": "error", "message": "HTTP 503"},
            },
        )

        with tempfile.TemporaryDirectory() as tempdir:
            result = ContentPackWorkflow(client, tempdir).run({"packs": []}, "preview")

        checks = result["itsi"]["checks"]
        self.assertTrue(any(check["status"] == "error" and "itsi is not installed" in check["message"] for check in checks), checks)
        self.assertTrue(any(check["status"] == "warn" and "KVStore status is failed" in check["message"] for check in checks), checks)
        self.assertTrue(any(check["status"] == "warn" and "itsi_kpi_template" in check["message"] for check in checks), checks)
        self.assertTrue(any(check["status"] == "warn" and "itsi_notable_event_group" in check["message"] for check in checks), checks)

    def test_apply_skips_pack_install_when_itsi_health_checks_fail(self) -> None:
        client = FakeContentPackClient(
            apps={ITSI_APP, CONTENT_LIBRARY_APP, "cisco_dc_networking_app_for_splunk"},
            catalog=[{"id": "DA-ITSI-CP-cisco-data-center", "title": "Cisco Data Center", "version": "1.0.0", "installed_versions": []}],
            previews={("DA-ITSI-CP-cisco-data-center", "1.0.0"): {"service": [{"id": "svc-1"}]}},
            inputs={
                "cisco_dc_networking_app_for_splunk": [
                    {"title": "cisco_nexus_dashboard://advisories_prod", "disabled": 0},
                    {"title": "cisco_nexus_dashboard://anomalies_prod", "disabled": 0},
                    {"title": "cisco_nexus_dashboard://fabrics_prod", "disabled": 0},
                    {"title": "cisco_nexus_dashboard://switches_prod", "disabled": 0},
                ]
            },
        )
        spec = {"content_library": {"require_present": True}, "packs": [{"profile": "cisco_data_center"}]}

        with tempfile.TemporaryDirectory() as tempdir:
            result = ContentPackWorkflow(client, tempdir).run(spec, "apply")

        self.assertEqual(client.install_requests, [])
        self.assertTrue(any(check["status"] == "error" for check in result["itsi"]["checks"]), result["itsi"]["checks"])

    def test_preview_resolves_live_pack_app_name_from_bundle_candidates(self) -> None:
        client = FakeContentPackClient(
            apps=HEALTHY_ITSI_APPS | {CONTENT_LIBRARY_APP, "Splunk_TA_nix", "DA-ITSI-CP-nix"},
            catalog=[{"id": "DA-ITSI-CP-linux", "title": "Monitoring Unix and Linux", "version": "1.2.0", "installed_versions": []}],
            previews={("DA-ITSI-CP-linux", "1.2.0"): {"service": [{"id": "svc-1"}]}},
            macros={("DA-ITSI-CP-nix", "itsi-cp-nix-indexes"): {"definition": 'index="os"'}},
            inputs={"Splunk_TA_nix": [{"title": "script://./bin/hardware.sh", "disabled": 0, "index": "os"}]},
        )
        spec = {"content_library": {"require_present": True}, "packs": [{"profile": "linux"}]}

        with tempfile.TemporaryDirectory() as tempdir:
            result = ContentPackWorkflow(client, tempdir).run(spec, "preview")

        findings = result["runs"][0]["findings"]
        self.assertFalse(any(finding["status"] == "error" for finding in findings), findings)
        self.assertFalse(any("cannot be validated until content-pack app" in finding["message"] for finding in findings), findings)

    def test_validate_warns_when_pack_companion_app_is_missing(self) -> None:
        client = FakeContentPackClient(
            apps=HEALTHY_ITSI_APPS | {CONTENT_LIBRARY_APP, "Splunk_TA_windows", "DA-ITSI-CP-windows"},
            catalog=[{"id": "DA-ITSI-CP-windows", "title": "Monitoring Microsoft Windows", "version": "1.0.0", "installed_versions": ["1.0.0"]}],
            macros={
                ("DA-ITSI-CP-windows", "itsi-cp-windows-indexes"): {"definition": "index=windows OR index=perfmon"},
                ("DA-ITSI-CP-windows", "itsi-cp-windows-metrics-indexes"): {"definition": "index=itsi_im_metrics"},
            },
            inputs={
                "Splunk_TA_windows": [
                    {"title": "WinHostMon://Processor", "disabled": 0},
                    {"title": "WinHostMon://OperatingSystem", "disabled": 0},
                    {"title": "WinHostMon://Disk", "disabled": 0},
                    {"title": "perfmon://CPU", "disabled": 0},
                    {"title": "perfmon://LogicalDisk", "disabled": 0},
                ]
            },
        )
        spec = {"content_library": {"require_present": True}, "packs": [{"profile": "windows"}]}

        with tempfile.TemporaryDirectory() as tempdir:
            result = ContentPackWorkflow(client, tempdir).run(spec, "validate")

        findings = result["runs"][0]["findings"]
        self.assertTrue(any(finding["status"] == "pass" and "Primary content-pack app is installed as DA-ITSI-CP-windows" in finding["message"] for finding in findings), findings)
        self.assertTrue(any(finding["status"] == "warn" and "Windows dashboards companion app is not installed" in finding["message"] for finding in findings), findings)

    def test_supported_profiles_pass_minimal_prerequisite_checks(self) -> None:
        cases = {
            "aws": (
                "DA-ITSI-CP-aws",
                FakeContentPackClient(
                    apps={"Splunk_TA_aws"},
                    macros={
                        ("DA-ITSI-CP-aws", "aws-account-summary"): {"definition": 'index="summary"'},
                        ("DA-ITSI-CP-aws", "aws-sourcetype-index-summary"): {"definition": 'index="summary"'},
                    },
                    inputs={"Splunk_TA_aws": [{"title": "aws_description://prod", "disabled": 0}]},
                ),
                {"summary_indexes": ["summary"]},
            ),
            "cisco_data_center": (
                "DA-ITSI-CP-cisco-data-center",
                FakeContentPackClient(
                    apps={"cisco_dc_networking_app_for_splunk"},
                    inputs={
                        "cisco_dc_networking_app_for_splunk": [
                            {"title": "cisco_nexus_dashboard://advisories_prod", "disabled": 0},
                            {"title": "cisco_nexus_dashboard://anomalies_prod", "disabled": 0},
                            {"title": "cisco_nexus_dashboard://fabrics_prod", "disabled": 0},
                            {"title": "cisco_nexus_dashboard://switches_prod", "disabled": 0},
                        ]
                    },
                ),
                {},
            ),
            "cisco_enterprise_networks": (
                "DA-ITSI-CP-enterprise-networking",
                FakeContentPackClient(
                    apps={"TA_cisco_catalyst", "Splunk_TA_cisco_meraki"},
                    macros={
                        ("DA-ITSI-CP-enterprise-networking", "itsi_cp_catalyst_center_index"): {"definition": 'index="catalyst"'},
                        ("Splunk_TA_cisco_meraki", "meraki_index"): {"definition": 'index="meraki"'},
                    },
                    inputs={
                        "TA_cisco_catalyst": [
                            {"title": "cisco_catalyst_dnac_issue://prod", "disabled": 0, "index": "catalyst"},
                            {"title": "cisco_catalyst_dnac_networkhealth://prod", "disabled": 0, "index": "catalyst"},
                            {"title": "cisco_catalyst_dnac_securityadvisory://prod", "disabled": 0, "index": "catalyst"},
                        ],
                        "Splunk_TA_cisco_meraki": [
                            {"title": "cisco_meraki_assurance_alerts://prod", "disabled": 0, "index": "meraki"},
                            {"title": "cisco_meraki_devices://prod", "disabled": 0, "index": "meraki"},
                            {"title": "cisco_meraki_organizations://prod", "disabled": 0, "index": "meraki"},
                        ],
                    },
                ),
                {},
            ),
            "cisco_thousandeyes": (
                "DA-ITSI-CP-cisco-thousandeyes",
                FakeContentPackClient(
                    apps={"ta_cisco_thousandeyes"},
                    macro_lists={
                        "DA-ITSI-CP-cisco-thousandeyes": [{"name": "itsi_cp_thousandeyes_index", "definition": 'index="thousandeyes"'}]
                    },
                    inputs={
                        "ta_cisco_thousandeyes": [
                            {"title": "ta_cisco_thousandeyes_event://prod", "disabled": 0, "index": "thousandeyes"}
                        ]
                    },
                ),
                {},
            ),
            "linux": (
                "DA-ITSI-CP-linux",
                FakeContentPackClient(
                    apps={"Splunk_TA_nix"},
                    macros={("DA-ITSI-CP-linux", "itsi-cp-nix-indexes"): {"definition": 'index="os"'}},
                    inputs={"Splunk_TA_nix": [{"title": "script://./bin/hardware.sh", "disabled": 0}]},
                ),
                {"event_indexes": ["os"]},
            ),
            "splunk_appdynamics": (
                "DA-ITSI-CP-APPDYNAMICS",
                FakeContentPackClient(
                    apps={"Splunk_TA_AppDynamics"},
                    macros={("DA-ITSI-CP-APPDYNAMICS", "itsi_cp_appdynamics_index"): {"definition": 'index="appdynamics"'}},
                    inputs={"Splunk_TA_AppDynamics": [{"title": "appdynamics_status://prod", "disabled": 0, "index": "appdynamics"}]},
                    confs={
                        ("Splunk_TA_AppDynamics", "splunk_ta_appdynamics_settings", "additional_parameters"): {"index": "appdynamics"}
                    },
                ),
                {},
            ),
            "splunk_observability_cloud": (
                "DA-ITSI-CP-splunk-observability",
                FakeContentPackClient(
                    apps={"splunk_ta_sim"},
                    macros={
                        ("DA-ITSI-CP-splunk-observability", "itsi-cp-observability-indexes"): {
                            "definition": "index=sim_metrics OR index=sim_metrics_extra"
                        }
                    },
                    inputs={"splunk_ta_sim": [{"title": "OS_Hosts", "disabled": 0}]},
                ),
                {"metrics_indexes": ["sim_metrics", "sim_metrics_extra"], "custom_subdomain": "acme-observability"},
            ),
            "vmware": (
                "DA-ITSI-CP-vmware-monitoring",
                FakeContentPackClient(
                    apps={"Splunk_TA_vmware_inframon"},
                    macros={
                        ("DA-ITSI-CP-vmware-monitoring", "cp_vmware_perf_metrics_index"): {
                            "definition": "index=vmware-perf-metrics"
                        }
                    },
                ),
                {"metrics_indexes": ["vmware-perf-metrics"]},
            ),
            "windows": (
                "DA-ITSI-CP-windows",
                FakeContentPackClient(
                    apps={"Splunk_TA_windows"},
                    macros={
                        ("DA-ITSI-CP-windows", "itsi-cp-windows-indexes"): {"definition": "index=windows OR index=perfmon"},
                        ("DA-ITSI-CP-windows", "itsi-cp-windows-metrics-indexes"): {"definition": "index=itsi_im_metrics"},
                    },
                    inputs={
                        "Splunk_TA_windows": [
                            {"title": "WinHostMon://Processor", "disabled": 0},
                            {"title": "WinHostMon://OperatingSystem", "disabled": 0},
                            {"title": "WinHostMon://Disk", "disabled": 0},
                            {"title": "perfmon://CPU", "disabled": 0},
                            {"title": "perfmon://LogicalDisk", "disabled": 0},
                        ]
                    },
                ),
                {"event_indexes": ["windows", "perfmon"], "metrics_indexes": ["itsi_im_metrics"]},
            ),
        }

        for profile, (pack_app, client, overrides) in cases.items():
            with self.subTest(profile=profile):
                spec = {"profile": profile, **overrides}
                findings = validate_profile(client, spec, PACK_PROFILES[profile], pack_app)
                self.assertFalse(any(finding["status"] == "error" for finding in findings), findings)

    def test_appdynamics_required_input_detects_live_input_type_with_custom_name(self) -> None:
        client = FakeContentPackClient(
            apps={"Splunk_TA_AppDynamics"},
            macros={("DA-ITSI-CP-APPDYNAMICS", "itsi_cp_appdynamics_index"): {"definition": 'index="appdynamics"'}},
            inputs={
                "Splunk_TA_AppDynamics": [
                    {"name": "fsotme_status", "eai:type": "appdynamics_status", "disabled": 0, "index": "appdynamics"}
                ]
            },
            confs={("Splunk_TA_AppDynamics", "splunk_ta_appdynamics_settings", "additional_parameters"): {"index": "appdynamics"}},
        )

        findings = validate_profile(
            client,
            {"profile": "splunk_appdynamics"},
            PACK_PROFILES["splunk_appdynamics"],
            "DA-ITSI-CP-APPDYNAMICS",
        )

        self.assertFalse(any(finding["status"] == "error" and finding["check"] == "input" for finding in findings), findings)

    def test_cisco_enterprise_required_inputs_match_live_modular_input_types(self) -> None:
        client = FakeContentPackClient(
            apps={"TA_cisco_catalyst", "Splunk_TA_cisco_meraki"},
            macros={
                ("DA-ITSI-CP-enterprise-networking", "itsi_cp_catalyst_center_index"): {"definition": 'index="catalyst"'},
                ("Splunk_TA_cisco_meraki", "meraki_index"): {"definition": 'index="meraki"'},
            },
            inputs={
                "TA_cisco_catalyst": [
                    {"name": "cvf_issue", "eai:type": "cisco_catalyst_dnac_issue", "disabled": 0, "index": "catalyst"},
                    {"name": "cvf_health", "eai:type": "cisco_catalyst_dnac_networkhealth", "disabled": 0, "index": "catalyst"},
                    {"name": "cvf_adv", "eai:type": "cisco_catalyst_dnac_securityadvisory", "disabled": 0, "index": "catalyst"},
                ],
                "Splunk_TA_cisco_meraki": [
                    {"name": "cvf_alerts", "eai:type": "cisco_meraki_assurance_alerts", "disabled": 0, "index": "meraki"},
                    {"name": "cvf_devices", "eai:type": "cisco_meraki_devices", "disabled": 0, "index": "meraki"},
                    {"name": "cvf_orgs", "eai:type": "cisco_meraki_organizations", "disabled": 0, "index": "meraki"},
                ],
            },
        )

        findings = validate_profile(
            client,
            {"profile": "cisco_enterprise_networks"},
            PACK_PROFILES["cisco_enterprise_networks"],
            "DA-ITSI-CP-enterprise-networking",
        )

        self.assertFalse(any(finding["status"] == "error" and finding["check"] == "input" for finding in findings), findings)

    def test_cisco_data_center_reports_missing_nexus_dashboard_account(self) -> None:
        client = FakeContentPackClient(
            apps={"cisco_dc_networking_app_for_splunk"},
            inputs={
                "cisco_dc_networking_app_for_splunk": [
                    {"name": "authentication", "eai:type": "cisco_nexus_aci", "disabled": 0, "index": "cisco_aci"}
                ]
            },
        )

        findings = validate_profile(
            client,
            {"profile": "cisco_data_center"},
            PACK_PROFILES["cisco_data_center"],
            "DA-ITSI-CP-cisco-data-center",
        )

        self.assertTrue(
            any(
                finding["status"] == "error"
                and finding["check"] == "account"
                and "Nexus Dashboard account is not configured" in finding["message"]
                for finding in findings
            ),
            findings,
        )

    def test_cisco_enterprise_networks_reports_missing_catalyst_center_account(self) -> None:
        client = FakeContentPackClient(
            apps={"TA_cisco_catalyst", "Splunk_TA_cisco_meraki"},
            macros={
                ("DA-ITSI-CP-enterprise-networking", "itsi_cp_catalyst_center_index"): {"definition": 'index="catalyst"'},
                ("Splunk_TA_cisco_meraki", "meraki_index"): {"definition": 'index="meraki"'},
            },
            inputs={
                "Splunk_TA_cisco_meraki": [
                    {"name": "cvf_alerts", "eai:type": "cisco_meraki_assurance_alerts", "disabled": 0, "index": "meraki"},
                    {"name": "cvf_devices", "eai:type": "cisco_meraki_devices", "disabled": 0, "index": "meraki"},
                    {"name": "cvf_orgs", "eai:type": "cisco_meraki_organizations", "disabled": 0, "index": "meraki"},
                ]
            },
        )

        findings = validate_profile(
            client,
            {"profile": "cisco_enterprise_networks"},
            PACK_PROFILES["cisco_enterprise_networks"],
            "DA-ITSI-CP-enterprise-networking",
        )

        self.assertTrue(
            any(
                finding["status"] == "error"
                and finding["check"] == "account"
                and "Catalyst Center account is not configured" in finding["message"]
                for finding in findings
            ),
            findings,
        )
        self.assertTrue(
            any(
                finding["status"] == "warn"
                and "no enabled source inputs were discovered in app TA_cisco_catalyst" in finding["message"]
                for finding in findings
            ),
            findings,
        )

    def test_windows_local_input_guardrail_accepts_live_input_types_with_custom_names(self) -> None:
        client = FakeContentPackClient(
            apps={"Splunk_TA_windows"},
            macros={
                ("DA-ITSI-CP-windows", "itsi-cp-windows-indexes"): {"definition": "index=windows OR index=perfmon"},
                ("DA-ITSI-CP-windows", "itsi-cp-windows-metrics-indexes"): {"definition": "index=itsi_im_metrics"},
            },
            inputs={
                "Splunk_TA_windows": [
                    {"name": "hostmon_proc", "eai:type": "WinHostMon", "eai:location": "/data/inputs/WinHostMon/Processor", "disabled": 0},
                    {"name": "hostmon_os", "eai:type": "WinHostMon", "eai:location": "/data/inputs/WinHostMon/OperatingSystem", "disabled": 0},
                    {"name": "hostmon_disk", "eai:type": "WinHostMon", "eai:location": "/data/inputs/WinHostMon/Disk", "disabled": 0},
                    {"name": "perf_cpu", "eai:type": "perfmon", "eai:location": "/data/inputs/perfmon/CPU", "disabled": 0},
                    {"name": "perf_disk", "eai:type": "perfmon", "eai:location": "/data/inputs/perfmon/LogicalDisk", "disabled": 0},
                ]
            },
        )

        findings = validate_profile(
            client,
            {"profile": "windows", "event_indexes": ["windows", "perfmon"], "metrics_indexes": ["itsi_im_metrics"]},
            PACK_PROFILES["windows"],
            "DA-ITSI-CP-windows",
        )

        self.assertFalse(any(finding["status"] == "error" and finding["check"] == "input" for finding in findings), findings)

    def test_validate_mode_does_not_call_preview_endpoint(self) -> None:
        class NoPreviewClient(FakeContentPackClient):
            def preview_content_pack(self, pack_id: str, version: str):
                raise AssertionError("validate should not call preview")

        client = NoPreviewClient(
            apps=HEALTHY_ITSI_APPS | {CONTENT_LIBRARY_APP, "cisco_dc_networking_app_for_splunk"},
            catalog=[{"id": "DA-ITSI-CP-cisco-data-center", "title": "Cisco Data Center", "version": "1.0.0", "installed_versions": ["1.0.0"]}],
            inputs={
                "cisco_dc_networking_app_for_splunk": [
                    {"title": "cisco_nexus_dashboard://advisories_prod", "disabled": 0},
                    {"title": "cisco_nexus_dashboard://anomalies_prod", "disabled": 0},
                    {"title": "cisco_nexus_dashboard://fabrics_prod", "disabled": 0},
                    {"title": "cisco_nexus_dashboard://switches_prod", "disabled": 0},
                ]
            },
        )
        spec = {"content_library": {"require_present": True}, "packs": [{"profile": "cisco_data_center"}]}

        with tempfile.TemporaryDirectory() as tempdir:
            result = ContentPackWorkflow(client, tempdir).run(spec, "validate")

        self.assertIsNone(result["runs"][0]["preview_summary"])
        self.assertTrue(any(finding["check"] == "install" and finding["status"] == "pass" for finding in result["runs"][0]["findings"]))

    def test_enterprise_networks_reads_meraki_macro_from_meraki_add_on(self) -> None:
        client = FakeContentPackClient(
            apps={"TA_cisco_catalyst", "Splunk_TA_cisco_meraki"},
            macros={
                ("DA-ITSI-CP-enterprise-networking", "itsi_cp_catalyst_center_index"): {"definition": 'index="catalyst"'},
                ("Splunk_TA_cisco_meraki", "meraki_index"): {"definition": 'index="meraki"'},
            },
            inputs={
                "TA_cisco_catalyst": [
                    {"title": "cisco_catalyst_dnac_issue://prod", "disabled": 0, "index": "catalyst"},
                    {"title": "cisco_catalyst_dnac_networkhealth://prod", "disabled": 0, "index": "catalyst"},
                    {"title": "cisco_catalyst_dnac_securityadvisory://prod", "disabled": 0, "index": "catalyst"},
                ],
                "Splunk_TA_cisco_meraki": [
                    {"title": "cisco_meraki_assurance_alerts://prod", "disabled": 0, "index": "meraki"},
                    {"title": "cisco_meraki_devices://prod", "disabled": 0, "index": "meraki"},
                    {"title": "cisco_meraki_organizations://prod", "disabled": 0, "index": "meraki"},
                ],
            },
        )

        findings = validate_profile(
            client,
            {"profile": "cisco_enterprise_networks"},
            PACK_PROFILES["cisco_enterprise_networks"],
            "DA-ITSI-CP-enterprise-networking",
        )

        self.assertFalse(any(finding["status"] == "error" for finding in findings), findings)

    def test_appdynamics_macro_drift_detection(self) -> None:
        client = FakeContentPackClient(
            apps={"Splunk_TA_AppDynamics"},
            macros={("DA-ITSI-CP-APPDYNAMICS", "itsi_cp_appdynamics_index"): {"definition": 'index="wrong_index"'}},
            inputs={"Splunk_TA_AppDynamics": [{"title": "appdynamics_status://prod", "disabled": 0, "index": "appdynamics"}]},
            confs={("Splunk_TA_AppDynamics", "splunk_ta_appdynamics_settings", "additional_parameters"): {"index": "appdynamics"}},
        )

        findings = validate_profile(client, {"profile": "splunk_appdynamics"}, PACK_PROFILES["splunk_appdynamics"], "DA-ITSI-CP-APPDYNAMICS")

        self.assertTrue(any(finding["status"] == "error" and "wrong_index" in finding["message"] for finding in findings))

    def test_vmware_requires_metrics_add_on(self) -> None:
        client = FakeContentPackClient(
            macros={
                ("DA-ITSI-CP-vmware-monitoring", "cp_vmware_perf_metrics_index"): {
                    "definition": "index=vmware-perf-metrics"
                }
            }
        )

        findings = validate_profile(client, {"profile": "vmware"}, PACK_PROFILES["vmware"], "DA-ITSI-CP-vmware-monitoring")

        self.assertTrue(any(finding["status"] == "error" and "Splunk Add-on for VMware Metrics" in finding["message"] for finding in findings))

    def test_linux_custom_indexes_require_spec_override(self) -> None:
        client = FakeContentPackClient(
            apps={"Splunk_TA_nix"},
            macros={("DA-ITSI-CP-linux", "itsi-cp-nix-indexes"): {"definition": 'index="os"'}},
            inputs={"Splunk_TA_nix": [{"title": "script://./bin/hardware.sh", "disabled": 0, "index": "custom_os"}]},
        )

        findings = validate_profile(client, {"profile": "linux"}, PACK_PROFILES["linux"], "DA-ITSI-CP-linux")

        self.assertTrue(any(finding["status"] == "error" and "event_indexes" in finding["message"] for finding in findings))

    def test_windows_local_input_guardrail_reports_missing_required_stanzas(self) -> None:
        client = FakeContentPackClient(
            apps={"Splunk_TA_windows"},
            macros={
                ("DA-ITSI-CP-windows", "itsi-cp-windows-indexes"): {"definition": "index=windows OR index=perfmon"},
                ("DA-ITSI-CP-windows", "itsi-cp-windows-metrics-indexes"): {"definition": "index=itsi_im_metrics"},
            },
            inputs={
                "Splunk_TA_windows": [
                    {"title": "WinHostMon://Processor", "disabled": 0},
                    {"title": "perfmon://CPU", "disabled": 0},
                ]
            },
        )

        findings = validate_profile(
            client,
            {"profile": "windows", "event_indexes": ["windows", "perfmon"], "metrics_indexes": ["itsi_im_metrics"]},
            PACK_PROFILES["windows"],
            "DA-ITSI-CP-windows",
        )

        self.assertTrue(any(finding["status"] == "error" and "required stanza families" in finding["message"] for finding in findings))

    def test_windows_custom_indexes_require_spec_override(self) -> None:
        client = FakeContentPackClient(
            apps={"Splunk_TA_windows"},
            macros={
                ("DA-ITSI-CP-windows", "itsi-cp-windows-indexes"): {"definition": "index=windows OR index=perfmon"},
                ("DA-ITSI-CP-windows", "itsi-cp-windows-metrics-indexes"): {"definition": "index=itsi_im_metrics"},
            },
            inputs={
                "Splunk_TA_windows": [
                    {"title": "WinHostMon://Processor", "disabled": 0, "index": "custom_windows"},
                    {"title": "WinHostMon://OperatingSystem", "disabled": 0, "index": "custom_windows"},
                    {"title": "WinHostMon://Disk", "disabled": 0, "index": "custom_windows"},
                    {"title": "perfmon://CPU", "disabled": 0, "index": "custom_perfmon"},
                    {"title": "perfmon://LogicalDisk", "disabled": 0, "index": "custom_perfmon"},
                ]
            },
        )

        findings = validate_profile(client, {"profile": "windows"}, PACK_PROFILES["windows"], "DA-ITSI-CP-windows")

        self.assertTrue(any(finding["status"] == "error" and "event_indexes, metrics_indexes" in finding["message"] for finding in findings))

    def test_macro_mentions_indexes_requires_exact_index_tokens(self) -> None:
        self.assertFalse(macro_mentions_indexes('index="prod_appdynamics_clone"', ["appdynamics"]))
        self.assertTrue(macro_mentions_indexes('index="appdynamics" OR index in ("appdynamics_secondary", "appdynamics")', ["appdynamics"]))

    def test_thousandeyes_validation_rejects_metrics_only_indexes(self) -> None:
        client = FakeContentPackClient(
            apps={"ta_cisco_thousandeyes"},
            macro_lists={
                "DA-ITSI-CP-cisco-thousandeyes": [{"name": "itsi_cp_thousandeyes_index", "definition": 'index="thousandeyes_metrics"'}]
            },
            inputs={
                "ta_cisco_thousandeyes": [
                    {"title": "ta_cisco_thousandeyes_event://prod", "disabled": 0, "index": "thousandeyes_metrics"}
                ]
            },
        )

        findings = validate_profile(client, {"profile": "cisco_thousandeyes"}, PACK_PROFILES["cisco_thousandeyes"], "DA-ITSI-CP-cisco-thousandeyes")

        self.assertTrue(any(finding["status"] == "error" and "events indexes" in finding["message"] for finding in findings))

    def test_observability_validation_checks_metrics_indexes_and_custom_subdomain(self) -> None:
        client = FakeContentPackClient(
            apps={"splunk_ta_sim"},
            macros={
                ("DA-ITSI-CP-splunk-observability", "itsi-cp-observability-indexes"): {
                    "definition": "index=sim_metrics OR index=sim_metrics_custom"
                }
            },
            inputs={"splunk_ta_sim": [{"title": "APM_Services", "disabled": 0}]},
        )
        findings = validate_profile(
            client,
            {"profile": "splunk_observability_cloud", "metrics_indexes": ["sim_metrics", "sim_metrics_custom"], "custom_subdomain": "acme-o11y"},
            PACK_PROFILES["splunk_observability_cloud"],
            "DA-ITSI-CP-splunk-observability",
        )

        self.assertFalse(any(finding["status"] == "error" for finding in findings), findings)
        self.assertTrue(any("custom subdomain" in finding["message"].lower() for finding in findings))

    def test_preview_warns_when_pack_owned_macro_is_unavailable_before_install(self) -> None:
        client = FakeContentPackClient(
            apps=HEALTHY_ITSI_APPS | {CONTENT_LIBRARY_APP, "Splunk_TA_nix"},
            catalog=[{"id": "DA-ITSI-CP-linux", "title": "Monitoring Unix and Linux", "version": "1.2.0", "installed_versions": []}],
            previews={("DA-ITSI-CP-linux", "1.2.0"): {"service": [{"id": "svc-1"}]}},
            inputs={"Splunk_TA_nix": [{"title": "script://./bin/hardware.sh", "disabled": 0, "index": "os"}]},
        )
        spec = {
            "content_library": {"require_present": True},
            "packs": [{"profile": "linux"}],
        }

        with tempfile.TemporaryDirectory() as tempdir:
            result = ContentPackWorkflow(client, tempdir).run(spec, "preview")

        findings = result["runs"][0]["findings"]
        self.assertFalse(any(finding["status"] == "error" for finding in findings), findings)
        self.assertTrue(
            any(
                finding["status"] == "warn"
                and "cannot be validated until content-pack app DA-ITSI-CP-nix is installed" in finding["message"]
                for finding in findings
            ),
            findings,
        )
        self.assertEqual(result["runs"][0]["preview_summary"]["object_counts"]["service"], 1)

    def test_preview_and_apply_generate_report_and_install_request(self) -> None:
        client = FakeContentPackClient(
            apps=HEALTHY_ITSI_APPS | {CONTENT_LIBRARY_APP, "cisco_dc_networking_app_for_splunk"},
            catalog=[{"id": "DA-ITSI-CP-cisco-data-center", "title": "Cisco Data Center", "version": "1.0.0", "installed_versions": []}],
            previews={
                ("DA-ITSI-CP-cisco-data-center", "1.0.0"): {
                    "service": [{"id": "svc-1"}, {"id": "svc-2"}],
                    "saved_searches": {"has_saved_searches": True, "has_consistent_status": True},
                }
            },
            inputs={
                "cisco_dc_networking_app_for_splunk": [
                    {"title": "cisco_nexus_dashboard://advisories_prod", "disabled": 0},
                    {"title": "cisco_nexus_dashboard://anomalies_prod", "disabled": 0},
                    {"title": "cisco_nexus_dashboard://fabrics_prod", "disabled": 0},
                    {"title": "cisco_nexus_dashboard://switches_prod", "disabled": 0},
                ]
            },
        )
        spec = {
            "content_library": {"require_present": True},
            "packs": [{"profile": "cisco_data_center"}],
        }

        with tempfile.TemporaryDirectory() as tempdir:
            preview_result = ContentPackWorkflow(client, tempdir).run(spec, "preview")
            self.assertTrue(Path(preview_result["report_path"]).exists())
            self.assertEqual(preview_result["runs"][0]["preview_summary"]["object_counts"]["service"], 2)

            apply_result = ContentPackWorkflow(client, tempdir).run(spec, "apply")
            self.assertEqual(len(client.install_requests), 1)
            self.assertEqual(client.install_requests[0][2]["resolution"], "skip")
            self.assertTrue(Path(apply_result["report_path"]).exists())

    def test_apply_surfaces_install_journal_failures(self) -> None:
        class PartialFailureClient(FakeContentPackClient):
            def install_content_pack(self, pack_id: str, version: str, payload: dict):
                self.install_requests.append((pack_id, version, payload))
                return {
                    "success": [],
                    "failure": [{"entity_types": [{"id": "failed-entity"}]}],
                    "saved_searches": {"success": [], "failure": ["failed-search"]},
                }

        client = PartialFailureClient(
            apps=HEALTHY_ITSI_APPS | {CONTENT_LIBRARY_APP, "Splunk_TA_AppDynamics"},
            catalog=[{"id": "DA-ITSI-CP-appdynamics", "title": "Splunk AppDynamics", "version": "1.0.1", "installed_versions": []}],
            previews={("DA-ITSI-CP-appdynamics", "1.0.1"): {"entity_types": [{"id": "entity-1"}]}},
            macros={("DA-ITSI-CP-appdynamics", "itsi_cp_appdynamics_index"): {"definition": 'index="appdynamics"'}},
            inputs={"Splunk_TA_AppDynamics": [{"name": "fsotme_status", "eai:type": "appdynamics_status", "disabled": 0, "index": "appdynamics"}]},
            confs={("Splunk_TA_AppDynamics", "splunk_ta_appdynamics_settings", "additional_parameters"): {"index": "appdynamics"}},
        )
        spec = {
            "content_library": {"require_present": True},
            "packs": [{"profile": "splunk_appdynamics"}],
        }

        with tempfile.TemporaryDirectory() as tempdir:
            result = ContentPackWorkflow(client, tempdir).run(spec, "apply")

        findings = result["runs"][0]["findings"]
        self.assertTrue(any(finding["status"] == "error" and "Install reported failures" in finding["message"] for finding in findings), findings)
        self.assertTrue(any(finding["status"] == "error" and "Saved search updates reported failures" in finding["message"] for finding in findings), findings)

    def test_report_contains_guided_handoff_steps_for_cisco_profiles(self) -> None:
        client = FakeContentPackClient(
            apps=HEALTHY_ITSI_APPS | {CONTENT_LIBRARY_APP, "cisco_dc_networking_app_for_splunk", "TA_cisco_catalyst", "Splunk_TA_cisco_meraki"},
            catalog=[
                {"id": "DA-ITSI-CP-cisco-data-center", "title": "Cisco Data Center", "version": "1.0.0", "installed_versions": []},
                {"id": "DA-ITSI-CP-enterprise-networking", "title": "Cisco Enterprise Networks", "version": "1.1.0", "installed_versions": []},
            ],
            previews={
                ("DA-ITSI-CP-cisco-data-center", "1.0.0"): {"service": [{"id": "svc-1"}]},
                ("DA-ITSI-CP-enterprise-networking", "1.1.0"): {"service": [{"id": "svc-2"}]},
            },
            macros={
                ("DA-ITSI-CP-enterprise-networking", "itsi_cp_catalyst_center_index"): {"definition": 'index="catalyst"'},
                ("Splunk_TA_cisco_meraki", "meraki_index"): {"definition": 'index="meraki"'},
            },
            inputs={
                "cisco_dc_networking_app_for_splunk": [
                    {"title": "cisco_nexus_dashboard://advisories_prod", "disabled": 0},
                    {"title": "cisco_nexus_dashboard://anomalies_prod", "disabled": 0},
                    {"title": "cisco_nexus_dashboard://fabrics_prod", "disabled": 0},
                    {"title": "cisco_nexus_dashboard://switches_prod", "disabled": 0},
                ],
                "TA_cisco_catalyst": [
                    {"title": "cisco_catalyst_dnac_issue://prod", "disabled": 0, "index": "catalyst"},
                    {"title": "cisco_catalyst_dnac_networkhealth://prod", "disabled": 0, "index": "catalyst"},
                    {"title": "cisco_catalyst_dnac_securityadvisory://prod", "disabled": 0, "index": "catalyst"},
                ],
                "Splunk_TA_cisco_meraki": [
                    {"title": "cisco_meraki_assurance_alerts://prod", "disabled": 0, "index": "meraki"},
                    {"title": "cisco_meraki_devices://prod", "disabled": 0, "index": "meraki"},
                    {"title": "cisco_meraki_organizations://prod", "disabled": 0, "index": "meraki"},
                ],
            },
        )
        spec = {
            "content_library": {"require_present": True},
            "packs": [{"profile": "cisco_data_center"}, {"profile": "cisco_enterprise_networks"}],
        }

        with tempfile.TemporaryDirectory() as tempdir:
            result = ContentPackWorkflow(client, tempdir).run(spec, "preview")
            report_text = Path(result["report_path"]).read_text(encoding="utf-8")

        self.assertIn("Import Cisco Nexus Dashboard services from the service import module.", report_text)
        self.assertIn("Import services from Cisco Catalyst Center and Cisco Meraki.", report_text)


if __name__ == "__main__":
    unittest.main()
