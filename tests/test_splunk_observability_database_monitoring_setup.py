"""Production-contract regressions for the Splunk Observability DBMon skill."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "skills/splunk-observability-database-monitoring-setup"
SETUP = SKILL / "scripts/setup.sh"
VALIDATE = SKILL / "scripts/validate.sh"
API_PROBE = SKILL / "scripts/api_probe.py"
TEMPLATE = SKILL / "template.example"
LIB_DIR = REPO_ROOT / "skills/shared/lib"
sys.path.insert(0, str(LIB_DIR))
from yaml_compat import dump_yaml, load_yaml_or_json  # noqa: E402

api_probe_spec = importlib.util.spec_from_file_location("dbmon_api_probe", API_PROBE)
assert api_probe_spec and api_probe_spec.loader
dbmon_api_probe = importlib.util.module_from_spec(api_probe_spec)
api_probe_spec.loader.exec_module(dbmon_api_probe)


class FakeResponse:
    def __init__(self, body: str) -> None:
        self.body = body.encode("utf-8")
        self.stream = io.BytesIO(self.body)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)

    def readline(self, size: int = -1) -> bytes:
        return self.stream.readline(size)


def run_setup(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        ["bash", str(SETUP), *args],
        cwd=REPO_ROOT,
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def run_validate(
    output_dir: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        ["bash", str(VALIDATE), "--output-dir", str(output_dir), *args],
        cwd=REPO_ROOT,
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def combined(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def load_yaml(path: Path) -> dict:
    value = load_yaml_or_json(path.read_text(encoding="utf-8"), source=str(path))
    assert isinstance(value, dict)
    return value


def write_yaml(path: Path, value: dict) -> None:
    path.write_text(dump_yaml(value, sort_keys=False), encoding="utf-8")


def base_spec(*, outputs: dict[str, bool] | None = None) -> dict:
    return {
        "api_version": "splunk-observability-database-monitoring-setup/v1",
        "realm": "us1",
        "cluster_name": "production-cluster",
        "distribution": "kubernetes",
        "scrape_owner": "kubernetes",
        "collector": {
            "version": "v0.158.0",
            "chart_version": "0.158.0",
            "namespace": "splunk-otel",
            "release_name": "splunk-otel-collector",
            "kube_context": "production-cluster-admin",
            "memory_mib": 4096,
            "cpu_limit": "2",
        },
        "outputs": outputs or {"kubernetes": True, "linux": True, "windows": True},
        "sizing_evidence": {
            "reference": "CHANGE-1234-load-test-report",
            "reviewed_by": "db-platform-owner",
            "reviewed_at": "2026-07-07",
            "peak_memory_mib": 3072,
            "peak_cpu_cores": 1.5,
            "target_count": 5,
        },
        "targets": [
            {
                "name": "orders_postgres",
                "type": "postgresql",
                "platform": "aws-rds",
                "version": "17.5",
                "endpoint": "orders-postgres.example.internal:5432",
                "databases": ["orders"],
                "credentials": credentials("orders-postgres", "DBMON_ORDERS_POSTGRES"),
                "advanced": {"tls": {"insecure": False, "insecure_skip_verify": False}},
            },
            {
                "name": "billing_sqlserver",
                "type": "sqlserver",
                "platform": "self-hosted",
                "version": "2022",
                "connection_mode": "datasource",
                "validation_filters": {
                    "service.instance.id": "billing-sql.example.internal:1433"
                },
                "credentials": credentials(
                    "billing-sqlserver", "DBMON_BILLING_SQLSERVER"
                ),
            },
            {
                "name": "erp_oracle",
                "type": "oracledb",
                "platform": "self-hosted",
                "version": "19c",
                "connection_mode": "datasource",
                "validation_filters": {
                    "service.instance.id": "erp-oracle.example.internal:1521/ERPPROD"
                },
                "credentials": credentials("erp-oracle", "DBMON_ERP_ORACLE"),
                "events": {"session_wait_sample": True},
            },
            {
                "name": "catalog_mysql",
                "type": "mysql",
                "platform": "aws-rds",
                "version": "8.4",
                "endpoint": "catalog-mysql.example.internal:3306",
                "credentials": credentials("catalog-mysql", "DBMON_CATALOG_MYSQL"),
                "advanced": {"tls": {"insecure": False, "insecure_skip_verify": False}},
            },
        ],
    }


def credentials(secret_name: str, prefix: str) -> dict:
    return {
        "kubernetes_secret": {
            "name": f"dbmon-{secret_name}",
            "namespace": "splunk-otel",
            "username_key": "username",
            "password_key": "password",
        },
        "linux_env": {
            "username_var": f"{prefix}_USERNAME",
            "password_var": f"{prefix}_PASSWORD",
        },
    }


def write_spec(path: Path, spec: dict | None = None) -> Path:
    path.write_text(json.dumps(spec or base_spec(), indent=2), encoding="utf-8")
    return path


def render(
    tmp_path: Path, spec_data: dict | None = None, *, validate: bool = False
) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", spec_data)
    args = ["--render"]
    if validate:
        args.append("--validate")
    args.extend(["--spec", str(spec), "--output-dir", str(output)])
    result = run_setup(*args)
    assert result.returncode == 0, combined(result)
    return output


def test_template_and_render_cover_release_engines_runtimes_and_actions(
    tmp_path: Path,
) -> None:
    result = run_setup(
        "--render",
        "--validate",
        "--spec",
        str(TEMPLATE),
        "--output-dir",
        str(tmp_path / "out"),
    )
    assert result.returncode == 0, combined(result)
    output = tmp_path / "out"
    expected = {
        "k8s/values.dbmon.clusterreceiver.yaml",
        "k8s/secrets.dbmon.stub.yaml",
        "linux/collector-dbmon.yaml",
        "linux/dbmon.env.template",
        "windows/collector-dbmon.yaml",
        "windows/dbmon.env.template",
        "scripts/apply-dbmon-overlay.sh",
        "scripts/rollback-dbmon-k8s.sh",
        "scripts/apply-dbmon-linux.sh",
        "scripts/rollback-dbmon-linux.sh",
        "scripts/apply-dbmon-windows.ps1",
        "scripts/rollback-dbmon-windows.ps1",
        "metadata.json",
    }
    files = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    }
    assert expected <= files

    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["collector_version"] == "v0.158.0"
    assert metadata["chart_version"] == "0.158.0"
    assert {item["type"] for item in metadata["targets"]} == {
        "postgresql",
        "sqlserver",
        "oracledb",
        "mysql",
        "mariadb",
    }
    assert set(metadata["validation_metrics"]) == {
        "postgresql.database.count",
        "sqlserver.lock.wait.rate",
        "oracledb.executions",
        "mysql.buffer_pool.usage",
    }
    assert len(metadata["validation_probes"]) == 5
    assert {item["target"] for item in metadata["validation_probes"]} == {
        item["name"] for item in metadata["targets"]
    }
    normalized = dbmon_api_probe.normalize_metadata_probes(metadata, [])
    assert len(normalized) == 5
    assert all(item["filters"] for item in normalized)
    assert metadata["collector_kube_context"] == "production-cluster-admin"


def test_k8s_overlay_is_additive_and_uses_engine_specific_pipelines(
    tmp_path: Path,
) -> None:
    output = render(tmp_path)
    overlay = load_yaml(output / "k8s/values.dbmon.clusterreceiver.yaml")
    assert "clusterName" not in overlay
    assert "distribution" not in overlay
    assert "splunkObservability" not in overlay
    assert "agent" not in overlay
    assert overlay["image"]["otelcol"]["repository"] == (
        "quay.io/signalfx/splunk-otel-collector"
    )
    assert overlay["image"]["otelcol"]["tag"] == (
        "0.158.0@sha256:27a458cd6873d6fef7d3d88fe0a266dffe83d5fe222df738f1937593d8c43357"
    )
    cluster = overlay["clusterReceiver"]
    assert cluster["enabled"] is True
    assert "replicas" not in cluster
    assert cluster["resources"]["limits"]["memory"] == "4096Mi"
    assert cluster["resources"]["requests"]["memory"] == "4096Mi"
    config = cluster["config"]
    assert "otlp_http/dbmon" in config["exporters"]
    assert "otlphttp/dbmon" not in config["exporters"]
    assert "metrics" not in config["service"]["pipelines"]
    pipelines = config["service"]["pipelines"]
    assert set(pipelines) == {
        "metrics/dbmon_core",
        "logs/dbmon_core",
        "metrics/dbmon_mysql",
        "logs/dbmon_mysql",
    }
    assert pipelines["metrics/dbmon_core"]["processors"] == [
        "memory_limiter/dbmon",
        "batch/dbmon",
    ]
    assert pipelines["metrics/dbmon_mysql"]["processors"] == [
        "memory_limiter/dbmon",
        "batch/dbmon",
        "resource_detection/dbmon",
        "resource/mysql_service_instance_id",
    ]
    assert pipelines["logs/dbmon_mysql"]["processors"] == [
        "memory_limiter/dbmon",
        "batch/dbmon",
        "resource/mysql_service_instance_id",
    ]
    assert set(config["receivers"]) == {
        "postgresql/orders_postgres",
        "sqlserver/billing_sqlserver",
        "oracledb/erp_oracle",
        "mysql/catalog_mysql",
    }


def test_standalone_configs_use_env_references_and_never_embed_secrets(
    tmp_path: Path,
) -> None:
    output = render(tmp_path)
    for relative in ("linux/collector-dbmon.yaml", "windows/collector-dbmon.yaml"):
        config = load_yaml(output / relative)
        sqlserver = config["receivers"]["sqlserver/billing_sqlserver"]
        assert sqlserver["datasource"] == "${env:DBMON_BILLING_SQLSERVER_DATASOURCE}"
        assert config["exporters"]["otlp_http/dbmon"]["headers"][
            "X-SF-Token"
        ].startswith("${env:")
    all_text = "\n".join(
        path.read_text(encoding="utf-8") for path in output.rglob("*") if path.is_file()
    )
    assert "INLINE_SHOULD_NOT_LEAK" not in all_text
    assert "PLACEHOLDER_PASSWORD" in all_text


def test_sqlserver_prerequisite_and_secure_datasource_trust_path_are_actionable(
    tmp_path: Path,
) -> None:
    output = render(tmp_path)
    runbook = (output / "prerequisites/billing_sqlserver.md").read_text(
        encoding="utf-8"
    )
    helper = (output / "scripts/apply-dbmon-overlay.sh").read_text(
        encoding="utf-8"
    )
    assert "GRANT VIEW ANY DATABASE TO [otel-user];" in runbook
    assert "CREATE LOGIN [otel-user]" in runbook
    assert 'raw_options.get("certificate", "")' in helper
    assert 'raw_options.get("wallet", "")' in helper
    assert "datasource-trust-paths" in helper
    assert "invalid datasource trust-path preflight record" in helper
    assert "not covered by a cluster-receiver volumeMount" in helper


def test_sql_server_connection_option_injection_is_rejected(tmp_path: Path) -> None:
    spec = base_spec()
    sql = next(item for item in spec["targets"] if item["type"] == "sqlserver")
    sql["connection_mode"] = "direct"
    sql["transport_exception"] = {
        "reason": "Externally protected private test path",
        "reference": "CHANGE-1234",
        "reviewed_by": "db-platform-owner",
        "reviewed_at": "2026-07-07",
    }
    sql["server"] = "db.example;encrypt=disable;password=INLINE_SHOULD_NOT_LEAK"
    result = run_setup(
        "--render", "--spec", str(write_spec(tmp_path / "spec.json", spec))
    )
    assert result.returncode == 1
    assert "hostname or IP address only" in combined(result)
    assert "INLINE_SHOULD_NOT_LEAK" not in combined(result)


def test_target_probe_identity_matches_upstream_formats(tmp_path: Path) -> None:
    spec = base_spec()
    mysql = next(item for item in spec["targets"] if item["type"] == "mysql")
    mysql["endpoint"] = "[2001:db8::10]:3306"
    output = render(tmp_path, spec)
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    filters = {
        probe["target"]: {entry["key"]: entry["value"] for entry in probe["filters"]}
        for probe in metadata["validation_probes"]
    }
    assert filters["orders_postgres"]["service.instance.id"] == (
        "orders-postgres.example.internal:5432"
    )
    assert filters["billing_sqlserver"]["service.instance.id"] == (
        "billing-sql.example.internal:1433"
    )
    assert filters["erp_oracle"]["service.instance.id"] == (
        "erp-oracle.example.internal:1521/ERPPROD"
    )
    assert filters["catalog_mysql"]["service.instance.id"] == "[2001:db8::10]:3306"


def test_loopback_identity_requires_explicit_target_filter(tmp_path: Path) -> None:
    spec = base_spec()
    postgres = next(item for item in spec["targets"] if item["type"] == "postgresql")
    postgres["endpoint"] = "localhost:5432"
    result = run_setup(
        "--render", "--spec", str(write_spec(tmp_path / "spec.json", spec))
    )
    assert result.returncode == 1
    assert "collector hostname" in combined(result)
    postgres["validation_filters"] = {"service.instance.id": "collector-01:5432"}
    output = render(tmp_path / "explicit", spec)
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    probe = next(
        item
        for item in metadata["validation_probes"]
        if item["target"] == "orders_postgres"
    )
    assert probe["filters"] == [
        {"key": "service.instance.id", "value": "collector-01:5432"}
    ]


def test_sqlserver_250_top_queries_is_valid_but_oracle_201_is_not(
    tmp_path: Path,
) -> None:
    spec = base_spec()
    sql = next(item for item in spec["targets"] if item["type"] == "sqlserver")
    sql["advanced"] = {
        "top_query_collection": {
            "max_query_sample_count": 1000,
            "top_query_count": 250,
        }
    }
    render(tmp_path / "sql", spec)
    oracle = next(item for item in spec["targets"] if item["type"] == "oracledb")
    oracle["advanced"] = {
        "top_query_collection": {
            "max_query_sample_count": 1000,
            "top_query_count": 201,
        }
    }
    result = run_setup(
        "--render",
        "--spec",
        str(write_spec(tmp_path / "oracle.json", spec)),
    )
    assert result.returncode == 1
    assert "1..200" in combined(result)


def test_platform_specific_prerequisites_are_actionable(tmp_path: Path) -> None:
    spec = base_spec()
    oracle = next(item for item in spec["targets"] if item["type"] == "oracledb")
    oracle["platform"] = "aws-rds"
    spec["targets"].append(
        {
            "name": "identity_mariadb",
            "type": "mariadb",
            "platform": "standalone",
            "version": "10.5.5",
            "endpoint": "identity-mariadb.example.internal:3306",
            "credentials": credentials(
                "identity-mariadb", "DBMON_IDENTITY_MARIADB"
            ),
            "advanced": {"tls": {"insecure": False, "insecure_skip_verify": False}},
        }
    )
    output = render(tmp_path, spec)
    oracle_runbook = (output / "prerequisites/erp_oracle.md").read_text(
        encoding="utf-8"
    )
    maria_runbook = (output / "prerequisites/identity_mariadb.md").read_text(
        encoding="utf-8"
    )
    assert "rdsadmin.rdsadmin_util.grant_sys_object" in oracle_runbook
    assert "p_obj_name => 'V_$SESSION_EVENT'" in oracle_runbook
    assert "GRANT BINLOG MONITOR" in maria_runbook
    assert "GRANT PROCESS ON *.*" in maria_runbook
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    maria = next(item for item in metadata["targets"] if item["type"] == "mariadb")
    assert maria["support_status"] == "official"


def test_generated_actions_bind_context_detect_duplicates_and_track_drift(
    tmp_path: Path,
) -> None:
    output = render(tmp_path)
    k8s = (output / "scripts/apply-dbmon-overlay.sh").read_text(encoding="utf-8")
    rollback = (output / "scripts/rollback-dbmon-k8s.sh").read_text(encoding="utf-8")
    linux = (output / "scripts/apply-dbmon-linux.sh").read_text(encoding="utf-8")
    linux_rollback = (output / "scripts/rollback-dbmon-linux.sh").read_text(
        encoding="utf-8"
    )
    assert '--kube-context "${KUBE_CONTEXT}"' in k8s
    assert '--context "${KUBE_CONTEXT}"' in k8s
    assert "text in types" in k8s
    assert "applied_revision" in k8s and "Helm revision drift" in rollback
    assert "applied_description" in k8s and "APPLIED_DESCRIPTION" in rollback
    assert "read_release_identity" in k8s and "read_release_identity" in rollback
    assert 'RECOVERY_SIGNAL_STATUS=143' in k8s
    assert 'RECOVERY_SIGNAL_STATUS=143' in rollback
    assert 'restore_previous_state "${restored_revision}" "${restored_description}"' in k8s
    assert "--network=none" in k8s
    for transport_failure in (
        "connection reset",
        "broken pipe",
        "bad connection",
        "unexpected EOF",
        "server closed the connection",
    ):
        assert transport_failure in k8s
        assert transport_failure in linux
    assert "quiesce_cluster_receiver_for_rollback" in k8s
    assert "quiesce_cluster_receiver_for_rollback" in rollback
    assert '--replicas=0' in k8s and '--for=delete pod' in k8s
    assert '--replicas=0' in rollback and '--for=delete pod' in rollback
    assert "info.st_uid != os.geteuid()" in k8s
    assert "info.st_uid != 0" not in k8s
    assert "TRANSACTION_ACTIVE=true" in linux
    assert "effective systemd ExecStart" in linux
    assert '"phase": "preparing"' in linux
    assert 'state["phase"] = "applying"' in linux
    assert "applied_hashes" in linux
    assert "applied-hash or backup-manifest inventory" in linux_rollback
    assert 'state["phase"] = "finalizing"' in linux_rollback
    assert "finish_without_restore finalizing" in linux_rollback
    assert "cgroup_path.relative_to(mount_root)" in linux
    assert "cpu.cfs_quota_us" in linux and "cpuset.cpus.effective" in linux


@pytest.mark.parametrize(
    ("helm_version", "incompatible", "deprecated_alias"),
    [
        ("v4.2.2", True, False),
        ("v4.2.2", False, True),
        ("v3.17.4", False, False),
        ("v4.2.2", False, False),
    ],
)
def test_k8s_upgrade_component_gate_and_helm_version_paths(
    tmp_path: Path,
    helm_version: str,
    incompatible: bool,
    deprecated_alias: bool,
) -> None:
    spec = base_spec(outputs={"kubernetes": True, "linux": False, "windows": False})
    spec["targets"] = [spec["targets"][0]]
    spec["sizing_evidence"]["target_count"] = 1
    output = render(
        tmp_path / "render",
        spec,
    )
    helper = output / "scripts/apply-dbmon-overlay.sh"
    helper_text = helper.read_text(encoding="utf-8")
    assert "build_target_component_inventory" in helper_text
    assert "existing-role-configs.jsonl" in helper_text
    assert "merged-role-configs.jsonl" in helper_text
    assert "target-role-validation" not in helper_text
    assert '.spec.strategy = {"type": "Recreate", "rollingUpdate": null}' in helper_text
    assert 'strategy.get("rollingUpdate") is not None' in helper_text
    assert 'sys.exit("expected exactly one DBMon Deployment")' in helper_text
    assert 'raise SystemExit("expected exactly one DBMon Deployment") if' not in helper_text
    assert "@sha256:27a458cd6873d6fef7d3d88fe0a266dffe83d5fe222df738f1937593d8c43357" in helper_text
    for role in ("otel-agent", "otel-gateway", "otel-k8s-cluster-receiver"):
        assert role in helper_text

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    helm_args = tmp_path / "helm.args"
    kubectl_args = tmp_path / "kubectl.args"
    docker_args = tmp_path / "docker.args"
    secret_marker = "INLINE_GATEWAY_SECRET_SHOULD_NOT_PRINT"

    helm = bin_dir / "helm"
    helm.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
printf 'plugins=%s args=%s\\n' "${{HELM_PLUGINS:-}}" "$*" >> "${{FAKE_HELM_ARGS}}"
case "$*" in
  "version --template {{{{.Version}}}}") printf '%s\\n' "${{FAKE_HELM_VERSION}}" ;;
  *" status "*) printf '%s\\n' '{{"info":{{"status":"deployed"}}}}' ;;
  "repo list -o json") printf '%s\\n' '[{{"name":"splunk-otel-collector-chart","url":"https://signalfx.github.io/splunk-otel-collector-chart"}}]' ;;
  "pull "*)
    destination=""
    while (( $# )); do
      if [[ "$1" == "--destination" ]]; then destination="$2"; break; fi
      shift
    done
    : > "${{destination}}/splunk-otel-collector-0.158.0.tgz"
    ;;
  "show chart "*) printf '%s\\n' 'appVersion: 0.158.0' ;;
  *" list "*) printf '%s\\n' '[{{"chart":"splunk-otel-collector-0.148.0"}}]' ;;
  *" get values "*)
    if [[ "${{FAKE_INCOMPATIBLE}}" == "true" ]]; then receiver_type=signalfx; else receiver_type=otlp; fi
    if [[ "${{FAKE_DEPRECATED_ALIAS}}" == "true" ]]; then
      agent_config=$'  config:\n    receivers:\n      filelog/private: {{}}\n    service:\n      pipelines:\n        logs/private:\n          receivers: [filelog/private]'
    else
      agent_config='  config: {{}}'
    fi
    cat <<YAML
splunkObservability:
  realm: us1
clusterName: production-cluster
distribution: ""
agent:
${{agent_config}}
gateway:
  config:
    receivers:
      ${{receiver_type}}:
        access_token: {secret_marker}
clusterReceiver:
  config: {{}}
YAML
    ;;
  *" get manifest "*)
    if [[ "${{FAKE_INCOMPATIBLE}}" == "true" ]]; then receiver_type=signalfx; else receiver_type=otlp; fi
    cat <<YAML
apiVersion: v1
kind: ConfigMap
metadata:
  name: splunk-otel-collector-otel-collector
data:
  relay: |
    receivers:
      ${{receiver_type}}:
        access_token: {secret_marker}
    service:
      pipelines: {{}}
YAML
    ;;
  *" history "*) printf '%s\\n' '[{{"revision":7,"description":"prior"}}]' ;;
  "template "*)
    if [[ "${{FAKE_INCOMPATIBLE}}" == "true" ]]; then receiver_type=signalfx; else receiver_type=otlp; fi
    cat <<YAML
apiVersion: apps/v1
kind: Deployment
metadata:
  name: splunk-otel-collector-otel-k8s-cluster-receiver
  labels:
    component: otel-k8s-cluster-receiver
spec:
  replicas: 1
  strategy:
    type: Recreate
  template:
    spec:
      containers:
        - name: otel-collector
          image: quay.io/signalfx/splunk-otel-collector:0.158.0@sha256:27a458cd6873d6fef7d3d88fe0a266dffe83d5fe222df738f1937593d8c43357
          env:
            - name: SPLUNK_OBSERVABILITY_ACCESS_TOKEN
              valueFrom:
                secretKeyRef:
                  name: splunk-observability-token
                  key: access-token
          resources:
            limits:
              cpu: "2"
              memory: 4096Mi
            requests:
              cpu: "2"
              memory: 4096Mi
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: splunk-otel-collector-otel-agent
data:
  relay: |
    receivers:
      hostmetrics:
        root_path: /hostfs
    exporters:
      signalfx: {{}}
    service:
      pipelines:
        metrics:
          receivers: [hostmetrics]
          exporters: [signalfx]
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: splunk-otel-collector-otel-collector
data:
  relay: |
    receivers:
      ${{receiver_type}}:
        access_token: {secret_marker}
    service:
      pipelines: {{}}
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: splunk-otel-collector-otel-k8s-cluster-receiver
data:
  relay: |
    receivers:
      postgresql/dbmon:
        username: "\\${{env:DBMON_ORDERS_POSTGRES_USERNAME}}"
    exporters:
      signalfx/dbmon: {{}}
    service:
      pipelines:
        metrics/dbmon:
          receivers: [postgresql/dbmon]
          exporters: [signalfx/dbmon]
YAML
    ;;
  *" upgrade "*) exit 0 ;;
  *) exit 97 ;;
esac
""",
        encoding="utf-8",
    )
    helm.chmod(0o755)

    kubectl = bin_dir / "kubectl"
    kubectl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${FAKE_KUBECTL_ARGS}"
