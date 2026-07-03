#!/usr/bin/env bash
set -uo pipefail

# Read-only AWS/EKS/Splunk Observability staging acceptance runner.
# This script never sources an environment file. It integrity-checks the token
# through a no-follow descriptor, but never prints, stores, or passes its value
# on a command line; authenticated child validators continue to use the file.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
umask 077

usage() {
    cat <<'EOF'
AWS/EKS/Splunk Observability staging acceptance (read-only)

Usage:
  scripts/staging/validate-aws-eks-o11y.sh [--report PATH]

Required environment:
  STAGING_EXPECTED_AWS_ACCOUNT_ID             Exact 12-digit AWS account ID
  AWS_REGION                                  Region containing the EKS cluster
  STAGING_EKS_CLUSTER_NAME                    Existing EKS cluster name
  STAGING_KUBE_CONTEXT                        Existing kubeconfig context; must be current
  STAGING_NAMESPACE                           Existing staging namespace
  STAGING_WORKLOAD                            Deployment/name, StatefulSet/name, or DaemonSet/name
  STAGING_APM_SERVICE                         Exact service.name expected in APM topology
  SPLUNK_O11Y_REALM                           Splunk Observability realm (for example us1)
  SPLUNK_O11Y_TOKEN_FILE                      Non-symlink, single-link, nonempty mode-0600 token file
  COLLECTOR_NAMESPACE                         Existing Collector namespace
  COLLECTOR_RELEASE                           Existing Collector Helm release
  INSTRUMENTATION_NAME                        Expected Instrumentation CR name
  WORKLOAD_LANGUAGE                           Expected auto-instrumentation language
  STAGING_OTEL_RENDERED_DIR                   Base OTel Collector rendered output
  STAGING_AUTO_INSTRUMENTATION_RENDERED_DIR   Kubernetes auto-instrumentation rendered output
  STAGING_AWS_INTEGRATION_RENDERED_DIR        AWS integration rendered output

Optional environment:
  AWS_PROFILE                                 AWS CLI profile (the standard AWS variable)
  STAGING_LAMBDA_APM_RENDERED_DIR             Run Lambda APM endpoint reachability when set
  STAGING_CLOUD_INTEGRATION_RENDERED_DIR      Run Splunk Platform<->O11y reachability when set
  STAGING_REPORT_PATH                         Report path when --report is omitted

The default report path is ./aws-eks-o11y-staging-report.json. Optional
validators are recorded as skipped when their rendered directory is unset.
No environment file is sourced and no command in this runner mutates AWS,
Kubernetes, Splunk Platform, or Splunk Observability Cloud.
EOF
}

REPORT_PATH="${STAGING_REPORT_PATH:-${PWD}/aws-eks-o11y-staging-report.json}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --report)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                echo "ERROR: --report requires a path." >&2
                exit 2
            fi
            REPORT_PATH="$2"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ -e "${REPORT_PATH}" && -L "${REPORT_PATH}" ]]; then
    echo "ERROR: report path must not be a symlink: ${REPORT_PATH}" >&2
    exit 2
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/aws-eks-o11y-staging.XXXXXX")" || exit 2
chmod 700 "${WORK_DIR}"
RESULTS_FILE="${WORK_DIR}/results.tsv"
EKS_JSON="${WORK_DIR}/eks.json"
EKS_ENDPOINT_FILE="${WORK_DIR}/eks-endpoint"
EKS_CA_FILE="${WORK_DIR}/eks-ca"
: >"${RESULTS_FILE}"
chmod 600 "${RESULTS_FILE}"
cleanup() { rm -rf -- "${WORK_DIR}"; }
trap cleanup EXIT HUP INT TERM

failures=0
optional_failures=0
configuration_failed=false

record_result() {
    local check_id="$1" category="$2" required="$3" status="$4" exit_code="$5" detail="$6"
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
        "${check_id}" "${category}" "${required}" "${status}" "${exit_code}" "${detail}" \
        >>"${RESULTS_FILE}"
    if [[ "${status}" == "failed" ]]; then
        if [[ "${required}" == "true" ]]; then
            failures=$((failures + 1))
        else
            optional_failures=$((optional_failures + 1))
        fi
    fi
}

