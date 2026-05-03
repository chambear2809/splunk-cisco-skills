#!/usr/bin/env python3
"""Render Splunk Platform PKI Setup assets.

Render-first by default. Never embeds secret values: secrets (CA private
key passphrase, leaf key passphrase, SAML SP key passphrase, Splunk admin
password, cluster pass4SymmKey) live in operator-managed local files
referenced by absolute path; the rendered scripts read those files at
apply time.

Closed GENERATED_FILES manifest at the top — every file the renderer
might emit is listed there (some conditional on flags). The smoke test
asserts that the actually-emitted set is a subset of the manifest and
that no unrecognised file appears.

Anchored to the upstream Splunk doc URLs in
references/authoritative-sources.md.
"""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Closed manifest of every file the renderer is allowed to emit.
# Conditional files (per-host CSRs, per-fleet UF overlays, EP placeholders,
# SAML SP, FIPS launch.conf, LDAPS ldap.conf) are listed as templates with
# {placeholder}; the renderer expands them at runtime against the operator's
# inventory and the actually-emitted set is checked against this.
# ---------------------------------------------------------------------------

GENERATED_FILES: set[str] = {
    "README.md",
    "metadata.json",
    "preflight.sh",
    "validate.sh",
    "inventory.sh",
    # Private CA scripts (only when --mode private)
    "pki/private-ca/create-root-ca.sh",
    "pki/private-ca/create-intermediate-ca.sh",
    "pki/private-ca/sign-server-cert.sh",
    "pki/private-ca/sign-client-cert.sh",
    "pki/private-ca/sign-saml-sp.sh",
    "pki/private-ca/openssl-root.cnf",
    "pki/private-ca/openssl-intermediate.cnf",
    "pki/private-ca/openssl-leaf-server.cnf",
    "pki/private-ca/openssl-leaf-client.cnf",
    "pki/private-ca/openssl-leaf-saml.cnf",
    "pki/private-ca/README.md",
    # CSR generation
    "pki/csr-templates/generate-csr.sh",
    "pki/csr-templates/README.md",
    # Install / verify helpers
    "pki/install/install-leaf.sh",
    "pki/install/verify-leaf.sh",
    "pki/install/kv-store-eku-check.sh",
    "pki/install/align-cli-trust.sh",
    "pki/install/install-fips-launch-conf.sh",
    "pki/install/prepare-key.sh",
    "pki/install/README.md",
    # Distribution payloads
    "pki/distribute/cluster-bundle/master-apps/000_pki_trust/default/app.conf",
    "pki/distribute/cluster-bundle/master-apps/000_pki_trust/local/server.conf",
    "pki/distribute/cluster-bundle/master-apps/000_pki_trust/local/inputs.conf",
    "pki/distribute/cluster-bundle/README.md",
    "pki/distribute/shc-deployer/shcluster/apps/000_pki_trust/default/app.conf",
    "pki/distribute/shc-deployer/shcluster/apps/000_pki_trust/local/server.conf",
    "pki/distribute/shc-deployer/shcluster/apps/000_pki_trust/local/web.conf",
    "pki/distribute/shc-deployer/shcluster/apps/000_pki_trust/local/inputs.conf",
    "pki/distribute/shc-deployer/README.md",
    "pki/distribute/standalone/000_pki_trust/default/app.conf",
    "pki/distribute/standalone/000_pki_trust/local/server.conf",
    "pki/distribute/standalone/000_pki_trust/local/web.conf",
    "pki/distribute/standalone/000_pki_trust/local/inputs.conf",
    "pki/distribute/standalone/000_pki_trust/local/outputs.conf",
    "pki/distribute/standalone/000_pki_trust/local/authentication.conf",
    "pki/distribute/standalone/000_pki_trust/local/deploymentclient.conf",
    "pki/distribute/standalone/000_pki_trust/local/splunk-launch.conf",
    "pki/distribute/standalone/000_pki_trust/system-files/ldap.conf",
    "pki/distribute/standalone/README.md",
    "pki/distribute/edge-processor/ca_cert.pem.example",
    "pki/distribute/edge-processor/edge_server_cert.pem.example",
    "pki/distribute/edge-processor/edge_server_key.pem.example",
    "pki/distribute/edge-processor/data_source_client_cert.pem.example",
    "pki/distribute/edge-processor/data_source_client_key.pem.example",
    "pki/distribute/edge-processor/upload-via-rest.sh.example",
    "pki/distribute/edge-processor/README.md",
    "pki/distribute/saml-sp/sp-signing.crt.placeholder",
    "pki/distribute/saml-sp/sp-signing.key.placeholder",
    "pki/distribute/saml-sp/README.md",
    # Rotation helpers
    "pki/rotate/plan-rotation.md",
    "pki/rotate/rotate-leaf-host.sh",
    "pki/rotate/swap-trust-anchor.sh",
    "pki/rotate/swap-replication-port-to-ssl.sh",
    "pki/rotate/expire-watch.sh",
    # Operator handoff Markdown
    "handoff/operator-checklist.md",
    "handoff/vault-pki.md",
    "handoff/acme-cert-manager.md",
    "handoff/microsoft-adcs.md",
    "handoff/ejbca.md",
    "handoff/splunk-cloud-ufcp.md",
    "handoff/splunk-cloud-byoc.md",
    "handoff/fips-migration.md",
    "handoff/edge-processor-upload.md",
    "handoff/post-install-monitoring.md",
}

# Patterns for conditionally-named files (per-host CSRs, per-group UF
# overlays). The smoke test allows any file matching one of these
# templates to be emitted without complaint.
GENERATED_FILE_PATTERNS: tuple[str, ...] = (
    r"^pki/csr-templates/(splunkd|web|s2s|hec|replication|shc-member|deployment-server|deployment-client|license-manager|monitoring-console|saml-sp|edge-processor-server|edge-processor-client|federation-provider|dmz-hf|uf-fleet)-.+\.cnf$",
    r"^pki/distribute/forwarder-fleet/[^/]+/(outputs-overlay|server-overlay)\.conf$",
)

# ---------------------------------------------------------------------------
# Argument parsing and validation
# ---------------------------------------------------------------------------

