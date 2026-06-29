#!/usr/bin/env python3
"""Render Splunk Observability Cloud Mobile RUM assets.

The renderer is intentionally non-mutating by default. It emits native iOS,
native Android, React Native, and Flutter snippets, optional source patches,
symbol upload helpers, privacy notes, WebView Browser RUM handoffs, and
RUM-to-APM Server-Timing validation helpers.
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

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from skills.shared.lib.yaml_compat import (  # noqa: E402
    YamlCompatError,
    dump_yaml,
    load_yaml_or_json,
)


SKILL_NAME = "splunk-observability-mobile-rum-setup"
API_VERSION = f"{SKILL_NAME}/v1"
DEFAULT_OUTPUT_DIR = "splunk-observability-mobile-rum-rendered"

SUPPORTED_PLATFORMS = {"ios", "android", "react_native", "flutter"}
SUPPORTED_SOURCE_MODES = {"render-snippets", "render-patches", "apply-patches"}
SUPPORTED_REALMS = {"us0", "us1", "us2", "eu0", "eu1", "eu2", "au0", "jp0"}

DEFAULT_VERSIONS = {
    "ios_agent": "2.2.3",
    "android_agent": "2.3.0",
    "android_gradle_plugins": "2.3.0",
    "react_native_agent": "1.0.0",
    "react_native_session_replay": "1.0.0",
    "flutter_agent": "1.0.1",
    "flutter_session_replay": "1.0.1",
}

VERSION_KEYS_BY_PLATFORM = {
    "ios": ("ios_agent",),
    "android": ("android_agent", "android_gradle_plugins"),
    "react_native": ("react_native_agent", "react_native_session_replay"),
    "flutter": ("flutter_agent", "flutter_session_replay"),
}

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

RAW_TOKEN_KEYS = {
    "rum_token",
    "access_token",
    "api_token",
    "o11y_token",
    "sf_token",
    "bearer_token",
    "hec_token",
    "platform_hec_token",
    "api_key",
}

PINNED_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$")
UNPINNED_VERSION_RE = re.compile(r"(?i)(^latest$|[+*xX]|^[~^<>]=?| - | \|\||,)")
TOKEN_LITERAL_RE = re.compile(
    r"(?i)(?:bearer\s+)?(?:"
    r"[A-Za-z0-9_-]{32,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}|"
    r"[A-Za-z0-9_./+=-]{48,}"
    r")"
)
TRACEPARENT_RE = re.compile(
    r"traceparent\s*;\s*desc=\"?(00-[0-9a-f]{32}-[0-9a-f]{16}-01)\"?",
    re.IGNORECASE,
)
SERVER_TIMING_LINE_RE = re.compile(r"^server-timing\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


class SpecError(ValueError):
    """Raised for invalid render input."""


def reject_direct_secret_args(argv: list[str]) -> None:
    for token in argv:
        flag = token.split("=", 1)[0]
        if flag in DIRECT_SECRET_FLAGS:
            raise SpecError(
                f"Direct secret flag {flag} is rejected. Use --rum-token-file, "
                "--o11y-token-file, or a build-time placeholder reference."
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", default="")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--source-mode", choices=sorted(SUPPORTED_SOURCE_MODES), default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--accept-session-replay-enterprise", action="store_true")
    parser.add_argument("--accept-mobile-rum-source-edit", action="store_true")
    parser.add_argument("--allow-latest-version", action="store_true")
    parser.add_argument("--allow-lower-android-api", action="store_true")

    parser.add_argument("--realm", default="")
    parser.add_argument("--rum-token-file", default="")
    parser.add_argument("--o11y-token-file", default="")
    parser.add_argument("--rum-token-ref", default="")
    parser.add_argument("--platform", action="append", choices=sorted(SUPPORTED_PLATFORMS), default=[])
    parser.add_argument("--app-root", default="")
    parser.add_argument("--app-name", default="")
    parser.add_argument("--bundle-id", default="")
    parser.add_argument("--application-id", default="")
    parser.add_argument("--deployment-environment", default="")
    parser.add_argument("--app-version", default="")
    parser.add_argument("--release-name", default="")
    parser.add_argument("--build-number", default="")
    parser.add_argument("--validation-url", action="append", default=[])
    parser.add_argument("--webview-url", action="append", default=[])

    parser.add_argument("--ios-agent-version", default="")
    parser.add_argument("--android-agent-version", default="")
    parser.add_argument("--android-gradle-plugins-version", default="")
    parser.add_argument("--react-native-agent-version", default="")
    parser.add_argument("--react-native-session-replay-version", default="")
    parser.add_argument("--flutter-agent-version", default="")
    parser.add_argument("--flutter-session-replay-version", default="")

    parser.add_argument("--enable-session-replay", action="store_true")
    parser.add_argument("--session-replay-sampler-ratio", default="")
    parser.add_argument("--privacy-ignore-url", action="append", default=[])
    parser.add_argument("--privacy-redact-query-strings", action="store_true")
    parser.add_argument("--user-tracking-mode", default="")
    return parser.parse_args(argv)


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
        raise SpecError(f"Spec api_version must be {API_VERSION!r}; got {data.get('api_version')!r}")
    return data


def boolish(value: Any, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return cleaned or "mobile-app"


def as_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    return [value]


def semver_tuple(value: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(value or ""))
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def deep_get(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = mapping
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def scan_for_secret_literals(value: Any, path: str = "spec") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            lower = key_text.lower().replace("-", "_")
            child_path = f"{path}.{key_text}"
            if lower in RAW_TOKEN_KEYS and child not in (None, ""):
                errors.append(
                    f"{child_path} contains an inline token field. Use a *_ref or *_file field instead."
                )
                continue
            if isinstance(child, str):
                allowed_ref = lower.endswith(("_ref", "_file", "_env", "_name")) or lower in {
                    "token_ref",
                    "rum_token_ref",
                    "org_access_token_ref",
                }
                if not allowed_ref and ("token" in lower or "api_key" in lower or "secret" in lower):
                    if TOKEN_LITERAL_RE.search(child):
                        errors.append(f"{child_path} looks like a raw secret/token literal.")
                elif (
                    not allowed_ref
                    and re.fullmatch(
                        r"(?i)(bearer\s+[A-Za-z0-9_./+=-]{20,}|"
                        r"[A-Za-z0-9_-]{32,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,})",
                        child.strip(),
                    )
                ):
                    errors.append(f"{child_path} looks like a raw token literal.")
            errors.extend(scan_for_secret_literals(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(scan_for_secret_literals(child, f"{path}[{index}]"))
    return errors


def validate_version(value: str, key: str, allow_latest: bool, errors: list[str], warnings: list[str]) -> None:
    text = str(value or "").strip()
    if not text:
        errors.append(f"{key} must be set to an exact version.")
        return
    if UNPINNED_VERSION_RE.search(text) or not PINNED_VERSION_RE.match(text):
        if allow_latest:
            warnings.append(f"{key}={text!r} is not pinned; allowed only because --allow-latest-version was set.")
            return
        errors.append(f"{key}={text!r} is not pinned. Use an exact X.Y.Z version or --allow-latest-version.")


def build_spec_from_args(args: argparse.Namespace) -> dict[str, Any]:
    platforms = args.platform or ["ios"]
    version_overrides = {
        "ios_agent": args.ios_agent_version,
        "android_agent": args.android_agent_version,
        "android_gradle_plugins": args.android_gradle_plugins_version,
        "react_native_agent": args.react_native_agent_version,
        "react_native_session_replay": args.react_native_session_replay_version,
        "flutter_agent": args.flutter_agent_version,
        "flutter_session_replay": args.flutter_session_replay_version,
    }
    versions = {key: value for key, value in version_overrides.items() if value}
    platform_entries: list[dict[str, Any]] = []
    for platform in platforms:
        entry: dict[str, Any] = {
            "platform": platform,
            "app_root": args.app_root,
            "app_name": args.app_name or f"{platform}-app",
            "deployment_environment": args.deployment_environment or "dev",
            "app_version": args.app_version or "0.1.0",
            "release": {
                "name": args.release_name or args.app_version or "0.1.0",
                "build": args.build_number or "local",
            },
            "privacy": {
                "ignore_urls": args.privacy_ignore_url,
                "redact_query_strings": args.privacy_redact_query_strings,
                "user_tracking_mode": args.user_tracking_mode or "anonymousTracking",
            },
            "session_replay": {
                "enabled": bool(args.enable_session_replay),
                "sampling_rate": args.session_replay_sampler_ratio or None,
            },
            "validation_urls": args.validation_url,
            "webviews": [{"url": url} for url in args.webview_url],
        }
        if platform == "ios":
            entry["bundle_id"] = args.bundle_id or "com.example.mobile"
        if platform in {"android", "react_native", "flutter"}:
            entry["application_id"] = args.application_id or "com.example.mobile"
        platform_entries.append(entry)
    return {
        "api_version": API_VERSION,
        "realm": args.realm or os.environ.get("SPLUNK_O11Y_REALM", "us0"),
        "rum_token_ref": args.rum_token_ref or "SPLUNK_O11Y_RUM_TOKEN_FILE",
        "org_access_token_ref": "SPLUNK_O11Y_TOKEN_FILE",
        "source_mode": args.source_mode or "render-snippets",
        "versions": versions,
        "platforms": platform_entries,
    }


def merge_cli_overrides(spec: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    merged = json.loads(json.dumps(spec))
    if args.realm:
        merged["realm"] = args.realm
    if args.source_mode:
        merged["source_mode"] = args.source_mode
    if args.rum_token_ref:
        merged["rum_token_ref"] = args.rum_token_ref
    if args.rum_token_file:
        merged["rum_token_file"] = args.rum_token_file
    if args.o11y_token_file:
        merged["org_access_token_file"] = args.o11y_token_file

    version_flags = {
        "ios_agent": args.ios_agent_version,
        "android_agent": args.android_agent_version,
        "android_gradle_plugins": args.android_gradle_plugins_version,
        "react_native_agent": args.react_native_agent_version,
        "react_native_session_replay": args.react_native_session_replay_version,
        "flutter_agent": args.flutter_agent_version,
        "flutter_session_replay": args.flutter_session_replay_version,
    }
    versions = dict(merged.get("versions") or {})
    versions.update({key: value for key, value in version_flags.items() if value})
    if versions:
        merged["versions"] = versions

    platforms = as_list(merged.get("platforms"))
    if args.platform:
        platforms = [p for p in platforms if isinstance(p, dict) and p.get("platform") in args.platform]
        existing = {p.get("platform") for p in platforms if isinstance(p, dict)}
        for platform in args.platform:
            if platform not in existing:
                platforms.append({"platform": platform})

    for platform in platforms:
        if not isinstance(platform, dict):
            continue
        for cli_name, spec_name in (
            ("app_root", "app_root"),
            ("app_name", "app_name"),
            ("bundle_id", "bundle_id"),
            ("application_id", "application_id"),
            ("deployment_environment", "deployment_environment"),
            ("app_version", "app_version"),
        ):
            value = getattr(args, cli_name)
            if value:
                platform[spec_name] = value
        if args.validation_url:
            platform["validation_urls"] = args.validation_url
        if args.webview_url:
            platform["webviews"] = [{"url": url} for url in args.webview_url]
        if args.enable_session_replay or args.session_replay_sampler_ratio:
            replay = dict(platform.get("session_replay") or {})
            if args.enable_session_replay:
                replay["enabled"] = True
            if args.session_replay_sampler_ratio:
                replay["sampling_rate"] = args.session_replay_sampler_ratio
            platform["session_replay"] = replay
        if args.privacy_ignore_url or args.privacy_redact_query_strings or args.user_tracking_mode:
            privacy = dict(platform.get("privacy") or {})
            if args.privacy_ignore_url:
                privacy["ignore_urls"] = args.privacy_ignore_url
            if args.privacy_redact_query_strings:
                privacy["redact_query_strings"] = True
            if args.user_tracking_mode:
                privacy["user_tracking_mode"] = args.user_tracking_mode
            platform["privacy"] = privacy
    if platforms:
        merged["platforms"] = platforms
    return merged


def normalize_spec(
    raw: dict[str, Any],
    *,
    allow_latest: bool,
    accept_session_replay: bool,
    accept_source_edit: bool,
    allow_lower_android_api: bool,
) -> tuple[dict[str, Any], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    errors.extend(scan_for_secret_literals(raw))

    realm = str(raw.get("realm") or "").strip()
    if not realm:
        realm = os.environ.get("SPLUNK_O11Y_REALM", "us0")
    if realm not in SUPPORTED_REALMS:
        warnings.append(f"realm={realm!r} is outside the baked allow-list {sorted(SUPPORTED_REALMS)}.")

    source_mode = str(raw.get("source_mode") or "render-snippets").strip()
    if source_mode not in SUPPORTED_SOURCE_MODES:
        errors.append(f"source_mode must be one of {sorted(SUPPORTED_SOURCE_MODES)}; got {source_mode!r}.")
    if source_mode == "apply-patches" and not accept_source_edit:
        errors.append("source_mode=apply-patches requires --accept-mobile-rum-source-edit.")

    versions = {**DEFAULT_VERSIONS, **(raw.get("versions") or {})}
    for key, value in versions.items():
        validate_version(str(value), f"versions.{key}", allow_latest, errors, warnings)

    platforms_raw = as_list(raw.get("platforms"))
    if not platforms_raw and raw.get("platform"):
        platforms_raw = [raw]
    if not platforms_raw:
        errors.append("At least one platforms[] entry is required.")

    normalized_platforms: list[dict[str, Any]] = []
    any_replay = False
    for index, item in enumerate(platforms_raw):
        if not isinstance(item, dict):
            errors.append(f"platforms[{index}] must be a mapping.")
            continue
        platform = str(item.get("platform") or item.get("kind") or "").strip().lower().replace("-", "_")
        if platform not in SUPPORTED_PLATFORMS:
            errors.append(f"platforms[{index}].platform must be one of {sorted(SUPPORTED_PLATFORMS)}; got {platform!r}.")
            continue

        app_name = str(item.get("app_name") or raw.get("app_name") or f"{platform}-app").strip()
        app_version = str(item.get("app_version") or raw.get("app_version") or "0.1.0").strip()
        deployment_environment = str(
            item.get("deployment_environment") or raw.get("deployment_environment") or "dev"
        ).strip()
        app_root = str(item.get("app_root") or "").strip()
        release = dict(raw.get("release") or {})
        release.update(item.get("release") or {})
        release.setdefault("name", app_version)
        release.setdefault("build", str(item.get("build_number") or "local"))
        release.setdefault("distribution", str(item.get("distribution") or "internal"))

        platform_versions = {**versions, **(item.get("versions") or {})}
        for key in VERSION_KEYS_BY_PLATFORM[platform]:
            validate_version(str(platform_versions.get(key, "")), f"platforms[{index}].versions.{key}", allow_latest, errors, warnings)

        privacy = {
            "redact_query_strings": True,
            "ignore_urls": [],
            "user_tracking_mode": "anonymousTracking",
            "drop_enduser_attributes": True,
            **(raw.get("privacy") or {}),
            **(item.get("privacy") or {}),
        }

        replay = {
            "enabled": False,
            "sampling_rate": None,
            "mask_all_text": True,
            "mask_all_inputs": True,
            "sensitivity_rules": [],
            **(raw.get("session_replay") or {}),
            **(item.get("session_replay") or {}),
        }
        replay["enabled"] = boolish(replay.get("enabled"), False)
        if replay["enabled"]:
            any_replay = True
            raw_rate = replay.get("sampling_rate")
            if raw_rate in (None, ""):
                replay["sampling_rate"] = 0.2
            try:
                rate = float(replay["sampling_rate"])
                if not 0 <= rate <= 1:
                    raise ValueError
                replay["sampling_rate"] = rate
            except (TypeError, ValueError):
                errors.append(f"platforms[{index}].session_replay.sampling_rate must be between 0 and 1.")

        requirements = dict(item.get("requirements") or {})
        if platform == "ios":
            min_ios = str(requirements.get("ios_minimum") or item.get("ios_minimum") or "15.0")
            if semver_tuple(f"{min_ios}.0" if min_ios.count(".") == 1 else min_ios) < (15, 0, 0):
                errors.append(f"{app_name}: iOS Mobile RUM requires iOS/iPadOS 15.0 or newer.")
            if not (item.get("bundle_id") or raw.get("bundle_id")):
                warnings.append(f"{app_name}: bundle_id is not set; snippets will use a placeholder.")
        if platform in {"android", "react_native", "flutter"}:
            min_api = int(requirements.get("android_min_api") or item.get("android_min_api") or 24)
            if min_api < 24 and not (allow_lower_android_api or boolish(item.get("allow_lower_android_api"), False)):
                errors.append(f"{app_name}: Android runtime API {min_api} is below the default supported floor 24.")
            requirements["android_min_api"] = min_api
        if platform == "react_native":
            rn_version = str(requirements.get("react_native") or item.get("react_native_version") or "0.75.0")
            react_version = str(requirements.get("react") or item.get("react_version") or "18.2.0")
            if semver_tuple(rn_version) < (0, 75, 0):
                errors.append(f"{app_name}: React Native must be 0.75.0 or newer.")
            if semver_tuple(react_version) < (18, 2, 0):
                errors.append(f"{app_name}: React must be 18.2.0 or newer.")
            requirements["react_native"] = rn_version
            requirements["react"] = react_version
        if platform == "flutter":
            flutter_version = str(requirements.get("flutter") or item.get("flutter_version") or "3.32.0")
            dart_version = str(requirements.get("dart") or item.get("dart_version") or "3.8.0")
            if semver_tuple(flutter_version) < (3, 32, 0):
                errors.append(f"{app_name}: Flutter must be 3.32.0 or newer.")
            if semver_tuple(dart_version) < (3, 8, 0):
                errors.append(f"{app_name}: Dart must be 3.8.0 or newer.")
            requirements["flutter"] = flutter_version
            requirements["dart"] = dart_version

        if source_mode in {"render-patches", "apply-patches"} and not app_root:
            warnings.append(f"{app_name}: app_root is empty; source patch helper will skip this platform.")

        normalized_platforms.append(
            {
                **item,
                "platform": platform,
                "realm": realm,
                "app_name": app_name,
                "app_version": app_version,
                "deployment_environment": deployment_environment,
                "app_root": app_root,
                "release": release,
                "versions": platform_versions,
                "privacy": privacy,
                "session_replay": replay,
                "requirements": requirements,
                "validation_urls": as_list(item.get("validation_urls") or raw.get("validation_urls")),
                "webviews": as_list(item.get("webviews")),
                "modules": dict(item.get("modules") or {}),
                "symbol_upload": {**(raw.get("symbol_upload") or {}), **(item.get("symbol_upload") or {})},
            }
        )

    if any_replay and not accept_session_replay:
        errors.append("Session Replay rendering requires --accept-session-replay-enterprise.")

    if errors:
        raise SpecError("\n".join(errors))

    normalized = {
        **raw,
        "api_version": API_VERSION,
        "realm": realm,
        "source_mode": source_mode,
        "versions": versions,
        "platforms": normalized_platforms,
        "rum_token_ref": raw.get("rum_token_ref") or "SPLUNK_O11Y_RUM_TOKEN_FILE",
        "org_access_token_ref": raw.get("org_access_token_ref") or "SPLUNK_O11Y_TOKEN_FILE",
        "allow_latest_version": bool(allow_latest),
        "accept_session_replay_enterprise": bool(accept_session_replay),
        "accept_mobile_rum_source_edit": bool(accept_source_edit),
    }
    return normalized, warnings, errors


def write_file(path: Path, text: str, *, executable: bool = False, rendered: list[str], root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(0o755)
    rendered.append(path.relative_to(root).as_posix())


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def format_kv_map(mapping: dict[str, Any], indent: str = "        ") -> str:
    lines = []
    for key, value in sorted(mapping.items()):
        lines.append(f'{indent}"{key}": "{value}"')
    return ",\n".join(lines)


def code_string(value: Any) -> str:
    return json.dumps(str(value))


def swift_global_attributes(mapping: dict[str, str], indent: str = "            ") -> str:
    return ",\n".join(f"{indent}{code_string(key)}: .string({code_string(value)})" for key, value in sorted(mapping.items()))


def kotlin_global_attribute_lines(mapping: dict[str, str], indent: str = "        ") -> str:
    return "\n".join(
        f"{indent}SplunkRum.instance.globalAttributes.set({code_string(key)}, {code_string(value)})"
        for key, value in sorted(mapping.items())
    )


def java_global_attribute_lines(mapping: dict[str, str], indent: str = "        ") -> str:
    return "\n".join(
        f"{indent}SplunkRum.getInstance().getGlobalAttributes().set({code_string(key)}, {code_string(value)});"
        for key, value in sorted(mapping.items())
    )


def rn_global_attribute_lines(mapping: dict[str, str], indent: str = "  ") -> str:
    return "\n".join(
        f"{indent}await rum.globalAttributes.setString({code_string(key)}, {code_string(value)});"
        for key, value in sorted(mapping.items())
    )


def flutter_global_attribute_lines(mapping: dict[str, str], indent: str = "  ") -> str:
    return "\n".join(
        f"{indent}await SplunkRum.instance.globalAttributes.setString(key: {code_string(key)}, value: {code_string(value)});"
        for key, value in sorted(mapping.items())
    )


def common_attributes(platform: dict[str, Any]) -> dict[str, str]:
    release = platform.get("release") or {}
    attrs = {
        "deployment.environment": str(platform["deployment_environment"]),
        "app.version": str(platform["app_version"]),
        "release.name": str(release.get("name") or platform["app_version"]),
        "release.build": str(release.get("build") or "local"),
        "release.distribution": str(release.get("distribution") or "internal"),
    }
    for key, value in dict(platform.get("global_attributes") or {}).items():
        attrs[str(key)] = str(value)
    return attrs


def privacy_summary(platform: dict[str, Any]) -> str:
    privacy = platform.get("privacy") or {}
    ignore_urls = ", ".join(str(item) for item in as_list(privacy.get("ignore_urls"))) or "none"
    return (
        f"- Redact URL query strings: {boolish(privacy.get('redact_query_strings'), True)}\n"
        f"- Ignore URL rules: {ignore_urls}\n"
        f"- User tracking mode: {privacy.get('user_tracking_mode', 'anonymousTracking')}\n"
        "- Avoid setting `enduser.*` attributes unless legal/privacy approval exists.\n"
        "- Drop, hash, or replace customer identifiers before adding global attributes.\n"
    )


def session_replay_summary(platform: dict[str, Any]) -> str:
    replay = platform.get("session_replay") or {}
    if not boolish(replay.get("enabled"), False):
        return "Session Replay is disabled for this platform.\n"
    rules = as_list(replay.get("sensitivity_rules"))
    return (
        f"Session Replay enabled with sampling_rate={replay.get('sampling_rate')}.\n"
        f"- mask_all_text: {boolish(replay.get('mask_all_text'), True)}\n"
        f"- mask_all_inputs: {boolish(replay.get('mask_all_inputs'), True)}\n"
        f"- sensitivity rules: {len(rules)} configured\n"
        "- Use local-device masking verification before production rollout.\n"
    )


def ios_files(platform: dict[str, Any]) -> dict[str, str]:
    versions = platform["versions"]
    attrs = common_attributes(platform)
    attrs_swift = swift_global_attributes(attrs)
    replay = platform["session_replay"]
    replay_enabled = boolish(replay.get("enabled"), False)
    package = f"""// Add to Package.swift dependencies.
