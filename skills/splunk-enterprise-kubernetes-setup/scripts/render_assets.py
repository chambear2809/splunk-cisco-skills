#!/usr/bin/env python3
"""Render Splunk Enterprise Kubernetes setup assets.

The renderer intentionally uses only the Python standard library so it can run
in the same minimal environments as the shell skills.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shlex
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, unquote_plus, urlsplit


DEFAULT_OPERATOR_VERSION = "3.1.0"
DEFAULT_POD_VERSION = "10.4.0_1.6.0"
VERIFIED_POD_BUNDLES = {DEFAULT_POD_VERSION}

_SHARED_LIB = Path(__file__).resolve().parents[2] / "shared" / "lib"
if str(_SHARED_LIB) not in sys.path:
    sys.path.insert(0, str(_SHARED_LIB))
from platform_versions import platform_default  # noqa: E402
from compatibility import check_sok_compatibility  # noqa: E402

DEFAULT_SPLUNK_VERSION = platform_default("enterprise_version")
SGT_ACCEPTANCE = "--accept-sgt-current-at-splunk-com"
VERIFIED_SOK_ARTIFACT_SHA256 = {
    "3.1.0": {
        "operator_chart": "c71c1a7fe495c1122c1b0b1b689a366f759107950130c6fcf1f0c453e5d57efd",
        "enterprise_chart": "0d46b934f78a270b2c9bbacb9f442855f125069800d0a1373eb5f21c54e7fc71",
        "crds": "d974a6f2c768ad60d8eb56b2dc571354b4dfe48873cbff4e478ca6aa3e2fb3fe",
    }
}
VERIFIED_SOK_PROBE_SHA256 = {
    "3.1.0": {
        "livenessProbe.sh": "3668ef135e7c7eb4b60b30f95081bee3d33ec1f62f6a109b7ade782f5d3c240d",
        "readinessProbe.sh": "97f88e6e6d0bf1d21f53666a35886a54eaf68c14c8f39844a13a2b8ceb71f4fe",
        "startupProbe.sh": "b8497b1365e88d2321e2802154ecbbadf4305536e2179fac8b11f25067f0c216",
    }
}
SOK_ARCHITECTURES = {"s1", "c3", "m4"}
POD_PROFILES = {
    "pod-small",
    "pod-medium",
    "pod-large",
    "pod-xlarge",
    "pod-small-es",
    "pod-medium-es",
    "pod-large-es",
    "pod-xlarge-es",
    "pod-small-itsi",
    "pod-medium-itsi",
    "pod-large-itsi",
    "pod-xlarge-itsi",
}
SOK_GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "namespace.yaml",
    "apply.sh",
    "bundle-verify.py",
    "crds-install.sh",
    "preflight.sh",
    "server-dry-run.sh",
    "operator-values.yaml",
    "enterprise-values.yaml",
    "helm-install-operator.sh",
    "helm-install-enterprise.sh",
    "create-license-configmap.sh",
    "eks-update-kubeconfig.sh",
    "status.sh",
    "compatibility-check.py",
    "verify-cluster.sh",
    "operator-values-overlay.yaml",
    "enterprise-values-overlay.yaml",
    "splunk-operator-chart.tgz",
    "splunk-enterprise-chart.tgz",
    "splunk-operator-crds.yaml",
    "bundle-manifest.json",
    # Runtime output from the EKS helper. It is intentionally not hashed, but
    # rerendering must remove it so a non-EKS bundle cannot inherit a context.
    "kubeconfig",
}
POD_GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "cluster-config.yaml",
    "preflight.sh",
    "deploy.sh",
    "status-workers.sh",
    "status.sh",
    "get-creds.sh",
    "web-docs.sh",
    "wait-ready.sh",
    "diagnostics.sh",
    "pod-artifacts.py",
    "pod-inputs.py",
    "bundle-verify.py",
    "kubernetes-installer-reviewed",
    "bundle-manifest.json",
}


def parse_args() -> argparse.Namespace:
    def nonempty_eks_name(value: str) -> str:
        if not value:
            raise argparse.ArgumentTypeError("EKS cluster name must not be empty")
        return value

    parser = argparse.ArgumentParser(
        description="Render Splunk Operator or Splunk POD deployment assets."
    )
    parser.add_argument("--target", choices=("sok", "pod"), required=True)
    parser.add_argument(
        "--architecture", choices=sorted(SOK_ARCHITECTURES), default="s1"
    )
    parser.add_argument("--pod-profile", choices=sorted(POD_PROFILES), default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--namespace", default="splunk-operator")
    parser.add_argument("--operator-namespace", default="splunk-operator")
    parser.add_argument("--release-name", default="splunk-enterprise")
    parser.add_argument("--operator-release-name", default="splunk-operator")
    parser.add_argument("--operator-version", default=DEFAULT_OPERATOR_VERSION)
    parser.add_argument("--operator-image", default="")
    parser.add_argument("--chart-version", default="")
    parser.add_argument("--operator-chart-archive", default="")
    parser.add_argument("--enterprise-chart-archive", default="")
    parser.add_argument("--crd-manifest", default="")
    parser.add_argument("--splunk-version", default=DEFAULT_SPLUNK_VERSION)
    parser.add_argument("--splunk-image", default="")
    parser.add_argument("--storage-class", default="")
    parser.add_argument("--etc-storage", default="10Gi")
    parser.add_argument("--var-storage", default="100Gi")
    parser.add_argument("--standalone-replicas", default="1")
    parser.add_argument("--indexer-replicas", default="3")
    parser.add_argument("--search-head-replicas", default="3")
    parser.add_argument("--site-count", default="2")
    parser.add_argument("--site-zones", default="")
    parser.add_argument("--manager-site", default="site1")
    parser.add_argument("--search-head-site", default="site2")
    parser.add_argument("--manager-zone", default="")
    parser.add_argument("--search-head-zone", default="")
    parser.add_argument("--license-file", default="")
    parser.add_argument("--smartstore-bucket", default="")
    parser.add_argument("--smartstore-prefix", default="")
    parser.add_argument("--smartstore-indexes", default="main")
    parser.add_argument(
        "--smartstore-provider", choices=("aws", "minio"), default="aws"
    )
    parser.add_argument("--smartstore-region", default="")
    parser.add_argument("--smartstore-endpoint", default="")
    parser.add_argument("--smartstore-secret-ref", default="")
    parser.add_argument(
        "--confirm-smartstore-index-inventory", action="store_true"
    )
    parser.add_argument("--confirm-smartstore-path-ownership", action="store_true")
    parser.add_argument("--eks-cluster-name", default=None, type=nonempty_eks_name)
    parser.add_argument("--aws-region", default="")
    parser.add_argument("--controller-ips", default="")
    parser.add_argument("--worker-ips", default="")
    parser.add_argument("--ssh-user", default="splunkadmin")
    parser.add_argument("--ssh-private-key-file", default="/path/to/ssh-private-key")
    parser.add_argument("--indexer-apps", default="")
    parser.add_argument("--search-apps", default="")
    parser.add_argument("--standalone-apps", default="")
    parser.add_argument("--premium-apps", default="")
    parser.add_argument("--accept-splunk-general-terms", action="store_true")
    parser.add_argument("--kubernetes-version", default="")
    parser.add_argument("--expected-kube-context", default="")
    parser.add_argument("--expected-api-server", default="")
    parser.add_argument("--expected-cluster-uid", default="")
    parser.add_argument("--allow-unverified-versions", action="store_true")
    parser.add_argument(
        "--operator-scope", choices=("cluster", "namespace"), default="namespace"
    )
    parser.add_argument("--watch-namespaces", default="")
    parser.add_argument(
        "--deployment-profile",
        choices=("development", "production"),
        default="development",
    )
    parser.add_argument("--allow-upgrade", action="store_true")
    parser.add_argument(
        "--confirm-splunk-10-4-upgrade-readiness", action="store_true"
    )
    parser.add_argument("--enterprise-values-overlay", default="")
    parser.add_argument("--operator-values-overlay", default="")
    parser.add_argument("--indexing-ingestion-separation", action="store_true")
    parser.add_argument("--ingestor-replicas", default="3")
    parser.add_argument("--ingestor-service-account", default="")
    parser.add_argument("--queue-provider", choices=("sqs", "sqs_cp"), default="sqs")
    parser.add_argument("--queue-name", default="")
    parser.add_argument("--queue-dlq", default="")
    parser.add_argument("--queue-region", default="")
    parser.add_argument("--queue-endpoint", default="")
    parser.add_argument("--queue-secret-ref", default="")
    parser.add_argument("--object-storage-path", default="")
    parser.add_argument("--object-storage-endpoint", default="")
    parser.add_argument("--existing-license-manager", default="")
    parser.add_argument("--existing-license-manager-namespace", default="")
    parser.add_argument("--splunk-service-account", default="")
    parser.add_argument("--splunk-irsa-role-arn", default="")
    parser.add_argument("--splunk-irsa-token-expiration", default="3600")
    parser.add_argument("--disable-monitoring-console", action="store_true")
    parser.add_argument("--pod-version", default=DEFAULT_POD_VERSION)
    parser.add_argument("--confirm-new-pod-install", action="store_true")
    parser.add_argument(
        "--installer-path", default="/path/to/kubernetes-installer-standalone"
    )
    parser.add_argument("--installer-sha256", default="")
    parser.add_argument("--primary-search-name", default="")
    parser.add_argument("--secondary-search-name", default="")
    parser.add_argument("--cluster-manager-apps", default="")
    parser.add_argument("--search-deployer-apps", default="")
    parser.add_argument("--license-manager-apps", default="")
    parser.add_argument("--itsi-apps", default="")
    parser.add_argument("--itsi-source-bundle", default="")
    parser.add_argument("--itsi-source-sha256", default="")
    parser.add_argument("--itsi-jdk-sha256", default="")
    parser.add_argument("--ingress-certificate-file", default="")
    parser.add_argument("--ingress-private-key-file", default="")
    parser.add_argument("--ingress-domain", default="")
    parser.add_argument("--ingress-ca-file", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def yaml_quote(value: object) -> str:
    text = str(value)
    return json.dumps(text)


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


def bool_word(value: bool) -> str:
    return "true" if value else "false"


def ensure_positive_int(
    value: str, option: str, *, maximum: int = 2_147_483_647
) -> int:
    if not re.fullmatch(r"[0-9]{1,10}", value or ""):
        die(f"{option} must be a positive integer no greater than {maximum}.")
    parsed = int(value)
    if parsed < 1 or parsed > maximum:
        die(f"{option} must be a positive integer no greater than {maximum}.")
    return parsed


def splunk_image(args: argparse.Namespace) -> str:
    return args.splunk_image or f"splunk/splunk:{args.splunk_version}"


def operator_image(args: argparse.Namespace) -> str:
    return (
        args.operator_image
        or f"docker.io/splunk/splunk-operator:{args.operator_version}"
    )


def validate_oci_image_reference(value: str, option: str) -> None:
    """Validate the Docker/OCI name grammar used by Kubernetes image fields."""
    if (
        not value
        or len(value) > 2048
        or re.search(r"[\x00-\x20\x7f]", value)
        or "://" in value
        or value.count("@") > 1
    ):
        die(f"{option} must be a valid OCI image reference without whitespace or a URI scheme.")
    reference, separator, digest = value.partition("@")
    if separator and not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        die(f"{option} digest must be canonical lowercase sha256:<64 hex>.")
    if not reference or reference.startswith(('/', '.')) or reference.endswith(('/', '.')):
        die(f"{option} has an invalid OCI repository name.")

    last_slash = reference.rfind("/")
    last_colon = reference.rfind(":")
    if last_colon > last_slash:
        repository = reference[:last_colon]
        tag = reference[last_colon + 1 :]
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", tag):
            die(f"{option} has an invalid OCI tag.")
    else:
        repository = reference
    if not repository or len(repository) > 255:
        die(f"{option} has an invalid OCI repository name.")

    components = repository.split("/")
    if any(not item for item in components):
        die(f"{option} has an invalid OCI repository path.")
    first = components[0]
    has_registry = (
        len(components) > 1
        and (first == "localhost" or "." in first or ":" in first or first.startswith("["))
    )
    path_components = components[1:] if has_registry else components
    path_component = re.compile(
        r"[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*"
    )
    if not path_components or any(
        not path_component.fullmatch(item) for item in path_components
    ):
        die(f"{option} has an invalid lowercase OCI repository path.")

    if has_registry:
        registry = first
        host = registry
        port = ""
        if registry.startswith("["):
            match = re.fullmatch(r"\[([^]]+)](?::([0-9]+))?", registry)
            if not match:
                die(f"{option} has an invalid OCI registry address.")
            host, port = match.groups()
            try:
                ipaddress.IPv6Address(host)
            except ValueError:
                die(f"{option} has an invalid OCI registry IPv6 address.")
        else:
            if registry.count(":") > 1:
                die(f"{option} must bracket an IPv6 registry address.")
            if ":" in registry:
                host, port = registry.rsplit(":", 1)
                if not port:
                    die(f"{option} has an empty OCI registry port.")
            try:
                ipaddress.IPv4Address(host)
            except ValueError:
                if host != "localhost" and (
                    len(host) > 253
                    or any(
                        not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", label)
                        for label in host.split(".")
                    )
                ):
                    die(f"{option} has an invalid lowercase OCI registry hostname.")
        if port and (not port.isdigit() or not 1 <= int(port) <= 65535):
            die(f"{option} has an invalid OCI registry port.")


def image_numeric_tag(image: str) -> str:
    reference, separator, digest = image.partition("@")
    if separator and not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        return ""
    name = reference.rsplit("/", 1)[-1]
    if ":" not in name:
        return ""
    tag = name.rsplit(":", 1)[-1]
    return tag if re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9_.-]+)?", tag) else ""


def version_major(version: str) -> int:
    match = re.match(r"^([0-9]+)", version)
    return int(match.group(1)) if match else 0


def chart_version(args: argparse.Namespace) -> str:
    return args.chart_version or args.operator_version


def assert_terms(args: argparse.Namespace) -> None:
    if args.target != "sok":
        return
    if not args.accept_splunk_general_terms:
        die(
            "Splunk Operator reconciliation requires explicit "
            "--accept-splunk-general-terms."
        )


def validate_k8s_name(value: str, option: str) -> None:
    if not re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", value or ""):
        die(f"{option} must be a valid Kubernetes DNS label.")
    if len(value) > 63:
        die(f"{option} must be 63 characters or fewer.")


def validate_helm_release_name(value: str, option: str) -> None:
    validate_k8s_name(value, option)
    if len(value) > 53:
        die(f"{option} must be 53 characters or fewer for Helm.")


def validate_release_version(
    value: str,
    option: str,
    allow_v: bool = False,
    allow_suffix: bool = False,
) -> None:
    core = r"v?\d+\.\d+(?:\.\d+)?" if allow_v else r"\d+\.\d+\.\d+"
    suffix = r"(?:[-+][0-9A-Za-z][0-9A-Za-z._-]*)?" if allow_suffix else ""
    if not re.fullmatch(rf"{core}{suffix}", value or ""):
        die(f"{option} must be a canonical three-part release version.")


def validate_k8s_subdomain(value: str, option: str) -> None:
    label = r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?"
    if not re.fullmatch(rf"{label}(?:\.{label})*", value or ""):
        die(f"{option} must be a valid Kubernetes DNS subdomain.")
    if len(value) > 253:
        die(f"{option} must be 253 characters or fewer.")
    if any(len(part) > 63 for part in value.split(".")):
        die(f"{option} must use DNS labels of 63 characters or fewer.")


def validate_k8s_label_value(value: str, option: str) -> None:
    if not value or len(value) > 63 or not re.fullmatch(
        r"[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?", value
    ):
        die(f"{option} must be a valid Kubernetes label value of at most 63 characters.")


def validate_endpoint(value: str, option: str, *, require_https: bool = False) -> None:
    if not value:
        return
    try:
        parsed = urlsplit(value)
    except ValueError:
        die(f"{option} must be a valid absolute HTTP(S) URL.")
    if (
        re.search(r"[\x00-\x20\x7f]", value)
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
    ):
        die(f"{option} must be an absolute HTTP(S) URL.")
    if parsed.username or parsed.password:
        die(f"{option} must not contain inline credentials.")
    if parsed.netloc.endswith(":"):
        die(f"{option} contains an empty port.")
    if parsed.query or parsed.fragment:
        die(f"{option} must not contain a query string or fragment.")
    if parsed.path not in {"", "/"}:
        die(f"{option} must identify an endpoint origin without a path.")
    try:
        port = parsed.port
    except ValueError:
        die(f"{option} contains an invalid port.")
    if port is not None and not 1 <= port <= 65535:
        die(f"{option} contains an invalid port.")
    hostname = parsed.hostname or ""
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        dns_label = r"[A-Za-z0-9](?:[-A-Za-z0-9]*[A-Za-z0-9])?"
        if (
            len(hostname) > 253
            or not re.fullmatch(rf"{dns_label}(?:\.{dns_label})*", hostname)
            or any(len(part) > 63 for part in hostname.split("."))
        ):
            die(f"{option} contains an invalid DNS hostname.")
    if require_https and parsed.scheme != "https":
        die(
            f"{option} must use HTTPS for production or credential-bearing "
            "object-store traffic."
        )


def validate_storage_quantity(value: str, option: str) -> None:
    """Accept positive, whole Kubernetes storage quantities.

    Storage size changes can be destructive and the Operator otherwise fails
    only after creating resources. The skill intentionally uses a narrower
    subset than the full Kubernetes quantity grammar: positive whole units in
    Ki/Mi/Gi/Ti/Pi/Ei or k/M/G/T/P/E.
    """
    if not re.fullmatch(
        r"[1-9][0-9]*(?:Ki|Mi|Gi|Ti|Pi|Ei|k|M|G|T|P|E)", value or ""
    ):
        die(
            f"{option} must be a positive whole Kubernetes storage quantity "
            "such as 10Gi or 1Ti."
        )


def validate_s3_bucket(value: str, option: str, *, aws: bool = False) -> None:
    if not value:
        return
    if (
        len(value) < 3
        or len(value) > 63
        or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*[a-z0-9]", value)
        or ".." in value
        or ".-" in value
        or "-." in value
    ):
        die(f"{option} must be a valid DNS-compatible S3 bucket name.")
    if aws and (
        value.startswith(("xn--", "sthree-", "amzn-s3-demo-"))
        or value.endswith(
            ("-s3alias", "--ol-s3", ".mrap", "--x-s3", "--table-s3")
        )
    ):
        die(f"{option} uses an AWS-reserved S3 bucket prefix or suffix.")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return
    die(f"{option} must not be formatted as an IP address.")


def validate_object_path(value: str, option: str) -> None:
    if not value:
        return
    if (
        value.startswith(("/", "s3://", "http://", "https://"))
        or value.endswith("/")
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or re.search(r"[\x00-\x20?#\\]", value)
    ):
        die(
            f"{option} must be a relative bucket or bucket/prefix path without "
            "a scheme, traversal, whitespace, query, or fragment."
        )


def validate_sqs_name(value: str, option: str) -> None:
    if value and not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        die(f"{option} must be a valid SQS queue name.")


def validate_aws_region(value: str, option: str) -> None:
    if value and not re.fullmatch(r"[a-z]{2,4}(?:-[a-z0-9]+)+-[1-9][0-9]*", value):
        die(f"{option} must be a valid AWS region name such as us-east-1.")


def validate_aws_iam_role_arn(value: str, option: str) -> None:
    if not re.fullmatch(
        r"arn:(?:aws|aws-us-gov|aws-cn):iam::[0-9]{12}:role/"
        r"[A-Za-z0-9+=,.@_/-]{1,512}",
        value,
    ) or "//" in value:
        die(f"{option} must be an exact AWS IAM role ARN without wildcards.")


def validate_sok_queue_region(value: str, option: str) -> None:
    # Keep this narrower than the general AWS-region parser: it mirrors the
    # SOK 3.1 Queue CRD SQSSpec.authRegion OpenAPI pattern exactly.
    if value and not re.fullmatch(
        r"(?:us|ap|eu|me|af|sa|ca|cn|il)(?:-[a-z]+){1,3}-[0-9]", value
    ):
        die(
            f"{option} is outside the AWS region grammar accepted by the "
            "SOK 3.1 Queue CRD."
        )


def validate_eks_cluster_name(value: str, option: str) -> None:
    if value and (
        len(value) > 100
        or not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z_-]*", value)
    ):
        die(
            f"{option} must be a 1..100 character EKS cluster name using "
            "letters, digits, underscore, or dash."
        )


def aws_service_endpoint(
    service: str, region: str, explicit: str = "", endpoint_option: str = ""
) -> str:
    if explicit:
        return explicit
    if region.startswith(("us-iso-", "us-isob-", "us-isof-", "eu-isoe-")):
        die(
            f"An explicit HTTPS {endpoint_option or '--' + service + '-endpoint'} "
            "is required for AWS "
            f"isolated region {region}."
        )
    if region.startswith("cn-"):
        suffix = "amazonaws.com.cn"
    elif region.startswith("eusc-"):
        suffix = "amazonaws.eu"
    else:
        suffix = "amazonaws.com"
    return f"https://{service}.{region}.{suffix}"


def validate_license_configmap_file(value: str) -> None:
    if not value:
        return
    path = Path(value).expanduser()
    if not re.fullmatch(r"[-._A-Za-z0-9]+", path.name):
        die(
            "--license-file basename must be a valid Kubernetes ConfigMap key "
            "using only letters, digits, dash, underscore, or dot."
        )
    if len(path.name) > 253:
        die("--license-file basename must be 253 characters or fewer.")
    if path.stat().st_size == 0:
        die("--license-file must not be empty.")
    if path.stat().st_size > 900 * 1024:
        die("--license-file is too large for the guarded Kubernetes ConfigMap path.")


def validate_nonempty_path_list(value: str, option: str) -> None:
    if value and not split_csv(value):
        die(f"{option} must contain at least one non-empty CSV value.")


def effective_splunk_version(args: argparse.Namespace) -> str:
    if args.splunk_image:
        tag = image_numeric_tag(args.splunk_image)
        if tag:
            return tag
        # A custom image with an opaque tag or digest cannot inherit the
        # separately supplied version claim; its compatibility is unverified.
        return ""
    return args.splunk_version


def validate_existing_file(value: str, option: str) -> None:
    if value:
        path = Path(value).expanduser()
        if path.is_symlink():
            die(f"{option} must not be a symbolic link: {value}")
        if not path.is_file():
            die(f"{option} file not found: {value}")


def canonical_file(value: str) -> str:
    return str(Path(value).expanduser().resolve()) if value else ""


def yaml_mapping_entries(line: str) -> Iterable[tuple[str, str]]:
    """Yield simple YAML/JSON mapping entries without loading untrusted YAML.

    Values overlays may use block YAML, flow YAML, or JSON (which is valid
    YAML). This conservative scanner deliberately recognizes quoted keys and
    nested flow mappings so guardrails cannot be bypassed by syntax alone.
    """

    entry = re.compile(
        r"(?=(?:^|[,{])\s*(?:-\s*)?"
        r'(?:"([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\']*)\'|([^\s{},:#][^{},:#]*?))'
        r"\s*:\s*([^,}#]*))"
    )
    for match in entry.finditer(line):
        if match.group(1) is not None:
            try:
                key = json.loads(f'"{match.group(1)}"')
            except json.JSONDecodeError as exc:
                raise ValueError("double-quoted YAML keys must use JSON-safe escapes") from exc
        else:
            key = next(group for group in match.groups()[1:3] if group is not None)
        yield key, match.group(4).strip()


def validate_overlay_ast(text: str, path: Path, option: str) -> None:
    """Validate the fully decoded YAML object graph before copying an overlay."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ModuleNotFoundError:
        die(
            f"{option} requires PyYAML 6.x for strict structural validation; "
            "install the repository requirements before using values overlays."
        )
    yaml_major = int(str(getattr(yaml, "__version__", "0")).split(".", 1)[0])
    if yaml_major != 6:
        die(f"{option} requires PyYAML 6.x; found {yaml.__version__!r}.")

    class StrictLoader(yaml.SafeLoader):
        pass

    def construct_mapping(loader: StrictLoader, node: object, deep: bool = False) -> dict:
        if not isinstance(node, yaml.MappingNode):
            raise yaml.constructor.ConstructorError(
                None, None, "expected a mapping node", getattr(node, "start_mark", None)
            )
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "overlay keys must be strings",
                    key_node.start_mark,
                )
            if key in result:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"duplicate key {key!r}",
                    key_node.start_mark,
                )
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    StrictLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping
    )

    try:
        for token in yaml.scan(text):
            if isinstance(
                token,
                (
                    yaml.tokens.AliasToken,
                    yaml.tokens.AnchorToken,
                    yaml.tokens.DirectiveToken,
                    yaml.tokens.TagToken,
                ),
            ):
                raise ValueError(
                    "aliases, anchors, directives, and explicit tags are not allowed"
                )
        documents = list(yaml.load_all(text, Loader=StrictLoader))
    except (yaml.YAMLError, ValueError) as exc:
        die(f"{option} is not strict, unambiguous YAML at {path}: {exc}")
    if len(documents) != 1 or not isinstance(documents[0], dict):
        die(f"{option} must contain exactly one YAML mapping document: {path}")

    protected_keys = {
        "allowprivilegeescalation", "args", "automountserviceaccounttoken",
        "capabilities", "clusterwideaccess", "command", "containers",
        "defaultsurl", "defaultsurlapps", "dnsconfig", "dnspolicy",
        "ephemeralcontainers", "extraenv", "extraenvs", "extramanifests",
        "fsgroup", "fullnameoverride", "hostaliases", "hostipc",
        "hostnetwork", "hostpath", "hostpid", "image", "initcontainers",
        "lifecycle", "licenseurl", "livenessprobe", "nameoverride",
        "namespaceoverride", "podsecuritycontext", "privileged", "procmount",
        "readinessprobe", "readonlyrootfilesystem", "runasgroup",
        "runasnonroot", "runasuser", "runtimeclassname", "securitycontext",
        "selinuxoptions", "serviceaccount", "serviceaccountname",
        "service", "servicetemplate", "shareprocessnamespace", "splunkgeneralterms",
        "startupprobe", "sysctls", "volumemounts", "watchnamespaces",
    }
    strong_sensitive = {
        "accesskey", "accesskeyid", "apikey", "clientkey", "clientsecret",
        "credential", "credentials", "hectoken", "passphrase", "password",
        "privatekey", "secretaccesskey", "secretkey", "stringdata", "token",
    }
    sensitive_suffixes = (
        "accesskey", "accesskeyid", "apikey", "clientsecret", "credential",
        "credentials", "hectoken", "passphrase", "password", "privatekey",
        "secret", "secretaccesskey", "secretkey", "token", "auth",
    )
    reference_suffixes = ("secretkeyref", "secretref", "secretname", "valuefrom")
    secret_env = re.compile(
        r"(?:password|passphrase|token|secret|credential|auth|access[_-]?key|"
        r"api[_-]?key|client[_-]?key|private[_-]?key|hec[_-]?token)",
        re.IGNORECASE,
    )
    volume_secret_keys = {
        "defaultMode", "items", "optional", "secretName",
    }
    volume_item_keys = {"key", "mode", "path"}

    def safe_remote_path(value: object, label: str, location: str) -> str:
        if not isinstance(value, str) or not value or len(value) > 1024:
            die(f"{option} requires a non-empty {label} at {location}.")
        if (
            value.startswith("/")
            or "\\" in value
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or any(part in {"", ".", ".."} for part in value.rstrip("/").split("/"))
        ):
            die(f"{option} has an unsafe {label} at {location}: {value!r}.")
        return value

    def app_repo_name(value: object, label: str, location: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(
            r"[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?", value
        ):
            die(f"{option} has an invalid App Framework {label} at {location}.")
        return value

    def validate_app_repo(value: object, location: str) -> None:
        if not isinstance(value, dict) or not value:
            die(f"{option} App Framework appRepo must be a non-empty map at {location}.")
        normalized_location = re.sub(r"[^a-z0-9]", "", location.lower())
        allowed_repo = {
            "appInstallPeriodSeconds", "appSources", "appsRepoPollIntervalSeconds",
            "defaults", "installMaxRetries", "maxConcurrentAppDownloads", "volumes",
        }
        unknown = set(value) - allowed_repo
        if unknown:
            die(f"{option} App Framework appRepo has unsupported keys at {location}: {sorted(unknown)}")
        if "appInstallPeriodSeconds" in value:
            die(
                f"{option} App Framework appInstallPeriodSeconds is support-directed "
                f"only and is not accepted by the strict bundle at {location}; "
                "use a Splunk Support-reviewed direct-CR handoff."
            )
        for key, minimum, maximum in (
            ("installMaxRetries", 0, 2**31 - 1),
            ("maxConcurrentAppDownloads", 0, 2**63 - 1),
        ):
            item = value.get(key)
            if item is not None and (
                not isinstance(item, int)
                or isinstance(item, bool)
                or not minimum <= item <= maximum
            ):
                die(f"{option} App Framework {key} must be {minimum}..{maximum} at {location}.")
        poll_interval = value.get("appsRepoPollIntervalSeconds")
        if poll_interval is not None and (
            not isinstance(poll_interval, int)
            or isinstance(poll_interval, bool)
            or (poll_interval != 0 and not 60 <= poll_interval <= 86400)
        ):
            die(
                f"{option} App Framework appsRepoPollIntervalSeconds must be 0 "
                f"or 60..86400 at {location}."
            )
        defaults = value.get("defaults", {})
        if not isinstance(defaults, dict) or set(defaults) - {
            "scope", "volumeName"
        }:
            die(f"{option} App Framework defaults are malformed at {location}.")
        default_scope = defaults.get("scope")
        if default_scope is not None and default_scope not in {
            "local", "cluster", "premiumApps"
        }:
            die(f"{option} App Framework default scope is unsupported at {location}.")
        if default_scope == "cluster" and not any(
            role in normalized_location
            for role in ("clustermanager", "searchheadcluster")
        ):
            die(
                f"{option} cluster App Framework default scope is invalid for "
                f"this CR at {location}."
            )
        if default_scope == "premiumApps" and not any(
            role in normalized_location
            for role in ("standalone", "searchheadcluster")
        ):
            die(
                f"{option} premiumApps default scope is invalid for this CR "
                f"at {location}."
            )
        default_volume = defaults.get("volumeName")
        if default_volume is not None:
            app_repo_name(default_volume, "default volumeName", location)

        volumes = value.get("volumes")
        if not isinstance(volumes, list) or not volumes:
            die(f"{option} App Framework needs at least one volume at {location}.")
        volume_names = set()
        volume_allowed = {
            "endpoint", "name", "path", "provider", "region", "secretRef",
            "storageType",
        }
        provider_storage = {
            "aws": "s3", "minio": "s3", "azure": "blob", "gcp": "gcs"
        }
        for index, volume in enumerate(volumes):
            item_location = f"{location}.volumes[{index}]"
            if not isinstance(volume, dict) or set(volume) - volume_allowed:
                die(f"{option} App Framework volume is malformed at {item_location}.")
            name = app_repo_name(volume.get("name"), "volume name", item_location)
            if name in volume_names:
                die(f"{option} App Framework volume names must be unique at {location}.")
            volume_names.add(name)
            provider = volume.get("provider")
            storage_type = volume.get("storageType")
            if provider_storage.get(provider) != storage_type:
                die(
                    f"{option} App Framework provider/storageType pair is unsupported "
                    f"at {item_location}."
                )
            if provider == "aws":
                region = volume.get("region")
                if not isinstance(region, str) or not region:
                    die(f"{option} AWS App Framework volume requires region at {item_location}.")
                validate_aws_region(
                    region, f"{option} AWS App Framework region at {item_location}"
                )
            safe_remote_path(volume.get("path"), "volume path", item_location)
            endpoint = volume.get("endpoint")
            if not isinstance(endpoint, str):
                die(f"{option} App Framework volume endpoint is missing at {item_location}.")
            validate_endpoint(
                endpoint,
                f"{option} App Framework endpoint at {item_location}",
                require_https=True,
            )
            parsed_endpoint = urlsplit(endpoint)
            endpoint_hostname = parsed_endpoint.hostname or ""
            if endpoint_hostname.lower() == "localhost":
                die(f"{option} App Framework endpoint cannot use localhost at {item_location}.")
            try:
                endpoint_ip = ipaddress.ip_address(endpoint_hostname)
            except ValueError:
                endpoint_ip = None
            if endpoint_ip and (
                endpoint_ip.is_loopback
                or endpoint_ip.is_unspecified
                or endpoint_ip.is_link_local
                or endpoint_ip.is_multicast
                or endpoint_ip.is_reserved
            ):
                die(f"{option} App Framework endpoint address is unsafe at {item_location}.")
            if "secretRef" in volume:
                if not isinstance(volume["secretRef"], str):
                    die(f"{option} App Framework secretRef is invalid at {item_location}.")
                validate_k8s_subdomain(
                    volume["secretRef"],
                    f"{option} App Framework secretRef at {item_location}",
                )

        sources = value.get("appSources")
        if not isinstance(sources, list) or not sources:
            die(f"{option} App Framework needs at least one appSource at {location}.")
        source_names = set()
        source_targets = set()
        source_allowed = {
            "location", "name", "premiumAppsProps", "scope", "volumeName"
        }
        if "indexercluster" in normalized_location:
            die(f"{option} App Framework is unsupported on IndexerCluster at {location}.")
        for index, source in enumerate(sources):
            item_location = f"{location}.appSources[{index}]"
            if not isinstance(source, dict) or set(source) - source_allowed:
                die(f"{option} App Framework appSource is malformed at {item_location}.")
            name = app_repo_name(source.get("name"), "appSource name", item_location)
            if name in source_names:
                die(f"{option} App Framework appSource names must be unique at {location}.")
            source_names.add(name)
            source_location = safe_remote_path(
                source.get("location"), "appSource location", item_location
            )
            scope = source.get("scope", default_scope)
            if scope not in {"local", "cluster", "premiumApps"}:
                die(f"{option} App Framework appSource scope is unsupported at {item_location}.")
            volume_name = source.get("volumeName", default_volume)
            if volume_name not in volume_names:
                die(f"{option} App Framework appSource references an unknown volume at {item_location}.")
            # SOK 3.1 detects duplicates by concatenating volumeName+location
            # without a separator. Mirror that upstream behavior so otherwise
            # distinct pairs cannot fail only after admission/reconciliation.
            target = (scope, f"{volume_name}{source_location}")
            if target in source_targets:
                die(
                    f"{option} App Framework appSources collide under the SOK "
                    f"3.1 scope/volume+location key at {location}."
                )
            source_targets.add(target)
            if scope == "cluster" and not any(
                role in normalized_location for role in ("clustermanager", "searchheadcluster")
            ):
                die(f"{option} cluster App Framework scope is invalid for this CR at {item_location}.")
            if scope == "premiumApps" and not any(
                role in normalized_location for role in ("standalone", "searchheadcluster")
            ):
                die(f"{option} premiumApps scope is invalid for this CR at {item_location}.")
            if "premiumAppsProps" in source and scope != "premiumApps":
                die(f"{option} premiumAppsProps requires premiumApps scope at {item_location}.")
            premium = source.get("premiumAppsProps")
            if scope == "premiumApps" and premium is None:
                die(f"{option} premiumApps scope requires premiumAppsProps at {item_location}.")
            if premium is not None:
                if not isinstance(premium, dict) or premium.get("type") != "enterpriseSecurity":
                    die(f"{option} premiumAppsProps must select enterpriseSecurity at {item_location}.")
                es_defaults = premium.get("esDefaults", {})
                if not isinstance(es_defaults, dict) or set(es_defaults) - {"sslEnablement"}:
                    die(f"{option} premiumAppsProps.esDefaults is malformed at {item_location}.")
                ssl_mode = es_defaults.get("sslEnablement", "strict")
                if ssl_mode not in {"strict", "auto", "ignore"}:
                    die(f"{option} premiumApps SSL mode is unsupported at {item_location}.")
                if "searchheadcluster" in normalized_location and ssl_mode == "auto":
                    die(f"{option} SearchHeadCluster premiumApps forbids sslEnablement auto.")

    def reference_only(value: object) -> bool:
        if not isinstance(value, dict) or not value:
            return False
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if normalized.endswith(reference_suffixes):
                if child in (None, ""):
                    return False
                continue
            if not reference_only(child):
                return False
        return True

    def valid_secret_volume(value: object) -> bool:
        if not isinstance(value, dict) or set(value) - volume_secret_keys:
            return False
        name = value.get("secretName")
        if not isinstance(name, str) or not re.fullmatch(
            r"[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?", name
        ):
            return False
        items = value.get("items", [])
        return isinstance(items, list) and all(
            isinstance(item, dict) and not set(item) - volume_item_keys
            for item in items
        )

    def validate_supported_overlay_shape(payload: object) -> None:
        """Reject Helm keys that the pinned charts would silently ignore."""
        if not isinstance(payload, dict) or not payload:
            die(f"{option} must be a non-empty YAML mapping.")
        operator_keys = {
            "affinity",
            "annotations",
            "imagePullSecrets",
            "labels",
            "nodeSelector",
            "podAnnotations",
            "podLabels",
            "resources",
            "terminationGracePeriodSeconds",
            "tolerations",
        }
        enterprise_roles = {
            "clusterManager",
            "indexerCluster",
            "ingestorCluster",
            "licenseManager",
            "monitoringConsole",
            "searchHeadCluster",
            "standalone",
        }
        enterprise_keys = {
            "additionalAnnotations",
            "additionalLabels",
            "affinity",
            "appRepo",
            "resources",
            "tolerations",
            "topologySpreadConstraints",
        }
        if option == "--operator-values-overlay":
            if set(payload) != {"splunkOperator"}:
                unknown = sorted(set(payload) - {"splunkOperator"})
                die(
                    f"{option} supports only the splunkOperator root; "
                    f"unsupported or misspelled roots: {unknown}."
                )
            settings = payload["splunkOperator"]
            if not isinstance(settings, dict) or not settings:
                die(f"{option} splunkOperator must be a non-empty mapping.")
            unknown = set(settings) - operator_keys
            if unknown:
                die(
                    f"{option} has unsupported or misspelled splunkOperator keys: "
                    f"{sorted(unknown)}."
                )
            for annotation_field in ("annotations", "podAnnotations"):
                annotations = settings.get(annotation_field, {})
                if isinstance(annotations, dict) and any(
                    str(key).startswith("eks.amazonaws.com/")
                    for key in annotations
                ):
                    die(
                        f"{option} cannot set EKS identity annotations in "
                        f"{annotation_field}; use a dedicated reviewed identity path."
                    )
            return
        unknown_roles = set(payload) - enterprise_roles
        if unknown_roles:
            die(
                f"{option} has unsupported or misspelled role roots: "
                f"{sorted(unknown_roles)}."
            )
        for role, settings in payload.items():
            if not isinstance(settings, dict) or not settings:
                die(f"{option} role {role!r} must be a non-empty mapping.")
            unknown = set(settings) - enterprise_keys
            if unknown:
                die(
                    f"{option} has unsupported or misspelled keys for {role}: "
                    f"{sorted(unknown)}."
                )
            annotations = settings.get("additionalAnnotations", {})
            if isinstance(annotations, dict) and any(
                str(key).startswith("eks.amazonaws.com/") for key in annotations
            ):
                die(
                    f"{option} cannot override EKS identity injection through "
                    f"{role}.additionalAnnotations; use the first-class IRSA inputs."
                )

    validate_supported_overlay_shape(documents[0])

    def inspect_string(value: str, location: str) -> None:
        if value == "clusterWithPreConfig":
            die(
                f"{option} uses unsupported SOK 3.1 App Framework scope "
                f"clusterWithPreConfig at {location}."
            )
        decoded_values = [value]
        for _ in range(2):
            decoded = unquote_plus(decoded_values[-1])
            if decoded == decoded_values[-1]:
                break
            decoded_values.append(decoded)
        secret_signatures = (
            re.compile(
                r"-----BEGIN (?:ENCRYPTED |RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
                re.IGNORECASE,
            ),
            re.compile(r"\b(?:AKIA|ASIA|AIDA|AROA|AIPA|ANPA|ANVA|ASCA)[A-Z0-9]{16}\b"),
            re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
            re.compile(r"\bxox(?:a|b|p|r|s)-[A-Za-z0-9-]{12,}\b"),
            re.compile(
                r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
            ),
            re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{16,}\b", re.IGNORECASE),
        )
        if any(
            pattern.search(decoded)
            for decoded in decoded_values
            for pattern in secret_signatures
        ):
            die(
                f"{option} contains credential or private-key material at "
                f"{location}; use a Kubernetes Secret-backed handoff."
            )
        candidates = [value]
        candidates.extend(
            match.group(0)
            for match in re.finditer(
                r"[A-Za-z][A-Za-z0-9+.-]*:(?://)[^\s'\"<>]+", value
            )
        )
        for candidate in candidates:
            while re.match(
                r"^[A-Za-z][A-Za-z0-9+.-]*:(?=[A-Za-z][A-Za-z0-9+.-]*://)",
                candidate,
            ):
                candidate = candidate.split(":", 1)[1]
            try:
                parsed = urlsplit(candidate)
            except ValueError as exc:
                die(f"{option} has an invalid URI at {location}: {exc}")
            if parsed.scheme and parsed.netloc and (
                parsed.username is not None or parsed.password is not None
            ):
                die(
                    f"{option} embeds URI userinfo credentials at {location}; "
                    "use a Kubernetes Secret-backed handoff."
                )
            for query_key, query_value in parse_qsl(
                parsed.query, keep_blank_values=True
            ):
                normalized_query_key = re.sub(
                    r"[^a-z0-9]", "", unquote_plus(query_key).lower()
                )
                if (
                    normalized_query_key in strong_sensitive
                    or normalized_query_key.endswith(sensitive_suffixes)
                    or normalized_query_key == "sig"
                    or normalized_query_key.endswith("signature")
                ) and query_value:
                    die(
                        f"{option} embeds a credential query parameter at {location}."
                    )
            for fragment_key, fragment_value in parse_qsl(
                parsed.fragment, keep_blank_values=True
            ):
                normalized_fragment_key = re.sub(
                    r"[^a-z0-9]", "", unquote_plus(fragment_key).lower()
                )
                if (
                    normalized_fragment_key in strong_sensitive
                    or normalized_fragment_key.endswith(sensitive_suffixes)
                    or normalized_fragment_key == "sig"
                    or normalized_fragment_key.endswith("signature")
                    or normalized_fragment_key in {"accountkey", "sharedaccesssignature"}
                ) and fragment_value:
                    die(
                        f"{option} embeds a credential fragment parameter at {location}."
                    )
        for assignment in re.finditer(
            r"(?i)(?:^|[;?&#\s])([A-Za-z][A-Za-z0-9_ -]*)\s*=\s*([^;&\s]+)",
            value,
        ):
            assignment_key = re.sub(
                r"[^a-z0-9]", "", assignment.group(1).lower()
            )
            if (
                assignment_key in strong_sensitive
                or assignment_key.endswith(sensitive_suffixes)
                or assignment_key in {"accountkey", "sharedaccesssignature"}
            ):
                die(f"{option} embeds a credential assignment at {location}.")
        if re.search(
            r"(?i)\bjdbc:oracle:thin:[^/\s:@]+/[^@\s]+@[^\s]+", value
        ):
            die(f"{option} embeds Oracle JDBC username/password at {location}.")
        if "\n" not in value and not re.match(
            r"^\s*[A-Za-z_][A-Za-z0-9_.-]*\s*:", value
        ):
            return
        try:
            embedded = yaml.load(value, Loader=StrictLoader)
        except yaml.YAMLError:
            return
        if isinstance(embedded, (dict, list)):
            walk(embedded, f"{location}<embedded>")

    def walk(value: object, location: str) -> None:
        if isinstance(value, str):
            inspect_string(value, location)
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{location}[{index}]")
            return
        if not isinstance(value, dict):
            return
        kind = value.get("kind")
        if isinstance(kind, str) and kind.lower() == "secret":
            die(f"{option} cannot define a Kubernetes Secret at {location}")
        env_name = value.get("name")
        if isinstance(env_name, str) and secret_env.search(env_name) and "value" in value:
            if value.get("value") not in (None, ""):
                die(
                    f"{option} contains literal sensitive environment variable "
                    f"{env_name!r} at {location}; use valueFrom."
                )
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            child_location = f"{location}.{key}"
            if key.lower().endswith(".enterprise.splunk.com/paused"):
                die(
                    f"{option} cannot pause a managed Splunk CR at {child_location}."
                )
            if key.lower() == "enterprise.splunk.com/admin-managed-pv":
                die(
                    f"{option} cannot enable admin-managed PVs at {child_location}; "
                    "use a reviewed PV label/selector/capacity/binding handoff."
                )
            if normalized in protected_keys:
                die(
                    f"{option} cannot override protected field {key!r} at "
                    f"{child_location}; use the first-class CLI option."
                )
            if normalized == "volumes" and ".appRepo" not in child_location:
                die(
                    f"{option} cannot add arbitrary Kubernetes volumes at "
                    f"{child_location}; use a reviewed platform/PVC handoff."
                )
            if normalized == "apprepo":
                validate_app_repo(child, child_location)
            if normalized == "secret" and valid_secret_volume(child):
                walk(child, child_location)
                continue
            is_reference = normalized.endswith(reference_suffixes)
            is_sensitive = normalized in strong_sensitive or normalized.endswith(
                sensitive_suffixes
            )
            if is_sensitive and not is_reference and child not in (None, ""):
                if not reference_only(child):
                    die(
                        f"{option} contains literal or ambiguous sensitive field "
                        f"{key!r} at {child_location}; use an explicit Secret reference."
                    )
            walk(child, child_location)

    walk(documents[0], "$overlay")


def validate_non_secret_overlay(value: str, option: str) -> None:
    if not value:
        return
    path = Path(value).expanduser()
    secret_keys = {
        "accesskey",
        "accesskeyid",
        "apikey",
        "clientkey",
        "clientsecret",
        "credential",
        "credentials",
        "hectoken",
        "passphrase",
        "password",
        "privatekey",
        "secretaccesskey",
        "secretkey",
        "stringdata",
        "token",
    }
    protected_keys = {
        "adminmanagedpv", "allowprivilegeescalation", "args",
        "automountserviceaccounttoken",
        "capabilities", "clusterwideaccess", "command", "containers",
        "defaultsurl", "defaultsurlapps", "dnsconfig", "dnspolicy",
        "enterprisesplunkcomadminmanagedpv", "ephemeralcontainers", "extraenv", "extraenvs",
        "extramanifests",
        "fsgroup",
        "fullnameoverride",
        "hostaliases", "hostipc", "hostnetwork", "hostpath", "hostpid",
        "image",
        "initcontainers", "lifecycle", "licenseurl", "livenessprobe",
        "nameoverride",
        "namespaceoverride",
        "podsecuritycontext", "privileged", "procmount", "readinessprobe",
        "readonlyrootfilesystem", "runasgroup", "runasnonroot", "runasuser",
        "runtimeclassname", "securitycontext", "selinuxoptions",
        "service", "serviceaccount", "serviceaccountname", "servicetemplate",
        "shareprocessnamespace",
        "splunkgeneralterms",
        "startupprobe", "sysctls", "volumemounts",
        "watchnamespaces",
    }
    secret_env_name = re.compile(
        r"(?:password|passphrase|token|secret|credential|auth|access[_-]?key|"
        r"api[_-]?key|client[_-]?key|private[_-]?key|hec[_-]?token)",
        re.IGNORECASE,
    )
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        die(f"{option} must be UTF-8 YAML: {path}")
    if len(text.encode("utf-8")) > 2 * 1024 * 1024:
        die(f"{option} exceeds the 2 MiB reviewed overlay limit: {path}")
    validate_overlay_ast(text, path, option)
    lines = text.splitlines()

    def flow_is_balanced(line: str) -> bool:
        stack = []
        quote = ""
        escaped = False
        pairs = {"{": "}", "[": "]"}
        for character in line:
            if quote:
                if quote == '"' and escaped:
                    escaped = False
                elif quote == '"' and character == "\\":
                    escaped = True
                elif character == quote:
                    quote = ""
                continue
            if character in {'"', "'"}:
                quote = character
            elif character == "#":
                break
            elif character in pairs:
                stack.append(pairs[character])
            elif character in {"}", "]"}:
                if not stack or stack.pop() != character:
                    return False
        return not stack and not quote

    for line_number, line in enumerate(lines, 1):
        uncommented = line.split("#", 1)[0]
        escaped = False
        double_quote_open = False
        for character in uncommented:
            if escaped:
                escaped = False
            elif character == "\\" and double_quote_open:
                escaped = True
            elif character == '"':
                double_quote_open = not double_quote_open
        if double_quote_open or escaped:
            die(
                f"{option} cannot use multiline double-quoted scalars at "
                f"{path}:{line_number}; keep every quoted value on one line."
            )
        if re.search(
            r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@",
            uncommented,
            re.IGNORECASE,
        ):
            die(
                f"{option} cannot embed URL userinfo credentials at "
                f"{path}:{line_number}; use a Kubernetes Secret-backed handoff."
            )
        for quoted in re.finditer(r'"(?:[^"\\]|\\.)*"', uncommented):
            try:
                decoded = json.loads(quoted.group(0))
            except json.JSONDecodeError:
                die(
                    f"{option} uses a double-quoted YAML escape outside the "
                    f"reviewed JSON-safe subset at {path}:{line_number}."
                )
            parsed_quoted_url = urlsplit(decoded)
            if parsed_quoted_url.scheme and parsed_quoted_url.netloc and (
                parsed_quoted_url.username is not None
                or parsed_quoted_url.password is not None
            ):
                die(
                    f"{option} cannot embed URL userinfo credentials at "
                    f"{path}:{line_number}; use a Kubernetes Secret-backed handoff."
                )
        if any(character in line for character in "{}[]") and not flow_is_balanced(line):
            die(
                f"{option} cannot use multiline or malformed YAML flow collections "
                f"at {path}:{line_number}; keep each {{...}} or [...] value on one line."
            )
        stripped = line.lstrip()
        if stripped.startswith(("? ", "?\t", ": ", ":\t")):
            die(
                f"{option} cannot use YAML explicit mapping-key syntax at "
                f"{path}:{line_number}; use an ordinary key: value mapping."
            )
        if re.search(r"(?:^|[\s:[{,])(?:&|\*)[A-Za-z0-9_-]+", line):
            die(
                f"{option} cannot use YAML anchors or aliases at "
                f"{path}:{line_number}; keep reviewed values explicit."
            )
        if re.search(
            r"(?:^|\s)(?:!!?[A-Za-z][A-Za-z0-9:/.+-]*|!<[^>\r\n]+>)",
            line.split("#", 1)[0],
        ) or stripped.startswith("%TAG"):
            die(
                f"{option} cannot use YAML tags at {path}:{line_number}; "
                "keep reviewed keys and values explicit."
            )
        try:
            entries = list(yaml_mapping_entries(line))
        except ValueError as exc:
            die(f"{option} has an unsupported quoted key at {path}:{line_number}: {exc}")
        for key, scalar in entries:
            normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())
            scalar_text = re.sub(
                r"^(?:(?:!!str|![^\s]+|&[^\s]+)\s+)+",
                "",
                scalar,
                flags=re.IGNORECASE,
            ).strip()
            if scalar_text.startswith('"'):
                try:
                    scalar_value = json.loads(scalar_text)
                except json.JSONDecodeError:
                    die(f"{option} has an invalid quoted scalar at {path}:{line_number}.")
            elif scalar_text.startswith("'") and scalar_text.endswith("'"):
                scalar_value = scalar_text[1:-1].replace("''", "'")
            else:
                scalar_value = scalar_text
            if isinstance(scalar_value, str):
                parsed_url = urlsplit(scalar_value)
                if parsed_url.scheme and parsed_url.netloc and (
                    parsed_url.username is not None or parsed_url.password is not None
                ):
                    die(
                        f"{option} cannot embed URL userinfo credentials at "
                        f"{path}:{line_number}; use a Kubernetes Secret-backed handoff."
                    )
            if scalar == "":
                current_indent = len(line) - len(line.lstrip())
                for offset, nested in enumerate(lines[line_number:], line_number + 1):
                    nested_text = nested.strip()
                    if not nested_text or nested_text.startswith("#"):
                        continue
                    nested_indent = len(nested) - len(nested.lstrip())
                    if (
                        nested_indent > current_indent
                        and not re.match(
                            r"^(?:-\s+|(?:[^:#]|:(?!\s))*:\s*)",
                            nested_text,
                        )
                    ):
                        die(
                            f"{option} cannot use an indented scalar continuation at "
                            f"{path}:{offset}; keep scalar values on the mapping line."
                        )
                    break
            if normalized_key == "kind" and scalar_value.lower() == "secret":
                die(
                    f"{option} cannot define a Kubernetes Secret at "
                    f"{path}:{line_number}; create it through a secret-managed handoff."
                )
            if normalized_key in protected_keys:
                die(
                    f"{option} cannot override protected compatibility field "
                    f"{key!r} at {path}:{line_number}; use the first-class CLI option."
                )
            if normalized_key == "secret" and scalar == "":
                current_indent = len(line) - len(line.lstrip())
                allowed_volume_keys = {
                    "defaultmode", "items", "key", "mode", "optional", "path",
                    "secretname",
                }
                found_secret_name = False
                for offset, nested in enumerate(lines[line_number:], line_number + 1):
                    nested_text = nested.strip()
                    if not nested_text or nested_text.startswith("#"):
                        continue
                    nested_indent = len(nested) - len(nested.lstrip())
                    if nested_indent <= current_indent:
                        break
                    try:
                        nested_entries = list(yaml_mapping_entries(nested))
                    except ValueError as exc:
                        die(
                            f"{option} has an unsupported Secret-volume key at "
                            f"{path}:{offset}: {exc}"
                        )
                    for nested_key, nested_scalar in nested_entries:
                        normalized_nested = re.sub(
                            r"[^a-z0-9]", "", nested_key.lower()
                        )
                        if normalized_nested not in allowed_volume_keys:
                            die(
                                f"{option} has unsupported field {nested_key!r} in a "
                                f"Secret volume at {path}:{offset}."
                            )
                        if normalized_nested == "secretname":
                            found_secret_name = bool(
                                re.fullmatch(
                                    r"[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?",
                                    nested_scalar.strip('"\''),
                                )
                            )
                if not found_secret_name:
                    die(
                        f"{option} Secret volume at {path}:{line_number} must "
                        "reference an explicit existing secretName."
                    )
                continue
            reference_kind = next(
                (
                    suffix
                    for suffix in (
                        "secretkeyref",
                        "secretref",
                        "secretname",
                        "valuefrom",
                    )
                    if normalized_key.endswith(suffix)
                ),
                "",
            )
            sensitive_key = normalized_key in secret_keys or normalized_key.endswith(
                (
                    "accesskey",
                    "accesskeyid",
                    "apikey",
                    "clientsecret",
                    "credential",
                    "credentials",
                    "password",
                    "passphrase",
                    "privatekey",
                    "secret",
                    "secretaccesskey",
                    "secretkey",
                    "token",
                    "auth",
                )
            )
            if reference_kind:
                empty_values = {"", "{}", '""', "''", "null", "~"}
                if reference_kind in {"valuefrom", "secretkeyref"}:
                    if scalar not in empty_values and not scalar.lstrip().startswith("{"):
                        die(
                            f"{option} has a malformed {key!r} reference at "
                            f"{path}:{line_number}; use a mapping, not a scalar value."
                        )
                elif scalar not in empty_values and not re.fullmatch(
                    r"[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?", scalar_value
                ):
                    die(
                        f"{option} has a malformed Kubernetes Secret reference at "
                        f"{path}:{line_number}."
                    )
                continue
            if not sensitive_key:
                continue
            if scalar in {"", "{}", "[]", '""', "''", "null", "~"}:
                if scalar == "":
                    current_indent = len(line) - len(line.lstrip())
                    for offset, nested in enumerate(
                        lines[line_number:], line_number + 1
                    ):
                        nested_text = nested.strip()
                        if not nested_text or nested_text.startswith("#"):
                            continue
                        nested_indent = len(nested) - len(nested.lstrip())
                        if nested_indent > current_indent:
                            die(
                                f"{option} cannot use a nested or block value for "
                                f"sensitive key {key!r} at {path}:{line_number}; "
                                "use an explicit Kubernetes Secret reference."
                            )
                        break
                continue
            die(
                f"{option} appears to contain an inline secret at "
                f"{path}:{line_number}; use a Kubernetes Secret and secretRef."
            )

        if re.search(
            r"\b(?:RELATED_IMAGE_SPLUNK_ENTERPRISE|SPLUNK_GENERAL_TERMS)\b",
            line,
            re.IGNORECASE,
        ):
            die(
                f"{option} cannot override protected operator environment fields at "
                f"{path}:{line_number}."
            )

        flow_values = {key.lower(): scalar for key, scalar in entries}
        flow_name_raw = flow_values.get("name", "").strip()
        if flow_name_raw.startswith('"'):
            try:
                flow_name = json.loads(flow_name_raw)
            except json.JSONDecodeError:
                die(f"{option} has an invalid quoted name at {path}:{line_number}.")
        elif flow_name_raw.startswith("'") and flow_name_raw.endswith("'"):
            flow_name = flow_name_raw[1:-1].replace("''", "'")
        else:
            flow_name = flow_name_raw
        flow_value = flow_values.get("value", "")
        if (
            flow_name
            and secret_env_name.search(flow_name)
            and flow_value not in {"", '""', "''", "null", "~"}
        ):
            die(
                f"{option} appears to contain an inline secret at "
                f"{path}:{line_number}; use valueFrom with a Kubernetes Secret."
            )

        env_match = re.match(
            r"^(\s*)-\s*(?:['\"]name['\"]|name)\s*:\s*(.*?)\s*$",
            line,
        )
        if not env_match:
            continue
        raw_env_name = env_match.group(2).split("#", 1)[0].strip()
        if raw_env_name.startswith('"'):
            try:
                env_name = json.loads(raw_env_name)
            except json.JSONDecodeError:
                die(f"{option} has an invalid quoted name at {path}:{line_number}.")
        elif raw_env_name.startswith("'") and raw_env_name.endswith("'"):
            env_name = raw_env_name[1:-1].replace("''", "'")
        else:
            env_name = raw_env_name
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", env_name or ""):
            die(
                f"{option} list name must be an explicit one-line scalar at "
                f"{path}:{line_number}."
            )
        if not secret_env_name.search(env_name):
            continue
        env_indent = len(env_match.group(1))
        for offset, nested in enumerate(lines[line_number:], line_number + 1):
            nested_indent = len(nested) - len(nested.lstrip())
            if nested.strip() and nested_indent <= env_indent:
                break
            value_match = re.match(
                r"^\s*(?:['\"]value['\"]|value)\s*:\s*(.*?)\s*$", nested
            )
            if value_match and value_match.group(1) == "":
                die(
                    f"{option} cannot use a nested/multiline literal for a "
                    f"sensitive environment variable at {path}:{offset}; use valueFrom."
                )
            if value_match and value_match.group(1) not in {
                "",
                '""',
                "''",
                "null",
                "~",
            }:
                die(
                    f"{option} appears to contain an inline secret at "
                    f"{path}:{offset}; use valueFrom with a Kubernetes Secret."
                )


def app_repo_identity_references(value: str) -> tuple[set[str], set[str]]:
    """Return reviewed App Framework Secret and service-account references."""
    if not value:
        return set(), set()
    import yaml  # type: ignore[import-untyped]

    payload = yaml.safe_load(Path(value).expanduser().read_text(encoding="utf-8"))
    secrets_found: set[str] = set()
    service_accounts: set[str] = set()

    def walk(item: object) -> None:
        if isinstance(item, list):
            for child in item:
                walk(child)
            return
        if not isinstance(item, dict):
            return
        for key, child in item.items():
            if re.sub(r"[^a-z0-9]", "", str(key).lower()) == "apprepo" and isinstance(child, dict):
                for volume in child.get("volumes", []):
                    if not isinstance(volume, dict):
                        continue
                    if isinstance(volume.get("secretRef"), str):
                        secrets_found.add(volume["secretRef"])
                    if isinstance(volume.get("serviceAccount"), str):
                        service_accounts.add(volume["serviceAccount"])
            walk(child)

    walk(payload)
    return secrets_found, service_accounts


def validate_addresses(value: str, expected: int, option: str) -> list[str]:
    addresses = split_csv(value)
    if not addresses:
        return []
    if len(addresses) != expected:
        die(f"{option} requires exactly {expected} addresses for this POD profile.")
    private_networks = tuple(
        ipaddress.IPv4Network(cidr)
        for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    )
    for address in addresses:
        try:
            parsed = ipaddress.IPv4Address(address)
        except ValueError:
            die(f"{option} contains an invalid IPv4 address: {address}")
        if (
            parsed.is_unspecified
            or parsed.is_loopback
            or parsed.is_link_local
            or parsed.is_multicast
            or parsed.is_reserved
            or int(parsed) == 0xFFFFFFFF
            or not (parsed.is_global or any(parsed in network for network in private_networks))
        ):
            die(f"{option} contains a non-unicast node address: {address}")
    if len(set(addresses)) != len(addresses):
        die(f"{option} contains duplicate addresses.")
    return addresses


def pod_bundle_tuple(value: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)_(\d+)\.(\d+)\.(\d+)", value or "")
    if not match:
        die("--pod-version must use <Splunk>_<installer>, for example 10.4.0_1.6.0.")
    parts = tuple(int(item) for item in match.groups())
    return parts[:3], parts[3:]


def validate_splunk_indexes(value: str, option: str) -> list[str]:
    indexes = split_csv(value)
    if not indexes:
        die(f"{option} must contain at least one index.")
    if len(indexes) != len(set(indexes)):
        die(f"{option} must not contain duplicate indexes.")
    for index in indexes:
        if not re.fullmatch(r"[_A-Za-z][_A-Za-z0-9-]{0,79}", index):
            die(f"{option} contains an invalid Splunk index name: {index}")
    return indexes


def validate_linux_username(value: str, option: str) -> None:
    if (
        not value
        or len(value) > 32
        or not re.fullmatch(r"[a-z_][a-z0-9_-]*\$?", value)
    ):
        die(
            f"{option} must be a 1..32 character lowercase Linux account name "
            "(letters, digits, underscore, dash, with an optional trailing $)."
        )


def validate_common(args: argparse.Namespace) -> None:
    standalone_replicas = ensure_positive_int(
        args.standalone_replicas, "--standalone-replicas"
    )
    indexer_replicas = ensure_positive_int(args.indexer_replicas, "--indexer-replicas")
    search_head_replicas = ensure_positive_int(
        args.search_head_replicas, "--search-head-replicas"
    )
    ensure_positive_int(args.site_count, "--site-count", maximum=63)
    if args.target == "sok":
        validate_release_version(
            args.operator_version,
            "--operator-version",
            allow_suffix=args.allow_unverified_versions,
        )
        validate_release_version(
            chart_version(args),
            "--chart-version",
            allow_suffix=args.allow_unverified_versions,
        )
        validate_release_version(
            args.splunk_version,
            "--splunk-version",
            allow_suffix=args.allow_unverified_versions,
        )
        if args.kubernetes_version:
            validate_release_version(
                args.kubernetes_version,
                "--kubernetes-version",
                allow_v=True,
                allow_suffix=True,
            )
        cluster_identity = (
            args.expected_kube_context,
            args.expected_api_server,
            args.expected_cluster_uid,
        )
        if any(cluster_identity) and not all(cluster_identity):
            die(
                "--expected-kube-context, --expected-api-server, and "
                "--expected-cluster-uid must be supplied together."
            )
        if args.expected_api_server:
            validate_endpoint(
                args.expected_api_server,
                "--expected-api-server",
                require_https=True,
            )
        if args.expected_cluster_uid and not re.fullmatch(
            r"[0-9a-fA-F-]{16,64}", args.expected_cluster_uid
        ):
            die("--expected-cluster-uid is not a valid Kubernetes UID.")
        validate_k8s_name(args.namespace, "--namespace")
        validate_k8s_name(args.operator_namespace, "--operator-namespace")
        validate_helm_release_name(args.release_name, "--release-name")
        validate_helm_release_name(
            args.operator_release_name, "--operator-release-name"
        )
        validate_oci_image_reference(operator_image(args), "--operator-image")
        validate_oci_image_reference(splunk_image(args), "--splunk-image")
        assert_terms(args)
        custom_operator_tag = image_numeric_tag(operator_image(args))
        if (
            args.operator_image
            and (
                not custom_operator_tag
                or custom_operator_tag
                not in {
                    args.operator_version,
                    f"{args.operator_version}-distroless",
                }
            )
            and not args.allow_unverified_versions
        ):
            die(
                "--operator-image must have a numeric tag matching "
                "--operator-version for a verified bundle."
            )
        if (
            chart_version(args) != args.operator_version
            and not args.allow_unverified_versions
        ):
            die(
                "--chart-version must match --operator-version for a verified "
                "SOK release bundle. Use --allow-unverified-versions only after review."
            )
        validate_existing_file(
            args.enterprise_values_overlay, "--enterprise-values-overlay"
        )
        validate_existing_file(
            args.operator_values_overlay, "--operator-values-overlay"
        )
        artifact_inputs = {
            "--operator-chart-archive": args.operator_chart_archive,
            "--enterprise-chart-archive": args.enterprise_chart_archive,
            "--crd-manifest": args.crd_manifest,
        }
        supplied_artifacts = [name for name, value in artifact_inputs.items() if value]
        if supplied_artifacts and len(supplied_artifacts) != len(artifact_inputs):
            die(
                "Local SOK supply-chain mode requires --operator-chart-archive, "
                "--enterprise-chart-archive, and --crd-manifest together."
            )
        for option, artifact in artifact_inputs.items():
            validate_existing_file(artifact, option)
        if supplied_artifacts:
            verified_hashes = VERIFIED_SOK_ARTIFACT_SHA256.get(args.operator_version)
            actual_hashes = {
                "operator_chart": file_sha256(
                    Path(args.operator_chart_archive).expanduser()
                ),
                "enterprise_chart": file_sha256(
                    Path(args.enterprise_chart_archive).expanduser()
                ),
                "crds": file_sha256(Path(args.crd_manifest).expanduser()),
            }
            if verified_hashes != actual_hashes:
                if args.deployment_profile == "production" or not args.allow_unverified_versions:
                    die(
                        "Local SOK artifact hashes do not match the verified official "
                        f"{args.operator_version} release artifacts."
                    )
        validate_non_secret_overlay(
            args.enterprise_values_overlay, "--enterprise-values-overlay"
        )
        validate_non_secret_overlay(
            args.operator_values_overlay, "--operator-values-overlay"
        )
        validate_existing_file(args.license_file, "--license-file")
        validate_license_configmap_file(args.license_file)
        validate_storage_quantity(args.etc_storage, "--etc-storage")
        validate_storage_quantity(args.var_storage, "--var-storage")
        if args.storage_class:
            validate_k8s_subdomain(args.storage_class, "--storage-class")
        if (
            args.operator_scope == "namespace"
            and args.namespace != args.operator_namespace
        ):
            die(
                "Namespace-scoped SOK requires --namespace and --operator-namespace "
                "to match; use --operator-scope cluster to watch another namespace."
            )
        watched = split_csv(args.watch_namespaces) or [args.namespace]
        for namespace in watched:
            validate_k8s_name(namespace, "--watch-namespaces")
        if args.operator_scope == "cluster" and args.namespace not in watched:
            die("--watch-namespaces must include the Splunk Enterprise namespace.")
        if len(watched) > 1:
            die(
                "This renderer manages one Splunk Enterprise namespace per bundle. "
                "Use a reviewed multi-namespace/operator handoff with an external "
                "License Manager for additional deployment namespaces."
            )
        if args.operator_scope == "namespace" and args.watch_namespaces:
            die("--watch-namespaces is valid only with --operator-scope cluster.")
        if args.eks_cluster_name and not args.aws_region:
            die("--aws-region is required with --eks-cluster-name.")
        validate_eks_cluster_name(args.eks_cluster_name, "--eks-cluster-name")
        validate_aws_region(args.aws_region, "--aws-region")
        if args.smartstore_bucket:
            if args.smartstore_provider == "aws" and not args.smartstore_region:
                die("--smartstore-region is required for the aws SmartStore provider.")
            if args.smartstore_provider == "minio" and not args.smartstore_endpoint:
                die("--smartstore-endpoint is required for the minio SmartStore provider.")
            if args.smartstore_provider == "minio" and args.smartstore_region:
                die("--smartstore-region is not used with --smartstore-provider minio.")
        validate_s3_bucket(
            args.smartstore_bucket,
            "--smartstore-bucket",
            aws=args.smartstore_provider == "aws",
        )
        validate_aws_region(args.smartstore_region, "--smartstore-region")
        if args.smartstore_prefix:
            validate_object_path(args.smartstore_prefix, "--smartstore-prefix")
        validate_splunk_indexes(args.smartstore_indexes, "--smartstore-indexes")
        validate_endpoint(
            args.smartstore_endpoint,
            "--smartstore-endpoint",
            require_https=(
                args.deployment_profile == "production"
                or bool(args.smartstore_secret_ref)
                or bool(args.splunk_service_account)
            ),
        )
        if args.smartstore_bucket and args.smartstore_provider == "aws":
            aws_service_endpoint(
                "s3",
                args.smartstore_region,
                args.smartstore_endpoint,
                "--smartstore-endpoint",
            )
        validate_endpoint(
            args.queue_endpoint,
            "--queue-endpoint",
            require_https=args.indexing_ingestion_separation,
        )
        validate_endpoint(
            args.object_storage_endpoint,
            "--object-storage-endpoint",
            require_https=args.indexing_ingestion_separation,
        )
        if args.smartstore_secret_ref:
            validate_k8s_subdomain(
                args.smartstore_secret_ref, "--smartstore-secret-ref"
            )
        if args.smartstore_secret_ref and args.splunk_service_account:
            die(
                "Use either --smartstore-secret-ref or --splunk-service-account "
                "for SmartStore authentication, not both."
            )
        if args.architecture == "s1" and standalone_replicas != 1:
            die(
                "The verified SOK S1 preset requires exactly one Standalone. "
                "Multiple independent Standalone instances need a direct-CR design "
                "with separate data and SmartStore paths."
            )
        if args.architecture == "c3" and indexer_replicas < 3:
            die("--indexer-replicas must be at least 3 for SOK C3.")
        if args.architecture == "m4" and indexer_replicas < 2:
            die("--indexer-replicas must be at least 2 per M4 site.")
        if args.architecture in {"c3", "m4"} and search_head_replicas < 3:
            die("--search-head-replicas must be at least 3 for SOK C3/M4.")
        if args.architecture == "m4":
            site_count = ensure_positive_int(
                args.site_count, "--site-count", maximum=63
            )
            if site_count != 2:
                die(
                    "The verified SOK 3.1 M4 chart contract requires exactly 2 sites "
                    "because its SVA preset fixes multisite replication and search "
                    "factor totals at 2. Use a reviewed direct-CR/custom-factor "
                    "handoff for 3..63 sites."
                )
            if args.site_zones and len(split_csv(args.site_zones)) != site_count:
                die("--site-zones must have one zone per M4 site.")
            if args.site_zones and len(set(split_csv(args.site_zones))) != site_count:
                die("--site-zones values must be unique.")
            for zone in split_csv(args.site_zones):
                validate_k8s_label_value(zone, "--site-zones")
            if args.manager_zone:
                validate_k8s_label_value(args.manager_zone, "--manager-zone")
            if args.search_head_zone:
                validate_k8s_label_value(args.search_head_zone, "--search-head-zone")
            site_names = [f"site{index}" for index in range(1, site_count + 1)]
            if args.manager_site not in site_names:
                die("--manager-site must identify one of the rendered M4 sites.")
            if args.search_head_site not in site_names:
                die("--search-head-site must identify one of the rendered M4 sites.")
            if args.site_zones:
                site_zone_map = dict(zip(site_names, split_csv(args.site_zones)))
                if (
                    args.manager_zone
                    and site_zone_map[args.manager_site] != args.manager_zone
                ):
                    die("--manager-zone must match the zone assigned to --manager-site.")
                if (
                    args.search_head_zone
                    and site_zone_map[args.search_head_site] != args.search_head_zone
                ):
                    die(
                        "--search-head-zone must match the zone assigned to "
                        "--search-head-site."
                    )
        if args.deployment_profile == "production":
            if args.allow_unverified_versions:
                die(
                    "Production SOK cannot bypass the verified compatibility "
                    "matrix with --allow-unverified-versions."
                )
            if not args.storage_class:
                die("--storage-class is required for the production profile.")
            if not args.smartstore_bucket:
                die("--smartstore-bucket is required for production SOK deployments.")
            if not (args.license_file or args.existing_license_manager):
                die(
                    "Production SOK requires --license-file or "
                    "--existing-license-manager."
                )
            if not (args.smartstore_secret_ref or args.splunk_service_account):
                die(
                    "Production SmartStore requires --smartstore-secret-ref or "
                    "--splunk-service-account for workload identity."
                )
            if args.architecture == "m4" and not (
                args.site_zones and args.manager_zone and args.search_head_zone
            ):
                die(
                    "Production M4 requires --site-zones, --manager-zone, and "
                    "--search-head-zone."
                )
            if not args.confirm_smartstore_index_inventory:
                die(
                    "Production SOK requires --confirm-smartstore-index-inventory "
                    "after reviewing every SmartStore-enabled index and migration."
                )
            if not args.confirm_smartstore_path_ownership:
                die(
                    "Production SOK requires --confirm-smartstore-path-ownership "
                    "after proving the bucket/prefix is unique to this active SVA."
                )
            if not supplied_artifacts:
                die(
                    "Production SOK requires reviewed local chart archives and a "
                    "CRD manifest so validation and apply consume identical hashed bytes."
                )
            if not all(cluster_identity):
                die(
                    "Production SOK requires --expected-kube-context, "
                    "--expected-api-server, and --expected-cluster-uid."
                )
            digest_pattern = re.compile(r"@sha256:[0-9a-fA-F]{64}$")
            if not digest_pattern.search(operator_image(args)):
                die("Production SOK requires a digest-pinned --operator-image.")
            if not digest_pattern.search(splunk_image(args)):
                die("Production SOK requires a digest-pinned --splunk-image.")
        target_version_match = re.match(
            r"^(\d+)\.(\d+)\.(\d+)", effective_splunk_version(args)
        )
        target_version = (
            tuple(int(item) for item in target_version_match.groups())
            if target_version_match
            else (0, 0, 0)
        )
        if args.confirm_splunk_10_4_upgrade_readiness and not args.allow_upgrade:
            die(
                "--confirm-splunk-10-4-upgrade-readiness is valid only with "
                "--allow-upgrade."
            )
        if (
            args.allow_upgrade
            and target_version >= (10, 4, 0)
            and not args.confirm_splunk_10_4_upgrade_readiness
        ):
            die(
                "Upgrading to Splunk Enterprise 10.4+ requires "
                "--confirm-splunk-10-4-upgrade-readiness after verifying a "
                "restorable platform/KV Store backup, KV Store server 7.0+, "
                "premium-app/add-on compatibility, TLS 1.2+, and the target "
                "release upgrade notes."
            )
        if args.allow_upgrade and args.architecture == "m4" and not (
            args.site_zones and args.manager_zone and args.search_head_zone
        ):
            die(
                "M4 upgrade review requires --site-zones, --manager-zone, and "
                "--search-head-zone to lock site placement."
            )
        if args.license_file and args.existing_license_manager:
            die("Use either --license-file or --existing-license-manager, not both.")
        if (
            args.existing_license_manager_namespace
            and not args.existing_license_manager
        ):
            die(
                "--existing-license-manager-namespace requires --existing-license-manager."
            )
        if args.existing_license_manager:
            validate_k8s_subdomain(
                args.existing_license_manager, "--existing-license-manager"
            )
        if args.existing_license_manager_namespace:
            validate_k8s_name(
                args.existing_license_manager_namespace,
                "--existing-license-manager-namespace",
            )
            if args.existing_license_manager_namespace != args.namespace:
                die(
                    "The strict single-namespace bundle cannot own a cross-namespace "
                    "LicenseManager reconciliation contract. Use the documented "
                    "one-Operator/multi-namespace external-LicenseManager handoff."
                )
        if args.splunk_service_account:
            validate_k8s_subdomain(
                args.splunk_service_account, "--splunk-service-account"
            )
            if not args.smartstore_bucket or args.smartstore_provider != "aws":
                die(
                    "--splunk-service-account is a narrowly verified AWS IRSA "
                    "path and requires AWS --smartstore-bucket configuration."
                )
            if not args.splunk_irsa_role_arn:
                die(
                    "--splunk-service-account requires --splunk-irsa-role-arn "
                    "so the live identity is part of the reviewed contract."
                )
            if not args.aws_region:
                die(
                    "--splunk-service-account requires --aws-region to validate "
                    "any region values injected by the EKS identity webhook."
                )
            validate_aws_iam_role_arn(
                args.splunk_irsa_role_arn, "--splunk-irsa-role-arn"
            )
            irsa_expiration = ensure_positive_int(
                args.splunk_irsa_token_expiration,
                "--splunk-irsa-token-expiration",
                maximum=86400,
            )
            if irsa_expiration < 600:
                die("--splunk-irsa-token-expiration must be 600..86400 seconds.")
            expected_partition = (
                "aws-cn"
                if args.aws_region.startswith("cn-")
                else "aws-us-gov"
                if args.aws_region.startswith("us-gov-")
                else "aws"
            )
            if not args.splunk_irsa_role_arn.startswith(
                f"arn:{expected_partition}:iam::"
            ):
                die(
                    "--splunk-irsa-role-arn partition does not match --aws-region."
                )
        elif args.splunk_irsa_role_arn or args.splunk_irsa_token_expiration != "3600":
            die(
                "--splunk-irsa-role-arn and a non-default "
                "--splunk-irsa-token-expiration require --splunk-service-account."
            )
        if args.indexing_ingestion_separation:
            if args.architecture != "c3":
                die(
                    "Indexing and ingestion separation is currently rendered only for C3."
                )
            ensure_positive_int(args.ingestor_replicas, "--ingestor-replicas")
            required = {
                "--queue-name": args.queue_name,
                "--queue-dlq": args.queue_dlq,
                "--queue-region": args.queue_region,
                "--object-storage-path": args.object_storage_path,
                "--queue-secret-ref": args.queue_secret_ref,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                die("Indexing and ingestion separation requires: " + ", ".join(missing))
            validate_sqs_name(args.queue_name, "--queue-name")
            validate_sqs_name(args.queue_dlq, "--queue-dlq")
            if args.queue_name == args.queue_dlq:
                die("--queue-name and --queue-dlq must identify different SQS queues.")
            validate_sok_queue_region(args.queue_region, "--queue-region")
            validate_object_path(args.object_storage_path, "--object-storage-path")
            validate_s3_bucket(
                args.object_storage_path.split("/", 1)[0],
                "--object-storage-path bucket",
                aws=True,
            )
            aws_service_endpoint(
                "sqs", args.queue_region, args.queue_endpoint, "--queue-endpoint"
            )
            aws_service_endpoint(
                "s3",
                args.queue_region,
                args.object_storage_endpoint,
                "--object-storage-endpoint",
            )
            if args.queue_secret_ref:
                validate_k8s_subdomain(args.queue_secret_ref, "--queue-secret-ref")
            if args.ingestor_service_account or args.splunk_service_account:
                die(
                    "Verified SOK 3.1 indexing/ingestion separation requires Queue "
                    "Secret auth with empty workload serviceAccount; the upstream "
                    "3.1 EKS workload-identity path is not verified."
                )
        compatibility = check_sok_compatibility(
            args.operator_version,
            effective_splunk_version(args),
            args.kubernetes_version,
            args.indexing_ingestion_separation,
        )
        if not compatibility.supported and not args.allow_unverified_versions:
            die(
                compatibility.message
                + " Use --allow-unverified-versions only after review."
            )
    if args.target == "pod":
        if args.confirm_splunk_10_4_upgrade_readiness:
            die(
                "--confirm-splunk-10-4-upgrade-readiness is valid only for "
                "the SOK target."
            )
        validate_linux_username(args.ssh_user, "--ssh-user")
        if not args.pod_profile:
            die(
                "--pod-profile is required for Splunk POD; POD profiles are not SVA aliases."
            )
        if args.confirm_new_pod_install and args.allow_upgrade:
            die("--confirm-new-pod-install and --allow-upgrade are mutually exclusive.")
        if args.installer_sha256 and not re.fullmatch(
            r"[0-9a-fA-F]{64}", args.installer_sha256
        ):
            die("--installer-sha256 must be exactly 64 hexadecimal characters.")
        if args.confirm_new_pod_install and not args.installer_sha256:
            die(
                "--confirm-new-pod-install requires an independently reviewed "
                "--installer-sha256."
            )
        installer_path = Path(args.installer_path).expanduser()
        if args.installer_path != "/path/to/kubernetes-installer-standalone" and (
            installer_path.is_symlink()
            or not installer_path.is_file()
            or not os.access(installer_path, os.X_OK)
        ):
            die("--installer-path must be a non-symlink executable regular file.")
        concrete_installer = (
            args.installer_path != "/path/to/kubernetes-installer-standalone"
            and installer_path.is_file()
        )
        if concrete_installer and not args.installer_sha256:
            die(
                "A concrete --installer-path requires an independently reviewed "
                "--installer-sha256 for every later live helper."
            )
        if (
            args.installer_sha256
            and installer_path.is_file()
            and file_sha256(installer_path).lower() != args.installer_sha256.lower()
        ):
            die("--installer-path does not match --installer-sha256.")
        profile = pod_profile(args)
        if profile not in POD_PROFILES:
            die(f"Unsupported POD profile: {profile}")
        _, expected_workers = pod_counts(profile)
        controllers = validate_addresses(args.controller_ips, 3, "--controller-ips")
        workers = validate_addresses(args.worker_ips, expected_workers, "--worker-ips")
        if controllers and workers and set(controllers).intersection(workers):
            die("Controller and worker IP addresses must be unique.")
        for option, value in (
            ("--premium-apps", args.premium_apps),
            ("--itsi-apps", args.itsi_apps),
            ("--indexer-apps", args.indexer_apps),
            ("--cluster-manager-apps", args.cluster_manager_apps),
            ("--search-apps", args.search_apps),
            ("--search-deployer-apps", args.search_deployer_apps),
            ("--standalone-apps", args.standalone_apps),
            ("--license-manager-apps", args.license_manager_apps),
        ):
            validate_nonempty_path_list(value, option)
            for app_path in split_csv(value):
                if not app_path.lower().endswith((".spl", ".tgz", ".tar.gz")):
                    die(
                        f"{option} accepts only documented POD .spl, .tgz, or "
                        f".tar.gz app archives: {app_path}"
                    )
        licenses = split_csv(args.license_file)
        if len(licenses) != len(set(licenses)):
            die("--license-file must not list the same license path more than once.")
        license_identities = set()
        if concrete_installer:
            for license_path in licenses:
                if not license_path.lower().endswith(".lic"):
                    die(f"POD license files must use the .lic suffix: {license_path}")
                validate_existing_file(license_path, "--license-file")
                license_stat = Path(license_path).expanduser().stat()
                license_identities.add((license_stat.st_dev, license_stat.st_ino))
        if (
            concrete_installer
            and (pod_is_es(profile) or pod_is_itsi(profile))
            and len(license_identities) < 2
        ):
            die(
                "Live POD ES/ITSI profiles require two physically distinct Enterprise and "
                "premium-product license files."
            )
        if args.itsi_source_bundle and not args.itsi_source_bundle.lower().endswith(
            (".spl", ".tgz", ".tar.gz")
        ):
            die(
                "--itsi-source-bundle must be a documented .spl, .tgz, or .tar.gz "
                "app archive."
            )
        base_profile = pod_base_profile(profile)
        if args.premium_apps and not pod_is_es(profile):
            die("--premium-apps is valid only with a POD -es profile.")
        if args.itsi_apps and not pod_is_itsi(profile):
            die("--itsi-apps is valid only with a POD -itsi profile.")
        if args.itsi_source_bundle and not pod_is_itsi(profile):
            die("--itsi-source-bundle is valid only with a POD -itsi profile.")
        if args.itsi_source_sha256 and not pod_is_itsi(profile):
            die("--itsi-source-sha256 is valid only with a POD -itsi profile.")
        if args.itsi_jdk_sha256 and not pod_is_itsi(profile):
            die("--itsi-jdk-sha256 is valid only with a POD -itsi profile.")
        if args.itsi_source_sha256 and not re.fullmatch(
            r"[0-9a-fA-F]{64}", args.itsi_source_sha256
        ):
            die("--itsi-source-sha256 must be a 64-character SHA-256 digest.")
        if args.itsi_jdk_sha256 and not re.fullmatch(
            r"[0-9a-fA-F]{64}", args.itsi_jdk_sha256
        ):
            die("--itsi-jdk-sha256 must be a 64-character SHA-256 digest.")
        if bool(args.itsi_source_bundle) != bool(args.itsi_source_sha256):
            die(
                "--itsi-source-bundle and --itsi-source-sha256 must be supplied together."
            )
        if args.itsi_apps and pod_is_itsi(profile) and not args.itsi_jdk_sha256:
            die("--itsi-apps requires a reviewed --itsi-jdk-sha256 for POD ITSI.")
        if base_profile == "pod-small" and (
            args.search_apps or args.search_deployer_apps
        ):
            die(
                "--search-apps and --search-deployer-apps are not used by POD Small; "
                "use --standalone-apps."
            )
        if base_profile != "pod-small" and args.standalone_apps:
            die(
                "--standalone-apps is valid only for POD Small; use --search-apps "
                "or --search-deployer-apps."
            )
        if args.secondary_search_name and not pod_has_secondary_search(profile):
            die(
                "--secondary-search-name is valid only with a POD -es or -itsi profile."
            )
        if bool(args.ingress_certificate_file) != bool(args.ingress_private_key_file):
            die(
                "--ingress-certificate-file and --ingress-private-key-file "
                "must be provided together."
            )
        validate_existing_file(
            args.ingress_certificate_file, "--ingress-certificate-file"
        )
        validate_existing_file(
            args.ingress_private_key_file, "--ingress-private-key-file"
        )
        validate_existing_file(args.ingress_ca_file, "--ingress-ca-file")
        validate_existing_file(args.itsi_source_bundle, "--itsi-source-bundle")
        for private_option, private_value in (
            ("--ssh-private-key-file", args.ssh_private_key_file),
            ("--ingress-private-key-file", args.ingress_private_key_file),
        ):
            if private_value and not private_value.startswith("/path/to/"):
                validate_existing_file(private_value, private_option)
                private_stat = Path(private_value).expanduser().stat()
                if private_stat.st_uid != os.geteuid() or private_stat.st_mode & 0o077:
                    die(
                        f"{private_option} must be owned by the rendering user and "
                        "deny all group/other permissions."
                    )
        if args.ingress_ca_file and not args.ingress_certificate_file:
            die("--ingress-ca-file requires an ingress certificate and private key.")
        if args.ingress_certificate_file and not args.ingress_ca_file:
            die(
                "POD name-based routing requires --ingress-ca-file so the "
                "certificate chain and server purpose can be verified."
            )
        if args.ingress_certificate_file and not args.ingress_domain:
            die(
                "POD name-based routing requires --ingress-domain to bind the "
                "wildcard certificate to the reviewed DNS suffix."
            )
        if args.ingress_domain:
            validate_k8s_subdomain(args.ingress_domain, "--ingress-domain")
        if args.primary_search_name:
            validate_k8s_name(args.primary_search_name, "--primary-search-name")
        if args.secondary_search_name:
            validate_k8s_name(args.secondary_search_name, "--secondary-search-name")
        bundled_splunk, installer_version = pod_bundle_tuple(args.pod_version)
        if bundled_splunk < (10, 2, 1) or installer_version < (1, 5, 0):
            die(
                "This POD workflow requires bundle 10.2.1_1.5.0 or later "
                "because preflightcheck.only is mandatory."
            )
        if ("xlarge" in profile or profile.endswith("-itsi")) and (
            bundled_splunk < (10, 4, 0) or installer_version < (1, 6, 0)
        ):
            die("POD X-Large and ITSI require POD bundle 10.4.0_1.6.0 or later.")
        if (
            profile.endswith("-es")
            and pod_base_profile(profile) != "pod-small"
            and (bundled_splunk < (10, 2, 1) or installer_version < (1, 5, 0))
        ):
            die("ES on POD Medium/Large/X-Large requires installer 1.5.0 or later.")
        if (args.ingress_certificate_file or args.ingress_domain) and (
            bundled_splunk < (10, 4, 0) or installer_version < (1, 6, 0)
        ):
            die("POD name-based routing requires bundle 10.4.0_1.6.0 or later.")
        if args.license_manager_apps and (
            bundled_splunk < (10, 4, 0) or installer_version < (1, 6, 0)
        ):
            die("POD License Manager apps require bundle 10.4.0_1.6.0 or later.")
        if (
            args.pod_version not in VERIFIED_POD_BUNDLES
            and not args.allow_unverified_versions
        ):
            die(
                f"Unverified POD bundle {args.pod_version}; current verified bundle is "
                f"{DEFAULT_POD_VERSION}. Use --allow-unverified-versions only after "
                "release-note and compatibility review."
            )


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o700 if executable else 0o600)


def stat_identity(item: os.stat_result) -> tuple[int, int, int, int, int]:
    return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns


def file_sha256(path: Path) -> str:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        die(f"Unable to hash regular file without following links: {path}: {exc}")
    digest = hashlib.sha256()
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            die(f"Hash input must be a singly linked regular file: {path}")
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(fd)
        if stat_identity(before) != stat_identity(after):
            die(f"Hash input changed while it was being read: {path}")
        return digest.hexdigest()
    finally:
        os.close(fd)


def stage_reviewed_executable(
    source: Path, destination: Path, expected_sha256: str
) -> str:
    """Copy one reviewed executable through a no-follow fd and verify its bytes.

    Generated POD helpers execute only this private snapshot.  They never reopen
    the user-supplied pathname, which prevents a pathname swap between review,
    status, and deployment invocations.
    """
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        source_fd = os.open(source, flags)
    except OSError as exc:
        die(f"Unable to open reviewed executable without following links: {exc}")
    try:
        before = os.fstat(source_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            die("Reviewed executable must be a singly linked regular file.")
        if not before.st_mode & 0o111:
            die("Reviewed executable is not executable.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination_fd = os.open(
            destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o500
        )
        digest = hashlib.sha256()
        try:
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(destination_fd, view)
                    if written <= 0:
                        raise OSError("short write while staging reviewed executable")
                    view = view[written:]
            os.fsync(destination_fd)
        finally:
            os.close(destination_fd)
        after = os.fstat(source_fd)
        if stat_identity(before) != stat_identity(after):
            destination.unlink(missing_ok=True)
            die("Reviewed executable changed while it was being staged.")
        actual = digest.hexdigest()
        if actual.lower() != expected_sha256.lower():
            destination.unlink(missing_ok=True)
            die("Reviewed executable does not match --installer-sha256.")
        destination.chmod(0o500)
        return actual
    finally:
        os.close(source_fd)


def stage_reviewed_file(
    source: Path,
    destination: Path,
    expected_sha256: str = "",
    *,
    mode: int = 0o400,
    max_bytes: int = 0,
) -> str:
    """Snapshot one reviewed regular file through a no-follow descriptor."""
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        source_fd = os.open(source, flags)
    except OSError as exc:
        die(f"Unable to open reviewed file without following links: {exc}")
    try:
        before = os.fstat(source_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            die("Reviewed file must be a singly linked regular file.")
        if max_bytes and before.st_size > max_bytes:
            die(f"Reviewed file exceeds the {max_bytes}-byte snapshot limit.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination_fd = os.open(
            destination,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            mode,
        )
        digest = hashlib.sha256()
        try:
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(destination_fd, view)
                    if written <= 0:
                        raise OSError("short write while staging reviewed file")
                    view = view[written:]
            os.fsync(destination_fd)
        finally:
            os.close(destination_fd)
        after = os.fstat(source_fd)
        if stat_identity(before) != stat_identity(after):
            destination.unlink(missing_ok=True)
            die("Reviewed file changed while it was being staged.")
        actual = digest.hexdigest()
        if expected_sha256 and actual.lower() != expected_sha256.lower():
            destination.unlink(missing_ok=True)
            die("Reviewed file digest changed while it was being staged.")
        destination.chmod(mode)
        return actual
    finally:
        os.close(source_fd)


def write_bundle_manifest(
    render_dir: Path, assets: list[str], external_files: Iterable[str] = ()
) -> None:
    hashes = {}
    modes = {}
    for rel_path in sorted(set(assets)):
        path = render_dir / rel_path
        if path.is_file():
            hashes[rel_path] = file_sha256(path)
            modes[rel_path] = stat.S_IMODE(path.stat().st_mode)
    external_hashes = {}
    for raw_path in sorted(set(external_files)):
        if not raw_path or raw_path.startswith("/path/to/"):
            continue
        unresolved_path = Path(raw_path).expanduser()
        if unresolved_path.is_symlink():
            die(f"External bundle input must not be a symbolic link: {raw_path}")
        path = unresolved_path.resolve()
        if path.is_file():
            if stat.S_IMODE(path.stat().st_mode) & 0o022:
                die(
                    f"External bundle input must not be group/world-writable: {path}"
                )
            external_hashes[str(path)] = file_sha256(path)
    write_file(
        render_dir / "bundle-manifest.json",
        json.dumps(
            {
                "algorithm": "sha256",
                "external_files": external_hashes,
                "files": hashes,
                "modes": modes,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    assets.append("bundle-manifest.json")


def make_script(body: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        'SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"\n'
        'cd -- "${SCRIPT_DIR}"\n\n'
        + body.lstrip()
    )


def storage_block(args: argparse.Namespace, indent: str = "  ") -> str:
    lines = [
        f"{indent}etcVolumeStorageConfig:",
        f"{indent}  ephemeralStorage: false",
        f"{indent}  storageCapacity: {yaml_quote(args.etc_storage)}",
        f"{indent}varVolumeStorageConfig:",
        f"{indent}  ephemeralStorage: false",
        f"{indent}  storageCapacity: {yaml_quote(args.var_storage)}",
    ]
    if args.storage_class:
        lines.insert(3, f"{indent}  storageClassName: {yaml_quote(args.storage_class)}")
        lines.append(f"{indent}  storageClassName: {yaml_quote(args.storage_class)}")
    return "\n".join(lines)


def resources_block(
    args: argparse.Namespace,
    role: str = "general",
    indent: str = "  ",
    field: str = "resources",
) -> str:
    if args.deployment_profile == "production":
        cpu = {
            "search": "32",
            "standalone": "24",
            "indexer": "24",
            "ingestor": "24",
            "cluster_manager": "24",
            "license_manager": "12",
            "monitoring_console": "12",
        }.get(role, "24")
        request_cpu = limit_cpu = cpu
        request_memory = limit_memory = "16Gi"
    else:
        request_cpu, limit_cpu = "4", "8"
        request_memory, limit_memory = "8Gi", "16Gi"
    return "\n".join(
        [
            f"{indent}{field}:",
            f"{indent}  requests:",
            f"{indent}    cpu: {yaml_quote(request_cpu)}",
            f"{indent}    memory: {yaml_quote(request_memory)}",
            f"{indent}  limits:",
            f"{indent}    cpu: {yaml_quote(limit_cpu)}",
            f"{indent}    memory: {yaml_quote(limit_memory)}",
        ]
    )


def zone_affinity_block(field: str, zone: str, indent: str = "  ") -> str:
    if not zone:
        return ""
    lines = [f"{indent}{field}:"]
    nested = indent + "  "
    if field == "affinity":
        lines.append(f"{nested}nodeAffinity:")
        nested += "  "
    lines.extend(
        [
            f"{nested}requiredDuringSchedulingIgnoredDuringExecution:",
            f"{nested}  nodeSelectorTerms:",
            f"{nested}    - matchExpressions:",
            f"{nested}        - key: topology.kubernetes.io/zone",
            f"{nested}          operator: In",
            f"{nested}          values:",
            f"{nested}            - {yaml_quote(zone)}",
        ]
    )
    return "\n".join(lines)


def license_block(args: argparse.Namespace, indent: str = "  ") -> str:
    if not args.license_file:
        return f'{indent}licenseUrl: ""'
    license_name = Path(args.license_file).name
    return "\n".join(
        [
            f"{indent}volumes:",
            f"{indent}  - name: licenses",
            f"{indent}    configMap:",
            f"{indent}      name: splunk-licenses",
            f"{indent}licenseUrl: {yaml_quote('/mnt/licenses/' + license_name)}",
        ]
    )


def license_manager_block(args: argparse.Namespace) -> str:
    if not args.license_file:
        return ""
    lines = [
        "licenseManager:",
        "  enabled: true",
        '  name: "lm"',
    ]
    lines.extend(
        [
            license_block(args),
            zone_affinity_block(
                "affinity", args.manager_zone if args.architecture == "m4" else ""
            ),
            storage_block(args),
            resources_block(args, "license_manager"),
            "",
        ]
    )
    return "\n".join(lines)


def smartstore_block(args: argparse.Namespace, indent: str = "  ") -> str:
    if not args.smartstore_bucket:
        return f"{indent}smartstore: {{}}"
    endpoint = (
        args.smartstore_endpoint
        if args.smartstore_provider == "minio"
        else aws_service_endpoint(
            "s3",
            args.smartstore_region,
            args.smartstore_endpoint,
            "--smartstore-endpoint",
        )
    )
    path = args.smartstore_bucket
    if args.smartstore_prefix:
        path = f"{path.rstrip('/')}/{args.smartstore_prefix.strip('/')}"
    lines = [
        f"{indent}smartstore:",
        f"{indent}  defaults:",
        f"{indent}    volumeName: remote_store",
        f"{indent}  indexes:",
    ]
    for index in validate_splunk_indexes(
        args.smartstore_indexes, "--smartstore-indexes"
    ):
        lines.extend(
            [
                f"{indent}    - name: {yaml_quote(index)}",
                f"{indent}      remotePath: $_index_name",
                f"{indent}      volumeName: remote_store",
            ]
        )
    lines.extend(
        [
            f"{indent}  volumes:",
            f"{indent}    - name: remote_store",
            f"{indent}      storageType: s3",
            f"{indent}      provider: {args.smartstore_provider}",
            f"{indent}      path: {yaml_quote(path)}",
            f"{indent}      endpoint: {yaml_quote(endpoint)}",
            f"{indent}      region: {yaml_quote(args.smartstore_region)}",
        ]
    )
    if args.smartstore_secret_ref:
        lines.append(
            f"{indent}      secretRef: {yaml_quote(args.smartstore_secret_ref)}"
        )
    return "\n".join(lines)


def render_sva(args: argparse.Namespace) -> str:
    indexers = ensure_positive_int(args.indexer_replicas, "--indexer-replicas")
    search_heads = ensure_positive_int(
        args.search_head_replicas, "--search-head-replicas"
    )
    standalones = ensure_positive_int(args.standalone_replicas, "--standalone-replicas")
    sites = ensure_positive_int(args.site_count, "--site-count")

    if args.architecture == "s1":
        return "\n".join(
            [
                "sva:",
                "  s1:",
                "    enabled: true",
                f"    standalones: {standalones}",
                "  c3:",
                "    enabled: false",
                "  m4:",
                "    enabled: false",
            ]
        )

    if args.architecture == "c3":
        return "\n".join(
            [
                "sva:",
                "  s1:",
                "    enabled: false",
                "  c3:",
                "    enabled: true",
                "    indexerClusters:",
                "      - name: idxc",
                "    searchHeadClusters:",
                "      - name: shc",
                "  m4:",
                "    enabled: false",
                f"# Effective C3 defaults: {indexers} indexers and {search_heads} search heads.",
            ]
        )

    site_names = [f"site{i}" for i in range(1, sites + 1)]
    site_zones = split_csv(args.site_zones)
    indexer_lines = []
    for index, site in enumerate(site_names):
        indexer_lines.extend(
            [
                f"      - name: idxc-{site}",
                f"        site: {site}",
            ]
        )
        if site_zones:
            indexer_lines.append(f"        zone: {yaml_quote(site_zones[index])}")
    return "\n".join(
        [
            "sva:",
            "  s1:",
            "    enabled: false",
            "  c3:",
            "    enabled: false",
            "  m4:",
            "    enabled: true",
            "    clusterManager:",
            f"      site: {args.manager_site}",
            f"      allSites: {yaml_quote(','.join(site_names))}",
            *(
                [f"      zone: {yaml_quote(args.manager_zone)}"]
                if args.manager_zone
                else []
            ),
            "    indexerClusters:",
            *indexer_lines,
            "    searchHeadClusters:",
            "      - name: shc",
            f"        site: {args.search_head_site}",
            *(
                [f"        zone: {yaml_quote(args.search_head_zone)}"]
                if args.search_head_zone
                else []
            ),
            f"# Effective M4 defaults: {indexers} indexers per site, {indexers * sites} total indexers, and {search_heads} search heads.",
            f"# M4 zone pinning: {'enabled' if site_zones else 'not rendered; provide --site-zones to add node affinity.'}",
        ]
    )


def render_enterprise_values(args: argparse.Namespace) -> str:
    architecture = args.architecture
    license_text = license_block(args)
    license_manager_text = license_manager_block(args)
    smartstore_text = smartstore_block(args)
    storage_text = storage_block(args)
    image = splunk_image(args)
    indexer_replicas = ensure_positive_int(args.indexer_replicas, "--indexer-replicas")
    search_replicas = ensure_positive_int(
        args.search_head_replicas, "--search-head-replicas"
    )
    standalone_replicas = ensure_positive_int(
        args.standalone_replicas, "--standalone-replicas"
    )

    lines = [
        "# Rendered by splunk-enterprise-kubernetes-setup. Review before applying.",
        "splunk-operator:",
        "  enabled: false",
        "image:",
        f"  repository: {yaml_quote(image)}",
        '  imagePullPolicy: "IfNotPresent"',
        render_sva(args),
        "",
    ]

    if args.existing_license_manager:
        lines.extend(
            [
                "existingLicenseManager:",
                f"  name: {yaml_quote(args.existing_license_manager)}",
            ]
        )
        if (
            args.existing_license_manager_namespace
            and args.existing_license_manager_namespace != args.namespace
        ):
            lines.append(
                "  namespace: " + yaml_quote(args.existing_license_manager_namespace)
            )
        lines.append("")

    if architecture == "s1":
        lines.extend(
            [
                "standalone:",
                "  enabled: true",
                '  name: "s1"',
                *(
                    [f"  serviceAccount: {yaml_quote(args.splunk_service_account)}"]
                    if args.splunk_service_account
                    else []
                ),
                f"  replicaCount: {standalone_replicas}",
                license_text,
                smartstore_text,
                storage_text,
                resources_block(args, "standalone"),
                "",
            ]
        )
    else:
        if license_manager_text:
            lines.append(license_manager_text)
        lines.extend(
            [
                "clusterManager:",
                "  enabled: true",
                '  name: "cm"',
                smartstore_text,
                storage_text,
                resources_block(args, "cluster_manager"),
                "",
                "indexerCluster:",
                "  enabled: true",
                '  name: "idxc"',
                f"  replicaCount: {indexer_replicas}",
                *(
                    [f"  serviceAccount: {yaml_quote(args.splunk_service_account)}"]
                    if args.splunk_service_account
                    and not args.indexing_ingestion_separation
                    else []
                ),
                storage_text,
                resources_block(args, "indexer"),
                "",
                "searchHeadCluster:",
                "  enabled: true",
                '  name: "shc"',
                f"  replicaCount: {search_replicas}",
                storage_text,
                zone_affinity_block(
                    "deployerNodeAffinity",
                    args.search_head_zone if architecture == "m4" else "",
                ),
                resources_block(
                    args, "search", field="deployerResourceSpec"
                ),
                resources_block(args, "search"),
                "",
            ]
        )
        if not args.disable_monitoring_console:
            lines.extend(
                [
                    "monitoringConsole:",
                    "  enabled: true",
                    '  name: "mc"',
                    zone_affinity_block(
                        "affinity",
                        args.manager_zone if architecture == "m4" else "",
                    ),
                    storage_text,
                    resources_block(args, "monitoring_console"),
                    "",
                ]
            )

    if args.indexing_ingestion_separation:
        queue_endpoint = aws_service_endpoint(
            "sqs", args.queue_region, args.queue_endpoint, "--queue-endpoint"
        )
        object_endpoint = aws_service_endpoint(
            "s3",
            args.queue_region,
            args.object_storage_endpoint,
            "--object-storage-endpoint",
        )
        if args.queue_secret_ref:
            # splunk-enterprise chart 3.1.0 serializes queue.sqs.volumes
            # incorrectly (it emits the complete SQS mapping beneath volumes).
            # Render the documented Queue CR through extraManifests until the
            # chart fixes that path; semantic Helm validation guards this CR.
            lines.extend(
                [
                    "extraManifests:",
                    "  - apiVersion: enterprise.splunk.com/v4",
                    "    kind: Queue",
                    "    metadata:",
                    "      name: ingest-queue",
                    f"      namespace: {yaml_quote(args.namespace)}",
                    "    spec:",
                    f"      provider: {yaml_quote(args.queue_provider)}",
                    "      sqs:",
                    f"        name: {yaml_quote(args.queue_name)}",
                    f"        authRegion: {yaml_quote(args.queue_region)}",
                    f"        endpoint: {yaml_quote(queue_endpoint)}",
                    f"        dlq: {yaml_quote(args.queue_dlq)}",
                    "        volumes:",
                    "          - name: queue-credentials",
                    f"            secretRef: {yaml_quote(args.queue_secret_ref)}",
                ]
            )
        else:
            lines.extend(
                [
                    "queue:",
                    "  enabled: true",
                    '  name: "ingest-queue"',
                    f"  provider: {yaml_quote(args.queue_provider)}",
                    "  sqs:",
                    f"    name: {yaml_quote(args.queue_name)}",
                    f"    authRegion: {yaml_quote(args.queue_region)}",
                    f"    endpoint: {yaml_quote(queue_endpoint)}",
                    f"    dlq: {yaml_quote(args.queue_dlq)}",
                ]
            )
        lines.extend(
            [
                "",
                "objectStorage:",
                "  enabled: true",
                '  name: "ingest-object-storage"',
                '  provider: "s3"',
                "  s3:",
                f"    path: {yaml_quote(args.object_storage_path)}",
                f"    endpoint: {yaml_quote(object_endpoint)}",
                "",
                "ingestorCluster:",
                "  enabled: true",
                '  name: "ingestor"',
                f"  replicaCount: {ensure_positive_int(args.ingestor_replicas, '--ingestor-replicas')}",
                "  queueRef:",
                '    name: "ingest-queue"',
                "  objectStorageRef:",
                '    name: "ingest-object-storage"',
                storage_text,
                resources_block(args, "ingestor"),
                "",
            ]
        )
        # The same identity and durable endpoints must be used by the index-only tier.
        indexer_pos = lines.index("indexerCluster:")
        insert_at = indexer_pos + 4
        lines[insert_at:insert_at] = [
            "  queueRef:",
            '    name: "ingest-queue"',
            "  objectStorageRef:",
            '    name: "ingest-object-storage"',
        ]
    return "\n".join(lines).rstrip() + "\n"


def render_operator_values(args: argparse.Namespace) -> str:
    image = operator_image(args)
    related_image = splunk_image(args)
    cluster_wide = args.operator_scope == "cluster"
    watch_namespaces = ",".join(split_csv(args.watch_namespaces) or [args.namespace])
    return "\n".join(
        [
            "# Rendered by splunk-enterprise-kubernetes-setup. Review before applying.",
            "image:",
            f"  repository: {yaml_quote(related_image)}",
            "splunkOperator:",
            "  image:",
            f"    repository: {yaml_quote(image)}",
            "    pullPolicy: IfNotPresent",
            f"  clusterWideAccess: {bool_word(cluster_wide)}",
            f"  watchNamespaces: {yaml_quote(watch_namespaces if cluster_wide else '')}",
            "  persistentVolumeClaim:",
            f"    storageClassName: {yaml_quote(args.storage_class)}",
            f"  splunkGeneralTerms: {yaml_quote(SGT_ACCEPTANCE if args.accept_splunk_general_terms else '')}",
            "",
        ]
    )


def render_namespace(args: argparse.Namespace) -> str:
    namespaces = []
    for name in (args.operator_namespace, args.namespace):
        if name not in namespaces:
            namespaces.append(name)
    docs = []
    for name in namespaces:
        docs.extend(
            [
                "apiVersion: v1",
                "kind: Namespace",
                "metadata:",
                f"  name: {name}",
            ]
        )
        docs.append("---")
    return "\n".join(docs).rstrip("-\n") + "\n"


def render_sok_preflight(args: argparse.Namespace) -> str:
    watched_namespaces = split_csv(args.watch_namespaces) or [args.namespace]
    compatibility_args = [
        "python3 compatibility-check.py",
        f"--operator-version {shell_quote(args.operator_version)}",
        f"--splunk-version {shell_quote(effective_splunk_version(args))}",
        '--kubernetes-version "${server_version}"',
    ]
    if args.indexing_ingestion_separation:
        compatibility_args.append("--indexing-ingestion-separation")
    compatibility_command = " ".join(compatibility_args)
    if args.allow_unverified_versions:
        compatibility_line = (
            f"if ! {compatibility_command}; then :; fi; "
            "printf 'WARNING: proceeding with an explicitly unverified "
            "non-production SOK version tuple.\\n' >&2"
        )
    else:
        compatibility_line = compatibility_command
    if args.operator_chart_archive:
        artifact_checks = [
            f"helm show chart ./splunk-operator-chart.tgz | grep -Eq {shell_quote('^version:[[:space:]]*' + re.escape(chart_version(args)) + '[[:space:]]*$')}",
            f"helm show chart ./splunk-enterprise-chart.tgz | grep -Eq {shell_quote('^version:[[:space:]]*' + re.escape(chart_version(args)) + '[[:space:]]*$')}",
            "kubectl apply --dry-run=client --server-side=false -f ./splunk-operator-crds.yaml >/dev/null",
        ]
    else:
        artifact_checks = [
            "helm repo add splunk https://splunk.github.io/splunk-operator/ --force-update >/dev/null",
            "helm repo update splunk --timeout 2m >/dev/null",
            f"helm show chart splunk/splunk-operator --version {shell_quote(chart_version(args))} >/dev/null",
            f"helm show chart splunk/splunk-enterprise --version {shell_quote(chart_version(args))} >/dev/null",
            f"python3 -c {shell_quote('import urllib.request; urllib.request.urlopen(' + repr(f'https://github.com/splunk/splunk-operator/releases/download/{args.operator_version}/splunk-operator-crds.yaml') + ', timeout=30).read(1)')}",
        ]
    lines = ["python3 bundle-verify.py verify . sok"]
    if args.eks_cluster_name:
        lines.append("./eks-update-kubeconfig.sh")
    lines.extend(
        [
            "command -v kubectl >/dev/null",
            "command -v helm >/dev/null",
            "command -v python3 >/dev/null",
            "python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else \"ERROR: Python 3.9+ is required.\")'",
            "python3 -c 'import yaml; raise SystemExit(0 if str(yaml.__version__).split(\".\", 1)[0] == \"6\" else f\"ERROR: PyYAML 6.x is required; found {yaml.__version__!r}.\")'",
            (
                '[[ -f "${PWD}/kubeconfig" ]] || { printf \'ERROR: EKS kubeconfig was not created.\\n\' >&2; exit 1; }; export KUBECONFIG="${PWD}/kubeconfig"'
                if args.eks_cluster_name
                else ": # use the caller's active Kubernetes context"
            ),
            "./verify-cluster.sh",
            "kubectl version --client=true",
            "kubectl cluster-info",
            'server_version="$(kubectl version -o json | python3 -c \'import json,sys; print(json.load(sys.stdin)["serverVersion"]["gitVersion"])\')"',
            compatibility_line,
            "helm version",
            *artifact_checks,
            "kubectl get nodes -o wide",
        ]
    )
    apply_verbs = ["get", "create", "patch", "update"]
    managed_verbs = [*apply_verbs, "delete", "list", "watch"]
    access_requirements = [
        {
            "group": "apiextensions.k8s.io",
            "resource": "customresourcedefinitions",
            "verbs": apply_verbs,
        },
        {"group": "", "resource": "namespaces", "verbs": apply_verbs},
        {
            "group": "apps",
            "resource": "deployments",
            "verbs": ["get", "list"],
        },
    ]
    operator_resources = (
        ("apps", "deployments"),
        ("", "persistentvolumeclaims"),
        ("", "services"),
        ("", "serviceaccounts"),
        ("rbac.authorization.k8s.io", "roles"),
        ("rbac.authorization.k8s.io", "rolebindings"),
        ("", "secrets"),
    )
    for group, resource in operator_resources:
        resource_verbs = [*managed_verbs]
        access_requirements.append(
            {
                "group": group,
                "resource": resource,
                "namespace": args.operator_namespace,
                "verbs": resource_verbs,
            }
        )
    enterprise_resources = []
    if args.architecture == "s1":
        enterprise_resources.append("standalones")
    else:
        enterprise_resources.extend(
            ["clustermanagers", "indexerclusters", "searchheadclusters"]
        )
    if args.license_file and args.architecture != "s1":
        enterprise_resources.append("licensemanagers")
    if not args.disable_monitoring_console and args.architecture != "s1":
        enterprise_resources.append("monitoringconsoles")
    if args.indexing_ingestion_separation:
        enterprise_resources.extend(["ingestorclusters", "queues", "objectstorages"])
    for resource in enterprise_resources:
        access_requirements.append(
            {
                "group": "enterprise.splunk.com",
                "resource": resource,
                "namespace": args.namespace,
                "verbs": managed_verbs,
            }
        )
    guard_resources = (
        "standalones", "clustermanagers", "indexerclusters",
        "searchheadclusters", "licensemanagers", "monitoringconsoles",
        "ingestorclusters", "queues", "objectstorages",
    )
    for resource in guard_resources:
        if resource in enterprise_resources:
            continue
        access_requirements.append(
            {
                "group": "enterprise.splunk.com",
                "resource": resource,
                "namespace": args.namespace,
                "verbs": ["get", "list"],
            }
        )
    if args.existing_license_manager:
        access_requirements.append(
            {
                "group": "enterprise.splunk.com",
                "resource": "licensemanagers",
                "namespace": args.existing_license_manager_namespace or args.namespace,
                "verbs": ["get", "watch"],
            }
        )
    for watched_namespace in watched_namespaces:
        if watched_namespace == args.namespace:
            continue
        for resource in (
            "standalones",
            "clustermanagers",
            "indexerclusters",
            "searchheadclusters",
            "licensemanagers",
            "monitoringconsoles",
            "ingestorclusters",
            "queues",
            "objectstorages",
        ):
            access_requirements.append(
                {
                    "group": "enterprise.splunk.com",
                    "resource": resource,
                    "namespace": watched_namespace,
                    "verbs": ["get", "list"],
                }
            )
    for resource in ("configmaps", "secrets"):
        resource_verbs = [*managed_verbs]
        access_requirements.append(
            {
                "group": "",
                "resource": resource,
                "namespace": args.namespace,
                "verbs": resource_verbs,
            }
        )
    for resource in ("clusterroles", "clusterrolebindings"):
        access_requirements.append(
            {
                "group": "rbac.authorization.k8s.io",
                "resource": resource,
                "verbs": (
                    managed_verbs
                    if args.operator_scope == "cluster"
                    else ["get", "list"]
                ),
            }
        )
    for namespace in sorted({args.operator_namespace, args.namespace}):
        for resource, verbs in (
            (
                "pods",
                [
                    "get",
                    "list",
                    "watch",
                    *(
                        ["create"]
                        if args.splunk_service_account
                        and namespace == args.namespace
                        else []
                    ),
                ],
            ),
            ("events", ["get", "list", "watch"]),
        ):
            access_requirements.append(
                {
                    "group": "",
                    "resource": resource,
                    "namespace": namespace,
                    "verbs": verbs,
                }
            )
    access_requirements.append(
        {
            "group": "apps",
            "resource": "statefulsets",
            "namespace": args.namespace,
            "verbs": ["get", "list", "watch"],
        }
    )
    access_requirements.extend(
        [
            {
                "group": "apps",
                "resource": "replicasets",
                "namespace": args.operator_namespace,
                "verbs": ["get", "list"],
            },
            {
                "group": "",
                "resource": "persistentvolumeclaims",
                "namespace": args.namespace,
                "verbs": ["get", "list"],
            },
        ]
    )
    access_requirements.extend(
        [
            {
                "group": "",
                "resource": "services",
                "namespace": args.namespace,
                "verbs": ["get", "list"],
            },
            {
                "group": "discovery.k8s.io",
                "resource": "endpointslices",
                "namespace": args.namespace,
                "verbs": ["get", "list"],
            },
        ]
    )
    for resource, verbs in (
        ("nodes", ["get", "list"]),
        ("storageclasses", ["get", "list"]),
    ):
        access_requirements.append(
            {
                "group": "storage.k8s.io" if resource == "storageclasses" else "",
                "resource": resource,
                "verbs": verbs,
            }
        )
    rbac_guard_code = """import json
import subprocess
import sys

requirements = json.loads(sys.argv[1])
for requirement in requirements:
    for verb in requirement.pop("verbs"):
        attributes = {**requirement, "verb": verb}
        payload = {
            "apiVersion": "authorization.k8s.io/v1",
            "kind": "SelfSubjectAccessReview",
            "spec": {"resourceAttributes": attributes},
        }
        result = subprocess.run(
            [
                "kubectl",
                "create",
                "--raw",
                "/apis/authorization.k8s.io/v1/selfsubjectaccessreviews",
                "-f",
                "-",
            ],
            input=json.dumps(payload),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode:
            raise SystemExit(result.stderr.strip() or "ERROR: RBAC review failed")
        response = json.loads(result.stdout)
        if not response.get("status", {}).get("allowed", False):
            scope = f" in {attributes['namespace']}" if attributes.get("namespace") else ""
            raise SystemExit(
                f"ERROR: RBAC denies {verb} {attributes['resource']}"
                f".{attributes.get('group', '')}{scope}"
            )
"""
    lines.append(
        f"python3 -c {shell_quote(rbac_guard_code)} "
        f"{shell_quote(json.dumps(access_requirements, sort_keys=True))}"
    )
    operator_collision_guard_code = """import json
import os
import subprocess
import sys

operator_namespace, release, scope, watched_json, allow_upgrade = sys.argv[1:]
watched = set(json.loads(watched_json))
validate_existing = os.environ.get("SOK_VALIDATE_EXISTING") == "true"
existing_mode = allow_upgrade == "true" or validate_existing

def kubectl_json(*arguments):
    result = subprocess.run(
        ["kubectl", *arguments, "-o", "json"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise SystemExit(result.stderr.strip() or "ERROR: cluster inventory failed")
    return json.loads(result.stdout)

def deployment_watches(containers, namespace):
    for container in containers:
        for env in container.get("env", []):
            if env.get("name") != "WATCH_NAMESPACE":
                continue
            field_path = env.get("valueFrom", {}).get("fieldRef", {}).get("fieldPath")
            if field_path == "metadata.namespace":
                return {namespace}
            value = env.get("value")
            if value:
                return {entry.strip() for entry in value.split(",") if entry.strip()}
            return None
    return None

owned_deployment = False
deployments = kubectl_json("get", "deployments", "--all-namespaces").get("items", [])
for item in deployments:
    metadata = item.get("metadata", {})
    labels = metadata.get("labels", {})
    containers = item.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    images = [container.get("image", "") for container in containers]
    is_operator = (
        metadata.get("name") == "splunk-operator-controller-manager"
        or labels.get("app.kubernetes.io/name") == "splunk-operator"
        or labels.get("helm.sh/chart", "").startswith("splunk-operator-")
        or any("splunk-operator" in image.rsplit("/", 1)[-1] for image in images)
    )
    if not is_operator:
        continue
    namespace = metadata.get("namespace", "")
    owner = metadata.get("annotations", {}).get("meta.helm.sh/release-name")
    owner_namespace = metadata.get("annotations", {}).get(
        "meta.helm.sh/release-namespace"
    )
    same_identity = (
        namespace == operator_namespace
        and metadata.get("name") == "splunk-operator-controller-manager"
        and owner == release
        and owner_namespace == operator_namespace
    )
    existing_watches = deployment_watches(containers, namespace)
    if existing_mode and same_identity:
        if existing_watches != watched:
            raise SystemExit(
                "ERROR: Operator watch-scope migration requires a manual handoff: "
                f"live={existing_watches}, reviewed={watched}"
            )
        owned_deployment = True
        continue
    overlaps = existing_watches is None or bool(existing_watches & watched)
    if scope == "cluster" or overlaps or same_identity:
        raise SystemExit(
            "ERROR: existing Splunk Operator overlaps the reviewed watch scope: "
            f"{namespace}/{metadata.get('name')} owner={owner!r}"
        )

owned_cluster_rbac = {"clusterroles": 0, "clusterrolebindings": 0}
for resource in owned_cluster_rbac:
    for item in kubectl_json("get", resource).get("items", []):
        metadata = item.get("metadata", {})
        labels = metadata.get("labels", {})
        name = metadata.get("name", "")
        app_name = labels.get("app.kubernetes.io/name", "")
        binds_reviewed_service_account = resource == "clusterrolebindings" and any(
            subject.get("kind") == "ServiceAccount"
            and subject.get("namespace") == operator_namespace
            and subject.get("name") == "splunk-operator-controller-manager"
            for subject in item.get("subjects", [])
        )
        if (
            "splunk-operator" not in name
            and "splunk-operator" not in app_name
            and not binds_reviewed_service_account
        ):
            continue
        annotations = metadata.get("annotations", {})
        exact_owner = (
            annotations.get("meta.helm.sh/release-name") == release
            and annotations.get("meta.helm.sh/release-namespace") == operator_namespace
        )
        if existing_mode and exact_owner:
            owned_cluster_rbac[resource] += 1
        elif scope == "cluster" or exact_owner or binds_reviewed_service_account:
            raise SystemExit(
                f"ERROR: existing {item.get('kind')}/{name} has a conflicting "
                "Splunk Operator Helm owner"
            )

if existing_mode:
    if not owned_deployment:
        raise SystemExit("ERROR: reviewed existing Operator Deployment was not found")
    has_cluster_rbac = all(count > 0 for count in owned_cluster_rbac.values())
    has_partial_cluster_rbac = any(count > 0 for count in owned_cluster_rbac.values())
    if scope == "cluster" and not has_cluster_rbac:
        raise SystemExit(
            "ERROR: namespace-to-cluster Operator scope migration requires a manual handoff"
        )
    if scope == "namespace" and has_partial_cluster_rbac:
        raise SystemExit(
            "ERROR: cluster-to-namespace Operator scope migration requires a manual handoff"
        )
"""
    lines.append(
        f"python3 -c {shell_quote(operator_collision_guard_code)} "
        f"{shell_quote(args.operator_namespace)} "
        f"{shell_quote(args.operator_release_name)} "
        f"{shell_quote(args.operator_scope)} "
        f"{shell_quote(json.dumps(watched_namespaces))} "
        f"{shell_quote(bool_word(args.allow_upgrade))}"
    )
    foreign_cr_guard_code = """import json
import sys
payload = json.load(sys.stdin)
items = payload.get("items", [])
if items:
    identities = [
        f"{item.get('kind')}/{item.get('metadata', {}).get('name')}"
        for item in items
    ]
    raise SystemExit(
        f"ERROR: watched namespace {sys.argv[1]} contains unmanaged Splunk CRs: "
        + ", ".join(identities)
    )
"""
    for watched_namespace in watched_namespaces:
        if watched_namespace == args.namespace:
            continue
        for resource in (
            "standalones",
            "clustermanagers",
            "indexerclusters",
            "searchheadclusters",
            "licensemanagers",
            "monitoringconsoles",
            "ingestorclusters",
            "queues",
            "objectstorages",
        ):
            lines.append(
                f"if kubectl get crd {resource}.enterprise.splunk.com --ignore-not-found -o name | grep -q .; then "
                f"kubectl get {resource} --namespace {shell_quote(watched_namespace)} -o json | "
                f"python3 -c {shell_quote(foreign_cr_guard_code)} {shell_quote(watched_namespace)}; fi"
            )
    if args.allow_upgrade:
        upgrade_guard_code = """import json
import re
import sys

raw = sys.stdin.read().strip()
rows = json.loads(raw or "[]")
name, target, expected_chart, expected_namespace = sys.argv[1:5]
matching = [item for item in rows if item.get("name") == name]
if not matching:
    raise SystemExit(f"ERROR: reviewed upgrade has no Helm release {name!r}")
if len(matching) != 1:
    raise SystemExit(f"ERROR: Helm release identity is ambiguous for {name!r}")
row = matching[0]
if row.get("namespace") != expected_namespace:
    raise SystemExit(
        f"ERROR: live Helm release namespace differs: {row.get('namespace')!r} "
        f"!= {expected_namespace!r}"
    )
if str(row.get("status", "")).lower() != "deployed":
    raise SystemExit(
        f"ERROR: live Helm release {name!r} is not deployed: {row.get('status')!r}"
    )

chart = row.get("chart", "")
chart_prefix = f"{expected_chart}-"
if not chart.startswith(chart_prefix):
    raise SystemExit(
        f"ERROR: live Helm chart identity differs: {chart!r} does not start "
        f"with {chart_prefix!r}"
    )
current_match = re.fullmatch(r"(\\d+(?:\\.\\d+){1,2})(?:[-+].*)?", chart[len(chart_prefix):])
target_match = re.match(r"(\\d+(?:\\.\\d+){1,2})", target)
if current_match is None:
    raise SystemExit(f"ERROR: cannot verify deployed chart version: {chart}")
if target_match is None:
    raise SystemExit(f"ERROR: cannot parse target chart version: {target}")

current = tuple(map(int, current_match.group(1).split(".")))
wanted = tuple(map(int, target_match.group(1).split(".")))
current += (0,) * (3 - len(current))
wanted += (0,) * (3 - len(wanted))
if wanted < current:
    raise SystemExit(
        f"ERROR: chart downgrade is unsupported: {chart} -> {target}"
    )
"""
        lines.extend(
            [
                f"helm list --all --namespace {shell_quote(args.operator_namespace)} -o json | python3 -c {shell_quote(upgrade_guard_code)} {shell_quote(args.operator_release_name)} {shell_quote(chart_version(args))} splunk-operator {shell_quote(args.operator_namespace)}",
                f"helm list --all --namespace {shell_quote(args.namespace)} -o json | python3 -c {shell_quote(upgrade_guard_code)} {shell_quote(args.release_name)} {shell_quote(chart_version(args))} splunk-enterprise {shell_quote(args.namespace)}",
            ]
        )
        live_upgrade_guard_code = """import json
import re
import sys

payload = json.loads(sys.stdin.read() or '{"items": []}')
items = payload.get("items", [])
target_release, target_architecture, target_version, target_image, target_i_and_i, target_sites, expected_json, storage_json, smartstore_json, m4_json, refs_json, runtime_json, external_lm, target_namespace = sys.argv[1:]
expected_names = json.loads(expected_json)
expected_storage = json.loads(storage_json)
expected_smartstore = json.loads(smartstore_json)
expected_m4 = json.loads(m4_json)
expected_refs = json.loads(refs_json)
expected_runtime = json.loads(runtime_json)

def require_healthy(item):
    kind = item.get("kind", "unknown")
    metadata = item.get("metadata", {})
    name = metadata.get("name", "unknown")
    generation = metadata.get("generation")
    annotations = metadata.get("annotations", {})
    if item.get("apiVersion") != "enterprise.splunk.com/v4":
        raise SystemExit(f"ERROR: live {kind}/{name} does not use v4")
    if metadata.get("deletionTimestamp") or any(
        key.lower().endswith(".enterprise.splunk.com/paused") for key in annotations
    ):
        raise SystemExit(f"ERROR: live {kind}/{name} is terminating or paused")
    if annotations.get("enterprise.splunk.com/admin-managed-pv") not in (None, "", "false"):
        raise SystemExit(
            f"ERROR: live {kind}/{name} enables unreviewed admin-managed PVs"
        )
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise SystemExit(f"ERROR: live {kind}/{name} generation is invalid")
    status = item.get("status", {})
    if status.get("phase") != "Ready" or status.get("message") not in (None, ""):
        raise SystemExit(f"ERROR: live {kind}/{name} is not cleanly Ready")
    if status.get("observedGeneration") not in (None, generation):
        raise SystemExit(f"ERROR: live {kind}/{name} status is stale")
    app_repo = item.get("spec", {}).get("appRepo")
    if isinstance(app_repo, dict) and app_repo:
        context = status.get("appContext", {})
        if (
            context.get("version") != 1
            or context.get("isDeploymentInProgress") is not False
            or context.get("appRepo") != app_repo
        ):
            raise SystemExit(f"ERROR: live {kind}/{name} App Framework is not converged")
        for source in context.get("appSrcDeployStatus", {}).values():
            for deployment in source.get("appDeploymentInfo", []):
                if deployment.get("repoState") not in {1, 2} or deployment.get("deployStatus") != 3:
                    raise SystemExit(f"ERROR: live {kind}/{name} has an unreconciled app")

if external_lm:
    matching_external = [
        item for item in items
        if item.get("kind") == "LicenseManager"
        and item.get("metadata", {}).get("name") == external_lm
    ]
    if len(matching_external) != 1:
        raise SystemExit(
            f"ERROR: expected exactly one external LicenseManager/{external_lm}"
        )
    require_healthy(matching_external[0])
    items = [item for item in items if item not in matching_external]
reference_fields = (
    "apiVersion", "fieldPath", "kind", "name", "namespace",
    "resourceVersion", "uid",
)

def canonical_reference(value):
    value = value if isinstance(value, dict) else {}
    return {field: value.get(field) or "" for field in reference_fields}
if not items:
    raise SystemExit("ERROR: reviewed upgrade release has no live Splunk custom resources")
for item in items:
    require_healthy(item)
    owner = item.get("metadata", {}).get("annotations", {}).get("meta.helm.sh/release-name")
    owner_namespace = item.get("metadata", {}).get("annotations", {}).get(
        "meta.helm.sh/release-namespace"
    )
    if owner != target_release or owner_namespace != target_namespace:
        kind = item.get("kind", "unknown")
        name = item.get("metadata", {}).get("name", "unknown")
        raise SystemExit(
            f"ERROR: live {kind}/{name} is not owned by reviewed Helm release {target_release}"
        )
kinds = [item.get("kind") for item in items]
actual_names = {}
for item in items:
    actual_names.setdefault(item.get("kind"), []).append(item.get("metadata", {}).get("name"))
actual_names = {kind: sorted(names) for kind, names in actual_names.items()}
if actual_names != expected_names:
    raise SystemExit(
        f"ERROR: changing Splunk custom-resource topology is destructive; "
        f"live={actual_names}, reviewed={expected_names}"
    )
for item in items:
    kind = item.get("kind")
    if kind not in expected_refs:
        continue
    spec = item.get("spec", {})
    actual = {}
    for field in ("clusterManagerRef", "monitoringConsoleRef", "licenseManagerRef"):
        actual[field] = canonical_reference(spec.get(field))
    if actual != expected_refs[kind]:
        raise SystemExit(
            f"ERROR: live {kind}/{item.get('metadata', {}).get('name')} references "
            f"differ from reviewed topology: live={actual}, reviewed={expected_refs[kind]}"
        )
    runtime = expected_runtime[kind]
    spec = item.get("spec", {})
    if runtime.get("replicas") is not None and spec.get("replicas") != runtime["replicas"]:
        raise SystemExit(
            f"ERROR: automated upgrade cannot scale {kind}/"
            f"{item.get('metadata', {}).get('name')}: "
            f"live={spec.get('replicas')}, reviewed={runtime['replicas']}"
        )
    if (spec.get("serviceAccount") or "") != runtime.get("serviceAccount", ""):
        raise SystemExit(
            f"ERROR: automated upgrade cannot change {kind} workload identity: "
            f"live={spec.get('serviceAccount')!r}, reviewed={runtime.get('serviceAccount')!r}"
        )
standalones = kinds.count("Standalone")
indexers = kinds.count("IndexerCluster")
clustered = all(kind in kinds for kind in ("ClusterManager", "IndexerCluster", "SearchHeadCluster"))
if standalones == 1 and not clustered:
    current_architecture = "s1"
elif clustered and standalones == 0:
    current_architecture = "m4" if indexers > 1 else "c3"
else:
    raise SystemExit("ERROR: live Splunk topology is incomplete or ambiguous")
if current_architecture != target_architecture:
    raise SystemExit(
        f"ERROR: topology migration is not an in-place upgrade: {current_architecture} -> {target_architecture}"
    )
if target_architecture == "m4" and indexers != int(target_sites):
    raise SystemExit("ERROR: changing the M4 site count is not an in-place upgrade")
live_i_and_i = any(kind in kinds for kind in ("Queue", "ObjectStorage", "IngestorCluster"))
if live_i_and_i and target_i_and_i != "true":
    raise SystemExit("ERROR: removing indexing/ingestion separation is destructive and unsupported")

def selected_smartstore(value):
    value = value if isinstance(value, dict) else {}
    return {
        "defaults": {"volumeName": value.get("defaults", {}).get("volumeName")},
        "indexes": sorted(
            [
                {
                    "name": entry.get("name"),
                    "remotePath": entry.get("remotePath"),
                    "volumeName": entry.get("volumeName"),
                }
                for entry in value.get("indexes", [])
            ],
            key=lambda entry: entry.get("name") or "",
        ),
        "volumes": sorted(
            [
                {
                    "name": entry.get("name"),
                    "storageType": entry.get("storageType"),
                    "provider": entry.get("provider"),
                    "path": entry.get("path"),
                    "endpoint": entry.get("endpoint"),
                    "region": entry.get("region") or "",
                    "secretRef": entry.get("secretRef"),
                }
                for entry in value.get("volumes", [])
            ],
            key=lambda entry: entry.get("name") or "",
        ),
    }

smartstore_owner = next(
    (item for item in items if item.get("kind") in {"Standalone", "ClusterManager"}),
    None,
)
live_smartstore = selected_smartstore(
    (smartstore_owner or {}).get("spec", {}).get("smartstore")
)
if live_smartstore != expected_smartstore:
    raise SystemExit(
        "ERROR: automated upgrade cannot change SmartStore volume/index identity; "
        f"live={live_smartstore}, reviewed={expected_smartstore}"
    )

def defaults_map(item):
    value = item.get("spec", {}).get("defaults", "")
    return {
        match.group(1): match.group(2).strip().strip(chr(34)).strip(chr(39))
        for match in re.finditer(r"^\\s*([A-Za-z0-9_]+):\\s*([^#\\n]+)", value, re.MULTILINE)
    }

def exact_zone(item, field, zone):
    value = item.get("spec", {}).get(field, {})
    if field == "affinity":
        value = value.get("nodeAffinity", {})
    terms = value.get("requiredDuringSchedulingIgnoredDuringExecution", {}).get(
        "nodeSelectorTerms", []
    )
    return terms == [
        {
            "matchExpressions": [
                {
                    "key": "topology.kubernetes.io/zone",
                    "operator": "In",
                    "values": [zone],
                }
            ]
        }
    ]

if expected_m4:
    by_identity = {
        (item.get("kind"), item.get("metadata", {}).get("name")): item
        for item in items
    }
    manager = by_identity[("ClusterManager", "cm")]
    manager_defaults = defaults_map(manager)
    for key, value in expected_m4["manager_defaults"].items():
        if manager_defaults.get(key) != value:
            raise SystemExit(f"ERROR: M4 ClusterManager defaults changed at {key}")
    if not exact_zone(manager, "affinity", expected_m4["manager_zone"]):
        raise SystemExit("ERROR: M4 ClusterManager zone change requires a migration handoff")
    for name, contract in expected_m4["indexers"].items():
        item = by_identity[("IndexerCluster", name)]
        if defaults_map(item).get("site") != contract["site"] or not exact_zone(
            item, "affinity", contract["zone"]
        ):
            raise SystemExit(f"ERROR: M4 {name} site/zone change requires a migration handoff")
    search = by_identity[("SearchHeadCluster", "shc")]
    if (
        defaults_map(search).get("site") != expected_m4["search_site"]
        or not exact_zone(search, "affinity", expected_m4["search_zone"])
        or not exact_zone(search, "deployerNodeAffinity", expected_m4["search_zone"])
    ):
        raise SystemExit("ERROR: M4 SearchHeadCluster site/zone change requires a migration handoff")
    for kind in ("LicenseManager", "MonitoringConsole"):
        item = by_identity.get((kind, "lm" if kind == "LicenseManager" else "mc"))
        if item is not None and not exact_zone(item, "affinity", expected_m4["manager_zone"]):
            raise SystemExit(f"ERROR: M4 {kind} zone change requires a migration handoff")

def numeric(value):
    reference = (value or "").split("@", 1)[0]
    match = re.search(r":(\\d+)\\.(\\d+)\\.(\\d+)(?:[-+]|$)", reference)
    return tuple(map(int, match.groups())) if match else None

target = numeric("image:" + target_version)
if target is None:
    raise SystemExit("ERROR: target Splunk image version cannot be verified")
for item in items:
    if item.get("kind") not in {
        "Standalone", "ClusterManager", "IndexerCluster", "SearchHeadCluster",
        "LicenseManager", "MonitoringConsole", "IngestorCluster",
    }:
        continue
    image = item.get("spec", {}).get("image", "")
    current = numeric(image)
    if current is None:
        raise SystemExit(f"ERROR: live {item.get('kind')} image cannot be verified: {image!r}")
    if target < current:
        raise SystemExit(
            f"ERROR: Splunk image downgrade is unsupported: {image} -> {target_version}"
        )
    current_line = current[:2]
    target_line = target[:2]
    allowed_hops = {
        (9, 4): {(10, 0), (10, 2)},
        (10, 0): {(10, 2), (10, 4)},
        (10, 2): {(10, 4)},
    }
    if current_line != target_line and target_line not in allowed_hops.get(
        current_line, set()
    ):
        raise SystemExit(
            "ERROR: unsupported direct Splunk upgrade hop: "
            f"{current_line} -> {target_line}; render the documented intermediate line first"
        )
    if target == current and image != target_image:
        raise SystemExit(
            "ERROR: replacing a same-version Splunk image/tag/digest requires a "
            f"manual image provenance handoff: {image} -> {target_image}"
        )
    spec = item.get("spec", {})
    for field, wanted in expected_storage.items():
        live = spec.get(field)
        if not isinstance(live, dict):
            raise SystemExit(
                f"ERROR: live {item.get('kind')} has no verifiable persistent {field}"
            )
        actual = {
            "ephemeralStorage": live.get("ephemeralStorage", False),
            "storageCapacity": live.get("storageCapacity"),
            "storageClassName": live.get("storageClassName") or "",
        }
        if actual != wanted:
            raise SystemExit(
                f"ERROR: automated upgrade cannot change persistent storage for "
                f"{item.get('kind')}/{item.get('metadata', {}).get('name')} at {field}: "
                f"live={actual}, reviewed={wanted}; use a storage migration/expansion handoff"
            )
"""
        collect_live_code = """import json
import subprocess
import sys

namespace = sys.argv[1]
items = []
for resource in (
    "standalones", "clustermanagers", "indexerclusters", "searchheadclusters",
    "licensemanagers", "monitoringconsoles", "ingestorclusters", "queues",
    "objectstorages",
):
    crd = subprocess.run(
        ["kubectl", "get", "crd", f"{resource}.enterprise.splunk.com", "--ignore-not-found", "-o", "name"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if crd.returncode:
        raise SystemExit(crd.stderr.strip())
    if not crd.stdout.strip():
        continue
    result = subprocess.run(
        ["kubectl", "get", resource, "--namespace", namespace, "-o", "json"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise SystemExit(result.stderr.strip())
    items.extend(json.loads(result.stdout).get("items", []))
print(json.dumps({"items": items}))
"""
        expected_upgrade_names: dict[str, list[str]] = {}
        if args.architecture == "s1":
            expected_upgrade_names["Standalone"] = ["s1"]
        else:
            expected_upgrade_names.update(
                {
                    "ClusterManager": ["cm"],
                    "IndexerCluster": (
                        [
                            f"idxc-site{index}"
                            for index in range(1, int(args.site_count) + 1)
                        ]
                        if args.architecture == "m4"
                        else ["idxc"]
                    ),
                    "SearchHeadCluster": ["shc"],
                }
            )
        if args.license_file and args.architecture != "s1":
            expected_upgrade_names["LicenseManager"] = ["lm"]
        if not args.disable_monitoring_console and args.architecture != "s1":
            expected_upgrade_names["MonitoringConsole"] = ["mc"]
        if args.indexing_ingestion_separation:
            expected_upgrade_names.update(
                {
                    "IngestorCluster": ["ingestor"],
                    "ObjectStorage": ["ingest-object-storage"],
                    "Queue": ["ingest-queue"],
                }
            )
        expected_upgrade_names = dict(sorted(expected_upgrade_names.items()))
        expected_upgrade_storage = {
            "etcVolumeStorageConfig": {
                "ephemeralStorage": False,
                "storageCapacity": args.etc_storage,
                "storageClassName": args.storage_class,
            },
            "varVolumeStorageConfig": {
                "ephemeralStorage": False,
                "storageCapacity": args.var_storage,
                "storageClassName": args.storage_class,
            },
        }
        if args.smartstore_bucket:
            smartstore_endpoint = (
                args.smartstore_endpoint
                if args.smartstore_provider == "minio"
                else aws_service_endpoint(
                    "s3",
                    args.smartstore_region,
                    args.smartstore_endpoint,
                    "--smartstore-endpoint",
                )
            )
            smartstore_path = args.smartstore_bucket
            if args.smartstore_prefix:
                smartstore_path = (
                    f"{smartstore_path.rstrip('/')}/{args.smartstore_prefix.strip('/')}"
                )
            expected_upgrade_smartstore = {
                "defaults": {"volumeName": "remote_store"},
                "indexes": sorted(
                    [
                        {
                            "name": name,
                            "remotePath": "$_index_name",
                            "volumeName": "remote_store",
                        }
                        for name in validate_splunk_indexes(
                            args.smartstore_indexes, "--smartstore-indexes"
                        )
                    ],
                    key=lambda entry: entry["name"],
                ),
                "volumes": [
                    {
                        "name": "remote_store",
                        "storageType": "s3",
                        "provider": args.smartstore_provider,
                        "path": smartstore_path,
                        "endpoint": smartstore_endpoint,
                        "region": args.smartstore_region,
                        "secretRef": args.smartstore_secret_ref or None,
                    }
                ],
            }
        else:
            expected_upgrade_smartstore = {
                "defaults": {"volumeName": None},
                "indexes": [],
                "volumes": [],
            }
        expected_upgrade_m4 = {}
        if args.architecture == "m4":
            site_names = [
                f"site{index}" for index in range(1, int(args.site_count) + 1)
            ]
            site_zones = split_csv(args.site_zones)
            expected_upgrade_m4 = {
                "manager_defaults": {
                    "site": args.manager_site,
                    "all_sites": ",".join(site_names),
                    "multisite_replication_factor_origin": "1",
                    "multisite_replication_factor_total": "2",
                    "multisite_search_factor_origin": "1",
                    "multisite_search_factor_total": "2",
                },
                "manager_zone": args.manager_zone,
                "search_site": args.search_head_site,
                "search_zone": args.search_head_zone,
                "indexers": {
                    f"idxc-{site}": {"site": site, "zone": site_zones[index]}
                    for index, site in enumerate(site_names)
                },
            }
        expected_license_name = ""
        expected_license_namespace = ""
        if args.license_file and args.architecture != "s1":
            expected_license_name = "lm"
        elif args.existing_license_manager:
            expected_license_name = args.existing_license_manager
            expected_license_namespace = args.existing_license_manager_namespace
        expected_upgrade_refs = {}
        expected_upgrade_runtime = {}
        for kind in expected_upgrade_names:
            if kind in {"Queue", "ObjectStorage"}:
                continue
            cluster_manager_name = (
                "cm"
                if args.architecture in {"c3", "m4"}
                and kind
                in {
                    "LicenseManager",
                    "IndexerCluster",
                    "SearchHeadCluster",
                    "MonitoringConsole",
                }
                else ""
            )
            monitoring_name = (
                "mc"
                if not args.disable_monitoring_console
                and args.architecture != "s1"
                and kind != "MonitoringConsole"
                else ""
            )
            license_name = (
                ""
                if kind == "LicenseManager"
                or (kind == "Standalone" and bool(args.license_file))
                else expected_license_name
            )
            expected_upgrade_refs[kind] = {
                "clusterManagerRef": {
                    "apiVersion": "", "fieldPath": "", "kind": "",
                    "name": cluster_manager_name, "namespace": "",
                    "resourceVersion": "", "uid": "",
                },
                "monitoringConsoleRef": {
                    "apiVersion": "", "fieldPath": "", "kind": "",
                    "name": monitoring_name, "namespace": "",
                    "resourceVersion": "", "uid": "",
                },
                "licenseManagerRef": {
                    "apiVersion": "", "fieldPath": "", "kind": "",
                    "name": license_name,
                    "namespace": expected_license_namespace if license_name else "",
                    "resourceVersion": "", "uid": "",
                },
            }
            replicas = None
            if kind == "Standalone":
                replicas = int(args.standalone_replicas)
            elif kind == "IndexerCluster":
                replicas = int(args.indexer_replicas)
            elif kind == "SearchHeadCluster":
                replicas = int(args.search_head_replicas)
            elif kind == "IngestorCluster":
                replicas = int(args.ingestor_replicas)
            service_account = (
                args.splunk_service_account
                if kind in {"Standalone", "IndexerCluster"}
                else ""
            )
            if args.indexing_ingestion_separation and kind in {
                "ClusterManager",
                "IndexerCluster",
                "IngestorCluster",
            }:
                service_account = args.ingestor_service_account
            expected_upgrade_runtime[kind] = {
                "replicas": replicas,
                "serviceAccount": service_account,
            }
        lines.append(
            f"python3 -c {shell_quote(collect_live_code)} {shell_quote(args.namespace)} | "
            f"python3 -c {shell_quote(live_upgrade_guard_code)} "
            f"{shell_quote(args.release_name)} {shell_quote(args.architecture)} "
            f"{shell_quote(effective_splunk_version(args))} "
            f"{shell_quote(splunk_image(args))} "
            f"{shell_quote(bool_word(args.indexing_ingestion_separation))} "
            f"{shell_quote(args.site_count)} "
            f"{shell_quote(json.dumps(expected_upgrade_names, sort_keys=True))} "
            f"{shell_quote(json.dumps(expected_upgrade_storage, sort_keys=True))} "
            f"{shell_quote(json.dumps(expected_upgrade_smartstore, sort_keys=True))} "
            f"{shell_quote(json.dumps(expected_upgrade_m4, sort_keys=True))} "
            f"{shell_quote(json.dumps(expected_upgrade_refs, sort_keys=True))} "
            f"{shell_quote(json.dumps(expected_upgrade_runtime, sort_keys=True))} "
            f"{shell_quote(args.existing_license_manager if args.existing_license_manager_namespace in {'', args.namespace} else '')} "
            f"{shell_quote(args.namespace)}"
        )
        operator_owner_guard = """import json
import re
import sys
raw = sys.stdin.read().strip()
if not raw:
    raise SystemExit("ERROR: reviewed operator upgrade has no live Deployment")
item = json.loads(raw)
owner = item.get("metadata", {}).get("annotations", {}).get("meta.helm.sh/release-name")
owner_namespace = item.get("metadata", {}).get("annotations", {}).get(
    "meta.helm.sh/release-namespace"
)
if owner != sys.argv[1] or owner_namespace != sys.argv[4]:
    raise SystemExit(
        f"ERROR: live operator Deployment belongs to {owner!r}, not reviewed release {sys.argv[1]!r}"
    )
target_image = sys.argv[2]
target_version = tuple(map(int, sys.argv[3].split(".")))
containers = item.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
operator_images = [
    container.get("image", "")
    for container in containers
    if container.get("name") == "manager"
]
if len(operator_images) != 1:
    raise SystemExit("ERROR: live Splunk Operator image identity is ambiguous")
live_image = operator_images[0]
match = re.search(
    r":(\\d+)\\.(\\d+)\\.(\\d+)(?:-distroless)?(?:@|$)",
    live_image.split("@", 1)[0],
)
if not match:
    raise SystemExit(f"ERROR: live Splunk Operator image version is unverifiable: {live_image!r}")
live_version = tuple(map(int, match.groups()))
if live_version <= (1, 0, 5) and target_version > live_version:
    raise SystemExit(
        "ERROR: Operator 1.0.5 or older requires the official 1.1.0 migration/cleanup "
        "handoff before upgrading to 3.1"
    )
if target_version < live_version:
    raise SystemExit(
        f"ERROR: Splunk Operator image downgrade is unsupported: {live_image} -> {target_image}"
    )
if target_version == live_version and live_image != target_image:
    raise SystemExit(
        "ERROR: replacing a same-version Operator image/tag/digest requires a "
        f"manual image provenance handoff: {live_image} -> {target_image}"
    )
spec = item.get("spec", {})
status = item.get("status", {})
replicas = spec.get("replicas", 1)
if (
    status.get("observedGeneration") != item.get("metadata", {}).get("generation")
    or status.get("updatedReplicas", 0) != replicas
    or status.get("availableReplicas", 0) != replicas
    or status.get("readyReplicas", 0) != replicas
):
    raise SystemExit("ERROR: Splunk Operator Deployment is not fully rolled out")
"""
        lines.append(
            f"kubectl get deployment splunk-operator-controller-manager --namespace {shell_quote(args.operator_namespace)} --ignore-not-found -o json | "
            f"python3 -c {shell_quote(operator_owner_guard)} "
            f"{shell_quote(args.operator_release_name)} {shell_quote(operator_image(args))} "
            f"{shell_quote(args.operator_version)} {shell_quote(args.operator_namespace)}"
        )
        pod_health_guard = """import json
import sys
items = json.load(sys.stdin).get("items", [])
splunk = [item for item in items if item.get("metadata", {}).get("name", "").startswith("splunk-")]
if not splunk:
    raise SystemExit("ERROR: reviewed upgrade has no live Splunk pods")
for item in splunk:
    name = item.get("metadata", {}).get("name", "unknown")
    status = item.get("status", {})
    ready = any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in status.get("conditions", [])
    )
    containers = status.get("containerStatuses", [])
    if status.get("phase") != "Running" or not ready or not containers or not all(
        container.get("ready") for container in containers
    ):
        raise SystemExit(f"ERROR: live Splunk pod is unhealthy before upgrade: {name}")
"""
        lines.append(
            f"kubectl get pods --namespace {shell_quote(args.namespace)} -o json | "
            f"python3 -c {shell_quote(pod_health_guard)}"
        )
    else:
        fresh_guard_code = """import json
import sys
raw = sys.stdin.read().strip()
if not raw:
    raise SystemExit(0)
payload = json.loads(raw)
items = payload.get("items", []) if isinstance(payload, dict) else []
allowed_name = sys.argv[1] if len(sys.argv) > 1 else ""
if allowed_name:
    items = [
        item for item in items
        if not (
            item.get("kind") == "LicenseManager"
            and item.get("metadata", {}).get("name") == allowed_name
        )
    ]
if items:
    names = [f"{item.get('kind')}/{item.get('metadata', {}).get('name')}" for item in items]
    raise SystemExit("ERROR: existing Splunk custom resources require a reviewed --allow-upgrade bundle: " + ", ".join(names))
"""
        fresh_resource_checks = []
        for resource in (
            "standalones",
            "clustermanagers",
            "indexerclusters",
            "searchheadclusters",
            "licensemanagers",
            "monitoringconsoles",
            "ingestorclusters",
            "queues",
            "objectstorages",
        ):
            allowed_name = (
                args.existing_license_manager
                if resource == "licensemanagers"
                and args.existing_license_manager_namespace in {"", args.namespace}
                else ""
            )
            fresh_resource_checks.append(
                f"  if kubectl get crd {resource}.enterprise.splunk.com --ignore-not-found -o name | grep -q .; then kubectl get {resource} --namespace {shell_quote(args.namespace)} -o json | python3 -c {shell_quote(fresh_guard_code)} {shell_quote(allowed_name)}; fi"
            )
        lines.extend(
            [
                'if [[ "${SOK_VALIDATE_EXISTING:-false}" != true ]]; then',
                f"  if helm list --all --namespace {shell_quote(args.operator_namespace)} -q | grep -Fxq {shell_quote(args.operator_release_name)}; then printf 'ERROR: Existing operator release requires a reviewed --allow-upgrade bundle.\\n' >&2; exit 1; fi",
                f"  if helm list --all --namespace {shell_quote(args.namespace)} -q | grep -Fxq {shell_quote(args.release_name)}; then printf 'ERROR: Existing Enterprise release requires a reviewed --allow-upgrade bundle.\\n' >&2; exit 1; fi",
                *fresh_resource_checks,
                f"  if kubectl get deployment splunk-operator-controller-manager --namespace {shell_quote(args.operator_namespace)} --ignore-not-found -o name | grep -q .; then printf 'ERROR: An existing Splunk Operator Deployment requires a reviewed --allow-upgrade bundle.\\n' >&2; exit 1; fi",
                *(
                    [
                        f"  if kubectl get configmap splunk-licenses --namespace {shell_quote(args.namespace)} --ignore-not-found -o name | grep -q .; then printf 'ERROR: Existing splunk-licenses ConfigMap requires a reviewed --allow-upgrade bundle.\\n' >&2; exit 1; fi"
                    ]
                    if args.license_file
                    else []
                ),
                "fi",
            ]
        )
    if args.storage_class:
        lines.append(
            f"kubectl get storageclass {shell_quote(args.storage_class)} >/dev/null"
        )
    secret_key_guard_code = """import base64
import binascii
import json
import sys
payload = json.load(sys.stdin)
data = payload.get("data", {})
if not isinstance(data, dict) or payload.get("stringData"):
    raise SystemExit("ERROR: referenced Kubernetes Secret has an invalid API representation")
if payload.get("type") not in (None, "", "Opaque"):
    raise SystemExit("ERROR: referenced Kubernetes Secret must use type Opaque")
keys = set(data)
required = {"s3_access_key", "s3_secret_key"}
missing = sorted(required - keys)
if missing:
    raise SystemExit(
        "ERROR: referenced Kubernetes Secret is missing required key names: "
        + ", ".join(missing)
    )
for key in sorted(required):
    value = data.get(key)
    if not isinstance(value, str):
        raise SystemExit(f"ERROR: referenced Kubernetes Secret key {key!r} is not base64 text")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SystemExit(
            f"ERROR: referenced Kubernetes Secret key {key!r} is not valid base64"
        ) from exc
    if not decoded or len(decoded) > 65536:
        raise SystemExit(
            f"ERROR: referenced Kubernetes Secret key {key!r} must decode to 1..65536 bytes"
        )
"""
    if args.smartstore_secret_ref:
        lines.append(
            f"kubectl get secret {shell_quote(args.smartstore_secret_ref)} --namespace {shell_quote(args.namespace)} -o json | "
            f"python3 -c {shell_quote(secret_key_guard_code)}"
        )
    app_repo_secrets, app_repo_service_accounts = app_repo_identity_references(
        args.enterprise_values_overlay
    )
    for secret_name in sorted(app_repo_secrets):
        lines.append(
            f"kubectl get secret {shell_quote(secret_name)} --namespace "
            f"{shell_quote(args.namespace)} -o name >/dev/null"
        )
    for service_account in sorted(app_repo_service_accounts):
        lines.append(
            f"kubectl get serviceaccount {shell_quote(service_account)} --namespace "
            f"{shell_quote(args.operator_namespace)} -o name >/dev/null"
        )
    if args.existing_license_manager:
        lm_namespace = args.existing_license_manager_namespace or args.namespace
        license_manager_guard = """import json
import sys
item = json.load(sys.stdin)
phase = item.get("status", {}).get("phase")
if phase != "Ready":
    raise SystemExit(
        f"ERROR: existing LicenseManager is not Ready (phase={phase!r}); "
        "resolve licensing health before applying dependent resources"
    )
"""
        lines.append(
            f"kubectl get licensemanager {shell_quote(args.existing_license_manager)} --namespace {shell_quote(lm_namespace)} -o json | "
            f"python3 -c {shell_quote(license_manager_guard)}"
        )
    if args.splunk_service_account:
        irsa_service_account_guard = """import json
import sys

item = json.load(sys.stdin)
metadata = item.get("metadata", {})
annotations = metadata.get("annotations", {})
if (
    item.get("apiVersion") != "v1"
    or item.get("kind") != "ServiceAccount"
    or metadata.get("name") != sys.argv[1]
    or metadata.get("namespace") != sys.argv[2]
    or not metadata.get("uid")
    or metadata.get("deletionTimestamp")
):
    raise SystemExit("ERROR: reviewed AWS IRSA ServiceAccount identity differs")
if annotations.get("eks.amazonaws.com/role-arn") != sys.argv[3]:
    raise SystemExit("ERROR: reviewed AWS IRSA role annotation differs")
if annotations.get("eks.amazonaws.com/token-expiration") != sys.argv[4]:
    raise SystemExit("ERROR: reviewed AWS IRSA token-expiration annotation differs")
if annotations.get("eks.amazonaws.com/audience") not in (None, "sts.amazonaws.com"):
    raise SystemExit("ERROR: reviewed AWS IRSA audience must be sts.amazonaws.com")
if annotations.get("eks.amazonaws.com/sts-regional-endpoints") != "true":
    raise SystemExit("ERROR: reviewed AWS IRSA must enable regional STS endpoints")
"""
        lines.append(
            f"kubectl get serviceaccount {shell_quote(args.splunk_service_account)} "
            f"--namespace {shell_quote(args.namespace)} -o json | python3 -c "
            f"{shell_quote(irsa_service_account_guard)} "
            f"{shell_quote(args.splunk_service_account)} "
            f"{shell_quote(args.namespace)} "
            f"{shell_quote(args.splunk_irsa_role_arn)} "
            f"{shell_quote(args.splunk_irsa_token_expiration)}"
        )
        irsa_probe_guard = """import json
import sys

pod = json.load(sys.stdin)
spec = pod.get("spec", {})
if pod.get("apiVersion") != "v1" or pod.get("kind") != "Pod":
    raise SystemExit("ERROR: AWS IRSA admission probe returned an invalid Pod")
if spec.get("serviceAccountName") != sys.argv[1]:
    raise SystemExit("ERROR: AWS IRSA admission probe service account differs")
volumes = [
    volume for volume in spec.get("volumes", [])
    if volume.get("name") == "aws-iam-token"
]
volume = volumes[0] if len(volumes) == 1 else {}
projected = volume.get("projected", {})
sources = projected.get("sources", [])
token = (
    sources[0].get("serviceAccountToken", {})
    if len(sources) == 1 and isinstance(sources[0], dict)
    else {}
)
if (
    set(volume) != {"name", "projected"}
    or set(projected) - {"defaultMode", "sources"}
    or projected.get("defaultMode", 420) != 420
    or len(sources) != 1
    or set(sources[0]) != {"serviceAccountToken"}
    or set(token) != {"audience", "expirationSeconds", "path"}
    or token.get("audience") != "sts.amazonaws.com"
    or token.get("expirationSeconds") != int(sys.argv[3])
    or token.get("path") != "token"
):
    raise SystemExit("ERROR: AWS IRSA admission probe token volume differs")


def validate_container(container, name):
    if container.get("name") != name:
        raise SystemExit("ERROR: AWS IRSA admission probe container inventory differs")
    env = container.get("env", [])
    aws_names = {
        "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
        "AWS_DEFAULT_REGION",
        "AWS_REGION",
        "AWS_ROLE_ARN",
        "AWS_STS_REGIONAL_ENDPOINTS",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
    }
    aws_env = [entry for entry in env if entry.get("name") in aws_names]
    if (
        len({entry.get("name") for entry in aws_env}) != len(aws_env)
        or any(set(entry) != {"name", "value"} for entry in aws_env)
    ):
        raise SystemExit("ERROR: AWS IRSA admission probe environment is ambiguous")
    values = {entry.get("name"): entry.get("value") for entry in aws_env}
    required = {
        "AWS_ROLE_ARN": sys.argv[2],
        "AWS_STS_REGIONAL_ENDPOINTS": "regional",
        "AWS_WEB_IDENTITY_TOKEN_FILE": (
            "/var/run/secrets/eks.amazonaws.com/serviceaccount/token"
        ),
    }
    if any(values.get(key) != value for key, value in required.items()):
        raise SystemExit("ERROR: AWS IRSA admission probe environment differs")
    region = {
        key: values[key]
        for key in ("AWS_DEFAULT_REGION", "AWS_REGION")
        if key in values
    }
    if region not in (
        {},
        {"AWS_DEFAULT_REGION": sys.argv[4], "AWS_REGION": sys.argv[4]},
    ) or set(values) - set(required) - set(region):
        raise SystemExit("ERROR: AWS IRSA admission probe region/credential mode differs")
    mounts = [
        mount for mount in container.get("volumeMounts", [])
        if mount.get("name") == "aws-iam-token"
        or mount.get("mountPath")
        == "/var/run/secrets/eks.amazonaws.com/serviceaccount"
    ]
    if mounts != [{
        "name": "aws-iam-token",
        "readOnly": True,
        "mountPath": "/var/run/secrets/eks.amazonaws.com/serviceaccount",
    }]:
        raise SystemExit("ERROR: AWS IRSA admission probe token mount differs")


containers = spec.get("containers", [])
init_containers = spec.get("initContainers", [])
if len(containers) != 1 or len(init_containers) != 1:
    raise SystemExit("ERROR: AWS IRSA admission probe was unexpectedly mutated")
validate_container(containers[0], "main")
validate_container(init_containers[0], "init")
"""
        probe_security = {
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
            "runAsNonRoot": True,
            "runAsUser": 41812,
            "seccompProfile": {"type": "RuntimeDefault"},
        }
        probe_container = {
            "name": "main",
            "image": splunk_image(args),
            "command": ["/bin/true"],
            "securityContext": probe_security,
        }
        irsa_probe = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "generateName": "splunk-irsa-admission-probe-",
                "namespace": args.namespace,
            },
            "spec": {
                "serviceAccountName": args.splunk_service_account,
                "restartPolicy": "Never",
                "securityContext": {
                    "runAsNonRoot": True,
                    "runAsUser": 41812,
                    "seccompProfile": {"type": "RuntimeDefault"},
                },
                "containers": [probe_container],
                "initContainers": [{**probe_container, "name": "init"}],
            },
        }
        lines.append(
            f"printf '%s\\n' {shell_quote(json.dumps(irsa_probe, sort_keys=True))} | "
            "kubectl create --dry-run=server -f - -o json | "
            f"python3 -c {shell_quote(irsa_probe_guard)} "
            f"{shell_quote(args.splunk_service_account)} "
            f"{shell_quote(args.splunk_irsa_role_arn)} "
            f"{shell_quote(args.splunk_irsa_token_expiration)} "
            f"{shell_quote(args.aws_region)}"
        )
    if args.indexing_ingestion_separation:
        if args.queue_secret_ref:
            lines.append(
                f"kubectl get secret {shell_quote(args.queue_secret_ref)} --namespace {shell_quote(args.namespace)} -o json | "
                f"python3 -c {shell_quote(secret_key_guard_code)}"
            )
        if args.allow_upgrade:
            immutable_guard_code = """import json
import sys

raw = sys.stdin.read().strip()
if not raw:
    raise SystemExit(0)
live = json.loads(raw).get("spec", {})
expected = json.loads(sys.argv[1])
resource = sys.argv[2]

def compare(expected_value, actual_value, path="spec"):
    for key, value in expected_value.items():
        actual = actual_value.get(key) if isinstance(actual_value, dict) else None
        if key in {"queueRef", "objectStorageRef"} and isinstance(value, dict):
            fields = (
                "apiVersion", "fieldPath", "kind", "name", "namespace",
                "resourceVersion", "uid",
            )
            expected_ref = {field: value.get(field) or "" for field in fields}
            actual_ref = {
                field: actual.get(field) or "" if isinstance(actual, dict) else ""
                for field in fields
            }
            if actual_ref != expected_ref:
                raise SystemExit(
                    f"ERROR: unsupported immutable reference change for {resource} "
                    f"at {path}.{key}: {actual_ref!r} -> {expected_ref!r}"
                )
        if isinstance(value, dict):
            compare(value, actual or {}, f"{path}.{key}")
        elif actual != value:
            raise SystemExit(
                f"ERROR: unsupported immutable change for {resource} at "
                f"{path}.{key}: {actual!r} -> {value!r}"
            )

compare(expected, live)
"""
            queue_endpoint = aws_service_endpoint(
                "sqs", args.queue_region, args.queue_endpoint, "--queue-endpoint"
            )
            object_endpoint = aws_service_endpoint(
                "s3",
                args.queue_region,
                args.object_storage_endpoint,
                "--object-storage-endpoint",
            )
            immutable_resources = [
                (
                    "queue",
                    "ingest-queue",
                    {
                        "provider": args.queue_provider,
                        "sqs": {
                            "name": args.queue_name,
                            "authRegion": args.queue_region,
                            "endpoint": queue_endpoint,
                            "dlq": args.queue_dlq,
                        },
                    },
                ),
                (
                    "objectstorage",
                    "ingest-object-storage",
                    {
                        "provider": "s3",
                        "s3": {
                            "path": args.object_storage_path,
                            "endpoint": object_endpoint,
                        },
                    },
                ),
                (
                    "indexercluster",
                    "idxc",
                    {
                        "queueRef": {"name": "ingest-queue", "namespace": ""},
                        "objectStorageRef": {
                            "name": "ingest-object-storage", "namespace": ""
                        },
                    },
                ),
                (
                    "ingestorcluster",
                    "ingestor",
                    {
                        "queueRef": {"name": "ingest-queue", "namespace": ""},
                        "objectStorageRef": {
                            "name": "ingest-object-storage", "namespace": ""
                        },
                    },
                ),
            ]
            for resource, name, expected in immutable_resources:
                lines.append(
                    f"kubectl get {resource} {shell_quote(name)} --namespace {shell_quote(args.namespace)} --ignore-not-found -o json | "
                    f"python3 -c {shell_quote(immutable_guard_code)} {shell_quote(json.dumps(expected, sort_keys=True))} {shell_quote(resource + '/' + name)}"
                )
    if args.eks_cluster_name:
        lines.extend(
            [
                "command -v aws >/dev/null",
                f"aws eks describe-cluster --name {shell_quote(args.eks_cluster_name)} --region {shell_quote(args.aws_region)} >/dev/null",
            ]
        )
    if args.architecture == "m4" and args.site_zones:
        for zone in sorted(
            set(
                [
                    *split_csv(args.site_zones),
                    args.manager_zone,
                    args.search_head_zone,
                ]
            )
        ):
            if zone:
                lines.append(
                    f"kubectl get nodes --selector {shell_quote('topology.kubernetes.io/zone=' + zone)} -o name | grep -q ."
                )
    return make_script("\n".join(lines) + "\n")


def render_sok_readme(args: argparse.Namespace) -> str:
    return f"""# Splunk Enterprise Kubernetes Rendered Assets

Target: Splunk Operator for Kubernetes

## Key files

- `namespace.yaml`
- `apply.sh`
- `bundle-verify.py`
- `crds-install.sh`
- `compatibility-check.py`
- `preflight.sh`
- `server-dry-run.sh`
- `verify-cluster.sh`
- `operator-values.yaml`
- `enterprise-values.yaml`
- `helm-install-operator.sh`
- `helm-install-enterprise.sh`
- `status.sh`
- `bundle-manifest.json`

Local-chart/CRD snapshots, EKS/license helpers, and reviewed overlays are added
when their corresponding render options are used.

## Review Points

- SVA architecture: `{args.architecture.upper()}`
- Splunk Operator: `{args.operator_version}`
- Splunk Enterprise image: `{splunk_image(args)}`
- Namespace: `{args.namespace}`
- Operator scope: `{args.operator_scope}`
- Deployment profile: `{args.deployment_profile}`
- StorageClass: `{args.storage_class or "cluster default"}`
- Indexing/ingestion separation: `{bool_word(args.indexing_ingestion_separation)}`
- Splunk General Terms accepted in rendered operator values: `{bool_word(args.accept_splunk_general_terms)}`

Run the repository validator before live use. `preflight.sh` checks the live
Kubernetes version, RBAC, chart/CRD availability, referenced storage and
identities, and upgrade safety. The owner/mode/SHA-256 manifest detects
accidental single-file drift while the manifest and verifier remain trusted;
it is not a signature or an external attestation.

For every SOK reconcile, the operator container must receive
`SPLUNK_GENERAL_TERMS={SGT_ACCEPTANCE}`. This directory renders that only when
the setup command included `--accept-splunk-general-terms`.
"""


def render_sok_assets(args: argparse.Namespace, render_dir: Path) -> list[str]:
    assets: list[str] = []
    # Copy each overlay once through a no-follow descriptor, then validate and
    # consume that exact private snapshot. This closes the source-path swap
    # window between validation and bundle publication.
    rendered_args = argparse.Namespace(**vars(args))
    for attribute, relative, option in (
        (
            "operator_values_overlay",
            "operator-values-overlay.yaml",
            "--operator-values-overlay",
        ),
        (
            "enterprise_values_overlay",
            "enterprise-values-overlay.yaml",
            "--enterprise-values-overlay",
        ),
    ):
        source_value = getattr(args, attribute)
        if not source_value:
            continue
        destination = render_dir / relative
        stage_reviewed_file(
            Path(source_value).expanduser(),
            destination,
            mode=0o600,
            max_bytes=2 * 1024 * 1024,
        )
        validate_non_secret_overlay(str(destination), option)
        setattr(rendered_args, attribute, str(destination))
        assets.append(relative)
    args = rendered_args
    kubeconfig_prefix = (
        "[[ -f \"${PWD}/kubeconfig\" ]] || { printf 'ERROR: expected EKS kubeconfig is missing.\\n' >&2; exit 1; }; "
        'export KUBECONFIG="${PWD}/kubeconfig"\n'
        if args.eks_cluster_name
        else ""
    )
    cluster_guard = "./verify-cluster.sh\n"

    def emit(rel: str, content: str, executable: bool = False) -> None:
        write_file(render_dir / rel, content, executable=executable)
        assets.append(rel)

    local_artifacts = bool(args.operator_chart_archive)
    if local_artifacts:
        actual_artifact_hashes = {
            "operator_chart": file_sha256(Path(args.operator_chart_archive).expanduser()),
            "enterprise_chart": file_sha256(Path(args.enterprise_chart_archive).expanduser()),
            "crds": file_sha256(Path(args.crd_manifest).expanduser()),
        }
        official_hashes = VERIFIED_SOK_ARTIFACT_SHA256.get(args.operator_version)
        verified = (
            official_hashes
            if official_hashes == actual_artifact_hashes
            else actual_artifact_hashes
        )
        artifact_targets = (
            (args.operator_chart_archive, "splunk-operator-chart.tgz", verified["operator_chart"]),
            (args.enterprise_chart_archive, "splunk-enterprise-chart.tgz", verified["enterprise_chart"]),
            (args.crd_manifest, "splunk-operator-crds.yaml", verified["crds"]),
        )
        for source, relative, digest in artifact_targets:
            stage_reviewed_file(
                Path(source).expanduser(), render_dir / relative, digest
            )
            assets.append(relative)
        operator_chart_ref = "./splunk-operator-chart.tgz"
        enterprise_chart_ref = "./splunk-enterprise-chart.tgz"
        crd_ref = "./splunk-operator-crds.yaml"
        helm_repo_setup = ": # reviewed local Helm archives are bundle snapshots"
    else:
        operator_chart_ref = "splunk/splunk-operator"
        enterprise_chart_ref = "splunk/splunk-enterprise"
        crd_ref = (
            "https://github.com/splunk/splunk-operator/releases/download/"
            f"{args.operator_version}/splunk-operator-crds.yaml"
        )
        helm_repo_setup = (
            "helm repo add splunk https://splunk.github.io/splunk-operator/ --force-update\n"
            "helm repo update splunk --timeout 2m"
        )

    emit("README.md", render_sok_readme(args))
    emit(
        "metadata.json",
        json.dumps(
            {
                "target": "sok",
                "architecture": args.architecture,
                "standalone_replicas": int(args.standalone_replicas),
                "site_count": int(args.site_count),
                "indexer_replicas": int(args.indexer_replicas),
                "search_head_replicas": int(args.search_head_replicas),
                "ingestor_replicas": int(args.ingestor_replicas),
                "chart_version": chart_version(args),
                "operator_version": args.operator_version,
                "operator_image": operator_image(args),
                "operator_chart_archive": operator_chart_ref if local_artifacts else None,
                "enterprise_chart_archive": enterprise_chart_ref if local_artifacts else None,
                "crd_manifest": crd_ref if local_artifacts else None,
                "artifact_source_paths": {
                    "operator_chart": canonical_file(args.operator_chart_archive) or None,
                    "enterprise_chart": canonical_file(args.enterprise_chart_archive) or None,
                    "crds": canonical_file(args.crd_manifest) or None,
                },
                "splunk_version": args.splunk_version,
                "splunk_image": splunk_image(args),
                "terms_accepted": args.accept_splunk_general_terms,
                "smartstore_indexes": validate_splunk_indexes(
                    args.smartstore_indexes, "--smartstore-indexes"
                ),
                "effective_splunk_version": effective_splunk_version(args),
                "kubernetes_version": args.kubernetes_version or None,
                "expected_kube_context": args.expected_kube_context or None,
                "expected_api_server": args.expected_api_server or None,
                "expected_cluster_uid": args.expected_cluster_uid or None,
                "eks_cluster_name": args.eks_cluster_name or None,
                "aws_region": args.aws_region or None,
                "namespace": args.namespace,
                "operator_namespace": args.operator_namespace,
                "release_name": args.release_name,
                "operator_release_name": args.operator_release_name,
                "operator_scope": args.operator_scope,
                "watch_namespaces": split_csv(args.watch_namespaces)
                or [args.namespace],
                "deployment_profile": args.deployment_profile,
                "storage_class": args.storage_class or None,
                "etc_storage": args.etc_storage,
                "var_storage": args.var_storage,
                "smartstore_path": (
                    f"{args.smartstore_bucket.rstrip('/')}/{args.smartstore_prefix.strip('/')}"
                    if args.smartstore_bucket and args.smartstore_prefix
                    else args.smartstore_bucket or None
                ),
                "smartstore_endpoint": (
                    (
                        args.smartstore_endpoint
                        if args.smartstore_provider == "minio"
                        else aws_service_endpoint(
                            "s3",
                            args.smartstore_region,
                            args.smartstore_endpoint,
                            "--smartstore-endpoint",
                        )
                    )
                    if args.smartstore_bucket
                    else None
                ),
                "smartstore_provider": (
                    args.smartstore_provider if args.smartstore_bucket else None
                ),
                "smartstore_region": args.smartstore_region or None,
                "smartstore_secret_ref": args.smartstore_secret_ref or None,
                "smartstore_index_inventory_confirmed": (
                    args.confirm_smartstore_index_inventory
                ),
                "smartstore_path_ownership_confirmed": (
                    args.confirm_smartstore_path_ownership
                ),
                "site_zones": split_csv(args.site_zones),
                "manager_site": args.manager_site,
                "search_head_site": args.search_head_site,
                "manager_zone": args.manager_zone or None,
                "search_head_zone": args.search_head_zone or None,
                "splunk_service_account": args.splunk_service_account or None,
                "splunk_irsa_role_arn": args.splunk_irsa_role_arn or None,
                "splunk_irsa_token_expiration": (
                    int(args.splunk_irsa_token_expiration)
                    if args.splunk_service_account
                    else None
                ),
                "ingestor_service_account": (
                    args.ingestor_service_account or None
                    if args.indexing_ingestion_separation
                    else None
                ),
                "local_license_manager": bool(
                    args.license_file and args.architecture != "s1"
                ),
                "license_file_name": (
                    Path(args.license_file).name if args.license_file else None
                ),
                "existing_license_manager": args.existing_license_manager or None,
                "existing_license_manager_namespace": (
                    args.existing_license_manager_namespace or args.namespace
                    if args.existing_license_manager
                    else None
                ),
                "monitoring_console": bool(
                    not args.disable_monitoring_console and args.architecture != "s1"
                ),
                "indexing_ingestion_separation": args.indexing_ingestion_separation,
                "allow_unverified_versions": args.allow_unverified_versions,
                "queue_provider": (
                    args.queue_provider if args.indexing_ingestion_separation else None
                ),
                "queue_name": (
                    args.queue_name if args.indexing_ingestion_separation else None
                ),
                "queue_dlq": (
                    args.queue_dlq if args.indexing_ingestion_separation else None
                ),
                "queue_region": (
                    args.queue_region if args.indexing_ingestion_separation else None
                ),
                "queue_endpoint": (
                    aws_service_endpoint(
                        "sqs",
                        args.queue_region,
                        args.queue_endpoint,
                        "--queue-endpoint",
                    )
                    if args.indexing_ingestion_separation
                    else None
                ),
                "object_storage_path": (
                    args.object_storage_path
                    if args.indexing_ingestion_separation
                    else None
                ),
                "object_storage_endpoint": (
                    aws_service_endpoint(
                        "s3",
                        args.queue_region,
                        args.object_storage_endpoint,
                        "--object-storage-endpoint",
                    )
                    if args.indexing_ingestion_separation
                    else None
                ),
                "queue_secret_workaround": bool(
                    args.indexing_ingestion_separation and args.queue_secret_ref
                ),
                "queue_secret_ref": args.queue_secret_ref or None,
                "allow_upgrade": args.allow_upgrade,
                "splunk_10_4_upgrade_readiness_confirmed": (
                    args.confirm_splunk_10_4_upgrade_readiness
                ),
                "support_matrix_source": "https://github.com/splunk/splunk-operator/releases/tag/3.1.0",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    emit("namespace.yaml", render_namespace(args))
    emit(
        "compatibility-check.py",
        Path(__file__).with_name("compatibility.py").read_text(encoding="utf-8"),
        executable=True,
    )
    if args.expected_kube_context:
        cluster_verify_body = f"""{kubeconfig_prefix}actual_context="$(kubectl config current-context)"
[[ "${{actual_context}}" == {shell_quote(args.expected_kube_context)} ]] || {{ printf 'ERROR: kube context differs: %s\\n' "${{actual_context}}" >&2; exit 1; }}
actual_server="$(kubectl config view --minify -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)["clusters"][0]["cluster"]["server"])')"
[[ "${{actual_server}}" == {shell_quote(args.expected_api_server)} ]] || {{ printf 'ERROR: Kubernetes API server differs: %s\\n' "${{actual_server}}" >&2; exit 1; }}
actual_uid="$(kubectl --request-timeout=30s get namespace kube-system -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)["metadata"]["uid"])')"
[[ "${{actual_uid}}" == {shell_quote(args.expected_cluster_uid)} ]] || {{ printf 'ERROR: Kubernetes cluster UID differs: %s\\n' "${{actual_uid}}" >&2; exit 1; }}
"""
    else:
        cluster_verify_body = (
            "printf 'WARNING: bundle has no reviewed Kubernetes context/server/UID "
            "binding; production rendering would reject this.\\n' >&2\n"
        )
    emit("verify-cluster.sh", make_script(cluster_verify_body), executable=True)
    emit(
        "bundle-verify.py",
        Path(__file__).with_name("bundle_verify.py").read_text(encoding="utf-8"),
        executable=True,
    )
    apply_token = secrets.token_hex(32)
    internal_guard = (
        f"[[ \"${{SOK_APPLY_ORCHESTRATED:-}}\" == {shell_quote(apply_token)} ]] || "
        "{ printf 'ERROR: internal mutation helper; run ./apply.sh.\\n' >&2; exit 1; };\n"
    )
    emit(
        "crds-install.sh",
        make_script(
            f"""{internal_guard}{kubeconfig_prefix}{cluster_guard}kubectl apply -f {shell_quote(crd_ref)} --server-side
kubectl wait --for=condition=Established --timeout=5m -f {shell_quote(crd_ref)}
"""
        ),
        executable=True,
    )
    emit("preflight.sh", render_sok_preflight(args), executable=True)
    emit("operator-values.yaml", render_operator_values(args))
    emit("enterprise-values.yaml", render_enterprise_values(args))
    operator_overlay_line = (
        "values_args+=(--values operator-values-overlay.yaml)"
        if args.operator_values_overlay
        else ":"
    )
    enterprise_overlay_line = (
        "values_args+=(--values enterprise-values-overlay.yaml)"
        if args.enterprise_values_overlay
        else ":"
    )
    allow_upgrade = bool_word(args.allow_upgrade)
    operator_dryrun_overlay_line = (
        "operator_values+=(--values operator-values-overlay.yaml)"
        if args.operator_values_overlay
        else ":"
    )
    enterprise_dryrun_overlay_line = (
        "enterprise_values+=(--values enterprise-values-overlay.yaml)"
        if args.enterprise_values_overlay
        else ":"
    )
    emit(
        "server-dry-run.sh",
        make_script(
            f"""python3 bundle-verify.py verify . sok
phase="${{1:-all}}"
case "${{phase}}" in
  all|operator|enterprise) ;;
  *) printf 'ERROR: server-dry-run phase must be all, operator, or enterprise.\n' >&2; exit 1 ;;
esac
{kubeconfig_prefix}{cluster_guard}operator_values=(--values operator-values.yaml)
enterprise_values=(--values enterprise-values.yaml)
{operator_dryrun_overlay_line}
{enterprise_dryrun_overlay_line}
{helm_repo_setup}
if [[ "${{phase}}" == all || "${{phase}}" == operator ]]; then
helm template {shell_quote(args.operator_release_name)} {shell_quote(operator_chart_ref)} \
  --version {shell_quote(chart_version(args))} \
  --namespace {shell_quote(args.operator_namespace)} \
  "${{operator_values[@]}}" | kubectl apply --server-side --dry-run=server \
  --namespace {shell_quote(args.operator_namespace)} \
  --field-manager=sok-preflight --force-conflicts -f -
fi
if [[ "${{phase}}" == all || "${{phase}}" == enterprise ]]; then
helm template {shell_quote(args.release_name)} {shell_quote(enterprise_chart_ref)} \
  --version {shell_quote(chart_version(args))} \
  --namespace {shell_quote(args.namespace)} \
  "${{enterprise_values[@]}}" | kubectl apply --server-side --dry-run=server \
  --namespace {shell_quote(args.namespace)} \
  --field-manager=sok-preflight --force-conflicts -f -
fi
"""
        ),
        executable=True,
    )
    emit(
        "helm-install-operator.sh",
        make_script(
            f"""{internal_guard}{kubeconfig_prefix}{cluster_guard}if helm list --all --namespace {shell_quote(args.operator_namespace)} -q | grep -Fxq {shell_quote(args.operator_release_name)} && [[ {allow_upgrade} != true ]]; then
  printf 'ERROR: Operator release already exists; rerender with --allow-upgrade after upgrade review.\\n' >&2
  exit 1
fi
values_args=(--values operator-values.yaml)
{operator_overlay_line}
{helm_repo_setup}
kubectl apply -f namespace.yaml
helm upgrade --install {shell_quote(args.operator_release_name)} {shell_quote(operator_chart_ref)} \\
  --version {shell_quote(chart_version(args))} \\
  --namespace {shell_quote(args.operator_namespace)} \\
  --create-namespace \\
  --wait \
  --timeout 15m \
  "${{values_args[@]}}"
"""
        ),
        executable=True,
    )
    emit(
        "helm-install-enterprise.sh",
        make_script(
            f"""{internal_guard}{kubeconfig_prefix}{cluster_guard}if helm list --all --namespace {shell_quote(args.namespace)} -q | grep -Fxq {shell_quote(args.release_name)} && [[ {allow_upgrade} != true ]]; then
  printf 'ERROR: Enterprise release already exists; rerender with --allow-upgrade after backup and upgrade review.\\n' >&2
  exit 1
fi
values_args=(--values enterprise-values.yaml)
{enterprise_overlay_line}
{helm_repo_setup}
kubectl apply -f namespace.yaml
helm upgrade --install {shell_quote(args.release_name)} {shell_quote(enterprise_chart_ref)} \\
  --version {shell_quote(chart_version(args))} \\
  --namespace {shell_quote(args.namespace)} \\
  --create-namespace \\
  --wait \
  --timeout 15m \
  "${{values_args[@]}}"
"""
        ),
        executable=True,
    )
    if args.license_file:
        emit(
            "create-license-configmap.sh",
            make_script(
                f"""{internal_guard}{kubeconfig_prefix}{cluster_guard}[[ -n "${{SOK_LICENSE_FILE:-}}" && -f "${{SOK_LICENSE_FILE}}" && ! -L "${{SOK_LICENSE_FILE}}" ]] || {{ printf 'ERROR: staged license file is missing.\\n' >&2; exit 1; }}
kubectl create configmap splunk-licenses \\
  --namespace {shell_quote(args.namespace)} \\
  --from-file={shell_quote(str(Path(args.license_file).name) + '=')}"${{SOK_LICENSE_FILE}}" \\
  --dry-run=client \\
  -o yaml | kubectl apply -f -
"""
            ),
            executable=True,
        )
    if args.eks_cluster_name:
        emit(
            "eks-update-kubeconfig.sh",
            make_script(
                f"""umask 077
export KUBECONFIG="${{PWD}}/kubeconfig"
aws eks update-kubeconfig --name {shell_quote(args.eks_cluster_name)} --region {shell_quote(args.aws_region)} --kubeconfig "${{KUBECONFIG}}"
kubectl config current-context
kubectl cluster-info
"""
            ),
            executable=True,
        )
    apply_eks = "./eks-update-kubeconfig.sh" if args.eks_cluster_name else ":"
    license_stage = ":"
    license_apply = ":"
    if args.license_file:
        license_stage = f"""apply_stage="$(mktemp -d "${{TMPDIR:-/tmp}}/splunk-sok-apply.XXXXXX")"
chmod 0700 "${{apply_stage}}"
trap 'rm -rf "${{apply_stage}}"' EXIT HUP INT TERM
python3 bundle-verify.py copy-external . {shell_quote(canonical_file(args.license_file))} "${{apply_stage}}/splunk.lic"
export SOK_LICENSE_FILE="${{apply_stage}}/splunk.lic"
"""
        license_apply = "./create-license-configmap.sh"
    emit(
        "apply.sh",
        make_script(
            f"""python3 bundle-verify.py verify . sok
{apply_eks}
./preflight.sh
{license_stage}
export SOK_APPLY_ORCHESTRATED={shell_quote(apply_token)}
if [[ {allow_upgrade} == true ]]; then
  ./server-dry-run.sh operator
  ./crds-install.sh
  ./server-dry-run.sh enterprise
else
  ./verify-cluster.sh
  kubectl apply -f namespace.yaml
  ./crds-install.sh
  ./server-dry-run.sh
fi
./helm-install-operator.sh
{license_apply}
./helm-install-enterprise.sh
"""
        ),
        executable=True,
    )
    expected_pods: list[dict[str, object]] = []
    cr_wait_lines: list[str] = []
    if args.existing_license_manager:
        cr_wait_lines.append(
            f"kubectl wait --for=jsonpath='{{.status.phase}}'=Ready licensemanager/{shell_quote(args.existing_license_manager)} --namespace {shell_quote(args.existing_license_manager_namespace or args.namespace)} --timeout=30m"
        )
    if args.license_file and args.architecture != "s1":
        cr_wait_lines.append(
            f"kubectl wait --for=jsonpath='{{.status.phase}}'=Ready licensemanager/lm --namespace {shell_quote(args.namespace)} --timeout=30m"
        )
        expected_pods.append({"prefix": "splunk-lm-license-manager-", "count": 1})
    if args.architecture == "s1":
        cr_wait_lines.append(
            f"kubectl wait --for=jsonpath='{{.status.phase}}'=Ready standalone/s1 --namespace {shell_quote(args.namespace)} --timeout=30m"
        )
        expected_pods.append(
            {"prefix": "splunk-s1-standalone-", "count": args.standalone_replicas}
        )
    else:
        indexer_names = (
            [f"idxc-site{index}" for index in range(1, int(args.site_count) + 1)]
            if args.architecture == "m4"
            else ["idxc"]
        )
        cr_wait_lines.append(
            f"kubectl wait --for=jsonpath='{{.status.phase}}'=Ready clustermanager/cm --namespace {shell_quote(args.namespace)} --timeout=30m"
        )
        if not args.disable_monitoring_console:
            cr_wait_lines.append(
                f"kubectl wait --for=jsonpath='{{.status.phase}}'=Ready monitoringconsole/mc --namespace {shell_quote(args.namespace)} --timeout=30m"
            )
            expected_pods.append(
                {"prefix": "splunk-mc-monitoring-console-", "count": 1}
            )
        cr_wait_lines.extend(
            [
                *[
                    f"kubectl wait --for=jsonpath='{{.status.phase}}'=Ready indexercluster/{name} --namespace {shell_quote(args.namespace)} --timeout=45m"
                    for name in indexer_names
                ],
                f"kubectl wait --for=jsonpath='{{.status.phase}}'=Ready searchheadcluster/shc --namespace {shell_quote(args.namespace)} --timeout=45m",
            ]
        )
        expected_pods.extend(
            [
                {"prefix": "splunk-cm-cluster-manager-", "count": 1},
                {"prefix": "splunk-shc-search-head-", "count": args.search_head_replicas},
                {"prefix": "splunk-shc-deployer-", "count": 1},
                *[
                    {
                        "prefix": f"splunk-{name}-indexer-",
                        "count": args.indexer_replicas,
                    }
                    for name in indexer_names
                ],
            ]
        )
    if args.indexing_ingestion_separation:
        cr_wait_lines.extend(
            [
                f"kubectl wait --for=jsonpath='{{.status.phase}}'=Ready queue/ingest-queue --namespace {shell_quote(args.namespace)} --timeout=30m",
                f"kubectl wait --for=jsonpath='{{.status.phase}}'=Ready objectstorage/ingest-object-storage --namespace {shell_quote(args.namespace)} --timeout=30m",
                f"kubectl wait --for=jsonpath='{{.status.phase}}'=Ready ingestorcluster/ingestor --namespace {shell_quote(args.namespace)} --timeout=30m",
            ]
        )
        expected_pods.append(
            {"prefix": "splunk-ingestor-ingestor-", "count": args.ingestor_replicas}
        )
    controller_owner_kinds = {
        "standalone": "Standalone",
        "cluster-manager": "ClusterManager",
        "indexer": "IndexerCluster",
        "search-head": "SearchHeadCluster",
        "deployer": "SearchHeadCluster",
        "license-manager": "LicenseManager",
        "monitoring-console": "MonitoringConsole",
        "ingestor": "IngestorCluster",
    }
    expected_controllers = []
    for contract in expected_pods:
        controller_name = str(contract["prefix"]).rstrip("-")
        controller_match = re.fullmatch(
            r"splunk-(.+)-(standalone|cluster-manager|indexer|search-head|deployer|"
            r"license-manager|monitoring-console|ingestor)",
            controller_name,
        )
        if controller_match is None:
            die(f"Cannot derive the reviewed SOK owner for {controller_name!r}.")
        expected_controllers.append(
            {
                "name": controller_name,
                "count": contract["count"],
                "owner_name": controller_match.group(1),
                "owner_kind": controller_owner_kinds[controller_match.group(2)],
            }
        )
    placement_zones: dict[str, str] = {}
    if args.architecture == "m4" and args.site_zones:
        zones = split_csv(args.site_zones)
        placement_zones.update(
            {
                "splunk-cm-cluster-manager-": args.manager_zone,
                "splunk-lm-license-manager-": args.manager_zone,
                "splunk-mc-monitoring-console-": args.manager_zone,
                "splunk-shc-search-head-": args.search_head_zone,
                "splunk-shc-deployer-": args.search_head_zone,
            }
        )
        for index, zone in enumerate(zones, start=1):
            placement_zones[f"splunk-idxc-site{index}-indexer-"] = zone
    placement_contracts = [
        {
            "prefix": contract["prefix"],
            "count": contract["count"],
            "zone": placement_zones.get(str(contract["prefix"]), ""),
        }
        for contract in expected_pods
    ]
    controller_health_code = """import base64
import hashlib
import json
import re
import sys
from decimal import Decimal, InvalidOperation

expected = json.loads(sys.argv[1])
target_image = sys.argv[2]
probe_hashes = json.loads(sys.argv[3])
expected_namespace = sys.argv[4]
expected_general_terms = sys.argv[5]
license_contract = json.loads(sys.argv[6])
items = json.loads(sys.stdin.readline()).get("items", [])
custom_resources = json.loads(sys.stdin.readline()).get("items", [])
config_maps = json.loads(sys.stdin.readline()).get("items", [])
smartstore_secret = json.loads(sys.stdin.read() or "{}")
by_name = {item.get("metadata", {}).get("name", ""): item for item in items}
config_map_by_name = {
    item.get("metadata", {}).get("name", ""): item for item in config_maps
}
if len(config_map_by_name) != len(config_maps):
    raise SystemExit("ERROR: ConfigMap identity is ambiguous")
cr_by_identity = {
    (item.get("kind", ""), item.get("metadata", {}).get("name", "")): item
    for item in custom_resources
}
if len(cr_by_identity) != len(custom_resources):
    raise SystemExit("ERROR: Splunk custom-resource identity is ambiguous")
expected_probe_name = f"splunk-{expected_namespace}-probe-configmap"
probe_config_map = config_map_by_name.get(expected_probe_name, {})
probe_metadata = probe_config_map.get("metadata", {})
probe_data = probe_config_map.get("data", {})
expected_probe_keys = {"livenessProbe.sh", "readinessProbe.sh", "startupProbe.sh"}
if (
    probe_config_map.get("apiVersion") != "v1"
    or probe_config_map.get("kind") != "ConfigMap"
    or probe_metadata.get("name") != expected_probe_name
    or probe_metadata.get("namespace") != expected_namespace
    or not probe_metadata.get("uid")
    or probe_metadata.get("deletionTimestamp")
    or probe_config_map.get("binaryData")
    or probe_config_map.get("immutable") is True
    or set(probe_data) != expected_probe_keys
    or (probe_hashes and any(
        hashlib.sha256(probe_data[name].encode("utf-8")).hexdigest() != digest
        for name, digest in probe_hashes.items()
    ))
):
    raise SystemExit("ERROR: namespace probe ConfigMap identity/content differs")


def normalized_quantity(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise SystemExit("ERROR: StatefulSet resource quantity is malformed")
    text = str(value)
    match = re.fullmatch(
        r"([+-]?(?:[0-9]+(?:\\.[0-9]*)?|\\.[0-9]+))"
        r"(Ki|Mi|Gi|Ti|Pi|Ei|n|u|m|k|M|G|T|P|E|[eE][+-]?[0-9]+)?",
        text,
    )
    if not match:
        raise SystemExit(
            f"ERROR: StatefulSet resource quantity is malformed: {text!r}"
        )
    try:
        quantity = Decimal(match.group(1))
        suffix = match.group(2) or ""
        binary_exponents = {
            "Ki": 1,
            "Mi": 2,
            "Gi": 3,
            "Ti": 4,
            "Pi": 5,
            "Ei": 6,
        }
        decimal_exponents = {
            "n": -9,
            "u": -6,
            "m": -3,
            "": 0,
            "k": 3,
            "M": 6,
            "G": 9,
            "T": 12,
            "P": 15,
            "E": 18,
        }
        if suffix in binary_exponents:
            quantity *= Decimal(1024) ** binary_exponents[suffix]
        elif suffix in decimal_exponents:
            quantity *= Decimal(10) ** decimal_exponents[suffix]
        else:
            quantity *= Decimal(10) ** int(suffix[1:])
    except (InvalidOperation, OverflowError, ValueError):
        raise SystemExit(
            f"ERROR: StatefulSet resource quantity is malformed: {text!r}"
        ) from None
    if not quantity.is_finite() or quantity < 0:
        raise SystemExit(
            f"ERROR: StatefulSet resource quantity is invalid: {text!r}"
        )
    return quantity


def normalized_resources(value):
    if not isinstance(value, dict) or set(value) - {"limits", "requests"}:
        raise SystemExit("ERROR: StatefulSet resource contract is malformed")
    normalized = {}
    for section, quantities in value.items():
        if not isinstance(quantities, dict):
            raise SystemExit("ERROR: StatefulSet resource contract is malformed")
        normalized[section] = {
            name: normalized_quantity(quantity)
            for name, quantity in quantities.items()
        }
    return normalized


def require_config_map(name, owner=None):
    item = config_map_by_name.get(name, {})
    metadata = item.get("metadata", {})
    if (
        item.get("apiVersion") != "v1"
        or item.get("kind") != "ConfigMap"
        or metadata.get("name") != name
        or metadata.get("namespace") != expected_namespace
        or not metadata.get("uid")
        or metadata.get("deletionTimestamp")
        or item.get("immutable") is True
    ):
        raise SystemExit(f"ERROR: ConfigMap/{name} identity differs")
    if owner is not None:
        owners = metadata.get("ownerReferences", [])
        controllers = [entry for entry in owners if entry.get("controller") is True]
        if (
            len(controllers) != 1
            or controllers[0].get("apiVersion")
            != "enterprise.splunk.com/v4"
            or controllers[0].get("kind") != owner.get("kind")
            or controllers[0].get("name") != owner.get("metadata", {}).get("name")
            or controllers[0].get("uid") != owner.get("metadata", {}).get("uid")
        ):
            raise SystemExit(f"ERROR: ConfigMap/{name} owner differs")
    return item


def decoded_smartstore_secret(secret_ref):
    metadata = smartstore_secret.get("metadata", {})
    if (
        smartstore_secret.get("apiVersion") != "v1"
        or smartstore_secret.get("kind") != "Secret"
        or metadata.get("name") != secret_ref
        or metadata.get("namespace") != expected_namespace
        or not metadata.get("uid")
        or not metadata.get("resourceVersion")
        or metadata.get("deletionTimestamp")
    ):
        raise SystemExit("ERROR: SmartStore Secret identity differs")
    decoded = {}
    for key in ("s3_access_key", "s3_secret_key"):
        encoded = smartstore_secret.get("data", {}).get(key)
        try:
            value = base64.b64decode(encoded, validate=True).decode("utf-8")
        except (TypeError, ValueError, UnicodeDecodeError):
            raise SystemExit("ERROR: SmartStore Secret data is malformed") from None
        if not value:
            raise SystemExit("ERROR: SmartStore Secret data is empty")
        decoded[key] = value
    return decoded


def expected_smartstore_data(smartstore):
    defaults = smartstore.get("defaults", {})
    defaults_lines = [
        "[default]",
        "repFactor = auto",
        "maxDataSize = auto",
        "homePath = $SPLUNK_DB/$_index_name/db",
        "coldPath = $SPLUNK_DB/$_index_name/colddb",
        "thawedPath = $SPLUNK_DB/$_index_name/thaweddb",
    ]
    if defaults.get("volumeName"):
        defaults_lines.append(
            f"remotePath = volume:{defaults['volumeName']}/$_index_name"
        )
    for field, setting in (
        ("maxGlobalDataSizeMB", "maxGlobalDataSizeMB"),
        ("maxGlobalRawDataSizeMB", "maxGlobalRawDataSizeMB"),
    ):
        if defaults.get(field):
            defaults_lines.append(f"{setting} = {defaults[field]}")
    defaults_conf = "\\n".join(defaults_lines) + "\\n"

    volumes_conf = ""
    secret_refs = {
        volume.get("secretRef")
        for volume in smartstore.get("volumes", [])
        if volume.get("secretRef")
    }
    if len(secret_refs) > 1:
        raise SystemExit("ERROR: SmartStore Secret references are ambiguous")
    credentials = (
        decoded_smartstore_secret(next(iter(secret_refs))) if secret_refs else {}
    )
    for volume in smartstore.get("volumes", []):
        lines = [
            "",
            f"[volume:{volume.get('name')}]",
            "storageType = remote",
            f"path = s3://{volume.get('path')}",
        ]
        if volume.get("secretRef"):
            lines.extend(
                [
                    f"remote.s3.access_key = {credentials['s3_access_key']}",
                    f"remote.s3.secret_key = {credentials['s3_secret_key']}",
                ]
            )
        lines.extend(
            [
                f"remote.s3.endpoint = {volume.get('endpoint')}",
                f"remote.s3.auth_region = {volume.get('region')}",
            ]
        )
        volumes_conf += "\\n".join(lines) + "\\n"

    indexes_conf = ""
    for index in smartstore.get("indexes", []):
        lines = ["", f"[{index.get('name')}]"]
        if index.get("volumeName"):
            lines.append(
                f"remotePath = volume:{index['volumeName']}/"
                f"{index.get('remotePath') or '$_index_name'}"
            )
        for field, setting in (
            ("hotlistBloomFilterRecencyHours", "hotlist_bloom_filter_recency_hours"),
            ("hotlistRecencySecs", "hotlist_recency_secs"),
            ("maxGlobalDataSizeMB", "maxGlobalDataSizeMB"),
            ("maxGlobalRawDataSizeMB", "maxGlobalRawDataSizeMB"),
        ):
            if index.get(field):
                lines.append(f"{setting} = {index[field]}")
        indexes_conf += "\\n".join(lines) + "\\n"

    cache = smartstore.get("cacheManager", {})
    cache_lines = ["[cachemanager]"]
    for field, setting in (
        ("evictionPadding", "eviction_padding"),
        ("evictionPolicy", "eviction_policy"),
        ("hotlistBloomFilterRecencyHours", "hotlist_bloom_filter_recency_hours"),
        ("hotlistRecencySecs", "hotlist_recency_secs"),
        ("maxCacheSize", "max_cache_size"),
        ("maxConcurrentDownloads", "max_concurrent_downloads"),
        ("maxConcurrentUploads", "max_concurrent_uploads"),
    ):
        if cache.get(field):
            cache_lines.append(f"{setting} = {cache[field]}")
    server_conf = "\\n".join(cache_lines) + "\\n" if len(cache_lines) > 1 else ""
    return {
        "indexes.conf": f"{defaults_conf} {volumes_conf} {indexes_conf}",
        "server.conf": server_conf,
    }


def add_monitoring_value(values, key, value):
    if not value:
        return
    current = values.get(key, "")
    existing = current.split(",") if current else []
    incoming = value.split(",")
    values[key] = ",".join([*existing, *[item for item in incoming if item not in existing]])


def expected_monitoring_console_data(monitoring_name):
    values = {}
    for resource in custom_resources:
        kind = resource.get("kind")
        resource_name = resource.get("metadata", {}).get("name", "")
        spec = resource.get("spec", {})
        if spec.get("monitoringConsoleRef", {}).get("name") != monitoring_name:
            continue
        if kind == "ClusterManager":
            service = f"splunk-{resource_name}-cluster-manager-service"
            add_monitoring_value(values, "SPLUNK_CLUSTER_MASTER_URL", service)
            if "all_sites:" in str(spec.get("defaults", "")):
                add_monitoring_value(values, "SPLUNK_SITE", "site0")
                add_monitoring_value(values, "SPLUNK_MULTISITE_MASTER", service)
        elif kind == "SearchHeadCluster":
            replicas = int(spec.get("replicas", 1))
            headless = f"splunk-{resource_name}-search-head-headless"
            urls = ",".join(
                f"splunk-{resource_name}-search-head-{ordinal}.{headless}."
                f"{expected_namespace}.svc.cluster.local"
                for ordinal in range(replicas)
            )
            add_monitoring_value(values, "SPLUNK_SEARCH_HEAD_URL", urls)
            add_monitoring_value(
                values, "SPLUNK_SEARCH_HEAD_CAPTAIN_URL", urls.split(",")[0]
            )
            add_monitoring_value(
                values,
                "SPLUNK_DEPLOYER_URL",
                f"splunk-{resource_name}-deployer-service",
            )
        elif kind == "Standalone":
            replicas = int(spec.get("replicas", 1))
            headless = f"splunk-{resource_name}-standalone-headless"
            urls = ",".join(
                f"splunk-{resource_name}-standalone-{ordinal}.{headless}."
                f"{expected_namespace}.svc.cluster.local"
                for ordinal in range(replicas)
            )
            add_monitoring_value(values, "SPLUNK_STANDALONE_URL", urls)
        elif kind == "LicenseManager":
            reference = spec.get("licenseManagerRef", {})
            if reference.get("name"):
                service = f"splunk-{reference['name']}-license-manager-service"
                if reference.get("namespace"):
                    service += (
                        f".{reference['namespace']}.svc.cluster.local"
                    )
            else:
                service = f"splunk-{resource_name}-license-manager-service"
            add_monitoring_value(values, "SPLUNK_LICENSE_MASTER_URL", service)
    return values


if license_contract:
    license_map = require_config_map("splunk-licenses")
    license_name = license_contract.get("name")
    data = license_map.get("data", {})
    binary_data = license_map.get("binaryData", {})
    if set(data) | set(binary_data) != {license_name} or set(data) & set(binary_data):
        raise SystemExit("ERROR: license ConfigMap key inventory differs")
    try:
        license_bytes = (
            data[license_name].encode("utf-8")
            if license_name in data
            else base64.b64decode(binary_data[license_name], validate=True)
        )
    except (TypeError, ValueError):
        raise SystemExit("ERROR: license ConfigMap content is malformed") from None
    if hashlib.sha256(license_bytes).hexdigest() != license_contract.get("sha256"):
        raise SystemExit("ERROR: license ConfigMap content differs")


expected_names = {contract["name"] for contract in expected}
role_name = re.compile(
    r"^splunk-.+-(?:standalone|cluster-manager|indexer|search-head|deployer|"
    r"license-manager|monitoring-console|ingestor)$"
)
live_role_names = {name for name in by_name if role_name.fullmatch(name)}
if live_role_names != expected_names:
    raise SystemExit(
        f"ERROR: Splunk StatefulSet inventory differs: live={sorted(live_role_names)}, "
        f"reviewed={sorted(expected_names)}"
    )
for contract in expected:
    name = contract["name"]
    count = int(contract["count"])
    item = by_name.get(name)
    if item is None:
        raise SystemExit(f"ERROR: reviewed StatefulSet is missing: {name}")
    spec = item.get("spec", {})
    status = item.get("status", {})
    metadata = item.get("metadata", {})
    reviewed_cr = cr_by_identity.get((contract["owner_kind"], contract["owner_name"]))
    reviewed_cr_uid = (
        reviewed_cr.get("metadata", {}).get("uid") if reviewed_cr else None
    )
    owners = item.get("metadata", {}).get("ownerReferences", [])
    controller_owners = [owner for owner in owners if owner.get("controller") is True]
    if (
        len(controller_owners) != 1
        or controller_owners[0].get("apiVersion") != "enterprise.splunk.com/v4"
        or controller_owners[0].get("kind") != contract["owner_kind"]
        or controller_owners[0].get("name") != contract["owner_name"]
        or not metadata.get("uid")
        or not reviewed_cr_uid
        or controller_owners[0].get("uid") != reviewed_cr_uid
    ):
        raise SystemExit(f"ERROR: StatefulSet/{name} has an invalid controller owner")
    reviewed_spec = reviewed_cr.get("spec", {})
    role_match = re.fullmatch(
        r"splunk-.+-(standalone|cluster-manager|indexer|search-head|deployer|"
        r"license-manager|monitoring-console|ingestor)",
        name,
    )
    role = role_match.group(1) if role_match else ""
    smartstore = reviewed_spec.get("smartstore", {})
    expects_smartstore_init = bool(smartstore) and role in {
        "standalone",
        "cluster-manager",
    }
    selector = spec.get("selector", {}).get("matchLabels", {})
    template_labels = spec.get("template", {}).get("metadata", {}).get("labels", {})
    retention = spec.get("persistentVolumeClaimRetentionPolicy")
    if (
        spec.get("podManagementPolicy") != "Parallel"
        or spec.get("updateStrategy") != {"type": "OnDelete"}
        or spec.get("minReadySeconds", 0) != 0
        or spec.get("revisionHistoryLimit", 10) != 10
        or spec.get("ordinals", {}).get("start", 0) != 0
        or not selector
        or any(template_labels.get(key) != value for key, value in selector.items())
        or (
            retention is not None
            and (
                retention.get("whenDeleted", "Retain") != "Retain"
                or retention.get("whenScaled", "Retain") != "Retain"
            )
        )
    ):
        raise SystemExit(
            f"ERROR: StatefulSet/{name} lifecycle/selector contract differs"
        )
    pod_spec = spec.get("template", {}).get("spec", {})
    containers = pod_spec.get("containers", [])
    main_containers = [
        container for container in containers if container.get("name") == "splunk"
    ]
    if (
        len(containers) != 1
        or len(main_containers) != 1
        or pod_spec.get("ephemeralContainers")
        or main_containers[0].get("image") != target_image
        or len(pod_spec.get("initContainers", []))
        != (1 if expects_smartstore_init else 0)
    ):
        raise SystemExit(
            f"ERROR: StatefulSet/{name} has not adopted target image {target_image!r}"
        )
    if any(
        pod_spec.get(field) is True
        for field in ("hostNetwork", "hostPID", "hostIPC", "shareProcessNamespace")
    ) or any("hostPath" in volume for volume in pod_spec.get("volumes", [])) or (
        pod_spec.get("terminationGracePeriodSeconds", 30) != 30
    ):
        raise SystemExit(f"ERROR: StatefulSet/{name} enables an unsafe pod/volume mode")
    forbidden_pod_fields = {
        "activeDeadlineSeconds",
        "dnsConfig",
        "hostAliases",
        "hostname",
        "overhead",
        "preemptionPolicy",
        "priority",
        "priorityClassName",
        "readinessGates",
        "resourceClaims",
        "runtimeClassName",
        "schedulingGates",
        "setHostnameAsFQDN",
        "subdomain",
    }
    if (
        any(pod_spec.get(field) not in (None, [], {}) for field in forbidden_pod_fields)
        or pod_spec.get("restartPolicy", "Always") != "Always"
        or pod_spec.get("dnsPolicy", "ClusterFirst") != "ClusterFirst"
        or pod_spec.get("schedulerName", "default-scheduler")
        != "default-scheduler"
        or pod_spec.get("automountServiceAccountToken") not in (None, True)
        or pod_spec.get("enableServiceLinks", True) is not True
        or pod_spec.get("hostUsers", True) is not True
    ):
        raise SystemExit(f"ERROR: StatefulSet/{name} pod runtime contract differs")
    pod_security = pod_spec.get("securityContext", {})
    expected_pod_security = {
        "fsGroup": 41812,
        "fsGroupChangePolicy": "OnRootMismatch",
        "runAsNonRoot": True,
        "runAsUser": 41812,
    }
    if (probe_hashes and pod_security != expected_pod_security) or (
        not probe_hashes
        and (
            pod_security.get("runAsNonRoot") is False
            or pod_security.get("runAsUser") == 0
            or pod_security.get("runAsGroup") == 0
            or pod_security.get("fsGroup") == 0
            or pod_security.get("sysctls")
            or pod_security.get("seccompProfile", {}).get("type") == "Unconfined"
            or pod_security.get("appArmorProfile", {}).get("type") == "Unconfined"
        )
    ):
        raise SystemExit(f"ERROR: StatefulSet/{name} has an unsafe pod security context")
    expected_affinity = json.loads(json.dumps(reviewed_spec.get("affinity", {})))
    if role == "deployer" and reviewed_spec.get("deployerNodeAffinity") is not None:
        expected_affinity["nodeAffinity"] = reviewed_spec["deployerNodeAffinity"]
    pod_anti_affinity = expected_affinity.setdefault("podAntiAffinity", {})
    preferred_anti_affinity = pod_anti_affinity.setdefault(
        "preferredDuringSchedulingIgnoredDuringExecution", []
    )
    preferred_anti_affinity.append(
        {
            "podAffinityTerm": {
                "labelSelector": {
                    "matchExpressions": [
                        {
                            "key": "app.kubernetes.io/instance",
                            "operator": "In",
                            "values": [name],
                        }
                    ]
                },
                "topologyKey": "kubernetes.io/hostname",
            },
            "weight": 100,
        }
    )
    if (
        pod_spec.get("affinity") != expected_affinity
        or pod_spec.get("tolerations", []) != reviewed_spec.get("tolerations", [])
        or pod_spec.get("topologySpreadConstraints", [])
        != reviewed_spec.get("topologySpreadConstraints", [])
        or pod_spec.get("nodeSelector") not in (None, {})
    ):
        raise SystemExit(f"ERROR: StatefulSet/{name} scheduling contract differs")
    expected_container_security = {
        "allowPrivilegeEscalation": False,
        "capabilities": {
            "add": ["NET_BIND_SERVICE"],
            "drop": ["ALL"],
        },
        "privileged": False,
        "runAsNonRoot": True,
        "runAsUser": 41812,
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    for container in containers:
        security = container.get("securityContext", {})
        unsafe_unverified_security = (
            security.get("privileged") is True
            or security.get("allowPrivilegeEscalation") is True
            or security.get("runAsNonRoot") is False
            or security.get("runAsUser") == 0
            or security.get("runAsGroup") == 0
            or security.get("procMount") == "Unmasked"
            or set(security.get("capabilities", {}).get("add", []))
            - {"NET_BIND_SERVICE"}
            or security.get("seccompProfile", {}).get("type") == "Unconfined"
            or security.get("appArmorProfile", {}).get("type") == "Unconfined"
        )
        if (
            (probe_hashes and security != expected_container_security)
            or (not probe_hashes and unsafe_unverified_security)
            or any(
                port.get("hostPort") not in (None, 0)
                for port in container.get("ports", [])
            )
        ):
            raise SystemExit(f"ERROR: StatefulSet/{name} has an unsafe container")
    if expects_smartstore_init:
        init_container = pod_spec.get("initContainers", [])[0]
        smartstore_commands = {
            "standalone": (
                "mkdir -p /opt/splk/etc/apps/splunk-operator/local && "
                "ln -sfn  /mnt/splunk-operator/local/indexes.conf "
                "/opt/splk/etc/apps/splunk-operator/local/indexes.conf && "
                "ln -sfn  /mnt/splunk-operator/local/server.conf "
                "/opt/splk/etc/apps/splunk-operator/local/server.conf"
            ),
            "cluster-manager": (
                "mkdir -p /opt/splk/etc/manager-apps/splunk-operator/local && "
                "ln -sfn /mnt/splunk-operator/local/indexes.conf "
                "/opt/splk/etc/manager-apps/splunk-operator/local/indexes.conf && "
                "ln -sfn /mnt/splunk-operator/local/server.conf "
                "/opt/splk/etc/manager-apps/splunk-operator/local/server.conf"
            ),
        }
        allowed_init_fields = {
            "command",
            "image",
            "imagePullPolicy",
            "name",
            "resources",
            "securityContext",
            "terminationMessagePath",
            "terminationMessagePolicy",
            "volumeMounts",
        }
        if (
            set(init_container) - allowed_init_fields
            or init_container.get("name") != "init"
            or init_container.get("image") != target_image
            or init_container.get("imagePullPolicy", "IfNotPresent")
            != reviewed_spec.get("imagePullPolicy", "IfNotPresent")
            or init_container.get("command")
            != ["bash", "-c", smartstore_commands[role]]
            or init_container.get("volumeMounts")
            != [{"mountPath": "/opt/splk/etc", "name": "pvc-etc"}]
            or normalized_resources(init_container.get("resources", {}))
            != normalized_resources(
                {
                    "limits": {"cpu": "1", "memory": "512Mi"},
                    "requests": {"cpu": "0.25", "memory": "128Mi"},
                }
            )
            or init_container.get("securityContext")
            != expected_container_security
            or init_container.get(
                "terminationMessagePath", "/dev/termination-log"
            )
            != "/dev/termination-log"
            or init_container.get("terminationMessagePolicy", "File") != "File"
        ):
            raise SystemExit(
                f"ERROR: StatefulSet/{name} SmartStore init contract differs"
            )
    expected_ports = {
        "http-splunkweb": (8000, "TCP"),
        "https-splunkd": (8089, "TCP"),
    }
    if role in {"standalone", "indexer", "monitoring-console", "ingestor"}:
        expected_ports.update(
            {"http-hec": (8088, "TCP"), "tcp-s2s": (9997, "TCP")}
        )
    actual_ports = {
        port.get("name"): (port.get("containerPort"), port.get("protocol", "TCP"))
        for port in main_containers[0].get("ports", [])
    }
    if len(actual_ports) != len(main_containers[0].get("ports", [])) or actual_ports != expected_ports:
        raise SystemExit(f"ERROR: StatefulSet/{name} Splunk port contract differs")
    if (
        main_containers[0].get("command")
        or main_containers[0].get("args")
        or main_containers[0].get("lifecycle")
    ):
        raise SystemExit(f"ERROR: StatefulSet/{name} overrides the Splunk image entrypoint")
    allowed_main_fields = {
        "env",
        "envFrom",
        "image",
        "imagePullPolicy",
        "livenessProbe",
        "name",
        "ports",
        "readinessProbe",
        "resources",
        "securityContext",
        "startupProbe",
        "terminationMessagePath",
        "terminationMessagePolicy",
        "volumeMounts",
    }
    if (
        set(main_containers[0]) - allowed_main_fields
        or main_containers[0].get(
            "terminationMessagePath", "/dev/termination-log"
        )
        != "/dev/termination-log"
        or main_containers[0].get("terminationMessagePolicy", "File") != "File"
    ):
        raise SystemExit(f"ERROR: StatefulSet/{name} container runtime differs")
    expected_role = {
        "standalone": "splunk_standalone",
        "cluster-manager": "splunk_cluster_master",
        "indexer": "splunk_indexer",
        "search-head": "splunk_search_head",
        "deployer": "splunk_deployer",
        "license-manager": "splunk_license_master",
        "monitoring-console": "splunk_monitor",
        "ingestor": "splunk_ingestor",
    }.get(role)
    cluster_manager_ref = reviewed_spec.get("clusterManagerRef", {})
    if role == "standalone" and cluster_manager_ref.get("name"):
        expected_role = "splunk_search_head"
    required_env = {
        "SPLUNK_HOME": "/opt/splunk",
        "SPLUNK_START_ARGS": "--accept-license",
        "SPLUNK_HOME_OWNERSHIP_ENFORCEMENT": "false",
        "SPLUNK_ROLE": expected_role,
        "SPLUNK_DECLARATIVE_ADMIN_PASSWORD": "true",
        "SPLUNK_OPERATOR_K8_LIVENESS_DRIVER_FILE_PATH": (
            "/tmp/splunk_operator_k8s/probes/k8_liveness_driver.sh"
        ),
        "SPLUNK_GENERAL_TERMS": expected_general_terms,
        "SPLUNK_SKIP_CLUSTER_BUNDLE_PUSH": "true",
    }
    env = main_containers[0].get("env", [])
    inline_defaults = bool(reviewed_spec.get("defaults"))
    defaults_sources = []
    if inline_defaults:
        defaults_sources.append("/mnt/splunk-defaults/default.yml")
    defaults_sources.append("/mnt/splunk-secrets/default.yml")
    expected_env_values = {
        **required_env,
        "SPLUNK_DEFAULTS_URL": ",".join(defaults_sources),
    }

    def referenced_service(ref, instance_role):
        service = f"splunk-{ref.get('name')}-{instance_role}-service"
        namespace = ref.get("namespace")
        if namespace:
            return f"{service}.{namespace}.svc.cluster.local"
        return service

    if reviewed_spec.get("licenseUrl"):
        expected_env_values["SPLUNK_LICENSE_URI"] = reviewed_spec["licenseUrl"]
    license_manager_ref = reviewed_spec.get("licenseManagerRef", {})
    if role != "license-manager" and license_manager_ref.get("name"):
        expected_env_values["SPLUNK_LICENSE_MASTER_URL"] = referenced_service(
            license_manager_ref, "license-manager"
        )
    if role == "cluster-manager":
        expected_env_values["SPLUNK_CLUSTER_MASTER_URL"] = "localhost"
    elif cluster_manager_ref.get("name"):
        expected_env_values["SPLUNK_CLUSTER_MASTER_URL"] = referenced_service(
            cluster_manager_ref, "cluster-manager"
        )
    monitoring_ref = reviewed_spec.get("monitoringConsoleRef", {})
    if monitoring_ref.get("name"):
        expected_env_values["SPLUNK_MONITORING_CONSOLE_REF"] = monitoring_ref[
            "name"
        ]
    if role in {"search-head", "deployer"}:
        replicas = int(reviewed_spec.get("replicas", count))
        search_head_service = (
            f"splunk-{contract['owner_name']}-search-head-headless"
        )
        search_head_urls = [
            f"splunk-{contract['owner_name']}-search-head-{ordinal}."
            f"{search_head_service}.{expected_namespace}.svc.cluster.local"
            for ordinal in range(replicas)
        ]
        expected_env_values["SPLUNK_SEARCH_HEAD_URL"] = ",".join(
            search_head_urls
        )
        expected_env_values["SPLUNK_SEARCH_HEAD_CAPTAIN_URL"] = search_head_urls[0]
        if role == "search-head":
            expected_env_values["SPLUNK_DEPLOYER_URL"] = (
                f"splunk-{contract['owner_name']}-deployer-service"
            )
    defaults_text = str(reviewed_spec.get("defaults", ""))
    if role == "cluster-manager" and "all_sites:" in defaults_text:
        expected_env_values["SPLUNK_SITE"] = "site0"
        expected_env_values["SPLUNK_MULTISITE_MASTER"] = (
            f"splunk-{contract['owner_name']}-cluster-manager-service"
        )
    if (
        len({item.get("name") for item in env}) != len(env)
        or any(set(item) != {"name", "value"} for item in env)
        or {item.get("name"): item.get("value") for item in env}
        != expected_env_values
    ):
        raise SystemExit(f"ERROR: StatefulSet/{name} environment contract differs")
    env_from = main_containers[0].get("envFrom", [])
    if role == "monitoring-console":
        source = env_from[0] if len(env_from) == 1 else {}
        config_map_ref = source.get("configMapRef", {})
        if (
            set(source) != {"configMapRef"}
            or set(config_map_ref) - {"name", "optional"}
            or config_map_ref.get("name") != name
            or config_map_ref.get("optional") not in (None, False)
        ):
            raise SystemExit(f"ERROR: StatefulSet/{name} envFrom contract differs")
        monitoring_map = require_config_map(name)
        if (
            monitoring_map.get("binaryData")
            or monitoring_map.get("data", {})
            != expected_monitoring_console_data(contract["owner_name"])
            or not monitoring_map.get("metadata", {}).get("resourceVersion")
            or spec.get("template", {}).get("metadata", {}).get(
                "annotations", {}
            ).get("monitoringConsoleConfigRev")
            != monitoring_map.get("metadata", {}).get("resourceVersion")
        ):
            raise SystemExit(
                f"ERROR: StatefulSet/{name} Monitoring Console content/adoption differs"
            )
    elif env_from:
        raise SystemExit(f"ERROR: StatefulSet/{name} has an unreviewed envFrom source")
    if reviewed_spec.get("defaultsUrl") or reviewed_spec.get("defaultsUrlApps"):
        raise SystemExit(f"ERROR: StatefulSet/{name} defaults provenance differs")
    expected_resources = reviewed_spec.get(
        "deployerResourceSpec" if role == "deployer" else "resources", {}
    )
    if normalized_resources(
        main_containers[0].get("resources", {})
    ) != normalized_resources(expected_resources):
        raise SystemExit(f"ERROR: StatefulSet/{name} resource contract differs")
    if main_containers[0].get("imagePullPolicy", "IfNotPresent") != reviewed_spec.get(
        "imagePullPolicy", "IfNotPresent"
    ):
        raise SystemExit(f"ERROR: StatefulSet/{name} image pull policy differs")
    reviewed_service_account = reviewed_spec.get("serviceAccount") or "default"
    if pod_spec.get("serviceAccountName", "default") != reviewed_service_account:
        raise SystemExit(f"ERROR: StatefulSet/{name} service account differs")
    if pod_spec.get("imagePullSecrets", []) != reviewed_spec.get(
        "imagePullSecrets", []
    ):
        raise SystemExit(f"ERROR: StatefulSet/{name} image pull Secrets differ")
    mounts = main_containers[0].get("volumeMounts", [])
    mounts_by_name = {mount.get("name"): mount for mount in mounts}
    if len(mounts_by_name) != len(mounts):
        raise SystemExit(f"ERROR: StatefulSet/{name} has ambiguous volume mounts")
    expected_mounts = {
        "pvc-etc": "/opt/splunk/etc",
        "pvc-var": "/opt/splunk/var",
        "mnt-splunk-secrets": "/mnt/splunk-secrets",
        expected_probe_name: "/mnt/probes",
    }
    license_url = reviewed_spec.get("licenseUrl", "")
    if license_url:
        if not re.fullmatch(r"/mnt/licenses/[A-Za-z0-9][A-Za-z0-9._-]*", license_url):
            raise SystemExit(f"ERROR: StatefulSet/{name} license URL is unreviewed")
        expected_mounts["licenses"] = "/mnt/licenses"
    if inline_defaults:
        expected_mounts["mnt-splunk-defaults"] = "/mnt/splunk-defaults"
    if smartstore:
        expected_mounts["mnt-splunk-operator"] = "/mnt/splunk-operator/local/"
    app_sources = reviewed_spec.get("appRepo", {}).get("appSources", [])
    expects_app_staging = bool(app_sources) and role not in {
        "indexer",
        "search-head",
    }
    if expects_app_staging:
        expected_mounts["operator-staging"] = "/operator-staging/"
    expected_mount_objects = {
        mount_name: {"name": mount_name, "mountPath": mount_path}
        for mount_name, mount_path in expected_mounts.items()
    }
    if mounts_by_name != expected_mount_objects:
        raise SystemExit(f"ERROR: StatefulSet/{name} volume-mount contract differs")
    volumes_by_name = {
        volume.get("name"): volume for volume in pod_spec.get("volumes", [])
    }
    if len(volumes_by_name) != len(pod_spec.get("volumes", [])):
        raise SystemExit(f"ERROR: StatefulSet/{name} has ambiguous volumes")
    expected_volume_names = {expected_probe_name, "mnt-splunk-secrets"}
    if license_url:
        expected_volume_names.add("licenses")
    if inline_defaults:
        expected_volume_names.add("mnt-splunk-defaults")
    if smartstore:
        expected_volume_names.add("mnt-splunk-operator")
    if expects_app_staging:
        expected_volume_names.add("operator-staging")
    if set(volumes_by_name) != expected_volume_names:
        raise SystemExit(f"ERROR: StatefulSet/{name} volume inventory differs")
    probe_volume = volumes_by_name.get(expected_probe_name, {})
    secret_volume = volumes_by_name.get("mnt-splunk-secrets", {})
    if (
        set(probe_volume) != {"name", "configMap"}
        or probe_volume.get("configMap", {}).get("name") != expected_probe_name
        or set(probe_volume.get("configMap", {})) - {"name", "defaultMode"}
        or probe_volume.get("configMap", {}).get("defaultMode", 365) != 365
        or set(secret_volume) != {"name", "secret"}
        or set(secret_volume.get("secret", {}))
        - {"secretName", "defaultMode"}
        or not re.fullmatch(
            re.escape(name) + r"-secret-v[1-9][0-9]*",
            str(secret_volume.get("secret", {}).get("secretName", "")),
        )
        or secret_volume.get("secret", {}).get("defaultMode", 420) != 420
    ):
        raise SystemExit(f"ERROR: StatefulSet/{name} critical volume source differs")
    if license_url:
        license_volume = volumes_by_name["licenses"]
        license_source = license_volume.get("configMap", {})
        if (
            set(license_volume) != {"name", "configMap"}
            or set(license_source) - {"name", "defaultMode"}
            or license_source.get("name") != "splunk-licenses"
            or license_source.get("defaultMode", 420) != 420
        ):
            raise SystemExit(f"ERROR: StatefulSet/{name} license volume differs")
    if inline_defaults:
        defaults_volume = volumes_by_name["mnt-splunk-defaults"]
        defaults_source = defaults_volume.get("configMap", {})
        defaults_kind = {
            "cluster-manager": "indexer",
            "deployer": "search-head",
            "indexer": "indexer",
            "ingestor": "ingestor",
            "license-manager": "license-manager",
            "monitoring-console": "monitoring-console",
            "search-head": "search-head",
            "standalone": "standalone",
        }[role]
        if (
            set(defaults_volume) != {"name", "configMap"}
            or set(defaults_source) - {"name", "defaultMode"}
            or defaults_source.get("name")
            != f"splunk-{contract['owner_name']}-{defaults_kind}-defaults"
            or defaults_source.get("defaultMode", 420) != 420
        ):
            raise SystemExit(f"ERROR: StatefulSet/{name} defaults volume differs")
        defaults_map = require_config_map(
            defaults_source["name"], owner=reviewed_cr
        )
        if (
            defaults_map.get("binaryData")
            or defaults_map.get("data")
            != {"default.yml": reviewed_spec["defaults"]}
            or not defaults_map.get("metadata", {}).get("resourceVersion")
            or spec.get("template", {}).get("metadata", {}).get(
                "annotations", {}
            ).get("defaultConfigRev")
            != defaults_map.get("metadata", {}).get("resourceVersion")
        ):
            raise SystemExit(
                f"ERROR: StatefulSet/{name} defaults content/adoption differs"
            )
    elif "defaultConfigRev" in spec.get("template", {}).get(
        "metadata", {}
    ).get("annotations", {}):
        raise SystemExit(f"ERROR: StatefulSet/{name} has stale defaults adoption")
    if smartstore:
        smartstore_volume = volumes_by_name["mnt-splunk-operator"]
        smartstore_source = smartstore_volume.get("configMap", {})
        smartstore_items = {
            (item.get("key"), item.get("path"), item.get("mode", 420))
            for item in smartstore_source.get("items", [])
        }
        expected_smartstore_items = {
            ("indexes.conf", "indexes.conf", 420),
            ("server.conf", "server.conf", 420),
            ("conftoken", "conftoken", 420),
        }
        expected_smartstore_name = (
            f"splunk-{contract['owner_name']}-"
            f"{str(contract['owner_kind']).lower()}-smartstore"
        )
        if (
            set(smartstore_volume) != {"name", "configMap"}
            or set(smartstore_source) - {"name", "defaultMode", "items"}
            or smartstore_source.get("name") != expected_smartstore_name
            or smartstore_source.get("defaultMode", 420) != 420
            or smartstore_items != expected_smartstore_items
            or len(smartstore_items) != len(smartstore_source.get("items", []))
        ):
            raise SystemExit(f"ERROR: StatefulSet/{name} SmartStore volume differs")
        smartstore_map = require_config_map(
            expected_smartstore_name, owner=reviewed_cr
        )
        smartstore_data = smartstore_map.get("data", {})
        reviewed_smartstore_data = expected_smartstore_data(smartstore)
        if (
            smartstore_map.get("binaryData")
            or set(smartstore_data)
            != {"indexes.conf", "server.conf", "conftoken"}
            or smartstore_data.get("indexes.conf")
            != reviewed_smartstore_data["indexes.conf"]
            or smartstore_data.get("server.conf")
            != reviewed_smartstore_data["server.conf"]
            or not re.fullmatch(r"[1-9][0-9]*", smartstore_data.get("conftoken", ""))
            or not smartstore_map.get("metadata", {}).get("resourceVersion")
        ):
            raise SystemExit(f"ERROR: StatefulSet/{name} SmartStore data differs")
        smartstore_revision = spec.get("template", {}).get("metadata", {}).get(
            "annotations", {}
        ).get("SmartStoreConfigRev")
        if role == "standalone":
            if smartstore_revision != smartstore_map.get("metadata", {}).get(
                "resourceVersion"
            ):
                raise SystemExit(
                    f"ERROR: StatefulSet/{name} SmartStore adoption differs"
                )
        elif smartstore_revision is not None:
            raise SystemExit(
                f"ERROR: StatefulSet/{name} has an unreviewed SmartStore revision"
            )
        if role == "cluster-manager" and reviewed_cr.get("status", {}).get(
            "bundlePushInfo", {}
        ).get("needToPushManagerApps") is not False:
            raise SystemExit(
                f"ERROR: StatefulSet/{name} SmartStore manager bundle is pending"
            )
    if expects_app_staging and volumes_by_name["operator-staging"] != {
        "name": "operator-staging",
        "emptyDir": {},
    }:
        raise SystemExit(f"ERROR: StatefulSet/{name} App Framework volume differs")
    probe_defaults = {
        "livenessProbe": {
            "initialDelaySeconds": reviewed_spec.get(
                "livenessInitialDelaySeconds", 30
            ) or 30,
            "timeoutSeconds": 30,
            "periodSeconds": 30,
            "failureThreshold": 3,
        },
        "readinessProbe": {
            "initialDelaySeconds": reviewed_spec.get(
                "readinessInitialDelaySeconds", 10
            ) or 10,
            "timeoutSeconds": 5,
            "periodSeconds": 5,
            "failureThreshold": 3,
        },
        "startupProbe": {
            "initialDelaySeconds": 40,
            "timeoutSeconds": 30,
            "periodSeconds": 30,
            "failureThreshold": 12,
        },
    }
    if any(
        reviewed_spec.get(field)
        for field in ("livenessProbe", "readinessProbe", "startupProbe")
    ):
        raise SystemExit(f"ERROR: StatefulSet/{name} has a custom probe contract")
    for probe_name, script_name in (
        ("livenessProbe", "livenessProbe.sh"),
        ("readinessProbe", "readinessProbe.sh"),
        ("startupProbe", "startupProbe.sh"),
    ):
        probe = main_containers[0].get(probe_name, {})
        if (
            probe.get("exec", {}).get("command") != [f"/mnt/probes/{script_name}"]
            or probe.get("initialDelaySeconds", 0) < 0
            or probe.get("timeoutSeconds", 0) < 1
            or probe.get("periodSeconds", 0) < 1
            or probe.get("failureThreshold", 0) < 1
            or any(key in probe for key in ("httpGet", "tcpSocket", "grpc"))
            or probe.get("successThreshold", 1) != 1
            or probe.get("terminationGracePeriodSeconds") is not None
            or (
                probe_hashes
                and any(
                    probe.get(field) != value
                    for field, value in probe_defaults[probe_name].items()
                )
            )
        ):
            raise SystemExit(f"ERROR: StatefulSet/{name} {probe_name} differs")
    if (
        spec.get("replicas") != count
        or status.get("observedGeneration") != item.get("metadata", {}).get("generation")
        or status.get("currentReplicas", 0) != count
        or status.get("updatedReplicas", 0) != count
        or status.get("readyReplicas", 0) != count
        or status.get("availableReplicas", 0) != count
        or not status.get("currentRevision")
        or status.get("currentRevision") != status.get("updateRevision")
    ):
        raise SystemExit(f"ERROR: StatefulSet/{name} rollout is incomplete or stale")
"""
    pod_health_code = """import json
import re
import sys

expected = json.loads(sys.argv[1])
target_image = sys.argv[2]
irsa = json.loads(sys.argv[3])
statefulsets = json.loads(sys.stdin.readline()).get("items", [])
items = json.loads(sys.stdin.readline()).get("items", [])
service_account = json.loads(sys.stdin.read() or "{}")
by_name = {item.get("metadata", {}).get("name", ""): item for item in items}
stateful_by_name = {
    item.get("metadata", {}).get("name", ""): item for item in statefulsets
}
if irsa:
    sa_metadata = service_account.get("metadata", {})
    sa_annotations = sa_metadata.get("annotations", {})
    if (
        service_account.get("apiVersion") != "v1"
        or service_account.get("kind") != "ServiceAccount"
        or sa_metadata.get("name") != irsa["service_account"]
        or sa_metadata.get("namespace") != irsa["namespace"]
        or not sa_metadata.get("uid")
        or sa_metadata.get("deletionTimestamp")
        or sa_annotations.get("eks.amazonaws.com/role-arn") != irsa["role_arn"]
        or sa_annotations.get("eks.amazonaws.com/token-expiration")
        != str(irsa["token_expiration"])
        or sa_annotations.get("eks.amazonaws.com/audience")
        not in (None, "sts.amazonaws.com")
        or sa_annotations.get("eks.amazonaws.com/sts-regional-endpoints") != "true"
    ):
        raise SystemExit("ERROR: reviewed AWS IRSA ServiceAccount contract differs")
elif service_account:
    raise SystemExit("ERROR: unreviewed AWS IRSA ServiceAccount input")
expected_names = {
    f"{contract['prefix']}{ordinal}"
    for contract in expected
    for ordinal in range(int(contract["count"]))
}
role_name = re.compile(
    r"^splunk-.+-(?:standalone|cluster-manager|indexer|search-head|deployer|"
    r"license-manager|monitoring-console|ingestor)-[0-9]+$"
)
live_role_names = {name for name in by_name if role_name.fullmatch(name)}
if live_role_names != expected_names:
    raise SystemExit(
        f"ERROR: Splunk pod inventory differs: live={sorted(live_role_names)}, "
        f"reviewed={sorted(expected_names)}"
    )
for contract in expected:
    prefix = contract["prefix"]
    matches = sorted(
        [
            item
            for name, item in by_name.items()
            if re.fullmatch(re.escape(prefix) + r"[0-9]+", name)
        ],
        key=lambda item: item.get("metadata", {}).get("name", ""),
    )
    if len(matches) != int(contract["count"]):
        names = [item.get("metadata", {}).get("name") for item in matches]
        raise SystemExit(
            f"ERROR: expected {contract['count']} reviewed pods with prefix "
            f"{prefix!r}, found {names}"
        )
    for item in matches:
        name = item.get("metadata", {}).get("name", "unknown")
        status = item.get("status", {})
        expected_owner = prefix.rstrip("-")
        expected_owner_uid = stateful_by_name.get(expected_owner, {}).get(
            "metadata", {}
        ).get("uid")
        owners = item.get("metadata", {}).get("ownerReferences", [])
        controller_owners = [owner for owner in owners if owner.get("controller") is True]
        if (
            len(controller_owners) != 1
            or controller_owners[0].get("kind") != "StatefulSet"
            or controller_owners[0].get("name") != expected_owner
            or not item.get("metadata", {}).get("uid")
            or not expected_owner_uid
            or controller_owners[0].get("uid") != expected_owner_uid
        ):
            raise SystemExit(f"ERROR: reviewed Splunk pod has an invalid owner: {name}")
        ready = any(
            condition.get("type") == "Ready" and condition.get("status") == "True"
            for condition in status.get("conditions", [])
        )
        containers = status.get("containerStatuses", [])
        pod_spec = item.get("spec", {})
        spec_containers = pod_spec.get("containers", [])
        spec_main = [
            container for container in spec_containers
            if container.get("name") == "splunk"
        ]
        target_statuses = [
            container for container in containers
            if container.get("name") == "splunk"
        ]
        if status.get("phase") != "Running" or not ready or not containers or not all(
            container.get("ready") for container in containers
        ):
            raise SystemExit(f"ERROR: reviewed Splunk pod is not Ready: {name}")
        if (
            len(spec_containers) != 1
            or len(spec_main) != 1
            or pod_spec.get("ephemeralContainers")
            or spec_main[0].get("image") != target_image
            or len(target_statuses) != 1
            or not target_statuses[0].get("ready")
        ):
            raise SystemExit(
                f"ERROR: reviewed Splunk pod has not adopted target image: {name}"
            )
        if any(
            pod_spec.get(field) is True
            for field in ("hostNetwork", "hostPID", "hostIPC", "shareProcessNamespace")
        ) or any("hostPath" in volume for volume in pod_spec.get("volumes", [])):
            raise SystemExit(f"ERROR: reviewed Splunk pod has an unsafe pod/volume mode: {name}")
        pod_security = pod_spec.get("securityContext", {})
        if (
            pod_security.get("runAsNonRoot") is False
            or pod_security.get("runAsUser") == 0
            or pod_security.get("runAsGroup") == 0
            or pod_security.get("fsGroup") == 0
            or pod_security.get("sysctls")
            or pod_security.get("seccompProfile", {}).get("type") == "Unconfined"
            or pod_security.get("appArmorProfile", {}).get("type") == "Unconfined"
        ):
            raise SystemExit(f"ERROR: reviewed Splunk pod has unsafe pod security: {name}")
        security = spec_main[0].get("securityContext", {})
        if (
            security.get("privileged") is True
            or security.get("allowPrivilegeEscalation") is True
            or security.get("runAsNonRoot") is False
            or security.get("runAsUser") == 0
            or security.get("runAsGroup") == 0
            or security.get("procMount") == "Unmasked"
            or set(security.get("capabilities", {}).get("add", []))
            - {"NET_BIND_SERVICE"}
            or security.get("seccompProfile", {}).get("type") == "Unconfined"
            or security.get("appArmorProfile", {}).get("type") == "Unconfined"
            or any(
                port.get("hostPort") not in (None, 0)
                for port in spec_main[0].get("ports", [])
            )
        ):
            raise SystemExit(f"ERROR: reviewed Splunk pod has an unsafe container: {name}")
        stateful_template = stateful_by_name[expected_owner].get("spec", {}).get(
            "template", {}
        ).get("spec", {})
        template_main = [
            container for container in stateful_template.get("containers", [])
            if container.get("name") == "splunk"
        ]
        if len(template_main) != 1:
            raise SystemExit(f"ERROR: StatefulSet template is invalid for pod {name}")

        actual_volumes = pod_spec.get("volumes", [])
        template_volumes = stateful_template.get("volumes", [])
        actual_volume_by_name = {
            volume.get("name"): volume for volume in actual_volumes
        }
        template_volume_by_name = {
            volume.get("name"): volume for volume in template_volumes
        }
        if (
            len(actual_volume_by_name) != len(actual_volumes)
            or len(template_volume_by_name) != len(template_volumes)
        ):
            raise SystemExit(f"ERROR: reviewed Splunk pod {name} has ambiguous volumes")
        for volume_name, reviewed_volume in template_volume_by_name.items():
            if actual_volume_by_name.get(volume_name) != reviewed_volume:
                raise SystemExit(
                    f"ERROR: reviewed Splunk pod {name} volume source differs from "
                    "its StatefulSet"
                )
        ordinal_match = re.fullmatch(re.escape(expected_owner) + r"-([0-9]+)", name)
        if ordinal_match is None:
            raise SystemExit(f"ERROR: reviewed Splunk pod ordinal is invalid: {name}")
        ordinal = ordinal_match.group(1)
        for claim_name in ("pvc-etc", "pvc-var"):
            claim_volume = actual_volume_by_name.get(claim_name, {})
            claim_source = claim_volume.get("persistentVolumeClaim", {})
            if (
                set(claim_volume) != {"name", "persistentVolumeClaim"}
                or set(claim_source) - {"claimName", "readOnly"}
                or claim_source.get("claimName")
                != f"{claim_name}-{expected_owner}-{ordinal}"
                or claim_source.get("readOnly", False) is not False
            ):
                raise SystemExit(
                    f"ERROR: reviewed Splunk pod {name} PVC volume differs"
                )

        kube_api_volumes = [
            volume for volume in actual_volumes
            if str(volume.get("name", "")).startswith("kube-api-access-")
        ]
        if len(kube_api_volumes) > 1:
            raise SystemExit(
                f"ERROR: reviewed Splunk pod {name} has ambiguous API token volumes"
            )
        kube_api_volume = kube_api_volumes[0] if len(kube_api_volumes) == 1 else {}
        kube_api_name = kube_api_volume.get("name", "")
        kube_projected = kube_api_volume.get("projected", {})
        kube_sources = kube_projected.get("sources", [])
        source_by_kind = {
            next(iter(source)): source[next(iter(source))]
            for source in kube_sources
            if isinstance(source, dict) and len(source) == 1
        }
        token_source = source_by_kind.get("serviceAccountToken", {})
        root_ca_source = source_by_kind.get("configMap", {})
        namespace_source = source_by_kind.get("downwardAPI", {})
        root_ca_items = root_ca_source.get("items", [])
        namespace_items = namespace_source.get("items", [])
        namespace_field = (
            namespace_items[0].get("fieldRef", {})
            if len(namespace_items) == 1 and isinstance(namespace_items[0], dict)
            else {}
        )
        if kube_api_volume and (
            set(kube_api_volume) != {"name", "projected"}
            or set(kube_projected) - {"defaultMode", "sources"}
            or kube_projected.get("defaultMode", 420) != 420
            or len(kube_sources) != 3
            or set(source_by_kind)
            != {"serviceAccountToken", "configMap", "downwardAPI"}
            or set(token_source) - {"audience", "expirationSeconds", "path"}
            or token_source.get("path") != "token"
            or not isinstance(token_source.get("expirationSeconds"), int)
            or isinstance(token_source.get("expirationSeconds"), bool)
            or not 600 <= token_source["expirationSeconds"] <= 2**32
            or set(root_ca_source) - {"items", "name", "optional"}
            or root_ca_source.get("name") != "kube-root-ca.crt"
            or root_ca_source.get("optional", False) is not False
            or root_ca_items != [{"key": "ca.crt", "path": "ca.crt"}]
            or set(namespace_source) != {"items"}
            or len(namespace_items) != 1
            or set(namespace_items[0]) != {"fieldRef", "path"}
            or namespace_items[0].get("path") != "namespace"
            or set(namespace_field) - {"apiVersion", "fieldPath"}
            or namespace_field.get("apiVersion", "v1") != "v1"
            or namespace_field.get("fieldPath") != "metadata.namespace"
        ):
            raise SystemExit(
                f"ERROR: reviewed Splunk pod {name} Kubernetes API token volume differs"
            )

        expected_irsa = bool(irsa) and (
            expected_owner.endswith("-standalone")
            or expected_owner.endswith("-indexer")
        )
        actual_irsa = (
            pod_spec.get("serviceAccountName", "default")
            == irsa.get("service_account")
            if irsa
            else False
        )
        template_irsa = (
            stateful_template.get("serviceAccountName", "default")
            == irsa.get("service_account")
            if irsa
            else False
        )
        if actual_irsa != expected_irsa or template_irsa != expected_irsa:
            raise SystemExit(f"ERROR: reviewed Splunk pod {name} IRSA role scope differs")

        irsa_volumes = [
            volume for volume in pod_spec.get("volumes", [])
            if volume.get("name") == "aws-iam-token"
        ]
        if expected_irsa:
            irsa_volume = irsa_volumes[0] if len(irsa_volumes) == 1 else {}
            projected = irsa_volume.get("projected", {})
            sources = projected.get("sources", [])
            token = (
                sources[0].get("serviceAccountToken", {})
                if len(sources) == 1 and isinstance(sources[0], dict)
                else {}
            )
            if (
                set(irsa_volume) != {"name", "projected"}
                or set(projected) - {"defaultMode", "sources"}
                or projected.get("defaultMode", 420) != 420
                or len(sources) != 1
                or set(sources[0]) != {"serviceAccountToken"}
                or set(token) != {"audience", "expirationSeconds", "path"}
                or token.get("audience") != "sts.amazonaws.com"
                or token.get("expirationSeconds") != irsa["token_expiration"]
                or token.get("path") != "token"
            ):
                raise SystemExit(f"ERROR: reviewed Splunk pod {name} IRSA token volume differs")
        elif irsa_volumes:
            raise SystemExit(f"ERROR: reviewed Splunk pod {name} has unreviewed IRSA volume")
        expected_actual_volume_names = {
            *template_volume_by_name,
            "pvc-etc",
            "pvc-var",
        }
        if kube_api_name:
            expected_actual_volume_names.add(kube_api_name)
        if expected_irsa:
            expected_actual_volume_names.add("aws-iam-token")
        if set(actual_volume_by_name) != expected_actual_volume_names:
            raise SystemExit(
                f"ERROR: reviewed Splunk pod {name} volume inventory differs"
            )

        def workload_mounts(container, expect_irsa, live_container):
            kube_mounts = [
                mount for mount in container.get("volumeMounts", [])
                if str(mount.get("name", "")).startswith("kube-api-access-")
                or mount.get("mountPath")
                == "/var/run/secrets/kubernetes.io/serviceaccount"
            ]
            if live_container:
                expected_kube_mounts = (
                    [{
                        "name": kube_api_name,
                        "readOnly": True,
                        "mountPath": "/var/run/secrets/kubernetes.io/serviceaccount",
                    }]
                    if kube_api_name
                    else []
                )
                if kube_mounts != expected_kube_mounts:
                    raise SystemExit(
                        f"ERROR: reviewed Splunk pod {name} Kubernetes API mount differs"
                    )
            elif kube_mounts:
                raise SystemExit(
                    f"ERROR: StatefulSet template for {name} has an unreviewed API mount"
                )
            irsa_mounts = [
                mount for mount in container.get("volumeMounts", [])
                if mount.get("name") == "aws-iam-token"
                or mount.get("mountPath")
                == "/var/run/secrets/eks.amazonaws.com/serviceaccount"
            ]
            if expect_irsa:
                if irsa_mounts != [{
                    "name": "aws-iam-token",
                    "readOnly": True,
                    "mountPath": "/var/run/secrets/eks.amazonaws.com/serviceaccount",
                }]:
                    raise SystemExit(
                        f"ERROR: reviewed Splunk pod {name} IRSA token mount differs"
                    )
            elif irsa_mounts:
                raise SystemExit(
                    f"ERROR: reviewed Splunk pod {name} has an unreviewed IRSA mount"
                )
            return sorted(
                [
                    mount for mount in container.get("volumeMounts", [])
                    if not (
                        str(mount.get("name", "")).startswith("kube-api-access-")
                        and mount.get("mountPath")
                        == "/var/run/secrets/kubernetes.io/serviceaccount"
                    )
                    and mount not in irsa_mounts
                ],
                key=lambda mount: (
                    str(mount.get("name", "")),
                    str(mount.get("mountPath", "")),
                ),
            )

        def normalized_container(container, expect_irsa):
            normalized = {
                key: value
                for key, value in container.items()
                if key != "volumeMounts"
            }
            env = normalized.get("env", [])
            irsa_names = {
                "AWS_DEFAULT_REGION",
                "AWS_REGION",
                "AWS_ROLE_ARN",
                "AWS_STS_REGIONAL_ENDPOINTS",
                "AWS_WEB_IDENTITY_TOKEN_FILE",
            }
            injected = [entry for entry in env if entry.get("name") in irsa_names]
            if expect_irsa:
                if (
                    len({entry.get("name") for entry in injected}) != len(injected)
                    or any(set(entry) != {"name", "value"} for entry in injected)
                ):
                    raise SystemExit(
                        f"ERROR: reviewed Splunk pod {name} IRSA environment is ambiguous"
                    )
                injected_values = {
                    entry.get("name"): entry.get("value") for entry in injected
                }
                mandatory = {
                    "AWS_ROLE_ARN": irsa["role_arn"],
                    "AWS_STS_REGIONAL_ENDPOINTS": "regional",
                    "AWS_WEB_IDENTITY_TOKEN_FILE": (
                        "/var/run/secrets/eks.amazonaws.com/serviceaccount/token"
                    ),
                }
                if any(injected_values.get(key) != value for key, value in mandatory.items()):
                    raise SystemExit(
                        f"ERROR: reviewed Splunk pod {name} IRSA environment differs"
                    )
                region_values = {
                    key: injected_values[key]
                    for key in ("AWS_DEFAULT_REGION", "AWS_REGION")
                    if key in injected_values
                }
                if region_values not in (
                    {},
                    {
                        "AWS_DEFAULT_REGION": irsa["region"],
                        "AWS_REGION": irsa["region"],
                    },
                ) or set(injected_values) - set(mandatory) - set(region_values):
                    raise SystemExit(
                        f"ERROR: reviewed Splunk pod {name} IRSA region environment differs"
                    )
            elif injected:
                raise SystemExit(
                    f"ERROR: reviewed Splunk pod {name} has unreviewed AWS identity environment"
                )
            if injected:
                normalized["env"] = [
                    entry for entry in env if entry.get("name") not in irsa_names
                ]
            normalized.setdefault("imagePullPolicy", "IfNotPresent")
            normalized.setdefault("terminationMessagePath", "/dev/termination-log")
            normalized.setdefault("terminationMessagePolicy", "File")
            return normalized

        if normalized_container(spec_main[0], expected_irsa) != normalized_container(
            template_main[0], False
        ):
            raise SystemExit(
                f"ERROR: reviewed Splunk pod {name} differs from its StatefulSet "
                "container contract"
            )
        if workload_mounts(spec_main[0], expected_irsa, True) != workload_mounts(
            template_main[0], False, False
        ):
            raise SystemExit(
                f"ERROR: reviewed Splunk pod {name} volume mounts differ from its StatefulSet"
            )
        spec_init = pod_spec.get("initContainers", [])
        template_init = stateful_template.get("initContainers", [])
        if len(spec_init) != len(template_init) or any(
            normalized_container(actual, expected_irsa)
            != normalized_container(reviewed, False)
            or workload_mounts(actual, expected_irsa, True)
            != workload_mounts(reviewed, False, False)
            for actual, reviewed in zip(spec_init, template_init)
        ):
            raise SystemExit(
                f"ERROR: reviewed Splunk pod {name} init contract differs from "
                "its StatefulSet"
            )
        init_statuses = status.get("initContainerStatuses", [])
        init_status_by_name = {
            init_status.get("name"): init_status for init_status in init_statuses
        }
        if len(init_status_by_name) != len(init_statuses) or set(
            init_status_by_name
        ) != {init.get("name") for init in spec_init}:
            raise SystemExit(f"ERROR: reviewed Splunk pod init status differs: {name}")
        for init in spec_init:
            init_status = init_status_by_name[init.get("name")]
            terminated = init_status.get("state", {}).get("terminated", {})
            if (
                init.get("image") != target_image
                or terminated.get("exitCode") != 0
            ):
                raise SystemExit(
                    f"ERROR: reviewed Splunk pod init did not complete safely: {name}"
                )
        for field in (
            "serviceAccountName", "securityContext", "nodeSelector", "affinity",
            "topologySpreadConstraints", "priorityClassName", "runtimeClassName",
            "imagePullSecrets", "restartPolicy", "dnsPolicy", "schedulerName",
            "terminationGracePeriodSeconds", "automountServiceAccountToken",
            "enableServiceLinks", "hostUsers",
        ):
            defaults = {
                "automountServiceAccountToken": True,
                "dnsPolicy": "ClusterFirst",
                "enableServiceLinks": True,
                "hostUsers": True,
                "restartPolicy": "Always",
                "schedulerName": "default-scheduler",
                "terminationGracePeriodSeconds": 30,
            }
            if pod_spec.get(field, defaults.get(field)) != stateful_template.get(
                field, defaults.get(field)
            ):
                raise SystemExit(
                    f"ERROR: reviewed Splunk pod {name} differs from its StatefulSet "
                    f"pod contract at {field}"
                )
        if "@sha256:" in target_image:
            digest = target_image.split("@", 1)[1]
            if digest not in target_statuses[0].get("imageID", ""):
                raise SystemExit(
                    f"ERROR: reviewed Splunk pod imageID does not match target digest: {name}"
                )
            if any(
                digest not in init_status.get("imageID", "")
                for init_status in init_statuses
            ):
                raise SystemExit(
                    f"ERROR: reviewed Splunk init imageID does not match target digest: {name}"
                )
"""
    service_health_code = """import ipaddress
import json
import re
import sys

expected = json.loads(sys.argv[1])
namespace = sys.argv[2]
statefulsets = json.loads(sys.stdin.readline()).get("items", [])
services = json.loads(sys.stdin.readline()).get("items", [])
slices = json.loads(sys.stdin.readline()).get("items", [])
pods = json.loads(sys.stdin.read()).get("items", [])
stateful_by_name = {
    item.get("metadata", {}).get("name", ""): item for item in statefulsets
}
service_by_name = {
    item.get("metadata", {}).get("name", ""): item for item in services
}
pod_by_name = {item.get("metadata", {}).get("name", ""): item for item in pods}
contracts_by_name = {contract["name"]: contract for contract in expected}
expected_stateful = {name: int(contract["count"]) for name, contract in contracts_by_name.items()}
role_pattern = re.compile(
    r"^splunk-.+-(standalone|cluster-manager|indexer|search-head|deployer|"
    r"license-manager|monitoring-console|ingestor)$"
)
def service_suffixes(stateful_name):
    match = role_pattern.fullmatch(stateful_name)
    if match is None:
        raise SystemExit(f"ERROR: unknown Splunk StatefulSet role: {stateful_name}")
    if match.group(1) in {"cluster-manager", "license-manager", "deployer"}:
        return ("service",)
    return ("headless", "service")

expected_services = {
    f"{name}-{suffix}"
    for name in expected_stateful
    for suffix in service_suffixes(name)
}
live_role_services = {
    name
    for name in service_by_name
    if re.fullmatch(
        r"splunk-.+-(?:standalone|cluster-manager|indexer|search-head|deployer|"
        r"license-manager|monitoring-console|ingestor)-(?:headless|service)",
        name,
    )
}
if live_role_services != expected_services:
    raise SystemExit(
        f"ERROR: Splunk Service inventory differs: live={sorted(live_role_services)}, "
        f"reviewed={sorted(expected_services)}"
    )

for stateful_name, count in expected_stateful.items():
    contract = contracts_by_name[stateful_name]
    stateful = stateful_by_name.get(stateful_name)
    if stateful is None:
        raise SystemExit(f"ERROR: StatefulSet is missing for Service validation: {stateful_name}")
    match = role_pattern.fullmatch(stateful_name)
    if match is None:
        raise SystemExit(f"ERROR: unknown Splunk StatefulSet role: {stateful_name}")
    role = match.group(1)
    stateful_owners = [
        owner for owner in stateful.get("metadata", {}).get("ownerReferences", [])
        if owner.get("controller") is True
    ]
    if (
        not stateful.get("metadata", {}).get("uid")
        or len(stateful_owners) != 1
        or stateful_owners[0].get("apiVersion") != "enterprise.splunk.com/v4"
        or stateful_owners[0].get("kind") != contract["owner_kind"]
        or stateful_owners[0].get("name") != contract["owner_name"]
        or not stateful_owners[0].get("uid")
    ):
        raise SystemExit(
            f"ERROR: StatefulSet/{stateful_name} owner identity differs"
        )
    required_ports = {
        "http-splunkweb": (8000, 8000, "TCP"),
        "https-splunkd": (8089, 8089, "TCP"),
    }
    if role in {"standalone", "indexer", "monitoring-console", "ingestor"}:
        required_ports.update(
            {
                "http-hec": (8088, 8088, "TCP"),
                "tcp-s2s": (9997, 9997, "TCP"),
            }
        )
    headless_name = f"{stateful_name}-headless"
    stateful_selector = stateful.get("spec", {}).get("selector", {}).get(
        "matchLabels", {}
    )
    if not stateful_selector:
        raise SystemExit(
            f"ERROR: StatefulSet/{stateful_name} has no exact service selector contract"
        )
    if stateful.get("spec", {}).get("serviceName") != headless_name:
        raise SystemExit(
            f"ERROR: StatefulSet/{stateful_name} serviceName does not match {headless_name}"
        )
    for suffix in service_suffixes(stateful_name):
        service_name = f"{stateful_name}-{suffix}"
        service = service_by_name.get(service_name)
        if service is None:
            raise SystemExit(f"ERROR: reviewed Splunk Service is missing: {service_name}")
        metadata = service.get("metadata", {})
        spec = service.get("spec", {})
        owners = [
            owner
            for owner in metadata.get("ownerReferences", [])
            if owner.get("controller") is True
        ]
        if (
            metadata.get("namespace") != namespace
            or metadata.get("deletionTimestamp")
            or len(owners) != 1
            or owners[0].get("apiVersion") != "enterprise.splunk.com/v4"
            or owners[0].get("kind") != contract["owner_kind"]
            or owners[0].get("name") != contract["owner_name"]
            or owners[0].get("uid") != stateful_owners[0].get("uid")
            or not metadata.get("uid")
            or spec.get("type", "ClusterIP") != "ClusterIP"
            or spec.get("externalIPs")
            or spec.get("loadBalancerIP")
            or spec.get("externalName")
            or spec.get("externalTrafficPolicy") not in (None, "Cluster")
            or spec.get("internalTrafficPolicy", "Cluster") != "Cluster"
            or spec.get("sessionAffinity", "None") != "None"
            or spec.get("sessionAffinityConfig")
            or spec.get("trafficDistribution")
            or spec.get("topologyKeys")
            or spec.get("loadBalancerClass")
            or spec.get("loadBalancerSourceRanges")
            or spec.get("selector") != stateful_selector
        ):
            raise SystemExit(f"ERROR: Splunk Service identity/exposure differs: {service_name}")
        if suffix == "headless" and spec.get("clusterIP") != "None":
            raise SystemExit(f"ERROR: headless Service is not headless: {service_name}")
        expected_publish_not_ready = (
            (role == "search-head" and suffix == "headless")
            or role == "deployer"
        )
        if spec.get("publishNotReadyAddresses", False) is not expected_publish_not_ready:
            raise SystemExit(
                f"ERROR: Service bootstrap readiness policy differs: {service_name}"
            )
        actual_ports = {
            port.get("name"): (
                port.get("port"), port.get("targetPort"), port.get("protocol", "TCP")
            )
            for port in spec.get("ports", [])
        }
        if len(actual_ports) != len(spec.get("ports", [])) or actual_ports != required_ports:
            raise SystemExit(
                f"ERROR: Splunk Service ports differ for {service_name}: {actual_ports}"
            )
        matching_slices = [
            item
            for item in slices
            if item.get("metadata", {}).get("labels", {}).get(
                "kubernetes.io/service-name"
            ) == service_name
            and not item.get("metadata", {}).get("deletionTimestamp")
        ]
        if not matching_slices:
            raise SystemExit(f"ERROR: Service has no EndpointSlice: {service_name}")
        endpoint_pods = set()
        seen_endpoint_targets = set()
        seen_endpoint_addresses = set()
        reviewed_service_pods = {
            f"{stateful_name}-{ordinal}" for ordinal in range(count)
        }
        for endpoint_slice in matching_slices:
            slice_metadata = endpoint_slice.get("metadata", {})
            slice_labels = slice_metadata.get("labels", {})
            slice_owners = [
                owner for owner in slice_metadata.get("ownerReferences", [])
                if owner.get("controller") is True
            ]
            address_type = endpoint_slice.get("addressType")
            if (
                endpoint_slice.get("apiVersion") != "discovery.k8s.io/v1"
                or endpoint_slice.get("kind") != "EndpointSlice"
                or slice_metadata.get("namespace") != namespace
                or not slice_metadata.get("uid")
                or slice_labels.get("endpointslice.kubernetes.io/managed-by")
                != "endpointslice-controller.k8s.io"
                or len(slice_owners) != 1
                or slice_owners[0].get("apiVersion") != "v1"
                or slice_owners[0].get("kind") != "Service"
                or slice_owners[0].get("name") != service_name
                or slice_owners[0].get("uid") != metadata.get("uid")
                or address_type not in {"IPv4", "IPv6"}
            ):
                raise SystemExit(
                    f"ERROR: EndpointSlice provenance differs for {service_name}"
                )
            slice_ports = {
                port.get("name"): (port.get("port"), port.get("protocol", "TCP"))
                for port in endpoint_slice.get("ports", [])
            }
            expected_slice_ports = {
                name: (values[0], values[2]) for name, values in required_ports.items()
            }
            if (
                len(slice_ports) != len(endpoint_slice.get("ports", []))
                or slice_ports != expected_slice_ports
            ):
                raise SystemExit(
                    f"ERROR: EndpointSlice ports differ for {service_name}: {slice_ports}"
                )
            for endpoint in endpoint_slice.get("endpoints", []):
                target = endpoint.get("targetRef", {})
                pod_name = target.get("name")
                conditions = endpoint.get("conditions", {})
                pod = pod_by_name.get(pod_name, {})
                pod_metadata = pod.get("metadata", {})
                pod_owner = [
                    owner for owner in pod_metadata.get("ownerReferences", [])
                    if owner.get("controller") is True
                ]
                if (
                    conditions.get("ready") is not True
                    or conditions.get("terminating") is True
                    or target.get("apiVersion") not in (None, "v1")
                    or target.get("kind") != "Pod"
                    or target.get("namespace") != namespace
                    or pod_name not in reviewed_service_pods
                    or not pod_metadata.get("uid")
                    or target.get("uid") != pod_metadata.get("uid")
                    or len(pod_owner) != 1
                    or pod_owner[0].get("apiVersion") != "apps/v1"
                    or pod_owner[0].get("kind") != "StatefulSet"
                    or pod_owner[0].get("name") != stateful_name
                    or pod_owner[0].get("uid")
                    != stateful.get("metadata", {}).get("uid")
                    or not endpoint.get("addresses")
                ):
                    raise SystemExit(
                        f"ERROR: unready or unexpected endpoint for {service_name}: {endpoint!r}"
                    )
                pod_labels = pod_metadata.get("labels", {})
                if any(
                    pod_labels.get(key) != value
                    for key, value in spec.get("selector", {}).items()
                ):
                    raise SystemExit(
                        f"ERROR: Service selector does not match endpoint pod {pod_name}"
                    )
                pod_ips = {
                    entry.get("ip")
                    for entry in pod.get("status", {}).get("podIPs", [])
                    if entry.get("ip")
                }
                primary_ip = pod.get("status", {}).get("podIP")
                if primary_ip:
                    pod_ips.add(primary_ip)
                family_ips = set()
                for address in pod_ips:
                    try:
                        parsed_address = ipaddress.ip_address(address)
                    except ValueError:
                        raise SystemExit(
                            f"ERROR: pod {pod_name} has an invalid status IP {address!r}"
                        )
                    if (address_type == "IPv4" and parsed_address.version == 4) or (
                        address_type == "IPv6" and parsed_address.version == 6
                    ):
                        family_ips.add(address)
                endpoint_addresses = set(endpoint.get("addresses", []))
                endpoint_key = (address_type, pod_name)
                address_keys = {(address_type, address) for address in endpoint_addresses}
                if (
                    not family_ips
                    or endpoint_addresses != family_ips
                    or endpoint_key in seen_endpoint_targets
                    or seen_endpoint_addresses.intersection(address_keys)
                ):
                    raise SystemExit(
                        f"ERROR: EndpointSlice address identity differs for {service_name}/"
                        f"{pod_name}: live={sorted(endpoint_addresses)}, "
                        f"pod={sorted(family_ips)}"
                    )
                seen_endpoint_targets.add(endpoint_key)
                seen_endpoint_addresses.update(address_keys)
                endpoint_pods.add(pod_name)
        if endpoint_pods != reviewed_service_pods:
            raise SystemExit(
                f"ERROR: Service {service_name} endpoint inventory differs: "
                f"live={sorted(endpoint_pods)}, reviewed={sorted(reviewed_service_pods)}"
            )
"""
    pvc_health_code = """import json
import re
import sys

expected = json.loads(sys.argv[1])
namespace, expected_etc, expected_var, expected_class = sys.argv[2:]
statefulsets = json.loads(sys.stdin.readline()).get("items", [])
pvcs = json.loads(sys.stdin.readline()).get("items", [])
pods = json.loads(sys.stdin.read()).get("items", [])
stateful_by_name = {
    item.get("metadata", {}).get("name", ""): item for item in statefulsets
}
pvc_by_name = {item.get("metadata", {}).get("name", ""): item for item in pvcs}
pod_by_name = {item.get("metadata", {}).get("name", ""): item for item in pods}

units = {
    "": 1, "k": 1000, "M": 1000**2, "G": 1000**3,
    "T": 1000**4, "P": 1000**5, "E": 1000**6,
    "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3,
    "Ti": 1024**4, "Pi": 1024**5, "Ei": 1024**6,
}

def storage_bytes(value, label):
    match = re.fullmatch(
        r"([1-9][0-9]*)(Ki|Mi|Gi|Ti|Pi|Ei|k|M|G|T|P|E)?",
        str(value or ""),
    )
    if match is None or (match.group(2) or "") not in units:
        raise SystemExit(f"ERROR: {label} has an unsupported storage quantity {value!r}")
    return int(match.group(1)) * units[match.group(2) or ""]

expected_sizes = {
    "pvc-etc": storage_bytes(expected_etc, "reviewed etc storage"),
    "pvc-var": storage_bytes(expected_var, "reviewed var storage"),
}
expected_pvcs = set()
default_classes = set()
role_pvc_pattern = re.compile(
    r"^pvc-(?:etc|var)-splunk-.+-(?:standalone|cluster-manager|indexer|"
    r"search-head|deployer|license-manager|monitoring-console|ingestor)-[0-9]+$"
)

for contract in expected:
    stateful_name = contract["name"]
    stateful = stateful_by_name.get(stateful_name)
    if stateful is None or not stateful.get("metadata", {}).get("uid"):
        raise SystemExit(f"ERROR: StatefulSet is missing for PVC validation: {stateful_name}")
    templates = stateful.get("spec", {}).get("volumeClaimTemplates", [])
    templates_by_name = {
        item.get("metadata", {}).get("name", ""): item for item in templates
    }
    if set(templates_by_name) != set(expected_sizes) or len(templates_by_name) != len(templates):
        raise SystemExit(
            f"ERROR: StatefulSet/{stateful_name} PVC template inventory differs"
        )
    selector = stateful.get("spec", {}).get("selector", {}).get("matchLabels", {})
    for claim, expected_size in expected_sizes.items():
        template = templates_by_name[claim]
        template_spec = template.get("spec", {})
        template_request = template_spec.get("resources", {}).get("requests", {}).get("storage")
        if (
            storage_bytes(template_request, f"StatefulSet/{stateful_name} {claim}")
            != expected_size
            or set(template_spec.get("accessModes", [])) != {"ReadWriteOnce"}
            or template_spec.get("volumeMode", "Filesystem") != "Filesystem"
            or template_spec.get("selector")
            or template_spec.get("dataSource")
            or template_spec.get("dataSourceRef")
        ):
            raise SystemExit(
                f"ERROR: StatefulSet/{stateful_name} {claim} template differs"
            )
        if expected_class:
            if template_spec.get("storageClassName") != expected_class:
                raise SystemExit(
                    f"ERROR: StatefulSet/{stateful_name} {claim} storage class differs"
                )
        elif template_spec.get("storageClassName") not in (None, ""):
            raise SystemExit(
                f"ERROR: StatefulSet/{stateful_name} has an unreviewed template storage class"
            )
        for ordinal in range(int(contract["count"])):
            pvc_name = f"{claim}-{stateful_name}-{ordinal}"
            expected_pvcs.add(pvc_name)
            pvc = pvc_by_name.get(pvc_name)
            pod = pod_by_name.get(f"{stateful_name}-{ordinal}")
            if pvc is None or pod is None:
                raise SystemExit(f"ERROR: reviewed PVC or pod is missing: {pvc_name}")
            metadata = pvc.get("metadata", {})
            spec = pvc.get("spec", {})
            status = pvc.get("status", {})
            actual_class = spec.get("storageClassName") or ""
            if not expected_class:
                if not actual_class:
                    raise SystemExit(f"ERROR: PVC/{pvc_name} has no resolved StorageClass")
                default_classes.add(actual_class)
            if (
                metadata.get("namespace") != namespace
                or not metadata.get("uid")
                or metadata.get("deletionTimestamp")
                or metadata.get("ownerReferences")
                or (expected_class and actual_class != expected_class)
                or set(spec.get("accessModes", [])) != {"ReadWriteOnce"}
                or spec.get("volumeMode", "Filesystem") != "Filesystem"
                or spec.get("selector")
                or spec.get("dataSource")
                or spec.get("dataSourceRef")
                or storage_bytes(
                    spec.get("resources", {}).get("requests", {}).get("storage"),
                    f"PVC/{pvc_name}",
                ) != expected_size
                or status.get("phase") != "Bound"
                or not spec.get("volumeName")
                or status.get("conditions")
                or storage_bytes(
                    status.get("capacity", {}).get("storage"),
                    f"PVC/{pvc_name} bound capacity",
                ) < expected_size
            ):
                raise SystemExit(f"ERROR: PVC/{pvc_name} storage contract differs")
            pvc_labels = metadata.get("labels", {})
            template_labels = template.get("metadata", {}).get("labels", {})
            if any(pvc_labels.get(key) != value for key, value in selector.items()) or any(
                pvc_labels.get(key) != value for key, value in template_labels.items()
            ):
                raise SystemExit(f"ERROR: PVC/{pvc_name} labels differ from its StatefulSet")
            pod_claims = {
                volume.get("name"): volume.get("persistentVolumeClaim", {}).get("claimName")
                for volume in pod.get("spec", {}).get("volumes", [])
                if "persistentVolumeClaim" in volume
            }
            if pod_claims.get(claim) != pvc_name:
                raise SystemExit(f"ERROR: pod does not mount reviewed PVC/{pvc_name}")

live_role_pvcs = {name for name in pvc_by_name if role_pvc_pattern.fullmatch(name)}
if live_role_pvcs != expected_pvcs:
    raise SystemExit(
        f"ERROR: Splunk PVC inventory differs: live={sorted(live_role_pvcs)}, "
        f"reviewed={sorted(expected_pvcs)}"
    )
if not expected_class and len(default_classes) != 1:
    raise SystemExit(
        f"ERROR: reviewed PVCs do not resolve to one default StorageClass: "
        f"{sorted(default_classes)}"
    )
"""
    placement_health_code = """import json
import sys

contracts = json.loads(sys.argv[1])
enforce_distinct = sys.argv[2] == "true"
pods = json.loads(sys.stdin.readline()).get("items", [])
nodes = json.loads(sys.stdin.read()).get("items", [])
pods_by_name = {
    item.get("metadata", {}).get("name", ""): item for item in pods
}
nodes_by_name = {
    item.get("metadata", {}).get("name", ""): item for item in nodes
}
for contract in contracts:
    names = [
        f"{contract['prefix']}{ordinal}"
        for ordinal in range(int(contract["count"]))
    ]
    assigned = []
    for name in names:
        pod = pods_by_name.get(name)
        if pod is None:
            raise SystemExit(f"ERROR: placement pod is missing: {name}")
        node_name = pod.get("spec", {}).get("nodeName")
        node = nodes_by_name.get(node_name)
        if not node_name or node is None:
            raise SystemExit(f"ERROR: pod has no verifiable node placement: {name}")
        expected_zone = contract.get("zone")
        live_zone = node.get("metadata", {}).get("labels", {}).get(
            "topology.kubernetes.io/zone"
        )
        if expected_zone and live_zone != expected_zone:
            raise SystemExit(
                f"ERROR: pod {name} is in zone {live_zone!r}, expected {expected_zone!r}"
            )
        assigned.append(node_name)
    if enforce_distinct and len(names) > 1 and len(set(assigned)) != len(names):
        raise SystemExit(
            f"ERROR: production replicas are co-located for {contract['prefix']}: "
            f"{assigned}"
        )
"""
    helm_status_guard = """import json
import sys
payload = json.load(sys.stdin)
status = payload.get("info", {}).get("status")
if status != "deployed":
    raise SystemExit(
        f"ERROR: Helm release {sys.argv[1]!r} is not deployed (status={status!r})"
    )
"""
    helm_list_guard = """import json
import sys
rows = json.load(sys.stdin)
name, namespace, chart = sys.argv[1:]
matches = [row for row in rows if row.get("name") == name]
if len(matches) != 1:
    raise SystemExit(f"ERROR: expected exactly one Helm release {name!r}")
row = matches[0]
if (
    row.get("namespace") != namespace
    or row.get("chart") != chart
    or row.get("status") != "deployed"
):
    raise SystemExit(
        f"ERROR: Helm release identity/status differs: {row!r}"
    )
"""
    operator_health_code = """import json
import sys

deployment = json.loads(sys.stdin.readline())
pods = json.loads(sys.stdin.readline())
service = json.loads(sys.stdin.readline())
replica_sets = json.loads(sys.stdin.read())
release, release_namespace, image, watched = sys.argv[1:]
metadata = deployment.get("metadata", {})
annotations = metadata.get("annotations", {})
if (
    annotations.get("meta.helm.sh/release-name") != release
    or annotations.get("meta.helm.sh/release-namespace") != release_namespace
    or metadata.get("deletionTimestamp")
    or not metadata.get("uid")
    or metadata.get("ownerReferences")
):
    raise SystemExit("ERROR: Operator Deployment has an unexpected Helm owner")
spec = deployment.get("spec", {})
status = deployment.get("status", {})
replicas = spec.get("replicas", 1)
selector = spec.get("selector", {}).get("matchLabels", {})
if not selector:
    raise SystemExit("ERROR: Operator Deployment has no exact pod selector")
pod_spec = spec.get("template", {}).get("spec", {})
containers = pod_spec.get("containers", [])
manager = [container for container in containers if container.get("name") == "manager"]
if (
    len(containers) != 1
    or len(manager) != 1
    or pod_spec.get("initContainers")
    or manager[0].get("image") != image
):
    raise SystemExit("ERROR: Operator Deployment has not adopted the reviewed image")
if any(pod_spec.get(field) is True for field in ("hostNetwork", "hostPID", "hostIPC", "shareProcessNamespace")):
    raise SystemExit("ERROR: Operator Deployment enables a host/shared namespace")
if any("hostPath" in volume for volume in pod_spec.get("volumes", [])):
    raise SystemExit("ERROR: Operator Deployment mounts a hostPath")
pod_security = pod_spec.get("securityContext", {})
if pod_security.get("runAsNonRoot") is False or pod_security.get("runAsUser") == 0:
    raise SystemExit("ERROR: Operator pod security context permits root")
for container in [*containers, *pod_spec.get("initContainers", [])]:
    security = container.get("securityContext", {})
    if (
        security.get("privileged") is True
        or security.get("allowPrivilegeEscalation") is True
        or security.get("runAsNonRoot") is False
        or security.get("runAsUser") == 0
    ):
        raise SystemExit("ERROR: Operator container security context is unsafe")
watch_values = []
for env in manager[0].get("env", []):
    if env.get("name") == "WATCH_NAMESPACE":
        watch_values.append(env.get("value") or metadata.get("namespace", ""))
if watch_values != [watched]:
    raise SystemExit(
        f"ERROR: Operator WATCH_NAMESPACE differs: live={watch_values}, reviewed={watched!r}"
    )
if (
    status.get("observedGeneration") != metadata.get("generation")
    or status.get("updatedReplicas", 0) != replicas
    or status.get("availableReplicas", 0) != replicas
    or status.get("readyReplicas", 0) != replicas
):
    raise SystemExit("ERROR: Operator Deployment rollout is incomplete or stale")
service_metadata = service.get("metadata", {})
service_annotations = service_metadata.get("annotations", {})
service_spec = service.get("spec", {})
if (
    service.get("apiVersion") != "v1"
    or service.get("kind") != "Service"
    or service_metadata.get("name") != "splunk-operator-controller-manager-service"
    or service_metadata.get("namespace") != release_namespace
    or service_annotations.get("meta.helm.sh/release-name") != release
    or service_annotations.get("meta.helm.sh/release-namespace") != release_namespace
    or service_metadata.get("deletionTimestamp")
    or service_spec.get("type", "ClusterIP") != "ClusterIP"
    or service_spec.get("externalIPs")
    or service_spec.get("loadBalancerIP")
):
    raise SystemExit("ERROR: Operator Service identity/exposure differs from review")
operator_pods = [
    pod for pod in pods.get("items", [])
    if pod.get("metadata", {}).get("name", "").startswith(
        "splunk-operator-controller-manager-"
    )
]
if len(operator_pods) != replicas:
    raise SystemExit("ERROR: Operator pod count differs from reviewed Deployment")
replica_set_by_name = {
    item.get("metadata", {}).get("name", ""): item
    for item in replica_sets.get("items", [])
}
for pod in operator_pods:
    pod_metadata = pod.get("metadata", {})
    pod_owners = [
        owner for owner in pod_metadata.get("ownerReferences", [])
        if owner.get("controller") is True
    ]
    replica_set = (
        replica_set_by_name.get(pod_owners[0].get("name", ""))
        if len(pod_owners) == 1 else None
    )
    replica_set_owners = [
        owner for owner in replica_set.get("metadata", {}).get("ownerReferences", [])
        if owner.get("controller") is True
    ] if replica_set else []
    if (
        pod_metadata.get("deletionTimestamp")
        or not pod_metadata.get("uid")
        or any(pod_metadata.get("labels", {}).get(key) != value for key, value in selector.items())
        or len(pod_owners) != 1
        or pod_owners[0].get("apiVersion") != "apps/v1"
        or pod_owners[0].get("kind") != "ReplicaSet"
        or not replica_set
        or replica_set.get("metadata", {}).get("deletionTimestamp")
        or pod_owners[0].get("uid") != replica_set.get("metadata", {}).get("uid")
        or len(replica_set_owners) != 1
        or replica_set_owners[0].get("apiVersion") != "apps/v1"
        or replica_set_owners[0].get("kind") != "Deployment"
        or replica_set_owners[0].get("name") != metadata.get("name")
        or replica_set_owners[0].get("uid") != metadata.get("uid")
    ):
        raise SystemExit("ERROR: Operator pod controller lineage differs from review")
    pod_spec = pod.get("spec", {})
    pod_manager = [
        container for container in pod_spec.get("containers", [])
        if container.get("name") == "manager"
    ]
    statuses = [
        container for container in pod.get("status", {}).get("containerStatuses", [])
        if container.get("name") == "manager"
    ]
    if (
        len(pod_spec.get("containers", [])) != 1
        or len(pod_manager) != 1
        or pod_spec.get("initContainers")
        or pod_manager[0].get("image") != image
        or len(statuses) != 1 or not statuses[0].get("ready")
    ):
        raise SystemExit("ERROR: Operator pod has not adopted the reviewed image")
    if "@sha256:" in image and image.split("@", 1)[1] not in statuses[0].get("imageID", ""):
        raise SystemExit("ERROR: Operator pod imageID differs from reviewed digest")
"""
    compact_json_code = "import json,sys; json.dump(json.load(sys.stdin), sys.stdout)"
    operator_health_shell = f"""operator_health_input="$(mktemp)"
trap 'rm -f "${{operator_health_input}}"' EXIT
kubectl --request-timeout=30s get deployment splunk-operator-controller-manager --namespace {shell_quote(args.operator_namespace)} -o json | python3 -c {shell_quote(compact_json_code)} >"${{operator_health_input}}"
printf '\\n' >>"${{operator_health_input}}"
kubectl --request-timeout=30s get pods --namespace {shell_quote(args.operator_namespace)} -o json | python3 -c {shell_quote(compact_json_code)} >>"${{operator_health_input}}"
printf '\n' >>"${{operator_health_input}}"
kubectl --request-timeout=30s get service splunk-operator-controller-manager-service --namespace {shell_quote(args.operator_namespace)} -o json | python3 -c {shell_quote(compact_json_code)} >>"${{operator_health_input}}"
printf '\n' >>"${{operator_health_input}}"
kubectl --request-timeout=30s get replicasets --namespace {shell_quote(args.operator_namespace)} -o json | python3 -c {shell_quote(compact_json_code)} >>"${{operator_health_input}}"
python3 -c {shell_quote(operator_health_code)} {shell_quote(args.operator_release_name)} {shell_quote(args.operator_namespace)} {shell_quote(operator_image(args))} {shell_quote(','.join(split_csv(args.watch_namespaces) or [args.namespace]))} <"${{operator_health_input}}"
rm -f "${{operator_health_input}}"
trap - EXIT
"""
    operator_contract_code = """import copy
import json
import subprocess
import sys
from pathlib import Path

import yaml

raw_path, expected_path, namespace, release = sys.argv[1:]
catalog = {
    "ServiceAccount": ("serviceaccounts", True),
    "PersistentVolumeClaim": ("persistentvolumeclaims", True),
    "ClusterRole": ("clusterroles", False),
    "ClusterRoleBinding": ("clusterrolebindings", False),
    "Role": ("roles", True),
    "RoleBinding": ("rolebindings", True),
    "Service": ("services", True),
    "Deployment": ("deployments", True),
}

def flatten(documents):
    result = []
    for item in documents:
        if not isinstance(item, dict):
            continue
        if item.get("kind") == "List" and isinstance(item.get("items"), list):
            result.extend(child for child in item["items"] if isinstance(child, dict))
        else:
            result.append(item)
    return result

raw = flatten(yaml.safe_load_all(Path(raw_path).read_text(encoding="utf-8")))
raw = [item for item in raw if item.get("kind") in catalog]
expected = flatten(yaml.safe_load_all(Path(expected_path).read_text(encoding="utf-8")))
expected = [item for item in expected if item.get("kind") in catalog]
if not raw or not expected:
    raise SystemExit("ERROR: reviewed Operator server dry-run returned no managed objects")

def identity(item):
    kind = item.get("kind", "")
    metadata = item.get("metadata", {})
    namespaced = catalog.get(kind, ("", False))[1]
    return (kind, metadata.get("name", ""), metadata.get("namespace") or (namespace if namespaced else ""))

raw_by_id = {}
for item in raw:
    key = identity(item)
    if not key[1] or key in raw_by_id:
        raise SystemExit(f"ERROR: raw Operator object identity is invalid: {key}")
    raw_by_id[key] = item

expected_by_id = {}
for item in expected:
    key = identity(item)
    if not key[1] or key in expected_by_id:
        raise SystemExit(f"ERROR: reviewed Operator object identity is invalid: {key}")
    expected_by_id[key] = item
if set(raw_by_id) != set(expected_by_id):
    raise SystemExit(
        "ERROR: Operator server dry-run object inventory differs from raw Helm intent: "
        f"raw={sorted(raw_by_id)}, server={sorted(expected_by_id)}"
    )

live = []
for kind, (resource, namespaced) in catalog.items():
    command = ["kubectl", "--request-timeout=30s", "get", resource]
    if namespaced:
        command.extend(["--namespace", namespace])
    command.extend(["-o", "json"])
    result = subprocess.run(
        command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if result.returncode:
        raise SystemExit(
            result.stderr.strip() or f"ERROR: cannot inspect Operator {resource}"
        )
    payload = json.loads(result.stdout or '{"items": []}')
    for item in payload.get("items", []):
        item_metadata = item.get("metadata", {})
        annotations = item_metadata.get("annotations", {})
        if (
            annotations.get("meta.helm.sh/release-name") == release
            and annotations.get("meta.helm.sh/release-namespace") == namespace
        ):
            allowed_finalizers = (
                {"kubernetes.io/pvc-protection"}
                if item.get("kind") == "PersistentVolumeClaim" else set()
            )
            if (
                item_metadata.get("deletionTimestamp")
                or item_metadata.get("ownerReferences")
                or set(item_metadata.get("finalizers", [])) - allowed_finalizers
            ):
                raise SystemExit(
                    f"ERROR: live Operator object is terminating or unexpectedly owned: "
                    f"{identity(item)}"
                )
            live.append(item)

live_by_id = {identity(item): item for item in live}
if len(live_by_id) != len(live):
    raise SystemExit("ERROR: live Operator object identity is ambiguous")
if set(live_by_id) != set(expected_by_id):
    raise SystemExit(
        "ERROR: Operator Helm object inventory differs: "
        f"live={sorted(live_by_id)}, reviewed={sorted(expected_by_id)}"
    )

dynamic_annotations = {
    "deployment.kubernetes.io/revision",
    "kubectl.kubernetes.io/last-applied-configuration",
    "meta.helm.sh/release-name",
    "meta.helm.sh/release-namespace",
    "pv.kubernetes.io/bind-completed",
    "pv.kubernetes.io/bound-by-controller",
    "volume.beta.kubernetes.io/storage-provisioner",
    "volume.kubernetes.io/storage-provisioner",
}

def reviewed_annotations(item):
    return {
        key: value
        for key, value in item.get("metadata", {}).get("annotations", {}).items()
        if key not in dynamic_annotations
    }

def named_inventory(values, path):
    if values is None:
        return []
    if not isinstance(values, list):
        raise SystemExit(f"ERROR: {path} is not a list")
    names = [item.get("name") for item in values if isinstance(item, dict)]
    if len(names) != len(values) or any(not name for name in names):
        raise SystemExit(f"ERROR: {path} has an unnamed entry")
    if len(names) != len(set(names)):
        raise SystemExit(f"ERROR: {path} has duplicate names")
    return names

def require_same(path, raw_value, live_value):
    if raw_value != live_value:
        raise SystemExit(
            f"ERROR: live Operator {path} differs from raw Helm intent: "
            f"live={live_value!r}, raw={raw_value!r}"
        )

def normalized_probe(value):
    if value is None:
        return None
    probe = copy.deepcopy(value)
    probe.setdefault("timeoutSeconds", 1)
    probe.setdefault("periodSeconds", 10)
    probe.setdefault("successThreshold", 1)
    probe.setdefault("failureThreshold", 3)
    if isinstance(probe.get("httpGet"), dict):
        probe["httpGet"].setdefault("scheme", "HTTP")
    return probe

def normalized_container_ports(values):
    result = copy.deepcopy(values or [])
    for port in result:
        port.setdefault("protocol", "TCP")
        if port.get("hostPort") not in (None, 0) or port.get("hostIP") not in (None, ""):
            raise SystemExit("ERROR: live Operator container exposes an unreviewed host port/IP")
        port.pop("hostPort", None)
        port.pop("hostIP", None)
    return sorted(result, key=lambda item: item.get("name", ""))

def normalized_volume_mounts(values):
    result = copy.deepcopy(values or [])
    for mount in result:
        if mount.get("readOnly") is False:
            mount.pop("readOnly", None)
        if mount.get("mountPropagation") in (None, "None"):
            mount.pop("mountPropagation", None)
        if mount.get("recursiveReadOnly") in (None, "Disabled"):
            mount.pop("recursiveReadOnly", None)
    return sorted(result, key=lambda item: item.get("name", ""))

def normalized_env(values):
    result = copy.deepcopy(values or [])
    for entry in result:
        field_ref = entry.get("valueFrom", {}).get("fieldRef")
        if isinstance(field_ref, dict):
            field_ref.setdefault("apiVersion", "v1")
    return sorted(result, key=lambda item: item.get("name", ""))

def normalized_service_ports(values):
    result = copy.deepcopy(values or [])
    for port in result:
        port.setdefault("protocol", "TCP")
        port.setdefault("targetPort", port.get("port"))
        if port.get("nodePort") in (None, 0):
            port.pop("nodePort", None)
    return sorted(result, key=lambda item: item.get("name", ""))

def enforce_raw_intent(raw_item, live_item):
    kind = raw_item.get("kind")
    raw_metadata = raw_item.get("metadata", {})
    live_metadata = live_item.get("metadata", {})
    require_same(
        f"{kind} metadata.labels",
        raw_metadata.get("labels", {}),
        live_metadata.get("labels", {}),
    )
    require_same(
        f"{kind} metadata.annotations",
        reviewed_annotations(raw_item),
        reviewed_annotations(live_item),
    )
    raw_spec = raw_item.get("spec", {})
    live_spec = live_item.get("spec", {})
    if kind in {"ClusterRole", "Role"}:
        require_same(f"{kind} rules", raw_item.get("rules", []), live_item.get("rules", []))
        if kind == "ClusterRole":
            require_same(
                "ClusterRole aggregationRule",
                raw_item.get("aggregationRule"), live_item.get("aggregationRule"),
            )
    elif kind in {"ClusterRoleBinding", "RoleBinding"}:
        require_same(f"{kind} roleRef", raw_item.get("roleRef"), live_item.get("roleRef"))
        require_same(f"{kind} subjects", raw_item.get("subjects", []), live_item.get("subjects", []))
    elif kind == "ServiceAccount":
        raw_automount = raw_item.get("automountServiceAccountToken", True)
        live_automount = live_item.get("automountServiceAccountToken", True)
        require_same(
            "ServiceAccount automountServiceAccountToken",
            raw_automount, live_automount,
        )
        require_same(
            "ServiceAccount imagePullSecrets",
            named_inventory(raw_item.get("imagePullSecrets", []), "raw ServiceAccount imagePullSecrets"),
            named_inventory(live_item.get("imagePullSecrets", []), "live ServiceAccount imagePullSecrets"),
        )
    elif kind == "Service":
        require_same("Service selector", raw_spec.get("selector", {}), live_spec.get("selector", {}))
        require_same(
            "Service port inventory",
            named_inventory(raw_spec.get("ports", []), "raw Service ports"),
            named_inventory(live_spec.get("ports", []), "live Service ports"),
        )
        require_same(
            "Service ports",
            normalized_service_ports(raw_spec.get("ports", [])),
            normalized_service_ports(live_spec.get("ports", [])),
        )
        for field, default_value in (
            ("internalTrafficPolicy", "Cluster"),
            ("sessionAffinity", "None"),
            ("publishNotReadyAddresses", False),
        ):
            require_same(
                f"Service {field}",
                raw_spec.get(field, default_value),
                live_spec.get(field, default_value),
            )
        for field in (
            "sessionAffinityConfig", "trafficDistribution", "externalIPs",
            "externalName", "loadBalancerClass", "loadBalancerSourceRanges",
        ):
            require_same(
                f"Service {field}", raw_spec.get(field), live_spec.get(field)
            )
    elif kind == "Deployment":
        for field in ("replicas", "selector", "strategy"):
            require_same(
                f"Deployment spec.{field}", raw_spec.get(field), live_spec.get(field)
            )
        deployment_defaults = {
            "paused": False,
            "minReadySeconds": 0,
            "revisionHistoryLimit": 10,
            "progressDeadlineSeconds": 600,
        }
        for field, default_value in deployment_defaults.items():
            require_same(
                f"Deployment spec.{field}",
                raw_spec.get(field, default_value),
                live_spec.get(field, default_value),
            )
        raw_template = raw_spec.get("template", {})
        live_template = live_spec.get("template", {})
        require_same(
            "Deployment template labels",
            raw_template.get("metadata", {}).get("labels", {}),
            live_template.get("metadata", {}).get("labels", {}),
        )
        require_same(
            "Deployment template annotations",
            raw_template.get("metadata", {}).get("annotations", {}),
            live_template.get("metadata", {}).get("annotations", {}),
        )
        raw_pod = raw_template.get("spec", {})
        live_pod = live_template.get("spec", {})
        pod_default_fields = {
            "restartPolicy": "Always",
            "dnsPolicy": "ClusterFirst",
            "schedulerName": "default-scheduler",
            "enableServiceLinks": True,
        }
        unexpected_pod_fields = set(live_pod) - set(raw_pod) - set(pod_default_fields) - {
            "serviceAccount"
        }
        if unexpected_pod_fields:
            raise SystemExit(
                "ERROR: live Operator pod template has fields absent from raw Helm "
                f"intent: {sorted(unexpected_pod_fields)}"
            )
        for field, default_value in pod_default_fields.items():
            if field not in raw_pod and live_pod.get(field, default_value) != default_value:
                raise SystemExit(
                    f"ERROR: live Operator pod template changes default {field}"
                )
        if "serviceAccount" in live_pod and live_pod.get("serviceAccount") != raw_pod.get(
            "serviceAccountName"
        ):
            raise SystemExit("ERROR: live Operator pod serviceAccount alias differs")
        for field in (
            "serviceAccountName", "securityContext", "hostNetwork", "hostPID",
            "hostIPC", "nodeSelector", "affinity", "tolerations",
            "terminationGracePeriodSeconds",
        ):
            require_same(
                f"Deployment template spec.{field}",
                raw_pod.get(field), live_pod.get(field),
            )
        for field in ("containers", "initContainers", "volumes", "imagePullSecrets"):
            require_same(
                f"Deployment template {field} inventory",
                named_inventory(raw_pod.get(field, []), f"raw Deployment {field}"),
                named_inventory(live_pod.get(field, []), f"live Deployment {field}"),
            )
        require_same(
            "Deployment template volumes",
            sorted(raw_pod.get("volumes", []), key=lambda item: item.get("name", "")),
            sorted(live_pod.get("volumes", []), key=lambda item: item.get("name", "")),
        )
        require_same(
            "Deployment template imagePullSecrets",
            sorted(raw_pod.get("imagePullSecrets", []), key=lambda item: item.get("name", "")),
            sorted(live_pod.get("imagePullSecrets", []), key=lambda item: item.get("name", "")),
        )
        raw_containers = {item["name"]: item for item in raw_pod.get("containers", [])}
        live_containers = {item["name"]: item for item in live_pod.get("containers", [])}
        for name, raw_container in raw_containers.items():
            live_container = live_containers[name]
            unexpected_fields = set(live_container) - set(raw_container) - {
                "terminationMessagePath", "terminationMessagePolicy"
            }
            if unexpected_fields:
                raise SystemExit(
                    f"ERROR: live Operator container {name!r} has fields absent from "
                    f"raw Helm intent: {sorted(unexpected_fields)}"
                )
            for field in (
                "image", "imagePullPolicy", "args", "command", "resources",
                "securityContext",
            ):
                require_same(
                    f"Deployment container {name}.{field}",
                    raw_container.get(field), live_container.get(field),
                )
            for field in ("livenessProbe", "readinessProbe", "startupProbe"):
                require_same(
                    f"Deployment container {name}.{field}",
                    normalized_probe(raw_container.get(field)),
                    normalized_probe(live_container.get(field)),
                )
            for field in ("env", "ports", "volumeMounts"):
                require_same(
                    f"Deployment container {name}.{field} inventory",
                    named_inventory(raw_container.get(field, []), f"raw container {name} {field}"),
                    named_inventory(live_container.get(field, []), f"live container {name} {field}"),
                )
            require_same(
                f"Deployment container {name}.env",
                normalized_env(raw_container.get("env", [])),
                normalized_env(live_container.get("env", [])),
            )
            require_same(
                f"Deployment container {name}.ports",
                normalized_container_ports(raw_container.get("ports", [])),
                normalized_container_ports(live_container.get("ports", [])),
            )
            require_same(
                f"Deployment container {name}.volumeMounts",
                normalized_volume_mounts(raw_container.get("volumeMounts", [])),
                normalized_volume_mounts(live_container.get("volumeMounts", [])),
            )
            require_same(
                f"Deployment container {name}.envFrom",
                raw_container.get("envFrom", []), live_container.get("envFrom", []),
            )

for key, raw_item in raw_by_id.items():
    enforce_raw_intent(raw_item, live_by_id[key])

def canonical(item):
    value = copy.deepcopy(item)
    value.pop("status", None)
    metadata = value.get("metadata", {})
    namespaced = catalog[value.get("kind")][1]
    annotations = {
        key: child
        for key, child in metadata.get("annotations", {}).items()
        if key not in dynamic_annotations
    }
    value["metadata"] = {
        "name": metadata.get("name", ""),
        "namespace": metadata.get("namespace") or (namespace if namespaced else ""),
        "labels": metadata.get("labels", {}),
        "annotations": annotations,
    }
    if value.get("kind") == "ServiceAccount":
        value.pop("secrets", None)
    if value.get("kind") == "PersistentVolumeClaim":
        value.get("spec", {}).pop("volumeName", None)
    if value.get("kind") == "Service":
        spec = value.get("spec", {})
        for field in (
            "clusterIP", "clusterIPs", "healthCheckNodePort", "ipFamilies",
            "ipFamilyPolicy", "internalTrafficPolicy",
        ):
            spec.pop(field, None)
    template_metadata = (
        value.get("spec", {}).get("template", {}).get("metadata", {})
    )
    if template_metadata.get("creationTimestamp") is None:
        template_metadata.pop("creationTimestamp", None)
    return value

for key, expected_item in expected_by_id.items():
    reviewed = canonical(expected_item)
    actual = canonical(live_by_id[key])
    if actual != reviewed:
        raise SystemExit(
            f"ERROR: live Operator object differs from reviewed server-dry-run: {key}; "
            f"live={actual!r}, reviewed={reviewed!r}"
        )
"""
    operator_contract_values = (
        "operator_contract_values+=(--values operator-values-overlay.yaml)"
        if args.operator_values_overlay
        else ":"
    )
    operator_contract_shell = f"""operator_contract_dir="$(mktemp -d "${{TMPDIR:-/tmp}}/splunk-operator-contract.XXXXXX")"
chmod 0700 "${{operator_contract_dir}}"
trap 'rm -rf "${{operator_contract_dir}}"' EXIT
operator_contract_values=(--values operator-values.yaml)
{operator_contract_values}
{helm_repo_setup}
helm template {shell_quote(args.operator_release_name)} {shell_quote(operator_chart_ref)} \
  --version {shell_quote(chart_version(args))} \
  --namespace {shell_quote(args.operator_namespace)} \
  "${{operator_contract_values[@]}}" >"${{operator_contract_dir}}/raw.yaml"
kubectl apply --server-side --dry-run=server \
  --namespace {shell_quote(args.operator_namespace)} \
  --field-manager=sok-status --force-conflicts -o yaml \
  -f "${{operator_contract_dir}}/raw.yaml" \
  >"${{operator_contract_dir}}/expected.yaml"
python3 -c {shell_quote(operator_contract_code)} \
  "${{operator_contract_dir}}/raw.yaml" \
  "${{operator_contract_dir}}/expected.yaml" \
  {shell_quote(args.operator_namespace)} {shell_quote(args.operator_release_name)}
rm -rf "${{operator_contract_dir}}"
trap - EXIT
"""
    enterprise_service_shell = f"""enterprise_service_input="$(mktemp)"
trap 'rm -f "${{enterprise_service_input}}"' EXIT
kubectl --request-timeout=30s get statefulsets --namespace {shell_quote(args.namespace)} -o json | python3 -c {shell_quote(compact_json_code)} >"${{enterprise_service_input}}"
printf '\n' >>"${{enterprise_service_input}}"
kubectl --request-timeout=30s get services --namespace {shell_quote(args.namespace)} -o json | python3 -c {shell_quote(compact_json_code)} >>"${{enterprise_service_input}}"
printf '\n' >>"${{enterprise_service_input}}"
kubectl --request-timeout=30s get endpointslices.discovery.k8s.io --namespace {shell_quote(args.namespace)} -o json | python3 -c {shell_quote(compact_json_code)} >>"${{enterprise_service_input}}"
printf '\n' >>"${{enterprise_service_input}}"
kubectl --request-timeout=30s get pods --namespace {shell_quote(args.namespace)} -o json | python3 -c {shell_quote(compact_json_code)} >>"${{enterprise_service_input}}"
python3 -c {shell_quote(service_health_code)} \
  {shell_quote(json.dumps(expected_controllers, sort_keys=True))} \
  {shell_quote(args.namespace)} <"${{enterprise_service_input}}"
rm -f "${{enterprise_service_input}}"
trap - EXIT
"""
    pvc_health_shell = f"""pvc_health_input="$(mktemp)"
trap 'rm -f "${{pvc_health_input}}"' EXIT
kubectl --request-timeout=30s get statefulsets --namespace {shell_quote(args.namespace)} -o json | python3 -c {shell_quote(compact_json_code)} >"${{pvc_health_input}}"
printf '\n' >>"${{pvc_health_input}}"
kubectl --request-timeout=30s get persistentvolumeclaims --namespace {shell_quote(args.namespace)} -o json | python3 -c {shell_quote(compact_json_code)} >>"${{pvc_health_input}}"
printf '\n' >>"${{pvc_health_input}}"
kubectl --request-timeout=30s get pods --namespace {shell_quote(args.namespace)} -o json | python3 -c {shell_quote(compact_json_code)} >>"${{pvc_health_input}}"
python3 -c {shell_quote(pvc_health_code)} \
  {shell_quote(json.dumps(expected_controllers, sort_keys=True))} \
  {shell_quote(args.namespace)} {shell_quote(args.etc_storage)} \
  {shell_quote(args.var_storage)} {shell_quote(args.storage_class)} \
  <"${{pvc_health_input}}"
rm -f "${{pvc_health_input}}"
trap - EXIT
"""
    irsa_contract = (
        {
            "namespace": args.namespace,
            "region": args.aws_region,
            "role_arn": args.splunk_irsa_role_arn,
            "service_account": args.splunk_service_account,
            "token_expiration": int(args.splunk_irsa_token_expiration),
        }
        if args.splunk_service_account
        else {}
    )
    irsa_service_account_status = "printf '%s' '{}'"
    if args.splunk_service_account:
        irsa_service_account_status = (
            "kubectl --request-timeout=30s get serviceaccount "
            f"{shell_quote(args.splunk_service_account)} --namespace "
            f"{shell_quote(args.namespace)} -o json | python3 -c "
            f"{shell_quote(compact_json_code)}"
        )
    pod_health_shell = f"""pod_health_input="$(mktemp)"
trap 'rm -f "${{pod_health_input}}"' EXIT
kubectl --request-timeout=30s get statefulsets --namespace {shell_quote(args.namespace)} -o json | python3 -c {shell_quote(compact_json_code)} >"${{pod_health_input}}"
printf '\n' >>"${{pod_health_input}}"
kubectl --request-timeout=30s get pods --namespace {shell_quote(args.namespace)} -o json | python3 -c {shell_quote(compact_json_code)} >>"${{pod_health_input}}"
printf '\n' >>"${{pod_health_input}}"
{irsa_service_account_status} >>"${{pod_health_input}}"
python3 -c {shell_quote(pod_health_code)} \
  {shell_quote(json.dumps(expected_pods, sort_keys=True))} \
  {shell_quote(splunk_image(args))} \
  {shell_quote(json.dumps(irsa_contract, sort_keys=True))} \
  <"${{pod_health_input}}"
rm -f "${{pod_health_input}}"
trap - EXIT
"""
    placement_health_shell = f"""placement_health_input="$(mktemp)"
trap 'rm -f "${{placement_health_input}}"' EXIT
kubectl --request-timeout=30s get pods --namespace {shell_quote(args.namespace)} -o json | python3 -c {shell_quote(compact_json_code)} >"${{placement_health_input}}"
printf '\n' >>"${{placement_health_input}}"
kubectl --request-timeout=30s get nodes -o json | python3 -c {shell_quote(compact_json_code)} >>"${{placement_health_input}}"
python3 -c {shell_quote(placement_health_code)} \
  {shell_quote(json.dumps(placement_contracts, sort_keys=True))} \
  {shell_quote(bool_word(args.deployment_profile == 'production'))} \
  <"${{placement_health_input}}"
rm -f "${{placement_health_input}}"
trap - EXIT
"""
    collect_live_crs_code = """import json
import subprocess
import sys
from urllib.parse import quote

namespace = sys.argv[1]
items = []
schemas = {}
crds = []
resources = (
    ("standalones", "v4"), ("clustermanagers", "v4"),
    ("indexerclusters", "v4"), ("searchheadclusters", "v4"),
    ("licensemanagers", "v4"), ("monitoringconsoles", "v4"),
    ("ingestorclusters", "v4"), ("queues", "v4"),
    ("objectstorages", "v4"),
    # Legacy manager CRs must be visible so an apparently healthy v4 release
    # cannot conceal unsupported v1-v3 topology in the reviewed namespace.
    ("clustermasters", ""), ("licensemasters", ""),
)
for resource, version in resources:
    crd = subprocess.run(
        [
            "kubectl", "--request-timeout=30s", "get", "crd",
            f"{resource}.enterprise.splunk.com", "--ignore-not-found",
            "-o", "json",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if crd.returncode:
        raise SystemExit(crd.stderr.strip() or f"ERROR: cannot inspect CRD {resource}")
    if not crd.stdout.strip():
        continue
    try:
        crd_payload = json.loads(crd.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: invalid kubectl CRD JSON for {resource}: {exc}") from exc
    crds.append(crd_payload)
    crd_kind = crd_payload.get("spec", {}).get("names", {}).get("kind")
    versions = crd_payload.get("spec", {}).get("versions", [])
    v4 = next((version for version in versions if version.get("name") == "v4"), None)
    if crd_kind and v4:
        schema = v4.get("schema", {}).get("openAPIV3Schema", {}).get(
            "properties", {}
        ).get("spec")
        if isinstance(schema, dict):
            schemas[crd_kind] = schema
    if version:
        get_args = [
            "kubectl", "--request-timeout=30s", "get", "--raw",
            f"/apis/enterprise.splunk.com/{version}/namespaces/"
            f"{quote(namespace, safe='')}/{resource}",
        ]
    else:
        get_args = [
            "kubectl", "--request-timeout=30s", "get", resource,
            "--namespace", namespace, "-o", "json",
        ]
    result = subprocess.run(
        get_args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise SystemExit(
            result.stderr.strip()
            or f"ERROR: cannot inventory {resource} in namespace {namespace}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: invalid kubectl JSON for {resource}: {exc}") from exc
    items.extend(payload.get("items", []))
print(json.dumps({"items": items, "schemas": schemas, "crds": crds}, separators=(",", ":")))
"""
    cr_contract_code = """import json
import sys

try:
    import yaml
except ModuleNotFoundError as exc:
    raise SystemExit(
        "ERROR: status contract validation requires PyYAML 6.x; install the "
        "repository requirements"
    ) from exc
if int(str(getattr(yaml, "__version__", "0")).split(".", 1)[0]) != 6:
    raise SystemExit(
        f"ERROR: status contract validation requires PyYAML 6.x; found "
        f"{getattr(yaml, '__version__', 'unknown')!r}"
    )

expected_path, live_path, expected_crd_path = sys.argv[1:4]
release, namespace, external_lm, queue_secret_version = sys.argv[4:]
managed_kinds = {
    "Standalone", "ClusterManager", "IndexerCluster", "SearchHeadCluster",
    "LicenseManager", "MonitoringConsole", "IngestorCluster", "Queue",
    "ObjectStorage",
}
reconciled_kinds = managed_kinds
replicated_kinds = {
    "Standalone", "IndexerCluster", "SearchHeadCluster", "IngestorCluster",
}
reference_fields = (
    "apiVersion", "fieldPath", "kind", "name", "namespace",
    "resourceVersion", "uid",
)
object_reference_names = {
    "clusterManagerRef", "licenseManagerRef", "monitoringConsoleRef",
    "objectStorageRef", "queueRef",
}


def flatten_documents(documents):
    for document in documents:
        if not isinstance(document, dict):
            continue
        if document.get("kind") == "List":
            yield from flatten_documents(document.get("items", []))
        else:
            yield document


with open(expected_path, encoding="utf-8") as handle:
    expected_documents = list(flatten_documents(yaml.safe_load_all(handle)))
with open(live_path, encoding="utf-8") as handle:
    live_payload = json.load(handle)
live_documents = live_payload.get("items", [])
spec_schemas = live_payload.get("schemas", {})


def normalize_crd_spec(value, crd_name):
    if not isinstance(value, dict):
        raise SystemExit(f"ERROR: CRD {crd_name} spec is not a mapping")
    spec = json.loads(json.dumps(value))

    # These are the apiextensions.k8s.io/v1 API defaults. Do not add broad
    # empty-value normalization here: omitted subresources, columns, warning
    # text, schemas, and webhook settings are part of the reviewed contract.
    names = spec.get("names")
    if not isinstance(names, dict):
        raise SystemExit(f"ERROR: CRD {crd_name} spec.names is not a mapping")
    kind = names.get("kind")
    if not names.get("singular") and isinstance(kind, str):
        names["singular"] = kind.lower()
    if not names.get("listKind") and isinstance(kind, str) and kind:
        names["listKind"] = kind + "List"
    if "preserveUnknownFields" not in spec:
        spec["preserveUnknownFields"] = False

    conversion = spec.get("conversion")
    if conversion is None:
        spec["conversion"] = {"strategy": "None"}
    elif not isinstance(conversion, dict):
        raise SystemExit(f"ERROR: CRD {crd_name} spec.conversion is not a mapping")
    else:
        service = (
            conversion.get("webhook", {})
            .get("clientConfig", {})
            .get("service")
        )
        if isinstance(service, dict) and service.get("port") is None:
            service["port"] = 443

    versions = spec.get("versions")
    if not isinstance(versions, list) or not versions:
        raise SystemExit(f"ERROR: CRD {crd_name} has no version contract")
    normalized_versions = []
    version_names = []
    for version in versions:
        if not isinstance(version, dict) or not isinstance(version.get("name"), str):
            raise SystemExit(f"ERROR: CRD {crd_name} has a malformed version")
        normalized_version = json.loads(json.dumps(version))
        if "deprecated" not in normalized_version:
            normalized_version["deprecated"] = False
        columns = normalized_version.get("additionalPrinterColumns", [])
        if not isinstance(columns, list):
            raise SystemExit(
                f"ERROR: CRD {crd_name} version {version.get('name')} has "
                "malformed additionalPrinterColumns"
            )
        for column in columns:
            if not isinstance(column, dict):
                raise SystemExit(
                    f"ERROR: CRD {crd_name} version {version.get('name')} has "
                    "a malformed printer column"
                )
        normalized_versions.append(normalized_version)
        version_names.append(normalized_version["name"])
    if len(set(version_names)) != len(version_names):
        raise SystemExit(f"ERROR: CRD {crd_name} has duplicate version names")
    spec["versions"] = sorted(
        normalized_versions, key=lambda version: version["name"]
    )
    return spec


def first_difference(expected, actual, path="spec"):
    if type(expected) is not type(actual):
        return path
    if isinstance(expected, dict):
        expected_keys = set(expected)
        actual_keys = set(actual)
        if expected_keys != actual_keys:
            differing_key = sorted(expected_keys ^ actual_keys)[0]
            return f"{path}.{differing_key}"
        for key in sorted(expected):
            difference = first_difference(expected[key], actual[key], f"{path}.{key}")
            if difference:
                return difference
        return ""
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return path
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            difference = first_difference(
                expected_item, actual_item, f"{path}[{index}]"
            )
            if difference:
                return difference
        return ""
    return "" if expected == actual else path


if expected_crd_path:
    with open(expected_crd_path, encoding="utf-8") as handle:
        reviewed_crd_documents = list(flatten_documents(yaml.safe_load_all(handle)))
    reviewed_crds = {
        item.get("metadata", {}).get("name"): item
        for item in reviewed_crd_documents
        if item.get("kind") == "CustomResourceDefinition"
    }
    live_crds = {
        item.get("metadata", {}).get("name"): item
        for item in live_payload.get("crds", [])
    }
    required_crd_names = {
        plural + ".enterprise.splunk.com"
        for plural in (
            "standalones", "clustermanagers", "indexerclusters",
            "searchheadclusters", "licensemanagers", "monitoringconsoles",
            "ingestorclusters", "queues", "objectstorages",
        )
    }
    if not required_crd_names.issubset(reviewed_crds) or not required_crd_names.issubset(live_crds):
        raise SystemExit("ERROR: reviewed/live SOK CRD inventory is incomplete")
    for crd_name in sorted(required_crd_names):
        reviewed_spec = normalize_crd_spec(
            reviewed_crds[crd_name].get("spec", {}), crd_name
        )
        live_spec = normalize_crd_spec(
            live_crds[crd_name].get("spec", {}), crd_name
        )
        difference = first_difference(reviewed_spec, live_spec)
        if difference:
            raise SystemExit(
                f"ERROR: live CRD {crd_name} differs from the reviewed bundle "
                f"at {difference}"
            )
        reviewed_versions = {
            version.get("name"): version for version in reviewed_spec.get("versions", [])
        }
        live_versions = {
            version.get("name"): version for version in live_spec.get("versions", [])
        }
        if (
            not live_versions.get("v4", {}).get("served")
            or not live_versions.get("v4", {}).get("storage")
        ):
            raise SystemExit(f"ERROR: live CRD {crd_name} does not serve/store v4")
        conditions = {
            condition.get("type"): condition.get("status")
            for condition in live_crds[crd_name].get("status", {}).get("conditions", [])
        }
        stored_versions = set(
            live_crds[crd_name].get("status", {}).get("storedVersions", [])
        )
        if (
            conditions.get("Established") != "True"
            or conditions.get("NamesAccepted") != "True"
            or "v4" not in stored_versions
            or not stored_versions.issubset(live_versions)
        ):
            raise SystemExit(f"ERROR: live CRD {crd_name} is not established on reviewed versions")


def identity(item):
    metadata = item.get("metadata", {})
    return item.get("kind"), metadata.get("name")


expected_items = [
    item for item in expected_documents
    if item.get("apiVersion") == "enterprise.splunk.com/v4"
    and item.get("kind") in managed_kinds
]
expected_by_identity = {}
for item in expected_items:
    item_identity = identity(item)
    kind, name = item_identity
    metadata = item.get("metadata", {})
    if not name or metadata.get("namespace") != namespace:
        raise SystemExit(
            f"ERROR: rendered {kind}/{name or '<missing>'} is outside reviewed "
            f"namespace {namespace!r}"
        )
    if item_identity in expected_by_identity:
        raise SystemExit(f"ERROR: rendered duplicate custom resource {kind}/{name}")
    expected_by_identity[item_identity] = item
if not expected_by_identity:
    raise SystemExit("ERROR: reviewed Helm template contains no Splunk v4 custom resources")

live_by_identity = {}
for item in live_documents:
    kind, name = identity(item)
    metadata = item.get("metadata", {})
    label = f"{kind}/{name or '<missing>'}"
    if not kind or not name or metadata.get("namespace") != namespace:
        raise SystemExit(f"ERROR: malformed or cross-namespace live custom resource {label}")
    if (kind, name) in live_by_identity:
        raise SystemExit(f"ERROR: duplicate live custom-resource identity {label}")
    if metadata.get("deletionTimestamp"):
        raise SystemExit(f"ERROR: live {label} is terminating")
    paused = sorted(
        key for key in metadata.get("annotations", {})
        if key.lower().endswith(".enterprise.splunk.com/paused")
    )
    if paused:
        raise SystemExit(f"ERROR: live {label} is paused by {paused}")
    if metadata.get("annotations", {}).get(
        "enterprise.splunk.com/admin-managed-pv"
    ) not in (None, "", "false"):
        raise SystemExit(f"ERROR: live {label} enables unreviewed admin-managed PVs")
    if metadata.get("ownerReferences"):
        raise SystemExit(f"ERROR: live {label} has an unreviewed Kubernetes ownerReference")
    generation = metadata.get("generation")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise SystemExit(f"ERROR: live {label} has no valid metadata.generation")
    if not metadata.get("uid") or not metadata.get("resourceVersion"):
        raise SystemExit(f"ERROR: live {label} has incomplete API-server identity")
    status = item.get("status", {})
    observed = status.get("observedGeneration")
    if observed is not None and observed != generation:
        raise SystemExit(
            f"ERROR: live {label} status is stale: observedGeneration={observed}, "
            f"generation={generation}"
        )
    for condition in status.get("conditions", []):
        observed = condition.get("observedGeneration")
        if observed is not None and observed != generation:
            raise SystemExit(
                f"ERROR: live {label} has a stale {condition.get('type')!r} condition"
            )
    live_by_identity[(kind, name)] = item

# A same-namespace existing LicenseManager is an explicit dependency rather
# than an object owned by this Enterprise Helm release. It may be excluded only
# by its exact reviewed identity, and it may not be a stale object owned by the
# release under validation.
if external_lm:
    external_identity = ("LicenseManager", external_lm)
    external = live_by_identity.get(external_identity)
    if external is None:
        raise SystemExit(
            f"ERROR: reviewed external LicenseManager/{external_lm} is missing"
        )
    if external.get("apiVersion") != "enterprise.splunk.com/v4":
        raise SystemExit(
            f"ERROR: external LicenseManager/{external_lm} does not use "
            "enterprise.splunk.com/v4"
        )
    annotations = external.get("metadata", {}).get("annotations", {})
    if (
        annotations.get("meta.helm.sh/release-name") == release
        and annotations.get("meta.helm.sh/release-namespace") == namespace
    ):
        raise SystemExit(
            f"ERROR: external LicenseManager/{external_lm} is unexpectedly owned "
            "by the reviewed Enterprise release"
        )
    if external.get("status", {}).get("phase") != "Ready":
        raise SystemExit(
            f"ERROR: external LicenseManager/{external_lm} is not Ready"
        )
    del live_by_identity[external_identity]

if set(live_by_identity) != set(expected_by_identity):
    missing = sorted(set(expected_by_identity) - set(live_by_identity))
    unexpected = sorted(set(live_by_identity) - set(expected_by_identity))
    raise SystemExit(
        "ERROR: live Splunk custom-resource inventory differs from the reviewed "
        f"Helm template: missing={missing}, unexpected={unexpected}"
    )


def canonical_reference(value):
    value = value if isinstance(value, dict) else {}
    return {field: value.get(field) or "" for field in reference_fields}


def normalize_with_schema(value, schema):
    if value is None and "default" in schema:
        value = json.loads(json.dumps(schema["default"]))
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        normalized = dict(value)
        for key, child_schema in properties.items():
            if key not in normalized and "default" in child_schema:
                normalized[key] = json.loads(json.dumps(child_schema["default"]))
        return {
            key: normalize_with_schema(child, properties.get(key, {}))
            for key, child in normalized.items()
        }
    if isinstance(value, list):
        item_schema = schema.get("items", {})
        normalized = [normalize_with_schema(child, item_schema) for child in value]
        list_type = schema.get("x-kubernetes-list-type")
        if list_type == "map":
            list_keys = schema.get("x-kubernetes-list-map-keys", [])
            normalized.sort(
                key=lambda child: tuple(
                    json.dumps(child.get(key), sort_keys=True) for key in list_keys
                )
            )
        elif list_type == "set":
            normalized.sort(key=lambda child: json.dumps(child, sort_keys=True))
        return normalized
    return value


def compare_selected(expected, actual, path, exact_maps=True):
    if path.rsplit(".", 1)[-1] in object_reference_names:
        expected_ref = canonical_reference(expected)
        actual_ref = canonical_reference(actual)
        if actual_ref != expected_ref:
            raise SystemExit(
                f"ERROR: live selected spec differs at {path}: "
                f"live={actual_ref!r}, reviewed={expected_ref!r}"
            )
        return
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            raise SystemExit(
                f"ERROR: live selected spec differs at {path}: expected a mapping"
            )
        if exact_maps and set(actual) != set(expected):
            raise SystemExit(
                f"ERROR: live mapping keys differ at {path}: "
                f"live={sorted(actual)}, reviewed={sorted(expected)}"
            )
        for key, value in expected.items():
            if key not in actual:
                raise SystemExit(f"ERROR: live selected spec is missing {path}.{key}")
            compare_selected(value, actual[key], f"{path}.{key}", exact_maps)
        return
    if isinstance(expected, list):
        if not isinstance(actual, list):
            raise SystemExit(
                f"ERROR: live selected spec differs at {path}: expected a list"
            )
        named_expected = all(
            isinstance(value, dict) and isinstance(value.get("name"), str)
            for value in expected
        )
        named_actual = all(
            isinstance(value, dict) and isinstance(value.get("name"), str)
            for value in actual
        )
        if named_expected and named_actual:
            expected_map = {value["name"]: value for value in expected}
            actual_map = {value["name"]: value for value in actual}
            if len(expected_map) != len(expected) or len(actual_map) != len(actual):
                raise SystemExit(f"ERROR: duplicate named list entry at {path}")
            if set(expected_map) != set(actual_map):
                raise SystemExit(
                    f"ERROR: live named-list identity differs at {path}: "
                    f"live={sorted(actual_map)}, reviewed={sorted(expected_map)}"
                )
            for name, value in expected_map.items():
                compare_selected(
                    value, actual_map[name], f"{path}[name={name!r}]", exact_maps
                )
            return
        if len(expected) != len(actual):
            raise SystemExit(
                f"ERROR: live list length differs at {path}: "
                f"live={len(actual)}, reviewed={len(expected)}"
            )
        for index, value in enumerate(expected):
            compare_selected(value, actual[index], f"{path}[{index}]", exact_maps)
        return
    if actual != expected:
        raise SystemExit(
            f"ERROR: live selected spec differs at {path}: "
            f"live={actual!r}, reviewed={expected!r}"
        )


def validate_app_framework(item, label):
    spec_repo = item.get("spec", {}).get("appRepo")
    if not isinstance(spec_repo, dict) or not spec_repo:
        return
    sources = spec_repo.get("appSources", [])
    if not isinstance(sources, list) or not sources:
        raise SystemExit(f"ERROR: live {label} App Framework has no appSources")
    source_names = [source.get("name") for source in sources if isinstance(source, dict)]
    if (
        len(source_names) != len(sources)
        or any(not isinstance(name, str) or not name for name in source_names)
        or len(set(source_names)) != len(source_names)
    ):
        raise SystemExit(f"ERROR: live {label} has invalid App Framework source identities")
    context = item.get("status", {}).get("appContext")
    if not isinstance(context, dict):
        raise SystemExit(f"ERROR: live {label} has no App Framework status context")
    if context.get("version") != 1:
        raise SystemExit(
            f"ERROR: live {label} App Framework status is not phase-3/version 1"
        )
    if context.get("isDeploymentInProgress") is not False:
        raise SystemExit(f"ERROR: live {label} App Framework deployment is in progress")
    last_check = context.get("lastAppInfoCheckTime")
    if not isinstance(last_check, int) or isinstance(last_check, bool) or last_check <= 0:
        raise SystemExit(f"ERROR: live {label} App Framework has not completed a repo check")
    if context.get("appRepo") != spec_repo:
        raise SystemExit(
            f"ERROR: live {label} App Framework status has not adopted spec.appRepo"
        )
    deploy_status = context.get("appSrcDeployStatus")
    if not isinstance(deploy_status, dict) or not set(source_names).issubset(
        deploy_status
    ):
        raise SystemExit(
            f"ERROR: live {label} App Framework is missing configured source status: "
            f"live={sorted(deploy_status) if isinstance(deploy_status, dict) else deploy_status!r}, "
            f"reviewed={sorted(source_names)}"
        )
    error_codes = {199, 298, 299, 398, 399}
    has_deployments = False
    for source_name, source_status in deploy_status.items():
        deployments = source_status.get("appDeploymentInfo", [])
        if not isinstance(deployments, list):
            raise SystemExit(
                f"ERROR: live {label} App Framework status for {source_name!r} is malformed"
            )
        has_deployments = has_deployments or bool(deployments)
        for deployment in deployments:
            app_name = deployment.get("appName", "<unknown>")
            # RepoStateDeleted (2) with DeployStatusComplete is the stable
            # post-uninstall record retained by SOK. Both active (1) and
            # completely deleted (2) records are converged; passive/unknown
            # records and any non-complete deployment are not.
            if deployment.get("repoState") not in {1, 2} or deployment.get("deployStatus") != 3:
                raise SystemExit(
                    f"ERROR: live {label} app {app_name!r} is not fully reconciled"
                )
            if source_name not in source_names and deployment.get("repoState") != 2:
                raise SystemExit(
                    f"ERROR: live {label} removed App Framework source "
                    f"{source_name!r} still has active app {app_name!r}"
                )
            phase_infos = [deployment.get("phaseInfo", {})]
            phase_infos.extend(deployment.get("auxPhaseInfo", []))
            for phase_info in phase_infos:
                if not isinstance(phase_info, dict):
                    raise SystemExit(
                        f"ERROR: live {label} app {app_name!r} has malformed phase status"
                    )
                # SOK retains historical failCount values after a successful
                # pod-copy retry, so convergence is defined by the terminal
                # phase/deploy codes rather than requiring failCount == 0.
                if phase_info.get("status") in error_codes:
                    raise SystemExit(
                        f"ERROR: live {label} app {app_name!r} has failed App Framework status"
                    )
            if deployment.get("repoState") == 1 and any(
                phase_info.get("phase") != "install"
                or phase_info.get("status") != 303
                for phase_info in phase_infos
            ):
                raise SystemExit(
                    f"ERROR: live {label} active app {app_name!r} has not reached "
                    "the terminal install/303 phase"
                )
    default_scope = spec_repo.get("defaults", {}).get("scope", "")
    scopes = {source.get("scope") or default_scope for source in sources}
    # Cluster scope always uses the CM/deployer bundle path. PremiumApps uses
    # that path only on SearchHeadCluster; the supported Standalone ES flow is
    # installed locally and deliberately leaves bundlePushStage uninitialized.
    requires_bundle = "cluster" in scopes or (
        "premiumApps" in scopes and item.get("kind") == "SearchHeadCluster"
    )
    if requires_bundle and has_deployments:
        bundle_status = context.get("bundlePushStatus", {})
        if (
            bundle_status.get("bundlePushStage") != 3
            or bundle_status.get("retryCount", 0) != 0
        ):
            raise SystemExit(
                f"ERROR: live {label} App Framework cluster bundle has not converged"
            )


for item_identity, expected in expected_by_identity.items():
    kind, name = item_identity
    label = f"{kind}/{name}"
    live = live_by_identity[item_identity]
    if live.get("apiVersion") != "enterprise.splunk.com/v4":
        raise SystemExit(f"ERROR: live {label} does not use enterprise.splunk.com/v4")
    metadata = live.get("metadata", {})
    annotations = metadata.get("annotations", {})
    if (
        annotations.get("meta.helm.sh/release-name") != release
        or annotations.get("meta.helm.sh/release-namespace") != namespace
    ):
        raise SystemExit(f"ERROR: live {label} has an unexpected Helm owner")
    compare_selected(
        expected.get("metadata", {}).get("labels", {}),
        metadata.get("labels", {}),
        f"{label}.metadata.labels",
        False,
    )
    compare_selected(
        expected.get("metadata", {}).get("annotations", {}),
        annotations,
        f"{label}.metadata.annotations",
        False,
    )
    expected_spec = expected.get("spec", {})
    live_spec = live.get("spec", {})
    spec_schema = spec_schemas.get(kind)
    if not isinstance(spec_schema, dict):
        raise SystemExit(f"ERROR: installed v4 CRD schema is missing for {kind}")
    expected_spec = normalize_with_schema(expected_spec, spec_schema)
    live_spec = normalize_with_schema(live_spec, spec_schema)
    compare_selected(expected_spec, live_spec, f"{label}.spec")
    status = live.get("status", {})
    if kind in reconciled_kinds and status.get("phase") != "Ready":
        raise SystemExit(
            f"ERROR: live {label} is not Ready (phase={status.get('phase')!r})"
        )
    if kind in {"Queue", "ObjectStorage"} and status.get("message") not in (None, ""):
        raise SystemExit(
            f"ERROR: live {label} reports a configuration error: "
            f"{status.get('message')!r}"
        )
    if kind in replicated_kinds:
        replicas = live_spec.get("replicas")
        if status.get("replicas") != replicas or status.get("readyReplicas") != replicas:
            raise SystemExit(
                f"ERROR: live {label} replica status differs: "
                f"spec={replicas}, status={status.get('replicas')}, "
                f"ready={status.get('readyReplicas')}"
            )
    validate_app_framework(live, label)

if queue_secret_version:
    for item_identity in (("IndexerCluster", "idxc"), ("IngestorCluster", "ingestor")):
        item = live_by_identity.get(item_identity)
        if item is None:
            raise SystemExit(f"ERROR: separated-ingestion resource is missing: {item_identity}")
        label = f"{item_identity[0]}/{item_identity[1]}"
        spec = item.get("spec", {})
        status = item.get("status", {})
        if spec.get("serviceAccount") not in (None, "") or status.get("serviceAccount") not in (None, ""):
            raise SystemExit(
                f"ERROR: live {label} must use the reviewed Secret-only SOK 3.1 identity path"
            )
        if status.get("message") not in (None, ""):
            raise SystemExit(
                f"ERROR: live {label} reports a separated-ingestion error: "
                f"{status.get('message')!r}"
            )
        if status.get("credentialSecretVersion") != queue_secret_version:
            raise SystemExit(
                f"ERROR: live {label} has not adopted the reviewed Queue Secret "
                "resourceVersion"
            )
        if item_identity[0] == "IndexerCluster" and (
            status.get("initialized_flag") is not True
            or status.get("indexing_ready_flag") is not True
            or status.get("service_ready_flag") is not True
            or status.get("maintenance_mode") is not False
        ):
            raise SystemExit(
                f"ERROR: live {label} has not converged its separated indexer status"
            )
"""
    enterprise_status_values = (
        "status_values+=(--values enterprise-values-overlay.yaml)"
        if args.enterprise_values_overlay
        else ":"
    )
    external_same_namespace_lm = (
        args.existing_license_manager
        if args.existing_license_manager
        and (args.existing_license_manager_namespace or args.namespace) == args.namespace
        else ""
    )
    queue_secret_version_shell = "queue_secret_version=''"
    if args.indexing_ingestion_separation:
        queue_secret_version_shell = f"""queue_secret_version="$(kubectl --request-timeout=30s get secret {shell_quote(args.queue_secret_ref)} --namespace {shell_quote(args.namespace)} -o jsonpath='{{.metadata.resourceVersion}}')"
[[ -n "${{queue_secret_version}}" ]] || {{ printf 'ERROR: Queue Secret has no resourceVersion.\\n' >&2; exit 1; }}"""
    external_lm_status_shell = ":"
    if args.existing_license_manager and (
        args.existing_license_manager_namespace or args.namespace
    ) != args.namespace:
        external_lm_guard_code = """import json
import sys
item = json.load(sys.stdin)
name, namespace = sys.argv[1:3]
metadata = item.get("metadata", {})
annotations = metadata.get("annotations", {})
generation = metadata.get("generation")
if item.get("apiVersion") != "enterprise.splunk.com/v4" or item.get("kind") != "LicenseManager":
    raise SystemExit("ERROR: external LicenseManager does not use the reviewed v4 API")
if metadata.get("name") != name or metadata.get("namespace") != namespace:
    raise SystemExit("ERROR: external LicenseManager identity differs")
if metadata.get("deletionTimestamp") or metadata.get("ownerReferences"):
    raise SystemExit("ERROR: external LicenseManager is terminating or unexpectedly owned")
if any(key.lower().endswith(".enterprise.splunk.com/paused") for key in annotations):
    raise SystemExit("ERROR: external LicenseManager is paused")
if annotations.get("enterprise.splunk.com/admin-managed-pv") not in (None, "", "false"):
    raise SystemExit("ERROR: external LicenseManager enables unreviewed admin-managed PVs")
if (
    not metadata.get("uid")
    or not metadata.get("resourceVersion")
    or not isinstance(generation, int)
    or isinstance(generation, bool)
    or generation < 1
):
    raise SystemExit("ERROR: external LicenseManager API identity is incomplete")
status = item.get("status", {})
if status.get("phase") != "Ready" or status.get("message") not in (None, ""):
    raise SystemExit("ERROR: external LicenseManager is not cleanly Ready")
if status.get("observedGeneration") not in (None, generation):
    raise SystemExit("ERROR: external LicenseManager status is stale")
"""
        external_lm_namespace = args.existing_license_manager_namespace or args.namespace
        external_lm_status_shell = (
            f"kubectl --request-timeout=30s get licensemanager "
            f"{shell_quote(args.existing_license_manager)} --namespace "
            f"{shell_quote(external_lm_namespace)} -o json | python3 -c "
            f"{shell_quote(external_lm_guard_code)} "
            f"{shell_quote(args.existing_license_manager)} "
            f"{shell_quote(external_lm_namespace)}"
        )
    cr_contract_shell = f"""umask 077
cr_contract_dir="$(mktemp -d "${{TMPDIR:-/tmp}}/splunk-sok-contract.XXXXXX")"
trap 'rm -rf "${{cr_contract_dir}}"' EXIT
status_values=(--values enterprise-values.yaml)
{enterprise_status_values}
{helm_repo_setup}
helm template {shell_quote(args.release_name)} {shell_quote(enterprise_chart_ref)} \\
  --version {shell_quote(chart_version(args))} \\
  --namespace {shell_quote(args.namespace)} \\
  "${{status_values[@]}}" >"${{cr_contract_dir}}/expected.yaml"
python3 -c {shell_quote(collect_live_crs_code)} {shell_quote(args.namespace)} >"${{cr_contract_dir}}/live.json"
{queue_secret_version_shell}
python3 -c {shell_quote(cr_contract_code)} \\
  "${{cr_contract_dir}}/expected.yaml" "${{cr_contract_dir}}/live.json" \\
  {shell_quote(crd_ref if local_artifacts else '')} \\
  {shell_quote(args.release_name)} {shell_quote(args.namespace)} \\
  {shell_quote(external_same_namespace_lm)} "${{queue_secret_version}}"
rm -rf "${{cr_contract_dir}}"
trap - EXIT
"""
    smartstore_secret_status = "printf '%s' '{}'"
    if args.smartstore_secret_ref:
        smartstore_secret_status = (
            "kubectl --request-timeout=30s get secret "
            f"{shell_quote(args.smartstore_secret_ref)} --namespace "
            f"{shell_quote(args.namespace)} -o json | python3 -c "
            f"{shell_quote(compact_json_code)}"
        )
    license_contract = (
        {
            "name": Path(args.license_file).name,
            "sha256": file_sha256(Path(args.license_file)),
        }
        if args.license_file
        else {}
    )
    controller_poll = f"""controller_timeout="${{SOK_STATEFULSET_TIMEOUT_SECONDS:-2700}}"
controller_interval="${{SOK_STATEFULSET_POLL_SECONDS:-10}}"
[[ "${{controller_timeout}}" =~ ^[1-9][0-9]{{0,4}}$ ]] && (( controller_timeout <= 86400 )) || {{ printf 'ERROR: SOK_STATEFULSET_TIMEOUT_SECONDS must be 1..86400.\\n' >&2; exit 1; }}
[[ "${{controller_interval}}" =~ ^[1-9][0-9]{{0,3}}$ ]] && (( controller_interval <= 3600 )) || {{ printf 'ERROR: SOK_STATEFULSET_POLL_SECONDS must be 1..3600.\\n' >&2; exit 1; }}
controller_deadline=$((SECONDS + controller_timeout))
controllers_ready=false
controller_health_input=""
trap 'rm -f -- "${{controller_health_input:-}}"' EXIT
trap 'exit 130' HUP INT TERM
while (( SECONDS < controller_deadline )); do
  controller_health_input="$(mktemp)"
  kubectl --request-timeout=30s get statefulsets --namespace {shell_quote(args.namespace)} -o json | python3 -c {shell_quote(compact_json_code)} >"${{controller_health_input}}"
  printf '\n' >>"${{controller_health_input}}"
  kubectl --request-timeout=30s get standalone,clustermanager,indexercluster,searchheadcluster,licensemanager,monitoringconsole,ingestorcluster --ignore-not-found --namespace {shell_quote(args.namespace)} -o json | python3 -c {shell_quote(compact_json_code)} >>"${{controller_health_input}}"
  printf '\n' >>"${{controller_health_input}}"
  kubectl --request-timeout=30s get configmaps --namespace {shell_quote(args.namespace)} -o json | python3 -c {shell_quote(compact_json_code)} >>"${{controller_health_input}}"
  printf '\n' >>"${{controller_health_input}}"
  {smartstore_secret_status} >>"${{controller_health_input}}"
  if python3 -c {shell_quote(controller_health_code)} {shell_quote(json.dumps(expected_controllers, sort_keys=True))} {shell_quote(splunk_image(args))} {shell_quote(json.dumps(VERIFIED_SOK_PROBE_SHA256.get(args.operator_version, {}), sort_keys=True))} {shell_quote(args.namespace)} {shell_quote(SGT_ACCEPTANCE if args.accept_splunk_general_terms else '')} {shell_quote(json.dumps(license_contract, sort_keys=True))} <"${{controller_health_input}}"; then
    controllers_ready=true
    rm -f "${{controller_health_input}}"
    controller_health_input=""
    break
  fi
  rm -f "${{controller_health_input}}"
  controller_health_input=""
  remaining=$((controller_deadline - SECONDS))
  (( remaining > 0 )) || break
  sleep_for=$(( controller_interval < remaining ? controller_interval : remaining ))
  sleep "${{sleep_for}}"
done
trap - EXIT HUP INT TERM
[[ "${{controllers_ready}}" == true ]] || {{ printf 'ERROR: reviewed Splunk StatefulSets did not converge within %s seconds.\\n' "${{controller_timeout}}" >&2; exit 1; }}
"""
    smartstore_adoption_shell = ""
    if args.smartstore_bucket and args.architecture != "s1":
        smartstore_adoption_shell = f"""smartstore_config_token="$(kubectl --request-timeout=30s get configmap splunk-cm-clustermanager-smartstore --namespace {shell_quote(args.namespace)} -o jsonpath='{{.data.conftoken}}')"
smartstore_mounted_token="$(kubectl --request-timeout=30s exec splunk-cm-cluster-manager-0 --namespace {shell_quote(args.namespace)} --container splunk -- cat /mnt/splunk-operator/local/conftoken)"
[[ "${{smartstore_config_token}}" =~ ^[1-9][0-9]*$ && "${{smartstore_mounted_token}}" == "${{smartstore_config_token}}" ]] || {{ printf 'ERROR: Cluster Manager SmartStore ConfigMap is not mounted at the reviewed revision.\\n' >&2; exit 1; }}
"""
    license_manager_name = ""
    if args.license_file and args.architecture != "s1":
        license_manager_name = "lm"
    elif args.existing_license_manager:
        license_manager_name = args.existing_license_manager
    license_event_code = """import json
import sys

license_manager = json.loads(sys.stdin.readline())
events = json.loads(sys.stdin.read()).get("items", [])
metadata = license_manager.get("metadata", {})
if (
    license_manager.get("apiVersion") != "enterprise.splunk.com/v4"
    or license_manager.get("kind") != "LicenseManager"
    or metadata.get("name") != sys.argv[1]
    or metadata.get("namespace") != sys.argv[2]
    or not metadata.get("uid")
):
    raise SystemExit("ERROR: LicenseManager identity is invalid for event validation")
for event in events:
    reference = event.get("involvedObject") or event.get("regarding") or {}
    if (
        event.get("type") == "Warning"
        and event.get("reason") == "LicenseExpired"
        and reference.get("apiVersion") == "enterprise.splunk.com/v4"
        and reference.get("kind") == "LicenseManager"
        and reference.get("name") == metadata.get("name")
        and reference.get("namespace", sys.argv[2]) == sys.argv[2]
        and reference.get("uid") == metadata.get("uid")
    ):
        raise SystemExit("ERROR: the reviewed LicenseManager reports an expired license")
"""
    license_event_shell = ""
    if license_manager_name:
        license_event_shell = f"""license_event_input="$(mktemp)"
trap 'rm -f -- "${{license_event_input}}"' EXIT
kubectl --request-timeout=30s get licensemanager {shell_quote(license_manager_name)} --namespace {shell_quote(args.namespace)} -o json | python3 -c {shell_quote(compact_json_code)} >"${{license_event_input}}"
printf '\n' >>"${{license_event_input}}"
kubectl --request-timeout=30s get events --namespace {shell_quote(args.namespace)} -o json | python3 -c {shell_quote(compact_json_code)} >>"${{license_event_input}}"
python3 -c {shell_quote(license_event_code)} {shell_quote(license_manager_name)} {shell_quote(args.namespace)} <"${{license_event_input}}"
rm -f "${{license_event_input}}"
trap - EXIT
"""
    emit(
        "status.sh",
        make_script(
            f"""python3 bundle-verify.py verify . sok
{kubeconfig_prefix}{cluster_guard}helm status {shell_quote(args.operator_release_name)} --namespace {shell_quote(args.operator_namespace)} -o json | python3 -c {shell_quote(helm_status_guard)} {shell_quote(args.operator_release_name)}
helm status {shell_quote(args.release_name)} --namespace {shell_quote(args.namespace)} -o json | python3 -c {shell_quote(helm_status_guard)} {shell_quote(args.release_name)}
helm list --all --namespace {shell_quote(args.operator_namespace)} -o json | python3 -c {shell_quote(helm_list_guard)} {shell_quote(args.operator_release_name)} {shell_quote(args.operator_namespace)} {shell_quote('splunk-operator-' + chart_version(args))}
helm list --all --namespace {shell_quote(args.namespace)} -o json | python3 -c {shell_quote(helm_list_guard)} {shell_quote(args.release_name)} {shell_quote(args.namespace)} {shell_quote('splunk-enterprise-' + chart_version(args))}
kubectl rollout status deployment/splunk-operator-controller-manager --namespace {shell_quote(args.operator_namespace)} --timeout=10m
{operator_health_shell}
{operator_contract_shell}
{external_lm_status_shell}
{chr(10).join(cr_wait_lines)}
{cr_contract_shell}
{controller_poll}
{smartstore_adoption_shell}
{enterprise_service_shell}
{pvc_health_shell}
{placement_health_shell}
{pod_health_shell}
{license_event_shell}
kubectl get standalone,clustermanager,indexercluster,searchheadcluster,licensemanager,monitoringconsole,ingestorcluster,queue,objectstorage --ignore-not-found --namespace {shell_quote(args.namespace)} -o wide
kubectl get pods --namespace {shell_quote(args.operator_namespace)} -o wide
kubectl get pods --namespace {shell_quote(args.namespace)} -o wide
kubectl get events --namespace {shell_quote(args.namespace)} --sort-by=.lastTimestamp
"""
        ),
        executable=True,
    )
    write_bundle_manifest(
        render_dir,
        assets,
        [
            args.license_file,
        ],
    )
    return assets


def pod_profile(args: argparse.Namespace) -> str:
    return args.pod_profile


def pod_base_profile(profile: str) -> str:
    return re.sub(r"-(?:es|itsi)$", "", profile)


def pod_is_es(profile: str) -> bool:
    return profile.endswith("-es")


def pod_is_itsi(profile: str) -> bool:
    return profile.endswith("-itsi")


def pod_has_secondary_search(profile: str) -> bool:
    return pod_is_es(profile) or pod_is_itsi(profile)


def example_ips(start: int, count: int) -> list[str]:
    return [f"10.10.10.{item}" for item in range(start, start + count)]


def pod_counts(profile: str) -> tuple[int, int]:
    base_profile = pod_base_profile(profile)
    base_workers = {
        "pod-small": 8,
        "pod-medium": 11,
        "pod-large": 15,
        "pod-xlarge": 30,
    }[base_profile]
    return 3, base_workers + (
        1 if base_profile == "pod-small" else 3
    ) if pod_has_secondary_search(profile) else base_workers


def pod_role_comment(profile: str, index: int) -> str:
    base_profile = pod_base_profile(profile)
    secondary = pod_has_secondary_search(profile)
    premium_label = "Enterprise Security" if pod_is_es(profile) else "ITSI"
    if base_profile == "pod-small":
        if index == 0:
            return "Search head C225"
        if secondary and index == 1:
            return f"{premium_label} search head C225"
        if index <= (4 if secondary else 3):
            return "Indexer C245"
        return "Volume C245"
    if index <= 2:
        return "Search head C225"
    if secondary and index <= 5:
        return f"{premium_label} search head C225"
    indexer_count = {
        "pod-medium": 4,
        "pod-large": 7,
        "pod-xlarge": 17,
    }[base_profile]
    last_indexer = (5 if secondary else 2) + indexer_count
    if index <= last_indexer:
        return "Indexer C245"
    return "Volume C245"


def render_yaml_path_list(items: Iterable[str], indent: str) -> list[str]:
    values = list(items)
    if not values:
        return [f"{indent}[]"]
    return [f"{indent}- {yaml_quote(item)}" for item in values]


def render_pod_config(args: argparse.Namespace) -> str:
    profile = pod_profile(args)
    controller_count, worker_count = pod_counts(profile)
    controllers = split_csv(args.controller_ips) or example_ips(1, controller_count)
    workers = split_csv(args.worker_ips) or example_ips(
        1 + controller_count, worker_count
    )
    license_files = split_csv(args.license_file) or ["/path/to/splunk.lic"]
    indexer_apps = split_csv(args.indexer_apps)
    cluster_manager_apps = split_csv(args.cluster_manager_apps)
    search_apps = split_csv(args.search_apps)
    search_deployer_apps = split_csv(args.search_deployer_apps)
    standalone_apps = split_csv(args.standalone_apps)
    license_manager_apps = split_csv(args.license_manager_apps)
    premium_apps = split_csv(args.premium_apps)
    itsi_apps = split_csv(args.itsi_apps)
    base_profile = pod_base_profile(profile)
    es_profile = pod_is_es(profile)
    itsi_profile = pod_is_itsi(profile)
    primary_name = args.primary_search_name or (
        "core-sh" if base_profile == "pod-small" else "core-shc"
    )
    secondary_name = args.secondary_search_name or (
        ("es-sh" if es_profile else "itsi-sh")
        if base_profile == "pod-small"
        else ("es-shc" if es_profile else "itsi-shc")
    )

    lines = [
        "---",
        "apiVersion: enterprise.splunk.com/v1beta1",
        "kind: KubernetesCluster",
        f"profile: {base_profile}",
        "licenses:",
        *render_yaml_path_list(license_files, "  "),
        "ssh:",
        f"  user: {yaml_quote(args.ssh_user)}",
        f"  privateKey: {yaml_quote(args.ssh_private_key_file)}",
    ]
    if args.ingress_certificate_file:
        lines.extend(
            [
                "certificate:",
                "  ingress:",
                f"    certificate: {yaml_quote(args.ingress_certificate_file)}",
                f"    privateKey: {yaml_quote(args.ingress_private_key_file)}",
            ]
        )
    lines.append("controllers:")
    for index, address in enumerate(controllers, start=1):
        lines.append(f"  - address: {yaml_quote(address)} # Controller C225")
    lines.append("workers:")
    for index, address in enumerate(workers):
        lines.append(
            f"  - address: {yaml_quote(address)} # {pod_role_comment(profile, index)}"
        )
    lines.extend(
        [
            "clustermanager:",
            "  apps:",
            "    cluster:",
            *render_yaml_path_list(indexer_apps, "      "),
            "    local:",
            *render_yaml_path_list(cluster_manager_apps, "      "),
        ]
    )
    if license_manager_apps:
        lines.extend(
            [
                "licensemanager:",
                "  apps:",
                "    local:",
                *render_yaml_path_list(license_manager_apps, "      "),
            ]
        )
    if base_profile == "pod-small":
        lines.extend(
            [
                "standalone:",
                f"  - name: {yaml_quote(primary_name)}",
                "    apps:",
                "      local:",
                *render_yaml_path_list(standalone_apps, "        "),
            ]
        )
        if pod_has_secondary_search(profile):
            lines.extend(
                [
                    f"  - name: {yaml_quote(secondary_name)}",
                    "    apps:",
                    "      local:",
                    *render_yaml_path_list(
                        itsi_apps if itsi_profile else [], "        "
                    ),
                ]
            )
            if es_profile:
                lines.extend(
                    [
                        "      premium:",
                        *render_yaml_path_list(premium_apps, "        "),
                    ]
                )
    else:
        lines.extend(
            [
                "searchheadcluster:",
                f"  - name: {yaml_quote(primary_name)}",
                "    apps:",
                "      cluster:",
                *render_yaml_path_list(search_apps, "        "),
                "      local:",
                *render_yaml_path_list(search_deployer_apps, "        "),
            ]
        )
        if pod_has_secondary_search(profile):
            lines.extend(
                [
                    f"  - name: {yaml_quote(secondary_name)}",
                    "    apps:",
                    "      cluster:",
                    *render_yaml_path_list(
                        itsi_apps if itsi_profile else [], "        "
                    ),
                    "      local:",
                    "        []",
                ]
            )
            if es_profile:
                lines.extend(
                    [
                        "      premium:",
                        *render_yaml_path_list(premium_apps, "        "),
                    ]
                )
    return "\n".join(lines) + "\n"


def render_pod_readme(args: argparse.Namespace) -> str:
    profile = pod_profile(args)
    base_profile = pod_base_profile(profile)
    return f"""# Splunk POD Rendered Assets

Target: Splunk POD on Cisco UCS with the Splunk Kubernetes Installer

## Key files

- `cluster-config.yaml`
- `bundle-verify.py`
- `preflight.sh`
- `deploy.sh`
- `status-workers.sh`
- `status.sh`
- `wait-ready.sh`
- `get-creds.sh`
- `web-docs.sh`
- `diagnostics.sh`
- `pod-artifacts.py`
- `pod-inputs.py`
- `bundle-manifest.json`

A hash-reviewed `kubernetes-installer-reviewed` snapshot is added when a
concrete installer is supplied.

Run the repository validator before live use. Live phases require concrete
node addresses, immutable search-tier names, local license/app/key files, and
the exact coupled installer binary. `deploy.sh` refreshes only the
`cluster-config.yaml` hash if the installer records terms acceptance.

The installer prompts for Terms and Conditions acceptance during the first
deployment. If it writes `termsConditionsAccepted: true`, remove that field
only from a separate copy made for sharing; editing the reviewed bundle causes
its integrity gate to fail.

Requested profile: `{profile}`.
Installer profile rendered in `cluster-config.yaml`: `{base_profile}`.
Coupled POD bundle: `{args.pod_version}`.
Controllers: `{pod_counts(profile)[0]}`. Workers: `{pod_counts(profile)[1]}`.
"""


def render_pod_assets(args: argparse.Namespace, render_dir: Path) -> list[str]:
    assets: list[str] = []

    def emit(rel: str, content: str, executable: bool = False) -> None:
        write_file(render_dir / rel, content, executable=executable)
        assets.append(rel)

    concrete_installer = (
        args.installer_path != "/path/to/kubernetes-installer-standalone"
        and Path(args.installer_path).expanduser().is_file()
    )
    reviewed_installer_rel = "kubernetes-installer-reviewed"
    if concrete_installer:
        stage_reviewed_executable(
            Path(args.installer_path).expanduser(),
            render_dir / reviewed_installer_rel,
            args.installer_sha256,
        )
        assets.append(reviewed_installer_rel)
        installer = shell_quote(f"./{reviewed_installer_rel}")
    else:
        installer = shell_quote(args.installer_path)
    external_files = [
        *split_csv(args.license_file),
        args.ssh_private_key_file,
        *split_csv(args.indexer_apps),
        *split_csv(args.cluster_manager_apps),
        *split_csv(args.search_apps),
        *split_csv(args.search_deployer_apps),
        *split_csv(args.standalone_apps),
        *split_csv(args.premium_apps),
        *split_csv(args.itsi_apps),
        args.itsi_source_bundle,
        *split_csv(args.license_manager_apps),
        args.ingress_certificate_file,
        args.ingress_private_key_file,
        args.ingress_ca_file,
    ]
    external_input_paths = {
        raw: canonical_file(raw)
        for raw in external_files
        if raw
        and not raw.startswith("/path/to/")
        and Path(raw).expanduser().is_file()
    }
    pod_timeout_prelude = """command -v timeout >/dev/null || { printf 'ERROR: GNU timeout is required on the POD bastion.\\n' >&2; exit 1; }
validate_timeout_value() {
  local name="$1" value="$2" maximum="$3"
  [[ "${value}" =~ ^[1-9][0-9]{0,5}$ ]] && (( value <= maximum )) || {
    printf 'ERROR: %s must be an integer from 1 through %s.\\n' "${name}" "${maximum}" >&2
    exit 1
  }
}
run_timed() {
  local seconds="$1"
  shift
  timeout --signal=TERM --kill-after=10s "${seconds}s" "$@"
}
"""
    pod_stage_prelude = """stage_dir=""
cleanup_stage() {
  if [[ -n "${stage_dir}" && -d "${stage_dir}" ]]; then
    rm -rf -- "${stage_dir}"
  fi
}
stage_inputs() {
  umask 077
  stage_dir="$(mktemp -d "${TMPDIR:-/tmp}/splunk-pod-inputs.XXXXXX")"
  chmod 0700 "${stage_dir}"
  trap cleanup_stage EXIT HUP INT TERM
  python3 pod-inputs.py stage . "${stage_dir}"
}
"""
    profile = pod_profile(args)
    base_profile = pod_base_profile(profile)
    bundled_splunk, installer_version = pod_bundle_tuple(args.pod_version)
    bundled_splunk_text = ".".join(str(item) for item in bundled_splunk)
    installer_version_text = ".".join(str(item) for item in installer_version)
    commit_config_code = """import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

candidate_path = Path(sys.argv[1])
config_path = Path("cluster-config.yaml")
manifest_path = Path("bundle-manifest.json")
before = config_path.read_text(encoding="utf-8")
candidate = candidate_path.read_text(encoding="utf-8")
term = re.compile(r"^termsConditionsAccepted:\\s*true\\s*$")

def normalize(text):
    lines = text.splitlines()
    terms = [line for line in lines if line.startswith("termsConditionsAccepted:")]
    if any(not term.fullmatch(line) for line in terms) or len(terms) > 1:
        raise SystemExit("ERROR: installer wrote an invalid termsConditionsAccepted field")
    return "\\n".join(line for line in lines if not term.fullmatch(line))

if normalize(before) != normalize(candidate):
    raise SystemExit(
        "ERROR: installer changed cluster-config.yaml beyond the allowed "
        "termsConditionsAccepted: true field; reviewed config was preserved"
    )
if candidate == before:
    raise SystemExit(0)

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
manifest["files"]["cluster-config.yaml"] = hashlib.sha256(
    candidate.encode("utf-8")
).hexdigest()
new_manifest = json.dumps(manifest, indent=2, sort_keys=True) + "\\n"

def atomic_write(path, content, mode):
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

old_mode = config_path.stat().st_mode & 0o777
try:
    atomic_write(config_path, candidate, old_mode)
    atomic_write(manifest_path, new_manifest, manifest_path.stat().st_mode & 0o777)
except BaseException:
    atomic_write(config_path, before, old_mode)
    raise
"""
    expected_pod_roles = {
        "indexer": {
            "pod-small": 3,
            "pod-medium": 4,
            "pod-large": 7,
            "pod-xlarge": 17,
        }[base_profile],
        "search": (1 if base_profile == "pod-small" else 3)
        * (2 if pod_has_secondary_search(profile) else 1),
        "cluster_manager": 1,
        "license_manager": 1,
        "monitoring_console": 1,
        "deployer": (
            0
            if base_profile == "pod-small"
            else (2 if pod_has_secondary_search(profile) else 1)
        ),
    }
    pod_health_code = """import json
import os
import re
import sys

expected = int(sys.argv[1])
expected_roles = json.loads(sys.argv[2])
workers = os.environ.get("POD_WORKERS_STATUS", "")
pods = os.environ.get("POD_PODS_STATUS", "")
worker_rows = []
for line in workers.splitlines():
    match = re.match(r"^\\s*(\\S+)\\s+(Ready|NotReady|Unknown)(?:\\s|$)", line, re.IGNORECASE)
    if match:
        worker_rows.append((match.group(1), match.group(2).lower()))
if (
    len(worker_rows) != expected
    or len({name for name, _ in worker_rows}) != expected
    or any(status != "ready" for _, status in worker_rows)
):
    raise SystemExit(1)
pod_rows = []
for line in pods.splitlines():
    if not line.strip():
        continue
    match = re.match(
        r"^\\s*(?:(?:[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?)\\s+)?"
        r"(\\S+)\\s+(\\d+)/(\\d+)\\s+(\\S+)(?:\\s|$)",
        line,
    )
    if match:
        pod_rows.append(
            (match.group(1), int(match.group(2)), int(match.group(3)), match.group(4))
        )
    elif re.search(r"(?:^|\\s)\\d+/\\d+(?:\\s|$)", line):
        raise SystemExit(1)
if len(pod_rows) < expected:
    raise SystemExit(1)
if any(
    not (
        (total >= 1 and ready == total and status.lower() == "running")
        or (ready == 0 and total >= 1 and status.lower() in {"completed", "succeeded"})
    )
    for _, ready, total, status in pod_rows
):
    raise SystemExit(1)
roles = {name: 0 for name in expected_roles}
for name, ready, total, status in pod_rows:
    if status.lower() != "running" or ready != total:
        continue
    normalized = name.lower()
    if re.fullmatch(r"splunk-[a-z0-9.-]+-indexer-[0-9]+", normalized):
        roles["indexer"] += 1
    elif re.fullmatch(
        r"splunk-[a-z0-9.-]+-cluster-manager-[0-9]+", normalized
    ):
        roles["cluster_manager"] += 1
    elif re.fullmatch(
        r"splunk-[a-z0-9.-]+-license-manager-[0-9]+", normalized
    ):
        roles["license_manager"] += 1
    elif re.fullmatch(
        r"splunk-[a-z0-9.-]+-monitoring-console-[0-9]+", normalized
    ):
        roles["monitoring_console"] += 1
    elif re.fullmatch(r"splunk-[a-z0-9.-]+-deployer-[0-9]+", normalized):
        roles["deployer"] += 1
    elif re.fullmatch(
        r"splunk-[a-z0-9.-]+-(?:standalone|search-head)-[0-9]+", normalized
    ):
        roles["search"] += 1
if roles != expected_roles:
    raise SystemExit(1)
"""
    pod_version_guard_code = r'''import re,sys
text = sys.stdin.read()
wanted_installer, wanted_splunk = sys.argv[1:3]
def exact(label):
    values = re.findall(rf"^{re.escape(label)}:[ \t]*([^\s]+)[ \t]*$", text, re.MULTILINE)
    if len(values) != 1:
        raise SystemExit(f"ERROR: expected one exact {label} field in installer output")
    return values[0]
if exact("Version") != wanted_installer:
    raise SystemExit("ERROR: POD installer version does not match the reviewed bundle")
if exact("Splunk Version") != wanted_splunk:
    raise SystemExit("ERROR: bundled Splunk version does not match the reviewed bundle")
'''
    installer_hash_code = '''import hashlib,sys
digest = hashlib.sha256()
with open(sys.argv[1], "rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
'''
    installer_digest_check = (
        "python3 bundle-verify.py verify . pod\n"
        f"python3 -c {shell_quote(installer_hash_code)} "
        f"{installer} | grep -Fx {shell_quote(args.installer_sha256.lower())} >/dev/null"
        if args.installer_sha256
        else "printf 'ERROR: reviewed POD installer SHA-256 is missing.\\n' >&2; exit 1"
    )
    emit("README.md", render_pod_readme(args))
    emit(
        "metadata.json",
        json.dumps(
            {
                "target": "pod",
                "pod_profile": profile,
                "pod_base_profile": base_profile,
                "controller_count": pod_counts(profile)[0],
                "worker_count": pod_counts(profile)[1],
                "pod_version": args.pod_version,
                "bundled_splunk_version": bundled_splunk_text,
                "installer_version": installer_version_text,
                "installer_path": args.installer_path,
                "reviewed_installer_bundle_path": (
                    reviewed_installer_rel if concrete_installer else None
                ),
                "installer_sha256": args.installer_sha256.lower() or None,
                "ssh_private_key_file": args.ssh_private_key_file,
                "external_input_paths": external_input_paths,
                "license_files": split_csv(args.license_file),
                "indexer_apps": split_csv(args.indexer_apps),
                "cluster_manager_apps": split_csv(args.cluster_manager_apps),
                "search_apps": split_csv(args.search_apps),
                "search_deployer_apps": split_csv(args.search_deployer_apps),
                "standalone_apps": split_csv(args.standalone_apps),
                "premium_apps": split_csv(args.premium_apps),
                "itsi_apps": split_csv(args.itsi_apps),
                "itsi_source_bundle": args.itsi_source_bundle or None,
                "itsi_source_sha256": args.itsi_source_sha256.lower() or None,
                "itsi_jdk_sha256": args.itsi_jdk_sha256.lower() or None,
                "license_manager_apps": split_csv(args.license_manager_apps),
                "ingress_certificate_file": args.ingress_certificate_file or None,
                "ingress_private_key_file": args.ingress_private_key_file or None,
                "ingress_domain": args.ingress_domain or None,
                "ingress_ca_file": args.ingress_ca_file or None,
                "allow_upgrade": args.allow_upgrade,
                "confirm_new_pod_install": args.confirm_new_pod_install,
                "support_matrix_source": "https://help.splunk.com/en/splunk-enterprise/splunk-pod-guide/10.4/splunk-pod-release-notes",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    emit("cluster-config.yaml", render_pod_config(args))
    emit(
        "pod-artifacts.py",
        Path(__file__).with_name("pod_artifacts.py").read_text(encoding="utf-8"),
        executable=True,
    )
    emit(
        "pod-inputs.py",
        Path(__file__).with_name("pod_inputs.py").read_text(encoding="utf-8"),
        executable=True,
    )
    emit(
        "bundle-verify.py",
        Path(__file__).with_name("bundle_verify.py").read_text(encoding="utf-8"),
        executable=True,
    )
    emit(
        "preflight.sh",
        make_script(
            f"""python3 bundle-verify.py verify . pod
command -v python3 >/dev/null
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else "ERROR: Python 3.9+ is required.")'
{pod_timeout_prelude}{pod_stage_prelude}call_timeout="${{POD_INSTALLER_CALL_TIMEOUT_SECONDS:-300}}"
validate_timeout_value POD_INSTALLER_CALL_TIMEOUT_SECONDS "${{call_timeout}}" 3600
stage_inputs
python3 pod-artifacts.py "${{stage_dir}}/metadata.json"
[[ -x {
                installer
            } ]] || {{ printf 'ERROR: POD installer is missing or not executable: %s\\n' {
                shell_quote(args.installer_path)
            } >&2; exit 1; }}
{installer_digest_check}
version_output="$(run_timed "${{call_timeout}}" {installer} -version)"
printf '%s\\n' "${{version_output}}"
python3 -c {
                shell_quote(pod_version_guard_code)
            } {shell_quote(installer_version_text)} {
                shell_quote(bundled_splunk_text)
            } <<<"${{version_output}}"
run_timed "${{call_timeout}}" {installer} -static.cluster "${{stage_dir}}/cluster-config.yaml" -preflightcheck.only
"""
        ),
        executable=True,
    )
    emit(
        "deploy.sh",
        make_script(
            f"""{installer_digest_check}
{pod_timeout_prelude}{pod_stage_prelude}call_timeout="${{POD_INSTALLER_CALL_TIMEOUT_SECONDS:-300}}"
deploy_timeout="${{POD_DEPLOY_TIMEOUT_SECONDS:-14400}}"
validate_timeout_value POD_INSTALLER_CALL_TIMEOUT_SECONDS "${{call_timeout}}" 3600
validate_timeout_value POD_DEPLOY_TIMEOUT_SECONDS "${{deploy_timeout}}" 86400
stage_inputs
python3 pod-artifacts.py "${{stage_dir}}/metadata.json"
version_output="$(run_timed "${{call_timeout}}" {installer} -version)"
python3 -c {shell_quote(pod_version_guard_code)} {shell_quote(installer_version_text)} {shell_quote(bundled_splunk_text)} <<<"${{version_output}}"
run_timed "${{call_timeout}}" {installer} -static.cluster "${{stage_dir}}/cluster-config.yaml" -preflightcheck.only
if [[ {bool_word(args.allow_upgrade)} == true ]]; then
  printf 'ERROR: Automated POD upgrade/app reconciliation is intentionally disabled because the official installer does not expose a documented machine-readable topology/version identity. Use the rendered preflight evidence with the official lockstep upgrade runbook and vendor review.\\n' >&2
  exit 1
fi
if [[ {bool_word(args.confirm_new_pod_install)} != true ]]; then
  printf 'ERROR: New POD deployment requires a reviewed --confirm-new-pod-install bundle; the installer does not document a machine-readable cluster-absence contract.\\n' >&2
  exit 1
fi
status_output=""
if status_output="$(run_timed "${{call_timeout}}" {installer} -static.cluster "${{stage_dir}}/cluster-config.yaml" -status 2>&1)"; then
  if [[ {bool_word(args.allow_upgrade)} != true ]]; then
    printf 'ERROR: An existing POD cluster was detected; rerender with --allow-upgrade after backup and lockstep upgrade review.\\n' >&2
    exit 1
  fi
elif [[ {bool_word(args.allow_upgrade)} == true ]]; then
  printf 'ERROR: Cannot verify the existing POD cluster before upgrade.\\n%s\\n' "${{status_output}}" >&2
  exit 1
elif ! grep -Eqi '(^|[[:space:]])(no deployed cluster|cluster (has not been|is not) deployed|cluster does not exist)([[:space:]]|$)' <<<"${{status_output}}"; then
  printf 'ERROR: POD status failed without a recognized new-cluster result; refusing deploy.\\n%s\\n' "${{status_output}}" >&2
  exit 1
fi
work_config="${{stage_dir}}/cluster-config.yaml"
run_timed "${{deploy_timeout}}" {installer} -static.cluster "${{work_config}}" -deploy
python3 pod-inputs.py restore "${{work_config}}" "${{stage_dir}}/path-map.json"
python3 -c {shell_quote(commit_config_code)} "${{work_config}}"
"""
        ),
        executable=True,
    )
    emit(
        "status-workers.sh",
        make_script(
            f"{installer_digest_check}\n{pod_timeout_prelude}{pod_stage_prelude}stage_inputs\ncall_timeout=\"${{POD_INSTALLER_CALL_TIMEOUT_SECONDS:-300}}\"\nvalidate_timeout_value POD_INSTALLER_CALL_TIMEOUT_SECONDS \"${{call_timeout}}\" 3600\nrun_timed \"${{call_timeout}}\" {installer} -static.cluster \"${{stage_dir}}/cluster-config.yaml\" -status.workers\n"
        ),
        executable=True,
    )
    emit(
        "status.sh",
        make_script(
            f"{installer_digest_check}\n{pod_timeout_prelude}{pod_stage_prelude}stage_inputs\ncall_timeout=\"${{POD_INSTALLER_CALL_TIMEOUT_SECONDS:-300}}\"\nvalidate_timeout_value POD_INSTALLER_CALL_TIMEOUT_SECONDS \"${{call_timeout}}\" 3600\nrun_timed \"${{call_timeout}}\" {installer} -static.cluster \"${{stage_dir}}/cluster-config.yaml\" -status\n"
        ),
        executable=True,
    )
    emit(
        "wait-ready.sh",
        make_script(
            f"""{installer_digest_check}
{pod_timeout_prelude}{pod_stage_prelude}stage_inputs
timeout_seconds="${{POD_READY_TIMEOUT_SECONDS:-1800}}"
interval_seconds="${{POD_READY_POLL_SECONDS:-30}}"
call_timeout="${{POD_INSTALLER_CALL_TIMEOUT_SECONDS:-120}}"
validate_timeout_value POD_READY_TIMEOUT_SECONDS "${{timeout_seconds}}" 86400
validate_timeout_value POD_READY_POLL_SECONDS "${{interval_seconds}}" 3600
validate_timeout_value POD_INSTALLER_CALL_TIMEOUT_SECONDS "${{call_timeout}}" 3600
deadline=$((SECONDS + timeout_seconds))
last_workers=""
last_pods=""
while (( SECONDS < deadline )); do
  workers_ok=false
  pods_ok=false
  remaining=$((deadline - SECONDS))
  (( remaining > 0 )) || break
  this_call=$(( call_timeout < remaining ? call_timeout : remaining ))
  if last_workers="$(run_timed "${{this_call}}" {installer} -static.cluster "${{stage_dir}}/cluster-config.yaml" -status.workers 2>&1)"; then workers_ok=true; fi
  remaining=$((deadline - SECONDS))
  (( remaining > 0 )) || break
  this_call=$(( call_timeout < remaining ? call_timeout : remaining ))
  if last_pods="$(run_timed "${{this_call}}" {installer} -static.cluster "${{stage_dir}}/cluster-config.yaml" -status 2>&1)"; then pods_ok=true; fi
  if [[ "${{workers_ok}}" == true && "${{pods_ok}}" == true ]] \
     && POD_WORKERS_STATUS="${{last_workers}}" POD_PODS_STATUS="${{last_pods}}" \
        python3 -c {shell_quote(pod_health_code)} {pod_counts(profile)[1]} {shell_quote(json.dumps(expected_pod_roles, sort_keys=True))}; then
    printf '%s\\n' "${{last_workers}}" "${{last_pods}}"
    exit 0
  fi
  remaining=$((deadline - SECONDS))
  (( remaining > 0 )) || break
  sleep_for=$(( interval_seconds < remaining ? interval_seconds : remaining ))
  sleep "${{sleep_for}}"
done
printf 'ERROR: Splunk POD did not converge within %s seconds.\\n' "${{timeout_seconds}}" >&2
printf '%s\\n' "${{last_workers}}" "${{last_pods}}" >&2
exit 1
"""
        ),
        executable=True,
    )
    emit(
        "get-creds.sh",
        make_script(
            f"{installer_digest_check}\n{pod_timeout_prelude}{pod_stage_prelude}stage_inputs\ncall_timeout=\"${{POD_INSTALLER_CALL_TIMEOUT_SECONDS:-300}}\"\nvalidate_timeout_value POD_INSTALLER_CALL_TIMEOUT_SECONDS \"${{call_timeout}}\" 3600\nrun_timed \"${{call_timeout}}\" {installer} -static.cluster \"${{stage_dir}}/cluster-config.yaml\" -get.creds\n"
        ),
        executable=True,
    )
    emit(
        "web-docs.sh",
        make_script(
            f"""{installer_digest_check}
python3 pod-inputs.py verify .
port="${{WEB_PORT:-8080}}"
printf 'Starting Splunk POD local documentation server.\\n'
printf 'Open http://<BASTION_IP>:%s/docs from a browser that can reach the bastion.\\n' "${{port}}"
exec {installer} --web --web.port "${{port}}"
"""
        ),
        executable=True,
    )
    emit(
        "diagnostics.sh",
        make_script(
            f"""{installer_digest_check}
{pod_timeout_prelude}{pod_stage_prelude}stage_inputs
umask 077
printf 'WARNING: POD logs and diag bundles can contain sensitive configuration. Store and share them securely.\\n' >&2
call_timeout="${{POD_DIAGNOSTICS_TIMEOUT_SECONDS:-3600}}"
validate_timeout_value POD_DIAGNOSTICS_TIMEOUT_SECONDS "${{call_timeout}}" 14400
bundle_dir="${{PWD}}"
diagnostics_parent="${{POD_DIAGNOSTICS_PARENT:-${{TMPDIR:-/tmp}}}}"
[[ -d "${{diagnostics_parent}}" && ! -L "${{diagnostics_parent}}" ]] || {{ printf 'ERROR: POD_DIAGNOSTICS_PARENT must be a real directory.\\n' >&2; exit 1; }}
diagnostics_dir="$(mktemp -d "${{diagnostics_parent%/}}/splunk-pod-diagnostics.XXXXXX")"
chmod 0700 "${{diagnostics_dir}}"
printf 'Writing sensitive POD diagnostics under %s\\n' "${{diagnostics_dir}}" >&2
cd "${{diagnostics_dir}}"
run_timed "${{call_timeout}}" "${{bundle_dir}}/kubernetes-installer-reviewed" -static.cluster "${{stage_dir}}/cluster-config.yaml" -get.logs
run_timed "${{call_timeout}}" "${{bundle_dir}}/kubernetes-installer-reviewed" -static.cluster "${{stage_dir}}/cluster-config.yaml" -get.diag
"""
        ),
        executable=True,
    )
    write_bundle_manifest(render_dir, assets, external_files)
    return assets


def command_plan(
    args: argparse.Namespace, render_dir: Path
) -> dict[str, list[list[str]]]:
    if args.target == "sok":
        return {
            "preflight": [["./preflight.sh"]],
            "apply": [["./apply.sh"]],
            "status": [["./status.sh"]],
        }
    return {
        "preflight": [["./preflight.sh"]],
        "apply": [["./deploy.sh"]],
        "status": [["./wait-ready.sh"]],
    }


def remove_path_without_following(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def directory_snapshot(path: Path) -> tuple | None:
    """Capture a no-follow identity/content snapshot for an owned bundle directory."""
    if not path.exists() and not path.is_symlink():
        return None
    root_stat = path.lstat()
    if path.is_symlink() or not path.is_dir():
        return ("non-directory", root_stat.st_dev, root_stat.st_ino, root_stat.st_mode)
    entries = []
    for child in sorted(path.iterdir(), key=lambda item: item.name):
        child_stat = child.lstat()
        if child.is_symlink():
            detail = ("symlink", os.readlink(child))
        elif child.is_file():
            detail = ("file", child_stat.st_size, child_stat.st_mtime_ns, file_sha256(child))
        elif child.is_dir():
            detail = ("directory", directory_snapshot(child))
        else:
            detail = ("other",)
        entries.append(
            (
                child.name,
                child_stat.st_dev,
                child_stat.st_ino,
                child_stat.st_mode,
                detail,
            )
        )
    return ("directory", root_stat.st_dev, root_stat.st_ino, tuple(entries))


def publish_render_dir(
    staging: Path, destination: Path, expected_destination: tuple | None
) -> Path | None:
    """Publish atomically, detect concurrent changes, and retain the old bundle."""
    backup = destination.parent / (
        f".{destination.name}.previous-{os.getpid()}-{secrets.token_hex(6)}"
    )
    conflict = destination.parent / (
        f".{destination.name}.concurrent-{os.getpid()}-{secrets.token_hex(6)}"
    )

    def restore_backup() -> None:
        if destination.exists() or destination.is_symlink():
            os.replace(destination, conflict)
        os.replace(backup, destination)

    had_destination = destination.exists() or destination.is_symlink()
    if had_destination:
        os.replace(destination, backup)
        if directory_snapshot(backup) != expected_destination:
            restore_backup()
            raise RuntimeError(
                f"Render target changed while the replacement was staged: {destination}"
            )
    try:
        os.replace(staging, destination)
    except BaseException:
        if had_destination and (backup.exists() or backup.is_symlink()):
            restore_backup()
        raise
    # Never delete the replaced directory here. A writer with an already-open
    # descriptor can still modify it after the snapshot check; retaining it is
    # the only way to guarantee that concurrent user data is recoverable.
    return backup if had_destination else None


def render(args: argparse.Namespace) -> dict:
    requested_output = Path(args.output_dir).expanduser()
    if requested_output.is_symlink():
        die(f"--output-dir must not be a symbolic link: {requested_output}")
    output_dir = requested_output.resolve()
    render_dir = output_dir / args.target
    if args.dry_run:
        assets: list[str] = []
    else:
        generated_files = (
            SOK_GENERATED_FILES if args.target == "sok" else POD_GENERATED_FILES
        )
        if render_dir.is_symlink():
            die(f"Render target must not be a symbolic link: {render_dir}")
        if render_dir.exists() and not render_dir.is_dir():
            die(f"Render target exists and is not a directory: {render_dir}")
        if render_dir.exists():
            unknown = sorted(
                child.name
                for child in render_dir.iterdir()
                if child.name not in generated_files
            )
            if unknown:
                die(
                    "Render target contains files not owned by this bundle: "
                    + ", ".join(unknown)
                )
        original_snapshot = directory_snapshot(render_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=f".{args.target}.staging-", dir=output_dir)
        )
        staging.chmod(0o700)
        try:
            if args.target == "sok":
                assets = render_sok_assets(args, staging)
            else:
                assets = render_pod_assets(args, staging)
            previous = publish_render_dir(staging, render_dir, original_snapshot)
            if previous is not None:
                print(
                    "WARNING: previous reviewed bundle retained for recovery at "
                    f"{previous}",
                    file=sys.stderr,
                )
        except RuntimeError as exc:
            remove_path_without_following(staging)
            die(str(exc))
        except BaseException:
            remove_path_without_following(staging)
            raise

    return {
        "target": args.target,
        "architecture": args.architecture if args.target == "sok" else None,
        "pod_profile": pod_profile(args) if args.target == "pod" else None,
        "pod_base_profile": (
            pod_base_profile(pod_profile(args)) if args.target == "pod" else None
        ),
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "assets": assets,
        "commands": command_plan(args, render_dir),
        "dry_run": args.dry_run,
        "versions": {
            "chart": chart_version(args) if args.target == "sok" else None,
            "splunk_operator": args.operator_version if args.target == "sok" else None,
            "splunk_enterprise": (
                args.splunk_version
                if args.target == "sok"
                else ".".join(
                    str(item) for item in pod_bundle_tuple(args.pod_version)[0]
                )
            ),
            "splunk_image": splunk_image(args) if args.target == "sok" else None,
            "pod_bundle": args.pod_version if args.target == "pod" else None,
            "pod_installer": (
                ".".join(str(item) for item in pod_bundle_tuple(args.pod_version)[1])
                if args.target == "pod"
                else None
            ),
        },
        "terms": {
            "accepted": (
                args.accept_splunk_general_terms if args.target == "sok" else None
            ),
            "value": (
                SGT_ACCEPTANCE
                if args.target == "sok" and args.accept_splunk_general_terms
                else ""
            ),
        },
    }


def main() -> int:
    args = parse_args()
    validate_common(args)
    metadata = render(args)
    if args.json:
        print(json.dumps(metadata, indent=2, sort_keys=True))
    elif args.dry_run:
        print(f"Would render {args.target} assets under {metadata['render_dir']}")
    else:
        print(f"Rendered {args.target} assets under {metadata['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