run_step() {
    local check_id="$1" category="$2" required="$3"
    shift 3
    local log_file="${WORK_DIR}/${check_id//[^A-Za-z0-9_.-]/_}.log" rc=0
    echo "==> ${check_id}"
    if "$@" >"${log_file}" 2>&1; then
        record_result "${check_id}" "${category}" "${required}" passed 0 "read-only check passed"
        echo "PASS: ${check_id}"
    else
        rc=$?
        record_result "${check_id}" "${category}" "${required}" failed "${rc}" "read-only check failed; inspect runner output"
        if [[ "${required}" == "true" ]]; then
            echo "FAIL: ${check_id} (exit ${rc})" >&2
        else
            echo "WARN: optional diagnostic ${check_id} failed (exit ${rc}); acceptance is unchanged." >&2
        fi
        python3 "${SCRIPT_DIR}/redact-output.py" "${log_file}" || \
            echo "WARN: diagnostic output could not be safely redacted and was suppressed." >&2
    fi
}

write_report() {
    local final_status=pass
    (( failures == 0 )) || final_status=fail
    REPORT_PATH="${REPORT_PATH}" \
    RESULTS_FILE="${RESULTS_FILE}" \
    FINAL_STATUS="${final_status}" \
    OPTIONAL_FAILURES="${optional_failures}" \
    EXPECTED_ACCOUNT="${STAGING_EXPECTED_AWS_ACCOUNT_ID:-}" \
    EXPECTED_REGION="${AWS_REGION:-}" \
    EXPECTED_CLUSTER="${STAGING_EKS_CLUSTER_NAME:-}" \
    EXPECTED_CONTEXT="${STAGING_KUBE_CONTEXT:-}" \
    EXPECTED_NAMESPACE="${STAGING_NAMESPACE:-}" \
    EXPECTED_WORKLOAD="${STAGING_WORKLOAD:-}" \
    EXPECTED_APM_SERVICE="${STAGING_APM_SERVICE:-}" \
    EXPECTED_REALM="${SPLUNK_O11Y_REALM:-}" \
    EXPECTED_COLLECTOR_NAMESPACE="${COLLECTOR_NAMESPACE:-}" \
    EXPECTED_COLLECTOR_RELEASE="${COLLECTOR_RELEASE:-}" \
    EXPECTED_INSTRUMENTATION_NAME="${INSTRUMENTATION_NAME:-}" \
    EXPECTED_WORKLOAD_LANGUAGE="${WORKLOAD_LANGUAGE:-}" \
    python3 - <<'PY'
import json
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

report_path = Path(os.environ["REPORT_PATH"])
report_path.parent.mkdir(parents=True, exist_ok=True)
try:
    if report_path.is_symlink():
        raise SystemExit(f"ERROR: report path must not be a symlink: {report_path}")
except OSError as exc:
    raise SystemExit(f"ERROR: cannot inspect report path: {exc}") from exc

checks = []
seen_check_ids = set()
for raw in Path(os.environ["RESULTS_FILE"]).read_text(encoding="utf-8").splitlines():
    if not raw:
        continue
    fields = raw.split("\t")
    if len(fields) != 6:
        raise SystemExit("ERROR: internal staging result record is malformed")
    check_id, category, required, status, exit_code, detail = fields
    if check_id in seen_check_ids:
        raise SystemExit(f"ERROR: duplicate staging check id: {check_id}")
    seen_check_ids.add(check_id)
    checks.append(
        {
            "id": check_id,
            "category": category,
            "required": required == "true",
            "status": status,
            "exit_code": int(exit_code),
            "detail": detail,
        }
    )

counts = {name: sum(row["status"] == name for row in checks) for name in ("passed", "failed", "skipped")}
payload = {
    "schema_version": "aws-eks-o11y-staging-acceptance/v1",
    "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "read_only": True,
    "status": os.environ["FINAL_STATUS"],
    "optional_diagnostics_failed": int(os.environ["OPTIONAL_FAILURES"]),
    "scope": {
        "aws_account_id": os.environ["EXPECTED_ACCOUNT"],
        "aws_region": os.environ["EXPECTED_REGION"],
        "eks_cluster": os.environ["EXPECTED_CLUSTER"],
        "kube_context": os.environ["EXPECTED_CONTEXT"],
        "namespace": os.environ["EXPECTED_NAMESPACE"],
        "workload": os.environ["EXPECTED_WORKLOAD"],
        "apm_service": os.environ["EXPECTED_APM_SERVICE"],
        "o11y_realm": os.environ["EXPECTED_REALM"],
        "collector_namespace": os.environ["EXPECTED_COLLECTOR_NAMESPACE"],
        "collector_release": os.environ["EXPECTED_COLLECTOR_RELEASE"],
        "instrumentation_name": os.environ["EXPECTED_INSTRUMENTATION_NAME"],
        "workload_language": os.environ["EXPECTED_WORKLOAD_LANGUAGE"],
    },
    "summary": counts,
    "checks": checks,
}

fd, temp_name = tempfile.mkstemp(prefix=f".{report_path.name}.", dir=report_path.parent)
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    if report_path.exists() and report_path.is_symlink():
        raise SystemExit(f"ERROR: report path became a symlink: {report_path}")
    os.replace(temp_name, report_path)
    os.chmod(report_path, stat.S_IRUSR | stat.S_IWUSR)
except BaseException:
    try:
        os.unlink(temp_name)
    except FileNotFoundError:
        pass
    raise
PY
}

