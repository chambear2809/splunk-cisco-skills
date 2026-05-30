#!/usr/bin/env bash
# Shared helpers for skills that apply Kubernetes / Helm overlays.
# Source from skill setup.sh after rendering, when the operator has explicitly
# opted into a live apply. These helpers do not authenticate, fetch secrets,
# or modify cluster state on their own — they enforce a uniform gate, surface
# blast radius, and wrap kubectl / helm invocations.

[[ -n "${_K8S_APPLY_HELPERS_LOADED:-}" ]] && return 0
_K8S_APPLY_HELPERS_LOADED=true

K8S_APPLY_DRY_RUN="${K8S_APPLY_DRY_RUN:-false}"
K8S_APPLY_ACCEPTED="${K8S_APPLY_ACCEPTED:-false}"

k8s_apply_log() {
    printf '[k8s-apply] %s\n' "$*" >&2
}

k8s_apply_die() {
    k8s_apply_log "ERROR: $*"
    exit 1
}

require_kubectl() {
    if ! command -v kubectl >/dev/null 2>&1; then
        k8s_apply_die "kubectl not found on PATH. Install kubectl before retrying with --apply."
    fi
}

require_helm() {
    if ! command -v helm >/dev/null 2>&1; then
        k8s_apply_die "helm not found on PATH. Install Helm v3.x before retrying with --apply."
    fi
}

# Print the active kube context + cluster URL so the operator sees blast radius
# before any mutation. Returns non-zero if kubectl cannot reach a cluster.
show_kube_context() {
    require_kubectl
    local ctx server
    ctx="$(kubectl config current-context 2>/dev/null || true)"
    if [[ -z "${ctx}" ]]; then
        k8s_apply_die "kubectl has no current-context. Set one with 'kubectl config use-context <name>'."
    fi
    server="$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}' 2>/dev/null || true)"
    k8s_apply_log "kube-context: ${ctx}"
    k8s_apply_log "cluster:      ${server:-<unknown>}"
    if ! kubectl version --request-timeout=5s >/dev/null 2>&1; then
        k8s_apply_die "kubectl cannot reach cluster ${server:-<unknown>}. Check connectivity / kubeconfig."
    fi
}

# Refuse to apply unless --accept-k8s-apply was passed. Skills are responsible
# for parsing the flag and exporting K8S_APPLY_ACCEPTED=true when set.
require_apply_acceptance() {
    if [[ "${K8S_APPLY_ACCEPTED}" != "true" ]]; then
        k8s_apply_die "--apply requires --accept-k8s-apply. Refusing to mutate the cluster."
    fi
}

# Run kubectl apply against a manifest path. Honors K8S_APPLY_DRY_RUN.
kubectl_apply_with_dryrun() {
    local manifest="${1:?manifest path required}"
    shift || true
    require_kubectl
    [[ -e "${manifest}" ]] || k8s_apply_die "manifest not found: ${manifest}"
    local args=(apply -f "${manifest}")
    if [[ "${K8S_APPLY_DRY_RUN}" == "true" ]]; then
        args+=(--dry-run=server)
        k8s_apply_log "kubectl apply (server dry-run): ${manifest}"
    else
        require_apply_acceptance
        k8s_apply_log "kubectl apply: ${manifest}"
    fi
    kubectl "${args[@]}" "$@"
}

# helm upgrade --install --reuse-values --atomic against an existing release.
# Args: release_name namespace chart_ref values_file [extra helm args...]
helm_upgrade_safe() {
    local release="${1:?release required}"
    local namespace="${2:?namespace required}"
    local chart_ref="${3:?chart ref required}"
    local values_file="${4:?values file required}"
    shift 4 || true
    require_helm
    [[ -e "${values_file}" ]] || k8s_apply_die "values file not found: ${values_file}"
    local args=(upgrade --install "${release}" "${chart_ref}" \
                --namespace "${namespace}" \
                --reuse-values \
                --values "${values_file}" \
                --atomic \
                --timeout 5m)
    if [[ "${K8S_APPLY_DRY_RUN}" == "true" ]]; then
        args+=(--dry-run)
        k8s_apply_log "helm upgrade (dry-run): release=${release} ns=${namespace} chart=${chart_ref}"
    else
        require_apply_acceptance
        k8s_apply_log "helm upgrade: release=${release} ns=${namespace} chart=${chart_ref}"
    fi
    helm "${args[@]}" "$@"
}

# Optional helper: ensure a namespace exists (create if missing). Honors dry-run.
ensure_namespace() {
    local ns="${1:?namespace required}"
    require_kubectl
    if kubectl get namespace "${ns}" >/dev/null 2>&1; then
        return 0
    fi
    if [[ "${K8S_APPLY_DRY_RUN}" == "true" ]]; then
        k8s_apply_log "would create namespace: ${ns}"
        return 0
    fi
    require_apply_acceptance
    k8s_apply_log "creating namespace: ${ns}"
    kubectl create namespace "${ns}"
}

# Convenience parser callable from setup.sh while iterating its argv loop.
# Usage in caller: case "$1" in ... ) parse_k8s_apply_flag "$1" || exit 1 ;; esac
# Sets K8S_APPLY_DRY_RUN / K8S_APPLY_ACCEPTED. Returns 0 if recognized, 1 otherwise.
parse_k8s_apply_flag() {
    case "${1:-}" in
        --accept-k8s-apply) K8S_APPLY_ACCEPTED=true; return 0 ;;
        --dry-run)          K8S_APPLY_DRY_RUN=true;  return 0 ;;
        *) return 1 ;;
    esac
}

export K8S_APPLY_DRY_RUN K8S_APPLY_ACCEPTED
