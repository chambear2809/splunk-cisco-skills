"""Production-gate regressions for AWS/EKS/Splunk Observability staging."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "scripts/staging/validate-aws-eks-o11y.sh"
WORKLOAD_VALIDATOR = (
    REPO_ROOT
    / "skills/splunk-observability-otel-collector-setup/scripts/validate_k8s_workloads.py"
)
AUTO_RENDER = (
    REPO_ROOT
    / "skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/render_assets.py"
)
AUTO_VALIDATE = (
    REPO_ROOT
    / "skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/validate.sh"
)
REDACTOR = REPO_ROOT / "scripts/staging/redact-output.py"


def _runner_env(tmp_path: Path, token: Path) -> dict[str, str]:
    otel = tmp_path / "otel"
    auto = tmp_path / "auto"
    aws = tmp_path / "aws"
    (otel / "k8s").mkdir(parents=True)
    auto.mkdir()
    aws.mkdir()
    (otel / "k8s/status.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (otel / "metadata.json").write_text(
        json.dumps(
            {
                "kubernetes": {
                    "rendered": True,
                    "cluster_name": "observability-staging",
                    "distribution": "eks",
                    "namespace": "splunk-otel",
                    "release_name": "splunk-otel-collector",
                }
            }
        ),
        encoding="utf-8",
    )
    (auto / "metadata.json").write_text(
        json.dumps(
            {
                "cluster_name": "observability-staging",
                "realm": "us1",
                "deployment_environment": "staging",
                "namespace": "splunk-otel",
                "base": {"namespace": "splunk-otel", "release": "splunk-otel-collector"},
                "operator_resources": {
                    "namespace": "splunk-otel",
                    "deployment_name": "splunk-otel-collector-operator",
                    "webhook_configuration_name": "splunk-otel-collector-operator-mutation",
                    "webhook_service_name": "splunk-otel-collector-operator-webhook",
                },
                "instrumentation_crs": [
                    {"namespace": "splunk-otel", "name": "splunk-otel-staging"}
                ],
                "targets": [
                    {
                        "kind": "Deployment",
                        "namespace": "staging",
                        "name": "checkout-api",
                        "language": "java",
                        "cr": "splunk-otel/splunk-otel-staging",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (aws / "apply-plan.json").write_text(
        json.dumps(
            {
                "ordered_steps": [
                    {"idempotency_key": "iam-trust:123456789012"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (aws / "payloads").mkdir()
    (aws / "payloads/integration-create.json").write_text(
        json.dumps(
            {
                "name": "observability-staging-staging",
                "regions": ["us-east-1"],
                "roleArn": "arn:aws:iam::123456789012:role/SplunkObservabilityStagingRole",
            }
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "STAGING_EXPECTED_AWS_ACCOUNT_ID": "123456789012",
            "AWS_REGION": "us-east-1",
            "STAGING_EKS_CLUSTER_NAME": "observability-staging",
            "STAGING_KUBE_CONTEXT": "staging-context",
            "STAGING_NAMESPACE": "staging",
            "STAGING_WORKLOAD": "Deployment/checkout-api",
            "STAGING_APM_SERVICE": "checkout-api",
            "SPLUNK_O11Y_REALM": "us1",
            "SPLUNK_O11Y_TOKEN_FILE": str(token),
            "COLLECTOR_NAMESPACE": "splunk-otel",
            "COLLECTOR_RELEASE": "splunk-otel-collector",
            "INSTRUMENTATION_NAME": "splunk-otel-staging",
            "WORKLOAD_LANGUAGE": "java",
            "STAGING_OTEL_RENDERED_DIR": str(otel),
            "STAGING_AUTO_INSTRUMENTATION_RENDERED_DIR": str(auto),
            "STAGING_AWS_INTEGRATION_RENDERED_DIR": str(aws),
        }
    )
    env.pop("STAGING_LAMBDA_APM_RENDERED_DIR", None)
    env.pop("STAGING_CLOUD_INTEGRATION_RENDERED_DIR", None)
    return env


def test_runner_help_documents_stable_contract_and_does_not_source_env() -> None:
    result = subprocess.run(["bash", str(RUNNER), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    for name in (
        "STAGING_EXPECTED_AWS_ACCOUNT_ID",
        "STAGING_KUBE_CONTEXT",
        "STAGING_OTEL_RENDERED_DIR",
        "STAGING_AUTO_INSTRUMENTATION_RENDERED_DIR",
        "STAGING_AWS_INTEGRATION_RENDERED_DIR",
        "STAGING_LAMBDA_APM_RENDERED_DIR",
        "STAGING_CLOUD_INTEGRATION_RENDERED_DIR",
        "STAGING_REPORT_PATH",
    ):
        assert name in result.stdout
    body = RUNNER.read_text(encoding="utf-8")
    assert "source \"" not in body
    assert "--k8s-workloads-only" in body


def test_runner_missing_environment_writes_private_sanitized_report(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    result = subprocess.run(
        ["bash", str(RUNNER), "--report", str(report)],
        cwd=REPO_ROOT,
        env={},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "fail"
    assert payload["read_only"] is True
    assert {row["id"] for row in payload["checks"] if row["status"] == "skipped"}.issuperset(
        {"lambda-apm-reachability", "cloud-integration-reachability"}
    )
    assert stat.S_IMODE(report.stat().st_mode) == 0o600
    check_ids = [row["id"] for row in payload["checks"]]
    assert len(check_ids) == len(set(check_ids))


def test_staging_diagnostic_redactor_covers_headers_json_bearer_and_url_userinfo(
    tmp_path: Path,
) -> None:
    secrets = (
        "BASIC_HEADER_SECRET",
        "JSON_TOKEN_SECRET",
        "JSON_XSF_SECRET",
        "JSON_AUTH_SECRET",
        "BARE_BEARER_SECRET",
        "PLAIN_API_SECRET",
        "URL_PASSWORD_SECRET",
    )
    source = tmp_path / "diagnostic.log"
    source.write_text(
        "> Authorization: Basic BASIC_HEADER_SECRET\n"
        '{"token":"JSON_TOKEN_SECRET","X-SF-Token":"JSON_XSF_SECRET",'
        '"authorization":"Bearer JSON_AUTH_SECRET"}\n'
        "request failed with Bearer BARE_BEARER_SECRET\n"
        "api_key=PLAIN_API_SECRET\n"
        "https://operator:URL_PASSWORD_SECRET@example.test/path\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(REDACTOR), str(source)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr.count("[REDACTED]") >= len(secrets)
    for secret in secrets:
        assert secret not in result.stderr


def test_runner_rejects_symlink_token_and_never_reports_token_value(tmp_path: Path) -> None:
    token_value = "SUPER_SECRET_STAGING_TOKEN_VALUE"
    token = tmp_path / "token"
    token.write_text(token_value, encoding="utf-8")
    token.chmod(0o600)
    link = tmp_path / "token-link"
    link.symlink_to(token)
    report = tmp_path / "report.json"
    result = subprocess.run(
        ["bash", str(RUNNER), "--report", str(report)],
        cwd=REPO_ROOT,
        env=_runner_env(tmp_path, link),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    payload = json.loads(report.read_text(encoding="utf-8"))
    token_check = next(row for row in payload["checks"] if row["id"] == "token-file")
    assert token_check["status"] == "failed"
    assert token_value not in report.read_text(encoding="utf-8")
    assert token_value not in result.stdout + result.stderr


def test_runner_rejects_non_0600_token_and_disabled_tls(tmp_path: Path) -> None:
    token = tmp_path / "token"
    token.write_text("secret-value", encoding="utf-8")
    token.chmod(0o640)
    report = tmp_path / "mode-report.json"
    mode_result = subprocess.run(
        ["bash", str(RUNNER), "--report", str(report)],
        cwd=REPO_ROOT,
        env=_runner_env(tmp_path, token),
        capture_output=True,
        text=True,
        check=False,
    )
    assert mode_result.returncode == 2
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert next(row for row in payload["checks"] if row["id"] == "token-file")["status"] == "failed"

    tls_report = tmp_path / "tls-report.json"
    tls_env = _runner_env(tmp_path / "tls", token)
    tls_env["SPLUNK_VERIFY_SSL"] = "false"
    tls_result = subprocess.run(
        ["bash", str(RUNNER), "--report", str(tls_report)],
        cwd=REPO_ROOT,
        env=tls_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert tls_result.returncode == 2
    assert "SPLUNK_VERIFY_SSL=false is forbidden" in tls_result.stderr


def test_runner_rejects_control_characters_in_scope(tmp_path: Path) -> None:
    token = tmp_path / "token"
    token.write_text("secret-value", encoding="utf-8")
    token.chmod(0o600)
    report = tmp_path / "control-report.json"
    env = _runner_env(tmp_path, token)
    env["STAGING_APM_SERVICE"] = "checkout-api\tescape"
    result = subprocess.run(
        ["bash", str(RUNNER), "--report", str(report)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "APM service" in result.stderr


def _write_runner_read_only_tools(
    tmp_path: Path,
    *,
    context_server: str = "https://eks.example.test",
    context_ca: str = "EXPECTED_CA",
    insecure_skip_tls: bool = False,
    server_minor: str = "35",
    exec_command: str = "aws",
    exec_env: list[dict[str, str]] | None = None,
    interactive_mode: str | None = None,
    exec_args: list[str] | None = None,
) -> Path:
    fake_bin = tmp_path / "runner-bin"
    fake_bin.mkdir()
    aws = fake_bin / "aws"
    aws.write_text(
        """#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if args == ['--version']:
    print('aws-cli/2.17.0 Python/3.11 Linux/amd64')
