"""Render Splunk Observability Database Monitoring collector assets."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


SKILL_NAME = "splunk-observability-database-monitoring-setup"
DEFAULT_COLLECTOR_VERSION = "v0.150.0"
ALLOWED_REALMS = {"us0", "us1", "eu0", "eu1", "eu2", "au0", "jp0", "sg0"}
TARGET_TYPES = {"postgresql", "sqlserver", "oracledb"}
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
}
VERSION_FLOORS = {
    "postgresql": "v0.147.0",
    "sqlserver": "v0.148.0",
    "oracledb": "v0.148.0",
}
SUPPORTED = {
    "postgresql": {
        "versions": {"14.20", "17.7", "14.15", "17.5"},
        "platforms": {"azure-flexible-server", "aws-rds"},
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
}
PROCESSORS = ["memory_limiter", "batch", "resourcedetection", "resource"]
SECRET_VALUE_KEYS = {
    "password",
    "token",
    "access_token",
    "api_token",
    "api_key",
    "datasource",
    "connection_string",
}

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "shared" / "lib"))
from yaml_compat import dump_yaml, load_yaml_or_json  # noqa: E402


class RenderError(ValueError):
    """Raised when the DBMon spec or rendered assets are invalid."""


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
    reject_inline_secret_fields(data)
    return data


def reject_inline_secret_fields(value: Any, path: str = "spec") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if key_text in SECRET_VALUE_KEYS and child not in (None, ""):
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
    if lowered in {"mysql", "mariadb"}:
        raise RenderError(
            "MySQL/MariaDB are not supported by this v1 skill. Splunk has not "
            "published an official DBMon collection page for MySQL, and the "
            "Splunk MySQL integration docs remain deprecated/end-of-support."
        )
    target_type = TYPE_ALIASES.get(lowered)
    if target_type not in TARGET_TYPES:
        raise RenderError(
            f"Unsupported target type {raw!r}; expected postgresql, sqlserver, or oracledb."
        )
    return target_type


def normalize_platform(raw: Any) -> str:
    return str(raw or "").strip().lower().replace(" ", "-").replace("_", "-")


def safe_name(raw: Any) -> str:
    name = str(raw or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise RenderError(
            f"Target name {raw!r} must use only letters, digits, '_' or '-'."
        )
    return name


def env_prefix(name: str) -> str:
    return "DBMON_" + re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()


def parse_semver(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(version).strip())
    if not match:
        raise RenderError(f"Collector version {version!r} must look like v0.150.0.")
    return tuple(int(part) for part in match.groups())


def check_collector_floor(target_type: str, collector_version: str) -> None:
    floor = VERSION_FLOORS[target_type]
    if parse_semver(collector_version) < parse_semver(floor):
        raise RenderError(
            f"{target_type} Database Monitoring requires collector {floor} or later; "
            f"got {collector_version}."
        )


def normalize_targets(
    spec: dict[str, Any], collector_version: str, *, allow_unsupported: bool
) -> list[dict[str, Any]]:
    raw_targets = spec.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise RenderError("Spec must define at least one targets[] entry.")

    seen: set[str] = set()
    targets: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_targets):
        if not isinstance(raw, dict):
            raise RenderError(f"targets[{index}] must be a mapping.")
        target_type = normalize_type(raw.get("type"))
        name = safe_name(raw.get("name"))
        if name in seen:
            raise RenderError(f"Duplicate target name {name!r}.")
        seen.add(name)

        platform = normalize_platform(raw.get("platform"))
        version = str(raw.get("version", "")).strip()
        supported = SUPPORTED[target_type]
        support_notes: list[str] = []
        if platform not in supported["platforms"]:
            support_notes.append(
                f"platform {platform!r} is outside the official support matrix "
                f"(allowed: {', '.join(sorted(supported['platforms']))})"
            )
        if version not in supported["versions"]:
            support_notes.append(
                f"version {version!r} is outside the official support matrix "
                f"(allowed: {', '.join(sorted(supported['versions']))})"
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
        normalized["receiver_id"] = f"{target_type}/{name}"
        normalized["platform"] = platform
        normalized["version"] = version
        normalized["support_status"] = (
            "unsupported_opt_in" if support_notes else "official"
        )
        normalized["support_notes"] = support_notes
        normalized["events"] = normalized_events(raw.get("events"))
        normalized["credentials"] = normalized_credentials(name, raw.get("credentials"))
        validate_connection_fields(normalized)
        targets.append(normalized)
    return targets


def normalized_events(raw: Any) -> dict[str, bool]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise RenderError("target.events must be a mapping when provided.")
    return {
        "query_sample": bool(raw.get("query_sample", True)),
        "top_query": bool(raw.get("top_query", True)),
    }


def normalized_credentials(name: str, raw: Any) -> dict[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise RenderError(f"{name}.credentials must be a mapping.")

    prefix = env_prefix(name)
    linux_env = raw.get("linux_env") or {}
    if not isinstance(linux_env, dict):
        raise RenderError(f"{name}.credentials.linux_env must be a mapping.")
    username_var = str(linux_env.get("username_var") or f"{prefix}_USERNAME")
    password_var = str(linux_env.get("password_var") or f"{prefix}_PASSWORD")

    k8s_secret = raw.get("kubernetes_secret") or {}
    if not isinstance(k8s_secret, dict):
        raise RenderError(f"{name}.credentials.kubernetes_secret must be a mapping.")
    secret_name = str(k8s_secret.get("name") or f"dbmon-{name}")
    secret_namespace = str(k8s_secret.get("namespace") or "splunk-otel")
    username_key = str(k8s_secret.get("username_key") or "username")
    password_key = str(k8s_secret.get("password_key") or "password")

    for label, value in {
        "username_var": username_var,
        "password_var": password_var,
        "secret_name": secret_name,
        "secret_namespace": secret_namespace,
        "username_key": username_key,
        "password_key": password_key,
    }.items():
        if not value:
            raise RenderError(f"{name}.credentials {label} cannot be empty.")

    return {
        "username_var": username_var,
        "password_var": password_var,
        "kubernetes_secret": {
            "name": secret_name,
            "namespace": secret_namespace,
            "username_key": username_key,
            "password_key": password_key,
        },
    }


def validate_connection_fields(target: dict[str, Any]) -> None:
    target_type = target["type"]
    name = target["name"]
    if target_type == "postgresql":
        if not target.get("endpoint"):
            raise RenderError(f"postgresql/{name} requires endpoint.")
        databases = target.get("databases")
        if not isinstance(databases, list) or not databases:
            raise RenderError(f"postgresql/{name} requires a non-empty databases list.")
    elif target_type == "sqlserver":
        if not target.get("server"):
            raise RenderError(f"sqlserver/{name} requires server.")
    elif target_type == "oracledb":
        if not target.get("endpoint"):
            raise RenderError(f"oracledb/{name} requires endpoint.")
        if not target.get("service"):
            raise RenderError(f"oracledb/{name} requires service.")


def receiver_config(target: dict[str, Any]) -> dict[str, Any]:
    creds = target["credentials"]
    config: dict[str, Any] = {
        "collection_interval": str(target.get("collection_interval") or "10s"),
        "username": f"${{env:{creds['username_var']}}}",
        "password": f"${{env:{creds['password_var']}}}",
    }
    events = target["events"]
    config["events"] = {
        "db.server.query_sample": {"enabled": events["query_sample"]},
        "db.server.top_query": {"enabled": events["top_query"]},
    }

    if target["type"] == "postgresql":
        config["endpoint"] = str(target["endpoint"])
        config["databases"] = [str(item) for item in target["databases"]]
        tls = target.get("tls")
        if isinstance(tls, dict):
            config["tls"] = tls
    elif target["type"] == "sqlserver":
        config["server"] = str(target["server"])
        config["port"] = int(target.get("port") or 1433)
        if target.get("instance_name"):
            config["instance_name"] = str(target["instance_name"])
        config["resource_attributes"] = {
            "sqlserver.instance.name": {"enabled": True},
        }
    elif target["type"] == "oracledb":
        config["endpoint"] = str(target["endpoint"])
        config["service"] = str(target["service"])
    return config


def collector_settings(spec: dict[str, Any], args: argparse.Namespace) -> dict[str, str]:
    collector = spec.get("collector") or {}
    if not isinstance(collector, dict):
        raise RenderError("spec.collector must be a mapping when provided.")
    release_name = str(collector.get("release_name") or "splunk-otel-collector")
    version = args.collector_version or str(
        collector.get("version") or DEFAULT_COLLECTOR_VERSION
    )
    return {
        "version": version,
        "namespace": str(collector.get("namespace") or "splunk-otel"),
        "release_name": release_name,
        "secret_name": str(collector.get("secret_name") or f"{release_name}-splunk"),
        "token_key": str(
            collector.get("token_key") or "splunk_observability_access_token"
        ),
    }


def output_settings(spec: dict[str, Any]) -> dict[str, bool]:
    raw = spec.get("outputs") or {}
    if not isinstance(raw, dict):
        raise RenderError("spec.outputs must be a mapping when provided.")
    return {
        "kubernetes": bool(raw.get("kubernetes", True)),
        "linux": bool(raw.get("linux", True)),
    }


def overlay_values(
    *,
    realm: str,
    cluster_name: str,
    distribution: str,
    collector: dict[str, str],
    targets: list[dict[str, Any]],
) -> dict[str, Any]:
    receivers = {target["receiver_id"]: receiver_config(target) for target in targets}
    receiver_ids = [target["receiver_id"] for target in targets]
    extra_envs = [
        {
            "name": "SPLUNK_ACCESS_TOKEN",
            "valueFrom": {
                "secretKeyRef": {
                    "name": collector["secret_name"],
                    "key": collector["token_key"],
                }
            },
        }
    ]
    for env in db_secret_envs(targets):
        extra_envs.append(env)

    return {
        "clusterName": cluster_name,
        "distribution": distribution,
        "clusterReceiver": {
            "enabled": True,
            "replicas": 1,
            "extraEnvs": extra_envs,
            "config": collector_config(
                realm=realm,
                receivers=receivers,
                receiver_ids=receiver_ids,
                include_signalfx_exporter=False,
            ),
        },
    }


def collector_config(
    *,
    realm: str,
    receivers: dict[str, Any],
    receiver_ids: list[str],
    include_signalfx_exporter: bool,
) -> dict[str, Any]:
    exporters: dict[str, Any] = {
        "otlphttp/dbmon": {
            "headers": {
                "X-SF-Token": "${env:SPLUNK_ACCESS_TOKEN}",
                "X-splunk-instrumentation-library": "dbmon",
            },
            "logs_endpoint": f"https://ingest.{realm}.observability.splunkcloud.com/v3/event",
            "sending_queue": {
                "batch": {
                    "max_size": 10485760,
                    "sizer": "bytes",
                }
            },
        }
    }
    if include_signalfx_exporter:
        exporters["signalfx"] = {
            "access_token": "${env:SPLUNK_ACCESS_TOKEN}",
            "realm": realm,
        }

    return {
        "receivers": receivers,
        "processors": {
            "memory_limiter": {"check_interval": "2s", "limit_mib": 256},
            "batch": {},
            "resourcedetection": {
                "detectors": ["system"],
                "system": {"hostname_sources": ["os"]},
            },
            "resource": {"attributes": []},
        },
        "exporters": exporters,
        "service": {
            "pipelines": {
                "metrics": {
                    "receivers": receiver_ids,
                    "processors": list(PROCESSORS),
                    "exporters": ["signalfx"],
                },
                "logs/dbmon": {
                    "receivers": receiver_ids,
                    "processors": list(PROCESSORS),
                    "exporters": ["otlphttp/dbmon"],
                },
            }
        },
    }


def db_secret_envs(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    envs: list[dict[str, Any]] = []
    for target in targets:
        creds = target["credentials"]
        secret = creds["kubernetes_secret"]
        envs.extend(
            [
                {
                    "name": creds["username_var"],
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": secret["name"],
                            "key": secret["username_key"],
                        }
                    },
                },
                {
                    "name": creds["password_var"],
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": secret["name"],
                            "key": secret["password_key"],
                        }
                    },
                },
            ]
        )
    return envs


def secret_stub(targets: list[dict[str, Any]]) -> str:
    blocks: list[str] = [
        "# Placeholder-only DB credential Secret manifests.",
        "# Replace values outside this repo or create equivalent Secrets with kubectl.",
        "# DO NOT commit real database credentials.",
    ]
    for target in targets:
        secret = target["credentials"]["kubernetes_secret"]
        blocks.append(
            "\n".join(
                [
                    "---",
                    "apiVersion: v1",
                    "kind: Secret",
                    "metadata:",
                    f"  name: {secret['name']}",
                    f"  namespace: {secret['namespace']}",
                    "type: Opaque",
                    "stringData:",
                    f"  {secret['username_key']}: PLACEHOLDER_USERNAME",
                    f"  {secret['password_key']}: PLACEHOLDER_PASSWORD",
                ]
            )
        )
    return "\n".join(blocks) + "\n"


def linux_config(realm: str, targets: list[dict[str, Any]]) -> dict[str, Any]:
    receivers = {target["receiver_id"]: receiver_config(target) for target in targets}
    return collector_config(
        realm=realm,
        receivers=receivers,
        receiver_ids=[target["receiver_id"] for target in targets],
        include_signalfx_exporter=True,
    )


def linux_env_template(targets: list[dict[str, Any]]) -> str:
    lines = [
        "# Fill these values locally before running the Linux collector.",
        "# Do not commit this file after adding real values.",
        "SPLUNK_ACCESS_TOKEN=",
    ]
    for target in targets:
        creds = target["credentials"]
        lines.extend(
            [
                f"{creds['username_var']}=",
                f"{creds['password_var']}=",
            ]
        )
    return "\n".join(lines) + "\n"


def handoff_k8s(
    *, realm: str, cluster_name: str, distribution: str, collector: dict[str, str]
) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
OUTPUT_DIR="$(cd "${{HERE}}/.." && pwd)"
BASE_OUTPUT_DIR="${{BASE_OUTPUT_DIR:-/tmp/splunk-observability-otel-rendered}}"
MERGED_VALUES="${{MERGED_VALUES:-${{HERE}}/values.dbmon.merged.yaml}}"

echo "Render the base Splunk OTel Collector values first:"
echo "  bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh \\"
echo "    --render-k8s --realm {realm} --cluster-name {cluster_name} \\"
echo "    --distribution {distribution} --output-dir ${{BASE_OUTPUT_DIR}}"
echo
echo "Then re-render DBMon with --base-values to produce a merge that preserves"
echo "existing receivers/processors/exporters/pipeline arrays:"
echo "  bash skills/splunk-observability-database-monitoring-setup/scripts/setup.sh \\"
echo "    --render --spec skills/splunk-observability-database-monitoring-setup/template.example \\"
echo "    --base-values ${{BASE_OUTPUT_DIR}}/k8s/values.yaml --output-dir ${{OUTPUT_DIR}}"
echo
echo "Apply with Helm after reviewing ${collector['version']} chart compatibility:"
echo "  helm upgrade --install {collector['release_name']} splunk-otel-collector-chart/splunk-otel-collector \\"
echo "    -n {collector['namespace']} --create-namespace -f ${{MERGED_VALUES}}"
"""