.package(url: "https://github.com/signalfx/splunk-otel-ios.git", exact: "{versions['ios_agent']}")

// Add the SplunkAgent product to the application target.
.product(name: "SplunkAgent", package: "splunk-otel-ios")
"""
    swift = f"""import Foundation
import SplunkAgent
import UIKit

enum MobileRumConfig {{
    static let realm = {code_string(platform['realm'])}
    static let rumToken = "<RUM_TOKEN_FROM_BUILD_CONFIG>"
    static let appName = {code_string(platform['app_name'])}
    static let deploymentEnvironment = {code_string(platform['deployment_environment'])}
}}

final class SplunkRumBootstrap {{
    @discardableResult
    static func start() -> SplunkRum? {{
        let endpointConfiguration = EndpointConfiguration(
            realm: MobileRumConfig.realm,
            rumAccessToken: MobileRumConfig.rumToken
        )
        let agentConfiguration = AgentConfiguration(
            endpoint: endpointConfiguration,
            appName: MobileRumConfig.appName,
            deploymentEnvironment: MobileRumConfig.deploymentEnvironment
        )
            .globalAttributes(MutableAttributes(dictionary: [
{attrs_swift}
            ]))
            .spanInterceptor {{ spanData in
                var spanData = spanData
                var attributes = spanData.attributes
                if attributes["http.url"] != nil {{
                    attributes["http.url"] = .string("redacted")
                }}
                return spanData.settingAttributes(attributes)
            }}

        do {{
            let agent = try SplunkRum.install(with: agentConfiguration)
            agent.navigation.preferences.enableAutomatedTracking = true
            return agent
        }} catch {{
            print("Unable to start the Splunk RUM agent: \\(error)")
            return nil
        }}
    }}
}}
"""
    objc = f"""#import <Foundation/Foundation.h>
