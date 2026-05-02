#!/usr/bin/env python3
"""Render Splunk index lifecycle and SmartStore assets."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
from pathlib import Path


GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "indexes.conf.template",
    "server.conf",
    "limits.conf",
    "preflight.sh",
    "apply-cluster-manager.sh",
    "apply-standalone-indexer.sh",
    "status.sh",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk SmartStore lifecycle assets.")
    parser.add_argument("--deployment", choices=("cluster", "standalone"), default="cluster")
    parser.add_argument("--scope", choices=("per-index", "global"), default="per-index")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--splunk-home", default="/opt/splunk")
    parser.add_argument("--app-name", default="ZZZ_cisco_skills_smartstore")
    parser.add_argument("--remote-provider", choices=("s3", "gcs", "azure"), default="s3")
    parser.add_argument("--volume-name", default="remote_store")
    parser.add_argument("--remote-path", required=True)
    parser.add_argument("--indexes", default="main")
    parser.add_argument("--max-global-data-size-mb", default="")
    parser.add_argument("--max-global-raw-data-size-mb", default="")
    parser.add_argument("--frozen-time-period-in-secs", default="")
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


def validate_index_name(value: str) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value or ""):
        die(f"Invalid index name {value!r}; use lowercase letters, numbers, underscores, and hyphens, starting with a letter or number.")
    if "kvstore" in value:
        die(f"Invalid index name {value!r}; index names must not contain 'kvstore'.")


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
    scheme = args.remote_path.split(":", 1)[0]
    expected_scheme = {"s3": "s3", "gcs": "gs", "azure": "azure"}[args.remote_provider]
    if scheme != expected_scheme:
        die(f"--remote-path must start with {expected_scheme}:// for --remote-provider {args.remote_provider}.")
    indexes = csv_list(args.indexes)
    if not indexes:
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
    ):
        no_newline(value, option)
    for value, option in (
        (args.max_global_data_size_mb, "--max-global-data-size-mb"),
        (args.max_global_raw_data_size_mb, "--max-global-raw-data-size-mb"),
        (args.frozen_time_period_in_secs, "--frozen-time-period-in-secs"),
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


def retention_lines(args: argparse.Namespace) -> list[str]:
    lines: list[str] = []
    if args.max_global_data_size_mb:
        lines.append(f"maxGlobalDataSizeMB = {args.max_global_data_size_mb}")
    if args.max_global_raw_data_size_mb:
        lines.append(f"maxGlobalRawDataSizeMB = {args.max_global_raw_data_size_mb}")
    if args.frozen_time_period_in_secs:
        lines.append(f"frozenTimePeriodInSecs = {args.frozen_time_period_in_secs}")
    return lines


def render_indexes(args: argparse.Namespace) -> str:
    indexes = csv_list(args.indexes)
    lines = [
        "# Rendered by splunk-index-lifecycle-smartstore-setup. Review before applying.",
        "# SmartStore remote volume paths must be unique per running indexer or indexer cluster.",
    ]
    if args.scope == "global":
        lines.extend(
            [
                "[default]",
                f"remotePath = volume:{args.volume_name}/$_index_name",
            ]
        )
        if args.deployment == "cluster":
            lines.append("repFactor = auto")
        lines.extend(retention_lines(args))
        lines.append("")
    lines.extend(
        [
            f"[volume:{args.volume_name}]",
            "storageType = remote",
            f"path = {args.remote_path}",
        ]
    )
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
    elif args.remote_provider == "gcs":
        if args.gcs_credential_file:
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


def render_readme(args: argparse.Namespace) -> str:
    return f"""# Splunk SmartStore Rendered Assets

Deployment: `{args.deployment}`
Scope: `{args.scope}`
Remote provider: `{args.remote_provider}`
Volume: `{args.volume_name}`
Remote path: `{args.remote_path}`

Files:

- `indexes.conf.template`
- `server.conf`
- `limits.conf`
- `preflight.sh`
- `apply-cluster-manager.sh`
- `apply-standalone-indexer.sh`
- `status.sh`

For indexer clusters, apply on the cluster manager and use the configuration
bundle method. SmartStore `indexes.conf` settings must be consistent across
all peers.

If S3 access-key files were supplied, the rendered `indexes.conf.template`
contains placeholders and the apply scripts substitute values locally.
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
"${{splunk_home}}/bin/splunk" btool server list cachemanager --debug 2>/dev/null || true
"${{splunk_home}}/bin/splunk" btool limits list remote_storage --debug 2>/dev/null || true
"${{splunk_home}}/bin/splunk" show cluster-bundle-status 2>/dev/null || true
"""
    )


def render(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "smartstore"
    assets: list[str] = []
    if not args.dry_run:
        clean_render_dir(render_dir)
        files = {
            "README.md": render_readme(args),
            "metadata.json": json.dumps(
                {
                    "deployment": args.deployment,
                    "scope": args.scope,
                    "remote_provider": args.remote_provider,
                    "volume_name": args.volume_name,
                    "remote_path": args.remote_path,
                    "indexes": csv_list(args.indexes),
                    "s3_encryption": args.s3_encryption,
                    "s3_access_key_file": args.s3_access_key_file,
                    "s3_secret_key_file": args.s3_secret_key_file,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "indexes.conf.template": render_indexes(args),
            "server.conf": render_server(args),
            "limits.conf": render_limits(args),
            "preflight.sh": render_preflight(args),
            "apply-cluster-manager.sh": render_apply(args, cluster=True),
            "apply-standalone-indexer.sh": render_apply(args, cluster=False),
            "status.sh": render_status(args),
        }
        for rel, content in files.items():
            write_file(render_dir / rel, content, executable=rel.endswith(".sh"))
            assets.append(rel)
    return {
        "target": "smartstore",
        "deployment": args.deployment,
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "assets": assets,
        "dry_run": args.dry_run,
        "commands": {
            "preflight": [["./preflight.sh"]],
            "apply": [["./apply-cluster-manager.sh" if args.deployment == "cluster" else "./apply-standalone-indexer.sh"]],
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
        print(f"Would render SmartStore assets under {payload['render_dir']}")
    else:
        print(f"Rendered SmartStore assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
