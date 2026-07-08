#!/usr/bin/env bats
# Tests for Splunk Enterprise Kubernetes setup shell entrypoints.

setup() {
    TEST_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")" && pwd)"
    PROJECT_ROOT="$(cd "${TEST_DIR}/.." && pwd)"
    TMP_ROOT="$(mktemp -d)"
    REAL_PYTHON="$(command -v python3)"
    export REAL_PYTHON
}

teardown() {
    rm -rf "${TMP_ROOT}"
}

write_mock_python() {
    cat > "${TMP_ROOT}/bin/python3" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

# SOK preflight intentionally probes the remote CRD URL. Keep this integration
# suite offline while still exercising the generated preflight control flow.
if [[ "${1:-}" == "-c" && "${2:-}" == *"urllib.request.urlopen"* ]]; then
  printf 'python3 offline-url-check\n' >> "${K8S_CMD_LOG}"
  exit 0
fi
if [[ "${1:-}" == "-c" && "${2:-}" == *"cannot download reviewed CRD manifest"* ]]; then
  destination="${@: -1}"
  printf '%s\n' 'apiVersion: v1' > "${destination}"
  printf 'python3 staged-crd-download\n' >> "${K8S_CMD_LOG}"
  exit 0
fi
if [[ "${1:-}" == "-c" && "${2:-}" == *"staged CRD manifest SHA-256 differs"* ]]; then
  printf 'python3 staged-crd-hash-check\n' >> "${K8S_CMD_LOG}"
  exit 0
fi
if [[ "${1:-}" == "-c" && "${2:-}" == *"PyYAML 6.x is required"* ]]; then
  printf 'python3 pyyaml-version-check\n' >> "${K8S_CMD_LOG}"
  exit 0
fi
exec "${REAL_PYTHON}" "$@"
SH
    chmod +x "${TMP_ROOT}/bin/python3"
}

write_mock_kubectl() {
    cat > "${TMP_ROOT}/bin/kubectl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'kubectl %s\n' "$*" >> "${K8S_CMD_LOG}"

if [[ -n "${K8S_MOCK_EXISTING_NAMESPACE:-}" && " ${*} " == *" get namespace ${K8S_MOCK_EXISTING_NAMESPACE} "* ]]; then
  printf '%s\n' "{\"apiVersion\":\"v1\",\"kind\":\"Namespace\",\"metadata\":{\"name\":\"${K8S_MOCK_EXISTING_NAMESPACE}\"},\"status\":{\"phase\":\"Active\"}}"
elif [[ " ${*} " == *" get customresourcedefinitions.apiextensions.k8s.io "* ]]; then
  printf '%s\n' '{"items":[]}'
elif [[ " ${*} " == *" version -o json "* ]]; then
  printf '%s\n' '{"serverVersion":{"gitVersion":"v1.33.5"}}'
elif [[ "${1:-}" == "version" ]]; then
  printf 'Client Version: v1.33.5\n'
elif [[ "${1:-}" == "auth" && "${2:-}" == "can-i" ]]; then
  printf 'yes\n'
elif [[ "${1:-}" == "create" && "${2:-}" == "configmap" ]]; then
  printf 'apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: splunk-licenses\n'
elif [[ "${1:-}" == "create" && "${2:-}" == "--raw" ]]; then
  command cat >/dev/null
  printf '%s\n' '{"status":{"allowed":true}}'
elif [[ "${1:-}" == "apply" && " ${*} " == *" -f - "* ]]; then
  # Consume Helm output so pipefail observes a complete, successful pipeline.
  command cat >/dev/null
elif [[ "${1:-}" == "config" && "${2:-}" == "current-context" ]]; then
  printf 'mock-context\n'
elif [[ "${1:-}" == "cluster-info" ]]; then
  printf 'Kubernetes control plane is running at https://127.0.0.1\n'
elif [[ "${1:-}" == "get" && " ${*} " == *" deployments --all-namespaces "* ]]; then
  printf '%s\n' '{"items":[]}'
elif [[ "${1:-}" == "get" && ( "${2:-}" == "clusterroles" || "${2:-}" == "clusterrolebindings" ) ]]; then
  printf '%s\n' '{"items":[]}'
fi
exit 0
SH
    chmod +x "${TMP_ROOT}/bin/kubectl"
}

