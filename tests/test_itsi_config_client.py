from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "skills" / "splunk-itsi-config" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.client import ClientConfig, SplunkRestClient
from lib.common import ValidationError


class SplunkRestClientTests(unittest.TestCase):
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

    def test_content_pack_catalog_reports_missing_itsi_endpoint_cleanly(self) -> None:
        client = SplunkRestClient(ClientConfig(base_url="https://example.com", verify_ssl=False, username=None, password=None, session_key="token"))
        client._request = lambda *args, **kwargs: (_ for _ in ()).throw(KeyError("/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/content_pack"))  # type: ignore[attr-defined]

        with self.assertRaises(ValidationError) as error:
            client.content_pack_catalog()

        self.assertIn("SA-ITOA", str(error.exception))
        self.assertIn("content_pack", str(error.exception))


if __name__ == "__main__":
    unittest.main()
