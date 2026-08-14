#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_SPEC="${SKILL_DIR}/template.example"

usage() {
    cat <<'EOF'
Galileo On-Prem Agent Control Setup

Usage:
  bash skills/galileo-on-prem-agent-control-setup/scripts/setup.sh --render [options]
  bash skills/galileo-on-prem-agent-control-setup/scripts/setup.sh --validate --output-dir DIR
  bash skills/galileo-on-prem-agent-control-setup/scripts/setup.sh LIFECYCLE_MODE [options]

Modes:
  --render                 Render a non-secret immutable lifecycle bundle
  --validate               Validate an existing rendered bundle
  --doctor                 Alias for render; includes fail-closed doctor findings
  --feature-matrix         Alias for render; includes coverage-report.json
  --preflight              Capture fresh read-only target-bound evidence
  --apply-install          Fail-closed Galileo/CSE install handoff sentinel
  --apply-upgrade          Fail-closed Galileo/CSE upgrade handoff sentinel
  --status                 Redacted read-only release status
  --plan-rollback          Render a rollback plan
  --apply-rollback         Fail-closed Galileo/CSE rollback handoff sentinel
  --plan-uninstall         Render a retention-first uninstall plan
  --apply-uninstall        Fail closed; use the retention-first manual handoff

Options:
  --spec PATH              Non-secret YAML/JSON intake (default: template.example)
  --output-dir DIR         New output directory; existing directories are rejected
  --galileo-console-url URL
                           Required Galileo instance console URL override
  --kubeconfig PATH        Required chmod-600 kubeconfig; snapshotted per lifecycle action
  --image-evidence-file PATH
                           Required private digest-pinned image evidence for non-uninstall preflight
  --endpoint-evidence-file PATH
                           Required private host-only endpoint evidence for non-uninstall preflight
  --help                   Show help without writing or contacting Kubernetes

This skill performs no lifecycle mutation. Read-only preflight binds an exact
kube context and fresh evidence into the joint-session handoff. Every
--apply-* mode fails before kubeconfig, bundle, subprocess, or state access.
Umbrella ownership emits an overlay only. Inline --password, --token, --secret,
--api-key, --set, and --set-string inputs are rejected.
EOF
}

MODE=""
SPEC="${DEFAULT_SPEC}"
OUTPUT_DIR=""
CONSOLE_URL=""

if [[ $# -eq 0 ]]; then usage; exit 0; fi
case "$1" in
    --preflight|--apply-install|--apply-upgrade|--status|--plan-rollback|--apply-rollback|--plan-uninstall|--apply-uninstall)
        exec python3 "${SCRIPT_DIR}/lifecycle.py" "$@"
        ;;
esac
while [[ $# -gt 0 ]]; do
    case "$1" in
        --render|--doctor|--feature-matrix) MODE="render"; shift ;;
        --validate) MODE="validate"; shift ;;
        --spec) [[ $# -ge 2 ]] || { echo "ERROR: --spec requires a value" >&2; exit 2; }; SPEC="$2"; shift 2 ;;
        --output-dir) [[ $# -ge 2 ]] || { echo "ERROR: --output-dir requires a value" >&2; exit 2; }; OUTPUT_DIR="$2"; shift 2 ;;
        --galileo-console-url) [[ $# -ge 2 ]] || { echo "ERROR: --galileo-console-url requires a value" >&2; exit 2; }; CONSOLE_URL="$2"; shift 2 ;;
        --password|--token|--secret|--api-key|--set|--set-string)
            echo "ERROR: direct secret/value flags are forbidden; use out-of-band Kubernetes Secret references" >&2
            exit 2 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

[[ -n "${MODE}" ]] || { echo "ERROR: choose --render or --validate" >&2; exit 2; }
[[ -n "${OUTPUT_DIR}" ]] || { echo "ERROR: --output-dir is required" >&2; exit 2; }

if [[ "${MODE}" == "validate" ]]; then
    exec "${SCRIPT_DIR}/validate.sh" --output-dir "${OUTPUT_DIR}"
fi
[[ -n "${CONSOLE_URL}" ]] || { echo "ERROR: Galileo instance URL intake is required via --galileo-console-url" >&2; exit 2; }
exec python3 "${SCRIPT_DIR}/render_bundle.py" \
    --spec "${SPEC}" --output-dir "${OUTPUT_DIR}" --galileo-console-url "${CONSOLE_URL}"