elif args[:2] == ['sts', 'get-caller-identity']:
    print('123456789012')
elif args[:2] == ['eks', 'describe-cluster']:
    print(json.dumps({'cluster': {
        'status': 'ACTIVE',
        'arn': 'arn:aws:eks:us-east-1:123456789012:cluster/observability-staging',
        'endpoint': 'https://eks.example.test',
        'certificateAuthority': {'data': 'EXPECTED_CA'},
    }}))
else:
    raise SystemExit(1)
""",
        encoding="utf-8",
    )
    aws.chmod(0o755)

    effective_exec_args = exec_args if exec_args is not None else [
        "--region",
        "us-east-1",
        "eks",
        "get-token",
        "--cluster-name",
        "observability-staging",
        "--output",
        "json",
    ]
    kubectl = fake_bin / "kubectl"
    kubectl.write_text(
        f"""#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if args[:2] == ['version', '--client']:
    print(json.dumps({{'clientVersion': {{'major': '1', 'minor': '35'}}}}))
elif args[:2] == ['config', 'get-contexts']:
    print('staging-context')
elif args[:2] == ['config', 'current-context']:
    print('staging-context')
elif args[:2] == ['config', 'view']:
    cluster = {{
        'server': {context_server!r},
        'certificate-authority-data': {context_ca!r},
        'insecure-skip-tls-verify': {insecure_skip_tls!r},
    }}
    exec_config = {{
        'command': {exec_command!r},
        'args': {effective_exec_args!r},
        'apiVersion': 'client.authentication.k8s.io/v1beta1',
    }}
    if {exec_env!r} is not None:
        exec_config['env'] = {exec_env!r}
    if {interactive_mode!r} is not None:
        exec_config['interactiveMode'] = {interactive_mode!r}
    print(json.dumps({{
        'clusters': [{{'name': 'cluster', 'cluster': cluster}}],
        'users': [{{'name': 'user', 'user': {{'exec': exec_config}}}}],
    }}))
elif 'get' in args and '--raw=/version' in args:
    print(json.dumps({{'gitVersion': 'v1.{server_minor}.0'}}))
elif 'version' in args and '--client' not in args:
    print(json.dumps({{
        'clientVersion': {{'major': '1', 'minor': '35'}},
        'serverVersion': {{'major': '1', 'minor': {server_minor!r}}},
    }}))
elif 'auth' in args and 'can-i' in args:
    print('yes')
elif 'get' in args and any(value in args for value in ('Deployment', 'deployment')):
    print(json.dumps({{
        'kind': 'Deployment',
        'metadata': {{'name': 'checkout-api', 'namespace': 'staging', 'generation': 1}},
        'spec': {{'replicas': 1}},
        'status': {{'observedGeneration': 1, 'readyReplicas': 1, 'updatedReplicas': 1, 'availableReplicas': 1}},
    }}))
else:
    raise SystemExit(1)
