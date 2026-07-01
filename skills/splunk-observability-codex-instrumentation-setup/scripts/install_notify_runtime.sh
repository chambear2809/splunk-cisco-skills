#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNTIME_SOURCE="${SKILL_DIR}/runtime"

CODEX_HOME_TARGET="${CODEX_HOME:-${HOME}/.codex}"
SERVICE_NAME="codex-cli"
ENVIRONMENT_NAME="prod"
REALM="us0"
TRACE_ENDPOINT=""
METRICS_ENDPOINT=""
PYTHON_VERSION="3.13.14"
DRY_RUN=false

usage() {
  cat <<'EOF'
Install the durable Codex turn-notify runtime.

The install is an explicit one-time dependency resolution step. Per-turn
notification never invokes uv, pip, or another package manager.

Usage:
  install_notify_runtime.sh [options]

Options:
  --codex-home DIR          Target CODEX_HOME (default: ~/.codex)
  --service-name NAME       service.name and sf_service (default: codex-cli)
  --environment NAME        deployment.environment and sf_environment (default: prod)
  --realm REALM             Splunk realm (default: us0)
  --trace-endpoint URL      Override the direct OTLP/HTTP trace endpoint
  --metrics-endpoint URL    Override the direct OTLP/HTTP metrics endpoint
  --python-version VERSION  Exact uv-managed Python version (default: 3.13.14)
  --dry-run                 Validate and print the plan without writing
  --help                    Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --codex-home) CODEX_HOME_TARGET="$2"; shift 2 ;;
    --service-name) SERVICE_NAME="$2"; shift 2 ;;
    --environment) ENVIRONMENT_NAME="$2"; shift 2 ;;
    --realm) REALM="$2"; shift 2 ;;
    --trace-endpoint) TRACE_ENDPOINT="$2"; shift 2 ;;
    --metrics-endpoint) METRICS_ENDPOINT="$2"; shift 2 ;;
    --python-version) PYTHON_VERSION="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

for required in \
  "${RUNTIME_SOURCE}/codex-splunk-o11y-notify.zsh" \
  "${RUNTIME_SOURCE}/codex-splunk-o11y-notify-span.py" \
  "${RUNTIME_SOURCE}/codex-splunk-o11y-health.zsh" \
  "${RUNTIME_SOURCE}/requirements-notify.lock"; do
  [[ -f "${required}" ]] || { printf 'Missing runtime source: %s\n' "${required}" >&2; exit 1; }
done

# Validate non-secret config before making any target changes. Values travel as
# argv only because none of them are credentials.
python3 - "${SERVICE_NAME}" "${ENVIRONMENT_NAME}" "${REALM}" "${TRACE_ENDPOINT}" "${METRICS_ENDPOINT}" "${PYTHON_VERSION}" <<'PY'
import re
import sys
from urllib.parse import urlsplit

service, environment, realm, trace_endpoint, metrics_endpoint, python_version = sys.argv[1:]
for label, value in (("service name", service), ("environment", environment), ("realm", realm)):
    if not value or len(value) > 200 or any(ord(char) < 32 for char in value):
        raise SystemExit(f"invalid {label}")
if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", python_version):
    raise SystemExit("python version must be an exact X.Y.Z version")
