---
name: splunk-platform-pki-setup
description: "Use when the user asks to build Splunk PKI, mint certs, prepare third-party CA CSRs, replace default
  certs, configure mTLS, fix KV Store cert validation, encrypt replication traffic, configure SAML/LDAPS
  trust, or rotate Splunk TLS certificates. Render, preflight, apply, validate, rotate, and inventory
  private or public PKI for Splunk Enterprise TLS surfaces: Splunk Web, splunkd REST, S2S, HEC, KV Store,
  indexer clusters, SHC, License Manager, Deployment Server, Monitoring Console, Federated Search, heavy
  forwarders, Universal Forwarders, Edge Processor, SAML SP signing, LDAPS trust, and CLI CA trust. Covers
  CSR handoffs, internal CA rendering, FIPS mode, TLS policy presets, KV Store EKU enforcement, default-
  cert refusal, SAN-aware leaf certs, mTLS, replication-port TLS, and delegated rotation runbooks."
compatibility: "Splunk Cloud Platform 10.5.2605: not applicable. This self-managed runtime workflow remains on the public Splunk Enterprise or Universal Forwarder 10.4 baseline."
metadata:
  splunk_cloud_10_5: "self-managed-10.4"
  compatibility_verified: "2026-07-02"
---

# Splunk Platform PKI Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ Preflight │ → │ Render/review │ → │ Apply/handoff │ → │ Validate evidence │
└───────────┘   └───────────────┘   └───────────────┘   └─────────────────┘
```

## When to Activate

- Build Splunk PKI, mint certs, prepare third-party CA CSRs, replace default certs, configure mTLS, fix KV Store
  cert validation, encrypt replication traffic, configure SAML/LDAPS trust, or rotate Splunk TLS certificates.
- Preview and review the splunk platform pki setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-platform-pki-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-platform-pki-setup/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

## Shared add-on completion gate

If this workflow installs or hands off a registry-listed certificate or health
add-on, follow the [shared completion gate](../shared/ta_completion_gate.md).
Package delivery alone is not success; validate applicable collection and
shipped views, or record explicit package evidence that no dashboards ship.

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
- It never renders SSLv3, TLS 1.0, or TLS 1.1. For Splunk 10.4+, the
  default TLS 1.2 floor permits both TLS 1.2 and TLS 1.3 and renders the
  documented `[tls1.3]` policy; `--tls-version-floor tls1.3` enforces
  TLS-1.3-only. Older Splunk versions remain TLS-1.2-only.
- It does not build the FIPS-validated OpenSSL module. The
  operator owns the FIPS module; the skill flips FIPS on by
  setting both `SPLUNK_FIPS=1` (the master enable switch) and
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

- Private mode builds an internal root/intermediate CA and signs
  the role-specific leaf certificates.
- Public mode renders CSRs and operator handoffs for Vault PKI,
  ACME, AD CS, EJBCA, or a commercial CA.
- Rendered outputs become cluster-bundle drop-ins, SHC deployer
  apps, standalone overlays, and UF fleet overlays.
- Cluster bundle apply and rolling restart remain delegated to
  `splunk-indexer-cluster-setup`; SHC app push remains delegated
  to `splunk-agent-management-setup`.

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

Start from [`template.example`](template.example), select `private` or `public`
mode, list the exact roles and FQDNs, and render a reviewable bundle. For
example, a private indexer cluster and SHC with S2S and HEC mTLS:

```bash
bash skills/splunk-platform-pki-setup/scripts/setup.sh \
  --phase render \
  --mode private \
  --target indexer-cluster,shc \
  --cm-fqdn cm01.example.com \
  --peer-hosts idx01.example.com,idx02.example.com,idx03.example.com \
  --shc-deployer-fqdn deployer01.example.com \
  --shc-members sh01.example.com,sh02.example.com,sh03.example.com \
  --enable-mtls s2s,hec \
  --include-intermediate-ca true
```

Public CA, FIPS 140-3, encrypted replication-port, SAML SP, and Edge Processor
variants use the same render phase with the corresponding reviewed template
fields. Follow the component-specific certificate contract and constraints in
[reference.md](reference.md).

Run read-only preflight or inventory before any mutation:

```bash
bash skills/splunk-platform-pki-setup/scripts/setup.sh \
  --phase preflight \
  --mode private \
  --target indexer-cluster,shc \
  --cm-fqdn cm01.example.com \
  --admin-password-file /tmp/splunk_admin_password
