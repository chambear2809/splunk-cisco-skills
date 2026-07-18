#!/usr/bin/env bash
# Validate the local Lemonade model, DefenseClaw configuration, and gateway.
set -euo pipefail

HOST=""
USER_NAME=""
MODEL="Qwen3.6-27B-GGUF"
KNOWN_HOSTS="${HOME}/.ssh/known_hosts"
LEMONADE_BASE_URL="http://127.0.0.1:13305"
MODEL_BASE_URL="http://127.0.0.1:13305/api/v1"
EXPECTED_MODE=""
LIVE=false
CHECK_INFERENCE=false

usage() {
  cat <<'EOF'
Usage:
  validate.sh --host HOST --user USER [options]

Verify that the remote Lemonade API, DefenseClaw local LLM configuration, and
gateway are healthy. --live runs the remote read-only checks; omitting it only
validates this script's interface.

Options:
  --model ID                  Expected Lemonade model registration
  --known-hosts-file FILE     Pinned SSH known_hosts file
  --lemonade-base-url URL     Loopback Lemonade management URL
  --model-base-url URL        Loopback OpenAI-compatible model URL
  --expect-mode MODE          Require observe or action policy mode
  --live                      Run remote read-only checks
  --check-inference           With --live, send a one-token benign canary
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="${2:-}"; shift 2 ;;
    --user) USER_NAME="${2:-}"; shift 2 ;;
    --model) MODEL="${2:-}"; shift 2 ;;
    --known-hosts-file) KNOWN_HOSTS="${2:-}"; shift 2 ;;
    --lemonade-base-url) LEMONADE_BASE_URL="${2:-}"; shift 2 ;;
    --model-base-url) MODEL_BASE_URL="${2:-}"; shift 2 ;;
    --expect-mode) EXPECTED_MODE="${2:-}"; shift 2 ;;
    --live) LIVE=true; shift ;;
    --check-inference) CHECK_INFERENCE=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'ERROR: unknown argument: %s\n' "$1" >&2; exit 1 ;;
  esac
done

if [[ "$LIVE" != true ]]; then
  printf 'Static validation passed. Add --live with --host and --user for remote validation.\n'
  exit 0
fi

[[ "$HOST" =~ ^[A-Za-z0-9._:-]+$ ]] || { printf 'ERROR: valid --host is required\n' >&2; exit 1; }
[[ "$USER_NAME" =~ ^[a-z_][a-z0-9_-]*$ ]] || { printf 'ERROR: valid --user is required\n' >&2; exit 1; }
[[ "$MODEL" =~ ^[A-Za-z0-9._+-]+$ ]] || { printf 'ERROR: valid --model is required\n' >&2; exit 1; }
[[ "$LEMONADE_BASE_URL" =~ ^http://(127\.0\.0\.1|localhost):[0-9]{1,5}$ ]] || { printf 'ERROR: --lemonade-base-url must be loopback\n' >&2; exit 1; }
[[ "$MODEL_BASE_URL" =~ ^http://(127\.0\.0\.1|localhost):[0-9]{1,5}/(api/)?v1$ ]] || { printf 'ERROR: --model-base-url must be loopback /api/v1 or /v1\n' >&2; exit 1; }
[[ -z "$EXPECTED_MODE" || "$EXPECTED_MODE" == observe || "$EXPECTED_MODE" == action ]] || { printf 'ERROR: --expect-mode must be observe or action\n' >&2; exit 1; }
[[ -r "$KNOWN_HOSTS" ]] || { printf 'ERROR: known_hosts file is not readable\n' >&2; exit 1; }
ssh-keygen -F "$HOST" -f "$KNOWN_HOSTS" >/dev/null 2>&1 || {
  printf 'ERROR: SSH host key is not pinned\n' >&2
  exit 1
}

ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$KNOWN_HOSTS" -o GlobalKnownHostsFile=/dev/null -o ConnectTimeout=10 "${USER_NAME}@${HOST}" 'bash -s' -- "$MODEL" "$LEMONADE_BASE_URL" "$MODEL_BASE_URL" "$CHECK_INFERENCE" "$EXPECTED_MODE" <<'REMOTE'
set -euo pipefail
model="$1"
lemonade_base_url="$2"
model_base_url="$3"
check_inference="$4"
expected_mode="$5"
export PATH="$HOME/.local/bin:$PATH"
curl --connect-timeout 2 --max-time 5 -fsS "$lemonade_base_url/v1/models" \
  | jq -e '.data | type == "array" and length > 0' >/dev/null
lemonade list --downloaded | awk 'NR > 2 {print $1}' | grep -Fqx "$model"
curl --connect-timeout 2 --max-time 5 -fsS "$model_base_url/models" \
  | jq -e --arg model "$model" '.data | any(.[]; .id == $model)' >/dev/null
active_model="$(lemonade status | awk '$1 == "Model" {in_models=1; next} in_models && NF >= 5 && $1 !~ /^-+$/ {print $1; exit}')"
[[ "$active_model" == "$model" ]]
defenseclaw --version
llm_config="$(defenseclaw setup llm --show)"
grep -F 'provider:' <<<"$llm_config" | grep -F 'lm_studio' >/dev/null
grep -F "$model" <<<"$llm_config" >/dev/null
grep -F "$model_base_url" <<<"$llm_config" >/dev/null
command -v skill-scanner >/dev/null
command -v mcp-scanner >/dev/null
[[ -x "$HOME/.defenseclaw/hooks/codex-hook.sh" ]]
python3 - "$model" <<'PY'
from pathlib import Path
import sys
import tomllib

with (Path.home() / ".codex" / "config.toml").open("rb") as handle:
    config = tomllib.load(handle)
if config.get("model") != sys.argv[1]:
    raise SystemExit("Codex model does not match the requested Lemonade registration")
PY
health="$(curl --connect-timeout 2 --max-time 5 -fsS http://127.0.0.1:18970/health)"
jq -e '.api.state == "running" and .guardrail.state == "running" and
       .guardrail.details.connector == "codex"' <<<"$health" >/dev/null
if [[ -n "$expected_mode" ]]; then
  jq -e --arg mode "$expected_mode" '.guardrail.details.policy_mode == $mode' <<<"$health" >/dev/null
  if [[ "$expected_mode" == action ]]; then
    jq -e '.guardrail.details.enforcement_enabled == true' <<<"$health" >/dev/null
  fi
fi
if [[ "$check_inference" == true ]]; then
  jq -n --arg model "$model" '{model: $model, messages: [{role: "user", content: "Reply READY."}], max_tokens: 2, stream: false}' \
    | curl --connect-timeout 2 --max-time 60 -fsS -H 'Content-Type: application/json' -d @- "$model_base_url/chat/completions" \
    | jq -e '.choices | length > 0' >/dev/null
fi
REMOTE