for label, endpoint in (("trace", trace_endpoint), ("metrics", metrics_endpoint)):
    if not endpoint:
        continue
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SystemExit(f"{label} endpoint must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise SystemExit(f"{label} endpoint must not contain credentials")
    if parsed.scheme == "http" and (parsed.hostname or "").lower() not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise SystemExit(f"{label} endpoint must use HTTPS unless it is loopback")
PY

if [[ "${DRY_RUN}" == true ]]; then
  printf 'Would install Codex notify assets into %s/bin\n' "${CODEX_HOME_TARGET}"
  printf 'Would build pinned Python %s runtime at %s/o11y-venv\n' "${PYTHON_VERSION}" "${CODEX_HOME_TARGET}"
  printf 'Would sync hash-locked packages from https://pypi.org/simple with user uv config disabled\n'
  printf 'Would write non-secret runtime config service=%s environment=%s realm=%s\n' \
    "${SERVICE_NAME}" "${ENVIRONMENT_NAME}" "${REALM}"
  exit 0
fi

UV_BIN="${UV_BIN:-$(command -v uv || true)}"
[[ -n "${UV_BIN}" && -x "${UV_BIN}" ]] || {
  printf 'uv is required for the one-time runtime build\n' >&2
  exit 1
}

/bin/mkdir -p "${CODEX_HOME_TARGET}" "${CODEX_HOME_TARGET}/bin" "${CODEX_HOME_TARGET}/log"
/bin/chmod 700 "${CODEX_HOME_TARGET}/bin" "${CODEX_HOME_TARGET}/log"
STAGE_ROOT="$(/usr/bin/mktemp -d "${CODEX_HOME_TARGET}/.o11y-runtime-stage.XXXXXX")"
INSTALL_COMMITTED=false
declare -a COMMIT_TARGETS=()
declare -a COMMIT_BACKUPS=()

cleanup() {
  if [[ "${INSTALL_COMMITTED}" != true ]]; then
    local index target backup
    for ((index=${#COMMIT_TARGETS[@]} - 1; index >= 0; index--)); do
      target="${COMMIT_TARGETS[index]}"
      backup="${COMMIT_BACKUPS[index]}"
      /bin/rm -rf "${target}" 2>/dev/null || true
      if [[ -e "${backup}" || -L "${backup}" ]]; then
        /bin/mkdir -p "$(/usr/bin/dirname "${target}")" 2>/dev/null || true
        /bin/mv "${backup}" "${target}" 2>/dev/null || true
      fi
    done
  fi
  if [[ -n "${STAGE_ROOT}" && -d "${STAGE_ROOT}" ]]; then
    /bin/rm -rf "${STAGE_ROOT}"
  fi
}
trap cleanup EXIT

STAGE_VENV="${STAGE_ROOT}/o11y-venv"
STAGE_CONFIG="${STAGE_ROOT}/codex-splunk-o11y-runtime.json"
STAGE_BIN="${STAGE_ROOT}/bin"
STAGE_RUNTIME="${STAGE_ROOT}/o11y-runtime"
/bin/mkdir -p "${STAGE_BIN}" "${STAGE_RUNTIME}"

# UV_NO_CONFIG is essential: a stale workstation-level private index must not
# redirect this runtime build. Hashes in the lock file authenticate every
# accepted distribution from the explicit public index.
UV_NO_CONFIG=1 "${UV_BIN}" venv --python "${PYTHON_VERSION}" "${STAGE_VENV}"
UV_NO_CONFIG=1 "${UV_BIN}" pip sync \
  --python "${STAGE_VENV}/bin/python" \
  --require-hashes \
  --default-index https://pypi.org/simple \
  "${RUNTIME_SOURCE}/requirements-notify.lock"

SERVICE_NAME="${SERVICE_NAME}" \
ENVIRONMENT_NAME="${ENVIRONMENT_NAME}" \
REALM="${REALM}" \
TRACE_ENDPOINT="${TRACE_ENDPOINT}" \
METRICS_ENDPOINT="${METRICS_ENDPOINT}" \
python3 - "${STAGE_CONFIG}" <<'PY'
import json
import os
import pathlib
import sys

config = {
    "schema_version": 1,
    "service_name": os.environ["SERVICE_NAME"],
    "environment": os.environ["ENVIRONMENT_NAME"],
    "realm": os.environ["REALM"],
}
if os.environ.get("TRACE_ENDPOINT"):
    config["trace_endpoint"] = os.environ["TRACE_ENDPOINT"]
if os.environ.get("METRICS_ENDPOINT"):
    config["metrics_endpoint"] = os.environ["METRICS_ENDPOINT"]
path = pathlib.Path(sys.argv[1])
path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
path.chmod(0o600)
PY

CODEX_HOME="${CODEX_HOME_TARGET}" \
CODEX_SPLUNK_O11Y_RUNTIME_CONFIG="${STAGE_CONFIG}" \
  "${STAGE_VENV}/bin/python" "${RUNTIME_SOURCE}/codex-splunk-o11y-notify-span.py" --health >/dev/null
CODEX_HOME="${CODEX_HOME_TARGET}" \
CODEX_SPLUNK_O11Y_RUNTIME_CONFIG="${STAGE_CONFIG}" \
  "${STAGE_VENV}/bin/python" "${RUNTIME_SOURCE}/codex-splunk-o11y-notify-span.py" --offline-smoke >/dev/null

/usr/bin/install -m 0700 \
  "${RUNTIME_SOURCE}/codex-splunk-o11y-notify.zsh" \
  "${STAGE_BIN}/codex-splunk-o11y-notify.zsh"
/usr/bin/install -m 0700 \
  "${RUNTIME_SOURCE}/codex-splunk-o11y-notify-span.py" \
  "${STAGE_BIN}/codex-splunk-o11y-notify-span.py"
/usr/bin/install -m 0700 \
  "${RUNTIME_SOURCE}/codex-splunk-o11y-health.zsh" \
  "${STAGE_BIN}/codex-splunk-o11y-health.zsh"
/usr/bin/install -m 0600 \
  "${RUNTIME_SOURCE}/requirements-notify.lock" \
  "${STAGE_RUNTIME}/requirements-notify.lock"

LOCK_SHA="$(/usr/bin/shasum -a 256 "${RUNTIME_SOURCE}/requirements-notify.lock" | /usr/bin/awk '{print $1}')"
UV_VERSION="$(UV_NO_CONFIG=1 "${UV_BIN}" --version)"
LOCK_SHA="${LOCK_SHA}" UV_VERSION="${UV_VERSION}" PYTHON_VERSION="${PYTHON_VERSION}" \
python3 - "${STAGE_RUNTIME}/manifest.json" <<'PY'
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

manifest = {
    "schema_version": 1,
    "installed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "python_version": os.environ["PYTHON_VERSION"],
    "requirements_sha256": os.environ["LOCK_SHA"],
    "uv_version": os.environ["UV_VERSION"],
    "package_installation_during_notify": False,
}
path = pathlib.Path(sys.argv[1])
path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
path.chmod(0o600)
PY

# Commit every managed artifact as one rollback domain. Renames stay on the
# CODEX_HOME filesystem; if any later move or the installed health check fails,
# the EXIT trap restores every prior artifact rather than only the venv.
staged_paths=(
  "${STAGE_VENV}"
  "${STAGE_BIN}/codex-splunk-o11y-notify.zsh"
  "${STAGE_BIN}/codex-splunk-o11y-notify-span.py"
  "${STAGE_BIN}/codex-splunk-o11y-health.zsh"
  "${STAGE_CONFIG}"
  "${STAGE_RUNTIME}/requirements-notify.lock"
  "${STAGE_RUNTIME}/manifest.json"
)
target_paths=(
  "${CODEX_HOME_TARGET}/o11y-venv"
  "${CODEX_HOME_TARGET}/bin/codex-splunk-o11y-notify.zsh"
  "${CODEX_HOME_TARGET}/bin/codex-splunk-o11y-notify-span.py"
  "${CODEX_HOME_TARGET}/bin/codex-splunk-o11y-health.zsh"
  "${CODEX_HOME_TARGET}/codex-splunk-o11y-runtime.json"
  "${CODEX_HOME_TARGET}/o11y-runtime/requirements-notify.lock"
  "${CODEX_HOME_TARGET}/o11y-runtime/manifest.json"
)

for ((index=0; index < ${#target_paths[@]}; index++)); do
  target="${target_paths[index]}"
  staged="${staged_paths[index]}"
  backup="${STAGE_ROOT}/backup-${index}"
  /bin/mkdir -p "$(/usr/bin/dirname "${target}")"
  if [[ -e "${target}" || -L "${target}" ]]; then
    /bin/mv "${target}" "${backup}"
  fi
  COMMIT_TARGETS+=("${target}")
  COMMIT_BACKUPS+=("${backup}")
  /bin/mv "${staged}" "${target}"
done
/bin/chmod 700 "${CODEX_HOME_TARGET}/o11y-runtime"

CODEX_HOME="${CODEX_HOME_TARGET}" \
  "${CODEX_HOME_TARGET}/bin/codex-splunk-o11y-health.zsh" >/dev/null

INSTALL_COMMITTED=true

printf 'Installed durable Codex notify runtime in %s\n' "${CODEX_HOME_TARGET}"
printf 'Offline validation passed. Run %s/bin/codex-splunk-o11y-health.zsh --live for an export smoke test.\n' \
  "${CODEX_HOME_TARGET}"
printf 'The Codex notify command must reference %s/bin/codex-splunk-o11y-notify.zsh.\n' \
  "${CODEX_HOME_TARGET}"
