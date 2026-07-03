"""Offline coverage for the AWS/EKS/O11y staging workflow and renderer."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github/workflows/aws-eks-o11y-staging.yml"
RENDERER = REPO_ROOT / "scripts/staging/render-aws-eks-o11y.py"
RBAC_TEMPLATE = REPO_ROOT / "scripts/staging/aws-eks-o11y-rbac.template.yaml"


def _github_action_references(node: object) -> list[str]:
    references: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "uses":
                assert isinstance(value, str), "GitHub Action `uses` value must be a string"
                references.append(value)
            references.extend(_github_action_references(value))
    elif isinstance(node, list):
        for value in node:
            references.extend(_github_action_references(value))
    return references


def _render_command(tmp_path: Path, token: Path) -> list[str]:
    return [
        sys.executable,
        str(RENDERER),
        "--output-root",
        str(tmp_path / "rendered"),
        "--token-file",
        str(token),
        "--aws-account-id",
        "123456789012",
        "--aws-region",
        "us-east-1",
        "--eks-cluster-name",
        "observability-staging",
        "--kube-context",
        "aws-eks-o11y-staging",
        "--o11y-realm",
        "us1",
        "--aws-integration-name",
        "observability-staging",
        "--collector-namespace",
        "splunk-otel",
        "--collector-release",
        "splunk-otel-collector",
        "--instrumentation-name",
        "splunk-otel-staging",
        "--namespace",
        "staging",
        "--workload",
        "Deployment/checkout-api",
        "--language",
        "java",
    ]


def _private_token(tmp_path: Path, value: str = "OFFLINE_STAGING_TOKEN_DO_NOT_EMBED") -> Path:
    token = tmp_path / "token"
    token.write_text(value, encoding="utf-8")
    token.chmod(0o600)
    return token


def test_workflow_is_manual_approved_read_only_and_immutably_pinned() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    payload = yaml.load(text, Loader=yaml.BaseLoader)

    assert set(payload["on"]) == {"workflow_dispatch"}
    assert payload["permissions"] == {"contents": "read", "id-token": "write"}
    job = payload["jobs"]["acceptance"]
    assert job["environment"] == "aws-eks-o11y-staging"
    assert job["timeout-minutes"] == "30"
    assert job["runs-on"] == "ubuntu-24.04"
    assert len(payload["on"]["workflow_dispatch"]["inputs"]) == 10
    assert payload["on"]["workflow_dispatch"]["inputs"]["language"]["options"] == [
        "java",
        "nodejs",
        "python",
        "dotnet",
        "go",
        "apache-httpd",
        "nginx",
    ]

    oidc_step = next(step for step in job["steps"] if step["name"] == "Assume read-only staging role with OIDC")
    policy = oidc_step["with"]["inline-session-policy"]
    policy = policy.replace("${{ inputs.aws_region }}", "us-east-1")
    policy = policy.replace("${{ inputs.expected_aws_account_id }}", "123456789012")
    policy = policy.replace("${{ inputs.eks_cluster_name }}", "observability-staging")
    assert json.loads(policy)["Statement"][0]["Action"] == "eks:DescribeCluster"

    action_refs = re.findall(r"^\s*uses:\s*([^\s#]+)", text, flags=re.MULTILINE)
    assert action_refs
    for action_ref in action_refs:
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action_ref), action_ref

    assert "inline-session-policy" in text
    assert '"Action":"eks:DescribeCluster"' in text
    assert "allowed-account-ids" in text
    assert "persist-credentials: false" in text
    assert "version: v1.35.1" in text
    assert "36e2f4ac66259232341dd7866952d64a958846470f6a9a6a813b9117bd965207" in text
    assert "scripts/staging/validate-aws-eks-o11y.sh" in text
    assert "SPLUNK_O11Y_TOKEN_FILE" in text
    assert "KUBECONFIG: ${{ runner.temp }}/aws-eks-o11y-kubeconfig" in text
    assert 'chmod 600 "${KUBECONFIG}"' in text
    assert "rm -f --" in text
    cleanup_index = next(
        index
        for index, step in enumerate(job["steps"])
        if step["name"] == "Remove local credentials and kubeconfig"
    )
    upload_index = next(
        index
        for index, step in enumerate(job["steps"])
        if step["name"] == "Upload sanitized acceptance report"
    )
    assert cleanup_index < upload_index
    assert "SPLUNK_VERIFY_SSL=false" not in text

    forbidden = (
        r"kubectl\s+(?:apply|create|delete|patch|replace|rollout\s+restart)",
        r"helm\s+(?:install|upgrade|uninstall)",
        r"aws\s+eks\s+(?:create|delete|associate|disassociate)[a-z-]*",
        r"aws\s+eks\s+update-(?:cluster|nodegroup|addon|access)",
        r"--apply(?:\s|$)",
    )
    for pattern in forbidden:
        assert re.search(pattern, text) is None, pattern


def test_every_github_action_reference_is_immutably_pinned() -> None:
    workflow_root = REPO_ROOT / ".github/workflows"
    workflows = sorted(
        {
            *workflow_root.glob("*.yml"),
            *workflow_root.glob("*.yaml"),
        }
    )
    assert workflows, f"no GitHub workflows found under {workflow_root}"

    action_references: list[tuple[Path, str]] = []
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        payload = yaml.load(text, Loader=yaml.BaseLoader)
        for action_ref in _github_action_references(payload):
            action_references.append((workflow, action_ref))

    assert action_references, "no GitHub Action `uses:` references found"
    for workflow, action_ref in action_references:
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action_ref), (
            f"{workflow.relative_to(REPO_ROOT)}: mutable action reference {action_ref}"
        )


def test_action_reference_discovery_covers_flow_style_and_quoted_keys() -> None:
    payload = yaml.load(
        """
