"""Render Splunk Observability Database Monitoring collector assets."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shutil
import stat
import sys
from datetime import date
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


SKILL_NAME = "splunk-observability-database-monitoring-setup"
DEFAULT_COLLECTOR_VERSION = "v0.158.0"
SUPPORTED_COLLECTOR_VERSIONS = {DEFAULT_COLLECTOR_VERSION}
AUDITED_COLLECTOR_REPOSITORY = "quay.io/signalfx/splunk-otel-collector"
AUDITED_COLLECTOR_MANIFEST_DIGEST = (
    "sha256:27a458cd6873d6fef7d3d88fe0a266dffe83d5fe222df738f1937593d8c43357"
)
AUDITED_COLLECTOR_IMAGE = (
    f"{AUDITED_COLLECTOR_REPOSITORY}:0.158.0@{AUDITED_COLLECTOR_MANIFEST_DIGEST}"
)
# Per-platform sub-manifest digests behind the 0.158.0 manifest list, in the
# order linux/amd64, linux/arm64, linux/ppc64le. A running pod reports the
# platform digest rather than the list digest, so apply-time image verification
# has to accept either form.
AUDITED_LINUX_IMAGE_DIGESTS = {
    "sha256:16f784e3966cf9ced03ea3765a39f44c3e6395d04d4885e55fde6fc83328b2f0",
    "sha256:90aeaa8d2ab3ddf7ed5f0758660daccdd99ce4f7cfb0d74d6a7d975613eebb6a",
    "sha256:af49079eaf5dc79fd957f00171653703f3c044ae0fd5777c4cefa38d037d47fd",
}
AUDITED_CHART_SHA256 = (
    "088a93ebbcfbecf8e6f7ef3651747b65bbad443f0823489768bd4901cce0a274"
)
# Rendered as the shell `case` arm that accepts the audited runtime image, built
# from the constants above so the two can never drift apart.
AUDITED_IMAGE_DIGEST_CASE_PATTERN = ("|\\\n" + " " * 8).join(
    f"*@{digest}"
    for digest in (
        AUDITED_COLLECTOR_MANIFEST_DIGEST,
        *sorted(AUDITED_LINUX_IMAGE_DIGESTS),
    )
)
ALLOWED_REALMS = {"us0", "us1", "eu0", "eu1", "eu2", "au0", "jp0", "sg0"}
TARGET_TYPES = {"postgresql", "sqlserver", "oracledb", "mysql", "mariadb"}
TYPE_ALIASES = {
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "mssql": "sqlserver",
    "microsoft-sql-server": "sqlserver",
    "microsoft_sql_server": "sqlserver",
    "sql-server": "sqlserver",
    "sqlserver": "sqlserver",
    "oracle": "oracledb",
    "oracle-database": "oracledb",
    "oracle_database": "oracledb",
    "oracledb": "oracledb",
    "mysql": "mysql",
    "maria-db": "mariadb",
    "mariadb": "mariadb",
}
VERSION_FLOORS = {
    "postgresql": "v0.147.0",
    "sqlserver": "v0.148.0",
    "oracledb": "v0.148.0",
    "mysql": "v0.154.0",
    "mariadb": "v0.154.0",
}
SUPPORTED = {
    "postgresql": {
        "versions": {"14.20", "17.7", "14.15", "17.5"},
        "platforms": {"azure-flexible-server", "aws-rds"},
        "platform_versions": {
            "azure-flexible-server": {"14.20", "17.7"},
            "aws-rds": {"14.15", "17.5"},
        },
    },
    "sqlserver": {
        "versions": {"2016", "2017", "2019", "2022"},
        "platforms": {
            "azure-managed-instance",
            "azure-sql-database",
            "aws-rds",
            "self-hosted",
        },
    },
    "oracledb": {
        "versions": {"19c", "26ai"},
        "platforms": {"aws-rds", "oracle-rac", "self-hosted"},
    },
    "mysql": {
        "minimum_version": (5, 7),
        "version_label": "5.7.x, 8.0.x, 8.4.x, or 9.x",
        "platforms": {"aws-rds", "standalone"},
    },
    "mariadb": {
        "minimum_version": (10, 5),
        "version_label": "10.5.x through 10.11.x, or 11.x",
        "platforms": {"aws-rds", "standalone"},
    },
}
RECEIVER_TYPES = {
    "postgresql": "postgresql",
    "sqlserver": "sqlserver",
    "oracledb": "oracledb",
    "mysql": "mysql",
    "mariadb": "mysql",
}
DEFAULT_VALIDATION_METRICS = {
    "postgresql": "postgresql.database.count",
    "sqlserver": "sqlserver.lock.wait.rate",
    "oracledb": "oracledb.executions",
    "mysql": "mysql.buffer_pool.usage",
    "mariadb": "mysql.buffer_pool.usage",
}
METRIC_INVENTORY = {
    "postgresql": set(
        """postgresql.backends postgresql.bgwriter.buffers.allocated postgresql.bgwriter.buffers.writes
postgresql.bgwriter.checkpoint.count postgresql.bgwriter.duration postgresql.bgwriter.maxwritten
postgresql.blks_hit postgresql.blks_read postgresql.blocks_read postgresql.commits
postgresql.connection.max postgresql.database.count postgresql.database.locks postgresql.db_size
postgresql.deadlocks postgresql.function.calls postgresql.index.scans postgresql.index.size
postgresql.operations postgresql.replication.data_delay postgresql.rollbacks postgresql.rows
postgresql.sequential_scans postgresql.table.count postgresql.table.size postgresql.table.vacuum.count
postgresql.temp.io postgresql.temp_files postgresql.tup_deleted postgresql.tup_fetched
postgresql.tup_inserted postgresql.tup_returned postgresql.tup_updated postgresql.wal.age
postgresql.wal.delay""".split()
    ),
    "sqlserver": set(
        """sqlserver.attention.rate sqlserver.batch.request.rate sqlserver.batch.sql_compilation.rate
sqlserver.batch.sql_recompilation.rate sqlserver.computer.uptime sqlserver.cpu.count
sqlserver.database.backup_or_restore.rate sqlserver.database.count sqlserver.database.execution.errors
sqlserver.database.full_scan.rate sqlserver.database.io sqlserver.database.latency
sqlserver.database.operations sqlserver.database.tempdb.space sqlserver.database.tempdb.version_store.size
sqlserver.deadlock.rate sqlserver.index.search.rate sqlserver.latch.superlatch.count
sqlserver.latch.superlatch.transition.rate sqlserver.latch.wait.rate sqlserver.latch.wait_time.avg
sqlserver.latch.wait_time.total sqlserver.lock.timeout.rate sqlserver.lock.wait.count
sqlserver.lock.wait.rate sqlserver.lock.wait_time.avg sqlserver.login.rate sqlserver.logout.rate
sqlserver.memory.area sqlserver.memory.cache.object.count sqlserver.memory.grants.pending.count
sqlserver.memory.page.count sqlserver.memory.usage sqlserver.os.wait.duration
sqlserver.page.buffer_cache.free_list.stalls.rate sqlserver.page.buffer_cache.hit_ratio
sqlserver.page.checkpoint.flush.rate sqlserver.page.lazy_write.rate sqlserver.page.life_expectancy
sqlserver.page.lookup.rate sqlserver.page.operation.rate sqlserver.page.split.rate
sqlserver.parameterization.rate sqlserver.plan.execution.rate sqlserver.processes.blocked
sqlserver.recompilation.ratio sqlserver.replica.data.rate sqlserver.resource_pool.disk.operations
sqlserver.resource_pool.disk.throttled.read.rate sqlserver.resource_pool.disk.throttled.write.rate
sqlserver.table.count sqlserver.transaction.delay sqlserver.transaction.mirror_write.rate
sqlserver.transaction.rate sqlserver.transaction.write.rate sqlserver.transaction_log.flush.data.rate
sqlserver.transaction_log.flush.rate sqlserver.transaction_log.flush.wait.rate
sqlserver.transaction_log.growth.count sqlserver.transaction_log.shrink.count
sqlserver.transaction_log.usage sqlserver.user.connection.count""".split()
    ),
    "oracledb": set(
        """oracledb.buffer_cache.utilization oracledb.consistent_gets oracledb.cpu_time
oracledb.data_dictionary.hit_ratio oracledb.database.cpu.utilization oracledb.database.wait.utilization
oracledb.db_block_gets oracledb.ddl_statements_parallelized oracledb.dml_locks.limit
oracledb.dml_locks.usage oracledb.dml_statements_parallelized oracledb.enqueue_deadlocks
oracledb.enqueue_locks.limit oracledb.enqueue_locks.usage oracledb.enqueue_resources.limit
oracledb.enqueue_resources.usage oracledb.exchange_deadlocks oracledb.execution.utilization
oracledb.executions oracledb.hard_parses oracledb.host.cpu.utilization
oracledb.library_cache.utilization oracledb.logical_reads oracledb.logons
oracledb.parallel_operations_downgraded_1_to_25_pct oracledb.parallel_operations_downgraded_25_to_50_pct
oracledb.parallel_operations_downgraded_50_to_75_pct oracledb.parallel_operations_downgraded_75_to_99_pct
oracledb.parallel_operations_downgraded_to_serial oracledb.parallel_operations_not_downgraded
oracledb.parse.rate oracledb.parse.utilization oracledb.parse_calls oracledb.pga_memory
oracledb.physical_io.cache_writes oracledb.physical_io.requests oracledb.physical_io.transferred
oracledb.physical_read_io_requests oracledb.physical_reads oracledb.physical_reads_direct
oracledb.physical_write_io_requests oracledb.physical_writes oracledb.physical_writes_direct
oracledb.processes.limit oracledb.processes.usage oracledb.queries_parallelized
oracledb.recycle_bin.limit oracledb.redo_allocation.utilization oracledb.sessions.limit
oracledb.sessions.usage oracledb.shared_pool.utilization oracledb.sort.ratio
oracledb.sql_service.response.duration oracledb.sqlnet.io.transferred oracledb.storage.usage
oracledb.storage.utilization oracledb.tablespace_size.limit oracledb.tablespace_size.usage
oracledb.transactions.limit oracledb.transactions.usage oracledb.user_commits
oracledb.user_rollbacks""".split()
    ),
    "mysql": set(
        """mysql.buffer_pool.data_pages mysql.buffer_pool.limit mysql.buffer_pool.operations
