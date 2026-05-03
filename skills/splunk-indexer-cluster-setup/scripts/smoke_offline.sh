#!/usr/bin/env bash
# Offline smoke test for splunk-indexer-cluster-setup. Renders both single-site
# and multisite plans and asserts every rendered artifact is present and
# well-formed (server.conf snippets, bootstrap, bundle, restart, maintenance,
# peer-ops, migration, redundancy when enabled, forwarder outputs).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_OUT_S="$(mktemp -d)"
TMP_OUT_M="$(mktemp -d)"
trap 'rm -rf "${TMP_OUT_S}" "${TMP_OUT_M}"' EXIT

# Single-site render with redundant managers + LB + forwarders.
bash "${SCRIPT_DIR}/setup.sh" \
    --phase render \
    --output-dir "${TMP_OUT_S}" \
    --cluster-mode single-site \
    --cluster-label prod-ss \
    --cluster-manager-uri https://cm01.example.com:8089 \
    --manager-hosts cm01.example.com,cm02.example.com \
    --manager-redundancy true \
    --manager-switchover-mode auto \
    --manager-lb-uri https://cm-lb.example.com:8089 \
    --replication-factor 3 \
    --search-factor 2 \
    --peer-hosts idx01.example.com,idx02.example.com,idx03.example.com \
    --sh-hosts sh01.example.com \
    --forwarder-hosts hf01.example.com,hf02.example.com \
    >/dev/null

# When manager redundancy is enabled, peer + SH server.conf must point at the
# LB / DNS endpoint, NOT a single manager host.
peer_uri=$(grep '^manager_uri' "${TMP_OUT_S}/cluster/peer-idx01.example.com/server.conf" | head -1)
[[ "${peer_uri}" == *"cm-lb.example.com"* ]] \
    || { echo "FAIL: redundant peer must reference LB URI; got '${peer_uri}'" >&2; exit 1; }
sh_uri=$(grep '^manager_uri' "${TMP_OUT_S}/cluster/sh-sh01.example.com/server.conf" | head -1)
[[ "${sh_uri}" == *"cm-lb.example.com"* ]] \
    || { echo "FAIL: redundant SH must reference LB URI; got '${sh_uri}'" >&2; exit 1; }

# Bootstrap script must NOT pass admin password or pass4SymmKey on the SSH
# command line. It also must use REST (/services/cluster/manager/peers) to
# count peers, not `splunk list cluster-peers` text parsing.
if grep -q 'splunk list cluster-peers' "${TMP_OUT_S}/cluster/bootstrap/sequenced-bootstrap.sh"; then
    echo "FAIL: sequenced-bootstrap.sh must not parse 'splunk list cluster-peers' (use REST)" >&2
    exit 1
fi
grep -q '/services/cluster/manager/peers' "${TMP_OUT_S}/cluster/bootstrap/sequenced-bootstrap.sh" \
    || { echo "FAIL: sequenced-bootstrap.sh must use /services/cluster/manager/peers REST endpoint" >&2; exit 1; }
# Secret values should be transferred via files (scp), not interpolated inline in ssh argv.
if grep -E 'ssh.*"\$\{SECRET\}"|ssh.*"\$\{ADMIN_PW\}"' "${TMP_OUT_S}/cluster/bootstrap/sequenced-bootstrap.sh"; then
    echo "FAIL: sequenced-bootstrap.sh must not pass secrets in ssh command line" >&2
    exit 1
fi