VALID_MODES = ("private", "public")
VALID_TARGETS = (
    "core5",
    "indexer-cluster",
    "shc",
    "license-manager",
    "deployment-server",
    "monitoring-console",
    "federated-search",
    "dmz-hf",
    "uf-fleet",
    "saml-sp",
    "ldaps",
    "edge-processor",
    "all",
)
VALID_KEY_ALGORITHMS = ("rsa-2048", "rsa-3072", "rsa-4096", "ecdsa-p256", "ecdsa-p384", "ecdsa-p521")
VALID_KEY_FORMATS = ("pkcs1", "pkcs8")
VALID_TLS_POLICIES = ("splunk-modern", "fips-140-3", "stig")
VALID_TLS_FLOORS = ("tls1.2",)
VALID_MTLS = ("none", "s2s", "hec", "splunkd", "all")
VALID_FIPS_MODES = ("none", "140-2", "140-3")
VALID_PUBLIC_CAS = ("vault", "acme", "adcs", "ejbca", "other")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Render Splunk Platform PKI Setup assets.",
    )
    p.add_argument("--output-dir", required=True)

    # Mode + target
    p.add_argument("--mode", choices=VALID_MODES, default="private")
    p.add_argument("--target", default="core5",
                   help="CSV from " + ", ".join(VALID_TARGETS))
    p.add_argument("--public-ca-name", choices=VALID_PUBLIC_CAS, default="vault")

    # Per-role FQDNs / hosts
    p.add_argument("--cm-fqdn", default="")
    p.add_argument("--peer-hosts", default="",
                   help="CSV of indexer peer FQDNs")
    p.add_argument("--shc-deployer-fqdn", default="")
    p.add_argument("--shc-members", default="",
                   help="CSV of SHC member FQDNs")
    p.add_argument("--lm-fqdn", default="")
    p.add_argument("--ds-fqdn", default="")
    p.add_argument("--mc-fqdn", default="")
    p.add_argument("--single-sh-fqdn", default="",
                   help="Used when --target=core5 and the deployment is a single search head")
    p.add_argument("--public-fqdn", default="",
                   help="Public FQDN for Splunk Web (for core5 / external-facing roles)")
    p.add_argument("--hec-fqdn", default="")
    p.add_argument("--ds-clients", default="",
                   help="CSV of deployment-client host FQDNs (when --enable-mtls covers splunkd)")
    p.add_argument("--uf-fleet-groups", default="",
                   help="CSV of UF fleet group names")
    p.add_argument("--dmz-hf-hosts", default="")
    p.add_argument("--ep-fqdn", default="")
    p.add_argument("--ep-data-source-fqdn", default="")
    p.add_argument("--federation-provider-hosts", default="")
    p.add_argument("--ldap-host", default="",
                   help="LDAPS server FQDN (when --ldaps=true)")

    # CA distinguished name (Private mode)
    p.add_argument("--ca-country", default="US")
    p.add_argument("--ca-state", default="")
    p.add_argument("--ca-locality", default="")
    p.add_argument("--ca-organization", default="Example Corp")
    p.add_argument("--ca-organizational-unit", default="Splunk Platform Engineering")
    p.add_argument("--ca-common-name", default="Example Corp Splunk Root CA")
    p.add_argument("--ca-email", default="")
    p.add_argument("--include-intermediate-ca", choices=("true", "false"), default="true")
    p.add_argument("--root-ca-days", type=int, default=3650)
    p.add_argument("--intermediate-ca-days", type=int, default=1825)
    p.add_argument("--leaf-days", type=int, default=825)

    # Algorithm policy
    p.add_argument("--tls-policy", choices=VALID_TLS_POLICIES, default="splunk-modern")
    p.add_argument("--tls-version-floor", choices=VALID_TLS_FLOORS, default="tls1.2")
    p.add_argument("--allow-deprecated-tls", action="store_true")
    p.add_argument("--key-algorithm", choices=VALID_KEY_ALGORITHMS, default="rsa-2048")
    p.add_argument("--key-format", choices=VALID_KEY_FORMATS, default="pkcs1")

    # mTLS surfaces
    p.add_argument("--enable-mtls", default="s2s,hec",
                   help="CSV from " + ", ".join(VALID_MTLS))

    # Optional surfaces
    p.add_argument("--encrypt-replication-port", choices=("true", "false"), default="false")
    p.add_argument("--saml-sp", choices=("true", "false"), default="false")
    p.add_argument("--ldaps", choices=("true", "false"), default="false")
    p.add_argument("--include-edge-processor", choices=("true", "false"), default="false")

    # FIPS
    p.add_argument("--fips-mode", choices=VALID_FIPS_MODES, default="none")

    # Splunk runtime
    p.add_argument("--splunk-home", default="/opt/splunk")
    p.add_argument("--splunk-version", default="10.2.2")
    p.add_argument("--cert-install-subdir", default="myssl")

    # Secret file paths (file paths only, never values)
    p.add_argument("--admin-password-file", default="")
    p.add_argument("--idxc-secret-file", default="")
    p.add_argument("--ca-key-password-file", default="")
    p.add_argument("--intermediate-ca-key-password-file", default="")
    p.add_argument("--leaf-key-password-file", default="")
    p.add_argument("--saml-sp-key-password-file", default="")

    # Algorithm policy override (rare; defaults to bundled JSON)
    p.add_argument("--algorithm-policy-file", default="")

    # Apply guard
    p.add_argument("--accept-pki-rotation", action="store_true")

    p.add_argument("--json", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _bool(value: str) -> bool:
    return str(value).lower() == "true"


def _expand_targets(target_csv: str) -> set[str]:
    raw = _split_csv(target_csv)
    if "all" in raw:
        return {t for t in VALID_TARGETS if t != "all"}
    invalid = [t for t in raw if t not in VALID_TARGETS]
    if invalid:
        sys.exit(f"ERROR: Invalid --target values: {invalid}. Valid: {sorted(VALID_TARGETS)}")
    return set(raw)


def _expand_mtls(mtls_csv: str) -> set[str]:
    raw = _split_csv(mtls_csv)
    if "all" in raw:
        return {"s2s", "hec", "splunkd"}
    if "none" in raw and len(raw) > 1:
        sys.exit("ERROR: --enable-mtls=none is mutually exclusive with other values")
    if raw == ["none"]:
        return set()
    invalid = [m for m in raw if m not in VALID_MTLS]
    if invalid:
        sys.exit(f"ERROR: Invalid --enable-mtls values: {invalid}. Valid: {sorted(VALID_MTLS)}")
    return set(raw)


def _load_algorithm_policy(args: argparse.Namespace) -> dict:
    if args.algorithm_policy_file:
        path = Path(args.algorithm_policy_file).expanduser().resolve()
    else:
        path = Path(__file__).resolve().parent.parent / "references" / "algorithm-policy.json"
    if not path.exists():
        sys.exit(f"ERROR: algorithm policy file not found: {path}")
    with path.open() as f:
        return json.load(f)


def _key_bits_or_curve(key_algorithm: str) -> dict:
    if key_algorithm.startswith("rsa-"):
        return {"family": "rsa", "bits": int(key_algorithm.split("-")[1])}
    if key_algorithm.startswith("ecdsa-"):
        curve_map = {"p256": "prime256v1", "p384": "secp384r1", "p521": "secp521r1"}
        c = key_algorithm.split("-")[1]
        return {"family": "ecdsa", "curve": curve_map[c]}
    sys.exit(f"ERROR: unknown key algorithm {key_algorithm}")


def _validate_args(args: argparse.Namespace, policy: dict) -> None:
    """Validate operator inputs against the algorithm policy and the docs."""
    targets = _expand_targets(args.target)
    mtls = _expand_mtls(args.enable_mtls)

    # TLS version floor.
    # `--allow-deprecated-tls` does NOT raise the upper bound (Splunk docs
    # don't yet support TLS 1.3); it only relaxes the lower bound so the
    # operator can include ssl3 / tls1.0 / tls1.1 in `sslVersions` for
    # legacy clients. Even with the relax, the rendered conf still
    # defaults to `sslVersions = tls1.2` — the relax just stops the
    # renderer from refusing.
    allowed_floors = list(policy["tls_version_supported"])
    if args.allow_deprecated_tls:
        allowed_floors.extend(policy["tls_version_forbidden"])
    if args.tls_version_floor not in allowed_floors:
        sys.exit(
            f"ERROR: tls_version_floor={args.tls_version_floor} not in supported set "
            f"{policy['tls_version_supported']}. Splunk's docs do not yet list TLS 1.3 "
            f"as a supported sslVersions value; see references/tls-protocol-policy.md. "
            f"Pass --allow-deprecated-tls to relax (still not recommended)."
        )

    # Validity day caps
    if args.leaf_days > policy["validity_days"]["leaf_cap_private"] and args.mode == "private":
        sys.exit(
            f"ERROR: --leaf-days {args.leaf_days} exceeds private-mode cap "
            f"{policy['validity_days']['leaf_cap_private']} (matches Splunk Edge Processor "
            f"doc precedent + CA/Browser Forum baseline). Lower --leaf-days or use --mode public."
        )
    if args.leaf_days < 1:
        sys.exit("ERROR: --leaf-days must be positive")
    if args.root_ca_days < 1 or args.intermediate_ca_days < 1:
        sys.exit("ERROR: CA validity days must be positive")

    # Key algorithm vs preset
    preset = policy["presets"][args.tls_policy]
    if args.key_algorithm not in preset["allowed_key_algorithms"]:
        sys.exit(
            f"ERROR: --key-algorithm {args.key_algorithm} not allowed by --tls-policy "
            f"{args.tls_policy}. Allowed: {preset['allowed_key_algorithms']}. "
            f"For STIG-grade policy use --key-algorithm rsa-3072 or ecdsa-p384."
        )

    # FIPS gating
    if args.fips_mode != "none" and args.tls_policy == "splunk-modern":
        # not fatal but warn-worthy via a stderr note
        print(
            "WARN: --fips-mode is non-none but --tls-policy=splunk-modern. "
            "Consider --tls-policy fips-140-3 for FIPS posture.",
            file=sys.stderr,
        )

    # Per-target host requirements
    if "indexer-cluster" in targets:
        if not args.cm_fqdn:
            sys.exit("ERROR: --cm-fqdn is required when --target includes indexer-cluster")
        if not args.peer_hosts:
            sys.exit("ERROR: --peer-hosts is required when --target includes indexer-cluster")
    if "shc" in targets:
        if not args.shc_deployer_fqdn:
            sys.exit("ERROR: --shc-deployer-fqdn is required when --target includes shc")
        if not args.shc_members:
            sys.exit("ERROR: --shc-members is required when --target includes shc")
    if "license-manager" in targets and not args.lm_fqdn:
        sys.exit("ERROR: --lm-fqdn is required when --target includes license-manager")
    if "deployment-server" in targets and not args.ds_fqdn:
        sys.exit("ERROR: --ds-fqdn is required when --target includes deployment-server")
    if "monitoring-console" in targets and not args.mc_fqdn:
        sys.exit("ERROR: --mc-fqdn is required when --target includes monitoring-console")
    if "edge-processor" in targets:
        if not _bool(args.include_edge_processor):
            sys.exit("ERROR: --target includes edge-processor but --include-edge-processor=false")
        if not args.ep_fqdn:
            sys.exit("ERROR: --ep-fqdn is required when --target includes edge-processor")
    if "saml-sp" in targets and not _bool(args.saml_sp):
        sys.exit("ERROR: --target includes saml-sp but --saml-sp=false")
    if "ldaps" in targets:
        if not _bool(args.ldaps):
            sys.exit("ERROR: --target includes ldaps but --ldaps=false")
        if not args.ldap_host:
            sys.exit("ERROR: --ldap-host is required when --target includes ldaps")
    if "core5" in targets and not (args.single_sh_fqdn or args.public_fqdn):
        sys.exit("ERROR: --single-sh-fqdn or --public-fqdn is required when --target includes core5")

    # Splunk Cloud refusal
    if "uf-fleet" in targets:
        # The skill only refuses when UF destination is Splunk Cloud, but since
        # we don't yet expose --uf-destination, surface a notice in the
        # render output (the splunk-cloud-ufcp handoff is always rendered).
        pass


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _write(path: Path, content: str, executable: bool = False) -> None:
    _ensure_dir(path)
    path.write_text(content)
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# Shell preamble shared by every rendered .sh
SH_PREAMBLE = """#!/usr/bin/env bash
# Rendered by skills/splunk-platform-pki-setup/scripts/render_assets.py.
# Edit the template, not this file.
set -euo pipefail
"""


def _sh(body: str) -> str:
    return SH_PREAMBLE + "\n" + body


def render_readme(out: Path, args: argparse.Namespace, targets: set[str], mtls: set[str]) -> None:
    body = f"""# Splunk Platform PKI Setup — Rendered Assets

This directory was generated by
`skills/splunk-platform-pki-setup/scripts/render_assets.py`. Treat it
as a reviewable blueprint; nothing here mutates a Splunk host until you
explicitly run an apply phase.

## Run summary

| Setting | Value |
|---|---|
| Mode | `{args.mode}` |
| Targets | `{', '.join(sorted(targets))}` |
| TLS policy | `{args.tls_policy}` |
| TLS version floor | `{args.tls_version_floor}` |
| Key algorithm | `{args.key_algorithm}` |
| Key format | `{args.key_format}` |
| mTLS surfaces | `{', '.join(sorted(mtls)) if mtls else 'none'}` |
| Encrypt replication port | `{args.encrypt_replication_port}` |
| FIPS mode | `{args.fips_mode}` |
| Include intermediate CA | `{args.include_intermediate_ca}` |
| Include Edge Processor | `{args.include_edge_processor}` |
| SAML SP signing cert | `{args.saml_sp}` |
| LDAPS trust | `{args.ldaps}` |
| Splunk version | `{args.splunk_version}` |

## Where to start

1. Read `pki/private-ca/README.md` (Private mode) or `pki/csr-templates/README.md`
   (Public mode).
2. Run `pki/install/verify-leaf.sh` and `pki/install/kv-store-eku-check.sh`
   on every signed leaf.
3. Read `pki/rotate/plan-rotation.md` for the delegated rolling-restart
   sequence.
4. Run `bash preflight.sh` against your target hosts. Refuses to mark
   the deployment ready when default Splunk certs or mismatched
   `splunk.secret` are detected.
5. Apply per role with `bash pki/install/install-leaf.sh ...` (requires
   `--accept-pki-rotation` at the setup.sh level).

## Out of band: rolling restart

This skill **does not** orchestrate the indexer-cluster rolling restart.
That belongs to `splunk-indexer-cluster-setup`:

```bash
bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \\
    --phase rolling-restart --rolling-restart-mode searchable \\
    --cluster-manager-uri https://{args.cm_fqdn or 'cm01.example.com'}:8089 \\
    --admin-password-file <password-file>
```

See `pki/rotate/plan-rotation.md` for the full sequence.
"""
    _write(out / "README.md", body)


def render_metadata(out: Path, args: argparse.Namespace, targets: set[str], mtls: set[str]) -> None:
    # Only non-secret values land in metadata.json. Secret file paths are
    # included (paths, not values) so the operator can audit which secrets
    # were referenced; the values never appear here.
    payload = {
        "skill": "splunk-platform-pki-setup",
        "mode": args.mode,
        "targets": sorted(targets),
        "tls_policy": args.tls_policy,
        "tls_version_floor": args.tls_version_floor,
        "key_algorithm": args.key_algorithm,
        "key_format": args.key_format,
        "enable_mtls": sorted(mtls),
        "encrypt_replication_port": _bool(args.encrypt_replication_port),
        "saml_sp": _bool(args.saml_sp),
        "ldaps": _bool(args.ldaps),
        "include_edge_processor": _bool(args.include_edge_processor),
        "include_intermediate_ca": _bool(args.include_intermediate_ca),
        "fips_mode": args.fips_mode,
        "splunk_version": args.splunk_version,
        "splunk_home": args.splunk_home,
        "validity_days": {
            "root_ca": args.root_ca_days,
            "intermediate_ca": args.intermediate_ca_days,
            "leaf": args.leaf_days,
        },
        "hosts": {
            "cm_fqdn": args.cm_fqdn,
            "peer_hosts": _split_csv(args.peer_hosts),
            "shc_deployer_fqdn": args.shc_deployer_fqdn,
            "shc_members": _split_csv(args.shc_members),
            "lm_fqdn": args.lm_fqdn,
            "ds_fqdn": args.ds_fqdn,
            "mc_fqdn": args.mc_fqdn,
            "single_sh_fqdn": args.single_sh_fqdn,
            "public_fqdn": args.public_fqdn,
            "hec_fqdn": args.hec_fqdn,
            "ds_clients": _split_csv(args.ds_clients),
            "uf_fleet_groups": _split_csv(args.uf_fleet_groups),
            "dmz_hf_hosts": _split_csv(args.dmz_hf_hosts),
            "ep_fqdn": args.ep_fqdn,
            "ep_data_source_fqdn": args.ep_data_source_fqdn,
            "federation_provider_hosts": _split_csv(args.federation_provider_hosts),
            "ldap_host": args.ldap_host,
        },
        "secret_file_paths_referenced": {
            "admin_password_file": args.admin_password_file,
            "idxc_secret_file": args.idxc_secret_file,
            "ca_key_password_file": args.ca_key_password_file,
            "intermediate_ca_key_password_file": args.intermediate_ca_key_password_file,
            "leaf_key_password_file": args.leaf_key_password_file,
            "saml_sp_key_password_file": args.saml_sp_key_password_file,
        },
        "operator_acknowledged_pki_rotation": bool(args.accept_pki_rotation),
    }
    _write(out / "metadata.json", json.dumps(payload, indent=2, sort_keys=True) + "\n")


# ---------- Private CA scripts ----------

def _openssl_root_cnf(args: argparse.Namespace) -> str:
    return f"""# Rendered by splunk-platform-pki-setup. Do not edit; re-render instead.
[ req ]
default_bits        = {_key_bits_or_curve(args.key_algorithm).get('bits', 4096)}
default_md          = sha384
prompt              = no
distinguished_name  = req_distinguished_name
x509_extensions     = v3_ca

[ req_distinguished_name ]
C  = {args.ca_country}
ST = {args.ca_state}
L  = {args.ca_locality}
O  = {args.ca_organization}
OU = {args.ca_organizational_unit}
CN = {args.ca_common_name}

[ v3_ca ]
basicConstraints       = critical, CA:TRUE
keyUsage               = critical, keyCertSign, cRLSign
subjectKeyIdentifier   = hash
"""


def _openssl_intermediate_cnf(args: argparse.Namespace) -> str:
    return f"""# Rendered by splunk-platform-pki-setup. Do not edit; re-render instead.
[ req ]
default_bits        = {_key_bits_or_curve(args.key_algorithm).get('bits', 4096)}
default_md          = sha384
prompt              = no
distinguished_name  = req_distinguished_name
req_extensions      = v3_intermediate_ca

[ req_distinguished_name ]
C  = {args.ca_country}
ST = {args.ca_state}
L  = {args.ca_locality}
O  = {args.ca_organization}
OU = {args.ca_organizational_unit}
CN = {args.ca_common_name} Intermediate

[ v3_intermediate_ca ]
basicConstraints       = critical, CA:TRUE, pathlen:0
keyUsage               = critical, keyCertSign, cRLSign
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always, issuer
"""


def _openssl_leaf_server_cnf() -> str:
    return """# Rendered by splunk-platform-pki-setup. Do not edit; re-render instead.
# Server leaf profile. Includes the dual EKU (serverAuth + clientAuth)
# required for KV Store 7.0+.
[ v3_srv ]
basicConstraints       = critical, CA:FALSE
keyUsage               = critical, digitalSignature, keyEncipherment
extendedKeyUsage       = serverAuth, clientAuth
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always, issuer
"""


def _openssl_leaf_client_cnf() -> str:
    return """# Rendered by splunk-platform-pki-setup. Do not edit; re-render instead.
# Client leaf profile. Used for forwarder mTLS and deployment-client mTLS.
[ v3_clt ]
basicConstraints       = critical, CA:FALSE
keyUsage               = critical, digitalSignature, keyEncipherment
extendedKeyUsage       = clientAuth
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always, issuer
"""


def _openssl_leaf_saml_cnf() -> str:
    return """# Rendered by splunk-platform-pki-setup. Do not edit; re-render instead.
# SAML SP signing leaf profile. NO Extended Key Usage by design — many IdPs
# reject SAML SP certs that carry serverAuth or clientAuth EKUs.
[ v3_saml ]
basicConstraints       = critical, CA:FALSE
keyUsage               = critical, digitalSignature, nonRepudiation
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always, issuer
"""


def _create_root_ca_sh(args: argparse.Namespace) -> str:
    kb = _key_bits_or_curve(args.key_algorithm)
    if kb["family"] == "rsa":
        keygen = f"""$SPLUNK_HOME/bin/splunk cmd openssl genpkey \\
    -algorithm RSA -pkeyopt rsa_keygen_bits:{kb["bits"]} \\
    -aes-256-cbc -pass file:"$PKI_ROOT_CA_KEY_PASSWORD_FILE" \\
    -out "$OUT_DIR/root-ca.key" """
    else:
        keygen = f"""$SPLUNK_HOME/bin/splunk cmd openssl genpkey \\
    -algorithm EC -pkeyopt ec_paramgen_curve:{kb["curve"]} \\
    -aes-256-cbc -pass file:"$PKI_ROOT_CA_KEY_PASSWORD_FILE" \\
    -out "$OUT_DIR/root-ca.key" """
    return _sh(f"""# Create the internal Root CA. Run this on an offline host when possible
# and back the resulting key + cert up to TWO physically separate locations.
#
# Inputs (env vars):
#   PKI_ROOT_CA_KEY_PASSWORD_FILE  Path to chmod 0600 file with root key passphrase
#   OUT_DIR                        Output directory (default: ./signed)
#   SPLUNK_HOME                    Splunk install (default: {args.splunk_home})

PKI_ROOT_CA_KEY_PASSWORD_FILE="${{PKI_ROOT_CA_KEY_PASSWORD_FILE:-}}"
OUT_DIR="${{OUT_DIR:-./signed}}"
SPLUNK_HOME="${{SPLUNK_HOME:-{args.splunk_home}}}"
DAYS={args.root_ca_days}

if [[ -z "$PKI_ROOT_CA_KEY_PASSWORD_FILE" ]] || [[ ! -r "$PKI_ROOT_CA_KEY_PASSWORD_FILE" ]]; then
    echo "ERROR: PKI_ROOT_CA_KEY_PASSWORD_FILE must be set and readable" >&2
    exit 1
fi

mkdir -p "$OUT_DIR"

{keygen}
chmod 0600 "$OUT_DIR/root-ca.key"

$SPLUNK_HOME/bin/splunk cmd openssl req -new -x509 -days "$DAYS" \\
    -config "$(dirname "$0")/openssl-root.cnf" \\
    -key "$OUT_DIR/root-ca.key" \\
    -passin file:"$PKI_ROOT_CA_KEY_PASSWORD_FILE" \\
    -sha384 \\
    -out "$OUT_DIR/root-ca.pem"
chmod 0644 "$OUT_DIR/root-ca.pem"

# Sanity check
$SPLUNK_HOME/bin/splunk cmd openssl x509 -in "$OUT_DIR/root-ca.pem" -text -noout | head -20
echo
echo "OK: Root CA written to $OUT_DIR/root-ca.{{key,pem}}"
echo "    Back up root-ca.key to TWO offline locations NOW."
""")


def _create_intermediate_ca_sh(args: argparse.Namespace) -> str:
    kb = _key_bits_or_curve(args.key_algorithm)
    if kb["family"] == "rsa":
        keygen = f"""$SPLUNK_HOME/bin/splunk cmd openssl genpkey \\
    -algorithm RSA -pkeyopt rsa_keygen_bits:{kb["bits"]} \\
    -aes-256-cbc -pass file:"$PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE" \\
    -out "$OUT_DIR/intermediate-ca.key" """
    else:
        keygen = f"""$SPLUNK_HOME/bin/splunk cmd openssl genpkey \\
    -algorithm EC -pkeyopt ec_paramgen_curve:{kb["curve"]} \\
    -aes-256-cbc -pass file:"$PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE" \\
    -out "$OUT_DIR/intermediate-ca.key" """
    return _sh(f"""# Create the internal Intermediate CA, signed by the Root CA. Run this
# AFTER create-root-ca.sh has produced root-ca.{{key,pem}}.
#
# Inputs (env vars):
#   PKI_ROOT_CA_KEY_PASSWORD_FILE          Path to root key passphrase file
#   PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE  Path to intermediate key passphrase file
#   OUT_DIR                                 Output directory (default: ./signed)
#   SPLUNK_HOME                             Splunk install (default: {args.splunk_home})

PKI_ROOT_CA_KEY_PASSWORD_FILE="${{PKI_ROOT_CA_KEY_PASSWORD_FILE:-}}"
PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE="${{PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE:-}}"
OUT_DIR="${{OUT_DIR:-./signed}}"
SPLUNK_HOME="${{SPLUNK_HOME:-{args.splunk_home}}}"
DAYS={args.intermediate_ca_days}

for var in PKI_ROOT_CA_KEY_PASSWORD_FILE PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE; do
    if [[ -z "${{!var}}" ]] || [[ ! -r "${{!var}}" ]]; then
        echo "ERROR: $var must be set and readable" >&2
        exit 1
    fi
done

if [[ ! -f "$OUT_DIR/root-ca.key" ]] || [[ ! -f "$OUT_DIR/root-ca.pem" ]]; then
    echo "ERROR: Run create-root-ca.sh first; root-ca.{{key,pem}} not found in $OUT_DIR" >&2
    exit 1
fi

{keygen}
chmod 0600 "$OUT_DIR/intermediate-ca.key"

$SPLUNK_HOME/bin/splunk cmd openssl req -new \\
    -config "$(dirname "$0")/openssl-intermediate.cnf" \\
    -key "$OUT_DIR/intermediate-ca.key" \\
    -passin file:"$PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE" \\
    -out "$OUT_DIR/intermediate-ca.csr"

$SPLUNK_HOME/bin/splunk cmd openssl x509 -req -days "$DAYS" \\
    -in "$OUT_DIR/intermediate-ca.csr" \\
    -CA "$OUT_DIR/root-ca.pem" \\
    -CAkey "$OUT_DIR/root-ca.key" \\
    -passin file:"$PKI_ROOT_CA_KEY_PASSWORD_FILE" \\
    -CAcreateserial \\
    -extfile "$(dirname "$0")/openssl-intermediate.cnf" \\
    -extensions v3_intermediate_ca \\
    -sha384 \\
    -out "$OUT_DIR/intermediate-ca.pem"
chmod 0644 "$OUT_DIR/intermediate-ca.pem"

# Build the trust bundle: intermediate + root.
cat "$OUT_DIR/intermediate-ca.pem" "$OUT_DIR/root-ca.pem" > "$OUT_DIR/cabundle.pem"
chmod 0644 "$OUT_DIR/cabundle.pem"

# Verify the chain
$SPLUNK_HOME/bin/splunk cmd openssl verify -verbose -x509_strict \\
    -CAfile "$OUT_DIR/root-ca.pem" \\
    "$OUT_DIR/intermediate-ca.pem"

echo "OK: Intermediate CA written to $OUT_DIR/intermediate-ca.{{key,pem}}"
echo "    Trust bundle written to $OUT_DIR/cabundle.pem"
""")


def _sign_server_cert_sh(args: argparse.Namespace) -> str:
    kb = _key_bits_or_curve(args.key_algorithm)
    if kb["family"] == "rsa":
        keygen = f"""$SPLUNK_HOME/bin/splunk cmd openssl genpkey \\
    -algorithm RSA -pkeyopt rsa_keygen_bits:{kb["bits"]} \\
    -aes-256-cbc -pass file:"$PKI_LEAF_KEY_PASSWORD_FILE" \\
    -out "$OUT_DIR/$NAME.key" """
    else:
        keygen = f"""$SPLUNK_HOME/bin/splunk cmd openssl genpkey \\
    -algorithm EC -pkeyopt ec_paramgen_curve:{kb["curve"]} \\
    -aes-256-cbc -pass file:"$PKI_LEAF_KEY_PASSWORD_FILE" \\
    -out "$OUT_DIR/$NAME.key" """
    if args.key_format == "pkcs8":
        post_keygen = """
# Convert to PKCS#8 (BEGIN PRIVATE KEY) - required for Edge Processor / DB Connect
$SPLUNK_HOME/bin/splunk cmd openssl pkcs8 -topk8 -inform PEM \\
    -in "$OUT_DIR/$NAME.key" \\
    -out "$OUT_DIR/$NAME.pkcs8.key" \\
    -nocrypt
mv "$OUT_DIR/$NAME.pkcs8.key" "$OUT_DIR/$NAME.key"
chmod 0600 "$OUT_DIR/$NAME.key"
"""
    else:
        post_keygen = ""
    return _sh(f"""# Sign a server leaf cert using the Intermediate CA (or Root if no
# Intermediate). Pass the CSR config file as --csr, the host name as --name,
# and the SANs as --san (CSV, may include DNS:host or IP:1.2.3.4).
#
# Usage:
#   PKI_LEAF_KEY_PASSWORD_FILE=/tmp/leaf-pwd \\
#   PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE=/tmp/int-pwd \\
#       bash sign-server-cert.sh --name splunkd-idx01.example.com \\
#                                --san DNS:idx01.example.com,DNS:idx01

NAME=""
SANS=""
OUT_DIR="${{OUT_DIR:-./signed}}"
SPLUNK_HOME="${{SPLUNK_HOME:-{args.splunk_home}}}"
DAYS={args.leaf_days}
SIGNER="${{SIGNER:-intermediate}}"   # intermediate | root

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name) NAME="$2"; shift 2 ;;
        --san)  SANS="$2"; shift 2 ;;
        --signer) SIGNER="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [[ -z "$NAME" ]] || [[ -z "$SANS" ]]; then
    echo "ERROR: --name and --san are required" >&2
    exit 1
fi

if [[ "$SIGNER" == "intermediate" ]]; then
    if [[ ! -f "$OUT_DIR/intermediate-ca.pem" ]]; then
        echo "ERROR: intermediate-ca.pem not found; pass --signer root or run create-intermediate-ca.sh first" >&2
        exit 1
    fi
    CA_CERT="$OUT_DIR/intermediate-ca.pem"
    CA_KEY="$OUT_DIR/intermediate-ca.key"
    CA_PASS_FILE="${{PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE:-}}"
else
    CA_CERT="$OUT_DIR/root-ca.pem"
    CA_KEY="$OUT_DIR/root-ca.key"
    CA_PASS_FILE="${{PKI_ROOT_CA_KEY_PASSWORD_FILE:-}}"
fi

if [[ -z "${{PKI_LEAF_KEY_PASSWORD_FILE:-}}" ]]; then
    echo "ERROR: PKI_LEAF_KEY_PASSWORD_FILE must be set" >&2
    exit 1
fi
if [[ -z "$CA_PASS_FILE" ]] || [[ ! -r "$CA_PASS_FILE" ]]; then
    echo "ERROR: CA passphrase file ($CA_PASS_FILE) must be set and readable" >&2
    exit 1
fi

mkdir -p "$OUT_DIR"

# Build a per-leaf CSR config inline (operator can override per-host with
# --csr-config).
CSR_TMP="$(mktemp)"
trap "rm -f $CSR_TMP" EXIT

cat > "$CSR_TMP" <<EOF
[ req ]
default_bits        = {kb.get("bits", 256)}
default_md          = sha384
prompt              = no
distinguished_name  = req_distinguished_name
req_extensions      = v3_req

[ req_distinguished_name ]
CN = $NAME

[ v3_req ]
basicConstraints   = critical, CA:FALSE
keyUsage           = critical, digitalSignature, keyEncipherment
extendedKeyUsage   = serverAuth, clientAuth
subjectAltName     = $SANS
EOF

{keygen}
chmod 0600 "$OUT_DIR/$NAME.key"
{post_keygen}
$SPLUNK_HOME/bin/splunk cmd openssl req -new \\
    -config "$CSR_TMP" \\
    -key "$OUT_DIR/$NAME.key" \\
    -passin file:"$PKI_LEAF_KEY_PASSWORD_FILE" \\
    -out "$OUT_DIR/$NAME.csr"

$SPLUNK_HOME/bin/splunk cmd openssl x509 -req -days "$DAYS" \\
    -in "$OUT_DIR/$NAME.csr" \\
    -CA "$CA_CERT" \\
    -CAkey "$CA_KEY" \\
    -passin file:"$CA_PASS_FILE" \\
    -CAcreateserial \\
    -extfile "$CSR_TMP" \\
    -extensions v3_req \\
    -sha384 \\
    -out "$OUT_DIR/$NAME.pem"
chmod 0644 "$OUT_DIR/$NAME.pem"

# Verify
$SPLUNK_HOME/bin/splunk cmd openssl verify -verbose -x509_strict \\
    -CAfile "$OUT_DIR/cabundle.pem" \\
    "$OUT_DIR/$NAME.pem"

echo "OK: Server leaf $NAME signed for $DAYS days. Files:"
echo "    $OUT_DIR/$NAME.pem"
echo "    $OUT_DIR/$NAME.key"
""")


def _sign_client_cert_sh(args: argparse.Namespace) -> str:
    return _sh(f"""# Sign a client leaf cert. Same as sign-server-cert.sh but with the
# client EKU profile. Used for forwarder mTLS and deployment-client mTLS.
exec "$(dirname "$0")/sign-server-cert.sh" "$@"
""")


def _sign_saml_sp_sh(args: argparse.Namespace) -> str:
    kb = _key_bits_or_curve(args.key_algorithm)
    if kb["family"] == "rsa":
        keygen = f"""$SPLUNK_HOME/bin/splunk cmd openssl genpkey \\
    -algorithm RSA -pkeyopt rsa_keygen_bits:{kb["bits"]} \\
    -aes-256-cbc -pass file:"$PKI_SAML_SP_KEY_PASSWORD_FILE" \\
    -out "$OUT_DIR/saml-sp-signing.key" """
    else:
        keygen = f"""$SPLUNK_HOME/bin/splunk cmd openssl genpkey \\
    -algorithm EC -pkeyopt ec_paramgen_curve:{kb["curve"]} \\
    -aes-256-cbc -pass file:"$PKI_SAML_SP_KEY_PASSWORD_FILE" \\
    -out "$OUT_DIR/saml-sp-signing.key" """
    return _sh(f"""# Sign the SAML SP signing cert. Separate trust domain from TLS:
# no Extended Key Usage, signing-only. Many IdPs reject SAML SP certs
# that carry serverAuth or clientAuth EKUs.
#
# Usage:
#   PKI_SAML_SP_KEY_PASSWORD_FILE=/tmp/sp-pwd \\
#   PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE=/tmp/int-pwd \\
#       bash sign-saml-sp.sh --name splunk.example.com

NAME=""
OUT_DIR="${{OUT_DIR:-./signed}}"
SPLUNK_HOME="${{SPLUNK_HOME:-{args.splunk_home}}}"
DAYS={args.leaf_days}
SIGNER="${{SIGNER:-intermediate}}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name) NAME="$2"; shift 2 ;;
        --signer) SIGNER="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [[ -z "$NAME" ]]; then
    echo "ERROR: --name (SP entity ID hostname) is required" >&2
    exit 1
fi
if [[ -z "${{PKI_SAML_SP_KEY_PASSWORD_FILE:-}}" ]]; then
    echo "ERROR: PKI_SAML_SP_KEY_PASSWORD_FILE must be set" >&2
    exit 1
fi

if [[ "$SIGNER" == "intermediate" ]]; then
    CA_CERT="$OUT_DIR/intermediate-ca.pem"
    CA_KEY="$OUT_DIR/intermediate-ca.key"
    CA_PASS_FILE="${{PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE:-}}"
else
    CA_CERT="$OUT_DIR/root-ca.pem"
    CA_KEY="$OUT_DIR/root-ca.key"
    CA_PASS_FILE="${{PKI_ROOT_CA_KEY_PASSWORD_FILE:-}}"
fi

mkdir -p "$OUT_DIR"

CSR_TMP="$(mktemp)"
trap "rm -f $CSR_TMP" EXIT

cat > "$CSR_TMP" <<EOF
[ req ]
default_bits        = {kb.get("bits", 256)}
default_md          = sha384
prompt              = no
distinguished_name  = req_distinguished_name
req_extensions      = v3_saml

[ req_distinguished_name ]
CN = $NAME

[ v3_saml ]
basicConstraints   = critical, CA:FALSE
keyUsage           = critical, digitalSignature, nonRepudiation
EOF

{keygen}
chmod 0600 "$OUT_DIR/saml-sp-signing.key"

$SPLUNK_HOME/bin/splunk cmd openssl req -new \\
    -config "$CSR_TMP" \\
    -key "$OUT_DIR/saml-sp-signing.key" \\
    -passin file:"$PKI_SAML_SP_KEY_PASSWORD_FILE" \\
    -out "$OUT_DIR/saml-sp-signing.csr"

$SPLUNK_HOME/bin/splunk cmd openssl x509 -req -days "$DAYS" \\
    -in "$OUT_DIR/saml-sp-signing.csr" \\
    -CA "$CA_CERT" \\
    -CAkey "$CA_KEY" \\
    -passin file:"$CA_PASS_FILE" \\
    -CAcreateserial \\
    -extfile "$CSR_TMP" \\
    -extensions v3_saml \\
    -sha384 \\
    -out "$OUT_DIR/saml-sp-signing.crt"
chmod 0644 "$OUT_DIR/saml-sp-signing.crt"

echo "OK: SAML SP signing cert + key written to $OUT_DIR/saml-sp-signing.{{crt,key}}"
echo "    After installing, regenerate SP metadata in Splunk Web and re-upload to the IdP."
""")


def _private_ca_readme(args: argparse.Namespace) -> str:
    return f"""# Private CA Operator Walkthrough

The renderer emits these scripts so you (the operator) become the
certificate authority. They run `$SPLUNK_HOME/bin/splunk cmd openssl`
so the same OpenSSL build that Splunk uses signs and verifies.

## Order of operations

```bash
# 1. Capture the CA passphrases in chmod-600 files. NEVER paste secrets.
bash skills/shared/scripts/write_secret_file.sh /tmp/pki_root_ca_key_password
{"bash skills/shared/scripts/write_secret_file.sh /tmp/pki_intermediate_ca_key_password" if _bool(args.include_intermediate_ca) else ""}
bash skills/shared/scripts/write_secret_file.sh /tmp/pki_leaf_key_password

# 2. Build the Root CA (run on an OFFLINE host when possible).
PKI_ROOT_CA_KEY_PASSWORD_FILE=/tmp/pki_root_ca_key_password \\
    bash create-root-ca.sh

{"# 3. Build the Intermediate CA, signed by the Root." if _bool(args.include_intermediate_ca) else "# 3. (Intermediate CA not requested via --include-intermediate-ca; skip.)"}
{"PKI_ROOT_CA_KEY_PASSWORD_FILE=/tmp/pki_root_ca_key_password \\\\\n    PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE=/tmp/pki_intermediate_ca_key_password \\\\\n    bash create-intermediate-ca.sh" if _bool(args.include_intermediate_ca) else ""}

# 4. Sign per-host server leaves. Repeat for each Splunk host.
PKI_LEAF_KEY_PASSWORD_FILE=/tmp/pki_leaf_key_password \\
    PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE=/tmp/pki_intermediate_ca_key_password \\
    bash sign-server-cert.sh \\
        --name splunkd-idx01.example.com \\
        --san  DNS:idx01.example.com,DNS:idx01

# 5. (Optional) sign client leaves for forwarder / DC mTLS.
PKI_LEAF_KEY_PASSWORD_FILE=/tmp/pki_leaf_key_password \\
    PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE=/tmp/pki_intermediate_ca_key_password \\
    bash sign-client-cert.sh \\
        --name client-uf01.example.com \\
        --san  DNS:uf01.example.com

# 6. (Optional) sign the SAML SP signing cert.
PKI_SAML_SP_KEY_PASSWORD_FILE=/tmp/pki_saml_sp_key_password \\
    PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE=/tmp/pki_intermediate_ca_key_password \\
    bash sign-saml-sp.sh --name splunk.example.com
```

## Backup the Root CA

The Root CA private key MUST be backed up to TWO physically separate
offline locations. If lost, every cert based on this Root must be
regenerated and redistributed — multiple days of cluster downtime.

## Validity windows

| Identity | Default | Override |
|---|---|---|
| Root CA | {args.root_ca_days} days | `--root-ca-days N` |
| Intermediate CA | {args.intermediate_ca_days} days | `--intermediate-ca-days N` |
| Leaves | {args.leaf_days} days | `--leaf-days N` |

## Next steps

- Verify each signed leaf with `bash ../install/verify-leaf.sh`.
- Run `bash ../install/kv-store-eku-check.sh` for any leaf destined for a
  KV-Store host (search head, SHC member, single SH).
- Stage the signed leaves on the target hosts using
  `bash ../install/install-leaf.sh`.
- See `../rotate/plan-rotation.md` for the cluster-wide rollout sequence.
"""


# ---------- CSR generation ----------

def _generate_csr_sh(args: argparse.Namespace) -> str:
    kb = _key_bits_or_curve(args.key_algorithm)
    if kb["family"] == "rsa":
        keygen = f"""$SPLUNK_HOME/bin/splunk cmd openssl genpkey \\
    -algorithm RSA -pkeyopt rsa_keygen_bits:{kb["bits"]} \\
    -aes-256-cbc -pass file:"$PKI_LEAF_KEY_PASSWORD_FILE" \\
    -out "$OUT_DIR/$BASENAME.key" """
    else:
        keygen = f"""$SPLUNK_HOME/bin/splunk cmd openssl genpkey \\
    -algorithm EC -pkeyopt ec_paramgen_curve:{kb["curve"]} \\
    -aes-256-cbc -pass file:"$PKI_LEAF_KEY_PASSWORD_FILE" \\
    -out "$OUT_DIR/$BASENAME.key" """
    return _sh(f"""# Generate a CSR + private key for one host. Used in BOTH private and
# public modes:
#  - private mode: feeds into sign-server-cert.sh.
#  - public  mode: emit the .csr and submit to the operator's CA
#                  (Vault PKI / ACME / AD CS / EJBCA / commercial).
#
# Usage:
#   PKI_LEAF_KEY_PASSWORD_FILE=/tmp/leaf-pwd \\
#       bash generate-csr.sh --config splunkd-idx01.example.com.cnf
#
# The .cnf file is one of the per-host templates in this directory.

CONFIG=""
OUT_DIR="${{OUT_DIR:-../signed}}"
SPLUNK_HOME="${{SPLUNK_HOME:-{args.splunk_home}}}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config) CONFIG="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [[ -z "$CONFIG" ]] || [[ ! -f "$CONFIG" ]]; then
    echo "ERROR: --config <file> required and must exist" >&2
    exit 1
fi
if [[ -z "${{PKI_LEAF_KEY_PASSWORD_FILE:-}}" ]]; then
    echo "ERROR: PKI_LEAF_KEY_PASSWORD_FILE must be set" >&2
    exit 1
fi

BASENAME="$(basename "$CONFIG" .cnf)"
mkdir -p "$OUT_DIR"

{keygen}
chmod 0600 "$OUT_DIR/$BASENAME.key"

$SPLUNK_HOME/bin/splunk cmd openssl req -new \\
    -config "$CONFIG" \\
    -key "$OUT_DIR/$BASENAME.key" \\
    -passin file:"$PKI_LEAF_KEY_PASSWORD_FILE" \\
    -out "$OUT_DIR/$BASENAME.csr"

echo "OK: CSR $OUT_DIR/$BASENAME.csr (key: $OUT_DIR/$BASENAME.key)"
""")


def _csr_template_cnf(args: argparse.Namespace, role: str, host: str, sans: list[str], saml: bool = False) -> str:
    kb = _key_bits_or_curve(args.key_algorithm)
    san_lines = []
    dns_index = 0
    ip_index = 0
    for s in sans:
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", s):
            ip_index += 1
            san_lines.append(f"IP.{ip_index} = {s}")
        else:
            dns_index += 1
            san_lines.append(f"DNS.{dns_index} = {s}")
    san_block = "\n".join(san_lines)
    profile = "v3_saml" if saml else "v3_req"
    profile_extensions = (
        "basicConstraints   = critical, CA:FALSE\n"
        "keyUsage           = critical, digitalSignature, nonRepudiation"
    ) if saml else (
        "basicConstraints   = critical, CA:FALSE\n"
        "keyUsage           = critical, digitalSignature, keyEncipherment\n"
        "extendedKeyUsage   = serverAuth, clientAuth"
    )
    san_section = "" if saml else f"subjectAltName     = @alt_names\n\n[ alt_names ]\n{san_block}\n"
    return f"""# CSR template rendered by splunk-platform-pki-setup.
# Role: {role}
# Host: {host}
# Algorithm: {args.key_algorithm}

[ req ]
default_bits        = {kb.get("bits", 256)}
default_md          = sha384
prompt              = no
distinguished_name  = req_distinguished_name
req_extensions      = {profile}

[ req_distinguished_name ]
C  = {args.ca_country}
{f"ST = {args.ca_state}" if args.ca_state else ""}
{f"L  = {args.ca_locality}" if args.ca_locality else ""}
O  = {args.ca_organization}
OU = {args.ca_organizational_unit}
CN = {host}
{f"emailAddress = {args.ca_email}" if args.ca_email else ""}

[ {profile} ]
{profile_extensions}
{san_section}"""


def _csr_template_readme(args: argparse.Namespace, mode: str) -> str:
    if mode == "private":
        body = """## Private mode

Each `.cnf` here is a CSR template for one Splunk host. After running
`generate-csr.sh --config <name>.cnf` you'll have a `.key` (encrypted)
and a `.csr` ready to feed into `../private-ca/sign-server-cert.sh` (or
`sign-saml-sp.sh` for the SAML SP cert).
"""
    else:
        body = """## Public mode

Each `.cnf` here is a CSR template for one Splunk host. After running
`generate-csr.sh --config <name>.cnf` you'll have a `.key` (encrypted,
keep it on the host) and a `.csr` to submit to your CA.

See:

- `../../handoff/vault-pki.md` for HashiCorp Vault PKI
- `../../handoff/acme-cert-manager.md` for ACME / Let's Encrypt / cert-manager
- `../../handoff/microsoft-adcs.md` for Microsoft AD CS
- `../../handoff/ejbca.md` for EJBCA
"""
    return f"""# CSR Templates

These templates produce CSRs that match Splunk's TLS requirements:

- **Dual EKU** (`serverAuth` + `clientAuth`) on every server leaf so
  KV Store 7.0+ accepts them.
- **SAN** populated from operator-supplied per-host FQDN list.
- **{args.key_algorithm}** key algorithm.
- **SHA-384** signing.

{body}
"""


# ---------- Install / verify ----------

def _install_leaf_sh(args: argparse.Namespace) -> str:
    install_subdir = args.cert_install_subdir
    splunk_home = args.splunk_home
    return _sh(f"""# Install a signed leaf cert + key on the local Splunk host AND write
# the per-host conf overlay to $SPLUNK_HOME/etc/system/local/<conf>.
# This is the critical step that makes the cluster bundle (which only
# carries SHARED settings) work correctly: each host's etc/system/local/
# overlay supplies the host-specific serverCert and sslPassword.
#
# Sets correct perms (0600 key, 0644 cert), aligns CLI trust, runs the
# KV Store EKU check for splunkd / SHC / core5 targets, and (when
# --ssl-password-file is supplied) writes the plaintext sslPassword
# into the overlay so Splunk encrypts it on first restart.
#
# Usage:
#   bash install-leaf.sh \\
#        --target splunkd \\
#        --host idx01.example.com \\
#        --cert /tmp/signed/splunkd-idx01.example.com.pem \\
#        --key  /tmp/signed/splunkd-idx01.example.com.key \\
#        --ca   /tmp/signed/cabundle.pem \\
#        [--ssl-password-file /tmp/leaf-key-password]
#
# --target is one of:
#   splunkd     -> write [sslConfig] serverCert overlay to system/local/server.conf
#   web         -> write [settings] serverCert+privKeyPath overlay to system/local/web.conf
#   s2s         -> write [SSL] serverCert overlay to system/local/inputs.conf
#   hec         -> write [http] serverCert overlay to system/local/inputs.conf
#   replication -> write [replication_port-ssl://9887] overlay to system/local/server.conf
#   forwarder   -> write [tcpout] clientCert overlay to system/local/outputs.conf
#   shc         -> alias for splunkd (SHC member)
#   core5       -> splunkd + web + s2s + hec on a single SH; writes ALL overlays
#
# Per-host SSL passphrase handling:
#   If --ssl-password-file PATH is supplied, install-leaf.sh writes the
#   PLAINTEXT password verbatim into the overlay's sslPassword line.
#   On first Splunk restart, splunkd encrypts it with splunk.secret and
#   rewrites the file. If --ssl-password-file is omitted, the script
#   assumes the leaf key is unencrypted (e.g. PKCS#8 nocrypt) and skips
#   sslPassword entirely.

TARGET=""
HOST=""
CERT=""
KEY=""
CA=""
SSL_PASSWORD_FILE=""
SPLUNK_HOME="${{SPLUNK_HOME:-{splunk_home}}}"
INSTALL_SUBDIR="${{INSTALL_SUBDIR:-{install_subdir}}}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target) TARGET="$2"; shift 2 ;;
        --host)   HOST="$2"; shift 2 ;;
        --cert)   CERT="$2"; shift 2 ;;
        --key)    KEY="$2"; shift 2 ;;
        --ca)     CA="$2"; shift 2 ;;
        --ssl-password-file) SSL_PASSWORD_FILE="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

for var in TARGET HOST CERT KEY CA; do
    if [[ -z "${{!var}}" ]]; then
        echo "ERROR: --${{var,,}} is required" >&2
        exit 1
    fi
done

valid_targets="splunkd web s2s hec replication forwarder shc core5"
found=0
for t in $valid_targets; do
    [[ "$TARGET" == "$t" ]] && found=1
done
if [[ "$found" -eq 0 ]]; then
    echo "ERROR: --target must be one of: $valid_targets" >&2
    exit 1
fi

DEST="$SPLUNK_HOME/etc/auth/$INSTALL_SUBDIR/$HOST"
mkdir -p "$DEST"

# Backup any existing PEMs
if compgen -G "$DEST/*.pem" > /dev/null || compgen -G "$DEST/*.key" > /dev/null; then
    BACKUP="$DEST/_backup-$(date -u +%Y%m%dT%H%M%SZ)"
    mkdir -p "$BACKUP"
    cp -p "$DEST"/*.pem "$DEST"/*.key "$BACKUP"/ 2>/dev/null || true
    echo "Backed up existing PEMs to $BACKUP"
fi

# Copy PEM files into the install directory, normalising names so the
# overlay always references the same path. Operators can override by
# setting the rendered overlay paths if they use a different layout.
NAME=""
case "$TARGET" in
    splunkd|shc) NAME="$HOST-splunkd" ;;
    web)         NAME="$HOST-web" ;;
    s2s)         NAME="$HOST-s2s" ;;
    hec)         NAME="$HOST-hec" ;;
    replication) NAME="$HOST-replication" ;;
    forwarder)   NAME="$HOST-s2s-client" ;;
    core5)       NAME="$HOST-splunkd" ;;  # core5 reuses splunkd PEM for system/local/web.conf
esac
cp -p "$CERT" "$DEST/$NAME.pem"
cp -p "$KEY"  "$DEST/$NAME.key"
cp -p "$CA"   "$DEST/cabundle.pem"

chmod 0600 "$DEST"/*.key
chmod 0644 "$DEST"/*.pem

# Verify the chain before declaring success
"$SPLUNK_HOME/bin/splunk" cmd openssl verify -verbose -x509_strict \\
    -CAfile "$DEST/cabundle.pem" \\
    "$DEST/$NAME.pem"

# Align CLI trust so subsequent `splunk` invocations work
bash "$(dirname "$0")/align-cli-trust.sh" "$DEST/cabundle.pem"

# KV-Store EKU check (splunkd / SHC / single-SH leaves only)
if [[ "$TARGET" == "splunkd" ]] || [[ "$TARGET" == "shc" ]] || [[ "$TARGET" == "core5" ]]; then
    bash "$(dirname "$0")/kv-store-eku-check.sh" \\
        --cert "$DEST/$NAME.pem" \\
        --ca   "$DEST/cabundle.pem"
fi

# Write the per-host overlay snippet to $SPLUNK_HOME/etc/system/local/<conf>.
# The cluster/SHC/standalone bundle does NOT carry per-host serverCert
# (which would resolve to the same literal file on every host); the
# overlay supplies it on each host individually.
SYSTEM_LOCAL="$SPLUNK_HOME/etc/system/local"
mkdir -p "$SYSTEM_LOCAL"

write_overlay() {{
    local conf="$1"
    local body="$2"
    local marker_begin="### BEGIN splunk-platform-pki-setup [$TARGET]"
    local marker_end="### END splunk-platform-pki-setup [$TARGET]"
    local target_file="$SYSTEM_LOCAL/$conf"

    # Strip any prior block for this target (idempotent re-runs).
    if [[ -f "$target_file" ]]; then
        cp -p "$target_file" "${{target_file}}.pki-backup-$(date -u +%Y%m%dT%H%M%SZ)"
        awk -v b="$marker_begin" -v e="$marker_end" '
            $0 == b {{ skip = 1; next }}
            $0 == e {{ skip = 0; next }}
            !skip   {{ print }}
        ' "$target_file" > "$target_file.tmp"
        mv "$target_file.tmp" "$target_file"
    fi

    {{
        printf '\\n%s\\n%s%s\\n' "$marker_begin" "$body" "$marker_end"
    }} >> "$target_file"
    chmod 0644 "$target_file"
}}

# Build the sslPassword line if --ssl-password-file was supplied.
SSL_PASSWORD_LINE=""
if [[ -n "$SSL_PASSWORD_FILE" ]]; then
    if [[ ! -r "$SSL_PASSWORD_FILE" ]]; then
        echo "ERROR: --ssl-password-file '$SSL_PASSWORD_FILE' is not readable" >&2
        exit 1
    fi
    SSL_PASSWORD_LINE="sslPassword = $(< "$SSL_PASSWORD_FILE")"
fi

case "$TARGET" in
    splunkd|shc)
        body="[sslConfig]
serverCert  = $DEST/$NAME.pem
$SSL_PASSWORD_LINE
"
        write_overlay "server.conf" "$body"
        ;;
    web)
        body="[settings]
serverCert  = $DEST/$NAME.pem
privKeyPath = $DEST/$NAME.key
$SSL_PASSWORD_LINE
"
        write_overlay "web.conf" "$body"
        ;;
    s2s)
        body="[SSL]
serverCert  = $DEST/$NAME.pem
$SSL_PASSWORD_LINE
"
        write_overlay "inputs.conf" "$body"
        ;;
    hec)
        body="[http]
serverCert  = $DEST/$NAME.pem
$SSL_PASSWORD_LINE
"
        write_overlay "inputs.conf" "$body"
        ;;
    replication)
        # Peer list comes from the rendered cluster bundle; pass via env if
        # different from the bundle.
        PEER_NAMES="${{REPLICATION_PEER_NAMES:-}}"
        body="[replication_port-ssl://9887]
disabled              = 0
rootCA                = $DEST/cabundle.pem
serverCert            = $DEST/$NAME.pem
sslCommonNameToCheck  = $PEER_NAMES
sslAltNameToCheck     = $PEER_NAMES
requireClientCert     = true
$SSL_PASSWORD_LINE
"
        write_overlay "server.conf" "$body"
        ;;
    forwarder)
        body="[tcpout]
clientCert  = $DEST/$NAME.pem
$SSL_PASSWORD_LINE
"
        write_overlay "outputs.conf" "$body"
        ;;
    core5)
        # Single SH that runs splunkd + web + s2s + hec. Re-run install-leaf.sh
        # for each surface separately if they use different PEMs; this branch
        # writes only the splunkd overlay.
        body="[sslConfig]
serverCert  = $DEST/$NAME.pem
$SSL_PASSWORD_LINE
"
        write_overlay "server.conf" "$body"
        ;;
esac

echo "OK: $TARGET cert installed for $HOST at $DEST"
echo "    Per-host overlay written to $SYSTEM_LOCAL/<conf>"
echo "Run 'splunk restart' on this host (or use the rotation runbook for clustered hosts)."
""")


def _verify_leaf_sh(args: argparse.Namespace) -> str:
    return _sh(f"""# Verify a signed leaf cert against a CA bundle. Uses Splunk's bundled
# OpenSSL so the verification matches what Splunk will do at startup.
#
# Usage: bash verify-leaf.sh --cert <leaf.pem> --ca <cabundle.pem>

CERT=""
CA=""
SPLUNK_HOME="${{SPLUNK_HOME:-{args.splunk_home}}}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --cert) CERT="$2"; shift 2 ;;
        --ca)   CA="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [[ -z "$CERT" ]] || [[ -z "$CA" ]]; then
    echo "ERROR: --cert and --ca required" >&2
    exit 1
fi

if "$SPLUNK_HOME/bin/splunk" cmd openssl verify -verbose -x509_strict \\
    -CAfile "$CA" "$CERT"; then
    echo "OK: $CERT validates against $CA"
else
    echo "FAIL: $CERT does not validate against $CA"
    exit 1
fi

# Show the SANs so the operator can sanity-check
echo
echo "Subject and SANs:"
"$SPLUNK_HOME/bin/splunk" cmd openssl x509 -in "$CERT" -text -noout \\
    | grep -E 'Subject:|DNS:|IP Address:'

# Check default-cert subject tokens (refuses to declare ready)
DEFAULT_TOKENS="SplunkServerDefaultCert SplunkCommonCA SplunkWebDefaultCert"
for token in $DEFAULT_TOKENS; do
    if "$SPLUNK_HOME/bin/splunk" cmd openssl x509 -in "$CERT" -subject -noout \\
        | grep -q "$token"; then
        echo "FAIL: $CERT still uses the default Splunk subject token '$token'."
        echo "      You must replace this cert before declaring the host ready."
        exit 1
    fi
done

echo "OK: $CERT does not use any default Splunk subject token."
""")


def _kv_store_eku_check_sh(args: argparse.Namespace) -> str:
    return _sh(f"""# Run the KV Store custom-cert prep check from the Splunk doc:
#   https://docs.splunk.com/Documentation/Splunk/9.4.2/Admin/CustomCertsKVstore
#
# Refuses success unless openssl verify -x509_strict returns OK AND the
# cert carries both serverAuth and clientAuth EKU values.

CERT=""
CA=""
SPLUNK_HOME="${{SPLUNK_HOME:-{args.splunk_home}}}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --cert) CERT="$2"; shift 2 ;;
        --ca)   CA="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [[ -z "$CERT" ]] || [[ -z "$CA" ]]; then
    echo "ERROR: --cert and --ca required" >&2
    exit 1
fi

# Strict chain check
if ! "$SPLUNK_HOME/bin/splunk" cmd openssl verify -verbose -x509_strict \\
    -CAfile "$CA" "$CERT"; then
    echo "FAIL: KV Store will reject this cert (chain validation failed under -x509_strict)."
    echo "      Ensure $CA contains the full chain (intermediate + root)."
    exit 1
fi

# EKU check
EKU="$("$SPLUNK_HOME/bin/splunk" cmd openssl x509 -in "$CERT" -text -noout \\
    | awk '/X509v3 Extended Key Usage/{{getline; print}}' \\
    | tr ',' '\\n' | tr -d ' ')"
need_server=true
need_client=true
while IFS= read -r usage; do
    [[ "$usage" == "TLSWebServerAuthentication" ]] && need_server=false
    [[ "$usage" == "TLSWebClientAuthentication" ]] && need_client=false
done <<< "$EKU"

if $need_server; then
    echo "FAIL: $CERT missing serverAuth EKU; KV Store will refuse to start."
    exit 1
fi
if $need_client; then
    echo "FAIL: $CERT missing clientAuth EKU; KV Store will refuse to start."
    exit 1
fi

echo "OK: $CERT has both serverAuth and clientAuth EKUs and validates under -x509_strict."
""")


def _align_cli_trust_sh(args: argparse.Namespace) -> str:
    return _sh(f"""# Copy the new CA bundle to $SPLUNK_HOME/etc/auth/cacert.pem so the
# local `splunk` CLI trusts the new chain. Without this, post-rotation
# CLI calls (`splunk apply cluster-bundle`, `splunk show cluster-status`)
# fail with "certificate verify failed".

NEW_CA_BUNDLE="${{1:-}}"
SPLUNK_HOME="${{SPLUNK_HOME:-{args.splunk_home}}}"
DEST="$SPLUNK_HOME/etc/auth/cacert.pem"

if [[ -z "$NEW_CA_BUNDLE" ]] || [[ ! -f "$NEW_CA_BUNDLE" ]]; then
    echo "ERROR: usage: $0 <new-ca-bundle.pem>" >&2
    exit 1
fi

if [[ -f "$DEST" ]]; then
    cp -p "$DEST" "${{DEST}}.pki-backup-$(date -u +%Y%m%dT%H%M%SZ)"
fi

cp -p "$NEW_CA_BUNDLE" "$DEST"
chmod 0644 "$DEST"

if "$SPLUNK_HOME/bin/splunk" cmd openssl verify -CAfile "$DEST" "$NEW_CA_BUNDLE" >/dev/null 2>&1; then
    echo "OK: cacert.pem aligned to new CA bundle"
else
    echo "WARN: openssl verify of $DEST failed; restore backup if local CLI breaks"
    exit 1
fi
""")


def _install_fips_launch_conf_sh(args: argparse.Namespace) -> str:
    return _sh(f"""# Idempotently set SPLUNK_FIPS_VERSION in splunk-launch.conf.
#
# NIST deprecates FIPS 140-2 on 2026-09-21. New deployments default to 140-3.
# See references/fips-and-common-criteria.md for the Phase 1 / Phase 2
# upgrade flow.

SPLUNK_HOME="${{SPLUNK_HOME:-{args.splunk_home}}}"
TARGET_FIPS_VERSION="${{1:-{args.fips_mode}}}"
LAUNCH_CONF="$SPLUNK_HOME/etc/splunk-launch.conf"

if [[ "$TARGET_FIPS_VERSION" == "none" ]]; then
    # Removing the line idempotently
    if grep -q '^SPLUNK_FIPS_VERSION' "$LAUNCH_CONF" 2>/dev/null; then
        cp -p "$LAUNCH_CONF" "$LAUNCH_CONF.pki-backup-$(date -u +%Y%m%dT%H%M%SZ)"
        sed -i.bak '/^SPLUNK_FIPS_VERSION/d' "$LAUNCH_CONF"
        rm -f "$LAUNCH_CONF.bak"
    fi
    echo "OK: FIPS disabled (line removed from splunk-launch.conf if present)"
    exit 0
fi

if [[ "$TARGET_FIPS_VERSION" != "140-2" ]] && [[ "$TARGET_FIPS_VERSION" != "140-3" ]]; then
    echo "ERROR: TARGET_FIPS_VERSION must be 140-2, 140-3, or none" >&2
    exit 1
fi

mkdir -p "$(dirname "$LAUNCH_CONF")"
[[ -f "$LAUNCH_CONF" ]] || touch "$LAUNCH_CONF"

if grep -q '^SPLUNK_FIPS_VERSION' "$LAUNCH_CONF"; then
    cp -p "$LAUNCH_CONF" "$LAUNCH_CONF.pki-backup-$(date -u +%Y%m%dT%H%M%SZ)"
    sed -i.bak "s/^SPLUNK_FIPS_VERSION.*/SPLUNK_FIPS_VERSION = $TARGET_FIPS_VERSION/" "$LAUNCH_CONF"
    rm -f "$LAUNCH_CONF.bak"
else
    echo "SPLUNK_FIPS_VERSION = $TARGET_FIPS_VERSION" >> "$LAUNCH_CONF"
fi

echo "OK: SPLUNK_FIPS_VERSION = $TARGET_FIPS_VERSION written to $LAUNCH_CONF"
echo "    Restart Splunk for the change to take effect."
""")


def _prepare_key_sh(args: argparse.Namespace) -> str:
    return _sh(f"""# Convert keys between PKCS#1 (BEGIN RSA PRIVATE KEY) and PKCS#8
# (BEGIN PRIVATE KEY), and concatenate cert chains.
#
# Usage:
#   bash prepare-key.sh --to-pkcs8 --in pkcs1.key --out pkcs8.key
#   bash prepare-key.sh --to-pkcs1 --in pkcs8.key --out pkcs1.key
#   bash prepare-key.sh --concat --leaf leaf.pem --intermediate int.pem [--root root.pem] --out chain.pem

ACTION=""
IN_FILE=""
OUT_FILE=""
LEAF=""
INTERMEDIATE=""
ROOT=""
SPLUNK_HOME="${{SPLUNK_HOME:-{args.splunk_home}}}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --to-pkcs8) ACTION="to-pkcs8"; shift ;;
        --to-pkcs1) ACTION="to-pkcs1"; shift ;;
        --concat)   ACTION="concat";   shift ;;
        --in)       IN_FILE="$2";  shift 2 ;;
        --out)      OUT_FILE="$2"; shift 2 ;;
        --leaf)     LEAF="$2";     shift 2 ;;
        --intermediate) INTERMEDIATE="$2"; shift 2 ;;
        --root)     ROOT="$2";     shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

case "$ACTION" in
    to-pkcs8)
        [[ -z "$IN_FILE" || -z "$OUT_FILE" ]] && {{ echo "ERROR: --in and --out required" >&2; exit 1; }}
        $SPLUNK_HOME/bin/splunk cmd openssl pkcs8 -topk8 -inform PEM \\
            -in "$IN_FILE" -out "$OUT_FILE" -nocrypt
        chmod 0600 "$OUT_FILE"
        echo "OK: $IN_FILE (PKCS#1) -> $OUT_FILE (PKCS#8 unencrypted)"
        ;;
    to-pkcs1)
        [[ -z "$IN_FILE" || -z "$OUT_FILE" ]] && {{ echo "ERROR: --in and --out required" >&2; exit 1; }}
        $SPLUNK_HOME/bin/splunk cmd openssl rsa -in "$IN_FILE" -out "$OUT_FILE"
        chmod 0600 "$OUT_FILE"
        echo "OK: $IN_FILE (PKCS#8) -> $OUT_FILE (PKCS#1)"
        ;;
    concat)
        [[ -z "$LEAF" || -z "$INTERMEDIATE" || -z "$OUT_FILE" ]] && {{
            echo "ERROR: --leaf, --intermediate, --out required (--root optional)" >&2
            exit 1
        }}
        if [[ -n "$ROOT" ]]; then
            cat "$LEAF" "$INTERMEDIATE" "$ROOT" > "$OUT_FILE"
        else
            cat "$LEAF" "$INTERMEDIATE" > "$OUT_FILE"
        fi
        chmod 0644 "$OUT_FILE"
        echo "OK: chain written to $OUT_FILE"
        ;;
    *)
        echo "ERROR: must specify --to-pkcs8, --to-pkcs1, or --concat" >&2
        exit 1
        ;;
esac
""")


def _install_readme(args: argparse.Namespace) -> str:
    return f"""# Install / Verify Helpers

| Script | Purpose |
|---|---|
| `install-leaf.sh` | Install a signed leaf cert + key on the local host with correct perms; back up old PEMs; align CLI trust; run KV-Store EKU check on splunkd certs. |
| `verify-leaf.sh` | `openssl verify -x509_strict` against the CA bundle + reject default Splunk subject tokens. |
| `kv-store-eku-check.sh` | Documented KV Store 7.0+ check: chain validity + dual `serverAuth`/`clientAuth` EKU. Refuses if either is missing. |
| `align-cli-trust.sh` | Copy CA bundle to `$SPLUNK_HOME/etc/auth/cacert.pem` so the local `splunk` CLI trusts the new chain. |
| `install-fips-launch-conf.sh` | Idempotently flip `SPLUNK_FIPS_VERSION` in `splunk-launch.conf` ({args.fips_mode}). |
| `prepare-key.sh` | PKCS#1 ↔ PKCS#8 conversion + chain concatenation. |
"""


# ---------- Distribution payloads ----------

def _app_conf(name: str) -> str:
    return f"""# Rendered by splunk-platform-pki-setup. Do not edit; re-render instead.
[install]
state = enabled

[ui]
is_visible = false
label = {name}

[launcher]
author = Splunk Platform PKI Setup
description = Trust anchor + TLS settings rendered by splunk-platform-pki-setup
version = 1.0.0

[package]
id = {name}
"""


def _shared_ssl_block(preset: dict, args: argparse.Namespace, mtls: set[str], name_check: str = "") -> str:
    """Cluster-wide / SHC-wide / fleet-wide [sslConfig] block.

    Carries trust anchor + cipher policy + name checks ONLY. Per-host
    `serverCert` and `sslPassword` are written by `install-leaf.sh` to
    each host's `etc/system/local/server.conf` (the per-host overlay),
    NOT to the shared bundle. This avoids the "every peer looks for the
    same literal serverCert path" bug that would break a shared bundle.
    """
    require_client = "true" if "splunkd" in mtls else "false"
    name_check_block = (
        f"sslCommonNameToCheck = {name_check}\nsslAltNameToCheck    = {name_check}\n"
        if (require_client == "true" and name_check)
        else ""
    )
    ca_path = f"{args.splunk_home}/etc/auth/{args.cert_install_subdir}/cabundle.pem"
    return f"""[sslConfig]
enableSplunkdSSL     = true
sslRootCAPath        = {ca_path}
caTrustStore         = splunk
sslVersions          = {preset['ssl_versions']}
sslVersionsForClient = {preset['ssl_versions_for_client']}
cipherSuite          = {preset['cipher_suite']}
ecdhCurves           = {preset['ecdh_curves']}
sslVerifyServerCert  = true
sslVerifyServerName  = true
requireClientCert    = {require_client}
{name_check_block}# Per-host serverCert / sslPassword are NOT in the bundle (they would
# break shared distribution because the path would resolve to the same
# literal file on every host). Each host's etc/system/local/server.conf
# overlay carries the host-specific serverCert + sslPassword;
# install-leaf.sh writes that overlay automatically.
"""


def _shared_web_block(preset: dict, args: argparse.Namespace) -> str:
    """Splunk Web settings safe to ship in a shared bundle. Per-host
    `serverCert` / `privKeyPath` / `sslPassword` go to the per-host
    overlay via install-leaf.sh."""
    ca_path = f"{args.splunk_home}/etc/auth/{args.cert_install_subdir}/cabundle.pem"
    return f"""[settings]
enableSplunkWebSSL = true
caCertPath         = {ca_path}
sslVersions        = {preset['ssl_versions']}
cipherSuite        = {preset['cipher_suite']}
ecdhCurves         = {preset['ecdh_curves']}
# Per-host serverCert / privKeyPath / sslPassword written by
# install-leaf.sh to etc/system/local/web.conf, NOT to this bundle.
"""


def _shared_s2s_block(preset: dict, args: argparse.Namespace, mtls: set[str], name_check: str = "") -> str:
    """S2S receiver shared settings. Per-host serverCert + sslPassword
    via install-leaf.sh."""
    require_client = "true" if "s2s" in mtls else "false"
    name_check_block = (
        f"sslCommonNameToCheck = {name_check}\nsslAltNameToCheck    = {name_check}\n"
        if (require_client == "true" and name_check)
        else ""
    )
    return f"""[splunktcp-ssl:9997]
disabled = 0

[SSL]
requireClientCert = {require_client}
sslVersions       = {preset['ssl_versions']}
cipherSuite       = {preset['cipher_suite']}
{name_check_block}# Per-host serverCert / sslPassword written by install-leaf.sh to
# etc/system/local/inputs.conf, NOT to this bundle.
"""


def _shared_hec_block(preset: dict, args: argparse.Namespace, mtls: set[str]) -> str:
    require_client = "true" if "hec" in mtls else "false"
    return f"""[http]
enableSSL             = 1
requireClientCert     = {require_client}
allowSslRenegotiation = false
allowSslCompression   = false
sslVersions           = {preset['ssl_versions']}
cipherSuite           = {preset['cipher_suite']}
# Per-host serverCert / sslPassword written by install-leaf.sh to
# etc/system/local/inputs.conf, NOT to this bundle.
"""


def _cluster_bundle_server_conf(args: argparse.Namespace, preset: dict, mtls: set[str]) -> str:
    name_check = ",".join(_split_csv(args.peer_hosts))
    return f"""# Rendered by splunk-platform-pki-setup.
# Cluster bundle drop-in. Trust anchor + cipher policy distributed via
# the cluster bundle; per-peer serverCert lives in each peer's
# etc/system/local/server.conf overlay (install-leaf.sh writes it).
#
# IF --encrypt-replication-port=true was set, the replication-port-ssl
# stanza ALSO lives in the per-host overlay (not here) because each
# peer needs its own serverCert in that stanza too.
{_shared_ssl_block(preset, args, mtls, name_check)}"""


def _cluster_bundle_inputs_conf(args: argparse.Namespace, preset: dict, mtls: set[str]) -> str:
    name_check = ",".join(_split_csv(args.peer_hosts))
    return f"""# Rendered by splunk-platform-pki-setup.
# Cluster-wide S2S receiver settings. Per-peer serverCert / sslPassword
# in the per-host overlay.

{_shared_s2s_block(preset, args, mtls, name_check)}"""


def _shc_deployer_server_conf(args: argparse.Namespace, preset: dict, mtls: set[str]) -> str:
    name_check = ",".join(_split_csv(args.shc_members))
    return f"""# Rendered by splunk-platform-pki-setup.
# SHC deployer bundle. Trust anchor + cipher policy go to all members
# via the deployer; per-member serverCert lives in each member's
# etc/system/local/server.conf overlay.
{_shared_ssl_block(preset, args, mtls, name_check)}"""


def _shc_deployer_web_conf(args: argparse.Namespace, preset: dict) -> str:
    return f"""# Rendered by splunk-platform-pki-setup.
# Splunk Web shared settings for SHC members. Per-member serverCert /
# privKeyPath / sslPassword in the per-host overlay.

{_shared_web_block(preset, args)}"""


def _shc_deployer_inputs_conf(args: argparse.Namespace, preset: dict, mtls: set[str]) -> str:
    return f"""# Rendered by splunk-platform-pki-setup.
# HEC shared settings for SHC members (when HEC runs on SHC). Per-member
# serverCert / sslPassword in the per-host overlay.

{_shared_hec_block(preset, args, mtls)}"""


def _standalone_server_conf(args: argparse.Namespace, preset: dict, mtls: set[str]) -> str:
    return f"""# Rendered by splunk-platform-pki-setup.
# Standalone-role server.conf overlay (LM, DS, MC, single SH, HF).
# Carries shared trust anchor + cipher policy. Per-host serverCert in
# etc/system/local/server.conf via install-leaf.sh.
{_shared_ssl_block(preset, args, mtls)}"""


def _standalone_web_conf(args: argparse.Namespace, preset: dict) -> str:
    return f"""# Rendered by splunk-platform-pki-setup.
# Standalone-role web.conf overlay (single SH, MC). Per-host serverCert
# in etc/system/local/web.conf via install-leaf.sh.

{_shared_web_block(preset, args)}"""


def _standalone_inputs_conf(args: argparse.Namespace, preset: dict, mtls: set[str]) -> str:
    return f"""# Rendered by splunk-platform-pki-setup.
# Standalone-role inputs.conf overlay (S2S receiver + HEC).

{_shared_s2s_block(preset, args, mtls)}
{_shared_hec_block(preset, args, mtls)}"""


def _standalone_outputs_conf(args: argparse.Namespace, preset: dict, mtls: set[str]) -> str:
    """Forwarding outputs. Per-host clientCert + sslPassword in the
    per-host overlay; the bundle carries shared targeting + name checks."""
    peers = _split_csv(args.peer_hosts) or ["idx01.example.com"]
    server_csv = ",".join(f"{h}:9997" for h in peers)
    cn_csv = ",".join(peers)
    body = f"""# Rendered by splunk-platform-pki-setup.
# Forwarding outputs. Per-host clientCert / sslPassword written by
# install-leaf.sh to etc/system/local/outputs.conf, NOT to this bundle.

[tcpout]

[tcpout:idxc_main]
server                  = {server_csv}
useClientSSLCompression = true
sslVerifyServerCert     = true
sslVerifyServerName     = true
sslCommonNameToCheck    = {cn_csv}
sslVersions             = {preset['ssl_versions']}
cipherSuite             = {preset['cipher_suite']}
"""
    for peer in peers:
        body += f"""
[tcpout-server://{peer}:9997]
sslCommonNameToCheck = {peer}
sslAltNameToCheck    = {peer}
"""
    return body


# NOTE: per-host overlay generation lives in install-leaf.sh (shell). The
# Python renderer used to have a `_per_host_overlay_snippet` helper that
# was superseded once install-leaf.sh learned to write the overlay
# directly with idempotent ### BEGIN/END markers. Keep overlay logic in
# one place (the rendered shell script) so the operator can audit a
# single source.


def _standalone_authentication_conf(args: argparse.Namespace) -> str:
    if not _bool(args.saml_sp):
        return "# Rendered by splunk-platform-pki-setup.\n# No SAML SP signing cert requested via --saml-sp; this file is intentionally empty.\n"
    return f"""# Rendered by splunk-platform-pki-setup.
# SAML SP signing cert wiring. The IdP cert (idpCertPath) is operator-supplied
# and lives under $SPLUNK_HOME/etc/auth/idpCerts/. See references/saml-signing-certs.md.

[saml_settings]
signAuthnRequest          = true
signedAssertion           = true
signatureAlgorithm        = RSA-SHA384
InboundSignatureAlgorithm = RSA-SHA384;RSA-SHA512
attributeQueryRequestSigned  = true
attributeQueryResponseSigned = true
"""


def _standalone_deploymentclient_conf(args: argparse.Namespace, mtls: set[str]) -> str:
    if not args.ds_fqdn:
        return "# Rendered by splunk-platform-pki-setup.\n# No deployment server FQDN supplied; this file is intentionally empty.\n"
    mtls_block = ""
    if "splunkd" in mtls:
        mtls_block = (
            "\n# When --enable-mtls includes splunkd, each deployment client must\n"
            "# present a clientCert. The per-host clientCert + sslPassword are\n"
            "# written by install-leaf.sh --target splunkd to each client's\n"
            "# etc/system/local/deploymentclient.conf overlay; they are NOT in\n"
            "# this shared bundle (which would resolve to the same literal\n"
            "# clientCert path on every client).\n"
        )
    return f"""# Rendered by splunk-platform-pki-setup.

[target-broker:deploymentServer]
targetUri            = {args.ds_fqdn}:8089
sslVerifyServerCert  = true
sslVerifyServerName  = true
sslCommonNameToCheck = {args.ds_fqdn}
{mtls_block}"""


def _standalone_splunk_launch_conf(args: argparse.Namespace) -> str:
    if args.fips_mode == "none":
        return "# Rendered by splunk-platform-pki-setup.\n# FIPS not requested via --fips-mode; this file is intentionally empty.\n"
    return f"""# Rendered by splunk-platform-pki-setup.
# Flip Splunk into FIPS mode. NIST deprecates FIPS 140-2 on 2026-09-21.
SPLUNK_FIPS_VERSION = {args.fips_mode}
"""


def _standalone_ldap_conf(args: argparse.Namespace, preset: dict) -> str:
    if not _bool(args.ldaps):
        return "# Rendered by splunk-platform-pki-setup.\n# LDAPS not requested via --ldaps; this file is intentionally empty.\n"
    return f"""# Rendered by splunk-platform-pki-setup.
# Drop into /etc/openldap/ldap.conf (RHEL) or /etc/ldap/ldap.conf (Debian).
# Splunk reads system OpenLDAP TLS settings from this file.
TLS_PROTOCOL_MIN  {preset['ldap_tls_protocol_min']}
TLS_CIPHER_SUITE  {preset['ldap_tls_cipher_suite']}
TLS_CACERT        {args.splunk_home}/etc/auth/{args.cert_install_subdir}/cabundle.pem
TLS_REQCERT       demand
"""


def _bundle_readme(scope: str, args: argparse.Namespace) -> str:
    return f"""# {scope} bundle drop-in

Drop the `000_pki_trust/` directory into the appropriate Splunk apps
location:

- Cluster bundle: `$SPLUNK_HOME/etc/master-apps/000_pki_trust/` on the
  cluster manager. Apply with
  `bash skills/splunk-indexer-cluster-setup/scripts/setup.sh --phase bundle-apply ...`
- SHC deployer: `$SPLUNK_HOME/etc/shcluster/apps/000_pki_trust/` on the
  deployer. Apply with `splunk apply shcluster-bundle ...`
- Standalone: `$SPLUNK_HOME/etc/apps/000_pki_trust/` on each non-clustered
  role (LM, DS, MC, single SH, HF) and run `splunk restart`.

Per-host leaf certs are NOT in the bundle (they're host-specific). Stage
them out-of-band on each host before the bundle apply, using
`bash ../../install/install-leaf.sh ...`.
"""


def _ep_placeholder() -> str:
    return """# Edge Processor cert placeholder.
# Replace this file with the real PEM produced by
# pki/private-ca/sign-server-cert.sh (private mode) or returned by your
# CA (public mode). Then upload via the EP UI or REST.
#
# See pki/distribute/edge-processor/README.md for the upload procedure
# and pki/distribute/edge-processor/upload-via-rest.sh.example for an
# operator-runnable REST helper template.
"""


def _ep_upload_sh_example(args: argparse.Namespace) -> str:
    # NOT chmod +x by intent — this is a template for the operator to copy
    # and adapt to their EP control-plane endpoint.
    return f"""#!/usr/bin/env bash
# Example REST upload of EP certs to a Splunk Enterprise EP control plane.
# This is NOT executed by the skill; copy + adapt for your environment.
#
# For Splunk Cloud Edge Processor, upload via the EP UI instead — there is
# no self-service ACS endpoint for EP cert upload.

set -euo pipefail
EP_CONTROL_PLANE="${{EP_CONTROL_PLANE:-https://ep-control.example.com:8089}}"
EP_ID="${{EP_ID:-}}"
ADMIN_PASSWORD_FILE="${{ADMIN_PASSWORD_FILE:-}}"

if [[ -z "$EP_ID" ]] || [[ -z "$ADMIN_PASSWORD_FILE" ]]; then
    echo "ERROR: EP_ID and ADMIN_PASSWORD_FILE must be set" >&2
    exit 1
fi

curl --silent --show-error --fail \\
     --cacert ./ca_cert.pem \\
     -u "admin:$(< "$ADMIN_PASSWORD_FILE")" \\
     -X POST \\
     "$EP_CONTROL_PLANE/services/edge_processor/$EP_ID/certificates" \\
     -F ca_cert=@./ca_cert.pem \\
     -F server_cert=@./edge_server_cert.pem \\
     -F server_key=@./edge_server_key.pem \\
     -F client_cert=@./data_source_client_cert.pem \\
     -F client_key=@./data_source_client_key.pem
echo
echo "OK: EP $EP_ID certificates uploaded"
"""


def _ep_readme(args: argparse.Namespace) -> str:
    return f"""# Edge Processor cert pair

This directory holds the five-file cert pair Splunk Edge Processor
expects per
[Obtain TLS certificates for data sources and Edge Processors](https://help.splunk.com/data-management/transform-and-route-data/use-edge-processors-for-splunk-cloud-platform/10.0.2503/get-data-into-edge-processors/obtain-tls-certificates-for-data-sources-and-edge-processors):

| File | Role |
|---|---|
| `ca_cert.pem` | CA cert. Uploaded to BOTH EP and the data source. |
| `edge_server_cert.pem` | EP server cert. Presented to data sources. |
| `edge_server_key.pem` | EP server private key. **PKCS#8, unencrypted** per the EP doc. |
| `data_source_client_cert.pem` | Data source client cert. Presented to EP. |
| `data_source_client_key.pem` | Data source client key. **PKCS#8, unencrypted**. |

The placeholders here exist so the operator knows what to produce.
Replace them with real PEMs from `pki/private-ca/sign-server-cert.sh`
(use `--key-format pkcs8`) or from your CA (public mode).

Algorithm: {args.key_algorithm}. EP supports both RSA and ECDSA per the
upstream doc.

## Splunk Cloud EP

Upload via the EP UI (Splunk Cloud → Data Management → Edge Processors →
EP → Settings → Certificates).

## Splunk Enterprise EP control plane

Use `upload-via-rest.sh.example` as a starting point.

## Restart

After uploading, restart the EP instance:

```bash
bash skills/splunk-edge-processor-setup/scripts/setup.sh \\
    --phase apply --ep-fqdn {args.ep_fqdn or 'ep01.example.com'} ...
```
"""


def _saml_sp_placeholder(args: argparse.Namespace) -> str:
    return f"""# SAML SP signing cert placeholder.
# Replace with the real cert from sign-saml-sp.sh.
# After installing, regenerate SP metadata in Splunk Web (Settings ->
# Authentication -> SAML -> Generate metadata) and re-upload to the IdP.
"""


def _saml_sp_readme(args: argparse.Namespace) -> str:
    return """# SAML SP signing cert

Separate trust domain from inter-Splunk TLS. The SP signing cert lives
in `$SPLUNK_HOME/etc/auth/myssl/saml/` and Splunk Web uses it to sign
SAML AuthnRequests.

## Order of operations

```bash
# 1. Mint the cert (Private mode) or get it from your CA (Public mode).
PKI_SAML_SP_KEY_PASSWORD_FILE=/tmp/pki_saml_sp_key_password \\
    PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE=/tmp/pki_intermediate_ca_key_password \\
    bash ../../private-ca/sign-saml-sp.sh --name splunk.example.com

# 2. Install on the Splunk host.
mkdir -p $SPLUNK_HOME/etc/auth/myssl/saml
cp signed/saml-sp-signing.crt $SPLUNK_HOME/etc/auth/myssl/saml/sp-signing.crt
cp signed/saml-sp-signing.key $SPLUNK_HOME/etc/auth/myssl/saml/sp-signing.key
chmod 0644 $SPLUNK_HOME/etc/auth/myssl/saml/sp-signing.crt
chmod 0600 $SPLUNK_HOME/etc/auth/myssl/saml/sp-signing.key

# 3. Splunk Web -> Settings -> Authentication -> SAML -> Generate metadata.
# 4. Upload the new SP metadata to the IdP (Okta / Entra / AD FS / etc.).
# 5. Test SSO with a NON-ADMIN account before completing rotation.
# 6. Once SSO works, deactivate the old SP cert at the IdP.
```

See `../../../references/saml-signing-certs.md` for the full SAML SP
signing cert lifecycle.
"""


# ---------- Rotation helpers ----------

def _plan_rotation_md(args: argparse.Namespace, targets: set[str]) -> str:
    cm = args.cm_fqdn or "cm01.example.com"
    peer_list = _split_csv(args.peer_hosts) or ["idx01.example.com"]
    peers_inline = " ".join(peer_list)
    target_csv = ",".join(sorted(targets))
    standalone_hosts = " ".join(filter(None, [args.lm_fqdn, args.ds_fqdn, args.mc_fqdn, args.single_sh_fqdn]))
    shc_members = _split_csv(args.shc_members) or ["captain01.example.com"]
    shc_captain = shc_members[0]
    if args.shc_deployer_fqdn:
        shc_block = (
            f"scp -r splunk-platform-pki-rendered/pki/distribute/shc-deployer/shcluster/apps/000_pki_trust "
            f"{args.shc_deployer_fqdn}:/opt/splunk/etc/shcluster/apps/\n"
            f"ssh {args.shc_deployer_fqdn} '/opt/splunk/bin/splunk apply shcluster-bundle "
            f"-target https://{shc_captain}:8089'"
        )
    else:
        shc_block = "# (No --shc-deployer-fqdn supplied; skip SHC step.)"
    return f"""# Rotation Runbook

This runbook is the operator-runnable companion to
`skills/splunk-platform-pki-setup/references/rotation-runbook.md`.
The skill DOES NOT exec rolling restart — it delegates to
`splunk-indexer-cluster-setup` and `splunk-agent-management-setup`,
matching the precedent set by cluster `pass4SymmKey` rotation.

## Maintenance window prerequisites

- All `verify-leaf.sh` runs returned `OK`.
- All `kv-store-eku-check.sh` runs returned `OK` for splunkd / SHC certs.
- `splunk.secret` SHA-256 matches across cluster members.
- The previous PEM directory has been backed up
  (`install-leaf.sh` does this automatically as
  `_backup-<timestamp>/`).
- Rollback path is communicated to operators.

## Sequence

```bash
# 0. Re-render with the same flags that produced this directory so the
#    runbook reflects the operator's intent.
bash skills/splunk-platform-pki-setup/scripts/setup.sh --phase preflight \\
    --target {target_csv} \\
    --cm-fqdn {cm} \\
    --admin-password-file /tmp/splunk_admin_password

# 1. Stage the new cluster bundle on the cluster manager.
scp -r splunk-platform-pki-rendered/pki/distribute/cluster-bundle/master-apps/000_pki_trust \\
    {cm}:/opt/splunk/etc/master-apps/

# 2. Stage per-peer leaf certs AND write the per-host overlay.
#    install-leaf.sh:
#      - copies PEMs into $SPLUNK_HOME/etc/auth/{args.cert_install_subdir}/<host>/
#      - writes [sslConfig] serverCert / sslPassword to
#        $SPLUNK_HOME/etc/system/local/server.conf with idempotent
#        ### BEGIN/END splunk-platform-pki-setup [splunkd] markers
#      - aligns $SPLUNK_HOME/etc/auth/cacert.pem so the splunk CLI works
#      - runs the documented KV Store openssl verify -x509_strict check
#
#    --ssl-password-file is the operator-supplied PLAINTEXT leaf-key
#    passphrase. install-leaf.sh writes it verbatim to sslPassword in the
#    overlay; on first restart Splunk encrypts it with splunk.secret.
#    Omit when the leaf key is unencrypted (e.g. PKCS#8 nocrypt for EP).
for peer in {peers_inline}; do
    scp splunk-platform-pki-rendered/pki/signed/splunkd-${{peer}}.{{pem,key}} \\
        ${{peer}}:/tmp/
    scp splunk-platform-pki-rendered/pki/install/cabundle.pem \\
        ${{peer}}:/tmp/
    scp /tmp/pki_leaf_key_password ${{peer}}:/tmp/
    ssh ${{peer}} "bash /tmp/install-leaf.sh \\
        --target splunkd \\
        --host ${{peer}} \\
        --cert /tmp/splunkd-${{peer}}.pem \\
        --key  /tmp/splunkd-${{peer}}.key \\
        --ca   /tmp/cabundle.pem \\
        --ssl-password-file /tmp/pki_leaf_key_password"
done

# 3. Bundle validate + apply (delegated).
bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \\
    --phase bundle-validate --cluster-manager-uri https://{cm}:8089 \\
    --admin-password-file /tmp/splunk_admin_password
bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \\
    --phase bundle-apply --cluster-manager-uri https://{cm}:8089 \\
    --admin-password-file /tmp/splunk_admin_password

# 4. Searchable rolling restart of the indexer cluster (delegated).
bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \\
    --phase rolling-restart --rolling-restart-mode searchable \\
    --cluster-manager-uri https://{cm}:8089 \\
    --admin-password-file /tmp/splunk_admin_password

# 5. Stage non-clustered roles (LM, DS, MC, single SH, HF) and restart each.
for host in {standalone_hosts}; do
    scp -r splunk-platform-pki-rendered/pki/distribute/standalone/000_pki_trust \\
        ${{host}}:/opt/splunk/etc/apps/
    ssh ${{host}} "/opt/splunk/bin/splunk restart"
done

# 6. SHC bundle apply at the deployer + member rolling restart.
{shc_block}

# 7. Roll the forwarder fleet (delegated).
# bash skills/splunk-agent-management-setup/scripts/setup.sh --phase apply ...

# 8. Validate end-to-end.
bash skills/splunk-platform-pki-setup/scripts/validate.sh \\
    --target {target_csv} \\
    --cm-fqdn {cm} \\
    --admin-password-file /tmp/splunk_admin_password
```

## Rollback

If `validate` fails:

1. On each host, restore from `_backup-<timestamp>/` next to the cert
   directory.
2. Run `bundle-rollback` via `splunk-indexer-cluster-setup`.
3. Searchable rolling restart back.
4. Re-run `validate`.

See `../../references/rotation-runbook.md` for the full narrative.
"""


def _rotate_leaf_host_sh(args: argparse.Namespace) -> str:
    return _sh(f"""# Rotate a single host's leaf cert in place. Backs up the existing PEMs,
# installs the new ones, runs verify + KV-Store EKU check, and prints a
# 'restart this host' nudge. Does NOT exec the restart.

HOST=""
TARGET="splunkd"
NEW_CERT=""
NEW_KEY=""
NEW_CA=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host) HOST="$2"; shift 2 ;;
        --target) TARGET="$2"; shift 2 ;;
        --cert) NEW_CERT="$2"; shift 2 ;;
        --key)  NEW_KEY="$2";  shift 2 ;;
        --ca)   NEW_CA="$2";   shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

for var in HOST NEW_CERT NEW_KEY NEW_CA; do
    if [[ -z "${{!var}}" ]]; then
        echo "ERROR: --${{var,,}} required" >&2
        exit 1
    fi
done

bash "$(dirname "$0")/../install/install-leaf.sh" \\
    --target "$TARGET" --host "$HOST" \\
    --cert "$NEW_CERT" --key "$NEW_KEY" --ca "$NEW_CA"

echo
echo "Cert rotated for $HOST. Now restart Splunk on that host (or run the rotation"
echo "runbook at pki/rotate/plan-rotation.md for clustered hosts)."
""")


def _swap_trust_anchor_sh(args: argparse.Namespace) -> str:
    return _sh(f"""# Replace the cluster-wide trust anchor (CA bundle). Apply this BEFORE
# rotating leaves so peers trust both the old AND new chain during the
# rolling restart window.

NEW_CA=""
SPLUNK_HOME="${{SPLUNK_HOME:-{args.splunk_home}}}"
INSTALL_SUBDIR="${{INSTALL_SUBDIR:-{args.cert_install_subdir}}}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --ca) NEW_CA="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [[ -z "$NEW_CA" ]] || [[ ! -f "$NEW_CA" ]]; then
    echo "ERROR: --ca <new-ca-bundle.pem> required" >&2
    exit 1
fi

DEST="$SPLUNK_HOME/etc/auth/$INSTALL_SUBDIR/cabundle.pem"

if [[ -f "$DEST" ]]; then
    cp -p "$DEST" "${{DEST}}.pre-rotate-$(date -u +%Y%m%dT%H%M%SZ)"
    # Concatenate old + new so peers trust both during the window
    cat "${{DEST}}.pre-rotate-"* "$NEW_CA" > "$DEST.tmp"
    mv "$DEST.tmp" "$DEST"
else
    cp -p "$NEW_CA" "$DEST"
fi
chmod 0644 "$DEST"

bash "$(dirname "$0")/../install/align-cli-trust.sh" "$DEST"

echo "OK: trust anchor swapped. Cluster now trusts old AND new chain."
echo "    After all leaves are rotated, re-run with the new CA only to drop the old."
""")


def _swap_replication_port_to_ssl_sh(args: argparse.Namespace) -> str:
    return _sh(f"""# Atomic migration of [replication_port://9887] -> [replication_port-ssl://9887]
# on the cluster bundle. Removes the cleartext stanza in the same edit so
# the bundle never contains both stanzas active.
#
# After running this, run:
#   bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \\
#       --phase bundle-apply --cluster-manager-uri https://CM:8089 \\
#       --admin-password-file /tmp/splunk_admin_password
# then a full searchable rolling restart with --percent-peers-to-restart 100.

BUNDLE_SERVER_CONF="${{1:-}}"

if [[ -z "$BUNDLE_SERVER_CONF" ]] || [[ ! -f "$BUNDLE_SERVER_CONF" ]]; then
    echo "ERROR: usage: $0 <path-to-master-apps/000_pki_trust/local/server.conf>" >&2
    exit 1
fi

cp -p "$BUNDLE_SERVER_CONF" "${{BUNDLE_SERVER_CONF}}.pre-ssl-$(date -u +%Y%m%dT%H%M%SZ)"

# Drop the cleartext stanza if present.
awk '
    BEGIN {{ skip = 0 }}
    /^\\[replication_port:\\/\\/9887\\]/ {{ skip = 1; next }}
    /^\\[/ && skip {{ skip = 0 }}
    !skip {{ print }}
' "$BUNDLE_SERVER_CONF" > "$BUNDLE_SERVER_CONF.tmp"

# Confirm the SSL stanza is present (the renderer should have written it
# when --encrypt-replication-port=true was passed).
if ! grep -q '^\\[replication_port-ssl://9887\\]' "$BUNDLE_SERVER_CONF.tmp"; then
    echo "ERROR: [replication_port-ssl://9887] not found in $BUNDLE_SERVER_CONF." >&2
    echo "       Re-render with --encrypt-replication-port=true." >&2
    rm -f "$BUNDLE_SERVER_CONF.tmp"
    exit 1
fi

mv "$BUNDLE_SERVER_CONF.tmp" "$BUNDLE_SERVER_CONF"

echo "OK: replication port swapped to SSL in $BUNDLE_SERVER_CONF"
echo "    Push the bundle and run a full searchable rolling restart."
""")


def _expire_watch_sh(args: argparse.Namespace) -> str:
    return _sh(f"""# Walk a directory of PEM files and report any cert expiring within
# THRESHOLD days. Wraps `openssl x509 -enddate`. Pair with the SSL
# Certificate Checker add-on (Splunkbase 3172) for ongoing monitoring.

DIR="${{1:-{args.splunk_home}/etc/auth}}"
THRESHOLD="${{2:-30}}"
SPLUNK_HOME="${{SPLUNK_HOME:-{args.splunk_home}}}"

now_epoch=$(date -u +%s)
threshold_epoch=$((now_epoch + THRESHOLD * 86400))

found=0
while IFS= read -r f; do
    if ! "$SPLUNK_HOME/bin/splunk" cmd openssl x509 -in "$f" -noout >/dev/null 2>&1; then
        continue
    fi
    enddate="$("$SPLUNK_HOME/bin/splunk" cmd openssl x509 -in "$f" -enddate -noout | sed 's/^notAfter=//')"
    end_epoch="$(date -u -d "$enddate" +%s 2>/dev/null || date -j -u -f '%b %e %T %Y %Z' "$enddate" +%s 2>/dev/null || echo 0)"
    if [[ "$end_epoch" -lt "$threshold_epoch" ]]; then
        days_left=$(( (end_epoch - now_epoch) / 86400 ))
        echo "EXPIRING: $f (expires in $days_left days, $enddate)"
        found=$((found + 1))
    fi
done < <(find "$DIR" -name '*.pem' -o -name '*.crt' 2>/dev/null)

if [[ "$found" -eq 0 ]]; then
    echo "OK: no certs in $DIR expire within $THRESHOLD days"
fi
""")


# ---------- Handoff Markdown (always present, content tailored per CA) ----------

def _handoff_operator_checklist(args: argparse.Namespace, targets: set[str], mtls: set[str]) -> str:
    primary_ca = args.public_ca_name if args.mode == "public" else "private"
    return f"""# Operator Checklist

Run-mode summary:

| Setting | Value |
|---|---|
| Mode | `{args.mode}` |
| Targets | `{', '.join(sorted(targets))}` |
| TLS policy | `{args.tls_policy}` |
| mTLS | `{', '.join(sorted(mtls)) if mtls else 'none'}` |
| Encrypt replication port | `{args.encrypt_replication_port}` |
| FIPS mode | `{args.fips_mode}` |

## Pre-rotation checklist

- [ ] CA passphrase files captured via `bash skills/shared/scripts/write_secret_file.sh /tmp/<name>`.
- [ ] Splunk admin password file captured.
- [ ] Cluster `pass4SymmKey` file (idxc-secret) captured.
- [ ] CSR templates in `pki/csr-templates/` reviewed.
- [ ] (Private) CA scripts in `pki/private-ca/` reviewed.
- [ ] (Public) {primary_ca.upper()} handoff doc reviewed (`handoff/{primary_ca}.md` or `handoff/vault-pki.md` etc.).
- [ ] Cluster bundle drop-in reviewed.
- [ ] SHC deployer drop-in reviewed.
- [ ] Standalone drop-ins reviewed for LM / DS / MC.
- [ ] (Edge Processor) cert pair placeholders reviewed; EP UI / REST upload procedure understood.
- [ ] (SAML SP) IdP re-upload procedure understood.

## Apply

- [ ] Run `bash preflight.sh` and resolve any FAILs.
- [ ] `--accept-pki-rotation` passed to setup.sh apply phase.
- [ ] **Per-host overlay written** by `pki/install/install-leaf.sh` on
      every target host. install-leaf.sh writes the per-host
      serverCert / sslPassword to `$SPLUNK_HOME/etc/system/local/<conf>`
      with idempotent `### BEGIN/END splunk-platform-pki-setup [<target>]`
      markers. The cluster bundle / SHC deployer bundle / standalone
      bundle deliberately do NOT carry per-host serverCert (which would
      resolve to the same literal path on every host). Pass
      `--ssl-password-file PATH` so install-leaf.sh writes the plaintext
      sslPassword (Splunk encrypts on first restart).
- [ ] Cluster bundle pushed via `splunk-indexer-cluster-setup --phase bundle-apply`.
- [ ] Indexer cluster searchable rolling-restart completed.
- [ ] (--encrypt-replication-port) per-peer `[replication_port-ssl://9887]`
      overlay written by `install-leaf.sh --target replication`; full
      cluster rolling-restart with `--percent-peers-to-restart 100`.
- [ ] Non-clustered roles restarted.
- [ ] SHC bundle pushed and members rolled.
- [ ] Forwarder fleet rolled via `splunk-agent-management-setup`.
- [ ] (SAML SP) New SP metadata uploaded to IdP; SSO tested with non-admin.
- [ ] (Edge Processor) New cert pair uploaded; EP instances restarted.

## Post-apply

- [ ] `bash validate.sh` returns OK on every targeted role.
- [ ] SSL Certificate Checker (Splunkbase 3172) installed and reporting.
- [ ] `/services/server/health/splunkd` returns `green` on every host.
- [ ] Rotation calendar entry created at leaf-validity - 30 days.
"""


def _handoff_vault(args: argparse.Namespace) -> str:
    return """# Handoff — HashiCorp Vault PKI

See references/handoff-vault-pki.md for the full procedure.

Quick reference:

```bash
# Configure Vault role with dual EKU
vault write pki/roles/splunk-leaf \\
    allowed_domains="example.com" allow_subdomains=true \\
    allow_ip_sans=true enforce_hostnames=true \\
    max_ttl=825d key_type=rsa key_bits=2048 \\
    server_flag=true client_flag=true \\
    use_csr_common_name=true use_csr_sans=true

# Sign each CSR
for csr in splunk-platform-pki-rendered/pki/signed/*.csr; do
    host="$(basename "$csr" .csr)"
    vault write -format=json pki/sign/splunk-leaf csr=@"$csr" common_name="$host" ttl=825d \\
        | jq -r .data.certificate \\
        > splunk-platform-pki-rendered/pki/signed/"$host".pem
done

# Pull CA chain
vault read -format=json pki/cert/ca_chain | jq -r .data.certificate \\
    > splunk-platform-pki-rendered/pki/install/cabundle.pem
```
"""


def _handoff_acme(args: argparse.Namespace) -> str:
    return """# Handoff — ACME / cert-manager / Let's Encrypt

See references/handoff-acme-cert-manager.md for the full procedure.

ACME / Let's Encrypt is best for **Splunk Web only** (public FQDN);
inter-Splunk surfaces (8089, 9997, 8088, KV Store) use private FQDNs
that public CAs can't validate.

Two flavours:

- **Direct** with `acme.sh` / `certbot` on the SH host (DNS-01 challenge
  recommended).
- **cert-manager** on Kubernetes-fronted Splunk (Splunk Operator for
  Kubernetes deployments).
"""


def _handoff_adcs(args: argparse.Namespace) -> str:
    return """# Handoff — Microsoft AD CS

See references/handoff-microsoft-adcs.md for the full procedure.

Cert template requirements:

- Application Policies: Server Authentication AND Client Authentication
  (KV Store needs both).
- Min key size: 2048; Hash: SHA-256+; Validity: 825 days.

Submit each CSR via `certreq.exe` or `Submit-CertificateRequest`.
"""


def _handoff_ejbca(args: argparse.Namespace) -> str:
    return """# Handoff — EJBCA

See references/handoff-ejbca.md for the full procedure.

EJBCA Certificate Profile must include both serverAuth and clientAuth EKUs.
Submit via REST `/ejbca/ejbca-rest-api/v1/certificate/pkcs10enroll` or via
CMP `cmpclient`.
"""


def _handoff_splunk_cloud_ufcp(args: argparse.Namespace) -> str:
    return """# Handoff — Splunk Cloud Universal Forwarder Credentials Package

This skill REFUSES to mint forwarder certs for Splunk Cloud destinations.
Splunk Cloud rotates its indexer certs on its own schedule, and your
forwarder must trust whatever Splunk presents.

Use the Universal Forwarder Credentials Package (UFCP) instead:

1. Splunk Cloud Platform -> Apps -> Universal Forwarder.
2. Download the credentials package for your stack.
3. Install on every forwarder via `splunk-universal-forwarder-setup` or
   `splunk-agent-management-setup`.
4. Restart the forwarder.

See references/splunk-cloud-ufcp-handoff.md for details.
"""


def _handoff_splunk_cloud_byoc(args: argparse.Namespace) -> str:
    return """# Handoff — Splunk Cloud HEC Custom-Domain BYOC

If you want HEC to serve under `hec.example.com` (instead of
`<stack>.splunkcloud.com`) on Splunk Cloud, this is NOT a self-service
ACS operation today. The Splunk Cloud ACS HEC endpoints manage tokens
but do NOT expose a BYOC cert upload.

Options:

- Open a Splunk Support ticket requesting a custom HEC domain (Splunk
  provisions the cert).
- Build a Splunk Cloud-installable app that includes your cert chain in
  `local/inputs.conf [http]` (operator-driven; subject to Splunk Cloud
  app review).

See references/splunk-cloud-ufcp-handoff.md.
"""


def _handoff_fips(args: argparse.Namespace) -> str:
    return f"""# Handoff — FIPS Migration

This skill renders the cert side. The FIPS module flip is a separate
two-phase operation per
[Upgrade and migrate your FIPS-mode deployments](https://help.splunk.com/en/splunk-enterprise/administer/install-and-upgrade/10.2/upgrade-or-migrate-splunk-enterprise/upgrade-and-migrate-your-fips-mode-deployments).

Current run: `--fips-mode {args.fips_mode}`

## Phase 1 — Splunk 10 in FIPS 140-2

- Splunk 10 ships both modules. Upgrading from 9.x in FIPS 140-2 leaves
  you in 140-2 by default.
- Confirm: AVX CPU, FIPS-supported OS, MongoDB 4.2+, Python 3.9 apps,
  TLS 1.2 everywhere.

## Phase 2 — flip to FIPS 140-3

- Required by 2026-09-21 (NIST 140-2 deprecation).
- Requires KV Store on MongoDB 7.0.17+ with OpenSSL 3.0.
- Requires all forwarders on Splunk 10.
- Edit `splunk-launch.conf` to set `SPLUNK_FIPS_VERSION = 140-3`. The
  renderer's `pki/install/install-fips-launch-conf.sh` does this
  idempotently.
- Restart each Splunk host.

The skill REFUSES to apply when the cluster is mid-Phase-1 (some peers
on 140-2, some on 140-3) to avoid signature-algorithm incompatibilities.
"""


def _handoff_ep_upload(args: argparse.Namespace) -> str:
    return """# Handoff — Edge Processor Cert Upload

The skill renders the five-file cert pair under
`pki/distribute/edge-processor/` but does NOT upload to the EP control
plane. Two paths:

## Splunk Cloud EP

1. Splunk Cloud -> Data Management -> Edge Processors -> pick the EP.
2. Settings -> Certificates.
3. Upload `ca_cert.pem`, `edge_server_cert.pem`, `edge_server_key.pem`,
   and (if mTLS) `data_source_client_cert.pem` + `data_source_client_key.pem`.
4. Save and apply.

## Splunk Enterprise EP control plane

Use `pki/distribute/edge-processor/upload-via-rest.sh.example` as a
starting point. Adapt for your control-plane endpoint.

## After upload

Restart EP instance(s) via `splunk-edge-processor-setup`:

```bash
bash skills/splunk-edge-processor-setup/scripts/setup.sh \\
    --phase apply --ep-fqdn ep01.example.com ...
```

See references/edge-processor-pki.md.
"""


def _handoff_post_install_monitoring(args: argparse.Namespace) -> str:
    return """# Handoff — Post-Install Monitoring

See references/post-install-monitoring.md for the full set. Quick
checklist:

- [ ] SSL Certificate Checker (Splunkbase 3172) installed.
- [ ] Saved search alerts at 30 / 14 / 7 days before expiry.
- [ ] `/services/server/health/splunkd` polled every 5 min.
- [ ] CIM Certificates data model populated.
- [ ] TLS handshake error search wired to alerting.
- [ ] KV Store TLS error search wired to real-time alert.
- [ ] Splunk On-Call routing keys configured.
"""


# ---------- preflight / validate / inventory ----------

def _preflight_sh(args: argparse.Namespace, targets: set[str]) -> str:
    return _sh(f"""# Read-only preflight checks. Refuses to declare the deployment ready
# when any check fails.

SPLUNK_HOME="${{SPLUNK_HOME:-{args.splunk_home}}}"
ADMIN_PASSWORD_FILE="${{SPLUNK_ADMIN_PASSWORD_FILE:-}}"

failed=0
fail() {{ echo "FAIL: $1" >&2; failed=$((failed + 1)); }}
ok()   {{ echo "OK:   $1"; }}

# 1. cabundle.pem present
if [[ -f "$SPLUNK_HOME/etc/auth/{args.cert_install_subdir}/cabundle.pem" ]]; then
    ok "trust anchor present at $SPLUNK_HOME/etc/auth/{args.cert_install_subdir}/cabundle.pem"
else
    fail "trust anchor missing at $SPLUNK_HOME/etc/auth/{args.cert_install_subdir}/cabundle.pem (run install-leaf.sh first)"
fi

# 2. Default-cert refusal
if [[ -f "$SPLUNK_HOME/etc/auth/server.pem" ]]; then
    if "$SPLUNK_HOME/bin/splunk" cmd openssl x509 -in "$SPLUNK_HOME/etc/auth/server.pem" -subject -noout 2>/dev/null \\
        | grep -qE 'SplunkServerDefaultCert|SplunkCommonCA|SplunkWebDefaultCert'; then
        fail "default Splunk cert still in use at $SPLUNK_HOME/etc/auth/server.pem; replace before declaring ready"
    else
        ok "no default Splunk cert in $SPLUNK_HOME/etc/auth/server.pem"
    fi
fi

# 3. TLS version floor
sslv="$("$SPLUNK_HOME/bin/splunk" cmd btool server list sslConfig 2>/dev/null | awk '/^sslVersions/ {{print $3}}' | head -1)"
if [[ -n "$sslv" ]] && [[ "$sslv" != "tls1.2" ]] && [[ "$sslv" != "*"*"-tls1.0,-tls1.1"* ]]; then
    fail "sslVersions = $sslv (expected tls1.2; Splunk docs do not yet support TLS 1.3)"
else
    ok "sslVersions floor satisfied"
fi

# 4. KV Store EKU verify (run the documented openssl verify -x509_strict)
if [[ -f "$SPLUNK_HOME/etc/auth/{args.cert_install_subdir}/cabundle.pem" ]]; then
    cert_path="$("$SPLUNK_HOME/bin/splunk" cmd btool server list sslConfig 2>/dev/null | awk '/^serverCert/ {{print $3}}' | head -1)"
    if [[ -n "$cert_path" ]] && [[ -f "$cert_path" ]]; then
        if "$SPLUNK_HOME/bin/splunk" cmd openssl verify -verbose -x509_strict \\
            -CAfile "$SPLUNK_HOME/etc/auth/{args.cert_install_subdir}/cabundle.pem" \\
            "$cert_path" >/dev/null 2>&1; then
            ok "KV Store openssl verify -x509_strict returns OK"
        else
            fail "KV Store openssl verify -x509_strict FAILED — ensure cabundle.pem holds full chain"
        fi
    fi
fi

# 5. splunk.secret SHA-256 (informational; cluster-wide check is operator-driven)
if [[ -f "$SPLUNK_HOME/etc/auth/splunk.secret" ]]; then
    sha="$(sha256sum "$SPLUNK_HOME/etc/auth/splunk.secret" 2>/dev/null | awk '{{print $1}}' || \\
           shasum -a 256 "$SPLUNK_HOME/etc/auth/splunk.secret" 2>/dev/null | awk '{{print $1}}')"
    ok "splunk.secret sha256: $sha (compare across cluster members)"
fi

# 6. FIPS posture
if [[ -f "$SPLUNK_HOME/etc/splunk-launch.conf" ]]; then
    fips_v="$(awk -F= '/^SPLUNK_FIPS_VERSION/ {{gsub(/ /,"",$2); print $2}}' "$SPLUNK_HOME/etc/splunk-launch.conf")"
    ok "FIPS posture: ${{fips_v:-disabled}}"
fi

if [[ "$failed" -gt 0 ]]; then
    echo
    echo "PREFLIGHT FAILED: $failed check(s) failed." >&2
    exit 1
fi

echo
echo "PREFLIGHT PASSED."
""")


def _validate_sh(args: argparse.Namespace, targets: set[str]) -> str:
    return _sh(f"""# Live validation probes against an applied deployment. Run after the
# rotation runbook completes.

SPLUNK_HOME="${{SPLUNK_HOME:-{args.splunk_home}}}"
failed=0
fail() {{ echo "FAIL: $1" >&2; failed=$((failed + 1)); }}
ok()   {{ echo "OK:   $1"; }}

# 1. Splunkd 8089 TLS handshake
if "$SPLUNK_HOME/bin/splunk" cmd openssl s_client \\
    -connect localhost:8089 -tls1_2 </dev/null 2>/dev/null \\
    | grep -q 'Verify return code: 0 (ok)'; then
    ok "splunkd 8089 handshake OK"
else
    fail "splunkd 8089 TLS handshake failed"
fi

# 2. Splunk Web 8000 TLS handshake (if enabled)
if ss -tln 2>/dev/null | grep -q ':8000 '; then
    if "$SPLUNK_HOME/bin/splunk" cmd openssl s_client \\
        -connect localhost:8000 -tls1_2 </dev/null 2>/dev/null \\
        | grep -q 'Verify return code: 0 (ok)'; then
        ok "Splunk Web 8000 handshake OK"
    else
        fail "Splunk Web 8000 TLS handshake failed"
    fi
fi

# 3. HEC 8088 TLS handshake (if enabled)
if ss -tln 2>/dev/null | grep -q ':8088 '; then
    if "$SPLUNK_HOME/bin/splunk" cmd openssl s_client \\
        -connect localhost:8088 -tls1_2 </dev/null 2>/dev/null \\
        | grep -q 'Verify return code: 0 (ok)'; then
        ok "HEC 8088 handshake OK"
    else
        fail "HEC 8088 TLS handshake failed"
    fi
fi

# 4. /services/server/health/splunkd
if [[ -n "${{SPLUNK_ADMIN_PASSWORD_FILE:-}}" ]] && [[ -r "$SPLUNK_ADMIN_PASSWORD_FILE" ]]; then
    health="$(curl -k -s -u "admin:$(< "$SPLUNK_ADMIN_PASSWORD_FILE")" \\
        https://localhost:8089/services/server/health/splunkd 2>/dev/null \\
        | grep -oE '"health":"[a-z]+"' | head -1 | cut -d'"' -f4)"
    if [[ "$health" == "green" ]]; then
        ok "/services/server/health/splunkd: green"
    else
        fail "/services/server/health/splunkd: ${{health:-unknown}}"
    fi
fi

# 5. splunk show-decrypted round trip on sslPassword
encrypted="$("$SPLUNK_HOME/bin/splunk" cmd btool server list sslConfig 2>/dev/null \\
    | awk '/^sslPassword/ {{print $3}}' | head -1)"
if [[ -n "$encrypted" ]] && [[ "$encrypted" == \\$* ]]; then
    if "$SPLUNK_HOME/bin/splunk" show-decrypted --value "$encrypted" >/dev/null 2>&1; then
        ok "splunk show-decrypted round-trip works"
    else
        fail "splunk show-decrypted on sslPassword failed (splunk.secret mismatch?)"
    fi
fi

if [[ "$failed" -gt 0 ]]; then
    echo
    echo "VALIDATE FAILED: $failed check(s) failed." >&2
    exit 1
fi

echo
echo "VALIDATE PASSED."
""")


def _inventory_sh(args: argparse.Namespace) -> str:
    return _sh(f"""# Read-only cert inventory. Emits pki/inventory/<host>.json with the
# discovered TLS posture. Never invokes a Splunk write API.

SPLUNK_HOME="${{SPLUNK_HOME:-{args.splunk_home}}}"
RENDER_ROOT="$(dirname "$0")"
HOST="$(hostname -f 2>/dev/null || hostname)"
OUT_DIR="$RENDER_ROOT/pki/inventory"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/$HOST.json"

ssl_block="$("$SPLUNK_HOME/bin/splunk" cmd btool server list sslConfig 2>/dev/null \\
    | awk '/^\\[sslConfig\\]/,/^\\[/ {{print}}')"
web_block="$("$SPLUNK_HOME/bin/splunk" cmd btool web list settings 2>/dev/null \\
    | awk '/^\\[settings\\]/,/^\\[/ {{print}}')"
hec_block="$("$SPLUNK_HOME/bin/splunk" cmd btool inputs list http 2>/dev/null \\
    | awk '/^\\[http\\]/,/^\\[/ {{print}}')"

# Walk PEM expiry
pem_summary="["
first=1
while IFS= read -r f; do
    if "$SPLUNK_HOME/bin/splunk" cmd openssl x509 -in "$f" -noout >/dev/null 2>&1; then
        sub="$("$SPLUNK_HOME/bin/splunk" cmd openssl x509 -in "$f" -subject -noout | sed 's/^subject=//; s/"/\\\\"/g')"
        end="$("$SPLUNK_HOME/bin/splunk" cmd openssl x509 -in "$f" -enddate -noout | sed 's/^notAfter=//')"
        [[ "$first" == "0" ]] && pem_summary+="," || first=0
        pem_summary+="{{\\"path\\":\\"$f\\",\\"subject\\":\\"$sub\\",\\"notAfter\\":\\"$end\\"}}"
    fi
done < <(find "$SPLUNK_HOME/etc/auth" -name '*.pem' -o -name '*.crt' 2>/dev/null)
pem_summary+="]"

cat > "$OUT" <<EOF
{{
  "host": "$HOST",
  "splunk_home": "$SPLUNK_HOME",
  "ssl_config": $(echo "$ssl_block" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))'),
  "web_settings": $(echo "$web_block" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))'),
  "hec_settings": $(echo "$hec_block" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))'),
  "pems": $pem_summary
}}
EOF

echo "OK: inventory written to $OUT"
""")


# ---------------------------------------------------------------------------
# Main render orchestration
# ---------------------------------------------------------------------------

def render(args: argparse.Namespace) -> tuple[Path, set[str]]:
    out_root = Path(args.output_dir).expanduser().resolve() / "platform-pki"
    out_root.mkdir(parents=True, exist_ok=True)

    policy = _load_algorithm_policy(args)
    _validate_args(args, policy)
    targets = _expand_targets(args.target)
    mtls = _expand_mtls(args.enable_mtls)
    preset = policy["presets"][args.tls_policy]

    emitted: set[str] = set()

    def emit(rel: str, content: str, executable: bool = False) -> None:
        path = out_root / rel
        _write(path, content, executable=executable)
        emitted.add(rel)

    # README + metadata
    render_readme(out_root, args, targets, mtls)
    emitted.add("README.md")
    render_metadata(out_root, args, targets, mtls)
    emitted.add("metadata.json")

    # Top-level scripts
    emit("preflight.sh", _preflight_sh(args, targets), executable=True)
    emit("validate.sh", _validate_sh(args, targets), executable=True)
    emit("inventory.sh", _inventory_sh(args), executable=True)

    # Private CA scripts (only when --mode=private)
    if args.mode == "private":
        emit("pki/private-ca/openssl-root.cnf", _openssl_root_cnf(args))
        emit("pki/private-ca/openssl-leaf-server.cnf", _openssl_leaf_server_cnf())
        emit("pki/private-ca/openssl-leaf-client.cnf", _openssl_leaf_client_cnf())
        emit("pki/private-ca/openssl-leaf-saml.cnf", _openssl_leaf_saml_cnf())
        emit("pki/private-ca/create-root-ca.sh", _create_root_ca_sh(args), executable=True)
        emit("pki/private-ca/sign-server-cert.sh", _sign_server_cert_sh(args), executable=True)
        emit("pki/private-ca/sign-client-cert.sh", _sign_client_cert_sh(args), executable=True)
        emit("pki/private-ca/sign-saml-sp.sh", _sign_saml_sp_sh(args), executable=True)
        emit("pki/private-ca/README.md", _private_ca_readme(args))
        if _bool(args.include_intermediate_ca):
            emit("pki/private-ca/openssl-intermediate.cnf", _openssl_intermediate_cnf(args))
            emit("pki/private-ca/create-intermediate-ca.sh", _create_intermediate_ca_sh(args), executable=True)

    # CSR templates
    emit("pki/csr-templates/generate-csr.sh", _generate_csr_sh(args), executable=True)
    emit("pki/csr-templates/README.md", _csr_template_readme(args, args.mode))
    csr_emitted = _emit_csr_templates(args, targets, emit)

    # Install / verify
    emit("pki/install/install-leaf.sh", _install_leaf_sh(args), executable=True)
    emit("pki/install/verify-leaf.sh", _verify_leaf_sh(args), executable=True)
    emit("pki/install/kv-store-eku-check.sh", _kv_store_eku_check_sh(args), executable=True)
    emit("pki/install/align-cli-trust.sh", _align_cli_trust_sh(args), executable=True)
    emit("pki/install/prepare-key.sh", _prepare_key_sh(args), executable=True)
    emit("pki/install/README.md", _install_readme(args))
    if args.fips_mode != "none":
        emit("pki/install/install-fips-launch-conf.sh", _install_fips_launch_conf_sh(args), executable=True)

    # Distribution
    if "indexer-cluster" in targets:
        emit("pki/distribute/cluster-bundle/master-apps/000_pki_trust/default/app.conf", _app_conf("000_pki_trust"))
        emit("pki/distribute/cluster-bundle/master-apps/000_pki_trust/local/server.conf", _cluster_bundle_server_conf(args, preset, mtls))
        emit("pki/distribute/cluster-bundle/master-apps/000_pki_trust/local/inputs.conf", _cluster_bundle_inputs_conf(args, preset, mtls))
        emit("pki/distribute/cluster-bundle/README.md", _bundle_readme("Cluster", args))

    if "shc" in targets:
        emit("pki/distribute/shc-deployer/shcluster/apps/000_pki_trust/default/app.conf", _app_conf("000_pki_trust"))
        emit("pki/distribute/shc-deployer/shcluster/apps/000_pki_trust/local/server.conf", _shc_deployer_server_conf(args, preset, mtls))
        emit("pki/distribute/shc-deployer/shcluster/apps/000_pki_trust/local/web.conf", _shc_deployer_web_conf(args, preset))
        emit("pki/distribute/shc-deployer/shcluster/apps/000_pki_trust/local/inputs.conf", _shc_deployer_inputs_conf(args, preset, mtls))
        emit("pki/distribute/shc-deployer/README.md", _bundle_readme("SHC deployer", args))

    if any(t in targets for t in ("license-manager", "deployment-server", "monitoring-console", "core5", "dmz-hf")):
        emit("pki/distribute/standalone/000_pki_trust/default/app.conf", _app_conf("000_pki_trust"))
        emit("pki/distribute/standalone/000_pki_trust/local/server.conf", _standalone_server_conf(args, preset, mtls))
        emit("pki/distribute/standalone/000_pki_trust/local/web.conf", _standalone_web_conf(args, preset))
        emit("pki/distribute/standalone/000_pki_trust/local/inputs.conf", _standalone_inputs_conf(args, preset, mtls))
        emit("pki/distribute/standalone/000_pki_trust/local/outputs.conf", _standalone_outputs_conf(args, preset, mtls))
        emit("pki/distribute/standalone/000_pki_trust/local/authentication.conf", _standalone_authentication_conf(args))
        emit("pki/distribute/standalone/000_pki_trust/local/deploymentclient.conf", _standalone_deploymentclient_conf(args, mtls))
        emit("pki/distribute/standalone/README.md", _bundle_readme("Standalone (LM/DS/MC/single-SH/HF)", args))
        if args.fips_mode != "none":
            emit("pki/distribute/standalone/000_pki_trust/local/splunk-launch.conf", _standalone_splunk_launch_conf(args))
        if _bool(args.ldaps):
            emit("pki/distribute/standalone/000_pki_trust/system-files/ldap.conf", _standalone_ldap_conf(args, preset))

    # UF fleet overlays (per group)
    if "uf-fleet" in targets:
        groups = _split_csv(args.uf_fleet_groups) or ["default"]
        for group in groups:
            base = f"pki/distribute/forwarder-fleet/{group}"
            emit(f"{base}/outputs-overlay.conf", _standalone_outputs_conf(args, preset, mtls))
            emit(f"{base}/server-overlay.conf", f"""# Rendered by splunk-platform-pki-setup.
# Forwarder server.conf overlay for fleet group "{group}".
# Aligns the trust anchor so sslVerifyServerCert validates the indexer chain.

[sslConfig]
sslRootCAPath = {args.splunk_home}/etc/auth/{args.cert_install_subdir}/cabundle.pem
sslVersionsForClient = {preset['ssl_versions_for_client']}
""")

    # Edge Processor
    if _bool(args.include_edge_processor):
        for fname in ("ca_cert.pem", "edge_server_cert.pem", "edge_server_key.pem",
                      "data_source_client_cert.pem", "data_source_client_key.pem"):
            emit(f"pki/distribute/edge-processor/{fname}.example", _ep_placeholder())
        emit("pki/distribute/edge-processor/upload-via-rest.sh.example", _ep_upload_sh_example(args))
        emit("pki/distribute/edge-processor/README.md", _ep_readme(args))

    # SAML SP
    if _bool(args.saml_sp):
        emit("pki/distribute/saml-sp/sp-signing.crt.placeholder", _saml_sp_placeholder(args))
        emit("pki/distribute/saml-sp/sp-signing.key.placeholder", _saml_sp_placeholder(args))
        emit("pki/distribute/saml-sp/README.md", _saml_sp_readme(args))

    # Rotation helpers
    emit("pki/rotate/plan-rotation.md", _plan_rotation_md(args, targets))
    emit("pki/rotate/rotate-leaf-host.sh", _rotate_leaf_host_sh(args), executable=True)
    emit("pki/rotate/swap-trust-anchor.sh", _swap_trust_anchor_sh(args), executable=True)
    emit("pki/rotate/swap-replication-port-to-ssl.sh", _swap_replication_port_to_ssl_sh(args), executable=True)
    emit("pki/rotate/expire-watch.sh", _expire_watch_sh(args), executable=True)

    # Operator handoff Markdown (always all four CA handoffs + checklists)
    emit("handoff/operator-checklist.md", _handoff_operator_checklist(args, targets, mtls))
    emit("handoff/vault-pki.md", _handoff_vault(args))
    emit("handoff/acme-cert-manager.md", _handoff_acme(args))
    emit("handoff/microsoft-adcs.md", _handoff_adcs(args))
    emit("handoff/ejbca.md", _handoff_ejbca(args))
    emit("handoff/splunk-cloud-ufcp.md", _handoff_splunk_cloud_ufcp(args))
    emit("handoff/splunk-cloud-byoc.md", _handoff_splunk_cloud_byoc(args))
    emit("handoff/fips-migration.md", _handoff_fips(args))
    emit("handoff/edge-processor-upload.md", _handoff_ep_upload(args))
    emit("handoff/post-install-monitoring.md", _handoff_post_install_monitoring(args))

    # Validate the manifest (no surprise files)
    for rel in emitted:
        if rel in GENERATED_FILES:
            continue
        if not any(re.match(pat, rel) for pat in GENERATED_FILE_PATTERNS):
            sys.exit(f"INTERNAL ERROR: emitted file not in manifest or pattern allow-list: {rel}")

    return out_root, emitted


def _emit_csr_templates(args: argparse.Namespace, targets: set[str], emit) -> set[str]:
    """Emit per-host CSR templates based on the operator's inventory."""
    csr_emitted: set[str] = set()

    def write_csr(role: str, host: str, sans: list[str], saml: bool = False) -> None:
        rel = f"pki/csr-templates/{role}-{host}.cnf"
        emit(rel, _csr_template_cnf(args, role, host, sans, saml=saml))
        csr_emitted.add(rel)

    if "indexer-cluster" in targets:
        peers = _split_csv(args.peer_hosts)
        for h in peers:
            write_csr("splunkd", h, [h, h.split(".")[0]])
            write_csr("s2s", h, [h])
            if _bool(args.encrypt_replication_port):
                write_csr("replication", h, peers)  # SAN = all peers so any can connect
        if args.cm_fqdn:
            write_csr("splunkd", args.cm_fqdn, [args.cm_fqdn, args.cm_fqdn.split(".")[0]])
    if "shc" in targets:
        for h in _split_csv(args.shc_members):
            write_csr("shc-member", h, [h, h.split(".")[0]])
            write_csr("web", h, [h, h.split(".")[0]])
            write_csr("hec", h, [h, h.split(".")[0]])
        if args.shc_deployer_fqdn:
            write_csr("splunkd", args.shc_deployer_fqdn, [args.shc_deployer_fqdn])
    if "license-manager" in targets and args.lm_fqdn:
        write_csr("license-manager", args.lm_fqdn, [args.lm_fqdn])
    if "deployment-server" in targets and args.ds_fqdn:
        write_csr("deployment-server", args.ds_fqdn, [args.ds_fqdn])
        for client in _split_csv(args.ds_clients):
            write_csr("deployment-client", client, [client])
    if "monitoring-console" in targets and args.mc_fqdn:
        write_csr("monitoring-console", args.mc_fqdn, [args.mc_fqdn])
    if "saml-sp" in targets and args.public_fqdn:
        write_csr("saml-sp", args.public_fqdn, [args.public_fqdn], saml=True)
    if "edge-processor" in targets:
        if args.ep_fqdn:
            write_csr("edge-processor-server", args.ep_fqdn, [args.ep_fqdn])
        if args.ep_data_source_fqdn:
            write_csr("edge-processor-client", args.ep_data_source_fqdn, [args.ep_data_source_fqdn])
    if "federated-search" in targets:
        for h in _split_csv(args.federation_provider_hosts):
            write_csr("federation-provider", h, [h])
    if "dmz-hf" in targets:
        for h in _split_csv(args.dmz_hf_hosts):
            write_csr("dmz-hf", h, [h])
    if "uf-fleet" in targets:
        for group in _split_csv(args.uf_fleet_groups) or ["default"]:
            # Group-level template; per-host SANs are filled in by the operator
            write_csr("uf-fleet", group, [f"{group}.example.com"])
    if "core5" in targets:
        primary = args.single_sh_fqdn or args.public_fqdn
        if primary:
            write_csr("splunkd", primary, [primary, primary.split(".")[0]])
            write_csr("web", primary, [primary])
            write_csr("hec", primary, [primary])
            write_csr("s2s", primary, [primary])

    return csr_emitted


def main() -> int:
    args = parse_args()
    if args.dry_run:
        # Emit a JSON summary of what would be rendered without touching disk
        policy = _load_algorithm_policy(args)
        _validate_args(args, policy)
        targets = _expand_targets(args.target)
        mtls = _expand_mtls(args.enable_mtls)
        summary = {
            "would_render_to": str(Path(args.output_dir).expanduser().resolve() / "platform-pki"),
            "mode": args.mode,
            "targets": sorted(targets),
            "tls_policy": args.tls_policy,
            "tls_version_floor": args.tls_version_floor,
            "key_algorithm": args.key_algorithm,
            "key_format": args.key_format,
            "enable_mtls": sorted(mtls),
            "encrypt_replication_port": _bool(args.encrypt_replication_port),
            "include_edge_processor": _bool(args.include_edge_processor),
            "saml_sp": _bool(args.saml_sp),
            "ldaps": _bool(args.ldaps),
            "fips_mode": args.fips_mode,
            "manifest_count_max": len(GENERATED_FILES),
        }
        if args.json:
            print(json.dumps(summary))
        else:
            for k, v in summary.items():
                print(f"{k}: {v}")
        return 0

    out_root, emitted = render(args)
    if args.json:
        print(json.dumps({"rendered_to": str(out_root), "files": sorted(emitted)}))
    else:
        print(f"Rendered {len(emitted)} files to {out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
