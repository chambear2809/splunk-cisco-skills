"""Render Splunk Observability Kubernetes Frontend RUM + Session Replay assets.

This is a standalone renderer. Splunk Browser RUM beacons land directly at
rum-ingest.<realm>.observability.splunkcloud.com/v1/rum, so the Splunk OTel
Collector is NOT a prerequisite. The renderer emits four kinds of K8s
injection manifests (nginx pod-side ConfigMap, ingress-nginx snippet,
initContainer rewriter, runtime-config ConfigMap), helper scripts, source-map
upload helpers, handoff specs, and metadata.json.

This is Splunk Browser RUM (@splunk/otel-web 2.x), NOT AppDynamics BRUM.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Make the shared yaml_compat helper importable when this file is run directly
# without setting PYTHONPATH (the same pattern used in other render_assets.py
# files in this repo).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from skills.shared.lib.yaml_compat import (  # noqa: E402
    YamlCompatError,
    dump_yaml,
    load_yaml_or_json,
)


SKILL_NAME = "splunk-observability-k8s-frontend-rum-setup"
API_VERSION = f"{SKILL_NAME}/v1"
DEFAULT_OUTPUT_DIR = "splunk-observability-k8s-frontend-rum-rendered"

SUPPORTED_REALMS = {"us0", "us1", "us2", "eu0", "eu1", "eu2", "au0", "jp0"}
SUPPORTED_INJECTION_MODES = {
    "nginx-configmap",
    "ingress-snippet",
    "init-container",
    "runtime-config",
}
SUPPORTED_ENDPOINT_DOMAINS = {"splunkcloud", "signalfx"}
SUPPORTED_PERSISTANCE = {"cookie", "localStorage"}
SUPPORTED_USER_TRACKING = {"anonymousTracking", "noTracking"}
SUPPORTED_RECORDERS = {"splunk", "rrweb"}
SUPPORTED_SAMPLERS = {"always_on", "always_off", "session_based"}
SUPPORTED_BUNDLERS = {"cli", "webpack"}
SUPPORTED_CI_PROVIDERS = {"github_actions", "gitlab_ci", "none"}

DEFAULT_AGENT_VERSION = "v1"
DEFAULT_REWRITER_IMAGE = "busybox:1.36"

# Distroless image patterns. When the workload's primary image matches one of
# these, mode C auto-routes through the rewriter image rather than relying on
# any in-image shell.
DISTROLESS_PATTERNS = (
    re.compile(r"gcr\.io/distroless/"),
    re.compile(r"^cgr\.dev/chainguard/"),
    re.compile(r"distroless"),
)

# Token-shaped CLI flags that the renderer rejects. Mirrors the auto-instr
# pattern.
DIRECT_SECRET_FLAGS = {
    "--rum-token",
    "--access-token",
    "--token",
    "--bearer-token",
    "--api-token",
    "--o11y-token",
    "--sf-token",
    "--hec-token",
    "--platform-hec-token",
    "--api-key",
}
TOKEN_SHAPED_RE = re.compile(
    r"(?i)(access[_-]?token|api[_-]?token|bearer[_-]?token|hec[_-]?token|sf[_-]?token|rum[_-]?token)"
    r"\s*[:=]\s*[A-Za-z0-9._-]{20,}"
)


class SpecError(ValueError):
    """Raised for invalid render input."""


# ---------------------------------------------------------------------------
# Spec loading
# ---------------------------------------------------------------------------


def load_spec(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SpecError(f"Spec file not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        data = load_yaml_or_json(text, source=str(path))
    except YamlCompatError as exc:
        raise SpecError(f"Failed to parse spec {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError(f"Spec {path} did not parse to a mapping.")
    if data.get("api_version") != API_VERSION:
        raise SpecError(
            f"Spec api_version must be {API_VERSION!r}; got {data.get('api_version')!r}"
        )
    return data


def boolish(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def split_csv(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(split_csv(item))
        return out
    return [part.strip() for part in str(value).split(",") if part.strip()]


def normalize_kind(value: str) -> str:
    aliases = {
        "deploy": "Deployment",
        "deployment": "Deployment",
        "deployments": "Deployment",
        "statefulset": "StatefulSet",
        "statefulsets": "StatefulSet",
        "sts": "StatefulSet",
        "daemonset": "DaemonSet",
        "daemonsets": "DaemonSet",
        "ds": "DaemonSet",
    }
    kind = aliases.get(value.strip().lower(), value.strip())
    if kind not in {"Deployment", "StatefulSet", "DaemonSet"}:
        raise SpecError(f"Unsupported workload kind {value!r}; expected Deployment/StatefulSet/DaemonSet")
    return kind


def normalize_injection_mode(value: str) -> str:
    aliases = {
        "nginx": "nginx-configmap",
        "nginx_configmap": "nginx-configmap",
        "ingress": "ingress-snippet",
        "ingress_snippet": "ingress-snippet",
        "ingress_nginx": "ingress-snippet",
        "init": "init-container",
        "initcontainer": "init-container",
        "init_container": "init-container",
        "runtime": "runtime-config",
        "runtime_config": "runtime-config",
    }
    mode = aliases.get(value.strip().lower(), value.strip())
    if mode not in SUPPORTED_INJECTION_MODES:
        raise SpecError(
            f"Unsupported injection_mode {value!r}; expected one of "
            f"{sorted(SUPPORTED_INJECTION_MODES)}"
        )
    return mode


# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--spec", default="")
    parser.add_argument("--mode", default="render",
                        help="render | discover | apply | uninstall")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--gitops-mode", action="store_true")
    parser.add_argument("--accept-frontend-injection", action="store_true")
    parser.add_argument("--accept-session-replay-enterprise", action="store_true")
    parser.add_argument("--allow-latest-version", action="store_true")

    parser.add_argument("--realm", default="")
    parser.add_argument("--application-name", default="")
    parser.add_argument("--deployment-environment", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--cluster-name", default="")
    parser.add_argument("--cookie-domain", default="")
    parser.add_argument("--rum-token-file", default="")
    parser.add_argument("--o11y-token-file", default="")

    parser.add_argument("--endpoint-domain", default="")
    parser.add_argument("--cdn-base", default="")
    parser.add_argument("--beacon-endpoint-override", default="")
    parser.add_argument("--agent-version", default="")
    parser.add_argument("--agent-sri", default="")
    parser.add_argument("--session-recorder-sri", default="")
    parser.add_argument("--legacy-ie11-build", action="store_true")

    parser.add_argument("--workload", action="append", default=[],
                        help="Kind/Namespace/Name=injection_mode. Repeatable.")
    parser.add_argument("--inventory-file", default="")

    # SplunkRum.init knobs
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--persistance", default="")
    parser.add_argument("--user-tracking-mode", default="")
    parser.add_argument("--global-attribute", action="append", default=[])
    parser.add_argument("--ignore-url", action="append", default=[])
    parser.add_argument("--exporter-otlp", action="store_true")
    parser.add_argument("--sampler-type", default="")
    parser.add_argument("--sampler-ratio", default="")
    parser.add_argument("--module-disable", action="append", default=[])
    parser.add_argument("--module-enable", action="append", default=[])
    parser.add_argument("--interactions-extra-event", action="append", default=[])

    # Frustration Signals 2.0
    parser.add_argument("--rage-click-disable", action="store_true")
    parser.add_argument("--rage-click-count", default="")
    parser.add_argument("--rage-click-timeframe-seconds", default="")
    parser.add_argument("--rage-click-ignore-selector", action="append", default=[])
    parser.add_argument("--enable-dead-click", action="store_true")
    parser.add_argument("--dead-click-time-window-ms", default="")
    parser.add_argument("--dead-click-ignore-url", action="append", default=[])
    parser.add_argument("--enable-error-click", action="store_true")
    parser.add_argument("--error-click-time-window-ms", default="")
    parser.add_argument("--error-click-ignore-url", action="append", default=[])
    parser.add_argument("--enable-thrashed-cursor", action="store_true")
    parser.add_argument("--thrashed-cursor-threshold", default="")
    parser.add_argument("--thrashed-cursor-throttle-ms", default="")

    # Browser RUM privacy
    parser.add_argument("--mask-all-text", action="store_true")
    parser.add_argument("--no-mask-all-text", action="store_true")
    parser.add_argument("--privacy-rule", action="append", default=[],
                        help="mask|unmask|exclude=CSS_SELECTOR. Repeatable.")

    # Session Replay
    parser.add_argument("--enable-session-replay", action="store_true")
    parser.add_argument("--session-replay-recorder", default="")
    parser.add_argument("--session-replay-mask-all-inputs", action="store_true")
    parser.add_argument("--session-replay-no-mask-all-inputs", action="store_true")
    parser.add_argument("--session-replay-mask-all-text", action="store_true")
    parser.add_argument("--session-replay-no-mask-all-text", action="store_true")
    parser.add_argument("--session-replay-rule", action="append", default=[])
    parser.add_argument("--session-replay-max-export-interval-ms", default="")
    parser.add_argument("--session-replay-sampler-ratio", default="")
    parser.add_argument("--session-replay-feature", action="append", default=[])
    parser.add_argument("--session-replay-pack-asset", action="append", default=[])
    parser.add_argument("--session-replay-background-service-src", default="")

    # Source maps
    parser.add_argument("--source-maps-enable", action="store_true")
    parser.add_argument("--source-maps-disable", action="store_true")
    parser.add_argument("--source-maps-bundler", default="")
    parser.add_argument("--source-maps-injection-target-dir", default="")
    parser.add_argument("--source-maps-ci", default="")

    # APM linking
    parser.add_argument("--apm-linking-enable", action="store_true")
    parser.add_argument("--apm-linking-disable", action="store_true")
    parser.add_argument("--apm-linking-backend-url", default="")

    # CSP
    parser.add_argument("--csp-emit-advisory", action="store_true")
    parser.add_argument("--csp-no-emit-advisory", action="store_true")

    # Handoffs
    parser.add_argument("--no-handoff-dashboards", action="store_true")
    parser.add_argument("--no-handoff-detectors", action="store_true")
    parser.add_argument("--no-handoff-cloud-integration", action="store_true")
    parser.add_argument("--enable-handoff-auto-instrumentation", action="store_true")

    # Discovery
    parser.add_argument("--discover-frontend-workloads", action="store_true")

    # Token files via env (for guided / wrapper compatibility)
    parser.add_argument("--kube-context", default="")

    return parser.parse_args()


def reject_secret_flags(argv: list[str]) -> None:
    """Refuse token-shaped CLI flags before argparse runs."""
    for arg in argv:
        if arg in DIRECT_SECRET_FLAGS:
            raise SpecError(
                f"Refusing to accept the secret-bearing flag {arg!r}. "
                "Use a chmod-600 token file via SPLUNK_O11Y_RUM_TOKEN_FILE "
                "(RUM token) or SPLUNK_O11Y_TOKEN_FILE (Org access token)."
            )
        if "=" in arg:
            head, _ = arg.split("=", 1)
            if head in DIRECT_SECRET_FLAGS:
                raise SpecError(
                    f"Refusing to accept the secret-bearing flag {head!r}. "
                    "Use a chmod-600 token file."
                )
        if TOKEN_SHAPED_RE.search(arg):
            raise SpecError(
                "Refusing argument that looks like an inline access token. "
                "Use a chmod-600 token file."
            )


# ---------------------------------------------------------------------------
# Spec normalization (apply CLI overrides)
# ---------------------------------------------------------------------------


def normalize_spec(spec: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Apply CLI overrides to a parsed spec and fill in defaults."""

    out = json.loads(json.dumps(spec))  # deep copy via JSON round-trip

    # Identity overrides
    if args.realm:
        out["realm"] = args.realm
    if args.application_name:
        out["application_name"] = args.application_name
    if args.deployment_environment:
        out["deployment_environment"] = args.deployment_environment
    if args.version:
        out["version"] = args.version
    if args.cluster_name:
        out["cluster_name"] = args.cluster_name
    if args.cookie_domain:
        out["cookie_domain"] = args.cookie_domain
    if args.rum_token_file:
        out["rum_token_file"] = args.rum_token_file

    # Endpoints / agent version
    out.setdefault("endpoints", {})
    if args.endpoint_domain:
        out["endpoints"]["domain"] = args.endpoint_domain
    if args.cdn_base:
        out["endpoints"]["cdn_base"] = args.cdn_base
    if args.beacon_endpoint_override:
        out["endpoints"]["beacon_endpoint_override"] = args.beacon_endpoint_override
    if args.agent_version:
        out["agent_version"] = args.agent_version
    if args.agent_sri:
        out["agent_sri"] = args.agent_sri
    if args.session_recorder_sri:
        out["session_recorder_sri"] = args.session_recorder_sri
    if args.legacy_ie11_build:
        out["legacy_ie11_build"] = True

    # Workload CLI additions / overrides
    cli_workloads = parse_workload_overrides(args.workload)
    if cli_workloads:
        existing = {(w["kind"], w["namespace"], w["name"]): w
                    for w in (out.get("workloads") or [])}
        for cw in cli_workloads:
            key = (cw["kind"], cw["namespace"], cw["name"])
            if key in existing:
                existing[key]["injection_mode"] = cw["injection_mode"]
            else:
                existing[key] = cw
        out["workloads"] = list(existing.values())

    if args.inventory_file:
        inv_path = Path(args.inventory_file).expanduser()
        if not inv_path.exists():
            raise SpecError(f"Inventory file not found: {inv_path}")
        inv_data = load_yaml_or_json(inv_path.read_text(encoding="utf-8"),
                                     source=str(inv_path))
        if isinstance(inv_data, dict) and isinstance(inv_data.get("workloads"), list):
            out["workloads"] = inv_data["workloads"]

    # SplunkRum.init knobs
    instr = out.setdefault("instrumentations", {})
    if args.debug:
        instr["debug"] = True
    if args.persistance:
        instr["persistance"] = args.persistance
    if args.user_tracking_mode:
        instr["user_tracking_mode"] = args.user_tracking_mode
    if args.global_attribute:
        gattrs = dict(instr.get("global_attributes") or {})
        for entry in args.global_attribute:
            if "=" not in entry:
                raise SpecError(f"--global-attribute expects KEY=VAL, got {entry!r}")
            k, v = entry.split("=", 1)
            gattrs[k.strip()] = v.strip()
        instr["global_attributes"] = gattrs
    if args.ignore_url:
        instr["ignore_urls"] = list(instr.get("ignore_urls") or []) + args.ignore_url
    if args.exporter_otlp:
        instr.setdefault("exporter", {})["otlp"] = True
    if args.sampler_type:
        instr.setdefault("tracer", {})["sampler_type"] = args.sampler_type
    if args.sampler_ratio:
        instr.setdefault("tracer", {})["sampler_ratio"] = float(args.sampler_ratio)
    modules = dict(instr.get("modules") or {})
    for m in args.module_enable:
        modules[m.strip()] = True
    for m in args.module_disable:
        modules[m.strip()] = False
    if modules:
        instr["modules"] = modules
    if args.interactions_extra_event:
        instr["interactions_extra_event_names"] = (
            list(instr.get("interactions_extra_event_names") or []) + args.interactions_extra_event
        )

    # Frustration signals
    fs = instr.setdefault("frustration_signals", {})
    rage = fs.setdefault("rage_click", {})
    if args.rage_click_disable:
        rage["enabled"] = False
    if args.rage_click_count:
        rage["count"] = int(args.rage_click_count)
    if args.rage_click_timeframe_seconds:
        rage["timeframe_seconds"] = int(args.rage_click_timeframe_seconds)
    if args.rage_click_ignore_selector:
        rage["ignore_selectors"] = (
            list(rage.get("ignore_selectors") or []) + args.rage_click_ignore_selector
        )
    if args.enable_dead_click:
        fs.setdefault("dead_click", {})["enabled"] = True
    if args.dead_click_time_window_ms:
        fs.setdefault("dead_click", {})["time_window_ms"] = int(args.dead_click_time_window_ms)
    if args.dead_click_ignore_url:
        fs.setdefault("dead_click", {})["ignore_urls"] = (
            list(fs.get("dead_click", {}).get("ignore_urls") or []) + args.dead_click_ignore_url
        )
    if args.enable_error_click:
        fs.setdefault("error_click", {})["enabled"] = True
    if args.error_click_time_window_ms:
        fs.setdefault("error_click", {})["time_window_ms"] = int(args.error_click_time_window_ms)
    if args.error_click_ignore_url:
        fs.setdefault("error_click", {})["ignore_urls"] = (
            list(fs.get("error_click", {}).get("ignore_urls") or []) + args.error_click_ignore_url
        )
    if args.enable_thrashed_cursor:
        fs.setdefault("thrashed_cursor", {})["enabled"] = True
    if args.thrashed_cursor_threshold:
        fs.setdefault("thrashed_cursor", {})["thrashing_score_threshold"] = float(args.thrashed_cursor_threshold)
    if args.thrashed_cursor_throttle_ms:
        fs.setdefault("thrashed_cursor", {})["throttle_ms"] = int(args.thrashed_cursor_throttle_ms)

    # Browser RUM privacy
    privacy = out.setdefault("privacy", {})
    if args.mask_all_text:
        privacy["mask_all_text"] = True
    if args.no_mask_all_text:
        privacy["mask_all_text"] = False
    if args.privacy_rule:
        privacy["sensitivity_rules"] = (
            list(privacy.get("sensitivity_rules") or []) + parse_privacy_rules(args.privacy_rule)
        )

    # Session Replay
    sr = out.setdefault("session_replay", {})
    if args.enable_session_replay:
        sr["enabled"] = True
    if args.session_replay_recorder:
        sr["recorder"] = args.session_replay_recorder
    if args.session_replay_mask_all_inputs:
        sr["mask_all_inputs"] = True
    if args.session_replay_no_mask_all_inputs:
        sr["mask_all_inputs"] = False
    if args.session_replay_mask_all_text:
        sr["mask_all_text"] = True
    if args.session_replay_no_mask_all_text:
        sr["mask_all_text"] = False
    if args.session_replay_rule:
        sr["sensitivity_rules"] = (
            list(sr.get("sensitivity_rules") or []) + parse_privacy_rules(args.session_replay_rule)
        )
    if args.session_replay_max_export_interval_ms:
        sr["max_export_interval_ms"] = int(args.session_replay_max_export_interval_ms)
    if args.session_replay_sampler_ratio:
        sr["sampler_ratio"] = float(args.session_replay_sampler_ratio)
    features = sr.setdefault("features", {})
    pack = features.setdefault("pack_assets", {})
    for entry in args.session_replay_feature:
        v = entry.strip()
        if v in {"canvas", "video", "iframes", "cache_assets", "cache-assets"}:
            features[v.replace("-", "_")] = True
        elif v in {"pack_assets", "pack-assets"}:
            features["pack_assets"] = True
        else:
            raise SpecError(f"Unknown --session-replay-feature {entry!r}")
    for entry in args.session_replay_pack_asset:
        v = entry.strip()
        if v not in {"styles", "fonts", "images"}:
            raise SpecError(f"--session-replay-pack-asset expects styles|fonts|images, got {entry!r}")
        if not isinstance(pack, dict):
            pack = {}
            features["pack_assets"] = pack
        pack[v] = True
    if args.session_replay_background_service_src:
        features["background_service_src"] = args.session_replay_background_service_src

    # Source maps
    sm = out.setdefault("source_maps", {})
    if args.source_maps_enable:
        sm["enabled"] = True
    if args.source_maps_disable:
        sm["enabled"] = False
    if args.source_maps_bundler:
        sm["bundler"] = args.source_maps_bundler
    if args.source_maps_injection_target_dir:
        sm["injection_target_dir"] = args.source_maps_injection_target_dir
    if args.source_maps_ci:
        sm["ci_provider"] = args.source_maps_ci

    # APM linking
    apm = out.setdefault("apm_linking", {})
    if args.apm_linking_enable:
        apm["enabled"] = True
    if args.apm_linking_disable:
        apm["enabled"] = False
    if args.apm_linking_backend_url:
        apm["expected_server_timing_backend_url"] = args.apm_linking_backend_url

    # CSP
    csp = out.setdefault("csp", {})
    if args.csp_emit_advisory:
        csp["emit_advisory"] = True
    if args.csp_no_emit_advisory:
        csp["emit_advisory"] = False

    # Handoffs
    h = out.setdefault("handoffs", {})
    if args.no_handoff_dashboards:
        h["dashboard_builder"] = False
    if args.no_handoff_detectors:
        h["native_ops"] = False
    if args.no_handoff_cloud_integration:
        h["cloud_integration"] = False
    if args.enable_handoff_auto_instrumentation:
        h["auto_instrumentation"] = True

    return out