mysql.buffer_pool.page_flushes mysql.buffer_pool.pages mysql.buffer_pool.usage mysql.client.network.io
mysql.commands mysql.connection.count mysql.connection.errors mysql.double_writes mysql.handlers
mysql.index.io.wait.count mysql.index.io.wait.time mysql.joins mysql.locks mysql.log_operations
mysql.max_used_connections mysql.mysqlx_connections mysql.mysqlx_worker_threads mysql.opened_resources
mysql.operations mysql.page_operations mysql.page_size mysql.prepared_statements mysql.query.client.count
mysql.query.count mysql.query.slow.count mysql.replica.sql_delay mysql.replica.time_behind_source
mysql.row_locks mysql.row_operations mysql.sorts mysql.statement_event.count
mysql.statement_event.wait.time mysql.table.average_row_length mysql.table.io.wait.count
mysql.table.io.wait.time mysql.table.lock_wait.read.count mysql.table.lock_wait.read.time
mysql.table.lock_wait.write.count mysql.table.lock_wait.write.time mysql.table.rows mysql.table.size
mysql.table_open_cache mysql.threads mysql.tmp_resources mysql.uptime""".split()
    ),
}
METRIC_INVENTORY["mariadb"] = METRIC_INVENTORY["mysql"]
K8S_DISTRIBUTIONS = {
    "kubernetes": "",
    "k8s": "",
    "": "",
    "aks": "aks",
    "eks": "eks",
    "eks/auto-mode": "eks/auto-mode",
    "eks/fargate": "eks/fargate",
    "gke": "gke",
    "gke/autopilot": "gke/autopilot",
    "openshift": "openshift",
}
MAX_TARGETS_PER_COLLECTOR = 30
RESOURCE_ATTRIBUTES = {
    "postgresql": {
        "postgresql.database.name",
        "postgresql.index.name",
        "postgresql.schema.name",
        "postgresql.table.name",
        "service.instance.id",
    },
    "sqlserver": {
        "host.name",
        "server.address",
        "server.port",
        "service.instance.id",
        "service.name",
        "service.namespace",
        "sqlserver.computer.name",
        "sqlserver.database.name",
        "sqlserver.instance.name",
    },
    "oracledb": {
        "host.name",
        "oracle.db.hosting_type",
        "oracle.db.open_mode",
        "oracle.db.pdb",
        "oracle.db.role",
        "oracle.db.version",
        "oracledb.instance.name",
        "service.instance.id",
    },
    "mysql": {"mysql.instance.endpoint", "service.instance.id"},
    "mariadb": {"mysql.instance.endpoint", "service.instance.id"},
}
RECEIVER_RESOURCE_ATTRIBUTES = {
    target_type: (
        {"mysql.instance.endpoint"}
        if target_type in {"mysql", "mariadb"}
        else set(attributes)
    )
    for target_type, attributes in RESOURCE_ATTRIBUTES.items()
}
SQLSERVER_OVERRIDE_TYPES = {
    "host.name": str,
    "server.address": str,
    "server.port": int,
    "service.instance.id": str,
    "service.name": str,
    "service.namespace": str,
    "sqlserver.computer.name": str,
    "sqlserver.database.name": str,
    "sqlserver.instance.name": str,
}
TLS_KEYS = {
    "ca_file",
    "cert_file",
    "cipher_suites",
    "curve_preferences",
    "include_insecure_cipher_suites",
    "include_system_ca_certs_pool",
    "insecure",
    "insecure_skip_verify",
    "key_file",
    "max_version",
    "min_version",
    "reload_interval",
    "server_name_override",
}
SECRET_VALUE_KEYS = {
    "password",
    "token",
    "access_token",
    "api_token",
    "api_key",
    "datasource",
    "connection_string",
    "client_secret",
    "private_key",
    "key_pem",
    "cert_pem",
    "ca_pem",
}
SECRET_VALUE_KEYS_NORMALIZED = {
    re.sub(r"[^a-z0-9]", "", key.lower()) for key in SECRET_VALUE_KEYS
}

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "shared" / "lib"))
from yaml_compat import dump_yaml, load_yaml_or_json  # noqa: E402


class RenderError(ValueError):
    """Raised when the DBMon spec or rendered assets are invalid."""


def bool_value(value: Any, *, label: str, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise RenderError(f"{label} must be a YAML/JSON boolean, not {value!r}.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--realm", default="")
    parser.add_argument("--cluster-name", default="")
    parser.add_argument("--distribution", default="")
    parser.add_argument("--collector-version", default="")
    parser.add_argument("--base-values", default="")
    parser.add_argument("--allow-unsupported-targets", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def load_spec(path: Path) -> dict[str, Any]:
    try:
        data = load_yaml_or_json(path.read_text(encoding="utf-8"), source=str(path))
    except Exception as exc:  # noqa: BLE001 - normalize parser exceptions for CLI.
        raise RenderError(f"Failed to parse spec {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RenderError(f"Spec {path} did not parse to a mapping.")
    if data.get("api_version") != f"{SKILL_NAME}/v1":
        raise RenderError(
            f"Spec api_version must be '{SKILL_NAME}/v1'; got {data.get('api_version')!r}"
        )
    allowed = {
        "allow_unsupported_targets",
        "api_version",
        "cluster_name",
        "collector",
        "distribution",
        "outputs",
        "realm",
        "scrape_owner",
        "sizing_evidence",
        "targets",
    }
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise RenderError("Spec contains unsupported top-level keys: " + ", ".join(unknown))
    reject_inline_secret_fields(data)
    return data


def reject_inline_secret_fields(value: Any, path: str = "spec") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            normalized_key = re.sub(r"[^a-z0-9]", "", key_text.lower())
            if normalized_key in SECRET_VALUE_KEYS_NORMALIZED and child not in (
                None,
                "",
            ):
                raise RenderError(
                    f"{child_path} contains secret-bearing material. Use env vars or "
                    "Kubernetes Secret references instead."
                )
            reject_inline_secret_fields(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_inline_secret_fields(child, f"{path}[{index}]")


def write_text(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def write_yaml(path: Path, payload: Any) -> None:
    write_text(path, dump_yaml(payload, sort_keys=False))


def write_json(path: Path, payload: Any) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def normalize_type(raw: Any) -> str:
    lowered = str(raw or "").strip().lower().replace(" ", "-")
    target_type = TYPE_ALIASES.get(lowered)
    if target_type not in TARGET_TYPES:
        raise RenderError(
            f"Unsupported target type {raw!r}; expected postgresql, sqlserver, "
            "oracledb, mysql, or mariadb."
        )
    return target_type


def normalize_platform(raw: Any) -> str:
    return str(raw or "").strip().lower().replace(" ", "-").replace("_", "-")


def safe_name(raw: Any) -> str:
    name = str(raw or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", name):
        raise RenderError(
            f"Target name {raw!r} must be 1..128 letters, digits, '_' or '-'."
        )
    return name


def dns_name(raw: Any, *, label: str) -> str:
    value = str(raw or "").strip()
    if len(value) > 253 or not re.fullmatch(r"[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?", value):
        raise RenderError(f"{label} {raw!r} must be a valid lowercase DNS name.")
    return value


def secret_key(raw: Any, *, label: str) -> str:
    value = str(raw or "").strip()
    if not re.fullmatch(r"[-._A-Za-z0-9]+", value):
        raise RenderError(f"{label} {raw!r} is not a valid Kubernetes Secret key.")
    return value


def env_name(raw: Any, *, label: str) -> str:
    value = str(raw or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise RenderError(f"{label} {raw!r} is not a valid environment variable name.")
    return value


def env_prefix(name: str) -> str:
    return "DBMON_" + re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()


def parse_semver(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(version).strip())
    if not match:
        raise RenderError(f"Collector version {version!r} must look like v0.150.0.")
    return tuple(int(part) for part in match.groups())


def parse_database_version(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?", version)
    if not match:
        raise RenderError(f"Database version {version!r} must be major.minor[.patch].")
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)


def duration_seconds(value: Any, *, label: str) -> float:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m|h)", str(value))
    if not match:
        raise RenderError(f"{label} must be a duration such as 10s, 1m, or 1h.")
    multiplier = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}[match.group(2)]
    return float(match.group(1)) * multiplier


def integer_value(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RenderError(f"{label} must be an integer.")
    return value


def reject_secret_like_text(value: str, *, label: str) -> None:
    if any(
        re.search(pattern, value)
        for pattern in (
            r"(?i)(?:password|passwd|token|secret|authorization|api[_-]?key)\s*[:=]",
            r"(?i)^[a-z][a-z0-9+.-]*://[^/@\s]+:[^/@\s]+@",
            r"AKIA[0-9A-Z]{16}",
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
            r"^[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}$",
        )
    ):
        raise RenderError(f"{label} resembles secret material; value suppressed.")


def normalized_sizing_evidence(
    raw: Any, *, required: bool
) -> dict[str, Any] | None:
    if raw is None:
        if required:
            raise RenderError(
                "sizing_evidence is required for PostgreSQL, MySQL, and MariaDB. "
                "Record a reviewed representative-load benchmark before production apply."
            )
        return None
    if not isinstance(raw, dict):
        raise RenderError("sizing_evidence must be a mapping.")
    expected = {
        "peak_cpu_cores",
        "peak_memory_mib",
        "reference",
        "reviewed_at",
        "reviewed_by",
        "target_count",
    }
    unknown = sorted(set(raw) - expected)
    missing = sorted(expected - set(raw))
    if unknown or missing:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unsupported: " + ", ".join(unknown))
        raise RenderError("sizing_evidence schema is invalid (" + "; ".join(details) + ").")
    evidence: dict[str, Any] = {}
    for key in ("reference", "reviewed_by"):
        value = str(raw.get(key) or "").strip()
        if (
            not value
            or len(value) > 256
            or any(character in value for character in "\r\n\x00")
            or re.search(r"(?i)placeholder|changeme|todo|tbd", value)
        ):
            raise RenderError(f"sizing_evidence.{key} must be a concrete, single-line value.")
        evidence[key] = value
        reject_secret_like_text(value, label=f"sizing_evidence.{key}")
    reviewed_at = str(raw.get("reviewed_at") or "").strip()
    try:
        reviewed_date = date.fromisoformat(reviewed_at)
    except ValueError as exc:
        raise RenderError("sizing_evidence.reviewed_at must be an ISO date (YYYY-MM-DD).") from exc
    if reviewed_date > date.today():
        raise RenderError("sizing_evidence.reviewed_at cannot be in the future.")
    evidence["reviewed_at"] = reviewed_at
    peak_memory = integer_value(
        raw.get("peak_memory_mib"), label="sizing_evidence.peak_memory_mib"
    )
    target_count = integer_value(
        raw.get("target_count"), label="sizing_evidence.target_count"
    )
    peak_cpu = raw.get("peak_cpu_cores")
    if (
        isinstance(peak_cpu, bool)
        or not isinstance(peak_cpu, (int, float))
        or peak_cpu <= 0
    ):
        raise RenderError("sizing_evidence.peak_cpu_cores must be a positive number.")
    if peak_memory <= 0 or not 1 <= target_count <= MAX_TARGETS_PER_COLLECTOR:
        raise RenderError(
            "sizing_evidence peak_memory_mib and target_count must be positive and "
            f"target_count must not exceed {MAX_TARGETS_PER_COLLECTOR}."
        )
    evidence["peak_memory_mib"] = peak_memory
    evidence["peak_cpu_cores"] = float(peak_cpu)
    evidence["target_count"] = target_count
    return evidence


def version_is_supported(target_type: str, version: str) -> bool:
    supported = SUPPORTED[target_type]
    if supported.get("product_supported") is False:
        return False
    if target_type == "mysql":
        major, minor, _ = parse_database_version(version)
        return (major == 5 and minor == 7) or (
            major == 8 and minor in {0, 4}
        ) or major == 9
    if target_type == "mariadb":
        major, minor, _ = parse_database_version(version)
        return (major == 10 and 5 <= minor <= 11) or major == 11
    if "minimum_version" in supported:
        try:
            return parse_database_version(version) >= supported["minimum_version"]
        except RenderError:
            return False
    return version in supported["versions"]


def component_version_is_supported(target_type: str, version: str) -> bool:
    if target_type == "mysql":
        parsed = parse_database_version(version)
        return parsed >= (5, 7)
    if target_type == "mariadb":
        return parse_database_version(version) >= (10, 5)
    return True


def supported_versions_text(target_type: str) -> str:
    supported = SUPPORTED[target_type]
    if "version_label" in supported:
        return str(supported["version_label"])
    return ", ".join(sorted(supported["versions"]))


def check_collector_floor(target_type: str, collector_version: str) -> None:
    floor = VERSION_FLOORS[target_type]
    if parse_semver(collector_version) < parse_semver(floor):
        raise RenderError(
            f"{target_type} Database Monitoring requires collector {floor} or later; "
            f"got {collector_version}."
        )


def normalize_targets(
    spec: dict[str, Any],
    collector_version: str,
    *,
    collector_namespace: str,
    allow_unsupported: bool,
) -> list[dict[str, Any]]:
    raw_targets = spec.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise RenderError("Spec must define at least one targets[] entry.")
    if len(raw_targets) > MAX_TARGETS_PER_COLLECTOR:
        raise RenderError(
            f"Spec defines {len(raw_targets)} targets; Splunk recommends at most "
            f"{MAX_TARGETS_PER_COLLECTOR} database servers per collector. Split the "
            "targets across dedicated collectors."
        )

    seen: set[str] = set()
    targets: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_targets):
        if not isinstance(raw, dict):
            raise RenderError(f"targets[{index}] must be a mapping.")
        target_type = normalize_type(raw.get("type"))
        name = safe_name(raw.get("name"))
        common_fields = {
            "advanced",
            "collection_interval",
            "connection_mode",
            "credentials",
            "events",
            "name",
            "platform",
            "transport_exception",
            "type",
            "validation_filters",
            "version",
        }
        type_fields = {
            "postgresql": {"databases", "endpoint"},
            "sqlserver": {"computer_name", "instance_name", "port", "server"},
            "oracledb": {"endpoint", "service"},
            "mysql": {"endpoint"},
            "mariadb": {"endpoint"},
        }[target_type]
        unknown_fields = sorted(set(raw) - common_fields - type_fields)
        if unknown_fields:
            raise RenderError(
                f"{target_type}/{name} contains unsupported fields: "
                + ", ".join(unknown_fields)
            )
        if name in seen:
            raise RenderError(f"Duplicate target name {name!r}.")
        seen.add(name)

        platform = normalize_platform(raw.get("platform"))
        if target_type in {"mysql", "mariadb"} and platform == "self-hosted":
            platform = "standalone"
        version = str(raw.get("version", "")).strip()
        if target_type in {"mysql", "mariadb"} and not re.fullmatch(
            r"\d+\.\d+(?:\.\d+)?", version
        ):
            raise RenderError(
                f"{target_type}/{name} version must be major.minor or major.minor.patch."
            )
        if not component_version_is_supported(target_type, version):
            floor = "5.7+" if target_type == "mysql" else "10.5+"
            raise RenderError(
                f"{target_type}/{name} version {version!r} is below Splunk's "
                f"published DBMon product floor {floor}."
            )
        supported = SUPPORTED[target_type]
        support_notes: list[str] = []
        if platform not in supported["platforms"]:
            support_notes.append(
                f"platform {platform!r} is outside the official support matrix "
                f"(allowed: {', '.join(sorted(supported['platforms']))})"
            )
        if not version_is_supported(target_type, version):
            support_notes.append(
                f"version {version!r} is outside the official support matrix "
                f"(allowed: {supported_versions_text(target_type)})"
            )
        if (
            target_type == "postgresql"
            and platform in supported["platforms"]
            and version in supported["versions"]
            and version not in supported["platform_versions"][platform]
        ):
            pairs = ", ".join(
                f"{provider}={version_name}"
                for provider, version_names in sorted(
                    supported["platform_versions"].items()
                )
                for version_name in sorted(version_names)
            )
            support_notes.append(
                f"PostgreSQL version/platform pair {platform}/{version} is not published "
                f"by Splunk (allowed pairs: {pairs})"
            )
        if support_notes and not allow_unsupported:
            raise RenderError(
                f"{target_type}/{name} {'; '.join(support_notes)}. "
                "Pass --allow-unsupported-targets only for lab/demo targets."
            )
        check_collector_floor(target_type, collector_version)

        normalized = dict(raw)
        normalized["name"] = name
        normalized["type"] = target_type
        normalized["receiver_type"] = RECEIVER_TYPES[target_type]
        normalized["receiver_id"] = f"{normalized['receiver_type']}/{name}"
        normalized["platform"] = platform
        normalized["version"] = version
        normalized["support_status"] = (
            "unsupported_opt_in" if support_notes else "official"
        )
        normalized["support_notes"] = support_notes
        normalized["connection_mode"] = (
            str(raw.get("connection_mode") or "direct").strip().lower()
        )
        normalized["events"] = normalized_events(target_type, raw.get("events"))
        normalized["credentials"] = normalized_credentials(
            name,
            raw.get("credentials"),
            connection_mode=normalized["connection_mode"],
            default_namespace=collector_namespace,
        )
        normalized["advanced"] = normalized_advanced(target_type, raw.get("advanced"))
        normalized["transport_exception"] = normalized_transport_exception(
            target_type=target_type,
            name=name,
            platform=platform,
            connection_mode=normalized["connection_mode"],
            raw=raw.get("transport_exception"),
        )
        validate_connection_fields(normalized)
        normalized["validation_filters"] = normalized_validation_filters(
            normalized, raw.get("validation_filters")
        )
        targets.append(normalized)
    validate_target_collisions(targets)
    return targets


def validate_target_collisions(targets: list[dict[str, Any]]) -> None:
    """Reject ambiguous process environments before rendering executable assets."""
    owners: dict[str, str] = {}
    identities: dict[tuple[tuple[str, str], ...], str] = {}
    for target in targets:
        filters = {
            item["key"]: item["value"] for item in target["validation_filters"]
        }
        if target["connection_mode"] == "windows":
            identity = tuple(
                (key, filters[key])
                for key in ("sqlserver.computer.name", "sqlserver.instance.name")
            )
        else:
            identity = (("service.instance.id", filters["service.instance.id"]),)
        if identity in identities:
            raise RenderError(
                f"Targets {identities[identity]} and {target['receiver_id']} share the same "
                "canonical validation identity; one database could falsely satisfy both probes."
            )
        identities[identity] = target["receiver_id"]
        if target["connection_mode"] == "windows":
            continue
        creds = target["credentials"]
        names = (
            [creds["datasource_var"]]
            if target["connection_mode"] == "datasource"
            else [creds["username_var"], creds["password_var"]]
        )
        for name in names:
            if name in owners:
                raise RenderError(
                    f"Environment variable {name!r} is shared by {owners[name]} and "
                    f"{target['receiver_id']}; give every credential reference a unique name."
                )
            owners[name] = target["receiver_id"]


def normalized_events(target_type: str, raw: Any) -> dict[str, bool]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise RenderError("target.events must be a mapping when provided.")
    allowed = {"query_sample", "top_query"}
    if target_type == "oracledb":
        allowed.add("session_wait_sample")
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise RenderError(
            f"{target_type} target.events contains unsupported keys: {', '.join(unknown)}."
        )
    events = {
        "query_sample": bool_value(
            raw.get("query_sample"), label="target.events.query_sample", default=True
        ),
        "top_query": bool_value(
            raw.get("top_query"), label="target.events.top_query", default=True
        ),
    }
    if target_type == "oracledb":
        events["session_wait_sample"] = bool_value(
            raw.get("session_wait_sample"),
            label="target.events.session_wait_sample",
            default=False,
        )
    return events


def normalized_transport_exception(
    *, target_type: str, name: str, platform: str, connection_mode: str, raw: Any
) -> dict[str, str] | None:
    managed_direct = (
        target_type == "sqlserver"
        and platform
        in {"azure-managed-instance", "azure-sql-database", "aws-rds"}
    ) or (target_type == "oracledb" and platform == "aws-rds")
    if managed_direct and connection_mode == "direct":
        raise RenderError(
            f"{target_type}/{name} on {platform} must use connection_mode: datasource "
            "with certificate-verifying driver options; the direct receiver fields do "
            "not expose transport security."
        )
    applies = target_type in {"sqlserver", "oracledb"} and connection_mode == "direct"
    if not applies:
        if raw is not None:
            raise RenderError(
                f"{target_type}/{name} transport_exception is allowed only for a direct "
                "self-managed SQL Server or Oracle connection."
            )
        return None
    if not isinstance(raw, dict):
        raise RenderError(
            f"{target_type}/{name} direct mode has no receiver TLS controls. Use a "
            "secret-backed datasource, or provide a reviewed transport_exception for "
            "an externally protected self-managed path."
        )
    expected = {"reason", "reference", "reviewed_at", "reviewed_by"}
    if set(raw) != expected:
        raise RenderError(
            f"{target_type}/{name} transport_exception must contain exactly: "
            + ", ".join(sorted(expected))
        )
    normalized: dict[str, str] = {}
    for key in ("reason", "reference", "reviewed_by"):
        value = str(raw.get(key) or "").strip()
        if (
            not value
            or len(value) > 512
            or any(character in value for character in "\r\n\x00")
            or re.search(r"(?i)placeholder|changeme|todo|tbd", value)
        ):
            raise RenderError(
                f"{target_type}/{name} transport_exception.{key} must be a concrete, single-line value."
            )
        normalized[key] = value
        reject_secret_like_text(
            value, label=f"{target_type}/{name} transport_exception.{key}"
        )
    reviewed_at = str(raw.get("reviewed_at") or "").strip()
    try:
        reviewed_date = date.fromisoformat(reviewed_at)
    except ValueError as exc:
        raise RenderError(
            f"{target_type}/{name} transport_exception.reviewed_at must be YYYY-MM-DD."
        ) from exc
    if reviewed_date > date.today():
        raise RenderError(
            f"{target_type}/{name} transport_exception.reviewed_at cannot be in the future."
        )
    normalized["reviewed_at"] = reviewed_at
    return normalized


def normalized_credentials(
    name: str, raw: Any, *, connection_mode: str, default_namespace: str
) -> dict[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise RenderError(f"{name}.credentials must be a mapping.")
    unknown = sorted(set(raw) - {"kubernetes_secret", "linux_env"})
    if unknown:
        raise RenderError(
            f"{name}.credentials contains unsupported keys: {', '.join(unknown)}."
        )

    prefix = env_prefix(name)
    linux_env = raw.get("linux_env") or {}
    if not isinstance(linux_env, dict):
        raise RenderError(f"{name}.credentials.linux_env must be a mapping.")
    unknown_linux = sorted(
        set(linux_env) - {"datasource_var", "password_var", "username_var"}
    )
    if unknown_linux:
        raise RenderError(
            f"{name}.credentials.linux_env contains unsupported keys: "
            + ", ".join(unknown_linux)
        )
    username_var = env_name(
        linux_env.get("username_var") or f"{prefix}_USERNAME",
        label=f"{name}.credentials.linux_env.username_var",
    )
    password_var = env_name(
        linux_env.get("password_var") or f"{prefix}_PASSWORD",
        label=f"{name}.credentials.linux_env.password_var",
    )
    datasource_var = env_name(
        linux_env.get("datasource_var") or f"{prefix}_DATASOURCE",
        label=f"{name}.credentials.linux_env.datasource_var",
    )
    for label, value in {
        "username_var": username_var,
        "password_var": password_var,
        "datasource_var": datasource_var,
    }.items():
        if not value.startswith("DBMON_"):
            raise RenderError(
                f"{name}.credentials.linux_env.{label} must start with DBMON_ to avoid "
                "colliding with collector, chart, Kubernetes, or system environment names."
            )

    k8s_secret = raw.get("kubernetes_secret") or {}
    if not isinstance(k8s_secret, dict):
        raise RenderError(f"{name}.credentials.kubernetes_secret must be a mapping.")
    unknown_secret = sorted(
        set(k8s_secret)
        - {"datasource_key", "name", "namespace", "password_key", "username_key"}
    )
    if unknown_secret:
        raise RenderError(
            f"{name}.credentials.kubernetes_secret contains unsupported keys: "
            + ", ".join(unknown_secret)
        )
    secret_name = dns_name(
        k8s_secret.get("name") or f"dbmon-{name.replace('_', '-')}",
        label=f"{name}.credentials.kubernetes_secret.name",
    )
    secret_namespace = dns_name(
        k8s_secret.get("namespace") or default_namespace,
        label=f"{name}.credentials.kubernetes_secret.namespace",
    )
    username_key = secret_key(
        k8s_secret.get("username_key") or "username",
        label=f"{name}.credentials.kubernetes_secret.username_key",
    )
    password_key = secret_key(
        k8s_secret.get("password_key") or "password",
        label=f"{name}.credentials.kubernetes_secret.password_key",
    )
    datasource_key = secret_key(
        k8s_secret.get("datasource_key") or "datasource",
        label=f"{name}.credentials.kubernetes_secret.datasource_key",
    )

    return {
        "username_var": username_var,
        "password_var": password_var,
        "datasource_var": datasource_var,
        "kubernetes_secret": {
            "name": secret_name,
            "namespace": secret_namespace,
            "username_key": username_key,
            "password_key": password_key,
            "datasource_key": datasource_key,
        },
        "mode": connection_mode,
    }


def normalized_advanced(target_type: str, raw: Any) -> dict[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise RenderError("target.advanced must be a mapping when provided.")
    allowed = {
        "metrics",
        "resource_attributes",
        "query_sample_collection",
        "top_query_collection",
        "initial_delay",
        "timeout",
    }
    if target_type == "postgresql":
        allowed |= {"exclude_databases", "connection_pool", "transport", "tls"}
    if target_type in {"mysql", "mariadb"}:
        allowed |= {
            "database",
            "statement_events",
            "transport",
            "allow_native_passwords",
            "tls",
        }
    if target_type == "oracledb":
        allowed |= {"session_wait_event_collection"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise RenderError(
            f"{target_type} target.advanced contains unsupported keys: {', '.join(unknown)}."
        )
    reject_inline_secret_fields(raw, "target.advanced")
    normalized = dict(raw)
    for section in ("metrics", "resource_attributes"):
        value = normalized.get(section)
        if value is not None and not isinstance(value, dict):
            raise RenderError(f"target.advanced.{section} must be a mapping.")
    return normalized


def validate_connection_fields(target: dict[str, Any]) -> None:
    target_type = target["type"]
    name = target["name"]
    mode = target["connection_mode"]
    if mode not in {"direct", "datasource", "windows"}:
        raise RenderError(
            f"{target_type}/{name} connection_mode must be direct, datasource, or windows."
        )
    if mode == "windows":
        if target_type != "sqlserver":
            raise RenderError(
                f"{target_type}/{name} cannot use Windows Performance Counters mode."
            )
        if not target.get("computer_name") or not target.get("instance_name"):
            raise RenderError(
                f"sqlserver/{name} Windows mode requires computer_name and instance_name."
            )
        validate_hostname_or_ip(
            str(target["computer_name"]),
            label=f"sqlserver/{name} computer_name",
        )
        validate_identifier(
            str(target["instance_name"]),
            label=f"sqlserver/{name} instance_name",
        )
        supplied = sorted(
            field for field in {"server", "port"} if target.get(field) not in (None, "")
        )
        if supplied:
            raise RenderError(
                f"sqlserver/{name} Windows Performance Counters mode ignores fields: "
                + ", ".join(supplied)
            )
        if any(target["events"].values()):
            raise RenderError(
                f"sqlserver/{name} Windows Performance Counters mode cannot emit DBMon "
                "query events; set query_sample and top_query false or use a direct/database "
                "datasource connection for complete Database Monitoring."
            )
    elif mode == "datasource":
        if target_type not in {"sqlserver", "oracledb"}:
            raise RenderError(
                f"{target_type}/{name} datasource mode is not supported by this receiver."
            )
        direct_fields = (
            {"server", "port", "computer_name", "instance_name"}
            if target_type == "sqlserver"
            else {"endpoint", "service"}
        )
        supplied = sorted(
            field for field in direct_fields if target.get(field) not in (None, "")
        )
        if supplied:
            raise RenderError(
                f"{target_type}/{name} datasource mode ignores direct fields: "
                + ", ".join(supplied)
            )
    elif target_type == "postgresql":
        if not target.get("endpoint"):
            raise RenderError(f"postgresql/{name} requires endpoint.")
        databases = target.get("databases")
        if databases is not None and (
            not isinstance(databases, list)
            or not all(isinstance(item, str) and item for item in databases)
        ):
            raise RenderError(
                f"postgresql/{name} databases must be a list of nonempty names when provided."
            )
        for database in databases or []:
            validate_identifier(
                database,
                label=f"postgresql/{name} database",
                max_length=128,
            )
    elif target_type == "sqlserver":
        if not target.get("server"):
            raise RenderError(f"sqlserver/{name} requires server.")
        validate_hostname_or_ip(str(target["server"]), label=f"sqlserver/{name} server")
        port = integer_value(target.get("port", 1433), label=f"sqlserver/{name} port")
        if not 1 <= port <= 65535:
            raise RenderError(f"sqlserver/{name} port must be between 1 and 65535.")
        if bool(target.get("instance_name")) != bool(target.get("computer_name")):
            raise RenderError(
                f"sqlserver/{name} instance_name and computer_name must be specified together."
            )
        if target.get("computer_name"):
            validate_hostname_or_ip(
                str(target["computer_name"]),
                label=f"sqlserver/{name} computer_name",
            )
            validate_identifier(
                str(target["instance_name"]),
                label=f"sqlserver/{name} instance_name",
            )
    elif target_type == "oracledb":
        if not target.get("endpoint"):
            raise RenderError(f"oracledb/{name} requires endpoint.")
        if not target.get("service"):
            raise RenderError(f"oracledb/{name} requires service.")
        validate_identifier(
            str(target["service"]), label=f"oracledb/{name} service", max_length=128
        )
    elif target_type in {"mysql", "mariadb"}:
        if not target.get("endpoint"):
            raise RenderError(f"{target_type}/{name} requires endpoint.")

    if mode == "direct" and target_type in {
        "postgresql",
        "oracledb",
        "mysql",
        "mariadb",
    }:
        validate_host_port(
            str(target.get("endpoint") or ""), label=f"{target_type}/{name} endpoint"
        )

    interval = str(target.get("collection_interval") or "10s")
    if interval != "10s":
        raise RenderError(
            f"{target_type}/{name} collection_interval must remain 10s for DBMon production support."
        )
    validate_advanced(target)


def validate_hostname_or_ip(value: str, *, label: str) -> None:
    """Accept a literal IP or conservative DNS hostname, never DSN syntax."""
    candidate = value.strip()
    try:
        ipaddress.ip_address(candidate.strip("[]"))
        return
    except ValueError:
        pass
    if len(candidate) > 253 or not re.fullmatch(
        r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", candidate
    ):
        raise RenderError(
            f"{label} must be a hostname or IP address only; datasource options, "
            "delimiters, whitespace, and credentials are forbidden."
        )
    if any(
        not part or len(part) > 63 or part.startswith("-") or part.endswith("-")
        for part in candidate.split(".")
    ):
        raise RenderError(f"{label} is not a valid DNS hostname.")


def validate_identifier(value: str, *, label: str, max_length: int = 64) -> None:
    if not re.fullmatch(rf"[A-Za-z0-9][A-Za-z0-9_.#$-]{{0,{max_length - 1}}}", value):
        raise RenderError(
            f"{label} must be 1..{max_length} safe identifier characters; "
            "whitespace, connection delimiters, and credentials are forbidden."
        )


def normalized_validation_filters(
    target: dict[str, Any], raw: Any
) -> list[dict[str, str]]:
    """Build a non-secret, target-specific SignalFlow identity filter."""
    target_type = target["type"]
    name = target["name"]
    if raw is None:
        if target["connection_mode"] == "datasource":
            raise RenderError(
                f"{target_type}/{name} datasource mode requires validation_filters with "
                "the expected non-secret service.instance.id so API validation cannot "
                "pass on another database."
            )
        if target["connection_mode"] == "windows":
            raw = {
                "sqlserver.computer.name": str(target["computer_name"]),
                "sqlserver.instance.name": str(target["instance_name"]),
            }
        elif target_type == "postgresql":
            raw = {
                "service.instance.id": service_id_from_endpoint(
                    target["endpoint"], target_type=target_type, name=name
                )
            }
        elif target_type == "sqlserver":
            if is_loopback_host(str(target["server"])):
                raise RenderError(
                    f"sqlserver/{name} uses a loopback server, whose service.instance.id "
                    "contains the collector hostname; set validation_filters explicitly."
                )
            raw = {
                "service.instance.id": f"{target['server']}:{int(target.get('port') or 1433)}"
            }
        elif target_type == "oracledb":
            raw = {
                "service.instance.id": (
                    f"{service_id_from_endpoint(target['endpoint'], target_type=target_type, name=name)}/{target['service']}"
                )
            }
        else:
            # The v0.155 MySQL identity processor copies the endpoint verbatim,
            # including IPv6 brackets.
            raw = {"service.instance.id": str(target["endpoint"])}
    if not isinstance(raw, dict) or not raw:
        raise RenderError(
            f"{target_type}/{name} validation_filters must be a nonempty mapping."
        )
    filters: list[dict[str, str]] = []
    for key, value in sorted(raw.items(), key=lambda item: str(item[0])):
        key_text = str(key).strip()
        if key_text not in RESOURCE_ATTRIBUTES[target_type]:
            raise RenderError(
                f"{target_type}/{name} validation filter {key_text!r} is not a known "
                "v0.155 receiver resource attribute."
            )
        normalized_key = re.sub(r"[^a-z0-9]", "", key_text.lower())
        if any(
            secret in normalized_key
            for secret in ("password", "secret", "token", "credential", "key")
        ):
            raise RenderError(
                f"{target_type}/{name} validation filter keys cannot name secrets."
            )
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise RenderError(
                f"{target_type}/{name} validation filter {key_text!r} must have a scalar value."
            )
        value_text = str(value).strip()
        if (
            not value_text
            or len(value_text) > 1024
            or any(
                ord(character) < 32 or ord(character) == 127 for character in value_text
            )
        ):
            raise RenderError(
                f"{target_type}/{name} validation filter {key_text!r} has an invalid value."
            )
        if any(
            re.search(pattern, value_text)
            for pattern in (
                r"(?i)(?:password|passwd|token|secret|authorization|api[_-]?key)\s*[:=]",
                r"(?i)^[a-z][a-z0-9+.-]*://[^/@\s]+:[^/@\s]+@",
                r"AKIA[0-9A-Z]{16}",
                r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
                r"^[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}$",
            )
        ):
            raise RenderError(
                f"{target_type}/{name} validation filter {key_text!r} resembles "
                "secret material; value suppressed."
            )
        filters.append({"key": key_text, "value": value_text})
    keys = {item["key"] for item in filters}
    identity_ok = "service.instance.id" in keys or (
        target["connection_mode"] == "windows"
        and {"sqlserver.computer.name", "sqlserver.instance.name"} <= keys
    )
    if not identity_ok:
        raise RenderError(
            f"{target_type}/{name} validation_filters must include service.instance.id "
            "(or both SQL Server Windows computer and instance names)."
        )
    return filters


def service_id_from_endpoint(value: Any, *, target_type: str, name: str) -> str:
    host, port = str(value).rsplit(":", 1)
    if is_loopback_host(host.strip("[]")):
        raise RenderError(
            f"{target_type}/{name} uses a loopback endpoint, whose service.instance.id "
            "contains the collector hostname; set validation_filters explicitly."
        )
    return f"{host.strip('[]')}:{port}"


def is_loopback_host(value: str) -> bool:
    if value.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value.strip("[]")).is_loopback
    except ValueError:
        return False


def validate_host_port(value: str, *, label: str) -> None:
    match = re.fullmatch(
        r"(?:\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9][A-Za-z0-9.-]*):(\d{1,5})", value
    )
    if not match or not 1 <= int(match.group(1)) <= 65535:
        raise RenderError(
            f"{label} must be a hostname-or-IP and port, for example db.example:5432."
        )


def validate_advanced(target: dict[str, Any]) -> None:
    target_type = target["type"]
    name = target["name"]
    advanced = target["advanced"]
    for field in ("initial_delay", "timeout"):
        if (
            field in advanced
            and duration_seconds(
                advanced[field], label=f"{target_type}/{name} advanced.{field}"
            )
            <= 0
        ):
            raise RenderError(
                f"{target_type}/{name} advanced.{field} must be positive."
            )
    if "transport" in advanced and advanced["transport"] != "tcp":
        raise RenderError(
            f"{target_type}/{name} advanced.transport must be tcp; Unix sockets are "
            "outside the audited production target contract."
        )
    if "exclude_databases" in advanced and (
        not isinstance(advanced["exclude_databases"], list)
        or not all(
            isinstance(item, str) and item for item in advanced["exclude_databases"]
        )
    ):
        raise RenderError(
            f"{target_type}/{name} advanced.exclude_databases must be a list of names."
        )
    pool = advanced.get("connection_pool")
    if pool is not None:
        if not isinstance(pool, dict) or set(pool) - {
            "max_idle",
            "max_idle_time",
            "max_lifetime",
            "max_open",
        }:
            raise RenderError(
                f"{target_type}/{name} advanced.connection_pool has unsupported settings."
            )
        for field in {"max_idle", "max_open"} & set(pool):
            if (
                integer_value(
                    pool[field], label=f"{target_type}/{name} connection_pool.{field}"
                )
                < 0
            ):
                raise RenderError(
                    f"{target_type}/{name} connection_pool.{field} cannot be negative."
                )
        for field in {"max_idle_time", "max_lifetime"} & set(pool):
            if (
                duration_seconds(
                    pool[field], label=f"{target_type}/{name} connection_pool.{field}"
                )
                < 0
            ):
                raise RenderError(
                    f"{target_type}/{name} connection_pool.{field} cannot be negative."
                )
    statements = advanced.get("statement_events")
    if statements is not None:
        if not isinstance(statements, dict) or set(statements) - {
            "digest_text_limit",
            "limit",
            "time_limit",
        }:
            raise RenderError(
                f"{target_type}/{name} advanced.statement_events has unsupported settings."
            )
        for field in {"digest_text_limit", "limit"} & set(statements):
            if (
                integer_value(
                    statements[field],
                    label=f"{target_type}/{name} statement_events.{field}",
                )
                <= 0
            ):
                raise RenderError(
                    f"{target_type}/{name} statement_events.{field} must be positive."
                )
        if (
            "time_limit" in statements
            and duration_seconds(
                statements["time_limit"],
                label=f"{target_type}/{name} statement_events.time_limit",
            )
            <= 0
        ):
            raise RenderError(
                f"{target_type}/{name} statement_events.time_limit must be positive."
            )
    metrics = advanced.get("metrics") or {}
    metric_prefix = (
        "mysql." if target_type in {"mysql", "mariadb"} else f"{target_type}."
    )
    normalized_metrics: dict[str, dict[str, bool]] = {}
    for metric, value in metrics.items():
        if str(metric) not in METRIC_INVENTORY[target_type]:
            raise RenderError(
                f"{target_type}/{name} metric {metric!r} is not in the exact v0.155 "
                f"{metric_prefix!r} receiver inventory."
            )
        if isinstance(value, bool):
            normalized_metrics[str(metric)] = {"enabled": value}
        elif (
            isinstance(value, dict)
            and set(value) == {"enabled"}
            and isinstance(value.get("enabled"), bool)
        ):
            normalized_metrics[str(metric)] = {"enabled": value["enabled"]}
        else:
            raise RenderError(
                f"{target_type}/{name} metric {metric!r} must be a boolean or an exact "
                "enabled: true|false mapping."
            )
    if normalized_metrics:
        validation_metric = DEFAULT_VALIDATION_METRICS[target_type]
        if normalized_metrics.get(validation_metric) == {"enabled": False}:
            raise RenderError(
                f"{target_type}/{name} cannot disable validation metric "
                f"{validation_metric!r}; tenant proof requires it."
            )
        advanced["metrics"] = normalized_metrics

    resource_attributes = advanced.get("resource_attributes") or {}
    for attribute, value in resource_attributes.items():
        if attribute not in RECEIVER_RESOURCE_ATTRIBUTES[target_type]:
            raise RenderError(
                f"{target_type}/{name} resource attribute {attribute!r} is not in the v0.155 schema."
            )
        if not isinstance(value, dict) or not isinstance(value.get("enabled"), bool):
            raise RenderError(
                f"{target_type}/{name} resource attribute {attribute!r} requires enabled: true|false."
            )
        extra = set(value) - (
            {"enabled", "override_value"} if target_type == "sqlserver" else {"enabled"}
        )
        if extra:
            raise RenderError(
                f"{target_type}/{name} resource attribute {attribute!r} has unsupported fields: {sorted(extra)}."
            )
        expected_override_type = SQLSERVER_OVERRIDE_TYPES.get(attribute, str)
        if "override_value" in value and not isinstance(
            value["override_value"], expected_override_type
        ):
            raise RenderError(
                f"sqlserver/{name} resource attribute {attribute!r} override_value must be "
                f"{expected_override_type.__name__}."
            )

    tls = advanced.get("tls")
    if target_type in {"postgresql", "mysql", "mariadb"}:
        if not isinstance(tls, dict):
            raise RenderError(
                f"{target_type}/{name} requires advanced.tls with certificate verification "
                "for production; use insecure: false and insecure_skip_verify: false."
            )
        unknown_tls = sorted(set(tls) - TLS_KEYS)
        if unknown_tls:
            raise RenderError(
                f"{target_type}/{name} advanced.tls has unsupported fields: {', '.join(unknown_tls)}."
            )
        if target_type == "postgresql":
            rejected_pg_tls = sorted(
                set(tls)
                & {
                    "max_version",
                    "min_version",
                    "server_name_override",
                }
            )
            if rejected_pg_tls:
                raise RenderError(
                    f"postgresql/{name} receiver v0.155 does not support TLS fields: "
                    f"{', '.join(rejected_pg_tls)}."
                )
        if (
            tls.get("insecure") is not False
            or tls.get("insecure_skip_verify") is not False
        ):
            raise RenderError(
                f"{target_type}/{name} advanced.tls must explicitly set insecure: false and "
                "insecure_skip_verify: false."
            )
        for key in {
            "include_insecure_cipher_suites",
            "include_system_ca_certs_pool",
        }:
            if key in tls and not isinstance(tls[key], bool):
                raise RenderError(
                    f"{target_type}/{name} advanced.tls.{key} must be a boolean."
                )
        if tls.get("include_insecure_cipher_suites") not in (None, False):
            raise RenderError(
                f"{target_type}/{name} advanced.tls.include_insecure_cipher_suites "
                "must remain false for a production packet."
            )
        if "cipher_suites" in tls and (
            not isinstance(tls["cipher_suites"], list)
            or not tls["cipher_suites"]
            or not all(
                isinstance(item, str) and re.fullmatch(r"TLS_[A-Z0-9_]+", item)
                for item in tls["cipher_suites"]
            )
        ):
            raise RenderError(
                f"{target_type}/{name} advanced.tls.cipher_suites must be a "
                "nonempty list of TLS_* suite names."
            )
        if "curve_preferences" in tls and (
            not isinstance(tls["curve_preferences"], list)
            or not tls["curve_preferences"]
            or not all(
                isinstance(item, str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", item)
                for item in tls["curve_preferences"]
            )
        ):
            raise RenderError(
                f"{target_type}/{name} advanced.tls.curve_preferences must be a "
                "nonempty list of Go TLS curve names."
            )
        for key in TLS_KEYS - {
            "cipher_suites",
            "curve_preferences",
            "include_insecure_cipher_suites",
            "insecure",
            "insecure_skip_verify",
            "include_system_ca_certs_pool",
        }:
            if key in tls and not isinstance(tls[key], str):
                raise RenderError(
                    f"{target_type}/{name} advanced.tls.{key} must be a string."
                )

    if "allow_native_passwords" in advanced and not isinstance(
        advanced["allow_native_passwords"], bool
    ):
        raise RenderError(
            f"{target_type}/{name} advanced.allow_native_passwords must be a boolean."
        )
    if "database" in advanced:
        validate_identifier(
            str(advanced["database"]),
            label=f"{target_type}/{name} advanced.database",
            max_length=128,
        )

    query = advanced.get("query_sample_collection") or {}
    if query:
        if not isinstance(query, dict) or set(query) - {
            "max_rows_per_query",
            "allowed_comment_keys",
        }:
            raise RenderError(
                f"{target_type}/{name} query_sample_collection contains unsupported settings."
            )
        max_rows = integer_value(
            query.get("max_rows_per_query", 100),
            label=f"{target_type}/{name} query_sample_collection.max_rows_per_query",
        )
        if not 1 <= max_rows <= 100:
            raise RenderError(
                f"{target_type}/{name} query_sample_collection.max_rows_per_query must be 1..100."
            )
        validate_comment_keys(target_type, name, query.get("allowed_comment_keys"))

    top = advanced.get("top_query_collection") or {}
    if top:
        allowed_top_by_type = {
            "postgresql": {
                "collection_interval",
                "max_rows_per_query",
                "top_n_query",
                "max_explain_each_interval",
                "query_plan_cache_size",
                "query_plan_cache_ttl",
            },
            "sqlserver": {
                "collection_interval",
                "lookback_time",
                "max_query_sample_count",
                "top_query_count",
            },
            "oracledb": {
                "allowed_comment_keys",
                "collection_interval",
                "max_query_sample_count",
                "top_query_count",
            },
            "mysql": {
                "collection_interval",
                "lookback_time",
                "max_query_sample_count",
                "query_plan_cache_size",
                "query_plan_cache_ttl",
                "top_query_count",
            },
            "mariadb": {
                "collection_interval",
                "lookback_time",
                "max_query_sample_count",
                "query_plan_cache_size",
                "query_plan_cache_ttl",
                "top_query_count",
            },
        }
        allowed_top = allowed_top_by_type[target_type]
        if not isinstance(top, dict) or set(top) - allowed_top:
            raise RenderError(
                f"{target_type}/{name} top_query_collection contains unsupported settings."
            )
        if (
            "collection_interval" in top
            and duration_seconds(
                top["collection_interval"],
                label=f"{target_type}/{name} top_query_collection.collection_interval",
            )
            < 10
        ):
            raise RenderError(
                f"{target_type}/{name} top_query_collection.collection_interval must be at least 10s."
            )
        if target_type != "postgresql":
            max_samples = integer_value(
                top.get("max_query_sample_count", 1000),
                label=f"{target_type}/{name} top_query_collection.max_query_sample_count",
            )
            if not 1 <= max_samples <= 10000:
                raise RenderError(
                    f"{target_type}/{name} top_query_collection.max_query_sample_count "
                    "must be 1..10000."
                )
            default_top_count = 250 if target_type == "sqlserver" else 200
            top_count = integer_value(
                top.get("top_query_count", default_top_count),
                label=f"{target_type}/{name} top_query_collection.top_query_count",
            )
            engine_max = 10000 if target_type == "sqlserver" else 200
            if not 1 <= top_count <= engine_max or top_count > max_samples:
                raise RenderError(
                    f"{target_type}/{name} top_query_collection.top_query_count must be "
                    f"1..{engine_max} and no greater than max_query_sample_count."
                )
        validate_comment_keys(target_type, name, top.get("allowed_comment_keys"))
        if "lookback_time" in top:
            if target_type in {"mysql", "mariadb"}:
                if (
                    integer_value(
                        top["lookback_time"],
                        label=f"{target_type}/{name} top_query_collection.lookback_time",
                    )
                    <= 0
                ):
                    raise RenderError(
                        f"{target_type}/{name} lookback_time must be positive seconds."
                    )
            elif (
                duration_seconds(
                    top["lookback_time"],
                    label=f"{target_type}/{name} top_query_collection.lookback_time",
                )
                <= 0
            ):
                raise RenderError(
                    f"{target_type}/{name} lookback_time must be positive."
                )
        for field in {
            "max_rows_per_query",
            "top_n_query",
            "max_explain_each_interval",
            "query_plan_cache_size",
        } & set(top):
            if (
                integer_value(
                    top[field],
                    label=f"{target_type}/{name} top_query_collection.{field}",
                )
                < 1
            ):
                raise RenderError(
                    f"{target_type}/{name} top_query_collection.{field} must be positive."
                )
        if (
            "query_plan_cache_ttl" in top
            and duration_seconds(
                top["query_plan_cache_ttl"],
                label=f"{target_type}/{name} top_query_collection.query_plan_cache_ttl",
            )
            <= 0
        ):
            raise RenderError(
                f"{target_type}/{name} query_plan_cache_ttl must be positive."
            )

    wait = advanced.get("session_wait_event_collection") or {}
    if wait:
        if (
            target_type != "oracledb"
            or not isinstance(wait, dict)
            or set(wait) - {"max_rows_per_query"}
        ):
            raise RenderError(
                f"{target_type}/{name} has invalid session_wait_event_collection settings."
            )
        if (
            not 1
            <= integer_value(
                wait.get("max_rows_per_query", 100),
                label=f"oracledb/{name} session_wait_event_collection.max_rows_per_query",
            )
            <= 100
        ):
            raise RenderError(
                f"oracledb/{name} session_wait_event_collection.max_rows_per_query must be 1..100."
            )


def validate_comment_keys(target_type: str, name: str, value: Any) -> None:
    if value is None:
        return
    if target_type != "oracledb" or not isinstance(value, list):
        raise RenderError(
            f"{target_type}/{name} allowed_comment_keys is supported only as an Oracle list."
        )
    for key in value:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", str(key)):
            raise RenderError(
                f"oracledb/{name} has invalid allowed_comment_key {key!r}."
            )


def receiver_config(target: dict[str, Any]) -> dict[str, Any]:
    creds = target["credentials"]
    config: dict[str, Any] = {
        "collection_interval": "10s",
    }
    if target["connection_mode"] == "datasource":
        config["datasource"] = f"${{env:{creds['datasource_var']}}}"
    elif target["connection_mode"] != "windows":
        config["username"] = f"${{env:{creds['username_var']}}}"
        config["password"] = f"${{env:{creds['password_var']}}}"
    events = target["events"]
    config["events"] = {
        "db.server.query_sample": {"enabled": events["query_sample"]},
        "db.server.top_query": {"enabled": events["top_query"]},
    }
    config["query_sample_collection"] = {"max_rows_per_query": 100}
    if target["type"] == "oracledb":
        config["events"]["db.server.session.wait_sample"] = {
            "enabled": events["session_wait_sample"]
        }

    if target["connection_mode"] == "windows":
        config["computer_name"] = str(target["computer_name"])
        config["instance_name"] = str(target["instance_name"])
        config["resource_attributes"] = {
            "sqlserver.computer.name": {"enabled": True},
            "sqlserver.instance.name": {"enabled": True},
        }
    elif target["type"] == "postgresql":
        config["endpoint"] = str(target["endpoint"])
        if target.get("databases") is not None:
            config["databases"] = [str(item) for item in target["databases"]]
    elif target["type"] == "sqlserver" and target["connection_mode"] == "direct":
        config["server"] = str(target["server"])
        config["port"] = int(target.get("port") or 1433)
        if target.get("instance_name"):
            config["instance_name"] = str(target["instance_name"])
            config["computer_name"] = str(target["computer_name"])
        config["resource_attributes"] = {
            "sqlserver.computer.name": {"enabled": True},
            "sqlserver.instance.name": {"enabled": True},
        }
        if target["platform"] in {"azure-managed-instance", "azure-sql-database"}:
            config["metrics"] = {"sqlserver.database.count": {"enabled": False}}
    elif target["type"] == "oracledb" and target["connection_mode"] == "direct":
        config["endpoint"] = str(target["endpoint"])
        config["service"] = str(target["service"])
        config["resource_attributes"] = {"oracledb.instance.name": {"enabled": True}}
    elif target["type"] in {"mysql", "mariadb"}:
        config["endpoint"] = str(target["endpoint"])
        config["resource_attributes"] = {"mysql.instance.endpoint": {"enabled": True}}

    # These attributes drive stable product identity and built-in content for
    # both discrete and datasource connection modes.
    if target["type"] == "sqlserver":
        config["resource_attributes"] = deep_merge(
            {
                "sqlserver.computer.name": {"enabled": True},
                "sqlserver.instance.name": {"enabled": True},
            },
            config.get("resource_attributes") or {},
        )
        if target["platform"] in {"azure-managed-instance", "azure-sql-database"}:
            config["metrics"] = deep_merge(
                {"sqlserver.database.count": {"enabled": False}},
                config.get("metrics") or {},
            )
    if target["type"] == "oracledb":
        config["resource_attributes"] = deep_merge(
            {"oracledb.instance.name": {"enabled": True}},
            config.get("resource_attributes") or {},
        )

    config = deep_merge(config, target["advanced"])
    return config


def collector_settings(
    spec: dict[str, Any], args: argparse.Namespace
) -> dict[str, Any]:
    collector = spec.get("collector") or {}
    if not isinstance(collector, dict):
        raise RenderError("spec.collector must be a mapping when provided.")
    unknown = sorted(
        set(collector)
        - {
            "chart_version",
            "cpu_limit",
            "kube_context",
            "memory_mib",
            "namespace",
            "release_name",
            "version",
        }
    )
    if unknown:
        raise RenderError(
            "spec.collector contains unsupported settings: " + ", ".join(unknown)
        )
    release_name = dns_name(
        collector.get("release_name") or "splunk-otel-collector",
        label="collector.release_name",
    )
    version = args.collector_version or str(
        collector.get("version") or DEFAULT_COLLECTOR_VERSION
    )
    parsed_version = parse_semver(version)
    version = f"v{parsed_version[0]}.{parsed_version[1]}.{parsed_version[2]}"
    if version not in SUPPORTED_COLLECTOR_VERSIONS:
        raise RenderError(
            f"Collector {version} has not been production-audited by this skill. "
            f"Supported: {', '.join(sorted(SUPPORTED_COLLECTOR_VERSIONS))}."
        )
    chart_version = str(collector.get("chart_version") or version.lstrip("v"))
    parsed_chart = parse_semver(chart_version)
    chart_version = f"{parsed_chart[0]}.{parsed_chart[1]}.{parsed_chart[2]}"
    if chart_version != version.lstrip("v"):
        raise RenderError(
            f"collector.chart_version {chart_version} must equal collector {version} for an "
            "audited receiver/component set."
        )
    namespace = dns_name(
        collector.get("namespace") or "splunk-otel", label="collector.namespace"
    )
    raw_memory = collector.get("memory_mib", 0)
    memory_mib = integer_value(raw_memory, label="collector.memory_mib")
    if memory_mib <= 0:
        raise RenderError(
            "collector.memory_mib must be explicitly set from the reviewed sizing evidence."
        )
    cpu_limit = str(collector.get("cpu_limit") or "")
    if not cpu_limit:
        raise RenderError(
            "collector.cpu_limit must be explicitly set from the reviewed sizing evidence."
        )
    if (
        not re.fullmatch(r"(?:[1-9]\d*m|[1-9]\d*(?:\.\d+)?|0\.\d+)", cpu_limit)
        or (not cpu_limit.endswith("m") and float(cpu_limit) <= 0)
    ):
        raise RenderError(
            "collector.cpu_limit must be a positive Kubernetes CPU quantity."
        )
    kube_context = str(collector.get("kube_context") or "").strip()
    if kube_context and not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,252}", kube_context
    ):
        raise RenderError("collector.kube_context contains unsafe characters.")
    return {
        "version": version,
        "chart_version": chart_version,
        "namespace": namespace,
        "release_name": release_name,
        "memory_mib": memory_mib,
        "cpu_limit": cpu_limit,
        "kube_context": kube_context,
    }


def output_settings(spec: dict[str, Any]) -> dict[str, bool]:
    raw = spec.get("outputs") or {}
    if not isinstance(raw, dict):
        raise RenderError("spec.outputs must be a mapping when provided.")
    unknown = sorted(set(raw) - {"kubernetes", "linux", "windows"})
    if unknown:
        raise RenderError("spec.outputs contains unsupported keys: " + ", ".join(unknown))
    return {
        "kubernetes": bool_value(
            raw.get("kubernetes"), label="outputs.kubernetes", default=True
        ),
        "linux": bool_value(raw.get("linux"), label="outputs.linux", default=True),
        "windows": bool_value(
            raw.get("windows"), label="outputs.windows", default=True
        ),
    }


def apply_sizing(collector: dict[str, Any], targets: list[dict[str, Any]]) -> None:
    required_memory = 500
    if any(target["type"] == "oracledb" for target in targets):
        required_memory = max(required_memory, 512)
    if any(target["type"] == "sqlserver" for target in targets):
        required_memory = max(required_memory, 2048)
    configured = int(collector.get("memory_mib") or 0)
    if configured and configured < required_memory:
        raise RenderError(
            f"collector.memory_mib={configured} is below the documented {required_memory} MiB "
            "minimum for the selected DBMon targets."
        )
    collector["memory_mib"] = configured or required_memory
    if not collector.get("cpu_limit"):
        collector["cpu_limit"] = "2" if required_memory >= 2048 else "500m"


def overlay_values(
    *,
    realm: str,
    cluster_name: str,
    distribution: str,
    collector: dict[str, Any],
    targets: list[dict[str, Any]],
) -> dict[str, Any]:
    receivers = {target["receiver_id"]: receiver_config(target) for target in targets}
    receiver_ids = [target["receiver_id"] for target in targets]
    extra_envs = db_secret_envs(targets)
    values: dict[str, Any] = {
        "image": {
            "otelcol": {
                "repository": AUDITED_COLLECTOR_REPOSITORY,
                "tag": (
                    f"{collector['version'].lstrip('v')}@"
                    f"{AUDITED_COLLECTOR_MANIFEST_DIGEST}"
                ),
            }
        },
        "clusterReceiver": {
            "enabled": True,
            "extraEnvs": extra_envs,
            "resources": {
                "limits": {
                    "cpu": collector["cpu_limit"],
                    "memory": f"{collector['memory_mib']}Mi",
                },
                "requests": {
                    "cpu": collector["cpu_limit"],
                    "memory": f"{collector['memory_mib']}Mi",
                },
            },
            "config": collector_config(
                realm=realm,
                receivers=receivers,
                receiver_ids=receiver_ids,
                mysql_receiver_ids=[
                    target["receiver_id"]
                    for target in targets
                    if target["type"] in {"mysql", "mariadb"}
                ],
                token_env="SPLUNK_OBSERVABILITY_ACCESS_TOKEN",
                memory_mib=collector["memory_mib"],
            ),
        },
    }
    # The base collector skill owns clusterName/distribution/realm. Omitting
    # those values prevents this DBMon overlay from relabeling production data
    # or replacing cloud-specific resource detectors during a merge.
    return values


def collector_config(
    *,
    realm: str,
    receivers: dict[str, Any],
    receiver_ids: list[str],
    mysql_receiver_ids: list[str],
    token_env: str,
    memory_mib: int,
) -> dict[str, Any]:
    exporters: dict[str, Any] = {
        "otlp_http/dbmon": {
            "headers": {
                "X-SF-Token": f"${{env:{token_env}}}",
                "X-splunk-instrumentation-library": "dbmon",
            },
            "logs_endpoint": f"https://ingest.{realm}.observability.splunkcloud.com/v3/event",
            "sending_queue": {
                "batch": {
                    "flush_timeout": "15s",
                    "max_size": 10485760,
                    "sizer": "bytes",
                }
            },
        }
    }
    exporters["signalfx/dbmon"] = {
        "access_token": f"${{env:{token_env}}}",
        "realm": realm,
    }
    processors: dict[str, Any] = {
        "memory_limiter/dbmon": {
            "check_interval": "2s",
            "limit_mib": max(128, int(memory_mib * 0.8)),
        },
        "batch/dbmon": {},
        "resource_detection/dbmon": {
            "detectors": ["system"],
            "system": {"hostname_sources": ["os"]},
        },
    }
    if mysql_receiver_ids:
        processors["resource/mysql_service_instance_id"] = {
            "attributes": [
                {
                    "action": "insert",
                    "from_attribute": "mysql.instance.endpoint",
                    "key": "service.instance.id",
                }
            ]
        }
    core_receiver_ids = [
        item for item in receiver_ids if item not in mysql_receiver_ids
    ]
    pipelines: dict[str, Any] = {}
    if core_receiver_ids:
        suffix = "/dbmon_core" if mysql_receiver_ids else "/dbmon"
        pipelines[f"metrics{suffix}"] = {
            "receivers": core_receiver_ids,
            "processors": ["memory_limiter/dbmon", "batch/dbmon"],
            "exporters": ["signalfx/dbmon"],
        }
        pipelines[f"logs{suffix}"] = {
            "receivers": core_receiver_ids,
            "processors": ["memory_limiter/dbmon", "batch/dbmon"],
            "exporters": ["otlp_http/dbmon"],
        }
    if mysql_receiver_ids:
        suffix = "/dbmon_mysql" if core_receiver_ids else "/dbmon"
        pipelines[f"metrics{suffix}"] = {
            "receivers": mysql_receiver_ids,
            "processors": [
                "memory_limiter/dbmon",
                "batch/dbmon",
                "resource_detection/dbmon",
                "resource/mysql_service_instance_id",
            ],
            "exporters": ["signalfx/dbmon"],
        }
        pipelines[f"logs{suffix}"] = {
            "receivers": mysql_receiver_ids,
            "processors": [
                "memory_limiter/dbmon",
                "batch/dbmon",
                "resource/mysql_service_instance_id",
            ],
            "exporters": ["otlp_http/dbmon"],
        }
    return {
        "receivers": receivers,
        "processors": processors,
        "exporters": exporters,
        "service": {"pipelines": pipelines},
    }


def db_secret_envs(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    envs: list[dict[str, Any]] = []
    for target in targets:
        creds = target["credentials"]
        secret = creds["kubernetes_secret"]
        if target["connection_mode"] == "windows":
            continue
        keys = (
            [(creds["datasource_var"], secret["datasource_key"])]
            if target["connection_mode"] == "datasource"
            else [
                (creds["username_var"], secret["username_key"]),
                (creds["password_var"], secret["password_key"]),
            ]
        )
        for env_var, key in keys:
            envs.append(
                {
                    "name": env_var,
                    "valueFrom": {"secretKeyRef": {"name": secret["name"], "key": key}},
                }
            )
    return envs


def secret_stub(targets: list[dict[str, Any]]) -> str:
    blocks: list[str] = [
        "# Placeholder-only DB credential Secret manifests.",
        "# Replace values outside this repo or create equivalent Secrets with kubectl.",
        "# DO NOT commit real database credentials.",
    ]
    grouped: dict[tuple[str, str], dict[str, str]] = {}
    for target in targets:
        if target["connection_mode"] == "windows":
            continue
        secret = target["credentials"]["kubernetes_secret"]
        if target["connection_mode"] == "datasource":
            values = {secret["datasource_key"]: "PLACEHOLDER_DATASOURCE"}
        else:
            values = {
                secret["username_key"]: "PLACEHOLDER_USERNAME",
                secret["password_key"]: "PLACEHOLDER_PASSWORD",
            }
        grouped.setdefault((secret["namespace"], secret["name"]), {}).update(values)
    for (namespace, name), values in sorted(grouped.items()):
        secret_lines = [f"  {key}: {value}" for key, value in sorted(values.items())]
        blocks.append(
            "\n".join(
                [
                    "---",
                    "apiVersion: v1",
                    "kind: Secret",
                    "metadata:",
                    f"  name: {name}",
                    f"  namespace: {namespace}",
                    "type: Opaque",
                    "stringData:",
                    *secret_lines,
                ]
            )
        )
    return "\n".join(blocks) + "\n"


def standalone_config(
    realm: str, collector: dict[str, Any], targets: list[dict[str, Any]]
) -> dict[str, Any]:
    receivers = {target["receiver_id"]: receiver_config(target) for target in targets}
    config = collector_config(
        realm=realm,
        receivers=receivers,
        receiver_ids=[target["receiver_id"] for target in targets],
        mysql_receiver_ids=[
            target["receiver_id"]
            for target in targets
            if target["type"] in {"mysql", "mariadb"}
        ],
        token_env="SPLUNK_ACCESS_TOKEN",
        memory_mib=collector["memory_mib"],
    )
    return config


def collector_fragment(
    realm: str,
    collector: dict[str, Any],
    targets: list[dict[str, Any]],
    *,
    token_env: str,
) -> dict[str, Any]:
    receivers = {target["receiver_id"]: receiver_config(target) for target in targets}
    return collector_config(
        realm=realm,
        receivers=receivers,
        receiver_ids=[target["receiver_id"] for target in targets],
        mysql_receiver_ids=[
            target["receiver_id"]
            for target in targets
            if target["type"] in {"mysql", "mariadb"}
        ],
        token_env=token_env,
        memory_mib=collector["memory_mib"],
    )


def credential_env_template(
    targets: list[dict[str, Any]],
    *,
    platform: str,
    include_access_token: bool = False,
    memory_mib: int | None = None,
) -> str:
    lines = (
        [
            "# PowerShell KEY=VALUE validation handoff; this file is never persisted to the service.",
            "# Fill locally, protect with an owner/SYSTEM/Administrators-only NTFS ACL, and never commit real values.",
        ]
        if platform == "windows"
        else [
            "# systemd EnvironmentFile syntax; quote values containing spaces or '#'.",
            "# Fill locally, make owner-only (for example chmod 0400 or 0600), and never commit real values.",
        ]
    )
    if include_access_token:
        lines.append("SPLUNK_ACCESS_TOKEN=")
    if memory_mib is not None:
        lines.append(f"SPLUNK_MEMORY_LIMIT_MIB={memory_mib}")
    for target in targets:
        creds = target["credentials"]
        if target["connection_mode"] == "windows":
            continue
        if target["connection_mode"] == "datasource":
            lines.append(f"{creds['datasource_var']}=")
        else:
            lines.extend(
                [
                    f"{creds['username_var']}=",
                    f"{creds['password_var']}=",
                ]
            )
    return "\n".join(lines) + "\n"


def required_credential_envs(targets: list[dict[str, Any]]) -> list[str]:
    required: list[str] = []
    for target in targets:
        creds = target["credentials"]
        if target["connection_mode"] == "windows":
            continue
        if target["connection_mode"] == "datasource":
            required.append(creds["datasource_var"])
        else:
            required.extend([creds["username_var"], creds["password_var"]])
    return required


def required_tls_files(targets: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for target in targets:
        tls = target["advanced"].get("tls") or {}
        for key in ("ca_file", "cert_file", "key_file"):
            value = tls.get(key)
            if value and value not in paths:
                paths.append(value)
    return paths


def tls_file_requirements(targets: list[dict[str, Any]]) -> list[dict[str, str]]:
    requirements: dict[str, str] = {}
    for target in targets:
        tls = target["advanced"].get("tls") or {}
        for key in ("ca_file", "cert_file", "key_file"):
            if tls.get(key):
                kind = "private_key" if key == "key_file" else "public_certificate"
                previous = requirements.get(tls[key])
                requirements[tls[key]] = (
                    "private_key" if previous == "private_key" else kind
                )
    return [
        {"path": path, "kind": kind}
        for path, kind in sorted(requirements.items())
    ]


def handoff_k8s(
    *,
    realm: str,
    cluster_name: str,
    distribution: str,
    scrape_owner: str,
    collector: dict[str, str],
) -> str:
    return rf"""#!/usr/bin/env bash
