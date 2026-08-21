# Splunkbase registry metadata provenance

`app_registry.json` points to the tracked
`splunkbase_registry_evidence.json` snapshot. The snapshot records the public
listing URL and release API URL for every numeric Splunkbase app, SHA-256 hashes
of the fetched source payloads, normalized latest and reviewed-release facts,
and per-app plus whole-registry canonical package-fact hashes.
The snapshot also records the ordered registry field projection used to compute
those hashes, so a verifier does not have to infer the canonical contract.

This is metadata/release provenance only. It does **not** download, hash, or
verify the contents of a `.spl`, `.tgz`, or other package binary. A snapshot
source hash must never be described as a package checksum.

## Audit and refresh

Run the fail-closed offline audit in CI or before using registry pins:

```bash
python3 skills/shared/scripts/audit_splunkbase_registry.py
```

It fails when the pointer or snapshot is missing, when the snapshot file hash
does not match, when registry package facts changed after evidence generation,
when app coverage/facts/source declarations differ, or when the evidence date
predates a registry verification date. Evidence dated in the future or older
than 90 days also fails. A human performing a read-only historical audit may
choose another 1–365 day window with `--max-evidence-age-days`; that option
cannot be combined with `--write-evidence`, and installers do not expose or use
it.

The generic app installer and Cloud batch installer run this offline audit
before creating local staging directories, reading registry routing fields, or
calling Splunk/ACS mutation APIs. There is no installer bypass for missing,
tampered, future-dated, or stale evidence.

Compare all records with current public sources without writing:

```bash
python3 skills/shared/scripts/audit_splunkbase_registry.py --live
```

After reviewing a clean live result, refresh the snapshot and its registry
pointer atomically in one workflow. Use an explicit UTC date so tracked output
does not depend on the operator's clock:

```bash
python3 skills/shared/scripts/audit_splunkbase_registry.py \
  --live --write-evidence --evidence-date YYYY-MM-DD
```

The generator sorts apps by numeric Splunkbase ID and serializes JSON
deterministically. Splunkbase listing HTML contains per-render UI IDs and emits
some set-like metadata arrays in nondeterministic order. The generator extracts
the fetched page's `__NEXT_DATA__` listing payload, recursively sorts JSON
arrays, and hashes its canonical JSON; stable source fields and asset URLs
remain covered. Each entry declares that hash input. Release API response bytes
are hashed without normalization. Any other source-payload change remains
visible in the hash.

Listing release facts are read from the structured
`props.pageProps.appDetails.release` object in that same payload rather than
from rendered page text, which the listing no longer server-renders. That object
is the one release the listing designates as current, which is not always the
most recently published release when a vendor maintains parallel release lines.
The audit compares it against the release API entry of the same version, so a
newer-but-not-designated release never advances a registry pin on its own.

The canonical registry projection covers release and compatibility facts plus
install-relevant identity and routing fields: package patterns, license
acknowledgement, dependencies (`install_requires`), placement roles,
capabilities, relationships, and Cloud install methods. Changing a dependency
or routing field therefore invalidates the evidence before an installer can act
on it.

`install_requires` must be a list of unique canonical numeric app-ID strings.
Every target must exist in the numeric registry; self-dependencies and graph
cycles are rejected by both the offline audit and the Cloud dependency
expander. Expansion errors propagate and stop the batch. Because versions are
app-specific, Cloud batch `--version` is rejected when expansion introduces a
dependency that was not explicitly requested.

Numeric Splunkbase IDs absent from the registry are outside this provenance
boundary. Local and Cloud install paths require
`--accept-unverified-release` after independent identity/release review and a
separate `--accept-unsupported-platform` acknowledgement after manual platform
compatibility review. Neither acknowledgement makes an unknown package
source-verified.

## Historical reviewed pins

The current public release API returns only the currently visible release for
some apps, so a previously reviewed pin can stop being reproducible from that
API. Such pins are explicitly classified
`historical-review-only-not-currently-reproducible`.

