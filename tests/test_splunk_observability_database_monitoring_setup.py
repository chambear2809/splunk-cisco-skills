"""Regressions for splunk-observability-database-monitoring-setup rendering."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/splunk-observability-database-monitoring-setup/scripts/setup.sh"
VALIDATE = REPO_ROOT / "skills/splunk-observability-database-monitoring-setup/scripts/validate.sh"
API_PROBE = REPO_ROOT / "skills/splunk-observability-database-monitoring-setup/scripts/api_probe.py"
LIB_DIR = REPO_ROOT / "skills/shared/lib"
sys.path.insert(0, str(LIB_DIR))
from yaml_compat import load_yaml_or_json  # noqa: E402

api_probe_spec = importlib.util.spec_from_file_location("dbmon_api_probe", API_PROBE)
assert api_probe_spec and api_probe_spec.loader
dbmon_api_probe = importlib.util.module_from_spec(api_probe_spec)
api_probe_spec.loader.exec_module(dbmon_api_probe)


class FakeResponse:
    def __init__(self, body: str, status: int = 200) -> None:
        self.body = body.encode("utf-8")
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        if size == -1:
            return self.body
        return self.body[:size]


def run_setup(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SETUP), *args],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
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


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def load_yaml(path: Path) -> dict:
    data = load_yaml_or_json(path.read_text(encoding="utf-8"), source=str(path))
    assert isinstance(data, dict)
    return data


def rendered_text(root: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def base_spec() -> dict:
    return {
        "api_version": "splunk-observability-database-monitoring-setup/v1",
        "realm": "us1",
        "cluster_name": "lab-cluster",
        "distribution": "kubernetes",
        "collector": {
            "version": "v0.150.0",
            "namespace": "splunk-otel",
            "release_name": "splunk-otel-collector",
            "secret_name": "splunk-otel-collector-splunk",
            "token_key": "splunk_observability_access_token",
        },
        "outputs": {"kubernetes": True, "linux": True},
        "targets": [
            {
                "name": "orders_postgres",
                "type": "postgresql",
                "platform": "aws-rds",
                "version": "17.5",
                "endpoint": "orders-postgres.example.internal:5432",
                "databases": ["orders"],
                "credentials": {
                    "kubernetes_secret": {
                        "name": "dbmon-orders-postgres",
                        "namespace": "splunk-otel",
                        "username_key": "username",
                        "password_key": "password",
                    },
                    "linux_env": {
                        "username_var": "DBMON_ORDERS_POSTGRES_USERNAME",
                        "password_var": "DBMON_ORDERS_POSTGRES_PASSWORD",
                    },
                },
                "events": {"query_sample": True, "top_query": True},
            },
            {
                "name": "billing_sqlserver",
                "type": "sqlserver",
                "platform": "self-hosted",
                "version": "2022",
                "server": "billing-sql.example.internal",
                "port": 1433,
                "credentials": {
                    "kubernetes_secret": {
                        "name": "dbmon-billing-sqlserver",
                        "namespace": "splunk-otel",
                        "username_key": "username",
                        "password_key": "password",
                    },
                    "linux_env": {
                        "username_var": "DBMON_BILLING_SQLSERVER_USERNAME",
                        "password_var": "DBMON_BILLING_SQLSERVER_PASSWORD",
                    },
                },
                "events": {"query_sample": True, "top_query": True},
            },
            {
                "name": "erp_oracle_node1",
                "type": "oracledb",
                "platform": "oracle-rac",
                "version": "19c",
                "endpoint": "erp-oracle-node1.example.internal:1521",
                "service": "ERPPROD",
                "credentials": {
                    "kubernetes_secret": {
                        "name": "dbmon-erp-oracle-node1",
                        "namespace": "splunk-otel",
                        "username_key": "username",
                        "password_key": "password",
                    },
                    "linux_env": {
                        "username_var": "DBMON_ERP_ORACLE_NODE1_USERNAME",
                        "password_var": "DBMON_ERP_ORACLE_NODE1_PASSWORD",
                    },
                },
                "events": {"query_sample": True, "top_query": True},
            },
        ],
    }


def write_spec(path: Path, spec: dict | None = None) -> Path:
    path.write_text(json.dumps(spec or base_spec(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def fake_kubectl_env(tmp_path: Path, logs: str) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "kubectl.args"
    kubectl = bin_dir / "kubectl"
    kubectl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "${FAKE_KUBECTL_ARGS}"
if [[ "${1:-}" == "get" && "${2:-}" == "pods" ]]; then
    if [[ "$*" != *"component in (otel-k8s-cluster-receiver,k8s-cluster-receiver)"* ]]; then
        echo "unexpected selector: $*" >&2
        exit 42
    fi
    if [[ "$*" == *"jsonpath"* ]]; then
        printf 'otel-splunk\\tsplunk-otel-collector-k8s-cluster-receiver-test\\n'
        exit 0
    fi
    echo "NAMESPACE NAME READY STATUS RESTARTS AGE"
    echo "otel-splunk splunk-otel-collector-k8s-cluster-receiver-test 1/1 Running 0 1m"
    exit 0
fi
if [[ "${1:-}" == "logs" ]]; then
    if [[ "$*" != *"--since=30s"* ]]; then
        echo "missing --since=30s: $*" >&2
        exit 42
    fi
    printf '%s\\n' "${FAKE_KUBECTL_LOGS:-}"
    exit 0
fi
echo "unexpected kubectl args: $*" >&2
exit 42
""",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_KUBECTL_ARGS": str(args_file),
        "FAKE_KUBECTL_LOGS": logs,
    }
    return env, args_file


