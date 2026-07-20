#!/usr/bin/env bash
# Install Cisco's signed DefenseClaw release and configure its local Lemonade LLM.
set -euo pipefail

DEFAULT_MODEL="Qwen3.6-27B-GGUF"
HOST=""
USER_NAME=""
MODEL="$DEFAULT_MODEL"
RELEASE=""
KNOWN_HOSTS="${HOME}/.ssh/known_hosts"
LEMONADE_BASE_URL="http://127.0.0.1:13305"
MODEL_BASE_URL="http://127.0.0.1:13305/api/v1"
GUARDRAIL_MODE="observe"
TIMEOUT_SECONDS=3600
APPLY=false
REPLACE_ACTIVE_MODEL=false

usage() {
  cat <<'EOF'
Usage:
  setup.sh --host HOST --user USER [options]

Preflight is the default and makes no remote changes. Add --apply to install
or upgrade Cisco DefenseClaw, download/load the requested Lemonade model, and
start the DefenseClaw gateway.

Required:
  --host HOST                 Pre-pinned SSH host name or IP address
  --user USER                 Remote Linux user

Options:
  --model ID                  Lemonade model ID (default: Qwen3.6-27B-GGUF)
  --release VERSION|latest    Required with --apply; explicit immutable version or latest
  --known-hosts-file FILE     Pinned SSH known_hosts file (default: ~/.ssh/known_hosts)
  --lemonade-base-url URL     Loopback Lemonade management URL (default: :13305)
  --model-base-url URL        Stable loopback Lemonade API (default: :13305/api/v1)
  --guardrail-mode MODE       Codex policy mode: observe or action (default: observe)
  --timeout-seconds SECONDS   Model download timeout (default: 3600)
  --replace-active-model      Allow replacing an active Lemonade model
  --apply                     Perform the installation and configuration
  --help                      Show this help
EOF
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

validate_safe_token() {
  local label="$1" value="$2" pattern="$3"
  [[ "$value" =~ $pattern ]] || die "$label contains unsupported characters"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="${2:-}"; shift 2 ;;
    --user) USER_NAME="${2:-}"; shift 2 ;;
    --model) MODEL="${2:-}"; shift 2 ;;
    --release) RELEASE="${2:-}"; shift 2 ;;
    --known-hosts-file) KNOWN_HOSTS="${2:-}"; shift 2 ;;
    --lemonade-base-url) LEMONADE_BASE_URL="${2:-}"; shift 2 ;;
    --model-base-url) MODEL_BASE_URL="${2:-}"; shift 2 ;;
    --guardrail-mode) GUARDRAIL_MODE="${2:-}"; shift 2 ;;
    --timeout-seconds) TIMEOUT_SECONDS="${2:-}"; shift 2 ;;
    --replace-active-model) REPLACE_ACTIVE_MODEL=true; shift ;;
    --apply) APPLY=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ -n "$HOST" ]] || die "--host is required"