def parse_workload_overrides(entries: list[str]) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for entry in entries:
        if "=" not in entry:
            raise SpecError(f"--workload expects Kind/NS/NAME=mode, got {entry!r}")
        target, mode = entry.split("=", 1)
        parts = target.split("/")
        if len(parts) != 3:
            raise SpecError(f"--workload target must be Kind/NS/NAME, got {target!r}")
        parsed.append({
            "kind": normalize_kind(parts[0]),
            "namespace": parts[1].strip(),
            "name": parts[2].strip(),
            "injection_mode": normalize_injection_mode(mode.strip()),
        })
    return parsed


def parse_privacy_rules(entries: list[str]) -> list[dict[str, str]]:
    parsed: list[dict[str, str]] = []
    for entry in entries:
        if "=" not in entry:
            raise SpecError(f"Privacy rule expects rule=selector, got {entry!r}")
        rule, selector = entry.split("=", 1)
        rule = rule.strip().lower()
        if rule not in {"mask", "unmask", "exclude"}:
            raise SpecError(f"Privacy rule type must be mask|unmask|exclude, got {rule!r}")
        parsed.append({"rule": rule, "selector": selector.strip()})
    return parsed


# ---------------------------------------------------------------------------
# Snippet generation
# ---------------------------------------------------------------------------


CDN_HOSTS = {
    "splunkcloud": "cdn.observability.splunkcloud.com",
    "signalfx": "cdn.signalfx.com",
}
INGEST_HOSTS = {
    "splunkcloud": "rum-ingest.{realm}.observability.splunkcloud.com",
    "signalfx": "rum-ingest.{realm}.signalfx.com",
}


def cdn_host(spec: dict[str, Any]) -> str:
    base = (spec.get("endpoints") or {}).get("cdn_base") or ""
    if base:
        return base.rstrip("/")
    domain = (spec.get("endpoints") or {}).get("domain") or "splunkcloud"
    return f"https://{CDN_HOSTS[domain]}"


def ingest_host(spec: dict[str, Any]) -> str:
    override = (spec.get("endpoints") or {}).get("beacon_endpoint_override") or ""
    if override:
        return override
    domain = (spec.get("endpoints") or {}).get("domain") or "splunkcloud"
    realm = spec.get("realm") or "us0"
    return f"https://{INGEST_HOSTS[domain].format(realm=realm)}/v1/rum"


def script_url(spec: dict[str, Any], filename: str) -> str:
    version = spec.get("agent_version") or DEFAULT_AGENT_VERSION
    return f"{cdn_host(spec)}/o11y-gdi-rum/{version}/{filename}"


def script_tag(spec: dict[str, Any], filename: str, sri: str | None) -> str:
    url = script_url(spec, filename)
    integrity = f' integrity="{sri}"' if sri else ""
    return (
        f'<script src="{url}"{integrity} crossorigin="anonymous"></script>'
    )


