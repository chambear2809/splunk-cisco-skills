#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
source "${PROJECT_ROOT}/skills/shared/lib/k8s_apply_helpers.sh"

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/cisco-isovalent-platform-rendered"
DEFAULT_SPEC="${SKILL_DIR}/template.example"

usage() {
    cat <<'EOF'
Cisco Isovalent Platform Setup

Usage:
  bash skills/cisco-isovalent-platform-setup/scripts/setup.sh [mode] [options]

Modes:
  --render               Render Helm values and install scripts (default)
  --discover             Read-only live inventory of Isovalent/Cilium/Tetragon resources
  --preflight            Render then run read-only Kubernetes preflights
  --doctor               Render and emit doctor-report.md; with kube context, append live inventory hints
  --apply [STEPS]        Render then apply selected steps; STEPS is comma-
                         separated (cilium, tetragon, hubble, dnsproxy,
                         timescape, load-balancer, network-policy, gateway-api,
                         ingress, service-mesh, clustermesh, egress-gateway,
                         bgp, lb-ipam, l2-announcements, encryption,
                         host-firewall, runtime-policies). With no list,
                         applies cilium and tetragon only.
  --backup               Read-only Helm values/history backup before mutation
  --upgrade-plan         Render upgrade-plan.md from current release inventory
  --rollback-plan        Render rollback-plan.md from current release history
  --uninstall-plan       Render uninstall-plan.md with CNI continuity warnings
  --feature-matrix       Render/print feature-matrix.md and coverage-report.json
  --validate             Run static validation against an already-rendered output
  --live                 With --validate, run read-only live probes
  --dry-run              Show the plan without writing
                         With --apply, run Helm/Kubectl dry-run validation
  --json                 Emit JSON dry-run output
  --explain              Print plan in plain English

Apply gates:
  --accept-k8s-apply     REQUIRED for mutating --apply.
  --accept-isovalent-disruptive-change
                         REQUIRED for CNI replacement, kube-proxy replacement,
                         Cluster Mesh, BGP, L2 announcements, encryption,
                         host firewall, rollback, uninstall, and load-balancer
                         changes.

Options:
  --spec PATH            YAML or JSON spec (default: template.example)
  --output-dir DIR       Rendered output directory
  --cluster-name NAME    Override spec.cluster_name
  --distribution NAME    generic, kubeadm, kind, minikube, kops, eks,
                         eks-byocni, eks-hybrid, aks-byocni,
                         aks-managed-cilium, gke, gke-dataplane-v2,
                         openshift, rke2, rancher, k3s, k0s, talos,
                         vmware-vsphere, alibaba-ack.
  --kube-context CTX     REQUIRED for live commands unless --allow-current-context
  --allow-current-context
                         Permit live commands to use kubectl's active context.
  --edition oss|enterprise
                         Override spec.edition. OSS = cilium/* from helm.cilium.io.
                         Enterprise = isovalent/* from helm.isovalent.com
                         (license required for mutating Enterprise apply steps).
  --eks-mirror           Use the AWS-published OCI mirror for Cilium (EKS Hybrid Nodes).
  --enable-dnsproxy      Render cilium-dnsproxy values + install (Enterprise only).
  --enable-hubble-enterprise
                         Render hubble-enterprise values + gated install (Enterprise only; private chart).
  --enable-timescape     Render hubble-timescape values + install (Enterprise only).
  --export-mode file|stdout|fluentd
                         Tetragon export mode (default: file). 'fluentd' is DEPRECATED.
  --isovalent-license-file PATH    Required for mutating Enterprise apply steps.
  --isovalent-pull-secret-file PATH (Optional, for the Isovalent private registry.)
  --private-chart-access-verified  Operator has verified private Isovalent chart access;
                         enables Helm apply rendering for Hubble Enterprise/Timescape.
  --render-eksctl-example          Render an eksctl BYOCNI example script.
  --allow-loose-token-perms        Skip the chmod-600 permission preflight on license/pull-secret files.
  --help                 Show this help

Direct license/secret flags such as --license, --license-key, --pull-secret are rejected.
EOF
}

bool_text() {
    if [[ "$1" == "true" ]]; then printf 'true'; else printf 'false'; fi
}

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

MODE_RENDER=true
MODE_APPLY=false
APPLY_STEPS=""
MODE_VALIDATE=false
MODE_DISCOVER=false
MODE_PREFLIGHT=false
MODE_DOCTOR=false
MODE_BACKUP=false
MODE_UPGRADE_PLAN=false
MODE_ROLLBACK_PLAN=false
MODE_UNINSTALL_PLAN=false
MODE_FEATURE_MATRIX=false
LIVE_VALIDATE=false
DRY_RUN=false
JSON_OUTPUT=false
EXPLAIN=false

OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
SPEC="${DEFAULT_SPEC}"
EDITION=""
CLUSTER_NAME=""
DISTRIBUTION=""
KUBE_CONTEXT=""
ALLOW_CURRENT_CONTEXT=false
EKS_MIRROR="false"
ENABLE_DNSPROXY="false"
ENABLE_HUBBLE_ENT="false"
ENABLE_TIMESCAPE="false"
EXPORT_MODE=""
ISOVALENT_LICENSE_FILE=""
ISOVALENT_PULL_SECRET_FILE=""
PRIVATE_CHART_ACCESS_VERIFIED=false
RENDER_EKSCTL_EXAMPLE="false"
ALLOW_LOOSE_TOKEN_PERMS=false
ISOVALENT_DISRUPTIVE_ACCEPTED=false

if [[ $# -eq 0 ]]; then
    usage
    exit 0
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) MODE_RENDER=true; shift ;;
        --discover) MODE_DISCOVER=true; MODE_RENDER=true; shift ;;
        --preflight) MODE_PREFLIGHT=true; MODE_RENDER=true; shift ;;
        --doctor) MODE_DOCTOR=true; MODE_RENDER=true; shift ;;
        --apply)
            MODE_APPLY=true; MODE_RENDER=true
            if [[ $# -ge 2 && ! "$2" =~ ^-- ]]; then
                APPLY_STEPS="$2"
                shift 2
            else
                shift
            fi
            ;;
        --backup) MODE_BACKUP=true; MODE_RENDER=true; shift ;;
        --upgrade-plan) MODE_UPGRADE_PLAN=true; MODE_RENDER=true; shift ;;
        --rollback-plan) MODE_ROLLBACK_PLAN=true; MODE_RENDER=true; shift ;;
        --uninstall-plan) MODE_UNINSTALL_PLAN=true; MODE_RENDER=true; shift ;;
        --feature-matrix) MODE_FEATURE_MATRIX=true; MODE_RENDER=true; shift ;;
        --validate) MODE_VALIDATE=true; shift ;;
        --live) LIVE_VALIDATE=true; shift ;;
        --accept-k8s-apply) K8S_APPLY_ACCEPTED=true; shift ;;
        --accept-isovalent-disruptive-change) ISOVALENT_DISRUPTIVE_ACCEPTED=true; shift ;;
        --dry-run) DRY_RUN=true; K8S_APPLY_DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --explain) EXPLAIN=true; shift ;;
        --spec) require_arg "$1" "$#" || exit 1; SPEC="$2"; shift 2 ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --cluster-name) require_arg "$1" "$#" || exit 1; CLUSTER_NAME="$2"; shift 2 ;;
        --distribution) require_arg "$1" "$#" || exit 1; DISTRIBUTION="$2"; shift 2 ;;
        --kube-context) require_arg "$1" "$#" || exit 1; KUBE_CONTEXT="$2"; shift 2 ;;
        --allow-current-context) ALLOW_CURRENT_CONTEXT=true; shift ;;
        --edition) require_arg "$1" "$#" || exit 1; EDITION="$2"; shift 2 ;;
        --eks-mirror) EKS_MIRROR="true"; shift ;;
        --enable-dnsproxy) ENABLE_DNSPROXY="true"; shift ;;
        --enable-hubble-enterprise) ENABLE_HUBBLE_ENT="true"; shift ;;
        --enable-timescape) ENABLE_TIMESCAPE="true"; shift ;;
        --export-mode) require_arg "$1" "$#" || exit 1; EXPORT_MODE="$2"; shift 2 ;;
        --isovalent-license-file) require_arg "$1" "$#" || exit 1; ISOVALENT_LICENSE_FILE="$2"; shift 2 ;;
        --isovalent-pull-secret-file) require_arg "$1" "$#" || exit 1; ISOVALENT_PULL_SECRET_FILE="$2"; shift 2 ;;
        --private-chart-access-verified) PRIVATE_CHART_ACCESS_VERIFIED=true; shift ;;
        --render-eksctl-example) RENDER_EKSCTL_EXAMPLE="true"; shift ;;
        --allow-loose-token-perms) ALLOW_LOOSE_TOKEN_PERMS=true; shift ;;
        --license|--license-key)
            reject_secret_arg "$1" "--isovalent-license-file"
            exit 1
            ;;
        --pull-secret)
            reject_secret_arg "$1" "--isovalent-pull-secret-file"
            exit 1
            ;;
        --help|-h) usage; exit 0 ;;
        *)
            log "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"

normalize_step() {
    local step="$1"
    step="$(printf '%s' "${step}" | tr '[:upper:]' '[:lower:]' | tr '_' '-' | tr -d '[:space:]')"
    case "${step}" in
        hubble-enterprise|hubbleenterprise) printf 'hubble' ;;
        cilium-dnsproxy|ciliumdnsproxy) printf 'dnsproxy' ;;
        hubble-timescape|hubbletimescape) printf 'timescape' ;;
        cluster-mesh) printf 'clustermesh' ;;
        lb_ipam) printf 'lb-ipam' ;;
        l2|l2-announcement) printf 'l2-announcements' ;;
        runtime-policy|runtime-policy-bundle) printf 'runtime-policies' ;;
        *) printf '%s' "${step}" ;;
    esac
}

requires_live_context() {
    [[ "${MODE_DISCOVER}" == "true" ]] && return 0
    [[ "${MODE_PREFLIGHT}" == "true" ]] && return 0
    [[ "${MODE_BACKUP}" == "true" ]] && return 0
    [[ "${MODE_UPGRADE_PLAN}" == "true" ]] && return 0
    [[ "${MODE_ROLLBACK_PLAN}" == "true" ]] && return 0
    [[ "${MODE_UNINSTALL_PLAN}" == "true" ]] && return 0
    [[ "${MODE_APPLY}" == "true" ]] && return 0
    [[ "${MODE_VALIDATE}" == "true" && "${LIVE_VALIDATE}" == "true" ]] && return 0
    return 1
}

if requires_live_context; then
    if [[ -z "${KUBE_CONTEXT}" && "${ALLOW_CURRENT_CONTEXT}" != "true" ]]; then
        log "ERROR: live Isovalent commands require --kube-context CTX, or --allow-current-context to use kubectl's active context."
        exit 1
    fi
    if [[ -n "${KUBE_CONTEXT}" ]]; then
        export KUBE_CONTEXT
    fi
fi

if [[ "${DRY_RUN}" != "true" && ( "${MODE_ROLLBACK_PLAN}" == "true" || "${MODE_UNINSTALL_PLAN}" == "true" ) && "${ISOVALENT_DISRUPTIVE_ACCEPTED}" != "true" ]]; then
    log "ERROR: rollback and uninstall planning require --accept-isovalent-disruptive-change so the runbook records explicit operator acknowledgement."
    exit 1
fi

_token_perm_octal() {
    local target="$1" mode=""
    mode="$(stat -f '%A' "${target}" 2>/dev/null)" && { printf '%s' "${mode}"; return 0; }
    mode="$(stat -c '%a' "${target}" 2>/dev/null)" && { printf '%s' "${mode}"; return 0; }
    printf ''
}

_check_token_perms() {
    local label="$1" path="$2"
    [[ -n "${path}" ]] || return 0
    if [[ ! -r "${path}" ]]; then
        log "ERROR: ${label} (${path}) is not readable or does not exist."
        return 1
    fi
    local mode
    mode="$(_token_perm_octal "${path}")"
    if [[ -z "${mode}" ]]; then
        log "  WARN: Could not stat ${label} (${path}); skipping permission check."
        return 0
    fi
    if [[ "${mode}" != "600" && "${mode}" != "0600" ]]; then
        if [[ "${ALLOW_LOOSE_TOKEN_PERMS:-false}" == "true" ]]; then
            log "  WARN: ${label} permissions are ${mode}; --allow-loose-token-perms is set, proceeding."
            return 0
        fi
        log "ERROR: ${label} (${path}) is mode ${mode}; secrets must be mode 600."
        log "       Run 'chmod 600 ${path}' to fix."
        return 1
    fi
}

[[ -n "${ISOVALENT_LICENSE_FILE}" ]] && { _check_token_perms "--isovalent-license-file" "${ISOVALENT_LICENSE_FILE}" || exit 1; }
[[ -n "${ISOVALENT_PULL_SECRET_FILE}" ]] && { _check_token_perms "--isovalent-pull-secret-file" "${ISOVALENT_PULL_SECRET_FILE}" || exit 1; }

if [[ "${EXPLAIN}" == "true" ]]; then
    cat <<EXPLAIN
Cisco Isovalent Platform Setup -- execution plan
================================================
  Spec:                     ${SPEC}
  Output directory:         ${OUTPUT_DIR}
  Cluster:                  ${CLUSTER_NAME:-<from spec, default lab-cluster>}
  Distribution:             ${DISTRIBUTION:-<from spec, default generic>}
  Kube context:             ${KUBE_CONTEXT:-<current context only if explicitly allowed>}
  Edition:                  ${EDITION:-<from spec, default oss>}
  EKS-AWS mirror:           ${EKS_MIRROR}
  Enable DNS proxy:         ${ENABLE_DNSPROXY}
  Enable Hubble Enterprise: ${ENABLE_HUBBLE_ENT}
  Enable Timescape:         ${ENABLE_TIMESCAPE}
  Tetragon export mode:     ${EXPORT_MODE:-<from spec, default file>}
  License file:             ${ISOVALENT_LICENSE_FILE:-<not set>}
  Pull-secret file:         ${ISOVALENT_PULL_SECRET_FILE:-<not set>}
  Private chart access:     ${PRIVATE_CHART_ACCESS_VERIFIED}
  Apply steps:              ${APPLY_STEPS:-<cilium,tetragon when --apply>}
  Gates:                    k8s_apply=${K8S_APPLY_ACCEPTED} disruptive=${ISOVALENT_DISRUPTIVE_ACCEPTED}
  Mode: render=$(bool_text "${MODE_RENDER}") discover=$(bool_text "${MODE_DISCOVER}") preflight=$(bool_text "${MODE_PREFLIGHT}") doctor=$(bool_text "${MODE_DOCTOR}") apply=$(bool_text "${MODE_APPLY}") validate=$(bool_text "${MODE_VALIDATE}") live=$(bool_text "${LIVE_VALIDATE}") backup=$(bool_text "${MODE_BACKUP}")
EXPLAIN
    exit 0
fi

RENDER_ARGS=(
    --output-dir "${OUTPUT_DIR}"
    --spec "${SPEC}"
    --edition "${EDITION}"
    --cluster-name "${CLUSTER_NAME}"
    --distribution "${DISTRIBUTION}"
    --apply-sections "${APPLY_STEPS}"
    --eks-mirror "${EKS_MIRROR}"
    --enable-dnsproxy "${ENABLE_DNSPROXY}"
    --enable-hubble-enterprise "${ENABLE_HUBBLE_ENT}"
    --enable-timescape "${ENABLE_TIMESCAPE}"
    --export-mode "${EXPORT_MODE}"
    --isovalent-license-file "${ISOVALENT_LICENSE_FILE}"
    --isovalent-pull-secret-file "${ISOVALENT_PULL_SECRET_FILE}"
    --render-eksctl-example "${RENDER_EKSCTL_EXAMPLE}"
)
if [[ "${MODE_FEATURE_MATRIX}" == "true" ]]; then
    RENDER_ARGS+=(--feature-matrix)
fi
if [[ "${PRIVATE_CHART_ACCESS_VERIFIED}" == "true" ]]; then
    RENDER_ARGS+=(--private-chart-access-verified)
fi
if [[ "${DRY_RUN}" == "true" && "${MODE_APPLY}" != "true" && "${MODE_PREFLIGHT}" != "true" ]]; then
    RENDER_ARGS+=(--dry-run)
fi
if [[ "${JSON_OUTPUT}" == "true" ]]; then
    RENDER_ARGS+=(--json)
fi

if [[ "${MODE_RENDER}" == "true" ]]; then
    python3 "${SCRIPT_DIR}/render_assets.py" "${RENDER_ARGS[@]}"
fi

if [[ "${DRY_RUN}" == "true" && "${MODE_APPLY}" != "true" && "${MODE_PREFLIGHT}" != "true" ]]; then
    exit 0
fi

if [[ "${MODE_VALIDATE}" == "true" ]]; then
    VALIDATE_ARGS=(--output-dir "${OUTPUT_DIR}")
    if [[ "${LIVE_VALIDATE}" == "true" ]]; then
        VALIDATE_ARGS+=(--live)
        if [[ -n "${KUBE_CONTEXT}" ]]; then
            VALIDATE_ARGS+=(--kube-context "${KUBE_CONTEXT}")
        elif [[ "${ALLOW_CURRENT_CONTEXT}" == "true" ]]; then
            VALIDATE_ARGS+=(--allow-current-context)
        fi
    fi
    bash "${SCRIPT_DIR}/validate.sh" "${VALIDATE_ARGS[@]}"
fi

_kubectl_cmd() {
    if [[ -n "${KUBE_CONTEXT}" ]]; then
        kubectl --context "${KUBE_CONTEXT}" "$@"
    else
        kubectl "$@"
    fi
}

_helm_cmd() {
    if [[ -n "${KUBE_CONTEXT}" ]]; then
        helm --kube-context "${KUBE_CONTEXT}" "$@"
    else
        helm "$@"
    fi
}

helm_release_namespace() {
    local release="$1"
    _helm_cmd list --all-namespaces --filter "^${release}$" 2>/dev/null \
        | awk -v release="${release}" 'NR > 1 && $1 == release {print $2; exit}'
}

current_context_name() {
    if [[ -n "${KUBE_CONTEXT}" ]]; then
        printf '%s' "${KUBE_CONTEXT}"
    else
        kubectl config current-context 2>/dev/null || printf '<unknown>'
    fi
}

write_live_state() {
    local command_class="$1" sections="${2:-}" state_dir="${OUTPUT_DIR}/state"
    local stamp helm_snapshot
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    mkdir -p "${state_dir}"
    helm_snapshot="${state_dir}/helm-releases-${stamp}.json"
    if command -v helm >/dev/null 2>&1; then
        _helm_cmd list --all-namespaces --filter '^(cilium|tetragon|hubble-enterprise|cilium-dnsproxy|hubble-timescape)$' -o json > "${helm_snapshot}" 2>/dev/null || printf '[]\n' > "${helm_snapshot}"
    else
        printf '[]\n' > "${helm_snapshot}"
    fi
    python3 - "${OUTPUT_DIR}" "${command_class}" "$(current_context_name)" "${sections}" "${helm_snapshot}" "${stamp}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

output = Path(sys.argv[1])
command_class = sys.argv[2]
kube_context = sys.argv[3]
sections = [item for item in sys.argv[4].split(",") if item]
helm_snapshot = Path(sys.argv[5])
stamp = sys.argv[6]
digest = hashlib.sha256()
helm_dir = output / "helm"
for path in sorted(helm_dir.glob("*.yaml")):
    digest.update(path.name.encode())
    digest.update(b"\0")
    digest.update(path.read_bytes())
    digest.update(b"\0")
try:
    releases = json.loads(helm_snapshot.read_text(encoding="utf-8"))
except Exception:
    releases = []
try:
    apply_plan = json.loads((output / "apply-plan.json").read_text(encoding="utf-8"))
    namespaces = apply_plan.get("live_action_state_contract", {}).get("namespaces") or {}
except Exception:
    namespaces = {}
chart_versions = {}
helm_release_revisions = {}
for release in releases if isinstance(releases, list) else []:
    name = release.get("name")
    if not name:
        continue
    chart_versions[name] = release.get("chart", "")
    helm_release_revisions[name] = release.get("revision", "")
payload = {
    "skill": "cisco-isovalent-platform-setup",
    "timestamp_utc": stamp,
    "kube_context": kube_context,
    "command_class": command_class,
    "sections": sections,
    "values_hash": digest.hexdigest(),
    "namespaces": namespaces,
    "helm_releases_snapshot": str(helm_snapshot),
    "chart_versions": chart_versions,
    "helm_release_revisions": helm_release_revisions,
    "crds_applied": sections,
    "previous_values_path": "backup/<timestamp>/helm-values",
    "rollback_hints": [
        "Review backup values before mutation.",
        "Use helm history and rollback-plan.md for release rollback.",
        "Do not remove the active CNI until alternate networking is validated.",
    ],
}
(output / "state").mkdir(parents=True, exist_ok=True)
state_file = output / "state" / f"live-action-state-{stamp}.json"
state_file.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
(output / "state" / "live-action-state.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

run_discover() {
    require_kubectl
    require_helm
    mkdir -p "${OUTPUT_DIR}/discover"
    log "Discovering Isovalent platform state in kube-context: $(current_context_name)"
    {
        printf '# Cisco Isovalent Platform Discover\n\n'
        printf "Kube context: \`%s\`\n\n" "$(current_context_name)"
        printf "## Helm Releases\n\n\`\`\`text\n"
        _helm_cmd list --all-namespaces --filter '^(cilium|tetragon|hubble-enterprise|cilium-dnsproxy|hubble-timescape)$' 2>&1 || true
        printf "\`\`\`\n\n## Nodes\n\n\`\`\`text\n"
        _kubectl_cmd get nodes -o wide 2>&1 || true
        printf "\`\`\`\n\n## Cilium/Tetragon CRDs\n\n\`\`\`text\n"
        _kubectl_cmd get crd 2>&1 | grep -E 'cilium|tetragon' || true
        printf "\`\`\`\n\n## CLI Availability\n\n\`\`\`text\n"
        command -v cilium >/dev/null 2>&1 && cilium version --client 2>&1 || printf 'cilium CLI not found\n'
        command -v tetra >/dev/null 2>&1 && tetra version 2>&1 || printf 'tetra CLI not found\n'
        printf "\`\`\`\n"
    } > "${OUTPUT_DIR}/discover/discover-report.md"
    write_live_state "discover" ""
    log "Discover report written to ${OUTPUT_DIR}/discover/discover-report.md"
}

run_preflight() {
    require_kubectl
    log "Running Isovalent preflight in kube-context: $(current_context_name)"
    KUBE_CONTEXT="${KUBE_CONTEXT}" K8S_APPLY_DRY_RUN=true bash "${OUTPUT_DIR}/scripts/preflight.sh"
    write_live_state "preflight" ""
}

run_backup() {
    require_helm
    local stamp backup_dir namespace
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    backup_dir="${OUTPUT_DIR}/backup/${stamp}"
    mkdir -p "${backup_dir}/helm-values" "${backup_dir}/helm-history"
    log "Backing up Helm values/history to ${backup_dir}"
    for release in cilium tetragon hubble-enterprise cilium-dnsproxy hubble-timescape; do
        namespace="$(helm_release_namespace "${release}")"
        if [[ -z "${namespace}" ]]; then
            printf '%s not installed\n' "${release}" > "${backup_dir}/helm-values/${release}.yaml"
            printf '%s not installed\n' "${release}" > "${backup_dir}/helm-history/${release}.txt"
            continue
        fi
        _helm_cmd get values "${release}" -n "${namespace}" -a > "${backup_dir}/helm-values/${release}.yaml" 2>&1 || true
        _helm_cmd history "${release}" -n "${namespace}" > "${backup_dir}/helm-history/${release}.txt" 2>&1 || true
    done
    write_live_state "backup" ""
}

write_plan_md() {
    local file="$1" title="$2" body="$3"
    {
        printf '# %s\n\n' "${title}"
        printf "Kube context: \`%s\`\n\n" "$(current_context_name)"
        printf '%s\n' "${body}"
    } > "${OUTPUT_DIR}/${file}"
    log "${title} written to ${OUTPUT_DIR}/${file}"
}

run_upgrade_plan() {
    require_helm
    local body
    body=$'Review current Helm release versions, generated values hash, and chart notes before running any upgrade.\n\n```text\n'
    body+="$(_helm_cmd list --all-namespaces --filter '^(cilium|tetragon|hubble-enterprise|cilium-dnsproxy|hubble-timescape)$' 2>&1 || true)"
    body+=$'\n```\n\nUse `--apply --dry-run` first, then `--apply --accept-k8s-apply` and add `--accept-isovalent-disruptive-change` for dataplane-impacting sections.'
    write_plan_md "upgrade-plan.md" "Cisco Isovalent Upgrade Plan" "${body}"
    write_live_state "upgrade-plan" ""
}

run_rollback_plan() {
    require_helm
    local body namespace
    namespace="$(helm_release_namespace cilium)"
    [[ -z "${namespace}" ]] && namespace="kube-system"
    body=$'Rollback is disruptive for CNI, kube-proxy replacement, BGP, L2 announcements, encryption, host firewall, and load-balancer sections.\n\n```text\n'
    body+="$(_helm_cmd history cilium -n "${namespace}" 2>&1 || true)"
    body+=$'\n```\n\nExample after review: `helm rollback cilium <REVISION> -n '"${namespace}"$'`. Validate workload networking before and after rollback.'
    write_plan_md "rollback-plan.md" "Cisco Isovalent Rollback Plan" "${body}"
    write_live_state "rollback-plan" ""
}

run_uninstall_plan() {
    local body
    body=$'Uninstall planning only. Do not remove Cilium from a cluster where it is the active CNI until replacement networking is installed and validated.\n\nRecommended order after approved change window: backup, drain or migrate workloads, disable policies that would block recovery, uninstall optional add-ons, then remove Tetragon and Cilium only when alternate CNI is active.'
    write_plan_md "uninstall-plan.md" "Cisco Isovalent Uninstall Plan" "${body}"
    write_live_state "uninstall-plan" ""
}

if [[ "${MODE_DISCOVER}" == "true" ]]; then run_discover; fi
if [[ "${MODE_PREFLIGHT}" == "true" ]]; then run_preflight; fi
if [[ "${MODE_DOCTOR}" == "true" ]]; then
    log "Doctor report available at ${OUTPUT_DIR}/doctor-report.md"
    if [[ -n "${KUBE_CONTEXT}" || "${ALLOW_CURRENT_CONTEXT}" == "true" ]]; then
        write_live_state "doctor" ""
    fi
fi
if [[ "${MODE_BACKUP}" == "true" ]]; then run_backup; fi
if [[ "${MODE_UPGRADE_PLAN}" == "true" ]]; then run_upgrade_plan; fi
if [[ "${MODE_ROLLBACK_PLAN}" == "true" ]]; then run_rollback_plan; fi
if [[ "${MODE_UNINSTALL_PLAN}" == "true" ]]; then run_uninstall_plan; fi
if [[ "${MODE_FEATURE_MATRIX}" == "true" && "${JSON_OUTPUT}" != "true" ]]; then
    log "Feature matrix written to ${OUTPUT_DIR}/feature-matrix.md"
    log "Coverage report written to ${OUTPUT_DIR}/coverage-report.json"
fi

run_step() {
    local step="$1" script="$2"
    local script_path="${OUTPUT_DIR}/scripts/${script}"
    if [[ ! -f "${script_path}" ]]; then
        log "ERROR: requested apply step '${step}' is not available in this render: ${script_path}"
        log "       Check --edition and the relevant --enable-* flag, or run --render first and inspect apply-plan.json."
        return 1
    fi
    log "Applying ${step}: ${script_path}"
    KUBE_CONTEXT="${KUBE_CONTEXT}" \
    K8S_APPLY_DRY_RUN="${K8S_APPLY_DRY_RUN}" \
    ISOVALENT_LICENSE_FILE="${ISOVALENT_LICENSE_FILE}" \
    ISOVALENT_PULL_SECRET_FILE="${ISOVALENT_PULL_SECRET_FILE}" \
        bash "${script_path}"
    write_live_state "apply" "${step}"
}

enforce_apply_plan_gates() {
    [[ "${MODE_APPLY}" == "true" ]] || return 0
    [[ "${DRY_RUN}" != "true" ]] || return 0
    python3 - "${OUTPUT_DIR}/apply-plan.json" "${K8S_APPLY_ACCEPTED}" "${ISOVALENT_DISRUPTIVE_ACCEPTED}" "${ISOVALENT_LICENSE_FILE}" <<'PY'
import json
import sys
from pathlib import Path

plan_path = Path(sys.argv[1])
k8s_accepted = sys.argv[2] == "true"
disruptive_accepted = sys.argv[3] == "true"
license_file = sys.argv[4]
try:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"ERROR: failed to read apply plan for gate enforcement: {plan_path}: {exc}", file=sys.stderr)
    raise SystemExit(1)
steps = plan.get("steps") or []
needs_k8s = [step["section"] for step in steps if step.get("requires_accept_k8s_apply")]
needs_disruptive = [step["section"] for step in steps if step.get("requires_accept_isovalent_disruptive_change")]
needs_license = [step["section"] for step in steps if step.get("requires_isovalent_license_file")]
if needs_k8s and not k8s_accepted:
    print(
        "ERROR: apply step(s) "
        + ",".join(needs_k8s)
        + " requires --accept-k8s-apply. Refusing to mutate the cluster.",
        file=sys.stderr,
    )
    raise SystemExit(1)
if needs_disruptive and not disruptive_accepted:
    print(
        "ERROR: apply step(s) "
        + ",".join(needs_disruptive)
        + " requires --accept-isovalent-disruptive-change.",
        file=sys.stderr,
    )
    raise SystemExit(1)
if needs_license and not license_file:
    print(
        "ERROR: enterprise apply step(s) "
        + ",".join(needs_license)
        + " requires --isovalent-license-file.",
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
}

if [[ "${MODE_APPLY}" == "true" ]]; then
    enforce_apply_plan_gates
    if [[ -n "${APPLY_STEPS}" ]]; then
        STEPS="${APPLY_STEPS}"
    else
        STEPS="$(python3 - "${OUTPUT_DIR}/apply-plan.json" <<'PY'
import json
import sys
from pathlib import Path

try:
    plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(",".join(plan.get("selected_sections") or ["cilium", "tetragon"]), end="")
except Exception:
    print("cilium,tetragon", end="")
PY
)"
    fi
    IFS=',' read -ra _STEPS_ARR <<< "${STEPS}"
    for step in "${_STEPS_ARR[@]}"; do
        step="$(normalize_step "${step}")"
        case "${step}" in
            cilium)             run_step cilium install-cilium.sh ;;
            tetragon)           run_step tetragon install-tetragon.sh ;;
            dnsproxy)           run_step dnsproxy install-cilium-dnsproxy.sh ;;
            hubble)             run_step hubble apply-hubble.sh ;;
            timescape)          run_step timescape install-hubble-timescape.sh ;;
            load-balancer)      run_step load-balancer apply-load-balancer.sh ;;
            network-policy)     run_step network-policy apply-network-policy.sh ;;
            gateway-api)        run_step gateway-api apply-gateway-api.sh ;;
            ingress)            run_step ingress apply-ingress.sh ;;
            service-mesh)       run_step service-mesh apply-service-mesh.sh ;;
            clustermesh)        run_step clustermesh apply-clustermesh.sh ;;
            egress-gateway)     run_step egress-gateway apply-egress-gateway.sh ;;
            bgp)                run_step bgp apply-bgp.sh ;;
            lb-ipam)            run_step lb-ipam apply-lb-ipam.sh ;;
            l2-announcements)   run_step l2-announcements apply-l2-announcements.sh ;;
            encryption)         run_step encryption apply-encryption.sh ;;
            host-firewall)      run_step host-firewall apply-host-firewall.sh ;;
            runtime-policies)   run_step runtime-policies apply-runtime-policies.sh ;;
            "" )                ;;
            *)
                log "ERROR: Unknown apply step: ${step}"
                exit 1
                ;;
        esac
    done
fi
