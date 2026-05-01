#!/usr/bin/env python3
"""Render Splunk Enterprise Kubernetes setup assets.

The renderer intentionally uses only the Python standard library so it can run
in the same minimal environments as the shell skills.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
import sys
from pathlib import Path
from typing import Iterable


DEFAULT_OPERATOR_VERSION = "3.1.0"
DEFAULT_SPLUNK_VERSION = "10.2.0"
SGT_ACCEPTANCE = "--accept-sgt-current-at-splunk-com"
SOK_ARCHITECTURES = {"s1", "c3", "m4"}
POD_PROFILES = {
    "pod-small",
    "pod-medium",
    "pod-large",
    "pod-small-es",
    "pod-medium-es",
    "pod-large-es",
}
SOK_GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "namespace.yaml",
    "crds-install.sh",
    "preflight.sh",
    "operator-values.yaml",
    "enterprise-values.yaml",
    "helm-install-operator.sh",
    "helm-install-enterprise.sh",
    "create-license-configmap.sh",
    "eks-update-kubeconfig.sh",
    "status.sh",
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
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render Splunk Operator or Splunk POD deployment assets."
    )
    parser.add_argument("--target", choices=("sok", "pod"), required=True)
    parser.add_argument("--architecture", choices=sorted(SOK_ARCHITECTURES), default="s1")
    parser.add_argument("--pod-profile", choices=sorted(POD_PROFILES), default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--namespace", default="splunk-operator")
    parser.add_argument("--operator-namespace", default="splunk-operator")
    parser.add_argument("--release-name", default="splunk-enterprise")
    parser.add_argument("--operator-release-name", default="splunk-operator")
    parser.add_argument("--operator-version", default=DEFAULT_OPERATOR_VERSION)
    parser.add_argument("--chart-version", default="")
    parser.add_argument("--splunk-version", default=DEFAULT_SPLUNK_VERSION)
    parser.add_argument("--splunk-image", default="")
    parser.add_argument("--storage-class", default="")
    parser.add_argument("--etc-storage", default="10Gi")
    parser.add_argument("--var-storage", default="100Gi")
    parser.add_argument("--standalone-replicas", default="1")
    parser.add_argument("--indexer-replicas", default="3")
    parser.add_argument("--search-head-replicas", default="3")
    parser.add_argument("--site-count", default="3")
    parser.add_argument("--site-zones", default="")
    parser.add_argument("--license-file", default="")
    parser.add_argument("--smartstore-bucket", default="")
    parser.add_argument("--smartstore-prefix", default="")
    parser.add_argument("--smartstore-region", default="")
    parser.add_argument("--smartstore-endpoint", default="")
    parser.add_argument("--smartstore-secret-ref", default="")
    parser.add_argument("--eks-cluster-name", default="")
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


def ensure_positive_int(value: str, option: str) -> int:
    if not re.fullmatch(r"[0-9]+", value or ""):
        die(f"{option} must be a positive integer.")
    parsed = int(value)
    if parsed < 1:
        die(f"{option} must be a positive integer.")
    return parsed


def splunk_image(args: argparse.Namespace) -> str:
    return args.splunk_image or f"splunk/splunk:{args.splunk_version}"


def version_major(version: str) -> int:
    match = re.match(r"^([0-9]+)", version)
    return int(match.group(1)) if match else 0


def image_tag_major(image: str) -> int:
    image_name = image.rsplit("/", 1)[-1]
    if ":" not in image_name:
        return 0
    return version_major(image_name.rsplit(":", 1)[-1])


def chart_version(args: argparse.Namespace) -> str:
    return args.chart_version or args.operator_version


def assert_terms(args: argparse.Namespace) -> None:
    if args.target != "sok":
        return
    if (
        version_major(args.splunk_version) >= 10
        or image_tag_major(args.splunk_image) >= 10
    ) and not args.accept_splunk_general_terms:
        die(
            "Splunk Enterprise 10.x container images require explicit "
            "--accept-splunk-general-terms."
        )


def validate_k8s_name(value: str, option: str) -> None:
    if not re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", value or ""):
        die(f"{option} must be a valid Kubernetes DNS label.")
    if len(value) > 63:
        die(f"{option} must be 63 characters or fewer.")


def validate_nonempty_path_list(value: str, option: str) -> None:
    if value and not split_csv(value):
        die(f"{option} must contain at least one non-empty CSV value.")


def validate_common(args: argparse.Namespace) -> None:
    ensure_positive_int(args.standalone_replicas, "--standalone-replicas")
    indexer_replicas = ensure_positive_int(args.indexer_replicas, "--indexer-replicas")
    search_head_replicas = ensure_positive_int(
        args.search_head_replicas, "--search-head-replicas"
    )
    ensure_positive_int(args.site_count, "--site-count")
    if args.target == "sok":
        validate_k8s_name(args.namespace, "--namespace")
        validate_k8s_name(args.operator_namespace, "--operator-namespace")
        validate_k8s_name(args.release_name, "--release-name")
        validate_k8s_name(args.operator_release_name, "--operator-release-name")
        assert_terms(args)
        if args.eks_cluster_name and not args.aws_region:
            die("--aws-region is required with --eks-cluster-name.")
        if args.smartstore_bucket and not (
            args.smartstore_region or args.smartstore_endpoint
        ):
            die(
                "--smartstore-region or --smartstore-endpoint is required "
                "with --smartstore-bucket."
            )
        if args.architecture == "c3" and indexer_replicas < 3:
            die("--indexer-replicas must be at least 3 for SOK C3.")
        if args.architecture in {"c3", "m4"} and search_head_replicas < 3:
            die("--search-head-replicas must be at least 3 for SOK C3/M4.")
        if args.architecture == "m4":
            site_count = ensure_positive_int(args.site_count, "--site-count")
            if args.site_zones and len(split_csv(args.site_zones)) != site_count:
                die("--site-zones must have one zone per M4 site.")
    if args.target == "pod":
        profile = pod_profile(args)
        if profile not in POD_PROFILES:
            die(f"Unsupported POD profile: {profile}")
        validate_nonempty_path_list(args.premium_apps, "--premium-apps")


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def remove_stale_generated_files(render_dir: Path, generated_files: set[str]) -> None:
    for rel_path in generated_files:
        candidate = render_dir / rel_path
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink()


def make_script(body: str) -> str:
    return "#!/usr/bin/env bash\nset -euo pipefail\n\n" + body.lstrip()


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


def resources_block(indent: str = "  ") -> str:
    return "\n".join(
        [
            f"{indent}resources:",
            f"{indent}  requests:",
            f"{indent}    cpu: \"4\"",
            f"{indent}    memory: \"8Gi\"",
            f"{indent}  limits:",
            f"{indent}    cpu: \"8\"",
            f"{indent}    memory: \"16Gi\"",
        ]
    )


def license_block(args: argparse.Namespace, indent: str = "  ") -> str:
    if not args.license_file:
        return f"{indent}licenseUrl: \"\""
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
    return "\n".join(
        [
            "licenseManager:",
            "  enabled: true",
            "  name: \"lm\"",
            license_block(args),
            storage_block(args),
            resources_block(),
            "",
        ]
    )


def smartstore_block(args: argparse.Namespace, indent: str = "  ") -> str:
    if not args.smartstore_bucket:
        return f"{indent}smartstore: {{}}"
    endpoint = args.smartstore_endpoint
    if not endpoint and args.smartstore_region:
        endpoint = f"https://s3.{args.smartstore_region}.amazonaws.com"
    path = args.smartstore_bucket
    if args.smartstore_prefix:
        path = f"{path.rstrip('/')}/{args.smartstore_prefix.strip('/')}"
    secret_ref = args.smartstore_secret_ref or "splunk-smartstore-s3"
    return "\n".join(
        [
            f"{indent}smartstore:",
            f"{indent}  defaults:",
            f"{indent}    volumeName: remote_store",
            f"{indent}  indexes:",
            f"{indent}    - name: main",
            f"{indent}      remotePath: $_index_name",
            f"{indent}      volumeName: remote_store",
            f"{indent}  volumes:",
            f"{indent}    - name: remote_store",
            f"{indent}      storageType: s3",
            f"{indent}      provider: aws",
            f"{indent}      path: {yaml_quote(path)}",
            f"{indent}      endpoint: {yaml_quote(endpoint)}",
            f"{indent}      region: {yaml_quote(args.smartstore_region)}",
            f"{indent}      secretRef: {yaml_quote(secret_ref)}",
        ]
    )


def render_sva(args: argparse.Namespace) -> str:
    indexers = ensure_positive_int(args.indexer_replicas, "--indexer-replicas")
    search_heads = ensure_positive_int(args.search_head_replicas, "--search-head-replicas")
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
            "      site: site1",
            f"      allSites: {yaml_quote(','.join(site_names))}",
            "    indexerClusters:",
            *indexer_lines,
            "    searchHeadClusters:",
            "      - name: shc",
            "        site: site0",
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
    resources_text = resources_block()
    image = splunk_image(args)
    indexer_replicas = ensure_positive_int(args.indexer_replicas, "--indexer-replicas")
    search_replicas = ensure_positive_int(args.search_head_replicas, "--search-head-replicas")
    standalone_replicas = ensure_positive_int(args.standalone_replicas, "--standalone-replicas")

    lines = [
        "# Rendered by splunk-enterprise-kubernetes-setup. Review before applying.",
        "splunk-operator:",
        "  enabled: false",
        "image:",
        f"  repository: {yaml_quote(image)}",
        "  imagePullPolicy: \"IfNotPresent\"",
        render_sva(args),
        "",
    ]

    if architecture == "s1":
        lines.extend(
            [
                "standalone:",
                "  enabled: true",
                "  name: \"s1\"",
                f"  replicaCount: {standalone_replicas}",
                license_text,
                smartstore_text,
                storage_text,
                resources_text,
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
                "  name: \"cm\"",
                smartstore_text,
                storage_text,
                resources_text,
                "",
                "indexerCluster:",
                "  enabled: true",
                "  name: \"idxc\"",
                f"  replicaCount: {indexer_replicas}",
                storage_text,
                resources_text,
                "",
                "searchHeadCluster:",
                "  enabled: true",
                "  name: \"shc\"",
                f"  replicaCount: {search_replicas}",
                storage_text,
                resources_text,
                "",
                "monitoringConsole:",
                "  enabled: true",
                "  name: \"mc\"",
                storage_text,
                resources_text,
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_operator_values(args: argparse.Namespace) -> str:
    image = f"docker.io/splunk/splunk-operator:{args.operator_version}"
    related_image = splunk_image(args)
    return "\n".join(
        [
            "# Rendered by splunk-enterprise-kubernetes-setup. Review before applying.",
            "image:",
            f"  repository: {yaml_quote(related_image)}",
            "splunkOperator:",
            "  image:",
            f"    repository: {yaml_quote(image)}",
            "    pullPolicy: IfNotPresent",
            "  clusterWideAccess: true",
            f"  watchNamespaces: {yaml_quote(args.namespace)}",
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
    lines = [
        "command -v kubectl >/dev/null",
        "command -v helm >/dev/null",
        "kubectl version --client=true",
        "helm version",
    ]
    if args.eks_cluster_name:
        lines.extend(
            [
                "command -v aws >/dev/null",
                f"aws eks describe-cluster --name {shell_quote(args.eks_cluster_name)} --region {shell_quote(args.aws_region)} >/dev/null",
            ]
        )
    return make_script("\n".join(lines) + "\n")


def render_sok_readme(args: argparse.Namespace) -> str:
    return f"""# Splunk Enterprise Kubernetes Rendered Assets