def js_literal(value: Any) -> str:
    """Render a Python value as a JS literal suitable for embedding in a script.

    Strings are double-quoted (so the surrounding nginx single-quoted
    sub_filter argument never needs to escape them). Dicts -> object literals,
    lists -> arrays, bool/int/float -> their JS form.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _js_string(value)
    if isinstance(value, list):
        items = [js_literal(item) for item in value]
        return "[" + ", ".join(items) + "]"
    if isinstance(value, dict):
        parts: list[str] = []
        for k, v in value.items():
            parts.append(f"{_js_key(str(k))}: {js_literal(v)}")
        return "{" + ", ".join(parts) + "}"
    return _js_string(str(value))


def _js_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
             .replace('"', '\\"')
             .replace("\n", "\\n")
             .replace("\r", "\\r")
             .replace("\t", "\\t")
    )
    return f'"{escaped}"'


_JS_IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def _js_key(value: str) -> str:
    if _JS_IDENT_RE.match(value):
        return value
    return _js_string(value)


def build_splunk_rum_init(spec: dict[str, Any], rum_token: str) -> dict[str, Any]:
    """Build the SplunkRum.init({ ... }) payload as a Python dict in declared order."""
    instr = spec.get("instrumentations") or {}
    privacy = spec.get("privacy") or {}
    payload: dict[str, Any] = {}
    payload["realm"] = spec.get("realm") or "us0"
    payload["rumAccessToken"] = rum_token
    payload["applicationName"] = spec.get("application_name") or "unknown-browser-app"
    if spec.get("deployment_environment"):
        payload["deploymentEnvironment"] = spec["deployment_environment"]
    if spec.get("version"):
        payload["version"] = spec["version"]
    if spec.get("cookie_domain"):
        payload["cookieDomain"] = spec["cookie_domain"]
    if (spec.get("endpoints") or {}).get("beacon_endpoint_override"):
        payload["beaconEndpoint"] = spec["endpoints"]["beacon_endpoint_override"]

    if instr.get("debug"):
        payload["debug"] = True
    if instr.get("disable_automation_frameworks", True):
        payload["disableAutomationFrameworks"] = True
    if instr.get("disable_bots", True):
        payload["disableBots"] = True
    persistance = instr.get("persistance") or "cookie"
    if persistance != "cookie":
        payload["persistance"] = persistance
    user_mode = instr.get("user_tracking_mode") or "anonymousTracking"
    payload["user"] = {"trackingMode": user_mode}
    if instr.get("global_attributes"):
        payload["globalAttributes"] = dict(instr["global_attributes"])
    if instr.get("ignore_urls"):
        payload["ignoreUrls"] = list(instr["ignore_urls"])

    exporter = instr.get("exporter") or {}
    if exporter.get("otlp"):
        payload["exporter"] = {"otlp": True}

    spa_metrics = instr.get("spa_metrics") or {}
    if spa_metrics:
        spa_payload: dict[str, Any] = {}
        if "quiet_time_ms" in spa_metrics:
            spa_payload["quietTime"] = spa_metrics["quiet_time_ms"]
        if "max_resources_to_watch" in spa_metrics:
            spa_payload["maxResourcesToWatch"] = spa_metrics["max_resources_to_watch"]
        if spa_metrics.get("ignore_urls"):
            spa_payload["ignoreUrls"] = list(spa_metrics["ignore_urls"])
        if spa_payload:
            payload["spaMetrics"] = spa_payload
        elif "enabled" in spa_metrics:
            payload["spaMetrics"] = bool(spa_metrics["enabled"])

    instrumentations_block = build_instrumentations_block(instr)
    if instrumentations_block:
        payload["instrumentations"] = instrumentations_block

    if privacy:
        privacy_payload: dict[str, Any] = {}
        if "mask_all_text" in privacy:
            privacy_payload["maskAllText"] = bool(privacy["mask_all_text"])
        if privacy.get("sensitivity_rules"):
            privacy_payload["sensitivityRules"] = [
                {"rule": r["rule"], "selector": r["selector"]}
                for r in privacy["sensitivity_rules"]
            ]
        if privacy_payload:
            payload["privacy"] = privacy_payload

    tracer = instr.get("tracer") or {}
    sampler_type = tracer.get("sampler_type") or "session_based"
    sampler_ratio = tracer.get("sampler_ratio")
    # The tracer field on SplunkRum.init takes { sampler: <sampler-instance> }.
    # The sampler field on SplunkSessionRecorder.init takes the bare sampler
    # instance. Use distinct placeholder prefixes so render_init_block can
    # substitute each correctly without mixing them up.
    if sampler_type == "always_on":
        payload["tracer"] = "__TRACER_ALWAYS_ON__"
    elif sampler_type == "always_off":
        payload["tracer"] = "__TRACER_ALWAYS_OFF__"
    elif sampler_type == "session_based":
        ratio = sampler_ratio if sampler_ratio is not None else 1.0
        payload["tracer"] = f"__TRACER_SESSION_BASED__{ratio}"
    return payload


def build_instrumentations_block(instr: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    modules = instr.get("modules") or {}
    module_defaults = {
        "errors": True, "fetch": True, "xhr": True, "interactions": True,
        "longtask": True, "postload": True, "document": True, "webvitals": True,
        "websocket": False, "socketio": False, "visibility": False, "connectivity": False,
    }
    for module, default in module_defaults.items():
        value = modules.get(module, default)
        if value != default:
            out[module] = value
    extra_events = instr.get("interactions_extra_event_names") or []
    if extra_events and modules.get("interactions", True):
        existing = out.get("interactions", True)
        if existing is True:
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
        existing["eventNames"] = [
            "...SplunkRum.DEFAULT_AUTO_INSTRUMENTED_EVENT_NAMES",
            *list(extra_events),
        ]
        out["interactions"] = existing
    if modules.get("socketio") and instr.get("socketio_target") and instr["socketio_target"] != "io":
        out["socketio"] = {"target": instr["socketio_target"]}
    fs = instr.get("frustration_signals") or {}
    fs_payload = build_frustration_signals(fs)
    if fs_payload:
        out["frustrationSignals"] = fs_payload
    return out


def build_frustration_signals(fs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    rage = fs.get("rage_click") or {}
    if rage:
        if rage.get("enabled") is False:
            out["rageClick"] = False
        else:
            rage_payload: dict[str, Any] = {}
            if "count" in rage:
                rage_payload["count"] = rage["count"]
            if "timeframe_seconds" in rage:
                rage_payload["timeframeSeconds"] = rage["timeframe_seconds"]
            if rage.get("ignore_selectors"):
                rage_payload["ignoreSelectors"] = list(rage["ignore_selectors"])
            if rage_payload:
                out["rageClick"] = rage_payload
    dead = fs.get("dead_click") or {}
    if dead and dead.get("enabled"):
        dead_payload: dict[str, Any] = {}
        if "time_window_ms" in dead:
            dead_payload["timeWindowMs"] = dead["time_window_ms"]
        if dead.get("ignore_urls"):
            dead_payload["ignoreUrls"] = list(dead["ignore_urls"])
        out["deadClick"] = dead_payload or True
    error = fs.get("error_click") or {}
    if error and error.get("enabled"):
        error_payload: dict[str, Any] = {}
        if "time_window_ms" in error:
            error_payload["timeWindowMs"] = error["time_window_ms"]
        if error.get("ignore_urls"):
            error_payload["ignoreUrls"] = list(error["ignore_urls"])
        out["errorClick"] = error_payload or True
    thrash = fs.get("thrashed_cursor") or {}
    if thrash and thrash.get("enabled"):
        thrash_payload: dict[str, Any] = {}
        thrash_field_map = {
            "time_window_ms": "timeWindowMs",
            "throttle_ms": "throttleMs",
            "min_direction_changes": "minDirectionChanges",
            "min_direction_change_degrees": "minDirectionChangeDegrees",
            "min_total_distance": "minTotalDistance",
            "min_movement_distance": "minMovementDistance",
            "min_average_velocity": "minAverageVelocity",
            "max_velocity": "maxVelocity",
            "max_confined_area_size": "maxConfinedAreaSize",
            "thrashing_score_threshold": "thrashingScoreThreshold",
            "score_weight_direction_changes": "scoreWeightDirectionChanges",
            "score_weight_velocity": "scoreWeightVelocity",
            "score_weight_confined_area": "scoreWeightConfinedArea",
        }
        for snake, camel in thrash_field_map.items():
            if snake in thrash:
                thrash_payload[camel] = thrash[snake]
        if thrash.get("ignore_urls"):
            thrash_payload["ignoreUrls"] = list(thrash["ignore_urls"])
        out["thrashedCursor"] = thrash_payload or True
    return out


def build_session_recorder_init(spec: dict[str, Any], rum_token: str) -> dict[str, Any]:
    sr = spec.get("session_replay") or {}
    payload: dict[str, Any] = {
        "realm": spec.get("realm") or "us0",
        "rumAccessToken": rum_token,
    }
    recorder = sr.get("recorder") or "splunk"
    if recorder:
        payload["recorder"] = recorder
    if sr.get("mask_all_inputs") is not None:
        payload["maskAllInputs"] = bool(sr["mask_all_inputs"])
    if sr.get("mask_all_text") is not None:
        payload["maskAllText"] = bool(sr["mask_all_text"])
    if sr.get("sensitivity_rules"):
        payload["sensitivityRules"] = [
            {"rule": r["rule"], "selector": r["selector"]}
            for r in sr["sensitivity_rules"]
        ]
    if "max_export_interval_ms" in sr:
        payload["maxExportIntervalMs"] = sr["max_export_interval_ms"]
    sampler_ratio = sr.get("sampler_ratio")
    if sampler_ratio is not None:
        payload["sampler"] = f"__SESSION_BASED_SAMPLER__{sampler_ratio}"
    features = sr.get("features") or {}
    if features:
        feat_payload: dict[str, Any] = {}
        for snake, camel in (("canvas", "canvas"), ("video", "video"),
                             ("iframes", "iframes"), ("cache_assets", "cacheAssets")):
            if features.get(snake) is not None:
                feat_payload[camel] = bool(features[snake])
        pack = features.get("pack_assets")
        if isinstance(pack, dict) and pack:
            feat_payload["packAssets"] = {k: bool(v) for k, v in pack.items()}
        elif pack is True:
            feat_payload["packAssets"] = True
        elif pack is False:
            feat_payload["packAssets"] = False
        if features.get("background_service_src"):
            feat_payload["backgroundServiceSrc"] = features["background_service_src"]
        if feat_payload:
            payload["features"] = feat_payload
    return payload


def render_init_block(payload: dict[str, Any], func_name: str) -> str:
    """Render an init({ ... }) call with sampler placeholders substituted."""
    return f"{func_name}.init({substitute_sampler_placeholders(js_literal(payload))});"


def substitute_sampler_placeholders(js: str) -> str:
    """Substitute sampler placeholders in a rendered JS literal.

    The renderer emits placeholder strings (e.g. "__TRACER_SESSION_BASED__1.0")
    for sampler positions because samplers are not JSON-serialisable. This
    function replaces them with the corresponding `new SplunkRum.*Sampler(...)`
    calls. Used by both render_init_block and the runtime-config writer.
    """
    # SplunkRum.init tracer field: wraps the sampler in { sampler: ... }.
    js = re.sub(
        r'"__TRACER_SESSION_BASED__([0-9.]+)"',
        r"{ sampler: new SplunkRum.SessionBasedSampler({ ratio: \1 }) }",
        js,
    )
    js = js.replace('"__TRACER_ALWAYS_ON__"',
                    "{ sampler: new SplunkRum.AlwaysOnSampler() }")
    js = js.replace('"__TRACER_ALWAYS_OFF__"',
                    "{ sampler: new SplunkRum.AlwaysOffSampler() }")
    # SplunkSessionRecorder.init sampler field: bare sampler instance.
    js = re.sub(
        r'"__SESSION_BASED_SAMPLER__([0-9.]+)"',
        r"new SplunkRum.SessionBasedSampler({ ratio: \1 })",
        js,
    )
    return js


def render_full_snippet(spec: dict[str, Any], rum_token: str) -> str:
    """Render the complete <script>...</script> block to inject into <head>."""
    lines: list[str] = []
    lines.append(script_tag(spec, "splunk-otel-web.js", spec.get("agent_sri")))
    sr = spec.get("session_replay") or {}
    sr_enabled = bool(sr.get("enabled"))
    if sr_enabled:
        lines.append(script_tag(spec, "splunk-otel-web-session-recorder.js",
                                spec.get("session_recorder_sri")))
    if spec.get("legacy_ie11_build"):
        legacy_url = script_url(spec, "splunk-otel-web-legacy.js")
        lines.append(
            f'<!--[if IE]><script src="{legacy_url}" crossorigin="anonymous"></script><![endif]-->'
        )
    init_payload = build_splunk_rum_init(spec, rum_token)
    init_block = render_init_block(init_payload, "SplunkRum")
    lines.append("<script>")
    lines.append(f"  {init_block}")
    if sr_enabled:
        sr_payload = build_session_recorder_init(spec, rum_token)
        lines.append(f"  {render_init_block(sr_payload, 'SplunkSessionRecorder')}")
    lines.append("</script>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Token loading
# ---------------------------------------------------------------------------


def read_rum_token(spec: dict[str, Any]) -> str:
    """Read the RUM token from the spec-referenced file, env var, or placeholder."""
    path = spec.get("rum_token_file") or os.environ.get("SPLUNK_O11Y_RUM_TOKEN_FILE", "")
    if not path:
        return "<<rum-token>>"
    p = Path(path).expanduser()
    if not p.exists():
        return "<<rum-token>>"
    return p.read_text(encoding="utf-8").strip() or "<<rum-token>>"


# ---------------------------------------------------------------------------
# Per-mode K8s manifest generators
# ---------------------------------------------------------------------------


def _strategic_merge_metadata(workload: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": workload["kind"],
        "apiVersion": "apps/v1",
        "metadata": {"name": workload["name"], "namespace": workload["namespace"]},
    }


def render_nginx_configmap_assets(spec: dict[str, Any], workload: dict[str, Any],
                                  snippet: str) -> list[tuple[str, Any]]:
    serve_path = workload.get("serve_path") or "/usr/share/nginx/html"
    html_file = workload.get("html_file") or "index.html"
    # Mount path inside the nginx container. Defaults to overriding default.conf
    # because almost every nginx-served SPA image (nginx:alpine, nginxinc/*,
    # custom images that build on top of those) ships an unmodified default.conf
    # that just serves /usr/share/nginx/html/ on port 80. A separately-named
    # conf.d file would have a port-80 conflict that nginx silently resolves
    # by picking one alphabetically -- often NOT ours.
    #
    # For images with a custom default.conf that the operator wants to keep,
    # set `nginx_conf_path` per-workload to a different path (e.g. an `include`
    # destination inside the operator's existing server block).
    nginx_conf_path = workload.get("nginx_conf_path") or "/etc/nginx/conf.d/default.conf"
    cm_name = f"splunk-rum-nginx-{workload['name']}"
    # Defensive: the rendered JS snippet uses double-quoted strings, so it must
    # not contain raw single quotes. If it ever does (e.g. an operator-supplied
    # globalAttribute key with an apostrophe), fail loudly rather than emit a
    # broken nginx config that silently truncates the sub_filter argument.
    if "'" in snippet:
        raise SpecError(
            "Rendered RUM snippet contains a single quote, which would break "
            "the single-quoted nginx sub_filter argument. Remove the apostrophe "
            "from the offending spec value (likely a globalAttributes key)."
        )
    server_block = (
        "# Splunk Browser RUM injection via nginx sub_filter.\n"
        f"# Mounted at {nginx_conf_path} inside the nginx container.\n"
        "# By default this OVERRIDES the image's /etc/nginx/conf.d/default.conf,\n"
        "# preserving the standard SPA-serving behavior (port 80, /usr/share/nginx/html,\n"
        "# index.html, try_files SPA fallback) and adding a sub_filter that injects\n"
        "# the rendered RUM snippet before </head>.\n"
        "#\n"
        "# IMPORTANT: sub_filter does NOT work on gzipped responses. For proxied\n"
        "# upstreams, the proxy_set_header line below disables gzip. For static-file\n"
        "# flavors, ensure your `gzip` directive does not pre-compress index.html.\n"
        "server {\n"
        "    listen 80 default_server;\n"
        "    server_name _;\n"
        f"    root {serve_path};\n"
        f"    index {html_file};\n"
        "    sub_filter_types text/html;\n"
        "    sub_filter_once on;\n"
        "    proxy_set_header Accept-Encoding \"\";\n"
        "    location / {\n"
        f"        try_files $uri $uri/ /{html_file};\n"
        "        sub_filter '</head>' '" + snippet + "</head>';\n"
        "    }\n"
        "}\n"
    )
    cm = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": cm_name,
            "namespace": workload["namespace"],
            "labels": _backup_labels(spec),
            "annotations": {
                "splunk.com/rum-injection-mode": "nginx-configmap",
                "splunk.com/rum-target-workload": _workload_key(workload),
                "splunk.com/rum-nginx-conf-path": nginx_conf_path,
            },
        },
        "data": {
            "splunk-rum.conf": server_block,
        },
    }
    nginx_container = workload.get("nginx_container") or "web"
    patch = _strategic_merge_metadata(workload)
    patch["spec"] = {
        "template": {
            "spec": {
                "containers": [
                    {
                        "name": nginx_container,
                        "volumeMounts": [
                            {
                                "name": "splunk-rum-nginx-conf",
                                "mountPath": nginx_conf_path,
                                "subPath": "splunk-rum.conf",
                            }
                        ],
                    }
                ],
                "volumes": [
                    {
                        "name": "splunk-rum-nginx-conf",
                        "configMap": {"name": cm_name},
                    }
                ],
            }
        }
    }
    # Deterministic strategic-merge undo patch. The `$patch: delete` directive
    # is the strategic-merge way to remove a list element by its merge key.
    # Merge keys differ per list type:
    #   - spec.template.spec.volumes:                       merge key = name
    #   - spec.template.spec.containers:                    merge key = name
    #   - spec.template.spec.initContainers:                merge key = name
    #   - spec.template.spec.containers[].volumeMounts:     merge key = mountPath
    #   - spec.template.spec.containers[].env:              merge key = name
    # Far more robust than restoring the full pre-injection spec from a YAML
    # backup, because it touches exactly the fields the apply added and
    # nothing else.
    undo_patch = _strategic_merge_metadata(workload)
    undo_patch["spec"] = {
        "template": {
            "spec": {
                "containers": [
                    {
                        "name": nginx_container,
                        "volumeMounts": [
                            {"$patch": "delete", "mountPath": nginx_conf_path},
                        ],
                    }
                ],
                "volumes": [
                    {"$patch": "delete", "name": "splunk-rum-nginx-conf"},
                ],
            }
        }
    }
    return [
        (f"k8s-rum/nginx-rum-configmap-{workload['name']}.yaml", cm),
        (f"k8s-rum/nginx-deployment-patch-{workload['name']}.yaml", patch),
        (f"k8s-rum/nginx-deployment-undo-{workload['name']}.yaml", undo_patch),
    ]


def render_ingress_snippet_assets(spec: dict[str, Any], workload: dict[str, Any],
                                  snippet: str) -> list[tuple[str, Any]]:
    ingress_name = workload.get("ingress_name") or workload["name"]
    snippet_value = (
        "sub_filter_types text/html;\n"
        "sub_filter_once on;\n"
        f"sub_filter '</head>' '{snippet}</head>';\n"
    )
    patch = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": ingress_name,
            "namespace": workload["namespace"],
            "annotations": {
                "nginx.ingress.kubernetes.io/configuration-snippet": snippet_value,
                "splunk.com/rum-injection-mode": "ingress-snippet",
                "splunk.com/rum-target-workload": _workload_key(workload),
            },
        },
    }
    return [(f"k8s-rum/ingress-snippet-patch-{workload['name']}.yaml", patch)]


def render_init_container_assets(spec: dict[str, Any], workload: dict[str, Any],
                                 snippet: str, distroless: bool) -> list[tuple[str, Any]]:
    serve_path = workload.get("serve_path") or "/usr/share/nginx/html"
    html_file = workload.get("html_file") or "index.html"
    rewriter_image = workload.get("rewriter_image") or DEFAULT_REWRITER_IMAGE
    target = f"{serve_path.rstrip('/')}/{html_file}"
    sentinel = "<!--SPLUNK_RUM_INJECTED-->"
    # The rewriter container reads /sourced-html-mount/<html_file>, prepends the
    # snippet before </head> if not already injected, and writes the rewritten
    # file to the shared emptyDir mounted at /splunk-rum-html.
    cm_name = f"splunk-rum-snippet-{workload['name']}"
    snippet_cm = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": cm_name,
            "namespace": workload["namespace"],
            "labels": _backup_labels(spec),
            "annotations": {
                "splunk.com/rum-injection-mode": "init-container",
                "splunk.com/rum-target-workload": _workload_key(workload),
            },
        },
        "data": {
            "snippet.html": snippet + "\n",
            "rewrite.sh": _init_container_rewrite_script(html_file, sentinel),
        },
    }
    patch = _strategic_merge_metadata(workload)
    patch["spec"] = {
        "template": {
            "spec": {
                "initContainers": [
                    {
                        "name": "splunk-rum-rewriter",
                        "image": rewriter_image,
                        "command": ["/bin/sh", "/snippet/rewrite.sh"],
                        "env": [
                            {"name": "SOURCE_HTML", "value": target},
                            {"name": "OUTPUT_DIR", "value": "/splunk-rum-html"},
                        ],
                        "volumeMounts": [
                            {"name": "splunk-rum-snippet", "mountPath": "/snippet"},
                            {"name": "splunk-rum-html", "mountPath": "/splunk-rum-html"},
                        ],
                    }
                ],
                "containers": [
                    {
                        "name": workload.get("nginx_container") or "web",
                        "volumeMounts": [
                            {
                                "name": "splunk-rum-html",
                                "mountPath": target,
                                "subPath": html_file,
                            }
                        ],
                    }
                ],
                "volumes": [
                    {"name": "splunk-rum-snippet", "configMap": {"name": cm_name}},
                    {"name": "splunk-rum-html", "emptyDir": {}},
                ],
            }
        }
    }
    if distroless:
        # Tag the patch so operators see the auto-routed utility image clearly.
        patch["metadata"].setdefault("annotations", {})["splunk.com/rum-distroless-detected"] = "true"
    nginx_container = workload.get("nginx_container") or "web"
    undo_patch = _strategic_merge_metadata(workload)
    undo_patch["spec"] = {
        "template": {
            "spec": {
                "initContainers": [
                    {"$patch": "delete", "name": "splunk-rum-rewriter"},
                ],
                "containers": [
                    {
                        "name": nginx_container,
                        "volumeMounts": [
                            # volumeMounts merge key is mountPath, not name.
                            {"$patch": "delete", "mountPath": target},
                        ],
                    }
                ],
                "volumes": [
                    {"$patch": "delete", "name": "splunk-rum-snippet"},
                    {"$patch": "delete", "name": "splunk-rum-html"},
                ],
            }
        }
    }
    return [
        (f"k8s-rum/initcontainer-configmap-{workload['name']}.yaml", snippet_cm),
        (f"k8s-rum/initcontainer-patch-{workload['name']}.yaml", patch),
        (f"k8s-rum/initcontainer-undo-{workload['name']}.yaml", undo_patch),
    ]


def _init_container_rewrite_script(html_file: str, sentinel: str) -> str:
    return (
        "#!/bin/sh\n"
        "# Splunk Browser RUM init container rewriter.\n"
        "# Injects the contents of /snippet/snippet.html before </head> in the\n"
        "# served HTML, then writes the result to the shared emptyDir.\n"
        "set -eu\n"
        "if [ ! -f \"${SOURCE_HTML}\" ]; then\n"
        "    echo \"ERROR: source HTML not found at ${SOURCE_HTML}\" >&2\n"
        "    exit 1\n"
        "fi\n"
        "mkdir -p \"${OUTPUT_DIR}\"\n"
        "# Idempotency: if the rendered file already contains the sentinel marker,\n"
        "# skip rewriting (operator restart, sidecar relaunch, etc.).\n"
        f"if grep -q '{sentinel}' \"${{SOURCE_HTML}}\"; then\n"
        f"    cp \"${{SOURCE_HTML}}\" \"${{OUTPUT_DIR}}/{html_file}\"\n"
        "    exit 0\n"
        "fi\n"
        "snippet=$(cat /snippet/snippet.html)\n"
        f"sentinel='{sentinel}'\n"
        "# Use awk to inject before the first </head>; preserves any other content.\n"
        f"awk -v snip=\"${{snippet}}${{sentinel}}\" 'BEGIN {{ done=0 }} {{ if (!done && /<\\/head>/) {{ sub(\"</head>\", snip \"</head>\"); done=1 }}; print }}' \\\n"
        f"    \"${{SOURCE_HTML}}\" > \"${{OUTPUT_DIR}}/{html_file}\"\n"
    )


def render_runtime_config_assets(spec: dict[str, Any], workload: dict[str, Any],
                                 rum_token: str) -> list[tuple[str, Any]]:
    serve_path = workload.get("serve_path") or "/usr/share/nginx/html"
    runtime_config_path = workload.get("runtime_config_path") or "/rum-config.js"
    cm_name = f"splunk-rum-runtime-config-{workload['name']}"
    config_payload = build_splunk_rum_init(spec, rum_token)
    sr = spec.get("session_replay") or {}
    sr_payload = build_session_recorder_init(spec, rum_token) if sr.get("enabled") else None
    js_lines = [
        "window.SPLUNK_RUM_CONFIG = "
        + substitute_sampler_placeholders(js_literal(config_payload))
        + ";"
    ]
    if sr_payload:
        js_lines.append(
            "window.SPLUNK_RUM_SESSION_REPLAY_CONFIG = "
            + substitute_sampler_placeholders(js_literal(sr_payload))
            + ";"
        )
    cm = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": cm_name,
            "namespace": workload["namespace"],
            "labels": _backup_labels(spec),
            "annotations": {
                "splunk.com/rum-injection-mode": "runtime-config",
                "splunk.com/rum-target-workload": _workload_key(workload),
            },
        },
        "data": {
            "rum-config.js": "\n".join(js_lines) + "\n",
        },
    }
    target = f"{serve_path.rstrip('/')}{runtime_config_path}"
    patch = _strategic_merge_metadata(workload)
    patch["spec"] = {
        "template": {
            "spec": {
                "containers": [
                    {
                        "name": workload.get("nginx_container") or "web",
                        "volumeMounts": [
                            {
                                "name": "splunk-rum-runtime-config",
                                "mountPath": target,
                                "subPath": "rum-config.js",
                            }
                        ],
                    }
                ],
                "volumes": [
                    {
                        "name": "splunk-rum-runtime-config",
                        "configMap": {"name": cm_name},
                    }
                ],
            }
        }
    }
    bootstrap = render_runtime_config_bootstrap(runtime_config_path, sr_payload is not None)
    nginx_container = workload.get("nginx_container") or "web"
    undo_patch = _strategic_merge_metadata(workload)
    undo_patch["spec"] = {
        "template": {
            "spec": {
                "containers": [
                    {
                        "name": nginx_container,
                        "volumeMounts": [
                            # volumeMounts merge key is mountPath, not name.
                            {"$patch": "delete", "mountPath": target},
                        ],
                    }
                ],
                "volumes": [
                    {"$patch": "delete", "name": "splunk-rum-runtime-config"},
                ],
            }
        }
    }
    return [
        (f"k8s-rum/runtime-config-configmap-{workload['name']}.yaml", cm),
        (f"k8s-rum/runtime-config-deployment-patch-{workload['name']}.yaml", patch),
        (f"k8s-rum/runtime-config-undo-{workload['name']}.yaml", undo_patch),
        (f"k8s-rum/bootstrap-snippet-{workload['name']}.html", bootstrap),
    ]


def render_runtime_config_bootstrap(runtime_config_path: str, include_session_replay: bool) -> str:
    parts = [
        "<!--",
        "  Drop this snippet into your application's index.html <head>.",
        "  It loads the Splunk Browser RUM agent (and Session Replay if enabled)",
        "  and reads the runtime configuration from the mounted ConfigMap.",
        "  See references/injection-modes.md (mode B / runtime-config) for context.",
        "-->",
        '<script src="https://cdn.observability.splunkcloud.com/o11y-gdi-rum/v1/splunk-otel-web.js" crossorigin="anonymous"></script>',
    ]
    if include_session_replay:
        parts.append(
            '<script src="https://cdn.observability.splunkcloud.com/o11y-gdi-rum/v1/splunk-otel-web-session-recorder.js" crossorigin="anonymous"></script>'
        )
    parts.append(f'<script src="{runtime_config_path}"></script>')
    parts.append("<script>")
    parts.append("  if (window.SPLUNK_RUM_CONFIG) { SplunkRum.init(window.SPLUNK_RUM_CONFIG); }")
    if include_session_replay:
        parts.append("  if (window.SPLUNK_RUM_SESSION_REPLAY_CONFIG) { SplunkSessionRecorder.init(window.SPLUNK_RUM_SESSION_REPLAY_CONFIG); }")
    parts.append("</script>")
    return "\n".join(parts) + "\n"


def _workload_key(workload: dict[str, Any]) -> str:
    return f"{workload['kind']}/{workload['namespace']}/{workload['name']}"


def _backup_labels(spec: dict[str, Any]) -> dict[str, str]:
    return {
        "app.kubernetes.io/managed-by": "splunk-observability-k8s-frontend-rum-setup",
        "app.kubernetes.io/part-of": spec.get("application_name") or "frontend-rum",
    }


# ---------------------------------------------------------------------------
# Backup ConfigMap + apply / uninstall / verify scripts
# ---------------------------------------------------------------------------


def render_backup_configmap(spec: dict[str, Any], workloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Render a single ConfigMap used by apply-injection.sh to record original state."""
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": "splunk-rum-injection-backup",
            "namespace": "default",
            "labels": _backup_labels(spec),
            "annotations": {
                "splunk.com/skill": SKILL_NAME,
                "splunk.com/note": "Populated at apply time with kubectl get -o yaml output for each target workload.",
            },
        },
        "data": {
            "workloads.json": json.dumps([
                {"kind": w["kind"], "namespace": w["namespace"], "name": w["name"]}
                for w in workloads
            ], indent=2) + "\n",
        },
    }