missing=()
for name in \
    STAGING_EXPECTED_AWS_ACCOUNT_ID AWS_REGION STAGING_EKS_CLUSTER_NAME \
    STAGING_KUBE_CONTEXT STAGING_NAMESPACE STAGING_WORKLOAD STAGING_APM_SERVICE \
    SPLUNK_O11Y_REALM SPLUNK_O11Y_TOKEN_FILE COLLECTOR_NAMESPACE COLLECTOR_RELEASE \
    INSTRUMENTATION_NAME WORKLOAD_LANGUAGE STAGING_OTEL_RENDERED_DIR \
    STAGING_AUTO_INSTRUMENTATION_RENDERED_DIR STAGING_AWS_INTEGRATION_RENDERED_DIR; do
    [[ -n "${!name:-}" ]] || missing+=("${name}")
done
if (( ${#missing[@]} > 0 )); then
    echo "ERROR: missing required environment: ${missing[*]}" >&2
    record_result configuration configuration true failed 2 "required environment is incomplete"
    configuration_failed=true
fi

toolchain_recorded=false
if [[ "${configuration_failed}" != "true" ]]; then
    verify_ssl_normalized="$(printf '%s' "${SPLUNK_VERIFY_SSL:-true}" | tr '[:upper:]' '[:lower:]')"
    case "${verify_ssl_normalized}" in
        false|0|no|off)
            echo "ERROR: SPLUNK_VERIFY_SSL=false is forbidden by the production staging gate." >&2
            configuration_failed=true
            ;;
    esac
    if [[ ! "${STAGING_EXPECTED_AWS_ACCOUNT_ID}" =~ ^[0-9]{12}$ ]]; then
        echo "ERROR: STAGING_EXPECTED_AWS_ACCOUNT_ID must be exactly 12 digits." >&2
        configuration_failed=true
    fi
    if [[ ! "${AWS_REGION}" =~ ^[a-z0-9]+(-[a-z0-9]+)+$ ]]; then
        echo "ERROR: AWS_REGION contains unsupported characters." >&2
        configuration_failed=true
    fi
    if [[ ! "${STAGING_EKS_CLUSTER_NAME}" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$ ]]; then
        echo "ERROR: STAGING_EKS_CLUSTER_NAME is invalid." >&2
        configuration_failed=true
    fi
    if [[ ! "${STAGING_NAMESPACE}" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]]; then
        echo "ERROR: STAGING_NAMESPACE must be a DNS-label namespace." >&2
        configuration_failed=true
    fi
    for value_name in COLLECTOR_NAMESPACE COLLECTOR_RELEASE INSTRUMENTATION_NAME; do
        if [[ ! "${!value_name}" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]]; then
            echo "ERROR: ${value_name} must be a DNS-label value." >&2
            configuration_failed=true
        fi
    done
    if [[ "${STAGING_NAMESPACE}" == "${COLLECTOR_NAMESPACE}" ]]; then
        echo "ERROR: STAGING_NAMESPACE must differ from COLLECTOR_NAMESPACE so workload pods cannot inherit Collector pod-log access." >&2
        configuration_failed=true
    fi
    case "${WORKLOAD_LANGUAGE}" in
        java|nodejs|python|dotnet|go|apache-httpd|nginx) ;;
        *)
            echo "ERROR: WORKLOAD_LANGUAGE is not supported by the staging gate." >&2
            configuration_failed=true
            ;;
    esac
    if [[ ! "${STAGING_WORKLOAD}" =~ ^(Deployment|StatefulSet|DaemonSet)/[a-z0-9]([-a-z0-9.]*[a-z0-9])?$ ]]; then
        echo "ERROR: STAGING_WORKLOAD must be Deployment/name, StatefulSet/name, or DaemonSet/name." >&2
        configuration_failed=true
    fi
    if [[ -z "${STAGING_KUBE_CONTEXT}" \
        || "${STAGING_KUBE_CONTEXT}" =~ [[:cntrl:]] \
        || "${STAGING_KUBE_CONTEXT}" =~ ^[[:space:]] \
        || "${STAGING_KUBE_CONTEXT}" =~ [[:space:]]$ \
        || "${STAGING_APM_SERVICE}" =~ [[:cntrl:]] \
        || "${STAGING_APM_SERVICE}" =~ ^[[:space:]] \
        || "${STAGING_APM_SERVICE}" =~ [[:space:]]$ \
        || ! "${SPLUNK_O11Y_REALM}" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
        echo "ERROR: context, APM service, or realm has an invalid value." >&2
        configuration_failed=true
    fi
    if [[ "${configuration_failed}" == "true" ]]; then
        record_result configuration configuration true failed 2 "required environment contains invalid values"
    fi
    case "${SPLUNK_O11Y_REALM}" in
        us0|us1|us2|us3|au0|eu0|eu1|eu2|jp0|sg0) ;;
        *)
            echo "ERROR: SPLUNK_O11Y_REALM is not a supported AWS-hosted realm." >&2
            if [[ "${configuration_failed}" != "true" ]]; then
                record_result configuration configuration true failed 2 "required environment contains invalid values"
            fi
            configuration_failed=true
            ;;
    esac
