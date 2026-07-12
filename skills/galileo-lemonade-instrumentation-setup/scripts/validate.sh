#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
collector_config=""
collector_binary=""
mode=""
native_pipeline="traces"
lemonade_service_name="lemonade-server"
client_service_name="lemonade-galileo-client"
client_receiver_endpoint="127.0.0.1:14318"
queue_policy="persistent"
queue_storage_directory="/var/lib/splunk-otel-collector/galileo-queue"
destination_fingerprint=""
production=false
galileo_proxy_url="http://127.0.0.1:18888"
allow_server_shared_receiver=false
allow_client_mirror=false
allow_custom_client_processors=false

usage() {
  cat <<'EOF'
Validate a staged Galileo/Lemonade collector configuration.

Usage:
  validate.sh --collector-config PATH --mode MODE [--collector-binary PATH]
              [--queue-policy persistent|memory] [--production]
              [--galileo-proxy-url URL] [--destination-fingerprint SHA256]

Production validation requires the exact collector binary, persistent queue,
destination fingerprint and matching queue namespace/runtime environment, plus
the protected tinyproxy binary/config/filter identity and successful bounded
allow/deny CONNECT probes. Server fan-out also needs
--allow-server-shared-receiver.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --collector-config|--collector-binary|--mode|--native-traces-pipeline|--lemonade-service-name|--client-service-name|--client-receiver-endpoint|--queue-policy|--queue-storage-directory|--galileo-proxy-url|--destination-fingerprint)
      [[ $# -ge 2 && -n "${2:-}" ]] || {
        echo "ERROR: $1 requires a nonempty value" >&2
        exit 2
      }
      case "$1" in
        --collector-config) collector_config="$2" ;;
        --collector-binary) collector_binary="$2" ;;
        --mode) mode="$2" ;;
        --native-traces-pipeline) native_pipeline="$2" ;;
        --lemonade-service-name) lemonade_service_name="$2" ;;
        --client-service-name) client_service_name="$2" ;;
        --client-receiver-endpoint) client_receiver_endpoint="$2" ;;
        --queue-policy) queue_policy="$2" ;;
        --queue-storage-directory) queue_storage_directory="$2" ;;
        --galileo-proxy-url) galileo_proxy_url="$2" ;;
        --destination-fingerprint) destination_fingerprint="$2" ;;
      esac
      shift 2
      ;;
    --production) production=true; shift ;;
    --allow-server-shared-receiver) allow_server_shared_receiver=true; shift ;;
    --allow-client-mirror) allow_client_mirror=true; shift ;;
    --allow-custom-client-processors) allow_custom_client_processors=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

[[ -n "$collector_config" && -f "$collector_config" ]] || {
  echo "ERROR: --collector-config must name a staged file" >&2
  exit 1
}
[[ "$mode" =~ ^(server-fanout|client-fanout|splunk-only)$ ]] || {
  echo "ERROR: --mode must be server-fanout, client-fanout, or splunk-only" >&2
  exit 1
}
[[ "$queue_policy" =~ ^(persistent|memory)$ ]] || {
  echo "ERROR: --queue-policy must be persistent or memory" >&2
  exit 1
}
if [[ "$production" == true && -z "$collector_binary" ]]; then
  echo "ERROR: --production requires --collector-binary with the installed binary" >&2
  exit 1
fi

validator_args=(
  --collector-config "$collector_config"
  --mode "$mode"
  --native-traces-pipeline "$native_pipeline"
  --lemonade-service-name "$lemonade_service_name"
  --client-service-name "$client_service_name"
  --client-receiver-endpoint "$client_receiver_endpoint"
  --queue-policy "$queue_policy"
  --queue-storage-directory "$queue_storage_directory"
  --galileo-proxy-url "$galileo_proxy_url"
)
if [[ -n "$destination_fingerprint" ]]; then
  validator_args+=(--destination-fingerprint "$destination_fingerprint")
fi
if [[ "$production" == true ]]; then
  validator_args+=(--production)
fi
if [[ "$allow_server_shared_receiver" == true ]]; then
  validator_args+=(--allow-server-shared-receiver)
fi
if [[ "$allow_client_mirror" == true ]]; then
  validator_args+=(--allow-client-mirror)
fi
if [[ "$allow_custom_client_processors" == true ]]; then
  validator_args+=(--allow-custom-client-processors)
fi
python3 "${SCRIPT_DIR}/validate_collector_config.py" "${validator_args[@]}"

if [[ -n "$collector_binary" ]]; then
  if [[ "$production" == true && "$collector_binary" != /* ]]; then
    echo "ERROR: --production requires an absolute --collector-binary path" >&2
    exit 1
  fi
  [[ -x "$collector_binary" ]] || {
    echo "ERROR: collector binary is not executable: $collector_binary" >&2
    exit 1
  }
  if [[ "$mode" != "splunk-only" ]]; then
    [[ -n "${GALILEO_OTLP_TRACES_ENDPOINT:-}" ]] || {
      echo "ERROR: export the reviewed non-secret Galileo endpoint before binary validation" >&2
      exit 1
    }
    python3 - "${GALILEO_OTLP_TRACES_ENDPOINT}" <<'PY'
import sys
import urllib.parse
value = sys.argv[1]
parsed = urllib.parse.urlparse(value)
if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
    raise SystemExit("ERROR: Galileo traces endpoint must be HTTPS without URL credentials")
if parsed.query or parsed.fragment or not parsed.path.strip("/"):
    raise SystemExit("ERROR: Galileo traces endpoint needs an exact path and no query/fragment")
PY
    # Literal collector placeholders are intentionally single-quoted.
    # shellcheck disable=SC2016
    if grep -Fq '${env:GALILEO_PROJECT_ID}' "$collector_config"; then
      [[ -n "${GALILEO_PROJECT_ID:-}" && -n "${GALILEO_LOG_STREAM_ID:-}" ]] || {
        echo "ERROR: the protected runtime environment is missing Galileo project/Log stream IDs" >&2
        exit 1
      }
    elif grep -Fq '${env:GALILEO_PROJECT}' "$collector_config"; then
      [[ -n "${GALILEO_PROJECT:-}" && -n "${GALILEO_LOG_STREAM:-}" ]] || {
        echo "ERROR: the protected runtime environment is missing Galileo project/Log stream names" >&2
        exit 1
      }
    fi
  fi
  (
    export GALILEO_API_KEY="collector-validation-placeholder"
    "$collector_binary" validate --config="$collector_config"
  )
fi
