# Ingest Processor Research Ledger

- 2026-05-17: Ingest Processor is a Splunk-hosted service for Splunk Cloud
  Platform Victoria Experience. Provisioning and some first-time setup remain
  support/UI workflows.
- 2026-05-17: Current docs make SPL2 pipelines central to Ingest Processor and
  define runtime profile `ingestProcessor`.
- 2026-05-17: Recent release notes add custom pipeline templates, Automated
  Field Extraction, stats, XML conversion, decrypt, OCSF, index partitioning,
  and PCRE2 migration surfaces.
- 2026-05-17: Destinations are paired Splunk Cloud indexes, Observability
  Cloud, metrics indexes, and Amazon S3. Splunk Enterprise destination routing
  is Edge Processor territory.
- 2026-05-17: Queueing and delivery caveats require explicit operator review,
  especially for branch/route fan-out and blocked destinations.
- 2026-06-17: Cisco Data Fabric/Cisco Live 2026 messaging adds AI-powered data
  management and auto-schematization language around onboarding and pipeline
  management. This skill treats those as UI handoffs and still refuses private
  Data Management CRUD.
- 2026-07-03: Splunk's March 11, 2026 AI-powered Data Management announcement
  labels Automated Field Extraction as Controlled Availability and Guided
  Onboarding with Auto-Schematization as Alpha. The latter can recommend CIM
  mappings and candidate TA or SPL2 outputs, but no stable public API or
  Ingest Processor release-note entry was found. Both remain entitlement-
  checked, human-reviewed UI handoffs; the renderer does not enroll tenants,
  invoke either AI workflow, generate or install TAs, or apply suggestions.
  Although the announcement says three capabilities, it publicly names only
  these two; the skill does not invent a third capability.
- 2026-08-20: Negative evidence re-check of the Ingest Processor release notes
  updated 2026-06-16, keeping Automated Field Extraction at Controlled
  Availability. AFE appears only in the February 18, 2026 entry, "Support for
  Automated Field Extraction (AFE)", which carries no release-stage label and
  repeats the same eight-region limit. The same table does label stages
  explicitly when they apply: the May 18, 2026 entry reads "Data routing to
  Microsoft Azure (Controlled Availability release)" and describes the CA
  gating inline, and the June 29, 2026 entry re-lists the same feature as
  "(General Availability release)". So Splunk tracks a feature through both
  stages in this table, and AFE has received neither label. The page preamble
  groups entries "by the generally available release date", but the May 18
  Controlled Availability entry shows that framing is not a per-entry GA
  assertion, so AFE's presence in the table does not establish GA. Splunk
  still never affirmatively states AFE is generally available, so the
  announcement's Controlled Availability label stands.
- 2026-08-20: Negative evidence re-check of the same release notes updated
  2026-06-16, keeping Guided Onboarding with Auto-Schematization at Alpha.
  The page contains zero occurrences of "Auto-Schematiz", "schematiz", or
  "Guided Onboarding" across every release section from the 2025 entries
  through July 17, 2026. The March 11, 2026 announcement remains the only
  source for this capability. Absence is equally consistent with "still
  Alpha" and with "quietly withdrawn", so the Alpha stance stays and the
  access, enrollment, and human-review gates are unchanged.
