from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "skills" / "splunk-itsi-config" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import lib.client as client_module  # noqa: E402
from lib.client import ClientConfig, SplunkRestClient  # noqa: E402
from lib.common import ValidationError  # noqa: E402


class SplunkRestClientTests(unittest.TestCase):
    def test_get_app_version_returns_version_and_missing_none(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))

        def fake_request(method, path, params=None, payload=None):
            if path == "/services/apps/local/SA-ITOA":
                return {"entry": [{"name": "SA-ITOA", "content": {"version": "4.21.2"}}]}
            if path == "/services/apps/local/missing":
                raise KeyError(path)
            raise AssertionError(path)

        client._request = fake_request  # type: ignore[attr-defined]

        self.assertEqual(client.get_app_version("SA-ITOA"), "4.21.2")
        self.assertIsNone(client.get_app_version("missing"))

    def test_kvstore_status_reads_current_status(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        client._request = lambda *args, **kwargs: {  # type: ignore[attr-defined]
            "entry": [{"content": {"current": {"status": "ready"}}}]
        }

        self.assertEqual(client.kvstore_status(), "ready")

    def test_kvstore_collection_health_reports_accessible_and_missing(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))

        def fake_request(method, path, params=None, payload=None):
            if path.endswith("/itsi_services"):
                return []
            if path.endswith("/itsi_missing"):
                raise KeyError(path)
            raise AssertionError(path)

        client._request = fake_request  # type: ignore[attr-defined]

        self.assertEqual(
            client.kvstore_collection_health("SA-ITOA", "itsi_services"),
            {"status": "ok", "message": "accessible"},
        )
        self.assertEqual(
            client.kvstore_collection_health("SA-ITOA", "itsi_missing"),
            {"status": "missing", "message": "not found"},
        )

    def test_content_pack_catalog_falls_back_to_legacy_route_and_normalizes_live_items_success(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path))
            if path == "/servicesNS/nobody/DA-ITSI-ContentLibrary/content_library/discovery":
                return {"success": {"apps_added": []}}
            if path == "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/content_pack":
                raise KeyError(path)
            if path == "/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack":
                return {
                    "items": {
                        "success": [
                            {
                                "id": "DA-ITSI-CP-appdynamics",
                                "title": "Splunk AppDynamics",
                                "version": "1.0.1",
                                "installed_versions": [],
                            }
                        ],
                        "failure": [],
                    }
                }
            raise AssertionError(path)

        client._request = fake_request  # type: ignore[attr-defined]

        catalog = client.content_pack_catalog()

        self.assertEqual(catalog, [{"id": "DA-ITSI-CP-appdynamics", "title": "Splunk AppDynamics", "version": "1.0.1", "installed_versions": []}])
        self.assertEqual(
            calls,
            [
                ("POST", "/servicesNS/nobody/DA-ITSI-ContentLibrary/content_library/discovery"),
                ("GET", "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/content_pack"),
                ("GET", "/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack"),
            ],
        )

    def test_preview_content_pack_falls_back_to_legacy_route(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path))
            if path == "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/content_pack/DA-ITSI-CP-appdynamics/1.0.1/preview":
                raise KeyError(path)
            if path == "/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack/DA-ITSI-CP-appdynamics/1.0.1/preview":
                return {"service_templates": [{"id": "template-1"}]}
            raise AssertionError(path)

        client._request = fake_request  # type: ignore[attr-defined]

        preview = client.preview_content_pack("DA-ITSI-CP-appdynamics", "1.0.1")

        self.assertEqual(preview, {"service_templates": [{"id": "template-1"}]})
        self.assertEqual(
            calls,
            [
                ("GET", "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/content_pack/DA-ITSI-CP-appdynamics/1.0.1/preview"),
                ("GET", "/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack/DA-ITSI-CP-appdynamics/1.0.1/preview"),
            ],
        )

    def test_install_content_pack_falls_back_to_legacy_route(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object]] = []
        payload = {"install_all": True}

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, payload))
            if path == "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/content_pack/DA-ITSI-CP-appdynamics/1.0.1/install":
                raise KeyError(path)
            if path == "/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack/DA-ITSI-CP-appdynamics/1.0.1/install":
                return {"success": True}
            raise AssertionError(path)

        client._request = fake_request  # type: ignore[attr-defined]

        result = client.install_content_pack("DA-ITSI-CP-appdynamics", "1.0.1", payload)

        self.assertEqual(result, {"success": True})
        self.assertEqual(
            calls,
            [
                ("POST", "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/content_pack/DA-ITSI-CP-appdynamics/1.0.1/install", payload),
                ("POST", "/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack/DA-ITSI-CP-appdynamics/1.0.1/install", payload),
            ],
        )

    def test_find_object_by_title_reports_missing_itsi_endpoint_cleanly(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        client._request = lambda *args, **kwargs: (_ for _ in ()).throw(KeyError("/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/service"))  # type: ignore[attr-defined]

        with self.assertRaises(ValidationError) as error:
            client.find_object_by_title("service", "Example Service")

        self.assertIn("SA-ITOA", str(error.exception))
        self.assertIn("service", str(error.exception))

    def test_create_object_reports_missing_itsi_endpoint_cleanly(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        client._request = lambda *args, **kwargs: (_ for _ in ()).throw(KeyError("/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/service"))  # type: ignore[attr-defined]

        with self.assertRaises(ValidationError) as error:
            client.create_object("service", {"title": "Example Service"})

        self.assertIn("SA-ITOA", str(error.exception))

    def test_update_object_uses_documented_post_for_keyed_itsi_updates(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object, object]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, params, payload))
            if path == "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/service/service%3Aapi":
                return {"_key": "service:api"}
            raise AssertionError(path)

        client._request = fake_request  # type: ignore[attr-defined]

        result = client.update_object("service", "service:api", {"title": "API"})

        self.assertEqual(result, {"_key": "service:api"})
        self.assertEqual(
            calls,
            [
                (
                    "POST",
                    "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/service/service%3Aapi",
                    {"is_partial_data": 1},
                    {"title": "API"},
                )
            ],
        )

    def test_find_object_by_field_uses_configured_identity_field(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, params))
            return {"entry": [{"content": {"_key": "correlation:1", "name": "Edge Device Down"}}]}

        client._request = fake_request  # type: ignore[attr-defined]

        found = client.find_object_by_field("correlation_search", "name", "Edge Device Down", interface="event_management")

        self.assertEqual(found, {"_key": "correlation:1", "name": "Edge Device Down"})
        self.assertEqual(
            calls,
            [
                (
                    "GET",
                    "/servicesNS/nobody/SA-ITOA/event_management_interface/vLatest/correlation_search",
                    {"filter_data": '{"name": "Edge Device Down"}'},
                )
            ],
        )

    def test_find_object_by_field_keeps_filter_for_default_itoa_interface(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, params))
            return {"entry": [{"content": {"_key": "service:1", "title": "API"}}]}

        client._request = fake_request  # type: ignore[attr-defined]

        found = client.find_object_by_field("service", "title", "API")

        self.assertEqual(found, {"_key": "service:1", "title": "API"})
        self.assertEqual(
            calls,
            [
                (
                    "GET",
                    "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/service",
                    {"count": 0, "filter": '{"title": "API"}'},
                )
            ],
        )

    def test_list_objects_uses_route_specific_pagination_params(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, params))
            return {"entry": [{"content": {"_key": "service:1", "title": "API"}}]}

        client._request = fake_request  # type: ignore[attr-defined]

        listed = client.list_objects("service")

        self.assertEqual(listed, [{"_key": "service:1", "title": "API"}])
        self.assertEqual(
            calls,
            [("GET", "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/service", {"count": 0})],
        )

    def test_list_event_management_objects_omits_unsupported_count_param(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, params))
            return {"entry": [{"content": {"_key": "correlation:1", "name": "Alert"}}]}

        client._request = fake_request  # type: ignore[attr-defined]

        listed = client.list_objects("correlation_search", interface="event_management")

        self.assertEqual(listed, [{"_key": "correlation:1", "name": "Alert"}])
        self.assertEqual(
            calls,
            [("GET", "/servicesNS/nobody/SA-ITOA/event_management_interface/vLatest/correlation_search", None)],
        )

    def test_kpi_entity_threshold_uses_documented_put_endpoint(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object, object]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, params, payload))
            if path == "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/kpi_entity_threshold":
                return {"_key": "threshold:1"}
            if path == "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/kpi_entity_threshold/threshold%3A1":
                return {"_key": "threshold:1"}
            raise AssertionError(path)

        client._request = fake_request  # type: ignore[attr-defined]

        created = client.create_object("kpi_entity_threshold", {"title": "Threshold"})
        updated = client.update_object("kpi_entity_threshold", "threshold:1", {"title": "Threshold"})
        deleted = client.delete_object("kpi_entity_threshold", "threshold:1")

        self.assertEqual(created, {"_key": "threshold:1"})
        self.assertEqual(updated, {"_key": "threshold:1"})
        self.assertEqual(deleted, {"_key": "threshold:1"})
        self.assertEqual(
            calls,
            [
                ("PUT", "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/kpi_entity_threshold", None, {"title": "Threshold"}),
                ("PUT", "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/kpi_entity_threshold/threshold%3A1", None, {"title": "Threshold"}),
                ("DELETE", "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/kpi_entity_threshold/threshold%3A1", None, None),
            ],
        )

    def test_event_management_object_uses_event_management_interface(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, payload))
            if path == "/servicesNS/nobody/SA-ITOA/event_management_interface/vLatest/correlation_search":
                raise KeyError(path)
            if path == "/servicesNS/nobody/SA-ITOA/event_management_interface/correlation_search":
                return {"_key": "correlation:1"}
            raise AssertionError(path)

        client._request = fake_request  # type: ignore[attr-defined]

        result = client.create_object("correlation_search", {"title": "Alert"}, interface="event_management")

        self.assertEqual(result, {"_key": "correlation:1"})
        self.assertEqual(
            calls,
            [
                ("POST", "/servicesNS/nobody/SA-ITOA/event_management_interface/vLatest/correlation_search", {"data": {"title": "Alert"}}),
                ("POST", "/servicesNS/nobody/SA-ITOA/event_management_interface/correlation_search", {"data": {"title": "Alert"}}),
            ],
        )

    def test_event_management_update_keeps_raw_keyed_payload(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object, object]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, params, payload))
            if path == "/servicesNS/nobody/SA-ITOA/event_management_interface/vLatest/correlation_search/correlation%3A1":
                return {"_key": "correlation:1"}
            raise AssertionError(path)

        client._request = fake_request  # type: ignore[attr-defined]

        result = client.update_object("correlation_search", "correlation:1", {"title": "Alert"}, interface="event_management")

        self.assertEqual(result, {"_key": "correlation:1"})
        self.assertEqual(
            calls,
            [
                (
                    "POST",
                    "/servicesNS/nobody/SA-ITOA/event_management_interface/vLatest/correlation_search/correlation%3A1",
                    {"is_partial_data": 1},
                    {"title": "Alert"},
                ),
            ],
        )

    def test_delete_object_uses_keyed_delete_endpoint(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object, object]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, params, payload))
            if path == "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/service/service%3Aorphan":
                return {"_key": "service:orphan"}
            raise AssertionError(path)

        client._request = fake_request  # type: ignore[attr-defined]

        result = client.delete_object("service", "service:orphan")

        self.assertEqual(result, {"_key": "service:orphan"})
        self.assertEqual(
            calls,
            [("DELETE", "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/service/service%3Aorphan", None, None)],
        )

    def test_content_pack_authorship_update_keeps_full_payload_semantics(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object, object]] = []
        payload = {"title": "Network Pack", "itsi_objects": {"service": []}}

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, params, payload))
            if path == "/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack_authorship/vLatest/content_pack/pack%3A1":
                raise KeyError(path)
            if path == "/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack_authorship/content_pack/pack%3A1":
                return {"_key": "pack:1"}
            raise AssertionError(path)

        client._request = fake_request  # type: ignore[attr-defined]

        result = client.update_object("content_pack", "pack:1", payload, interface="content_pack_authorship")

        self.assertEqual(result, {"_key": "pack:1"})
        self.assertEqual(
            calls,
            [
                (
                    "POST",
                    "/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack_authorship/vLatest/content_pack/pack%3A1",
                    None,
                    payload,
                ),
                (
                    "POST",
                    "/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack_authorship/content_pack/pack%3A1",
                    None,
                    payload,
                ),
            ],
        )

    def test_delete_object_uses_content_pack_authorship_delete_route(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object, object]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, params, payload))
            if path == "/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack_authorship/vLatest/content_pack/pack%3A1":
                return {"_key": "pack:1"}
            raise AssertionError(path)

        client._request = fake_request  # type: ignore[attr-defined]

        result = client.delete_object("content_pack", "pack:1", interface="content_pack_authorship")

        self.assertEqual(result, {"_key": "pack:1"})
        self.assertEqual(
            calls,
            [("DELETE", "/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack_authorship/vLatest/content_pack/pack%3A1", None, None)],
        )

    def test_backup_restore_object_uses_backup_restore_interface(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, payload))
            if path == "/servicesNS/nobody/SA-ITOA/backup_restore_interface/vLatest/backup_restore":
                return {"_key": "backup:1"}
            raise AssertionError(path)

        client._request = fake_request  # type: ignore[attr-defined]

        result = client.create_object("backup_restore", {"title": "Nightly Backup"}, interface="backup_restore")

        self.assertEqual(result, {"_key": "backup:1"})
        self.assertEqual(
            calls,
            [("POST", "/servicesNS/nobody/SA-ITOA/backup_restore_interface/vLatest/backup_restore", {"title": "Nightly Backup"})],
        )

    def test_custom_content_pack_uses_content_pack_authorship_interface(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, payload))
            if path == "/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack_authorship/vLatest/content_pack":
                raise KeyError(path)
            if path == "/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack_authorship/content_pack":
                return {"_key": "pack:1"}
            raise AssertionError(path)

        client._request = fake_request  # type: ignore[attr-defined]

        result = client.create_object("content_pack", {"title": "Network Pack"}, interface="content_pack_authorship")

        self.assertEqual(result, {"_key": "pack:1"})
        self.assertEqual(
            calls,
            [
                ("POST", "/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack_authorship/vLatest/content_pack", {"title": "Network Pack"}),
                ("POST", "/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack_authorship/content_pack", {"title": "Network Pack"}),
            ],
        )

    def test_glass_table_icons_use_icon_collection_route_and_result_normalizer(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object, object]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, params, payload))
            if method == "GET" and path == "/services/SA-ITOA/v1/icon_collection":
                return {"result": [{"_key": "icon:1", "title": "Router"}]}
            if method == "PUT" and path == "/services/SA-ITOA/v1/icon_collection":
                return ["icon:1"]
            if method == "DELETE" and path == "/services/SA-ITOA/v1/icon_collection/icon%3A1":
                return {"_key": "icon:1"}
            raise AssertionError(path)

        client._request = fake_request  # type: ignore[attr-defined]

        found = client.find_object_by_title("icon", "Router", interface="icon_collection")
        created = client.create_object("icon", {"title": "Router", "svg_path": "M0 0h10v10H0z"}, interface="icon_collection")
        updated = client.update_object("icon", "icon:1", {"title": "Router", "svg_path": "M1 1h8v8H1z"}, interface="icon_collection")
        deleted = client.delete_object("icon", "icon:1", interface="icon_collection")

        self.assertEqual(found, {"_key": "icon:1", "title": "Router"})
        self.assertEqual(created, {"_key": "icon:1"})
        self.assertEqual(updated, {"_key": "icon:1"})
        self.assertEqual(deleted, {"_key": "icon:1"})
        self.assertEqual(
            calls,
            [
                ("GET", "/services/SA-ITOA/v1/icon_collection", {"filter": '{"title": "Router"}'}, None),
                ("PUT", "/services/SA-ITOA/v1/icon_collection", None, [{"title": "Router", "svg_path": "M0 0h10v10H0z"}]),
                ("PUT", "/services/SA-ITOA/v1/icon_collection", None, [{"title": "Router", "svg_path": "M1 1h8v8H1z", "_key": "icon:1"}]),
                ("DELETE", "/services/SA-ITOA/v1/icon_collection/icon%3A1", None, None),
            ],
        )

    def test_get_service_template_link_returns_linked_template_key(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, payload))
            self.assertIsNone(payload)
            return {"_key": "template:esxi"}

        client._request = fake_request  # type: ignore[attr-defined]

        linked_key = client.get_service_template_link("service:cluster")

        self.assertEqual(linked_key, "template:esxi")
        self.assertEqual(
            calls,
            [("GET", "/servicesNS/nobody/SA-ITOA/itoa_interface/service/service%3Acluster/base_service_template", None)],
        )

    def test_link_service_to_template_posts_expected_payload(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, payload))
            return {"_key": "service:cluster"}

        client._request = fake_request  # type: ignore[attr-defined]

        result = client.link_service_to_template("service:cluster", "template:esxi")

        self.assertEqual(result, {"_key": "service:cluster"})
        self.assertEqual(
            calls,
            [
                (
                    "POST",
                    "/servicesNS/nobody/SA-ITOA/itoa_interface/service/service%3Acluster/base_service_template",
                    {"_key": "template:esxi"},
                )
            ],
        )

    def test_custom_threshold_window_linked_kpis_reads_all_links(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object, object]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, params, payload))
            return {"linked_kpis": [{"service_key": "service:api", "kpi_key": "kpi:latency"}], "count": 1}

        client._request = fake_request  # type: ignore[attr-defined]

        result = client.custom_threshold_window_linked_kpis("ctw:business-hours")

        self.assertEqual(result["count"], 1)
        self.assertEqual(
            calls,
            [
                (
                    "GET",
                    "/servicesNS/nobody/SA-ITOA/itoa_interface/custom_threshold_windows/linked_kpis",
                    {"custom_threshold_window_id": "ctw:business-hours", "limit": 0},
                    None,
                )
            ],
        )

    def test_associate_custom_threshold_window_kpis_posts_payload(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object]] = []
        payload = {"services": [{"_key": "service:api", "kpi_ids": ["kpi:latency"]}]}

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, payload))
            return {"services": [{"_key": "service:api", "kpi_ids": ["kpi:latency"]}]}

        client._request = fake_request  # type: ignore[attr-defined]

        result = client.associate_custom_threshold_window_kpis("ctw:business-hours", payload)

        self.assertEqual(result, payload)
        self.assertEqual(
            calls,
            [
                (
                    "POST",
                    "/servicesNS/nobody/SA-ITOA/itoa_interface/custom_threshold_windows/ctw%3Abusiness-hours/associate_service_kpi",
                    payload,
                )
            ],
        )

    def test_guarded_operational_helpers_use_documented_routes(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, payload))
            if path == "/servicesNS/nobody/SA-ITOA/itoa_interface/entity/retire_retirable":
                return ["entity:1"]
            return {"status": "ok"}

        client._request = fake_request  # type: ignore[attr-defined]

        client.disconnect_custom_threshold_window_kpis("ctw:business-hours")
        client.stop_custom_threshold_window("ctw:business-hours")
        client.retire_entities({"data": ["entity:1"]})
        client.restore_entities({"data": ["entity:1"]})
        retired = client.retire_retirable_entities()
        client.apply_kpi_threshold_recommendation({"itsi_service_id": "service:1", "itsi_kpi_id": "kpi:1"})
        client.apply_kpi_entity_threshold_recommendation({"itsi_service_id": "service:1", "itsi_kpi_id": "kpi:1", "entity_key": "entity:1"})
        client.shift_time_offset({"offset": 3600, "service": {"_keys": ["service:1"]}})

        self.assertEqual(retired, ["entity:1"])
        self.assertEqual(
            calls,
            [
                ("POST", "/servicesNS/nobody/SA-ITOA/itoa_interface/custom_threshold_windows/ctw%3Abusiness-hours/disconnect_kpis", None),
                ("POST", "/servicesNS/nobody/SA-ITOA/itoa_interface/custom_threshold_windows/ctw%3Abusiness-hours/stop", None),
                ("POST", "/servicesNS/nobody/SA-ITOA/itoa_interface/entity/retire", {"data": ["entity:1"]}),
                ("POST", "/servicesNS/nobody/SA-ITOA/itoa_interface/entity/restore", {"data": ["entity:1"]}),
                ("POST", "/servicesNS/nobody/SA-ITOA/itoa_interface/entity/retire_retirable", None),
                ("POST", "/servicesNS/nobody/SA-ITOA/itoa_interface/kpi_threshold_recommendations", {"itsi_service_id": "service:1", "itsi_kpi_id": "kpi:1"}),
                ("POST", "/servicesNS/nobody/SA-ITOA/itoa_interface/kpi_entity_threshold_recommendations", {"itsi_service_id": "service:1", "itsi_kpi_id": "kpi:1", "entity_key": "entity:1"}),
                ("PUT", "/servicesNS/nobody/SA-ITOA/itoa_interface/shift_time_offset", {"offset": 3600, "service": {"_keys": ["service:1"]}}),
            ],
        )

    def test_content_pack_catalog_reports_missing_itsi_endpoint_cleanly(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        client._request = lambda *args, **kwargs: (_ for _ in ()).throw(KeyError("/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/content_pack"))  # type: ignore[attr-defined]

        with self.assertRaises(ValidationError) as error:
            client.content_pack_catalog()

        self.assertIn("SA-ITOA", str(error.exception))
        self.assertIn("content_pack", str(error.exception))

    def test_request_wraps_urlerror_as_validation_error(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username="user", password="pass", session_key=None))

        with patch.object(client_module, "urlopen", side_effect=URLError("timed out")):
            with self.assertRaises(ValidationError) as error:
                client.app_exists("SA-ITOA")

        self.assertIn("timed out", str(error.exception))
        self.assertIn("GET", str(error.exception))

    def test_discovery_helpers_use_itsi_interfaces(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path))
            if path == "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/get_supported_object_types":
                return ["service", "entity"]
            if path == "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/get_alias_list":
                return {"items": ["host"]}
            if path == "/servicesNS/nobody/SA-ITOA/event_management_interface/vLatest/notable_event_actions":
                return {"entry": [{"name": "send_email", "content": {"name": "send_email"}}]}
            raise AssertionError(path)

        client._request = fake_request  # type: ignore[attr-defined]

        self.assertEqual(client.itsi_supported_object_types("itoa")[0]["title"], "service")
        self.assertEqual(client.itsi_supported_object_types("itoa")[1]["name"], "entity")
        self.assertEqual(client.itsi_alias_list(), {"items": ["host"]})
        self.assertEqual(client.notable_event_actions()[0]["name"], "send_email")
        self.assertEqual(
            calls,
            [
                ("GET", "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/get_supported_object_types"),
                ("GET", "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/get_supported_object_types"),
                ("GET", "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/get_alias_list"),
                ("GET", "/servicesNS/nobody/SA-ITOA/event_management_interface/vLatest/notable_event_actions"),
            ],
        )

    def test_event_analytics_helpers_use_documented_routes(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        calls: list[tuple[str, str, object]] = []

        def fake_request(method, path, params=None, payload=None):
            calls.append((method, path, payload))
            return {"ok": True}

        client._request = fake_request  # type: ignore[attr-defined]

        client.update_notable_event_group("episode:1", {"status": 5})
        client.execute_notable_event_action("send_email", {"ids": ["episode:1"], "params": {}})
        client.link_episode_ticket({"ticket_id": "NET-1"}, group_key="episode:1")
        client.unlink_episode_ticket("episode:1", "jira", "NET-1")
        client.create_episode_export({"filter_data": {"status": 5}})
        client.event_management_count("notable_event_group", {"status": 5})
        client.active_maintenance_window("service:1")
        client.maintenance_windows_for_object("service:1")
        client.maintenance_windows_count_for_object("service:1")

        self.assertEqual(
            calls,
            [
                ("POST", "/servicesNS/nobody/SA-ITOA/event_management_interface/vLatest/notable_event_group/episode%3A1", {"status": 5}),
                ("POST", "/servicesNS/nobody/SA-ITOA/event_management_interface/vLatest/notable_event_actions/send_email", {"ids": ["episode:1"], "params": {}}),
                ("POST", "/servicesNS/nobody/SA-ITOA/event_management_interface/vLatest/ticketing/episode%3A1", {"ticket_id": "NET-1"}),
                ("DELETE", "/servicesNS/nobody/SA-ITOA/event_management_interface/vLatest/ticketing/episode%3A1/jira/NET-1", None),
                ("POST", "/servicesNS/nobody/SA-ITOA/event_management_interface/vLatest/episode_export", {"filter_data": {"status": 5}}),
                ("GET", "/servicesNS/nobody/SA-ITOA/event_management_interface/vLatest/notable_event_group/count", None),
                ("GET", "/servicesNS/nobody/SA-ITOA/maintenance_services_interface/vLatest/get_active_maintenance_window/service%3A1", None),
                ("GET", "/servicesNS/nobody/SA-ITOA/maintenance_services_interface/vLatest/get_maintenance_windows/service%3A1", None),
                ("GET", "/servicesNS/nobody/SA-ITOA/maintenance_services_interface/vLatest/get_maintenance_windows/count/service%3A1", None),
            ],
        )

    def test_from_spec_inherits_verify_ssl_from_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SPLUNK_SEARCH_API_URI": "https://example.com:8089",
                "SPLUNK_SESSION_KEY": "token",
                "SPLUNK_VERIFY_SSL": "false",
            },
            clear=True,
        ):
            client = SplunkRestClient.from_spec({"connection": {}})

        self.assertFalse(client.config.verify_ssl)

    def test_from_spec_verify_ssl_overrides_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SPLUNK_SEARCH_API_URI": "https://example.com:8089",
                "SPLUNK_SESSION_KEY": "token",
                "SPLUNK_VERIFY_SSL": "false",
            },
            clear=True,
        ):
            client = SplunkRestClient.from_spec({"connection": {"verify_ssl": True}})

        self.assertTrue(client.config.verify_ssl)


if __name__ == "__main__":
    unittest.main()