if [[ "$*" == "config current-context" ]]; then
  printf '%s\n' production-cluster-admin
elif [[ "$*" == *"get deployment,daemonset,statefulset"* ]]; then
  printf '%s\n' '{"items":[{"spec":{"template":{"spec":{"containers":[{"name":"otel-collector","image":"quay.io/signalfx/splunk-otel-collector:0.148.0"}]}}}}]}'
elif [[ "$*" == *"get secret"* ]]; then
  printf '%s\n' '{"data":{"username":"bW9uaXRvcg==","password":"c2VjcmV0","access-token":"dG9rZW4="}}'
elif [[ "$*" == *"get configmap kube-root-ca.crt"* ]]; then
  printf '%s\n' '{"data":{"ca.crt":"-----BEGIN CERTIFICATE-----\\nvalidation\\n-----END CERTIFICATE-----\\n"}}'
else
  exit 96
fi
""",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)

    docker = bin_dir / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${FAKE_DOCKER_ARGS}"
if [[ "$*" != *"dbmon-component-inventory.yaml"* ]]; then exit 0; fi
cat >&2 <<'EOF'
'receivers' unknown type: "dbmoninventoryunavailable" for id: "dbmoninventoryunavailable" (valid values: [hostmetrics mysql oracledb otlp postgresql sqlserver])
'processors' unknown type: "dbmoninventoryunavailable" for id: "dbmoninventoryunavailable" (valid values: [batch memory_limiter resource resourcedetection resource_detection])
'exporters' unknown type: "dbmoninventoryunavailable" for id: "dbmoninventoryunavailable" (valid values: [otlp_http signalfx])
'connectors' unknown type: "dbmoninventoryunavailable" for id: "dbmoninventoryunavailable" (valid values: [forward])
'extensions' unknown type: "dbmoninventoryunavailable" for id: "dbmoninventoryunavailable" (valid values: [health_check])
EOF
exit 1
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    python = bin_dir / "python3"
    python.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-c" && "${2:-}" == *"hashlib.sha256"* && "${*: -1}" == *.tgz ]]; then
  printf '%s\n' 088a93ebbcfbecf8e6f7ef3651747b65bbad443f0823489768bd4901cce0a274
  exit 0
fi
exec "${REAL_PYTHON}" "$@"
""",
        encoding="utf-8",
    )
    python.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "REAL_PYTHON": sys.executable,
            "FAKE_HELM_ARGS": str(helm_args),
            "FAKE_KUBECTL_ARGS": str(kubectl_args),
            "FAKE_DOCKER_ARGS": str(docker_args),
            "FAKE_HELM_VERSION": helm_version,
            "FAKE_INCOMPATIBLE": str(incompatible).lower(),
            "FAKE_DEPRECATED_ALIAS": str(deprecated_alias).lower(),
            "K8S_APPLY_DRY_RUN": "true",
            "ACCEPT_COLLECTOR_UPGRADE": "true",
            "HOME": str(tmp_path / "home"),
        }
    )
    result = subprocess.run(
        ["bash", str(helper)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    output_text = combined(result)
    assert secret_marker not in output_text
    assert "signalfx" not in output_text
    helm_calls = helm_args.read_text(encoding="utf-8").splitlines()
    kubectl_calls = kubectl_args.read_text(encoding="utf-8")
    if deprecated_alias:
        assert result.returncode == 1, output_text
        assert "chart 0.158.0 rejects deprecated collector component aliases" in output_text
        assert "receivers filelog->file_log definitions=1 pipeline_refs=1" in output_text
        assert "splunk-observability-otel-collector-setup" in output_text
        assert not any("args=template " in line for line in helm_calls)
        assert not any(" upgrade " in f" {line} " for line in helm_calls)
        assert "get secret" not in kubectl_calls
        return
    if incompatible:
        assert result.returncode == 1, output_text
        assert "target Collector compatibility preflight rejected merged" in output_text
        assert not any(" upgrade " in f" {line} " for line in helm_calls)
        assert "get secret" not in kubectl_calls
        return

    assert result.returncode == 0, output_text
    template_call = next(line for line in helm_calls if "args=template " in line)
    upgrade_call = next(line for line in helm_calls if " upgrade " in f" {line} ")
    assert "--hide-secret" in upgrade_call
    if helm_version.startswith("v4"):
        assert "plugins=" in template_call and "plugins= args=" not in template_call
        assert "--post-renderer splunk-dbmon-recreate" in template_call
        assert "--post-renderer splunk-dbmon-recreate" in upgrade_call
        assert "--rollback-on-failure" not in upgrade_call
        assert "--wait=watcher" in upgrade_call
        assert "--server-side=false" in upgrade_call
        assert "--atomic" not in upgrade_call
        assert "--dry-run=server" in upgrade_call
        for call in helm_calls:
            if call not in (template_call, upgrade_call):
                assert call.startswith("plugins= args=")
    else:
        assert template_call.startswith("plugins= args=")
        assert "/dbmon-post-renderer.sh" in template_call
        assert "/dbmon-post-renderer.sh" in upgrade_call
        assert "--wait" in upgrade_call
        assert "--atomic" not in upgrade_call
        assert "--rollback-on-failure" not in upgrade_call
        assert "--server-side=false" not in upgrade_call
        assert "--dry-run --hide-secret" in upgrade_call
        assert "--dry-run=server" not in upgrade_call


@pytest.mark.parametrize(
    "scenario",
    ["commit", "rollback", "rollback-history-failure", "rollback-state-failure"],
)
def test_k8s_non_dry_run_post_upgrade_commit_and_rollback_trap(
    tmp_path: Path, scenario: str
) -> None:
    """Exercise the generated mutation lifecycle without contacting a cluster."""
    rollout_fails = scenario != "commit"
    spec = base_spec(outputs={"kubernetes": True, "linux": False, "windows": False})
    spec["targets"] = [spec["targets"][0]]
    spec["sizing_evidence"]["target_count"] = 1
    output = render(tmp_path / "render", spec)
    helper = output / "scripts/apply-dbmon-overlay.sh"

    bin_dir = tmp_path / "bin"
    fake_state = tmp_path / "fake-state"
    xdg_state = tmp_path / "xdg-state"
    home = tmp_path / "home"
    for directory in (bin_dir, fake_state, home):
        directory.mkdir()
    helm_args = tmp_path / "helm.args"
    kubectl_args = tmp_path / "kubectl.args"
    docker_args = tmp_path / "docker.args"

    helm = bin_dir / "helm"
    helm.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf 'plugins=%s args=%s\n' "${HELM_PLUGINS:-}" "$*" >> "${FAKE_HELM_ARGS}"
case " $* " in
  *" version --template "*)
    printf '%s\n' 'v4.2.2'
    ;;
  *" status "*)
    printf '%s\n' '{"info":{"status":"deployed"}}'
    ;;
  *" repo list "*)
    printf '%s\n' '[{"name":"splunk-otel-collector-chart","url":"https://signalfx.github.io/splunk-otel-collector-chart"}]'
    ;;
  *" pull "*)
    destination=""
    while (( $# )); do
      if [[ "$1" == "--destination" ]]; then
        destination="$2"
        break
      fi
      shift
    done
    : > "${destination}/splunk-otel-collector-0.158.0.tgz"
    ;;
  *" show chart "*)
    printf '%s\n' 'appVersion: 0.158.0'
    ;;
  *" list "*)
    printf '%s\n' '[{"chart":"splunk-otel-collector-0.158.0"}]'
    ;;
  *" get values "*)
    cat <<'YAML'