""",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)
    for name in ("bash", "curl"):
        tool = fake_bin / name
        tool.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        tool.chmod(0o755)
    return fake_bin


@pytest.mark.parametrize(
    ("context_server", "context_ca", "insecure_skip_tls", "server_minor"),
    [
        ("https://wrong.example.test", "EXPECTED_CA", False, "35"),
        ("https://eks.example.test", "WRONG_CA", False, "35"),
        ("https://eks.example.test", "EXPECTED_CA", True, "35"),
        ("https://eks.example.test", "EXPECTED_CA", False, "32"),
    ],
)
def test_runner_fails_closed_on_context_binding_or_version_skew(
    tmp_path: Path,
    context_server: str,
    context_ca: str,
    insecure_skip_tls: bool,
    server_minor: str,
) -> None:
    token = tmp_path / "token"
    token.write_text("secret-value", encoding="utf-8")
    token.chmod(0o600)
    env = _runner_env(tmp_path, token)
    fake_bin = _write_runner_read_only_tools(
        tmp_path,
        context_server=context_server,
        context_ca=context_ca,
        insecure_skip_tls=insecure_skip_tls,
        server_minor=server_minor,
    )
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    report = tmp_path / "binding-report.json"
    result = subprocess.run(
        ["/bin/bash", str(RUNNER), "--report", str(report)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode != 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    check = next(row for row in payload["checks"] if row["id"] == "kube-context")
    assert check["status"] == "failed"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"exec_command": "/tmp/aws"}, "audited aws executable"),
        (
            {"exec_env": [{"name": "AWS_PROFILE", "value": "different-role"}]},
            "overrides the runner AWS environment",
        ),
        ({"interactive_mode": "Always"}, "unsupported interactiveMode"),
        (
            {
                "exec_args": [
                    "--profile",
                    "different-role",
                    "--region",
                    "us-east-1",
                    "eks",
                    "get-token",
                    "--cluster-name",
                    "observability-staging",
                    "--output",
                    "json",
                ]
            },
            "not bound to the current AWS CLI identity",
        ),
    ],
)
def test_runner_rejects_kube_exec_identity_overrides(
    tmp_path: Path,
    overrides: dict[str, object],
    expected: str,
) -> None:
    token = tmp_path / "token"
    token.write_text("secret-value", encoding="utf-8")
    token.chmod(0o600)
    env = _runner_env(tmp_path, token)
    fake_bin = _write_runner_read_only_tools(tmp_path, **overrides)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    report = tmp_path / "identity-report.json"
    result = subprocess.run(
        ["/bin/bash", str(RUNNER), "--report", str(report)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode != 0
    assert expected in result.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert next(row for row in payload["checks"] if row["id"] == "kube-context")[
        "status"
    ] == "failed"


def test_optional_diagnostic_failures_are_redacted_recorded_and_non_gating(
    tmp_path: Path,
) -> None:
    token = tmp_path / "token"
    token.write_text("secret-value\n", encoding="utf-8")
    token.chmod(0o600)
    env = _runner_env(tmp_path, token)
    # This is the value emitted by current `aws eks update-kubeconfig`.
    fake_bin = _write_runner_read_only_tools(tmp_path, interactive_mode="IfAvailable")
    fake_bash = fake_bin / "bash"
    fake_bash.write_text(
        """#!/bin/sh
