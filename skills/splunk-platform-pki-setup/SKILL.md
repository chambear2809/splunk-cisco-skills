---
name: splunk-platform-pki-setup
description: >-
  Render, preflight, apply, validate, rotate, and inventory Private PKI
  (operator becomes the CA) or Public PKI (CSR + handoff to a third-party
  CA / HashiCorp Vault PKI / ACME / Microsoft AD CS / EJBCA) across every
  Splunk Enterprise TLS surface — Splunk Web (8000), splunkd REST (8089),
  S2S (9997), HEC (8088), KV Store, indexer cluster (including the
  `[replication_port-ssl://9887]` channel), search-head cluster, License
  Manager, Deployment Server, Monitoring Console, Federated Search, DMZ
  heavy forwarder, the universal forwarder fleet, Splunk Edge Processor
  (RSA + ECDSA), the SAML SP signing cert, LDAPS trust, and the local
  `splunk` CLI's `cacert.pem`. Wires FIPS 140-2 / 140-3 mode through
  `splunk-launch.conf`, ships three TLS algorithm presets
  (`splunk-modern`, `fips-140-3`, `stig`), enforces the KV-Store
  `serverAuth`+`clientAuth` EKU pair, refuses default Splunk certs,
  mints leaves with operator-supplied SANs, and emits a delegated
  rotation runbook that hands off rolling restart and cluster bundle
  apply to `splunk-indexer-cluster-setup`. Use when the user asks to
  build a Splunk PKI, mint TLS certs for a Splunk cluster, prepare CSRs
  for a third-party CA, replace default Splunk certs, configure mTLS
  on splunkd / S2S / HEC, encrypt the indexer-cluster replication
  port, fix KV-Store cert validation errors after an upgrade,
  configure SAML SP signing or LDAPS trust, or rotate Splunk TLS
  certificates across an indexer cluster, SHC, License Manager,
  Deployment Server, Monitoring Console, or universal forwarder fleet.
---

# Splunk Platform PKI Setup

This skill owns the **full TLS / PKI lifecycle** for a self-managed
Splunk Enterprise deployment. It runs in either of two modes:

- **Private PKI** — the skill renders scripts that build an internal
  Root CA (and optional Intermediate), then mint per-component
  server / client certificates with the right `basicConstraints`,
  `keyUsage`, and `extendedKeyUsage` (including the dual `serverAuth`
  + `clientAuth` EKU that **KV Store 7.0+ requires**), with per-host
  SANs.
- **Public PKI** — the skill renders per-host CSRs +
  `openssl.cnf` and a handoff Markdown for the operator's
  third-party CA (HashiCorp Vault PKI, ACME / cert-manager / Let's
  Encrypt, Microsoft AD CS, EJBCA, or any commercial CA). It
  installs and validates the returned signed PEMs but never embeds
  CA credentials.

It is **render-first**: the default phase produces a reviewable
directory of CA scripts, CSR templates, install / verify scripts,
per-role distribution payloads (cluster bundle, SHC deployer
bundle, standalone, forwarder fleet, Edge Processor placeholders),
rotation runbooks, and operator handoff Markdown. It refuses to
apply changes until the operator passes `--accept-pki-rotation`.

## Read this first — what this skill does NOT do

- It does not talk to a CA. Public-PKI mode renders CSRs and a
  handoff Markdown; the operator submits to Vault / ACME / AD CS /
  EJBCA / commercial CA out of band.
- It does not implement rolling restart or cluster bundle apply.
  Both are delegated to
  [`skills/splunk-indexer-cluster-setup`](../splunk-indexer-cluster-setup/SKILL.md)
  (matches the repo precedent set by `pass4SymmKey` rotation,
  which is also operator-orchestrated).
- It does not configure Splunk Web HSTS / CSP / browser security
  headers. Splunk Web has no `customHttpHeaders`; those headers
  come from the reverse proxy and are owned by
  [`skills/splunk-enterprise-public-exposure-hardening`](../splunk-enterprise-public-exposure-hardening/SKILL.md).
- It does not force TLS 1.3. Splunk's TLS-protocol-version doc
  lists `tls1.2` as the maximum supported version; the skill
  defaults to and refuses anything below `tls1.2`.