As of the 2026-08-20 snapshot no registry entry carries this classification.
Every previously historical pin was advanced to a release that the current
public API returns and whose package was downloaded, unpacked, and inspected:

| App | Old historical pin | Verified now |
| --- | --- | --- |
| `1620` `Splunk_TA_cisco-asa` | `6.0.1` | `6.1.2` |
| `1761` `Splunk_TA_cisco-esa` | `1.7.0` | `1.7.1` |
| `1928` `Splunk_TA_snow` | `10.0.1` | `11.0.2` |
| `2911` `Splunk_TA_tomcat` | `4.0.0` | `4.0.3` |
| `3088` `Splunk_TA_google-cloudplatform` | `5.0.2` | `5.1.1` |
| `3449` `DA-ESS-ContentUpdate` | `6.0.0` | `6.4.0` |
| `3549` `Splunk_TA_salesforce` | `6.0.2` | `7.0.0` |
| `6553` `Splunk_TA_okta_identity_cloud` | `5.0.2` | `5.1.0` |
| `7245` `Splunk_AI_Assistant_Cloud` | `2.0.0` | `2.2.0` |
| `8485` `ta_cisco_spaces` | `1.0.7` | `2.0.1` |

The classification and its gate stay implemented, because the public release API
can drop a release again at any time. When an entry carries it, its stored facts
remain bound to the registry snapshot but are not claimed as current
public-source proof, and its `verified_platform_versions` is recorded as an empty
list because no current public source proves that pin's platform list. The
generic and Cloud batch installers refuse such a pin before mutation unless the
operator supplies `--accept-historical-review-only-pin` after independent
package/version approval. Platform incompatibility remains a separate gate and
may also require `--accept-unsupported-platform`. Choosing
`--accept-unverified-release` selects public latest for review instead of the
historical pin.

## Reviewed pins held behind public latest

Some entries deliberately keep a reviewed pin that is older than public latest.
They are recorded as split entries: `latest_release_version` tracks the current
public release, while `latest_verified_version` stays on the reviewed pin. Two
distinct reasons apply as of the 2026-08-20 snapshot, and a refresh of public
metadata alone never clears either of them.

**Platform gate.** The public release stopped advertising the
`compatibility_target` platform, so adopting it would break a 10.5 deployment:

- `5556` — `Splunk_TA_Google_Workspace` pins `4.0.0`; public `5.0.0` does not
  advertise Splunk 10.5.
- `7828` — `Splunk_TA_Cisco_Intersight` pins `3.1.1`; public `3.2.0` does not
  advertise Splunk 10.5.

**Entitlement gate.** The public release advertises the platform target, but its
Splunkbase download is entitlement-gated and returns HTTP 403 without the
product entitlement, so its package cannot be inspected from this repo:

- `263` — `SplunkEnterpriseSecuritySuite` pins `8.5.1`; public `8.6.1` needs an
  Enterprise Security entitlement to download.
- `1841` — `SA-ITOA` pins `4.21.2`; public `5.0.1` needs an ITSI entitlement to
  download.

Both pins advertise Splunk 10.5, so the default install path still works; only
the package-evidence refresh is deferred until an entitled download is
available.

**Package verification boundary.** The owning skill renders inputs, source
types, macros, or validation logic derived from a specific inspected package, so
the pin can only advance after that newer package is downloaded, unpacked, and
re-reviewed. Public listing metadata is not package verification. As of the
2026-08-20 snapshot no pin is held for this reason: every skill-derived pin was
re-verified against a freshly downloaded package under `splunk-ta/_unpacked/`,
and the skills that previously documented an `--accept-unverified-release`
override for this reason no longer need one. The boundary itself still governs
future advances, and is enforced through an inspected package under
`splunk-ta/_unpacked/`, a version constant in the skill's renderer, or an
explicit Package Verification Boundary section in the skill.
