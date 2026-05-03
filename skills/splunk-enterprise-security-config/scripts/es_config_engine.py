#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import ssl
import stat
import subprocess
import sys
import tarfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode
from urllib.request import Request, urlopen

# Splunk's auth endpoint returns a small, trusted XML document (sessionKey),
# but defense-in-depth wants a hardened XML parser per the repo's
# codeguard-0-xml-and-serialization rule. Prefer defusedxml when available,
# fall back to the stdlib if the dependency is missing so the engine still
# runs on minimal environments.
try:  # pragma: no cover - import guard
    from defusedxml.ElementTree import fromstring as _xml_fromstring
except ImportError:  # pragma: no cover - import fallback
    from xml.etree.ElementTree import fromstring as _xml_fromstring  # noqa: S405


APP_NAME = "SplunkEnterpriseSecuritySuite"
IDENTITY_APP = "SA-IdentityManagement"
THREAT_APP = "SA-ThreatIntelligence"
MISSION_CONTROL_APP = "missioncontrol"
AUDIT_APP = "SA-AuditAndDataProtection"
UTILS_APP = "SA-Utils"
CONTENT_UPDATE_APP = "DA-ESS-ContentUpdate"
CONTENT_LIBRARY_APP = "SA-ContentLibrary"
EXPOSURE_ANALYTICS_APP = "exposure-analytics"
CONTENT_UPDATE_APP_ID = "3449"
TA_FOR_INDEXERS_APP = "Splunk_TA_ForIndexers"
THREAT_UPLOAD_FORMATS = {"csv", "stix", "openioc"}
MAX_UPLOAD_BYTES = 100 * 1024 * 1024

TOP_LEVEL_SECTIONS = (
    "baseline",
    "indexes",
    "roles",
    "data_models",
    "assets",
    "identities",
    "threat_intel",
    "detections",
    "risk",
    "urgency",
    "adaptive_response",
    "notable_suppressions",
    "log_review",
    "review_statuses",
    "use_cases",
    "governance",
    "macros",
    "eventtypes",
    "tags",
    "navigation",
    "glass_tables",
    "workflow_actions",
    "kv_collections",
    "findings",
    "intelligence_management",
    "es_ai_settings",
    "dlx_settings",
    "exposure_analytics",
    "content_library",
    "mission_control",
    "integrations",
    "ta_for_indexers",
    "content_governance",
    "package_conf_coverage",
    "validation",
)

PACKAGE_CONF_CLASSIFICATION = {
    "alert_actions": ("adaptive_response", "Managed adaptive-response/action defaults."),
    "algos": ("inventory_only", "Bundled MLTK algorithm registry; do not rewrite from ES config."),
    "analyticstories": ("package_conf_coverage", "Analytic story packaging metadata; inventory/export only."),
    "app": ("install", "App metadata is handled by install workflows."),
    "app_permissions": ("package_conf_coverage", "ES app permission metadata; inventory/export only."),
    "audit": ("platform", "Splunk platform audit settings are outside ES config scope."),
    "authentication": ("platform", "Splunk platform authentication is outside ES config scope."),
    "authorize": ("roles", "Role management is handled through the roles section."),
    "cloud-connection": ("package_conf_coverage", "Splunk Cloud Connect tenant state; inventory/export only."),
    "cloud_integrations": ("integrations", "Stable non-secret values can be handled through integrations.local_conf."),
    "collections": ("kv_collections", "KV collection definitions are handled by kv_collections and inventory/export."),
    "commands": ("package_internal", "Search command registration is package-owned."),
    "content_packs": ("content_library", "Content Library packs are handled through content_library."),
    "content_versioning": ("content_governance", "Content Versioning state is handled through content_governance."),
    "correlationsearches": ("detections", "Correlation metadata is handled through detections.correlation_metadata."),
    "datamodels": ("data_models", "Data model acceleration/constraints are handled through data_models."),
    "distsearch": ("platform", "Distributed search settings are platform/runtime configuration."),
    "dlx_settings": ("dlx_settings", "DLX settings are handled through dlx_settings."),
    "entitlement_flags": ("package_conf_coverage", "Entitlement flags are inventory/export only."),
    "es_ai_settings": ("es_ai_settings", "ES AI settings are handled through es_ai_settings."),
    "es_investigations": ("package_conf_coverage", "Investigation workbench panel metadata; inventory/export only."),
    "escu_subscription": ("content_library", "ESCU subscription is handled through content_library."),
    "ess_setup": ("package_conf_coverage", "ES setup marker state; inventory/export only."),
    "essoar": ("integrations", "SOAR pairing/proxy state is secret/tenant controlled; inventory/export only."),
    "eventtypes": ("eventtypes", "Eventtypes are handled through eventtypes."),
    "experiments": ("package_internal", "MLTK experiment registry is package-owned."),
    "feature_flags": ("package_conf_coverage", "Feature flags are inventory/export only unless a supported public API exists."),
    "federated_analytics": ("package_conf_coverage", "Federated analytics state is inventory/export only."),
    "fields": ("package_internal", "Field aliases/extractions are package or TA content."),
    "findings": ("findings", "Findings settings are handled through findings."),
    "governance": ("governance", "Governance frameworks are handled through governance."),
    "im_settings": ("intelligence_management", "TIM Cloud tenant/proxy settings are inventory/export only; safe fields use intelligence_management."),
    "indexes": ("indexes", "Index creation is handled through indexes."),
    "infra": ("package_conf_coverage", "Mission Control infrastructure flags are inventory/export only."),
    "inputs": ("multiple", "Inputs are handled by assets, identities, threat_intel, data_models, and content_governance."),
    "intelligence_management": ("intelligence_management", "TIM Cloud settings are handled through intelligence_management."),
    "license_info": ("package_conf_coverage", "License/subscription state is inventory/export only."),
    "limits": ("baseline", "Baseline lookup ordering is handled through baseline."),
    "log_review": ("log_review", "Log review settings are handled through log_review."),
    "macros": ("macros", "Macros are handled through macros and data_models constraints."),
    "managed_configurations": ("package_conf_coverage", "ES managed-configuration registry metadata; inventory/export only."),
    "mc_checkpoints": ("package_conf_coverage", "Mission Control checkpoint internals; inventory/export only."),
    "mc_configuration_editor": ("package_conf_coverage", "Mission Control configuration editor metadata; inventory/export only."),
    "mc_data_migration_task": ("package_conf_coverage", "Mission Control migration internals; inventory/export only."),
    "mc_database": ("package_conf_coverage", "Mission Control database internals; inventory/export only."),
    "mc_rate_limit": ("package_conf_coverage", "Mission Control rate limits; inventory/export only."),
    "mc_sa_spl_context": ("package_conf_coverage", "Mission Control SPL context internals; inventory/export only."),
    "mc_search": (
        "package_conf_coverage",
        "Mission Control search internals are inventory/export only except workload_pool via mission_control.search.",
    ),
    "mc_setup_task": ("package_conf_coverage", "Mission Control setup task internals; inventory/export only."),
    "messages": ("package_internal", "UI message metadata is package-owned."),
    "mlspl": ("package_internal", "MLTK command metadata is package-owned."),
    "nav": ("navigation", "Navigation is handled through data/ui/nav."),
    "notable_suppressions": ("notable_suppressions", "Notable suppressions are handled through notable_suppressions."),
    "ocsf_cim_addon_for_splunk": ("package_conf_coverage", "OCSF CIM add-on metadata; inventory/export only."),
    "outputs": ("platform", "Forwarding outputs are platform/runtime configuration."),
    "passwords": ("forbidden", "Secret storage is never exported or managed by this workflow."),
    "pre_es_convergence_conversion": ("package_conf_coverage", "Migration/convergence metadata; inventory/export only."),
    "props": ("ta_content", "Props are TA/package content and not safe ES declarative config in v1."),
    "restmap": ("package_internal", "REST handler registration is package-owned."),
    "reviewstatuses": ("review_statuses", "Review statuses are handled through review_statuses/log_review."),
    "risk_factors": ("risk", "Risk factors are handled through risk."),
    "savedsearches": ("detections", "Saved searches are handled through detections, risk, and content_library."),
    "scorings": ("package_internal", "MLTK scoring metadata is package-owned."),
    "searchbnf": ("package_internal", "Search syntax help metadata is package-owned."),
    "sequence_templates": ("package_conf_coverage", "Sequence templates are inventory/export only."),
    "server": ("platform", "Splunk server/runtime settings are outside ES config scope."),
    "splunk_create": ("package_internal", "Splunk create UI metadata is package-owned."),
    "tags": ("tags", "Field-value tags are handled through tags."),
    "times": ("package_internal", "Time picker metadata is package-owned."),
    "transforms": ("assets", "Lookup definitions are handled through assets/identities; TA transforms remain package content."),
    "uba": ("integrations", "UEBA REST connection state is inventory/export only; non-secret local config uses integrations."),
    "udf_dashboard_mapping": ("package_conf_coverage", "Dashboard mapping metadata; inventory/export only."),
    "ueba_px": ("integrations", "UEBA feature/proxy state is inventory/export only."),
    "ui-tour": ("package_internal", "UI tour metadata is package-owned."),
    "user-prefs": ("mission_control", "Mission Control preferences can be handled through mission_control.settings."),
    "viewstates": ("user_state", "Per-user view state is not managed."),
    "visualizations": ("package_internal", "Visualization registration is package-owned."),
    "web": ("platform", "Web/runtime settings are outside ES config scope."),
    "workflow_actions": ("workflow_actions", "Workflow actions are handled through workflow_actions."),
}

_PACKAGE_CONF_MANIFEST_CACHE: dict[tuple[str, int], dict[str, Any]] = {}

INDEX_GROUPS = {
    "core": (
        "audit_summary",
        "ba_test",
        "cim_modactions",
        "cms_main",
        "endpoint_summary",
        "gia_summary",
        "ioc",
        "notable",
        "notable_summary",
        "risk",
        "sequenced_events",
        "threat_activity",
        "whois",
    ),
    "ueba": ("ers", "ueba_summaries", "ubaroute", "ueba"),
    "pci": ("pci", "pci_posture_summary", "pci_summary"),
    "exposure": ("ea_sources", "ea_discovery", "ea_analytics"),
    "mission_control": (
        "mc_aux_incidents",
        "mc_artifacts",
        "mc_investigations",
        "mc_events",
        "mc_incidents_backup",
        "kvcollection_retention_archive",
    ),
    "dlx": ("dlx_confidence", "dlx_kpi"),
}

INTEGRATION_APPS = {
    "soar": ("missioncontrol", "SplunkEnterpriseSecuritySuite"),
    "attack_analyzer": ("missioncontrol", "SplunkEnterpriseSecuritySuite"),
    "tim_cloud": ("missioncontrol", "SplunkEnterpriseSecuritySuite"),
    "behavioral_analytics": ("DA-ESS-UEBA", "Splunk_TA_ueba"),
    "ueba": ("DA-ESS-UEBA", "Splunk_TA_ueba"),
    "splunk_cloud_connect": ("splunk_cloud_connect",),
}

SECRET_FILE_KEYS = (
    "secret_file",
    "password_file",
    "token_file",
    "cert_bundle_file",
    "client_secret_file",
    "certificate_file",
)

INTEGRATION_PREFLIGHT_ENDPOINTS = {
    "soar": "/servicesNS/nobody/missioncontrol/configs/conf-essoar?count=0",
    "attack_analyzer": "/servicesNS/nobody/missioncontrol/configs/conf-cloud_integrations?count=0",
    "tim_cloud": "/servicesNS/nobody/missioncontrol/configs/conf-intelligence_management?count=0",
    "behavioral_analytics": "/servicesNS/nobody/SplunkEnterpriseSecuritySuite/configs/conf-cloud_integrations?count=0",
    "ueba": "/servicesNS/nobody/SplunkEnterpriseSecuritySuite/configs/conf-cloud_integrations?count=0",
    "splunk_cloud_connect": "/servicesNS/nobody/splunk_cloud_connect/configs/conf-cloud-connection?count=0",
}

INTEGRATION_DOC_HINTS = {
    "soar": "Pairing is a UI/operator workflow: validate SOAR host reachability, role capability readiness, and file-based certificate inputs first.",
    "attack_analyzer": "Attack Analyzer tenant setup is licensed/tenant controlled; validate app presence and non-secret settings before handoff.",
    "tim_cloud": "TIM Cloud pairing and tenant secrets remain file-only handoffs; safe subscription fields are handled by intelligence_management.",
    "splunk_cloud_connect": "Splunk Cloud Connect access is tenant controlled; use this preflight as evidence before completing the UI/Support path.",
}

MISSION_CONTROL_PRIVATE_ALLOWLIST = {
    ("mc_search", "aq_sid_caching", "workload_pool"),
}

EXTENDED_INVENTORY_ENDPOINTS = {
    "urgency": (THREAT_APP, "/servicesNS/nobody/{app}/configs/conf-urgency?count=0"),
    "adaptive_response": (APP_NAME, "/servicesNS/nobody/{app}/configs/conf-alert_actions?count=0"),
    "notable_suppressions": (THREAT_APP, "/servicesNS/nobody/{app}/configs/conf-notable_suppressions?count=0"),
    "log_review": (APP_NAME, "/servicesNS/nobody/{app}/configs/conf-log_review?count=0"),
    "use_cases": (UTILS_APP, "/servicesNS/nobody/{app}/configs/conf-use_cases?count=0"),
    "governance": (AUDIT_APP, "/servicesNS/nobody/{app}/configs/conf-governance?count=0"),
    "macros": (APP_NAME, "/servicesNS/nobody/{app}/admin/macros?count=0"),
    "eventtypes": (APP_NAME, "/servicesNS/nobody/{app}/saved/eventtypes?count=0"),
    "tags": (APP_NAME, "/servicesNS/nobody/{app}/saved/fvtags?count=0"),
    "navigation": (APP_NAME, "/servicesNS/nobody/{app}/data/ui/nav?count=0"),
    "glass_tables": (APP_NAME, "/servicesNS/nobody/{app}/data/ui/views?count=0"),
}

MISSION_CONTROL_ENDPOINTS = {
    "queues": "/servicesNS/nobody/missioncontrol/v2/queues?count=0",
    "response_templates": "/servicesNS/nobody/missioncontrol/v1/responsetemplates?count=0",
    "response_plans": "/servicesNS/nobody/missioncontrol/v2/responseplans?count=0",
    "incident_types": "/servicesNS/nobody/missioncontrol/v2/incidenttypes?count=0",
    "investigation_types": "/servicesNS/nobody/missioncontrol/v2/investigationtypes?count=0",
}


class EsConfigError(RuntimeError):
    pass


class HandoffRequired(EsConfigError):
    pass


def handoff_payload(
    reason: str,
    *,
    required_inputs: list[str] | None = None,
    safe_next_command: str | None = None,
    docs_hint: str | None = None,
    blocking_secret_files: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"reason": reason}
    if required_inputs:
        payload["required_inputs"] = required_inputs
    if safe_next_command:
        payload["safe_next_command"] = safe_next_command
    if docs_hint:
        payload["docs_hint"] = docs_hint
    if blocking_secret_files:
        payload["blocking_secret_files"] = blocking_secret_files
    payload.update({key: value for key, value in extra.items() if value is not None})
    return payload


def stable_confirm_id(kind: str, target: str, payload: dict[str, Any] | None = None) -> str:
    material = {
        "kind": kind,
        "target": target,
        "payload": sanitize_live_value(payload or {}),
    }
    digest = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"{kind}:{digest[:16]}"


def without_guard_fields(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: child
        for key, child in value.items()
        if key
        not in {
            "apply",
            "backup_export",
            "confirm_id",
            "confirm",
            "handoff",
            "private_override",
            "safe_next_command",
            "docs_hint",
            "required_inputs",
            "blocking_secret_files",
        }
    }


def secret_file_paths(value: Any) -> list[dict[str, str]]:
    paths: list[dict[str, str]] = []

    def visit(child: Any, context: str = "") -> None:
        if isinstance(child, dict):
            for key, nested in child.items():
                lowered = str(key).lower()
                if lowered in SECRET_FILE_KEYS and isinstance(nested, str) and nested.strip():
                    paths.append({"key": context + str(key), "path": nested.strip()})
                elif lowered == "secret_files":
                    if isinstance(nested, dict):
                        for file_key, file_path in nested.items():
                            if isinstance(file_path, str) and file_path.strip():
                                paths.append({"key": context + str(file_key), "path": file_path.strip()})
                    elif isinstance(nested, list):
                        for index, file_path in enumerate(nested):
                            if isinstance(file_path, str) and file_path.strip():
                                paths.append({"key": f"{context}secret_files[{index}]", "path": file_path.strip()})
                    elif isinstance(nested, str) and nested.strip():
                        paths.append({"key": context + str(key), "path": nested.strip()})
                else:
                    visit(nested, context + str(key) + ".")
        elif isinstance(child, list):
            for index, nested in enumerate(child):
                visit(nested, f"{context}[{index}].")

    visit(value)
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in paths:
        marker = (item["key"], item["path"])
        if marker not in seen:
            deduped.append(item)
            seen.add(marker)
    return deduped


def secret_file_checks(value: Any, base: Path | None = None) -> list[dict[str, Any]]:
    checks = []
    for item in secret_file_paths(value):
        declared_path = item["path"]
        resolved = resolve_local_path(declared_path, base)
        check: dict[str, Any] = {
            "key": item["key"],
            "path": declared_path,
            "exists": resolved.exists(),
            "is_file": resolved.is_file(),
        }
        if resolved.exists():
            mode = stat.S_IMODE(resolved.stat().st_mode)
            check["mode"] = oct(mode)
            check["secure_permissions"] = (mode & 0o077) == 0
        else:
            check["secure_permissions"] = False
        checks.append(check)
    return checks


