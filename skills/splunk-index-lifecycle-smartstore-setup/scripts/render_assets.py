#!/usr/bin/env python3
"""Render Splunk index lifecycle and SmartStore assets."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
from pathlib import Path
from typing import Any


OPERATIONS = (
    "inventory",
    "retention",
    "smartstore",
    "archive",
    "disable-index",
    "delete-index",
    "clean-data",
    "restore-handoff",
)

DESTRUCTIVE_OPERATIONS = {"delete-index", "clean-data"}
DISRUPTIVE_OPERATIONS = DESTRUCTIVE_OPERATIONS | {"disable-index"}
PROTECTED_DEFAULT_INDEXES = {"main", "summary", "history", "lastchanceindex", "splunklogger"}
SENSITIVE_INDEXES = {
    "notable",
    "risk",
    "threat_activity",
    "threat_intel",
    "itsi_summary",
    "itsi_summary_metrics",
    "itsi_tracked_alerts",
    "ari_staging",
    "ari_asset",
    "ari_internal",
    "ari_ta",
}

GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "indexes.conf.template",
    "retention-indexes.conf.template",
    "indexes-disable.conf.template",
    "server.conf",
    "limits.conf",
    "preflight.sh",
    "apply-cluster-manager.sh",
    "apply-standalone-indexer.sh",
    "status.sh",
    "index-lifecycle-report.md",
    "index-lifecycle-report.json",
    "index-dependency-report.md",
    "index-dependency-report.json",
    "collection-searches.spl",
    "collect-evidence.sh",
    "retention-change-plan.md",
    "destructive-action-plan.md",
    "acs-index-update-payload.json",
    "apply-retention-enterprise.sh",
    "apply-retention-cloud.sh",
    "apply-disable-index.sh",
    "apply-delete-index.sh",
    "apply-clean-data.sh",
    "archive-handoff.sh",
    "restore-handoff.sh",
    "restore-handoff.md",
    "peer-cleanup-runbook.md",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk index lifecycle and SmartStore assets.")
    parser.add_argument("--deployment", choices=("cluster", "standalone"), default="cluster")
    parser.add_argument("--platform", choices=("enterprise", "cloud"), default="enterprise")
    parser.add_argument("--operation", choices=OPERATIONS, default="smartstore")
    parser.add_argument("--scope", choices=("per-index", "global"), default="per-index")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--splunk-home", default="/opt/splunk")
    parser.add_argument("--app-name", default="ZZZ_cisco_skills_smartstore")
    parser.add_argument("--stack", default="")
    parser.add_argument("--acs-base", default="https://admin.splunk.com")
    parser.add_argument("--datatype", choices=("event", "metric"), default="event")
    parser.add_argument("--remote-provider", choices=("s3", "gcs", "azure"), default="s3")
    parser.add_argument("--volume-name", default="remote_store")
    parser.add_argument("--remote-path", default="")
    parser.add_argument("--indexes", default="main")
    parser.add_argument("--max-total-data-size-mb", default="")
    parser.add_argument("--max-global-data-size-mb", default="")
    parser.add_argument("--max-global-raw-data-size-mb", default="")
    parser.add_argument("--frozen-time-period-in-secs", default="")
    parser.add_argument("--searchable-days", default="")
    parser.add_argument("--archival-retention-days", default="")
    parser.add_argument("--max-data-size-mb", default="")
    parser.add_argument("--cache-size-mb", default="")
    parser.add_argument("--eviction-policy", default="")
    parser.add_argument("--eviction-padding-mb", default="")
    parser.add_argument("--hotlist-recency-secs", default="")
    parser.add_argument("--hotlist-bloom-filter-recency-hours", default="")
    parser.add_argument("--index-hotlist-recency-secs", default="")
    parser.add_argument("--index-hotlist-bloom-filter-recency-hours", default="")
    parser.add_argument("--s3-endpoint", default="")
    parser.add_argument("--s3-auth-region", default="")
    parser.add_argument("--s3-signature-version", default="")
    parser.add_argument("--s3-supports-versioning", choices=("true", "false", "unset"), default="unset")
    parser.add_argument("--s3-tsidx-compression", choices=("true", "false", "unset"), default="unset")
    parser.add_argument("--s3-encryption", choices=("unset", "none", "sse-s3", "sse-kms", "sse-c"), default="unset")
    parser.add_argument("--s3-kms-key-id", default="")
    parser.add_argument("--s3-kms-auth-region", default="")
    parser.add_argument("--s3-ssl-verify-server-cert", choices=("true", "false", "unset"), default="unset")
    parser.add_argument("--s3-ssl-versions", default="")
    parser.add_argument("--s3-access-key-file", default="")
    parser.add_argument("--s3-secret-key-file", default="")
    parser.add_argument("--gcs-credential-file", default="")
    parser.add_argument("--azure-endpoint", default="")
    parser.add_argument("--azure-container-name", default="")
    parser.add_argument("--bucket-localize-acquire-lock-timeout-sec", default="")
    parser.add_argument("--bucket-localize-connect-timeout-max-retries", default="")
    parser.add_argument("--bucket-localize-max-timeout-sec", default="")
    parser.add_argument("--clean-remote-storage-by-default", choices=("true", "false"), default="false")
    parser.add_argument("--apply-cluster-bundle", choices=("true", "false"), default="false")
    parser.add_argument("--restart-splunk", choices=("true", "false"), default="true")
    parser.add_argument("--evidence-file", default="")
    parser.add_argument("--session-key-file", default="")
    parser.add_argument("--splunk-uri", default="https://localhost:8089")
    parser.add_argument("--acs-token-file", default="/tmp/acs_token")
    parser.add_argument("--owner-approval-file", default="")
    parser.add_argument("--backup-evidence-file", default="")
    parser.add_argument("--accept-destructive-index-delete", action="store_true")
    parser.add_argument("--confirm-token", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


def bool_value(value: str) -> bool:
    return value.lower() == "true"


def no_newline(value: str, option: str) -> None:
    if "\n" in value or "\r" in value:
        die(f"{option} must not contain newlines.")


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def make_script(body: str) -> str:
    return "#!/usr/bin/env bash\nset -euo pipefail\n\n" + body.lstrip()


def clean_render_dir(render_dir: Path) -> None:
    for rel in GENERATED_FILES:
        candidate = render_dir / rel
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink()


def csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def target_indexes(args: argparse.Namespace) -> list[str]:
    if args.indexes.strip().lower() == "all":
        return []
    return csv_list(args.indexes)


def validate_index_name(value: str) -> None:
    if not re.fullmatch(r"[a-z0-9_][a-z0-9_-]*", value or ""):
        die(
            f"Invalid index name {value!r}; use lowercase letters, numbers, "
            "underscores, and hyphens."
        )
    if "kvstore" in value:
        die(f"Invalid index name {value!r}; index names must not contain 'kvstore'.")


def validate_stack_name(value: str) -> None:
    if value and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        die("--stack must be a valid Splunk Cloud stack name.")


def validate_nonnegative_int(value: str, option: str, allow_empty: bool = True) -> None:
    if allow_empty and not value:
        return
    if not re.fullmatch(r"[0-9]+", value or ""):
        die(f"{option} must be a nonnegative integer.")


def validate(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", args.app_name or ""):
        die("--app-name must contain only letters, numbers, underscore, dot, colon, or hyphen.")
    if not re.fullmatch(r"[A-Za-z0-9_]+", args.volume_name or ""):
        die("--volume-name must contain only letters, numbers, and underscores.")
    validate_stack_name(args.stack)
    if not args.acs_base.startswith("https://"):
        die("--acs-base must be an https URL.")
    if not args.splunk_uri.startswith(("https://", "http://")):
        die("--splunk-uri must be an http or https URL.")

    indexes_all = args.indexes.strip().lower() == "all"
    indexes = target_indexes(args)
    if args.operation == "smartstore" and indexes_all:
        die("--indexes all is not valid for SmartStore rendering; provide explicit index names.")
    if args.operation in DISRUPTIVE_OPERATIONS and indexes_all:
        die(f"--indexes all is not allowed for {args.operation}; provide explicit index names.")
    if args.operation not in {"inventory"} and not indexes and not indexes_all:
        die("--indexes must contain at least one index.")
    for index in indexes:
        validate_index_name(index)

    for value, option in (
        (args.remote_path, "--remote-path"),
        (args.indexes, "--indexes"),
        (args.eviction_policy, "--eviction-policy"),
        (args.s3_endpoint, "--s3-endpoint"),
        (args.s3_auth_region, "--s3-auth-region"),
        (args.s3_signature_version, "--s3-signature-version"),
        (args.s3_kms_key_id, "--s3-kms-key-id"),
        (args.s3_kms_auth_region, "--s3-kms-auth-region"),
        (args.s3_ssl_versions, "--s3-ssl-versions"),
        (args.s3_access_key_file, "--s3-access-key-file"),
        (args.s3_secret_key_file, "--s3-secret-key-file"),
        (args.gcs_credential_file, "--gcs-credential-file"),
        (args.azure_endpoint, "--azure-endpoint"),
        (args.azure_container_name, "--azure-container-name"),
        (args.stack, "--stack"),
        (args.acs_base, "--acs-base"),
        (args.evidence_file, "--evidence-file"),
        (args.session_key_file, "--session-key-file"),
        (args.splunk_uri, "--splunk-uri"),
        (args.acs_token_file, "--acs-token-file"),
        (args.owner_approval_file, "--owner-approval-file"),
        (args.backup_evidence_file, "--backup-evidence-file"),
    ):
        no_newline(value, option)
    for token in args.confirm_token:
        no_newline(token, "--confirm-token")

    for value, option in (
        (args.max_total_data_size_mb, "--max-total-data-size-mb"),
        (args.max_global_data_size_mb, "--max-global-data-size-mb"),
        (args.max_global_raw_data_size_mb, "--max-global-raw-data-size-mb"),
        (args.frozen_time_period_in_secs, "--frozen-time-period-in-secs"),
        (args.searchable_days, "--searchable-days"),
        (args.archival_retention_days, "--archival-retention-days"),
        (args.max_data_size_mb, "--max-data-size-mb"),
        (args.cache_size_mb, "--cache-size-mb"),
        (args.eviction_padding_mb, "--eviction-padding-mb"),
        (args.hotlist_recency_secs, "--hotlist-recency-secs"),
        (args.hotlist_bloom_filter_recency_hours, "--hotlist-bloom-filter-recency-hours"),
        (args.index_hotlist_recency_secs, "--index-hotlist-recency-secs"),
        (args.index_hotlist_bloom_filter_recency_hours, "--index-hotlist-bloom-filter-recency-hours"),
        (args.bucket_localize_acquire_lock_timeout_sec, "--bucket-localize-acquire-lock-timeout-sec"),
        (args.bucket_localize_connect_timeout_max_retries, "--bucket-localize-connect-timeout-max-retries"),
        (args.bucket_localize_max_timeout_sec, "--bucket-localize-max-timeout-sec"),
    ):
        validate_nonnegative_int(value, option)

    if args.operation == "smartstore":
        if not args.remote_path:
            die("--remote-path is required for --operation smartstore.")
        scheme = args.remote_path.split(":", 1)[0]
        expected_scheme = {"s3": "s3", "gcs": "gs", "azure": "azure"}[args.remote_provider]
        if scheme != expected_scheme:
            die(f"--remote-path must start with {expected_scheme}:// for --remote-provider {args.remote_provider}.")
    elif args.remote_path:
        scheme = args.remote_path.split(":", 1)[0]
        expected_scheme = {"s3": "s3", "gcs": "gs", "azure": "azure"}[args.remote_provider]
        if scheme != expected_scheme:
            die(f"--remote-path must start with {expected_scheme}:// for --remote-provider {args.remote_provider}.")

    if args.operation == "clean-data" and args.deployment == "cluster":
        die("--operation clean-data is blocked for indexer clusters; Splunk does not support clean on clustered indexes.")
    if args.operation == "delete-index":
        for index in indexes:
            reason = protected_index_reason(index, {}, strict=True)
            if reason.startswith("internal index"):
                die(f"Refusing to render delete workflow for {index}: {reason}.")
    if args.eviction_policy and not re.fullmatch(r"[A-Za-z0-9_-]+", args.eviction_policy):
        die("--eviction-policy must contain only letters, numbers, underscores, and hyphens.")
    if (args.s3_access_key_file and not args.s3_secret_key_file) or (args.s3_secret_key_file and not args.s3_access_key_file):
        die("--s3-access-key-file and --s3-secret-key-file must be supplied together.")
    if args.s3_encryption in {"sse-kms", "sse-c"} and not args.s3_kms_key_id:
        die("--s3-kms-key-id is required when --s3-encryption is sse-kms or sse-c.")
    if args.remote_provider != "s3" and (
        args.s3_endpoint
        or args.s3_auth_region
        or args.s3_signature_version
        or args.s3_access_key_file
        or args.s3_secret_key_file
        or args.s3_supports_versioning != "unset"
        or args.s3_tsidx_compression != "unset"
        or args.s3_encryption != "unset"
        or args.s3_kms_key_id
        or args.s3_kms_auth_region
        or args.s3_ssl_verify_server_cert != "unset"
        or args.s3_ssl_versions
    ):
        die("remote.s3 settings can only be used with --remote-provider s3.")
    if args.remote_provider != "gcs" and args.gcs_credential_file:
        die("--gcs-credential-file can only be used with --remote-provider gcs.")
    if args.remote_provider != "azure" and (args.azure_endpoint or args.azure_container_name):
        die("remote.azure settings can only be used with --remote-provider azure.")
    if args.archival_retention_days and args.searchable_days:
        if int(args.archival_retention_days) <= int(args.searchable_days):
            die("--archival-retention-days must be greater than --searchable-days.")


def load_evidence(path: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not path:
        return {}, {"provided": False, "loaded": False, "path": ""}
    evidence_path = Path(path).expanduser()
    status: dict[str, Any] = {"provided": True, "loaded": False, "path": str(evidence_path)}
    if not evidence_path.exists():
        status["error"] = "file_not_found"
        return {}, status
    try:
        data = json.loads(evidence_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - exact parser messages vary
        status["error"] = f"invalid_json: {exc}"
        return {}, status
    if not isinstance(data, dict):
        status["error"] = "top_level_json_must_be_object"
        return {}, status
    status["loaded"] = True
    return data, status


def evidence_list(evidence: dict[str, Any], *paths: str) -> set[str]:
    values: set[str] = set()
    for path in paths:
        node: Any = evidence
        for part in path.split("."):
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(part)
        if isinstance(node, list):
            values.update(str(item) for item in node)
        elif isinstance(node, str):
            values.add(node)
    return values


def evidence_index_record(evidence: dict[str, Any], index: str) -> dict[str, Any]:
    candidates: list[Any] = []
    destructive = evidence.get("destructive_actions")
    if isinstance(destructive, dict):
        indexes = destructive.get("indexes")
        if isinstance(indexes, dict):
            candidates.append(indexes.get(index))
    indexes_node = evidence.get("indexes")
    if isinstance(indexes_node, dict):
        for key in ("by_name", "inventory", "classification", "classifications"):
            child = indexes_node.get(key)
            if isinstance(child, dict):
                candidates.append(child.get(index))
        direct = indexes_node.get(index)
        if isinstance(direct, dict):
            candidates.append(direct)
        inventory = indexes_node.get("inventory")
        if isinstance(inventory, list):
            for item in inventory:
                if isinstance(item, dict) and item.get("name") == index:
                    candidates.append(item)
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return {}


def evidence_marks_nonprod(index: str, evidence: dict[str, Any]) -> bool:
    nonprod = evidence_list(
        evidence,
        "non_production_test_indexes",
        "indexes.non_production_test",
        "destructive_actions.non_production_test_indexes",
    )
    if index in nonprod:
        return True
    record = evidence_index_record(evidence, index)
    return bool(record.get("non_production_test") or record.get("classification") == "non-production-test")


def evidence_marks_sensitive_approved(index: str, evidence: dict[str, Any]) -> bool:
    approved = evidence_list(
        evidence,
        "sensitive_delete_approved_indexes",
        "destructive_actions.sensitive_delete_approved_indexes",
    )
    return index in approved


def evidence_marks_safe_to_delete(index: str, evidence: dict[str, Any]) -> bool:
    safe_indexes = evidence_list(evidence, "safe_to_delete_indexes", "destructive_actions.safe_to_delete_indexes")
    if index in safe_indexes:
        return True
    record = evidence_index_record(evidence, index)
    if not record:
        return False
    return bool(record.get("safe_to_delete") is True and record.get("dependencies_clear", True) is not False)


def protected_index_reason(index: str, evidence: dict[str, Any], strict: bool = False) -> str:
    if index.startswith("_"):
        return "internal index names beginning with '_' are hard-blocked"
    if index in PROTECTED_DEFAULT_INDEXES and not evidence_marks_nonprod(index, evidence):
        return "protected default index requires non-production test classification in evidence"
    if index in SENSITIVE_INDEXES and not evidence_marks_sensitive_approved(index, evidence):
        return "ES/ITSI/ARI-sensitive index requires explicit sensitive delete approval in evidence"
    if strict and index in PROTECTED_DEFAULT_INDEXES:
        return "protected default index"
    return ""


def index_search_clause(args: argparse.Namespace, field: str = "title") -> str:
    indexes = target_indexes(args)
    if not indexes:
        return ""
    return " OR ".join(f'{field}="{index}"' for index in indexes)


def retention_lines(args: argparse.Namespace) -> list[str]:
    lines: list[str] = []
    if args.max_global_data_size_mb:
        lines.append(f"maxGlobalDataSizeMB = {args.max_global_data_size_mb}")
    if args.max_global_raw_data_size_mb:
        lines.append(f"maxGlobalRawDataSizeMB = {args.max_global_raw_data_size_mb}")
    if args.frozen_time_period_in_secs:
        lines.append(f"frozenTimePeriodInSecs = {args.frozen_time_period_in_secs}")
    return lines


def enterprise_retention_lines(args: argparse.Namespace) -> list[str]:
    lines: list[str] = []
    if args.max_total_data_size_mb:
        lines.append(f"maxTotalDataSizeMB = {args.max_total_data_size_mb}")
    if args.frozen_time_period_in_secs:
        lines.append(f"frozenTimePeriodInSecs = {args.frozen_time_period_in_secs}")
    return lines


def render_indexes(args: argparse.Namespace) -> str:
    indexes = target_indexes(args)
    lines = [
        "# Rendered by splunk-index-lifecycle-smartstore-setup. Review before applying.",
        "# SmartStore remote volume paths must be unique per running indexer or indexer cluster.",
    ]
    if args.scope == "global":
        lines.extend(["[default]", f"remotePath = volume:{args.volume_name}/$_index_name"])
        if args.deployment == "cluster":
            lines.append("repFactor = auto")
        lines.extend(retention_lines(args))
        lines.append("")
    lines.extend([f"[volume:{args.volume_name}]", "storageType = remote", f"path = {args.remote_path}"])
    if args.remote_provider == "s3":
        if args.s3_endpoint:
            lines.append(f"remote.s3.endpoint = {args.s3_endpoint}")
        if args.s3_auth_region:
            lines.append(f"remote.s3.auth_region = {args.s3_auth_region}")
        if args.s3_signature_version:
            lines.append(f"remote.s3.signature_version = {args.s3_signature_version}")
        if args.s3_supports_versioning != "unset":
            lines.append(f"remote.s3.supports_versioning = {args.s3_supports_versioning}")
        if args.s3_tsidx_compression != "unset":
            lines.append(f"remote.s3.tsidx_compression = {args.s3_tsidx_compression}")
        if args.s3_encryption != "unset":
            lines.append(f"remote.s3.encryption = {args.s3_encryption}")
        if args.s3_kms_key_id:
            lines.append(f"remote.s3.kms.key_id = {args.s3_kms_key_id}")
        if args.s3_kms_auth_region:
            lines.append(f"remote.s3.kms.auth_region = {args.s3_kms_auth_region}")
        if args.s3_ssl_verify_server_cert != "unset":
            lines.append(f"remote.s3.sslVerifyServerCert = {args.s3_ssl_verify_server_cert}")
        if args.s3_ssl_versions:
            lines.append(f"remote.s3.sslVersions = {args.s3_ssl_versions}")
        if args.s3_access_key_file:
            lines.append("remote.s3.access_key = __SMARTSTORE_S3_ACCESS_KEY_FROM_FILE__")
            lines.append("remote.s3.secret_key = __SMARTSTORE_S3_SECRET_KEY_FROM_FILE__")
    elif args.remote_provider == "gcs" and args.gcs_credential_file:
        lines.append(f"remote.gs.credential_file = {args.gcs_credential_file}")
    elif args.remote_provider == "azure":
        if args.azure_endpoint:
            lines.append(f"remote.azure.endpoint = {args.azure_endpoint}")
        if args.azure_container_name:
            lines.append(f"remote.azure.container_name = {args.azure_container_name}")
    lines.append("")
    for index in indexes:
        lines.extend(
            [
                f"[{index}]",
                f"homePath = $SPLUNK_DB/{index}/db",
                f"coldPath = $SPLUNK_DB/{index}/colddb",
                f"thawedPath = $SPLUNK_DB/{index}/thaweddb",
            ]
        )
        if args.deployment == "cluster":
            lines.append("repFactor = auto")
        if args.scope == "per-index":
            lines.append(f"remotePath = volume:{args.volume_name}/$_index_name")
            lines.extend(retention_lines(args))
        if args.index_hotlist_recency_secs:
            lines.append(f"hotlist_recency_secs = {args.index_hotlist_recency_secs}")
        if args.index_hotlist_bloom_filter_recency_hours:
            lines.append(f"hotlist_bloom_filter_recency_hours = {args.index_hotlist_bloom_filter_recency_hours}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_retention_indexes(args: argparse.Namespace) -> str:
    lines = ["# Rendered retention overlay. Review before applying."]
    settings = enterprise_retention_lines(args)
    if not settings:
        lines.append("# No Enterprise retention values supplied.")
    for index in target_indexes(args):
        lines.append(f"[{index}]")
        lines.extend(settings or ["# Add maxTotalDataSizeMB and/or frozenTimePeriodInSecs before apply."])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_disable_indexes(args: argparse.Namespace) -> str:
    lines = ["# Rendered disabled index overlay. Review before applying."]
    for index in target_indexes(args):
        lines.extend([f"[{index}]", "disabled = 1", ""])
    return "\n".join(lines).rstrip() + "\n"


def render_server(args: argparse.Namespace) -> str:
    lines = ["# Rendered by splunk-index-lifecycle-smartstore-setup. Review before applying."]
    if bool_value(args.clean_remote_storage_by_default):
        lines.extend(["[general]", "cleanRemoteStorageByDefault = true", ""])
    cache_lines = []
    if args.eviction_policy:
        cache_lines.append(f"eviction_policy = {args.eviction_policy}")
    if args.cache_size_mb:
        cache_lines.append(f"max_cache_size = {args.cache_size_mb}")
    if args.eviction_padding_mb:
        cache_lines.append(f"eviction_padding = {args.eviction_padding_mb}")
    if args.hotlist_recency_secs:
        cache_lines.append(f"hotlist_recency_secs = {args.hotlist_recency_secs}")
    if args.hotlist_bloom_filter_recency_hours:
        cache_lines.append(f"hotlist_bloom_filter_recency_hours = {args.hotlist_bloom_filter_recency_hours}")
    if cache_lines:
        lines.append("[cachemanager]")
        lines.extend(cache_lines)
        lines.append("")
    if len(lines) == 1:
        lines.append("# No server.conf SmartStore cache-manager settings requested.")
    return "\n".join(lines).rstrip() + "\n"


def render_limits(args: argparse.Namespace) -> str:
    remote_storage_lines = []
    if args.bucket_localize_acquire_lock_timeout_sec:
        remote_storage_lines.append(f"bucket_localize_acquire_lock_timeout_sec = {args.bucket_localize_acquire_lock_timeout_sec}")
    if args.bucket_localize_connect_timeout_max_retries:
        remote_storage_lines.append(f"bucket_localize_connect_timeout_max_retries = {args.bucket_localize_connect_timeout_max_retries}")
    if args.bucket_localize_max_timeout_sec:
        remote_storage_lines.append(f"bucket_localize_max_timeout_sec = {args.bucket_localize_max_timeout_sec}")
    if not remote_storage_lines:
        return "\n".join(
            [
                "# Rendered by splunk-index-lifecycle-smartstore-setup. Review before applying.",
                "# No limits.conf remote_storage settings requested.",
                "",
            ]
        )
    return "\n".join(
        [
            "# Rendered by splunk-index-lifecycle-smartstore-setup. Review before applying.",
            "# Low-level remote-storage localization settings; change only with operational need.",
            "[remote_storage]",
            *remote_storage_lines,
            "",
        ]
    )


def render_collection_searches(args: argparse.Namespace) -> str:
    title_clause = index_search_clause(args, "title")
    index_clause = index_search_clause(args, "index")
    title_filter = f" | search {title_clause}" if title_clause else ""
    event_filter = f"search ({index_clause})" if index_clause else "search index=*"
    return "\n".join(
        [
            "# Splunk index lifecycle evidence collection searches",
            "# Run with a read-only user and summarize evidence into --evidence-file.",
            "",
            "## Index inventory, size, retention, and disabled state",
            f"| rest splunk_server=local count=0 /services/data/indexes{title_filter} | table title disabled datatype totalEventCount currentDBSizeMB maxTotalDataSizeMB maxGlobalDataSizeMB maxGlobalRawDataSizeMB frozenTimePeriodInSecs searchableDays splunkArchivalRetentionDays homePath coldPath thawedPath splunk_server",
            "",
            "## Latest event by index",
            f"{event_filter} earliest=-90d latest=now | stats count latest(_time) as latest_event earliest(_time) as earliest_event by index",
            "",
            "## Ingest throughput and stopped-ingest evidence",
            'index=_internal source=*metrics.log* group=per_index_thruput earliest=-7d latest=now | stats sum(kb) as kb latest(_time) as latest by series host',
            "",
            "## HEC token targets",
            "| rest splunk_server=local count=0 /servicesNS/nobody/splunk_httpinput/data/inputs/http | table title disabled index indexes sourcetype useACK eai:acl.app",
            "",
            "## Saved searches, alerts, dashboards, and macros that reference target indexes",
            '| rest splunk_server=local count=0 /servicesNS/-/-/saved/searches | table title disabled is_scheduled search eai:acl.app eai:acl.owner eai:acl.sharing',
            '| rest splunk_server=local count=0 /servicesNS/-/-/data/ui/views | table title label isVisible eai:acl.app eai:acl.sharing eai:data',
            "| rest splunk_server=local count=0 /servicesNS/-/-/admin/macros | table title definition args iseval eai:acl.app eai:acl.sharing",
            "",
            "## Role default indexes",
            "| rest splunk_server=local count=0 /services/authorization/roles | table title srchIndexesDefault srchIndexesAllowed imported_roles",
            "",
            "## ES, ITSI, ARI, CIM readiness hints",
            "| rest splunk_server=local count=0 /services/data/models | table title acceleration.* constraints tags_whitelist eai:acl.app",
            "search (index=notable OR index=risk OR index=itsi_summary OR index=itsi_summary_metrics OR index=ari_* ) earliest=-24h latest=now | stats count latest(_time) as latest by index sourcetype",
            "",
        ]
    )


def render_collect_evidence(args: argparse.Namespace) -> str:
    session_key_file = shell_quote(str(Path(args.session_key_file).expanduser())) if args.session_key_file else "''"
    splunk_uri = shell_quote(args.splunk_uri.rstrip("/"))
    return make_script(
        f"""session_key_file={session_key_file}
