# Cisco Splunkbase discovery — 2026-11-16

The [reviewable inventory](coverage.md) and [structured coverage report](coverage.json)
join live source metadata to exact registry entries, existing product-use-case
routes, companion/legacy relationships, reviewed pins, and package inspections.
See [implementation and remaining adoption gates](../cisco-splunkbase-audit-results-2026-11-16.md)
and [29 downloaded archive records](../cisco-package-evidence-2026-11-16.json).

The sweep retained **184 candidate listings**. Whole product words, catalog
relationships, and exact Cisco skill registry entries identify **52 coverage
rows**, including optional Stream components; the other 132 remain visible in
[inventory.json](inventory.json) as discovery results. This selection rule avoids
substring collisions such as `aci` inside unrelated words, plus explicitly
excluded uberAgent ESA and ESET packages that are not Cisco products. A related package or
use-case route is not classified as an approved Cisco-built workflow.

## Live discovery method

1. Queried Splunkbase v2 `/api/v2/apps/?author=cisco&page=N` to its reported
   total; verified pagination with distinct returned offsets and IDs. The Cisco
   account returns 11 listings, which fit on one page. Product queries were
   independently paginated to their totals for Cisco, Nexus, ACI, APIC, UCS,
   Intersight, Webex, AppDynamics, Cyber Vision, endpoint security, Secure Access,
   Meraki, Spaces, ThousandEyes, Catalyst, ASA, ISE, ESA and WSA.
2. Cross-checked actual publisher-account identifiers observed in listings:
   `cisco`, `nvzFlow`, `cisco-cybervision-splunk@cisco.com`, `splunklabs`, and
   `svc-sfs-splunk.gen@cisco.com`. Also tested display-name variants `Cisco
   Systems`, `Cisco Systems Inc`, and `Cisco ThousandEyes Inc`; zero-result
   variants are retained rather than treated as successful publisher filters.
   All eight account queries were paginated; totals, offsets and returned
   counts are under `publisher_account_crosschecks` in inventory.json. Broad
   Splunk publisher accounts were filtered to Cisco-product terms before
   adding candidate listing pages; their other products are outside this audit.
3. Seeded the requested numeric IDs and repository identities independently of
   search ranking, then explicitly added Stream 1809/5238/5234 for NetFlow
   collector/deployment dependencies. Exact matches and current selected pins
   were joined from `skills/shared/app_registry.json`.
4. Fetched each candidate listing directly and parsed
   `__NEXT_DATA__.props.pageProps.appDetails`; the release designated by
   `appDetails.release` is the listing default. Cross-checked its identity,
   publication date and platform versions against the exact live release API
   `/api/v1/app/<id>/release/<release-id>/`. All 52 coverage rows match these
   comparisons. Other visible releases are retained, and coverage.json reports
   newer parallel releases separately. Intersight illustrates the distinction:
   listing default 3.2.2, newer parallel 3.3.1, selected pin 3.1.1.
5. Publisher, support badge, package type, license, Enterprise/Cloud declarations,
   exact Splunk platform list, registry entry, inspected versions and
   companion/dependency/use-case relationships are retained separately.
   Cyber Vision package `app.conf` names Cisco Systems as author even though
   its listing publisher is Cyber Vision and support is developer-level.

## Sources and reproducibility

`raw/` retains discovery pagination/identity records plus release API facts and
compact listing projections for the 52 coverage rows. Long-form vendor prose,
release-note bodies and sample commands are omitted from API projections; each
projected response records the original fetched-payload hash and omitted fields.
The public source URLs remain available for reading that prose. Excluded candidate
projections remain in inventory.json, avoiding duplicate unrelated source
files. Source
URLs recoverable from the filenames and per-listing records. Source-payload
hashes describe metadata provenance. `release.sha256` / `sha256_listing` are
publisher-supplied artifact digests; only the separate binary evidence report
records hashes independently computed from actual downloaded archives.
Structured page projections are retained instead of large rendered HTML/JS.
The Meraki v2 app record omits vendor curl authorization examples from its
troubleshooting text; its retention record keeps the exact original payload
hash, source URL, and omitted-field declaration. No secret-scan exception or
registry-evidence hash was altered.
Their source hashes refer to the full canonical appDetails object fetched at
inspection time; they are not hashes of the smaller retained projection.

`discover.py` performs the primary sweep; API responses are cached in `raw/`,
while listing pages are fetched again. For a fresh sweep use a new dated output
copy with an empty raw directory; do not overwrite this dated evidence to imply
it was collected later. `extend_discovery.py` adds live observed-publisher account
cross-checks and explicit dependency seeds. `make_report.py` rebuilds inventory.md,
coverage.md and coverage.json from retained sources and current registry/package
evidence. It does not fetch or approve packages. The initial broad metadata
index remains inventory.json.

## Limits and disposition

This is a live, dated public-listing sweep, not a proof of every historical,
unlisted, archived, private or entitlement-gated Cisco package. Keyword APIs
rank/filter current results; archived-only records and publisher identities not
exposed by these searches may be missing. The repository's pinned SCAN fixture
supplies product routing context and is not presented as fresh Splunkbase
metadata. Source consistency is separate from whether a listing advertises
technically sufficient compatibility, whether its support terms are current,
and whether scripts/dashboards have been inspected.

Only the 29 archive/version records in the binary evidence report were obtained
and statically inspected. Unreviewed alternatives remain workflow gaps or
explicit evidence-only handoffs; no runtime, ingestion, UI rendering, licensing
entitlement, or production setup is claimed. CESA 4221/2992, Cyber Vision
5748/5747, separate ISE 1915, and third-party Sideview/CCX alternatives have
explicit dispositions. Stream 8.1.7 archives and receiver/management specifications were additionally
inspected as dependencies; existing reviewed 8.1.6 pins were preserved pending
native management-authentication, runtime and hybrid NetFlow qualification.