def render_apply_script(spec: dict[str, Any], workloads: list[dict[str, Any]]) -> str:
    target_lines = ["TARGETS=("]
    for w in workloads:
        target_lines.append(f"    \"{w['kind']}/{w['namespace']}/{w['name']}\"")
    target_lines.append(")")
    return (
        "#!/usr/bin/env bash\n"
        "# Splunk Browser RUM injection apply.\n"
        "# Backs up each target workload into the splunk-rum-injection-backup\n"
        "# ConfigMap, applies the rendered RUM ConfigMap with `kubectl apply`,\n"
        "# applies the workload strategic-merge patch with\n"
        "# `kubectl patch --type=strategic --patch-file=`, applies any Ingress\n"
        "# annotation patch with `kubectl patch --type=merge --patch-file=`, and\n"
        "# triggers a rollout restart so the pods pick up the injected snippet.\n"
        "set -euo pipefail\n"
        "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"\n"
        "cd \"${SCRIPT_DIR}\"\n"
        + "\n".join(target_lines) + "\n"
        "kubectl apply -f injection-backup-configmap.yaml\n"
        "for target in \"${TARGETS[@]}\"; do\n"
        "    kind=\"${target%%/*}\"; rest=\"${target#*/}\"; ns=\"${rest%%/*}\"; name=\"${rest#*/}\"\n"
        "    safekey=\"$(printf '%s' \"${target}\" | tr '/' '_' )\"\n"
        "    echo \"Backing up ${kind}/${name} in ${ns} ...\"\n"
        "    backup_file=\"$(mktemp)\"\n"
        "    if kubectl get -n \"${ns}\" \"${kind}\" \"${name}\" -o yaml > \"${backup_file}\" 2>/dev/null; then\n"
        "        kubectl create configmap splunk-rum-injection-backup \\\n"
        "            --from-file=\"${safekey}=${backup_file}\" \\\n"
        "            --dry-run=client -o yaml | kubectl apply -f -\n"
        "    else\n"
        "        echo \"WARN: could not snapshot ${kind}/${name}; skipping\" >&2\n"
        "    fi\n"
        "    rm -f \"${backup_file}\"\n"
        "    workload_patched=false\n"
        "    for f in *${name}*.yaml; do\n"
        "        case \"${f}\" in\n"
        "            injection-backup-configmap.yaml) continue ;;\n"
        "            *-undo-*) continue ;;\n"
        "        esac\n"
        "        # Inspect each rendered manifest by kind. ConfigMaps are\n"
        "        # full objects (kubectl apply); workload patches are\n"
        "        # strategic-merge patches (kubectl patch); Ingress patches\n"
        "        # are merge patches (annotation-only).\n"
        "        rendered_kind=\"$(awk '/^kind:/ {print $2; exit}' \"${f}\")\"\n"
        "        case \"${rendered_kind}\" in\n"
        "            ConfigMap)\n"
        "                echo \"Applying ConfigMap ${f}\"\n"
        "                kubectl apply -f \"${f}\"\n"
        "                ;;\n"
        "            Deployment|StatefulSet|DaemonSet)\n"
        "                echo \"Strategic-merge patching ${rendered_kind}/${name} in ${ns} from ${f}\"\n"
        "                kubectl -n \"${ns}\" patch \"${rendered_kind}\" \"${name}\" \\\n"
        "                    --type=strategic --patch-file=\"${f}\"\n"
        "                workload_patched=true\n"
        "                ;;\n"
        "            Ingress)\n"
        "                ingress_name=\"$(awk '/^  name:/ {print $2; exit}' \"${f}\")\"\n"
        "                echo \"Merge patching Ingress/${ingress_name} in ${ns} from ${f}\"\n"
        "                kubectl -n \"${ns}\" patch ingress \"${ingress_name}\" \\\n"
        "                    --type=merge --patch-file=\"${f}\"\n"
        "                ;;\n"
        "            *)\n"
        "                echo \"Applying ${f} (kind=${rendered_kind})\"\n"
        "                kubectl apply -f \"${f}\"\n"
        "                ;;\n"
        "        esac\n"
        "    done\n"
        "    if [[ \"${workload_patched}\" == \"true\" ]]; then\n"
        "        echo \"Rollout restart ${kind}/${name} in ${ns} ...\"\n"
        "        kubectl -n \"${ns}\" rollout restart \"${kind}/${name}\"\n"
        "    fi\n"
        "done\n"
    )


