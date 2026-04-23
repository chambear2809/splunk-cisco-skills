from __future__ import annotations

import base64
import json
import os
import ssl
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
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
            with urlopen(request, context=self._ssl_context) as response:
                raw = response.read()
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 404:
                raise KeyError(path) from exc
            raise ValidationError(f"Splunk REST request failed: {method} {path} -> HTTP {exc.code}: {response_body}") from exc
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
            return [deepcopy(response)]
        return []

    def app_exists(self, app_name: str) -> bool:
        try:
            self._request("GET", f"/services/apps/local/{quote(app_name)}")
            return True
        except KeyError:
            return False

    def first_installed_app(self, candidates: list[str]) -> str | None:
        for candidate in candidates:
            if self.app_exists(candidate):
                return candidate
        return None

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

    def find_object_by_title(self, object_type: str, title: str) -> dict[str, Any] | None:
        path = f"/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/{quote(object_type)}"
        try:
            response = self._request(
                "GET",
                path,
                params={"count": 0, "filter": json.dumps({"title": title})},
            )
        except KeyError as exc:
            raise ValidationError(
                f"ITSI REST endpoint '{path}' is unavailable. Confirm Splunk IT Service Intelligence (SA-ITOA) is installed on this instance."
            ) from exc
        entries = self._normalize_entries(response)
        return entries[0] if entries else None

    def get_object(self, object_type: str, key: str) -> dict[str, Any] | None:
        try:
            response = self._request("GET", f"/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/{quote(object_type)}/{quote(key)}")
        except KeyError:
            return None
        entries = self._normalize_entries(response)
        return entries[0] if entries else None

    def create_object(self, object_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        path = f"/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/{quote(object_type)}"
        try:
            return self._request("POST", path, payload=payload)
        except KeyError as exc:
            raise ValidationError(
                f"ITSI REST endpoint '{path}' is unavailable. Confirm Splunk IT Service Intelligence (SA-ITOA) is installed on this instance."
            ) from exc

    def update_object(self, object_type: str, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        path = f"/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/{quote(object_type)}/{quote(key)}"
        try:
            return self._request(
                "PUT",
                path,
                payload=payload,
            )
        except KeyError as exc:
            raise ValidationError(
                f"ITSI REST endpoint '{path}' is unavailable. Confirm Splunk IT Service Intelligence (SA-ITOA) is installed on this instance."
            ) from exc

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