splunk_uri={splunk_uri}
[[ -s "${{session_key_file}}" ]] || {{ echo "ERROR: session key file missing or empty: ${{session_key_file}}" >&2; exit 1; }}
curl_config="$(mktemp)"
out="live-index-lifecycle-evidence.jsonl"
trap 'rm -f "${{curl_config}}"' EXIT
printf 'header = "Authorization: Splunk %s"\\n' "$(cat "${{session_key_file}}")" > "${{curl_config}}"
: > "${{out}}"
python3 - "${{splunk_uri}}" "${{curl_config}}" "${{out}}" <<'PY'
import json
import subprocess
import sys

splunk_uri, curl_config, out_path = sys.argv[1:4]
searches = []
current_title = "untitled"
for raw in open("collection-searches.spl", encoding="utf-8"):
    line = raw.strip()
    if not line:
        continue
    if line.startswith("## "):
        current_title = line[3:]
        continue
    if line.startswith("#"):
        continue
    searches.append((current_title, line))

url = f"{{splunk_uri}}/services/search/v2/jobs/export"
with open(out_path, "a", encoding="utf-8") as out:
    for title, search in searches:
        print(f"POST {{url}} :: {{title}}")
        result = subprocess.run(
            [
                "curl",
                "-sS",
                "-X",
                "POST",
                url,
                "-K",
                curl_config,
                "--data-urlencode",
                f"search={{search}}",
                "-d",
                "output_mode=json",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        out.write(json.dumps({{"title": title, "search": search, "returncode": result.returncode}}) + "\\n")
        for row in result.stdout.splitlines():
            out.write(row + "\\n")
        if result.returncode != 0:
            out.write(json.dumps({{"title": title, "stderr": result.stderr}}) + "\\n")
            raise SystemExit(result.stderr or f"search export failed for {{title}}")
PY
echo "Wrote ${{out}}"
"""
    )


def lifecycle_report_payload(args: argparse.Namespace, evidence: dict[str, Any], evidence_status: dict[str, Any]) -> dict[str, Any]:
    indexes = target_indexes(args)
    findings = dependency_findings(args, evidence)
    handoffs = []
    if args.operation == "archive" and args.platform == "cloud":
        handoffs.append("splunk-ddaa-archive")
    if args.operation in {"inventory", "retention", "delete-index", "disable-index"}:
        handoffs.append("splunk-data-source-readiness-doctor")
    if args.platform == "cloud" and args.operation in {"retention", "delete-index"}:
        handoffs.append("splunk-cloud-acs-admin-setup")
    return {
        "target": "index-lifecycle",
        "platform": args.platform,
        "deployment": args.deployment,
        "operation": args.operation,
        "indexes": "all" if not indexes and args.indexes.strip().lower() == "all" else indexes,
        "evidence": evidence_status,
        "destructive": args.operation in DESTRUCTIVE_OPERATIONS,
        "disruptive": args.operation in DISRUPTIVE_OPERATIONS,
        "dependency_findings": findings,
        "handoffs": handoffs,
        "safety": {
            "delete_requires_owner_approval_file": True,
            "delete_requires_backup_evidence_file": True,
            "delete_requires_evidence_file": True,
            "delete_requires_accept_flag": True,
            "delete_requires_confirm_token": "DELETE_INDEX:<index>",
            "internal_indexes_hard_blocked": True,
            "cluster_clean_data_hard_blocked": True,
        },
    }


def dependency_findings(args: argparse.Namespace, evidence: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for index in target_indexes(args):
        reason = protected_index_reason(index, evidence)
        record = evidence_index_record(evidence, index)
        dependencies = record.get("dependencies") if isinstance(record.get("dependencies"), list) else []
        safe = evidence_marks_safe_to_delete(index, evidence)
        if reason:
            status = "blocked"
        elif safe:
            status = "safe_to_delete_candidate"
        elif record:
            status = "needs_review"
        else:
            status = "unknown_no_evidence"
        findings.append(
            {
                "index": index,
                "status": status,
                "protected_reason": reason,
                "safe_to_delete": safe,
                "dependencies": dependencies,
                "evidence_keys": sorted(record.keys()),
            }
        )
    return findings


def render_lifecycle_report(args: argparse.Namespace, payload: dict[str, Any]) -> str:
    indexes = payload["indexes"]
    index_text = indexes if isinstance(indexes, str) else ", ".join(indexes)
    lines = [
        "# Splunk Index Lifecycle Report",
        "",
        f"- Platform: `{args.platform}`",
        f"- Deployment: `{args.deployment}`",
        f"- Operation: `{args.operation}`",
        f"- Indexes: `{index_text or 'none'}`",
        f"- Evidence loaded: `{payload['evidence'].get('loaded', False)}`",
        "",
        "## Decision Notes",
        "",
        "- Render evidence before applying retention, disable, delete, clean, archive, or restore changes.",
        "- Use `collection-searches.spl` to prove index usage, ingest state, retention, and dependency status.",
        "- Route downstream consumer proof to `splunk-data-source-readiness-doctor` when dashboards, ES, ITSI, ARI, or CIM content may depend on the index.",
    ]
    if args.platform == "cloud":
        lines.append("- Cloud retention/delete apply uses ACS token files only; DDAA archive/restore stays delegated or UI-bound.")
    else:
        lines.append("- Enterprise retention and SmartStore changes render bundle/app overlays for review before apply.")
    return "\n".join(lines).rstrip() + "\n"


def render_dependency_report(findings: list[dict[str, Any]]) -> str:
    lines = ["# Splunk Index Dependency Report", ""]
    if not findings:
        lines.append("No explicit index list was supplied; run inventory collection first.")
    for finding in findings:
        lines.extend(
            [
                f"## {finding['index']}",
                "",
                f"- Status: `{finding['status']}`",
                f"- Safe-to-delete evidence: `{finding['safe_to_delete']}`",
                f"- Protected reason: `{finding['protected_reason'] or 'none'}`",
                f"- Dependency count: `{len(finding['dependencies'])}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_retention_change_plan(args: argparse.Namespace) -> str:
    lines = ["# Retention Change Plan", ""]
    if args.platform == "cloud":
        lines.extend(
            [
                "Splunk Cloud retention changes are rendered as ACS payloads.",
                "",
                f"- Stack: `{args.stack or '(required for apply)'}`",
                f"- searchableDays: `{args.searchable_days or '(unchanged/not supplied)'}`",
                f"- maxDataSizeMB: `{args.max_data_size_mb or '(unchanged/not supplied)'}`",
                f"- splunkArchivalRetentionDays: `{args.archival_retention_days or '(delegated to DDAA when archive is requested)'}`",
            ]
        )
    else:
        lines.extend(
            [
                "Self-managed Enterprise retention changes are rendered in `retention-indexes.conf.template`.",
                "",
                f"- maxTotalDataSizeMB: `{args.max_total_data_size_mb or '(unchanged/not supplied)'}`",
                f"- frozenTimePeriodInSecs: `{args.frozen_time_period_in_secs or '(unchanged/not supplied)'}`",
                f"- Deployment path: `{'cluster-manager bundle' if args.deployment == 'cluster' else 'standalone app overlay'}`",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_destructive_action_plan(args: argparse.Namespace, findings: list[dict[str, Any]]) -> str:
    lines = [
        "# Destructive Action Plan",
        "",
        f"- Operation: `{args.operation}`",
        f"- Platform: `{args.platform}`",
        "",
        "Required gates before destructive apply:",
        "",
        "- `--accept-destructive-index-delete`",
        "- `--owner-approval-file` exists and is non-empty",
        "- `--backup-evidence-file` exists and is non-empty",
        "- `--evidence-file` exists and marks each target index safe to delete",
        "- `--confirm-token DELETE_INDEX:<index>` for every target index",
        "",
    ]
    if args.operation == "disable-index":
        lines[5:10] = [
            "Required gates before disable apply:",
            "",
            "- `--owner-approval-file` exists and is non-empty",
            "- `--evidence-file` exists and has been reviewed",
        ]
    if not findings:
        lines.append("No explicit target index list was supplied.")
    for finding in findings:
        lines.append(f"- `{finding['index']}`: {finding['status']} {finding['protected_reason']}".rstrip())
    return "\n".join(lines).rstrip() + "\n"


def render_acs_payload(args: argparse.Namespace) -> str:
    payloads = []
    for index in target_indexes(args):
        payload: dict[str, Any] = {"name": index, "datatype": args.datatype}
        if args.searchable_days:
            payload["searchableDays"] = int(args.searchable_days)
        if args.max_data_size_mb:
            payload["maxDataSizeMB"] = int(args.max_data_size_mb)
        if args.archival_retention_days:
            payload["splunkArchivalRetentionDays"] = int(args.archival_retention_days)
        payloads.append(payload)
    return json.dumps({"operation": args.operation, "indexes": payloads}, indent=2, sort_keys=True) + "\n"


def render_readme(args: argparse.Namespace) -> str:
    return f"""# Splunk Index Lifecycle / SmartStore Rendered Assets

Platform: `{args.platform}`
Deployment: `{args.deployment}`
Operation: `{args.operation}`
Scope: `{args.scope}`
Remote provider: `{args.remote_provider}`
Volume: `{args.volume_name}`
Remote path: `{args.remote_path or '(not used)'}`

Review these lifecycle files before any apply:

- `index-lifecycle-report.md`
- `index-dependency-report.md`
- `collection-searches.spl`
- `retention-change-plan.md`
- `destructive-action-plan.md`

SmartStore renders also include:

- `indexes.conf.template`
- `server.conf`
- `limits.conf`
- `preflight.sh`
- `apply-cluster-manager.sh`
- `apply-standalone-indexer.sh`
- `status.sh`

Destructive operations fail closed unless approval, backup, dependency evidence,
the explicit accept flag, and exact confirmation tokens are provided.
"""


def render_preflight(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    return make_script(
        f"""splunk_home={splunk_home}
test -x "${{splunk_home}}/bin/splunk"
"${{splunk_home}}/bin/splunk" btool indexes list --debug >/dev/null || true
"${{splunk_home}}/bin/splunk" btool server list cachemanager --debug >/dev/null || true
"${{splunk_home}}/bin/splunk" btool limits list remote_storage --debug >/dev/null || true
"""
    )


def substitution_python() -> str:
    return r"""from pathlib import Path
import sys

target = Path(sys.argv[1])
template = Path(sys.argv[2]).read_text(encoding="utf-8")
access_key_file = sys.argv[3]
secret_key_file = sys.argv[4]
if "__SMARTSTORE_S3_ACCESS_KEY_FROM_FILE__" in template:
    access_key = Path(access_key_file).read_text(encoding="utf-8").strip()
    secret_key = Path(secret_key_file).read_text(encoding="utf-8").strip()
    if not access_key or not secret_key:
        raise SystemExit("ERROR: S3 credential files must not be empty.")
    template = template.replace("__SMARTSTORE_S3_ACCESS_KEY_FROM_FILE__", access_key)
    template = template.replace("__SMARTSTORE_S3_SECRET_KEY_FROM_FILE__", secret_key)
target.write_text(template, encoding="utf-8")
"""


def render_apply(args: argparse.Namespace, cluster: bool) -> str:
    splunk_home = shell_quote(args.splunk_home)
    app_name = shell_quote(args.app_name)
    access_key_file = shell_quote(str(Path(args.s3_access_key_file).expanduser())) if args.s3_access_key_file else "''"
    secret_key_file = shell_quote(str(Path(args.s3_secret_key_file).expanduser())) if args.s3_secret_key_file else "''"
    base = "${splunk_home}/etc/manager-apps" if cluster else "${splunk_home}/etc/apps"
    bundle_block = (
        '"${splunk_home}/bin/splunk" apply cluster-bundle --answer-yes\n'
        if cluster and bool_value(args.apply_cluster_bundle)
        else 'echo "Cluster bundle apply skipped. Run splunk apply cluster-bundle --answer-yes after review."\n'
    )
    restart_block = (
        '"${splunk_home}/bin/splunk" restart\n'
        if not cluster and bool_value(args.restart_splunk)
        else 'echo "Restart skipped. Restart the standalone indexer after review."\n'
    )
    final_block = bundle_block if cluster else restart_block
    return make_script(
        f"""splunk_home={splunk_home}
app_name={app_name}
access_key_file={access_key_file}
secret_key_file={secret_key_file}

if grep -q "__SMARTSTORE_S3_ACCESS_KEY_FROM_FILE__" indexes.conf.template; then
  [[ -s "${{access_key_file}}" ]] || {{ echo "ERROR: S3 access key file is missing or empty: ${{access_key_file}}" >&2; exit 1; }}
  [[ -s "${{secret_key_file}}" ]] || {{ echo "ERROR: S3 secret key file is missing or empty: ${{secret_key_file}}" >&2; exit 1; }}
fi

target_dir="{base}/${{app_name}}/local"
mkdir -p "${{target_dir}}"
python3 - "${{target_dir}}/indexes.conf" indexes.conf.template "${{access_key_file}}" "${{secret_key_file}}" <<'PY'
{substitution_python()}
PY
chmod 600 "${{target_dir}}/indexes.conf"
cp server.conf "${{target_dir}}/server.conf"
cp limits.conf "${{target_dir}}/limits.conf"
"${{splunk_home}}/bin/splunk" btool indexes list --debug >/dev/null
{final_block}"""
    )


def render_status(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    volume = shell_quote(f"volume:{args.volume_name}")
    return make_script(
        f"""splunk_home={splunk_home}
"${{splunk_home}}/bin/splunk" btool indexes list {volume} --debug 2>/dev/null | grep -v -E 'remote\\.(s3|gs|azure)\\.(access|secret|key)' || true
"${{splunk_home}}/bin/splunk" btool indexes list --debug 2>/dev/null | grep -E 'frozenTimePeriodInSecs|maxTotalDataSizeMB|maxGlobal(Data|Raw)SizeMB|disabled' || true
"${{splunk_home}}/bin/splunk" btool server list cachemanager --debug 2>/dev/null || true
"${{splunk_home}}/bin/splunk" btool limits list remote_storage --debug 2>/dev/null || true
"${{splunk_home}}/bin/splunk" show cluster-bundle-status 2>/dev/null || true
"""
    )


def render_apply_retention_enterprise(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    app_name = shell_quote(args.app_name)
    base = "${splunk_home}/etc/manager-apps" if args.deployment == "cluster" else "${splunk_home}/etc/apps"
    final_block = (
        '"${splunk_home}/bin/splunk" apply cluster-bundle --answer-yes\n'
        if args.deployment == "cluster" and bool_value(args.apply_cluster_bundle)
        else (
            'echo "Cluster bundle apply skipped. Run splunk apply cluster-bundle --answer-yes after review."\n'
            if args.deployment == "cluster"
            else (
                '"${splunk_home}/bin/splunk" restart\n'
                if bool_value(args.restart_splunk)
                else 'echo "Restart skipped. Restart the standalone indexer after review."\n'
            )
        )
    )
    return make_script(
        f"""splunk_home={splunk_home}
app_name={app_name}
target_dir="{base}/${{app_name}}/local"
mkdir -p "${{target_dir}}"
cp retention-indexes.conf.template "${{target_dir}}/indexes.conf"
"${{splunk_home}}/bin/splunk" btool indexes list --debug >/dev/null
{final_block}"""
    )


def render_apply_retention_cloud(args: argparse.Namespace) -> str:
    token_file = shell_quote(str(Path(args.acs_token_file).expanduser()))
    base = shell_quote(args.acs_base.rstrip("/"))
    stack = shell_quote(args.stack)
    return make_script(
        f"""token_file={token_file}
acs_base={base}
stack={stack}
[[ -n "${{stack}}" ]] || {{ echo "ERROR: --stack is required for Splunk Cloud retention apply." >&2; exit 1; }}
[[ -s "${{token_file}}" ]] || {{ echo "ERROR: ACS token file missing or empty: ${{token_file}}" >&2; exit 1; }}
python3 - <<'PY'
import json
payload=json.load(open("acs-index-update-payload.json", encoding="utf-8"))
if not payload.get("indexes"):
    raise SystemExit("ERROR: no index payloads were rendered.")
PY
curl_config="$(mktemp)"
trap 'rm -f "${{curl_config}}" /tmp/index_lifecycle_acs_response.json' EXIT
printf 'header = "Authorization: Bearer %s"\\n' "$(cat "${{token_file}}")" > "${{curl_config}}"
python3 - "${{acs_base}}" "${{stack}}" "${{curl_config}}" <<'PY'
import json, subprocess, sys, tempfile
acs_base, stack, curl_config = sys.argv[1:4]
payload=json.load(open("acs-index-update-payload.json", encoding="utf-8"))
for item in payload["indexes"]:
    name=item["name"]
    body={{k:v for k,v in item.items() if k not in {{"name","datatype"}}}}
    if not body:
        print(f"Skip {{name}}: no mutable ACS fields supplied")
        continue
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as fh:
        json.dump(body, fh)
        path=fh.name
    url=f"{{acs_base.rstrip('/')}}/{{stack}}/adminconfig/v2/indexes/{{name}}"
    print(f"PATCH {{url}}")
    result=subprocess.run([
        "curl","-sS","-o","/tmp/index_lifecycle_acs_response.json","-w","%{{http_code}}",
        "-X","PATCH",url,"-K",curl_config,"-H","Content-Type: application/json","--data",f"@{{path}}"
    ], text=True, capture_output=True, check=False)
    print("HTTP", result.stdout.strip())
    if result.returncode != 0 or not result.stdout.startswith("2"):
        raise SystemExit(result.stderr or "ACS retention request failed")
PY
"""
    )


def render_disable_script(args: argparse.Namespace) -> str:
    indexes = ",".join(target_indexes(args))
    splunk_home = shell_quote(args.splunk_home)
    app_name = shell_quote(args.app_name)
    owner_file = shell_quote(str(Path(args.owner_approval_file).expanduser())) if args.owner_approval_file else "''"
    evidence_file = shell_quote(str(Path(args.evidence_file).expanduser())) if args.evidence_file else "''"
    if args.platform == "cloud":
        return make_script(
            """cat <<'EOF'
Splunk Cloud index disable is not exposed as a safe generic apply path here.
Use ACS retention/delete or Splunk Web/support based on your Cloud stack policy.
EOF
exit 1
"""
        )
    if args.deployment == "cluster":
        final_block = (
            '"${splunk_home}/bin/splunk" apply cluster-bundle --answer-yes\n'
            if bool_value(args.apply_cluster_bundle)
            else 'echo "Cluster bundle apply skipped. Run splunk apply cluster-bundle --answer-yes after review."\n'
        )
        return make_script(
            f"""splunk_home={splunk_home}
app_name={app_name}
owner_approval_file={owner_file}
evidence_file={evidence_file}
[[ -s "${{owner_approval_file}}" ]] || {{ echo "ERROR: owner approval file missing or empty." >&2; exit 1; }}
[[ -s "${{evidence_file}}" ]] || {{ echo "ERROR: evidence file missing or empty." >&2; exit 1; }}
target_dir="${{splunk_home}}/etc/manager-apps/${{app_name}}/local"
mkdir -p "${{target_dir}}"
cp indexes-disable.conf.template "${{target_dir}}/indexes.conf"
{final_block}"""
        )
    return make_script(
        f"""splunk_home={splunk_home}
owner_approval_file={owner_file}
evidence_file={evidence_file}
indexes_csv={shell_quote(indexes)}
[[ -s "${{owner_approval_file}}" ]] || {{ echo "ERROR: owner approval file missing or empty." >&2; exit 1; }}
[[ -s "${{evidence_file}}" ]] || {{ echo "ERROR: evidence file missing or empty." >&2; exit 1; }}
IFS=',' read -r -a indexes <<< "${{indexes_csv}}"
for idx in "${{indexes[@]}}"; do
  [[ -n "${{idx}}" ]] || continue
  "${{splunk_home}}/bin/splunk" disable index "${{idx}}"
done
"""
    )


def destructive_gate_python() -> str:
    protected_defaults = sorted(PROTECTED_DEFAULT_INDEXES)
    sensitive = sorted(SENSITIVE_INDEXES)
    return f"""import json, sys
from pathlib import Path

evidence_path, indexes_csv, confirm_tokens_csv = sys.argv[1:4]
indexes = [item for item in indexes_csv.split(",") if item]
tokens = set(item for item in confirm_tokens_csv.split(",") if item)
protected_defaults = set({protected_defaults!r})
sensitive = set({sensitive!r})

try:
    evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
except Exception as exc:
    raise SystemExit(f"ERROR: cannot load destructive evidence: {{exc}}")
if not isinstance(evidence, dict):
    raise SystemExit("ERROR: destructive evidence must be a JSON object.")

def list_at(path):
    node = evidence
    for part in path.split("."):
        if not isinstance(node, dict):
            return set()
        node = node.get(part)
    if isinstance(node, list):
        return set(str(item) for item in node)
    if isinstance(node, str):
        return {{node}}
    return set()

nonprod = list_at("non_production_test_indexes") | list_at("indexes.non_production_test") | list_at("destructive_actions.non_production_test_indexes")
safe = list_at("safe_to_delete_indexes") | list_at("destructive_actions.safe_to_delete_indexes")
sensitive_approved = list_at("sensitive_delete_approved_indexes") | list_at("destructive_actions.sensitive_delete_approved_indexes")

def record_for(index):
    candidates = []
    for path in (("destructive_actions","indexes"), ("indexes","by_name"), ("indexes","classification"), ("indexes","classifications")):
        node = evidence
        for part in path:
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, dict):
            candidates.append(node.get(index))
    node = evidence.get("indexes")
    if isinstance(node, dict):
        direct = node.get(index)
        if isinstance(direct, dict):
            candidates.append(direct)
        inventory = node.get("inventory")
        if isinstance(inventory, list):
            for item in inventory:
                if isinstance(item, dict) and item.get("name") == index:
                    candidates.append(item)
    for item in candidates:
        if isinstance(item, dict):
            return item
    return {{}}

for index in indexes:
    expected = f"DELETE_INDEX:{{index}}"
    if expected not in tokens:
        raise SystemExit(f"ERROR: missing exact confirmation token {{expected}}")
    if index.startswith("_"):
        raise SystemExit(f"ERROR: protected index {{index}}: internal indexes beginning with '_' are hard-blocked")
    rec = record_for(index)
    if index in protected_defaults and not (index in nonprod or rec.get("non_production_test") is True or rec.get("classification") == "non-production-test"):
        raise SystemExit(f"ERROR: protected index {{index}}: default index requires non-production test evidence")
    if index in sensitive and index not in sensitive_approved:
        raise SystemExit(f"ERROR: protected index {{index}}: ES/ITSI/ARI-sensitive index requires explicit sensitive approval evidence")
    safe_by_record = rec.get("safe_to_delete") is True and rec.get("dependencies_clear", True) is not False
    if index not in safe and not safe_by_record:
        raise SystemExit(f"ERROR: evidence does not mark {{index}} safe_to_delete with dependencies_clear")
print("Destructive gates passed for: " + ", ".join(indexes))
"""


def render_delete_script(args: argparse.Namespace) -> str:
    indexes = ",".join(target_indexes(args))
    evidence_file = shell_quote(str(Path(args.evidence_file).expanduser())) if args.evidence_file else "''"
    owner_file = shell_quote(str(Path(args.owner_approval_file).expanduser())) if args.owner_approval_file else "''"
    backup_file = shell_quote(str(Path(args.backup_evidence_file).expanduser())) if args.backup_evidence_file else "''"
    confirm_tokens = shell_quote(",".join(args.confirm_token))
    accept = "true" if args.accept_destructive_index_delete else "false"
    gate = f"""accept_destructive={accept}
evidence_file={evidence_file}
owner_approval_file={owner_file}
backup_evidence_file={backup_file}
indexes_csv={shell_quote(indexes)}
confirm_tokens_csv={confirm_tokens}
[[ "${{accept_destructive}}" == "true" ]] || {{ echo "ERROR: --accept-destructive-index-delete is required." >&2; exit 1; }}
[[ -n "${{indexes_csv}}" ]] || {{ echo "ERROR: explicit --indexes are required." >&2; exit 1; }}
[[ -s "${{owner_approval_file}}" ]] || {{ echo "ERROR: owner approval file missing or empty." >&2; exit 1; }}
[[ -s "${{backup_evidence_file}}" ]] || {{ echo "ERROR: backup evidence file missing or empty." >&2; exit 1; }}
[[ -s "${{evidence_file}}" ]] || {{ echo "ERROR: evidence file missing or empty." >&2; exit 1; }}
python3 - "${{evidence_file}}" "${{indexes_csv}}" "${{confirm_tokens_csv}}" <<'PY'
{destructive_gate_python()}
PY
"""
    if args.platform == "cloud":
        token_file = shell_quote(str(Path(args.acs_token_file).expanduser()))
        base = shell_quote(args.acs_base.rstrip("/"))
        stack = shell_quote(args.stack)
        return make_script(
            gate
            + f"""token_file={token_file}
acs_base={base}
stack={stack}
[[ -n "${{stack}}" ]] || {{ echo "ERROR: --stack is required for Splunk Cloud delete apply." >&2; exit 1; }}
[[ -s "${{token_file}}" ]] || {{ echo "ERROR: ACS token file missing or empty: ${{token_file}}" >&2; exit 1; }}
curl_config="$(mktemp)"
trap 'rm -f "${{curl_config}}" /tmp/index_lifecycle_delete_response.json' EXIT
printf 'header = "Authorization: Bearer %s"\\n' "$(cat "${{token_file}}")" > "${{curl_config}}"
IFS=',' read -r -a indexes <<< "${{indexes_csv}}"
for idx in "${{indexes[@]}}"; do
  url="${{acs_base}}/${{stack}}/adminconfig/v2/indexes/${{idx}}"
  echo "DELETE ${{url}}"
  http_code=$(curl -sS -o /tmp/index_lifecycle_delete_response.json -w '%{{http_code}}' -X DELETE "${{url}}" -K "${{curl_config}}") || {{ echo "ERROR: ACS delete request failed." >&2; exit 1; }}
  echo "HTTP ${{http_code}}"
  [[ "${{http_code}}" =~ ^2 ]] || {{ cat /tmp/index_lifecycle_delete_response.json >&2 || true; exit 1; }}
done
"""
        )
    splunk_home = shell_quote(args.splunk_home)
    if args.deployment == "cluster":
        app_name = shell_quote(args.app_name)
        final_block = (
            '"${splunk_home}/bin/splunk" apply cluster-bundle --answer-yes\n'
            if bool_value(args.apply_cluster_bundle)
            else 'echo "Cluster bundle apply skipped. Run splunk apply cluster-bundle --answer-yes after review."\n'
        )
        return make_script(
            gate
            + f"""splunk_home={splunk_home}
app_name={app_name}
target_conf="${{splunk_home}}/etc/manager-apps/${{app_name}}/local/indexes.conf"
[[ -f "${{target_conf}}" ]] || {{ echo "ERROR: manager app indexes.conf not found: ${{target_conf}}" >&2; exit 1; }}
python3 - "${{target_conf}}" "${{indexes_csv}}" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
targets = set(item for item in sys.argv[2].split(",") if item)
lines = path.read_text(encoding="utf-8").splitlines()
out = []
skip = False
for line in lines:
    stripped = line.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        stanza = stripped[1:-1]
        skip = stanza in targets
    if not skip:
        out.append(line)
path.write_text("\\n".join(out).rstrip() + "\\n", encoding="utf-8")
PY
{final_block}cat peer-cleanup-runbook.md
"""
        )
    return make_script(
        gate
        + f"""splunk_home={splunk_home}
IFS=',' read -r -a indexes <<< "${{indexes_csv}}"
for idx in "${{indexes[@]}}"; do
  "${{splunk_home}}/bin/splunk" remove index "${{idx}}"
done
"""
    )


def render_clean_data_script(args: argparse.Namespace) -> str:
    indexes = ",".join(target_indexes(args))
    splunk_home = shell_quote(args.splunk_home)
    evidence_file = shell_quote(str(Path(args.evidence_file).expanduser())) if args.evidence_file else "''"
    owner_file = shell_quote(str(Path(args.owner_approval_file).expanduser())) if args.owner_approval_file else "''"
    backup_file = shell_quote(str(Path(args.backup_evidence_file).expanduser())) if args.backup_evidence_file else "''"
    confirm_tokens = shell_quote(",".join(args.confirm_token))
    accept = "true" if args.accept_destructive_index_delete else "false"
    return make_script(
        f"""accept_destructive={accept}
splunk_home={splunk_home}
evidence_file={evidence_file}
owner_approval_file={owner_file}
backup_evidence_file={backup_file}
indexes_csv={shell_quote(indexes)}
confirm_tokens_csv={confirm_tokens}
[[ "${{accept_destructive}}" == "true" ]] || {{ echo "ERROR: --accept-destructive-index-delete is required." >&2; exit 1; }}
[[ -s "${{owner_approval_file}}" ]] || {{ echo "ERROR: owner approval file missing or empty." >&2; exit 1; }}
[[ -s "${{backup_evidence_file}}" ]] || {{ echo "ERROR: backup evidence file missing or empty." >&2; exit 1; }}
[[ -s "${{evidence_file}}" ]] || {{ echo "ERROR: evidence file missing or empty." >&2; exit 1; }}
python3 - "${{evidence_file}}" "${{indexes_csv}}" "${{confirm_tokens_csv}}" <<'PY'
{destructive_gate_python()}
PY
IFS=',' read -r -a indexes <<< "${{indexes_csv}}"
for idx in "${{indexes[@]}}"; do
  "${{splunk_home}}/bin/splunk" clean eventdata -index "${{idx}}" -f
done
"""
    )


def render_archive_handoff(args: argparse.Namespace) -> str:
    indexes = target_indexes(args)
    first_index = indexes[0] if indexes else "<index>"
    if args.platform == "cloud":
        return make_script(
            f"""cat <<'EOF'
Splunk Cloud archive lifecycle is delegated to splunk-ddaa-archive.

Suggested command:
bash skills/splunk-ddaa-archive/scripts/setup.sh \\
  --stack {args.stack or '<stack>'} \\
  --index {first_index} \\
  --searchable-days {args.searchable_days or '<searchable-days>'} \\
  --archival-retention-days {args.archival_retention_days or '<total-retention-days>'} \\
  --token-file {args.acs_token_file}

Restore remains a Splunk Web workflow from Settings > Indexes.
EOF
"""
        )
    return make_script(
        """cat <<'EOF'
Self-managed archive handoff:

- Review frozenTimePeriodInSecs and cold-to-frozen archive requirements.
- Configure coldToFrozenScript or frozen archive path only after backup and restore tests.
- Use retention-indexes.conf.template for the searchable retention overlay.
EOF
"""
    )


def render_restore_handoff(args: argparse.Namespace) -> tuple[str, str]:
    index_text = ",".join(target_indexes(args)) or "<index>"
    if args.platform == "cloud":
        md = f"""# Splunk Cloud Restore Handoff

Restore archived DDAA data from Splunk Web:

1. Go to Settings > Indexes.
2. Select `{index_text}`.
3. Choose the archived time range to restore.
4. Validate restored buckets with `| dbinspect index={index_text.split(',')[0]}`.

There is no public ACS restore endpoint in this workflow.
"""
    else:
        md = f"""# Splunk Enterprise Thaw Handoff

To restore frozen archived data for `{index_text}`, copy archived buckets into
the target index's `thawedPath`, rebuild if required, and validate with
`| dbinspect index={index_text.split(',')[0]}`.
"""
    script = make_script("cat restore-handoff.md\n")
    return md, script


def render_peer_cleanup_runbook(args: argparse.Namespace) -> str:
    return """# Peer Cleanup Runbook

After a cluster-manager bundle removes index stanzas, do not delete bucket
directories from peers until the cluster is healthy and owner approval confirms
the retention/delete decision. Capture `splunk show cluster-status`,
`dbinspect`, and filesystem backup evidence first.
"""


def render(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "smartstore"
    assets: list[str] = []
    evidence, evidence_status = load_evidence(args.evidence_file)
    payload = lifecycle_report_payload(args, evidence, evidence_status)
    findings = payload["dependency_findings"]
    restore_md, restore_script = render_restore_handoff(args)
    files = {
        "README.md": render_readme(args),
        "metadata.json": json.dumps(
            {
                "target": "index-lifecycle",
                "platform": args.platform,
                "deployment": args.deployment,
                "operation": args.operation,
                "scope": args.scope,
                "remote_provider": args.remote_provider,
                "volume_name": args.volume_name,
                "remote_path": args.remote_path,
                "indexes": "all" if args.indexes.strip().lower() == "all" else target_indexes(args),
                "s3_encryption": args.s3_encryption,
                "s3_access_key_file": args.s3_access_key_file,
                "s3_secret_key_file": args.s3_secret_key_file,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "indexes.conf.template": render_indexes(args) if args.operation == "smartstore" else "# SmartStore remote volume not requested for this operation.\n",
        "retention-indexes.conf.template": render_retention_indexes(args),
        "indexes-disable.conf.template": render_disable_indexes(args),
        "server.conf": render_server(args),
        "limits.conf": render_limits(args),
        "preflight.sh": render_preflight(args),
        "apply-cluster-manager.sh": render_apply(args, cluster=True),
        "apply-standalone-indexer.sh": render_apply(args, cluster=False),
        "status.sh": render_status(args),
        "index-lifecycle-report.md": render_lifecycle_report(args, payload),
        "index-lifecycle-report.json": json.dumps(payload, indent=2, sort_keys=True) + "\n",
        "index-dependency-report.md": render_dependency_report(findings),
        "index-dependency-report.json": json.dumps({"findings": findings}, indent=2, sort_keys=True) + "\n",
        "collection-searches.spl": render_collection_searches(args),
        "collect-evidence.sh": render_collect_evidence(args),
        "retention-change-plan.md": render_retention_change_plan(args),
        "destructive-action-plan.md": render_destructive_action_plan(args, findings),
        "acs-index-update-payload.json": render_acs_payload(args),
        "apply-retention-enterprise.sh": render_apply_retention_enterprise(args),
        "apply-retention-cloud.sh": render_apply_retention_cloud(args),
        "apply-disable-index.sh": render_disable_script(args),
        "apply-delete-index.sh": render_delete_script(args),
        "apply-clean-data.sh": render_clean_data_script(args),
        "archive-handoff.sh": render_archive_handoff(args),
        "restore-handoff.sh": restore_script,
        "restore-handoff.md": restore_md,
        "peer-cleanup-runbook.md": render_peer_cleanup_runbook(args),
    }
    if args.operation == "smartstore":
        apply_script = "./apply-cluster-manager.sh" if args.deployment == "cluster" else "./apply-standalone-indexer.sh"
    elif args.operation == "retention":
        apply_script = "./apply-retention-cloud.sh" if args.platform == "cloud" else "./apply-retention-enterprise.sh"
    elif args.operation == "archive":
        apply_script = "./archive-handoff.sh"
    elif args.operation == "disable-index":
        apply_script = "./apply-disable-index.sh"
    elif args.operation == "delete-index":
        apply_script = "./apply-delete-index.sh"
    elif args.operation == "clean-data":
        apply_script = "./apply-clean-data.sh"
    elif args.operation == "restore-handoff":
        apply_script = "./restore-handoff.sh"
    else:
        apply_script = "./status.sh"
    if not args.dry_run:
        clean_render_dir(render_dir)
        for rel, content in files.items():
            write_file(render_dir / rel, content, executable=rel.endswith(".sh"))
            assets.append(rel)
    return {
        "target": "index-lifecycle",
        "deployment": args.deployment,
        "platform": args.platform,
        "operation": args.operation,
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "assets": assets,
        "dry_run": args.dry_run,
        "commands": {
            "preflight": [["./preflight.sh"]],
            "apply": [[apply_script]],
            "status": [["./status.sh"]],
        },
    }


def main() -> int:
    args = parse_args()
    validate(args)
    payload = render(args)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.dry_run:
        print(f"Would render index lifecycle assets under {payload['render_dir']}")
    else:
        print(f"Rendered index lifecycle assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
