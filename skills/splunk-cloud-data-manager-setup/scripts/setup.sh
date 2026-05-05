#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"
SPEC="${SKILL_DIR}/template.example"
OUTPUT_DIR="${REPO_ROOT}/splunk-cloud-data-manager-rendered"
PHASE="render"
ACCEPT_APPLY="false"

usage() {
  cat <<'EOF'
Usage: setup.sh [--phase render|doctor|status|apply|validate|all] [--spec PATH] [--output-dir DIR] [--accept-apply]

Render, doctor, apply supported artifacts for, and validate Splunk Cloud Data
Manager onboarding. Specs must contain only non-secret values and secret file
paths.
EOF
}

reject_secret_arg() {
  case "$1" in
    --token|--access-token|--api-token|--password|--client-secret|--secret|--aws-secret-access-key|--aws-secret-key|--private-key)
      echo "Refusing secret argument $1. Use a *_file option in the spec instead." >&2
      exit 2
      ;;
  esac
}

while [[ $# -gt 0 ]]; do
  reject_secret_arg "$1"
  case "$1" in
    --phase)
      [[ $# -ge 2 ]] || { echo "--phase requires a value" >&2; exit 2; }
      PHASE="$2"
      shift 2
      ;;
    --spec)
      [[ $# -ge 2 ]] || { echo "--spec requires a value" >&2; exit 2; }
      SPEC="$2"
      shift 2
      ;;
    --output-dir)
      [[ $# -ge 2 ]] || { echo "--output-dir requires a value" >&2; exit 2; }
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --accept-apply)
      ACCEPT_APPLY="true"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

render() {
  python3 "${SKILL_DIR}/scripts/render_assets.py" \
    --mode render \
    --spec "${SPEC}" \
    --output-dir "${OUTPUT_DIR}"
}

doctor() {
  python3 "${SKILL_DIR}/scripts/render_assets.py" \
    --mode doctor \
    --spec "${SPEC}" \
    --output-dir "${OUTPUT_DIR}"
}

validate() {
  bash "${SKILL_DIR}/scripts/validate.sh" --output-dir "${OUTPUT_DIR}"
}

status() {
  python3 "${SKILL_DIR}/scripts/render_assets.py" \
    --mode status \
    --output-dir "${OUTPUT_DIR}"
}

apply_artifacts() {
  if [[ "${ACCEPT_APPLY}" != "true" ]]; then
    echo "Refusing apply without --accept-apply." >&2
    exit 2
  fi
  render
  if ! python3 "${SKILL_DIR}/scripts/render_assets.py" \
    --mode check-rendered \
    --output-dir "${OUTPUT_DIR}"; then
    exit 2
  fi
  (
    cd "${OUTPUT_DIR}"
    ACCEPT_DATA_MANAGER_APPLY=1 bash scripts/apply-data-manager-artifacts.sh
  )
}

case "${PHASE}" in
  render)
    render
    ;;
  doctor)
    doctor
    ;;
  status)
    status
    ;;
  apply)
    apply_artifacts
    ;;
  validate)
    validate
    ;;
  all)
    render
    doctor
    validate
    ;;
  *)
    echo "Unknown phase: ${PHASE}" >&2
    usage >&2
    exit 2
    ;;
esac
