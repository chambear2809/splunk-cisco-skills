from __future__ import annotations

import base64
import json
import os
import ssl
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .common import ValidationError, bool_from_any


@dataclass
class ClientConfig:
    base_url: str
    verify_ssl: bool
    username: str | None
    password: str | None
    session_key: str | None


class SplunkRestClient:
    REQUEST_TIMEOUT_SECONDS = 30

    def __init__(self, config: ClientConfig):
        self.config = config
        self._ssl_context = None
        self._content_pack_base_path: str | None = None
        self._content_library_discovery_attempted = False
        if not config.verify_ssl:
            self._ssl_context = ssl._create_unverified_context()

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> "SplunkRestClient":
        connection = spec.get("connection", {})
        base_url = str(connection.get("base_url") or os.environ.get("SPLUNK_SEARCH_API_URI") or os.environ.get("SPLUNK_URI") or "").strip()
        if not base_url:
            raise ValidationError("Missing Splunk base URL. Set connection.base_url or SPLUNK_SEARCH_API_URI.")
        verify_ssl = bool_from_any(connection.get("verify_ssl"), default=True)
        session_key = cls._read_secret(connection.get("session_key_env"), "SPLUNK_SESSION_KEY")
        username = cls._read_secret(connection.get("username_env"), "SPLUNK_USERNAME")
        password = cls._read_secret(connection.get("password_env"), "SPLUNK_PASSWORD")
        if not session_key and not (username and password):
            raise ValidationError(
                "Missing Splunk credentials. Set SPLUNK_SESSION_KEY or provide SPLUNK_USERNAME and SPLUNK_PASSWORD."
            )
        return cls(
            ClientConfig(
                base_url=base_url.rstrip("/"),
                verify_ssl=verify_ssl,
                username=username,
                password=password,
                session_key=session_key,
            )
        )

    @staticmethod
    def _read_secret(configured_env: Any, fallback_env: str) -> str | None:
        if configured_env:
            return os.environ.get(str(configured_env))
        return os.environ.get(fallback_env)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.config.session_key:
            headers["Authorization"] = f"Splunk {self.config.session_key}"
        elif self.config.username and self.config.password:
            token = base64.b64encode(f"{self.config.username}:{self.config.password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        return headers

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None, payload: Any = None) -> Any:
        query_params = {"output_mode": "json"}
        if params:
            query_params.update({key: value for key, value in params.items() if value is not None})
        query = urlencode(query_params)
        url = f"{self.config.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        body = None
        headers = self._headers()
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, method=method.upper(), headers=headers, data=body)
        try:
            with urlopen(request, context=self._ssl_context, timeout=self.REQUEST_TIMEOUT_SECONDS) as response:
                raw = response.read()
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 404:
                raise KeyError(path) from exc
            raise ValidationError(f"Splunk REST request failed: {method} {path} -> HTTP {exc.code}: {response_body}") from exc
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise ValidationError(f"Splunk REST request failed: {method} {path} -> {reason}") from exc
        except OSError as exc:
            raise ValidationError(f"Splunk REST request failed: {method} {path} -> {exc}") from exc
        if not raw:
            return {}
        content_type = response.headers.get("Content-Type", "")
        if "json" in content_type or raw[:1] in {b"{", b"["}:
            return json.loads(raw.decode("utf-8"))
        return raw.decode("utf-8")

    @staticmethod
    def _normalize_entries(response: Any) -> list[dict[str, Any]]:
        if isinstance(response, list):
            return [deepcopy(item) for item in response if isinstance(item, dict)]
        if isinstance(response, dict):
            if isinstance(response.get("entry"), list):
                normalized = []
                for entry in response["entry"]:
                    if not isinstance(entry, dict):
                        continue
                    item = deepcopy(entry.get("content") or {})
                    if "name" in entry:
                        item.setdefault("name", entry["name"])
                    if "_key" in entry:
                        item.setdefault("_key", entry["_key"])
                    if "acl" in entry:
                        item["acl"] = deepcopy(entry["acl"])
                        if isinstance(entry["acl"], dict) and "app" in entry["acl"]:
                            item.setdefault("eai:acl.app", entry["acl"]["app"])
                    normalized.append(item)
                return normalized
            if isinstance(response.get("items"), list):
                return [deepcopy(item) for item in response["items"] if isinstance(item, dict)]
            if isinstance(response.get("result"), list):
                return [deepcopy(item) for item in response["result"] if isinstance(item, dict)]
            return [deepcopy(response)]
        return []

    def get_app(self, app_name: str) -> dict[str, Any] | None:
        try:
            response = self._request("GET", f"/services/apps/local/{quote(app_name)}")
        except KeyError:
            return None
        entries = self._normalize_entries(response)
        return entries[0] if entries else None

    def app_exists(self, app_name: str) -> bool:
        return self.get_app(app_name) is not None

    def get_app_version(self, app_name: str) -> str | None:
        app = self.get_app(app_name)
        if not app:
            return None
        version = str(app.get("version") or "").strip()
        return version or None

    def first_installed_app(self, candidates: list[str]) -> str | None:
        for candidate in candidates:
            if self.app_exists(candidate):
                return candidate
        return None

    def kvstore_status(self) -> str | None:
        response = self._request("GET", "/services/kvstore/status")
        entries = self._normalize_entries(response)
        if not entries:
            return None
        current = entries[0].get("current")
        if isinstance(current, dict):
            status = str(current.get("status") or "").strip()
            return status or None
        status = str(entries[0].get("status") or "").strip()
        return status or None

    def kvstore_collection_health(self, app_name: str, collection_name: str) -> dict[str, str]:
        path = f"/servicesNS/nobody/{quote(app_name)}/storage/collections/data/{quote(collection_name)}"
        try:
            self._request("GET", path, params={"count": 1})
            return {"status": "ok", "message": "accessible"}
        except KeyError:
            return {"status": "missing", "message": "not found"}
        except ValidationError as exc:
            return {"status": "error", "message": str(exc)}

    def list_macros(self, app_name: str) -> list[dict[str, Any]]:
        return self._normalize_entries(self._request("GET", f"/servicesNS/nobody/{quote(app_name)}/admin/macros", params={"count": 0}))

    def get_macro(self, app_name: str, macro_name: str) -> dict[str, Any] | None:
        try:
            response = self._request("GET", f"/servicesNS/nobody/{quote(app_name)}/admin/macros/{quote(macro_name)}")
        except KeyError:
            return None
        entries = self._normalize_entries(response)
        return entries[0] if entries else None

    def get_conf_stanza(self, app_name: str, conf_name: str, stanza_name: str) -> dict[str, Any] | None:
        try:
            response = self._request(
                "GET",
                f"/servicesNS/nobody/{quote(app_name)}/configs/conf-{quote(conf_name)}/{quote(stanza_name)}",
            )
        except KeyError:
            return None
        entries = self._normalize_entries(response)
        return entries[0] if entries else None

    def list_inputs(self, app_name: str | None = None) -> list[dict[str, Any]]:
        entries = self._normalize_entries(self._request("GET", "/services/data/inputs/all", params={"count": 0}))
        if not app_name:
            return entries
        return [entry for entry in entries if str(entry.get("eai:acl.app") or entry.get("app") or "").strip() == app_name]

    def list_endpoint_entries(self, app_name: str, endpoint_name: str) -> list[dict[str, Any]]:
        try:
            response = self._request(
                "GET",
                f"/servicesNS/nobody/{quote(app_name)}/{quote(endpoint_name)}",
                params={"count": 0},
            )
        except KeyError:
            return []
        return self._normalize_entries(response)

    @staticmethod
    def _itsi_interface_base_candidates(interface: str) -> list[str]:
        interface_paths = {
            "itoa": "itoa_interface",
            "event_management": "event_management_interface",
            "maintenance": "maintenance_services_interface",
            "backup_restore": "backup_restore_interface",
            "content_pack_authorship": "itoa_interface/content_pack_authorship",
        }
        if interface == "icon_collection":
            return ["/services/SA-ITOA/v1/icon_collection"]
        interface_path = interface_paths.get(interface)
        if not interface_path:
            raise ValidationError(f"Unsupported ITSI REST interface '{interface}'.")
        base = f"/servicesNS/nobody/SA-ITOA/{interface_path}"
        return [f"{base}/vLatest", base]

    def _request_itsi_object(
        self,
        method: str,
        interface: str,
        object_type: str,
        key: str | None = None,
        params: dict[str, Any] | None = None,
        payload: Any = None,
    ) -> Any:
        last_missing: KeyError | None = None
        checked_paths: list[str] = []
        suffix = "" if interface == "icon_collection" else f"/{quote(object_type)}"
        if key:
            suffix = f"{suffix}/{quote(key)}"
        for base_path in self._itsi_interface_base_candidates(interface):
            path = f"{base_path}{suffix}"
            checked_paths.append(path)
            try:
                return self._request(method, path, params=params, payload=payload)
            except KeyError as exc:
                last_missing = exc
        checked = ", ".join(checked_paths)
        raise ValidationError(
            "ITSI REST endpoint is unavailable. "
            f"Checked: {checked}. Confirm Splunk IT Service Intelligence (SA-ITOA) is installed on this instance."
        ) from last_missing

    @staticmethod
    def _itsi_filter_param(interface: str) -> str:
        if interface == "event_management":
            return "filter_data"
        return "filter"

    @classmethod
    def _itsi_lookup_params(cls, interface: str, field: str, value: str) -> dict[str, Any]:
        params: dict[str, Any] = {cls._itsi_filter_param(interface): json.dumps({field: value})}
        if interface in {"itoa", "content_pack_authorship"}:
            params["count"] = 0
        return params

    def find_object_by_field(
        self,
        object_type: str,
        field: str,
        value: str,
        interface: str = "itoa",
    ) -> dict[str, Any] | None:
        response = self._request_itsi_object(
            "GET",
            interface,
            object_type,
            params=self._itsi_lookup_params(interface, field, value),
        )
        entries = self._normalize_entries(response)
        return entries[0] if entries else None

    def find_object_by_title(self, object_type: str, title: str, interface: str = "itoa") -> dict[str, Any] | None:
        return self.find_object_by_field(object_type, "title", title, interface=interface)

    def find_object_by_titles(self, object_type: str, titles: list[str], interface: str = "itoa") -> dict[str, Any] | None:
        for title in titles:
            found = self.find_object_by_title(object_type, title, interface=interface)
            if found:
                return found
        return None

    def list_objects(self, object_type: str, interface: str = "itoa") -> list[dict[str, Any]]:
        params: dict[str, Any] | None = {"count": 0} if interface in {"itoa", "content_pack_authorship"} else None
        response = self._request_itsi_object("GET", interface, object_type, params=params)
        return self._normalize_entries(response)

    def get_object(self, object_type: str, key: str, interface: str = "itoa") -> dict[str, Any] | None:
        try:
            response = self._request_itsi_object("GET", interface, object_type, key=key)
        except ValidationError as exc:
            if "unavailable" not in str(exc):
                raise
            return None
        entries = self._normalize_entries(response)
        return entries[0] if entries else None

    def _save_icon_collection_object(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request_itsi_object("PUT", "icon_collection", "icon", payload=[payload])
        if isinstance(response, list) and response:
            key = response[0]
            if isinstance(key, str):
                return {"_key": key}
        if isinstance(response, dict) and response.get("_key"):
            return {"_key": response["_key"]}
        return {}

    @staticmethod
    def _itsi_write_method(method_type: str, interface: str, object_type: str) -> str:
        if interface == "itoa" and object_type == "kpi_entity_threshold":
            return "PUT"
        if method_type == "update":
            return "POST"
        return "POST"

    @staticmethod
    def _itsi_write_payload(method_type: str, interface: str, payload: dict[str, Any]) -> Any:
        if interface == "event_management" and method_type == "create":
            if set(payload) == {"data"}:
                return payload
            return {"data": payload}
        return payload

    @staticmethod
    def _itsi_update_params(interface: str, object_type: str) -> dict[str, Any] | None:
        if interface in {"itoa", "event_management", "maintenance", "backup_restore"} and object_type != "kpi_entity_threshold":
            return {"is_partial_data": 1}
        return None

    def create_object(self, object_type: str, payload: dict[str, Any], interface: str = "itoa") -> dict[str, Any]:
        if interface == "icon_collection":
            return self._save_icon_collection_object(payload)
        return self._request_itsi_object(
            self._itsi_write_method("create", interface, object_type),
            interface,
            object_type,
            payload=self._itsi_write_payload("create", interface, payload),
        )

    def update_object(self, object_type: str, key: str, payload: dict[str, Any], interface: str = "itoa") -> dict[str, Any]:
        if interface == "icon_collection":
            updated_payload = deepcopy(payload)
            updated_payload.setdefault("_key", key)
            return self._save_icon_collection_object(updated_payload)
        return self._request_itsi_object(
            self._itsi_write_method("update", interface, object_type),
            interface,
            object_type,
            key=key,
            params=self._itsi_update_params(interface, object_type),
            payload=self._itsi_write_payload("update", interface, payload),
        )

    def delete_object(self, object_type: str, key: str, interface: str = "itoa") -> dict[str, Any]:
        if interface == "icon_collection":
            raise ValidationError("Cleanup deletion for icon_collection is not supported by this skill.")
        response = self._request_itsi_object("DELETE", interface, object_type, key=key)
        return response if isinstance(response, dict) else {}

    def get_service_template_link(self, service_key: str) -> str | None:
        path = f"/servicesNS/nobody/SA-ITOA/itoa_interface/service/{quote(service_key)}/base_service_template"
        try:
            response = self._request("GET", path)
        except KeyError as exc:
            raise ValidationError(
                f"ITSI REST endpoint '{path}' is unavailable. Confirm Splunk IT Service Intelligence (SA-ITOA) is installed on this instance."
            ) from exc
        if isinstance(response, dict):
            template_key = str(response.get("_key") or "").strip()
            return template_key or None
        return None

    def link_service_to_template(self, service_key: str, template_key: str) -> dict[str, Any]:
        path = f"/servicesNS/nobody/SA-ITOA/itoa_interface/service/{quote(service_key)}/base_service_template"
        try:
            return self._request("POST", path, payload={"_key": template_key})
        except KeyError as exc:
            raise ValidationError(
                f"ITSI REST endpoint '{path}' is unavailable. Confirm Splunk IT Service Intelligence (SA-ITOA) is installed on this instance."
            ) from exc

    def custom_threshold_window_linked_kpis(self, window_key: str) -> dict[str, Any]:
        path = "/servicesNS/nobody/SA-ITOA/itoa_interface/custom_threshold_windows/linked_kpis"
        try:
            response = self._request("GET", path, params={"custom_threshold_window_id": window_key, "limit": 0})
        except KeyError as exc:
            raise ValidationError(
                f"ITSI REST endpoint '{path}' is unavailable. Confirm Splunk IT Service Intelligence (SA-ITOA) is installed on this instance."
            ) from exc
        return response if isinstance(response, dict) else {}

    def associate_custom_threshold_window_kpis(self, window_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        path = f"/servicesNS/nobody/SA-ITOA/itoa_interface/custom_threshold_windows/{quote(window_key)}/associate_service_kpi"
        try:
            response = self._request("POST", path, payload=payload)
        except KeyError as exc:
            raise ValidationError(
                f"ITSI REST endpoint '{path}' is unavailable. Confirm Splunk IT Service Intelligence (SA-ITOA) is installed on this instance."
            ) from exc
        return response if isinstance(response, dict) else {}

    def disconnect_custom_threshold_window_kpis(self, window_key: str) -> dict[str, Any]:
        path = f"/servicesNS/nobody/SA-ITOA/itoa_interface/custom_threshold_windows/{quote(window_key)}/disconnect_kpis"
        try:
            response = self._request("POST", path)
        except KeyError as exc:
            raise ValidationError(
                f"ITSI REST endpoint '{path}' is unavailable. Confirm Splunk IT Service Intelligence (SA-ITOA) is installed on this instance."
            ) from exc
        return response if isinstance(response, dict) else {}

    def stop_custom_threshold_window(self, window_key: str) -> dict[str, Any]:
        path = f"/servicesNS/nobody/SA-ITOA/itoa_interface/custom_threshold_windows/{quote(window_key)}/stop"
        try:
            response = self._request("POST", path)
        except KeyError as exc:
            raise ValidationError(
                f"ITSI REST endpoint '{path}' is unavailable. Confirm Splunk IT Service Intelligence (SA-ITOA) is installed on this instance."
            ) from exc
        return response if isinstance(response, dict) else {}

    def retire_entities(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = "/servicesNS/nobody/SA-ITOA/itoa_interface/entity/retire"
        try:
            response = self._request("POST", path, payload=payload)
        except KeyError as exc:
            raise ValidationError(
                f"ITSI REST endpoint '{path}' is unavailable. Confirm Splunk IT Service Intelligence (SA-ITOA) is installed on this instance."
            ) from exc
        return response if isinstance(response, dict) else {}

    def restore_entities(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = "/servicesNS/nobody/SA-ITOA/itoa_interface/entity/restore"
        try:
            response = self._request("POST", path, payload=payload)
        except KeyError as exc:
            raise ValidationError(
                f"ITSI REST endpoint '{path}' is unavailable. Confirm Splunk IT Service Intelligence (SA-ITOA) is installed on this instance."
            ) from exc
        return response if isinstance(response, dict) else {}

    def retire_retirable_entities(self) -> Any:
        path = "/servicesNS/nobody/SA-ITOA/itoa_interface/entity/retire_retirable"
        try:
            response = self._request("POST", path)
        except KeyError as exc:
            raise ValidationError(
                f"ITSI REST endpoint '{path}' is unavailable. Confirm Splunk IT Service Intelligence (SA-ITOA) is installed on this instance."
            ) from exc
        return response if isinstance(response, (dict, list)) else {}

    def apply_kpi_threshold_recommendation(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = "/servicesNS/nobody/SA-ITOA/itoa_interface/kpi_threshold_recommendations"
        try:
            response = self._request("POST", path, payload=payload)
        except KeyError as exc:
            raise ValidationError(
                f"ITSI REST endpoint '{path}' is unavailable. Confirm Splunk IT Service Intelligence (SA-ITOA) is installed on this instance."
            ) from exc
        return response if isinstance(response, dict) else {}

    def apply_kpi_entity_threshold_recommendation(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = "/servicesNS/nobody/SA-ITOA/itoa_interface/kpi_entity_threshold_recommendations"
        try:
            response = self._request("POST", path, payload=payload)
        except KeyError as exc:
            raise ValidationError(
                f"ITSI REST endpoint '{path}' is unavailable. Confirm Splunk IT Service Intelligence (SA-ITOA) is installed on this instance."
            ) from exc
        return response if isinstance(response, dict) else {}

    def shift_time_offset(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = "/servicesNS/nobody/SA-ITOA/itoa_interface/shift_time_offset"
        try:
            response = self._request("PUT", path, payload=payload)
        except KeyError as exc:
            raise ValidationError(
                f"ITSI REST endpoint '{path}' is unavailable. Confirm Splunk IT Service Intelligence (SA-ITOA) is installed on this instance."
            ) from exc
        return response if isinstance(response, dict) else {}

    @staticmethod
    def _content_pack_base_candidates() -> list[str]:
        return [
            "/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/content_pack",
            "/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack",
        ]

    def _content_pack_path_candidates(self, suffix: str = "") -> list[tuple[str, str]]:
        bases = self._content_pack_base_candidates()
        cached = self._content_pack_base_path
        if cached in bases:
            bases = [cached] + [base for base in bases if base != cached]
        return [(base, f"{base}{suffix}") for base in bases]

    def _request_content_pack(self, method: str, suffix: str = "", params: dict[str, Any] | None = None, payload: Any = None) -> Any:
        last_missing: KeyError | None = None
        last_path = ""
        for base_path, path in self._content_pack_path_candidates(suffix):
            last_path = path
            try:
                response = self._request(method, path, params=params, payload=payload)
                self._content_pack_base_path = base_path
                return response
            except KeyError as exc:
                last_missing = exc
        raise KeyError(last_path) from last_missing

    def _sync_content_library_catalog(self) -> None:
        if self._content_library_discovery_attempted:
            return
        self._content_library_discovery_attempted = True
        try:
            self._request("POST", "/servicesNS/nobody/DA-ITSI-ContentLibrary/content_library/discovery")
        except (KeyError, ValidationError):
            return

    def _content_pack_unavailable_error(self, suffix: str = "") -> ValidationError:
        checked = ", ".join(path for _, path in self._content_pack_path_candidates(suffix))
        return ValidationError(
            "ITSI REST content_pack endpoints are unavailable. "
            f"Checked: {checked}. Confirm Splunk IT Service Intelligence (SA-ITOA) is installed on this instance."
        )

    @staticmethod
    def _normalize_content_pack_catalog(response: Any) -> list[dict[str, Any]]:
        if isinstance(response, dict):
            items = response.get("items")
            if isinstance(items, dict) and isinstance(items.get("success"), list):
                return [deepcopy(item) for item in items["success"] if isinstance(item, dict)]
        return SplunkRestClient._normalize_entries(response)

    def content_pack_catalog(self) -> list[dict[str, Any]]:
        self._sync_content_library_catalog()
        try:
            response = self._request_content_pack("GET", params={"count": 0})
        except KeyError as exc:
            raise self._content_pack_unavailable_error() from exc
        return self._normalize_content_pack_catalog(response)

    def preview_content_pack(self, pack_id: str, version: str) -> Any:
        suffix = f"/{quote(pack_id)}/{quote(version)}/preview"
        try:
            return self._request_content_pack("GET", suffix)
        except KeyError as exc:
            raise self._content_pack_unavailable_error(suffix) from exc

    def install_content_pack(self, pack_id: str, version: str, payload: dict[str, Any]) -> Any:
        suffix = f"/{quote(pack_id)}/{quote(version)}/install"
        try:
            return self._request_content_pack("POST", suffix, payload=payload)
        except KeyError as exc:
            raise self._content_pack_unavailable_error(suffix) from exc