def render_uninstall_script(spec: dict[str, Any], workloads: list[dict[str, Any]]) -> str:
    target_lines = ["TARGETS=("]
    for w in workloads:
        target_lines.append(f"    \"{w['kind']}/{w['namespace']}/{w['name']}\"")
    target_lines.append(")")
    return (
        "#!/usr/bin/env bash\n"
        "# Splunk Browser RUM injection uninstall.\n"
        "#\n"
        "# Applies the rendered `*-undo-*.yaml` strategic-merge patches, which\n"
        "# use $patch: delete to remove exactly the volumes / volumeMounts /\n"
        "# initContainers / annotations the apply added -- nothing else. Then\n"
        "# deletes the RUM ConfigMaps and triggers a rollout restart.\n"
        "#\n"
        "# This is more robust than restoring from a YAML backup because:\n"
        "#   - It does not hit kubectl optimistic-concurrency conflicts.\n"
        "#   - It does not need to strip server-managed metadata fields.\n"
        "#   - It does not undo any changes the operator made between apply\n"
        "#     and uninstall (the backup restore approach would).\n"
        "set -euo pipefail\n"
        "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"\n"
        "cd \"${SCRIPT_DIR}\"\n"
        + "\n".join(target_lines) + "\n"
        "for target in \"${TARGETS[@]}\"; do\n"
        "    kind=\"${target%%/*}\"; rest=\"${target#*/}\"; ns=\"${rest%%/*}\"; name=\"${rest#*/}\"\n"
        "    workload_undone=false\n"
        "    for f in *${name}*.yaml; do\n"
        "        case \"${f}\" in injection-backup-configmap.yaml) continue ;; esac\n"
        "        rendered_kind=\"$(awk '/^kind:/ {print $2; exit}' \"${f}\")\"\n"
        "        case \"${f}\" in\n"
        "            *-undo-*)\n"
        "                echo \"Strategic-merge undo patch ${rendered_kind}/${name} in ${ns} from ${f}\"\n"
        "                kubectl -n \"${ns}\" patch \"${rendered_kind}\" \"${name}\" \\\n"
        "                    --type=strategic --patch-file=\"${f}\" || true\n"
        "                workload_undone=true\n"
        "                ;;\n"
        "        esac\n"
        "    done\n"
        "    for f in *${name}*.yaml; do\n"
        "        case \"${f}\" in injection-backup-configmap.yaml|*-undo-*) continue ;; esac\n"
        "        rendered_kind=\"$(awk '/^kind:/ {print $2; exit}' \"${f}\")\"\n"
        "        case \"${rendered_kind}\" in\n"
        "            ConfigMap)\n"
        "                echo \"Deleting RUM ConfigMap from ${f}\"\n"
        "                kubectl delete --ignore-not-found -f \"${f}\"\n"
        "                ;;\n"
        "            Ingress)\n"
        "                ingress_name=\"$(awk '/^  name:/ {print $2; exit}' \"${f}\")\"\n"
        "                echo \"Removing RUM annotation from Ingress/${ingress_name} in ${ns}\"\n"
        "                kubectl -n \"${ns}\" annotate ingress \"${ingress_name}\" \\\n"
        "                    nginx.ingress.kubernetes.io/configuration-snippet- \\\n"
        "                    splunk.com/rum-injection-mode- \\\n"
        "                    splunk.com/rum-target-workload- 2>/dev/null || true\n"
        "                ;;\n"
        "        esac\n"
        "    done\n"
        "    if [[ \"${workload_undone}\" == \"true\" ]]; then\n"
        "        echo \"Rollout restart ${kind}/${name} in ${ns} ...\"\n"
        "        kubectl -n \"${ns}\" rollout restart \"${kind}/${name}\" || true\n"
        "    fi\n"
        "done\n"
        "kubectl delete --ignore-not-found configmap splunk-rum-injection-backup\n"
    )