ss_dir="${TMP_OUT_S}/cluster"
ss_required=(
    README.md metadata.json validate.sh
    manager/cm01.example.com/server.conf manager/cm02.example.com/server.conf
    peer-idx01.example.com/server.conf peer-idx02.example.com/server.conf peer-idx03.example.com/server.conf
    sh-sh01.example.com/server.conf
    bootstrap/sequenced-bootstrap.sh
    bundle/validate.sh bundle/status.sh bundle/apply.sh bundle/apply-skip-validation.sh bundle/rollback.sh
    restart/rolling-restart.sh restart/searchable-rolling-restart.sh restart/force-searchable.sh
    maintenance/enable.sh maintenance/disable.sh
    peer-ops/offline-fast.sh peer-ops/offline-enforce-counts.sh peer-ops/remove-peer.sh peer-ops/extend-restart-timeout.sh
    migration/single-to-multisite.sh migration/replace-manager.sh migration/decommission-site.sh migration/move-peer-to-site.sh migration/migrate-non-clustered.sh
    redundancy/lb-haproxy.cfg redundancy/dns-record-template.txt redundancy/ha-health-check.sh
    forwarder-outputs/hf01.example.com/outputs.conf forwarder-outputs/hf02.example.com/outputs.conf
    handoffs/license-peers.txt
)
for file in "${ss_required[@]}"; do
    [[ -f "${ss_dir}/${file}" ]] || { echo "FAIL: single-site missing ${file}" >&2; exit 1; }
done

# Multisite render with site-mappings.
bash "${SCRIPT_DIR}/setup.sh" \
    --phase render \
    --output-dir "${TMP_OUT_M}" \
    --cluster-mode multisite \
    --cluster-label prod-ms \
    --cluster-manager-uri https://cm01.example.com:8089 \
    --manager-hosts cm01.example.com \
    --available-sites site1,site2 \
    --site-replication-factor "origin:2,total:3" \
    --site-search-factor "origin:1,total:2" \
    --site-mappings "default_mapping:site1" \
    --peer-hosts "idx01.example.com=site1,idx02.example.com=site2,idx03.example.com=site2" \
    --sh-hosts "sh01.example.com=site1" \
    >/dev/null

ms_dir="${TMP_OUT_M}/cluster"
ms_required=(
    manager/cm01.example.com/server.conf
    peer-idx01.example.com/server.conf peer-idx02.example.com/server.conf
    sh-sh01.example.com/server.conf
)
for file in "${ms_required[@]}"; do
    [[ -f "${ms_dir}/${file}" ]] || { echo "FAIL: multisite missing ${file}" >&2; exit 1; }
done

# Multisite manager config must contain multisite + available_sites + site_mappings.
grep -q 'multisite = true' "${ms_dir}/manager/cm01.example.com/server.conf"
grep -q 'available_sites = site1,site2' "${ms_dir}/manager/cm01.example.com/server.conf"
grep -q 'site_mappings = default_mapping:site1' "${ms_dir}/manager/cm01.example.com/server.conf"
grep -q 'site = site1' "${ms_dir}/peer-idx01.example.com/server.conf"
grep -q 'site = site2' "${ms_dir}/peer-idx02.example.com/server.conf"

# Single-site manager redundancy must include cluster_label and switchover stanza.
grep -q 'cluster_label = prod-ss' "${ss_dir}/manager/cm01.example.com/server.conf"
grep -q 'manager_switchover_mode = auto' "${ss_dir}/manager/cm01.example.com/server.conf"
grep -q '\[clustermanager:cm1\]' "${ss_dir}/manager/cm01.example.com/server.conf"

# Every shell script must be syntactically valid.
while IFS= read -r script; do
    bash -n "${script}" || { echo "FAIL: shell syntax error in ${script}" >&2; exit 1; }
done < <(find "${ss_dir}" "${ms_dir}" -name '*.sh')

# Forwarder outputs.conf must contain indexer_discovery stanza.
grep -q 'indexerDiscovery = idxc_main' "${ss_dir}/forwarder-outputs/hf01.example.com/outputs.conf"

# Hand-off file must list all hosts (manager + peers + SH).
grep -q 'cm01.example.com' "${ss_dir}/handoffs/license-peers.txt"
grep -q 'idx03.example.com' "${ss_dir}/handoffs/license-peers.txt"
grep -q 'sh01.example.com' "${ss_dir}/handoffs/license-peers.txt"

echo "PASS: splunk-indexer-cluster-setup offline smoke OK (single-site + multisite)"