def test_render_produces_k8s_linux_and_gateway_assets(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--validate", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)

    expected = {
        "k8s/values.dbmon.clusterreceiver.yaml",
        "k8s/secrets.dbmon.stub.yaml",
        "k8s/handoff-base-collector.sh",
        "linux/collector-dbmon.yaml",
        "linux/dbmon.env.template",
        "linux/handoff-base-collector.sh",
        "references/gateway-routing.sqlserver.md",
        "metadata.json",
    }
    rendered = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
    assert expected <= rendered

    overlay = load_yaml(output / "k8s/values.dbmon.clusterreceiver.yaml")
    assert "agent" not in overlay
    cluster = overlay["clusterReceiver"]
    assert cluster["enabled"] is True
    assert cluster["replicas"] == 1
    config = cluster["config"]
    assert set(config["receivers"]) == {
        "postgresql/orders_postgres",
        "sqlserver/billing_sqlserver",
        "oracledb/erp_oracle_node1",
    }
    assert config["exporters"]["otlphttp/dbmon"]["logs_endpoint"] == (
        "https://ingest.us1.observability.splunkcloud.com/v3/event"
    )
    assert config["exporters"]["otlphttp/dbmon"]["headers"][
        "X-splunk-instrumentation-library"
    ] == "dbmon"
    assert config["service"]["pipelines"]["metrics"]["processors"] == config["service"][
        "pipelines"
    ]["logs/dbmon"]["processors"]

    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["target_count"] == 3
    assert any("license" in warning.lower() for warning in metadata["warnings"])


def test_linux_config_uses_env_placeholders_not_inline_secrets(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    linux = load_yaml(output / "linux/collector-dbmon.yaml")
    sqlserver = linux["receivers"]["sqlserver/billing_sqlserver"]
    assert sqlserver["username"] == "${env:DBMON_BILLING_SQLSERVER_USERNAME}"
    assert sqlserver["password"] == "${env:DBMON_BILLING_SQLSERVER_PASSWORD}"
    assert "SPLUNK_ACCESS_TOKEN=" in (output / "linux/dbmon.env.template").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    ("flag", "replacement"),
    [
        ("--token", "SPLUNK_O11Y_TOKEN_FILE"),
        ("--access-token", "SPLUNK_O11Y_TOKEN_FILE"),
        ("--password", "credentials.*_env"),
        ("--datasource", "credentials.*_env"),
        ("--connection-string", "credentials.*_env"),
    ],
)
def test_direct_secret_flags_are_rejected(flag: str, replacement: str, tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), flag, "INLINE_SHOULD_NOT_LEAK")
    assert result.returncode == 1
    assert replacement in combined_output(result)
    assert "INLINE_SHOULD_NOT_LEAK" not in combined_output(result)


