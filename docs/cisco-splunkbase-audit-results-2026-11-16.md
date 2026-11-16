# Cisco Splunkbase implementation audit — 2026-11-16

This audit changes repository workflows and selected package pins. It does not
install into Splunk, change AWS resources, publish, or create a pull request.
Existing documentation work was incorporated, and the pre-existing Meraki
`scripts/setup.sh` modification was preserved byte-for-byte.

## Evidence and coverage

- [Discovery method and inventory](cisco-splunkbase-audit-2026-11-16/README.md):
  paginated live publisher and product searches, publisher variations, explicit
  repository/requested IDs, listing-default releases, parallel releases,
  publisher/support, platform declarations, relationships, and dispositions.
- [29 downloaded package archives](cisco-package-evidence-2026-11-16.json): exact
  app identity, package version, archive filename, inspection date, binary
  SHA-256, Python declarations, and shipped view IDs.
- [Networking and data center review](cisco-package-review-network-dc-2026-11-16.md).
- [Security, access, collaboration, AppDynamics, CESA, and Cyber Vision review](cisco-package-review-security-2026-11-16.md).
- [SCAN review](cisco-package-review-scan-2026-11-16.md).
- [Initial full-registry drift](cisco-splunkbase-registry-drift-2026-11-16.json):
  235 public metadata differences across the shared 120-entry boundary before
  refresh. Public metadata was refreshed for all 120 entries because the
  existing evidence generator requires a clean full-registry comparison.

Source-payload hashes establish metadata provenance. The binary hashes in the
package evidence file were computed from downloaded archive bytes. Static
inspection does not establish deployed ingestion, browser rendering, runtime
execution, or current vendor support beyond the sources recorded.

## Selected pin changes

| Package | Previous selected pin | Selected after audit | Basis |
|---|---|---|---|
| UCS 2731 | 4.3.3 | 5.0.0 | Existing server/template/task fields retained; task enablement, migration helpers, Python declarations, and monitoring views reviewed |
| Meraki 5580 | 3.4.0 | 3.5.0 | Core account/input contract and polling defaults reviewed; existing user interval fix retained |
| Secure Access add-on 7569 | 1.0.53, historical | 1.0.57 | Current archive/account/input contract reviewed with companion app |
| Secure Access app 5558 | 1.0.57 | 1.0.60 | Dashboard/account/settings contract reviewed with add-on |
| Spaces 8485 | 2.0.1 | 2.0.20 | Firehose/stream/token and optional health/checkpoint controls reviewed |
| ThousandEyes 7719 | 0.8.0 | 0.9.0 | OAuth, HEC stream groups, and refresh-token workflow reviewed |
| ESA 1761 | 1.7.1 | 1.8.0 | Parser/search-time contract and transport handoff reviewed |
| AppDynamics 3471 | 3.2.1 | 3.3.0 | Controller/Analytics account and input fields reviewed |

These approvals apply to repository configuration contracts and the documented
platform gates. Complete live ingest and dashboard validation on the selected
Enterprise or Cloud topology before declaring onboarding successful.

## Inspected candidates intentionally held

| Package | Inspected listing default | Retained pin | Concrete adoption boundary |
|---|---|---|---|
| Enterprise Networking TA 7538 | 4.0.60 | 3.2.44 | Coordinated TA/app/NetFlow 4.x migration, expanded input handlers, saved searches and dashboards |
| Enterprise Networking app 7539 | 4.0.20 | 3.2.20 | Paired TA compatibility and changed `summariesonly` / old-summary behavior; accelerated model qualification |
| NetFlow mapping add-on 6872 | 4.0.0 | 2.1.0 | Coordinated 4.x package set; receiver/exporter ownership and decoded field validation |
| Security Cloud 7404 | 4.1.3 | 3.6.10 | Granular FTD routing changes affect custom SPL, alerts, macros, eventtypes, dashboards, CIM and acceleration |
| DC Networking 7777 | 2.0.0 | 1.2.2 | Beta major migration; wrappers cover ACI/APIC, Nexus Dashboard and Nexus 9K; Hyperfabric/MDS remain manual handoffs |
| Intersight 7828 | 3.2.2 | 3.1.1 | Current 3.2.2 metadata advertises through 10.5, without explicit Enterprise 10.6 support |
| Stream 1809/5238/5234 | 8.1.7 | 8.1.6 | Native management-credential lifecycle, startup behavior, capture permissions and hybrid NetFlow validation |
| SCAN 8566 | 1.0.50 | 1.0.30 | Python 3.13 commands, catalog/reconciliation, four views and per-member lookup sync need adoption qualification |