write_mock_helm() {
    cat > "${TMP_ROOT}/bin/helm" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'helm %s\n' "$*" >> "${K8S_CMD_LOG}"

case "${1:-}" in
  list)
    [[ -z "${HELM_MOCK_RELEASES:-}" ]] || printf '%s\n' "${HELM_MOCK_RELEASES}"
    ;;
  show)
    printf 'apiVersion: v2\nversion: 3.1.0\n'
    ;;
  template)
    "${REAL_PYTHON}" - "$@" <<'PY'
import re
import sys
from pathlib import Path

args = sys.argv[1:]
namespace = args[args.index("--namespace") + 1]
operator = any(argument.endswith("/splunk-operator") for argument in args)
path = Path("operator-values.yaml" if operator else "enterprise-values.yaml")
text = path.read_text(encoding="utf-8")

def section(name):
    match = re.search(rf"^{re.escape(name)}:\n((?:  .*\n|\n)*)", text, re.MULTILINE)
    return match.group(1) if match else ""

def value(body, key, default=""):
    match = re.search(rf"^\s+{re.escape(key)}:\s*[\"']?([^\"'\s]+)", body, re.MULTILINE)
    return match.group(1) if match else default

if operator:
    op = section("splunkOperator")
    related_image = value(section("image"), "repository")
    image = value(section("  image"), "repository")
    if not image:
        images = re.findall(r"repository:\s*[\"']?([^\"'\s]+)", op)
        image = images[0]
    terms = value(op, "splunkGeneralTerms")
    print(f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: splunk-operator-controller-manager
  namespace: {namespace}
spec:
  template:
    spec:
      containers:
        - name: manager
          image: {image}
          imagePullPolicy: IfNotPresent
          env:
            - name: RELATED_IMAGE_SPLUNK_ENTERPRISE
              value: {related_image}
            - name: SPLUNK_GENERAL_TERMS
              value: {terms}
            - name: WATCH_NAMESPACE
              value: {namespace}
          volumeMounts:
            - mountPath: /opt/splunk/appframework/
              name: app-staging
      volumes:
        - name: app-staging
          persistentVolumeClaim:
            claimName: splunk-operator-app-download
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: splunk-operator-app-download
  namespace: {namespace}
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  volumeMode: Filesystem
  storageClassName: ""
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: splunk-operator
  namespace: {namespace}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: splunk-operator
  namespace: {namespace}""")
    raise SystemExit(0)

image = value(section("image"), "repository")
docs = []
clustered = value(section("clusterManager"), "enabled") == "true"
monitoring = value(section("monitoringConsole"), "enabled") == "true"

def emit(kind, name, body):
    replicas = value(body, "replicaCount")
    spec = [f"  image: {image}", "  imagePullPolicy: IfNotPresent"]
    if replicas:
        spec.append(f"  replicas: {replicas}")
    license_url = value(body, "licenseUrl")
    if license_url:
        spec.extend([
            "  volumes:",
            "    - configMap:",
            "        name: splunk-licenses",
            "      name: licenses",
            f"  licenseUrl: {license_url}",
        ])
    if clustered and kind in {"LicenseManager", "IndexerCluster", "SearchHeadCluster", "MonitoringConsole"}:
        spec.extend(["  clusterManagerRef:", "    name: cm"])
    if monitoring and kind != "MonitoringConsole" and kind not in {"Queue", "ObjectStorage"}:
        spec.extend(["  monitoringConsoleRef:", "    name: mc"])
    if kind not in {"Queue", "ObjectStorage"}:
        capacities = re.findall(r"^\s+storageCapacity:\s*[\"']?([^\"'\s]+)", body, re.MULTILINE)
        classes = re.findall(r"^\s+storageClassName:\s*[\"']?([^\"'\s]+)", body, re.MULTILINE)
        spec.extend([
            "  etcVolumeStorageConfig:",
            "    ephemeralStorage: false",
            f"    storageCapacity: {capacities[0]}",
            "  varVolumeStorageConfig:",
            "    ephemeralStorage: false",
            f"    storageCapacity: {capacities[1]}",
        ])
        if classes:
            spec.insert(spec.index("  varVolumeStorageConfig:"), f"    storageClassName: {classes[0]}")
            spec.append(f"    storageClassName: {classes[1]}")
    docs.append("\n".join([
        "apiVersion: enterprise.splunk.com/v4",
        f"kind: {kind}",
        "metadata:",
        f"  name: {name}",
        f"  namespace: {namespace}",
        "spec:",
        *spec,
    ]))

roles = (
    ("Standalone", "s1", "standalone"),
    ("ClusterManager", "cm", "clusterManager"),
    ("IndexerCluster", "idxc", "indexerCluster"),
    ("SearchHeadCluster", "shc", "searchHeadCluster"),
    ("LicenseManager", "lm", "licenseManager"),
    ("MonitoringConsole", "mc", "monitoringConsole"),
    ("Queue", "ingest-queue", "queue"),
    ("ObjectStorage", "ingest-object-storage", "objectStorage"),
    ("IngestorCluster", "ingestor", "ingestorCluster"),
)
for kind, name, key in roles:
    body = section(key)
    if value(body, "enabled") == "true":
        emit(kind, name, body)
print("\n---\n".join(docs))
PY
    ;;
esac
exit 0
SH
    chmod +x "${TMP_ROOT}/bin/helm"
}

write_mock_aws() {
    cat > "${TMP_ROOT}/bin/aws" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'aws %s\n' "$*" >> "${K8S_CMD_LOG}"
if [[ " ${*} " == *" eks update-kubeconfig "* ]]; then
  args=("$@")
  for ((i = 0; i < ${#args[@]}; i++)); do
    if [[ "${args[$i]}" == "--kubeconfig" ]]; then
      : > "${args[$((i + 1))]}"
      break
    fi
  done
fi
exit 0
SH
    chmod +x "${TMP_ROOT}/bin/aws"
}

write_mock_installer() {
    cat > "${TMP_ROOT}/bin/kubernetes-installer-standalone" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'kubernetes-installer-standalone %s\n' "$*" >> "${K8S_CMD_LOG}"

if [[ " ${*} " == *" -version "* ]]; then
  printf 'Version: %s\nSplunk Version: %s\n' \
    "${POD_MOCK_INSTALLER_VERSION:-1.6.0}" \
    "${POD_MOCK_SPLUNK_VERSION:-10.4.0}"
  exit 0
fi
if [[ " ${*} " == *" -preflightcheck.only "* ]]; then
  printf 'Preflight checks passed\n'
  exit 0
fi
if [[ " ${*} " == *" -deploy "* ]]; then
  : > "${POD_INSTALLER_STATE}"
  printf 'Deployment completed\n'
  exit 0
fi
if [[ " ${*} " == *" -status.workers "* ]]; then
  if [[ -f "${POD_INSTALLER_STATE}" ]]; then
    for worker in 1 2 3 4 5 6 7 8; do printf 'worker-%s Ready\n' "${worker}"; done
    exit 0
  fi
  printf 'worker-1 NotReady\n'
  exit 1
fi
if [[ " ${*} " == *" -status "* ]]; then
  if [[ -f "${POD_INSTALLER_STATE}" ]]; then
    printf '%s\n' \
      'splunk-idx-indexer-0 1/1 Running' \
      'splunk-idx-indexer-1 1/1 Running' \
      'splunk-idx-indexer-2 1/1 Running' \
      'splunk-core-search-standalone-0 1/1 Running' \
      'splunk-cm-cluster-manager-0 1/1 Running' \
      'splunk-lm-license-manager-0 1/1 Running' \
      'splunk-mc-monitoring-console-0 1/1 Running' \
      'seaweedfs-master-0 1/1 Running'
    exit 0
  fi
  printf 'No deployed cluster\n'
  exit 1
fi
exit 0
SH
    chmod +x "${TMP_ROOT}/bin/kubernetes-installer-standalone"
}

write_mock_timeout() {
    cat > "${TMP_ROOT}/bin/timeout" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
while [[ "${1:-}" == --* ]]; do shift; done
[[ "${1:-}" == *s ]] && shift
exec "$@"
SH
    chmod +x "${TMP_ROOT}/bin/timeout"
}

make_mock_path() {
    mkdir -p "${TMP_ROOT}/bin"
    export K8S_CMD_LOG="${TMP_ROOT}/commands.log"
    export POD_INSTALLER_STATE="${TMP_ROOT}/pod-deployed"
    : > "${K8S_CMD_LOG}"
    write_mock_python
    write_mock_kubectl
    write_mock_helm
    write_mock_aws
    write_mock_installer
    write_mock_timeout
    export PATH="${TMP_ROOT}/bin:${PATH}"
    # Any unmocked network attempt should fail quickly instead of reaching the
    # public Internet.
    export HTTPS_PROXY="http://127.0.0.1:9"
    export HTTP_PROXY="http://127.0.0.1:9"
    export NO_PROXY=""
}

make_pod_inputs() {
    license_file="${TMP_ROOT}/splunk.lic"
    ssh_key="${TMP_ROOT}/ssh.key"
    installer_path="${TMP_ROOT}/bin/kubernetes-installer-standalone"
    controller_ips="10.10.10.1,10.10.10.2,10.10.10.3"
    worker_ips="10.10.10.4,10.10.10.5,10.10.10.6,10.10.10.7,10.10.10.8,10.10.10.9,10.10.10.10,10.10.10.11"
    printf 'license\n' > "${license_file}"
    ssh-keygen -q -t ed25519 -N '' -f "${ssh_key}"
    rm -f "${ssh_key}.pub"
    installer_sha256="$(shasum -a 256 "${installer_path}" | awk '{print $1}')"
}

@test "enterprise kubernetes dry-run json emits POD plan without rendering" {
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target pod \
      --pod-profile pod-small \
      --phase apply \
      --dry-run \
      --json \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    python3 - "$output" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
assert payload["target"] == "pod"
assert payload["pod_profile"] == "pod-small"
assert payload["dry_run"] is True
assert payload["commands"]["preflight"] == [["./preflight.sh"]]
assert payload["commands"]["apply"] == [["./deploy.sh"]]
assert payload["commands"]["status"] == [["./wait-ready.sh"]]
PY
    [ ! -e "${output_dir}" ]
}

@test "enterprise kubernetes render-only writes reviewed SOK bundle and runs no tools" {
    make_mock_path
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target sok \
      --architecture s1 \
      --output-dir "${output_dir}" \
      --accept-splunk-general-terms
    [ "$status" -eq 0 ]
    [ -f "${output_dir}/sok/operator-values.yaml" ]
    [ -f "${output_dir}/sok/enterprise-values.yaml" ]
    [ -f "${output_dir}/sok/metadata.json" ]
    [ -f "${output_dir}/sok/bundle-manifest.json" ]
    [ -x "${output_dir}/sok/preflight.sh" ]
    [ -x "${output_dir}/sok/helm-install-enterprise.sh" ]
    [ ! -s "${K8S_CMD_LOG}" ]
}

@test "enterprise kubernetes rejects undersized C3 indexer replicas" {
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target sok \
      --architecture c3 \
      --indexer-replicas 1 \
      --output-dir "${output_dir}" \
      --accept-splunk-general-terms
    [ "$status" -ne 0 ]
    [[ "$output" =~ "--indexer-replicas must be at least 3 for SOK C3" ]]
}

@test "enterprise kubernetes validator performs offline SOK pull lint and template checks" {
    make_mock_path
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target sok \
      --architecture c3 \
      --output-dir "${output_dir}" \
      --accept-splunk-general-terms
    [ "$status" -eq 0 ]

    : > "${K8S_CMD_LOG}"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/validate.sh" \
      --target sok \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    log_text="$(cat "${K8S_CMD_LOG}")"
    [[ "${log_text}" =~ "helm repo add splunk https://splunk.github.io/splunk-operator/ --force-update" ]]
    [[ "${log_text}" =~ "helm pull splunk/splunk-operator --version 3.1.0 --untar" ]]
    [[ "${log_text}" =~ "helm lint" ]]
    [[ "${log_text}" =~ "helm template splunk-operator" ]]
    [[ "${log_text}" =~ "helm template splunk-enterprise" ]]
}

@test "enterprise kubernetes live SOK apply requires a reviewed bundle" {
    make_mock_path
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target sok \
      --phase apply \
      --output-dir "${output_dir}"
    [ "$status" -ne 0 ]
    [[ "$output" =~ "No reviewed sok bundle exists" ]]
    [ ! -s "${K8S_CMD_LOG}" ]
}

@test "enterprise kubernetes SOK apply runs expanded preflight before mocked helpers" {
    make_mock_path
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target sok \
      --architecture c3 \
      --output-dir "${output_dir}" \
      --eks-cluster-name demo \
      --aws-region us-west-2 \
      --accept-splunk-general-terms
    [ "$status" -eq 0 ]

    : > "${K8S_CMD_LOG}"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target sok \
      --phase apply \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    log_text="$(cat "${K8S_CMD_LOG}")"
    [[ "${log_text}" =~ "aws eks update-kubeconfig --name demo --region us-west-2" ]]
    [[ "${log_text}" =~ "kubectl cluster-info" ]]
    [[ "${log_text}" =~ "kubectl version -o json" ]]
    [[ "${log_text}" =~ "kubectl create --raw /apis/authorization.k8s.io/v1/selfsubjectaccessreviews -f -" ]]
    [[ "${log_text}" =~ "helm show chart splunk/splunk-operator --version 3.1.0" ]]
    [[ "${log_text}" =~ "python3 staged-crd-download" ]]
    [[ "${log_text}" =~ "python3 staged-crd-hash-check" ]]
    [[ ! "${log_text}" =~ "python3 offline-url-check" ]]
    [[ "${log_text}" =~ "aws eks describe-cluster --name demo --region us-west-2" ]]
    [[ "${log_text}" =~ "splunk-operator-crds.yaml --server-side" ]]
    [[ "${log_text}" =~ "helm upgrade --install splunk-operator splunk/splunk-operator" ]]
    [[ "${log_text}" =~ "helm upgrade --install splunk-enterprise splunk/splunk-enterprise" ]]
    python3 - "${K8S_CMD_LOG}" <<'PY'
from pathlib import Path
import sys
lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
preflight = next(i for i, line in enumerate(lines) if line == "kubectl cluster-info")
namespace = next(i for i, line in enumerate(lines) if line == "kubectl create namespace splunk-operator")
crds = next(i for i, line in enumerate(lines) if "splunk-operator-crds.yaml" in line and line.startswith("kubectl apply"))
operator = next(i for i, line in enumerate(lines) if line.startswith("helm upgrade --install splunk-operator"))
enterprise = next(i for i, line in enumerate(lines) if line.startswith("helm upgrade --install splunk-enterprise"))
assert preflight < namespace < crds < operator < enterprise
PY
}

@test "enterprise kubernetes fresh SOK apply preserves a healthy staged namespace" {
    make_mock_path
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target sok \
      --architecture s1 \
      --output-dir "${output_dir}" \
      --accept-splunk-general-terms
    [ "$status" -eq 0 ]

    : > "${K8S_CMD_LOG}"
    run env K8S_MOCK_EXISTING_NAMESPACE=splunk-operator \
      bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target sok \
      --phase apply \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    log_text="$(cat "${K8S_CMD_LOG}")"
    [[ "${log_text}" =~ "kubectl --request-timeout=30s get namespace splunk-operator" ]]
    [[ ! "${log_text}" =~ "kubectl create namespace" ]]
    [[ "${log_text}" =~ "splunk-operator-crds.yaml --server-side" ]]
    [[ "${log_text}" =~ "helm upgrade --install" ]]
}

@test "enterprise kubernetes SOK apply uses bundled license helper without repeated inputs" {
    make_mock_path
    output_dir="${TMP_ROOT}/rendered"
    license_file="${TMP_ROOT}/splunk.lic"
    printf 'license\n' > "${license_file}"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target sok \
      --architecture s1 \
      --license-file "${license_file}" \
      --output-dir "${output_dir}" \
      --accept-splunk-general-terms
    [ "$status" -eq 0 ]

    : > "${K8S_CMD_LOG}"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target sok \
      --phase apply \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    [[ "$(cat "${K8S_CMD_LOG}")" =~ "kubectl create configmap splunk-licenses" ]]
}

@test "enterprise kubernetes POD preflight requires a reviewed bundle" {
    make_mock_path
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target pod \
      --phase preflight \
      --output-dir "${output_dir}"
    [ "$status" -ne 0 ]
    [[ "$output" =~ "No reviewed pod bundle exists" ]]
    [ ! -s "${K8S_CMD_LOG}" ]
}

@test "enterprise kubernetes POD render plus preflight verifies coupled installer versions" {
    make_mock_path
    make_pod_inputs
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target pod \
      --pod-profile pod-small \
      --output-dir "${output_dir}" \
      --controller-ips "${controller_ips}" \
      --worker-ips "${worker_ips}" \
      --license-file "${license_file}" \
      --ssh-private-key-file "${ssh_key}" \
      --installer-path "${installer_path}" \
      --installer-sha256 "${installer_sha256}" \
      --confirm-new-pod-install \
      --primary-search-name core-search
    [ "$status" -eq 0 ]
    [ -f "${output_dir}/pod/bundle-manifest.json" ]
    [ -x "${output_dir}/pod/wait-ready.sh" ]
    [ -x "${output_dir}/pod/diagnostics.sh" ]

    : > "${K8S_CMD_LOG}"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target pod \
      --phase preflight \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Version: 1.6.0" ]]
    [[ "$output" =~ "Splunk Version: 10.4.0" ]]
    log_text="$(cat "${K8S_CMD_LOG}")"
    [[ "${log_text}" =~ "kubernetes-installer-standalone -version" ]]
    [[ "${log_text}" =~ kubernetes-installer-standalone\ -static.cluster\ .*cluster-config.yaml\ -preflightcheck.only ]]
}

@test "enterprise kubernetes POD apply reruns preflight then deploys reviewed bundle" {
    make_mock_path
    make_pod_inputs
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target pod \
      --pod-profile pod-small \
      --output-dir "${output_dir}" \
      --controller-ips "${controller_ips}" \
      --worker-ips "${worker_ips}" \
      --license-file "${license_file}" \
      --ssh-private-key-file "${ssh_key}" \
      --installer-path "${installer_path}" \
      --installer-sha256 "${installer_sha256}" \
      --confirm-new-pod-install \
      --primary-search-name core-search
    [ "$status" -eq 0 ]

    : > "${K8S_CMD_LOG}"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target pod \
      --phase apply \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    [ -f "${POD_INSTALLER_STATE}" ]
    log_text="$(cat "${K8S_CMD_LOG}")"
    [[ "${log_text}" =~ "kubernetes-installer-standalone -version" ]]
    [[ "${log_text}" =~ kubernetes-installer-standalone\ -static.cluster\ .*cluster-config.yaml\ -preflightcheck.only ]]
    [[ "${log_text}" =~ kubernetes-installer-standalone\ -static.cluster\ .*cluster-config.yaml\ -status ]]
    [[ "${log_text}" =~ "kubernetes-installer-standalone -static.cluster" ]]
    [[ "${log_text}" =~ "splunk-pod-inputs." ]]
    [[ "${log_text}" =~ " -deploy" ]]

    : > "${K8S_CMD_LOG}"
    run env POD_READY_TIMEOUT_SECONDS=2 POD_READY_POLL_SECONDS=1 \
      bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target pod \
      --phase status \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    [[ "$output" =~ "worker-8 Ready" ]]
    [[ "$output" =~ "splunk-mc-monitoring-console-0 1/1 Running" ]]
}

@test "enterprise kubernetes POD all rejects placeholder live inputs before rendering" {
    make_mock_path
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target pod \
      --pod-profile pod-small \
      --phase all \
      --confirm-new-pod-install \
      --output-dir "${output_dir}"
    [ "$status" -ne 0 ]
    [[ "$output" =~ "--controller-ips is required for POD preflight/apply workflows" ]]
    [ ! -e "${output_dir}" ]
    [ ! -s "${K8S_CMD_LOG}" ]
}