def test_inline_password_in_spec_is_rejected(tmp_path: Path) -> None:
    spec_data = base_spec()
    spec_data["targets"][0]["password"] = "INLINE_SHOULD_NOT_LEAK"
    spec = write_spec(tmp_path / "spec.json", spec_data)
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(tmp_path / "out"))
    assert result.returncode == 1
    assert "secret-bearing material" in combined_output(result)
    assert "INLINE_SHOULD_NOT_LEAK" not in combined_output(result)


def test_mysql_is_explicitly_rejected(tmp_path: Path) -> None:
    spec_data = base_spec()
    spec_data["targets"] = [
        {
            "name": "legacy_mysql",
            "type": "mysql",
            "platform": "self-hosted",
            "version": "8.0.34",
            "endpoint": "mysql.example.internal:3306",
        }
    ]
    spec = write_spec(tmp_path / "spec.json", spec_data)
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(tmp_path / "out"))
    assert result.returncode == 1
    assert "MySQL" in combined_output(result)
    assert "not supported" in combined_output(result)


def test_realm_allow_list_rejects_us2(tmp_path: Path) -> None:
    spec_data = base_spec()
    spec_data["realm"] = "us2"
    spec = write_spec(tmp_path / "spec.json", spec_data)
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(tmp_path / "out"))
    assert result.returncode == 1
    assert "realm 'us2'" in combined_output(result)


def test_env_realm_fallback_when_spec_omits_realm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_data = base_spec()
    spec_data.pop("realm")
    spec = write_spec(tmp_path / "spec.json", spec_data)
    monkeypatch.setenv("SPLUNK_O11Y_REALM", "eu1")
    result = run_setup("--dry-run", "--json", "--spec", str(spec))
    assert result.returncode == 0, combined_output(result)
    assert json.loads(result.stdout)["realm"] == "eu1"


def test_collector_version_floors_are_enforced(tmp_path: Path) -> None:
    spec_data = base_spec()
    spec_data["targets"] = [spec_data["targets"][1]]
    spec_data["collector"]["version"] = "v0.147.0"
    spec = write_spec(tmp_path / "spec.json", spec_data)
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(tmp_path / "out"))
    assert result.returncode == 1
    assert "v0.148.0 or later" in combined_output(result)


def test_support_matrix_rejects_invalid_postgres_platform(tmp_path: Path) -> None:
    spec_data = base_spec()
    spec_data["targets"] = [spec_data["targets"][0]]
    spec_data["targets"][0]["platform"] = "self-hosted"
    spec = write_spec(tmp_path / "spec.json", spec_data)
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(tmp_path / "out"))
    assert result.returncode == 1
    assert "platform 'self-hosted' is outside the official support matrix" in (
        combined_output(result)
    )


def test_live_demo_postgres16_shape_is_rejected_by_official_matrix(
    tmp_path: Path,
) -> None:
    spec_data = base_spec()
    spec_data["targets"] = [
        {
            "name": "streaming_postgres",
            "type": "postgresql",
            "platform": "self-hosted",
            "version": "16",
            "endpoint": "streaming-postgres.streaming-service-app.svc.cluster.local:5432",
            "databases": ["streaming"],
        }
    ]
    spec = write_spec(tmp_path / "spec.json", spec_data)
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(tmp_path / "out"))
    assert result.returncode == 1
    assert "postgresql/streaming_postgres platform 'self-hosted' is outside" in combined_output(
        result
    )


