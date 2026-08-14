#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Galileo On-Prem Stack bundle validation

Usage:
  validate.sh --bundle PATH [--json]
  validate.sh --self-test [--json]

Options:
  --bundle PATH             Immutable rendered bundle
  --self-test               Run offline source and parser checks
  --galileo-console-url URL Accepted for Galileo intake consistency; validation is offline
  --json                    Emit JSON
  --help                    Show help
EOF
}

BUNDLE=""
SELF_TEST=false
JSON=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --bundle) [[ $# -ge 2 ]] || { echo "ERROR: --bundle requires a value" >&2; exit 2; }; BUNDLE="$2"; shift 2 ;;
    --self-test) SELF_TEST=true; shift ;;
    --galileo-console-url) [[ $# -ge 2 ]] || { echo "ERROR: --galileo-console-url requires a value" >&2; exit 2; }; shift 2 ;;
    --json) JSON=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "${SELF_TEST}" == true ]]; then
  python3 -c 'from pathlib import Path; import sys; compile(Path(sys.argv[1]).read_bytes(), sys.argv[1], "exec")' "${SCRIPT_DIR}/stack_lifecycle.py"
  python3 "${SCRIPT_DIR}/stack_lifecycle.py" --help >/dev/null
  PYTHONDONTWRITEBYTECODE=1 python3 "${SCRIPT_DIR}/self_test.py"
  bash -n "${SCRIPT_DIR}/setup.sh" "${SCRIPT_DIR}/validate.sh"
  if [[ "${JSON}" == true ]]; then
    printf '{"status":"ok","checks":["python-compile","help","secure-file-regressions","namespace-binding","synthetic-render","unknown-dependency","bash-syntax"]}\n'
  else
    echo "Galileo On-Prem Stack offline self-test: ok"
  fi
  exit 0
fi

[[ -n "${BUNDLE}" ]] || { echo "ERROR: --bundle or --self-test is required" >&2; exit 2; }
PYTHONDONTWRITEBYTECODE=1 python3 - "${SCRIPT_DIR}/stack_lifecycle.py" "${BUNDLE}" "${JSON}" <<'PY'
import importlib.util
import json
import sys
from pathlib import Path

engine, bundle, as_json = sys.argv[1:]
spec = importlib.util.spec_from_file_location("galileo_stack_lifecycle", engine)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
try:
    manifest, deployment = module.verify_bundle(Path(bundle))
    result = {
        "status": "implementation-validated",
        "bundle_sha256": manifest["bundle_sha256"],
        "deployment_id": deployment["deployment_id"],
        "secret_values_rendered": False,
        "production_ready": False,
        "unresolved_gates": [
            "entitled_chart_integration_unvalidated",
            "cse_values_contract_missing_or_unverified",
            "live_readonly_integration_unvalidated",
        ],
    }
except module.ContractError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2)
if as_json == "true":
    print(json.dumps(result, indent=2, sort_keys=True))
else:
    print(f"bundle validation: implementation-validated, not production-ready ({result['bundle_sha256']})")
PY