Target: Splunk Operator for Kubernetes

## Files

- `namespace.yaml`
- `crds-install.sh`
- `operator-values.yaml`
- `enterprise-values.yaml`
- `helm-install-operator.sh`
- `helm-install-enterprise.sh`
- `status.sh`

## Review Points

- SVA architecture: `{args.architecture.upper()}`
- Splunk Operator: `{args.operator_version}`
- Splunk Enterprise image: `{splunk_image(args)}`
- Namespace: `{args.namespace}`
- StorageClass: `{args.storage_class or "cluster default"}`
- Splunk General Terms accepted in rendered operator values: `{bool_word(args.accept_splunk_general_terms)}`

For Splunk Enterprise 10.x images, the operator container must receive
`SPLUNK_GENERAL_TERMS={SGT_ACCEPTANCE}`. This directory renders that only when
the setup command included `--accept-splunk-general-terms`.
"""


def render_sok_assets(args: argparse.Namespace, render_dir: Path) -> list[str]:
    assets: list[str] = []

    def emit(rel: str, content: str, executable: bool = False) -> None:
        write_file(render_dir / rel, content, executable=executable)
        assets.append(rel)

    emit("README.md", render_sok_readme(args))
    emit(
        "metadata.json",
        json.dumps(
            {
                "target": "sok",
                "architecture": args.architecture,
                "chart_version": chart_version(args),
                "operator_version": args.operator_version,
                "splunk_version": args.splunk_version,
                "namespace": args.namespace,
                "operator_namespace": args.operator_namespace,
                "release_name": args.release_name,
                "operator_release_name": args.operator_release_name,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    emit("namespace.yaml", render_namespace(args))
    emit(
        "crds-install.sh",
        make_script(
            f"""kubectl apply -f {shell_quote(f'https://github.com/splunk/splunk-operator/releases/download/{args.operator_version}/splunk-operator-crds.yaml')} --server-side
