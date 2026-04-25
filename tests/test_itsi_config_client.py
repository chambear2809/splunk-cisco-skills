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

import lib.client as client_module
from lib.client import ClientConfig, SplunkRestClient
from lib.common import ValidationError


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


if __name__ == "__main__":
    unittest.main()