set -euo pipefail

echo "The base Splunk OTel Collector release must already exist with:"
echo "  release={collector["release_name"]} namespace={collector["namespace"]}"
echo "  kube-context={collector["kube_context"]}"
echo "  realm={realm} clusterName={cluster_name} distribution={K8S_DISTRIBUTIONS[distribution]}"
echo "The DBMon action reuses the chart-owned access-token Secret and refuses to"
echo "replace realm, clusterName, distribution, or an existing extraEnv value."
echo "If the release is absent, first run the splunk-observability-otel-collector-setup"
echo "skill to render, approve, apply, and validate the base collector release."
echo "Declared scrape owner: {scrape_owner}"
echo
echo "After reviewing the rendered packet, apply through the guarded setup command:"
echo "  setup.sh --apply-k8s --accept-k8s-apply --spec <spec> --output-dir <output>"
echo "Collector and chart are pinned to {collector["version"]}; upgrades require a separate approval."
"""


def render_apply_overlay_script(
    *,
    realm: str,
    cluster_name: str,
    distribution: str,
    scrape_owner: str,
    collector: dict[str, Any],
    targets: list[dict[str, Any]],
    overlay_sha256: str,
) -> str:
    chart_ref = "splunk-otel-collector-chart/splunk-otel-collector"
    secret_checks: list[str] = []
    for target in targets:
        if target["connection_mode"] == "windows":
            continue
        secret = target["credentials"]["kubernetes_secret"]
        if target["connection_mode"] == "datasource":
            secret_checks.append(
                f'check_secret_key "{secret["name"]}" "{secret["datasource_key"]}" "{target["type"]}"'
            )
        else:
            for key in (secret["username_key"], secret["password_key"]):
                secret_checks.append(f'check_secret_key "{secret["name"]}" "{key}" value')
    checks = "\n".join(secret_checks)
    receiver_pattern = "|".join(re.escape(target["receiver_id"]) for target in targets)
    component_pattern = (
        receiver_pattern
        + r"|otlp_http/dbmon|signalfx/dbmon|logs/dbmon(_core|_mysql)?|metrics/dbmon(_core|_mysql)?"
    )
    return rf"""#!/usr/bin/env bash
set -euo pipefail
umask 077

for tool in helm kubectl yq python3 install mkdir mv wc; do
    command -v "${{tool}}" >/dev/null 2>&1 || {{ echo "ERROR: ${{tool}} is required." >&2; exit 1; }}
done
yq --version 2>&1 | grep -Eq 'version[[:space:]]+v?4\.' || {{
    echo 'ERROR: Mike Farah yq major version 4 is required.' >&2
    exit 1
}}
if command -v docker >/dev/null 2>&1; then
    CONTAINER_RUNTIME=docker
elif command -v podman >/dev/null 2>&1; then
    CONTAINER_RUNTIME=podman
else
    echo 'ERROR: docker or podman is required for exact collector config validation.' >&2
    exit 1
fi
helm_version="$(helm version --template '{{{{.Version}}}}' 2>/dev/null)" || {{
    echo 'ERROR: could not determine the installed Helm version.' >&2
    exit 1
}}
if [[ "${{helm_version}}" =~ ^v?([0-9]+)\.[0-9]+(\.|$) ]]; then
    HELM_MAJOR="${{BASH_REMATCH[1]}}"
else
    echo 'ERROR: installed Helm version is not a recognized semantic version.' >&2
    exit 1
fi
if (( HELM_MAJOR != 3 && HELM_MAJOR != 4 )); then
    echo "ERROR: DBMon Kubernetes apply requires Helm 3 or Helm 4; found major version ${{HELM_MAJOR}}." >&2
    exit 1
fi

DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)"
OVERLAY="${{DIR}}/k8s/values.dbmon.clusterreceiver.yaml"
EXPECTED_OVERLAY_SHA256="{overlay_sha256}"
RELEASE="{collector["release_name"]}"
NAMESPACE="{collector["namespace"]}"
CHART_REF="{chart_ref}"
CHART_REPO_URL="https://signalfx.github.io/splunk-otel-collector-chart"
CHART_VERSION="{collector["chart_version"]}"
CHART_SHA256="{AUDITED_CHART_SHA256}"
COLLECTOR_VERSION="{collector["version"].lstrip("v")}"
AUDITED_IMAGE="{AUDITED_COLLECTOR_IMAGE}"
KUBE_CONTEXT="{collector["kube_context"]}"
SELECTOR="app=splunk-otel-collector,component=otel-k8s-cluster-receiver,release=${{RELEASE}}"
TLS_FILE_REQUIREMENTS_JSON='{json.dumps(tls_file_requirements(targets), separators=(",", ":"))}'
EXPECTED_REALM="{realm}"
EXPECTED_CLUSTER="{cluster_name}"
EXPECTED_DISTRIBUTION="{K8S_DISTRIBUTIONS[distribution]}"
DBMON_COMPONENT_PATTERN="{component_pattern}"
SCRAPE_OWNER="{scrape_owner}"
UNSUPPORTED_TARGET_COUNT="{sum(1 for target in targets if target['support_status'] != 'official')}"

actual_overlay_sha256="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "${{OVERLAY}}")"
[[ "${{actual_overlay_sha256}}" == "${{EXPECTED_OVERLAY_SHA256}}" ]] || {{
    echo 'ERROR: rendered DBMon overlay changed after packet generation; re-render and review before apply.' >&2
    exit 1
}}

helm_ctx() {{ command helm --kube-context "${{KUBE_CONTEXT}}" "$@"; }}
kubectl_ctx() {{ command kubectl --context "${{KUBE_CONTEXT}}" "$@"; }}
read_release_identity() {{
    helm_ctx history "${{RELEASE}}" -n "${{NAMESPACE}}" -o json | python3 -c '
import json
import sys

history = json.load(sys.stdin)
if not isinstance(history, list) or not history:
    raise SystemExit("Helm history is empty")
revision = history[-1].get("revision")
description = history[-1].get("description")
if isinstance(revision, bool):
    raise SystemExit("Helm revision is invalid")
try:
    revision = int(revision)
except (TypeError, ValueError):
    raise SystemExit("Helm revision is invalid")
if revision < 1 or not isinstance(description, str) or not description or any(character in description for character in "\t\r\n"):
    raise SystemExit("Helm release identity is invalid")
print("%d\t%s" % (revision, description))
'
}}

[[ "${{SCRAPE_OWNER}}" == "kubernetes" ]] || {{
    echo 'ERROR: This spec assigns DBMon scrape ownership to {scrape_owner}; re-render with scrape_owner: kubernetes before Kubernetes apply.' >&2
    exit 1
}}
[[ "${{UNSUPPORTED_TARGET_COUNT}}" == "0" ]] || {{
    echo 'ERROR: unsupported-target opt-in is render/validate-only; production Kubernetes apply is disabled.' >&2
    exit 1
}}
actual_context="$(kubectl config current-context)"
[[ "${{actual_context}}" == "${{KUBE_CONTEXT}}" ]] || {{
    echo "ERROR: active kube context ${{actual_context:-<none>}} does not match reviewed context ${{KUBE_CONTEXT}}." >&2
    exit 1
}}
if [[ "${{K8S_APPLY_DRY_RUN:-false}}" != "true" && "${{ACCEPT_K8S_APPLY:-false}}" != "true" ]]; then
    echo 'ERROR: Explicit --accept-k8s-apply approval is required for Helm mutation.' >&2
    exit 1
fi
STATE_DIR="${{XDG_STATE_HOME:-${{HOME:?HOME is required}}/.local/state}}/splunk-dbmon"
STATE="${{STATE_DIR}}/${{NAMESPACE}}-${{RELEASE}}.json"
[[ "${{STATE}}" =~ ^/[A-Za-z0-9._/@:-]+$ ]] || {{
    echo 'ERROR: derived Kubernetes DBMon state path contains unsafe characters.' >&2
    exit 1
}}
if [[ "${{K8S_APPLY_DRY_RUN:-false}}" != "true" ]]; then
    python3 - "${{STATE_DIR}}" <<'PY'
import os
import pathlib
import stat
import sys

target = pathlib.Path(sys.argv[1])
current = pathlib.Path(target.root)
for part in target.parts[1:]:
    current /= part
    try:
        info = os.lstat(current)
    except FileNotFoundError:
        os.mkdir(current, 0o700)
        info = os.lstat(current)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise SystemExit(f"ERROR: unsafe state directory component: {{current}}")
if os.lstat(target).st_uid != os.geteuid() or stat.S_IMODE(os.lstat(target).st_mode) & 0o077:
    raise SystemExit("ERROR: DBMon state leaf directory must be owner-owned and owner-only.")
PY
    STATE_PROBE="$(mktemp "${{STATE_DIR}}/.dbmon-write-test.XXXXXX")"
    chmod 0600 "${{STATE_PROBE}}"
    rm -f -- "${{STATE_PROBE}}"
    LOCK_FILE="${{STATE_DIR}}/${{NAMESPACE}}-${{RELEASE}}.lock"
    if [[ -e "${{LOCK_FILE}}" || -L "${{LOCK_FILE}}" ]]; then
        python3 - "${{LOCK_FILE}}" <<'PY'
import os
import stat
import sys
info = os.lstat(sys.argv[1])
if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or info.st_mode & 0o077:
    raise SystemExit("ERROR: unsafe Kubernetes DBMon transaction lock file.")
PY
    fi
    exec 9>>"${{LOCK_FILE}}"
    chmod 0600 "${{LOCK_FILE}}"
    if ! python3 - "${{LOCK_FILE}}" <<'PY'
import fcntl
import os
import stat
import sys

try:
    descriptor = os.fstat(9)
    target = os.stat(sys.argv[1], follow_symlinks=False)
    if not stat.S_ISREG(descriptor.st_mode) or (descriptor.st_dev, descriptor.st_ino) != (target.st_dev, target.st_ino):
        raise OSError("file descriptor 9 is not the reviewed DBMon lock file")
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
except (BlockingIOError, OSError):
    raise SystemExit(1)
PY
    then
        echo 'ERROR: another DBMon apply or rollback transaction is active.' >&2
        exit 1
    fi
