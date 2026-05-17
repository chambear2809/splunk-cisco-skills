#!/usr/bin/env bash
# Offline smoke test for splunk-db-connect-setup.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="${SCRIPT_DIR}/setup.sh"
RENDERER="${SCRIPT_DIR}/render_assets.py"
VALIDATE="${SCRIPT_DIR}/validate.sh"
TEMPLATE="${SCRIPT_DIR}/../template.example"

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

failed=0
fail() { echo "FAIL: $1" >&2; failed=$((failed + 1)); }
ok() { echo "OK:   $1"; }

if python3 "${RENDERER}" --help >/dev/null 2>&1; then ok "renderer --help"; else fail "renderer --help"; fi
if bash "${SETUP}" --help >/dev/null 2>&1; then ok "setup.sh --help"; else fail "setup.sh --help"; fi
if bash "${VALIDATE}" --help >/dev/null 2>&1; then ok "validate.sh --help"; else fail "validate.sh --help"; fi

if bash "${SETUP}" --preflight --spec "${TEMPLATE}" >/dev/null 2>&1; then
    ok "template preflight"
else
    fail "template preflight"
fi

if bash "${SETUP}" --render --validate --spec "${TEMPLATE}" --output-dir "${tmp}/rendered" >/dev/null 2>&1; then
    ok "template render + validate"
else
    fail "template render + validate"
fi

cat >"${tmp}/secret.yaml" <<'YAML'
version: splunk-db-connect-setup/v1
platform:
  type: enterprise
topology:
  mode: single_sh
  install_targets:
    - search-tier
java:
  version: "17"
identities:
  - name: bad
    username: app
    password: plaintext
YAML
if bash "${SETUP}" --preflight --spec "${tmp}/secret.yaml" >/dev/null 2>&1; then
    fail "plaintext secret rejection"
else
    ok "plaintext secret rejection"
fi

cat >"${tmp}/bad-target.yaml" <<'YAML'
version: splunk-db-connect-setup/v1
platform:
  type: enterprise
topology:
  mode: single_sh
  install_targets:
    - indexer
java:
  version: "17"
YAML
if bash "${SETUP}" --preflight --spec "${tmp}/bad-target.yaml" >/dev/null 2>&1; then
    fail "indexer target rejection"
else
    ok "indexer target rejection"
fi

cat >"${tmp}/cloud-victoria.yaml" <<'YAML'
version: splunk-db-connect-setup/v1
platform:
  type: cloud_victoria
topology:
  mode: cloud_victoria
  install_targets:
    - search-tier
java:
  version: "21"
connections:
  - name: db
    jdbc_url: jdbc:postgresql://db.example.com:5432/app
YAML
if bash "${SETUP}" --preflight --spec "${tmp}/cloud-victoria.yaml" >/dev/null 2>&1; then
    fail "Cloud Victoria allowlist rejection"
else
    ok "Cloud Victoria allowlist rejection"
fi

cat >"${tmp}/cloud-classic.yaml" <<'YAML'
version: splunk-db-connect-setup/v1
platform:
  type: cloud_classic
topology:
  mode: cloud_classic
  install_targets:
    - search-tier
install:
  install_apps: true
java:
  version: "17"
YAML
if bash "${SETUP}" --preflight --spec "${tmp}/cloud-classic.yaml" >/dev/null 2>&1; then
    fail "Cloud Classic self-service rejection"
else
    ok "Cloud Classic self-service rejection"
fi

cat >"${tmp}/archived.yaml" <<'YAML'
version: splunk-db-connect-setup/v1
platform:
  type: enterprise
topology:
  mode: single_sh
  install_targets:
    - search-tier
java:
  version: "17"
drivers:
  - name: influx
    type: splunkbase
    splunkbase_id: "6759"
YAML
if bash "${SETUP}" --preflight --spec "${tmp}/archived.yaml" >/dev/null 2>&1; then
    fail "archived driver rejection"
else
    ok "archived driver rejection"
fi

cat >"${tmp}/hf-ha.yaml" <<'YAML'
version: splunk-db-connect-setup/v1
platform:
  type: enterprise
topology:
  mode: heavy_forwarder_ha
  install_targets:
    - heavy-forwarder
java:
  version: "21"
ha:
  enabled: true
YAML
if bash "${SETUP}" --preflight --spec "${tmp}/hf-ha.yaml" >"${tmp}/hf-ha.out" 2>&1 && grep -q "HF HA requested" "${tmp}/hf-ha.out"; then
    ok "HF HA warning"
else
    fail "HF HA warning"
fi

if (( failed > 0 )); then
    echo "${failed} smoke checks failed." >&2
    exit 1
fi

echo "All splunk-db-connect-setup offline smoke checks passed."