@import SplunkAgentObjC;

void StartSplunkMobileRum(void) {{
    // Keep the RUM token in build-time configuration, not tracked source.
    NSString *realm = @{code_string(platform['realm'])};
    NSString *rumToken = @"<RUM_TOKEN_FROM_BUILD_CONFIG>";
    NSString *appName = @{code_string(platform['app_name'])};
    NSString *environment = @{code_string(platform['deployment_environment'])};

    SPLKEndpointConfiguration *endpointConfiguration =
      [[SPLKEndpointConfiguration alloc] initWithRealm:realm rumAccessToken:rumToken];
    SPLKAgentConfiguration *agentConfiguration =
      [[SPLKAgentConfiguration alloc] initWithEndpoint:endpointConfiguration
                                               appName:appName
                                 deploymentEnvironment:environment];
    NSError *error = nil;
    SPLKAgent *agent = [SPLKAgent installWith:agentConfiguration error:&error];
    if (agent == nil) {{
        NSLog(@"Unable to start the Splunk RUM agent: %@", [error description]);
    }}
}}
"""
    session = f"""import SplunkAgent

enum SplunkMobileSessionReplayControls {{
    static func start() {{
        // Enterprise feature. Configure sampling at install time; reviewed target: {replay.get('sampling_rate', 0.2)}.
        SplunkRum.shared.sessionReplay.start()
    }}

