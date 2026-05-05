#!/usr/bin/env python3
"""Regression tests for splunk-observability-ai-agent-monitoring-setup."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.regression_helpers import REPO_ROOT


SKILL = "skills/splunk-observability-ai-agent-monitoring-setup/scripts/setup.sh"


def run_setup(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["bash", str(REPO_ROOT / SKILL), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_ai_agent_monitoring_render_validate_outputs_complete_tree(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    run_setup("--render", "--validate", "--realm", "us0", "--output-dir", str(output_dir))

    required = [
        "coverage-report.json",
        "coverage-report.md",
        "apply-plan.json",
        "handoff.md",
        "doctor-report.md",
        "runtime/python.env",
        "runtime/requirements.txt",
        "collector/values-ai-agent-monitoring.yaml",
        "collector/splunk-hec-logs-overlay.yaml",
        "kubernetes/deployment-env-patch.yaml",
    ]
    for rel in required:
        assert (output_dir / rel).is_file(), rel

    values = (output_dir / "collector/values-ai-agent-monitoring.yaml").read_text()
    assert "send_otlp_histograms: true" in values
    assert "correlation: true" not in values

    runtime_env = (output_dir / "runtime/python.env").read_text()
    assert "$(" not in runtime_env
    assert "OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317" in runtime_env
    k8s_patch = (output_dir / "kubernetes/deployment-env-patch.yaml").read_text()
    assert "kind: Deployment" in k8s_patch
    assert k8s_patch.count("name: SPLUNK_OTEL_AGENT") == 1
    assert "        - name: app" in k8s_patch
    assert 'value: "http://$(SPLUNK_OTEL_AGENT):4317"' in k8s_patch
    k8s_script = (output_dir / "scripts/apply-kubernetes-runtime.sh").read_text()
    assert "kubectl -n 'default' patch 'deployment' 'ai-agent-service'" in k8s_script
    assert "--dry-run=server" in k8s_script

    coverage = json.loads((output_dir / "coverage-report.json").read_text())["coverage"]
    assert coverage
    assert all(entry["status"] != "unknown" for entry in coverage)
    assert all(entry["source_url"] for entry in coverage)


def test_ai_agent_monitoring_coverage_includes_current_ai_infra_catalog(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    run_setup("--render", "--realm", "us0", "--output-dir", str(output_dir))
    coverage = json.loads((output_dir / "coverage-report.json").read_text())["coverage"]
    keys = {entry["key"] for entry in coverage}

    expected_products = {
        "agentgateway_llm_proxy",
        "amazon_bedrock",
        "amazon_bedrock_agentcore_gateway",
        "azure_openai",
        "cisco_ai_pods",
        "kong_ai_gateway_proxy",
        "chromadb",
        "gcp_vertexai",
        "kserve",
        "kubeflow_pipelines",
        "litellm_proxy",
        "milvus",
        "nvidia_gpu",
        "nvidia_nim",
        "openai",
        "pinecone",
        "ray",
        "seldon_core",
        "tensorflow_serving",
        "weaviate",
    }
    assert {f"ai_infra.{name}" for name in expected_products}.issubset(keys)


def test_ai_agent_monitoring_apply_plan_uses_existing_child_skill_flags(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    run_setup("--render", "--realm", "us0", "--output-dir", str(output_dir))
    plan = json.loads((output_dir / "apply-plan.json").read_text())
    commands = {" ".join(step["command"]) for step in plan["steps"]}
    joined = "\n".join(commands)

    assert "splunk-observability-otel-collector-setup/scripts/setup.sh --apply-k8s" in joined
    assert "--extra-values-file" in joined
    assert str(output_dir / "collector" / "values-ai-agent-monitoring.yaml") in joined
    assert "--deployment-environment prod" in joined
    assert "splunk-hec-service-setup/scripts/setup.sh --platform enterprise --phase apply" in joined
    assert "splunk-observability-cloud-integration-setup/scripts/setup.sh --apply log_observer_connect" in joined
    assert str(output_dir / "delegated" / "hec-service") in joined
    assert str(output_dir / "delegated" / "cloud-integration-loc") in joined
    assert str(output_dir / "delegated" / "dashboards") in joined
    assert str(output_dir / "delegated" / "native-ops") in joined
    assert "--apply collector" not in joined
    assert " --token " not in f" {joined} "
    assert " --access-token " not in f" {joined} "
    assert " --api-token " not in f" {joined} "
    assert " --o11y-token " not in f" {joined} "
    assert " --hec-token " not in f" {joined} "


def test_ai_agent_monitoring_apply_dry_run_renders_then_skips_execution(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    result = run_setup("--apply", "python-runtime", "--dry-run", "--realm", "us0", "--output-dir", str(output_dir))

    assert "DRY RUN:" in result.stdout
    assert (output_dir / "scripts/apply-python-runtime.sh").is_file()


def test_ai_agent_monitoring_default_apply_order_runs_hec_before_collector(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    result = run_setup("--apply", "--dry-run", "--realm", "us0", "--output-dir", str(output_dir))

    hec = result.stdout.index("==> applying section: hec")
    collector = result.stdout.index("==> applying section: collector")
    assert hec < collector


def test_ai_agent_monitoring_platform_hec_token_file_is_shared_with_hec_child(tmp_path: Path) -> None:
    output_dir = tmp_path / "enterprise"
    token_path = tmp_path / "platform-hec-token"
    run_setup(
        "--render",
        "--realm",
        "us0",
        "--platform-hec-token-file",
        str(token_path),
        "--output-dir",
        str(output_dir),
    )
    enterprise_plan = json.loads((output_dir / "apply-plan.json").read_text())
    enterprise_hec = next(step for step in enterprise_plan["steps"] if step["section"] == "hec")
    enterprise_collector = next(step for step in enterprise_plan["steps"] if step["section"] == "collector")
    assert ["--token-file", str(token_path)] == enterprise_hec["command"][-2:]
    assert ["--platform-hec-token-file", str(token_path)] == enterprise_collector["command"][-2:]

    spec = {
        "api_version": "splunk-observability-ai-agent-monitoring-setup/v1",
        "realm": "us0",
        "ai_agent_monitoring": {"hec": {"platform": "cloud"}},
    }
    spec_path = tmp_path / "cloud-hec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    cloud_output = tmp_path / "cloud"
    run_setup(
        "--render",
        "--spec",
        str(spec_path),
        "--platform-hec-token-file",
        str(token_path),
        "--output-dir",
        str(cloud_output),
    )
    cloud_plan = json.loads((cloud_output / "apply-plan.json").read_text())
    cloud_hec = next(step for step in cloud_plan["steps"] if step["section"] == "hec")
    assert ["--write-token-file", str(token_path)] == cloud_hec["command"][-2:]


def test_ai_agent_monitoring_custom_kubernetes_workload_target(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    run_setup(
        "--render",
        "--realm",
        "us0",
        "--workload-kind",
        "statefulset",
        "--workload-namespace",
        "agents",
        "--workload-name",
        "agent-worker",
        "--container-name",
        "worker",
        "--output-dir",
        str(output_dir),
    )

    k8s_patch = (output_dir / "kubernetes/deployment-env-patch.yaml").read_text()
    assert "kind: StatefulSet" in k8s_patch
    assert "  name: agent-worker" in k8s_patch
    assert "        - name: worker" in k8s_patch
    k8s_script = (output_dir / "scripts/apply-kubernetes-runtime.sh").read_text()
    assert "kubectl -n 'agents' patch 'statefulset' 'agent-worker'" in k8s_script


def test_ai_agent_monitoring_rejects_invalid_kubernetes_workload_kind(tmp_path: Path) -> None:
    result = run_setup(
        "--render",
        "--realm",
        "us0",
        "--workload-kind",
        "cronjob",
        "--json",
        "--output-dir",
        str(tmp_path / "rendered"),
        check=False,
    )

    assert result.returncode != 0
    assert "deployment.workload_kind" in result.stdout


def test_ai_agent_monitoring_rejects_equals_form_direct_secret_flags(tmp_path: Path) -> None:
    result = run_setup("--render", "--token=abc123", "--output-dir", str(tmp_path / "rendered"), check=False)

    assert result.returncode != 0
    assert "would expose a secret" in result.stdout + result.stderr


def test_ai_agent_monitoring_disabled_apply_sections_render_noop_scripts(tmp_path: Path) -> None:
    spec = {
        "api_version": "splunk-observability-ai-agent-monitoring-setup/v1",
        "realm": "us0",
        "ai_agent_monitoring": {
            "hec": {"enabled": False},
            "log_observer_connect": {"enabled": False},
        },
        "dashboards": {"enabled": False},
        "detectors": {"enabled": False},
    }
    spec_path = tmp_path / "disabled-sections.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    output_dir = tmp_path / "rendered"
    run_setup("--render", "--spec", str(spec_path), "--realm", "us0", "--output-dir", str(output_dir))
    plan = json.loads((output_dir / "apply-plan.json").read_text())
    by_section = {step["section"]: step for step in plan["steps"]}

    for section in ("hec", "loc", "dashboards", "detectors"):
        assert by_section[section]["coverage"] == "not_applicable"
        assert by_section[section]["command"] == ["bash", str(output_dir / "scripts" / f"apply-{section}.sh")]
        script = (output_dir / "scripts" / f"apply-{section}.sh").read_text()
        assert "no live changes made" in script


def test_ai_agent_monitoring_privacy_and_histogram_gates_fail(tmp_path: Path) -> None:
    histogram = run_setup(
        "--render",
        "--realm",
        "us0",
        "--output-dir",
        str(tmp_path / "histogram"),
        "--send-otlp-histograms",
        "false",
        "--json",
        check=False,
    )
    assert histogram.returncode != 0
    assert "send_otlp_histograms must be true" in histogram.stdout

    content = run_setup(
        "--render",
        "--realm",
        "us0",
        "--output-dir",
        str(tmp_path / "content"),
        "--enable-content-capture",
        "--json",
        check=False,
    )
    assert content.returncode != 0
    assert "Content capture requires" in content.stdout

    evals = run_setup(
        "--render",
        "--realm",
        "us0",
        "--output-dir",
        str(tmp_path / "evals"),
        "--enable-evaluations",
        "--json",
        check=False,
    )
    assert evals.returncode != 0
    assert "evaluations require" in evals.stdout


def test_ai_agent_monitoring_blocks_bad_package_names(tmp_path: Path) -> None:
    spec = {
        "api_version": "splunk-observability-ai-agent-monitoring-setup/v1",
        "realm": "us0",
        "ai_agent_monitoring": {
            "python_version": "3.10",
            "frameworks": ["openai"],
            "additional_packages": ["splunk-otel-instrumentation-openai-v2"],
        },
    }
    spec_path = tmp_path / "bad-package.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    result = run_setup(
        "--render",
        "--spec",
        str(spec_path),
        "--output-dir",
        str(tmp_path / "bad-package-rendered"),
        "--json",
        check=False,
    )
    assert result.returncode != 0
    assert "splunk-otel-instrumentation-openai-v2" in result.stdout