def test_allow_unsupported_target_renders_live_demo_postgres16(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec_data = base_spec()
    spec_data["targets"] = [
        {
            "name": "streaming_postgres",
            "type": "postgresql",
            "platform": "self-hosted",
            "version": "16",
            "endpoint": "streaming-postgres.streaming-service-app.svc.cluster.local:5432",
            "databases": ["streaming"],
            "credentials": {
                "kubernetes_secret": {
                    "name": "streaming-postgres-dbmon",
                    "namespace": "otel-splunk",
                    "username_key": "username",
                    "password_key": "password",
                },
                "linux_env": {
                    "username_var": "SPLUNK_DBMON_POSTGRES_USERNAME",
                    "password_var": "SPLUNK_DBMON_POSTGRES_PASSWORD",
                },
            },
        }
    ]
    spec = write_spec(tmp_path / "spec.json", spec_data)
    result = run_setup(
        "--render",
        "--validate",
        "--allow-unsupported-targets",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, combined_output(result)
    overlay = load_yaml(output / "k8s/values.dbmon.clusterreceiver.yaml")
    assert "postgresql/streaming_postgres" in overlay["clusterReceiver"]["config"][
        "receivers"
    ]
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["support_mode"] == "unsupported-opt-in"
    assert metadata["targets"][0]["support_status"] == "unsupported_opt_in"
    assert "self-hosted" in " ".join(metadata["targets"][0]["support_notes"])
    assert "version '16'" in " ".join(metadata["targets"][0]["support_notes"])
    assert any("unsupported-target opt-in" in item for item in metadata["warnings"])


def test_spec_level_allow_unsupported_target_renders(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec_data = base_spec()
    spec_data["allow_unsupported_targets"] = True
    spec_data["targets"] = [
        {
            "name": "streaming_postgres",
            "type": "postgresql",
            "platform": "self-hosted",
            "version": "16",
            "endpoint": "streaming-postgres.streaming-service-app.svc.cluster.local:5432",
            "databases": ["streaming"],
        }
    ]
    spec = write_spec(tmp_path / "spec.json", spec_data)
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)


def test_base_values_merge_preserves_existing_pipeline_arrays(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    base_values = tmp_path / "base-values.json"
    base_values.write_text(
        json.dumps(
            {
                "agent": {
                    "config": {
                        "receivers": {"otlp": {"protocols": {"grpc": {}}}},
                    }
                },
                "clusterReceiver": {
                    "enabled": True,
                    "config": {
                        "receivers": {"k8s_cluster": {}},
                        "processors": {
                            "memory_limiter": {},
                            "batch": {},
                            "k8sattributes": {},
                        },
                        "exporters": {"signalfx": {}},
                        "service": {
                            "pipelines": {
                                "metrics": {
                                    "receivers": ["k8s_cluster"],
                                    "processors": [
                                        "memory_limiter",
                                        "batch",
                                        "k8sattributes",
                                    ],
                                    "exporters": ["signalfx"],
                                }
                            }
                        },
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    result = run_setup(
        "--render",
        "--validate",
        "--spec",
        str(spec),
        "--base-values",
        str(base_values),
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, combined_output(result)
    merged = load_yaml(output / "k8s/values.dbmon.merged.yaml")
    assert "otlp" in merged["agent"]["config"]["receivers"]
    metrics = merged["clusterReceiver"]["config"]["service"]["pipelines"]["metrics"]
    logs = merged["clusterReceiver"]["config"]["service"]["pipelines"]["logs/dbmon"]
    assert "k8s_cluster" in metrics["receivers"]
    assert "postgresql/orders_postgres" in metrics["receivers"]
    assert metrics["processors"][:3] == ["memory_limiter", "batch", "k8sattributes"]
    assert "resourcedetection" in metrics["processors"]
    assert logs["processors"] == metrics["processors"]
    assert logs["exporters"] == ["otlphttp/dbmon"]
    assert "signalfx" in metrics["exporters"]


def test_base_values_merge_rejects_db_receivers_under_agent(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    base_values = tmp_path / "base-values.json"
    base_values.write_text(
        json.dumps(
            {
                "agent": {
                    "config": {
                        "receivers": {
                            "postgresql/wrong_place": {
                                "endpoint": "bad.example.internal:5432"
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    result = run_setup(
        "--render",
        "--validate",
        "--spec",
        str(spec),
        "--base-values",
        str(base_values),
        "--output-dir",
        str(output),
    )
    assert result.returncode == 1
    assert "must not place DB receivers under agent" in combined_output(result)


def test_live_validation_accepts_current_cluster_receiver_selector(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    render = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert render.returncode == 0, combined_output(render)
    env, args_file = fake_kubectl_env(tmp_path, "dbmon pipeline healthy")

    result = run_validate(output, "--live", "--live-since", "30s", env=env)

    assert result.returncode == 0, combined_output(result)
    assert "dbmon pipeline healthy" in combined_output(result)
    assert "otel-k8s-cluster-receiver,k8s-cluster-receiver" in args_file.read_text(
        encoding="utf-8"
    )


def test_live_validation_fails_on_recent_dbmon_errors(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    render = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert render.returncode == 0, combined_output(render)
    env, _ = fake_kubectl_env(
        tmp_path,
        "postgresqlreceiver error dial tcp 10.100.2.88:5432: connect: operation not permitted",
    )

    result = run_validate(output, "--live", "--live-since", "30s", env=env)

    assert result.returncode == 1
    assert "Recent DBMon collector log lines include errors" in combined_output(result)


def test_api_probe_checks_metric_catalog_and_signalflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("TOKEN_SHOULD_NOT_PRINT", encoding="utf-8")
    metadata = tmp_path / "metadata.json"
    metadata.write_text(
        json.dumps({"realm": "us1", "cluster_name": "isovalent-demo"}),
        encoding="utf-8",
    )
    requests = []

    def fake_urlopen(request, timeout: int):  # type: ignore[no-untyped-def]
        requests.append((request, timeout))
        if "/v2/metric?" in request.full_url:
            assert "TOKEN_SHOULD_NOT_PRINT" not in request.full_url
            return FakeResponse(
                json.dumps(
                    {
                        "count": 1,
                        "results": [{"name": "postgresql.database.count"}],
                    }
                )
            )
        assert request.full_url.startswith("https://stream.us1.signalfx.com")
        assert request.get_header("Content-type") == "text/plain"
        assert b"TOKEN_SHOULD_NOT_PRINT" not in request.data
        return FakeResponse(
            """
event: metadata
data: {
data:   "properties" : {
data:     "sf_originatingMetric" : "postgresql.database.count"
data:   }
data: }

event: data
data: {"data":[{"value":1}]}
"""
        )

    monkeypatch.setattr(dbmon_api_probe.urllib.request, "urlopen", fake_urlopen)
    result = dbmon_api_probe.run(
        [
            "--metadata",
            str(metadata),
            "--token-file",
            str(token_file),
            "--lookback-seconds",
            "60",
        ]
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "TOKEN_SHOULD_NOT_PRINT" not in output
    payload = json.loads(output)
    assert payload["metric"] == "postgresql.database.count"
    assert payload["filters"] == [{"key": "k8s.cluster.name", "value": "isovalent-demo"}]
    assert payload["metric_catalog"]["matches"] == 1
    assert payload["signalflow"]["metadata_seen"] is True
    assert len(requests) == 2


def test_api_probe_fails_when_signalflow_has_no_matching_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("TOKEN_SHOULD_NOT_PRINT", encoding="utf-8")
    metadata = tmp_path / "metadata.json"
    metadata.write_text(
        json.dumps({"realm": "us1", "cluster_name": "isovalent-demo"}),
        encoding="utf-8",
    )

    def fake_urlopen(request, timeout: int):  # type: ignore[no-untyped-def]
        if "/v2/metric?" in request.full_url:
            return FakeResponse(
                json.dumps(
                    {
                        "count": 1,
                        "results": [{"name": "postgresql.database.count"}],
                    }
                )
            )
        return FakeResponse("event: control-message\ndata: {}\n")

    monkeypatch.setattr(dbmon_api_probe.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(dbmon_api_probe.ApiProbeError):
        dbmon_api_probe.run(
            [
                "--metadata",
                str(metadata),
                "--token-file",
                str(token_file),
                "--lookback-seconds",
                "60",
            ]
        )
    assert "TOKEN_SHOULD_NOT_PRINT" not in capsys.readouterr().err


def test_rendered_output_never_contains_supplied_secret_value(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    text = rendered_text(output)
    assert "PLACEHOLDER_PASSWORD" in text
    assert "INLINE_SHOULD_NOT_LEAK" not in text