    static func stop() {{
        SplunkRum.shared.sessionReplay.stop()
    }}

    static func status() -> String {{
        return String(describing: SplunkRum.shared.sessionReplay.state.status)
    }}

    static func notes() -> String {{
        return "configured={'enabled' if replay_enabled else 'disabled'}; use recording masks and sensitive view rules before production"
    }}
}}
"""
    webview = """import WebKit
import SplunkAgent

func attachSplunkBrowserRumBridge(to webView: WKWebView) {
    // Only load pages you control and have instrumented with Splunk Browser RUM.
    // The bridge shares the native session id with Browser RUM in the WebView.
    SplunkRum.shared.webViewNativeBridge.integrateWithBrowserRum(webView)
}
"""
    privacy = f"""# iOS Privacy Controls

{privacy_summary(platform)}
{session_replay_summary(platform)}

Use span filters to drop or replace URL query strings, customer identifiers,
and values that would populate `enduser.*` attributes.
"""
    dsym = f"""#!/usr/bin/env bash
set -euo pipefail
: "${{SPLUNK_O11Y_TOKEN_FILE:?set SPLUNK_O11Y_TOKEN_FILE to a chmod 600 org access-token file}}"
: "${{DSYM_PATH:?set DSYM_PATH to the .dSYM bundle or zip}}"

export SPLUNK_REALM={shell_quote(platform['realm'])}
export SPLUNK_ACCESS_TOKEN="$(<"${{SPLUNK_O11Y_TOKEN_FILE}}")"

splunk-rum ios upload \\
  --path "${{DSYM_PATH}}"

splunk-rum ios list
"""
    return {
        "Package.swift.snippet": package,
        "SplunkRumBootstrap.swift": swift,
        "SplunkRumBootstrap.m": objc,
        "SessionReplayControls.swift": session,
        "WebViewBrowserRumBridge.swift": webview,
        "privacy.md": privacy,
        "dsym-upload.sh": dsym,
    }


def android_files(platform: dict[str, Any]) -> dict[str, str]:
    versions = platform["versions"]
    attrs = common_attributes(platform)
    attrs_kotlin = kotlin_global_attribute_lines(attrs, indent="        ")
    attrs_java = java_global_attribute_lines(attrs, indent="        ")
    replay = platform["session_replay"]
    replay_enabled = boolish(replay.get("enabled"), False)
    gradle = f"""// Root build.gradle.kts or settings plugin management must include Maven Central.
