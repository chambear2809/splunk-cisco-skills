# Cisco Collaboration Setup Reference

This reference is an operator summary. Claim-level dates, versions, ownership,
and primary URLs live in `references/source-ledger.json`.

## Collection Matrix

| Product | Path | Source type / schema | Default index | Collector or handoff | CIM treatment |
|---|---|---|---|---|---|
| CUCM | Remote-audit-logging syslog | `cisco:ucm` | `ucm` | Explicit UDP/TCP/TLS audit profile plus blocking SC4S listener handoff for every operator-selected port | No automatic call-analytics mapping |
| CUCM | CDR flat files | Spec-evidenced custom source type | Spec-evidenced | SFTP billing server or on-demand SOAP request followed by SFTP delivery | Product-specific normalized schema |
| CUCM | CMR flat files | Separate spec-evidenced custom source type | Spec-evidenced | Same supported export families, independently evidenced | Product-specific normalized schema |
| CUCM | AXL | SOAP/XML configuration records | N/A | HTTPS POST to publisher `/axl/` | Enrichment only; not CDR collection |
| Expressway | Syslog | `cisco:tvcs` (SC4S table also says `cisco:vcs`) | `main` | Device: UDP/514 legacy-BSD or IETF, or TLS/6514 IETF with reviewed trust; SC4S listener plan is separate | Only spec-qualified standard models |
| Expressway | CDR readiness | INFO records on syslog when enabled | `main` | Expressway syslog | Product-specific normalized schema |
| Expressway | Media readiness | `local2` media statistics | `main` | Expressway syslog | Product-specific normalized schema |
| CMS | Syslog | `cisco:ms` | `netops` | CMS TCP or optional `tls:` sender; deterministic SC4S mapping; TLS listener/certificate gap | Only spec-qualified standard models |
| CMS | XML CDR | XML over HTTP(S) | UNKNOWN | External receiver gap | Product-specific normalized schema |
| Meeting Management | System syslog | `cisco:mm:system:*` | `netops` | Independent TCP or TLS 1.2 sender profile; deterministic SC4S mapping | Only spec-qualified standard models |
| Meeting Management | Audit syslog | `cisco:mm:audit` | `netops` | Independent TCP or TLS 1.2 profile; parser separates audit | Authentication/Change only with qualifying evidence |

SC4S human documentation is mutable and was checked on `2026-07-19`. CMS and
Meeting Management parser source evidence is pinned to commit
`f878a6e8031b07ae8777e97738b27afe735f118d`.

## Recoverable Replacement

Recovery is a reviewed rename-back operation: stop concurrent renderers,
confirm the exact original target and its `.lock` sibling are absent, inspect
the exact backup path returned by `backup_dir` for current-user ownership,
`0700` mode, and absence of symlinks, rename that exact directory back to the
original target, then run `validate.sh --output-dir <original-target>`. Do not
modify the marker and do not substitute a glob-derived path.
The path-bound backup is not a valid bundle at the backup location; validation
is expected to fail there. After safe restoration, a packet with CDR/CMR, CIM,
partner-package, or CMM operator-attested evidence must be validated with the
trusted original `--spec` and, when available, its externally recorded
`--expected-spec-sha256`; bare validation intentionally fails closed. Internal
replacement preflight checks ownership, structure, and the renderer-created
marker commitments only and never upgrades old-packet provenance.

## Integrity and Provenance Boundary

Every artifact, including the manifest, is SHA-256-bound in the private
path-bound marker. Bare validation byte-compares all projections to that marker
and rejects partial artifact-plus-manifest rehashes, impossible executable/live
semantics, and fixed-registry changes. These are unkeyed integrity commitments,
not signatures: the same owner can coherently rewrite the bundle and marker.
Historical provenance therefore requires `validate.sh --spec <trusted-spec>`;
the validator strictly re-parses that external spec, verifies the optional
external digest, re-reads its local evidence, rebuilds every privacy-bounded
projection, and byte-compares the full packet.

## Deterministic SC4S Classification