The held packages were obtained and statically inspected. They are not blocked
by download access. Initial transient authentication failures were resolved
using the established helper; unauthenticated HTTP 401 responses are not
evidence of missing entitlement.

Intersight also publishes a newer **3.3.1 parallel release**, dated 2026-11-16,
which advertises Enterprise 10.6/10.7. Its archive was additionally inspected;
it adds physical-disk telemetry with a separate 1800-second input. The listing
default remains 3.2.2 and selected pin remains 3.1.1 pending 3.3.x input,
checkpoint and dashboard migration qualification.

## Workflow implementation

- Security Cloud setup and direct product/input configuration enforce the
  reviewed 3.6.10 contract before writes on Enterprise 10.6 as well as Cloud
  10.5. Newer listing compatibility cannot bypass the FTD migration boundary.
- Enterprise Networking guards apply on all targets and verify the reviewed
  TA/app pair before dashboard macro or acceleration changes.
- Intersight guards apply across target versions, including its direct account
  helper, while retaining the selected 3.1.1 package.
- UCS completion checks app visibility, exact monitoring/configuration/input
  view IDs, enabled tasks, templates, server records, and real UCS data.
  Monitoring-log absence remains diagnostic because healthy collectors can
  have different log levels or internal-log forwarding.
  Its Monitoring Dashboard is UCC ingestion health content, not a claim of a
  standalone UCS business dashboard. Operator browser/panel checks remain
  required.
- SCAN adds `validate.sh --completion`, requiring four named views and
  nonempty lookup results. Setup now invokes that gate. Final handoff also
  requires opening the views and retaining their rendered results.
- The Cisco product router now distinguishes separately published ISE 1915,
  CESA 4221/2992, and Cyber Vision 5748/5747 from the existing Cisco TA routes.
  Generated catalog output was rebuilt from overrides.

## Remaining workflow and support limits

CESA is Cisco-published with a current `not_supported` badge. Listing text
requires a CESA endpoint license from 2.1.4, with stated trial/small-deployment
exceptions. Its add-on bundles an external nvzFlow collector that was identified
but not executed or approved. A dedicated automated CESA workflow still needs
collector runtime/placement, transport, licensing and support confirmation, and
dashboard/CIM migration qualification. Security Cloud's NVM route is not proof
of equivalence to CESA.

Cyber Vision's separate add-on and app are authored by Cisco Systems in their
packages and published as Cyber Vision with developer support. The add-on's
advertised platform range stops at 10.4, while its app advertises newer
versions. The existing Catalyst Cyber Vision route covers the product use case;
it does not configure this separate package pair or prove its 10.5/10.6 support.

Webex's add-on remains Enterprise-only while its visualization app advertises
Cloud compatibility; use an approved customer-managed collector placement.
Publisher identity, support badge, licensing, release compatibility and package
contract review are separate facts throughout the inventory.

