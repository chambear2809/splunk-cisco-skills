#!/usr/bin/env bats
# Tests for Splunk Enterprise Kubernetes setup shell entrypoints.

setup() {
    TEST_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")" && pwd)"
    PROJECT_ROOT="$(cd "${TEST_DIR}/.." && pwd)"
    TMP_ROOT="$(mktemp -d)"
}

teardown() {
    rm -rf "${TMP_ROOT}"
}

write_mock_command() {
    local name="$1"
    cat > "${TMP_ROOT}/bin/${name}" <<'SH'
#!/usr/bin/env bash
printf '%s %s\n' "$(basename "$0")" "$*" >> "${K8S_CMD_LOG}"
if [[ "$(basename "$0")" == "kubectl" && "${1:-}" == "create" ]]; then
  printf 'apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: splunk-licenses\n'
fi
exit 0
SH
    chmod +x "${TMP_ROOT}/bin/${name}"
}

make_mock_path() {
    mkdir -p "${TMP_ROOT}/bin"
    export K8S_CMD_LOG="${TMP_ROOT}/commands.log"
    : > "${K8S_CMD_LOG}"
    write_mock_command kubectl
    write_mock_command helm
    write_mock_command aws
    write_mock_command kubernetes-installer-standalone
    export PATH="${TMP_ROOT}/bin:${PATH}"
}

@test "enterprise kubernetes dry-run json emits plan without rendering" {
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target pod \
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
assert payload["dry_run"] is True
assert payload["commands"]["apply"] == [["./deploy.sh"]]
PY
    [ ! -e "${output_dir}" ]
}

@test "enterprise kubernetes render-only writes SOK assets and does not run tools" {
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

@test "enterprise kubernetes validator runs SOK helm template checks when helm is available" {
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
    [[ "${log_text}" =~ "helm template splunk-operator splunk/splunk-operator --version 3.1.0 --namespace splunk-operator --values operator-values.yaml" ]]
    [[ "${log_text}" =~ "helm template splunk-enterprise splunk/splunk-enterprise --version 3.1.0 --namespace splunk-operator --values enterprise-values.yaml" ]]
}

@test "enterprise kubernetes SOK apply runs mocked aws kubectl and helm helpers" {
    make_mock_path
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target sok \
      --architecture c3 \
      --phase apply \
      --output-dir "${output_dir}" \
      --eks-cluster-name demo \
      --aws-region us-west-2 \
      --accept-splunk-general-terms
    [ "$status" -eq 0 ]
    log_text="$(cat "${K8S_CMD_LOG}")"
    [[ "${log_text}" =~ "aws eks update-kubeconfig --name demo --region us-west-2" ]]
    [[ "${log_text}" =~ "kubectl apply -f https://github.com/splunk/splunk-operator/releases/download/3.1.0/splunk-operator-crds.yaml --server-side" ]]
    [[ "${log_text}" =~ "helm upgrade --install splunk-operator splunk/splunk-operator" ]]
    [[ "${log_text}" =~ "helm upgrade --install splunk-enterprise splunk/splunk-enterprise" ]]
}

@test "enterprise kubernetes POD preflight rejects placeholder inputs" {
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target pod \
      --pod-profile pod-small \
      --phase preflight \
      --output-dir "${output_dir}"
    [ "$status" -ne 0 ]
    [[ "$output" =~ "--controller-ips is required for POD preflight/apply workflows" ]]
}

@test "enterprise kubernetes POD apply runs mocked installer deploy" {
    make_mock_path
    output_dir="${TMP_ROOT}/rendered"
    license_file="${TMP_ROOT}/splunk.lic"
    ssh_key="${TMP_ROOT}/ssh.key"
    printf 'license\n' > "${license_file}"
    printf 'key\n' > "${ssh_key}"
    chmod 600 "${ssh_key}"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" \
      --target pod \
      --pod-profile pod-small \
      --phase apply \
      --output-dir "${output_dir}" \
      --controller-ips 10.10.10.1,10.10.10.2,10.10.10.3 \
      --worker-ips 10.10.10.4,10.10.10.5,10.10.10.6,10.10.10.7,10.10.10.8,10.10.10.9,10.10.10.10,10.10.10.11 \
      --license-file "${license_file}" \
      --ssh-private-key-file "${ssh_key}"
    [ "$status" -eq 0 ]
    log_text="$(cat "${K8S_CMD_LOG}")"
    [[ "${log_text}" =~ "kubernetes-installer-standalone -static.cluster cluster-config.yaml -deploy" ]]
}