CMS and Meeting Management deterministic classification uses one of:

- an exact RFC-valid host name with no wildcard or regex metacharacters;
- an exact IPv4 or IPv6 address; or
- a unique dedicated TCP port from 1024 through 65535, excluding shared ports
  514 and 6514.

When CMS and Meeting Management are both enabled they must use the same
selector mode with distinct values; cross-mode pairs cannot prove disjointness
and fail closed. A dedicated-port
plan can be expressed to the local SC4S child renderer with `--vendor-port`.
It is emitted only for a compatible plain-TCP sender profile. TLS sender
profiles retain a blocking listener/certificate gap and suppress that
plaintext vendor-port argv.
Exact-source plans remain reviewed classifier handoffs; this router does not
invent or apply an undocumented SC4S site configuration.

CUCM device transport is intentionally narrower than the `cisco:ucm` parser
scope. Cisco 15 proves UDP (default), TCP, and TLS only for remote audit logs;
it does not prove those transports for every `%UC_` or `%CCM_` service-syslog
message detected by the SC4S parser. Receiver port is therefore explicit and
operator-selected, never presented as a Cisco default. Every enabled CUCM
profile retains a blocking SC4S listener gap: a bare child render does not open
that port, and this router emits no CUCM vendor-port or source-TLS argv.

## CUCM CDR/CMR and AXL

CUCM CDR and CMR are separate SFTP-delivered flat-file types with distinct
formats and two header rows. Current Cisco documentation describes CDR Agent
transfer to the repository over SFTP, billing-server export, and an on-demand
SOAP/HTTPS request whose matching files are returned over SFTP. Cisco CUCM 15
pages conflict on the maximum billing-server count, so this skill encodes no
maximum. The diagnostic CLI namespace
`cm/cdr_repository/processed/<date>` is not a production export contract.
Line 1 contains unique field names, line 2 contains equally wide nonempty field
types, and lines 3 onward contain equally wide records. Every sample must have
one `cdrRecordType` column whose data value is `1` for CDR and `2` for CMR, as
well as the matching `cdr_` or `cmr_` filename family. CDR uses the unambiguous
`globalCallID_callManagerId` and `globalCallID_callId`. Current Release 15
export evidence maps CDR party-number fields to `VARCHAR(50)`. For CMR, only
the exported `globalCallID_callId` (`INTEGER`) plus `directoryNum`
(`VARCHAR(50)`) pair can qualify local evidence. The field-description spelling
`globalCallId_callId` plus `directoryNumber` (both `INTEGER`) is recorded only
as documentation compatibility and is rejected for qualification because no
versioned exported line-2 type row proves it. Every CMR path also requires
`globalCallID_callManagerId`.
Every data cell whose type row declares `INTEGER` must contain a nonempty ASCII
base-10 integer; an explicit plus prefix remains accepted. Cisco Positive
Integer fields must be greater than zero: CDR manager/call/original-leg IDs and
CMR manager/call/node/call-identifier fields. CMR `jitter` is unsigned, while
`numberPacketsLost` may be negative; ordinary date/time/latency Integer fields
receive no invented bound. Exact CDR/CMR `cdrRecordType` constants remain `1`
and `2`.

AXL is a provisioning/configuration SOAP API, normally posted to
`https://<publisher>:8443/axl/`. It is throttled and not a realtime API. This
skill renders AXL only as an enrichment readiness packet and never asks for or
stores AXL credentials.

## Optional Sideview Packages

The following packages are partner-built and developer-supported. They are not
Splunk-owned official TAs and this router emits no installation command.

| App ID | Pinned listing version | Role in the evidence plan | Known placement / block |
|---|---|---|---|
| 669 | 8.4.2 | Commercial Cisco CDR Reporting and Analytics | Search tier or full app on a standalone indexer; entitlement required |
| 4434 | 8.3.1 | CDR/CMR index-time TA | Universal or heavy forwarder; require app 669 evidence elsewhere |
| 4640 | 1.2.9 | Separately licensed AXL supporting app | Search tier; any strict numeric platform version above verified maximum 10.4 is blocked |
| 8413 | 0.6.1 | Cisco Meeting Server CDR support | Receiver and tier remain UNKNOWN, so selection is blocked |
| 8592 | 0.5.0 | Expressway CDR index-time add-on | Indexer, or heavy forwarder when it produces cooked data |
| 8593 | 0.5.3 | Expressway CDR search-side app | Search tier; require 8592 and 669 evidence |