splunkObservability:
  realm: us1
clusterName: production-cluster
distribution: ""
agent:
  config: {}
gateway:
  config: {}
clusterReceiver:
  config: {}
  extraEnvs: []
YAML
    ;;
  *" get manifest "*)
    cat <<'YAML'
apiVersion: v1
kind: ConfigMap
metadata:
  name: splunk-otel-collector-otel-k8s-cluster-receiver
data:
  relay: |
    receivers: {}
    service:
      pipelines: {}
YAML
    ;;
  *" template "*)
    cat <<'YAML'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: splunk-otel-collector-otel-k8s-cluster-receiver
  labels:
    app: splunk-otel-collector
    component: otel-k8s-cluster-receiver
    release: splunk-otel-collector
spec:
  replicas: 1
  strategy:
    type: Recreate
    rollingUpdate: null
  template:
    spec:
      containers:
        - name: otel-collector
          image: quay.io/signalfx/splunk-otel-collector:0.158.0@sha256:27a458cd6873d6fef7d3d88fe0a266dffe83d5fe222df738f1937593d8c43357
          env:
            - name: SPLUNK_OBSERVABILITY_ACCESS_TOKEN
              valueFrom:
                secretKeyRef:
                  name: splunk-observability-token
                  key: access-token
          resources:
            limits:
              cpu: "2"
              memory: 4096Mi
            requests:
              cpu: "2"
              memory: 4096Mi
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: splunk-otel-collector-otel-k8s-cluster-receiver
data:
  relay: |
    receivers:
      postgresql/orders_postgres:
        endpoint: orders-postgres.example.internal:5432
        username: ${env:DBMON_ORDERS_POSTGRES_USERNAME}
        password: ${env:DBMON_ORDERS_POSTGRES_PASSWORD}
    exporters:
      signalfx/dbmon: {}
    service:
      pipelines:
        metrics/dbmon:
          receivers: [postgresql/orders_postgres]
          exporters: [signalfx/dbmon]
YAML
    ;;
  *" upgrade "*)
    args=("$@")
    description=""
    for ((index = 0; index < ${#args[@]}; index++)); do
      if [[ "${args[index]}" == "--description" ]]; then
        description="${args[index + 1]}"
      fi
    done
    [[ -n "${description}" ]]
    printf '%s\n' "${description}" > "${FAKE_HELM_STATE}/description"
    printf '%s\n' applied > "${FAKE_HELM_STATE}/phase"
    ;;
  *" rollback "*)
    printf '%s\n' "$*" > "${FAKE_HELM_STATE}/rollback"
    printf '%s\n' restored > "${FAKE_HELM_STATE}/phase"
    if [[ "${FAKE_STATE_RESTORE_FAILURE:-false}" == "true" ]]; then
      "${REAL_PYTHON}" - "${FAKE_DBMON_STATE}" <<'PY'
import json
import sys
path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    state = json.load(handle)
state["previous_state"] = "invalid"
with open(path, "w", encoding="utf-8") as handle:
    json.dump(state, handle)
PY
    fi
    ;;
  *" history "*)
    phase=before
    [[ ! -f "${FAKE_HELM_STATE}/phase" ]] || phase="$(<"${FAKE_HELM_STATE}/phase")"
    if [[ "${phase}" == "applied" ]]; then
      description="$(<"${FAKE_HELM_STATE}/description")"
      printf '[{"revision":7,"description":"prior"},{"revision":8,"description":"%s"}]\n' "${description}"
    elif [[ "${phase}" == "restored" ]]; then
      [[ "${FAKE_HISTORY_FAIL_AFTER_ROLLBACK:-false}" != "true" ]] || exit 95
      description="$(<"${FAKE_HELM_STATE}/description")"
      printf '[{"revision":7,"description":"prior"},{"revision":8,"description":"%s"},{"revision":9,"description":"Rollback to 7"}]\n' "${description}"
    else
      printf '%s\n' '[{"revision":7,"description":"prior"}]'
    fi
    ;;
  *)
    printf 'unexpected fake helm invocation: %s\n' "$*" >&2
    exit 97
    ;;
esac
""",
        encoding="utf-8",
    )
    helm.chmod(0o755)

    kubectl = bin_dir / "kubectl"
    kubectl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${FAKE_KUBECTL_ARGS}"
if [[ "$*" == "config current-context" ]]; then
  printf '%s\n' production-cluster-admin
elif [[ "$*" == *"get deployment,daemonset,statefulset"* ]]; then
  printf '%s\n' '{"items":[{"spec":{"template":{"spec":{"containers":[{"name":"otel-collector","image":"quay.io/signalfx/splunk-otel-collector:0.158.0@sha256:27a458cd6873d6fef7d3d88fe0a266dffe83d5fe222df738f1937593d8c43357"}]}}}}]}'
elif [[ "$*" == *"get secret"* ]]; then
  printf '%s\n' '{"data":{"username":"bW9uaXRvcg==","password":"c2VjcmV0","access-token":"dG9rZW4="}}'
elif [[ "$*" == *"get configmap kube-root-ca.crt"* ]]; then
  printf '%s\n' '{"data":{"ca.crt":"-----BEGIN CERTIFICATE-----\\nvalidation\\n-----END CERTIFICATE-----\\n"}}'
elif [[ "$*" == *"get deployment -l"* ]]; then
  printf '%s\n' '{"items":[{"metadata":{"name":"splunk-otel-collector-otel-k8s-cluster-receiver"},"spec":{"replicas":1}}]}'
elif [[ "$*" == *"scale deployment/"* ]]; then
  printf '%s\n' 'deployment.apps/splunk-otel-collector-otel-k8s-cluster-receiver scaled'
elif [[ "$*" == *"wait --for=delete pod -l"* ]]; then
  printf '%s\n' 'pod deleted'
elif [[ "$*" == *"rollout status"* ]]; then
  if [[ -f "${FAKE_HELM_STATE}/phase" && "$(<"${FAKE_HELM_STATE}/phase")" == "restored" ]]; then
    exit 0
  fi
  [[ "${FAKE_ROLLOUT_FAIL}" != "true" ]]
elif [[ "$*" == *"get deployment/"* ]]; then
  cat <<'JSON'
{"spec":{"replicas":1,"strategy":{"type":"Recreate","rollingUpdate":null},"template":{"spec":{"containers":[{"name":"otel-collector","image":"quay.io/signalfx/splunk-otel-collector:0.158.0@sha256:27a458cd6873d6fef7d3d88fe0a266dffe83d5fe222df738f1937593d8c43357","resources":{"limits":{"cpu":"2","memory":"4096Mi"},"requests":{"cpu":"2","memory":"4096Mi"}}}]}}},"status":{"readyReplicas":1}}
JSON
elif [[ "$*" == *"get pod -l"* ]]; then
  cat <<'JSON'
{"items":[{"status":{"containerStatuses":[{"name":"otel-collector","ready":true,"imageID":"docker-pullable://quay.io/signalfx/splunk-otel-collector@sha256:27a458cd6873d6fef7d3d88fe0a266dffe83d5fe222df738f1937593d8c43357"}]}}]}
JSON
elif [[ "$*" == *"logs deployment/"* ]]; then
  printf '%s\n' 'info receiver postgresql/orders_postgres started'
else
  printf 'unexpected fake kubectl invocation: %s\n' "$*" >&2
  exit 96
fi
""",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)

    docker = bin_dir / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${FAKE_DOCKER_ARGS}"
exit 0
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    python = bin_dir / "python3"
    python.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-c" && "${2:-}" == *"hashlib.sha256"* && "${*: -1}" == *.tgz ]]; then
  printf '%s\n' 088a93ebbcfbecf8e6f7ef3651747b65bbad443f0823489768bd4901cce0a274
  exit 0