repositories {{
    google()
    mavenCentral()
}}

// App module build.gradle.kts
plugins {{
    // Mapping and network auto-instrumentation plugins are pinned with the agent.
    id("com.splunk.rum-mapping-file-plugin") version "{versions['android_gradle_plugins']}"
    id("com.splunk.rum-okhttp3-auto-plugin") version "{versions['android_gradle_plugins']}"
    id("com.splunk.rum-httpurlconnection-auto-plugin") version "{versions['android_gradle_plugins']}"
}}

android {{
    defaultConfig {{
        minSdk = {platform['requirements'].get('android_min_api', 24)}
    }}
    compileOptions {{
        isCoreLibraryDesugaringEnabled = true
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }}
}}

dependencies {{
    implementation("com.splunk:splunk-otel-android:{versions['android_agent']}")
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.3")
}}

// Keep the org access token in CI or a local Gradle property; never commit it.
splunkRum {{
    enabled = true
    realm = "{platform['realm']}"
    apiAccessToken = providers.environmentVariable("SPLUNK_ACCESS_TOKEN").orNull
        ?: error("Set SPLUNK_ACCESS_TOKEN in CI before mapping upload")
    failBuildOnUploadFailure = false
}}

// Artifact coordinates for legacy buildscript classpath setups:
// classpath("com.splunk:rum-mapping-file-plugin:{versions['android_gradle_plugins']}")
// classpath("com.splunk:rum-okhttp3-auto-plugin:{versions['android_gradle_plugins']}")
// classpath("com.splunk:rum-httpurlconnection-auto-plugin:{versions['android_gradle_plugins']}")
"""
    kotlin = f"""package {str(platform.get('application_id') or 'com.example.mobile')}.observability

import android.app.Application
import com.splunk.rum.AgentConfiguration
import com.splunk.rum.EndpointConfiguration
import com.splunk.rum.SplunkRum

object SplunkRumBootstrap {{
    fun start(application: Application): SplunkRum {{
        val agent = SplunkRum.install(
            application = application,
            agentConfiguration = AgentConfiguration(
                endpoint = EndpointConfiguration(
                    realm = {code_string(platform['realm'])},
                    rumAccessToken = "<RUM_TOKEN_FROM_BUILD_CONFIG>"
                ),
                appName = {code_string(platform['app_name'])},
                deploymentEnvironment = {code_string(platform['deployment_environment'])},
                appVersion = {code_string(platform['app_version'])}
            )
        )
{attrs_kotlin}
        return agent
    }}
}}
"""
    java = f"""import android.app.Application;
import com.splunk.rum.AgentConfiguration;
import com.splunk.rum.EndpointConfiguration;
import com.splunk.rum.SplunkRum;

public final class SplunkRumBootstrap {{
    public static SplunkRum start(Application application) {{
        SplunkRum agent = SplunkRum.install(
            application,
            new AgentConfiguration(
                new EndpointConfiguration({code_string(platform['realm'])}, "<RUM_TOKEN_FROM_BUILD_CONFIG>"),
                {code_string(platform['app_name'])},
                {code_string(platform['deployment_environment'])},
                {code_string(platform['app_version'])}
            )
        );
{attrs_java}
        return agent;
    }}
}}
"""
    session = f"""package {str(platform.get('application_id') or 'com.example.mobile')}.observability

import com.splunk.rum.SplunkRum

object SplunkMobileSessionReplayControls {{
    fun start() {{
        // Enterprise feature. Configure sampling at install time; reviewed target: {replay.get('sampling_rate', 0.2)}.
        SplunkRum.instance.sessionReplay.start()
    }}

    fun stop() {{
        SplunkRum.instance.sessionReplay.stop()
    }}

    fun status(): String = SplunkRum.instance.sessionReplay.state.status.toString()

    fun configuredState(): String = "{'enabled' if replay_enabled else 'disabled'}"
}}
"""
    webview = """import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import com.splunk.rum.SplunkRum

fun attachSplunkBrowserRumBridge(webView: WebView, url: String) {
    // Only load pages you control and have instrumented with Splunk Browser RUM.
    val webSettings: WebSettings = webView.settings
    webSettings.javaScriptEnabled = true
    SplunkRum.instance.webViewNativeBridge.integrateWithBrowserRum(webView)
    webView.webViewClient = WebViewClient()
    webView.loadUrl(url)
}
"""
    mapping = f"""#!/usr/bin/env bash
set -euo pipefail
: "${{SPLUNK_O11Y_TOKEN_FILE:?set SPLUNK_O11Y_TOKEN_FILE to a chmod 600 org access-token file}}"
: "${{MAPPING_FILE:?set MAPPING_FILE to mapping.txt}}"
: "${{APPLICATION_ID:={str(platform.get('application_id') or 'com.example.mobile')}}}"
: "${{VERSION_CODE:?set VERSION_CODE to the Android versionCode for this build}}"

export SPLUNK_REALM={shell_quote(platform['realm'])}
export SPLUNK_ACCESS_TOKEN="$(<"${{SPLUNK_O11Y_TOKEN_FILE}}")"

splunk-rum android upload \\
  --app-id="${{APPLICATION_ID}}" \\
  --version-code="${{VERSION_CODE}}" \\
  --path="${{MAPPING_FILE}}"

# Alternative for CI manifests:
# splunk-rum android upload-with-manifest --manifest "${{ANDROID_MANIFEST}}" --path "${{MAPPING_FILE}}"

splunk-rum android list --app-id="${{APPLICATION_ID}}"
"""
    privacy = f"""# Android Privacy Controls

{privacy_summary(platform)}
{session_replay_summary(platform)}

Use View-level Session Replay masks for payment, health, auth, and profile
screens. For WebViews, hide sensitive DOM elements with CSS before enabling the
native bridge.
"""
    return {
        "build.gradle.kts.snippet": gradle,
        "SplunkRumBootstrap.kt": kotlin,
        "SplunkRumBootstrap.java": java,
        "SessionReplayControls.kt": session,
        "WebViewBrowserRumBridge.kt": webview,
        "privacy.md": privacy,
        "mapping-upload.sh": mapping,
    }


def react_native_files(platform: dict[str, Any]) -> dict[str, str]:
    versions = platform["versions"]
    replay = platform["session_replay"]
    replay_enabled = boolish(replay.get("enabled"), False)
    replay_modules = (
        f"[\n  new SessionReplayModuleConfiguration(true, {replay.get('sampling_rate', 0.2)}),\n]"
        if replay_enabled
        else "[]"
    )
    rn_attrs = rn_global_attribute_lines(common_attributes(platform), indent="  ")
    package = {
        "dependencies": {
            "@splunk/otel-react-native": versions["react_native_agent"],
        }
    }
    if replay_enabled:
        package["dependencies"]["@splunk/otel-session-replay-react-native"] = versions[
            "react_native_session_replay"
        ]
    provider = f"""import React from 'react';
import {{ SplunkRum, SplunkRumProvider, SessionReplayModuleConfiguration }} from '@splunk/otel-react-native';