[[ -n "$USER_NAME" ]] || die "--user is required"
validate_safe_token "host" "$HOST" '^[A-Za-z0-9._:-]+$'
validate_safe_token "user" "$USER_NAME" '^[a-z_][a-z0-9_-]*$'
validate_safe_token "model" "$MODEL" '^[A-Za-z0-9._+-]+$'
[[ "$TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] || die "--timeout-seconds must be a positive integer"
[[ "$LEMONADE_BASE_URL" =~ ^http://(127\.0\.0\.1|localhost):[0-9]{1,5}$ ]] || die "--lemonade-base-url must be a loopback HTTP origin"
[[ "$MODEL_BASE_URL" =~ ^http://(127\.0\.0\.1|localhost):[0-9]{1,5}/(api/)?v1$ ]] || die "--model-base-url must be a stable loopback OpenAI-compatible /api/v1 or /v1 URL"
[[ "$GUARDRAIL_MODE" == observe || "$GUARDRAIL_MODE" == action ]] || die "--guardrail-mode must be observe or action"
[[ -r "$KNOWN_HOSTS" ]] || die "--known-hosts-file is not readable: $KNOWN_HOSTS"

for command in ssh ssh-keygen curl jq; do
  command -v "$command" >/dev/null 2>&1 || die "local prerequisite is missing: $command"
done

ssh-keygen -F "$HOST" -f "$KNOWN_HOSTS" >/dev/null 2>&1 || die "SSH host key for $HOST is not pinned in $KNOWN_HOSTS"

ssh_base=(ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$KNOWN_HOSTS" -o GlobalKnownHostsFile=/dev/null -o ConnectTimeout=10 "${USER_NAME}@${HOST}")

if [[ "$APPLY" == true ]]; then
  [[ -n "$RELEASE" ]] || die "--release VERSION or --release latest is required with --apply"
  validate_safe_token "release" "$RELEASE" '^(latest|[0-9]+\.[0-9]+\.[0-9]+)$'
fi

"${ssh_base[@]}" 'bash -s' -- "$MODEL" "$LEMONADE_BASE_URL" "$MODEL_BASE_URL" <<'REMOTE'
set -euo pipefail
model="$1"
lemonade_base_url="$2"
model_base_url="$3"
export PATH="$HOME/.local/bin:$PATH"
for command in lemonade curl jq timeout; do
  command -v "$command" >/dev/null
done
if command -v codex >/dev/null 2>&1; then
  codex --version
else
  printf 'Codex: not installed\n'
fi
lemonade status
lemonade list --downloaded
if command -v defenseclaw >/dev/null 2>&1; then
  defenseclaw --version
else
  printf 'DefenseClaw: not installed\n'
fi
if command -v defenseclaw-gateway >/dev/null 2>&1; then
  defenseclaw-gateway status || true
else
  printf 'DefenseClaw gateway: not installed\n'
fi
curl --connect-timeout 2 --max-time 5 -fsS "$lemonade_base_url/v1/models" \
  | jq -e '.data | type == "array"' >/dev/null
if timeout 20 lemonade list | awk 'NR > 2 {print $1}' | grep -Fqx "$model"; then
  printf 'Requested model is registered: %s\n' "$model"
else
  printf 'Requested model is not registered: %s\n' "$model" >&2
  exit 20
fi
curl --connect-timeout 2 --max-time 5 -fsS "$model_base_url/models" \
  | jq -e '.data | type == "array" and length > 0' >/dev/null || true
REMOTE

if [[ "$APPLY" != true ]]; then
  printf 'Preflight passed. Re-run with --apply to install/configure DefenseClaw.\n'
  exit 0
fi

if [[ "$RELEASE" == latest ]]; then
  RELEASE="$(curl -fsSL https://api.github.com/repos/cisco-ai-defense/defenseclaw/releases/latest | jq -er '.tag_name | select(test("^[0-9]+\\.[0-9]+\\.[0-9]+$"))')"
fi

"${ssh_base[@]}" 'bash -s' -- "$MODEL" "$RELEASE" "$TIMEOUT_SECONDS" "$REPLACE_ACTIVE_MODEL" "$LEMONADE_BASE_URL" "$MODEL_BASE_URL" "$GUARDRAIL_MODE" <<'REMOTE'
set -euo pipefail
model="$1"
release="$2"
timeout_seconds="$3"
replace_active_model="$4"
lemonade_base_url="$5"
model_base_url="$6"
guardrail_mode="$7"
export PATH="$HOME/.local/bin:$PATH"

installer="$(mktemp)"
trap 'rm -f "$installer"' EXIT
if command -v defenseclaw >/dev/null 2>&1; then
  installed_version="$(defenseclaw --version | awk '{print $3}')"
  if [[ "$installed_version" == "$release" ]]; then
    printf 'DefenseClaw %s is already installed.\n' "$release"
  else
    defenseclaw upgrade --version "$release" --yes
  fi
else
  curl -fsSL "https://raw.githubusercontent.com/cisco-ai-defense/defenseclaw/${release}/scripts/install.sh" -o "$installer"
  VERSION="$release" bash "$installer" --yes --connector none
fi

command -v codex >/dev/null 2>&1 || {
  printf 'Codex is required for the DefenseClaw hook connector.\n' >&2
  exit 25
}
for scanner in skill-scanner mcp-scanner; do
  scanner_source="$HOME/.defenseclaw/.venv/bin/$scanner"
  scanner_target="$HOME/.local/bin/$scanner"
  [[ -x "$scanner_source" ]] || {
    printf 'DefenseClaw scanner is missing: %s\n' "$scanner_source" >&2
    exit 26
  }
  if [[ -e "$scanner_target" || -L "$scanner_target" ]]; then
    [[ "$(readlink -f "$scanner_target")" == "$(readlink -f "$scanner_source")" ]] || {
      printf 'Refusing to replace unrelated scanner entry point: %s\n' "$scanner_target" >&2
      exit 27
    }
  else
    ln -s "$scanner_source" "$scanner_target"
  fi
done

downloaded() {
  timeout 20 lemonade list --downloaded | awk 'NR > 2 {print $1}' | grep -Fqx "$model"
}

if ! downloaded; then
  lemonade pull "$model"
  elapsed=0
  until downloaded; do
    if (( elapsed >= timeout_seconds )); then
      printf 'Timed out waiting for Lemonade model download: %s\n' "$model" >&2
      exit 21
    fi
    sleep 10
    elapsed=$((elapsed + 10))
  done
fi

active_model="$(lemonade status | awk '$1 == "Model" {in_models=1; next} in_models && NF >= 5 && $1 !~ /^-+$/ {print $1; exit}')"
if [[ -n "$active_model" && "$active_model" != "$model" && "$replace_active_model" != true ]]; then
  printf 'Refusing to replace active model %s without --replace-active-model\n' "$active_model" >&2
  exit 22
fi

config_file="$HOME/.defenseclaw/config.yaml"
config_backup=""
config_existed=false
if [[ -f "$config_file" ]]; then
  config_existed=true
  config_backup="${config_file}.before-deskside-$(date -u +%Y%m%dT%H%M%SZ)"
  cp -p "$config_file" "$config_backup"
  printf 'Backed up DefenseClaw config: %s\n' "$config_backup"
fi

codex_config="$HOME/.codex/config.toml"
codex_config_backup=""
codex_config_existed=false
if [[ -f "$codex_config" ]]; then
  codex_config_existed=true
  codex_config_backup="${codex_config}.before-defenseclaw-$(date -u +%Y%m%dT%H%M%SZ)"
  cp -p "$codex_config" "$codex_config_backup"
  printf 'Backed up Codex config: %s\n' "$codex_config_backup"
fi

model_switched=false
configuration_touched=false
rollback() {
  local exit_code="${1:-$?}"
  if [[ "$config_existed" == true && -n "$config_backup" && -f "$config_backup" ]]; then
    cp -p "$config_backup" "$config_file" || true
  elif [[ "$config_existed" == false ]]; then
    rm -f "$config_file" || true
  fi
  if [[ "$codex_config_existed" == true && -n "$codex_config_backup" && -f "$codex_config_backup" ]]; then
    cp -p "$codex_config_backup" "$codex_config" || true
  elif [[ "$codex_config_existed" == false ]]; then
    rm -f "$codex_config" || true
  fi
  if [[ "$configuration_touched" == true ]]; then
    defenseclaw-gateway restart || defenseclaw-gateway start || true
  fi
  if [[ "$model_switched" == true && -n "$active_model" ]]; then
    lemonade load "$active_model" || true
  fi
  exit "$exit_code"
}
trap rollback ERR

if [[ "$active_model" != "$model" ]]; then
  lemonade load "$model"
  model_switched=true
fi

model_api_waited=0
until curl --connect-timeout 2 --max-time 5 -fsS "$model_base_url/models" \
  | jq -e --arg model "$model" '.data | any(.[]; .id == $model)' >/dev/null; do
  if (( model_api_waited >= timeout_seconds )); then
    printf 'Timed out waiting for one Lemonade inference model to become ready.\n' >&2
    rollback 24
  fi
  sleep 2
  model_api_waited=$((model_api_waited + 2))
done

configuration_touched=true
defenseclaw setup llm \
  --provider lm_studio \
  --instance-name '' \
  --model "$model" \
  --base-url "$model_base_url" \
  --role unified \
  --ping \
  --non-interactive
defenseclaw init \
  --skip-install \
  --enable-guardrail \
  --connector codex \
  --profile "$guardrail_mode" \
  --scanner-mode local \
  --with-judge \
  --fail-mode open \
  --no-human-approval \
  --start-gateway \
  --verify \
  --non-interactive \
  --yes
defenseclaw setup codex \
  --mode "$guardrail_mode" \
  --rule-pack default \
  --enable-judge \
  --judge-hook-connectors codex \
  --fail-mode open \
  --no-human-approval \
  --yes \
  --restart

# Connector setup rewrites managed Codex tables. Pin the agent model after that
# final rewrite so the registered Lemonade name cannot drift to another cache.
python3 - "$codex_config" "$model" <<'PY'
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import sys

path = Path(sys.argv[1])
model = sys.argv[2]
st = path.lstat()
if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
    raise SystemExit(f"refusing non-regular Codex config: {path}")
text = path.read_text(encoding="utf-8")
line = f"model = {json.dumps(model)}"
pattern = re.compile(r"(?m)^model\s*=\s*(?:\"(?:\\.|[^\"])*\"|'[^']*')\s*$")
text, count = pattern.subn(line, text, count=1)
if count == 0:
    text = line + "\n" + text
fd, temporary = tempfile.mkstemp(prefix=".config.toml.", dir=path.parent)
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
codex --strict-config --version >/dev/null

for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if curl --connect-timeout 2 --max-time 5 -fsS http://127.0.0.1:18970/health \
    | jq -e --arg mode "$guardrail_mode" \
      '.api.state == "running" and .guardrail.state == "running" and
       .guardrail.details.connector == "codex" and .guardrail.details.policy_mode == $mode' >/dev/null; then
    break
  fi
  sleep 2
  if [[ "$attempt" == 10 ]]; then
    printf 'DefenseClaw API did not become healthy after restart.\n' >&2
    exit 23
  fi
done
jq -n --arg model "$model" '{model: $model, messages: [{role: "user", content: "Reply READY."}], max_tokens: 2, stream: false}' \
  | curl --connect-timeout 2 --max-time 60 -fsS -H 'Content-Type: application/json' -d @- "$model_base_url/chat/completions" \
  | jq -e '.choices | length > 0' >/dev/null
trap - ERR
REMOTE