fi
exec "${REAL_PYTHON}" "$@"
""",
        encoding="utf-8",
    )
    python.chmod(0o755)

    sleep = bin_dir / "sleep"
    sleep.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    sleep.chmod(0o755)

    state_path = (
        xdg_state
        / "splunk-dbmon"
        / "splunk-otel-splunk-otel-collector.json"
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "REAL_PYTHON": sys.executable,
            "FAKE_HELM_ARGS": str(helm_args),
            "FAKE_HELM_STATE": str(fake_state),
            "FAKE_KUBECTL_ARGS": str(kubectl_args),
            "FAKE_DOCKER_ARGS": str(docker_args),
            "FAKE_ROLLOUT_FAIL": str(rollout_fails).lower(),
            "FAKE_HISTORY_FAIL_AFTER_ROLLBACK": str(
                scenario == "rollback-history-failure"
            ).lower(),
            "FAKE_STATE_RESTORE_FAILURE": str(
                scenario == "rollback-state-failure"
            ).lower(),
            "FAKE_DBMON_STATE": str(state_path),
            "ACCEPT_K8S_APPLY": "true",
            "XDG_STATE_HOME": str(xdg_state),
            "HOME": str(home),
        }
    )
    result = subprocess.run(
        ["bash", str(helper)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    output_text = combined(result)
    helm_calls = helm_args.read_text(encoding="utf-8").splitlines()
    upgrade_call = next(line for line in helm_calls if " upgrade " in f" {line} ")
    assert "--post-renderer splunk-dbmon-recreate" in upgrade_call
    assert "--rollback-on-failure" not in upgrade_call
    assert "--wait=watcher" in upgrade_call
    assert "--server-side=false" in upgrade_call
    rollback_path = fake_state / "rollback"

    if rollout_fails:
        assert result.returncode == 1, output_text
        assert "DBMon cluster-receiver rollout did not become ready" in output_text
        assert "rolling back action-owned revision 8" in output_text
        assert rollback_path.exists()
        rollback_call = rollback_path.read_text(encoding="utf-8")
        assert "rollback splunk-otel-collector 7" in rollback_call
        kubectl_calls = kubectl_args.read_text(encoding="utf-8")
        assert "scale deployment/splunk-otel-collector-otel-k8s-cluster-receiver --replicas=0" in kubectl_calls
        assert "wait --for=delete pod -l" in kubectl_calls
        if scenario in {"rollback-history-failure", "rollback-state-failure"}:
            assert state_path.exists()
            pending = json.loads(state_path.read_text(encoding="utf-8"))
            assert pending["phase"] == "applying"
            if scenario == "rollback-history-failure":
                assert "live release identity could not be verified" in output_text
            else:
                assert pending["previous_state"] == "invalid"
                assert "trusted state could not be safely advanced" in output_text
        else:
            assert not state_path.exists()
        return

    assert result.returncode == 0, output_text
    assert "DBMon Kubernetes apply completed at Helm revision 8" in output_text
    assert not rollback_path.exists()
    assert state_path.stat().st_mode & 0o777 == 0o600
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["phase"] == "validated"
    assert state["previous_revision"] == 7
    assert state["applied_revision"] == 8
    assert state["previous_state"] is None
    assert state["transaction_id"].startswith("dbmon-")
    assert state["applied_description"] == state["transaction_id"]
    assert state["running_image"].endswith(
        "@sha256:27a458cd6873d6fef7d3d88fe0a266dffe83d5fe222df738f1937593d8c43357"
    )
    assert state["running_image_id"].endswith(
        "@sha256:27a458cd6873d6fef7d3d88fe0a266dffe83d5fe222df738f1937593d8c43357"
    )
    calls_before = helm_args.read_text(encoding="utf-8").count(" upgrade ")
    (fake_state / "description").write_text(
        "external-unowned-description", encoding="utf-8"
    )
    drifted = subprocess.run(
        ["bash", str(helper)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert drifted.returncode == 1
    assert "Helm release identity drifted" in combined(drifted)
    calls_after = helm_args.read_text(encoding="utf-8").count(" upgrade ")
    assert calls_after == calls_before


def test_explicit_k8s_rollback_rebases_nested_release_identity(
    tmp_path: Path,
) -> None:
    """Two consecutive rollbacks must follow Helm's new live descriptions."""
    spec = base_spec(outputs={"kubernetes": True, "linux": False, "windows": False})
    spec["targets"] = [spec["targets"][0]]
    spec["sizing_evidence"]["target_count"] = 1
    output = render(tmp_path / "render", spec)
    helper = output / "scripts/rollback-dbmon-k8s.sh"

    bin_dir = tmp_path / "bin"
    fake_runtime = tmp_path / "fake-runtime"
    xdg_state = tmp_path / "xdg-state"
    home = tmp_path / "home"
    for directory in (bin_dir, fake_runtime, xdg_state / "splunk-dbmon", home):
        directory.mkdir(parents=True, exist_ok=True)
    phase_file = fake_runtime / "phase"
    helm_args = fake_runtime / "helm.args"
    kubectl_args = fake_runtime / "kubectl.args"

    helm = bin_dir / "helm"
    helm.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${FAKE_HELM_ARGS}"
case " $* " in
  *" history "*)
    phase=before
    [[ ! -f "${FAKE_PHASE_FILE}" ]] || phase="$(<"${FAKE_PHASE_FILE}")"
    case "${phase}" in
      before) printf '%s\n' '[{"revision":9,"description":"dbmon-transaction-b"}]' ;;
      after1) printf '%s\n' '[{"revision":9,"description":"dbmon-transaction-b"},{"revision":10,"description":"Rollback to 8"}]' ;;
      after2) printf '%s\n' '[{"revision":10,"description":"Rollback to 8"},{"revision":11,"description":"Rollback to 7"}]' ;;
      *) exit 91 ;;
    esac
    ;;
  *" status "*) printf '%s\n' '{"info":{"status":"deployed"}}' ;;
  *" rollback "*)
    phase=before
    [[ ! -f "${FAKE_PHASE_FILE}" ]] || phase="$(<"${FAKE_PHASE_FILE}")"
    if [[ "${phase}" == "before" && " $* " == *" rollback splunk-otel-collector 8 "* ]]; then
      printf '%s\n' after1 > "${FAKE_PHASE_FILE}"
    elif [[ "${phase}" == "after1" && " $* " == *" rollback splunk-otel-collector 7 "* ]]; then
      printf '%s\n' after2 > "${FAKE_PHASE_FILE}"
    else
      exit 92
    fi
    ;;
  *) printf 'unexpected fake helm invocation: %s\n' "$*" >&2; exit 93 ;;