"""
        ),
        executable=True,
    )
    emit("preflight.sh", render_sok_preflight(args), executable=True)
    emit("operator-values.yaml", render_operator_values(args))
    emit("enterprise-values.yaml", render_enterprise_values(args))
    emit(
        "helm-install-operator.sh",
        make_script(
            f"""helm repo add splunk https://splunk.github.io/splunk-operator/ --force-update
helm repo update
kubectl apply -f namespace.yaml
helm upgrade --install {shell_quote(args.operator_release_name)} splunk/splunk-operator \\
  --version {shell_quote(chart_version(args))} \\
  --namespace {shell_quote(args.operator_namespace)} \\
  --create-namespace \\
  --values operator-values.yaml
"""
        ),
        executable=True,
    )
    emit(
        "helm-install-enterprise.sh",
        make_script(
            f"""helm repo add splunk https://splunk.github.io/splunk-operator/ --force-update
helm repo update
kubectl apply -f namespace.yaml
helm upgrade --install {shell_quote(args.release_name)} splunk/splunk-enterprise \\
  --version {shell_quote(chart_version(args))} \\
  --namespace {shell_quote(args.namespace)} \\
  --create-namespace \\
  --values enterprise-values.yaml
"""
        ),
        executable=True,
    )
    if args.license_file:
        emit(
            "create-license-configmap.sh",
            make_script(
                f"""kubectl create configmap splunk-licenses \\
  --namespace {shell_quote(args.namespace)} \\
  --from-file={shell_quote(str(Path(args.license_file).name) + '=' + args.license_file)} \\
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
                f"""aws eks update-kubeconfig --name {shell_quote(args.eks_cluster_name)} --region {shell_quote(args.aws_region)}
"""
            ),
            executable=True,
        )
    emit(
        "status.sh",
        make_script(
            f"""helm list --namespace {shell_quote(args.operator_namespace)}
helm list --namespace {shell_quote(args.namespace)}
kubectl get pods --namespace {shell_quote(args.operator_namespace)}
kubectl get pods --namespace {shell_quote(args.namespace)}
kubectl get standalone,indexercluster,searchheadcluster,clustermanager --namespace {shell_quote(args.namespace)} || true
"""
        ),
        executable=True,
    )
    return assets