- It does not build the FIPS-validated OpenSSL module. The
  operator owns the FIPS module; the skill flips
  `SPLUNK_FIPS_VERSION` in `splunk-launch.conf`.
- It does not issue certificates for Splunk Cloud. It refuses and
  emits the
  [Universal Forwarder Credentials Package](https://help.splunk.com/?resourceId=Forwarder_Forwarder_ConfigSCUFCredentials)
  handoff. Splunk Cloud's ACS does not currently expose a
  self-service BYOC endpoint for HEC custom-domain certificates;
  operators open a Splunk Support ticket or deploy an
  `inputs.conf`-in-app instead.
- It does not generate Java keystores / truststores (JKS / PKCS#12).
  Splunk DB Connect uses those and is intentionally out of scope.
- It does not own Splunk SOAR PKI, Splunk Mobile / Secure Gateway
  certs, IdP-side configuration, HSM integration for the CA private
  key, or CRL / OCSP responder hosting. Each is referenced where
  relevant but operator-driven.
- It does not certify compliance (PCI / HIPAA / FedRAMP / SOC 2 /
  DISA STIG). It renders STIG-aligned configs (`--tls-policy stig`)
  and cites NIST controls in
  [references/fips-and-common-criteria.md](references/fips-and-common-criteria.md)
  but does not attest.

## Architecture the skill assumes

```
                 Private PKI mode                                       Public PKI mode
                 ----------------                                       ---------------
              Internal Root CA                                Operator's CA: Vault PKI /
              (offline, 3650 d)                               ACME / AD CS / EJBCA /
                     │                                        commercial CA
                     ▼                                                    │
           Internal Intermediate CA                                       │
           (online, 1825 d)                                               │
                     │                                                    │
                     └──────────── signs ───────────┐    ┌── fulfills CSR ┘
                                                   ▼    ▼
                                  splunk-platform-pki-setup renderer
                                          │
                ┌─────────────────────────┼──────────────────────────┐
                ▼                         ▼                          ▼
        Cluster bundle drop-in    SHC deployer drop-in      Standalone / fleet
        master-apps/000_pki_trust shcluster/apps/...        000_pki_trust + UF overlay
                │                         │                          │
                ▼                         ▼                          ▼
        splunk-indexer-cluster-setup   splunk-agent-management       Operator runs install-leaf
        --phase bundle-apply           -setup deployer push          on LM / DS / MC / single SH
        --phase rolling-restart                                      / DMZ HF / UF fleet
                │
                ▼
        Cluster peers + SHs install certs and restart in waves
```

## Agent behavior — credentials

Never paste secrets into chat or pass them on argv. The skill
consumes **file paths** for every secret and never embeds secret
values in rendered output:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_admin_password
bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_idxc_secret
bash skills/shared/scripts/write_secret_file.sh /tmp/pki_root_ca_key_password
bash skills/shared/scripts/write_secret_file.sh /tmp/pki_intermediate_ca_key_password
bash skills/shared/scripts/write_secret_file.sh /tmp/pki_leaf_key_password
bash skills/shared/scripts/write_secret_file.sh /tmp/pki_saml_sp_key_password
```

Pass them in via `--admin-password-file`, `--idxc-secret-file`,
`--ca-key-password-file`, `--intermediate-ca-key-password-file`,
`--leaf-key-password-file`, `--saml-sp-key-password-file`.

The rendered `pki/install/install-leaf.sh` script accepts a
**separate** `--ssl-password-file PATH` flag — this is the
plaintext leaf-key passphrase the operator copies to each
target host. install-leaf.sh writes it verbatim to the
`sslPassword` line of the per-host overlay
(`$SPLUNK_HOME/etc/system/local/server.conf | web.conf | inputs.conf | outputs.conf`)
and on first restart Splunk encrypts it with `splunk.secret`. In
typical deployments `--ssl-password-file` and
`--leaf-key-password-file` reference the same plaintext file
(the leaf key's passphrase, which is what Splunk needs to read
the key). Omit `--ssl-password-file` when the leaf key is
unencrypted (e.g. PKCS#8 nocrypt for Edge Processor).

For non-secret values (FQDNs, SANs, role inventory, validity days,
key algorithm, mTLS surfaces, FIPS mode, TLS preset) use
[`template.example`](template.example).

## Quick start

Render a Private PKI for a 3-peer indexer cluster + 3-member SHC
with default Splunk-modern algorithms, mTLS on S2S + HEC,
hostname validation everywhere, and the splunkd cert distributed
through the cluster bundle:

```bash
bash skills/splunk-platform-pki-setup/scripts/setup.sh \
  --phase render \
  --mode private \
  --target indexer-cluster,shc,license-manager,deployment-server,monitoring-console \
  --cm-fqdn cm01.example.com \
  --peer-hosts idx01.example.com,idx02.example.com,idx03.example.com \
  --shc-deployer-fqdn deployer01.example.com \
  --shc-members sh01.example.com,sh02.example.com,sh03.example.com \
  --lm-fqdn lm01.example.com \
  --ds-fqdn ds01.example.com \
  --mc-fqdn mc01.example.com \
  --enable-mtls s2s,hec \
  --tls-policy splunk-modern \
  --include-intermediate-ca true
```

Render a Public PKI for the same cluster with a HashiCorp Vault PKI
operator handoff and the SAML SP signing cert:

```bash
bash skills/splunk-platform-pki-setup/scripts/setup.sh \
  --phase render \
  --mode public \
  --target indexer-cluster,shc,license-manager,saml-sp \
  --cm-fqdn cm01.example.com \
  --peer-hosts idx01.example.com,idx02.example.com,idx03.example.com \
  --shc-deployer-fqdn deployer01.example.com \
  --shc-members sh01.example.com,sh02.example.com,sh03.example.com \
  --lm-fqdn lm01.example.com \
  --saml-sp true \
  --public-ca-name vault \
  --leaf-days 397
```

Render a FIPS 140-3 Private PKI with the indexer-cluster replication
port encrypted (atomic migration of `[replication_port://9887]` to
`[replication_port-ssl://9887]`):

```bash
bash skills/splunk-platform-pki-setup/scripts/setup.sh \
  --phase render \
  --mode private \
  --target indexer-cluster \
  --cm-fqdn cm01.example.com \
  --peer-hosts idx01.example.com,idx02.example.com,idx03.example.com \
  --fips-mode 140-3 \
  --tls-policy fips-140-3 \
  --encrypt-replication-port true \
  --key-algorithm rsa-2048 \
  --include-intermediate-ca true
```

Render the Edge Processor cert pair (RSA-2048 by default; pass
`--key-algorithm ecdsa-p256` for ECDSA):

```bash
bash skills/splunk-platform-pki-setup/scripts/setup.sh \
  --phase render \
  --mode private \
  --target edge-processor \
  --include-edge-processor true \
  --ep-fqdn ep01.example.com \
  --ep-data-source-fqdn datasource01.example.com \
  --key-format pkcs8
```

Run preflight against a live host (read-only checks; refuses to
apply):

```bash
bash skills/splunk-platform-pki-setup/scripts/setup.sh \
  --phase preflight \
  --mode private \
  --target indexer-cluster,shc \
  --cm-fqdn cm01.example.com \
  --admin-password-file /tmp/splunk_admin_password
```

Inventory live cert posture (read-only; never writes):

```bash
bash skills/splunk-platform-pki-setup/scripts/setup.sh \
  --phase inventory \
  --target all \
  --admin-password-file /tmp/splunk_admin_password
```

Apply rendered certs to a search head (mutates Splunk; requires
the explicit accept flag):

```bash
bash skills/splunk-platform-pki-setup/scripts/setup.sh \
  --phase apply \
  --mode private \
  --target shc \
  --shc-deployer-fqdn deployer01.example.com \
  --accept-pki-rotation \
  --admin-password-file /tmp/splunk_admin_password \
  --leaf-key-password-file /tmp/pki_leaf_key_password
```

Validate live state post-apply:

```bash
bash skills/splunk-platform-pki-setup/scripts/validate.sh \
  --target indexer-cluster,shc \
  --cm-fqdn cm01.example.com \
  --admin-password-file /tmp/splunk_admin_password
```

## What it renders

Under the project root in `splunk-platform-pki-rendered/`:

- `pki/private-ca/` — only when `--mode private`: `create-root-ca.sh`,
  `create-intermediate-ca.sh`, `sign-server-cert.sh`,
  `sign-client-cert.sh`, `sign-saml-sp.sh`, plus `openssl-*.cnf`
  files with the documented `basicConstraints` / `keyUsage` /
  `extendedKeyUsage` extensions, and a `README.md` that walks the
  operator through CA generation. Uses
  `$SPLUNK_HOME/bin/splunk cmd openssl genpkey/req/x509` per
  Splunk's documented workflow so the same OpenSSL build that
  Splunk uses signs and verifies.
- `pki/csr-templates/<role>-<host>.cnf` + `generate-csr.sh` —
  emitted in both modes; per-host CSR config with SANs and EKU.
- `pki/install/install-leaf.sh`, `verify-leaf.sh`,
  `kv-store-eku-check.sh`, `align-cli-trust.sh`,
  `install-fips-launch-conf.sh`, `prepare-key.sh` — cert
  install + verify per host. `kv-store-eku-check.sh` runs the
  documented `splunk cmd openssl verify -x509_strict` check from
  the KV Store custom-cert prep doc and refuses to declare a host
  ready unless the verification returns `OK`.
- `pki/distribute/cluster-bundle/master-apps/000_pki_trust/local/`
  — cluster-bundle drop-in: `server.conf` (with
  `[replication_port-ssl://9887]` if `--encrypt-replication-port=true`),
  `inputs.conf` (`[splunktcp-ssl:9997]` + `[SSL]`).
- `pki/distribute/shc-deployer/shcluster/apps/000_pki_trust/local/`
  — SHC deployer drop-in: `server.conf`, `web.conf`, `inputs.conf`.
- `pki/distribute/standalone/000_pki_trust/local/` — for
  non-clustered roles (LM, DS, MC, single SH, HF):
  `server.conf`, `web.conf`, `inputs.conf`, `outputs.conf`,
  `authentication.conf`, `deploymentclient.conf`,
  `splunk-launch.conf` (when FIPS), `system-files/ldap.conf`
  (when LDAPS).
- `pki/distribute/forwarder-fleet/<group>/{outputs-overlay.conf,server-overlay.conf}`
  — UF / HF outputs overlay with `clientCert` /
  `sslVerifyServerCert=true` / `sslVerifyServerName=true` and
  per-indexer `[tcpout-server://host:port]` SAN overrides.
- `pki/distribute/edge-processor/` — only when
  `--include-edge-processor=true`: 5-file PEM placeholders
  (`ca_cert.pem.example`, `edge_server_cert.pem.example`,
  `edge_server_key.pem.example`,
  `data_source_client_cert.pem.example`,
  `data_source_client_key.pem.example`) + `upload-via-rest.sh.example`
  for the EP REST upload and `README.md` for the EP UI walkthrough.
- `pki/distribute/saml-sp/` — only when `--saml-sp=true`:
  `sp-signing.crt`, `sp-signing.key.placeholder`, `README.md` for
  re-uploading IdP metadata after rotation.
- `pki/rotate/{plan-rotation.md, rotate-leaf-host.sh,
  swap-trust-anchor.sh, swap-replication-port-to-ssl.sh,
  expire-watch.sh}` — rotation helpers with the delegated
  rolling-restart runbook.
- `handoff/` — Markdown checklists for Vault PKI, ACME / cert-manager,
  Microsoft AD CS, EJBCA, Splunk Cloud UFCP / BYOC, FIPS migration,
  Edge Processor upload, post-install monitoring (SSL Cert Checker
  Splunkbase 3172, `/server/health/splunkd` REST endpoint, CIM
  Certificates data model), and the operator checklist.
- `preflight.sh`, `validate.sh`, `inventory.sh`, `README.md`,
  `metadata.json`.

## Phases

- `render` (default) — produce the reviewable rendered tree. No
  Splunk REST calls; safe to run anywhere.
- `preflight` — render then run the live preflight checks: cert
  directory permissions, default-cert refusal,
  KV-Store EKU verification (`splunk cmd openssl verify -x509_strict`
  must return `OK`), `splunk.secret` SHA-256 parity across cluster
  members, FIPS posture (refuses mid-Phase-1 / Phase-2 migration),
  hostname-validation gating, TLS protocol floor check
  (`sslVersions = tls1.2`), per-host
  `splunk btool server list sslConfig` snapshot, replication-port
  mode (cleartext vs SSL), `[shclustering]` `pass4SymmKey`
  presence reminder. Refuses to mark the deployment ready when any
  check fails.
- `apply` — render then run the per-role
  `pki/install/install-leaf.sh` + `align-cli-trust.sh` +
  `install-fips-launch-conf.sh` if FIPS. Requires
  `--accept-pki-rotation` (a single-flag acknowledgement that the
  operator is about to swap serving certs and trigger downstream
  restart).
- `rotate` — render then emit a rotation runbook
  (`pki/rotate/plan-rotation.md`) describing the full delegated
  order. Does NOT exec the rolling restart itself (delegate
  pattern, see "Rotation ownership" below).
- `validate` — render then run the live validation probes:
  REST + `openssl s_client -connect` per surface, KV Store
  handshake check, `splunk show-decrypted` round-trip on
  `sslPassword`, SAML SP signing cert exposed in IdP-metadata
  endpoint.
- `inventory` — read-only: collects
  `splunk btool server list sslConfig`, `web list sslConfig`,
  `inputs list http SSL`, dumps PEM expiry catalogue and emits
  `pki/inventory/<host>.json`. No Splunk write operations. No
  `--accept-…` required.
- `all` — render + preflight + apply + validate, gated by
  `--accept-pki-rotation`.

## Apply guard — `--accept-pki-rotation`

The skill refuses to run `apply` or `all` without
`--accept-pki-rotation`. This is a single-flag acknowledgement
that:

- The new cert chain has been verified (`verify-leaf.sh` returned
  `OK`).
- A rolling restart of the indexer cluster and SHC will follow
  (delegated to `splunk-indexer-cluster-setup --phase rolling-restart`).
- The SAML / LDAPS / Edge Processor / Splunk Cloud handoffs (where
  applicable) will be completed.
- The operator has a rollback plan (the previous PEM directory
  is preserved).

The render and preflight phases never need this flag.

## Rotation ownership — delegate

The skill emits `pki/rotate/plan-rotation.md` describing the order
of operations:

1. Stage the new trust anchor in the cluster bundle and SHC
   deployer apps (already rendered).
2. Run `bash skills/splunk-indexer-cluster-setup/scripts/setup.sh
   --phase bundle-validate` then `--phase bundle-apply`.
3. Run `bash skills/splunk-indexer-cluster-setup/scripts/setup.sh
   --phase rolling-restart --rolling-restart-mode searchable` to
   roll the indexer cluster.
4. Stage new leaf certs on each non-clustered role (LM, DS, MC,
   single SH, HF) and run `splunk restart`.
5. On the SHC deployer, run
   `splunk apply shcluster-bundle -target https://captain01.example.com:8089`
   and let the SHC roll its members.
6. Roll the forwarder fleet via
   `bash skills/splunk-agent-management-setup/scripts/setup.sh`.
7. Run this skill's `validate` phase to confirm.

Every step is a single shell line that the operator runs. No tight
coupling, no duplicated rolling-restart logic. This matches the
repo precedent set by
[`splunk-indexer-cluster-setup`](../splunk-indexer-cluster-setup/SKILL.md)
("Cluster `pass4SymmKey` rotation… does not orchestrate that
rolling rotation").

## Cross-skill handoff matrix

The skill consumes — does not duplicate — these. When you also
use one of the adjacent skills below, run THIS skill's render +
preflight first to establish the cert paths, then layer the
adjacent skill's behaviour on top.

| Adjacent skill | What it owns | What this skill provides |
|---|---|---|
| [splunk-enterprise-public-exposure-hardening](../splunk-enterprise-public-exposure-hardening/SKILL.md) | Splunk Web HSTS / CSP / browser headers via reverse proxy, public-FQDN binding, default-cert refusal, `splunk.secret` rotation, public-exposure preflight | All cert PEMs the hardening skill consumes; this skill consumes the hardening skill's `--enable-fips` / `--fips-version` semantics rather than re-defining |
| [splunk-indexer-cluster-setup](../splunk-indexer-cluster-setup/SKILL.md) | Cluster bundle apply, rolling restart, peer offline, multisite migration | Cluster-bundle drop-in (including `[replication_port-ssl://9887]`); rotation runbook delegates to its `--phase bundle-apply` and `--phase rolling-restart` |
| [splunk-agent-management-setup](../splunk-agent-management-setup/SKILL.md) | SHC deployer push, server classes, deployment apps | SHC deployer drop-in and the forwarder-fleet outputs overlay |
| [splunk-hec-service-setup](../splunk-hec-service-setup/SKILL.md) | HEC token lifecycle, allowed indexes, ACS HEC tokens | HEC TLS cert + optional mTLS |
| [splunk-federated-search-setup](../splunk-federated-search-setup/SKILL.md) | Federation provider / consumer wiring | Per-provider client cert and `--cacert` snippet |
| [splunk-monitoring-console-setup](../splunk-monitoring-console-setup/SKILL.md) | MC distributed config | `trusted.pem` distribution helper |
| [splunk-universal-forwarder-setup](../splunk-universal-forwarder-setup/SKILL.md) | UF runtime install / upgrade | UF outputs overlay; for Splunk Cloud-bound UFs, this skill refuses and points at the UFCP |
| [splunk-license-manager-setup](../splunk-license-manager-setup/SKILL.md) | License manager / peer wiring | LM cert install |
| [splunk-mcp-server-setup](../splunk-mcp-server-setup/SKILL.md) | MCP server install + token issuance | MCP `mcp.conf [server] ssl_verify=true` aligns with the new trust anchor |
| [splunk-edge-processor-setup](../splunk-edge-processor-setup/SKILL.md) | EP control-plane object, instance install, pipelines | EP cert profile (RSA + ECDSA) + REST upload helper when `--include-edge-processor=true` |
| [splunk-enterprise-host-setup](../splunk-enterprise-host-setup/SKILL.md) | Splunk host install / cluster bootstrap | Unblocks the v1 "TLS certificate generation — out of scope" gap noted in its [reference.md](../splunk-enterprise-host-setup/reference.md) lines 49–55 |
| [splunk-cloud-acs-allowlist-setup](../splunk-cloud-acs-allowlist-setup/SKILL.md) | Splunk Cloud ACS IP allowlists | Out of scope — this skill is on-prem only; the Splunk Cloud HEC custom-domain BYOC handoff lives in `handoff/splunk-cloud-byoc.md` |

## TLS algorithm presets

Pick with `--tls-policy {splunk-modern|fips-140-3|stig}`:

- `splunk-modern` (default) — Splunk's documented modern cipher
  set (`ECDHE-(EC)DSA/RSA-AES{128,256}-GCM-SHA{256,384}` family
  with `ECDHE-AES{128,256}-SHA{256,384}` fallbacks); ECDH curves
  `prime256v1, secp384r1, secp521r1`. Source:
  [About TLS encryption and cipher suites](https://docs.splunk.com/Documentation/Splunk/latest/Security/AboutTLSencryptionandciphersuites).
- `fips-140-3` — NIST-approved AEAD suites only (no CBC, no
  SHA-1, no RSA-1024, no anonymous DH); RSA-2048+ or ECDSA P-256+;
  SHA-256 / 384 / 512 only.
- `stig` — DISA STIG-aligned (cross-references
  `splunk-enterprise-public-exposure-hardening/references/disa-stig-cross-reference.md`).

## TLS protocol floor

Defaults to `sslVersions = tls1.2` and `sslVersionsForClient = tls1.2`.
Splunk's
[TLS-protocol-version doc](https://help.splunk.com/splunk-enterprise/administer/manage-users-and-security/10.2/secure-splunk-platform-communications-with-transport-layer-security-certificates/configure-tls-protocol-version-support-for-secure-connections-between-splunk-platform-instances)
lists the supported set as `SSLv3` (deprecated), `TLS1.0` (deprecated,
9.4+), `TLS1.1` (deprecated, 9.4+), `TLS1.2`. **TLS 1.3 is not yet
documented as a Splunk-supported TLS version.** Pass
`--allow-deprecated-tls` to relax the floor (not recommended).

## FIPS mode

`--fips-mode {none|140-2|140-3}` — when set, the renderer emits a
`splunk-launch.conf` overlay with `SPLUNK_FIPS_VERSION = 140-3` (or
`140-2`). Splunk 10.0+ ships both modules. The skill consumes the
public-exposure-hardening skill's `--enable-fips` /
`--fips-version` semantics when both run together. NIST deprecates
FIPS 140-2 on 2026-09-21, so default for new deployments is
`140-3`. The skill refuses to apply mid-migration (Phase 1 not yet
complete) per the
[Splunk FIPS upgrade doc](https://help.splunk.com/en/splunk-enterprise/administer/install-and-upgrade/10.2/upgrade-or-migrate-splunk-enterprise/upgrade-and-migrate-your-fips-mode-deployments).

## Validity-day defaults

| Identity type | Default | Cap |
|---|---|---|
| Internal Root CA | 3650 d (10 y) | unlimited |
| Internal Intermediate CA | 1825 d (5 y) | unlimited |
| Server / client leaf (private mode) | 825 d | 825 d (preflight refuses higher) |
| Server / client leaf (public mode) | 397 d | warns at 90 d (Let's Encrypt floor) and 397 d (CA/Browser Forum baseline); operator's CA enforces its own cap |

Override with `--root-ca-days`, `--intermediate-ca-days`,
`--leaf-days`.

## Key format / permissions

- Default private key format is **encrypted PKCS#1 PEM** (matches
  Splunk's `splunk cmd openssl genpkey -aes-256-cbc` example).
- `--key-format pkcs8` switches to PKCS#8 (`BEGIN PRIVATE KEY`),
  required for Edge Processor and Splunk DB Connect compatibility.
- After install, the renderer runs `chmod 0600 <key>` and
  `chmod 0644 <cert>` explicitly so Splunk's restart-time
  permission flap starts from a known baseline.
- `verify-leaf.sh` runs `splunk show-decrypted` to confirm the
  encrypted `sslPassword` (Splunk encrypts on restart with
  `splunk.secret`) round-trips back to the plaintext the operator
  supplied via `--leaf-key-password-file`.

## mTLS surfaces

Opt-in via `--enable-mtls {none|s2s|hec|splunkd|all}`. Default is
`s2s,hec`. When `all`, sets `requireClientCert=true` on splunkd
(8089), S2S (9997), and HEC (8088) per the
[Splunk 10.0 mTLS doc](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/10.2/secure-splunk-platform-communications-with-transport-layer-security-certificates/configure-mutually-authenticated-transport-layer-security-mtls-on-the-splunk-platform).
Default leaves splunkd off because turning it on can break
operator tooling that does not present a client cert.

## References

Read [reference.md](reference.md) before any apply. Topical deep
dives (each anchored to a specific upstream Splunk doc captured in
[references/authoritative-sources.md](references/authoritative-sources.md)):

- [references/component-cert-matrix.md](references/component-cert-matrix.md)
- [references/private-pki-workflow.md](references/private-pki-workflow.md)
- [references/public-pki-workflow.md](references/public-pki-workflow.md)
- [references/handoff-vault-pki.md](references/handoff-vault-pki.md)
- [references/handoff-acme-cert-manager.md](references/handoff-acme-cert-manager.md)
- [references/handoff-microsoft-adcs.md](references/handoff-microsoft-adcs.md)
- [references/handoff-ejbca.md](references/handoff-ejbca.md)
- [references/kv-store-eku-requirements.md](references/kv-store-eku-requirements.md)
- [references/mtls-and-hostname-validation.md](references/mtls-and-hostname-validation.md)
- [references/replication-port-tls.md](references/replication-port-tls.md)
- [references/saml-signing-certs.md](references/saml-signing-certs.md)
- [references/ldaps-trust.md](references/ldaps-trust.md)
- [references/edge-processor-pki.md](references/edge-processor-pki.md)
- [references/cli-trust-cacert-alignment.md](references/cli-trust-cacert-alignment.md)
- [references/tls-protocol-policy.md](references/tls-protocol-policy.md)
- [references/algorithm-presets.md](references/algorithm-presets.md)
  + [algorithm-policy.json](references/algorithm-policy.json) (machine-readable companion consumed by renderer + preflight)
- [references/fips-and-common-criteria.md](references/fips-and-common-criteria.md)
- [references/key-format-and-permissions.md](references/key-format-and-permissions.md)
- [references/rotation-runbook.md](references/rotation-runbook.md)
- [references/post-install-monitoring.md](references/post-install-monitoring.md)
- [references/splunk-cloud-ufcp-handoff.md](references/splunk-cloud-ufcp-handoff.md)
- [references/troubleshooting.md](references/troubleshooting.md)
- [references/authoritative-sources.md](references/authoritative-sources.md)
