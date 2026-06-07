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
  - scripts/install-hubble-enterprise.sh  (Enterprise + --enable-hubble-enterprise; gated private unless access verified)
  - scripts/install-hubble-timescape.sh   (Enterprise + --enable-timescape; gated private unless access verified)
  - scripts/preflight.sh
  - scripts/eksctl-byocni-example.sh      (when --render-eksctl-example)
  - feature-catalog.json
  - feature-matrix.md
  - coverage-report.json
  - environment-profiles.json
  - environment-profiles.md
  - apply-plan.json
  - doctor-report.md
  - metadata.json
"""

from __future__ import annotations

import argparse
import copy
import hashlib
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
VALID_STATUSES = {
    "helm_apply",
    "kubectl_apply",
    "cli_apply",
    "live_validate",
    "discover_only",
    "delegated_handoff",
    "gated_private",
    "not_applicable",
    "unsupported_with_reason",
}
APPLY_SECTIONS = {
    "cilium",
    "tetragon",
    "hubble",
    "dnsproxy",
    "timescape",
    "load-balancer",
    "network-policy",
    "gateway-api",
    "ingress",
    "service-mesh",
    "clustermesh",
    "egress-gateway",
    "bgp",
    "lb-ipam",
    "l2-announcements",
    "encryption",
    "host-firewall",
    "runtime-policies",
}
SECTION_ALIASES = {
    "hubble-enterprise": "hubble",
    "hubble_enterprise": "hubble",
    "cilium-dnsproxy": "dnsproxy",
    "cilium_dnsproxy": "dnsproxy",
    "hubble-timescape": "timescape",
    "hubble_timescape": "timescape",
    "lb_ipam": "lb-ipam",
    "l2": "l2-announcements",
    "l2_announcements": "l2-announcements",
    "cluster-mesh": "clustermesh",
    "runtime_policy": "runtime-policies",
    "runtime_policy_bundle": "runtime-policies",
}
DISTRIBUTION_ALIASES = {
    "": "generic",
    "kubernetes": "generic",
    "k8s": "generic",
    "ocp": "openshift",
    "openshift4": "openshift",
    "eks_byocni": "eks-byocni",
    "eks-hybrid-nodes": "eks-hybrid",
    "aks": "aks-byocni",
    "aks_cilium": "aks-managed-cilium",
    "gke_dataplane_v2": "gke-dataplane-v2",
    "vsphere": "vmware-vsphere",
    "ack": "alibaba-ack",
}
MANAGED_CILIUM_DISTRIBUTIONS = {"aks-managed-cilium", "gke-dataplane-v2"}
DISRUPTIVE_SECTIONS = {
    "cilium",
    "clustermesh",
    "bgp",
    "l2-announcements",
    "encryption",
    "host-firewall",
    "load-balancer",
    "runtime-policies-enforcement",
}
CATALOG_PATH = Path(__file__).resolve().parents[1] / "catalog.json"

CILIUM_SECTION_VALUE_OVERRIDES: dict[str, dict[str, Any]] = {
    "gateway-api": {"gatewayAPI": {"enabled": True}},
    "ingress": {"ingressController": {"enabled": True}},
    "service-mesh": {
        "envoy": {"enabled": True},
        "gatewayAPI": {"enabled": True},
        "ingressController": {"enabled": True},
    },
    "egress-gateway": {"egressGateway": {"enabled": True}},
    "bgp": {"bgpControlPlane": {"enabled": True}},
    "l2-announcements": {"l2announcements": {"enabled": True}},
    "encryption": {"encryption": {"enabled": True, "type": "wireguard"}},
    "host-firewall": {"hostFirewall": {"enabled": True}},
}


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
    parser.add_argument("--distribution", default="", help="Distribution profile, e.g. generic, eks-byocni, openshift")
    parser.add_argument("--apply-sections", default="", help="Comma-separated scoped apply sections for apply-plan.json")
    parser.add_argument("--feature-matrix", action="store_true", help="Emit feature-matrix payload in dry-run/json mode")
    parser.add_argument("--private-chart-access-verified", action="store_true", help="Operator confirms private Isovalent chart access was verified.")
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


def load_catalog() -> dict[str, Any]:
    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SpecError(f"Failed to read Isovalent catalog {CATALOG_PATH}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SpecError(f"Failed to parse Isovalent catalog {CATALOG_PATH}: {exc}") from exc
    validate_catalog(catalog)
    return catalog


def validate_catalog(catalog: dict[str, Any]) -> None:
    features = catalog.get("features")
    if not isinstance(features, list) or not features:
        raise SpecError("Isovalent catalog must contain a non-empty features list.")
    allowed = set(catalog.get("allowed_statuses") or VALID_STATUSES)
    if allowed != VALID_STATUSES:
        raise SpecError("Isovalent catalog allowed_statuses does not match the skill status contract.")
    seen: set[str] = set()
    missing_fields: list[str] = []
    invalid_statuses: list[str] = []
    unreviewed: list[str] = []
    for item in features:
        if not isinstance(item, dict):
            raise SpecError("Isovalent catalog features must be objects.")
        feature_id = str(item.get("id") or "")
        if not feature_id:
            missing_fields.append("<missing id>")
            continue
        if feature_id in seen:
            raise SpecError(f"Duplicate Isovalent catalog feature id: {feature_id}")
        seen.add(feature_id)
        for field in ("product", "feature", "status", "source_url", "reason"):
            if not str(item.get(field) or "").strip():
                missing_fields.append(f"{feature_id}.{field}")
        status = str(item.get("status") or "")
        if status not in VALID_STATUSES:
            invalid_statuses.append(f"{feature_id}:{status}")
        if status in {"unsupported_with_reason", "not_applicable", "gated_private"} and not str(item.get("reason") or "").strip():
            unreviewed.append(feature_id)
    target_ids = set(catalog.get("target_feature_ids") or [])
    missing_targets = sorted(target_ids - seen)
    extra_targets = sorted(seen - target_ids)
    profiles = catalog.get("distribution_profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise SpecError("Isovalent catalog must contain distribution_profiles.")
    for profile_name, profile in profiles.items():
        if not isinstance(profile, dict):
            raise SpecError(f"Distribution profile {profile_name!r} must be an object.")
        for field in (
            "supported_install_path",
            "preflight_checks",
            "cloud_cni_conflicts",
            "kube_proxy_handling",
            "ipam_constraints",
            "required_privileges",
            "scc_psa_rbac_requirements",
            "kernel_ebpf_requirements",
            "lb_ipam_limitations",
            "not_applicable_features",
        ):
            if field not in profile:
                missing_fields.append(f"distribution_profiles.{profile_name}.{field}")
    required_profiles = {
        "generic",
        "kubeadm",
        "kind",
        "minikube",
        "kops",
        "eks",
        "eks-byocni",
        "eks-hybrid",
        "aks-byocni",
        "aks-managed-cilium",
        "gke",
        "gke-dataplane-v2",
        "openshift",
        "rke2",
        "rancher",
        "k3s",
        "k0s",
        "talos",
        "vmware-vsphere",
        "alibaba-ack",
    }
    missing_profiles = sorted(required_profiles - set(profiles))
    errors = []
    if missing_fields:
        errors.append("missing catalog fields: " + ", ".join(sorted(missing_fields)))
    if invalid_statuses:
        errors.append("invalid catalog statuses: " + ", ".join(sorted(invalid_statuses)))
    if unreviewed:
        errors.append("unreviewed gated/unsupported features: " + ", ".join(sorted(unreviewed)))
    if missing_targets:
        errors.append("missing target feature rows: " + ", ".join(missing_targets))
    if extra_targets:
        errors.append("features not listed in target_feature_ids: " + ", ".join(extra_targets))
    if missing_profiles:
        errors.append("missing distribution profiles: " + ", ".join(missing_profiles))
    if errors:
        raise SpecError("; ".join(errors))


def effective_catalog(catalog: dict[str, Any], *, private_chart_access_verified: bool) -> dict[str, Any]:
    result = copy.deepcopy(catalog)
    if not private_chart_access_verified:
        return result
    for item in result.get("features", []):
        if item.get("id") in {"isovalent.hubble_enterprise", "isovalent.hubble_timescape"}:
            item["status"] = "helm_apply"
            item["reason"] = (
                "Private Isovalent chart access was verified by operator flag; "
                "rendered scripts perform helm show values before upgrade/install."
            )
            item["private_chart_access_verified"] = True
    return result


def normalize_distribution(value: str) -> str:
    key = (value or "").strip().lower()
    return DISTRIBUTION_ALIASES.get(key, key or "generic")


def selected_apply_sections(raw: str) -> list[str]:
    if not raw:
        return ["cilium", "tetragon"]
    sections: list[str] = []
    for token in raw.split(","):
        key = token.strip().lower().replace("_", "-")
        if not key:
            continue
        key = SECTION_ALIASES.get(key, key)
        if key not in APPLY_SECTIONS:
            raise SpecError(f"Unknown apply section {token!r}; valid sections: {', '.join(sorted(APPLY_SECTIONS))}")
        if key not in sections:
            sections.append(key)
    return sections or ["cilium", "tetragon"]


def write_text(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def write_yaml(path: Path, payload: Any) -> None:
    write_text(path, dump_yaml(payload, sort_keys=True))


def write_json(path: Path, payload: Any) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def cilium_values(spec: dict[str, Any], edition: str) -> dict[str, Any]:
    overrides = (spec.get("cilium") or {})
    base: dict[str, Any] = {
        "cluster": {
            "name": spec.get("cluster_name", "lab-cluster"),
        },
        "ipam": {"mode": "kubernetes"},
        "kubeProxyReplacement": True,
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
            "tls": {
                "enabled": True,
                "auto": {
                    "enabled": True,
                    "method": "cronJob",
                    "schedule": "0 0 1 */4 *",
                },
            },
        },
    }
    # Enterprise feature gate. The Isovalent Enterprise chart accepts
    # `enterprise.featureGate`; OSS chart ignores it and continues without
    # Enterprise-only features. Set explicitly for clarity.
    if edition == "enterprise":
        base["enterprise"] = {"featureGate": "v1.18"}
    return _deep_merge(base, overrides)


def cilium_section_values(spec: dict[str, Any], section: str) -> dict[str, Any]:
    """Return a section-specific Helm values overlay.

    These overlays intentionally contain only chart-supported toggles for the
    selected surface. Site-specific CRDs such as BGP peers, egress policies, or
    IP pools still belong in reviewed customer manifests.
    """
    base = CILIUM_SECTION_VALUE_OVERRIDES.get(section, {})
    section_overrides = ((spec.get("cilium_feature_overrides") or {}).get(section) or {})
    return _deep_merge(base, section_overrides)


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
    export_file_perm = str(export_block.get("file_perm", "644"))
    enable_events = (overrides.get("enable_events") or {})
    base: dict[str, Any] = {
        "tetragon": {
            "clusterName": spec.get("cluster_name", "lab-cluster"),
            "enableEvents": {
                "network": bool(enable_events.get("network", True)),
            },
            "exportDirectory": export_directory,
            "exportFilename": export_filename,
            "exportFilePerm": export_file_perm,
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


def status_counts(features: list[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in sorted(VALID_STATUSES)}
    for item in features:
        counts[str(item["status"])] += 1
    return counts


def feature_matrix_markdown(catalog: dict[str, Any]) -> str:
    lines = [
        "# Cisco Isovalent Platform Feature Matrix",
        "",
        "Every target product row has one explicit automation status.",
        "",
        "| Product | Feature | Status | Apply section | Source | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for item in catalog["features"]:
        lines.append(
            "| {product} | {feature} | `{status}` | `{section}` | [source]({source}) | {reason} |".format(
                product=item["product"],
                feature=item["feature"],
                status=item["status"],
                section=item.get("apply_section", ""),
                source=item["source_url"],
                reason=str(item["reason"]).replace("|", "\\|"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def environment_profiles_markdown(catalog: dict[str, Any]) -> str:
    lines = [
        "# Isovalent Kubernetes Distribution Profiles",
        "",
        "| Distribution | Install path | Kube-proxy | IPAM | LB/IPAM limits |",
        "|---|---|---|---|---|",
    ]
    for name, profile in sorted(catalog["distribution_profiles"].items()):
        lines.append(
            "| `{name}` | {path} | {kube_proxy} | {ipam} | {lb} |".format(
                name=name,
                path=str(profile["supported_install_path"]).replace("|", "\\|"),
                kube_proxy=str(profile["kube_proxy_handling"]).replace("|", "\\|"),
                ipam=str(profile["ipam_constraints"]).replace("|", "\\|"),
                lb=str(profile["lb_ipam_limitations"]).replace("|", "\\|"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def coverage_report(catalog: dict[str, Any], distribution: str) -> dict[str, Any]:
    feature_ids = {str(item["id"]) for item in catalog["features"]}
    target_ids = set(catalog["target_feature_ids"])
    missing = sorted(target_ids - feature_ids)
    unsupported_without_reason = sorted(
        str(item["id"])
        for item in catalog["features"]
        if item["status"] in {"unsupported_with_reason", "not_applicable", "gated_private"}
        and not str(item.get("reason") or "").strip()
    )
    profile = catalog["distribution_profiles"].get(distribution, catalog["distribution_profiles"]["generic"])
    return {
        "api_version": f"{SKILL_NAME}/coverage/v1",
        "skill": SKILL_NAME,
        "distribution": distribution,
        "ok": not missing and not unsupported_without_reason,
        "missing_features": missing,
        "unsupported_without_reason": unsupported_without_reason,
        "status_counts": status_counts(catalog["features"]),
        "target_feature_count": len(target_ids),
        "covered_feature_count": len(feature_ids),
        "features": catalog["features"],
        "distribution_profile": profile,
    }


def values_hash(output_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((output_dir / "helm").glob("*.yaml")):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def apply_plan(
    *,
    args: argparse.Namespace,
    spec: dict[str, Any],
    catalog: dict[str, Any],
    edition: str,
    distribution: str,
    output_dir: Path,
    sections: list[str],
    namespaces: dict[str, Any],
    eks_mirror: bool,
    enable_dnsproxy: bool,
    enable_hubble_enterprise: bool,
    enable_timescape: bool,
) -> dict[str, Any]:
    private_chart_access_verified = bool(getattr(args, "private_chart_access_verified", False))
    enterprise_license_sections = {
        "cilium",
        "tetragon",
        "dnsproxy",
        "hubble",
        "timescape",
        "gateway-api",
        "ingress",
        "service-mesh",
        "egress-gateway",
        "bgp",
        "l2-announcements",
        "encryption",
        "host-firewall",
    }
    features_by_section: dict[str, list[str]] = {section: [] for section in APPLY_SECTIONS}
    for item in catalog["features"]:
        section = str(item.get("apply_section") or "")
        section = SECTION_ALIASES.get(section, section)
        if section in features_by_section:
            features_by_section[section].append(str(item["id"]))
    cilium_ns = namespaces.get("cilium", "kube-system")
    tetragon_ns = namespaces.get("tetragon", "tetragon")
    steps: list[dict[str, Any]] = []
    for section in sections:
        if section == "cilium":
            namespace = cilium_ns
            command = ["bash", str(output_dir / "scripts/install-cilium.sh")]
        elif section == "tetragon":
            namespace = tetragon_ns
            command = ["bash", str(output_dir / "scripts/install-tetragon.sh")]
        elif section == "dnsproxy":
            namespace = namespaces.get("cilium_dnsproxy", "kube-system")
            command = ["bash", str(output_dir / "scripts/install-cilium-dnsproxy.sh")]
        elif section == "timescape":
            namespace = namespaces.get("hubble_timescape", "hubble-timescape")
            command = ["bash", str(output_dir / "scripts/install-hubble-timescape.sh")]
        elif section == "hubble":
            namespace = namespaces.get("hubble_enterprise", "kube-system")
            command = ["bash", str(output_dir / "scripts/apply-hubble.sh")]
        elif section in {"network-policy", "lb-ipam", "runtime-policies"}:
            namespace = cilium_ns if section != "runtime-policies" else tetragon_ns
            command = ["bash", str(output_dir / f"scripts/apply-{section}.sh")]
        else:
            namespace = cilium_ns
            command = ["bash", str(output_dir / f"scripts/apply-{section}.sh")]
        if section == "cilium" and distribution in MANAGED_CILIUM_DISTRIBUTIONS:
            command_class = "discover_only"
        elif (
            section == "load-balancer"
            or (section == "dnsproxy" and edition != "enterprise")
            or (section in {"hubble", "timescape"} and (edition != "enterprise" or not private_chart_access_verified))
        ):
            command_class = "gated_private"
        elif section == "clustermesh":
            command_class = "cli_apply"
        else:
            command_class = "mutating"
        automation = "cli" if command_class == "cli_apply" else "helm_or_kubectl"
        if command_class == "discover_only":
            automation = "none"
        steps.append(
            {
                "section": section,
                "automation": automation,
                "command_class": command_class,
                "requires_accept_k8s_apply": command_class in {"mutating", "cli_apply"},
                "requires_accept_isovalent_disruptive_change": (
                    command_class in {"mutating", "cli_apply"} and section in DISRUPTIVE_SECTIONS
                ),
                "requires_isovalent_license_file": (
                    edition == "enterprise"
                    and command_class == "mutating"
                    and section in enterprise_license_sections
                    and not eks_mirror
                ),
                "namespace": namespace,
                "features": features_by_section.get(section, []),
                "command": command,
                "dry_run": {
                    "supported": True,
                    "environment": "K8S_APPLY_DRY_RUN=true",
                },
            }
        )
    return {
        "api_version": f"{SKILL_NAME}/apply-plan/v1",
        "skill": SKILL_NAME,
        "edition": edition,
        "distribution": distribution,
        "cluster_name": spec.get("cluster_name", "lab-cluster"),
        "output_dir": str(output_dir),
        "selected_sections": sections,
        "eks_mirror": eks_mirror,
        "enterprise_addons": {
            "dnsproxy": enable_dnsproxy,
            "hubble_enterprise": enable_hubble_enterprise,
            "timescape": enable_timescape,
        },
        "live_action_state_contract": {
            "kube_context": "<recorded at live execution>",
            "namespaces": namespaces,
            "chart_versions": "<helm show/status at live execution>",
            "helm_release_revisions": "<helm history at live execution>",
            "values_hash": values_hash(output_dir) if output_dir.exists() else "",
            "crds_applied": "<recorded for kubectl apply sections>",
            "previous_values_path": "backup/<timestamp>/helm-values",
            "command_class": "rendered_plan",
            "rollback_hints": [
                "Use generated backup before mutation.",
                "Use rollback-plan.md and Helm release history for release rollback.",
                "Do not uninstall Cilium from a live workload cluster without alternate networking validated.",
            ],
        },
        "steps": steps,
    }


def doctor_report_markdown(
    *,
    catalog: dict[str, Any],
    distribution: str,
    warnings_list: list[str],
    sections: list[str],
) -> str:
    coverage = coverage_report(catalog, distribution)
    gated = [item for item in catalog["features"] if item["status"] == "gated_private"]
    lines = [
        "# Cisco Isovalent Platform Doctor Report",
        "",
        f"Distribution profile: `{distribution}`",
        f"Coverage OK: `{str(coverage['ok']).lower()}`",
        f"Missing feature rows: `{len(coverage['missing_features'])}`",
        f"Selected apply sections: `{','.join(sections)}`",
        "",
        "## Warnings",
    ]
    if warnings_list:
        lines.extend(f"- {item}" for item in warnings_list)
    else:
        lines.append("- None.")
    lines.extend(["", "## Gated Private Workflows"])
    for item in gated:
        lines.append(
            f"- `{item['id']}`: {item['reason']} Verify customer docs and chart access with `helm repo add isovalent {ENTERPRISE_REPO_URL}` then `helm show values {item.get('chart', '<private-chart>')}` before apply."
        )
    lines.extend(
        [
            "",
            "## Day-2 Operations",
            "- `--discover`: read-only inventory of Helm releases, Cilium/Tetragon CRDs, nodes, and CLI availability.",
            "- `--preflight`: read-only kernel, CNI conflict, distribution, and Enterprise chart-access checks.",
            "- `--validate --live`: read-only status and metrics endpoint probes.",
            "- `--backup`: read-only Helm values/history backup before mutation.",
            "- `--upgrade-plan`: render target chart/version and values-hash review before upgrade.",
            "- `--rollback-plan`: render Helm rollback commands and CNI replacement cautions.",
            "- `--uninstall-plan`: render an uninstall runbook with networking continuity warnings.",
            "",
        ]
    )
    return "\n".join(lines)


def openshift_scc_manifest(spec: dict[str, Any]) -> dict[str, Any]:
    namespaces = spec.get("namespaces") or {}
    service_accounts = [
        {"namespace": namespaces.get("cilium", "kube-system"), "name": "cilium"},
        {"namespace": namespaces.get("tetragon", "tetragon"), "name": "tetragon"},
    ]
    return {
        "apiVersion": "security.openshift.io/v1",
        "kind": "SecurityContextConstraints",
        "metadata": {"name": "isovalent-platform-privileged"},
        "allowHostDirVolumePlugin": True,
        "allowHostNetwork": True,
        "allowHostPID": True,
        "allowHostPorts": True,
        "allowPrivilegedContainer": True,
        "allowedCapabilities": ["*"],
        "fsGroup": {"type": "RunAsAny"},
        "runAsUser": {"type": "RunAsAny"},
        "seLinuxContext": {"type": "RunAsAny"},
        "supplementalGroups": {"type": "RunAsAny"},
        "users": [
            f"system:serviceaccount:{item['namespace']}:{item['name']}"
            for item in service_accounts
        ],
        "volumes": ["*"],
    }


def install_script(*, name: str, body: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        f"# {name}\n"
        'KUBECTL=(kubectl)\n'
        'HELM=(helm)\n'
        'if [[ -n "${KUBE_CONTEXT:-}" ]]; then\n'
        '    KUBECTL=(kubectl --context "${KUBE_CONTEXT}")\n'
        '    HELM=(helm --kube-context "${KUBE_CONTEXT}")\n'
        'fi\n'
        'HELM_DRY_RUN=()\n'
        'KUBECTL_DRY_RUN=()\n'
        'if [[ "${K8S_APPLY_DRY_RUN:-false}" == "true" ]]; then\n'
        '    HELM_DRY_RUN=(--dry-run)\n'
        '    KUBECTL_DRY_RUN=(--dry-run=server)\n'
        'fi\n\n'
        f"{body}\n"
    )


def enterprise_secret_args_body(chart: str, license_pattern: str = "license|enterprise") -> str:
    return (
        'SET_FILE_ARGS=()\n'
        'SET_ARGS=()\n'
        'if [[ "${K8S_APPLY_DRY_RUN:-false}" != "true" && -z "${ISOVALENT_LICENSE_FILE:-}" ]]; then\n'
        '    echo "ERROR: Enterprise apply requires ISOVALENT_LICENSE_FILE via --isovalent-license-file." >&2\n'
        '    exit 1\n'
        'fi\n'
        'if [[ -n "${ISOVALENT_LICENSE_FILE:-}" ]]; then\n'
        f'    "${{HELM[@]}}" show values "{chart}" | grep -E "{license_pattern}" >/dev/null || {{\n'
        f'        echo "ERROR: could not verify license-related chart values for {chart}." >&2\n'
        '        exit 1\n'
        '    }\n'
        '    SET_FILE_ARGS+=(--set-file "enterprise.license=${ISOVALENT_LICENSE_FILE}")\n'
        'fi\n'
        'if [[ -n "${ISOVALENT_PULL_SECRET_FILE:-}" ]]; then\n'
        '    if [[ "${K8S_APPLY_DRY_RUN:-false}" == "true" ]]; then\n'
        '        "${KUBECTL[@]}" create namespace "${NAMESPACE}" --dry-run=client -o yaml >/dev/null\n'
        '        "${KUBECTL[@]}" -n "${NAMESPACE}" create secret generic isovalent-pull-secret \\\n'
        '            --from-file=.dockerconfigjson="${ISOVALENT_PULL_SECRET_FILE}" \\\n'
        '            --type=kubernetes.io/dockerconfigjson --dry-run=client -o yaml >/dev/null\n'
        '    else\n'
        '        "${KUBECTL[@]}" create namespace "${NAMESPACE}" --dry-run=client -o yaml | "${KUBECTL[@]}" apply -f -\n'
        '        "${KUBECTL[@]}" -n "${NAMESPACE}" create secret generic isovalent-pull-secret \\\n'
        '            --from-file=.dockerconfigjson="${ISOVALENT_PULL_SECRET_FILE}" \\\n'
        '            --type=kubernetes.io/dockerconfigjson --dry-run=client -o yaml | "${KUBECTL[@]}" apply -f -\n'
        '    fi\n'
        '    SET_ARGS+=(--set "imagePullSecrets[0].name=isovalent-pull-secret")\n'
        'fi\n'
    )


def cilium_install_body(edition: str, eks_mirror: bool, namespace: str, distribution: str = "generic") -> str:
    if distribution in MANAGED_CILIUM_DISTRIBUTIONS:
        return (
            f'NAMESPACE="${{1:-{namespace}}}"\n'
            f'echo "ERROR: {distribution} uses a provider-managed Cilium dataplane." >&2\n'
            'echo "This skill will not Helm-replace provider-owned Cilium. Use --discover, --preflight, --validate, or a provider-supported BYOCNI migration path." >&2\n'
            'exit 1\n'
        )
    chart = OSS_CILIUM_CHART
    repo_setup = (
        f'"${{HELM[@]}}" repo add {OSS_REPO_NAME} {OSS_REPO_URL}\n'
        f'"${{HELM[@]}}" repo update {OSS_REPO_NAME}\n'
    )
    secret_setup = "SET_FILE_ARGS=()\nSET_ARGS=()\n"
    if edition == "enterprise":
        chart = ENTERPRISE_CILIUM_CHART
        repo_setup = (
            f'"${{HELM[@]}}" repo add {ENTERPRISE_REPO_NAME} {ENTERPRISE_REPO_URL}\n'
            f'"${{HELM[@]}}" repo update {ENTERPRISE_REPO_NAME}\n'
        )
        secret_setup = enterprise_secret_args_body(chart)
    if eks_mirror:
        # AWS publishes Cilium for EKS Hybrid Nodes via OCI. When the operator
        # asks for the EKS-AWS mirror we install from the OCI registry instead
        # of helm.cilium.io.
        chart = EKS_AWS_MIRROR_OCI
        repo_setup = "# EKS-AWS mirror: chart is an OCI URL; no helm repo add needed.\n"
        secret_setup = "SET_FILE_ARGS=()\nSET_ARGS=()\n"
    return (
        f'NAMESPACE="${{1:-{namespace}}}"\n'
        f"{repo_setup}"
        f"{secret_setup}"
        f'"${{HELM[@]}}" upgrade --install cilium "{chart}" \\\n'
        '    -n "${NAMESPACE}" --create-namespace \\\n'
        '    -f "$(dirname "${BASH_SOURCE[0]}")/../helm/cilium-values.yaml" \\\n'
        '    "${SET_FILE_ARGS[@]}" "${SET_ARGS[@]}" "${HELM_DRY_RUN[@]}"\n'
        'if [[ "${K8S_APPLY_DRY_RUN:-false}" != "true" ]]; then\n'
        '    "${KUBECTL[@]}" -n "${NAMESPACE}" rollout status ds/cilium --timeout=300s\n'
        'fi\n'
    )


def tetragon_install_body(edition: str, namespace: str) -> str:
    chart = OSS_TETRAGON_CHART
    repo_setup = (
        f'"${{HELM[@]}}" repo add {OSS_REPO_NAME} {OSS_REPO_URL}\n'
        f'"${{HELM[@]}}" repo update {OSS_REPO_NAME}\n'
    )
    secret_setup = "SET_FILE_ARGS=()\nSET_ARGS=()\n"
    if edition == "enterprise":
        chart = ENTERPRISE_TETRAGON_CHART
        repo_setup = (
            f'"${{HELM[@]}}" repo add {ENTERPRISE_REPO_NAME} {ENTERPRISE_REPO_URL}\n'
            f'"${{HELM[@]}}" repo update {ENTERPRISE_REPO_NAME}\n'
        )
        secret_setup = enterprise_secret_args_body(chart, "license|enterprise|tetragon")
    return (
        f'NAMESPACE="${{1:-{namespace}}}"\n'
        f"{repo_setup}"
        f"{secret_setup}"
        f'"${{HELM[@]}}" upgrade --install tetragon "{chart}" \\\n'
        '    -n "${NAMESPACE}" --create-namespace \\\n'
        '    -f "$(dirname "${BASH_SOURCE[0]}")/../helm/tetragon-values.yaml" \\\n'
        '    "${SET_FILE_ARGS[@]}" "${SET_ARGS[@]}" "${HELM_DRY_RUN[@]}"\n'
        'if [[ "${K8S_APPLY_DRY_RUN:-false}" != "true" ]]; then\n'
        '    "${KUBECTL[@]}" -n "${NAMESPACE}" rollout status ds/tetragon --timeout=300s\n'
        'fi\n'
        '# Apply the starter TracingPolicy if present.\n'
        'POLICY="$(dirname "${BASH_SOURCE[0]}")/../helm/tracing-policy.yaml"\n'
        '[[ -f "${POLICY}" ]] && "${KUBECTL[@]}" apply -f "${POLICY}" "${KUBECTL_DRY_RUN[@]}"\n'
    )


def cilium_dnsproxy_install_body(namespace: str) -> str:
    return (
        f'NAMESPACE="${{1:-{namespace}}}"\n'
        f'"${{HELM[@]}}" repo add {ENTERPRISE_REPO_NAME} {ENTERPRISE_REPO_URL}\n'
        f'"${{HELM[@]}}" repo update {ENTERPRISE_REPO_NAME}\n'
        f"{enterprise_secret_args_body(ENTERPRISE_DNSPROXY_CHART)}"
        f'"${{HELM[@]}}" upgrade --install cilium-dnsproxy "{ENTERPRISE_DNSPROXY_CHART}" \\\n'
        '    -n "${NAMESPACE}" --create-namespace \\\n'
        '    -f "$(dirname "${BASH_SOURCE[0]}")/../helm/cilium-dnsproxy-values.yaml" \\\n'
        '    "${SET_FILE_ARGS[@]}" "${SET_ARGS[@]}" "${HELM_DRY_RUN[@]}"\n'
    )


def hubble_enterprise_install_body(namespace: str, *, private_chart_access_verified: bool = False) -> str:
    if private_chart_access_verified:
        return (
            f'NAMESPACE="${{1:-{namespace}}}"\n'
            f'"${{HELM[@]}}" repo add {ENTERPRISE_REPO_NAME} {ENTERPRISE_REPO_URL}\n'
            f'"${{HELM[@]}}" repo update {ENTERPRISE_REPO_NAME}\n'
            f'"${{HELM[@]}}" show values "{ENTERPRISE_HUBBLE_ENT_CHART}" >/dev/null\n'
            f"{enterprise_secret_args_body(ENTERPRISE_HUBBLE_ENT_CHART)}"
            f'"${{HELM[@]}}" upgrade --install hubble-enterprise "{ENTERPRISE_HUBBLE_ENT_CHART}" \\\n'
            '    -n "${NAMESPACE}" --create-namespace \\\n'
            '    -f "$(dirname "${BASH_SOURCE[0]}")/../helm/hubble-enterprise-values.yaml" \\\n'
            '    "${SET_FILE_ARGS[@]}" "${SET_ARGS[@]}" "${HELM_DRY_RUN[@]}"\n'
        )
    # Hubble Enterprise is a private chart. Without an explicit access
    # assertion, fail closed and print the customer access runbook.
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
        'exit 1\n'
    )


def hubble_timescape_install_body(namespace: str, *, private_chart_access_verified: bool = False) -> str:
    if not private_chart_access_verified:
        return gated_private_body("Hubble Timescape")
    return (
        f'NAMESPACE="${{1:-{namespace}}}"\n'
        f'"${{HELM[@]}}" repo add {ENTERPRISE_REPO_NAME} {ENTERPRISE_REPO_URL}\n'
        f'"${{HELM[@]}}" repo update {ENTERPRISE_REPO_NAME}\n'
        f'"${{HELM[@]}}" show values "{ENTERPRISE_TIMESCAPE_CHART}" >/dev/null\n'
        f"{enterprise_secret_args_body(ENTERPRISE_TIMESCAPE_CHART)}"
        f'"${{HELM[@]}}" upgrade --install hubble-timescape "{ENTERPRISE_TIMESCAPE_CHART}" \\\n'
        '    -n "${NAMESPACE}" --create-namespace \\\n'
        '    -f "$(dirname "${BASH_SOURCE[0]}")/../helm/hubble-timescape-values.yaml" \\\n'
        '    "${SET_FILE_ARGS[@]}" "${SET_ARGS[@]}" "${HELM_DRY_RUN[@]}"\n'
    )


def preflight_body(spec: dict[str, Any], edition: str, distribution: str, catalog: dict[str, Any]) -> str:
    eks_byocni = (spec.get("eks_byocni") or {})
    kernel = (spec.get("kernel_preflight") or {})
    minimum_kernel = kernel.get("minimum_version", "5.10")
    profile = catalog["distribution_profiles"].get(distribution, catalog["distribution_profiles"]["generic"])
    body = [
        "# Preflight checks for Cilium / Tetragon install.",
        f'echo "Distribution profile: {distribution}"',
        f'echo "Install path: {profile["supported_install_path"]}"',
        f'echo "Kube-proxy handling: {profile["kube_proxy_handling"]}"',
        f'echo "IPAM constraints: {profile["ipam_constraints"]}"',
    ]
    if kernel.get("enable", True):
        body.append(
            f'echo "Kernel check: minimum {minimum_kernel} required for Cilium v1.18.x."'
        )
        body.append(
            '"${KUBECTL[@]}" get nodes -o jsonpath=\'{range .items[*]}{.metadata.name}{"\\t"}{.status.nodeInfo.kernelVersion}{"\\n"}{end}\' \\\n'
            f'    | awk -v min="{minimum_kernel}" \'{{split($2,a,/[.-]/); split(min,b,/[.-]/);'
            ' ok=(a[1]>b[1] || (a[1]==b[1] && a[2]>=b[2])); printf "%s\\t%s\\t%s\\n", $1, $2, ok?"OK":"WARN"}\''
        )
    if eks_byocni.get("enable_preflight", True):
        body.append(
            'if "${KUBECTL[@]}" -n kube-system get ds aws-node >/dev/null 2>&1; then'
        )
        body.append(
            '    echo "WARN: AWS VPC CNI (aws-node DaemonSet) is installed; Cilium requires BYOCNI (--network-plugin none)."'
        )
        body.append("fi")
    if distribution == "openshift":
        body.append(
            'if ! "${KUBECTL[@]}" api-resources | grep -q SecurityContextConstraints; then'
        )
        body.append('    echo "WARN: OpenShift profile selected but SCC API was not found."')
        body.append("fi")
    if distribution in MANAGED_CILIUM_DISTRIBUTIONS:
        body.append(
            f'echo "WARN: {distribution} owns the managed Cilium dataplane; CNI replacement is discover-only unless the provider-supported path explicitly allows it."'
        )
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


def helm_section_apply_body(section: str, edition: str, eks_mirror: bool, namespace: str) -> str:
    chart = ENTERPRISE_CILIUM_CHART if edition == "enterprise" else OSS_CILIUM_CHART
    repo_setup = (
        f'"${{HELM[@]}}" repo add {OSS_REPO_NAME} {OSS_REPO_URL}\n'
        f'"${{HELM[@]}}" repo update {OSS_REPO_NAME}\n'
    )
    secret_setup = "SET_FILE_ARGS=()\nSET_ARGS=()\n"
    if edition == "enterprise":
        repo_setup = (
            f'"${{HELM[@]}}" repo add {ENTERPRISE_REPO_NAME} {ENTERPRISE_REPO_URL}\n'
            f'"${{HELM[@]}}" repo update {ENTERPRISE_REPO_NAME}\n'
        )
        secret_setup = enterprise_secret_args_body(chart)
    if eks_mirror:
        chart = EKS_AWS_MIRROR_OCI
        repo_setup = "# EKS-AWS mirror: chart is an OCI URL; no helm repo add needed.\n"
        secret_setup = "SET_FILE_ARGS=()\nSET_ARGS=()\n"
    overlay = f"../helm/cilium-section-{section}-values.yaml"
    return (
        f'NAMESPACE="${{1:-{namespace}}}"\n'
        f"{repo_setup}"
        f"{secret_setup}"
        f'OVERLAY="$(dirname "${{BASH_SOURCE[0]}}")/{overlay}"\n'
        'if [[ ! -f "${OVERLAY}" ]]; then\n'
        f'    echo "ERROR: values overlay for {section} not found: ${{OVERLAY}}" >&2\n'
        '    exit 1\n'
        'fi\n'
        f'echo "Applying scoped Cilium section: {section}"\n'
        f'"${{HELM[@]}}" upgrade --install cilium "{chart}" \\\n'
        '    -n "${NAMESPACE}" --create-namespace \\\n'
        '    -f "$(dirname "${BASH_SOURCE[0]}")/../helm/cilium-values.yaml" \\\n'
        '    -f "${OVERLAY}" \\\n'
        '    "${SET_FILE_ARGS[@]}" "${SET_ARGS[@]}" "${HELM_DRY_RUN[@]}"\n'
        'if [[ "${K8S_APPLY_DRY_RUN:-false}" != "true" ]]; then\n'
        '    "${KUBECTL[@]}" -n "${NAMESPACE}" rollout status ds/cilium --timeout=300s\n'
        'fi\n'
    )


def clustermesh_cli_body(namespace: str) -> str:
    return (
        f'NAMESPACE="${{1:-{namespace}}}"\n'
        'SERVICE_TYPE="${CILIUM_CLUSTERMESH_SERVICE_TYPE:-LoadBalancer}"\n'
        'REMOTE_CONTEXTS="${CILIUM_CLUSTERMESH_REMOTE_CONTEXTS:-}"\n'
        'CONTEXT_ARGS=()\n'
        'if [[ -n "${KUBE_CONTEXT:-}" ]]; then\n'
        '    CONTEXT_ARGS=(--context "${KUBE_CONTEXT}")\n'
        'fi\n'
        'ENABLE_CMD=(cilium clustermesh enable "${CONTEXT_ARGS[@]}" --service-type "${SERVICE_TYPE}")\n'
        'if [[ "${K8S_APPLY_DRY_RUN:-false}" == "true" ]]; then\n'
        '    printf "DRY-RUN: "; printf "%q " "${ENABLE_CMD[@]}"; printf "\\n"\n'
        '    if [[ -n "${REMOTE_CONTEXTS}" ]]; then\n'
        '        IFS="," read -ra _REMOTE_CTXS <<< "${REMOTE_CONTEXTS}"\n'
        '        for remote in "${_REMOTE_CTXS[@]}"; do\n'
        '            remote="$(printf "%s" "${remote}" | tr -d "[:space:]")"\n'
        '            [[ -z "${remote}" ]] && continue\n'
        '            CONNECT_CMD=(cilium clustermesh connect "${CONTEXT_ARGS[@]}" --destination-context "${remote}")\n'
        '            printf "DRY-RUN: "; printf "%q " "${CONNECT_CMD[@]}"; printf "\\n"\n'
        '        done\n'
        '    fi\n'
        '    exit 0\n'
        'fi\n'
        'if ! command -v cilium >/dev/null 2>&1; then\n'
        '    echo "ERROR: cilium CLI not found; install it or run --apply clustermesh --dry-run for the planned commands." >&2\n'
        '    exit 1\n'
        'fi\n'
        '"${ENABLE_CMD[@]}"\n'
        'if [[ -n "${REMOTE_CONTEXTS}" ]]; then\n'
        '    IFS="," read -ra _REMOTE_CTXS <<< "${REMOTE_CONTEXTS}"\n'
        '    for remote in "${_REMOTE_CTXS[@]}"; do\n'
        '        remote="$(printf "%s" "${remote}" | tr -d "[:space:]")"\n'
        '        [[ -z "${remote}" ]] && continue\n'
        '        cilium clustermesh connect "${CONTEXT_ARGS[@]}" --destination-context "${remote}"\n'
        '    done\n'
        'fi\n'
    )


def kubectl_manifest_apply_body(name: str, manifest: str, namespace: str) -> str:
    return (
        f'NAMESPACE="${{1:-{namespace}}}"\n'
        f'MANIFEST="$(dirname "${{BASH_SOURCE[0]}}")/../{manifest}"\n'
        'if [[ ! -f "${MANIFEST}" ]]; then\n'
        f'    echo "ERROR: manifest for {name} not found: ${{MANIFEST}}" >&2\n'
        '    exit 1\n'
        'fi\n'
        f'echo "Applying {name}: ${{MANIFEST}}"\n'
        '"${KUBECTL[@]}" apply -f "${MANIFEST}" "${KUBECTL_DRY_RUN[@]}"\n'
    )


def gated_private_body(product: str) -> str:
    return (
        f'cat <<EOF\n'
        f'{product} is gated behind private Cisco Isovalent customer documentation and/or chart access.\n'
        f'No Kubernetes mutation was attempted.\n'
        f'\n'
        f'Access workflow:\n'
        f'  1. Confirm entitlement and chart/customer-doc access with Cisco Isovalent.\n'
        f'  2. Run: helm repo add {ENTERPRISE_REPO_NAME} {ENTERPRISE_REPO_URL}\n'
        f'  3. Run: helm repo update {ENTERPRISE_REPO_NAME}\n'
        f'  4. Run: helm show values <private-chart> and map values into the rendered spec.\n'
        f'  5. Re-run this skill with --edition enterprise and the relevant scoped section.\n'
        f'EOF\n'
        f'exit 1\n'
    )


def network_policy_manifest() -> dict[str, Any]:
    return {
        "apiVersion": "cilium.io/v2",
        "kind": "CiliumNetworkPolicy",
        "metadata": {"name": "isovalent-observe-dns", "namespace": "default"},
        "spec": {
            "endpointSelector": {},
            "egress": [
                {
                    "toEndpoints": [
                        {
                            "matchLabels": {
                                "k8s:io.kubernetes.pod.namespace": "kube-system",
                                "k8s:k8s-app": "kube-dns",
                            }
                        }
                    ],
                    "toPorts": [
                        {
                            "ports": [{"port": "53", "protocol": "ANY"}],
                            "rules": {"dns": [{"matchPattern": "*"}]},
                        }
                    ],
                }
            ],
        },
    }


def lb_ipam_manifest() -> dict[str, Any]:
    return {
        "apiVersion": "cilium.io/v2alpha1",
        "kind": "CiliumLoadBalancerIPPool",
        "metadata": {"name": "isovalent-example-pool"},
        "spec": {
            "blocks": [{"cidr": "10.0.10.0/24"}],
            "serviceSelector": {"matchLabels": {"isovalent.example/lb": "true"}},
        },
    }


def runtime_policy_bundle() -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            {
                "apiVersion": "cilium.io/v1alpha1",
                "kind": "TracingPolicy",
                "metadata": {"name": "isovalent-runtime-exec-watch"},
                "spec": {
                    "kprobes": [
                        {
                            "call": "security_bprm_check",
                            "syscall": False,
                            "args": [{"index": 0, "type": "linux_binprm"}],
                            "selectors": [
                                {
                                    "matchBinaries": [
                                        {
                                            "operator": "In",
                                            "values": ["/bin/sh", "/bin/bash"],
                                        }
                                    ]
                                }
                            ],
                        }
                    ]
                },
            },
            {
                "apiVersion": "cilium.io/v1alpha1",
                "kind": "TracingPolicy",
                "metadata": {"name": "isovalent-file-access-watch"},
                "spec": {
                    "kprobes": [
                        {
                            "call": "security_file_open",
                            "syscall": False,
                            "args": [{"index": 0, "type": "file"}],
                            "selectors": [
                                {
                                    "matchArgs": [
                                        {
                                            "index": 0,
                                            "operator": "Prefix",
                                            "values": ["/etc/passwd", "/etc/shadow", "/root/.ssh/"],
                                        }
                                    ]
                                }
                            ],
                        }
                    ]
                },
            },
            {
                "apiVersion": "cilium.io/v1alpha1",
                "kind": "TracingPolicy",
                "metadata": {"name": "isovalent-privilege-syscall-watch"},
                "spec": {
                    "kprobes": [
                        {"call": "__sys_setuid", "syscall": True},
                        {"call": "__sys_setgid", "syscall": True},
                    ]
                },
            },
            {
                "apiVersion": "cilium.io/v1alpha1",
                "kind": "TracingPolicyNamespaced",
                "metadata": {"name": "isovalent-namespace-shell-watch", "namespace": "default"},
                "spec": {
                    "kprobes": [
                        {
                            "call": "security_bprm_check",
                            "syscall": False,
                            "args": [{"index": 0, "type": "linux_binprm"}],
                            "selectors": [
                                {
                                    "matchBinaries": [
                                        {
                                            "operator": "In",
                                            "values": ["/bin/sh", "/bin/bash"],
                                        }
                                    ]
                                }
                            ],
                        }
                    ]
                },
            },
        ],
    }


def render_metadata(
    args: argparse.Namespace,
    spec: dict[str, Any],
    edition: str,
    distribution: str,
    sections: list[str],
    *,
    enable_dnsproxy: bool,
    enable_hubble_enterprise: bool,
    enable_timescape: bool,
) -> dict[str, Any]:
    export_mode = args.export_mode or (spec.get("tetragon") or {}).get("export", {}).get("mode", "file")
    return {
        "skill": SKILL_NAME,
        "edition": edition,
        "distribution": distribution,
        "cluster_name": spec.get("cluster_name", "lab-cluster"),
        "eks_mirror": bool_flag(args.eks_mirror),
        "enable_dnsproxy": enable_dnsproxy,
        "enable_hubble_enterprise": enable_hubble_enterprise,
        "enable_timescape": enable_timescape,
        "tetragon_export_mode": export_mode,
        "apply_sections": sections,
        "outputs": {
            "feature_catalog": "feature-catalog.json",
            "feature_matrix": "feature-matrix.md",
            "coverage_report": "coverage-report.json",
            "environment_profiles": "environment-profiles.json",
            "apply_plan": "apply-plan.json",
            "doctor_report": "doctor-report.md",
        },
        "warnings": warnings(
            args,
            spec,
            edition,
            enable_dnsproxy=enable_dnsproxy,
            enable_hubble_enterprise=enable_hubble_enterprise,
            enable_timescape=enable_timescape,
        ),
    }


def warnings(
    args: argparse.Namespace,
    spec: dict[str, Any],
    edition: str,
    *,
    enable_dnsproxy: bool | None = None,
    enable_hubble_enterprise: bool | None = None,
    enable_timescape: bool | None = None,
) -> list[str]:
    items: list[str] = []
    enterprise_addons = spec.get("enterprise_addons") or {}
    dnsproxy_enabled = (
        enable_dnsproxy
        if enable_dnsproxy is not None
        else bool_flag(args.enable_dnsproxy) or bool(enterprise_addons.get("cilium_dnsproxy", False))
    )
    hubble_enabled = (
        enable_hubble_enterprise
        if enable_hubble_enterprise is not None
        else bool_flag(args.enable_hubble_enterprise) or bool(enterprise_addons.get("hubble_enterprise", False))
    )
    timescape_enabled = (
        enable_timescape
        if enable_timescape is not None
        else bool_flag(args.enable_timescape) or bool(enterprise_addons.get("hubble_timescape", False))
    )
    if edition == "enterprise" and hubble_enabled:
        items.append(
            "Hubble Enterprise chart (isovalent/hubble-enterprise) is private. "
            "Contact the Splunk + Isovalent team for chart access "
            "(https://isovalent.com/splunk-contact-us/). Without "
            "--private-chart-access-verified, the generated script fails closed; "
            "with verified access, it runs helm show values before apply."
        )
    export_mode = (args.export_mode or (spec.get("tetragon") or {}).get("export", {}).get("mode") or "file")
    if export_mode == "fluentd":
        items.append(
            "DEPRECATED: tetragon export mode 'fluentd' uses the archived "
            "fluent-plugin-splunk-hec (archived 2025-06-24). Plan to migrate "
            "to the file-based path used by splunk-observability-isovalent-integration."
        )
    if edition == "oss" and (dnsproxy_enabled or hubble_enabled or timescape_enabled):
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
    try:
        catalog = load_catalog()
    except SpecError as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1
    catalog = effective_catalog(catalog, private_chart_access_verified=args.private_chart_access_verified)
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
    distribution = normalize_distribution(args.distribution or str(spec.get("distribution") or "generic"))
    if distribution not in catalog["distribution_profiles"]:
        print(
            f"ERROR: distribution must be one of {sorted(catalog['distribution_profiles'])}; got {distribution!r}",
            file=__import__("sys").stderr,
        )
        return 1
    try:
        sections = selected_apply_sections(args.apply_sections or str((spec.get("apply") or {}).get("sections", "")))
    except SpecError as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1
    if edition == "enterprise":
        enable_dnsproxy = enable_dnsproxy or "dnsproxy" in sections
        enable_hubble_enterprise = enable_hubble_enterprise or "hubble" in sections
        enable_timescape = enable_timescape or "timescape" in sections
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
        "distribution": distribution,
        "cluster_name": spec.get("cluster_name", "lab-cluster"),
        "eks_mirror": eks_mirror,
        "enable_dnsproxy": enable_dnsproxy,
        "enable_hubble_enterprise": enable_hubble_enterprise,
        "enable_timescape": enable_timescape,
        "export_mode": export_mode,
        "apply_sections": sections,
        "coverage": {
            "missing_features": coverage_report(catalog, distribution)["missing_features"],
            "status_counts": coverage_report(catalog, distribution)["status_counts"],
        },
        "warnings": warnings(
            args,
            spec,
            edition,
            enable_dnsproxy=enable_dnsproxy,
            enable_hubble_enterprise=enable_hubble_enterprise,
            enable_timescape=enable_timescape,
        ),
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
    for section in sorted(CILIUM_SECTION_VALUE_OVERRIDES):
        write_yaml(out / f"helm/cilium-section-{section}-values.yaml", cilium_section_values(spec, section))
    write_yaml(out / "helm/tetragon-values.yaml", tetragon_values(spec, edition, args.export_mode))
    policy = tracing_policy(spec)
    if policy is not None:
        write_yaml(out / "helm/tracing-policy.yaml", policy)
    write_yaml(out / "helm/network-policy-example.yaml", network_policy_manifest())
    write_yaml(out / "helm/lb-ipam-example.yaml", lb_ipam_manifest())
    write_yaml(out / "helm/tetragon-runtime-policies.yaml", runtime_policy_bundle())
    if edition == "enterprise" and enable_dnsproxy:
        write_yaml(out / "helm/cilium-dnsproxy-values.yaml", cilium_dnsproxy_values(spec))
    if edition == "enterprise" and enable_hubble_enterprise:
        write_yaml(out / "helm/hubble-enterprise-values.yaml", hubble_enterprise_values(spec, export_mode))
    if edition == "enterprise" and enable_timescape:
        write_yaml(out / "helm/hubble-timescape-values.yaml", hubble_timescape_values(spec))
    if distribution == "openshift":
        write_yaml(out / "k8s/openshift-scc.yaml", openshift_scc_manifest(spec))

    write_text(
        out / "scripts/install-cilium.sh",
        install_script(
            name="install-cilium.sh",
            body=cilium_install_body(edition, eks_mirror, cilium_ns, distribution),
        ),
        executable=True,
    )
    write_text(
        out / "scripts/install-tetragon.sh",
        install_script(name="install-tetragon.sh", body=tetragon_install_body(edition, tetragon_ns)),
        executable=True,
    )
    if edition == "enterprise" and enable_dnsproxy:
        dnsproxy_body = cilium_dnsproxy_install_body(dnsproxy_ns)
    else:
        dnsproxy_body = gated_private_body("Cilium DNSProxy")
    write_text(
        out / "scripts/install-cilium-dnsproxy.sh",
        install_script(name="install-cilium-dnsproxy.sh", body=dnsproxy_body),
        executable=True,
    )
    if edition == "enterprise" and enable_hubble_enterprise:
        write_text(
            out / "scripts/install-hubble-enterprise.sh",
            install_script(
                name="install-hubble-enterprise.sh",
                body=hubble_enterprise_install_body(
                    hubble_ent_ns,
                    private_chart_access_verified=args.private_chart_access_verified,
                ),
            ),
            executable=True,
        )
    if edition == "enterprise" and enable_timescape:
        timescape_body = hubble_timescape_install_body(
            timescape_ns,
            private_chart_access_verified=args.private_chart_access_verified,
        )
    else:
        timescape_body = gated_private_body("Hubble Timescape")
    write_text(
        out / "scripts/install-hubble-timescape.sh",
        install_script(name="install-hubble-timescape.sh", body=timescape_body),
        executable=True,
    )

    for section in (
        "gateway-api",
        "ingress",
        "service-mesh",
        "egress-gateway",
        "bgp",
        "l2-announcements",
        "encryption",
        "host-firewall",
        "load-balancer",
    ):
        body = gated_private_body("Isovalent Load Balancer") if section == "load-balancer" else helm_section_apply_body(section, edition, eks_mirror, cilium_ns)
        write_text(
            out / f"scripts/apply-{section}.sh",
            install_script(name=f"apply-{section}.sh", body=body),
            executable=True,
        )
    write_text(
        out / "scripts/apply-clustermesh.sh",
        install_script(name="apply-clustermesh.sh", body=clustermesh_cli_body(cilium_ns)),
        executable=True,
    )
    write_text(
        out / "scripts/apply-hubble.sh",
        install_script(
            name="apply-hubble.sh",
            body=(
                hubble_enterprise_install_body(
                    hubble_ent_ns,
                    private_chart_access_verified=args.private_chart_access_verified,
                )
                if edition == "enterprise" and enable_hubble_enterprise
                else gated_private_body("Hubble Enterprise")
            ),
        ),
        executable=True,
    )
    write_text(
        out / "scripts/apply-network-policy.sh",
        install_script(name="apply-network-policy.sh", body=kubectl_manifest_apply_body("network-policy", "helm/network-policy-example.yaml", cilium_ns)),
        executable=True,
    )
    write_text(
        out / "scripts/apply-lb-ipam.sh",
        install_script(name="apply-lb-ipam.sh", body=kubectl_manifest_apply_body("lb-ipam", "helm/lb-ipam-example.yaml", cilium_ns)),
        executable=True,
    )
    write_text(
        out / "scripts/apply-runtime-policies.sh",
        install_script(name="apply-runtime-policies.sh", body=kubectl_manifest_apply_body("runtime-policies", "helm/tetragon-runtime-policies.yaml", tetragon_ns)),
        executable=True,
    )
    write_text(out / "scripts/preflight.sh", install_script(name="preflight.sh", body=preflight_body(spec, edition, distribution, catalog)), executable=True)
    if bool_flag(args.render_eksctl_example) or (spec.get("eks_byocni") or {}).get("render_eksctl_example", False):
        write_text(out / "scripts/eksctl-byocni-example.sh", eksctl_byocni_example(), executable=True)

    write_json(out / "feature-catalog.json", catalog)
    write_text(out / "feature-matrix.md", feature_matrix_markdown(catalog))
    write_json(out / "coverage-report.json", coverage_report(catalog, distribution))
    write_json(out / "environment-profiles.json", catalog["distribution_profiles"])
    write_text(out / "environment-profiles.md", environment_profiles_markdown(catalog))
    write_json(
        out / "apply-plan.json",
        apply_plan(
            args=args,
            spec=spec,
            catalog=catalog,
            edition=edition,
            distribution=distribution,
            output_dir=out.resolve(),
            sections=sections,
            namespaces=namespaces,
            eks_mirror=eks_mirror,
            enable_dnsproxy=enable_dnsproxy,
            enable_hubble_enterprise=enable_hubble_enterprise,
            enable_timescape=enable_timescape,
        ),
    )
    write_text(
        out / "doctor-report.md",
        doctor_report_markdown(
            catalog=catalog,
            distribution=distribution,
            warnings_list=warnings(
                args,
                spec,
                edition,
                enable_dnsproxy=enable_dnsproxy,
                enable_hubble_enterprise=enable_hubble_enterprise,
                enable_timescape=enable_timescape,
            ),
            sections=sections,
        ),
    )
    write_text(
        out / "metadata.json",
        json.dumps(
            render_metadata(
                args,
                spec,
                edition,
                distribution,
                sections,
                enable_dnsproxy=enable_dnsproxy,
                enable_hubble_enterprise=enable_hubble_enterprise,
                enable_timescape=enable_timescape,
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