def pod_profile(args: argparse.Namespace) -> str:
    if args.pod_profile:
        return args.pod_profile
    mapping = {"s1": "pod-small", "c3": "pod-medium", "m4": "pod-large"}
    return mapping[args.architecture]


def pod_base_profile(profile: str) -> str:
    return profile.removesuffix("-es")


def pod_is_es(profile: str) -> bool:
    return profile.endswith("-es")


def example_ips(start: int, count: int) -> list[str]:
    return [f"10.10.10.{item}" for item in range(start, start + count)]


def pod_counts(profile: str) -> tuple[int, int]:
    base_profile = pod_base_profile(profile)
    es_profile = pod_is_es(profile)
    if base_profile == "pod-small":
        return 3, 9 if es_profile else 8
    if base_profile == "pod-medium":
        return 3, 14 if es_profile else 11
    return 3, 18 if es_profile else 15


def pod_role_comment(profile: str, index: int) -> str:
    base_profile = pod_base_profile(profile)
    es = pod_is_es(profile)
    if base_profile == "pod-small":
        if index == 0:
            return "Search head C225"
        if es and index == 1:
            return "Enterprise Security search head C225"
        if index <= (4 if es else 3):
            return "Indexer C245"
        return "Volume C245"
    if base_profile == "pod-medium":
        if index <= 2:
            return "Search head C225"
        if es and index <= 5:
            return "Enterprise Security search head C225"
        if index <= (9 if es else 6):
            return "Indexer C245"
        return "Volume C245"
    if index <= 2:
        return "Search head C225"
    if es and index <= 5:
        return "Enterprise Security search head C225"
    if index <= (12 if es else 9):
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
    workers = split_csv(args.worker_ips) or example_ips(1 + controller_count, worker_count)
    license_files = split_csv(args.license_file) or ["/path/to/splunk.lic"]
    indexer_apps = split_csv(args.indexer_apps) or ["/path/to/indexer-app.tgz"]
    search_apps = split_csv(args.search_apps)
    standalone_apps = split_csv(args.standalone_apps) or ["./path/to/myapp.tgz"]
    premium_apps = split_csv(args.premium_apps) or ["./apps/splunk_app_es.tgz"]
    base_profile = pod_base_profile(profile)
    es_profile = pod_is_es(profile)

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
        "controllers:",
    ]
    for index, address in enumerate(controllers, start=1):
        lines.append(f"  - address: {yaml_quote(address)} # Controller C225")
    lines.append("workers:")
    for index, address in enumerate(workers):
        lines.append(f"  - address: {yaml_quote(address)} # {pod_role_comment(profile, index)}")
    lines.extend(
        [
            "clustermanager:",
            "  apps:",
            "    cluster:",
            *render_yaml_path_list(indexer_apps, "      "),
        ]
    )
    if base_profile == "pod-small":
        lines.extend(
            [
                "standalone:",
                "  - name: my-sh",
                "    apps:",
                "      local:",
                *render_yaml_path_list(standalone_apps, "        "),
            ]
        )
        if es_profile:
            lines.extend(
                [
                    "  - name: es-sh",
                    "    apps:",
                    "      local:",
                    "        []",
                    "      premium:",
                    *render_yaml_path_list(premium_apps, "        "),
                ]
            )
    else:
        lines.extend(
            [
                "searchheadcluster:",
                "  - name: core-shc",
                "    apps:",
                "      cluster:",
                *render_yaml_path_list(search_apps or ["/path/to/sh-app.tar.gz"], "        "),
            ]
        )
        if es_profile:
            lines.extend(
                [
                    "  - name: es-shc",
                    "    apps:",
                    "      cluster:",
                    "        []",
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

## Files

- `cluster-config.yaml`
- `preflight.sh`
- `deploy.sh`
- `status-workers.sh`
- `status.sh`
- `get-creds.sh`
- `web-docs.sh`

The installer prompts for Terms and Conditions acceptance during the first
deployment. If the installer writes `termsConditionsAccepted: true` back into
`cluster-config.yaml`, remove that key before sharing the file.

Requested profile: `{profile}`.
Installer profile rendered in `cluster-config.yaml`: `{base_profile}`.
"""


def render_pod_assets(args: argparse.Namespace, render_dir: Path) -> list[str]:
    assets: list[str] = []

    def emit(rel: str, content: str, executable: bool = False) -> None:
        write_file(render_dir / rel, content, executable=executable)
        assets.append(rel)

    installer = "kubernetes-installer-standalone"
    profile = pod_profile(args)
    base_profile = pod_base_profile(profile)
    emit("README.md", render_pod_readme(args))
    emit(
        "metadata.json",
        json.dumps(
            {
                "target": "pod",
                "pod_profile": profile,
                "pod_base_profile": base_profile,
                "architecture": args.architecture,
                "controller_count": pod_counts(profile)[0],
                "worker_count": pod_counts(profile)[1],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    emit("cluster-config.yaml", render_pod_config(args))
    emit(
        "preflight.sh",
        make_script(f"{installer} -static.cluster cluster-config.yaml -preflightcheck.only\n"),
        executable=True,
    )
    emit(
        "deploy.sh",
        make_script(f"{installer} -static.cluster cluster-config.yaml -deploy\n"),
        executable=True,
    )
    emit(
        "status-workers.sh",
        make_script(f"{installer} -static.cluster cluster-config.yaml -status.workers\n"),
        executable=True,
    )
    emit(
        "status.sh",
        make_script(f"{installer} -static.cluster cluster-config.yaml -status\n"),
        executable=True,
    )
    emit(
        "get-creds.sh",
        make_script(f"{installer} -static.cluster cluster-config.yaml -get.creds\n"),
        executable=True,
    )
    emit(
        "web-docs.sh",
        make_script(
            f"""port="${{WEB_PORT:-8080}}"
printf 'Starting Splunk POD local documentation server.\\n'
printf 'Open http://<BASTION_IP>:%s/docs from a browser that can reach the bastion.\\n' "${{port}}"
exec {installer} -web --web.port "${{port}}"
"""
        ),
        executable=True,
    )
    return assets


def command_plan(args: argparse.Namespace, render_dir: Path) -> dict[str, list[list[str]]]:
    if args.target == "sok":
        apply_cmds: list[list[str]] = []
        if args.eks_cluster_name:
            apply_cmds.append(["./eks-update-kubeconfig.sh"])
        apply_cmds.extend([["./crds-install.sh"], ["./helm-install-operator.sh"]])
        if args.license_file:
            apply_cmds.append(["./create-license-configmap.sh"])
        apply_cmds.append(["./helm-install-enterprise.sh"])
        return {
            "preflight": [["./preflight.sh"]],
            "apply": apply_cmds,
            "status": [["./status.sh"]],
        }
    return {
        "preflight": [["./preflight.sh"]],
        "apply": [["./deploy.sh"]],
        "status": [["./status-workers.sh"], ["./status.sh"]],
    }


def render(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / args.target
    if args.dry_run:
        assets: list[str] = []
    elif args.target == "sok":
        remove_stale_generated_files(render_dir, SOK_GENERATED_FILES)
        assets = render_sok_assets(args, render_dir)
    else:
        remove_stale_generated_files(render_dir, POD_GENERATED_FILES)
        assets = render_pod_assets(args, render_dir)

    return {
        "target": args.target,
        "architecture": args.architecture,
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
            "splunk_operator": args.operator_version,
            "splunk_enterprise": args.splunk_version,
            "splunk_image": splunk_image(args),
        },
        "terms": {
            "accepted": args.accept_splunk_general_terms,
            "value": SGT_ACCEPTANCE if args.accept_splunk_general_terms else "",
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