const agentConfiguration = {{
  endpoint: {{
    realm: {code_string(platform['realm'])},
    rumAccessToken: '<RUM_TOKEN_FROM_BUILD_CONFIG>',
  }},
  appName: {code_string(platform['app_name'])},
  deploymentEnvironment: {code_string(platform['deployment_environment'])},
  appVersion: {code_string(platform['app_version'])},
  globalAttributes: {json.dumps(common_attributes(platform), indent=2)}
}};

const moduleConfigurations = {replay_modules};

export async function startSplunkRum() {{
  await SplunkRum.install(agentConfiguration, moduleConfigurations);
  const rum = SplunkRum.instance;
{rn_attrs}
}}

export function AppWithSplunkRum({{ children }}: {{ children: React.ReactNode }}) {{
  return <SplunkRumProvider agentConfiguration={{agentConfiguration}}>{{children}}</SplunkRumProvider>;
}}
"""
    session = f"""import {{ SplunkSessionReplay, MaskType }} from '@splunk/otel-session-replay-react-native';

export async function startMobileSessionReplay() {{
  await SplunkSessionReplay.instance.start();
}}

export async function stopMobileSessionReplay() {{
  await SplunkSessionReplay.instance.stop();
}}

export async function mobileSessionReplayStatus() {{
  return SplunkSessionReplay.instance.getState();
}}

export async function coverSensitiveRegion() {{
  await SplunkSessionReplay.instance.setRecordingMask({{
    elements: [
      {{
        rect: {{ x: 0, y: 100, width: 400, height: 200 }},
        type: MaskType.COVERING,
      }},
    ],
  }});
}}

export const mobileSessionReplayConfigured = {{
  enabled: {str(replay_enabled).lower()},
  samplingRate: {replay.get('sampling_rate', 0.2)},
  maskAllText: {str(boolish(replay.get('mask_all_text'), True)).lower()},
  maskAllInputs: {str(boolish(replay.get('mask_all_inputs'), True)).lower()},
}};
"""
    webview = """import { WebView } from 'react-native-webview';

export function InstrumentedWebView(props) {
  // Instrument the loaded page with Browser RUM separately and hand off to
  // splunk-observability-k8s-frontend-rum-setup for JS source maps.
  return <WebView {...props} injectedJavaScriptBeforeContentLoaded="window.__SPLUNK_NATIVE_WEBVIEW__ = true;" />;
}
"""
    native = f"""# React Native Native-Side Setup

- Requires React Native {platform['requirements'].get('react_native', '0.75.0')}+ and React {platform['requirements'].get('react', '18.2.0')}+.
- iOS requires iOS 15+ and `USE_FRAMEWORKS=dynamic` when the app uses the SDK pod path.
- Android runtime default is API {platform['requirements'].get('android_min_api', 24)}+.
- Bare React Native apps wire native iOS dSYM and Android mapping upload through the native helpers.
- Expo apps require a development build; Expo Go cannot load custom native modules.
- This skill does not claim React Native JS bundle source-map upload support. Browser source maps apply only to WebView Browser RUM handoff pages.
"""
    privacy = f"""# React Native Privacy Controls

{privacy_summary(platform)}
{session_replay_summary(platform)}

Mask TextInput, payment, health, profile, auth, and free-form text views before
enabling Session Replay. Keep user identity attributes out of global attributes
unless approved.
"""
    return {
        "package.json.snippet": json.dumps(package, indent=2) + "\n",
        "SplunkRumProvider.tsx": provider,
        "SessionReplayControls.ts": session,
        "WebViewBrowserRumBridge.tsx": webview,
        "native-setup.md": native,
        "privacy.md": privacy,
    }


def flutter_files(platform: dict[str, Any]) -> dict[str, str]:
    versions = platform["versions"]
    replay = platform["session_replay"]
    replay_enabled = boolish(replay.get("enabled"), False)
    flutter_attrs = flutter_global_attribute_lines(common_attributes(platform), indent="  ")
    replay_dependency = (
        f"  splunk_otel_flutter_session_replay: {versions['flutter_session_replay']}\n"
        if replay_enabled
        else f"# Add only when Session Replay is enabled:\n#   splunk_otel_flutter_session_replay: {versions['flutter_session_replay']}\n"
    )
    replay_module_config = (
        "    moduleConfigurations: [\n"
        "      SessionReplayModuleConfiguration(\n"
        "        isEnabled: true,\n"
        f"        samplingRate: {replay.get('sampling_rate', 0.2)},\n"
        "      ),\n"
        "    ],\n"
    )
    if not replay_enabled:
        replay_module_config = ""
    pubspec = f"""dependencies:
  splunk_otel_flutter: {versions['flutter_agent']}
{replay_dependency}

# Requires Flutter {platform['requirements'].get('flutter', '3.32.0')}+ and Dart {platform['requirements'].get('dart', '3.8.0')}+.
"""
    dart = f"""import 'package:flutter/widgets.dart';
import 'package:splunk_otel_flutter/splunk_otel_flutter.dart';

Future<void> startSplunkRum() async {{
  WidgetsFlutterBinding.ensureInitialized();
  await SplunkRum.instance.install(
    agentConfiguration: AgentConfiguration(
      endpointConfiguration: EndpointConfiguration.forRum(
        realm: {code_string(platform['realm'])},
        rumAccessToken: '<RUM_TOKEN_FROM_BUILD_CONFIG>',
      ),
      appName: {code_string(platform['app_name'])},
      deploymentEnvironment: {code_string(platform['deployment_environment'])},
      appVersion: {code_string(platform['app_version'])},
    ),
{replay_module_config}  );
{flutter_attrs}
}}

Future<void> trackSplunkScreen(String screenName) async {{
  await SplunkRum.instance.navigation.track(screenName: screenName);
}}

class SplunkRouteObserver extends RouteObserver<PageRoute<dynamic>> {{
  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) {{
    super.didPush(route, previousRoute);
    final name = route.settings.name;
    if (name != null) {{
      SplunkRum.instance.navigation.track(screenName: name);
    }}
  }}
}}

final RouteObserver<PageRoute<dynamic>> splunkRumRouteObserver =
    SplunkRouteObserver();
"""
    session = f"""import 'dart:ui';
import 'package:splunk_otel_flutter_session_replay/splunk_otel_flutter_session_replay.dart';

Future<void> startMobileSessionReplay() async {{
  await SplunkSessionReplay.instance.start();
}}

Future<void> stopMobileSessionReplay() async {{
  await SplunkSessionReplay.instance.stop();
}}

Future<SessionReplayStatus> mobileSessionReplayStatus() async {{
  return SplunkSessionReplay.instance.getStatus();
}}

Future<void> coverSensitiveRect(Rect rect) async {{
  await SplunkSessionReplay.instance.setRecordingMask(
    mask: RecordingMask(
      elements: [
        MaskElement(
          rect: rect,
          type: MaskType.covering,
        ),
      ],
    ),
  );
}}

const mobileSessionReplayConfigured = {{
  'enabled': {str(replay_enabled).lower()},
  'samplingRate': {replay.get('sampling_rate', 0.2)},
  'maskAllText': {str(boolish(replay.get('mask_all_text'), True)).lower()},
  'maskAllInputs': {str(boolish(replay.get('mask_all_inputs'), True)).lower()},
}};
"""
    native = f"""# Flutter Native-Side Setup

- Android runtime default is API {platform['requirements'].get('android_min_api', 24)}+.
- iOS requires iOS 15+.
- Use native iOS dSYM and Android mapping upload helpers for release artifacts.
- Browser source maps apply only to WebView Browser RUM handoff pages.
"""
    webview = """// WebView pages are Browser RUM surfaces. Instrument the hosted page with
