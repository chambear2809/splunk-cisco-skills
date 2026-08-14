#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
cat <<'EOF'
Galileo On-Prem Luna Studio Setup

Usage:
  bash skills/galileo-on-prem-luna-studio-setup/scripts/setup.sh --render [options]
  bash skills/galileo-on-prem-luna-studio-setup/scripts/setup.sh LIFECYCLE_MODE [options]

Modes:
  --render --validate --doctor --feature-matrix
  --preflight --status --plan-rollback --plan-uninstall
  --apply-install --apply-upgrade --apply-rollback --apply-uninstall
                      Permanent fail-closed Galileo/CSE handoff sentinels

Render options:
  --spec PATH
  --output-dir DIR
  --galileo-console-url URL   Required Galileo instance console URL
  --kubeconfig PATH           Required chmod-600 snapshot source for lifecycle modes
  --image-evidence-file PATH  Required private digest-pinned evidence for non-uninstall preflight
  --endpoint-evidence-file PATH
                              Required private host-only endpoint evidence for non-uninstall preflight

This skill performs no lifecycle mutation. Read-only preflight binds the exact
kube context and fresh evidence into a Galileo/CSE joint-session handoff. Every
--apply-* mode fails before kubeconfig, bundle, subprocess, or state access.
Inline --password, --token, --secret, --api-key, --set, and --set-string flags
are forbidden.
EOF
}

if [[ $# -eq 0 ]]; then usage; exit 0; fi
case "$1" in
  --preflight|--apply-install|--apply-upgrade|--status|--plan-rollback|--apply-rollback|--plan-uninstall|--apply-uninstall)
    exec python3 "${SCRIPT_DIR}/lifecycle.py" "$@" ;;
  --help|-h) usage; exit 0 ;;
esac
MODE=""; SPEC="${SKILL_DIR}/template.example"; OUTPUT_DIR=""; CONSOLE_URL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --render|--doctor|--feature-matrix) MODE=render; shift ;;
    --validate) MODE=validate; shift ;;
    --spec) [[ $# -ge 2 ]] || exit 2; SPEC="$2"; shift 2 ;;
    --output-dir) [[ $# -ge 2 ]] || exit 2; OUTPUT_DIR="$2"; shift 2 ;;
    --galileo-console-url) [[ $# -ge 2 ]] || exit 2; CONSOLE_URL="$2"; shift 2 ;;
    --password|--token|--secret|--api-key|--set|--set-string) echo "ERROR: direct secret/value flags are forbidden" >&2; exit 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; exit 2 ;;
  esac
done
[[ -n "${MODE}" && -n "${OUTPUT_DIR}" ]] || { echo "ERROR: mode and --output-dir are required" >&2; exit 2; }
if [[ "${MODE}" == validate ]]; then exec "${SCRIPT_DIR}/validate.sh" --output-dir "${OUTPUT_DIR}"; fi
[[ -n "${CONSOLE_URL}" ]] || { echo "ERROR: Galileo instance URL intake is required via --galileo-console-url" >&2; exit 2; }
exec python3 "${SCRIPT_DIR}/render_bundle.py" --spec "${SPEC}" --output-dir "${OUTPUT_DIR}" --galileo-console-url "${CONSOLE_URL}"