Package names and active CDR/CMR source types must be confirmed from reviewed
package contents. App 8592's listing mentions CSV/JSON source types as under
development, so this skill does not promote either to an active source type.

## CIM Boundary

Current official CIM documentation does not establish a Telephony or VoIP data
model. Call records stay in a product-specific normalized schema. The renderer
allows only Authentication and Change candidates, and only when the spec has:

- a read-only search constrained by both `index=` and `sourcetype=`;
- the conservative qualifying field set;
- a local evidence file and exact SHA-256; and
- no write-capable SPL command.

The qualifying operator search is validated from the local spec but never
copied into the bundle. Rendered CIM artifacts retain only its SHA-256,
structural review outcome, exact CMM-audit route/field allowlist, and a
non-identifying `search index=netops sourcetype=cisco:mm:audit | head 0`
skeleton. Identifier literals in `search`, `eval`, or `where` therefore remain
outside the credential-free/private packet.

Network Traffic is not inferred merely because a record contains addresses or
media statistics.

Dashboard searches derive a fixed collaboration-route label, project only
`_time` and `collaboration_route`, explicitly remove `_raw` as the final step
before aggregation, and then run `timechart`. Every other field—including
present and future vendor identifiers—is discarded; `_time` is preserved and
no identifier hash is retained. Evidence samples are verified locally by
structure and digest and are never copied or displayed.

The private packet necessarily retains reviewed operational routing
identifiers: project, environment, owner, restricted role, exact host/IP
selectors, indexes/source types, and the marker-bound output path. The
no-identifiers claim is limited to event evidence values plus dashboard/CIM
output. The source spec basename is not retained; metadata stores only its
SHA-256 with `name_persisted: false`. Copied free text and every CDR/CMR header
are screened for email/credential shapes, secret-like names, and a bounded
Cisco-style technical-field grammar. The resolved marker-bound output path and
its derived SC4S child sibling are screened before any write because both are
intentionally retained in plan/marker output. Detection is deliberately finite:
it covers private-key/bearer material and recognized AWS, GitHub, Slack, JWT,
OpenAI `sk-`/`sk-proj-`, and Google `AIza` shapes. UUID-like HEC/client-secret
strings remain allowed because they cannot be distinguished from legitimate
identifiers by shape alone; the renderer does not claim universal secret
detection.

Listener and trust state is derived, not operator-upgradable: disabled product
routes render `listener_readiness: disabled`; enabled TLS routes retain an
unresolved listener/certificate gap; enabled supported plaintext routes remain
`planned_render_handoff`. CUCM and Expressway trust review is true exactly for
enabled TLS and false for UDP/TCP or disabled routes. CMS/CMM protocol selectors
do not count as operator evidence, and CMM operator assertion requires its
strict sanitized metadata packet.

CUCM AXL and Expressway CDR/media intake is deliberately operator metadata,
not event-derived evidence. Search and asserted-field notes may guide later
live review, but they never set `local_sample_validated` or upgrade beyond
`planned_render_handoff`. File/hash evidence fields are not accepted for these
paths until a source-backed sanitized event schema is defined.

## Roadmap and UNKNOWN Handoffs

- RoomOS stays `unsupported_roadmap`. The packet separates Webex API/device
  evidence from ThousandEyes endpoint/network evidence.
- BroadWorks stays `unsupported_roadmap`. The packet points first to Cisco's
  BroadWorks developer getting-started interface and claims no executable
  collection status, TA, parser, source type, or collector.
- UCCX/UCCE stays `UNKNOWN` until primary product and Splunk integration
  evidence is added.
