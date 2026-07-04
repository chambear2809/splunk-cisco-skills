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
some apps. As of the 2026-07-03 snapshot, these older reviewed pins are not
reproducible from that API and are explicitly classified
`historical-review-only-not-currently-reproducible`:

- `1761` — `Splunk_TA_cisco-esa` `1.7.0`
- `1928` — `Splunk_TA_snow` `10.0.1`
- `2911` — `Splunk_TA_tomcat` `4.0.0`
- `3549` — `Splunk_TA_salesforce` `6.0.2`
- `7557` — `Splunk_TA_Talos_Intelligence` `1.0.1`

Their stored facts remain bound to the registry snapshot, but they are not
claimed as current public-source proof. The generic and Cloud batch installers
refuse these pins before mutation unless the operator supplies
`--accept-historical-review-only-pin` after independent package/version
approval. Platform incompatibility remains a separate gate and may also require
`--accept-unsupported-platform`. Choosing `--accept-unverified-release` selects
public latest for review instead of the historical pin.