Several inspected packages declare Python 3.13. Check the exact execution tier,
including forwarders, rather than extending listing ranges to older runtimes.
Splunk documents Python 3.13 availability from Enterprise 10.2 and default use
from 10.4; Cloud has its own release cadence. See the
[Enterprise transition notes](https://help.splunk.com/en/splunk-enterprise/get-started/install-and-upgrade/10.2/upgrade-or-migrate-splunk-enterprise/about-upgrading-to-10.2-read-this-first)
and [Cloud 10.4 release notes](https://help.splunk.com/en/splunk-cloud-platform/release-notes/10.4.2604/splunk-cloud-platform-release-notes/whats-new).

The shared refresh also found that Infoblox 2934/2.2.0, ESCU 3449/6.4.0, and
ARI 7180/1.2.2 had disappeared from the public release API. Their selected pins
were preserved and marked historical-only. Their owning Enterprise 10.6
profiles are now conditional; no unrelated package was upgraded to hide the
missing evidence. Seven historical pins remain subject to the existing gates.

This is a dated audit with explicit adoption holds and workflow gaps, not a
claim that every Cisco ecosystem package or every deployed runtime is current.

## Verification

| Check | Result |
|---|---|
| Full Python suite, repository virtual environment, four workers | 5,080 passed, 26 skipped, 3,258 subtests passed; 10 failures at the integration snapshot |
| Final affected/failing tests and guard/completion suites | Initial final run: 36 passed; one unrelated freshness failure, resolved during PR integration as described below |
| Shell regression suite | All 379 Bats tests passed |
| Shell syntax | All 442 first-party scripts passed; changed scripts rechecked after edits |
| ShellCheck | All 442 first-party scripts passed at warning severity; changed scripts rechecked |
| Registry/evidence audit | Offline and live comparison passed for all 120 numeric entries, with zero findings |
| Evidence refresh | Documented live/write-evidence workflow completed with explicit date 2026-11-16; no hashes or gates bypassed |
| Generated surfaces | All six generators run and checked in dependency order; SCAN catalog check passed |
| Python/config quality | Ruff passed; audit JSON parsed successfully; no audit artifact exceeds 1 MB |
| Secret scanning | Tracked-file hook passed; explicit scan of all new audit artifacts passed with no findings |
| Whitespace/diff | `git diff --check` passed |
| All-files pre-commit | Initial audit run: every hook passed except repository readiness; PR integration verification follows below |

The nine resolved full-suite failures concerned outdated current-release
expectations, a stale ACS mock version, the now-resolved Secure Access selected
package compatibility hold, and validator mock responses collected before the
final visibility checks. The final 37-case run explicitly included every
full-suite failure plus the changed guard/completion suites and generated
Enterprise compatibility check. The full 5,116-case suite was not rerun after
those corrections; the affected checks were rerun against the final files.
The local full-suite runner used pytest-xdist; no dependency manifests changed.

The initial remaining failing test was
`tests/test_product_feature_coverage_contract.py::test_product_feature_coverage_contract_passes`.
Repository readiness/pre-commit reported the same cause:
`skills/splunk-observability-deep-native-workflows/reference.md` records research
on **2026-05-01**, which is **199 days** old on this audit date, exceeding the
existing **180-day** maximum. That file and its date were already present in
the original audit baseline and were not changed by this audit. This Cisco package audit did not re-research the
unrelated Observability native API matrix, change the freshness limit, or
replace its date without source review.

The Cisco semantic coverage snapshot was refreshed only after reviewing the
three explicit ISE/Cyber Vision/NVM route-boundary changes, following
`skills/shared/references/product_feature_coverage_contract.md`. Feature IDs,
feature count (86), owner skills, and mutation boundaries were preserved.
No live Splunk installation, ingestion, native collector execution, dashboard
browser rendering or production change was performed. Publication is a separately
authorized follow-up to this audit.

### PR integration

The publication branch incorporates remote main through `19609eb`, including
PR #117 (`2b966e2`). That existing change substantively refreshed the unrelated
Observability native workflow sources to 2026-10-31 and updated the matching
semantic manifest. Independent review confirmed its source changes and passing
freshness checks. The original stale provenance blocker is therefore resolved
without relaxing the 180-day gate or substituting an unsupported date.

Unregistered ecosystem alternatives, including Secure Networking Essentials
9257 and the third-party Sideview/CCX/JDS packages, remain uninspected or lack
an exact configuration contract as explicitly recorded per row in the coverage
inventory. Existing product-use-case overlap is identified separately; it is
not approval to install a different package. Unrelated public metadata updates
(such as Google Workspace 5.1.0, MCP 2.1.0 and AI Assistant 2.3.6) did not advance
their selected package pins or establish package inspection for them.
