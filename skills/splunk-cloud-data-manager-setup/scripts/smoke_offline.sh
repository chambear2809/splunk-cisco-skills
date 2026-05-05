#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

OUT="${TMP_DIR}/rendered"

bash "${SKILL_DIR}/scripts/setup.sh" \
  --phase render \
  --spec "${SKILL_DIR}/template.example" \
  --output-dir "${OUT}"

bash "${SKILL_DIR}/scripts/validate.sh" --output-dir "${OUT}"

grep -q '"coverage_status": "ui_handoff"' "${OUT}/coverage-report.json"
grep -q 'scdm-scs-promote-hec-token' "${OUT}/source-catalog.json"
grep -q 'scdm-scs-hec-token' "${OUT}/source-catalog.json"
grep -q 'No Terraform-based Data Manager input CRUD' "${OUT}/apply-plan.json"
test -x "${OUT}/scripts/aws-cloudformation.sh"
test -x "${OUT}/scripts/azure-arm.sh"
test -x "${OUT}/scripts/gcp-terraform.sh"

echo "Offline smoke test passed."
