"""Render Cilium / Tetragon / Hubble Enterprise install assets.

NOT a Splunk skill -- this skill installs the Isovalent platform itself
on Kubernetes. Splunk wiring lives in
splunk-observability-isovalent-integration.

Outputs:
  - helm/cilium-values.yaml
  - helm/tetragon-values.yaml
  - helm/tracing-policy.yaml (starter)
  - helm/cilium-dnsproxy-values.yaml      (Enterprise + --enable-dnsproxy)
  - helm/hubble-enterprise-values.yaml    (Enterprise + --enable-hubble-enterprise; private chart)
  - helm/hubble-timescape-values.yaml     (Enterprise + --enable-timescape)
  - scripts/install-cilium.sh
  - scripts/install-tetragon.sh
  - scripts/install-cilium-dnsproxy.sh    (Enterprise + --enable-dnsproxy)
  - scripts/install-hubble-enterprise.sh  (Enterprise + --enable-hubble-enterprise; emits contact link, no helm pull)
  - scripts/install-hubble-timescape.sh   (Enterprise + --enable-timescape)
  - scripts/preflight.sh
  - scripts/eksctl-byocni-example.sh      (when --render-eksctl-example)
  - metadata.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SHARED_LIB = Path(__file__).resolve().parents[3] / "skills" / "shared" / "lib"
if str(SHARED_LIB) not in sys.path:
    sys.path.insert(0, str(SHARED_LIB))

from yaml_compat import YamlCompatError, dump_yaml, load_yaml_or_json  # noqa: E402


SKILL_NAME = "cisco-isovalent-platform-setup"

OSS_REPO_URL = "https://helm.cilium.io"
OSS_REPO_NAME = "cilium"
OSS_CILIUM_CHART = "cilium/cilium"
OSS_TETRAGON_CHART = "cilium/tetragon"

ENTERPRISE_REPO_URL = "https://helm.isovalent.com"
ENTERPRISE_REPO_NAME = "isovalent"
ENTERPRISE_CILIUM_CHART = "isovalent/cilium-enterprise"
ENTERPRISE_TETRAGON_CHART = "isovalent/tetragon"
ENTERPRISE_DNSPROXY_CHART = "isovalent/cilium-dnsproxy"
ENTERPRISE_HUBBLE_ENT_CHART = "isovalent/hubble-enterprise"
ENTERPRISE_TIMESCAPE_CHART = "isovalent/hubble-timescape"

EKS_AWS_MIRROR_OCI = "oci://public.ecr.aws/eks/cilium/cilium"

VALID_EDITIONS = {"oss", "enterprise"}
VALID_EXPORT_MODES = {"file", "stdout", "fluentd"}


class SpecError(ValueError):
    """Raised when the input spec violates skill constraints."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--edition", default="", help="oss | enterprise (or empty = inherit from spec.edition)")
    parser.add_argument("--cluster-name", default="", help="Override spec.cluster_name")
    parser.add_argument("--eks-mirror", default="")
    parser.add_argument("--enable-dnsproxy", default="false")
    parser.add_argument("--enable-hubble-enterprise", default="false")
    parser.add_argument("--enable-timescape", default="false")
    parser.add_argument("--export-mode", default="")
    parser.add_argument("--isovalent-license-file", default="")
    parser.add_argument("--isovalent-pull-secret-file", default="")
    parser.add_argument("--render-eksctl-example", default="false")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def bool_flag(value: str) -> bool:
    return str(value).lower() == "true"