jobs:
  test:
    steps: [{uses: actions/checkout@mutable}, {"uses": owner/action@0123456789abcdef0123456789abcdef01234567}]
""",
        Loader=yaml.BaseLoader,
    )
    assert _github_action_references(payload) == [
        "actions/checkout@mutable",
        "owner/action@0123456789abcdef0123456789abcdef01234567",
    ]


def test_rbac_template_has_no_secret_or_mutating_access() -> None:
    documents = list(yaml.safe_load_all(RBAC_TEMPLATE.read_text(encoding="utf-8")))
    assert len(documents) == 6
    allowed_verbs = {"get", "list"}
    groups = set()
    resources = set()
    namespaces = set()
    for document in documents:
        metadata = document.get("metadata") or {}
        if document["kind"] == "RoleBinding":
            namespaces.add(metadata["namespace"])
        for subject in document.get("subjects") or []:
            if subject.get("kind") == "Group":
                groups.add(subject.get("name"))
        for rule in document.get("rules") or []:
            assert set(rule.get("verbs") or []) <= allowed_verbs
            resources.update(rule.get("resources") or [])

    assert groups == {"aws-eks-o11y-staging-validator"}
    assert namespaces == {"__COLLECTOR_NAMESPACE__", "__STAGING_NAMESPACE__"}
    assert "secrets" not in resources
    assert "replicasets" not in resources
    assert {"pods", "pods/log", "configmaps", "instrumentations"} <= resources
    assert "mutatingwebhookconfigurations" in resources
    webhook_rule = next(
        rule
        for document in documents
        for rule in document.get("rules") or []
        if "mutatingwebhookconfigurations" in (rule.get("resources") or [])
    )
    assert webhook_rule["verbs"] == ["get"]
    assert webhook_rule["resourceNames"] == ["__OPERATOR_WEBHOOK_NAME__"]
    collector_role = next(
        document
        for document in documents
        if document["kind"] == "Role"
        and document["metadata"]["namespace"] == "__COLLECTOR_NAMESPACE__"
    )
    workload_role = next(
        document
        for document in documents
        if document["kind"] == "Role"
        and document["metadata"]["namespace"] == "__STAGING_NAMESPACE__"
    )
    assert any("pods/log" in rule.get("resources", []) for rule in collector_role["rules"])
    assert all("pods/log" not in rule.get("resources", []) for rule in workload_role["rules"])
    assert all("configmaps" not in rule.get("resources", []) for rule in workload_role["rules"])
    service_rule = next(
        rule for rule in collector_role["rules"] if "services" in rule.get("resources", [])
    )
    assert set(service_rule["resources"]) == {"services", "endpoints"}
    assert service_rule["resourceNames"] == ["__OPERATOR_WEBHOOK_SERVICE_NAME__"]


def test_renderer_builds_exact_secret_free_review_packets(tmp_path: Path) -> None:
    token_value = "OFFLINE_STAGING_TOKEN_DO_NOT_EMBED"
    token = _private_token(tmp_path, token_value)
    result = subprocess.run(
        _render_command(tmp_path, token),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    rendered = tmp_path / "rendered"
    lines = result.stdout.splitlines()
    summary_start = max(index for index, line in enumerate(lines) if line == "{")
    summary = json.loads("\n".join(lines[summary_start:]))
    assert summary["read_only"] is True
    assert set(summary["outputs"]) == {"otel", "auto_instrumentation", "aws_integration"}

    otel = json.loads((rendered / "otel/metadata.json").read_text(encoding="utf-8"))
    assert otel["kubernetes"]["cluster_name"] == "observability-staging"
    assert otel["kubernetes"]["distribution"] == "eks"
    assert otel["kubernetes"]["release_name"] == "splunk-otel-collector"

    auto = json.loads((rendered / "auto-instrumentation/metadata.json").read_text(encoding="utf-8"))
    assert auto["cluster_name"] == "observability-staging"
    assert auto["realm"] == "us1"
    assert auto["namespace"] == "splunk-otel"
    assert auto["operator_resources"] == {
        "namespace": "splunk-otel",
        "deployment_name": "splunk-otel-collector-operator",
        "webhook_configuration_name": "splunk-otel-collector-operator-mutation",
        "webhook_service_name": "splunk-otel-collector-operator-webhook",
    }
    assert [row["target"] for row in auto["targets"]] == ["Deployment/staging/checkout-api"]

    plan = json.loads((rendered / "aws-integration/apply-plan.json").read_text(encoding="utf-8"))
    keys = {row["idempotency_key"] for row in plan["ordered_steps"]}
    assert "iam-trust:123456789012" in keys
    cfn_step = next(row for row in plan["ordered_steps"] if row["step"] == "metric_streams.cfn")
    assert cfn_step["coverage"] == "not_applicable"

    aws_payload = json.loads(
        (rendered / "aws-integration/payloads/integration-create.json").read_text(encoding="utf-8")
    )
    assert aws_payload["roleArn"] == (
        "arn:aws:iam::123456789012:role/SplunkObservabilityStagingRole"
    )
    assert aws_payload["useMetricStreamsSync"] is False

    for path in rendered.rglob("*"):
        if path.is_file():
            assert token_value.encode() not in path.read_bytes(), path


def test_renderer_rejects_unsafe_or_stale_inputs(tmp_path: Path) -> None:
    token = _private_token(tmp_path)
    token.chmod(0o640)
    loose = subprocess.run(
        _render_command(tmp_path, token),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert loose.returncode != 0
    assert "exact mode 0600" in loose.stderr

    token.chmod(0o600)
    link = tmp_path / "token-link"
    link.symlink_to(token)
    symlink_command = _render_command(tmp_path / "symlink", link)
    symlink = subprocess.run(
        symlink_command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert symlink.returncode != 0
    assert "securely open --token-file" in symlink.stderr

    control_token = tmp_path / "control-token"
    control_token.write_bytes(b"token\tvalue")
    control_token.chmod(0o600)
    control_command = _render_command(tmp_path / "control", control_token)
    control = subprocess.run(
        control_command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert control.returncode != 0
    assert "at most one trailing LF or CRLF" in control.stderr

    shared_namespace_command = _render_command(tmp_path / "shared-namespace", token)
    shared_namespace_command[shared_namespace_command.index("--namespace") + 1] = "splunk-otel"
    shared_namespace = subprocess.run(
        shared_namespace_command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert shared_namespace.returncode != 0
    assert "cannot inherit Collector pod-log access" in shared_namespace.stderr

    stale_root = tmp_path / "stale"
    stale_root.mkdir()
    (stale_root / "rendered/otel").mkdir(parents=True)
    stale_command = _render_command(stale_root, token)
    stale = subprocess.run(
        stale_command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert stale.returncode != 0
    assert "refusing to reuse existing otel output" in stale.stderr


def test_renderer_accepts_shared_writer_newline_and_binds_custom_operator_scope(
    tmp_path: Path,
) -> None:
    token = _private_token(tmp_path, "OFFLINE_STAGING_TOKEN_DO_NOT_EMBED\n")
    command = _render_command(tmp_path, token)
    command[command.index("splunk-otel")] = "custom-observability"
    command[command.index("splunk-otel-collector")] = "splunk-otel-collector-staging"
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    metadata = json.loads(
        (tmp_path / "rendered/auto-instrumentation/metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["namespace"] == "custom-observability"
    assert metadata["base"]["namespace"] == "custom-observability"
    assert metadata["operator_resources"] == {
        "namespace": "custom-observability",
        "deployment_name": "splunk-otel-collector-aa0e38f3",
        "webhook_configuration_name": "splunk-otel-collector-aa0e38f3-mutation",
        "webhook_service_name": "splunk-otel-collector-aa0e38f3-webhook",
    }


def test_staging_renderer_rejects_sdk_language(tmp_path: Path) -> None:
    token = _private_token(tmp_path)
    command = _render_command(tmp_path, token)
    command[command.index("java")] = "sdk"
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "invalid choice: 'sdk'" in result.stderr


def test_renderer_and_report_artifacts_default_to_private_files(tmp_path: Path) -> None:
    token = _private_token(tmp_path)
    result = subprocess.run(
        _render_command(tmp_path, token),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert stat.S_IMODE((tmp_path / "rendered").stat().st_mode) == 0o700
    assert os.access(RENDERER, os.X_OK)