// Browser RUM and use the native bridge only for pages you control.
"""
    privacy = f"""# Flutter Privacy Controls

{privacy_summary(platform)}
{session_replay_summary(platform)}

Mask TextField, payment, health, profile, auth, and free-form text widgets
before enabling Session Replay.
"""
    return {
        "pubspec.yaml.snippet": pubspec,
        "splunk_rum.dart": dart,
        "session_replay_controls.dart": session,
        "native-setup.md": native,
        "webview_browser_rum_bridge.dart": webview,
        "privacy.md": privacy,
    }


PLATFORM_RENDERERS = {
    "ios": ios_files,
    "android": android_files,
    "react_native": react_native_files,
    "flutter": flutter_files,
}


def unified_new_file_patch(path: str, content: str) -> str:
    lines = content.splitlines()
    body = "\n".join(f"+{line}" for line in lines)
    if body:
        body += "\n"
    return (
        f"diff --git a/{path} b/{path}\n"
        "new file mode 100644\n"
        "index 0000000..0000000\n"
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n"
        f"{body}"
    )


def patch_payload(platform: dict[str, Any], files: dict[str, str]) -> tuple[str, str] | None:
    platform_name = platform["platform"]
    if platform_name == "ios":
        return "splunk-rum/SplunkRumBootstrap.swift", files["SplunkRumBootstrap.swift"]
    if platform_name == "android":
        return "splunk-rum/SplunkRumBootstrap.kt", files["SplunkRumBootstrap.kt"]
    if platform_name == "react_native":
        return "src/splunkRum.tsx", files["SplunkRumProvider.tsx"]
    if platform_name == "flutter":
        return "lib/splunk_rum.dart", files["splunk_rum.dart"]
    return None


def render_patch_helper(platforms: list[dict[str, Any]], root: Path) -> str:
    entries = []
    for platform in platforms:
        app_root = str(platform.get("app_root") or "")
        name = f"{platform['platform']}-{slug(platform['app_name'])}.patch"
        entries.append((platform["app_name"], platform["platform"], app_root, name))
    case_lines = []
    for app_name, platform, app_root, patch_name in entries:
        case_lines.append(
            "apply_one "
            f"{shell_quote(app_name)} {shell_quote(platform)} {shell_quote(app_root)} "
            f"\"${{PATCH_DIR}}/{patch_name}\""
        )
    return f"""#!/usr/bin/env bash
set -euo pipefail

PATCH_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/source-patches" && pwd)"
: "${{ACCEPT_MOBILE_RUM_SOURCE_EDIT:?set ACCEPT_MOBILE_RUM_SOURCE_EDIT=true after reviewing generated patches}}"

apply_one() {{
  local app_name="$1"
  local platform="$2"
  local app_root="$3"
  local patch_file="$4"
  if [[ -z "${{app_root}}" ]]; then
    echo "SKIP ${{app_name}} (${{platform}}): app_root is empty" >&2
    return 0
  fi
  if [[ ! -d "${{app_root}}" ]]; then
    echo "ERROR: app_root not found for ${{app_name}}: ${{app_root}}" >&2
    return 1
  fi
  if [[ ! -f "${{patch_file}}" ]]; then
    echo "ERROR: patch file missing: ${{patch_file}}" >&2
    return 1
  fi
  (
    cd "${{app_root}}"
    git apply --check "${{patch_file}}"
    git apply "${{patch_file}}"
  )
  echo "Applied ${{patch_file}} to ${{app_root}}"
}}

{chr(10).join(case_lines)}
"""


def render_runbook(spec: dict[str, Any], warnings: list[str]) -> str:
    lines = [
        "# Splunk Observability Mobile RUM Runbook",
        "",
        f"Spec version: `{API_VERSION}`",
        f"Source mode: `{spec['source_mode']}`",
        f"Realm: `{spec['realm']}`",
        "",
        "## Guardrails",
        "",
        "- Do not commit raw RUM or org access token values. Use build-time config, secrets managers, or CI secret stores.",
        "- RUM tokens are client-exposed after build, but this skill still keeps them out of tracked source.",
        "- Session Replay is enterprise-tier and must be reviewed with privacy/legal owners before rollout.",
        "- WebViews are Browser RUM surfaces; use the generated bridge only for pages you control.",
        "",
        "## Platform Steps",
        "",
    ]
    for platform in spec["platforms"]:
        lines.extend(
            [
                f"### {platform['app_name']} ({platform['platform']})",
                "",
                f"- App root: `{platform.get('app_root') or '<not set>'}`",
                f"- Deployment environment: `{platform['deployment_environment']}`",
                f"- App version: `{platform['app_version']}`",
                "- Review the platform snippets and add the SDK dependency with the pinned version.",
                "- Wire token retrieval through build-time configuration or runtime secret delivery.",
                "- Add release/build global attributes before rollout.",
                "- Run local privacy masking checks before enabling Session Replay in production.",
                "",
            ]
        )
    if spec["source_mode"] == "render-patches":
        lines.extend(
            [
                "## Source Patches",
                "",
                "Patch files are rendered under `source-patches/`. Review them, then apply manually or run:",
                "",
                "```bash",
                "ACCEPT_MOBILE_RUM_SOURCE_EDIT=true ./apply-source-patches.sh",
                "```",
                "",
            ]
        )
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")
    return "\n".join(lines)


def render_preflight(spec: dict[str, Any], warnings: list[str]) -> str:
    lines = [
        "# Mobile RUM Preflight Report",
        "",
        "## Failures",
        "",
        "None.",
        "",
        "## Warnings",
        "",
    ]
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("None.")
    lines.extend(
        [
            "",
            "## Advisories",
            "",
            f"- Default iOS agent: {DEFAULT_VERSIONS['ios_agent']}.",
            f"- Default Android agent and Gradle plugins: {DEFAULT_VERSIONS['android_agent']}.",
            f"- Default React Native agent: {DEFAULT_VERSIONS['react_native_agent']}; Session Replay: {DEFAULT_VERSIONS['react_native_session_replay']}.",
            f"- Default Flutter agent: {DEFAULT_VERSIONS['flutter_agent']}; Session Replay: {DEFAULT_VERSIONS['flutter_session_replay']}.",
            "- React Native and Flutter native symbols route to iOS dSYM and Android mapping workflows.",
            "- JS/browser source maps are only for Browser RUM inside WebViews.",
        ]
    )
    if any(as_list(p.get("webviews")) for p in spec["platforms"]):
        lines.append("- WebView Browser RUM handoff emitted.")
    return "\n".join(lines) + "\n"


def render_browser_handoff(spec: dict[str, Any]) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

echo "WebView pages are Browser RUM surfaces. Use the Kubernetes/browser skill for hosted page injection and JS source maps:"
echo "  bash skills/splunk-observability-k8s-frontend-rum-setup/scripts/setup.sh --render --realm {spec['realm']}"
"""


def render_auto_instrumentation_handoff(url: str = "") -> str:
    url_note = f" for {url}" if url else ""
    return f"""#!/usr/bin/env bash
set -euo pipefail

echo "RUM-to-APM Server-Timing traceparent was missing or invalid{url_note}."
echo "Enable Splunk APM response header injection on the backend, then re-run validate.sh --check-server-timing."
echo "For Kubernetes backends, start with:"
echo "  bash skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/setup.sh --render"
"""


