#!/usr/bin/env python3
"""Focused production-boundary regressions for lemonade-splunk-otel."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "skills/lemonade-splunk-otel"
RENDERER = SKILL / "scripts/render_collector_config.py"
VALIDATOR = SKILL / "scripts/validate.sh"
CANARY = SKILL / "scripts/send_genai_canary.py"


def test_docs_require_least_privilege_token_rotation_transaction() -> None:
    skill_text = " ".join(
        (SKILL / "SKILL.md").read_text(encoding="utf-8").lower().split()
    )
    keychain_text = " ".join(
        (SKILL / "references/keychain.md")
        .read_text(encoding="utf-8")
        .lower()
        .replace("`", "")
        .replace("*", "")
        .split()
    )

    assert "separate least-privilege splunk organization tokens" in skill_text
    assert "combined api-and-ingest token is not production-ready" in skill_text
    assert "reject literal credential-bearing yaml fields" in skill_text
    for required in (
        "ingest-scoped token",
        "api-scoped token",
        "read_only",
        "user api session token",
        "grace period",
        "accepted/sent deltas",
        "empty exporter queues",
        "backend readback",
        "old secret to be rejected",
        "do not deactivate the last working token",
        "rotation changes only the secret",
        "does not split or change",
        "expiration-alert owner",
        "cutover budget plus validation budget plus rollback budget",
        "collector counters alone are not sufficient",
        "inventory state alone is insufficient",
        "transactional_splunk_token.py",
        "--private-artifact",
        "never a token value",
    ):
        assert required in keychain_text


def test_validation_docs_fail_closed_on_ai_monitoring_metric_claims() -> None:
    validation_text = " ".join(
        (SKILL / "references/validation.md").read_text(encoding="utf-8").lower().split()
    )
    for required in (
        "native telemetry emits traces, not otlp metrics",
        "send_otlp_histograms: true",
        "does not synthesize them from spans",
        "gen_ai.client.operation.duration",
        "gen_ai.client.token.usage",
        "backend metric evidence",
        "signed-in ui",
        "is not sufficient evidence",
    ):
        assert required in validation_text


@pytest.mark.parametrize(
    ("container", "field"),
    [
        ("exporter", "access_token"),
        ("exporter", "api_key"),
        ("exporter", "token"),
        ("headers", "X-SF-Token"),
        ("headers", "Authorization"),
    ],
)
def test_renderer_rejects_literal_exporter_credentials_without_echoing_them(
    tmp_path: Path, container: str, field: str
) -> None:
    literal = "OFFLINE_LITERAL_CREDENTIAL_MUST_NOT_SURVIVE"
    document = base_document()
    exporter = document["exporters"]["otlphttp"]
    if container == "headers":
        exporter.setdefault("headers", {})[field] = literal
    else:
        exporter[field] = literal

    result, output = render_document(tmp_path, document)
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "credential-bearing collector fields" in combined.lower()
    assert literal not in combined
    assert not output.exists()


@pytest.mark.parametrize(
    "placeholder", ["${SPLUNK_ACCESS_TOKEN}", "${env:SPLUNK_ACCESS_TOKEN}"]
)
def test_renderer_and_validator_accept_exact_secret_placeholders(
    tmp_path: Path, placeholder: str
) -> None:
    document = base_document()
    document["exporters"]["otlphttp"]["headers"] = {"X-SF-Token": placeholder}
    result, output = render_document(tmp_path, document)
    assert result.returncode == 0, result.stdout + result.stderr
    validated = validate(output)
    assert validated.returncode == 0, validated.stdout + validated.stderr


def test_validator_rejects_literal_credential_added_after_render(
    tmp_path: Path,
) -> None:
    result, output = render(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    document = yaml.safe_load(output.read_text(encoding="utf-8"))
    literal = "OFFLINE_POST_RENDER_LITERAL_MUST_NOT_SURVIVE"
    document["exporters"]["otlphttp"]["headers"] = {"X-SF-Token": literal}
    write_yaml(output, document)

    validated = validate(output)
    combined = validated.stdout + validated.stderr
    assert validated.returncode != 0
    assert "credential-bearing Collector fields" in combined
    assert literal not in combined


def base_document() -> dict[str, Any]:
    return {
        "receivers": {
            "otlp": {
                "protocols": {
                    "grpc": {"endpoint": "127.0.0.1:4317"},
                    "http": {"endpoint": "127.0.0.1:4318"},
                }
            }
        },
        "processors": {
            "memory_limiter": {},
            "resourcedetection": {"detectors": ["env", "system"]},
            "batch": {},
        },
        "exporters": {"otlphttp": {"endpoint": "https://example.invalid"}},
        "service": {
            "pipelines": {
                "traces": {
                    "receivers": ["otlp"],
                    "processors": ["memory_limiter", "resourcedetection", "batch"],
                    "exporters": ["otlphttp"],
                }
            }
        },
    }


def base_document_with_logs() -> dict[str, Any]:
    document = base_document()
    document["service"]["pipelines"]["logs"] = {
        "receivers": ["otlp"],
        "processors": ["memory_limiter", "resourcedetection", "batch"],
        "exporters": ["otlphttp"],
    }
    return document


def legacy_resource_component() -> dict[str, Any]:
    return {
        "attributes": [
            {"key": "service.name", "value": "lemonade-server", "action": "insert"},
            {
                "key": "deployment.environment.name",
                "value": "legacy-dev",
                "action": "insert",
            },
            {
                "key": "deployment.environment",
                "value": "legacy-dev",
                "action": "insert",
            },
        ]
    }


def add_recognized_legacy_render(document: dict[str, Any]) -> None:
    document["processors"]["resource/lemonade"] = legacy_resource_component()
    for pipeline_name in ("traces", "logs"):
        document["service"]["pipelines"][pipeline_name]["processors"].append(
            "resource/lemonade"
        )


def write_yaml(path: Path, document: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def render(
    tmp_path: Path, *extra: str
) -> tuple[subprocess.CompletedProcess[str], Path]:
    return render_document(tmp_path, base_document(), *extra)


def render_document(
    tmp_path: Path,
    document: dict[str, Any],
    *extra: str,
    output_name: str = "rendered.yaml",
) -> tuple[subprocess.CompletedProcess[str], Path]:
    base = tmp_path / "base.yaml"
    output = tmp_path / output_name
    write_yaml(base, document)
    result = subprocess.run(
        [
            sys.executable,
            str(RENDERER),
            "--base",
            str(base),
            "--output",
            str(output),
            "--deployment-environment",
            "ryzen-halo-dev",
            *extra,
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, output


def validate(
    path: Path, *extra: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ) if env is None else dict(env)
    environment["PATH"] = f"{Path(sys.executable).parent}:{environment.get('PATH', '')}"
    return subprocess.run(
        ["bash", str(VALIDATOR), "--collector-config", str(path), *extra],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )


def run_canary(
    endpoint: str, *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CANARY), "--endpoint", endpoint],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
        timeout=15,
    )


def test_setup_help_is_actionable_and_names_pyyaml() -> None:
    result = subprocess.run(
        ["bash", str(SKILL / "scripts/setup.sh"), "--help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    help_text = (result.stdout + result.stderr).lower()
    assert "render-only" in help_text
    assert "pyyaml" in help_text

    validator_help = subprocess.run(
        ["bash", str(VALIDATOR), "--help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert validator_help.returncode == 0
    assert "pyyaml" in (validator_help.stdout + validator_help.stderr).lower()


@pytest.mark.parametrize(
    ("option", "value", "message"),
    [
        ("--deployment-environment", "   ", "non-empty"),
        ("--service-name", "lemonade\nserver", "control characters"),
        ("--unit", "lemond\t.service", "control characters"),
        ("--traces-pipeline", "\x7ftraces", "control characters"),
        ("--logs-pipeline", "", "non-empty"),
    ],
)
def test_renderer_rejects_empty_or_control_bearing_scalars(
    tmp_path: Path, option: str, value: str, message: str
) -> None:
    result, _ = render(tmp_path, option, value)
    assert result.returncode != 0
    assert message in result.stderr


def test_legacy_migration_rejects_dangling_reference(tmp_path: Path) -> None:
    document = base_document()
    document["service"]["pipelines"]["traces"]["processors"].insert(
        -1, "resource/lemonade"
    )
    base = tmp_path / "base.yaml"
    output = tmp_path / "output.yaml"
    write_yaml(base, document)
    result = subprocess.run(
        [
            sys.executable,
            str(RENDERER),
            "--base",
            str(base),
            "--output",
            str(output),
            "--deployment-environment",
            "new-dev",
            "--migrate-legacy-lemonade-renderer",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "dangling" in result.stderr


@pytest.mark.parametrize(
    "mutate",
    [
        lambda component: component.update({"unexpected": True}),
        lambda component: component["attributes"][0].update({"unexpected": True}),
        lambda component: component["attributes"][0].update({"value": "other-service"}),
        lambda component: component["attributes"][1].update({"value": "different-dev"}),
        lambda component: component.clear(),
    ],
)
def test_legacy_migration_rejects_unknown_shape_or_values(
    tmp_path: Path, mutate: Any
) -> None:
    document = base_document_with_logs()
    component = legacy_resource_component()
    mutate(component)
    document["processors"]["resource/lemonade"] = component
    for pipeline_name in ("traces", "logs"):
        document["service"]["pipelines"][pipeline_name]["processors"].append(
            "resource/lemonade"
        )
    base = tmp_path / "base.yaml"
    output = tmp_path / "output.yaml"
    write_yaml(base, document)
    result = subprocess.run(
        [
            sys.executable,
            str(RENDERER),
            "--base",
            str(base),
            "--output",
            str(output),
            "--deployment-environment",
            "new-dev",
            "--migrate-legacy-lemonade-renderer",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "resource/lemonade" in result.stderr or "legacy component" in result.stderr


def test_legacy_migration_accepts_only_recognized_shape_and_safe_values(
    tmp_path: Path,
) -> None:
    document = base_document_with_logs()
    add_recognized_legacy_render(document)
    base = tmp_path / "base.yaml"
    output = tmp_path / "output.yaml"
    write_yaml(base, document)
    result = subprocess.run(
        [
            sys.executable,
            str(RENDERER),
            "--base",
            str(base),
            "--output",
            str(output),
            "--deployment-environment",
            "new-dev",
            "--migrate-legacy-lemonade-renderer",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    migrated = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert "resource/lemonade" not in migrated["processors"]
    assert (
        "resource/lemonade"
        not in migrated["service"]["pipelines"]["traces"]["processors"]
    )
    assert (
        "resource/lemonade"
        not in migrated["service"]["pipelines"]["logs"]["processors"]
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_log_reference",
        "duplicate_trace_reference",
        "wrong_field_reference",
        "metrics_pipeline_reference",
        "foreign_pipeline_reference",
        "unreferenced_component",
        "wrong_index",
    ],
)
def test_legacy_migration_rejects_nonexact_reference_topology(
    tmp_path: Path, mutation: str
) -> None:
    document = base_document_with_logs()
    add_recognized_legacy_render(document)
    pipelines = document["service"]["pipelines"]
    if mutation == "missing_log_reference":
        pipelines["logs"]["processors"].remove("resource/lemonade")
    elif mutation == "duplicate_trace_reference":
        pipelines["traces"]["processors"].append("resource/lemonade")
    elif mutation == "wrong_field_reference":
        pipelines["traces"]["exporters"].append("resource/lemonade")
    elif mutation == "metrics_pipeline_reference":
        pipelines["metrics"] = {
            "receivers": ["otlp"],
            "processors": ["resource/lemonade", "batch"],
            "exporters": ["otlphttp"],
        }
    elif mutation == "foreign_pipeline_reference":
        pipelines["traces/foreign"] = {
            "receivers": ["otlp"],
            "processors": ["resource/lemonade", "batch"],
            "exporters": ["otlphttp"],
        }
    elif mutation == "unreferenced_component":
        for pipeline_name in ("traces", "logs"):
            pipelines[pipeline_name]["processors"].remove("resource/lemonade")
    else:
        pipelines["traces"]["processors"].remove("resource/lemonade")
        pipelines["traces"]["processors"].insert(-1, "resource/lemonade")

    result, _ = render_document(
        tmp_path,
        document,
        "--migrate-legacy-lemonade-renderer",
        output_name="rejected.yaml",
    )
    assert result.returncode != 0
    assert "expected exactly one final processor reference" in result.stderr


@pytest.mark.parametrize("enable_journald", [False, True])
def test_renderer_exact_prior_render_is_idempotent(
    tmp_path: Path, enable_journald: bool
) -> None:
    document = base_document_with_logs() if enable_journald else base_document()
    extra = ("--enable-journald",) if enable_journald else ()
    first, first_path = render_document(
        tmp_path, document, *extra, output_name="first.yaml"
    )
    assert first.returncode == 0, first.stderr
    first_document = yaml.safe_load(first_path.read_text(encoding="utf-8"))

    second, second_path = render_document(
        tmp_path, first_document, *extra, output_name="second.yaml"
    )
    assert second.returncode == 0, second.stderr
    assert yaml.safe_load(second_path.read_text(encoding="utf-8")) == first_document


def test_renderer_safely_updates_and_removes_recognized_prior_render(
    tmp_path: Path,
) -> None:
    first, first_path = render_document(
        tmp_path,
        base_document_with_logs(),
        "--enable-journald",
        output_name="first.yaml",
    )
    assert first.returncode == 0, first.stderr
    prior = yaml.safe_load(first_path.read_text(encoding="utf-8"))

    updated, updated_path = render_document(
        tmp_path,
        prior,
        "--deployment-environment",
        "production",
        "--service-name",
        "lemonade-api",
        "--unit",
        "lemonade.service",
        "--enable-journald",
        output_name="updated.yaml",
    )
    assert updated.returncode == 0, updated.stderr
    document = yaml.safe_load(updated_path.read_text(encoding="utf-8"))
    assert document["receivers"]["journald/lemonade"]["units"] == ["lemonade.service"]
    log_resource = document["processors"]["resource/lemonade_logs"]
    assert "production" in str(log_resource)
    assert "lemonade-api" in str(log_resource)
    privacy = document["processors"]["transform/lemonade_resource_privacy"]
    assert "production" in str(privacy)
    assert "lemonade-api" in str(privacy)

    removed, removed_path = render_document(
        tmp_path,
        document,
        "--deployment-environment",
        "production",
        "--service-name",
        "lemonade-api",
        output_name="removed.yaml",
    )
    assert removed.returncode == 0, removed.stderr
    without_journald = yaml.safe_load(removed_path.read_text(encoding="utf-8"))
    assert "journald/lemonade" not in without_journald["receivers"]
    assert "resource/lemonade_logs" not in without_journald["processors"]
    assert "logs/lemonade" not in without_journald["service"]["pipelines"]


@pytest.mark.parametrize(
    "mutation",
    [
        "tamper_component",
        "unreferenced_component",
        "duplicate_reference",
        "wrong_field_reference",
        "wrong_order",
    ],
)
def test_renderer_rejects_tampered_privacy_prior_render(
    tmp_path: Path, mutation: str
) -> None:
    first, first_path = render_document(
        tmp_path, base_document(), output_name="first.yaml"
    )
    assert first.returncode == 0, first.stderr
    document = yaml.safe_load(first_path.read_text(encoding="utf-8"))
    processors = document["service"]["pipelines"]["traces"]["processors"]
    if mutation == "tamper_component":
        document["processors"]["transform/lemonade_resource_privacy"]["error_mode"] = (
            "ignore"
        )
    elif mutation == "unreferenced_component":
        processors.remove("transform/lemonade_resource_privacy")
    elif mutation == "duplicate_reference":
        processors.insert(0, "transform/lemonade_resource_privacy")
    elif mutation == "wrong_field_reference":
        processors.remove("transform/lemonade_resource_privacy")
        document["service"]["pipelines"]["traces"]["exporters"].append(
            "transform/lemonade_resource_privacy"
        )
    else:
        processors.remove("transform/lemonade_resource_privacy")
        processors.append("transform/lemonade_resource_privacy")

    result, _ = render_document(tmp_path, document, output_name="rejected.yaml")
    assert result.returncode != 0
    assert "collision" in result.stderr


def test_renderer_rejects_exact_privacy_reference_in_wrong_pipeline(
    tmp_path: Path,
) -> None:
    first, first_path = render_document(
        tmp_path, base_document(), output_name="first.yaml"
    )
    assert first.returncode == 0, first.stderr
    document = yaml.safe_load(first_path.read_text(encoding="utf-8"))
    document["service"]["pipelines"]["traces/other"] = {
        "receivers": ["otlp"],
        "processors": ["memory_limiter", "resourcedetection", "batch"],
        "exporters": ["otlphttp"],
    }
    document["service"]["pipelines"]["traces"]["processors"].remove(
        "transform/lemonade_resource_privacy"
    )
    document["service"]["pipelines"]["traces/other"]["processors"].insert(
        -1, "transform/lemonade_resource_privacy"
    )

    result, _ = render_document(tmp_path, document, output_name="rejected.yaml")
    assert result.returncode != 0
    assert "selected pipeline traces" in result.stderr


def test_renderer_refuses_to_silently_move_privacy_to_new_selected_pipeline(
    tmp_path: Path,
) -> None:
    document = base_document()
    document["service"]["pipelines"]["traces/other"] = {
        "receivers": ["otlp"],
        "processors": ["memory_limiter", "resourcedetection", "batch"],
        "exporters": ["otlphttp"],
    }
    first, first_path = render_document(tmp_path, document, output_name="first.yaml")
    assert first.returncode == 0, first.stderr
    prior = yaml.safe_load(first_path.read_text(encoding="utf-8"))

    moved, _ = render_document(
        tmp_path,
        prior,
        "--traces-pipeline",
        "traces/other",
        output_name="rejected.yaml",
    )
    assert moved.returncode != 0
    assert "selected pipeline traces/other" in moved.stderr


def test_renderer_rejects_dangling_privacy_reference(tmp_path: Path) -> None:
    document = base_document()
    document["service"]["pipelines"]["traces"]["processors"].insert(
        -1, "transform/lemonade_resource_privacy"
    )
    result, _ = render_document(tmp_path, document)
    assert result.returncode != 0
    assert "dangling managed reference" in result.stderr


@pytest.mark.parametrize("collision", ["receiver", "processor", "pipeline"])
def test_renderer_rejects_partial_or_foreign_journald_managed_ids(
    tmp_path: Path, collision: str
) -> None:
    document = base_document_with_logs()
    if collision == "receiver":
        document["receivers"]["journald/lemonade"] = {"units": ["foreign.service"]}
    elif collision == "processor":
        document["processors"]["resource/lemonade_logs"] = {"attributes": []}
    else:
        document["service"]["pipelines"]["logs/lemonade"] = {
            "receivers": ["otlp"],
            "processors": ["batch"],
            "exporters": ["otlphttp"],
        }
    result, _ = render_document(tmp_path, document, "--enable-journald")
    assert result.returncode != 0
    assert "managed journald render" in result.stderr


@pytest.mark.parametrize(
    "mutation",
    [
        "receiver_shape",
        "processor_shape",
        "pipeline_shape",
        "receiver_extra_reference",
        "processor_extra_reference",
        "identity_mismatch",
    ],
)
def test_renderer_rejects_tampered_journald_prior_render(
    tmp_path: Path, mutation: str
) -> None:
    first, first_path = render_document(
        tmp_path,
        base_document_with_logs(),
        "--enable-journald",
        output_name="first.yaml",
    )
    assert first.returncode == 0, first.stderr
    document = yaml.safe_load(first_path.read_text(encoding="utf-8"))
    if mutation == "receiver_shape":
        document["receivers"]["journald/lemonade"]["priority"] = "debug"
    elif mutation == "processor_shape":
        document["processors"]["resource/lemonade_logs"]["attributes"][0]["action"] = (
            "insert"
        )
    elif mutation == "pipeline_shape":
        document["service"]["pipelines"]["logs/lemonade"]["exporters"].append("other")
    elif mutation == "receiver_extra_reference":
        document["service"]["pipelines"]["logs"]["receivers"].append(
            "journald/lemonade"
        )
    elif mutation == "processor_extra_reference":
        document["service"]["pipelines"]["logs"]["processors"].append(
            "resource/lemonade_logs"
        )
    else:
        attributes = document["processors"]["resource/lemonade_logs"]["attributes"]
        attributes[1]["value"] = "other-environment"
        attributes[2]["value"] = "other-environment"

    result, _ = render_document(
        tmp_path,
        document,
        "--enable-journald",
        output_name="rejected.yaml",
    )
    assert result.returncode != 0
    assert "managed" in result.stderr


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--traces-pipeline", "logs/lemonade"),
        ("--logs-pipeline", "logs/lemonade"),
    ],
)
def test_renderer_rejects_reserved_managed_pipeline_as_source(
    tmp_path: Path, option: str, value: str
) -> None:
    result, _ = render_document(tmp_path, base_document_with_logs(), option, value)
    assert result.returncode != 0
    assert "reserves the managed pipeline ID" in result.stderr


@pytest.mark.parametrize(
    ("option", "value", "signal"),
    [
        ("--traces-pipeline", "metrics", "traces"),
        ("--logs-pipeline", "metrics", "logs"),
    ],
)
def test_renderer_rejects_wrong_signal_pipeline_selector(
    tmp_path: Path, option: str, value: str, signal: str
) -> None:
    result, _ = render_document(tmp_path, base_document_with_logs(), option, value)
    assert result.returncode != 0
    assert f"must identify a {signal}[/name] pipeline" in result.stderr


def test_validator_accepts_exact_managed_config(tmp_path: Path) -> None:
    rendered, output = render(tmp_path)
    assert rendered.returncode == 0, rendered.stderr
    result = validate(output)
    assert result.returncode == 0, result.stderr
    assert "Static Lemonade collector validation passed" in result.stdout


@pytest.mark.parametrize(
    "mutation", ("privacy", "receiver_port", "receiver_host", "duplicate", "empty")
)
def test_validator_rejects_tampered_managed_boundaries(
    tmp_path: Path, mutation: str
) -> None:
    rendered, output = render(tmp_path)
    assert rendered.returncode == 0, rendered.stderr
    document = yaml.safe_load(output.read_text(encoding="utf-8"))
    if mutation == "privacy":
        statements = document["processors"]["transform/lemonade_resource_privacy"][
            "trace_statements"
        ][0]["statements"]
        statements[0], statements[1] = statements[1], statements[0]
    elif mutation == "receiver_port":
        document["receivers"]["otlp"]["protocols"]["grpc"]["endpoint"] = (
            "127.0.0.1:70000"
        )
    elif mutation == "receiver_host":
        document["receivers"]["otlp"]["protocols"]["http"]["endpoint"] = "0.0.0.0:4318"
    elif mutation == "duplicate":
        document["service"]["pipelines"]["traces"]["exporters"].append("otlphttp")
    else:
        document["service"]["pipelines"]["traces"]["receivers"] = []
    write_yaml(output, document)
    result = validate(output)
    assert result.returncode != 0


def test_validator_requires_every_selected_protocol_endpoint(tmp_path: Path) -> None:
    rendered, output = render(tmp_path)
    assert rendered.returncode == 0, rendered.stderr
    document = yaml.safe_load(output.read_text(encoding="utf-8"))
    document["receivers"]["otlp"]["protocols"]["grpc"] = {}
    write_yaml(output, document)
    result = validate(output)
    assert result.returncode != 0
    assert "explicit endpoint" in result.stderr


def test_production_validation_requires_exact_absolute_collector_binary(
    tmp_path: Path,
) -> None:
    rendered, output = render(tmp_path)
    assert rendered.returncode == 0, rendered.stderr
    missing = validate(output, "--production")
    assert missing.returncode != 0
    assert "requires --collector-binary" in missing.stderr

    relative = validate(
        output,
        "--production",
        "--collector-binary",
        "otelcol",
    )
    assert relative.returncode != 0
    assert "absolute" in relative.stderr

    mock = tmp_path / "otelcol"
    args_file = tmp_path / "collector-args.json"
    mock.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "open(os.environ['ARGS_FILE'], 'w', encoding='utf-8').write(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    mock.chmod(0o700)
    environment = dict(os.environ)
    environment["ARGS_FILE"] = str(args_file)
    accepted = validate(
        output,
        "--production",
        "--collector-binary",
        str(mock),
        env=environment,
    )
    assert accepted.returncode == 0, accepted.stderr
    assert json.loads(args_file.read_text(encoding="utf-8")) == [
        "validate",
        f"--config={output}",
    ]


class _CanaryHandler(BaseHTTPRequestHandler):
    body = b"{}"
    status = 200
    location = ""
    hits = 0

    def do_POST(self) -> None:  # noqa: N802
        type(self).hits += 1
        content_length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(content_length)
        self.send_response(type(self).status)
        if type(self).location:
            self.send_header("Location", type(self).location)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(type(self).body)))
        self.end_headers()
        self.wfile.write(type(self).body)

    def do_GET(self) -> None:  # noqa: N802
        type(self).hits += 1
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args: object) -> None:
        return


def start_server(
    handler: type[BaseHTTPRequestHandler],
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop_server(server: ThreadingHTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://user@127.0.0.1:4318/v1/traces",
        "http://127.0.0.1:4318/v1/traces?debug=1",
        "http://127.0.0.1:4318/v1/traces?",
        "http://127.0.0.1:4318/v1/traces#fragment",
        "http://127.0.0.1:4318/v1/traces#",
        "http://127.0.0.1:4318/other",
        "http://127.0.0.1:70000/v1/traces",
        "http://127.0.0.1/v1/traces",
    ],
)
def test_canary_rejects_non_exact_receiver_urls(endpoint: str) -> None:
    result = run_canary(endpoint)
    assert result.returncode != 0
    assert "--endpoint" in result.stderr


def test_canary_accepts_exact_success_and_bypasses_proxy() -> None:
    class Handler(_CanaryHandler):
        body = b"{}"
        hits = 0

    server, thread = start_server(Handler)
    try:
        environment = dict(os.environ)
        environment.update(
            {
                "HTTP_PROXY": "http://127.0.0.1:1",
                "http_proxy": "http://127.0.0.1:1",
                "NO_PROXY": "",
                "no_proxy": "",
            }
        )
        result = run_canary(
            f"http://127.0.0.1:{server.server_port}/v1/traces", env=environment
        )
    finally:
        stop_server(server, thread)
    assert result.returncode == 0, result.stderr
    assert Handler.hits == 1
    assert "TRACE_ID=" in result.stdout
    assert "CREATED_AFTER=" in result.stdout
    assert "CREATED_BEFORE=" in result.stdout


@pytest.mark.parametrize(
    "response",
    [
        {"partialSuccess": {"rejectedSpans": "0"}},
        {"partial_success": {"rejected_spans": 0}},
        {"partialSuccess": {}},
    ],
)
def test_canary_surfaces_zero_rejection_partial_success_as_evidence(
    response: dict[str, Any],
) -> None:
    class Handler(_CanaryHandler):
        body = json.dumps(response).encode("utf-8")

    server, thread = start_server(Handler)
    try:
        result = run_canary(f"http://127.0.0.1:{server.server_port}/v1/traces")
    finally:
        stop_server(server, thread)
    assert result.returncode == 0, result.stderr
    assert "OTLP_PARTIAL_SUCCESS_PRESENT=true" in result.stdout


@pytest.mark.parametrize(
    "response",
    [
        {"partialSuccess": {"errorMessage": "review this warning"}},
        {"partialSuccess": None},
    ],
)
def test_canary_rejects_partial_success_warnings_or_invalid_shapes(
    response: dict[str, Any],
) -> None:
    class Handler(_CanaryHandler):
        body = json.dumps(response).encode("utf-8")

    server, thread = start_server(Handler)
    try:
        result = run_canary(f"http://127.0.0.1:{server.server_port}/v1/traces")
    finally:
        stop_server(server, thread)
    assert result.returncode != 0
    assert "partialSuccess" in result.stderr
    assert "review this warning" not in result.stderr


def test_canary_refuses_redirects() -> None:
    class Target(_CanaryHandler):
        hits = 0

    target, target_thread = start_server(Target)

    class Redirect(_CanaryHandler):
        status = 302
        location = f"http://127.0.0.1:{target.server_port}/v1/traces"
        hits = 0

    redirect, redirect_thread = start_server(Redirect)
    try:
        result = run_canary(f"http://127.0.0.1:{redirect.server_port}/v1/traces")
    finally:
        stop_server(redirect, redirect_thread)
        stop_server(target, target_thread)
    assert result.returncode != 0
    assert Redirect.hits == 1
    assert Target.hits == 0


def test_canary_rejects_oversized_and_rejected_span_responses() -> None:
    class Oversized(_CanaryHandler):
        body = b"x" * (1024 * 1024 + 1)

    oversized, oversized_thread = start_server(Oversized)
    try:
        too_large = run_canary(f"http://127.0.0.1:{oversized.server_port}/v1/traces")
    finally:
        stop_server(oversized, oversized_thread)
    assert too_large.returncode != 0
    assert "size limit" in too_large.stderr

    class Rejected(_CanaryHandler):
        body = b'{"partial_success":{"rejected_spans":"2"}}'

    rejected, rejected_thread = start_server(Rejected)
    try:
        refused = run_canary(f"http://127.0.0.1:{rejected.server_port}/v1/traces")
    finally:
        stop_server(rejected, rejected_thread)
    assert refused.returncode != 0
    assert "rejected 2 span" in refused.stderr


@pytest.mark.parametrize(
    ("status", "content_type", "body", "expected"),
    [
        (201, "application/json", b"{}", "HTTP 201"),
        (200, "text/plain", b"{}", "non-JSON content"),
        (200, "application/json", b"", "empty response"),
        (200, "application/json", b"[]", "JSON object"),
        (200, "application/json", b"not-json", "non-JSON content"),
        (200, "application/json", b'{"bad":NaN}', "non-JSON content"),
    ],
)
def test_canary_requires_exact_otlp_json_success(
    status: int, content_type: str, body: bytes, expected: str
) -> None:
    class Handler(_CanaryHandler):
        pass

    Handler.status = status
    Handler.body = body

    class ContentTypeHandler(Handler):
        def do_POST(self) -> None:  # noqa: N802
            content_length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(content_length)
            self.send_response(type(self).status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(type(self).body)))
            self.end_headers()
            self.wfile.write(type(self).body)

    server, thread = start_server(ContentTypeHandler)
    try:
        result = run_canary(f"http://127.0.0.1:{server.server_port}/v1/traces")
    finally:
        stop_server(server, thread)
    assert result.returncode != 0
    assert expected in result.stderr
