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
from urllib.parse import urlsplit


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


def validate_service_url(value: str, option: str, schemes: tuple[str, ...]) -> None:
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        die(f"{option} must be a valid URL: {exc}")
    if parsed.scheme not in schemes or not parsed.hostname:
        expected = " or ".join(f"{scheme}://" for scheme in schemes)
        die(f"{option} must be an absolute {expected} URL.")
    if parsed.username is not None or parsed.password is not None:
        die(f"{option} must not contain embedded credentials.")
    if parsed.query or parsed.fragment:
        die(f"{option} must not contain a query string or fragment.")


def validate(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", args.app_name or ""):
        die("--app-name must contain only letters, numbers, underscore, dot, colon, or hyphen.")
    if not re.fullmatch(r"[A-Za-z0-9_]+", args.volume_name or ""):
        die("--volume-name must contain only letters, numbers, and underscores.")
    validate_stack_name(args.stack)
    validate_service_url(args.acs_base, "--acs-base", ("https",))
    validate_service_url(args.splunk_uri, "--splunk-uri", ("https", "http"))

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

    if args.platform == "cloud" and args.operation == "smartstore":
        die("--operation smartstore is a self-managed Splunk Enterprise workflow; use the Cloud index/DDSS workflow for Splunk Cloud.")
    if args.operation == "clean-data" and (args.platform != "enterprise" or args.deployment != "standalone"):
        die("--operation clean-data is supported only for a standalone Splunk Enterprise indexer.")
    if args.operation == "retention":
        if args.platform == "enterprise" and not (args.max_total_data_size_mb or args.frozen_time_period_in_secs):
            die("Enterprise retention requires --max-total-data-size-mb and/or --frozen-time-period-in-secs.")
        if args.platform == "cloud" and not (
            args.searchable_days or args.max_data_size_mb or args.archival_retention_days
        ):
            die("Splunk Cloud retention requires --searchable-days, --max-data-size-mb, and/or --archival-retention-days.")

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
    return bool(record.get("safe_to_delete") is True and record.get("dependencies_clear") is True)


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
out="live-index-lifecycle-evidence.jsonl"
{secure_curl_context('session_key_file', 'Splunk')}
python3 - "${{splunk_uri}}" "${{curl_config}}" "${{out}}" <<'PY'
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

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

out = Path(out_path)
if out.is_symlink():
    raise SystemExit(f"ERROR: evidence output must not be a symlink: {{out}}")
flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
fd = os.open(out, flags, 0o600)
os.fchmod(fd, 0o600)

url = f"{{splunk_uri}}/services/search/v2/jobs/export"
with os.fdopen(fd, "w", encoding="utf-8") as output, tempfile.TemporaryDirectory(prefix="splunk-index-evidence-") as tmp_dir:
    for title, search in searches:
        print(f"POST {{url}} :: {{title}}")
        response_path = Path(tmp_dir) / "response.json"
        result = subprocess.run(
            [
                "curl",
                "-sS",
                "--proto",
                "=https,http",
                "-X",
                "POST",
                url,
                "-K",
                curl_config,
                "-o",
                str(response_path),
                "-w",
                "%{{http_code}}",
                "--data-urlencode",
                f"search={{search}}",
                "-d",
                "output_mode=json",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        status = result.stdout.strip()
        body = response_path.read_text(encoding="utf-8", errors="replace") if response_path.exists() else ""
        output.write(json.dumps({{"title": title, "search": search, "returncode": result.returncode, "http_status": status}}) + "\\n")
        if result.returncode != 0 or not re.fullmatch(r"2[0-9]{{2}}", status):
            output.write(json.dumps({{"title": title, "error": (result.stderr or body)[:2000]}}) + "\\n")
            output.flush()
            raise SystemExit(result.stderr or f"search export failed for {{title}} with HTTP {{status or 'unknown'}}")
        for row in body.splitlines():
            output.write(row + "\\n")
        output.flush()
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
    if args.platform == "cloud":
        if args.operation not in {"inventory", "retention", "delete-index"}:
            return make_script(
                f'''command -v python3 >/dev/null || {{ echo "ERROR: python3 is required." >&2; exit 1; }}
echo "HANDOFF: {args.operation} has no generic live ACS apply in this workflow; review the rendered runbook."
'''
            )
        token_file = shell_quote(str(Path(args.acs_token_file).expanduser()))
        stack = shell_quote(args.stack)
        payload_check = ""
        if args.operation == "retention":
            payload_check = '''python3 - <<'PY'
import json
from pathlib import Path

path = Path("acs-index-update-payload.json")
if path.is_symlink() or not path.is_file():
    raise SystemExit(f"ERROR: ACS payload must be a regular, non-symlink file: {path}")
payload = json.loads(path.read_text(encoding="utf-8"))
indexes = payload.get("indexes") if isinstance(payload, dict) else None
if not isinstance(indexes, list) or not indexes:
    raise SystemExit("ERROR: no index payloads were rendered.")
for item in indexes:
    if not isinstance(item, dict) or not item.get("name"):
        raise SystemExit("ERROR: ACS payload contains an invalid index record.")
    if not any(key in item for key in ("searchableDays", "maxDataSizeMB", "splunkArchivalRetentionDays")):
        raise SystemExit(f"ERROR: ACS payload for {item.get('name')} has no mutable fields.")
PY
'''
        return make_script(
            f'''token_file={token_file}
stack={stack}
[[ -n "${{stack}}" ]] || {{ echo "ERROR: --stack is required for this Splunk Cloud operation." >&2; exit 1; }}
{secure_curl_context('token_file', 'Bearer')}{payload_check}echo "Splunk Cloud preflight passed for stack ${{stack}}."
'''
        )
    splunk_home = shell_quote(args.splunk_home)
    return make_script(
        f"""splunk_home={splunk_home}
test -x "${{splunk_home}}/bin/splunk"
"${{splunk_home}}/bin/splunk" btool indexes list --debug >/dev/null
"${{splunk_home}}/bin/splunk" btool server list cachemanager --debug >/dev/null
"${{splunk_home}}/bin/splunk" btool limits list remote_storage --debug >/dev/null
"""
    )


def secure_install_python() -> str:
    return r"""from pathlib import Path
import os
import stat
import sys
import tempfile
import time

if (len(sys.argv) - 1) % 4:
    raise SystemExit("ERROR: secure installer received an invalid argument list.")

def regular_file(path_value, label, secret=False):
    path = Path(path_value)
    try:
        info = path.lstat()
    except OSError as exc:
        raise SystemExit(f"ERROR: cannot inspect {label} {path}: {exc}")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise SystemExit(f"ERROR: {label} must be a regular, non-symlink file: {path}")
    if secret:
        if info.st_uid != os.geteuid():
            raise SystemExit(f"ERROR: {label} must be owned by the executing user: {path}")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise SystemExit(f"ERROR: {label} must be owner-only (mode 0600 or stricter): {path}")
    return path

def read_secret(path_value, label):
    path = regular_file(path_value, label, secret=True)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    with os.fdopen(fd, "r", encoding="utf-8") as fh:
        info = os.fstat(fh.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise SystemExit(f"ERROR: {label} changed while it was being opened: {path}")
        value = fh.read().strip()
    if not value:
        raise SystemExit(f"ERROR: {label} must not be empty: {path}")
    if "\n" in value or "\r" in value:
        raise SystemExit(f"ERROR: {label} must contain exactly one line: {path}")
    return value

def backup_existing(target):
    if not target.exists():
        return
    if target.is_symlink() or not target.is_file():
        raise SystemExit(f"ERROR: target must be a regular, non-symlink file: {target}")
    stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    for suffix in range(1000):
        backup = target.with_name(f"{target.name}.bak.{stamp}.{os.getpid()}.{suffix}")
        try:
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "wb") as fh:
            fh.write(target.read_bytes())
            fh.flush()
            os.fsync(fh.fileno())
        return
    raise SystemExit(f"ERROR: could not create a unique backup for {target}")

def install(target_value, source_value, access_key_file, secret_key_file):
    target = Path(target_value)
    source = regular_file(source_value, "rendered source")
    content = source.read_text(encoding="utf-8")
    if "__SMARTSTORE_S3_ACCESS_KEY_FROM_FILE__" in content:
        access_key = read_secret(access_key_file, "S3 access-key file")
        secret_key = read_secret(secret_key_file, "S3 secret-key file")
        content = content.replace("__SMARTSTORE_S3_ACCESS_KEY_FROM_FILE__", access_key)
        content = content.replace("__SMARTSTORE_S3_SECRET_KEY_FROM_FILE__", secret_key)
    if "__SMARTSTORE_" in content:
        raise SystemExit(f"ERROR: unresolved SmartStore secret placeholder remains in {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.is_symlink():
        raise SystemExit(f"ERROR: target directory must not be a symlink: {target.parent}")
    backup_existing(target)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise

for offset in range(1, len(sys.argv), 4):
    install(*sys.argv[offset:offset + 4])
"""


def curl_config_python(auth_scheme: str) -> str:
    return f'''from pathlib import Path
import os
import stat
import sys

token_path = Path(sys.argv[1])
config_path = Path(sys.argv[2])
flags = os.O_RDONLY
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
try:
    fd = os.open(token_path, flags)
except OSError as exc:
    raise SystemExit(f"ERROR: cannot securely open token file {{token_path}}: {{exc}}")
with os.fdopen(fd, "r", encoding="utf-8") as fh:
    token_info = os.fstat(fh.fileno())
    if not stat.S_ISREG(token_info.st_mode):
        raise SystemExit(f"ERROR: token file must be a regular, non-symlink file: {{token_path}}")
    if token_info.st_uid != os.geteuid():
        raise SystemExit(f"ERROR: token file must be owned by the executing user: {{token_path}}")
    if stat.S_IMODE(token_info.st_mode) & 0o077:
        raise SystemExit(f"ERROR: token file must be owner-only (mode 0600 or stricter): {{token_path}}")
    token = fh.read().strip()
if not token:
    raise SystemExit(f"ERROR: token file is empty: {{token_path}}")
if any(char.isspace() for char in token):
    raise SystemExit(f"ERROR: token file must contain one whitespace-free token: {{token_path}}")
escaped = token.replace("\\", "\\\\").replace('"', '\\"')
flags = os.O_WRONLY | os.O_TRUNC
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
fd = os.open(config_path, flags)
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write('header = "Authorization: {auth_scheme} ' + escaped + '"\\n')
        fh.flush()
        os.fsync(fh.fileno())
except BaseException:
    try:
        os.close(fd)
    except OSError:
        pass
    raise
'''


def secure_curl_context(token_var: str, auth_scheme: str) -> str:
    return f'''umask 077
command -v curl >/dev/null || {{ echo "ERROR: curl is required." >&2; exit 1; }}
command -v python3 >/dev/null || {{ echo "ERROR: python3 is required." >&2; exit 1; }}
curl_config="$(mktemp "${{TMPDIR:-/tmp}}/splunk-index-lifecycle-curl.XXXXXX")"
cleanup_curl_config() {{ rm -f -- "${{curl_config}}"; }}
trap cleanup_curl_config EXIT
python3 - "${{{token_var}}}" "${{curl_config}}" <<'PY'
{curl_config_python(auth_scheme)}PY
'''


def acs_http_runtime_python() -> str:
    return r'''import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import quote

acs_base, stack, curl_config = sys.argv[1:4]

def response_summary(raw, limit=2000):
    def redact(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                lowered = str(key).lower()
                result[key] = "<redacted>" if any(word in lowered for word in ("token", "secret", "password", "credential")) else redact(item)
            return result
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value
    try:
        rendered = json.dumps(redact(json.loads(raw)), sort_keys=True)
    except Exception:
        rendered = raw
    return rendered if limit is None else rendered[:limit]

def request(method, url, body=None):
    with tempfile.TemporaryDirectory(prefix="splunk-index-acs-") as tmp_dir:
        response_path = Path(tmp_dir) / "response.json"
        response_path.touch(mode=0o600)
        command = [
            "curl", "-sS", "--proto", "=https", "--connect-timeout", "15", "--max-time", "120",
            "-o", str(response_path), "-w", "%{http_code}", "-X", method, url, "-K", curl_config,
            "-H", "Accept: application/json",
        ]
        if body is not None:
            payload_path = Path(tmp_dir) / "payload.json"
            fd = os.open(payload_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(body, fh, separators=(",", ":"), sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            command.extend(["-H", "Content-Type: application/json", "--data-binary", f"@{payload_path}"])
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        status = result.stdout.strip()
        raw = response_path.read_text(encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"curl failed with return code {result.returncode}")
    if not re.fullmatch(r"[0-9]{3}", status):
        raise RuntimeError(f"ACS returned an invalid HTTP status {status!r}: {response_summary(raw)}")
    return int(status), raw

def index_url(name):
    return f"{acs_base.rstrip('/')}/{quote(stack, safe='')}/adminconfig/v2/indexes/{quote(name, safe='')}"

def collection_url():
    return f"{acs_base.rstrip('/')}/{quote(stack, safe='')}/adminconfig/v2/indexes"

def parse_json_object(raw, context):
    try:
        value = json.loads(raw)
    except Exception as exc:
        raise RuntimeError(f"{context} returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{context} returned JSON type {type(value).__name__}, expected object")
    return value

def extract_index_record(value, name):
    candidates = [value]
    for key in ("index", "item", "data"):
        child = value.get(key) if isinstance(value, dict) else None
        if isinstance(child, dict):
            candidates.append(child)
    for key in ("indexes", "items", "results"):
        child = value.get(key) if isinstance(value, dict) else None
        if isinstance(child, list):
            candidates.extend(item for item in child if isinstance(item, dict))
    for candidate in candidates:
        if candidate.get("name") == name or candidate.get("title") == name:
            return candidate
    for candidate in candidates:
        if any(key in candidate for key in ("searchableDays", "maxDataSizeMB", "splunkArchivalRetentionDays")):
            return candidate
    raise RuntimeError(f"ACS readback did not contain an index record for {name}")

def equivalent(actual, expected):
    if isinstance(expected, int):
        try:
            return int(actual) == expected
        except (TypeError, ValueError):
            return False
    return actual == expected

def verify_fields(record, expected):
    return {
        key: {"expected": value, "actual": record.get(key)}
        for key, value in expected.items()
        if key not in record or not equivalent(record.get(key), value)
    }
'''


def smartstore_expected_settings(args: argparse.Namespace) -> dict[str, dict[str, dict[str, str]]]:
    indexes: dict[str, dict[str, str]] = {
        f"volume:{args.volume_name}": {
            "storageType": "remote",
            "path": args.remote_path,
        }
    }
    volume = indexes[f"volume:{args.volume_name}"]
    if args.remote_provider == "s3":
        optional = {
            "remote.s3.endpoint": args.s3_endpoint,
            "remote.s3.auth_region": args.s3_auth_region,
            "remote.s3.signature_version": args.s3_signature_version,
            "remote.s3.kms.key_id": args.s3_kms_key_id,
            "remote.s3.kms.auth_region": args.s3_kms_auth_region,
            "remote.s3.sslVersions": args.s3_ssl_versions,
        }
        volume.update({key: value for key, value in optional.items() if value})
        for key, value in (
            ("remote.s3.supports_versioning", args.s3_supports_versioning),
            ("remote.s3.tsidx_compression", args.s3_tsidx_compression),
            ("remote.s3.encryption", args.s3_encryption),
            ("remote.s3.sslVerifyServerCert", args.s3_ssl_verify_server_cert),
        ):
            if value != "unset":
                volume[key] = value
        if args.s3_access_key_file:
            volume["remote.s3.access_key"] = "__NONEMPTY_SECRET__"
            volume["remote.s3.secret_key"] = "__NONEMPTY_SECRET__"
    elif args.remote_provider == "gcs" and args.gcs_credential_file:
        volume["remote.gs.credential_file"] = args.gcs_credential_file
    elif args.remote_provider == "azure":
        if args.azure_endpoint:
            volume["remote.azure.endpoint"] = args.azure_endpoint
        if args.azure_container_name:
            volume["remote.azure.container_name"] = args.azure_container_name

    retention = {
        line.split("=", 1)[0].strip(): line.split("=", 1)[1].strip()
        for line in retention_lines(args)
    }
    if args.scope == "global":
        indexes["default"] = {"remotePath": f"volume:{args.volume_name}/$_index_name", **retention}
        if args.deployment == "cluster":
            indexes["default"]["repFactor"] = "auto"
    for index in target_indexes(args):
        expected: dict[str, str] = {}
        if args.deployment == "cluster":
            expected["repFactor"] = "auto"
        if args.scope == "per-index":
            expected["remotePath"] = f"volume:{args.volume_name}/$_index_name"
            expected.update(retention)
        if args.index_hotlist_recency_secs:
            expected["hotlist_recency_secs"] = args.index_hotlist_recency_secs
        if args.index_hotlist_bloom_filter_recency_hours:
            expected["hotlist_bloom_filter_recency_hours"] = args.index_hotlist_bloom_filter_recency_hours
        indexes[index] = expected

    server: dict[str, dict[str, str]] = {}
    if bool_value(args.clean_remote_storage_by_default):
        server["general"] = {"cleanRemoteStorageByDefault": "true"}
    cache = {
        key: value
        for key, value in (
            ("eviction_policy", args.eviction_policy),
            ("max_cache_size", args.cache_size_mb),
            ("eviction_padding", args.eviction_padding_mb),
            ("hotlist_recency_secs", args.hotlist_recency_secs),
            ("hotlist_bloom_filter_recency_hours", args.hotlist_bloom_filter_recency_hours),
        )
        if value
    }
    if cache:
        server["cachemanager"] = cache
    limits = {
        key: value
        for key, value in (
            ("bucket_localize_acquire_lock_timeout_sec", args.bucket_localize_acquire_lock_timeout_sec),
            ("bucket_localize_connect_timeout_max_retries", args.bucket_localize_connect_timeout_max_retries),
            ("bucket_localize_max_timeout_sec", args.bucket_localize_max_timeout_sec),
        )
        if value
    }
    result: dict[str, dict[str, dict[str, str]]] = {"indexes": indexes}
    if server:
        result["server"] = server
    if limits:
        result["limits"] = {"remote_storage": limits}
    return result


def retention_expected_settings(args: argparse.Namespace) -> dict[str, dict[str, dict[str, str]]]:
    settings = {
        line.split("=", 1)[0].strip(): line.split("=", 1)[1].strip()
        for line in enterprise_retention_lines(args)
    }
    return {"indexes": {index: dict(settings) for index in target_indexes(args)}}


def btool_readback_python(expected: dict[str, dict[str, dict[str, str]]]) -> str:
    expected_literal = repr(json.dumps(expected, sort_keys=True))
    return f'''import json
import re
import subprocess
import sys

splunk_home = sys.argv[1]
expected = json.loads({expected_literal})
failures = []
for conf_name, stanzas in expected.items():
    for stanza, settings in stanzas.items():
        result = subprocess.run(
            [f"{{splunk_home}}/bin/splunk", "btool", conf_name, "list", stanza],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            failures.append(f"{{conf_name}} [{{stanza}}]: btool failed: {{result.stderr.strip()}}")
            continue
        actual = {{}}
        for line in result.stdout.splitlines():
            match = re.match(r"^\\s*([^#;][^=]*?)\\s*=\\s*(.*?)\\s*$", line)
            if match:
                actual[match.group(1).strip()] = match.group(2)
        for key, wanted in settings.items():
            observed = actual.get(key)
            if wanted == "__NONEMPTY_SECRET__":
                if not observed or observed.startswith("__SMARTSTORE_"):
                    failures.append(f"{{conf_name}} [{{stanza}}] {{key}}: secret value is missing or unresolved")
            elif observed != wanted:
                failures.append(f"{{conf_name}} [{{stanza}}] {{key}}: expected {{wanted!r}}, got {{observed!r}}")
if failures:
    print("ERROR: post-activation btool readback did not match the rendered configuration:", file=sys.stderr)
    for failure in failures:
        print(f"  - {{failure}}", file=sys.stderr)
    raise SystemExit(1)
print("Post-activation btool readback matched all rendered settings.")
'''


def render_apply(args: argparse.Namespace, cluster: bool) -> str:
    splunk_home = shell_quote(args.splunk_home)
    app_name = shell_quote(args.app_name)
    access_key_file = shell_quote(str(Path(args.s3_access_key_file).expanduser())) if args.s3_access_key_file else "''"
    secret_key_file = shell_quote(str(Path(args.s3_secret_key_file).expanduser())) if args.s3_secret_key_file else "''"
    base = "${splunk_home}/etc/manager-apps" if cluster else "${splunk_home}/etc/apps"
    bundle_block = (
        '"${splunk_home}/bin/splunk" apply cluster-bundle --answer-yes\n'
        '"${splunk_home}/bin/splunk" show cluster-bundle-status\n'
        if cluster and bool_value(args.apply_cluster_bundle)
        else 'echo "HANDOFF: cluster bundle apply is disabled; configuration was staged but not activated." >&2\nexit 2\n'
    )
    restart_block = (
        '"${splunk_home}/bin/splunk" restart\n'
        'python3 - "${splunk_home}" <<\'PY\'\n'
        f'{btool_readback_python(smartstore_expected_settings(args))}'
        'PY\n'
        if not cluster and bool_value(args.restart_splunk)
        else 'echo "HANDOFF: restart is disabled; configuration was staged but not activated." >&2\nexit 2\n'
    )
    final_block = bundle_block if cluster else restart_block
    return make_script(
        f"""rendered_operation={shell_quote(args.operation)}
[[ "${{rendered_operation}}" == "smartstore" ]] || {{ echo "ERROR: this helper was not rendered for a SmartStore operation." >&2; exit 2; }}
splunk_home={splunk_home}
app_name={app_name}
access_key_file={access_key_file}
secret_key_file={secret_key_file}

target_dir="{base}/${{app_name}}/local"
mkdir -p "${{target_dir}}"
python3 - \
  "${{target_dir}}/indexes.conf" indexes.conf.template "${{access_key_file}}" "${{secret_key_file}}" \
  "${{target_dir}}/server.conf" server.conf '' '' \
  "${{target_dir}}/limits.conf" limits.conf '' '' <<'PY'
{secure_install_python()}
PY
if grep -q '__SMARTSTORE_' "${{target_dir}}/indexes.conf" "${{target_dir}}/server.conf" "${{target_dir}}/limits.conf"; then
  echo "ERROR: unresolved SmartStore placeholder remains under ${{target_dir}}." >&2
  exit 1
fi
{final_block}"""
    )


def render_cloud_status(args: argparse.Namespace) -> str:
    token_file = shell_quote(str(Path(args.acs_token_file).expanduser()))
    base = shell_quote(args.acs_base.rstrip("/"))
    stack = shell_quote(args.stack)
    indexes_csv = shell_quote(",".join(target_indexes(args)))
    operation = shell_quote(args.operation)
    return make_script(
        f'''token_file={token_file}
acs_base={base}
stack={stack}
indexes_csv={indexes_csv}
operation={operation}
[[ -n "${{stack}}" ]] || {{ echo "ERROR: --stack is required for Splunk Cloud status." >&2; exit 1; }}
{secure_curl_context('token_file', 'Bearer')}python3 - "${{acs_base}}" "${{stack}}" "${{curl_config}}" "${{indexes_csv}}" "${{operation}}" <<'PY'
{acs_http_runtime_python()}
indexes_csv, operation = sys.argv[4:6]
indexes = [item for item in indexes_csv.split(",") if item]
expected_by_name = {{}}
if operation == "retention":
    payload_path = Path("acs-index-update-payload.json")
    if payload_path.is_symlink() or not payload_path.is_file():
        raise SystemExit(f"ERROR: ACS payload must be a regular, non-symlink file: {{payload_path}}")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    expected_by_name = {{
        item["name"]: {{key: value for key, value in item.items() if key not in ("name", "datatype")}}
        for item in payload.get("indexes", [])
        if isinstance(item, dict) and item.get("name")
    }}

if not indexes:
    status, raw = request("GET", collection_url())
    if status < 200 or status >= 300:
        raise SystemExit(f"ERROR: ACS index inventory failed with HTTP {{status}}: {{response_summary(raw)}}")
    print(response_summary(raw, None))
    raise SystemExit(0)

failures = []
for name in indexes:
    try:
        status, raw = request("GET", index_url(name))
        if operation == "delete-index":
            if status == 404:
                print(f"VERIFIED ABSENT: {{name}}")
                continue
            failures.append(f"{{name}}: expected HTTP 404 after deletion, got HTTP {{status}}")
            continue
        if status < 200 or status >= 300:
            failures.append(f"{{name}}: describe failed with HTTP {{status}}: {{response_summary(raw)}}")
            continue
        value = parse_json_object(raw, f"ACS describe for {{name}}")
        record = extract_index_record(value, name)
        mismatches = verify_fields(record, expected_by_name.get(name, {{}}))
        if mismatches:
            failures.append(f"{{name}}: readback mismatch {{json.dumps(mismatches, sort_keys=True)}}")
            continue
        print(f"VERIFIED PRESENT: {{name}}")
        print(response_summary(json.dumps(record, sort_keys=True), None))
    except Exception as exc:
        failures.append(f"{{name}}: {{exc}}")
if failures:
    print("ERROR: Splunk Cloud status verification failed:", file=sys.stderr)
    for failure in failures:
        print(f"  - {{failure}}", file=sys.stderr)
    raise SystemExit(1)
PY
'''
    )


def render_status(args: argparse.Namespace) -> str:
    if args.platform == "cloud":
        return render_cloud_status(args)
    splunk_home = shell_quote(args.splunk_home)
    volume = shell_quote(f"volume:{args.volume_name}")
    cluster_status = (
        '"${splunk_home}/bin/splunk" show cluster-bundle-status\n'
        if args.deployment == "cluster"
        else 'echo "INFO: standalone deployment; cluster bundle status is not applicable."\n'
    )
    return make_script(
        f"""rendered_operation={shell_quote(args.operation)}
[[ "${{rendered_operation}}" == "retention" ]] || {{ echo "ERROR: this helper was not rendered for a retention operation." >&2; exit 2; }}
splunk_home={splunk_home}
volume_output="$("${{splunk_home}}/bin/splunk" btool indexes list {volume} --debug)"
printf '%s\n' "${{volume_output}}" | grep -v -E 'remote\\.(s3|gs|azure)\\.(access|secret|key)' || echo "INFO: no non-secret settings found for {volume}."
indexes_output="$("${{splunk_home}}/bin/splunk" btool indexes list --debug)"
printf '%s\n' "${{indexes_output}}" | grep -E 'frozenTimePeriodInSecs|maxTotalDataSizeMB|maxGlobal(Data|Raw)SizeMB|disabled' || echo "INFO: no lifecycle overrides found."
"${{splunk_home}}/bin/splunk" btool server list cachemanager --debug
"${{splunk_home}}/bin/splunk" btool limits list remote_storage --debug
{cluster_status}
"""
    )


def render_apply_retention_enterprise(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    app_name = shell_quote(f"{args.app_name}_retention")
    base = "${splunk_home}/etc/manager-apps" if args.deployment == "cluster" else "${splunk_home}/etc/apps"
    final_block = (
        '"${splunk_home}/bin/splunk" apply cluster-bundle --answer-yes\n'
        '"${splunk_home}/bin/splunk" show cluster-bundle-status\n'
        if args.deployment == "cluster" and bool_value(args.apply_cluster_bundle)
        else (
            'echo "HANDOFF: cluster bundle apply is disabled; retention configuration was staged but not activated." >&2\nexit 2\n'
            if args.deployment == "cluster"
            else (
                '"${splunk_home}/bin/splunk" restart\n'
                'python3 - "${splunk_home}" <<\'PY\'\n'
                f'{btool_readback_python(retention_expected_settings(args))}'
                'PY\n'
                if bool_value(args.restart_splunk)
                else 'echo "HANDOFF: restart is disabled; retention configuration was staged but not activated." >&2\nexit 2\n'
            )
        )
    )
    return make_script(
        f"""splunk_home={splunk_home}
app_name={app_name}
target_dir="{base}/${{app_name}}/local"
mkdir -p "${{target_dir}}"
python3 - "${{target_dir}}/indexes.conf" retention-indexes.conf.template '' '' <<'PY'
{secure_install_python()}
PY
{final_block}"""
    )


def render_apply_retention_cloud(args: argparse.Namespace) -> str:
    token_file = shell_quote(str(Path(args.acs_token_file).expanduser()))
    base = shell_quote(args.acs_base.rstrip("/"))
    stack = shell_quote(args.stack)
    return make_script(
        f'''rendered_operation={shell_quote(args.operation)}
[[ "${{rendered_operation}}" == "retention" ]] || {{ echo "ERROR: this helper was not rendered for a retention operation." >&2; exit 2; }}
token_file={token_file}
acs_base={base}
stack={stack}
[[ -n "${{stack}}" ]] || {{ echo "ERROR: --stack is required for Splunk Cloud retention apply." >&2; exit 1; }}
{secure_curl_context('token_file', 'Bearer')}
python3 - "${{acs_base}}" "${{stack}}" "${{curl_config}}" <<'PY'
{acs_http_runtime_python()}
import time

payload_path = Path("acs-index-update-payload.json")
if payload_path.is_symlink() or not payload_path.is_file():
    raise SystemExit(f"ERROR: ACS payload must be a regular, non-symlink file: {{payload_path}}")
try:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
except Exception as exc:
    raise SystemExit(f"ERROR: cannot parse ACS payload: {{exc}}") from exc
items = payload.get("indexes") if isinstance(payload, dict) else None
if not isinstance(items, list) or not items:
    raise SystemExit("ERROR: no index payloads were rendered.")

verified = []
for item in items:
    name = item.get("name") if isinstance(item, dict) else None
    if not name:
        raise SystemExit("ERROR: ACS payload contains an invalid index record.")
    body = {{key: value for key, value in item.items() if key not in ("name", "datatype")}}
    if not body:
        raise SystemExit(f"ERROR: ACS payload for {{name}} has no mutable fields.")
    try:
        status, raw = request("PATCH", index_url(name), body)
        if status < 200 or status >= 300:
            raise RuntimeError(f"PATCH returned HTTP {{status}}: {{response_summary(raw)}}")
        last_problem = "readback did not run"
        for attempt in range(15):
            read_status, read_raw = request("GET", index_url(name))
            if 200 <= read_status < 300:
                value = parse_json_object(read_raw, f"ACS readback for {{name}}")
                record = extract_index_record(value, name)
                mismatches = verify_fields(record, body)
                if not mismatches:
                    verified.append(name)
                    print(f"VERIFIED: ACS retention fields for {{name}} match the requested values.")
                    break
                last_problem = f"field mismatch {{json.dumps(mismatches, sort_keys=True)}}"
            elif read_status in (404, 409, 429, 500, 502, 503, 504):
                last_problem = f"transient HTTP {{read_status}}: {{response_summary(read_raw)}}"
            else:
                raise RuntimeError(f"GET readback returned HTTP {{read_status}}: {{response_summary(read_raw)}}")
            if attempt < 14:
                time.sleep(2)
        else:
            raise RuntimeError(f"ACS did not converge after PATCH: {{last_problem}}")
    except Exception as exc:
        print(f"ERROR: ACS retention mutation failed for {{name}}: {{exc}}", file=sys.stderr)
        if verified:
            print("PARTIAL MUTATION: already verified indexes: " + ", ".join(verified), file=sys.stderr)
        raise SystemExit(1)
PY
'''
    )


def disruptive_gate_python() -> str:
    return r'''import json
from pathlib import Path
import stat
import sys

owner_path = Path(sys.argv[1])
evidence_path = Path(sys.argv[2])
for path, label in ((owner_path, "owner approval"), (evidence_path, "evidence")):
    try:
        info = path.lstat()
    except OSError as exc:
        raise SystemExit(f"ERROR: cannot inspect {label} file {path}: {exc}")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_size == 0:
        raise SystemExit(f"ERROR: {label} file must be a non-empty regular, non-symlink file: {path}")
try:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
except Exception as exc:
    raise SystemExit(f"ERROR: cannot parse evidence JSON: {exc}")
if not isinstance(evidence, dict):
    raise SystemExit("ERROR: evidence JSON must be an object.")
'''


def render_disable_script(args: argparse.Namespace) -> str:
    indexes = ",".join(target_indexes(args))
    splunk_home = shell_quote(args.splunk_home)
    app_name = shell_quote(f"{args.app_name}_disable")
    owner_file = shell_quote(str(Path(args.owner_approval_file).expanduser())) if args.owner_approval_file else "''"
    evidence_file = shell_quote(str(Path(args.evidence_file).expanduser())) if args.evidence_file else "''"
    operation_guard = f'''rendered_operation={shell_quote(args.operation)}
[[ "${{rendered_operation}}" == "disable-index" ]] || {{ echo "ERROR: this helper was not rendered for a disable-index operation." >&2; exit 2; }}
'''
    if args.platform == "cloud":
        return make_script(
            operation_guard
            + """cat <<'EOF'
Splunk Cloud index disable is not exposed as a safe generic apply path here.
Use ACS retention/delete or Splunk Web/support based on your Cloud stack policy.
EOF
exit 2
"""
        )
    if args.deployment == "cluster":
        final_block = (
            '"${splunk_home}/bin/splunk" apply cluster-bundle --answer-yes\n'
            '"${splunk_home}/bin/splunk" show cluster-bundle-status\n'
            if bool_value(args.apply_cluster_bundle)
            else 'echo "HANDOFF: cluster bundle apply is disabled; disable configuration was staged but not activated." >&2\nexit 2\n'
        )
        return make_script(
            operation_guard
            + f"""splunk_home={splunk_home}
app_name={app_name}
owner_approval_file={owner_file}
evidence_file={evidence_file}
python3 - "${{owner_approval_file}}" "${{evidence_file}}" <<'PY'
{disruptive_gate_python()}
PY
target_dir="${{splunk_home}}/etc/manager-apps/${{app_name}}/local"
mkdir -p "${{target_dir}}"
python3 - "${{target_dir}}/indexes.conf" indexes-disable.conf.template '' '' <<'PY'
{secure_install_python()}
PY
{final_block}"""
        )
    return make_script(
        operation_guard
        + f"""splunk_home={splunk_home}
owner_approval_file={owner_file}
evidence_file={evidence_file}
indexes_csv={shell_quote(indexes)}
python3 - "${{owner_approval_file}}" "${{evidence_file}}" <<'PY'
{disruptive_gate_python()}
PY
IFS=',' read -r -a indexes <<< "${{indexes_csv}}"
for idx in "${{indexes[@]}}"; do
  [[ -n "${{idx}}" ]] || continue
  "${{splunk_home}}/bin/splunk" disable index "${{idx}}"
done
python3 - "${{splunk_home}}" "${{indexes_csv}}" <<'PY'
import re
import subprocess
import sys

splunk_home, indexes_csv = sys.argv[1:3]
failures = []
for name in (item for item in indexes_csv.split(",") if item):
    result = subprocess.run(
        [f"{{splunk_home}}/bin/splunk", "btool", "indexes", "list", name],
        text=True,
        capture_output=True,
        check=False,
    )
    match = re.search(r"(?m)^\\s*disabled\\s*=\\s*(\\S+)\\s*$", result.stdout)
    if result.returncode != 0 or not match or match.group(1).lower() not in ("1", "true", "yes"):
        failures.append(name)
if failures:
    raise SystemExit("ERROR: post-disable btool readback did not show disabled=true for: " + ", ".join(failures))
print("Post-disable btool readback verified: " + ", ".join(item for item in indexes_csv.split(",") if item))
PY
"""
    )


def destructive_gate_python() -> str:
    protected_defaults = sorted(PROTECTED_DEFAULT_INDEXES)
    sensitive = sorted(SENSITIVE_INDEXES)
    return f"""import json, stat, sys
from pathlib import Path

evidence_path, indexes_csv, confirm_tokens_csv, owner_path, backup_path = sys.argv[1:6]
indexes = [item for item in indexes_csv.split(",") if item]
tokens = set(item for item in confirm_tokens_csv.split(",") if item)
protected_defaults = set({protected_defaults!r})
sensitive = set({sensitive!r})

for path_value, label in ((evidence_path, "evidence"), (owner_path, "owner approval"), (backup_path, "backup evidence")):
    path = Path(path_value)
    try:
        info = path.lstat()
    except OSError as exc:
        raise SystemExit(f"ERROR: cannot inspect {{label}} file {{path}}: {{exc}}")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_size == 0:
        raise SystemExit(f"ERROR: {{label}} file must be a non-empty regular, non-symlink file: {{path}}")

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
    safe_by_record = rec.get("safe_to_delete") is True and rec.get("dependencies_clear") is True
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
    gate = f"""rendered_operation={shell_quote(args.operation)}
[[ "${{rendered_operation}}" == "delete-index" ]] || {{ echo "ERROR: this helper was not rendered for a delete-index operation." >&2; exit 2; }}
accept_destructive={accept}
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
python3 - "${{evidence_file}}" "${{indexes_csv}}" "${{confirm_tokens_csv}}" "${{owner_approval_file}}" "${{backup_evidence_file}}" <<'PY'
{destructive_gate_python()}
PY
"""
    if args.platform == "cloud":
        token_file = shell_quote(str(Path(args.acs_token_file).expanduser()))
        base = shell_quote(args.acs_base.rstrip("/"))
        stack = shell_quote(args.stack)
        return make_script(
            gate
            + f'''token_file={token_file}
acs_base={base}
stack={stack}
[[ -n "${{stack}}" ]] || {{ echo "ERROR: --stack is required for Splunk Cloud delete apply." >&2; exit 1; }}
{secure_curl_context('token_file', 'Bearer')}python3 - "${{acs_base}}" "${{stack}}" "${{curl_config}}" "${{indexes_csv}}" <<'PY'
{acs_http_runtime_python()}
import time

indexes = [item for item in sys.argv[4].split(",") if item]
verified = []
for name in indexes:
    try:
        status, raw = request("DELETE", index_url(name))
        if status < 200 or status >= 300:
            raise RuntimeError(f"DELETE returned HTTP {{status}}: {{response_summary(raw)}}")
        last_problem = "readback did not run"
        for attempt in range(15):
            read_status, read_raw = request("GET", index_url(name))
            if read_status == 404:
                verified.append(name)
                print(f"VERIFIED ABSENT: {{name}}")
                break
            if 200 <= read_status < 300:
                last_problem = f"index is still present (HTTP {{read_status}})"
            elif read_status in (409, 429, 500, 502, 503, 504):
                last_problem = f"transient HTTP {{read_status}}: {{response_summary(read_raw)}}"
            else:
                raise RuntimeError(f"GET readback returned HTTP {{read_status}}: {{response_summary(read_raw)}}")
            if attempt < 14:
                time.sleep(2)
        else:
            raise RuntimeError(f"ACS did not confirm deletion: {{last_problem}}")
    except Exception as exc:
        print(f"ERROR: ACS delete failed for {{name}}: {{exc}}", file=sys.stderr)
        if verified:
            print("PARTIAL MUTATION: already verified absent: " + ", ".join(verified), file=sys.stderr)
        raise SystemExit(1)
PY
'''
        )
    splunk_home = shell_quote(args.splunk_home)
    if args.deployment == "cluster":
        app_name = shell_quote(args.app_name)
        final_block = (
            '"${splunk_home}/bin/splunk" apply cluster-bundle --answer-yes\n'
            '"${splunk_home}/bin/splunk" show cluster-bundle-status\n'
            if bool_value(args.apply_cluster_bundle)
            else 'echo "HANDOFF: cluster bundle apply is disabled; index stanzas were removed only from the staged manager app." >&2\nexit 2\n'
        )
        return make_script(
            gate
            + f"""splunk_home={splunk_home}
app_name={app_name}
target_conf="${{splunk_home}}/etc/manager-apps/${{app_name}}/local/indexes.conf"
python3 - "${{target_conf}}" "${{indexes_csv}}" <<'PY'
from pathlib import Path
import os
import stat
import sys
import tempfile
import time

path = Path(sys.argv[1])
targets = set(item for item in sys.argv[2].split(",") if item)
try:
    info = path.lstat()
except OSError as exc:
    raise SystemExit(f"ERROR: cannot inspect manager app indexes.conf {{path}}: {{exc}}")
if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
    raise SystemExit(f"ERROR: manager app indexes.conf must be a regular, non-symlink file: {{path}}")
lines = path.read_text(encoding="utf-8").splitlines()
out = []
skip = False
found = set()
for line in lines:
    stripped = line.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        stanza = stripped[1:-1]
        skip = stanza in targets
        if skip:
            found.add(stanza)
    if not skip:
        out.append(line)
missing = sorted(targets - found)
if missing:
    raise SystemExit("ERROR: target manager app does not define index stanza(s): " + ", ".join(missing))
stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
backup = path.with_name(f"{{path.name}}.bak.{{stamp}}.{{os.getpid()}}")
fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "wb") as fh:
    fh.write(path.read_bytes())
    fh.flush()
    os.fsync(fh.fileno())
fd, tmp_name = tempfile.mkstemp(prefix=f".{{path.name}}.", dir=path.parent)
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\\n".join(out).rstrip() + "\\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_name, path)
except BaseException:
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.unlink(tmp_name)
    except FileNotFoundError:
        pass
    raise
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
python3 - "${{splunk_home}}" "${{indexes_csv}}" <<'PY'
import re
import subprocess
import sys

splunk_home, indexes_csv = sys.argv[1:3]
still_present = []
for name in (item for item in indexes_csv.split(",") if item):
    result = subprocess.run(
        [f"{{splunk_home}}/bin/splunk", "btool", "indexes", "list", name],
        text=True,
        capture_output=True,
        check=False,
    )
    if re.search(rf"(?m)^\\s*\\[{{re.escape(name)}}\\]\\s*$", result.stdout):
        still_present.append(name)
if still_present:
    raise SystemExit("ERROR: post-delete btool readback still finds index stanza(s): " + ", ".join(still_present))
print("Post-delete btool readback verified index stanza absence.")
PY
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
        f"""rendered_operation={shell_quote(args.operation)}
[[ "${{rendered_operation}}" == "clean-data" ]] || {{ echo "ERROR: this helper was not rendered for a clean-data operation." >&2; exit 2; }}
accept_destructive={accept}
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
python3 - "${{evidence_file}}" "${{indexes_csv}}" "${{confirm_tokens_csv}}" "${{owner_approval_file}}" "${{backup_evidence_file}}" <<'PY'
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
bash skills/splunk-ddaa-archive-setup/scripts/setup.sh \\
  --phase render \\
  --index {first_index} \\
  --searchable-days {args.searchable_days or '<searchable-days>'} \\
  --archival-retention-days {args.archival_retention_days or '<total-retention-days>'}

Restore remains a Splunk Web workflow from Settings > Indexes.
EOF
exit 2
"""
        )
    return make_script(
        """cat <<'EOF'
Self-managed archive handoff:

- Review frozenTimePeriodInSecs and cold-to-frozen archive requirements.
- Configure coldToFrozenScript or frozen archive path only after backup and restore tests.
- Use retention-indexes.conf.template for the searchable retention overlay.
EOF
exit 2
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
    script = make_script("cat restore-handoff.md\necho 'HANDOFF: restore requires operator-controlled Splunk Web or thaw steps; no data was restored.' >&2\nexit 2\n")
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