def load_spec(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        data = load_yaml_or_json(text, source=str(path))
    except YamlCompatError as exc:
        raise SpecError(f"Failed to parse spec {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError(f"Spec {path} did not parse to a mapping.")
    if data.get("api_version") != f"{SKILL_NAME}/v1":
        raise SpecError(
            f"Spec api_version must be '{SKILL_NAME}/v1'; got {data.get('api_version')!r}"
        )
    return data


def write_text(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def write_yaml(path: Path, payload: Any) -> None:
    write_text(path, dump_yaml(payload, sort_keys=True))


def cilium_values(spec: dict[str, Any], edition: str) -> dict[str, Any]:
    overrides = (spec.get("cilium") or {})
    base: dict[str, Any] = {
        "cluster": {
            "name": spec.get("cluster_name", "lab-cluster"),
        },
        "ipam": {"mode": "kubernetes"},
        "kubeProxyReplacement": "strict",
        "rollOutCiliumPods": True,
        "operator": {
            "rollOutPods": True,
            "prometheus": {"enabled": True},
        },
        "prometheus": {"enabled": True},
        "envoy": {"prometheus": {"enabled": True}},
        "hubble": {
            "enabled": True,
            "metrics": {"enabled": [], "enableOpenMetrics": True},
            "relay": {"enabled": True},
        },
    }
    # Enterprise feature gate. The Isovalent Enterprise chart accepts
    # `enterprise.featureGate`; OSS chart ignores it and continues without
    # Enterprise-only features. Set explicitly for clarity.
    if edition == "enterprise":
        base["enterprise"] = {"featureGate": "v1.18"}
    return _deep_merge(base, overrides)


def tetragon_values(spec: dict[str, Any], edition: str, export_mode_override: str) -> dict[str, Any]:
    overrides = (spec.get("tetragon") or {})
    export_block = (overrides.get("export") or {})
    export_mode = export_mode_override or export_block.get("mode") or "file"
    if export_mode not in VALID_EXPORT_MODES:
        raise SpecError(
            f"tetragon.export.mode must be one of {sorted(VALID_EXPORT_MODES)}; got {export_mode!r}"
        )
    export_directory = export_block.get("directory", "/var/run/cilium/tetragon")
    export_filename = export_block.get("filename", "tetragon.log")
    enable_events = (overrides.get("enable_events") or {})
    base: dict[str, Any] = {
        "tetragon": {
            "clusterName": spec.get("cluster_name", "lab-cluster"),
            "enableEvents": {
                "network": bool(enable_events.get("network", True)),
            },
            "exportDirectory": export_directory,
            "exportFilename": export_filename,
        }
    }
    if export_mode == "file":
        # Default file-based export path. Coordinates with
        # splunk-observability-isovalent-integration's hostPath mount of
        # /var/run/cilium/tetragon and its extraFileLogs.filelog/tetragon
        # block. No additional Helm fields needed; the chart exports to
        # files when both exportDirectory and exportFilename are set.
        pass
    elif export_mode == "stdout":
        base["tetragon"]["export"] = {"mode": "stdout"}
    elif export_mode == "fluentd":
        # Legacy path. fluent-plugin-splunk-hec was archived 2025-06-24;
        # operators on this path should plan to migrate to the OTel logs
        # receiver path (the default for splunk-observability-isovalent-integration).
        base["tetragon"]["export"] = {
            "mode": "fluentd",
            "fluentd": {
                "output": (
                    "@type splunk_hec\n"
                    "host PLACEHOLDER_HEC_HOST\n"
                    "port 8088\n"
                    "token PLACEHOLDER_HEC_TOKEN\n"
                    "default_index PLACEHOLDER_INDEX\n"
                    "use_ssl false\n"
                    "# DEPRECATED: fluent-plugin-splunk-hec was archived 2025-06-24.\n"
                    "# Migrate to splunk-observability-isovalent-integration's\n"
                    "# OTel filelog receiver path (mode: file).\n"
                ),
            },
        }
    if edition == "enterprise":
        base["tetragon"]["enterprise"] = {"enabled": True}
    return base


def tracing_policy(spec: dict[str, Any]) -> dict[str, Any] | None:
    block = spec.get("tracing_policy") or {}
    if not block.get("enabled", True):
        return None
    name = block.get("name", "network-monitoring")
    return {
        "apiVersion": "cilium.io/v1alpha1",
        "kind": "TracingPolicy",
        "metadata": {"name": name},
        "spec": {
            "kprobes": [
                {
                    "call": "tcp_connect",
                    "syscall": False,
                    "args": [{"index": 0, "type": "sock"}],
                },
                {
                    "call": "tcp_close",
                    "syscall": False,
                    "args": [{"index": 0, "type": "sock"}],
                },
            ],
        },
    }


def cilium_dnsproxy_values(spec: dict[str, Any]) -> dict[str, Any]:
    overrides = (spec.get("cilium_dnsproxy") or {})
    base: dict[str, Any] = {
        "metrics": {
            "serviceMonitor": {"enabled": False},
        },
    }
    return _deep_merge(base, overrides)


def hubble_enterprise_values(spec: dict[str, Any], export_mode: str) -> dict[str, Any]:
    overrides = (spec.get("hubble_enterprise") or {})
    base: dict[str, Any] = {
        "enabled": True,
        "exportDirectory": "/var/run/cilium/tetragon",
    }
    if export_mode == "fluentd":
        base["export"] = {
            "mode": "fluentd",
            "fluentd": {
                "output": (
                    "@type splunk_hec\n"
                    "host PLACEHOLDER_HEC_HOST\n"
                    "port 8088\n"
                    "token PLACEHOLDER_HEC_TOKEN\n"
                    "default_index PLACEHOLDER_INDEX\n"
                    "use_ssl false\n"
                ),
            },
        }
    return _deep_merge(base, overrides)


def hubble_timescape_values(spec: dict[str, Any]) -> dict[str, Any]:
    overrides = (spec.get("hubble_timescape") or {})
    base: dict[str, Any] = {
        "enabled": True,
    }
    return _deep_merge(base, overrides)


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(overrides, dict):
        return base
    result = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def install_script(*, name: str, body: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        f"# {name}\n"
        f"{body}\n"
    )


def cilium_install_body(edition: str, eks_mirror: bool, namespace: str) -> str:
    chart = OSS_CILIUM_CHART
    repo_setup = (
        f"helm repo add {OSS_REPO_NAME} {OSS_REPO_URL}\n"
        f"helm repo update {OSS_REPO_NAME}\n"
    )
    if edition == "enterprise":
        chart = ENTERPRISE_CILIUM_CHART
        repo_setup = (
            f"helm repo add {ENTERPRISE_REPO_NAME} {ENTERPRISE_REPO_URL}\n"
            f"helm repo update {ENTERPRISE_REPO_NAME}\n"
        )
    if eks_mirror:
        # AWS publishes Cilium for EKS Hybrid Nodes via OCI. When the operator
        # asks for the EKS-AWS mirror we install from the OCI registry instead
        # of helm.cilium.io.
        chart = EKS_AWS_MIRROR_OCI
        repo_setup = "# EKS-AWS mirror: chart is an OCI URL; no helm repo add needed.\n"
    return (
        f'NAMESPACE="${{1:-{namespace}}}"\n'
        f"{repo_setup}"
        f'helm upgrade --install cilium "{chart}" \\\n'
        '    -n "${NAMESPACE}" --create-namespace \\\n'
        '    -f "$(dirname "${BASH_SOURCE[0]}")/../helm/cilium-values.yaml"\n'
        'kubectl -n "${NAMESPACE}" rollout status ds/cilium --timeout=300s\n'
    )


def tetragon_install_body(edition: str, namespace: str) -> str:
    chart = OSS_TETRAGON_CHART
    repo_setup = (
        f"helm repo add {OSS_REPO_NAME} {OSS_REPO_URL}\n"
        f"helm repo update {OSS_REPO_NAME}\n"
    )
    if edition == "enterprise":
        chart = ENTERPRISE_TETRAGON_CHART
        repo_setup = (
            f"helm repo add {ENTERPRISE_REPO_NAME} {ENTERPRISE_REPO_URL}\n"
            f"helm repo update {ENTERPRISE_REPO_NAME}\n"
        )
    return (
        f'NAMESPACE="${{1:-{namespace}}}"\n'
        f"{repo_setup}"
        f'helm upgrade --install tetragon "{chart}" \\\n'
        '    -n "${NAMESPACE}" --create-namespace \\\n'
        '    -f "$(dirname "${BASH_SOURCE[0]}")/../helm/tetragon-values.yaml"\n'
        'kubectl -n "${NAMESPACE}" rollout status ds/tetragon --timeout=300s\n'
        '# Apply the starter TracingPolicy if present.\n'
        'POLICY="$(dirname "${BASH_SOURCE[0]}")/../helm/tracing-policy.yaml"\n'
        '[[ -f "${POLICY}" ]] && kubectl apply -f "${POLICY}"\n'
    )


def cilium_dnsproxy_install_body(namespace: str) -> str:
    return (
        f'NAMESPACE="${{1:-{namespace}}}"\n'
        f"helm repo add {ENTERPRISE_REPO_NAME} {ENTERPRISE_REPO_URL}\n"
        f"helm repo update {ENTERPRISE_REPO_NAME}\n"
        f'helm upgrade --install cilium-dnsproxy "{ENTERPRISE_DNSPROXY_CHART}" \\\n'
        '    -n "${NAMESPACE}" --create-namespace \\\n'
        '    -f "$(dirname "${BASH_SOURCE[0]}")/../helm/cilium-dnsproxy-values.yaml"\n'
    )


def hubble_enterprise_install_body(namespace: str) -> str:
    # Hubble Enterprise is a private chart. We do NOT attempt to helm pull
    # it; instead the script prints the contact link and instructs the
    # operator to install once they have chart access. The values file
    # is rendered alongside so the operator can use it directly.
    return (
        'cat <<EOF\n'
        'Hubble Enterprise is a private chart distributed by Isovalent / Cisco.\n'
        'Contact the Splunk + Isovalent team to request chart access:\n'
        '  https://isovalent.com/splunk-contact-us/\n'
        '\n'
        'Once you have access:\n'
        f"  helm repo add {ENTERPRISE_REPO_NAME} {ENTERPRISE_REPO_URL}\n"
        f"  helm repo update {ENTERPRISE_REPO_NAME}\n"
        f'  helm upgrade --install hubble-enterprise "{ENTERPRISE_HUBBLE_ENT_CHART}" \\\n'
        f'      -n {namespace} --create-namespace --wait \\\n'
        '      -f "$(dirname "${BASH_SOURCE[0]}")/../helm/hubble-enterprise-values.yaml"\n'
        f'  kubectl rollout restart -n {namespace} ds/hubble-enterprise\n'
        'EOF\n'
    )


def hubble_timescape_install_body(namespace: str) -> str:
    return (
        f'NAMESPACE="${{1:-{namespace}}}"\n'
        f"helm repo add {ENTERPRISE_REPO_NAME} {ENTERPRISE_REPO_URL}\n"
        f"helm repo update {ENTERPRISE_REPO_NAME}\n"
        f'helm upgrade --install hubble-timescape "{ENTERPRISE_TIMESCAPE_CHART}" \\\n'
        '    -n "${NAMESPACE}" --create-namespace \\\n'
        '    -f "$(dirname "${BASH_SOURCE[0]}")/../helm/hubble-timescape-values.yaml"\n'
    )


def preflight_body(spec: dict[str, Any], edition: str) -> str:
    eks_byocni = (spec.get("eks_byocni") or {})
    kernel = (spec.get("kernel_preflight") or {})
    minimum_kernel = kernel.get("minimum_version", "5.10")
    body = ["# Preflight checks for Cilium / Tetragon install."]
    if kernel.get("enable", True):
        body.append(
            f'echo "Kernel check: minimum {minimum_kernel} required for Cilium v1.18.x."'
        )
        body.append(
            'kubectl get nodes -o jsonpath=\'{range .items[*]}{.metadata.name}{"\\t"}{.status.nodeInfo.kernelVersion}{"\\n"}{end}\' \\\n'
            f'    | awk -v min="{minimum_kernel}" \'{{split($2,a,/[.-]/); split(min,b,/[.-]/);'
            ' ok=(a[1]>b[1] || (a[1]==b[1] && a[2]>=b[2])); printf "%s\\t%s\\t%s\\n", $1, $2, ok?"OK":"WARN"}\''
        )
    if eks_byocni.get("enable_preflight", True):
        body.append(
            'if kubectl -n kube-system get ds aws-node >/dev/null 2>&1; then'
        )
        body.append(
            '    echo "WARN: AWS VPC CNI (aws-node DaemonSet) is installed; Cilium requires BYOCNI (--network-plugin none)."'
        )
        body.append("fi")
    body.append('echo "Preflight done. Review WARN lines before install."')
    return "\n".join(body) + "\n"


def eksctl_byocni_example() -> str:
    return (
        "#!/usr/bin/env bash\n"
        "# Example: create an EKS cluster in BYOCNI mode for Cilium.\n"
        "# Requires eksctl >= 0.150.\n"
        "cat <<EOF\n"
        "apiVersion: eksctl.io/v1alpha5\n"
        "kind: ClusterConfig\n"
        "metadata:\n"
        "  name: cilium-byocni\n"
        "  region: us-east-1\n"
        "managedNodeGroups:\n"
        "  - name: ng-1\n"
        "    instanceType: m5.large\n"
        "    desiredCapacity: 3\n"
        "addons:\n"
        "  - name: kube-proxy\n"
        "  - name: coredns\n"
        "EOF\n"
        "echo 'Save the above as cluster.yaml, then:'\n"
        "echo '  eksctl create cluster -f cluster.yaml --without-nodegroup'\n"
        "echo '  eksctl create nodegroup --config-file cluster.yaml --network-plugin none'\n"
    )


def render_metadata(args: argparse.Namespace, spec: dict[str, Any], edition: str) -> dict[str, Any]:
    export_mode = args.export_mode or (spec.get("tetragon") or {}).get("export", {}).get("mode", "file")
    return {
        "skill": SKILL_NAME,
        "edition": edition,
        "cluster_name": spec.get("cluster_name", "lab-cluster"),
        "eks_mirror": bool_flag(args.eks_mirror),
        "enable_dnsproxy": bool_flag(args.enable_dnsproxy),
        "enable_hubble_enterprise": bool_flag(args.enable_hubble_enterprise),
        "enable_timescape": bool_flag(args.enable_timescape),
        "tetragon_export_mode": export_mode,
        "warnings": warnings(args, spec, edition),
    }


def warnings(args: argparse.Namespace, spec: dict[str, Any], edition: str) -> list[str]:
    items: list[str] = []
    if edition == "enterprise" and bool_flag(args.enable_hubble_enterprise):
        items.append(
            "Hubble Enterprise chart (isovalent/hubble-enterprise) is private. "
            "Contact the Splunk + Isovalent team for chart access "
            "(https://isovalent.com/splunk-contact-us/). The renderer prints "
            "the install steps; it does NOT helm pull the chart."
        )
    export_mode = (args.export_mode or (spec.get("tetragon") or {}).get("export", {}).get("mode") or "file")
    if export_mode == "fluentd":
        items.append(
            "DEPRECATED: tetragon export mode 'fluentd' uses the archived "
            "fluent-plugin-splunk-hec (archived 2025-06-24). Plan to migrate "
            "to the file-based path used by splunk-observability-isovalent-integration."
        )
    if edition == "oss" and (bool_flag(args.enable_dnsproxy) or bool_flag(args.enable_hubble_enterprise) or bool_flag(args.enable_timescape)):
        items.append(
            "Enterprise add-ons (cilium-dnsproxy / hubble-enterprise / hubble-timescape) "
            "require --edition enterprise. Switching to enterprise is required for these flags."
        )
    return items


def main() -> int:
    args = parse_args()
    spec_path = Path(args.spec)
    if not spec_path.is_file():
        print(f"ERROR: spec not found: {spec_path}", file=__import__("sys").stderr)
        return 1
    try:
        spec = load_spec(spec_path)
    except SpecError as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1
    if args.cluster_name:
        spec = dict(spec)
        spec["cluster_name"] = args.cluster_name

    edition = (args.edition or spec.get("edition") or "oss").lower()
    if edition not in VALID_EDITIONS:
        print(f"ERROR: edition must be one of {sorted(VALID_EDITIONS)}; got {edition!r}", file=__import__("sys").stderr)
        return 1
    eks_mirror = bool_flag(args.eks_mirror) or bool(spec.get("eks_mirror", False))
    enable_dnsproxy = bool_flag(args.enable_dnsproxy) or bool((spec.get("enterprise_addons") or {}).get("cilium_dnsproxy", False))
    enable_hubble_enterprise = bool_flag(args.enable_hubble_enterprise) or bool((spec.get("enterprise_addons") or {}).get("hubble_enterprise", False))
    enable_timescape = bool_flag(args.enable_timescape) or bool((spec.get("enterprise_addons") or {}).get("hubble_timescape", False))
    export_mode = args.export_mode or (spec.get("tetragon") or {}).get("export", {}).get("mode", "file")
    namespaces = spec.get("namespaces") or {}
    cilium_ns = namespaces.get("cilium", "kube-system")
    tetragon_ns = namespaces.get("tetragon", "tetragon")
    hubble_ent_ns = namespaces.get("hubble_enterprise", "kube-system")
    dnsproxy_ns = namespaces.get("cilium_dnsproxy", "kube-system")
    timescape_ns = namespaces.get("hubble_timescape", "hubble-timescape")

    plan = {
        "skill": SKILL_NAME,
        "output_dir": str(Path(args.output_dir).resolve()),
        "edition": edition,
        "cluster_name": spec.get("cluster_name", "lab-cluster"),
        "eks_mirror": eks_mirror,
        "enable_dnsproxy": enable_dnsproxy,
        "enable_hubble_enterprise": enable_hubble_enterprise,
        "enable_timescape": enable_timescape,
        "export_mode": export_mode,
        "warnings": warnings(args, spec, edition),
    }

    if args.dry_run:
        if args.json:
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            print("Cisco Isovalent Platform Setup render plan")
            for key, value in plan.items():
                print(f"  {key}: {value}")
        return 0

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    write_yaml(out / "helm/cilium-values.yaml", cilium_values(spec, edition))
    write_yaml(out / "helm/tetragon-values.yaml", tetragon_values(spec, edition, args.export_mode))
    policy = tracing_policy(spec)
    if policy is not None:
        write_yaml(out / "helm/tracing-policy.yaml", policy)
    if edition == "enterprise" and enable_dnsproxy:
        write_yaml(out / "helm/cilium-dnsproxy-values.yaml", cilium_dnsproxy_values(spec))
    if edition == "enterprise" and enable_hubble_enterprise:
        write_yaml(out / "helm/hubble-enterprise-values.yaml", hubble_enterprise_values(spec, export_mode))
    if edition == "enterprise" and enable_timescape:
        write_yaml(out / "helm/hubble-timescape-values.yaml", hubble_timescape_values(spec))

    write_text(
        out / "scripts/install-cilium.sh",
        install_script(name="install-cilium.sh", body=cilium_install_body(edition, eks_mirror, cilium_ns)),
        executable=True,
    )
    write_text(
        out / "scripts/install-tetragon.sh",
        install_script(name="install-tetragon.sh", body=tetragon_install_body(edition, tetragon_ns)),
        executable=True,
    )
    if edition == "enterprise" and enable_dnsproxy:
        write_text(
            out / "scripts/install-cilium-dnsproxy.sh",
            install_script(name="install-cilium-dnsproxy.sh", body=cilium_dnsproxy_install_body(dnsproxy_ns)),
            executable=True,
        )
    if edition == "enterprise" and enable_hubble_enterprise:
        write_text(
            out / "scripts/install-hubble-enterprise.sh",
            install_script(name="install-hubble-enterprise.sh", body=hubble_enterprise_install_body(hubble_ent_ns)),
            executable=True,
        )
    if edition == "enterprise" and enable_timescape:
        write_text(
            out / "scripts/install-hubble-timescape.sh",
            install_script(name="install-hubble-timescape.sh", body=hubble_timescape_install_body(timescape_ns)),
            executable=True,
        )

    write_text(out / "scripts/preflight.sh", install_script(name="preflight.sh", body=preflight_body(spec, edition)), executable=True)
    if bool_flag(args.render_eksctl_example) or (spec.get("eks_byocni") or {}).get("render_eksctl_example", False):
        write_text(out / "scripts/eksctl-byocni-example.sh", eksctl_byocni_example(), executable=True)

    write_text(out / "metadata.json", json.dumps(render_metadata(args, spec, edition), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