fi

validate_token_file() {
    python3 - "${SPLUNK_O11Y_TOKEN_FILE}" <<'PY'
import os
import stat
import sys

path = sys.argv[1]
if not hasattr(os, "O_NOFOLLOW"):
    print("ERROR: secure token validation requires O_NOFOLLOW support.", file=sys.stderr)
    raise SystemExit(1)
try:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
except OSError as exc:
    print(f"ERROR: cannot safely open SPLUNK_O11Y_TOKEN_FILE: {exc}", file=sys.stderr)
    raise SystemExit(1)
try:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        print("ERROR: SPLUNK_O11Y_TOKEN_FILE must be a single-link, non-symlink regular file.", file=sys.stderr)
        raise SystemExit(1)
    if stat.S_IMODE(before.st_mode) != 0o600:
        print("ERROR: SPLUNK_O11Y_TOKEN_FILE must have mode 0600.", file=sys.stderr)
        raise SystemExit(1)
    if before.st_size < 1 or before.st_size > 16 * 1024:
        print("ERROR: SPLUNK_O11Y_TOKEN_FILE size is outside the 1-byte through 16-KiB bound.", file=sys.stderr)
        raise SystemExit(1)
    chunks = []
    remaining = 16 * 1024 + 1
    while remaining:
        chunk = os.read(descriptor, min(4096, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    after = os.fstat(descriptor)
    path_after = os.stat(path, follow_symlinks=False)
finally:
    os.close(descriptor)
fingerprint = lambda info: (
    info.st_dev,
    info.st_ino,
    info.st_size,
    info.st_mtime_ns,
    info.st_ctime_ns,
    info.st_nlink,
    stat.S_IMODE(info.st_mode),
)
try:
    if fingerprint(before) != fingerprint(after):
        raise ValueError("changed while it was being read")
    if (path_after.st_dev, path_after.st_ino) != (after.st_dev, after.st_ino):
        raise ValueError("path identity changed while it was being read")
    data = b"".join(chunks)
    if data.endswith(b"\r\n"):
        data = data[:-2]
    elif data.endswith(b"\n"):
        data = data[:-1]
    if (
        not data
        or b"\x00" in data
        or b"\r" in data
        or b"\n" in data
        or data != data.strip()
        or any(byte <= 0x20 or byte == 0x7F for byte in data)
        or any(byte > 0x7E for byte in data)
    ):
        raise ValueError("must contain one nonempty printable-ASCII token without whitespace/control bytes")
except ValueError as exc:
    print(f"ERROR: SPLUNK_O11Y_TOKEN_FILE {exc}.", file=sys.stderr)
    raise SystemExit(1)
PY
}

validate_rendered_contracts() {
    python3 - \
        "${STAGING_EXPECTED_AWS_ACCOUNT_ID}" \
        "${STAGING_EKS_CLUSTER_NAME}" \
        "${AWS_REGION}" \
        "${STAGING_NAMESPACE}" \
        "${STAGING_WORKLOAD}" \
        "${SPLUNK_O11Y_REALM}" \
        "${COLLECTOR_NAMESPACE}" \
        "${COLLECTOR_RELEASE}" \
        "${INSTRUMENTATION_NAME}" \
        "${WORKLOAD_LANGUAGE}" \
        "${STAGING_OTEL_RENDERED_DIR}" \
        "${STAGING_AUTO_INSTRUMENTATION_RENDERED_DIR}" \
        "${STAGING_AWS_INTEGRATION_RENDERED_DIR}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

(
    account,
    cluster,
    region,
    namespace,
    workload,
    realm,
    collector_namespace,
    collector_release,
    instrumentation_name,
    language,
    otel_root,
    auto_root,
    aws_root,
) = sys.argv[1:]
kind, name = workload.split("/", 1)
otel = Path(otel_root)
auto = Path(auto_root)
aws = Path(aws_root)
for label, root in (("OTel", otel), ("auto-instrumentation", auto), ("AWS integration", aws)):
    if not root.is_dir() or root.is_symlink():
        raise SystemExit(f"ERROR: {label} rendered directory must be an existing non-symlink directory: {root}")

otel_meta = json.loads((otel / "metadata.json").read_text(encoding="utf-8"))
k8s = otel_meta.get("kubernetes") or {}
if not k8s.get("rendered"):
    raise SystemExit("ERROR: OTel rendered packet does not contain Kubernetes assets")
if k8s.get("cluster_name") != cluster:
    raise SystemExit("ERROR: OTel rendered cluster_name does not match STAGING_EKS_CLUSTER_NAME")
if not str(k8s.get("distribution") or "").startswith("eks"):
    raise SystemExit("ERROR: OTel rendered distribution is not EKS")
if k8s.get("namespace") != collector_namespace or k8s.get("release_name") != collector_release:
    raise SystemExit("ERROR: OTel rendered namespace/release does not match the selected Collector")
if not (otel / "k8s" / "status.sh").is_file():
    raise SystemExit("ERROR: OTel rendered packet has no k8s/status.sh")

auto_meta = json.loads((auto / "metadata.json").read_text(encoding="utf-8"))
if auto_meta.get("cluster_name") != cluster:
    raise SystemExit("ERROR: auto-instrumentation cluster_name does not match STAGING_EKS_CLUSTER_NAME")
if auto_meta.get("realm") != realm:
    raise SystemExit("ERROR: auto-instrumentation realm does not match SPLUNK_O11Y_REALM")
if auto_meta.get("deployment_environment") != "staging":
    raise SystemExit("ERROR: auto-instrumentation packet is not bound to the staging environment")
if auto_meta.get("namespace") != collector_namespace:
    raise SystemExit("ERROR: auto-instrumentation operational namespace does not match the selected Collector")
base = auto_meta.get("base") or {}
if base.get("namespace") != collector_namespace or base.get("release") != collector_release:
    raise SystemExit("ERROR: auto-instrumentation base release does not match the selected Collector")
raw_operator = collector_release if "operator" in collector_release else f"{collector_release}-operator"
if len(raw_operator) <= 31:
    operator_name = raw_operator.rstrip("-")
else:
    digest = hashlib.sha256(raw_operator.encode("utf-8")).hexdigest()[:8]
    operator_name = f"{raw_operator[:22].rstrip('-')}-{digest}"
expected_operator_resources = {
    "namespace": collector_namespace,
    "deployment_name": operator_name,
    "webhook_configuration_name": f"{operator_name}-mutation",
    "webhook_service_name": f"{operator_name}-webhook",
}
if auto_meta.get("operator_resources") != expected_operator_resources:
    raise SystemExit("ERROR: auto-instrumentation Operator resource names do not match the Collector contract")
crs = auto_meta.get("instrumentation_crs") or []
if not any(
    row.get("namespace") == collector_namespace and row.get("name") == instrumentation_name
    for row in crs
):
    raise SystemExit("ERROR: rendered Instrumentation CR does not match the selected name/namespace")
matches = [
    row for row in (auto_meta.get("targets") or [])
    if row.get("kind") == kind and row.get("namespace") == namespace and row.get("name") == name
]
if len(matches) != 1:
    raise SystemExit("ERROR: STAGING_WORKLOAD is not a rendered auto-instrumentation target")
if matches[0].get("language") != language:
    raise SystemExit("ERROR: rendered target language does not match WORKLOAD_LANGUAGE")
expected_cr = f"{collector_namespace}/{instrumentation_name}"
if matches[0].get("cr") != expected_cr:
    raise SystemExit("ERROR: rendered target CR binding does not match INSTRUMENTATION_NAME")

plan = json.loads((aws / "apply-plan.json").read_text(encoding="utf-8"))
keys = {str(row.get("idempotency_key") or "") for row in (plan.get("ordered_steps") or [])}
if f"iam-trust:{account}" not in keys:
    raise SystemExit("ERROR: AWS integration rendered account does not match STAGING_EXPECTED_AWS_ACCOUNT_ID")
payload = json.loads((aws / "payloads" / "integration-create.json").read_text(encoding="utf-8"))
if payload.get("name") != f"{cluster}-staging" or payload.get("regions") != [region]:
    raise SystemExit("ERROR: AWS integration rendered name/region does not match the selected staging cluster")
expected_role = f"arn:aws:iam::{account}:role/SplunkObservabilityStagingRole"
if payload.get("roleArn") != expected_role:
    raise SystemExit("ERROR: AWS integration rendered roleArn does not match the staging role contract")
PY
}

if [[ "${configuration_failed}" != "true" ]]; then
    for command in aws kubectl curl python3 bash; do
        if ! command -v "${command}" >/dev/null 2>&1; then
            echo "ERROR: required command not found: ${command}" >&2
            configuration_failed=true
        fi
    done
    if [[ "${configuration_failed}" == "true" ]]; then
        record_result toolchain configuration true failed 2 "required read-only command is missing"
        toolchain_recorded=true
    fi
fi

if [[ "${configuration_failed}" != "true" ]]; then
    run_step token-file configuration true validate_token_file
    run_step rendered-contracts configuration true validate_rendered_contracts
    if (( failures > 0 )); then
        configuration_failed=true
    fi
fi

check_aws_identity() {
    local actual
    actual="$(AWS_PAGER='' AWS_CLI_AUTO_PROMPT=off aws sts get-caller-identity --query Account --output text)" || return 1
    [[ "${actual}" == "${STAGING_EXPECTED_AWS_ACCOUNT_ID}" ]] || {
        echo "ERROR: AWS caller account does not match STAGING_EXPECTED_AWS_ACCOUNT_ID." >&2
        return 1
    }
}

check_toolchain_versions() {
    python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
        echo "ERROR: Python 3.10 or newer is required." >&2
        return 1
    }
    aws --version 2>&1 | grep -Eq '^aws-cli/2\.' || {
        echo "ERROR: AWS CLI v2 is required." >&2
        return 1
    }
    kubectl version --client -o json | python3 -c '
import json, re, sys
version = (json.load(sys.stdin) or {}).get("clientVersion") or {}
if str(version.get("major")) != "1" or not re.match(r"^[0-9]+", str(version.get("minor") or "")):
    raise SystemExit("ERROR: kubectl returned an invalid client version")
' || return 1
}

check_eks_cluster() {
    AWS_PAGER='' AWS_CLI_AUTO_PROMPT=off aws eks describe-cluster \
        --name "${STAGING_EKS_CLUSTER_NAME}" --region "${AWS_REGION}" --output json >"${EKS_JSON}" || return 1
    python3 - "${EKS_JSON}" "${STAGING_EXPECTED_AWS_ACCOUNT_ID}" "${AWS_REGION}" \
        "${STAGING_EKS_CLUSTER_NAME}" "${EKS_ENDPOINT_FILE}" "${EKS_CA_FILE}" <<'PY'
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

source, account, region, name, endpoint_file, ca_file = sys.argv[1:]
cluster = (json.load(open(source, encoding="utf-8")) or {}).get("cluster") or {}
if cluster.get("status") != "ACTIVE":
    raise SystemExit(f"ERROR: EKS cluster status is {cluster.get('status')!r}, expected 'ACTIVE'")
arn = str(cluster.get("arn") or "")
match = re.fullmatch(r"arn:[^:]+:eks:([^:]+):([0-9]{12}):cluster/(.+)", arn)
if not match or match.groups() != (region, account, name):
    raise SystemExit("ERROR: EKS cluster ARN does not match expected region/account/name")
endpoint = str(cluster.get("endpoint") or "")
parsed = urlsplit(endpoint)
if parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"}:
    raise SystemExit("ERROR: EKS cluster endpoint is not a canonical HTTPS endpoint")
ca_data = str((cluster.get("certificateAuthority") or {}).get("data") or "")
if not ca_data:
    raise SystemExit("ERROR: EKS cluster has no certificate authority data")
Path(endpoint_file).write_text(endpoint, encoding="utf-8")
Path(ca_file).write_text(ca_data, encoding="utf-8")
PY
}

check_kube_context() {
    local configured current context_json="${WORK_DIR}/kube-context.json"
    local version_json="${WORK_DIR}/kube-version.json"
    configured="$(kubectl config get-contexts "${STAGING_KUBE_CONTEXT}" -o name)" || return 1
    [[ "${configured}" == "${STAGING_KUBE_CONTEXT}" ]] || {
        echo "ERROR: STAGING_KUBE_CONTEXT is not present in kubeconfig." >&2
        return 1
    }
    current="$(kubectl config current-context)" || return 1
    [[ "${current}" == "${STAGING_KUBE_CONTEXT}" ]] || {
        echo "ERROR: STAGING_KUBE_CONTEXT must be current so rendered status scripts cannot target another cluster." >&2
        return 1
    }
    kubectl config view --raw --minify --context "${STAGING_KUBE_CONTEXT}" -o json >"${context_json}" || return 1
    python3 - "${context_json}" "${EKS_ENDPOINT_FILE}" "${EKS_CA_FILE}" \
        "${STAGING_EKS_CLUSTER_NAME}" "${AWS_REGION}" <<'PY' || return 1
import json
import sys
from pathlib import Path

payload = json.load(open(sys.argv[1], encoding="utf-8"))
expected = Path(sys.argv[2]).read_text(encoding="utf-8")
expected_ca = Path(sys.argv[3]).read_text(encoding="utf-8")
expected_cluster = sys.argv[4]
expected_region = sys.argv[5]
clusters = payload.get("clusters") or []
if len(clusters) != 1:
    raise SystemExit("ERROR: kube context does not contain exactly one cluster")
cluster = clusters[0].get("cluster") or {}
if str(cluster.get("server") or "") != expected:
    raise SystemExit("ERROR: kube context server does not match the described EKS cluster endpoint")
if cluster.get("insecure-skip-tls-verify") is True:
    raise SystemExit("ERROR: kube context disables TLS verification")
if str(cluster.get("certificate-authority-data") or "") != expected_ca:
    raise SystemExit("ERROR: kube context CA does not match the described EKS cluster CA")
users = payload.get("users") or []
if len(users) != 1:
    raise SystemExit("ERROR: kube context does not contain exactly one exec user")
exec_config = ((users[0].get("user") or {}).get("exec") or {})
command = str(exec_config.get("command") or "")
args = [str(value) for value in (exec_config.get("args") or [])]
if command != "aws":
    raise SystemExit("ERROR: kube context exec command is not the audited aws executable name")
if exec_config.get("env") not in (None, []):
    raise SystemExit("ERROR: kube context exec command overrides the runner AWS environment")
if exec_config.get("apiVersion") not in {
    "client.authentication.k8s.io/v1beta1",
    "client.authentication.k8s.io/v1",
}:
    raise SystemExit("ERROR: kube context exec command uses an unsupported credential API version")
if exec_config.get("interactiveMode") not in (None, "Never", "IfAvailable"):
    raise SystemExit("ERROR: kube context exec command has an unsupported interactiveMode")
if exec_config.get("provideClusterInfo") not in (None, False):
    raise SystemExit("ERROR: kube context exec command unexpectedly requests cluster information")
expected_args = [
    "--region",
    expected_region,
    "eks",
    "get-token",
    "--cluster-name",
    expected_cluster,
    "--output",
    "json",
]
if args != expected_args:
    raise SystemExit("ERROR: kube context is not bound to the current AWS CLI identity")
PY
    kubectl --context "${STAGING_KUBE_CONTEXT}" get --raw=/version --request-timeout=20s >/dev/null || return 1
    kubectl --context "${STAGING_KUBE_CONTEXT}" version -o json >"${version_json}" || return 1
    python3 - "${version_json}" <<'PY' || return 1
import json
import re
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
client = payload.get("clientVersion") or {}
server = payload.get("serverVersion") or {}


def component(value, label):
    if str(value.get("major")) != "1":
        raise SystemExit(f"ERROR: {label} major version is not Kubernetes 1.x")
    match = re.match(r"^[0-9]+", str(value.get("minor") or ""))
    if not match:
        raise SystemExit(f"ERROR: {label} minor version is invalid")
    return int(match.group())


client_minor = component(client, "kubectl")
server_minor = component(server, "kube-apiserver")
if abs(client_minor - server_minor) > 1:
    raise SystemExit(
        f"ERROR: kubectl 1.{client_minor} is outside the supported +/-1 minor skew "
        f"for kube-apiserver 1.{server_minor}"
    )
PY
    [[ "$(kubectl --context "${STAGING_KUBE_CONTEXT}" auth can-i get pods -n "${STAGING_NAMESPACE}")" == yes ]] || {
        echo "ERROR: Kubernetes identity cannot get pods in the staging namespace." >&2
        return 1
    }
}

check_staging_workload() {
    local kind="${STAGING_WORKLOAD%%/*}" name="${STAGING_WORKLOAD#*/}" workload_json="${WORK_DIR}/workload.json"
    kubectl --context "${STAGING_KUBE_CONTEXT}" -n "${STAGING_NAMESPACE}" \
        get "${kind}" "${name}" -o json --request-timeout=20s >"${workload_json}" || return 1
    python3 - "${workload_json}" "${kind}" "${STAGING_NAMESPACE}" "${name}" <<'PY'
import json
import sys

source, expected_kind, namespace, name = sys.argv[1:]
obj = json.load(open(source, encoding="utf-8"))
meta = obj.get("metadata") or {}
spec = obj.get("spec") or {}
status = obj.get("status") or {}
if obj.get("kind") != expected_kind or meta.get("namespace") != namespace or meta.get("name") != name:
    raise SystemExit("ERROR: Kubernetes returned a different workload identity")
generation = int(meta.get("generation") or 0)
observed = int(status.get("observedGeneration") or 0)
if generation and observed < generation:
    raise SystemExit("ERROR: workload controller has not observed the latest generation")
if expected_kind == "DaemonSet":
    desired = int(status.get("desiredNumberScheduled") or 0)
    checks = (
        desired > 0,
        int(status.get("numberReady") or 0) == desired,
        int(status.get("updatedNumberScheduled") or 0) == desired,
        int(status.get("numberUnavailable") or 0) == 0,
    )
else:
    desired = int(spec.get("replicas", 1))
    checks = (
        desired > 0,
        int(status.get("readyReplicas") or 0) == desired,
        int(status.get("updatedReplicas") or 0) == desired,
    )
    if expected_kind == "Deployment":
        checks += (int(status.get("availableReplicas") or 0) == desired,)
    else:
        checks += (int(status.get("currentReplicas") or 0) == desired,)
if not all(checks):
    raise SystemExit("ERROR: staging workload is not fully rolled out and Ready")
PY
}

if [[ "${configuration_failed}" == "true" ]]; then
    if [[ "${toolchain_recorded}" != "true" ]]; then
        record_result toolchain core true skipped 0 "blocked by configuration failure"
    fi
    for check_id in aws-identity eks-cluster kube-context staging-workload otel-collector-live auto-instrumentation-live aws-integration-live; do
        record_result "${check_id}" core true skipped 0 "blocked by configuration failure"
    done
else
    run_step toolchain configuration true check_toolchain_versions
    run_step aws-identity aws true check_aws_identity
    run_step eks-cluster eks true check_eks_cluster
    run_step kube-context eks true check_kube_context
    run_step staging-workload eks true check_staging_workload
    run_step otel-collector-live o11y true \
        bash "${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/validate.sh" \
        --output-dir "${STAGING_OTEL_RENDERED_DIR}" --k8s-workloads-only \
        --kube-context "${STAGING_KUBE_CONTEXT}"
    run_step auto-instrumentation-live o11y true \
        bash "${PROJECT_ROOT}/skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/validate.sh" \
        --output-dir "${STAGING_AUTO_INSTRUMENTATION_RENDERED_DIR}" \
        --kube-context "${STAGING_KUBE_CONTEXT}" \
        --check-webhook --check-instrumentation --check-injection --check-backup \
        --check-apm "${STAGING_APM_SERVICE}"
    run_step aws-integration-live o11y true \
        bash "${PROJECT_ROOT}/skills/splunk-observability-aws-integration/scripts/validate.sh" \
        --output-dir "${STAGING_AWS_INTEGRATION_RENDERED_DIR}" --live
fi

if [[ -n "${STAGING_LAMBDA_APM_RENDERED_DIR:-}" ]]; then
    if [[ "${configuration_failed}" == "true" ]]; then
        record_result lambda-apm-reachability optional false skipped 0 "blocked by configuration failure"
    else
        run_step lambda-apm-reachability optional false \
            bash "${PROJECT_ROOT}/skills/splunk-observability-aws-lambda-apm-setup/scripts/validate.sh" \
            --output-dir "${STAGING_LAMBDA_APM_RENDERED_DIR}" --live
    fi
else
    record_result lambda-apm-reachability optional false skipped 0 "optional rendered directory not configured"
fi

if [[ -n "${STAGING_CLOUD_INTEGRATION_RENDERED_DIR:-}" ]]; then
    if [[ "${configuration_failed}" == "true" ]]; then
        record_result cloud-integration-reachability optional false skipped 0 "blocked by configuration failure"
    else
        run_step cloud-integration-reachability optional false \
            bash "${PROJECT_ROOT}/skills/splunk-observability-cloud-integration-setup/scripts/validate.sh" \
            --output-dir "${STAGING_CLOUD_INTEGRATION_RENDERED_DIR}" --live
    fi
else
    record_result cloud-integration-reachability optional false skipped 0 "optional rendered directory not configured"
fi

if ! write_report; then
    echo "ERROR: failed to write staging report: ${REPORT_PATH}" >&2
    exit 2
fi
echo "Staging report: ${REPORT_PATH}"

if [[ "${configuration_failed}" == "true" ]]; then
    exit 2
fi
if (( optional_failures > 0 )); then
    echo "WARN: ${optional_failures} optional diagnostic(s) failed; acceptance status is determined only by required checks." >&2
fi
(( failures == 0 )) || exit 1
exit 0