fi
TMPDIR_LOCAL="$(mktemp -d)"
APPLY_OWNED_REVISION=""
APPLY_PREVIOUS_REVISION=""
APPLY_TRANSACTION_ID=""
APPLY_COMMITTED=false
QUIESCED_DEPLOYMENT=""
QUIESCE_ACTIVE=false
ROLLBACK_HELM_COMPLETED=false
RECOVERY_SIGNAL_STATUS=0
restore_previous_state() {{
    local restored_revision="$1" restored_description="$2"
    python3 - "${{STATE}}" "${{restored_revision}}" "${{restored_description}}" <<'PY'
import json
import os
import sys

try:
    restored_revision = int(sys.argv[2])
except (TypeError, ValueError):
    raise SystemExit("ERROR: restored DBMon revision is invalid.")
restored_description = sys.argv[3]
if restored_revision < 1 or not restored_description or any(
    character in restored_description for character in "\t\r\n"
):
    raise SystemExit("ERROR: restored DBMon release identity is invalid.")
with open(sys.argv[1], encoding="utf-8") as handle:
    current = json.load(handle)
previous = current.get("previous_state")
if previous is None:
    os.unlink(sys.argv[1])
    directory = os.open(os.path.dirname(sys.argv[1]), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    raise SystemExit(0)
if not isinstance(previous, dict):
    raise SystemExit("ERROR: pending DBMon state has an invalid previous_state.")
previous["applied_revision"] = restored_revision
previous["applied_description"] = restored_description
previous["phase"] = "validated"
temporary = sys.argv[1] + f".restore.{{os.getpid()}}"
descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    json.dump(previous, handle, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.replace(temporary, sys.argv[1])
directory = os.open(os.path.dirname(sys.argv[1]), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY
}}
quiesce_cluster_receiver_for_rollback() {{
    local deployment_identity deployment_name desired_replicas pod_count
    if ! deployment_identity="$(kubectl_ctx -n "${{NAMESPACE}}" get deployment -l "${{SELECTOR}}" -o json \
        | python3 -c 'import json,sys; x=json.load(sys.stdin).get("items", []); sys.exit("expected exactly one DBMon Deployment before rollback") if len(x) != 1 else None; r=x[0].get("spec", {{}}).get("replicas", 1); sys.exit("DBMon rollback only supports zero or one desired replica") if r not in (0, 1) else print(x[0]["metadata"]["name"] + "\t" + str(r))')"; then
        echo 'ERROR: could not identify exactly one DBMon cluster-receiver Deployment before rollback; pending state retained.' >&2
        return 1
    fi
    IFS=$'\t' read -r deployment_name desired_replicas <<< "${{deployment_identity}}"
    QUIESCED_DEPLOYMENT="${{deployment_name}}"
    QUIESCE_ACTIVE=true
    ROLLBACK_HELM_COMPLETED=false
    if [[ "${{desired_replicas}}" == "1" ]] \
        && ! kubectl_ctx -n "${{NAMESPACE}}" scale "deployment/${{deployment_name}}" --replicas=0; then
        echo 'ERROR: could not quiesce the DBMon cluster-receiver before rollback; pending state retained.' >&2
        return 1
    fi
    pod_count="$(kubectl_ctx -n "${{NAMESPACE}}" get pod -l "${{SELECTOR}}" -o json \
        | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("items", [])))' 2>/dev/null || true)"
    if [[ "${{pod_count}}" == "0" ]]; then
        return 0
    fi
    if kubectl_ctx -n "${{NAMESPACE}}" wait --for=delete pod -l "${{SELECTOR}}" --timeout=180s; then
        return 0
    fi
    pod_count="$(kubectl_ctx -n "${{NAMESPACE}}" get pod -l "${{SELECTOR}}" -o json \
        | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("items", [])))' 2>/dev/null || true)"
    if [[ "${{pod_count}}" == "0" ]]; then
        return 0
    fi
    if kubectl_ctx -n "${{NAMESPACE}}" scale "deployment/${{deployment_name}}" --replicas=1 >/dev/null 2>&1; then
        QUIESCE_ACTIVE=false
    fi
    echo 'ERROR: DBMon cluster-receiver pods did not terminate before rollback; replica count was restored and pending state retained.' >&2
    return 1
}}
resume_cluster_receiver_after_failed_rollback() {{
    local deployment_name
    deployment_name="${{QUIESCED_DEPLOYMENT}}"
    if [[ -z "${{deployment_name}}" ]]; then
        deployment_name="$(kubectl_ctx -n "${{NAMESPACE}}" get deployment -l "${{SELECTOR}}" -o json \
            | python3 -c 'import json,sys; x=json.load(sys.stdin).get("items", []); print(x[0]["metadata"]["name"] if len(x) == 1 else "")' 2>/dev/null || true)"
    fi
    [[ -n "${{deployment_name}}" ]] || return 1
    if kubectl_ctx -n "${{NAMESPACE}}" scale "deployment/${{deployment_name}}" --replicas=1 >/dev/null 2>&1; then
        QUIESCE_ACTIVE=false
        return 0
    fi
    return 1
}}
restored_release_is_ready() {{
    local release_status deployment_count
    release_status="$(helm_ctx status "${{RELEASE}}" -n "${{NAMESPACE}}" -o json 2>/dev/null \
        | python3 -c 'import json,sys; print((json.load(sys.stdin).get("info") or {{}}).get("status", ""))' 2>/dev/null || true)"
    [[ "${{release_status}}" == "deployed" ]] || return 1
    deployment_count="$(kubectl_ctx -n "${{NAMESPACE}}" get deployment -l "${{SELECTOR}}" -o json 2>/dev/null \
        | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("items", [])))' 2>/dev/null || true)"
    if [[ "${{deployment_count}}" == "0" ]]; then
        return 0
    fi
    [[ "${{deployment_count}}" == "1" ]] || return 1
    kubectl_ctx -n "${{NAMESPACE}}" rollout status deployment -l "${{SELECTOR}}" --timeout=180s >/dev/null
}}
automatic_rollback() {{
    [[ -n "${{APPLY_OWNED_REVISION}}" && "${{APPLY_COMMITTED}}" != "true" ]] || return 0
    local current_revision="" current_description="" history_identity="" current_chart_identity=""
    if ! history_identity="$(read_release_identity 2>/dev/null)"; then
        echo 'ERROR: could not read a valid Helm release identity during automatic rollback; pending state retained.' >&2
        return 1
    fi
    IFS=$'\t' read -r current_revision current_description <<< "${{history_identity}}"
    if [[ "${{current_revision}}" != "${{APPLY_OWNED_REVISION}}" || "${{current_description}}" != "${{APPLY_TRANSACTION_ID}}" ]]; then
        current_chart_identity="$(helm_ctx list -n "${{NAMESPACE}}" -f "^${{RELEASE}}$" -o json 2>/dev/null \
            | python3 -c 'import json,sys; x=json.load(sys.stdin); print(x[0].get("chart", "") if x else "")' 2>/dev/null || true)"
        if helm_ctx get values "${{RELEASE}}" -n "${{NAMESPACE}}" -o json > "${{TMPDIR_LOCAL}}/reconcile-values.json" 2>/dev/null \
            && helm_ctx get manifest "${{RELEASE}}" -n "${{NAMESPACE}}" > "${{TMPDIR_LOCAL}}/reconcile-manifest.yaml" 2>/dev/null \
            && python3 - "${{STATE}}" "${{TMPDIR_LOCAL}}/reconcile-values.json" \
                "${{TMPDIR_LOCAL}}/reconcile-manifest.yaml" "${{current_chart_identity}}" <<'PY'
import hashlib
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)
with open(sys.argv[2], encoding="utf-8") as handle:
    values = json.load(handle)
values_digest = hashlib.sha256(
    json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
with open(sys.argv[3], "rb") as handle:
    manifest_digest = hashlib.sha256(handle.read()).hexdigest()
matches = (
    values_digest == state.get("previous_values_sha256")
    and manifest_digest == state.get("previous_manifest_sha256")
    and sys.argv[4] == state.get("previous_chart")
)
raise SystemExit(0 if matches else 1)
PY
        then
            if ! restored_release_is_ready; then
                echo 'ERROR: exact pre-apply Helm content is present but its workload is not ready; pending state retained.' >&2
                return 1
            fi
            echo 'DBMon Helm operation already restored the exact pre-apply chart, values, and manifest; rebasing prior trusted state.' >&2
            if ! restore_previous_state "${{current_revision}}" "${{current_description}}"; then
                echo 'ERROR: exact pre-apply content is present but trusted rollback state could not be safely rebased; pending state retained.' >&2
                return 1
            fi
            APPLY_OWNED_REVISION=""
            return 0
        fi
        echo "ERROR: DBMon apply did not commit and current Helm revision/description is not action-owned or pre-apply-equivalent; refusing automatic rollback and retaining pending state." >&2
        return 1
    fi
    echo "ERROR: DBMon apply did not commit; rolling back action-owned revision ${{APPLY_OWNED_REVISION}}." >&2
    if ! quiesce_cluster_receiver_for_rollback; then
        return 1
    fi
    if helm_ctx rollback "${{RELEASE}}" "${{APPLY_PREVIOUS_REVISION}}" -n "${{NAMESPACE}}" --wait --timeout 5m; then
        local restored_revision="" restored_description="" restored_identity=""
        ROLLBACK_HELM_COMPLETED=true
        QUIESCE_ACTIVE=false
        if ! restored_identity="$(read_release_identity)"; then
            echo 'ERROR: automatic Helm rollback completed but its live release identity could not be verified; pending state retained.' >&2
            return 1
        fi
        IFS=$'\t' read -r restored_revision restored_description <<< "${{restored_identity}}"
        if ! restored_release_is_ready; then
            echo 'ERROR: automatic Helm rollback completed but the restored release is not ready; pending state retained.' >&2
            return 1
        fi
        if ! restore_previous_state "${{restored_revision}}" "${{restored_description}}"; then
            echo 'ERROR: automatic Helm rollback completed but trusted state could not be safely advanced; pending state retained.' >&2
            return 1
        fi
        APPLY_OWNED_REVISION=""
        return 0
    fi
    if ! resume_cluster_receiver_after_failed_rollback; then
        echo 'ERROR: automatic Helm rollback failed and the cluster-receiver could not be resumed automatically.' >&2
    fi
    echo 'ERROR: automatic Helm rollback failed; pending state was retained for manual recovery.' >&2
    return 1
}}
on_exit() {{
    local status=$?
    trap - EXIT
    trap 'RECOVERY_SIGNAL_STATUS=130' INT
    trap 'RECOVERY_SIGNAL_STATUS=143' TERM
    set +e
    automatic_rollback
    local rollback_status=$?
    if [[ "${{QUIESCE_ACTIVE}}" == "true" && "${{ROLLBACK_HELM_COMPLETED}}" != "true" ]]; then
        if ! resume_cluster_receiver_after_failed_rollback; then
            echo 'ERROR: interrupted rollback recovery could not restore the cluster-receiver replica.' >&2
            rollback_status=1
        fi
    fi
    rm -rf -- "${{TMPDIR_LOCAL}}"
    trap - INT TERM
    if [[ "${{RECOVERY_SIGNAL_STATUS}}" != "0" ]]; then status="${{RECOVERY_SIGNAL_STATUS}}"; fi
    if [[ "${{status}}" == "0" && "${{rollback_status}}" != "0" ]]; then status=1; fi
    exit "${{status}}"
}}
trap 'exit 130' INT
trap 'exit 143' TERM
trap on_exit EXIT

check_secret_key() {{
    local secret_name="$1" secret_key="$2" value_kind="${{3:-value}}"
    local trust_path=""
    if ! kubectl_ctx -n "${{NAMESPACE}}" get secret "${{secret_name}}" -o json > "${{TMPDIR_LOCAL}}/secret-check.json" \
        || ! trust_path="$(python3 - "${{TMPDIR_LOCAL}}/secret-check.json" "${{secret_key}}" "${{value_kind}}" <<'PY'
import base64
import json
import pathlib
import re
import sys
import urllib.parse

with open(sys.argv[1], encoding="utf-8") as handle:
    encoded = (json.load(handle).get("data") or {{}}).get(sys.argv[2], "")
try:
    raw = base64.b64decode(encoded, validate=True) if encoded else b""
    value = raw.decode("utf-8", "strict")
except (ValueError, UnicodeError):
    raise SystemExit(1)
if not raw or raw.startswith((b"PLACEHOLDER_", b"CHANGEME")) or "\x00" in value:
    raise SystemExit(1)
kind = sys.argv[3]
if kind == "token" and any(character.isspace() for character in value):
    raise SystemExit(1)
parsed = urllib.parse.urlsplit(value)
pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
options = {{}}
raw_options = {{}}
for key, option in pairs:
    normalized = key.strip().casefold()
    if normalized in options:
        raise SystemExit(1)
    options[normalized] = option.strip().casefold()
    raw_options[normalized] = option.strip()
trust_path = ""
if kind == "sqlserver":
    if parsed.scheme.casefold() != "sqlserver" or not parsed.hostname or parsed.fragment:
        raise SystemExit(1)
    if options.get("encrypt") not in {{"true", "yes", "mandatory", "strict", "1"}}:
        raise SystemExit(1)
    if options.get("trustservercertificate") not in {{"false", "no", "0"}}:
        raise SystemExit(1)
    trust_path = raw_options.get("certificate", "")
elif kind == "oracledb":
    if parsed.scheme.casefold() != "oracle" or not parsed.hostname or parsed.fragment:
        raise SystemExit(1)
    if options.get("ssl") not in {{"enable", "true"}} or options.get("ssl verify") != "true":
        raise SystemExit(1)
    trust_path = raw_options.get("wallet", "")
if trust_path:
    path = pathlib.PurePosixPath(trust_path)
    if not path.is_absolute() or ".." in path.parts or any(
        ord(character) < 32 or ord(character) == 127 for character in trust_path
    ):
        raise SystemExit(1)
    if kind == "sqlserver" and path.suffix.casefold() != ".pem":
        raise SystemExit(1)
    print(trust_path)
PY
        )"; then
        echo "ERROR: Secret ${{secret_name}} in ${{NAMESPACE}} is missing/placeholder key ${{secret_key}}, or its datasource lacks required certificate-verifying transport options." >&2
        exit 1
    fi
    if [[ -n "${{trust_path}}" ]]; then
        printf '%s\t%s\n' "${{value_kind}}" "${{trust_path}}" >> "${{TMPDIR_LOCAL}}/datasource-trust-paths"
    fi
}}

# Chart upgrades can preserve arbitrary custom collector config from the
# installed release.  Extract only the three chart collector roles and keep
# parser diagnostics private because an existing ConfigMap can contain
# operator-supplied connection material.
extract_role_configs() {{
    local manifest="$1" output="$2" phase="$3"
    local role_spec role_suffix role_name
    : > "${{output}}"
    for role_spec in \
        '-otel-agent:otel-agent' \
        '-otel-collector:otel-gateway' \
        '-otel-k8s-cluster-receiver:otel-k8s-cluster-receiver'; do
        role_suffix="${{role_spec%%:*}}"
        role_name="${{role_spec#*:}}"
        if ! ROLE_SUFFIX="${{role_suffix}}" ROLE_NAME="${{role_name}}" \
            yq ea -o=json -I=0 '
                select(
                    .kind == "ConfigMap"
                    and .data.relay != null
                    and ((.metadata.name // "") | test(strenv(ROLE_SUFFIX) + "$"))
                  )
                | {{"role": strenv(ROLE_NAME), "config": (.data.relay | from_yaml)}}
            ' "${{manifest}}" >> "${{output}}" \
            2>> "${{TMPDIR_LOCAL}}/${{phase}}-role-config-extract.log"; then
            echo "ERROR: could not parse ${{phase}} agent/gateway/clusterReceiver configs; config and parser output suppressed." >&2
            exit 1
        fi
    done
}}

# The Splunk distribution does not expose a components subcommand.  Ask the
# exact target binary to reject one deliberately unavailable type in every
# component section, then parse its authoritative "valid values" inventories.
# The probe and its raw output contain no release config or credentials.
build_target_component_inventory() {{
    local probe="${{TMPDIR_LOCAL}}/target-component-inventory-probe.yaml"
    local probe_log="${{TMPDIR_LOCAL}}/target-component-inventory.log"
    local inventory="${{TMPDIR_LOCAL}}/target-component-inventory.json"
    python3 - "${{probe}}" <<'PY'
import os
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
path.write_text(
    "receivers:\n"
    "  dbmoninventoryunavailable: {{}}\n"
    "processors:\n"
    "  dbmoninventoryunavailable: {{}}\n"
    "exporters:\n"
    "  dbmoninventoryunavailable: {{}}\n"
    "connectors:\n"
    "  dbmoninventoryunavailable: {{}}\n"
    "extensions:\n"
    "  dbmoninventoryunavailable: {{}}\n"
    "service:\n"
    "  extensions: [dbmoninventoryunavailable]\n"
    "  pipelines:\n"
    "    metrics:\n"
    "      receivers: [dbmoninventoryunavailable]\n"
    "      processors: [dbmoninventoryunavailable]\n"
    "      exporters: [dbmoninventoryunavailable]\n",
    encoding="utf-8",
)
os.chmod(path, 0o600)
PY
    if "${{CONTAINER_RUNTIME}}" run --rm --pull=always --network=none \
        --volume "${{probe}}:/etc/otelcol/dbmon-component-inventory.yaml:ro" \
        "${{AUDITED_IMAGE}}" \
        validate --config=/etc/otelcol/dbmon-component-inventory.yaml \
        > "${{probe_log}}" 2>&1; then
        echo 'ERROR: target Collector unexpectedly accepted the component inventory probe; refusing upgrade.' >&2
        exit 1
    fi
    if ! python3 - "${{probe_log}}" "${{inventory}}" \
        > /dev/null 2> "${{TMPDIR_LOCAL}}/target-component-inventory-parse.log" <<'PY'
import json
import re
import sys

text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
sections = ("receivers", "processors", "exporters", "connectors", "extensions")
inventory = {{}}
for section in sections:
    matches = re.findall(
        rf"'{{section}}' unknown type: .*?\(valid values: \[([^\]]+)\]\)",
        text,
        flags=re.DOTALL,
    )
    values = sorted({{value for match in matches for value in match.split()}})
    if not values:
        raise SystemExit(1)
    inventory[section] = values
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    json.dump(inventory, handle, sort_keys=True)
    handle.write("\n")
PY
    then
        echo 'ERROR: could not obtain a complete component inventory from the target Collector; raw output suppressed.' >&2
        exit 1
    fi
}}

check_target_component_inventory() {{
    local phase="$1" values_path="$2" role_configs_path="$3"
    local enforcement="${{4:-enforce}}"
    if ! python3 - \
        "${{TMPDIR_LOCAL}}/target-component-inventory.json" \
        "${{values_path}}" "${{role_configs_path}}" "${{phase}}" \
        > /dev/null 2> "${{TMPDIR_LOCAL}}/${{phase}}-component-compatibility.log" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    inventory = {{key: set(value) for key, value in json.load(handle).items()}}
with open(sys.argv[2], encoding="utf-8") as handle:
    values = json.load(handle)

roles = ("agent", "gateway", "clusterReceiver")
role_labels = {{
    "otel-agent": "agent",
    "otel-gateway": "gateway",
    "otel-k8s-cluster-receiver": "clusterReceiver",
}}
configs = []
manifest_role_counts = {{role: 0 for role in roles}}
for role in roles:
    role_values = values.get(role) or {{}}
    if not isinstance(role_values, dict):
        raise SystemExit(1)
    config = role_values.get("config") or {{}}
    if not isinstance(config, dict):
        raise SystemExit(1)
    configs.append((role, config))

with open(sys.argv[3], encoding="utf-8") as handle:
    for line in handle:
        if not line.strip():
            continue
        item = json.loads(line)
        role = role_labels.get(item.get("role"))
        config = item.get("config")
        if role is None or not isinstance(config, dict):
            raise SystemExit(1)
        manifest_role_counts[role] += 1
        configs.append((role, config))

if sys.argv[4] == "merged" and sum(manifest_role_counts.values()):
    if manifest_role_counts["clusterReceiver"] != 1:
        raise SystemExit(1)
    if manifest_role_counts["agent"] > 1 or manifest_role_counts["gateway"] > 1:
        raise SystemExit(1)

for _role, config in configs:
    for section, allowed in inventory.items():
        configured = config.get(section) or {{}}
        if not isinstance(configured, dict):
            raise SystemExit(1)
        for component_id in configured:
            if not isinstance(component_id, str):
                raise SystemExit(1)
            component_type = component_id.split("/", 1)[0]
            if component_type not in allowed:
                raise SystemExit(1)
PY
    then
        if [[ "${{enforcement}}" == "report-only" ]]; then
            echo 'NOTICE: existing collector role config contains component types unavailable in the target image; the target-rendered config must remove them before upgrade.' >&2
            return 0
        fi
        echo "ERROR: target Collector compatibility preflight rejected ${{phase}} agent/gateway/clusterReceiver config; component identifiers, config, and validation output suppressed." >&2
        exit 1
    fi
}}

# Chart 0.158.0 fails template rendering when custom role config retains any
# deprecated component alias.  These renames can also imply a topology change
# (for example, an old agent-to-gateway path), so this action never rewrites
# them mechanically.  Report only the public base-name mapping and counts.
reject_deprecated_chart_aliases() {{
    local values_path="$1"
    local report="${{TMPDIR_LOCAL}}/deprecated-chart-aliases.report"
    local status=0
    if python3 - "${{values_path}}" "${{report}}" \
        > /dev/null 2> "${{TMPDIR_LOCAL}}/deprecated-chart-aliases.log" <<'PY'
import json
import sys

aliases = {{
    "exporters": (("otlp", "otlp_grpc"), ("otlphttp", "otlp_http")),
    "processors": (
        ("k8sattributes", "k8s_attributes"),
        # Added by chart 0.158.0.
        ("resourcedetection", "resource_detection"),
    ),
    "receivers": (
        ("filelog", "file_log"),
        ("hostmetrics", "host_metrics"),
        ("k8sobjects", "k8s_objects"),
        # Added by chart 0.157.0.
        ("kubeletstats", "kubelet_stats"),
    ),
}}
roles = ("agent", "gateway", "clusterReceiver")
stats = {{
    (section, old, new): [0, 0]
    for section, mappings in aliases.items()
    for old, new in mappings
}}

def alias_for(section, component_id):
    if not isinstance(component_id, str):
        raise ValueError("component IDs must be strings")
    component_type = component_id.split("/", 1)[0]
    return next(
        ((old, new) for old, new in aliases[section] if component_type == old),
        None,
    )

with open(sys.argv[1], encoding="utf-8") as handle:
    values = json.load(handle)
for role in roles:
    role_values = values.get(role) or {{}}
    if not isinstance(role_values, dict):
        raise SystemExit(1)
    config = role_values.get("config") or {{}}
    if not isinstance(config, dict):
        raise SystemExit(1)
    for section in aliases:
        definitions = config.get(section) or {{}}
        if not isinstance(definitions, dict):
            raise SystemExit(1)
        for component_id in definitions:
            mapping = alias_for(section, component_id)
            if mapping:
                stats[(section, *mapping)][0] += 1
    service = config.get("service") or {{}}
    if not isinstance(service, dict):
        raise SystemExit(1)
    pipelines = service.get("pipelines") or {{}}
    if not isinstance(pipelines, dict):
        raise SystemExit(1)
    for pipeline in pipelines.values():
        if not pipeline:
            continue
        if not isinstance(pipeline, dict):
            raise SystemExit(1)
        for section in aliases:
            references = pipeline.get(section) or []
            if not isinstance(references, list):
                raise SystemExit(1)
            for component_id in references:
                mapping = alias_for(section, component_id)
                if mapping:
                    stats[(section, *mapping)][1] += 1

findings = [
    (section, old, new, counts)
    for (section, old, new), counts in stats.items()
    if any(counts)
]
if not findings:
    raise SystemExit(0)
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    for section, old, new, (definitions, references) in sorted(findings):
        handle.write(
            f"{{section}} {{old}}->{{new}} definitions={{definitions}} "
            f"pipeline_refs={{references}}\n"
        )
raise SystemExit(2)
PY
    then
        return 0
    else
        status=$?
    fi
    if [[ "${{status}}" == "2" && -s "${{report}}" ]]; then
        echo 'ERROR: chart 0.158.0 rejects deprecated collector component aliases in the merged release config.' >&2
        while IFS= read -r migration_summary; do
            printf '  %s\n' "${{migration_summary}}" >&2
        done < "${{report}}"
        echo '       Config values and suffixed component IDs are suppressed.' >&2
        echo '       Use splunk-observability-otel-collector-setup for a reviewed full-release topology migration, then rerun DBMon apply.' >&2
        exit 1
    fi
    echo 'ERROR: could not safely audit merged collector config for chart 0.158.0 deprecated aliases; details suppressed.' >&2
    exit 1
}}

release_status="$(helm_ctx status "${{RELEASE}}" -n "${{NAMESPACE}}" -o json 2>/dev/null \
    | python3 -c 'import json,sys; print((json.load(sys.stdin).get("info") or {{}}).get("status", ""))' 2>/dev/null || true)"
[[ "${{release_status}}" == "deployed" ]] || {{
    echo "ERROR: Base release ${{RELEASE}} in ${{NAMESPACE}} is not deployed; use splunk-observability-otel-collector-setup first." >&2
    exit 1
}}
configured_repo_url="$(helm repo list -o json | python3 -c 'import json,sys; x=json.load(sys.stdin); print(next((item.get("url", "") for item in x if item.get("name") == sys.argv[1]), ""))' "${{CHART_REF%%/*}}")"
[[ "${{configured_repo_url%/}}" == "${{CHART_REPO_URL}}" ]] || {{
    echo "ERROR: Helm alias ${{CHART_REF%%/*}} must point to the audited public Splunk chart repository; configured URL suppressed." >&2
    exit 1
}}
helm pull "${{CHART_REF}}" --version "${{CHART_VERSION}}" --destination "${{TMPDIR_LOCAL}}"
CHART_PACKAGE="${{TMPDIR_LOCAL}}/splunk-otel-collector-${{CHART_VERSION}}.tgz"
actual_chart_sha="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "${{CHART_PACKAGE}}")"
[[ "${{actual_chart_sha}}" == "${{CHART_SHA256}}" ]] || {{
    echo "ERROR: downloaded chart digest ${{actual_chart_sha}} does not match audited ${{CHART_SHA256}}." >&2
    exit 1
}}
POST_RENDERER="${{TMPDIR_LOCAL}}/dbmon-post-renderer.sh"
printf '%s\n' \
    '#!/usr/bin/env bash' \
    'set -euo pipefail' \
    'yq eval '\''with(select(.kind == "Deployment" and .metadata.labels.component == "otel-k8s-cluster-receiver"); .spec.strategy = {{"type": "Recreate", "rollingUpdate": null}})'\'' -' \
    > "${{POST_RENDERER}}"
chmod 0700 "${{POST_RENDERER}}"
HELM_RENDER_COMMAND=(helm)
HELM_POST_RENDERER_ARGS=(--post-renderer "${{POST_RENDERER}}")
# Rollback is intentionally owned by this transaction helper. Helm's built-in
# atomic rollback cannot quiesce a singleton, fixed-node Deployment before a
# prior RollingUpdate strategy is restored and can deadlock on pod overlap.
HELM_UPGRADE_SAFETY_ARGS=(--wait)
if (( HELM_MAJOR == 4 )); then
    HELM4_POST_RENDERER_NAME=splunk-dbmon-recreate
    HELM4_PLUGIN_ROOT="${{TMPDIR_LOCAL}}/helm-plugins"
    HELM4_PLUGIN_DIR="${{HELM4_PLUGIN_ROOT}}/${{HELM4_POST_RENDERER_NAME}}"
    install -d -m 0700 "${{HELM4_PLUGIN_ROOT}}" "${{HELM4_PLUGIN_DIR}}"
    install -m 0600 /dev/null "${{HELM4_PLUGIN_DIR}}/plugin.yaml"
    # shellcheck disable=SC2016 # Helm expands HELM_PLUGIN_DIR at plugin runtime.
    printf '%s\n' \
        'apiVersion: v1' \
        'type: postrenderer/v1' \
        "name: ${{HELM4_POST_RENDERER_NAME}}" \
        'version: 1.0.0' \
        'runtime: subprocess' \
        'sourceURL: https://github.com/chambear2809/splunk-cisco-skills' \
        'runtimeConfig:' \
        '  platformCommand:' \
        '    - command: ${{HELM_PLUGIN_DIR}}/run.sh' \
        > "${{HELM4_PLUGIN_DIR}}/plugin.yaml"
    install -m 0700 /dev/null "${{HELM4_PLUGIN_DIR}}/run.sh"
    # shellcheck disable=SC2016 # Write runtime shell variables literally.
    printf '%s\n' \
        '#!/usr/bin/env bash' \
        'set -euo pipefail' \
        'plugin_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"' \
        'exec "${{plugin_dir}}/../../dbmon-post-renderer.sh" "$@"' \
        > "${{HELM4_PLUGIN_DIR}}/run.sh"
    python3 - \
        "${{TMPDIR_LOCAL}}" "${{HELM4_PLUGIN_ROOT}}" "${{HELM4_PLUGIN_DIR}}" \
        "${{HELM4_PLUGIN_DIR}}/plugin.yaml" "${{HELM4_PLUGIN_DIR}}/run.sh" <<'PY'
import os
import stat
import sys

expected = ((sys.argv[1], 0o700, True), (sys.argv[2], 0o700, True),
            (sys.argv[3], 0o700, True), (sys.argv[4], 0o600, False),
            (sys.argv[5], 0o700, False))
for path, mode, directory in expected:
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or info.st_uid != os.geteuid():
        raise SystemExit("ERROR: unsafe temporary Helm 4 post-renderer plugin ownership.")
    if directory != stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != mode:
        raise SystemExit("ERROR: unsafe temporary Helm 4 post-renderer plugin mode.")
PY
    HELM_RENDER_COMMAND=(env "HELM_PLUGINS=${{HELM4_PLUGIN_ROOT}}" helm)
    HELM_POST_RENDERER_ARGS=(--post-renderer "${{HELM4_POST_RENDERER_NAME}}")
    # Helm 4 server-side apply drops the explicit rollingUpdate: null needed
    # while changing an existing chart Deployment from RollingUpdate to
    # Recreate, then the API rejects the retained rollingUpdate field. Use the
    # supported client-side three-way update for this one owned release. The
    # action-owned EXIT transaction performs any required quiesced rollback.
    HELM_UPGRADE_SAFETY_ARGS=(--wait=watcher --server-side=false)
fi
chart_meta="$(helm show chart "${{CHART_PACKAGE}}")"
chart_app_version="$(printf '%s\n' "${{chart_meta}}" | awk '$1 == "appVersion:" {{gsub(/\"/, "", $2); print $2; exit}}')"
[[ "${{chart_app_version}}" == "${{COLLECTOR_VERSION}}" ]] || {{
    echo "ERROR: Chart appVersion ${{chart_app_version}} does not equal collector ${{COLLECTOR_VERSION}}." >&2
    exit 1
}}
current_chart="$(helm_ctx list -n "${{NAMESPACE}}" -f "^${{RELEASE}}$" -o json \
    | python3 -c 'import json,sys; x=json.load(sys.stdin); print(x[0].get("chart", "") if x else "")')"
UPGRADE_REQUESTED=false
if [[ "${{current_chart}}" != "splunk-otel-collector-${{CHART_VERSION}}" ]]; then
    UPGRADE_REQUESTED=true
    if [[ "${{ACCEPT_COLLECTOR_UPGRADE:-false}}" != "true" ]]; then
        echo "ERROR: Release uses ${{current_chart:-unknown}}; target is splunk-otel-collector-${{CHART_VERSION}}." >&2
        echo "       Review the upgrade and pass --accept-collector-upgrade." >&2
        exit 1
    fi
fi
current_images="$(kubectl_ctx -n "${{NAMESPACE}}" get deployment,daemonset,statefulset \
    -l "app=splunk-otel-collector,release=${{RELEASE}}" -o json \
    | python3 -c 'import json,sys; x=json.load(sys.stdin); print("\n".join(sorted({{c.get("image", "") for i in x.get("items", []) for c in i.get("spec", {{}}).get("template", {{}}).get("spec", {{}}).get("containers", []) if c.get("name") == "otel-collector"}})))')"
[[ -n "${{current_images}}" ]] || {{
    echo 'ERROR: no current otel-collector workload images were found for the release.' >&2
    exit 1
}}
if printf '%s\n' "${{current_images}}" | grep -Fxvq "${{AUDITED_IMAGE}}"; then
    UPGRADE_REQUESTED=true
    if [[ "${{ACCEPT_COLLECTOR_UPGRADE:-false}}" != "true" ]]; then
        echo 'ERROR: the DBMon overlay pins the global collector image tag and would change one or more chart workloads:' >&2
        printf '  %s\n' "${{current_images}}" >&2
        echo '       Review the release-wide image change and pass --accept-collector-upgrade.' >&2
        exit 1
    fi
fi

helm_ctx get values "${{RELEASE}}" -n "${{NAMESPACE}}" -o yaml > "${{TMPDIR_LOCAL}}/current-values.yaml"
helm_ctx get manifest "${{RELEASE}}" -n "${{NAMESPACE}}" > "${{TMPDIR_LOCAL}}/current-manifest.yaml"
previous_identity="$(read_release_identity)"
IFS=$'\t' read -r previous_revision previous_description <<< "${{previous_identity}}"
if [[ -e "${{STATE}}" || -L "${{STATE}}" ]]; then
    python3 - "${{STATE}}" "${{RELEASE}}" "${{NAMESPACE}}" "${{KUBE_CONTEXT}}" \
        "${{previous_revision}}" "${{previous_description}}" <<'PY'
import json
import os
import stat
import sys

path = sys.argv[1]
info = os.lstat(path)
if (
    not stat.S_ISREG(info.st_mode)
    or stat.S_ISLNK(info.st_mode)
    or info.st_mode & 0o077
    or info.st_uid != os.geteuid()
    or info.st_nlink != 1
):
    raise SystemExit("ERROR: existing DBMon Kubernetes state must be an owner-only regular file.")
with open(path, encoding="utf-8") as handle:
    state = json.load(handle)
if state.get("phase") != "validated":
    raise SystemExit("ERROR: existing DBMon state is not a committed validated apply; recover it before reapply.")
expected = {{"release": sys.argv[2], "namespace": sys.argv[3], "kube_context": sys.argv[4]}}
for key, value in expected.items():
    if state.get(key) != value:
        raise SystemExit(f"ERROR: existing DBMon state {{key}} does not match this reviewed packet.")
applied_description = state.get("applied_description", state.get("transaction_id"))
if (
    str(state.get("applied_revision")) != sys.argv[5]
    or applied_description != sys.argv[6]
):
    raise SystemExit("ERROR: Helm release identity drifted since the recorded DBMon apply; reconcile or manually archive state before a new apply.")
PY
fi

current_realm="$(yq -r '.splunkObservability.realm // ""' "${{TMPDIR_LOCAL}}/current-values.yaml")"
current_cluster="$(yq -r '.clusterName // ""' "${{TMPDIR_LOCAL}}/current-values.yaml")"
current_distribution="$(yq -r '.distribution // ""' "${{TMPDIR_LOCAL}}/current-values.yaml")"
[[ "${{current_realm}}" == "${{EXPECTED_REALM}}" ]] || {{
    echo "ERROR: Existing realm ${{current_realm:-<empty>}} does not match ${{EXPECTED_REALM}}; the DBMon overlay will not relabel it." >&2
    exit 1
}}
[[ "${{current_cluster}}" == "${{EXPECTED_CLUSTER}}" ]] || {{
    echo "ERROR: Existing clusterName ${{current_cluster:-<empty>}} does not match ${{EXPECTED_CLUSTER}}; the DBMon overlay will not relabel it." >&2
    exit 1
}}
[[ "${{current_distribution}}" == "${{EXPECTED_DISTRIBUTION}}" ]] || {{
    echo "ERROR: Existing distribution ${{current_distribution:-<empty>}} does not match ${{EXPECTED_DISTRIBUTION:-<empty>}}." >&2
    exit 1
}}

yq -o=json '.' "${{TMPDIR_LOCAL}}/current-values.yaml" > "${{TMPDIR_LOCAL}}/current-values.json"
yq -o=json '.' "${{OVERLAY}}" > "${{TMPDIR_LOCAL}}/overlay.json"
python3 - "${{TMPDIR_LOCAL}}/current-values.json" "${{TMPDIR_LOCAL}}/overlay.json" \
    "${{TMPDIR_LOCAL}}/merged.yaml" "${{ACCEPT_DBMON_RECONFIGURE:-false}}" <<'PY'
import json
import sys

base = json.load(open(sys.argv[1], encoding="utf-8"))
overlay = json.load(open(sys.argv[2], encoding="utf-8"))
allow_reconfigure = sys.argv[4] == "true"
types = ("postgresql", "sqlserver", "oracledb", "mysql")

def is_db_id(value):
    text = str(value)
    return text in types or any(text.startswith(item + "/") for item in types)

def db_ids(config):
    receivers = (config or {{}}).get("receivers") or {{}}
    return {{key for key in receivers if is_db_id(key)}}

def config_at(root, role):
    section = root.get(role) or {{}}
    config = section.get("config") or {{}}
    if not isinstance(config, dict):
        raise SystemExit(f"ERROR: existing {{role}}.config must be a mapping.")
    return config

for role in ("agent", "gateway"):
    if db_ids(config_at(base, role)):
        raise SystemExit(
            f"ERROR: existing {{role}} config already contains a DB receiver; migrate it "
            "out before assigning the clusterReceiver as sole scraper."
        )

current = config_at(base, "clusterReceiver")
desired = config_at(overlay, "clusterReceiver")
current_receivers = current.get("receivers") or {{}}
desired_receivers = desired.get("receivers") or {{}}
current_ids = db_ids(current)
desired_ids = db_ids(desired)
changes = []
if current_ids - desired_ids:
    changes.append("remove DB receivers: " + ", ".join(sorted(current_ids - desired_ids)))
for receiver_id in sorted(current_ids & desired_ids):
    if current_receivers[receiver_id] != desired_receivers[receiver_id]:
        changes.append(f"change receiver {{receiver_id}}")
desired_pipelines = ((desired.get("service") or {{}}).get("pipelines") or {{}})
for name, pipeline in (((current.get("service") or {{}}).get("pipelines") or {{}}).items()):
    assigned = [item for item in (pipeline or {{}}).get("receivers", []) if is_db_id(item)]
    if not assigned:
        continue
    non_db = [item for item in (pipeline or {{}}).get("receivers", []) if not is_db_id(item)]
    if non_db:
        raise SystemExit(
            f"ERROR: existing DB pipeline {{name}} also carries non-DB receivers; "
            "split it manually before DBMon reconfiguration."
        )
    if name not in desired_pipelines or pipeline != desired_pipelines[name]:
        changes.append(f"replace DB pipeline {{name}}")

managed_components = {{
    "exporters": {{"otlp_http/dbmon", "signalfx/dbmon"}},
    "processors": {{
        "memory_limiter/dbmon",
        "batch/dbmon",
        "resource_detection/dbmon",
        "resource/mysql_service_instance_id",
    }},
}}
for section, managed_ids in managed_components.items():
    current_section = current.get(section) or {{}}
    desired_section = desired.get(section) or {{}}
    if not isinstance(current_section, dict) or not isinstance(desired_section, dict):
        raise SystemExit(f"ERROR: existing and desired {{section}} sections must be mappings.")
    for component_id in sorted(managed_ids):
        if component_id not in current_section:
            continue
        if component_id not in desired_section:
            changes.append(f"remove DBMon {{section[:-1]}} {{component_id}}")
        elif current_section[component_id] != desired_section[component_id]:
            changes.append(f"change DBMon {{section[:-1]}} {{component_id}}")

base_envs = (base.get("clusterReceiver") or {{}}).get("extraEnvs") or []
overlay_envs = (overlay.get("clusterReceiver") or {{}}).get("extraEnvs") or []
if any(
    isinstance(item, dict) and item.get("name") == "SPLUNK_OBSERVABILITY_ACCESS_TOKEN"
    for item in base_envs
):
    raise SystemExit(
        "ERROR: base clusterReceiver.extraEnvs must not redefine the chart-owned "
        "SPLUNK_OBSERVABILITY_ACCESS_TOKEN."
    )
known = {{item.get("name"): item for item in base_envs if isinstance(item, dict) and item.get("name")}}
desired_env_names = {{item.get("name") for item in overlay_envs}}
stale_env_names = {{name for name in known if str(name).startswith("DBMON_") and name not in desired_env_names}}
if stale_env_names:
    changes.append("remove DB credential env references: " + ", ".join(sorted(stale_env_names)))
changed_env_names = set()
for item in overlay_envs:
    name = item.get("name")
    if name in known and known[name] != item:
        changed_env_names.add(name)
        changes.append(f"change DB credential env reference {{name}}")
if changes and not allow_reconfigure:
    raise SystemExit(
        "ERROR: existing DBMon config differs from the reviewed overlay (" + "; ".join(changes) +
        "). Re-render, review removal/change impact, and pass --accept-dbmon-reconfigure."
    )

# Remove the prior managed DBMon slice before merging so a reviewed target
# removal or pipeline change cannot leave an orphan duplicate scraper.
current["receivers"] = {{key: value for key, value in current_receivers.items() if key not in current_ids}}
for section, managed_ids in managed_components.items():
    current_section = current.get(section) or {{}}
    current[section] = {{
        key: value for key, value in current_section.items() if key not in managed_ids
    }}
service = current.setdefault("service", {{}})
pipelines = service.get("pipelines") or {{}}
service["pipelines"] = {{
    name: pipeline
    for name, pipeline in pipelines.items()
    if not any(is_db_id(item) for item in (pipeline or {{}}).get("receivers", []))
}}

def merge(left, right):
    if isinstance(left, dict) and isinstance(right, dict):
        result = dict(left)
        for key, value in right.items():
            result[key] = merge(result[key], value) if key in result else value
        return result
    return right

merged = merge(base, overlay)
preserved_envs = [
    item for name, item in known.items()
    if name not in stale_env_names
    and name not in changed_env_names
    and name not in desired_env_names
]
merged["clusterReceiver"]["extraEnvs"] = preserved_envs + overlay_envs
final_env_names = [item.get("name") for item in merged["clusterReceiver"]["extraEnvs"]]
if len(final_env_names) != len(set(final_env_names)):
    raise SystemExit("ERROR: merged clusterReceiver.extraEnvs contains duplicate names.")
with open(sys.argv[3], "w", encoding="utf-8") as handle:
    json.dump(merged, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
if [[ "${{UPGRADE_REQUESTED}}" == "true" ]]; then
    reject_deprecated_chart_aliases "${{TMPDIR_LOCAL}}/merged.yaml"
    extract_role_configs \
        "${{TMPDIR_LOCAL}}/current-manifest.yaml" \
        "${{TMPDIR_LOCAL}}/existing-role-configs.jsonl" \
        existing
    [[ -s "${{TMPDIR_LOCAL}}/existing-role-configs.jsonl" ]] || {{
        echo 'ERROR: no existing agent/gateway/clusterReceiver ConfigMap could be inventoried; refusing collector upgrade.' >&2
        exit 1
    }}
    build_target_component_inventory
    check_target_component_inventory \
        existing \
        "${{TMPDIR_LOCAL}}/current-values.json" \
        "${{TMPDIR_LOCAL}}/existing-role-configs.jsonl" \
        report-only
    check_target_component_inventory \
        merged \
        "${{TMPDIR_LOCAL}}/merged.yaml" \
        /dev/null \
        report-only
fi
"${{HELM_RENDER_COMMAND[@]}}" template "${{RELEASE}}" "${{CHART_PACKAGE}}" \
    --namespace "${{NAMESPACE}}" --values "${{TMPDIR_LOCAL}}/merged.yaml" \
    "${{HELM_POST_RENDERER_ARGS[@]}}" \
    > "${{TMPDIR_LOCAL}}/rendered-manifests.yaml"
rendered_images="$(yq ea -N -r '.. | select(has("containers")).containers[]? | select(.name == "otel-collector") | .image' \
    "${{TMPDIR_LOCAL}}/rendered-manifests.yaml" | sort -u)"
[[ -n "${{rendered_images}}" ]] || {{ echo 'ERROR: rendered chart has no otel-collector workloads.' >&2; exit 1; }}
if printf '%s\n' "${{rendered_images}}" | grep -Fxvq "${{AUDITED_IMAGE}}"; then
    echo 'ERROR: not every rendered collector workload is pinned to the audited image:' >&2
    printf '  %s\n' "${{rendered_images}}" >&2
    exit 1
fi

if [[ "${{UPGRADE_REQUESTED}}" == "true" ]]; then
    extract_role_configs \
        "${{TMPDIR_LOCAL}}/rendered-manifests.yaml" \
        "${{TMPDIR_LOCAL}}/merged-role-configs.jsonl" \
        merged
    [[ -s "${{TMPDIR_LOCAL}}/merged-role-configs.jsonl" ]] || {{
        echo 'ERROR: no merged agent/gateway/clusterReceiver ConfigMap could be inventoried; refusing collector upgrade.' >&2
        exit 1
    }}
    check_target_component_inventory \
        merged \
        "${{TMPDIR_LOCAL}}/merged.yaml" \
        "${{TMPDIR_LOCAL}}/merged-role-configs.jsonl"
fi

: > "${{TMPDIR_LOCAL}}/datasource-trust-paths"
{checks}

yq ea -o=json 'select(.kind == "Deployment" and .metadata.labels.component == "otel-k8s-cluster-receiver")' \
    "${{TMPDIR_LOCAL}}/rendered-manifests.yaml" > "${{TMPDIR_LOCAL}}/deployment.json"
python3 - "${{TMPDIR_LOCAL}}/overlay.json" "${{TMPDIR_LOCAL}}/deployment.json" \
    "{collector["memory_mib"]}" "{collector["cpu_limit"]}" \
    "${{TMPDIR_LOCAL}}/token-ref" "${{TMPDIR_LOCAL}}/datasource-trust-paths" <<'PY'
import json
import pathlib
import sys

overlay = json.load(open(sys.argv[1], encoding="utf-8"))
deployment = json.load(open(sys.argv[2], encoding="utf-8"))
required_memory_mib = int(sys.argv[3])
required_cpu = sys.argv[4]
if deployment.get("spec", {{}}).get("replicas") != 1:
    raise SystemExit("ERROR: rendered clusterReceiver Deployment must have exactly one replica.")
strategy = deployment.get("spec", {{}}).get("strategy") or {{}}
if strategy.get("type") != "Recreate" or strategy.get("rollingUpdate") is not None:
    raise SystemExit(
        "ERROR: clusterReceiver Deployment must use Recreate without rollingUpdate "
        "to prevent scraper overlap and remain valid for server-side apply."
    )
receivers = overlay["clusterReceiver"]["config"]["receivers"].values()
required = []
for receiver in receivers:
    tls = receiver.get("tls") or {{}}
    required.extend(tls[key] for key in ("ca_file", "cert_file", "key_file") if tls.get(key))
with open(sys.argv[6], encoding="utf-8") as handle:
    for line in handle:
        kind, separator, trust_path = line.rstrip("\n").partition("\t")
        if not separator or kind not in {{"sqlserver", "oracledb"}} or not trust_path:
            raise SystemExit("ERROR: invalid datasource trust-path preflight record.")
        required.append(trust_path)
containers = deployment.get("spec", {{}}).get("template", {{}}).get("spec", {{}}).get("containers", [])
collector_containers = [item for item in containers if item.get("name") == "otel-collector"]
if len(collector_containers) != 1:
    raise SystemExit("ERROR: rendered clusterReceiver must have exactly one otel-collector container.")
mounts = []
container = collector_containers[0]
mounts.extend(item.get("mountPath", "") for item in container.get("volumeMounts", []))
resources = container.get("resources") or {{}}
for resource_class in ("limits", "requests"):
    memory = str((resources.get(resource_class) or {{}}).get("memory") or "")
    match = __import__("re").fullmatch(r"([1-9][0-9]*)(Mi|Gi)", memory)
    if not match:
        raise SystemExit(f"ERROR: clusterReceiver memory {{resource_class}} is missing or invalid: {{memory!r}}.")
    actual_mib = int(match.group(1)) * (1024 if match.group(2) == "Gi" else 1)
    if actual_mib < required_memory_mib:
        raise SystemExit(
            f"ERROR: clusterReceiver memory {{resource_class}} {{actual_mib}}Mi is below {{required_memory_mib}}Mi."
        )
    cpu = str((resources.get(resource_class) or {{}}).get("cpu") or "")
    def millicores(value):
        return int(value[:-1]) if value.endswith("m") else int(float(value) * 1000)
    try:
        actual_cpu = millicores(cpu)
        minimum_cpu = millicores(required_cpu)
    except (TypeError, ValueError):
        raise SystemExit(f"ERROR: clusterReceiver CPU {{resource_class}} is invalid: {{cpu!r}}.")
    if actual_cpu < minimum_cpu:
        raise SystemExit(f"ERROR: clusterReceiver CPU {{resource_class}} is below audited sizing.")
token_env = [item for item in container.get("env", []) if item.get("name") == "SPLUNK_OBSERVABILITY_ACCESS_TOKEN"]
if len(token_env) != 1 or "value" in token_env[0]:
    raise SystemExit("ERROR: clusterReceiver must have exactly one Secret-backed chart token environment entry.")
secret_ref = ((token_env[0].get("valueFrom") or {{}}).get("secretKeyRef") or {{}})
if not secret_ref.get("name") or not secret_ref.get("key"):
    raise SystemExit("ERROR: clusterReceiver chart token environment is not Secret-backed.")
with open(sys.argv[5], "w", encoding="utf-8") as handle:
    handle.write(secret_ref["name"] + "\t" + secret_ref["key"] + "\n")
for required_path in required:
    path = pathlib.PurePosixPath(required_path)
    if not any(path == pathlib.PurePosixPath(mount) or pathlib.PurePosixPath(mount) in path.parents for mount in mounts if mount):
        raise SystemExit(f"ERROR: TLS file {{required_path}} is not covered by a cluster-receiver volumeMount.")
PY

IFS=$'\t' read -r token_secret token_key < "${{TMPDIR_LOCAL}}/token-ref"
[[ -n "${{token_secret}}" && -n "${{token_key}}" ]] || {{
    echo 'ERROR: rendered cluster receiver does not use a Secret-backed SPLUNK_OBSERVABILITY_ACCESS_TOKEN.' >&2
    exit 1
}}
check_secret_key "${{token_secret}}" "${{token_key}}" token

yq ea -r 'select(.kind == "ConfigMap" and (.metadata.name | test("otel-k8s-cluster-receiver$"))) | .data.relay' \
    "${{TMPDIR_LOCAL}}/rendered-manifests.yaml" > "${{TMPDIR_LOCAL}}/collector.yaml"
[[ -s "${{TMPDIR_LOCAL}}/collector.yaml" ]] || {{ echo 'ERROR: Could not extract the cluster-receiver collector config.' >&2; exit 1; }}
grep -Eo '\$\{{(env:)?[A-Za-z_][A-Za-z0-9_]*\}}' "${{TMPDIR_LOCAL}}/collector.yaml" \
    | sed -E 's/^\$\{{(env:)?//; s/\}}$//' | sort -u > "${{TMPDIR_LOCAL}}/env-names"
: > "${{TMPDIR_LOCAL}}/validate.env"
while IFS= read -r env_key; do
    [[ -n "${{env_key}}" ]] || continue
    if [[ "${{env_key}}" == "SPLUNK_MEMORY_LIMIT_MIB" ]]; then
        printf '%s=%s\n' "${{env_key}}" "{collector["memory_mib"]}" >> "${{TMPDIR_LOCAL}}/validate.env"
    else
        printf '%s=%s\n' "${{env_key}}" validation-placeholder >> "${{TMPDIR_LOCAL}}/validate.env"
    fi
done < "${{TMPDIR_LOCAL}}/env-names"

# The Kubernetes config can reference service-account and mounted TLS files
# that are absent from a local container runtime. Recreate a non-secret
# service-account shape and securely materialize only the exact Secret keys
# mapped to reviewed, read-only cluster-receiver paths.
SERVICEACCOUNT_FIXTURE="${{TMPDIR_LOCAL}}/serviceaccount"
mkdir -p "${{SERVICEACCOUNT_FIXTURE}}"
chmod 0700 "${{SERVICEACCOUNT_FIXTURE}}"
printf '%s' "${{NAMESPACE}}" > "${{SERVICEACCOUNT_FIXTURE}}/namespace"
printf '%s' validation-placeholder > "${{SERVICEACCOUNT_FIXTURE}}/token"
kubectl_ctx -n "${{NAMESPACE}}" get configmap kube-root-ca.crt -o json \
    > "${{TMPDIR_LOCAL}}/kube-root-ca.json"
python3 - "${{TMPDIR_LOCAL}}/kube-root-ca.json" "${{SERVICEACCOUNT_FIXTURE}}/ca.crt" <<'PY'
import json
import os
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    value = (json.load(handle).get("data") or {{}}).get("ca.crt", "")
if "-----BEGIN CERTIFICATE-----" not in value:
    raise SystemExit("ERROR: namespace kube-root-ca.crt ConfigMap has no certificate.")
descriptor = os.open(sys.argv[2], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    handle.write(value)
PY
chmod 0400 "${{SERVICEACCOUNT_FIXTURE}}"/*
COLLECTOR_VALIDATE_MOUNTS=(
    --volume "${{SERVICEACCOUNT_FIXTURE}}:/var/run/secrets/kubernetes.io/serviceaccount:ro"
)
python3 - "${{TMPDIR_LOCAL}}/deployment.json" "${{TLS_FILE_REQUIREMENTS_JSON}}" \
    "${{TMPDIR_LOCAL}}/datasource-trust-paths" \
    > "${{TMPDIR_LOCAL}}/runtime-secret-paths" <<'PY'
import json
import pathlib
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    deployment = json.load(handle)
required = [(item["path"], item["kind"]) for item in json.loads(sys.argv[2])]
with open(sys.argv[3], encoding="utf-8") as handle:
    for line in handle:
        kind, separator, path = line.rstrip("\n").partition("\t")
        if not separator:
            raise SystemExit("ERROR: invalid datasource trust-path record.")
        if kind == "oracledb":
            path = path.rstrip("/") + "/cwallet.sso"
        required.append((path, kind + "_trust"))

pod_spec = deployment.get("spec", {{}}).get("template", {{}}).get("spec", {{}})
containers = [item for item in pod_spec.get("containers", []) if item.get("name") == "otel-collector"]
if len(containers) != 1:
    raise SystemExit("ERROR: rendered cluster receiver must have one otel-collector container.")
mounts = containers[0].get("volumeMounts", [])
volumes = {{item.get("name"): item for item in pod_spec.get("volumes", [])}}
seen = set()
for path_text, kind in required:
    path = pathlib.PurePosixPath(path_text)
    candidates = []
    for mount in mounts:
        mount_path = pathlib.PurePosixPath(mount.get("mountPath", ""))
        try:
            relative = path.relative_to(mount_path)
        except ValueError:
            continue
        if mount.get("subPath"):
            if path != mount_path:
                continue
            relative = pathlib.PurePosixPath(mount["subPath"])
        candidates.append((len(mount_path.parts), mount, relative))
    if not candidates:
        raise SystemExit(f"ERROR: runtime trust path is not mounted: {{path_text}}")
    _, mount, relative = max(candidates, key=lambda item: item[0])
    if mount.get("readOnly") is not True:
        raise SystemExit(f"ERROR: runtime trust path mount must be read-only: {{path_text}}")
    volume = volumes.get(mount.get("name")) or {{}}
    secret = volume.get("secret") or {{}}
    secret_name = secret.get("secretName")
    if not secret_name:
        raise SystemExit(f"ERROR: runtime trust path must use a Secret volume: {{path_text}}")
    relative_text = str(relative)
    items = secret.get("items") or []
    if items:
        keys = [item.get("key") for item in items if item.get("path") == relative_text]
        if len(keys) != 1:
            raise SystemExit(f"ERROR: runtime trust path has no unique Secret item: {{path_text}}")
        secret_key = keys[0]
    else:
        secret_key = relative_text
    record = (path_text, kind, secret_name, secret_key)
    if record not in seen:
        print("\t".join(record))
        seen.add(record)
PY
tls_index=0
while IFS=$'\t' read -r runtime_path tls_kind secret_name secret_key; do
    [[ -n "${{runtime_path}}" && -n "${{tls_kind}}" && -n "${{secret_name}}" && -n "${{secret_key}}" ]] || continue
    tls_index=$((tls_index + 1))
    local_tls_file="${{TMPDIR_LOCAL}}/runtime-tls-${{tls_index}}"
    kubectl_ctx -n "${{NAMESPACE}}" get secret "${{secret_name}}" -o json \
        > "${{TMPDIR_LOCAL}}/runtime-secret.json"
    python3 - "${{TMPDIR_LOCAL}}/runtime-secret.json" "${{secret_key}}" "${{local_tls_file}}" <<'PY'
import base64
import json
import os
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    encoded = (json.load(handle).get("data") or {{}}).get(sys.argv[2], "")
try:
    value = base64.b64decode(encoded, validate=True)
except ValueError:
    raise SystemExit("ERROR: runtime TLS Secret key is not valid base64.")
if not value:
    raise SystemExit("ERROR: runtime TLS Secret key is empty.")
descriptor = os.open(sys.argv[3], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
with os.fdopen(descriptor, "wb") as handle:
    handle.write(value)
PY
    COLLECTOR_VALIDATE_MOUNTS+=(--volume "${{local_tls_file}}:${{runtime_path}}:ro")
done < "${{TMPDIR_LOCAL}}/runtime-secret-paths"
"${{CONTAINER_RUNTIME}}" run --rm --pull=always --network=none \
    --env-file "${{TMPDIR_LOCAL}}/validate.env" \
    --volume "${{TMPDIR_LOCAL}}/collector.yaml:/etc/otelcol/config.yaml:ro" \
    "${{COLLECTOR_VALIDATE_MOUNTS[@]}}" \
    "${{AUDITED_IMAGE}}" \
    validate --config=/etc/otelcol/config.yaml

DRY_RUN_FLAG=()
if [[ "${{K8S_APPLY_DRY_RUN:-false}}" == "true" ]]; then
    if (( HELM_MAJOR == 4 )); then
        DRY_RUN_FLAG=(--dry-run=server --hide-secret)
    else
        DRY_RUN_FLAG=(--dry-run --hide-secret)
    fi
fi
TRANSACTION_ID="dbmon-$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
DESCRIPTION_FLAG=(--description "${{TRANSACTION_ID}}")
latest_identity="$(read_release_identity)"
[[ "${{latest_identity}}" == "${{previous_identity}}" ]] || {{
    echo 'ERROR: Helm release identity changed during preflight; rerun against the new state.' >&2
    exit 1
}}
expected_revision="$((previous_revision + 1))"
if [[ "${{K8S_APPLY_DRY_RUN:-false}}" != "true" ]]; then
    python3 - "${{STATE}}" "${{OVERLAY}}" "${{RELEASE}}" "${{NAMESPACE}}" \
        "${{KUBE_CONTEXT}}" "${{previous_revision}}" "${{expected_revision}}" \
        "${{CHART_VERSION}}" "${{TRANSACTION_ID}}" \
        "${{TMPDIR_LOCAL}}/current-values.json" "${{current_chart}}" \
        "${{TMPDIR_LOCAL}}/current-manifest.yaml" <<'PY'
import hashlib
import json
import os
import sys

previous_state = None
if os.path.exists(sys.argv[1]):
    with open(sys.argv[1], encoding="utf-8") as handle:
        previous_state = json.load(handle)
with open(sys.argv[2], "rb") as handle:
    fingerprint = hashlib.sha256(handle.read()).hexdigest()
with open(sys.argv[10], encoding="utf-8") as handle:
    previous_values = json.load(handle)
previous_values_sha256 = hashlib.sha256(
    json.dumps(previous_values, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
with open(sys.argv[12], "rb") as handle:
    previous_manifest_sha256 = hashlib.sha256(handle.read()).hexdigest()
state = {{
    "phase": "applying",
    "release": sys.argv[3],
    "namespace": sys.argv[4],
    "kube_context": sys.argv[5],
    "previous_revision": int(sys.argv[6]),
    "applied_revision": int(sys.argv[7]),
    "chart_version": sys.argv[8],
    "transaction_id": sys.argv[9],
    "applied_description": sys.argv[9],
    "overlay_sha256": fingerprint,
    "previous_chart": sys.argv[11],
    "previous_manifest_sha256": previous_manifest_sha256,
    "previous_values_sha256": previous_values_sha256,
    "previous_state": previous_state,
}}
temporary = sys.argv[1] + f".pending.{{os.getpid()}}"
descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    json.dump(state, handle, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.replace(temporary, sys.argv[1])
directory = os.open(os.path.dirname(sys.argv[1]), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY
    APPLY_PREVIOUS_REVISION="${{previous_revision}}"
    APPLY_OWNED_REVISION="${{expected_revision}}"
    APPLY_TRANSACTION_ID="${{TRANSACTION_ID}}"
fi
"${{HELM_RENDER_COMMAND[@]}}" --kube-context "${{KUBE_CONTEXT}}" \
    upgrade "${{RELEASE}}" "${{CHART_PACKAGE}}" \
    --namespace "${{NAMESPACE}}" --values "${{TMPDIR_LOCAL}}/merged.yaml" \
    "${{HELM_POST_RENDERER_ARGS[@]}}" \
    "${{HELM_UPGRADE_SAFETY_ARGS[@]}}" \
    --timeout 5m "${{DESCRIPTION_FLAG[@]}}" "${{DRY_RUN_FLAG[@]}}"

if [[ "${{K8S_APPLY_DRY_RUN:-false}}" != "true" ]]; then
    post_upgrade_identity="$(helm_ctx history "${{RELEASE}}" -n "${{NAMESPACE}}" -o json \
        | python3 -c 'import json,sys; x=json.load(sys.stdin); print(str(x[-1].get("revision", "")) + "\t" + str(x[-1].get("description", "")))')"
    IFS=$'\t' read -r post_upgrade_revision post_upgrade_description <<< "${{post_upgrade_identity}}"
    [[ "${{post_upgrade_revision}}" == "${{expected_revision}}" && "${{post_upgrade_description}}" == "${{TRANSACTION_ID}}" ]] || {{
        echo 'ERROR: post-upgrade Helm revision is not owned by this transaction; pending state retained and no unowned revision will be rolled back.' >&2
        exit 1
    }}
    rollback_failed_apply() {{
        echo "ERROR: $1" >&2
        exit 1
    }}
    deployments_json="$(kubectl_ctx -n "${{NAMESPACE}}" get deployment -l "${{SELECTOR}}" -o json)" \
        || rollback_failed_apply 'DBMon cluster-receiver deployment lookup failed.'
    deployment="$(python3 -c 'import json,sys; x=json.load(sys.stdin).get("items", []); sys.exit("expected exactly one DBMon Deployment") if len(x) != 1 else print(x[0]["metadata"]["name"])' <<< "${{deployments_json}}")" \
        || rollback_failed_apply 'Expected exactly one DBMon cluster-receiver Deployment.'
    kubectl_ctx -n "${{NAMESPACE}}" rollout status "deployment/${{deployment}}" --timeout=180s \
        || rollback_failed_apply 'DBMon cluster-receiver rollout did not become ready.'
    live_deployment_json="$(kubectl_ctx -n "${{NAMESPACE}}" get "deployment/${{deployment}}" -o json)" \
        || rollback_failed_apply 'Could not read live Deployment state.'
    printf '%s\n' "${{live_deployment_json}}" > "${{TMPDIR_LOCAL}}/live-deployment.json"
    image="$(python3 - "{collector["memory_mib"]}" "{collector["cpu_limit"]}" \
        "${{AUDITED_IMAGE}}" "${{TMPDIR_LOCAL}}/live-deployment.json" <<'PY'
import json
import re
import sys

deployment = json.load(open(sys.argv[4], encoding="utf-8"))
if deployment.get("spec", {{}}).get("replicas") != 1 or deployment.get("status", {{}}).get("readyReplicas") != 1:
    raise SystemExit("desired and ready DBMon replicas must both equal one")
strategy = deployment.get("spec", {{}}).get("strategy") or {{}}
if strategy.get("type") != "Recreate" or strategy.get("rollingUpdate") is not None:
    raise SystemExit("live DBMon Deployment does not use a valid Recreate strategy")
containers = deployment.get("spec", {{}}).get("template", {{}}).get("spec", {{}}).get("containers", [])
containers = [item for item in containers if item.get("name") == "otel-collector"]
if len(containers) != 1 or containers[0].get("image") != sys.argv[3]:
    raise SystemExit("live named otel-collector container is not the audited image")
resources = containers[0].get("resources") or {{}}
for category in ("requests", "limits"):
    memory = str((resources.get(category) or {{}}).get("memory") or "")
    match = re.fullmatch(r"([1-9][0-9]*)(Mi|Gi)", memory)
    actual = int(match.group(1)) * (1024 if match and match.group(2) == "Gi" else 1) if match else 0
    if actual < int(sys.argv[1]):
        raise SystemExit(f"live collector memory {{category}} is below audited sizing")
    cpu = str((resources.get(category) or {{}}).get("cpu") or "")
    def millicores(value):
        return int(value[:-1]) if value.endswith("m") else int(float(value) * 1000)
    try:
        actual_cpu = millicores(cpu)
        required_cpu = millicores(sys.argv[2])
    except (TypeError, ValueError):
        raise SystemExit(f"live collector CPU {{category}} is invalid")
    if actual_cpu < required_cpu:
        raise SystemExit(f"live collector CPU {{category}} is below audited sizing")
print(containers[0]["image"])
PY
)" || rollback_failed_apply 'Live Deployment replicas, image, or memory resources failed validation.'
    image_id=""
    for ((pod_attempt = 1; pod_attempt <= 36; pod_attempt++)); do
        if pods_json="$(kubectl_ctx -n "${{NAMESPACE}}" get pod -l "${{SELECTOR}}" -o json)"; then
            printf '%s\n' "${{pods_json}}" > "${{TMPDIR_LOCAL}}/live-pods.json"
            if candidate_image_id="$(python3 - "${{TMPDIR_LOCAL}}/live-pods.json" <<'PY'
import json
import sys

pods = json.load(open(sys.argv[1], encoding="utf-8")).get("items", [])
if len(pods) != 1:
    raise SystemExit("expected exactly one selected DBMon pod")
statuses = [item for item in pods[0].get("status", {{}}).get("containerStatuses", []) if item.get("name") == "otel-collector"]
if len(statuses) != 1 or not statuses[0].get("ready"):
    raise SystemExit("named otel-collector container is not uniquely ready")
if statuses[0].get("restartCount", 0) != 0:
    raise SystemExit("new DBMon collector pod restarted during post-apply validation")
print(statuses[0].get("imageID", ""))
PY
            )" && [[ -n "${{candidate_image_id}}" ]]; then
                image_id="${{candidate_image_id}}"
                break
            fi
        fi
        sleep 5
    done
    [[ -n "${{image_id}}" ]] \
        || rollback_failed_apply 'Exactly one ready DBMon pod did not remain after Recreate rollout convergence.'
    case "${{image_id}}" in
        {AUDITED_IMAGE_DIGEST_CASE_PATTERN}) ;;
        *) rollback_failed_apply "Runtime imageID ${{image_id}} is not the audited manifest or a Linux platform digest." ;;
    esac
    sleep 15
    post_apply_logs="${{TMPDIR_LOCAL}}/post-apply-collector.log"
    if ! kubectl_ctx -n "${{NAMESPACE}}" logs "deployment/${{deployment}}" -c otel-collector \
        --since=2m --tail=-1 --limit-bytes=10485761 > "${{post_apply_logs}}" 2>&1; then
        rollback_failed_apply 'Unable to read post-apply cluster-receiver logs.'
    fi
    if (( $(wc -c < "${{post_apply_logs}}") > 10485760 )); then
        rollback_failed_apply 'Post-apply cluster-receiver logs exceeded the 10 MiB validation bound; narrow the validation window and retry.'
    fi
    recent_logs="$(<"${{post_apply_logs}}")"
    relevant_logs="$(printf '%s\n' "${{recent_logs}}" | grep -E "${{DBMON_COMPONENT_PATTERN}}" || true)"
    # PostgreSQL query-plan collection is best effort. Upstream deliberately
    # logs these per-statement EXPLAIN failures and still records the top-query
    # event because monitoring users should not execute arbitrary application
    # SQL. Do not mistake those two exact source messages for receiver failure.
    actionable_logs="$(printf '%s\n' "${{relevant_logs}}" \
        | grep -Eiv 'postgresqlreceiver@v[0-9.]+/(client|scraper)\.go:[0-9]+[[:space:]]+failed to explain (statement|query)' || true)"
    if printf '%s\n' "${{relevant_logs}}" \
        | grep -Eqi 'unauthorized|forbidden|(^|[^0-9])(401|403|429)([^0-9]|$)|too many requests|resource.?exhausted|rate.?limit|throttl|queue.*full|dropp?(ed|ing).*(telemetry|data)|authentication failed|password authentication failed|access denied|login failed|connection refused|connection reset|broken pipe|bad connection|unexpected EOF|server closed the connection|connection (was )?closed|no such host|no route to host|i/o timeout|x509:|certificate.*(invalid|unknown)|failed to export|export(ing)? (failed|failure)|error exporting|unable to export' \
        || printf '%s\n' "${{actionable_logs}}" \
        | grep -Eqi '(^|[[:space:]"=:])(error|fatal)([[:space:]"=:]|$)|unauthorized|forbidden|(^|[^0-9])(401|403|429)([^0-9]|$)|too many requests|resource.?exhausted|rate.?limit|throttl|queue.*full|dropp?(ed|ing).*(telemetry|data)|deadline exceeded|no such host|authentication failed|access denied|login failed|permission denied|connection refused|no route to host|i/o timeout|x509:|certificate.*(invalid|unknown)|failed to (start|export|fetch|collect|scrape|connect|query)|export(ing)? (failed|failure)|error (exporting|scraping|reading|collecting|querying)|unable to (export|connect|collect|query)|cannot start|duplicate scraper|ORA-[0-9]+'; then
        echo 'ERROR: DBMon receiver logged a critical startup/connectivity failure.' >&2
        echo '       Raw collector lines are suppressed because they can contain database connection or query material.' >&2
        rollback_failed_apply 'Critical DBMon receiver log validation failed.'
    fi
    final_identity="$(helm_ctx history "${{RELEASE}}" -n "${{NAMESPACE}}" -o json \
        | python3 -c 'import json,sys; x=json.load(sys.stdin); print(str(x[-1].get("revision", "")) + "\t" + str(x[-1].get("description", "")))')" \
        || rollback_failed_apply 'Could not verify the final Helm revision identity.'
    IFS=$'\t' read -r final_revision final_description <<< "${{final_identity}}"
    [[ "${{final_revision}}" == "${{expected_revision}}" && "${{final_description}}" == "${{TRANSACTION_ID}}" ]] \
        || rollback_failed_apply 'Helm revision drifted during post-apply validation; pending state retained.'
    if ! python3 - "${{STATE}}" "${{expected_revision}}" "${{TRANSACTION_ID}}" \
        "${{image}}" "${{image_id}}" <<'PY'
import json
import os
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)
if (
    state.get("phase") != "applying"
    or state.get("applied_revision") != int(sys.argv[2])
    or state.get("transaction_id") != sys.argv[3]
    or state.get("applied_description") != sys.argv[3]
):
    raise SystemExit("ERROR: pending DBMon state identity changed before commit.")
state["phase"] = "validated"
state["running_image"] = sys.argv[4]
state["running_image_id"] = sys.argv[5]
temporary = sys.argv[1] + f".tmp.{{os.getpid()}}"
descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(state, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, sys.argv[1])
    directory = os.open(os.path.dirname(sys.argv[1]), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
except BaseException:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
    raise
PY
    then
        rollback_failed_apply 'Applied successfully but could not persist trusted rollback state.'
    fi
    APPLY_COMMITTED=true
    APPLY_OWNED_REVISION=""
    echo "DBMon Kubernetes apply completed at Helm revision ${{expected_revision}}; tenant target probes are still required for telemetry proof."
fi
"""


def render_rollback_k8s_script(*, collector: dict[str, Any]) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
[[ "${{ACCEPT_K8S_ROLLBACK:-false}}" == "true" ]] || {{ echo 'ERROR: --accept-k8s-rollback is required.' >&2; exit 1; }}
for tool in helm kubectl python3 mktemp rm; do
    command -v "${{tool}}" >/dev/null 2>&1 || {{ echo "ERROR: ${{tool}} is required." >&2; exit 1; }}
done
RELEASE="{collector["release_name"]}"
NAMESPACE="{collector["namespace"]}"
KUBE_CONTEXT="{collector["kube_context"]}"
SELECTOR="app=splunk-otel-collector,component=otel-k8s-cluster-receiver,release=${{RELEASE}}"
helm_ctx() {{ command helm --kube-context "${{KUBE_CONTEXT}}" "$@"; }}
kubectl_ctx() {{ command kubectl --context "${{KUBE_CONTEXT}}" "$@"; }}
read_release_identity() {{
    helm_ctx history "${{RELEASE}}" -n "${{NAMESPACE}}" -o json | python3 -c '
import json
import sys

history = json.load(sys.stdin)
if not isinstance(history, list) or not history:
    raise SystemExit("Helm history is empty")
revision = history[-1].get("revision")
description = history[-1].get("description")
if isinstance(revision, bool):
    raise SystemExit("Helm revision is invalid")
try:
    revision = int(revision)
except (TypeError, ValueError):
    raise SystemExit("Helm revision is invalid")
if revision < 1 or not isinstance(description, str) or not description or any(character in description for character in "\\t\\r\\n"):
    raise SystemExit("Helm release identity is invalid")
print("%d\\t%s" % (revision, description))
'
}}
actual_context="$(kubectl config current-context)"
[[ "${{actual_context}}" == "${{KUBE_CONTEXT}}" ]] || {{
    echo "ERROR: active kube context ${{actual_context:-<none>}} does not match reviewed context ${{KUBE_CONTEXT}}." >&2
    exit 1
}}
STATE="${{XDG_STATE_HOME:-${{HOME:?HOME is required}}/.local/state}}/splunk-dbmon/${{NAMESPACE}}-${{RELEASE}}.json"
[[ "${{STATE}}" =~ ^/[A-Za-z0-9._/@:-]+$ ]] || {{ echo 'ERROR: invalid DBMon state path.' >&2; exit 1; }}
[[ -f "${{STATE}}" && ! -L "${{STATE}}" ]] || {{ echo 'ERROR: trusted Kubernetes DBMon apply state was not found.' >&2; exit 1; }}
LOCK_FILE="${{STATE%.json}}.lock"
if [[ -e "${{LOCK_FILE}}" || -L "${{LOCK_FILE}}" ]]; then
    python3 - "${{LOCK_FILE}}" <<'PY'
import os
import stat
import sys
info = os.lstat(sys.argv[1])
if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or info.st_mode & 0o077:
    raise SystemExit("ERROR: unsafe Kubernetes DBMon transaction lock file.")
PY
fi
exec 9>>"${{LOCK_FILE}}"
chmod 0600 "${{LOCK_FILE}}"
if ! python3 - "${{LOCK_FILE}}" <<'PY'
import fcntl
import os
import stat
import sys

try:
    descriptor = os.fstat(9)
    target = os.stat(sys.argv[1], follow_symlinks=False)
    if not stat.S_ISREG(descriptor.st_mode) or (descriptor.st_dev, descriptor.st_ino) != (target.st_dev, target.st_ino):
        raise OSError("file descriptor 9 is not the reviewed DBMon lock file")
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
except (BlockingIOError, OSError):
    raise SystemExit(1)
PY
then
    echo 'ERROR: another DBMon apply or rollback transaction is active.' >&2
    exit 1
fi
TMPDIR_LOCAL="$(mktemp -d)"
QUIESCED_DEPLOYMENT=""
QUIESCE_ACTIVE=false
ROLLBACK_HELM_COMPLETED=false
RECOVERY_SIGNAL_STATUS=0

restore_previous_state() {{
    local restored_revision="$1" restored_description="$2"
    python3 - "${{STATE}}" "${{restored_revision}}" "${{restored_description}}" <<'PY'
import json
import os
import sys

try:
    restored_revision = int(sys.argv[2])
except (TypeError, ValueError):
    raise SystemExit("ERROR: restored DBMon revision is invalid.")
restored_description = sys.argv[3]
if restored_revision < 1 or not restored_description or any(
    character in restored_description for character in "\\t\\r\\n"
):
    raise SystemExit("ERROR: restored DBMon release identity is invalid.")
with open(sys.argv[1], encoding="utf-8") as handle:
    current = json.load(handle)
previous = current.get("previous_state")
if previous is None:
    os.unlink(sys.argv[1])
    directory = os.open(os.path.dirname(sys.argv[1]), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    raise SystemExit(0)
if not isinstance(previous, dict):
    raise SystemExit("ERROR: DBMon previous_state is invalid.")
previous["applied_revision"] = restored_revision
previous["applied_description"] = restored_description
previous["phase"] = "validated"
temporary = sys.argv[1] + f".restore.{{os.getpid()}}"
descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(previous, handle, sort_keys=True)
        handle.write("\\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, sys.argv[1])
    directory = os.open(os.path.dirname(sys.argv[1]), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
except BaseException:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
    raise
PY
}}
quiesce_cluster_receiver_for_rollback() {{
    local deployment_identity deployment_name desired_replicas pod_count
    if ! deployment_identity="$(kubectl_ctx -n "${{NAMESPACE}}" get deployment -l "${{SELECTOR}}" -o json \
        | python3 -c 'import json,sys; x=json.load(sys.stdin).get("items", []); sys.exit("expected exactly one DBMon Deployment before rollback") if len(x) != 1 else None; r=x[0].get("spec", {{}}).get("replicas", 1); sys.exit("DBMon rollback only supports zero or one desired replica") if r not in (0, 1) else print(x[0]["metadata"]["name"] + "\t" + str(r))')"; then
        echo 'ERROR: could not identify exactly one DBMon cluster-receiver Deployment before rollback; state retained.' >&2
        return 1
    fi
    IFS=$'\t' read -r deployment_name desired_replicas <<< "${{deployment_identity}}"
    QUIESCED_DEPLOYMENT="${{deployment_name}}"
    QUIESCE_ACTIVE=true
    ROLLBACK_HELM_COMPLETED=false
    if [[ "${{desired_replicas}}" == "1" ]] \
        && ! kubectl_ctx -n "${{NAMESPACE}}" scale "deployment/${{deployment_name}}" --replicas=0; then
        echo 'ERROR: could not quiesce the DBMon cluster-receiver before rollback; state retained.' >&2
        return 1
    fi
    pod_count="$(kubectl_ctx -n "${{NAMESPACE}}" get pod -l "${{SELECTOR}}" -o json \
        | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("items", [])))' 2>/dev/null || true)"
    if [[ "${{pod_count}}" == "0" ]]; then
        return 0
    fi
    if kubectl_ctx -n "${{NAMESPACE}}" wait --for=delete pod -l "${{SELECTOR}}" --timeout=180s; then
        return 0
    fi
    pod_count="$(kubectl_ctx -n "${{NAMESPACE}}" get pod -l "${{SELECTOR}}" -o json \
        | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("items", [])))' 2>/dev/null || true)"
    if [[ "${{pod_count}}" == "0" ]]; then
        return 0
    fi
    if kubectl_ctx -n "${{NAMESPACE}}" scale "deployment/${{deployment_name}}" --replicas=1 >/dev/null 2>&1; then
        QUIESCE_ACTIVE=false
    fi
    echo 'ERROR: DBMon cluster-receiver pods did not terminate before rollback; replica count was restored and state retained.' >&2
    return 1
}}
resume_cluster_receiver_after_failed_rollback() {{
    local deployment_name
    deployment_name="${{QUIESCED_DEPLOYMENT}}"
    if [[ -z "${{deployment_name}}" ]]; then
        deployment_name="$(kubectl_ctx -n "${{NAMESPACE}}" get deployment -l "${{SELECTOR}}" -o json \
            | python3 -c 'import json,sys; x=json.load(sys.stdin).get("items", []); print(x[0]["metadata"]["name"] if len(x) == 1 else "")' 2>/dev/null || true)"
    fi
    [[ -n "${{deployment_name}}" ]] || return 1
    if kubectl_ctx -n "${{NAMESPACE}}" scale "deployment/${{deployment_name}}" --replicas=1 >/dev/null 2>&1; then
        QUIESCE_ACTIVE=false
        return 0
    fi
    return 1
}}
restored_release_is_ready() {{
    local release_status deployment_count
    release_status="$(helm_ctx status "${{RELEASE}}" -n "${{NAMESPACE}}" -o json 2>/dev/null \
        | python3 -c 'import json,sys; print((json.load(sys.stdin).get("info") or {{}}).get("status", ""))' 2>/dev/null || true)"
    [[ "${{release_status}}" == "deployed" ]] || return 1
    deployment_count="$(kubectl_ctx -n "${{NAMESPACE}}" get deployment -l "${{SELECTOR}}" -o json 2>/dev/null \
        | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("items", [])))' 2>/dev/null || true)"
    if [[ "${{deployment_count}}" == "0" ]]; then
        return 0
    fi
    [[ "${{deployment_count}}" == "1" ]] || return 1
    kubectl_ctx -n "${{NAMESPACE}}" rollout status deployment -l "${{SELECTOR}}" --timeout=180s >/dev/null
}}

rollback_cleanup() {{
    local status=$?
    trap - EXIT
    trap 'RECOVERY_SIGNAL_STATUS=130' INT
    trap 'RECOVERY_SIGNAL_STATUS=143' TERM
    set +e
    if [[ "${{QUIESCE_ACTIVE}}" == "true" && "${{ROLLBACK_HELM_COMPLETED}}" != "true" ]]; then
        if ! resume_cluster_receiver_after_failed_rollback; then
            echo 'ERROR: interrupted rollback recovery could not restore the cluster-receiver replica.' >&2
            if [[ "${{status}}" == "0" ]]; then status=1; fi
        fi
    fi
    rm -rf -- "${{TMPDIR_LOCAL}}"
    trap - INT TERM
    if [[ "${{RECOVERY_SIGNAL_STATUS}}" != "0" ]]; then status="${{RECOVERY_SIGNAL_STATUS}}"; fi
    exit "${{status}}"
}}
trap 'exit 130' INT
trap 'exit 143' TERM
trap rollback_cleanup EXIT

state_values="$(python3 - "${{STATE}}" "${{RELEASE}}" "${{NAMESPACE}}" "${{KUBE_CONTEXT}}" <<'PY'
import json
import os
import stat
import sys

info = os.lstat(sys.argv[1])
if (
    not stat.S_ISREG(info.st_mode)
    or info.st_mode & 0o077
    or info.st_uid != os.geteuid()
    or info.st_nlink != 1
):
    raise SystemExit("ERROR: DBMon state must be an owner-only regular file.")
with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)
for key, value in {{"release": sys.argv[2], "namespace": sys.argv[3], "kube_context": sys.argv[4]}}.items():
    if state.get(key) != value:
        raise SystemExit(f"ERROR: DBMon state {{key}} does not match this rollback helper.")
previous = state.get("previous_revision")
applied = state.get("applied_revision")
if not isinstance(previous, int) or previous < 1 or not isinstance(applied, int) or applied < 1:
    raise SystemExit("ERROR: DBMon state contains invalid Helm revisions.")
phase = state.get("phase")
if phase not in {{"applying", "validated"}}:
    raise SystemExit("ERROR: DBMon state phase is not recoverable by this helper.")
transaction = state.get("transaction_id")
if not isinstance(transaction, str) or not transaction.startswith("dbmon-"):
    raise SystemExit("ERROR: DBMon state transaction identity is invalid.")
applied_description = state.get("applied_description", transaction)
if not isinstance(applied_description, str) or not applied_description or any(
    character in applied_description for character in "\\t\\r\\n"
):
    raise SystemExit("ERROR: DBMon state applied description is invalid.")
print(f"{{phase}}\t{{previous}}\t{{applied}}\t{{applied_description}}")
PY
)"
IFS=$'\t' read -r PHASE PREVIOUS_REVISION APPLIED_REVISION APPLIED_DESCRIPTION <<< "${{state_values}}"
REVISION="${{1:-${{PREVIOUS_REVISION}}}}"
[[ "${{REVISION}}" =~ ^[1-9][0-9]*$ ]] || {{ echo 'ERROR: Helm revision must be a positive integer.' >&2; exit 1; }}
[[ "${{REVISION}}" == "${{PREVIOUS_REVISION}}" ]] || {{
    echo 'ERROR: explicit rollback revision does not match the recorded previous revision; use manual Helm recovery after review.' >&2
    exit 1
}}
CURRENT_IDENTITY="$(read_release_identity)"
IFS=$'\t' read -r CURRENT_REVISION CURRENT_DESCRIPTION <<< "${{CURRENT_IDENTITY}}"

if [[ "${{PHASE}}" == "applying" && "${{CURRENT_REVISION}}" == "${{PREVIOUS_REVISION}}" ]]; then
    restored_release_is_ready || {{ echo 'ERROR: pre-upgrade Helm content is present but its workload is not ready; state retained.' >&2; exit 1; }}
    restore_previous_state "${{CURRENT_REVISION}}" "${{CURRENT_DESCRIPTION}}"
    echo "Recovered a pre-upgrade interrupted transaction at Helm revision ${{CURRENT_REVISION}}; no Helm mutation was needed."
    exit 0
fi

if [[ "${{CURRENT_REVISION}}" != "${{APPLIED_REVISION}}" ]]; then
    CURRENT_CHART="$(helm_ctx list -n "${{NAMESPACE}}" -f "^${{RELEASE}}$" -o json \
        | python3 -c 'import json,sys; x=json.load(sys.stdin); print(x[0].get("chart", "") if x else "")')"
    helm_ctx get values "${{RELEASE}}" -n "${{NAMESPACE}}" -o json > "${{TMPDIR_LOCAL}}/current-values.json"
    helm_ctx get manifest "${{RELEASE}}" -n "${{NAMESPACE}}" > "${{TMPDIR_LOCAL}}/current-manifest.yaml"
    if python3 - "${{STATE}}" "${{TMPDIR_LOCAL}}/current-values.json" \
        "${{TMPDIR_LOCAL}}/current-manifest.yaml" "${{CURRENT_CHART}}" <<'PY'
import hashlib
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)
with open(sys.argv[2], encoding="utf-8") as handle:
    values = json.load(handle)
values_digest = hashlib.sha256(
    json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
with open(sys.argv[3], "rb") as handle:
    manifest_digest = hashlib.sha256(handle.read()).hexdigest()
matches = (
    values_digest == state.get("previous_values_sha256")
    and manifest_digest == state.get("previous_manifest_sha256")
    and sys.argv[4] == state.get("previous_chart")
)
raise SystemExit(0 if matches else 1)
PY
    then
        restored_release_is_ready || {{ echo 'ERROR: exact pre-apply Helm content is present but its workload is not ready; state retained.' >&2; exit 1; }}
        restore_previous_state "${{CURRENT_REVISION}}" "${{CURRENT_DESCRIPTION}}"
        echo "Reconciled an already-restored pre-apply Helm state at revision ${{CURRENT_REVISION}}; no Helm mutation was needed."
        exit 0
    fi
    echo "ERROR: Helm revision drift detected (current ${{CURRENT_REVISION}}, recorded ${{APPLIED_REVISION}}) and content is not the exact pre-apply release; refusing stale rollback." >&2
    exit 1
fi
if [[ "${{CURRENT_DESCRIPTION}}" != "${{APPLIED_DESCRIPTION}}" ]]; then
    echo 'ERROR: current Helm revision is not owned by the recorded DBMon transaction; refusing rollback.' >&2
    exit 1
fi
quiesce_cluster_receiver_for_rollback
if ! helm_ctx rollback "${{RELEASE}}" "${{REVISION}}" -n "${{NAMESPACE}}" --wait --timeout 5m; then
    if ! resume_cluster_receiver_after_failed_rollback; then
        echo 'ERROR: Helm rollback failed and the cluster-receiver could not be resumed automatically.' >&2
    fi
    echo 'ERROR: Helm rollback failed; state retained for manual recovery.' >&2
    exit 1
fi
ROLLBACK_HELM_COMPLETED=true
QUIESCE_ACTIVE=false
RESTORED_STATUS="$(helm_ctx status "${{RELEASE}}" -n "${{NAMESPACE}}" -o json \
    | python3 -c 'import json,sys; print((json.load(sys.stdin).get("info") or {{}}).get("status", ""))')"
[[ "${{RESTORED_STATUS}}" == "deployed" ]] || {{ echo 'ERROR: rolled-back Helm release is not deployed; state retained.' >&2; exit 1; }}
RESTORED_IDENTITY="$(read_release_identity)"
IFS=$'\t' read -r RESTORED_REVISION RESTORED_DESCRIPTION <<< "${{RESTORED_IDENTITY}}"
deployment_count="$(kubectl_ctx -n "${{NAMESPACE}}" get deployment -l "${{SELECTOR}}" -o json \
    | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("items", [])))')"
if [[ "${{deployment_count}}" == "1" ]]; then
    kubectl_ctx -n "${{NAMESPACE}}" rollout status deployment -l "${{SELECTOR}}" --timeout=180s
elif [[ "${{deployment_count}}" != "0" ]]; then
    echo "ERROR: rollback produced ${{deployment_count}} matching cluster-receiver Deployments; state retained." >&2
    exit 1
fi
# Consume or rebase trusted state only after the restored release is deployed
# and its cluster-receiver workload has converged.
restore_previous_state "${{RESTORED_REVISION}}" "${{RESTORED_DESCRIPTION}}"
echo "Restored Helm revision ${{REVISION}} as live revision ${{RESTORED_REVISION}} and safely advanced the DBMon rollback chain."
"""


def secure_env_helper() -> str:
    return r'''#!/usr/bin/env python3
"""Validate systemd-style environment files and run without shell sourcing."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import stat
import subprocess
import sys
import urllib.parse
from pathlib import Path

KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def validate_secure_datasource(name: str, engine: str, value: str) -> None:
    parsed = urllib.parse.urlsplit(value)
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    options: dict[str, str] = {}
    raw_options: dict[str, str] = {}
    for key, option in pairs:
        normalized = key.strip().casefold()
        if normalized in options:
            raise ValueError(f"{name} repeats datasource option {normalized}")
        options[normalized] = option.strip().casefold()
        raw_options[normalized] = option.strip()
    trust_path = ""
    if engine == "sqlserver":
        if parsed.scheme.casefold() != "sqlserver" or not parsed.hostname or parsed.fragment:
            raise ValueError(f"{name} must be a URL-form sqlserver datasource")
        if options.get("encrypt") not in {"true", "yes", "mandatory", "strict", "1"}:
            raise ValueError(f"{name} must enable SQL Server encryption")
        if options.get("trustservercertificate") not in {"false", "no", "0"}:
            raise ValueError(f"{name} must disable TrustServerCertificate")
        trust_path = raw_options.get("certificate", "")
    elif engine == "oracledb":
        if parsed.scheme.casefold() != "oracle" or not parsed.hostname or parsed.fragment:
            raise ValueError(f"{name} must be a URL-form oracle datasource")
        if options.get("ssl") not in {"enable", "true"}:
            raise ValueError(f"{name} must enable Oracle SSL")
        if options.get("ssl verify") != "true":
            raise ValueError(f"{name} must enable Oracle SSL Verify")
        trust_path = raw_options.get("wallet", "")
    else:
        raise ValueError(f"unsupported secure datasource engine {engine}")
    if not trust_path:
        return
    path = Path(trust_path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{name} trust path must be absolute and traversal-free")
    if engine == "sqlserver":
        if path.suffix.casefold() != ".pem":
            raise ValueError(f"{name} certificate path must use the .pem suffix")
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ValueError(f"{name} certificate path must be a regular, non-symlink file")
        if not os.access(path, os.R_OK):
            raise ValueError(f"{name} certificate path is not readable")
    else:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"{name} wallet path must be a non-symlink directory")
        wallet = path / "cwallet.sso"
        wallet_info = wallet.lstat()
        if stat.S_ISLNK(wallet_info.st_mode) or not stat.S_ISREG(wallet_info.st_mode):
            raise ValueError(f"{name} wallet must contain a regular cwallet.sso file")
        if not os.access(wallet, os.R_OK):
            raise ValueError(f"{name} cwallet.sso is not readable")


def load(path_text: str, *, strict: bool, copy_to: str = "") -> dict[str, str]:
    path = Path(path_text)
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ValueError(f"{path} must be a regular, non-symlink file")
    if before.st_size > 1024 * 1024:
        raise ValueError(f"{path} exceeds the 1 MiB safety limit")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError(f"{path} changed while it was being opened")
        raw = os.read(descriptor, 1024 * 1024 + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise ValueError(f"{path} changed while it was being read")
    if len(raw) != info.st_size:
        raise ValueError(f"{path} could not be read atomically")
    if b"\x00" in raw:
        raise ValueError(f"{path} contains a NUL byte")
    if strict and info.st_nlink != 1:
        raise ValueError(f"{path} must have exactly one hard link")
    if not strict and (info.st_uid != 0 or info.st_nlink != 1):
        raise ValueError(f"{path} base environment must be root-owned with one hard link")
    forbidden = 0o077 if strict else 0o022
    if stat.S_IMODE(info.st_mode) & forbidden:
        expected = (
            "owner-only (for example 0400 or 0600)"
            if strict
            else "not group/world writable"
        )
        raise ValueError(f"{path} permissions must be {expected}")
    if copy_to:
        destination = Path(copy_to)
        destination_info = destination.lstat()
        if stat.S_ISLNK(destination_info.st_mode) or not stat.S_ISREG(
            destination_info.st_mode
        ):
            raise ValueError(f"{destination} must be a regular, non-symlink staging file")
        output_flags = (
            os.O_WRONLY
            | os.O_TRUNC
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        output = os.open(destination, output_flags)
        try:
            os.fchmod(output, 0o600)
            view = memoryview(raw)
            while view:
                written = os.write(output, view)
                if written <= 0:
                    raise OSError("short write while staging credentials")
                view = view[written:]
            os.fsync(output)
        finally:
            os.close(output)
    values: dict[str, str] = {}
    text = raw.decode("utf-8", "strict")
    for number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, raw_value = line.partition("=")
        key = key.strip()
        if not separator or not KEY.fullmatch(key):
            raise ValueError(f"{path}:{number}: invalid environment assignment")
        if key in values:
            raise ValueError(f"{path}:{number}: duplicate key {key}")
        parsed = shlex.split(raw_value, comments=False, posix=True)
        if len(parsed) > 1:
            raise ValueError(f"{path}:{number}: quote values containing whitespace")
        values[key] = parsed[0] if parsed else ""
        if key == "SPLUNK_ACCESS_TOKEN" and any(
            character.isspace() or character == "\x00" for character in values[key]
        ):
            raise ValueError(f"{path}:{number}: access token cannot contain whitespace or NUL")
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-file", default="")
    parser.add_argument("--strict-file", required=True)
    parser.add_argument("--allowed", action="append", default=[])
    parser.add_argument("--required", action="append", default=[])
    parser.add_argument("--minimum-memory-mib", type=int, default=0)
    parser.add_argument("--secure-datasource", action="append", default=[])
    parser.add_argument("--synthetic-secrets", action="store_true")
    parser.add_argument("--copy-to", default="")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        values: dict[str, str] = {}
        if args.base_file and Path(args.base_file).exists():
            values.update(load(args.base_file, strict=False))
        strict_values = load(args.strict_file, strict=True, copy_to=args.copy_to)
        unexpected = sorted(set(strict_values) - set(args.allowed))
        if unexpected:
            raise ValueError(
                "strict credential file contains keys outside the rendered allowlist: "
                + ", ".join(unexpected)
            )
        missing = [key for key in args.required if not strict_values.get(key)]
        if missing:
            raise ValueError("missing nonempty values: " + ", ".join(missing))
        values.update(strict_values)
        if args.minimum_memory_mib:
            try:
                actual_memory = int(strict_values.get("SPLUNK_MEMORY_LIMIT_MIB", ""))
            except ValueError as exc:
                raise ValueError("SPLUNK_MEMORY_LIMIT_MIB must be an integer") from exc
            if actual_memory < args.minimum_memory_mib:
                raise ValueError(
                    f"SPLUNK_MEMORY_LIMIT_MIB={actual_memory} is below required "
                    f"{args.minimum_memory_mib}"
                )
        secure_engines: dict[str, str] = {}
        for item in args.secure_datasource:
            name, separator, engine = item.partition("=")
            if not separator or not KEY.fullmatch(name):
                raise ValueError("--secure-datasource must be ENV_NAME=engine")
            if not strict_values.get(name):
                raise ValueError(f"missing nonempty secure datasource {name}")
            validate_secure_datasource(name, engine, strict_values[name])
            secure_engines[name] = engine
        if args.command:
            command = args.command[1:] if args.command[0] == "--" else args.command
            if not command:
                raise ValueError("empty command")
            environment = os.environ.copy()
            environment.update(values)
            if args.synthetic_secrets:
                for name in list(environment):
                    if re.search(
                        r"(?i)(password|passwd|token|secret|authorization|api[_-]?key|datasource|connection[_-]?string|private[_-]?key)",
                        name,
                    ):
                        environment[name] = "dbmon-validation-placeholder"
                for name in strict_values:
                    if name == "SPLUNK_MEMORY_LIMIT_MIB":
                        continue
                    environment[name] = "dbmon-validation-placeholder"
                for name, engine in secure_engines.items():
                    environment[name] = (
                        "sqlserver://validation:placeholder@db.invalid:1433?encrypt=true&trustservercertificate=false"
                        if engine == "sqlserver"
                        else "oracle://validation:placeholder@db.invalid:1521/service?SSL=enable&SSL%20Verify=true"
                    )
            return subprocess.run(command, env=environment, check=False).returncode
        return 0
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


def base_config_audit_helper() -> str:
    return r'''#!/usr/bin/env python3
"""Reject base Collector configs that already own DBMon component IDs."""

import json
import sys

try:
    parsed = json.load(sys.stdin)
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise SystemExit(f"ERROR: base collector config is not valid JSON: {exc}") from exc
if not isinstance(parsed, dict):
    raise SystemExit("ERROR: base collector config must be a mapping.")

types = ("postgresql", "sqlserver", "oracledb", "mysql")


def db_id(value):
    text = str(value)
    return text in types or any(text.startswith(item + "/") for item in types)


receivers = parsed.get("receivers") or {}
if any(db_id(key) for key in receivers):
    raise SystemExit(
        "ERROR: base collector config already contains a DB receiver; migrate it "
        "before applying this sole-scraper fragment."
    )
reserved = []
for section, names in (
    ("exporters", {"otlp_http/dbmon", "signalfx/dbmon"}),
    (
        "processors",
        {
            "memory_limiter/dbmon",
            "batch/dbmon",
            "resource_detection/dbmon",
            "resource/mysql_service_instance_id",
        },
    ),
):
    collisions = set(parsed.get(section) or {}) & names
    if collisions:
        reserved.extend(f"{section}.{name}" for name in sorted(collisions))
pipelines = ((parsed.get("service") or {}).get("pipelines") or {})
reserved.extend(
    f"service.pipelines.{name}"
    for name in pipelines
    if str(name).startswith(("metrics/dbmon", "logs/dbmon"))
)
if reserved:
    raise SystemExit(
        "ERROR: base collector config already owns reserved DBMon component IDs: "
        + ", ".join(reserved)
    )
'''


def handoff_linux() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Populate ${HERE}/dbmon.env.template into a separate owner-only secret file (for example chmod 0400 or 0600)."
echo "Do not source that file. Apply with:"
echo "  setup.sh --apply-linux --db-credentials-env-file /secure/path/dbmon.env --accept-linux-apply ..."
echo "The action validates collector 0.158.0, both configs, service health, and writes rollback state."
echo "If the service is absent, first use splunk-observability-otel-collector-setup to install and validate the pinned Linux collector."
"""


def render_apply_linux_script(
    *,
    scrape_owner: str,
    collector: dict[str, Any],
    targets: list[dict[str, Any]],
    source_config_sha256: str,
) -> str:
    required_names = ["SPLUNK_ACCESS_TOKEN", *required_credential_envs(targets)]
    required_flags = " ".join(f'--required "{name}"' for name in required_names)
    allowed_flags = " ".join(
        f'--allowed "{name}"'
        for name in ["SPLUNK_MEMORY_LIMIT_MIB", *required_names]
    )
    secure_datasource_flags = " ".join(
        f'--secure-datasource "{target["credentials"]["datasource_var"]}={target["type"]}"'
        for target in targets
        if target["connection_mode"] == "datasource"
    )
    tls_requirements_json = json.dumps(tls_file_requirements(targets))
    tls_checks = f"""python3 - '{tls_requirements_json}' <<'PY'
import json
import os
import stat
import sys

for requirement in json.loads(sys.argv[1]):
    path = requirement["path"]
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
        raise SystemExit(f"ERROR: TLS path {{path}} must be a root-owned, single-link regular file.")
    forbidden = 0o077 if requirement["kind"] == "private_key" else 0o022
    if info.st_mode & forbidden:
        raise SystemExit(f"ERROR: TLS path {{path}} has unsafe permissions for {{requirement['kind']}}.")
PY"""
    receiver_pattern = "|".join(re.escape(target["receiver_id"]) for target in targets)
    version = collector["version"]
    return rf'''#!/usr/bin/env bash
set -euo pipefail

SCRAPE_OWNER="{scrape_owner}"
UNSUPPORTED_TARGET_COUNT="{sum(1 for target in targets if target['support_status'] != 'official')}"
[[ "${{SCRAPE_OWNER}}" == "linux" ]] || {{ echo "ERROR: spec scrape_owner is ${{SCRAPE_OWNER}}, not linux." >&2; exit 1; }}
[[ "${{UNSUPPORTED_TARGET_COUNT}}" == "0" ]] || {{ echo 'ERROR: unsupported-target opt-in is render/validate-only; production Linux apply is disabled.' >&2; exit 1; }}
[[ "$(id -u)" == "0" ]] || {{ echo 'ERROR: run the Linux apply as root or with sudo.' >&2; exit 1; }}
for tool in python3 systemctl install cp sha256sum journalctl yq; do
    command -v "${{tool}}" >/dev/null 2>&1 || {{ echo "ERROR: ${{tool}} is required." >&2; exit 1; }}
done
yq --version 2>&1 | grep -Eq 'version[[:space:]]+v?4\.' || {{
    echo 'ERROR: Mike Farah yq major version 4 is required.' >&2
    exit 1
}}

DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)"
SOURCE_CONFIG="${{DIR}}/linux/collector-dbmon.fragment.yaml"
EXPECTED_SOURCE_CONFIG_SHA256="{source_config_sha256}"
ENV_SOURCE="${{DBMON_ENV_FILE:-}}"
BASE_CONFIG="${{SPLUNK_BASE_CONFIG:-/etc/otel/collector/agent_config.yaml}}"
BASE_ENV="${{SPLUNK_BASE_ENV_FILE:-/etc/otel/collector/splunk-otel-collector.conf}}"
DEST_CONFIG="/etc/otel/collector/dbmon.yaml"
DEST_ENV="/etc/otel/collector/dbmon.env"
DROPIN_DIR="/etc/systemd/system/splunk-otel-collector.service.d"
DROPIN="${{DROPIN_DIR}}/20-dbmon.conf"
STATE_DIR="/var/lib/splunk-otel-collector"
STATE="${{STATE_DIR}}/dbmon-state.json"
SERVICE="splunk-otel-collector.service"
OTELCOL="/usr/bin/otelcol"
DBMON_COMPONENT_PATTERN="{receiver_pattern}|logs/dbmon(_core|_mysql)?|metrics/dbmon(_core|_mysql)?|otlp_http/dbmon|signalfx/dbmon"

actual_source_config_sha256="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "${{SOURCE_CONFIG}}")"
[[ "${{actual_source_config_sha256}}" == "${{EXPECTED_SOURCE_CONFIG_SHA256}}" ]] || {{
    echo 'ERROR: rendered Linux DBMon fragment changed after packet generation; re-render and review before apply.' >&2
    exit 1
}}

[[ -n "${{ENV_SOURCE}}" ]] || {{ echo 'ERROR: --db-credentials-env-file is required.' >&2; exit 1; }}
[[ -x "${{OTELCOL}}" ]] || {{ echo 'ERROR: otelcol is not installed.' >&2; exit 1; }}
[[ "${{OTELCOL}}" =~ ^/[A-Za-z0-9._/-]+$ && "${{BASE_CONFIG}}" =~ ^/[A-Za-z0-9._/-]+$ && "${{BASE_ENV}}" =~ ^/[A-Za-z0-9._/-]+$ ]] || {{
    echo 'ERROR: collector and base paths must be absolute and contain only safe path characters.' >&2
    exit 1
}}
[[ -f "${{BASE_CONFIG}}" && ! -L "${{BASE_CONFIG}}" ]] || {{ echo "ERROR: invalid base config ${{BASE_CONFIG}}." >&2; exit 1; }}
python3 - "${{OTELCOL}}" "${{BASE_CONFIG}}" <<'PY'
import os
import stat
import sys

for path in sys.argv[1:]:
    info = os.lstat(path)
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != 0
        or info.st_mode & 0o022
        or info.st_nlink != 1
    ):
        raise SystemExit(
            f"ERROR: privileged collector path {{path}} must be a root-owned, "
            "non-writable, single-link regular file."
        )
PY
systemctl is-active --quiet "${{SERVICE}}" || {{ echo 'ERROR: base collector service must already be active; use splunk-observability-otel-collector-setup first.' >&2; exit 1; }}
if ! yq -o=json '.' "${{BASE_CONFIG}}" | python3 "${{DIR}}/scripts/audit-base-config.py"; then
    echo 'ERROR: base collector config is invalid or collides with DBMon components.' >&2
    exit 1
fi
{tls_checks}
systemctl cat "${{SERVICE}}" >/dev/null
EFFECTIVE_EXECSTART="$(systemctl show "${{SERVICE}}" --property=ExecStart --value)"
python3 - "${{EFFECTIVE_EXECSTART}}" "${{OTELCOL}}" "${{BASE_CONFIG}}" "${{STATE}}" \
    "${{DEST_CONFIG}}" "${{DEST_ENV}}" "${{DROPIN}}" <<'PY'
import hashlib
import json
import os
import re
import shlex
import stat
import sys

match = re.search(r"argv\[\]=(.+?)\s+;\s+(?:ignore_errors|start_time)=", sys.argv[1])
if not match:
    raise SystemExit("ERROR: could not audit the effective systemd ExecStart; use the manual host handoff.")
try:
    argv = shlex.split(match.group(1))
except ValueError as exc:
    raise SystemExit(f"ERROR: could not parse effective ExecStart: {{exc}}") from exc
base_commands = ([sys.argv[2], "--config=" + sys.argv[3]], [sys.argv[2], "--config", sys.argv[3]])
managed_commands = (
    [sys.argv[2], "--config=" + sys.argv[3], "--config=" + sys.argv[5]],
    [sys.argv[2], "--config", sys.argv[3], "--config", sys.argv[5]],
)
state_exists = os.path.lexists(sys.argv[4])
if argv in base_commands and state_exists:
    raise SystemExit(
        "ERROR: trusted DBMon state exists but the effective ExecStart no longer includes "
        "the managed fragment; reconcile drift before reapply."
    )
if argv in managed_commands:
    if not state_exists:
        raise SystemExit("ERROR: managed DBMon ExecStart has no trusted apply state.")
    info = os.lstat(sys.argv[4])
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_mode & 0o077
        or info.st_uid != 0
        or info.st_nlink != 1
    ):
        raise SystemExit("ERROR: Linux DBMon state must be an owner-only regular file.")
    with open(sys.argv[4], encoding="utf-8") as handle:
        state = json.load(handle)
    if state.get("phase") != "validated":
        raise SystemExit("ERROR: Linux DBMon state is pending recovery; run rollback before reapply.")
    expected = state.get("applied_hashes")
    if not isinstance(expected, dict) or set(expected) != set(sys.argv[5:8]):
        raise SystemExit("ERROR: Linux DBMon state applied-hash inventory is invalid.")
    for path in sys.argv[5:8]:
        if not os.path.isfile(path) or os.path.islink(path):
            raise SystemExit(f"ERROR: applied DBMon file drift detected at {{path}}.")
        with open(path, "rb") as handle:
            actual = hashlib.sha256(handle.read()).hexdigest()
        if expected[path] != actual:
            raise SystemExit(f"ERROR: applied DBMon file drift detected at {{path}}.")
elif argv not in base_commands:
    raise SystemExit(
        "ERROR: effective collector ExecStart has additional or different arguments; "
        "the generated action will not discard feature gates/config providers. Use the manual handoff."
    )
PY
SERVICE_MAIN_PID="$(systemctl show "${{SERVICE}}" --property=MainPID --value)"
python3 - "{collector["memory_mib"]}" "{collector["cpu_limit"]}" "${{SERVICE_MAIN_PID}}" <<'PY'
import os
import pathlib
import sys

try:
    service_pid = int(sys.argv[3])
except ValueError as exc:
    raise SystemExit("ERROR: collector service MainPID is invalid.") from exc
if service_pid <= 0:
    raise SystemExit("ERROR: collector service has no live MainPID for cgroup sizing audit.")

entries = []
try:
    for line in pathlib.Path(f"/proc/{{service_pid}}/cgroup").read_text(encoding="utf-8").splitlines():
        _, controllers, relative = line.split(":", 2)
        cgroup_path = pathlib.PurePosixPath(relative)
        if not cgroup_path.is_absolute() or any(part in {{".", ".."}} for part in cgroup_path.parts):
            raise ValueError("unsafe cgroup path")
        entries.append((set(filter(None, controllers.split(","))), cgroup_path))
except (FileNotFoundError, OSError, ValueError) as exc:
    raise SystemExit("ERROR: cannot resolve the collector service cgroup.") from exc

mounts = []
try:
    for line in pathlib.Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
        before, separator, after = line.partition(" - ")
        if not separator:
            raise ValueError("invalid mountinfo record")
        fields = before.split()
        filesystem = after.split()
        if len(fields) < 5 or len(filesystem) < 3 or filesystem[0] not in {{"cgroup", "cgroup2"}}:
            continue
        def decode_mountinfo_path(value):
            return value.replace(r"\040", " ").replace(r"\011", "\t").replace(r"\012", "\n").replace(r"\134", "\\")

        mount_root = pathlib.PurePosixPath(decode_mountinfo_path(fields[3]))
        mountpoint = pathlib.Path(
            decode_mountinfo_path(fields[4])
        )
        if not mount_root.is_absolute() or not mountpoint.is_absolute():
            raise ValueError("cgroup mount paths must be absolute")
        controllers = (
            set(filesystem[1].split(",")) | set(filesystem[2].split(","))
            if filesystem[0] == "cgroup"
            else set()
        )
        mounts.append((filesystem[0], controllers, mount_root, mountpoint))
except (OSError, ValueError) as exc:
    raise SystemExit("ERROR: cannot resolve cgroup controller mounts.") from exc

def cgroup_files(controller, filename):
    paths = []
    seen = set()
    matched_hierarchy = False
    for controllers, cgroup_path in entries:
        if not controllers:
            candidates = [
                (mount_root, mountpoint)
                for kind, _, mount_root, mountpoint in mounts
                if kind == "cgroup2"
            ]
        elif controller in controllers:
            candidates = [
                (mount_root, mountpoint)
                for kind, mount_controllers, mount_root, mountpoint in mounts
                if kind == "cgroup" and controller in mount_controllers
            ]
        else:
            continue
        matched_hierarchy = True
        if not candidates:
            raise SystemExit(f"ERROR: cannot resolve the {{controller}} cgroup mount.")
        mapped = False
        for mount_root, root in candidates:
            try:
                relative = cgroup_path.relative_to(mount_root)
            except ValueError:
                continue
            mapped = True
            current = root.joinpath(*relative.parts)
            while True:
                candidate = current / filename
                if candidate not in seen:
                    seen.add(candidate)
                    paths.append(candidate)
                if current == root:
                    break
                if root not in current.parents:
                    raise SystemExit("ERROR: cgroup path escaped its controller mount.")
                current = current.parent
        if not mapped:
            raise SystemExit(f"ERROR: cannot map the {{controller}} cgroup path to its controller mount root.")
    if entries and not matched_hierarchy and any(not controllers for controllers, _ in entries):
        raise SystemExit(f"ERROR: cannot audit the unified {{controller}} cgroup hierarchy.")
    return paths

required = int(sys.argv[1]) * 1024 * 1024
limits = []
meminfo = pathlib.Path("/proc/meminfo")
if meminfo.is_file():
    for line in meminfo.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            limits.append(int(line.split()[1]) * 1024)
            break
for path in [
    *cgroup_files("memory", "memory.max"),
    *cgroup_files("memory", "memory.limit_in_bytes"),
]:
    try:
        value = path.read_text(encoding="utf-8").strip()
        if value != "max":
            parsed = int(value)
            if parsed > 0:
                limits.append(parsed)
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        raise SystemExit(f"ERROR: cannot audit cgroup memory limit {{path}}.") from exc
if not limits or min(limits) < required:
    actual = min(limits) // (1024 * 1024) if limits else 0
    raise SystemExit(f"ERROR: effective host/cgroup memory {{actual}}Mi is below required {collector["memory_mib"]}Mi.")
required_cpu = int(sys.argv[2][:-1]) / 1000 if sys.argv[2].endswith("m") else float(sys.argv[2])
cpu_limits = [float(os.cpu_count() or 0)]
for path in cgroup_files("cpu", "cpu.max"):
    try:
        quota, period = path.read_text(encoding="utf-8").split()
        if quota != "max":
            cpu_limits.append(int(quota) / int(period))
    except FileNotFoundError:
        pass
    except (OSError, ValueError, ZeroDivisionError) as exc:
        raise SystemExit(f"ERROR: cannot audit cgroup CPU limit {{path}}.") from exc
for quota_path in cgroup_files("cpu", "cpu.cfs_quota_us"):
    try:
        quota = int(quota_path.read_text(encoding="utf-8"))
        period = int(quota_path.with_name("cpu.cfs_period_us").read_text(encoding="utf-8"))
        if quota > 0:
            cpu_limits.append(quota / period)
    except FileNotFoundError:
        pass
    except (OSError, ValueError, ZeroDivisionError) as exc:
        raise SystemExit(f"ERROR: cannot audit cgroup CPU quota {{quota_path}}.") from exc
for cpuset_name in ("cpuset.cpus.effective", "cpuset.cpus"):
    for cpuset_path in cgroup_files("cpuset", cpuset_name):
        try:
            value = cpuset_path.read_text(encoding="utf-8").strip()
            if not value:
                continue
            count = 0
            for item in value.split(","):
                if "-" in item:
                    start, end = (int(part) for part in item.split("-", 1))
                    if end < start:
                        raise ValueError("descending CPU set range")
                    count += end - start + 1
                else:
                    int(item)
                    count += 1
            if count > 0:
                cpu_limits.append(float(count))
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            raise SystemExit(f"ERROR: cannot audit cgroup CPU set {{cpuset_path}}.") from exc
actual_cpu = min(cpu_limits) if cpu_limits else 0
if actual_cpu < required_cpu:
    raise SystemExit(f"ERROR: effective host/cgroup CPU {{actual_cpu:.3g}} is below required {{required_cpu:.3g}} cores.")
PY
actual_version="$(${{OTELCOL}} --version 2>&1)"
python3 - "${{actual_version}}" "{version}" <<'PY'
import re
import sys
matches = re.findall(r"(?<![0-9A-Za-z_.+-])v?(\d+\.\d+\.\d+)(?![0-9A-Za-z_.+-])", sys.argv[1])
if matches != [sys.argv[2].lstrip("v")]:
    raise SystemExit("ERROR: collector binary did not report the exact audited version.")
PY

TMP_CONFIG=""
TMP_ENV=""
TMP_DROPIN=""
BACKUP=""
TRANSACTION_ACTIVE=false
COMMITTED=false
cleanup() {{
    local temp_file
    for temp_file in "${{TMP_CONFIG}}" "${{TMP_ENV}}" "${{TMP_DROPIN}}"; do
        [[ -z "${{temp_file}}" ]] || rm -f -- "${{temp_file}}"
    done
}}
on_exit() {{
    local status=$?
    trap - EXIT
    set +e
    if [[ "${{TRANSACTION_ACTIVE}}" == "true" && "${{COMMITTED}}" != "true" ]]; then
        echo 'ERROR: Linux DBMon transaction did not commit; invoking resumable recovery.' >&2
        if ! DBMON_INHERITED_LOCK=true ACCEPT_LINUX_ROLLBACK=true \
            bash "${{DIR}}/scripts/rollback-dbmon-linux.sh"; then
            echo "ERROR: automatic recovery failed; trusted pending state and backup ${{BACKUP}} were retained." >&2
            status=1
        fi
    fi
    cleanup
    exit "${{status}}"
}}
trap on_exit EXIT
SOURCE_ENV_ARGS=(--strict-file "${{ENV_SOURCE}}" --minimum-memory-mib "{collector["memory_mib"]}" {allowed_flags} {required_flags} {secure_datasource_flags})
if [[ -f "${{BASE_ENV}}" ]]; then
    SOURCE_ENV_ARGS=(--base-file "${{BASE_ENV}}" "${{SOURCE_ENV_ARGS[@]}}")
fi
python3 "${{DIR}}/scripts/secure-env.py" "${{SOURCE_ENV_ARGS[@]}}" --synthetic-secrets -- \
    "${{OTELCOL}}" validate --config="${{BASE_CONFIG}}" --config="${{SOURCE_CONFIG}}"

if [[ "${{LINUX_APPLY_DRY_RUN:-false}}" == "true" ]]; then
    echo 'DRY-RUN: validation passed; no host files or services were changed.'
    exit 0
fi
[[ "${{ACCEPT_LINUX_APPLY:-false}}" == "true" ]] || {{ echo 'ERROR: --accept-linux-apply is required.' >&2; exit 1; }}

python3 - "${{STATE_DIR}}" <<'PY'
import os
import pathlib
import stat
import sys

target = pathlib.Path(sys.argv[1])
current = pathlib.Path(target.root)
for part in target.parts[1:]:
    current /= part
    try:
        info = os.lstat(current)
    except FileNotFoundError:
        os.mkdir(current, 0o750)
        info = os.lstat(current)
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != 0
        or info.st_mode & 0o022
    ):
        raise SystemExit(f"ERROR: unsafe privileged state directory component: {{current}}")
PY
LOCK_FILE="${{STATE_DIR}}/dbmon.lock"
if [[ -e "${{LOCK_FILE}}" || -L "${{LOCK_FILE}}" ]]; then
    python3 - "${{LOCK_FILE}}" <<'PY'
import os
import stat
import sys
info = os.lstat(sys.argv[1])
if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o077:
    raise SystemExit("ERROR: unsafe Linux DBMon transaction lock file.")
PY
fi
exec 9>>"${{LOCK_FILE}}"
chmod 0600 "${{LOCK_FILE}}"
if ! python3 - "${{LOCK_FILE}}" <<'PY'
import fcntl
import os
import stat
import sys

try:
    descriptor = os.fstat(9)
    target = os.stat(sys.argv[1], follow_symlinks=False)
    if not stat.S_ISREG(descriptor.st_mode) or (descriptor.st_dev, descriptor.st_ino) != (target.st_dev, target.st_ino):
        raise OSError("file descriptor 9 is not the reviewed DBMon lock file")
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
except (BlockingIOError, OSError):
    raise SystemExit(1)
PY
then
    echo 'ERROR: another Linux DBMon apply or rollback transaction is active.' >&2
    exit 1
fi
if [[ -e "${{STATE}}" || -L "${{STATE}}" ]]; then
    python3 - "${{STATE}}" "${{DEST_CONFIG}}" "${{DEST_ENV}}" "${{DROPIN}}" <<'PY'
import hashlib
import json
import os
import stat
import sys

info = os.lstat(sys.argv[1])
if (
    not stat.S_ISREG(info.st_mode)
    or stat.S_ISLNK(info.st_mode)
    or info.st_mode & 0o077
    or info.st_uid != 0
    or info.st_nlink != 1
):
    raise SystemExit("ERROR: existing Linux DBMon state must be an owner-only regular file.")
with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)
if state.get("state_version") != 2:
    raise SystemExit(
        "ERROR: legacy Linux DBMon state cannot be adopted safely; use the rollback "
        "helper from the packet that created it before applying this packet."
    )
if state.get("phase") != "validated":
    raise SystemExit("ERROR: existing Linux DBMon state is pending recovery; run rollback before reapply.")
expected = state.get("applied_hashes")
if not isinstance(expected, dict):
    raise SystemExit("ERROR: existing Linux DBMon state lacks applied hashes.")
for path in sys.argv[2:]:
    if not os.path.isfile(path) or os.path.islink(path):
        raise SystemExit(f"ERROR: applied DBMon file drift detected at {{path}}.")
    with open(path, "rb") as handle:
        actual = hashlib.sha256(handle.read()).hexdigest()
    if expected.get(path) != actual:
        raise SystemExit(f"ERROR: applied DBMon file drift detected at {{path}}; reconcile before reapply.")
PY
else
    for managed_path in "${{DEST_CONFIG}}" "${{DEST_ENV}}" "${{DROPIN}}"; do
        if [[ -e "${{managed_path}}" || -L "${{managed_path}}" ]]; then
            echo "ERROR: ${{managed_path}} already exists without trusted DBMon state; refusing to overwrite unowned content." >&2
            exit 1
        fi
    done
fi
TRANSACTION_ID="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
BACKUP="${{STATE_DIR}}/dbmon-backups/${{TRANSACTION_ID}}"
TMP_CONFIG="/etc/otel/collector/.dbmon.yaml.${{TRANSACTION_ID}}"
TMP_ENV="/etc/otel/collector/.dbmon.env.${{TRANSACTION_ID}}"
TMP_DROPIN="${{DROPIN_DIR}}/.20-dbmon.conf.${{TRANSACTION_ID}}"
RESTORE_CONFIG="/etc/otel/collector/.dbmon.yaml.restore.${{TRANSACTION_ID}}"
RESTORE_ENV="/etc/otel/collector/.dbmon.env.restore.${{TRANSACTION_ID}}"
RESTORE_DROPIN="${{DROPIN_DIR}}/.20-dbmon.conf.restore.${{TRANSACTION_ID}}"
python3 - "${{STATE}}" "${{TRANSACTION_ID}}" "${{BACKUP}}" \
    "${{DEST_CONFIG}}" "${{TMP_CONFIG}}" "${{RESTORE_CONFIG}}" \
    "${{DEST_ENV}}" "${{TMP_ENV}}" "${{RESTORE_ENV}}" \
    "${{DROPIN}}" "${{TMP_DROPIN}}" "${{RESTORE_DROPIN}}" \
    "${{BASE_CONFIG}}" "${{OTELCOL}}" "{version}" <<'PY'
import hashlib
import json
import os
import stat
import sys

state_path = sys.argv[1]
transaction_id = sys.argv[2]
backup = sys.argv[3]
destinations = (sys.argv[4], sys.argv[7], sys.argv[10])
staging_paths = {{sys.argv[4]: sys.argv[5], sys.argv[7]: sys.argv[8], sys.argv[10]: sys.argv[11]}}
restore_paths = {{sys.argv[4]: sys.argv[6], sys.argv[7]: sys.argv[9], sys.argv[10]: sys.argv[12]}}
for path in (backup, *staging_paths.values(), *restore_paths.values()):
    if os.path.lexists(path):
        raise SystemExit(f"ERROR: transaction artifact already exists before preparation: {{path}}")

previous_state = None
if os.path.exists(state_path):
    with open(state_path, encoding="utf-8") as handle:
        previous_state = json.load(handle)
    if previous_state.get("state_version") != 2 or previous_state.get("phase") != "validated":
        raise SystemExit("ERROR: existing Linux DBMon state is not a committed v2 transaction.")

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")

def validate_committed(candidate, depth=0):
    if depth > 64:
        raise SystemExit("ERROR: Linux DBMon previous-state chain is unreasonably deep.")
    if candidate.get("state_version") != 2 or candidate.get("phase") != "validated":
        raise SystemExit("ERROR: Linux DBMon previous-state chain is not committed.")
    hashes = candidate.get("applied_hashes")
    if not isinstance(hashes, dict) or set(hashes) != set(destinations):
        raise SystemExit("ERROR: Linux DBMon previous-state applied hashes are invalid.")
    parent = candidate.get("previous_state")
    parent_digest = candidate.get("previous_state_sha256")
    if parent is None:
        if parent_digest is not None:
            raise SystemExit("ERROR: Linux DBMon previous-state chain has an orphan digest.")
        return
    if not isinstance(parent, dict) or hashlib.sha256(canonical(parent)).hexdigest() != parent_digest:
        raise SystemExit("ERROR: Linux DBMon previous-state chain digest is invalid.")
    validate_committed(parent, depth + 1)

if previous_state is not None:
    validate_committed(previous_state)

state = {{
    "state_version": 2,
    "transaction_id": transaction_id,
    "phase": "preparing",
    "backup": backup,
    "service": "splunk-otel-collector.service",
    "base_config": sys.argv[13],
    "collector_binary": sys.argv[14],
    "collector_version": sys.argv[15],
    "staging_paths": staging_paths,
    "restore_paths": restore_paths,
    "applied_hashes": None,
    "backup_manifest_sha256": None,
    "previous_state": previous_state,
    "previous_state_sha256": (
        hashlib.sha256(canonical(previous_state)).hexdigest()
        if previous_state is not None
        else None
    ),
}}
temporary = state_path + f".prepare.{{transaction_id}}"
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
descriptor = os.open(temporary, flags, 0o600)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(state, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, state_path)
    directory = os.open(os.path.dirname(state_path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
except BaseException:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
    raise
PY
TRANSACTION_ACTIVE=true
python3 - "${{BACKUP}}" <<'PY'
import os
import pathlib
import stat
import sys

backup = pathlib.Path(sys.argv[1])
parent = backup.parent
try:
    info = os.lstat(parent)
except FileNotFoundError:
    os.mkdir(parent, 0o700)
    info = os.lstat(parent)
if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
    raise SystemExit("ERROR: Linux DBMon backup parent is not trusted.")
os.mkdir(backup, 0o700)
PY
backup_file() {{
    local source="$1" label="$2"
    if [[ -e "${{source}}" || -L "${{source}}" ]]; then
        cp -a -- "${{source}}" "${{BACKUP}}/${{label}}"
    else
        : > "${{BACKUP}}/${{label}}.missing"
    fi
}}
backup_file "${{DEST_CONFIG}}" dbmon.yaml
backup_file "${{DEST_ENV}}" dbmon.env
backup_file "${{DROPIN}}" 20-dbmon.conf
(cd "${{BACKUP}}" && sha256sum -- * > SHA256SUMS)

install -d -m 0755 /etc/otel/collector "${{DROPIN_DIR}}"
python3 - "${{TMP_CONFIG}}" "${{TMP_ENV}}" "${{TMP_DROPIN}}" <<'PY'
import os
import stat
import sys

for path, mode in ((sys.argv[1], 0o644), (sys.argv[2], 0o600), (sys.argv[3], 0o644)):
    parent = os.path.dirname(path)
    info = os.lstat(parent)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise SystemExit(f"ERROR: unsafe Linux DBMon staging parent: {{parent}}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, mode)
    os.fchmod(descriptor, mode)
    os.close(descriptor)
PY
install -m 0644 -o root -g root "${{SOURCE_CONFIG}}" "${{TMP_CONFIG}}"
COPY_ENV_ARGS=(--strict-file "${{ENV_SOURCE}}" --copy-to "${{TMP_ENV}}" --minimum-memory-mib "{collector["memory_mib"]}" {allowed_flags} {required_flags} {secure_datasource_flags})
STAGED_ENV_ARGS=(--strict-file "${{TMP_ENV}}" --minimum-memory-mib "{collector["memory_mib"]}" {allowed_flags} {required_flags} {secure_datasource_flags})
if [[ -f "${{BASE_ENV}}" ]]; then
    COPY_ENV_ARGS=(--base-file "${{BASE_ENV}}" "${{COPY_ENV_ARGS[@]}}")
    STAGED_ENV_ARGS=(--base-file "${{BASE_ENV}}" "${{STAGED_ENV_ARGS[@]}}")
fi
python3 "${{DIR}}/scripts/secure-env.py" "${{COPY_ENV_ARGS[@]}}"
python3 "${{DIR}}/scripts/secure-env.py" "${{STAGED_ENV_ARGS[@]}}" --synthetic-secrets -- \
    "${{OTELCOL}}" validate --config="${{BASE_CONFIG}}" --config="${{TMP_CONFIG}}"
printf '%s\n' '[Service]' \
    'EnvironmentFile=/etc/otel/collector/dbmon.env' \
    'ExecStart=' \
    "ExecStart=${{OTELCOL}} --config=${{BASE_CONFIG}} --config=${{DEST_CONFIG}}" > "${{TMP_DROPIN}}"
chmod 0644 "${{TMP_DROPIN}}"
chown root:root "${{TMP_DROPIN}}"
python3 - "${{STATE}}" "${{BACKUP}}" "${{DEST_CONFIG}}" "${{TMP_CONFIG}}" \
    "${{DEST_ENV}}" "${{TMP_ENV}}" "${{DROPIN}}" "${{TMP_DROPIN}}" \
    "${{TRANSACTION_ID}}" "${{EXPECTED_SOURCE_CONFIG_SHA256}}" <<'PY'
import hashlib
import json
import os
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)
if state.get("state_version") != 2 or state.get("phase") != "preparing":
    raise SystemExit("ERROR: Linux DBMon preparation state changed before staging completed.")
if state.get("transaction_id") != sys.argv[9] or state.get("backup") != sys.argv[2]:
    raise SystemExit("ERROR: Linux DBMon transaction identity changed during preparation.")
hashes = {{}}
for destination, staged in ((sys.argv[3], sys.argv[4]), (sys.argv[5], sys.argv[6]), (sys.argv[7], sys.argv[8])):
    with open(staged, "rb") as handle:
        hashes[destination] = hashlib.sha256(handle.read()).hexdigest()
if hashes[sys.argv[3]] != sys.argv[10]:
    raise SystemExit("ERROR: staged DBMon collector fragment differs from the reviewed packet.")
manifest_path = os.path.join(sys.argv[2], "SHA256SUMS")
with open(manifest_path, "rb") as handle:
    manifest_sha256 = hashlib.sha256(handle.read()).hexdigest()
backup_files = [entry.path for entry in os.scandir(sys.argv[2]) if entry.is_file(follow_symlinks=False)]
for path in (sys.argv[4], sys.argv[6], sys.argv[8], *backup_files):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
for directory_path in {{os.path.dirname(sys.argv[4]), os.path.dirname(sys.argv[6]), os.path.dirname(sys.argv[8]), sys.argv[2], os.path.dirname(sys.argv[2])}}:
    descriptor = os.open(directory_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
state["phase"] = "applying"
state["applied_hashes"] = hashes
state["backup_manifest_sha256"] = manifest_sha256
temporary = sys.argv[1] + f".applying.{{os.getpid()}}"
descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(state, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, sys.argv[1])
    directory = os.open(os.path.dirname(sys.argv[1]), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
except BaseException:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
    raise
PY
mv -f -- "${{TMP_CONFIG}}" "${{DEST_CONFIG}}"
mv -f -- "${{TMP_ENV}}" "${{DEST_ENV}}"
mv -f -- "${{TMP_DROPIN}}" "${{DROPIN}}"
python3 - "${{DEST_CONFIG}}" "${{DEST_ENV}}" "${{DROPIN}}" <<'PY'
import os
import sys
for directory_path in {{os.path.dirname(path) for path in sys.argv[1:]}}:
    descriptor = os.open(directory_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
PY

systemctl daemon-reload
POST_EXECSTART="$(systemctl show "${{SERVICE}}" --property=ExecStart --value)"
POST_ENVFILES="$(systemctl show "${{SERVICE}}" --property=EnvironmentFiles --value)"
python3 - "${{POST_EXECSTART}}" "${{OTELCOL}}" "${{BASE_CONFIG}}" "${{DEST_CONFIG}}" \
    "${{POST_ENVFILES}}" "${{DEST_ENV}}" <<'PY'
import re
import shlex
import sys

match = re.search(r"argv\[\]=(.+?)\s+;\s+(?:ignore_errors|start_time)=", sys.argv[1])
if not match:
    raise SystemExit("ERROR: effective post-reload ExecStart could not be audited.")
argv = shlex.split(match.group(1))
allowed = (
    [sys.argv[2], "--config=" + sys.argv[3], "--config=" + sys.argv[4]],
    [sys.argv[2], "--config", sys.argv[3], "--config", sys.argv[4]],
)
if argv not in allowed:
    raise SystemExit("ERROR: a later systemd override prevented the managed DBMon ExecStart.")
if sys.argv[6] not in sys.argv[5]:
    raise SystemExit("ERROR: effective systemd EnvironmentFiles does not include DBMon credentials.")
PY
APPLY_STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
APPLY_FAILED=false
if ! systemctl restart "${{SERVICE}}"; then
    APPLY_FAILED=true
else
    sleep 15
    if ! systemctl is-active --quiet "${{SERVICE}}"; then
        APPLY_FAILED=true
    elif ! RECENT_LOGS="$(journalctl -q -u "${{SERVICE}}" --since "${{APPLY_STARTED}}" --no-pager -o cat)"; then
        APPLY_FAILED=true
    else
        RELEVANT_LOGS="$(printf '%s\n' "${{RECENT_LOGS}}" | grep -E "${{DBMON_COMPONENT_PATTERN}}" || true)"
        ACTIONABLE_LOGS="$(printf '%s\n' "${{RELEVANT_LOGS}}" \
            | grep -Eiv 'postgresqlreceiver@v[0-9.]+/(client|scraper)\.go:[0-9]+[[:space:]]+failed to explain (statement|query)' || true)"
        if printf '%s\n' "${{RELEVANT_LOGS}}" | grep -Eqi 'unauthorized|forbidden|(^|[^0-9])(401|403|429)([^0-9]|$)|too many requests|resource.?exhausted|rate.?limit|throttl|queue.*full|dropp?(ed|ing).*(telemetry|data)|authentication failed|password authentication failed|access denied|login failed|connection refused|connection reset|broken pipe|bad connection|unexpected EOF|server closed the connection|connection (was )?closed|no such host|no route to host|i/o timeout|x509:|certificate.*(invalid|unknown)|failed to export|export(ing)? (failed|failure)|error exporting|unable to export' \
            || printf '%s\n' "${{ACTIONABLE_LOGS}}" | grep -Eqi '(^|[[:space:]"=:])(error|fatal)([[:space:]"=:]|$)|unauthorized|forbidden|(^|[^0-9])(401|403|429)([^0-9]|$)|too many requests|resource.?exhausted|rate.?limit|throttl|queue.*full|dropp?(ed|ing).*(telemetry|data)|deadline exceeded|no such host|authentication failed|access denied|login failed|permission denied|connection refused|no route to host|i/o timeout|x509:|certificate.*(invalid|unknown)|failed to (start|export|fetch|collect|scrape|connect|query)|export(ing)? (failed|failure)|error (exporting|scraping|reading|collecting|querying)|unable to (export|connect|collect|query)|cannot start|duplicate scraper|ORA-[0-9]+'; then
            echo 'ERROR: collector emitted a DBMon startup/connectivity failure:' >&2
            echo '       Raw collector lines are suppressed because they can contain database connection or query material.' >&2
            APPLY_FAILED=true
        fi
    fi
fi
if [[ "${{APPLY_FAILED}}" == "true" ]]; then
    echo 'ERROR: collector restart or scoped DBMon health validation failed.' >&2
    exit 1
fi
python3 - "${{STATE}}" "${{BACKUP}}" "${{DEST_CONFIG}}" "${{DEST_ENV}}" "${{DROPIN}}" \
    "${{BASE_CONFIG}}" "${{OTELCOL}}" "{version}" <<'PY'
import hashlib
import json
import os
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)
if state.get("state_version") != 2 or state.get("phase") != "applying" or state.get("backup") != sys.argv[2]:
    raise SystemExit("ERROR: pending Linux DBMon state changed before commit.")
expected = state.get("applied_hashes") or {{}}
for path in sys.argv[3:6]:
    with open(path, "rb") as handle:
        actual = hashlib.sha256(handle.read()).hexdigest()
    if expected.get(path) != actual:
        raise SystemExit(f"ERROR: applied Linux DBMon file drifted before commit: {{path}}")
state["phase"] = "validated"
temporary = sys.argv[1] + f".tmp.{{os.getpid()}}"
descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(state, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, sys.argv[1])
    directory = os.open(os.path.dirname(sys.argv[1]), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
except BaseException:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
    raise
PY
COMMITTED=true
echo 'Linux DBMon collector apply committed; tenant target probes are still required for telemetry proof.'
systemctl --no-pager --full status "${{SERVICE}}" || true
'''


def render_rollback_linux_script() -> str:
    return r"""#!/usr/bin/env bash
set -euo pipefail
[[ "$(id -u)" == "0" ]] || { echo 'ERROR: run rollback as root or with sudo.' >&2; exit 1; }
[[ "${ACCEPT_LINUX_ROLLBACK:-false}" == "true" ]] || { echo 'ERROR: --accept-linux-rollback is required.' >&2; exit 1; }
for tool in python3 systemctl cp sha256sum mktemp mv; do
    command -v "${tool}" >/dev/null 2>&1 || { echo "ERROR: ${tool} is required." >&2; exit 1; }
done
python3 - /var/lib/splunk-otel-collector <<'PY'
import os
import pathlib
import stat
import sys
current = pathlib.Path("/")
for part in pathlib.Path(sys.argv[1]).parts[1:]:
    current /= part
    info = os.lstat(current)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise SystemExit(f"ERROR: unsafe privileged state directory component: {current}")
PY
STATE="/var/lib/splunk-otel-collector/dbmon-state.json"
[[ -f "${STATE}" && ! -L "${STATE}" ]] || { echo 'ERROR: no trusted Linux DBMon apply state found.' >&2; exit 1; }
LOCK_FILE="/var/lib/splunk-otel-collector/dbmon.lock"
if [[ -e "${LOCK_FILE}" || -L "${LOCK_FILE}" ]]; then
    python3 - "${LOCK_FILE}" <<'PY'
import os
import stat
import sys
info = os.lstat(sys.argv[1])
if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o077:
    raise SystemExit("ERROR: unsafe Linux DBMon transaction lock file.")
PY
fi
if [[ "${DBMON_INHERITED_LOCK:-false}" != "true" ]]; then
    exec 9>>"${LOCK_FILE}"
    chmod 0600 "${LOCK_FILE}"
fi
if ! python3 - "${LOCK_FILE}" <<'PY'
import fcntl
import os
import stat
import sys

try:
    descriptor = os.fstat(9)
    target = os.stat(sys.argv[1], follow_symlinks=False)
    if not stat.S_ISREG(descriptor.st_mode) or (descriptor.st_dev, descriptor.st_ino) != (target.st_dev, target.st_ino):
        raise OSError("file descriptor 9 is not the reviewed DBMon lock file")
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
except (BlockingIOError, OSError):
    raise SystemExit(1)
PY
then
    echo 'ERROR: another Linux DBMon apply or rollback transaction is active.' >&2
    exit 1
fi
STATE_HEADER="$(python3 - "${STATE}" /etc/otel/collector/dbmon.yaml /etc/otel/collector/dbmon.env /etc/systemd/system/splunk-otel-collector.service.d/20-dbmon.conf <<'PY'
import hashlib
import json
import os
import re
import stat
import sys

info = os.lstat(sys.argv[1])
if (
    not stat.S_ISREG(info.st_mode)
    or stat.S_ISLNK(info.st_mode)
    or info.st_mode & 0o077
    or info.st_uid != 0
    or info.st_nlink != 1
):
    raise SystemExit("ERROR: Linux DBMon state must be an owner-only regular file.")
with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)
if state.get("state_version") != 2:
    raise SystemExit(
        "ERROR: legacy Linux DBMon state requires the rollback helper from the packet "
        "that created it; this v2 helper will not guess at legacy recovery."
    )
if state.get("service") != "splunk-otel-collector.service":
    raise SystemExit("ERROR: Linux DBMon state service identity is invalid.")
phase = state.get("phase")
if phase not in {"preparing", "applying", "restoring", "validated", "finalizing"}:
    raise SystemExit("ERROR: Linux DBMon state phase is not recoverable.")
transaction_id = state.get("transaction_id")
if not isinstance(transaction_id, str) or not re.fullmatch(r"[0-9a-f]{32}", transaction_id):
    raise SystemExit("ERROR: Linux DBMon transaction identity is invalid.")
backup = f"/var/lib/splunk-otel-collector/dbmon-backups/{transaction_id}"
if state.get("backup") != backup:
    raise SystemExit("ERROR: Linux DBMon backup identity is invalid.")
staging = {
    sys.argv[2]: f"/etc/otel/collector/.dbmon.yaml.{transaction_id}",
    sys.argv[3]: f"/etc/otel/collector/.dbmon.env.{transaction_id}",
    sys.argv[4]: f"/etc/systemd/system/splunk-otel-collector.service.d/.20-dbmon.conf.{transaction_id}",
}
restores = {
    sys.argv[2]: f"/etc/otel/collector/.dbmon.yaml.restore.{transaction_id}",
    sys.argv[3]: f"/etc/otel/collector/.dbmon.env.restore.{transaction_id}",
    sys.argv[4]: f"/etc/systemd/system/splunk-otel-collector.service.d/.20-dbmon.conf.restore.{transaction_id}",
}
if state.get("staging_paths") != staging or state.get("restore_paths") != restores:
    raise SystemExit("ERROR: Linux DBMon transaction path inventory is invalid.")
previous = state.get("previous_state")
previous_digest = state.get("previous_state_sha256")
if previous is None:
    if previous_digest is not None:
        raise SystemExit("ERROR: Linux DBMon empty previous state has a digest.")
else:
    if not isinstance(previous, dict) or previous.get("state_version") != 2 or previous.get("phase") != "validated":
        raise SystemExit("ERROR: Linux DBMon previous state is not a committed v2 transaction.")
    canonical = json.dumps(previous, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != previous_digest:
        raise SystemExit("ERROR: Linux DBMon previous-state digest is invalid.")
expected = state.get("applied_hashes")
manifest_digest = state.get("backup_manifest_sha256")
if phase == "preparing":
    if expected is not None or manifest_digest is not None:
        raise SystemExit("ERROR: Linux DBMon preparing state already contains applied data.")
elif (
    not isinstance(expected, dict)
    or set(expected) != set(sys.argv[2:])
    or not all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in expected.values())
    or not isinstance(manifest_digest, str)
    or not re.fullmatch(r"[0-9a-f]{64}", manifest_digest)
):
    raise SystemExit("ERROR: Linux DBMon applied-hash or backup-manifest inventory is invalid.")
print(f"{phase}\t{transaction_id}\t{backup}")
PY
)"
IFS=$'\t' read -r PHASE TRANSACTION_ID BACKUP <<<"${STATE_HEADER}"
RESTORE_CONFIG="/etc/otel/collector/.dbmon.yaml.restore.${TRANSACTION_ID}"
RESTORE_ENV="/etc/otel/collector/.dbmon.env.restore.${TRANSACTION_ID}"
RESTORE_DROPIN="/etc/systemd/system/splunk-otel-collector.service.d/.20-dbmon.conf.restore.${TRANSACTION_ID}"

finish_without_restore() {
    local expected_phase="$1"
    python3 - "${STATE}" "${expected_phase}" <<'PY'
import hashlib
import json
import os
import shutil
import stat
import sys

state_path = sys.argv[1]
expected_phase = sys.argv[2]
with open(state_path, encoding="utf-8") as handle:
    state = json.load(handle)
if state.get("state_version") != 2 or state.get("phase") != expected_phase:
    raise SystemExit("ERROR: Linux DBMon cleanup state changed unexpectedly.")
previous = state.get("previous_state")
previous_digest = state.get("previous_state_sha256")
if previous is None:
    if previous_digest is not None:
        raise SystemExit("ERROR: Linux DBMon empty previous state has a digest.")
else:
    canonical = json.dumps(previous, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != previous_digest:
        raise SystemExit("ERROR: Linux DBMon previous-state digest changed during cleanup.")

destinations = tuple(state["staging_paths"])
if previous is None:
    for destination in destinations:
        if os.path.lexists(destination):
            raise SystemExit(f"ERROR: destination changed during preparation: {destination}")
else:
    baseline = previous.get("applied_hashes")
    if not isinstance(baseline, dict) or set(baseline) != set(destinations):
        raise SystemExit("ERROR: previous Linux DBMon applied hashes are invalid.")
    for destination in destinations:
        if not os.path.isfile(destination) or os.path.islink(destination):
            raise SystemExit(f"ERROR: previous Linux DBMon destination is unsafe: {destination}")
        with open(destination, "rb") as handle:
            actual = hashlib.sha256(handle.read()).hexdigest()
        if actual != baseline[destination]:
            raise SystemExit(f"ERROR: previous Linux DBMon destination drifted: {destination}")

directories = {os.path.dirname(state_path)}
for path in (*state["staging_paths"].values(), *state["restore_paths"].values()):
    directories.add(os.path.dirname(path))
    if os.path.lexists(path):
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
            raise SystemExit(f"ERROR: unsafe tracked Linux DBMon temporary file: {path}")
        os.unlink(path)
backup = state["backup"]
directories.add(os.path.dirname(backup))
if os.path.lexists(backup):
    info = os.lstat(backup)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise SystemExit("ERROR: unsafe tracked Linux DBMon backup directory.")
    shutil.rmtree(backup)
for directory_path in directories:
    if os.path.isdir(directory_path) and not os.path.islink(directory_path):
        descriptor = os.open(directory_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

if previous is None:
    os.unlink(state_path)
else:
    temporary = state_path + f".previous.{os.getpid()}"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(previous, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, state_path)
directory = os.open(os.path.dirname(state_path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY
}

if [[ "${PHASE}" == "preparing" ]]; then
    finish_without_restore preparing
    echo 'Removed a tracked, pre-apply Linux DBMon transaction; live configuration was unchanged.'
    exit 0
fi
if [[ "${PHASE}" == "finalizing" ]]; then
    systemctl is-active --quiet splunk-otel-collector.service
    finish_without_restore finalizing
    echo "Completed final cleanup for Linux DBMon transaction ${TRANSACTION_ID}."
    exit 0
fi

[[ "${BACKUP}" =~ ^/var/lib/splunk-otel-collector/dbmon-backups/[0-9a-f]{32}$ && -d "${BACKUP}" ]] || { echo 'ERROR: invalid backup path in state.' >&2; exit 1; }
python3 - "${BACKUP}" "${STATE}" <<'PY'
import hashlib
import json
import os
import stat
import sys
info = os.lstat(sys.argv[1])
if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
    raise SystemExit("ERROR: Linux DBMon backup directory is not trusted.")
with open(sys.argv[2], encoding="utf-8") as handle:
    state = json.load(handle)
manifest = os.path.join(sys.argv[1], "SHA256SUMS")
with open(manifest, "rb") as handle:
    actual_manifest = hashlib.sha256(handle.read()).hexdigest()
if actual_manifest != state.get("backup_manifest_sha256"):
    raise SystemExit("ERROR: Linux DBMon backup manifest digest is invalid.")
names = set(os.listdir(sys.argv[1]))
if "SHA256SUMS" not in names:
    raise SystemExit("ERROR: Linux DBMon backup manifest is missing.")
names.remove("SHA256SUMS")
for label in ("dbmon.yaml", "dbmon.env", "20-dbmon.conf"):
    choices = {label, label + ".missing"} & names
    if len(choices) != 1:
        raise SystemExit(f"ERROR: Linux DBMon backup entry is ambiguous: {label}")
    name = choices.pop()
    names.remove(name)
    path = os.path.join(sys.argv[1], name)
    entry = os.lstat(path)
    if not stat.S_ISREG(entry.st_mode) or stat.S_ISLNK(entry.st_mode) or entry.st_uid != 0 or entry.st_nlink != 1:
        raise SystemExit(f"ERROR: Linux DBMon backup entry is unsafe: {name}")
if names:
    raise SystemExit("ERROR: Linux DBMon backup contains untracked entries.")
PY
(cd "${BACKUP}" && sha256sum --check --strict SHA256SUMS)
python3 - "${STATE}" "${BACKUP}" /etc/otel/collector/dbmon.yaml dbmon.yaml \
    /etc/otel/collector/dbmon.env dbmon.env \
    /etc/systemd/system/splunk-otel-collector.service.d/20-dbmon.conf 20-dbmon.conf <<'PY'
import hashlib
import json
import os
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)
expected = state["applied_hashes"]
backup = sys.argv[2]
for index in range(3, len(sys.argv), 2):
    destination = sys.argv[index]
    label = sys.argv[index + 1]
    restored_missing = os.path.isfile(os.path.join(backup, label + ".missing"))
    restored_hash = None
    if not restored_missing:
        with open(os.path.join(backup, label), "rb") as handle:
            restored_hash = hashlib.sha256(handle.read()).hexdigest()
    if os.path.lexists(destination):
        if not os.path.isfile(destination) or os.path.islink(destination):
            raise SystemExit(f"ERROR: unsafe managed path during rollback: {destination}")
        with open(destination, "rb") as handle:
            actual = hashlib.sha256(handle.read()).hexdigest()
        if actual not in {expected[destination], restored_hash}:
            raise SystemExit(f"ERROR: managed path is neither applied nor restored state: {destination}")
    elif not restored_missing:
        raise SystemExit(f"ERROR: managed path disappeared outside rollback: {destination}")
PY
python3 - "${STATE}" <<'PY'
import json
import os
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)
if state.get("state_version") != 2 or state.get("phase") not in {"applying", "restoring", "validated"}:
    raise SystemExit("ERROR: Linux DBMon state cannot enter restoring phase.")
state["phase"] = "restoring"
temporary = sys.argv[1] + f".restoring.{os.getpid()}"
descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    json.dump(state, handle, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.replace(temporary, sys.argv[1])
directory = os.open(os.path.dirname(sys.argv[1]), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY
restore_file() {
    local destination="$1" label="$2" staged="$3"
    if [[ -f "${BACKUP}/${label}.missing" ]]; then
        python3 - "${destination}" "${staged}" <<'PY'
import os
import stat
import sys
for path in sys.argv[1:]:
    if os.path.lexists(path):
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
            raise SystemExit(f"ERROR: unsafe tracked Linux DBMon restore path: {path}")
        os.unlink(path)
for directory_path in {os.path.dirname(path) for path in sys.argv[1:]}:
    descriptor = os.open(directory_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
PY
    else
        python3 - "${BACKUP}/${label}" "${staged}" <<'PY'
import hashlib
import os
import stat
import sys
source, staged = sys.argv[1:]
source_info = os.lstat(source)
if not stat.S_ISREG(source_info.st_mode) or stat.S_ISLNK(source_info.st_mode) or source_info.st_uid != 0 or source_info.st_nlink != 1:
    raise SystemExit("ERROR: unsafe Linux DBMon backup source.")
if os.path.lexists(staged):
    info = os.lstat(staged)
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
        raise SystemExit("ERROR: unsafe tracked Linux DBMon restore staging file.")
    with open(source, "rb") as handle:
        expected = hashlib.sha256(handle.read()).hexdigest()
    with open(staged, "rb") as handle:
        actual = hashlib.sha256(handle.read()).hexdigest()
    if actual != expected:
        os.unlink(staged)
PY
        if [[ ! -e "${staged}" ]]; then
            cp -a -- "${BACKUP}/${label}" "${staged}"
        fi
        python3 - "${BACKUP}/${label}" "${staged}" <<'PY'
import hashlib
import os
import stat
import sys
source, staged = sys.argv[1:]
info = os.lstat(staged)
if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
    raise SystemExit("ERROR: unsafe Linux DBMon restore staging file after copy.")
with open(source, "rb") as handle:
    expected = hashlib.sha256(handle.read()).hexdigest()
with open(staged, "rb") as handle:
    actual = hashlib.sha256(handle.read()).hexdigest()
if actual != expected:
    raise SystemExit("ERROR: Linux DBMon restore staging hash mismatch.")
descriptor = os.open(staged, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY
        mv -f -- "${staged}" "${destination}"
        python3 - "${destination}" <<'PY'
import os
import sys
directory = os.open(os.path.dirname(sys.argv[1]), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY
    fi
}
restore_file /etc/otel/collector/dbmon.yaml dbmon.yaml "${RESTORE_CONFIG}"
restore_file /etc/otel/collector/dbmon.env dbmon.env "${RESTORE_ENV}"
restore_file /etc/systemd/system/splunk-otel-collector.service.d/20-dbmon.conf 20-dbmon.conf "${RESTORE_DROPIN}"
systemctl daemon-reload
systemctl restart splunk-otel-collector.service
systemctl is-active --quiet splunk-otel-collector.service
python3 - "${STATE}" "${BACKUP}" /etc/otel/collector/dbmon.yaml dbmon.yaml \
    /etc/otel/collector/dbmon.env dbmon.env \
    /etc/systemd/system/splunk-otel-collector.service.d/20-dbmon.conf 20-dbmon.conf <<'PY'
import hashlib
import json
import os
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)
if state.get("phase") != "restoring" or state.get("backup") != sys.argv[2]:
    raise SystemExit("ERROR: Linux DBMon rollback state changed during restore.")
for index in range(3, len(sys.argv), 2):
    destination = sys.argv[index]
    label = sys.argv[index + 1]
    if os.path.isfile(os.path.join(sys.argv[2], label + ".missing")):
        if os.path.lexists(destination):
            raise SystemExit(f"ERROR: expected restored path to be absent: {destination}")
    else:
        with open(os.path.join(sys.argv[2], label), "rb") as handle:
            expected = hashlib.sha256(handle.read()).hexdigest()
        with open(destination, "rb") as handle:
            actual = hashlib.sha256(handle.read()).hexdigest()
        if actual != expected:
            raise SystemExit(f"ERROR: restored path hash mismatch: {destination}")
state["phase"] = "finalizing"
temporary = sys.argv[1] + f".finalizing.{os.getpid()}"
descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    json.dump(state, handle, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.replace(temporary, sys.argv[1])
directory = os.open(os.path.dirname(sys.argv[1]), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY
finish_without_restore finalizing
echo "Restored DBMon Linux state from ${BACKUP}."
"""


def render_apply_windows_script(
    *, scrape_owner: str, collector: dict[str, Any], targets: list[dict[str, Any]]
) -> str:
    template = r"""#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
if ("__SCRAPE_OWNER__" -ne "windows") { throw "Spec scrape_owner is __SCRAPE_OWNER__, not windows" }
$ServiceName = "splunk-otel-collector"
$ExpectedVersion = "__VERSION__"
$ExpectedMemoryMiB = __MEMORY_MIB__
$Required = @((ConvertFrom-Json '__REQUIRED_JSON__'))
$Allowed = @((ConvertFrom-Json '__ALLOWED_JSON__'))
$SecureDatasources = @((ConvertFrom-Json '__SECURE_DATASOURCES_JSON__'))
$TlsFiles = @((ConvertFrom-Json '__TLS_FILES_JSON__'))
$TlsPrivateKeys = @((ConvertFrom-Json '__TLS_PRIVATE_KEYS_JSON__'))
$Root = Split-Path -Parent $PSScriptRoot
$SourceConfig = Join-Path $Root "windows\collector-dbmon.fragment.yaml"
$CredentialFile = $env:DBMON_ENV_FILE
$ProgramRoot = Join-Path $env:ProgramData "Splunk\OpenTelemetry Collector"
$BaseConfig = if ($env:SPLUNK_BASE_CONFIG) { $env:SPLUNK_BASE_CONFIG } else { Join-Path $ProgramRoot "agent_config.yaml" }
$RegistryPath = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName"

function Read-StrictEnvironmentFile([string]$Path) {
    if (-not $Path) { throw "--db-credentials-env-file is required" }
    $Item = Get-Item -LiteralPath $Path -Force
    if ($Item.PSIsContainer -or ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "$Path must be a regular, non-reparse-point file"
    }
    if ($Item.Length -gt 1MB) { throw "$Path exceeds 1 MiB" }
    $Acl = Get-Acl -LiteralPath $Path
    $OwnerSid = $Acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
    $AllowedSids = @($OwnerSid, "S-1-5-18", "S-1-5-32-544")
    $Unsafe = $Acl.Access | Where-Object {
        $Sid = $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
        $_.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
        $_.FileSystemRights -match 'Read|ReadAndExecute|FullControl|Modify' -and
        $AllowedSids -notcontains $Sid
    }
    if ($Unsafe) { throw "$Path grants credential access outside owner, SYSTEM, and Administrators" }
    $Values = @{}
    $Number = 0
    $BeforeLength = $Item.Length
    $BeforeWrite = $Item.LastWriteTimeUtc
    $Stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
    try {
        $Reader = [IO.StreamReader]::new($Stream, [Text.UTF8Encoding]::new($false, $true), $true)
        try { $Content = $Reader.ReadToEnd() } finally { $Reader.Dispose() }
    } finally { $Stream.Dispose() }
    $After = Get-Item -LiteralPath $Path -Force
    if ($After.Length -ne $BeforeLength -or $After.LastWriteTimeUtc -ne $BeforeWrite) {
        throw "$Path changed while it was being read"
    }
    foreach ($Line in ($Content -split "`r?`n")) {
        $Number++
        $Text = $Line.Trim()
        if (-not $Text -or $Text.StartsWith("#")) { continue }
        $Parts = $Text.Split('=', 2)
        if ($Parts.Count -ne 2 -or $Parts[0] -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
            throw "$Path`:$Number has an invalid assignment"
        }
        if ($Values.ContainsKey($Parts[0])) { throw "$Path`:$Number repeats $($Parts[0])" }
        $Value = $Parts[1].Trim()
        if ($Value.Length -ge 2 -and (($Value[0] -eq '"' -and $Value[-1] -eq '"') -or ($Value[0] -eq "'" -and $Value[-1] -eq "'"))) {
            $Value = $Value.Substring(1, $Value.Length - 2)
        }
        $Values[$Parts[0]] = $Value
    }
    $Unexpected = @($Values.Keys | Where-Object { $Allowed -notcontains $_ })
    if ($Unexpected.Count -gt 0) { throw "Credential file contains keys outside the rendered allowlist" }
    return $Values
}

function Assert-SecureDatasource([string]$Name, [string]$Engine, [string]$Value) {
    $Uri = $null
    if (-not [Uri]::TryCreate($Value, [UriKind]::Absolute, [ref]$Uri) -or -not $Uri.Host -or $Uri.Fragment) {
        throw "$Name must be an absolute URL-form datasource"
    }
    $Query = $Uri.Query
    if ($Engine -eq "sqlserver") {
        $Encrypt = [regex]::Matches($Query, '(?i)(?:^|[?&])encrypt=(true|yes|mandatory|strict|1)(?:&|$)')
        $Trust = [regex]::Matches($Query, '(?i)(?:^|[?&])trustservercertificate=(false|no|0)(?:&|$)')
        if ($Uri.Scheme -ne "sqlserver" -or $Encrypt.Count -ne 1 -or $Trust.Count -ne 1) {
            throw "$Name must enable SQL encryption and disable TrustServerCertificate"
        }
    } elseif ($Engine -eq "oracledb") {
        $Ssl = [regex]::Matches($Query, '(?i)(?:^|[?&])ssl=(enable|true)(?:&|$)')
        $Verify = [regex]::Matches($Query, '(?i)(?:^|[?&])ssl(?:%20|\+)verify=true(?:&|$)')
        if ($Uri.Scheme -ne "oracle" -or $Ssl.Count -ne 1 -or $Verify.Count -ne 1) {
            throw "$Name must enable Oracle SSL and SSL Verify"
        }
    } else { throw "Unsupported secure datasource engine" }
}

function Convert-Environment([object]$Raw) {
    $Map = @{}
    foreach ($Entry in @($Raw)) {
        if (-not $Entry) { continue }
        $Parts = ([string]$Entry).Split('=', 2)
        if ($Parts.Count -eq 2) { $Map[$Parts[0]] = $Parts[1] }
    }
    return $Map
}

$Credentials = Read-StrictEnvironmentFile $CredentialFile
foreach ($Name in $Required) {
    if (-not $Credentials.ContainsKey($Name) -or -not $Credentials[$Name]) { throw "Missing nonempty credential $Name" }
}
foreach ($Entry in $SecureDatasources) {
    $DatasourceName = [string]$Entry.name
    Assert-SecureDatasource $DatasourceName ([string]$Entry.engine) ([string]$Credentials[$DatasourceName])
}
if ([int]$Credentials["SPLUNK_MEMORY_LIMIT_MIB"] -lt $ExpectedMemoryMiB) {
    throw "SPLUNK_MEMORY_LIMIT_MIB is below the required $ExpectedMemoryMiB MiB"
}
$ActualMemoryMiB = [math]::Floor((Get-CimInstance Win32_OperatingSystem).TotalVisibleMemorySize / 1024)
if ($ActualMemoryMiB -lt $ExpectedMemoryMiB) {
    throw "Effective Windows host memory $ActualMemoryMiB MiB is below required $ExpectedMemoryMiB MiB"
}
$Service = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
if (-not $Service) { throw "The $ServiceName service is not installed" }
$Match = [regex]::Match($Service.PathName, '^\s*(?:"([^"]+)"|(\S+))')
$Executable = if ($Match.Groups[1].Success) { $Match.Groups[1].Value } else { $Match.Groups[2].Value }
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { throw "Collector executable not found: $Executable" }
$ExecutableItem = Get-Item -LiteralPath $Executable -Force
if ($ExecutableItem.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Collector executable cannot be a reparse point" }
$ExecutableAcl = Get-Acl -LiteralPath $Executable
$ExecutableOwner = $ExecutableAcl.GetOwner([Security.Principal.SecurityIdentifier]).Value
$ExecutableAllowed = @($ExecutableOwner, "S-1-5-18", "S-1-5-32-544")
$ExecutableUnsafe = $ExecutableAcl.Access | Where-Object {
    $Sid = $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    $_.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
    $_.FileSystemRights -match 'Write|Modify|FullControl' -and
    $ExecutableAllowed -notcontains $Sid
}
if ($ExecutableUnsafe) { throw "Collector executable is writable outside its trusted owner/SYSTEM/Administrators set" }
$VersionText = (& $Executable --version 2>&1 | Out-String)
$VersionMatches = [regex]::Matches($VersionText, '(?<![0-9A-Za-z_.+-])v?(\d+\.\d+\.\d+)(?![0-9A-Za-z_.+-])')
if ($VersionMatches.Count -ne 1 -or $VersionMatches[0].Groups[1].Value -ne $ExpectedVersion.TrimStart('v')) {
    throw "Collector binary did not report the exact audited version"
}
if (-not (Test-Path -LiteralPath $BaseConfig -PathType Leaf)) { throw "Base config not found: $BaseConfig" }
$BaseText = [IO.File]::ReadAllText($BaseConfig)
if ($BaseText.TrimStart().StartsWith("{") -or $BaseText -match '(?m)^\s*receivers\s*:\s*\{') {
    throw "JSON/flow-style base receiver maps require a separately reviewed Windows handoff; duplicate ownership cannot be proven safely"
}
if ($BaseText -match '(?m)^\s+["'']?(postgresql|sqlserver|oracledb|mysql)(/[^:"''\s]+)?["'']?\s*:') {
    throw "Base collector config already contains a DB receiver; migrate it before using the sole-scraper handoff"
}
foreach ($TlsFile in $TlsFiles) {
    $TlsItem = Get-Item -LiteralPath $TlsFile -Force
    if ($TlsItem.PSIsContainer -or ($TlsItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "TLS file is missing, a directory, or a reparse point: $TlsFile"
    }
    if ($TlsPrivateKeys -contains $TlsFile) {
        $TlsAcl = Get-Acl -LiteralPath $TlsFile
        $TlsOwnerSid = $TlsAcl.GetOwner([Security.Principal.SecurityIdentifier]).Value
        $TlsAllowedSids = @($TlsOwnerSid, "S-1-5-18", "S-1-5-32-544")
        $TlsUnsafe = $TlsAcl.Access | Where-Object {
            $Sid = $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
            $_.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
            $_.FileSystemRights -match 'Read|ReadAndExecute|FullControl|Modify' -and
            $TlsAllowedSids -notcontains $Sid
        }
        if ($TlsUnsafe) { throw "TLS private key ACL grants access outside owner, SYSTEM, and Administrators" }
    }
}

$Registry = Get-ItemProperty -LiteralPath $RegistryPath
$ExistingEnvironment = Convert-Environment $Registry.Environment
if (-not $ExistingEnvironment.ContainsKey("SPLUNK_ACCESS_TOKEN") -or -not $ExistingEnvironment["SPLUNK_ACCESS_TOKEN"]) {
    throw "The protected collector service environment does not provide SPLUNK_ACCESS_TOKEN"
}
foreach ($Name in $Credentials.Keys) {
    if ($ExistingEnvironment.ContainsKey($Name) -and $ExistingEnvironment[$Name] -ne $Credentials[$Name]) {
        throw "Service environment variable $Name already exists with a different value"
    }
    $ExistingEnvironment[$Name] = $Credentials[$Name]
}
$Synthetic = @{}
foreach ($Name in $Credentials.Keys) {
    $Synthetic[$Name] = if ($Name -eq "SPLUNK_MEMORY_LIMIT_MIB") { $Credentials[$Name] } else { "dbmon-validation-placeholder" }
}
foreach ($Entry in $SecureDatasources) {
    $Synthetic[[string]$Entry.name] = if ([string]$Entry.engine -eq "sqlserver") {
        "sqlserver://validation:placeholder@db.invalid:1433?encrypt=true&trustservercertificate=false"
    } else {
        "oracle://validation:placeholder@db.invalid:1521/service?SSL=enable&SSL%20Verify=true"
    }
}
$Synthetic["SPLUNK_ACCESS_TOKEN"] = "dbmon-validation-placeholder"
foreach ($Entry in $ExistingEnvironment.GetEnumerator()) {
    $Value = if ($Synthetic.ContainsKey($Entry.Key)) { $Synthetic[$Entry.Key] } elseif ($Entry.Key -match '(?i)password|passwd|token|secret|authorization|api[_-]?key|datasource|connection[_-]?string|private[_-]?key') { "dbmon-validation-placeholder" } else { [string]$Entry.Value }
    [Environment]::SetEnvironmentVariable($Entry.Key, $Value, "Process")
}
& $Executable validate "--config=$BaseConfig" "--config=$SourceConfig" *> $null
if ($LASTEXITCODE -ne 0) { throw "Collector config validation failed" }
Write-Host "Windows DBMon collector configuration validation passed."
throw "Live Windows apply is intentionally disabled: the receiver requires process environment credentials, and persisting them in the service registry is not an approved secret mechanism. Provision credentials and service configuration through the owning protected Windows service-secret workflow, then rerun this validator and tenant-side validation."
"""
    return (
        template.replace("__VERSION__", collector["version"])
        .replace("__SCRAPE_OWNER__", scrape_owner)
        .replace("__MEMORY_MIB__", str(collector["memory_mib"]))
        .replace(
            "__REQUIRED_JSON__",
            json.dumps(["SPLUNK_MEMORY_LIMIT_MIB", *required_credential_envs(targets)]),
        )
        .replace(
            "__ALLOWED_JSON__",
            json.dumps(["SPLUNK_MEMORY_LIMIT_MIB", *required_credential_envs(targets)]),
        )
        .replace(
            "__SECURE_DATASOURCES_JSON__",
            json.dumps(
                [
                    {
                        "name": target["credentials"]["datasource_var"],
                        "engine": target["type"],
                    }
                    for target in targets
                    if target["connection_mode"] == "datasource"
                ]
            ),
        )
        .replace("__TLS_FILES_JSON__", json.dumps(required_tls_files(targets)))
        .replace(
            "__TLS_PRIVATE_KEYS_JSON__",
            json.dumps(
                [
                    item["path"]
                    for item in tls_file_requirements(targets)
                    if item["kind"] == "private_key"
                ]
            ),
        )
    )


def render_rollback_windows_script() -> str:
    return r"""#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
throw "No Windows rollback action is generated because live Windows mutation is intentionally disabled. Manage any operator-owned Windows service changes through that system's protected service-secret and rollback workflow."
"""


def gateway_reference() -> str:
    source = (
        Path(__file__).resolve().parents[1]
        / "references"
        / "gateway-routing.sqlserver.md"
    )
    return source.read_text(encoding="utf-8")


def mysql_wait_events_enabled(target: dict[str, Any]) -> bool:
    return bool(
        target["type"] in {"mysql", "mariadb"}
        and target["events"].get("query_sample")
    )


def prerequisite_runbook(target: dict[str, Any]) -> str:
    heading = f"# Database prerequisite handoff: {target['name']}\n\n"
    common = (
        f"Receiver: `{target['receiver_id']}`  \n"
        f"Platform/version: `{target['platform']}` / `{target['version']}`\n\n"
        "Have a database administrator run and review these commands. They are not "
        "executed by this skill. Substitute the account identifier and supply its secret "
        "through the database's approved secret workflow.\n\n"
    )
    target_type = target["type"]
    if target_type == "postgresql":
        body = """## Required database changes

```sql
GRANT pg_monitor TO "otel-user";
GRANT SELECT ON pg_stat_database TO "otel-user";
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
```

Create `pg_stat_statements` in every database the receiver scrapes. For Azure
Flexible Server, also configure `azure.extensions=pg_stat_statements`,
`shared_preload_libraries=pg_stat_statements`, `pg_stat_statements.track=all`,
`pg_stat_statements.max=10000`, and `pg_stat_statements.track_utility=on`, then
perform the provider-required restart.
"""
    elif target_type == "sqlserver":
        permission = (
            "VIEW SERVER PERFORMANCE STATE"
            if target["version"] == "2022"
            else "VIEW SERVER STATE"
        )
        if target["platform"] == "azure-sql-database":
            login_sql = """-- Provision the contained SQL or Microsoft Entra user through the
-- Azure SQL identity owner's approved secret/identity workflow.
CREATE USER [otel-user] WITH PASSWORD = N'$(OTEL_LOGIN_PASSWORD)';"""
        else:
            login_sql = """-- Create the login first through the database owner's approved secret workflow.
-- With sqlcmd, supply OTEL_LOGIN_PASSWORD from a protected environment:
CREATE LOGIN [otel-user] WITH PASSWORD = N'$(OTEL_LOGIN_PASSWORD)',
  CHECK_POLICY = ON, CHECK_EXPIRATION = OFF;
CREATE USER [otel-user] FOR LOGIN [otel-user];"""
        body = f"""## Required database changes

```sql
{login_sql}
GRANT VIEW ANY DATABASE TO [otel-user];
GRANT {permission} TO [otel-user];
GRANT VIEW ANY DEFINITION TO [otel-user];
```

Set the login secret outside this file. On Windows Performance Counter targets,
run the collector with the privileges required to read all counters. Azure-managed
targets have `sqlserver.database.count` disabled automatically by the renderer.
"""
    elif target_type in {"mysql", "mariadb"}:
        version_parts = parse_database_version(target["version"])
        if target_type == "mysql":
            replica_grant = "GRANT REPLICATION CLIENT ON *.* TO 'otel-user'@'%';"
            settings = (
                "`max_digest_length=4096`, `performance_schema_max_digest_length=4096`, "
                "and `performance_schema_max_sql_text_length=4096`"
            )
            plan_note = (
                "Grant schema-level access for explain plans:\n\n"
                "```sql\nGRANT SELECT ON `schema-name`.* TO 'otel-user'@'%';\n```"
                if version_parts >= (8, 0)
                else "MySQL 5.7 is fully supported for metrics and query events but does "
                "not expose executable sample text for explain plans; record plans as not supported."
            )
        else:
            if version_parts < (10, 5, 2):
                replica_grant = "GRANT REPLICATION CLIENT ON *.* TO 'otel-user'@'%';"
            elif version_parts < (10, 5, 9):
                replica_grant = "GRANT BINLOG MONITOR ON *.* TO 'otel-user'@'%';"
            else:
                replica_grant = "GRANT SLAVE MONITOR ON *.* TO 'otel-user'@'%';"
            settings = (
                "`max_digest_length=4096`"
                if version_parts < (10, 5, 2)
                else "`max_digest_length=4096`, `performance_schema_max_digest_length=4096`, "
                "and `performance_schema_max_sql_text_length=4096`"
            )
            plan_note = (
                "MariaDB 10.5+ is a supported DBMon target for metrics and query events. "
                "The v0.155 receiver does not provide MariaDB explain plans because MariaDB "
                "does not expose MySQL's `query_sample_text`; record plan evidence as not supported."
            )
        platform_note = (
            "For AWS RDS, apply these Performance Schema values through the attached DB "
            "parameter group and perform the required restart. Optionally suppress the "
            "receiver version warning with:\n\n"
            "```sql\nGRANT EXECUTE ON PROCEDURE mysql.rds_version TO 'otel-user'@'%';\n```"
            if target["platform"] == "aws-rds"
            else "For standalone deployments, put these values in the `[mysqld]` section "
            "of `my.cnf`/`mysqld.cnf`, restart the database, and verify them with `SHOW VARIABLES`."
        )
        body = f"""## Required database changes

Enable Performance Schema. Set `performance_schema=1`; Splunk recommends {settings}.
{platform_note}

```sql
{replica_grant}
GRANT PROCESS ON *.* TO 'otel-user'@'%';
GRANT SELECT ON performance_schema.* TO 'otel-user'@'%';
```

{plan_note}
MySQL 8.0.22+ uses `SHOW REPLICA STATUS` terminology and emits the current
client/network port attributes; record those version-specific checks when applicable.
"""
        if mysql_wait_events_enabled(target):
            body += """

## Optional wait-duration metric enabled by this spec

`mysql.events_waits_current.timer_wait` requires the normally disabled
`events_waits_current` Performance Schema consumer. Have the DBA run and verify:

```sql
-- Run as the DBA/startup-automation identity, not the collector account.
UPDATE performance_schema.setup_consumers
SET ENABLED = 'YES'
WHERE NAME = 'events_waits_current';
SELECT NAME, ENABLED FROM performance_schema.setup_consumers
WHERE NAME = 'events_waits_current';
```

On AWS RDS this setting resets after restart or failover. Use reviewed DBA or
provider startup automation to re-enable it and record a post-failover evidence
check; the v0.155 receiver itself does not prove that mutation. Do not grant
broader Performance Schema writes.
"""
    else:
        grants = [
            "SYS.V_$INSTANCE",
            "SYS.V_$DATABASE",
            "SYS.V_$DATAFILE",
            "SYS.V_$PDBS",
            "SYS.CDB_SERVICES",
            "SYS.V_$SESSION",
            "SYS.V_$SYSSTAT",
            "SYS.V_$RESOURCE_LIMIT",
            "SYS.V_$ROWCACHE",
            "SYS.V_$SYSMETRIC",
            "SYS.V_$PARAMETER",
            "SYS.DBA_TABLESPACES",
            "SYS.DBA_DATA_FILES",
            "SYS.DBA_FREE_SPACE",
            "SYS.DBA_RECYCLEBIN",
            "SYS.DBA_TABLESPACE_USAGE_METRICS",
        ]
        if any(target["events"].values()):
            grants.extend(
                [
                    "SYS.V_$SQL",
                    "SYS.V_$SQL_PLAN",
                    "SYS.V_$SESSION_EVENT",
                    "SYS.V_$LOCK",
                    "SYS.V_$CONTAINERS",
                    "SYS.DBA_OBJECTS",
                    "SYS.DBA_PROCEDURES",
                ]
            )
        if target["platform"] == "aws-rds":
            grant_sql = "\n".join(
                "BEGIN\n"
                "  rdsadmin.rdsadmin_util.grant_sys_object(\n"
                f"    p_obj_name => '{item.removeprefix('SYS.')}',\n"
                "    p_grantee => 'OTEL_USER',\n"
                "    p_privilege => 'SELECT',\n"
                "    p_grant_option => false);\n"
                "END;\n/"
                for item in grants
            )
            platform_note = (
                "These are the AWS RDS-specific calls for every required SYS/DBA view. "
                "The RDS master user must be able to transfer each privilege."
            )
        else:
            grant_sql = "\n".join(
                f"GRANT SELECT ON {item} TO OTEL_USER;" for item in grants
            )
            platform_note = ""
        body = f"""## Required database changes

```sql
-- Create OTEL_USER through the database owner's approved secret workflow.
GRANT CREATE SESSION TO OTEL_USER;
{grant_sql}
```

Set the account secret outside this file. {platform_note} Configure one receiver
per RAC node. The event-view grants, including `V_$SESSION_EVENT`, are emitted whenever
query samples, top queries, or session-wait samples are enabled because the
audited v0.155 receiver requires that complete event grant set. Do not add the
upstream v0.156 `V_$SQL_PLAN_STATISTICS_ALL` grant until Splunk ships it.
"""
    return heading + common + body


def apm_correlation_reference(targets: list[dict[str, Any]]) -> str:
    engines = sorted({target["type"] for target in targets})
    return f"""# DBMon query-to-trace correlation handoff

Configured engines: {", ".join(engines)}

- Correlation appears only for sampled queries and requires a Splunk APM license.
- Java/JDBC: set `OTEL_INSTRUMENTATION_SPLUNK_JDBC_ENABLED=true`.
- .NET + SQL Server: set
  `OTEL_DOTNET_EXPERIMENTAL_SQLCLIENT_ENABLE_TRACE_CONTEXT_PROPAGATION=true`.
- Minimum Java agents: SQL Server/Oracle 2.20.1, PostgreSQL 2.22.0,
  MySQL 2.26.1. MariaDB correlation is not explicitly listed by Splunk.
- Minimum .NET agent for SQL Server: 1.11.0.
- Restart the application after applying instrumentation changes, then validate
  both Query details > Traces and APM Trace Analyzer navigation.

Delegate application mutation to
`splunk-observability-k8s-auto-instrumentation-setup` or the appropriate host
instrumentation workflow.
"""


def product_validation_reference(targets: list[dict[str, Any]]) -> str:
    session_wait = any(
        target["type"] == "oracledb" and target["events"].get("session_wait_sample")
        for target in targets
    )
    mysql_wait = any(mysql_wait_events_enabled(target) for target in targets)
    release_checks = []
    if any(
        target["type"] == "sqlserver"
        and target["events"].get("top_query")
        for target in targets
    ):
        release_checks.append(
            "For collector v0.155, verify `sqlserver.query.plan.creation_time` on enabled top-query events."
        )
    sql_service_attributes = sorted(
        {
            name
            for target in targets
            if target["type"] == "sqlserver"
            for name, config in (
                target["advanced"].get("resource_attributes") or {}
            ).items()
            if name in {"service.name", "service.namespace"}
            and config.get("enabled")
        }
    )
    if sql_service_attributes:
        release_checks.append(
            "Verify enabled SQL Server v0.155 service resource attributes are populated: "
            + ", ".join(f"`{name}`" for name in sql_service_attributes)
            + "."
        )
    sql_override_attributes = sorted(
        {
            name
            for target in targets
            if target["type"] == "sqlserver"
            for name, config in (
                target["advanced"].get("resource_attributes") or {}
            ).items()
            if "override_value" in config
        }
    )
    if sql_override_attributes:
        release_checks.append(
            "Verify reviewed SQL Server resource-attribute overrides match the intended values for: "
            + ", ".join(f"`{name}`" for name in sql_override_attributes)
            + "."
        )
    if any(
        target["type"] == "oracledb"
        and target["events"].get("top_query")
        for target in targets
    ):
        release_checks.append(
            "For collector v0.155, verify `oracledb.plan.first_load` and the "
            "`OBJECT_NAME`, `OBJECT_TYPE`, `FILTER_PREDICATES`, `PARTITION_START`, "
            "and `PARTITION_STOP` plan-step fields on enabled Oracle query-plan events."
        )
    if any(
        target["type"] == "oracledb" and any(target["events"].values())
        for target in targets
    ):
        release_checks.append(
            "For collector v0.155, verify `oracle.db.service` and corrected `db.namespace` "
            "values on enabled Oracle events."
        )
    comment_tag_targets = [
        target["name"]
        for target in targets
        if (
            target["events"].get("query_sample")
            and (target["advanced"].get("query_sample_collection") or {}).get(
                "allowed_comment_keys"
            )
        )
        or (
            target["events"].get("top_query")
            and (target["advanced"].get("top_query_collection") or {}).get(
                "allowed_comment_keys"
            )
        )
    ]
    if comment_tag_targets:
        release_checks.append(
            "Verify filtered `db.query.comment_tags` on query-sample/top-query events for: "
            + ", ".join(f"`{name}`" for name in comment_tag_targets)
            + "."
        )
    if mysql_wait:
        release_checks.append(
            "Verify `mysql.events_waits_current.timer_wait` is nonzero under representative load, "
            "and repeat after an AWS RDS restart/failover."
        )
    if any(target["connection_mode"] == "windows" for target in targets):
        release_checks.append(
            "Windows Performance Counter targets are infrastructure-metrics-only: record Query samples, "
            "Top queries, plans, and trace correlation as not applicable for those targets."
        )
    release_section = "\n".join(f"- {item}" for item in release_checks)
    network_targets = [
        target for target in targets if target["connection_mode"] != "windows"
    ]
    windows_targets = [
        target for target in targets if target["connection_mode"] == "windows"
    ]
    sample_targets = [
        target["name"]
        for target in network_targets
        if target["events"].get("query_sample")
    ]
    top_targets = [
        target["name"]
        for target in network_targets
        if target["events"].get("top_query")
    ]
    disabled_samples = [
        target["name"] for target in network_targets if target["name"] not in sample_targets
    ]
    disabled_top = [
        target["name"] for target in network_targets if target["name"] not in top_targets
    ]
    plan_gap_targets = [
        target["name"]
        for target in network_targets
        if target["type"] == "mariadb"
        or (
            target["type"] == "mysql"
            and parse_database_version(target["version"]) < (8, 0)
        )
    ]
    sections: list[str] = ["# Splunk Database Monitoring product validation", ""]
    if network_targets:
        sections.extend(
            [
                "## Network database targets",
                "",
                "- Open **APM > Database monitoring > Overview** and confirm every network target appears in the reviewed time window.",
                "- Confirm Metrics, Dependencies, Metadata, alerts, and the Infrastructure Monitoring database navigator are populated.",
                "- Three tabs instead of the full navigator indicates a missing infrastructure metrics pipeline or entitlement.",
            ]
        )
        if top_targets:
            sections.append(
                "- Confirm Queries and Query metrics contain current normalized-query data for: "
                + ", ".join(f"`{name}`" for name in top_targets)
                + "."
            )
        if sample_targets:
            sections.append(
                "- Confirm Query samples and Query details (Statement, supported Explain plans, Metrics, and optional Traces) for: "
                + ", ".join(f"`{name}`" for name in sample_targets)
                + "."
            )
        if disabled_top:
            sections.append(
                "- Top-query evidence is disabled/not applicable by spec for: "
                + ", ".join(f"`{name}`" for name in disabled_top)
                + "."
            )
        if disabled_samples:
            sections.append(
                "- Query-sample, plan, and trace-correlation evidence is disabled/not applicable by spec for: "
                + ", ".join(f"`{name}`" for name in disabled_samples)
                + "."
            )
        if plan_gap_targets:
            sections.append(
                "- Explain plans are not provided by the v0.155 receiver for MariaDB or "
                "MySQL 5.7; record plans as not supported while still validating metrics, "
                "top queries, and query samples for: "
                + ", ".join(f"`{name}`" for name in plan_gap_targets)
                + "."
            )
        if any(
            target["type"] in {"sqlserver", "oracledb"}
            for target in network_targets
        ):
            sections.append(
                "- Verify Stored procedures for SQL Server and Oracle; Oracle procedure counts are best-effort."
            )
        sections.append(
            "- AI Assistant summaries/recommendations require Splunk Support activation; record that handoff instead of claiming API enablement."
        )
    if windows_targets:
        sections.extend(
            [
                "",
                "## Windows Performance Counter targets",
                "",
                "- Validate current SQL Server infrastructure metrics in Infrastructure Monitoring for: "
                + ", ".join(f"`{target['name']}`" for target in windows_targets)
                + ".",
                "- Record DBMon Queries, samples, plans, stored procedures, APM correlation, and AI Assistant as not applicable for these metrics-only targets.",
            ]
        )
    if session_wait:
        sections.append("- Verify configured Oracle session-wait samples are populated.")
    sections.extend(
        [
            "",
            "## v0.155 and target-specific evidence",
            "",
            release_section or "- No additional target-specific v0.155 evidence is required.",
            "",
            "Record screenshots or operator evidence in the change ticket. The public API probe validates metrics, but Splunk does not document a public DBMon event-query API that proves query samples/top queries reached the product UI.",
            "",
        ]
    )
    return "\n".join(sections)


def non_default_advanced_controls(target: dict[str, Any]) -> list[str]:
    controls: list[str] = []
    for key, value in target["advanced"].items():
        if key == "tls":
            continue
        if key == "query_sample_collection" and value == {"max_rows_per_query": 100}:
            continue
        if key == "top_query_collection" and value == {"collection_interval": "60s"}:
            continue
        controls.append(key)
    return sorted(controls)


def coverage_payload(
    targets: list[dict[str, Any]], outputs: dict[str, bool], scrape_owner: str
) -> dict[str, Any]:
    return {
        "engines": sorted({target["type"] for target in targets}),
        "scrape_owner": scrape_owner,
        "targets": [
            {
                "name": target["name"],
                "engine": target["type"],
                "platform": target["platform"],
                "version": target["version"],
                "support_status": target["support_status"],
                "connection_mode": target["connection_mode"],
                "transport_exception": target["transport_exception"],
                "events": target["events"],
                "query_plan_support": (
                    "supported"
                    if target["type"] == "mysql"
                    and parse_database_version(target["version"]) >= (8, 0)
                    else "not_supported"
                    if target["type"] == "mariadb"
                    or (
                        target["type"] == "mysql"
                        and parse_database_version(target["version"]) < (8, 0)
                    )
                    else "engine-dependent"
                ),
                "advanced_controls": sorted(target["advanced"]),
                "non_default_advanced_controls": non_default_advanced_controls(target),
            }
            for target in targets
        ],
        "collector": {
            "metrics": "configured_unverified",
            "query_samples": (
                "configured_unverified"
                if any(t["events"].get("query_sample") for t in targets)
                else "disabled_by_spec"
            ),
            "top_queries": (
                "configured_unverified"
                if any(t["events"].get("top_query") for t in targets)
                else "disabled_by_spec"
            ),
            "oracle_session_wait_samples": (
                "configured_unverified"
                if any(t["events"].get("session_wait_sample") for t in targets)
                else "disabled_by_spec"
            ),
            "optional_metrics": "spec-supported-with-strict-enabled-schema",
            "optional_metric_attribute_and_aggregation_tuning": (
                "intentionally-gated-not-production-supported"
            ),
            "postgresql_wal_lag_legacy_feature_gate": (
                "intentionally-gated-use-postgresql.wal.delay"
            ),
            "resource_attributes": "enabled-and-sqlserver-override-value-supported",
            "sqlserver_experimental_resource_attribute_filters": (
                "intentionally-gated-not-production-supported"
            ),
            "mysql_wait_events_current": (
                "configured-unverified-with-prerequisite-and-failover-handoff"
                if any(mysql_wait_events_enabled(target) for target in targets)
                else "disabled_by_spec"
            ),
            "tls_and-datasource": "runtime-preflighted-secret-references",
            "direct_transport_exceptions": [
                {"target": target["name"], **target["transport_exception"]}
                for target in targets
                if target["transport_exception"] is not None
            ],
        },
        "runtimes": {
            "kubernetes": (
                "guarded_action_available_unexecuted"
                if scrape_owner == "kubernetes"
                else "rendered-handoff-not-owner"
                if outputs["kubernetes"]
                else "not-rendered"
            ),
            "linux": (
                "guarded_action_available_unexecuted"
                if scrape_owner == "linux"
                else "rendered-handoff-not-owner"
                if outputs["linux"]
                else "not-rendered"
            ),
            "windows": (
                "reviewed-nonmutating-powershell-validation-handoff"
                if scrape_owner == "windows"
                else "rendered-handoff-not-owner"
                if outputs["windows"]
                else "not-rendered"
            ),
        },
        "product": {
            "overview_queries_samples_metrics_dependencies_metadata": (
                "ui-validation-handoff"
                if any(target["connection_mode"] != "windows" for target in targets)
                else "not_applicable-windows-performance-counters-infrastructure-metrics-only"
            ),
            "stored_procedures": (
                "ui-validation-handoff-sqlserver-oracle"
                if any(
                    t["type"] in {"sqlserver", "oracledb"}
                    and t["connection_mode"] != "windows"
                    for t in targets
                )
                else "not_applicable"
            ),
            "apm_correlation": (
                "instrumentation-handoff"
                if any(t["connection_mode"] != "windows" for t in targets)
                else "not_applicable"
            ),
            "ai_assistant": (
                "splunk-support-handoff"
                if any(t["connection_mode"] != "windows" for t in targets)
                else "not_applicable"
            ),
        },
        "evidence_state": "configured_unverified",
    }


def deep_merge(base: Any, overlay: Any) -> Any:
    if isinstance(base, dict) and isinstance(overlay, dict):
        merged = dict(base)
        for key, value in overlay.items():
            if key in merged:
                merged[key] = deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged
    if isinstance(base, list) and isinstance(overlay, list):
        merged = list(base)
        for item in overlay:
            if item not in merged:
                merged.append(item)
        return merged
    return overlay


def reject_base_value_secrets(value: Any, path: str = "base_values") -> None:
    if isinstance(value, dict):
        env_name_value = value.get("name")
        if isinstance(env_name_value, str) and re.search(
            r"(?i)(?:password|passwd|token|secret|datasource|connection[_-]?string|private[_-]?key|api[_-]?key)",
            env_name_value,
        ):
            inline_value = value.get("value")
            if inline_value not in (None, ""):
                raise RenderError(
                    f"{path} provides an inline value for secret-like environment name; "
                    "use valueFrom and an existing Secret."
                )
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            secret_key = normalized in {
                "accesstoken",
                "apitoken",
                "clientsecret",
                "datasource",
                "password",
                "token",
            } or any(
                part in normalized
                for part in (
                    "authorization",
                    "connectionstring",
                    "privatekey",
                    "xsftoken",
                )
            )
            safe_env_reference = isinstance(child, str) and bool(
                re.fullmatch(r"\$\{env:[A-Z][A-Z0-9_]*\}", child)
            )
            if secret_key and child not in (None, "", False) and not safe_env_reference:
                raise RenderError(
                    f"{path}.{key} contains inline secret material. Render the base chart "
                    "with an external Secret and do not copy credentials into DBMon output."
                )
            reject_base_value_secrets(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_base_value_secrets(child, f"{path}[{index}]")


def merge_base_values(
    base: dict[str, Any],
    overlay: dict[str, Any],
    *,
    realm: str,
    cluster_name: str,
    distribution: str,
) -> dict[str, Any]:
    reject_base_value_secrets(base)
    receiver_types = {"postgresql", "sqlserver", "oracledb", "mysql"}

    def is_db_receiver(value: Any) -> bool:
        text = str(value)
        return text in receiver_types or any(
            text.startswith(item + "/") for item in receiver_types
        )

    def role_config(values: dict[str, Any], role: str) -> dict[str, Any]:
        section = values.get(role) or {}
        config = section.get("config") or {}
        if not isinstance(config, dict):
            raise RenderError(f"base_values.{role}.config must be a mapping.")
        return config

    for role in ("agent", "gateway"):
        receivers = role_config(base, role).get("receivers") or {}
        if any(is_db_receiver(receiver_id) for receiver_id in receivers):
            raise RenderError(
                f"base_values.{role}.config already contains a DB receiver; migrate it "
                "before assigning clusterReceiver as the sole scraper."
            )
    base_cluster = role_config(base, "clusterReceiver")
    overlay_cluster = role_config(overlay, "clusterReceiver")
    base_receivers = base_cluster.get("receivers") or {}
    overlay_receivers = overlay_cluster.get("receivers") or {}
    for receiver_id, config in base_receivers.items():
        if is_db_receiver(receiver_id) and overlay_receivers.get(receiver_id) != config:
            raise RenderError(
                f"base_values has conflicting or orphan DB receiver {receiver_id!r}; "
                "use the guarded reconfiguration action after reviewing migration impact."
            )
    overlay_pipelines = (overlay_cluster.get("service") or {}).get("pipelines") or {}
    for name, pipeline in (
        (base_cluster.get("service") or {}).get("pipelines") or {}
    ).items():
        assigned = [
            item
            for item in (pipeline or {}).get("receivers", [])
            if is_db_receiver(item)
        ]
        if assigned and (overlay_pipelines.get(name) or {}).get("receivers") != (
            pipeline or {}
        ).get("receivers"):
            raise RenderError(
                f"base_values has conflicting DB pipeline {name!r}; use the guarded "
                "reconfiguration action after review."
            )
    identity = {
        "splunkObservability.realm": (
            (base.get("splunkObservability") or {}).get("realm") or ""
        ),
        "clusterName": base.get("clusterName") or "",
        "distribution": base.get("distribution") or "",
    }
    expected = {
        "splunkObservability.realm": realm,
        "clusterName": cluster_name,
        "distribution": K8S_DISTRIBUTIONS[distribution],
    }
    for field, value in identity.items():
        if str(value) != str(expected[field]):
            raise RenderError(
                f"base_values {field}={value!r} does not match requested {expected[field]!r}; "
                "the DBMon overlay will not relabel an existing collector."
            )
    base_envs = (base.get("clusterReceiver") or {}).get("extraEnvs") or []
    overlay_envs = (overlay.get("clusterReceiver") or {}).get("extraEnvs") or []
    if not isinstance(base_envs, list):
        raise RenderError("base_values.clusterReceiver.extraEnvs must be a list.")
    if any(
        isinstance(item, dict)
        and item.get("name") == "SPLUNK_OBSERVABILITY_ACCESS_TOKEN"
        for item in base_envs
    ):
        raise RenderError(
            "base_values.clusterReceiver.extraEnvs must not redefine the "
            "chart-owned SPLUNK_OBSERVABILITY_ACCESS_TOKEN."
        )
    known = {
        item.get("name"): item
        for item in base_envs
        if isinstance(item, dict) and item.get("name")
    }
    for item in overlay_envs:
        name = item.get("name")
        if name in known and known[name] != item:
            raise RenderError(
                f"base_values clusterReceiver.extraEnvs already defines {name!r} "
                "with a different value; refusing to replace it."
            )
    managed_components = {
        "exporters": {"otlp_http/dbmon", "signalfx/dbmon"},
        "processors": {
            "memory_limiter/dbmon",
            "batch/dbmon",
            "resource_detection/dbmon",
            "resource/mysql_service_instance_id",
        },
    }
    sanitized_cluster = dict(base_cluster)
    for section, managed_ids in managed_components.items():
        current_section = base_cluster.get(section) or {}
        desired_section = overlay_cluster.get(section) or {}
        for component_id in managed_ids & set(current_section):
            if current_section.get(component_id) != desired_section.get(component_id):
                raise RenderError(
                    f"base_values has conflicting managed DBMon component "
                    f"{section}.{component_id}; use the guarded reconfiguration action."
                )
        sanitized_cluster[section] = {
            key: value
            for key, value in current_section.items()
            if key not in managed_ids
        }
    base = dict(base)
    base["clusterReceiver"] = {
        **(base.get("clusterReceiver") or {}),
        "config": sanitized_cluster,
    }
    return deep_merge(base, overlay)


def load_base_values(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RenderError(f"--base-values not found: {path}")
    data = load_yaml_or_json(path.read_text(encoding="utf-8"), source=str(path))
    if not isinstance(data, dict):
        raise RenderError(f"--base-values {path} did not parse to a mapping.")
    return data


def validate_realm(realm: str) -> None:
    if realm not in ALLOWED_REALMS:
        raise RenderError(
            f"realm {realm!r} is not listed for Splunk Database Monitoring. "
            f"Allowed: {', '.join(sorted(ALLOWED_REALMS))}."
        )


def rendered_metadata(
    *,
    realm: str,
    cluster_name: str,
    distribution: str,
    scrape_owner: str,
    collector: dict[str, Any],
    targets: list[dict[str, Any]],
    base_values: str,
) -> dict[str, Any]:
    has_mysql_family = any(target["type"] in {"mysql", "mariadb"} for target in targets)
    has_core_family = any(
        target["type"] not in {"mysql", "mariadb"} for target in targets
    )
    if has_core_family and has_mysql_family:
        metrics_pipelines = ["metrics/dbmon_core", "metrics/dbmon_mysql"]
        logs_pipelines = ["logs/dbmon_core", "logs/dbmon_mysql"]
    else:
        metrics_pipelines = ["metrics/dbmon"]
        logs_pipelines = ["logs/dbmon"]
    return {
        "skill": SKILL_NAME,
        "support_mode": (
            "unsupported-opt-in"
            if any(target["support_status"] != "official" for target in targets)
            else "official"
        ),
        "realm": realm,
        "cluster_name": cluster_name,
        "distribution": distribution,
        "scrape_owner": scrape_owner,
        "collector_version": collector["version"],
        "chart_version": collector["chart_version"],
        "collector_namespace": collector["namespace"],
        "collector_release_name": collector["release_name"],
        "collector_kube_context": collector["kube_context"],
        "collector_memory_mib": collector["memory_mib"],
        "collector_cpu_limit": collector["cpu_limit"],
        "sizing_evidence": collector.get("sizing_evidence"),
        "max_targets_per_collector": MAX_TARGETS_PER_COLLECTOR,
        "target_count": len(targets),
        "targets": [
            {
                "name": target["name"],
                "type": target["type"],
                "receiver_type": target["receiver_type"],
                "receiver_id": target["receiver_id"],
                "platform": target["platform"],
                "version": target["version"],
                "collector_floor": VERSION_FLOORS[target["type"]],
                "support_status": target["support_status"],
                "support_notes": target["support_notes"],
                "connection_mode": target["connection_mode"],
                "transport_exception": target["transport_exception"],
                "validation_metric": DEFAULT_VALIDATION_METRICS[target["type"]],
                "validation_filters": target["validation_filters"],
                "events": target["events"],
                "tls_files": [
                    target["advanced"]["tls"][key]
                    for key in ("ca_file", "cert_file", "key_file")
                    if (target["advanced"].get("tls") or {}).get(key)
                ],
            }
            for target in targets
        ],
        "base_values_merged": bool(base_values),
        "validation_metrics": sorted(
            {DEFAULT_VALIDATION_METRICS[target["type"]] for target in targets}
        ),
        "validation_probes": [
            {
                "target": target["name"],
                "receiver_id": target["receiver_id"],
                "metric": DEFAULT_VALIDATION_METRICS[target["type"]],
                "filters": target["validation_filters"],
            }
            for target in targets
        ],
        "collector_config_contract": {
            "metrics_pipelines": metrics_pipelines,
            "logs_pipelines": logs_pipelines,
            "event_exporter": "otlp_http/dbmon",
            "event_endpoint": f"https://ingest.{realm}.observability.splunkcloud.com/v3/event",
        },
        "warnings": [
            "Splunk Database Monitoring requires the appropriate Splunk Observability Cloud DBMon license entitlement; this renderer does not verify tenant licensing.",
            "APM query-to-trace correlation requires a separate Splunk APM license and application instrumentation.",
            *(
                [
                    "MariaDB 10.5+ and MySQL 5.7+ are supported DBMon product targets, but the v0.155 receiver does not provide explain plans for MariaDB or MySQL 5.7."
                ]
                if any(
                    target["type"] == "mariadb"
                    or (
                        target["type"] == "mysql"
                        and parse_database_version(target["version"]) < (8, 0)
                    )
                    for target in targets
                )
                else []
            ),
            *[
                f"{target['receiver_id']} uses discrete direct-connect fields; for explicit driver TLS/trust controls, use a secret-backed datasource connection."
                for target in targets
                if target["type"] in {"sqlserver", "oracledb"}
                and target["connection_mode"] == "direct"
            ],
            *[
                (
                    f"{target['receiver_id']} is rendered by explicit unsupported-target "
                    f"opt-in and is outside Splunk's published DBMon support matrix: "
                    f"{'; '.join(target['support_notes'])}."
                )
                for target in targets
                if target["support_status"] != "official"
            ],
        ],
    }


def build_plan(
    spec: dict[str, Any], args: argparse.Namespace
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, bool]]:
    collector = collector_settings(spec, args)
    outputs = output_settings(spec)
    if not any(outputs.values()):
        raise RenderError(
            "At least one of outputs.kubernetes/linux/windows must be true."
        )
    if args.base_values and not outputs["kubernetes"]:
        raise RenderError(
            "--base-values is valid only when outputs.kubernetes is true."
        )
    enabled_runtimes = [name for name, enabled in outputs.items() if enabled]
    scrape_owner = str(spec.get("scrape_owner") or "").strip().lower()
    if not scrape_owner:
        if len(enabled_runtimes) == 1:
            scrape_owner = enabled_runtimes[0]
        else:
            raise RenderError(
                "scrape_owner is required when rendering multiple runtimes; choose exactly "
                "one of kubernetes, linux, or windows to prevent duplicate database scrapes."
            )
    if scrape_owner not in outputs or not outputs[scrape_owner]:
        raise RenderError(
            f"scrape_owner {scrape_owner!r} must name an enabled output runtime."
        )
    realm = args.realm or str(
        spec.get("realm") or os.environ.get("SPLUNK_O11Y_REALM") or ""
    )
    if not realm:
        raise RenderError(
            "realm is required in the spec, --realm, or SPLUNK_O11Y_REALM."
        )
    cluster_name = args.cluster_name or str(spec.get("cluster_name") or "")
    if cluster_name and not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", cluster_name
    ):
        raise RenderError(
            "cluster_name must start with an alphanumeric character and contain only "
            "letters, digits, '.', '_' or '-'."
        )
    distribution = (
        (
            args.distribution
            or str(
                spec.get("distribution")
                or (
                    "kubernetes"
                    if outputs["kubernetes"]
                    else "windows"
                    if outputs["windows"] and not outputs["linux"]
                    else "linux"
                )
            )
        )
        .strip()
        .lower()
    )
    validate_realm(realm)
    allow_unsupported = bool(args.allow_unsupported_targets) or bool_value(
        spec.get("allow_unsupported_targets"),
        label="allow_unsupported_targets",
        default=False,
    )
    targets = normalize_targets(
        spec,
        collector["version"],
        collector_namespace=collector["namespace"],
        allow_unsupported=allow_unsupported,
    )
    collector["sizing_evidence"] = normalized_sizing_evidence(
        spec.get("sizing_evidence"),
        required=True,
    )
    sizing_evidence = collector["sizing_evidence"] or {}
    configured_cpu = (
        int(collector["cpu_limit"][:-1]) / 1000
        if collector["cpu_limit"].endswith("m")
        else float(collector["cpu_limit"])
    )
    if collector["memory_mib"] < sizing_evidence["peak_memory_mib"]:
        raise RenderError(
            "collector.memory_mib is below sizing_evidence.peak_memory_mib."
        )
    if configured_cpu < sizing_evidence["peak_cpu_cores"]:
        raise RenderError(
            "collector.cpu_limit is below sizing_evidence.peak_cpu_cores."
        )
    if len(targets) > sizing_evidence["target_count"]:
        raise RenderError(
            "Configured target count exceeds sizing_evidence.target_count."
        )
    for tls_path in required_tls_files(targets):
        parsed_tls_path = (
            PureWindowsPath(tls_path)
            if scrape_owner == "windows"
            else PurePosixPath(tls_path)
        )
        if not parsed_tls_path.is_absolute() or ".." in parsed_tls_path.parts:
            raise RenderError(
                f"TLS file path {tls_path!r} must be an absolute, traversal-free "
                f"{scrape_owner} runtime path."
            )
        if scrape_owner == "windows":
            safe_tls_path = re.fullmatch(r"[A-Za-z]:\\[A-Za-z0-9 ._\\/-]+", tls_path)
        else:
            safe_tls_path = re.fullmatch(r"/[A-Za-z0-9._/-]+", tls_path)
        if not safe_tls_path:
            raise RenderError(
                f"TLS file path {tls_path!r} contains unsupported runtime path characters."
            )
    if any(target["connection_mode"] == "windows" for target in targets) and (
        outputs["kubernetes"] or outputs["linux"]
    ):
        raise RenderError(
            "Windows Performance Counters mode is Windows-only. Disable Kubernetes/Linux "
            "outputs or use a direct SQL Server database connection."
        )
    if outputs["kubernetes"]:
        if not collector["kube_context"]:
            raise RenderError(
                "collector.kube_context is required when outputs.kubernetes is true so "
                "live validation, apply, and rollback are bound to a reviewed cluster."
            )
        if distribution not in K8S_DISTRIBUTIONS:
            raise RenderError(
                f"distribution {distribution!r} is not supported by Splunk OTel chart 0.158.0. "
                f"Allowed: {', '.join(sorted(key for key in K8S_DISTRIBUTIONS if key))}."
            )
        if distribution == "eks/fargate":
            raise RenderError(
                "DBMon cannot use the chart clusterReceiver on eks/fargate because the chart "
                "hard-codes two replicas, violating the single-scraper rule. Use a dedicated "
                "Linux gateway collector."
            )
        if not cluster_name:
            raise RenderError("cluster_name is required for Kubernetes DBMon output.")
        for target in targets:
            if target["connection_mode"] == "windows":
                continue
            secret_namespace = target["credentials"]["kubernetes_secret"]["namespace"]
            if secret_namespace != collector["namespace"]:
                raise RenderError(
                    f"{target['receiver_id']} Secret namespace {secret_namespace!r} must equal "
                    f"collector.namespace {collector['namespace']!r}; secretKeyRef cannot cross namespaces."
                )
    else:
        expected_distribution = "windows" if scrape_owner == "windows" else "linux"
        if distribution != expected_distribution:
            raise RenderError(
                f"distribution must be {expected_distribution!r} when Kubernetes output "
                f"is disabled and scrape_owner is {scrape_owner!r}."
            )
    apply_sizing(collector, targets)
    plan = {
        "skill": SKILL_NAME,
        "realm": realm,
        "cluster_name": cluster_name,
        "distribution": distribution,
        "scrape_owner": scrape_owner,
        "collector_version": collector["version"],
        "chart_version": collector["chart_version"],
        "collector_memory_mib": collector["memory_mib"],
        "sizing_evidence": collector["sizing_evidence"],
        "outputs": outputs,
        "target_count": len(targets),
        "target_types": sorted({target["type"] for target in targets}),
        "allow_unsupported_targets": allow_unsupported,
        "unsupported_target_count": sum(
            1 for target in targets if target["support_status"] != "official"
        ),
        "base_values": bool(args.base_values),
        "validation_metrics": sorted(
            {DEFAULT_VALIDATION_METRICS[target["type"]] for target in targets}
        ),
    }
    return plan, collector, targets, outputs


def prepare_rendered_output(out: Path) -> Path:
    """Create a clean, owned packet root without following a user-controlled link."""
    out = Path(os.path.abspath(os.fspath(out.expanduser())))
    skill_root = PROJECT_ROOT / "skills" / SKILL_NAME
    forbidden = {Path(out.anchor), PROJECT_ROOT, skill_root, Path.home()}
    if out in forbidden:
        raise RenderError(f"Refusing dangerous output directory: {out}")

    if out.exists() or out.is_symlink():
        info = os.lstat(out)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise RenderError("Output directory must be a real directory, not a symlink.")
        if info.st_uid != os.geteuid():
            raise RenderError("Output directory must be owned by the current user.")
        entries = list(out.iterdir())
        if entries:
            trusted = False
            metadata_path = out / "metadata.json"
            if metadata_path.is_file() and not metadata_path.is_symlink():
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    trusted = metadata.get("skill") == SKILL_NAME
                except (OSError, UnicodeError, json.JSONDecodeError):
                    trusted = False
            if not trusted:
                raise RenderError(
                    "Refusing to replace a nonempty output directory that is not a prior "
                    f"{SKILL_NAME} packet. Choose an empty directory."
                )
        shutil.rmtree(out)
    else:
        parent = out.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        info = os.lstat(parent)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise RenderError("Nearest existing output parent must be a real directory.")
        if info.st_uid != os.geteuid():
            raise RenderError("Nearest existing output parent must be owned by the current user.")
    out.mkdir(parents=True, mode=0o700)
    return out


def render(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec)
    if not spec_path.is_file():
        raise RenderError(f"spec not found: {spec_path}")
    spec = load_spec(spec_path)
    plan, collector, targets, outputs = build_plan(spec, args)

    if args.dry_run:
        if args.json:
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            print("Splunk Observability Database Monitoring render plan")
            for key, value in plan.items():
                print(f"  {key}: {value}")
        return 0

    out = prepare_rendered_output(Path(args.output_dir))

    realm = plan["realm"]
    cluster_name = plan["cluster_name"]
    distribution = plan["distribution"]
    scrape_owner = plan["scrape_owner"]
    overlay = overlay_values(
        realm=realm,
        cluster_name=cluster_name,
        distribution=distribution,
        collector=collector,
        targets=targets,
    )

    if outputs["kubernetes"]:
        overlay_text = dump_yaml(overlay, sort_keys=False)
        overlay_sha256 = hashlib.sha256(overlay_text.encode()).hexdigest()
        write_text(out / "k8s" / "values.dbmon.clusterreceiver.yaml", overlay_text)
        write_text(out / "k8s" / "secrets.dbmon.stub.yaml", secret_stub(targets))
        write_text(
            out / "k8s" / "handoff-base-collector.sh",
            handoff_k8s(
                realm=realm,
                cluster_name=cluster_name,
                distribution=distribution,
                scrape_owner=scrape_owner,
                collector=collector,
            ),
            executable=True,
        )
        write_text(
            out / "scripts" / "apply-dbmon-overlay.sh",
            render_apply_overlay_script(
                realm=realm,
                cluster_name=cluster_name,
                distribution=distribution,
                scrape_owner=scrape_owner,
                collector=collector,
                targets=targets,
                overlay_sha256=overlay_sha256,
            ),
            executable=True,
        )
        write_text(
            out / "scripts" / "rollback-dbmon-k8s.sh",
            render_rollback_k8s_script(collector=collector),
            executable=True,
        )
        if args.base_values:
            base_values = load_base_values(Path(args.base_values))
            merged_values = merge_base_values(
                base_values,
                overlay,
                realm=realm,
                cluster_name=cluster_name,
                distribution=distribution,
            )
            write_yaml(
                out / "k8s" / "values.dbmon.merged.yaml",
                merged_values,
            )

    if outputs["linux"]:
        linux_standalone = standalone_config(realm, collector, targets)
        linux_fragment = collector_fragment(
            realm, collector, targets, token_env="SPLUNK_ACCESS_TOKEN"
        )
        linux_fragment_text = dump_yaml(linux_fragment, sort_keys=False)
        write_yaml(
            out / "linux" / "collector-dbmon.yaml",
            linux_standalone,
        )
        write_text(
            out / "linux" / "collector-dbmon.fragment.yaml",
            linux_fragment_text,
        )
        write_text(
            out / "linux" / "dbmon.env.template",
            credential_env_template(
                targets,
                platform="linux",
                include_access_token=True,
                memory_mib=collector["memory_mib"],
            ),
        )
        write_text(
            out / "linux" / "handoff-base-collector.sh",
            handoff_linux(),
            executable=True,
        )
        write_text(
            out / "scripts" / "secure-env.py", secure_env_helper(), executable=True
        )
        write_text(
            out / "scripts" / "audit-base-config.py",
            base_config_audit_helper(),
            executable=True,
        )
        write_text(
            out / "scripts" / "apply-dbmon-linux.sh",
            render_apply_linux_script(
                scrape_owner=scrape_owner,
                collector=collector,
                targets=targets,
                source_config_sha256=hashlib.sha256(
                    linux_fragment_text.encode()
                ).hexdigest(),
            ),
            executable=True,
        )
        write_text(
            out / "scripts" / "rollback-dbmon-linux.sh",
            render_rollback_linux_script(),
            executable=True,
        )

    if outputs["windows"]:
        write_yaml(
            out / "windows" / "collector-dbmon.yaml",
            standalone_config(realm, collector, targets),
        )
        write_yaml(
            out / "windows" / "collector-dbmon.fragment.yaml",
            collector_fragment(
                realm, collector, targets, token_env="SPLUNK_ACCESS_TOKEN"
            ),
        )
        write_text(
            out / "windows" / "dbmon.env.template",
            credential_env_template(
                targets,
                platform="windows",
                include_access_token=False,
                memory_mib=collector["memory_mib"],
            ),
        )
        write_text(
            out / "scripts" / "apply-dbmon-windows.ps1",
            render_apply_windows_script(
                scrape_owner=scrape_owner, collector=collector, targets=targets
            ),
        )
        write_text(
            out / "scripts" / "rollback-dbmon-windows.ps1",
            render_rollback_windows_script(),
        )

    for target in targets:
        write_text(
            out / "prerequisites" / f"{target['name']}.md",
            prerequisite_runbook(target),
        )
    write_text(
        out / "apm" / "query-correlation.md",
        apm_correlation_reference(targets),
    )
    write_text(
        out / "validation" / "product-validation.md",
        product_validation_reference(targets),
    )
    write_json(out / "coverage.json", coverage_payload(targets, outputs, scrape_owner))

    write_text(
        out / "references" / "gateway-routing.sqlserver.md",
        gateway_reference(),
    )
    write_json(
        out / "metadata.json",
        rendered_metadata(
            realm=realm,
            cluster_name=cluster_name,
            distribution=distribution,
            scrape_owner=scrape_owner,
            collector=collector,
            targets=targets,
            base_values=args.base_values,
        ),
    )
    return 0


def main() -> int:
    try:
        return render(parse_args())
    except RenderError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