def handoff_linux() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "1. Populate ${HERE}/dbmon.env from your local secret store."
echo "2. Export the env file before starting or validating the collector:"
echo "     set -a; . ${HERE}/dbmon.env; set +a"
echo "3. Merge ${HERE}/collector-dbmon.yaml with your existing Splunk OTel"
echo "   Collector Linux config, or pass both config files to a collector runtime"
echo "   that supports multi-file configuration."
"""


def gateway_reference() -> str:
    source = (
        Path(__file__).resolve().parents[1]
        / "references"
        / "gateway-routing.sqlserver.md"
    )
    return source.read_text(encoding="utf-8")


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


def align_dbmon_pipeline_after_merge(values: dict[str, Any]) -> dict[str, Any]:
    cluster_config = ((values.get("clusterReceiver") or {}).get("config") or {})
    pipelines = ((cluster_config.get("service") or {}).get("pipelines") or {})
    metrics = pipelines.get("metrics") or {}
    logs = pipelines.get("logs/dbmon") or {}
    if metrics and logs:
        logs["processors"] = list(metrics.get("processors") or [])
        logs["exporters"] = ["otlphttp/dbmon"]
    return values


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
    collector: dict[str, str],
    targets: list[dict[str, Any]],
    base_values: str,
) -> dict[str, Any]:
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
        "collector_version": collector["version"],
        "collector_namespace": collector["namespace"],
        "target_count": len(targets),
        "targets": [
            {
                "name": target["name"],
                "type": target["type"],
                "receiver_id": target["receiver_id"],
                "platform": target["platform"],
                "version": target["version"],
                "collector_floor": VERSION_FLOORS[target["type"]],
                "support_status": target["support_status"],
                "support_notes": target["support_notes"],
            }
            for target in targets
        ],
        "base_values_merged": bool(base_values),
        "warnings": [
            "Splunk Database Monitoring requires the appropriate Splunk Observability Cloud DBMon license entitlement; this renderer does not verify tenant licensing.",
            "MySQL/MariaDB are intentionally excluded from v1 until Splunk publishes an official DBMon collection page for them.",
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
) -> tuple[dict[str, Any], dict[str, str], list[dict[str, Any]], dict[str, bool]]:
    collector = collector_settings(spec, args)
    realm = args.realm or str(
        spec.get("realm") or os.environ.get("SPLUNK_O11Y_REALM") or "us0"
    )
    cluster_name = args.cluster_name or str(spec.get("cluster_name") or "lab-cluster")
    distribution = args.distribution or str(spec.get("distribution") or "kubernetes")
    validate_realm(realm)
    allow_unsupported = bool(args.allow_unsupported_targets) or bool(
        spec.get("allow_unsupported_targets", False)
    )
    targets = normalize_targets(
        spec, collector["version"], allow_unsupported=allow_unsupported
    )
    outputs = output_settings(spec)
    plan = {
        "skill": SKILL_NAME,
        "realm": realm,
        "cluster_name": cluster_name,
        "distribution": distribution,
        "collector_version": collector["version"],
        "outputs": outputs,
        "target_count": len(targets),
        "target_types": sorted({target["type"] for target in targets}),
        "allow_unsupported_targets": allow_unsupported,
        "unsupported_target_count": sum(
            1 for target in targets if target["support_status"] != "official"
        ),
        "base_values": bool(args.base_values),
    }
    return plan, collector, targets, outputs


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

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    realm = plan["realm"]
    cluster_name = plan["cluster_name"]
    distribution = plan["distribution"]
    overlay = overlay_values(
        realm=realm,
        cluster_name=cluster_name,
        distribution=distribution,
        collector=collector,
        targets=targets,
    )

    if outputs["kubernetes"]:
        write_yaml(out / "k8s" / "values.dbmon.clusterreceiver.yaml", overlay)
        write_text(out / "k8s" / "secrets.dbmon.stub.yaml", secret_stub(targets))
        write_text(
            out / "k8s" / "handoff-base-collector.sh",
            handoff_k8s(
                realm=realm,
                cluster_name=cluster_name,
                distribution=distribution,
                collector=collector,
            ),
            executable=True,
        )
        if args.base_values:
            base_values = load_base_values(Path(args.base_values))
            merged_values = align_dbmon_pipeline_after_merge(
                deep_merge(base_values, overlay)
            )
            write_yaml(
                out / "k8s" / "values.dbmon.merged.yaml",
                merged_values,
            )

    if outputs["linux"]:
        write_yaml(out / "linux" / "collector-dbmon.yaml", linux_config(realm, targets))
        write_text(out / "linux" / "dbmon.env.template", linux_env_template(targets))
        write_text(
            out / "linux" / "handoff-base-collector.sh",
            handoff_linux(),
            executable=True,
        )

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