def render_verify_script(spec: dict[str, Any], workloads: list[dict[str, Any]]) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "# Splunk Browser RUM injection verify.\n"
        "# For each workload, picks a Pod and curls the served HTML through\n"
        "# kubectl port-forward, asserting that SplunkRum.init( appears.\n"
        "set -euo pipefail\n"
        "for target in " + " ".join(f"\"{w['kind']}/{w['namespace']}/{w['name']}\"" for w in workloads) + "; do\n"
        "    kind=\"${target%%/*}\"; rest=\"${target#*/}\"; ns=\"${rest%%/*}\"; name=\"${rest#*/}\"\n"
        "    pod=\"$(kubectl -n \"${ns}\" get pods -l app=\"${name}\" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)\"\n"
        "    if [[ -z \"${pod}\" ]]; then\n"
        "        echo \"WARN: no pod found for ${target}; skipping verify\" >&2\n"
        "        continue\n"
        "    fi\n"
        "    port=8080\n"
        "    kubectl -n \"${ns}\" port-forward \"pod/${pod}\" \"${port}:80\" >/dev/null 2>&1 &\n"
        "    pf_pid=$!\n"
        "    sleep 1\n"
        "    if curl -s \"http://localhost:${port}/\" | grep -q 'SplunkRum.init('; then\n"
        "        echo \"OK: ${target} carries SplunkRum.init()\"\n"
        "    else\n"
        "        echo \"FAIL: ${target} missing SplunkRum.init()\" >&2\n"
        "    fi\n"
        "    kill \"${pf_pid}\" 2>/dev/null || true\n"
        "    wait \"${pf_pid}\" 2>/dev/null || true\n"
        "done\n"
    )


def render_status_script(spec: dict[str, Any], workloads: list[dict[str, Any]]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "# Splunk Browser RUM injection status snapshot.",
        "set -euo pipefail",
        "echo 'Backup ConfigMap:'",
        "kubectl get configmap splunk-rum-injection-backup -o wide 2>&1 || true",
        "echo",
        "echo 'Per-workload ConfigMaps:'",
    ]
    for w in workloads:
        lines.append(f"kubectl -n {w['namespace']} get configmap -l app.kubernetes.io/managed-by=splunk-observability-k8s-frontend-rum-setup 2>&1 || true")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Source-map upload helpers
# ---------------------------------------------------------------------------


def render_sourcemap_upload_script(spec: dict[str, Any]) -> str:
    sm = spec.get("source_maps") or {}
    target_dir = sm.get("injection_target_dir") or "dist"
    return (
        "#!/usr/bin/env bash\n"
        "# Splunk Browser RUM source-map upload helper.\n"
        "# Wraps the splunk-rum CLI to inject sourceMapId into minified .js files\n"
        "# and upload .js.map files so production stack traces become readable in\n"
        "# the Splunk RUM UI.\n"
        "#\n"
        "# Required env:\n"
        "#   SPLUNK_O11Y_TOKEN_FILE  Path to chmod 600 file with Org Access Token\n"
        "#   SPLUNK_O11Y_REALM       Realm (us0, us1, us2, eu0, ...)\n"
        "#   APP_NAME                Same value used in SplunkRum.init({applicationName})\n"
        "#   APP_VERSION             Same value used in SplunkRum.init({version})\n"
        "#\n"
        "# Optional env:\n"
        "#   TARGET_DIR              Build output dir (default: " + target_dir + ")\n"
        "set -euo pipefail\n"
        ": \"${SPLUNK_O11Y_TOKEN_FILE:?Set SPLUNK_O11Y_TOKEN_FILE to a chmod 600 token file}\"\n"
        ": \"${SPLUNK_O11Y_REALM:?Set SPLUNK_O11Y_REALM (us0, us1, us2, eu0, ...)}\"\n"
        ": \"${APP_NAME:?Set APP_NAME (same as SplunkRum.init applicationName)}\"\n"
        ": \"${APP_VERSION:?Set APP_VERSION (same as SplunkRum.init version)}\"\n"
        f"TARGET_DIR=\"${{TARGET_DIR:-{target_dir}}}\"\n"
        "if ! command -v splunk-rum >/dev/null; then\n"
        "    echo 'ERROR: splunk-rum CLI not found. Install with: npm install -g @splunk/rum-cli' >&2\n"
        "    exit 2\n"
        "fi\n"
        "if [[ ! -d \"${TARGET_DIR}\" ]]; then\n"
        "    echo \"ERROR: TARGET_DIR ${TARGET_DIR} does not exist\" >&2\n"
        "    exit 2\n"
        "fi\n"
        "TOKEN=\"$(cat \"${SPLUNK_O11Y_TOKEN_FILE}\")\"\n"
        "echo 'Injecting sourceMapId into minified files ...'\n"
        "splunk-rum sourcemaps inject --path \"${TARGET_DIR}\"\n"
        "echo 'Uploading source maps ...'\n"
        "SPLUNK_REALM=\"${SPLUNK_O11Y_REALM}\" SPLUNK_ACCESS_TOKEN=\"${TOKEN}\" \\\n"
        "    splunk-rum sourcemaps upload \\\n"
        "    --app-name \"${APP_NAME}\" \\\n"
        "    --app-version \"${APP_VERSION}\" \\\n"
        "    --path \"${TARGET_DIR}\"\n"
        "echo 'Done.'\n"
    )


def render_github_actions_snippet(spec: dict[str, Any]) -> str:
    return (
        "# Sample GitHub Actions job for Splunk Browser RUM source-map upload.\n"
        "# Drop this into .github/workflows/<your-pipeline>.yml and adjust the\n"
        "# `needs:` chain so it runs after your production build job.\n"
        "name: Upload Splunk RUM source maps\n"
        "on:\n"
        "  push:\n"
        "    branches: [main]\n"
        "jobs:\n"
        "  upload-sourcemaps:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: actions/setup-node@v4\n"
        "        with:\n"
        "          node-version: '20'\n"
        "      - name: Install splunk-rum CLI\n"
        "        run: npm install -g @splunk/rum-cli\n"
        "      - name: Build production bundle\n"
        "        run: npm ci && npm run build\n"
        "      - name: Upload source maps\n"
        "        env:\n"
        "          SPLUNK_O11Y_REALM: ${{ vars.SPLUNK_O11Y_REALM }}\n"
        "          SPLUNK_ACCESS_TOKEN: ${{ secrets.SPLUNK_O11Y_ORG_TOKEN }}\n"
        "          APP_NAME: ${{ vars.APP_NAME }}\n"
        "          APP_VERSION: ${{ github.sha }}\n"
        "        run: |\n"
        "          splunk-rum sourcemaps inject --path dist\n"
        "          splunk-rum sourcemaps upload --path dist \\\n"
        "              --app-name \"${APP_NAME}\" \\\n"
        "              --app-version \"${APP_VERSION}\"\n"
    )


def render_gitlab_ci_snippet(spec: dict[str, Any]) -> str:
    return (
        "# Sample GitLab CI job for Splunk Browser RUM source-map upload.\n"
        "# Drop this into .gitlab-ci.yml and chain after your production build.\n"
        "upload-sourcemaps:\n"
        "  stage: deploy\n"
        "  image: node:20\n"
        "  variables:\n"
        "    SPLUNK_O11Y_REALM: \"${SPLUNK_O11Y_REALM}\"\n"
        "    SPLUNK_ACCESS_TOKEN: \"${SPLUNK_O11Y_ORG_TOKEN}\"\n"
        "    APP_NAME: \"${APP_NAME}\"\n"
        "    APP_VERSION: \"${CI_COMMIT_SHA}\"\n"
        "  script:\n"
        "    - npm install -g @splunk/rum-cli\n"
        "    - npm ci\n"
        "    - npm run build\n"
        "    - splunk-rum sourcemaps inject --path dist\n"
        "    - splunk-rum sourcemaps upload --path dist --app-name \"${APP_NAME}\" --app-version \"${APP_VERSION}\"\n"
        "  only:\n"
        "    - main\n"
    )


def render_webpack_plugin_snippet(spec: dict[str, Any]) -> str:
    app_name = spec.get("application_name") or "your-app"
    return (
        "// Sample Splunk RUM Webpack plugin configuration.\n"
        "// Drop this into webpack.config.js. Source maps are uploaded automatically\n"
        "// by SplunkRumWebpackPlugin during the production build.\n"
        "//\n"
        "// npm install --save-dev @splunk/rum-build-plugins\n"
        "const { SplunkRumWebpackPlugin } = require('@splunk/rum-build-plugins');\n"
        "\n"
        "module.exports = {\n"
        "    devtool: 'source-map',\n"
        "    plugins: [\n"
        "        new SplunkRumWebpackPlugin({\n"
        f"            applicationName: '{app_name}',\n"
        "            version: process.env.APP_VERSION || 'dev',\n"
        "            sourceMaps: {\n"
        "                token: process.env.SPLUNK_ACCESS_TOKEN,\n"
        "                realm: process.env.SPLUNK_O11Y_REALM,\n"
        "                disableUpload: process.env.NODE_ENV !== 'production',\n"
        "            },\n"
        "        }),\n"
        "    ],\n"
        "};\n"
    )


# ---------------------------------------------------------------------------
# Handoff scripts + specs
# ---------------------------------------------------------------------------