```

Apply only a reviewed leaf bundle, with the explicit rotation acceptance and
file-backed credentials:

```bash
bash skills/splunk-platform-pki-setup/scripts/setup.sh \
  --phase apply \
  --mode private \
  --target shc \
  --shc-deployer-fqdn deployer01.example.com \
  --leaf-target shc \
  --leaf-host sh01.example.com \
  --leaf-cert-file /tmp/signed/sh01.pem \
  --leaf-private-key-file /tmp/signed/sh01.key \
  --leaf-ca-bundle-file /tmp/signed/cabundle.pem \
  --accept-pki-rotation \
  --admin-password-file /tmp/splunk_admin_password \
  --leaf-key-password-file /tmp/pki_leaf_key_password
```

Then validate live state:

```bash
bash skills/splunk-platform-pki-setup/scripts/validate.sh \
  --target indexer-cluster,shc \
  --cm-fqdn cm01.example.com \
  --admin-password-file /tmp/splunk_admin_password
```

## What it renders

`splunk-platform-pki-rendered/` contains private-CA helpers when selected,
per-role CSR templates, leaf install and verification helpers, cluster/SHC/
standalone/forwarder configuration overlays, optional Edge Processor and SAML
packets, rotation helpers, operator handoffs, and the preflight, validation,
inventory, metadata, and README artifacts. The private workflow uses Splunk's
own OpenSSL build; KV Store validation requires strict EKU verification.
Review the component and output contract in [reference.md](reference.md) before
distributing any rendered file.

## Certificate-Monitoring Guardrail

SSL Certificate Checker (`3172`, app `ssl_certificate_checker`) stops at 9.4
and must not be installed on Cloud 10.5. Use `expire-watch.sh` plus
`inventory.sh`; see [post-install monitoring](references/post-install-monitoring.md).

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
- `apply` — render then run the local-host
  `pki/install/install-leaf.sh` + `align-cli-trust.sh` +
  `install-fips-launch-conf.sh` if FIPS. Requires
  explicit `--leaf-target`, `--leaf-host`, and `--leaf-ca-bundle-file`
  inputs, plus `--leaf-cert-file` and `--leaf-private-key-file` for every
  target except CA-only `ldaps`, and
  `--accept-pki-rotation` (a single-flag acknowledgement that the
  operator is about to swap serving certs and trigger downstream
  restart).
- `rotate` — render then emit a rotation runbook
  (`pki/rotate/plan-rotation.md`) describing the full delegated
  order. Does NOT exec the rolling restart itself (delegate
  pattern, see "Rotation ownership" below), and exits nonzero so
  rendering the runbook cannot be mistaken for a completed rotation.
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
- `all` — render + one local-host leaf apply + installed-state preflight, then
  stop nonzero at the cluster-aware restart/rotation handoff. Run `validate` only after that
  restart completes. It uses the same explicit leaf inputs and
  `--accept-pki-rotation` gate.

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

The skill emits `pki/rotate/plan-rotation.md`, but does not run cluster
or SHC rolling restarts itself. Follow the canonical
[rotation runbook](references/rotation-runbook.md) for the exact staging,
bundle validation/apply, rolling-restart, SHC push, forwarder rollout,
validation, and rollback commands. That delegation preserves the
[`splunk-indexer-cluster-setup`](../splunk-indexer-cluster-setup/SKILL.md)
ownership model instead of duplicating restart orchestration here.

## Handoffs and TLS Policy

Read the [cross-skill ownership matrix](reference.md#cross-skill-ownership)
before delegating restarts, bundle pushes, token lifecycle, or fleet rollout.
TLS algorithms, protocol floors, FIPS lifecycle, validity caps, key formats,
and mTLS defaults are defined in [reference.md](reference.md#cross-cutting-controls)
and the topic files under [references/](references/authoritative-sources.md).
The renderer consumes the machine-readable
[algorithm policy](references/algorithm-policy.json) and fails closed on
deprecated protocols or incomplete FIPS transitions.

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