case "$1" in
  *splunk-observability-aws-lambda-apm-setup*|*splunk-observability-cloud-integration-setup*)
    printf '%s\n' '> Authorization: Bearer OPTIONAL_AUTH_SECRET' >&2
    printf '%s\n' '{"X-SF-Token":"OPTIONAL_JSON_SECRET"}' >&2
    exit 7
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    fake_bash.chmod(0o755)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["STAGING_LAMBDA_APM_RENDERED_DIR"] = str(tmp_path / "lambda")
    env["STAGING_CLOUD_INTEGRATION_RENDERED_DIR"] = str(tmp_path / "cloud")
    report = tmp_path / "optional-report.json"
    result = subprocess.run(
        ["/bin/bash", str(RUNNER), "--report", str(report)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "pass"
    assert payload["optional_diagnostics_failed"] == 2
    optionals = [row for row in payload["checks"] if not row["required"]]
    assert {row["id"] for row in optionals} == {
        "lambda-apm-reachability",
        "cloud-integration-reachability",
    }
    assert {row["status"] for row in optionals} == {"failed"}
    check_ids = [row["id"] for row in payload["checks"]]
    assert len(check_ids) == len(set(check_ids))
    combined = result.stdout + result.stderr + report.read_text(encoding="utf-8")
    assert "OPTIONAL_AUTH_SECRET" not in combined
    assert "OPTIONAL_JSON_SECRET" not in combined
    assert "[REDACTED]" in result.stderr


def _write_fake_kubectl(
    path: Path,
    log_path: Path,
    *,
    unready: bool = False,
    bad_release_only_image: bool = False,
    fail_selector: str = "",
    dual_label_churn: bool = False,
    unready_auxiliary: bool = False,
    failed_auxiliary: bool = False,
    completed_job_auxiliary: bool = False,
) -> None:
    path.write_text(
        f"""#!/usr/bin/env python3
import json, sys
from pathlib import Path
Path({str(log_path)!r}).open('a', encoding='utf-8').write(json.dumps(sys.argv[1:]) + '\\n')
args = sys.argv[1:]
name = args[args.index('get') + 2]
resource = args[args.index('get') + 1]
namespace = args[args.index('-n') + 1]
ready = {str(not unready)}
def pod_payload(pod_name, resource_version):
    image = 'example.test/collector@sha256:' + ('b' if pod_name == 'collector-primary' else 'a') * 64
    if pod_name == 'collector-primary' and {bad_release_only_image!r}:
        image = 'example.test/collector:latest'
    phase = 'Running'
    condition = 'True' if ready else 'False'
    owner_references = []
    if pod_name == 'collector-auxiliary' and {unready_auxiliary!r}:
        condition = 'False'
    if pod_name == 'collector-auxiliary' and {failed_auxiliary!r}:
        phase = 'Failed'
        condition = 'False'
    if pod_name == 'collector-auxiliary' and {completed_job_auxiliary!r}:
        phase = 'Succeeded'
        condition = 'False'
        owner_references = [{{
            'apiVersion': 'batch/v1',
            'kind': 'Job',
            'name': 'collector-completed-hook',
            'controller': True,
        }}]
    return {{
        'apiVersion': 'v1', 'kind': 'Pod',
        'metadata': {{
            'name': pod_name,
            'namespace': namespace,
            'resourceVersion': resource_version,
            'ownerReferences': owner_references,
        }},
        'spec': {{'containers': [{{'name': 'collector', 'image': image}}]}},
        'status': {{
            'phase': phase,
            'conditions': [{{'type': 'Ready', 'status': condition}}],
        }},
    }}
if resource == 'pods':
    selector = args[args.index('-l') + 1]
    if {fail_selector!r} and selector == {fail_selector!r}:
        print('SELECTOR_PRIVATE_MARKER', file=sys.stderr)
        raise SystemExit(1)
    shared_version = '2' if {dual_label_churn!r} and not selector.startswith('release=') else '1'
    shared = pod_payload('collector-shared', shared_version)
    items = [shared]
    if selector.startswith('release='):
        items.insert(0, pod_payload('collector-primary', '1'))
    elif {bool(unready_auxiliary or failed_auxiliary or completed_job_auxiliary)!r}:
        items.append(pod_payload('collector-auxiliary', '1'))
    payload = {{'apiVersion': 'v1', 'kind': 'List', 'items': items}}
elif resource == 'pod':
    payload = pod_payload(name, '3')
else:
    kinds = {{'daemonset': 'DaemonSet', 'deployment': 'Deployment', 'statefulset': 'StatefulSet', 'instrumentation': 'Instrumentation'}}
    kind = kinds[resource]
    status = {{'observedGeneration': 1, 'readyReplicas': 1 if ready else 0, 'updatedReplicas': 1, 'availableReplicas': 1, 'currentReplicas': 1,
               'desiredNumberScheduled': 1, 'numberReady': 1 if ready else 0, 'updatedNumberScheduled': 1, 'numberUnavailable': 0}}
    payload = {{'apiVersion': 'apps/v1', 'kind': kind, 'metadata': {{'name': name, 'namespace': namespace, 'generation': 1}},
               'spec': {{'replicas': 1}}, 'status': status}}
print(json.dumps(payload))
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_runtime_verifier(
    path: Path, *, log_path: Path | None = None, fail_with_private_marker: bool = False
) -> None:
    log_literal = repr(str(log_path) if log_path is not None else "")
    path.write_text(
        "import json,sys\n"
        "from pathlib import Path\n"
        f"log_path = {log_literal}\n"
        "payload=json.load(sys.stdin)\n"
        "if log_path:\n"
        "    Path(log_path).open('a', encoding='utf-8').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        f"if {fail_with_private_marker!r}:\n"
        "    print('VERIFIER_PRIVATE_MARKER', file=sys.stderr)\n"
        "    raise SystemExit(7)\n"
        "for container in payload.get('spec', {}).get('containers', []):\n"
        "    assert '@sha256:' in container['image']\n"
        "owners = [row for row in payload.get('metadata', {}).get('ownerReferences', []) "
        "if row.get('controller') is True]\n"
        "if payload.get('status', {}).get('phase') == 'Succeeded' "
        "and len(owners) == 1 and owners[0].get('kind') == 'Job':\n"
        "    raise SystemExit(10)\n",
        encoding="utf-8",
    )


def test_secret_free_collector_workload_validator_never_reads_k8s_secrets(tmp_path: Path) -> None:
    metadata = tmp_path / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "kubernetes": {
                    "rendered": True,
                    "namespace": "splunk-otel",
                    "release_name": "staging",
                    "distribution": "eks",
                    "agent_enabled": True,
                    "gateway_enabled": False,
                    "cluster_receiver_enabled": True,
                    "operator_enabled": False,
                    "target_allocator_enabled": False,
                    "obi_enabled": False,
                }
            }
        ),
        encoding="utf-8",
    )
    log = tmp_path / "kubectl.log"
    kubectl = tmp_path / "kubectl"
    _write_fake_kubectl(kubectl, log)
    verifier = tmp_path / "verify.py"
    _write_fake_runtime_verifier(verifier)
    result = subprocess.run(
        [
            sys.executable,
            str(WORKLOAD_VALIDATOR),
            "--metadata",
            str(metadata),
            "--image-verifier",
            str(verifier),
            "--kube-context",
            "staging-context",
            "--kubectl-bin",
            str(kubectl),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert calls
    assert all("secret" not in " ".join(call).lower() for call in calls)
    assert "audited image digests" in result.stdout


def test_secret_free_collector_validator_unions_churning_dual_label_pods_then_fetches_once(
    tmp_path: Path,
) -> None:
    metadata = tmp_path / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "kubernetes": {
                    "rendered": True,
                    "namespace": "splunk-otel",
                    "release_name": "staging",
                    "distribution": "eks",
                    "agent_enabled": True,
                }
            }
        ),
        encoding="utf-8",
    )
    log = tmp_path / "kubectl.log"
    kubectl = tmp_path / "kubectl"
    _write_fake_kubectl(kubectl, log, dual_label_churn=True)
    verifier = tmp_path / "verify.py"
    _write_fake_runtime_verifier(verifier)

    result = subprocess.run(
        [
            sys.executable,
            str(WORKLOAD_VALIDATOR),
            "--metadata",
            str(metadata),
            "--image-verifier",
            str(verifier),
            "--kubectl-bin",
            str(kubectl),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    fresh_pod_names = [
        call[call.index("get") + 2]
        for call in calls
        if "get" in call and call[call.index("get") + 1] == "pod"
    ]
    assert fresh_pod_names.count("collector-shared") == 1
    assert fresh_pod_names.count("collector-primary") == 1


def test_secret_free_collector_workload_validator_fails_unready(tmp_path: Path) -> None:
    metadata = tmp_path / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "kubernetes": {
                    "rendered": True,
                    "namespace": "splunk-otel",
                    "release_name": "staging",
                    "distribution": "eks",
                    "agent_enabled": True,
                }
            }
        ),
        encoding="utf-8",
    )
    kubectl = tmp_path / "kubectl"
    _write_fake_kubectl(kubectl, tmp_path / "kubectl.log", unready=True)
    verifier = tmp_path / "verify.py"
    verifier.write_text("import sys\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(WORKLOAD_VALIDATOR),
            "--metadata",
            str(metadata),
            "--image-verifier",
            str(verifier),
            "--kubectl-bin",
            str(kubectl),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "not fully rolled out and Ready" in result.stderr


def test_secret_free_collector_validator_checks_release_only_pod_images(
    tmp_path: Path,
) -> None:
    metadata = tmp_path / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "kubernetes": {
                    "rendered": True,
                    "namespace": "splunk-otel",
                    "release_name": "staging",
                    "distribution": "eks",
                    "agent_enabled": True,
                }
            }
        ),
        encoding="utf-8",
    )
    log = tmp_path / "kubectl.log"
    kubectl = tmp_path / "kubectl"
    _write_fake_kubectl(kubectl, log, bad_release_only_image=True)
    verifier = tmp_path / "verify.py"
    _write_fake_runtime_verifier(verifier)
    result = subprocess.run(
        [
            sys.executable,
            str(WORKLOAD_VALIDATOR),
            "--metadata",
            str(metadata),
            "--image-verifier",
            str(verifier),
            "--kubectl-bin",
            str(kubectl),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    selectors = {call[call.index("-l") + 1] for call in calls if "-l" in call}
    assert selectors == {"release=staging", "app.kubernetes.io/instance=staging"}


def test_secret_free_collector_validator_fails_on_either_selector_error(
    tmp_path: Path,
) -> None:
    metadata = tmp_path / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "kubernetes": {
                    "rendered": True,
                    "namespace": "splunk-otel",
                    "release_name": "staging",
                    "distribution": "eks",
                    "agent_enabled": True,
                }
            }
        ),
        encoding="utf-8",
    )
    kubectl = tmp_path / "kubectl"
    _write_fake_kubectl(
        kubectl,
        tmp_path / "kubectl.log",
        fail_selector="app.kubernetes.io/instance=staging",
    )
    verifier = tmp_path / "verify.py"
    verifier.write_text("import sys\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(WORKLOAD_VALIDATOR),
            "--metadata",
            str(metadata),
            "--image-verifier",
            str(verifier),
            "--kubectl-bin",
            str(kubectl),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "SELECTOR_PRIVATE_MARKER" not in result.stdout + result.stderr


@pytest.mark.parametrize("state", ["unready", "failed"])
def test_secret_free_collector_validator_rejects_unhealthy_auxiliary_union_pod(
    tmp_path: Path, state: str
) -> None:
    metadata = tmp_path / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "kubernetes": {
                    "rendered": True,
                    "namespace": "splunk-otel",
                    "release_name": "staging",
                    "distribution": "eks",
                    "agent_enabled": True,
                }
            }
        ),
        encoding="utf-8",
    )
    kubectl = tmp_path / "kubectl"
    _write_fake_kubectl(
        kubectl,
        tmp_path / "kubectl.log",
        unready_auxiliary=state == "unready",
        failed_auxiliary=state == "failed",
    )
    verifier = tmp_path / "verify.py"
    _write_fake_runtime_verifier(verifier)
    result = subprocess.run(
        [
            sys.executable,
            str(WORKLOAD_VALIDATOR),
            "--metadata",
            str(metadata),
            "--image-verifier",
            str(verifier),
            "--kubectl-bin",
            str(kubectl),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "collector-auxiliary is not active, Running, and Ready" in result.stderr


def test_secret_free_collector_validator_excludes_only_completed_job_pods(
    tmp_path: Path,
) -> None:
    metadata = tmp_path / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "kubernetes": {
                    "rendered": True,
                    "namespace": "splunk-otel",
                    "release_name": "staging",
                    "distribution": "eks",
                    "agent_enabled": True,
                }
            }
        ),
        encoding="utf-8",
    )
    kubectl_log = tmp_path / "kubectl.log"
    kubectl = tmp_path / "kubectl"
    _write_fake_kubectl(
        kubectl,
        kubectl_log,
        completed_job_auxiliary=True,
    )
    verifier_log = tmp_path / "verifier.log"
    verifier = tmp_path / "verify.py"
    _write_fake_runtime_verifier(verifier, log_path=verifier_log)
    result = subprocess.run(
        [
            sys.executable,
            str(WORKLOAD_VALIDATOR),
            "--metadata",
            str(metadata),
            "--image-verifier",
            str(verifier),
            "--kubectl-bin",
            str(kubectl),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 completed Job pod(s) excluded" in result.stdout
    verifier_calls = [
        json.loads(line) for line in verifier_log.read_text(encoding="utf-8").splitlines()
    ]
    assert ["--verify-runtime-pod-json", "collector-primary", "primary"] in verifier_calls
    assert ["--verify-runtime-pod-json", "collector-auxiliary", "auxiliary"] in (
        verifier_calls
    )


def test_secret_free_collector_validator_suppresses_verifier_failure_output(
    tmp_path: Path,
) -> None:
    metadata = tmp_path / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "kubernetes": {
                    "rendered": True,
                    "namespace": "splunk-otel",
                    "release_name": "staging",
                    "distribution": "eks",
                    "agent_enabled": True,
                }
            }
        ),
        encoding="utf-8",
    )
    kubectl = tmp_path / "kubectl"
    _write_fake_kubectl(kubectl, tmp_path / "kubectl.log")
    verifier = tmp_path / "verify.py"
    _write_fake_runtime_verifier(verifier, fail_with_private_marker=True)
    result = subprocess.run(
        [
            sys.executable,
            str(WORKLOAD_VALIDATOR),
            "--metadata",
            str(metadata),
            "--image-verifier",
            str(verifier),
            "--kubectl-bin",
            str(kubectl),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "verifier output suppressed" in result.stderr
    assert "VERIFIER_PRIVATE_MARKER" not in result.stdout + result.stderr


def _render_auto(tmp_path: Path) -> Path:
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        yaml.safe_dump(
            {
                "api_version": "splunk-observability-k8s-auto-instrumentation-setup/v1",
                "realm": "us1",
                "cluster_name": "observability-staging",
                "deployment_environment": "staging",
                "distribution": "eks",
                "instrumentation_crs": [
                    {"name": "splunk-otel-auto-instrumentation", "namespace": "splunk-otel", "languages": ["java"]}
                ],
                "workload_annotations": [
                    {
                        "kind": "Deployment",
                        "namespace": "staging",
                        "name": "checkout-api",
                        "language": "java",
                        "cr": "splunk-otel/splunk-otel-auto-instrumentation",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "rendered"
    result = subprocess.run(
        [sys.executable, str(AUTO_RENDER), "--spec", str(spec), "--output-dir", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return out


def _auto_env_with_kubectl(tmp_path: Path, script_body: str) -> dict[str, str]:
    fake_bin = tmp_path / "auto-bin"
    fake_bin.mkdir(parents=True)
    kubectl = fake_bin / "kubectl"
    kubectl.write_text(f"#!/usr/bin/env python3\n{script_body}", encoding="utf-8")
    kubectl.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    return env


def _instrumentation_document(out: Path) -> dict[str, object]:
    documents = [
        document
        for document in yaml.safe_load_all(
            (out / "k8s-instrumentation/instrumentation-cr.yaml").read_text(encoding="utf-8")
        )
        if document
    ]
    assert len(documents) == 1
    return documents[0]


def test_auto_static_validation_rejects_errored_or_malformed_metadata(tmp_path: Path) -> None:
    out = _render_auto(tmp_path)
    metadata_path = out / "metadata.json"
    original = json.loads(metadata_path.read_text(encoding="utf-8"))
    cases = [
        ("preflight-errors", {"preflight": {"errors": ["hard failure"]}}, "unresolved preflight"),
        ("top-errors", {"errors": ["hard failure"]}, "unresolved top-level"),
        ("preflight-wrong-type", {"preflight": {"errors": {}}}, "must be a list"),
        ("top-wrong-type", {"errors": ""}, "must be a list"),
    ]
    for _, override, expected in cases:
        mutated = json.loads(json.dumps(original))
        for key, value in override.items():
            mutated[key] = value
        metadata_path.write_text(json.dumps(mutated), encoding="utf-8")
        result = subprocess.run(
            ["bash", str(AUTO_VALIDATE), "--output-dir", str(out)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert expected in result.stdout + result.stderr
    metadata_path.write_text(json.dumps(original), encoding="utf-8")


def test_auto_live_is_complete_and_requires_named_skips(tmp_path: Path) -> None:
    out = _render_auto(tmp_path)
    missing_apm = subprocess.run(
        [
            "bash",
            str(AUTO_VALIDATE),
            "--output-dir",
            str(out),
            "--live",
            "--allow-current-context",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_apm.returncode != 0
    assert "--live requires --check-apm SERVICE" in missing_apm.stdout + missing_apm.stderr

    env = _auto_env_with_kubectl(tmp_path, "raise SystemExit(1)\n")
    skipped = subprocess.run(
        [
            "bash",
            str(AUTO_VALIDATE),
            "--output-dir",
            str(out),
            "--live",
            "--skip-apm-check",
            "--skip-backup-check",
            "--allow-current-context",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert skipped.returncode != 0
    combined = skipped.stdout + skipped.stderr
    assert "--live requires" not in combined
    assert "Kubernetes API failed while reading MutatingWebhookConfiguration" in combined


def _webhook_kubectl_body(*, endpoint_port: int = 9443, failure_policy: str = "Ignore") -> str:
    ca_bundle = "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tClkyVnlkR2xtYVdOaGRHVXRZbmwwWlhNPQotLS0tLUVORCBDRVJUSUZJQ0FURS0tLS0tCg=="
    name = "splunk-otel-collector-operator"
    webhook = {
        "apiVersion": "admissionregistration.k8s.io/v1",
        "kind": "MutatingWebhookConfiguration",
        "metadata": {"name": f"{name}-mutation"},
        "webhooks": [
            {
                "name": "mpod.kb.io",
                "admissionReviewVersions": ["v1"],
                "sideEffects": "None",
                "failurePolicy": failure_policy,
                "timeoutSeconds": 10,
                "clientConfig": {
                    "caBundle": ca_bundle,
                    "service": {
                        "name": f"{name}-webhook",
                        "namespace": "splunk-otel",
                        "path": "/mutate-v1-pod",
                        "port": 443,
                    },
                },
                "rules": [
                    {
                        "apiGroups": [""],
                        "apiVersions": ["v1"],
                        "operations": ["CREATE"],
                        "resources": ["pods"],
                        "scope": "Namespaced",
                    }
                ],
            }
        ],
    }
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": f"{name}-webhook", "namespace": "splunk-otel"},
        "spec": {
            "type": "ClusterIP",
            "clusterIP": "172.20.1.10",
            "selector": {"app.kubernetes.io/name": "operator"},
            "ports": [{"port": 443, "protocol": "TCP", "targetPort": "webhook-server"}],
        },
    }
    endpoints = {
        "apiVersion": "v1",
        "kind": "Endpoints",
        "metadata": {"name": f"{name}-webhook", "namespace": "splunk-otel"},
        "subsets": [
            {
                "addresses": [{"ip": "10.0.0.10"}],
                "ports": [{"port": endpoint_port, "protocol": "TCP"}],
            }
        ],
    }
    pods = {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            {
                "metadata": {"name": f"{name}-abc", "namespace": "splunk-otel"},
                "status": {
                    "phase": "Running",
                    "conditions": [{"type": "Ready", "status": "True"}],
                },
            }
        ],
    }
    payloads = {"webhook": webhook, "service": service, "endpoints": endpoints, "pods": pods}
    return (
        "import json, sys\n"
        f"payloads = json.loads({json.dumps(json.dumps(payloads))})\n"
        "args = sys.argv[1:]\n"
        "if 'logs' in args:\n"
        "    raise SystemExit(0)\n"
        "if 'mutatingwebhookconfiguration' in args:\n"
        "    key = 'webhook'\n"
        "elif 'service' in args:\n"
        "    key = 'service'\n"
        "elif 'endpoints' in args:\n"
        "    key = 'endpoints'\n"
        "elif 'pods' in args:\n"
        "    key = 'pods'\n"
        "else:\n"
        "    raise SystemExit(2)\n"
        "print(json.dumps(payloads[key]))\n"
    )


def test_auto_webhook_check_requires_exact_route_ready_pinned_contract(tmp_path: Path) -> None:
    out = _render_auto(tmp_path)
    success_env = _auto_env_with_kubectl(tmp_path / "success", _webhook_kubectl_body())
    success = subprocess.run(
        ["bash", str(AUTO_VALIDATE), "--output-dir", str(out), "--check-webhook", "--allow-current-context"],
        cwd=REPO_ROOT,
        env=success_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert success.returncode == 0, success.stdout + success.stderr
    assert "pod admission route ready (failurePolicy=Ignore)" in success.stdout

    wrong_port_env = _auto_env_with_kubectl(
        tmp_path / "wrong-port", _webhook_kubectl_body(endpoint_port=9444)
    )
    wrong_port = subprocess.run(
        ["bash", str(AUTO_VALIDATE), "--output-dir", str(out), "--check-webhook", "--allow-current-context"],
        cwd=REPO_ROOT,
        env=wrong_port_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert wrong_port.returncode != 0
    assert "pinned 9443/TCP endpoint port" in wrong_port.stdout + wrong_port.stderr

    wrong_policy_env = _auto_env_with_kubectl(
        tmp_path / "wrong-policy", _webhook_kubectl_body(failure_policy="Fail")
    )
    wrong_policy = subprocess.run(
        ["bash", str(AUTO_VALIDATE), "--output-dir", str(out), "--check-webhook", "--allow-current-context"],
        cwd=REPO_ROOT,
        env=wrong_policy_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert wrong_policy.returncode != 0
    assert "pinned chart contract (Ignore)" in wrong_policy.stdout + wrong_policy.stderr


def test_auto_instrumentation_live_check_ignores_only_server_metadata_and_status(
    tmp_path: Path,
) -> None:
    out = _render_auto(tmp_path)
    live = _instrumentation_document(out)
    live["metadata"].update(
        {
            "uid": "server-assigned",
            "resourceVersion": "42",
            "managedFields": [{"manager": "kubectl"}],
        }
    )
    live["status"] = {"conditions": [{"type": "Ready", "status": "True"}]}
    body = "import json\nprint(json.dumps(json.loads(" + repr(json.dumps(live)) + ")))\n"
    env = _auto_env_with_kubectl(tmp_path, body)
    result = subprocess.run(
        ["bash", str(AUTO_VALIDATE), "--output-dir", str(out), "--check-instrumentation", "--allow-current-context"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "managed spec matches rendered CR" in result.stdout


def test_auto_instrumentation_live_check_rejects_managed_spec_drift(tmp_path: Path) -> None:
    out = _render_auto(tmp_path)
    live = _instrumentation_document(out)
    live["spec"]["sampler"]["type"] = "always_off"
    body = "import json\nprint(json.dumps(json.loads(" + repr(json.dumps(live)) + ")))\n"
    env = _auto_env_with_kubectl(tmp_path, body)
    result = subprocess.run(
        ["bash", str(AUTO_VALIDATE), "--output-dir", str(out), "--check-instrumentation", "--allow-current-context"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "managed spec drifted" in result.stdout + result.stderr


def _injection_kubectl_body(
    out: Path,
    *,
    extra_template_annotation: bool = False,
    include_java_hook: bool = True,
) -> str:
    metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    expected_annotations = dict(metadata["targets"][0]["annotations"])
    template_annotations = dict(expected_annotations)
    if extra_template_annotation:
        template_annotations["instrumentation.opentelemetry.io/inject-nodejs"] = "true"
    java_spec = _instrumentation_document(out)["spec"]["java"]
    endpoint = java_spec["env"][0]["value"]
    java_image = java_spec["image"]
    env = [{"name": "OTEL_EXPORTER_OTLP_ENDPOINT", "value": endpoint}]
    if include_java_hook:
        env.append(
            {
                "name": "JAVA_TOOL_OPTIONS",
                "value": "-javaagent:/otel-auto-instrumentation-java-app/javaagent.jar",
            }
        )
    workload = {
        "kind": "Deployment",
        "metadata": {"generation": 3},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": "checkout"}},
            "template": {"metadata": {"annotations": template_annotations}},
        },
        "status": {
            "observedGeneration": 3,
            "replicas": 1,
            "readyReplicas": 1,
            "updatedReplicas": 1,
            "availableReplicas": 1,
        },
    }
    pods = {
        "kind": "List",
        "items": [
            {
                "metadata": {
                    "name": "checkout-api-abc",
                    "namespace": "staging",
                    "labels": {"app": "checkout"},
                    "annotations": expected_annotations,
                },
                "spec": {
                    "initContainers": [
                        {
                            "name": "opentelemetry-auto-instrumentation-java",
                            "image": java_image,
                        }
                    ],
                    "containers": [{"name": "app", "env": env}],
                },
                "status": {
                    "phase": "Running",
                    "conditions": [{"type": "Ready", "status": "True"}],
                },
            }
        ],
    }
    return (
        "import json, sys\n"
        f"workload = json.loads({json.dumps(json.dumps(workload))})\n"
        f"pods = json.loads({json.dumps(json.dumps(pods))})\n"
        "args = sys.argv[1:]\n"
        "print(json.dumps(pods if 'pods' in args else workload))\n"
    )


def test_auto_injection_requires_exact_annotations_and_java_evidence(tmp_path: Path) -> None:
    out = _render_auto(tmp_path)
    success_env = _auto_env_with_kubectl(tmp_path / "success", _injection_kubectl_body(out))
    success = subprocess.run(
        ["bash", str(AUTO_VALIDATE), "--output-dir", str(out), "--check-injection", "--allow-current-context"],
        cwd=REPO_ROOT,
        env=success_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert success.returncode == 0, success.stdout + success.stderr
    assert "exact managed annotations and java evidence" in success.stdout

    annotation_env = _auto_env_with_kubectl(
        tmp_path / "annotation-drift",
        _injection_kubectl_body(out, extra_template_annotation=True),
    )
    annotation_drift = subprocess.run(
        ["bash", str(AUTO_VALIDATE), "--output-dir", str(out), "--check-injection", "--allow-current-context"],
        cwd=REPO_ROOT,
        env=annotation_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert annotation_drift.returncode != 0
    assert "managed pod-template annotations drifted" in annotation_drift.stdout + annotation_drift.stderr

    hook_env = _auto_env_with_kubectl(
        tmp_path / "missing-hook",
        _injection_kubectl_body(out, include_java_hook=False),
    )
    missing_hook = subprocess.run(
        ["bash", str(AUTO_VALIDATE), "--output-dir", str(out), "--check-injection", "--allow-current-context"],
        cwd=REPO_ROOT,
        env=hook_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_hook.returncode != 0
    assert "JAVA_TOOL_OPTIONS" in missing_hook.stdout + missing_hook.stderr


def test_auto_apm_check_fails_when_auth_prerequisites_are_absent(tmp_path: Path) -> None:
    out = _render_auto(tmp_path)
    env = os.environ.copy()
    env.pop("SPLUNK_O11Y_REALM", None)
    env.pop("SPLUNK_O11Y_TOKEN_FILE", None)
    env["SPLUNK_CREDENTIALS_FILE"] = str(tmp_path / "no-credentials")
    result = subprocess.run(
        ["bash", str(AUTO_VALIDATE), "--output-dir", str(out), "--check-apm", "checkout-api", "--allow-current-context"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "required for --check-apm" in result.stdout + result.stderr


def test_auto_apm_header_comes_from_the_validated_no_follow_descriptor() -> None:
    body = AUTO_VALIDATE.read_text(encoding="utf-8")
    assert 'path, header_path = sys.argv[1:]' in body
    assert 'os.O_WRONLY | os.O_NOFOLLOW' in body
    assert 'os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW' not in body
    assert 'os.ftruncate(header_fd, 0)' in body
    assert 'b"X-SF-Token: " + data' in body
    assert '$(<"${SPLUNK_O11Y_TOKEN_FILE}")' not in body


def test_auto_apm_check_fails_when_requested_service_is_absent(tmp_path: Path) -> None:
    out = _render_auto(tmp_path)
    token = tmp_path / "token"
    # Match skills/shared/scripts/write_secret_file.sh, which emits one
    # secret line with a trailing newline.
    token.write_text("valid-token-value\n", encoding="utf-8")
    token.chmod(0o600)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl = fake_bin / "curl"
    curl.write_text(
        """#!/usr/bin/env python3
import json, sys
from pathlib import Path
args = sys.argv[1:]
Path(args[args.index('-o') + 1]).write_text(json.dumps({'nodes':[{'serviceName':'different-service','type':'service'}]}), encoding='utf-8')
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["SPLUNK_O11Y_REALM"] = "us1"
    env["SPLUNK_O11Y_TOKEN_FILE"] = str(token)
    env["SPLUNK_CREDENTIALS_FILE"] = str(tmp_path / "no-credentials")
    result = subprocess.run(
        ["bash", str(AUTO_VALIDATE), "--output-dir", str(out), "--check-apm", "checkout-api", "--allow-current-context"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "is not visible in the scoped APM topology" in result.stdout + result.stderr


def test_auto_apm_query_is_bound_to_service_environment_and_cluster(tmp_path: Path) -> None:
    out = _render_auto(tmp_path)
    token = tmp_path / "token"
    token.write_text("valid-token-value\n", encoding="utf-8")
    token.chmod(0o600)
    capture = tmp_path / "apm-request.json"
    fake_bin = tmp_path / "apm-bin"
    fake_bin.mkdir()
    curl = fake_bin / "curl"
    curl.write_text(
        f"""#!/usr/bin/env python3
import json, sys
from pathlib import Path
args = sys.argv[1:]
request_arg = args[args.index('--data-binary') + 1]
request = json.loads(Path(request_arg[1:]).read_text(encoding='utf-8'))
Path({str(capture)!r}).write_text(json.dumps({{'request': request, 'url': args[-1]}}), encoding='utf-8')
Path(args[args.index('-o') + 1]).write_text(json.dumps({{'nodes':[{{'serviceName':'checkout-api','type':'service'}}]}}), encoding='utf-8')
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["SPLUNK_O11Y_REALM"] = "us1"
    env["SPLUNK_O11Y_TOKEN_FILE"] = str(token)
    env["SPLUNK_CREDENTIALS_FILE"] = str(tmp_path / "no-credentials")
    result = subprocess.run(
        ["bash", str(AUTO_VALIDATE), "--output-dir", str(out), "--check-apm", "checkout-api", "--allow-current-context"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    captured = json.loads(capture.read_text(encoding="utf-8"))
    assert captured["url"] == "https://api.us1.observability.splunkcloud.com/v2/apm/topology"
    filters = {row["name"]: row["value"] for row in captured["request"]["tagFilters"]}
    assert filters == {
        "sf_service": "checkout-api",
        "sf_environment": "staging",
        "k8s.cluster.name": "observability-staging",
    }

    help_result = subprocess.run(
        ["bash", str(AUTO_VALIDATE), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "api.<realm>.observability.splunkcloud.com/v2/apm/topology" in help_result.stdout
    assert "signalfx.com/v2/apm/topology" not in help_result.stdout


def test_auto_injection_and_backup_checks_fail_on_missing_state(tmp_path: Path) -> None:
    out = _render_auto(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    kubectl = fake_bin / "kubectl"
    kubectl.write_text(
        """#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if 'deployment' in args:
    print(json.dumps({'kind':'Deployment',
        'metadata':{'generation':1},
        'spec':{
        'replicas':1,
        'selector':{'matchLabels':{'app':'checkout'}},
        'template':{'metadata':{'annotations':{
            'instrumentation.opentelemetry.io/inject-java':'splunk-otel/splunk-otel-auto-instrumentation'
        }}}
    },
        'status':{'observedGeneration':1,'replicas':1,'readyReplicas':1,'updatedReplicas':1,'availableReplicas':1}
    }))
elif 'configmap' in args:
    print(json.dumps({
        'apiVersion':'v1',
        'kind':'ConfigMap',
        'metadata':{
            'name':'splunk-otel-auto-instrumentation-annotations-backup',
            'namespace':'splunk-otel',
            'labels':{
                'app.kubernetes.io/name':'splunk-otel-auto-instrumentation',
                'app.kubernetes.io/managed-by':'splunk-observability-k8s-auto-instrumentation-setup',
                'splunk.com/ttl':'7d'
            }
        },
        'data':{}
    }))
else:
    print(json.dumps({'kind':'List','items':[]}))
""",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    injection = subprocess.run(
        ["bash", str(AUTO_VALIDATE), "--output-dir", str(out), "--check-injection", "--allow-current-context"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert injection.returncode != 0
    assert "no active pods" in injection.stdout + injection.stderr
    backup = subprocess.run(
        ["bash", str(AUTO_VALIDATE), "--output-dir", str(out), "--check-backup", "--allow-current-context"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert backup.returncode != 0
    assert "backup snapshot for Deployment/staging/checkout-api is missing" in backup.stdout + backup.stderr


def test_scoped_live_validators_fail_when_prerequisites_are_absent(tmp_path: Path) -> None:
    fake_bin = tmp_path / "live-bin"
    fake_bin.mkdir()
    fake_curl = fake_bin / "curl"
    fake_curl.write_text("#!/usr/bin/env bash\nprintf '200'\n", encoding="utf-8")
    fake_curl.chmod(0o755)
    cases = [
        (
            REPO_ROOT / "skills/splunk-observability-aws-integration/scripts/render_assets.py",
            REPO_ROOT / "skills/splunk-observability-aws-integration/template.example",
            REPO_ROOT / "skills/splunk-observability-aws-integration/scripts/validate.sh",
            [],
            "SPLUNK_O11Y_REALM and SPLUNK_O11Y_TOKEN_FILE are required",
        ),
        (
            REPO_ROOT / "skills/splunk-observability-aws-lambda-apm-setup/scripts/render_assets.py",
            REPO_ROOT / "skills/splunk-observability-aws-lambda-apm-setup/template.example",
            REPO_ROOT / "skills/splunk-observability-aws-lambda-apm-setup/scripts/validate.sh",
            ["--accept-beta"],
            "SPLUNK_O11Y_REALM is required",
        ),
        (
            REPO_ROOT / "skills/splunk-observability-cloud-integration-setup/scripts/render_assets.py",
            REPO_ROOT / "skills/splunk-observability-cloud-integration-setup/template.example",
            REPO_ROOT / "skills/splunk-observability-cloud-integration-setup/scripts/validate.sh",
            [],
            "status unreachable",
        ),
    ]
    for index, (renderer, template, validator, extra, expected) in enumerate(cases):
        rendered = tmp_path / f"rendered-{index}"
        render = subprocess.run(
            [sys.executable, str(renderer), "--spec", str(template), "--output-dir", str(rendered), *extra],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert render.returncode == 0, render.stdout + render.stderr
        env = os.environ.copy()
        env["PATH"] = f"{fake_bin}:{env['PATH']}"
        for name in (
            "SPLUNK_O11Y_REALM",
            "SPLUNK_O11Y_TOKEN_FILE",
            "SPLUNK_SEARCH_API_URI",
            "SPLUNK_USER",
            "SPLUNK_PASS",
        ):
            env.pop(name, None)
        env["SPLUNK_CREDENTIALS_FILE"] = str(tmp_path / "no-credentials")
        result = subprocess.run(
            ["bash", str(validator), "--output-dir", str(rendered), "--live"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0, validator
        assert expected in result.stdout + result.stderr