def render_handoff_dashboards(spec: dict[str, Any]) -> tuple[str, str]:
    sh = (
        "#!/usr/bin/env bash\n"
        "# Hand off Splunk Browser RUM dashboards to splunk-observability-dashboard-builder.\n"
        "set -euo pipefail\n"
        "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"\n"
        "echo 'Run:'\n"
        "echo \"  bash skills/splunk-observability-dashboard-builder/scripts/setup.sh \\\\\"\n"
        "echo \"    --spec ${SCRIPT_DIR}/handoff-dashboards.spec.yaml --render --validate\"\n"
    )
    spec_yaml = (
        "# Starter dashboard spec for splunk-observability-dashboard-builder.\n"
        "# Renders RUM web vitals, page-view rate, JS error rate, frustration\n"
        "# signals, sessions per app, and route-change funnels.\n"
        "api_version: splunk-observability-dashboard-builder/v1\n"
        f"realm: {spec.get('realm', 'us0')}\n"
        "groups:\n"
        f"  - name: 'RUM - {spec.get('application_name', 'frontend')}'\n"
        "    description: 'Splunk Browser RUM dashboards rendered by splunk-observability-k8s-frontend-rum-setup.'\n"
        "    dashboards:\n"
        "      - name: 'Web Vitals'\n"
        "        charts:\n"
        "          - name: 'LCP p75'\n"
        "            program_text: \"data('rum.lcp', filter=filter('app', '" + (spec.get('application_name') or 'frontend') + "')).percentile(75).publish()\"\n"
        "          - name: 'CLS p75'\n"
        "            program_text: \"data('rum.cls').percentile(75).publish()\"\n"
        "          - name: 'INP p75'\n"
        "            program_text: \"data('rum.inp').percentile(75).publish()\"\n"
        "          - name: 'FCP p75'\n"
        "            program_text: \"data('rum.fcp').percentile(75).publish()\"\n"
        "          - name: 'TTFB p75'\n"
        "            program_text: \"data('rum.ttfb').percentile(75).publish()\"\n"
        "      - name: 'JS Errors + Frustration'\n"
        "        charts:\n"
        "          - name: 'JS error rate'\n"
        "            program_text: \"data('rum.client_error.count').rate().publish()\"\n"
        "          - name: 'Rage clicks'\n"
        "            program_text: \"data('rum.frustration.count', filter=filter('frustration_type', 'rage')).sum().publish()\"\n"
        "          - name: 'Sessions per app'\n"
        "            program_text: \"data('rum.session.count').sum().publish()\"\n"
    )
    return sh, spec_yaml


def render_handoff_detectors(spec: dict[str, Any]) -> tuple[str, str]:
    sh = (
        "#!/usr/bin/env bash\n"
        "# Hand off Splunk Browser RUM starter detectors to splunk-observability-native-ops.\n"
        "set -euo pipefail\n"
        "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"\n"
        "echo 'Run:'\n"
        "echo \"  bash skills/splunk-observability-native-ops/scripts/render_native_ops.py \\\\\"\n"
        "echo \"    --spec ${SCRIPT_DIR}/handoff-detectors.spec.yaml --render --validate\"\n"
    )
    spec_yaml = (
        "# Starter detector spec for splunk-observability-native-ops.\n"
        "# Renders web vitals SLO breach, JS error spike, rage-click rate,\n"
        "# dead-click ratio, and page-view drop detectors.\n"
        "api_version: splunk-observability-native-ops/v1\n"
        f"realm: {spec.get('realm', 'us0')}\n"
        "detectors:\n"
        f"  - name: 'RUM - LCP SLO breach ({spec.get('application_name', 'frontend')})'\n"
        "    program_text: \"detect(when(data('rum.lcp').percentile(75) > 2500, lasting='5m')).publish('LCP SLO breach')\"\n"
        "    severity: 'Major'\n"
        f"  - name: 'RUM - JS error spike ({spec.get('application_name', 'frontend')})'\n"
        "    program_text: \"detect(when(data('rum.client_error.count').rate() > data('rum.client_error.count').rate().mean(over='1h') * 3, lasting='5m')).publish('JS error spike')\"\n"
        "    severity: 'Critical'\n"
        f"  - name: 'RUM - Rage click rate ({spec.get('application_name', 'frontend')})'\n"
        "    program_text: \"detect(when(data('rum.frustration.count', filter=filter('frustration_type', 'rage')).sum() > 10, lasting='5m')).publish('Rage click rate')\"\n"
        "    severity: 'Minor'\n"
    )
    return sh, spec_yaml


def render_handoff_cloud_integration(spec: dict[str, Any]) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "# Advisory: enable the existing `rum` SIM modular input in Splunk Platform.\n"
        "# Pulls page_view, client_error, page_view_time p75, web vitals (LCP/CLS/FID)\n"
        "# from Splunk Observability Cloud into Splunk Platform.\n"
        "#\n"
        "# Run:\n"
        "#   bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \\\n"
        "#     --render-sim-templates rum --realm " + (spec.get("realm") or "us0") + "\n"
        "echo 'See skills/splunk-observability-cloud-integration-setup/SKILL.md and the rum modular input.'\n"
    )


def render_handoff_auto_instrumentation(spec: dict[str, Any]) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "# Advisory: backend missing Server-Timing: traceparent header.\n"
        "# Splunk Browser RUM links to APM via this header on backend HTTP responses.\n"
        "# Backends instrumented via the Splunk OTel auto-instrumentation operator\n"
        "# emit it automatically.\n"
        "#\n"
        "# Run:\n"
        "#   bash skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/setup.sh --help\n"
        "#\n"
        "# CORS callers also need:\n"
        "#   Access-Control-Expose-Headers: Server-Timing\n"
        "echo 'See skills/splunk-observability-k8s-auto-instrumentation-setup/SKILL.md for backend wiring.'\n"
    )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def render_discovery_outputs(out_dir: Path, spec: dict[str, Any]) -> None:
    """Emit discovery/workloads.yaml + discovery/services.yaml templates.

    The renderer cannot run kubectl in a hermetic context; the templates carry
    blank `injection_mode` slots that the operator fills in after running the
    discovery walk shown in the runbook.
    """
    discovery_dir = out_dir / "discovery"
    discovery_dir.mkdir(parents=True, exist_ok=True)
    workloads_template = (
        "# Frontend workload candidates discovered by `kubectl get svc,deploy,daemonset,statefulset`.\n"
        "# Set per-workload injection_mode to one of:\n"
        "#   nginx-configmap | ingress-snippet | init-container | runtime-config\n"
        "workloads: []\n"
    )
    services_template = (
        "# Frontend service candidates (port 80/8080/3000 typical).\n"
        "services: []\n"
    )
    (discovery_dir / "workloads.yaml").write_text(workloads_template, encoding="utf-8")
    (discovery_dir / "services.yaml").write_text(services_template, encoding="utf-8")


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def run_preflight(spec: dict[str, Any], args: argparse.Namespace) -> tuple[list[dict[str, str]], list[str]]:
    """Run preflight checks. Returns (findings, fail_messages)."""
    findings: list[dict[str, str]] = []
    fail_msgs: list[str] = []

    def add(check: str, severity: str, message: str) -> None:
        findings.append({"check": check, "severity": severity, "message": message})

    # https-only
    cdn = cdn_host(spec)
    if cdn.startswith("http://"):
        add("https-only", "FAIL", f"CDN base must be HTTPS, got {cdn}")
        fail_msgs.append(findings[-1]["message"])
    else:
        add("https-only", "OK", "All rendered <script src=> URLs use HTTPS.")

    # version-pinned
    version = spec.get("agent_version") or DEFAULT_AGENT_VERSION
    if version == "latest" and not args.allow_latest_version:
        msg = "agent_version is 'latest' which is REJECTED in production. Pass --allow-latest-version to override."
        add("version-pinned", "FAIL", msg)
        fail_msgs.append(msg)
    elif version == "latest":
        add("version-pinned", "WARN", "agent_version is 'latest' (operator passed --allow-latest-version).")
    else:
        add("version-pinned", "OK", f"agent_version pinned to {version}.")

    # SRI hash advisory
    if re.fullmatch(r"v\d+\.\d+\.\d+", version or ""):
        if not spec.get("agent_sri"):
            add("sri-emitted", "WARN",
                f"Exact-version pin {version} has no agent_sri. Operator should fetch the SRI hash from the GitHub release page and supply --agent-sri.")
        else:
            add("sri-emitted", "OK", "SRI hash supplied for the agent <script>.")
        if (spec.get("session_replay") or {}).get("enabled") and not spec.get("session_recorder_sri"):
            add("sri-emitted", "WARN",
                "Session Replay enabled with exact version but no session_recorder_sri.")

    # realm-supported
    realm = spec.get("realm") or ""
    if realm not in SUPPORTED_REALMS:
        msg = f"realm {realm!r} not in supported list {sorted(SUPPORTED_REALMS)}"
        add("realm-supported", "FAIL", msg)
        fail_msgs.append(msg)
    else:
        add("realm-supported", "OK", f"realm={realm} is supported.")

    # endpoint-domain-supported
    domain = (spec.get("endpoints") or {}).get("domain") or "splunkcloud"
    if domain not in SUPPORTED_ENDPOINT_DOMAINS:
        msg = f"endpoints.domain {domain!r} not in supported list {sorted(SUPPORTED_ENDPOINT_DOMAINS)}"
        add("endpoint-domain-supported", "FAIL", msg)
        fail_msgs.append(msg)
    elif domain == "signalfx":
        add("endpoint-domain-supported", "WARN",
            "Using legacy 'signalfx' endpoint domain. Splunk supports both as of Mar 24, 2026; new code should use 'splunkcloud'.")
    else:
        add("endpoint-domain-supported", "OK", "Using new observability.splunkcloud endpoint domain.")

    # session-replay gate
    sr = spec.get("session_replay") or {}
    if sr.get("enabled") and not args.accept_session_replay_enterprise:
        msg = "session_replay.enabled: true requires --accept-session-replay-enterprise (enterprise tier)."
        add("session-replay-gated", "FAIL", msg)
        fail_msgs.append(msg)
    elif sr.get("enabled"):
        add("session-replay-gated", "OK", "Session Replay enabled with operator acknowledgement.")

    # recorder advisory
    if sr.get("enabled") and (sr.get("recorder") or "splunk") == "rrweb":
        add("session-replay-recorder", "WARN",
            "Session Replay recorder=rrweb is legacy (deprecated since v1.0.0). Use recorder=splunk.")

    # Frontend injection gate is checked by setup.sh, not here. Workloads list
    # validation happens here so render fails fast.
    workloads = list(spec.get("workloads") or [])
    if not workloads and not args.discover_frontend_workloads:
        add("workloads-present", "WARN",
            "spec has no workloads. Render will produce an empty k8s-rum/ tree. Use --workload Kind/NS/NAME=mode or --discover-frontend-workloads.")
    else:
        add("workloads-present", "OK", f"{len(workloads)} workload(s) configured.")

    # Mode-vs-image is best-effort (we don't fetch image metadata in render).
    distroless_workloads = []
    for w in workloads:
        image = (w.get("image") or "")
        if w.get("injection_mode") == "init-container" and any(p.search(image) for p in DISTROLESS_PATTERNS):
            distroless_workloads.append(_workload_key(w))
    if distroless_workloads:
        add("distroless-detected", "WARN",
            f"Distroless image detected for {distroless_workloads}; mode C auto-routes through the rewriter image.")

    # Mode A.i nginx pattern detection
    for w in workloads:
        if w.get("injection_mode") == "ingress-snippet":
            add("ingress-nginx-cve", "WARN",
                f"{_workload_key(w)} uses mode ingress-snippet. Verify ingress-nginx ConfigMap has allow-snippet-annotations: 'true' (default false since CVE-2021-25742).")

    # APM linking advisory
    apm = spec.get("apm_linking") or {}
    if apm.get("enabled", True):
        add("apm-linking-server-timing", "INFO",
            "Splunk Browser RUM links to APM via Server-Timing: traceparent on backend HTTP responses. "
            "Run validate.sh --check-server-timing <backend-url> to verify.")

    # CSP advisory
    if (spec.get("csp") or {}).get("emit_advisory", True):
        ingest = ingest_host(spec)
        host = ingest.split("/v1/rum")[0].replace("https://", "")
        add("csp-advisory", "INFO",
            f"Add to your existing CSP: script-src {cdn.replace('https://', '')}; connect-src {host}.")

    # Multi-workload mode advisory
    if len({w.get("injection_mode") for w in workloads}) > 1:
        add("multi-workload-mixed-mode", "INFO",
            f"Multiple injection modes in this spec: {sorted({w.get('injection_mode') for w in workloads})}. Mixed-mode is supported.")

    # gzip advisory (mode A.i)
    for w in workloads:
        if w.get("injection_mode") == "nginx-configmap":
            add("gzip-warning", "WARN",
                f"{_workload_key(w)} uses mode nginx-configmap. Rendered conf disables proxy gzip. Static-file gzip on index.html will defeat sub_filter; verify your nginx gzip block excludes text/html when needed.")

    return findings, fail_msgs