def render_handoff(kind: str) -> str:
    if kind == "dashboards":
        target = "splunk-observability-dashboard-builder"
        message = "Render starter Mobile RUM dashboards for app launches, crashes, network, slow rendering, and sessions."
    else:
        target = "splunk-observability-native-ops"
        message = "Render starter Mobile RUM detectors for crash rate, ANR, network error spikes, and slow rendering."
    return f"""#!/usr/bin/env bash
set -euo pipefail

echo {shell_quote(message)}
echo "Next skill: {target}"
"""


def server_timing_traceparent_status(headers: str) -> dict[str, str]:
    """Validate Server-Timing traceparent entries.

    Returns status=valid when at least one valid traceparent entry is present.
    If multiple valid entries are present, the returned traceparent is the last
    valid value, matching Splunk RUM's "last valid header wins" behavior.
    """

    server_timing_values = SERVER_TIMING_LINE_RE.findall(headers or "")
    if not server_timing_values:
        return {"status": "missing", "message": "Server-Timing header is missing."}
    matches: list[str] = []
    for value in server_timing_values:
        matches.extend(match.group(1) for match in TRACEPARENT_RE.finditer(value))
    if matches:
        return {
            "status": "valid",
            "traceparent": matches[-1],
            "message": "Server-Timing traceparent is valid; last valid header wins.",
        }
    return {
        "status": "invalid",
        "message": "Server-Timing header is present but no valid traceparent desc was found.",
    }


def render_assets(spec: dict[str, Any], output_dir: Path, warnings: list[str]) -> dict[str, Any]:
    rendered: list[str] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    spec_digest = hashlib.sha256(
        json.dumps(spec, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    platform_summaries: list[dict[str, Any]] = []
    any_webviews = False
    any_replay = False

    for index, platform in enumerate(spec["platforms"]):
        platform_name = platform["platform"]
        app_slug = slug(f"{platform_name}-{platform['app_name']}")
        target_dir = output_dir / platform_name / app_slug
        files = PLATFORM_RENDERERS[platform_name](platform)
        for name, content in files.items():
            write_file(
                target_dir / name,
                content,
                executable=name.endswith(".sh"),
                rendered=rendered,
                root=output_dir,
            )
        if spec["source_mode"] in {"render-patches", "apply-patches"}:
            payload = patch_payload(platform, files)
            if payload:
                patch_path, patch_content = payload
                patch_name = f"{platform_name}-{slug(platform['app_name'])}.patch"
                write_file(
                    output_dir / "source-patches" / patch_name,
                    unified_new_file_patch(patch_path, patch_content),
                    rendered=rendered,
                    root=output_dir,
                )
        replay_enabled = boolish(deep_get(platform, "session_replay", "enabled"), False)
        any_replay = any_replay or replay_enabled
        any_webviews = any_webviews or bool(as_list(platform.get("webviews")))
        platform_summaries.append(
            {
                "index": index,
                "platform": platform_name,
                "app_name": platform["app_name"],
                "app_root": platform.get("app_root") or "",
                "app_version": platform["app_version"],
                "deployment_environment": platform["deployment_environment"],
                "session_replay_enabled": replay_enabled,
                "versions": {key: platform["versions"][key] for key in VERSION_KEYS_BY_PLATFORM[platform_name]},
                "validation_urls": as_list(platform.get("validation_urls")),
            }
        )

    if spec["source_mode"] in {"render-patches", "apply-patches"}:
        write_file(
            output_dir / "apply-source-patches.sh",
            render_patch_helper(spec["platforms"], output_dir),
            executable=True,
            rendered=rendered,
            root=output_dir,
        )

    write_file(output_dir / "runbook.md", render_runbook(spec, warnings), rendered=rendered, root=output_dir)
    write_file(output_dir / "preflight-report.md", render_preflight(spec, warnings), rendered=rendered, root=output_dir)
    write_file(
        output_dir / "version-lock.json",
        json.dumps(
            {
                "verified_on": "2026-05-19",
                "defaults": DEFAULT_VERSIONS,
                "sources": {
                    "ios": "https://github.com/signalfx/splunk-otel-ios/releases/tag/2.2.3",
                    "android": "https://central.sonatype.com/artifact/com.splunk/splunk-otel-android",
                    "react_native": "https://registry.npmjs.org/%40splunk%2Fotel-react-native/latest",
                    "react_native_session_replay": "https://registry.npmjs.org/%40splunk%2Fotel-session-replay-react-native/latest",
                    "flutter": "https://pub.dev/api/packages/splunk_otel_flutter",
                    "flutter_session_replay": "https://pub.dev/api/packages/splunk_otel_flutter_session_replay",
                },
            },
            indent=2,
        )
        + "\n",
        rendered=rendered,
        root=output_dir,
    )
    write_file(output_dir / "handoff-dashboards.sh", render_handoff("dashboards"), executable=True, rendered=rendered, root=output_dir)
    write_file(output_dir / "handoff-detectors.sh", render_handoff("detectors"), executable=True, rendered=rendered, root=output_dir)
    if any_webviews:
        write_file(output_dir / "handoff-browser-rum.sh", render_browser_handoff(spec), executable=True, rendered=rendered, root=output_dir)
    write_file(output_dir / "handoff-auto-instrumentation.sh", render_auto_instrumentation_handoff(), executable=True, rendered=rendered, root=output_dir)

    metadata = {
        "skill": SKILL_NAME,
        "api_version": API_VERSION,
        "spec_digest": spec_digest,
        "realm": spec["realm"],
        "source_mode": spec["source_mode"],
        "versions": spec["versions"],
        "allow_latest_version": spec["allow_latest_version"],
        "session_replay_enabled": any_replay,
        "platforms": platform_summaries,
        "warnings": warnings,
        "rendered_files": sorted(rendered + ["metadata.json"]),
        "rum_token_ref": spec.get("rum_token_ref"),
        "org_access_token_ref": spec.get("org_access_token_ref"),
    }
    write_file(output_dir / "metadata.json", json.dumps(metadata, indent=2) + "\n", rendered=rendered, root=output_dir)
    return metadata


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        reject_direct_secret_args(argv)
        args = parse_args(argv)
        if args.spec:
            raw = load_spec(Path(args.spec))
            raw = merge_cli_overrides(raw, args)
        else:
            raw = build_spec_from_args(args)
        spec, warnings, _ = normalize_spec(
            raw,
            allow_latest=args.allow_latest_version,
            accept_session_replay=args.accept_session_replay_enterprise,
            accept_source_edit=args.accept_mobile_rum_source_edit,
            allow_lower_android_api=args.allow_lower_android_api,
        )
        output_dir = Path(args.output_dir)
        if args.dry_run:
            payload = {
                "would_render": True,
                "output_dir": str(output_dir),
                "source_mode": spec["source_mode"],
                "platforms": [p["platform"] for p in spec["platforms"]],
                "warnings": warnings,
            }
            print(json.dumps(payload, indent=2) if args.json else dump_yaml(payload), end="")
            return 0
        metadata = render_assets(spec, output_dir, warnings)
        if args.json:
            print(json.dumps(metadata, indent=2))
        else:
            print(f"Rendered {len(metadata['rendered_files'])} files to {output_dir}")
        return 0
    except SpecError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