esac
""",
        encoding="utf-8",
    )
    helm.chmod(0o755)

    kubectl = bin_dir / "kubectl"
    kubectl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${FAKE_KUBECTL_ARGS}"
if [[ "$*" == "config current-context" ]]; then
  printf '%s\n' production-cluster-admin
elif [[ "$*" == *"get deployment -l"* ]]; then
  printf '%s\n' '{"items":[{"metadata":{"name":"dbmon-cluster-receiver"},"spec":{"replicas":1}}]}'
elif [[ "$*" == *"get pod -l"* ]]; then
  printf '%s\n' '{"items":[]}'
elif [[ "$*" == *"scale deployment/dbmon-cluster-receiver"* ]]; then
  printf '%s\n' scaled
elif [[ "$*" == *"rollout status"* ]]; then
  printf '%s\n' ready
else
  printf 'unexpected fake kubectl invocation: %s\n' "$*" >&2
  exit 94
fi
""",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)

    state_path = (
        xdg_state
        / "splunk-dbmon"
        / "splunk-otel-splunk-otel-collector.json"
    )
    state_a = {
        "phase": "validated",
        "release": "splunk-otel-collector",
        "namespace": "splunk-otel",
        "kube_context": "production-cluster-admin",
        "previous_revision": 7,
        "applied_revision": 8,
        "transaction_id": "dbmon-transaction-a",
        "previous_state": None,
    }
    state_b = {
        "phase": "validated",
        "release": "splunk-otel-collector",
        "namespace": "splunk-otel",
        "kube_context": "production-cluster-admin",
        "previous_revision": 8,
        "applied_revision": 9,
        "transaction_id": "dbmon-transaction-b",
        "previous_state": state_a,
    }
    state_path.write_text(json.dumps(state_b), encoding="utf-8")
    state_path.chmod(0o600)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "FAKE_PHASE_FILE": str(phase_file),
            "FAKE_HELM_ARGS": str(helm_args),
            "FAKE_KUBECTL_ARGS": str(kubectl_args),
            "ACCEPT_K8S_ROLLBACK": "true",
            "XDG_STATE_HOME": str(xdg_state),
            "HOME": str(home),
        }
    )

    first = subprocess.run(
        ["bash", str(helper)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert first.returncode == 0, combined(first)
    rebased = json.loads(state_path.read_text(encoding="utf-8"))
    assert rebased["transaction_id"] == "dbmon-transaction-a"
    assert rebased["applied_revision"] == 10
    assert rebased["applied_description"] == "Rollback to 8"

    second = subprocess.run(
        ["bash", str(helper)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert second.returncode == 0, combined(second)
    assert not state_path.exists()
    calls = helm_args.read_text(encoding="utf-8")
    assert "rollback splunk-otel-collector 8" in calls
    assert "rollback splunk-otel-collector 7" in calls


def test_explicit_k8s_rollback_signal_restores_quiesced_replica(
    tmp_path: Path,
) -> None:
    spec = base_spec(outputs={"kubernetes": True, "linux": False, "windows": False})
    spec["targets"] = [spec["targets"][0]]
    spec["sizing_evidence"]["target_count"] = 1
    output = render(tmp_path / "render", spec)
    helper = output / "scripts/rollback-dbmon-k8s.sh"

    bin_dir = tmp_path / "bin"
    xdg_state = tmp_path / "xdg-state"
    home = tmp_path / "home"
    for directory in (bin_dir, xdg_state / "splunk-dbmon", home):
        directory.mkdir(parents=True, exist_ok=True)
    marker = tmp_path / "rollback-started"
    release = tmp_path / "release-rollback"
    kubectl_args = tmp_path / "kubectl.args"

    helm = bin_dir / "helm"
    helm.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case " $* " in
  *" history "*) printf '%s\n' '[{"revision":8,"description":"dbmon-signal-test"}]' ;;
  *" rollback "*)
    : > "${ROLLBACK_MARKER}"
    while [[ ! -f "${ROLLBACK_RELEASE}" ]]; do sleep 0.02; done
    ;;
  *) exit 95 ;;
esac
""",
        encoding="utf-8",
    )
    helm.chmod(0o755)

    kubectl = bin_dir / "kubectl"
    kubectl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${FAKE_KUBECTL_ARGS}"
if [[ "$*" == "config current-context" ]]; then
  printf '%s\n' production-cluster-admin
elif [[ "$*" == *"get deployment -l"* ]]; then
  printf '%s\n' '{"items":[{"metadata":{"name":"dbmon-cluster-receiver"},"spec":{"replicas":1}}]}'
elif [[ "$*" == *"get pod -l"* ]]; then
  printf '%s\n' '{"items":[]}'
elif [[ "$*" == *"scale deployment/dbmon-cluster-receiver"* ]]; then
  printf '%s\n' scaled
else
  exit 96
fi
""",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)

    state_path = (
        xdg_state
        / "splunk-dbmon"
        / "splunk-otel-splunk-otel-collector.json"
    )
    state_path.write_text(
        json.dumps(
            {
                "phase": "validated",
                "release": "splunk-otel-collector",
                "namespace": "splunk-otel",
                "kube_context": "production-cluster-admin",
                "previous_revision": 7,
                "applied_revision": 8,
                "transaction_id": "dbmon-signal-test",
                "applied_description": "dbmon-signal-test",
                "previous_state": None,
            }
        ),
        encoding="utf-8",
    )
    state_path.chmod(0o600)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "ROLLBACK_MARKER": str(marker),
            "ROLLBACK_RELEASE": str(release),
            "FAKE_KUBECTL_ARGS": str(kubectl_args),
            "ACCEPT_K8S_ROLLBACK": "true",
            "XDG_STATE_HOME": str(xdg_state),
            "HOME": str(home),
        }
    )
    process = subprocess.Popen(
        ["bash", str(helper)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 5
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert marker.exists(), "fake Helm rollback did not enter its quiesced window"
    process.terminate()
    release.touch()
    stdout, stderr = process.communicate(timeout=5)

    assert process.returncode == 143, stdout + stderr
    calls = kubectl_args.read_text(encoding="utf-8")
    assert calls.count(
        "scale deployment/dbmon-cluster-receiver --replicas=0"
    ) == 1
    assert calls.count(
        "scale deployment/dbmon-cluster-receiver --replicas=1"
    ) == 1
    assert state_path.exists()


def test_every_generated_python_heredoc_compiles(tmp_path: Path) -> None:
    output = render(tmp_path)
    scripts = sorted((output / "scripts").glob("*.sh"))
    found = 0
    for script in scripts:
        text = script.read_text(encoding="utf-8")
        for index, block in enumerate(
            re.findall(r"<<'PY'\n(.*?)\nPY(?:\n|$)", text, flags=re.DOTALL), 1
        ):
            compile(block, f"{script.name}:heredoc-{index}", "exec")
            found += 1
    assert found >= 10


@pytest.mark.parametrize(
    ("engine", "value"),
    [
        (
            "sqlserver",
            "sqlserver://monitor:secret@sql.example:1433?encrypt=true&trustservercertificate=false",
        ),
        (
            "oracledb",
            "oracle://monitor:secret@oracle.example:1521/PROD?SSL=enable&SSL%20Verify=true",
        ),
    ],
)
def test_generated_secure_env_runs_and_validates_datasources(
    tmp_path: Path, engine: str, value: str
) -> None:
    output = render(tmp_path / engine)
    env_file = tmp_path / f"{engine}.env"
    env_file.write_text(
        f"SPLUNK_MEMORY_LIMIT_MIB=4096\nDBMON_DATASOURCE={value}\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    command = [
        sys.executable,
        str(output / "scripts/secure-env.py"),
        "--strict-file",
        str(env_file),
        "--allowed",
        "SPLUNK_MEMORY_LIMIT_MIB",
        "--allowed",
        "DBMON_DATASOURCE",
        "--required",
        "DBMON_DATASOURCE",
        "--minimum-memory-mib",
        "4096",
        "--secure-datasource",
        f"DBMON_DATASOURCE={engine}",
    ]
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, combined(result)

    if engine == "sqlserver":
        env_file.write_text(
            "SPLUNK_MEMORY_LIMIT_MIB=4096\n"
            "DBMON_DATASOURCE=sqlserver://monitor:secret@sql.example:1433?"
            "encrypt=true&trustservercertificate=true\n",
            encoding="utf-8",
        )
        invalid = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert invalid.returncode == 1
        assert "DBMON_DATASOURCE must disable TrustServerCertificate" in combined(
            invalid
        )


def test_generated_base_config_audit_runs_and_rejects_dbmon_collisions(
    tmp_path: Path,
) -> None:
    output = render(tmp_path)
    helper = output / "scripts/audit-base-config.py"
    clean = subprocess.run(
        [sys.executable, str(helper)],
        input=json.dumps({"receivers": {"hostmetrics": {}}, "service": {}}),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert clean.returncode == 0, combined(clean)
    collision = subprocess.run(
        [sys.executable, str(helper)],
        input=json.dumps({"receivers": {"mysql/existing": {}}}),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert collision.returncode == 1
    assert "already contains a DB receiver" in combined(collision)


def _linux_sizing_program(output: Path, fixture_root: Path) -> str:
    text = (output / "scripts/apply-dbmon-linux.sh").read_text(encoding="utf-8")
    marker = 'SERVICE_MAIN_PID="$(systemctl show'
    command_start = text.index("python3 - ", text.index(marker))
    body_start = text.index("<<'PY'\n", command_start) + len("<<'PY'\n")
    body_end = text.index("\nPY\nactual_version=", body_start)
    program = text[body_start:body_end]
    replacements = {
        'pathlib.Path(f"/proc/{service_pid}/cgroup")': repr(
            str(fixture_root / "proc-cgroup")
        ),
        'pathlib.Path("/proc/self/mountinfo")': repr(
            str(fixture_root / "mountinfo")
        ),
        'pathlib.Path("/proc/meminfo")': repr(str(fixture_root / "meminfo")),
        "float(os.cpu_count() or 0)": "8.0",
    }
    for original, replacement in replacements.items():
        program = program.replace(original, f"pathlib.Path({replacement})" if original.startswith("pathlib.Path") else replacement)
    return program


def _run_sizing_program(
    program: str, *, memory_mib: int = 4096, cpu: str = "2"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-", str(memory_mib), cpu, "999"],
        input=program,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_linux_sizing_audits_non_root_cgroup_mount_ancestors(tmp_path: Path) -> None:
    output = render(tmp_path / "render")
    fixture = tmp_path / "cgroup-fixture"
    mount = fixture / "cgroup2"
    leaf = mount / "app.slice/service.scope"
    ancestor = mount / "app.slice"
    leaf.mkdir(parents=True)
    fixture.mkdir(exist_ok=True)
    (fixture / "proc-cgroup").write_text(
        "0::/tenant.slice/app.slice/service.scope\n", encoding="utf-8"
    )
    (fixture / "mountinfo").write_text(
        f"36 29 0:32 /tenant.slice {mount} rw - cgroup2 cgroup rw\n",
        encoding="utf-8",
    )
    (fixture / "meminfo").write_text("MemTotal: 16777216 kB\n", encoding="utf-8")
    for path in (mount, ancestor, leaf):
        (path / "memory.max").write_text("max\n", encoding="utf-8")
        (path / "cpu.max").write_text("max 100000\n", encoding="utf-8")
        (path / "cpuset.cpus.effective").write_text("0-7\n", encoding="utf-8")

    program = _linux_sizing_program(output, fixture)
    (ancestor / "memory.max").write_text(str(2048 * 1024 * 1024), encoding="utf-8")
    result = _run_sizing_program(program)
    assert result.returncode == 1
    assert "cgroup memory 2048Mi" in combined(result)

    (ancestor / "memory.max").write_text("max\n", encoding="utf-8")
    (ancestor / "cpu.max").write_text("50000 100000\n", encoding="utf-8")
    result = _run_sizing_program(program)
    assert result.returncode == 1
    assert "cgroup CPU 0.5" in combined(result)

    (ancestor / "cpu.max").write_text("max 100000\n", encoding="utf-8")
    (ancestor / "cpuset.cpus.effective").write_text("0\n", encoding="utf-8")
    result = _run_sizing_program(program)
    assert result.returncode == 1
    assert "cgroup CPU 1" in combined(result)


def test_linux_sizing_resolves_combined_v1_controller_mount_source(
    tmp_path: Path,
) -> None:
    output = render(tmp_path / "render")
    fixture = tmp_path / "cgroup-v1-fixture"
    mount = fixture / "cpu"
    leaf = mount / "app.slice/service.scope"
    ancestor = mount / "app.slice"
    leaf.mkdir(parents=True)
    (fixture / "proc-cgroup").write_text(
        "2:cpu,cpuacct:/tenant.slice/app.slice/service.scope\n", encoding="utf-8"
    )
    (fixture / "mountinfo").write_text(
        f"37 29 0:33 /tenant.slice {mount} rw - cgroup cpu,cpuacct rw\n",
        encoding="utf-8",
    )
    (fixture / "meminfo").write_text("MemTotal: 16777216 kB\n", encoding="utf-8")
    for path in (mount, ancestor, leaf):
        (path / "cpu.cfs_quota_us").write_text("-1\n", encoding="utf-8")
        (path / "cpu.cfs_period_us").write_text("100000\n", encoding="utf-8")
    (ancestor / "cpu.cfs_quota_us").write_text("50000\n", encoding="utf-8")

    result = _run_sizing_program(_linux_sizing_program(output, fixture))
    assert result.returncode == 1
    assert "cgroup CPU 0.5" in combined(result)


@pytest.mark.parametrize(
    ("flag", "replacement"),
    [
        ("--token", "SPLUNK_O11Y_TOKEN_FILE"),
        ("--access-token", "SPLUNK_O11Y_TOKEN_FILE"),
        ("--password", "credentials env/Secret references"),
        ("--datasource", "credentials env/Secret references"),
    ],
)
def test_direct_secret_flags_are_rejected(
    flag: str, replacement: str, tmp_path: Path
) -> None:
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), flag, "INLINE_SHOULD_NOT_LEAK")
    assert result.returncode == 1
    assert replacement in combined(result)
    assert "INLINE_SHOULD_NOT_LEAK" not in combined(result)


def test_equals_form_secret_flag_is_rejected_without_echoing_value() -> None:
    result = run_setup("--connection-string=INLINE_SHOULD_NOT_LEAK")
    assert result.returncode == 1
    assert "credentials env/Secret references" in combined(result)
    assert "INLINE_SHOULD_NOT_LEAK" not in combined(result)

    for flag in ("--client-secret", "--private-key", "--api-key", "--unknown-secret"):
        result = run_setup(f"{flag}=INLINE_SHOULD_NOT_LEAK")
        assert result.returncode == 1
        assert "INLINE_SHOULD_NOT_LEAK" not in combined(result)


def test_inline_secret_and_identifier_injection_are_rejected(tmp_path: Path) -> None:
    spec_data = base_spec()
    spec_data["targets"][0]["password"] = "INLINE_SHOULD_NOT_LEAK"
    result = run_setup(
        "--render", "--spec", str(write_spec(tmp_path / "secret.json", spec_data))
    )
    assert result.returncode == 1
    assert "secret-bearing material" in combined(result)
    assert "INLINE_SHOULD_NOT_LEAK" not in combined(result)

    spec_data = base_spec()
    spec_data["targets"][0]["name"] = "orders; touch pwned"
    result = run_setup(
        "--render", "--spec", str(write_spec(tmp_path / "inject.json", spec_data))
    )
    assert result.returncode == 1
    assert "letters, digits" in combined(result)

    spec_data = base_spec()
    spec_data["targets"][0]["credentials"]["linux_env"]["username_var"] = (
        "SPLUNK_OBSERVABILITY_ACCESS_TOKEN"
    )
    result = run_setup(
        "--render", "--spec", str(write_spec(tmp_path / "reserved-env.json", spec_data))
    )
    assert result.returncode == 1
    assert "must start with DBMON_" in combined(result)


def test_mysql_mariadb_floor_namespace_and_fargate_guards(tmp_path: Path) -> None:
    spec_data = base_spec()
    spec_data["targets"] = [spec_data["targets"][3]]
    spec_data["collector"]["version"] = "v0.153.0"
    spec_data["collector"]["chart_version"] = "0.153.0"
    result = run_setup(
        "--render", "--spec", str(write_spec(tmp_path / "floor.json", spec_data))
    )
    assert result.returncode == 1
    assert "production-audited" in combined(result)
    assert "v0.158.0" in combined(result)

    spec_data = base_spec()
    spec_data["targets"][3]["credentials"]["kubernetes_secret"]["namespace"] = "wrong"
    result = run_setup(
        "--render", "--spec", str(write_spec(tmp_path / "namespace.json", spec_data))
    )
    assert result.returncode == 1
    assert "cannot cross namespaces" in combined(result)

    spec_data = base_spec()
    spec_data["distribution"] = "eks/fargate"
    result = run_setup(
        "--render", "--spec", str(write_spec(tmp_path / "fargate.json", spec_data))
    )
    assert result.returncode == 1
    assert "single-scraper" in combined(result)


def test_postgresql_provider_version_pairs_and_scrape_owner_are_enforced(
    tmp_path: Path,
) -> None:
    spec_data = base_spec()
    spec_data["targets"] = [spec_data["targets"][0]]
    spec_data["targets"][0]["platform"] = "azure-flexible-server"
    spec_data["targets"][0]["version"] = "17.5"
    result = run_setup(
        "--render", "--spec", str(write_spec(tmp_path / "pair.json", spec_data))
    )
    assert result.returncode == 1
    assert "version/platform pair" in combined(result)

    spec_data = base_spec()
    spec_data.pop("scrape_owner")
    result = run_setup(
        "--render", "--spec", str(write_spec(tmp_path / "owner.json", spec_data))
    )
    assert result.returncode == 1
    assert "scrape_owner is required" in combined(result)


def test_non_owner_action_helpers_fail_closed(tmp_path: Path) -> None:
    output = render(tmp_path)
    linux = subprocess.run(
        ["bash", str(output / "scripts/apply-dbmon-linux.sh")],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert linux.returncode == 1
    assert "scrape_owner is kubernetes, not linux" in combined(linux)
    windows = (output / "scripts/apply-dbmon-windows.ps1").read_text(encoding="utf-8")
    assert 'if ("kubernetes" -ne "windows")' in windows


def test_oracle_event_grants_include_session_event_for_query_events(
    tmp_path: Path,
) -> None:
    spec_data = base_spec()
    oracle = spec_data["targets"][2]
    oracle["events"] = {
        "query_sample": True,
        "top_query": True,
        "session_wait_sample": False,
    }
    spec_data["targets"] = [oracle]
    output = render(tmp_path, spec_data)
    runbook = (output / "prerequisites/erp_oracle.md").read_text(encoding="utf-8")
    assert "GRANT SELECT ON SYS.V_$SESSION_EVENT TO OTEL_USER;" in runbook
    assert "GRANT CREATE SESSION TO OTEL_USER;" in runbook
    for required_view in (
        "SYS.V_$ROWCACHE",
        "SYS.V_$SYSMETRIC",
        "SYS.V_$PARAMETER",
        "SYS.DBA_FREE_SPACE",
        "SYS.DBA_RECYCLEBIN",
    ):
        assert f"GRANT SELECT ON {required_view} TO OTEL_USER;" in runbook

    oracle["events"] = {
        "query_sample": False,
        "top_query": False,
        "session_wait_sample": False,
    }
    output = render(tmp_path / "metrics-only", spec_data)
    runbook = (output / "prerequisites/erp_oracle.md").read_text(encoding="utf-8")
    assert "SYS.V_$SESSION_EVENT" not in runbook


def test_product_release_evidence_is_gated_by_enabled_event(tmp_path: Path) -> None:
    spec = base_spec()
    oracle = spec["targets"][2]
    oracle["events"] = {
        "query_sample": False,
        "top_query": False,
        "session_wait_sample": True,
    }
    oracle.setdefault("advanced", {})["query_sample_collection"] = {
        "allowed_comment_keys": ["traceparent"]
    }
    spec["targets"] = [oracle]
    output = render(tmp_path / "session-only", spec)
    validation = (output / "validation/product-validation.md").read_text(
        encoding="utf-8"
    )
    assert "oracle.db.service" in validation
    assert "oracledb.plan.first_load" not in validation
    assert "OBJECT_NAME" not in validation
    assert "db.query.comment_tags" not in validation

    oracle["events"]["query_sample"] = True
    output = render(tmp_path / "query-sample", spec)
    validation = (output / "validation/product-validation.md").read_text(
        encoding="utf-8"
    )
    assert "oracledb.plan.first_load" not in validation
    for plan_field in (
        "OBJECT_NAME",
        "OBJECT_TYPE",
        "FILTER_PREDICATES",
        "PARTITION_START",
        "PARTITION_STOP",
    ):
        assert plan_field not in validation
    assert "db.query.comment_tags" in validation

    oracle["events"]["top_query"] = True
    output = render(tmp_path / "top-query", spec)
    validation = (output / "validation/product-validation.md").read_text(
        encoding="utf-8"
    )
    assert "oracledb.plan.first_load" in validation
    for plan_field in (
        "OBJECT_NAME",
        "OBJECT_TYPE",
        "FILTER_PREDICATES",
        "PARTITION_START",
        "PARTITION_STOP",
    ):
        assert plan_field in validation


def test_sqlserver_release_evidence_separates_top_query_and_resource_overrides(
    tmp_path: Path,
) -> None:
    spec = base_spec()
    sqlserver = next(item for item in spec["targets"] if item["type"] == "sqlserver")
    sqlserver["events"] = {"query_sample": True, "top_query": False}
    sqlserver.setdefault("advanced", {})["resource_attributes"] = {
        "service.name": {"enabled": True},
        "host.name": {"enabled": True, "override_value": "reviewed-db-host"},
    }
    spec["targets"] = [sqlserver]

    output = render(tmp_path / "query-sample", spec)
    validation = (output / "validation/product-validation.md").read_text(
        encoding="utf-8"
    )
    assert "sqlserver.query.plan.creation_time" not in validation
    assert "service resource attributes are populated: `service.name`" in validation
    assert "resource-attribute overrides" in validation
    assert "`host.name`" in validation

    sqlserver["events"]["top_query"] = True
    output = render(tmp_path / "top-query", spec)
    validation = (output / "validation/product-validation.md").read_text(
        encoding="utf-8"
    )
    assert "sqlserver.query.plan.creation_time" in validation


def test_current_mysql_mariadb_product_matrix_and_plan_gaps(
    tmp_path: Path,
) -> None:
    spec = base_spec()
    mysql = next(item for item in spec["targets"] if item["type"] == "mysql")
    mysql["version"] = "5.7"
    spec["targets"] = [mysql]
    output = render(tmp_path / "mysql57", spec)
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    coverage = json.loads((output / "coverage.json").read_text(encoding="utf-8"))
    assert metadata["targets"][0]["support_status"] == "official"
    assert coverage["targets"][0]["query_plan_support"] == "not_supported"
    assert "GRANT PROCESS ON *.*" in (
        output / "prerequisites/catalog_mysql.md"
    ).read_text(encoding="utf-8")

    mariadb = {
        "name": "identity_mariadb",
        "type": "mariadb",
        "platform": "standalone",
        "version": "10.5",
        "endpoint": "identity-mariadb.example.internal:3306",
        "credentials": credentials("identity-mariadb", "DBMON_IDENTITY_MARIADB"),
        "advanced": {"tls": {"insecure": False, "insecure_skip_verify": False}},
    }
    spec["targets"] = [mariadb]
    output = render(tmp_path / "mariadb105", spec)
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    coverage = json.loads((output / "coverage.json").read_text(encoding="utf-8"))
    assert metadata["targets"][0]["support_status"] == "official"
    assert coverage["targets"][0]["query_plan_support"] == "not_supported"
    runbook = (output / "prerequisites/identity_mariadb.md").read_text(
        encoding="utf-8"
    )
    assert "GRANT REPLICATION CLIENT" in runbook
    assert "GRANT PROCESS ON *.*" in runbook

    mysql["version"] = "5.6"
    spec["targets"] = [mysql]
    result = run_setup(
        "--render", "--spec", str(write_spec(tmp_path / "below-floor.json", spec))
    )
    assert result.returncode == 1
    assert "published DBMon product floor 5.7+" in combined(result)

    mysql["version"] = "8.1"
    result = run_setup(
        "--render", "--spec", str(write_spec(tmp_path / "unverified-mysql.json", spec))
    )
    assert result.returncode == 1
    assert "5.7.x, 8.0.x, 8.4.x, or 9.x" in combined(result)

    mariadb["version"] = "12.0"
    spec["targets"] = [mariadb]
    result = run_setup(
        "--render", "--spec", str(write_spec(tmp_path / "unverified-maria.json", spec))
    )
    assert result.returncode == 1
    assert "10.5.x through 10.11.x, or 11.x" in combined(result)

    mysql["version"] = "5.7"
    mysql["platform"] = "azure-flexible-server"
    spec["targets"] = [mysql]
    result = run_setup(
        "--render", "--spec", str(write_spec(tmp_path / "unsupported.json", spec))
    )
    assert result.returncode == 1
    assert "outside the official support matrix" in combined(result)
    spec["allow_unsupported_targets"] = True
    output = render(tmp_path / "lab", spec)
    helper = (output / "scripts/apply-dbmon-overlay.sh").read_text(encoding="utf-8")
    assert "unsupported-target opt-in is render/validate-only" in helper


def test_v0155_tls_schema_and_metric_inventory_are_strict(tmp_path: Path) -> None:
    spec = base_spec()
    mysql = next(item for item in spec["targets"] if item["type"] == "mysql")
    mysql["advanced"]["tls"].update(
        {
            "include_system_ca_certs_pool": True,
            "cipher_suites": ["TLS_AES_256_GCM_SHA384"],
            "curve_preferences": ["X25519", "CurveP256"],
        }
    )
    output = render(tmp_path / "valid", spec)
    receiver = load_yaml(output / "linux/collector-dbmon.yaml")["receivers"][
        "mysql/catalog_mysql"
    ]
    assert receiver["tls"]["include_system_ca_certs_pool"] is True

    bad = base_spec()
    mysql = next(item for item in bad["targets"] if item["type"] == "mysql")
    mysql["advanced"]["tls"]["include_system_ca_certs"] = True
    result = run_setup(
        "--render", "--spec", str(write_spec(tmp_path / "old-tls.json", bad))
    )
    assert result.returncode == 1
    assert "unsupported fields" in combined(result)

    bad = base_spec()
    mysql = next(item for item in bad["targets"] if item["type"] == "mysql")
    mysql["advanced"]["metrics"] = {"mysql.fake": True}
    result = run_setup(
        "--render", "--spec", str(write_spec(tmp_path / "fake-metric.json", bad))
    )
    assert result.returncode == 1
    assert "exact v0.155" in combined(result)


def test_managed_sqlserver_requires_secure_datasource(tmp_path: Path) -> None:
    spec = base_spec()
    sql = next(item for item in spec["targets"] if item["type"] == "sqlserver")
    sql["platform"] = "aws-rds"
    sql["connection_mode"] = "direct"
    sql["server"] = "billing-sql.example.internal"
    sql["transport_exception"] = {
        "reason": "private path",
        "reference": "CHANGE-1234",
        "reviewed_by": "security-owner",
        "reviewed_at": "2026-07-07",
    }
    result = run_setup(
        "--render", "--spec", str(write_spec(tmp_path / "managed-direct.json", spec))
    )
    assert result.returncode == 1
    assert "must use connection_mode: datasource" in combined(result)


def test_output_symlink_and_unreviewed_sizing_are_rejected(tmp_path: Path) -> None:
    destination = tmp_path / "real-output"
    destination.mkdir()
    linked = tmp_path / "linked-output"
    linked.symlink_to(destination, target_is_directory=True)
    spec_path = write_spec(tmp_path / "spec.json")
    result = run_setup(
        "--render", "--spec", str(spec_path), "--output-dir", str(linked)
    )
    assert result.returncode == 1
    assert "not a symlink" in combined(result)

    spec = base_spec()
    spec["sizing_evidence"]["peak_memory_mib"] = 8192
    result = run_setup(
        "--render", "--spec", str(write_spec(tmp_path / "undersized.json", spec))
    )
    assert result.returncode == 1
    assert "below sizing_evidence.peak_memory_mib" in combined(result)


def test_static_validator_rejects_old_exporter_and_replicas(tmp_path: Path) -> None:
    output = render(tmp_path)
    overlay_path = output / "k8s/values.dbmon.clusterreceiver.yaml"
    overlay = load_yaml(overlay_path)
    exporter = overlay["clusterReceiver"]["config"]["exporters"].pop("otlp_http/dbmon")
    overlay["clusterReceiver"]["config"]["exporters"]["otlphttp/dbmon"] = exporter
    write_yaml(overlay_path, overlay)
    result = run_validate(output)
    assert result.returncode == 1
    assert "removed exporter ID" in combined(result)

    output = render(tmp_path / "second")
    overlay_path = output / "k8s/values.dbmon.clusterreceiver.yaml"
    overlay = load_yaml(overlay_path)
    overlay["clusterReceiver"]["replicas"] = 1
    write_yaml(overlay_path, overlay)
    result = run_validate(output)
    assert result.returncode == 1
    assert "not valid in chart 0.158.0" in combined(result)


def test_apply_always_renders_and_validates_before_acceptance_gate(
    tmp_path: Path,
) -> None:
    spec_data = base_spec(outputs={"kubernetes": True, "linux": False, "windows": False})
    output = render(tmp_path / "initial", spec_data)
    (output / "stale.txt").write_text("stale", encoding="utf-8")
    spec = write_spec(
        tmp_path / "spec.json",
        spec_data,
    )
    result = run_setup("--apply-k8s", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 1
    assert "--accept-k8s-apply is required" in combined(result)
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["collector_version"] == "v0.158.0"
    assert not (output / "stale.txt").exists()
    assert "passed static validation" in combined(result)


def fake_kubectl_env(
    tmp_path: Path,
    logs: str,
    *,
    restart_count: int = 0,
    previous_logs: str = "",
    previous_logs_available: bool = True,
    current_log_bytes: int = 0,
) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "kubectl.args"
    kubectl = bin_dir / "kubectl"
    kubectl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${FAKE_KUBECTL_ARGS}"
if [[ "$*" == "config current-context" ]]; then
  printf '%s\n' production-cluster-admin
  exit 0
fi
if [[ "$*" == *"get deployments"* ]]; then
  [[ "$*" == *"--context production-cluster-admin"* ]] || exit 42
  [[ "$*" == *"-n splunk-otel"* ]] || exit 42
  cat <<'JSON'
{"items":[{"metadata":{"name":"dbmon-cluster-receiver"},"spec":{"replicas":1}}]}
JSON
  exit 0
fi
if [[ "$*" == *"get pods"* ]]; then
  [[ "$*" == *"--context production-cluster-admin"* ]] || exit 42
  [[ "$*" == *"-n splunk-otel"* ]] || exit 42
  [[ "$*" == *"release=splunk-otel-collector"* ]] || exit 42
  cat <<JSON
{"items":[{"metadata":{"name":"dbmon-cluster-receiver"},"status":{"conditions":[{"type":"Ready","status":"True"}],"containerStatuses":[{"name":"otel-collector","ready":true,"restartCount":${FAKE_KUBECTL_RESTART_COUNT:-0},"imageID":"quay.io/signalfx/splunk-otel-collector@sha256:16f784e3966cf9ced03ea3765a39f44c3e6395d04d4885e55fde6fc83328b2f0"}]},"spec":{"containers":[{"name":"otel-collector","image":"quay.io/signalfx/splunk-otel-collector:0.158.0@sha256:27a458cd6873d6fef7d3d88fe0a266dffe83d5fe222df738f1937593d8c43357"}]}}]}
JSON
  exit 0
fi
if [[ "$*" == *" logs "* ]]; then
  [[ "$*" == *"--context production-cluster-admin"* ]] || exit 42
  [[ "$*" == *"-n splunk-otel dbmon-cluster-receiver"* ]] || exit 42
  [[ "$*" == *"--since=30s"* ]] || exit 42
  [[ "$*" == *"--tail=-1"* ]] || exit 42
  [[ "$*" == *"--limit-bytes=10485761"* ]] || exit 42
  if [[ "$*" == *"--previous"* ]]; then
    [[ "${FAKE_KUBECTL_PREVIOUS_AVAILABLE:-true}" == "true" ]] || exit 43
    printf '%s\n' "${FAKE_KUBECTL_PREVIOUS_LOGS:-}"
  elif (( ${FAKE_KUBECTL_LOG_BYTES:-0} > 0 )); then
    printf '%s' x
  else
    printf '%s\n' "${FAKE_KUBECTL_LOGS:-}"
  fi
  exit 0
fi
exit 42
""",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)
    wc = bin_dir / "wc"
    wc.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if (( ${FAKE_KUBECTL_LOG_BYTES:-0} > 0 )); then
  printf '%s\n' "${FAKE_KUBECTL_LOG_BYTES}"
else
  exec /usr/bin/wc "$@"
fi
""",
        encoding="utf-8",
    )
    wc.chmod(0o755)
    return {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_KUBECTL_ARGS": str(args_file),
        "FAKE_KUBECTL_LOGS": logs,
        "FAKE_KUBECTL_PREVIOUS_LOGS": previous_logs,
        "FAKE_KUBECTL_PREVIOUS_AVAILABLE": str(previous_logs_available).lower(),
        "FAKE_KUBECTL_RESTART_COUNT": str(restart_count),
        "FAKE_KUBECTL_LOG_BYTES": str(current_log_bytes),
    }, args_file


def test_live_validation_is_scoped_and_does_not_fail_on_known_warnings(
    tmp_path: Path,
) -> None:
    output = render(tmp_path)
    env, args_file = fake_kubectl_env(
        tmp_path, "warn oracledb metadata procedure count is best effort"
    )
    result = run_validate(output, "--live", "--live-since", "30s", env=env)
    assert result.returncode == 0, combined(result)
    calls = args_file.read_text(encoding="utf-8")
    assert "get pods -n splunk-otel" in calls
    assert "-A" not in calls
    log_calls = [line for line in calls.splitlines() if " logs " in line]
    assert len(log_calls) == 1
    assert "--tail=-1" in log_calls[0]
    assert "--limit-bytes=10485761" in log_calls[0]


def test_live_validation_fails_on_critical_receiver_error(tmp_path: Path) -> None:
    output = render(tmp_path)
    env, _ = fake_kubectl_env(
        tmp_path, "postgresql/orders_postgres error: connection refused"
    )
    result = run_validate(output, "--live", "--live-since", "30s", env=env)
    assert result.returncode == 1
    assert "critical failure" in combined(result)


def test_live_validation_scans_bounded_previous_logs_after_restart(
    tmp_path: Path,
) -> None:
    output = render(tmp_path)
    env, args_file = fake_kubectl_env(
        tmp_path,
        "postgresql/orders_postgres scrape completed",
        restart_count=1,
        previous_logs="sqlserver/billing_sqlserver error: connection refused",
    )
    result = run_validate(output, "--live", "--live-since", "30s", env=env)
    assert result.returncode == 1
    assert "critical failure" in combined(result)
    log_calls = [
        line
        for line in args_file.read_text(encoding="utf-8").splitlines()
        if " logs " in line
    ]
    assert len(log_calls) == 2
    assert sum("--previous" in line for line in log_calls) == 1
    assert all("--since=30s" in line for line in log_calls)
    assert all("--tail=-1" in line for line in log_calls)
    assert all("--limit-bytes=10485761" in line for line in log_calls)


def test_live_validation_fails_closed_when_previous_logs_are_unavailable(
    tmp_path: Path,
) -> None:
    output = render(tmp_path)
    env, _ = fake_kubectl_env(
        tmp_path,
        "postgresql/orders_postgres scrape completed",
        restart_count=1,
        previous_logs_available=False,
    )
    result = run_validate(output, "--live", "--live-since", "30s", env=env)
    assert result.returncode == 1
    assert "previous-container logs are unavailable" in combined(result)


def test_live_validation_fails_closed_after_multiple_restarts(tmp_path: Path) -> None:
    output = render(tmp_path)
    env, args_file = fake_kubectl_env(
        tmp_path,
        "postgresql/orders_postgres scrape completed",
        restart_count=2,
        previous_logs="postgresql/orders_postgres prior scrape completed",
    )
    result = run_validate(output, "--live", "--live-since", "30s", env=env)
    assert result.returncode == 1
    assert "restarted more than once" in combined(result)
    assert not any(
        " logs " in line
        for line in args_file.read_text(encoding="utf-8").splitlines()
    )


def test_live_validation_rejects_current_logs_over_ten_mib(tmp_path: Path) -> None:
    output = render(tmp_path)
    env, _ = fake_kubectl_env(
        tmp_path,
        "",
        current_log_bytes=10 * 1024 * 1024 + 1,
    )
    result = run_validate(output, "--live", "--live-since", "30s", env=env)
    assert result.returncode == 1
    assert "current DBMon collector logs exceed the 10 MiB" in combined(result)


def test_live_validation_allows_upstream_best_effort_postgresql_explain_errors(
    tmp_path: Path,
) -> None:
    output = render(tmp_path)
    logs = "\n".join(
        (
            "2026-07-08T01:00:00Z error postgresqlreceiver@v0.158.0/client.go:169 "
            "failed to explain statement postgresql/orders_postgres permission denied",
            "2026-07-08T01:00:00Z error postgresqlreceiver@v0.158.0/scraper.go:365 "
            "failed to explain query postgresql/orders_postgres permission denied",
        )
    )
    env, _ = fake_kubectl_env(tmp_path, logs)
    result = run_validate(output, "--live", "--live-since", "30s", env=env)
    assert result.returncode == 0, combined(result)


@pytest.mark.parametrize(
    "transport_failure",
    [
        "connection refused",
        "connection reset by peer",
        "broken pipe",
        "driver: bad connection",
        "unexpected EOF",
        "server closed the connection unexpectedly",
    ],
)
def test_live_validation_keeps_transport_failure_fatal_inside_explain_error(
    tmp_path: Path, transport_failure: str
) -> None:
    output = render(tmp_path)
    logs = (
        "2026-07-08T01:00:00Z error postgresqlreceiver@v0.158.0/scraper.go:365 "
        f"failed to explain query postgresql/orders_postgres {transport_failure}"
    )
    env, _ = fake_kubectl_env(tmp_path, logs)
    result = run_validate(output, "--live", "--live-since", "30s", env=env)
    assert result.returncode == 1
    assert "critical failure" in combined(result)


def secure_token(path: Path, value: str = "TOKEN_SHOULD_NOT_PRINT") -> Path:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


def sse(metric: str, *, with_data: bool = True) -> str:
    data = 'event: data\ndata: {"data":[{"value":1}]}\n\n' if with_data else ""
    return (
        "event: metadata\n"
        f'data: {{"properties":{{"sf_originatingMetric":"{metric}"}}}}\n\n' + data
    )


def target_probe_metadata() -> dict:
    return {
        "realm": "us1",
        "targets": [
            {
                "name": "orders_postgres",
                "receiver_id": "postgresql/orders_postgres",
            },
            {
                "name": "catalog_mysql",
                "receiver_id": "mysql/catalog_mysql",
            },
        ],
        "validation_probes": [
            {
                "target": "orders_postgres",
                "receiver_id": "postgresql/orders_postgres",
                "metric": "postgresql.database.count",
                "filters": [{"key": "service.instance.id", "value": "orders-db-01"}],
            },
            {
                "target": "catalog_mysql",
                "receiver_id": "mysql/catalog_mysql",
                "metric": "mysql.buffer_pool.usage",
                "filters": [
                    {
                        "key": "mysql.instance.endpoint",
                        "value": "catalog-db-01:3306",
                    }
                ],
            },
        ],
    }


def one_target_probe_metadata() -> dict:
    metadata = target_probe_metadata()
    metadata["targets"] = metadata["targets"][:1]
    metadata["validation_probes"] = metadata["validation_probes"][:1]
    return metadata


def test_api_probe_runs_every_target_probe_with_redacted_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    token = secure_token(tmp_path / "token")
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(target_probe_metadata()), encoding="utf-8")
    metrics = ["postgresql.database.count", "mysql.buffer_pool.usage"]
    requests: list[object] = []
    programs: list[str] = []

    def fake_urlopen(request, timeout: int):  # type: ignore[no-untyped-def]
        requests.append(request)
        if "/v2/metric?" in request.full_url:
            query = urllib_parse_query(request.full_url)
            metric = query["query"][0].removeprefix("name:")
            return FakeResponse(json.dumps({"count": 1, "results": [{"name": metric}]}))
        assert request.full_url.startswith(
            "https://stream.us1.observability.splunkcloud.com/v2/signalflow/execute"
        )
        program = request.data.decode("utf-8")
        programs.append(program)
        metric = next(item for item in metrics if item in program)
        return FakeResponse(sse(metric))

    monkeypatch.setattr(dbmon_api_probe.urllib.request, "urlopen", fake_urlopen)
    assert (
        dbmon_api_probe.run(["--metadata", str(metadata), "--token-file", str(token)])
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["global_filters"] == []
    assert [item["target"] for item in payload["probes"]] == [
        "orders_postgres",
        "catalog_mysql",
    ]
    assert [item["metric"] for item in payload["probes"]] == metrics
    assert all(item["signalflow"]["data_messages"] > 0 for item in payload["probes"])
    assert all(
        item["filters"][0]["value"] == "<redacted>" for item in payload["probes"]
    )
    serialized = json.dumps(payload)
    assert "orders-db-01" not in serialized
    assert "catalog-db-01:3306" not in serialized
    assert any("orders-db-01" in program for program in programs)
    assert any("catalog-db-01:3306" in program for program in programs)
    assert len(requests) == 4


def urllib_parse_query(url: str) -> dict[str, list[str]]:
    from urllib.parse import parse_qs, urlparse

    return parse_qs(urlparse(url).query)


def test_api_probe_global_filter_augments_but_cannot_override_target_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    token = secure_token(tmp_path / "token")
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(one_target_probe_metadata()), encoding="utf-8")
    programs: list[str] = []

    def fake_urlopen(request, timeout: int):  # type: ignore[no-untyped-def]
        metric = "postgresql.database.count"
        if "/v2/metric?" in request.full_url:
            return FakeResponse(json.dumps({"count": 1, "results": [{"name": metric}]}))
        programs.append(request.data.decode("utf-8"))
        return FakeResponse(sse(metric))

    monkeypatch.setattr(dbmon_api_probe.urllib.request, "urlopen", fake_urlopen)
    assert (
        dbmon_api_probe.run(
            [
                "--metadata",
                str(metadata),
                "--token-file",
                str(token),
                "--filter",
                "deployment.environment=production",
            ]
        )
        == 0
    )
    assert "service.instance.id" in programs[0]
    assert "orders-db-01" in programs[0]
    assert "deployment.environment" in programs[0]
    assert "production" in programs[0]
    output = capsys.readouterr().out
    assert "orders-db-01" not in output
    assert "production" not in output

    with pytest.raises(dbmon_api_probe.ApiProbeError, match="conflicts") as raised:
        dbmon_api_probe.run(
            [
                "--metadata",
                str(metadata),
                "--token-file",
                str(token),
                "--filter",
                "service.instance.id=attempted-override",
            ]
        )
    assert "orders-db-01" not in str(raised.value)
    assert "attempted-override" not in str(raised.value)


def test_api_probe_fails_when_one_target_has_no_positive_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = secure_token(tmp_path / "token")
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(target_probe_metadata()), encoding="utf-8")

    def fake_urlopen(request, timeout: int):  # type: ignore[no-untyped-def]
        if "/v2/metric?" in request.full_url:
            query = urllib_parse_query(request.full_url)
            metric = query["query"][0].removeprefix("name:")
            return FakeResponse(json.dumps({"count": 1, "results": [{"name": metric}]}))
        program = request.data.decode("utf-8")
        metric = (
            "mysql.buffer_pool.usage"
            if "mysql.buffer_pool.usage" in program
            else "postgresql.database.count"
        )
        if metric == "mysql.buffer_pool.usage":
            return FakeResponse(sse(metric).replace('"value":1', '"value":0'))
        return FakeResponse(sse(metric))

    monkeypatch.setattr(dbmon_api_probe.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(dbmon_api_probe.ApiProbeError, match="catalog_mysql") as raised:
        dbmon_api_probe.run(["--metadata", str(metadata), "--token-file", str(token)])
    assert "catalog-db-01:3306" not in str(raised.value)


def test_signalflow_stream_finishes_on_positive_data_without_waiting_for_eof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    token = secure_token(tmp_path / "token")
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(one_target_probe_metadata()), encoding="utf-8")
    metric = "postgresql.database.count"

    class TimeoutAfterBodyResponse(FakeResponse):
        def readline(self, size: int = -1) -> bytes:
            value = super().readline(size)
            if not value:
                raise TimeoutError("stream intentionally remains open")
            return value

    def fake_urlopen(request, timeout: int):  # type: ignore[no-untyped-def]
        if "/v2/metric?" in request.full_url:
            return FakeResponse(json.dumps({"count": 1, "results": [{"name": metric}]}))
        return TimeoutAfterBodyResponse(sse(metric))

    monkeypatch.setattr(dbmon_api_probe.urllib.request, "urlopen", fake_urlopen)
    assert (
        dbmon_api_probe.run(["--metadata", str(metadata), "--token-file", str(token)])
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["probes"][0]["signalflow"]["data_messages"] == 1


def test_signalflow_timeout_with_partial_metadata_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = secure_token(tmp_path / "token")
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(one_target_probe_metadata()), encoding="utf-8")
    metric = "postgresql.database.count"

    class TimeoutAfterBodyResponse(FakeResponse):
        def readline(self, size: int = -1) -> bytes:
            value = super().readline(size)
            if not value:
                raise TimeoutError("stream intentionally remains open")
            return value

    def fake_urlopen(request, timeout: int):  # type: ignore[no-untyped-def]
        if "/v2/metric?" in request.full_url:
            return FakeResponse(json.dumps({"count": 1, "results": [{"name": metric}]}))
        return TimeoutAfterBodyResponse(
            f'event: metadata\ndata: {{"properties":{{"sf_originatingMetric":"{metric}"}}}}\n\n'
        )

    monkeypatch.setattr(dbmon_api_probe.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(dbmon_api_probe.ApiProbeError, match="no positive data"):
        dbmon_api_probe.run(["--metadata", str(metadata), "--token-file", str(token)])


def test_signalflow_endless_control_stream_stops_at_absolute_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = secure_token(tmp_path / "token")
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(one_target_probe_metadata()), encoding="utf-8")
    metric = "postgresql.database.count"

    class EndlessControlResponse:
        def __init__(self) -> None:
            self.lines = (
                b"event: control-message\n",
                b'data: {"event":"JOB_PROGRESS","progress":10}\n',
                b"\n",
            )
            self.read_calls = 0

        def __enter__(self) -> "EndlessControlResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def readline(self, size: int = -1) -> bytes:
            line = self.lines[self.read_calls % len(self.lines)]
            self.read_calls += 1
            return line

    stream = EndlessControlResponse()
    monotonic_value = -0.25

    def advancing_monotonic() -> float:
        nonlocal monotonic_value
        monotonic_value += 0.25
        return monotonic_value

    def fake_urlopen(request, timeout: int):  # type: ignore[no-untyped-def]
        if "/v2/metric?" in request.full_url:
            return FakeResponse(json.dumps({"count": 1, "results": [{"name": metric}]}))
        return stream

    monkeypatch.setattr(dbmon_api_probe.time, "monotonic", advancing_monotonic)
    monkeypatch.setattr(dbmon_api_probe.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(dbmon_api_probe.ApiProbeError) as raised:
        dbmon_api_probe.run(
            [
                "--metadata",
                str(metadata),
                "--token-file",
                str(token),
                "--timeout-seconds",
                "1",
            ]
        )
    assert "SignalFlow" in str(raised.value)
    assert stream.read_calls == 3
    assert monotonic_value >= 1.0


def test_signalflow_http_errors_suppress_filter_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    import urllib.error

    token = secure_token(tmp_path / "token")
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(one_target_probe_metadata()), encoding="utf-8")

    class CloseOnlyBody(io.BytesIO):
        closed_by_probe = False

        def read(self, size: int = -1) -> bytes:
            raise AssertionError("suppressed HTTP error bodies must not be drained")

        def close(self) -> None:
            self.closed_by_probe = True
            super().close()

    error_body = CloseOnlyBody(
        b"rejected filter orders-db-01 TOKEN_SHOULD_NOT_PRINT"
    )

    def fake_urlopen(request, timeout: int):  # type: ignore[no-untyped-def]
        metric = "postgresql.database.count"
        if "/v2/metric?" in request.full_url:
            return FakeResponse(json.dumps({"count": 1, "results": [{"name": metric}]}))
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "bad program",
            {},
            error_body,
        )

    monkeypatch.setattr(dbmon_api_probe.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(dbmon_api_probe.ApiProbeError) as raised:
        dbmon_api_probe.run(["--metadata", str(metadata), "--token-file", str(token)])
    assert "orders-db-01" not in str(raised.value)
    assert "TOKEN_SHOULD_NOT_PRINT" not in str(raised.value)
    assert "response body was suppressed" in str(raised.value)
    assert error_body.closed_by_probe


def test_metric_catalog_http_error_suppresses_literal_and_escaped_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.error

    token = "TOKEN_SHOULD_NOT_PRINT"
    escaped_token = r"TOKEN\u005fSHOULD\u005fNOT\u005fPRINT"
    response_body = (
        '{"literal":"TOKEN_SHOULD_NOT_PRINT",'
        f'"escaped":"{escaped_token}","target":"orders-db-01"}}'
    ).encode("utf-8")

    class CloseOnlyBody(io.BytesIO):
        closed_by_probe = False

        def read(self, size: int = -1) -> bytes:
            raise AssertionError("suppressed HTTP error bodies must not be drained")

        def close(self) -> None:
            self.closed_by_probe = True
            super().close()

    error_body = CloseOnlyBody(response_body)

    def fake_urlopen(request, timeout: int):  # type: ignore[no-untyped-def]
        raise urllib.error.HTTPError(
            request.full_url,
            500,
            "catalog failure",
            {},
            error_body,
        )

    monkeypatch.setattr(dbmon_api_probe.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(dbmon_api_probe.ApiProbeError) as raised:
        dbmon_api_probe.request_json(
            "https://api.us1.observability.splunkcloud.com/v2/metric",
            token,
            20,
        )
    message = str(raised.value)
    assert token not in message
    assert escaped_token not in message
    assert "orders-db-01" not in message
    assert "HTTP 500; response body was suppressed" in message
    assert error_body.closed_by_probe


def test_metric_catalog_response_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OversizedResponse:
        def __enter__(self) -> "OversizedResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            assert size == 1024 * 1024 + 1
            return b"x" * size

    monkeypatch.setattr(
        dbmon_api_probe.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: OversizedResponse(),
    )
    with pytest.raises(dbmon_api_probe.ApiProbeError, match="one-megabyte"):
        dbmon_api_probe.request_json(
            "https://api.us1.observability.splunkcloud.com/v2/metric",
            "TOKEN_SHOULD_NOT_PRINT",
            20,
        )


def test_metric_catalog_timeout_is_wrapped_without_secret_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = secure_token(tmp_path / "token")
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(one_target_probe_metadata()), encoding="utf-8")

    def fake_urlopen(request, timeout: int):  # type: ignore[no-untyped-def]
        raise TimeoutError("orders-db-01 TOKEN_SHOULD_NOT_PRINT")

    monkeypatch.setattr(dbmon_api_probe.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(dbmon_api_probe.ApiProbeError, match="request timed out") as raised:
        dbmon_api_probe.run(["--metadata", str(metadata), "--token-file", str(token)])
    assert "orders-db-01" not in str(raised.value)
    assert "TOKEN_SHOULD_NOT_PRINT" not in str(raised.value)


def test_ad_hoc_api_metric_requires_filter_and_remains_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    token = secure_token(tmp_path / "token")
    metric = "postgresql.database.count"
    with pytest.raises(dbmon_api_probe.ApiProbeError, match="requires at least one"):
        dbmon_api_probe.run(
            ["--realm", "us1", "--token-file", str(token), "--metric", metric]
        )

    def fake_urlopen(request, timeout: int):  # type: ignore[no-untyped-def]
        if "/v2/metric?" in request.full_url:
            return FakeResponse(json.dumps({"count": 1, "results": [{"name": metric}]}))
        assert "service.instance.id" in request.data.decode("utf-8")
        return FakeResponse(sse(metric))

    monkeypatch.setattr(dbmon_api_probe.urllib.request, "urlopen", fake_urlopen)
    assert (
        dbmon_api_probe.run(
            [
                "--realm",
                "us1",
                "--token-file",
                str(token),
                "--metric",
                metric,
                "--filter",
                "service.instance.id=ad-hoc-db-01",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["probes"][0]["target"] == "ad-hoc-1"
    assert payload["probes"][0]["filters"][0]["value"] == "<redacted>"
    assert "ad-hoc-db-01" not in json.dumps(payload)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda metadata: metadata["validation_probes"][0].update({"filters": []}),
        lambda metadata: metadata["validation_probes"].append(
            dict(metadata["validation_probes"][0])
        ),
        lambda metadata: metadata["validation_probes"][0].update(
            {"filters": [{"key": "db.password", "value": "suppressed"}]}
        ),
        lambda metadata: metadata["validation_probes"][0].update(
            {
                "filters": [
                    {
                        "key": "service.instance.id",
                        "value": "postgres://user:SECRET_SHOULD_NOT_PRINT@db",
                    }
                ]
            }
        ),
    ],
)
def test_metadata_probes_reject_malformed_or_secret_like_filters(mutator) -> None:  # type: ignore[no-untyped-def]
    metadata = one_target_probe_metadata()
    mutator(metadata)
    with pytest.raises(dbmon_api_probe.ApiProbeError) as raised:
        dbmon_api_probe.normalize_metadata_probes(metadata, [])
    assert "SECRET_SHOULD_NOT_PRINT" not in str(raised.value)


def test_metadata_probes_require_complete_target_coverage() -> None:
    metadata = target_probe_metadata()
    metadata["validation_probes"] = metadata["validation_probes"][:1]
    with pytest.raises(dbmon_api_probe.ApiProbeError, match="does not cover every"):
        dbmon_api_probe.normalize_metadata_probes(metadata, [])


@pytest.mark.parametrize(
    "raw_filter",
    [
        "db.password=SECRET_SHOULD_NOT_PRINT",
        "service.instance.id=Bearer SECRET_SHOULD_NOT_PRINT",
        "bad key=SECRET_SHOULD_NOT_PRINT",
        "SECRET_SHOULD_NOT_PRINT",
    ],
)
def test_cli_filters_reject_malformed_or_secret_like_values_without_echo(
    raw_filter: str,
) -> None:
    with pytest.raises(dbmon_api_probe.ApiProbeError) as raised:
        dbmon_api_probe.parse_filter(raw_filter)
    assert "SECRET_SHOULD_NOT_PRINT" not in str(raised.value)


def test_legacy_global_metric_metadata_cannot_bypass_target_filters() -> None:
    with pytest.raises(dbmon_api_probe.ApiProbeError, match="validation_probes"):
        dbmon_api_probe.normalize_metadata_probes(
            {
                "targets": [
                    {
                        "name": "orders_postgres",
                        "receiver_id": "postgresql/orders_postgres",
                    }
                ],
                "validation_metrics": ["postgresql.database.count"],
            },
            [],
        )


def test_ad_hoc_metric_rejects_secret_like_input_without_echo() -> None:
    secret_like_metric = "AKIAABCDEFGHIJKLMNOP"
    with pytest.raises(dbmon_api_probe.ApiProbeError) as raised:
        dbmon_api_probe.normalize_ad_hoc_probes(
            [secret_like_metric], [("service.instance.id", "db-01")]
        )
    assert secret_like_metric not in str(raised.value)


@pytest.mark.parametrize("kind", ["mode", "newline", "symlink", "hardlink"])
def test_api_token_file_guardrails(tmp_path: Path, kind: str) -> None:
    original = tmp_path / "original"
    original.write_text("TOKEN" + ("\n" if kind == "newline" else ""), encoding="utf-8")
    original.chmod(0o600 if kind != "mode" else 0o644)
    candidate = original
    if kind == "symlink":
        candidate = tmp_path / "link"
        candidate.symlink_to(original)
    elif kind == "hardlink":
        candidate = tmp_path / "hardlink"
        os.link(original, candidate)
    with pytest.raises(dbmon_api_probe.ApiProbeError):
        dbmon_api_probe.token_from_file(str(candidate))


def test_api_token_file_rejects_owner_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = secure_token(tmp_path / "token")
    actual_uid = token.stat().st_uid
    monkeypatch.setattr(dbmon_api_probe.os, "geteuid", lambda: actual_uid + 1)

    with pytest.raises(dbmon_api_probe.ApiProbeError, match="owned by the current user"):
        dbmon_api_probe.token_from_file(str(token))


def test_api_token_file_open_is_nonblocking_against_fifo_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = secure_token(tmp_path / "token")
    real_open = dbmon_api_probe.os.open
    observed_flags = 0

    def tracking_open(path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal observed_flags
        observed_flags = flags
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(dbmon_api_probe.os, "open", tracking_open)
    assert dbmon_api_probe.token_from_file(str(token)) == "TOKEN_SHOULD_NOT_PRINT"
    if hasattr(dbmon_api_probe.os, "O_NONBLOCK"):
        assert observed_flags & dbmon_api_probe.os.O_NONBLOCK


@pytest.mark.parametrize("kind", ["fifo", "directory"])
def test_api_token_file_rejects_non_regular_paths_before_open(
    tmp_path: Path, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / kind
    if kind == "fifo":
        os.mkfifo(candidate, 0o600)
    else:
        candidate.mkdir(mode=0o700)
    monkeypatch.setattr(
        dbmon_api_probe.os,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("non-regular token path must be rejected before os.open")
        ),
    )

    with pytest.raises(dbmon_api_probe.ApiProbeError, match="regular file"):
        dbmon_api_probe.token_from_file(str(candidate))


def test_collector_validate_pins_exact_image(tmp_path: Path) -> None:
    output = render(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "container.args"
    docker = bin_dir / "docker"
    docker.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\n\' "$*" > "${CONTAINER_ARGS}"\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "CONTAINER_ARGS": str(args_file)}
    result = run_validate(output, "--collector-validate", env=env)
    assert result.returncode == 0, combined(result)
    args = args_file.read_text(encoding="utf-8")
    assert "quay.io/signalfx/splunk-otel-collector:0.158.0" in args
    assert "validate --config=/etc/otel/collector/dbmon.yaml" in args
    assert "--network=none" in args


def test_collector_validate_cleans_k8s_temp_config_after_runtime_failure(
    tmp_path: Path,
) -> None:
    spec = base_spec(
        outputs={"kubernetes": True, "linux": False, "windows": False}
    )
    output = render(tmp_path, spec)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "container.args"
    docker = bin_dir / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
printf '%s\n' "$@" > "${CONTAINER_ARGS}"
exit 73
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "CONTAINER_ARGS": str(args_file)}

    result = run_validate(output, "--collector-validate", env=env)

    assert result.returncode == 73, combined(result)
    mount_suffix = ":/etc/otel/collector/dbmon.yaml:ro"
    mount_arg = next(
        argument
        for argument in args_file.read_text(encoding="utf-8").splitlines()
        if argument.endswith(mount_suffix)
    )
    temporary_config = Path(mount_arg.removesuffix(mount_suffix))
    assert temporary_config.is_absolute()
    assert not temporary_config.exists()
