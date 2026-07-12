#!/usr/bin/env python3
"""Render a clean AWS/EKS/Splunk O11y staging acceptance packet.

The orchestrator only writes local review artifacts. It does not call AWS,
Kubernetes, or Splunk APIs and it never embeds the O11y token in rendered
output. The token file is validated here because the collector renderer needs
its path when it emits the file-backed Kubernetes Secret handoff.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = PROJECT_ROOT / "skills"

AWS_SKILL = SKILLS_ROOT / "splunk-observability-aws-integration"
OTEL_SKILL = SKILLS_ROOT / "splunk-observability-otel-collector-setup"
AUTO_SKILL = SKILLS_ROOT / "splunk-observability-k8s-auto-instrumentation-setup"

AWS_ACCOUNT_RE = re.compile(r"[0-9]{12}")
AWS_REGION_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+")
EKS_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")
DNS_LABEL_RE = re.compile(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?")
WORKLOAD_RE = re.compile(
    r"(?P<kind>Deployment|StatefulSet|DaemonSet)/"
    r"(?P<name>[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?)"
)
REALM_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
O11Y_REALMS = ("us0", "us1", "us2", "us3", "au0", "eu0", "eu1", "eu2", "jp0", "sg0")
LANGUAGES = (
    "java",
    "nodejs",
    "python",
    "dotnet",
    "go",
    "apache-httpd",
    "nginx",
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def validate_fullmatch(pattern: re.Pattern[str], value: str, label: str) -> None:
    if not pattern.fullmatch(value):
        fail(f"{label} has an invalid value")


def stat_fingerprint(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_nlink,
        stat.S_IMODE(info.st_mode),
    )


def read_token_file(path: Path) -> None:
    """Validate the token without returning or logging its value."""

    if not hasattr(os, "O_NOFOLLOW"):
        fail("secure --token-file validation requires O_NOFOLLOW support")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    try:
        before = path.lstat()
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"cannot securely open --token-file: {exc}")

    try:
        opened = os.fstat(descriptor)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(opened.st_mode):
            fail("--token-file must be a non-symlink regular file")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            fail("--token-file changed while it was being opened")
        if stat.S_IMODE(opened.st_mode) != 0o600:
            fail("--token-file must have exact mode 0600")
        if opened.st_nlink != 1:
            fail("--token-file must have exactly one hard link")
        if opened.st_size < 1 or opened.st_size > 16 * 1024:
            fail("--token-file size must be between 1 byte and 16 KiB")
        value = os.read(descriptor, 16 * 1024 + 1)
        after = os.fstat(descriptor)
        path_after = path.stat(follow_symlinks=False)
        if stat_fingerprint(opened) != stat_fingerprint(after):
            fail("--token-file changed while it was being read")
        if (path_after.st_dev, path_after.st_ino) != (after.st_dev, after.st_ino):
            fail("--token-file path changed while it was being read")
        if value.endswith(b"\r\n"):
            token = value[:-2]
        elif value.endswith(b"\n"):
            token = value[:-1]
        else:
            token = value
        if (
            not token
            or len(value) != after.st_size
            or b"\x00" in token
            or b"\r" in token
            or b"\n" in token
            or token != token.strip()
            or any(byte <= 0x20 or byte == 0x7F for byte in token)
            or any(byte > 0x7E for byte in token)
        ):
            fail(
                "--token-file must contain one nonempty printable-ASCII token "
                "with at most one trailing LF or CRLF"
            )
    finally:
        os.close(descriptor)


def load_template(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        fail(f"template is not a YAML mapping: {path}")
    return data


def write_private_yaml(path: Path, payload: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)


def run(command: list[str]) -> None:
    try:
        subprocess.run(command, cwd=PROJECT_ROOT, check=True)
    except subprocess.CalledProcessError as exc:
        fail(f"renderer failed with exit code {exc.returncode}: {Path(command[0]).name}")


def build_aws_spec(args: argparse.Namespace) -> dict[str, Any]:
    spec = load_template(AWS_SKILL / "template.example")
    spec["realm"] = args.o11y_realm
    spec["integration_name"] = args.aws_integration_name
    spec["authentication"]["mode"] = "external_id"
    spec["authentication"]["aws_account_id"] = args.aws_account_id
    spec["authentication"]["iam_role_name"] = "SplunkObservabilityStagingRole"
    spec["authentication"]["role_arn"] = (
        f"arn:aws:iam::{args.aws_account_id}:role/SplunkObservabilityStagingRole"
    )
    spec["authentication"]["external_id"] = ""
    spec["connection"]["mode"] = "polling"
    spec["regions"] = [args.aws_region]
    spec["services"]["mode"] = "explicit"
    spec["services"]["explicit"] = ["AWS/EC2", "AWS/Lambda", "AWS/ApplicationELB"]
    spec["services"]["namespace_sync_rules"] = []
    spec["custom_namespaces"]["simple_list"] = ["ContainerInsights"]
    spec["custom_namespaces"]["sync_rules"] = []
    spec["metric_streams"]["use_metric_streams_sync"] = False
    spec["metric_streams"]["managed_externally"] = False
    spec["metric_streams"]["cloudformation"] = False
    spec["metric_streams"]["use_stack_sets"] = False
    spec["metric_streams"]["terraform"] = False
    spec["multi_account"]["enabled"] = False
    spec["handoffs"]["otel_collector_for_ec2_eks"] = True
    return spec


def build_auto_spec(args: argparse.Namespace) -> dict[str, Any]:
    match = WORKLOAD_RE.fullmatch(args.workload)
    if match is None:  # Already validated; keep this branch explicit for typing.
        fail("--workload is invalid")

    spec = load_template(AUTO_SKILL / "template.example")
    spec["realm"] = args.o11y_realm
    spec["cluster_name"] = args.eks_cluster_name
    spec["deployment_environment"] = "staging"
    spec["distribution"] = "eks"
    spec["namespace"] = args.collector_namespace
    spec["base"] = {
        "release": args.collector_release,
        "namespace": args.collector_namespace,
    }

    instrumentation = dict(spec["instrumentation_crs"][0])
    instrumentation["name"] = args.instrumentation_name
    instrumentation["namespace"] = args.collector_namespace
    instrumentation["languages"] = [args.language]
    instrumentation["runtime_metrics_enabled"] = args.language in {"java", "nodejs"}
    spec["instrumentation_crs"] = [instrumentation]
    spec["namespace_annotations"] = {}
    spec["workload_annotations"] = [
        {
            "kind": match.group("kind"),
            "namespace": args.namespace,
            "name": match.group("name"),
            "language": args.language,
            "cr": f"{args.collector_namespace}/{args.instrumentation_name}",
        }
    ]
    spec["obi"]["enabled"] = False
    return spec


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--aws-account-id", required=True)
    parser.add_argument("--aws-region", required=True)
    parser.add_argument("--eks-cluster-name", required=True)
    parser.add_argument("--kube-context", required=True)
    parser.add_argument("--o11y-realm", choices=O11Y_REALMS, required=True)
    parser.add_argument("--aws-integration-name", required=True)
    parser.add_argument("--collector-namespace", default="splunk-otel")
    parser.add_argument("--collector-release", default="splunk-otel-collector")
    parser.add_argument("--instrumentation-name", default="splunk-otel-staging")
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--workload", required=True)
    parser.add_argument("--language", choices=LANGUAGES, required=True)
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    validate_fullmatch(AWS_ACCOUNT_RE, args.aws_account_id, "--aws-account-id")
    validate_fullmatch(AWS_REGION_RE, args.aws_region, "--aws-region")
    validate_fullmatch(EKS_NAME_RE, args.eks_cluster_name, "--eks-cluster-name")
    validate_fullmatch(REALM_RE, args.o11y_realm, "--o11y-realm")
    validate_fullmatch(DNS_LABEL_RE, args.collector_namespace, "--collector-namespace")
    validate_fullmatch(DNS_LABEL_RE, args.collector_release, "--collector-release")
    validate_fullmatch(DNS_LABEL_RE, args.instrumentation_name, "--instrumentation-name")
    validate_fullmatch(DNS_LABEL_RE, args.namespace, "--namespace")
    validate_fullmatch(WORKLOAD_RE, args.workload, "--workload")
    if args.namespace == args.collector_namespace:
        fail(
            "--namespace must differ from --collector-namespace so the staging "
            "workload namespace cannot inherit Collector pod-log access"
        )
    for label in ("kube-context", "aws-integration-name"):
        value = getattr(args, label.replace("-", "_"))
        if not value.strip() or value != value.strip() or "\n" in value or "\r" in value:
            fail(f"--{label} must be a nonempty single-line value")


def main() -> int:
    args = parse_args()
    validate_args(args)
    read_token_file(args.token_file)

    output_root = args.output_root
    if output_root.is_symlink():
        fail("--output-root must not be a symlink")
    output_root.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(output_root, 0o700)
    if not output_root.is_dir():
        fail("--output-root is not a directory")

    outputs = {
        "otel": output_root / "otel",
        "auto_instrumentation": output_root / "auto-instrumentation",
        "aws_integration": output_root / "aws-integration",
    }
    for label, path in outputs.items():
        if path.exists() or path.is_symlink():
            fail(f"refusing to reuse existing {label} output: {path}")

    with tempfile.TemporaryDirectory(prefix="aws-eks-o11y-specs-") as temp_name:
        temp_root = Path(temp_name)
        os.chmod(temp_root, 0o700)
        aws_spec = temp_root / "aws.yaml"
        auto_spec = temp_root / "auto.yaml"
        write_private_yaml(aws_spec, build_aws_spec(args))
        write_private_yaml(auto_spec, build_auto_spec(args))

        run(
            [
                sys.executable,
                str(AWS_SKILL / "scripts/render_assets.py"),
                "--spec",
                str(aws_spec),
                "--output-dir",
                str(outputs["aws_integration"]),
            ]
        )
        run(
            [
                "bash",
                str(OTEL_SKILL / "scripts/setup.sh"),
                "--render-k8s",
                "--realm",
                args.o11y_realm,
                "--o11y-token-file",
                str(args.token_file),
                "--output-dir",
                str(outputs["otel"]),
                "--namespace",
                args.collector_namespace,
                "--release-name",
                args.collector_release,
                "--cluster-name",
                args.eks_cluster_name,
                "--distribution",
                "eks",
                "--cloud-provider",
                "aws",
                "--kube-context",
                args.kube_context,
                "--eks-cluster-name",
                args.eks_cluster_name,
                "--aws-region",
                args.aws_region,
                "--deployment-environment",
                "staging",
                "--enable-metrics",
                "--enable-traces",
                "--enable-autoinstrumentation",
            ]
        )
        run(
            [
                "bash",
                str(AUTO_SKILL / "scripts/setup.sh"),
                "--render",
                "--gitops-mode",
                "--spec",
                str(auto_spec),
                "--output-dir",
                str(outputs["auto_instrumentation"]),
            ]
        )

    summary = {
        "schema_version": "aws-eks-o11y-staging-render/v1",
        "read_only": True,
        "output_root": str(output_root),
        "outputs": {key: str(value) for key, value in outputs.items()},
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
