---
name: cisco-collaboration-setup
description: >-
  Use when planning or reviewing Splunk onboarding for Cisco Unified Communications Manager syslog,
  CDR, or CMR; Cisco Expressway syslog, CDR, or media evidence; Cisco Meeting Server syslog or XML
  CDR; or Cisco Meeting Management system and audit syslog. Render a privacy-safe, evidence-gated
  collaboration plan with deterministic SC4S classification and explicit RoomOS, BroadWorks, Webex,
  and ThousandEyes handoffs without applying changes.
compatibility: "Splunk Cloud Platform 10.5.2605: delegated. Compatibility is determined by the canonical replacement or selected child skill; this compatibility alias or router does not own a runtime or package."
metadata:
  splunk_cloud_10_5: "delegated"
  compatibility_verified: "2026-07-02"
---

# Cisco Collaboration Setup

## Prerequisites

| Tool or evidence | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run the offline renderer and validator | `bash --version && python3 --version` |
| Reviewed intake spec | Keep product routes, indexes, and privacy choices explicit | Start from `template.example` |
| Local evidence files | Qualify CDR/CMR, CIM, and partner-package claims; optional AXL/Expressway notes never qualify readiness | Use relative, single-link regular files with SHA-256 values |

## When to Activate

- Route CUCM remote-audit-logging syslog separately from CDR and CMR flat-file collection.
- Plan Expressway syslog and optional CDR or `local2` media-statistics readiness.
- Plan CMS syslog while keeping its HTTP(S) XML CDR receiver as an explicit gap.
- Plan Meeting Management system and audit syslog.
- Produce evidence-only RoomOS, BroadWorks, UCCX, or UCCE gap packets.

Do not use this skill for Webex REST collection itself; hand that work to
`cisco-webex-setup`. Use `cisco-thousandeyes-setup` for ThousandEyes data and
`cisco-product-setup` when the Cisco product is not yet known.

## Safety Contract

- Rendering is the only mode and is the default. There is no apply, install,
  execute, device-login, API, or credential mode.
- Never generate a child apply command or a Cisco device mutation. Delegated
  commands are stored as argv arrays and use render/help modes only.
- Reject unknown fields, secret-bearing keys, path traversal, symlinks,
  hard-linked evidence, unowned output directories, and executable artifacts.
- For CMS and Meeting Management, emit a deterministic classifier only for
  compatible plain-TCP handoffs. Their sender profiles may select documented
  TLS, but that selection keeps a blocking SC4S listener/certificate gap and
  suppresses plaintext vendor-port argv. Classifiers must use an exact host,
  exact IP, or unique dedicated port; regex and overlapping selectors are
  invalid.
- Keep the documented syslog destinations fixed: `cisco:ucm` to `ucm`,
  `cisco:tvcs` to `main`, `cisco:ms` to `netops`, and Meeting Management
  `cisco:mm:system:*` plus `cisco:mm:audit` to `netops`.
- Treat call analytics as product-specific normalized data. Do not claim a
  Telephony or VoIP CIM model. Render Authentication or Change mappings only
  when the spec supplies a constrained qualifying search, the conservative
  field set, and hashed local evidence. Keep the operator query outside the
  rendered bundle; persist only its SHA-256, structural review result, fixed
  route/field allowlist, and a non-identifying `head 0` skeleton.
- Dashboard SPL must project `fields _time collaboration_route`, explicitly
  run `fields - _raw` as the final pre-aggregation step, and then aggregate.
  `_time` survives for `timechart`; no raw or hashed identifiers are retained
  or displayed.
- The private packet necessarily retains reviewed operational routing
  identifiers: project/environment/owner, restricted role, exact host/IP
  selectors, indexes/source types, and its marker-bound output path. The
  no-event-identifier boundary applies to evidence values and dashboard/CIM
  output, not those routing coordinates. Source spec names are never persisted.
  Every intake string and the resolved output/derived child path are screened
  for email, private-key, bearer, and a finite set of AWS, GitHub, Slack, JWT,
  OpenAI, and Google API credential shapes before any write. UUID-like HEC or
  client-secret strings remain allowed because their shape is indistinguishable
  from legitimate operational identifiers; this is not universal secret
  detection.
- Treat Splunkbase apps 669, 4434, 4640, 8413, 8592, and 8593 as optional
  Sideview partner packages, never Splunk-owned official TAs. Do not emit
  install commands; require exact version, tier, entitlement, and package
  metadata evidence before recording a selection.

## Render and Validate

Render the example spec offline:

```bash
bash skills/cisco-collaboration-setup/scripts/setup.sh \
  --spec skills/cisco-collaboration-setup/template.example
```

Preview without writing:

```bash
bash skills/cisco-collaboration-setup/scripts/setup.sh \
  --spec skills/cisco-collaboration-setup/template.example \
  --dry-run --json
```

Validate the rendered packet without contacting Splunk, SC4S, or Cisco:

```bash
bash skills/cisco-collaboration-setup/scripts/validate.sh
```

Bare validation proves current structure, private ownership/modes, fixed
registries, and consistency with the renderer-created unkeyed marker
commitments. It does not authenticate historical provenance. If the packet
contains CDR/CMR local qualification, CIM evidence, partner evidence, or CMM
operator-attested evidence, validation fails closed until an externally trusted
spec is supplied and its bound evidence is re-read:

```bash
bash skills/cisco-collaboration-setup/scripts/validate.sh \
  --spec /private/operator-owned/collaboration-spec.yaml \
  --expected-spec-sha256 <externally-recorded-sha256>
```

The optional digest is an external trust anchor. Because the bundle and its
unkeyed SHA-256 marker are owner-rewritable, a coherent same-owner rewrite is
outside bare `validate.sh` authenticity guarantees. Trusted-spec mode strictly
re-parses the spec, verifies its digest, re-reads bound evidence, and compares
every rendered projection deterministically.

With no arguments, `setup.sh` renders `template.example` to the repository's
`cisco-collaboration-rendered/` child directory. Review `readiness/`,
`privacy/`, `sc4s/`, `evidence/`, `gaps/`, and `handoffs/` before any operator
uses a child workflow.

The renderer refuses an existing bundle by default. After reviewing it, use
`--replace-existing` to publish a fully validated private sibling stage and
preserve the prior output under a sibling backup name. The backup marker stays
bound to the original target path, so the backup is intentionally not a valid
bundle while it has the backup name. It is a
recoverable replacement under a private target lock, not a claim of gap-free
atomic replacement. It never clears an owned tree in place or deletes that
backup.

For reviewed recovery, stop concurrent renderers, verify that the exact target
is absent and its sibling lock is absent, verify the recorded backup is a
current-user-owned `0700` real directory, rename that exact backup to the
original target path, and run `validate.sh --output-dir <original-target>`.
If the restored packet carries historical/local evidence, also pass the trusted
original `--spec` and optional externally recorded `--expected-spec-sha256`.
Bare validation is expected to fail for that qualified restore. Never edit the
marker or validate the backup under its temporary sibling name. Replacement
preflight checks only ownership, structure, and marker commitments; it never
reports provenance success for the old packet.

## Product Boundaries

| Product path | Rendered result | Boundary |
|---|---|---|
| CUCM remote-audit-logging syslog | `cisco:ucm` parser readiness plus blocking SC4S listener handoff | UDP/TCP/TLS evidence applies only to remote audit logging; every operator-selected port remains unresolved and does not prove transport support for all `%UC_`/`%CCM_` service syslog |
| CUCM CDR | SFTP billing-server or on-demand SOAP/SFTP evidence packet | No AXL substitution; complete sample evidence required |
| CUCM CMR | Independent flat-file evidence packet | Never infer readiness from CDR evidence |
| CUCM AXL | Configuration-enrichment readiness only | SOAP/XML HTTPS POST to `/axl/`; not realtime CDR collection |
| Expressway | `cisco:tvcs` syslog plus optional INFO CDR and `local2` media checks | Device mode is UDP/514 legacy-BSD or IETF, or TLS/6514 IETF with trust review; SC4S listener capability is separate |
| CMS | TCP or `tls:` sender profile for `cisco:ms` | TLS listener/certificate readiness and XML CDR receiver implementation remain gaps |
| Meeting Management | Independent TCP or TLS 1.2 system/audit profiles | Exact classifier cannot overlap CMS; TLS listener/certificate readiness remains a gap |
| RoomOS | `unsupported_roadmap` evidence packet | Separate Webex and ThousandEyes handoffs only |
| BroadWorks | `unsupported_roadmap` evidence packet | Vendor-document handoff; no local collector claim |
| UCCX/UCCE | `UNKNOWN` evidence packet | No implementation claim |

## Evidence and Package Gates

When CDR or CMR is enabled, the spec must name its exact file type, two header
rows, a local sample file, exact SHA-256, nonzero record count, header fields,
export path, receiver owner, collection evidence, and the origin of the chosen
custom source type. The renderer reads only that local file and never copies
its contents into output.

Optional Sideview selections use `partner_packages.mode: evidence_only`. The
renderer fails when a release, tier, dependency, license/entitlement record,
or Splunk platform claim is unsupported. App 8413 remains non-selectable until
receiver and tier placement are verified; app 4640 remains blocked on Splunk
10.5 because its verified public compatibility stops at 10.4.

## Source Discipline

Read [reference.md](reference.md) for the collection matrix and
[`references/source-ledger.json`](references/source-ledger.json) for the
claim-level ledger. SC4S parser evidence is pinned to commit
`f878a6e8031b07ae8777e97738b27afe735f118d`; human documentation pages are
separately marked mutable and checked on `2026-07-19`.

## Completion Contract

This router can validate only the offline packet. Product routes remain
`partial` until operators complete child collection and prove index,
sourcetype, event-flow, privacy, and dashboard results. Any optional TA or app
must also satisfy the [shared completion gate](../shared/ta_completion_gate.md).
The permanent CMS XML receiver gap and roadmap/UNKNOWN packets must not be
reported as completed onboarding.

## Troubleshooting

| Failure | Meaning | Resolution |
|---|---|---|
| Unknown or secret field | The strict schema rejected an unsafe assumption | Remove it; use only documented non-secret fields |
| CDR/CMR evidence incomplete | Flat-file readiness is not proven | Add a local sample, hash, fields, owner, export path, and collection evidence |
| Classifier overlap | CMS and CMM could be misclassified | Use unique exact sources or dedicated ports above 1023 |
| Output refused | The path is a symlink, unowned, or tampered | Choose an empty dedicated directory or review the existing packet |
| Partner package refused | Version, tier, dependency, entitlement, or platform support is unproven | Keep it disabled and record the residual evidence gap |
