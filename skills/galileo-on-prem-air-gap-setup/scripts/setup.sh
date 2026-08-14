#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
usage() { cat <<'EOF'
Galileo On-Prem Air-Gap Setup

Usage:
  bash skills/galileo-on-prem-air-gap-setup/scripts/setup.sh --render [options]
  bash skills/galileo-on-prem-air-gap-setup/scripts/setup.sh --verify --bundle DIR --galileo-console-url URL
  bash skills/galileo-on-prem-air-gap-setup/scripts/setup.sh --push-registry

Modes: --render --validate --doctor --feature-matrix --verify --verify-no-egress --push-registry
Options:
  --spec PATH
  --output-dir DIR
  --bundle DIR
  --galileo-console-url URL   Required exact Galileo instance console URL for every mode
  --push-registry             Permanent fail-closed registry handoff sentinel;
                              it reads no bundle, auth, approval, or result file
  --help

This skill never mutates Kubernetes or a registry. Inline passwords, tokens,
credentials, --set, and insecure-TLS flags are forbidden.
EOF
}
if [[ $# -eq 0 ]]; then usage; exit 0; fi
case "$1" in
  --verify|--verify-no-egress|--push-registry) exec python3 "${SCRIPT_DIR}/supply_chain.py" "$@" ;;
  --help|-h) usage; exit 0 ;;
esac
MODE=""; SPEC="${SKILL_DIR}/template.example"; OUTPUT=""; CONSOLE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --render|--doctor|--feature-matrix) MODE=render; shift ;;
    --validate) MODE=validate; shift ;;
    --spec) [[ $# -ge 2 ]] || exit 2; SPEC="$2"; shift 2 ;;
    --output-dir) [[ $# -ge 2 ]] || exit 2; OUTPUT="$2"; shift 2 ;;
    --galileo-console-url) [[ $# -ge 2 ]] || exit 2; CONSOLE="$2"; shift 2 ;;
    --password|--token|--credential|--set|--set-string|--insecure-skip-tls-verify) echo "ERROR: unsafe direct input is forbidden" >&2; exit 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; exit 2 ;;
  esac
done
[[ -n "${MODE}" && -n "${OUTPUT}" ]] || { echo "ERROR: mode and --output-dir are required" >&2; exit 2; }
[[ -n "${CONSOLE}" ]] || { echo "ERROR: Galileo instance URL intake is required via --galileo-console-url" >&2; exit 2; }
if [[ "${MODE}" == validate ]]; then
  exec "${SCRIPT_DIR}/validate.sh" --output-dir "${OUTPUT}" --galileo-console-url "${CONSOLE}"
fi
exec python3 "${SCRIPT_DIR}/supply_chain.py" --render --spec "${SPEC}" --output-dir "${OUTPUT}" --galileo-console-url "${CONSOLE}"