def boolish(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False
    return bool(value)


def listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def comma_join(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


def comma_list(value: Any) -> list[Any]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return listify(value)


def splunk_bool(value: Any) -> str:
    return "1" if boolish(value) else "0"


def spec_platform(spec: dict[str, Any]) -> str:
    connection = spec.get("connection") if isinstance(spec.get("connection"), dict) else {}
    return str(connection.get("platform") or connection.get("deployment") or "").strip().lower()


def content_library_app_id(section: dict[str, Any], app: str) -> str | None:
    aliases = {
        CONTENT_UPDATE_APP: ("content_update", "escu", CONTENT_UPDATE_APP),
        CONTENT_LIBRARY_APP: ("content_library", CONTENT_LIBRARY_APP),
    }
    app_ids = section.get("app_ids") if isinstance(section.get("app_ids"), dict) else {}
    for key in aliases.get(app, (app,)):
        value = app_ids.get(key)
        if value:
            return str(value)
    if app == CONTENT_UPDATE_APP:
        return CONTENT_UPDATE_APP_ID
    return None


def resolve_local_path(path: str, base: Path | None = None) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    roots = []
    if base is not None:
        roots.append(base)
    roots.append(Path.cwd())
    for root in roots:
        resolved = (root / candidate).resolve()
        if resolved.exists():
            return resolved
    return (roots[0] / candidate).resolve()


def local_file_exists(path: str) -> bool:
    if not path:
        return False
    return resolve_local_path(path).is_file()


_SECRET_LITERAL_PATTERNS = (
    re.compile(r"(?i)\bpassword\s*[:=]\s*['\"]?[^\s'\"<>]{3,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|apikey|auth[_-]?token|bearer|session[_-]?key|client[_-]?secret)\s*[:=]\s*['\"]?[^\s'\"<>]{6,}"),
    re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    re.compile(r"(?i)aws_secret_access_key\s*[:=]"),
)


def _looks_like_secret(text: str) -> bool:
    if not isinstance(text, str):
        return False
    return any(pattern.search(text) for pattern in _SECRET_LITERAL_PATTERNS)


def read_spec(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    spec_path = Path(path)
    raw = spec_path.read_text(encoding="utf-8")
    if spec_path.suffix.lower() == ".json":
        loaded = json.loads(raw)
    else:
        loaded = load_yaml(raw)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise EsConfigError("ES config spec must be a mapping at the top level.")
    assert_no_inline_secrets(loaded)
    return loaded


def load_yaml(raw: str) -> Any:
    try:
        import yaml  # type: ignore

        return yaml.safe_load(raw)
    except ModuleNotFoundError:
        pass

    try:
        completed = subprocess.run(
            [
                "ruby",
                "-ryaml",
                "-rjson",
                "-e",
                "puts JSON.generate(YAML.safe_load(STDIN.read, aliases: true) || {})",
            ],
            input=raw,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise EsConfigError(
            "YAML specs require PyYAML or Ruby's yaml/json libraries. "
            "Install requirements-dev.txt or provide JSON. "
            f"Details: {detail}"
        ) from exc
    return json.loads(completed.stdout or "{}")


def normalize_spec(spec: dict[str, Any]) -> dict[str, Any]:
    # Defense-in-depth: re-check for inline secrets on every normalization pass so
    # programmatic callers that construct Runner/PlanBuilder from a raw dict cannot
    # bypass the file-level check performed by read_spec().
    assert_no_inline_secrets(spec)
    normalized = {section: spec.get(section, {}) for section in TOP_LEVEL_SECTIONS}
    extras = sorted(key for key in spec if key not in TOP_LEVEL_SECTIONS and key != "connection")
    if extras:
        normalized["_unknown_sections"] = extras
    if "connection" in spec:
        connection = spec["connection"]
        if not isinstance(connection, dict):
            raise EsConfigError("connection must be a mapping when provided.")
        forbidden = sorted(
            key
            for key in connection
            if any(secret_word in key.lower() for secret_word in ("pass", "password", "secret", "token", "session"))
        )
        if forbidden:
            raise EsConfigError(
                "Do not put Splunk passwords, tokens, session keys, or secrets in ES config specs. "
                "Use the repo credentials file or secret-file handoff instead. "
                f"Forbidden connection keys: {', '.join(forbidden)}"
            )
        normalized["connection"] = dict(connection)
    return normalized


def assert_no_inline_secrets(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            lowered = str(key).lower()
            secret_like = any(word in lowered for word in ("pass", "password", "secret", "token", "api_key", "session"))
            file_reference = lowered.endswith("_file") or lowered.endswith("_path") or lowered in {"secret_files"}
            if secret_like and not file_reference:
                raise EsConfigError(
                    "ES config specs must not contain inline passwords, tokens, session keys, API keys, or secrets. "
                    f"Use a secret-file path instead of {child_path}."
                )
            assert_no_inline_secrets(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_inline_secrets(child, f"{path}[{index}]")


def named_items(value: Any, default_key: str = "name") -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if value is None:
        return items
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, dict):
                item = dict(child)
            else:
                item = {"value": child}
            item.setdefault(default_key, key)
            items.append(item)
        return items
    if isinstance(value, list):
        for child in value:
            if isinstance(child, dict):
                items.append(dict(child))
            else:
                items.append({default_key: str(child)})
        return items
    return [{default_key: str(value)}]


@dataclass
class Action:
    section: str
    operation: str
    target: str
    app: str | None = None
    endpoint: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    apply_supported: bool = True
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Diagnostic:
    level: str
    section: str
    message: str
    target: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PlanBuilder:
    def __init__(self, spec: dict[str, Any], project_root: Path | None = None, *, strict: bool = False):
        self.spec = normalize_spec(spec)
        self.project_root = project_root or Path.cwd()
        self.actions: list[Action] = []
        self.diagnostics: list[Diagnostic] = []
        # Strict mode escalates `_unknown_sections` warnings into hard errors
        # so a typo like `valdation:` (missing 'i') fails fast instead of
        # silently dropping the section.
        self.strict = bool(strict)

    def build(self) -> dict[str, Any]:
        self._warn_unknown_sections()
        self._baseline()
        self._indexes()
        self._roles()
        self._data_models()
        self._assets_or_identities("assets", "asset")
        self._assets_or_identities("identities", "identity")
        self._threat_intel()
        self._detections()
        self._risk()
        self._urgency()
        self._adaptive_response()
        self._notable_suppressions()
        self._log_review()
        self._review_statuses()
        self._use_cases()
        self._governance()
        self._macros()
        self._eventtypes()
        self._tags()
        self._navigation()
        self._glass_tables()
        self._workflow_actions()
        self._kv_collections()
        self._findings()
        self._intelligence_management()
        self._es_ai_settings()
        self._dlx_settings()
        self._exposure_analytics()
        self._content_library()
        self._mission_control()
        self._integrations()
        self._ta_for_indexers()
        self._content_governance()
        self._package_conf_coverage()
        self._validation()
        supported = sum(1 for action in self.actions if action.apply_supported)
        return {
            "summary": {
                "actions": len(self.actions),
                "apply_supported": supported,
                "handoff": len(self.actions) - supported,
                "diagnostics": len(self.diagnostics),
            },
            "normalized_spec": self.spec,
            "actions": [action.as_dict() for action in self.actions],
            "diagnostics": [diagnostic.as_dict() for diagnostic in self.diagnostics],
        }

    def _add(self, action: Action) -> None:
        self.actions.append(action)

    def _diag(self, level: str, section: str, message: str, target: str | None = None) -> None:
        self.diagnostics.append(Diagnostic(level=level, section=section, message=message, target=target))

    def _warn_unknown_sections(self) -> None:
        unknown = list(self.spec.get("_unknown_sections", []) or [])
        if not unknown:
            return
        if self.strict:
            joined = ", ".join(sorted(unknown))
            raise EsConfigError(
                f"Strict mode: spec contains unknown top-level section(s): {joined}. "
                "Remove the unknown key(s) or rerun without --strict."
            )
        for section in unknown:
            self._diag("warn", section, "Unknown top-level spec section will be ignored.")

    def _baseline(self) -> None:
        baseline = self.spec.get("baseline")
        if not baseline:
            return
        if isinstance(baseline, bool):
            baseline = {"enabled": baseline}
        if not isinstance(baseline, dict):
            self._diag("error", "baseline", "baseline must be a boolean or mapping.")
            return
        if not boolish(baseline.get("enabled"), default=True):
            return
        if boolish(baseline.get("lookup_order"), default=True):
            self._add(
                Action(
                    section="baseline",
                    operation="set_global_conf",
                    target="limits/lookup",
                    endpoint="/services/configs/conf-limits/lookup",
                    payload={"enforce_auto_lookup_order": "true"},
                )
            )
        managed_roles = baseline.get("managed_roles")
        if managed_roles is None:
            managed_roles = ["ess_analyst", "ess_user"]
        self._add(
            Action(
                section="baseline",
                operation="set_conf",
                target="app_permissions_manager://enforce_es_permissions",
                app=APP_NAME,
                endpoint=f"/servicesNS/nobody/{APP_NAME}/configs/conf-inputs/app_permissions_manager%3A%2F%2Fenforce_es_permissions",
                payload={"managed_roles": comma_join(managed_roles), "disabled": "0"},
            )
        )
        if boolish(baseline.get("all_indexes")):
            self._add_index_groups(tuple(INDEX_GROUPS))

    def _indexes(self) -> None:
        indexes = self.spec.get("indexes") or {}
        if not indexes:
            return
        if isinstance(indexes, list):
            for item in named_items(indexes):
                self._add_custom_index(item)
            return
        if not isinstance(indexes, dict):
            self._diag("error", "indexes", "indexes must be a mapping or list.")
            return
        if boolish(indexes.get("all")):
            self._add_index_groups(tuple(INDEX_GROUPS))
        groups = indexes.get("groups") or indexes.get("create_groups") or []
        self._add_index_groups(tuple(str(group) for group in listify(groups)))
        for group in INDEX_GROUPS:
            if boolish(indexes.get(group)):
                self._add_index_groups((group,))
        for item in named_items(indexes.get("custom")):
            self._add_custom_index(item)

    def _add_index_groups(self, groups: tuple[str, ...]) -> None:
        for group in groups:
            if group not in INDEX_GROUPS:
                self._diag("warn", "indexes", "Unknown index group ignored.", group)
                continue
            for index_name in INDEX_GROUPS[group]:
                self._add(
                    Action(
                        section="indexes",
                        operation="create_index",
                        target=index_name,
                        endpoint="/services/data/indexes",
                        payload={"name": index_name, "datatype": "event", "group": group},
                    )
                )

    def _add_custom_index(self, item: dict[str, Any]) -> None:
        name = str(item.get("name") or "").strip()
        if not name:
            self._diag("error", "indexes", "Custom index entry is missing name.")
            return
        payload = {
            "name": name,
            "datatype": str(item.get("datatype") or "event"),
            "maxTotalDataSizeMB": str(item.get("max_size_mb") or item.get("maxTotalDataSizeMB") or "512000"),
        }
        self._add(Action(section="indexes", operation="create_index", target=name, endpoint="/services/data/indexes", payload=payload))

    def _roles(self) -> None:
        roles = self.spec.get("roles")
        for role in named_items(roles):
            name = str(role.get("name") or "").strip()
            if not name:
                self._diag("error", "roles", "Role entry is missing name.")
                continue
            payload: dict[str, Any] = {}
            mapping = {
                "allowed_indexes": "srchIndexesAllowed",
                "default_indexes": "srchIndexesDefault",
                "import_roles": "importRoles",
                "capabilities": "capabilities",
                "search_disk_quota": "srchDiskQuota",
                "search_jobs_quota": "srchJobsQuota",
            }
            for source, dest in mapping.items():
                if source in role:
                    payload[dest] = role[source]
            if not payload:
                self._diag("warn", "roles", "Role has no managed fields.", name)
                continue
            self._add(
                Action(
                    section="roles",
                    operation="set_role",
                    target=name,
                    endpoint=f"/services/admin/roles/{quote(name, safe='')}",
                    payload=payload,
                )
            )

    def _data_models(self) -> None:
        section = self.spec.get("data_models")
        for model in named_items(section):
            name = str(model.get("name") or "").strip().replace(" ", "_")
            if not name:
                self._diag("error", "data_models", "Data model entry is missing name.")
                continue
            if "acceleration" in model or "enabled" in model:
                enabled = model.get("acceleration", model.get("enabled"))
                stanza = f"dm_accel_settings://{name}"
                self._add(
                    Action(
                        section="data_models",
                        operation="set_conf",
                        target=stanza,
                        app=APP_NAME,
                        endpoint=f"/servicesNS/nobody/{APP_NAME}/configs/conf-inputs/{quote(stanza, safe='')}",
                        payload={"acceleration": "true" if boolish(enabled) else "false", "disabled": "0"},
                    )
                )
            constraint = model.get("constraint") or {}
            if isinstance(constraint, dict) and constraint.get("macro"):
                macro = str(constraint["macro"])
                definition = constraint.get("definition")
                if definition is None and constraint.get("indexes"):
                    definition = " OR ".join(f"index={idx}" for idx in listify(constraint["indexes"]))
                if definition:
                    self._add(
                        Action(
                            section="data_models",
                            operation="set_macro",
                            target=macro,
                            app=constraint.get("app") or "Splunk_SA_CIM",
                            endpoint=f"/servicesNS/nobody/{constraint.get('app') or 'Splunk_SA_CIM'}/admin/macros/{quote(macro, safe='')}",
                            payload={"definition": str(definition)},
                        )
                    )
                else:
                    self._diag("warn", "data_models", "Constraint macro declared without definition or indexes.", name)
            elif constraint:
                self._add(
                    Action(
                        section="data_models",
                        operation="handoff",
                        target=name,
                        apply_supported=False,
                        reason="Data model constraints require an explicit macro and definition to avoid unsafe CIM rewrites.",
                    )
                )

    def _assets_or_identities(self, section_name: str, target_type: str) -> None:
        for source in named_items(self.spec.get(section_name)):
            name = str(source.get("name") or "").strip()
            if not name:
                self._diag("error", section_name, f"{target_type} source is missing name.")
                continue
            lookup_definition = source.get("lookup_definition")
            if lookup_definition:
                payload = {"filename": str(source.get("lookup_file") or lookup_definition)}
                if source.get("fields_list"):
                    payload["fields_list"] = comma_join(source["fields_list"])
                self._add(
                    Action(
                        section=section_name,
                        operation="set_lookup_definition",
                        target=str(lookup_definition),
                        app=source.get("app") or IDENTITY_APP,
                        endpoint=f"/servicesNS/nobody/{source.get('app') or IDENTITY_APP}/configs/conf-transforms/{quote(str(lookup_definition), safe='')}",
                        payload=payload,
                    )
                )
            if source.get("lookup_file"):
                self._lookup_file_action(section_name, target_type, source, lookup_definition)
            self._asset_identity_generating_search(section_name, target_type, source, lookup_definition)
            manager_payload = {
                "category": source.get("category") or name,
                "description": source.get("description") or f"Managed {target_type} source {name}",
                "disabled": splunk_bool(not boolish(source.get("enabled"), default=False)),
                "target": target_type,
                "rank": str(source.get("rank") or "1"),
            }
            if source.get("url"):
                manager_payload["url"] = str(source["url"])
            elif lookup_definition:
                manager_payload["url"] = f"lookup://{lookup_definition}"
            else:
                self._diag("warn", section_name, "Source has no url or lookup_definition.", name)
            self._add(
                Action(
                    section=section_name,
                    operation="set_conf",
                    target=f"identity_manager://{name}",
                    app=IDENTITY_APP,
                    endpoint=f"/servicesNS/nobody/{IDENTITY_APP}/configs/conf-inputs/{quote('identity_manager://' + name, safe='')}",
                    payload=manager_payload,
                )
            )

    def _asset_identity_generating_search(
        self,
        section_name: str,
        target_type: str,
        source: dict[str, Any],
        lookup_definition: Any,
    ) -> None:
        generator = (
            source.get("generating_search")
            or source.get("search_driven_lookup")
        )
        builder_type = ""
        if isinstance(source.get("ldap"), dict) or boolish(source.get("ldap"), default=False):
            builder_type = "ldap"
        if isinstance(source.get("cloud_service_provider"), dict) or isinstance(source.get("cloud_provider"), dict):
            builder_type = "cloud_service_provider"
        if not generator:
            if builder_type:
                reason = (
                    f"{target_type.title()} {builder_type} registration requires the builder-generated SPL "
                    "or an explicit generating_search.search value."
                )
                self._add(
                    Action(
                        section=section_name,
                        operation="search_builder_handoff",
                        target=str(source.get("name") or lookup_definition or target_type),
                        app=source.get("app") or IDENTITY_APP,
                        payload=handoff_payload(
                            reason,
                            required_inputs=[
                                "generating_search.search",
                                "lookup_definition",
                                "lookup_file",
                                "cron_schedule",
                            ],
                            docs_hint=(
                                "ES Asset and Identity Builder saves a scheduled search, lookup table file, "
                                "lookup definition, and identity-manager input. Provide explicit SPL to automate it."
                            ),
                            builder_type=builder_type,
                        ),
                        apply_supported=False,
                        reason=reason,
                    )
                )
            return
        generator_body = generator if isinstance(generator, dict) else {"search": generator}
        search = str(generator_body.get("search") or "").strip()
        search_name = str(
            generator_body.get("name")
            or generator_body.get("search_name")
            or f"{source.get('name') or lookup_definition} - Generate {target_type.title()} Lookup"
        ).strip()
        if not search_name:
            self._diag("error", section_name, f"{target_type.title()} generating search is missing name.", str(source.get("name") or ""))
            return
        if not search:
            self._diag("error", section_name, f"{target_type.title()} generating search requires explicit SPL.", search_name)
            return
        if "outputlookup" not in search.lower():
            self._diag(
                "warn",
                section_name,
                "Generating search does not contain outputlookup; ensure it writes the declared lookup file.",
                search_name,
            )
        payload: dict[str, Any] = {
            "search": search,
            "disabled": splunk_bool(not boolish(generator_body.get("enabled"), default=False)),
        }
        cron = generator_body.get("cron_schedule") or generator_body.get("schedule")
        if cron:
            payload["cron_schedule"] = str(cron)
            payload["is_scheduled"] = "1"
        for source_key, dest_key in (
            ("description", "description"),
            ("dispatch_earliest_time", "dispatch.earliest_time"),
            ("dispatch_latest_time", "dispatch.latest_time"),
            ("schedule_window", "schedule_window"),
            ("schedule_priority", "schedule_priority"),
            ("realtime_schedule", "realtime_schedule"),
        ):
            if source_key in generator_body:
                value = generator_body[source_key]
                payload[dest_key] = splunk_bool(value) if isinstance(value, bool) else str(value)
        app = str(generator_body.get("app") or source.get("app") or IDENTITY_APP)
        self._add(
            Action(
                section=section_name,
                operation="create_saved_search",
                target=search_name,
                app=app,
                endpoint=f"/servicesNS/nobody/{app}/saved/searches/{quote(search_name, safe='')}",
                payload=payload,
            )
        )

    def _lookup_file_action(
        self,
        section_name: str,
        target_type: str,
        source: dict[str, Any],
        lookup_definition: Any,
    ) -> None:
        lookup_file = str(source.get("lookup_file") or "").strip()
        app = str(source.get("app") or IDENTITY_APP)
        upload_spec = source.get("lookup_upload")
        if upload_spec is None:
            upload_spec = source.get("upload_lookup")
        if upload_spec is None:
            upload_spec = source.get("upload")
        upload_body = upload_spec if isinstance(upload_spec, dict) else {}
        upload_requested = (
            boolish(upload_spec)
            if not isinstance(upload_spec, dict)
            else boolish(upload_spec.get("apply") or upload_spec.get("enabled") or upload_spec.get("upload"), default=False)
        )
        file_path = str(upload_body.get("path") or upload_body.get("file") or source.get("file") or lookup_file)
        filename = str(upload_body.get("filename") or lookup_file or Path(file_path).name)
        acl = upload_body.get("acl") if isinstance(upload_body.get("acl"), dict) else source.get("acl")
        definition_acl = upload_body.get("definition_acl") if isinstance(upload_body.get("definition_acl"), dict) else source.get("definition_acl")
        reason = "Upload or package lookup files through a deployment app or supported lookup-file upload workflow."
        handoff = handoff_payload(
            reason,
            required_inputs=["lookup_upload.apply: true", "local lookup CSV path", "target lookup filename"],
            docs_hint="Use lookup_upload.apply only for non-secret CSV lookup files; exported specs never include file contents.",
            lookup_file=filename,
            target_type=target_type,
        )
        if spec_platform(self.spec) == "cloud":
            self._add(
                Action(
                    section=section_name,
                    operation="lookup_file_handoff",
                    target=filename,
                    app=app,
                    payload=handoff_payload(
                        "Splunk Cloud lookup-file deployment can be app-package or support controlled; hand off file placement.",
                        required_inputs=["deployment app package or supported Cloud lookup upload path"],
                        docs_hint="Keep CSV contents out of exported specs and logs.",
                        lookup_file=filename,
                        target_type=target_type,
                    ),
                    apply_supported=False,
                    reason="Splunk Cloud lookup-file deployment can be app-package or support controlled; hand off file placement.",
                )
            )
            return
        if not upload_requested:
            self._add(
                Action(
                    section=section_name,
                    operation="lookup_file_handoff",
                    target=filename,
                    app=app,
                    payload=handoff,
                    apply_supported=False,
                    reason=reason,
                )
            )
            return
        if not local_file_exists(file_path):
            missing_reason = "Lookup upload was requested but the local file was not found; hand off packaging or fix the path."
            self._add(
                Action(
                    section=section_name,
                    operation="lookup_file_handoff",
                    target=filename,
                    app=app,
                    payload=handoff_payload(
                        missing_reason,
                        required_inputs=[file_path],
                        docs_hint="Paths are resolved relative to the current working directory unless absolute.",
                        lookup_file=filename,
                        target_type=target_type,
                    ),
                    apply_supported=False,
                    reason=missing_reason,
                )
            )
            return
        payload: dict[str, Any] = {
            "file": file_path,
            "filename": filename,
            "lookup_definition": str(lookup_definition or ""),
            "target_type": target_type,
        }
        if isinstance(acl, dict):
            payload["acl"] = acl
        if isinstance(definition_acl, dict):
            payload["definition_acl"] = definition_acl
        self._add(
            Action(
                section=section_name,
                operation="upload_lookup_file",
                target=filename,
                app=app,
                endpoint=f"/servicesNS/nobody/{app}/data/lookup-table-files/{quote(filename, safe='')}",
                payload=payload,
            )
        )

    def _threat_intel(self) -> None:
        section = self.spec.get("threat_intel") or {}
        if not isinstance(section, dict):
            self._diag("error", "threat_intel", "threat_intel must be a mapping.")
            return
        for feed in named_items(section.get("threatlists") or section.get("feeds")):
            name = str(feed.get("name") or "").strip()
            if not name:
                self._diag("error", "threat_intel", "Threat list is missing name.")
                continue
            payload = {
                "disabled": splunk_bool(not boolish(feed.get("enabled"), default=False)),
                "type": str(feed.get("type") or "threatlist"),
                "url": str(feed.get("url") or ""),
                "interval": str(feed.get("interval") or "43200"),
                "is_threatintel": splunk_bool(feed.get("is_threatintel", True)),
                "weight": str(feed.get("weight") or "60"),
            }
            for key in ("fields", "description", "post_process", "workloads"):
                if key in feed:
                    payload[key] = feed[key] if isinstance(feed[key], str) else json.dumps(feed[key])
            self._add(
                Action(
                    section="threat_intel",
                    operation="set_conf",
                    target=f"threatlist://{name}",
                    app=THREAT_APP,
                    endpoint=f"/servicesNS/nobody/{THREAT_APP}/configs/conf-inputs/{quote('threatlist://' + name, safe='')}",
                    payload=payload,
                )
            )
        for upload in named_items(section.get("uploads")):
            name = str(upload.get("name") or upload.get("file") or "").strip()
            self._threat_intel_upload(upload, name)
        if boolish(section.get("tim_cloud")):
            self._add(
                Action(
                    section="threat_intel",
                    operation="integration_readiness",
                    target="tim_cloud",
                    payload=handoff_payload(
                        "TIM Cloud pairing is tenant-controlled; validate readiness and hand off pairing steps.",
                        required_inputs=["TIM Cloud tenant", "pairing status"],
                        docs_hint="Tenant pairing and OAuth material remain outside this declarative spec.",
                    ),
                    apply_supported=False,
                    reason="TIM Cloud pairing is tenant-controlled; validate readiness and hand off pairing steps.",
                )
            )

    def _threat_intel_upload(self, upload: dict[str, Any], name: str) -> None:
        upload_format = str(upload.get("format") or "").strip().lower()
        file_path = str(upload.get("file") or upload.get("path") or "").strip()
        apply_requested = boolish(upload.get("apply") or upload.get("enabled") or upload.get("upload"), default=False)
        target = name or Path(file_path).name
        reason = "Threat-intel file upload requires explicit apply intent plus a supported local CSV, STIX, or OpenIOC file."
        payload = {
            key: value
            for key, value in upload.items()
            if key not in {"name", "reason", "required_inputs", "safe_next_command", "docs_hint", "blocking_secret_files"}
        }
        payload.setdefault("format", upload_format)
        if spec_platform(self.spec) == "cloud":
            self._add(
                Action(
                    section="threat_intel",
                    operation="threat_intel_upload",
                    target=target,
                    app=THREAT_APP,
                    endpoint=f"/servicesNS/nobody/{THREAT_APP}/data/threat_intel/upload",
                    payload=handoff_payload(
                        "Splunk Cloud threat-intel file upload may be support or app-package controlled; hand off file placement.",
                        required_inputs=["supported Cloud upload path or packaged lookup/intel app"],
                        docs_hint="Do not inline IOC file contents in the spec.",
                        **payload,
                    ),
                    apply_supported=False,
                    reason="Splunk Cloud threat-intel file upload may be support or app-package controlled; hand off file placement.",
                )
            )
            return
        if not apply_requested:
            self._add(
                Action(
                    section="threat_intel",
                    operation="threat_intel_upload",
                    target=target,
                    app=THREAT_APP,
                    endpoint=f"/servicesNS/nobody/{THREAT_APP}/data/threat_intel/upload",
                    payload=handoff_payload(
                        reason,
                        required_inputs=["uploads[].apply: true", "file", "format: csv|stix|openioc"],
                        docs_hint="Use apply only after validating local IOC file provenance and format.",
                        **payload,
                    ),
                    apply_supported=False,
                    reason=reason,
                )
            )
            return
        if upload_format not in THREAT_UPLOAD_FORMATS:
            bad_format_reason = "Threat-intel upload format must be one of csv, stix, or openioc."
            self._add(
                Action(
                    section="threat_intel",
                    operation="threat_intel_upload",
                    target=target,
                    app=THREAT_APP,
                    endpoint=f"/servicesNS/nobody/{THREAT_APP}/data/threat_intel/upload",
                    payload=handoff_payload(
                        bad_format_reason,
                        required_inputs=["format: csv|stix|openioc"],
                        docs_hint="Unknown formats stay handoff-only to avoid corrupting threat collections.",
                        **payload,
                    ),
                    apply_supported=False,
                    reason=bad_format_reason,
                )
            )
            return
        if not local_file_exists(file_path):
            missing_reason = "Threat-intel upload was requested but the local file was not found; hand off packaging or fix the path."
            self._add(
                Action(
                    section="threat_intel",
                    operation="threat_intel_upload",
                    target=target,
                    app=THREAT_APP,
                    endpoint=f"/servicesNS/nobody/{THREAT_APP}/data/threat_intel/upload",
                    payload=handoff_payload(
                        missing_reason,
                        required_inputs=[file_path or "file"],
                        docs_hint="Paths are resolved relative to the current working directory unless absolute.",
                        **payload,
                    ),
                    apply_supported=False,
                    reason=missing_reason,
                )
            )
            return
        size = resolve_local_path(file_path).stat().st_size
        if size > MAX_UPLOAD_BYTES:
            size_reason = f"Threat-intel upload file is larger than the guarded {MAX_UPLOAD_BYTES} byte limit."
            self._add(
                Action(
                    section="threat_intel",
                    operation="threat_intel_upload",
                    target=target,
                    app=THREAT_APP,
                    endpoint=f"/servicesNS/nobody/{THREAT_APP}/data/threat_intel/upload",
                    payload=handoff_payload(size_reason, required_inputs=["smaller validated IOC file"], **payload),
                    apply_supported=False,
                    reason=size_reason,
                )
            )
            return
        self._add(
            Action(
                section="threat_intel",
                operation="upload_threat_intel",
                target=target,
                app=THREAT_APP,
                endpoint=f"/servicesNS/nobody/{THREAT_APP}/data/threat_intel/upload",
                payload=payload,
            )
        )

    def _detections(self) -> None:
        section = self.spec.get("detections") or {}
        if not isinstance(section, dict):
            self._diag("error", "detections", "detections must be a mapping.")
            return
        for detection in named_items(section.get("existing") or section.get("tune")):
            self._detection_action(detection, create=False)
        for detection in named_items(section.get("custom") or section.get("create")):
            self._detection_action(detection, create=True)
        if boolish(section.get("inventory")):
            self._add(Action(section="detections", operation="inventory", target="detections", apply_supported=False, reason="Read-only inventory mode."))

    def _detection_action(self, detection: dict[str, Any], create: bool) -> None:
        name = str(detection.get("name") or "").strip()
        if not name:
            self._diag("error", "detections", "Detection entry is missing name.")
            return
        payload: dict[str, Any] = {}
        if create:
            if not detection.get("search"):
                self._diag("error", "detections", "Custom detection requires explicit search SPL.", name)
                return
            payload["search"] = str(detection["search"])
            payload["disabled"] = splunk_bool(not boolish(detection.get("enabled"), default=False))
        for source, dest in (
            ("enabled", "disabled"),
            ("cron_schedule", "cron_schedule"),
            ("description", "description"),
            ("actions", "actions"),
            ("dispatch_earliest_time", "dispatch.earliest_time"),
            ("dispatch_latest_time", "dispatch.latest_time"),
        ):
            if source not in detection:
                continue
            if source == "enabled":
                payload[dest] = splunk_bool(not boolish(detection[source]))
            elif source == "actions":
                payload[dest] = comma_join(detection[source])
            else:
                payload[dest] = detection[source]
        for prefix in ("action.notable", "action.risk", "action.finding", "annotations"):
            values = detection.get(prefix.replace(".", "_")) or detection.get(prefix)
            if isinstance(values, dict):
                for key, value in values.items():
                    payload[f"{prefix}.{key}"] = value if isinstance(value, str) else json.dumps(value)
        drilldown = detection.get("drilldown")
        if isinstance(drilldown, dict):
            if drilldown.get("name"):
                payload["action.correlationsearch.drilldown_name"] = str(drilldown["name"])
            if drilldown.get("search"):
                payload["action.correlationsearch.drilldown_search"] = str(drilldown["search"])
            if drilldown.get("earliest_offset"):
                payload["action.correlationsearch.drilldown_earliest_offset"] = str(drilldown["earliest_offset"])
            if drilldown.get("latest_offset"):
                payload["action.correlationsearch.drilldown_latest_offset"] = str(drilldown["latest_offset"])
        app = str(detection.get("app") or APP_NAME)
        self._add(
            Action(
                section="detections",
                operation="create_saved_search" if create else "set_saved_search",
                target=name,
                app=app,
                endpoint=f"/servicesNS/nobody/{app}/saved/searches/{quote(name, safe='')}",
                payload=payload,
            )
        )
        correlation_meta = detection.get("correlation_metadata")
        if isinstance(correlation_meta, dict):
            self._correlation_metadata_action(name, app, detection, correlation_meta)
        acl = detection.get("acl") or detection.get("permissions")
        if isinstance(acl, dict):
            self._saved_search_acl_action(name, app, acl)

    def _saved_search_acl_action(
        self,
        name: str,
        app: str,
        acl: dict[str, Any],
    ) -> None:
        payload: dict[str, Any] = {}
        if "sharing" in acl:
            sharing = str(acl["sharing"]).strip().lower()
            if sharing not in {"user", "app", "global", "system"}:
                self._diag("warn", "detections", f"Unknown sharing '{sharing}'; passing to Splunk as-is.", name)
            payload["sharing"] = sharing
        if "owner" in acl:
            payload["owner"] = str(acl["owner"])
        read_roles = acl.get("read") or acl.get("perms.read")
        if read_roles is not None:
            payload["perms.read"] = comma_join(read_roles) if read_roles else "*"
        write_roles = acl.get("write") or acl.get("perms.write")
        if write_roles is not None:
            payload["perms.write"] = comma_join(write_roles) if write_roles else ""
        if not payload:
            return
        owner = str(acl.get("owner") or "nobody")
        self._add(
            Action(
                section="detections",
                operation="set_acl",
                target=name,
                app=app,
                endpoint=f"/servicesNS/{quote(owner, safe='')}/{app}/saved/searches/{quote(name, safe='')}/acl",
                payload=payload,
            )
        )

    # Default search order for correlation metadata when correlation_metadata.app
    # is not explicitly set. ES OOTB correlation searches are owned by SA-* and
    # DA-ESS-* apps, not by SplunkEnterpriseSecuritySuite itself. Operators may
    # override via correlation_metadata.app_search_order.
    DEFAULT_CORRELATION_APP_SEARCH_ORDER = (
        "SA-AccessProtection",
        "SA-NetworkProtection",
        "SA-ThreatIntelligence",
        "SA-EndpointProtection",
        "SA-IdentityManagement",
        "SA-AuditAndDataProtection",
        "SA-Detections",
        "DA-ESS-AccessProtection",
        "DA-ESS-NetworkProtection",
        "DA-ESS-ThreatIntelligence",
        "DA-ESS-EndpointProtection",
        "DA-ESS-IdentityManagement",
        "SplunkEnterpriseSecuritySuite",
    )

    def _correlation_metadata_action(
        self,
        name: str,
        app: str,
        detection: dict[str, Any],
        meta: dict[str, Any],
    ) -> None:
        payload: dict[str, Any] = {}
        mapping = {
            "rule_name": "rule_name",
            "rule_description": "rule_description",
            "rule_title": "rule_title",
            "security_domain": "security_domain",
            "severity": "severity",
            "nes_fields": "nes_fields",
            "default_owner": "default_owner",
            "default_status": "default_status",
            "drilldown_name": "drilldown_name",
            "drilldown_search": "drilldown_search",
            "drilldown_earliest_offset": "drilldown_earliest_offset",
            "drilldown_latest_offset": "drilldown_latest_offset",
            "annotations": "annotations",
            "search_window": "search_window",
        }
        for source, dest in mapping.items():
            if source in meta:
                value = meta[source]
                if isinstance(value, (list, dict)):
                    payload[dest] = json.dumps(value)
                else:
                    payload[dest] = str(value)
        if "enabled" in meta:
            payload["disabled"] = splunk_bool(not boolish(meta["enabled"]))
        if not payload:
            return
        explicit_app = str(meta.get("app") or "").strip()
        action_payload: dict[str, Any] = dict(payload)
        if explicit_app:
            meta_app = explicit_app
            endpoint = f"/servicesNS/nobody/{meta_app}/admin/correlationsearches/{quote(name, safe='')}"
        else:
            # No explicit app: planner records the candidate search order and
            # apply path discovers the correct owning app via GET-by-name.
            search_order = meta.get("app_search_order")
            if not isinstance(search_order, list) or not search_order:
                search_order = list(self.DEFAULT_CORRELATION_APP_SEARCH_ORDER)
            else:
                search_order = [str(item).strip() for item in search_order if str(item).strip()]
            action_payload["_app_search_order"] = search_order
            meta_app = search_order[0] if search_order else APP_NAME
            endpoint = f"/servicesNS/nobody/{meta_app}/admin/correlationsearches/{quote(name, safe='')}"
        self._add(
            Action(
                section="detections",
                operation="set_correlation_metadata",
                target=name,
                app=meta_app,
                endpoint=endpoint,
                payload=action_payload,
            )
        )

    def _risk(self) -> None:
        section = self.spec.get("risk") or {}
        if not isinstance(section, dict):
            self._diag("error", "risk", "risk must be a mapping.")
            return
        for factor in named_items(section.get("factors")):
            name = str(factor.get("name") or "").strip()
            if not name:
                self._diag("error", "risk", "Risk factor is missing name.")
                continue
            payload = {key: value for key, value in factor.items() if key != "name"}
            self._add(
                Action(
                    section="risk",
                    operation="set_conf",
                    target=name,
                    app=THREAT_APP,
                    endpoint=f"/servicesNS/nobody/{THREAT_APP}/configs/conf-risk_factors/{quote(name, safe='')}",
                    payload=payload,
                )
            )
        for search in named_items(section.get("risk_rules")):
            search.setdefault("action_risk", {"param._risk_score": search.get("risk_score", 10)})
            self._detection_action(search, create=boolish(search.get("create"), default=False))

    def _urgency(self) -> None:
        section = self.spec.get("urgency") or {}
        if not section:
            return
        if not isinstance(section, dict):
            self._diag("error", "urgency", "urgency must be a mapping.")
            return
        # The ES urgency matrix keys by "<priority>|<severity>" (lowercase).
        if "matrix" in section:
            entries = section.get("matrix") or []
        else:
            entries = section
        for entry in named_items(entries, default_key="stanza"):
            stanza = str(entry.get("stanza") or entry.get("name") or "").strip()
            urgency_value = entry.get("urgency")
            if not stanza or urgency_value is None:
                if "matrix" in section:
                    self._diag("error", "urgency", "Urgency matrix entry is missing stanza or urgency.")
                continue
            payload = {"urgency": str(urgency_value)}
            if "disabled" in entry:
                payload["disabled"] = splunk_bool(not boolish(entry["enabled"], default=True)) if "enabled" in entry else splunk_bool(boolish(entry["disabled"]))
            self._add(
                Action(
                    section="urgency",
                    operation="set_conf",
                    target=stanza,
                    app=THREAT_APP,
                    endpoint=f"/servicesNS/nobody/{THREAT_APP}/configs/conf-urgency/{quote(stanza, safe='')}",
                    payload=payload,
                )
            )

    def _adaptive_response(self) -> None:
        section = self.spec.get("adaptive_response") or {}
        if not section:
            return
        if not isinstance(section, dict):
            self._diag("error", "adaptive_response", "adaptive_response must be a mapping.")
            return
        allowed = {"notable", "risk", "finding", "rba", "sendalert", "email", "webhook"}
        for stanza, values in section.items():
            if stanza == "app":
                continue
            if stanza not in allowed:
                self._diag("warn", "adaptive_response", "Unknown adaptive response action; applied as-is.", stanza)
            if not isinstance(values, dict):
                self._diag("error", "adaptive_response", "Action body must be a mapping.", stanza)
                continue
            app = str(section.get("app") or values.get("app") or APP_NAME)
            payload = {key: (value if isinstance(value, str) else json.dumps(value)) for key, value in values.items() if key != "app"}
            if not payload:
                continue
            self._add(
                Action(
                    section="adaptive_response",
                    operation="set_conf",
                    target=f"alert_actions://{stanza}",
                    app=app,
                    endpoint=f"/servicesNS/nobody/{app}/configs/conf-alert_actions/{quote(stanza, safe='')}",
                    payload=payload,
                )
            )

    def _notable_suppressions(self) -> None:
        section = self.spec.get("notable_suppressions") or []
        if isinstance(section, dict):
            section = section.get("suppressions") or section.get("rules") or []
        if not section:
            return
        for entry in named_items(section):
            name = str(entry.get("name") or "").strip()
            if not name:
                self._diag("error", "notable_suppressions", "Notable suppression is missing name.")
                continue
            search = entry.get("search")
            if not search:
                self._diag("error", "notable_suppressions", "Notable suppression requires a search.", name)
                continue
            payload: dict[str, Any] = {
                "search": str(search),
                "disabled": splunk_bool(not boolish(entry.get("enabled"), default=True)),
            }
            if entry.get("comment"):
                payload["comment"] = str(entry["comment"])
            if entry.get("description"):
                payload["description"] = str(entry["description"])
            stanza = f"notable_suppression://{name}"
            self._add(
                Action(
                    section="notable_suppressions",
                    operation="set_conf",
                    target=stanza,
                    app=THREAT_APP,
                    endpoint=f"/servicesNS/nobody/{THREAT_APP}/configs/conf-notable_suppressions/{quote(stanza, safe='')}",
                    payload=payload,
                )
            )

    def _log_review(self) -> None:
        section = self.spec.get("log_review") or {}
        if not section:
            return
        if not isinstance(section, dict):
            self._diag("error", "log_review", "log_review must be a mapping.")
            return
        # ES 8.x stores notable / investigation review status definitions in
        # SA-ThreatIntelligence/reviewstatuses.conf, not in SplunkEnterpriseSecuritySuite/log_review.conf.
        # Keep the legacy log_review.statuses / log_review.dispositions spec
        # sub-keys for backward compatibility and route them to reviewstatuses.
        for entry in named_items(section.get("statuses")):
            self._review_status_action(entry, default_type="notable", section_label="log_review")
        for entry in named_items(section.get("dispositions")):
            # Dispositions historically shared log_review.conf but ES 8.x treats them
            # as investigation-type review statuses in reviewstatuses.conf.
            self._review_status_action(entry, default_type="investigation", section_label="log_review")
        settings = section.get("settings")
        if isinstance(settings, dict):
            payload = {key: (value if isinstance(value, str) else json.dumps(value)) for key, value in settings.items()}
            if payload:
                self._add(
                    Action(
                        section="log_review",
                        operation="set_conf",
                        target="incident_review",
                        app=THREAT_APP,
                        endpoint=f"/servicesNS/nobody/{THREAT_APP}/configs/conf-log_review/incident_review",
                        payload=payload,
                    )
                )

    def _review_statuses(self) -> None:
        section = self.spec.get("review_statuses") or {}
        if not section:
            return
        if isinstance(section, list):
            for entry in named_items(section):
                self._review_status_action(entry, default_type="notable", section_label="review_statuses")
            return
        if not isinstance(section, dict):
            self._diag("error", "review_statuses", "review_statuses must be a mapping or list.")
            return
        for status_type_key, values in section.items():
            if status_type_key not in {"notable", "investigation"}:
                self._diag("warn", "review_statuses", "Unknown status_type; expected 'notable' or 'investigation'.", status_type_key)
            for entry in named_items(values):
                self._review_status_action(entry, default_type=status_type_key, section_label="review_statuses")

    def _review_status_action(
        self,
        entry: dict[str, Any],
        default_type: str,
        section_label: str,
    ) -> None:
        name = str(entry.get("name") or entry.get("id") or "").strip()
        if not name:
            self._diag("error", section_label, "Review status entry is missing name / id.")
            return
        status_type = str(entry.get("status_type") or default_type).strip().lower()
        if status_type not in {"notable", "investigation"}:
            self._diag("warn", section_label, f"Coercing unknown status_type '{status_type}' to 'notable'.", name)
            status_type = "notable"
        payload: dict[str, Any] = {
            "label": str(entry.get("label") or name),
            "status_type": status_type,
            "disabled": splunk_bool(not boolish(entry.get("enabled"), default=True)),
        }
        if entry.get("description"):
            payload["description"] = str(entry["description"])
        if "end" in entry:
            payload["end"] = splunk_bool(entry["end"])
        if "is_default" in entry:
            payload["default"] = splunk_bool(entry["is_default"])
        elif "default" in entry:
            payload["default"] = splunk_bool(entry["default"])
        if "editable" in entry:
            payload["editable"] = splunk_bool(entry["editable"])
        if "hidden" in entry:
            payload["hidden"] = splunk_bool(entry["hidden"])
        if "rank" in entry:
            payload["rank"] = str(entry["rank"])
        self._add(
            Action(
                section=section_label,
                operation="set_conf",
                target=name,
                app=THREAT_APP,
                endpoint=f"/servicesNS/nobody/{THREAT_APP}/configs/conf-reviewstatuses/{quote(name, safe='')}",
                payload=payload,
            )
        )

    def _use_cases(self) -> None:
        section = self.spec.get("use_cases") or []
        if isinstance(section, dict):
            section = section.get("entries") or []
        if not section:
            return
        for entry in named_items(section):
            name = str(entry.get("name") or "").strip()
            if not name:
                self._diag("error", "use_cases", "Use case entry is missing name.")
                continue
            payload = {key: (value if isinstance(value, str) else json.dumps(value)) for key, value in entry.items() if key != "name"}
            if not payload:
                continue
            self._add(
                Action(
                    section="use_cases",
                    operation="set_conf",
                    target=name,
                    app=UTILS_APP,
                    endpoint=f"/servicesNS/nobody/{UTILS_APP}/configs/conf-use_cases/{quote(name, safe='')}",
                    payload=payload,
                )
            )

    def _governance(self) -> None:
        section = self.spec.get("governance") or []
        if isinstance(section, dict):
            section = section.get("frameworks") or section.get("entries") or []
        if not section:
            return
        for entry in named_items(section):
            name = str(entry.get("name") or "").strip()
            if not name:
                self._diag("error", "governance", "Governance framework is missing name.")
                continue
            payload = {key: (value if isinstance(value, str) else json.dumps(value)) for key, value in entry.items() if key != "name"}
            if not payload:
                continue
            self._add(
                Action(
                    section="governance",
                    operation="set_conf",
                    target=name,
                    app=AUDIT_APP,
                    endpoint=f"/servicesNS/nobody/{AUDIT_APP}/configs/conf-governance/{quote(name, safe='')}",
                    payload=payload,
                )
            )

    def _macros(self) -> None:
        section = self.spec.get("macros") or []
        if isinstance(section, dict):
            section = section.get("entries") or []
        if not section:
            return
        for entry in named_items(section):
            name = str(entry.get("name") or "").strip()
            if not name:
                self._diag("error", "macros", "Macro entry is missing name.")
                continue
            payload: dict[str, Any] = {}
            if "definition" in entry:
                payload["definition"] = str(entry["definition"])
            if "args" in entry:
                payload["args"] = comma_join(entry["args"])
            if "validation" in entry:
                payload["validation"] = str(entry["validation"])
            if "iseval" in entry:
                payload["iseval"] = splunk_bool(entry["iseval"])
            if not payload:
                continue
            app = str(entry.get("app") or APP_NAME)
            self._add(
                Action(
                    section="macros",
                    operation="set_macro",
                    target=name,
                    app=app,
                    endpoint=f"/servicesNS/nobody/{app}/admin/macros/{quote(name, safe='')}",
                    payload=payload,
                )
            )

    def _eventtypes(self) -> None:
        section = self.spec.get("eventtypes") or []
        if isinstance(section, dict):
            section = section.get("entries") or []
        if not section:
            return
        for entry in named_items(section):
            name = str(entry.get("name") or "").strip()
            if not name:
                self._diag("error", "eventtypes", "Eventtype entry is missing name.")
                continue
            payload: dict[str, Any] = {}
            if "search" in entry:
                payload["search"] = str(entry["search"])
            if "description" in entry:
                payload["description"] = str(entry["description"])
            if "priority" in entry:
                payload["priority"] = str(entry["priority"])
            if "tags" in entry:
                payload["tags"] = comma_join(entry["tags"])
            if "disabled" in entry or "enabled" in entry:
                payload["disabled"] = splunk_bool(
                    not boolish(entry.get("enabled"), default=True) if "enabled" in entry else boolish(entry.get("disabled"))
                )
            if not payload:
                continue
            app = str(entry.get("app") or APP_NAME)
            self._add(
                Action(
                    section="eventtypes",
                    operation="set_eventtype",
                    target=name,
                    app=app,
                    endpoint=f"/servicesNS/nobody/{app}/saved/eventtypes/{quote(name, safe='')}",
                    payload=payload,
                )
            )

    def _tags(self) -> None:
        section = self.spec.get("tags") or []
        if isinstance(section, dict):
            section = section.get("entries") or []
        if not section:
            return
        for entry in named_items(section, default_key="field"):
            field_name = str(entry.get("field") or entry.get("name") or "").strip()
            value = entry.get("value")
            tags_list = listify(entry.get("tags"))
            if not field_name or value is None or not tags_list:
                self._diag("error", "tags", "Tag entry requires field, value, and tags.", field_name or None)
                continue
            target = f"{field_name}={value}"
            payload = {tag: "enabled" for tag in tags_list}
            app = str(entry.get("app") or APP_NAME)
            self._add(
                Action(
                    section="tags",
                    operation="set_tag",
                    target=target,
                    app=app,
                    endpoint=f"/servicesNS/nobody/{app}/saved/fvtags/{quote(target, safe='')}",
                    payload=payload,
                )
            )

    def _navigation(self) -> None:
        section = self.spec.get("navigation") or {}
        if not section:
            return
        if not isinstance(section, dict):
            self._diag("error", "navigation", "navigation must be a mapping.")
            return
        xml = section.get("xml") or section.get("data")
        path = section.get("path")
        if not xml and path:
            try:
                xml = Path(path).read_text(encoding="utf-8")
            except OSError as exc:
                self._diag("error", "navigation", f"Could not read navigation XML from path: {exc}", path)
                return
        if not xml:
            self._diag("error", "navigation", "navigation requires inline xml or a path to an XML file.")
            return
        app = str(section.get("app") or APP_NAME)
        name = str(section.get("name") or "default")
        self._add(
            Action(
                section="navigation",
                operation="set_navigation",
                target=name,
                app=app,
                endpoint=f"/servicesNS/nobody/{app}/data/ui/nav/{quote(name, safe='')}",
                payload={"eai:data": str(xml)},
            )
        )

    def _glass_tables(self) -> None:
        section = self.spec.get("glass_tables") or []
        if isinstance(section, dict):
            section = section.get("entries") or []
        if not section:
            return
        for entry in named_items(section):
            name = str(entry.get("name") or "").strip()
            if not name:
                self._diag("error", "glass_tables", "Glass table entry is missing name.")
                continue
            xml = entry.get("xml")
            path = entry.get("path")
            if not xml and path:
                try:
                    xml = Path(path).read_text(encoding="utf-8")
                except OSError as exc:
                    self._diag("error", "glass_tables", f"Could not read XML from path: {exc}", name)
                    continue
            if not xml:
                self._diag("error", "glass_tables", "Glass table requires inline xml or a path.", name)
                continue
            xml_text = str(xml)
            if _looks_like_secret(xml_text):
                self._add(
                    Action(
                        section="glass_tables",
                        operation="handoff",
                        target=name,
                        apply_supported=False,
                        reason="Glass table XML looks like it contains secret material; review manually and deploy outside the engine.",
                    )
                )
                continue
            app = str(entry.get("app") or APP_NAME)
            self._add(
                Action(
                    section="glass_tables",
                    operation="set_view",
                    target=name,
                    app=app,
                    endpoint=f"/servicesNS/nobody/{app}/data/ui/views/{quote(name, safe='')}",
                    payload={"eai:data": xml_text},
                )
            )

    def _workflow_actions(self) -> None:
        section = self.spec.get("workflow_actions") or []
        if isinstance(section, dict):
            section = section.get("entries") or []
        if not section:
            return
        for entry in named_items(section):
            name = str(entry.get("name") or "").strip()
            if not name:
                self._diag("error", "workflow_actions", "Workflow action entry is missing name.")
                continue
            app = str(entry.get("app") or APP_NAME)
            payload: dict[str, Any] = {}
            mapping = {
                "display_location": "display_location",
                "fields": "fields",
                "label": "label",
                "link_uri": "link.uri",
                "link_method": "link.method",
                "link_target": "link.target",
                "link_app": "link.app",
                "link_view": "link.view",
                "type": "type",
                "eventtypes": "eventtypes",
                "search_earliest": "search.earliest",
                "search_latest": "search.latest",
                "search_preserve_time_range": "search.preserve_time_range",
                "search_view": "search.view",
                "search_app": "search.app",
                "disabled": "disabled",
            }
            for src, dest in mapping.items():
                if src in entry:
                    value = entry[src]
                    if isinstance(value, list):
                        payload[dest] = comma_join(value)
                    elif isinstance(value, bool):
                        payload[dest] = splunk_bool(value)
                    else:
                        payload[dest] = str(value)
            if "enabled" in entry and "disabled" not in entry:
                payload["disabled"] = splunk_bool(not boolish(entry["enabled"]))
            if not payload:
                self._diag("warn", "workflow_actions", "Workflow action has no managed fields.", name)
                continue
            self._add(
                Action(
                    section="workflow_actions",
                    operation="post_endpoint",
                    target=name,
                    app=app,
                    endpoint=f"/servicesNS/nobody/{app}/data/ui/workflow-actions/{quote(name, safe='')}",
                    payload=payload,
                )
            )

    def _kv_collections(self) -> None:
        section = self.spec.get("kv_collections") or []
        if isinstance(section, dict):
            section = section.get("entries") or []
        if not section:
            return
        for entry in named_items(section):
            name = str(entry.get("name") or "").strip()
            if not name:
                self._diag("error", "kv_collections", "KV collection entry is missing name.")
                continue
            app = str(entry.get("app") or APP_NAME)
            payload: dict[str, Any] = {}
            fields = entry.get("fields") or {}
            if isinstance(fields, dict):
                for field_name, field_type in fields.items():
                    if not isinstance(field_type, str):
                        field_type = str(field_type)
                    payload[f"field.{field_name}"] = field_type
            accelerated = entry.get("accelerated_fields") or {}
            if isinstance(accelerated, dict):
                for accel_name, spec in accelerated.items():
                    payload[f"accelerated_fields.{accel_name}"] = (
                        spec if isinstance(spec, str) else json.dumps(spec)
                    )
            for scalar in ("replicate", "enforceTypes", "profilingEnabled", "type"):
                if scalar in entry:
                    value = entry[scalar]
                    if isinstance(value, bool):
                        payload[scalar] = splunk_bool(value)
                    else:
                        payload[scalar] = str(value)
            if not payload:
                self._diag("warn", "kv_collections", "KV collection has no fields or settings.", name)
                continue
            self._add(
                Action(
                    section="kv_collections",
                    operation="set_kv_collection",
                    target=name,
                    app=app,
                    endpoint=f"/servicesNS/nobody/{app}/storage/collections/config/{quote(name, safe='')}",
                    payload=payload,
                )
            )

    def _findings(self) -> None:
        section = self.spec.get("findings") or {}
        if not section:
            return
        if not isinstance(section, dict):
            self._diag("error", "findings", "findings must be a mapping.")
            return
        intermediate = section.get("intermediate") or section.get("intermediate_findings")
        if isinstance(intermediate, dict) and intermediate:
            payload = {
                key: (splunk_bool(value) if isinstance(value, bool) else str(value))
                for key, value in intermediate.items()
            }
            self._add(
                Action(
                    section="findings",
                    operation="set_conf",
                    target="intermediate_findings",
                    app=THREAT_APP,
                    endpoint=f"/servicesNS/nobody/{THREAT_APP}/configs/conf-findings/intermediate_findings",
                    payload=payload,
                )
            )

    def _intelligence_management(self) -> None:
        section = self.spec.get("intelligence_management") or {}
        if not section:
            return
        if not isinstance(section, dict):
            self._diag("error", "intelligence_management", "intelligence_management must be a mapping.")
            return
        payload: dict[str, Any] = {}
        mapping = {
            "subscribed": "subscribed",
            "enclave_ids": "enclave_ids",
            "enclave_names": "enclave_names",
            "im_scs_url": "im_scs_url",
            "is_talos_query_enabled": "is_talos_query_enabled",
        }
        for src, dest in mapping.items():
            if src in section:
                value = section[src]
                if isinstance(value, list):
                    payload[dest] = comma_join(value)
                elif isinstance(value, bool):
                    payload[dest] = splunk_bool(value)
                else:
                    payload[dest] = str(value)
        if section.get("tenant_pairing_required") or section.get("secret_file"):
            self._add(
                Action(
                    section="intelligence_management",
                    operation="handoff",
                    target="tim_cloud_pairing",
                    payload={
                        key: section.get(key)
                        for key in ("tenant_pairing_required", "secret_file")
                        if key in section
                    },
                    apply_supported=False,
                    reason="TIM Cloud tenant pairing requires Splunk-hosted secrets; handle out-of-band.",
                )
            )
        if not payload:
            return
        self._add(
            Action(
                section="intelligence_management",
                operation="set_conf",
                target="im",
                app=MISSION_CONTROL_APP,
                endpoint=f"/servicesNS/nobody/{MISSION_CONTROL_APP}/configs/conf-intelligence_management/im",
                payload=payload,
            )
        )

    def _es_ai_settings(self) -> None:
        section = self.spec.get("es_ai_settings") or {}
        if not section:
            return
        if not isinstance(section, dict):
            self._diag("error", "es_ai_settings", "es_ai_settings must be a mapping.")
            return
        stanza_map = {
            "settings": "settings",
            "ai_triage_detections": "ai_triage_detections",
            "triage_agent_dispatch_settings": "triage_agent_dispatch_settings",
        }
        for src, stanza in stanza_map.items():
            values = section.get(src)
            if not isinstance(values, dict) or not values:
                continue
            payload = {}
            for key, value in values.items():
                if isinstance(value, bool):
                    payload[key] = splunk_bool(value)
                elif isinstance(value, (list, dict)):
                    payload[key] = json.dumps(value)
                else:
                    payload[key] = str(value)
            self._add(
                Action(
                    section="es_ai_settings",
                    operation="set_conf",
                    target=stanza,
                    app=MISSION_CONTROL_APP,
                    endpoint=f"/servicesNS/nobody/{MISSION_CONTROL_APP}/configs/conf-es_ai_settings/{quote(stanza, safe='')}",
                    payload=payload,
                )
            )

    def _dlx_settings(self) -> None:
        section = self.spec.get("dlx_settings") or {}
        if not section:
            return
        if not isinstance(section, dict):
            self._diag("error", "dlx_settings", "dlx_settings must be a mapping.")
            return
        # Each child key is a stanza (api_config, scheduler, worker, detection_sync, search).
        for stanza, values in section.items():
            if not isinstance(values, dict) or not values:
                continue
            payload: dict[str, Any] = {}
            for key, value in values.items():
                if isinstance(value, bool):
                    payload[key] = splunk_bool(value)
                elif isinstance(value, (list, dict)):
                    payload[key] = json.dumps(value)
                else:
                    payload[key] = str(value)
            if not payload:
                continue
            self._add(
                Action(
                    section="dlx_settings",
                    operation="set_conf",
                    target=stanza,
                    app="dlx-app",
                    endpoint=f"/servicesNS/nobody/dlx-app/configs/conf-dlx_settings/{quote(stanza, safe='')}",
                    payload=payload,
                )
            )

    def _exposure_analytics(self) -> None:
        section = self.spec.get("exposure_analytics") or {}
        if not section:
            return
        if not isinstance(section, dict):
            self._diag("error", "exposure_analytics", "exposure_analytics must be a mapping.")
            return
        population = section.get("asset_identity_population") or section.get("ai_population") or {}
        if isinstance(population, dict):
            self._exposure_population_target("assets", population.get("assets") or population.get("asset"))
            self._exposure_population_target("identities", population.get("identities") or population.get("identity"))
        elif population:
            self._diag("error", "exposure_analytics", "asset_identity_population must be a mapping.")
        for search in named_items(section.get("processing_searches")):
            self._exposure_saved_search(search)
        for source in named_items(section.get("sources") or section.get("entity_discovery_sources")):
            name = str(source.get("name") or "").strip()
            if not name:
                self._diag("error", "exposure_analytics", "Exposure Analytics source is missing name.")
                continue
            self._exposure_schema_object("source", source, name)
        for rule in named_items(section.get("enrichment_rules")):
            name = str(rule.get("name") or "").strip()
            if not name:
                self._diag("error", "exposure_analytics", "Exposure Analytics enrichment rule is missing name.")
                continue
            self._exposure_schema_object("enrichment_rule", rule, name)

    def _exposure_schema_object(self, object_type: str, item: dict[str, Any], name: str) -> None:
        endpoint = str(item.get("endpoint") or item.get("rest_endpoint") or "").strip()
        conflict_policy = str(item.get("conflict_policy") or "").strip().lower()
        requested_operation = str(item.get("operation") or ("update" if item.get("id") or item.get("existing") else "create")).strip().lower()
        if not endpoint:
            classification = "missing_endpoint"
        elif conflict_policy not in {"create_only", "create-only"}:
            classification = "manual_resolution_required"
        elif requested_operation not in {"create", "add"}:
            classification = "manual_resolution_required"
        elif isinstance(item.get("schema"), dict) and item.get("package_schema") and item.get("schema") != item.get("package_schema"):
            classification = "schema_mismatch"
        else:
            classification = "create_only_safe"
        object_payload = {
            key: value
            for key, value in item.items()
            if key
            not in {
                "apply",
                "conflict_policy",
                "endpoint",
                "rest_endpoint",
                "operation",
                "existing",
                "package_schema",
                "schema_status",
            }
        }
        reason = (
            "Exposure Analytics source/enrichment automation is create-only unless live/package schema validation proves it is safe."
        )
        metadata = {
            "object_type": object_type,
            "schema_classification": classification,
            "conflict_policy": conflict_policy or "manual",
            "requested_operation": requested_operation,
            "endpoint": endpoint,
            "object": object_payload,
        }
        if boolish(item.get("apply"), default=False) and classification == "create_only_safe":
            self._add(
                Action(
                    section="exposure_analytics",
                    operation="exposure_schema_apply",
                    target=name,
                    app=EXPOSURE_ANALYTICS_APP,
                    endpoint=endpoint,
                    payload=metadata,
                )
            )
            return
        self._add(
            Action(
                section="exposure_analytics",
                operation="exposure_schema_check",
                target=name,
                app=EXPOSURE_ANALYTICS_APP,
                endpoint=endpoint or None,
                payload=handoff_payload(
                    reason,
                    required_inputs=[
                        "documented REST endpoint",
                        "conflict_policy: create_only",
                        "apply: true only for create-only objects",
                        "operator-reviewed schema conflict report",
                    ],
                    docs_hint="Updates, deletes, and schema conflicts stay handoff-only; declare saved-search/macro toggles for fully supported automation.",
                    **metadata,
                ),
                apply_supported=False,
                reason=reason,
            )
        )

    def _exposure_population_target(self, target: str, body: Any) -> None:
        if body in (None, False):
            return
        if isinstance(body, bool):
            body = {"enabled": body}
        if not isinstance(body, dict):
            self._diag("error", "exposure_analytics", f"{target} population must be a boolean or mapping.")
            return
        search_name = "ea_gen_es_lookup_assets" if target == "assets" else "ea_gen_es_lookup_identities"
        macro_prefix = "ea_es_assets" if target == "assets" else "ea_es_identities"
        payload: dict[str, Any] = {
            "disabled": splunk_bool(not boolish(body.get("enabled"), default=True)),
            "is_scheduled": splunk_bool(True),
        }
        if "cron_schedule" in body or "schedule" in body:
            payload["cron_schedule"] = str(body.get("cron_schedule") or body.get("schedule"))
        for source_key, dest_key in (
            ("dispatch_earliest_time", "dispatch.earliest_time"),
            ("dispatch_latest_time", "dispatch.latest_time"),
            ("schedule_window", "schedule_window"),
            ("schedule_priority", "schedule_priority"),
        ):
            if source_key in body:
                payload[dest_key] = str(body[source_key])
        self._add(
            Action(
                section="exposure_analytics",
                operation="set_saved_search",
                target=search_name,
                app=EXPOSURE_ANALYTICS_APP,
                endpoint=f"/servicesNS/nobody/{EXPOSURE_ANALYTICS_APP}/saved/searches/{quote(search_name, safe='')}",
                payload=payload,
            )
        )
        macro_map = {
            "filter": f"{macro_prefix}_filter_macro",
            "filter_macro": f"{macro_prefix}_filter_macro",
            "max_populate": f"{macro_prefix}_max_populate",
            "fields": f"{macro_prefix}_fields",
            "evals": f"{macro_prefix}_evals",
            "renames": f"{macro_prefix}_renames",
        }
        for source_key, macro_name in macro_map.items():
            if source_key not in body:
                continue
            value = body[source_key]
            definition = comma_join(value) if source_key == "fields" and not isinstance(value, str) else str(value)
            self._add(
                Action(
                    section="exposure_analytics",
                    operation="set_macro",
                    target=macro_name,
                    app=EXPOSURE_ANALYTICS_APP,
                    endpoint=f"/servicesNS/nobody/{EXPOSURE_ANALYTICS_APP}/admin/macros/{quote(macro_name, safe='')}",
                    payload={"definition": definition},
                )
            )

    def _exposure_saved_search(self, search: dict[str, Any]) -> None:
        name = str(search.get("name") or "").strip()
        if not name:
            self._diag("error", "exposure_analytics", "Processing search is missing name.")
            return
        payload: dict[str, Any] = {}
        if "enabled" in search:
            payload["disabled"] = splunk_bool(not boolish(search["enabled"]))
            payload["is_scheduled"] = splunk_bool(True)
        if "cron_schedule" in search or "schedule" in search:
            payload["cron_schedule"] = str(search.get("cron_schedule") or search.get("schedule"))
            payload.setdefault("is_scheduled", splunk_bool(True))
        for source_key, dest_key in (
            ("dispatch_earliest_time", "dispatch.earliest_time"),
            ("dispatch_latest_time", "dispatch.latest_time"),
            ("schedule_window", "schedule_window"),
            ("schedule_priority", "schedule_priority"),
        ):
            if source_key in search:
                payload[dest_key] = str(search[source_key])
        if not payload:
            self._diag("warn", "exposure_analytics", "Processing search has no managed fields.", name)
            return
        self._add(
            Action(
                section="exposure_analytics",
                operation="set_saved_search",
                target=name,
                app=EXPOSURE_ANALYTICS_APP,
                endpoint=f"/servicesNS/nobody/{EXPOSURE_ANALYTICS_APP}/saved/searches/{quote(name, safe='')}",
                payload=payload,
            )
        )

    def _content_library(self) -> None:
        section = self.spec.get("content_library") or {}
        if not section:
            return
        if not isinstance(section, dict):
            self._diag("error", "content_library", "content_library must be a mapping.")
            return
        if boolish(section.get("install")):
            is_cloud = spec_platform(self.spec) == "cloud"
            install_targets = [CONTENT_UPDATE_APP]
            if content_library_app_id(section, CONTENT_LIBRARY_APP):
                install_targets.append(CONTENT_LIBRARY_APP)
            for app in install_targets:
                app_id = content_library_app_id(section, app)
                payload = {
                    "app_name": app,
                    "source": "splunkbase",
                    "update": True,
                }
                if app_id:
                    payload["app_id"] = app_id
                self._add(
                    Action(
                        section="content_library",
                        operation="install_app",
                        target=app,
                        app=app,
                        payload=(
                            handoff_payload(
                                "Splunk Cloud content-library app installation is support/ACS controlled; hand off installation.",
                                required_inputs=["Splunk Cloud supported app install path", "tenant/admin approval"],
                                docs_hint="ESCU is Splunkbase app 3449; run the install skill only for self-managed Enterprise.",
                                **payload,
                            )
                            if is_cloud
                            else payload
                        ),
                        apply_supported=not is_cloud,
                        reason=(
                            "Splunk Cloud content-library app installation is support/ACS controlled; hand off installation."
                            if is_cloud
                            else ""
                        ),
                    )
                )
        escu = section.get("escu")
        if isinstance(escu, dict):
            if "subscription" in escu or "auto_update" in escu:
                payload: dict[str, Any] = {}
                if "subscription" in escu:
                    payload["subscription"] = str(escu["subscription"])
                if "auto_update" in escu:
                    payload["auto_update"] = splunk_bool(escu["auto_update"])
                self._add(
                    Action(
                        section="content_library",
                        operation="set_conf",
                        target="subscription",
                        app=CONTENT_UPDATE_APP,
                        endpoint=f"/servicesNS/nobody/{CONTENT_UPDATE_APP}/configs/conf-escu_subscription/subscription",
                        payload=payload,
                    )
                )
            for story in listify(escu.get("enabled_stories")):
                story_name = str(story).strip()
                if not story_name:
                    continue
                self._add(
                    Action(
                        section="content_library",
                        operation="set_saved_search",
                        target=story_name,
                        app=CONTENT_UPDATE_APP,
                        endpoint=f"/servicesNS/nobody/{CONTENT_UPDATE_APP}/saved/searches/{quote(story_name, safe='')}",
                        payload={"disabled": "0"},
                    )
                )
            for detection in listify(escu.get("enabled_detections")):
                detection_name = str(detection).strip()
                if not detection_name:
                    continue
                self._add(
                    Action(
                        section="content_library",
                        operation="set_saved_search",
                        target=detection_name,
                        app=CONTENT_UPDATE_APP,
                        endpoint=f"/servicesNS/nobody/{CONTENT_UPDATE_APP}/saved/searches/{quote(detection_name, safe='')}",
                        payload={"disabled": "0"},
                    )
                )
        for pack in named_items(section.get("content_packs")):
            pack_name = str(pack.get("name") or "").strip()
            if not pack_name:
                self._diag("error", "content_library", "Content pack is missing name.")
                continue
            payload = {
                "id": pack_name,
                "disabled": splunk_bool(not boolish(pack.get("enabled"), default=False)),
            }
            if "source" in pack:
                payload["source"] = str(pack["source"])
            self._add(
                Action(
                    section="content_library",
                    operation="set_conf",
                    target=pack_name,
                    app=CONTENT_LIBRARY_APP,
                    endpoint=f"/servicesNS/nobody/{CONTENT_LIBRARY_APP}/configs/conf-content_packs/{quote(pack_name, safe='')}",
                    payload=payload,
                )
            )

    def _mission_control(self) -> None:
        section = self.spec.get("mission_control") or {}
        if not isinstance(section, dict):
            self._diag("error", "mission_control", "mission_control must be a mapping.")
            return
        for queue in named_items(section.get("queues")):
            self._mc_api_action("queue", "/servicesNS/nobody/missioncontrol/v2/queues", queue)
        for template in named_items(section.get("response_templates")):
            self._mc_api_action("response_template", "/servicesNS/nobody/missioncontrol/v1/responsetemplates", template)
        for plan in named_items(section.get("response_plans")):
            self._mc_api_action("response_plan", "/servicesNS/nobody/missioncontrol/v2/responseplans", plan)
        self._mission_control_search_settings(section.get("search") or section.get("search_settings"))
        self._mission_control_rbac_lockdown(section.get("rbac_lockdown") or section.get("lockdown"))
        for override in named_items(section.get("private_overrides")):
            self._mission_control_private_override(override)
        if section.get("settings"):
            self._add(
                Action(
                    section="mission_control",
                    operation="set_conf",
                    target="user-prefs/general",
                    app=MISSION_CONTROL_APP,
                    endpoint=f"/servicesNS/nobody/{MISSION_CONTROL_APP}/configs/conf-user-prefs/general",
                    payload=dict(section["settings"]),
                )
            )

    def _mission_control_private_override(self, override: dict[str, Any]) -> None:
        conf = str(override.get("conf") or "").strip()
        stanza = str(override.get("stanza") or "").strip()
        values = override.get("values") or override.get("payload") or {}
        if not conf or not stanza or not isinstance(values, dict) or not values:
            self._diag("error", "mission_control", "Private override requires conf, stanza, and values.", str(override.get("name") or "private_override"))
            return
        target = f"{conf}/{stanza}"
        allowlisted_fields = {
            key
            for key in values
            if (conf, stanza, str(key)) in MISSION_CONTROL_PRIVATE_ALLOWLIST
        }
        if allowlisted_fields == set(values):
            self._add(
                Action(
                    section="mission_control",
                    operation="set_conf",
                    target=target,
                    app=MISSION_CONTROL_APP,
                    endpoint=f"/servicesNS/nobody/{MISSION_CONTROL_APP}/configs/conf-{quote(conf, safe='')}/{quote(stanza, safe='')}",
                    payload={key: str(value) for key, value in values.items()},
                )
            )
            return
        intent = {
            "conf": conf,
            "stanza": stanza,
            "values": values,
        }
        confirm_id = stable_confirm_id("mission_control_private_override", target, intent)
        backup_export = override.get("backup_export")
        confirm_matches = str(override.get("confirm_id") or "") == confirm_id
        apply_requested = boolish(override.get("apply"), default=False)
        private_requested = boolish(override.get("private_override"), default=False)
        reason = (
            "Mission Control private/internal overrides are blocked unless the spec includes private_override, apply, backup_export, and the preview confirm_id."
        )
        if private_requested and apply_requested and backup_export and confirm_matches:
            self._add(
                Action(
                    section="mission_control",
                    operation="set_conf",
                    target=target,
                    app=MISSION_CONTROL_APP,
                    endpoint=f"/servicesNS/nobody/{MISSION_CONTROL_APP}/configs/conf-{quote(conf, safe='')}/{quote(stanza, safe='')}",
                    payload={key: (json.dumps(value) if isinstance(value, (dict, list)) else str(value)) for key, value in values.items()},
                )
            )
            return
        self._add(
            Action(
                section="mission_control",
                operation="private_override_handoff",
                target=target,
                app=MISSION_CONTROL_APP,
                payload=handoff_payload(
                    reason,
                    required_inputs=[
                        "private_override: true",
                        "apply: true",
                        "backup_export path or artifact id",
                        f"confirm_id: {confirm_id}",
                    ],
                    safe_next_command="bash skills/splunk-enterprise-security-config/scripts/setup.sh --spec es-config.yaml --mode export --output es-before-private-overrides.json",
                    docs_hint="Only mc_search.conf [aq_sid_caching] workload_pool is allowlisted for direct automation.",
                    confirm_id=confirm_id,
                    requested=intent,
                    backup_export=backup_export,
                ),
                apply_supported=False,
                reason=reason,
            )
        )

    def _mission_control_search_settings(self, body: Any) -> None:
        if not body:
            return
        if not isinstance(body, dict):
            self._diag("error", "mission_control", "search settings must be a mapping.")
            return
        payload: dict[str, Any] = {}
        if "workload_pool" in body:
            payload["workload_pool"] = str(body.get("workload_pool") or "")
        unsupported = sorted(
            key
            for key in body
            if key not in {"workload_pool", "inventory", "export_notes"}
        )
        for key in unsupported:
            self._add(
                Action(
                    section="mission_control",
                    operation="mission_control_setting_handoff",
                    target=f"mc_search/{key}",
                    app=MISSION_CONTROL_APP,
                    payload=handoff_payload(
                        "Only mc_search.conf [aq_sid_caching] workload_pool is safely automated in v1.",
                        required_inputs=["supported ES UI field", "Splunk Support guidance if field is not UI-supported"],
                        docs_hint="The ES System configuration page exposes selected fields, not arbitrary Mission Control internals.",
                        requested_field=key,
                    ),
                    apply_supported=False,
                    reason="Only mc_search.conf [aq_sid_caching] workload_pool is safely automated in v1.",
                )
            )
        if payload:
            self._add(
                Action(
                    section="mission_control",
                    operation="set_conf",
                    target="mc_search/aq_sid_caching",
                    app=MISSION_CONTROL_APP,
                    endpoint=f"/servicesNS/nobody/{MISSION_CONTROL_APP}/configs/conf-mc_search/aq_sid_caching",
                    payload=payload,
                )
            )

    def _mission_control_rbac_lockdown(self, body: Any) -> None:
        if body in (None, False):
            return
        if isinstance(body, bool):
            body = {"apply": body, "enabled": body, "lock": True}
        if not isinstance(body, dict):
            self._diag("error", "mission_control", "rbac_lockdown must be a boolean or mapping.")
            return
        payload: dict[str, Any] = {}
        if "collections" in body:
            payload["collections"] = comma_join(body["collections"])
        if "indexes" in body:
            payload["indexes"] = comma_join(body["indexes"])
        if "roles" in body:
            payload["roles"] = comma_join(body["roles"])
        if "lock" in body:
            payload["lock"] = splunk_bool(body["lock"])
        if "enabled" in body or "input_enabled" in body:
            payload["disabled"] = splunk_bool(not boolish(body.get("enabled", body.get("input_enabled")), default=False))
        if "interval" in body:
            payload["interval"] = str(body["interval"])
        if "debug" in body:
            payload["debug"] = splunk_bool(body["debug"])
        if not payload:
            self._diag("warn", "mission_control", "rbac_lockdown has no managed fields.", "lock_unlock_resources://default")
            return
        apply_requested = boolish(body.get("apply"), default=False)
        reason = (
            "RBAC lockdown changes queue KV collection and notable-index access; "
            "set rbac_lockdown.apply: true after reviewing affected collections, indexes, and roles."
        )
        self._add(
            Action(
                section="mission_control",
                operation="set_conf" if apply_requested else "rbac_lockdown_handoff",
                target="lock_unlock_resources://default",
                app=MISSION_CONTROL_APP,
                endpoint=f"/servicesNS/nobody/{MISSION_CONTROL_APP}/configs/conf-inputs/{quote('lock_unlock_resources://default', safe='')}",
                payload=(
                    payload
                    if apply_requested
                    else handoff_payload(
                        reason,
                        required_inputs=["rbac_lockdown.apply: true", "reviewed role/index impact", "rollback/unlock window"],
                        docs_hint="Lockdown is optional and can restrict direct access for non-admin users.",
                        proposed_payload=payload,
                    )
                ),
                apply_supported=apply_requested,
                reason="" if apply_requested else reason,
            )
        )

    def _mc_api_action(self, operation: str, endpoint: str, item: dict[str, Any]) -> None:
        name = str(item.get("name") or item.get("title") or item.get("id") or "").strip()
        if not name:
            self._diag("error", "mission_control", f"Mission Control {operation} entry is missing name/title/id.")
            return
        apply_supported = boolish(item.get("apply"), default=False)
        payload = {key: value for key, value in item.items() if key not in {"apply"}}
        try:
            json.dumps(payload)
        except TypeError as exc:
            self._diag("error", "mission_control", f"Mission Control {operation} payload is not JSON-serializable: {exc}", name)
            return
        reason = "" if apply_supported else "Mission Control API write requires explicit apply: true on the object."
        self._add(
            Action(
                section="mission_control",
                operation=f"{operation}_api",
                target=name,
                app=MISSION_CONTROL_APP,
                endpoint=endpoint,
                payload=payload,
                apply_supported=apply_supported,
                reason=reason,
            )
        )
        if not apply_supported:
            self.actions[-1].payload = handoff_payload(
                reason,
                required_inputs=["apply: true", "live Mission Control API support"],
                docs_hint="Validate Mission Control API support before enabling writes; unsupported endpoints remain handoff-only.",
                proposed_payload=payload,
            )

    def _integrations(self) -> None:
        section = self.spec.get("integrations") or {}
        if not isinstance(section, dict):
            self._diag("error", "integrations", "integrations must be a mapping.")
            return
        self._cloud_support_evidence()
        for name, body in section.items():
            body = body if isinstance(body, dict) else {"enabled": body}
            candidates = INTEGRATION_APPS.get(name, ())
            self._add(
                Action(
                    section="integrations",
                    operation="integration_inventory",
                    target=name,
                    payload={"candidate_apps": list(candidates), "enabled": body.get("enabled")},
                    apply_supported=False,
                    reason="Integration inventory/readiness check.",
                )
            )
            local_conf = body.get("local_conf")
            if isinstance(local_conf, dict):
                app = str(local_conf.get("app") or (candidates[0] if candidates else APP_NAME))
                conf = str(local_conf.get("conf") or "cloud_integrations")
                stanza = str(local_conf.get("stanza") or name)
                payload = dict(local_conf.get("values") or {})
                if payload:
                    self._add(
                        Action(
                            section="integrations",
                            operation="set_conf",
                            target=f"{conf}/{stanza}",
                            app=app,
                            endpoint=f"/servicesNS/nobody/{app}/configs/conf-{conf}/{quote(stanza, safe='')}",
                            payload=payload,
                        )
                    )
            preflight_requested = (
                boolish(body.get("preflight"), default=False)
                or bool(secret_file_paths(body))
                or bool(body.get("tenant_pairing") or body.get("tenant_pairing_required"))
                or boolish(body.get("support_required"), default=False)
            )
            if preflight_requested:
                self._integration_preflight(name, body, candidates)
            if secret_file_paths(body) or body.get("tenant_pairing_required") or body.get("tenant_pairing") or body.get("support_required"):
                reason = "Integration requires secret, tenant, or Splunk Support-controlled setup."
                secret_files = [item["path"] for item in secret_file_paths(body)]
                self._add(
                    Action(
                        section="integrations",
                        operation="handoff",
                        target=name,
                        payload=handoff_payload(
                            reason,
                            required_inputs=[
                                key
                                for key in (*SECRET_FILE_KEYS, "tenant_pairing", "tenant_pairing_required", "support_required")
                                if key in body
                            ],
                            safe_next_command="bash skills/splunk-enterprise-security-config/scripts/setup.sh --spec es-config.yaml --mode validate",
                            docs_hint="Use stable local_conf for non-secret settings; complete OAuth, tenant pairing, and Support tasks outside the engine.",
                            blocking_secret_files=secret_files,
                            **{key: body.get(key) for key in ("tenant_pairing_required", "support_required") if key in body},
                        ),
                        apply_supported=False,
                        reason=reason,
                    )
                )

    def _cloud_support_evidence(self) -> None:
        connection = self.spec.get("connection") if isinstance(self.spec.get("connection"), dict) else {}
        cloud_support = connection.get("cloud_support") if isinstance(connection.get("cloud_support"), dict) else {}
        if spec_platform(self.spec) != "cloud" or not boolish(cloud_support.get("evidence_package"), default=False):
            return
        content_library = self.spec.get("content_library") if isinstance(self.spec.get("content_library"), dict) else {}
        requested_apps = []
        if boolish(content_library.get("install"), default=False):
            requested_apps.append(CONTENT_UPDATE_APP)
            if content_library_app_id(content_library, CONTENT_LIBRARY_APP):
                requested_apps.append(CONTENT_LIBRARY_APP)
        for name, body in (self.spec.get("integrations") or {}).items():
            if isinstance(body, dict) and (boolish(body.get("enabled"), default=False) or boolish(body.get("support_required"), default=False)):
                requested_apps.extend(INTEGRATION_APPS.get(name, ()))
        requested_apps = sorted(set(app for app in requested_apps if app))
        reason = "Splunk Cloud Support-managed ES setup is evidence-package only unless a documented ACS-supported path exists."
        self._add(
            Action(
                section="integrations",
                operation="cloud_support_evidence",
                target="splunk_cloud_support",
                payload=handoff_payload(
                    reason,
                    required_inputs=["Splunk Cloud stack name", "ACS app/index inventory", "Support case or admin approval"],
                    safe_next_command="bash skills/splunk-enterprise-security-config/scripts/setup.sh --spec es-config.yaml --mode export --output es-cloud-support-evidence.json",
                    docs_hint="Cloud writes stay limited to documented ACS-supported operations; Support-only ES setup remains handoff.",
                    requested_apps=requested_apps,
                    acs_supported_operations=["app inventory", "index inventory", "supported app install/update readiness", "search-head validation"],
                    requested_settings={
                        "content_library_install": boolish(content_library.get("install"), default=False),
                        "integrations": sorted((self.spec.get("integrations") or {}).keys()),
                    },
                ),
                apply_supported=False,
                reason=reason,
            )
        )

    def _integration_preflight(self, name: str, body: dict[str, Any], candidates: tuple[str, ...]) -> None:
        checks = secret_file_checks(body, self.project_root)
        endpoint = str(body.get("preflight_endpoint") or INTEGRATION_PREFLIGHT_ENDPOINTS.get(name, "")).strip()
        tenant_pairing = body.get("tenant_pairing") if isinstance(body.get("tenant_pairing"), dict) else {}
        reason = "Integration preflight is read-only; OAuth/token exchange and tenant pairing remain operator handoffs."
        self._add(
            Action(
                section="integrations",
                operation="integration_preflight",
                target=name,
                app=candidates[0] if candidates else None,
                endpoint=endpoint or None,
                payload=handoff_payload(
                    reason,
                    required_inputs=[
                        "required non-secret tenant fields",
                        "secret-file paths with 0600-style permissions",
                        "installed integration app",
                        "role/capability readiness",
                    ],
                    safe_next_command="bash skills/splunk-enterprise-security-config/scripts/setup.sh --spec es-config.yaml --mode validate",
                    docs_hint=INTEGRATION_DOC_HINTS.get(
                        name,
                        "Secret-dependent integrations are preflighted here; complete OAuth, tenant pairing, or Support-managed setup outside the engine.",
                    ),
                    candidate_apps=list(candidates),
                    secret_file_checks=checks,
                    tenant_pairing={
                        key: sanitize_live_value(value, key)
                        for key, value in tenant_pairing.items()
                        if key not in SECRET_FILE_KEYS and not redacts_value_for_key(key)
                    },
                    endpoint=endpoint,
                    support_required=boolish(body.get("support_required"), default=False),
                    non_secret_fields=sorted(
                        key
                        for key in body
                        if key
                        not in {
                            *SECRET_FILE_KEYS,
                            "secret_files",
                            "local_conf",
                            "tenant_pairing",
                        }
                    ),
                ),
                apply_supported=False,
                reason=reason,
            )
        )

    def _ta_for_indexers(self) -> None:
        section = self.spec.get("ta_for_indexers") or {}
        if not section:
            return
        body = section if isinstance(section, dict) else {"enabled": section}
        readiness_payload = dict(body)
        readiness_payload.setdefault("expected_package", TA_FOR_INDEXERS_APP)
        readiness_payload.setdefault("generated_bundle", str(self._default_ta_for_indexers_output()))
        readiness_payload.setdefault(
            "handoff",
            handoff_payload(
                "Generate readiness and redeploy plan; do not overwrite conflicting indexer apps automatically.",
                required_inputs=["ES package in splunk-ta/", "cluster-manager deployment context"],
                safe_next_command=(
                    "bash skills/splunk-enterprise-security-install/scripts/generate_ta_for_indexers.sh "
                    "--output-dir ta-for-indexers-rendered"
                ),
                docs_hint="Deploy the generated Splunk_TA_ForIndexers through the cluster manager after conflict review.",
            ),
        )
        self._add(
            Action(
                section="ta_for_indexers",
                operation="readiness",
                target=TA_FOR_INDEXERS_APP,
                payload=readiness_payload,
                apply_supported=False,
                reason="Generate readiness and redeploy plan; do not overwrite conflicting indexer apps automatically.",
            )
        )
        deploy_requested = boolish(body.get("deploy") or body.get("apply") or str(body.get("deploy_strategy") or "").lower() in {"apply", "deploy"})
        if not deploy_requested:
            return
        replace_existing = boolish(body.get("replace_existing"), default=False)
        payload = dict(body)
        payload.setdefault("output_dir", "ta-for-indexers-rendered")
        payload.setdefault("replace_existing", replace_existing)
        overwrite_policy = str(payload.get("overwrite_policy") or "").strip().lower()
        destructive_intent = replace_existing or overwrite_policy in {"replace_existing", "replace-generated", "replace_generated_only", "overwrite"}
        confirm_material = without_guard_fields(
            {
                key: value
                for key, value in payload.items()
                if key not in {"confirm_id", "handoff"}
            }
        )
        confirm_id = stable_confirm_id("ta_for_indexers_overwrite", TA_FOR_INDEXERS_APP, confirm_material)
        has_backup = bool(payload.get("backup_export"))
        confirm_matches = str(payload.get("confirm_id") or "") == confirm_id
        conflict_checks_clean = boolish(payload.get("conflict_checks_clean") or payload.get("clean_conflict_checks"), default=False)
        apply_supported = (
            deploy_requested
            and destructive_intent
            and has_backup
            and confirm_matches
            and conflict_checks_clean
        )
        deploy_reason = (
            ""
            if apply_supported
            else "TA for Indexers overwrite/deploy requires two-phase confirmation, backup export, and clean conflict checks."
        )
        if deploy_reason:
            payload["handoff"] = handoff_payload(
                deploy_reason,
                required_inputs=[
                    "replace_existing: true or overwrite_policy: replace_existing",
                    "backup_export path or artifact id",
                    f"confirm_id: {confirm_id}",
                    "conflict_checks_clean: true",
                ],
                safe_next_command=(
                    "bash skills/splunk-enterprise-security-install/scripts/generate_ta_for_indexers.sh "
                    "--output-dir ta-for-indexers-rendered --force"
                ),
                docs_hint="Indexer app overwrites stay guarded until the operator confirms replacement and conflict checks are clean.",
                confirm_id=confirm_id,
            )
        self._add(
            Action(
                section="ta_for_indexers",
                operation="deploy_ta_for_indexers",
                target=TA_FOR_INDEXERS_APP,
                payload=payload,
                apply_supported=apply_supported,
                reason=deploy_reason,
            )
        )

    @staticmethod
    def _default_ta_for_indexers_output() -> Path:
        return Path("ta-for-indexers-rendered")

    def _content_governance(self) -> None:
        section = self.spec.get("content_governance") or {}
        if not isinstance(section, dict):
            self._diag("error", "content_governance", "content_governance must be a mapping.")
            return
        if "test_mode" in section:
            self._add(
                Action(
                    section="content_governance",
                    operation="set_conf",
                    target="test_mode",
                    app="SA-TestModeControl",
                    endpoint="/servicesNS/nobody/SA-TestModeControl/configs/conf-inputs/test_mode",
                    payload={"disabled": splunk_bool(not boolish(section["test_mode"]))},
                )
            )
        importer = section.get("content_importer")
        if isinstance(importer, dict):
            payload = dict(importer)
            self._add(
                Action(
                    section="content_governance",
                    operation="set_conf",
                    target="ess_content_importer://content_importer",
                    app=APP_NAME,
                    endpoint=f"/servicesNS/nobody/{APP_NAME}/configs/conf-inputs/ess_content_importer%3A%2F%2Fcontent_importer",
                    payload=payload,
                )
            )
        if "content_versioning" in section:
            self._content_versioning(section["content_versioning"])

    def _content_versioning(self, value: Any) -> None:
        reason = "Inventory content versioning state and report manual conflict-resolution steps."
        if not isinstance(value, dict):
            self._add(
                Action(
                    section="content_governance",
                    operation="integration_inventory",
                    target="SA-ContentVersioning",
                    payload=handoff_payload(
                        reason,
                        required_inputs=["live SA-ContentVersioning state"],
                        docs_hint="Production/test toggles are supported only when declared explicitly with apply: true.",
                    ),
                    apply_supported=False,
                    reason=reason,
                )
            )
            return
        destructive_keys = [key for key in ("rollback", "delete", "conflict_resolution", "resolve_conflicts") if key in value]
        if destructive_keys:
            for key in destructive_keys:
                self._content_versioning_destructive_action(key, value.get(key), value)
            return
        payload: dict[str, Any] = {}
        if "mode" in value:
            mode = str(value["mode"]).strip().lower()
            if mode not in {"production", "test"}:
                self._diag("error", "content_governance", "content_versioning.mode must be production or test.", "SA-ContentVersioning")
                return
            payload["mode"] = mode
        if "production_mode" in value:
            payload["production_mode"] = splunk_bool(value["production_mode"])
        if "test_mode" in value:
            payload["test_mode"] = splunk_bool(value["test_mode"])
        if "enabled" in value:
            payload["disabled"] = splunk_bool(not boolish(value["enabled"]))
        if not payload or not boolish(value.get("apply"), default=False):
            self._add(
                Action(
                    section="content_governance",
                    operation="integration_inventory",
                    target="SA-ContentVersioning",
                    payload=handoff_payload(
                        "Content versioning changes require explicit production/test fields and apply: true.",
                        required_inputs=["mode: production|test or production_mode/test_mode", "apply: true"],
                        docs_hint="Read-only inventory remains the default.",
                        requested=value,
                    ),
                    apply_supported=False,
                    reason="Content versioning changes require explicit production/test fields and apply: true.",
                )
            )
            return
        self._add(
            Action(
                section="content_governance",
                operation="set_conf",
                target="content_versioning",
                app="SA-ContentVersioning",
                endpoint="/servicesNS/nobody/SA-ContentVersioning/configs/conf-content_versioning/content_versioning",
                payload=payload,
            )
        )

    def _content_versioning_destructive_action(self, key: str, requested: Any, parent: dict[str, Any]) -> None:
        requested_body = requested if isinstance(requested, dict) else {"target": requested}
        action_name = "delete" if key == "delete" else "rollback" if key == "rollback" else "conflict_resolution"
        target = f"SA-ContentVersioning/{action_name}"
        endpoint = str(requested_body.get("endpoint") or parent.get("endpoint") or "").strip()
        object_payload = without_guard_fields(
            {
                key: value
                for key, value in requested_body.items()
                if key not in {"endpoint", "confirm_id"}
            }
        )
        confirm_id = stable_confirm_id(f"content_versioning_{action_name}", target, object_payload)
        apply_requested = boolish(requested_body.get("apply", parent.get("apply")), default=False)
        backup_export = requested_body.get("backup_export", parent.get("backup_export"))
        confirm_matches = str(requested_body.get("confirm_id") or parent.get("confirm_id") or "") == confirm_id
        reason = "Content rollback/delete/conflict-resolution requires two-phase confirmation and backup evidence."
        if apply_requested and backup_export and confirm_matches and endpoint:
            self._add(
                Action(
                    section="content_governance",
                    operation="content_versioning_destructive_apply",
                    target=target,
                    app="SA-ContentVersioning",
                    endpoint=endpoint,
                    payload={
                        "action": action_name,
                        "object": object_payload,
                        "backup_export": backup_export,
                        "confirm_id": confirm_id,
                    },
                )
            )
            return
        required = [
            "apply: true",
            "backup_export path or artifact id",
            f"confirm_id: {confirm_id}",
        ]
        if not endpoint:
            required.append("documented content-versioning endpoint")
        self._add(
            Action(
                section="content_governance",
                operation="content_versioning_handoff",
                target=target,
                app="SA-ContentVersioning",
                endpoint=endpoint or None,
                payload=handoff_payload(
                    reason,
                    required_inputs=required,
                    safe_next_command="bash skills/splunk-enterprise-security-config/scripts/setup.sh --spec es-config.yaml --mode export --output es-content-before-change.json",
                    docs_hint="No single boolean can roll back, delete, or resolve ES content conflicts; preview emits the confirm_id for the exact requested action.",
                    confirm_id=confirm_id,
                    requested=object_payload,
                    backup_export=backup_export,
                ),
                apply_supported=False,
                reason=reason,
            )
        )

    def _package_conf_coverage(self) -> None:
        section = self.spec.get("package_conf_coverage") or {}
        if not section:
            return
        if isinstance(section, bool):
            section = {"inventory": section}
        if not isinstance(section, dict):
            self._diag("error", "package_conf_coverage", "package_conf_coverage must be a boolean or mapping.")
            return
        if boolish(section.get("apply"), default=False):
            self._diag("warn", "package_conf_coverage", "package_conf_coverage is inventory/export-only; apply was ignored.")
        payload = {
            "inventory": boolish(section.get("inventory"), default=True),
            "include_live": boolish(section.get("include_live") or section.get("live"), default=False),
            "families": section.get("families") or "all",
            "max_entries_per_family": str(section.get("max_entries_per_family", 25)),
        }
        self._add(
            Action(
                section="package_conf_coverage",
                operation="package_conf_inventory",
                target="es_package_conf_manifest",
                payload=payload,
                apply_supported=False,
                reason="Package .conf coverage is inventory/export-only; use existing first-class sections for supported writes.",
            )
        )

    def _validation(self) -> None:
        section = self.spec.get("validation") or {}
        if not isinstance(section, dict):
            return
        for search in listify(section.get("searches")):
            if isinstance(search, dict):
                name = str(search.get("name") or search.get("search") or "validation_search")
                spl = str(search.get("search") or "")
                # expect_rows defaults to True so a validation search that
                # returns zero events is treated as a failure (zero events on
                # `| tstats count where index=notable` means the data model is
                # not populated, which is what the operator wanted to learn).
                expect_rows = boolish(search.get("expect_rows"), default=True)
                raw_min = search.get("min_event_count")
                try:
                    min_event_count = int(raw_min) if raw_min is not None else None
                except (TypeError, ValueError):
                    min_event_count = None
                if min_event_count is None:
                    min_event_count = 1 if expect_rows else 0
                if min_event_count < 0:
                    min_event_count = 0
            else:
                name = str(search)
                spl = str(search)
                expect_rows = True
                min_event_count = 1
            self._add(
                Action(
                    section="validation",
                    operation="search_check",
                    target=name,
                    payload={
                        "search": spl,
                        "expect_rows": bool(expect_rows),
                        "min_event_count": int(min_event_count),
                    },
                    apply_supported=False,
                    reason="Validation searches are read-only and run in validate mode.",
                )
            )


class CredentialLoader:
    ALLOWED_KEYS = {
        "SPLUNK_PROFILE",
        "SPLUNK_SEARCH_API_URI",
        "SPLUNK_URI",
        "SPLUNK_USER",
        "SPLUNK_PASS",
        "SPLUNK_USERNAME",
        "SPLUNK_PASSWORD",
        "SPLUNK_VERIFY_SSL",
        "SPLUNK_CA_CERT",
    }

    def __init__(self, project_root: Path):
        self.project_root = project_root

    def load(self) -> dict[str, str]:
        # Repo-wide guidance: secrets MUST come from the credentials file, not
        # from environment variable prefixes. Prefer file values; only fall
        # back to env when the file is absent or the key is missing. Warn
        # (key only, never the value) when an env value would shadow a file
        # value so operators can fix surprising behavior.
        values: dict[str, str] = {}
        path = self._credential_path()
        file_values: dict[str, str] = {}
        if path and path.exists():
            file_values = self._parse_file(path)
            values.update(file_values)
        for key in self.ALLOWED_KEYS:
            env_value = os.environ.get(key)
            if not env_value:
                continue
            if key in file_values and env_value != file_values[key]:
                print(
                    f"WARN: env var {key} differs from credentials file; using file value. "
                    "Unset the env var or update the credentials file to match.",
                    file=sys.stderr,
                )
                continue
            values.setdefault(key, env_value)
        return values

    def _credential_path(self) -> Path | None:
        if os.environ.get("SPLUNK_CREDENTIALS_FILE"):
            return Path(os.environ["SPLUNK_CREDENTIALS_FILE"])
        local = self.project_root / "credentials"
        if local.exists():
            return local
        home = Path.home() / ".splunk" / "credentials"
        return home if home.exists() else None

    def _parse_file(self, path: Path) -> dict[str, str]:
        raw: dict[str, str] = {}
        profiles: dict[str, dict[str, str]] = {}
        profile_re = re.compile(r"PROFILE_([A-Za-z0-9_-]+)__([A-Za-z_][A-Za-z0-9_]*)$")
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = _strip_shell_quotes(value.strip())
            match = profile_re.fullmatch(key)
            if match:
                profile, actual = match.groups()
                if actual in self.ALLOWED_KEYS:
                    profiles.setdefault(profile, {})[actual] = value
                continue
            if key in self.ALLOWED_KEYS:
                raw[key] = value
        selected = os.environ.get("SPLUNK_PROFILE") or raw.get("SPLUNK_PROFILE") or ""
        merged = dict(raw)
        if selected and selected in profiles:
            merged.update(profiles[selected])
        return merged


def _strip_shell_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def summarize_saved_search(search: dict[str, Any]) -> dict[str, Any]:
    actions = str(search.get("actions") or "")
    action_set = {action.strip() for action in actions.split(",") if action.strip()}
    annotations = search.get("annotations") or search.get("action.correlationsearch.annotations")
    # An ES correlation search is identified strictly by action.correlationsearch.enabled.
    # A merely scheduled saved search is not a correlation search.
    correlation_flag = search.get("action.correlationsearch.enabled")
    return {
        "name": search.get("name"),
        "app": search.get("app"),
        "owner": search.get("owner"),
        "disabled": search.get("disabled"),
        "cron_schedule": search.get("cron_schedule"),
        "actions": actions,
        "has_notable_action": "notable" in action_set or bool(search.get("action.notable")),
        "has_risk_action": "risk" in action_set or bool(search.get("action.risk")),
        "is_correlation_search": boolish(correlation_flag),
        "annotations": annotations,
        "security_domain": search.get("action.notable.param.security_domain"),
        "urgency": search.get("action.notable.param.urgency"),
        "risk_score": search.get("action.risk.param._risk_score"),
    }


def summarize_conf_stanza(stanza: dict[str, Any]) -> dict[str, Any]:
    return {
        key: stanza.get(key)
        for key in (
            "name",
            "app",
            "disabled",
            "target",
            "category",
            "description",
            "filename",
            "url",
            "interval",
            "type",
            "weight",
        )
        if key in stanza
    }


def redacts_value_for_key(key: str) -> bool:
    lowered = key.lower()
    return any(word in lowered for word in ("pass", "password", "secret", "token", "api_key", "apikey", "session"))


def sanitize_text(text: Any, max_chars: int = 2000) -> str:
    sanitized = str(text)
    sanitized = re.sub(
        r"(?i)(password|pass|secret|token|api[_-]?key|apikey|session[_-]?key|client[_-]?secret)(\s*[:=]\s*)('[^']*'|\"[^\"]*\"|[^\s,}]+)",
        r"\1\2[REDACTED]",
        sanitized,
    )
    sanitized = re.sub(r"(?i)(Authorization:\s*(?:Splunk|Bearer)\s+)[^\s]+", r"\1[REDACTED]", sanitized)
    if len(sanitized) > max_chars:
        return sanitized[:max_chars] + "...[truncated]"
    return sanitized


def sanitize_live_value(value: Any, key: str = "") -> Any:
    if redacts_value_for_key(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {child_key: sanitize_live_value(child_value, child_key) for child_key, child_value in value.items()}
    if isinstance(value, list):
        return [sanitize_live_value(item, key) for item in value]
    if isinstance(value, str) and _looks_like_secret(value):
        return "[REDACTED]"
    return value


def clean_live_entry(entry: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in entry.items():
        if redacts_value_for_key(key):
            continue
        if key == "eai:data":
            cleaned["xml"] = sanitize_live_value(value, key)
            continue
        if key in {"eai:acl", "eai:attributes", "eai:roles"}:
            continue
        if key.startswith("eai:"):
            continue
        if key.startswith("_"):
            continue
        if value is None:
            continue
        cleaned[key] = sanitize_live_value(value, key)
    return cleaned


def export_entries(entries: list[dict[str, Any]], prefix: str = "") -> list[dict[str, Any]]:
    exported = []
    for entry in entries:
        item = clean_live_entry(entry)
        if prefix and isinstance(item.get("name"), str) and item["name"].startswith(prefix):
            item["name"] = item["name"][len(prefix) :]
        exported.append(item)
    return exported


def find_latest_ta_for_indexers_package(project_root: Path) -> Path | None:
    candidates = sorted((project_root / "ta-for-indexers-rendered").glob("Splunk_TA_ForIndexers*"))
    return candidates[-1].resolve() if candidates else None


def find_latest_es_package(project_root: Path) -> Path | None:
    package_dir = project_root / "splunk-ta"
    patterns = (
        "splunk-enterprise-security_*.spl",
        "splunk-enterprise-security_*.tgz",
        "splunk-enterprise-security_*.tar.gz",
    )
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(package_dir.glob(pattern))
    return sorted(candidates)[-1].resolve() if candidates else None


def package_conf_coverage_manifest(project_root: Path) -> dict[str, Any]:
    package = find_latest_es_package(project_root)
    if not package:
        return {
            "package_present": False,
            "package_path": "",
            "families": [],
            "unclassified": [],
            "export_notes": "No local Splunk Enterprise Security package was found under splunk-ta/.",
        }
    cache_key = (str(package), package.stat().st_mtime_ns)
    if cache_key in _PACKAGE_CONF_MANIFEST_CACHE:
        return _PACKAGE_CONF_MANIFEST_CACHE[cache_key]
    family_map: dict[str, dict[str, Any]] = {}

    def add_conf(path: str, text: str) -> None:
        parts = path.split("/")
        if len(parts) < 3 or parts[1] not in {"default", "local"} or not parts[-1].endswith(".conf"):
            return
        app = parts[0]
        family = parts[-1][:-5]
        stanzas = re.findall(r"^\[([^\]]+)\]", text, flags=re.M)
        item = family_map.setdefault(
            family,
            {
                "name": family,
                "apps": set(),
                "file_count": 0,
                "stanza_count": 0,
                "sample_stanzas": [],
            },
        )
        item["apps"].add(app)
        item["file_count"] += 1
        item["stanza_count"] += len(stanzas)
        for stanza in stanzas:
            if len(item["sample_stanzas"]) >= 10:
                break
            if stanza not in item["sample_stanzas"]:
                item["sample_stanzas"].append(stanza)

    def scan_tar(tf: tarfile.TarFile) -> None:
        for member in tf.getmembers():
            if not member.name.endswith(".conf"):
                continue
            source = tf.extractfile(member)
            if source is None:
                continue
            add_conf(member.name, source.read().decode("utf-8", errors="replace"))

    with tarfile.open(package) as outer:
        scan_tar(outer)
        for member in outer.getmembers():
            if not member.name.endswith((".spl", ".tgz", ".tar.gz")):
                continue
            source = outer.extractfile(member)
            if source is None:
                continue
            data = source.read()
            try:
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as inner:
                    scan_tar(inner)
            except tarfile.TarError:
                continue
    families = []
    unclassified = []
    for family, item in sorted(family_map.items()):
        managed_by, reason = PACKAGE_CONF_CLASSIFICATION.get(
            family,
            ("unclassified", "No package-level classification exists yet; review before automating."),
        )
        if managed_by == "unclassified":
            unclassified.append(family)
        families.append(
            {
                "name": family,
                "apps": sorted(item["apps"]),
                "file_count": item["file_count"],
                "stanza_count": item["stanza_count"],
                "sample_stanzas": item["sample_stanzas"],
                "managed_by": managed_by,
                "reason": reason,
            }
        )
    manifest = {
        "package_present": True,
        "package_path": str(package),
        "family_count": len(families),
        "families": families,
        "unclassified": unclassified,
        "export_notes": "Manifest is derived from the local ES package; file contents and secret storage are not exported.",
    }
    _PACKAGE_CONF_MANIFEST_CACHE.clear()
    _PACKAGE_CONF_MANIFEST_CACHE[cache_key] = manifest
    return manifest


def select_package_conf_families(manifest: dict[str, Any], requested: Any) -> list[dict[str, Any]]:
    families = [item for item in manifest.get("families", []) if isinstance(item, dict)]
    if requested in (None, "", "all"):
        return families
    wanted = {str(item).removesuffix(".conf") for item in listify(requested)}
    return [item for item in families if str(item.get("name")) in wanted]


def export_identity_sources(
    manager_inputs: list[dict[str, Any]],
    lookup_definitions: list[dict[str, Any]],
    lookup_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    definitions = {str(item.get("name") or ""): item for item in lookup_definitions}
    files = {str(item.get("name") or item.get("filename") or ""): item for item in lookup_files}
    exported = []
    for raw in manager_inputs:
        item = clean_live_entry(raw)
        if isinstance(item.get("name"), str) and item["name"].startswith("identity_manager://"):
            item["name"] = item["name"][len("identity_manager://") :]
        url = str(item.get("url") or "")
        if url.startswith("lookup://"):
            lookup_definition = url[len("lookup://") :]
            item["lookup_definition"] = lookup_definition
            definition = definitions.get(lookup_definition, {})
            if definition.get("filename"):
                filename = str(definition["filename"])
                item["lookup_file"] = filename
                lookup_file = files.get(filename, {})
                if definition.get("acl"):
                    item["lookup_definition_acl"] = sanitize_live_value(definition["acl"])
                if lookup_file.get("acl"):
                    item["lookup_file_acl"] = sanitize_live_value(lookup_file["acl"])
                if definition.get("fields_list"):
                    item["fields_list"] = definition["fields_list"]
        exported.append(item)
    return exported


def export_tags(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    exported = []
    for entry in entries:
        name = str(entry.get("name") or "")
        if "=" not in name:
            continue
        field, value = name.split("=", 1)
        tags = [
            key
            for key, tag_value in entry.items()
            if key not in {"name", "app", "owner", "acl"} and str(tag_value).lower() == "enabled"
        ]
        if tags:
            exported.append({"field": field, "value": value, "tags": tags})
    return exported


def export_named_mapping(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for entry in entries:
        item = clean_live_entry(entry)
        name = str(item.pop("name", "")).replace("alert_actions://", "")
        if name and item:
            mapped[name] = item
    return mapped


def export_navigation(entries: list[dict[str, Any]]) -> dict[str, Any]:
    exported = export_entries(entries)
    if not exported:
        return {}
    first = dict(exported[0])
    if "xml" not in first:
        return {}
    return first


def export_content_library_spec(inventory: dict[str, Any]) -> dict[str, Any]:
    content = inventory.get("content_library", {})
    subscription_entries = content.get("escu_subscription", [])
    escu: dict[str, Any] = {}
    if subscription_entries:
        first = clean_live_entry(subscription_entries[0])
        for key in ("subscription", "auto_update", "disabled"):
            if key in first:
                escu[key] = first[key]
        escu["subscription_inventory"] = export_entries(subscription_entries)
    saved_searches = content.get("escu_saved_searches", [])
    if saved_searches:
        escu["saved_searches_inventory"] = saved_searches
    result = {
        "install": False,
        "apps": content.get("apps", {}),
        "export_notes": "Brownfield export is non-mutating by default; set install or explicit ESCU fields before apply.",
    }
    if escu:
        result["escu"] = escu
    content_packs = content.get("content_packs", [])
    if content_packs:
        result["content_packs"] = content_packs
    return result


def export_content_governance_spec(inventory: dict[str, Any]) -> dict[str, Any]:
    content = inventory.get("content_governance", {})
    return {
        "content_versioning": {
            "apply": False,
            "mode": "production",
            "rollback": {
                "apply": False,
                "backup_export": "",
                "confirm_id": "",
            },
            "delete": {
                "apply": False,
                "backup_export": "",
                "confirm_id": "",
            },
        },
        "inventory": content,
        "export_notes": "Rollback/delete/conflict resolution and test-mode changes are exported as non-applying guarded intents.",
    }


def export_mission_control_spec(inventory: dict[str, Any]) -> dict[str, Any]:
    mission = inventory.get("mission_control", {})
    exported: dict[str, Any] = {
        "queues": export_entries(mission.get("queues", [])),
        "response_templates": export_entries(mission.get("response_templates", [])),
        "response_plans": export_entries(mission.get("response_plans", [])),
        "api_support": mission.get("api_support", {}),
    }
    search_entries = export_entries(mission.get("search_settings", []))
    if search_entries:
        exported["search"] = {"inventory": search_entries}
        for entry in search_entries:
            if entry.get("name") == "aq_sid_caching" and "workload_pool" in entry:
                exported["search"]["workload_pool"] = entry.get("workload_pool") or ""
                break
    lockdown_entries = export_entries(mission.get("rbac_lockdown", []))
    if lockdown_entries:
        first = clean_live_entry(lockdown_entries[0])
        exported["rbac_lockdown"] = {
            "apply": False,
            "enabled": not boolish(first.get("disabled"), default=True),
            "lock": boolish(first.get("lock"), default=True),
            "collections": comma_list(first.get("collections")),
            "indexes": comma_list(first.get("indexes")),
            "roles": comma_list(first.get("roles")),
            "inventory": lockdown_entries,
            "export_notes": "RBAC lockdown is exported disabled for apply; review before setting apply: true.",
        }
    exported["private_overrides"] = []
    exported["private_override_notes"] = (
        "Private Mission Control internals are inventory/export-first. Only allowlisted UI-backed fields are automated; "
        "other overrides require private_override, apply, backup_export, and preview confirm_id."
    )
    return exported


def export_exposure_analytics_spec(inventory: dict[str, Any]) -> dict[str, Any]:
    exposure = inventory.get("exposure_analytics", {})
    saved_searches = {
        str(item.get("name") or ""): item
        for item in exposure.get("saved_searches", [])
        if isinstance(item, dict)
    }
    macros = {
        str(item.get("name") or ""): clean_live_entry(item)
        for item in exposure.get("macros", [])
        if isinstance(item, dict)
    }
    population: dict[str, Any] = {}
    for target, search_name, prefix in (
        ("assets", "ea_gen_es_lookup_assets", "ea_es_assets"),
        ("identities", "ea_gen_es_lookup_identities", "ea_es_identities"),
    ):
        search = saved_searches.get(search_name)
        body: dict[str, Any] = {}
        if search:
            body["enabled"] = not boolish(search.get("disabled"), default=False)
            if search.get("cron_schedule"):
                body["cron_schedule"] = search["cron_schedule"]
            body["saved_search_inventory"] = search
        macro_keys = {
            "filter": f"{prefix}_filter_macro",
            "max_populate": f"{prefix}_max_populate",
            "fields": f"{prefix}_fields",
            "evals": f"{prefix}_evals",
            "renames": f"{prefix}_renames",
        }
        for key, macro_name in macro_keys.items():
            macro = macros.get(macro_name)
            if macro and "definition" in macro:
                body[key] = macro["definition"]
        if body:
            population[target] = body
    result: dict[str, Any] = {
        "app_present": exposure.get("app_present", False),
        "inventory": {
            "lookup_definitions": exposure.get("lookup_definitions", []),
            "entity_discovery_sources": exposure.get("entity_discovery_sources", []),
            "enrichment_rules": exposure.get("enrichment_rules", []),
            "rest_metadata": exposure.get("rest_metadata", []),
            "schema_status": exposure.get("schema_status", {}),
        },
        "sources": [
            {
                **entry,
                "apply": False,
                "conflict_policy": "create_only",
                "export_notes": "Exported source inventory is non-applying; add a documented endpoint and keep conflict_policy create_only before apply.",
            }
            for entry in exposure.get("entity_discovery_sources", [])
            if isinstance(entry, dict)
        ],
        "enrichment_rules": [
            {
                **entry,
                "apply": False,
                "conflict_policy": "create_only",
                "export_notes": "Exported enrichment inventory is non-applying; updates/deletes/conflicts remain operator-reviewed.",
            }
            for entry in exposure.get("enrichment_rules", [])
            if isinstance(entry, dict)
        ],
        "export_notes": "Entity-discovery source and enrichment-rule writes are create-only guarded; updates/deletes/schema conflicts stay handoff-only.",
    }
    if population:
        result["asset_identity_population"] = population
    return result


def export_package_conf_coverage_spec(inventory: dict[str, Any]) -> dict[str, Any]:
    package = inventory.get("package_conf_coverage", {})
    return {
        "inventory": True,
        "include_live": False,
        "families": "all",
        "manifest": package.get("families", []),
        "unclassified": package.get("unclassified", []),
        "export_notes": "Package .conf coverage is inventory/export-only; use first-class sections for supported writes.",
    }


def count_search_events(response: Any) -> int:
    if isinstance(response, dict):
        if isinstance(response.get("results"), list):
            return len(response["results"])
        if "result" in response:
            return 1
        if isinstance(response.get("entry"), list):
            return len(response["entry"])
        return 0
    if isinstance(response, list):
        return len(response)
    if isinstance(response, str):
        count = 0
        for line in response.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and "result" in parsed:
                count += 1
            elif isinstance(parsed, dict) and isinstance(parsed.get("results"), list):
                count += len(parsed["results"])
        return count
    return 0


class SplunkClient:
    def __init__(self, project_root: Path, spec: dict[str, Any]):
        self.project_root = project_root
        self.spec = spec
        credentials = CredentialLoader(project_root).load()
        connection = spec.get("connection") if isinstance(spec.get("connection"), dict) else {}
        self.base_url = str(
            connection.get("base_url")
            or credentials.get("SPLUNK_SEARCH_API_URI")
            or credentials.get("SPLUNK_URI")
            or ""
        ).rstrip("/")
        self.username = str(connection.get("username") or credentials.get("SPLUNK_USER") or credentials.get("SPLUNK_USERNAME") or "")
        self.password = str(credentials.get("SPLUNK_PASS") or credentials.get("SPLUNK_PASSWORD") or "")
        self.verify_ssl = boolish(connection.get("verify_ssl", credentials.get("SPLUNK_VERIFY_SSL")), default=True)
        self.ca_cert = str(connection.get("ca_cert") or credentials.get("SPLUNK_CA_CERT") or "")
        self.session_key = ""
        if not self.base_url:
            raise EsConfigError("Missing Splunk URI. Configure SPLUNK_SEARCH_API_URI or SPLUNK_URI in credentials.")
        if not self.username or not self.password:
            raise EsConfigError("Missing Splunk credentials. Run skills/shared/scripts/setup_credentials.sh.")
        self.context = None
        if self.ca_cert:
            self.context = ssl.create_default_context(cafile=self.ca_cert)
        elif not self.verify_ssl:
            self.context = ssl._create_unverified_context()

    def login(self) -> None:
        body = urlencode({"username": self.username, "password": self.password}).encode("utf-8")
        request = Request(f"{self.base_url}/services/auth/login", data=body, method="POST")
        with urlopen(request, context=self.context, timeout=30) as response:
            raw = response.read()
        root = _xml_fromstring(raw)
        session = root.findtext(".//sessionKey")
        if not session:
            raise EsConfigError("Splunk login did not return a session key.")
        self.session_key = session

    def headers(self) -> dict[str, str]:
        if not self.session_key:
            self.login()
        return {"Authorization": f"Splunk {self.session_key}", "Accept": "application/json"}

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None, json_payload: bool = False) -> Any:
        url = f"{self.base_url}{path}"
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}output_mode=json"
        data = None
        headers = self.headers()
        if payload is not None:
            if json_payload:
                data = json.dumps(payload).encode("utf-8")
                headers["Content-Type"] = "application/json"
            else:
                # `doseq=True` serializes list values as repeated key/value
                # pairs, which is the documented Splunk REST contract for
                # multi-valued fields on /services/authorization/roles
                # (`srchIndexesAllowed`, `srchIndexesDefault`, `importRoles`,
                # `capabilities`) and for inputs/saved-search list fields
                # such as `actions`. Splunk accepts repeated parameters here;
                # do NOT rejoin into a single comma-separated value or you
                # will silently drop everything except the first entry.
                data = urlencode(payload, doseq=True).encode("utf-8")
                headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urlopen(request, context=self.context, timeout=45) as response:
                raw = response.read()
        except HTTPError as exc:
            if exc.code == 404:
                raise KeyError(path) from exc
            body = exc.read().decode("utf-8", errors="replace")
            raise EsConfigError(f"{method} {path} failed with HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise EsConfigError(f"{method} {path} failed: {exc}") from exc
        if not raw:
            return {}
        text = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    @staticmethod
    def entries(response: Any) -> list[dict[str, Any]]:
        if isinstance(response, dict) and isinstance(response.get("entry"), list):
            result = []
            for entry in response["entry"]:
                content = dict(entry.get("content") or {})
                if entry.get("name"):
                    content.setdefault("name", entry["name"])
                acl = entry.get("acl")
                if isinstance(acl, dict):
                    content.setdefault("app", acl.get("app"))
                    content.setdefault("owner", acl.get("owner"))
                    content.setdefault("acl", sanitize_live_value(acl))
                result.append(content)
            return result
        if isinstance(response, dict):
            for key in ("results", "items", "data"):
                value = response.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        if isinstance(response, list):
            return [item for item in response if isinstance(item, dict)]
        return []

    def safe_entries(self, path: str) -> list[dict[str, Any]]:
        try:
            return self.entries(self.request("GET", path))
        except (KeyError, EsConfigError):
            return []

    def endpoint_status(self, path: str) -> dict[str, Any]:
        try:
            entries = self.entries(self.request("GET", path))
        except KeyError:
            return {"supported": False, "entry_count": 0, "reason": "not_found"}
        except EsConfigError as exc:
            return {"supported": False, "entry_count": 0, "reason": sanitize_text(exc)}
        return {"supported": True, "entry_count": len(entries)}

    def app_exists(self, app: str) -> bool:
        try:
            self.request("GET", f"/services/apps/local/{quote(app, safe='')}")
            return True
        except KeyError:
            return False

    def index_exists(self, index_name: str) -> bool:
        try:
            self.request("GET", f"/services/data/indexes/{quote(index_name, safe='')}")
            return True
        except KeyError:
            return False

    def create_index(self, payload: dict[str, Any]) -> str:
        name = str(payload["name"])
        if self.index_exists(name):
            return "unchanged"
        body = {key: value for key, value in payload.items() if key not in {"group"}}
        self.request("POST", "/services/data/indexes", body)
        return "created"

    def set_global_conf(self, conf: str, stanza: str, payload: dict[str, Any]) -> str:
        encoded = quote(stanza, safe="")
        try:
            self.request("POST", f"/services/configs/conf-{conf}/{encoded}", payload)
            return "updated"
        except KeyError:
            body = {"name": stanza}
            body.update(payload)
            self.request("POST", f"/services/configs/conf-{conf}", body)
            return "created"

    def set_conf(self, app: str, conf: str, stanza: str, payload: dict[str, Any]) -> str:
        encoded = quote(stanza, safe="")
        try:
            self.request("POST", f"/servicesNS/nobody/{quote(app, safe='')}/configs/conf-{conf}/{encoded}", payload)
            return "updated"
        except KeyError:
            body = {"name": stanza}
            body.update(payload)
            self.request("POST", f"/servicesNS/nobody/{quote(app, safe='')}/configs/conf-{conf}", body)
            return "created"

    def set_saved_search(self, app: str, name: str, payload: dict[str, Any], create_missing: bool = True) -> str:
        encoded = quote(name, safe="")
        try:
            self.request("POST", f"/servicesNS/nobody/{quote(app, safe='')}/saved/searches/{encoded}", payload)
            return "updated"
        except KeyError:
            if not create_missing:
                raise EsConfigError(
                    f"Saved search '{name}' was not found in app '{app}'. "
                    "Declare it under detections.custom with explicit SPL to create it."
                )
            body = {"name": name}
            body.update(payload)
            self.request("POST", f"/servicesNS/nobody/{quote(app, safe='')}/saved/searches", body)
            return "created"

    def set_role(self, name: str, payload: dict[str, Any]) -> str:
        encoded = quote(name, safe="")
        try:
            self.request("POST", f"/services/admin/roles/{encoded}", payload)
            return "updated"
        except KeyError:
            body = {"name": name}
            body.update(payload)
            self.request("POST", "/services/admin/roles", body)
            return "created"

    def _request_multipart(
        self,
        method: str,
        path: str,
        fields: dict[str, Any],
        file_field: str,
        file_path: Path,
        filename: str,
    ) -> Any:
        boundary = "----codex-splunk-es-config-boundary"
        chunks: list[bytes] = []
        for key, value in fields.items():
            if value is None:
                continue
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode("utf-8"),
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"),
                    f"{value}\r\n".encode("utf-8"),
                ]
            )
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{file_field}"; '
                    f'filename="{filename}"\r\nContent-Type: text/csv\r\n\r\n'
                ).encode("utf-8"),
                file_path.read_bytes(),
                b"\r\n",
                f"--{boundary}--\r\n".encode("utf-8"),
            ]
        )
        url = f"{self.base_url}{path}"
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}output_mode=json"
        request = Request(
            url,
            data=b"".join(chunks),
            headers={
                **self.headers(),
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method=method.upper(),
        )
        try:
            with urlopen(request, context=self.context, timeout=120) as response:
                raw = response.read()
        except HTTPError as exc:
            if exc.code == 404:
                raise KeyError(path) from exc
            body = exc.read().decode("utf-8", errors="replace")
            raise EsConfigError(f"{method} {path} failed with HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise EsConfigError(f"{method} {path} failed: {exc}") from exc
        if not raw:
            return {}
        text = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def _resolve_upload_file(self, file_name: str) -> Path:
        path = resolve_local_path(file_name, self.project_root)
        if not path.is_file():
            raise HandoffRequired(f"Local upload file was not found: {file_name}")
        size = path.stat().st_size
        if size > MAX_UPLOAD_BYTES:
            raise HandoffRequired(f"Local upload file exceeds the guarded {MAX_UPLOAD_BYTES} byte limit: {file_name}")
        return path

    def _set_acl_if_supported(self, path: str, acl: dict[str, Any]) -> bool:
        if not acl:
            return False
        payload = {
            key: value
            for key, value in acl.items()
            if key in {"owner", "sharing", "perms.read", "perms.write", "read", "write"}
        }
        if "read" in payload and "perms.read" not in payload:
            payload["perms.read"] = payload.pop("read")
        if "write" in payload and "perms.write" not in payload:
            payload["perms.write"] = payload.pop("write")
        if not payload:
            return False
        try:
            self.request("POST", path, payload)
        except KeyError:
            return False
        return True

    def upload_lookup_file(self, app: str, payload: dict[str, Any]) -> str:
        filename = str(payload.get("filename") or payload.get("lookup_file") or "").strip()
        file_name = str(payload.get("file") or "").strip()
        if not filename or not file_name:
            raise HandoffRequired("Lookup upload requires filename and local file path.")
        path = self._resolve_upload_file(file_name)
        app_quoted = quote(app, safe="")
        encoded = quote(filename, safe="")
        fields = {"name": filename}
        try:
            self._request_multipart(
                "POST",
                f"/servicesNS/nobody/{app_quoted}/data/lookup-table-files/{encoded}",
                fields,
                "eai:data",
                path,
                filename,
            )
            status = "updated"
        except KeyError:
            try:
                self._request_multipart(
                    "POST",
                    f"/servicesNS/nobody/{app_quoted}/data/lookup-table-files",
                    fields,
                    "eai:data",
                    path,
                    filename,
                )
                status = "uploaded"
            except KeyError as exc:
                raise HandoffRequired("Lookup-file upload endpoint is not available on this Splunk deployment.") from exc
        acl = payload.get("acl") if isinstance(payload.get("acl"), dict) else {}
        definition_acl = payload.get("definition_acl") if isinstance(payload.get("definition_acl"), dict) else {}
        lookup_definition = str(payload.get("lookup_definition") or "").strip()
        acl_updates = []
        if self._set_acl_if_supported(f"/servicesNS/nobody/{app_quoted}/data/lookup-table-files/{encoded}/acl", acl):
            acl_updates.append("lookup_file_acl")
        if lookup_definition and self._set_acl_if_supported(
            f"/servicesNS/nobody/{app_quoted}/configs/conf-transforms/{quote(lookup_definition, safe='')}/acl",
            definition_acl or acl,
        ):
            acl_updates.append("lookup_definition_acl")
        return f"{status}:{','.join(acl_updates)}" if acl_updates else status

    def upload_threat_intel(self, payload: dict[str, Any]) -> str:
        file_name = str(payload.get("file") or payload.get("path") or "").strip()
        upload_format = str(payload.get("format") or "").strip().lower()
        if upload_format not in THREAT_UPLOAD_FORMATS:
            raise HandoffRequired("Threat-intel upload format must be one of csv, stix, or openioc.")
        path = self._resolve_upload_file(file_name)
        fields = {
            key: value
            for key, value in payload.items()
            if key not in {"file", "path", "apply", "enabled", "upload"} and not isinstance(value, (dict, list))
        }
        fields.setdefault("format", upload_format)
        fields.setdefault("name", path.name)
        try:
            self._request_multipart(
                "POST",
                f"/servicesNS/nobody/{THREAT_APP}/data/threat_intel/upload",
                fields,
                "file",
                path,
                path.name,
            )
        except KeyError as exc:
            raise HandoffRequired("Threat-intel upload endpoint is not available on this ES deployment.") from exc
        return "uploaded"

    def list_saved_searches(self, app: str) -> list[dict[str, Any]]:
        return self.entries(self.request("GET", f"/servicesNS/nobody/{quote(app, safe='')}/saved/searches?count=0"))

    def post_endpoint(self, path: str, payload: dict[str, Any]) -> str:
        """Generic form-encoded POST to a preformed Splunk endpoint.

        Falls back to a collection-level POST with the 'name' field if the
        endpoint does not exist yet (mirrors the set_conf/set_saved_search
        upsert semantics for handler endpoints).
        """

        if not path:
            raise EsConfigError("post_endpoint requires a non-empty endpoint path.")
        try:
            self.request("POST", path, payload)
            return "updated"
        except KeyError:
            parent, _, leaf = path.rpartition("/")
            if not parent:
                raise
            body = {"name": unquote(leaf)}
            body.update(payload)
            self.request("POST", parent, body)
            return "created"

    def run_search(self, search: str) -> dict[str, Any]:
        response = self.request(
            "POST",
            "/services/search/jobs/export",
            {"search": search, "exec_mode": "oneshot", "output_mode": "json"},
        )
        return {"event_count": count_search_events(response), "raw_type": type(response).__name__}

    def package_conf_coverage_inventory(self) -> dict[str, Any]:
        root = getattr(self, "project_root", Path.cwd())
        manifest = package_conf_coverage_manifest(root)
        spec = getattr(self, "spec", {})
        section = spec.get("package_conf_coverage") if isinstance(spec.get("package_conf_coverage"), dict) else {}
        if not section:
            return {**manifest, "live": []}
        selected = select_package_conf_families(manifest, section.get("families") or "all")
        include_live = boolish(section.get("include_live") or section.get("live"), default=False)
        try:
            max_entries = int(section.get("max_entries_per_family", 25))
        except (TypeError, ValueError):
            max_entries = 25
        if not include_live:
            return {**manifest, "families": selected, "live": []}
        live = []
        for family in selected:
            name = str(family.get("name") or "")
            if not name or name == "passwords":
                continue
            family_entries = []
            for app in family.get("apps", []):
                entries = export_entries(
                    self.safe_entries(f"/servicesNS/nobody/{quote(str(app), safe='')}/configs/conf-{quote(name, safe='')}?count=0")
                )
                if max_entries > 0:
                    entries = entries[:max_entries]
                family_entries.append(
                    {
                        "app": app,
                        "entry_count": len(entries),
                        "entries": entries,
                        "truncated": max_entries > 0 and len(entries) >= max_entries,
                    }
                )
            live.append({"name": name, "apps": family_entries})
        return {**manifest, "families": selected, "live": live}

    def inventory(self) -> dict[str, Any]:
        apps = [
            APP_NAME,
            IDENTITY_APP,
            THREAT_APP,
            MISSION_CONTROL_APP,
            AUDIT_APP,
            UTILS_APP,
            CONTENT_UPDATE_APP,
            CONTENT_LIBRARY_APP,
            "SA-Detections",
            "SA-ContentVersioning",
            "SA-TestModeControl",
            "DA-ESS-UEBA",
            TA_FOR_INDEXERS_APP,
            "splunk_cloud_connect",
            EXPOSURE_ANALYTICS_APP,
        ]
        app_presence = {app: self.app_exists(app) for app in apps}
        saved_searches = self.safe_entries("/servicesNS/-/-/saved/searches?count=0")
        if not saved_searches and app_presence.get(APP_NAME):
            saved_searches = self.safe_entries(f"/servicesNS/nobody/{quote(APP_NAME, safe='')}/saved/searches?count=0")
        summarized_searches = [summarize_saved_search(search) for search in saved_searches]
        detection_searches = [
            search
            for search in summarized_searches
            if search.get("is_correlation_search") or search.get("has_notable_action") or search.get("has_risk_action")
        ]
        threat_inputs = [
            summarize_conf_stanza(item)
            for item in self.safe_entries(f"/servicesNS/nobody/{THREAT_APP}/configs/conf-inputs?count=0")
            if str(item.get("name") or "").startswith("threatlist://")
        ]
        identity_inputs = [
            summarize_conf_stanza(item)
            for item in self.safe_entries(f"/servicesNS/nobody/{IDENTITY_APP}/configs/conf-inputs?count=0")
            if str(item.get("name") or "").startswith("identity_manager://")
        ]
        lookup_definitions = [
            summarize_conf_stanza(item)
            for item in self.safe_entries(f"/servicesNS/nobody/{IDENTITY_APP}/configs/conf-transforms?count=0")
            if item.get("filename")
        ]
        lookup_files = export_entries(self.safe_entries(f"/servicesNS/nobody/{IDENTITY_APP}/data/lookup-table-files?count=0"))
        threat_uploads = export_entries(self.safe_entries(f"/servicesNS/nobody/{THREAT_APP}/data/threat_intel/upload?count=0"))
        mission_control_inventory = {
            key: self.safe_entries(path) for key, path in MISSION_CONTROL_ENDPOINTS.items()
        }
        mission_control_inventory["api_support"] = {
            key: self.endpoint_status(path) for key, path in MISSION_CONTROL_ENDPOINTS.items()
        }
        mission_control_inventory["search_settings"] = export_entries(
            self.safe_entries(f"/servicesNS/nobody/{MISSION_CONTROL_APP}/configs/conf-mc_search?count=0")
        )
        mission_control_inventory["rbac_lockdown"] = [
            item
            for item in export_entries(
                self.safe_entries(f"/servicesNS/nobody/{MISSION_CONTROL_APP}/configs/conf-inputs?count=0")
            )
            if str(item.get("name") or "").startswith("lock_unlock_resources")
        ]
        integration_inventory = {
            name: {"apps": {app: app_presence.get(app, False) for app in candidates}}
            for name, candidates in INTEGRATION_APPS.items()
        }
        if spec_platform(getattr(self, "spec", {})) == "cloud":
            integration_inventory["cloud_support"] = {
                "acs_supported_operations": [
                    "app inventory",
                    "index inventory",
                    "supported app install/update readiness",
                    "search-head validation",
                ],
                "support_managed": True,
                "export_notes": "Use preview/export evidence for Support-managed Cloud ES setup; unsupported Cloud REST writes are not attempted.",
            }
        extended_inventory = {
            section: export_entries(self.safe_entries(path.format(app=app)))
            for section, (app, path) in EXTENDED_INVENTORY_ENDPOINTS.items()
        }
        content_library_inventory = {
            "apps": {
                CONTENT_UPDATE_APP: app_presence.get(CONTENT_UPDATE_APP, False),
                CONTENT_LIBRARY_APP: app_presence.get(CONTENT_LIBRARY_APP, False),
            },
            "escu_subscription": export_entries(
                self.safe_entries(f"/servicesNS/nobody/{CONTENT_UPDATE_APP}/configs/conf-escu_subscription?count=0")
            ),
            "escu_saved_searches": [
                summarize_saved_search(item)
                for item in self.safe_entries(f"/servicesNS/nobody/{CONTENT_UPDATE_APP}/saved/searches?count=0")
            ],
            "content_packs": export_entries(
                self.safe_entries(f"/servicesNS/nobody/{CONTENT_LIBRARY_APP}/configs/conf-content_packs?count=0")
            ),
        }
        root = getattr(self, "project_root", Path.cwd())
        ta_package = find_latest_ta_for_indexers_package(root)
        ta_state = {
            "installed": app_presence.get(TA_FOR_INDEXERS_APP, False),
            "package_path": str(ta_package) if ta_package else "",
            "generated_bundle_dir": str((root / "ta-for-indexers-rendered").resolve()),
            "conflict_risk": "installed_existing_app" if app_presence.get(TA_FOR_INDEXERS_APP, False) else "none",
        }
        content_governance_inventory = {
            "SA-ContentVersioning": app_presence.get("SA-ContentVersioning", False),
            "SA-TestModeControl": app_presence.get("SA-TestModeControl", False),
            "SA-Detections": app_presence.get("SA-Detections", False),
            "content_versioning": export_entries(
                self.safe_entries("/servicesNS/nobody/SA-ContentVersioning/configs/conf-content_versioning?count=0")
            ),
            "test_mode": export_entries(
                self.safe_entries("/servicesNS/nobody/SA-TestModeControl/configs/conf-inputs?count=0")
            ),
            "detections_content": [
                summarize_saved_search(item)
                for item in self.safe_entries("/servicesNS/nobody/SA-Detections/saved/searches?count=0")
            ],
            "content_importer": export_entries(
                self.safe_entries(f"/servicesNS/nobody/{APP_NAME}/configs/conf-inputs?count=0")
            ),
        }
        exposure_inventory = {
            "app_present": app_presence.get(EXPOSURE_ANALYTICS_APP, False),
            "saved_searches": [
                summarize_saved_search(item)
                for item in self.safe_entries(f"/servicesNS/nobody/{EXPOSURE_ANALYTICS_APP}/saved/searches?count=0")
            ],
            "macros": export_entries(
                self.safe_entries(f"/servicesNS/nobody/{EXPOSURE_ANALYTICS_APP}/admin/macros?count=0")
            ),
            "lookup_definitions": export_entries(
                self.safe_entries(f"/servicesNS/nobody/{EXPOSURE_ANALYTICS_APP}/configs/conf-transforms?count=0")
            ),
            "entity_discovery_sources": export_entries(
                self.safe_entries(f"/servicesNS/nobody/{EXPOSURE_ANALYTICS_APP}/configs/conf-ea_sources?count=0")
            ),
            "enrichment_rules": export_entries(
                self.safe_entries(f"/servicesNS/nobody/{EXPOSURE_ANALYTICS_APP}/configs/conf-ea_enrichment_rules?count=0")
            ),
            "rest_metadata": export_entries(
                self.safe_entries(f"/servicesNS/nobody/{EXPOSURE_ANALYTICS_APP}/configs/conf-restmap?count=0")
            ),
            "schema_status": {
                "entity_discovery_sources": self.endpoint_status(f"/servicesNS/nobody/{EXPOSURE_ANALYTICS_APP}/configs/conf-ea_sources?count=0"),
                "enrichment_rules": self.endpoint_status(f"/servicesNS/nobody/{EXPOSURE_ANALYTICS_APP}/configs/conf-ea_enrichment_rules?count=0"),
            },
        }
        package_conf_inventory = self.package_conf_coverage_inventory()
        return {
            "apps": app_presence,
            "indexes": {group: {idx: self.index_exists(idx) for idx in indexes} for group, indexes in INDEX_GROUPS.items()},
            "assets": {
                "identity_manager_inputs": [item for item in identity_inputs if item.get("target") == "asset"],
                "lookup_files": lookup_files,
            },
            "identities": {
                "identity_manager_inputs": [item for item in identity_inputs if item.get("target") == "identity"],
                "lookup_files": lookup_files,
            },
            "lookup_definitions": lookup_definitions,
            "threat_intel": {"threatlist_inputs": threat_inputs, "uploads": threat_uploads},
            "detections": {
                "saved_search_count": len(summarized_searches),
                "correlation_search_count": len(detection_searches),
                "risk_action_count": sum(1 for search in summarized_searches if search.get("has_risk_action")),
                "notable_action_count": sum(1 for search in summarized_searches if search.get("has_notable_action")),
                "searches": detection_searches,
            },
            "mission_control": mission_control_inventory,
            "integrations": integration_inventory,
            **extended_inventory,
            "exposure_analytics": exposure_inventory,
            "content_library": content_library_inventory,
            "ta_for_indexers": ta_state,
            "content_governance": content_governance_inventory,
            "package_conf_coverage": package_conf_inventory,
        }


class Runner:
    def __init__(
        self,
        project_root: Path,
        spec: dict[str, Any],
        *,
        stop_on_error: bool = False,
        strict: bool = False,
    ):
        self.project_root = project_root
        self.spec = normalize_spec(spec)
        self.plan = PlanBuilder(spec, project_root, strict=strict).build()
        self.stop_on_error = bool(stop_on_error)
        self.strict = bool(strict)

    def preview(self) -> dict[str, Any]:
        return {"mode": "preview", **self.plan}

    def apply(self) -> dict[str, Any]:
        client = SplunkClient(self.project_root, self.spec)
        results = []
        stopped_at: dict[str, Any] | None = None
        for action_dict in self.plan["actions"]:
            action = Action(**action_dict)
            if stopped_at is not None:
                # When --stop-on-error fires, mark every remaining action as
                # 'skipped' so operators can see exactly which work did NOT
                # run. There is no rollback; previously-applied actions stay
                # applied.
                results.append({
                    "target": action.target,
                    "operation": action.operation,
                    "status": "skipped",
                    "reason": "Skipped because --stop-on-error tripped on a prior action.",
                })
                continue
            if not action.apply_supported:
                results.append({"target": action.target, "operation": action.operation, "status": "handoff", "reason": action.reason})
                continue
            try:
                status = self._apply_action(client, action)
            except HandoffRequired as exc:
                results.append({"target": action.target, "operation": action.operation, "status": "handoff", "reason": sanitize_text(exc)})
            except Exception as exc:  # noqa: BLE001 - preserve action context for operators
                failure = {"target": action.target, "operation": action.operation, "status": "failed", "error": sanitize_text(exc)}
                results.append(failure)
                if self.stop_on_error:
                    stopped_at = failure
            else:
                results.append({"target": action.target, "operation": action.operation, "status": status})
        payload: dict[str, Any] = {"mode": "apply", **self.plan, "results": results}
        if stopped_at is not None:
            payload["stopped_on_error"] = True
            payload["stopped_at"] = stopped_at
        return payload

    def validate(self) -> dict[str, Any]:
        client = SplunkClient(self.project_root, self.spec)
        inventory = client.inventory()
        checks = []
        search_checks = []
        for action_dict in self.plan["actions"]:
            action = Action(**action_dict)
            if action.operation == "create_index":
                checks.append({"target": action.target, "operation": action.operation, "ok": client.index_exists(action.target)})
            elif action.operation == "search_check":
                search = str(action.payload.get("search") or "")
                # `expect_rows` and `min_event_count` come from the planner
                # (see Builder._validation). Older plans without these fields
                # default to expecting at least one event so behavior is
                # backward-compatible only on plans that already declared
                # rows-required searches.
                expect_rows = bool(action.payload.get("expect_rows", True))
                try:
                    min_event_count = int(action.payload.get("min_event_count", 1 if expect_rows else 0))
                except (TypeError, ValueError):
                    min_event_count = 1 if expect_rows else 0
                if min_event_count < 0:
                    min_event_count = 0
                check = {
                    "name": action.target,
                    "search": search,
                    "expect_rows": expect_rows,
                    "min_event_count": min_event_count,
                }
                try:
                    result = client.run_search(search)
                except Exception as exc:  # noqa: BLE001 - validation must report all checks
                    check.update({"ok": False, "event_count": 0, "error": sanitize_text(exc)})
                else:
                    event_count = int(result.get("event_count", 0))
                    check["event_count"] = event_count
                    if event_count >= min_event_count:
                        check["ok"] = True
                    else:
                        check["ok"] = False
                        check["reason"] = (
                            f"Returned {event_count} event(s); expected at least {min_event_count}."
                        )
                search_checks.append(check)
            elif action.section == "mission_control" and action.operation.endswith("_api") and action.endpoint:
                status = client.endpoint_status(action.endpoint)
                checks.append(
                    {
                        "target": action.target,
                        "operation": action.operation,
                        "app": action.app,
                        "endpoint": action.endpoint,
                        "api_supported": status.get("supported", False),
                        "entry_count": status.get("entry_count", 0),
                        "apply_intent": action.apply_supported,
                    }
                )
            elif action.operation == "integration_preflight":
                endpoint_status = client.endpoint_status(action.endpoint) if action.endpoint else {"supported": False, "reason": "no_endpoint"}
                app_states = {
                    app: client.app_exists(app)
                    for app in action.payload.get("candidate_apps", [])
                }
                checks.append(
                    {
                        "target": action.target,
                        "operation": action.operation,
                        "apps": app_states,
                        "endpoint": action.endpoint,
                        "endpoint_status": endpoint_status,
                        "secret_file_checks": action.payload.get("secret_file_checks", []),
                        "ok": all(app_states.values()) and all(item.get("exists") and item.get("is_file") for item in action.payload.get("secret_file_checks", [])),
                    }
                )
            elif action.operation == "cloud_support_evidence":
                checks.append(
                    {
                        "target": action.target,
                        "operation": action.operation,
                        "ok": True,
                        "evidence_package": action.payload,
                    }
                )
            elif action.section == "exposure_analytics" and action.operation in {"exposure_schema_check", "exposure_schema_apply"}:
                status = client.endpoint_status(action.endpoint) if action.endpoint else {"supported": False, "reason": "missing_endpoint"}
                checks.append(
                    {
                        "target": action.target,
                        "operation": action.operation,
                        "endpoint": action.endpoint,
                        "endpoint_status": status,
                        "schema_classification": action.payload.get("schema_classification"),
                        "apply_intent": action.apply_supported,
                        "ok": action.payload.get("schema_classification") == "create_only_safe" and bool(status.get("supported")),
                    }
                )
            elif action.operation in {"content_versioning_handoff", "content_versioning_destructive_apply", "deploy_ta_for_indexers", "private_override_handoff"}:
                checks.append(
                    {
                        "target": action.target,
                        "operation": action.operation,
                        "apply_intent": action.apply_supported,
                        "confirm_id": action.payload.get("confirm_id") or (action.payload.get("handoff") or {}).get("confirm_id"),
                        "backup_export": action.payload.get("backup_export") or (action.payload.get("handoff") or {}).get("backup_export"),
                        "ok": action.apply_supported,
                    }
                )
            elif action.app:
                checks.append({"target": action.target, "operation": action.operation, "app": action.app, "app_present": client.app_exists(action.app)})
        return {"mode": "validate", **self.plan, "inventory": inventory, "checks": checks, "search_checks": search_checks}

    def inventory(self) -> dict[str, Any]:
        client = SplunkClient(self.project_root, self.spec)
        return {"mode": "inventory", "inventory": client.inventory(), "plan": self.plan}

    def export(self) -> dict[str, Any]:
        client = SplunkClient(self.project_root, self.spec)
        inventory = client.inventory()
        exported = {
            "baseline": {"enabled": True, "lookup_order": True, "managed_roles": ["ess_analyst", "ess_user"]},
            "indexes": {"groups": [group for group, states in inventory["indexes"].items() if all(states.values())]},
            "assets": export_identity_sources(
                inventory.get("assets", {}).get("identity_manager_inputs", []),
                inventory.get("lookup_definitions", []),
                inventory.get("assets", {}).get("lookup_files", []),
            ),
            "identities": export_identity_sources(
                inventory.get("identities", {}).get("identity_manager_inputs", []),
                inventory.get("lookup_definitions", []),
                inventory.get("identities", {}).get("lookup_files", []),
            ),
            "threat_intel": {
                "threatlists": export_entries(inventory.get("threat_intel", {}).get("threatlist_inputs", []), "threatlist://"),
                "uploads": [
                    {
                        **entry,
                        "apply": False,
                        "export_notes": "Threat-intel uploads are exported as metadata only; file contents are never exported.",
                    }
                    for entry in export_entries(inventory.get("threat_intel", {}).get("uploads", []))
                ],
            },
            "detections": {"inventory": True, "existing": inventory.get("detections", {}).get("searches", [])},
            "urgency": {"matrix": export_entries(inventory.get("urgency", []))},
            "adaptive_response": export_named_mapping(inventory.get("adaptive_response", [])),
            "notable_suppressions": export_entries(inventory.get("notable_suppressions", []), "notable_suppression://"),
            "log_review": {"entries": export_entries(inventory.get("log_review", []))},
            "use_cases": export_entries(inventory.get("use_cases", [])),
            "governance": export_entries(inventory.get("governance", [])),
            "macros": export_entries(inventory.get("macros", [])),
            "eventtypes": export_entries(inventory.get("eventtypes", [])),
            "tags": export_tags(inventory.get("tags", [])),
            "navigation": export_navigation(inventory.get("navigation", [])),
            "glass_tables": export_entries(inventory.get("glass_tables", [])),
            "exposure_analytics": export_exposure_analytics_spec(inventory),
            "content_library": export_content_library_spec(inventory),
            "integrations": {
                name: {
                    "enabled": any(inventory["apps"].get(app, False) for app in apps),
                    "preflight": False,
                    "tenant_pairing": {"required": False},
                    "export_notes": "Secret, tenant pairing, OAuth, and Support-managed setup are not exported.",
                }
                for name, apps in INTEGRATION_APPS.items()
            },
            "mission_control": export_mission_control_spec(inventory),
            "ta_for_indexers": {
                **inventory.get("ta_for_indexers", {}),
                "enabled": True,
                "deploy": False,
                "replace_existing": False,
                "overwrite_policy": "preview_only",
                "backup_export": "",
                "confirm_id": "",
                "export_notes": "Generated bundles and indexer deployment remain guarded; no overwrite is exported.",
            },
            "content_governance": export_content_governance_spec(inventory),
            "package_conf_coverage": export_package_conf_coverage_spec(inventory),
        }
        return {"mode": "export", "export": exported, "inventory": inventory}

    def _apply_action(self, client: SplunkClient, action: Action) -> str:
        if action.operation == "create_index":
            return client.create_index(action.payload)
        if action.operation == "set_global_conf":
            _, stanza = action.target.split("/", 1)
            return client.set_global_conf("limits", stanza, action.payload)
        if action.operation == "set_conf":
            conf, stanza = self._conf_and_stanza(action)
            return client.set_conf(action.app or APP_NAME, conf, stanza, action.payload)
        if action.operation == "set_lookup_definition":
            return client.set_conf(action.app or IDENTITY_APP, "transforms", action.target, action.payload)
        if action.operation == "upload_lookup_file":
            return client.upload_lookup_file(action.app or IDENTITY_APP, action.payload)
        if action.operation == "upload_threat_intel":
            return client.upload_threat_intel(action.payload)
        if action.operation == "set_macro":
            return client.set_conf(action.app or "Splunk_SA_CIM", "macros", action.target, action.payload)
        if action.operation == "set_saved_search":
            return client.set_saved_search(action.app or APP_NAME, action.target, action.payload, create_missing=False)
        if action.operation == "create_saved_search":
            return client.set_saved_search(action.app or APP_NAME, action.target, action.payload, create_missing=True)
        if action.operation == "set_correlation_metadata":
            payload = {key: value for key, value in action.payload.items() if key != "_app_search_order"}
            search_order = action.payload.get("_app_search_order") or []
            if isinstance(search_order, list) and search_order:
                # Discover the owning app at apply time. ES OOTB correlation
                # rules live in SA-* / DA-ESS-* apps; the same rule name is
                # not present in every app, so we GET-probe in priority order
                # and POST to the first app that resolves.
                discovered_app = None
                for candidate in search_order:
                    if not isinstance(candidate, str) or not candidate.strip():
                        continue
                    candidate = candidate.strip()
                    probe_path = (
                        f"/servicesNS/nobody/{candidate}/admin/correlationsearches/"
                        f"{quote(action.target, safe='')}"
                    )
                    try:
                        client.request("GET", probe_path)
                    except KeyError:
                        continue
                    except EsConfigError:
                        # Treat unexpected HTTP errors as "not this app" and
                        # keep probing; the final POST will surface the real
                        # error if no app accepts the metadata.
                        continue
                    discovered_app = candidate
                    break
                if discovered_app is None:
                    raise EsConfigError(
                        f"Correlation metadata for '{action.target}' not found in any of the candidate apps: "
                        f"{', '.join(search_order)}. Set correlation_metadata.app explicitly."
                    )
                endpoint = (
                    f"/servicesNS/nobody/{discovered_app}/admin/correlationsearches/"
                    f"{quote(action.target, safe='')}"
                )
                return client.post_endpoint(endpoint, payload)
            return client.post_endpoint(action.endpoint or "", payload)
        if action.operation == "install_app":
            if client.app_exists(action.target):
                return "unchanged"
            return self._install_app(action)
        if action.operation == "deploy_ta_for_indexers":
            return self._deploy_ta_for_indexers(client, action)
        if action.operation == "set_role":
            return client.set_role(action.target, action.payload)
        if action.operation == "set_eventtype":
            return client.post_endpoint(action.endpoint or "", action.payload)
        if action.operation == "set_tag":
            return client.post_endpoint(action.endpoint or "", action.payload)
        if action.operation == "set_navigation":
            return client.post_endpoint(action.endpoint or "", action.payload)
        if action.operation == "set_view":
            return client.post_endpoint(action.endpoint or "", action.payload)
        if action.operation == "post_endpoint":
            return client.post_endpoint(action.endpoint or "", action.payload)
        if action.operation == "exposure_schema_apply":
            return client.post_endpoint(action.endpoint or "", action.payload.get("object") or {})
        if action.operation == "content_versioning_destructive_apply":
            return client.post_endpoint(action.endpoint or "", action.payload.get("object") or {})
        if action.operation == "set_kv_collection":
            return client.post_endpoint(action.endpoint or "", action.payload)
        if action.operation == "set_acl":
            # ACL endpoints don't support create-on-missing via collection POST.
            client.request("POST", action.endpoint or "", action.payload)
            return "updated"
        if action.operation.endswith("_api") and action.endpoint:
            try:
                client.request("POST", action.endpoint, action.payload, json_payload=True)
            except KeyError as exc:
                raise HandoffRequired("Mission Control API endpoint is not available on this ES deployment.") from exc
            return "posted"
        raise EsConfigError(f"Unsupported apply action: {action.operation}")

    def _install_app(self, action: Action) -> str:
        app_id = str(action.payload.get("app_id") or "").strip()
        if not app_id:
            raise EsConfigError(f"Content-library app install for {action.target} requires an app_id.")
        installer = self.project_root / "skills" / "splunk-app-install" / "scripts" / "install_app.sh"
        cmd = ["bash", str(installer), "--source", "splunkbase", "--app-id", app_id, "--update"]
        if action.payload.get("app_version"):
            cmd.extend(["--app-version", str(action.payload["app_version"])])
        completed = subprocess.run(
            cmd,
            cwd=self.project_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if completed.returncode != 0:
            raise EsConfigError(
                f"install_app failed for {action.target} (exit {completed.returncode}): "
                f"{sanitize_text(completed.stdout)}"
            )
        return "installed"

    def _deploy_ta_for_indexers(self, client: SplunkClient, action: Action) -> str:
        if not action.payload.get("backup_export") or not action.payload.get("confirm_id"):
            raise HandoffRequired("Splunk_TA_ForIndexers deployment requires backup_export and a preview-generated confirm_id.")
        confirm_material = without_guard_fields(
            {
                key: value
                for key, value in action.payload.items()
                if key not in {"confirm_id", "handoff"}
            }
        )
        expected_confirm = stable_confirm_id("ta_for_indexers_overwrite", TA_FOR_INDEXERS_APP, confirm_material)
        if str(action.payload.get("confirm_id") or "") != expected_confirm:
            raise HandoffRequired("Splunk_TA_ForIndexers confirm_id does not match the requested deployment payload.")
        if not boolish(action.payload.get("conflict_checks_clean") or action.payload.get("clean_conflict_checks"), default=False):
            raise HandoffRequired("Splunk_TA_ForIndexers deployment requires conflict_checks_clean: true.")
        if client.app_exists(TA_FOR_INDEXERS_APP) and not boolish(action.payload.get("replace_existing"), default=False):
            raise HandoffRequired("Splunk_TA_ForIndexers already exists; set replace_existing: true after conflict review.")
        helper = self.project_root / "skills" / "splunk-enterprise-security-install" / "scripts" / "generate_ta_for_indexers.sh"
        output_dir = str(action.payload.get("output_dir") or "ta-for-indexers-rendered")
        cmd = ["bash", str(helper), "--output-dir", output_dir, "--force"]
        if action.payload.get("package"):
            cmd.extend(["--package", str(action.payload["package"])])
        completed = subprocess.run(
            cmd,
            cwd=self.project_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if completed.returncode != 0:
            raise EsConfigError(
                f"generate_ta_for_indexers failed (exit {completed.returncode}): "
                f"{sanitize_text(completed.stdout)}"
            )
        generated = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else output_dir
        cluster_manager_uri = str(action.payload.get("cluster_manager_uri") or action.payload.get("cluster_manager") or "").strip()
        if not cluster_manager_uri:
            return f"generated:{generated}"
        setup = self.project_root / "skills" / "splunk-enterprise-security-install" / "scripts" / "setup.sh"
        deploy = subprocess.run(
            ["bash", str(setup), "--deploy-ta-for-indexers", cluster_manager_uri],
            cwd=self.project_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if deploy.returncode != 0:
            raise HandoffRequired(
                "Generated Splunk_TA_ForIndexers, but cluster-manager deploy needs operator handoff: "
                f"{sanitize_text(deploy.stdout)}"
            )
        return f"deployed:{generated}"

    @staticmethod
    def _conf_and_stanza(action: Action) -> tuple[str, str]:
        match = re.search(r"/configs/conf-([^/]+)/([^/?]+)", action.endpoint or "")
        if match:
            return match.group(1), unquote(match.group(2))
        if "/" in action.target:
            conf, stanza = action.target.split("/", 1)
            return conf, stanza
        return "inputs", action.target


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def output_payload(payload: dict[str, Any], output: str | None) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output:
        Path(output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Splunk Enterprise Security declarative config engine")
    parser.add_argument("--spec", help="YAML or JSON ES config spec")
    parser.add_argument("--mode", choices=("preview", "apply", "validate", "inventory", "export"), default="preview")
    parser.add_argument("--output", help="Write JSON output to this path")
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Halt apply on the first failed action (no rollback; remaining actions are marked 'skipped').",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail fast when the spec contains unknown top-level sections (typos like 'valdation:').",
    )
    args = parser.parse_args(argv)

    try:
        spec = read_spec(args.spec)
        runner = Runner(project_root(), spec, stop_on_error=args.stop_on_error, strict=args.strict)
        if args.mode == "preview":
            payload = runner.preview()
        elif args.mode == "apply":
            payload = runner.apply()
        elif args.mode == "validate":
            payload = runner.validate()
        elif args.mode == "inventory":
            payload = runner.inventory()
        else:
            payload = runner.export()
        output_payload(payload, args.output)
        failed = any(item.get("status") == "failed" for item in payload.get("results", []))
        return 1 if failed else 0
    except EsConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