def write_preflight_report(out_dir: Path, findings: list[dict[str, str]]) -> None:
    lines = ["# Preflight Report\n"]
    by_sev: dict[str, list[dict[str, str]]] = {"FAIL": [], "WARN": [], "INFO": [], "OK": []}
    for f in findings:
        by_sev.setdefault(f["severity"], []).append(f)
    for sev in ("FAIL", "WARN", "INFO", "OK"):
        items = by_sev.get(sev) or []
        if not items:
            continue
        lines.append(f"## {sev} ({len(items)})\n")
        for item in items:
            lines.append(f"- **{item['check']}** - {item['message']}\n")
        lines.append("")
    (out_dir / "preflight-report.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Runbook
# ---------------------------------------------------------------------------


def write_runbook(out_dir: Path, spec: dict[str, Any]) -> None:
    realm = spec.get("realm") or "us0"
    workloads = spec.get("workloads") or []
    workload_lines = "\n".join(
        f"- {_workload_key(w)} -> mode {w.get('injection_mode', 'nginx-configmap')}"
        for w in workloads
    ) or "- (no workloads configured; run --discover-frontend-workloads or pass --workload Kind/NS/NAME=mode)"
    runbook = (
        "# Splunk Browser RUM Injection Runbook\n\n"
        f"Realm: `{realm}`. Application name: `{spec.get('application_name', '')}`. Environment: `{spec.get('deployment_environment', '')}`.\n\n"
        "## Targets\n\n"
        f"{workload_lines}\n\n"
        "## Steps\n\n"
        "1. Review `preflight-report.md` and address any FAIL or WARN entries.\n"
        "2. Inspect the rendered manifests in `k8s-rum/`. Each ConfigMap/patch is\n"
        "   labelled with `app.kubernetes.io/managed-by=splunk-observability-k8s-frontend-rum-setup`.\n"
        "3. Apply (gated):\n"
        "   ```bash\n"
        "   bash apply-injection.sh\n"
        "   ```\n"
        "4. Verify in cluster:\n"
        "   ```bash\n"
        "   bash verify-injection.sh\n"
        "   ```\n"
        "5. Verify from outside the cluster (recommended):\n"
        "   ```bash\n"
        "   bash ../scripts/validate.sh --live --check-injection https://<your-frontend>\n"
        "   bash ../scripts/validate.sh --live --check-csp https://<your-frontend>\n"
        "   bash ../scripts/validate.sh --live --check-rum-ingest\n"
        "   bash ../scripts/validate.sh --live --check-server-timing https://<your-backend>\n"
        "   ```\n"
        "6. Hand off:\n"
        "   ```bash\n"
        "   bash handoff-dashboards.sh\n"
        "   bash handoff-detectors.sh\n"
        "   bash handoff-cloud-integration.sh\n"
        "   ```\n"
        "7. (Source maps) Wire `source-maps/sourcemap-upload.sh` into your CI\n"
        "   pipeline. Stack traces in Splunk RUM remain mangled until source maps\n"
        "   are uploaded for each application version.\n"
        "8. To revert:\n"
        "   ```bash\n"
        "   bash uninstall-injection.sh\n"
        "   ```\n"
    )
    (out_dir / "runbook.md").write_text(runbook, encoding="utf-8")


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def write_text(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def write_yaml(path: Path, payload: Any) -> None:
    write_text(path, _dump_kube_yaml(payload))


def _dump_kube_yaml(payload: Any) -> str:
    """Dump K8s manifests with multi-line strings as literal `|` block scalars.

    Falls back to the shared yaml_compat dumper when PyYAML is not installed.
    """
    try:
        import yaml
    except ModuleNotFoundError:
        return dump_yaml(payload, sort_keys=False)

    class _LiteralDumper(yaml.SafeDumper):
        pass

    def _str_presenter(dumper: yaml.SafeDumper, data: str) -> Any:
        if "\n" in data:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    _LiteralDumper.add_representer(str, _str_presenter)
    return yaml.dump(payload, Dumper=_LiteralDumper, sort_keys=False, default_flow_style=False)


def main() -> int:
    reject_secret_flags(sys.argv[1:])
    args = parse_args()
    out_dir = Path(args.output_dir).expanduser().resolve()

    spec_path = Path(args.spec).expanduser() if args.spec else (
        Path(__file__).resolve().parent.parent / "template.example"
    )
    spec = load_spec(spec_path)
    spec = normalize_spec(spec, args)

    findings, fail_msgs = run_preflight(spec, args)

    if args.dry_run:
        plan = {
            "skill": SKILL_NAME,
            "output_dir": str(out_dir),
            "preflight_findings": findings,
            "would_fail": bool(fail_msgs),
        }
        if args.json:
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            print(f"DRY RUN: would render to {out_dir}")
            for f in findings:
                print(f"  [{f['severity']}] {f['check']}: {f['message']}")
        return 2 if fail_msgs else 0

    if fail_msgs:
        for msg in fail_msgs:
            print(f"PREFLIGHT FAIL: {msg}", file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    write_preflight_report(out_dir, findings)
    write_runbook(out_dir, spec)

    rum_token = read_rum_token(spec)

    snippet = render_full_snippet(spec, rum_token)

    workloads = list(spec.get("workloads") or [])
    rendered_files: list[str] = ["preflight-report.md", "runbook.md"]

    for w in workloads:
        kind = normalize_kind(w["kind"])
        w["kind"] = kind
        mode = normalize_injection_mode(w.get("injection_mode") or "nginx-configmap")
        w["injection_mode"] = mode
        distroless = any(p.search(w.get("image") or "") for p in DISTROLESS_PATTERNS)
        if mode == "nginx-configmap":
            assets = render_nginx_configmap_assets(spec, w, snippet)
        elif mode == "ingress-snippet":
            assets = render_ingress_snippet_assets(spec, w, snippet)
        elif mode == "init-container":
            assets = render_init_container_assets(spec, w, snippet, distroless)
        elif mode == "runtime-config":
            assets = render_runtime_config_assets(spec, w, rum_token)
        else:
            raise SpecError(f"Unhandled injection_mode {mode!r}")
        for rel, payload in assets:
            full_path = out_dir / rel
            if isinstance(payload, str):
                write_text(full_path, payload)
            else:
                write_yaml(full_path, payload)
            rendered_files.append(rel)

    backup_cm = render_backup_configmap(spec, workloads)
    write_yaml(out_dir / "k8s-rum/injection-backup-configmap.yaml", backup_cm)
    rendered_files.append("k8s-rum/injection-backup-configmap.yaml")

    if not args.gitops_mode:
        write_text(out_dir / "k8s-rum/apply-injection.sh",
                   render_apply_script(spec, workloads), executable=True)
        write_text(out_dir / "k8s-rum/uninstall-injection.sh",
                   render_uninstall_script(spec, workloads), executable=True)
        rendered_files.extend(["k8s-rum/apply-injection.sh", "k8s-rum/uninstall-injection.sh"])
    write_text(out_dir / "k8s-rum/verify-injection.sh",
               render_verify_script(spec, workloads), executable=True)
    write_text(out_dir / "k8s-rum/status.sh",
               render_status_script(spec, workloads), executable=True)
    rendered_files.extend(["k8s-rum/verify-injection.sh", "k8s-rum/status.sh"])

    if args.discover_frontend_workloads:
        render_discovery_outputs(out_dir, spec)
        rendered_files.extend(["discovery/workloads.yaml", "discovery/services.yaml"])

    sm = spec.get("source_maps") or {}
    if sm.get("enabled", True):
        if not args.gitops_mode:
            write_text(out_dir / "source-maps/sourcemap-upload.sh",
                       render_sourcemap_upload_script(spec), executable=True)
            rendered_files.append("source-maps/sourcemap-upload.sh")
        ci = sm.get("ci_provider") or "github_actions"
        if ci == "github_actions":
            write_text(out_dir / "source-maps/github-actions.yaml",
                       render_github_actions_snippet(spec))
            rendered_files.append("source-maps/github-actions.yaml")
        elif ci == "gitlab_ci":
            write_text(out_dir / "source-maps/gitlab-ci.yaml",
                       render_gitlab_ci_snippet(spec))
            rendered_files.append("source-maps/gitlab-ci.yaml")
        if (sm.get("bundler") or "cli") == "webpack":
            write_text(out_dir / "source-maps/splunk.webpack.js",
                       render_webpack_plugin_snippet(spec))
            rendered_files.append("source-maps/splunk.webpack.js")

    handoffs = spec.get("handoffs") or {}
    handoff_list: list[str] = []
    if handoffs.get("dashboard_builder", True):
        sh, sy = render_handoff_dashboards(spec)
        write_text(out_dir / "handoff-dashboards.sh", sh, executable=True)
        write_text(out_dir / "handoff-dashboards.spec.yaml", sy)
        rendered_files.extend(["handoff-dashboards.sh", "handoff-dashboards.spec.yaml"])
        handoff_list.append("dashboards")
    if handoffs.get("native_ops", True):
        sh, sy = render_handoff_detectors(spec)
        write_text(out_dir / "handoff-detectors.sh", sh, executable=True)
        write_text(out_dir / "handoff-detectors.spec.yaml", sy)
        rendered_files.extend(["handoff-detectors.sh", "handoff-detectors.spec.yaml"])
        handoff_list.append("detectors")
    if handoffs.get("cloud_integration", True):
        write_text(out_dir / "handoff-cloud-integration.sh",
                   render_handoff_cloud_integration(spec), executable=True)
        rendered_files.append("handoff-cloud-integration.sh")
        handoff_list.append("cloud_integration")
    if handoffs.get("auto_instrumentation", False):
        write_text(out_dir / "handoff-auto-instrumentation.sh",
                   render_handoff_auto_instrumentation(spec), executable=True)
        rendered_files.append("handoff-auto-instrumentation.sh")
        handoff_list.append("auto_instrumentation")

    spec_digest = hashlib.sha256(
        json.dumps(spec, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()

    metadata = {
        "skill": SKILL_NAME,
        "version": "1",
        "spec_digest": spec_digest,
        "realm": spec.get("realm"),
        "application_name": spec.get("application_name"),
        "deployment_environment": spec.get("deployment_environment"),
        "agent_version": spec.get("agent_version") or DEFAULT_AGENT_VERSION,
        "endpoint_domain": (spec.get("endpoints") or {}).get("domain") or "splunkcloud",
        "session_replay_enabled": bool((spec.get("session_replay") or {}).get("enabled")),
        "source_maps_enabled": bool(sm.get("enabled", True)),
        "targets": [
            {
                "kind": w["kind"],
                "namespace": w["namespace"],
                "name": w["name"],
                "injection_mode": w.get("injection_mode", "nginx-configmap"),
            }
            for w in workloads
        ],
        "rendered_files": sorted(rendered_files),
        "preflight_summary": {
            "ok": sum(1 for f in findings if f["severity"] == "OK"),
            "warn": sum(1 for f in findings if f["severity"] == "WARN"),
            "fail": sum(1 for f in findings if f["severity"] == "FAIL"),
            "info": sum(1 for f in findings if f["severity"] == "INFO"),
        },
        "handoffs": handoff_list,
    }
    write_text(out_dir / "metadata.json",
               json.dumps(metadata, indent=2, sort_keys=True) + "\n")

    if args.json:
        print(json.dumps(metadata, indent=2, sort_keys=True))
    else:
        print(f"Rendered to {out_dir}")
        print(f"Files: {len(rendered_files)} | Workloads: {len(workloads)} | "
              f"Session Replay: {metadata['session_replay_enabled']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SpecError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
